"""Structural breaks: the whitespace that separates one block from the next.

The unit an operator needs in order to *remove* formatting boundaries, and the
one the baseline needs in order to say how many a note had to begin with.

**A break is not a newline.** Clinical notes are hard-wrapped, so most newlines
are mid-sentence continuations; deleting those would be a re-wrapping operator,
not a loss of structure. The distinction between the two is already the
load-bearing heuristic of this package —
:func:`~robustehr.segment.wrap.wraps_into_next` — so a break is defined as its
complement rather than by a second, competing rule:

    a break is the whitespace between two consecutive non-blank lines
    where the first does **not** wrap into the second.

Two exclusions, both to keep this denominator disjoint from another operator's:

* **inside an aligned block.** Every lab row "starts a new block" as far as
  ``wraps_into_next`` is concerned, so without this clause a single flowsheet
  would supply more breaks than the whole narrative. Merging lab rows also
  re-associates values with labels, which is `render.lab_column_shift`'s
  altering contract, not this one's.
* **inside a list block.** Joining list items into running text is
  `render.bullet_to_prose` / `render.list_to_prose`. Counting those boundaries
  here too would let one severity be delivered twice under two names.

The break that *ends* such a block is kept: that boundary genuinely separates
the block from the narrative around it.
"""

from __future__ import annotations

from dataclasses import dataclass

from robustehr.segment.blocks import AlignedBlock, ListBlock
from robustehr.segment.lines import LineIndex
from robustehr.segment.wrap import wrap_width, wraps_into_next
from robustehr.types import Span


@dataclass(frozen=True, slots=True)
class Break:
    """One structural boundary, addressed as the whitespace that forms it."""

    idx: int
    span: Span
    """From the end of the preceding line's content to the start of the next.

    Everything in it is whitespace by construction — trailing spaces, one or
    more newlines, any blank lines between, and the next line's indent. Taking
    the whole run rather than just the newline is what lets a replacement of
    ``" "`` produce ``foo bar`` from ``foo   \\n\\n  bar`` instead of
    ``foo    bar``, which would read as column alignment to the block detector.
    """
    before_line: int
    after_line: int
    blank_lines: int
    """Blank lines inside the break. Zero for a plain newline boundary."""

    @property
    def is_paragraph(self) -> bool:
        """Whether the boundary is marked by blank lines as well as a newline."""
        return self.blank_lines > 0


def _lines_in_blocks(
    lists: tuple[ListBlock, ...], aligned: tuple[AlignedBlock, ...]
) -> dict[int, str]:
    """Map line index -> the id of the block owning it, for the two exclusions.

    Keyed by a string id rather than a bool so that the *boundary between* two
    adjacent blocks stays a break: two lab tables back to back are separated by
    something a reader can lose.
    """
    owner: dict[int, str] = {}
    for list_block in lists:
        for item in list_block.items:
            owner[item.line_idx] = f"list:{list_block.idx}"
    for aligned_block in aligned:
        for line_idx in aligned_block.lines:
            owner[line_idx] = f"aligned:{aligned_block.idx}"
    return owner


def detect_breaks(
    text: str,
    lines: LineIndex,
    *,
    lists: tuple[ListBlock, ...] = (),
    aligned: tuple[AlignedBlock, ...] = (),
    width: int | None = None,
) -> tuple[Break, ...]:
    """Every structural break in the document, in document order.

    ``width`` defaults to the note's own measured wrap column, so a note that is
    not hard-wrapped at all yields a break at every line boundary — which is
    correct: in that note, every newline *is* structure.
    """
    if len(lines) < 2:
        return ()
    column = wrap_width(lines) if width is None else width
    owner = _lines_in_blocks(lists, aligned)

    found: list[Break] = []
    non_blank = [line.idx for line in lines.lines if not line.is_blank]
    for position, idx in enumerate(non_blank[:-1]):
        nxt = non_blank[position + 1]
        if wraps_into_next(text, lines, idx, column):
            continue
        block = owner.get(idx)
        if block is not None and block == owner.get(nxt):
            continue
        start = lines[idx].content.end
        end = lines[nxt].content.start
        if start >= end:  # pragma: no cover - consecutive lines always separate
            continue
        found.append(
            Break(
                idx=len(found),
                span=Span(start, end),
                before_line=idx,
                after_line=nxt,
                blank_lines=nxt - idx - 1,
            )
        )
    return tuple(found)


def break_counts(breaks: tuple[Break, ...]) -> dict[str, int]:
    """Baseline shape of the breaks in a note.

    Paragraph breaks (blank-line separated) and plain line breaks are reported
    apart because removing them looks different to a reader: losing a blank line
    runs two paragraphs together, losing a bare newline runs two lines together.
    """
    return {
        "n": len(breaks),
        "paragraph": sum(1 for b in breaks if b.is_paragraph),
        "line": sum(1 for b in breaks if not b.is_paragraph),
        "chars": sum(len(b.span) for b in breaks),
    }


__all__ = ["Break", "break_counts", "detect_breaks"]
