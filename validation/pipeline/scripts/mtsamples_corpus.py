"""Turn the public-domain MTSamples CSV into a `(note_id, text)` corpus.

MTSamples (mtsamples.com, redistributed on Kaggle under CC0) is about 5,000
transcribed reports across 40 specialties — dictated outpatient, consult,
operative and radiology text from no single institution, with headers written
`SUBJECTIVE:,` and no de-identification placeholders at all. It is the real,
non-MIMIC corpus the cross-corpus characterisation in
`validation/measurements/corpus/` runs on, chosen because anyone can download
it without a data use agreement and replay the published edit scripts.

Selection is deterministic: rows with a transcription of at least
`--min-chars` characters are ranked by the BLAKE2b digest of their text and the
first `--n` are kept, so the same sample comes out on any machine. `note_id` is
the row's position in the source CSV, which is stable for a given download.

The scrape flattened every report to a single line: line breaks became `,`
and section labels appear as `,PAST MEDICAL HISTORY:,`. With `--restore-lines`
(the default) that one artifact of the CSV is reversed — a newline is inserted
before every `UPPER CASE LABEL:` that follows a comma, and the comma that
replaced the original break is dropped — so the section layer sees the
dictated report's own headers as lines. Nothing else is changed; the rule is
the regex below and the manifest records that it ran. Pass `--no-restore-lines`
to keep the flat text, which measures the corpus as a total loss of text
structure instead.

    python validation/pipeline/scripts/mtsamples_corpus.py \
        --src data/mtsamples/mtsamples.csv --out data/mtsamples/notes.csv --n 500

Writes the corpus and a manifest (`notes.manifest.json`: source digest, row
count, sample digest, selection rule) beside it. Nothing here is committed —
`data/*/*` is ignored — but the manifest's digests are what the measurement
artifact records.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

# `,PAST MEDICAL HISTORY:,` / `,PROCEDURE: ,` — an upper-case label of 2-60
# characters ending in a colon, preceded by the comma the scrape substituted
# for a line break. The lookahead keeps the label; only the comma is consumed.
FLATTENED_HEADER = re.compile(r",\s*(?=[A-Z][A-Z0-9 /&()'\-]{1,60}:\s*,)")
TRAILING_LABEL_COMMA = re.compile(r"^([A-Z][A-Z0-9 /&()'\-]{1,60}:)\s*,\s*", re.MULTILINE)


def restore_lines(text: str) -> str:
    text = FLATTENED_HEADER.sub("\n", text)
    text = TRAILING_LABEL_COMMA.sub(r"\1 ", text)
    return text.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, default=Path("data/mtsamples/mtsamples.csv"))
    ap.add_argument("--out", type=Path, default=Path("data/mtsamples/notes.csv"))
    ap.add_argument("--n", type=int, default=500, help="sample size; 0 keeps every eligible row")
    ap.add_argument("--min-chars", type=int, default=200)
    ap.add_argument("--restore-lines", dest="restore", action="store_true", default=True)
    ap.add_argument("--no-restore-lines", dest="restore", action="store_false")
    args = ap.parse_args()

    csv.field_size_limit(1 << 30)
    raw = args.src.read_bytes()
    src_sha = hashlib.sha256(raw).hexdigest()
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    eligible = []
    for i, row in enumerate(rows):
        text = (row.get("transcription") or "").strip()
        if len(text) < args.min_chars:
            continue
        if args.restore:
            text = restore_lines(text)
        rank = hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()
        eligible.append((rank, i, text, (row.get("medical_specialty") or "").strip()))
    eligible.sort()
    chosen = eligible if args.n == 0 else eligible[: args.n]
    chosen.sort(key=lambda t: t[1])  # source order, so the file is stable and diffable

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["note_id", "text", "specialty"])
        for _, i, text, spec in chosen:
            w.writerow([f"mts-{i:04d}", text, spec])
    sample_sha = hashlib.sha256(args.out.read_bytes()).hexdigest()
    manifest = {
        "source": str(args.src),
        "source_sha256": src_sha,
        "source_rows": len(rows),
        "eligible_rows": len(eligible),
        "min_chars": args.min_chars,
        "selection": "blake2b(text) ascending, first n, then source order",
        "restore_lines": args.restore,
        "restore_rule": FLATTENED_HEADER.pattern if args.restore else None,
        "n": len(chosen),
        "sample_sha256": sample_sha,
        "licence": "CC0 1.0 (Kaggle: tboyle10/medicaltranscriptions)",
    }
    args.out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
