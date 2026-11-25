#!/usr/bin/env python
"""Closure candidates: the one-hop neighborhood of each phenotype's concept set.

**The failure this closes.** The evidence audit found decisive surfaces matched
by the concept matcher to CUIs one relation away from the set: a note writes
"diastolic heart failure" (C1135196) and hfpef holds only the concepts *below*
it; 831 of 1,388 notes write "metastasis"/"metastatic disease" (C0027627) and
the metastatic_cancer set holds 1,087 site-specific descendants and not the
generic concept. A `pheno=X`-targeted corruption misses exactly the mention
that carries the phenotype call.

**Standard value-set expansion, bounded and adjudicated.** For every set
member: its parents (one hop up the isa+MTH-RN hierarchy), and for
non-medication members, those parents' children (one hop down — the siblings,
which is how hfpef reaches the diastolic-HF variants that are siblings of its
seed, not ancestors). This produces CANDIDATES ONLY: nothing here enters any
set. Admission requires the vetting pass (`phenotype_vet.py --facet closure`)
under a targeting criterion, and clinician sign-off before a manuscript run —
the same generate → adjudicate → freeze workflow every published value set
uses, and the same one this repo already applies to the medication facet.

**Two scale guards, both principled and both logged.**

*Parents come from every member; siblings only where documentation variants
live.* Every non-identity member contributes its parents (up 1): that is how
"Neoplasm Metastasis" arrives above the deep site-specific metastatic
concepts and "Insulin" above insulin glargine. Sibling expansion (down 1 from
those parents) runs only from the disorder top region — the seeds and their
depth-1 descendants, where "diastolic heart failure" sits beside the hfpef
seed — and from the small declared/proposed facets, where "Gastric Bypass"
sits beside the kept bariatric procedures. Deep-leaf siblings are not
documentation variants; expanding them produced 72k candidates — measured,
and the reason for the bound.

*Drugs never expand siblings.* A drug's siblings are the rest of its class —
exactly what MED-RT's `may_treat` edge deliberately did not assert for this
phenotype. Identity-tier variants contribute nothing at all: Layer 1's job.

*Umbrella parents do not expand.* A parent with more than --max-fanout
children (default 100) is a grouper ("Neurological finding", whose children
are the whole physical exam), not a documentation variant's home; it can
still BE a candidate itself, but its children are not pulled in through it.

*Hierarchy isolates need declaring.* A handful of documentation-variant CUIs
carry no isa/RN edge at all ("diastolic congestive heart failure", C2183328)
and NO graph rule can reach them. ``--declare name:CUI`` adds one as an
explicit candidate with source ``residual`` — it then faces the same vetting
and clinician adjudication as everything else, and the declaration is itself
recorded in the artifact. This is the residual-analysis route; it is not a
back door, because declaring a candidate admits nothing.

*Parents survive at any support; siblings need >= --min-support members
(default 2).* A parent generalizes its child by construction — "Metastatic
Renal Cell Cancer" above one site-specific member is a documentation variant
even though only one member sits under it — so the up-hop needs no
convergence. A sibling is lateral: reached from one member it is usually that
member's idiosyncratic neighbor, reached from several it is structure. The
generator prints the dropped support-1 sibling count so the threshold's cost
is visible, not assumed.

**Licence.** Reads the local hierarchy artifact; emits identifiers and counts
only. The output is a frozen resource so downstream runs need no UMLS.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from collections import Counter
from pathlib import Path

from robustehr.concepts import facets, hierarchy
from robustehr.concepts.phenotype import build, load_definitions, load_maps

#: The audit's motivating CUIs: the generator reports whether each was
#: produced, and for which phenotypes, so a run's log answers "did this close
#: the measured gap" before any vetting is spent.
MOTIVATING = {
    "C0027627": "Neoplasm Metastasis",
    "C1135196": "Heart Failure, Diastolic",
    "C2183328": "diastolic congestive heart failure",
    "C1135191": "Heart Failure, Systolic",
    "C0278678": "Metastatic Renal Cell Cancer",
    "C0017125": "Gastric Bypass",
    "C0021641": "Insulin",
}


def invert(children: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    """child -> parents, from the artifact's parent -> children map."""
    parents: dict[str, list[str]] = {}
    for parent, kids in children.items():
        for child in kids:
            parents.setdefault(child, []).append(parent)
    return parents


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--edges", type=Path, default=facets.DEFAULT_EDGES)
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--max-fanout", type=int, default=100)
    parser.add_argument(
        "--declare",
        action="append",
        metavar="NAME:CUI",
        default=[],
        help="add a hierarchy-isolate candidate for one phenotype (residual "
        "analysis route); it still requires a vetting verdict to be admitted",
    )
    parser.add_argument("--phenotype", action="extend", nargs="*", metavar="NAME", default=None)
    parser.add_argument(
        "--out", type=Path, default=Path("src/robustehr/resources/phenotype_closure.yaml")
    )
    args = parser.parse_args(argv)

    isa = hierarchy.load(args.isa)
    up = invert(isa.children)
    down = isa.children
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    edges = facets.load(args.edges)
    definitions = load_definitions()
    names = args.phenotype or sorted(definitions)
    built = {p.name: p for p in build(names, isa, code_to_cuis, cui_to_codes)}
    vetting = facets.load_vetting()
    declares: dict[str, list[str]] = {}
    for spec in args.declare:
        pheno, _, cui = spec.partition(":")
        if pheno not in definitions or not cui.startswith("C"):
            parser.error(f"--declare {spec!r}: expected <phenotype>:<CUI>")
        declares.setdefault(pheno, []).append(cui)

    rows: dict[str, dict] = {}
    print(
        f"{'phenotype':<28} {'members':>7} {'cand':>6} {'kept':>6} {'supp=1':>7}  motivating",
        file=sys.stderr,
    )
    for name in names:
        members = built[name].concept_cuis
        seed_cuis = frozenset(
            c for code in definitions[name].seeds for c in code_to_cuis.get(code, ())
        )
        disorder_full = build([name], isa, code_to_cuis, cui_to_codes, facets=False)[0].concept_cuis
        # Medication members: parents only, and never the identity variants.
        medication = facets.medications(
            seed_cuis,
            disorder_full,
            edges,
            declared=definitions[name].medication_seeds,
            vetted=vetting.get(name, {}).get("medication"),
        )
        med_identity = {c for c, t in medication.provenance.items() if t == "identity"}
        # Siblings from the disorder top region and the small non-medication
        # facets; parents from everything except identity variants. See the
        # docstring for the measured volume rationale.
        top_disorder = frozenset(isa.descendants(*seed_cuis, max_depth=1)) & members
        extra_nonmed = members - disorder_full - medication.cuis
        sibling_sources = seed_cuis | top_disorder | extra_nonmed

        support: Counter[str] = Counter()
        via: dict[str, list[str]] = {}
        as_parent: set[str] = set()

        def reach(member: str, candidate: str, parent_hop: bool = False) -> None:
            if candidate in members or candidate == member:
                return
            support[candidate] += 1
            if parent_hop:
                as_parent.add(candidate)
            if len(via.setdefault(candidate, [])) < 5:
                via[candidate].append(member)

        for member in sorted(sibling_sources):
            for parent in up.get(member, ()):
                reach(member, parent, parent_hop=True)
                if len(down.get(parent, ())) <= args.max_fanout:
                    for sibling in down.get(parent, ()):
                        reach(member, sibling)
        parent_only = (members - med_identity) - sibling_sources
        for member in sorted(parent_only):
            for parent in up.get(member, ()):
                reach(member, parent, parent_hop=True)

        kept = as_parent | {c for c, n in support.items() if n >= args.min_support}
        singles = sum(1 for c, n in support.items() if n == 1 and c not in as_parent)
        candidates = {
            cui: {
                "source": "lift",
                "hop": "parent" if cui in as_parent else "sibling",
                "support": support[cui],
                "via": sorted(via[cui]),
            }
            for cui in sorted(kept)
        }
        for cui in declares.get(name, []):
            if cui not in members:
                candidates.setdefault(cui, {"source": "residual", "support": 0, "via": []})
        hits = sorted(c for c in MOTIVATING if c in candidates)
        rows[name] = {
            "members": len(members),
            "candidates_any_support": len(support),
            "candidates": candidates,
        }
        print(
            f"{name:<28} {len(members):>7} {len(support):>6} {len(kept):>6} {singles:>7}  "
            f"{','.join(hits) or '—'}",
            file=sys.stderr,
        )

    payload = {
        "schema_version": "1.0",
        "what": (
            "closure candidates: the bounded one-hop neighborhood of each "
            "phenotype's concept set over the isa+MTH-RN hierarchy. CANDIDATES "
            "ONLY — nothing here is admitted to any set without a vetting "
            "verdict (phenotype_vet.py --facet closure) and clinician review."
        ),
        "method": (
            "for every non-medication member: parents (up 1) and their "
            "children (down 1, the siblings). For medication members outside "
            "the identity tier: parents only — a drug's siblings are the rest "
            "of its class, which the MED-RT treatment relation deliberately "
            "did not assert. Candidates already in the set are excluded."
        ),
        "min_support": args.min_support,
        "hierarchy": str(args.isa),
        "licence": "identifiers and counts only; no UMLS string appears here",
        "phenotypes": rows,
    }
    import yaml

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True, width=88), encoding="utf-8"
    )
    total = sum(len(r["candidates"]) for r in rows.values())
    print(f"\n{total} candidates over {len(rows)} phenotypes -> {args.out}", file=sys.stderr)
    for cui, label in MOTIVATING.items():
        where = sorted(n for n, r in rows.items() if cui in r["candidates"])
        print(f"  {cui} ({label}): {', '.join(where) or 'NOT GENERATED'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
