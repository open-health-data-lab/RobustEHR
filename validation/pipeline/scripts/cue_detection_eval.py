#!/usr/bin/env python
"""Cue detection, scored directly and compared across implementations.

Every other measurement here scores at the **span** level: did this mention get
the right attribute. That conflates two abilities. A cue that was never found and
a cue that was found and mis-scoped produce the identical wrong span, so a
span-level number cannot say which is failing — and the MIMIC gold's shape
(`historical` precision 0.846 against recall 0.111) says the failure is almost
entirely detection. This measures detection on its own terms.

**Unit of evaluation.** A predicted cue matches a gold cue when their character
spans overlap and the dimension agrees. Overlap rather than exact match, because
`status post` against `status` is a detection success with a boundary
disagreement, and scoring it as a miss would conflate two different problems —
the same reason the concept layer reports character IoU rather than exact spans.

**Arms.**

* **medspaCy stock** — the shipped rule set, 102 rules / 271 triggers.
* **medspaCy extended** — plus `assertion_extensions.yaml` (`s/p`, `status post`,
  `nil`, `NKDA`), mined on the development half only.
* **negspaCy** — an independent implementation of the same algorithm. Negation
  only, so it appears in that row alone; a blank elsewhere is a scope limit, not
  a score of zero.
* **lexicon floor** — every cue literal in medspaCy's rule file, matched as a
  case-insensitive substring with no scope logic at all. This is what pure
  vocabulary buys, and the gap above it is what the *engine* contributes.

The floor matters most. If stock ConText barely beats a substring match, the
engine is not the limiting factor and neither is the algorithm — the vocabulary
is, and that is a different repair.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.split_assertion_gold import load_split

from robustehr.concepts.context import DIMENSIONS, cues_in

#: ConText category -> reported dimension.
CATEGORY = {
    "NEGATED_EXISTENCE": "negated",
    "POSSIBLE_EXISTENCE": "uncertain",
    "HISTORICAL": "historical",
    "HYPOTHETICAL": "uncertain",
    "FAMILY": "family",
}


def note_split(notes: list[str], split_file: Path, split: str | None) -> list[str]:
    """Notes assigned to `split`, read from the one split file both harnesses use.

    **This used to hash-rank note ids under its own salt**, which made it a
    different partition from the span-level split rather than the same one:
    97 of 100 notes had spans in both halves, and 224 of the 399 span-level
    held-out spans sat inside notes this script called development. A cue
    vocabulary mined here had therefore read the majority of the evidence the
    span-level scorer was about to call held out.
    """
    if not split:
        return notes
    loaded = load_split(split_file, split)
    assert loaded is not None  # load_split returns None only for split=None
    _assignment, assigned = loaded
    kept = sorted(n for n in notes if assigned.get(n) == split)
    if not kept:
        raise SystemExit(f"no notes assigned to {split!r} in {split_file}")
    return kept


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def score(predicted: list[tuple[int, int]], gold: list[tuple[int, int]]) -> dict[str, Any]:
    """Precision, recall and F1 over cue occurrences, matched by overlap.

    Greedy one-to-one: each gold cue may be claimed once, so a detector that
    emits three overlapping predictions for one cue scores one hit and two false
    positives rather than three hits.
    """
    unclaimed = list(gold)
    tp = 0
    for p in predicted:
        for i, g in enumerate(unclaimed):
            if overlaps(p, g):
                tp += 1
                unclaimed.pop(i)
                break
    fp = len(predicted) - tp
    fn = len(unclaimed)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "gold": len(gold),
        "predicted": len(predicted),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0.0,
    }


def lexicon_terms() -> dict[str, list[str]]:
    """Every literal in medspaCy's rule file, by dimension — the vocabulary floor."""
    import pathlib

    from robustehr.concepts.matcher import _neutral_cwd

    with _neutral_cwd():
        import medspacy

    root = pathlib.Path(medspacy.__file__).resolve().parents[1]
    rules = json.loads(
        (root / "resources" / "en" / "context_rules.json").read_text(encoding="utf-8")
    )["context_rules"]
    out: dict[str, list[str]] = defaultdict(list)
    for rule in rules:
        dimension = CATEGORY.get(str(rule.get("category")))
        if dimension and rule.get("literal"):
            out[dimension].append(str(rule["literal"]).lower())
    return dict(out)


def lexicon_hits(text: str, terms: list[str]) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    lowered = text.lower()
    for term in terms:
        for m in re.finditer(rf"(?<![a-z]){re.escape(term)}(?![a-z])", lowered):
            found.append((m.start(), m.end()))
    return sorted(set(found))


def negspacy_cues(text: str) -> list[tuple[int, int]]:
    """negspaCy's negation triggers, via its own termset."""
    from robustehr.concepts.matcher import _neutral_cwd

    with _neutral_cwd():
        from negspacy.termsets import termset

    ts = termset("en_clinical").get_patterns()
    terms = [
        t.lower()
        for key in ("pseudo_negations", "preceding_negations", "following_negations")
        for t in ts.get(key, [])
    ]
    return lexicon_hits(text, terms)


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    root = Path("data/assertion_gold_mimic")
    parser.add_argument("--cues", type=Path, default=root / "cues.json")
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--limit", type=int, default=0, help="notes; 0 means all")
    parser.add_argument(
        "--split",
        default=None,
        choices=["development", "held_out"],
        help="note-level 60/40. The cue vocabulary in assertion_extensions.yaml "
        "was mined on `development`, so an extension figure is only honest on "
        "`held_out`",
    )
    parser.add_argument(
        "--split-file", type=Path, default=Path("data/assertion_gold_mimic/split.json")
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    from robustehr.corpus import read_documents
    from robustehr.document import Document

    gold_raw = json.loads(args.cues.read_text(encoding="utf-8"))
    gold: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(lambda: defaultdict(list))
    for cue in gold_raw["items"]:
        # `hypothetical` folds into `uncertain`; the annotation predates the
        # merge and the raw file keeps both so it can be re-derived either way.
        dimension = "uncertain" if cue["dimension"] == "hypothetical" else cue["dimension"]
        gold[cue["note_id"]][dimension].append((cue["start"], cue["end"]))

    notes = note_split(sorted(gold), args.split_file, args.split)
    notes = notes[: args.limit] if args.limit else notes
    texts = {d.uid: d.text for d in read_documents(args.corpus) if d.uid in set(notes)}
    terms = lexicon_terms()

    arms = ("medspacy_stock", "medspacy_extended", "lexicon_floor", "negspacy")
    buckets: dict[str, dict[str, dict[str, list[Any]]]] = {
        a: {d: {"p": [], "g": []} for d in DIMENSIONS} for a in arms
    }

    for note_id in notes:
        text = texts[note_id]
        doc = Document.from_text(text, uid=note_id)
        bounds = tuple(s.span.start for s in doc.sentences.sentences)
        detected = {
            "medspacy_stock": cues_in(text, boundaries=bounds),
            "medspacy_extended": cues_in(text, boundaries=bounds, extended=True),
        }
        for arm, found in detected.items():
            for dimension in DIMENSIONS:
                buckets[arm][dimension]["p"] += [
                    (c.span.start, c.span.end)
                    for c in found
                    if CATEGORY.get(c.category) == dimension
                ]
        for dimension in DIMENSIONS:
            buckets["lexicon_floor"][dimension]["p"] += lexicon_hits(text, terms.get(dimension, []))
        buckets["negspacy"]["negated"]["p"] += negspacy_cues(text)
        for arm in arms:
            for dimension in DIMENSIONS:
                buckets[arm][dimension]["g"] += gold[note_id].get(dimension, [])

    results = {
        arm: {d: score(b[d]["p"], b[d]["g"]) for d in DIMENSIONS} for arm, b in buckets.items()
    }
    # negspaCy detects negation only; a zero elsewhere would read as a score.
    for dimension in DIMENSIONS:
        if dimension != "negated":
            results["negspacy"][dimension] = {"not_applicable": "negation-only implementation"}

    payload = {
        "question": "How well is each implementation detecting assertion cues?",
        "why": (
            "span-level scores conflate finding a cue with scoping it. The MIMIC "
            "gold's shape — historical precision 0.846 against recall 0.111 — "
            "says the failure is detection, and this measures that directly."
        ),
        "unit": "cue occurrence, matched by character overlap plus dimension, greedy one-to-one",
        "notes": len(notes),
        "split": args.split or "all",
        "split_note": (
            "the cue vocabulary was mined on the development notes, so the "
            "medspacy_extended row is only an honest estimate on held_out."
        ),
        "gold_cues": {
            d: len(gold_raw["by_dimension"]) and gold_raw["by_dimension"][d] for d in DIMENSIONS
        },
        "arms": results,
        "how_to_read": (
            "the lexicon floor is the number that matters most. It is every "
            "medspaCy literal matched as a bare substring, with no scope logic "
            "at all. Where stock ConText barely exceeds it, the engine is not "
            "the limiting factor and neither is the algorithm — the vocabulary "
            "is, and vocabulary is a different repair from scope. Where stock "
            "falls BELOW it, the engine's scope pruning is discarding true cues."
        ),
    }
    text_out = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text_out + "\n", encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
