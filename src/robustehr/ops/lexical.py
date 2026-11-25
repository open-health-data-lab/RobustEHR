"""LEXICAL-channel operators: the same thing said with different words.

The channel `Channel.LEXICAL` was declared from the start and had no
implementation. What distinguishes it from RENDER and INPUT is that its edits
are *intentional*: nobody's scanner produced ``Tylenol`` where the chart said
``acetaminophen``, and nobody mistyped ``thirty`` for ``30``. A different
clinician, a different institution or a different template wrote it that way.

That makes the contract question sharper rather than softer. A lexical operator
either preserves the underlying referent exactly — same value, same drug — or it
does not belong on this channel, because "we substituted a word that means
something else" is a SEMANTIC edit wearing a lexical costume. Both operators
here are therefore conditionally preserving with an explicit equivalence source,
and both refuse to act where that equivalence is not available.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from robustehr.dose import DoseSpec
from robustehr.drugs import DRUGS_RESOURCE, Representation, load_synonyms
from robustehr.numerals import spell
from robustehr.ops.base import Layer, OpContext, OperatorMeta, make_edit
from robustehr.segment.tokens import TokenKind
from robustehr.types import (
    Channel,
    Contract,
    Edit,
    ProtectionClass,
    ReflowPolicy,
    Unit,
    UnitKind,
    make_unit_id,
)


class NumeralToWord:
    """Write a number out in words: ``EF 30%`` -> ``EF thirty%``.

    Numeric representation varies between dictated and typed notes, between
    templates, and between clinicians — ``patient is 64`` and ``patient is
    sixty-four`` are the same fact. An extractor keyed on digit patterns sees
    only one of them, which is what this operator measures.

    **Unit-bearing values are excluded by default**, which is a decision rather
    than an oversight, and it is a mode rather than a rule. In ``bare`` mode
    only numbers carrying no unit are eligible, so ``5 days`` converts and
    ``650 mg`` does not. Spelling out a drug dose is a materially more dangerous
    edit than spelling out a count: it moves the number out of the
    ``<value><unit>`` shape every dose parser keys on, so a result would
    conflate "the model cannot read written numbers" with "the model cannot find
    the dose at all". Those are two experiments, and ``bare`` is the first.

    ``all`` mode runs the second: every spellable integer including unit-bearing
    ones, which is what reproduces ``EF 30 %`` -> ``EF thirty %``. The mode is
    recorded on every edit, so the two are never averaged together.

    Both modes declare ``DOSAGE`` as a target — the mode decides eligibility,
    the protection registry decides what an eligible span may still not touch,
    and keeping those two questions apart is why the exclusion lives in
    ``eligible`` rather than in ``targets``.

    Conditionally preserving: the value is identical by construction — the
    conversion is refused outright unless it round-trips (see
    :mod:`robustehr.numerals`) — but a written number no longer matches a
    numeric-range rule downstream, and whether that matters depends on where it
    landed.
    """

    meta = OperatorMeta(
        id="lexical.numeral_to_word",
        version="1.0.0",
        layer=Layer.WORD,
        channel=Channel.LEXICAL,
        contract=Contract.CONDITIONALLY_PRESERVING,
        canonicalizer=None,
        dose=DoseSpec(
            UnitKind.NUMBER,
            denominator_doc=(
                "integer tokens with an exact written form — no decimal point, "
                "no leading zero, at most six digits — carrying no unit in "
                "`bare` mode, any in `all` mode"
            ),
        ),
        targets=frozenset({ProtectionClass.NUMERIC_VALUE, ProtectionClass.DOSAGE}),
        resources=(),
        modes=("bare", "all"),
        severity_levels=("0.30", "0.50", "1"),
        simulates="a dictated or template-written note that spells numbers out",
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
        mode = ctx.str_param("mode", "bare")
        dosage = (
            frozenset()
            if mode == "all"
            else {protected.span for protected in ctx.protection.of_class(ProtectionClass.DOSAGE)}
        )
        return [
            Unit(make_unit_id(UnitKind.NUMBER, token.span), UnitKind.NUMBER, token.span)
            for token in ctx.doc.tokens
            if token.kind is TokenKind.NUMBER
            and spell(token.span.surface(ctx.text)) is not None
            and not any(token.span.overlaps(span) for span in dosage)
        ]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        mode = ctx.str_param("mode", "bare")
        for rank, unit in enumerate(selected):
            surface = unit.span.surface(ctx.text)
            words = spell(surface)
            if words is None:  # pragma: no cover - eligible() already checked
                continue
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                words,
                rank=rank,
                reflow=ReflowPolicy.VERBATIM,
                meta={"from": surface, "mode": mode},
            )


class MedicationRename:
    """Swap a drug's generic name for a brand name, or the reverse.

    ``Tylenol 650 mg PO q6h`` becomes ``acetaminophen 650 mg PO q6h``. The
    single most common lexical variation in medication documentation, and the
    one that most reliably breaks a dictionary-based extractor: the concept is
    identical and the string shares no characters.

    **Dose, route, frequency and formulation survive by construction.** The edit
    spans the drug name and nothing else, so everything around it is untouched —
    there is no code here that has to remember to preserve them, which is
    exactly why the propose-then-apply engine is span-based.

    **Only confident equivalences are used**, which is where most of the work
    is. :mod:`robustehr.drugs` refuses multi-token names on either side, because
    a brand like ``Arcapta Neohaler`` encodes a delivery system and ``Thyroid,
    porcine`` is a formulation rather than an ingredient; refuses brands that
    are ordinary English words, because an OTC product named ``Major`` would
    corrupt prose; and refuses brands mapping to more than one generic, because
    ``Vasotec`` is both enalapril and enalaprilat and guessing between them
    would change the drug.

    Conditionally preserving: the medication concept is unchanged, and a reader
    or a terminology loses nothing. What can change is anything keyed on the
    surface form, which is the point of running it.
    """

    meta = OperatorMeta(
        id="lexical.medication_rename",
        version="1.0.0",
        layer=Layer.WORD,
        channel=Channel.LEXICAL,
        contract=Contract.CONDITIONALLY_PRESERVING,
        canonicalizer=None,
        dose=DoseSpec(
            UnitKind.MENTION,
            denominator_doc=(
                "medication name tokens resolving to a confident generic-brand equivalence"
            ),
        ),
        targets=frozenset({ProtectionClass.CLINICAL_MENTION}),
        resources=(DRUGS_RESOURCE,),
        modes=("flip", "to_brand", "to_generic"),
        severity_levels=("0.30", "0.50", "1"),
        simulates="a clinician or institution that names drugs the other way round",
    )

    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources

    def _wanted(self, mode: str, representation: Representation) -> bool:
        """Does this mention's current representation match what the mode asks for?"""
        if mode == "to_brand":
            return representation is Representation.GENERIC
        if mode == "to_generic":
            return representation is Representation.COMMERCIAL
        # `flip` takes whichever it finds and swaps it. `UNKNOWN` is never
        # eligible in any mode: a surface we cannot classify is one we cannot
        # substitute without risking a change of drug.
        return representation in (Representation.GENERIC, Representation.COMMERCIAL)

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        mode = ctx.str_param("mode", "flip")
        synonyms = load_synonyms()
        found: list[Unit] = []
        for token in ctx.doc.tokens:
            if token.kind is not TokenKind.WORD:
                continue
            surface = token.span.surface(ctx.text)
            representation = synonyms.classify(surface)
            if not self._wanted(mode, representation):
                continue
            if not synonyms.alternatives(surface):
                continue
            found.append(
                Unit(make_unit_id(UnitKind.MENTION, token.span), UnitKind.MENTION, token.span)
            )
        return found

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        synonyms = load_synonyms()
        for rank, unit in enumerate(selected):
            surface = unit.span.surface(ctx.text)
            options = synonyms.alternatives(surface)
            if not options:  # pragma: no cover - eligible() already checked
                continue
            chosen = str(ctx.rng(unit.unit_id).pick(options))
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                _match_case(chosen, surface),
                rank=rank,
                reflow=ReflowPolicy.VERBATIM,
                meta={"from": surface, "was": synonyms.classify(surface).value},
            )


def _match_case(replacement: str, original: str) -> str:
    """Carry the original mention's casing onto the substitute.

    Notes are inconsistent — ``LASIX``, ``Lasix`` and ``lasix`` all occur — and a
    substitution that always emitted the dictionary's casing would deliver a
    capitalisation change alongside the rename. Title case is left as the
    dictionary has it, since that is how both brand and generic names are
    conventionally written.
    """
    if original.isupper():
        return replacement.upper()
    if original.islower():
        return replacement.lower()
    return replacement


OPERATORS = (NumeralToWord, MedicationRename)

__all__ = ["OPERATORS", "MedicationRename", "NumeralToWord"]
