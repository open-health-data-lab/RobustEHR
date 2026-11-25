"""What a note *contains*, before anything is injected.

**The gap this closes.** Every measurement this package produced was
corpus-aggregated: not one artifact carried a `note_uid`. A robustness result
that says "30% of medications were corrupted" cannot be read without knowing how
many medications the note had — three or three hundred — and nothing reported
that. `dose.jsonl` records where edits *landed* (`clinical_hits`,
`category_hits`, `evidence_touch`); nothing recorded what was *there*.

**Why this is not part of `baseline`.** `robustehr baseline` needs no
terminology, and that is deliberate: it is what lets a reader without a UMLS
licence reproduce the structural half of the work. Concept counts need an index,
so this follows the precedent `robustehr ambiguity` already set — a
baseline-quality measurement that lives in its own command because it has its
own dependency.

**Three denominators, because a rate needs the right one.** Concepts per note is
not comparable across notes of different lengths, so density is per thousand
content tokens. A phenotype's share is of *concepts*, not of tokens. And the
count of distinct CUIs is reported beside the count of mentions, because a note
naming hypertension nine times has one concept and nine mentions, and an
operator's dose is over mentions while a clinical reader thinks in concepts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from robustehr.concepts.matcher import MentionIndex
    from robustehr.concepts.phenotype import PhenotypeIndex
    from robustehr.document import Document

#: Density is per this many content tokens. A note is a few thousand, so
#: per-thousand keeps the number readable without decimals dominating.
DENSITY_BASE = 1000


@dataclass(frozen=True, slots=True)
class PhenotypeCount:
    """One phenotype's presence in one note."""

    spans: int
    """Evidence mentions — the dose denominator when targeting this phenotype."""
    distinct_cuis: int
    """How many *different* concepts, which is what a clinician would count."""
    affirmed: int | None
    """Evidence the note asserts plainly. ``None`` when stage 8 did not run.

    Null rather than zero: "no affirmed evidence" and "assertion was never
    computed" are different facts, and only the first is a property of the note.
    """
    by_category: dict[str, int] = field(default_factory=dict)
    """Evidence spans by UMLS semantic category.

    What a phenotype's evidence is MADE of, which the span count alone cannot
    say. A hypertension count resting entirely on `medication` is a different
    claim from one resting on `disease` — the first is inferring the condition
    from its treatment — and a reader deciding whether to trust a phenotype
    result has to be able to see which they have.

    Overlapping, like every category breakdown here: one concept may carry
    several semantic types.
    """

    def to_row(self) -> dict[str, Any]:
        return {
            "spans": self.spans,
            "distinct_cuis": self.distinct_cuis,
            "affirmed": self.affirmed,
            "by_category": dict(sorted(self.by_category.items())),
        }


@dataclass(frozen=True, slots=True)
class ConceptProfile:
    """The concept content of one note."""

    note_uid: str
    note_sha256: str
    content_tokens: int
    concepts: int
    distinct_cuis: int
    by_category: dict[str, int]
    by_phenotype: dict[str, PhenotypeCount]
    phenotype_evidence: int
    """Mentions belonging to *any* declared phenotype, deduplicated.

    Not the sum of `by_phenotype`: concept sets overlap, and a mention that is
    evidence for two phenotypes would otherwise be counted twice.
    """
    assertion_counts: dict[str, int]
    concept_tokens: int = 0
    """Content tokens lying inside at least one mention span.

    A different question from `concepts`, and the one a reader means by "what
    fraction of this note is clinical content". `concepts` counts MENTIONS, and
    a mention is a span: `acute on chronic systolic heart failure` is one
    mention over six tokens, while `pain` is one over one. Dividing mentions by
    tokens therefore answers nothing — it can exceed 1 on a note dense in
    single-token concepts and understate a note dense in long ones.
    """
    category_tokens: dict[str, int] = field(default_factory=dict)
    """Content tokens covered by a mention of each category.

    Overlapping, not a partition: a concept may carry several semantic types, so
    these sum to more than `concept_tokens`.
    """
    span_token_lengths: dict[str, int] = field(default_factory=dict)
    """How long the mention spans are, in tokens: `1`, `2`, `3`, `4+`.

    The bridge between the span level and the token level. Without it the two
    counts look contradictory — 3,918 mentions over 12,399 content tokens reads
    as 32% until you know most mentions are one token long.
    """
    assertion_by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    """Assertion attribute -> semantic category -> mentions.

    The cross-tabulation a robustness result needs: "355 negated mentions" does
    not say whether a negation flip would land on a disease or on an anatomical
    site, and those are different corruptions with different downstream costs.
    """

    @property
    def concept_token_share(self) -> float | None:
        """Fraction of content tokens inside a concept mention."""
        if not self.content_tokens:
            return None
        return round(self.concept_tokens / self.content_tokens, 4)

    @property
    def concept_density(self) -> float | None:
        """Concepts per 1,000 content tokens, or ``None`` for an empty note."""
        if not self.content_tokens:
            return None
        return round(DENSITY_BASE * self.concepts / self.content_tokens, 3)

    @property
    def phenotype_share(self) -> float | None:
        """Fraction of this note's concepts belonging to a declared phenotype.

        ``None`` when no phenotype was declared — the run was agnostic, so the
        question was never asked. Zero would claim it was asked and answered.
        """
        if not self.by_phenotype or not self.concepts:
            return None
        return round(self.phenotype_evidence / self.concepts, 4)

    def to_row(self) -> dict[str, Any]:
        return {
            "note_uid": self.note_uid,
            "note_sha256": self.note_sha256,
            "content_tokens": self.content_tokens,
            "concepts": self.concepts,
            "distinct_cuis": self.distinct_cuis,
            "concept_density_per_1k": self.concept_density,
            "by_category": dict(sorted(self.by_category.items())),
            "concept_tokens": self.concept_tokens,
            "concept_token_share": self.concept_token_share,
            "category_tokens": dict(sorted(self.category_tokens.items())),
            "span_token_lengths": dict(sorted(self.span_token_lengths.items())),
            "assertion_by_category": {
                k: dict(sorted(v.items())) for k, v in sorted(self.assertion_by_category.items())
            },
            "by_phenotype": {k: v.to_row() for k, v in sorted(self.by_phenotype.items())},
            "phenotype_evidence": self.phenotype_evidence,
            "phenotype_share": self.phenotype_share,
            "by_assertion": dict(sorted(self.assertion_counts.items())),
        }


def _count_assertions(assertions: dict[Any, frozenset[str]]) -> dict[str, int]:
    """One count per attribute, with `unmodified` for a qualified-but-clean span."""
    counts: Counter[str] = Counter()
    for attributes in assertions.values():
        if attributes:
            for name in attributes:
                counts[name] += 1
        else:
            counts["unmodified"] += 1
    return dict(counts)


def _cross_assertions(
    mentions: MentionIndex, assertions: dict[Any, frozenset[str]]
) -> dict[str, dict[str, int]]:
    """Assertion attribute x semantic category, over mentions.

    Joined on the span, which is the key `ContextIndex.as_map` uses and the same
    span the mention carries, so the two indices align exactly rather than by
    position.

    A mention with no entry is SKIPPED rather than counted as unmodified: the
    assertion stage qualifies a subset, and "not asked" is not "asked and found
    clean". Conflating them would inflate `unmodified` by every span the stage
    never reached.
    """
    crossed: dict[str, Counter[str]] = {}
    for mention in mentions.mentions:
        attributes = assertions.get(mention.span)
        if attributes is None:
            continue
        for name in attributes or ("unmodified",):
            bucket = crossed.setdefault(name, Counter())
            for category in mention.categories:
                bucket[category] += 1
    return {k: dict(v) for k, v in crossed.items()}


def profile_concepts(
    doc: Document,
    mentions: MentionIndex,
    phenotypes: PhenotypeIndex | None = None,
    assertions: dict[Any, frozenset[str]] | None = None,
) -> ConceptProfile:
    """One note's concept content.

    Takes an already-annotated `MentionIndex` rather than a matcher, so a caller
    profiling a corpus builds the matcher once. The previous per-document
    construction in `cli._document_evidence` was a real cost on any corpus worth
    profiling.
    """
    by_category: Counter[str] = Counter()
    cuis: set[str] = set()
    # Character-level coverage masks, one for "any mention" and one per
    # category. A token is covered when any of its characters is, which is the
    # only definition that survives a mention whose span starts mid-token — and
    # QuickUMLS does produce those on hyphenated and slashed forms.
    #
    # Masks rather than an interval search because the cost is linear in matched
    # characters instead of tokens x mentions: on one MIMIC note that is ~9k
    # writes against 6,134 x 780 comparisons.
    covered = bytearray(len(doc.text))
    per_category: dict[str, bytearray] = {}
    for mention in mentions.mentions:
        cuis.add(mention.cui)
        start, end = mention.span.start, mention.span.end
        covered[start:end] = b"\x01" * (end - start)
        for category in mention.categories:
            by_category[category] += 1
            mask = per_category.setdefault(category, bytearray(len(doc.text)))
            mask[start:end] = b"\x01" * (end - start)

    content = [t for t in doc.tokens.tokens if t.is_content]
    concept_tokens = sum(1 for t in content if any(covered[t.span.start : t.span.end]))
    category_tokens = {
        name: sum(1 for t in content if any(mask[t.span.start : t.span.end]))
        for name, mask in sorted(per_category.items())
    }

    by_phenotype: dict[str, PhenotypeCount] = {}
    evidence_spans: set[tuple[int, int]] = set()
    if phenotypes is not None and phenotypes.names:
        for name in sorted(phenotypes.names):
            # `spans()` deduplicates and returns Span, losing the CUI and the
            # assertion. The evidence list is the right source here: a mention
            # that is evidence for two phenotypes must count once per phenotype.
            found = [e for e in phenotypes.evidence if e.phenotype == name]
            qualified = [e for e in found if e.qualified]
            # Categories come from the MENTION, not the evidence record, which
            # carries only the CUI. Joined on the span, the same key everything
            # else in this module joins on.
            spans_to_categories = {
                (m.span.start, m.span.end): m.categories for m in mentions.mentions
            }
            evidence_categories: Counter[str] = Counter()
            for e in found:
                for category in spans_to_categories.get((e.span.start, e.span.end), ()):
                    evidence_categories[category] += 1
            by_phenotype[name] = PhenotypeCount(
                spans=len(found),
                # Anchor-tier evidence carries no CUI; it is evidence, not a concept.
                distinct_cuis=len({e.cui for e in found if e.cui}),
                affirmed=sum(1 for e in qualified if e.affirmed) if qualified else None,
                by_category=dict(evidence_categories),
            )
            evidence_spans |= {(e.span.start, e.span.end) for e in found}

    # How long a mention is, in tokens. Reported because the span count and the
    # token count otherwise look contradictory: 3,918 mentions over 12,399
    # content tokens reads as 32% of the note until you know that most mentions
    # are a single token and that they overlap.
    starts = [t.span.start for t in content]
    span_lengths: Counter[str] = Counter()
    for mention in mentions.mentions:
        n = sum(1 for s in starts if mention.span.start <= s < mention.span.end)
        span_lengths[str(n) if n < 4 else "4+"] += 1

    assertion_counts: dict[str, int] = {}
    assertion_by_category: dict[str, dict[str, int]] = {}
    if assertions:
        assertion_counts = _count_assertions(assertions)
        assertion_by_category = _cross_assertions(mentions, assertions)

    return ConceptProfile(
        note_uid=doc.uid,
        note_sha256=doc.sha256,
        content_tokens=len(content),
        concepts=len(mentions.mentions),
        distinct_cuis=len(cuis),
        by_category=dict(by_category),
        by_phenotype=by_phenotype,
        phenotype_evidence=len(evidence_spans),
        assertion_counts=assertion_counts,
        concept_tokens=concept_tokens,
        category_tokens=category_tokens,
        span_token_lengths=dict(span_lengths),
        assertion_by_category=assertion_by_category,
    )


def summarise(profiles: list[ConceptProfile]) -> dict[str, Any]:
    """Corpus totals and the spread, for the default (non per-note) output.

    Medians rather than means: concept counts are right-skewed — a discharge
    summary carries several times what a progress note does — and a mean would
    describe a note that does not exist.
    """
    if not profiles:
        return {"notes": 0}
    densities = sorted(p.concept_density or 0.0 for p in profiles)
    concepts = sorted(p.concepts for p in profiles)
    categories: Counter[str] = Counter()
    phenotype_totals: Counter[str] = Counter()
    phenotype_notes: Counter[str] = Counter()
    for profile in profiles:
        categories.update(profile.by_category)
        for name, count in profile.by_phenotype.items():
            phenotype_totals[name] += count.spans
            if count.spans:
                phenotype_notes[name] += 1

    middle = len(profiles) // 2
    return {
        "notes": len(profiles),
        "concepts_total": sum(concepts),
        "concepts_median": concepts[middle],
        "concepts_min": concepts[0],
        "concepts_max": concepts[-1],
        "density_median_per_1k": densities[middle],
        "by_category": dict(categories.most_common()),
        "by_phenotype": {
            name: {
                "evidence_spans": phenotype_totals[name],
                "notes_with_any": phenotype_notes[name],
                "share_of_notes": round(phenotype_notes[name] / len(profiles), 4),
            }
            for name in sorted(phenotype_totals)
        },
        "note_on_phenotype_counts": (
            "a phenotype's concept set is only as good as its measured set "
            "recall; see `robustehr taxonomy --phenotypes`. Evidence never "
            "matched is evidence never counted here and never protected in a run."
        ),
    }


__all__ = ["ConceptProfile", "PhenotypeCount", "profile_concepts", "summarise"]
