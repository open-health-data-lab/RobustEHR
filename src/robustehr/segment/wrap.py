"""Hard-wrap detection, and the reflow view that hides it.

MIMIC-IV discharge summaries are hard-wrapped at roughly 65 characters, so
essentially every sentence spans several physical lines. That is a serialization
artifact of the corpus, not a property of clinical language, and any operator
working at sentence level or above has to see through it.

The approach is a *view*: a string in which wrap newlines (and the trailing
whitespace that precedes them) are replaced by a single space, together with a
monotone piecewise-linear map back to raw offsets. Operators match on the view
and emit edits in raw coordinates, so nothing downstream ever has to know the
view existed.

The wrap width is computed per note as a pure function of its own text, so this
stays deterministic and adapts to corpora wrapped at other widths — or not
wrapped at all.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from robustehr.segment.lines import Line, LineIndex
from robustehr.segment.patterns import DIGITS, LOWERS, TERMINATORS, UPPERS
from robustehr.types import Span

#: Lines shorter than this are ignored when estimating the wrap width; short
#: lines are usually headers, list items or deliberate breaks.
_MIN_MEASURED_LINE = 20

#: A line this far short of the wrap width ended deliberately, not by wrapping.
_SHORT_OF_WIDTH = 6

_BULLET_STARTS = ("-", "*", "#", "+", "•", "|", "‣", "·")

#: A clock time opening a line marks a new timestamped entry, not a wrapped
#: continuation. Nursing and flowsheet notes are written this way:
#: ``0700 Pt awake alert``, ``09:57 VSS afebrile``. Measured on hard-wrapped
#: prose, only 1.2% of genuine continuations begin with a digit at all, so this
#: costs almost nothing and prevents an entire note style from being falsely
#: re-flowed into one paragraph.
_TIME_PREFIX = re.compile(r"^(?:[0-9]{4}(?![0-9])|[0-9]{1,2}:[0-9]{2})")


def wrap_width(lines: LineIndex, default: int = 80) -> int:
    """Estimate the note's own wrap column.

    The 90th percentile of substantial line lengths: robust to the short lines
    that end paragraphs, and to notes that are not wrapped at all (where it
    simply returns a large value and nothing is treated as a continuation).
    """
    measured = sorted(len(line) for line in lines.lines if len(line) >= _MIN_MEASURED_LINE)
    if not measured:
        return default
    return measured[(len(measured) * 9) // 10 - (1 if len(measured) * 9 % 10 == 0 else 0)]


def _starts_new_block(text: str, line: Line) -> bool:
    """True when a line opens a new structural unit rather than continuing one.

    Every clause here rules out a note style that would otherwise be silently
    re-flowed: bullets and table rows, tab-delimited flowsheet rows, timestamped
    nursing entries, numbered lists, and headers.
    """
    content = line.content_text(text)
    if not content:
        return True
    if content[0] in _BULLET_STARTS:
        return True
    if "\t" in content:
        return True  # a delimited row, not prose
    if _TIME_PREFIX.match(content):
        return True
    # "1." / "12)" list markers
    i = 0
    while i < len(content) and content[i] in DIGITS:
        i += 1
    if 0 < i < len(content) and content[i] in ".)":
        return True
    # A header-ish line: a short capitalised label followed by a colon.
    colon = content.find(":")
    return 0 < colon <= 40 and content[0] in UPPERS


def wraps_into_next(  # noqa: PLR0911 - guard clauses, one per case ruled out
    text: str, lines: LineIndex, idx: int, width: int
) -> bool:
    """Does line ``idx`` continue into the following line?

    This is the load-bearing heuristic of the whole segmentation layer, so each
    clause states the case it rules out.
    """
    if idx + 1 >= len(lines):
        return False
    prev = lines[idx]
    if prev.is_blank:
        return False

    blank_run = lines.blank_run_after(idx)
    nxt_idx = idx + 1 + blank_run
    if nxt_idx >= len(lines):
        return False
    nxt = lines[nxt_idx]

    if len(prev) < width - _SHORT_OF_WIDTH:
        return False  # ended well short of the margin: a deliberate break
    content = prev.content_text(text)
    if content and content[-1] in TERMINATORS + ";:":
        return False  # already terminated
    if _starts_new_block(text, nxt):
        return False  # the next line opens something new
    if nxt.indent > prev.indent + 2:
        return False  # a deeper indent is a structural change, not a wrap

    if blank_run:
        # One intervening blank line can sit mid-sentence in this corpus, but
        # only accept it when the continuation clearly is one: at the margin and
        # resuming in lower case. Two or more blanks is always a real break.
        if blank_run > 1:
            return False
        nxt_content = nxt.content_text(text)
        if not nxt_content or nxt_content[0] not in LOWERS:
            return False
    return True


@dataclass(frozen=True, slots=True)
class ReflowView:
    """A newline-free view of the text, with a monotone map back to raw offsets.

    ``view_starts``/``raw_starts``/``lengths`` describe runs of characters shared
    by both strings. Wrap points appear in the view as a single space that has no
    raw counterpart.
    """

    text: str
    view_starts: tuple[int, ...]
    raw_starts: tuple[int, ...]
    lengths: tuple[int, ...]
    raw_len: int
    wrap_width: int

    def to_raw(self, index: int) -> int:
        """Map a view offset to raw. Wrap-space offsets map to the raw wrap point."""
        run = self._run(self.view_starts, index)
        if run is None:
            return self._nearest_raw(index)
        return self.raw_starts[run] + (index - self.view_starts[run])

    def to_raw_span(self, span: Span) -> Span:
        """Map a view span to a contiguous raw span covering the same content."""
        if span.is_empty:
            point = self.to_raw(span.start)
            return Span(point, point)
        return Span(self.to_raw(span.start), self.to_raw(span.end - 1) + 1)

    def from_raw(self, index: int) -> int | None:
        run = self._run(self.raw_starts, index)
        if run is None:
            return None
        return self.view_starts[run] + (index - self.raw_starts[run])

    def _run(self, starts: tuple[int, ...], index: int) -> int | None:
        if not starts:
            return None
        i = bisect_right(starts, index) - 1
        if i < 0:
            return None
        if index < starts[i] + self.lengths[i]:
            return i
        return None

    def _nearest_raw(self, index: int) -> int:
        """Fallback for offsets landing on a synthesized space."""
        if not self.view_starts:
            return 0
        i = bisect_right(self.view_starts, index) - 1
        if i < 0:
            return self.raw_starts[0]
        return self.raw_starts[i] + self.lengths[i]


def build_reflow_view(text: str, lines: LineIndex) -> ReflowView:
    """Join wrapped lines into a flat view, recording the offset map."""
    width = wrap_width(lines)
    out: list[str] = []
    view_starts: list[int] = []
    raw_starts: list[int] = []
    lengths: list[int] = []
    written = 0
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        content = line.content
        if not content.is_empty:
            out.append(content.surface(text))
            view_starts.append(written)
            raw_starts.append(content.start)
            lengths.append(len(content))
            written += len(content)

        if wraps_into_next(text, lines, idx, width):
            out.append(" ")  # the synthesized join; no raw counterpart
            written += 1
            idx += 1 + lines.blank_run_after(idx)
            continue

        if idx + 1 < len(lines):
            out.append("\n")
            written += 1
        idx += 1

    return ReflowView(
        text="".join(out),
        view_starts=tuple(view_starts),
        raw_starts=tuple(raw_starts),
        lengths=tuple(lengths),
        raw_len=len(text),
        wrap_width=width,
    )


__all__ = ["ReflowView", "build_reflow_view", "wrap_width", "wraps_into_next"]
