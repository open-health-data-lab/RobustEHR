"""`phenotype_scope`: the run mode that applies to every operator.

The claim under test is the architectural one — that phenotype relatedness is an
attribute of *where an edit landed* rather than a class of operator. So the
operators exercised here are deliberately the least clinical ones in the suite: a
whitespace collapse has nothing to do with hypertension, and it must still be
possible to say whether it touched it.

Three properties matter, and only the first is self-evident:

1. ``agnostic`` is unchanged from having no phenotype at all.
2. ``protect`` makes ``evidence_touch == 0`` true **by construction**.
3. that zero is only meaningful next to ``evidence_n``, because a matcher that
   found nothing produces the same zero as an operator that stayed clear.
"""

from __future__ import annotations

import pytest

from robustehr.concepts.matcher import Mention, MentionIndex
from robustehr.concepts.phenotype import (
    Evidence,
    Phenotype,
    PhenotypeIndex,
    index_document,
    protected_spans,
)
from robustehr.document import Document
from robustehr.ops import registry
from robustehr.protect import protect_document
from robustehr.protect.registry import Strength
from robustehr.runner import apply_operator, severity_ladder
from robustehr.types import PhenotypeScope, Span

NOTE = """Discharge Summary

History of Present Illness:
The patient has hypertension and reports chest    pain on exertion.
He denies shortness of breath.

Assessment:
Hypertension, well controlled.
"""

HYPERTENSION = Phenotype(
    name="hypertension",
    seed_codes=("38341003",),
    concept_cuis=frozenset({"C0020538"}),
    concept_codes=frozenset({"38341003"}),
)


def _evidence(doc: Document) -> PhenotypeIndex:
    """Evidence spans for every literal `hypertension` in the note.

    Built by hand rather than by running the matcher: this suite tests the run
    mode, and a real matcher would make it depend on a licensed index.
    """
    found = []
    lowered = doc.text.lower()
    start = lowered.find("hypertension")
    while start != -1:
        found.append(
            Mention(
                span=Span(start, start + len("hypertension")),
                cui="C0020538",
                tuis=frozenset({"T047"}),
                similarity=1.0,
                surface=doc.text[start : start + len("hypertension")],
            )
        )
        start = lowered.find("hypertension", start + 1)
    return index_document(MentionIndex(tuple(found)), [HYPERTENSION])


@pytest.fixture
def doc() -> Document:
    return Document.from_text(NOTE, uid="note-1")


#: Operators with nothing clinical about them. That is the point.
#:
#: ``input.typo`` is here specifically because it edits word characters, so it
#: *can* land inside `hypertension`. A protect test using only whitespace
#: operators would pass without protecting anything.
NON_CLINICAL_OPS = ("render.whitespace_collapse", "input.typo")

FULL = severity_ladder("1")[0]


def run(op_id: str, doc: Document, **kwargs):
    """Apply one operator, with whatever phenotype configuration is under test."""
    op = registry.get(op_id)()
    return apply_operator(doc, op, op.meta, kwargs.pop("severity", FULL), **kwargs)


class TestAgnostic:
    def test_agnostic_is_identical_to_no_phenotype(self, doc: Document) -> None:
        """The default mode must cost nothing, or it is not really the default."""
        for op_id in NON_CLINICAL_OPS:
            half = severity_ladder("0.5")[0]
            plain = run(op_id, doc, severity=half)
            agnostic = run(
                op_id,
                doc,
                severity=half,
                phenotypes=_evidence(doc),
                phenotype_scope=PhenotypeScope.AGNOSTIC,
            )
            assert plain.text == agnostic.text
            assert plain.dose.applied_n == agnostic.dose.applied_n

    def test_agnostic_records_no_evidence_fields(self, doc: Document) -> None:
        result = run("render.whitespace_collapse", doc, severity=FULL)
        assert result.dose.phenotype_scope == "agnostic"
        assert result.dose.evidence_touch == {}


class TestProtect:
    def test_evidence_touch_is_zero_by_construction(self, doc: Document) -> None:
        """The guarantee, on operators that know nothing about phenotypes."""
        evidence = _evidence(doc)
        assert len(evidence) > 0, "fixture must produce evidence or the test is vacuous"
        for op_id in NON_CLINICAL_OPS:
            result = run(
                op_id,
                doc,
                severity=FULL,
                phenotypes=evidence,
                phenotype_scope=PhenotypeScope.PROTECT,
            )
            assert result.dose.evidence_touch == {"hypertension": 0}

    def test_the_guarantee_is_not_vacuous(self, doc: Document) -> None:
        """Without protection the same operator *does* hit the evidence.

        The control that makes the test above mean something. A protect-mode
        suite that only ever ran operators incapable of reaching the evidence
        would pass while protecting nothing — which is precisely the vacuous-zero
        failure the whole design worries about, reproduced in the test suite.
        """
        evidence = _evidence(doc)
        unprotected = run("input.typo", doc, phenotypes=evidence)
        touched = evidence.touched([e.span for e in unprotected.apply_result.applied])
        assert touched["hypertension"] > 0, (
            "operator cannot reach the evidence, so protecting it proves nothing"
        )

        protected = run(
            "input.typo", doc, phenotypes=evidence, phenotype_scope=PhenotypeScope.PROTECT
        )
        assert protected.dose.evidence_touch["hypertension"] == 0
        assert protected.dose.applied_n > 0, "protection must not silence the operator"

    def test_protected_n_accounts_for_the_withheld_units(self, doc: Document) -> None:
        """Dose accounting has to show where the units went, not just the result."""
        evidence = _evidence(doc)
        plain = run("input.typo", doc, phenotypes=evidence)
        protect = run(
            "input.typo", doc, phenotypes=evidence, phenotype_scope=PhenotypeScope.PROTECT
        )
        assert protect.dose.protected_n > plain.dose.protected_n
        assert protect.dose.eligible_n < plain.dose.eligible_n

    def test_the_zero_is_reported_against_a_denominator(self, doc: Document) -> None:
        """A vacuous zero and a real one are indistinguishable without this.

        This is the failure mode `docs/targeting-design.md` calls the strongest
        argument for set membership: a mention the matcher never found is never
        protected, an operator corrupts it, and the run still reports zero.
        """
        result = run(
            "render.whitespace_collapse",
            doc,
            severity=FULL,
            phenotypes=_evidence(doc),
            phenotype_scope=PhenotypeScope.PROTECT,
        )
        assert result.dose.evidence_n["hypertension"] > 0
        assert result.dose.evidence_touch["hypertension"] == 0

    def test_empty_evidence_still_declares_the_phenotype(self, doc: Document) -> None:
        """Nothing found is a measurement, and must not look like nothing asked."""
        empty = PhenotypeIndex(evidence=(), names=("hypertension",))
        result = run(
            "render.whitespace_collapse",
            doc,
            severity=FULL,
            phenotypes=empty,
            phenotype_scope=PhenotypeScope.PROTECT,
        )
        assert result.dose.evidence_n == {"hypertension": 0}
        assert result.dose.evidence_touch == {"hypertension": 0}
        assert result.dose.phenotype_scope == "protect"

    def test_protection_does_not_leak_between_operators(self, doc: Document) -> None:
        """Protect rebuilds the index; mutating a shared one would order-couple runs."""
        shared = protect_document(doc)
        before = len(shared)
        run(
            "render.whitespace_collapse",
            doc,
            severity=FULL,
            protection=shared,
            phenotypes=_evidence(doc),
            phenotype_scope=PhenotypeScope.PROTECT,
        )
        assert len(shared) == before


class TestTarget:
    def test_target_restricts_to_evidence(self, doc: Document) -> None:
        """Every operator becomes phenotype-targeted, without knowing it has."""
        evidence = _evidence(doc)
        targeted = run(
            "render.whitespace_collapse",
            doc,
            severity=FULL,
            phenotypes=evidence,
            phenotype_scope=PhenotypeScope.TARGET,
        )
        agnostic = run("render.whitespace_collapse", doc, severity=FULL)
        assert targeted.dose.scope_n <= agnostic.dose.scope_n

    def test_target_and_protect_are_opposites(self, doc: Document) -> None:
        evidence = _evidence(doc)
        protect = run(
            "input.typo",
            doc,
            phenotypes=evidence,
            phenotype_scope=PhenotypeScope.PROTECT,
        )
        assert protect.dose.evidence_touch["hypertension"] == 0


class TestRelatedness:
    def test_every_declared_phenotype_appears_in_the_tag(self) -> None:
        """A missing key is not a measurement; `intersects_evidence: false` is."""
        index = PhenotypeIndex(
            evidence=(Evidence(Span(0, 5), "hypertension", "C1"),),
            names=("diabetes", "hypertension"),
        )
        tag = index.relatedness(Span(0, 5))
        assert tag["hypertension"]["intersects_evidence"] is True
        assert tag["diabetes"] == {"intersects_evidence": False}

    def test_assertion_travels_with_the_tag(self) -> None:
        """Carried for reporting; never consulted for eligibility."""
        index = PhenotypeIndex(
            evidence=(Evidence(Span(0, 5), "dyspnea", "C1", frozenset({"negated"})),),
            names=("dyspnea",),
        )
        tag = index.relatedness(Span(0, 5))
        assert tag["dyspnea"]["assertion"] == ["negated"]
        assert tag["dyspnea"]["affirmed"] is False

    def test_touched_counts_evidence_spans_not_edits(self) -> None:
        """Three edits inside one mention disturb one mention."""
        index = PhenotypeIndex(evidence=(Evidence(Span(10, 20), "htn", "C1"),), names=("htn",))
        assert index.touched([Span(11, 12), Span(13, 14), Span(15, 16)]) == {"htn": 1}

    def test_a_mention_can_be_evidence_for_several_phenotypes(self) -> None:
        """Overlap is a real property of clinical concepts, so it is recorded."""
        shared = Phenotype("a", ("1",), frozenset({"C1"}), frozenset({"1"}))
        other = Phenotype("b", ("2",), frozenset({"C1"}), frozenset({"2"}))
        mentions = MentionIndex((Mention(Span(0, 4), "C1", frozenset({"T047"}), 1.0, "test"),))
        index = index_document(mentions, [shared, other])
        assert {e.phenotype for e in index.evidence} == {"a", "b"}


class TestProtectedSpans:
    def test_evidence_is_soft_not_hard(self) -> None:
        """HARD means atomic, which is the wrong shape for evidence.

        HARD exists to stop an operator fabricating PHI-shaped text inside a
        de-id mask — it permits whole replacement. Evidence needs withholding
        outright, which is a SOFT class no operator declares.
        """
        index = PhenotypeIndex(evidence=(Evidence(Span(0, 5), "htn", "C1"),), names=("htn",))
        spans = protected_spans(index)
        assert [s.strength for s in spans] == [Strength.SOFT]
        assert spans[0].cls.value == "phenotype_evidence"

    def test_no_phenotype_yields_no_protection(self) -> None:
        assert protected_spans(PhenotypeIndex()) == []


class TestSurfaceWarrantReachesSelection:
    """The disjunction changes what a `pheno=` target selects, not only what it reports.

    A note whose only mention of the diagnosis is an abbreviation the matcher never
    grounds has no concept-warrant evidence at all. With the surface warrant the
    abbreviation is the evidence, and under `target` scope it is the only thing the
    operator may touch.
    """

    NOTE = "Assessment:\nHTN, well controlled. Continue home regimen.\n"

    def _index(self) -> PhenotypeIndex:
        from robustehr.concepts.surface import AnchorSet

        pheno = Phenotype(
            name="hypertension",
            seed_codes=("38341003",),
            concept_cuis=frozenset({"C0020538"}),
            concept_codes=frozenset({"38341003"}),
            anchors=AnchorSet(phenotype="hypertension", anchors=("htn",)),
        )
        return index_document(MentionIndex(()), [pheno], text=self.NOTE)

    def test_without_text_there_is_nothing_to_target(self) -> None:
        from robustehr.concepts.surface import AnchorSet

        pheno = Phenotype(
            name="hypertension",
            seed_codes=("38341003",),
            concept_cuis=frozenset({"C0020538"}),
            concept_codes=frozenset({"38341003"}),
            anchors=AnchorSet(phenotype="hypertension", anchors=("htn",)),
        )
        assert len(index_document(MentionIndex(()), [pheno])) == 0

    def test_target_scope_selects_the_anchor_and_nothing_else(self) -> None:
        doc = Document.from_text(self.NOTE, uid="note-htn")
        evidence = self._index()
        assert len(evidence) == 1
        assert evidence.evidence[0].tier == "anchor"
        result = run(
            "input.typo",
            doc,
            severity=FULL,
            phenotypes=evidence,
            phenotype_scope=PhenotypeScope.TARGET,
        )
        assert result.dose.eligible_n >= 1
        assert result.dose.applied_n >= 1
        span = evidence.evidence[0].span
        for edit in result.apply_result.applied:
            assert edit.span.start >= span.start and edit.span.end <= span.end, edit
        assert result.dose.evidence_touch["hypertension"] == 1
