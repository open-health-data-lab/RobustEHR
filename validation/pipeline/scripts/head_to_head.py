#!/usr/bin/env python
"""RobustEHR's concept tagger against medspaCy's, on the same gold.

This is the comparison that matters for adoption, and it is not the challenge
leaderboard. Nobody choosing a clinical NLP tool asks whether it would have won a
2024 competition; they ask whether it is at least as good as what they would
otherwise use. medspaCy is what they would otherwise use.

Both systems wrap QuickUMLS over the same index, so the comparison isolates
**configuration and post-processing** rather than matching algorithm. That is the
honest framing: RobustEHR does not claim a better matcher, it claims a better
configured one, and the difference is measurable.

The metric is category-level, because that is what a downstream user needs from
a concept tagger in this package — *is this span a disorder, a procedure, an
anatomical site* — rather than which of 6,595 SNOMED concepts it is. Recall is
reported first: the reference annotates selected concepts rather than every
clinical word, so a span the annotators marked and the tagger found is
unambiguous, while a span only the tagger marked cannot be adjudicated.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

from robustehr.categories import categories_of, load_categories
from robustehr.concepts.matcher import ConceptMatcher, default_semtypes
from robustehr.concepts.pipeline import annotate_document
from robustehr.document import Document
from robustehr.eval import snomed_el
from robustehr.types import Span

CATEGORIES = ("disorder", "disease", "symptom", "procedure", "anatomy", "lab_measurement")


def medspacy_mentions(nlp: Any, text: str) -> list[tuple[Span, frozenset[str]]]:
    """Spans and semantic types from a stock medspaCy pipeline."""
    doc = nlp(text)
    out = []
    for ent in doc.ents:
        semtypes = frozenset(getattr(ent._, "semtypes", None) or ())
        out.append((Span(ent.start_char, ent.end_char), semtypes))
    return out


def build_medspacy(index: Path) -> Any:
    """A stock medspaCy pipeline with QuickUMLS, as a user would get it."""
    import os
    import tempfile

    # Resolve before changing directory, or the path resolves against the temp
    # root — the same trap ConceptMatcher documents.
    resolved = str(index.resolve())
    previous = os.getcwd()
    os.chdir(tempfile.gettempdir())  # see ConceptMatcher for why
    try:
        import medspacy

        # medspacy_quickumls must be named explicitly;  does not
        # include it. This is the stock pipeline a user assembles when they want
        # UMLS concepts out of medspaCy.
        return medspacy.load(
            medspacy_enable=["medspacy_pyrush", "medspacy_quickumls"],
            quickumls_path=resolved,
        )
    finally:
        os.chdir(previous)


#: Minimum linker confidence for a scispaCy candidate to count.
#:
#: scispaCy returns ranked candidates with scores; taking the top one
#: unconditionally would credit it for guesses the other systems do not make.
#: 0.85 is its own documented default for `threshold`.
SCISPACY_THRESHOLD = 0.85


def build_scispacy() -> Any:
    """A stock scispaCy pipeline with the UMLS entity linker.

    The other tool a user would reach for, and unlike medspaCy it is a *linker*
    rather than a dictionary matcher — a genuinely different approach to the same
    problem, which is what makes it worth having as a second baseline.
    """
    import os
    import tempfile

    previous = os.getcwd()
    os.chdir(tempfile.gettempdir())
    try:
        import spacy
        from scispacy.abbreviation import AbbreviationDetector  # noqa: F401
        from scispacy.linking import EntityLinker  # noqa: F401

        nlp = spacy.load("en_core_sci_sm")
        # The detector must be added explicitly. `resolve_abbreviations=True` on
        # the linker only tells it to *consult* `doc._.abbreviations`; without
        # this pipe that extension is never registered and the flag is a silent
        # no-op, and a baseline labelled "abbreviations resolved" would have
        # resolved none.
        nlp.add_pipe("abbreviation_detector")
        nlp.add_pipe(
            "scispacy_linker",
            config={"resolve_abbreviations": True, "linker_name": "umls"},
        )
        return nlp
    finally:
        os.chdir(previous)


def scispacy_mentions(nlp: Any, text: str) -> list[tuple[Span, frozenset[str]]]:
    """Spans and semantic types from scispaCy's UMLS linker.

    Types come from the linker's own knowledge base rather than from our UMLS
    install, so the system is evaluated as its authors ship it.
    """
    linker = nlp.get_pipe("scispacy_linker")
    out = []
    doc = nlp(text)
    for ent in doc.ents:
        candidates = [c for c in ent._.kb_ents if c[1] >= SCISPACY_THRESHOLD]
        if not candidates:
            continue
        entity = linker.kb.cui_to_entity.get(candidates[0][0])
        if entity is None:
            continue
        out.append((Span(ent.start_char, ent.end_char), frozenset(entity.types)))
    return out


def score_system(
    corpus,
    mentions_for,
) -> dict[str, dict[str, float]]:
    """Per-category recall and precision over the gold corpus."""
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"gold": 0, "covered": 0, "predicted": 0, "hits": 0}
    )
    for note_id, text in sorted(corpus.notes.items()):
        gold = corpus.for_note(note_id)
        predicted = mentions_for(text)
        for category in CATEGORIES:
            relevant = [g for g in gold if category in g.categories]
            mine = [s for s, tuis in predicted if category in categories_of(tuis)]

            marked: set[int] = set()
            for g in relevant:
                marked.update(range(g.span.start, g.span.end))
            chosen: set[int] = set()
            for s in mine:
                chosen.update(range(s.start, s.end))

            t = totals[category]
            t["gold"] += len(relevant)
            t["predicted"] += len(mine)
            t["covered"] += sum(
                1 for g in relevant if any(i in chosen for i in range(g.span.start, g.span.end))
            )
            t["hits"] += sum(1 for s in mine if any(i in marked for i in range(s.start, s.end)))
    return {
        category: {
            "gold": t["gold"],
            "predicted": t["predicted"],
            "recall": round(t["covered"] / t["gold"], 4) if t["gold"] else None,
            "precision": round(t["hits"] / t["predicted"], 4) if t["predicted"] else None,
        }
        for category, t in totals.items()
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--split", default="test")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    corpus = snomed_el.load(args.root, limit=args.limit)
    if args.split:
        corpus = corpus.split(args.split)

    ours = ConceptMatcher(args.index)
    results: dict[str, Any] = {
        # Bare matcher first, because that is the like-for-like comparison with
        # medspaCy: same index, same algorithm, configuration only.
        "RobustEHR (matcher only)": score_system(
            corpus,
            lambda t: [(m.span, m.tuis) for m in ours.annotate(t).mentions],
        ),
        # Then the shipped pipeline, which is what a user actually gets. Both are
        # reported: replacing the first would make the medspaCy comparison
        # measure two different things at once.
        "RobustEHR (full pipeline)": score_system(
            corpus,
            lambda t: [
                (m.span, m.tuis)
                for m in annotate_document(Document.from_text(t, uid="h2h"), ours).mentions
            ],
        ),
    }

    try:
        from loguru import logger

        logger.remove()
    except ImportError:  # pragma: no cover
        pass
    nlp = build_medspacy(args.index)
    results["medspaCy (stock)"] = score_system(corpus, lambda t: medspacy_mentions(nlp, t))

    sci = build_scispacy()
    results["scispaCy (UMLS linker)"] = score_system(corpus, lambda t: scispacy_mentions(sci, t))

    payload = {
        "question": (
            "Is RobustEHR's concept tagger at least as good as the tool a user "
            "would otherwise reach for?"
        ),
        "systems": {
            "RobustEHR (matcher only)": (
                "ConceptMatcher — QuickUMLS with the semantic-type filter aligned "
                f"to RobustEHR's {len(default_semtypes())} category types"
            ),
            "medspaCy (stock)": (
                "medspacy.load with QuickUMLS, default configuration — what a "
                "user gets out of the box"
            ),
            "scispaCy (UMLS linker)": (
                "en_core_sci_sm with scispacy_linker (umls, abbreviations "
                f"resolved), candidates above {SCISPACY_THRESHOLD}. A linker "
                "rather than a dictionary matcher, so a genuinely different "
                "approach to the same problem"
            ),
        },
        "shared": (
            "same notes, same gold spans, same metric. RobustEHR and medspaCy "
            "additionally share the same QuickUMLS index; scispaCy brings its "
            "own knowledge base, as its authors ship it"
        ),
        "metric": (
            "per-category recall and precision against expert annotations. Recall "
            "leads: the reference annotates selected concepts rather than every "
            "clinical word, so an unmatched prediction cannot be adjudicated."
        ),
        "notes": len(corpus.notes),
        "gold_spans": len(corpus.spans),
        "categories": {k: load_categories()[k].label for k in CATEGORIES},
        "results": results,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
