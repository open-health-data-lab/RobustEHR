"""The recipe layer: what a user writes, and what it must refuse to run.

Most of these assert a *rejection*. That is the shape of the module: a recipe
that runs but does not mean what it says produces a corpus-wide number nobody
can tell is wrong, so the loader's job is to fail before any note is read.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from robustehr.config import ConfigError, DocumentSelection, PerDocument, Recipe, Targeting
from robustehr.corpus import Record, select_records


class TestSeverityIsNeverAFloat:
    """The rule `types.RateSeverity` has always stated and nothing enforced."""

    def test_a_yaml_float_is_refused_with_the_fix_in_the_message(self) -> None:
        with pytest.raises(ConfigError, match="quoted"):
            Recipe.parse({"corruptions": ["input.typo"], "severity": 0.1})

    def test_a_quoted_literal_is_accepted(self) -> None:
        recipe = Recipe.parse({"corruptions": ["input.typo"], "severity": "0.10"})
        assert recipe.severity_for("input.typo").canon() == "rate:0.1"

    def test_a_float_fraction_is_refused_too(self) -> None:
        with pytest.raises(ConfigError, match="quoted"):
            Recipe.parse({"corruptions": ["input.typo"], "documents": {"fraction": 0.5}})


class TestNamedLevelsResolvePerOperator:
    """One global mapping would compare a mild dose against a severe one."""

    def test_medium_means_different_things_to_different_operators(self) -> None:
        recipe = Recipe.parse({"corruptions": ["input.typo"], "severity": "medium"})
        assert recipe.severity_for("input.typo").canon() == "rate:0.1"
        assert recipe.severity_for("render.header_delete").canon() == "rate:0.5"

    def test_a_count_operator_gets_a_count_not_a_rate(self) -> None:
        """`discourse.section_duplicate` has no honest rate; "medium" is 2 sections."""
        recipe = Recipe.parse(
            {"corruptions": ["discourse.section_duplicate"], "severity": "medium"}
        )
        assert recipe.severity_for("discourse.section_duplicate").canon() == "count:2:document"

    def test_the_ladders_match_the_specification(self) -> None:
        expected = {
            "input.typo": ("0.05", "0.10", "0.15"),
            "input.ocr_confusion": ("0.05", "0.10", "0.15"),
            "render.header_delete": ("0.30", "0.50", "1"),
            "render.header_rename": ("0.30", "0.50", "1"),
            "render.list_to_prose": ("0.30", "0.50", "1"),
            "render.break_removal": ("0.30", "0.50", "1"),
            "render.space_delete": ("0.10", "0.20", "0.30"),
            "discourse.section_duplicate": ("count:1", "count:2", "count:5"),
            "lexical.numeral_to_word": ("0.30", "0.50", "1"),
        }
        from robustehr.ops import registry

        registry.register_builtins()
        for op_id, ladder in expected.items():
            assert registry.get(op_id).meta.severity_levels == ladder, op_id


class TestFamiliesAreDerived:
    """A new operator must join its family by declaring a layer, not by an edit."""

    def test_families_cover_every_non_control_operator(self) -> None:
        from robustehr.ops import registry
        from robustehr.types import Channel

        registry.register_builtins()
        covered = {op for ids in registry.families().values() for op in ids}
        expected = {
            op_id
            for op_id in registry.all_ids()
            if registry.get(op_id).meta.channel is not Channel.CONTROL
        }
        assert covered == expected

    def test_controls_are_in_no_family(self) -> None:
        """ "All character corruptions" must not silently include the destructive ceiling."""
        from robustehr.ops import registry

        registry.register_builtins()
        covered = {op for ids in registry.families().values() for op in ids}
        assert "control.char_shuffle" not in covered
        assert "control.identity" not in covered

    def test_a_family_name_expands(self) -> None:
        recipe = Recipe.parse({"corruptions": ["character"]})
        assert "input.typo" in recipe.operators()
        assert "render.header_delete" not in recipe.operators()

    def test_an_unknown_name_names_the_alternatives(self) -> None:
        with pytest.raises(ConfigError, match="Families"):
            Recipe.parse({"corruptions": ["strutcural"]}).operators()


class TestTargetingDoesNotReachStructure:
    """configuration.md §13, enforced rather than documented."""

    def test_umls_mode_on_a_structural_operator_is_refused(self) -> None:
        recipe = Recipe.parse({"corruptions": ["render.header_delete"], "target": {"mode": "umls"}})
        with pytest.raises(ConfigError, match="not a concept span"):
            recipe.check()

    def test_structural_operators_get_everything_even_in_a_mixed_recipe(self) -> None:
        recipe = Recipe.parse({"corruptions": ["input.typo"], "target": {"mode": "umls"}})
        assert recipe.target_for("input.typo").canon() == "concept"
        assert recipe.target_for("render.header_delete").canon() == "all"

    def test_refinements_outside_umls_mode_are_refused(self) -> None:
        with pytest.raises(ConfigError, match="no such set to refine"):
            Targeting.parse({"mode": "random", "semantic_categories": ["medication"]})


class TestTargetModes:
    def test_the_four_modes_map_to_the_documented_targets(self) -> None:
        assert Targeting.parse({"mode": "random"}).to_target().canon() == "all"
        assert Targeting.parse({"mode": "umls"}).to_target().canon() == "concept"
        assert Targeting.parse({"mode": "non_umls"}).to_target().canon() == "not(concept)"
        assert (
            Targeting.parse({"mode": "clinical"}).to_target().canon()
            == "clinical(salience>=0.5,drug,labelled,unseen)"
        )

    def test_clinical_takes_no_refinement(self) -> None:
        """Category and phenotype refine a set of UMLS concepts; the clinical rule is not one."""
        with pytest.raises(ConfigError):
            Targeting.parse({"mode": "clinical", "phenotype": "hypertension"})

    def test_filters_intersect_left_to_right(self) -> None:
        """The §12 eligibility chain: UMLS -> category -> phenotype."""
        target = Targeting.parse(
            {
                "mode": "umls",
                "semantic_categories": ["medication"],
                "phenotype": "heart_failure",
            }
        ).to_target()
        assert target.canon() == "all(cat=medication;concept;pheno=heart_failure)"

    def test_bare_umls_mode_adds_no_stratifier(self) -> None:
        """§9: the natural concept distribution is preserved by NOT balancing it.

        Selection is one uniform hash-rank over the eligible pool, so a document
        whose concepts are 70% medications receives about 70% of its
        perturbations on medications. The assertion is that the target adds
        nothing beyond concept membership — a category filter here would impose
        a distribution rather than preserve one.
        """
        assert Targeting.parse({"mode": "umls"}).to_target().canon() == "concept"


class TestPerDocument:
    def test_a_bare_integer_is_the_ablation_mode(self) -> None:
        assert PerDocument.parse(1).is_single

    def test_min_above_max_is_refused(self) -> None:
        with pytest.raises(ConfigError, match="exceeds max"):
            PerDocument.parse({"min": 3, "max": 2})

    def test_asking_for_more_operators_than_exist_is_refused(self) -> None:
        recipe = Recipe.parse(
            {"corruptions": ["input.typo"], "corruptions_per_document": {"min": 1, "max": 3}}
        )
        with pytest.raises(ConfigError, match="cannot receive more"):
            recipe.check()

    def test_the_draw_is_deterministic_from_seed_and_note(self) -> None:
        recipe = Recipe.parse(
            {"corruptions": ["character"], "corruptions_per_document": {"min": 1, "max": 3}}
        )
        assert recipe.operators_for("n1") == recipe.operators_for("n1")
        assert recipe.operators_for("n1") != recipe.operators_for("n2")

    def test_widening_the_range_is_a_paired_comparison(self) -> None:
        """A note keeps the operators it had and gains more, rather than being redrawn.

        Without this, comparing `max: 2` against `max: 4` mixes the effect of
        more operators with the effect of *different* ones.
        """
        base = {"corruptions": ["character"], "seed": "rep0"}
        narrow = Recipe.parse({**base, "corruptions_per_document": {"min": 1, "max": 1}})
        wide = Recipe.parse({**base, "corruptions_per_document": {"min": 1, "max": 4}})
        for uid in ("n1", "n2", "n3", "n4", "n5"):
            assert set(narrow.operators_for(uid)) <= set(wide.operators_for(uid)), uid


class TestDocumentSelection:
    def make(self, n: int) -> list[Record]:
        return [Record(note_id=f"n{i}", text="x") for i in range(n)]

    def test_n_and_fraction_together_are_refused(self) -> None:
        with pytest.raises(ConfigError, match="not both"):
            DocumentSelection.parse({"n": 5, "fraction": "0.5"})

    def test_the_sample_nests(self) -> None:
        """`fraction: 0.25` must be a subset of `fraction: 0.50`.

        The same property severity ladders have, one level up: a corpus-size
        sweep is then paired rather than mixing sample size with sampling noise.
        """
        records = self.make(100)
        previous: set[str] = set()
        for literal in ("0.1", "0.25", "0.5", "1"):
            chosen = {r.note_id for r in select_records(records, fraction=Fraction(literal))}
            assert previous <= chosen, literal
            previous = chosen

    def test_the_sample_is_reproducible_and_salted(self) -> None:
        records = self.make(50)
        a = {r.note_id for r in select_records(records, n=10, salt="rep0")}
        assert a == {r.note_id for r in select_records(records, n=10, salt="rep0")}
        assert a != {r.note_id for r in select_records(records, n=10, salt="rep1")}

    def test_a_tiny_fraction_selects_one_not_none(self) -> None:
        """CEIL, matching `SubUnitPolicy` — a silent zero is the worse failure."""
        assert len(select_records(self.make(50), fraction=Fraction("0.01"))) == 1

    def test_selection_is_returned_in_corpus_order(self) -> None:
        records = self.make(20)
        chosen = select_records(records, n=8)
        order = [r.note_id for r in records if r in chosen]
        assert [r.note_id for r in chosen] == order


def test_an_empty_recipe_is_an_error_not_everything() -> None:
    """A recipe naming no corruption is a typo far more often than a request."""
    with pytest.raises(ConfigError, match="selects no corruptions"):
        Recipe.parse({}).operators()


def test_unknown_keys_are_refused() -> None:
    """A misspelled key would otherwise be silently ignored and its default used."""
    with pytest.raises(ConfigError, match="unknown recipe key"):
        Recipe.parse({"corruptions": ["input.typo"], "severities": ["0.1"]})
