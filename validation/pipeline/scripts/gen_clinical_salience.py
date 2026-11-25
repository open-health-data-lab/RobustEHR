"""Build the clinical-salience lexicon from adjudicated annotations.

For each word type, the rate at which it falls **inside a span a human annotator
marked as a clinical concept**. That is an empirical property of one corpus, not
a definition of "clinical", and the manifest records which corpus so a downstream
run cannot quietly claim more.

Why this is not simply "the words in the gold spans": gold spans carry function
words with them — ``of``, ``no``, ``to`` each appear inside hundreds of them —
so presence is uninformative and only the *rate* discriminates. ``pain`` is
inside 83% of the time, ``of`` under 10%.

Smoothed as ``(inside + 1) / (total + 4)``, so a token seen twice cannot reach
1.0 and a token never seen sits at 0.25 rather than 0. The prior is deliberately
below every usable threshold: an unseen token must be admitted by another clause
(the drug vocabulary, the labelled-value test) rather than by this one.

    python validation/pipeline/scripts/gen_clinical_salience.py

Writes ``src/robustehr/resources/clinical_salience.json`` and a manifest beside
it. Measured in ``validation/measurements/clinical_targeting.json``; the protocol is
``validation/protocol.md`` §9.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

#: Same tokenizer the targets use, so a lexicon key is a token a rule can look
#: up. Trailing hyphens are kept: ``Hct-`` in a lab block is a different token
#: from ``hct`` in prose, and they have genuinely different salience (0.99 vs
#: 0.77) because one is a labelled value and the other is discourse.
WORD = re.compile(r"[A-Za-z][A-Za-z\-']*")

SMOOTH_ALPHA = 1.0
SMOOTH_BETA = 3.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", type=Path, default=Path("data/snomed_el/train_notes.csv"))
    parser.add_argument(
        "--annotations", type=Path, default=Path("data/snomed_el/train_annotations.csv")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("src/robustehr/resources/clinical_salience.json")
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=2,
        help="drop hapax types: one observation cannot estimate a rate, and "
        "shipping 40k singletons at the prior helps nothing",
    )
    args = parser.parse_args()

    with args.notes.open(newline="", encoding="utf-8") as handle:
        notes = {r["note_id"]: r["text"] for r in csv.DictReader(handle)}
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with args.annotations.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            spans[row["note_id"]].append((int(float(row["start"])), int(float(row["end"]))))

    ids = sorted(set(notes) & set(spans))
    inside: Counter[str] = Counter()
    outside: Counter[str] = Counter()

    for uid in ids:
        text = notes[uid]
        gold = sorted(spans[uid])
        starts = [s for s, _ in gold]

        def covered(
            a: int, b: int, gold: list[tuple[int, int]] = gold, starts: list[int] = starts
        ) -> bool:
            j = bisect.bisect_right(starts, b) - 1
            while j >= 0 and starts[j] >= a - 400:
                s, e = gold[j]
                if s < b and a < e:
                    return True
                j -= 1
            return False

        for match in WORD.finditer(text):
            a, b = match.span()
            (inside if covered(a, b) else outside)[match.group().lower()] += 1

    counts = {w: (inside[w], inside[w] + outside[w]) for w in set(inside) | set(outside)}
    kept = {
        w: round((i + SMOOTH_ALPHA) / (n + SMOOTH_ALPHA + SMOOTH_BETA), 4)
        for w, (i, n) in counts.items()
        if n >= args.min_count
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "corpus": "SNOMED CT Entity Linking Challenge — MIMIC-IV discharge summaries",
        "notes": len(ids),
        "annotations": sum(len(v) for v in spans.values()),
        "tokens": sum(inside.values()) + sum(outside.values()),
        "gold_token_rate": round(
            sum(inside.values()) / (sum(inside.values()) + sum(outside.values())), 4
        ),
        "smoothing": {"alpha": SMOOTH_ALPHA, "beta": SMOOTH_BETA},
        "prior": round(SMOOTH_ALPHA / (SMOOTH_ALPHA + SMOOTH_BETA), 4),
        "min_count": args.min_count,
        "salience": dict(sorted(kept.items())),
    }
    body = json.dumps(payload, indent=1, sort_keys=True) + "\n"
    args.out.write_text(body, encoding="utf-8")

    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    manifest = args.out.with_suffix(".manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "sha256": digest,
                "corpus": payload["corpus"],
                "notes": payload["notes"],
                "types": len(kept),
                "gold_token_rate": payload["gold_token_rate"],
                "generated_by": "validation/pipeline/scripts/gen_clinical_salience.py",
                "validated_in": "validation/measurements/clinical_targeting.json",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"notes {len(ids)}   types kept {len(kept):,} of {len(counts):,}")
    print(f"gold token rate {payload['gold_token_rate']:.1%}   prior {payload['prior']}")
    print(f"wrote {args.out}  sha256 {digest[:16]}")
    print(f"wrote {manifest}")
    for probe in ("hypertension", "pneumonia", "pain", "metoprolol", "she", "patient", "sig"):
        print(f"  {probe:<14} {kept.get(probe, payload['prior'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
