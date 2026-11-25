#!/usr/bin/env python
"""Score matcher configurations on both metrics and record the trajectory.

Runs each configuration over the same notes and gold spans, scores it on the
challenge's character-IoU metric *and* on per-category recall and targeting
precision, and appends the result to ``validation/measurements/benchmark_history.json``.

Both are tracked because they can move in opposite directions, and a change that
improves the leaderboard number while degrading category recall is a regression
for this package however it looks published. Only a history makes that visible.

Configurations that alter QuickUMLS's matching parameters are recorded with
``inherits_quickumls_validation: false``. That is not a warning label to be
ignored — it means the published evaluation no longer covers the configuration
and it owes its own.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from robustehr.categories import load_categories, tuis_for
from robustehr.concepts.matcher import ConceptMatcher, MatcherConfig
from robustehr.concepts.pipeline import annotate_document
from robustehr.document import Document
from robustehr.eval import snomed_el
from robustehr.eval.ablation import EVALUABLE
from robustehr.eval.benchmark import Entry, History
from robustehr.eval.snomed_el import score
from robustehr.lexicon import load_clinical_lexicon
from robustehr.target import Categories, TargetContext

CHALLENGE_SCOPE = ("disorder", "procedure", "anatomy")

#: How predictions are restricted before scoring on the challenge metric.
#:
#: `none`        every UMLS concept the matcher finds
#: `snomed`      any concept with a SNOMED code — the honest apples-to-apples
#:               scope, since the gold is SNOMED and nothing else was annotated
#: `gold_tuis`   the semantic types the gold actually uses, read from the data
#: `categories`  RobustEHR's curated categories
#:
#: `categories` is the package's own view and is the wrong lens for a
#: leaderboard comparison: the curated set omits semantic types the annotators
#: did use, which costs benchmark performance for no benefit. Measured on the
#: full corpus it still covers 96.9% of annotations, so it is a small handicap
#: rather than a large one — but a handicap taken for nothing is still worth
#: removing when the question is "how do we compare".
SCOPES = ("none", "snomed", "gold_tuis", "categories")


def resolve_scope(name: str, corpus) -> frozenset[str] | None:
    if name == "categories":
        return tuis_for(*CHALLENGE_SCOPE)
    if name == "gold_tuis":
        return frozenset(t for span in corpus.spans for t in span.tuis)
    return None


def char_iou_macro(predicted, gold) -> tuple[float, int]:
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


#: The configurations to try. Each names one hypothesis about why the matcher
#: underperforms, so a result attributes to a cause rather than to a number.
#: An entry is (label, matcher overrides, scope, note, index override or None).
CONFIGS: list[tuple[str, dict[str, Any], str, str]] = [
    ("baseline (defaults)", {}, "none", "QuickUMLS defaults, all of UMLS"),
    (
        "scoped: categories",
        {},
        "categories",
        "restricted to RobustEHR's curated categories — the package's own view",
    ),
    (
        "scoped: gold semantic types",
        {},
        "gold_tuis",
        "restricted to the semantic types the annotators actually used",
    ),
    (
        "scoped: SNOMED only",
        {},
        "snomed",
        "any concept with a SNOMED code — the apples-to-apples scope",
    ),
    (
        "threshold 0.8",
        {"threshold": 0.8},
        "snomed",
        "stricter similarity — fewer, better matches?",
    ),
    (
        "threshold 0.9",
        {"threshold": 0.9},
        "snomed",
        "near-exact matching only",
    ),
    (
        "threshold 1.0 (exact)",
        {"threshold": 1.0},
        "snomed",
        "exact dictionary matching, the plan's original design",
    ),
    (
        "overlap by length",
        {"overlapping_criteria": "length"},
        "snomed",
        "prefer longer spans — helps multi-word procedures?",
    ),
    (
        "overlap by length + affix trim",
        {"overlapping_criteria": "length", "trim_affixes": True},
        "snomed",
        "longest match, then drop leading/trailing function words. Targets the "
        "52% fragmentation class directly: 'shortness of breath' stops "
        "collapsing to 'breath', without the 'and vitamin D deficiency' "
        "over-extension that preferring length alone introduces",
    ),
    (
        "length + trim + prefer SNOMED",
        {"overlapping_criteria": "length", "trim_affixes": True, "_prefer": "snomed"},
        "snomed",
        "as above, plus a similarity tie-break toward SNOMED-linked concepts. "
        "Targets the remaining granularity errors: 'diabetes' returned C0011847 "
        "(Diabetes), which carries no SNOMED code at all and so can never be a "
        "member of a SNOMED-seeded phenotype set, over C0011849 (Diabetes "
        "Mellitus), which the annotators chose",
    ),
    (
        "cosine similarity",
        {"similarity_name": "cosine"},
        "snomed",
        "different similarity measure",
    ),
    (
        "min_match_length 5",
        {"min_match_length": 5},
        "snomed",
        "drop very short matches, which are the noisiest",
    ),
    # Best scope combined with best threshold. The two were found under
    # different conditions, so the combination is not implied by either.
    (
        "exact + gold semantic types",
        {"threshold": 1.0},
        "gold_tuis",
        "best scope with exact matching — the plan's original design",
    ),
    (
        "0.9 + gold semantic types",
        {"threshold": 0.9},
        "gold_tuis",
        "best scope, near-exact matching",
    ),
    # 94% of missed gold spans are single words and most are lab abbreviations
    # — hgb, hct, creat, wbc, mcv, na, cl, mg. The default min_match_length of 3
    # cannot match the two-character ones at all, so the sweep has to test
    # lowering it as well as raising it.
    (
        "exact + min_match_length 2",
        {"threshold": 1.0, "min_match_length": 2},
        "gold_tuis",
        "admit two-character abbreviations: na, cl, hr, mg",
    ),
    (
        "exact + min_match_length 1",
        {"threshold": 1.0, "min_match_length": 1},
        "gold_tuis",
        "admit every length — how much noise does that buy?",
    ),
    (
        "default threshold + min_match_length 2",
        {"min_match_length": 2},
        "gold_tuis",
        "shorter matches without exactness, to separate the two effects",
    ),
    # Vocabulary change rather than parameter change: an index built from
    # SNOMEDCT_US terms only, so the matcher's vocabulary is the gold's.
    (
        "SNOMED-only index",
        {"_index": "data/quickumls_snomed"},
        "gold_tuis",
        "index built from SNOMEDCT_US terms only — vocabulary aligned with gold",
    ),
    (
        "SNOMED-only index + exact",
        {"_index": "data/quickumls_snomed", "threshold": 1.0},
        "gold_tuis",
        "aligned vocabulary with exact matching",
    ),
    # Aligning QuickUMLS's semantic-type filter with RobustEHR's categories.
    # Leaving it at their defaults filtered twice with two different filters and
    # silently dropped terms our categories want — `wbc` is T025 Cell, in our
    # `anatomy` but not in their 27.
    (
        "aligned semtypes",
        {"_semtypes": "ours"},
        "gold_tuis",
        "QuickUMLS filter aligned with RobustEHR's categories",
    ),
    (
        "aligned semtypes + mml 2",
        {"_semtypes": "ours", "min_match_length": 2},
        "gold_tuis",
        "aligned filter, admitting two-character abbreviations",
    ),
    (
        "aligned + exact + mml 2",
        {"_semtypes": "ours", "threshold": 1.0, "min_match_length": 2},
        "gold_tuis",
        "aligned filter, exact matching, short abbreviations",
    ),
    (
        "SNOMED-only + exact + mml 2",
        {"_index": "data/quickumls_snomed", "threshold": 1.0, "min_match_length": 2},
        "gold_tuis",
        "aligned vocabulary, exact, admitting short abbreviations",
    ),
]


def evaluate(
    corpus,
    matcher: ConceptMatcher,
    lexicon,
    cui_to_snomed: dict[str, list[str]],
    *,
    scope_name: str,
) -> dict[str, Any]:
    scope = resolve_scope(scope_name, corpus)
    require_snomed = scope_name != "none"
    gold_concepts = {s.concept_id for s in corpus.spans}

    gold_by_note: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for span in corpus.spans:
        gold_by_note[span.note_id].append((span.span.start, span.span.end, span.concept_id))

    predicted: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    per_category: dict[str, list] = defaultdict(list)

    for note_id, text in sorted(corpus.notes.items()):
        doc = Document.from_text(text, uid=note_id)
        # The composed pipeline, not bare matcher output. Measuring
        # `matcher.annotate` here would report the pre-stage-3 system while the
        # CLI runs the post-stage-3 one — the same defect that made the
        # phenotype numbers describe a configuration nothing used.
        mentions = annotate_document(doc, matcher)
        gold = corpus.for_note(note_id)

        for mention in mentions.mentions:
            if scope is not None and not (mention.tuis & scope):
                continue
            codes = cui_to_snomed.get(mention.cui, [])
            if require_snomed and not codes:
                continue
            if not codes:
                continue
            chosen = next((c for c in codes if c in gold_concepts), codes[0])
            predicted[note_id].append((mention.span.start, mention.span.end, chosen))

        ctx = TargetContext(doc=doc, lexicon=lexicon, mentions=mentions)
        for category in EVALUABLE:
            target = Categories(category)
            spans = [t.span for t in doc.tokens if t.is_content and target.admits(t.span, ctx)]
            per_category[category].append(score(spans, gold, category, "sweep"))

    challenge, _ = char_iou_macro(predicted, gold_by_note)
    flat_p = {n: [(a, b, "ANY") for a, b, _ in v] for n, v in predicted.items()}
    flat_g = {n: [(a, b, "ANY") for a, b, _ in v] for n, v in gold_by_note.items()}
    span_iou, _ = char_iou_macro(flat_p, flat_g)

    recall, precision = {}, {}
    for category, scores in per_category.items():
        gold_total = sum(s.gold for s in scores)
        covered = sum(s.gold_covered for s in scores)
        selected = sum(s.selected for s in scores)
        hits = sum(s.hits for s in scores)
        recall[category] = round(covered / gold_total, 4) if gold_total else None
        precision[category] = round(hits / selected, 4) if selected else None
    return {
        "challenge_iou": round(challenge, 4),
        "span_iou": round(span_iou, 4),
        "category_recall": recall,
        "category_precision": precision,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--lexicon", type=Path, default=Path("data/lexicon/clinical_tokens.txt"))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--split", default="test")
    parser.add_argument("--only", nargs="*", default=None, help="run only these labels")
    parser.add_argument(
        "--stamp",
        default=None,
        help="date to record; defaults to today. Read here rather than in the "
        "package, which must never depend on when it ran.",
    )
    args = parser.parse_args(argv)

    corpus = snomed_el.load(args.root, limit=args.limit)
    if args.split:
        corpus = corpus.split(args.split)
    lexicon = load_clinical_lexicon(args.lexicon)
    cui_to_snomed = json.loads((args.root / "cui_snomed.json").read_text(encoding="utf-8"))

    stamp = args.stamp or datetime.now(UTC).strftime("%Y-%m-%d")
    history = History.load()
    for label, overrides, scoped, note in CONFIGS:
        if args.only and label not in args.only:
            continue
        params = dict(overrides)
        # A label may name an alternate index — a vocabulary change rather than
        # a parameter change, and the two are worth keeping distinguishable.
        index = Path(params.pop("_index", args.index))
        if params.pop("_prefer", None) == "snomed":
            params["preferred_cuis"] = frozenset(cui_to_snomed)
        if params.pop("_semtypes", None) == "ours":
            params["accepted_semtypes"] = frozenset(
                t for c in load_categories().values() for t in c.tuis
            )
        config = MatcherConfig(**params)
        matcher = ConceptMatcher(index, config)
        print(f"scoring {label} ...", flush=True)
        result = evaluate(corpus, matcher, lexicon, cui_to_snomed, scope_name=scoped)
        entry = Entry(
            label=label,
            # The *resolved* configuration, not just the overrides: an entry
            # recording only what changed cannot say whether the rest is at
            # defaults, which is exactly what the inheritance check needs.
            config={
                "threshold": config.threshold,
                "similarity_name": config.similarity_name,
                "min_match_length": config.min_match_length,
                "overlapping_criteria": config.overlapping_criteria,
                "trim_affixes": config.trim_affixes,
                "preferred_cuis": (
                    None
                    if config.preferred_cuis is None
                    else f"snomed:{len(config.preferred_cuis)}"
                ),
                "window": config.window,
                "accepted_semtypes": (
                    "quickumls_default"
                    if config.accepted_semtypes is None
                    else f"robustehr:{len(config.accepted_semtypes)}"
                ),
                "scope": scoped,
                "canon": config.canon(),
                "index": index.name,
            },
            challenge_iou=result["challenge_iou"],
            span_iou=result["span_iou"],
            category_recall=result["category_recall"],
            category_precision=result["category_precision"],
            notes_scored=len(corpus.notes),
            gold_spans=len(corpus.spans),
            note=note,
        )
        history.add(entry, stamp=stamp)
        print(f"   challenge={result['challenge_iou']} span={result['span_iou']}")

    history.save()
    print()
    print(history.table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
