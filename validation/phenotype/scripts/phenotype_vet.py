#!/usr/bin/env python
"""Clinical vetting of generated facet candidates, decided once and frozen.

**Why generation is not enough, in one example.** `clostridioides_difficile` has
no MED-RT treatment edge, so its medication facet lifts one `isa` step and
returns **ciprofloxacin** — a drug that *causes* C. difficile rather than
treating it. The relation is real, the traversal is correct, and the answer is
clinically wrong. No structural rule catches that: it needs a clinician, or a
model standing in for one.

So every generated candidate is a *candidate*. This pass asks a model, concept by
concept, whether it belongs, and writes the verdicts to
``src/robustehr/resources/phenotype_vetting.yaml``.

**Frozen, because an LLM is not deterministic and this package is.** The verdicts
are data, not a runtime call: expansion reads the frozen file and never contacts
a model. Re-running with the same candidates is a cache hit and changes nothing;
re-running after a seed changes re-decides only the concepts that are new. A
run's manifest can therefore name a vetting file by digest, which a live model
call could never support.

**Identifiers ship; the terms the model saw do not.** The prompt carries UMLS
preferred terms, which cannot be redistributed. What is written back is CUIs plus
a verdict, plus ``surface_sha256`` of the term so a reader can confirm they are
looking at the same concept against their own release without us shipping it.

**This is an assistant to review, not a substitute for it.** The output records
``vetted_by: llm`` and the model id. A human pass over the same file changes that
to a name, and the schema keeps them apart on purpose — a set signed by a
clinician and a set filtered by a cheap model support different claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

from robustehr import llm
from robustehr.concepts import facets, hierarchy
from robustehr.concepts.phenotype import build, load_definitions, load_maps

#: Concepts per request. Large enough to amortise the prompt, small enough that
#: one malformed reply costs little and that the model keeps the list in view.
BATCH = 40

#: Recommended for this task — cheap, and measured at rater level on the
#: assertion benchmark. Overridden by ROBUSTEHR_LLM_MODEL; no default ships.
SUGGESTED_MODEL = "google/gemini-3.6-flash"

PROMPT = """You are vetting a candidate concept set for a clinical phenotype.

PHENOTYPE: {label}
FACET: {facet}

{criterion}

For each numbered concept below, answer keep or drop.

Judge the CONCEPT, not the wording. Be strict about direction: a drug that
CAUSES the condition, is CONTRAINDICATED in it, or merely occurs in the same
patients is a drop, not a keep. A drug used for a different condition that
happens to share a mechanism is a drop.

Salt, ester and formulation variants of a kept ingredient are keeps.

Reply with one line per concept, exactly `<number>|<keep|drop>|<3-6 word reason>`.
No preamble, no numbering beyond what is given, no blank lines.

{items}"""

CRITERION = {
    "medication": (
        "Keep a concept only if it is a drug used to TREAT or PREVENT this "
        "phenotype in routine practice, or a class of such drugs."
    ),
    "finding": (
        "Keep a concept only if it is a sign, symptom or observation that is "
        "part of this phenotype's clinical presentation."
    ),
    "disorder": (
        "Keep a concept only if a clinician reading it in a note would count it "
        "as this phenotype or a subtype of it."
    ),
    # The four below judge PROPOSED concepts by their assigned facet. Each ends
    # on the same acid test: a concept true of most hospitalized patients — a
    # CBC, a chest X-ray, fatigue — associates with every phenotype at once and
    # therefore with none.
    "disease": (
        "Keep a concept only if it is this phenotype itself, a subtype of it, a "
        "characteristic complication, or a condition that is part of its typical "
        "presentation. A condition that merely co-occurs in the same patients "
        "is a drop."
    ),
    "symptom": (
        "Keep a concept only if it is a symptom or elicited sign that is part "
        "of this phenotype's presentation or of its typical complications. A "
        "finding caused by the TREATMENT of the phenotype rather than the "
        "phenotype is a drop. A symptom common to most hospitalized patients "
        "is a drop."
    ),
    "procedure": (
        "Keep a concept only if it is a procedure used to diagnose, monitor or "
        "treat this phenotype in routine practice. A procedure ordered for "
        "most hospitalized patients regardless of phenotype is a drop."
    ),
    "lab_result": (
        "Keep a concept only if it is a laboratory test or result used to "
        "diagnose or monitor this phenotype, or one characteristically "
        "abnormal in it. A panel ordered on every ICU patient regardless of "
        "phenotype is a drop."
    ),
    # Judges CLOSURE candidates — the one-hop hierarchy neighborhood of the
    # set. The question is evidential force for TARGETING, deliberately more
    # permissive than identity: the corruption experiment must hit the mention
    # a phenotype call rides on, and clinicians document hfpef as "diastolic
    # CHF" and site-specific metastases as "metastatic disease".
    "closure": (
        "Keep a concept only if a clinician reading this term in a note would "
        "take it as evidence FOR this phenotype — the phenotype itself, a "
        "subtype, a closely related variant, or a generalization specific "
        "enough that its mention in a note supports this phenotype. This is "
        "evidential force, not identity: 'congestive heart failure' is "
        "evidence for HFpEF. A concept that names a different disease, or one "
        "true of most hospitalized patients, is a drop."
    ),
}

#: Appended to every criterion above. One test, asked the same way each time.
#:
#: The criteria differ by facet because a drug and a symptom earn their place
#: differently, but they share a failure: each was written as "is this related?",
#: and relatedness is not what a targeted corruption needs. An arm that corrupts
#: a phenotype's evidence should be corrupting what a reader used to make the
#: call, and a concept that would count equally for a dozen conditions is not
#: that, however true it is of this one.
#:
#: Phrased as belief revision rather than as a list of banned categories because
#: the categories were the leak: "a generalization specific enough" and "part of
#: its typical presentation" both read as permission when the concept is a
#: plausible-sounding association, and the model had no reason to ask how many
#: OTHER phenotypes the same sentence would license.
SPECIFICITY = (
    "\n\nAPPLY THIS TEST TO EVERY CONCEPT, and it is the strictest one here.\n"
    "Imagine the term is the ONLY thing you see from the note. Ask: does it "
    "move your belief that THIS patient has THIS phenotype, specifically, and "
    "not merely that the patient is sick?\n"
    "- If the same term would count as evidence for three or more unrelated "
    "conditions, it is a drop. It discriminates nothing.\n"
    "- If the term is ordinary English whose everyday sense is not clinical, it "
    "is a drop however it is catalogued.\n"
    "- If you would need surrounding context to know whether it refers to this "
    "phenotype at all, it is a drop.\n"
    "Being genuinely associated with the phenotype is NOT sufficient. Most "
    "patients with this phenotype having the finding is NOT sufficient. The "
    "question is whether the term points HERE rather than somewhere else."
)

#: The `--facet` modes main() knows how to build candidates for. `proposed`
#: vets the grounded LLM proposals concept-by-concept under the CRITERION of
#: each concept's ASSIGNED facet; `closure` vets the one-hop hierarchy
#: neighborhood from `phenotype_closure.yaml`; the others traverse curated
#: vocabularies.
FACET_MODES = ("medication", "finding", "disorder", "proposed", "closure")


def preferred_terms(mrconso: Path, wanted: frozenset[str]) -> dict[str, str]:
    """One English preferred term per CUI, for the prompt only. Never shipped."""
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


def vet_batch(
    config: Any, label: str, facet: str, chunk: list[tuple[str, str]]
) -> dict[str, dict[str, str]]:
    """Ask for one batch of verdicts; unparseable lines leave a concept undecided.

    An undecided concept is **excluded** by the caller rather than admitted. The
    asymmetry is deliberate: a silent parse failure that admitted concepts would
    widen the set exactly where the evidence is weakest.
    """
    items = "\n".join(f"{i + 1}. {term}" for i, (_, term) in enumerate(chunk))
    prompt = PROMPT.format(
        label=label,
        facet=facet,
        criterion=CRITERION.get(facet, CRITERION["disorder"]) + SPECIFICITY,
        items=items,
    )
    try:
        reply = llm.complete(config, prompt)
    except llm.LlmUnavailable as exc:
        print(f"    LLM unavailable: {exc}", file=sys.stderr)
        return {}
    verdicts: dict[str, dict[str, str]] = {}
    for line in reply.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3 or not parts[0].rstrip(".").isdigit():
            continue
        index = int(parts[0].rstrip(".")) - 1
        if not 0 <= index < len(chunk):
            continue
        keep = parts[1].lower().startswith("keep")
        cui, term = chunk[index]
        verdicts[cui] = {
            "verdict": "keep" if keep else "drop",
            "reason": parts[2][:60],
            "surface_sha256": hashlib.sha256(term.encode("utf-8")).hexdigest()[:16],
        }
    return verdicts


def _existing_decisions(out: Path, *, revet: bool = False) -> dict[str, Any]:
    """Prior verdicts, so a re-run decides only what is new.

    ``revet`` discards them, which is what a **changed criterion** requires: the
    incremental path asks the model only about concepts it has never seen, so
    editing `CRITERION` and re-running is otherwise a no-op on every concept
    already decided under the old wording. That is the safe default — a criterion
    is usually stable and re-deciding costs money and moves a digest three
    experiments reference — but it means the one case where the wording is the
    point needs saying explicitly.
    """
    if revet or not out.exists():
        return {}
    from robustehr.resources import load_yaml

    return (load_yaml(out.name) or {}).get("phenotypes", {})


def _write_payload(out: Path, decisions: dict[str, Any], config: Any) -> None:
    payload = {
        "schema_version": "1.0",
        "what": (
            "clinical vetting of generated facet candidates. Identifiers and "
            "verdicts only; the UMLS terms the model saw are represented by "
            "surface_sha256 and are not redistributed."
        ),
        "vetted_by": "llm",
        "model": llm.provenance(config).get("model"),
        "undecided_policy": "a concept with no parseable verdict is EXCLUDED, never admitted",
        "phenotypes": decisions,
    }
    import yaml

    out.write_text(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True, width=88), encoding="utf-8"
    )
    print(f"-> {out}", file=sys.stderr)
    # A phenotype row holds facet blocks AND bookkeeping that is not a facet:
    # `clinician` records the review tally and has no `kept`. Summarising every
    # key as a facet crashed the moment the first clinician verdict was
    # ingested, after the file had already been written — so the run looked
    # like a failure while its output was fine.
    print(
        json.dumps(
            {
                k: {f: len(b["kept"]) for f, b in v.items() if isinstance(b, dict) and "kept" in b}
                for k, v in decisions.items()
            },
            indent=1,
        )
    )


def vet_proposed(args: Any, config: Any, definitions: dict[str, Any], names: list[str]) -> int:
    """Vet the grounded LLM proposals, one decision per CUI.

    Unlike the medication path there is no ingredient grouping and no seed tier:
    every proposed concept is model-generated, so every one is judged — nothing
    is auto-asserted. Each concept is judged under the CRITERION of the facet its
    semantic type ASSIGNED it to (not the facet it was proposed under), because
    the assigned facet describes what the concept is.
    """
    by_name = {n: facets.load_proposals().get(n, {}) for n in names}
    union = frozenset(
        c for by_facet in by_name.values() for cuis in by_facet.values() for c in cuis
    )
    total = sum(len(cuis) for by_facet in by_name.values() for cuis in by_facet.values())
    print(
        f"{total} proposed concepts over {len(names)} phenotypes; all are "
        "model-generated, so all are vetted",
        file=sys.stderr,
    )
    terms = preferred_terms(args.mrconso, union)

    decisions = _existing_decisions(args.out, revet=getattr(args, "revet", False))
    for name in names:
        row = decisions.setdefault(name, {})
        facet_row = row.setdefault("proposed", {})
        verdicts: dict[str, dict[str, str]] = dict(facet_row.get("reviewed", {}))
        candidates = frozenset(c for cuis in by_name[name].values() for c in cuis)
        pending_by_facet = {
            facet: sorted((c, terms[c]) for c in cuis if c in terms and c not in verdicts)
            for facet, cuis in sorted(by_name[name].items())
        }
        n_pending = sum(len(v) for v in pending_by_facet.values())
        print(
            f"  {name}: {len(candidates)} proposed concepts, {n_pending} to decide",
            file=sys.stderr,
        )
        for facet, pending in pending_by_facet.items():
            for start in range(0, len(pending), BATCH):
                verdicts |= vet_batch(
                    config, definitions[name].label, facet, pending[start : start + BATCH]
                )
        # Undecided concepts are excluded, not admitted — see vet_batch. `kept`
        # is restricted to the CURRENT candidates so a stale verdict for a
        # concept the proposals no longer carry cannot re-admit it.
        kept = sorted(c for c in candidates if verdicts.get(c, {}).get("verdict") == "keep")
        kept_set = frozenset(kept)
        facet_row.update(
            {
                "candidates": len(candidates),
                "reviewed_n": sum(1 for c in candidates if c in verdicts),
                "kept": kept,
                "by_assigned_facet": {
                    facet: len(cuis) for facet, cuis in sorted(by_name[name].items())
                },
                "kept_by_assigned_facet": {
                    facet: sum(1 for c in cuis if c in kept_set)
                    for facet, cuis in sorted(by_name[name].items())
                },
                "reviewed": {c: verdicts[c] for c in sorted(verdicts)},
            }
        )
        dropped = sum(1 for c in candidates if c in verdicts and verdicts[c]["verdict"] != "keep")
        undecided = sum(1 for c in candidates if c not in verdicts)
        print(
            f"    kept {len(kept)}, dropped {dropped}, undecided (excluded) {undecided}",
            file=sys.stderr,
        )

    _write_payload(args.out, decisions, config)
    return 0


def vet_closure(args: Any, config: Any, definitions: dict[str, Any], names: list[str]) -> int:
    """Vet the closure candidates, one decision per CUI, targeting criterion.

    Everything here is mechanical graph output, so everything is judged —
    there is no seed tier and no ingredient grouping. The kept set is
    restricted to CURRENT candidates so a stale verdict cannot re-admit a
    concept the generator no longer produces, and `_with_facets` additionally
    intersects with the candidate file at build time (strict gate).
    """
    by_name = {n: facets.load_closure().get(n, frozenset()) for n in names}
    union = frozenset(c for cuis in by_name.values() for c in cuis)
    print(
        f"{sum(len(c) for c in by_name.values())} closure candidates over "
        f"{len(names)} phenotypes; all are graph-generated, so all are vetted",
        file=sys.stderr,
    )
    terms = preferred_terms(args.mrconso, union)

    decisions = _existing_decisions(args.out, revet=getattr(args, "revet", False))
    for name in names:
        row = decisions.setdefault(name, {})
        facet_row = row.setdefault("closure", {})
        verdicts: dict[str, dict[str, str]] = dict(facet_row.get("reviewed", {}))
        candidates = by_name[name]
        pending = sorted((c, terms[c]) for c in candidates if c in terms and c not in verdicts)
        print(
            f"  {name}: {len(candidates)} candidates, {len(pending)} to decide",
            file=sys.stderr,
        )
        for start in range(0, len(pending), BATCH):
            verdicts |= vet_batch(
                config, definitions[name].label, "closure", pending[start : start + BATCH]
            )
        kept = sorted(c for c in candidates if verdicts.get(c, {}).get("verdict") == "keep")
        facet_row.update(
            {
                "candidates": len(candidates),
                "reviewed_n": sum(1 for c in candidates if c in verdicts),
                "kept": kept,
                "reviewed": {c: verdicts[c] for c in sorted(verdicts)},
            }
        )
        dropped = sum(1 for c in candidates if verdicts.get(c, {}).get("verdict") == "drop")
        undecided = sum(1 for c in candidates if c not in verdicts)
        print(
            f"    kept {len(kept)}, dropped {dropped}, undecided (excluded) {undecided}",
            file=sys.stderr,
        )

    _write_payload(args.out, decisions, config)
    return 0


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--edges", type=Path, default=facets.DEFAULT_EDGES)
    parser.add_argument("--mrconso", type=Path, default=Path("data/umls/2026AA/META/MRCONSO.RRF"))
    parser.add_argument("--phenotype", action="extend", nargs="*", metavar="NAME", default=None)
    parser.add_argument("--facet", default="medication", choices=FACET_MODES)
    parser.add_argument(
        "--out", type=Path, default=Path("src/robustehr/resources/phenotype_vetting.yaml")
    )
    parser.add_argument(
        "--revet",
        action="store_true",
        help="discard prior verdicts and decide every concept again. Needed when "
        "CRITERION changes, since the incremental path only asks about concepts "
        "never seen. Moves the vetting digest, so every corpus built against the "
        "old one becomes a different treatment and must say so",
    )
    args = parser.parse_args(argv)

    if not os.environ.get(llm.MODEL_ENV):
        print(
            f"Set {llm.MODEL_ENV} to choose a model, e.g.\n"
            f"    export {llm.MODEL_ENV}={SUGGESTED_MODEL}\n"
            "and OPENROUTER_API_KEY to your own key. No model ships as a default.",
            file=sys.stderr,
        )
        return 2
    config = llm.configure()

    definitions = load_definitions()
    names = args.phenotype or sorted(definitions)
    if args.facet == "proposed":
        return vet_proposed(args, config, definitions, names)
    if args.facet == "closure":
        return vet_closure(args, config, definitions, names)
    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    edges = facets.load(args.edges)

    # One decision per INGREDIENT, and only for tiers we inferred. See the
    # module docstring: judging 1,746 concepts with a cheap model is a rubber
    # stamp, and re-judging MED-RT's own assertion about the phenotype replaces
    # stronger evidence with weaker.
    candidates: dict[str, dict[str, tuple[str, ...]]] = {}
    lifts: dict[str, int] = {}
    tiers: dict[str, dict[str, str]] = {}
    for name in names:
        disorder = build([name], isa, code_to_cuis, cui_to_codes, facets=False)[0].concept_cuis
        seed_cuis = frozenset(
            c for code in definitions[name].seeds for c in code_to_cuis.get(code, ())
        )
        if args.facet == "medication":
            facet_set = facets.medications(seed_cuis, disorder, edges)
        elif args.facet == "finding":
            facet_set = facets.findings(
                definitions[name].finding_seeds, isa, code_to_cuis, max_depth=6
            )
        else:
            facet_set = facets.FacetSet(facets.Facet.DISORDER, disorder, 0, "descendant closure")
        groups: dict[str, set[str]] = {}
        for cui in facet_set.cuis:
            # Identity variants (brands, dose forms) inherit their ingredient's
            # verdict by construction and are expanded at runtime AFTER the
            # vetting gate — they are never candidates, and grouping them here
            # would put thousands of formulations in front of the model.
            if facet_set.provenance.get(cui) == "identity":
                continue
            groups.setdefault(edges.ingredient(cui), set()).add(cui)
        # An ingredient inherits the STRONGEST tier among its variants, so a
        # salt reached only by lift does not demote an ingredient MED-RT asserts.
        rank = {"seed": 0, "closure": 1, "lift": 2}
        tiers[name] = {
            base: min(
                (facet_set.provenance.get(c, "lift") for c in group), key=lambda t: rank.get(t, 2)
            )
            for base, group in groups.items()
        }
        candidates[name] = {base: tuple(sorted(group)) for base, group in groups.items()}
        lifts[name] = facet_set.lift

    to_vet = {n: [b for b, t in tiers[n].items() if t != "seed"] for n in names}
    total = sum(len(v) for v in to_vet.values())
    print(
        f"{sum(len(c) for c in candidates.values())} ingredient decisions over "
        f"{len(names)} phenotypes; {total} are inferred and need vetting",
        file=sys.stderr,
    )
    union = frozenset(b for v in to_vet.values() for b in v)
    terms = preferred_terms(args.mrconso, union)

    decisions: dict[str, Any] = _existing_decisions(args.out, revet=args.revet)
    for name in names:
        row = decisions.setdefault(name, {})
        facet_row = row.setdefault(args.facet, {})
        verdicts: dict[str, dict[str, str]] = dict(facet_row.get("reviewed", {}))
        pending = sorted((c, terms[c]) for c in to_vet[name] if c in terms and c not in verdicts)
        auto = sorted(b for b, t in tiers[name].items() if t == "seed")
        print(
            f"  {name}: {len(tiers[name])} ingredients, {len(auto)} seed-asserted, "
            f"{len(pending)} to decide",
            file=sys.stderr,
        )
        for start in range(0, len(pending), BATCH):
            verdicts |= vet_batch(
                config, definitions[name].label, args.facet, pending[start : start + BATCH]
            )
        # Undecided concepts are excluded, not admitted — see vet_batch.
        kept_ingredients = set(auto) | {c for c, v in verdicts.items() if v["verdict"] == "keep"}
        # A verdict is taken on the ingredient and inherited by its salt and
        # ester forms, which stay in the set: a note writing "amlodipine
        # besylate" must still match a kept amlodipine.
        kept = sorted(c for base in kept_ingredients for c in candidates[name].get(base, ()))
        facet_row.update(
            {
                "lift": lifts[name],
                "ingredients": len(tiers[name]),
                "seed_asserted": len(auto),
                "reviewed_n": len(verdicts),
                "kept_ingredients": sorted(kept_ingredients),
                "kept": kept,
                "provenance": dict(sorted(tiers[name].items())),
                "reviewed": {c: verdicts[c] for c in sorted(verdicts)},
            }
        )
        dropped = sum(1 for v in verdicts.values() if v["verdict"] != "keep")
        print(
            f"    kept {len(kept_ingredients)} ingredients ({len(kept)} concepts), "
            f"dropped {dropped}",
            file=sys.stderr,
        )

    _write_payload(args.out, decisions, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
