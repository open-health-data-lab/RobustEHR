#!/usr/bin/env python
"""Split the MIMIC gold 60/40 **by note**, stratified, so nothing leaks.

**This exists because the first cue extension was fitted and scored on the same
1,000 spans.** `missing_cues.py` mined `s/p`, `status post` and `nil` from the
gold's false negatives, and `assertion_gold_eval.py` then reported that adding
them lifted `historical` recall — on those same spans. That figure is in-sample.

**And the first fix for that was not enough, which is why this splits notes.**
The original version split *spans*, stratified on the exact label combination.
`cue_detection_eval.py` meanwhile hash-ranked *notes* under a different salt and
never read this file at all. The two partitions were of different units, so they
overlapped: **97 of 100 notes had spans in both halves, and 224 of the 399
span-level held-out spans sat inside notes the cue miner treated as
development** — 56% of the supposedly held-out evidence. A vocabulary mined from
a note's prose has seen the phrasing of every span in that note, wherever the
span-level split happened to put it.

So the unit of the split is the **note**, one file governs both harnesses, and no
note appears in both halves. This changes which spans are held out, so every
held-out number moves; that is a change of instrument, not of detector, and the
two are reported separately.

**Stratified on the scarcest dimension the note carries.** Stratifying notes on
their exact label combination gives 16 strata of which the smallest holds one
note — too sparse to divide. Ordering the dimensions by scarcity (`family` 9
positives, `negated` 81, `historical` 99, `uncertain` 119) and keying each note
on the scarcest it contains gives five strata, and keeps `family` — which cannot
survive an unstratified draw — present in both halves.

**Hash-ranked within each stratum**, per the house rule (`rng.py:22`): the split
is a property of the note ids and the salt, so it replays exactly and does not
depend on iteration order.

The split lives in `data/` beside the gold — it is note-derived and inherits the
same handling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

DEV = "development"
HELD_OUT = "held_out"

#: Dimensions from scarcest to commonest, by gold positives. A note's stratum is
#: the first of these it carries, so the rarest evidence governs placement and
#: `family` cannot end up concentrated in one half.
SCARCITY = ("family", "negated", "historical", "uncertain")


def stratum(items: list[dict[str, Any]]) -> str:
    """The scarcest dimension this note carries, or ``affirmed`` for none."""
    present = {label for item in items for label in item["labels"]}
    for dimension in SCARCITY:
        if dimension in present:
            return dimension
    return "affirmed"


def rank(salt: str, note: str) -> str:
    return hashlib.blake2b(f"{salt}\x1f{note}".encode(), digest_size=16).hexdigest()


def load_split(path: Path, split: str | None) -> tuple[dict[str, str], dict[str, str]] | None:
    """``(spans, notes)`` assignments, or ``None`` when scoring everything.

    **Raises when a split was asked for and the file is not there.** The two
    call sites this replaces both fell back silently, which prints
    ``split: held_out`` while scoring all 1,000 spans — a mistake that reads as
    a result. Every consumer reads this one file, which is what stops the two
    harnesses from drifting into different partitions again.
    """
    if split is None:
        return None
    if split not in (DEV, HELD_OUT):
        raise SystemExit(f"unknown split {split!r}; expected {DEV} or {HELD_OUT}")
    if not path.exists():
        raise SystemExit(f"--split {split} was requested but {path} does not exist")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("unit") != "note":
        raise SystemExit(
            f"{path} is a span-level split; re-run split_assertion_gold.py. "
            "Mining on a span-level split leaks: 97 of 100 notes had spans in "
            "both halves."
        )
    return dict(payload["assignment"]), dict(payload["notes"])


def keep_items(items: list[dict[str, Any]], path: Path, split: str | None) -> list[dict[str, Any]]:
    """Gold items belonging to `split`, or all of them when `split` is None."""
    loaded = load_split(path, split)
    if loaded is None:
        return list(items)
    assignment, _notes = loaded
    kept = [i for i in items if assignment.get(f"{i['fixture']}:{i['start']}:{i['end']}") == split]
    if not kept:
        raise SystemExit(f"no items assigned to {split!r} in {path}")
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    root = Path("data/assertion_gold_mimic")
    parser.add_argument("--gold", type=Path, default=root / "gold.yaml")
    parser.add_argument("--salt", default="assertion-note-split-v1")
    parser.add_argument("--dev-fraction", type=float, default=0.6)
    parser.add_argument("--out", type=Path, default=root / "split.json")
    args = parser.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    dimensions = list(gold["dimensions"])

    by_note: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in gold["items"]:
        by_note[str(item["fixture"])].append(item)

    groups: dict[str, list[str]] = defaultdict(list)
    for note, items in by_note.items():
        groups[stratum(items)].append(note)

    notes: dict[str, str] = {}
    for _name, members in sorted(groups.items()):
        ordered = sorted(members, key=lambda n: (rank(args.salt, n), n))
        cut = round(len(ordered) * args.dev_fraction)
        for position, note in enumerate(ordered):
            notes[note] = DEV if position < cut else HELD_OUT

    # Spans inherit their note's half. The key format is unchanged so every
    # existing consumer of `assignment` keeps working; what changed is that the
    # value is now a property of the note rather than of the span.
    assignment = {
        f"{item['fixture']}:{item['start']}:{item['end']}": notes[str(item["fixture"])]
        for item in gold["items"]
    }

    def counts(split: str) -> dict[str, Any]:
        members = [i for i in gold["items"] if notes[str(i["fixture"])] == split]
        return {
            "notes": sum(1 for n, s in notes.items() if s == split),
            "spans": len(members),
            "affirmed": sum(1 for i in members if not i["labels"]),
            "label_counts": {d: sum(1 for i in members if d in i["labels"]) for d in dimensions},
        }

    payload = {
        "salt": args.salt,
        "dev_fraction": args.dev_fraction,
        "unit": "note",
        "stratified_on": "the scarcest dimension the note carries",
        "why_note_level": (
            "the span-level split and the cue-level split were different "
            "partitions of different units: 97 of 100 notes had spans in both "
            "halves, and 224 of 399 held-out spans sat in notes the cue miner "
            "used as development. A vocabulary mined from a note has seen the "
            "phrasing of every span in it. One note-level split governs both "
            "harnesses so that cannot recur."
        ),
        "why_stratified": (
            "family carries 9 positives in 1,000 spans. An unstratified split "
            "could leave one half unable to measure it at all — the failure the "
            "fixture gold already demonstrated. Stratifying notes on the exact "
            "label combination gives 16 strata whose smallest holds one note, so "
            "the key is the scarcest dimension present instead."
        ),
        "why_at_all": (
            "the first cue extension was mined from the gold's false negatives "
            "and then scored on the same spans. That figure is in-sample; this "
            "split is what makes the next one honest."
        ),
        "strata": {name: len(members) for name, members in sorted(groups.items())},
        DEV: counts(DEV),
        HELD_OUT: counts(HELD_OUT),
        "notes": notes,
        "assignment": assignment,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    args.out.write_text(text + "\n", encoding="utf-8")

    overlap = {n for n, s in notes.items() if s == DEV} & {
        n for n, s in notes.items() if s == HELD_OUT
    }
    if overlap:
        raise SystemExit(f"a note landed in both halves: {sorted(overlap)[:3]}")

    summary = {k: v for k, v in payload.items() if k not in {"assignment", "notes"}}
    summary["split_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
