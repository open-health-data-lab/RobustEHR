"""Physical lines, and the hard-wrap problem.

A **physical line** is a ``\\n``-delimited run. A **logical sentence** spans
several of them. Conflating the two is the single most common way to get a
clinical-text denominator wrong, so they are separate layers here and the join
between them is explicit.

Measured on the development corpus: line length p99 = 65 characters, 99.9% of
lines are at most 70, and the per-note modal width is 58-65. Wrap points carry
trailing whitespace ("``...word  \\n``") on 51% of non-blank lines.

Two findings that break the obvious implementations:

* **Blank lines are not paragraph boundaries.** A wrapped sentence sometimes
  contains one::

      "...with positive tilt table  \\n\\ntesting ___ after syncopal episodes;  \\n"

  Both an empty line and a line holding a single space occur, and both appear
  *within* as well as *between* paragraphs. Any segmenter that treats a run of
  blank lines as a paragraph break is wrong on this corpus.

* **A blank "line" may be whitespace, not empty.** ``is_blank`` tests content,
  not length.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from robustehr.segment.patterns import HSPACE
from robustehr.types import Span

_TRAILING_HSPACE = re.compile(f"[{HSPACE}]+$")
_LEADING_HSPACE = re.compile(f"^[{HSPACE}]*")


@dataclass(frozen=True, slots=True)
class Line:
    """One physical line, with its whitespace structure made explicit."""

    idx: int
    span: Span
    """The line's characters, excluding the newline."""
    newline: Span
    """The newline itself; zero-length at end of file."""
    content: Span
    """The line minus leading indent and trailing whitespace."""
    indent: int
    is_blank: bool
    has_trailing_space: bool

    @property
    def full(self) -> Span:
        return Span(self.span.start, self.newline.end)

    def text(self, source: str) -> str:
        return self.span.surface(source)

    def content_text(self, source: str) -> str:
        return self.content.surface(source)

    def __len__(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class LineIndex:
    lines: tuple[Line, ...]

    def __len__(self) -> int:
        return len(self.lines)

    def __getitem__(self, idx: int) -> Line:
        return self.lines[idx]

    def at_offset(self, index: int) -> Line | None:
        for line in self.lines:
            if line.span.start <= index <= line.span.end:
                return line
        return None

    def blank_run_after(self, idx: int) -> int:
        """How many consecutive blank lines follow line ``idx``.

        The distinction that matters: *one* intervening blank line can sit
        mid-sentence, so it is not evidence of a break. Two or more is.
        """
        count = 0
        for line in self.lines[idx + 1 :]:
            if not line.is_blank:
                break
            count += 1
        return count

    def non_blank(self) -> tuple[Line, ...]:
        return tuple(line for line in self.lines if not line.is_blank)


def split_lines(text: str) -> LineIndex:
    """Split into physical lines, preserving every offset.

    Never normalizes. Trailing whitespace, indentation style and blank-line form
    are all measurable properties of the note and several operators target them
    directly, so discarding them here would destroy the signal.
    """
    lines: list[Line] = []
    start = 0
    idx = 0
    length = len(text)

    while start <= length:
        newline_at = text.find("\n", start)
        if newline_at == -1:
            end = length
            newline = Span(length, length)
        else:
            end = newline_at
            newline = Span(newline_at, newline_at + 1)

        raw = text[start:end]
        indent_match = _LEADING_HSPACE.match(raw)
        indent = indent_match.end() if indent_match else 0
        trailing = _TRAILING_HSPACE.search(raw, indent)
        content_end = trailing.start() if trailing else len(raw)
        content = Span(start + indent, start + max(indent, content_end))

        lines.append(
            Line(
                idx=idx,
                span=Span(start, end),
                newline=newline,
                content=content,
                indent=indent,
                is_blank=content.is_empty,
                has_trailing_space=trailing is not None,
            )
        )

        if newline_at == -1:
            break
        start = newline_at + 1
        idx += 1

    # A document ending in "\n" produces a final empty line above; that is
    # correct — it is a real, addressable position — but drop it when the text
    # is empty overall so an empty document has zero lines rather than one.
    if not text:
        return LineIndex(())
    return LineIndex(tuple(lines))


__all__ = ["Line", "LineIndex", "split_lines"]
