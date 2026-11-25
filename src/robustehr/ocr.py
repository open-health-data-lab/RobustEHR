"""The OCR confusion table, and the two directions it is read in.

Identification and corruption are the same feature here, which is why they share
one loader rather than one copy each:

* **forward** — ``0`` on the page may be emitted as ``O``. That is what
  `input.ocr_confusion` injects.
* **inverse** — an ``O`` in the text may have been a ``0``. That is what
  :mod:`robustehr.metrics.ocr` uses to ask whether a word already looks like it
  came off a scanner.

The inverse is built by transposing the forward table rather than being authored
separately, so the two can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from robustehr.resources import load_yaml, resource_sha256

OCR_RESOURCE = "ocr_confusions.yaml"


@dataclass(frozen=True, slots=True)
class OcrTable:
    """Character and ligature confusions, in both directions."""

    glyphs: dict[str, tuple[str, ...]]
    """On-the-page character -> what an engine may emit instead."""
    ligatures: tuple[tuple[str, str], ...]
    """``(source run, emitted run)``, length-changing by design."""
    inverse_glyphs: dict[str, tuple[str, ...]]
    """Emitted character -> what it may have been. The transpose of ``glyphs``."""
    inverse_ligatures: tuple[tuple[str, str], ...]
    sha256: str

    def confusable_positions(self, word: str) -> tuple[int, ...]:
        """Indices in ``word`` holding a character this table can substitute.

        The dose denominator for glyph mode: one eligible unit per position, not
        per word, so a severity is a fraction of *characters* — the character
        error rate the OCR literature reports.
        """
        return tuple(i for i, c in enumerate(word) if c in self.glyphs)

    def ligature_positions(self, word: str) -> tuple[tuple[int, str, str], ...]:
        """``(index, source, replacement)`` for every ligature occurrence.

        Overlapping occurrences are all reported. ``mm`` contains ``m`` twice
        and both are things a scanner could misread, so both are eligible.
        """
        found: list[tuple[int, str, str]] = []
        for src, dst in self.ligatures:
            start = word.find(src)
            while start != -1:
                found.append((start, src, dst))
                start = word.find(src, start + 1)
        return tuple(sorted(found))


def _transpose(table: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {}
    for source, emitted in table.items():
        for char in emitted:
            out.setdefault(char, []).append(source)
    # Sorted so the inverse is a pure function of the forward table and does not
    # inherit its iteration order.
    return {k: tuple(sorted(set(v))) for k, v in sorted(out.items())}


@lru_cache(maxsize=1)
def load_table() -> OcrTable:
    raw = load_yaml(OCR_RESOURCE)
    glyphs = {k: tuple(v) for k, v in raw["glyphs"].items()}
    ligatures = tuple((src, dst) for src, dst in raw["ligatures"])
    _check_consistency(glyphs, ligatures)
    return OcrTable(
        glyphs=glyphs,
        ligatures=ligatures,
        inverse_glyphs=_transpose(glyphs),
        inverse_ligatures=tuple(sorted((dst, src) for src, dst in ligatures)),
        sha256=resource_sha256(OCR_RESOURCE),
    )


def _check_consistency(
    glyphs: dict[str, tuple[str, ...]], ligatures: tuple[tuple[str, str], ...]
) -> None:
    """Reject a table that would silently produce no-op edits.

    A row mapping a character to itself, or a ligature whose two sides are
    equal, yields a proposal identical to the source. The applier drops it, the
    dose comes up short, and nothing says why — so it is refused at load time
    where the file can be fixed instead.
    """
    for source, emitted in glyphs.items():
        if not emitted:
            raise ValueError(f"{OCR_RESOURCE}: glyph {source!r} has no confusions")
        if source in emitted:
            raise ValueError(f"{OCR_RESOURCE}: glyph {source!r} confuses with itself")
    for src, dst in ligatures:
        if src == dst:
            raise ValueError(f"{OCR_RESOURCE}: ligature {src!r} confuses with itself")


__all__ = ["OCR_RESOURCE", "OcrTable", "load_table"]
