#!/usr/bin/env python
"""Export each phenotype's concept set for a clinician to read and mark up.

**The point of grounding is that a human can check it, and a CUI list cannot be
checked.** Every artifact this layer ships carries identifiers and hashes,
because that is what the UMLS licence permits us to redistribute — and it is
also unreviewable. Nobody can look at ``C0018801`` and say whether it belongs in
heart failure.

So there are two artifacts with deliberately different contents, the same split
``validation/phenotype/scripts/phenotype_vet.py`` already uses:

* **this one** — ``data/phenotype_review/<name>.tsv``, carrying the term in the
  clear beside its identifier, its facet, and where it came from. It is
  gitignored and stays under ``data/`` because it contains UMLS strings.
* **the shipped resources** — identifiers and ``surface_sha256`` only.

Review decisions come back as **CUI lists**, so the round trip is licence-safe
in both directions: strings go out to a reader who already holds a licence,
identifiers come back into the package.

**Every row says where the concept came from**, because that is what a reviewer
needs in order to spend attention well:

===========  ==========================================================
source       how it entered the set
===========  ==========================================================
closure      descendant of a declared SNOMED seed
med-rt       MED-RT ``may_treat`` / ``may_prevent``
declared     named by hand, where the vocabulary had no edge to infer
proposed     a clinical term proposed and grounded against the release
===========  ==========================================================

A ``med-rt`` row also carries its provenance tier — ``seed`` is MED-RT's own
assertion about this phenotype, ``closure`` and ``lift`` are our inference — so
a reviewer can skip what a curated source already asserted and concentrate on
what we derived. That is the same triage that took the vetting pass from 1,746
concepts to 556.

**The LLM's verdict rides along, and keeps sort first.** Where a vetting pass
has judged a concept, its ``llm_verdict`` and ``llm_reason`` appear beside it,
and the export deliberately shows the FULL candidate surface — including
concepts the model dropped — because auditing a triage means seeing both sides
of it. Rows sort model-keeps first: keeps are what SHIPS, so adjudicating them
is the mandatory pass, while the drops below them (closure drops run to the
hundreds per phenotype) need only an audit sample. Then auto-keeps a curated
source asserted, then anything unvetted. A blank ``keep`` column means the
model's verdict stands; ``y``/``n`` overrides it.
"""

from __future__ import annotations

import argparse
import csv
import warnings
from pathlib import Path
from typing import Any

from robustehr.concepts import facets, hierarchy
from robustehr.concepts.phenotype import build, load_definitions, load_maps

#: Under `data/` by design: these files carry UMLS strings.
DEFAULT_OUT = Path("data/phenotype_review")

COLUMNS = [
    "cui",
    "term",
    "facet",
    "source",
    "provenance",
    "llm_verdict",
    "llm_reason",
    "keep",
    "reviewer_note",
]

#: Reading order for a reviewer: the model's keeps first — they are what
#: SHIPS, so adjudicating them is the mandatory pass — then its drops (an
#: audit sample suffices; closure drops number in the hundreds per phenotype),
#: then what a curated source asserted without review, then the unvetted rest.
VERDICT_RANK = {"keep": 0, "drop": 1, "auto-keep": 2, "": 3}


def preferred_terms(mrconso: Path, wanted: frozenset[str]) -> dict[str, str]:
    """One English preferred term per CUI. Local only — never redistributed."""
    best: dict[str, tuple[int, str, str]] = {}
    with mrconso.open(encoding="utf-8") as handle:
        for line in handle:
            row = line.split("|")
            cui = row[0]
            if cui not in wanted or row[1] != "ENG" or row[16] != "N":
                continue
            text = row[14].strip()
            if not text:
                continue
            rank = 0 if (row[2] == "P" and row[4] == "PF" and row[6] == "Y") else 1
            key = (rank, row[5], text)
            if cui not in best or key < best[cui]:
                best[cui] = key
    return {c: v[2] for c, v in best.items()}


def rows_for(  # noqa: PLR0917 - one argument per resource the export joins
    name: str,
    definition: Any,
    maps: tuple[Any, Any, Any],
    edges: facets.FacetEdges,
    resources: tuple[dict[str, Any], dict[str, Any]],
    closure: dict[str, dict[str, Any]] | None = None,
) -> dict[str, tuple[str, str, str]]:
    """CUI -> (facet, source, provenance) for one phenotype.

    A concept reached more than one way keeps the FIRST source in this order,
    which is strongest-evidence-first: a drug MED-RT asserts is recorded as
    ``med-rt``/``seed`` even if the closure also reaches it.
    """
    isa, code_to_cuis, cui_to_codes = maps
    proposals, _vetting = resources
    out: dict[str, tuple[str, str, str]] = {}

    # `vetted=None` on purpose: the export is the review surface, and a review
    # that only shows what survived the triage cannot audit the triage. The
    # model's verdicts appear in their own column instead of silently filtering.
    medication = facets.medications(
        frozenset(c for code in definition.seeds for c in code_to_cuis.get(code, ())),
        build([name], isa, code_to_cuis, cui_to_codes, facets=False)[0].concept_cuis,
        edges,
        declared=definition.medication_seeds,
        vetted=None,
    )
    for cui, tier in sorted(medication.provenance.items()):
        # Identity variants (brands, dose forms) carry their ingredient's
        # verdict; exporting them would bury the reviewable rows under
        # formulations no one needs to judge.
        if tier == "identity":
            continue
        source = "declared" if tier == "declared" else "med-rt"
        out[cui] = ("medication", source, tier)

    for facet, cuis in sorted(proposals.get(name, {}).items()):
        for cui in sorted(cuis):
            out.setdefault(cui, (facet, "proposed", "grounded"))

    # Closure candidates: the one-hop hierarchy neighborhood, exported in full
    # (keeps AND drops) with the model's verdict beside each — the strict gate
    # means nothing ships without a verdict, and the reviewer audits both sides.
    for cui, meta in sorted((closure or {}).items()):
        out.setdefault(cui, ("closure", meta.get("source", "lift"), meta.get("hop", "declared")))

    finding = facets.findings(definition.finding_seeds, isa, code_to_cuis)
    for cui in sorted(finding.cuis):
        out.setdefault(cui, ("finding", "declared", "seed"))

    disorder = build([name], isa, code_to_cuis, cui_to_codes, facets=False)[0].concept_cuis
    for cui in sorted(disorder):
        out.setdefault(cui, ("disorder", "closure", "closure"))
    return out


def verdict_for(
    cui: str, facet_rows: list[dict[str, Any]], edges: facets.FacetEdges
) -> tuple[str, str]:
    """The model's verdict for one concept, as ``(verdict, reason)``.

    A medication verdict is taken on the ingredient and inherited by its salt
    and ester variants, mirroring `validation/phenotype/scripts/phenotype_vet.py`. ``auto-keep``
    marks a concept a curated source asserted, which was never model-reviewed.
    """
    for row in facet_rows:
        reviewed = row.get("reviewed") or {}
        if cui in reviewed:
            return reviewed[cui]["verdict"], reviewed[cui].get("reason", "")
    base = edges.ingredient(cui)
    for row in facet_rows:
        reviewed = row.get("reviewed") or {}
        if base != cui and base in reviewed:
            v = reviewed[base]
            return v["verdict"], (v.get("reason", "") + " (ingredient)").strip()
        if cui in row.get("kept", ()):
            return "auto-keep", "asserted by a curated source, not model-reviewed"
    return "", ""


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--edges", type=Path, default=facets.DEFAULT_EDGES)
    parser.add_argument("--mrconso", type=Path, default=Path("data/umls/2026AA/META/MRCONSO.RRF"))
    parser.add_argument("--phenotype", action="extend", nargs="*", metavar="NAME", default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--no-disorder",
        action="store_true",
        help="omit the disorder closure, which is large and already validated by "
        "measured_set_recall. Leaves the reviewer the facets that need judgement",
    )
    args = parser.parse_args(argv)

    # These files carry UMLS strings. Refusing to write them anywhere else is
    # the same guard the rest of the package applies to licensed content — a
    # convenience path outside data/ is how a licensed string ends up in git.
    resolved = args.out.resolve()
    if Path("data").resolve() not in resolved.parents and resolved != Path("data").resolve():
        print(
            f"refusing to write UMLS terms to {args.out}: this export carries "
            "vocabulary content and must stay under data/, which is gitignored."
        )
        return 2

    definitions = load_definitions()
    names = args.phenotype or sorted(definitions)
    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    edges = facets.load(args.edges)
    proposals = facets.load_proposals()
    vetting = facets.load_vetting()
    from robustehr.resources import load_yaml

    vetting_raw = (load_yaml("phenotype_vetting.yaml") or {}).get("phenotypes", {})
    try:
        closure_raw = (load_yaml("phenotype_closure.yaml") or {}).get("phenotypes", {})
    except FileNotFoundError:
        closure_raw = {}
    maps = (isa, code_to_cuis, cui_to_codes)

    per_phenotype = {
        name: rows_for(
            name,
            definitions[name],
            maps,
            edges,
            (proposals, vetting),
            closure_raw.get(name, {}).get("candidates", {}),
        )
        for name in names
    }
    if args.no_disorder:
        per_phenotype = {
            n: {c: v for c, v in rows.items() if v[1] != "closure"}
            for n, rows in per_phenotype.items()
        }
    union = frozenset(c for rows in per_phenotype.values() for c in rows)
    terms = preferred_terms(args.mrconso, union)

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"{'phenotype':<30}{'rows':>6}  by verdict")
    for name, rows in per_phenotype.items():
        path = args.out / f"{name}.tsv"
        facet_rows = list(vetting_raw.get(name, {}).values())
        verdicts = {cui: verdict_for(cui, facet_rows, edges) for cui in rows}
        counts: dict[str, int] = {}
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter="\t")
            writer.writeheader()
            # Model drops first, then keeps, then auto-keeps, then unvetted;
            # within a verdict, by source then facet then term, so a reviewer
            # reads comparable rows together rather than hunting for them.
            for cui, (facet, source, provenance) in sorted(
                rows.items(),
                key=lambda kv: (
                    VERDICT_RANK.get(verdicts[kv[0]][0], 3),
                    kv[1][1],
                    kv[1][0],
                    terms.get(kv[0], kv[0]).lower(),
                ),
            ):
                verdict, reason = verdicts[cui]
                counts[verdict or "unvetted"] = counts.get(verdict or "unvetted", 0) + 1
                writer.writerow(
                    {
                        "cui": cui,
                        "term": terms.get(cui, ""),
                        "facet": facet,
                        "source": source,
                        "provenance": provenance,
                        "llm_verdict": verdict,
                        "llm_reason": reason,
                        "keep": "",
                        "reviewer_note": "",
                    }
                )
        print(f"{name:<30}{len(rows):>6}  {dict(sorted(counts.items()))}")

    print(
        f"\n-> {args.out}/  (gitignored: these carry UMLS terms)\n"
        "Mark the `keep` column y/n; blank means the llm_verdict stands. Ingest\n"
        "with validation/phenotype/scripts/phenotype_review_ingest.py. Decisions come back as CUI\n"
        "lists, so nothing licensed travels in either direction."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
