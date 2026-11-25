"""Clinical shorthand expanded to long form, scoped to a structural slot.

Stage 3a/3b of the concept-matching pipeline, and the component the V0 gate
redirected the whole stage toward. **44.9% of abbreviation-shaped gold spans have
no UMLS candidate carrying the right category**, and no disambiguation policy
reaches them, because the candidate set is empty. `creatinine` is in UMLS;
`creat` is not. Only vocabulary closes that.

**Nothing here is a UMLS string or a CUI.** The table maps shorthand to ordinary
clinical English, and the caller's own licensed terminology resolves the long
form. That is what lets it ship, and it is also why the resource carries no
identifiers.

**Slot scoping is the safety mechanism, not a convenience.** Every entry names
the structural position it is valid in and is applied nowhere else, so the entry
criterion is *monosemous within its slot* rather than monosemous outright. That
distinction lets in entries a global table would have to reject: `pt` in a
labelled-value slot is prothrombin time, while in prose it is the patient or
physical therapy; `ca` is calcium in the slot and cancer outside it. The slot has
already done the disambiguating, which is the same argument that makes the
structural emitter work at all.

Anything ambiguous *inside* its slot does not belong here. It belongs to the
anchor-vote rung, which abstains.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from robustehr.resources import load_yaml, resource_sha256

EXPANSIONS_RESOURCE = "lab_shorthand.yaml"


class Slot(StrEnum):
    """The structural position an expansion is valid in."""

    VALUE_LABEL = "value_label"
    """The label half of ``Creat-1.1`` — a labelled numeric value."""
    EXAM_LABEL = "exam_label"
    """The system named by an exam subsection header, ``HEENT:``."""


@dataclass(frozen=True, slots=True)
class Expansion:
    """One shorthand form and what it stands for, in one slot."""

    short: str
    long: str
    slot: Slot
    panel: str = ""
    """The orderable panel it belongs to — the authoring unit, and a reviewer's
    handle. Empty for exam labels, which are organised by system instead."""
    snomed: str = ""
    """The concept this expansion names, as a SNOMED identifier.

    **The authoritative half of the entry**, with :attr:`long` demoted to a
    human-readable review handle and a fallback. Anchoring to an identifier
    rather than to a string fixes a defect the string-only design had by
    construction: the long form is a *lookup key*, so an entry expanding to a
    string the terminology does not carry resolves to nothing and is dropped
    exactly as if absent — `crp -> C reactive protein` fails where
    `c-reactive protein` works — and nothing in the pipeline would notice.

    Identifiers also ship where strings do not. `phenotypes.yaml` already
    carries SNOMED seed codes on exactly that basis: the licence constrains
    vocabulary *content*, and a code is not content.

    Empty where this UMLS release maps the concept to no SNOMED code at all
    (`baso`, `pco2`, `hba1c`, `hr`, `temp`, `gen`), in which case the long form
    is all there is.
    """


@dataclass(frozen=True, slots=True)
class ExpansionTable:
    """Shorthand expansions, indexed by ``(slot, lowercased short form)``."""

    entries: tuple[Expansion, ...]
    reviewed: bool
    sha256: str

    @property
    def _index(self) -> dict[tuple[Slot, str], Expansion]:
        return {(e.slot, e.short.lower()): e for e in self.entries}

    def entry(self, surface: str, slot: Slot) -> Expansion | None:
        """The whole entry, so a caller can prefer the identifier over the string."""
        return self._index.get((slot, surface.strip().lower()))

    def expand(self, surface: str, slot: Slot) -> str | None:
        """The long form for this surface in this slot, or ``None``.

        Case-insensitive, because `Creat`, `creat` and `CREAT` are the same
        analyte and a table that distinguished them would be a table with three
        rows per entry and three chances to disagree with itself.
        """
        found = self._index.get((slot, surface.strip().lower()))
        return found.long if found is not None else None

    def for_slot(self, slot: Slot) -> tuple[Expansion, ...]:
        return tuple(e for e in self.entries if e.slot is slot)

    def __len__(self) -> int:
        return len(self.entries)


@lru_cache(maxsize=1)
def load_expansions() -> ExpansionTable:
    """The shipped expansion table.

    Raises at load rather than returning a flawed table, on the same principle
    as the category loader: a duplicate entry is a silent behaviour change, and
    discovering it in a measurement is far more expensive than discovering it
    here.
    """
    raw = load_yaml(EXPANSIONS_RESOURCE)
    entries = tuple(
        Expansion(
            short=str(row["short"]),
            long=str(row["long"]),
            slot=Slot(str(row["slot"])),
            panel=str(row.get("panel", "")),
            snomed=str(row.get("snomed", "")),
        )
        for row in raw["expansions"]
    )
    _check_consistency(entries)
    return ExpansionTable(
        entries=entries,
        reviewed=bool(raw.get("reviewed", False)),
        sha256=resource_sha256(EXPANSIONS_RESOURCE),
    )


def _check_consistency(entries: tuple[Expansion, ...]) -> None:
    """Refuse a table that cannot mean one thing.

    Two rows with the same short form in the same slot make the expansion depend
    on iteration order — the exact class of defect the determinism rules exist to
    prevent, arriving through a data file rather than through code.
    """
    seen: dict[tuple[Slot, str], str] = {}
    for entry in entries:
        key = (entry.slot, entry.short.lower())
        if key in seen and seen[key] != entry.long:
            raise ValueError(
                f"{entry.short!r} in slot {entry.slot.value} expands to both "
                f"{seen[key]!r} and {entry.long!r}; an expansion must be "
                "monosemous within its slot or it does not belong in this table"
            )
        seen[key] = entry.long
        if not entry.long.strip():
            raise ValueError(f"{entry.short!r} has an empty long form")
        if entry.short.lower() == entry.long.lower():
            raise ValueError(
                f"{entry.short!r} expands to itself, which cannot help: the "
                "point of an entry is to reach a form the terminology carries"
            )


__all__ = [
    "EXPANSIONS_RESOURCE",
    "Expansion",
    "ExpansionTable",
    "Slot",
    "load_expansions",
]
