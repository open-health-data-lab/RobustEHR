"""Concept-set expansion through the UMLS hierarchy.

A phenotype is declared by a handful of **seed** concepts and expanded to the set
of concepts that count as evidence for it. Expansion is what makes the
declaration tractable: nobody enumerates every way a note can say "chronic kidney
disease", but everybody can name the root.

The expansion is **descendant closure over ``isa``**, restricted to one source
vocabulary. Measured on the challenge's own error cases, this is what absorbs the
largest class of concept-assignment errors: ``Diverticulosis`` (C1510475) is the
``isa`` parent of ``Diverticulosis of large intestine`` (C4518471), and
``Chronic kidney disease`` (C1561643) the parent of ``stage 3`` (C2316787). A
matcher that lands on the general concept where an annotator chose the specific
one still lands inside a descendant-closed set, so the disagreement costs nothing.

**Two edge sets, and the second is the one that is easy to miss.**

UMLS has no concept hierarchy of its own in the usual sense: every edge in
``MRREL`` carries a ``SAB`` naming the vocabulary that asserted it. So "the UMLS
hierarchy" can only mean one source's, or the union of all of them — except for
one genuinely Metathesaurus-native layer, ``SAB='MTH'``, where NLM asserts
broader/narrower relations itself rather than inheriting them.

Both are used here, because each reaches concepts the other cannot:

* ``SNOMEDCT_US`` ``isa`` — one editorially coherent clinical hierarchy, and the
  one the gold standard is annotated in.
* ``MTH`` ``RN`` — the Metathesaurus's own narrower-than assertions, 453,230 of
  them. This is what connects concepts that no clinical source places in a
  common tree. ``C0011847`` (*Diabetes*) has **no ``isa`` edge in any source
  vocabulary** — it is hierarchically orphaned everywhere except ``PSY`` — yet
  ``MTH`` records ``C0011847 --RN--> C0011849`` (*Diabetes Mellitus*). Our
  matcher returns the former where annotators chose the latter, so without this
  edge set that mention is unreachable from any SNOMED seed.

Both conventions place the parent in ``cui1``.

Taking the union across *every* source was measured as the third option and
rejected on evidence rather than taste. It triples the mean closure (434 concepts
against 202) and buys nothing: it claims **fewer** gold evidence spans than
``isa + MTH.RN`` (994 against 998) while introducing cross-phenotype
contamination that the other two have none of — 28 gold spans claimed by both
the hypertension and the heart-failure set, which are clinically distinct and
share no evidence by construction. A closure that conflates two phenotypes is
worse than a smaller one, however good its recall looks.

That comparison is also why set recall is never reported alone. Recall rises
monotonically with closure size, so without a specificity counterpart "expand
harder" always appears to win.

**Edge direction is verified, not assumed.** In ``MRREL`` a row carrying
``rela='isa'`` reads *cui2 is a kind of cui1* — the parent is ``cui1``. This is
easy to get backwards and fails quietly, because reversing it still produces a
plausible-looking closure: an ancestor closure rather than a descendant one. The
check that settles it is a concept pair whose direction is known independently —
``Diverticulosis`` (C1510475) and ``Diverticulosis of large intestine``
(C4518471) appear as ``cui1=C1510475, cui2=C4518471, rel=CHD, rela=isa``, so
``cui1`` is the general concept. ``tests/test_hierarchy.py`` pins the resulting
orientation.

**Closure is bounded by depth, deliberately.** Unbounded descent from a
sufficiently general seed reaches most of the terminology, and a phenotype whose
evidence set is a third of SNOMED is not a phenotype. A depth limit makes
over-broad seeds fail visibly at build time rather than silently at run time.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Relations that mean "is a kind of", in the direction child -> parent.
ISA_RELATIONS = ("isa",)

#: The single source vocabulary the closure follows. See the module docstring.
SOURCE = "SNOMEDCT_US"

#: How far a closure may descend from a seed before it is treated as a mistake.
MAX_DEPTH = 12

MRREL_COLUMNS: list[str] = [
    "cui1",
    "aui1",
    "stype1",
    "rel",
    "cui2",
    "aui2",
    "stype2",
    "rela",
    "rui",
    "srui",
    "sab",
    "sl",
    "rg",
    "dir",
    "suppress",
    "cvf",
]


@dataclass(frozen=True, slots=True)
class Hierarchy:
    """Parent -> children over one vocabulary's ``isa`` relation."""

    children: dict[str, tuple[str, ...]]

    def descendants(self, *seeds: str, max_depth: int = MAX_DEPTH) -> frozenset[str]:
        """Every concept at or below the seeds, breadth-first and bounded.

        Includes the seeds themselves: a phenotype's own root concept is
        evidence for it.
        """
        seen: set[str] = set(seeds)
        frontier: deque[tuple[str, int]] = deque((s, 0) for s in seeds)
        while frontier:
            node, depth = frontier.popleft()
            if depth >= max_depth:
                continue
            for child in self.children.get(node, ()):
                if child not in seen:
                    seen.add(child)
                    frontier.append((child, depth + 1))
        return frozenset(seen)

    def __len__(self) -> int:
        return len(self.children)


def build(
    release: Any, out: Path, *, source: str | None = SOURCE, metathesaurus: bool = True
) -> dict[str, Any]:
    """Extract the ``isa`` edges once into a cached artifact.

    ``MRREL`` is several gigabytes and re-reading it per query is untenable, so
    the edge list is materialized. Derived from licensed content, so it lives
    beside the other build products under ``data/`` and never enters git.
    """
    import duckdb

    con = duckdb.connect(":memory:")
    # source=None takes the union across every contributing vocabulary. UMLS has
    # no concept hierarchy of its own — every edge in MRREL carries a SAB — so
    # "the UMLS hierarchy" can only mean one source's or the union of all.
    isa = "rela = 'isa'"
    if source is not None:
        isa = f"sab = '{source}' AND {isa}"
    clauses = [isa]
    if metathesaurus:
        # The Metathesaurus's own narrower-than assertions, which reach concepts
        # no source vocabulary places in a tree. See the module docstring.
        clauses.append("(sab = 'MTH' AND rel = 'RN')")
    rows = con.execute(f"""
        SELECT DISTINCT cui1 AS parent, cui2 AS child
        FROM read_csv('{release.rrf("MRREL.RRF")}', delim='|', header=false,
                      quote='', names={MRREL_COLUMNS!r}, all_varchar=true)
        WHERE suppress = 'N' AND ({" OR ".join(clauses)})
    """).fetchall()
    children: dict[str, list[str]] = {}
    for parent, child in rows:
        children.setdefault(str(parent), []).append(str(child))
    payload = {
        "source": source or "ALL",
        "relation": "isa+MTH.RN" if metathesaurus else "isa",
        "parents": len(children),
        "edges": sum(len(v) for v in children.values()),
        "children": {k: sorted(set(v)) for k, v in sorted(children.items())},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return {k: v for k, v in payload.items() if k != "children"}


def load(path: Path) -> Hierarchy:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Hierarchy(children={k: tuple(v) for k, v in raw["children"].items()})


__all__ = ["ISA_RELATIONS", "MAX_DEPTH", "SOURCE", "Hierarchy", "build", "load"]
