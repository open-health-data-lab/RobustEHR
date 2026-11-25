"""Sentence segmentation.

Sentences are the denominator for deletion, duplication, distractor injection
and every assertion-level operator, and they are also the scope within which
context cues are resolved. Getting the boundaries wrong therefore misstates dose
*and* misattributes negation, so this is one of the highest-consequence pieces
of the package — which is why it is hand-written, versioned and tested against
every note format rather than delegated to a general-purpose splitter.

Off-the-shelf splitters are wrong on clinical text in specific, repeatable ways.
Each is handled here:

* **A lot of clinical text has no terminators at all.** ``0700 Pt awake alert
  oriented x3`` is a complete unit. A splitter that requires a period returns one
  enormous sentence for a whole nursing note, and the sentence denominator
  collapses to 1. Line structure is the fallback boundary.
* **De-identification manufactures false terminators.** ``PLT COUNT-___. Mood
  disorder`` is a lab value running into prose, and ``___. Tonsillectomy`` is a
  list item whose *number* was masked.
* **Decimals and dosages are full of periods.** ``4.46``, ``0.4 mg``. These are
  already single tokens, so the splitter works over the token stream rather than
  over characters and cannot break them.
* **Genus abbreviations are single capitals.** Splitting ``E. coli`` yields a
  sentence ending in "E".
* **Hard wrap puts newlines inside sentences.** Boundaries are found on
  logically-joined lines, then mapped back to raw offsets.
* **Not every line is prose.** Lab blocks, table rows and list items are emitted
  as their own non-prose units so that an operator can exclude them from a prose
  denominator instead of silently perturbing a flowsheet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from robustehr.resources import load_yaml, resource_sha256
from robustehr.segment.blocks import AlignedBlock, ListBlock
from robustehr.segment.headers import Header, HeaderGrammar
from robustehr.segment.lines import LineIndex
from robustehr.segment.patterns import DIGITS, TERMINATORS, UPPERS
from robustehr.segment.tokens import TokenIndex, TokenKind
from robustehr.segment.wrap import wrap_width, wraps_into_next
from robustehr.types import Span

SENTENCES_RESOURCE = "sentences.yaml"

#: Characters that may open or close a quotation and therefore may sit between a
#: terminator and the capital that confirms a boundary. Typographic quotes are
#: included deliberately: rich-text exports and copied patient speech use them,
#: and a note quoting the patient is exactly where boundary detection matters.
_OPENERS = frozenset("\"'“‘([{")  # noqa: RUF001 - typographic quotes are intended
_CLOSERS = frozenset("\"'”’)]}")  # noqa: RUF001 - typographic quotes are intended


@dataclass(frozen=True, slots=True)
class SentenceRules:
    abbreviations: frozenset[str]
    single_letter_is_abbreviation: bool
    sha256: str


@lru_cache(maxsize=1)
def load_rules() -> SentenceRules:
    raw: dict[str, Any] = load_yaml(SENTENCES_RESOURCE)
    return SentenceRules(
        abbreviations=frozenset(str(a).lower() for a in raw["abbreviations"]),
        single_letter_is_abbreviation=bool(raw["single_letter_is_abbreviation"]),
        sha256=resource_sha256(SENTENCES_RESOURCE),
    )


@dataclass(frozen=True, slots=True)
class Sentence:
    idx: int
    span: Span
    """Contiguous in raw text. May contain newlines when the source is wrapped."""
    is_prose: bool
    """``False`` for lab blocks, table rows, list items and headers.

    Kept as units rather than dropped, so that an operator can choose a
    prose-only denominator explicitly instead of a splitter silently deciding
    for it.
    """
    terminator: str | None
    """The punctuation that ended it, or ``None`` when a line break did."""
    line_idxs: tuple[int, ...]

    def text(self, source: str) -> str:
        return self.span.surface(source)


@dataclass(frozen=True, slots=True)
class SentenceIndex:
    sentences: tuple[Sentence, ...]

    def __len__(self) -> int:
        return len(self.sentences)

    def __getitem__(self, idx: int) -> Sentence:
        return self.sentences[idx]

    def prose(self) -> tuple[Sentence, ...]:
        return tuple(s for s in self.sentences if s.is_prose)

    def at_offset(self, index: int) -> Sentence | None:
        for sentence in self.sentences:
            if sentence.span.start <= index < sentence.span.end:
                return sentence
        return None

    def covering(self, span: Span) -> tuple[Sentence, ...]:
        return tuple(s for s in self.sentences if s.span.overlaps(span))


def _logical_units(text: str, lines: LineIndex) -> list[tuple[int, int]]:
    """Group physical lines into logical ones, following wrap continuations."""
    width = wrap_width(lines)
    units: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        if lines[i].is_blank:
            i += 1
            continue
        start = i
        while i < len(lines) and wraps_into_next(text, lines, i, width):
            i += 1 + lines.blank_run_after(i)
        units.append((start, i))
        i += 1
    return units


def _is_abbreviation(prev_surface: str, rules: SentenceRules) -> bool:
    stripped = prev_surface.strip()
    if not stripped:
        return False
    if rules.single_letter_is_abbreviation and len(stripped) == 1 and stripped in UPPERS:
        return True
    return stripped.lower() in rules.abbreviations


def _confirms_boundary(surface: str) -> bool:
    """Does the first meaningful character after a terminator open a sentence?

    Whitespace and quotation marks are skipped: the character that decides is
    the first letter or digit. Failing to skip the separating space is a silent
    catastrophe — it collapses an entire free-text paragraph into one sentence
    and drives the sentence denominator to 1.
    """
    for ch in surface:
        if ch in " \t\n\r" or ch in _OPENERS or ch in _CLOSERS:
            continue
        return ch in UPPERS or ch in DIGITS
    return True  # nothing follows: end of unit


def _opens_a_decimal(token: Any, following: Sequence[Any]) -> bool:
    """Is this period the decimal point of a number written without a leading zero?

    True only when a digit follows *immediately*, with no space. ``TB .5`` is a
    value; ``Stage 3. 5 patients`` is a boundary, and the space is what separates
    them.
    """
    if token.lower != ".":
        return False
    nxt = following[0] if following else None
    return nxt is not None and nxt.kind is TokenKind.NUMBER and nxt.span.start == token.span.end


def _split_prose(  # noqa: PLR0912 - one branch per documented boundary rule
    text: str,
    span: Span,
    tokens: TokenIndex,
    rules: SentenceRules,
    forced: tuple[int, ...] = (),
) -> list[tuple[Span, str | None]]:
    """Find boundaries inside one logical prose unit.

    Works over tokens rather than characters, which is what makes decimals and
    de-identification masks unsplittable: the tokenizer has already made each of
    them a single atom, so no rule here can see the period inside ``4.46``.
    """
    inside = tokens.in_span(span)
    if not inside:
        return [(span, None)]

    boundaries: list[tuple[int, str | None]] = []
    for position, token in enumerate(inside):
        if token.kind is not TokenKind.PUNCT or token.lower not in TERMINATORS:
            continue

        previous = next((t for t in reversed(inside[:position]) if not t.kind.is_whitespace), None)
        if previous is not None:
            if previous.kind is TokenKind.NUMBER and token.lower == ".":
                # "1." / "2." — a list marker, or a number the author ended a
                # clause with. Only a following capital settles it, checked below.
                pass
            elif previous.kind is TokenKind.WORD and _is_abbreviation(previous.lower, rules):
                continue

        # A run of terminators ("...", "?!") ends at the last one.
        following = inside[position + 1 :]
        if following and following[0].kind is TokenKind.PUNCT and following[0].lower in TERMINATORS:
            continue

        if _opens_a_decimal(token, following):
            # A *leading* decimal: "TB .5", "Lactate .9". The tokenizer merges
            # "4.46" into one atom, so no rule here can see inside it — but it
            # cannot merge a point that has no digit before it, so ".5" arrives
            # as PUNCT followed by NUMBER and every terminator rule fires. The
            # boundary confirmation does not save us either, because it accepts
            # a following digit so that "... 2. Hypertension" still splits.
            #
            # Found by comparing against PyRuSH on MIMIC discharge summaries,
            # where it split lab lines mid-value: "Lipase 54 / TB ." | "5 / Alb".
            continue

        remainder = text[token.span.end : span.end]
        if not _confirms_boundary(remainder):
            continue
        boundaries.append((token.span.end, token.lower))

    boundaries.extend((offset, None) for offset in forced)
    boundaries.sort(key=lambda b: b[0])

    if not boundaries:
        return [(span, None)]

    out: list[tuple[Span, str | None]] = []
    cursor = span.start
    for end, terminator in boundaries:
        # Absorb trailing space so a sentence does not begin with a blank.
        stop = end
        while stop < span.end and text[stop] in " \t":
            stop += 1
        out.append((Span(cursor, stop), terminator))
        cursor = stop
    if cursor < span.end:
        out.append((Span(cursor, span.end), None))
    return [(s, t) for s, t in out if len(s) > 0]


def _non_prose_lines(
    headers: tuple[Header, ...],
    lists: tuple[ListBlock, ...],
    aligned: tuple[AlignedBlock, ...],
) -> frozenset[int]:
    """Line indices that are structure rather than prose.

    Inline headers are deliberately excluded. ``INDICATION: ___ year old with
    pleuritic chest pain`` carries its content on the header line, so marking
    the whole line structural would exclude real prose from every prose-scoped
    operator. Only label-only lines — standalone and markdown headers — are
    structure.
    """
    marked: set[int] = {h.line_idx for h in headers if h.grammar is not HeaderGrammar.INLINE}
    marked |= {item.line_idx for block in lists for item in block.items}
    marked |= {idx for block in aligned for idx in block.lines}
    return frozenset(marked)


def _forced_boundaries(headers: tuple[Header, ...], span: Span) -> tuple[int, ...]:
    """Offsets inside ``span`` where a sentence must end regardless of syntax.

    An inline header's marker is one: the label and its value are different
    statements, and no punctuation separates them.
    """
    return tuple(
        sorted(
            h.marker.end
            for h in headers
            if h.grammar is HeaderGrammar.INLINE and span.start < h.marker.end < span.end
        )
    )


def split_sentences(
    text: str,
    lines: LineIndex,
    tokens: TokenIndex,
    *,
    headers: tuple[Header, ...] = (),
    lists: tuple[ListBlock, ...] = (),
    aligned: tuple[AlignedBlock, ...] = (),
) -> SentenceIndex:
    """Split into sentences, falling back to line boundaries where prose does not.

    ``headers``, ``lists`` and ``aligned`` mark lines that are structure rather
    than prose; passing them is optional but strongly recommended, since without
    them a lab block is split on its decimal points and a medication list is
    treated as one long sentence.
    """
    if not text:
        return SentenceIndex(())

    rules = load_rules()
    structural = _non_prose_lines(headers, lists, aligned)

    found: list[Sentence] = []
    for start_line, end_line in _logical_units(text, lines):
        unit_lines = tuple(range(start_line, end_line + 1))
        span = Span(lines[start_line].content.start, lines[end_line].content.end)
        if span.is_empty:
            continue

        if any(idx in structural for idx in unit_lines):
            found.append(
                Sentence(
                    idx=len(found),
                    span=span,
                    is_prose=False,
                    terminator=None,
                    line_idxs=unit_lines,
                )
            )
            continue

        for piece, terminator in _split_prose(
            text, span, tokens, rules, _forced_boundaries(headers, span)
        ):
            found.append(
                Sentence(
                    idx=len(found),
                    span=piece,
                    is_prose=True,
                    terminator=terminator,
                    line_idxs=unit_lines,
                )
            )

    return SentenceIndex(tuple(found))


__all__ = [
    "SENTENCES_RESOURCE",
    "Sentence",
    "SentenceIndex",
    "SentenceRules",
    "load_rules",
    "split_sentences",
]
