#!/usr/bin/env python
"""V0: is an abbreviation resolver worth building at all?

The gate that `validation/record/abbreviation-resolver-spec.md` puts in front of the whole
subsystem, run before a line of it is written. Two numbers decide:

**The floor** — what the shipped matcher already gets on abbreviation-shaped gold
spans, including at the exact-lookup configuration a from-scratch resolver would
have to beat. If a subsystem cannot improve on a two-line configuration change,
it is not warranted.

**The ceiling** — what a *perfect* disambiguator could get. For every gold
abbreviation span, ask whether the UMLS inventory contains **any** candidate
carrying the annotated category. Where it does not, no resolver at any policy can
recover that span, and the gap between floor and ceiling is the entire budget
available to stage 3.

Reporting the ceiling is the honest part. A resolver measured only against its
own before-and-after looks like progress at any level of performance; measured
against what is achievable it either closes a real gap or does not. If most of
the miss set is unreachable, the correct engineering decision is to spend the
budget elsewhere and say so in the limitations section.

Definition of "abbreviation-shaped": a gold span that is a **single token of 2-6
alphabetic characters**. Deliberately mechanical — a definition that required
judging what "is really an abbreviation" would put the finding at the mercy of
the judgement.

The script also reports **where** each one sits, which turns out to decide the
architecture. "Does expansion need context?" has three answers, not two, and the
largest class needs neither a dictionary sense nor surrounding prose — only the
structural position stage 2 already knows.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.categories import categories_of
from robustehr.concepts.matcher import ConceptMatcher, MatcherConfig, default_semtypes
from robustehr.concepts.structural import labelled_values
from robustehr.document import Document
from robustehr.eval import snomed_el

#: Where an abbreviation sits, which decides what can disambiguate it.
#:
#: The first two are resolvable from **structure alone** — no dictionary sense
#: and no surrounding prose, just the position stage 2 already computed. That is
#: the finding: they need neither of the things "context" usually means.
PLACEMENT_LABEL = "label of a value (creat 1.1)"
PLACEMENT_IN_LAB_LINE = "inside a labelled-value line"
PLACEMENT_COLON = "followed by a colon (HEENT:)"
PLACEMENT_PROSE = "free prose"


def placement_of(
    gold: Any, text: str, label_spans: set[tuple[int, int]], lab_lines: set[int]
) -> str:
    """Which structural position this gold span occupies."""
    if (gold.span.start, gold.span.end) in label_spans:
        return PLACEMENT_LABEL
    if text.count("\n", 0, gold.span.start) in lab_lines:
        return PLACEMENT_IN_LAB_LINE
    if text[gold.span.end : gold.span.end + 1] == ":":
        return PLACEMENT_COLON
    return PLACEMENT_PROSE


#: Bounds of an abbreviation-shaped surface, in characters.
MIN_CHARS, MAX_CHARS = 2, 6


def is_abbreviation_shaped(surface: str) -> bool:
    """One token, 2-6 characters, all alphabetic."""
    stripped = surface.strip()
    return (
        MIN_CHARS <= len(stripped) <= MAX_CHARS
        and stripped.isalpha()
        and " " not in stripped
        and "\n" not in stripped
    )


def candidates_for(matcher: ConceptMatcher, surface: str) -> list[dict[str, Any]]:
    """Every UMLS candidate for this surface, not just the best one.

    The ceiling needs the whole candidate set: a perfect disambiguator picks the
    right member, so the question is whether a right member exists at all.
    """
    groups = matcher._load().match(surface, best_match=False, ignore_syntax=True)
    return [c for group in groups for c in group]


def survey_placement(
    corpus: Any, inventory: dict[str, list[dict[str, Any]]]
) -> tuple[Counter[str], Counter[str]]:
    """Where the abbreviation-shaped spans sit, and where the unreachable ones do.

    The second counter is the one that decides the design: if the unreachable
    spans cluster in structurally anchored positions, the fix is structural
    rather than lexical.
    """
    placement: Counter[str] = Counter()
    unreachable: Counter[str] = Counter()
    for note_id, text in sorted(corpus.notes.items()):
        pairs = labelled_values(Document.from_text(text, uid=note_id))
        label_spans = {(lv.label.start, lv.label.end) for lv in pairs}
        lab_lines = {text.count("\n", 0, lv.label.start) for lv in pairs}
        for gold in corpus.for_note(note_id):
            if not is_abbreviation_shaped(gold.surface):
                continue
            where = placement_of(gold, text, label_spans, lab_lines)
            placement[where] += 1
            found = inventory.get(gold.surface.strip().lower(), [])
            if not any(
                gold.categories & categories_of(frozenset(str(t) for t in c["semtypes"]))
                for c in found
            ):
                unreachable[where] += 1
    return placement, unreachable


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--split", default="test")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    corpus = snomed_el.load(args.root, limit=args.limit)
    if args.split:
        corpus = corpus.split(args.split)

    targets = [g for g in corpus.spans if is_abbreviation_shaped(g.surface)]
    # Surfaces repeat heavily (`hct` hundreds of times), so the expensive lookup
    # runs once per distinct surface and the result is reused per occurrence.
    distinct = sorted({g.surface.strip().lower() for g in targets})

    exact = ConceptMatcher(
        args.index,
        MatcherConfig(
            threshold=1.0, min_match_length=MIN_CHARS, accepted_semtypes=default_semtypes()
        ),
    )
    shipped = ConceptMatcher(args.index)

    inventory: dict[str, list[dict[str, Any]]] = {
        surface: candidates_for(exact, surface) for surface in distinct
    }

    placement, placement_unreachable = survey_placement(corpus, inventory)

    reachable = 0
    exact_correct = 0
    shipped_correct = 0
    no_candidates = 0
    unreachable_surfaces: Counter[str] = Counter()
    ambiguity: Counter[int] = Counter()

    for gold in targets:
        surface = gold.surface.strip().lower()
        found = inventory[surface]
        wanted = gold.categories
        if not found:
            no_candidates += 1
            unreachable_surfaces[surface] += 1
            continue
        ambiguity[len({str(c["cui"]) for c in found})] += 1

        # Ceiling: does ANY candidate carry the annotated category?
        if any(wanted & categories_of(frozenset(str(t) for t in c["semtypes"])) for c in found):
            reachable += 1
        else:
            unreachable_surfaces[surface] += 1

        # Floor: what each configuration actually returns for this surface alone.
        for matcher, counter in ((exact, "exact"), (shipped, "shipped")):
            mentions = matcher.annotate(surface).mentions
            hit = any(wanted & m.categories for m in mentions)
            if hit and counter == "exact":
                exact_correct += 1
            elif hit:
                shipped_correct += 1

    total = len(targets)
    payload = {
        "question": "Is an abbreviation resolver worth building, and how much room is there?",
        "definition": (
            f"abbreviation-shaped = a gold span that is one token of "
            f"{MIN_CHARS}-{MAX_CHARS} alphabetic characters. Mechanical on "
            "purpose: judging what 'is really an abbreviation' would put the "
            "finding at the mercy of the judgement."
        ),
        "notes": len(corpus.notes),
        "gold_spans_total": len(corpus.spans),
        "abbreviation_shaped": total,
        "abbreviation_share": round(total / len(corpus.spans), 4) if corpus.spans else None,
        "distinct_surfaces": len(distinct),
        "floor": {
            "shipped_matcher_correct": shipped_correct,
            "shipped_accuracy": round(shipped_correct / total, 4) if total else None,
            "exact_lookup_correct": exact_correct,
            "exact_accuracy": round(exact_correct / total, 4) if total else None,
        },
        "ceiling": {
            "category_reachable": reachable,
            "ceiling_accuracy": round(reachable / total, 4) if total else None,
            "no_umls_candidate_at_all": no_candidates,
            "unreachable_share": round(1 - reachable / total, 4) if total else None,
        },
        "ambiguity_histogram": {str(k): v for k, v in sorted(ambiguity.items())[:12]},
        "placement": {
            "all": dict(placement.most_common()),
            "unreachable_only": dict(placement_unreachable.most_common()),
            "why_it_matters": (
                "the first two positions are resolvable from STRUCTURE alone — no "
                "dictionary sense, no surrounding prose, only what stage 2 already "
                "computed. That is a third answer to 'does expansion need "
                "context?', and it covers the largest share of the miss set."
            ),
        },
        "top_unreachable_surfaces": dict(unreachable_surfaces.most_common(25)),
        "how_to_read": (
            "ceiling minus floor is the entire budget available to stage 3. "
            "unreachable_share is what no resolver at any policy can recover, and "
            "belongs in the limitations section rather than in a future work list."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
