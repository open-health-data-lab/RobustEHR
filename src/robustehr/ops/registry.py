"""Operator registry, including third-party plugins.

Third-party operators are namespaced and their resource digests fold into their
version exactly as built-in ones do, so a plugin author cannot silently change
another lab's results by editing a lexicon.
"""

from __future__ import annotations

import importlib.metadata

from robustehr.ops.base import Layer, Operator, OperatorMeta
from robustehr.resources import is_external, resource_sha256
from robustehr.types import Channel

_REGISTRY: dict[str, type[Operator]] = {}

ENTRY_POINT_GROUP = "robustehr.operators"


def register(cls: type[Operator]) -> type[Operator]:
    """Register an operator class. Ids must be namespaced and unique."""
    op_id = cls.id
    if "." not in op_id:
        raise ValueError(
            f"operator id {op_id!r} must be namespaced as '<channel>.<name>' so that "
            "third-party operators cannot collide with built-ins"
        )
    if op_id in _REGISTRY and _REGISTRY[op_id] is not cls:
        raise ValueError(f"duplicate operator id {op_id!r}")
    _REGISTRY[op_id] = cls
    return cls


def get(op_id: str) -> type[Operator]:
    if op_id not in _REGISTRY:
        raise KeyError(f"unknown operator {op_id!r}; known: {all_ids()}")
    return _REGISTRY[op_id]


def all_ids() -> tuple[str, ...]:
    """Sorted, never set-iteration order."""
    return tuple(sorted(_REGISTRY))


def all_operators() -> tuple[type[Operator], ...]:
    return tuple(_REGISTRY[op_id] for op_id in all_ids())


def clear() -> None:
    """Test helper. Not part of the public API."""
    _REGISTRY.clear()


def load_plugins() -> tuple[str, ...]:
    """Load third-party operators declared under the entry-point group."""
    loaded: list[str] = []
    for entry in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        register(entry.load())
        loaded.append(entry.name)
    return tuple(sorted(loaded))


#: What an unshippable resource contributes to a *committed* version string.
#: Eight characters, like the digest slices it stands in for.
_EXTERNAL_TOKEN = "external"


def resolved_version(meta: OperatorMeta, *, canonical: bool = False) -> str:
    """Operator version with its resource digests folded in.

    Swapping a lexicon changes this, which changes the seed material, which
    invalidates the affected selections. A resource edit is therefore a version
    bump rather than a silent change to previously reported results.

    `canonical=True` substitutes a fixed token for resources that cannot ship —
    the DrugBank-derived synonym map, the concept lockfiles. Their digest is a
    property of the machine that happened to run the export: present here,
    ``absent`` on a fresh clone, different again on a colleague's laptop. Baking
    one into a file that is committed and redistributed makes the artifact
    unreproducible, which is the opposite of what a lockfile is for.

    Runs keep the real digest. `canonical` is for the committed taxonomy only,
    and the resource is still named in that entry, so the dependency is visible
    rather than hidden behind a hash nobody else can reproduce.
    """
    if not meta.resources:
        return meta.version
    digest = "".join(
        _EXTERNAL_TOKEN if canonical and is_external(name) else resource_sha256(name)[:8]
        for name in sorted(meta.resources)
    )
    return f"{meta.version}+r{digest}"


#: The three corruption families a user selects by name, defined by the LEVEL an
#: operator acts on rather than by an enumerated list of ids.
#:
#: Derivation, not enumeration, is the point: a new operator joins its family by
#: declaring its `Layer`, and no registry edit is needed. A hard-coded list is
#: how `configuration.md`'s "we will add more corruption types later" turns into
#: an operator that exists, runs, and cannot be reached by the config that was
#: supposed to be its interface.
#:
#: `control` operators are deliberately in no family. They are the calibration
#: floor and ceiling, and a user asking for "all character corruptions" must not
#: silently receive the one whose job is to destroy the note.
FAMILIES: dict[str, frozenset[Layer]] = {
    "structural": frozenset({Layer.STRUCTURE, Layer.SECTION, Layer.SENTENCE}),
    "word": frozenset({Layer.WORD}),
    "character": frozenset({Layer.CHAR}),
}


def families() -> dict[str, tuple[str, ...]]:
    """``{family: operator ids}`` over everything currently registered."""
    out: dict[str, list[str]] = {name: [] for name in FAMILIES}
    for op_id, cls in sorted(_REGISTRY.items()):
        meta = cls.meta
        if meta.channel is Channel.CONTROL:
            continue
        for name, layers in FAMILIES.items():
            if meta.layer in layers:
                out[name].append(op_id)
    return {name: tuple(ids) for name, ids in out.items()}


def resolve_family(name: str) -> tuple[str, ...]:
    """Operator ids for one family name, or a clear error naming the choices."""
    found = families()
    if name not in found:
        raise KeyError(f"unknown corruption family {name!r}; known: {sorted(found)}")
    return found[name]


def register_builtins() -> None:
    # Deferred: `render` imports from this module, so a top-level import
    # would be circular.
    from robustehr.ops import (  # noqa: PLC0415
        control,
        discourse,
        input,
        lexical,
        render,
        semantic,
        semantic_llm,
    )

    for module in (render, input, lexical, discourse, control, semantic, semantic_llm):
        for cls in module.OPERATORS:
            register(cls)


__all__ = [
    "ENTRY_POINT_GROUP",
    "FAMILIES",
    "all_ids",
    "all_operators",
    "clear",
    "families",
    "get",
    "load_plugins",
    "register",
    "register_builtins",
    "resolve_family",
    "resolved_version",
]
