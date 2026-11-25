"""Tokenization.

A token is the eligible unit for most word- and character-level operators, so
this is a dose denominator and has to be exact rather than convenient.

Three decisions worth defending:

* **De-identification masks are recognised first and are atomic.** 3,344 of them
  sit flush against a word character in the development corpus (``___F``,
  ``___yo``, ``PLT COUNT-___``). A tokenizer that split on the boundary would
  fragment a mask into pieces that individual character operators could then
  mangle, fabricating PHI-shaped text.
* **Whitespace is emitted, not discarded.** The token stream reconstructs the
  document exactly, which turns "did we lose anything?" into an assertion rather
  than a hope, and gives whitespace operators a real unit to count.
* **Decimals are one token.** ``4.46`` must not become ``4`` ``.`` ``46``, or
  punctuation deletion silently turns a lab value into a different number — a
  "preserving" operator producing a factual error.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from enum import StrEnum

from robustehr.segment.deid import DeidIndex, DeidScheme, index_deid
from robustehr.segment.patterns import ALPHA, DIGIT, HSPACE, LETTERS
from robustehr.types import Span


class TokenKind(StrEnum):
    WORD = "word"
    """Letters only: ``patient``, ``denies``, ``HTN``."""
    NUMBER = "number"
    """Digits, possibly with internal decimal points: ``4``, ``4.46``."""
    MIXED = "mixed"
    """Letters and digits: ``HCO3``, ``T2DM``, ``B12``."""
    PLACEHOLDER = "placeholder"
    """A de-identification mask. Atomic, and protected by default."""
    DIVIDER = "divider"
    """An ASCII horizontal rule. Layout, not content."""
    PUNCT = "punct"
    SPACE = "space"
    NEWLINE = "newline"

    @property
    def is_content(self) -> bool:
        return self in {TokenKind.WORD, TokenKind.NUMBER, TokenKind.MIXED}

    @property
    def is_whitespace(self) -> bool:
        return self in {TokenKind.SPACE, TokenKind.NEWLINE}


# Ordered alternation. Placeholder and divider come first so that an underscore
# run is claimed as a whole before any other rule can see part of it.
_TOKEN_RE = re.compile(
    "|".join(
        [
            r"(?P<placeholder>(?<!_)_{3}(?!_))",
            r"(?P<divider>_{4,})",
            rf"(?P<number>[{DIGIT}]+(?:\.[{DIGIT}]+)*)",
            rf"(?P<alnum>[{ALPHA}][{ALPHA}{DIGIT}]*)",
            rf"(?P<space>[{HSPACE}]+)",
            r"(?P<newline>\n)",
            r"(?P<punct>.)",
        ]
    ),
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Token:
    idx: int
    span: Span
    kind: TokenKind
    lower: str
    """ASCII-lowercased surface, precomputed for dictionary lookup.

    Lowercased with an explicit table rather than ``str.lower()``, which is
    Unicode-database dependent for exotic codepoints and would make the same
    note tokenize differently on two CPython point releases.
    """

    def surface(self, text: str) -> str:
        return self.span.surface(text)

    @property
    def is_content(self) -> bool:
        return self.kind.is_content

    def __len__(self) -> int:
        return len(self.span)


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def ascii_lower(text: str) -> str:
    """Case-fold ASCII letters only, leaving everything else untouched."""
    return text.translate(_ASCII_LOWER)


def _classify_alnum(surface: str) -> TokenKind:
    has_non_letter = any(ch not in LETTERS for ch in surface)
    return TokenKind.MIXED if has_non_letter else TokenKind.WORD


@dataclass(frozen=True, slots=True)
class TokenIndex:
    tokens: tuple[Token, ...]
    starts: tuple[int, ...]
    """Token start offsets, ascending. Enables O(log n) span queries.

    Without it, a caller that asks "which tokens are in this span?" once per
    sentence performs a full scan each time, which is quadratic in the document.
    That is not a micro-optimisation: it dominated document construction by a
    factor of four before it was indexed.
    """

    def __len__(self) -> int:
        return len(self.tokens)

    def __getitem__(self, idx: int) -> Token:
        return self.tokens[idx]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.tokens)

    def content(self) -> tuple[Token, ...]:
        """Word, number and mixed tokens — the usual dose denominator."""
        return tuple(t for t in self.tokens if t.is_content)

    def words(self) -> tuple[Token, ...]:
        return tuple(t for t in self.tokens if t.kind is TokenKind.WORD)

    def of_kind(self, *kinds: TokenKind) -> tuple[Token, ...]:
        wanted = set(kinds)
        return tuple(t for t in self.tokens if t.kind in wanted)

    def _window(self, span: Span) -> tuple[int, int]:
        """Index range of tokens that could possibly touch ``span``."""
        lo = bisect_right(self.starts, span.start) - 1
        return max(lo, 0), bisect_right(self.starts, span.end)

    def in_span(self, span: Span) -> tuple[Token, ...]:
        lo, hi = self._window(span)
        return tuple(t for t in self.tokens[lo:hi] if span.contains(t.span))

    def overlapping(self, span: Span) -> tuple[Token, ...]:
        lo, hi = self._window(span)
        return tuple(t for t in self.tokens[lo:hi] if t.span.overlaps(span))


def _base_tokens(text: str) -> list[tuple[Span, TokenKind]]:
    out: list[tuple[Span, TokenKind]] = []
    for match in _TOKEN_RE.finditer(text):
        group = match.lastgroup
        if group == "alnum":
            kind = _classify_alnum(match.group())
        elif group == "placeholder":
            kind = TokenKind.PLACEHOLDER
        elif group == "divider":
            kind = TokenKind.DIVIDER
        elif group == "number":
            kind = TokenKind.NUMBER
        elif group == "space":
            kind = TokenKind.SPACE
        elif group == "newline":
            kind = TokenKind.NEWLINE
        else:
            kind = TokenKind.PUNCT
        out.append((Span(*match.span()), kind))
    return out


def tokenize(text: str, deid: DeidIndex | None = None) -> TokenIndex:
    """Split into tokens, preserving every character.

    ``"".join(t.surface(text) for t in tokenize(text))`` reconstructs ``text``
    exactly. That invariant is asserted over every fixture format.

    De-identification masks are collapsed to single atomic tokens *whatever the
    corpus convention* — ``___``, ``[**Known lastname 12**]``, ``<PATIENT>``,
    ``{{MRN}}``, ``XXXXX``. Doing this as a merge pass over the base tokens,
    rather than by teaching the tokenizer regex about every scheme, keeps the
    regex simple and means a new convention costs one pattern in
    :mod:`robustehr.segment.deid` and nothing here.
    """
    base = _base_tokens(text)
    index = deid if deid is not None else index_deid(text)

    if index.scheme is not DeidScheme.NONE:
        merged: list[tuple[Span, TokenKind]] = []
        masks = sorted(index.spans, key=lambda s: s.start)
        mask_at = 0
        i = 0
        while i < len(base):
            span, kind = base[i]
            while mask_at < len(masks) and masks[mask_at].end <= span.start:
                mask_at += 1
            mask = masks[mask_at] if mask_at < len(masks) else None
            if mask is not None and mask.overlaps(span):
                # Consume every base token the mask touches, and emit one atom.
                while i < len(base) and base[i][0].start < mask.end:
                    i += 1
                merged.append((mask, TokenKind.PLACEHOLDER))
                continue
            merged.append((span, kind))
            i += 1
        base = merged

    tokens = tuple(
        Token(idx=idx, span=span, kind=kind, lower=ascii_lower(span.surface(text)))
        for idx, (span, kind) in enumerate(base)
    )
    return TokenIndex(tokens, tuple(t.span.start for t in tokens))


__all__ = ["Token", "TokenIndex", "TokenKind", "ascii_lower", "tokenize"]
