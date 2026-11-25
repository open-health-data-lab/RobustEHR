#!/usr/bin/env python
"""Distil the LLM gold into a deterministic encoder, and see whether 600 spans is enough.

**The architecture this is testing.** The gold is frontier-LLM supervision — two
independent models over the same 1,000 spans, agreeing at κ 0.845-0.913. An LLM
cannot sit in this package's shipped path, which promises replayable edit scripts
and whose AST lint bans `random`, `hash()` and wall-clock from `src/`. An encoder
can: fixed weights, greedy argmax, CPU, and a checkpoint hash that folds into
provenance like any other resource. So:

    LLM annotates  ->  encoder distils  ->  deterministic detector ships

**Why a fine-tune is needed at all**, given that an off-the-shelf i2b2 checkpoint
already beats the rules on negation by 0.117 F1: it covers negation and nothing
else. i2b2's assertion task has no temporality class, so `historical` has no
published baseline in any benchmark, and the checkpoint dropped
`associated_with_someone_else` too. Only training on this gold can reach those.

**The training signal is thin, and that is stated before the numbers rather than
after them.** 600 development spans carry 82 `uncertain`, 61 `historical`, 47
`negated` and **5 `family`**. Five examples cannot teach a class; `family` is
reported for completeness and should be read as untrained. `negated` at 47 is
also unlikely to beat a checkpoint already fine-tuned on i2b2's thousands.

**Multi-label, because the dimensions co-occur** — `no history of X` is both
`negated` and `historical`. Four independent sigmoids with a positive-class
weight, not a four-way softmax, which would force a false choice.

**The held-out half is never touched during training.** Model selection uses a
validation slice carved out of the *development* notes, so early stopping cannot
see the test half. The split is note-level throughout, for the reason recorded in
`split_assertion_gold.py`: a vocabulary or a weight matrix that has read one span
of a note has read the phrasing of every span in it.
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
from scripts.assertion_neural_eval import score, sentence_window
from scripts.split_assertion_gold import keep_items

from robustehr.concepts.context import DIMENSIONS
from robustehr.document import Document
from robustehr.types import Span

#: Encoders to fine-tune. Two bases, and the pair is the point.
#:
#: `Bio_ClinicalBERT` is pretrained on MIMIC-III, which overlaps MIMIC-IV in
#: period and patients — the better-suited model and the contaminated one.
#: `BiomedBERT` is pretrained on PubMed only and has never seen a clinical note,
#: so it is the **contamination control**: if the MIMIC-pretrained base wins by a
#: lot, some of that margin is exposure rather than domain fit, and the gap
#: between them bounds how much.
#:
#: The i2b2 assertion checkpoint is included as a third base because starting
#: from a model that already knows negation is the obvious way to spend 47
#: negated examples.
BASES = (
    "emilyalsentzer/Bio_ClinicalBERT",
    "microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext",
    "bvanaken/clinical-assertion-negation-bert",
)

#: Fixed a priori, not tuned. With 600 examples a hyperparameter search would
#: fit the validation slice and report a number that means nothing.
EPOCHS = 8
LEARNING_RATE = 2e-5
BATCH = 16
SEED = 20260804
VALIDATION_NOTES = 12
MAX_LENGTH = 256


def build_examples(
    gold: dict[str, Any], split_file: Path, split: str, corpus: Path
) -> tuple[list[str], list[list[float]], list[str]]:
    """`(windows, multi-hot labels, note ids)` for one half of the gold."""
    from robustehr.corpus import read_documents

    items = keep_items(gold["items"], split_file, split)
    by_note: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_note[str(item["fixture"])].append(item)
    texts = {d.uid: d.text for d in read_documents(corpus) if d.uid in by_note}

    windows: list[str] = []
    labels: list[list[float]] = []
    notes: list[str] = []
    for note, note_items in sorted(by_note.items()):
        text = texts[note]
        doc = Document.from_text(text, uid=note)
        for item in note_items:
            span = Span(int(item["start"]), int(item["end"]))
            windows.append(sentence_window(doc, span, text))
            labels.append([float(d in set(item["labels"])) for d in DIMENSIONS])
            notes.append(note)
    return windows, labels, notes


def validation_notes(notes: list[str], count: int) -> set[str]:
    """A held-back slice of the *development* notes, hash-ranked.

    Carved from development rather than from the test half so early stopping
    cannot see the numbers this script will report. Hash-ranked per the house
    rule so it replays exactly.
    """
    unique = sorted(set(notes))
    ordered = sorted(
        unique, key=lambda n: hashlib.blake2b(f"val\x1f{n}".encode(), digest_size=8).hexdigest()
    )
    return set(ordered[:count])


def encode(tokenizer: Any, texts: list[str]) -> tuple[Any, Any]:
    """`(input_ids, attention_mask)`, padded to a fixed length.

    Fixed-length rather than dynamic padding so a batch boundary cannot change
    a prediction — the same determinism concern that governs everything else
    here.
    """
    encoded = tokenizer(
        texts, return_tensors="pt", padding="max_length", truncation=True, max_length=MAX_LENGTH
    )
    return encoded["input_ids"], encoded["attention_mask"]


def train_one(base: str, train: Any, val: Any, n_labels: int) -> Any:
    """Fine-tune `base` and return the model at its best validation loss."""
    import torch
    from torch.utils.data import DataLoader, TensorDataset
    from transformers import AutoModelForSequenceClassification

    torch.manual_seed(SEED)
    model = AutoModelForSequenceClassification.from_pretrained(
        base,
        num_labels=n_labels,
        problem_type="multi_label_classification",
        ignore_mismatched_sizes=True,
    )
    train_x, train_mask, train_y = train
    # Positive-class weighting, because `family` is 0.8% of the development half
    # and an unweighted loss would learn to answer "no" to everything and score
    # well doing it.
    positives = train_y.sum(dim=0).clamp(min=1.0)
    pos_weight = ((len(train_y) - positives) / positives).clamp(max=50.0)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimiser = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)

    generator = torch.Generator().manual_seed(SEED)
    loader = DataLoader(
        TensorDataset(train_x, train_mask, train_y),
        batch_size=BATCH,
        shuffle=True,
        generator=generator,
    )
    val_x, val_mask, val_y = val
    best_loss, best_state = float("inf"), None
    for epoch in range(EPOCHS):
        model.train()
        for x, mask, y in loader:
            optimiser.zero_grad()
            loss = loss_fn(model(input_ids=x, attention_mask=mask).logits, y)
            loss.backward()
            optimiser.step()
        model.eval()
        with torch.inference_mode():
            val_loss = loss_fn(model(input_ids=val_x, attention_mask=val_mask).logits, val_y).item()
        print(f"    epoch {epoch + 1}/{EPOCHS}  val_loss {val_loss:.4f}")
        if val_loss < best_loss:
            best_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model, round(best_loss, 4)


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("data/assertion_gold_mimic/gold.yaml"))
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument(
        "--split-file", type=Path, default=Path("data/assertion_gold_mimic/split.json")
    )
    parser.add_argument("--bases", nargs="*", default=list(BASES))
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/assertion_finetune.json")
    )
    args = parser.parse_args(argv)

    import torch
    from transformers import AutoTokenizer

    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)

    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    dev_x, dev_y, dev_notes = build_examples(gold, args.split_file, "development", args.corpus)
    test_x, test_y, _ = build_examples(gold, args.split_file, "held_out", args.corpus)
    held_back = validation_notes(dev_notes, VALIDATION_NOTES)
    is_val = [note in held_back for note in dev_notes]

    counts = {d: int(sum(row[i] for row in dev_y)) for i, d in enumerate(DIMENSIONS)}
    print(f"development {len(dev_x)} spans ({sum(is_val)} held back for validation)")
    print(f"  training positives: {counts}")
    print(f"held out    {len(test_x)} spans\n")

    arms: dict[str, Any] = {}
    for base in args.bases:
        print(f"== {base}")
        tokenizer = AutoTokenizer.from_pretrained(base)
        train_texts = [t for t, v in zip(dev_x, is_val, strict=True) if not v]
        train_labels = [y for y, v in zip(dev_y, is_val, strict=True) if not v]
        val_texts = [t for t, v in zip(dev_x, is_val, strict=True) if v]
        val_labels = [y for y, v in zip(dev_y, is_val, strict=True) if v]

        tx, tm = encode(tokenizer, train_texts)
        vx, vm = encode(tokenizer, val_texts)
        ex, em = encode(tokenizer, test_x)
        model, best_loss = train_one(
            base,
            (tx, tm, torch.tensor(train_labels)),
            (vx, vm, torch.tensor(val_labels)),
            len(DIMENSIONS),
        )

        with torch.inference_mode():
            probabilities = torch.sigmoid(model(input_ids=ex, attention_mask=em).logits)
        predicted = (probabilities >= 0.5).tolist()

        per_dimension = {}
        for index, dimension in enumerate(DIMENSIONS):
            pairs = [
                (bool(p[index]), bool(t[index])) for p, t in zip(predicted, test_y, strict=True)
            ]
            row = score(pairs)
            row["training_positives"] = counts[dimension]
            if counts[dimension] < 10:
                row["untrained"] = (
                    f"{counts[dimension]} training examples. Reported for "
                    "completeness; a class this rare cannot be learned and the "
                    "figure is not evidence about the method."
                )
            per_dimension[dimension] = row
        arms[base] = {"best_validation_loss": best_loss, "by_dimension": per_dimension}

        for dimension in DIMENSIONS:
            row = per_dimension[dimension]
            print(
                f"    {dimension:<11} F1 {row['f1']:.4f}  P {row['precision']:.4f}"
                f"  R {row['recall']:.4f}  kappa {row['cohens_kappa']}"
                f"  (train n={counts[dimension]})"
            )
        print()

    payload = {
        "question": "Can 600 LLM-annotated spans distil into a deterministic encoder?",
        "why": (
            "the gold is frontier-LLM supervision at kappa 0.845-0.913, and an "
            "LLM cannot sit in a package that promises replayable edit scripts. "
            "An encoder can. This tests whether the supervision transfers."
        ),
        "architecture": "LLM annotates -> encoder distils -> deterministic detector ships",
        "why_not_the_i2b2_checkpoint": (
            "it beats the rules on negation by 0.117 F1 and covers nothing else. "
            "i2b2 assertion has no temporality class, so `historical` has no "
            "published baseline anywhere, and the checkpoint dropped "
            "associated_with_someone_else as well."
        ),
        "training_signal": counts,
        "training_signal_warning": (
            "600 development spans carrying 82 uncertain, 61 historical, 47 "
            "negated and FIVE family. Five examples cannot teach a class. "
            "negated at 47 is also unlikely to beat a checkpoint already "
            "fine-tuned on i2b2's thousands."
        ),
        "task_form": (
            "multi-label — four independent sigmoids with positive-class "
            "weighting, not a four-way softmax, because the dimensions co-occur "
            "(`no history of X` is both negated and historical)."
        ),
        "model_selection": (
            f"{VALIDATION_NOTES} development NOTES held back for early stopping. "
            "The test half is never seen during training or selection."
        ),
        "hyperparameters": {
            "epochs": EPOCHS,
            "learning_rate": LEARNING_RATE,
            "batch": BATCH,
            "seed": SEED,
            "max_length": MAX_LENGTH,
            "note": (
                "fixed a priori, not searched. With 600 examples a "
                "hyperparameter sweep would fit the validation slice."
            ),
        },
        "contamination_control": (
            "Bio_ClinicalBERT is pretrained on MIMIC-III, which overlaps "
            "MIMIC-IV in period and patients. BiomedBERT is pretrained on PubMed "
            "and has never seen a clinical note. The gap between them bounds how "
            "much of the clinical model's margin is exposure rather than domain "
            "fit."
        ),
        "n_train": len(dev_x) - sum(is_val),
        "n_validation": sum(is_val),
        "n_test": len(test_x),
        "arms": arms,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
