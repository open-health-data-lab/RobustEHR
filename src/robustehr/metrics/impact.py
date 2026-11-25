"""Where a corruption landed, in UMLS terms, without re-tagging anything.

**The corpus is tagged once.** A concept annotation costs 2.38 s per note and
dominates every other measurement by a factor of thirty; tagging the clean
corpus plus 36 corrupted copies of it is a five-hour job. But the clean tags and
the edit script together already answer the question that motivates most of it:

    which concepts did this corruption touch, and in what proportion?

An edit carries original offsets, and a mention carries an original span, so the
intersection is a lookup. Nothing has to be re-annotated.

**What this does not answer, and the distinction matters.** A *touched* concept
is not the same as a *lost* one. ``hypertension`` mistyped as ``hypertesion``
may still match at the configured Jaccard threshold; a corruption can also
create a spurious match that was not there before. Measuring recognition
survival genuinely requires re-tagging the corrupted text — which
:mod:`robustehr.concepts.cache` makes affordable and resumable when a particular
condition is worth it.

So this is the cheap, exact half: an upper bound on damage, reported per
category, with the expensive half available on request rather than paid for
everywhere by default.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from robustehr.concepts.matcher import MentionIndex


@dataclass(frozen=True, slots=True)
class ConceptImpact:
    """One note's concept exposure to one condition's edits."""

    note_uid: str
    mentions: int
    touched: int
    by_category: dict[str, int] = field(default_factory=dict)
    touched_by_category: dict[str, int] = field(default_factory=dict)

    @property
    def share_touched(self) -> float | None:
        """``None`` rather than ``0`` when the note carried no mentions at all.

        A note with nothing to hit is not a note the corruption spared, and
        averaging a zero in would understate every corpus containing one.
        """
        if not self.mentions:
            return None
        return self.touched / self.mentions

    def as_row(self) -> dict[str, Any]:
        return {
            "note_uid": self.note_uid,
            "mentions": self.mentions,
            "touched": self.touched,
            "by_category": dict(sorted(self.by_category.items())),
            "touched_by_category": dict(sorted(self.touched_by_category.items())),
        }


def concept_impact(note_uid: str, mentions: MentionIndex, edits: Any) -> ConceptImpact:
    """Which of this note's concepts an edit script overlaps.

    A mention counts once however many edits hit it — the question is whether
    the concept was disturbed, not how many times. Categories overlap by design
    (``dyspnea`` is symptom and finding), so the per-category counts sum past the
    total and are shares of their own category rather than of the whole.
    """
    spans = [e.span for e in edits]
    total: Counter[str] = Counter()
    hit: Counter[str] = Counter()
    touched = 0
    for mention in mentions.mentions:
        categories = mention.categories
        for name in categories:
            total[name] += 1
        if any(mention.span.overlaps(s) for s in spans):
            touched += 1
            for name in categories:
                hit[name] += 1
    return ConceptImpact(
        note_uid=note_uid,
        mentions=len(mentions.mentions),
        touched=touched,
        by_category=dict(total),
        touched_by_category=dict(hit),
    )


def aggregate(impacts: list[ConceptImpact]) -> dict[str, Any]:
    """Corpus-level exposure, per category, with the rate each was hit at.

    ``rate`` is the number that answers "was any category disproportionately
    corrupted": under Experiment 2's stratified sampling these should be close
    to equal, and under Experiment 1's uniform draw they will not be.
    """
    if not impacts:
        return {}
    mentions = sum(i.mentions for i in impacts)
    touched = sum(i.touched for i in impacts)
    total: Counter[str] = Counter()
    hit: Counter[str] = Counter()
    for impact in impacts:
        total.update(impact.by_category)
        hit.update(impact.touched_by_category)
    return {
        "notes": len(impacts),
        "mentions": mentions,
        "touched": touched,
        "share_touched": round(touched / mentions, 4) if mentions else None,
        "by_category": {
            name: {
                "mentions": total[name],
                "touched": hit.get(name, 0),
                "rate": round(hit.get(name, 0) / total[name], 4) if total[name] else None,
            }
            for name in sorted(total)
        },
    }


__all__ = ["ConceptImpact", "aggregate", "concept_impact"]
