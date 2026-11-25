"""Validation harness: the crosswalk, the scorer, and what they may claim."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from robustehr.document import Document
from robustehr.eval import snomed_el
from robustehr.eval.ablation import CLINICAL_ANY, EVALUABLE, LADDER
from robustehr.eval.snomed_el import GoldSpan, score
from robustehr.types import Span

REAL_ROOT = Path("data/snomed_el")
needs_corpus = pytest.mark.skipif(
    not (REAL_ROOT / snomed_el.CROSSWALK).exists(),
    reason="SNOMED challenge corpus or crosswalk not present",
)


@pytest.fixture
def corpus_root(tmp_path):
    """A miniature challenge corpus with the real file layout."""
    (tmp_path / snomed_el.CROSSWALK).write_text(
        json.dumps({"111": ["T047"], "222": ["T029"], "333": ["T033"]}), encoding="utf-8"
    )
    with (tmp_path / "train_notes.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["note_id", "text"])
        writer.writerow(["n1", "Patient has pneumonia in the chest.\n"])
    with (tmp_path / "train_annotations.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["annotation_id", "note_id", "start", "end", "span", "concept_id", "annotation_type"]
        )
        writer.writerow(["1", "n1", "12.0", "21.0", "pneumonia", "111", "train"])
        writer.writerow(["2", "n1", "29.0", "34.0", "chest", "222", "test"])
    return tmp_path


def test_gold_spans_carry_categories(corpus_root):
    corpus = snomed_el.load(corpus_root)
    by_surface = {s.surface: s for s in corpus.spans}
    assert "disease" in by_surface["pneumonia"].categories
    assert "anatomy" in by_surface["chest"].categories


def test_offsets_index_the_note_text(corpus_root):
    """The annotations are only usable if their offsets are exact."""
    corpus = snomed_el.load(corpus_root)
    for gold in corpus.spans:
        text = corpus.notes[gold.note_id]
        assert text[gold.span.start : gold.span.end] == gold.surface


def test_splits_are_separable(corpus_root):
    corpus = snomed_el.load(corpus_root)
    assert len(corpus.split("test").spans) == 1
    assert len(corpus.split("train").spans) == 1


def test_a_missing_crosswalk_says_how_to_build_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="eval crosswalk"):
        snomed_el.load(tmp_path)


# -- scoring ---------------------------------------------------------------


def gold(start, end, tuis, surface="x"):
    return GoldSpan("n1", Span(start, end), surface, "c", frozenset(tuis), "train")


def test_scoring_counts_overlap_not_exact_boundaries():
    """A target selects tokens; gold marks mentions.

    Requiring identical boundaries would score a correct token selection inside
    `chest pain` as a miss.
    """
    result = score([Span(0, 5)], [gold(0, 10, {"T047"})], "disease", "L0")
    assert result.hits == 1
    assert result.precision == 1.0


def test_a_selection_outside_every_gold_span_is_a_miss():
    result = score([Span(50, 55)], [gold(0, 10, {"T047"})], "disease", "L0")
    assert result.hits == 0
    assert result.precision == 0.0
    assert result.recall == 0.0


def test_only_the_named_category_counts():
    """Selecting an anatomy span does not earn credit against disease gold."""
    spans = [gold(0, 10, {"T047"}), gold(20, 30, {"T029"})]
    result = score([Span(20, 25)], spans, "disease", "L0")
    assert result.gold == 1
    assert result.hits == 0


def test_recall_counts_gold_spans_covered():
    spans = [gold(0, 10, {"T047"}), gold(20, 30, {"T047"})]
    result = score([Span(0, 5)], spans, "disease", "L0")
    assert result.gold == 2
    assert result.gold_covered == 1
    assert result.recall == 0.5


def test_empty_selection_reports_null_precision_not_zero():
    """Null is not zero — the same convention the dose record uses."""
    result = score([], [gold(0, 10, {"T047"})], "disease", "L0")
    assert result.precision is None
    assert result.recall == 0.0


def test_clinical_any_scores_against_the_default_union():
    """The pseudo-category where the T033 question lives.

    T033 is excluded from the default, so a finding-only gold span must not
    count toward `clinical_any`.
    """
    spans = [gold(0, 10, {"T047"}), gold(20, 30, {"T033"})]
    result = score([Span(0, 5), Span(20, 25)], spans, CLINICAL_ANY, "L1")
    assert result.gold == 1
    assert result.hits == 1


def test_the_ladder_varies_exactly_one_thing_per_rung():
    by_name = {r.name: r for r in LADDER}
    assert not by_name["L0"].use_concepts
    assert by_name["L1"].use_concepts and not by_name["L1"].admit_finding
    assert by_name["L1F"].use_concepts and by_name["L1F"].admit_finding


def test_medication_is_not_evaluable_here():
    """The challenge annotates no medications; n2c2 2018 is the complement."""
    assert "medication" not in EVALUABLE


# -- against the real corpus ------------------------------------------------


@needs_corpus
def test_the_real_corpus_loads_with_usable_offsets():
    """Offsets must index the text, modulo hard-wrap whitespace.

    The annotation's `span` column normalizes a wrap newline to a space, so an
    exact comparison fails on mentions crossing a line break. Offsets are
    authoritative; the rendering is not.
    """
    corpus = snomed_el.load(REAL_ROOT, limit=5)
    assert corpus.notes
    assert corpus.spans
    disagreeing = corpus.offsets_agree()
    assert len(disagreeing) / len(corpus.spans) < 0.01
    for span in disagreeing:
        actual = corpus.notes[span.note_id][span.span.start : span.span.end]
        assert "\n" in actual, f"{span.surface!r} differs for a reason other than wrapping"


@needs_corpus
def test_every_annotated_concept_crosswalks():
    """100% coverage is what makes the crosswalk usable as a reference."""
    corpus = snomed_el.load(REAL_ROOT, limit=20)
    unmapped = [s for s in corpus.spans if not s.tuis]
    assert not unmapped, f"{len(unmapped)} annotations have no semantic type"


@needs_corpus
def test_gold_is_not_exhaustive_over_clinical_content():
    """The caveat that bounds every absolute number this harness produces.

    The challenge annotates selected concepts, not every clinical word, so
    absolute precision against it is a lower bound and the L0-to-L1 delta is
    the interpretable result. Asserted so the caveat cannot quietly lapse.
    """
    corpus = snomed_el.load(REAL_ROOT, limit=5)
    covered = total = 0
    for note_id, text in corpus.notes.items():
        doc = Document.from_text(text, uid=note_id)
        spans = corpus.for_note(note_id)
        tokens = [t for t in doc.tokens if t.is_content]
        total += len(tokens)
        covered += sum(1 for t in tokens if any(t.span.overlaps(g.span) for g in spans))
    assert 0.1 < covered / total < 0.6, covered / total


def test_split_restricts_notes_as_well_as_spans():
    """The bug this guards: filtering spans alone breaks every score.

    The challenge partitions by note — 204 train, 68 test. Keeping all 272 notes
    while filtering only the spans makes a system predict over text that carries
    no gold, so every mention there counts against it.
    """
    corpus = snomed_el.load(REAL_ROOT) if (REAL_ROOT / snomed_el.CROSSWALK).exists() else None
    if corpus is None:
        pytest.skip("challenge corpus not present")
    test = corpus.split("test")
    assert len(test.notes) < len(corpus.notes)
    assert set(test.notes) == {s.note_id for s in test.spans}


def test_split_partitions_by_note_without_overlap():
    if not (REAL_ROOT / snomed_el.CROSSWALK).exists():
        pytest.skip("challenge corpus not present")
    corpus = snomed_el.load(REAL_ROOT)
    train, test = corpus.split("train"), corpus.split("test")
    assert not set(train.notes) & set(test.notes)
    assert len(test.notes) == 68
