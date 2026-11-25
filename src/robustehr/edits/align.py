"""Bidirectional character alignment between original and perturbed text.

An edit script already contains an alignment: everything *between* two disjoint
edits is matched context. So the map is a list of unchanged runs, stored as
parallel integer arrays and queried by bisection — no dynamic programming, and
no need to recompute an edit distance over 11 kB documents.

This is what keeps annotation offsets, evidence spans and protected spans
meaningful after perturbation, and what makes multi-operator composition
well-defined.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from robustehr.types import Span


@dataclass(frozen=True, slots=True)
class Alignment:
    """Monotone piecewise-linear map over the unchanged runs of a document.

    ``src_starts[i]``/``dst_starts[i]``/``lengths[i]`` describe one run of
    characters carried through unmodified. Characters inside an edited region
    have no counterpart and map to ``None``.
    """

    src_starts: tuple[int, ...]
    dst_starts: tuple[int, ...]
    lengths: tuple[int, ...]
    src_len: int
    dst_len: int

    def _run_containing(self, starts: tuple[int, ...], index: int) -> int | None:
        if not starts:
            return None
        i = bisect_right(starts, index) - 1
        if i < 0:
            return None
        if index < starts[i] + self.lengths[i]:
            return i
        return None

    def src_to_dst(self, index: int) -> int | None:
        """Map an original offset to the perturbed text, or ``None`` if edited away."""
        run = self._run_containing(self.src_starts, index)
        if run is None:
            return None
        return self.dst_starts[run] + (index - self.src_starts[run])

    def dst_to_src(self, index: int) -> int | None:
        """Map a perturbed offset back to the original, or ``None`` if inserted."""
        run = self._run_containing(self.dst_starts, index)
        if run is None:
            return None
        return self.src_starts[run] + (index - self.dst_starts[run])

    def is_unchanged(self, index: int) -> bool:
        return self._run_containing(self.src_starts, index) is not None

    def src_span_to_dst(self, span: Span) -> Span | None:
        """Map a span, contracting to the surviving portion.

        Returns ``None`` when no character of the span survived, which is
        exactly the signal that an operator removed a mention or an evidence
        span outright.
        """
        if span.is_empty:
            start = self.src_to_dst(span.start)
            return None if start is None else Span(start, start)
        first: int | None = None
        last: int | None = None
        for i in range(span.start, span.end):
            mapped = self.src_to_dst(i)
            if mapped is None:
                continue
            if first is None:
                first = mapped
            last = mapped
        if first is None or last is None:
            return None
        return Span(first, last + 1)

    def surviving_chars(self, span: Span) -> int:
        return sum(1 for i in range(span.start, span.end) if self.is_unchanged(i))

    @classmethod
    def identity(cls, length: int) -> Alignment:
        if length == 0:
            return cls((), (), (), 0, 0)
        return cls((0,), (0,), (length,), length, length)


class AlignmentBuilder:
    """Accumulates unchanged runs while the applier walks the document."""

    __slots__ = ("_dst", "_len", "_src")

    def __init__(self) -> None:
        self._src: list[int] = []
        self._dst: list[int] = []
        self._len: list[int] = []

    def add_run(self, src_start: int, dst_start: int, length: int) -> None:
        if length <= 0:
            return
        # Merge with the previous run when they are contiguous on both sides, so
        # the map stays compact and the run count is a stable property.
        if self._len:
            i = len(self._len) - 1
            if (
                self._src[i] + self._len[i] == src_start
                and self._dst[i] + self._len[i] == dst_start
            ):
                self._len[i] += length
                return
        self._src.append(src_start)
        self._dst.append(dst_start)
        self._len.append(length)

    def build(self, src_len: int, dst_len: int) -> Alignment:
        return Alignment(tuple(self._src), tuple(self._dst), tuple(self._len), src_len, dst_len)


__all__ = ["Alignment", "AlignmentBuilder"]
