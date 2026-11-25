#!/usr/bin/env python
"""Emit an annotation worksheet for the assertion dimensions that have no gold.

Three of stage 8's attributes — `historical`, `family`, `uncertain` —
have no gold in any domain, and `uncertain` has only an out-of-domain proxy
(`scope_accuracy.json`, biomedical abstracts). The operators that depend on them
(`semantic.temporality_shift`, `semantic.experiencer_shift`,
`discourse.distractor_inject`) would therefore ship anchored on detectors nobody
has scored.

**Why the synthetic fixtures and not MIMIC.** MIMIC-IV note text is held under
the PhysioNet Credentialed Health Data Use Agreement, and disclosing it to a
third party — an LLM API included — requires authorisation the fixtures do not.
`tests/fixtures/clinical/` was written from scratch, describes no real patient,
and each module says so, so it can be annotated by any means and the resulting
gold can ship **in the repository** rather than in `data/`. That is the
difference between a gold this project can publish and one it can only reference,
and it is why this gold was built first.

A companion MIMIC gold was built afterwards under confirmed authorisation, with
routing restricted to providers that do not log prompts — see
`validation/pipeline/scripts/annotate_assertions.py`. It answers a question this one cannot, because
these fixtures are negation-dense and hedge-poor. It lives in `data/` and only
its aggregates are published: authorisation to *annotate* is not permission to
*redistribute*, and the DUA's bar on the second is unchanged.

The fixtures were also built to encode assertion traps deliberately — a shared
negation cue over three targets, a family history without the word "family", a
rule-out that is precision-side, spoken punctuation replacing terminators — so
they are unusually dense in exactly the phenomena under test.

**Spans come from the pipeline, not from the annotator.** Stage 8 qualifies spans
supplied by stages 5-7, so the worksheet is built from `annotate_document` output.
That keeps the measurement about assertion rather than detection, matching how
NegEx and BioScope are scored, and it means the gold covers the spans the running
system will actually ask about.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

from robustehr.concepts.matcher import ConceptMatcher
from robustehr.concepts.pipeline import annotate_document
from robustehr.document import Document
from robustehr.types import Span

#: Fixtures in the worksheet.
#:
#: **Every mention in a chosen fixture is annotated**, and fixtures are chosen
#: rather than mentions. Sampling mentions would have to sample on *something* —
#: and sampling on ConText's own output, the obvious handle, would build a gold
#: that can never contain its false negatives. Whole fixtures keep the set
#: unbiased within itself at the cost of covering fewer documents, which is the
#: right trade for a first gold.
#:
#: Chosen for assertion density and format stress, not volume:
#: `complex_discharge` alone carries 524 mentions and would dominate the set.
FIXTURES = (
    "epic_progress",  # structured EHR export; one `Denies` over three findings
    "cardiology_dictated",  # spoken punctuation replaces terminators
    "psychiatry_clinic",  # exercises the `: no` BACKWARD rule
    "family_med_freetext",  # abbreviated, header-free
    "radiology_report",  # impression-style negation
    "allcaps_legacy",  # case robustness
    "pediatric_admission",  # third-party experiencer without the word `family`
)

#: Characters of context either side of the mention shown to the annotator.
#: Wide enough to carry a cue at the far end of a sentence, narrow enough that a
#: worksheet stays readable.
CONTEXT_CHARS = 190


def window(text: str, span: Span) -> str:
    """The mention marked inside its neighbourhood, newlines made visible.

    Newlines matter to the judgement — a cue on the previous line may or may not
    govern the mention — so they are shown as ``⏎`` rather than collapsed.
    """
    left = max(0, span.start - CONTEXT_CHARS)
    right = min(len(text), span.end + CONTEXT_CHARS)
    piece = (
        text[left : span.start] + "《" + text[span.start : span.end] + "》" + text[span.end : right]
    )
    return piece.replace("\n", " ⏎ ")


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    from tests.fixtures.clinical import FORMATS

    matcher = ConceptMatcher(args.index)
    items = []
    for name in FIXTURES:
        note = FORMATS[name]
        doc = Document.from_text(note.text, uid=name)
        seen: set[tuple[int, int]] = set()
        for mention in annotate_document(doc, matcher).mentions:
            key = (mention.span.start, mention.span.end)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "fixture": name,
                    "start": mention.span.start,
                    "end": mention.span.end,
                    "surface": note.text[mention.span.start : mention.span.end],
                    "cui": mention.cui,
                    "context": window(note.text, mention.span),
                }
            )

    payload = {
        "task": "assertion annotation over synthetic clinical fixtures",
        "dimensions": ["negated", "uncertain", "historical", "family", "hypothetical"],
        "instruction": (
            "For each item, decide which of the dimensions apply to the "
            "marked span 《like this》, from the patient's chart perspective. "
            "negated: the note says this is absent. uncertain: hedged, possible, "
            "cannot be excluded. historical: past rather than current. family: "
            "belongs to someone other than the patient. hypothetical: "
            "conditional, contingent, or a PRN/return instruction. Empty means "
            "affirmed and current for this patient. Dimensions co-occur."
        ),
        "fixtures": list(FIXTURES),
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(items)} items across {len(FIXTURES)} fixtures -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
