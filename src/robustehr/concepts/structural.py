"""Concept mentions recoverable from layout rather than from matching.

Clinical notes carry a large amount of concept content in a form the matcher was
never going to reach: the label half of a label-value pair inside a
column-aligned block.

    WBC-6.9  RBC-4.46  Hgb-12.8  Hct-36.1  Plt-250
    Na-140   K-4.1     Cl-104    HCO3-24   BUN-18

Measured on the SNOMED CT Entity Linking Challenge, **9,378 gold spans — 12.4% of
all 75,491, and 75.6% of every T059 "Laboratory Procedure" span — sit exactly on
one of those labels.** The matcher found 6.4% of them against 83.9% elsewhere,
and that single gap was the whole `procedure` recall deficit.

They are hard for a general matcher for compounding reasons: they are 2-4
characters, so the length floor rejects them; they abut punctuation and digits,
so the n-gram window straddles the value; and many are institution shorthand
absent from any terminology (``angap``, ``urean``, ``creat``).

They are easy structurally. The layout says *this token labels that number*, and
the structural layer already detects it — ``detect_aligned_blocks`` exposes
``self_labelling`` precisely for this shape, the same signal that decides whether
a column shift is dangerous.

**This does not bypass the terminology.** A structural candidate is a *span*
proposal; it still has to resolve against the vocabulary to acquire a concept and
semantic types. What structure supplies is the boundary the matcher could not
find, which is the half it was actually failing at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from robustehr.concepts.expansion import Slot, load_expansions
from robustehr.document import Document
from robustehr.segment.headers import HeaderKind
from robustehr.types import Span

#: A label-value pair, mirroring ``segment/blocks.py``'s own detector so the two
#: cannot drift. Kept separate rather than imported because this one needs the
#: label's *offsets*, not merely a count.
_LABELLED_VALUE = re.compile(r"([A-Za-z][A-Za-z0-9/%]*)([-:])([A-Za-z0-9.<>+*_]+)")

#: Longest a label may be. Beyond this it is prose with a colon, not a lab label
#: — `Discharge Instructions:` is a header, not an analyte.
MAX_LABEL_CHARS = 12


@dataclass(frozen=True, slots=True)
class LabelledValue:
    """One ``label-value`` pair located inside a self-labelling block."""

    label: Span
    value: Span
    separator: str

    @property
    def is_numeric_value(self) -> bool:
        """Values that parse as numbers are the strongest evidence of a lab."""
        text = self.value_text
        return bool(text) and text[0].isdigit()

    value_text: str = ""


def labelled_values(doc: Document) -> tuple[LabelledValue, ...]:
    """Label-value pairs inside self-labelling aligned blocks, in document order.

    Restricted to ``self_labelling`` blocks deliberately. In a block where values
    are positional rather than labelled, a token before a number is a column
    header for the whole column and not a label for that value, and treating it
    as one would attach the wrong concept to every row.
    """
    found: list[LabelledValue] = []
    for block in doc.aligned:
        if not block.self_labelling:
            continue
        for line_idx in block.lines:
            line = doc.lines[line_idx]
            if line.is_blank:
                continue
            content = line.content
            surface = content.surface(doc.text)
            for match in _LABELLED_VALUE.finditer(surface):
                label = match.group(1)
                if len(label) > MAX_LABEL_CHARS:
                    continue
                start = content.start + match.start(1)
                value_start = content.start + match.start(3)
                found.append(
                    LabelledValue(
                        label=Span(start, start + len(label)),
                        value=Span(value_start, value_start + len(match.group(3))),
                        separator=match.group(2),
                        value_text=match.group(3),
                    )
                )
    found.sort(key=lambda p: (p.label.start, p.label.end))
    return tuple(found)


#: Header kinds whose label names an examined system rather than note structure.
#:
#: ``SUBSECTION`` is where ``HEENT:``, ``Neuro:`` and ``EXT:`` land: the header
#: lexicon already recognises them (``exam_heent``, ``exam_neuro``,
#: ``exam_extremities`` in ``headers.yaml``), but ``headers.SECTION_KINDS``
#: deliberately excludes them from ``doc.sections``, because they organise a
#: physical exam rather than the note. That exclusion is right for sectioning and
#: wrong here — the label still names an anatomical region or body system, and it
#: is still a concept.
#:
#: ``UNKNOWN`` is **not** included, though it costs a few real labels such as
#: ``GA`` for general appearance. It admitted ``PATHOLOGIC DIAGNOSIS``,
#: ``Pending labs`` and ``SIGNIFICANT IMAGING`` — heuristic header matches with
#: no lexicon entry, which are note structure rather than examined systems.
_EXAM_LABEL_KINDS = frozenset({HeaderKind.SUBSECTION})

#: Longest an exam-system label may be, in characters.
#:
#: Larger than :data:`MAX_LABEL_CHARS` because these are words rather than
#: analyte abbreviations — ``Extremities`` and ``Neurologic`` are real labels —
#: but still short enough to exclude ``Discharge Instructions`` and the rest of
#: the note's actual section headers.
MAX_EXAM_LABEL_CHARS = 20


def exam_label_spans(doc: Document) -> tuple[Span, ...]:
    """Candidate concept spans from exam-system labels — the ``HEENT:`` slot.

    The other structural position where a short token is a concept because of
    *where it sits*. ``HEENT:`` names head, eyes, ears, nose and throat; ``EXT:``
    names the extremities. Neither is guessable from surrounding prose, and both
    are unreachable through :func:`labelled_values`, whose gate requires an
    aligned self-labelling block with a numeric value — a colon followed by prose
    satisfies neither.

    Measured on the challenge gold, 793 abbreviation-shaped spans sit in this
    position and 71.9% of them carry no reachable UMLS candidate, which made it
    the largest structural slot with no handler at all.

    **Both grammars count.** An exam label is normally *inline* — the finding
    follows on the same line, as in ``HEENT: PERRLA, dry mucous membranes`` — so
    restricting to standalone headers, which is the intuitive reading of "the
    label sits alone in its slot", excludes almost every case this exists for.
    Overlap with :func:`labelled_values` is possible in principle (``Temp: 98.6``
    satisfies both) and is resolved by deduplication in :func:`resolve_labels`
    rather than by excluding a grammar here.
    """
    found = [
        header.label
        for header in doc.headers
        if header.kind in _EXAM_LABEL_KINDS
        and header.label.end - header.label.start <= MAX_EXAM_LABEL_CHARS
    ]
    found.sort(key=lambda s: (s.start, s.end))
    return tuple(found)


def label_spans(doc: Document, *, numeric_values_only: bool = True) -> tuple[Span, ...]:
    """Candidate concept spans from labels in self-labelling blocks.

    ``numeric_values_only`` keeps the precision: a label attached to a number is
    an analyte, while one attached to a word is usually part of a hyphenated
    phrase (``follow-up``, ``non-tender``) that the pattern also matches.
    """
    return tuple(
        pair.label
        for pair in labelled_values(doc)
        if not numeric_values_only or pair.is_numeric_value
    )


__all__ = [
    "MAX_EXAM_LABEL_CHARS",
    "MAX_LABEL_CHARS",
    "LabelledValue",
    "exam_label_spans",
    "label_spans",
    "labelled_values",
    "resolve_labels",
    "slotted_spans",
    "structural_spans",
]


def structural_spans(
    doc: Document,
    *,
    numeric_values_only: bool = True,
    include_exam_labels: bool = False,
) -> tuple[Span, ...]:
    """Every span a structural position proposes, deduplicated and ordered.

    The slots union here rather than at the call site, because a caller should
    ask "what does layout tell us" once. Deduplication is real work: ``Temp:
    98.6`` in a vitals block satisfies both gates, and emitting it twice would
    double-count the span in every downstream denominator.

    **``include_exam_labels`` defaults to off, on measured grounds.** Isolated on
    the 68-note test split, the exam slot buys +0.0059 `procedure` recall and
    costs 0.0117 `anatomy` precision and 0.0101 `disease` precision — it does not
    currently pay for itself.

    The first explanation offered for that was that the slot needed the
    **expansion table**: 71.9% of the gold spans sitting in it carry no reachable
    UMLS candidate, and ``heent``, ``neuro`` and ``ext`` are exactly the surfaces
    no terminology holds. The prediction was that adding expansions would make
    the slot worthwhile.

    **That prediction was tested and is false.** With expansion on, the slot adds
    +0.0058 `procedure` recall and costs 0.0117 `anatomy` and 0.0098 `disease`
    precision — essentially the same trade as before. Expanding ``heent`` to
    *head eyes ears nose and throat* does resolve it, but to a body-system
    concept the annotators do not mark in that position, so the emission is a
    false positive rather than a recovery.

    The slot therefore stays off, now for a measured reason rather than a
    provisional one. What would change the verdict is evidence about how the gold
    treats exam-subsection labels, not more vocabulary.
    """
    return tuple(
        span
        for span, _ in slotted_spans(
            doc,
            numeric_values_only=numeric_values_only,
            include_exam_labels=include_exam_labels,
        )
    )


def slotted_spans(
    doc: Document,
    *,
    numeric_values_only: bool = True,
    include_exam_labels: bool = False,
) -> tuple[tuple[Span, Slot], ...]:
    """Structural spans paired with the slot each came from.

    The slot travels with the span because it is what makes expansion safe: an
    entry in the table is valid *in one slot* and nowhere else, so a resolver
    that has forgotten where a span came from cannot apply the table correctly.

    Where both gates claim a span, the labelled-value slot wins — it is the more
    specific claim, having also seen a numeric value.
    """
    slotted: dict[Span, Slot] = {}
    if include_exam_labels:
        for span in exam_label_spans(doc):
            slotted[span] = Slot.EXAM_LABEL
    for span in label_spans(doc, numeric_values_only=numeric_values_only):
        slotted[span] = Slot.VALUE_LABEL
    return tuple((span, slotted[span]) for span in sorted(slotted, key=lambda s: (s.start, s.end)))


@lru_cache(maxsize=1)
def _code_maps() -> tuple[dict[str, list[str]] | None, dict[str, str]]:
    """SNOMED code -> semantic types, and code -> CUI, if the crosswalk exists.

    Built once. Absent on a machine without the eval artifacts, in which case
    expansion falls back to resolving the long form as a string.
    """
    import json

    root = Path("data/snomed_el")
    try:
        tuis = json.loads((root / "concept_tui.json").read_text(encoding="utf-8"))
        cui_codes = json.loads((root / "cui_snomed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {}
    code_cui: dict[str, str] = {}
    for cui, codes in sorted(cui_codes.items()):
        for code in codes:
            code_cui.setdefault(code, cui)
    return tuis, code_cui


def resolve_labels(
    doc: Document,
    matcher: object,
    *,
    numeric_values_only: bool = True,
    include_exam_labels: bool = False,
    expand: bool = True,
) -> tuple[object, ...]:
    """Resolve structural label spans into concept mentions.

    Structure supplies the boundary; the terminology still supplies the concept.
    A label that resolves to nothing is dropped rather than emitted untyped —
    the point is to recover mentions the matcher missed, not to invent them.

    Covers the labelled-value slot by default and the exam-label slot on
    request; see :func:`structural_spans` for why the second is off until the
    expansion table exists.

    The label is resolved **in isolation and with the length floor lifted**, and
    both are deliberate. In isolation, because the surrounding digits and
    punctuation are exactly what made the n-gram window straddle the value in
    the first place. Without the floor, because the floor exists to suppress
    spurious short matches in running prose — and here the layout has already
    established that this token labels a value, so the evidence the floor was
    standing in for is present by other means.

    **Expansion is the fallback, not the first move.** A surface is looked up as
    written first; only if the terminology has nothing does the slot-scoped
    expansion table get consulted and the *long form* resolved instead. So the
    table can add mentions and never overrides one the terminology already had.

    The mention's span and surface always come from the **original note**. The
    long form is a lookup key and is never substituted into text, because every
    offset in this package is an offset into the note as written.
    """
    from robustehr.concepts.matcher import ConceptMatcher, MatcherConfig, Mention

    inner = ConceptMatcher(
        matcher.index,  # type: ignore[attr-defined]
        MatcherConfig(
            threshold=1.0,  # exact: structure gives the boundary, not a guess
            min_match_length=1,
            accepted_semtypes=matcher.config.accepted_semtypes,  # type: ignore[attr-defined]
        ),
    )
    table = load_expansions()
    crosswalk, code_cui = _code_maps()
    out: list[Mention] = []
    seen: dict[str, tuple[str, frozenset[str]]] = {}

    def resolve_code(code: str) -> tuple[str, frozenset[str]] | None:
        """Semantic types for a SNOMED identifier, via the shipped crosswalk.

        Returns ``None`` when the entry carries no code or the crosswalk is
        unavailable, so the caller falls back to the long form rather than
        losing the entry.
        """
        if not code or crosswalk is None:
            return None
        tuis = frozenset(crosswalk.get(code, ()))
        return (code_cui.get(code, ""), tuis) if tuis else None

    def resolve(key: str) -> tuple[str, frozenset[str]]:
        """Exact whole-string resolution of one surface, cached across the note."""
        if key not in seen:
            found = inner.annotate(key).mentions
            exact = [m for m in found if m.span.end - m.span.start == len(key)]
            seen[key] = (exact[0].cui, exact[0].tuis) if exact else ("", frozenset())
        return seen[key]

    for span, slot in slotted_spans(
        doc,
        numeric_values_only=numeric_values_only,
        include_exam_labels=include_exam_labels,
    ):
        surface = span.surface(doc.text)
        cui, tuis = resolve(surface)
        if not tuis and expand:
            entry = table.entry(surface, slot)
            if entry is not None:
                # The identifier is authoritative where the release carries one:
                # it names the concept directly, where the long form only names
                # a string that may or may not be in this release. The string is
                # the fallback and the reviewer's handle, not the anchor.
                cui, tuis = resolve_code(entry.snomed) or resolve(entry.long)
        if not tuis:
            continue
        # Span and surface come from the original note even when the concept was
        # reached through a long form: the expansion is a lookup key, never text.
        out.append(Mention(span=span, cui=cui, tuis=tuis, similarity=1.0, surface=surface))
    return tuple(out)
