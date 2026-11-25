"""The immutable document, and every offset-anchored view over it.

One governing invariant, inherited from :mod:`robustehr.types`:

> The raw string is the only text. Every layer is an offset-anchored view into
> it, and no layer stores a copy of a substring.

That is what makes the propose-then-apply engine work — any unit at any
granularity is addressable as ``doc.text[span.start:span.end]``, so every
operator emits edits against one coordinate system.

A ``Document`` is built once per note and reused across every operator and
severity cell in a run. That is not just an optimisation: rebuilding it per cell
would make segmentation the dominant cost of a sweep, and it would also invite
the layers to drift apart between cells.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field

from robustehr.resources import resource_digest_map
from robustehr.rng import sha256_text
from robustehr.segment.blocks import (
    AlignedBlock,
    ListBlock,
    detect_aligned_blocks,
    detect_lists,
)
from robustehr.segment.breaks import Break, detect_breaks
from robustehr.segment.deid import DeidIndex, DeidScheme, index_deid
from robustehr.segment.headers import (
    HEADERS_RESOURCE,
    SECTION_KINDS,
    Header,
    HeaderKind,
    detect_headers,
)
from robustehr.segment.lines import LineIndex, split_lines
from robustehr.segment.patterns import SEGMENTER_VERSION
from robustehr.segment.sections import Section, build_sections, section_at
from robustehr.segment.sentences import SENTENCES_RESOURCE, SentenceIndex, split_sentences
from robustehr.segment.tokens import TokenIndex, tokenize
from robustehr.segment.wrap import ReflowView, build_reflow_view
from robustehr.types import Span


class UnicodeFormError(ValueError):
    """Raised when input text is not in NFC form.

    Deliberately an error rather than a silent normalization. Normalizing input
    would itself be a perturbation — it changes offsets and character counts —
    applied before any operator ran and recorded in no dose record. The caller
    has to decide, so that the decision is visible.
    """


@dataclass(frozen=True, slots=True)
class Document:
    """A clinical note plus every structural layer derived from it."""

    uid: str
    text: str
    sha256: str
    deid: DeidIndex
    lines: LineIndex
    view: ReflowView
    tokens: TokenIndex
    headers: tuple[Header, ...]
    sections: tuple[Section, ...]
    lists: tuple[ListBlock, ...]
    aligned: tuple[AlignedBlock, ...]
    breaks: tuple[Break, ...]
    sentences: SentenceIndex
    segmenter_version: str
    resource_digests: Mapping[str, str]
    meta: Mapping[str, str] = field(default_factory=dict)

    # -- construction ------------------------------------------------------

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        uid: str,
        deid_scheme: DeidScheme | None = None,
        section_kinds: frozenset[HeaderKind] = SECTION_KINDS,
        meta: Mapping[str, str] | None = None,
    ) -> Document:
        """Build every layer from raw note text.

        ``deid_scheme`` may be pinned when the corpus convention is known;
        otherwise it is detected from the document.
        """
        if text and unicodedata.normalize("NFC", text) != text:
            raise UnicodeFormError(
                f"{uid}: text is not NFC-normalized. RobustEHR does not normalize input, "
                "because doing so would silently perturb offsets and character counts "
                "before any operator ran. Normalize upstream and record that you did."
            )

        deid = index_deid(text, deid_scheme)
        lines = split_lines(text)
        tokens = tokenize(text, deid)
        headers = detect_headers(text, lines)
        section_headers = tuple(h for h in headers if h.kind in section_kinds)
        lists = detect_lists(text, lines)
        aligned = detect_aligned_blocks(text, lines)

        return cls(
            uid=uid,
            text=text,
            sha256=sha256_text(text),
            deid=deid,
            lines=lines,
            view=build_reflow_view(text, lines),
            tokens=tokens,
            headers=headers,
            sections=build_sections(text, section_headers),
            lists=lists,
            aligned=aligned,
            breaks=detect_breaks(text, lines, lists=lists, aligned=aligned),
            sentences=split_sentences(
                text, lines, tokens, headers=headers, lists=lists, aligned=aligned
            ),
            segmenter_version=SEGMENTER_VERSION,
            resource_digests=resource_digest_map(HEADERS_RESOURCE, SENTENCES_RESOURCE),
            meta=dict(meta or {}),
        )

    # -- queries -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.text)

    def surface(self, span: Span) -> str:
        return span.surface(self.text)

    def section_at(self, index: int) -> Section | None:
        return section_at(self.sections, index)

    def sentence_at(self, index: int):  # type: ignore[no-untyped-def]
        return self.sentences.at_offset(index)

    def section_headers(self) -> tuple[Header, ...]:
        return tuple(h for h in self.headers if h.kind in SECTION_KINDS)

    @property
    def is_empty(self) -> bool:
        return not self.text

    # -- provenance --------------------------------------------------------

    def provenance(self) -> dict[str, str]:
        """Everything a dose record needs to identify how this was segmented.

        A segmenter change or a resource swap is a breaking change to every
        previously reported denominator, so both are carried explicitly rather
        than assumed stable.
        """
        return {
            "note_uid": self.uid,
            "note_sha256": self.sha256,
            "segmenter_version": self.segmenter_version,
            "deid_scheme": self.deid.scheme.value,
            **{
                f"resource:{name}": digest for name, digest in sorted(self.resource_digests.items())
            },
        }

    def unit_counts(self) -> dict[str, int]:
        """Raw denominators, before any scope or protection filter.

        Reported alongside eligibility so a reader can see how much of a
        document each operator was even able to consider.
        """
        return {
            "chars": len(self.text),
            "lines": len(self.lines),
            "tokens": len(self.tokens),
            "content_tokens": len(self.tokens.content()),
            "sentences": len(self.sentences),
            "prose_sentences": len(self.sentences.prose()),
            "headers": len(self.headers),
            "section_headers": len(self.section_headers()),
            "sections": len(self.sections),
            "list_blocks": len(self.lists),
            "list_items": sum(len(b.items) for b in self.lists),
            "aligned_blocks": len(self.aligned),
            "aligned_lines": sum(len(b.lines) for b in self.aligned),
            "breaks": len(self.breaks),
            "deid_placeholders": self.deid.count,
            "divider_rules": len(self.deid.dividers),
        }


__all__ = ["Document", "UnicodeFormError"]
