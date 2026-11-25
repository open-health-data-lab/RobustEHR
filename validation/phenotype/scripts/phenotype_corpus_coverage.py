#!/usr/bin/env python
"""How much of each phenotype's concept set the MIPA corpus actually contains.

**The question nothing else answers.** The set audit counts what each phenotype
*declares*; the link audit asks whether the matcher could recover each concept
*from its own name*; Table 2 counts evidence *spans* in positive notes. None of
them says how many of hypertension's 609 concepts occur anywhere in the 1,388
discharge summaries — which is the number that separates "the set is broad and
the corpus is narrow" from "the set is broken".

**Three columns, because an absent concept is absent for one of two reasons.**
A declared CUI the corpus never shows is either a concept clinicians do not
write in ICU discharge summaries (a fact about the corpus) or one the matcher
cannot recover from any surface (a fact about the pipeline). Joining the
faceted link audit splits them:

    declared  >=  reachable (matcher recovers its own name)  >=  observed here

Low `observed` against high `reachable` is the honest situation this corpus is
expected to produce — these are ICU discharge summaries, not a textbook, and a
set built for clinical completeness SHOULD outrun any single corpus. Low
`reachable` is a pipeline finding instead. The unobserved remainder is reported
under both readings, per phenotype.

**Coverage is not recall.** `measured_set_recall` asks how much of the *gold
evidence* the set recovers; this asks how much of the *set* the corpus ever
instantiates. A handful of common concepts carries most evidence — the head/
tail numbers here measure exactly how concentrated that is.

**The enrichment screen is a screen, not a precision measurement.** For
phenotypes with expert labels, each observed concept's note-rate in the
label-positive cohort is compared with its rate in the rest of the corpus.
A concept as common in negatives as positives is flagged for review. The
caveat is structural and stated in the payload: labels are per-admission, ICU
notes co-report comorbidities, and a flagged concept may still be correct.
This is the closest available proxy while union precision has no independent
key (validation/methodology/14 §5); it does not close that gap.

**No re-tagging.** Reads the mention cache the corpus runs already wrote
(`data/concept_cache/`), which stores offsets and CUIs, never text. Licence:
the artifact carries identifiers and counts only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.concepts import hierarchy
from robustehr.concepts.phenotype import build, load_definitions, load_maps
from robustehr.metrics.describe import load_group_map, read_groups
from robustehr.rng import sha256_text

#: An observed concept is FLAGGED when its positive-cohort note-rate is less
#: than this multiple of its rate elsewhere AND it appears in a meaningful
#: share of non-positive notes. Both thresholds ship in the payload.
ENRICHMENT_FLAG_BELOW = 1.5
NEGATIVE_RATE_FLOOR = 0.05

#: Continuity correction for the rate ratio, so a concept absent from the
#: negative cohort gets a large finite enrichment rather than a division error.
EPS = 0.5


def load_notes(path: Path) -> dict[str, str]:
    csv.field_size_limit(1_000_000_000)
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["note_id"]: row["text"] for row in csv.DictReader(handle)}


def cache_dir(root: Path, digest: str | None) -> Path:
    """The single matcher-config directory, or the one named explicitly."""
    if digest:
        return root / digest
    dirs = [p for p in root.iterdir() if p.is_dir()]
    if len(dirs) != 1:
        raise SystemExit(
            f"{root} holds {len(dirs)} matcher-config caches; pick one with --cache-digest: "
            f"{sorted(p.name for p in dirs)}"
        )
    return dirs[0]


def note_cuis(cache: Path, sha: str) -> Counter[str] | None:
    """CUI -> mention count for one cached note, or None on a cache miss."""
    path = cache / sha[:2] / f"{sha}.json"
    if not path.exists():
        return None
    mentions = json.loads(path.read_text(encoding="utf-8"))["mentions"]
    return Counter(m[2] for m in mentions)


def enrichment(pos_notes: int, neg_notes: int, n_pos: int, n_neg: int) -> float:
    return ((pos_notes + EPS) / (n_pos + 2 * EPS)) / ((neg_notes + EPS) / (n_neg + 2 * EPS))


def head_size(counts: Counter[str], share: float = 0.9) -> int:
    """How many concepts carry `share` of all mentions — the concentration."""
    total = sum(counts.values())
    if not total:
        return 0
    running = 0
    for i, (_, n) in enumerate(counts.most_common(), start=1):
        running += n
        if running >= share * total:
            return i
    return len(counts)


def _repo_relative(path: Path) -> str:
    """The path as it appears in the repository, whatever machine ran this."""
    resolved = path.resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / "pyproject.toml").is_file():
            return str(resolved.relative_to(parent))
    return path.name


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0912, PLR0915 - one block per stage
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/golden_labels.csv"))
    parser.add_argument("--group-map", default="mipa")
    parser.add_argument("--cache", type=Path, default=Path("data/concept_cache"))
    parser.add_argument("--cache-digest", default=None)
    parser.add_argument("--isa", type=Path, default=Path("data/umls_isa_mth.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--edges", type=Path, default=None, help="facet edges json")
    parser.add_argument(
        "--link-audit",
        type=Path,
        default=Path("validation/measurements/phenotype_link_audit_facets.json"),
        help="faceted link audit run with --full; supplies the `reachable` column",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/phenotype_corpus_coverage.json")
    )
    parser.add_argument(
        "--markdown", type=Path, default=Path("validation/phenotype/phenotype-corpus-coverage.md")
    )
    args = parser.parse_args(argv)

    notes = load_notes(args.notes)
    cache = cache_dir(args.cache, args.cache_digest)
    per_note: dict[str, Counter[str]] = {}
    missing: list[str] = []
    for uid, text in notes.items():
        counts = note_cuis(cache, sha256_text(text))
        if counts is None:
            missing.append(uid)
        else:
            per_note[uid] = counts
    if missing:
        print(f"WARNING: {len(missing)} of {len(notes)} notes have no cache entry; excluded")

    # Cohorts: a phenotype's positive notes are the union of every label column
    # that maps to it. Phenotypes outside the label set get corpus-wide numbers
    # only, reported as such rather than as zeros.
    group_map = load_group_map(args.group_map)
    groups = read_groups(args.labels, group_map)
    positive: dict[str, set[str]] = {}
    for column, uids in groups.items():
        for pheno in group_map.get(column, ()):
            positive.setdefault(pheno, set()).update(u for u in uids if u in per_note)

    isa = hierarchy.load(args.isa)
    code_to_cuis, cui_to_codes = load_maps(args.crosswalk)
    names = sorted(load_definitions())
    built = {p.name: p for p in build(names, isa, code_to_cuis, cui_to_codes)}
    from robustehr.concepts import facets as facets_mod

    closure_candidates = facets_mod.load_closure()
    vetting = facets_mod.load_vetting()
    edges_path = args.edges or facets_mod.DEFAULT_EDGES
    edges = facets_mod.load(edges_path) if edges_path.exists() else None
    definitions = load_definitions()

    audit = {}
    if args.link_audit.exists():
        payload = json.loads(args.link_audit.read_text(encoding="utf-8"))
        if "faceted" not in payload.get("expansion", ""):
            print(
                f"WARNING: {args.link_audit} audits the {payload.get('expansion')!r} sets, "
                "not the faceted runtime sets; the reachable column will not line up"
            )
        audit = payload.get("phenotypes", {})
    else:
        print(
            f"WARNING: {args.link_audit} not found — run "
            "validation/phenotype/scripts/phenotype_link_audit.py --facets --full; "
            "reporting coverage without the reachable column"
        )

    all_uids = set(per_note)
    corpus_cuis: Counter[str] = Counter()
    for counts in per_note.values():
        corpus_cuis.update(counts)

    rows: dict[str, Any] = {}
    for name in names:
        members = built[name].concept_cuis
        mention_counts = Counter(
            {c: sum(counts.get(c, 0) for counts in per_note.values()) for c in members}
        )
        mention_counts = Counter({c: n for c, n in mention_counts.items() if n})
        observed = frozenset(mention_counts)
        notes_with_any = sum(1 for counts in per_note.values() if observed & counts.keys())

        row: dict[str, Any] = {
            "declared": len(members),
            "observed": len(observed),
            "observed_share": round(len(observed) / len(members), 4) if members else None,
            "mentions": sum(mention_counts.values()),
            "notes_with_any": notes_with_any,
            "notes_with_any_share": round(notes_with_any / len(per_note), 4),
            "head_cuis_for_90pct_of_mentions": head_size(mention_counts),
            "top_cuis": [[c, n] for c, n in mention_counts.most_common(20)],
        }

        arow = audit.get(name)
        if arow:
            no_string = set(arow.get("cuis_without_english_string", ()))
            unreachable = set(arow.get("probe_preferred_term", {}).get("unreachable_cuis", ()))
            reachable = members - unreachable - no_string
            unobserved = members - observed
            row["reachable"] = len(reachable)
            row["unobserved_but_reachable"] = len(unobserved & reachable)
            row["unobserved_unreachable"] = len(unobserved - reachable)
            # A concept observed in the corpus but "unreachable" by its own
            # preferred name is normal, not contradictory: notes reach it
            # through synonyms and abbreviations the preferred term lacks.
            row["observed_despite_unreachable_name"] = len(observed - reachable)

        pos = positive.get(name)
        if pos is not None and pos:
            neg = all_uids - pos
            pos_observed = frozenset(c for c in members if any(c in per_note[u] for u in pos))
            pos_with_any = sum(1 for u in pos if observed & per_note[u].keys())
            per_cui = {}
            for cui in sorted(observed):
                in_pos = sum(1 for u in pos if cui in per_note[u])
                in_neg = sum(1 for u in neg if cui in per_note[u])
                per_cui[cui] = (in_pos, in_neg, enrichment(in_pos, in_neg, len(pos), len(neg)))
            ratios = sorted(r for _, _, r in per_cui.values())
            flagged = sorted(
                (
                    cui
                    for cui, (in_pos, in_neg, r) in per_cui.items()
                    if r < ENRICHMENT_FLAG_BELOW and in_neg / len(neg) >= NEGATIVE_RATE_FLOOR
                ),
                key=lambda c: -per_cui[c][1],
            )
            row["cohort"] = {
                "positive_notes": len(pos),
                "observed_in_positive": len(pos_observed),
                "positive_notes_with_any": pos_with_any,
                "positive_notes_with_any_share": round(pos_with_any / len(pos), 4),
                "median_enrichment": round(ratios[len(ratios) // 2], 2) if ratios else None,
                "nonspecific_flags": flagged[:15],
                "nonspecific_flag_count": len(flagged),
            }

        # Near-miss prevalence: how often notes mention a concept ONE RELATION
        # away from the pre-closure set, and how much of that the closed set
        # now captures. The candidate pool was generated corpus-blind
        # (phenotype_closure.py) and excludes the old set by construction, so
        # every pool mention here was a targeting miss before the closure.
        pool = closure_candidates.get(name, frozenset())
        if pool:
            scope = pos if pos else all_uids
            kept_closure = pool & vetting.get(name, {}).get("closure", frozenset())
            identity: frozenset[str] = frozenset()
            if edges is not None:
                med = facets_mod.medications(
                    frozenset(
                        c for code in definitions[name].seeds for c in code_to_cuis.get(code, ())
                    ),
                    build([name], isa, code_to_cuis, cui_to_codes, facets=False)[0].concept_cuis,
                    edges,
                    declared=definitions[name].medication_seeds,
                    vetted=vetting.get(name, {}).get("medication"),
                )
                identity = frozenset(c for c, t in med.provenance.items() if t == "identity")
            nm_mentions = nm_captured = notes_nm = notes_nm_captured = 0
            id_mentions = notes_id = notes_recovered = 0
            for uid in scope:
                counts = per_note[uid]
                in_pool = sum(n for c, n in counts.items() if c in pool)
                in_kept = sum(n for c, n in counts.items() if c in kept_closure)
                in_id = sum(n for c, n in counts.items() if c in identity)
                nm_mentions += in_pool
                nm_captured += in_kept
                notes_nm += in_pool > 0
                notes_nm_captured += in_kept > 0
                id_mentions += in_id
                notes_id += in_id > 0
                notes_recovered += (in_kept + in_id) > 0
            row["near_miss"] = {
                "scope": "label_positive_cohort" if pos else "whole_corpus",
                "scope_notes": len(scope),
                "candidate_pool": len(pool),
                "adjudicated_kept": len(kept_closure),
                "notes_with_near_miss": notes_nm,
                "notes_with_near_miss_share": round(notes_nm / len(scope), 4),
                "near_miss_mentions": nm_mentions,
                "captured_mentions": nm_captured,
                "captured_mention_share": (
                    round(nm_captured / nm_mentions, 4) if nm_mentions else None
                ),
                "notes_with_captured_near_miss": notes_nm_captured,
                "identity_mentions": id_mentions,
                "notes_with_identity_mention": notes_id,
                # The headline: notes with >=1 mention of RECOVERED evidence —
                # an adjudicated closure keep or an identity variant — that the
                # pre-closure target could not reach.
                "notes_with_recovered_evidence": notes_recovered,
                "notes_with_recovered_evidence_share": round(notes_recovered / len(scope), 4),
            }
        rows[name] = row

    manifest = {
        "notes": len(per_note),
        "notes_without_cache_entry": len(missing),
        "cache_config_digest": cache.name,
        "vetting_sha256": hashlib.sha256(
            Path("src/robustehr/resources/phenotype_vetting.yaml").read_bytes()
        ).hexdigest()[:16],
        # Repo-relative: a machine-local path in a committed artifact says
        # nothing a reader can use and leaks a working directory.
        "link_audit": _repo_relative(args.link_audit) if audit else None,
        "distinct_cuis_in_corpus": len(corpus_cuis),
    }
    payload = {
        "question": (
            "how many of each phenotype's declared concepts occur anywhere in "
            "the MIPA corpus, and how concentrated is the evidence?"
        ),
        "columns": (
            "declared = the vetting-gated runtime set build() carries; "
            "reachable = concepts the matcher recovers from their own preferred "
            "name (faceted link audit); observed = declared concepts with at "
            "least one cached mention in the corpus"
        ),
        "how_to_read_a_gap": (
            "unobserved_but_reachable concepts are ones ICU discharge summaries "
            "simply do not write — a fact about the corpus, expected to be "
            "large for a clinically complete set. unobserved_unreachable "
            "concepts could not have been found by any spelling — a fact about "
            "the pipeline, and the number to watch."
        ),
        "coverage_is_not_recall": (
            "measured_set_recall asks how much of the gold evidence the set "
            "recovers; this asks how much of the set the corpus instantiates. "
            "Neither substitutes for the other."
        ),
        "enrichment_caveat": (
            "the cohort screen compares note-rates between label-positive and "
            "other notes. Labels are per-admission and ICU notes co-report "
            "comorbidities, so a flagged concept may still belong in the set — "
            "this is a review queue, NOT a precision measurement, and it does "
            "not close the union-precision gap in validation/methodology/14 §5. "
            f"Flag rule: enrichment < {ENRICHMENT_FLAG_BELOW} and present in "
            f">= {NEGATIVE_RATE_FLOOR:.0%} of non-positive notes."
        ),
        "near_miss": (
            "the closure's measured effect. The candidate pool is DELIBERATELY "
            "broad (one hop of graph neighborhood, corpus-blind), so pool-"
            "mention prevalence saturates and is context, not the claim. The "
            "claim is notes_with_recovered_evidence: notes containing at least "
            "one mention of an ADJUDICATED closure keep or an RxNorm identity "
            "variant — evidence the pre-closure target could not reach. "
            "Mentions of dropped candidates are correctly rejected noise, not "
            "a residual gap."
        ),
        "licence": "identifiers and counts only; no UMLS string appears here",
        "manifest": manifest,
        "phenotypes": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    _render_markdown(args.markdown, payload)

    width = max(len(n) for n in names)
    print(
        f"{'phenotype':<{width}} {'decl':>5} {'reach':>6} {'obs':>5} {'obs%':>6} "
        f"{'notes%':>7} {'head90':>6} {'pos-obs':>8} {'med-enr':>8}"
    )
    for name, row in rows.items():
        cohort = row.get("cohort") or {}
        print(
            f"{name:<{width}} {row['declared']:>5} {row.get('reachable', '—'):>6} "
            f"{row['observed']:>5} {row['observed_share']:>6} "
            f"{row['notes_with_any_share']:>7} {row['head_cuis_for_90pct_of_mentions']:>6} "
            f"{cohort.get('observed_in_positive', '—'):>8} "
            f"{cohort.get('median_enrichment', '—'):>8}"
        )
    print(f"\n-> {args.out}\n-> {args.markdown}")
    return 0


def _render_markdown(path: Path, payload: dict[str, Any]) -> None:
    rows = payload["phenotypes"]
    manifest = payload["manifest"]
    out = [
        "# Phenotype concept sets in the MIPA corpus",
        "",
        "Generated — do not hand-edit:",
        "",
        "```bash",
        "python validation/phenotype/scripts/phenotype_link_audit.py --facets --full",
        "python validation/phenotype/scripts/phenotype_corpus_coverage.py",
        "```",
        "",
        f"Corpus: {manifest['notes']:,} MIMIC-IV discharge summaries "
        f"(mention cache `{manifest['cache_config_digest']}`), "
        f"{manifest['distinct_cuis_in_corpus']:,} distinct CUIs corpus-wide. "
        f"Concept sets are the vetting-gated runtime sets "
        f"(`phenotype_vetting.yaml` sha `{manifest['vetting_sha256']}`).",
        "",
        "`declared` is what `build()` carries; `reachable` is what the matcher "
        "recovers from a concept's own preferred name; `observed` is what the "
        "corpus contains at least one mention of. An unobserved-but-reachable "
        "concept is one ICU discharge summaries do not write — expected, and a "
        "fact about the corpus. An unreachable one is a pipeline gap. "
        "`head90` is how many concepts carry 90% of the phenotype's mentions — "
        "evidence is expected to concentrate heavily.",
        "",
        "**This table measures the concept warrant alone, and `reachable` is "
        "therefore a floor rather than the pipeline's reach.** Evidence is "
        "admitted on either of two warrants: a concept-set membership, which is "
        "what is counted here, or a declared surface form matched literally. A "
        "concept the matcher cannot recover from its own preferred name is "
        "counted unreachable in this column even when a declared anchor reaches "
        "the same text — which is the case the anchors exist for, since an "
        "organism or a qualifier has no `is-a` path to a disorder set at any hop "
        "count. Read the surface warrant from "
        "`validation/measurements/phenotype_gap_audit.json`, and the two "
        "together from methodology 16; neither column below moves when an anchor "
        "is added or removed.",
        "",
        "| phenotype | declared | reachable | observed | obs. share | notes w/ any "
        "| head90 | unobs. reachable | unobs. unreachable |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in sorted(rows.items(), key=lambda kv: -kv[1]["declared"]):
        out.append(
            f"| {name} | {row['declared']} | {row.get('reachable', '—')} "
            f"| {row['observed']} | {row['observed_share']:.0%} "
            f"| {row['notes_with_any_share']:.0%} "
            f"| {row['head_cuis_for_90pct_of_mentions']} "
            f"| {row.get('unobserved_but_reachable', '—')} "
            f"| {row.get('unobserved_unreachable', '—')} |"
        )
    out += [
        "",
        "## Label-positive cohorts",
        "",
        "For phenotypes with expert labels: how much of the set the positive "
        "notes instantiate, and the enrichment screen. Median enrichment is the "
        "note-rate ratio (positive vs rest) across observed concepts; flags are "
        "concepts as common outside the cohort as in it — a review queue, not a "
        "precision measurement (labels are per-admission and ICU notes "
        "co-report comorbidities).",
        "",
        "| phenotype | positive notes | observed in cohort | cohort notes w/ any "
        "| median enrichment | flagged non-specific |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, row in sorted(rows.items()):
        cohort = row.get("cohort")
        if not cohort:
            continue
        out.append(
            f"| {name} | {cohort['positive_notes']} "
            f"| {cohort['observed_in_positive']} "
            f"| {cohort['positive_notes_with_any_share']:.0%} "
            f"| {cohort['median_enrichment']} "
            f"| {cohort['nonspecific_flag_count']} |"
        )
    out += ["", payload["enrichment_caveat"], ""]
    if any("near_miss" in r for r in rows.values()):
        out += [
            "## Recovered evidence (the closure's measured effect)",
            "",
            "The headline column is **notes w/ recovered evidence**: notes "
            "containing at least one mention of an adjudicated closure keep or "
            "an RxNorm identity variant — evidence the pre-closure `pheno=` "
            "target could not reach. The candidate pool is deliberately broad "
            "(one corpus-blind graph hop), so its own mention prevalence "
            "saturates; mentions of dropped candidates are correctly rejected "
            "noise, not a residual gap.",
            "",
            "| phenotype | scope | notes w/ recovered evidence | closure-keep "
            "mentions | notes w/ closure keep | notes w/ identity variant |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for name, row in sorted(rows.items()):
            nm = row.get("near_miss")
            if not nm:
                continue
            out.append(
                f"| {name} | {nm['scope']} ({nm['scope_notes']}) "
                f"| **{nm['notes_with_recovered_evidence_share']:.0%}** "
                f"| {nm['captured_mentions']:,} "
                f"| {nm['notes_with_captured_near_miss']} "
                f"| {nm['notes_with_identity_mention']} |"
            )
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
