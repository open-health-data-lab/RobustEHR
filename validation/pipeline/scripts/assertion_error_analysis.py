#!/usr/bin/env python
"""Why did stage 8 get this span wrong? Every error attributed to a cause.

**The gap this closes.** The repository can say *how often* the detector is
wrong, per dimension, on two instruments. It cannot say *why*, and the two
questions have opposite answers depending on the dimension — so a fix chosen
from the F1 table alone is a guess. `cue_detection_eval.py` scores cue
occurrences without ever joining them to the spans those cues should have
governed; `missing_cues.py` looks only at misses, and only at their left
context; `assertion_disagreement.py` has a cause vocabulary but adjudicates one
segmenter against another rather than a prediction against gold.

**What it measures.** Each gold span is scored against the detector, and every
disagreement is partitioned:

* a **false negative** is *cue-absent* when no cue of that dimension appears
  anywhere in the span's sentence, and *cue-present-but-unscoped* when one does.
  The first is a vocabulary problem and the second a scope problem, and they are
  fixed by opposite changes — more triggers versus wider reach.
* a **false positive** is attributed by asking what the note's *layout* says:
  `concepts.context.separation` reports whether the cue and the target sit in
  different list items, different rows of an aligned block, different lines or
  different sections. What remains is a genuine same-line scope error.

Everything else — a cue-present FN, a same-line FP — is the residue that cannot
be blamed on structure or vocabulary, and is the honest measure of how much the
published algorithm itself is getting wrong on this corpus.

**For the false-negative side the cue direction is also recorded**, because a
cue sitting *after* its target with a FORWARD-only rule is unreachable by any
amount of extra vocabulary, and the fix is a one-word change to the rule.

Licensing: counts only. No surface, no sentence, no note id reaches the
artifact, and the script refuses to emit anything else from a `restricted` gold.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from scripts.split_assertion_gold import keep_items

from robustehr.concepts.context import DIMENSIONS, Cue, cues_in, qualify, separation
from robustehr.document import Document
from robustehr.types import Span

#: ConText's rule categories mapped to the dimensions this package reports.
#: Mirrors `context._NAMES`, which keys on spaCy attribute names rather than on
#: the rule file's categories.
CATEGORY = {
    "NEGATED_EXISTENCE": "negated",
    "POSSIBLE_EXISTENCE": "uncertain",
    "HYPOTHETICAL": "uncertain",
    "HISTORICAL": "historical",
    "FAMILY": "family",
}


def sentence_bounds(doc: Document) -> list[tuple[int, int]]:
    return [(s.span.start, s.span.end) for s in doc.sentences.sentences]


def enclosing(bounds: list[tuple[int, int]], offset: int) -> tuple[int, int]:
    for start, end in bounds:
        if start <= offset < end:
            return (start, end)
    return (offset, offset + 1)


def attribute_false_negative(
    dimension: str, span: Span, sentence: tuple[int, int], cues: list[Cue]
) -> tuple[str, str | None]:
    """``(cause, direction)`` for a missed dimension on this span."""
    local = [c for c in cues if sentence[0] <= c.span.start < sentence[1]]
    matching = [c for c in local if CATEGORY.get(c.category) == dimension]
    if not matching:
        return ("cue absent from the sentence", None)
    # Which side the nearest cue sits on decides whether vocabulary or direction
    # is the blocker: a FORWARD rule can never reach a target to its left.
    nearest = min(matching, key=lambda c: abs(c.span.start - span.start))
    side = "cue before target" if nearest.span.end <= span.start else "cue after target"
    return (f"cue present but unscoped, {side}", nearest.direction)


def attribute_false_positive(dimension: str, doc: Document, span: Span, cues: list[Cue]) -> str:
    """Why a dimension was asserted that the gold does not carry."""
    governing = [
        c
        for c in cues
        if CATEGORY.get(c.category) == dimension
        and c.scope.start <= span.start
        and span.end <= c.scope.end
    ]
    if not governing:
        return "no locatable cue"
    nearest = min(governing, key=lambda c: abs(c.span.start - span.start))
    return separation(doc, nearest.span, span) or "same line, scope error"


def attribute_all(
    by_note: dict[str, list[dict[str, Any]]],
    texts: dict[str, str],
    dimensions: list[str],
    *,
    extended: bool,
) -> tuple[
    dict[str, Counter[str]],
    dict[str, Counter[str]],
    dict[str, Counter[str]],
    dict[str, Counter[str]],
    int,
]:
    """Score every span and attribute every disagreement.

    Runs on the CTX-B composition — this package's sentence boundaries — because
    that is what the shipped pipeline uses, and an error analysis of a
    configuration nobody runs would steer the wrong fixes.
    """
    outcomes: dict[str, Counter[str]] = {d: Counter() for d in dimensions}
    fn_cause: dict[str, Counter[str]] = {d: Counter() for d in dimensions}
    fn_direction: dict[str, Counter[str]] = {d: Counter() for d in dimensions}
    fp_cause: dict[str, Counter[str]] = {d: Counter() for d in dimensions}
    unqualified = 0

    for note, note_items in sorted(by_note.items()):
        text = texts[note]
        doc = Document.from_text(text, uid=note)
        bounds = tuple(s.span.start for s in doc.sentences.sentences)
        sentences = sentence_bounds(doc)
        spans = tuple(Span(int(i["start"]), int(i["end"])) for i in note_items)
        index = qualify(text, spans, boundaries=bounds, extended=extended)
        cues = list(cues_in(text, boundaries=bounds, extended=extended))
        for item, span in zip(note_items, spans, strict=True):
            if not index.is_qualified(span):
                unqualified += 1
            truth, predicted = set(item["labels"]), set(index.attributes_for(span))
            sentence = enclosing(sentences, span.start)
            for dimension in dimensions:
                if dimension in truth and dimension in predicted:
                    outcomes[dimension]["tp"] += 1
                elif dimension in truth:
                    outcomes[dimension]["fn"] += 1
                    cause, direction = attribute_false_negative(dimension, span, sentence, cues)
                    fn_cause[dimension][cause] += 1
                    if direction:
                        fn_direction[dimension][direction] += 1
                elif dimension in predicted:
                    outcomes[dimension]["fp"] += 1
                    fp_cause[dimension][attribute_false_positive(dimension, doc, span, cues)] += 1
                else:
                    outcomes[dimension]["tn"] += 1
    return outcomes, fn_cause, fn_direction, fp_cause, unqualified


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("data/assertion_gold_mimic/gold.yaml"))
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument(
        "--split-file", type=Path, default=Path("data/assertion_gold_mimic/split.json")
    )
    parser.add_argument("--split", default=None, choices=["development", "held_out"])
    parser.add_argument("--extended", action="store_true", help="use the mined cue extensions")
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/assertion_error_analysis.json")
    )
    args = parser.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    items = keep_items(gold["items"], args.split_file, args.split)

    by_note: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_note[str(item["fixture"])].append(item)

    from robustehr.corpus import read_documents

    texts = {d.uid: d.text for d in read_documents(args.corpus) if d.uid in by_note}
    missing = sorted(set(by_note) - set(texts))
    if missing:
        raise SystemExit(f"{len(missing)} notes in the gold are absent from {args.corpus}")

    dimensions = [d for d in DIMENSIONS if d in set(gold["dimensions"])]
    outcomes, fn_cause, fn_direction, fp_cause, unqualified = attribute_all(
        by_note, texts, dimensions, extended=args.extended
    )

    per_dimension = {}
    for dimension in dimensions:
        counts = outcomes[dimension]
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        per_dimension[dimension] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": counts["tn"],
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "false_negatives_by_cause": dict(fn_cause[dimension].most_common()),
            "false_negative_cue_direction": dict(fn_direction[dimension].most_common()),
            "false_positives_by_cause": dict(fp_cause[dimension].most_common()),
            "bottleneck": _bottleneck(tp, fp, fn, fn_cause[dimension]),
        }

    payload = {
        "question": "Why is stage 8 wrong when it is wrong?",
        "why": (
            "The F1 tables say how often, never why, and the answer differs by "
            "dimension — so a fix chosen from them alone is a guess. This "
            "partitions every error into a cause that names the change which "
            "would repair it."
        ),
        "how_to_read": (
            "A false negative with the cue ABSENT is a vocabulary problem; one "
            "with the cue PRESENT is a scope problem, and if the cue sits after "
            "the target a FORWARD-only rule can never reach it whatever the "
            "vocabulary. A false positive attributed to a structural separation "
            "is a boundary problem — the cue and the target are in different "
            "lines, list items or table rows, so the sentence the scope ran to "
            "is not a unit the note's author wrote. What is left is the "
            "published algorithm's own residual error on this corpus."
        ),
        "arm": "medspacy_extended" if args.extended else "medspacy_stock",
        "boundaries": "this package's sentence boundaries (CTX-B composition)",
        "split": args.split or "all",
        "n_items": len(items),
        "n_notes": len(by_note),
        "unqualified_spans": unqualified,
        "unqualified_note": (
            "spans qualify() dropped — char_span widening or the widest-wins "
            "overlap rule. They score as affirmed, so a dropped gold positive "
            "would be an automatic false negative no cue change could repair."
        ),
        "restricted_source": bool(gold.get("restricted")),
        "dimensions": dimensions,
        "by_dimension": per_dimension,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"{len(items)} spans over {len(by_note)} notes ({args.split or 'all'}) -> {args.out}")
    for dimension in dimensions:
        row = per_dimension[dimension]
        print(
            f"\n## {dimension}  tp={row['tp']} fp={row['fp']} fn={row['fn']}"
            f"  P={row['precision']} R={row['recall']}  -> {row['bottleneck']}"
        )
        for cause, n in row["false_negatives_by_cause"].items():
            print(f"     FN  {cause:<44} {n}")
        for cause, n in row["false_positives_by_cause"].items():
            print(f"     FP  {cause:<44} {n}")
    return 0


def _bottleneck(tp: int, fp: int, fn: int, causes: Counter[str]) -> str:
    """One phrase naming what to fix first for this dimension."""
    if fp > fn:
        return "precision — over-scoping"
    absent = sum(n for c, n in causes.items() if c.startswith("cue absent"))
    if absent > fn / 2:
        return "recall — cue vocabulary"
    if fn > tp:
        return "recall — scope reach"
    return "balanced"


if __name__ == "__main__":
    raise SystemExit(main())
