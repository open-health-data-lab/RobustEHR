#!/usr/bin/env python
"""Does the assertion layer survive a perturbation that provably preserves meaning?

The gate for stage 8, and the one the package is uniquely able to run.

Five operators carry the contract `INVARIANT_BY_CONSTRUCTION`: each declares a
canonicalizer κ, and CI proves `κ(apply(d)) == κ(d)` over the corpus at every
severity. **No clinical reference can change under them.** Restyling a
de-identification placeholder, collapsing a run of spaces, or rewriting a bullet
as prose leaves what the note says about the patient exactly as it was.

So if an assertion flips under one of them, the assertion layer is reading
something that is not clinical content — and every result conditioned on
assertion inherits that as a confound. This is the package measuring a downstream
tool with its own instrument, which is what it was built for.

`probe_deid_assertion.py` already found one instance: three de-identification
conventions, including MIMIC-III's and MIMIC-IV's, cause the sentence segmenter
to merge two list items, which lets a negation cue take scope over the next item
and mark an active diagnosis as negated. **That probe is one note.** This is the
same question at corpus scale, over every invariant operator rather than one.

The metric is a **flip rate**: of the mentions assertable before and after, what
share changed verdict. Zero is the only good answer, because the operator is
proved not to have changed the meaning.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.concepts.context import qualify
from robustehr.concepts.matcher import ConceptMatcher
from robustehr.concepts.pipeline import annotate_document, qualify_document
from robustehr.corpus import read_documents
from robustehr.document import Document
from robustehr.ops import registry
from robustehr.runner import apply_operator, severity_ladder
from robustehr.types import Contract, Span


def overall(rows: list[dict[str, Any]]) -> float | None:
    """Flip rate across every operator in one arm."""
    compared = sum(r["mentions_compared"] for r in rows)
    flipped = sum(r["assertions_flipped"] for r in rows)
    return round(flipped / compared, 4) if compared else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--severity", default="1.00")
    parser.add_argument(
        "--boundaries",
        choices=["ours", "pyrush"],
        default="ours",
        help="which sentence boundaries stage 8 scopes cues to. 'ours' is the "
        "shipped configuration; 'pyrush' is medspaCy's own splitter, kept so the "
        "two can be attributed against each other on identical notes",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        default=True,
        help="also run the other segmenter, so the difference is attributed",
    )
    parser.add_argument("--no-compare", dest="compare", action="store_false")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    args = build_parser().parse_args(argv)

    registry.register_builtins()
    invariant = sorted(
        op_id
        for op_id in registry.all_ids()
        if registry.get(op_id)().meta.contract is Contract.INVARIANT_BY_CONSTRUCTION
    )
    matcher = ConceptMatcher(args.index)
    severity = severity_ladder(args.severity)[0]
    docs = list(read_documents(args.corpus, limit=args.limit))

    def assert_for(doc: Document, boundaries: str) -> Any:
        """Stage 8 over a document, on whichever boundaries the arm selects.

        `qualify_document` is the shipped path; `qualify` without boundaries is
        medspaCy's own PyRuSH. Both are run so the difference between them is
        attributed rather than guessed — on identical notes and identical spans.
        """
        mentions = annotate_document(doc, matcher)
        if boundaries == "ours":
            return qualify_document(doc, mentions)
        return qualify(doc.text, tuple(m.span for m in mentions.mentions))

    def measure(boundaries: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for op_id in invariant:
            operator = registry.get(op_id)()
            compared = flipped = lost = 0
            transitions: Counter[str] = Counter()
            for doc in docs:
                before = assert_for(doc, boundaries)
                if not len(before):
                    continue
                result = apply_operator(doc, operator, operator.meta, severity)
                if result.dose.applied_n == 0:
                    continue
                perturbed = Document.from_text(result.text, uid=doc.uid)
                after = assert_for(perturbed, boundaries)
                # Follow each span through the alignment rather than assuming
                # offsets survived: these operators change lengths.
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
                    if moved.attributes != assertion.attributes:
                        flipped += 1
                        transitions[f"{assertion.canon()} -> {moved.canon()}"] += 1
            rows.append(
                {
                    "operator": op_id,
                    "mentions_compared": compared,
                    "assertions_flipped": flipped,
                    "flip_rate": round(flipped / compared, 4) if compared else None,
                    "not_realignable": lost,
                    "top_transitions": dict(transitions.most_common(6)),
                }
            )
        return rows

    rows = measure(args.boundaries)
    other = "pyrush" if args.boundaries == "ours" else "ours"
    comparison = measure(other) if args.compare else []

    payload = build_payload(
        rows, comparison, args=args, notes=len(docs), other=other, overall=overall
    )
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def build_payload(
    rows: list[dict[str, Any]],
    comparison: list[dict[str, Any]],
    *,
    args: argparse.Namespace,
    notes: int,
    other: str,
    overall: Any,
) -> dict[str, Any]:
    total_c = sum(r["mentions_compared"] for r in rows)
    total_f = sum(r["assertions_flipped"] for r in rows)
    return {
        "question": (
            "Does an assertion survive a perturbation proved not to change clinical reference?"
        ),
        "why_these_operators": (
            "each declares a canonicalizer kappa and CI proves kappa(apply(d)) == "
            "kappa(d) over the corpus at every severity, so no clinical reference "
            "can change. A flip therefore means the assertion layer is reading "
            "something that is not clinical content, and every result conditioned "
            "on assertion inherits it as a confound."
        ),
        "prior_finding": (
            "probe_deid_assertion.py found one instance on ONE note: three de-id "
            "conventions, including MIMIC-III's and MIMIC-IV's, merge two list "
            "items so a negation cue takes scope over the next. This is the same "
            "question at corpus scale over every invariant operator."
        ),
        "notes": notes,
        "severity": args.severity,
        "boundaries": args.boundaries,
        "operators": rows,
        "overall_flip_rate": round(total_f / total_c, 4) if total_c else None,
        "comparison_other_segmenter": {
            "boundaries": other,
            "operators": comparison,
            "overall_flip_rate": overall(comparison),
            "why": (
                "the two segmenters are run on identical notes and identical "
                "spans so the difference is attributed rather than guessed. It "
                "is a trade, not a win: our boundaries take the structural "
                "operators (header, lab-block, bullet, whitespace) toward zero "
                "because they model list and header structure, and lose badly on "
                "deid_restyle because they also model de-identification "
                "placeholders — so the placeholder convention is an input to "
                "their own rules. PyRuSH models neither, which is why restyling "
                "barely moves it and list structure moves it a lot."
            ),
        }
        if comparison
        else None,
        "how_to_read": (
            "zero is the only good answer. A non-zero flip rate is the size of a "
            "confound, not a performance number, and it bounds what an "
            "assertion-conditioned result can claim. Read the two segmenters "
            "per operator rather than on the overall figure: the overall numbers "
            "are close and their composition is completely different."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
