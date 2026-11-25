"""Which concepts discriminate between phenotypes, and which merely co-occur.

Methodology 14 states the criterion in prose: *a concept true of most
hospitalized patients — a CBC, a chest X-ray, fatigue — associates with every
phenotype at once and therefore with none.* It is the right test and it was
applied in the wrong place. Vetting judges one concept against one phenotype, so
the model deciding whether `fatigue` belongs in the depression set cannot see
that it has already been admitted to eleven others. The property is invisible
from inside a single decision.

Counted across the declared panel it becomes measurable, and it needs no corpus:
this is a statement about what the sets contain, not about what any note says.

**Families, not phenotypes.** Counting raw set membership would punish exactly
the overlap that ought to exist. `heart_failure`, `hfpef` and `hfref` share
concepts because they are one disease at three resolutions, and a screen that
called their shared concepts unspecific would delete what those phenotypes are
built from. So phenotypes are first grouped into families by seed ancestry in
the hierarchy — two phenotypes are related when one seed reaches the other, in
either direction — and a concept is scored by how many *families* it spans.

**The disorder facet is never screened.** A concept in a phenotype's own
descendant closure is that disease or a subtype of it, and nothing can be too
unspecific to be itself. Only the associative facets are eligible.

Usage::

    python validation/phenotype/scripts/phenotype_specificity.py
    python validation/phenotype/scripts/phenotype_specificity.py --threshold 3 --dry-run
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from robustehr.concepts import facets, hierarchy
from robustehr.concepts.phenotype import build, load_definitions, load_maps

#: A MEASUREMENT by default, not a shipped resource.
#:
#: Writing it into `src/robustehr/resources/` makes `_with_facets` subtract it
#: from every set, and that is a heavier decision than the screen's evidence
#: supports. Under a per-token-capped dose at rate 1.00 every eligible span
#: receives exactly one edit, so a broad set does not take edits away from the
#: diagnosis — the concepts this screen removes were costing interpretability,
#: not coverage. `Evidence.tier` now reports that directly, per tier, which is
#: strictly more informative than deleting the spans before anyone can see them.
#:
#: So the ladder and the flagged list are published and the sets are left alone.
#: Pass `--out src/robustehr/resources/phenotype_nonspecific.yaml` to apply it,
#: and expect to justify the removal against a reach measurement.
DEFAULT_OUT = Path("validation/measurements/phenotype_nonspecific_candidates.yaml")
DEFAULT_MEASUREMENT = Path("validation/measurements/phenotype_specificity.json")

#: Families a concept may span before it stops discriminating.
#:
#: **Deliberately high, and the height is the design.** This screen and the
#: vetting criterion divide one job between them, and the division is by how
#: contestable the call is. At five families a term is what sick inpatients
#: have — `fatigue`, `tachycardia`, `increased sweating`, a transthoracic echo,
#: aspirin — and no clinician would argue for keeping it as evidence of any one
#: phenotype. Those are worth removing mechanically, because a mechanical rule
#: applies them uniformly and a reviewer will not.
#:
#: Lower thresholds sweep in judgement. At three, the flagged set is dominated
#: by cardiovascular agents: metoprolol, amlodipine, enalapril, hydrochlorothiazide
#: each span hypertension, heart failure, atrial fibrillation and chest pain,
#: and a reader seeing metoprolol in a note HAS learned something cardiac. That
#: is a clinical judgement about how much a drug narrows the field, it belongs
#: to the vetting criterion where a model can weigh it concept by concept, and a
#: count of set memberships is not entitled to make it.
#:
#: Grouping cannot rescue the lower thresholds either. Merging phenotypes by
#: shared ancestry was tried, and the SNOMED hierarchy is too flat near the top
#: to support it: two `isa` hops up puts hypertension and type 2 diabetes in one
#: family and three puts eighteen phenotypes in one. The same umbrella-parent
#: problem `--max-fanout` exists to bound in the closure builder.
#:
#: The full ladder ships in the measurement artifact, so the cost of moving this
#: is visible rather than argued.
DEFAULT_THRESHOLD = 5

#: Facets the screen may remove from. `disorder` is absent on purpose.
SCREENED = ("medication", "finding", "proposed", "closure")


def families(
    names: list[str],
    definitions: dict[str, Any],
    isa: Any,
    code_to_cuis: Any,
    *,
    edges: Any | None = None,
    hops: int = 2,
) -> dict:
    """Group phenotypes that are the same clinical territory.

    Two phenotypes are related when one seed reaches the other, **or** when
    their seeds share an ancestor within ``hops`` ``isa`` steps up.

    The second clause is what makes the screen say anything useful about drugs.
    Descendant reachability alone splits hypertension, heart failure, atrial
    fibrillation and chest pain into four families, so every cardiovascular
    agent looks promiscuous: `metoprolol` spans four families and is flagged,
    when a reader seeing metoprolol in a note has genuinely learned something
    cardiac. Grouping by shared ancestry merges that territory, and a drug that
    still spans three families afterwards is spanning cardiology, psychiatry and
    endocrinology — which is what a term true of sick inpatients looks like.

    Union-find over the relation rather than a clustering: it is symmetric, and
    a similarity threshold would be one more number to defend.
    """
    seeds = {
        n: frozenset(c for code in definitions[n].seeds for c in code_to_cuis.get(code, ()))
        for n in names
    }
    reach = {
        n: frozenset(isa.descendants(*seeds[n], max_depth=6)) if seeds[n] else frozenset()
        for n in names
    }
    above = {
        n: (edges.ancestors(seeds[n], hops) - seeds[n])
        if edges is not None and seeds[n]
        else frozenset()
        for n in names
    }
    parent = dict.fromkeys(names)

    def find(x: str) -> str:
        while parent[x] is not None:
            x = parent[x]  # type: ignore[assignment]
        return x

    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            related = (
                bool(seeds[b] & reach[a]) or bool(seeds[a] & reach[b]) or bool(above[a] & above[b])
            )
            if not related:
                continue
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    grouped: dict[str, list[str]] = defaultdict(list)
    for n in names:
        grouped[find(n)].append(n)
    return {root: sorted(members) for root, members in sorted(grouped.items())}


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument(
        "--family-hops",
        type=int,
        default=0,
        help="merge phenotypes sharing an ancestor within N isa hops; 0 uses "
        "descendant reachability alone. Kept for sensitivity analysis: the "
        "hierarchy is too flat above 1 for this to mean what it sounds like",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--measurement", type=Path, default=DEFAULT_MEASUREMENT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    definitions = load_definitions()
    names = sorted(definitions)

    # Built with the screen necessarily absent or stale, which is why this reads
    # the facet artifacts directly rather than trusting a set it may have
    # narrowed on a previous run. The screen must be a function of the
    # candidates, not of its own last output.
    phenotypes = build(names, isa, code_to_cuis, cui_to_codes)
    by_name = {p.name: p for p in phenotypes}

    # Scored at the INGREDIENT, then propagated to its formulations.
    #
    # Scoring products directly measures the identity closure rather than
    # specificity. One admitted ingredient becomes dozens of CUIs — `metoprolol
    # Oral Solution`, `metoprolol tartrate 12.5 MG`, `metoprolol Cartridge` —
    # and every one of them spans exactly the families the ingredient spans, so
    # a ladder built on products counts the same clinical fact forty times and
    # is dominated by whichever drug has the most dose forms.
    #
    # `FacetSet.needs_review` already draws this line for the review queue, in
    # the same words and for the same reason: a brand or product form carries
    # its ingredient's verdict. The screen follows it.
    # Two hops, because neither map alone reaches the ingredient. `ingredient_of`
    # goes precise-ingredient -> base (amlodipine besylate -> amlodipine), and
    # `variants` goes ingredient -> its brands and products. A product therefore
    # needs the INVERSE of `variants` first, then `ingredient()` to normalise the
    # salt. Using `ingredient()` alone leaves every dose form as its own unit,
    # which is the flood this collapse exists to stop.
    edges = facets.load(facets.DEFAULT_EDGES) if facets.DEFAULT_EDGES.exists() else None
    base_of: dict[str, str] = {}
    if edges is not None:
        for ingredient, products in edges.variants.items():
            for product in products:
                # min() keeps it deterministic where a combination product lists
                # several ingredients; the unit only has to be stable, not chosen.
                prior = base_of.get(product)
                base_of[product] = ingredient if prior is None else min(prior, ingredient)

    def unit(cui: str) -> str:
        if edges is None:
            return cui
        return edges.ingredient(base_of.get(cui, cui))

    fams = families(names, definitions, isa, code_to_cuis, edges=edges, hops=args.family_hops)
    family_of = {n: root for root, members in fams.items() for n in members}

    # A concept in some phenotype's DISORDER facet is exempt everywhere: it is a
    # disease in its own right, and being widely associated does not make it
    # less of one.
    #
    # So is anything a human DECLARED. `medication_seeds` exists because the
    # vocabulary lagged — empagliflozin carries no `may_treat` edge to heart
    # failure in 2026AA, so it was named by hand precisely because no edge
    # existed to infer from. An automatic screen overriding that would be
    # deleting the curation the declaration was for, and `needs_review()`
    # already draws this exemption for the same reason.
    exempt: set[str] = set()
    for definition in definitions.values():
        for seed in definition.medication_seeds:
            exempt.add(seed)
            exempt.update(edges.variants_of(seed) if edges is not None else ())
    spans: dict[str, set[str]] = defaultdict(set)
    members_of: dict[str, set[str]] = defaultdict(set)
    for name, pheno in by_name.items():
        exempt |= set(pheno.facet_cuis.get("disorder", frozenset()))
        for facet in SCREENED:
            for cui in pheno.facet_cuis.get(facet, frozenset()):
                base = unit(cui)
                spans[base].add(family_of[name])
                members_of[base].add(cui)

    scored = {base: len(f) for base, f in spans.items() if base not in exempt}
    flagged_units = {base for base, n in scored.items() if n >= args.threshold}
    # Propagate: a flagged ingredient takes its formulations with it, or the
    # set would keep `Lasix` and `furosemide 20 MG` after dropping furosemide.
    flagged = sorted(cui for base in flagged_units for cui in members_of[base] if cui not in exempt)

    ladder = {
        str(t): sum(1 for n in scored.values() if n >= t)
        for t in range(2, max(6, args.threshold + 2))
    }
    distribution = {
        str(n): sum(1 for v in scored.values() if v == n) for n in sorted(set(scored.values()))
    }
    per_phenotype = {
        name: sum(
            1
            for facet in SCREENED
            for cui in by_name[name].facet_cuis.get(facet, frozenset())
            if cui in set(flagged)
        )
        for name in names
    }

    measurement = {
        "what": (
            "concepts spanning too many unrelated phenotype families to discriminate. "
            "Corpus-blind: a property of the declared sets, not of any note collection."
        ),
        "threshold": args.threshold,
        "families": {root: members for root, members in fams.items()},
        "family_count": len(fams),
        "family_hops": args.family_hops,
        "screened_facets": list(SCREENED),
        "units_scored": len(scored),
        "flagged_units": len(flagged_units),
        "flagged": len(flagged),
        "scored_at": "ingredient, with formulations inheriting; see needs_review()",
        "flagged_unit_share": round(len(flagged_units) / len(scored), 4) if scored else None,
        "families_spanned_distribution": distribution,
        "threshold_ladder": ladder,
        "removed_per_phenotype": per_phenotype,
    }

    print(f"{len(fams)} phenotype families over {len(names)} phenotypes")
    for root, members in fams.items():
        if len(members) > 1:
            print(f"  {root}: {', '.join(members)}")
    print(
        f"\n{len(scored)} associative concepts scored, "
        f"{len(flagged)} flagged at >= {args.threshold} families"
    )
    print(f"threshold ladder: {json.dumps(ladder)}")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    args.measurement.parent.mkdir(parents=True, exist_ok=True)
    args.measurement.write_text(json.dumps(measurement, indent=2, sort_keys=True), encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "what": measurement["what"],
                "licence": "identifiers only; no UMLS string appears here",
                "threshold": args.threshold,
                "family_count": len(fams),
                "screened_facets": list(SCREENED),
                "cuis": flagged,
            },
            sort_keys=True,
            width=88,
        ),
        encoding="utf-8",
    )
    print(f"\n{args.out}: {len(flagged)} concepts")
    print(f"{args.measurement}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
