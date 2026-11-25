"""Section assembly.

A section runs from its header to the next header at the same or shallower
depth. Two details make this less mechanical than it sounds:

* **An inline header owns only its own line.** ``Service: MEDICINE`` is a
  complete section; treating it as opening a body that runs to the next header
  would swallow everything after it. Standalone and markdown headers do open a
  body.
* **Text before the first header is a real section.** Letters open with a
  salutation, MIMIC notes open with a metadata block, and nursing notes have no
  headers at all — in which case the whole document is one implicit section.
  Dropping the preamble would silently exclude it from every section-scoped
  operator.

Sections are what ``section_scope`` selects on, so getting the boundaries wrong
would misattribute dose rather than merely mislabel it.
"""

from __future__ import annotations

from dataclasses import dataclass

from robustehr.segment.headers import Header, HeaderGrammar
from robustehr.types import Span

PREAMBLE_ID = "_preamble"
"""Canonical id for the text before the first header."""

INTERSTITIAL_ID = "_interstitial"
"""Canonical id for text that belongs to no header's section.

Inline headers own only their own line, so anything written after one and
before the next header — a letter's closing, a trailing paragraph — would
otherwise belong to nothing. Sections must *tile* the document: a gap silently
excludes that text from every section-scoped operator, and makes the section
denominator disagree with the character count.
"""


@dataclass(frozen=True, slots=True)
class Section:
    idx: int
    header: Header | None
    """``None`` for the implicit preamble."""
    body: Span
    """Content after the header, excluding the header line itself."""
    full: Span
    """Header and body together — what a section-drop operator removes."""
    canonical_id: str | None
    depth: int

    @property
    def name(self) -> str:
        if self.header is None:
            return PREAMBLE_ID
        return self.canonical_id or self.header.raw_name

    @property
    def is_canonical(self) -> bool:
        return self.canonical_id is not None

    def text(self, source: str) -> str:
        return self.full.surface(source)

    def body_text(self, source: str) -> str:
        return self.body.surface(source)


def _opens_a_body(header: Header) -> bool:
    return header.grammar is not HeaderGrammar.INLINE


def build_sections(text: str, headers: tuple[Header, ...]) -> tuple[Section, ...]:
    """Assemble sections from detected headers.

    ``headers`` should already be filtered to the kinds that count as structure;
    passing every header-shaped line would nest medication boilerplate inside
    the note's outline.
    """
    if not text:
        return ()

    ordered = sorted(headers, key=lambda h: h.span.start)
    sections: list[Section] = []

    first_start = ordered[0].span.start if ordered else len(text)
    if first_start > 0:
        # Everything before the first header, including the case where there are
        # no headers at all and the whole note is one section.
        preamble = Span(0, first_start)
        sections.append(
            Section(
                idx=0,
                header=None,
                body=preamble,
                full=preamble,
                canonical_id=PREAMBLE_ID,
                depth=0,
            )
        )

    for position, header in enumerate(ordered):
        body_start = header.span.end
        if _opens_a_body(header):
            # A standalone or markdown header owns everything up to the next
            # header at the same or shallower depth.
            end = len(text)
            for later in ordered[position + 1 :]:
                if later.depth <= header.depth:
                    end = later.span.start
                    break
        else:
            # An inline header owns its own line only.
            newline = text.find("\n", body_start)
            end = len(text) if newline == -1 else newline + 1

        end = max(end, body_start)
        sections.append(
            Section(
                idx=len(sections),
                header=header,
                body=Span(body_start, end),
                full=Span(header.span.start, end),
                canonical_id=header.canonical_id,
                depth=header.depth,
            )
        )

    return _tile(text, sections)


def _tile(text: str, sections: list[Section]) -> tuple[Section, ...]:
    """Fill any range covered by no section, so the set tiles the document."""
    covered: list[tuple[int, int]] = sorted((s.full.start, s.full.end) for s in sections)
    merged: list[list[int]] = []
    for start, end in covered:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    gaps: list[Span] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            gaps.append(Span(cursor, start))
        cursor = max(cursor, end)
    if cursor < len(text):
        gaps.append(Span(cursor, len(text)))

    filled = [
        Section(
            idx=0,
            header=None,
            body=gap,
            full=gap,
            canonical_id=INTERSTITIAL_ID,
            depth=0,
        )
        for gap in gaps
    ]
    ordered = sorted([*sections, *filled], key=lambda s: (s.full.start, -len(s.full)))
    # Reindex so idx reflects document order after the fillers are woven in.
    return tuple(
        Section(
            idx=position,
            header=s.header,
            body=s.body,
            full=s.full,
            canonical_id=s.canonical_id,
            depth=s.depth,
        )
        for position, s in enumerate(ordered)
    )


def section_at(sections: tuple[Section, ...], index: int) -> Section | None:
    """The deepest section containing a character offset."""
    best: Section | None = None
    for section in sections:
        if section.full.start <= index < section.full.end and (
            best is None or section.depth >= best.depth
        ):
            best = section
    return best


def sections_named(sections: tuple[Section, ...], *names: str) -> tuple[Section, ...]:
    wanted = set(names)
    return tuple(s for s in sections if s.name in wanted or s.canonical_id in wanted)


__all__ = [
    "INTERSTITIAL_ID",
    "PREAMBLE_ID",
    "Section",
    "build_sections",
    "section_at",
    "sections_named",
]
