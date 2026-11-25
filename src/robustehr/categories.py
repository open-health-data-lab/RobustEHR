"""What kind of clinical thing is this token?

The question "is this word clinical?" was the wrong one, and dropping it removes
a problem that could not be solved rather than solving it. It is too broad to
answer — measured on the development corpus, general-English frequency,
source-vocabulary count and Semantic Group each failed to separate ``one``,
``well``, ``normal`` and ``stairs`` from ``dyspnea`` and ``pneumonia`` — and too
broad to act on, because no use case actually wants "corrupt clinical words". Use
cases want *corrupt the medications*, or *corrupt the diagnoses but not the
symptoms*.

So the primary axis is **which semantic category a term belongs to**, and the
second is **whether it relates to a phenotype under study**, which the concept
layer answers. Between them they cover what a robustness experiment needs to
target, and neither requires a universal definition of "clinical".

This is also what makes the determination defensible. Category membership is a
lookup against a published, versioned terminology — a term either carries T121 or
it does not — so there is no threshold to justify and disagreement is concrete.

**Granularity is the semantic type (TUI), not the Semantic Group.** McCray's
groups put Disease or Syndrome (T047) and Sign or Symptom (T184) both into
``DISO``, so a group-level target cannot tell a diagnosis from a symptom, which is
precisely the distinction a phenotyping study turns on.

A consequence worth stating because it does real work: **T033 "Finding" is
excluded from every default category.** It is where source vocabularies deposit
whatever does not fit elsewhere, and where the noise lives — ``one``, ``well``,
``normal``, ``stairs`` and ``history`` are T033-only. Excluding it quarantines
that noise by construction rather than by tuning a threshold.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from typing import Any

from robustehr.resources import load_yaml

CATEGORIES_RESOURCE = "semantic_categories.yaml"


class Tier(StrEnum):
    """How strongly a category's boundary is evidenced.

    Carried into every result so a reader can tell which numbers rest on a gold
    standard and which do not. Pretending a fine category is validated because
    its parent is would be exactly the overclaim this distinction prevents.
    """

    ANCHORED = "anchored"
    """A gold standard adjudicates this category directly, via ``crosswalk``."""
    DERIVED = "derived"
    """A semantic-type partition of an anchored parent. The parent's boundary is
    validated; the split within it is deterministic and inspectable, but no gold
    standard adjudicates it."""
    UNANCHORED = "unanchored"
    """No gold standard covers it. Usable, honestly marked, never a headline."""


@dataclass(frozen=True, slots=True)
class SemanticCategory:
    """A named set of UMLS semantic types, plus how it gets validated."""

    name: str
    label: str
    definition: str
    """One-sentence statement of what belongs here and why it is separate."""
    tuis: frozenset[str]
    tier: Tier = Tier.UNANCHORED
    crosswalk: Mapping[str, str] = field(default_factory=dict)
    """Gold standard -> the label there that this category maps onto.

    The crosswalk *is* the validation protocol: it says which annotations to
    compare against, which is what makes "we validated the categories" a
    reproducible claim rather than a sentence.
    """
    parent: str | None = None
    children: tuple[str, ...] = ()
    in_default: bool = True
    """Whether this category counts towards ``clinical_any``."""
    note: str = ""

    def admits(self, tuis: frozenset[str]) -> bool:
        return bool(tuis & self.tuis)

    @property
    def is_validatable(self) -> bool:
        """Can a number be put on this category's boundary directly?"""
        return self.tier is Tier.ANCHORED


@lru_cache(maxsize=1)
def load_categories() -> dict[str, SemanticCategory]:
    raw: dict[str, Any] = load_yaml(CATEGORIES_RESOURCE)
    excluded = set(raw.get("clinical_any_excludes", ()))
    out: dict[str, SemanticCategory] = {}
    for name, entry in raw["categories"].items():
        out[name] = SemanticCategory(
            name=name,
            label=str(entry.get("label", name)),
            definition=" ".join(str(entry.get("definition", "")).split()),
            tuis=frozenset(str(t) for t in entry["tuis"]),
            tier=Tier(str(entry.get("tier", Tier.UNANCHORED.value))),
            crosswalk={str(k): str(v) for k, v in (entry.get("crosswalk") or {}).items()},
            parent=entry.get("parent"),
            children=tuple(entry.get("children", ())),
            in_default=bool(entry.get("default", True)) and name not in excluded,
            note=str(entry.get("note", "")),
        )
    _check_consistency(out)
    return out


def _check_consistency(categories: dict[str, SemanticCategory]) -> None:
    """Catch a malformed taxonomy at load rather than in a result.

    A derived category whose types escape its parent is a silent measurement
    error: results would be reported under a parent whose validated boundary
    does not actually contain them.
    """
    for name, category in categories.items():
        if category.parent is not None:
            parent = categories.get(category.parent)
            if parent is None:
                raise ValueError(f"category {name!r} names unknown parent {category.parent!r}")
            if not category.tuis <= parent.tuis:
                escaped = sorted(category.tuis - parent.tuis)
                raise ValueError(
                    f"category {name!r} has semantic types outside its parent "
                    f"{category.parent!r}: {escaped}"
                )
        if not category.definition:
            raise ValueError(f"category {name!r} has no definition")
        if category.tier is Tier.ANCHORED and not category.crosswalk:
            raise ValueError(
                f"category {name!r} is tier=anchored but declares no crosswalk; "
                "an anchored category must say which gold standard adjudicates it"
            )
        for child in category.children:
            if child not in categories:
                raise ValueError(f"category {name!r} names unknown child {child!r}")


@lru_cache(maxsize=1)
def default_tuis() -> frozenset[str]:
    """Semantic types counting as clinical content when no category is named.

    Excluded categories are **subtracted**, not merely omitted from the union.
    Omitting them does nothing, because an excluded category is usually a subset
    of an included parent: ``finding`` is part of ``disorder``, so leaving it out
    of the union still admits T033 through ``disorder`` and the exclusion becomes
    decorative.

    Consequence worth knowing: this makes ``clinical_any`` narrower than
    ``disorder``. Targeting ``disorder`` explicitly *does* include findings —
    that is what the SNOMED ``clinical finding`` hierarchy means — while the
    unnamed default stays conservative. Naming a category always gets you
    exactly that category.
    """
    categories = load_categories().values()
    included = frozenset(tui for c in categories if c.in_default for tui in c.tuis)
    excluded = frozenset(tui for c in categories if not c.in_default for tui in c.tuis)
    return included - excluded


def default_categories() -> frozenset[str]:
    """Category names counted as content when a target names none."""
    return frozenset(n for n, c in load_categories().items() if c.in_default)


def tuis_for(*names: str) -> frozenset[str]:
    """Resolve category names to the semantic types they cover.

    Raises on an unknown name rather than returning an empty set: a typo in a
    target would otherwise silently select nothing and report a legitimate-looking
    dose of zero.
    """
    categories = load_categories()
    unknown = [n for n in names if n not in categories]
    if unknown:
        raise ValueError(
            f"unknown semantic categor{'y' if len(unknown) == 1 else 'ies'} "
            f"{unknown!r}; known: {sorted(categories)}"
        )
    return frozenset(tui for name in names for tui in categories[name].tuis)


def anchored() -> dict[str, SemanticCategory]:
    """Categories a gold standard can put a number on."""
    return {n: c for n, c in load_categories().items() if c.is_validatable}


def gold_standards() -> dict[str, list[str]]:
    """Which categories each gold standard can validate."""
    out: dict[str, list[str]] = {}
    for name, category in sorted(load_categories().items()):
        for standard in category.crosswalk:
            out.setdefault(standard, []).append(name)
    return out


def categories_of(tuis: frozenset[str]) -> frozenset[str]:
    """Which named categories these semantic types belong to."""
    return frozenset(name for name, c in load_categories().items() if c.admits(tuis))


#: A concept matched, and none of its semantic types is in the partition.
UNCATEGORIZED = "uncategorized"
#: No concept covers the word at all.
NO_CONCEPT = "no_concept"


@lru_cache(maxsize=1)
def exclusive_order() -> tuple[str, ...]:
    """The precedence that gives a concept exactly one category.

    Read from ``exclusive_order`` in the resource and checked at load: every
    name must be a category, and a parent may not be listed ahead of one of its
    own children, since it would absorb everything the child admits.
    """
    raw: dict[str, Any] = load_yaml(CATEGORIES_RESOURCE)
    order = tuple(str(name) for name in raw["exclusive_order"])
    categories = load_categories()
    unknown = [name for name in order if name not in categories]
    if unknown:
        raise ValueError(f"exclusive_order names unknown categor(ies) {unknown}")
    for position, name in enumerate(order):
        parent = categories[name].parent
        if parent in order[:position]:
            raise ValueError(
                f"exclusive_order lists {parent!r} ahead of its child {name!r}, "
                "which would then never be assigned"
            )
    if len(set(order)) != len(order):
        raise ValueError("exclusive_order lists a category twice")
    return order


def primary_category(tuis: frozenset[str] | None) -> str:
    """The one category a concept is counted under, for tables that must sum.

    :func:`categories_of` returns every category that admits a concept, which is
    what a target wants and what a table cannot use: rows would overlap and their
    shares would sum past 100%. This returns the first category of
    :func:`exclusive_order` that admits it.

    ``tuis`` is the concept's semantic types, or ``None`` when no concept covers
    the word. The two failures are different facts and are returned as different
    values: :data:`NO_CONCEPT` when there was nothing to classify, and
    :data:`UNCATEGORIZED` when a concept matched whose types the partition does
    not name.
    """
    if tuis is None:
        return NO_CONCEPT
    found = categories_of(tuis)
    for name in exclusive_order():
        if name in found:
            return name
    return UNCATEGORIZED


@lru_cache(maxsize=1)
def display_groups() -> dict[str, tuple[str, tuple[str, ...]]]:
    """``{group: (label, members)}``: the partition grouped for reading.

    Checked at load to be a partition of everything :func:`primary_category`
    can return, so a table built on the groups cannot drop or double a word.
    """
    raw: dict[str, Any] = load_yaml(CATEGORIES_RESOURCE)
    groups = {
        str(name): (str(entry["label"]), tuple(str(m) for m in entry["members"]))
        for name, entry in raw["display_groups"].items()
    }
    members = [m for _, group in groups.values() for m in group]
    expected = {*exclusive_order(), UNCATEGORIZED, NO_CONCEPT}
    if sorted(members) != sorted(expected):
        raise ValueError(
            "display_groups must hold each primary category exactly once; "
            f"missing {sorted(expected - set(members))}, "
            f"unexpected or repeated {sorted(set(members) - expected)}"
        )
    return groups


def display_group(category: str) -> str:
    """The display group a primary category belongs to."""
    for name, (_, members) in display_groups().items():
        if category in members:
            return name
    raise ValueError(f"{category!r} is not a primary category; see exclusive_order()")


__all__ = [
    "CATEGORIES_RESOURCE",
    "NO_CONCEPT",
    "UNCATEGORIZED",
    "SemanticCategory",
    "Tier",
    "anchored",
    "categories_of",
    "default_categories",
    "default_tuis",
    "display_group",
    "display_groups",
    "exclusive_order",
    "gold_standards",
    "load_categories",
    "primary_category",
    "tuis_for",
]
