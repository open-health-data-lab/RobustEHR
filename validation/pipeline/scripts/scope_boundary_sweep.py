#!/usr/bin/env python
"""How far should a cue reach? Sweep the unit ConText scopes to.

**ConText's scope is a sentence, so the segmenter is the scope knob.** That is
already this package's one modification to the component — CTX-B feeds it our
boundaries instead of PyRuSH's — but the boundaries fed are sentence starts and
nothing else, and a "sentence" in a discharge summary is routinely a whole lab
block or a bulleted problem list, because the text carries no punctuation to
split on. One `no` then reaches every mention below it.

The error analysis puts a number on that: of the 50 held-out false positives
across the three weak dimensions, **27 have the cue and the target in different
lines, list items or table rows**. The author of the note used layout to separate
them; the scope algorithm cannot see layout.

**Four variants, because "add line breaks" is too blunt.** A line break inside
running prose is a wrap, not a boundary — this package has a whole reflow layer
built on that fact — so splitting on every newline would cut sentences that a
reader joins, trading the false positives for false negatives. The variants
separate the structural line breaks from the cosmetic ones:

* `sentences` — the shipped baseline, sentence starts only.
* `sentences+all_lines` — every line start. The blunt version, measured so the
  cost of bluntness is on the record rather than assumed.
* `sentences+structural` — line starts inside aligned blocks, list items and
  headers only. The hypothesis: these are the breaks the author meant.
* `sentences+aligned` — aligned-block rows alone, the narrowest intervention.

Measured on the development half; the held-out half judges the winner once.
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

from robustehr.concepts.context import DIMENSIONS, qualify
from robustehr.document import Document
from robustehr.types import Span


def sentence_starts(doc: Document) -> set[int]:
    return {s.span.start for s in doc.sentences.sentences}


def all_line_starts(doc: Document) -> set[int]:
    return {line.span.start for line in doc.lines.lines if not line.is_blank}


def structural_line_starts(doc: Document) -> set[int]:
    """Line starts the note's author put there — table rows, list items, headers.

    Deliberately *not* every newline. A wrapped prose paragraph breaks lines for
    width, and this package's reflow layer exists because that break carries no
    meaning; cutting scope there would invent boundaries the reader does not see.
    """
    starts: set[int] = set()
    aligned = {line for block in doc.aligned for line in block.lines}
    by_index = {line.idx: line for line in doc.lines.lines}
    for index in aligned:
        if (line := by_index.get(index)) is not None and not line.is_blank:
            starts.add(line.span.start)
    for block in doc.lists:
        for item in block.items:
            starts.add(item.content.start)
    for header in doc.headers:
        starts.add(header.label.start)
        # The body of an inline header (`ALLERGIES: none`) starts after the
        # marker, and a cue in the heading should not reach the next heading.
        if header.value is not None:
            starts.add(header.value.start)
    return starts


def aligned_line_starts(doc: Document) -> set[int]:
    by_index = {line.idx: line for line in doc.lines.lines}
    return {
        by_index[index].span.start
        for block in doc.aligned
        for index in block.lines
        if index in by_index and not by_index[index].is_blank
    }


#: Boundary variants, each a function of the document. Order is the order
#: reported, from shipped to most aggressive.
VARIANTS: dict[str, Any] = {
    "sentences": sentence_starts,
    "sentences+aligned": lambda doc: sentence_starts(doc) | aligned_line_starts(doc),
    "sentences+structural": lambda doc: sentence_starts(doc) | structural_line_starts(doc),
    "sentences+all_lines": lambda doc: sentence_starts(doc) | all_line_starts(doc),
}


def score(
    corpus: dict[str, str],
    by_note: dict[str, list[dict[str, Any]]],
    boundaries_of: Any,
    *,
    extended: bool,
) -> dict[str, dict[str, float | int]]:
    counts: dict[str, dict[str, int]] = {d: defaultdict(int) for d in DIMENSIONS}
    for note, items in sorted(by_note.items()):
        text = corpus[note]
        doc = Document.from_text(text, uid=note)
        bounds = tuple(sorted(boundaries_of(doc)))
        spans = tuple(Span(int(i["start"]), int(i["end"])) for i in items)
        index = qualify(text, spans, boundaries=bounds, extended=extended)
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
    parser.add_argument("--extended", action="store_true", default=True)
    parser.add_argument("--stock", dest="extended", action="store_false")
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/scope_boundary_sweep.json")
    )
    args = parser.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    items = keep_items(gold["items"], args.split_file, args.split)
    by_note: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_note[str(item["fixture"])].append(item)

    from robustehr.corpus import read_documents

    corpus = {d.uid: d.text for d in read_documents(args.corpus) if d.uid in by_note}

    results = {
        name: score(corpus, by_note, fn, extended=args.extended) for name, fn in VARIANTS.items()
    }
    baseline = results["sentences"]

    print(f"{args.split}: {len(items)} spans, {len(by_note)} notes, extended={args.extended}")
    for name, result in results.items():
        print(f"\n  {name}")
        for dimension in DIMENSIONS:
            row, base = result[dimension], baseline[dimension]
            delta = float(row["f1"]) - float(base["f1"])
            print(
                f"    {dimension:<11} F1 {row['f1']:.4f} ({delta:+.4f})"
                f"  P {row['precision']:.4f}  R {row['recall']:.4f}"
                f"  fp {row['fp']:>3} ({int(row['fp']) - int(base['fp']):+d})"
            )

    payload = {
        "question": "What unit should a cue's scope stop at?",
        "why": (
            "ConText scopes a cue to its sentence, so the segmenter IS the scope "
            "knob. A sentence in a discharge summary is routinely a whole lab "
            "block, and 27 of 50 held-out false positives have the cue and the "
            "target in different lines, list items or table rows — separated by "
            "layout the scope algorithm cannot see."
        ),
        "why_not_every_newline": (
            "a line break inside running prose is a wrap, not a boundary — this "
            "package has a reflow layer built on that fact. Splitting on every "
            "newline would trade false positives for false negatives, so the "
            "structural variant is the hypothesis and the blunt one is the "
            "control that prices it."
        ),
        "how_to_read": (
            "development-half figures, which is where the choice is made. The "
            "held-out half judges the adopted variant once and is not consulted "
            "here."
        ),
        "split": args.split,
        "arm": "medspacy_extended" if args.extended else "medspacy_stock",
        "n_items": len(items),
        "n_notes": len(by_note),
        "variants": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
