#!/usr/bin/env python
"""Which categories should a line break stop? Swept one category at a time.

**The boundary sweep found a conflict that a global knob cannot resolve.** Handing
ConText a boundary at every line start lifts `negated` F1 by 0.029 on development
and cuts its false positives from 23 to 10 — and costs `historical` 0.139 and
`uncertain` 0.165. Both effects are real: a negation is local to its clause,
while a hedge or a history frame reaches across a wrapped line the way a reader
does. `boundaries=` applies to every category at once and so has to pick one.

`ConTextRule.terminated_by` does not. A `LINE_BREAK` terminator rule plus a
per-category subscription lets negation stop at the newline while the others
carry on, and this sweeps which categories should subscribe.

**One category at a time, on the development half.** Four categories is sixteen
subsets, small enough to sweep exhaustively — and it is swept exhaustively rather
than greedily, because the categories interact through medspaCy's shared
`update_scopes` pass and a greedy walk could miss the combination.
"""

from __future__ import annotations

import argparse
import itertools
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

#: ConText categories that can subscribe, and the dimension each reports as.
CATEGORIES = {
    "NEGATED_EXISTENCE": "negated",
    "POSSIBLE_EXISTENCE": "uncertain",
    "HYPOTHETICAL": "uncertain",
    "HISTORICAL": "historical",
    "FAMILY": "family",
}

#: The terminator every subscription names.
TERMINATOR = "LINE_BREAK"


def config_for(subscribers: tuple[str, ...]) -> str:
    """The extension resource with `subscribers` cut by a line break."""
    resource = _extension_config()
    scope = dict(resource.get("scope") or {})
    scope["terminated_by"] = {category: [TERMINATOR] for category in subscribers}
    return json.dumps({**resource, "scope": scope}, sort_keys=True)


def score(
    corpus: dict[str, str], by_note: dict[str, list[dict[str, Any]]], config: str
) -> dict[str, dict[str, float | int]]:
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


def macro_f1(result: dict[str, dict[str, float | int]]) -> float:
    """Mean F1 over the three dimensions this effort is trying to raise.

    `family` is excluded because it carries 5 development positives; including
    it would let a change that moved one span dominate the objective.
    """
    return round(sum(float(result[d]["f1"]) for d in ("negated", "uncertain", "historical")) / 3, 4)


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
        "--out", type=Path, default=Path("validation/measurements/scope_termination_sweep.json")
    )
    args = parser.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    items = keep_items(gold["items"], args.split_file, args.split)
    by_note: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_note[str(item["fixture"])].append(item)

    from robustehr.corpus import read_documents

    corpus = {d.uid: d.text for d in read_documents(args.corpus) if d.uid in by_note}

    names = sorted(CATEGORIES)
    rows: list[dict[str, Any]] = []
    print(f"{args.split}: {len(items)} spans, {len(by_note)} notes")
    for size in range(len(names) + 1):
        for subset in itertools.combinations(names, size):
            result = score(corpus, by_note, config_for(subset))
            rows.append(
                {
                    "terminated_by_line_break": list(subset),
                    "macro_f1": macro_f1(result),
                    "per_dimension": result,
                }
            )
            label = "+".join(c.split("_")[0].lower() for c in subset) or "(none)"
            print(
                f"  {label:<44} macro {rows[-1]['macro_f1']:.4f}"
                f"  neg {result['negated']['f1']:.4f}"
                f"  unc {result['uncertain']['f1']:.4f}"
                f"  hist {result['historical']['f1']:.4f}"
            )

    baseline = next(r for r in rows if not r["terminated_by_line_break"])
    best = max(rows, key=lambda r: r["macro_f1"])
    print(f"\nbaseline macro {baseline['macro_f1']}  ->  best {best['macro_f1']}")
    print(f"adopt: {best['terminated_by_line_break'] or '(none — no subset beat the baseline)'}")

    payload = {
        "question": "Which ConText categories should stop at a line break?",
        "why": (
            "a boundary at every line start lifts negated F1 by 0.029 and costs "
            "historical 0.139 and uncertain 0.165 — both real, because a "
            "negation is local to its clause while a hedge reaches across a "
            "wrapped line. `boundaries=` is global and must pick one; "
            "`terminated_by` is per category and does not."
        ),
        "method": (
            "all 2^5 subsets of the ConText categories, scored on the "
            "development half. Exhaustive rather than greedy because categories "
            "interact through medspaCy's shared update_scopes pass."
        ),
        "objective": (
            "mean F1 over negated, uncertain and historical. `family` is "
            "excluded: 5 development positives would let one span dominate."
        ),
        "how_to_read": (
            "development-half figures, where the choice is made. The held-out "
            "half judges the adopted subset once and is not consulted here."
        ),
        "split": args.split,
        "n_items": len(items),
        "n_notes": len(by_note),
        "terminator": TERMINATOR,
        "baseline": baseline,
        "best": best,
        "all_subsets": sorted(rows, key=lambda r: -r["macro_f1"]),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
