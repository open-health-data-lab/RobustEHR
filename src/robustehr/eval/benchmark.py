"""Tracking concept-matcher performance across iterations.

Two scores are tracked, because they answer different questions and can move in
opposite directions:

* **challenge** — character IoU macro-averaged by concept, the SNOMED CT Entity
  Linking Challenge's own metric. Comparable to a published leaderboard, and the
  number that says where a general-purpose matcher sits.
* **category** — per-category recall and targeting precision against the same
  gold. What RobustEHR actually needs, since typing a span as a medication does
  not require resolving which medication.

Every entry records the **full configuration** alongside the scores, because a
score without its configuration is not a measurement. That matters more here
than usual: QuickUMLS's published validation is inherited only while its
matching parameters are untouched, so a tuned entry is explicitly marked as
having forfeited it and owing its own evaluation.

History is append-only and committed. The point is not the best number but the
*trajectory* — a change that improves the challenge score while degrading
category recall is a regression for this package however good it looks on a
leaderboard, and only a history makes that visible.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HISTORY = Path("validation/measurements/benchmark_history.json")

#: Published final scores on the challenge's metric, for context in every report.
LEADERBOARD: dict[str, float] = {
    "KIRI (dictionary-based, winner)": 0.4202,
    "SNOBERT (encoder-based)": 0.4194,
    "MITEL-UNIUD (decoder-based)": 0.3777,
    "median of all final submissions": 0.2572,
}

#: Parameters whose modification forfeits QuickUMLS's inherited validation.
#: Changing any of these makes the configuration ours to evaluate, not theirs.
VALIDATION_CRITICAL = ("threshold", "similarity_name", "min_match_length", "overlapping_criteria")

#: QuickUMLS's own default semantic types. Restricting *within* this set yields a
#: subset of the validated output and inherits their evaluation; going outside it
#: yields spans they never scored and does not.
QUICKUMLS_DEFAULT_SEMTYPES = frozenset(
    {
        "T023",
        "T029",
        "T031",
        "T033",
        "T034",
        "T037",
        "T039",
        "T040",
        "T041",
        "T046",
        "T047",
        "T048",
        "T058",
        "T059",
        "T060",
        "T061",
        "T067",
        "T074",
        "T121",
        "T130",
        "T170",
        "T184",
        "T191",
        "T195",
        "T200",
        "T201",
        "T203",
    }
)

DEFAULTS = {
    "threshold": 0.7,
    "similarity_name": "jaccard",
    "min_match_length": 3,
    "overlapping_criteria": "score",
    "window": 5,
}


@dataclass(frozen=True, slots=True)
class Entry:
    """One scored configuration."""

    label: str
    config: dict[str, Any]
    challenge_iou: float | None
    span_iou: float | None
    category_recall: dict[str, float]
    category_precision: dict[str, float]
    notes_scored: int
    gold_spans: int
    recorded: str = ""
    note: str = ""

    @property
    def inherits_quickumls_validation(self) -> bool:
        """Is this configuration still covered by QuickUMLS's published evaluation?

        Two conditions, and the second is asymmetric. Matching parameters must be
        at their defaults, because those change the algorithm. The semantic-type
        filter may be *narrowed* — a post-match filter, so the output stays a
        subset of what was validated — but not *widened*, because that returns
        spans their evaluation never scored.
        """
        if any(self.config.get(k) != DEFAULTS[k] for k in VALIDATION_CRITICAL):
            return False
        semtypes = self.config.get("accepted_semtypes")
        if semtypes in (None, "quickumls_default"):
            return True
        if isinstance(semtypes, (list, set, frozenset)):
            return frozenset(semtypes) <= QUICKUMLS_DEFAULT_SEMTYPES
        # Recorded as a summary string such as "robustehr:36" — the set is not
        # recoverable, so the conservative reading is that it was widened.
        return False

    @property
    def mean_category_recall(self) -> float | None:
        values = [v for v in self.category_recall.values() if v is not None]
        return sum(values) / len(values) if values else None

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["inherits_quickumls_validation"] = self.inherits_quickumls_validation
        row["mean_category_recall"] = (
            round(self.mean_category_recall, 4) if self.mean_category_recall else None
        )
        return row


@dataclass
class History:
    entries: list[Entry] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = HISTORY) -> History:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            entries=[
                Entry(
                    label=e["label"],
                    config=e["config"],
                    challenge_iou=e.get("challenge_iou"),
                    span_iou=e.get("span_iou"),
                    category_recall=e.get("category_recall", {}),
                    category_precision=e.get("category_precision", {}),
                    notes_scored=e.get("notes_scored", 0),
                    gold_spans=e.get("gold_spans", 0),
                    recorded=e.get("recorded", ""),
                    note=e.get("note", ""),
                )
                for e in raw["entries"]
            ]
        )

    def add(self, entry: Entry, *, stamp: str) -> Entry:
        """Append an entry, stamped so the trajectory has an order.

        The stamp is **required and passed in**, never read from the clock here.
        A wall-clock read inside the package would make output depend on when it
        ran, which is the one thing this package cannot allow, and the AST lint
        enforces it.
        """
        stamped = Entry(**{**asdict(entry), "recorded": stamp})
        self.entries.append(stamped)
        return stamped

    def best(self, metric: str = "challenge_iou") -> Entry | None:
        scored = [e for e in self.entries if getattr(e, metric, None) is not None]
        if not scored:
            return None
        return max(scored, key=lambda e: getattr(e, metric))

    def save(self, path: Path = HISTORY) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metric_challenge": (
                "character IoU macro-averaged by concept — the SNOMED CT Entity "
                "Linking Challenge's own metric"
            ),
            "metric_category": (
                "per-category recall and targeting precision against the same "
                "gold spans; recall is the interpretable direction because the "
                "reference covers only ~26% of content tokens"
            ),
            "leaderboard": LEADERBOARD,
            "validation_note": (
                "QuickUMLS's published validation is inherited only while "
                f"{', '.join(VALIDATION_CRITICAL)} are at their defaults. An entry "
                "with inherits_quickumls_validation=false owes its own evaluation."
            ),
            "entries": [e.to_row() for e in self.entries],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def table(self) -> str:
        """A compact trajectory, for a terminal or a commit message."""
        lines = [
            f"  {'label':34} {'challenge':>10} {'span':>7} {'mean recall':>12} {'inherits':>9}",
        ]
        for entry in self.entries:
            challenge = f"{entry.challenge_iou:.4f}" if entry.challenge_iou is not None else "—"
            span = f"{entry.span_iou:.4f}" if entry.span_iou is not None else "—"
            recall = entry.mean_category_recall
            lines.append(
                f"  {entry.label[:34]:34} {challenge:>10} {span:>7} "
                f"{(f'{recall:.4f}' if recall else '—'):>12} "
                f"{'yes' if entry.inherits_quickumls_validation else 'NO':>9}"
            )
        return "\n".join(lines)


__all__ = [
    "DEFAULTS",
    "HISTORY",
    "LEADERBOARD",
    "QUICKUMLS_DEFAULT_SEMTYPES",
    "VALIDATION_CRITICAL",
    "Entry",
    "History",
]
