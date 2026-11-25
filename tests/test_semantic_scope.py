"""Aiming an assertion operator at one phenotype, and not editing terminators.

Two defects motivated this file, and both were silent — they produced a clean
run, a plausible artifact and a wrong number, which is the failure mode this
package spends most of its machinery preventing.

**A cue is not evidence.** `--phenotype-scope target` composes
`PhenotypeEvidence` onto every operator's target, and `_by_target` tests the
unit's own span. For a SEMANTIC operator the unit *is* the cue, and the `denies`
in `denies hypertension` is not itself evidence for hypertension, so every cue
was rejected. The run completed, the corpus came out byte-identical to the
baseline, and only `eligible_n = 0` on the dose ledger said so. Nothing in the
suite covered the combination: `test_phenotype_scope.py` deliberately exercises
the least clinical operators, on the argument that a whitespace collapse has
nothing to do with hypertension.

**A terminator asserts nothing.** `_cues_for_category` filtered on category and
not direction, so ConText's TERMINATE rules — the ones marking where a cue stops
reaching — were handed to the flip table, which has no entry for them and
applied the category default. `negated._default` is the empty string, so `but`
was deleted; `historical._default` is `current`, so `presentation` became
`current`. Measured over 40 MIMIC discharge summaries that was 250 of 1,359
cues: roughly a fifth of every arm was a discourse edit wearing a negation
operator's contract.

The `Governs` and direction tests below need no clinical extra — `Cue`,
`Assertion` and `AssertionIndex` are plain dataclasses and `context` imports
medspaCy lazily. Only the end-to-end class does.
"""

from __future__ import annotations

import pytest

from robustehr.concepts.context import Assertion, AssertionIndex, Cue
from robustehr.concepts.phenotype import Evidence, PhenotypeIndex
from robustehr.document import Document
from robustehr.ops.base import OpContext, Scope
from robustehr.ops.semantic import _FLIPPABLE_DIRECTIONS, _flippable
from robustehr.protect.registry import protect_document
from robustehr.target import (
    AllOf,
    Governs,
    Not,
    PhenotypeEvidence,
    TargetContext,
    governs_used,
    parse,
)
from robustehr.types import Span

TEXT = "The patient denies hypertension. She also denies chest pain today.\n"


def _span(word: str) -> Span:
    start = TEXT.index(word)
    return Span(start, start + len(word))


def _cue(literal: str, category: str = "NEGATED_EXISTENCE", direction: str = "FORWARD") -> Cue:
    span = _span(literal)
    return Cue(
        category=category,
        direction=direction,
        literal=literal.lower(),
        span=span,
        scope=Span(span.end, len(TEXT)),
    )


def _context(*, assertions: AssertionIndex | None, phenotypes: PhenotypeIndex) -> TargetContext:
    return TargetContext(
        doc=Document.from_text(TEXT, uid="t"),
        phenotypes=phenotypes,
        assertions=assertions,
    )


#: The `denies` governing hypertension, and the one governing chest pain. Only
#: the first is in scope for `governs(pheno=hypertension)`.
_HTN = _span("hypertension")
_FIRST_DENIES = Cue(
    category="NEGATED_EXISTENCE",
    direction="FORWARD",
    literal="deny",
    span=Span(TEXT.index("denies"), TEXT.index("denies") + 6),
    scope=Span(TEXT.index("denies") + 6, _HTN.end),
)
_SECOND_DENIES = Cue(
    category="NEGATED_EXISTENCE",
    direction="FORWARD",
    literal="deny",
    span=Span(TEXT.rindex("denies"), TEXT.rindex("denies") + 6),
    scope=Span(TEXT.rindex("denies") + 6, len(TEXT)),
)
_INDEX = AssertionIndex(
    assertions=(
        Assertion(span=_HTN, attributes=frozenset({"negated"}), cues=(_FIRST_DENIES,)),
        Assertion(
            span=_span("chest pain"),
            attributes=frozenset({"negated"}),
            cues=(_SECOND_DENIES,),
        ),
    ),
    requested_n=2,
)
_PHENOTYPES = PhenotypeIndex(
    evidence=(Evidence(span=_HTN, phenotype="hypertension", cui="C0020538"),),
    names=("hypertension",),
)


class TestGovernsTarget:
    def test_a_cue_governing_the_named_phenotype_is_admitted(self) -> None:
        ctx = _context(assertions=_INDEX, phenotypes=_PHENOTYPES)
        assert Governs(PhenotypeEvidence("hypertension")).admits(_FIRST_DENIES.span, ctx)

    def test_a_cue_governing_something_else_is_rejected(self) -> None:
        """The whole point: `denies chest pain` is a negation, just not this one."""
        ctx = _context(assertions=_INDEX, phenotypes=_PHENOTYPES)
        assert not Governs(PhenotypeEvidence("hypertension")).admits(_SECOND_DENIES.span, ctx)

    def test_pheno_star_admits_any_declared_phenotype(self) -> None:
        ctx = _context(assertions=_INDEX, phenotypes=_PHENOTYPES)
        assert Governs(PhenotypeEvidence()).admits(_FIRST_DENIES.span, ctx)

    def test_the_evidence_span_itself_is_not_admitted(self) -> None:
        """`governs(...)` selects the cue, not the thing it governs.

        Both would be wrong to conflate: `pheno=hypertension` already names the
        evidence, and an operator asking for one and getting both would silently
        double its dose.
        """
        ctx = _context(assertions=_INDEX, phenotypes=_PHENOTYPES)
        assert not Governs(PhenotypeEvidence("hypertension")).admits(_HTN, ctx)

    def test_no_assertion_index_admits_nothing(self) -> None:
        """The refusal `Concept` makes with no matcher, for the same reason."""
        ctx = _context(assertions=None, phenotypes=_PHENOTYPES)
        assert not Governs(PhenotypeEvidence("hypertension")).admits(_FIRST_DENIES.span, ctx)

    def test_canon_round_trips(self) -> None:
        target = Governs(PhenotypeEvidence("hypertension"))
        assert target.canon() == "governs(pheno=hypertension)"
        assert parse(target.canon()) == target

    def test_canon_round_trips_when_nested(self) -> None:
        target = AllOf(
            Governs(PhenotypeEvidence("hypertension")), Not(Governs(PhenotypeEvidence()))
        )
        assert parse(target.canon()) == target

    def test_phenotype_names_are_visible_through_governs(self) -> None:
        """Otherwise the CLI's undeclared-phenotype refusal cannot see the name.

        That refusal exists because naming a phenotype nobody declared admits
        nothing, silently — the same class of failure this target fixes, so it
        must not be reintroduced one level up.
        """
        from robustehr.target import phenotypes_named, wants_any_phenotype

        assert phenotypes_named(Governs(PhenotypeEvidence("hypertension"))) == {"hypertension"}
        assert wants_any_phenotype(Governs(PhenotypeEvidence()))

    def test_governs_used_sees_through_combinators(self) -> None:
        assert governs_used(AllOf(Not(Governs(PhenotypeEvidence())), PhenotypeEvidence("x")))
        assert not governs_used(AllOf(PhenotypeEvidence("x"), Not(PhenotypeEvidence("y"))))


class TestDirectionFilter:
    """A TERMINATE rule marks where a cue stops reaching; it asserts nothing."""

    @pytest.mark.parametrize("literal", ["but", "secondary", "cause for"])
    def test_a_terminator_is_not_flippable(self, literal: str) -> None:
        cue = Cue(
            category="NEGATED_EXISTENCE",
            direction="TERMINATE",
            literal=literal,
            span=Span(0, len(literal)),
            scope=Span(0, 0),
        )
        assert not _flippable(cue, ("NEGATED_EXISTENCE",))

    @pytest.mark.parametrize("direction", _FLIPPABLE_DIRECTIONS)
    def test_forward_and_backward_cues_are_flippable(self, direction: str) -> None:
        assert _flippable(_cue("denies", direction=direction), ("NEGATED_EXISTENCE",))

    def test_the_category_filter_still_applies(self) -> None:
        assert not _flippable(_cue("denies", category="FAMILY"), ("NEGATED_EXISTENCE",))


class TestRunnerRefusesGovernsWithoutAnIndex:
    def test_it_raises_rather_than_reporting_zero(self) -> None:
        """Reporting zero here is indistinguishable from a note with no cues.

        Which is exactly the bug. A configuration error must not present as a
        finding.
        """
        from robustehr.ops.registry import get, register_builtins
        from robustehr.runner import apply_operator, parse_severity

        register_builtins()
        operator = get("semantic.negation_flip")()
        doc = Document.from_text(TEXT, uid="t")
        with pytest.raises(ValueError, match="governs"):
            apply_operator(
                doc,
                operator,
                operator.meta,
                parse_severity("1.00"),
                scope=Scope(target=Governs(PhenotypeEvidence("hypertension"))),
                phenotypes=_PHENOTYPES,
            )


class TestOperatorStillWorksWithoutTheClinicalExtra:
    def test_eligible_returns_a_sequence(self) -> None:
        """`_cues_for_category` degrades to empty rather than raising.

        Pinned by `test_core_only.py::TestAssertionLayerDegrades`; restated here
        because the direction filter runs inside the same function and must not
        turn a degrade into a crash.
        """
        from robustehr.ops.registry import get, register_builtins

        register_builtins()
        operator = get("semantic.negation_flip")()
        doc = Document.from_text(TEXT, uid="t")
        ctx = OpContext(doc=doc, protection=protect_document(doc), scope=Scope())
        assert isinstance(list(operator.eligible(ctx)), list)
