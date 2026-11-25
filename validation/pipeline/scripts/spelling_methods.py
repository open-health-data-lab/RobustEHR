#!/usr/bin/env python
"""Two questions about spelling: is our detector sound, and which corrector wins?

**Question 1 — is the misspelling estimator validated?** It was not. The Document
Quality Profile calls a token a suspected misspelling when it is unrecognized,
alphabetic, at least four characters, and occurs once in the whole corpus. That
is a reasonable heuristic and it had never been checked against a case where the
truth is known.

It can be, because the estimator and ``input.typo`` are **dual**: one injects
misspellings at measured dose, the other estimates how many are present. So
injecting a known number and asking what the estimator reports is an
injection-recovery experiment, and the release gate for those is already
specified — slope in [0.90, 1.10], R² > 0.90.

**Question 2 — which correction method?** Correcting clinical text with a general
dictionary is worse than not correcting it, because every clinical term becomes a
correction target. The variants below differ along the axes that actually matter
here — how far to search, what to rank by, and *which dictionary* — and the last
is the one specific to this domain.

Ground truth is exact: the operator knows what each word was before it corrupted
it, so a corrector's answer is right or wrong with no adjudication.

Both questions are answered offline, from lists this package already ships. No
network, no additional dependency, and the comparison is therefore reproducible
by anyone who can build the lexicon.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import warnings
from pathlib import Path

from robustehr.corpus import read_documents
from robustehr.document import Document
from robustehr.lexical import english_vocabulary
from robustehr.lexicon import DEFAULT_LEXICON, Lexicon, load_clinical_lexicon
from robustehr.metrics.dqp import corpus_frequencies, profile
from robustehr.ops import registry
from robustehr.runner import apply_operator, severity_ladder

_WORD = re.compile(r"[A-Za-z]+")
LETTERS = "abcdefghijklmnopqrstuvwxyz"

#: Severities for the injection-recovery arm, as quoted literals.
DOSES = ("0", "0.01", "0.02", "0.05", "0.10")


def edits1(word: str) -> set[str]:
    """Every string one edit from ``word`` — the Norvig candidate set."""
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    out = {left + right[1:] for left, right in splits if right}
    out |= {left + right[1] + right[0] + right[2:] for left, right in splits if len(right) > 1}
    out |= {left + c + right[1:] for left, right in splits if right for c in LETTERS}
    out |= {left + c + right for left, right in splits for c in LETTERS}
    return out


class Corrector:
    """One correction policy: a dictionary, a search radius, and a ranking."""

    def __init__(
        self,
        name: str,
        vocabulary: frozenset[str],
        frequencies: dict[str, int] | None,
        radius: int,
    ) -> None:
        self.name = name
        self.vocabulary = vocabulary
        self.frequencies = frequencies
        self.radius = radius

    def correct(self, word: str) -> str | None:
        """The best in-vocabulary candidate, or ``None`` to abstain.

        Abstention is a first-class answer. A corrector that always guesses turns
        every unrecognized clinical term into a wrong word, which is worse than
        leaving it alone.
        """
        if word in self.vocabulary:
            return word
        candidates = {c for c in edits1(word) if c in self.vocabulary}
        if not candidates and self.radius > 1:
            for near in edits1(word):
                candidates |= {c for c in edits1(near) if c in self.vocabulary}
        if not candidates:
            return None
        if self.frequencies is None:
            # No ranking signal: abstain on ties rather than break them
            # alphabetically, which is the failure the matcher's CUI tiebreak
            # already demonstrated.
            return next(iter(candidates)) if len(candidates) == 1 else None
        return max(sorted(candidates), key=lambda c: self.frequencies.get(c, 0))


def build_correctors(lexicon: Lexicon, frequencies: dict[str, int]) -> list[Corrector]:
    english = english_vocabulary()
    clinical = frozenset(lexicon.clinical) | frozenset(lexicon.ambiguous)
    both = english | clinical
    return [
        Corrector("english only, edit-1", english, frequencies, 1),
        Corrector("english + clinical, edit-1", both, frequencies, 1),
        Corrector("english + clinical, edit-1, no ranking", both, None, 1),
        Corrector("english + clinical, edit-2", both, frequencies, 2),
    ]


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - one block per arm
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--lexicon", type=Path, default=Path("data/lexicon/clinical_tokens.txt"))
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    lexicon = load_clinical_lexicon(args.lexicon) if args.lexicon.exists() else DEFAULT_LEXICON
    docs = list(read_documents(args.corpus, limit=args.limit))
    frequencies = corpus_frequencies(docs, lexicon)
    registry.register_builtins()
    operator = registry.get("input.typo")()

    # -- arm 1: does the estimator recover an injected dose? -----------------
    recovery = []
    for literal in DOSES:
        severity = severity_ladder(literal)[0]
        injected = detected = 0
        for doc in docs:
            result = apply_operator(doc, operator, operator.meta, severity)
            injected += result.dose.applied_n
            perturbed = Document.from_text(result.text, uid=doc.uid)
            found = profile(perturbed, lexicon, frequencies)
            detected += found.suspected_misspellings or 0
        recovery.append({"severity": literal, "injected": injected, "detected": detected})
    base = recovery[0]["detected"]
    xs = [r["injected"] for r in recovery]
    ys = [r["detected"] - base for r in recovery]
    slope = statistics.linear_regression(xs, ys, proportional=True).slope
    mean_y = sum(ys) / len(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - slope * x) ** 2 for x, y in zip(xs, ys, strict=True))
    r2 = 1 - ss_res / ss_tot if ss_tot else None

    # -- arm 2: which corrector recovers the original word? ------------------
    correctors = build_correctors(lexicon, dict(frequencies))
    truth: list[tuple[str, str]] = []
    severity = severity_ladder("0.10")[0]
    for doc in docs:
        result = apply_operator(doc, operator, operator.meta, severity)
        for edit in result.apply_result.applied:
            before = edit.span.surface(doc.text)
            after = edit.replacement
            if _WORD.fullmatch(before) and _WORD.fullmatch(after) and before != after:
                truth.append((after.lower(), before.lower()))

    scores = []
    for corrector in correctors:
        right = wrong = abstained = 0
        for corrupted, original in truth:
            answer = corrector.correct(corrupted)
            if answer is None:
                abstained += 1
            elif answer == original:
                right += 1
            else:
                wrong += 1
        answered = right + wrong
        scores.append(
            {
                "method": corrector.name,
                "vocabulary": len(corrector.vocabulary),
                "answered": answered,
                "correct": right,
                "wrong": wrong,
                "abstained": abstained,
                "coverage": round(answered / len(truth), 4) if truth else None,
                "accuracy": round(right / answered, 4) if answered else None,
                "recovery": round(right / len(truth), 4) if truth else None,
            }
        )
    scores.sort(key=lambda s: -(s["recovery"] or 0))

    payload = {
        "detector_validation": {
            "question": ("Does the DQP misspelling estimator recover a known injected dose?"),
            "method": (
                "input.typo and the estimator are dual — one injects at measured "
                "dose, the other estimates. Injecting a known number and reading "
                "the estimate is the injection-recovery design the release gates "
                "already specify."
            ),
            "estimator": (
                "unrecognized AND alphabetic AND >= 4 characters AND corpus frequency <= 1"
            ),
            "baseline_detected_before_injection": base,
            "rungs": recovery,
            "slope": round(slope, 4),
            "r_squared": round(r2, 4) if r2 is not None else None,
            "gate": "slope in [0.90, 1.10], r_squared > 0.90",
            "passes": bool(0.90 <= slope <= 1.10 and (r2 or 0) > 0.90),
        },
        "corrector_comparison": {
            "question": "Which correction policy recovers the original word most often?",
            "ground_truth": (
                "exact: the operator knows what each word was before it corrupted "
                "it, so an answer is right or wrong with no adjudication."
            ),
            "corrupted_words": len(truth),
            "why_abstention_counts": (
                "a corrector that always guesses turns every unrecognized clinical "
                "term into a wrong word, which is worse than leaving it alone. "
                "recovery = correct / all corrupted words is therefore the metric "
                "that ranks them, not accuracy among those answered."
            ),
            "methods": scores,
        },
        "notes": len(docs),
        "lexicon_source": lexicon.source,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
