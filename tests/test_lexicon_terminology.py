"""The terminology tier, and the measurement of what the fallback costs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from robustehr.categories import default_tuis
from robustehr.concepts.umls import (
    CLINICAL_GROUPS,
    CLINICAL_TUIS,
    GROUP_BY_TUI,
    SEMANTIC_GROUPS,
)
from robustehr.concepts.validate import MIN_EXAMPLE_FREQUENCY, measure_fallback
from robustehr.document import Document
from robustehr.lexicon import (
    DEFAULT_LEXICON,
    Evidence,
    Specificity,
    TokenClass,
    load_clinical_lexicon,
)

#: Written by `robustehr concepts validate`, and quoted in the lexicon module
#: docstring. Absent on a machine with no UMLS installation.
MEASUREMENT = Path("validation/measurements/lexicon_fallback.json")


@pytest.fixture
def artifact(tmp_path):
    """A miniature stand-in for the built vocabulary."""
    path = tmp_path / "clinical_tokens.txt"
    path.write_text("\n".join(["aspirin", "pneumonia", "warfarin", "fever"]), encoding="utf-8")
    path.with_suffix(".manifest.json").write_text(
        json.dumps({"umls_release": "2026AA", "tokens": 4}), encoding="utf-8"
    )
    return path


# -- semantic groups --------------------------------------------------------


def test_every_registered_tui_belongs_to_a_known_group():
    assert set(GROUP_BY_TUI.values()) <= set(SEMANTIC_GROUPS)


def test_clinical_groups_are_a_strict_subset():
    """Excluding CONC/GEOG/OCCU/ORGA is the choice that makes the measure mean
    anything; if they crept in, most of a note would classify as clinical."""
    assert set(SEMANTIC_GROUPS) > CLINICAL_GROUPS
    assert {"CONC", "GEOG", "OCCU", "ORGA"}.isdisjoint(CLINICAL_GROUPS)


def test_clinical_tuis_are_derived_not_hand_listed():
    assert (
        frozenset(tui for tui, group in GROUP_BY_TUI.items() if group in CLINICAL_GROUPS)
        == CLINICAL_TUIS
    )
    assert len(CLINICAL_TUIS) > 80


# -- loading ----------------------------------------------------------------


def test_loading_records_the_release(artifact):
    lexicon = load_clinical_lexicon(artifact)
    assert lexicon.source == "umls-2026AA"
    assert lexicon.release == "2026AA"
    assert lexicon.has_vocabulary


def test_release_is_unknown_without_a_manifest(tmp_path):
    path = tmp_path / "tokens.txt"
    path.write_text("aspirin\n", encoding="utf-8")
    assert load_clinical_lexicon(path).source == "umls-unknown"


# -- classification ---------------------------------------------------------


def test_terminology_beats_morphology_on_words_with_no_affix(artifact):
    """`aspirin` and `fever` are the whole argument: clinical, no morphology."""
    lexicon = load_clinical_lexicon(artifact)
    doc = Document.from_text("Patient given aspirin for fever.", uid="t")
    by_word = {t.lower: lexicon.classify(t) for t in doc.tokens if t.is_content}
    for word in ("aspirin", "fever"):
        assert by_word[word].token_class is TokenClass.CLINICAL
        assert by_word[word].evidence is Evidence.TERMINOLOGY

    without = {t.lower: DEFAULT_LEXICON.classify(t) for t in doc.tokens if t.is_content}
    assert without["aspirin"].token_class is TokenClass.UNKNOWN
    assert without["fever"].token_class is TokenClass.UNKNOWN


def test_absence_from_the_terminology_is_itself_evidence(artifact):
    lexicon = load_clinical_lexicon(artifact)
    doc = Document.from_text("The stapler was returned.", uid="t")
    stapler = next(t for t in doc.tokens if t.lower == "stapler")
    result = lexicon.classify(stapler)
    assert result.token_class is TokenClass.NON_CLINICAL
    assert result.evidence is Evidence.TERMINOLOGY


def test_without_a_terminology_absence_is_unknown_not_negative():
    """The distinction that keeps a no-terminology run honest."""
    doc = Document.from_text("The stapler was returned.", uid="t")
    stapler = next(t for t in doc.tokens if t.lower == "stapler")
    result = DEFAULT_LEXICON.classify(stapler)
    assert result.token_class is TokenClass.UNKNOWN
    assert result.evidence is Evidence.NONE


def test_morphology_still_fires_for_words_outside_a_partial_vocabulary(artifact):
    """The fallback is consulted after the terminology, not instead of it."""
    lexicon = load_clinical_lexicon(artifact)
    doc = Document.from_text("Underwent cholecystectomy.", uid="t")
    token = next(t for t in doc.tokens if t.lower == "cholecystectomy")
    result = lexicon.classify(token)
    assert result.token_class is TokenClass.CLINICAL
    assert result.evidence is Evidence.MORPHOLOGY


def test_default_lexicon_declares_itself_as_the_fallback():
    assert DEFAULT_LEXICON.source == "morphology-only"
    assert not DEFAULT_LEXICON.has_vocabulary


# -- the measurement --------------------------------------------------------


def test_measurement_requires_a_reference():
    with pytest.raises(ValueError, match="terminology-backed reference"):
        measure_fallback([Document.from_text("Fever.", uid="t")], DEFAULT_LEXICON)


def test_measurement_separates_the_four_cells(artifact):
    lexicon = load_clinical_lexicon(artifact)
    doc = Document.from_text(
        "Aspirin for pneumonia. Cholecystectomy performed. The stapler broke.",
        uid="t",
    )
    report = measure_fallback([doc], lexicon)

    # aspirin, pneumonia: in the terminology, no clinical morphology -> missed.
    assert report.false_negative >= 2
    # cholecystectomy: morphology fires, absent from this miniature vocabulary.
    assert report.false_positive >= 1
    # stapler: neither -> correctly negative.
    assert report.true_negative >= 1
    assert report.reference == "umls-2026AA"


def test_examples_are_withheld_below_the_frequency_floor(artifact):
    """Counts are complete; quoted examples must recur before they travel.

    A word type seen once is not an aggregate statistic, and the report is meant
    to be publishable next to a result.
    """
    lexicon = load_clinical_lexicon(artifact)
    rare = Document.from_text("Cholecystectomy performed.", uid="rare")
    report = measure_fallback([rare], lexicon)
    assert report.false_positive == 1
    assert report.false_positive_examples == ()

    frequent = [
        Document.from_text("Cholecystectomy performed.", uid=f"n{i}")
        for i in range(MIN_EXAMPLE_FREQUENCY)
    ]
    assert "cholecystectomy" in measure_fallback(frequent, lexicon).false_positive_examples


def test_measurement_reports_null_rather_than_zero_when_undefined(artifact):
    """An empty cell has no rate; reporting 0.0 would be a claim, not a gap."""
    lexicon = load_clinical_lexicon(artifact)
    report = measure_fallback([Document.from_text("The stapler broke.", uid="t")], lexicon)
    assert report.true_positive == 0
    assert report.precision is None or report.precision == 0
    assert report.recall is None


def test_token_coverage_counts_occurrences_not_types(artifact):
    lexicon = load_clinical_lexicon(artifact)
    doc = Document.from_text("Fever fever fever. The stapler broke.", uid="t")
    report = measure_fallback([doc], lexicon)
    assert report.tokens_clinical_reference == 3
    assert report.n_types < report.tokens_total


def test_report_serializes_without_fractions(artifact):
    lexicon = load_clinical_lexicon(artifact)
    report = measure_fallback([Document.from_text("Aspirin for fever.", uid="t")], lexicon)
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["reference"] == "umls-2026AA"
    assert isinstance(payload["recall"], float)


# -- the recorded result ----------------------------------------------------


def test_recorded_measurement_matches_the_documented_numbers():
    """The figures quoted in the module docstring must stay attached to a run.

    This is the paper's number. If the extraction changes and the docstring does
    not, that is a citation to a measurement nobody made.
    """
    path = MEASUREMENT
    if not path.exists():
        pytest.skip("measurement artifact not built (needs a UMLS installation)")
    recorded = json.loads(path.read_text(encoding="utf-8"))
    assert recorded["reference"] == "umls-2026AA"

    # Every figure quoted in prose must be asserted here, not just precision.
    # Coverage, recall and F1 drifted undetected once because this test checked
    # only precision while the docs claimed a test guarded all of them.
    quoted = {
        "precision": 0.607,
        "recall": 0.103,
        "f1": 0.176,
        "reference_token_coverage": 0.543,
        "fallback_token_coverage": 0.034,
    }
    for field, expected in quoted.items():
        assert recorded[field] == pytest.approx(expected, abs=0.01), field
    assert recorded["precision"] == pytest.approx(0.607, abs=0.01)
    assert recorded["recall"] == pytest.approx(0.103, abs=0.01)
    assert recorded["reference_token_coverage"] == pytest.approx(0.543, abs=0.01)
    assert all(
        example["corpus_n"] >= MIN_EXAMPLE_FREQUENCY
        for example in recorded["false_negative_examples"]
    )
    assert recorded["fallback_token_coverage"] == pytest.approx(0.034, abs=0.01)


# -- selectivity ------------------------------------------------------------


@pytest.fixture
def tiered(tmp_path):
    """A vocabulary carrying semantic groups and specificity tiers."""
    path = tmp_path / "clinical_tokens.txt"
    path.write_text(
        "\n".join(
            [
                "warfarin\tT121|T109\tspecific",
                "pneumonia\tT047\tspecific",
                "dyspnea\tT184|T033\tspecific",
                "chest\tT029\tspecific",
                "blood\tT031\tambiguous",
                "one\tT033\tambiguous",
            ]
        ),
        encoding="utf-8",
    )
    path.with_suffix(".manifest.json").write_text(
        json.dumps({"umls_release": "2026AA"}), encoding="utf-8"
    )
    return path


def test_semantic_types_load(tiered):
    lexicon = load_clinical_lexicon(tiered)
    assert lexicon.semantic_types("warfarin") == frozenset({"T121", "T109"})
    assert lexicon.in_categories("warfarin", "medication")
    assert not lexicon.in_categories("warfarin", "disease")


def test_category_targeting_separates_drug_disease_and_symptom(tiered):
    """The selectivity that makes one agnostic mechanism serve many use cases.

    Note that `disease` excludes `dyspnea`: a diagnosis and a symptom are
    different targets, and the coarse DISO semantic group cannot tell them
    apart, which is why membership is stored per semantic type.
    """
    lexicon = load_clinical_lexicon(tiered)
    words = ["warfarin", "pneumonia", "dyspnea", "chest", "one"]
    assert [w for w in words if lexicon.in_categories(w, "medication")] == ["warfarin"]
    assert [w for w in words if lexicon.in_categories(w, "disease")] == ["pneumonia"]
    assert [w for w in words if lexicon.in_categories(w, "symptom")] == ["dyspnea"]
    assert [w for w in words if lexicon.in_categories(w, "anatomy")] == ["chest"]


def test_junk_is_quarantined_in_the_finding_category(tiered):
    """`one` carries T033 only, which the conservative default subtracts.

    It still resolves under `disorder`, because `finding` is part of that
    hierarchy and asking for `disorder` explicitly means asking for findings
    too. What it does not do is count towards clinical content by default.
    """
    lexicon = load_clinical_lexicon(tiered)
    assert lexicon.categories("one") == frozenset({"finding", "disorder"})
    assert not lexicon.semantic_types("one") & default_tuis()
    assert not lexicon.in_categories("one", "disease")
    # A real diagnosis is admitted by the defaults.
    assert lexicon.semantic_types("pneumonia") & default_tuis()
    assert lexicon.in_categories("pneumonia", "disease")


def test_unknown_category_is_refused(tiered):
    """A typo in a target must not silently select nothing."""
    with pytest.raises(ValueError, match="unknown semantic categor"):
        load_clinical_lexicon(tiered).in_categories("warfarin", "medicaton")


def test_specificity_is_reported_on_clinical_tokens(tiered):
    lexicon = load_clinical_lexicon(tiered)
    doc = Document.from_text("Given warfarin. Blood drawn.", uid="t")
    by_word = {t.lower: lexicon.classify(t) for t in doc.tokens if t.is_content}
    assert by_word["warfarin"].specificity is Specificity.SPECIFIC
    assert by_word["blood"].specificity is Specificity.AMBIGUOUS
    # Both are clinical; the tier says how much weight the evidence carries.
    assert by_word["warfarin"].is_clinical and by_word["blood"].is_clinical


def test_bare_token_list_still_loads(tmp_path):
    """A hand-written vocabulary needs no group or tier columns."""
    path = tmp_path / "tokens.txt"
    path.write_text("aspirin\nfever\n", encoding="utf-8")
    lexicon = load_clinical_lexicon(path)
    assert lexicon.clinical == frozenset({"aspirin", "fever"})
    assert lexicon.tuis == {}
    assert lexicon.ambiguous == frozenset()


def test_semantic_group_would_not_have_separated_them(tiered):
    """Documents the negative result that drove the design to semantic types.

    ``one`` and ``pneumonia`` both fall in the DISO Semantic Group, so a
    group-level target cannot tell them apart. Their semantic *types* differ —
    T033 versus T047 — which is why the vocabulary stores types. If this ever
    stops holding, the ROADMAP §4 argument needs revisiting.
    """
    lexicon = load_clinical_lexicon(tiered)
    groups = {GROUP_BY_TUI[t] for t in lexicon.semantic_types("one")}
    assert groups == {GROUP_BY_TUI[t] for t in lexicon.semantic_types("pneumonia")} == {"DISO"}
    assert lexicon.semantic_types("one") != lexicon.semantic_types("pneumonia")
