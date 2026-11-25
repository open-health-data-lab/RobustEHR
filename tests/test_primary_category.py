"""One category per word: the partition tables are built on."""

from __future__ import annotations

import pytest

from robustehr.categories import (
    NO_CONCEPT,
    UNCATEGORIZED,
    categories_of,
    display_group,
    display_groups,
    exclusive_order,
    load_categories,
    primary_category,
)


def test_a_word_with_no_concept_is_not_an_uncategorized_concept() -> None:
    assert primary_category(None) == NO_CONCEPT
    assert primary_category(frozenset({"T999"})) == UNCATEGORIZED
    assert primary_category(frozenset()) == UNCATEGORIZED


def test_disease_wins_over_finding_and_symptom() -> None:
    assert primary_category(frozenset({"T047", "T033", "T184"})) == "disease"


def test_finding_precedes_symptom_as_the_published_tables_assume() -> None:
    order = exclusive_order()
    assert order.index("finding") < order.index("symptom")
    assert primary_category(frozenset({"T033", "T184"})) == "finding"


def test_lab_result_is_not_absorbed_by_a_broader_category() -> None:
    assert primary_category(frozenset({"T034"})) == "lab_result"
    assert primary_category(frozenset({"T059"})) == "procedure"


def test_every_categorised_type_gets_exactly_one_primary_category() -> None:
    every_tui = {tui for c in load_categories().values() for tui in c.tuis}
    for tui in sorted(every_tui):
        primary = primary_category(frozenset({tui}))
        assert primary in exclusive_order(), tui
        assert primary in categories_of(frozenset({tui})), tui


def test_no_parent_precedes_its_own_child() -> None:
    order = exclusive_order()
    categories = load_categories()
    for position, name in enumerate(order):
        assert categories[name].parent not in order[:position], name


def test_display_groups_partition_every_outcome() -> None:
    members = [m for _, group in display_groups().values() for m in group]
    assert sorted(members) == sorted({*exclusive_order(), UNCATEGORIZED, NO_CONCEPT})
    assert display_group("finding") == display_group("symptom") == "signs_symptoms_and_findings"
    assert display_group(NO_CONCEPT) == display_group(UNCATEGORIZED) == "other"
    assert display_groups()["other"][0] == "Other"


def test_a_parent_category_has_no_display_group() -> None:
    with pytest.raises(ValueError, match="not a primary category"):
        display_group("disorder")
