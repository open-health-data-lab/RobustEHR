#!/usr/bin/env python
"""Which extension rules should reach backwards? Measured, one rule at a time.

**Every rule in `assertion_extensions.yaml` is FORWARD, and nobody chose that.**
The loader defaulted to it while medspaCy's own default is `BIDIRECTIONAL`, so
the direction of nine rules was set by an unexamined line of code. The error
analysis then found that **33 of the 66 held-out false negatives** across
`negated`, `uncertain` and `historical` are a cue sitting *after* its target —
which a FORWARD rule cannot reach whatever vocabulary is added to it.

*"Rash was thought to represent a drug rash"* is FORWARD and works. *"discharged
with rheumatology follow up"*, *"Recurrent aspiration s/p G tube"*, *"Tylenol
PRN"* put the cue after the mention, and no amount of extra triggers helps.

**Widening direction is not free**, which is why this sweeps rather than assumes.
A BIDIRECTIONAL cue reaches both ways and can only add false positives; whether
the recall it buys is worth them is a per-rule question, and `prn` behaves
nothing like `nil`.

**One rule at a time, on the development half only.** A full sweep of nine rules
in three directions is 19,683 configurations; the interactions between rules of
different categories are weak, so each is measured against the shipped baseline
independently and the winners are combined and re-measured together. The held-out
half is never touched here — it is what judges the combination afterwards.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from scripts.split_assertion_gold import keep_items

from robustehr.concepts.context import DIMENSIONS, _extension_config, qualify
from robustehr.document import Document
from robustehr.types import Span

#: Which reported dimension each rule can affect, so a sweep row is scored on
#: the dimension it could possibly move rather than on all four.
CATEGORY_DIMENSION = {
    "NEGATED_EXISTENCE": "negated",
    "POSSIBLE_EXISTENCE": "uncertain",
    "HYPOTHETICAL": "uncertain",
    "HISTORICAL": "historical",
    "FAMILY": "family",
}

DIRECTIONS = ("FORWARD", "BIDIRECTIONAL", "BACKWARD")

#: Smallest development-half F1 gain worth adopting, and the smallest number of
#: recovered true positives that must come with it.
#:
#: Without a floor this sweep adopts noise. `s/p` scored +0.0044 by trading one
#: recovered span for three new false positives — an F1 gain only because
#: `historical` recall is low enough that any true positive is worth more than a
#: false one, which is an artefact of the base rate rather than evidence the rule
#: should reach backwards. A change this small will not survive the held-out half
#: and adopting it would be fitting the development set.
MIN_DELTA_F1 = 0.01
MIN_DELTA_TP = 1


def encode(rules: list[dict[str, Any]]) -> str:
    """The extension resource with these cue rules, as `qualify(config=...)` takes."""
    return json.dumps({**_extension_config(), "cues": rules}, sort_keys=True)


def score(
    corpus: dict[str, str],
    by_note: dict[str, list[dict[str, Any]]],
    config: str,
) -> dict[str, dict[str, float | int]]:
    """Per-dimension tp/fp/fn for one rule configuration."""
    counts: dict[str, dict[str, int]] = {d: defaultdict(int) for d in DIMENSIONS}
    for note, items in sorted(by_note.items()):
        text = corpus[note]
        doc = Document.from_text(text, uid=note)
        bounds = tuple(s.span.start for s in doc.sentences.sentences)
        spans = tuple(Span(int(i["start"]), int(i["end"])) for i in items)
        index = qualify(text, spans, boundaries=bounds, extended=True, config=config)
        for item, span in zip(items, spans, strict=True):
            truth, predicted = set(item["labels"]), set(index.attributes_for(span))
            for dimension in DIMENSIONS:
                if dimension in truth and dimension in predicted:
                    counts[dimension]["tp"] += 1
                elif dimension in truth:
                    counts[dimension]["fn"] += 1
                elif dimension in predicted:
                    counts[dimension]["fp"] += 1
    out: dict[str, dict[str, float | int]] = {}
    for dimension, c in counts.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[dimension] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("data/assertion_gold_mimic/gold.yaml"))
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument(
        "--split-file", type=Path, default=Path("data/assertion_gold_mimic/split.json")
    )
    parser.add_argument("--split", default="development", choices=["development", "held_out"])
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/cue_direction_sweep.json")
    )
    args = parser.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    items = keep_items(gold["items"], args.split_file, args.split)
    by_note: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_note[str(item["fixture"])].append(item)

    from robustehr.corpus import read_documents

    corpus = {d.uid: d.text for d in read_documents(args.corpus) if d.uid in by_note}

    shipped = [dict(r) for r in (_extension_config().get("cues") or [])]
    baseline = score(corpus, by_note, encode(shipped))
    print(f"baseline on {args.split} ({len(items)} spans, {len(by_note)} notes)")
    for dimension in DIMENSIONS:
        row = baseline[dimension]
        print(f"  {dimension:<11} F1={row['f1']}  P={row['precision']} R={row['recall']}")

    rows: list[dict[str, Any]] = []
    for position, rule in enumerate(shipped):
        dimension = CATEGORY_DIMENSION.get(str(rule["category"]))
        if dimension is None:
            continue
        current = str(rule.get("direction", "FORWARD"))
        for direction in DIRECTIONS:
            if direction == current:
                continue
            variant = [dict(r) for r in shipped]
            variant[position]["direction"] = direction
            result = score(corpus, by_note, encode(variant))[dimension]
            delta = round(float(result["f1"]) - float(baseline[dimension]["f1"]), 4)
            rows.append(
                {
                    "rule": str(rule["literal"]),
                    "category": str(rule["category"]),
                    "dimension": dimension,
                    "from": current,
                    "to": direction,
                    "f1": result["f1"],
                    "delta_f1": delta,
                    "delta_tp": int(result["tp"]) - int(baseline[dimension]["tp"]),
                    "delta_fp": int(result["fp"]) - int(baseline[dimension]["fp"]),
                }
            )
            print(
                f"  {rule['literal']:<20} {current:<12} -> {direction:<13}"
                f" {dimension:<11} F1 {result['f1']:.4f}  delta {delta:+.4f}"
                f"  (+{int(result['tp']) - int(baseline[dimension]['tp'])} tp,"
                f" {int(result['fp']) - int(baseline[dimension]['fp']):+d} fp)"
            )

    winners = [r for r in rows if r["delta_f1"] >= MIN_DELTA_F1 and r["delta_tp"] >= MIN_DELTA_TP]
    # Best change per rule, so a rule cannot be counted twice in the combination.
    best: dict[str, dict[str, Any]] = {}
    for row in sorted(winners, key=lambda r: -r["delta_f1"]):
        best.setdefault(row["rule"], row)

    combined = [dict(r) for r in shipped]
    for rule in combined:
        if (win := best.get(str(rule["literal"]))) is not None:
            rule["direction"] = win["to"]
    combined_score = score(corpus, by_note, encode(combined))

    print("\ncombined (all individually-winning direction changes applied together):")
    for dimension in DIMENSIONS:
        before, after = baseline[dimension]["f1"], combined_score[dimension]["f1"]
        print(
            f"  {dimension:<11} {before} -> {after}  ({float(after) - float(before):+.4f})"  # type: ignore[arg-type]
        )

    payload = {
        "question": "Which extension rules should reach backwards, and at what cost?",
        "why": (
            "every rule in the resource is FORWARD because the loader defaulted "
            "to it, not because anyone chose it — and 33 of 66 held-out false "
            "negatives are a cue sitting after its target, which a FORWARD rule "
            "cannot reach at any vocabulary size."
        ),
        "method": (
            "one rule at a time against the shipped baseline, on the development "
            "half only. A full sweep is 3^9 configurations; cross-rule "
            "interaction is weak because the rules carry different categories, "
            "so winners are combined and re-measured together at the end."
        ),
        "how_to_read": (
            "delta_f1 is on the development half, which is where the choice is "
            "made. It is NOT evidence of generalisation — the held-out half "
            "judges the adopted combination, and only once."
        ),
        "split": args.split,
        "n_items": len(items),
        "n_notes": len(by_note),
        "baseline": baseline,
        "per_rule": rows,
        "adoption_threshold": {"min_delta_f1": MIN_DELTA_F1, "min_delta_tp": MIN_DELTA_TP},
        "why_a_threshold": (
            "without one the sweep adopts noise: `s/p` gained 0.0044 F1 by "
            "trading one recovered span for three new false positives, an "
            "improvement only because the base rate makes any true positive "
            "outweigh a false one. Changes that small do not survive held-out."
        ),
        "adopted": {r: best[r]["to"] for r in sorted(best)},
        "combined": combined_score,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
