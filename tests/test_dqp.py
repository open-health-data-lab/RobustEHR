"""The Document Quality Profile: baseline degradation, before any operator."""

from __future__ import annotations

import json
from fractions import Fraction

import pytest

from robustehr.document import Document
from robustehr.dose import DoseRecord
from robustehr.lexicon import DEFAULT_LEXICON, load_clinical_lexicon
from robustehr.metrics.dqp import (
    MAX_MISSPELLING_FREQUENCY,
    corpus_frequencies,
    profile,
    tertiles,
    unrecognized_words,
)


@pytest.fixture
def lexicon(tmp_path):
    path = tmp_path / "clinical_tokens.txt"
    path.write_text(
        "\n".join(
            [
                "warfarin\tT121\tspecific",
                "dyspnea\tT184\tspecific",
                "pain\tT184\tspecific",
            ]
        ),
        encoding="utf-8",
    )
    path.with_suffix(".manifest.json").write_text(
        json.dumps({"umls_release": "2026AA"}), encoding="utf-8"
    )
    return load_clinical_lexicon(path)


def test_recognised_clinical_jargon_is_not_unrecognized(lexicon):
    """`warfarin` is unknown to general English but is a medication."""
    doc = Document.from_text("Started warfarin for dyspnea.\n", uid="t")
    assert "warfarin" not in unrecognized_words(doc, lexicon)
    assert "dyspnea" not in unrecognized_words(doc, lexicon)


def test_a_misspelling_is_unrecognized(lexicon):
    doc = Document.from_text("Reports abdmoninal discomfort.\n", uid="t")
    assert "abdmoninal" in unrecognized_words(doc, lexicon)


def test_misspelling_estimate_is_none_without_a_corpus(lexicon):
    """One note cannot tell a typo from a term: both appear once.

    Reporting None rather than falling back to the unrecognized count is what
    keeps a quality signal from being read as an error count.
    """
    doc = Document.from_text("Reports abdmoninal discomfort.\n", uid="t")
    assert profile(doc, lexicon).suspected_misspellings is None
    assert profile(doc, lexicon).misspelling_rate is None
    # The unrecognized count is always available.
    assert profile(doc, lexicon).unrecognized > 0


def test_frequent_unrecognized_words_are_not_misspellings(lexicon):
    """The bug this design exists to prevent.

    Counting every unrecognized token as a misspelling put `daily` (2,627
    occurrences) and `tablet` (2,390) at the top of the list on the development
    corpus. A word used throughout a corpus is vocabulary, however unrecognized.
    """
    docs = [Document.from_text(f"Take tablet daily. Note {i}.\n", uid=f"n{i}") for i in range(10)]
    docs.append(Document.from_text("Reports abdmoninal pain.\n", uid="typo"))
    frequencies = corpus_frequencies(docs, lexicon)
    assert frequencies["tablet"] > MAX_MISSPELLING_FREQUENCY
    assert frequencies["abdmoninal"] <= MAX_MISSPELLING_FREQUENCY

    typo_note = profile(docs[-1], lexicon, frequencies)
    common_note = profile(docs[0], lexicon, frequencies)
    assert typo_note.suspected_misspellings == 1
    assert common_note.suspected_misspellings == 0


def test_short_tokens_are_left_to_the_abbreviation_resolver(lexicon):
    docs = [Document.from_text("Given prn and bid.\n", uid="t")]
    frequencies = corpus_frequencies(docs, lexicon)
    assert profile(docs[0], lexicon, frequencies).suspected_misspellings == 0


def test_structural_dimensions_are_measured():
    doc = Document.from_text(
        "DISCHARGE SUMMARY\nName:  ___\nHPI:   Patient with     dyspnea.\n", uid="t"
    )
    result = profile(doc)
    assert result.whitespace_runs > 0
    assert result.deid_placeholders == 1
    assert result.lines == 4


def test_lexical_dimension_flags_itself_as_unmeasured():
    """Without a terminology every clinical term looks unrecognized."""
    doc = Document.from_text("Started warfarin.\n", uid="t")
    assert not profile(doc, DEFAULT_LEXICON).is_measured


def test_measured_when_a_terminology_is_installed(lexicon):
    doc = Document.from_text("Started warfarin.\n", uid="t")
    assert profile(doc, lexicon).is_measured


def test_row_serializes_without_fractions(lexicon):
    doc = Document.from_text("Started warfarin for dyspnea.\n", uid="t")
    row = json.loads(json.dumps(profile(doc, lexicon).to_row()))
    assert row["note_uid"] == "t"
    assert row["suspected_misspellings"] is None


def test_tertiles_split_into_thirds():
    values = [Fraction(i, 100) for i in range(9)]
    lo, hi = tertiles(values)
    assert lo == Fraction(3, 100)
    assert hi == Fraction(6, 100)


def test_tertiles_refuse_an_empty_corpus():
    with pytest.raises(ValueError, match="no values"):
        tertiles([])


def test_baseline_is_never_summed_with_injected_dose():
    """A structural guarantee, asserted so it cannot be lost by accident.

    QualityProfile shares no field name with DoseRecord that could be added
    together. Baseline stratifies results; it is not a term in a total.
    """
    profile_fields = set(profile(Document.from_text("x.\n", uid="t")).to_row())
    dose_fields = {f for f in DoseRecord.__dataclass_fields__ if "rate" in f or "_n" in f}
    assert not profile_fields & dose_fields
