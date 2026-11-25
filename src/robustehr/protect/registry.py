"""Protected spans, and the rule that decides who may edit what.

Protection is not global. A span is protected *relative to an operator*: each
operator declares the protection classes it targets, and may edit only those.
``render.deid_restyle`` exists precisely to rewrite de-identification masks, so
it declares ``DEID_PLACEHOLDER`` and everything else stays off limits; an
unrelated character-level operator declares nothing and cannot touch a mask at
all.

Getting this wrong turns a preserving operator into a factual error. Deleting a
period from ``8.0`` yields ``80`` — a tenfold change in a lab value, produced by
an operator whose contract claims it preserves clinical reference. Numeric
values are therefore protected by default, and only an operator that says it is
perturbing numbers can reach them.

The registry is also what keeps the denominator honest. Every operator reports
``protected_n`` alongside ``eligible_n``, so a reader can see how much of a
document was withheld rather than inferring it from a rate that looks low.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

from robustehr.resources import load_yaml
from robustehr.segment.patterns import ALPHA, DIGIT, HSPACE
from robustehr.segment.tokens import TokenKind
from robustehr.types import ProtectionClass, Span


class Strength(StrEnum):
    """How absolute a protection is."""

    HARD = "hard"
    """Atomic: may be replaced whole, never edited internally.

    Reserved for spans where a *partial* edit fabricates content that was never
    in the record. A de-identification mask is the case that matters: replacing
    ``___`` with ``[**Name**]`` wholesale is a legitimate restyling, but
    deleting one of its underscores or inserting a typo inside it produces
    PHI-shaped text that no operator contract justifies.

    So the rule is not "nobody may touch this" — that would block the restyler,
    which is the whole reason the class exists — but "nobody may touch *part* of
    this".
    """
    SOFT = "soft"
    """Editable, in whole or in part, by an operator declaring this class."""


@dataclass(frozen=True, slots=True)
class ProtectedSpan:
    span: Span
    cls: ProtectionClass
    strength: Strength
    reason: str
    """Human-readable, surfaced in the audit log when an edit is refused."""


@dataclass(frozen=True, slots=True)
class ProtectionIndex:
    spans: tuple[ProtectedSpan, ...]
    starts: tuple[int, ...]

    def _window(self, span: Span) -> tuple[int, int]:
        lo = bisect_right(self.starts, span.start) - 1
        return max(lo - 1, 0), bisect_right(self.starts, span.end)

    def covering(self, span: Span) -> tuple[ProtectedSpan, ...]:
        lo, hi = self._window(span)
        return tuple(p for p in self.spans[lo:hi] if p.span.overlaps(span))

    def _refuses(
        self, protected: ProtectedSpan, span: Span, targets: frozenset[ProtectionClass]
    ) -> bool:
        if protected.cls not in targets:
            return True
        # Targeted, but HARD spans admit only whole replacement.
        return protected.strength is Strength.HARD and not span.contains(protected.span)

    def blocks(self, span: Span, targets: frozenset[ProtectionClass] = frozenset()) -> bool:
        """Is this span off limits to an operator declaring ``targets``?"""
        return any(self._refuses(p, span, targets) for p in self.covering(span))

    def blocking(
        self, span: Span, targets: frozenset[ProtectionClass] = frozenset()
    ) -> tuple[ProtectedSpan, ...]:
        """The specific protections that refuse an edit, for the audit trail."""
        return tuple(p for p in self.covering(span) if self._refuses(p, span, targets))

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for protected in self.spans:
            counts[protected.cls.value] = counts.get(protected.cls.value, 0) + 1
        return counts

    def of_class(self, *classes: ProtectionClass) -> tuple[ProtectedSpan, ...]:
        wanted = set(classes)
        return tuple(p for p in self.spans if p.cls in wanted)

    def __len__(self) -> int:
        return len(self.spans)


def build_index(spans: list[ProtectedSpan]) -> ProtectionIndex:
    ordered = tuple(sorted(spans, key=lambda p: (p.span.start, p.span.end, p.cls.value)))
    return ProtectionIndex(ordered, tuple(p.span.start for p in ordered))


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

PROTECTION_RESOURCE = "protection.yaml"


@lru_cache(maxsize=1)
def load_units() -> frozenset[str]:
    """Units of measure that bind an adjacent number into a dosage.

    Lives in a hashed resource rather than in code: it is data, it will grow as
    corpora from other systems arrive, and its content hash belongs in the
    version of every operator that consults it.
    """
    raw: dict[str, Any] = load_yaml(PROTECTION_RESOURCE)
    return frozenset(str(unit).lower() for group in raw["units"].values() for unit in group)


# Horizontal whitespace only: a value and its unit share a line, and `\s` is
# Unicode-database dependent, which would make the same note yield different
# protected spans on two CPython point releases.
_NUMBER_UNIT = re.compile(
    rf"(?P<value>[{DIGIT}]+(?:\.[{DIGIT}]+)?)[{HSPACE}]?(?P<unit>[{ALPHA}]+(?:/[{ALPHA}]+)?|%)"
)


def _normalized_unit(raw: str) -> str:
    return "".join(ch for ch in raw.lower() if ch in "abcdefghijklmnopqrstuvwxyz")


def protect_document(doc) -> ProtectionIndex:  # type: ignore[no-untyped-def]
    """Derive every protected span from a :class:`~robustehr.document.Document`.

    Clinical-concept and phenotype-evidence classes are added later by the
    concept layer; this covers everything that is derivable from structure
    alone, which is what a ``phenotype_scope: agnostic`` run needs.
    """
    found: list[ProtectedSpan] = []

    # De-identification masks are HARD. Perturbing one fabricates PHI-shaped
    # text that was never in the record, and no operator contract justifies
    # that except the restyler, which replaces the mask wholesale rather than
    # editing inside it.
    for placeholder in doc.deid.placeholders:
        found.append(
            ProtectedSpan(
                placeholder.span,
                ProtectionClass.DEID_PLACEHOLDER,
                Strength.HARD,
                "de-identification mask",
            )
        )
    for divider in doc.deid.dividers:
        found.append(
            ProtectedSpan(
                divider, ProtectionClass.DIVIDER_RULE, Strength.SOFT, "ASCII divider rule"
            )
        )

    # Numbers. Deleting the period from "8.0" gives "80": a tenfold change in a
    # lab value from an operator claiming to preserve reference.
    for token in doc.tokens:
        if token.kind is TokenKind.NUMBER:
            found.append(
                ProtectedSpan(
                    token.span, ProtectionClass.NUMERIC_VALUE, Strength.SOFT, "numeric value"
                )
            )

    # Dosages: a number bound to a unit is a stronger claim than a bare number,
    # and is what a medication operator needs to see as one thing.
    for match in _NUMBER_UNIT.finditer(doc.text):
        if _normalized_unit(match.group("unit")) in load_units() or match.group("unit") == "%":
            found.append(
                ProtectedSpan(
                    Span(*match.span()),
                    ProtectionClass.DOSAGE,
                    Strength.SOFT,
                    f"dosage or measurement: {match.group()!r}",
                )
            )

    for header in doc.headers:
        found.append(
            ProtectedSpan(
                header.span, ProtectionClass.SECTION_HEADER, Strength.SOFT, "section header"
            )
        )

    for block in doc.lists:
        for item in block.items:
            found.append(
                ProtectedSpan(
                    item.marker, ProtectionClass.LIST_MARKER, Strength.SOFT, "list marker"
                )
            )

    for block in doc.aligned:
        found.append(
            ProtectedSpan(
                block.span,
                ProtectionClass.LAB_BLOCK,
                Strength.SOFT,
                f"{block.style.value} block"
                + ("" if block.self_labelling else ", position-dependent"),
            )
        )

    return build_index(found)


__all__ = [
    "PROTECTION_RESOURCE",
    "ProtectedSpan",
    "ProtectionIndex",
    "Strength",
    "build_index",
    "load_units",
    "protect_document",
]
