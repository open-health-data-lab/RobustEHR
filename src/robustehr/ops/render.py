"""RENDER-channel operators: serialization, formatting and encoding.

These simulate the note being written out differently, not written differently.
Most carry an ``INVARIANT_BY_CONSTRUCTION`` contract, and each names the
projection that proves it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from robustehr.dose import DoseSpec
from robustehr.ops.base import Layer, OpContext, OperatorMeta, make_edit
from robustehr.segment.deid import DeidScheme
from robustehr.segment.headers import (
    HEADERS_RESOURCE,
    HeaderConfidence,
    HeaderGrammar,
    load_lexicon,
)
from robustehr.segment.patterns import HSPACE
from robustehr.segment.tokens import TokenKind
from robustehr.types import (
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

_SPACE_RUN = re.compile(f"[{HSPACE}]{{2,}}")


# ---------------------------------------------------------------------------
# render.whitespace_collapse
# ---------------------------------------------------------------------------


class WhitespaceCollapse:
    """Collapse runs of horizontal whitespace to a single space.

    Simulates a renderer or copy-paste that does not preserve column alignment.
    Invariant by construction: only inter-token whitespace changes, so the
    content-token sequence is untouched.
    """

    meta = OperatorMeta(
        id="render.whitespace_collapse",
        version="1.0.0",
        layer=Layer.CHAR,
        channel=Channel.RENDER,
        contract=Contract.INVARIANT_BY_CONSTRUCTION,
        canonicalizer="content_tokens",
        dose=DoseSpec(
            UnitKind.SPACE_RUN,
            denominator_doc="runs of two or more horizontal whitespace characters",
        ),
        targets=frozenset({ProtectionClass.LAB_BLOCK}),
        resources=(),
        simulates="a renderer or clipboard that does not preserve column alignment",
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
        found: list[Unit] = []
        for match in _SPACE_RUN.finditer(ctx.text):
            span = Span(*match.span())
            found.append(Unit(make_unit_id(UnitKind.SPACE_RUN, span), UnitKind.SPACE_RUN, span))
        return found

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            yield make_edit(self.meta, unit, unit.span, " ", rank=rank)


# ---------------------------------------------------------------------------
# render.deid_restyle
# ---------------------------------------------------------------------------

#: Target conventions. The value is a template; ``{label}`` is filled from the
#: source mask's type label when it has one.
_DEID_STYLES: dict[str, str] = {
    "underscore": "___",
    "bracket_star": "[**{label}**]",
    "angle_tag": "<{label}>",
    "square_tag": "[{label}]",
    "curly_tag": "{{{{{label}}}}}",
    "xxx": "XXXXX",
    "asterisk": "***",
    "redacted": "[REDACTED]",
    "delete": "",
}

_DEFAULT_LABEL = "REDACTED"


class DeidRestyle:
    """Rewrite de-identification masks into a different convention.

    The highest-eligibility operator in the suite — masks appear in essentially
    every note of a de-identified corpus, ~65 per note in the development
    corpus — and one of the most useful, because a model trained on one masking
    convention has partly learned that convention rather than clinical language.

    Invariant by construction under a projection that collapses masks to a
    sentinel: the surrounding clinical tokens and the positions of the masks
    among them are unchanged. Collapsing rather than dropping matters — dropping
    would let ``mode: delete`` pass while removing masks entirely.

    ``mode: delete`` is therefore *not* invariant and is rejected under that
    contract; it is offered as a separate, conditionally-preserving mode.
    """

    meta = OperatorMeta(
        id="render.deid_restyle",
        version="1.0.0",
        layer=Layer.CHAR,
        channel=Channel.RENDER,
        contract=Contract.INVARIANT_BY_CONSTRUCTION,
        canonicalizer="content_tokens_masked_deid",
        dose=DoseSpec(
            UnitKind.PLACEHOLDER,
            denominator_doc="de-identification masks, whatever the source convention",
        ),
        # Masks sit inside lab lines and header values as often as in prose —
        # `___ 09:57PM BLOOD WBC-6.9 ... Plt ___` is a mask inside an aligned
        # block. Declaring only DEID_PLACEHOLDER would leave those unreachable
        # and silently halve the operator's eligibility, so the enclosing
        # structural classes are declared too. Replacing a mask does not damage
        # the block or the header; it is the same edit wherever it occurs.
        targets=frozenset(
            {
                ProtectionClass.DEID_PLACEHOLDER,
                ProtectionClass.LAB_BLOCK,
                ProtectionClass.SECTION_HEADER,
            }
        ),
        resources=(),
        modes=tuple(sorted(_DEID_STYLES)),
        simulates="a corpus de-identified under a different convention",
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
        if ctx.doc.deid.scheme is DeidScheme.NONE:
            return ()
        return [
            Unit(
                make_unit_id(UnitKind.PLACEHOLDER, p.span),
                UnitKind.PLACEHOLDER,
                p.span,
                {"label": p.type_label or _DEFAULT_LABEL},
            )
            for p in ctx.doc.deid.placeholders
        ]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        mode = ctx.str_param("mode", "bracket_star")
        template = _DEID_STYLES.get(mode, _DEID_STYLES["bracket_star"])
        for rank, unit in enumerate(selected):
            label = str(unit.payload.get("label", _DEFAULT_LABEL))
            replacement = template.format(label=label)
            if replacement == unit.span.surface(ctx.text):
                continue  # already in the target style
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                replacement,
                rank=rank,
                meta={"mode": mode, "source_scheme": ctx.doc.deid.scheme.value},
            )


# ---------------------------------------------------------------------------
# render.header_style
# ---------------------------------------------------------------------------


class HeaderStyle:
    """Restyle section header labels without changing which section they name.

    Simulates template variation between institutions: ``Past Medical
    History:`` versus ``PAST MEDICAL HISTORY:`` versus ``Past medical
    history:``. Only casing changes, so the case-folded content-token sequence
    is invariant.

    The contract is deliberately the *casefolded* projection rather than the
    plain one, because case genuinely carries meaning in clinical text — it is
    much of what separates an abbreviation from a word. Claiming full invariance
    here would be claiming more than is true.
    """

    meta = OperatorMeta(
        id="render.header_style",
        version="1.0.0",
        layer=Layer.SECTION,
        channel=Channel.RENDER,
        contract=Contract.INVARIANT_BY_CONSTRUCTION,
        canonicalizer="content_tokens_casefolded",
        dose=DoseSpec(
            UnitKind.HEADER,
            denominator_doc="detected section headers, excluding boilerplate and report fields",
        ),
        targets=frozenset({ProtectionClass.SECTION_HEADER}),
        resources=("headers.yaml",),
        modes=("upper", "lower", "title"),
        simulates="header capitalisation conventions differing between institutions",
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
            Unit(make_unit_id(UnitKind.HEADER, h.label), UnitKind.HEADER, h.label)
            for h in ctx.doc.section_headers()
            if h.grammar is not HeaderGrammar.MARKDOWN
        ]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        mode = ctx.str_param("mode", "upper")
        for rank, unit in enumerate(selected):
            original = unit.span.surface(ctx.text)
            if mode == "upper":
                restyled = original.upper()
            elif mode == "lower":
                restyled = original.lower()
            else:
                restyled = original.title()
            if restyled == original:
                continue
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                restyled,
                rank=rank,
                reflow=ReflowPolicy.VERBATIM,
                meta={"mode": mode},
            )


# ---------------------------------------------------------------------------
# render.lab_block_collapse
# ---------------------------------------------------------------------------


class LabBlockCollapse:
    """Collapse column alignment in a lab block to single spaces.

    Simulates a viewer, export or clipboard that does not preserve the
    whitespace padding holding a two-dimensional layout together. The values and
    their labels survive in order; only the padding between them goes.

    Invariant by construction under ``content_tokens``: nothing but runs of
    horizontal whitespace *inside an aligned block* changes, so the content-token
    sequence is identical. This is deliberately narrower than
    ``whitespace_collapse``, whose denominator is every space run in the note —
    the two answer different questions and must not share a denominator.

    The unit is a space run rather than a line, and that is not cosmetic. Lab
    lines in a de-identified corpus routinely contain masks, which are
    HARD-protected; a whole-line edit therefore partially overlaps a protected
    span and is refused, and an early version of this operator was eligible on 3
    lines in 60 notes for exactly that reason. Per-run edits leave the masks
    alone and collapse the padding around them.
    """

    meta = OperatorMeta(
        id="render.lab_block_collapse",
        version="1.0.0",
        layer=Layer.STRUCTURE,
        channel=Channel.RENDER,
        contract=Contract.INVARIANT_BY_CONSTRUCTION,
        canonicalizer="content_tokens",
        dose=DoseSpec(
            UnitKind.SPACE_RUN,
            denominator_doc=(
                "runs of two or more horizontal whitespace characters inside a "
                "detected column-aligned block"
            ),
        ),
        targets=frozenset({ProtectionClass.LAB_BLOCK}),
        resources=(),
        simulates="an export or viewer that does not preserve column alignment",
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
        found: list[Unit] = []
        for block in ctx.doc.aligned:
            for line_idx in block.lines:
                line = ctx.doc.lines[line_idx]
                if line.is_blank:
                    continue
                content = line.content
                for match in _SPACE_RUN.finditer(content.surface(ctx.text)):
                    span = Span(content.start + match.start(), content.start + match.end())
                    found.append(
                        Unit(make_unit_id(UnitKind.SPACE_RUN, span), UnitKind.SPACE_RUN, span)
                    )
        return found

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            yield make_edit(self.meta, unit, unit.span, " ", rank=rank)


# ---------------------------------------------------------------------------
# render.bullet_to_prose
# ---------------------------------------------------------------------------


class BulletToProse:
    """Strip list markers, leaving the item content in place.

    Simulates a note pasted out of a structured editor into plain prose, or a
    template whose numbering did not survive the round trip. Only the marker and
    its trailing whitespace are removed; the item text and the line structure
    around it are untouched.

    Invariant by construction under ``content_tokens_without_list_markers``, and
    the choice of projection is the honest part. ``content_tokens`` would be
    wrong: a numbered marker like ``1.`` tokenizes as a *number*, which counts as
    content, so stripping it does change that sequence. The guarantee this
    operator actually offers is narrower — the prose survives untouched and only
    the enumeration around it goes — and the projection states exactly that.
    """

    meta = OperatorMeta(
        id="render.bullet_to_prose",
        version="1.0.0",
        layer=Layer.STRUCTURE,
        channel=Channel.RENDER,
        contract=Contract.INVARIANT_BY_CONSTRUCTION,
        canonicalizer="content_tokens_without_list_markers",
        dose=DoseSpec(
            UnitKind.LIST_ITEM,
            denominator_doc="items in a detected list block",
        ),
        # NUMERIC_VALUE as well as LIST_MARKER: a numbered marker like "1." is
        # covered by both, and the digit there is list structure rather than a
        # clinical value. Without it every numbered list is refused.
        targets=frozenset({ProtectionClass.LIST_MARKER, ProtectionClass.NUMERIC_VALUE}),
        resources=(),
        severity_levels=("0.30", "0.50", "1"),
        simulates="a note pasted out of a structured editor into plain prose",
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
        found: list[Unit] = []
        for block in ctx.doc.lists:
            for item in block.items:
                if item.marker.is_empty:
                    continue
                found.append(
                    Unit(
                        make_unit_id(UnitKind.LIST_ITEM, item.marker),
                        UnitKind.LIST_ITEM,
                        item.marker,
                    )
                )
        return found

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            # Absorb the whitespace after the marker too, or stripping "1." from
            # "1.  Pneumonia" would leave a two-space gap that reads as column
            # alignment to the block detector.
            end = unit.span.end
            while end < len(ctx.text) and ctx.text[end] in " \t":
                end += 1
            yield make_edit(self.meta, unit, Span(unit.span.start, end), "", rank=rank)


# ---------------------------------------------------------------------------
# render.header_delete
# ---------------------------------------------------------------------------


class HeaderDelete:
    """Remove a section header, keeping the content beneath it.

    Simulates a note whose structure was flattened in transit — an export that
    dropped headings, or a template rendered without them.

    **Conditionally preserving, not invariant**, and the distinction is the
    reason this operator is interesting. Deleting ``Family History:`` does not
    change a single content token, but it merges the experiencer scope of what
    follows into the surrounding narrative: a reader, or a model, can no longer
    tell that the diabetes belonged to the mother. The content survives; the
    reference does not. Whether that matters depends on where the edit lands,
    which is exactly what ``CONDITIONALLY_PRESERVING`` means.
    """

    meta = OperatorMeta(
        id="render.header_delete",
        version="1.0.0",
        layer=Layer.STRUCTURE,
        channel=Channel.RENDER,
        contract=Contract.CONDITIONALLY_PRESERVING,
        canonicalizer=None,
        dose=DoseSpec(
            UnitKind.HEADER,
            denominator_doc="standalone section headers",
        ),
        targets=frozenset({ProtectionClass.SECTION_HEADER}),
        resources=(),
        severity_levels=("0.30", "0.50", "1"),
        simulates="an export or template that dropped section headings",
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
        found: list[Unit] = []
        for header in ctx.doc.section_headers():
            if header.value is not None and not header.value.is_empty:
                # Inline header: deleting the line would take content with it.
                continue
            line = ctx.doc.lines[header.line_idx]
            found.append(Unit(make_unit_id(UnitKind.HEADER, line.full), UnitKind.HEADER, line.full))
        return found

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            yield make_edit(self.meta, unit, unit.span, "", rank=rank, reflow=ReflowPolicy.FLATTEN)


# ---------------------------------------------------------------------------
# render.header_rename
# ---------------------------------------------------------------------------


def _match_case(alias: str, original: str) -> str:
    """Re-case an alias to the casing style of the label it replaces.

    Without this, renaming ``PAST MEDICAL HISTORY:`` to ``Medical Hx:`` would
    deliver a rename *and* a capitalisation change in one edit, and no result
    could attribute the effect to either. `render.header_style` is the operator
    that changes case; this one changes the name.
    """
    if original.isupper():
        return alias.upper()
    if original.islower():
        return alias.lower()
    return alias


class HeaderRename:
    """Replace a section header with a clinically equivalent name for the same section.

    ``Assessment and Plan:`` becomes ``Clinical Impression:`` — the section is
    still the same section, and a reader loses nothing, but any model keyed on
    the literal string loses the anchor. This is the header corruption that is
    *not* a deletion: the structure survives and only its label moves.

    **Lexicon confidence is required, and that is the point.** The alternatives
    come from `headers.yaml`, which maps 58 canonical sections onto their known
    clinical variants, so a rename is a move within one canonical section rather
    than an invented synonym. A heuristic header match has no canonical id and
    therefore no equivalence class to draw from — this operator refuses it,
    where `render.header_delete` can safely take it. That asymmetry is the
    reason `HeaderConfidence` has three tiers rather than being a boolean.

    Conditionally preserving for the same reason header deletion is: renaming
    ``Family History:`` to ``Social and Family History:`` keeps every content
    token but moves the boundary of the experiencer scope beneath it.
    """

    meta = OperatorMeta(
        id="render.header_rename",
        version="1.0.0",
        layer=Layer.SECTION,
        channel=Channel.RENDER,
        contract=Contract.CONDITIONALLY_PRESERVING,
        canonicalizer=None,
        dose=DoseSpec(
            UnitKind.HEADER,
            denominator_doc=(
                "section headers resolving to a canonical id that has at least "
                "one other known clinical name"
            ),
        ),
        targets=frozenset({ProtectionClass.SECTION_HEADER}),
        resources=(HEADERS_RESOURCE,),
        severity_levels=("0.30", "0.50", "1"),
        simulates="a template or institution that names the same section differently",
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
        lexicon = load_lexicon()
        found: list[Unit] = []
        for header in ctx.doc.section_headers():
            if header.confidence is not HeaderConfidence.LEXICON:
                continue
            if not lexicon.aliases_for(header.canonical_id, excluding=header.raw_name):
                continue
            found.append(
                Unit(make_unit_id(UnitKind.HEADER, header.label), UnitKind.HEADER, header.label)
            )
        return found

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        lexicon = load_lexicon()
        for rank, unit in enumerate(selected):
            original = unit.span.surface(ctx.text)
            header = self._header_at(ctx, unit)
            if header is None:  # pragma: no cover - selected units come from eligible()
                continue
            options = lexicon.aliases_for(header.canonical_id, excluding=original)
            if not options:
                continue
            chosen = str(ctx.rng(unit.unit_id).pick(options))
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                _match_case(chosen, original),
                rank=rank,
                meta={"canonical_id": header.canonical_id or "", "from": original},
            )

    @staticmethod
    def _header_at(ctx: OpContext, unit: Unit):  # type: ignore[no-untyped-def]
        for header in ctx.doc.section_headers():
            if header.label == unit.span:
                return header
        return None


# ---------------------------------------------------------------------------
# render.list_to_prose
# ---------------------------------------------------------------------------


class ListToProse:
    """Join a whole list into one line of running prose, items separated by ``; ``.

    The corruption a structured problem list undergoes when it is pasted into a
    free-text field::

        - Diabetes          ->   Diabetes; Hypertension; CKD
        - Hypertension
        - CKD

    Distinct from `render.bullet_to_prose`, and the difference is the
    denominator rather than the mechanism. That operator's unit is the
    ``LIST_ITEM``: it strips markers where it lands and leaves the lines alone,
    so "30%" means 30% of items. This one's unit is the ``LIST_BLOCK``, because
    a half-joined list is not a thing that happens — a list either survived the
    paste or it did not. "30%" here means 30% of the note's lists, whole.

    Indented continuation lines are folded into the item they continue rather
    than becoming items of their own, so no text is dropped: the join is a
    re-serialization of the block, not a rewrite of it.
    """

    meta = OperatorMeta(
        id="render.list_to_prose",
        version="2.0.0",
        layer=Layer.STRUCTURE,
        channel=Channel.RENDER,
        contract=Contract.INVARIANT_BY_CONSTRUCTION,
        canonicalizer="content_tokens_without_list_markers",
        dose=DoseSpec(
            UnitKind.LIST_BLOCK,
            denominator_doc="detected list blocks holding at least two items",
        ),
        targets=frozenset({ProtectionClass.LIST_MARKER, ProtectionClass.NUMERIC_VALUE}),
        resources=(),
        severity_levels=("0.30", "0.50", "1"),
        simulates="a structured problem list pasted into a free-text field",
    )

    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources

    #: A single item is already prose; joining it would only strip its marker,
    #: which is `render.bullet_to_prose`'s job at a different denominator.
    MIN_ITEMS = 2

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        """One unit per joinable list, spanning what the operator actually edits.

        **The unit's span is the gaps, not the block**, and the difference is
        74% of MIMIC's lists. The framework withholds a unit when anything
        protected covers its span, which is right — but a medication list is
        full of dosages and de-identification masks, and if the unit spanned the
        whole block every such list would be refused for content this operator
        never touches. Measured: 6,303 of 8,511 blocks withheld, 381 notes
        entirely, for spans the join does not go near.

        So the span runs from the first marker to the start of the last item's
        content — the region the gap edits live in — and the check lands on
        that. It is still conservative (the last item's text is inside it) and
        it is now conservative about the right region. The block's identity is
        unchanged: `unit_id` is still derived from the block span, so a
        denominator is still a count of lists.
        """
        found: list[Unit] = []
        for block in ctx.doc.lists:
            if len(block.items) < self.MIN_ITEMS:
                continue
            gaps = self._gaps(ctx, block)
            if not gaps:  # pragma: no cover - a multi-item block always has one
                continue
            # Every gap checked against protection, not just the one the unit
            # carries. This is the operator making the guarantee the framework
            # cannot: a unit has one contiguous span and the edits do not.
            if any(ctx.protection.blocks(gap, self.meta.targets) for gap in gaps):
                continue
            found.append(
                Unit(make_unit_id(UnitKind.LIST_BLOCK, block.span), UnitKind.LIST_BLOCK, gaps[0])
            )
        return found

    def _gaps(self, ctx: OpContext, block) -> list[Span]:  # type: ignore[no-untyped-def]
        """The spans this operator would edit: markers and inter-item whitespace.

        Never item text. That is what makes the narrow protection check sound —
        a dosage or a de-identification mask inside an item is not in any of
        these spans, so refusing the whole block for one was refusing it for
        content the join does not go near.
        """
        item_by_line = {item.line_idx: item for item in block.items}
        first = block.items[0]
        end = first.marker.end
        while end < len(ctx.text) and ctx.text[end] in " \t":
            end += 1
        gaps = [Span(first.marker.start, end)]
        previous_end = first.content.end
        for line_idx in range(first.line_idx + 1, block.items[-1].line_idx + 1):
            line = ctx.doc.lines[line_idx]
            if line.is_blank:
                continue
            item = item_by_line.get(line_idx)
            start = item.content.start if item is not None else line.content.start
            while start < len(ctx.text) and ctx.text[start] in " \t":
                start += 1
            if start > previous_end:
                gaps.append(Span(previous_end, start))
            previous_end = line.content.end
        return gaps

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        """One small edit per boundary, never one big joined replacement.

        The obvious implementation — build the joined line and replace the whole
        block with it — puts a few hundred characters of the note into the edit
        script, which is the one thing an edit script must never carry
        (`store.MAX_REPLACEMENT_CHARS` refuses it, and is right to).

        So the block is joined by editing only the **gaps**: the marker of the
        first item is deleted, and every boundary between one line's content and
        the next is replaced by `"; "` (between items) or `" "` (a continuation
        folding into the item above). Item text is never in an edit at all — it
        survives by not being touched. Every replacement is at most two
        characters, and the output is identical.

        All the edits for one block share a ``group_id``, so a block is joined
        completely or not at all: half-joined is not a thing that happens to a
        list, and it is not a thing this operator can produce either.
        """
        by_id = {make_unit_id(UnitKind.LIST_BLOCK, block.span): block for block in ctx.doc.lists}
        for rank, unit in enumerate(selected):
            block = by_id.get(unit.unit_id)
            if block is None:  # pragma: no cover - selected units come from eligible()
                continue
            yield from self._join_edits(ctx, unit, block, rank)

    def _join_edits(self, ctx: OpContext, unit: Unit, block, rank: int) -> Iterable[Edit]:  # type: ignore[no-untyped-def]
        item_by_line = {item.line_idx: item for item in block.items}
        first = block.items[0]
        group = unit.unit_id

        # The first item's marker, plus the whitespace after it.
        end = first.marker.end
        while end < len(ctx.text) and ctx.text[end] in " \t":
            end += 1
        yield make_edit(
            self.meta,
            unit,
            Span(first.marker.start, end),
            "",
            rank=rank,
            group_id=group,
        )

        previous_end = first.content.end
        for line_idx in range(first.line_idx + 1, block.items[-1].line_idx + 1):
            line = ctx.doc.lines[line_idx]
            if line.is_blank:
                continue
            item = item_by_line.get(line_idx)
            # `"; "` starts a new item; `" "` folds a continuation line into the
            # item above it, so no text is dropped and no two words merge.
            #
            # `item.content` begins immediately after the marker, which is
            # before the space that follows it — absorb that too, or `1.  Foo`
            # joins as `; <space>Foo` and the output carries a double space the
            # block detector would read as column alignment.
            start = item.content.start if item is not None else line.content.start
            while start < len(ctx.text) and ctx.text[start] in " \t":
                start += 1
            if start <= previous_end:  # pragma: no cover - lines never overlap
                continue
            yield make_edit(
                self.meta,
                unit,
                Span(previous_end, start),
                "; " if item is not None else " ",
                rank=rank,
                group_id=group,
                reflow=ReflowPolicy.FLATTEN,
            )
            previous_end = line.content.end


# ---------------------------------------------------------------------------
# render.break_removal
# ---------------------------------------------------------------------------


class BreakRemoval:
    """Remove the boundary between two blocks, running them together as one.

    The degradation a note suffers when it is exported through a channel that
    does not carry line structure: sections, paragraphs and lists all arrive as
    one undifferentiated wall of text.

    **The replacement is a space, never nothing.** Deleting the newline outright
    would join ``...left arm`` to ``Medications:`` as ``armMedications:``, which
    is not a loss of structure but a word-merging corruption — that is
    `render.space_delete`, at a different denominator and a different contract.
    Every break here already carries the surrounding whitespace (see
    :mod:`robustehr.segment.breaks`), so one space replaces the whole run and no
    token is ever merged with its neighbour.

    Conditionally preserving: the content tokens are untouched, but the
    boundaries a reader uses to tell a header from its content, or one
    paragraph's subject from the next's, are what is being removed.
    """

    meta = OperatorMeta(
        id="render.break_removal",
        version="1.0.0",
        layer=Layer.STRUCTURE,
        channel=Channel.RENDER,
        contract=Contract.CONDITIONALLY_PRESERVING,
        canonicalizer=None,
        dose=DoseSpec(
            UnitKind.PARAGRAPH,
            denominator_doc=(
                "structural breaks between blocks, excluding hard-wrap "
                "continuations and boundaries interior to a list or lab block"
            ),
        ),
        targets=frozenset(),
        resources=(),
        severity_levels=("0.30", "0.50", "1"),
        simulates="an export that did not carry line structure",
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
            Unit(make_unit_id(UnitKind.PARAGRAPH, brk.span), UnitKind.PARAGRAPH, brk.span)
            for brk in ctx.doc.breaks
        ]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            yield make_edit(self.meta, unit, unit.span, " ", rank=rank, reflow=ReflowPolicy.FLATTEN)


# ---------------------------------------------------------------------------
# render.space_delete
# ---------------------------------------------------------------------------


class SpaceDelete:
    """Delete the space between two words, merging them.

    ``denies chest pain`` becomes ``denies chestpain``. Simulates the copy-paste
    and PDF-extraction degradation where word boundaries are lost — a different
    failure from `render.whitespace_collapse`, which normalises runs of two or
    more spaces down to one and by construction *never* removes the last space
    separating two tokens.

    That difference is why this operator cannot be a mode of that one. Collapsing
    a run is invariant under ``content_tokens``: the same tokens come out.
    Deleting the final space merges two content tokens into one, so no token
    projection can hold and the contract has to be conditional.

    Restricted to single spaces between two content tokens **inside prose
    sentences**. Lab rows and column-aligned blocks are excluded because a space
    there is column structure, not a word gap — corrupting it is
    `render.lab_block_collapse`'s territory — and the spec that motivated this
    operator asks specifically for word spacing rather than layout.
    """

    meta = OperatorMeta(
        id="render.space_delete",
        version="1.0.0",
        layer=Layer.CHAR,
        channel=Channel.RENDER,
        contract=Contract.CONDITIONALLY_PRESERVING,
        canonicalizer=None,
        dose=DoseSpec(
            UnitKind.CHAR,
            denominator_doc="single spaces separating two content tokens in prose sentences",
        ),
        targets=frozenset(),
        resources=(),
        severity_levels=("0.10", "0.20", "0.30"),
        simulates="word boundaries lost to copy-paste or PDF text extraction",
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
        prose = [s.span for s in ctx.doc.sentences.prose()]
        if not prose:
            return []
        tokens = ctx.doc.tokens.tokens
        found: list[Unit] = []
        for idx in range(1, len(tokens) - 1):
            token = tokens[idx]
            if token.kind is not TokenKind.SPACE or len(token.span) != 1:
                continue
            if not (tokens[idx - 1].is_content and tokens[idx + 1].is_content):
                continue
            if not any(s.contains(token.span) for s in prose):
                continue
            found.append(Unit(make_unit_id(UnitKind.CHAR, token.span), UnitKind.CHAR, token.span))
        return found

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            yield make_edit(self.meta, unit, unit.span, "", rank=rank)


OPERATORS = (
    WhitespaceCollapse,
    DeidRestyle,
    HeaderStyle,
    LabBlockCollapse,
    BulletToProse,
    ListToProse,
    HeaderDelete,
    HeaderRename,
    BreakRemoval,
    SpaceDelete,
)

__all__ = [
    "OPERATORS",
    "BreakRemoval",
    "BulletToProse",
    "DeidRestyle",
    "HeaderDelete",
    "HeaderRename",
    "HeaderStyle",
    "LabBlockCollapse",
    "ListToProse",
    "SpaceDelete",
    "WhitespaceCollapse",
]
