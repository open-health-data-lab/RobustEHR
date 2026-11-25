#!/usr/bin/env python
"""How much phenotype evidence is negated, historical, or someone else's?

The measurement that decides whether ``phenotype_scope`` needs an assertion
layer, rather than the assumption that it obviously does.

The argument for needing one is intuitive — "no evidence of pneumonia" is not
evidence of pneumonia — but it does not survive contact with what the two modes
actually do. Under ``protect``, every mention of the phenotype is withheld from
every operator, and a negated mention is still a mention whose corruption would
change what the note says; protecting it is correct. Under ``target``, a negated
mention is still phenotype-related text, and corrupting it is still a
phenotype-targeted corruption. Neither mode's *eligibility* decision changes with
assertion status.

Where assertion does change something is **reporting**. ``evidence_touch``
counts edits landing on phenotype evidence, and an edit landing on
``denies chest pain`` has a different downstream meaning from one landing on
``severe chest pain``. Collapsing them makes the headline table less informative
than it looks.

So the question this script answers is quantitative: how much evidence is
non-affirmed? If it is a rounding error, one number suffices and the assertion
layer is deferrable. This runs medspaCy ConText over the gold evidence spans and
counts.

Requires the clinical extra (``uv pip install medspacy``). Not part of CI, for
the same reason ``probe_deid_assertion.py`` is not.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.phenotype_eval import PHENOTYPES

from robustehr.concepts import hierarchy
from robustehr.concepts.context import _NAMES, ATTRIBUTES, qualify
from robustehr.document import Document
from robustehr.eval import phenotype as ph
from robustehr.eval import snomed_el

__all__ = ["ATTRIBUTES", "assertions_for", "main"]


def assertions_for(text: str, spans: list[Any], *, ours: bool = True) -> list[dict[str, bool]]:
    """Each gold span's ConText attributes, via the shipped stage-8 component.

    This used to be sixty lines reimplementing `concepts.context.qualify` — the
    same pipeline construction, the same ``alignment_mode='expand'``, the same
    overlap pruning — with one difference that mattered: it did *not* sort, so
    its output order was spaCy's. Delegating removes the duplication and makes
    this measurement deterministic, and it also means the number reported here
    describes the component the package actually ships rather than a copy of it.

    ``ours`` selects this package's sentence boundaries over PyRuSH's. Both are
    reported, because the gap between them *is* the segmentation result at
    corpus scale — the NegEx gold cannot show it, since every row there is one
    sentence.
    """
    wanted = tuple(gold.span for gold in spans)
    if not ours:
        return _flags(qualify(text, wanted))
    doc = Document.from_text(text, uid="assertion")
    boundaries = tuple(s.span.start for s in doc.sentences.sentences)
    return _flags(qualify(text, wanted, boundaries=boundaries))


def _flags(index: Any) -> list[dict[str, bool]]:
    return [
        {attr: _NAMES[attr] in assertion.attributes for attr in ATTRIBUTES}
        for assertion in index.assertions
    ]


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa.json"))
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--split", default="test")
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    corpus = snomed_el.load(args.root, limit=args.limit)
    if args.split:
        corpus = corpus.split(args.split)
    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = ph.load_maps(args.root)

    declared = [
        (name, ph.declare(name, seeds, isa, code_to_cuis, cui_to_codes, max_depth=args.depth))
        for name, seeds in PHENOTYPES
    ]

    def measure(*, ours: bool) -> tuple[list[dict[str, Any]], Counter[str], int]:
        rows: list[dict[str, Any]] = []
        overall: Counter[str] = Counter()
        overall_total = 0
        for name, pheno in declared:
            by_note: dict[str, list[Any]] = {}
            for span in ph.evidence_spans(corpus, pheno):
                by_note.setdefault(span.note_id, []).append(span)
            counts: Counter[str] = Counter()
            total = 0
            for note_id, spans in sorted(by_note.items()):
                for flags in assertions_for(corpus.notes[note_id], spans, ours=ours):
                    total += 1
                    for attr, value in flags.items():
                        if value:
                            counts[attr] += 1
                    if not any(flags.values()):
                        counts["affirmed"] += 1
            overall += counts
            overall_total += total
            rows.append(
                {
                    "phenotype": name,
                    "evidence_spans": total,
                    "counts": dict(sorted(counts.items())),
                    "non_affirmed_rate": round(1 - counts["affirmed"] / total, 4)
                    if total
                    else None,
                }
            )
        return rows, overall, overall_total

    rows, overall, overall_total = measure(ours=True)
    _, legacy, legacy_total = measure(ours=False)

    payload = {
        "question": (
            "How much expert-annotated phenotype evidence is negated, historical, "
            "or attributed to someone other than the patient?"
        ),
        "why_it_matters": (
            "Not for eligibility — protect withholds every mention regardless of "
            "assertion, and target corrupts every mention regardless. It matters "
            "for reporting: an edit landing on 'denies chest pain' means something "
            "different from one landing on 'severe chest pain', and evidence_touch "
            "collapses them unless the assertion is carried alongside."
        ),
        "source": "medspaCy ConText over gold evidence spans; detection is not in question",
        "notes": len(corpus.notes),
        "phenotypes": rows,
        "overall": {
            "evidence_spans": overall_total,
            "counts": dict(sorted(overall.items())),
            "non_affirmed_rate": round(1 - overall["affirmed"] / overall_total, 4)
            if overall_total
            else None,
        },
        "boundaries": "this package's segmenter (the shipped configuration)",
        "comparison_pyrush_boundaries": {
            "evidence_spans": legacy_total,
            "counts": dict(sorted(legacy.items())),
            "non_affirmed_rate": round(1 - legacy["affirmed"] / legacy_total, 4)
            if legacy_total
            else None,
            "why": (
                "the same spans scored with medspaCy's own sentence splitter. "
                "The gap is the segmentation result at corpus scale, which the "
                "NegEx gold cannot show because every row there is a single "
                "sentence. PyRuSH attributes more of everything — historical "
                "most of all — which is what a cue leaking past a list or header "
                "boundary looks like in aggregate."
            ),
        },
        "supersedes": (
            "an earlier 0.4286 non-affirmed rate, which was measured over 12 "
            "notes and 133 spans rather than 68 and 934, and with PyRuSH "
            "boundaries. Both the sample and the segmenter changed, so the "
            "figure is superseded rather than corrected; comparison_pyrush_"
            "boundaries isolates the segmenter's share of the difference."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
