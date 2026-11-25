"""Tokenization: the denominator for most word- and character-level operators."""

from __future__ import annotations

import pytest

from robustehr.segment.tokens import TokenKind, ascii_lower, tokenize
from robustehr.types import Span
from tests.fixtures.notes import FIXTURES


def kinds(text: str) -> list[tuple[str, TokenKind]]:
    return [(t.surface(text), t.kind) for t in tokenize(text)]


class TestReconstruction:
    @pytest.mark.parametrize("name", sorted(FIXTURES))
    def test_tokens_reconstruct_the_document(self, name: str) -> None:
        """Nothing may be silently dropped: the stream is the document."""
        text = FIXTURES[name]
        assert "".join(t.surface(text) for t in tokenize(text)) == text

    def test_offsets_are_contiguous(self) -> None:
        text = FIXTURES["ambiguous_ra"]
        tokens = tokenize(text)
        assert tokens[0].span.start == 0
        for prev, nxt in zip(tokens.tokens, tokens.tokens[1:], strict=False):
            assert prev.span.end == nxt.span.start

    def test_empty_text(self) -> None:
        assert len(tokenize("")) == 0


class TestPlaceholders:
    def test_placeholder_is_atomic(self) -> None:
        assert kinds("___") == [("___", TokenKind.PLACEHOLDER)]

    @pytest.mark.parametrize("text", ["___F", "___yo", "COUNT-___", "Plt ___"])
    def test_glued_placeholders_are_not_fragmented(self, text: str) -> None:
        """3,344 real masks sit flush against a word character.

        Fragmenting one would let a character operator mangle part of a PHI
        mask, fabricating PHI-shaped text.
        """
        placeholders = [t for t in tokenize(text) if t.kind is TokenKind.PLACEHOLDER]
        assert len(placeholders) == 1
        assert placeholders[0].surface(text) == "___"

    def test_divider_is_not_a_placeholder(self) -> None:
        rule = "_" * 56
        assert kinds(rule) == [(rule, TokenKind.DIVIDER)]

    def test_short_underscore_runs_are_punctuation(self) -> None:
        assert [k for _, k in kinds("__")] == [TokenKind.PUNCT, TokenKind.PUNCT]


class TestClassification:
    def test_decimals_stay_whole(self) -> None:
        """Splitting 4.46 would let punctuation deletion turn it into 446."""
        assert kinds("4.46") == [("4.46", TokenKind.NUMBER)]

    def test_letters_are_words(self) -> None:
        assert kinds("patient") == [("patient", TokenKind.WORD)]
        assert kinds("HTN") == [("HTN", TokenKind.WORD)]

    def test_letter_digit_mixes(self) -> None:
        for surface in ("HCO3", "T2DM", "B12"):
            assert kinds(surface) == [(surface, TokenKind.MIXED)]

    def test_slash_is_punctuation(self) -> None:
        assert [k for _, k in kinds("s/p")] == [
            TokenKind.WORD,
            TokenKind.PUNCT,
            TokenKind.WORD,
        ]

    def test_whitespace_kinds(self) -> None:
        assert [k for _, k in kinds("a b\nc")] == [
            TokenKind.WORD,
            TokenKind.SPACE,
            TokenKind.WORD,
            TokenKind.NEWLINE,
            TokenKind.WORD,
        ]

    def test_content_filter_excludes_whitespace_and_punctuation(self) -> None:
        text = "BP 128/74, HR 78."
        assert [t.surface(text) for t in tokenize(text).content()] == [
            "BP",
            "128",
            "74",
            "HR",
            "78",
        ]

    def test_lower_is_precomputed_ascii_only(self) -> None:
        text = "HTN"
        assert tokenize(text)[0].lower == "htn"

    def test_ascii_lower_leaves_non_ascii_alone(self) -> None:
        assert ascii_lower("Barré") == "barré"


class TestQueries:
    def test_in_span_requires_containment(self) -> None:
        text = "alpha beta gamma"
        inside = tokenize(text).in_span(Span(6, 10))
        assert [t.surface(text) for t in inside] == ["beta"]

    def test_span_queries_do_not_scan_the_document(self) -> None:
        """Guards against a quadratic that already cost a 2.6x slowdown.

        The sentence splitter asks "which tokens are in this span?" once per
        logical unit. If that scans the whole token list each time, document
        construction becomes quadratic — it was calling Span.contains 64 million
        times per 100 notes before the index was added.
        """
        text = ("word " * 5000).strip()
        index = tokenize(text)
        assert len(index) > 9000
        lo, hi = index._window(Span(0, 12))
        assert hi - lo < 20, f"window scanned {hi - lo} tokens for a 12-char span"

    def test_starts_are_sorted_and_aligned(self) -> None:
        index = tokenize("Some clinical text with 4.46 and ___ inside.")
        assert list(index.starts) == sorted(index.starts)
        assert len(index.starts) == len(index.tokens)
        assert all(t.span.start == s for t, s in zip(index.tokens, index.starts, strict=True))

    def test_overlapping_includes_partial(self) -> None:
        text = "alpha beta gamma"
        touching = tokenize(text).overlapping(Span(3, 8))
        assert [t.surface(text) for t in touching] == ["alpha", " ", "beta"]

    def test_of_kind(self) -> None:
        text = "EF 35-40%"
        numbers = tokenize(text).of_kind(TokenKind.NUMBER)
        assert [t.surface(text) for t in numbers] == ["35", "40"]
