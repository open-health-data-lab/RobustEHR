"""Core value types.

Two invariants govern this module and everything built on it:

1. **The raw string is the only text.** Every layer is an offset-anchored view
   into it. No layer stores a copy of a substring, so any unit at any
   granularity is addressable as ``doc.text[span.start:span.end]`` and every
   operator can emit edits against one coordinate system.

2. **No float ever reaches a control-flow path.** ``0.1 + 0.2 != 0.3`` and
   ``repr(float)`` has changed across CPython releases. Severities are exact
   rationals parsed from string literals; ``k`` is integer arithmetic; rates
   serialize as ``(numerator, denominator)`` pairs.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import IntEnum, StrEnum
from fractions import Fraction

# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, order=True)
class Span:
    """A half-open character range ``[start, end)`` into a document's raw text."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span: [{self.start}, {self.end})")

    def __len__(self) -> int:
        return self.end - self.start

    @property
    def is_empty(self) -> bool:
        return self.start == self.end

    def overlaps(self, other: Span) -> bool:
        """True when the two spans share at least one character.

        Empty spans never overlap anything; a zero-width insertion point sitting
        on a boundary is legal and is ordered by :class:`Anchor` instead.
        """
        if self.is_empty or other.is_empty:
            return False
        return self.start < other.end and other.start < self.end

    def contains(self, other: Span) -> bool:
        return self.start <= other.start and other.end <= self.end

    def strictly_inside(self, other: Span) -> bool:
        """True when this span sits strictly within ``other``, boundaries excluded."""
        return other.start < self.start and self.end < other.end

    def surface(self, text: str) -> str:
        return text[self.start : self.end]

    def shifted(self, delta: int) -> Span:
        return Span(self.start + delta, self.end + delta)


# ---------------------------------------------------------------------------
# Taxonomy axes
# ---------------------------------------------------------------------------


class UnitKind(StrEnum):
    """Eligible-unit types. A unit kind *is* a dose denominator."""

    CHAR = "char"
    LETTER = "letter"
    SPACE_RUN = "space_run"
    PUNCT = "punct"
    TOKEN = "token"
    WORD = "word"
    NUMBER = "number"
    PLACEHOLDER = "placeholder"
    PHRASE = "phrase"
    ASSERTION = "assertion"
    SENTENCE = "sentence"
    LINE = "line"
    LAB_LINE = "lab_line"
    PARAGRAPH = "paragraph"
    LIST_BLOCK = "list_block"
    LIST_ITEM = "list_item"
    HEADER = "header"
    SECTION = "section"
    MENTION = "mention"
    DOCUMENT = "document"


class Channel(StrEnum):
    """The failure mode an operator simulates.

    ``ADVERSARIAL`` is explicit so that model-driven attacks cannot smuggle in a
    clinical-realism claim they do not support.
    """

    RENDER = "render"
    INPUT = "input"
    LEXICAL = "lexical"
    DISCOURSE = "discourse"
    SEMANTIC = "semantic"
    FACTUAL = "factual"
    ADVERSARIAL = "adversarial"
    CONTROL = "control"


class Contract(StrEnum):
    """Declared reference promise, ordered by strength of guarantee.

    The important distinction, and the reason this is a lattice rather than a
    boolean: ``INVARIANT_BY_CONSTRUCTION`` operators can *never* alter clinical
    reference, for any phenotype, in any document, because their edits are
    confined to character classes carrying no clinical content. That is
    discharged by an automated property test (``kappa_op(apply(d)) ==
    kappa_op(d)``), not by assertion. ``CONDITIONALLY_PRESERVING`` operators are
    preserving only when the edit misses clinical evidence, which is a *measured
    rate*, never an assumption.
    """

    CONTROL_NULL = "control_null"
    INVARIANT_BY_CONSTRUCTION = "invariant_by_construction"
    CONDITIONALLY_PRESERVING = "conditionally_preserving"
    REFERENCE_ALTERING_BY_DESIGN = "reference_altering_by_design"
    REFERENCE_UNCONSTRAINED = "reference_unconstrained"
    CONTROL_DESTRUCTIVE = "control_destructive"


class ProtectionClass(StrEnum):
    """Span classes that may be withheld from an operator's eligible set."""

    DEID_PLACEHOLDER = "deid_placeholder"
    DIVIDER_RULE = "divider_rule"
    NUMERIC_VALUE = "numeric_value"
    DECIMAL_POINT = "decimal_point"
    DOSAGE = "dosage"
    SECTION_HEADER = "section_header"
    LIST_MARKER = "list_marker"
    LAB_BLOCK = "lab_block"
    CLINICAL_MENTION = "clinical_mention"
    AMBIGUOUS_MENTION = "ambiguous_mention"
    PHENOTYPE_EVIDENCE = "phenotype_evidence"
    ASSERTION_CUE = "assertion_cue"


class PhenotypeScope(StrEnum):
    """Run-level phenotype mode.

    Phenotype relatedness is an attribute of *where an edit landed*, not a class
    of operator, so this is a property of the run and applies to every operator
    in it.
    """

    AGNOSTIC = "agnostic"
    PROTECT = "protect"
    TARGET = "target"


class TargetMode(StrEnum):
    """Restrict an operator to clinical or non-clinical content."""

    ALL = "all"
    CLINICAL_ONLY = "clinical_only"
    NONCLINICAL_ONLY = "nonclinical_only"


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

_RATE_LITERAL = re.compile(r"^(?:0|1|0?\.[0-9]{1,6}|1\.0{1,6})$")


@dataclass(frozen=True, slots=True)
class RateSeverity:
    """A fraction of the eligible units, parsed exactly from a string literal.

    The literal is retained verbatim so the canonical form is stable across
    platforms. Config loaders must reject severities that arrive as YAML floats;
    see :mod:`robustehr.config`.
    """

    literal: str

    def __post_init__(self) -> None:
        if not _RATE_LITERAL.match(self.literal):
            raise ValueError(
                f"severity must be a quoted decimal literal in [0, 1], got {self.literal!r}"
            )

    @property
    def value(self) -> Fraction:
        try:
            return Fraction(Decimal(self.literal))
        except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
            raise ValueError(f"unparseable severity {self.literal!r}") from exc

    def canon(self) -> str:
        return f"rate:{Decimal(self.literal).normalize():f}"


@dataclass(frozen=True, slots=True)
class CountSeverity:
    """A count of applications per enclosing unit, e.g. 3 duplications/paragraph.

    ``per=DOCUMENT`` is the absolute form: *n* applications in this note, full
    stop. Some corruptions have no honest rate — "duplicate 30% of sections"
    would mean something different in a four-section note than in a twenty, and
    the structural spec asks for 1, 2 or 5 sections precisely because the count
    is the quantity a reader can interpret. Every other ``per`` is a rate in
    disguise and multiplies through the eligible set.
    """

    n: int
    per: UnitKind

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValueError(f"count severity must be non-negative, got {self.n}")

    def canon(self) -> str:
        return f"count:{self.n}:{self.per.value}"


Severity = RateSeverity | CountSeverity


class SubUnitPolicy(StrEnum):
    """How to resolve ``rate * eligible_n < 1``.

    ``CEIL`` is the default. ``FLOOR`` makes low severities a no-op on most
    documents, which manufactures a flat region at the bottom of every
    dose-response curve — the easiest way to publish a wrong figure. ``CEIL``
    inflates the achieved rate instead, which is visible because
    ``dose_inflation`` is reported and every figure plots achieved, not
    requested.
    """

    CEIL = "ceil"
    FLOOR = "floor"
    FLOOR_MIN1 = "floor_min1"


def requested_k(severity: Severity, eligible_n: int, policy: SubUnitPolicy) -> int:
    """Resolve a severity to an integer count. Exact arithmetic only."""
    if isinstance(severity, CountSeverity):
        # Per-document counts are absolute: `count:5` means five applications in
        # this note, not five per eligible unit. `rng.select` caps at the
        # eligible size, so a five-section request on a three-section note
        # applies three and reports `saturated` rather than silently inflating.
        if severity.per is UnitKind.DOCUMENT:
            return severity.n
        return severity.n * eligible_n
    num = severity.value.numerator
    den = severity.value.denominator
    match policy:
        case SubUnitPolicy.CEIL:
            return -((-num * eligible_n) // den)
        case SubUnitPolicy.FLOOR:
            return (num * eligible_n) // den
        case SubUnitPolicy.FLOOR_MIN1:
            floor = (num * eligible_n) // den
            return max(floor, 1) if num > 0 and eligible_n > 0 else floor
    raise AssertionError(f"unhandled policy {policy!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Edits
# ---------------------------------------------------------------------------


class EditKind(StrEnum):
    INSERT = "insert"
    DELETE = "delete"
    REPLACE = "replace"


class Anchor(IntEnum):
    """Which side of a boundary a zero-width insertion binds to."""

    LEFT = 0
    RIGHT = 1


class ReflowPolicy(StrEnum):
    """What an edit is allowed to do to line structure.

    This exists to close a subtle contamination hole. Clinical notes are
    hard-wrapped, so a sentence span usually contains newlines. If a
    sentence-level operator replaces such a span with single-line text it has
    silently *also* applied a structure-flattening corruption, and any claim to
    have isolated that operator's effect is false.

    ``PRESERVE`` (the default) re-wraps the replacement to the note's own wrap
    width and indent; the applier then asserts the line count is unchanged.
    ``FLATTEN`` says the operator means to destroy line structure. ``VERBATIM``
    inserts the replacement as given and is only valid for single-line spans.
    """

    PRESERVE = "preserve"
    FLATTEN = "flatten"
    VERBATIM = "verbatim"


def _edit_digest(
    *,
    op_id: str,
    start: int,
    end: int,
    unit_id: str,
    rank: int,
    replacement: str,
    copy_from: str = "",
) -> str:
    material = "\x1f".join(
        [op_id, str(start), str(end), unit_id, str(rank), replacement, copy_from]
    )
    return hashlib.blake2b(material.encode("utf-8"), digest_size=8).hexdigest()


@dataclass(frozen=True, slots=True)
class Edit:
    """An immutable proposal to replace ``[start, end)`` with ``replacement``.

    Operators are pure proposers: they never mutate text, never observe each
    other's output, and never sample. All offsets are into the *stage input*
    text, which for a single-stage recipe is the original note.
    """

    start: int
    end: int
    replacement: str
    op_id: str
    unit_id: str
    rank: int = 0
    op_priority: int = 0
    anchor: Anchor = Anchor.LEFT
    reflow: ReflowPolicy = ReflowPolicy.PRESERVE
    group_id: str | None = None
    copy_from: Span | None = None
    """Source range to copy, when the replacement IS text already in the note.

    The mechanism that keeps a duplication operator redistributable. A section
    duplicate replaces nothing and inserts a few thousand characters of the
    note — put in :attr:`replacement`, that would write clinical text into the
    edit script and destroy the one property that makes edit scripts shareable
    when the corpus is not (`store.MAX_REPLACEMENT_CHARS` enforces this, and is
    right to reject it).

    So the edit says *where to copy from* instead, in the same coordinate system
    as everything else, and the applier resolves it against the stage input. The
    stored row carries two integers. Replay is unchanged: the same source text
    plus the same offsets gives the same bytes.
    """
    targets: frozenset[ProtectionClass] = frozenset()
    # Provenance only (rule name, dictionary key, original surface). Excluded
    # from equality and hashing so that edits stay usable in sets: identity is
    # already fully determined by the fields feeding `edit_id`.
    meta: Mapping[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid edit range [{self.start}, {self.end})")
        if self.is_noop:
            raise ValueError(f"{self.op_id}: edit is a no-op at offset {self.start}")

    @property
    def span(self) -> Span:
        return Span(self.start, self.end)

    @property
    def is_noop(self) -> bool:
        return self.start == self.end and not self.replacement and self.copy_from is None

    def text_for(self, source: str) -> str:
        """The replacement, resolving :attr:`copy_from` against the stage input."""
        if self.copy_from is None:
            return self.replacement
        return self.copy_from.surface(source) + self.replacement

    @property
    def kind(self) -> EditKind:
        if self.start == self.end:
            return EditKind.INSERT
        if not self.replacement:
            return EditKind.DELETE
        return EditKind.REPLACE

    @property
    def edit_id(self) -> str:
        return _edit_digest(
            op_id=self.op_id,
            start=self.start,
            end=self.end,
            unit_id=self.unit_id,
            rank=self.rank,
            replacement=self.replacement,
            copy_from=(
                "" if self.copy_from is None else f"{self.copy_from.start}:{self.copy_from.end}"
            ),
        )

    @property
    def sort_key(self) -> tuple[int, int, int, str, int, str]:
        """The one canonical total order.

        At a shared offset ``p``: LEFT insertions first (in key order), then the
        replacement or deletion covering ``[p, q)``, then RIGHT insertions. The
        trailing ``edit_id`` keeps the order total even if an operator emits two
        otherwise-identical edits.
        """
        if self.start != self.end:
            slot = 1  # the replacement or deletion covering [start, end)
        elif self.anchor is Anchor.LEFT:
            slot = 0  # insertions binding to the character on the left
        else:
            slot = 2  # insertions binding to the character on the right
        return (self.start, slot, self.op_priority, self.op_id, self.rank, self.edit_id)

    def conflicts_with(self, other: Edit) -> bool:
        """True when two edits cannot both be applied.

        Overlap is only defined between edits of non-zero length. A pure
        insertion conflicts with a replacement only when it lands *strictly*
        inside it; at the boundaries it is legal and ordered by ``anchor``.
        """
        a, b = self.span, other.span
        if a.is_empty and b.is_empty:
            return False
        if a.is_empty:
            return a.start > b.start and a.start < b.end
        if b.is_empty:
            return b.start > a.start and b.start < a.end
        return a.overlaps(b)


@dataclass(frozen=True, slots=True)
class Unit:
    """An eligible unit reported by an operator.

    ``unit_id`` must be content-addressed and stable — the framework derives the
    selection key from it, so a segmenter change that inserts one sentence
    should change that sentence's fate and nothing else.
    """

    unit_id: str
    kind: UnitKind
    span: Span
    # Operator-specific detail (the Header object, the matched rule, ...).
    # Excluded from equality and hashing: `unit_id` is content-addressed, so it
    # already identifies the unit, and units must remain set-usable.
    payload: Mapping[str, object] = field(default_factory=dict, compare=False)


def make_unit_id(kind: UnitKind, span: Span) -> str:
    return f"{kind.value}:{span.start}:{span.end}"


__all__ = [
    "Anchor",
    "Channel",
    "Contract",
    "CountSeverity",
    "Edit",
    "EditKind",
    "PhenotypeScope",
    "ProtectionClass",
    "RateSeverity",
    "ReflowPolicy",
    "Severity",
    "Span",
    "SubUnitPolicy",
    "TargetMode",
    "Unit",
    "UnitKind",
    "make_unit_id",
    "requested_k",
]
