#!/usr/bin/env python
"""Which assertion arm survives a change of de-identification convention?

`assertion_accuracy.json` measures whether stage 8 is *right*, and it finds
negation good — 0.9289 F1 against a 0.0000 majority floor. But it cannot
separate the two ConText arms, and the reason is structural rather than a
result: every row of the NegEx gold is a single sentence with the concept inside
it, so there is no second sentence for a cue to leak into and both segmenters
return the same one boundary. **The instrument has no power there.**

This is where segmentation is testable. `probe_deid_assertion.py` showed, on one
note and one arm, that three de-identification conventions — including MIMIC-IV's
``___`` and MIMIC-III's ``[** **]`` — merge two list items so a negation cue in
item 1 takes scope over item 2 and marks an active diagnosis as negated. This
generalises it to **three arms across several templates**, and asks a question
with a right answer known in advance:

    A de-identification placeholder carries no clinical meaning. Swapping one
    convention for another cannot change what a note says about a patient. So an
    arm whose verdict moves with the convention is reading formatting, not
    medicine.

Two numbers per arm:

* **accuracy** — verdicts matching the known-correct answer.
* **instability** — the share of templates for which the arm gives more than one
  answer across conventions. This is the invariance claim, and it needs no gold
  at all: whatever the right answer is, it cannot depend on the mask.

`anchors.py` predicts the window arm wins the second and loses the first — a
fixed token window cannot see a sentence boundary, so it is immune to
segmentation but blind to scope. Whether our boundaries buy ConText the same
immunity is the CTX-B question, asked here because it cannot be asked of NegEx.

Every template is written from scratch and describes no real patient, so this
script and its artifact are publishable in full.
"""

from __future__ import annotations

import argparse
import json
import warnings
from dataclasses import dataclass
from pathlib import Path

from scripts.assertion_accuracy import (
    context_literals,
    dependency_predicts_negated,
    negspacy_predicts_negated,
    window_predicts_negated,
)

from robustehr.concepts.context import qualify
from robustehr.document import Document
from robustehr.types import Span

#: Conventions RobustEHR's de-id segmenter recognises, plus two unmasked
#: controls that separate "the mask did it" from "the structure did it".
CONVENTIONS: dict[str, str] = {
    "mimic_iv_underscore": "___",
    "mimic_iii_bracket": "[** Name **]",
    "angle_redacted": "<REDACTED>",
    "curly_tag": "{{NAME}}",
    "xxx": "XXX",
    "control_real_name": "Mr. Smith",
    "control_generic_noun": "The patient",
}


@dataclass(frozen=True, slots=True)
class Template:
    name: str
    text: str
    """Contains ``{placeholder}`` exactly once."""
    target: str
    """The concept whose assertion is under test. Located by string search."""
    negated: bool
    """The correct verdict, which no de-identification convention may change."""
    why: str


#: Each one puts a negation cue and the target in *different* structural units,
#: so a segmenter that merges them produces a wrong verdict. That is the only
#: mechanism under test.
TEMPLATES: tuple[Template, ...] = (
    Template(
        name="numbered_list_leak",
        text=(
            "ASSESSMENT:\n"
            "   1.  No evidence of acute\n"
            "       pneumonia on imaging.\n"
            "   2.  {placeholder} has hypertension,   controlled.\n"
        ),
        target="hypertension",
        negated=False,
        why="a negation cue in item 1 must not reach item 2",
    ),
    Template(
        name="bulleted_problem_list",
        text=(
            "PROBLEM LIST:\n"
            "  - Denies chest pain and dyspnea.\n"
            "  - {placeholder} continues on metformin for diabetes.\n"
        ),
        target="diabetes",
        negated=False,
        why="a bulleted denial must not scope into the next bullet",
    ),
    Template(
        name="header_boundary",
        text=(
            "HPI:\nNo fevers reported. {placeholder} was seen in clinic.\n\n"
            "PAST MEDICAL HISTORY:\nAtrial fibrillation on apixaban.\n"
        ),
        target="Atrial fibrillation",
        negated=False,
        why="a cue before a section header must not cross it",
    ),
    Template(
        name="true_negation_survives",
        text=("IMPRESSION:\n{placeholder} imaging shows no pulmonary embolism.\n"),
        target="pulmonary embolism",
        negated=True,
        why="a genuine negation must survive every convention too",
    ),
    # The three below exist to give the instrument power against arms that pass
    # the first four trivially. Each targets one arm's known failure mode.
    Template(
        name="lexical_negation",
        text="ROS:\n{placeholder} denies orthopnea and reports good exercise tolerance.\n",
        target="orthopnea",
        negated=True,
        why="`denies` carries the negation in the verb; no parse relation marks it",
    ),
    Template(
        name="placeholder_ends_sentence",
        text=(
            "The patient was seen by {placeholder}. "
            "Chest radiograph demonstrated a left lower lobe infiltrate.\n"
        ),
        target="infiltrate",
        negated=False,
        why="a placeholder abutting a period is where sentence splitters disagree",
    ),
    Template(
        name="negation_two_sentences_back",
        text=(
            "IMPRESSION:\n{placeholder} shows no acute intracranial abnormality. "
            "The paranasal sinuses are clear. There is mild cerebral atrophy.\n"
        ),
        target="cerebral atrophy",
        negated=False,
        why="a cue must not reach two sentences forward, whatever the mask",
    ),
)


def locate(text: str, target: str) -> Span | None:
    at = text.find(target)
    return Span(at, at + len(target)) if at >= 0 else None


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    cues = context_literals()
    arms = (
        "dependency_parse",
        "window_cue",
        "negspacy",
        "ctx_a_pyrush",
        "ctx_b_our_boundaries",
    )
    verdicts: dict[str, dict[str, dict[str, bool | None]]] = {a: {} for a in arms}

    for template in TEMPLATES:
        for arm in arms:
            verdicts[arm][template.name] = {}
        for convention, placeholder in CONVENTIONS.items():
            text = template.text.format(placeholder=placeholder)
            span = locate(text, template.target)
            if span is None:  # pragma: no cover - templates are fixed
                continue
            verdicts["window_cue"][template.name][convention] = window_predicts_negated(
                text, span, cues, args.window
            )
            verdicts["negspacy"][template.name][convention] = negspacy_predicts_negated(text, span)
            verdicts["dependency_parse"][template.name][convention] = dependency_predicts_negated(
                text, span
            )
            verdicts["ctx_a_pyrush"][template.name][convention] = "negated" in qualify(
                text, (span,)
            ).attributes_for(span)
            doc = Document.from_text(text, uid=template.name)
            bounds = tuple(s.span.start for s in doc.sentences)
            verdicts["ctx_b_our_boundaries"][template.name][convention] = "negated" in qualify(
                text, (span,), boundaries=bounds
            ).attributes_for(span)

    expected = {t.name: t.negated for t in TEMPLATES}
    results = {}
    for arm in arms:
        cells = correct = 0
        unstable = []
        for name, per_convention in sorted(verdicts[arm].items()):
            answers = set(per_convention.values())
            if len(answers) > 1:
                unstable.append(name)
            for _convention, answer in sorted(per_convention.items()):
                cells += 1
                if answer is expected[name]:
                    correct += 1
        results[arm] = {
            "cells": cells,
            "correct": correct,
            "accuracy": round(correct / cells, 4) if cells else None,
            "templates_unstable_across_conventions": sorted(unstable),
            "instability": round(len(unstable) / len(TEMPLATES), 4),
            "per_template": {
                name: {c: v for c, v in sorted(per.items())}
                for name, per in sorted(verdicts[arm].items())
            },
        }

    payload = {
        "question": (
            "Does an assertion verdict change when only the de-identification convention changes?"
        ),
        "why": (
            "a placeholder carries no clinical meaning, so swapping one "
            "convention for another cannot change what a note says about a "
            "patient. An arm whose verdict moves with the convention is reading "
            "formatting, not medicine. Unlike accuracy, this needs no gold: "
            "whatever the right answer is, it cannot depend on the mask."
        ),
        "why_not_measurable_on_negex": (
            "every NegEx gold row is a single sentence containing its concept, "
            "so no cue can leak across a boundary and both segmenters return one "
            "sentence. assertion_accuracy.json therefore reports CTX-A and CTX-B "
            "as identical; that tie is the instrument having no power, not a "
            "finding about segmentation."
        ),
        "templates": [
            {"name": t.name, "target": t.target, "expected_negated": t.negated, "why": t.why}
            for t in TEMPLATES
        ],
        "conventions": CONVENTIONS,
        "arms": results,
        "how_to_read": (
            "instability 0.0 is the only good answer for the second metric, and "
            "it is a property of the instrument rather than a score. An arm can "
            "be perfectly stable and wrong — the always-affirmed baseline is — "
            "so read instability beside the accuracy column and beside "
            "assertion_accuracy.json, never alone."
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
