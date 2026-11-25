#!/usr/bin/env python
"""Which cues is the detector missing, and how much recall would they buy?

`assertion_gold_mimic.json` reports a specific and lopsided failure: on real
discharge summaries the detector's precision is respectable and its **recall
collapses** — `historical` 0.111, `uncertain` 0.293. It
finds 13 of 99 historical spans. A rule set that is right when it fires and
almost never fires is missing triggers, not mis-scoping them.

Two candidates were known before this script existed, and both are confirmed
absent: ``s/p`` and ``status post`` produce **no cue at all**, and neither does
``nil``. Those are ordinary discharge-summary usage. The question this answers is
how much else is missing, and whether a cue extension is worth building.

**The gate is the same one that redirected stages 3 and 4.** Measure the ceiling
before writing the component: for every gold-positive span the detector missed,
look at the words preceding it and count which ones recur. A word that appears
before many missed spans of one dimension and rarely before affirmed spans is a
candidate trigger; the sum over candidates bounds what an extension could
recover. If that bound is small, the honest answer is a limitation rather than a
rule file.

**Precision matters as much as coverage**, so each candidate is scored on both:
how often it precedes a span the gold marks with the dimension, against how often
it precedes one the gold does not. A word that precedes everything — `the`, `and`
— buys recall and destroys precision, and the ratio is what separates them.

**Candidate words are note-derived, so a restricted gold splits the output.**
The words are lifted from MIMIC text; requiring `MIN_OCCURRENCES` distinct
missed spans makes them overwhelmingly clinical function terms rather than note
content, but "overwhelmingly" is not a disclosure rule. When the gold declares
`restricted: true` the committed artifact carries **counts and the recall
ceiling only** and the candidate words go to a `data/` sidecar, which
`.gitignore` default-denies. The published number — what a cue extension could
buy — survives; the strings it was derived from do not.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from scripts.split_assertion_gold import keep_items

from robustehr.concepts.context import qualify
from robustehr.document import Document
from robustehr.types import Span

_WORD = re.compile(r"[A-Za-z][A-Za-z/.'-]*")

#: Tokens of left context searched for a trigger. Wide enough to reach a cue at
#: the head of a clause, narrow enough that a candidate is plausibly governing.
LEFT_TOKENS = 6

#: A candidate must precede at least this many distinct missed spans. Below it,
#: an apparent pattern is one note's phrasing.
MIN_OCCURRENCES = 3


def left_words(text: str, span: Span, n: int) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(text[: span.start])][-n:]


def redact_if_restricted(gold: dict[str, Any], report: dict[str, Any], candidates: Path) -> bool:
    """Move note-derived candidate words out of the committed artifact.

    Split here rather than filtered at each emission site, so there is exactly
    one place where the words leave the payload and one place to audit.
    """
    if not gold.get("restricted"):
        return False
    sidecar = {
        "handling": (
            "candidate words lifted from MIMIC note text under the PhysioNet "
            "Credentialed Health Data Use Agreement. Stays in data/."
        ),
        "dimensions": report,
    }
    candidates.parent.mkdir(parents=True, exist_ok=True)
    candidates.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for row in report.values():
        row["high_precision_candidates"] = [
            {k: v for k, v in c.items() if k != "word"}
            for c in row.get("high_precision_candidates", [])
        ]
    return True


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("data/assertion_gold_mimic/gold.yaml"))
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument(
        "--split-file", type=Path, default=Path("data/assertion_gold_mimic/split.json")
    )
    parser.add_argument("--split", default=None, choices=["development", "held_out"])
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/assertion_gold_mimic/cue_candidates.json"),
        help="where the note-derived candidate words go when the gold is restricted",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    from robustehr.corpus import read_documents

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    gold["items"] = keep_items(gold["items"], args.split_file, args.split)
    dimensions = list(gold["dimensions"])
    by_note: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in gold["items"]:
        by_note[item["fixture"]].append(item)
    texts = {d.uid: d.text for d in read_documents(args.corpus) if d.uid in by_note}

    # For each dimension: words before spans the detector MISSED, and words
    # before spans the gold says do NOT carry it. The second is the precision
    # control — without it every common word looks like a trigger.
    missed: dict[str, Counter[str]] = {d: Counter() for d in dimensions}
    elsewhere: dict[str, Counter[str]] = {d: Counter() for d in dimensions}
    totals = {d: 0 for d in dimensions}

    for note_id, items in sorted(by_note.items()):
        text = texts[note_id]
        doc = Document.from_text(text, uid=note_id)
        spans = tuple(Span(int(i["start"]), int(i["end"])) for i in items)
        bounds = tuple(s.span.start for s in doc.sentences.sentences)
        index = qualify(text, spans, boundaries=bounds)
        for item, span in zip(items, spans, strict=True):
            truth = set(item["labels"])
            predicted = set(index.attributes_for(span))
            words = set(left_words(text, span, LEFT_TOKENS))
            for dimension in dimensions:
                if dimension in truth:
                    totals[dimension] += 1
                    if dimension not in predicted:
                        missed[dimension].update(words)
                else:
                    elsewhere[dimension].update(words)

    report = {}
    for dimension in dimensions:
        candidates = []
        for word, hits in missed[dimension].most_common():
            if hits < MIN_OCCURRENCES:
                continue
            other = elsewhere[dimension][word]
            # Precision proxy: of the spans this word precedes, the share the
            # gold marks with the dimension.
            precision = hits / (hits + other)
            candidates.append(
                {
                    "word": word,
                    "precedes_missed": hits,
                    "precedes_negative": other,
                    "precision_proxy": round(precision, 4),
                }
            )
        candidates.sort(key=lambda c: (-c["precision_proxy"], -c["precedes_missed"]))
        strong = [c for c in candidates if c["precision_proxy"] >= 0.5]
        report[dimension] = {
            "gold_positives": totals[dimension],
            "candidates_considered": len(candidates),
            "high_precision_candidates": strong[:15],
            "ceiling_if_all_strong_adopted": round(
                min(sum(c["precedes_missed"] for c in strong), totals[dimension])
                / totals[dimension],
                4,
            )
            if totals[dimension]
            else None,
        }

    restricted = redact_if_restricted(gold, report, args.candidates)

    payload = {
        "question": "Which triggers is the rule set missing, and what would adding them buy?",
        "restricted_source": restricted,
        "candidate_words": (
            f"withheld — note-derived; full list in {args.candidates}"
            if restricted
            else "published; this gold is synthetic"
        ),
        "why": (
            "on real discharge summaries the detector's recall collapses while "
            "its precision holds — historical 0.111. That is "
            "the signature of missing triggers rather than mis-scoped ones. "
            "`s/p`, `status post` and `nil` were confirmed to produce no cue at "
            "all before this ran."
        ),
        "method": (
            f"for every gold-positive span the detector missed, the {LEFT_TOKENS} "
            "preceding word types are counted, against the same counts over spans "
            "the gold does NOT mark. The ratio is a precision proxy: a word that "
            "precedes everything buys recall and destroys precision."
        ),
        "left_tokens": LEFT_TOKENS,
        "min_occurrences": MIN_OCCURRENCES,
        "dimensions": report,
        "how_to_read": (
            "`ceiling_if_all_strong_adopted` is an OPTIMISTIC bound on what a cue "
            "extension could recover, not a promise: it assumes every candidate "
            "becomes a working rule with its proxy precision intact, and it "
            "double-counts spans preceded by more than one candidate. Treat it as "
            "the gate — if the ceiling is small the honest answer is a documented "
            "limitation, not a rule file."
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
