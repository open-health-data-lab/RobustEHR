"""How much of the corpus already looks like it came off a scanner.

The identification half of `input.ocr_confusion`, and the reason the confusion
table lives in a shared resource rather than inside the operator: **the same
table drives both directions.** Injection applies it forward; this module
applies it in reverse and asks whether the result is a word.

    creatinjne  --( j -> i )-->  creatinine   in the lexicon  -> OCR-suspect
    burn        --( n -> h )-->  burh         not a word
                --( u -> n )-->  brn          not a word      -> not suspect

Method deliberately mirrors :mod:`robustehr.metrics.spelling`, whose near-miss
estimator is already measured and whose failure modes are already published,
rather than introducing a second and unvalidated instrument. Both start from the
same candidate set (out-of-vocabulary alphabetic tokens) and both ask whether one
edit reaches a known term. The only difference is *which* edits are allowed:
Damerau-1 over any character for typing, the OCR table for scanning.

**This is a candidate count, not a corrected rate**, and it must be read the way
`near_miss_edit1` is read. A word can be OCR-reachable by coincidence — `arm` is
one inverse substitution from `am` — so the count is an upper bound on the noise
that is actually present. What makes it useful is not its absolute value but its
*movement*: run it before and after `input.ocr_confusion` and the difference is
attributable, because the two share a table.

Two exclusions keep the count honest:

* **known words are never candidates.** `burn` is a real word, so it is not
  reported even though `burn -> bum` is a textbook OCR error. Counting it would
  make the estimate a function of how many short words the note contains.
* **digit-bearing tokens are excluded.** `5.1` is one inverse substitution from
  `S.1`, and every lab value in the note would be "suspect". The digit rows are
  the clinically dangerous half of the injection and the unmeasurable half of
  the detection — a number that came off a scanner wrong still looks exactly
  like a number. `validation/protocol.md` records that asymmetry rather
  than papering over it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from robustehr.metrics.spelling import MIN_LENGTH, _known_terms
from robustehr.ocr import load_table

if TYPE_CHECKING:  # pragma: no cover
    from robustehr.document import Document
    from robustehr.lexicon import Lexicon


@dataclass(frozen=True, slots=True)
class OcrProfile:
    """One note's OCR-noise baseline, beside the operator's own denominator."""

    note_uid: str
    content_tokens: int
    confusable_chars: int
    """Character positions `input.ocr_confusion` could act on — its denominator.

    Reported next to the estimate on purpose: a note with 4,000 confusable
    positions and 3 suspect tokens is a clean note that offers plenty of
    material, and a table showing only one of those two numbers cannot say so.
    """
    candidates: int
    """Out-of-vocabulary alphabetic tokens, the pool the estimate draws from."""
    suspect: int
    """Candidates reachable from a known term by one inverse OCR confusion."""
    surfaces: Counter[str] = field(default_factory=Counter)

    @property
    def suspect_rate(self) -> float | None:
        """Suspect tokens per content token, or ``None`` when there are none.

        ``None`` rather than ``0``: a note with no content tokens has no rate,
        and averaging a zero in would understate every corpus it appears in.
        """
        if not self.content_tokens:
            return None
        return self.suspect / self.content_tokens


def _reachable(word: str, known: frozenset[str]) -> str | None:
    """A known term one inverse OCR confusion away, or ``None``.

    Both tables are tried, glyph before ligature, and the lexicographically
    first hit wins — the same determinism rule
    :func:`robustehr.metrics.spelling.nearest` follows, so the term a surface is
    reported near is reproducible for a human adjudicator.
    """
    table = load_table()
    found: set[str] = set()
    lowered = word.lower()
    for index, char in enumerate(lowered):
        for source in table.inverse_glyphs.get(char, ()):
            candidate = lowered[:index] + source.lower() + lowered[index + 1 :]
            if candidate != lowered and candidate in known:
                found.add(candidate)
    for emitted, source in table.inverse_ligatures:
        start = lowered.find(emitted)
        while start != -1:
            candidate = lowered[:start] + source + lowered[start + len(emitted) :]
            if candidate != lowered and candidate in known:
                found.add(candidate)
            start = lowered.find(emitted, start + 1)
    return min(found) if found else None


def profile_ocr(
    doc: Document,
    lexicon: Lexicon,
    lexicon_path: Path | None = None,
    *,
    keep_surfaces: bool = True,
) -> OcrProfile:
    """Estimate pre-existing OCR-like noise in one note.

    ``lexicon`` decides what counts as recognised and ``lexicon_path`` builds the
    known-term set — the same split, and the same cached vocabulary, that
    :func:`robustehr.metrics.spelling.profile_near_miss` uses, so the two
    estimates are computed over identical candidate pools and can be compared.
    """
    from robustehr.metrics.dqp import unrecognized_words

    table = load_table()
    known = _known_terms(lexicon_path)
    surfaces: Counter[str] = Counter()
    candidates = 0
    suspect = 0
    seen: dict[str, bool] = {}
    for word in unrecognized_words(doc, lexicon):
        if not word.isalpha() or len(word) < MIN_LENGTH or word in known:
            continue
        candidates += 1
        if word not in seen:
            seen[word] = _reachable(word, known) is not None
        if seen[word]:
            suspect += 1
            if keep_surfaces:
                surfaces[word] += 1

    confusable = 0
    for token in doc.tokens:
        if len(token.span) < 2:
            continue
        confusable += len(table.confusable_positions(token.span.surface(doc.text)))

    return OcrProfile(
        note_uid=doc.uid,
        content_tokens=sum(1 for t in doc.tokens if t.is_content),
        confusable_chars=confusable,
        candidates=candidates,
        suspect=suspect,
        surfaces=surfaces,
    )


__all__ = ["OcrProfile", "profile_ocr"]
