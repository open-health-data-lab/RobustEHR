"""The taxonomy as a single, non-drifting source of truth.

The taxonomy has to exist in two forms. Operators need it as typed Python, so
that an operator cannot be registered without declaring its unit, contract and
targets. Reviewers, clinicians and the paper's methods table need it as a flat
document they can read and diff without opening the source.

Keeping both by hand guarantees they diverge. So the Python declarations are the
source, ``taxonomy.yaml`` is *generated* from them and committed like a
lockfile, and a test asserts the file on disk matches what the code would
produce. The reviewable artifact stays reviewable, and it cannot silently
disagree with what actually ran.
"""

from __future__ import annotations

from typing import Any

import yaml

from robustehr.ops import all_operators, resolved_version
from robustehr.resources import is_external
from robustehr.version import SCHEMA_VERSION

TAXONOMY_FILE = "taxonomy.yaml"

_HEADER = """\
# RobustEHR operator taxonomy — GENERATED, DO NOT EDIT BY HAND.
#
# Regenerate with:  robustehr taxonomy --yaml > src/robustehr/resources/taxonomy.yaml
#
# The Python operator declarations are the source of truth; this file is
# committed like a lockfile so the taxonomy stays reviewable and diffable
# without opening the source, and a test asserts the two agree.
#
# Column meanings:
#   level        the operator's eligible unit — which *is* its dose denominator
#   channel      the failure mode it simulates
#   contract     the reference promise, and how that promise is discharged
#   canonicalizer  the projection proving an INVARIANT contract, checked in CI
#   targets      protection classes the operator is permitted to edit
#   resources    hashed lexicons folded into the operator's version
#   external_resources  locally-built, unshippable inputs. Named, not hashed:
#                their digest is a property of the machine that built them, so
#                the committed version carries `external` in their place
"""


def operator_entry(op_cls: Any) -> dict[str, Any]:
    meta = op_cls.meta
    entry: dict[str, Any] = {
        "id": meta.id,
        "version": resolved_version(meta, canonical=True),
        "level": meta.dose.unit_kind.value,
        "channel": meta.channel.value,
        "contract": meta.contract.value,
        "dose_kind": meta.dose.dose_kind,
        "denominator": meta.dose.denominator_doc,
        "sub_unit_policy": meta.dose.sub_unit_policy.value,
        "targets": sorted(cls.value for cls in meta.targets),
        "resources": list(meta.resources),
        "simulates": meta.simulates,
    }
    external = sorted(name for name in meta.resources if is_external(name))
    if external:
        # Named rather than hashed. These are built locally from licensed
        # sources and never packaged, so their digest describes one machine.
        # A reader who wants to reproduce the run version needs to know the
        # dependency exists; a hash they cannot recompute tells them nothing.
        entry["external_resources"] = external
    if meta.canonicalizer:
        entry["canonicalizer"] = meta.canonicalizer
    if meta.modes:
        entry["modes"] = list(meta.modes)
    return entry


def build() -> dict[str, Any]:
    """The taxonomy as plain data, in a stable order."""
    return {
        "schema_version": SCHEMA_VERSION,
        "operators": [operator_entry(cls) for cls in all_operators()],
    }


def to_yaml() -> str:
    body = yaml.safe_dump(build(), sort_keys=False, width=88, allow_unicode=True)
    return _HEADER + "\n" + body


def summary_rows() -> list[dict[str, str]]:
    """One row per operator, for ``robustehr taxonomy --list`` and the paper."""
    return [
        {
            "id": entry["id"],
            "level": entry["level"],
            "channel": entry["channel"],
            "contract": entry["contract"],
            "denominator": entry["denominator"],
        }
        for entry in build()["operators"]
    ]


__all__ = ["TAXONOMY_FILE", "build", "operator_entry", "summary_rows", "to_yaml"]
