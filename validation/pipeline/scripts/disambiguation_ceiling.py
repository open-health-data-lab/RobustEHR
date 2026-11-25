#!/usr/bin/env python
"""V0 for stage 3c: is an anchor-vote disambiguator worth building?

The same gate that redirected stage 3 as a whole, applied to its last rung
before that rung is written. The question is not "can context disambiguate" —
obviously it can, sometimes — but **how much is left for it to do once the
cheap baseline has run**.

The cheap baseline is **most-frequent sense**: for each short form, always answer
with the sense it most often has. It needs no context, no cues, no inventory, and
it is the standard floor in every word-sense-disambiguation paper. Fitted on the
challenge's `train` split and reported on `test`, so the number is held out — the
discipline this project demands of KIRI applies to us.

Three quantities decide whether stage 3c is warranted:

* **MFS accuracy** — what you get for free.
* **oracle accuracy** — what a *perfect* disambiguator would get, which is 1.0
  by construction wherever the gold sense is reachable at all.
* **the gap between them** — the entire budget available to anchor voting, cue
  authoring, abstention policy and everything else in the rung.

If the gap is small, the correct engineering decision is to ship most-frequent
sense with abstention on the residue and spend the budget elsewhere — and to say
so in the limitations section rather than in a future-work list.

Scope: **free-prose short forms only.** Anything in a structural slot has already
been settled by position (stage 3a), and anything expanded from the table has
been settled by vocabulary (stage 3b). What is left is the population that
genuinely needs context.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from robustehr.concepts.matcher import ConceptMatcher, MatcherConfig
from robustehr.concepts.structural import slotted_spans
from robustehr.document import Document
from robustehr.eval import snomed_el
from robustehr.lexical import general_english

#: Minimum gold occurrences on `train` for a form to be worth fitting a prior to.
#: Below this the majority sense is an artefact of a handful of annotations.
MIN_TRAIN_OCCURRENCES = 20


def prose_senses(corpus: Any, *, drop_general_english: bool) -> dict[str, Counter[str]]:
    """Gold sense distribution per abbreviation-shaped free-prose surface.

    Structural slots are excluded because position has already resolved them,
    and general-English words because they are not abbreviations — including
    them would inflate both the population and the apparent ambiguity.
    """
    from scripts.abbreviation_ceiling import is_abbreviation_shaped

    english = general_english()
    senses: dict[str, Counter[str]] = defaultdict(Counter)
    for note_id, text in sorted(corpus.notes.items()):
        doc = Document.from_text(text, uid=note_id)
        slots = {span for span, _ in slotted_spans(doc, include_exam_labels=True)}
        for gold in corpus.for_note(note_id):
            surface = gold.surface.strip().lower()
            if not is_abbreviation_shaped(gold.surface) or gold.span in slots:
                continue
            if drop_general_english and surface in english:
                continue
            senses[surface][gold.concept_id] += 1
    return senses


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    train = snomed_el.load(args.root, limit=args.limit).split("train")
    test = snomed_el.load(args.root, limit=args.limit).split("test")
    fitted = prose_senses(train, drop_general_english=True)
    held_out = prose_senses(test, drop_general_english=True)

    # The prior: majority sense per form, fitted on train only. Ties break on the
    # concept id so the fit is reproducible rather than dict-order dependent.
    prior = {
        surface: max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
        for surface, counts in fitted.items()
        if sum(counts.values()) >= MIN_TRAIN_OCCURRENCES
    }

    lookup = ConceptMatcher(
        args.index,
        MatcherConfig(threshold=1.0, min_match_length=1, accepted_semtypes=None),
        align_semtypes=False,
    )

    def umls_candidates(surface: str) -> int:
        groups = lookup._load().match(surface, best_match=False, ignore_syntax=True)
        return len({x["cui"] for g in groups for x in g if x["ngram"].lower() == surface})

    covered = correct = total = 0
    unseen = 0
    # The headroom splits, and the split is the finding. A form the gold assigns
    # several concepts to, while UMLS offers at most one, is not a disambiguation
    # problem: no policy over candidates can select a candidate that does not
    # exist. That share is unreachable in exactly the sense the stage-3 V0 gate
    # meant, and counting it as headroom would promise a rung something it can
    # never deliver.
    reachable_miss = unreachable_miss = 0
    rows = []
    for surface, counts in sorted(held_out.items()):
        n = sum(counts.values())
        total += n
        if surface not in prior:
            unseen += n
            continue
        covered += n
        hits = counts.get(prior[surface], 0)
        correct += hits
        if umls_candidates(surface) >= 2:
            reachable_miss += n - hits
        else:
            unreachable_miss += n - hits
        if n >= 10:
            rows.append(
                {
                    "surface": surface,
                    "test_n": n,
                    "test_senses": len(counts),
                    "mfs_accuracy": round(hits / n, 4),
                    "headroom": round(1 - hits / n, 4),
                    "umls_candidates": umls_candidates(surface),
                }
            )
    rows.sort(key=lambda r: -r["headroom"] * r["test_n"])

    payload = {
        "question": (
            "How much is left for contextual disambiguation once most-frequent sense has run?"
        ),
        "why": (
            "the budget for the whole rung. Anchor voting, cue authoring and "
            "abstention policy all compete for the gap between the free baseline "
            "and a perfect disambiguator. If the gap is small the correct "
            "decision is to ship the baseline and spend the effort elsewhere."
        ),
        "scope": (
            "free-prose abbreviation-shaped gold spans only. Structural slots are "
            "excluded (position already resolved them, stage 3a) as are "
            "general-English words (not abbreviations)."
        ),
        "protocol": (
            f"majority sense fitted on the train split over forms with >= "
            f"{MIN_TRAIN_OCCURRENCES} occurrences, reported on the held-out test "
            "split. Ties break on concept id so the fit is reproducible."
        ),
        "forms_fitted": len(prior),
        "test_occurrences": total,
        "covered_by_prior": covered,
        "unseen_in_train": unseen,
        "coverage": round(covered / total, 4) if total else None,
        "mfs_accuracy_on_covered": round(correct / covered, 4) if covered else None,
        "oracle_accuracy": 1.0,
        "headroom_total": round(1 - correct / covered, 4) if covered else None,
        "headroom_reachable": round(reachable_miss / covered, 4) if covered else None,
        "headroom_unreachable": round(unreachable_miss / covered, 4) if covered else None,
        "headroom_split_note": (
            "a form the gold assigns several concepts to while UMLS offers at "
            "most one is not a disambiguation problem — no policy over candidates "
            "can select a candidate that does not exist. Only headroom_reachable "
            "is available to stage 3c; headroom_unreachable belongs in the "
            "limitations section with the rest of the vocabulary gap."
        ),
        "worst_forms": rows[:20],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
