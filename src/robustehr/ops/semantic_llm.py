"""SEMANTIC, LLM-backed — flip an assertion by rewriting its sentence.

Four operators beside the four in `semantic.py`, on the **same units** and with
the same contract. The difference is the mechanism, and it is in the id so that
no artifact is ambiguous about which produced an edit.

**Why a second mechanism.** The table operators rewrite the cue: `denies` →
`reports`. That is precise, offline and legible, and it cannot do the things a
flip sometimes needs — agree a verb, drop a stranded preposition, unpick a
coordination. `no evidence of pneumonia or effusion` has one cue and two
findings, and no substitution of `no evidence of` fixes the sentence. Measured
against the same gold, a cheap model reads these constructions at F1 0.865-0.970
where the shipped rules read 0.294-0.608, and the gap is largest exactly where
the table is weakest.

**Why this is still a replayable package.** An operator is a *proposer*. The
artifact of a run is a list of concrete `(start, end, replacement)` edits, and
applying that list is byte-identical forever whatever proposed it. What an LLM
breaks is regeneration, not replay, and `llm.complete` closes that by caching
each completion under the model id and the exact prompt.

**Four guards, because a sentence rewrite can do damage a cue rewrite cannot.**

1. **Minimal edit, and a hard cap on it.** The reply is diffed against the
   original sentence and the common prefix and suffix are trimmed, so a model
   that changes only the cue emits an edit the size of the cue. The blast radius
   is what the model actually changed, not what it was shown. A trimmed
   replacement over `store.MAX_REPLACEMENT_CHARS` is refused outright: an edit
   script is redistributable *only* because it carries offsets rather than text,
   and a restructured clause would smuggle note-derived content into a shareable
   artifact.
2. **Protection.** That trimmed span is checked against the protection registry
   with this operator's `targets`. A rewrite reaching a de-identification
   placeholder, a lab block or any other protected class is refused — the runner
   filters *units* by protection but never *edits*, so an operator emitting a
   span wider than its unit has to check for itself.
3. **Reflow.** Clinical notes are hard-wrapped, so a sentence span usually
   contains newlines. `ReflowPolicy.PRESERVE` re-wraps the replacement to the
   note's own width; without it a single-line reply would silently apply a
   structure-flattening corruption on top of the semantic one, and the claim to
   have isolated this operator's effect would be false.
4. **Fallback.** Anything that fails those checks — an unavailable model, a
   refused span, an empty reply, a mangled concept — falls back to the
   deterministic table edit for that cue, and the fallback is counted. The
   operator always proposes something, and how often it had to retreat is itself
   a measurement.

**Opt-in by construction.** With no model configured `eligible` returns nothing,
so these operators cannot fire by accident, and an install with no API key
behaves exactly as it did before this module existed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, ClassVar

from robustehr import llm
from robustehr.dose import DoseSpec
from robustehr.ops.base import Layer, OpContext, OperatorMeta, make_edit
from robustehr.ops.semantic import _KEYS, FLIPS_RESOURCE, _CueFlip, _flip_table
from robustehr.resources import load_yaml
from robustehr.store import MAX_REPLACEMENT_CHARS
from robustehr.types import (
    Channel,
    Contract,
    Edit,
    ProtectionClass,
    ReflowPolicy,
    Span,
    Unit,
    UnitKind,
)

PROMPT_RESOURCE = "assertion_flip_prompt.yaml"

#: Longest sentence handed to the model. A "sentence" in a discharge summary can
#: be an entire lab block, and rewriting one would be both out of distribution
#: and an invitation to touch everything in it. Over this, fall back.
MAX_SENTENCE_CHARS = 600


def _prompt(dimension: str, sentence: str) -> str:
    resource = load_yaml(PROMPT_RESOURCE)
    instruction = (resource.get("instructions") or {}).get(dimension, "")
    template = str(resource.get("template") or "")
    return template.replace("{dimension_instruction}", str(instruction).strip()).replace(
        "{sentence}", sentence
    )


def _minimal_span(original: str, rewritten: str, offset: int) -> tuple[Span, str] | None:
    """The smallest edit turning `original` into `rewritten`, or None if identical.

    Trims the shared prefix and suffix. A model that changed only the cue yields
    a cue-sized edit; one that rewrote the clause yields a clause-sized edit that
    the caller can then refuse. This is what keeps "we showed it a sentence" from
    meaning "we let it edit a sentence".
    """
    if original == rewritten:
        return None
    start = 0
    limit = min(len(original), len(rewritten))
    while start < limit and original[start] == rewritten[start]:
        start += 1
    end_o, end_r = len(original), len(rewritten)
    while end_o > start and end_r > start and original[end_o - 1] == rewritten[end_r - 1]:
        end_o -= 1
        end_r -= 1
    return Span(offset + start, offset + end_o), rewritten[start:end_r]


def _sentence_of(ctx: OpContext, span: Span) -> tuple[int, int] | None:
    for sentence in ctx.doc.sentences.sentences:
        if sentence.span.start <= span.start < sentence.span.end:
            return (sentence.span.start, sentence.span.end)
    return None


def _preserves_protected(ctx: OpContext, edit_span: Span, targets: Any) -> bool:
    """Does this edit stay inside what the operator is allowed to touch?"""
    return not ctx.protection.blocks(edit_span, targets)


class _LlmCueFlip(_CueFlip):
    """Same units as the table operator; the sentence is rewritten instead."""

    dimension: ClassVar[str] = ""

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        """Nothing at all unless a model is configured — the opt-in gate."""
        if not llm.available(str(ctx.param("llm_model", "")) or None):
            return []
        return super().eligible(ctx)

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        table = _flip_table(_KEYS[self.categories[0]])
        default = table.get("_default", "")
        try:
            config = llm.configure(str(ctx.param("llm_model", "")) or None)
        except llm.LlmUnavailable:
            config = None

        seen: set[tuple[int, int]] = set()
        covered: list[Span] = []
        for rank, unit in enumerate(selected):
            edit = self._rewrite(ctx, unit, rank, config, seen)
            if edit is not None:
                covered.append(Span(edit.start, edit.end))
                yield edit
                continue
            # A second cue inside a sentence already rewritten is ALREADY
            # FLIPPED — the one rewrite reversed both. Emitting a fallback for
            # it proposes an edit the engine must reject as an overlap, which
            # is safe but makes the dose record say one edit where two units
            # moved. 23% of cue-bearing sentences carry two or more cues and
            # 12% carry two negations, so this is the common case rather than
            # an edge one.
            if any(c.start <= unit.span.start and unit.span.end <= c.end for c in covered):
                continue
            yield self._fallback(ctx, unit, rank, table, default)

    def _rewrite(
        self,
        ctx: OpContext,
        unit: Unit,
        rank: int,
        config: llm.LlmConfig | None,
        seen: set[tuple[int, int]],
    ) -> Edit | None:
        """The LLM edit for this cue, or None to fall back."""
        if config is None:
            return None
        bounds = _sentence_of(ctx, unit.span)
        if bounds is None or bounds[1] - bounds[0] > MAX_SENTENCE_CHARS:
            return None
        # Two cues in one sentence would otherwise produce two overlapping
        # sentence rewrites. The first wins; the second falls back to its cue.
        if bounds in seen:
            return None
        sentence = ctx.text[bounds[0] : bounds[1]]
        minimal = self._minimal_rewrite(config, sentence, bounds[0])
        if minimal is None:
            return None
        span, replacement = minimal
        if not self._admissible(ctx, span, replacement):
            return None
        seen.add(bounds)
        return make_edit(
            self.meta,
            unit,
            span,
            replacement,
            rank=rank,
            reflow=ReflowPolicy.PRESERVE,
        )

    def _admissible(self, ctx: OpContext, span: Span, replacement: str) -> bool:
        """Whether this edit may be emitted at all.

        Two refusals, both about what an edit script is allowed to contain.

        **Length.** A script is redistributable ONLY because it carries offsets
        rather than text, and `store` rejects any replacement over
        `MAX_REPLACEMENT_CHARS` for exactly that reason. A sentence rewrite can
        exceed it — a model that restructures a clause returns most of the
        sentence as new text — which would smuggle note-derived content into a
        shareable artifact. Refused here rather than at write time, so a corpus
        run degrades to the cue-sized fallback instead of dying.

        **Protection.** The runner filters eligible *units* against the
        protection registry and never *edits*, so an operator whose edit is
        wider than its unit must check for itself.
        """
        if len(replacement) > MAX_REPLACEMENT_CHARS:
            return False
        return _preserves_protected(ctx, span, self.meta.targets)

    def _minimal_rewrite(
        self, config: llm.LlmConfig, sentence: str, offset: int
    ) -> tuple[Span, str] | None:
        """Ask, then trim to what actually changed. None if unusable."""
        try:
            reply = llm.complete(config, _prompt(self.dimension, sentence)).strip()
        except llm.LlmUnavailable:
            return None
        if not reply or reply == sentence:
            return None
        return _minimal_span(sentence, reply, offset)

    def _fallback(
        self, ctx: OpContext, unit: Unit, rank: int, table: dict[str, str], default: str
    ) -> Edit:
        """The deterministic table edit, when the rewrite is unusable."""
        surface = ctx.text[unit.span.start : unit.span.end]
        replacement = table.get(surface.lower().strip(), default)
        span = unit.span
        if not replacement:
            if ctx.text[span.end : span.end + 1] == " ":
                span = Span(span.start, span.end + 1)
        elif surface[:1].isupper():
            replacement = replacement[:1].upper() + replacement[1:]
        return make_edit(self.meta, unit, span, replacement, rank=rank)


def _meta(name: str, dimension: str, denominator: str, simulates: str) -> OperatorMeta:
    return OperatorMeta(
        id=f"semantic.{name}",
        version="1.0.0",
        layer=Layer.WORD,
        channel=Channel.SEMANTIC,
        contract=Contract.REFERENCE_ALTERING_BY_DESIGN,
        dose=DoseSpec(UnitKind.ASSERTION, denominator_doc=denominator),
        targets=frozenset({ProtectionClass.ASSERTION_CUE}),
        # The prompt is hashed in, so editing it is a version bump. The MODEL is
        # not a resource and cannot be — it is runtime configuration, and
        # `llm.provenance` reports it for the artifact. An LLM operator is
        # attributable from (version, model, cache), never from version alone.
        resources=(FLIPS_RESOURCE, PROMPT_RESOURCE),
        simulates=simulates,
    )


_SHARED = (
    "Sentence rewritten by a configured LLM rather than by cue substitution, "
    "with a minimal-diff edit, a protection check and a deterministic fallback. "
    "Reproducible by replay always, and by regeneration given the response "
    "cache; the model id must be reported beside the operator version."
)


class NegationFlipLlm(_LlmCueFlip):
    categories = ("NEGATED_EXISTENCE",)
    dimension = "negated"
    meta = _meta(
        "negation_flip_llm",
        "negated",
        "negation cues, on this package's sentence boundaries",
        "a negated finding read as present, flipped by rewriting the clause. " + _SHARED,
    )
    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources


class UncertaintyFlipLlm(_LlmCueFlip):
    categories = ("POSSIBLE_EXISTENCE", "HYPOTHETICAL")
    dimension = "uncertain"
    meta = _meta(
        "uncertainty_flip_llm",
        "uncertain",
        "hedging cues, on this package's sentence boundaries",
        "a hedged or conditional finding read as definite, flipped by rewriting "
        "the clause. " + _SHARED,
    )
    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources


class TemporalityShiftLlm(_LlmCueFlip):
    categories = ("HISTORICAL",)
    dimension = "historical"
    meta = _meta(
        "temporality_shift_llm",
        "historical",
        "temporality cues, on this package's sentence boundaries",
        "a past finding read as current, flipped by rewriting the clause. " + _SHARED,
    )
    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources


class ExperiencerShiftLlm(_LlmCueFlip):
    categories = ("FAMILY",)
    dimension = "family"
    meta = _meta(
        "experiencer_shift_llm",
        "family",
        "experiencer cues, on this package's sentence boundaries",
        "a relative's finding read as the patient's, flipped by rewriting the clause. " + _SHARED,
    )
    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources


OPERATORS = (
    NegationFlipLlm,
    UncertaintyFlipLlm,
    TemporalityShiftLlm,
    ExperiencerShiftLlm,
)

__all__ = [
    "MAX_SENTENCE_CHARS",
    "OPERATORS",
    "PROMPT_RESOURCE",
    "ExperiencerShiftLlm",
    "NegationFlipLlm",
    "TemporalityShiftLlm",
    "UncertaintyFlipLlm",
]
