#!/usr/bin/env python
"""Annotate the assertion **cues** themselves, not the spans they govern.

Every measurement so far scores at the span level — did this mention get the
right attribute — which conflates two different abilities: **finding the cue**
and **scoping it correctly**. The MIMIC gold showed the failure is lopsided
(`historical` precision 0.846, recall 0.111), which points at detection rather
than scoping, but a span-level metric cannot prove that. A cue that is never
found and a cue that is found and mis-scoped produce the same wrong span.

This builds the instrument that separates them: a gold of the cue occurrences
themselves, over the same windows, so cue detection can be scored directly as
precision and recall over cue spans.

**Why offsets are located rather than requested.** Asking a model for character
offsets is unreliable and its errors are silent. It is asked for the exact
substrings instead, and each is located in the window here — **at word
boundaries**, which the first version omitted and which wrecked the measurement:
`no` matched inside *normal*, *nodules* and *Diagnosis*, inflating the gold and
making every detector's recall read far lower than it is.

A cue string occurring more than once is still accepted at every boundary-
respecting occurrence. That over-counts a word which is a cue in one clause and
ordinary usage in another, and it is recorded rather than hidden because it
inflates gold recall and therefore makes the detector look *worse*, not better.

Same authorisation and handling as `annotate_assertions.py`: cached under
`data/`, `data_collection: deny`, aggregates only.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from scripts.annotate_assertions import DIMENSIONS, api_key, call, windows

#: Categories the annotator is asked for, in the vocabulary the rest of the
#: package uses rather than ConText's internal names.
PROMPT = """You are marking ASSERTION CUES in clinical text.

An assertion cue is the word or short phrase that tells a reader a finding is
absent, uncertain, past, someone else's, or conditional. It is NOT the finding.

  "The patient denies chest pain"    -> cue "denies"    (negated)
  "possible pneumonia"               -> cue "possible"  (uncertain)
  "s/p CABG"                         -> cue "s/p"       (historical)
  "Father with MI"                   -> cue "Father"    (family)
  "Tylenol PRN for pain"             -> cue "PRN"       (hypothetical)

Dimensions: negated, uncertain, historical, family, hypothetical.

Mark every cue occurrence in the text below. Use the EXACT substring as it
appears, preserving case. Include abbreviations and shorthand: s/p, h/o, hx,
nil, NKDA, PRN, q6h, r/o, w/o, +/-, and so on.

TEXT:
{body}

Reply with JSON only, no prose:
{{"cues": [{{"text": "denies", "dimension": "negated"}}, ...]}}
Return an empty list if there are none."""


def locate_all(window: str, needle: str, offset: int) -> list[tuple[int, int]]:
    """Every occurrence of ``needle`` in the window, at word boundaries.

    **Boundaries are not optional here, and omitting them silently wrecked the
    measurement.** A first version used bare `str.find`, so the cue `no` matched
    inside `normal`, `nodules`, `none` and `Diagnosis` — five gold cues where one
    was real. That inflates the gold, and since inflated gold counts as missed
    recall, it made every detector look far worse than it is.

    The boundary is applied per edge and only where the edge is alphanumeric:
    cues like `(-)`, `?` and `+/-` have no word character to anchor against and
    would match nothing under a naive ``\\b``.
    """
    if not needle:
        return []
    left = r"(?<![A-Za-z0-9])" if needle[0].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if needle[-1].isalnum() else ""
    pattern = re.compile(left + re.escape(needle) + right, re.IGNORECASE)
    return [(offset + m.start(), offset + m.end()) for m in pattern.finditer(window)]


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    root = Path("data/assertion_gold_mimic")
    parser.add_argument("--sample", type=Path, default=root / "sample.json")
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--model", default="openai/gpt-5.6-luna")
    parser.add_argument("--cache", type=Path, default=Path("data/openrouter_cache"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--cap", type=int, default=2000)
    parser.add_argument("--out", type=Path, default=root / "cues.json")
    args = parser.parse_args(argv)

    from robustehr.corpus import read_documents

    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    wanted = set(sample["note_ids"])
    key = api_key()
    args.cache.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, int, int, str]] = []
    for doc in read_documents(args.corpus):
        if doc.uid not in wanted:
            continue
        for start, end, _header in windows(doc, args.cap):
            body = doc.text[start:end]
            if body.strip():
                jobs.append((doc.uid, start, end, body))

    print(f"{len(jobs)} windows", flush=True)

    def run(job: tuple[str, int, int, str]) -> dict[str, Any]:
        uid, start, _end, body = job
        payload = call(PROMPT.format(body=body), args.model, key, args.cache)
        try:
            content = payload["choices"][0]["message"]["content"]
            text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            raw = json.loads(text).get("cues", [])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return {"note_id": uid, "cues": None, "error": payload.get("error", "unparseable")}
        cues = []
        for entry in raw if isinstance(raw, list) else []:
            if not isinstance(entry, dict):
                continue
            needle, dimension = str(entry.get("text", "")), str(entry.get("dimension", ""))
            if dimension not in DIMENSIONS:
                continue
            for a, b in locate_all(body, needle, start):
                cues.append({"start": a, "end": b, "dimension": dimension, "text": needle})
        return {"note_id": uid, "cues": cues, "error": None}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, jobs))

    failed = [r for r in results if r["cues"] is None]
    # Deduplicate: windows share header context, and one cue may be reported by
    # two windows. Identity is (note, offsets, dimension).
    seen: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for result in results:
        for cue in result["cues"] or []:
            seen[(result["note_id"], cue["start"], cue["end"], cue["dimension"])] = {
                "note_id": result["note_id"],
                **cue,
            }
    cues = [seen[k] for k in sorted(seen)]

    counts = {d: sum(1 for c in cues if c["dimension"] == d) for d in DIMENSIONS}
    payload = {
        "model_requested": args.model,
        "windows": len(jobs),
        "windows_failed": len(failed),
        "cues": len(cues),
        "by_dimension": counts,
        "items": cues,
        "known_limitation": (
            "a cue string occurring more than once is accepted at every "
            "boundary-respecting occurrence. That over-counts a word which is a "
            "cue in one clause and ordinary usage in another, which inflates "
            "gold recall and therefore makes the detector look worse rather "
            "than better. Matching is word-bounded, so `no` cannot match inside "
            "`normal` or `Diagnosis`."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(cues)} cue occurrences, {len(failed)} windows failed")
    print(f"by dimension: {counts}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
