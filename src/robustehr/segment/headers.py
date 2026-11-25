"""Section-header detection.

Clinical notes use two header grammars, and both have to be handled:

* **standalone** — the whole line is a label, e.g. ``Past Medical History:``
* **inline** — a label and its value share a line, e.g. ``Service: MEDICINE``

The hard part is not finding lines that end in a colon; it is *not* finding the
ones that only look like headers. The development corpus contains 2,689 distinct
header-like strings, 61.3% of them singletons, and 1,374 occurrences of ordinary
prose that happens to end in a colon::

    In the ED, initial vitals were:
    Emergency Department for any of the following:
    The following changes were made to your medications:

A naive ``^[A-Z].*:$`` rule collects all of these and roughly doubles the
denominator — which is why "delete 10% of headers" is not a reproducible
instruction until "header" is pinned to a published set. That set is
``resources/headers.yaml``, and its content hash goes into every dose record.

Each detection carries a confidence tier so that operators can choose their own
risk posture: header deletion at high dose can safely use heuristic matches,
while an operator that *renames* a header to a same-concept synonym should
require a lexicon hit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache
from typing import Any

from robustehr.resources import load_yaml, resource_sha256
from robustehr.segment.lines import Line, LineIndex
from robustehr.segment.patterns import LETTERS, TERMINATORS, UPPERS
from robustehr.segment.tokens import ascii_lower
from robustehr.types import Span

HEADERS_RESOURCE = "headers.yaml"

#: A label longer than this many characters is prose, whatever else it looks like.
_MAX_LABEL_CHARS = 60

_NON_ALNUM_SPACE = re.compile(r"[^a-z0-9 ]+")
_MULTI_SPACE = re.compile(r" {2,}")


class HeaderGrammar(StrEnum):
    STANDALONE = "standalone"
    """The whole line is a label: ``Past Medical History:``"""
    INLINE = "inline"
    """Label and value share a line: ``Service: MEDICINE``"""
    MARKDOWN = "markdown"
    """A hash heading: ``## Assessment``. Used by templated and modern exports."""


_MD_HEADING = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<title>[^ \t].*?)[ \t]*$")


def uses_markdown_headings(text: str) -> bool:
    """Decide, per document, whether ``#`` opens a heading or a problem-list item.

    This is genuinely ambiguous and the two readings are both common: MIMIC-IV
    problem lists are written ``# Hypertension`` (70% of notes, ~7 per note),
    while templated exports use ``# Title`` / ``## Section``.

    The disambiguator is document-level and deterministic: a note containing any
    ``##``-or-deeper heading is being written in markdown, so its single-hash
    lines are headings too. A note with only single hashes is using them as
    bullets, which is the clinical convention.
    """
    for line in text.split("\n"):
        stripped = line.lstrip(" \t")
        match = _MD_HEADING.match(stripped)
        if match and len(match.group("hashes")) >= 2:
            return True
    return False


class HeaderConfidence(StrEnum):
    LEXICON = "lexicon"
    """The label matched a published alias. Safe for renaming and canonical work."""
    STRONG_HEURISTIC = "strong_heuristic"
    """Short, capitalised, no prose markers. Safe to delete or restyle."""
    WEAK_HEURISTIC = "weak_heuristic"
    """Plausible but unverified. Excluded from denominators by default."""


class HeaderKind(StrEnum):
    """What a header-shaped line actually is.

    The distinction is a denominator question. ``Disp:``, ``Refills:`` and
    ``Sig:`` have header grammar and appear in up to a quarter of notes, but
    they are boilerplate inside a medication list rather than note structure.
    Counting them as section headers roughly doubles the denominator and makes
    "delete 30% of headers" mean something different in every note.
    """

    SECTION = "section"
    METADATA = "metadata"
    SUBSECTION = "subsection"
    BOILERPLATE = "boilerplate"
    REPORT_FIELD = "report_field"
    """Structures an embedded radiology or microbiology report, not the note."""
    UNKNOWN = "unknown"
    """Heuristic match with no lexicon entry — could be any of the above."""


def normalize_label(label: str) -> str:
    """Fold a surface label to its lookup key.

    Case- and punctuation-insensitive, so the corpus's rampant case variation
    (``Transitional Issues`` / ``TRANSITIONAL ISSUES`` / ``Transitional
    issues``) collapses without needing an alias per casing.
    """
    folded = _NON_ALNUM_SPACE.sub(" ", ascii_lower(label))
    return _MULTI_SPACE.sub(" ", folded).strip()


@dataclass(frozen=True, slots=True)
class HeaderLexicon:
    alias_to_id: dict[str, str]
    depth_by_id: dict[str, int]
    kind_by_id: dict[str, HeaderKind]
    surface_by_id: dict[str, tuple[str, ...]]
    """Canonical id -> its aliases in *display* form, in file order.

    ``alias_to_id`` is keyed by :func:`normalize_label`, which folds case and
    punctuation away — right for recognition, useless for rewriting. A rename
    operator has to emit ``Clinical Impression and Plan``, not ``clinical
    impression and plan``, so the surface strings are kept alongside.
    """
    prose_markers: tuple[str, ...]
    max_label_words: int
    sha256: str

    def lookup(self, label: str) -> str | None:
        return self.alias_to_id.get(normalize_label(label))

    def aliases_for(
        self, canonical_id: str | None, *, excluding: str | None = None
    ) -> tuple[str, ...]:
        """Display-form aliases for a canonical section, minus one surface.

        ``excluding`` is the label already in the document: renaming a header to
        the string it already has is a no-op that would still be counted as an
        applied edit, inflating the realized dose with edits that changed
        nothing. Compared after :func:`normalize_label`, so ``PAST MEDICAL
        HISTORY`` and ``Past Medical History`` are recognised as the same name.
        """
        aliases = self.surface_by_id.get(canonical_id or "", ())
        if excluding is None:
            return aliases
        key = normalize_label(excluding)
        return tuple(a for a in aliases if normalize_label(a) != key)

    def depth(self, canonical_id: str | None) -> int:
        return self.depth_by_id.get(canonical_id or "", 0)

    def kind(self, canonical_id: str | None) -> HeaderKind:
        if canonical_id is None:
            return HeaderKind.UNKNOWN
        return self.kind_by_id.get(canonical_id, HeaderKind.SECTION)

    @property
    def canonical_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.alias_to_id.values())))


@lru_cache(maxsize=1)
def load_lexicon() -> HeaderLexicon:
    raw: dict[str, Any] = load_yaml(HEADERS_RESOURCE)
    alias_to_id: dict[str, str] = {}
    depth_by_id: dict[str, int] = {}
    kind_by_id: dict[str, HeaderKind] = {}
    surface_by_id: dict[str, tuple[str, ...]] = {}
    for canonical_id, entry in raw["canonical"].items():
        depth = int(entry.get("depth", 0))
        depth_by_id[canonical_id] = depth
        declared = entry.get("kind")
        if declared is not None:
            kind_by_id[canonical_id] = HeaderKind(declared)
        else:
            kind_by_id[canonical_id] = HeaderKind.SUBSECTION if depth else HeaderKind.SECTION
        surfaces: list[str] = []
        for alias in entry["aliases"]:
            key = normalize_label(alias)
            # First definition wins, so an alias shared between two canonical
            # ids resolves deterministically rather than by dict ordering.
            alias_to_id.setdefault(key, canonical_id)
            # Deduplicated on the normalized key so that two aliases differing
            # only in case do not give one spelling twice the weight in a
            # rename draw.
            if all(normalize_label(s) != key for s in surfaces):
                surfaces.append(alias)
        alias_to_id.setdefault(normalize_label(canonical_id.replace("_", " ")), canonical_id)
        surface_by_id[canonical_id] = tuple(surfaces)
    return HeaderLexicon(
        alias_to_id=alias_to_id,
        depth_by_id=depth_by_id,
        kind_by_id=kind_by_id,
        surface_by_id=surface_by_id,
        prose_markers=tuple(raw["prose_markers"]),
        max_label_words=int(raw["max_label_words"]),
        sha256=resource_sha256(HEADERS_RESOURCE),
    )


@dataclass(frozen=True, slots=True)
class Header:
    line_idx: int
    label: Span
    """The label text, excluding any marker."""
    marker: Span
    """The syntactic marker: the trailing colon, or the leading hashes.

    It sits *after* the label in the colon grammars and *before* it in markdown,
    which is why :attr:`span` takes the extent of both rather than assuming an
    order.
    """
    value: Span | None
    """The inline value, or ``None`` for standalone and markdown headers."""
    grammar: HeaderGrammar
    confidence: HeaderConfidence
    kind: HeaderKind
    canonical_id: str | None
    raw_name: str
    depth: int

    @property
    def span(self) -> Span:
        """Marker plus label — what a deletion operator removes."""
        return Span(
            min(self.label.start, self.marker.start),
            max(self.label.end, self.marker.end),
        )

    @property
    def is_canonical(self) -> bool:
        return self.canonical_id is not None


#: Characters that mean the line is a delimited row rather than a label. A
#: pipe-separated title such as ``DISCHARGE SUMMARY | Patient: X | MRN: Y``
#: otherwise yields the spurious header "DISCHARGE SUMMARY | Patient".
_DELIMITERS = frozenset("|\t")


def _looks_like_prose(label: str, lexicon: HeaderLexicon) -> bool:
    if any(ch in _DELIMITERS for ch in label):
        return True
    padded = f" {ascii_lower(label)} "
    if any(marker in padded for marker in lexicon.prose_markers):
        return True
    if len(label.split()) > lexicon.max_label_words:
        return True
    return any(ch in TERMINATORS for ch in label)


def _confidence(
    label: str, canonical_id: str | None, lexicon: HeaderLexicon
) -> HeaderConfidence | None:
    if canonical_id is not None:
        return HeaderConfidence.LEXICON
    if not label or len(label) > _MAX_LABEL_CHARS:
        return None
    if label[0] not in UPPERS:
        return None
    if _looks_like_prose(label, lexicon):
        return None
    words = [w for w in label.split() if any(ch in LETTERS for ch in w)]
    if not words:
        return None
    initial_caps = all(w[0] in UPPERS for w in words)
    return HeaderConfidence.STRONG_HEURISTIC if initial_caps else HeaderConfidence.WEAK_HEURISTIC


#: The default denominator for header operators: real note structure, with
#: pharmacy boilerplate and exam subsections excluded.
SECTION_KINDS = frozenset({HeaderKind.SECTION, HeaderKind.METADATA})


def _markdown_header(text: str, line: Line, lexicon: HeaderLexicon) -> Header | None:
    """A hash heading, e.g. ``## Assessment``."""
    md = _MD_HEADING.match(line.content_text(text))
    if md is None:
        return None
    title = md.group("title")
    canonical_id = lexicon.lookup(title)
    # A hash heading is structural by syntax even when the title is not a
    # recognisable label, so accept it rather than dropping real structure.
    confidence = _confidence(title, canonical_id, lexicon) or HeaderConfidence.STRONG_HEURISTIC
    # And unlike a colon label — which may be prose, boilerplate or a report
    # field — it is unambiguously a *section*. Leaving it UNKNOWN would exclude
    # "## Subjective" from the section denominator of every markdown-style note.
    kind = lexicon.kind(canonical_id) if canonical_id is not None else HeaderKind.SECTION
    title_start = line.content.start + md.start("title")
    return Header(
        line_idx=line.idx,
        label=Span(title_start, title_start + len(title)),
        marker=Span(line.content.start, line.content.start + len(md.group("hashes"))),
        value=None,
        grammar=HeaderGrammar.MARKDOWN,
        confidence=confidence,
        kind=kind,
        canonical_id=canonical_id,
        raw_name=title,
        depth=len(md.group("hashes")) - 1,
    )


def _colon_header(text: str, line: Line, lexicon: HeaderLexicon) -> Header | None:
    """A ``Label:`` header, standalone or with an inline value."""
    content = line.content_text(text)
    colon_at = content.find(":")
    if colon_at <= 0:
        return None
    label = content[:colon_at].rstrip()
    if not label:
        return None
    canonical_id = lexicon.lookup(label)
    confidence = _confidence(label, canonical_id, lexicon)
    if confidence is None:
        return None

    label_start = line.content.start
    colon_start = label_start + colon_at
    remainder = content[colon_at + 1 :]
    value_text = remainder.strip()
    if value_text:
        value_offset = colon_start + 1 + (len(remainder) - len(remainder.lstrip()))
        value: Span | None = Span(value_offset, value_offset + len(value_text))
        grammar = HeaderGrammar.INLINE
    else:
        value = None
        grammar = HeaderGrammar.STANDALONE

    return Header(
        line_idx=line.idx,
        label=Span(label_start, label_start + len(label)),
        marker=Span(colon_start, colon_start + 1),
        value=value,
        grammar=grammar,
        confidence=confidence,
        kind=lexicon.kind(canonical_id),
        canonical_id=canonical_id,
        raw_name=label,
        depth=lexicon.depth(canonical_id),
    )


_CONFIDENCE_ORDER = (
    HeaderConfidence.LEXICON,
    HeaderConfidence.STRONG_HEURISTIC,
    HeaderConfidence.WEAK_HEURISTIC,
)


def detect_headers(
    text: str,
    lines: LineIndex,
    *,
    min_confidence: HeaderConfidence | None = None,
    kinds: frozenset[HeaderKind] | None = None,
) -> tuple[Header, ...]:
    """Find headers on each line, rejecting prose that merely ends in a colon.

    ``min_confidence`` filters the result; passing ``STRONG_HEURISTIC`` excludes
    the unverified tail. ``kinds`` filters by what the header actually is —
    passing :data:`SECTION_KINDS` gives the section-structure denominator.
    """
    lexicon = load_lexicon()
    cutoff = (
        _CONFIDENCE_ORDER.index(min_confidence)
        if min_confidence is not None
        else len(_CONFIDENCE_ORDER)
    )
    markdown = uses_markdown_headings(text)

    found: list[Header] = []
    for line in lines.lines:
        if line.is_blank:
            continue
        header = (_markdown_header(text, line, lexicon) if markdown else None) or _colon_header(
            text, line, lexicon
        )
        if header is None:
            continue
        if _CONFIDENCE_ORDER.index(header.confidence) > cutoff:
            continue
        if kinds is not None and header.kind not in kinds:
            continue
        found.append(header)
    return _normalize_markdown_depth(tuple(found))


def _normalize_markdown_depth(headers: tuple[Header, ...]) -> tuple[Header, ...]:
    """Make markdown depth relative to the document's shallowest heading.

    A note whose top-level sections are written ``## Section`` would otherwise
    have every section at depth 1 and no depth-0 section at all, leaving the
    "next header at the same or shallower depth" rule with nothing to close
    against and the document untiled by top-level sections.
    """
    levels = [h.depth for h in headers if h.grammar is HeaderGrammar.MARKDOWN]
    if not levels or min(levels) == 0:
        return headers
    shift = min(levels)
    return tuple(
        replace(h, depth=h.depth - shift) if h.grammar is HeaderGrammar.MARKDOWN else h
        for h in headers
    )


__all__ = [
    "HEADERS_RESOURCE",
    "SECTION_KINDS",
    "Header",
    "HeaderConfidence",
    "HeaderGrammar",
    "HeaderKind",
    "HeaderLexicon",
    "detect_headers",
    "load_lexicon",
    "normalize_label",
]
