"""The category taxonomy: what we tag, and what evidence each category has."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from robustehr.categories import (
    Tier,
    anchored,
    categories_of,
    default_tuis,
    gold_standards,
    load_categories,
    tuis_for,
)


def test_every_category_declares_a_tier():
    for name, category in load_categories().items():
        assert isinstance(category.tier, Tier), name


def test_anchored_categories_declare_a_crosswalk():
    """An anchored category must say which gold standard adjudicates it.

    Otherwise "anchored" is a label rather than a commitment.
    """
    for name, category in anchored().items():
        assert category.crosswalk, f"{name} claims to be anchored but names no gold standard"


def test_derived_categories_stay_inside_their_parent():
    """A child escaping its parent would report results under a boundary that
    does not contain them — a silent measurement error."""
    categories = load_categories()
    for name, category in categories.items():
        if category.parent is None:
            continue
        parent = categories[category.parent]
        assert category.tuis <= parent.tuis, f"{name} escapes {category.parent}"
        assert parent.tier is Tier.ANCHORED, f"{name} derives from an unvalidated parent"


def test_the_anchored_categories_are_the_expected_ones():
    """`lab_measurement` joined them deliberately; see its definition for why."""
    assert set(anchored()) == {
        "disorder",
        "procedure",
        "anatomy",
        "medication",
        "lab_measurement",
    }


def test_disorder_partitions_into_its_children():
    """disease + symptom + finding must cover disorder exactly.

    A gap would mean a disorder term that no child claims; an overlap would
    double-count it.
    """
    categories = load_categories()
    disorder = categories["disorder"]
    children = [categories[c] for c in disorder.children]
    union: frozenset[str] = frozenset().union(*(c.tuis for c in children))
    assert union == disorder.tuis
    for i, left in enumerate(children):
        for right in children[i + 1 :]:
            assert not left.tuis & right.tuis, f"{left.name} overlaps {right.name}"


def test_medication_is_tight():
    """Widening this is what admitted `date` and every amino acid."""
    assert tuis_for("medication") == frozenset({"T121", "T200", "T195"})


def test_snomed_challenge_covers_four_categories():
    """Its medication gap is why n2c2 2018 is not optional."""
    coverage = gold_standards()
    assert set(coverage["snomed_el"]) == {
        "disorder",
        "procedure",
        "anatomy",
        "lab_measurement",
    }
    assert "medication" not in coverage["snomed_el"]
    assert "medication" in coverage["n2c2_2018"]


def test_every_anchored_category_has_some_gold_standard():
    covered = {name for names in gold_standards().values() for name in names}
    assert set(anchored()) <= covered


def test_t033_is_present_but_excluded_from_the_default():
    """The exclusion is provisional and measurable, not a deletion.

    T033 stays in the taxonomy — QuickUMLS and MedMentions both keep it — but
    out of `clinical_any` until the with/without measurement settles it.
    """
    finding = load_categories()["finding"]
    assert finding.tuis == frozenset({"T033"})
    assert not finding.in_default
    assert "T033" not in default_tuis()
    # Still reachable when explicitly asked for.
    assert tuis_for("finding") == frozenset({"T033"})
    assert categories_of(frozenset({"T033"})) >= {"finding", "disorder"}


def test_only_finding_is_excluded_from_the_default():
    excluded = {n for n, c in load_categories().items() if not c.in_default}
    assert excluded == {"finding"}


def test_every_category_has_a_definition():
    """A category with no definition is a TUI set nobody can review."""
    for name, category in load_categories().items():
        assert category.definition, name
        assert len(category.definition) > 40, f"{name} definition is too thin to review"


def test_lab_measurement_spans_both_typing_conventions():
    """The category exists precisely to be indifferent to the disagreement.

    UMLS types `hgb` as T034, a test *result*; the challenge annotators chose a
    T059 concept, the *procedure* that produces it. Roughly 640 abbreviation-
    shaped gold spans turn on it. A user asking for "the analyte" should not
    have to know which convention their corpus was annotated under.
    """
    tuis = tuis_for("lab_measurement")
    assert tuis == {"T034", "T059"}
    assert "lab_measurement" in categories_of(frozenset({"T034"}))
    assert "lab_measurement" in categories_of(frozenset({"T059"}))


def test_lab_measurement_does_not_change_the_default_tui_set():
    """Adding it must not silently move any existing measurement.

    T034 and T059 were both already admitted, via `lab_result` and `procedure`.
    So the new category adds a *row* to every per-category report without
    changing which spans the matcher returns — which is what makes it safe to
    add mid-project rather than a reason to re-measure everything.
    """
    assert tuis_for("lab_measurement") <= default_tuis()


def test_categories_removed_for_irrelevance_stay_removed():
    """chemical, organism and physiology were cut after measurement.

    Re-adding one should be a deliberate act with fresh numbers, not a quiet
    revert — the measurements that justified removal are in docs/categories.md.
    """
    names = set(load_categories())
    assert not names & {"chemical", "organism", "physiology"}


def test_the_taxonomy_stays_small_enough_to_review():
    """A dozen categories is reviewable by a clinician; forty is not.

    This number is meant to be hard to change. It moved from 11 to 12 once, for
    `lab_measurement`, because UMLS and the SNOMED challenge annotators type the
    same lab analyte differently and neither is wrong — see its definition.
    """
    assert len(load_categories()) == 12


def test_unknown_category_is_refused():
    with pytest.raises(ValueError, match="unknown semantic categor"):
        tuis_for("medicaton")


def test_disease_and_symptom_are_disjoint():
    """The distinction the coarse DISO group cannot express."""
    assert not tuis_for("disease") & tuis_for("symptom")
    assert "T047" in tuis_for("disease")
    assert "T184" in tuis_for("symptom")


def test_exclusions_subtract_rather_than_merely_omit():
    """An excluded child must not sneak in through an included parent.

    `finding` is part of `disorder`, so omitting it from the union would leave
    T033 admitted via `disorder` and the exclusion would be decorative.
    """
    categories = load_categories()
    assert "T033" in categories["disorder"].tuis
    assert categories["disorder"].in_default
    assert "T033" not in default_tuis()


def test_naming_a_category_overrides_the_conservative_default():
    """clinical_any is narrower than `disorder`; asking for `disorder` gets it all."""
    assert "T033" in tuis_for("disorder")
    assert not tuis_for("disorder") <= default_tuis()


def test_category_sheets_are_not_stale():
    """Every category has a validation sheet, matching the current taxonomy.

    The sheets are generated from the resource, so a taxonomy change with no
    regenerate would leave documentation asserting a validation story that no
    longer matches what the code does.
    """
    if not Path("validation/pipeline/categories").exists():  # pragma: no cover - fresh checkout
        pytest.skip("category sheets not generated")
    result = subprocess.run(
        [sys.executable, "validation/pipeline/scripts/gen_category_docs.py", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_every_category_has_a_sheet():
    for name in load_categories():
        assert Path(f"validation/pipeline/categories/{name}_NER_validation.md").exists(), name
