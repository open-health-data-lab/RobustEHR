"""The decisive surfaces from the evidence audit must fall inside the target set.

The corruption experiment's treatment is only valid if a `pheno=X` target
covers the mention the phenotype call actually rides on. The manual audit
(`data/phenotype_review/evidence_audit.md`) caught the sets missing exactly
those mentions — "Lasix" grounding to a brand CUI, "diastolic heart failure"
to a sibling of the hfpef seed, "metastasis" to a concept with no isa edge at
all — and the closure layer exists to capture them. Each fixture here is one
row of that audit, frozen as a regression.

The NEGATIVE fixtures are the other half of the guarantee: the audit also
found matcher misgroundings ("CHF" -> Congenital Hepatic Fibrosis, "DM Type
II" -> Split cord malformation type II), and no closure, however broad, may
"fix" those by set widening — that would encode the error instead of the
evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from robustehr.concepts.facets import FacetEdges, load_closure, medications

ISA = Path("data/umls_isa_mth.json")
CROSSWALK = Path("data/snomed_el")
INDEX = Path("data/quickumls_index")

from robustehr.concepts import surface as surface_mod  # noqa: E402
from robustehr.concepts.matcher import index_present  # noqa: E402

needs_terminology = pytest.mark.skipif(
    not (ISA.exists() and (CROSSWALK / "cui_snomed.json").exists()),
    reason="no local UMLS crosswalk or isa cache",
)
needs_index = pytest.mark.skipif(not index_present(INDEX), reason="no QuickUMLS index built")

#: (surface a note actually wrote, phenotypes whose target set must catch it).
#: Every row is a mechanism-(a) case from the evidence audit.
DECISIVE = [
    ("Lasix", ["heart_failure", "hfpef", "hfref"]),
    ("Furosemide 20 mg", ["heart_failure", "hfpef", "hfref"]),
    ("flagyl", ["clostridioides_difficile"]),
    ("Metronidazole 500 mg", ["clostridioides_difficile"]),
    ("diastolic heart failure", ["hfpef"]),
    ("Diastolic CHF", ["hfpef"]),
    ("Systolic Heart Failure", ["hfref"]),
    ("metastatic disease", ["metastatic_cancer"]),
    ("metastases", ["metastatic_cancer"]),
    ("metastatic renal cell carcinoma", ["metastatic_cancer"]),
    ("Gastric Bypass", ["obesity"]),
    ("insulin", ["diabetes_mellitus", "type_1_diabetes", "type_2_diabetes"]),
]

#: (misgrounded CUI, its real meaning, phenotypes that must NOT contain it).
MISGROUNDINGS = [
    ("C0009714", "Congenital Hepatic Fibrosis (via 'CHF')", ["heart_failure", "hfpef", "hfref"]),
    (
        "C5680360",
        "Split cord malformation type II (via 'DM Type II')",
        ["diabetes_mellitus", "type_1_diabetes", "type_2_diabetes"],
    ),
]


@pytest.fixture(scope="module")
def built():
    from robustehr.concepts import hierarchy
    from robustehr.concepts.phenotype import build, load_definitions, load_maps

    isa = hierarchy.load(ISA)
    code_to_cuis, cui_to_codes = load_maps(CROSSWALK)
    names = sorted(load_definitions())
    return {p.name: p for p in build(names, isa, code_to_cuis, cui_to_codes)}


@pytest.fixture(scope="module")
def matcher():
    from robustehr.concepts.matcher import ConceptMatcher

    return ConceptMatcher(INDEX)


def _closure_vetted() -> bool:
    from robustehr.concepts.facets import load_vetting

    return any("closure" in row for row in load_vetting().values())


@needs_terminology
@needs_index
class TestDecisiveSurfaces:
    @pytest.mark.parametrize(("surface", "phenotypes"), DECISIVE, ids=[s for s, _ in DECISIVE])
    def test_the_surface_falls_inside_the_target_set(
        self, surface: str, phenotypes: list[str], built, matcher
    ) -> None:
        if not _closure_vetted():
            pytest.skip("closure facet not vetted yet: run phenotype_vet.py --facet closure")
        returned = {m.cui for m in matcher.annotate(surface).mentions}
        assert returned, f"the matcher emits nothing for {surface!r}"
        for name in phenotypes:
            pheno = built[name]
            by_concept = bool(returned & pheno.concept_cuis)
            # The aim has two warrants, so this fixture tests the aim rather
            # than one of its implementations. A surface the closure cannot
            # reach but an anchor names exactly is still inside the target, and
            # asserting only the first would fail a set that had been correctly
            # tightened — which is the direction the specificity screen and the
            # vetting criterion both push.
            by_surface = pheno.anchors is not None and bool(
                surface_mod.anchor_spans(surface, pheno.anchors)
            )
            assert by_concept or by_surface, (
                f"{surface!r} grounds to {sorted(returned)}, none of which is in "
                f"the {name} set, and no declared anchor matches it either — "
                "the decision basis escapes the target on both warrants"
            )


@needs_terminology
class TestMisgroundingsStayOut:
    @pytest.mark.parametrize(
        ("cui", "meaning", "phenotypes"), MISGROUNDINGS, ids=[c for c, _, _ in MISGROUNDINGS]
    )
    def test_a_misgrounded_cui_is_never_admitted(
        self, cui: str, meaning: str, phenotypes: list[str], built
    ) -> None:
        for name in phenotypes:
            assert cui not in built[name].concept_cuis, (
                f"{cui} ({meaning}) entered the {name} set — a matcher error "
                "was 'fixed' by set widening"
            )


class TestIdentityExpansion:
    """Unit-level: no terminology, no index, synthetic edges."""

    EDGES = FacetEdges(
        treats={"D1": ("I1",)},
        parents={},
        ingredient_of={},
        variants={"I1": ("B1", "P1"), "I2": ("B2",)},
    )

    def test_variants_ride_on_admitted_ingredients(self) -> None:
        facet = medications(frozenset(), frozenset({"D1"}), self.EDGES)
        assert {"I1", "B1", "P1"} <= facet.cuis
        assert facet.provenance["B1"] == "identity"
        assert facet.provenance["P1"] == "identity"

    def test_variants_of_a_rejected_ingredient_stay_out(self) -> None:
        facet = medications(frozenset(), frozenset({"D1"}), self.EDGES, vetted=frozenset())
        assert "B1" not in facet.cuis, "identity must ride the vetting gate"

    def test_identity_needs_no_review(self) -> None:
        facet = medications(frozenset(), frozenset({"D1"}), self.EDGES)
        assert "B1" not in facet.needs_review()
        assert "P1" not in facet.needs_review()


@needs_terminology
class TestStrictGate:
    def test_no_vetting_row_admits_nothing(self, built) -> None:
        """Candidates exist for every phenotype; a phenotype whose vetting file
        carries no closure row must gain zero closure concepts, because raw
        graph output unjudged is exactly how a misgrounding would slip in."""
        from robustehr.concepts.facets import load_vetting

        candidates = load_closure()
        vetting = load_vetting()
        for name, phenotype in built.items():
            has_row = "closure" in vetting.get(name, {})
            size = phenotype.facet_sizes.get("closure", 0) if phenotype.facet_sizes else 0
            if not has_row:
                assert size == 0, f"{name}: closure admitted without a vetting row"
            if has_row and candidates.get(name):
                kept = vetting[name]["closure"]
                assert kept <= candidates[name], (
                    f"{name}: kept closure concepts that are not candidates"
                )
