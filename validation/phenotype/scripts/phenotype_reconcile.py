"""The recall pass: revisit what vetting dropped, and say which drops were wrong.

**Why a second look, and why in this direction.** The vetting pass judges one
concept against one phenotype and answers "does this belong". Asked that way, a
model is conservative: anything it cannot immediately justify gets dropped, and
over 13,846 closure candidates it dropped 12,841. Most of that is correct —
roughly two thirds of the drops cite breadth or wrong kind, and read as
`Peptides`, `Ferricyanides`, `Catatonia`, `Procedure on brain`. Those are what a
one-hop graph walk produces and they should go.

The remaining third was dropped on a closer clinical call, and that is where a
conservative pass loses recall it should not. `malignancy` was dropped from
metastatic cancer as "a generalisation"; a clinician reading it in a note would
disagree. A target for a corruption experiment needs to be **sensitive enough to
contain what a reader used**, and a criterion phrased as "does this belong"
optimises the wrong error.

So this pass asks a stronger model about the drops only: **would seeing this
term move a reader toward this diagnosis specifically?** A keep here overrides a
drop; a drop here confirms it. Nothing that was kept is revisited, because this
pass cannot lower recall and is not entitled to.

**"Recall-biased" is not "credulous", and the difference had to be learned.**
The first version of this criterion ended *when you are unsure, answer KEEP*,
and the model obliged: 64% of 8,296 borderline drops came back. The sample read
`Coughing` reinstated to metastatic cancer as a "possible symptom", `Hyphema` to
hypertension as "potentially vascular related", and `Hypotension` to
hypertension as a "blood pressure abnormality directly relevant" — the phenotype
read as a topic rather than as a diagnosis. That set would have been worse than
the conservative one it replaced, because every one of those terms is text a
corruption would then spend its dose on while reporting it as diagnosis
coverage.

The tell was in the model's own wording. Every bad reinstatement hedged, and a
reinstatement that needs a modal verb to justify itself is an association being
laundered into a cue. The criterion now names the failure cases outright — a
finding of the same organ system, the opposite condition, a primary disease
where the phenotype is defined by spread — and says to expect confirming more
than overturning. `HEDGES` refuses the ones that hedge anyway.

**It is separate from vetting rather than a looser setting on it.** Two passes
with opposite biases, both recorded, is auditable in a way one pass with a tuned
threshold is not: every override carries the model that made it and the reason,
so a reader can see exactly where the two disagreed and judge the disagreement
rather than the tuning.

**Junk is filtered before the model sees it, not by it.** Drops whose stated
reason already cites breadth, chemical class or wrong kind are not re-asked.
Re-litigating `Ferricyanides` wastes a request and invites a stronger model to
find a creative reason to keep it.

Usage::

    export ROBUSTEHR_LLM_MODEL=openai/gpt-5.6-terra
    python validation/phenotype/scripts/phenotype_reconcile.py --facet closure --dry-run
    python validation/phenotype/scripts/phenotype_reconcile.py --facet closure
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

import yaml

from robustehr import llm
from robustehr.concepts import facets
from robustehr.concepts.phenotype import load_definitions

BATCH = 40

#: A stronger tier than the vetting pass used, on purpose. This pass exists
#: because the first one was systematically conservative, and asking the same
#: model the same way in softer words would mostly reproduce its answers.
SUGGESTED_MODEL = "openai/gpt-5.6-terra"

#: Drop reasons that need no second look. Matched against the recorded reason,
#: lowercased. Each names a property of the CANDIDATE POOL rather than a
#: clinical judgement, so a stronger model has no better information than the
#: first one did.
SETTLED = (
    "broad",
    "generic",
    "chemical",
    "not a phenotype",
    "not phenotype",
    "overly",
    "class",
    "unrelated",
)

#: Reasons a reinstatement is not allowed to rest on.
#:
#: A lexical guard on the model's own stated reason, and a crude one, kept
#: because the failure it catches was measured rather than imagined. The first
#: version of this prompt ended "when you are unsure, answer KEEP", and the
#: model took it at its word: 64% of 8,296 borderline drops came back, justified
#: as `Coughing` being a "possible symptom of metastatic disease", `Hyphema`
#: being "potentially vascular related" to hypertension, and — reading the
#: phenotype as a topic rather than a diagnosis — `Hypotension` being a "blood
#: pressure abnormality directly relevant" to it.
#:
#: Every one of those reasons hedges, and the hedge is the tell. A term that
#: MIGHT co-occur is not evidence, and a reinstatement that needs a modal verb
#: to justify itself is an association being laundered into a cue. The prompt
#: now says so; this refuses the ones that say it anyway.
HEDGES = (
    "may ",
    "might",
    "possible",
    "possibly",
    "potential",
    "can be",
    "could ",
    "suggests",
    "warrants",
)

PROMPT = """You are auditing concepts that were REJECTED from a clinical phenotype's
evidence set, to find the rejections that were wrong.

PHENOTYPE: {label}

The set locates the text in a discharge summary that a reader would use when
deciding whether this patient has this phenotype. It needs to be sensitive
enough to contain what a reader actually used, and specific enough that what it
contains points HERE rather than at the organ system in general.

Answer KEEP only if seeing that term would move a reader TOWARD this diagnosis
specifically: it is the phenotype, a subtype, a generalization of it, a
characteristic complication, or a treatment or investigation used for it rather
than for the organ system generally.

Answer DROP otherwise. In particular DROP:
- anything you would justify with "may", "possible", "potentially" or "can be
  associated with". A term that merely COULD occur alongside this phenotype is
  not evidence of it. If your reason needs a hedge, the answer is DROP.
- a finding of the same organ system that does not point at this diagnosis.
  Coughing is not evidence of metastatic cancer; abdominal pain is not evidence
  of C. difficile; a retinal finding is not evidence of hypertension.
- the OPPOSITE condition, or a different disorder of the same measurement.
  Hypotension is not evidence of hypertension.
- a primary disease at a site, where the phenotype is defined by spread rather
  than by site.
- a test or procedure ordered broadly for the organ system rather than for this
  diagnosis.

The previous pass removed the obvious rejects, so these are genuinely borderline
and most of them were dropped correctly. Expect to confirm more than you
overturn. Overturn where the drop reason was about the term being a
generalization, a synonym, an abbreviation or a closely related variant — those
are the rejections worth revisiting — not where it was about the term being
weakly associated.

Reply with one line per term, exactly `<number>|<keep|drop>|<3-6 word reason>`.
No preamble, no blank lines.

{items}"""


def preferred_terms(mrconso: Path, wanted: frozenset[str]) -> dict[str, str]:
    """One English preferred term per CUI, for the prompt only. Never shipped."""
    out: dict[str, str] = {}
    with mrconso.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split("|")
            if len(parts) < 15:
                continue
            cui = parts[0]
            preferred = parts[1] == "ENG" and parts[2] == "P" and parts[4] == "PF"
            if preferred and cui in wanted and cui not in out:
                out[cui] = parts[14]
    return out


def settled(reason: str) -> bool:
    lowered = reason.lower()
    return any(token in lowered for token in SETTLED)


def ask(config: Any, label: str, chunk: list[tuple[str, str]]) -> dict[str, dict[str, str]]:
    """One batch. An unparseable line leaves the prior drop standing.

    The asymmetry is the opposite of the vetting pass's and for the same reason:
    there, a parse failure must not widen the set; here, it must not narrow it.
    In both cases the failure leaves the existing verdict alone.
    """
    items = "\n".join(f"{i + 1}. {term}" for i, (_, term) in enumerate(chunk))
    try:
        reply = llm.complete(config, PROMPT.format(label=label, items=items))
    except llm.LlmUnavailable as exc:
        print(f"    LLM unavailable: {exc}", file=sys.stderr)
        return {}
    out: dict[str, dict[str, str]] = {}
    for line in reply.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3 or not parts[0].rstrip(".").isdigit():
            continue
        index = int(parts[0].rstrip(".")) - 1
        if not 0 <= index < len(chunk):
            continue
        cui, term = chunk[index]
        reason = parts[2][:60]
        keep = parts[1].lower().startswith("keep")
        # A reinstatement justified by a hedge is refused, however the model
        # voted. See HEDGES: this is the failure mode that made the first run
        # of this pass unusable, and the model's own wording is the evidence.
        if keep and any(h in reason.lower() for h in HEDGES):
            keep = False
            reason = f"hedged: {reason}"[:60]
        out[cui] = {
            "verdict": "keep" if keep else "drop",
            "reason": reason,
            "surface_sha256": hashlib.sha256(term.encode("utf-8")).hexdigest()[:16],
        }
    return out


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--facet", default="closure", choices=("closure", "proposed"))
    parser.add_argument("--mrconso", type=Path, default=Path("data/umls/2026AA/META/MRCONSO.RRF"))
    parser.add_argument("--phenotype", action="extend", nargs="*", default=None)
    parser.add_argument(
        "--out", type=Path, default=Path("src/robustehr/resources/phenotype_vetting.yaml")
    )
    parser.add_argument(
        "--measurement", type=Path, default=Path("validation/measurements/phenotype_reconcile.json")
    )
    parser.add_argument(
        "--all-drops",
        action="store_true",
        help="re-ask every drop, including those whose reason already cites "
        "breadth or wrong kind. Wastes requests and invites a stronger model to "
        "argue its way back to Ferricyanides",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    payload: Any = yaml.safe_load(args.out.read_text(encoding="utf-8"))
    decisions = payload["phenotypes"]
    definitions = load_definitions()
    names = args.phenotype or sorted(decisions)

    candidates = facets.load_closure() if args.facet == "closure" else {}

    pending: dict[str, list[str]] = {}
    for name in names:
        row = decisions.get(name, {}).get(args.facet)
        if not row:
            continue
        reviewed = row.get("reviewed", {})
        pool = candidates.get(name, frozenset()) if candidates else set(reviewed)
        drops = [
            cui
            for cui in sorted(pool)
            if reviewed.get(cui, {}).get("verdict") == "drop"
            # A clinician verdict is final. This pass may overturn a model, not
            # a person, and the reviewer field is what tells them apart.
            and "reviewer" not in reviewed.get(cui, {})
            and (args.all_drops or not settled(reviewed[cui].get("reason", "")))
        ]
        if drops:
            pending[name] = drops

    total = sum(len(v) for v in pending.values())
    print(f"{total} borderline drops over {len(pending)} phenotypes, facet={args.facet}")
    for name in sorted(pending):
        print(f"  {name:32s} {len(pending[name]):5d}")
    if args.dry_run:
        print(f"\ndry run: ~{-(-total // BATCH)} requests")
        return 0
    if not total:
        print("nothing to reconcile")
        return 0

    if not os.environ.get(llm.MODEL_ENV):
        print(f"Set {llm.MODEL_ENV}, e.g. {SUGGESTED_MODEL}", file=sys.stderr)
        return 2
    config = llm.configure()

    wanted = frozenset(c for v in pending.values() for c in v)
    print(f"\nreading preferred terms for {len(wanted)} concepts...", file=sys.stderr)
    terms = preferred_terms(args.mrconso, wanted)

    overturned = confirmed = 0
    per_phenotype: dict[str, dict[str, int]] = {}
    for name in sorted(pending):
        row = decisions[name][args.facet]
        reviewed = row["reviewed"]
        kept = set(row.get("kept", []))
        chunk_src = [(c, terms[c]) for c in pending[name] if c in terms]
        flips = 0
        for start in range(0, len(chunk_src), BATCH):
            verdicts = ask(config, definitions[name].label, chunk_src[start : start + BATCH])
            for cui, verdict in verdicts.items():
                if verdict["verdict"] != "keep":
                    confirmed += 1
                    continue
                reviewed[cui] = {**verdict, "pass": "recall", "model": config.model}
                kept.add(cui)
                flips += 1
        row["kept"] = sorted(kept)
        overturned += flips
        per_phenotype[name] = {"asked": len(chunk_src), "overturned": flips}
        print(f"  {name:32s} asked {len(chunk_src):5d}  reinstated {flips:5d}")

    payload["reconciled_by"] = config.model
    payload["reconcile_pass"] = {
        "what": "a recall-biased second look at drops, overriding keeps only",
        "facet": args.facet,
        "asked": total,
        "overturned": overturned,
        "confirmed": confirmed,
    }
    args.out.write_text(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True, width=88), encoding="utf-8"
    )
    args.measurement.parent.mkdir(parents=True, exist_ok=True)
    args.measurement.write_text(
        json.dumps(
            {
                "what": (
                    "drops revisited under a recall-biased criterion by a stronger "
                    "model; keeps override, drops confirm"
                ),
                "model": config.model,
                "facet": args.facet,
                "asked": total,
                "overturned": overturned,
                "confirmed": confirmed,
                "override_rate": round(overturned / total, 4) if total else None,
                "per_phenotype": per_phenotype,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\nreinstated {overturned} of {total} ({overturned / total:.0%})")
    print(f"{args.out}\n{args.measurement}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
