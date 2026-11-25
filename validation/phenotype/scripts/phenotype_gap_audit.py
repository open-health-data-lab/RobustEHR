"""Can the target actually find the terms a clinician would write?

`phenotype_link_audit.py` walks the chain from a declared seed to a mention and
asks where it breaks. It is a *concept-space* audit: every term it tests is one
the set already contains, so it can find a concept that is unreachable and
cannot find a concept that is missing. The question it does not ask is the one
that matters for targeting — **is there a term a clinician would write that
neither warrant catches?**

Answering it needs a term list from outside the pipeline, because a list derived
from the sets can only confirm what the sets already hold. So this takes one as
input: a file of terms per phenotype, written independently, and reports for
each whether the pipeline would produce evidence from a note containing it.

Four outcomes per term, and the distinction between them is the point:

``concept``     the matcher grounded it to a CUI in the phenotype's set
``anchor``      a declared surface form matched it; it is the diagnosis
``associated``  a declared surface matched it; it supports the diagnosis
``gap``         neither warrant produced evidence — the term is invisible

A `gap` is the failure this audit exists to surface. It means a clinician could
write that term, a reader could use it to make the call, and a perturbation
aimed at the phenotype would leave it untouched — which makes any null result
for that phenotype uninterpretable rather than reassuring.

**The term list is the study's, not the package's.** Which terms a clinician
writes depends on the corpus, the specialty and local convention, so shipping
one would be asserting a generality this package has not measured. The format is
deliberately trivial so any study can supply its own::

    # phenotype<TAB>term
    hfref\tsystolic heart failure
    hfref\tejection fraction of 25%

Usage::

    python validation/phenotype/scripts/phenotype_gap_audit.py --terms my_terms.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from collections import defaultdict
from pathlib import Path

from robustehr.concepts import hierarchy
from robustehr.concepts.matcher import ConceptMatcher, index_present
from robustehr.concepts.phenotype import build, index_document, load_definitions, load_maps
from robustehr.document import Document

DEFAULT_INDEX = Path("data/quickumls_index")
DEFAULT_MEASUREMENT = Path("validation/measurements/phenotype_gap_audit.json")

#: Wrapped in a sentence rather than matched bare.
#:
#: The matcher is not context-free: segmentation, the section layer and the
#: affix trimmer all behave differently on a fragment than on a clause, and a
#: term audited bare would be scored under conditions no note reproduces. The
#: carrier is deliberately bland so it contributes no clinical content of its
#: own — and it is checked for that at startup, since a carrier that itself
#: matched a phenotype would silently pass every term.
CARRIER = "The patient has a documented history of {term} noted on admission."


def load_terms(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if not row or row[0].lstrip().startswith("#") or len(row) < 2:
                continue
            name, term = row[0].strip(), row[1].strip()
            if name and term:
                out[name].append(term)
    return dict(out)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--terms", type=Path, required=True)
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--measurement", type=Path, default=DEFAULT_MEASUREMENT)
    parser.add_argument("--show-gaps", type=int, default=12)
    args = parser.parse_args(argv)

    if not index_present(args.index):
        print(f"no QuickUMLS index at {args.index}", file=sys.stderr)
        return 2

    by_phenotype = load_terms(args.terms)
    definitions = load_definitions()
    unknown = [n for n in by_phenotype if n not in definitions]
    if unknown:
        print(f"unknown phenotype(s) in term file: {unknown}", file=sys.stderr)
        return 2

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    names = sorted(by_phenotype)
    phenotypes = build(names, isa, code_to_cuis, cui_to_codes)
    by_name = {p.name: p for p in phenotypes}
    matcher = ConceptMatcher(args.index)

    # A carrier that itself produced evidence would mark every term reachable.
    control = Document.from_text(CARRIER.format(term="something"), uid="carrier")
    if len(index_document(matcher.annotate(control.text), phenotypes, text=control.text)):
        print("the carrier sentence produces evidence on its own; fix CARRIER", file=sys.stderr)
        return 2

    results: dict[str, dict[str, object]] = {}
    for name in names:
        counts: dict[str, int] = defaultdict(int)
        gaps: list[str] = []
        for term in by_phenotype[name]:
            text = CARRIER.format(term=term)
            doc = Document.from_text(text, uid="audit")
            index = index_document(matcher.annotate(text), [by_name[name]], text=text)
            tiers = {e.tier for e in index.evidence if e.phenotype == name}
            if not tiers:
                counts["gap"] += 1
                gaps.append(term)
            elif "anchor" in tiers:
                counts["anchor"] += 1
            elif tiers == {"associated"}:
                counts["associated"] += 1
            else:
                counts["concept"] += 1
            del doc
        total = len(by_phenotype[name])
        results[name] = {
            "terms": total,
            "by_warrant": dict(sorted(counts.items())),
            "reachable": total - counts["gap"],
            "reach": round((total - counts["gap"]) / total, 4) if total else None,
            "gaps": gaps,
        }
        reach = results[name]["reach"]
        print(
            f"  {name:32s} {total - counts['gap']:4d}/{total:<4d} "
            f"reach={reach if reach is not None else '-'}  "
            f"anchor={counts['anchor']} assoc={counts['associated']} "
            f"concept={counts['concept']} GAP={counts['gap']}"
        )
        for term in gaps[: args.show_gaps]:
            print(f"        gap: {term}")

    terms_total = sum(len(v) for v in by_phenotype.values())
    gaps_total = sum(int(r["by_warrant"].get("gap", 0)) for r in results.values())  # type: ignore[union-attr]
    payload = {
        "what": (
            "whether the target produces evidence from a note containing each term of "
            "an independently written clinical lexicon, and by which warrant"
        ),
        "terms_file": str(args.terms),
        "carrier": CARRIER,
        "terms": terms_total,
        "gaps": gaps_total,
        "reach": round((terms_total - gaps_total) / terms_total, 4) if terms_total else None,
        "per_phenotype": results,
    }
    args.measurement.parent.mkdir(parents=True, exist_ok=True)
    args.measurement.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\n{terms_total - gaps_total}/{terms_total} reachable ({payload['reach']})")
    print(args.measurement)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
