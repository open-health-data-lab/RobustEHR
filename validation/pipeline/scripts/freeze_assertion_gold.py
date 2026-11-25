#!/usr/bin/env python
"""Freeze the assertion annotations into a committed, hashed resource.

The annotation itself is an LLM-assisted judgement and therefore **not
reproducible by re-running anything**. That is incompatible with a package whose
central claim is determinism, so the labels are frozen once into
`resources/assertion_gold.yaml` and every downstream measurement reads the frozen
file. Re-scoring is then exactly as deterministic as any other measurement here,
and the annotation is a one-time input rather than a live dependency.

The label indices below are positions within `build_assertion_task.py`'s
worksheet for each fixture. They are recorded rather than the offsets so the
annotation stays readable against the worksheet a reviewer can regenerate; the
offsets are resolved at freeze time and written into the resource.

**Two annotation rules were needed and are recorded because they change labels:**

* A morphologically negative *single word* naming a normal state — ``nontender``,
  ``nondistended``, ``afebrile`` — is **affirmed**. It asserts the normal
  finding; it does not negate a mentioned one.
* A *multi-word* span that swallows its own negation cue — ``not indicated``,
  ``not elevated`` — is **negated**, because the finding it names is the thing
  being denied. The NegEx gold contains the same construction and this keeps the
  two consistent.

Under ``historical``: a condition introduced by *"history of"* or sitting under a
*Past Medical History* header is labelled historical **even when it is also
currently active** — ischemic cardiomyopathy does not stop existing. The
dimension records how the note frames the mention, which is what an assertion
layer can observe and what a temporality operator would rewrite.

Under ``family``: the label means **the finding on this span belongs to someone
other than the patient**. A first pass got this wrong by marking the *person*
mentions — ``mother`` as informant in a paediatric note — which is a category
error: a person is not a finding with an experiencer. Corrected, and the
correction matters, because it separates a guideline flaw from a detector flaw.
What remains after the fix is a genuine ConText error in the opposite direction:
*"brought in by mother with 3 days of fever"* makes ``mother`` a FORWARD cue that
scopes over the **child's own** symptoms, so `fever`, `decreased oral intake` and
`breathing` are all marked family. Those are the patient's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from pathlib import Path

import yaml

#: Annotations, keyed by fixture then by worksheet index. Anything unlisted is
#: affirmed — the overwhelming majority, so listing the exceptions is both
#: shorter and easier to check than listing every span.
LABELS: dict[str, dict[str, tuple[int, ...]]] = {
    "epic_progress": {
        "negated": (3, 4, 5, 6, 8, 13, 17, 20, 21, 24, 25, 48, 49),
        "hypothetical": (56, 59),
    },
    "radiology_report": {
        "uncertain": (5, 6),
        "negated": (13, 15, 16, 21, 25, 26),
    },
    "family_med_freetext": {
        "negated": (8, 9, 14, 15, 16, 17, 18, 19),
        "hypothetical": (27, 28),
    },
    "psychiatry_clinic": {
        # `mother` at 12 is the person, not a finding attributed to her.
        "negated": (32, 34, 37, 38, 39, 41, 42),
        "hypothetical": (48,),
    },
    "pediatric_admission": {
        # 19 is `unwell`, of the daycare children — a finding on someone who is
        # not the patient. The `mother` mentions are people, not findings.
        "family": (19,),
        "historical": (8,),
        "negated": (17, 57, 58, 59, 60),
        "hypothetical": (51, 53, 54, 55, 56, 61),
    },
    "cardiology_dictated": {
        "historical": (6, 10, 11),
        "negated": (24, 25, 26, 30, 31, 37, 38, 46, 53, 54),
        "hypothetical": (70,),
    },
    "allcaps_legacy": {
        "historical": (12, 20, 21, 22),
        "negated": (16, 17, 26),
    },
}

DIMENSIONS = ("negated", "uncertain", "historical", "family")


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, default=Path("src/robustehr/resources/assertion_gold.yaml")
    )
    args = parser.parse_args(argv)

    task = json.loads(args.task.read_text(encoding="utf-8"))
    by_fixture: dict[str, list[dict[str, object]]] = {}
    for item in task["items"]:
        by_fixture.setdefault(str(item["fixture"]), []).append(item)

    items = []
    for fixture in sorted(LABELS):
        worksheet = by_fixture[fixture]
        marked: dict[int, list[str]] = {}
        for dimension, positions in LABELS[fixture].items():
            # `hypothetical` folds into `uncertain`: this stage modifies the
            # asserted presence of a concept, and a hedge and a condition are
            # the same move for that. See `concepts.context._NAMES`.
            folded = "uncertain" if dimension == "hypothetical" else dimension
            for position in positions:
                marked.setdefault(position, []).append(folded)
        for position, item in enumerate(worksheet):
            items.append(
                {
                    "fixture": fixture,
                    "start": item["start"],
                    "end": item["end"],
                    "surface": item["surface"],
                    "labels": sorted(set(marked.get(position, []))),
                }
            )

    counts = {d: sum(1 for i in items if d in i["labels"]) for d in DIMENSIONS}
    affirmed = sum(1 for i in items if not i["labels"])
    payload = {
        "schema_version": "1.0",
        "corpus": "tests/fixtures/clinical — synthetic, describes no real patient",
        "why_synthetic": (
            "MIMIC-IV note text is held under the PhysioNet Credentialed Health "
            "Data Use Agreement, and disclosing it to a third party — an LLM "
            "API included — requires authorisation these fixtures do not. They "
            "were written from scratch, so this gold can ship in the repository "
            "rather than in data/, which is why it was built first. A companion "
            "MIMIC gold was built afterwards under confirmed authorisation and "
            "lives in data/ with only its aggregates published: permission to "
            "annotate is not permission to redistribute."
        ),
        "annotator": (
            "Claude Opus 5, reading each note whole and marking the non-affirmed "
            "spans. NOT an independent gold: the annotator had prior exposure to "
            "this codebase, so agreement with medspaCy ConText is a second "
            "opinion rather than a ground truth, and the scorer reports "
            "agreement statistics on that footing."
        ),
        "spans_from": "annotate_document — the spans stage 8 qualifies in production",
        "dimensions": list(DIMENSIONS),
        "fixtures": sorted(LABELS),
        "n_items": len(items),
        "n_affirmed": affirmed,
        "label_counts": counts,
        "items": items,
    }
    text = yaml.safe_dump(payload, sort_keys=True, allow_unicode=True, width=100)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    print(f"{len(items)} items, {affirmed} affirmed -> {args.out}")
    print(f"  labels: {counts}")
    print(f"  sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
