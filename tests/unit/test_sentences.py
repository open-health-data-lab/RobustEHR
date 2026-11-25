"""Sentence segmentation, and the clinical text that defeats generic splitters."""

from __future__ import annotations

from itertools import pairwise

import pytest

from robustehr.document import Document
from robustehr.segment.sentences import load_rules
from tests.fixtures.clinical import FORMATS
from tests.fixtures.notes import FIXTURES


def split(text: str):
    """Sentences of a one-off note, for the boundary-rule tests below."""
    return Document.from_text(text, uid="t").sentences.sentences


def sentences(text: str, uid: str = "t"):  # type: ignore[no-untyped-def]
    return Document.from_text(text, uid=uid).sentences


def prose_texts(text: str) -> list[str]:
    doc = Document.from_text(text, uid="t")
    return [s.text(doc.text).strip() for s in doc.sentences.prose()]


class TestBoundaries:
    def test_plain_prose_splits(self) -> None:
        assert prose_texts("He has a fever. She does not. They improved.") == [
            "He has a fever.",
            "She does not.",
            "They improved.",
        ]

    def test_space_after_terminator_is_skipped(self) -> None:
        """The bug that collapsed an entire free-text paragraph into one unit.

        The character that decides a boundary is the first *letter or digit*
        after the period, not the separating space.
        """
        text = FORMATS["family_med_freetext"].text
        assert len(prose_texts(text)) > 8

    def test_lowercase_continuation_is_not_a_boundary(self) -> None:
        assert len(prose_texts("Given 5 mg. p.o. daily thereafter")) == 1

    def test_question_and_exclamation_terminate(self) -> None:
        assert len(prose_texts("Is he improving? Yes. Good!")) == 3

    def test_run_of_terminators_ends_once(self) -> None:
        assert prose_texts("He paused... Then continued.") == [
            "He paused...",
            "Then continued.",
        ]


class TestClinicalTraps:
    def test_decimals_are_never_split(self) -> None:
        """Splitting 4.46 would invent a sentence boundary inside a lab value."""
        assert len(prose_texts("Creatinine was 1.4 and calcium 8.46 today")) == 1

    def test_genus_abbreviations_survive(self) -> None:
        """`E. coli` must not become a sentence ending in "E"."""
        assert prose_texts("Urine grew E. coli overnight. Sensitivities pending.") == [
            "Urine grew E. coli overnight.",
            "Sensitivities pending.",
        ]

    def test_c_difficile(self) -> None:
        assert len(prose_texts("Stool positive for C. difficile toxin")) == 1

    def test_titles_are_abbreviations(self) -> None:
        assert len(prose_texts("Referred by Dr. Smith for assessment")) == 1

    def test_dosing_abbreviations(self) -> None:
        for text in (
            "Metoprolol 25 mg. daily was continued",
            "Give 500 mL. of normal saline",
            "Ordered q.i.d. for three days",
        ):
            assert len(prose_texts(text)) == 1, text

    def test_deid_mask_does_not_split_mid_value(self) -> None:
        """`___` is atomic, so no rule can see a period inside it."""
        doc = Document.from_text(FIXTURES["deid_in_lab_line"], uid="t")
        for sentence in doc.sentences.sentences:
            surface = sentence.text(doc.text)
            assert surface.count("_") % 3 == 0, surface

    def test_hard_wrapped_sentence_is_one_unit(self) -> None:
        text = FIXTURES["hard_wrapped"]
        joined = next(s for s in prose_texts(text) if s.startswith("Ms."))
        # The wrap point falls inside "psychiatry\nservice", so the unit spans
        # four physical lines and the newline is preserved rather than repaired.
        assert "psychiatry\nservice" in joined
        # "Ms." must not have terminated it, so the unit runs to the real period.
        assert joined.startswith("Ms.")
        assert joined.endswith("back to psychiatry.")

    def test_blank_line_midsentence_does_not_split(self) -> None:
        """A blank line falls inside this wrapped item; it must still be one unit.

        Checked over all units rather than prose only: the line is a dash bullet,
        so it is correctly classified as structure.
        """
        doc = Document.from_text(FIXTURES["blank_line_midsentence"], uid="t")
        texts = [s.text(doc.text) for s in doc.sentences.sentences]
        assert any("tilt table" in t and "testing" in t for t in texts)


class TestFallbacks:
    def test_telegraphic_note_uses_line_boundaries(self) -> None:
        """A splitter that requires a period returns one sentence for the whole
        note, collapsing the denominator to 1."""
        text = FORMATS["ward_nursing"].text
        prose = prose_texts(text)
        assert len(prose) == 8
        assert all(s.terminator is None for s in sentences(text).prose())

    def test_dictated_note_without_punctuation(self) -> None:
        """Spoken punctuation is transcribed as the word "period"."""
        text = FORMATS["cardiology_dictated"].text
        assert len(prose_texts(text)) > 1

    def test_short_note_is_not_one_sentence(self) -> None:
        assert len(prose_texts(FORMATS["dermatology_brief"].text)) >= 4


class TestStructuralUnits:
    def test_list_items_are_non_prose(self) -> None:
        doc = Document.from_text("Past Medical History:\n1. Hypertension\n2. Diabetes\n", uid="t")
        texts = [s.text(doc.text) for s in doc.sentences.sentences if not s.is_prose]
        # The standalone header is structure too, so all three units are.
        assert texts == ["Past Medical History:", "1. Hypertension", "2. Diabetes"]
        assert not doc.sentences.prose()

    def test_aligned_lab_lines_are_non_prose(self) -> None:
        doc = Document.from_text("WBC-6.9 RBC-4.46 Hgb-12.8\nNa-138 K-4.1 Cl-102\n", uid="t")
        assert all(not s.is_prose for s in doc.sentences.sentences)

    def test_inline_header_value_stays_prose(self) -> None:
        """`INDICATION: ___ with chest pain` carries content on the header line.

        Marking the whole line structural would exclude real prose from every
        prose-scoped operator.
        """
        doc = Document.from_text("INDICATION: patient with pleuritic chest pain\n", uid="t")
        prose = doc.sentences.prose()
        assert any("pleuritic" in s.text(doc.text) for s in prose)

    def test_inline_header_forces_a_boundary(self) -> None:
        """Label and value are different statements with no punctuation between."""
        doc = Document.from_text("Service: MEDICINE\n", uid="t")
        assert len(doc.sentences.prose()) == 2

    def test_standalone_header_is_non_prose(self) -> None:
        doc = Document.from_text("Allergies:\nPenicillin causes rash.\n", uid="t")
        header = doc.sentences[0]
        assert not header.is_prose
        assert header.text(doc.text) == "Allergies:"


@pytest.mark.parametrize("name", sorted(FORMATS))
class TestSentenceGeneralization:
    def test_spans_are_valid_and_ordered(self, name: str) -> None:
        doc = Document.from_text(FORMATS[name].text, uid=name)
        found = doc.sentences.sentences
        assert found
        for sentence in found:
            assert 0 <= sentence.span.start < sentence.span.end <= len(doc.text)
        for a, b in pairwise(found):
            assert a.span.end <= b.span.start

    def test_no_sentence_is_only_whitespace(self, name: str) -> None:
        doc = Document.from_text(FORMATS[name].text, uid=name)
        for sentence in doc.sentences.sentences:
            assert sentence.text(doc.text).strip()

    def test_denominator_is_not_degenerate(self, name: str) -> None:
        """Every note must yield more than one unit, whatever its punctuation."""
        doc = Document.from_text(FORMATS[name].text, uid=name)
        assert len(doc.sentences) >= 2, f"{name}: sentence denominator collapsed"


class TestRules:
    def test_rules_are_hashed(self) -> None:
        assert len(load_rules().sha256) == 64

    def test_abbreviation_list_is_substantial(self) -> None:
        rules = load_rules()
        assert {"dr", "mg", "bid", "hx"} <= rules.abbreviations
        assert rules.single_letter_is_abbreviation


class TestLeadingDecimals:
    """Values written without a leading zero: `TB .5`, `Lactate .9`.

    The tokenizer merges `4.46` into one atom, so no boundary rule can see the
    point inside it — that is the design the splitter relies on. It cannot merge
    a point with no digit before it, so `.5` arrives as PUNCT followed by NUMBER
    and every terminator rule fires. Boundary confirmation does not save it
    either, because it deliberately accepts a following digit so that
    `2. Hypertension` still splits.

    Found by comparing against PyRuSH on MIMIC discharge summaries, where it cut
    lab lines mid-value. A whole class of segmentation error that our own golden
    fixtures never contained, which is the argument for external baselines.
    """

    def test_a_leading_decimal_does_not_end_a_sentence(self) -> None:
        text = "ALT 20 / AST 62 / Lipase 54 / TB .5 / Alb 3.2"
        assert [s.span.start for s in split(text)] == [0]

    def test_several_in_one_line(self) -> None:
        text = "Na 139 / K 5.4 / Cl 107 / CO2 21 / Glucose 79 / Lactate .9"
        assert len(split(text)) == 1

    def test_a_space_still_separates_a_boundary_from_a_number(self) -> None:
        """`Stage 3. 5 patients` is two sentences; the space is what says so."""
        assert len(split("Stage 3. 5 patients were seen.")) == 2

    def test_numbered_list_markers_still_split(self) -> None:
        """The rule must not silence the list-marker boundary it sits next to."""
        assert len(split("He improved. 2. Hypertension controlled.")) > 1

    def test_a_trailing_period_before_a_letter_still_splits(self) -> None:
        assert len(split("Lipase was .5. Patient improved.")) == 2
