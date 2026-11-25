"""The ablation ladder: what each method addition is worth, as a number.

Each rung changes one thing and is measured on the same gold spans, so the value
of an addition is measured rather than argued.

===== ==================================== =========================================
Rung  Method                               Question it answers
===== ==================================== =========================================
L0    word-level lookup                    what does the cheap method cost?
L1    concept matching (QuickUMLS)         does span matching fix bare-token errors?
L1F   L1 with T033 Finding admitted        should the provisional exclusion stand?
===== ==================================== =========================================

L2 (overlap resolution) is not a separate rung here because ``best_match=True``
already applies it inside the matcher; separating it would need a QuickUMLS
configuration change, which forfeits the inherited validation.

**L3 and L4 are measured, but not by this harness and not per category.** They
belong to the assertion layer, whose gold is span-level assertion rather than
category membership, so they are scored on their own instruments:

* **L3** — ConText qualification: negated-class F1 **0.9289** against the NegEx
  test set, 0.0000 majority-class floor (``assertion_accuracy.json``). Its
  effect on the phenotype layer is 30.1% of gold evidence non-affirmed
  (``phenotype_assertion.json``).
* **L4** — our structural boundaries instead of PyRuSH: de-identification
  instability **0.0000 against 0.1429** (``assertion_deid_invariance.json``), and
  a corpus-scale non-affirmed rate of 30.1% against PyRuSH's 34.7% on identical
  spans.

A per-category split of either would need category-stratified assertion gold,
which no available corpus supplies.

**The T033 rung is the one that settles a standing decision.** ``finding`` is
currently excluded from the default on word-level evidence — bare ``stairs``,
``one`` and ``normal`` matched — while QuickUMLS keeps T033 among its 27
defaults, MedMentions among its 21, and the challenge's own ``clinical finding``
hierarchy is largely T033. Running with and without it lets the gold standard
decide instead of the argument.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from robustehr.categories import default_tuis, load_categories, tuis_for
from robustehr.concepts.matcher import ConceptMatcher, MatcherConfig
from robustehr.document import Document
from robustehr.eval.snomed_el import CategoryScore, GoldCorpus, score
from robustehr.lexicon import Lexicon
from robustehr.target import Categories, SemanticTypes, TargetContext
from robustehr.types import Span

#: Categories the challenge can adjudicate. It annotates SNOMED's clinical
#: finding, procedure and body structure hierarchies and carries no medications,
#: which is why `medication` needs n2c2 2018 and is absent here.
EVALUABLE = ("disorder", "disease", "symptom", "finding", "procedure", "anatomy")

#: Pseudo-category for the unnamed default — what a run selects when a target
#: names no category. This is where the T033 question actually lives: `finding`
#: is always reachable by name, and what the exclusion governs is whether T033
#: counts toward this union.
CLINICAL_ANY = "clinical_any"


@dataclass(frozen=True, slots=True)
class Rung:
    name: str
    description: str
    use_concepts: bool
    admit_finding: bool = False


LADDER = (
    Rung("L0", "word-level lookup", use_concepts=False),
    Rung("L1", "concept matching (QuickUMLS)", use_concepts=True),
    Rung("L1F", "concept matching, T033 Finding admitted", use_concepts=True, admit_finding=True),
)


def _target_for(category: str, admit_finding: bool) -> Categories | SemanticTypes:
    """The target under evaluation for this category and rung."""
    if category != CLINICAL_ANY:
        return Categories(category)
    tuis = set(default_tuis())
    if admit_finding:
        tuis |= tuis_for("finding")
    return SemanticTypes(*sorted(tuis))


def _selected_spans(
    doc: Document,
    ctx: TargetContext,
    category: str,
    admit_finding: bool = False,
) -> list[Span]:
    """Content-token spans the target admits."""
    target = _target_for(category, admit_finding)
    return [t.span for t in doc.tokens if t.is_content and target.admits(t.span, ctx)]


def gold_coverage(corpus: GoldCorpus) -> tuple[int, int]:
    """Content tokens inside any gold span, over all content tokens.

    The figure that bounds every absolute number this harness produces. The
    challenge annotates selected concepts rather than every clinical word, so a
    tagger finding real mentions the annotators did not mark is scored as
    imprecise. Absolute precision is therefore a lower bound, and the
    rung-to-rung delta is the interpretable result.
    """
    covered = total = 0
    for note_id, text in corpus.notes.items():
        doc = Document.from_text(text, uid=note_id)
        marked: set[int] = set()
        for span in corpus.for_note(note_id):
            marked.update(range(span.span.start, span.span.end))
        for token in doc.tokens:
            if not token.is_content:
                continue
            total += 1
            if any(i in marked for i in range(token.span.start, token.span.end)):
                covered += 1
    return covered, total


def run(
    corpus: GoldCorpus,
    lexicon: Lexicon,
    *,
    matcher: ConceptMatcher | None = None,
    categories: tuple[str, ...] = (*EVALUABLE, CLINICAL_ANY),
    rungs: tuple[Rung, ...] = LADDER,
) -> list[CategoryScore]:
    """Score every category at every rung over the gold corpus."""
    known = set(load_categories()) | {CLINICAL_ANY}
    categories = tuple(c for c in categories if c in known)
    results: list[CategoryScore] = []
    per_rung: dict[tuple[str, str], list[CategoryScore]] = {}

    for note_id, text in sorted(corpus.notes.items()):
        doc = Document.from_text(text, uid=note_id)
        gold = corpus.for_note(note_id)
        mentions = matcher.annotate(text) if matcher is not None else None
        for rung in rungs:
            if rung.use_concepts and mentions is None:
                continue
            ctx = TargetContext(
                doc=doc,
                lexicon=lexicon,
                mentions=mentions if rung.use_concepts else None,
            )
            for category in categories:
                spans = _selected_spans(doc, ctx, category, rung.admit_finding)
                per_rung.setdefault((rung.name, category), []).append(
                    score(spans, gold, category, rung.name)
                )

    for (rung_name, category), scores in sorted(per_rung.items()):
        results.append(
            CategoryScore(
                category=category,
                rung=rung_name,
                selected=sum(s.selected for s in scores),
                hits=sum(s.hits for s in scores),
                gold=sum(s.gold for s in scores),
                gold_covered=sum(s.gold_covered for s in scores),
            )
        )
    return results


def report(
    results: list[CategoryScore],
    *,
    notes: int,
    config: MatcherConfig,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the measurement artifact, with the deltas made explicit."""
    by_key = {(r.rung, r.category): r for r in results}
    deltas = []
    for category in sorted({r.category for r in results}):
        l0, l1 = by_key.get(("L0", category)), by_key.get(("L1", category))
        if l0 and l1 and l0.precision is not None and l1.precision is not None:
            deltas.append(
                {
                    "category": category,
                    "L0_precision": round(l0.precision, 4),
                    "L1_precision": round(l1.precision, 4),
                    "delta": round(l1.precision - l0.precision, 4),
                    "L0_recall": round(l0.recall or 0.0, 4),
                    "L1_recall": round(l1.recall or 0.0, 4),
                }
            )
    return {
        "benchmark": "SNOMED CT Entity Linking Challenge",
        "notes": notes,
        "caveat": (
            "The gold standard is not exhaustive over clinical content — see "
            "gold_token_coverage. A tagger finding real mentions the annotators "
            "did not mark scores as imprecise, so absolute targeting precision "
            "is a LOWER BOUND and the rung-to-rung delta is what is "
            "interpretable."
        ),
        "matcher": config.canon(),
        "metric": (
            "targeting precision — of the units a category target selected, the "
            "fraction overlapping a gold span of that category. Precision gates; "
            "recall informs."
        ),
        "rungs": [r.to_row() for r in results],
        "L0_to_L1": deltas,
        **(extra or {}),
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = ["EVALUABLE", "LADDER", "Rung", "report", "run", "write_report"]
