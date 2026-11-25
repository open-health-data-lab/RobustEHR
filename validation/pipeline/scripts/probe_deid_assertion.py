#!/usr/bin/env python
"""Does the de-identification convention change a downstream clinical verdict?

It does, and this script is the reproduction.

``render.deid_restyle`` converts between de-identification conventions. It is
``INVARIANT_BY_CONSTRUCTION``: the canonicalizer ``kappa.mask_deid`` projects
every placeholder to one sentinel token, and the property test proves the
projection is unchanged by the operator. No clinical reference can move. By any
reasonable reading, a note with ``___`` and the same note with ``<REDACTED>``
say the same thing about the same patient.

medspaCy ConText disagrees. On the note below, three of six conventions cause
the sentence segmenter to merge two list items, which lets a negation cue in
item 1 take scope over item 2 and mark an active, controlled diagnosis as
negated. Two of the three failing conventions are ``___`` and ``[** **]`` — the
MIMIC-IV and MIMIC-III conventions, i.e. the formatting of the most widely used
clinical corpora in the field.

This is the package's thesis in one table. The perturbation is provably
reference-preserving, the dose is a formatting change, and the downstream
assertion flips from present to absent. It also explains why the assertion layer
must be measured *per de-identification scheme* rather than once, and why
RobustEHR segments structure itself instead of delegating to a sentence splitter.

Requires the clinical extra::

    uv pip install medspacy
    python validation/pipeline/scripts/probe_deid_assertion.py \
        --out validation/measurements/deid_assertion_probe.json

Not part of the test suite: medspaCy is not a core dependency, and a probe whose
purpose is to document another package's behaviour must not gate this one's CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: The same clinical note throughout. Only the de-identification placeholder in
#: item 2 varies, and item 2 is what gets misread.
TEMPLATE = (
    "ASSESSMENT:\n"
    "   1.  No evidence of acute\n"
    "       pneumonia on imaging.\n"
    "   2.  {placeholder} has hypertension,   controlled.\n"
)

#: Conventions RobustEHR's de-id segmenter already recognises, plus two
#: non-masked controls that show the failure is caused by the mask and not by
#: the sentence structure.
CONVENTIONS: dict[str, str] = {
    "mimic_iv_underscore": "___",
    "mimic_iii_bracket": "[** Name **]",
    "angle_redacted": "<REDACTED>",
    "xxx": "XXX",
    "control_real_name": "Mr. Smith",
    "control_generic_noun": "Patient",
}

#: What every convention should say. Hypertension is asserted, present and
#: controlled; nothing in the note negates it.
EXPECTED_NEGATED = False


def run() -> dict[str, object]:
    import warnings

    warnings.filterwarnings("ignore")
    from robustehr.concepts.context import silence_pyrush

    silence_pyrush()

    import medspacy
    from medspacy.ner import TargetRule

    nlp = medspacy.load(
        medspacy_enable=["medspacy_pyrush", "medspacy_target_matcher", "medspacy_context"]
    )
    nlp.get_pipe("medspacy_target_matcher").add(
        [TargetRule("hypertension", "CONDITION"), TargetRule("pneumonia", "CONDITION")]
    )

    results = []
    for name, placeholder in CONVENTIONS.items():
        doc = nlp(TEMPLATE.format(placeholder=placeholder))
        entity = next((e for e in doc.ents if e.text == "hypertension"), None)
        negated = None if entity is None else bool(entity._.is_negated)
        results.append(
            {
                "convention": name,
                "placeholder": placeholder,
                "sentences": len(list(doc.sents)),
                "hypertension_negated": negated,
                "correct": negated is EXPECTED_NEGATED,
            }
        )

    failures = [r for r in results if not r["correct"]]
    return {
        "tool": f"medspacy {medspacy.__version__}",
        "finding": (
            "The de-identification convention alone flips the negation verdict "
            "on an active diagnosis. The perturbation between conventions is "
            "INVARIANT_BY_CONSTRUCTION and cannot change clinical reference."
        ),
        "mechanism": (
            "Masked placeholders defeat sentence segmentation, merging two list "
            "items into one sentence, which lets the negation cue in item 1 take "
            "scope over the diagnosis in item 2."
        ),
        "expected_negated": EXPECTED_NEGATED,
        "n_conventions": len(results),
        "n_incorrect": len(failures),
        "incorrect_conventions": [r["convention"] for r in failures],
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        report = run()
    except ImportError:
        print(
            "medspacy is not installed; this probe documents medspaCy behaviour.\n"
            "  uv pip install medspacy",
            file=sys.stderr,
        )
        return 2

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)

    print(
        f"\n{report['n_incorrect']} of {report['n_conventions']} de-identification "
        f"conventions produced a false negation: {report['incorrect_conventions']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
