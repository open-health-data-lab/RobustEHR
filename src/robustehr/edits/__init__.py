"""Edit proposal, conflict resolution, application and alignment."""

from __future__ import annotations

from robustehr.edits.align import Alignment, AlignmentBuilder
from robustehr.edits.apply import (
    ApplyResult,
    RejectedEdit,
    RejectionReason,
    apply_edits,
    levenshtein,
)

__all__ = [
    "Alignment",
    "AlignmentBuilder",
    "ApplyResult",
    "RejectedEdit",
    "RejectionReason",
    "apply_edits",
    "levenshtein",
]
