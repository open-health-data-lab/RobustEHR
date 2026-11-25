"""The target grammar: what a user can write, and that it survives a round trip.

**Why the round trip is the central property here.** A run records its target in
the manifest as `canon()`. If that string cannot be parsed back, the artifact
cannot reproduce the run it describes — the target would be provenance a reader
can see and not re-execute. So `parse(t.canon()) == t` is not a tidiness test, it
is what makes a recorded target a reproducible one.
"""

from __future__ import annotations

import pytest

from robustehr import target as T

#: One of every atom and combinator, including nesting. Written as the canon
#: form so the table doubles as the grammar's documentation.
SPECS = [
    "all",
    "uncategorized",
    "cat=medication",
    "cat=disease,medication",
    "tui=T047",
    "tui=T047,T121",
    "lex=general_english",
    "section=history_of_present_illness",
    "struct=deid_placeholder",
    "pheno=hypertension",
    "pheno=diabetes_mellitus,hypertension",
    "pheno=*",
    "not(cat=disease)",
    "not(pheno=*)",
    "all(cat=medication;pheno=hypertension)",
    "any(cat=disease;cat=medication)",
    "all(cat=medication;not(pheno=*))",
    "all(any(cat=disease;cat=medication);section=hpi)",
]


class TestRoundTrip:
    @pytest.mark.parametrize("spec", SPECS)
    def test_canon_parses_back_to_itself(self, spec: str) -> None:
        """The property the manifest depends on."""
        assert T.parse(spec).canon() == spec

    @pytest.mark.parametrize("spec", SPECS)
    def test_parsing_twice_is_stable(self, spec: str) -> None:
        parsed = T.parse(spec)
        assert T.parse(parsed.canon()).canon() == parsed.canon()

    def test_canon_is_order_independent(self) -> None:
        """Logically identical targets must be textually identical.

        Canon feeds the BLAKE2b seed, so two spellings of the same target that
        produced different canon would select different units and silently make
        two equivalent runs incomparable.
        """
        a = T.parse("all(cat=medication;pheno=hypertension)")
        b = T.parse("all(pheno=hypertension;cat=medication)")
        assert a.canon() == b.canon()


class TestPhenotypeAtom:
    def test_named_phenotypes(self) -> None:
        parsed = T.parse("pheno=hypertension")
        assert isinstance(parsed, T.PhenotypeEvidence)
        assert parsed.names == ("hypertension",)

    def test_star_means_any_declared_not_all_named(self) -> None:
        """`pheno=*` is a different request from naming every phenotype.

        It means *whichever ones this run declared*, so a run configured with two
        targets their union without repeating the names.
        """
        parsed = T.parse("pheno=*")
        assert isinstance(parsed, T.PhenotypeEvidence)
        assert parsed.names == ()

    def test_phenotypes_named_finds_them_through_combinators(self) -> None:
        """The walker that stops a target from silently admitting nothing.

        `PhenotypeEvidence` consults the run's phenotype index, which is empty
        unless a phenotype was declared — so a target naming an undeclared one
        reports zero eligible units and reads like an empty corpus rather than a
        configuration error.
        """
        deep = T.parse("all(cat=medication;any(pheno=hypertension;not(pheno=fever)))")
        assert T.phenotypes_named(deep) == frozenset({"hypertension", "fever"})

    def test_star_names_nothing_but_wants_something(self) -> None:
        star = T.parse("pheno=*")
        assert T.phenotypes_named(star) == frozenset()
        assert T.wants_any_phenotype(star)

    def test_a_named_phenotype_does_not_want_any(self) -> None:
        named = T.parse("pheno=hypertension")
        assert not T.wants_any_phenotype(named)

    def test_wants_any_is_found_through_combinators(self) -> None:
        assert T.wants_any_phenotype(T.parse("all(cat=disease;not(pheno=*))"))


class TestRepeatedTargets:
    def test_repeating_intersects(self) -> None:
        """`--target a --target b` is the shell-friendly spelling of `all(a;b)`."""
        repeated = T.parse_all(["cat=medication", "pheno=hypertension"])
        composite = T.parse("all(cat=medication;pheno=hypertension)")
        assert repeated.canon() == composite.canon()

    def test_a_single_target_is_not_wrapped(self) -> None:
        """One target must not become `all(one)`, which has a different canon."""
        assert T.parse_all(["cat=medication"]).canon() == "cat=medication"

    def test_everything_is_absorbed(self) -> None:
        """`all` intersected with anything is that thing.

        Otherwise the default `--target all` would poison every explicit target
        a user added beside it.
        """
        assert T.parse_all(["all", "cat=medication"]).canon() == "cat=medication"

    def test_nothing_means_everything(self) -> None:
        assert T.parse_all([]).canon() == "all"
        assert T.parse_all(["all"]).canon() == "all"


class TestRejections:
    @pytest.mark.parametrize(
        "spec",
        ["nonsense", "cat", "unknown=x", "both(cat=disease;cat=medication)"],
    )
    def test_a_bad_spec_raises_rather_than_matching_nothing(self, spec: str) -> None:
        """Failing loudly beats a target that silently admits nothing."""
        with pytest.raises(ValueError):
            T.parse(spec)

    @pytest.mark.parametrize("spec", ["all(cat=disease", "all(cat=disease))"])
    def test_unbalanced_parentheses_raise(self, spec: str) -> None:
        with pytest.raises(ValueError):
            T.parse(spec)

    def test_an_unknown_category_raises_before_the_run_starts(self) -> None:
        """A typo'd category must not be discovered after an hour of corpus work."""
        with pytest.raises(ValueError):
            T.parse("cat=not_a_category")


class TestSplitting:
    def test_semicolons_split_only_at_depth_zero(self) -> None:
        """Otherwise a composite could never contain a composite."""
        assert T._split_composite("a;b") == ["a", "b"]
        assert T._split_composite("all(a;b);c") == ["all(a;b)", "c"]
        assert T._split_composite("not(a);any(b;c)") == ["not(a)", "any(b;c)"]

    def test_empty_parts_are_dropped(self) -> None:
        assert T._split_composite("a;;b") == ["a", "b"]


class TestClinicalAtom:
    """The clinical-content aim is reachable from the command line and round-trips."""

    def test_clinical_is_the_measured_rule_at_its_default(self) -> None:
        target = T.parse("clinical")
        assert isinstance(target, T.ClinicalSalience)
        assert target.canon() == "clinical(salience>=0.5,drug,labelled,unseen)"

    def test_canon_parses_back(self) -> None:
        canon = T.ClinicalSalience().canon()
        assert T.parse(canon) == T.ClinicalSalience()
        assert T.parse(canon).canon() == canon

    def test_clauses_are_switches(self) -> None:
        lexicon_only = T.parse("clinical(salience>=0.4)")
        assert lexicon_only == T.ClinicalSalience(
            threshold=0.4, use_drugs=False, use_labelled_values=False, use_unseen_mentions=False
        )
        assert T.parse(lexicon_only.canon()) == lexicon_only

    def test_unknown_clause_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown clinical clause"):
            T.parse("clinical(salience>=0.5,magic)")

    def test_composes_like_any_atom(self) -> None:
        assert (
            T.parse("all(clinical;pheno=hypertension)").canon()
            == "all(clinical(salience>=0.5,drug,labelled,unseen);pheno=hypertension)"
        )
