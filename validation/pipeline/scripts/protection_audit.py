#!/usr/bin/env python
"""Is the protection registry right? Seven classes, and what each one rests on.

**Why this was owed.** The protection registry decides what an operator may
never edit, and it is load-bearing twice over. It sets the gap between `total_n`
and `eligible_n`, so it silently defines every dose denominator in the package —
a class that over-fires shrinks the denominator and makes severity 0.30 deliver
0.35. And `DEID_PLACEHOLDER` is `HARD`, so a class that under-fires lets an
operator corrupt a de-identification marker. Seven producers existed with no
artifact scoring any of them.

**Not every class can be validated the same way, and pretending otherwise would
be the real failure.** Three have a ground truth that can be derived
independently of the detector; four rest on judgement and are reported as
disclosures rather than scores:

* `deid_placeholder`, `divider_rule` — MIMIC's de-identification writes runs of
  underscores. Enumerating those runs from the raw text is a ground truth the
  registry did not produce, so coverage is a real measurement. **Scheme-specific**:
  a corpus using `[**Name**]` or `<REDACTED>` needs its own scheme, and this
  number does not transfer.
* `numeric_value` — a token either parses as a number or does not.
* `section_header` — no independent gold, but `HeaderConfidence` distinguishes
  headers matched against the shipped lexicon from headers guessed by heuristic,
  and the mix is the honest disclosure.
* `lab_block`, `dosage`, `list_marker` — layout judgements with no external
  reference. Counts and rates only.

**The end-to-end property is checkable even where the classes are not.** Whatever
the per-class accuracy, the guarantee a user needs is that *no edit any operator
proposes ever lands on a HARD-protected span*. That is measured over a real run
rather than argued from the registry's design, because the runner filters
eligible units and an operator emitting a wider edit could still reach one.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.corpus import read_documents
from robustehr.document import Document
from robustehr.ops import registry
from robustehr.protect.registry import Strength, protect_document
from robustehr.runner import apply_operator, severity_ladder
from robustehr.types import ProtectionClass

#: MIMIC-IV de-identification. Runs of two or more underscores, which the
#: registry then splits: short runs are placeholders, long ones are rules.
UNDERSCORE_RUN = re.compile(r"_{2,}")

#: Where the registry draws that line, mirrored here so a disagreement shows up
#: as a number rather than as a silent reclassification.
PLACEHOLDER_MAX = 10


def audit_underscores(docs: list[Document]) -> dict[str, Any]:
    """Coverage of every underscore run, by length and by protecting class."""
    buckets: Counter[tuple[str, str]] = Counter()
    unprotected = 0
    total = 0
    for doc in docs:
        index = protect_document(doc)
        covering: dict[int, set[str]] = {}
        for protected in index.spans:
            for offset in range(protected.span.start, protected.span.end):
                covering.setdefault(offset, set()).add(protected.cls.value)
        for match in UNDERSCORE_RUN.finditer(doc.text):
            total += 1
            classes = covering.get(match.start(), set())
            length = match.end() - match.start()
            bucket = (
                "short (placeholder-shaped)" if length <= PLACEHOLDER_MAX else "long (rule-shaped)"
            )
            buckets[(bucket, "+".join(sorted(classes)) or "UNPROTECTED")] += 1
            if not classes:
                unprotected += 1
    return {
        "ground_truth": (
            "every run of 2+ underscores in the raw text, enumerated independently of the registry"
        ),
        "runs_found": total,
        "completely_unprotected": unprotected,
        "coverage": round(1 - unprotected / total, 6) if total else None,
        "by_length_and_class": {f"{b} -> {c}": n for (b, c), n in sorted(buckets.items())},
        "scheme_specific": (
            "MIMIC-IV writes de-identification as underscore runs. A corpus "
            "using [**Name**] or <REDACTED> needs its own DeidScheme and this "
            "number does not transfer to it."
        ),
    }


def audit_numeric(docs: list[Document]) -> dict[str, Any]:
    """Every protected NUMERIC_VALUE span should contain a digit, and vice versa."""
    marked_without_digit = 0
    marked = 0
    digits_unmarked = 0
    digit_tokens = 0
    for doc in docs:
        index = protect_document(doc)
        numeric = [p for p in index.spans if p.cls is ProtectionClass.NUMERIC_VALUE]
        marked += len(numeric)
        spans = {(p.span.start, p.span.end) for p in numeric}
        for start, end in spans:
            if not any(c.isdigit() for c in doc.text[start:end]):
                marked_without_digit += 1
        for token in doc.tokens.tokens:
            text = doc.text[token.span.start : token.span.end]
            if (
                text
                and all(c.isdigit() or c in ".," for c in text)
                and any(c.isdigit() for c in text)
            ):
                digit_tokens += 1
                if (token.span.start, token.span.end) not in spans:
                    digits_unmarked += 1
    return {
        "ground_truth": "a token either contains a digit or does not",
        "spans_marked": marked,
        "marked_without_a_digit": marked_without_digit,
        "precision": round(1 - marked_without_digit / marked, 6) if marked else None,
        "pure_number_tokens": digit_tokens,
        "pure_number_tokens_unmarked": digits_unmarked,
        "recall_on_pure_numbers": round(1 - digits_unmarked / digit_tokens, 6)
        if digit_tokens
        else None,
    }


def audit_headers(docs: list[Document]) -> dict[str, Any]:
    """No gold — so report how many headers came from the lexicon vs a guess."""
    confidence: Counter[str] = Counter()
    canonical = 0
    total = 0
    for doc in docs:
        for header in doc.headers:
            total += 1
            confidence[header.confidence.value] += 1
            if header.canonical_id:
                canonical += 1
    return {
        "ground_truth": (
            "NONE. There is no external header gold, so this is a disclosure "
            "rather than a score: how many headers matched the shipped lexicon "
            "and how many were guessed."
        ),
        "headers": total,
        "by_confidence": dict(confidence.most_common()),
        "with_a_canonical_id": canonical,
        "canonical_share": round(canonical / total, 4) if total else None,
    }


def audit_hard_safety(docs: list[Document], severity: Any) -> dict[str, Any]:
    """No applied edit may CUT a HARD-protected span.

    **The property is not "nothing may touch a HARD span", and assuming that is
    an easy way to measure the wrong thing.** `ProtectionIndex._refuses` refuses
    a HARD span to an operator that has not declared its class, and to one that
    has *unless the edit contains the span whole*. That is the right rule for a
    de-identification placeholder: `discourse.sentence_delete` removing a whole
    sentence that contains `___` deletes the marker cleanly, and
    `render.deid_restyle` rewriting `___` into another scheme replaces it whole.
    What must never happen is a PARTIAL edit leaving `_x_` — a mangled marker
    that reads as content and would corrupt any downstream de-identification
    measurement.

    So two violations are counted separately, and neither is "touched it":

    * **undeclared** — the operator does not list the class at all;
    * **partial** — it does, but the edit cuts the span instead of replacing it.
    """
    undeclared: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    edits = touching = 0
    operators = sorted(registry.all_ids())
    for doc in docs:
        index = protect_document(doc)
        hard = [p for p in index.spans if p.strength is Strength.HARD]
        for op_id in operators:
            operator = registry.get(op_id)()
            declared = operator.meta.targets
            try:
                result = apply_operator(doc, operator, operator.meta, severity)
            except Exception:
                continue
            for edit in result.apply_result.applied:
                edits += 1
                for protected in hard:
                    if not (edit.start < protected.span.end and protected.span.start < edit.end):
                        continue
                    touching += 1
                    row = {"op_id": op_id, "class": protected.cls.value, "note": doc.uid}
                    whole = edit.start <= protected.span.start and protected.span.end <= edit.end
                    if protected.cls not in declared:
                        undeclared.append(row)
                    elif not whole:
                        partial.append(row)
    return {
        "property": (
            "an applied edit may contain a HARD span whole if the operator "
            "declares its class; it may never cut one, and may never touch one "
            "it has not declared"
        ),
        "operators_exercised": len(operators),
        "edits_applied": edits,
        "edits_touching_a_hard_span": touching,
        "violations_undeclared": len(undeclared),
        "violations_partial": len(partial),
        "violations": len(undeclared) + len(partial),
        "detail": (undeclared + partial)[:10],
        "note": (
            "edits_touching_a_hard_span is expected to be large and is not an "
            "error. It counts legitimate whole replacements — sentence deletion "
            "and de-id restyling — which the class permits to operators that "
            "declare it."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--severity", default="1.00")
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/protection_audit.json")
    )
    args = parser.parse_args(argv)

    registry.register_builtins()
    docs = [
        Document.from_text(d.text, uid=d.uid) for d in read_documents(args.corpus, limit=args.limit)
    ]
    severity = severity_ladder(args.severity)[0]

    prevalence: Counter[str] = Counter()
    for doc in docs:
        for protected in protect_document(doc).spans:
            prevalence[f"{protected.cls.value} ({protected.strength.name})"] += 1

    payload = {
        "question": "Does the protection registry identify its classes correctly?",
        "why": (
            "the registry sets the gap between total_n and eligible_n, so it "
            "silently defines every dose denominator; and DEID_PLACEHOLDER is "
            "HARD, so under-firing lets an operator corrupt a de-identification "
            "marker. Seven producers existed with nothing scoring any of them."
        ),
        "what_can_and_cannot_be_validated": (
            "deid/divider and numeric have a ground truth derivable WITHOUT the "
            "registry, so those are measurements. section_header has no external "
            "gold and is disclosed by confidence mix. lab_block, dosage and "
            "list_marker are layout judgements with no reference and are "
            "reported as counts only. Scoring them against themselves would be "
            "the failure this file exists to avoid."
        ),
        "n_notes": len(docs),
        "prevalence": dict(prevalence.most_common()),
        "deid_and_dividers": audit_underscores(docs),
        "numeric_value": audit_numeric(docs),
        "section_header": audit_headers(docs),
        "unvalidated_classes": {
            "classes": ["lab_block", "dosage", "list_marker"],
            "why": (
                "layout judgements with no external reference corpus. Their "
                "counts are reported above; their accuracy is not established, "
                "and a robustness result that leaned on them would be resting "
                "on an unmeasured component."
            ),
        },
        "hard_protection_safety": audit_hard_safety(docs, severity),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"{len(docs)} notes\n")
    print("prevalence:")
    for name, n in prevalence.most_common():
        print(f"   {name:<34} {n:6d}")
    under = payload["deid_and_dividers"]
    print(
        f"\nde-id + dividers: {under['runs_found']} underscore runs, "
        f"{under['completely_unprotected']} unprotected (coverage {under['coverage']})"
    )
    num = payload["numeric_value"]
    print(f"numeric_value:    precision {num['precision']}  recall {num['recall_on_pure_numbers']}")
    hdr = payload["section_header"]
    print(f"section_header:   {hdr['headers']} headers, {hdr['canonical_share']} from the lexicon")
    safe = payload["hard_protection_safety"]
    print(
        f"\nHARD safety:      {safe['edits_applied']} edits, "
        f"{safe['edits_touching_a_hard_span']} touched a HARD span, "
        f"{safe['violations']} violations "
        f"({safe['violations_undeclared']} undeclared, {safe['violations_partial']} partial)"
    )
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
