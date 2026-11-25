#!/usr/bin/env python
"""Is stage 8 right about *uncertainty*, not only negation?

`assertion_accuracy.json` validates one of five attributes, because the NegEx
gold labels only `Affirmed`/`Negated`. The other four ship **disclosed and
unvalidated**. This script closes one of them.

**The design problem, and the control that solves it.** The only freely
available uncertainty gold is BioScope, and its clinical subcorpus is de-worded —
every token replaced by ``*``, reconstitutable only with the 2007 CMC challenge
text obtained separately. What remains is biomedical *scientific writing*, and
medspaCy's ConText rules are clinical rules. Hedging in an abstract
(*"suggesting that"*, *"these results indicate"*) is not hedging in a radiology
report (*"cannot exclude"*, *"versus"*). A weak uncertainty score here could
mean weak rules **or** a genre this rule set was never aimed at, and those are
different conclusions.

So negation is scored **on the same sentences**. Both dimensions face the same
genre shift, which makes the comparison interpretable in two directions:

* negation here versus negation on the NegEx clinical gold → **the cost of the
  domain shift**, measured rather than assumed;
* uncertainty versus negation *within* BioScope → **the difference between the
  dimensions**, with domain held constant.

Neither number alone would support a conclusion. Together they separate "our
uncertainty rules are thin" from "this corpus is not our corpus", and the answer
turns out to matter for what may be claimed about `is_uncertain`.

**Unit of evaluation.** BioScope annotates *scopes*, not concept-level labels, so
this scores token-in-scope: every content token is a span, its gold label is
whether it falls inside a negation or speculation scope, and the prediction is
whatever `qualify` assigns that span. That is the corpus's own convention and it
matches how stage 8 is actually used — an attribute attached to a span someone
else supplied.

Licensing: BioScope carries no licence file and is handled exactly like MIMIC.
This artifact reports counts and metrics; no sentence reaches it.
"""

from __future__ import annotations

import argparse
import json
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from robustehr.concepts.anchors import _WORD
from robustehr.concepts.context import qualify
from robustehr.document import Document
from robustehr.types import Span

#: Shortest token scored. One- and two-character tokens are mostly symbols and
#: units in this corpus, and including them would inflate every denominator with
#: items no assertion layer is meant to qualify.
MIN_TOKEN_CHARS = 3

#: BioScope cue type -> the attribute `qualify` reports.
GOLD_TO_ATTRIBUTE = {"negation": "negated", "speculation": "uncertain"}


@dataclass(frozen=True, slots=True)
class Sentence:
    text: str
    scopes: tuple[tuple[int, int, str], ...]
    """``(start, end, cue_type)`` per annotated scope, in character offsets."""


def parse_sentence(element: Any) -> Sentence:
    """Reconstruct a sentence's text and its scope offsets from the XML.

    Offsets have to be built while walking, because `xcope` nests and the text
    of a scope is spread across an element's `text`, its children, and their
    `tail`s. Reading `itertext()` and searching for the scope string afterwards
    would break on any sentence that repeats a phrase.
    """
    parts: list[str] = []
    scopes: list[tuple[int, int, str]] = []
    length = 0

    def walk(node: Any) -> None:
        nonlocal length
        if node.text:
            parts.append(node.text)
            length += len(node.text)
        for child in node:
            start = length
            if child.tag == "xcope":
                kind = next((c.get("type") for c in child.iter("cue")), None)
                walk(child)
                if kind:
                    scopes.append((start, length, kind))
            else:
                walk(child)
            if child.tail:
                parts.append(child.tail)
                length += len(child.tail)

    walk(element)
    return Sentence("".join(parts), tuple(scopes))


def load(path: Path, limit: int) -> list[Sentence]:
    """Sentences in document order, so a limit is a prefix rather than a sample."""
    found: list[Sentence] = []
    for element in ET.parse(path).iter("sentence"):
        sentence = parse_sentence(element)
        if sentence.text.strip():
            found.append(sentence)
        if limit and len(found) >= limit:
            break
    return found


def gold_labels(sentence: Sentence, span: Span) -> set[str]:
    """Which attributes the gold says apply to this span."""
    out: set[str] = set()
    for start, end, kind in sentence.scopes:
        attribute = GOLD_TO_ATTRIBUTE.get(kind or "")
        if attribute and span.start >= start and span.end <= end:
            out.add(attribute)
    return out


def content_spans(text: str) -> tuple[Span, ...]:
    return tuple(
        Span(m.start(), m.end())
        for m in _WORD.finditer(text)
        if len(m.group(0)) >= MIN_TOKEN_CHARS and m.group(0).isalpha()
    )


def score(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    tp = sum(1 for p, t in pairs if p and t)
    fp = sum(1 for p, t in pairs if p and not t)
    fn = sum(1 for p, t in pairs if not p and t)
    tn = sum(1 for p, t in pairs if not p and not t)
    n = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tokens": n,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "prevalence": round((tp + fn) / n, 4) if n else None,
        "accuracy": round((tp + tn) / n, 4) if n else None,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "majority_class_accuracy": round((tn + fp) / n, 4) if n else None,
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("data/bioscope/abstracts.xml"))
    parser.add_argument("--limit", type=int, default=600, help="sentences; 0 means all")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    sentences = load(args.gold, args.limit)
    arms: dict[str, dict[str, list[tuple[bool, bool]]]] = {
        attribute: {"ctx_a_pyrush": [], "ctx_b_our_boundaries": []}
        for attribute in ("negated", "uncertain")
    }

    for sentence in sentences:
        spans = content_spans(sentence.text)
        if not spans:
            continue
        index_a = qualify(sentence.text, spans)
        doc = Document.from_text(sentence.text, uid="bioscope")
        bounds = tuple(s.span.start for s in doc.sentences.sentences)
        index_b = qualify(sentence.text, spans, boundaries=bounds)
        for span in spans:
            truth = gold_labels(sentence, span)
            for attribute in ("negated", "uncertain"):
                want = attribute in truth
                arms[attribute]["ctx_a_pyrush"].append(
                    (attribute in index_a.attributes_for(span), want)
                )
                arms[attribute]["ctx_b_our_boundaries"].append(
                    (attribute in index_b.attributes_for(span), want)
                )

    results = {
        attribute: {arm: score(pairs) for arm, pairs in sorted(by_arm.items())}
        for attribute, by_arm in sorted(arms.items())
    }
    shipped = "ctx_b_our_boundaries"
    payload = {
        "question": "Is stage 8 right about uncertainty, not only negation?",
        "why": (
            "assertion_accuracy.json validates one of five attributes because "
            "the NegEx gold labels only Affirmed/Negated. The other four ship "
            "disclosed and unvalidated; this closes one of them."
        ),
        "gold": {
            "corpus": "BioScope (Vincze et al.), abstracts subcorpus",
            "licence": "none upstream; handled like MIMIC, see data/bioscope/manifest.json",
            "sentences": len(sentences),
            "unit": "token-in-scope — every content token is a span, its gold "
            "label is whether it falls inside an annotated scope",
        },
        "domain_caveat": (
            "**OUT OF DOMAIN.** These are biomedical abstracts, not clinical "
            "notes, and ConText's rules are clinical rules. BioScope's clinical "
            "subcorpus is de-worded (every token is '*', 0 letters against "
            "42,514 asterisks) and needs the 2007 CMC text to reconstitute, "
            "which this project does not have. Negation is scored on the same "
            "sentences so the genre shift is held constant: compare negation "
            "here against 0.9289 on the NegEx clinical gold to price the domain "
            "shift, then compare uncertainty against negation here to isolate "
            "the dimension."
        ),
        "attributes": results,
        "domain_shift_on_negation": {
            "negex_clinical_f1": 0.9289,
            "bioscope_abstracts_f1": results["negated"][shipped]["f1"],
            "delta": round(results["negated"][shipped]["f1"] - 0.9289, 4),
            "how_to_read": (
                "this is the same engine and the same attribute on a different "
                "genre, so the drop is the price of the domain shift and not a "
                "property of the rules. It is the yardstick the uncertainty "
                "number must be read against."
            ),
        },
        "how_to_read": (
            "read uncertainty beside negation *in this table*, never beside the "
            "NegEx figure. If uncertainty is far below negation here, the 18 "
            "speculation rules are thin on their own terms. If the two are "
            "close, the limiting factor is the genre and the honest conclusion "
            "is that no in-domain uncertainty gold exists to settle it."
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
