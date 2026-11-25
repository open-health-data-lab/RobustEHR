#!/usr/bin/env python
"""Do the SEMANTIC operators actually flip the dimension they claim to?

The gold says whether the detector *reads* a dimension correctly. This says
whether the operator *changes* it — a different question, and one nothing else in
the package answers. An operator can be eligible, dosed and applied, and still
leave the assertion exactly where it was; the edit script would look perfectly
healthy and the perturbation would be a no-op.

**Injection-recovery.** The same dual-instrument design the package already uses
for `input.typo` against the Document Quality Profile's misspelling estimator:
inject a known change, then measure whether the independent detector recovers it.

1. qualify the note, and note which spans carry dimension *D*;
2. apply the operator that flips *D*;
3. re-qualify the perturbed note, following each span through the alignment
   because these edits change lengths;
4. ask what moved.

**Three quantities, and the second and third matter as much as the first:**

* **flip rate** — of spans carrying *D* before, the share that lost it. This is
  the operator doing its job.
* **collateral** — spans whose *other* dimensions changed. A negation flip that
  also clears `historical` is over-editing, and the dose accounting would not
  notice: it counts edits applied, not consequences.
* **dose fidelity** — achieved against requested `k`, already tracked by the
  runner and reported here so a low flip rate can be attributed to the operator
  rather than to nothing having been applied.

Runs on the **shipped** composition — `qualify_document`, this package's sentence
boundaries — rather than a hand-assembled one. Measuring a configuration nothing
runs is the failure that made every stage-3 headline describe the wrong pipeline.
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

#: Operator -> the dimension it is supposed to flip.
FLIPS = {
    "semantic.negation_flip": "negated",
    "semantic.uncertainty_flip": "uncertain",
    "semantic.temporality_shift": "historical",
    "semantic.experiencer_shift": "family",
}

#: The LLM-backed arm, on the same units and the same dimensions. Measured
#: beside the table arm rather than instead of it: the question is not whether a
#: sentence rewrite works, it is whether it works BETTER than a cue substitution
#: on the same cues, and at what collateral cost.
FLIPS_LLM = {f"{op}_llm": dim for op, dim in FLIPS.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--arms",
        default="table",
        choices=["table", "llm", "both"],
        help="the llm arm needs ROBUSTEHR_LLM_MODEL and a key, and calls out "
        "once per sentence carrying a cue. Responses cache, so a second run is "
        "offline and free",
    )
    parser.add_argument("--severity", default="1.00")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def table_edits(doc: Any, op_id: str, severity: Any) -> set[tuple[int, int, str]]:
    """What the deterministic arm would have proposed on this document.

    Used to estimate how often the LLM arm fell back. It is an ESTIMATE and
    over-counts: an LLM that independently produces the table's rewrite is
    indistinguishable here from one that failed a guard. It bounds the fallback
    rate from above, which is the direction that matters.
    """
    if not op_id.endswith("_llm"):
        return set()
    table_op = registry.get(op_id.removesuffix("_llm"))()
    result = apply_operator(doc, table_op, table_op.meta, severity)
    return {(e.start, e.end, e.replacement) for e in result.apply_result.applied}


def measure(
    op_id: str, dimension: str, docs: list[Any], matcher: Any, severity: Any
) -> dict[str, Any]:
    """Flip and collateral counts for one operator over the corpus."""
    operator = registry.get(op_id)()
    carried = flipped = 0
    other_changed = unaffected_changed = 0
    compared = lost = 0
    eligible = applied = 0
    matching_table = 0
    transitions: Counter[str] = Counter()

    for doc in docs:
        before = qualify_document(doc, annotate_document(doc, matcher))
        if not len(before):
            continue
        result = apply_operator(doc, operator, operator.meta, severity)
        eligible += result.dose.eligible_n
        applied += result.dose.applied_n
        if baseline := table_edits(doc, op_id, severity):
            matching_table += sum(
                1
                for e in result.apply_result.applied
                if (e.start, e.end, e.replacement) in baseline
            )
        if result.dose.applied_n == 0:
            continue
        perturbed = Document.from_text(result.text, uid=doc.uid)
        after = qualify_document(perturbed, annotate_document(perturbed, matcher))
        mapping = result.apply_result.alignment

        for assertion in before.assertions:
            start = mapping.src_to_dst(assertion.span.start)
            end = mapping.src_to_dst(assertion.span.end)
            if start is None or end is None:
                lost += 1
                continue
            moved = after.at(Span(start, end))
            if moved is None:
                lost += 1
                continue
            compared += 1
            had = dimension in assertion.attributes
            has = dimension in moved.attributes
            if had:
                carried += 1
                if not has:
                    flipped += 1
                    transitions[f"{assertion.canon()} -> {moved.canon()}"] += 1
            # Collateral: anything that moved other than the target
            # dimension on a span that carried it.
            others_before = assertion.attributes - {dimension}
            others_after = moved.attributes - {dimension}
            if others_before != others_after:
                if had:
                    other_changed += 1
                else:
                    unaffected_changed += 1

    return {
        "operator": op_id,
        "dimension": dimension,
        "eligible_cues": eligible,
        "edits_applied": applied,
        "spans_compared": compared,
        "not_realignable": lost,
        "spans_carrying_dimension": carried,
        "spans_flipped": flipped,
        "flip_rate": round(flipped / carried, 4) if carried else None,
        "collateral_on_flipped_spans": other_changed,
        "collateral_on_untouched_spans": unaffected_changed,
        "collateral_rate": round((other_changed + unaffected_changed) / compared, 4)
        if compared
        else None,
        "top_transitions": dict(transitions.most_common(5)),
        **(
            {
                "edits_matching_the_table_arm": matching_table,
                "fallback_rate_upper_bound": round(matching_table / applied, 4)
                if applied
                else None,
                "fallback_note": (
                    "an UPPER bound on how often a guard refused the rewrite. An "
                    "LLM that independently produces the table's edit counts "
                    "here too, so the true fallback rate is at most this."
                ),
            }
            if op_id.endswith("_llm")
            else {}
        ),
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    args = build_parser().parse_args(argv)

    registry.register_builtins()
    matcher = ConceptMatcher(args.index)
    severity = severity_ladder(args.severity)[0]
    docs = list(read_documents(args.corpus, limit=args.limit))
    wanted = dict(FLIPS)
    if args.arms in {"llm", "both"}:
        wanted.update(FLIPS_LLM)
    if args.arms == "llm":
        wanted = dict(FLIPS_LLM)
    rows = [measure(op, dim, docs, matcher, severity) for op, dim in sorted(wanted.items())]

    payload = {
        "question": "Do the SEMANTIC operators change the dimension they claim to?",
        "why": (
            "the gold says whether the detector reads a dimension correctly; "
            "this says whether the operator changes it. An operator can be "
            "eligible, dosed and applied and still leave the assertion where it "
            "was — the edit script would look healthy and the perturbation "
            "would be a no-op."
        ),
        "design": (
            "injection-recovery, the same dual-instrument shape used for "
            "input.typo against the DQP misspelling estimator: inject a known "
            "change, then ask whether the independent detector recovers it."
        ),
        "composition": (
            "qualify_document on this package's sentence boundaries — the "
            "shipped configuration, not a hand-assembled one."
        ),
        "notes": len(docs),
        "severity": args.severity,
        "operators": rows,
        "how_to_read": (
            "flip_rate near 1.0 means the operator does what it says. "
            "collateral_rate is the cost: spans whose *other* dimensions moved, "
            "which dose accounting cannot see because it counts edits applied "
            "rather than consequences. A high flip rate with high collateral is "
            "an operator that works and over-reaches, and the two must be read "
            "together. Read every row beside the detector's reliability for that "
            "dimension in assertion_gold_mimic.json: an operator anchored on a "
            "detector that mislabels cannot be more trustworthy than the label."
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
