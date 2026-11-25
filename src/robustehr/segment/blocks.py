"""List blocks and whitespace-aligned value blocks.

Both are dose denominators for structural operators, and both vary sharply by
corpus — which is why neither is hard-coded to one marker style.

**Lists.** Measured across the development corpus: numbered items in 99.5% of
notes (~30 each), ``#`` problem-list bullets in ~70%, ``-`` in ~66%, ``*`` in
~11%. Other corpora invert this. So marker style is *detected and reported*
rather than assumed, and eligibility is reported per style — otherwise
"bullet-to-prose at 30%" means something different in every note.

**Aligned blocks.** Lines like::

    WBC-6.9    RBC-4.46   Hgb-12.8   Hct-38.2
    Na-138     K-4.1      Cl-102     HCO3-26

carry meaning in their column positions. Collapsing the runs of spaces is
reference-preserving; shifting a column by one field re-associates values with
the wrong labels and is not. They appear in 100% of development-corpus notes
(~7 lines each) and are the nearest analogue to a table in a corpus that has no
tables at all — but genuine pipe- and tab-delimited rows do occur elsewhere, so
those are recognised too and kept as a distinct style.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from robustehr.segment.lines import Line, LineIndex
from robustehr.types import Span


class ListStyle(StrEnum):
    NUMBERED = "numbered"
    """``1.`` / ``12)`` — dominant in medication and problem lists."""
    HASH = "hash"
    """``# Hypertension`` — the clinical problem-list convention."""
    DASH = "dash"
    ASTERISK = "asterisk"
    BULLET = "bullet"
    """``•`` and friends, from rich-text exports."""


class BlockStyle(StrEnum):
    ALIGNED_SPACES = "aligned_spaces"
    """Columns held by runs of spaces. No delimiter to rely on."""
    PIPE_TABLE = "pipe_table"
    TAB_DELIMITED = "tab_delimited"


_MARKERS: tuple[tuple[ListStyle, re.Pattern[str]], ...] = (
    (ListStyle.NUMBERED, re.compile(r"^(?P<marker>[0-9]{1,3}[.)])(?=[ \t])")),
    (ListStyle.HASH, re.compile(r"^(?P<marker>#{1,3})(?=[ \t])")),
    (ListStyle.DASH, re.compile(r"^(?P<marker>-)(?=[ \t])")),
    (ListStyle.ASTERISK, re.compile(r"^(?P<marker>\*)(?=[ \t])")),
    (ListStyle.BULLET, re.compile(r"^(?P<marker>[•‣·])(?=[ \t]?)")),
)

#: Two or more spaces holding a column apart. Counted as the whitespace dose
#: denominator; a single space is just a word gap.
_COLUMN_GAP = re.compile(r"[ ]{2,}")

#: Three or more is the *detection* signal for genuine column alignment.
_WIDE_GAP = re.compile(r"[ ]{3,}")

#: ``Label-Value`` or ``Label: Value`` repeated across a line, as in
#: ``WBC-6.9 RBC-4.46 Hgb-12.8``.
_KEY_VALUE = re.compile(r"[A-Za-z][A-Za-z0-9/%]*[-:][A-Za-z0-9.<>+*_]+")


@dataclass(frozen=True, slots=True)
class ListItem:
    line_idx: int
    marker: Span
    content: Span
    style: ListStyle
    indent: int


@dataclass(frozen=True, slots=True)
class ListBlock:
    """A run of consecutive items sharing a marker style."""

    idx: int
    style: ListStyle
    items: tuple[ListItem, ...]
    span: Span

    def __len__(self) -> int:
        return len(self.items)


@dataclass(frozen=True, slots=True)
class AlignedBlock:
    """A run of lines whose layout carries meaning."""

    idx: int
    style: BlockStyle
    lines: tuple[int, ...]
    span: Span
    column_gaps: int
    """Total number of multi-space runs, for the whitespace dose denominator."""
    self_labelling: bool
    """Whether each value carries its own label, e.g. ``WBC-6.9 RBC-4.46``.

    This decides whether a column shift is dangerous. In a self-labelling block
    the pairing survives any amount of re-spacing, so shifting is
    reference-preserving. In a position-dependent block — a header row plus
    value rows — shifting re-associates values with the wrong labels, which is
    the genuinely harmful EHR rendering failure and must be declared altering.
    """


def _match_marker(text: str, line: Line) -> tuple[ListStyle, Span] | None:
    content = line.content_text(text)
    for style, pattern in _MARKERS:
        match = pattern.match(content)
        if match:
            start = line.content.start + match.start("marker")
            return style, Span(start, start + len(match.group("marker")))
    return None


def detect_lists(text: str, lines: LineIndex) -> tuple[ListBlock, ...]:
    """Group consecutive list items into blocks, one block per marker style.

    A style change starts a new block, so a numbered medication list followed by
    a dashed instruction list are two units rather than one — which keeps the
    per-style eligibility honest.
    """
    blocks: list[ListBlock] = []
    current: list[ListItem] = []
    current_style: ListStyle | None = None

    def flush() -> None:
        nonlocal current, current_style
        if current:
            blocks.append(
                ListBlock(
                    idx=len(blocks),
                    style=current_style or ListStyle.DASH,
                    items=tuple(current),
                    span=Span(current[0].marker.start, current[-1].content.end),
                )
            )
        current = []
        current_style = None

    for line in lines.lines:
        if line.is_blank:
            continue
        found = _match_marker(text, line)
        if found is None:
            # A non-item, non-blank line ends the block unless it is an indented
            # continuation of the previous item.
            if current and line.indent <= current[-1].indent:
                flush()
            continue
        style, marker = found
        if current_style is not None and style is not current_style:
            flush()
        current_style = style
        current.append(
            ListItem(
                line_idx=line.idx,
                marker=marker,
                content=Span(marker.end, line.content.end),
                style=style,
                indent=line.indent,
            )
        )
    flush()
    return tuple(blocks)


def _line_block_style(text: str, line: Line) -> tuple[BlockStyle, bool] | None:
    """Classify one line, returning its style and whether it is self-labelling."""
    content = line.content_text(text)
    if not content:
        return None
    if "\t" in content:
        return BlockStyle.TAB_DELIMITED, False
    if content.count("|") >= 2:
        return BlockStyle.PIPE_TABLE, False
    pairs = len(_KEY_VALUE.findall(content))
    if pairs >= 2:
        # `WBC-6.9 RBC-4.46 Hgb-12.8` — each value carries its own label, so the
        # pairing survives re-spacing. The dominant form in the development
        # corpus, and requiring a wide gap as well misses it entirely.
        return BlockStyle.ALIGNED_SPACES, True
    if len(_WIDE_GAP.findall(content)) >= 2:
        # Columns held only by position; re-spacing destroys the association.
        return BlockStyle.ALIGNED_SPACES, False
    return None


def detect_aligned_blocks(text: str, lines: LineIndex) -> tuple[AlignedBlock, ...]:
    """Group consecutive column-structured lines, one block per style."""
    blocks: list[AlignedBlock] = []
    run: list[Line] = []
    run_style: BlockStyle | None = None
    run_self_labelling = True

    def flush() -> None:
        nonlocal run, run_style, run_self_labelling
        if run and run_style is not None:
            gaps = sum(len(_COLUMN_GAP.findall(line.content_text(text))) for line in run)
            blocks.append(
                AlignedBlock(
                    idx=len(blocks),
                    style=run_style,
                    lines=tuple(line.idx for line in run),
                    span=Span(run[0].content.start, run[-1].content.end),
                    column_gaps=gaps,
                    # One position-dependent line makes the whole block unsafe
                    # to shift, so this is a conjunction rather than a majority.
                    self_labelling=run_self_labelling,
                )
            )
        run = []
        run_style = None
        run_self_labelling = True

    for line in lines.lines:
        classified = None if line.is_blank else _line_block_style(text, line)
        if classified is None or (run_style is not None and classified[0] is not run_style):
            flush()
        if classified is not None:
            style, self_labelling = classified
            run_style = style
            run_self_labelling = run_self_labelling and self_labelling
            run.append(line)
    flush()
    return tuple(blocks)


def list_style_counts(blocks: tuple[ListBlock, ...]) -> dict[str, int]:
    """Item count per marker style, for per-style eligibility reporting."""
    counts = {style.value: 0 for style in ListStyle}
    for block in blocks:
        counts[block.style.value] += len(block.items)
    return counts


__all__ = [
    "AlignedBlock",
    "BlockStyle",
    "ListBlock",
    "ListItem",
    "ListStyle",
    "detect_aligned_blocks",
    "detect_lists",
    "list_style_counts",
]
