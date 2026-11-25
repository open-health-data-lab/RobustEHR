"""The shorthand expansion table: slot scoping, and what it refuses.

The table is the component the V0 gate redirected stage 3 toward, and its whole
safety argument rests on one idea — an entry is valid **in one structural slot**
and nowhere else. That is what lets `pt` mean prothrombin time here while
remaining untouchable in prose, and it is the property most worth pinning.
"""

from __future__ import annotations

import pytest

from robustehr.concepts.expansion import (
    EXPANSIONS_RESOURCE,
    Expansion,
    ExpansionTable,
    Slot,
    _check_consistency,
    load_expansions,
)
from robustehr.resources import resource_sha256


class TestSlotScoping:
    """The safety mechanism: monosemous *within its slot*, not outright."""

    def test_pt_is_a_lab_in_a_value_slot_and_nothing_in_an_exam_slot(self) -> None:
        """The case the whole design exists for.

        `pt` in prose is the patient, or physical therapy. In the label half of
        a numeric value it can only be prothrombin time, because the layout has
        already established that this token names a measured quantity.
        """
        table = load_expansions()
        assert table.expand("pt", Slot.VALUE_LABEL) == "prothrombin"
        assert table.expand("pt", Slot.EXAM_LABEL) is None

    def test_ca_is_calcium_only_in_a_value_slot(self) -> None:
        table = load_expansions()
        assert table.expand("ca", Slot.VALUE_LABEL) == "calcium"
        assert table.expand("ca", Slot.EXAM_LABEL) is None

    def test_exam_systems_do_not_leak_into_the_value_slot(self) -> None:
        table = load_expansions()
        assert table.expand("heent", Slot.EXAM_LABEL) is not None
        assert table.expand("heent", Slot.VALUE_LABEL) is None

    def test_lookup_is_case_insensitive(self) -> None:
        """`Creat`, `creat` and `CREAT` are one analyte, not three rows."""
        table = load_expansions()
        expected = "creatinine"
        for surface in ("creat", "Creat", "CREAT", "  Creat  "):
            assert table.expand(surface, Slot.VALUE_LABEL) == expected


class TestTheTableRefusesBadEntries:
    """Raising at load, on the same principle as the category loader."""

    def test_a_short_form_meaning_two_things_in_one_slot_is_refused(self) -> None:
        """Otherwise the expansion depends on iteration order.

        Exactly the class of defect the determinism rules exist to prevent,
        arriving through a data file rather than through code.
        """
        with pytest.raises(ValueError, match="monosemous within its slot"):
            _check_consistency(
                (
                    Expansion("ra", "room air", Slot.VALUE_LABEL),
                    Expansion("ra", "rheumatoid arthritis", Slot.VALUE_LABEL),
                )
            )

    def test_the_same_meaning_twice_is_allowed(self) -> None:
        """`basos` and `baso` both mean basophils; that is not a conflict."""
        _check_consistency(
            (
                Expansion("baso", "basophils", Slot.VALUE_LABEL),
                Expansion("baso", "basophils", Slot.VALUE_LABEL),
            )
        )

    def test_an_entry_expanding_to_itself_is_refused(self) -> None:
        """It cannot help: the point is to reach a form the terminology carries.

        Twelve such rows were written in the first draft of the shipped table —
        `lipase`, `ferritin`, `skin`, `neck` — and this check is what caught
        them. They are words, not abbreviations.
        """
        with pytest.raises(ValueError, match="expands to itself"):
            _check_consistency((Expansion("lipase", "lipase", Slot.VALUE_LABEL),))

    def test_an_empty_long_form_is_refused(self) -> None:
        with pytest.raises(ValueError, match="empty long form"):
            _check_consistency((Expansion("xyz", "  ", Slot.VALUE_LABEL),))


class TestTheShippedTable:
    def test_it_loads_and_covers_both_slots(self) -> None:
        table = load_expansions()
        assert len(table.for_slot(Slot.VALUE_LABEL)) > 50
        assert len(table.for_slot(Slot.EXAM_LABEL)) > 15

    def test_no_entry_carries_a_cui(self) -> None:
        """Licensing: the table ships, so it must contain no UMLS identifiers.

        It maps shorthand to ordinary clinical English and the caller's own
        licensed terminology resolves the rest. A CUI here would make the file
        UMLS-derived content.
        """
        for entry in load_expansions().entries:
            assert not entry.long.startswith("C0")
            assert not any(
                part.startswith("C") and part[1:].isdigit() for part in entry.long.split()
            )

    def test_the_review_flag_is_reported_not_assumed(self) -> None:
        """An unreviewed table is an assumption wearing the costume of a resource."""
        assert isinstance(load_expansions().reviewed, bool)

    def test_the_digest_pins_the_file(self) -> None:
        """A table edit must invalidate seeds rather than silently move results."""
        assert load_expansions().sha256 == resource_sha256(EXPANSIONS_RESOURCE)

    def test_the_analytes_that_motivated_the_table_are_in_it(self) -> None:
        """The measured unreachable set: absent from every terminology."""
        table = load_expansions()
        for short in ("creat", "angap", "urean", "rdwsd", "neuts", "monos"):
            assert table.expand(short, Slot.VALUE_LABEL) is not None, short


def test_empty_table_expands_nothing() -> None:
    empty = ExpansionTable(entries=(), reviewed=False, sha256="")
    assert empty.expand("creat", Slot.VALUE_LABEL) is None
    assert len(empty) == 0


class TestOntologicAnchoring:
    """Entries name a concept, not merely a string that might match one.

    The string-only design had a defect by construction: the long form is a
    *lookup key*, so an entry expanding to something the terminology does not
    carry resolves to nothing and is dropped exactly as if absent. It looks like
    coverage, delivers none, and nothing downstream notices. 14 of 99 shipped
    rows were dead that way.
    """

    def test_most_entries_carry_a_concept_identifier(self) -> None:
        entries = load_expansions().entries
        anchored = [e for e in entries if e.snomed]
        assert len(anchored) / len(entries) > 0.85

    def test_identifiers_are_numeric_snomed_codes(self) -> None:
        for entry in load_expansions().entries:
            if entry.snomed:
                assert entry.snomed.isdigit(), entry

    def test_the_long_form_survives_as_the_review_handle(self) -> None:
        """A clinician checks `creat -> creatinine`, not `creat -> C0201975`.

        The identifier is authoritative and the string is what makes the row
        reviewable, so both are kept rather than one replacing the other.
        """
        for entry in load_expansions().entries:
            assert entry.long and not entry.long.isdigit()

    def test_entries_without_a_code_still_carry_a_long_form(self) -> None:
        """Some concepts have no SNOMED code in a given release.

        `baso`, `pco2`, `hba1c`, `hr`, `temp` and `gen` are such cases here. The
        string is then all there is, and the entry must still work.
        """
        for entry in load_expansions().entries:
            if not entry.snomed:
                assert entry.long

    def test_entry_returns_the_whole_row_not_just_the_string(self) -> None:
        found = load_expansions().entry("creat", Slot.VALUE_LABEL)
        assert found is not None
        assert found.long == "creatinine"
        assert found.snomed
