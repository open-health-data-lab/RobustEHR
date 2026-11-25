#!/usr/bin/env python
"""What is actually IN each phenotype's concept set, by facet and by category.

**The question this answers.** A phenotype ships as a count — "hypertension, 361
concepts" — and a count cannot be reviewed. 361 what? The audit that motivated
the facet layer was exactly this table, and it showed every set was 100%
disorder: depression carried 206 disorders, 13 findings and **zero** medications,
so a perturbation aimed at "the depression content of this note" left every
antidepressant untouched.

Two decompositions, because they answer different questions:

*By facet* — how the concept got in, which is a property of our construction:
``disorder`` closure, ``medication`` from MED-RT, ``finding`` from declared
seeds. This is the axis a reader checks for coverage gaps.

*By UMLS semantic category* — what the concept IS, independent of how we found
it. This is the axis a reader checks for contamination: a disorder facet holding
``anatomy`` concepts, or a medication facet holding ``procedure`` ones, is a
closure that wandered. The two are deliberately not the same partition, and
comparing them is the point.

**Categories are RobustEHR's, not UMLS's own.** UMLS ships 127 semantic types;
``robustehr.categories`` groups them into the twelve a clinical reader thinks in.
A concept can carry several types and so land in several categories — hypertension
is both ``disease`` and ``disorder`` — so the category columns **sum to more than
the set size** by construction, and ``uncategorised`` is the residue that maps to
none of the twelve.

**Licence.** Reads MRSTY from the local release. Emits identifiers and counts;
no UMLS string.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.categories import categories_of
from robustehr.concepts import facets, hierarchy
from robustehr.concepts.phenotype import build, load_definitions, load_maps

#: Column order for the printed table: clinical content first, then the
#: categories that indicate a closure has drifted.
COLUMNS = [
    "disorder",
    "disease",
    "finding",
    "symptom",
    "medication",
    "procedure",
    "therapeutic_procedure",
    "diagnostic_procedure",
    "lab_measurement",
    "lab_result",
    "anatomy",
    "device",
    "uncategorised",
]

#: The manuscript partition: every concept counted exactly once, in this order.
#:
#: The shipped taxonomy is a *lattice*, not a partition — `disorder` is the
#: parent of `disease`, `symptom` and `finding`, and `procedure` the parent of
#: its two children — so category counts overlap and a column total exceeds the
#: set size. That is right for targeting (a user asking for `cat=disorder` wants
#: all three children) and wrong for a table a reader sums.
#:
#: These eight are the leaf-level categories, and at TUI level they are disjoint:
#: disease is the T047 family, `finding` is T033, `symptom` is T184,
#: `lab_result` is T034, and no concept carries two of them.
#:
#: Concept-level overlap survives TUI-level disjointness, because one CUI may
#: carry several types. `contested` counts those, so a reader can see how much
#: the tie-break moved.
#:
#: **`lab_measurement` is deliberately absent, and cannot be added.** It is by
#: construction the union of T034 and T059 — the analyte *and* the procedure that
#: produces it — so it has no territory of its own once `procedure` (T059) and
#: `lab_result` (T034) are both present. Listing it as a ninth column would
#: report a structural zero as if it were a measurement. Its members are split
#: across those two, and `lab_measurement_union` reports the total so the
#: quantity is not lost.
EXCLUSIVE = [
    "disease",
    "finding",
    "symptom",
    "medication",
    "anatomy",
    "procedure",
    "lab_result",
    "device",
]

#: The two types `lab_measurement` spans, counted together for disclosure.
LAB_TUIS = frozenset({"T034", "T059"})


def assign_one(tuis: frozenset[str]) -> tuple[str, int]:
    """The single category a concept is counted under, and how many it matched.

    Returns ``other`` for a concept in none of the eight — mostly organisms,
    chemicals that are not drugs, and the qualifier types.
    """
    found = categories_of(tuis)
    matched = [c for c in EXCLUSIVE if c in found]
    return (matched[0] if matched else "other"), len(matched)


def load_semantic_types(mrsty: Path, wanted: frozenset[str]) -> dict[str, frozenset[str]]:
    """CUI -> its TUIs, for the concepts we care about.

    MRSTY rather than the matcher: these concepts are being audited as a *set*,
    and most of them never appear in any note, so there is nothing to match.
    """
    types: dict[str, set[str]] = {}
    with mrsty.open(encoding="utf-8") as handle:
        for line in handle:
            cui, tui = line.split("|", 2)[:2]
            if cui in wanted:
                types.setdefault(cui, set()).add(tui)
    return {c: frozenset(t) for c, t in types.items()}


def facet_sets(
    name: str,
    definition: Any,
    maps: tuple[Any, Any, Any],
    edges: facets.FacetEdges,
    resources: tuple[dict[str, Any], dict[str, Any]],
) -> dict[str, facets.FacetSet]:
    """One phenotype's facets: relation-derived, plus knowledge-first proposals.

    The two halves are kept as separate facets rather than merged, because they
    carry different warrants. ``disorder`` and ``medication`` are traversals of a
    curated vocabulary; ``proposed`` is clinical knowledge grounded against that
    vocabulary, and a reader deciding how much to trust a count needs to see
    which produced it.
    """
    isa, code_to_cuis, cui_to_codes = maps
    proposals, vetting = resources
    disorder = build([name], isa, code_to_cuis, cui_to_codes, facets=False)[0].concept_cuis
    seeds = frozenset(c for code in definition.seeds for c in code_to_cuis.get(code, ()))
    grounded = frozenset(c for cuis in proposals.get(name, {}).values() for c in cuis)
    # The same gate `phenotype.build` applies: a vetting row over the proposed
    # facet keeps only its keeps, so this audit counts the SHIPPED set, not the
    # raw candidates. No row means no gate (pre-vetting behaviour).
    kept_proposed = vetting.get(name, {}).get("proposed")
    if kept_proposed is not None:
        grounded &= kept_proposed
    # Strict gate, same as `phenotype.build`: candidates AND a kept verdict.
    closure = facets.load_closure().get(name, frozenset()) & vetting.get(name, {}).get(
        "closure", frozenset()
    )
    return {
        "disorder": facets.FacetSet(
            facets.Facet.DISORDER,
            disorder,
            0,
            "descendant closure",
            dict.fromkeys(disorder, "closure"),
        ),
        "medication": facets.medications(
            seeds,
            disorder,
            edges,
            declared=definition.medication_seeds,
            vetted=vetting.get(name, {}).get("medication"),
        ),
        "finding": facets.findings(definition.finding_seeds, isa, code_to_cuis),
        "proposed": facets.FacetSet(
            facets.Facet.FINDING,
            grounded,
            0,
            "LLM-proposed terms grounded against the release, vetting-gated",
            dict.fromkeys(grounded, "proposed"),
        ),
        "closure": facets.FacetSet(
            facets.Facet.DISORDER,
            closure,
            0,
            "one-hop hierarchy neighborhood, vetting-gated (strict)",
            dict.fromkeys(closure, "closure"),
        ),
    }


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--edges", type=Path, default=facets.DEFAULT_EDGES)
    parser.add_argument("--mrsty", type=Path, default=Path("data/umls/2026AA/META/MRSTY.RRF"))
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/phenotype_set_audit.json")
    )
    args = parser.parse_args(argv)

    definitions = load_definitions()
    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    edges = facets.load(args.edges)
    proposals = facets.load_proposals()
    vetting = facets.load_vetting()

    per_phenotype = {
        name: facet_sets(name, d, (isa, code_to_cuis, cui_to_codes), edges, (proposals, vetting))
        for name, d in definitions.items()
    }
    union = frozenset(c for sets in per_phenotype.values() for f in sets.values() for c in f.cuis)
    types = load_semantic_types(args.mrsty, union)

    def categories(cuis: frozenset[str]) -> Counter[str]:
        counts: Counter[str] = Counter()
        for cui in cuis:
            found = categories_of(types.get(cui, frozenset()))
            for category in found or ("uncategorised",):
                counts[category] += 1
        return counts

    def exclusive(cuis: frozenset[str]) -> tuple[dict[str, int], int]:
        counts: Counter[str] = Counter()
        contested = 0
        for cui in cuis:
            category, matched = assign_one(types.get(cui, frozenset()))
            counts[category] += 1
            contested += matched > 1
        return dict(counts), contested

    rows: dict[str, Any] = {}
    for name, sets in per_phenotype.items():
        every = frozenset(c for f in sets.values() for c in f.cuis)
        partition, contested = exclusive(every)
        rows[name] = {
            "total_distinct_cuis": len(every),
            "by_facet": {k: v.to_row() for k, v in sets.items()},
            "exclusive": partition,
            "exclusive_contested": contested,
            "lab_measurement_union": sum(1 for c in every if LAB_TUIS & types.get(c, frozenset())),
            "by_category": dict(sorted(categories(every).items())),
            "by_facet_and_category": {
                k: dict(sorted(categories(v.cuis).items())) for k, v in sets.items()
            },
            "cuis_with_no_semantic_type": sum(1 for c in every if c not in types),
        }

    payload = {
        "question": "what is in each phenotype's concept set, by facet and by category?",
        "facets": (
            "how the concept got in: disorder = descendant closure, medication = "
            "MED-RT may_treat with bounded ancestor lift plus declared seeds, "
            "finding = declared seeds expanded by closure (UMLS has no usable "
            "disease->symptom relation; see concepts/facets.py)"
        ),
        "categories": (
            "what the concept IS, from MRSTY semantic types grouped by "
            "robustehr.categories. A concept carrying several types lands in "
            "several categories, so category counts SUM TO MORE than the set "
            "size. `uncategorised` maps to none of the twelve."
        ),
        "why_both": (
            "facets are checked for coverage gaps, categories for contamination. "
            "A disorder facet full of anatomy concepts is a closure that wandered."
        ),
        "licence": "identifiers and counts only; no UMLS string appears here",
        "phenotypes": rows,
        "exclusive_partition": {
            "order": EXCLUSIVE,
            "rule": (
                "a concept is counted under the FIRST category in this order it "
                "matches, so the columns sum to the set size. The shipped "
                "taxonomy is a lattice — disorder is the parent of disease, "
                "symptom and finding — which is right for targeting and wrong "
                "for a table a reader sums."
            ),
            "lab_measurement_is_not_a_column": (
                "lab_measurement is the union T034 (lab_result) and T059 (a "
                "procedure), because it deliberately spans both readings of an "
                "analyte like `Hgb-9.9`. With procedure and lab_result both "
                "present it has no exclusive territory, so listing it would "
                "report a structural zero as a measurement. "
                "`lab_measurement_union` carries the total instead."
            ),
            "other": "in none of the eight — organisms, non-drug chemicals, qualifiers",
        },
        "totals": {
            "distinct_cuis_over_all_phenotypes": len(union),
            "by_facet": {
                facet: sum(len(s[facet].cuis) for s in per_phenotype.values())
                for facet in ("disorder", "medication", "finding", "proposed", "closure")
            },
            "exclusive": dict(sorted(exclusive(union)[0].items())),
            "lab_measurement_union": sum(1 for c in union if LAB_TUIS & types.get(c, frozenset())),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    width = max(len(n) for n in rows)
    print(
        f"{'phenotype':<{width}} {'TOTAL':>6} {'disord':>7} {'med':>6} {'ident':>6} "
        f"{'find':>6} {'propos':>7} {'closur':>7}"
    )
    for name, row in rows.items():
        f = row["by_facet"]
        identity = f["medication"].get("by_provenance", {}).get("identity", 0)
        print(
            f"{name:<{width}} {row['total_distinct_cuis']:>6} {f['disorder']['n']:>7} "
            f"{f['medication']['n']:>6} {identity:>6} {f['finding']['n']:>6} "
            f"{f['proposed']['n']:>7} {f['closure']['n']:>7}"
        )
    print(f"\n{'phenotype':<{width}} " + " ".join(f"{c[:6]:>6}" for c in COLUMNS))
    for name, row in rows.items():
        cells = row["by_category"]
        print(f"{name:<{width}} " + " ".join(f"{cells.get(c, 0):>6}" for c in COLUMNS))

    header = [*EXCLUSIVE, "other"]
    print(f"\nEXCLUSIVE partition — every concept counted once, {' > '.join(EXCLUSIVE)}")
    print(
        f"{'phenotype':<{width}} {'TOTAL':>6} "
        + " ".join(f"{c[:6]:>6}" for c in header)
        + "  contested"
    )
    totals: Counter[str] = Counter()
    for name, row in rows.items():
        cells = row["exclusive"]
        totals.update(cells)
        line = " ".join(f"{cells.get(c, 0):>6}" for c in header)
        assert sum(cells.values()) == row["total_distinct_cuis"], name
        print(
            f"{name:<{width}} {row['total_distinct_cuis']:>6} {line}"
            f"  {row['lab_measurement_union']:>5}  {row['exclusive_contested']:>6}"
        )
    print(
        f"{'ALL (union)':<{width}} {payload['totals']['distinct_cuis_over_all_phenotypes']:>6} "
        + " ".join(f"{payload['totals']['exclusive'].get(c, 0):>6}" for c in header)
    )
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
