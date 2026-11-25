"""DISCOURSE-channel operators: what gets written down, and how much of it.

These model note-composition behaviour rather than rendering or capture. All of
them are altering by construction — removing or duplicating content changes what
the record asserts — so none carries a preservation claim.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from robustehr.dose import DoseSpec
from robustehr.ops.base import Layer, OpContext, OperatorMeta, make_edit
from robustehr.types import (
    Anchor,
    Channel,
    Contract,
    Edit,
    ProtectionClass,
    ReflowPolicy,
    Span,
    Unit,
    UnitKind,
    make_unit_id,
)


class Truncate:
    """Cut the document down to a fraction of its length.

    The dominant real deployment constraint for LLM-based extraction, and unlike
    most operators it needs no lexicon and has no eligibility problem — every
    document can be truncated.

    Altering by construction, and that is the interesting part rather than a
    caveat. Results should be reported split two ways: notes where the evidence
    for a target phenotype *survived* the cut measure genuine robustness, while
    notes where it was removed measure something else entirely — a model still
    predicting positive there is hallucinating, not being robust. That second
    arm is only available because the operator is honest about being altering.

    Severity is read as the fraction *removed*, so higher severity means less
    text, consistent with every other operator.
    """

    meta = OperatorMeta(
        id="discourse.truncate",
        version="1.0.0",
        layer=Layer.STRUCTURE,
        channel=Channel.DISCOURSE,
        contract=Contract.REFERENCE_ALTERING_BY_DESIGN,
        dose=DoseSpec(
            UnitKind.DOCUMENT,
            denominator_doc="document characters; severity is the fraction removed",
        ),
        targets=frozenset(ProtectionClass),
        resources=(),
        modes=("tail", "head", "middle"),
        simulates="context-window limits and EHR free-text field caps",
    )

    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        if not ctx.text:
            return ()
        span = Span(0, len(ctx.text))
        return [Unit(make_unit_id(UnitKind.DOCUMENT, span), UnitKind.DOCUMENT, span)]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        if not selected:
            return
        mode = ctx.str_param("mode", "tail")
        length = len(ctx.text)
        # A document-level operator has exactly one unit, so `k` carries no
        # information and the magnitude has to come from the severity itself.
        # It arrives on the context rather than through `params`, because
        # `params` feeds the seed and severity is deliberately excluded from it
        # so that severity ladders nest.
        fraction = ctx.severity_fraction
        remove = (length * fraction.numerator) // fraction.denominator
        remove = max(0, min(remove, length))
        if remove == 0:
            return

        unit = selected[0]
        if mode == "head":
            cut = Span(0, remove)
        elif mode == "middle":
            start = (length - remove) // 2
            cut = Span(start, start + remove)
        else:
            cut = Span(length - remove, length)

        yield make_edit(
            self.meta,
            unit,
            cut,
            "",
            reflow=ReflowPolicy.FLATTEN,
            meta={"mode": mode, "removed_chars": str(remove)},
        )


class SentenceDelete:
    """Drop whole prose sentences, as a summarizer or a terse author would.

    Restricted to prose units: deleting a row from a lab block or an item from a
    medication list is a different failure mode with a different denominator,
    and conflating them would make "5% of sentences" mean something different in
    a flowsheet than in a narrative.
    """

    meta = OperatorMeta(
        id="discourse.sentence_delete",
        version="1.0.0",
        layer=Layer.SENTENCE,
        channel=Channel.DISCOURSE,
        contract=Contract.REFERENCE_ALTERING_BY_DESIGN,
        dose=DoseSpec(
            UnitKind.SENTENCE,
            denominator_doc="prose sentences, excluding lab blocks, list items and headers",
        ),
        targets=frozenset(ProtectionClass),
        resources=(),
        simulates="summarization loss and terse documentation",
    )

    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        return [
            Unit(make_unit_id(UnitKind.SENTENCE, s.span), UnitKind.SENTENCE, s.span)
            for s in ctx.doc.sentences.prose()
        ]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                "",
                rank=rank,
                reflow=ReflowPolicy.FLATTEN,
            )


class SectionDuplicate:
    """Repeat a whole section immediately after itself.

    Note bloat: the copy-forward and paste-again behaviour that makes real
    discharge summaries repeat their own problem list two or three times. The
    benign control for a stale copy-forward operator (not built) — the content is
    identical, so nothing has become *stale*, and any performance change is
    attributable to redundancy alone rather than to contradiction.

    **Dosed as a count, not a rate**, and it is the only operator here that is.
    "Duplicate 50% of sections" would be four sections in one note and eleven in
    another, which is not a comparable experimental condition; "duplicate two
    sections" is. `count:1`, `count:2` and `count:5` still nest, because
    selection is hash-rank over the same eligible set — the note that gets its
    Hospital Course duplicated at `count:1` still gets it at `count:5`.

    Conditionally preserving rather than altering: every content token survives
    and none is contradicted, but a duplicated ``Assessment and Plan`` doubles
    the apparent evidence for whatever it asserts, and a reader counting
    mentions will count them twice.
    """

    meta = OperatorMeta(
        id="discourse.section_duplicate",
        version="1.0.0",
        layer=Layer.STRUCTURE,
        channel=Channel.DISCOURSE,
        contract=Contract.CONDITIONALLY_PRESERVING,
        canonicalizer=None,
        dose=DoseSpec(
            UnitKind.SECTION,
            dose_kind="count_per_doc",
            denominator_doc="complete identified sections, header and body",
        ),
        # A duplicate is an insertion at the section boundary: it overlaps
        # nothing, so it withholds nothing. The classes are declared because the
        # inserted *text* carries them, and an audit reading the edit should see
        # that a header and a lab block came along with it.
        targets=frozenset(
            {
                ProtectionClass.SECTION_HEADER,
                ProtectionClass.LIST_MARKER,
                ProtectionClass.NUMERIC_VALUE,
                ProtectionClass.LAB_BLOCK,
            }
        ),
        resources=(),
        severity_levels=("count:1", "count:2", "count:5"),
        simulates="copy-paste note bloat that repeats a section verbatim",
    )

    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        return [
            Unit(make_unit_id(UnitKind.SECTION, section.full), UnitKind.SECTION, section.full)
            for section in ctx.doc.sections
            if not section.full.is_empty
        ]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            # `copy_from` rather than the section text, and this is the whole
            # reason the field exists. A section is thousands of characters;
            # carried as a literal replacement it would write clinical text into
            # the edit script and break the property that makes edit scripts
            # shareable when the corpus is not. As two offsets it carries none,
            # and replay is identical — same source, same offsets, same bytes.
            body = unit.span.surface(ctx.text)
            # Anchored RIGHT so the copy lands after the section rather than
            # before it. The leading newline is the only literal text here, and
            # it is needed when the section did not end with one: otherwise the
            # duplicate's header is glued to the original's last line and stops
            # being a header at all.
            separator = "" if body.endswith("\n") else "\n"
            yield make_edit(
                self.meta,
                unit,
                Span(unit.span.end, unit.span.end),
                separator,
                rank=rank,
                anchor=Anchor.RIGHT,
                reflow=ReflowPolicy.FLATTEN,
                copy_from=unit.span,
            )


OPERATORS = (Truncate, SentenceDelete, SectionDuplicate)

__all__ = ["OPERATORS", "SectionDuplicate", "SentenceDelete", "Truncate"]
