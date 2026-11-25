"""Protected spans and eligibility filtering."""

from __future__ import annotations

from robustehr.protect.registry import (
    ProtectedSpan,
    ProtectionIndex,
    Strength,
    build_index,
    protect_document,
)

__all__ = [
    "ProtectedSpan",
    "ProtectionIndex",
    "Strength",
    "build_index",
    "protect_document",
]
