#!/usr/bin/env python
"""Fetch Chapman's NegEx test set — the reference gold for the ConText family.

Stage 8 shipped with a *stability* gate (`assertion_stability.json`) and no
*correctness* one. Those measure different things, and the distinction matters:
a contextualizer that marked every span affirmed would score a perfect 0.0000
flip rate while being wrong on every negation in the corpus. This script fetches
the gold that closes that gap.

**Why this corpus.** `Annotations-1-120.txt` carries 2,376 concept-level
assertions over discharge summaries — `Report No. | Concept | Sentence |
Negation` — where the concept is a phrase *within* the sentence. That is exactly
the shape `concepts.context.qualify` consumes: spans supplied from outside,
assertion measured in isolation from detection. It is also the gold the
NegEx/ConText algorithm family was developed and reported against, so a result
on it is comparable to the literature rather than to ourselves.

**Licensing — the binding constraint.** The upstream repository carries no
`LICENSE`, `LICENSE.txt` or `README` at master. Provenance is therefore unclear,
and this project's standing rule for a corpus with no attached licence (set for
CASI) is to *treat it exactly like MIMIC*: it lives in `data/`, which is
default-deny in `.gitignore`, and nothing derived from it may carry note text.
Committed artifacts get counts, hashes and metrics — never a sentence.

The manifest records a SHA-256 per file so a measurement can name the exact bytes
it was computed over. No timestamp is written: the hash is the provenance anchor,
and a wall-clock field would make two identical fetches produce different files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

#: Raw-content URLs, pinned to `master`. Keyed by the local filename.
SOURCES = {
    "Annotations-1-120.txt": (
        "https://raw.githubusercontent.com/chapmanbe/negex/master/"
        "negex.python/Annotations-1-120.txt"
    ),
    "negex_triggers.txt": (
        "https://raw.githubusercontent.com/chapmanbe/negex/master/negex.python/negex_triggers.txt"
    ),
}

#: The two labels the scorer understands. Rows carrying anything else are
#: reported in the manifest rather than silently dropped.
LABELS = ("Affirmed", "Negated")


def fetch(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "robustehr-fetch"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def summarize_gold(path: Path) -> dict[str, object]:
    """Row and label counts, so the manifest describes content and not only bytes."""
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    labels: dict[str, int] = {}
    for row in rows:
        value = (row.get("Negation") or "").strip()
        labels[value] = labels.get(value, 0) + 1
    negated = labels.get("Negated", 0)
    total = sum(labels.values())
    return {
        "rows": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "label_counts": dict(sorted(labels.items())),
        "labels_outside_scorer": sorted(set(labels) - set(LABELS)),
        # The floor every method must beat. Reported here so it cannot be
        # rediscovered wrongly downstream.
        "majority_class_accuracy": round((total - negated) / total, 4) if total else None,
        "negated_prevalence": round(negated / total, 4) if total else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=Path("data/negex"))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--force", action="store_true", help="re-download even if the file is already present"
    )
    args = parser.parse_args(argv)

    args.dest.mkdir(parents=True, exist_ok=True)
    files: dict[str, object] = {}
    for name, url in sorted(SOURCES.items()):
        target = args.dest / name
        if target.exists() and not args.force:
            print(f"present, skipping: {target}", file=sys.stderr)
        else:
            print(f"fetching {url}", file=sys.stderr)
            target.write_bytes(fetch(url, args.timeout))
        payload = target.read_bytes()
        entry: dict[str, object] = {
            "url": url,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
        if name.startswith("Annotations"):
            entry.update(summarize_gold(target))
        files[name] = entry

    manifest = {
        "corpus": "NegEx test set (Chapman et al.)",
        "purpose": (
            "gold for the stage 8 correctness benchmark. Stage 8 was gated for "
            "stability, which a trivially wrong contextualizer also passes; this "
            "supplies the correctness measurement that gate cannot give."
        ),
        "licence": (
            "NONE FOUND. The upstream repository has no LICENSE, LICENSE.txt or "
            "README at master. Handled under this project's rule for unlicensed "
            "corpora, set for CASI: treat exactly like MIMIC. Lives in data/ "
            "(default-deny in .gitignore); no derived artifact may carry sentence "
            "text; only counts, hashes and metrics are committed."
        ),
        "scorer_labels": list(LABELS),
        "files": files,
    }
    (args.dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
