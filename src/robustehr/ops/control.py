"""Controls.

Neither of these simulates anything. They exist to tell you whether the
measurement apparatus is working, and a sweep without both of them cannot
distinguish a robustness finding from a harness bug.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from robustehr.dose import DoseSpec
from robustehr.ops.base import Layer, OpContext, OperatorMeta, make_edit
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


class Identity:
    """The null control: proposes nothing, ever.

    Mandatory in every sweep. Without it you cannot separate a corruption effect
    from model stochasticity, a caching bug or a harness fault — a non-zero
    result here means something is wrong with the pipeline, not with the model.
    """

    meta = OperatorMeta(
        id="control.identity",
        version="1.0.0",
        layer=Layer.CHAR,
        channel=Channel.CONTROL,
        contract=Contract.CONTROL_NULL,
        canonicalizer="identity",
        dose=DoseSpec(UnitKind.DOCUMENT, denominator_doc="the document"),
        targets=frozenset(),
        resources=(),
        simulates="nothing; it is the null control",
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
        return ()


class CharShuffle:
    """The positive control: scramble the interior characters of words.

    Deliberately destructive and deliberately not realistic. Its job is to fail:
    if downstream performance does *not* collapse under this, the harness is
    broken, the model is ignoring the text, or the labels leak — and that is
    worth knowing before any real result is interpreted.

    Interior-only scrambling keeps first and last characters, so the output
    still looks like language and the failure cannot be blamed on the text
    having become obviously non-textual.
    """

    meta = OperatorMeta(
        id="control.char_shuffle",
        version="1.0.0",
        layer=Layer.CHAR,
        channel=Channel.CONTROL,
        contract=Contract.CONTROL_DESTRUCTIVE,
        dose=DoseSpec(
            UnitKind.WORD,
            denominator_doc="alphabetic tokens of at least four characters",
        ),
        targets=frozenset(ProtectionClass),
        resources=(),
        simulates="nothing; it is the positive control",
    )

    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources

    MIN_LENGTH = 4

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        return [
            Unit(make_unit_id(UnitKind.WORD, t.span), UnitKind.WORD, t.span)
            for t in ctx.doc.tokens
            if t.kind is TokenKind.WORD and len(t.span) >= self.MIN_LENGTH
        ]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            word = unit.span.surface(ctx.text)
            rng = ctx.rng(unit.unit_id)
            interior = list(word[1:-1])
            # Fisher-Yates over the restricted RNG surface. `shuffle` is absent
            # from RestrictedRandom because CPython's implementation is not a
            # specified algorithm.
            for i in range(len(interior) - 1, 0, -1):
                j = rng.below(i + 1)
                interior[i], interior[j] = interior[j], interior[i]
            scrambled = word[0] + "".join(interior) + word[-1]
            if scrambled == word:
                continue
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                scrambled,
                rank=rank,
                reflow=ReflowPolicy.VERBATIM,
            )


OPERATORS = (Identity, CharShuffle)

__all__ = ["OPERATORS", "CharShuffle", "Identity"]
