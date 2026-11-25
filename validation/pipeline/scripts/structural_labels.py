#!/usr/bin/env python
"""Stage 3a: what structural label recovery is worth, measured.

`concepts/structural.py` recovers the label half of `Creat-1.1` — a lab analyte
identified by **where it sits** rather than by what surrounds it. It has been in
the repo, tested, and quoted at "+35% procedure recall" from a commit message,
with no committed artifact behind it. This is that artifact, and it exists
because the project's own rule says a figure in prose with no artifact is a
citation to a measurement nobody made.

**Why it is stage 3a and not part of stage 5.** The V0 gate found that 2,152 gold
spans sit in a label slot and 63.8% of them carry no reachable UMLS candidate.
Position is the evidence that identifies them, and position is stage 2's output —
so this is expansion by structure, before candidate generation, not a matcher
setting.

The measurement is a straight on/off: the same matcher, the same notes, the same
gold, with and without the structural emitter. Per category, so a gain in
`procedure` that costs `anatomy` is visible rather than averaged away.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

from robustehr.concepts.expansion import load_expansions
from robustehr.concepts.matcher import ConceptMatcher
from robustehr.concepts.structural import resolve_labels, structural_spans
from robustehr.document import Document
from robustehr.eval import snomed_el
from robustehr.types import Span

CATEGORIES = (
    "disorder",
    "disease",
    "symptom",
    "procedure",
    "anatomy",
    "lab_result",
    "lab_measurement",
)


def score(corpus: Any, predictions: dict[str, list[tuple[Span, frozenset[str]]]]) -> dict[str, Any]:
    """Per-category recall and targeting precision, character-overlap based."""
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"gold": 0, "covered": 0, "predicted": 0, "hits": 0}
    )
    for note_id in sorted(corpus.notes):
        gold = corpus.for_note(note_id)
        mine = predictions.get(note_id, [])
        for category in CATEGORIES:
            relevant = [g for g in gold if category in g.categories]
            chosen = [s for s, cats in mine if category in cats]
            marked: set[int] = set()
            for g in relevant:
                marked.update(range(g.span.start, g.span.end))
            covered: set[int] = set()
            for s in chosen:
                covered.update(range(s.start, s.end))
            t = totals[category]
            t["gold"] += len(relevant)
            t["predicted"] += len(chosen)
            t["covered"] += sum(
                1 for g in relevant if any(i in covered for i in range(g.span.start, g.span.end))
            )
            t["hits"] += sum(1 for s in chosen if any(i in marked for i in range(s.start, s.end)))
    return {
        category: {
            "gold": t["gold"],
            "predicted": t["predicted"],
            "recall": round(t["covered"] / t["gold"], 4) if t["gold"] else None,
            "precision": round(t["hits"] / t["predicted"], 4) if t["predicted"] else None,
        }
        for category, t in sorted(totals.items())
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--split", default="test")
    parser.add_argument("--no-expand", action="store_true", help="disable the expansion table")
    parser.add_argument("--exam-labels", action="store_true", help="enable the HEENT: slot")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    corpus = snomed_el.load(args.root, limit=args.limit)
    if args.split:
        corpus = corpus.split(args.split)

    matcher = ConceptMatcher(args.index)
    without: dict[str, list[tuple[Span, frozenset[str]]]] = {}
    with_labels: dict[str, list[tuple[Span, frozenset[str]]]] = {}
    candidates = resolved = 0
    for note_id, text in sorted(corpus.notes.items()):
        doc = Document.from_text(text, uid=note_id)
        base = [(m.span, m.categories) for m in matcher.annotate(text).mentions]
        extra = list(
            resolve_labels(
                doc,
                matcher,
                expand=not args.no_expand,
                include_exam_labels=args.exam_labels,
            )
        )
        candidates += len(structural_spans(doc, include_exam_labels=args.exam_labels))
        resolved += len(extra)
        without[note_id] = base
        with_labels[note_id] = base + [(m.span, m.categories) for m in extra]

    off = score(corpus, without)
    on = score(corpus, with_labels)
    deltas = {
        category: {
            "recall": round(on[category]["recall"] - off[category]["recall"], 4)
            if off[category]["recall"] is not None and on[category]["recall"] is not None
            else None,
            "precision": round(on[category]["precision"] - off[category]["precision"], 4)
            if off[category]["precision"] is not None and on[category]["precision"] is not None
            else None,
        }
        for category in on
    }

    payload = {
        "question": "What does recovering lab-panel labels by structural position buy?",
        "stage": "3a — structural expansion",
        "why_structural": (
            "a token in the label slot of `Creat-1.1` is a lab analyte because of "
            "WHERE it sits, not because of what surrounds it. Position comes from "
            "stage 2, so no dictionary sense and no surrounding prose are needed — "
            "which is the third answer to 'does expansion need context?' and covers "
            "the largest share of the abbreviation miss set."
        ),
        "method": (
            "same matcher, same notes, same gold, with and without the structural "
            "emitter. Per category, so a gain in one that costs another is visible."
        ),
        "matcher_config": matcher.config.canon(),
        "expansion_table": None
        if args.no_expand
        else {
            "entries": len(load_expansions()),
            "reviewed": load_expansions().reviewed,
            "sha256": load_expansions().sha256,
        },
        "exam_label_slot": args.exam_labels,
        "notes": len(corpus.notes),
        "gold_spans": len(corpus.spans),
        "label_candidates": candidates,
        "labels_resolved": resolved,
        "resolution_rate": round(resolved / candidates, 4) if candidates else None,
        "without_structural": off,
        "with_structural": on,
        "delta": deltas,
        "caveat": (
            "the emitter resolves a label by matching the label surface in "
            "isolation, so a surface absent from UMLS (`creat`, `angap`) still "
            "resolves to nothing. That residue is what the stage-3a expansion "
            "table is for, and resolution_rate is the headroom."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
