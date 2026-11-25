#!/usr/bin/env python
"""When our segmenter changes a UMLS concept's assertion, which arm is right?

Stage 8 reuses medspaCy's ConText engine but **modifies its input**: cue scope is
resolved against this package's sentence boundaries instead of PyRuSH's. That is
a departure from a reused tool, and this project's rule is that a departure owes
a number against the thing it departed from — not an argument.

Two of those numbers already exist and neither is sufficient here.
`assertion_accuracy.json` reports the two arms as *identical*, because every row
of the NegEx gold is a single sentence and no cue can cross a boundary that does
not exist. `phenotype_assertion.json` shows the arms disagreeing at scale — the
non-affirmed rate over 934 gold UMLS concept spans moves 34.7% to 30.1% — but it
reports only that the rate changed, not whether the changes were improvements.

**So this script asks the question those two cannot: on real UMLS concept spans,
where exactly do the arms disagree, and which one is correct?**

There is no in-domain assertion gold to answer that with. There is something
better suited to this particular question: **the note's own structure**. ConText
assigns an attribute because a cue took scope over a target. If the cue and the
target sit in *different list items*, or on opposite sides of a *section header*,
then the cue did not govern that target — and that is a fact about the document,
not an opinion about the annotation. The structural layer that decides it is
hand-written, versioned, and validated against PyRuSH at stage 2, so using it as
the referee here reuses a measured component rather than inventing a judgement.

Each disagreement is therefore adjudicated:

* **structure favours ours** — the losing arm asserted an attribute using a cue
  separated from the target by a list-item or section boundary.
* **structure favours PyRuSH** — the same, with the arms swapped.
* **undecided** — the cue and target share a line, item and section, so document
  structure does not settle it and neither arm can claim the span.

Reporting the undecided share honestly matters more than the win rate: it is the
fraction of the disagreement this method has no authority over.

No note text reaches the artifact — spans are reported as offsets, attributes and
CUIs, and the cue as the ConText rule literal, which is terminology rather than
patient data.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.concepts.context import Cue, qualify
from robustehr.concepts.matcher import ConceptMatcher
from robustehr.concepts.pipeline import annotate_document, qualify_document
from robustehr.corpus import read_documents
from robustehr.document import Document
from robustehr.types import Span


def item_index(doc: Document, offset: int) -> tuple[int, int] | None:
    """``(block, item)`` for the list item containing ``offset``, if any."""
    for block in doc.lists:
        for position, item in enumerate(block.items):
            if item.content.start <= offset < item.content.end:
                return (block.idx, position)
    return None


def section_index(doc: Document, offset: int) -> int | None:
    for section in doc.sections:
        if section.full.start <= offset < section.full.end:
            return section.idx
    return None


def separated(doc: Document, cue: Cue, target: Span) -> str | None:
    """Why the note's structure says this cue cannot govern this target.

    ``None`` means it does not say so — the two share whatever units exist, and
    the disagreement is outside this referee's authority.
    """
    cue_item, target_item = item_index(doc, cue.span.start), item_index(doc, target.start)
    if cue_item is not None and target_item is not None and cue_item != target_item:
        return "different list items"
    if (cue_item is None) != (target_item is None):
        return "one inside a list item, one outside"
    if section_index(doc, cue.span.start) != section_index(doc, target.start):
        return "different sections"
    return None


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    matcher = ConceptMatcher(args.index)
    verdicts: Counter[str] = Counter()
    transitions: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    by_attribute: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    note_labels: dict[str, int] = {}
    compared = disagreed = 0

    for doc in read_documents(args.corpus, limit=args.limit):
        mentions = annotate_document(doc, matcher)
        spans = tuple(m.span for m in mentions.mentions)
        if not spans:
            continue
        cui_of = {m.span: m.cui for m in mentions.mentions}
        ours = qualify_document(doc, mentions)
        stock = qualify(doc.text, spans)

        for span in spans:
            a, b = stock.at(span), ours.at(span)
            if a is None or b is None:
                continue
            compared += 1
            if a.attributes == b.attributes:
                continue
            disagreed += 1
            transitions[f"{a.canon()} -> {b.canon()}"] += 1
            for name in a.attributes ^ b.attributes:
                by_attribute[name] += 1

            # The arm that asserted the extra attribute owns the burden: it is
            # the one claiming a cue reached this target.
            claimant, other = ("pyrush", a) if a.attributes - b.attributes else ("ours", b)
            reason = next(
                (r for cue in other.cues if (r := separated(doc, cue, span)) is not None),
                None,
            )
            if reason is None:
                verdicts["undecided"] += 1
            else:
                reasons[reason] += 1
                verdicts["ours" if claimant == "pyrush" else "pyrush"] += 1
                if len(examples) < 25:
                    examples.append(
                        {
                            # An ordinal label, never the corpus's own note id: an
                            # id beside an offset and a concept is a statement
                            # about one patient's note, and this file is published.
                            "note": f"note-{note_labels.setdefault(doc.uid, len(note_labels) + 1)}",
                            "span": [span.start, span.end],
                            "cui": cui_of.get(span, ""),
                            "pyrush": a.canon(),
                            "ours": b.canon(),
                            "cue_literal": next((c.literal for c in other.cues), None),
                            "structure_says": reason,
                            "favours": "ours" if claimant == "pyrush" else "pyrush",
                        }
                    )

    decided = verdicts["ours"] + verdicts["pyrush"]
    payload = {
        "question": (
            "Where our boundaries change a UMLS concept's assertion, which arm does "
            "the note's own structure support?"
        ),
        "why": (
            "stage 8 reuses medspaCy's ConText engine but feeds it our sentence "
            "boundaries instead of PyRuSH's. A departure from a reused tool owes "
            "a number against that tool. assertion_accuracy.json cannot supply "
            "it (its gold is single sentences, so the arms tie) and "
            "phenotype_assertion.json shows only that the rate moved, not that "
            "the moves were right."
        ),
        "referee": (
            "the note's own structure, not an annotator. A cue separated from "
            "its target by a list-item or section boundary did not govern it — a "
            "fact about the document. The structural layer deciding this is "
            "hand-written, versioned and validated against PyRuSH at stage 2."
        ),
        "notes": args.limit,
        "umls_spans_compared": compared,
        "spans_where_arms_disagree": disagreed,
        "disagreement_rate": round(disagreed / compared, 4) if compared else None,
        "attributes_involved": dict(by_attribute.most_common()),
        "top_transitions": dict(transitions.most_common(8)),
        "adjudication": {
            "structure_favours_ours": verdicts["ours"],
            "structure_favours_pyrush": verdicts["pyrush"],
            "undecided": verdicts["undecided"],
            "decided_share": round(decided / disagreed, 4) if disagreed else None,
            "ours_share_of_decided": round(verdicts["ours"] / decided, 4) if decided else None,
        },
        "separation_reasons": dict(reasons.most_common()),
        "how_to_read": (
            "the undecided count matters more than the win rate: it is the share "
            "of the disagreement document structure has no authority over, and "
            "no claim should be made about it here. A high ours_share_of_decided "
            "means that where structure can rule, it rules for the boundaries we "
            "ship — which is the specific claim four documents made and none had "
            "measured."
        ),
        "examples": examples,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
