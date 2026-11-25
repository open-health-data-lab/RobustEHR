"""De-identification masks, across conventions, plus ASCII divider rules.

Every corpus masks PHI differently, and the differences are not cosmetic — a
model trained on one convention has partly learned that convention rather than
clinical language. That makes cross-scheme restyling one of the most useful
perturbations the package offers, and it means the layer cannot hard-code a
single pattern.

Conventions handled, all observed in real corpora:

===================  ==========================  ==============================
Scheme               Example                     Seen in
===================  ==========================  ==============================
``underscore_run``   ``___``                     MIMIC-IV
``bracket_star``     ``[**Known lastname 12**]``  MIMIC-III, i2b2 lineage
``angle_tag``        ``<PATIENT_NAME>``          UK CRIS and similar
``square_tag``       ``[NOM]``, ``[REDACTED]``   many European and Canadian sites
``xxx_run``          ``XXXXX``                   legacy mainframe exports
``asterisk_run``     ``***``                     Epic smart-phrase placeholders
``curly_tag``        ``{{PATIENT}}``             structured/templated exports
``none``             —                           nursing flowsheets, some notes
===================  ==========================  ==============================

Two properties matter downstream:

* **Typed schemes carry a label the untyped ones throw away.** ``<GP_NAME>``
  says *what* was masked; ``___`` does not. Recording ``type_label`` lets a
  restyling operator be honest about direction: typed → untyped is lossy,
  untyped → typed has to invent, and both facts belong in the dose record.
* **Masks are atomic and protected by default.** Perturbing one fabricates
  PHI-shaped text and breaks any model that learned the corpus convention.

Separately, a run of four or more underscores is a horizontal *rule* — layout,
not content. A lazy ``_+`` regex conflates the two, which is how you end up
protecting formatting while corrupting PHI masks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from robustehr.types import Span


class DeidScheme(StrEnum):
    UNDERSCORE_RUN = "underscore_run"
    BRACKET_STAR = "bracket_star"
    ANGLE_TAG = "angle_tag"
    SQUARE_TAG = "square_tag"
    XXX_RUN = "xxx_run"
    ASTERISK_RUN = "asterisk_run"
    CURLY_TAG = "curly_tag"
    NONE = "none"

    @property
    def is_typed(self) -> bool:
        """Does the mask carry a label saying what was removed?"""
        return self in {
            DeidScheme.BRACKET_STAR,
            DeidScheme.ANGLE_TAG,
            DeidScheme.SQUARE_TAG,
            DeidScheme.CURLY_TAG,
        }


# Ordered most specific first: `[**...**]` must be claimed before `[TAG]` could
# see part of it, and `{{...}}` before any brace heuristic.
SCHEME_PATTERNS: tuple[tuple[DeidScheme, re.Pattern[str]], ...] = (
    (DeidScheme.BRACKET_STAR, re.compile(r"\[\*\*(?P<label>[^\]]*?)\*\*\]")),
    (DeidScheme.CURLY_TAG, re.compile(r"\{\{(?P<label>[^{}]*)\}\}")),
    # Labels must be at least two characters. A one-character bracket is
    # pick-list residue, not a mask: templated forms are full of `[X]` and
    # `[ ]` checkboxes, and treating those as PHI would protect checkboxes
    # while leaving the note's actual masks exposed.
    (DeidScheme.ANGLE_TAG, re.compile(r"<(?P<label>[A-Z][A-Z0-9_ -]+)>")),
    (DeidScheme.SQUARE_TAG, re.compile(r"\[(?P<label>[A-Z][A-Z0-9_ -]+)\]")),
    (DeidScheme.UNDERSCORE_RUN, re.compile(r"(?<!_)(?P<label>_{3})(?!_)")),
    (DeidScheme.ASTERISK_RUN, re.compile(r"(?<!\*)(?P<label>\*{3,})(?!\*)")),
    # Bounded so that ordinary words in an all-caps note are not swallowed.
    (DeidScheme.XXX_RUN, re.compile(r"(?<![A-WYZ])(?P<label>X{2,})(?![A-WYZ])")),
)

_SCHEME_BY_NAME = {scheme.value: scheme for scheme, _ in SCHEME_PATTERNS}

#: Four or more underscores: an ASCII horizontal rule, in any scheme.
DIVIDER_RE = re.compile(r"_{4,}")

#: The canonical untyped mask, kept for callers that need a literal.
PLACEHOLDER = "___"


@dataclass(frozen=True, slots=True)
class Placeholder:
    span: Span
    scheme: DeidScheme
    type_label: str | None
    """What the mask says was removed, for typed schemes. ``None`` otherwise."""

    def surface(self, text: str) -> str:
        return self.span.surface(text)


@dataclass(frozen=True, slots=True)
class DeidIndex:
    """Offset-anchored index of masks and rules in one document."""

    scheme: DeidScheme
    placeholders: tuple[Placeholder, ...]
    dividers: tuple[Span, ...]
    scheme_counts: dict[str, int]
    """Match counts for every scheme, so a mixed-convention note is visible."""

    @property
    def count(self) -> int:
        return len(self.placeholders)

    @property
    def spans(self) -> tuple[Span, ...]:
        return tuple(p.span for p in self.placeholders)

    @property
    def is_typed(self) -> bool:
        return self.scheme.is_typed

    def is_placeholder_at(self, index: int) -> bool:
        return any(p.span.start <= index < p.span.end for p in self.placeholders)

    def covering(self, span: Span) -> tuple[Placeholder, ...]:
        return tuple(p for p in self.placeholders if p.span.overlaps(span))

    def density_per_1k_chars(self, text_len: int) -> tuple[int, int]:
        """Masks per 1,000 characters, as an exact ``(num, den)`` pair."""
        if text_len == 0:
            return (0, 1)
        return (len(self.placeholders) * 1000, text_len)


def scheme_counts(text: str) -> dict[str, int]:
    """Match count per scheme, with more specific schemes claiming first.

    Regions already claimed by a more specific pattern are masked out before the
    next is tried, so ``[**Known lastname**]`` is not also counted as a square
    tag and ``{{PATIENT}}`` is not double-counted.
    """
    remaining = text
    counts: dict[str, int] = {}
    for scheme, pattern in SCHEME_PATTERNS:
        matches = list(pattern.finditer(remaining))
        counts[scheme.value] = len(matches)
        if matches:
            # Blank out claimed regions with a character that no pattern uses.
            chars = list(remaining)
            for match in matches:
                for i in range(*match.span()):
                    chars[i] = "\x00"
            remaining = "".join(chars)
    return counts


def detect_scheme(text: str) -> DeidScheme:
    """Pick the dominant masking convention, or ``NONE``.

    Ties break toward the more specific scheme, which is the order in
    ``SCHEME_PATTERNS``. A note with no masks at all — a nursing flowsheet, an
    un-de-identified record — returns ``NONE`` rather than guessing.
    """
    counts = scheme_counts(text)
    best = DeidScheme.NONE
    best_count = 0
    for scheme, _pattern in SCHEME_PATTERNS:
        count = counts[scheme.value]
        if count > best_count:
            best, best_count = scheme, count
    return best


def index_deid(text: str, scheme: DeidScheme | None = None) -> DeidIndex:
    """Locate masks and divider rules, keeping them distinct.

    ``scheme`` may be pinned when the corpus convention is known; otherwise it
    is detected from the text. Detection is a pure function of the document, so
    it stays deterministic.
    """
    counts = scheme_counts(text)
    resolved = scheme if scheme is not None else detect_scheme(text)

    placeholders: tuple[Placeholder, ...] = ()
    if resolved is not DeidScheme.NONE:
        pattern = dict(SCHEME_PATTERNS)[resolved]
        placeholders = tuple(
            Placeholder(
                span=Span(*match.span()),
                scheme=resolved,
                type_label=match.group("label").strip() if resolved.is_typed else None,
            )
            for match in pattern.finditer(text)
        )

    dividers = tuple(Span(*m.span()) for m in DIVIDER_RE.finditer(text))
    return DeidIndex(
        scheme=resolved,
        placeholders=placeholders,
        dividers=dividers,
        scheme_counts=counts,
    )


def scheme_from_name(name: str) -> DeidScheme:
    if name == DeidScheme.NONE.value:
        return DeidScheme.NONE
    if name not in _SCHEME_BY_NAME:
        raise ValueError(f"unknown de-identification scheme {name!r}")
    return _SCHEME_BY_NAME[name]


def strip_placeholders(text: str, replacement: str = " ") -> str:
    """Blank out masks for measurement purposes only.

    **Length-preserving**: each masked character becomes one ``replacement``
    character, so offsets into the result still line up with the original. That
    matters because the estimators using this — abbreviation density, suspected
    misspelling rate, token counts — also report spans.

    Used only to stop masks being counted as clinical tokens. Never used to
    produce output text.
    """
    index = index_deid(text)
    if index.scheme is DeidScheme.NONE:
        return text
    chars = list(text)
    for placeholder in index.placeholders:
        for i in range(placeholder.span.start, placeholder.span.end):
            chars[i] = replacement
    return "".join(chars)


__all__ = [
    "DIVIDER_RE",
    "PLACEHOLDER",
    "SCHEME_PATTERNS",
    "DeidIndex",
    "DeidScheme",
    "Placeholder",
    "detect_scheme",
    "index_deid",
    "scheme_counts",
    "scheme_from_name",
    "strip_placeholders",
]
