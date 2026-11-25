"""Abbreviation load as a baseline-quality dimension.

A property of the note *before* any operator runs, in the same sense as
misspelling rate and de-identification density — and a plausible stratifier for
a robustness result, since a note dense in ambiguous shorthand is harder for
every reader independently of anything this package does to it.
"""

from __future__ import annotations

from fractions import Fraction

from robustehr.metrics.ambiguity import (
    AMBIGUOUS_AT,
    HIGHLY_AMBIGUOUS_AT,
    SHORT_CAPS_MAX,
    AmbiguityProfile,
    Occurrence,
    Outcome,
    is_abbreviation_shaped,
    is_mixed_case,
)
from robustehr.types import Span


def occ(surface: str, senses: int, snomed: int = 0) -> Occurrence:
    outcome = Outcome.AMBIGUOUS if senses >= AMBIGUOUS_AT else Outcome.RESOLVED
    return Occurrence(Span(0, len(surface)), surface, outcome, senses, snomed)


class TestWhatCounts:
    def test_ordinary_english_is_not_an_abbreviation(self) -> None:
        """Without this the population inflates by about a third.

        `clear`, `left` and `small` are 2-6 alphabetic characters and are not
        abbreviations. The stage-3 gate found them swept in by the mechanical
        definition, and the error ran in the direction that flatters the result.
        """
        for word in ("clear", "left", "small", "right", "severe"):
            assert not is_abbreviation_shaped(word), word

    def test_clinically_typed_ordinary_words_are_excluded(self) -> None:
        """The bug this rule exists to fix.

        `stable`, `mild`, `wound` and `fever` are ordinary English and are *not*
        in `general_english()` — that list deliberately removes words carrying a
        high-precision clinical type so `resolve_tags` lets the terminology speak
        for them. Correct there, and wrong here: using it as the abbreviation
        gate counted every one of them as an abbreviation, and 71% of the corpus
        count was ordinary English as a result.

        `english_vocabulary()` subtracts nothing and is the right list for the
        question "would a reader recognise this word".
        """
        for word in ("stable", "mild", "wound", "fever", "cough", "acute"):
            assert not is_abbreviation_shaped(word), word

    def test_capitalisation_does_not_make_a_word_an_abbreviation(self) -> None:
        """Sentence-initial capitals say nothing; they are positional."""
        for word in ("Stable", "Mild", "Left", "Clear"):
            assert not is_abbreviation_shaped(word), word

    def test_clinical_shorthand_counts(self) -> None:
        for short in ("hgb", "angap", "hfref", "RA", "creat"):
            assert is_abbreviation_shaped(short), short

    def test_length_bounds_are_enforced(self) -> None:
        assert not is_abbreviation_shaped("a")
        assert not is_abbreviation_shaped("epinephrine")

    def test_tokens_with_digits_or_spaces_are_excluded(self) -> None:
        assert not is_abbreviation_shaped("hgb1")
        assert not is_abbreviation_shaped("on ra")

    def test_lowercase_ra_is_the_english_word(self) -> None:
        """Casing is the only thing separating them, and it is enough.

        `RA` in a note is room air or an atrium; lowercase `ra` is the Egyptian
        god, which is why it is in the word list at all. Treating them alike
        would either lose the abbreviation or admit the noun.
        """
        assert is_abbreviation_shaped("RA")
        assert not is_abbreviation_shaped("ra")


class TestCasingOverridesTheWordList:
    """Two bounded exceptions, because the word list over-excludes.

    `ra` is in the English vocabulary — Ra, the Egyptian god, clears Zipf 3.0 —
    so the list alone loses `RA`, the canonical ambiguous abbreviation in this
    corpus. So are `po`, `ms`, `pe`, `dm` and `bs`.
    """

    def test_short_all_capitals_beats_the_word_list(self) -> None:
        for short in ("RA", "PO", "MS", "PE", "DM", "BS"):
            assert is_abbreviation_shaped(short), short

    def test_long_all_capitals_does_not(self) -> None:
        """The bound that stops the rescue readmitting everything.

        `BLOOD` and `STABLE` are all-capitals in MIMIC lab lines and headings and
        are plainly not abbreviations. Without the length bound, `BLOOD` alone
        contributed 1,813 spurious ambiguous tokens.
        """
        for word in ("BLOOD", "STABLE", "CHEST"):
            assert not is_abbreviation_shaped(word), word
            assert len(word) > SHORT_CAPS_MAX

    def test_mixed_case_beats_the_word_list_at_any_length(self) -> None:
        """A capital the author put *inside* a word is a deliberate choice."""
        for short in ("HFrEF", "AnGap", "pO2"[:5]):
            assert is_mixed_case(short) or not short.isalpha(), short
        assert is_abbreviation_shaped("HFrEF")
        assert is_abbreviation_shaped("AnGap")

    def test_all_capitals_is_not_mixed_case(self) -> None:
        """Otherwise every shouted heading becomes an abbreviation."""
        assert not is_mixed_case("BLOOD")
        assert is_mixed_case("HFrEF")

    def test_lowercase_shorthand_still_counts(self) -> None:
        """The word list carries the ordinary case: not English, so shorthand."""
        for short in ("hgb", "angap", "creat", "rdwsd"):
            assert is_abbreviation_shaped(short), short


class TestTheBands:
    """Two headline numbers and a band above them."""

    def test_one_sense_is_not_ambiguous(self) -> None:
        assert not occ("hgb", 1).ambiguous

    def test_two_senses_is_the_definition_not_a_threshold(self) -> None:
        assert occ("vs", AMBIGUOUS_AT).ambiguous

    def test_five_senses_is_highly_ambiguous(self) -> None:
        """`pt` at nine behaves differently from a two-way split."""
        assert occ("pt", HIGHLY_AMBIGUOUS_AT).highly_ambiguous
        assert not occ("vs", HIGHLY_AMBIGUOUS_AT - 1).highly_ambiguous

    def test_highly_ambiguous_is_a_subset_of_ambiguous(self) -> None:
        pt = occ("pt", 9)
        assert pt.highly_ambiguous and pt.ambiguous


class TestRates:
    def _profile(self, **kw) -> AmbiguityProfile:
        return AmbiguityProfile(note_uid="n", note_sha256="s", content_tokens=100, **kw)

    def test_a_note_with_no_abbreviations_has_no_rate(self) -> None:
        """None, not zero — the null-is-not-zero rule.

        Zero would place a note with nothing to be ambiguous about alongside one
        whose shorthand all resolved, which are different things.
        """
        empty = self._profile(abbreviations=0, ambiguous=0)
        assert empty.ambiguity_rate is None
        assert empty.high_ambiguity_rate is None

    def test_rates_are_exact_fractions(self) -> None:
        """No floats on anything that feeds a comparison."""
        found = self._profile(abbreviations=20, ambiguous=5, highly_ambiguous=1)
        assert found.ambiguity_rate == Fraction(1, 4)
        assert isinstance(found.ambiguity_rate, Fraction)

    def test_density_is_per_content_token(self) -> None:
        """Comparable across note lengths, where the raw count is not."""
        found = self._profile(abbreviations=20, ambiguous=10)
        assert found.density == Fraction(10, 100)


class TestOutput:
    """The task is to *locate* them, not only to count them."""

    def _profile(self) -> AmbiguityProfile:
        return AmbiguityProfile(
            note_uid="n",
            note_sha256="s",
            content_tokens=50,
            abbreviations=4,
            ambiguous=3,
            highly_ambiguous=1,
            occurrences=(occ("pt", 9), occ("ra", 5), occ("vs", 2), occ("hgb", 1)),
        )

    def test_the_worst_offenders_come_first(self) -> None:
        assert [s for s, _ in self._profile().most_ambiguous()] == ["pt", "ra", "vs"]

    def test_unambiguous_tokens_are_not_listed(self) -> None:
        assert "hgb" not in dict(self._profile().most_ambiguous())

    def test_surfaces_are_counted_case_insensitively(self) -> None:
        found = AmbiguityProfile(
            note_uid="n",
            note_sha256="s",
            content_tokens=10,
            abbreviations=2,
            ambiguous=2,
            occurrences=(occ("RA", 5), occ("ra", 5)),
        )
        assert found.ambiguous_surfaces() == {"ra": 2}

    def test_the_row_carries_both_headline_numbers_and_the_list(self) -> None:
        row = self._profile().to_row()
        assert row["abbreviations"] == 4
        assert row["ambiguous"] == 3
        assert row["highly_ambiguous"] == 1
        assert row["most_ambiguous"]

    def test_snomed_is_reported_alongside_umls_not_instead(self) -> None:
        """Two defensible denominators; a reader should not have to guess."""
        row = self._profile().to_row()
        assert "ambiguous" in row and "ambiguous_snomed" in row
