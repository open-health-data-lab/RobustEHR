#!/usr/bin/env python
"""Generate one validation sheet per semantic category.

Generated rather than hand-written so the sheets cannot drift from
``semantic_categories.yaml``, which is the definition of record. Re-run after any
change to the taxonomy; ``--check`` fails if the checked-in files are stale,
which is what keeps CI honest.

Corpus prevalence is measured once with ``--corpus`` and persisted to
``validation/measurements/category_prevalence.json``; sheet generation then reads that
artifact. The indirection is load-bearing: CI has no corpus (the notes are
gitignored under a data-use agreement), so a sheet whose content depended on
having one could never be checked for staleness.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from robustehr.categories import Tier, load_categories

OUT_DIR = Path("validation/pipeline/categories")
OVERVIEW = Path("docs/categories.md")
PREVALENCE = Path("validation/measurements/category_prevalence.json")

#: Where each gold standard lives, so a sheet links rather than merely names it.
BENCHMARKS: dict[str, dict[str, str]] = {
    "snomed_el": {
        "name": "SNOMED CT Entity Linking Challenge",
        "url": "https://physionet.org/content/snomed-ct-entity-challenge/",
        "paper": "https://doi.org/10.1093/jamia/ocaf104",
        "corpus": "272 MIMIC-IV discharge notes",
        "size": "75,491 annotations of 6,595 concepts as released (74,808 / 6,624 as published)",
        "access": "PhysioNet credentialed",
        "notes": (
            "Six clinical annotators, ~70% double-annotated with a third "
            "adjudicating disagreements. Same corpus family as the development "
            "notes, which is why it is the primary anchor."
        ),
    },
    "n2c2_2018": {
        "name": "n2c2 2018 Track 2 (medication and ADE)",
        "url": "https://portal.dbmi.hms.harvard.edu/projects/n2c2-nlp/",
        "paper": "https://doi.org/10.1093/jamia/ocz166",
        "corpus": "MIMIC-III discharge summaries",
        "size": "~500 annotated notes",
        "access": "DBMI data-use agreement",
        "notes": (
            "Annotates drug plus strength, dosage, route, frequency, duration, "
            "reason and ADE. The only anchor covering medications."
        ),
    },
    "i2b2_2010": {
        "name": "i2b2/VA 2010 concept extraction",
        "url": "https://portal.dbmi.hms.harvard.edu/projects/n2c2-nlp/",
        "paper": "https://doi.org/10.1136/amiajnl-2011-000203",
        "corpus": "Partners, Beth Israel Deaconess and UPMC notes",
        "size": "170 training / 256 test summaries",
        "access": "DBMI data-use agreement",
        "notes": (
            "Three categories only: problem, test, treatment. `treatment` "
            "covers both procedures and drugs, so it can only ever partially "
            "anchor either."
        ),
    },
    "share_clef": {
        "name": "ShARe/CLEF eHealth 2013-2014",
        "url": "https://physionet.org/content/shareclefehealth2013/",
        "paper": "https://doi.org/10.1007/978-3-642-40802-1_24",
        "corpus": "clinical notes",
        "size": "298 notes (2013 task 1)",
        "access": "PhysioNet credentialed",
        "notes": (
            "Disorders plus ten contextual attributes. Also the corpus "
            "QuickUMLS itself was evaluated on, so it doubles as the check "
            "that our configuration reproduces published behaviour."
        ),
    },
}

TIER_BLURB = {
    Tier.ANCHORED: (
        "A gold standard adjudicates this category directly. Precision, recall "
        "and F1 can be reported against expert annotations."
    ),
    Tier.DERIVED: (
        "A semantic-type partition of an anchored parent. The parent's boundary "
        "is validated; **the split within it is not adjudicated by any corpus**. "
        "Report the parent's metrics and label this as a refinement."
    ),
    Tier.UNANCHORED: (
        "**No gold standard covers this category.** It is usable and it is "
        "labelled; it must never carry a headline claim."
    ),
}


def load_prevalence() -> dict[str, tuple[int, float]]:
    """Read the persisted measurement, if it has been taken."""
    if not PREVALENCE.exists():
        return {}
    raw = json.loads(PREVALENCE.read_text(encoding="utf-8"))
    return {k: (v["types"], v["token_share"]) for k, v in raw["categories"].items()}


def measure_prevalence(corpus: Path, limit: int) -> dict[str, tuple[int, float]]:
    from robustehr.corpus import read_documents
    from robustehr.lexicon import load_clinical_lexicon, load_morphology
    from robustehr.segment.tokens import TokenKind

    lexicon = load_clinical_lexicon(Path("data/lexicon/clinical_tokens.txt"))
    closed = load_morphology().closed_class
    freq: Counter[str] = Counter()
    for doc in read_documents(corpus, limit=limit):
        for token in doc.tokens:
            word = token.lower
            if (
                token.kind is TokenKind.WORD
                and token.is_content
                and word.isalpha()
                and word not in closed
            ):
                freq[word] += 1
    total = sum(freq.values()) or 1
    out = {}
    for name, category in load_categories().items():
        hits = sum(n for w, n in freq.items() if category.admits(lexicon.semantic_types(w)))
        types = sum(1 for w in freq if category.admits(lexicon.semantic_types(w)))
        out[name] = (types, hits / total)

    PREVALENCE.parent.mkdir(parents=True, exist_ok=True)
    PREVALENCE.write_text(
        json.dumps(
            {
                "corpus": corpus.name,
                "notes": limit,
                "content_tokens": total,
                "categories": {
                    k: {"types": t, "token_share": round(share, 4)}
                    for k, (t, share) in sorted(out.items())
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return out


def sheet(name: str, corpus_stats: dict[str, tuple[int, float]]) -> str:
    categories = load_categories()
    category = categories[name]
    lines = [
        f"# `{name}` — NER validation",
        "",
        f"**{category.label}**",
        "",
        "<!-- Generated by validation/pipeline/scripts/gen_category_docs.py from",
        "     src/robustehr/resources/semantic_categories.yaml. Do not edit by hand. -->",
        "",
        "## Definition",
        "",
        f"- **Tier:** `{category.tier.value}`",
        f"- **Semantic types:** {', '.join(f'`{t}`' for t in sorted(category.tuis))}",
    ]
    if category.parent:
        lines.append(f"- **Parent:** [`{category.parent}`]({category.parent}_NER_validation.md)")
    if category.children:
        kids = ", ".join(f"[`{c}`]({c}_NER_validation.md)" for c in category.children)
        lines.append(f"- **Children:** {kids}")
    lines.append(
        f"- **Counts toward `clinical_any`:** {'yes' if category.in_default else '**no**'}"
    )
    if name in corpus_stats:
        types, share = corpus_stats[name]
        lines += [
            f"- **Development-corpus prevalence:** {share:.1%} of content tokens, "
            f"{types:,} distinct word types "
            f"([measured](../../measurements/category_prevalence.json))",
        ]
    lines += ["", "## Definition in words", "", category.definition, ""]
    lines += [TIER_BLURB[category.tier], ""]
    if category.note:
        lines += ["> " + " ".join(category.note.split()), ""]

    lines += ["## Benchmark", ""]
    if not category.crosswalk:
        if category.parent:
            lines += [
                "**None for this category directly.**",
                "",
                f"Validation runs against its parent [`{category.parent}`]"
                f"({category.parent}_NER_validation.md); this sheet inherits those "
                "numbers and must say so wherever they are quoted.",
                "",
            ]
        else:
            lines += [
                "**None.**",
                "",
                "No public corpus annotates this category, so no precision or recall "
                "figure can be produced for it. Results involving it are reported "
                "with the tier attached and are excluded from headline claims.",
                "",
                "_Add a benchmark here if one becomes available._",
                "",
            ]
    else:
        for standard, label in sorted(category.crosswalk.items()):
            meta = BENCHMARKS.get(standard, {})
            lines += [
                f"### [{meta.get('name', standard)}]({meta.get('url', '')})",
                "",
                f"- **Maps to:** `{label}`",
                f"- **Corpus:** {meta.get('corpus', '—')}",
                f"- **Size:** {meta.get('size', '—')}",
                f"- **Access:** {meta.get('access', '—')}",
                f"- **Paper:** {meta.get('paper', '—')}",
                "",
            ]
            if meta.get("notes"):
                lines += [meta["notes"], ""]
        lines += [
            "### Protocol",
            "",
            "Per [`validation/protocol.md`](../../protocol.md):",
            "",
            "1. Tag the gold corpus, map gold labels onto this category via the crosswalk above.",
            "2. Report **targeting precision** first — of the edits placed under this "
            "category, what fraction hit a gold span of the mapped label. This is the "
            "package's actual claim.",
            "3. Report strict and relaxed P/R/F1 for completeness, with "
            "cluster-bootstrap CIs **by `patient_id`**.",
            "4. Run the L0-L4 ablation so each method addition gets a number.",
            "",
        ]

    lines += [
        "## Results",
        "",
        "_Not yet run._",
        "",
        "| Rung | Method | Targeting precision | Recall | F1 |",
        "|---|---|---|---|---|",
        "| L0 | word-level lookup | — | — | — |",
        "| L1 | + concept matching (QuickUMLS) | — | — | — |",
        "| L2 | + overlap resolution | — | — | — |",
        "| L3 | + ConText qualification | corpus-level | corpus-level | corpus-level |",
        "| L4 | + RobustEHR structural boundaries | corpus-level | corpus-level | corpus-level |",
        "",
        "L3 and L4 are measured, but **not per category**: their gold is",
        "span-level assertion rather than category membership, so a",
        "category-stratified split would need assertion gold no available corpus",
        "supplies. Corpus-level values are in `assertion_accuracy.json` (L3,",
        "negated-class F1 0.9289 against a 0.0000 floor) and",
        "`assertion_deid_invariance.json` (L4, instability 0.0000 against",
        "PyRuSH's 0.1429).",
        "",
    ]
    return "\n".join(lines) + "\n"


SEMANTIC_TYPE_NAMES: dict[str, str] = {
    "T017": "Anatomical Structure",
    "T018": "Embryonic Structure",
    "T019": "Congenital Abnormality",
    "T020": "Acquired Abnormality",
    "T021": "Fully Formed Anatomical Structure",
    "T022": "Body System",
    "T023": "Body Part, Organ, or Organ Component",
    "T024": "Tissue",
    "T025": "Cell",
    "T026": "Cell Component",
    "T029": "Body Location or Region",
    "T030": "Body Space or Junction",
    "T031": "Body Substance",
    "T033": "Finding",
    "T034": "Laboratory or Test Result",
    "T037": "Injury or Poisoning",
    "T046": "Pathologic Function",
    "T047": "Disease or Syndrome",
    "T048": "Mental or Behavioral Dysfunction",
    "T049": "Cell or Molecular Dysfunction",
    "T050": "Experimental Model of Disease",
    "T058": "Health Care Activity",
    "T059": "Laboratory Procedure",
    "T060": "Diagnostic Procedure",
    "T061": "Therapeutic or Preventive Procedure",
    "T062": "Research Activity",
    "T063": "Molecular Biology Research Technique",
    "T065": "Educational Activity",
    "T074": "Medical Device",
    "T075": "Research Device",
    "T121": "Pharmacologic Substance",
    "T184": "Sign or Symptom",
    "T191": "Neoplastic Process",
    "T195": "Antibiotic",
    "T200": "Clinical Drug",
    "T203": "Drug Delivery Device",
}


def _partition_section() -> list[str]:
    """The exclusive partition, stated where a reader of the categories looks."""
    from robustehr.categories import display_groups, exclusive_order

    order = " > ".join(f"`{name}`" for name in exclusive_order())
    lines = [
        "## Categories overlap; a table needs one per word",
        "",
        "The categories above are sets of semantic types, and they overlap by",
        "design: `finding` and `symptom` lie inside `disorder`, `lab_measurement`",
        "shares types with `lab_result` and `procedure`, and one concept can carry",
        "several types. `robustehr.categories.categories_of` returns every category",
        "that admits a concept, which is what a target needs (`cat=medication`",
        "means any concept that is a medication).",
        "",
        "A table whose rows must sum needs exactly one category per word.",
        "`robustehr.categories.primary_category` gives it: the first category in",
        "this order that admits the concept.",
        "",
        order,
        "",
        "Two outcomes are not categories and are returned as themselves:",
        "`uncategorized` when a concept matched and none of its types is in the",
        "order, and `no_concept` when no concept covers the word (pass `None`).",
        "`finding` precedes `symptom` because the published tables were computed",
        "that way; the two share a display group, so the choice shows only when",
        "they are read separately. The order is declared under `exclusive_order`",
        "in `semantic_categories.yaml`.",
        "",
        "For reading, the primary categories are grouped",
        "(`robustehr.categories.display_groups`):",
        "",
        "| Display group | Primary categories |",
        "|---|---|",
    ]
    for label, members in display_groups().values():
        lines.append(f"| {label} | {', '.join(f'`{m}`' for m in members)} |")
    lines.append("")
    return lines


def overview(stats: dict[str, tuple[int, float]]) -> str:
    """The human entry point: what we tag, in hierarchy, with definitions."""
    cats = load_categories()
    roots = [c for c in cats.values() if c.parent is None]
    lines = [
        "# Semantic categories",
        "",
        "What RobustEHR can target and what it reports hits against. Every",
        "category is a set of UMLS semantic types, so membership is a lookup",
        "against a published terminology rather than a judgement call.",
        "",
        "<!-- Generated by validation/pipeline/scripts/gen_category_docs.py from",
        "     src/robustehr/resources/semantic_categories.yaml. Do not edit by hand. -->",
        "",
        "## Hierarchy",
        "",
        "```",
    ]
    for root in sorted(roots, key=lambda c: c.name):
        mark = "" if root.in_default else "   (excluded from clinical_any)"
        lines.append(f"{root.name}{mark}")
        for i, child in enumerate(root.children):
            kid = cats[child]
            last = i == len(root.children) - 1
            note = "" if kid.in_default else "   (excluded from clinical_any)"
            lines.append(f"{'└──' if last else '├──'} {kid.name}{note}")
    lines += ["```", "", "## Categories", ""]

    for root in sorted(roots, key=lambda c: c.name):
        lines += [f"### `{root.name}` — {root.label}", "", root.definition, ""]
        rows = [root, *(cats[c] for c in root.children)]
        lines += [
            "| Category | Tier | Definition | Semantic types |",
            "|---|---|---|---|",
        ]
        for c in rows:
            name = f"`{c.name}`" if c is root else f"&nbsp;&nbsp;↳ `{c.name}`"
            types = ", ".join(
                f"{t} {SEMANTIC_TYPE_NAMES.get(t, '')}".strip() for t in sorted(c.tuis)
            )
            defn = c.definition if c is not root else "_(above)_"
            lines.append(f"| {name} | `{c.tier.value}` | {defn} | {types} |")
        lines.append("")
        if root.crosswalk:
            cw = "; ".join(
                f"**{BENCHMARKS.get(k, {}).get('name', k)}** → `{v}`"
                for k, v in sorted(root.crosswalk.items())
            )
            lines += [f"**Validated against:** {cw}", ""]
        else:
            lines += ["**Validated against:** _no gold standard covers this._", ""]
        lines += [
            f"Sheet: [`{root.name}_NER_validation.md`]"
            f"(../validation/pipeline/categories/{root.name}_NER_validation.md)",
            "",
        ]

    if stats:
        lines += [
            "## Prevalence in the development corpus",
            "",
            "200 MIMIC-IV discharge summaries. Word-level lookup, so these are",
            "**upper bounds** — see [validation/protocol.md](../validation/protocol.md).",
            "",
            "The rows overlap and do not sum to 100%: a parent counts everything its",
            "children do, and a word may carry several semantic types. For shares",
            "that sum, use the primary category below.",
            "",
            "| Category | % of content tokens | Distinct word types |",
            "|---|---|---|",
        ]
        for name, (types, share) in sorted(stats.items(), key=lambda kv: -kv[1][1]):
            lines.append(f"| `{name}` | {share:.1%} | {types:,} |")
        lines.append("")

    lines += _partition_section()

    lines += [
        "## Removed categories",
        "",
        "Cut for irrelevance to clinical notes rather than for being",
        "indefensible, each measured on the same 200 notes first:",
        "",
        "| Category | Measured | Why removed |",
        "|---|---|---|",
        "| `chemical` | 11.1% of tokens | Matches were abbreviation collisions "
        "(`sig`, `bid`, `date`), not clinical substance. Drugs are covered by "
        "`medication`; the rest is research chemistry. |",
        "| `organism` | 1.7%, 149 of 99,788 terms used | Top matches `patient`, "
        "`major`, `areas`. Pathogens matter but need concept-level matching, "
        "not a 100,000-term word list. |",
        "| `physiology` | 6.1% of tokens | Overlapped `disorder` and `finding`, "
        "with `pain`, `status`, `instructions` on top. Vital signs are handled "
        "by the numeric extractors. |",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus", type=Path, default=None, help="re-measure prevalence from this corpus"
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--check", action="store_true", help="fail if files are stale")
    args = parser.parse_args(argv)

    if args.corpus is not None:
        measure_prevalence(args.corpus, args.limit)
    stats = load_prevalence()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    targets = [(OVERVIEW, overview(stats))]
    for name in sorted(load_categories()):
        targets.append((OUT_DIR / f"{name}_NER_validation.md", sheet(name, stats)))
    for path, content in targets:
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path))
        else:
            path.write_text(content, encoding="utf-8")

    if args.check:
        if stale:
            print("stale category sheets (re-run without --check):", file=sys.stderr)
            for entry in stale:
                print(f"  {entry}", file=sys.stderr)
            return 1
        print(f"{len(targets)} category documents up to date")
        return 0

    print(f"wrote {OVERVIEW} and {len(load_categories())} sheets to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
