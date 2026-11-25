"""Concept mentions recovered from layout rather than from matching."""

from __future__ import annotations

import pytest

from robustehr.concepts.matcher import DEFAULT_INDEX, ConceptMatcher, index_present
from robustehr.concepts.structural import (
    MAX_LABEL_CHARS,
    exam_label_spans,
    label_spans,
    labelled_values,
    resolve_labels,
    structural_spans,
)
from robustehr.document import Document

LAB = "Labs:\nWBC-6.9  RBC-4.46  Hgb-12.8  Hct-36.1\nNa-140  K-4.1  Cl-104  BUN-18\n"

needs_index = pytest.mark.skipif(not index_present(DEFAULT_INDEX), reason="no QuickUMLS index")


def test_labels_are_found_in_self_labelling_blocks():
    doc = Document.from_text(LAB, uid="t")
    surfaces = {s.surface(doc.text) for s in label_spans(doc)}
    assert {"WBC", "RBC", "Hgb", "Hct", "Na", "K", "Cl", "BUN"} <= surfaces


def test_spans_are_offsets_into_the_original_text():
    """The invariant the whole edit model rests on."""
    doc = Document.from_text(LAB, uid="t")
    for pair in labelled_values(doc):
        assert doc.text[pair.label.start : pair.label.end] == pair.label.surface(doc.text)
        assert doc.text[pair.value.start : pair.value.end] == pair.value_text


def test_two_character_labels_are_reachable():
    """`Na` and `Cl` are exactly what the matcher's length floor rejects."""
    doc = Document.from_text(LAB, uid="t")
    surfaces = {s.surface(doc.text) for s in label_spans(doc)}
    assert "Na" in surfaces
    assert "Cl" in surfaces


def test_non_self_labelling_blocks_are_skipped():
    """A positional column header labels the column, not the value beside it.

    Treating it as a label would attach the wrong concept to every row.
    """
    positional = "Date        Value      Unit\n2180-01-01  6.9        K/uL\n"
    doc = Document.from_text(positional, uid="t")
    assert not any(b.self_labelling for b in doc.aligned) or not label_spans(doc)


def test_word_values_are_excluded_by_default():
    """`follow-up` matches the pattern and is not an analyte."""
    doc = Document.from_text("Plan:\nfollow-up  next-week  re-check\n", uid="t")
    assert label_spans(doc, numeric_values_only=True) == ()


def test_long_labels_are_rejected():
    doc = Document.from_text("Section:\nDischargeInstructions-5  WBC-6.9\n", uid="t")
    surfaces = {s.surface(doc.text) for s in label_spans(doc)}
    assert all(len(s) <= MAX_LABEL_CHARS for s in surfaces)


def test_ordering_is_deterministic():
    doc = Document.from_text(LAB, uid="t")
    first = label_spans(doc)
    assert first == label_spans(doc)
    assert list(first) == sorted(first, key=lambda s: (s.start, s.end))


@needs_index
def test_labels_resolve_to_concepts_with_semantic_types():
    doc = Document.from_text(LAB, uid="t")
    mentions = resolve_labels(doc, ConceptMatcher())
    assert mentions
    assert all(m.tuis for m in mentions), "an unresolved label must be dropped, not emitted untyped"
    by_surface = {m.surface for m in mentions}
    assert "WBC" in by_surface or "Hgb" in by_surface


@needs_index
def test_resolution_preserves_the_structural_span():
    """Structure supplies the boundary; the terminology only supplies the concept."""
    doc = Document.from_text(LAB, uid="t")
    structural = set(label_spans(doc))
    for mention in resolve_labels(doc, ConceptMatcher()):
        assert mention.span in structural


@needs_index
def test_unresolvable_labels_are_dropped_not_invented():
    """Institution shorthand absent from every terminology stays absent."""
    doc = Document.from_text("Labs:\nZZQX-1.0  WBC-6.9\n", uid="t")
    surfaces = {m.surface for m in resolve_labels(doc, ConceptMatcher())}
    assert "ZZQX" not in surfaces


class TestExamLabelSlot:
    """The `HEENT:` slot — built, measured, and parked until 3b lands.

    Its gold spans are 71.9% unreachable in UMLS, so the emitter alone cannot
    help them; it needs the expansion table. Measured in isolation it buys
    +0.0059 `procedure` recall and costs ~0.011 precision in two categories,
    which is why it is off by default rather than merely undocumented.
    """

    NOTE = (
        "Physical Exam:\n"
        "HEENT: PERRLA, dry mucous membranes.\n"
        "Neuro: CN II-XII intact.\n"
        "EXT: no edema\n"
        "Discharge Instructions:\n"
        "Follow up in two weeks.\n"
    )

    def _doc(self):
        return Document.from_text(self.NOTE, uid="exam")

    def test_exam_system_labels_are_found(self) -> None:
        doc = self._doc()
        found = {s.surface(doc.text) for s in exam_label_spans(doc)}
        assert {"HEENT", "Neuro", "EXT"} <= found

    def test_note_section_headers_are_not_exam_labels(self) -> None:
        """`Discharge Instructions:` organises the note, not an examination."""
        doc = self._doc()
        found = {s.surface(doc.text) for s in exam_label_spans(doc)}
        assert "Discharge Instructions" not in found
        assert "Physical Exam" not in found

    def test_inline_grammar_counts(self) -> None:
        """Exam labels carry their finding on the same line — the usual case.

        Restricting to standalone headers is the intuitive reading of "the label
        sits alone in its slot" and excludes almost every real instance. An
        earlier version did exactly that and found 0 of these three.
        """
        doc = self._doc()
        assert len(exam_label_spans(doc)) >= 3

    def test_the_slot_is_off_by_default(self) -> None:
        """Measured, not assumed: it does not yet pay for itself."""
        doc = self._doc()
        assert not set(exam_label_spans(doc)) <= set(structural_spans(doc))
        assert set(exam_label_spans(doc)) <= set(structural_spans(doc, include_exam_labels=True))

    def test_structural_spans_deduplicates_across_slots(self) -> None:
        """A span both gates claim must be emitted once, or denominators lie."""
        doc = self._doc()
        spans = structural_spans(doc, include_exam_labels=True)
        assert len(spans) == len(set(spans))
        assert list(spans) == sorted(spans, key=lambda s: (s.start, s.end))
