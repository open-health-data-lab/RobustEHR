#!/usr/bin/env python
"""Is stage 8 *right*? Six arms against Chapman's NegEx gold.

Stage 8 shipped with `assertion_stability.json`, which asks whether an assertion
survives a perturbation proved not to change clinical meaning. That is a real
gate and it caught a real confound — but **a contextualizer that marked every
span affirmed would pass it perfectly**, at a 0.0000 flip rate, while being
wrong on every negation in the corpus. Stability and correctness are different
properties and the stage had only the first.

This is the second. The gold is `Annotations-1-120.txt`: 2,376 concept-level
assertions over discharge summaries, each a concept *within* a sentence, which
is exactly the shape `qualify` consumes — spans supplied from outside, so the
measurement isolates assertion from detection.

**Six arms, ordered from free to shipped, each isolating one variable:**

* **majority** — always affirmed. The free floor, and it is *high*: negation is
  rare, so this scores about 0.79 accuracy while getting every negation wrong.
  That is the whole reason accuracy is not reported as the headline anywhere
  below; negated-class F1 is what discriminates.
* **dependency_parse** — a ``neg`` dependency governing the mention's head, over
  spaCy's parser. A different *algorithmic family*: no cue list, no scope
  window, no sentence boundary. Included because every other arm descends from
  Chapman, and a benchmark where all methods share one ancestor cannot show
  whether the family itself is the right choice for clinical text.
* **window** — literal cues within N tokens, direction-aware. Tests whether
  cue-scope resolution buys anything over a flat window. It is *not* NegEx:
  `anchors._WORD` tokenizes to single alphanumeric runs, so multi-word cues like
  ``no evidence of`` are approximated by their head token. A weak baseline, and
  reported as one.
* **negspacy** — an independent third-party NegEx implementation. Separates *the
  published algorithm works* from *medspaCy's implementation of it works*, which
  no configuration of our own component can distinguish.
* **CTX-A** — medspaCy ConText with its own PyRuSH boundaries.
* **CTX-B** — medspaCy ConText with this package's segmenter. Four documents,
  the CTX-B ablation rung and the L4 evaluation rung all say our boundaries
  should replace PyRuSH here; none of them measured it. This arm does.

If CTX-B does not beat CTX-A we ship PyRuSH and say so with a number. The gate
discipline that redirected stages 3 and 4 applies to our own promises too.

`negspacy` and the parser model are **benchmark-only** dependencies. Neither is
imported by the package, and a machine without them can still run everything
except this script.

Licensing: the gold is unlicensed upstream and handled like MIMIC — it lives in
`data/`, and this script emits counts and metrics only. No sentence reaches the
artifact, including in the error samples, which carry the *concept* string and a
report id rather than the text around it.
"""

from __future__ import annotations

import argparse
import csv
import json
import warnings
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from robustehr.concepts.anchors import _WORD
from robustehr.concepts.context import qualify
from robustehr.concepts.matcher import _neutral_cwd
from robustehr.document import Document
from robustehr.types import Span

#: Tokens either side of the mention that the window arm looks at. Matches the
#: `abbrev_cues.yaml` default so the two rungs use one hyperparameter.
WINDOW_TOKENS = 8

#: The ConText categories that mean "negated" in the gold's binary scheme.
NEGATING = ("NEGATED_EXISTENCE",)

#: Longest concept string reproduced in the committed error sample. The gold's
#: `Concept` column is usually a clinical term, which is terminology content and
#: safe, but occasionally holds an entire report line. Capping keeps unlicensed
#: note text out of an artifact that ships.
CONCEPT_CHARS = 40


@dataclass(frozen=True, slots=True)
class Row:
    report: str
    concept: str
    sentence: str
    negated: bool
    span: Span


def load_gold(path: Path) -> list[Row]:
    """Gold rows whose concept can be located in their sentence.

    The concept is uppercased inside the sentence, so the match is
    case-insensitive. Rows where it cannot be found are counted, never guessed.
    """
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        raw = list(csv.DictReader(handle, delimiter="\t"))
    rows: list[Row] = []
    for record in raw:
        label = (record.get("Negation") or "").strip()
        sentence = record.get("Sentence") or ""
        concept = (record.get("Concept") or "").strip()
        if label not in ("Affirmed", "Negated") or not concept:
            continue
        at = sentence.lower().find(concept.lower())
        if at < 0:
            continue
        rows.append(
            Row(
                report=(record.get("Report No.") or "").strip(),
                concept=concept,
                sentence=sentence,
                negated=label == "Negated",
                span=Span(at, at + len(concept)),
            )
        )
    return rows


def context_literals() -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """Single-token ConText literals for the window arm, split by direction.

    Read from the installed rule file rather than transcribed, so the baseline
    tracks the same medspaCy the CTX arms use. Multi-word literals contribute
    their *last* token for FORWARD rules and their *first* for BACKWARD — the
    head that sits nearest the target — which is the approximation that makes
    this a weak baseline rather than a reimplementation of NegEx.
    """
    import json as _json
    import pathlib

    # nltk's meta-path finder refuses any module resolving under the cwd, and
    # medspaCy imports it transitively through QuickUMLS.
    with _neutral_cwd():
        import medspacy

    # medspaCy resolves this as parents[2] of medspacy/context/context.py, i.e.
    # site-packages — the resources tree sits beside the package, not inside it.
    root = pathlib.Path(medspacy.__file__).resolve().parents[1]
    rules = _json.loads(
        (root / "resources" / "en" / "context_rules.json").read_text(encoding="utf-8")
    )["context_rules"]
    forward: set[str] = set()
    backward: set[str] = set()
    for rule in rules:
        if rule.get("category") not in NEGATING:
            continue
        tokens = [m.group(0).lower() for m in _WORD.finditer(rule.get("literal", ""))]
        if not tokens:
            continue
        if rule.get("direction") == "FORWARD":
            forward.add(tokens[-1])
        elif rule.get("direction") == "BACKWARD":
            backward.add(tokens[0])
    return {"negated": (frozenset(forward), frozenset(backward))}


@lru_cache(maxsize=1)
def _negspacy() -> Any:
    """negspaCy — an independent third-party NegEx implementation for spaCy.

    A genuinely different codebase implementing the same published algorithm, so
    it separates "Chapman's algorithm works" from "medspaCy's implementation of
    it works". Given a blank English pipeline plus a sentencizer, because the
    arm under test is the negation component and not somebody's tokenizer.
    """
    with _neutral_cwd():
        # Importing the module is what registers the `negex` factory with spaCy.
        import negspacy.negation  # noqa: F401
        import spacy

        nlp = spacy.blank("en")
        nlp.add_pipe("sentencizer")
        nlp.add_pipe("negex", config={"chunk_prefix": []})
        return nlp


@lru_cache(maxsize=1)
def _parser() -> Any:
    """A dependency parser, for the syntactic arm."""
    with _neutral_cwd():
        import spacy

        return spacy.load("en_core_web_sm", exclude=["ner"])


def negspacy_predicts_negated(text: str, span: Span) -> bool:
    nlp = _negspacy()
    doc = nlp.make_doc(text)
    converted = doc.char_span(span.start, span.end, label="MENTION", alignment_mode="expand")
    if converted is None:
        return False
    doc.ents = [converted]
    for _, proc in nlp.pipeline:
        doc = proc(doc)
    return bool(next((e._.negex for e in doc.ents), False))


#: Determiners that negate the phrase they attach to. English marks *"no X"* as
#: a determiner and reserves the ``neg`` relation for *"not"*, so a detector
#: keyed on ``neg`` alone misses the commonest clinical negation entirely.
NEGATING_DETERMINERS = frozenset({"no", "neither", "without"})


def dependency_predicts_negated(text: str, span: Span) -> bool:
    """Syntactic negation, over the parse tree rather than a cue list.

    A different *algorithmic family* from every other arm — no clinical cue
    inventory, no scope window, no sentence boundary. Included because the other
    five all descend from Chapman, and a benchmark where every method shares one
    ancestor cannot show whether the family itself is the right choice here.

    **Deliberately the strongest fair version, not the textbook one.** A bare
    ``neg``-dependency detector scores 0.0000 on this gold, because English
    parses *"No pericardial effusion"* as a **determiner** and reserves ``neg``
    for *"not"* — which is rare in clinical prose. Reporting that number would
    be a straw man. So this also accepts a negating determiner anywhere on the
    mention's head chain, which covers *"no evidence of X"* where ``X`` is a
    prepositional object two hops from the determiner.

    What it still cannot reach is *"denies X"*, where the negation is carried by
    the lexical verb and nothing in the parse marks it. That gap is the finding:
    it is why this field built cue-based systems instead of using parsers.
    """
    doc = _parser()(text)
    converted = doc.char_span(span.start, span.end, alignment_mode="expand")
    if converted is None:
        return False
    for token in converted:
        walker = token
        for _ in range(6):  # bounded: the chain terminates at a self-headed root
            for child in walker.children:
                if child.dep_ == "neg":
                    return True
                if child.dep_ == "det" and child.lemma_.lower() in NEGATING_DETERMINERS:
                    return True
            if walker.head is walker:
                break
            walker = walker.head
    return False


def window_predicts_negated(
    text: str, span: Span, cues: dict[str, tuple[frozenset[str], frozenset[str]]], size: int
) -> bool:
    """A FORWARD cue in the preceding window, or a BACKWARD cue in the following one.

    Direction matters: `no` before a mention negates it, `no` after it does not.
    `anchors._window_tokens` merges both sides into one frozenset, so the two
    halves are taken separately here using the same tokenizer.
    """
    before = [m.group(0).lower() for m in _WORD.finditer(text[: span.start])][-size:]
    after = [m.group(0).lower() for m in _WORD.finditer(text[span.end :])][:size]
    forward, backward = cues["negated"]
    return bool(forward & set(before)) or bool(backward & set(after))


def score(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    """Confusion matrix and negated-class metrics from (predicted, truth) pairs."""
    tp = sum(1 for p, t in pairs if p and t)
    fp = sum(1 for p, t in pairs if p and not t)
    fn = sum(1 for p, t in pairs if not p and t)
    tn = sum(1 for p, t in pairs if not p and not t)
    n = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "n": n,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": round((tp + tn) / n, 4) if n else None,
        "negated_precision": round(precision, 4),
        "negated_recall": round(recall, 4),
        "negated_f1": round(f1, 4),
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("data/negex/Annotations-1-120.txt"))
    parser.add_argument("--window", type=int, default=WINDOW_TOKENS)
    parser.add_argument("--limit", type=int, default=0, help="0 means all rows")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    rows = load_gold(args.gold)
    if args.limit:
        rows = rows[: args.limit]
    cues = context_literals()

    arms: dict[str, list[tuple[bool, bool]]] = {
        "majority_always_affirmed": [],
        "dependency_parse": [],
        "window_cue": [],
        "negspacy": [],
        "ctx_a_pyrush": [],
        "ctx_b_our_boundaries": [],
    }
    unqualified = Counter[str]()
    errors: list[dict[str, object]] = []

    for row in rows:
        truth = row.negated
        arms["majority_always_affirmed"].append((False, truth))
        arms["window_cue"].append(
            (window_predicts_negated(row.sentence, row.span, cues, args.window), truth)
        )
        arms["negspacy"].append((negspacy_predicts_negated(row.sentence, row.span), truth))
        arms["dependency_parse"].append(
            (dependency_predicts_negated(row.sentence, row.span), truth)
        )

        index_a = qualify(row.sentence, (row.span,))
        pred_a = "negated" in index_a.attributes_for(row.span)
        if not index_a.is_qualified(row.span):
            unqualified["ctx_a_pyrush"] += 1
        arms["ctx_a_pyrush"].append((pred_a, truth))

        doc = Document.from_text(row.sentence, uid=row.report or "row")
        bounds = tuple(s.span.start for s in doc.sentences)
        index_b = qualify(row.sentence, (row.span,), boundaries=bounds)
        pred_b = "negated" in index_b.attributes_for(row.span)
        if not index_b.is_qualified(row.span):
            unqualified["ctx_b_our_boundaries"] += 1
        arms["ctx_b_our_boundaries"].append((pred_b, truth))

        if pred_a != truth and len(errors) < 40:
            # Concept and report id only. The sentence stays in data/, and the
            # concept is truncated because the gold's `Concept` field sometimes
            # holds a whole report line rather than a term — which would put
            # unlicensed note text in a committed artifact.
            errors.append(
                {
                    "report": row.report,
                    "concept": row.concept[:CONCEPT_CHARS]
                    + ("…" if len(row.concept) > CONCEPT_CHARS else ""),
                    "gold": "negated" if truth else "affirmed",
                    "ctx_a": "negated" if pred_a else "affirmed",
                    "ctx_b": "negated" if pred_b else "affirmed",
                }
            )

    results = {name: score(pairs) for name, pairs in sorted(arms.items())}
    for name, result in results.items():
        result["unqualified_spans"] = unqualified.get(name, 0)

    best = max(results.items(), key=lambda kv: kv[1]["negated_f1"])
    payload = {
        "question": "Is the assertion stage right, not merely stable?",
        "why": (
            "assertion_stability.json gates stage 8 on invariance under "
            "meaning-preserving perturbation. A contextualizer that marked "
            "everything affirmed would score a perfect 0.0000 flip rate on that "
            "gate while being wrong on every negation. This is the correctness "
            "measurement that gate cannot give."
        ),
        "gold": {
            "corpus": "NegEx test set (Chapman et al.), Annotations-1-120.txt",
            "licence": "none upstream; handled like MIMIC, see data/negex/manifest.json",
            "rows_scored": len(rows),
            "negated_prevalence": round(sum(1 for r in rows if r.negated) / len(rows), 4)
            if rows
            else None,
        },
        "arms": results,
        "window_tokens": args.window,
        "headline_metric": "negated_f1",
        "why_not_accuracy": (
            "negation is rare, so always-affirmed already scores about 0.79 "
            "accuracy while getting every negation wrong. Accuracy cannot "
            "separate a working contextualizer from a broken one on this gold; "
            "negated-class F1 can."
        ),
        "best_arm": best[0],
        "ctx_b_minus_ctx_a_f1": round(
            results["ctx_b_our_boundaries"]["negated_f1"] - results["ctx_a_pyrush"]["negated_f1"], 4
        ),
        "ctx_b_is_not_testable_here": (
            "**This gold cannot separate the two CTX arms, and the tie is "
            "structural rather than a result.** Every row is a single sentence "
            "with the concept inside it, so there is no second sentence for a "
            "cue to leak into and both segmenters return the same one boundary. "
            "The segmentation question needs multi-sentence text, which is what "
            "`assertion_deid_invariance.json` measures on the synthetic fixtures "
            "this package owns. Reporting the delta as 0.0000 evidence that our "
            "boundaries do not help would be a misreading: the instrument has no "
            "power here."
        ),
        "how_to_read": (
            "read the arms as a ladder, and read precision against recall "
            "rather than F1 alone. (1) The window arm reaches high recall at "
            "poor precision: *spotting* a cue is easy, *scoping* it is the hard "
            "part, and that gap is what ConText's scope resolution buys. (2) "
            "The dependency arm inverts it — high precision, low recall — "
            "because English marks `no X` as a determiner and carries `denies "
            "X` in the verb, which no parse relation exposes. That is why this "
            "field built cue-based systems rather than using parsers, and it is "
            "measured here rather than asserted. (3) negspacy landing beside "
            "medspaCy separates *the published algorithm works* from *this "
            "implementation of it works*; no configuration of our own component "
            "could distinguish those. (4) The window arm's accuracy falls below "
            "the always-affirmed baseline while its F1 is far above it, which "
            "is the clearest demonstration available that accuracy is the wrong "
            "headline on this gold."
        ),
        "independent_implementation_check": (
            "negspacy is a separate codebase implementing the same published "
            "algorithm. Agreement between it and medspaCy is evidence about "
            "Chapman's method; disagreement would have been evidence about one "
            "implementation. This is the arm that makes the reuse argument in "
            "concepts/context.py checkable rather than merely stated."
        ),
        "why_ship_context_when_negspacy_scores_higher": (
            "negspacy wins this benchmark on negation, by roughly one F1 point, "
            "and matches the shipped arm on the invariance test. It is "
            "nonetheless not the component to ship, for a reason this benchmark "
            "is structurally unable to show: **negspacy detects negation and "
            "nothing else**. medspaCy ConText returns five dimensions, and the "
            "package needs temporality and experiencer for phenotype reporting "
            "(30.1% of gold evidence is non-affirmed, of which negation is only "
            "17.8 points) and needs cue spans and scope spans to give the "
            "SEMANTIC operator channel a dose denominator. Choosing the "
            "single-dimension winner would trade four dimensions and the whole "
            "operator channel for one F1 point on one of them. The number is "
            "reported rather than buried because it is the honest cost of that "
            "choice, and because a future version that needs only negation "
            "should know which component to reach for."
        ),
        "ctx_a_errors_sample": errors,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
