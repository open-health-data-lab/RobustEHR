#!/usr/bin/env python
"""Does the pipeline do what it was built to do? Run it end to end and check.

**Why this is a script and not a test.** The unit suite proves each stage in
isolation on synthetic fixtures. What it cannot prove is that the *chain* holds
on a real corpus with a real terminology installed: baseline → corrupt →
reconstruct → re-measure, with every invariant intact. That needs a UMLS index,
so it cannot live in a suite that must pass without one.

The chain, and what each link is being asked:

    segment            can we parse the note at all?
    applicability      does this operator apply to this corpus?
    baseline           what is the note's structure and degradation, WITHOUT
                       terminology — the half a reader without a licence can
                       reproduce
    describe           Table 1, keyed by structural level. Deterministic, runs
                       with no index, and leaves no level with operators
                       unmeasured
    concept-profile    what concepts does it contain, by category and phenotype
    run                corrupt it, at a chosen scale and target
    run --compose      corrupt it several ways at once
    replay             reconstruct every corrupted note and verify its hash
    compare            re-measure the corrupted note with the baseline instrument

**Seven invariants, asserted rather than eyeballed.** Each has failed at least
once in this package's history, which is why it is here rather than assumed:

1. **Determinism** — the same command twice produces the same bytes.
2. **Replay** — every stored cell reconstructs to its recorded hash. Composite
   cells verified 0-of-2 until `EditRow.cell_id` existed, and the failure was
   silent.
3. **Dose monotonicity** — ``applied_n ≤ eligible_n ≤ scope_n ≤ total_n``. A
   violation means a denominator is measuring a different population from its
   numerator, which makes every severity in the run uninterpretable.
4. **No HARD-protection breach** — no applied edit may *cut* a de-identification
   placeholder. Whole replacement by a declaring operator is permitted.
5. **`baseline` and `describe` run with no `--index`** — the guarantee that
   keeps the structural half of the paper reproducible without a UMLS licence.
6. **Conflicts are counted** — a composite that drops edits must say so.
7. **Every level with operators has a baseline** — `space_run` carried two
   operators and appeared nowhere in Table 1, so a user could corrupt something
   the characterisation never counted.

Writes ``validation/measurements/pipeline_audit.json``: counts, hashes and verdicts,
never note text.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

#: Two operators that genuinely collide — a sentence delete swallows spans a
#: token operator wanted — so the conflict counter is exercised rather than
#: reported as a structural zero.
COLLIDING = ["input.typo", "discourse.sentence_delete"]


def run_cli(*args: str, scratch: Path) -> tuple[int, str]:
    """Invoke the CLI as a subprocess, the way a user does."""
    proc = subprocess.run(
        [sys.executable, "-P", "-W", "ignore", "-m", "robustehr.cli", *args],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env={"PYTHONPATH": ".", "PATH": "/usr/bin:/bin"},
        check=False,
    )
    return proc.returncode, proc.stdout


def digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def check_dose_monotonic(run: Path) -> dict[str, Any]:
    """applied ≤ eligible ≤ scope ≤ total, per cell."""
    violations = []
    rows = [json.loads(x) for x in (run / "dose.jsonl").read_text().splitlines() if x.strip()]
    for r in rows:
        if not (r["applied_n"] <= r["eligible_n"] <= r["scope_n"] <= r["total_n"]):
            violations.append(
                {
                    k: r[k]
                    for k in ("op_id", "note_uid", "applied_n", "eligible_n", "scope_n", "total_n")
                }
            )
    return {"cells": len(rows), "violations": violations, "ok": not violations}


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--scratch", type=Path, default=Path("data/pipeline_audit"))
    parser.add_argument("--phenotype", action="extend", nargs="*", default=["hypertension"])
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/pipeline_audit.json")
    )
    args = parser.parse_args(argv)
    scratch = args.scratch
    scratch.mkdir(parents=True, exist_ok=True)
    corpus, limit = str(args.corpus), str(args.limit)
    stages: dict[str, Any] = {}

    # 1. baseline WITHOUT an index — the licence guarantee.
    code, _ = run_cli(
        "baseline",
        "--corpus",
        corpus,
        "--limit",
        limit,
        "--out",
        str(scratch / "baseline.json"),
        scratch=scratch,
    )
    stages["baseline_without_index"] = {"exit": code, "ok": code == 0}

    code, _ = run_cli(
        "applicability",
        "--corpus",
        corpus,
        "--limit",
        limit,
        "--out",
        str(scratch / "applicability.json"),
        scratch=scratch,
    )
    stages["applicability"] = {"exit": code, "ok": code == 0}

    # 1b. Table 1 WITHOUT an index, twice, with the per-note rows. This is the
    # command a methods section opens with, so three things are asserted: it
    # runs with no terminology, it is byte-identical across runs, and no
    # structural level with operators is left unmeasured. The last one is a
    # coverage check that has caught a real gap — `space_run` carried two
    # operators and appeared nowhere in the table.
    for i in (1, 2):
        code, _ = run_cli(
            "describe",
            "--corpus",
            corpus,
            "--limit",
            limit,
            "--index",
            "/nonexistent",
            "--per-note",
            "--out",
            str(scratch / f"describe{i}.json"),
            scratch=scratch,
        )
    table = json.loads((scratch / "describe1.json").read_text())
    unmeasured = table["by_level"]["_unmeasured_levels_with_operators"]
    same = digest(scratch / "describe1.json") == digest(scratch / "describe2.json")
    stages["describe_without_index"] = {
        "exit": code,
        "deterministic": same,
        "levels": len([k for k in table["by_level"] if not k.startswith("_")]),
        "unmeasured_levels_with_operators": unmeasured,
        "per_note_rows": len(table.get("notes_detail", [])),
        "ok": code == 0 and same and not unmeasured and bool(table.get("notes_detail")),
    }

    # 2. concept-profile, twice, for determinism.
    pheno_args = [a for p in args.phenotype for a in ("--phenotype", p)]
    for i in (1, 2):
        code, _ = run_cli(
            "concept-profile",
            "--corpus",
            corpus,
            "--limit",
            limit,
            "--no-assertions",
            *pheno_args,
            "--out",
            str(scratch / f"profile{i}.json"),
            scratch=scratch,
        )
    same = digest(scratch / "profile1.json") == digest(scratch / "profile2.json")
    stages["concept_profile"] = {
        "exit": code,
        "deterministic": same,
        "ok": code == 0 and same,
        "digest": digest(scratch / "profile1.json"),
    }

    # 3. corrupt: one operator, then a colliding composite.
    single = scratch / "run_single"
    code, _ = run_cli(
        "run",
        "--corpus",
        corpus,
        "--limit",
        limit,
        "--severities",
        "0.10",
        "0.30",
        "--operators",
        *COLLIDING,
        "--out",
        str(single),
        scratch=scratch,
    )
    stages["run_single"] = {"exit": code, "ok": code == 0, **check_dose_monotonic(single)}

    composite = scratch / "run_composite"
    for i in (1, 2):
        target = composite if i == 1 else scratch / "run_composite2"
        code, _ = run_cli(
            "run",
            "--corpus",
            corpus,
            "--limit",
            limit,
            "--severities",
            "1.00",
            "--operators",
            *COLLIDING,
            "--compose",
            "--emit-text",
            str(scratch / "corrupted"),
            "--out",
            str(target),
            scratch=scratch,
        )
    same = digest(composite / "edits.jsonl") == digest(scratch / "run_composite2" / "edits.jsonl")
    doses = [
        json.loads(x) for x in (composite / "dose.jsonl").read_text().splitlines() if x.strip()
    ]
    conflicts = sum(d.get("conflicts_dropped", 0) for d in doses)
    stages["run_composite"] = {
        "exit": code,
        "deterministic": same,
        "conflicts_dropped": conflicts,
        "conflicts_counted": conflicts > 0,
        "ok": code == 0 and same and conflicts > 0,
        **check_dose_monotonic(composite),
    }

    # 4. replay both, and verify every hash.
    for name, run in (("replay_single", single), ("replay_composite", composite)):
        code, out = run_cli("replay", "--run", str(run), "--corpus", corpus, scratch=scratch)
        report = json.loads(out) if out.strip().startswith("{") else {}
        verified = report.get("verified", 0)
        mismatched = len(report.get("mismatched", []))
        stages[name] = {
            "exit": code,
            "verified": verified,
            "mismatched": mismatched,
            "ok": code == 0 and verified > 0 and mismatched == 0,
        }

    # 5. compare, and confirm the corruption actually cost concepts.
    code, _ = run_cli(
        "compare",
        "--run",
        str(composite),
        "--corpus",
        corpus,
        "--limit",
        limit,
        "--no-assertions",
        *pheno_args,
        "--out",
        str(scratch / "compare.json"),
        scratch=scratch,
    )
    rows = json.loads((scratch / "compare.json").read_text())["rows"]
    lost = sum(1 for r in rows if r["concepts_delta"] < 0)
    stages["compare"] = {
        "exit": code,
        "cells": len(rows),
        "cells_losing_concepts": lost,
        "ok": code == 0 and bool(rows) and lost > 0,
        "worst_delta": min((r["concepts_delta"] for r in rows), default=None),
    }

    # 6. HARD-protection safety, over the composite's applied edits.
    from robustehr.corpus import read_documents
    from robustehr.document import Document
    from robustehr.protect.registry import Strength, protect_document
    from robustehr.store import read_edits

    docs = {d.uid: d for d in read_documents(args.corpus, limit=args.limit)}
    partial = 0
    touched = 0
    for row in read_edits(composite):
        doc = docs.get(row.note_uid)
        if doc is None:
            continue
        for protected in protect_document(Document.from_text(doc.text, uid=doc.uid)).spans:
            if protected.strength is not Strength.HARD:
                continue
            if row.start < protected.span.end and protected.span.start < row.end:
                touched += 1
                if not (row.start <= protected.span.start and protected.span.end <= row.end):
                    partial += 1
    stages["hard_protection"] = {
        "edits_touching_a_hard_span": touched,
        "partial_cuts": partial,
        "ok": partial == 0,
        "note": "whole replacement by a declaring operator is permitted; a PARTIAL "
        "cut would leave a mangled de-identification marker and is the violation",
    }

    payload = {
        "question": "does the pipeline parse, baseline, corrupt and re-measure, end to end?",
        "corpus": args.corpus.name,
        "notes": args.limit,
        "phenotypes": args.phenotype,
        "operators": COLLIDING,
        "stages": stages,
        "all_ok": all(s.get("ok", False) for s in stages.values()),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    width = max(len(k) for k in stages)
    for name, stage in stages.items():
        mark = "ok  " if stage.get("ok") else "FAIL"
        detail = {k: v for k, v in stage.items() if k not in ("ok", "note", "violations")}
        print(f"  {mark} {name:<{width}}  {detail}")
    print(f"\n-> {args.out}")
    print("PIPELINE OK" if payload["all_ok"] else "PIPELINE HAS FAILING STAGES")
    return 0 if payload["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
