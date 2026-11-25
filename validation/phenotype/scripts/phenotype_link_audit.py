#!/usr/bin/env python
"""Does every declared phenotype actually have concepts linked to it?

**Why a non-empty concept set is not the question.** A phenotype is declared as a
SNOMED seed and expanded to its descendant closure, so "does it have concepts"
has a trivially reassuring answer: nearly every one expands to hundreds. That
number is worth almost nothing on its own. A set of concepts the matcher can never emit is
functionally the empty set, and it fails *silently* — the run reports
``evidence_touch: 0``, which reads exactly like a note that never mentioned the
phenotype. `heart_failure` is the worked example: 161 concepts, and a measured
set recall of 0.449, because the concepts are there and the surfaces are not.

So the chain from a declaration to a mention is checked link by link, and each
link can break in its own way:

======  ==========================  ==================================
link    breaks when                 consequence
======  ==========================  ==================================
seed    the code carries no CUI     the phenotype is empty; total
                                    silence, no error
closure the CUI is a hierarchy      the set is the seed alone, so only
        leaf or absent from it      the exact term is ever evidence
surface a set CUI has no English    that concept is unreachable by any
        string in the release       text; it inflates the set size and
                                    contributes nothing
match   a set CUI has a string the  the ceiling case — a note names the
        matcher cannot recover      concept outright and we still miss
======  ==========================  ==================================

**The last link is the interesting one, and it is measured by asking the
concept's own name.** For every concept in the set we take its preferred English
string, run the real matcher over it, and ask whether what comes back is *in the
set*. A second probe uses the shortest English string, and the two disagree often
enough to be worth reporting separately.

**What self-name reachability is, and what it is not.** It is *necessary*: a
concept the matcher cannot recover from its own preferred term will not be
recovered from prose. It is emphatically **not** an estimate of
``measured_set_recall``, and the audit's own output is the proof. Every concept
in a set counts once here, while real evidence is dominated by a handful of
common ones, so the two diverge in **both** directions:

* ``chronic_kidney_disease`` — reachability 0.349, recall 0.889. The tail of the
  set is stage- and cause-qualified concepts whose names match poorly, and
  almost no note writes them; the notes write "CKD", which resolves to the seed.
* ``heart_failure`` — reachability 0.863, recall 0.449. The mirror image, and
  the one that matters: the concepts are reachable *by their own names*, and the
  surfaces clinicians actually type are not. That is the abbreviation gap the
  definition's note describes, now located precisely — not a missing concept, a
  missing surface.

Read this audit for **broken links**, and ``measured_set_recall`` for how much of
a phenotype's evidence a run will find. Neither substitutes for the other.

**Set membership, not linking.** A probe that returns a *different* CUI which is
still inside the set is a success, because phenotype evidence is set membership
(``concepts/phenotype.py``). The stricter same-CUI rate is reported beside it as
``found_exact`` so the two are never conflated.

**Licence.** Reads MRCONSO from the local release; emits identifiers and counts
only. No UMLS string reaches the artifact.

Exit code is non-zero when any phenotype breaks a link, so this is usable as a
gate when a new phenotype is declared — see
``validation/methodology/17-phenotype-association-method.md``.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

from robustehr.concepts import hierarchy
from robustehr.concepts.phenotype import declare, load_definitions, load_maps

#: MRCONSO columns used. The file has no header; these are its documented
#: positions in the 2026AA release.
CUI, LAT, TS, STT, ISPREF, SUI, STR, SUPPRESS = 0, 1, 2, 4, 6, 5, 14, 16

#: How many unreachable identifiers to name per phenotype. CUIs may ship; the
#: strings behind them may not, so a reader takes these to `robustehr concepts`
#: against their own release rather than reading them here.
EXAMPLE_LIMIT = 10

#: Preferred string, shortest string, and atom count — each keyed by CUI.
Surfaces = tuple[dict[str, str], dict[str, str], dict[str, int]]


def collect_strings(mrconso: Path, wanted: frozenset[str]) -> Surfaces:
    """Preferred and shortest English string per wanted CUI, plus a string count.

    One pass, filtered to the union of every phenotype's set, because MRCONSO is
    2.3 GB and the sets together are a few thousand concepts.

    "Preferred" is UMLS's own answer where it gives one — ``TS=P``, ``STT=PF``,
    ``ISPREF=Y`` — falling back to the lowest SUI so a concept without a marked
    preferred term still gets a deterministic probe rather than an arbitrary one.
    Suppressible atoms are skipped: they are suppressed in the index too, so
    probing with one would measure a string the matcher was never given.
    """
    preferred: dict[str, tuple[int, str, str]] = {}
    shortest: dict[str, tuple[int, str, str]] = {}
    counts: dict[str, int] = defaultdict(int)
    with mrconso.open(encoding="utf-8") as handle:
        for line in handle:
            row = line.split("|")
            cui = row[CUI]
            if cui not in wanted or row[LAT] != "ENG" or row[SUPPRESS] != "N":
                continue
            text = row[STR].strip()
            if not text:
                continue
            counts[cui] += 1
            # Rank 0 is UMLS's preferred atom; rank 1 is everything else, so the
            # SUI tie-break only decides among equals.
            rank = 0 if (row[TS] == "P" and row[STT] == "PF" and row[ISPREF] == "Y") else 1
            key = (rank, row[SUI], text)
            if cui not in preferred or key < preferred[cui]:
                preferred[cui] = key
            short = (len(text), text, row[SUI])
            if cui not in shortest or short < shortest[cui]:
                shortest[cui] = (len(text), text, row[SUI])
    return (
        {c: v[2] for c, v in preferred.items()},
        {c: v[1] for c, v in shortest.items()},
        dict(counts),
    )


def probe(
    matcher: Any, strings: dict[str, str], members: frozenset[str], full: bool = False
) -> dict[str, Any]:
    """Run the matcher over each concept's own name; is the answer in the set?

    ``found_in_set`` is the number that bounds evidence recovery, because
    membership is what phenotype evidence tests. ``found_exact`` is the stricter
    linking rate and is reported so a reader cannot mistake one for the other.

    ``full`` writes the COMPLETE unreachable list instead of examples, so a
    downstream join (the corpus-coverage report splits unobserved concepts into
    reachable-but-unseen vs unreachable) has the whole roster. CUIs ship;
    the strings behind them stay local either way.
    """
    in_set = exact = anything = 0
    missed: list[str] = []
    for cui in sorted(members):
        text = strings.get(cui)
        if text is None:
            continue
        returned = {m.cui for m in matcher.annotate(text).mentions}
        if returned:
            anything += 1
        if returned & members:
            in_set += 1
        else:
            missed.append(cui)
        if cui in returned:
            exact += 1
    probed = sum(1 for c in members if c in strings)
    row = {
        "probed": probed,
        "found_anything": anything,
        "found_in_set": in_set,
        "found_exact": exact,
        "rate_in_set": round(in_set / probed, 4) if probed else None,
        "rate_exact": round(exact / probed, 4) if probed else None,
        "unreachable_examples": missed[:EXAMPLE_LIMIT],
    }
    if full:
        row["unreachable_cuis"] = missed
    return row


def audit_one(
    declaration: tuple[Any, set[str], list[str], Any],
    surfaces: Surfaces,
    matcher: Any,
    full: bool = False,
) -> dict[str, Any]:
    """One phenotype's four links, and which of them are broken."""
    definition, seed_cuis, unresolved, phenotype = declaration
    preferred, shortest, string_counts = surfaces
    members = phenotype.concept_cuis
    with_string = sum(1 for c in members if c in preferred)
    row: dict[str, Any] = {
        "seed_codes": list(definition.seeds),
        "seed_cuis": sorted(seed_cuis),
        "seed_codes_unresolved": unresolved,
        "set_size_cuis": len(members),
        "set_size_codes": len(phenotype.concept_codes),
        "expanded_beyond_seed": len(members) > len(seed_cuis),
        "cuis_with_an_english_string": with_string,
        "surface_coverage": round(with_string / len(members), 4) if members else None,
        "atoms_total": sum(string_counts.get(c, 0) for c in members),
        "declared_measured_set_recall": definition.measured_set_recall,
    }
    if full:
        row["cuis_without_english_string"] = sorted(c for c in members if c not in preferred)
    if matcher is not None:
        row["probe_preferred_term"] = probe(matcher, preferred, members, full=full)
        row["probe_shortest_term"] = probe(matcher, shortest, members, full=full)
        pref = row["probe_preferred_term"]["rate_in_set"]
        short = row["probe_shortest_term"]["rate_in_set"]
        # Signed on purpose, and negative for five of the eight. The preferred
        # term is not the easier surface: UMLS preferred strings carry
        # qualifiers and parentheticals the matcher cannot absorb, while the
        # shortest atom is usually the bare clinical term. Naming this
        # "abbreviation loss" would have asserted a direction the measurement
        # contradicts.
        row["probe_delta_preferred_minus_shortest"] = (
            round(pref - short, 4) if pref is not None and short is not None else None
        )
    failures = []
    unusable = []
    probe_result = row.get("probe_preferred_term")
    if probe_result and probe_result["probed"] and not probe_result["found_in_set"]:
        # Structurally intact and functionally dead: every link holds and the
        # matcher still cannot recover ONE of the set's concepts from its own
        # preferred name. hfpef and hfref are here, and their declarations say DO
        # NOT USE. Kept apart from `links_broken` because the declaration is not
        # malformed — the exit code gates malformed declarations, and a standing
        # known-bad set must not mask a new one.
        unusable.append("the matcher recovers no concept in the set from its own name")
    if unresolved:
        failures.append("a seed code resolves to no CUI")
    if not members:
        failures.append("the concept set is empty")
    elif len(members) <= len(seed_cuis):
        # Not empty, so no emptiness check catches it — but only the exact seed
        # term is ever evidence, and the phenotype has quietly degraded into a
        # single-concept lookup.
        failures.append("the closure added nothing to the seeds")
    if not with_string:
        failures.append("no concept in the set has an English string")
    row["links_broken"] = failures
    row["unusable"] = unusable
    return row


def report(rows: dict[str, Any], probed: bool) -> None:
    width = max(len(n) for n in rows)
    header = f"{'phenotype':<{width}}  {'seed':>4} {'CUIs':>6} {'surf':>6}"
    if probed:
        header += f" {'pref':>6} {'short':>6} {'delta':>7}"
    print(header + "  declared")
    for name, row in rows.items():
        line = (
            f"{name:<{width}}  {len(row['seed_cuis']):>4} {row['set_size_cuis']:>6} "
            f"{row['surface_coverage']:>6}"
        )
        if probed:
            line += (
                f" {row['probe_preferred_term']['rate_in_set']:>6}"
                f" {row['probe_shortest_term']['rate_in_set']:>6}"
                f" {row['probe_delta_preferred_minus_shortest']:>7}"
            )
        recall = row["declared_measured_set_recall"]
        line += f"  {'—' if recall is None else recall}"
        print(line)
        for failure in row["links_broken"]:
            print(f"{'':<{width}}  !! {failure}")
        for note in row.get("unusable", ()):
            print(f"{'':<{width}}  ** {note}")


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--mrconso", type=Path, default=Path("data/umls/2026AA/META/MRCONSO.RRF"))
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="skip the matcher probe; check the seed, closure and surface links only",
    )
    parser.add_argument(
        "--facets",
        action="store_true",
        help="audit the faceted RUNTIME set (concepts.phenotype.build, vetting-"
        "gated) instead of the bare disorder closure — the set every coverage "
        "denominator uses",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="write complete unreachable/no-string CUI lists, not examples, so "
        "the corpus-coverage report can split unobserved into "
        "reachable-but-unseen vs unreachable",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.out is None:
        args.out = Path(
            "validation/measurements/phenotype_link_audit_facets.json"
            if args.facets
            else "validation/measurements/phenotype_link_audit.json"
        )

    definitions = load_definitions()
    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)

    built = {}
    if args.facets:
        from robustehr.concepts.phenotype import build

        built = {p.name: p for p in build(sorted(definitions), isa, code_to_cuis, cui_to_codes)}
    expanded = {}
    for name, definition in definitions.items():
        seed_cuis = {c for code in definition.seeds for c in code_to_cuis.get(code, ())}
        unresolved = [c for c in definition.seeds if not code_to_cuis.get(c)]
        phenotype = built.get(name) or declare(
            name,
            definition.seeds,
            isa,
            code_to_cuis,
            cui_to_codes,
            # A phenotype's own bound wins. Auditing `pulmonary_embolism` at the
            # file-wide depth would probe the 9,712-concept blow-up its
            # declaration exists to prevent, and report reachability for a set
            # no run will ever build.
            max_depth=definition.max_depth or args.max_depth,
        )
        expanded[name] = (definition, seed_cuis, unresolved, phenotype)

    union = frozenset().union(*(p.concept_cuis for _, _, _, p in expanded.values()))
    surfaces = collect_strings(args.mrconso, union)

    matcher = None
    if not args.no_probe:
        from robustehr.concepts.matcher import ConceptMatcher

        matcher = ConceptMatcher(args.index)

    rows: dict[str, Any] = {
        name: audit_one(expanded[name], surfaces, matcher, full=args.full) for name in expanded
    }
    broken = [name for name, row in rows.items() if row["links_broken"]]
    unusable = [name for name, row in rows.items() if row["unusable"]]

    payload = {
        "question": (
            "does every declared phenotype have concepts linked to it, all the way to text?"
        ),
        "why": (
            "a non-empty concept set is not the question. A set the matcher "
            "cannot emit is functionally empty and fails silently: the run "
            "reports evidence_touch 0, which reads exactly like a note that "
            "never mentioned the phenotype."
        ),
        "links_checked": [
            "seed -> CUI",
            "CUI -> closure",
            "closure -> surface",
            "surface -> match",
        ],
        "probe": (
            "each concept's own preferred English string is fed to the real "
            "matcher; found_in_set means the answer was a member, which is what "
            "phenotype evidence tests. A shortest-string probe runs beside it, "
            "and the signed delta between them is negative for five of eight: "
            "UMLS preferred terms carry qualifiers the matcher cannot absorb, "
            "so the bare short atom is often the easier surface, not the harder."
        ),
        "reachability_is_not_recall": (
            "self-name reachability is necessary and not sufficient, and it does "
            "NOT estimate measured_set_recall. Every concept counts once here "
            "while real evidence is dominated by a few common ones, so the two "
            "diverge in both directions: chronic_kidney_disease 0.349 vs 0.889 "
            "(a poorly-matching tail no note writes), heart_failure 0.863 vs "
            "0.449 (concepts reachable by their own names, surfaces clinicians "
            "type that are not). Read this for broken links; read "
            "measured_set_recall for how much evidence a run will find."
        ),
        "membership_not_linking": (
            "a probe returning a different CUI inside the set is a success. "
            "found_exact is the stricter linking rate, reported separately."
        ),
        "licence": "identifiers and counts only; no UMLS string appears here",
        "expansion": (
            "build (faceted runtime set, vetting-gated)"
            if args.facets
            else "declare (bare disorder closure)"
        ),
        "max_depth": args.max_depth,
        "isa": str(args.isa),
        "phenotypes": rows,
        "phenotypes_with_a_broken_link": broken,
        "phenotypes_unusable": unusable,
        "broken_vs_unusable": (
            "broken means the declaration is malformed and gates the exit code. "
            "unusable means every link holds and the matcher still recovers "
            "nothing — a real set the pipeline cannot reach. Those definitions "
            "say DO NOT USE; they are kept declared so the failure stays visible "
            "and so they start working when the abbreviation resolver lands."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report(rows, probed=matcher is not None)
    print(f"\n-> {args.out}")
    if unusable:
        print(f"UNUSABLE (every link holds, matcher reaches nothing): {', '.join(unusable)}")
    if broken:
        print(f"BROKEN: {', '.join(broken)}")
        return 1
    print(
        f"every declared phenotype resolves to a non-empty, surface-bearing concept set"
        f"{'; see UNUSABLE above for the ones the matcher still cannot reach' if unusable else ''}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
