"""Protection: who may edit what, and why a preserving operator must not."""

from __future__ import annotations

import pytest

from robustehr.document import Document
from robustehr.protect import Strength, protect_document
from robustehr.types import ProtectionClass, Span
from tests.fixtures.clinical import FORMATS


def index_for(text: str):  # type: ignore[no-untyped-def]
    return protect_document(Document.from_text(text, uid="t"))


def span_of(text: str, needle: str) -> Span:
    start = text.index(needle)
    return Span(start, start + len(needle))


class TestDeidProtection:
    def test_masks_are_atomic_not_untouchable(self) -> None:
        """HARD means "no partial edits", not "nobody may touch this".

        The stricter reading would block the restyler, which is the entire
        reason the class exists. What must never happen is an edit to *part* of
        a mask, which produces PHI-shaped text that was never in the record.
        """
        text = "Name: ___ here"
        index = index_for(text)
        mask = span_of(text, "___")
        targeting = frozenset({ProtectionClass.DEID_PLACEHOLDER})

        assert index.blocks(mask, targets=frozenset()), "undeclared operators are refused"
        assert not index.blocks(mask, targets=targeting), "whole replacement is allowed"
        inside = Span(mask.start + 1, mask.end)
        assert index.blocks(inside, targets=targeting), "partial edits are always refused"

    def test_hard_strength_is_recorded(self) -> None:
        index = index_for("Name: ___ here")
        deid = index.of_class(ProtectionClass.DEID_PLACEHOLDER)
        assert deid and all(p.strength is Strength.HARD for p in deid)

    def test_divider_rules_are_soft(self) -> None:
        text = "Header\n" + "_" * 56 + "\nBody"
        index = index_for(text)
        rule = span_of(text, "_" * 56)
        assert index.blocks(rule, targets=frozenset())
        assert not index.blocks(rule, targets=frozenset({ProtectionClass.DIVIDER_RULE}))


class TestNumericProtection:
    def test_decimals_are_protected(self) -> None:
        """Deleting the period from 8.0 yields 80 — a tenfold change in a lab
        value, produced by an operator claiming to preserve reference."""
        text = "Potassium was 8.0 today"
        index = index_for(text)
        assert index.blocks(span_of(text, "8.0"))

    def test_an_operator_targeting_numbers_may_edit_them(self) -> None:
        text = "Potassium was 8.0 today"
        index = index_for(text)
        assert not index.blocks(
            span_of(text, "8.0"),
            targets=frozenset({ProtectionClass.NUMERIC_VALUE, ProtectionClass.DOSAGE}),
        )

    @pytest.mark.parametrize(
        "phrase", ["40 mg", "0.4 mg", "500 mL", "18 micrograms", "94%", "128 mmHg"]
    )
    def test_dosages_and_measurements_are_recognized(self, phrase: str) -> None:
        text = f"Give {phrase} now"
        index = index_for(text)
        assert index.of_class(ProtectionClass.DOSAGE), phrase

    def test_plain_prose_is_not_protected(self) -> None:
        text = "The patient denies chest pain today"
        index = index_for(text)
        assert not index.blocks(span_of(text, "denies"))


class TestStructuralProtection:
    def test_headers_are_protected_but_targetable(self) -> None:
        text = "Allergies:\nPenicillin\n"
        index = index_for(text)
        header = span_of(text, "Allergies:")
        assert index.blocks(header)
        assert not index.blocks(header, targets=frozenset({ProtectionClass.SECTION_HEADER}))

    def test_list_markers_are_protected(self) -> None:
        text = "1. Hypertension\n2. Diabetes\n"
        index = index_for(text)
        assert index.of_class(ProtectionClass.LIST_MARKER)
        assert index.blocks(span_of(text, "1."))

    def test_position_dependent_blocks_record_why(self) -> None:
        text = "Date       Temp       BP\n01/01      37.0       142/88\n"
        index = index_for(text)
        blocks = index.of_class(ProtectionClass.LAB_BLOCK)
        assert blocks
        assert any("position-dependent" in p.reason for p in blocks)


class TestQueries:
    def test_blocking_reports_the_specific_protections(self) -> None:
        text = "Name: ___ here"
        index = index_for(text)
        blocking = index.blocking(span_of(text, "___"))
        assert blocking and blocking[0].reason == "de-identification mask"

    def test_adjacent_spans_do_not_block(self) -> None:
        text = "abc ___ def"
        index = index_for(text)
        assert not index.blocks(span_of(text, "abc"))
        assert not index.blocks(span_of(text, "def"))

    def test_counts_are_reported_per_class(self) -> None:
        counts = index_for(FORMATS["mimic_discharge"].text).counts()
        assert counts[ProtectionClass.DEID_PLACEHOLDER.value] > 0
        assert counts[ProtectionClass.NUMERIC_VALUE.value] > 0

    def test_index_is_sorted(self) -> None:
        index = index_for(FORMATS["complex_discharge"].text)
        assert list(index.starts) == sorted(index.starts)
        assert len(index.starts) == len(index.spans)


@pytest.mark.parametrize("name", sorted(FORMATS))
class TestProtectionGeneralization:
    def test_spans_stay_within_the_document(self, name: str) -> None:
        doc = Document.from_text(FORMATS[name].text, uid=name)
        for protected in protect_document(doc).spans:
            assert 0 <= protected.span.start < protected.span.end <= len(doc.text)

    def test_masks_admit_whole_replacement_but_never_partial_edits(self, name: str) -> None:
        """The rule that lets the restyler exist without letting anyone forge PHI.

        Replacing ``___`` with ``[**Name**]`` wholesale is a legitimate
        restyling. Deleting one of its underscores, or inserting a typo inside
        it, produces PHI-shaped text that was never in the record — so a HARD
        span is atomic rather than untouchable.
        """
        doc = Document.from_text(FORMATS[name].text, uid=name)
        index = protect_document(doc)
        everything = frozenset(ProtectionClass)
        for placeholder in doc.deid.placeholders:
            span = placeholder.span
            assert not index.blocks(span, targets=everything), "whole replacement must be allowed"
            assert index.blocks(span), "an operator declaring nothing must be refused"
            if len(span) > 1:
                inner = Span(span.start, span.end - 1)
                assert index.blocks(inner, targets=everything), "partial edits must be refused"
