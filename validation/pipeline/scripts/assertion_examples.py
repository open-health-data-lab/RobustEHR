#!/usr/bin/env python
"""Worked examples of the assertion task, generated rather than transcribed.

Every published example of this task must come from the **synthetic** fixture
gold. The MIMIC gold is the larger and more informative instrument, but its spans
carry note text held under the PhysioNet Credentialed Health Data Use Agreement,
so a worked example drawn from it could not be committed — quoting the sentence
around a span is exactly the disclosure the agreement forbids. The fixtures were
written from scratch, describe no real patient, and ship in the repository, which
is what makes them quotable.

The examples are **generated from the frozen gold and the shipped detector**, not
typed into a document. A hand-written example table drifts the moment a rule
changes and there is nothing to catch it; this script re-runs and the table is
regenerated, so an example that stops being true stops being printed.

For each selected span the row carries the sentence it sits in, the gold labels,
and what each detector arm returned — including the cue each arm fired on, which
is the part that explains a disagreement. A row where the arms differ is more
useful than a row where they agree, so selection deliberately favours them.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from tests.fixtures.clinical import FORMATS

from robustehr.concepts import context
from robustehr.types import Span

#: Spans chosen to cover the four dimensions and both outcomes — agreement and
#: disagreement — keyed by fixture and character offset. Recorded here rather
#: than selected by a heuristic so the document's examples are stable across
#: runs and a reviewer can see exactly what was picked and object to it.
SELECTED: tuple[tuple[str, int, str], ...] = (
    ("cardiology_dictated", 480, "textbook negation, both arms correct"),
    ("allcaps_legacy", 287, "negation in an all-caps legacy note"),
    ("cardiology_dictated", 193, "historical framing of a still-active condition"),
    ("allcaps_legacy", 344, "historical by section membership, not by cue"),
    ("cardiology_dictated", 1118, "conditional future plan — folded into uncertain"),
    ("family_med_freetext", 531, "as-needed / contingent order"),
    ("pediatric_admission", 489, "finding belonging to someone who is not the patient"),
    ("epic_progress", 1020, "hedged discharge planning"),
)


def sentence_around(text: str, start: int, end: int, *, width: int = 110) -> str:
    """The sentence containing the span, or a bounded window if it is long."""
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right = min(
        (i for i in (text.find(".", end), text.find("\n", end)) if i != -1),
        default=len(text),
    )
    fragment = text[left:right].strip()
    if len(fragment) <= width:
        return fragment
    keep = text[max(left, start - width // 2) : min(right, end + width // 2)].strip()
    return f"…{keep}…"


def arm_for(
    text: str, spans: list[Span], *, extended: bool
) -> dict[tuple[int, int], dict[str, Any]]:
    """Assertions and the cues that produced them, keyed by span."""
    index = context.qualify(text, spans, extended=extended)
    cues = context.cues_in(text, extended=extended)
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for span, labels in index.as_map().items():
        key = (span.start, span.end)
        firing = sorted(
            {
                text[c.span.start : c.span.end]
                for c in cues
                if c.scope is not None and c.scope.start <= span.start and span.end <= c.scope.end
            }
        )
        out[key] = {"labels": sorted(labels), "cues": firing}
    return out


def load_corpus(by_note: dict[str, list[dict[str, Any]]], corpus: Path | None) -> dict[str, str]:
    """Note text for a restricted gold, which names `note_id`s rather than fixtures."""
    if corpus is None:
        raise SystemExit("this gold references a corpus; pass --corpus")
    from robustehr.corpus import read_documents

    return {d.uid: d.text for d in read_documents(corpus) if d.uid in by_note}


def emit_restricted(
    by_note: dict[str, list[dict[str, Any]]],
    texts: dict[str, str],
    args: argparse.Namespace,
) -> int:
    """Worked examples from the MIMIC gold, for a credentialed reader, in `data/`.

    **These are the spans actually annotated**, which the synthetic examples are
    only a stand-in for. They exist because the question "what did the annotators
    really see?" deserves a real answer, and the answer cannot be committed: the
    rows carry note text, which is the whole point of an example and the whole
    reason the PhysioNet agreement forbids redistributing it.

    Selection is deterministic and **balanced between agreement and
    disagreement**. Taking the first N spans per dimension would show whatever
    the corpus order happens to surface; taking only errors would misrepresent
    the detector. Half of each dimension's quota comes from spans the shipped arm
    gets right and half from spans it gets wrong, so a reader sees the failure
    modes without being shown only failures.
    """
    quota = max(2, args.per_dimension)
    hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    misses: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for note, items in sorted(by_note.items()):
        text = texts.get(note)
        if text is None:
            continue
        spans = [Span(int(i["start"]), int(i["end"])) for i in items]
        stock = arm_for(text, spans, extended=False)
        extended = arm_for(text, spans, extended=True)
        for item in items:
            start, end = int(item["start"]), int(item["end"])
            key = (start, end)
            truth = sorted(item["labels"])
            row = {
                "note_id": note,
                "sentence": sentence_around(text, start, end),
                "span": text[start:end],
                "offsets": [start, end],
                "gold": truth or ["affirmed"],
                "stock": stock.get(key, {}).get("labels") or ["affirmed"],
                "stock_cues": stock.get(key, {}).get("cues", []),
                "extended": extended.get(key, {}).get("labels") or ["affirmed"],
                "extended_cues": extended.get(key, {}).get("cues", []),
            }
            row["extended_correct"] = row["extended"] == row["gold"]
            for dimension in truth or ["affirmed"]:
                (hits if row["extended_correct"] else misses)[dimension].append(row)

    rows: list[dict[str, Any]] = []
    for dimension in (*context.DIMENSIONS, "affirmed"):
        chosen = hits[dimension][: quota // 2] + misses[dimension][: quota - quota // 2]
        for row in chosen:
            rows.append({"dimension": dimension, **row})

    payload = {
        "question": "What did the annotators actually read, on the real corpus?",
        "why": (
            "Every score in validation/pipeline/assertion-benchmarks.md comes from these spans. "
            "The worked examples published there are synthetic because these "
            "rows cannot be committed, and a reader with credentials should be "
            "able to see the real ones."
        ),
        "restricted": True,
        "handling": (
            "MIMIC-IV note text under the PhysioNet Credentialed Health Data Use "
            "Agreement. NOT redistributable: this file stays in data/, which "
            ".gitignore default-denies. Do not paste these rows into a document "
            "that leaves this machine without checking the agreement first."
        ),
        "selection": "half detector-correct, half detector-wrong, per dimension",
        "dimensions": list(context.DIMENSIONS),
        "n_rows": len(rows),
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    readable = args.out.with_suffix(".md")
    lines = [
        "# Annotated MIMIC spans — RESTRICTED, do not commit or redistribute",
        "",
        payload["handling"],
        "",
    ]
    for dimension in (*context.DIMENSIONS, "affirmed"):
        picked = [r for r in rows if r["dimension"] == dimension]
        if not picked:
            continue
        lines += [f"## {dimension}", ""]
        for row in picked:
            mark = "correct" if row["extended_correct"] else "MISSED"
            cues = ", ".join(row["extended_cues"]) or "—"
            lines += [
                f"- **{row['span']}**  ({row['note_id']} @{row['offsets'][0]})",
                f"  > {row['sentence']}",
                f"  gold `{'+'.join(row['gold'])}` — detector "
                f"`{'+'.join(row['extended'])}` [{mark}], cue: {cues}",
                "",
            ]
    readable.write_text("\n".join(lines), encoding="utf-8")

    print(f"{len(rows)} restricted examples -> {args.out} and {readable}")
    for dimension in (*context.DIMENSIONS, "affirmed"):
        picked = [r for r in rows if r["dimension"] == dimension]
        ok = sum(1 for r in picked if r["extended_correct"])
        print(f"  {dimension:<11} {len(picked)} rows, {ok} detector-correct")
    return 0


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--gold", type=Path, default=Path("src/robustehr/resources/assertion_gold.yaml")
    )
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--per-dimension", type=int, default=4)
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/assertion_examples.json")
    )
    args = parser.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    restricted = bool(gold.get("restricted"))
    if restricted and Path("data") not in args.out.parents:
        # The guard is a path check rather than a reminder in the docstring
        # because this is the one script that deliberately writes note text: the
        # examples ARE the sentences. A restricted gold may produce them for a
        # credentialed reader on this machine and nowhere else.
        raise SystemExit(
            f"refusing to write examples from a restricted gold to {args.out}. "
            "Its rows carry MIMIC note text held under the PhysioNet "
            "Credentialed Health Data Use Agreement; --out must be under data/."
        )

    by_fixture: dict[str, list[dict[str, Any]]] = {}
    for item in gold["items"]:
        by_fixture.setdefault(str(item["fixture"]), []).append(item)

    texts = (
        load_corpus(by_fixture, args.corpus)
        if restricted
        else {name: FORMATS[name].text for name in by_fixture}
    )
    if restricted:
        return emit_restricted(by_fixture, texts, args)

    rows: list[dict[str, Any]] = []
    for fixture, items in sorted(by_fixture.items()):
        text = texts[fixture]
        spans = [Span(int(i["start"]), int(i["end"])) for i in items]
        stock = arm_for(text, spans, extended=False)
        extended = arm_for(text, spans, extended=True)
        wanted = {start: why for f, start, why in SELECTED if f == fixture}
        for item in items:
            start, end = int(item["start"]), int(item["end"])
            if start not in wanted:
                continue
            key = (start, end)
            rows.append(
                {
                    "fixture": fixture,
                    "why_selected": wanted[start],
                    "sentence": sentence_around(text, start, end),
                    "span": item["surface"],
                    "gold": sorted(item["labels"]) or ["affirmed"],
                    "stock": stock.get(key, {}).get("labels") or ["affirmed"],
                    "stock_cues": stock.get(key, {}).get("cues", []),
                    "extended": extended.get(key, {}).get("labels") or ["affirmed"],
                    "extended_cues": extended.get(key, {}).get("cues", []),
                }
            )

    for row in rows:
        row["stock_correct"] = row["stock"] == row["gold"]
        row["extended_correct"] = row["extended"] == row["gold"]

    payload = {
        "question": "What does one span of the assertion task actually look like?",
        "why": (
            "A per-dimension F1 says how often the detector is right; it does not "
            "say what being right consists of. These rows show the unit of "
            "annotation — a span, its sentence, the label, and the cue each arm "
            "fired on — so a reader can judge the task before judging the score."
        ),
        "corpus": (
            "tests/fixtures/clinical — synthetic, describes no real patient. The "
            "MIMIC gold is the larger instrument but its text is held under the "
            "PhysioNet DUA and cannot be quoted, so worked examples come from the "
            "fixtures by necessity, not by preference."
        ),
        "dimensions": list(context.DIMENSIONS),
        "arms": {
            "stock": "medspaCy ConText, 102 English rules as distributed",
            "extended": "the same engine plus resources/assertion_extensions.yaml",
        },
        "n_rows": len(rows),
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(rows)} worked examples -> {args.out}")
    for row in rows:
        mark = "ok " if row["extended_correct"] else "MISS"
        print(f"  {mark} {row['span']!r:32} gold={row['gold']} ext={row['extended']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
