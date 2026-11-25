"""What does running without a terminology cost?

RobustEHR classifies tokens as clinical using a UMLS-derived vocabulary, and
falls back to a morphological heuristic when no terminology is installed. The
fallback is not offered as an equivalent — it is offered as a degraded mode whose
degradation is *measured*, by this module, and reported alongside any result that
depended on it.

The measurement is an agreement study, not an accuracy study, and the difference
matters for how it is written up. UMLS is treated as the reference standard
because it is the field's reference standard, but it is not truth: a token the
heuristic calls clinical and UMLS does not may be a genuine miss by the
heuristic, or a misspelling in the corpus, or a term the terminology lacks. The
run therefore reports disagreement *examples* and not only rates, because the
direction of the errors is the interesting part.

Two rates carry most of the meaning:

* **Type-level recall** — of the word types UMLS calls clinical, what fraction
  does the heuristic find? This is low, and unavoidably so: most clinical words
  carry no diagnostic morphology.
* **Token-level coverage** — of the running tokens in a corpus, what fraction
  does each method classify as clinical? This is what actually determines how
  many of an operator's edits get attributed to clinical content, so it is the
  number that propagates into results.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction

from robustehr.document import Document
from robustehr.dose import ratio
from robustehr.lexicon import Lexicon, clinical_by_morphology, load_morphology
from robustehr.segment.tokens import TokenKind

#: How many disagreeing word types to keep as examples. The examples are the
#: point — a bare F1 says the heuristic is bad, the examples say *how*.
EXAMPLE_LIMIT = 20

#: Minimum corpus frequency for a word type to appear as an example.
#:
#: The report is meant to be publishable next to a result, which means it leaves
#: the machine that holds the corpus. Aggregate vocabulary statistics are not
#: note text and are reported in every corpus paper, but a word type occurring
#: *once* is not really an aggregate — it could be an identifier that survived
#: de-identification, and there is no way to inspect thousands of them by hand.
#: Requiring a type to recur before it can be quoted costs nothing (the useful
#: examples are all frequent) and removes the question entirely.
MIN_EXAMPLE_FREQUENCY = 5


@dataclass(frozen=True, slots=True)
class AgreementReport:
    """Morphological fallback measured against the UMLS-derived vocabulary."""

    reference: str
    """Which terminology was the reference, e.g. ``umls-2026AA``."""
    n_types: int
    """Word types compared."""
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int

    tokens_total: int = 0
    tokens_clinical_reference: int = 0
    tokens_clinical_fallback: int = 0

    false_positive_examples: tuple[str, ...] = ()
    """Types the heuristic calls clinical and the terminology does not.

    Read these before quoting the precision: a corpus misspelling of a clinical
    word lands here, and the heuristic arguably got it right. Filtered to types
    occurring at least ``MIN_EXAMPLE_FREQUENCY`` times, so these are a sample of
    the disagreements rather than all of them — the counts above are complete.
    """
    false_negative_examples: tuple[tuple[str, int]] | tuple[tuple[str, int], ...] = ()
    """Missed types with corpus frequency, most frequent first."""

    resource_digests: dict[str, str] = field(default_factory=dict)

    @property
    def precision(self) -> Fraction | None:
        return ratio(self.true_positive, self.true_positive + self.false_positive)

    @property
    def recall(self) -> Fraction | None:
        return ratio(self.true_positive, self.true_positive + self.false_negative)

    @property
    def f1(self) -> Fraction | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)

    @property
    def reference_token_coverage(self) -> Fraction | None:
        """Share of running tokens the terminology calls clinical."""
        return ratio(self.tokens_clinical_reference, self.tokens_total)

    @property
    def fallback_token_coverage(self) -> Fraction | None:
        return ratio(self.tokens_clinical_fallback, self.tokens_total)

    def to_dict(self) -> dict[str, object]:
        def pct(value: Fraction | None) -> float | None:
            return None if value is None else round(float(value), 4)

        return {
            "reference": self.reference,
            "n_types": self.n_types,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "true_negative": self.true_negative,
            "precision": pct(self.precision),
            "recall": pct(self.recall),
            "f1": pct(self.f1),
            "tokens_total": self.tokens_total,
            "reference_token_coverage": pct(self.reference_token_coverage),
            "fallback_token_coverage": pct(self.fallback_token_coverage),
            "false_positive_examples": list(self.false_positive_examples),
            "false_negative_examples": [
                {"token": token, "corpus_n": n} for token, n in self.false_negative_examples
            ],
            "resource_digests": dict(sorted(self.resource_digests.items())),
        }


def measure_fallback(
    documents: list[Document],
    reference: Lexicon,
) -> AgreementReport:
    """Measure the morphological fallback against a terminology-backed lexicon.

    Restricted to alphabetic content tokens outside the closed class, because
    those are the only tokens either method makes a claim about — including
    numbers, placeholders and function words would inflate agreement with cases
    neither method decides.
    """
    if not reference.has_vocabulary:
        raise ValueError(
            "measure_fallback needs a terminology-backed reference lexicon; "
            "build one with `robustehr concepts build-lexicon`"
        )

    closed = load_morphology().closed_class
    frequency: Counter[str] = Counter()
    for doc in documents:
        for token in doc.tokens:
            if token.kind is not TokenKind.WORD or not token.is_content:
                continue
            word = token.lower
            if not word.isalpha() or word in closed:
                continue
            frequency[word] += 1

    tp = fp = fn = tn = 0
    tokens_reference = tokens_fallback = 0
    false_positives: list[str] = []
    false_negatives: list[tuple[str, int]] = []

    for word, count in frequency.items():
        in_reference = word in reference.clinical
        by_morphology = clinical_by_morphology(word)
        tokens_reference += count if in_reference else 0
        tokens_fallback += count if by_morphology else 0
        if in_reference and by_morphology:
            tp += 1
        elif by_morphology:
            fp += 1
            if count >= MIN_EXAMPLE_FREQUENCY:
                false_positives.append(word)
        elif in_reference:
            fn += 1
            if count >= MIN_EXAMPLE_FREQUENCY:
                false_negatives.append((word, count))
        else:
            tn += 1

    false_negatives.sort(key=lambda item: (-item[1], item[0]))
    return AgreementReport(
        reference=reference.source,
        n_types=len(frequency),
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
        tokens_total=sum(frequency.values()),
        tokens_clinical_reference=tokens_reference,
        tokens_clinical_fallback=tokens_fallback,
        false_positive_examples=tuple(sorted(false_positives)[:EXAMPLE_LIMIT]),
        false_negative_examples=tuple(false_negatives[:EXAMPLE_LIMIT]),
    )


__all__ = [
    "EXAMPLE_LIMIT",
    "MIN_EXAMPLE_FREQUENCY",
    "AgreementReport",
    "measure_fallback",
]
