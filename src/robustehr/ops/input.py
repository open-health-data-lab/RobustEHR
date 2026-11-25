"""INPUT-channel operators: typing, dictation and OCR.

These simulate the note being *captured* wrongly — a mis-heard word, a slipped
key — as opposed to being rendered differently. None of them is invariant by
construction: they all change tokens, and whether that changes clinical
reference depends on which token.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from robustehr.dose import DoseSpec
from robustehr.ocr import OCR_RESOURCE, load_table
from robustehr.ops.base import Layer, OpContext, OperatorMeta, make_edit
from robustehr.phonetics import PHONETIC_RESOURCE, load_rules
from robustehr.rng import unit_key
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


def _match_case(original: str, replacement: str) -> str:
    """Carry the original's casing onto the substitute.

    Without this, substituting inside an all-caps legacy note would turn
    ``HYPERTENSION`` into ``hypotension`` — a casing artifact a downstream model
    could learn to detect, which would confound the very robustness measurement
    the operator exists to make.
    """
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


class PhoneticConfusion:
    """Substitute a phonetically confusable form, generated from morpheme rules.

    Altering by design, in both directions and deliberately so.
    ``hypertension → hypotension`` removes evidence for the most prevalent
    phenotype in most corpora; the reverse inserts evidence for a condition the
    patient does not have. One attacks recall, the other precision, and a
    robustness result reporting only one of them is reporting half the story.

    Substitutions are **generated, not enumerated**. A curated list of
    confusable pairs covers the few dozen words somebody thought to write down,
    cannot follow the vocabulary into a new specialty, and has to be rebuilt
    from scratch for another language. Morpheme rules generate across the whole
    lexicon instead: on the development corpus the intrinsic rules alone produce
    substitutions for 137 distinct words, including
    ``hypogammaglobulinemia``/``hypergammaglobulinemia`` — a pair no curator
    would have listed.

    Rules whose affixes collide with ordinary English are gated behind a
    vocabulary, because "starts with `dis`" is not the same as "is built from
    the `dis-` morpheme"; without that gate the operator turns ``discharge``
    into ``dyscharge``. When no lexicon is available those rules are skipped and
    the skipped tokens are counted, so reduced coverage is visible rather than
    looking like a corpus with fewer confusable terms.
    """

    meta = OperatorMeta(
        id="input.phonetic_confusion",
        version="1.0.0",
        layer=Layer.WORD,
        channel=Channel.INPUT,
        contract=Contract.REFERENCE_ALTERING_BY_DESIGN,
        dose=DoseSpec(
            UnitKind.TOKEN,
            denominator_doc=(
                "tokens for which a morpheme rule generates a phonetically confusable substitute"
            ),
        ),
        # Numeric confusions are the point of the operator, so it must reach
        # values that ordinary numeric protection withholds.
        targets=frozenset(
            {
                ProtectionClass.NUMERIC_VALUE,
                ProtectionClass.DOSAGE,
                ProtectionClass.LAB_BLOCK,
                ProtectionClass.SECTION_HEADER,
            }
        ),
        resources=(PHONETIC_RESOURCE,),
        simulates="speech-recognition and dictation substitution errors",
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
        rules = load_rules()
        found: list[Unit] = []
        for token in ctx.doc.tokens:
            if not token.is_content:
                continue
            if token.kind is TokenKind.NUMBER:
                substitute = rules.substitute_digits(token.lower)
            else:
                substitute = rules.substitute(token.lower, ctx.lexicon.general or None)
            if substitute:
                found.append(
                    Unit(
                        make_unit_id(UnitKind.TOKEN, token.span),
                        UnitKind.TOKEN,
                        token.span,
                        {"substitute": substitute},
                    )
                )
        return found

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        for rank, unit in enumerate(selected):
            original = unit.span.surface(ctx.text)
            substitute = _match_case(original, str(unit.payload["substitute"]))
            if substitute == original:
                continue
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                substitute,
                rank=rank,
                reflow=ReflowPolicy.VERBATIM,
                meta={"from": original, "to": substitute},
            )


#: Adjacent keys on a QWERTY keyboard. Explicit rather than derived from a
#: layout model, so the table is auditable and stable across releases.
_ADJACENT: dict[str, str] = {
    "a": "qwsz",
    "b": "vghn",
    "c": "xdfv",
    "d": "serfcx",
    "e": "wsdr",
    "f": "drtgvc",
    "g": "ftyhbv",
    "h": "gyujnb",
    "i": "ujko",
    "j": "huikmn",
    "k": "jiolm",
    "l": "kop",
    "m": "njk",
    "n": "bhjm",
    "o": "iplk",
    "p": "ol",
    "q": "wa",
    "r": "edft",
    "s": "awedxz",
    "t": "rfgy",
    "u": "yhji",
    "v": "cfgb",
    "w": "qase",
    "x": "zsdc",
    "y": "tghu",
    "z": "asx",
}


class Typo:
    """Insert a single-character typing error into a word.

    Conditionally preserving, and only up to a low dose. A typo in ``the`` is
    inconsequential; a typo in ``obese`` destroys the only evidence token for
    that phenotype in most notes that carry it. Whether a given application
    preserves reference is therefore a measured property of where it landed, not
    a property of the operator — which is exactly what the contract lattice is
    for.

    Above roughly 10% of tokens the text stops resembling a mistyped note and
    becomes an adversarial construction, and the taxonomy says so rather than
    letting a high-severity run quietly claim realism.
    """

    meta = OperatorMeta(
        id="input.typo",
        version="1.0.0",
        layer=Layer.CHAR,
        channel=Channel.INPUT,
        contract=Contract.CONDITIONALLY_PRESERVING,
        dose=DoseSpec(
            UnitKind.WORD,
            denominator_doc=(
                "alphabetic tokens of at least three characters; alphanumeric "
                "tokens of the same length too when `include_mixed` is set"
            ),
        ),
        targets=frozenset(),
        resources=(),
        modes=("substitute", "transpose", "delete", "double"),
        severity_levels=("0.05", "0.10", "0.15"),
        simulates="keyboard typing errors",
    )

    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources

    MIN_LENGTH = 3

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        """Alphabetic tokens, and with `include_mixed` alphanumeric ones too.

        **`include_mixed` exists because clinical abbreviations are often
        alphanumeric.** `DM2`, `T2DM` and `A1c` tokenize as MIXED rather than
        WORD, and without the parameter this operator cannot touch them: aimed
        at type 2 diabetes over 120 notes it reaches 38 of 158 declared
        diagnosis spans, missing `DM2` 25 times and `T2DM` 8, while the glyph
        operator reaches 153 of 158 on the same spans. A typist reaching for
        `DM2` can mistype the `D` or the `M` as readily as in any other word;
        there is no typing reason the token is exempt, and an arm aimed at a
        phenotype should set the parameter.

        **Off by default.** `params_canon` is built from the dict the caller
        passed rather than from operator defaults, and neither `meta.version`
        nor `meta.resources` depends on the parameter, so a run that does not
        name it is byte-identical to one that cannot. Same mechanism as
        `max_edits_per_token` on `input.ocr_confusion`.

        A mixed token still needs an interior letter to mutate: the keyboard map
        holds no digits, so a position landing on one yields no edit and is
        dropped by `propose`.
        """
        kinds = {TokenKind.WORD}
        if ctx.bool_param("include_mixed", False):
            kinds.add(TokenKind.MIXED)
        return [
            Unit(make_unit_id(UnitKind.WORD, token.span), UnitKind.WORD, token.span)
            for token in ctx.doc.tokens
            if token.kind in kinds and len(token.span) >= self.MIN_LENGTH
        ]

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        mode = ctx.str_param("mode", "substitute")
        for rank, unit in enumerate(selected):
            word = unit.span.surface(ctx.text)
            rng = ctx.rng(unit.unit_id)
            # Interior positions only: first and last characters carry most of
            # a word's recognisability, and damaging them produces something a
            # reader parses as a different word rather than as a typo.
            #
            # Restricted to positions the mode can actually act on. For an
            # alphabetic token that is every interior position, so this is a
            # no-op there and the selection is unchanged. For an alphanumeric
            # one admitted by `include_mixed` it is not: the keyboard map holds
            # no digits, so a substitute landing on the `2` of `T2DM` produced
            # nothing and the token escaped on a coin flip. Drawing from the
            # positions that can move makes the opt-in mean what it says.
            # `_can_mutate` and not `_mutate`: the latter DRAWS from `rng` for a
            # substitute, so probing positions with it would consume the stream
            # before the real selection and change every previously generated
            # corpus. Nothing here touches the RNG until the position is chosen.
            usable = [i for i in range(1, len(word) - 1) if self._can_mutate(word, i, mode)]
            if not usable:
                continue
            position = usable[rng.below(len(usable))]
            mutated = self._mutate(word, position, mode, rng)
            if mutated == word:
                continue
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                mutated,
                rank=rank,
                reflow=ReflowPolicy.VERBATIM,
                meta={"mode": mode},
            )

    def _can_mutate(self, word: str, position: int, mode: str) -> bool:
        """Whether this mode could change this position, without drawing.

        Every mode but `substitute` acts on the character's place rather than
        its identity, so any interior position works. `substitute` needs a
        keyboard neighbour, and the map holds letters only — which is the whole
        reason an alphanumeric token could survive the operator untouched.
        """
        if mode in ("transpose", "delete", "double"):
            return True
        return bool(_ADJACENT.get(word[position].lower(), ""))

    def _mutate(self, word: str, position: int, mode: str, rng: Any) -> str:
        char = word[position]
        if mode == "transpose" and position + 1 < len(word):
            return word[:position] + word[position + 1] + char + word[position + 2 :]
        if mode == "delete":
            return word[:position] + word[position + 1 :]
        if mode == "double":
            return word[:position] + char + char + word[position + 1 :]
        neighbours = _ADJACENT.get(char.lower(), "")
        if not neighbours:
            return word
        replacement = neighbours[rng.below(len(neighbours))]
        if char.isupper():
            replacement = replacement.upper()
        return word[:position] + replacement + word[position + 1 :]


#: Retained as module-level names because `tests/test_ops_ocr.py` and
#: `metrics/describe.py` both read them, and because the assertion that no
#: digit-letter confusion is keyboard-adjacent is easiest to state against the
#: same object the operator uses. The tables themselves now live in
#: `resources/ocr_confusions.yaml` so their digest reaches the operator version.
_OCR_CONFUSIONS: dict[str, tuple[str, ...]] = load_table().glyphs
_OCR_LIGATURES: tuple[tuple[str, str], ...] = load_table().ligatures


class OcrConfusion:
    """Misread a character the way a scanner does: by shape, not by key.

    **Why this is not a mode of `input.typo`.** A typo model asks which keys sit
    next to each other; an OCR model asks which glyphs look alike. The two
    disagree almost everywhere — `m` and `rn` are opposite ends of the keyboard
    and nearly indistinguishable in print, while `q` and `w` are adjacent keys
    and share no shape. Folding OCR into the typo operator would make a claim
    about scanned documents using a keyboard's geometry.

    **Conditionally preserving, and the condition is where it lands.** `burn` ->
    `bum` is a different word; `patient` -> `patlent` is still readable as
    patient by a human and invisible to an exact-match lookup. Which happened is
    a property of the span, which is what the contract lattice exists to say.

    **Digits are in scope on purpose.** OCR on a scanned chart misreads `5.1`
    as `S.1`, and a numeric-protection rule that withheld those would model only
    the half of OCR that does not matter. The operator therefore declares
    `NUMERIC_VALUE`, `DOSAGE` and `LAB_BLOCK` as targets — the same reasoning
    `input.phonetic_confusion` uses.

    Ligature mode changes token LENGTH (`rn` -> `m`), which is the failure a
    downstream tokeniser cannot absorb, as distinct from a substitution it can.

    **The dose is a fraction of characters, not of words**, and that is the
    difference from `input.typo` that a methods table has to state. Typing
    errors are events per word typed, so the typo operator is dosed over
    eligible words. Scanning errors are events per character scanned, so this
    one is dosed over eligible character positions — the character error rate
    the OCR literature reports. Eligibility is still confined to positions
    *inside* a token of two or more characters, because that is where OCR errors
    land; the change is what "10%" counts, not where it lands.

    **`max_edits_per_token` bounds what a character dose can do to one word.**
    A rate over characters is the right denominator for a page and the wrong
    one for a word: at a saturating severity over a narrow target it substitutes
    every confusable position in a token at once, and `Hypertension` comes back
    as `Hvpcrfousj0h`. That is not a misreading a scanner makes — it is the term
    deleted and replaced with noise of the same length, a redaction wearing an
    operator's name. With the cap at 1 the operator emits what it documents,
    `patient` -> `patlent`, at any severity, which is the configuration for an
    arm aimed at one phenotype's evidence. Unset (the default), the cap
    contributes nothing to `params_canon`, so a run that does not name it
    selects and emits exactly what it would without the parameter.
    """

    meta = OperatorMeta(
        id="input.ocr_confusion",
        version="2.1.0",
        layer=Layer.CHAR,
        channel=Channel.INPUT,
        contract=Contract.CONDITIONALLY_PRESERVING,
        dose=DoseSpec(
            UnitKind.CHAR,
            denominator_doc=(
                "confusable character positions inside tokens of at least two "
                "characters; in ligature mode, occurrences of a confusable "
                "character run; at most `max_edits_per_token` positions per "
                "token when that parameter is set"
            ),
        ),
        # OCR reads whatever is on the page, including the numbers. Withholding
        # them would model only the harmless half of the phenomenon.
        targets=frozenset(
            {
                ProtectionClass.NUMERIC_VALUE,
                ProtectionClass.DOSAGE,
                ProtectionClass.LAB_BLOCK,
            }
        ),
        resources=(OCR_RESOURCE,),
        modes=("glyph", "ligature"),
        severity_levels=("0.05", "0.10", "0.15"),
        simulates="optical character recognition on a scanned or faxed chart",
    )

    id = meta.id
    version = meta.version
    layer = meta.layer
    channel = meta.channel
    contract = meta.contract
    dose = meta.dose
    targets = meta.targets
    resources = meta.resources

    #: A one-character token carries no context for a scanner to misread it in,
    #: and `_` placeholders and punctuation are single characters. Confining
    #: eligibility to tokens of two or more keeps every eligible character
    #: *inside a word*, which is where OCR errors land.
    MIN_LENGTH = 2

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        mode = ctx.str_param("mode", "glyph")
        cap = ctx.int_param("max_edits_per_token", 0)
        table = load_table()
        found: list[Unit] = []
        for token in ctx.doc.tokens:
            if len(token.span) < self.MIN_LENGTH:
                continue
            word = token.span.surface(ctx.text)
            base = token.span.start
            if mode == "ligature":
                spans = [
                    Span(base + index, base + index + len(src))
                    for index, src, _ in table.ligature_positions(word)
                ]
            else:
                spans = [Span(base + i, base + i + 1) for i in table.confusable_positions(word)]
            units = [Unit(make_unit_id(UnitKind.CHAR, span), UnitKind.CHAR, span) for span in spans]
            if cap > 0:
                units = self._cap(units, cap, ctx)
            found.extend(units)
        return found

    @staticmethod
    def _cap(units: list[Unit], cap: int, ctx: OpContext) -> list[Unit]:
        """Keep at most ``cap`` of one token's confusable positions.

        Ranked by the same key ``select`` uses, so the survivors are the ones a
        later draw would have preferred anyway: the cap narrows the eligible set
        without fighting the selection that follows, and severity ladders still
        nest because that key carries no severity.

        Falls back to document order when there is no seed material. `eligible`
        is called that way by the baseline describers, which want the count and
        never the identities.
        """
        if len(units) <= cap:
            return units
        material = ctx.material
        if material is None:
            kept = units[:cap]
        else:
            kept = sorted(units, key=lambda u: (unit_key(material, u.unit_id), u.unit_id))[:cap]
        return sorted(kept, key=lambda u: (u.span.start, u.span.end, u.unit_id))

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        mode = ctx.str_param("mode", "glyph")
        table = load_table()
        for rank, unit in enumerate(selected):
            source = unit.span.surface(ctx.text)
            rng = ctx.rng(unit.unit_id)
            if mode == "ligature":
                replacement = dict(table.ligatures).get(source)
            else:
                options = table.glyphs.get(source, ())
                replacement = options[rng.below(len(options))] if options else None
            if replacement is None or replacement == source:  # pragma: no cover
                continue
            yield make_edit(
                self.meta,
                unit,
                unit.span,
                replacement,
                rank=rank,
                reflow=ReflowPolicy.VERBATIM,
                meta={"mode": mode},
            )


OPERATORS = (PhoneticConfusion, Typo, OcrConfusion)

__all__ = ["OPERATORS", "OcrConfusion", "PhoneticConfusion", "Typo"]
