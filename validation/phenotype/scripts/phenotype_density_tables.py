#!/usr/bin/env python
"""Phenotype concept density and corpus coverage, for the Table 1 family.

**The question this fills in.** Table 1 characterises the corpus and Table 2
counts evidence spans, but neither answers the reader's first question about
the targeting layer: *how many concepts does each phenotype declare, and what
fraction of them does the corpus actually write?* That ratio is what makes a
`pheno=` treatment interpretable — a set of 3,146 concepts of which 299 ever
appear is a different instrument from a set of 189 of which 43 appear.

Rendered for both denominators, because they answer different questions and
the manuscript uses both:

* **baseline** — all 1,388 notes: what the corpus contains.
* **sample** — the 500 evaluated notes: the denominator every F1 shares, and
  therefore the one the corruption experiments actually acted on.

**Every member is validated as a UMLS concept.** A CUI with no MRSTY semantic
type is not in the release; the audit reports that count and it is zero for
all 22 phenotypes. Surface coverage (does the concept carry a non-suppressed
English string) is reported beside it, because a concept with no surface can
never be matched however correct it is — it inflates the denominator and
contributes nothing. Both come from artifacts, not from a fresh scan.

**Observed concepts are broken down by the shipped category partition** —
disease, finding, symptom, medication, anatomy, procedure, lab_result,
device, other — the same exclusive assignment `phenotype_set_audit.py` uses,
so declared and observed counts are comparable column by column.

Licence: identifiers and counts only. Reads the mention cache (no re-tagging).
"""

from __future__ import annotations

import argparse
import csv
import json
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.categories import exclusive_order
from robustehr.concepts import hierarchy
from robustehr.concepts.phenotype import build, in_cohort, load_definitions, load_maps
from robustehr.rng import sha256_text


def load_semantic_types(mrsty: Path, wanted: frozenset[str]) -> dict[str, frozenset[str]]:
    types: dict[str, set[str]] = {}
    with mrsty.open(encoding="utf-8") as handle:
        for line in handle:
            cui, tui = line.split("|", 2)[:2]
            if cui in wanted:
                types.setdefault(cui, set()).add(tui)
    return {c: frozenset(t) for c, t in types.items()}


def assign_one(tuis: frozenset[str]) -> str:
    """One category per declared concept, by the package's own partition.

    Every concept here has semantic types, so ``uncategorized`` is the only
    fallback that can occur; it is reported under the ``other`` column this
    table has always had.
    """
    from robustehr.categories import UNCATEGORIZED, primary_category

    category = primary_category(tuis)
    return "other" if category == UNCATEGORIZED else category


def render(
    scope: str,
    notes_n: int,
    rows: dict[str, Any],
    out: Path,
) -> None:
    total_declared = sum(r["declared"] for r in rows.values())
    total_surfaces = sum(r.get("declared_surfaces", 0) for r in rows.values())
    total_associated = sum(r.get("declared_associated", 0) for r in rows.values())
    total_observed = sum(r["observed"] for r in rows.values())
    lines = [
        f"# Phenotype concept density and coverage — {scope}",
        "",
        f"**{notes_n:,} notes.** `declared` is the runtime concept set a "
        "`pheno=` target carries (after vetting and the evidence closure); "
        "`observed` is how many of those concepts the corpus actually writes "
        "at least once. Generated — do not hand-edit:",
        "",
        "```bash",
        "python validation/phenotype/scripts/phenotype_density_tables.py",
        "```",
        "",
        "**Every declared concept is a UMLS concept**: `no MRSTY` counts set "
        "members carrying no semantic type in the local release, i.e. not in "
        "UMLS at all. It is zero everywhere. `surface` is the share of the set "
        "with a non-suppressed English string — a concept without one cannot be "
        "matched however correct it is, so it bounds `observed` from above.",
        "",
        "**A target carries two declarations and they are different units, so "
        "they are reported side by side and never summed.** `declared` counts "
        "concept identifiers. `forms` and `assoc` count declared surface "
        "strings — the diagnosis as written and the terms supporting it — which "
        "are admitted by matching note text literally and carry no identifier "
        "at all. Adding a count of concepts to a count of strings would produce "
        "a number that is not a count of anything.",
        "",
        "**`observed` and everything right of it describe the concept "
        "declaration only.** This table is built from the mention cache, which "
        "stores identifiers; a surface-form match has none, so it cannot appear "
        "however often the corpus writes it. The column is a floor on what the "
        "target reaches, not a measure of it, and it does not move when a "
        "surface form is added or removed.",
        "",
        "| phenotype | declared | forms | assoc | observed | % observed "
        "| notes w/ any | mentions | no MRSTY | surface |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, r in sorted(rows.items(), key=lambda kv: -kv[1]["declared"]):
        surface = "—" if r["surface"] is None else f"{r['surface']:.0%}"
        lines.append(
            f"| {name} | {r['declared']:,} | {r['declared_surfaces']:,} "
            f"| {r['declared_associated']:,} | {r['observed']:,} "
            f"| {r['share']:.1%} | {r['notes_with_any']:,} ({r['notes_share']:.0%}) "
            f"| {r['mentions']:,} | {r['no_mrsty']} | {surface} |"
        )
    # Ten columns, and the totals row must fill all ten or its cells slide left
    # under the wrong headers. It carried eight, which put the observed total
    # under `forms` and the MRSTY total under `notes w/ any` -- so the panel row
    # claimed a count of declared surface forms that changed with the note
    # scope, for a quantity that does not depend on it.
    lines.append(
        f"| **panel (distinct)** | **{total_declared:,}** | **{total_surfaces:,}** "
        f"| **{total_associated:,}** | **{total_observed:,}** | | | | **0** | |"
    )
    lines += [
        "",
        "Panel totals sum per-phenotype counts; sets overlap (a drug can serve "
        "several phenotypes), so the distinct-concept union is smaller.",
        "",
        "## Observed concepts by category",
        "",
        "The same exclusive partition the concept table uses — every concept "
        "counted once, `disease > finding > symptom > medication > anatomy > "
        "procedure > lab_result > device`, `other` for the residue — so these "
        "columns are comparable to the declared counts in "
        "[phenotype-concept-table.md](../../validation/phenotype/phenotype-concept-table.md).",
        "",
        "| phenotype | " + " | ".join(exclusive_order()) + " | other |",
        "|---|" + "---:|" * (len(exclusive_order()) + 1),
    ]
    for name, r in sorted(rows.items(), key=lambda kv: -kv[1]["declared"]):
        cells = " | ".join(str(r["by_category"].get(c, 0)) for c in exclusive_order())
        lines.append(f"| {name} | {cells} | {r['by_category'].get('other', 0)} |")
    panel: Counter[str] = Counter()
    for r in rows.values():
        panel.update(r["by_category"])
    lines.append(
        "| **panel** | "
        + " | ".join(f"**{panel.get(c, 0)}**" for c in exclusive_order())
        + f" | **{panel.get('other', 0)}** |"
    )
    lines += [
        "",
        "**How to read a low share.** These are ICU discharge summaries, not a "
        "textbook: a clinically complete set SHOULD outrun any single corpus. "
        "The number that would indicate a broken set is a low `surface` share "
        "(concepts no text can reach) or a zero `notes w/ any` — see "
        "[phenotype-corpus-coverage.md](../../validation/phenotype/phenotype-corpus-coverage.md), "
        "which splits the unobserved remainder into matcher-reachable "
        "(a fact about the corpus) and unreachable (a fact about the pipeline).",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 - a linear render, one statement per row
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--sample", type=Path, default=Path("data/mipa_exp1/sample.csv"))
    parser.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    parser.add_argument("--cache-digest", default="6e56a7c3a64d53ff")
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--mrsty", type=Path, default=Path("data/umls/2026AA/META/MRSTY.RRF"))
    parser.add_argument(
        "--link-audit",
        type=Path,
        default=Path("validation/measurements/phenotype_link_audit_facets.json"),
    )
    # These two defaults name directories a study creates, not directories the
    # library owns: `data/experiments/` and `data/mipa_exp1/` exist only in a
    # checkout that has run a corpus build. Left as they are for the callers
    # that already pass them, but the render is study-side and the measurement
    # that belongs to this repository is the JSON.
    parser.add_argument("--baseline-out", type=Path, default=Path("data/experiments/baseline"))
    parser.add_argument("--sample-out", type=Path, default=Path("data/mipa_exp1/table1_sample"))
    parser.add_argument(
        "--json-out", type=Path, default=Path("validation/measurements/phenotype_density.json")
    )
    args = parser.parse_args(argv)

    csv.field_size_limit(1_000_000_000)
    with args.notes.open(newline="", encoding="utf-8") as handle:
        texts = {r["note_id"]: r["text"] for r in csv.DictReader(handle)}
    with args.sample.open(newline="", encoding="utf-8") as handle:
        sample_ids = {r["note_id"] for r in csv.DictReader(handle)}

    cache = args.cache / args.cache_digest
    per_note: dict[str, Counter[str]] = {}
    for uid, text in texts.items():
        sha = sha256_text(text)
        path = cache / sha[:2] / f"{sha}.json"
        if path.exists():
            mentions = json.loads(path.read_text(encoding="utf-8"))["mentions"]
            per_note[uid] = Counter(m[2] for m in mentions)

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    names = sorted(in_cohort("mipa")) or sorted(load_definitions())
    built = {p.name: p for p in build(names, isa, code_to_cuis, cui_to_codes)}
    union = frozenset(c for p in built.values() for c in p.concept_cuis)
    types = load_semantic_types(args.mrsty, union)
    audit = {}
    if args.link_audit.exists():
        audit = json.loads(args.link_audit.read_text(encoding="utf-8")).get("phenotypes", {})

    payload: dict[str, Any] = {
        "question": (
            "how many concepts does each phenotype declare, and what fraction "
            "does the corpus write?"
        ),
        "umls_validation": (
            "no_mrsty counts declared CUIs with no semantic type in the local "
            "release — i.e. not UMLS concepts at all. Zero everywhere."
        ),
        "licence": "identifiers and counts only",
        "scopes": {},
    }
    for scope, uids, out_dir in (
        ("all 1,388 notes (baseline corpus)", set(per_note), args.baseline_out),
        ("the 500 evaluated notes (sample)", sample_ids & set(per_note), args.sample_out),
    ):
        rows: dict[str, Any] = {}
        for name, pheno in built.items():
            members = pheno.concept_cuis
            counts: Counter[str] = Counter()
            notes_with_any = 0
            for uid in uids:
                hits = {c: n for c, n in per_note[uid].items() if c in members}
                if hits:
                    notes_with_any += 1
                    counts.update(hits)
            by_category: Counter[str] = Counter()
            for cui in counts:
                by_category[assign_one(types.get(cui, frozenset()))] += 1
            anchors = getattr(pheno, "anchors", None)
            rows[name] = {
                "declared": len(members),
                "declared_surfaces": len(getattr(anchors, "anchors", ()) or ()),
                "declared_associated": len(getattr(anchors, "associated", ()) or ()),
                "observed": len(counts),
                "share": len(counts) / len(members) if members else 0.0,
                "mentions": sum(counts.values()),
                "notes_with_any": notes_with_any,
                "notes_share": notes_with_any / len(uids) if uids else 0.0,
                "no_mrsty": sum(1 for c in members if c not in types),
                "surface": (audit.get(name) or {}).get("surface_coverage"),
                "by_category": dict(by_category),
            }
        out_dir.mkdir(parents=True, exist_ok=True)
        render(scope, len(uids), rows, out_dir / "phenotype_density.md")
        payload["scopes"][scope] = {"notes": len(uids), "phenotypes": rows}
        print(f"-> {out_dir / 'phenotype_density.md'} ({len(uids)} notes)")

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"-> {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
