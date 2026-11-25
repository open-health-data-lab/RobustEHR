#!/usr/bin/env python
"""Cheap LLMs against the gold: the cost tier of the detector comparison.

**What this can and cannot establish.** The gold *is* two frontier models
agreeing at κ 0.845-0.913, so the frontier tier is already measured — by
construction, and reported as inter-annotator agreement rather than as accuracy.
What is unknown is whether a model costing an order of magnitude less reaches the
same judgements, and that is a cheap question to answer: the annotation
machinery, the guideline, the windowing and the response cache already exist, so
a new arm is a different `--model` and a scorer.

**Not a candidate detector.** An API call is not replayable, not offline, and not
hashable into an operator version, and this package's central claim is
deterministic edit scripts. The LLM arms exist to say *how far the deterministic
detector is from the ceiling*, and to price that gap. If a cheap model scores
well the conclusion is to distil it into an encoder, not to call it at runtime —
which is exactly what `assertion_finetune.py` does with the gold itself.

**The circularity is real and is bounded rather than denied.** Scoring an LLM
against a gold two other LLMs wrote is not an independent test: models share
training distributions and can agree on the same mistake. Two things keep it
informative. The gold's two annotators are from a different family than the cheap
models measured here, and agreement is reported against the **subset where both
annotators agreed** as well as against the merged gold — where the two raters
disagreed there is no fact for a third model to get right, and scoring it there
would measure the yardstick's wobble rather than the model.

Credentials: `OPENROUTER_API_KEY`. Every
user supplies their own; none ships. Needed only to *re-run* this arm — the
numbers it produces are committed and the shipped detector needs no network.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Any

import yaml
from scripts.assertion_neural_eval import score
from scripts.split_assertion_gold import keep_items

from robustehr.concepts.context import DIMENSIONS

#: Models to price. Chosen for cost spread rather than for expected quality —
#: the question is where the price/agreement curve bends, so a very cheap model
#: is as informative as a good one.
MODELS = (
    "google/gemini-2.5-flash",
    "google/gemini-2.5-flash-lite",
)


def load_labels(path: Path) -> dict[tuple[str, int, int], set[str]]:
    """`labels.json` from `annotate_assertions.py`, keyed by span."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["items"] if isinstance(payload, dict) else payload
    out: dict[tuple[str, int, int], set[str]] = {}
    for row in rows:
        key = (str(row["note_id"]), int(row["start"]), int(row["end"]))
        out[key] = {str(x) for x in row.get("labels", [])}
    return out


def fold(labels: set[str]) -> set[str]:
    """`hypothetical` folds into `uncertain`, as everywhere else in this stage."""
    return {"uncertain" if x == "hypothetical" else x for x in labels}


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    root = Path("data/assertion_gold_mimic")
    parser.add_argument("--gold", type=Path, default=root / "gold.yaml")
    parser.add_argument("--split-file", type=Path, default=root / "split.json")
    parser.add_argument("--split", default="held_out", choices=["development", "held_out"])
    parser.add_argument(
        "--labels",
        nargs="+",
        metavar="MODEL=PATH",
        required=True,
        help="one per arm, e.g. google/gemini-2.5-flash=data/.../labels_gemini.json",
    )
    parser.add_argument("--annotator-1", type=Path, default=root / "labels.json")
    parser.add_argument("--annotator-2", type=Path, default=root / "labels_terra.json")
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/assertion_llm_eval.json")
    )
    args = parser.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    items = keep_items(gold["items"], args.split_file, args.split)
    truth = {(str(i["fixture"]), int(i["start"]), int(i["end"])): set(i["labels"]) for i in items}

    # Spans where the two gold annotators agreed exactly. Scoring a third model
    # only here removes the rows on which "correct" is undefined.
    consensus: set[tuple[str, int, int]] = set()
    if args.annotator_1.exists() and args.annotator_2.exists():
        first, second = load_labels(args.annotator_1), load_labels(args.annotator_2)
        consensus = {k for k in truth if fold(first.get(k, set())) == fold(second.get(k, set()))}

    # `unmodified` is scored as a fifth class rather than left implicit. It is
    # ~70% of spans, it is the class an over-calling detector destroys, and for
    # this package it is the one that matters most: a span wrongly marked
    # modified is a span withheld from an operator, so a low `unmodified`
    # precision silently shrinks the dose denominator.
    scored = (*DIMENSIONS, "unmodified")

    arms: dict[str, Any] = {}
    for spec in args.labels:
        model, _, path = spec.partition("=")
        predictions = load_labels(Path(path))
        missing = [k for k in truth if k not in predictions]

        def holds(dimension: str, labels: set[str]) -> bool:
            return not labels if dimension == "unmodified" else dimension in labels

        rows: dict[str, Any] = {}
        for dimension in scored:
            pairs = [
                (holds(dimension, fold(predictions.get(key, set()))), holds(dimension, gold_labels))
                for key, gold_labels in truth.items()
            ]
            rows[dimension] = score(pairs)
            if consensus:
                agreed = [
                    (
                        holds(dimension, fold(predictions.get(key, set()))),
                        holds(dimension, truth[key]),
                    )
                    for key in consensus
                ]
                rows[dimension]["on_annotator_consensus"] = score(agreed)

        # The strictest measure: every one of the four dimensions right at once.
        # A span with the correct negation and a spurious `historical` is not a
        # usable answer, because the operator anchored on it edits the wrong cue.
        exact = sum(
            1
            for key, gold_labels in truth.items()
            if fold(predictions.get(key, set())) == gold_labels
        )
        arms[model] = {
            "spans_scored": len(truth),
            "spans_missing_a_prediction": len(missing),
            "predicted_positives": {d: rows[d]["predicted_positives"] for d in scored},
            "exact_label_set_agreement": round(exact / len(truth), 4) if truth else None,
            "by_dimension": rows,
        }
        print(f"== {model}  ({len(truth) - len(missing)}/{len(truth)} spans predicted)")
        print(f"  exact label-set agreement {exact}/{len(truth)} = {exact / len(truth):.4f}")
        for dimension in scored:
            row = rows[dimension]
            tail = ""
            if consensus:
                tail = f"   | consensus F1 {row['on_annotator_consensus']['f1']:.4f}"
            print(
                f"  {dimension:<11} F1 {row['f1']:.4f}  P {row['precision']:.4f}"
                f"  R {row['recall']:.4f}  kappa {row['cohens_kappa']}{tail}"
            )
        print()

    payload = {
        "question": "Do cheap LLMs reach the same assertion judgements as frontier ones?",
        "why": (
            "the gold is two frontier models agreeing at kappa 0.845-0.913, so "
            "that tier is already measured. What is unknown is where the "
            "price/agreement curve bends."
        ),
        "not_a_candidate_detector": (
            "an API call is not replayable, not offline and not hashable into an "
            "operator version, and this package promises deterministic edit "
            "scripts. These arms price the gap between the shipped detector and "
            "the ceiling. A cheap model that scores well is an argument for "
            "DISTILLING it into an encoder, not for calling it at runtime."
        ),
        "circularity": (
            "scoring an LLM against a gold two other LLMs wrote is not an "
            "independent test. It is bounded rather than denied: the annotators "
            "are from a different model family, and every arm is also scored on "
            "the subset where BOTH annotators agreed — where they disagreed "
            "there is no fact for a third model to get right."
        ),
        "split": args.split,
        "n_items": len(truth),
        "n_unmodified": sum(1 for v in truth.values() if not v),
        "gold_positives": {
            **{d: sum(1 for v in truth.values() if d in v) for d in DIMENSIONS},
            "unmodified": sum(1 for v in truth.values() if not v),
        },
        "counts_note": (
            "gold_positives is the denominator of recall and predicted_positives "
            "the denominator of precision; the ratio between them is the "
            "over-calling this comparison is largely about. They do not sum to "
            "n_items because dimensions co-occur and most spans carry none."
        ),
        "n_annotator_consensus": len(consensus),
        "arms": arms,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
