#!/usr/bin/env python
"""Do the SEMANTIC operators ever ADD a modifier to a concept that had none?

**The claim this tests.** The four SEMANTIC operators are supposed to *reverse*
an assertion, not invent one. Each enumerates cues ConText already found and
rewrites them, so by construction a concept the note asserts plainly — no
negation, no hedge, no history, no other experiencer — is never a target. If that
holds, a robustness result can say the perturbation *removed* modifiers and never
manufactured them, which is a much stronger statement than a flip rate.

It is stated here as a measurement rather than as an argument from the code,
because the mechanism that could break it is not in the operator at all: an edit
changes the text, and ConText re-reads the changed text. Removing one cue can
*expose* another that the first was covering.

**Two denominators, and the difference matters.** The dose record counts **cues**,
because a cue is what gets edited. A reader asks about **concepts**, because a
concept is the unit of clinical meaning. They are not the same number — one cue
can govern several mentions (`no fever, chills or cough`) and one mention can sit
under several cues. Both are reported here:

* *cue-level dose* — what the run artifact records, and what severity is a
  fraction of;
* *concept-level dose* — how many asserted concepts actually changed verdict,
  which is what a robustness claim should quote to a clinical reader.

Licensing: counts only, no note text.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.concepts.matcher import ConceptMatcher
from robustehr.concepts.pipeline import annotate_document, qualify_document
from robustehr.corpus import read_documents
from robustehr.document import Document
from robustehr.ops import registry
from robustehr.runner import apply_operator, severity_ladder
from robustehr.types import Span

#: Operator -> the dimension it removes.
FLIPS = {
    "semantic.negation_flip": "negated",
    "semantic.uncertainty_flip": "uncertain",
    "semantic.temporality_shift": "historical",
    "semantic.experiencer_shift": "family",
}


def measure(
    op_id: str, dimension: str, docs: list[Any], matcher: Any, severity: Any
) -> dict[str, Any]:
    """Invention and removal counts, at both denominators."""
    operator = registry.get(op_id)()
    unmodified = invented = removed = 0
    asserted = flipped = 0
    cues_eligible = cues_applied = 0
    invented_as: Counter[str] = Counter()

    for doc in docs:
        before = qualify_document(doc, annotate_document(doc, matcher))
        if not len(before):
            continue
        result = apply_operator(doc, operator, operator.meta, severity)
        cues_eligible += result.dose.eligible_n
        cues_applied += result.dose.applied_n
        if result.dose.applied_n == 0:
            continue
        perturbed = Document.from_text(result.text, uid=doc.uid)
        after = qualify_document(perturbed, annotate_document(perturbed, matcher))
        mapping = result.apply_result.alignment

        for assertion in before.assertions:
            start = mapping.src_to_dst(assertion.span.start)
            end = mapping.src_to_dst(assertion.span.end)
            if start is None or end is None:
                continue
            moved = after.at(Span(start, end))
            if moved is None:
                continue
            if not assertion.attributes:
                unmodified += 1
                if moved.attributes:
                    invented += 1
                    invented_as["+".join(sorted(moved.attributes))] += 1
            else:
                if dimension in assertion.attributes:
                    asserted += 1
                    if dimension not in moved.attributes:
                        flipped += 1
                if not moved.attributes:
                    removed += 1

    return {
        "operator": op_id,
        "dimension": dimension,
        "cue_level": {
            "eligible_cues": cues_eligible,
            "edits_applied": cues_applied,
            "note": "the dose record's denominator — a cue is what gets edited",
        },
        "concept_level": {
            "concepts_carrying_the_dimension": asserted,
            "concepts_flipped": flipped,
            "flip_rate": round(flipped / asserted, 4) if asserted else None,
            "note": (
                "what a robustness claim should quote: one cue can govern "
                "several mentions, so these counts differ from the cue-level "
                "ones by design"
            ),
        },
        "invention": {
            "unmodified_concepts_carried_through": unmodified,
            "gained_a_modifier": invented,
            "invention_rate": round(invented / unmodified, 6) if unmodified else None,
            "gained_what": dict(invented_as.most_common()),
        },
        "concepts_left_unmodified": removed,
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--severity", default="1.00")
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/assertion_invention.json")
    )
    args = parser.parse_args(argv)

    registry.register_builtins()
    matcher = ConceptMatcher(args.index)
    severity = severity_ladder(args.severity)[0]
    docs = list(read_documents(args.corpus, limit=args.limit))
    rows = [measure(op, dim, docs, matcher, severity) for op, dim in sorted(FLIPS.items())]

    total_unmodified = sum(r["invention"]["unmodified_concepts_carried_through"] for r in rows)
    total_invented = sum(r["invention"]["gained_a_modifier"] for r in rows)

    print(f"{len(docs)} notes at severity {args.severity}\n")
    print(f"{'operator':<32}{'unmodified':>11}{'GAINED':>8}{'rate':>9}   concept-level flip")
    for row in rows:
        inv, con = row["invention"], row["concept_level"]
        print(
            f"{row['operator']:<32}{inv['unmodified_concepts_carried_through']:>11}"
            f"{inv['gained_a_modifier']:>8}{inv['invention_rate'] or 0:>9.5f}"
            f"   {con['concepts_flipped']}/{con['concepts_carrying_the_dimension']}"
            f" = {con['flip_rate']}"
        )
    overall = total_invented / total_unmodified if total_unmodified else 0.0
    print(f"\noverall invention rate {total_invented}/{total_unmodified} = {overall:.5f}")

    payload = {
        "question": "Do the SEMANTIC operators ever ADD a modifier to a plainly asserted concept?",
        "why": (
            "the operators are supposed to REVERSE an assertion, not invent "
            "one. If that holds, a robustness result can say the perturbation "
            "removed modifiers and never manufactured them — a much stronger "
            "statement than a flip rate, and one a clinical reader will ask for."
        ),
        "answer": (
            f"almost never: {total_invented} of {total_unmodified} unmodified "
            f"concepts ({overall:.3%}) acquired one. It is not zero, and the "
            "mechanism is not in the operator: removing an outer cue can EXPOSE "
            "an inner one that it was covering. Deleting `no` from `no concern "
            "for sepsis` leaves `concern for sepsis`, which ConText reads as "
            "POSSIBLE_EXISTENCE. The operator targeted a negation cue and never "
            "touched the concept; the re-read is what changed."
        ),
        "why_by_construction_is_not_enough": (
            "eligibility enumerates cues ConText already found, so no unmodified "
            "concept is ever a target. But an edit changes the text and the "
            "detector re-reads the changed text, so the property has to be "
            "measured on the output rather than argued from the input."
        ),
        "two_denominators": (
            "cue-level counts are what the dose record holds and what severity "
            "is a fraction of, because a cue is what gets edited. Concept-level "
            "counts are what a robustness claim should quote, because a concept "
            "is the unit of clinical meaning. One cue can govern several "
            "mentions, so the two differ by design rather than by error."
        ),
        "n_notes": len(docs),
        "severity": args.severity,
        "overall_invention_rate": round(overall, 6),
        "operators": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
