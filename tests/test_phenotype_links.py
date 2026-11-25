"""Every declared phenotype must resolve to concepts. Enforced, not audited.

`validation/phenotype/scripts/phenotype_link_audit.py` answers the question for the definitions that
exist now and prices how reachable each set is in text. This is the part that has
to keep holding: a phenotype added to `phenotypes.yaml` with a mistyped seed, a
retired SNOMED code, or a code that is a hierarchy leaf expands to an empty or
one-element set, and **nothing downstream complains**. The run reports
`evidence_touch: 0`, which is what a note with no mention of the phenotype also
reports. The failure looks exactly like a finding.

The MIPA panel walked straight into two of these on the way in — a seed whose
closure blew up to 9,712 concepts, and two sets that recover none of their own
evidence — so the gate now covers the depth bound and the precision counterpart
as well as the links themselves.

Two tiers, because only one of them can run everywhere:

* the shape of the declaration — no terminology needed, always runs;
* the expansion — needs the local crosswalk and `isa` cache, both derived from
  licensed UMLS content and both gitignored, so it skips when they are absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from robustehr.concepts.phenotype import declare, load_definitions

ISA = Path("data/umls_isa_mth.json")
CROSSWALK = Path("data/snomed_el")

needs_terminology = pytest.mark.skipif(
    not (ISA.exists() and (CROSSWALK / "cui_snomed.json").exists()),
    reason="no local UMLS crosswalk or isa cache",
)

DEFINITIONS = load_definitions()
NAMES = sorted(DEFINITIONS)


@pytest.fixture(scope="module")
def expansion() -> dict[str, object]:
    from robustehr.concepts import hierarchy
    from robustehr.concepts.phenotype import load_maps

    isa = hierarchy.load(ISA)
    code_to_cuis, cui_to_codes = load_maps(CROSSWALK)
    return {
        name: (
            declare(name, d.seeds, isa, code_to_cuis, cui_to_codes),
            {c for code in d.seeds for c in code_to_cuis.get(code, ())},
        )
        for name, d in DEFINITIONS.items()
    }


class TestDeclarationShape:
    """No terminology required — these catch a typo before a build does."""

    def test_there_are_definitions(self) -> None:
        assert NAMES

    @pytest.mark.parametrize("name", NAMES)
    def test_every_phenotype_declares_at_least_one_seed(self, name: str) -> None:
        assert DEFINITIONS[name].seeds

    @pytest.mark.parametrize("name", NAMES)
    def test_seeds_are_snomed_identifiers(self, name: str) -> None:
        """SNOMED CT concept ids are digit strings.

        Cheap, and it catches the likely paste error: a CUI (``C0018801``) or a
        label dropped into the seed list, which resolves to nothing and expands
        to an empty set without raising.
        """
        for seed in DEFINITIONS[name].seeds:
            assert seed.isdigit(), f"{name}: seed {seed!r} is not a SNOMED identifier"

    @pytest.mark.parametrize("name", NAMES)
    def test_a_label_and_a_name_that_agree_in_style(self, name: str) -> None:
        assert DEFINITIONS[name].label
        assert name == name.lower().replace(" ", "_")

    def test_names_are_unique(self) -> None:
        assert len(NAMES) == len({n.lower() for n in NAMES})

    @pytest.mark.parametrize("name", NAMES)
    def test_recall_is_in_range(self, name: str) -> None:
        recall = DEFINITIONS[name].measured_set_recall
        assert recall is None or 0.0 <= recall <= 1.0

    @pytest.mark.parametrize("name", NAMES)
    def test_unmeasured_is_allowed_only_when_it_is_explained(self, name: str) -> None:
        """Null recall must mean "not measurable here", and must say so.

        A set with no measured recall must not ship *silently* — `phenotypes.yaml`
        says every protect-mode result is conditional on that number, so a
        definition that omits it is not unconditional, it is unquantified.

        But the honest case is real: `systemic_lupus_erythematosus` has one gold
        span in this corpus, and inventing a rate from n=1 would be worse than
        declaring none. So null is permitted **and must carry a note**, which is
        what keeps it from becoming the easy way past this gate.
        """
        definition = DEFINITIONS[name]
        if definition.measured_set_recall is None:
            assert definition.note, f"{name}: null recall needs a note saying why"
            assert definition.gold_evidence_spans is not None, (
                f"{name}: null recall must still report how many gold spans there were — "
                "that is what distinguishes 'not measurable' from 'not measured'"
            )

    @pytest.mark.parametrize("name", NAMES)
    def test_a_weak_set_carries_a_note(self, name: str) -> None:
        """Below 0.6 the number needs an explanation beside it, not in a paper.

        `heart_failure` at 0.449 is usable if a reader knows it is the
        abbreviation gap and not a corpus with no heart failure in it. Bare, it
        is a trap.
        """
        definition = DEFINITIONS[name]
        if definition.measured_set_recall is not None and definition.measured_set_recall < 0.6:
            assert definition.note, f"{name}: recall {definition.measured_set_recall} needs a note"

    @pytest.mark.parametrize("name", NAMES)
    def test_precision_accompanies_recall(self, name: str) -> None:
        """Recall without precision is the measurement that hides a blow-up.

        Recall rises monotonically with closure size, so a set that swallows
        half the terminology scores well on it. `pulmonary_embolism` at the
        file-wide depth posts 0.669 recall on 9,712 concepts; its precision is
        0.049. Shipping the first number without the second is what would let
        that set look adequate.

        Precision may be null only when recall is null (nothing measurable) or
        when the matcher claimed nothing at all, which leaves it no denominator.
        """
        definition = DEFINITIONS[name]
        if definition.measured_set_recall:
            assert definition.measured_set_precision is not None, (
                f"{name}: has recall {definition.measured_set_recall} and no precision"
            )
        if definition.measured_set_precision is not None:
            assert 0.0 <= definition.measured_set_precision <= 1.0


@needs_terminology
class TestExpansion:
    """The links that need the local release."""

    @pytest.mark.parametrize("name", NAMES)
    def test_every_seed_resolves_to_a_cui(self, name: str, expansion: dict) -> None:
        _, seed_cuis = expansion[name]
        assert seed_cuis, f"{name}: no seed code resolves to a CUI"

    @pytest.mark.parametrize("name", NAMES)
    def test_the_concept_set_is_not_empty(self, name: str, expansion: dict) -> None:
        phenotype, _ = expansion[name]
        assert phenotype.concept_cuis, f"{name}: empty concept set — targeting it would be silent"

    @pytest.mark.parametrize("name", NAMES)
    def test_expansion_reaches_past_the_seeds(self, name: str, expansion: dict) -> None:
        """A set equal to its seeds is a declaration that did not expand.

        It still "has concepts", so no emptiness check catches it — but only the
        exact seed term is ever evidence, and the phenotype silently degrades
        into a single-concept lookup.
        """
        phenotype, seed_cuis = expansion[name]
        assert len(phenotype.concept_cuis) > len(seed_cuis), f"{name}: closure added nothing"

    @pytest.mark.parametrize("name", NAMES)
    def test_the_seeds_are_members_of_their_own_set(self, name: str, expansion: dict) -> None:
        """`descendants` includes the seeds; a phenotype's own root is evidence."""
        phenotype, seed_cuis = expansion[name]
        assert seed_cuis <= set(phenotype.concept_cuis)

    @pytest.mark.parametrize("name", NAMES)
    def test_source_codes_come_back_out(self, name: str, expansion: dict) -> None:
        """Both identifier systems are materialized, so gold spans can be tested
        in their own namespace without a lossy round trip."""
        phenotype, _ = expansion[name]
        assert phenotype.concept_codes
        assert set(DEFINITIONS[name].seeds) <= set(phenotype.concept_codes)


@needs_terminology
class TestDepthBound:
    """A per-phenotype `max_depth` must actually bind.

    `pulmonary_embolism` is the only definition using it, and it exists because
    one `MTH RN` edge makes *Vascular Diseases* a descendant of PE: unbounded,
    the set is 9,712 concepts at precision 0.049. If the override were silently
    ignored the set would still build, still expand, and still report a recall —
    a higher one — so nothing downstream would flag it.
    """

    def test_the_bound_is_applied_not_just_stored(self) -> None:
        from robustehr.concepts import hierarchy
        from robustehr.concepts.phenotype import build, load_maps

        isa = hierarchy.load(ISA)
        code_to_cuis, cui_to_codes = load_maps(CROSSWALK)
        bounded = build(["pulmonary_embolism"], isa, code_to_cuis, cui_to_codes)[0]
        assert DEFINITIONS["pulmonary_embolism"].max_depth == 1
        # Asserted against the DISORDER closure, which is the only thing
        # `max_depth` governs. The medication and finding facets are added
        # deliberately by `build` and are not hierarchy descent, so a total that
        # includes them cannot answer whether the bound bound. Before the facets
        # were wired in the two numbers were the same and the total was a fair
        # proxy; now it is not, and using it would test the wrong thing.
        disorder = bounded.facet_sizes.get("disorder", len(bounded.concept_cuis))
        assert disorder < 100, f"depth bound ignored: {disorder} disorder concepts"

    def test_a_phenotype_without_a_bound_uses_the_caller_depth(self) -> None:
        from robustehr.concepts import hierarchy
        from robustehr.concepts.phenotype import build, load_maps

        isa = hierarchy.load(ISA)
        code_to_cuis, cui_to_codes = load_maps(CROSSWALK)
        shallow = build(["hypertension"], isa, code_to_cuis, cui_to_codes, max_depth=1)[0]
        deep = build(["hypertension"], isa, code_to_cuis, cui_to_codes, max_depth=6)[0]
        assert len(shallow.concept_cuis) < len(deep.concept_cuis)


class TestCohorts:
    def test_the_mipa_panel_is_declared(self) -> None:
        from robustehr.concepts.phenotype import in_cohort

        assert len(in_cohort("mipa")) >= 14

    def test_an_unknown_cohort_is_empty_not_an_error(self) -> None:
        from robustehr.concepts.phenotype import in_cohort

        assert in_cohort("not_a_study") == ()


#: A phenotype below this is too thin to target meaningfully: a corruption aimed
#: at it would find almost nothing in a note, and `evidence_touch: 0` would read
#: as robustness rather than as an empty set.
MIN_CONCEPTS = 50


@needs_terminology
class TestConceptFloor:
    """Every phenotype must carry a usable number of concepts across its facets.

    **This is a regression gate, not an aspiration.** The facets are built from
    four independent sources, and narrowing any one of them moves the total a
    long way without touching a count anyone is watching: making the finding
    facet proposals-only took `clostridioides_difficile` from 404 concepts to
    60 in a single commit, and applying the vetting verdicts took its medication
    facet from 8 to 3. Both were correct changes. A third such change is how a
    phenotype ends up too thin to target, and nothing downstream would say so —
    a run against an under-populated set reports `evidence_touch: 0`, which is
    what a note that never mentioned the phenotype also reports.
    """

    #: Phenotypes measured below the floor, each with the size the waiver was
    #: granted at — recorded so further shrinkage still fails. Currently empty:
    #: the proposed-facet vetting (2026-08-17) briefly took
    #: clostridioides_difficile to 45, and the closure layer (RxNorm identity
    #: variants of its kept antibiotics plus vetted neighborhood concepts)
    #: brought it to 189 the same day.
    BELOW_FLOOR_PENDING_REVIEW: ClassVar[dict[str, int]] = {}

    @staticmethod
    @pytest.fixture(scope="class")
    def totals() -> dict[str, int]:
        """The RUNTIME sets, exactly as `build()` ships them.

        This used to reconstruct the union by hand from the facet sources, and
        the reconstruction drifted from the real thing twice: `build()` grew
        the facets (making the manual `disorder` term circular) and the
        proposed facet grew a vetting gate the manual union never applied. The
        floor guards what a run actually targets, so measure that.
        """
        from robustehr.concepts import hierarchy
        from robustehr.concepts.phenotype import build, load_maps

        isa = hierarchy.load(ISA)
        code_to_cuis, cui_to_codes = load_maps(CROSSWALK)
        return {
            p.name: len(p.concept_cuis)
            for p in build(sorted(DEFINITIONS), isa, code_to_cuis, cui_to_codes)
        }

    @pytest.mark.parametrize("name", NAMES)
    def test_phenotype_meets_the_floor(self, name: str, totals: dict[str, int]) -> None:
        waived = self.BELOW_FLOOR_PENDING_REVIEW.get(name)
        if waived is not None:
            assert totals[name] >= waived, (
                f"{name}: {totals[name]} concepts, below even its recorded "
                f"waiver of {waived} — the set shrank again since the waiver"
            )
            return
        assert totals[name] >= MIN_CONCEPTS, (
            f"{name}: {totals[name]} concepts, below the {MIN_CONCEPTS} floor. "
            "Add finding or medication seeds, or re-run validation/phenotype/scripts/phenotype_propose.py"
        )

    def test_every_facet_source_contributes_somewhere(self, totals: dict[str, int]) -> None:
        """A source that contributes to nothing has silently stopped working.

        Four sources build these sets and three of them are easy to break
        without any test failing — a bad relation direction, an unread frozen
        file, a default that turned expansion off. Asserting each still reaches
        at least one phenotype catches the whole class.
        """
        from robustehr.concepts import facets

        assert any(facets.load_proposals().values()), "no phenotype has grounded proposals"
        assert any(facets.load_vetting().values()), "no phenotype has vetting verdicts"
        assert any(facets.load_closure().values()), "no phenotype has closure candidates"
        assert any(d.medication_seeds for d in DEFINITIONS.values()), "no declared medications"
        assert any(d.finding_seeds for d in DEFINITIONS.values()), "no declared finding seeds"
