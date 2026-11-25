"""Characterise, corrupt, replay and compare a corpus with the core install — no terminology.

This is the cross-corpus measurement behind `validation/measurements/corpus/`:
the same commands a reader without a UMLS licence can run, executed over a
corpus and reduced to aggregate counts that carry no note text. It exists to
answer one question a single development corpus cannot: does the structural
layer — header detection, segmentation, list and aligned blocks, placeholder
indexing — and the operator suite behave on notes the package was not
developed on?

Per corpus it records:

* the `applicability` table — per structural unit, the share of notes with any;
* the `describe --no-concepts` Table 1 — per-level medians, and the header
  resolution share: heading-shaped lines the MIMIC-developed header lexicon
  resolves to one of the 58 canonical sections, the measure of whether the
  section layer over-fits its development corpus;
* a `run` over every registered non-LLM operator at two severities, reduced
  per operator to eligible units per note, applicability (share of notes with
  ≥1 eligible unit), requested vs applied dose, and dose status counts;
* `replay` verification and `compare` deltas.

Optionally, `--group-by COLUMN` repeats the applicability and header-resolution
summary per value of a corpus column (the synthetic demo corpus carries
`format` and `deid_scheme`), which is how per-format invariance is reported.

    python validation/pipeline/scripts/corpus_characterisation.py \
        --corpus examples/demo_notes.csv --name demo --work data/corpus_runs/demo \
        --group-by format --group-by deid_scheme \
        --out validation/measurements/corpus/demo_characterisation.json

Everything under `--work` is note-derived and stays under `data/`; only the
`--out` aggregate is meant to be committed.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

LLM_SUFFIX = "_llm"


def sh(*args: str) -> str:
    proc = subprocess.run(list(args), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"command failed: {' '.join(args)}")
    return proc.stdout


def registered_operators() -> list[str]:
    from robustehr.ops.registry import all_operators, register_builtins

    register_builtins()
    return sorted(op.id for op in all_operators() if not op.id.endswith(LLM_SUFFIX))


def median_iqr(block: dict) -> dict:
    return {k: block.get(k) for k in ("median", "p25", "p75", "total") if k in block}


def header_resolution(table: dict) -> dict:
    header = table["by_level"]["header"]
    heading = header["heading_lines"]["total"]
    canonical = header["canonical"]["total"]
    guessed = header["guessed"]["total"]
    excluded = header["excluded_non_structural"]["total"]
    resolvable = heading - excluded
    return {
        "heading_shaped_lines": heading,
        "excluded_non_structural": excluded,
        "resolved_to_canonical_section": canonical,
        "heuristic_unresolved": guessed,
        "resolved_share_of_structural_headings": (
            round(canonical / resolvable, 4) if resolvable else None
        ),
        "canonical_ids_present": table["by_level"]["section"]["distinct_canonical_ids"],
        "canonical_ids_present_distinct": table["by_level"]["section"]["canonical_declared"]
        - len(table["by_level"]["section"]["canonical_absent"]),
        "canonical_ids_declared": table["by_level"]["section"]["canonical_declared"],
    }


REDUCE_ONLY = False


def describe(corpus: Path, work: Path, limit: int | None) -> dict:
    out = work / "table1.json"
    args = ["robustehr", "describe", "--corpus", str(corpus), "--no-concepts", "--out", str(out)]
    if limit:
        args += ["--limit", str(limit)]
    if not (REDUCE_ONLY and out.exists()):
        sh(*args)
    return json.loads(out.read_text())


def applicability(corpus: Path, work: Path, limit: int | None) -> dict:
    out = work / "applicability.json"
    args = ["robustehr", "applicability", "--corpus", str(corpus), "--out", str(out)]
    if limit:
        args += ["--limit", str(limit)]
    if not (REDUCE_ONLY and out.exists()):
        sh(*args)
    data = json.loads(out.read_text())
    return {
        "notes": data["notes"],
        "units": {
            u["unit_kind"]: {k: u[k] for k in ("median", "p25", "p75", "total", "notes_with_any")}
            for u in data["units"]
        },
    }


def run_and_replay(
    corpus: Path, work: Path, operators: list[str], severities: list[str], limit: int | None
) -> dict:
    run_dir = work / "run"
    args = [
        "robustehr",
        "run",
        "--corpus",
        str(corpus),
        "--out",
        str(run_dir),
        "--operators",
        *operators,
        "--severities",
        *severities,
        "--salt",
        "corpus-characterisation",
    ]
    if limit:
        args += ["--limit", str(limit)]
    replay_out = work / "replay.json"
    compare_out = work / "compare.json"
    if not (REDUCE_ONLY and compare_out.exists()):
        sh(*args)
        sh(
            "robustehr",
            "replay",
            "--run",
            str(run_dir),
            "--corpus",
            str(corpus),
            "--out",
            str(replay_out),
        )
        sh(
            "robustehr",
            "compare",
            "--run",
            str(run_dir),
            "--corpus",
            str(corpus),
            "--out",
            str(compare_out),
        )
    manifest = json.loads((run_dir / "manifest.json").read_text())
    replay = json.loads(replay_out.read_text())
    compare = json.loads(compare_out.read_text())
    compare_rows = compare.get("rows", []) if isinstance(compare, dict) else compare

    per_op: dict[str, dict[str, dict]] = defaultdict(dict)
    rows = [
        json.loads(line)
        for line in (run_dir / "dose.jsonl").read_text().splitlines()
        if line.strip()
    ]
    by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_cell[(r["op_id"], str(r["severity"]))].append(r)
    for (op, sev), cells in sorted(by_cell.items()):
        eligible = [c["eligible_n"] for c in cells]
        requested = sum(c["requested_k"] for c in cells)
        applied = sum(c["applied_n"] for c in cells)
        statuses = Counter(c["status"] for c in cells)
        per_op[op][sev] = {
            "notes": len(cells),
            "eligible_per_note_median": statistics.median(eligible) if eligible else None,
            "eligible_total": sum(eligible),
            "applicability": round(sum(1 for e in eligible if e > 0) / len(cells), 4)
            if cells
            else None,
            "requested_k_total": requested,
            "applied_n_total": applied,
            "achieved_over_requested": round(applied / requested, 4) if requested else None,
            "status_counts": dict(statuses),
        }
    return {
        "operators": operators,
        "severities": severities,
        "manifest": {
            k: manifest.get(k)
            for k in (
                "notes",
                "cells",
                "edits",
                "contains_note_text",
                "dose_sha256",
                "edits_sha256",
                "max_replacement_chars",
            )
        },
        "replay": {k: replay.get(k) for k in ("verified", "failed")},
        "compare": {
            "cells": compare.get("cells") if isinstance(compare, dict) else None,
            "concepts_measured": compare.get("concepts_measured")
            if isinstance(compare, dict)
            else None,
            "rows": len(compare_rows),
        },
        "per_operator": per_op,
    }


def grouped(corpus: Path, column: str, work: Path, describe_fn, applic_fn) -> dict:
    csv.field_size_limit(1 << 30)
    with corpus.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if column not in rows[0]:
        raise SystemExit(f"no column {column!r} in {corpus}")
    fields = list(rows[0].keys())
    out: dict[str, dict] = {}
    for value in sorted({r[column] for r in rows}):
        sub = [r for r in rows if r[column] == value]
        gdir = work / "groups" / column / value.replace("/", "_")
        gdir.mkdir(parents=True, exist_ok=True)
        gcsv = gdir / "notes.csv"
        with gcsv.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(sub)
        table = describe_fn(gcsv, gdir, None)
        app = applic_fn(gcsv, gdir, None)
        out[value] = {
            "notes": len(sub),
            "header_resolution": header_resolution(table),
            "notes_with_any": {k: v["notes_with_any"] for k, v in app["units"].items()},
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--work", type=Path, required=True, help="scratch under data/; note-derived")
    ap.add_argument("--out", type=Path, required=True, help="aggregate artifact to commit")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--severities", nargs="+", default=["0.10", "0.30"])
    ap.add_argument("--group-by", action="append", default=[])
    ap.add_argument("--skip-run", action="store_true")
    ap.add_argument(
        "--reduce-only",
        action="store_true",
        help="rebuild the artifact from an existing --work directory without re-running the CLI",
    )
    args = ap.parse_args()
    globals()["REDUCE_ONLY"] = args.reduce_only
    args.work.mkdir(parents=True, exist_ok=True)

    table = describe(args.corpus, args.work, args.limit)
    app = applicability(args.corpus, args.work, args.limit)
    levels = {}
    for level, block in table["by_level"].items():
        if level.startswith("_"):
            continue
        entry = {}
        if isinstance(block, dict):
            if "n" in block and isinstance(block["n"], dict):
                entry["n"] = median_iqr(block["n"])
            entry["operators"] = block.get("operators")
        levels[level] = entry
    result = {
        "what": (
            "cross-corpus characterisation with the core install (no terminology); "
            "aggregate counts only"
        ),
        "corpus": args.name,
        "notes": table["notes"],
        "levels": levels,
        "header_resolution": header_resolution(table),
        "sentences": {k: median_iqr(table["by_level"]["sentence"][k]) for k in ("prose", "layout")},
        "hard_wrapped_notes": table["by_level"]["document"]["hard_wrapped"]["total"],
        "assertion_cues": {
            op: {
                k: table["by_level"]["assertion"][op].get(k)
                for k in ("eligible_cues", "median", "p25", "p75")
            }
            for op in table["by_level"]["assertion"].get("operators", [])
        },
        "applicability": app,
        "unavailable": table.get("unavailable"),
    }
    if not args.skip_run:
        result["run"] = run_and_replay(
            args.corpus, args.work, registered_operators(), args.severities, args.limit
        )
    for column in args.group_by:
        result.setdefault("grouped", {})[column] = grouped(
            args.corpus, column, args.work, describe, applicability
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    print(
        json.dumps(
            {
                "notes": result["notes"],
                "header_resolution": result["header_resolution"],
                "replay": result.get("run", {}).get("replay"),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
