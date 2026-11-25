"""SEMANTIC — flip what the note asserts, by rewriting the cue that asserts it.

The channel `Channel.SEMANTIC` was declared in `types.py` with no members, and
the reason was never the operators: it was that nothing produced their dose
denominator. `UnitKind.ASSERTION` and `ProtectionClass.ASSERTION_CUE` were
declared and unpopulated, so `runner.requested_k` had nothing to compute against.
`concepts.context.cues_in` closed that, and this module is what it unblocked.

**Each operator edits the cue, never the mention.** `denies chest pain` becomes
`reports chest pain`: `chest pain` is untouched, and the note's claim about it is
reversed. That keeps the package's central invariant — every offset is an offset
into the note as written — and it makes the perturbation legible, because the
edit script names exactly which four characters changed the diagnosis.

**Contract is ALT for all four.** They alter clinical reference on purpose. That
is not a weakness to be canonicalized away; it is the measurement. An operator
that flipped negation while preserving meaning would be a contradiction.

**They need medspaCy, not UMLS.** Eligibility comes from
`context.cues_in(text)`, which reads ConText's modifiers directly and never
consults an entity. So the channel runs without a terminology licence, and — more
importantly — an operator's eligibility does not shrink on a document the
concept matcher happens to cover poorly.

**Detector quality is carried, not hidden.** Each operator's `simulates` string
records the measured reliability of the detector it anchors on, because those
reliabilities differ by a factor of three. `negation_flip` rests on a detector
validated at 0.9289 F1 against clinical gold; `experiencer_shift` rests on one
whose agreement with a careful reading is κ 0.22, and it was cut from v1 on that
basis before being reinstated by explicit decision. Shipping them as silent peers
would misrepresent both. See `validation/record/methodology/12-context-qualification.md`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, ClassVar

from robustehr.dose import DoseSpec
from robustehr.ops.base import Layer, OpContext, OperatorMeta, make_edit
from robustehr.resources import load_yaml, resource_sha256
from robustehr.types import (
    Channel,
    Contract,
    Edit,
    ProtectionClass,
    Span,
    Unit,
    UnitKind,
    make_unit_id,
)

FLIPS_RESOURCE = "assertion_flips.yaml"

#: Cue category -> the key in `assertion_flips.yaml`, which uses the vocabulary
#: the rest of the package reports rather than ConText's internal names.
#:
#: HYPOTHETICAL still maps to `uncertain` for reporting, because that is what
#: `concepts.context._NAMES` reports and this table is keyed by the reported
#: dimension. No shipped operator enumerates HYPOTHETICAL any more -- see
#: `UncertaintyFlip` for why a care instruction is not a diagnostic hedge.
_KEYS = {
    "NEGATED_EXISTENCE": "negated",
    "POSSIBLE_EXISTENCE": "uncertain",
    "HISTORICAL": "historical",
    "HYPOTHETICAL": "uncertain",
    "FAMILY": "family",
}


#: Cue directions a flip operator may edit.
#:
#: A TERMINATE rule marks where a cue *stops* reaching; it asserts nothing
#: itself. Measured over 40 MIMIC discharge summaries, 250 of 1,359 cues are
#: terminators — `but`, `secondary`, `cause for`, `presentation`, `because` —
#: and the flip table has no entry for any of them, so they took the category
#: default: `negated._default` is the empty string, which **deleted `but`**, and
#: `historical._default` is `current`, which rewrote **`presentation` ->
#: `current`**. Those are discourse edits carrying a SEMANTIC operator's
#: contract, counted in a denominator documented as "negation cues".
#:
#: Not a mode. Editing a terminator is never the perturbation any of these four
#: operators claims to apply.
_FLIPPABLE_DIRECTIONS = ("FORWARD", "BACKWARD")


def _flippable(cue: Any, categories: tuple[str, ...]) -> bool:
    """Whether a cue is one this channel may rewrite.

    Module-level and duck-typed so it is testable against hand-built cues with
    no medspaCy installed — the bug it guards against was invisible precisely
    because reaching it required the optional extra.
    """
    return cue.category in categories and cue.direction in _FLIPPABLE_DIRECTIONS


def _flip_table(key: str) -> dict[str, str]:
    table = load_yaml(FLIPS_RESOURCE).get(key) or {}
    return {str(k).lower(): str(v) for k, v in table.items()}


def _cues_for_category(ctx: OpContext, categories: tuple[str, ...]) -> list[Any]:
    """Cues of one ConText category, on this package's sentence boundaries.

    Our boundaries rather than PyRuSH's, because that is the shipped stage-8
    configuration — an operator enumerating against a different segmentation
    than the detector uses would flip cues the detector never attributed.
    Scope terminators are excluded — see `_FLIPPABLE_DIRECTIONS`.

    Returns nothing when medspaCy is absent, so an install without the
    ``clinical`` extra reports zero eligible units instead of failing.
    """
    try:
        from robustehr.concepts.context import cues_in
    except ImportError:  # pragma: no cover - clinical extra not installed
        return []
    boundaries = tuple(s.span.start for s in ctx.doc.sentences.sentences)
    return [c for c in cues_in(ctx.doc.text, boundaries=boundaries) if _flippable(c, categories)]


class _CueFlip:
    """Shared machinery: enumerate cues of one category, rewrite each."""

    categories: ClassVar[tuple[str, ...]] = ()
    """ConText categories this operator rewrites. A tuple because one reported
    dimension may span several — `uncertain` covers POSSIBLE_EXISTENCE and
    HYPOTHETICAL."""
    meta: ClassVar[OperatorMeta]

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        return [
            Unit(make_unit_id(UnitKind.ASSERTION, c.span), UnitKind.ASSERTION, c.span)
            for c in _cues_for_category(ctx, self.categories)
        ]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        table = _flip_table(_KEYS[self.categories[0]])
        default = table.get("_default", "")
        for rank, unit in enumerate(selected):
            surface = ctx.text[unit.span.start : unit.span.end]
            replacement = table.get(surface.lower().strip(), default)
            span = unit.span
            if not replacement:
                # Deleting a cue leaves `has  fever` — a doubled space, which is
                # a *second* perturbation from a different channel riding along
                # inside a semantic one. The edit absorbs one trailing space so
                # what changes is the assertion and nothing else.
                if ctx.text[span.end : span.end + 1] == " ":
                    span = Span(span.start, span.end + 1)
            elif surface[:1].isupper():
                # Preserve sentence-initial capitalisation: a note full of
                # lowercase sentence openings is a different corruption from the
                # one being applied.
                replacement = replacement[:1].upper() + replacement[1:]
            yield make_edit(self.meta, unit, span, replacement, rank=rank)


def _meta(name: str, denominator: str, simulates: str) -> OperatorMeta:
    return OperatorMeta(
        id=f"semantic.{name}",
        version="1.0.0",
        layer=Layer.WORD,
        channel=Channel.SEMANTIC,
        contract=Contract.REFERENCE_ALTERING_BY_DESIGN,
        dose=DoseSpec(UnitKind.ASSERTION, denominator_doc=denominator),
        targets=frozenset({ProtectionClass.ASSERTION_CUE}),
        resources=(FLIPS_RESOURCE,),
        simulates=simulates,
    )


class NegationFlip(_CueFlip):
    categories = ("NEGATED_EXISTENCE",)
    meta = _meta(
        "negation_flip",
        "negation cues, on this package's sentence boundaries, excluding scope terminators",
        "a negated finding read as present — the commonest and most consequential "
        "assertion error. Detector validated at 0.9289 negated-class F1 on the "
        "NegEx gold, kappa 0.74 against an independent reading",
    )
    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources


class UncertaintyFlip(_CueFlip):
    #: POSSIBLE_EXISTENCE only. HYPOTHETICAL was folded in here on the argument
    #: that "a hedge and a condition are the same move for this channel", and an
    #: audit of the emitted edits showed they are not. ConText's HYPOTHETICAL
    #: catches conditional and future *care planning* -- `as needed`, `prn`,
    #: `if`, `return for`, `should he` -- and flipping those to their actual-mood
    #: counterparts fabricates facts the note does not contain: `as needed` ->
    #: `scheduled` changes a medication order, `return` -> `presented` asserts an
    #: encounter, `risks of` -> `complications of` asserts an outcome. Measured
    #: over exp4's negation-and-hedge arms, 14 of 50 sampled uncertainty edits
    #: left the assertion layer this way, and every one was HYPOTHETICAL.
    #:
    #: A care instruction is not a hedge about whether the patient has the
    #: condition, which is the only question downstream asks. POSSIBLE_EXISTENCE
    #: -- `possible`, `concerning for`, `cannot exclude` -- is that hedge, and it
    #: is also the only half the BioScope number was measured on.
    categories = ("POSSIBLE_EXISTENCE",)
    meta = _meta(
        "uncertainty_flip",
        "diagnostic hedging cues (POSSIBLE_EXISTENCE), on this package's "
        "sentence boundaries, excluding scope terminators",
        "a hedged finding read as definite. Detector measured only out of domain "
        "(BioScope abstracts, F1 0.2511 at precision 0.855 and recall 0.147): "
        "precise where it fires, and it fires on a minority of hedges",
    )
    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources


class TemporalityShift(_CueFlip):
    categories = ("HISTORICAL",)
    meta = _meta(
        "temporality_shift",
        "historical cues, on this package's sentence boundaries, excluding scope terminators",
        "a past condition read as current. Detector has no published gold; "
        "F1 0.29 on this project's held-out MIMIC gold (0.53 with the section-header "
        "rule), kappa 0.41 against an independent reading of synthetic notes",
    )
    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources


class ExperiencerShift(_CueFlip):
    categories = ("FAMILY",)
    meta = _meta(
        "experiencer_shift",
        "experiencer cues, on this package's sentence boundaries, excluding scope terminators",
        "a relative's condition read as the patient's. Detector has no published gold and "
        "kappa 0.22 against an independent reading — it marked 8 spans family "
        "where 1 was warranted, so this operator was cut from v1 and reinstated "
        "by explicit decision. Read its dose beside that number",
    )
    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources


def flips_digest() -> str:
    """SHA-256 of the rewrite table, folded into each operator's version."""
    return resource_sha256(FLIPS_RESOURCE)


OPERATORS = (NegationFlip, UncertaintyFlip, TemporalityShift, ExperiencerShift)
