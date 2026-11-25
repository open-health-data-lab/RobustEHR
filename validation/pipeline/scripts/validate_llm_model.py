#!/usr/bin/env python
"""Score your chosen LLM against a gold before trusting it with your notes.

**The problem this solves.** These operators let you name any OpenRouter model.
That is the right design — model availability and price move faster than a
release cycle — but it means a user can point the SEMANTIC channel at something
that reads assertion badly and find out only from downstream results that make no
sense. Measured on the held-out MIMIC gold, the spread between two models from
the same vendor one tier apart is F1 0.33 against 0.97 on negation. Naming a
model is a decision, and this is the instrument for making it.

**It runs out of the box, with no credentialed data.** The default gold is the
**synthetic** fixture gold that ships in the package — 350 spans over seven notes
written from scratch, describing no real patient. A new user can therefore
validate a model in one command with no data agreement, no download and no
credentials beyond an OpenRouter key.

Be clear about what that buys and what it does not. The fixture corpus is
negation-dense and hedge-poor — 52 negated spans against 14 uncertain, 8
historical and 1 family — so it will tell you confidently whether a model handles
negation and only weakly whether it handles the rest. It is a **smoke test with
real numbers**, not the corpus the published figures come from. Pass `--gold` to
point at the MIMIC gold if you hold the credentials, and the same script reports
against it.

**Reference numbers for orientation.** On the held-out MIMIC gold, with the same
prompt this script uses:

    model                       negated  uncertain  historical  unmodified
    google/gemini-3.6-flash       0.970     0.886      0.865       0.969
    google/gemini-2.5-flash       0.838     0.695      0.623       0.856
    google/gemini-2.5-flash-lite  0.326     0.400      0.400       0.679
    (the shipped rule detector)   0.608     0.442      0.294        --

Those are on a different, harder corpus than this script's default, so treat them
as ordering rather than as thresholds your fixture-gold run should reproduce.

Cost: the fixture gold is seven short notes, so a full run is a few cents at
Flash prices. Responses cache, so re-running is free and offline.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Any

import yaml

from robustehr import llm
from robustehr.concepts.context import DIMENSIONS
from robustehr.resources import load_yaml

#: What the shipped rule detector scores on the same fixture gold, so a user can
#: see immediately whether their model is worth the network round trip.
RULE_REFERENCE = {"negated": 0.7788, "uncertain": 0.3810, "historical": None, "family": None}

#: Below this on `negated` — the dimension the fixture gold can actually measure
#: — a model is not worth using for the SEMANTIC channel.
NEGATED_FLOOR = 0.70


def build_prompt(sentence: str, marked: str) -> str:
    """The detection prompt, reusing the flip resource's dimension language.

    Deliberately the *same* wording the annotation arms used, including the base
    rate and the governance requirement, so a score here is comparable to the
    reference table above rather than to a prompt this script invented.
    """
    return (
        "You are reading one sentence from a clinical note.\n\n"
        f"Sentence:\n{sentence}\n\n"
        f"The span in question is: {marked}\n\n"
        "Which of these modifiers does the note apply to that span?\n"
        "  negated    - the note says it is absent or denied\n"
        "  uncertain  - hedged, possible, or conditional on something that has "
        "not happened\n"
        "  historical - framed as past rather than the current episode\n"
        "  family     - the finding belongs to someone other than the patient\n\n"
        "MOST SPANS CARRY NONE. About 70% of spans in clinical notes are "
        "affirmed, current and the patient's, and their answer is the empty "
        "list. Returning [] is the normal outcome.\n\n"
        "A modifier applies only if a cue in the text GOVERNS THIS SPAN, not if "
        "one merely appears nearby. If you are weighing a modifier against none, "
        "choose none.\n\n"
        'Reply with a JSON list and nothing else, for example ["negated"] or [].'
    )


def parse(reply: str) -> set[str]:
    """The model's labels, or an empty set if it did not answer in the contract."""
    text = reply.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        return set()
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return set()
    folded = {"uncertain" if x == "hypothetical" else str(x) for x in parsed}
    return {x for x in folded if x in DIMENSIONS}


def score(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    tp = sum(1 for p, t in pairs if p and t)
    fp = sum(1 for p, t in pairs if p and not t)
    fn = sum(1 for p, t in pairs if not p and t)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "gold_positives": tp + fn,
        "predicted_positives": tp + fp,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0.0,
    }


def load_fixture_gold() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The packaged synthetic gold and the fixture texts it references."""
    from tests.fixtures.clinical import FORMATS

    gold = load_yaml("assertion_gold.yaml")
    return list(gold["items"]), {name: note.text for name, note in FORMATS.items()}


def sentence_around(text: str, start: int, end: int, *, width: int = 400) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right = min(
        (i for i in (text.find(".", end), text.find("\n", end)) if i != -1), default=len(text)
    )
    if right - left > width:
        left, right = max(left, start - width // 2), min(right, end + width // 2)
    return text[left:right].strip()


def load_gold(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """`(items, texts, label)` for whichever gold was asked for."""
    if args.gold is None:
        items, texts = load_fixture_gold()
        return items, texts, "packaged synthetic fixtures (no credentials needed)"
    from robustehr.corpus import read_documents

    if args.corpus is None:
        raise SystemExit("--gold needs --corpus")
    gold = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    items = list(gold["items"])
    wanted = {str(i["fixture"]) for i in items}
    texts = {d.uid: d.text for d in read_documents(args.corpus) if d.uid in wanted}
    return items, texts, str(args.gold)


def predict_all(
    config: llm.LlmConfig, items: list[dict[str, Any]], texts: dict[str, str]
) -> tuple[list[set[str]], list[set[str]], int]:
    """One cached call per span. Progress printed because this is user-facing."""
    predictions: list[set[str]] = []
    truths: list[set[str]] = []
    unparsed = 0
    for position, item in enumerate(items, start=1):
        text = texts[str(item["fixture"])]
        start, end = int(item["start"]), int(item["end"])
        prompt = build_prompt(sentence_around(text, start, end), repr(text[start:end]))
        try:
            reply = llm.complete(config, prompt)
        except llm.LlmUnavailable as error:
            raise SystemExit(f"call failed at span {position}: {error}") from error
        found = parse(reply)
        if not found and "[" not in reply:
            unparsed += 1
        predictions.append(found)
        truths.append(set(item["labels"]))
        if position % 50 == 0:
            print(f"  {position}/{len(items)} spans")
    return predictions, truths, unparsed


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=None, help=f"defaults to ${llm.MODEL_ENV}")
    parser.add_argument("--gold", type=Path, default=None, help="defaults to the packaged gold")
    parser.add_argument("--corpus", type=Path, default=None, help="needed with --gold")
    parser.add_argument("--limit", type=int, default=0, help="score only the first N spans")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        config = llm.configure(args.model)
    except llm.LlmUnavailable as error:
        raise SystemExit(str(error)) from error

    items, texts, corpus_name = load_gold(args)
    if args.limit:
        items = items[: args.limit]

    print(f"model  {config.model}")
    print(f"gold   {corpus_name} — {len(items)} spans\n")
    predictions, truths, unparsed = predict_all(config, items, texts)

    rows = {}
    for dimension in (*DIMENSIONS, "unmodified"):

        def holds(labels: set[str], dimension: str = dimension) -> bool:
            return not labels if dimension == "unmodified" else dimension in labels

        rows[dimension] = score(
            [(holds(p), holds(t)) for p, t in zip(predictions, truths, strict=True)]
        )
    exact = sum(1 for p, t in zip(predictions, truths, strict=True) if p == t)

    print(f"\n  exact label set  {exact}/{len(items)} = {exact / len(items):.4f}")
    for dimension, row in rows.items():
        reference = RULE_REFERENCE.get(dimension)
        against = f"   (shipped rules {reference})" if reference else ""
        note = "" if row["gold_positives"] >= 10 else "  [too few positives to judge]"
        print(
            f"  {dimension:<11} F1 {row['f1']:.4f}  P {row['precision']:.4f}"
            f"  R {row['recall']:.4f}  n={row['gold_positives']}{against}{note}"
        )
    if unparsed:
        print(f"\n  {unparsed} replies did not follow the JSON contract")

    negated = float(rows["negated"]["f1"])
    verdict = (
        f"USABLE — negated F1 {negated:.3f} clears the {NEGATED_FLOOR} floor"
        if negated >= NEGATED_FLOOR
        else f"NOT RECOMMENDED — negated F1 {negated:.3f} is below the "
        f"{NEGATED_FLOOR} floor, and below what the offline rule detector "
        "already achieves. Use a stronger model, or the deterministic operators."
    )
    print(f"\n  {verdict}")

    if args.out:
        payload = {
            "question": "Is this model good enough to flip assertions in my notes?",
            "model": config.model,
            "gold": corpus_name,
            "n_items": len(items),
            "exact_label_set_agreement": round(exact / len(items), 4),
            "unparsed_replies": unparsed,
            "by_dimension": rows,
            "negated_floor": NEGATED_FLOOR,
            "verdict": verdict,
            "caveat": (
                "the packaged gold is negation-dense and hedge-poor, so it "
                "judges negation confidently and the other dimensions weakly. "
                "It is a smoke test with real numbers, not the corpus the "
                "published figures come from."
            ),
            **llm.provenance(config),
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
