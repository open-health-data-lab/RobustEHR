#!/usr/bin/env python
"""Fold a clinician's marked-up review back into the frozen vetting file.

The other half of ``validation/phenotype/scripts/phenotype_export_review.py``: that script writes
``data/phenotype_review/<name>.tsv`` with UMLS terms in the clear for a licensed
reader; this one reads the marked-up copies back and records the verdicts in
``src/robustehr/resources/phenotype_vetting.yaml``. The round trip is CUIs in
one direction and terms in the other, so nothing licensed enters git.

**The keep column is an override, not a ballot.** A blank cell means the
model's verdict stands — the clinician read the row and let it pass, which is
itself a decision the export documents. ``y``/``n`` replaces the verdict, and
the row is written back with a ``reviewer`` field the model rows never carry, so
a reader of the YAML can always tell which authority decided each concept. A
set with clinician rows supports the stronger claim ``vetted_by:
llm+clinician``; the schema keeps the two apart on purpose.

**Disagreement is a measurement, not noise.** Every override is counted and the
per-phenotype tally lands in the YAML (``clinician: {decided, overrides}``),
because the rate at which a clinician overturns the model is exactly the
validation number `validation/methodology/14` reports for the vetting pass.

Verdicts apply to the CUI on the row, nothing more: the export already lists
every salt and ester variant on its own row, so there is no hidden inheritance
to reason about at ingest time.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import sys
from pathlib import Path
from typing import Any

#: Which vetting-file facet row a review row belongs to, by (facet, source).
#: The export writes one TSV per phenotype spanning every facet; the vetting
#: file keys verdicts by the facet that produced the candidate.
YES = frozenset({"y", "yes", "keep", "k", "1", "true"})
NO = frozenset({"n", "no", "drop", "d", "0", "false"})


def facet_key(facet: str, source: str) -> str:
    # The closure FACET is checked before the closure SOURCE: disorder-closure
    # rows carry source "closure" and belong to the disorder verdicts, while
    # closure-facet rows carry facet "closure" and their own vetting row.
    if facet == "closure":
        return "closure"
    if source == "proposed":
        return "proposed"
    if source == "closure":
        return "disorder"
    if facet == "medication":
        return "medication"
    return facet


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - a linear ingest, one statement per stage
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reviews", type=Path, default=Path("data/phenotype_review"))
    parser.add_argument("--phenotype", action="extend", nargs="*", metavar="NAME", default=None)
    parser.add_argument("--reviewer", required=True, help="name recorded on every human verdict")
    parser.add_argument(
        "--out", type=Path, default=Path("src/robustehr/resources/phenotype_vetting.yaml")
    )
    args = parser.parse_args(argv)

    import yaml

    payload: dict[str, Any] = {}
    if args.out.exists():
        payload = yaml.safe_load(args.out.read_text(encoding="utf-8")) or {}
    decisions: dict[str, Any] = payload.setdefault("phenotypes", {})

    files = sorted(args.reviews.glob("*.tsv"))
    if args.phenotype:
        files = [f for f in files if f.stem in set(args.phenotype)]
    if not files:
        print(f"no review TSVs under {args.reviews}", file=sys.stderr)
        return 2

    file_digests: dict[str, str] = {}
    total_decided = total_overrides = 0
    for path in files:
        name = path.stem
        rows = read_tsv(path)
        file_digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        decided = overrides = 0
        for row in rows:
            mark = (row.get("keep") or "").strip().lower()
            if not mark:
                continue  # blank: the model's verdict stands
            if mark in YES:
                verdict = "keep"
            elif mark in NO:
                verdict = "drop"
            else:
                print(f"  {name}: unreadable keep={mark!r} for {row['cui']}, skipped")
                continue
            decided += 1
            key = facet_key(row.get("facet", ""), row.get("source", ""))
            facet_row = decisions.setdefault(name, {}).setdefault(key, {})
            reviewed = facet_row.setdefault("reviewed", {})
            prior = reviewed.get(row["cui"], {}).get("verdict")
            overrides += prior is not None and prior != verdict
            reviewed[row["cui"]] = {
                "verdict": verdict,
                "reason": (row.get("reviewer_note") or "clinician review").strip()[:60],
                "surface_sha256": hashlib.sha256(
                    (row.get("term") or "").encode("utf-8")
                ).hexdigest()[:16],
                "reviewer": args.reviewer,
            }
            kept = set(facet_row.get("kept", ()))
            (kept.add if verdict == "keep" else kept.discard)(row["cui"])
            facet_row["kept"] = sorted(kept)
            # Medication keeps are counted in ingredients too; keep that
            # roster in step where it exists so the audit numbers agree.
            if verdict != "keep" and "kept_ingredients" in facet_row:
                facet_row["kept_ingredients"] = sorted(
                    set(facet_row["kept_ingredients"]) - {row["cui"]}
                )
        row_summary = decisions.setdefault(name, {}).setdefault("clinician", {})
        row_summary["decided"] = row_summary.get("decided", 0) + decided
        row_summary["overrides"] = row_summary.get("overrides", 0) + overrides
        total_decided += decided
        total_overrides += overrides
        print(f"  {name}: {decided} human verdicts, {overrides} override the model")

    payload["vetted_by"] = "llm+clinician" if total_decided else payload.get("vetted_by", "llm")
    payload.setdefault("clinician_review", {}).update(
        {
            "reviewer": args.reviewer,
            "date": _dt.date.today().isoformat(),
            "policy": "blank keep = model verdict stands; y/n overrides it",
            "source_tsv_sha256": file_digests,
        }
    )
    args.out.write_text(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True, width=88), encoding="utf-8"
    )
    print(
        f"-> {args.out}\n{total_decided} human verdicts over {len(files)} phenotypes, "
        f"{total_overrides} overrides of the model"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
