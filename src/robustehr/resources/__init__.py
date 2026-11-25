"""Packaged, content-hashed resources.

Every resource file's SHA-256 is folded into the ``op_version`` of any operator
that reads it, and recorded in the run manifest. Swapping a header lexicon or an
abbreviation inventory is therefore a version bump that invalidates the affected
seeds, not a silent change to previously reported results.
"""

from __future__ import annotations

import hashlib
from functools import cache
from importlib import resources
from typing import Any

import yaml

#: Digest providers for resources that **cannot ship**.
#:
#: Some operators depend on data derived from a licensed source — the concept
#: lockfiles, and the DrugBank-derived generic/brand map. Those are built
#: locally into `data/` and never packaged, but they still have to reach
#: ``op_version``, or swapping one would silently change previously reported
#: results. A module owning such a resource registers a callable here at import
#: and :func:`resource_sha256` consults it before touching the package tree.
#:
#: The provider returns ``"absent"`` when the artifact has not been built. That
#: is deliberate and not an error: an operator whose resource is missing reports
#: zero eligible units, exactly as the LLM operators do with no model named, and
#: the artifact records *which* state produced it.
_EXTERNAL: dict[str, Any] = {}


def register_external(name: str, digest: Any) -> None:
    """Declare a locally-built resource and how to hash it."""
    _EXTERNAL[name] = digest


def is_external(name: str) -> bool:
    """Is this resource one of the locally-built, unshippable ones?

    Callers building a *committed* artifact need to know, because an external
    digest describes the machine that ran the export and nothing else.
    """
    return name in _EXTERNAL


def resource_bytes(name: str) -> bytes:
    return (resources.files(__package__) / name).read_bytes()


@cache
def resource_sha256(name: str) -> str:
    """Content hash, used to version any operator that depends on this file."""
    if name in _EXTERNAL:
        return _EXTERNAL[name]()
    return hashlib.sha256(resource_bytes(name)).hexdigest()


@cache
def optional_resource_sha256(name: str) -> str:
    """Content hash, or ``"absent"`` for a resource that does not ship.

    For the run manifest, where every targeting resource is named whether or
    not it exists: a corpus built before a resource existed was built under a
    different target, and ``"absent"`` is what records that.
    """
    try:
        return resource_sha256(name)
    except FileNotFoundError:
        return "absent"


@cache
def load_yaml(name: str) -> Any:
    """Parse a packaged YAML resource.

    Uses ``safe_load``: resources are data, and a loader that can construct
    arbitrary Python objects turns a data file into an execution vector.
    """
    return yaml.safe_load(resource_bytes(name).decode("utf-8"))


def resource_digest_map(*names: str) -> dict[str, str]:
    """``{name: sha256}`` for the manifest and for operator versioning."""
    return {name: resource_sha256(name) for name in sorted(names)}


__all__ = [
    "is_external",
    "load_yaml",
    "optional_resource_sha256",
    "register_external",
    "resource_bytes",
    "resource_digest_map",
    "resource_sha256",
]
