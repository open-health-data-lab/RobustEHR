"""Document structure: lines, wrap handling, de-identification, and the units
that every dose denominator is defined over.

This layer is hand-written pure Python rather than spaCy/pysbd/nltk, for three
reasons that are worth stating because the choice looks like reinvention:

1. **Reproducibility.** A downloaded model is the largest byte-reproducibility
   risk in a cross-institution pipeline: versions drift, downloads change, and
   nobody can diff a 400 MB blob.
2. **Correctness on this text.** Generic segmenters are demonstrably wrong on
   clinical notes — ``___.`` inside a lab line, blank lines mid-sentence,
   ``0157:H7``, and de-identified list numbers all break them.
3. **Accountability.** Segmentation *defines* the denominator of every dose the
   package reports. It has to be inspectable and versioned, and every output
   record carries ``SEGMENTER_VERSION`` so a reader knows which one applied.
"""

from __future__ import annotations

from robustehr.segment.blocks import (
    AlignedBlock,
    BlockStyle,
    ListBlock,
    ListItem,
    ListStyle,
    detect_aligned_blocks,
    detect_lists,
    list_style_counts,
)
from robustehr.segment.breaks import Break, break_counts, detect_breaks
from robustehr.segment.deid import (
    DeidIndex,
    DeidScheme,
    Placeholder,
    detect_scheme,
    index_deid,
)
from robustehr.segment.headers import (
    SECTION_KINDS,
    Header,
    HeaderConfidence,
    HeaderGrammar,
    HeaderKind,
    detect_headers,
)
from robustehr.segment.lines import Line, LineIndex, split_lines
from robustehr.segment.patterns import SEGMENTER_VERSION
from robustehr.segment.sections import PREAMBLE_ID, Section, build_sections, section_at
from robustehr.segment.tokens import Token, TokenIndex, TokenKind, tokenize
from robustehr.segment.wrap import ReflowView, build_reflow_view, wrap_width, wraps_into_next

__all__ = [
    "PREAMBLE_ID",
    "SECTION_KINDS",
    "SEGMENTER_VERSION",
    "AlignedBlock",
    "BlockStyle",
    "Break",
    "DeidIndex",
    "DeidScheme",
    "Header",
    "HeaderConfidence",
    "HeaderGrammar",
    "HeaderKind",
    "Line",
    "LineIndex",
    "ListBlock",
    "ListItem",
    "ListStyle",
    "Placeholder",
    "ReflowView",
    "Section",
    "Token",
    "TokenIndex",
    "TokenKind",
    "break_counts",
    "build_reflow_view",
    "build_sections",
    "detect_aligned_blocks",
    "detect_breaks",
    "detect_headers",
    "detect_lists",
    "detect_scheme",
    "index_deid",
    "list_style_counts",
    "section_at",
    "split_lines",
    "tokenize",
    "wrap_width",
    "wraps_into_next",
]
