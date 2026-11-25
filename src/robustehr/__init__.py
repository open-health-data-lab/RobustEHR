"""RobustEHR — deterministic, dose-calibrated perturbation of clinical free text.

The package is corpus-agnostic and label-free by default. Selecting one or more
phenotypes configures whether entities related to them are *protected* or
*targeted*; that needs concept sets, never gold labels.
"""

from __future__ import annotations

from robustehr.document import Document, UnicodeFormError
from robustehr.types import (
    Anchor,
    Channel,
    Contract,
    CountSeverity,
    Edit,
    PhenotypeScope,
    ProtectionClass,
    RateSeverity,
    ReflowPolicy,
    Span,
    SubUnitPolicy,
    TargetMode,
    Unit,
    UnitKind,
)
from robustehr.version import SCHEMA_VERSION, SPEC_VERSION, __version__

__all__ = [
    "SCHEMA_VERSION",
    "SPEC_VERSION",
    "Anchor",
    "Channel",
    "Contract",
    "CountSeverity",
    "Document",
    "Edit",
    "PhenotypeScope",
    "ProtectionClass",
    "RateSeverity",
    "ReflowPolicy",
    "Span",
    "SubUnitPolicy",
    "TargetMode",
    "UnicodeFormError",
    "Unit",
    "UnitKind",
    "__version__",
]
