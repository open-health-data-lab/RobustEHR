#!/usr/bin/env python
"""Our sentence segmentation against PyRuSH, the clinical baseline.

The most foundational component in the package and, until this script, the least
validated: 2,178 lines of segmentation checked only against golden fixtures we
wrote ourselves. Everything downstream reads it — concept spans, ConText scope,
section priors, and half the operators' units — so self-validation is not enough.

**Why this comparison and not a gold standard.** There is no clean public
sentence-boundary gold for MIMIC discharge summaries. Inventing one by annotating
a sample would make the reference our own judgement again, which is the problem
rather than the fix. So this measures **agreement with PyRuSH** (Jianlin Shi's
rule-based clinical splitter, what medspaCy ships and what most clinical NLP
pipelines use) and then **classifies every disagreement**, because the
disagreement taxonomy is the informative output. A number without it would say
nothing about which splitter is right.

**The hypothesis worth testing**, stated before looking: our segmentation should
beat PyRuSH specifically on **de-identification placeholders**, because it is
de-id-aware by construction and PyRuSH is not. ``probe_deid_assertion.py``
already shows that a placeholder can end a sentence spuriously, letting a
negation cue take scope over the next clause and flip an active diagnosis to
negated. If that is real, it appears here as a disagreement class concentrated
on placeholder boundaries — and if it does not appear, the honest conclusion is
that we should use PyRuSH and delete our splitter.

Requires the clinical extra. Not part of CI, for the same reason the other
baseline probes are not.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.concepts.matcher import _neutral_cwd
from robustehr.corpus import read_documents
from robustehr.segment.deid import index_deid

#: How far apart two boundaries may be and still count as the same decision.
#:
#: Zero would make trailing-whitespace conventions look like disagreements.
#: One character absorbs that without absorbing any real difference: no two
#: genuinely different sentence splits land within one character of each other.
BOUNDARY_TOLERANCE = 1


def build_pyrush() -> Any:
    try:
        from loguru import logger

        logger.remove()  # PyRuSH emits a DEBUG line per token otherwise
    except ImportError:  # pragma: no cover - loguru ships with medspacy
        pass
    with _neutral_cwd():
        import medspacy

        return medspacy.load(medspacy_enable=["medspacy_pyrush"])


def pyrush_boundaries(nlp: Any, text: str) -> list[int]:
    """Sentence *start* offsets, which is what the two systems can be compared on."""
    return [sent.start_char for sent in nlp(text).sents]


def ours_boundaries(text: str) -> list[int]:
    from robustehr.document import Document

    return [s.span.start for s in Document.from_text(text, uid="cmp").sentences.sentences]


def classify(offset: int, text: str) -> str:  # noqa: PLR0911 - one return per class
    """What kind of boundary is this? The disagreement taxonomy.

    Ordered most specific first, because a boundary can satisfy several and the
    most informative label should win — a placeholder immediately before a
    boundary is the case under test, and reporting it as "after punctuation"
    would hide exactly what the script exists to find.
    """
    before = text[max(0, offset - 40) : offset]
    after = text[offset : offset + 40]
    stripped = before.rstrip()
    if index_deid(before[-14:]).placeholders or index_deid(after[:14]).placeholders:
        return "de-id placeholder"
    if stripped.endswith(":"):
        return "after a colon (header or label)"
    if not stripped or before.endswith("\n\n"):
        return "blank line"
    if before.endswith("\n"):
        return "line break, no terminal punctuation"
    if stripped and stripped[-1] in ".!?":
        return "after terminal punctuation"
    if stripped and stripped[-1].isdigit():
        return "after a digit (list number or value)"
    return "mid-line, no cue"


def compare(ours: list[int], theirs: list[int], text: str) -> dict[str, Any]:
    """Boundary-level agreement, plus what each system found alone."""
    theirs_set = sorted(theirs)

    def near(offset: int, pool: list[int]) -> bool:
        return any(abs(offset - p) <= BOUNDARY_TOLERANCE for p in pool)

    only_ours = [o for o in ours if not near(o, theirs_set)]
    only_theirs = [t for t in theirs_set if not near(t, ours)]
    shared = len(ours) - len(only_ours)
    return {
        "ours_n": len(ours),
        "pyrush_n": len(theirs_set),
        "agreed": shared,
        "only_ours": [(o, classify(o, text)) for o in only_ours],
        "only_pyrush": [(t, classify(t, text)) for t in only_theirs],
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--examples",
        type=Path,
        default=None,
        help="write sampled disagreements here for adjudication. CONTAINS NOTE "
        "TEXT — must never be written under docs/ or committed. A Jaccard "
        "figure without examples is not interpretable, so this exists, but the "
        "output is DUA-restricted like any other note excerpt.",
    )
    parser.add_argument("--per-class", type=int, default=4)
    args = parser.parse_args(argv)
    if args.examples and "docs" in args.examples.parts:
        print("--examples contains note text and must not be written under docs/", file=sys.stderr)
        return 2

    nlp = build_pyrush()
    totals = Counter[str]()
    only_ours = Counter[str]()
    only_pyrush = Counter[str]()
    notes = 0
    samples: dict[str, list[str]] = {}

    def keep(system: str, kind: str, offset: int, text: str) -> None:
        bucket = samples.setdefault(f"{system} :: {kind}", [])
        if len(bucket) < args.per_class:
            before = repr(text[max(0, offset - 60) : offset])
            after = repr(text[offset : offset + 60])
            bucket.append(f"{before}  ||SPLIT||  {after}")

    for doc in read_documents(args.corpus, limit=args.limit):
        result = compare(ours_boundaries(doc.text), pyrush_boundaries(nlp, doc.text), doc.text)
        notes += 1
        totals["ours"] += result["ours_n"]
        totals["pyrush"] += result["pyrush_n"]
        totals["agreed"] += result["agreed"]
        for offset, kind in result["only_ours"]:
            only_ours[kind] += 1
            keep("ours only", kind, offset, doc.text)
        for offset, kind in result["only_pyrush"]:
            only_pyrush[kind] += 1
            keep("pyrush only", kind, offset, doc.text)

    union = totals["ours"] + totals["pyrush"] - totals["agreed"]
    payload = {
        "question": (
            "Does RobustEHR's segmentation agree with the clinical baseline, and "
            "where it does not, which one is right?"
        ),
        "baseline": "PyRuSH via medspaCy — the clinical sentence splitter in common use",
        "why_no_gold": (
            "no clean public sentence-boundary gold exists for MIMIC discharge "
            "summaries, and annotating one ourselves would make the reference our "
            "own judgement again. Agreement plus a disagreement taxonomy is the "
            "honest measurement; the taxonomy is the informative half."
        ),
        "tolerance_chars": BOUNDARY_TOLERANCE,
        "notes": notes,
        "boundaries": {
            "ours": totals["ours"],
            "pyrush": totals["pyrush"],
            "agreed": totals["agreed"],
            "jaccard": round(totals["agreed"] / union, 4) if union else None,
        },
        "only_ours": dict(only_ours.most_common()),
        "only_pyrush": dict(only_pyrush.most_common()),
    }
    if args.examples:
        lines = []
        for key in sorted(samples):
            lines.append(f"\n### {key}")
            lines.extend(f"  {x}" for x in samples[key])
        args.examples.write_text("\n".join(lines) + "\n", encoding="utf-8")
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
