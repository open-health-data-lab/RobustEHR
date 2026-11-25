#!/usr/bin/env python
"""How many concepts the RUNTIME annotator actually carries per phenotype.

This is the set ``--target pheno=`` selects and the set `index_document` tests
membership against — the denominator of every coverage number. It is a separate
artifact from `phenotype_set_audit.json` because the two have disagreed before,
and the disagreement was the finding: the audit counted faceted sets that
``build()`` never loaded, so hypertension audited at 635 concepts and ran with
361, and hfpef ran with 8. Table 2 renders both columns precisely so that gap
cannot hide again.

Since ``build(..., facets=True)`` became the default, the runtime set equals
the audited union whenever the facet artifacts are present — and this artifact
is the proof, regenerated rather than asserted. On an install without
`data/umls_facets.json` the runtime honestly falls back to the disorder
closure, which is why the two files still exist separately.

Replaces the throwaway snippet this file used to point readers at.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

from robustehr.concepts import facets, hierarchy
from robustehr.concepts.phenotype import build, load_definitions, load_maps


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/phenotype_runtime_sets.json")
    )
    args = parser.parse_args(argv)

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    names = sorted(load_definitions())
    built = build(names, isa, code_to_cuis, cui_to_codes)

    payload = {
        "question": "how many concepts does the RUNTIME annotator actually carry per phenotype?",
        "method": (
            "concepts.phenotype.build with its defaults: seed codes expanded "
            "through the SNOMED isa union MTH RN hierarchy, plus the medication "
            "facet with its RxNorm identity variants, the finding, vetting-gated "
            "proposed and strict-gated closure facets (facets=True is the "
            "default since the Table 2 audit found them built and never loaded). "
            "This is the set --target pheno= selects and the set index_document "
            "tests against."
        ),
        "facets_loaded": facets.DEFAULT_EDGES.exists(),
        "generated_by": "validation/phenotype/scripts/phenotype_runtime_sets.py",
        "runtime_set_size": {p.name: len(p.concept_cuis) for p in built},
        "by_facet": {p.name: dict(p.facet_sizes) for p in built if p.facet_sizes},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    width = max(len(n) for n in names)
    for p in built:
        print(f"{p.name:<{width}} {len(p.concept_cuis):>6}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
