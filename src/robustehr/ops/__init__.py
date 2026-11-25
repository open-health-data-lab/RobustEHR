"""Operators, the registry, and the protocol they implement."""

from __future__ import annotations

from robustehr.ops.base import (
    LAYER_PRIORITY,
    Layer,
    OpContext,
    Operator,
    OperatorMeta,
    Scope,
    make_edit,
)
from robustehr.ops.registry import (
    all_ids,
    all_operators,
    get,
    load_plugins,
    register,
    register_builtins,
    resolved_version,
)

register_builtins()

__all__ = [
    "LAYER_PRIORITY",
    "Layer",
    "OpContext",
    "Operator",
    "OperatorMeta",
    "Scope",
    "all_ids",
    "all_operators",
    "get",
    "load_plugins",
    "make_edit",
    "register",
    "register_builtins",
    "resolved_version",
]
