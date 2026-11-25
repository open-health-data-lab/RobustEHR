"""Validation against the SNOMED CT Entity Linking Challenge.

272 MIMIC-IV discharge notes, 75,491 expert annotations of 6,595 concepts, six
clinical annotators with ~70% double annotation. The same corpus family as the
development notes, which is why it is the primary anchor: it tests the tagger on
the text it will actually run on rather than on abstracts.

**What is being measured is not NER.** The package's claim is narrower and more
checkable: *when we say an edit landed on a medication, it landed on a
medication*. So the gating metric is **targeting precision** — of the units a
target selected, what fraction overlap a gold span of the crosswalked category —
and recall is reported for completeness rather than as a gate.

The asymmetry is deliberate and belongs in the methods. Missing a mention only
means fewer were corrupted than possible, which the dose accounting already
reports as achieved versus requested. A *false* mention means the corruption did
not land where the results claim, and every downstream conclusion inherits that.

**The crosswalk goes through UMLS, not through SNOMED's hierarchy.** The
annotations carry SNOMED concept identifiers; categories here are sets of UMLS
semantic types. Mapping ``concept_id -> CUI -> TUI -> category`` through
``MRCONSO`` reuses the terminology already installed rather than requiring a
SNOMED hierarchy traversal, and it maps 100% of the 6,595 annotated concepts.
"""

from __future__ import annotations

import csv
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from robustehr.categories import categories_of, default_tuis
from robustehr.dose import ratio
from robustehr.types import Span

DEFAULT_ROOT = Path("data/snomed_el")

#: Cached ``SNOMED code -> semantic types`` map. Derived from licensed UMLS
#: content, so it is written beside the corpus and gitignored rather than
#: shipped; the builder is what travels.
CROSSWALK = "concept_tui.json"

#: Annotation splits. ``proposed_ACCEPTED`` are annotator-proposed spans that
#: survived adjudication, so they are gold and are kept with the training split.
TEST_SPLIT = "test"


@dataclass(frozen=True, slots=True)
class GoldSpan:
    note_id: str
    span: Span
    surface: str
    """The annotation's own rendering of the span.

    **Not byte-identical to the note.** Where a mention crosses a hard-wrap
    boundary the annotation normalizes the newline to a space, so
    ``text[start:end]`` may contain ``\n`` where this reads ``' '``. The offsets
    are authoritative; this is for display. Fittingly for this package, the
    discrepancy is caused by exactly the wrapping the RENDER channel perturbs.
    """
    concept_id: str
    tuis: frozenset[str]
    split: str

    @property
    def categories(self) -> frozenset[str]:
        return categories_of(self.tuis)


@dataclass(frozen=True, slots=True)
class GoldCorpus:
    notes: dict[str, str]
    spans: tuple[GoldSpan, ...]
    _by_note: dict[str, tuple[GoldSpan, ...]] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        # Grouped once. A linear scan per note is 272 x 75,491 comparisons on
        # the full corpus, which dominated the evaluation before this.
        grouped: dict[str, list[GoldSpan]] = {}
        for span in self.spans:
            grouped.setdefault(span.note_id, []).append(span)
        object.__setattr__(self, "_by_note", {k: tuple(v) for k, v in grouped.items()})

    def for_note(self, note_id: str) -> tuple[GoldSpan, ...]:
        return self._by_note.get(note_id, ())

    def split(self, name: str) -> GoldCorpus:
        """Restrict to one annotation split — **both spans and notes**.

        Keeping every note while filtering only the spans is wrong and was a bug
        here: a system then predicts over 272 notes of text while only 68 carry
        gold, so every mention in the other 204 counts as a false positive and
        the score collapses. The challenge partitions by note (204 train, 68
        test), and evaluation has to follow it.
        """
        keep = tuple(s for s in self.spans if s.split == name)
        note_ids = {s.note_id for s in keep}
        return GoldCorpus(
            notes={k: v for k, v in self.notes.items() if k in note_ids},
            spans=keep,
        )

    def with_category(self, category: str) -> tuple[GoldSpan, ...]:
        return tuple(s for s in self.spans if category in s.categories)

    def offsets_agree(self) -> tuple[GoldSpan, ...]:
        """Spans whose text disagrees with the annotation's rendering.

        Expected to be only wrap-crossing mentions; anything else would mean
        the corpus and the annotations are out of step.
        """
        out = []
        for span in self.spans:
            actual = self.notes[span.note_id][span.span.start : span.span.end]
            if " ".join(actual.split()) != " ".join(span.surface.split()):
                out.append(span)
        return tuple(out)


def build_crosswalk(
    root: Path = DEFAULT_ROOT, umls: Path = Path("data/umls")
) -> dict[str, list[str]]:
    """Map every annotated SNOMED concept to its UMLS semantic types.

    Runs once and caches. Requires DuckDB and a local UMLS release; the cached
    artifact is what the evaluation actually reads.
    """
    import duckdb

    from robustehr.concepts.umls import MRCONSO_COLUMNS, MRSTY_COLUMNS, UmlsRelease

    release = UmlsRelease.discover(umls)
    con = duckdb.connect(":memory:")
    con.execute(f"""
        CREATE TABLE code_tui AS
        SELECT DISTINCT c.code, s.tui
        FROM read_csv('{release.rrf("MRCONSO.RRF")}', delim='|', header=false, quote='',
                      names={MRCONSO_COLUMNS!r}, all_varchar=true) c
        JOIN read_csv('{release.rrf("MRSTY.RRF")}', delim='|', header=false, quote='',
                      names={MRSTY_COLUMNS!r}, all_varchar=true) s ON s.cui = c.cui
        WHERE c.sab = 'SNOMEDCT_US'
    """)
    rows = con.execute("SELECT code, list(tui) FROM code_tui GROUP BY code").fetchall()
    mapping = {str(code): sorted(str(t) for t in tuis) for code, tuis in rows}
    (root / CROSSWALK).write_text(json.dumps(mapping, sort_keys=True), encoding="utf-8")
    return mapping


def load_crosswalk(root: Path = DEFAULT_ROOT) -> dict[str, list[str]]:
    path = root / CROSSWALK
    if not path.exists():
        raise FileNotFoundError(
            f"no crosswalk at {path}. Build it with `robustehr eval crosswalk`, "
            "which needs a local UMLS release."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load(root: Path = DEFAULT_ROOT, *, limit: int | None = None) -> GoldCorpus:
    """Read the challenge notes and annotations."""
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    crosswalk = load_crosswalk(root)

    with (root / "train_notes.csv").open(encoding="utf-8", newline="") as handle:
        notes = {row["note_id"]: row["text"] for row in csv.DictReader(handle)}
    if limit is not None:
        notes = dict(sorted(notes.items())[:limit])

    spans = []
    with (root / "train_annotations.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            note_id = row["note_id"]
            if note_id not in notes:
                continue
            spans.append(
                GoldSpan(
                    note_id=note_id,
                    span=Span(int(float(row["start"])), int(float(row["end"]))),
                    surface=row["span"],
                    concept_id=row["concept_id"],
                    tuis=frozenset(crosswalk.get(row["concept_id"], ())),
                    split=row["annotation_type"],
                )
            )
    spans.sort(key=lambda s: (s.note_id, s.span.start, s.span.end, s.concept_id))
    return GoldCorpus(notes=notes, spans=tuple(spans))


@dataclass(frozen=True, slots=True)
class CategoryScore:
    """Targeting precision and recall for one category at one ablation rung."""

    category: str
    rung: str
    selected: int
    """Units the target selected."""
    hits: int
    """Selected units overlapping a gold span of this category."""
    gold: int
    """Gold spans of this category in the evaluated notes."""
    gold_covered: int
    """Gold spans overlapped by at least one selected unit."""

    @property
    def precision(self) -> float | None:
        value = ratio(self.hits, self.selected)
        return None if value is None else float(value)

    @property
    def recall(self) -> float | None:
        value = ratio(self.gold_covered, self.gold)
        return None if value is None else float(value)

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if not p or not r:
            return None
        return 2 * p * r / (p + r)

    def to_row(self) -> dict[str, Any]:
        def pct(v: float | None) -> float | None:
            return None if v is None else round(v, 4)

        return {
            "category": self.category,
            "rung": self.rung,
            "selected": self.selected,
            "hits": self.hits,
            "gold": self.gold,
            "gold_covered": self.gold_covered,
            "targeting_precision": pct(self.precision),
            "recall": pct(self.recall),
            "f1": pct(self.f1),
        }


def score(
    selected: Iterable[Span],
    gold: Iterable[GoldSpan],
    category: str,
    rung: str,
) -> CategoryScore:
    """Targeting precision and recall for one category over one note set.

    Overlap rather than exact boundary match, because the unit a target selects
    is a token while a gold span is a mention: requiring identical boundaries
    would score a correct token selection inside ``chest pain`` as a miss.
    """
    selected = list(selected)
    if category == "clinical_any":
        # Any gold span the default union would count, which is every annotated
        # concept carrying a default semantic type.
        relevant = [g for g in gold if g.tuis & default_tuis()]
    else:
        relevant = [g for g in gold if category in g.categories]
    # Mark covered characters once rather than comparing every selection against
    # every gold span: the nested form is O(selected x gold) per note and both
    # run to thousands.
    marked: set[int] = set()
    for span in relevant:
        marked.update(range(span.span.start, span.span.end))
    hits = sum(1 for s in selected if any(i in marked for i in range(s.start, s.end)))

    chosen: set[int] = set()
    for s in selected:
        chosen.update(range(s.start, s.end))
    covered = sum(1 for g in relevant if any(i in chosen for i in range(g.span.start, g.span.end)))
    return CategoryScore(
        category=category,
        rung=rung,
        selected=len(selected),
        hits=hits,
        gold=len(relevant),
        gold_covered=covered,
    )


__all__ = [
    "CROSSWALK",
    "DEFAULT_ROOT",
    "TEST_SPLIT",
    "CategoryScore",
    "GoldCorpus",
    "GoldSpan",
    "build_crosswalk",
    "load",
    "load_crosswalk",
    "score",
]
