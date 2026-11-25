# MIMIC assertion gold (1,000 spans) — restricted, built locally, never committed

**What.** 100 hash-ranked MIMIC-IV notes × 10 spans, annotated on four assertion dimensions by
two language models under a pre-committed guideline and frozen with a reliability bound.
Files: `sample.json`, `labels.json`, `gold.yaml` (`restricted: true`), `split.json`,
`cue_candidates.json`, `examples.*`.
**Build.** Needs `data/golden_notes.csv`, `data/quickumls_index/`, the `[clinical]` extra and
`OPENROUTER_API_KEY`; run in order (flags in `validation/pipeline/assertion-benchmarks.md`):
    python validation/pipeline/scripts/sample_assertion_corpus.py
    python validation/pipeline/scripts/annotate_assertions.py --model <model>
    python validation/pipeline/scripts/freeze_mimic_gold.py
    python validation/pipeline/scripts/split_assertion_gold.py
**Licence.** MIMIC-derived: PhysioNet Credentialed Health Data Use Agreement.
**Needed by.** The `assertion_*`, `cue_*` and `scope_*` validation scripts only; nothing in `src/`.
**Never commit.** Denied by `data/*/*`; only this file is tracked.
