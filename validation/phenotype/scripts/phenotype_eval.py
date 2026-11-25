#!/usr/bin/env python
"""Do we find a declared phenotype's evidence? Measured against expert spans.

The validation the phenotype layer owed and did not have. `docs/targeting-design.md`
argued that phenotype targeting needs **set membership** rather than general
linking, but listed "we find a declared phenotype's evidence" as *not yet
measured*. This measures it.

Method: declare a phenotype as a seed SNOMED concept plus its ``isa``
descendants, take the gold spans an expert annotated with a concept in that
closure, and ask what fraction our matcher recovers — first as text (span
recall), then as text carrying a concept inside the set (set recall).

The gap between the two is the cost of concept-assignment error stated in the
units that matter, and set recall is the number that bounds the vacuous-zero
failure of ``phenotype_scope=protect``.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Any

from robustehr.concepts import hierarchy
from robustehr.concepts.matcher import ConceptMatcher, MatcherConfig
from robustehr.concepts.pipeline import annotate_document
from robustehr.document import Document
from robustehr.eval import phenotype as ph
from robustehr.eval import snomed_el


def declared_phenotypes() -> tuple[tuple[str, tuple[str, ...], int | None], ...]:
    """Seeds from ``phenotypes.yaml``, which is the single source of truth.

    This list used to be a second copy, hardcoded here. Two copies of a seed set
    is the sort of drift that produces a `measured_set_recall` in the shipped
    definition that was never measured on the seed it now sits beside.

    The per-phenotype depth travels with the seeds for the same reason: measuring
    `pulmonary_embolism` at the file-wide depth would report the 9,712-concept
    blow-up its declared bound exists to prevent.
    """
    from robustehr.concepts.phenotype import load_definitions

    return tuple((name, d.seeds, d.max_depth) for name, d in load_definitions().items())


def parse_seed(spec: str) -> tuple[str, tuple[str, ...], int | None]:
    """``name=code[,code…]`` — a candidate phenotype, measured before it is declared.

    The order this package wants: choose a seed, **measure its recall**, then
    declare it in `phenotypes.yaml` with that number beside it. Declaring first
    and measuring later is how a set ships with a recall nobody checked, and the
    definition file's own contract — every protect-mode result is conditional on
    that number — makes it the one thing that must not be guessed.
    """
    name, _, codes = spec.partition("=")
    seeds = tuple(c.strip() for c in codes.split(",") if c.strip())
    if not name or not seeds:
        raise argparse.ArgumentTypeError(f"expected name=code[,code], got {spec!r}")
    return name, seeds, None


def measure(
    corpus: snomed_el.GoldCorpus,
    pheno: ph.Phenotype,
    predictions: dict[str, list[tuple[Any, str]]],
    reference_codes: frozenset[str] | None = None,
) -> ph.PhenotypeScore:
    """Span and set recall for one phenotype over the gold corpus.

    ``predictions`` maps note id to (span, CUI) so the matcher runs once for all
    phenotypes rather than once per phenotype — the notes are the expensive
    part, and the phenotypes only differ in which spans they claim.
    """
    gold = ph.evidence_spans(corpus, pheno)
    span_found = set_found = 0
    for g in gold:
        overlapping = [(s, cui) for s, cui in predictions.get(g.note_id, ()) if s.overlaps(g.span)]
        if not overlapping:
            continue
        span_found += 1
        if any(cui in pheno.concept_cuis for _, cui in overlapping):
            set_found += 1

    # The other direction: what WE claimed. Without it an over-broad closure
    # scores well by claiming everything — see PhenotypeScore.set_precision.
    #
    # The answer key is `reference_codes`, the seed's SNOMEDCT_US isa closure,
    # NOT `pheno.concept_codes`. Scoring against the set being tested is
    # circular and silently forgives exactly the blow-up this measure exists to
    # catch. Falling back to the phenotype's own codes keeps the function usable
    # without a reference, and the caller says which it passed.
    key = reference_codes if reference_codes is not None else pheno.concept_codes
    by_note: dict[str, list[Any]] = {}
    for g in corpus.spans:
        by_note.setdefault(g.note_id, []).append(g)
    claimed = claimed_correct = 0
    for note_id, mentions in predictions.items():
        annotated = by_note.get(note_id, ())
        for span, cui in mentions:
            if cui not in pheno.concept_cuis:
                continue
            claimed += 1
            if any(g.span.overlaps(span) and g.concept_id in key for g in annotated):
                claimed_correct += 1

    return ph.PhenotypeScore(
        phenotype=pheno.name,
        concept_set_size=pheno.size,
        gold_spans=len(gold),
        span_found=span_found,
        set_found=set_found,
        claimed=claimed,
        claimed_correct=claimed_correct,
    )


def union_phenotype(
    disorder: ph.Phenotype,
    definition: Any,
    edges: Any,
    maps: tuple[dict[str, list[str]], dict[str, list[str]]],
) -> ph.Phenotype:
    """The set a ``pheno=X`` target actually selects: every facet, unioned.

    Built here rather than imported because `eval.phenotype.Phenotype` is a
    different type from the runtime one — the eval half deliberately keeps its
    own, so a change to the runtime layer cannot silently move the yardstick.
    """
    from robustehr.concepts import facets

    code_to_cuis, cui_to_codes = maps
    seed_cuis = frozenset(c for code in definition.seeds for c in code_to_cuis.get(code, ()))
    vetting = facets.load_vetting().get(disorder.name, {})
    medication = facets.medications(
        seed_cuis,
        disorder.concept_cuis,
        edges,
        declared=definition.medication_seeds,
        vetted=vetting.get("medication"),
    ).cuis
    proposed = frozenset(
        c for cuis in facets.load_proposals().get(disorder.name, {}).values() for c in cuis
    )
    kept_proposed = vetting.get("proposed")
    if kept_proposed is not None:
        proposed &= kept_proposed
    closure = facets.load_closure().get(disorder.name, frozenset()) & vetting.get(
        "closure", frozenset()
    )
    cuis = frozenset(disorder.concept_cuis) | medication | proposed | closure
    codes = {code for cui in cuis for code in cui_to_codes.get(cui, ())}
    return ph.Phenotype(
        name=disorder.name,
        seed_codes=disorder.seed_codes,
        concept_cuis=cuis,
        concept_codes=frozenset(codes | set(disorder.concept_codes)),
    )


def _macro(scores: list[ph.PhenotypeScore]) -> dict[str, Any]:
    """Unweighted means over the phenotypes that have gold evidence at all.

    Phenotypes with zero gold spans are excluded rather than scored zero: an
    absent condition is a property of the corpus, and averaging it in would
    report a matcher failure that did not happen.
    """

    def mean(attribute: str) -> float | None:
        values = [v for s in scores if (v := getattr(s, attribute)) is not None]
        return round(sum(values) / len(values), 4) if values else None

    return {
        "span_recall": mean("span_recall"),
        "set_recall": mean("set_recall"),
        "set_precision": mean("set_precision"),
        "set_f1": mean("set_f1"),
        "measured_over": len(scores),
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument(
        "--reference-isa",
        type=Path,
        default=Path("data/umls_isa.json"),
        help="SNOMEDCT_US isa only — the independent answer key for set_precision. "
        "Must not be the same edge set as --isa, which is what is under test",
    )
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--split", default="test")
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--overlap", default="score", choices=("score", "length"))
    parser.add_argument("--trim-affixes", action="store_true")
    parser.add_argument(
        "--prefer-snomed",
        action="store_true",
        help="break similarity ties toward SNOMED-linked concepts. A concept "
        "with no SNOMED code cannot be in a SNOMED-seeded phenotype set, so at "
        "equal similarity preferring one costs nothing.",
    )
    parser.add_argument(
        "--seed",
        type=parse_seed,
        action="append",
        metavar="NAME=CODE[,CODE]",
        help="measure a CANDIDATE phenotype that is not declared yet. Repeatable. "
        "Given any --seed, only the candidates are measured, so a new set can be "
        "compared against alternatives before one is written into phenotypes.yaml",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    corpus = snomed_el.load(args.root, limit=args.limit)
    if args.split:
        corpus = corpus.split(args.split)

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = ph.load_maps(args.root)
    from robustehr.concepts import facets
    from robustehr.concepts.phenotype import load_definitions

    definitions = load_definitions()
    edges = facets.load() if facets.DEFAULT_EDGES.exists() else None
    selected = tuple(args.seed) if args.seed else declared_phenotypes()
    phenotypes = [
        ph.declare(name, seeds, isa, code_to_cuis, cui_to_codes, max_depth=depth or args.depth)
        for name, seeds, depth in selected
    ]

    config = MatcherConfig(
        overlapping_criteria=args.overlap,
        trim_affixes=args.trim_affixes,
        preferred_cuis=frozenset(cui_to_codes) if args.prefer_snomed else None,
    )
    matcher = ConceptMatcher(args.index, config)
    predictions: dict[str, list[tuple[Any, str]]] = {}
    for note_id, text in sorted(corpus.notes.items()):
        doc = Document.from_text(text, uid=note_id)
        predictions[note_id] = [(m.span, m.cui) for m in annotate_document(doc, matcher).mentions]

    # The independent answer key for precision: the same seeds expanded through
    # SNOMEDCT_US `isa` alone. `--isa` carries the MTH RN edges under test, so
    # it cannot also be the reference.
    snomed_only = hierarchy.load(args.reference_isa)
    reference = {
        name: ph.declare(
            name, seeds, snomed_only, code_to_cuis, cui_to_codes, max_depth=depth or args.depth
        ).concept_codes
        for name, seeds, depth in selected
    }
    scores = [measure(corpus, p, predictions, reference[p.name]) for p in phenotypes]

    # The DISORDER facet is what `scores` measures, and it is no longer what a
    # `pheno=X` target selects — that is the union across facets. Publishing
    # only the disorder number would describe a set the pipeline stopped using.
    #
    # RECALL is measurable for the union and precision is NOT, which is stated
    # rather than fudged. Precision needs an answer key independent of the set
    # being scored, and the only one available is the seed's SNOMEDCT_US `isa`
    # closure — a *disease* closure, which no medication or procedure concept
    # can ever fall inside. Scored against it the union reads 0.000 for five
    # phenotypes: that is the key being wrong for the set, not the set being
    # imprecise, and calling it a "lower bound" would dress up a broken
    # measurement as a conservative one. So union precision is reported as null
    # with this reason, and the disorder facet remains the specificity anchor.
    union_scores: list[ph.PhenotypeScore] = []
    if not args.seed and edges is not None:
        union_scores = [
            measure(
                corpus,
                union_phenotype(p, definitions[p.name], edges, (code_to_cuis, cui_to_codes)),
                predictions,
                reference[p.name],
            )
            for p in phenotypes
        ]
    measurable = [s for s in scores if s.gold_spans]
    payload = {
        "question": "Do we find the evidence an expert annotated for a declared phenotype?",
        "method": (
            "phenotype = seed SNOMED concept + isa descendants (SNOMEDCT_US, depth "
            f"{args.depth}). Gold spans whose annotated concept falls in that closure "
            "are the phenotype's evidence. span_recall = we found the text; "
            "set_recall = we found it and assigned a concept inside the set."
        ),
        "why_two_recalls": (
            "span_recall bounds what a corruption operator can reach; set_recall "
            "bounds whether phenotype_scope is correct. A mention missed under "
            "protect mode is never protected, and the run still reports "
            "evidence_touch=0 because measurement and protection read the same "
            "span set — set_recall is what makes that zero non-vacuous."
        ),
        "config": config.canon(),
        "source": "candidate seeds (--seed)" if args.seed else "phenotypes.yaml",
        "seeds": {
            name: {"codes": list(seeds), "max_depth": depth or args.depth}
            for name, seeds, depth in selected
        },
        "notes": len(corpus.notes),
        "gold_spans_total": len(corpus.spans),
        "phenotypes": [s.to_row() for s in scores],
        "phenotypes_union": [
            {**s.to_row(), "set_precision": None, "set_f1": None} for s in union_scores
        ],
        "macro_union": {
            k: v
            for k, v in _macro([s for s in union_scores if s.gold_spans]).items()
            if k not in ("set_precision", "set_f1")
        },
        "two_sets": (
            "`phenotypes` scores the DISORDER facet, which is what the shipped "
            "measured_set_recall describes. `phenotypes_union` scores what a "
            "pheno=X target actually selects — every facet unioned. Precision "
            "for the union keeps the same independent answer key (the SNOMED "
            "isa closure of the seed), so it is a strict LOWER bound: a "
            "medication concept cannot appear under a disease seed's closure, "
            "so union PRECISION is not measurable here and is reported null "
            "rather than as a near-zero that would read as imprecision. The "
            "disorder facet remains the specificity anchor."
        ),
        "macro": _macro(measurable),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
