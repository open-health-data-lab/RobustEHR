"""Does a targeting rule actually select clinical content? Measured, not asserted.

Experiment 2 corrupts "clinical concepts". Restricting to UMLS mentions was
assumed to deliver that and does not: measured on the corrupted corpora, only
~25% of the edit budget landed on unambiguously clinical tokens, ~14% on plain
English (`she`, `you`, `please`), and 43% of every note's characters fell inside
some mention. A rule that admits 43% of a discharge summary is not a
concept-targeted rule.

This scores candidate rules against an **external, adjudicated** benchmark: the
SNOMED CT Entity Linking Challenge annotations over 272 MIMIC-IV discharge
summaries (75,491 spans). Gold is "a human annotator marked this character as
part of a clinical concept", so precision and recall here mean what they say,
rather than agreement with the tagger that produced the problem.

Why token level rather than span level: corruption is dosed on characters and
words inside a mention, so what matters is whether *the token we would corrupt*
is clinical — not whether some enclosing span was. The two differ sharply,
because gold spans carry function words along with them (`of`, `no`, `to` all
appear inside hundreds of gold spans without being clinical themselves).

    python validation/pipeline/scripts/validate_clinical_targeting.py
    python validation/pipeline/scripts/validate_clinical_targeting.py --limit 60      # quick pass

`validation/methodology/05-semantic-categories.md` records the conclusion this produces;
`validation/measurements/clinical_targeting.json` is the machine-readable result.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
WORD = re.compile(r"[A-Za-z][A-Za-z\-']*")

#: The T033 question the category YAML leaves open: "Run the validation with and
#: without it and keep whichever the gold standard supports." `finding` is
#: currently excluded from `clinical_any` provisionally, on the evidence that
#: bare `stairs`, `one` and `normal` match at word level.
FINDING_TUI = "T033"


@dataclass(frozen=True, slots=True)
class Score:
    """Token-level agreement with the adjudicated gold."""

    name: str
    tp: int
    fp: int
    fn: int
    selected: int
    tokens: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def coverage(self) -> float:
        """Share of all word tokens the rule would corrupt.

        The number that decides whether "targeted" means anything: a rule at 40%
        coverage is barely distinguishable from corrupting the whole note, however
        good its precision looks.
        """
        return self.selected / self.tokens if self.tokens else 0.0

    def row(self) -> dict[str, object]:
        return {
            "rule": self.name,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "coverage": round(self.coverage, 4),
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


def gold_spans(path: Path) -> dict[str, list[tuple[int, int]]]:
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            spans[row["note_id"]].append((int(float(row["start"])), int(float(row["end"]))))
    return {k: sorted(v) for k, v in spans.items()}


def overlaps(spans: list[tuple[int, int]], starts: list[int], a: int, b: int) -> bool:
    """Does [a,b) touch any span? Spans are sorted; scan back over the longest one."""
    j = bisect.bisect_right(starts, b) - 1
    while j >= 0 and starts[j] >= a - 400:
        s, e = spans[j]
        if s < b and a < e:
            return True
        j -= 1
    return False


def main() -> int:  # noqa: PLR0915 - a linear measurement, one statement per stage
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", type=Path, default=Path("data/snomed_el/train_notes.csv"))
    parser.add_argument(
        "--annotations", type=Path, default=Path("data/snomed_el/train_annotations.csv")
    )
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/clinical_targeting.json")
    )
    args = parser.parse_args()

    from robustehr.categories import categories_of, load_categories
    from robustehr.concepts.annotate import annotate_corpus
    from robustehr.document import Document
    from robustehr.lexical import general_english

    with args.notes.open(newline="", encoding="utf-8") as handle:
        notes = {r["note_id"]: r["text"] for r in csv.DictReader(handle)}
    gold = gold_spans(args.annotations)
    ids = sorted(set(notes) & set(gold))
    if args.limit:
        ids = ids[: args.limit]
    print(f"gold notes: {len(ids)}", flush=True)

    docs = [Document.from_text(notes[i], uid=i) for i in ids]
    mentions = annotate_corpus(docs, args.index, args.cache, workers=args.workers, label="gold")

    cats = load_categories()
    # `in_default` IS the `clinical_any` flag; `finding` is its sole exclusion.
    CLINICAL = {n for n, v in cats.items() if v.in_default}
    WITH_FINDING = CLINICAL | {"finding"}
    ENG = general_english()

    def cats_of(tuis: set[str]) -> set[str]:
        return set(categories_of(frozenset(tuis)))

    def rule_concept(word: str, tuis: set[str]) -> bool:
        return True  # any mention — what exp2 used

    def rule_clinical_any(word: str, tuis: set[str]) -> bool:
        return bool(cats_of(tuis) & CLINICAL)

    def rule_with_finding(word: str, tuis: set[str]) -> bool:
        return bool(cats_of(tuis) & WITH_FINDING)

    def rule_not_english(word: str, tuis: set[str]) -> bool:
        return word.lower() not in ENG

    def rule_clinical_not_english(word: str, tuis: set[str]) -> bool:
        return rule_clinical_any(word, tuis) and rule_not_english(word, tuis)

    def rule_with_finding_not_english(word: str, tuis: set[str]) -> bool:
        return rule_with_finding(word, tuis) and rule_not_english(word, tuis)

    rules: list[tuple[str, Callable[[str, set[str]], bool]]] = [
        ("concept (exp2 as built)", rule_concept),
        ("clinical_any (no finding)", rule_clinical_any),
        ("clinical_any + finding", rule_with_finding),
        ("concept AND not general_english", rule_not_english),
        ("clinical_any AND not general_english", rule_clinical_not_english),
        ("clinical_any+finding AND not general_english", rule_with_finding_not_english),
    ]
    tally = {name: [0, 0, 0, 0] for name, _ in rules}  # tp, fp, fn, selected
    total_tokens = 0

    for uid in ids:
        text = notes[uid]
        spans = gold[uid]
        starts = [s for s, _ in spans]
        index = mentions.get(uid)
        ment = sorted((m.span.start, m.span.end, m) for m in index.mentions) if index else []
        m_starts = [s for s, _, _ in ment]

        for match in WORD.finditer(text):
            a, b = match.span()
            total_tokens += 1
            is_gold = overlaps(spans, starts, a, b)
            # every mention covering this token, unioned
            tuis: set[str] = set()
            hit = False
            j = bisect.bisect_right(m_starts, b) - 1
            while j >= 0 and m_starts[j] >= a - 400:
                s, e, m = ment[j]
                if s < b and a < e:
                    hit = True
                    tuis |= set(m.tuis)
                j -= 1

            for name, fn in rules:
                selected = hit and fn(match.group(), tuis)
                t = tally[name]
                if selected:
                    t[3] += 1
                    t[0 if is_gold else 1] += 1
                elif is_gold:
                    t[2] += 1

    scores = [Score(name, *tally[name][:3], tally[name][3], total_tokens) for name, _ in rules]
    print(f"\nword tokens scored: {total_tokens:,}\n")
    print(f"{'rule':<46} {'prec':>6} {'recall':>7} {'F1':>6} {'coverage':>9}")
    print("-" * 80)
    for s in scores:
        print(f"{s.name:<46} {s.precision:>6.3f} {s.recall:>7.3f} {s.f1:>6.3f} {s.coverage:>8.1%}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "benchmark": "SNOMED CT Entity Linking Challenge (MIMIC-IV discharge summaries)",
                "notes": len(ids),
                "word_tokens": total_tokens,
                "gold_token_rate": round((scores[0].tp + scores[0].fn) / total_tokens, 4),
                "rules": [s.row() for s in scores],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
