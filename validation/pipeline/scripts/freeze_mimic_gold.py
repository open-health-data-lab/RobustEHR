#!/usr/bin/env python
"""Freeze the MIMIC annotations into a hashed gold, with a reliability bound.

Annotation is not reproducible by re-running anything, so the labels are frozen
once and every downstream measurement reads the frozen file. That is what lets a
deterministic scorer sit on top of a non-deterministic input.

**The reliability bound is the point of the second pass.** At temperature 0 an
identical prompt returns an identical answer, so re-running measures nothing. The
second pass reverses the span *numbering* within each window — text unchanged,
question unchanged, only the order the spans are asked about. A label that moves
under that was never stable, and the resulting intra-annotator κ **bounds every
detector number computed against this gold**: the detector cannot be shown to
agree with the gold more than the gold agrees with itself.

The fixture gold had no such bound, which is the main thing this one improves on
besides being real clinical text.

**Restricted, and the flag travels with the data.** The gold carries
``restricted: true`` and ``source: corpus``, so `assertion_gold_eval.py` suppresses
surfaces without a caller having to remember to. The file stays in `data/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

DIMENSIONS = ("negated", "uncertain", "historical", "family")


def kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """Cohen's kappa between two passes over one dimension."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(1 for a, b in pairs if a == b) / n
    p_a = sum(1 for a, _ in pairs if a) / n
    p_b = sum(1 for _, b in pairs if b) / n
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def fold(labels: list[str]) -> list[str]:
    """`hypothetical` folds into `uncertain`.

    The stage modifies the asserted presence of a concept — absent, possible, or
    someone else's — and for that purpose a hedge and a condition are the same
    move: neither asserts the finding is present now. Keeping them apart also
    forced an arbitrary choice on every shared modal, since `may`, `should` and
    `can` all serve both. See `concepts/context._NAMES`.
    """
    return sorted({"uncertain" if x == "hypothetical" else x for x in labels})


def by_span(labels: dict[str, Any]) -> dict[tuple[str, int, int], list[str]]:
    return {(i["note_id"], i["start"], i["end"]): fold(i["labels"]) for i in labels["items"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    root = Path("data/assertion_gold_mimic")
    parser.add_argument("--labels", type=Path, default=root / "labels.json")
    parser.add_argument("--pass2", type=Path, default=root / "labels_pass2.json")
    parser.add_argument(
        "--second-annotator",
        type=Path,
        default=root / "labels_terra.json",
        help="a DIFFERENT model over the same spans. Intra-annotator agreement "
        "only shows self-consistency; inter-annotator agreement is what makes "
        "this a gold standard rather than one model's opinion",
    )
    parser.add_argument("--out", type=Path, default=root / "gold.yaml")
    args = parser.parse_args(argv)

    first = json.loads(args.labels.read_text(encoding="utf-8"))
    primary = by_span(first)

    reliability: dict[str, Any] = {"measured": False}
    if args.pass2.exists():
        second = by_span(json.loads(args.pass2.read_text(encoding="utf-8")))
        shared = sorted(set(primary) & set(second))
        per_dimension = {}
        for dimension in DIMENSIONS:
            pairs = [(dimension in primary[k], dimension in second[k]) for k in shared]
            value = kappa(pairs)
            per_dimension[dimension] = {
                "cohens_kappa": round(value, 4) if value is not None else None,
                "pass1_positives": sum(1 for a, _ in pairs if a),
                "pass2_positives": sum(1 for _, b in pairs if b),
            }
        exact = sum(1 for k in shared if set(primary[k]) == set(second[k]))
        reliability = {
            "measured": True,
            "design": (
                "second pass with the span numbering reversed within each "
                "window — same text, same question, different order. At "
                "temperature 0 an identical prompt would measure nothing."
            ),
            "spans_compared": len(shared),
            "exact_label_set_agreement": round(exact / len(shared), 4) if shared else None,
            "per_dimension": per_dimension,
            "how_to_read": (
                "this bounds every detector figure computed against this gold. "
                "A dimension whose annotator kappa is low cannot support a "
                "confident claim about the detector, because the yardstick "
                "itself moves."
            ),
        }

    inter: dict[str, Any] = {"measured": False}
    if args.second_annotator.exists():
        other_raw = json.loads(args.second_annotator.read_text(encoding="utf-8"))
        other = by_span(other_raw)
        shared = sorted(set(primary) & set(other))
        per_dimension = {}
        for dimension in DIMENSIONS:
            pairs = [(dimension in primary[k], dimension in other[k]) for k in shared]
            value = kappa(pairs)
            per_dimension[dimension] = {
                "cohens_kappa": round(value, 4) if value is not None else None,
                "annotator_1_positives": sum(1 for a, _ in pairs if a),
                "annotator_2_positives": sum(1 for _, b in pairs if b),
            }
        exact = sum(1 for k in shared if set(primary[k]) == set(other[k]))
        inter = {
            "measured": True,
            "annotator_2": other_raw.get("model_requested"),
            "annotator_2_served": other_raw.get("model_served"),
            "design": (
                "a different model over the identical spans and identical "
                "guideline. This is the counter-validation: intra-annotator "
                "agreement shows only that one rater repeats itself, which a "
                "consistently wrong rater also does."
            ),
            "spans_compared": len(shared),
            "exact_label_set_agreement": round(exact / len(shared), 4) if shared else None,
            "per_dimension": per_dimension,
            "how_to_read": (
                "this is the ceiling on any detector claim made against this "
                "gold, and the number that distinguishes a gold standard from "
                "one model's opinion. Where two independent annotators agree "
                "and the detector does not, the detector is the outlier."
            ),
        }

    items = [
        {
            "fixture": note_id,  # the scorer's key; a note_id here, a fixture name there
            "start": start,
            "end": end,
            "labels": sorted(labels),
        }
        for (note_id, start, end), labels in sorted(primary.items())
    ]
    counts = {d: sum(1 for i in items if d in i["labels"]) for d in DIMENSIONS}
    payload = {
        "schema_version": "1.0",
        "restricted": True,
        "source": "corpus",
        "corpus": "MIMIC-IV discharge summaries (data/golden_notes.csv)",
        "licence": (
            "PhysioNet Credentialed Health Data Use Agreement. This file carries "
            "note-derived offsets and must never be committed; surfaces are "
            "omitted entirely and the scorer suppresses them for any gold "
            "flagged restricted."
        ),
        "annotator": first.get("model_requested"),
        "annotator_served": first.get("model_served"),
        "annotator_note": (
            "an LLM via OpenRouter, prompted with docs/assertion-annotation-"
            "guideline.md. A second opinion, not a ground truth: agreement with "
            "medspaCy ConText is between two imperfect raters, and the "
            "intra-annotator kappa below bounds what may be claimed."
        ),
        "spans_from": "annotate_document, sampled by hash rank — see sample_assertion_corpus.py",
        "dimensions": list(DIMENSIONS),
        "n_items": len(items),
        "n_affirmed": sum(1 for i in items if not i["labels"]),
        "label_counts": counts,
        "annotator_reliability": reliability,
        "inter_annotator_agreement": inter,
        "items": items,
    }
    text = yaml.safe_dump(payload, sort_keys=True, allow_unicode=True, width=100)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")

    summary = {
        "n_items": len(items),
        "n_affirmed": payload["n_affirmed"],
        "label_counts": counts,
        "gold_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "annotator_reliability": reliability,
        "inter_annotator_agreement": inter,
    }
    (args.out.parent / "gold_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
