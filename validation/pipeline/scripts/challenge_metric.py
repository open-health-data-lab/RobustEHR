#!/usr/bin/env python
"""Score our concept matcher on the SNOMED challenge's own metric.

Run so that "how do we compare" has a number rather than an argument. It is a
**context measurement, not a competitive claim**, and four differences have to
travel with it.

1. **Different task.** The challenge is entity linking: find the span *and*
   assign the correct SNOMED concept from 6,595. RobustEHR needs to know what
   *kind* of thing a span is, over 11 coarse categories. Its own reported
   numbers are targeting precision at the category level and are not comparable
   to a concept-level score in either direction.

2. **Different system class.** The winners are purpose-built for this task and
   two of the three are trained on the challenge's own training split. This is
   an untrained, off-the-shelf dictionary matcher with default parameters,
   scored as a **baseline** to say where a reused component sits.

3. **Different evaluation set.** The challenge's true test set was held out and
   is not in the public release. This scores the ``test``-marked rows of the
   released annotations, which is not the same data the leaderboard ranked.

4. **Concepts reached through UMLS.** QuickUMLS returns CUIs; the gold is SNOMED.
   A CUI is credited when any of its SNOMED codes matches, which is more
   forgiving than the challenge's exact concept identity.

The metric itself is the challenge's: character intersection-over-union of
predicted and gold spans, macro-averaged by class so every class weighs equally.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from robustehr.categories import tuis_for
from robustehr.concepts.matcher import ConceptMatcher
from robustehr.concepts.pipeline import annotate_document
from robustehr.document import Document
from robustehr.eval import snomed_el

#: Published final scores, character IoU macro-averaged by class.
LEADERBOARD = {
    "KIRI (dictionary-based)": 0.4202,
    "SNOBERT (encoder-based)": 0.4194,
    "MITEL-UNIUD (decoder-based)": 0.3777,
    "median of all final submissions": 0.2572,
}


def char_iou_macro(
    predicted: dict[str, list[tuple[int, int, str]]],
    gold: dict[str, list[tuple[int, int, str]]],
) -> tuple[float, int]:
    """Character IoU per class, macro-averaged.

    A class is a concept. For each class the predicted and gold character sets
    are pooled across notes, then intersected — the challenge's formulation,
    which rewards partial span overlap rather than demanding exact boundaries.
    """
    pred_chars: dict[str, set[tuple[str, int]]] = defaultdict(set)
    gold_chars: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for note_id, spans in predicted.items():
        for start, end, concept in spans:
            pred_chars[concept].update((note_id, i) for i in range(start, end))
    for note_id, spans in gold.items():
        for start, end, concept in spans:
            gold_chars[concept].update((note_id, i) for i in range(start, end))

    classes = set(gold_chars) | set(pred_chars)
    total = 0.0
    for concept in classes:
        p, g = pred_chars.get(concept, set()), gold_chars.get(concept, set())
        union = p | g
        total += len(p & g) / len(union) if union else 0.0
    return (total / len(classes) if classes else 0.0), len(classes)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0912 - a linear script
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--split", default="test")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--scoped",
        action="store_true",
        help="restrict predictions to the challenge's own scope before scoring",
    )
    args = parser.parse_args(argv)

    cui_to_snomed: dict[str, list[str]] = json.loads(
        (args.root / "cui_snomed.json").read_text(encoding="utf-8")
    )
    corpus = snomed_el.load(args.root, limit=args.limit)
    if args.split:
        corpus = corpus.split(args.split)

    gold: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for span in corpus.spans:
        gold[span.note_id].append((span.span.start, span.span.end, span.concept_id))

    gold_concepts = {s.concept_id for s in corpus.spans}
    matcher = ConceptMatcher(args.index)

    # The challenge annotates only SNOMED's clinical finding, procedure and body
    # structure hierarchies. Scoring an all-of-UMLS matcher against it penalizes
    # every mention the annotators never looked for — measured at 52% of our
    # predictions — which is a property of the comparison rather than of the
    # matcher. `--scoped` restricts predictions to the same ground before
    # scoring, which is the apples-to-apples number.
    scope = tuis_for("disorder", "procedure", "anatomy") if args.scoped else None

    predicted: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for note_id, text in sorted(corpus.notes.items()):
        doc = Document.from_text(text, uid=note_id)
        for mention in annotate_document(doc, matcher).mentions:
            if scope is not None and not (mention.tuis & scope):
                continue
            codes = cui_to_snomed.get(mention.cui, [])
            if scope is not None and not codes:
                continue
            # Credit the CUI's SNOMED code that the gold actually uses, if any.
            # More forgiving than exact concept identity, and stated as such.
            chosen = next((c for c in codes if c in gold_concepts), codes[0] if codes else None)
            if chosen is not None:
                predicted[note_id].append((mention.span.start, mention.span.end, chosen))

    score, classes = char_iou_macro(predicted, gold)

    # Span detection alone, with concept identity collapsed. Decomposes the
    # gap: a low overall score with a high span score means the spans are found
    # and the concept is wrong, which is a different problem with a different
    # fix — and the one that matters for the phenotype layer, since a phenotype
    # is a set of CUIs.
    flat_pred = {n: [(a, b, "ANY") for a, b, _ in v] for n, v in predicted.items()}
    flat_gold = {n: [(a, b, "ANY") for a, b, _ in v] for n, v in gold.items()}
    span_score, _ = char_iou_macro(flat_pred, flat_gold)

    # Category-level, which is what RobustEHR actually needs.
    from robustehr.categories import categories_of

    cat_pred: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    cat_gold: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for note_id, text in sorted(corpus.notes.items()):
        for mention in annotate_document(Document.from_text(text, uid=note_id), matcher).mentions:
            if scope is not None and not (mention.tuis & scope):
                continue
            for category in categories_of(mention.tuis):
                cat_pred[note_id].append((mention.span.start, mention.span.end, category))
    for span in corpus.spans:
        for category in span.categories:
            cat_gold[span.note_id].append((span.span.start, span.span.end, category))
    cat_score, cat_classes = char_iou_macro(cat_pred, cat_gold)
    payload = {
        "metric": "character IoU, macro-averaged by concept (the challenge's metric)",
        "our_score": round(score, 4),
        "classes_scored": classes,
        "span_detection_only": round(span_score, 4),
        "category_level": round(cat_score, 4),
        "category_classes": cat_classes,
        "notes": len(corpus.notes),
        "gold_spans": len(corpus.spans),
        "split": args.split,
        "system": "QuickUMLS via medspaCy, default parameters, untrained",
        "scoped_to_challenge": args.scoped,
        "leaderboard": LEADERBOARD,
        "caveats": [
            "Different task: the challenge is concept-level entity linking over "
            "6,595 concepts; RobustEHR needs category-level typing over 11.",
            "Different system class: the winners are purpose-built and two are "
            "trained on the challenge's training split. This is an untrained "
            "off-the-shelf matcher scored as a baseline.",
            "Different evaluation set: the challenge's test set was held out and "
            "is not public. This scores the test-marked rows of the release.",
            "Concept identity is reached through UMLS CUIs and credited when any "
            "of a CUI's SNOMED codes matches, which is more forgiving.",
        ],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
