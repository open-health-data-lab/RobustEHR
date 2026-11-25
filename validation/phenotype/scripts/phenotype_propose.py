#!/usr/bin/env python
"""Knowledge-first concept discovery: propose clinical terms, then ground them.

**Why the relation-first pipeline leaves holes.** `concepts/facets.py` builds a
phenotype from its seed CUI outward, traversing UMLS relations. That works for
disorders (``isa`` closure) and for medications (``MED-RT may_treat``), and it
returns *nothing at all* for procedures, laboratory results and symptoms —
because those relations do not exist. Asked for the findings of heart failure,
UMLS offers "H/O: heart failure" and a set of OMIM genetic syndromes; asked for
its investigations, it offers nothing. The audit shows the consequence as a wall
of zeros: no phenotype had a single procedure or lab concept.

**So the direction is inverted here.** A clinician does not derive "echocardiogram
belongs to heart failure" from a relation; they know it. This script asks for
that knowledge as *terms*, then maps each term onto the terminology:

    propose  ->  ground  ->  expand  ->  vet  ->  freeze

**The model proposes strings, never identifiers.** Asking a model for CUIs
produces confident, well-formed, wrong ones — `C0018801` is memorable enough to
be hallucinated. Asking for *clinical terms* plays to what it knows, and the CUI
is then resolved by exact lookup against the local release. Every identifier in
the output came from UMLS; none came from the model.

**Grounding is the measurement, not a plumbing step.** A proposed term either
matches a concept of the right semantic type or it does not, and the rate is
reported per phenotype and per facet. That number is what the manuscript can
show: it is the feasibility of building phenotype-concept associations this way,
stated as a fraction rather than asserted.

Terms that FAIL to ground are listed in full: they are not in UMLS, so they are
model output rather than vocabulary content, and they are the honest error bar
on the method. A term that DOES ground is by definition a UMLS string, so it is
stored as ``surface_sha256`` rather than in the clear — the same rule the rest
of this package applies to licensed content.

**Type-checked, but against the clinical types as a whole rather than the facet
the term was proposed under.** A concept must be clinical — a name that resolves
only to a body structure or an organism is rejected — but which facet it lands
in is decided by its semantic type, not by the question it answered. Enforcing
the proposed facet scored 8/24 on heart-failure symptoms while rejecting
*peripheral edema*, *paroxysmal nocturnal dyspnea* and *jugular venous
distension*, all of which UMLS types T033 Finding rather than T184 Sign or
Symptom. Relaxing the gate took the same run to 23/24. See :func:`assign`.

**Determinism.** The proposal is a cached LLM call; the artifact is a frozen list
of CUIs. Expansion reads the frozen file and never contacts a model, so a run is
reproducible from identifiers alone. This is the same contract as
``validation/phenotype/scripts/phenotype_vet.py``, and the same reason: an LLM may
inform what ships,
but nothing that ships depends on one being reachable.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import warnings
from pathlib import Path
from typing import Any

from robustehr import llm
from robustehr.concepts.phenotype import load_definitions

_DISORDER_TUIS = frozenset({"T047", "T048", "T049", "T050", "T037", "T046", "T020", "T019", "T191"})

#: Semantic types per facet. The facet a term is PROPOSED under is a hint, not a
#: gate — see `assign` for why.
FACET_TUIS: dict[str, frozenset[str]] = {
    "symptom": frozenset({"T184"}),
    "finding": frozenset({"T033"}),
    "procedure": frozenset({"T058", "T059", "T060", "T061", "T062", "T063", "T065"}),
    "lab_result": frozenset({"T034", "T059"}),
    "disease": _DISORDER_TUIS,
    # A proposed diagnosis is a disorder like any other; what differs is the
    # question asked, not the semantic types accepted back.
    "diagnosis": _DISORDER_TUIS,
    "medication": frozenset({"T121", "T200", "T195"}),
}

#: How many terms to ask for.
#:
#: **60, because 25 is the binding constraint on recall.** A low ceiling keeps
#: a model on the common terms rather than padding with rarities, and that is
#: true of the terms it adds LAST. It is not true of what it leaves out: asked
#: for 25 findings for
#: alcohol use disorder it returned 19, and the withdrawal syndrome — `delirium
#: tremens`, `tongue fasciculations`, `CIWA`, withdrawal seizures — was not
#: among them. The gap audit scored that phenotype at 30% and its misses were
#: almost entirely that omission.
#:
#: A ceiling cannot distinguish "the model ran out of real terms" from "the
#: model ran out of room", and only the first is a fact about the phenotype.
#: Vetting and the specificity screen both exist downstream to remove what does
#: not belong, so the cost of asking for too many is a longer review and the
#: cost of asking for too few is silent and unmeasurable.
WANTED = 60

PROMPT = """You are building a concept list for a clinical phenotype, for use in
information-extraction research on hospital notes.

PHENOTYPE: {label}
CATEGORY: {facet}

{criterion}

List every term that genuinely belongs, up to {wanted}. Completeness matters
more than brevity here: a term you leave out is unreachable, while a term that
does not belong is removed by a later review. Do not stop at the obvious ones —
include the named syndromes, complications and characteristic findings a
clinician would recognise.

Rules:
- Use the term a clinician would WRITE IN A NOTE, in its canonical form.
- Prefer common, specific terms over rare or generic ones.
- One term per line, no numbering, no explanation, no abbreviations in
  parentheses. Write the full form: "shortness of breath", not "SOB".
{exclusion}
- Do not invent terms to reach the limit. If the phenotype genuinely has
  fewer, list fewer — but exhaust what it has first."""

#: Every facet but one is asking what ACCOMPANIES the phenotype, so naming the
#: phenotype is padding. `diagnosis` asks the opposite question and the same
#: line would forbid the only answers it wants.
EXCLUDE_SELF = "- Do NOT include the phenotype's own name or its synonyms."
INCLUDE_SELF = (
    "- The phenotype's own names ARE what is wanted here. Include them.\n"
    "- Do NOT include symptoms, findings, drugs, tests or complications."
)

CRITERION = {
    "symptom": (
        "List the SIGNS AND SYMPTOMS a patient with this phenotype reports or "
        "the clinician observes — what appears in a history or examination."
    ),
    "finding": (
        "List the CLINICAL FINDINGS associated with this phenotype that are "
        "neither a named disease nor a simple symptom — examination findings, "
        "observations, qualified states."
    ),
    "procedure": (
        "List the PROCEDURES, TESTS AND INVESTIGATIONS used to diagnose, "
        "monitor or treat this phenotype."
    ),
    "lab_result": (
        "List the LABORATORY ANALYTES measured in the assessment or monitoring of this phenotype."
    ),
    "disease": "List the DISEASES that are complications, causes or close comorbidities.",
    # The gap this facet exists to close, found by the gap audit rather than
    # reasoned about. `alcohol_use_disorder` ships on SNOMED's *Harmful pattern
    # of use of alcohol*, and `alcohol dependence`, `alcohol abuse`, `alcohol
    # withdrawal syndrome` and `delirium tremens` each ground to a real CUI that
    # is in no branch the seed reaches. Nothing proposed them either: every
    # other facet asks what ACCOMPANIES the phenotype and the prompt forbids
    # naming it. So the words a note actually uses for that condition were
    # reachable by neither warrant, and the phenotype scored 24% against a
    # held-out term list.
    #
    # This is a third kind of gap, distinct from the two already handled. A term
    # with no CUI is recovered as a surface; a term whose CUI the hierarchy
    # connects is reached by the closure. A term whose CUI EXISTS but sits in
    # another branch falls between them, and only asking for it finds it.
    "diagnosis": (
        "List the OTHER NAMES AND NEAR-EQUIVALENT DIAGNOSES a clinician would "
        "write in a note to record this same condition: alternative names, "
        "superseded names the record still carries, named subtypes, and "
        "conditions a coder would treat as this phenotype. A distinct disease "
        "that merely co-occurs is NOT one of these."
    ),
    "medication": "List the DRUGS used to treat or prevent this phenotype.",
}


#: Assignment order, identical to the exclusive partition in
#: `validation/phenotype/scripts/phenotype_set_audit.py` so the two artifacts agree.
ASSIGN_ORDER = [
    "disease",
    "finding",
    "symptom",
    "medication",
    "procedure",
    "lab_result",
]


def assign(tuis: frozenset[str]) -> str | None:
    """Which facet a grounded concept actually belongs to, by its semantic type.

    **The facet a term was proposed under is a hint, and enforcing it was wrong.**
    The first pass required a term proposed as a ``symptom`` to carry T184, and
    scored 8/24 on heart failure — but the rejects were *peripheral edema*,
    *paroxysmal nocturnal dyspnea*, *jugular venous distension*. Those are
    correct, useful concepts; UMLS simply types them T033 Finding. The mirror
    case appeared in the same run: *abdominal tenderness* and *rebound
    tenderness*, proposed as findings, are typed T184.

    The T184/T033 boundary is not one clinical knowledge tracks, and UMLS itself
    applies it inconsistently. Rejecting on it discarded a third of the
    proposals and measured our own gate rather than the method. So a term is
    grounded into **any** clinical type and assigned by what it turns out to be;
    ``proposed_as`` and ``assigned_to`` are both recorded, and their
    disagreement is a reportable quantity rather than a loss.
    """
    for facet in ASSIGN_ORDER:
        if FACET_TUIS[facet] & tuis:
            return facet
    return None


def normalise(text: str) -> str:
    """Lowercase, strip punctuation and collapse space — both sides matched alike.

    Deliberately blunt. A looser normaliser (stemming, stopword removal) raises
    the match rate by matching things that are not the same concept, which is
    the one error this pipeline cannot detect downstream: a wrongly grounded
    term looks exactly like a correctly grounded one.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def propose(config: Any, label: str, facet: str, wanted: int = WANTED) -> list[str]:
    """Ask for the terms. Returns [] when the model is unreachable."""
    prompt = PROMPT.format(
        label=label,
        facet=facet,
        criterion=CRITERION[facet],
        wanted=wanted,
        exclusion=INCLUDE_SELF if facet == "diagnosis" else EXCLUDE_SELF,
    )
    try:
        reply = llm.complete(config, prompt)
    except llm.LlmUnavailable as exc:
        print(f"    unavailable: {exc}", file=sys.stderr)
        return []
    terms = []
    for line in reply.splitlines():
        text = line.strip().lstrip("-*0123456789. ").strip()
        if text and len(text) > 2 and not text.endswith(":"):
            terms.append(text)
    return terms[:WANTED]


def ground(
    mrconso: Path, mrsty: Path, wanted: frozenset[str]
) -> tuple[dict[str, list[str]], dict[str, frozenset[str]]]:
    """Normalised term -> CUIs, and CUI -> TUIs, in two passes over the release."""
    surface: dict[str, list[str]] = {}
    with mrconso.open(encoding="utf-8") as handle:
        for line in handle:
            row = line.split("|")
            if row[1] != "ENG" or row[16] != "N":
                continue
            key = normalise(row[14])
            if key in wanted:
                surface.setdefault(key, []).append(row[0])
    cuis = {c for v in surface.values() for c in v}
    types: dict[str, set[str]] = {}
    with mrsty.open(encoding="utf-8") as handle:
        for line in handle:
            cui, tui = line.split("|", 2)[:2]
            if cui in cuis:
                types.setdefault(cui, set()).add(tui)
    return (
        {k: sorted(set(v)) for k, v in surface.items()},
        {c: frozenset(t) for c, t in types.items()},
    )


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0912, PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mrconso", type=Path, default=Path("data/umls/2026AA/META/MRCONSO.RRF"))
    parser.add_argument("--mrsty", type=Path, default=Path("data/umls/2026AA/META/MRSTY.RRF"))
    parser.add_argument("--phenotype", action="extend", nargs="*", metavar="NAME", default=None)
    parser.add_argument(
        "--facet", action="extend", nargs="*", default=None, choices=sorted(FACET_TUIS)
    )
    parser.add_argument(
        "--wanted",
        type=int,
        default=WANTED,
        help="terms to ask for per phenotype-facet. A ceiling cannot tell a "
        "model running out of real terms from one running out of room",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("src/robustehr/resources/phenotype_proposals.yaml")
    )
    args = parser.parse_args(argv)

    if not os.environ.get(llm.MODEL_ENV):
        print(f"Set {llm.MODEL_ENV} and OPENROUTER_API_KEY; no model ships.", file=sys.stderr)
        return 2
    config = llm.configure()

    definitions = load_definitions()
    names = args.phenotype or sorted(definitions)
    wanted_facets = args.facet or ["diagnosis", "symptom", "finding", "procedure", "lab_result"]

    proposed: dict[str, dict[str, list[str]]] = {}
    for name in names:
        proposed[name] = {}
        for facet in wanted_facets:
            terms = propose(config, definitions[name].label, facet, args.wanted)
            proposed[name][facet] = terms
            print(f"  {name}/{facet}: {len(terms)} proposed", file=sys.stderr)

    every = frozenset(
        normalise(t) for f in proposed.values() for terms in f.values() for t in terms
    )
    print(f"\ngrounding {len(every)} distinct terms against the release", file=sys.stderr)
    surface, types = ground(args.mrconso, args.mrsty, every)

    rows: dict[str, Any] = {}
    totals = {"proposed": 0, "grounded": 0, "not_clinical": 0, "unmatched": 0, "reassigned": 0}
    drift: dict[str, int] = {}
    for name in names:
        rows[name] = {}
        for facet in wanted_facets:
            grounded: dict[str, dict[str, str]] = {}
            not_clinical: list[str] = []
            unmatched: list[str] = []
            for term in proposed[name][facet]:
                candidates = surface.get(normalise(term), [])
                if not candidates:
                    unmatched.append(term)
                    continue
                # Prefer a concept in the proposed facet; otherwise take the
                # first that is clinical at all, and record where it landed.
                same = [c for c in candidates if FACET_TUIS[facet] & types.get(c, frozenset())]
                pool = same or [c for c in candidates if assign(types.get(c, frozenset()))]
                if not pool:
                    not_clinical.append(term)
                    continue
                # Lowest CUI among equals: deterministic, and the choice was
                # arbitrary anyway.
                cui = min(pool)
                landed = assign(types.get(cui, frozenset())) or facet
                grounded[term] = {
                    "cui": cui,
                    "assigned_to": landed,
                    # The term is stored as a digest, not in the clear. A term
                    # that GROUNDS is by definition a string present in UMLS, so
                    # shipping it would redistribute vocabulary content however
                    # ordinary the words look. Terms that fail to ground are not
                    # in UMLS and are kept readable — they are the error bar, and
                    # they are the ones a reader needs to see.
                    "surface_sha256": hashlib.sha256(term.encode("utf-8")).hexdigest()[:16],
                }
                if landed != facet:
                    totals["reassigned"] += 1
                    drift[f"{facet} -> {landed}"] = drift.get(f"{facet} -> {landed}", 0) + 1
            rows[name][facet] = {
                "proposed": len(proposed[name][facet]),
                "grounded": len(grounded),
                "grounding_rate": round(len(grounded) / len(proposed[name][facet]), 3)
                if proposed[name][facet]
                else None,
                "cuis_by_assigned_facet": {
                    f: sorted({v["cui"] for v in grounded.values() if v["assigned_to"] == f})
                    for f in sorted({v["assigned_to"] for v in grounded.values()})
                },
                "grounded_concepts": [
                    {k: v for k, v in sorted(entry.items())}
                    for entry in sorted(grounded.values(), key=lambda e: e["cui"])
                ],
                "terms_not_clinical": sorted(not_clinical),
                "terms_unmatched": sorted(unmatched),
            }
            totals["proposed"] += len(proposed[name][facet])
            totals["grounded"] += len(grounded)
            totals["not_clinical"] += len(not_clinical)
            totals["unmatched"] += len(unmatched)

    payload = {
        "schema_version": "1.0",
        "what": (
            "clinical terms proposed by a model and GROUNDED against the local "
            "UMLS release. The model supplied strings; every identifier here "
            "came from UMLS. A grounded term is by definition a UMLS string and "
            "is stored as surface_sha256, not in the clear. Terms that failed to "
            "ground are NOT in UMLS and are listed readable — they are the "
            "method's error bar and a reader needs to see them."
        ),
        "why": (
            "UMLS has no disease->symptom, disease->procedure or disease->analyte "
            "relation to traverse, so the relation-first expansion in "
            "concepts/facets.py returns zero for those facets on every "
            "phenotype. Knowledge names them; the terminology grounds them."
        ),
        "grounding": (
            "a term matches on normalised surface form and must carry SOME "
            "clinical semantic type. The facet it was proposed under is a hint, "
            "not a gate: enforcing it rejected peripheral edema and paroxysmal "
            "nocturnal dyspnea as symptoms because UMLS types them T033, and "
            "abdominal tenderness as a finding because UMLS types it T184. "
            "`assigned_to` records where each concept actually landed and "
            "`facet_drift` totals the disagreement, which is a property of the "
            "T184/T033 boundary rather than an error by either side."
        ),
        "facet_drift": dict(sorted(drift.items())),
        "model": llm.provenance(config).get("model"),
        "vetted_by": "llm-proposed, terminology-grounded, not clinician-reviewed",
        "totals": totals,
        "grounding_rate": round(totals["grounded"] / totals["proposed"], 4)
        if totals["proposed"]
        else None,
        "phenotypes": rows,
    }
    import yaml

    # MERGE, do not replace. `--facet` runs one facet at a time and the output
    # is keyed by phenotype then facet, so writing `rows` alone deletes every
    # facet this invocation did not ask for. That is silent and total: running
    # `--facet diagnosis` against a file holding four facets left one, and the
    # loss only surfaced two steps later when the vetting pass recomputed its
    # kept lists against candidates that no longer existed.
    #
    # Totals are recomputed over the merged file rather than carried from this
    # run, or `grounding_rate` would describe whichever facet went last.
    if args.out.exists():
        prior = yaml.safe_load(args.out.read_text(encoding="utf-8")) or {}
        merged: dict[str, Any] = dict(prior.get("phenotypes", {}))
        for name, facets in rows.items():
            for facet, block in facets.items():
                # UNION the grounded concepts rather than replacing them.
                #
                # A re-proposal is a fresh generation, so the model returns a
                # different list even for the same facet — and replacing meant a
                # concept proposed last time, grounded, and VETTED silently
                # stopped being a candidate. Vetting recomputes `kept` against
                # current candidates by design, so it then dropped from the
                # shipped set with no verdict having changed. Raising the term
                # ceiling lost 180 concepts that way while adding 1,014, and the
                # only visible trace was union recall falling while the set grew.
                #
                # Verdicts in this package are frozen and re-runs decide only
                # what is new. A candidate pool that churns underneath them
                # breaks that guarantee, so it does not churn.
                prior_block = merged.setdefault(name, {}).get(facet, {})
                prior_g = {g["cui"]: g for g in prior_block.get("grounded_concepts", ())}
                fresh_g = {g["cui"]: g for g in block.get("grounded_concepts", ())}
                union_g = {**prior_g, **fresh_g}
                by_facet: dict[str, list[str]] = {}
                for cui, g in union_g.items():
                    by_facet.setdefault(g.get("assigned_to", facet), []).append(cui)
                unmatched = sorted(
                    set(prior_block.get("terms_unmatched") or ())
                    | set(block.get("terms_unmatched") or ())
                )
                merged[name][facet] = {
                    **block,
                    "grounded_concepts": sorted(union_g.values(), key=lambda g: g["cui"]),
                    "grounded": len(union_g),
                    "cuis_by_assigned_facet": {k: sorted(v) for k, v in sorted(by_facet.items())},
                    "terms_unmatched": unmatched,
                    "proposed": max(block.get("proposed", 0), prior_block.get("proposed", 0)),
                }
        payload["phenotypes"] = merged
        summed = {"proposed": 0, "grounded": 0, "not_clinical": 0, "unmatched": 0, "reassigned": 0}
        for facets in merged.values():
            for block in facets.values():
                summed["proposed"] += block.get("proposed", 0)
                summed["grounded"] += block.get("grounded", 0)
                summed["unmatched"] += len(block.get("terms_unmatched") or ())
                summed["not_clinical"] += len(block.get("terms_not_clinical") or ())
        summed["reassigned"] = totals.get("reassigned", 0) + prior.get("totals", {}).get(
            "reassigned", 0
        )
        payload["totals"] = summed
        payload["grounding_rate"] = (
            round(summed["grounded"] / summed["proposed"], 4) if summed["proposed"] else None
        )
        drift_prior = prior.get("facet_drift", {})
        payload["facet_drift"] = dict(sorted({**drift_prior, **dict(drift)}.items()))

    args.out.write_text(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True, width=88), encoding="utf-8"
    )

    width = max(len(n) for n in rows)
    print(f"\n{'phenotype':<{width}} " + " ".join(f"{f[:9]:>10}" for f in wanted_facets))
    for name in names:
        cells = [
            f"{rows[name][f]['grounded']:>3}/{rows[name][f]['proposed']:<3}" for f in wanted_facets
        ]
        print(f"{name:<{width}} " + " ".join(f"{c:>10}" for c in cells))
    print(
        f"\ngrounded {totals['grounded']}/{totals['proposed']} "
        f"({payload['grounding_rate']:.1%}); {totals['reassigned']} reassigned across "
        f"facets, {totals['not_clinical']} non-clinical, {totals['unmatched']} not in UMLS"
    )
    if drift:
        print("facet drift: " + ", ".join(f"{k} {v}" for k, v in sorted(drift.items())))
    print(f"-> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
