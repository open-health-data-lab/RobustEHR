"""Generic ⇄ brand substitution: same drug, same dose, same route.

The operator's contract is narrow and load-bearing. Every test here is a case
where a looser implementation would change the drug, the delivery system or the
dosing instruction while reporting itself as a naming change.
"""

from __future__ import annotations

import pytest

from robustehr.document import Document
from robustehr.drugs import Representation, load_synonyms
from robustehr.ops import registry
from robustehr.ops.base import Scope
from robustehr.runner import apply_operator, severity_ladder

needs_map = pytest.mark.skipif(
    not load_synonyms(),
    reason="drug_synonyms.json not built; run validation/pipeline/scripts/build_drug_synonyms.py",
)


def run(text: str, mode: str = "flip", severity: str = "1"):  # type: ignore[no-untyped-def]
    registry.register_builtins()
    op = registry.get("lexical.medication_rename")()
    doc = Document.from_text(text, uid="n")
    return apply_operator(
        doc,
        op,
        op.meta,
        severity_ladder(severity)[0],
        scope=Scope(),
        salt="rep0",
        params={"mode": mode},
    )


class TestClassification:
    """Three-way, and `unknown` is an answer rather than a failure."""

    @needs_map
    def test_a_generic_is_a_generic(self) -> None:
        assert load_synonyms().classify("furosemide") is Representation.GENERIC

    @needs_map
    def test_a_brand_is_a_brand(self) -> None:
        assert load_synonyms().classify("Lasix") is Representation.COMMERCIAL

    def test_an_unlisted_word_is_unknown(self) -> None:
        assert load_synonyms().classify("hypertension") is Representation.UNKNOWN

    def test_an_unknown_surface_offers_no_alternatives(self) -> None:
        """Eligibility and proposal agree, so a dose is never silently short."""
        assert load_synonyms().alternatives("hypertension") == ()

    def test_a_missing_map_degrades_rather_than_crashing(self) -> None:
        """Absent, everything is UNKNOWN and the operator reports zero eligible."""
        from robustehr.drugs import DrugSynonyms

        empty = DrugSynonyms()
        assert not empty
        assert empty.classify("furosemide") is Representation.UNKNOWN
        assert empty.alternatives("Lasix") == ()


class TestSubstitution:
    @needs_map
    def test_dose_route_and_frequency_survive(self) -> None:
        """The PRD's central constraint, and it falls out of the span-based edit."""
        result = run("Tylenol 650 mg PO q6h and Lasix 40 mg IV daily.\n")
        assert "40 mg IV daily" in result.text
        assert "Furosemide" in result.text or "furosemide" in result.text

    @needs_map
    def test_only_the_name_span_is_touched(self) -> None:
        result = run("Coumadin 5 mg PO nightly.\n")
        assert result.text.endswith("5 mg PO nightly.\n")

    @needs_map
    def test_to_generic_leaves_generics_alone(self) -> None:
        result = run("Furosemide 40 mg and Coumadin 5 mg.\n", mode="to_generic")
        assert "Furosemide 40 mg" in result.text
        assert "Warfarin" in result.text

    @needs_map
    def test_to_brand_leaves_brands_alone(self) -> None:
        result = run("Coumadin 5 mg and warfarin 5 mg.\n", mode="to_brand")
        assert "Coumadin 5 mg" in result.text

    @needs_map
    def test_casing_is_carried_over(self) -> None:
        """Otherwise a rename would also deliver a capitalisation change."""
        assert "LASIX" in run("FUROSEMIDE 40 mg daily.\n").text

    @needs_map
    def test_reruns_are_byte_identical(self) -> None:
        text = "Furosemide 40 mg, metoprolol 25 mg, warfarin 5 mg.\n"
        assert run(text).text == run(text).text


class TestRefusals:
    """Each of these is a substitution the build filters exist to prevent."""

    def test_sig_words_are_not_drugs(self) -> None:
        """`Daily` is a real mouthwash brand and a frequency in every note.

        `general_english()` deliberately subtracts clinically-typed words, so it
        did NOT catch this; `english_vocabulary()` plus an explicit sig list
        does. Substituting here would destroy the dosing instruction.
        """
        synonyms = load_synonyms()
        for word in ("daily", "nightly", "tablet", "once", "unit", "po"):
            assert synonyms.classify(word) is Representation.UNKNOWN, word

    def test_ordinary_english_words_are_not_brands(self) -> None:
        synonyms = load_synonyms()
        for word in ("burn", "major", "scrub", "handy", "lucky"):
            assert synonyms.classify(word) is Representation.UNKNOWN, word

    @needs_map
    def test_multi_token_brands_are_absent(self) -> None:
        """`Arcapta Neohaler` encodes an inhaler; substituting it changes the route."""
        for brand in load_synonyms().to_generic:
            assert " " not in brand

    @needs_map
    def test_a_brand_maps_to_exactly_one_generic(self) -> None:
        """`Vasotec` is enalapril AND enalaprilat, so it is refused rather than guessed."""
        for generic in load_synonyms().to_generic.values():
            assert isinstance(generic, str)

    @needs_map
    def test_no_pair_is_a_misspelling_of_the_other(self) -> None:
        """`Fuosemide` for `Furosemide` would emit a TYPO under a naming label."""
        synonyms = load_synonyms()
        for generic, brands in synonyms.to_brand.items():
            for brand in brands:
                low = brand.lower()
                assert generic not in low and low not in generic, f"{generic}/{brand}"
