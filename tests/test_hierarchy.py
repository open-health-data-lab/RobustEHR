"""Concept-set expansion: direction, bounds, and the phenotype declaration.

The direction test is the important one. Reversing the ``isa`` edges produces an
*ancestor* closure that looks entirely plausible — non-empty, correctly typed,
full of related concepts — and silently measures the wrong thing. It shipped
reversed once and was caught only by a concept pair whose direction is known
independently. That pair is pinned here.
"""

from __future__ import annotations

import json

import pytest

from robustehr.concepts.hierarchy import Hierarchy, load
from robustehr.eval.phenotype import Phenotype, PhenotypeScore, declare, load_maps

# Diverticulosis (C1510475) is the isa PARENT of Diverticulosis of large
# intestine (C4518471); MRREL records that as cui1=C1510475, cui2=C4518471,
# rel=CHD, rela=isa. The extractor must read cui1 as the parent.
DIVERTICULOSIS = "C1510475"
DIVERTICULOSIS_LARGE_INTESTINE = "C4518471"


@pytest.fixture
def small() -> Hierarchy:
    return Hierarchy(
        children={
            DIVERTICULOSIS: (DIVERTICULOSIS_LARGE_INTESTINE,),
            DIVERTICULOSIS_LARGE_INTESTINE: ("C_SIGMOID",),
            "C_SIGMOID": ("C_DEEP",),
        }
    )


def test_descendants_run_from_general_to_specific(small: Hierarchy) -> None:
    """The general concept reaches the specific one, and not the reverse."""
    assert DIVERTICULOSIS_LARGE_INTESTINE in small.descendants(DIVERTICULOSIS)
    assert DIVERTICULOSIS not in small.descendants(DIVERTICULOSIS_LARGE_INTESTINE)


def test_seeds_are_their_own_evidence(small: Hierarchy) -> None:
    assert DIVERTICULOSIS in small.descendants(DIVERTICULOSIS)


def test_depth_bounds_the_closure(small: Hierarchy) -> None:
    """An over-broad seed must fail visibly at build time, not silently later."""
    assert small.descendants(DIVERTICULOSIS, max_depth=1) == frozenset(
        {DIVERTICULOSIS, DIVERTICULOSIS_LARGE_INTESTINE}
    )
    assert len(small.descendants(DIVERTICULOSIS, max_depth=3)) == 4


def test_cycles_terminate(small: Hierarchy) -> None:
    """Terminologies are not guaranteed acyclic; the traversal must not care."""
    looped = Hierarchy(children={"A": ("B",), "B": ("A",)})
    assert looped.descendants("A") == frozenset({"A", "B"})


def test_metathesaurus_edges_reach_what_no_source_vocabulary_connects() -> None:
    """The UMLS-intrinsic layer is not redundant with the source hierarchies.

    ``C0011847`` (*Diabetes*) carries no ``isa`` edge in any source vocabulary —
    it is hierarchically orphaned outside ``PSY`` — so taking the union across
    *every* source still fails to connect it to ``C0011849`` (*Diabetes
    Mellitus*), which is what annotators chose for the string ``diabetes``. Only
    ``SAB='MTH'``'s own narrower-than assertion links them, and without it that
    mention is unreachable from any SNOMED seed.
    """
    source_only = Hierarchy(children={"C0011849": ("C_STAGE",)})
    with_mth = Hierarchy(children={"C0011847": ("C0011849",), "C0011849": ("C_STAGE",)})
    assert "C0011849" not in source_only.descendants("C0011847")
    assert "C0011849" in with_mth.descendants("C0011847")


def test_load_round_trips(tmp_path) -> None:
    path = tmp_path / "isa.json"
    path.write_text(json.dumps({"children": {"A": ["B", "C"]}}), encoding="utf-8")
    assert load(path).children == {"A": ("B", "C")}


def test_declare_uses_every_cui_a_seed_code_carries(tmp_path) -> None:
    """A SNOMED code can carry several CUIs, and taking one loses the hierarchy.

    ``84114007`` (Heart failure) maps to both C0018801, which has the
    descendants, and C1959583, which is childless. Picking arbitrarily collapsed
    heart failure to a one-element set and reported zero gold evidence for it.
    """
    (tmp_path / "cui_snomed.json").write_text(
        json.dumps({"C_CHILDLESS": ["84114007"], "C_REAL": ["84114007"], "C_KID": ["1"]}),
        encoding="utf-8",
    )
    code_to_cuis, cui_to_codes = load_maps(tmp_path)
    assert code_to_cuis["84114007"] == ["C_CHILDLESS", "C_REAL"]

    pheno = declare(
        "heart_failure",
        ("84114007",),
        Hierarchy(children={"C_REAL": ("C_KID",)}),
        code_to_cuis,
        cui_to_codes,
    )
    assert "C_KID" in pheno.concept_cuis, "the childless duplicate must not win"
    assert "1" in pheno.concept_codes


def test_declare_materializes_both_identifier_systems(tmp_path) -> None:
    """Our matcher emits CUIs, the gold carries SNOMED codes; neither is converted."""
    (tmp_path / "cui_snomed.json").write_text(
        json.dumps({"C_SEED": ["100"], "C_KID": ["200", "201"]}), encoding="utf-8"
    )
    code_to_cuis, cui_to_codes = load_maps(tmp_path)
    pheno = declare(
        "p", ("100",), Hierarchy(children={"C_SEED": ("C_KID",)}), code_to_cuis, cui_to_codes
    )
    assert pheno.concept_cuis == frozenset({"C_SEED", "C_KID"})
    assert pheno.concept_codes == frozenset({"100", "200", "201"})


def test_seed_code_absent_from_umls_yields_only_itself() -> None:
    pheno = declare("p", ("99999",), Hierarchy(children={}), {}, {})
    assert pheno.concept_codes == frozenset({"99999"})
    assert pheno.concept_cuis == frozenset()


def test_phenotype_score_reports_null_not_zero_without_gold() -> None:
    """No gold evidence is not the same as evidence we failed to find."""
    empty = PhenotypeScore("p", concept_set_size=5, gold_spans=0, span_found=0, set_found=0)
    assert empty.span_recall is None and empty.set_recall is None
    assert empty.to_row()["set_recall"] is None


def test_set_recall_never_exceeds_span_recall() -> None:
    """Finding the concept entails finding the text — the metrics nest."""
    score = PhenotypeScore("p", concept_set_size=5, gold_spans=10, span_found=8, set_found=6)
    assert score.set_recall < score.span_recall
    assert score.to_row()["span_recall"] == 0.8


def test_phenotype_size_counts_concepts_not_codes() -> None:
    pheno = Phenotype("p", ("1",), frozenset({"C1", "C2"}), frozenset({"1", "2", "3"}))
    assert pheno.size == 2
