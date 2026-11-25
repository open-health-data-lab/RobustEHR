"""Header detection, and the prose it must refuse to collect."""

from __future__ import annotations

import pytest

from robustehr.segment.headers import (
    SECTION_KINDS,
    HeaderConfidence,
    HeaderGrammar,
    HeaderKind,
    detect_headers,
    load_lexicon,
    normalize_label,
)
from robustehr.segment.lines import split_lines
from tests.fixtures.notes import FIXTURES


def headers(text: str, **kw: object):  # type: ignore[no-untyped-def]
    return detect_headers(text, split_lines(text), **kw)  # type: ignore[arg-type]


class TestNormalization:
    @pytest.mark.parametrize(
        "surface",
        [
            "Past Medical History",
            "PAST MEDICAL HISTORY",
            "past medical history",
            "Past  Medical History",
        ],
    )
    def test_case_and_spacing_collapse(self, surface: str) -> None:
        """The corpus varies casing constantly; aliases should not have to."""
        assert normalize_label(surface) == "past medical history"

    def test_punctuation_is_stripped(self) -> None:
        assert normalize_label("Follow-up Instructions") == "follow up instructions"


class TestLexicon:
    def test_loads_and_is_hashed(self) -> None:
        lexicon = load_lexicon()
        assert len(lexicon.sha256) == 64
        assert "past_medical_history" in lexicon.canonical_ids

    def test_kinds_are_assigned(self) -> None:
        lexicon = load_lexicon()
        assert lexicon.kind("past_medical_history") is HeaderKind.SECTION
        assert lexicon.kind("service") is HeaderKind.METADATA
        assert lexicon.kind("exam_heent") is HeaderKind.SUBSECTION
        assert lexicon.kind("rx_dispense") is HeaderKind.BOILERPLATE
        assert lexicon.kind(None) is HeaderKind.UNKNOWN


class TestGrammars:
    def test_standalone(self) -> None:
        found = headers("Past Medical History:\n1. Hypertension\n")
        assert len(found) == 1
        assert found[0].grammar is HeaderGrammar.STANDALONE
        assert found[0].value is None
        assert found[0].canonical_id == "past_medical_history"

    def test_inline_captures_the_value(self) -> None:
        text = "Service: MEDICINE\n"
        found = headers(text)
        assert found[0].grammar is HeaderGrammar.INLINE
        assert found[0].value is not None
        assert found[0].value.surface(text) == "MEDICINE"

    def test_span_covers_label_and_colon(self) -> None:
        text = "Allergies: \nPenicillin\n"
        found = headers(text)
        assert found[0].span.surface(text) == "Allergies:"


class TestProseRejection:
    @pytest.mark.parametrize(
        "line",
        [
            "In the ED, initial vitals were: 98.8 153/91",
            "In the ED, initial vitals: 98.8",
            "Exam notable for: mild distress",
            "Emergency Department for any of the following: chest pain",
            "The following changes were made to your medications: none",
            "Please call your doctor if you have: fever",
        ],
    )
    def test_prose_ending_in_a_colon_is_not_a_header(self, line: str) -> None:
        """1,374 real occurrences. Collecting them roughly doubles the denominator."""
        assert headers(line + "\n") == ()

    def test_lowercase_start_is_rejected(self) -> None:
        assert headers("continued therapy: as above\n") == ()

    def test_a_sentence_terminator_in_the_label_is_rejected(self) -> None:
        assert headers("He improved. Discharge plan: home\n") == ()

    def test_lexicon_entries_survive_prose_markers(self) -> None:
        """ "History of the Present Illness" contains " the " but is real."""
        found = headers("History of the Present Illness: patient reports\n")
        assert found and found[0].canonical_id == "history_present_illness"

    def test_lab_lines_are_not_headers(self) -> None:
        """`___ 09:57PM BLOOD WBC-6.9` has a colon inside a timestamp."""
        assert headers("___ 09:57PM BLOOD WBC-6.9 RBC-4.46\n") == ()

    def test_no_colon_is_not_a_header(self) -> None:
        assert headers("WBC-6.9    RBC-4.46   Hgb-12.8\n") == ()


class TestKindFiltering:
    def test_boilerplate_is_excluded_from_the_section_denominator(self) -> None:
        """`Disp:` appears in a quarter of notes but is not note structure."""
        text = "Discharge Medications:\n1. Metoprolol\nDisp:*30 Tablet*\nRefills:*2*\n"
        assert {h.raw_name for h in headers(text)} == {"Discharge Medications", "Disp", "Refills"}
        assert {h.raw_name for h in headers(text, kinds=SECTION_KINDS)} == {"Discharge Medications"}

    def test_min_confidence_drops_the_unverified_tail(self) -> None:
        text = "Some Novel Label: value\nAllergies: none\n"
        all_found = headers(text)
        lexicon_only = headers(text, min_confidence=HeaderConfidence.LEXICON)
        assert len(all_found) == 2
        assert [h.canonical_id for h in lexicon_only] == ["allergies"]


class TestFixtures:
    def test_family_history_section_is_found(self) -> None:
        found = headers(FIXTURES["family_history"], kinds=SECTION_KINDS)
        assert {h.canonical_id for h in found} == {"family_history", "social_history"}

    def test_physical_exam_and_subsections(self) -> None:
        found = headers(FIXTURES["ambiguous_ra"])
        by_id = {h.canonical_id for h in found}
        assert "physical_examination" in by_id
        assert "hospital_course" in by_id
        # VITALS/GEN are subsections, not sections.
        sections = {h.canonical_id for h in headers(FIXTURES["ambiguous_ra"], kinds=SECTION_KINDS)}
        assert "vital_signs" not in sections

    def test_admission_pe_is_a_header_but_not_canonical(self) -> None:
        found = headers(FIXTURES["ambiguous_pe"])
        pe = next(h for h in found if h.raw_name == "Admission PE")
        assert pe.canonical_id is None
        assert pe.confidence is HeaderConfidence.STRONG_HEURISTIC
        assert pe.kind is HeaderKind.UNKNOWN

    def test_deid_list_numbers_are_not_headers(self) -> None:
        found = headers(FIXTURES["deid_as_list_number"], kinds=SECTION_KINDS)
        assert [h.canonical_id for h in found] == ["past_medical_history"]
