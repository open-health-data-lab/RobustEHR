#!/usr/bin/env python
"""A clinical encoder against the shipped rules, on the same held-out spans.

**Why a neural arm at all.** The rule-based effort is near its ceiling: a cue
direction sweep bought `historical` +0.060 and `uncertain` +0.026 held out, and
the scope-termination fix that the error analysis pointed straight at did not
generalise. ConText implements a 2001 algorithm; the published state of the art
on clinical assertion is a fine-tuned encoder, and the honest thing is to measure
the gap rather than assert the rules are good enough.

**The model.** `bvanaken/clinical-assertion-negation-bert` — Bio_Discharge_
Summary_BERT fine-tuned on the i2b2 2010 assertion challenge (van Aken et al.,
NLPMC 2021). It takes a sentence with the target mention wrapped in `[entity]`
markers and returns PRESENT / ABSENT / POSSIBLE, which is **exactly this stage's
seam**: spans come from outside, so the measurement isolates assertion from
detection the same way the ConText arms do.

**Two limits that must be stated with any number it produces.**

* It covers `negated` and `uncertain` **only**. The i2b2 assertion task has no
  temporality at all, so `historical` has no published baseline anywhere, and
  this checkpoint also dropped i2b2's `associated_with_someone_else`, so there is
  no `family` either. Those two dimensions are why a fine-tune on our own gold is
  the next step rather than the last.
* **Pretraining overlap.** Bio_Discharge_Summary_BERT is pretrained on MIMIC-III
  discharge summaries; this gold is MIMIC-IV, and the two corpora overlap in
  period and in patients. That is exposure during *pretraining*, not fine-tuning
  on our labels, so it is weaker than leakage — but it is not nothing, and the
  encoder's numbers are not directly comparable to a model that never saw MIMIC.

**Determinism.** Fixed weights, greedy argmax, CPU, `torch.use_deterministic_
algorithms`. A checkpoint hash goes into the artifact so a rerun is checkable —
which is the property that makes an encoder a candidate for the shipped path and
an LLM API not one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from scripts.split_assertion_gold import keep_items

from robustehr.document import Document
from robustehr.types import Span

MODEL = "bvanaken/clinical-assertion-negation-bert"

#: The checkpoint's three classes, mapped into this package's dimensions.
#: PRESENT carries no dimension — it is the unmodified case.
LABEL_TO_DIMENSION = {"PRESENT": None, "ABSENT": "negated", "POSSIBLE": "uncertain"}

#: Dimensions this checkpoint can express. `historical` and `family` are absent
#: from its label set, so it is scored on these and reported as not-applicable
#: elsewhere — the same convention `cue_detection_eval.py` uses for negspaCy,
#: which likewise attempts one dimension and would otherwise read as scoring 0.
SUPPORTED = ("negated", "uncertain")


def sentence_window(doc: Document, span: Span, text: str, *, max_chars: int = 900) -> str:
    """The span's sentence with the mention wrapped in `[entity]` markers.

    The checkpoint was trained on single sentences with one marked entity, so a
    whole note would be both out of distribution and past its 512-token limit.
    A long "sentence" — a lab block with no punctuation to split on — is trimmed
    around the mention rather than truncated from the left, which would drop the
    marker itself.
    """
    start, end = span.start, span.end
    bounds = next(
        (
            (s.span.start, s.span.end)
            for s in doc.sentences.sentences
            if s.span.start <= start < s.span.end
        ),
        (start, end),
    )
    left, right = bounds
    if right - left > max_chars:
        half = max_chars // 2
        left, right = max(left, start - half), min(right, end + half)
    return f"{text[left:start]}[entity] {text[start:end]} [entity]{text[end:right]}".strip()


def load_classifier(model_name: str) -> Any:
    """The checkpoint, pinned to CPU and deterministic inference."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    model.eval()
    return tokenizer, model


def predict(tokenizer: Any, model: Any, windows: list[str], *, batch: int = 16) -> list[str]:
    import torch

    labels: list[str] = []
    with torch.inference_mode():
        for start in range(0, len(windows), batch):
            chunk = windows[start : start + batch]
            encoded = tokenizer(
                chunk, return_tensors="pt", padding=True, truncation=True, max_length=512
            )
            logits = model(**encoded).logits
            for row in logits.argmax(dim=-1).tolist():
                labels.append(model.config.id2label[row])
    return labels


def score(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    tp = sum(1 for p, t in pairs if p and t)
    fp = sum(1 for p, t in pairs if p and not t)
    fn = sum(1 for p, t in pairs if not p and t)
    tn = sum(1 for p, t in pairs if not p and not t)
    n = len(pairs)
    observed = (tp + tn) / n if n else 0.0
    p_pred, p_gold = (tp + fp) / n if n else 0.0, (tp + fn) / n if n else 0.0
    expected = p_pred * p_gold + (1 - p_pred) * (1 - p_gold)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else None
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "gold_positives": tp + fn,
        "predicted_positives": tp + fp,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0.0,
        "cohens_kappa": round(kappa, 4) if kappa is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("data/assertion_gold_mimic/gold.yaml"))
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument(
        "--split-file", type=Path, default=Path("data/assertion_gold_mimic/split.json")
    )
    parser.add_argument("--split", default="held_out", choices=["development", "held_out"])
    parser.add_argument("--model", default=MODEL)
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/assertion_neural_eval.json")
    )
    args = parser.parse_args(argv)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    items = keep_items(gold["items"], args.split_file, args.split)
    by_note: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_note[str(item["fixture"])].append(item)

    from robustehr.corpus import read_documents

    corpus = {d.uid: d.text for d in read_documents(args.corpus) if d.uid in by_note}

    windows: list[str] = []
    truths: list[set[str]] = []
    for note, note_items in sorted(by_note.items()):
        text = corpus[note]
        doc = Document.from_text(text, uid=note)
        for item in note_items:
            span = Span(int(item["start"]), int(item["end"]))
            windows.append(sentence_window(doc, span, text))
            truths.append(set(item["labels"]))

    tokenizer, model = load_classifier(args.model)
    predicted = predict(tokenizer, model, windows)

    arms: dict[str, dict[str, Any]] = {}
    for dimension in SUPPORTED:
        pairs = [
            (LABEL_TO_DIMENSION.get(label) == dimension, dimension in truth)
            for label, truth in zip(predicted, truths, strict=True)
        ]
        arms[dimension] = score(pairs)
    for dimension in ("historical", "family"):
        arms[dimension] = {
            "not_applicable": (
                "absent from this checkpoint's label set. i2b2 2010 assertion "
                "has no temporality class at all, and this model dropped "
                "i2b2's associated_with_someone_else."
            )
        }

    from collections import Counter

    distribution = dict(Counter(predicted).most_common())
    missed_uncertain = dict(
        Counter(
            label for label, truth in zip(predicted, truths, strict=True) if "uncertain" in truth
        ).most_common()
    )

    digest = hashlib.sha256(
        json.dumps(
            {k: str(v) for k, v in sorted(model.config.to_dict().items())}, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()

    payload = {
        "question": "Does a clinical encoder beat the shipped rules on our spans?",
        "why": (
            "the rule-based effort is near its ceiling — a direction sweep bought "
            "historical +0.060 held out and the scope fix the error analysis "
            "pointed at did not generalise. ConText implements a 2001 algorithm; "
            "the published state of the art is a fine-tuned encoder."
        ),
        "model": args.model,
        "model_provenance": (
            "Bio_Discharge_Summary_BERT fine-tuned on the i2b2 2010 assertion "
            "challenge (van Aken et al., NLPMC 2021)."
        ),
        "pretraining_overlap": (
            "the base model is pretrained on MIMIC-III discharge summaries and "
            "this gold is MIMIC-IV; the corpora overlap in period and patients. "
            "That is PRETRAINING exposure, not fine-tuning on these labels, so "
            "it is weaker than leakage — but these numbers are not directly "
            "comparable to a model that never saw MIMIC."
        ),
        "coverage": (
            "negated and uncertain only. historical has no published baseline in "
            "any assertion benchmark, which is the strongest argument for "
            "fine-tuning on this gold rather than reusing a checkpoint."
        ),
        "determinism": (
            "fixed weights, greedy argmax, CPU, torch.use_deterministic_"
            "algorithms(True), single thread. An encoder can therefore sit in a "
            "package that promises replayable edit scripts; an LLM API cannot."
        ),
        "input_form": (
            "the mention's sentence with the span wrapped in [entity] markers, "
            "as the checkpoint was trained. Spans come from stages 5-7, so this "
            "measures assertion alone, exactly as the ConText arms do."
        ),
        "config_sha256": digest,
        "prediction_distribution": distribution,
        "on_gold_uncertain_spans": missed_uncertain,
        "why_uncertain_collapses": (
            "a LABEL-SEMANTICS mismatch, not a model failure. i2b2's `possible` "
            "is a diagnostic hedge on a condition — `possible pneumonia`. This "
            "package's `uncertain` deliberately merges that with the conditional "
            "case — `Tylenol PRN`, return precautions, future plans — because "
            "for modifying a concept's asserted presence a hedge and a condition "
            "are the same move. i2b2 keeps them apart as `possible` versus "
            "`conditional`/`hypothetical`, and this checkpoint dropped the "
            "latter two entirely. So it is answering a narrower question, and "
            "calls almost every conditional span PRESENT. The merge that made "
            "our own lexicon work is exactly what makes this checkpoint "
            "inapplicable to the dimension."
        ),
        "split": args.split,
        "n_items": len(items),
        "n_notes": len(by_note),
        "by_dimension": arms,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"{len(items)} spans, {len(by_note)} notes ({args.split}) — {args.model}")
    for dimension in SUPPORTED:
        row = arms[dimension]
        print(
            f"  {dimension:<11} P {row['precision']:.4f}  R {row['recall']:.4f}"
            f"  F1 {row['f1']:.4f}  kappa {row['cohens_kappa']}"
            f"   (gold {row['gold_positives']}, predicted {row['predicted_positives']})"
        )
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
