#!/usr/bin/env python
"""CTX-D: can a section header act as a cue for `historical`, without becoming a prior?

**The gap this addresses.** 21 of 32 held-out `historical` misses have no cue
anywhere in the span's sentence — the dimension's bottleneck is vocabulary, and
no reordering of scope can reach them. Most sit under a header that says the
section is past.

**The objection this respects.** Assertion is resolved at the span level in this
package, and a blanket section prior — *everything under this header is
historical* — is not span-level evidence. It is an assumption about a
neighbourhood. So the arm measured here treats the header as a **cue**: text in
the note, with a scope, defeasible by other text. What makes that different from
a prior is the defeater — a span whose own sentence says *now*, *new*, *acute*,
*currently* keeps its own framing and the header does not override it.

**A naive version of this fails, and the data says so before it is built.** On
the development half, by section:

    Past Medical History          22/22 historical
    Past Surgical History           2/2
    PAST ONCOLOGIC HISTORY          3/5
    History of Present Illness    10/71
    Brief Hospital Course         11/102

A rule keying on `history` fires on *History of Present Illness*, which is 86%
**not** historical — the HPI is the current admission's story, and its header
contains the word by grammatical accident. A rule keying on `past` gets 27 of 29.
Both are measured below rather than one being assumed.

Four arms, on the development half. The held-out half judges the winner once.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from scripts.split_assertion_gold import keep_items

from robustehr.concepts.context import DIMENSIONS, qualify
from robustehr.document import Document
from robustehr.types import Span

#: Header words that frame a section as past. `past` is the discriminating one;
#: `history` is included in a separate arm precisely to show that it is not.
PAST = re.compile(r"(?<![a-z])past(?![a-z])", re.IGNORECASE)
HISTORY = re.compile(r"(?<![a-z])(?:history|hx)(?![a-z])", re.IGNORECASE)

#: Words that defeat an inherited header frame. A span's own sentence saying the
#: finding is current outranks the section it happens to sit in — which is the
#: whole difference between a cue and a prior.
#:
#: **Present tense only, and the first draft got that wrong.** It included
#: `presented`, `admitted`, `started` and `developed` — all PAST-tense narration,
#: which is the opposite of a present-tense defeater and exactly what a
#: past-history section is full of. Those are removed on the grammar, not on the
#: data: a word list for "this is happening now" cannot contain past participles,
#: whatever it scores.
DEFEATERS = re.compile(
    r"(?<![a-z])(?:now|new|newly|current|currently|today|acute|acutely|"
    r"presents|admits|ongoing|active|persistent|worsening)"
    r"(?![a-z])",
    re.IGNORECASE,
)


def framed_sections(doc: Document, text: str, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    """Body spans of sections whose header matches `pattern`."""
    out = []
    for section in doc.sections:
        if section.header is None:
            continue
        label = text[section.header.label.start : section.header.label.end]
        if pattern.search(label):
            out.append((section.body.start, section.body.end))
    return out


def sentence_of(doc: Document, offset: int) -> tuple[int, int]:
    for sentence in doc.sentences.sentences:
        if sentence.span.start <= offset < sentence.span.end:
            return (sentence.span.start, sentence.span.end)
    return (offset, offset + 1)


def score(
    corpus: dict[str, str],
    by_note: dict[str, list[dict[str, Any]]],
    *,
    pattern: re.Pattern[str] | None,
    defeasible: bool,
) -> dict[str, dict[str, Any]]:
    counts: dict[str, dict[str, int]] = {d: defaultdict(int) for d in DIMENSIONS}
    for note, items in sorted(by_note.items()):
        text = corpus[note]
        doc = Document.from_text(text, uid=note)
        bounds = tuple(s.span.start for s in doc.sentences.sentences)
        spans = tuple(Span(int(i["start"]), int(i["end"])) for i in items)
        index = qualify(text, spans, boundaries=bounds, extended=True)
        frames = framed_sections(doc, text, pattern) if pattern else []
        for item, span in zip(items, spans, strict=True):
            truth = set(item["labels"])
            predicted = set(index.attributes_for(span))
            if any(a <= span.start < b for a, b in frames):
                start, end = sentence_of(doc, span.start)
                if not (defeasible and DEFEATERS.search(text[start:end])):
                    predicted = predicted | {"historical"}
            for dimension in DIMENSIONS:
                if dimension in truth and dimension in predicted:
                    counts[dimension]["tp"] += 1
                elif dimension in truth:
                    counts[dimension]["fn"] += 1
                elif dimension in predicted:
                    counts[dimension]["fp"] += 1
    out = {}
    for dimension, c in counts.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        out[dimension] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4)
            if precision + recall
            else 0.0,
        }
    return out


ARMS: tuple[tuple[str, re.Pattern[str] | None, bool], ...] = (
    ("ctx_c_baseline", None, False),
    ("ctx_d_past", PAST, False),
    ("ctx_d_past_defeasible", PAST, True),
    ("ctx_d_history_naive", HISTORY, True),
)


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    root = Path("data/assertion_gold_mimic")
    parser.add_argument("--gold", type=Path, default=root / "gold.yaml")
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--split-file", type=Path, default=root / "split.json")
    parser.add_argument("--split", default="development", choices=["development", "held_out"])
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/header_frame_sweep.json")
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
        name: score(corpus, by_note, pattern=pattern, defeasible=defeasible)
        for name, pattern, defeasible in ARMS
    }
    base = results["ctx_c_baseline"]["historical"]
    print(f"{args.split}: {len(items)} spans, {len(by_note)} notes")
    print(f"{'arm':<24} {'hist F1':>8} {'delta':>8} {'P':>7} {'R':>7}  other dimensions")
    for name in results:
        row = results[name]["historical"]
        others = " ".join(
            f"{d[:4]} {results[name][d]['f1']:.3f}" for d in DIMENSIONS if d != "historical"
        )
        print(
            f"{name:<24} {row['f1']:>8.4f} {row['f1'] - base['f1']:>+8.4f}"
            f" {row['precision']:>7.4f} {row['recall']:>7.4f}  {others}"
        )

    payload = {
        "question": "Can a section header supply `historical` without becoming a prior?",
        "why": (
            "21 of 32 held-out historical misses have no cue anywhere in the "
            "span's sentence. The dimension's bottleneck is vocabulary and no "
            "scope change can reach them."
        ),
        "what_makes_it_a_cue_not_a_prior": (
            "the defeater. A span whose own sentence says now/new/acute/current "
            "keeps its own framing and the header does not override it. A prior "
            "would apply regardless, which is the thing this package's "
            "span-level rule rejects."
        ),
        "why_past_and_not_history": (
            "on development, `Past Medical History` is 22/22 historical and "
            "`History of Present Illness` is 10/71. A rule keying on `history` "
            "fires on the HPI, whose header contains the word by grammatical "
            "accident while its content is the CURRENT admission. The naive arm "
            "is measured rather than dismissed."
        ),
        "split": args.split,
        "n_items": len(items),
        "n_notes": len(by_note),
        "arms": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
