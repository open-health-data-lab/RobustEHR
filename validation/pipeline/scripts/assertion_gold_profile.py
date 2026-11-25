#!/usr/bin/env python
"""What kind of concept carries an assertion modifier, in the gold.

A per-dimension F1 treats every span as interchangeable. They are not: a
`disease` and a `medication` are qualified by different constructions, and a
detector that is strong on one may be weak on the other for reasons the pooled
number hides. `negated` on a disease is *the patient does not have it*;
`uncertain` on a medication is usually *take it only if*, which is a different
linguistic phenomenon wearing the same label.

This profiles the gold along that axis: how the 1,000 annotated spans distribute
over semantic categories, what share of each category carries a modifier, and where
the detector's error concentrates. It is the answer to "what were you actually
annotating", which the dimension counts alone do not give.

**Categories come from the sampler, not from this script.** The corpus was
filtered to clinical semantic categories via `categories.categories_of` before
any span was drawn, so the distribution here is a property of the sample rather
than a post-hoc rationalisation of it.

Every span carries one or two category labels, and the pairs are hierarchical —
`disease` implies `disorder`, `diagnostic_procedure` implies `procedure`. The
most specific label is used so the table partitions the spans exactly rather than
double-counting the 535 that are `disorder` in the broad sense.

Licensing: reads a restricted gold and emits **counts only**. No surface, no
sentence, no note id reaches the artifact — CUIs are UMLS identifiers, which may
ship, but they are aggregated away here in any case.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from robustehr.concepts import context

#: Broad-to-specific precedence. A span labelled `{disorder, finding}` is
#: reported as `finding`, because `disorder` admits it only by being the wider
#: class. Ordered most specific first; the first match wins.
PRECEDENCE = (
    "medication",
    "diagnostic_procedure",
    "therapeutic_procedure",
    "symptom",
    "disease",
    "finding",
    "disorder",
    "procedure",
)


def most_specific(categories: list[str]) -> str:
    """The narrowest category this span belongs to."""
    for name in PRECEDENCE:
        if name in categories:
            return name
    return "uncategorised"


def detector_predictions(
    gold: dict[str, Any], corpus: Path
) -> dict[tuple[str, int, int], set[str]]:
    """The shipped arm's labels for every gold span.

    `qualify_document`'s composition — our sentence boundaries plus the mined cue
    extensions — because the question is what the package as shipped does on each
    concept type, not what some configuration could do.
    """
    from robustehr.concepts.context import qualify
    from robustehr.corpus import read_documents
    from robustehr.document import Document
    from robustehr.types import Span

    by_note: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in gold["items"]:
        by_note[str(item["fixture"])].append(item)

    out: dict[tuple[str, int, int], set[str]] = {}
    for document in read_documents(corpus):
        items = by_note.get(document.uid)
        if not items:
            continue
        text = document.text
        parsed = Document.from_text(text, uid=document.uid)
        bounds = tuple(s.span.start for s in parsed.sentences.sentences)
        spans = tuple(Span(int(i["start"]), int(i["end"])) for i in items)
        index = qualify(text, spans, boundaries=bounds, extended=True)
        for span in spans:
            out[(document.uid, span.start, span.end)] = set(index.attributes_for(span))
    return out


def score_by_category(
    gold: dict[str, Any],
    category_of: dict[tuple[str, int, int], str],
    by_category: dict[str, dict[str, Any]],
    corpus: Path,
) -> None:
    """Attach the shipped detector's per-category agreement, in place.

    **Exact-label-set agreement**, not per-dimension F1. The question is on what
    kind of concept this detector produces a usable answer, and a span with the
    right negation but a spurious `historical` is not a usable answer — the
    operator anchored on it would edit the wrong cue.
    """
    predictions = detector_predictions(gold, corpus)
    agree: dict[str, list[bool]] = defaultdict(list)
    worst: dict[str, Counter[str]] = defaultdict(Counter)
    for item in gold["items"]:
        key = (str(item["fixture"]), int(item["start"]), int(item["end"]))
        category = category_of.get(key)
        if category is None or key not in predictions:
            continue
        truth, guess = set(item["labels"]), predictions[key]
        agree[category].append(truth == guess)
        for dimension in truth ^ guess:
            worst[category][dimension] += 1
    for category, flags in agree.items():
        by_category[category]["detector_exact_agreement"] = round(sum(flags) / len(flags), 4)
        by_category[category]["detector_errors_by_dimension"] = dict(worst[category].most_common())


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("data/assertion_gold_mimic/gold.yaml"))
    parser.add_argument(
        "--sample", type=Path, default=Path("data/assertion_gold_mimic/sample.json")
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="score the shipped detector per category as well as profiling the gold",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/assertion_gold_profile.json")
    )
    args = parser.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    sample = json.loads(args.sample.read_text(encoding="utf-8"))

    category_of = {
        (s["note_id"], int(s["start"]), int(s["end"])): most_specific(s["categories"])
        for s in sample["spans"]
    }
    cui_of = {(s["note_id"], int(s["start"]), int(s["end"])): s.get("cui") for s in sample["spans"]}

    dimensions = list(context.DIMENSIONS)
    by_category: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "unmodified": 0, **{d: 0 for d in dimensions}}
    )
    distinct_cuis: dict[str, set[str]] = defaultdict(set)
    unmatched = 0

    for item in gold["items"]:
        key = (str(item["fixture"]), int(item["start"]), int(item["end"]))
        category = category_of.get(key)
        if category is None:
            unmatched += 1
            continue
        row = by_category[category]
        row["n"] += 1
        labels = list(item["labels"])
        if not labels:
            row["unmodified"] += 1
        for label in labels:
            row[label] += 1
        if (cui := cui_of.get(key)) is not None:
            distinct_cuis[category].add(str(cui))

    if args.corpus is not None:
        score_by_category(gold, category_of, by_category, args.corpus)

    for category, row in by_category.items():
        row["distinct_cuis"] = len(distinct_cuis[category])
        # The union is checkable against its members only if the overlap is
        # published: `sum of dimension counts - non_affirmed` is the number of
        # spans carrying two labels, and without it the row looks like an
        # arithmetic error rather than inclusion-exclusion.
        row["label_instances"] = sum(row[d] for d in dimensions)
        row["modified"] = row["n"] - row["unmodified"]
        row["multi_label_spans"] = row["label_instances"] - row["modified"]
        row["modifier_rate"] = round(row["modified"] / row["n"], 4) if row["n"] else 0.0
        for dimension in dimensions:
            row[f"{dimension}_rate"] = round(row[dimension] / row["n"], 4) if row["n"] else 0.0

    total = sum(r["n"] for r in by_category.values())
    overall = {d: sum(r[d] for r in by_category.values()) for d in dimensions}
    payload = {
        "question": "What kind of concept carries each assertion in the gold?",
        "why": (
            "A pooled per-dimension F1 treats every span as interchangeable. A "
            "disease and a medication are qualified by different constructions, "
            "so the mix of concepts in a gold determines what its numbers mean. "
            "This states the mix."
        ),
        "restricted_source": bool(gold.get("restricted")),
        "modified_means": (
            "the span carries at least one of the four modifiers — the UNION of "
            "the dimension columns. `label_instances` is their sum and "
            "`multi_label_spans` the difference, so the inclusion-exclusion is "
            "checkable per row: dimensions co-occur, and `no history of X` is "
            "negated AND historical. Its complement, `unmodified`, is what "
            "ConText and this codebase call `affirmed`."
        ),
        "why_not_non_affirmed": (
            "because it is false for two of the four. `historical` does not "
            "withhold the assertion — `history of hypertension` AFFIRMS the "
            "hypertension and locates it in the past; `family` affirms the "
            "finding in someone else. Only `negated` truly withholds, and "
            "`uncertain` only partly. `non-affirmed` is accurate only with the "
            "trailing qualifier `about the patient now`, which drops off every "
            "time the term is used alone. Each dimension MODIFIES the asserted "
            "presence of the concept, which is what the SEMANTIC operators flip, "
            "so `modifier` is both positively defined and true of all four."
        ),
        "why_not_positive": (
            "it inverts between frames. Clinically, `positive for pneumonia` "
            "means the patient has it — an UNMODIFIED span here. In the scorer, "
            "`gold_positives` for `negated` counts spans that ARE negated, which "
            "is clinically negative. `modified`/`unmodified` describes what the "
            "note does to the concept and does not flip between those readings."
        ),
        "publishable": (
            "counts only. Surfaces, sentences and note ids stay in data/; the "
            "categories are derived from UMLS semantic types, which are "
            "identifiers rather than licensed strings."
        ),
        "how_categories_were_assigned": (
            "by `categories.categories_of` at sampling time, before annotation. "
            "Where a span carries a broad and a narrow label the narrow one is "
            "reported, so the table partitions the spans rather than "
            "double-counting the hierarchy."
        ),
        "precedence": list(PRECEDENCE),
        "n_spans": total,
        "unmatched_spans": unmatched,
        "dimensions": dimensions,
        "overall_label_counts": overall,
        "by_category": {k: dict(v) for k, v in sorted(by_category.items())},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"{total} spans over {len(by_category)} categories -> {args.out}")
    header = f"  {'category':<24}{'n':>6}{'modified':>10}" + "".join(f"{d:>12}" for d in dimensions)
    print(header)
    for category, row in sorted(by_category.items(), key=lambda kv: -kv[1]["n"]):
        cells = "".join(f"{row[d]:>6} {row[f'{d}_rate']:>5.1%}" for d in dimensions)
        exact = row.get("detector_exact_agreement")
        tail = f"   detector {exact:.1%}" if exact is not None else ""
        print(f"  {category:<24}{row['n']:>6}{row['modifier_rate']:>9.1%} {cells}{tail}")
    if unmatched:
        print(f"  ({unmatched} gold spans had no sample entry)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
