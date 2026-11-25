"""Segmentation against the pathologies that break naive implementations."""

from __future__ import annotations

import re

import pytest

from robustehr.segment import build_reflow_view, index_deid, patterns, split_lines, wrap_width
from robustehr.segment.deid import DIVIDER_RE, DeidScheme, strip_placeholders
from robustehr.segment.wrap import wraps_into_next
from robustehr.types import Span
from tests.fixtures.notes import FIXTURES


class TestCharacterClasses:
    """Guard against a silent-correctness trap that already bit once.

    `DIGIT` and friends are regex class *fragments* for interpolation into
    `[...]`. Using one in a Python membership test asks whether the character is
    literally '0', '-' or '9', which is wrong but raises nothing — the predicate
    just quietly returns False and the surrounding heuristic stops firing.
    """

    def test_fragments_are_not_membership_sets(self) -> None:
        assert "1" not in patterns.DIGIT
        assert "t" not in patterns.LOWER
        assert "P" not in patterns.UPPER

    def test_sets_are_membership_sets(self) -> None:
        assert "1" in patterns.DIGITS
        assert "t" in patterns.LOWERS
        assert "P" in patterns.UPPERS
        assert "_" in patterns.WORD_CHARS
        assert "-" not in patterns.WORD_CHARS

    @pytest.mark.parametrize(
        ("fragment", "sample"),
        [
            (patterns.DIGIT, "0123456789"),
            (patterns.LOWER, "abcxyz"),
            (patterns.UPPER, "ABCXYZ"),
            (patterns.ALPHA, "aZ"),
            (patterns.ALNUM, "a0Z9"),
            (patterns.WORD, "a0Z9_"),
        ],
    )
    def test_fragments_compile_as_regex_classes(self, fragment: str, sample: str) -> None:
        match = re.compile(f"[{fragment}]+").match(sample)
        assert match is not None and match.group() == sample


class TestDeid:
    """The underscore convention specifically. Cross-scheme behaviour lives in
    ``test_formats.py``, so that a change here cannot quietly narrow the package
    back down to one corpus."""

    def test_placeholder_is_exactly_three_underscores(self) -> None:
        pinned = DeidScheme.UNDERSCORE_RUN
        assert [p.surface("a ___ b") for p in index_deid("a ___ b", pinned).placeholders] == ["___"]
        assert index_deid("a __ b", pinned).count == 0
        assert index_deid("a ____ b", pinned).count == 0

    def test_divider_is_four_or_more(self) -> None:
        """The distinction a lazy `_+` regex destroys."""
        rule = "_" * 56
        assert index_deid(rule).dividers and not index_deid(rule).placeholders
        assert index_deid("___").placeholders and not index_deid("___").dividers

    def test_divider_fixture_has_no_placeholders(self) -> None:
        idx = index_deid(FIXTURES["divider_rule"])
        assert len(idx.dividers) == 1
        assert idx.count == 0

    def test_placeholders_glued_to_words_are_still_found(self) -> None:
        # 3,344 real instances look like this: ___F, ___yo, PLT COUNT-___
        for text in ("___F", "___yo", "PLT COUNT-___", "Plt ___"):
            assert index_deid(text).count == 1, text

    def test_offsets_are_exact(self) -> None:
        text = "Name: ___ Sex: ___"
        found = index_deid(text).placeholders
        assert [text[p.span.start : p.span.end] for p in found] == ["___", "___"]

    def test_density_is_an_exact_fraction(self) -> None:
        num, den = index_deid("___" + "x" * 997).density_per_1k_chars(1000)
        assert (num, den) == (1000, 1000)

    def test_strip_is_measurement_only_and_length_preserving(self) -> None:
        """Offsets into the stripped text must still line up with the original."""
        text = "Name: ___ here"
        stripped = strip_placeholders(text)
        assert stripped == "Name:     here"
        assert len(stripped) == len(text)

    def test_divider_regex_does_not_match_placeholder(self) -> None:
        assert not DIVIDER_RE.search("___")


class TestLines:
    def test_offsets_reconstruct_the_document(self) -> None:
        for name, text in FIXTURES.items():
            lines = split_lines(text)
            rebuilt = "".join(line.full.surface(text) for line in lines.lines)
            assert rebuilt == text, name

    def test_empty_document(self) -> None:
        assert len(split_lines("")) == 0

    def test_blank_line_may_be_whitespace(self) -> None:
        """`" "` is a blank line. Testing length rather than content misses it."""
        lines = split_lines("a\n \nb")
        assert [line.is_blank for line in lines.lines] == [False, True, False]

    def test_trailing_whitespace_is_preserved_and_flagged(self) -> None:
        lines = split_lines("word  \nnext")
        assert lines[0].has_trailing_space
        assert lines[0].content_text("word  \nnext") == "word"
        assert lines[0].span.surface("word  \nnext") == "word  "

    def test_indent_is_measured(self) -> None:
        lines = split_lines("    indented")
        assert lines[0].indent == 4
        assert lines[0].content_text("    indented") == "indented"

    def test_blank_run_after(self) -> None:
        lines = split_lines("a\n\n\nb")
        assert lines.blank_run_after(0) == 2
        assert lines.blank_run_after(3) == 0

    def test_no_trailing_newline(self) -> None:
        lines = split_lines("a\nb")
        assert len(lines) == 2
        assert lines[1].newline.is_empty


class TestWrap:
    def test_width_lands_in_the_observed_range(self) -> None:
        # The development corpus wraps at 59-64; the estimator must find it.
        width = wrap_width(split_lines(FIXTURES["hard_wrapped"]))
        assert 45 <= width <= 70

    def test_unwrapped_text_yields_no_continuations(self) -> None:
        text = "Short line.\nAnother short line.\nA third.\n"
        lines = split_lines(text)
        width = wrap_width(lines)
        assert not any(wraps_into_next(text, lines, i, width) for i in range(len(lines)))

    def test_terminated_line_does_not_continue(self) -> None:
        text = "a" * 62 + ".\n" + "continuation here\n"
        lines = split_lines(text)
        assert not wraps_into_next(text, lines, 0, 62)

    def test_next_line_opening_a_list_does_not_continue(self) -> None:
        text = "a" * 62 + "\n1. First item\n"
        lines = split_lines(text)
        assert not wraps_into_next(text, lines, 0, 62)

    def test_next_line_opening_a_header_does_not_continue(self) -> None:
        text = "a" * 62 + "\nPast Medical History:\n"
        lines = split_lines(text)
        assert not wraps_into_next(text, lines, 0, 62)

    def test_deeper_indent_does_not_continue(self) -> None:
        text = "a" * 62 + "\n      deeply indented\n"
        lines = split_lines(text)
        assert not wraps_into_next(text, lines, 0, 62)

    def test_two_blank_lines_always_break(self) -> None:
        text = "a" * 62 + "\n\n\ncontinuation\n"
        lines = split_lines(text)
        assert not wraps_into_next(text, lines, 0, 62)


class TestReflowView:
    @pytest.mark.parametrize("name", sorted(FIXTURES))
    def test_offsets_stay_in_range(self, name: str) -> None:
        text = FIXTURES[name]
        view = build_reflow_view(text, split_lines(text))
        for pos in range(len(view.text)):
            assert 0 <= view.to_raw(pos) <= len(text)

    @pytest.mark.parametrize("name", sorted(FIXTURES))
    def test_content_characters_map_back_exactly(self, name: str) -> None:
        """Every non-synthesized view character must name its raw original."""
        text = FIXTURES[name]
        view = build_reflow_view(text, split_lines(text))
        for pos, ch in enumerate(view.text):
            if ch in " \n":
                continue  # may be a synthesized join
            assert text[view.to_raw(pos)] == ch, (name, pos, ch)

    def test_wrapped_sentence_becomes_one_line_in_the_view(self) -> None:
        text = FIXTURES["hard_wrapped"]
        view = build_reflow_view(text, split_lines(text))
        # Five physical lines in the fixture, but the four-line sentence joins.
        assert view.text.count("\n") < text.count("\n")
        assert "psychiatry service" in view.text  # joined across the wrap point

    def test_blank_line_midsentence_is_joined(self) -> None:
        """The finding that kills `\\n\\s*\\n` paragraph splitting."""
        text = FIXTURES["blank_line_midsentence"]
        view = build_reflow_view(text, split_lines(text))
        assert "tilt table testing" in view.text

    def test_span_mapping_is_contiguous(self) -> None:
        text = FIXTURES["hard_wrapped"]
        view = build_reflow_view(text, split_lines(text))
        start = view.text.index("psychiatry")
        span = view.to_raw_span(Span(start, start + len("psychiatry")))
        assert text[span.start : span.end] == "psychiatry"

    def test_unwrapped_text_view_equals_stripped_source(self) -> None:
        text = "Short one.\nShort two.\n"
        view = build_reflow_view(text, split_lines(text))
        assert view.text == "Short one.\nShort two.\n"
