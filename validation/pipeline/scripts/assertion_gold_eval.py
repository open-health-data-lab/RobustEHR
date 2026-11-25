#!/usr/bin/env python
"""Score stage 8 against a frozen assertion gold, on all four dimensions.

The gap this closes: `assertion_accuracy.json` validates negation on clinical
gold, `scope_accuracy.json` bounds uncertainty out of domain, and `historical`,
and `family` had **nothing at all** — yet three SEMANTIC operators
(`temporality_shift`, `experiencer_shift` and `uncertainty_flip`) would anchor on
exactly those detectors.

Five baselines run beside the three ConText arms. `lexicon_cooccurrence` is the
floor — a cue literal anywhere in the span's sentence, no scope logic — so the
gap above it is what the scope algorithm earns. `negspacy` is a third-party NegEx
brought over from `assertion_accuracy.py`, which is how the rank reversal between
curated single sentences and real discharge summaries became visible.

**This is a second opinion, not a ground truth, and the statistics say so.** The
annotator is an LLM with prior exposure to this codebase, so what is measured is
*agreement between two imperfect raters*, and Cohen's κ is reported beside
precision and recall for that reason. A high κ means the deterministic rule set
and an independent-ish reading of the note reach the same conclusion; it does not
mean either is right. Where they disagree the disagreement is enumerated, because
that list is more useful than the coefficient.

**Prevalence governs what may be claimed per dimension.** With 52 negated spans a
recall estimate is worth reporting; with 2 uncertain ones it is not, and the
scorer refuses to dress up an F1 computed on single digits. Dimensions below a
floor are reported as counts and disagreements only.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from scripts.split_assertion_gold import keep_items

from robustehr.concepts.context import qualify
from robustehr.document import Document
from robustehr.resources import load_yaml
from robustehr.types import Span

GOLD_RESOURCE = "assertion_gold.yaml"

#: ConText's rule categories, mapped to the dimensions this package reports.
#: HYPOTHETICAL and POSSIBLE_EXISTENCE both land on `uncertain` — see
#: `concepts.context._NAMES`, which this mirrors for the rule file rather than
#: for the spaCy attribute names.
ATTRIBUTE_TO_DIMENSION = {
    "NEGATED_EXISTENCE": "negated",
    "POSSIBLE_EXISTENCE": "uncertain",
    "HYPOTHETICAL": "uncertain",
    "HISTORICAL": "historical",
    "FAMILY": "family",
}

#: Fewest positives for which precision, recall and F1 are reported. Below this
#: the estimate's confidence interval spans most of the unit interval and a
#: three-decimal figure would be false precision.
MIN_POSITIVES = 10


def kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """Cohen's kappa between predicted and gold, over one dimension.

    Reported instead of raw agreement because these classes are rare: a rater
    that says "affirmed" to everything agrees with the gold on 85% of spans and
    has learned nothing. Kappa prices that away.
    """
    n = len(pairs)
    if not n:
        return None
    observed = sum(1 for p, t in pairs if p == t) / n
    p_pred = sum(1 for p, _ in pairs if p) / n
    p_gold = sum(1 for _, t in pairs if t) / n
    expected = p_pred * p_gold + (1 - p_pred) * (1 - p_gold)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def score(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    tp = sum(1 for p, t in pairs if p and t)
    fp = sum(1 for p, t in pairs if p and not t)
    fn = sum(1 for p, t in pairs if not p and t)
    tn = sum(1 for p, t in pairs if not p and not t)
    positives = tp + fn
    out: dict[str, Any] = {
        "gold_positives": positives,
        "predicted_positives": tp + fp,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "cohens_kappa": round(k, 4) if (k := kappa(pairs)) is not None else None,
    }
    if positives < MIN_POSITIVES:
        out["metrics_withheld"] = (
            f"fewer than {MIN_POSITIVES} gold positives; precision, recall and "
            "F1 would be false precision at this prevalence"
        )
        return out
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / positives
    out["precision"] = round(precision, 4)
    out["recall"] = round(recall, 4)
    out["f1"] = (
        round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0
    )
    return out


def load_texts(gold: dict[str, Any], corpus: Path | None) -> dict[str, str]:
    """Document text for every key the gold references.

    Two golds, two sources: the synthetic gold names fixtures, the MIMIC gold
    names `note_id`s in a corpus file. Reading whichever the gold declares keeps
    one scorer rather than two that can drift.
    """
    if gold.get("source") == "corpus":
        if corpus is None:
            raise SystemExit("this gold references a corpus; pass --corpus")
        from robustehr.corpus import read_documents

        wanted = {i["fixture"] for i in gold["items"]}
        return {d.uid: d.text for d in read_documents(corpus) if d.uid in wanted}
    from tests.fixtures.clinical import FORMATS

    return {name: note.text for name, note in FORMATS.items()}


def lexicon_terms() -> dict[str, list[str]]:
    """Every literal in medspaCy's rule file, by reported dimension.

    The vocabulary with the engine removed. Shared with `cue_detection_eval.py`
    in intent but re-derived here rather than imported, because that script
    scores cue *spans* and this one scores *span classification* — the same
    lexicon answering two different questions.
    """
    from robustehr.concepts.matcher import _neutral_cwd

    with _neutral_cwd():
        import medspacy

    root = Path(medspacy.__file__).resolve().parents[1]
    path = root / "resources" / "en" / "context_rules.json"
    out: dict[str, list[str]] = defaultdict(list)
    for rule in json.loads(path.read_text(encoding="utf-8"))["context_rules"]:
        if rule.get("direction") == "TERMINATE":
            continue
        dimension = ATTRIBUTE_TO_DIMENSION.get(str(rule.get("category", "")))
        if dimension and rule.get("literal"):
            out[dimension].append(str(rule["literal"]).lower())
    return dict(out)


def sentence_bounds(doc: Document, span: Span) -> tuple[int, int]:
    """The sentence containing `span`, as offsets into the note."""
    for sentence in doc.sentences.sentences:
        if sentence.span.start <= span.start < sentence.span.end:
            return sentence.span.start, sentence.span.end
    return span.start, span.end


def cooccurrence_labels(
    text: str, bounds: tuple[int, int], terms: dict[str, list[str]]
) -> set[str]:
    """Dimensions whose vocabulary appears anywhere in the span's sentence.

    **The floor for span-level assertion.** No direction, no scope, no
    termination: a cue literal anywhere in the sentence assigns its dimension to
    every span in that sentence. It is what a keyword search would achieve, and
    the gap between it and ConText is the value the scope algorithm actually
    adds — as opposed to the value of knowing which words are cues, which both
    arms get for free from the same rule file.
    """
    window = text[bounds[0] : bounds[1]].lower()
    return {
        dimension
        for dimension, literals in terms.items()
        if any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", window) for t in literals)
    }


def negspacy_pipeline() -> Any:
    """negspaCy on a blank pipeline — a third-party NegEx, negation only.

    The same arm `assertion_accuracy.py` runs against the NegEx gold, brought
    here so the comparison that exists on 2,365 curated single-sentence rows
    also exists on real multi-sentence discharge summaries. It reports no
    dimension but negation, which is the whole reason this package does not ship
    it despite it winning the negation benchmark.
    """
    import negspacy.negation  # noqa: F401
    import spacy

    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    nlp.add_pipe("negex", config={"chunk_prefix": []})
    return nlp


def negspacy_labels(nlp: Any, text: str, spans: tuple[Span, ...]) -> dict[Span, set[str]]:
    """Negation per span, by giving negspaCy our spans as its entities."""
    from spacy.tokens import Span as SpacySpan

    # `make_doc` skips the pipeline, so the sentencizer is applied explicitly:
    # negspaCy terminates scope at sentence boundaries and raises without them.
    doc = nlp.get_pipe("sentencizer")(nlp.make_doc(text))
    entities = []
    for span in spans:
        found = doc.char_span(span.start, span.end, label="CONCEPT", alignment_mode="expand")
        if found is not None:
            entities.append(found)
    kept: list[SpacySpan] = []
    seen: set[int] = set()
    for entity in sorted(entities, key=lambda e: (e.start, -e.end)):
        if any(t.i in seen for t in entity):
            continue
        seen.update(t.i for t in entity)
        kept.append(entity)
    doc.ents = kept
    doc = nlp.get_pipe("negex")(doc)
    out: dict[Span, set[str]] = {}
    for span in spans:
        found = doc.char_span(span.start, span.end, alignment_mode="expand")
        match = next((e for e in doc.ents if found is not None and e.start == found.start), None)
        out[span] = {"negated"} if match is not None and match._.negex else set()
    return out


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--gold",
        type=Path,
        default=None,
        help="gold YAML; defaults to the packaged synthetic resource",
    )
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument(
        "--split-file", type=Path, default=Path("data/assertion_gold_mimic/split.json")
    )
    parser.add_argument("--split", default=None, choices=["development", "held_out"])
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    gold = (
        yaml.safe_load(args.gold.read_text(encoding="utf-8"))
        if args.gold
        else load_yaml(GOLD_RESOURCE)
    )
    gold["items"] = keep_items(gold["items"], args.split_file, args.split)
    # A restricted gold is note-derived and its surfaces may not be published.
    # The flag lives in the gold rather than in a caller's argument so the rule
    # travels with the data instead of depending on somebody remembering it.
    restricted = bool(gold.get("restricted"))
    texts = load_texts(gold, args.corpus)
    dimensions = list(gold["dimensions"])
    by_fixture: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in gold["items"]:
        by_fixture[item["fixture"]].append(item)

    arms: dict[str, dict[str, list[tuple[bool, bool]]]] = {
        arm: {d: [] for d in dimensions}
        for arm in (
            "ctx_a_pyrush",
            "ctx_b_our_boundaries",
            "ctx_c_extended_cues",
            "lexicon_cooccurrence",
            "negspacy",
        )
    }
    terms = lexicon_terms()
    negex = negspacy_pipeline()
    disagreements: list[dict[str, Any]] = []

    for fixture, items in sorted(by_fixture.items()):
        text = texts[fixture]
        doc = Document.from_text(text, uid=fixture)
        spans = tuple(Span(int(i["start"]), int(i["end"])) for i in items)
        bounds = tuple(s.span.start for s in doc.sentences.sentences)
        indexes = {
            "ctx_a_pyrush": qualify(text, spans),
            "ctx_b_our_boundaries": qualify(text, spans, boundaries=bounds),
            "ctx_c_extended_cues": qualify(text, spans, boundaries=bounds, extended=True),
        }
        floor = {s_: cooccurrence_labels(text, sentence_bounds(doc, s_), terms) for s_ in spans}
        negated = negspacy_labels(negex, text, spans)
        for item, span in zip(items, spans, strict=True):
            truth = set(item["labels"])
            per_arm = {arm: set(ix.attributes_for(span)) for arm, ix in indexes.items()}
            per_arm["lexicon_cooccurrence"] = floor[span]
            # negspaCy reports negation only. Scoring it as a silent negative on
            # the other three would read as "it got them wrong"; it does not
            # attempt them, and that distinction is the point of the row.
            per_arm["negspacy"] = negated[span]
            for arm, predicted in per_arm.items():
                for dimension in dimensions:
                    if arm == "negspacy" and dimension != "negated":
                        continue
                    arms[arm][dimension].append((dimension in predicted, dimension in truth))
                if arm == "ctx_b_our_boundaries" and predicted != truth:
                    entry = {"gold": sorted(truth), "context": sorted(predicted)}
                    if not restricted:
                        entry["fixture"] = fixture
                        entry["surface"] = item["surface"]
                    disagreements.append(entry)

    results = {
        arm: {d: score(pairs) for d, pairs in by_dimension.items()}
        for arm, by_dimension in arms.items()
    }
    payload = {
        "question": (
            "Does stage 8 agree with a careful reading of the note, on all four dimensions?"
        ),
        "why": (
            "negation had clinical gold and uncertainty an out-of-domain proxy; "
            "historical and family had nothing, yet three SEMANTIC operators "
            "would anchor on them."
        ),
        "status_of_this_gold": (
            "a SECOND OPINION, not a ground truth. The annotator is an LLM with "
            "prior exposure to this codebase, so agreement is between two "
            "imperfect raters. Cohen's kappa is the headline for that reason, "
            "and the disagreement list matters more than the coefficient."
        ),
        "corpus": gold["corpus"],
        "restricted": restricted,
        # Counted from the items actually scored, not from the gold's header:
        # under `--split` the header describes the whole gold and would overstate
        # the sample this result rests on.
        "split": args.split or "all",
        "n_items": len(gold["items"]),
        "n_affirmed": sum(1 for i in gold["items"] if not i["labels"]),
        "gold_label_counts": {
            d: sum(1 for i in gold["items"] if d in i["labels"]) for d in dimensions
        },
        "arms": results,
        "prevalence_note": (
            f"dimensions with fewer than {MIN_POSITIVES} gold positives report "
            "counts and kappa only. The fixture corpus is negation-dense and "
            "hedge-poor, so `uncertain` in particular is too thin here to score "
            "— scope_accuracy.json remains its only quantitative evidence."
        ),
        "ctx_b_disagreements": disagreements,
        "how_to_read": (
            "kappa near 1 means the deterministic rule set and a careful reading "
            "reach the same conclusion; it does not establish that either is "
            "right. A dimension with high kappa is one where the rules can be "
            "trusted to behave predictably enough to anchor an operator. A "
            "dimension with low kappa is one where a SEMANTIC operator would be "
            "editing spans nobody can agree about."
        ),
    }
    text_out = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text_out + "\n", encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
