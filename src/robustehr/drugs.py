"""Medication naming: is this a generic name, a brand name, or neither?

The identification half of `lexical.medication_rename`, and the answer to the
question `semantic_categories.yaml` cannot answer on its own. The `medication`
category is TUI-based (T121/T200/T195), and a brand name carrying T121 is
indistinguishable from its generic — the terminology knows *that* `Lasix` is a
drug, not that it is the *commercial* name for one.

Three-way by design::

    GENERIC      furosemide, metoprolol   — in the generic dictionary only
    COMMERCIAL   Lasix, Lopressor         — in the brand dictionary only
    UNKNOWN      insulin, Tylenol, iron   — in neither, or in both

``UNKNOWN`` is a real answer and not a failure. A surface in *both* dictionaries
(`iron`, `manganese`, `valerian` are somebody's brand and somebody's generic)
cannot be classified from the surface, and a surface in neither is simply not in
this source. Forcing a guess in either case would let the operator substitute
the wrong drug, which is the one thing it must never do.

**The map does not ship.** It is derived from the DrugBank-sourced CSVs in
`data/drugs/` by ``validation/pipeline/scripts/build_drug_synonyms.py``, following the same rule as
the concept lockfiles: identifiers and hashes travel, licensed strings do not.
When it has not been built, :func:`load_synonyms` returns an empty map, every
mention classifies as ``UNKNOWN``, and `lexical.medication_rename` reports zero
eligible units — the same "declared but inapplicable" state the LLM operators
occupy with no model named, rather than a crash or a silent no-op.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from robustehr.resources import register_external

#: Not a packaged file. Declared under this name so it reaches ``op_version``
#: through the external-digest hook; see :mod:`robustehr.resources`.
DRUGS_RESOURCE = "drug_synonyms.json"

#: Where `validation/pipeline/scripts/build_drug_synonyms.py` writes it. Under `data/`, which is
#: gitignored, because the content is derived from a licensed source.
SYNONYMS_PATH = Path("data") / "drugs" / DRUGS_RESOURCE


class Representation(StrEnum):
    """How a medication mention is currently written."""

    GENERIC = "generic"
    COMMERCIAL = "commercial"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DrugSynonyms:
    """Generic-brand equivalences, both directions, keyed casefolded."""

    to_brand: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Lowercased generic -> its brand names, sorted."""
    to_generic: dict[str, str] = field(default_factory=dict)
    """Lowercased brand -> its single generic. One, never several: a brand
    mapping to more than one generic is dropped at build time rather than
    resolved by guessing."""
    sha256: str = "absent"

    def __bool__(self) -> bool:
        return bool(self.to_brand)

    def classify(self, surface: str) -> Representation:
        """Generic, commercial or unknown — never a forced choice."""
        key = surface.lower()
        in_generic = key in self.to_brand
        in_brand = key in self.to_generic
        if in_generic and not in_brand:
            return Representation.GENERIC
        if in_brand and not in_generic:
            return Representation.COMMERCIAL
        return Representation.UNKNOWN

    def alternatives(self, surface: str) -> tuple[str, ...]:
        """Equivalent names for the other convention, in display form.

        Empty when the surface is unclassifiable, which is what makes the
        operator's eligibility and its proposal agree: a mention with no
        alternatives is never selected, so a dose is never silently short.
        """
        key = surface.lower()
        match self.classify(surface):
            case Representation.GENERIC:
                return self.to_brand.get(key, ())
            case Representation.COMMERCIAL:
                generic = self.to_generic.get(key)
                return (generic,) if generic else ()
            case _:
                return ()

    def counts(self) -> dict[str, int]:
        return {
            "generics": len(self.to_brand),
            "brands": len(self.to_generic),
            "pairs": sum(len(v) for v in self.to_brand.values()),
        }


def _path() -> Path:
    return SYNONYMS_PATH


@lru_cache(maxsize=1)
def load_synonyms() -> DrugSynonyms:
    """The equivalence map, or an empty one when it has not been built."""
    path = _path()
    if not path.exists():
        return DrugSynonyms()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return DrugSynonyms(
        to_brand={k: tuple(v) for k, v in raw["to_brand"].items()},
        to_generic=dict(raw["to_generic"]),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def synonyms_digest() -> str:
    """``sha256`` of the built map, or ``"absent"``. Folded into ``op_version``."""
    return load_synonyms().sha256


register_external(DRUGS_RESOURCE, synonyms_digest)


__all__ = [
    "DRUGS_RESOURCE",
    "SYNONYMS_PATH",
    "DrugSynonyms",
    "Representation",
    "load_synonyms",
    "synonyms_digest",
]
