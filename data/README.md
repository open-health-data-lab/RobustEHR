# `data/` — local, licensed, never committed

Everything in this directory is gitignored by default-deny (`data/*`) except this file,
`notes.sql`, and one `README.md` per placeholder directory (`!data/<dir>/`, then the shared
`data/*/*` / `!data/*/README.md` pair — see `.gitignore` for why the order matters). Nothing
else here is redistributable. To add a publishable file, add it to the allowlist by name
(`CONTRIBUTING.md`); never loosen the rule.

## Expected layout

```
data/
├── README.md, notes.sql            # committed
├── golden_notes.csv                # MIMIC-IV development corpus via notes.sql (PhysioNet DUA)
├── golden_labels.csv               # optional; only phenotype_corpus_coverage.py reads it
├── umls/2026AA/META/*.RRF          # umls/README.md — unpacked UMLS release
├── quickumls_index/                # quickumls_index/README.md (+ quickumls_snomed/, benchmark arm only)
├── snomed_el/                      # snomed_el/README.md — SNOMED CT Entity Linking Challenge
├── negex/  bioscope/               # fetched by script, no credentials
├── drugs/  lexicon/  casi/         # licensed inputs and the tables built from them
├── assertion_gold_mimic/           # built, MIMIC-derived
├── phenotype_review/               # exported for clinician review, UMLS terms in the clear
├── mtsamples/                      # mtsamples/README.md — public-domain transcribed reports
├── umls_isa_mth.json, umls_facets.json   # derived edge lists, see below
└── llm_cache/ openrouter_cache/ concept_cache/ pipeline_audit/   # auto-created caches
```

Each placeholder directory's `README.md` says what goes there, where to get it, how to build
it, which package features need it, and under what licence.

## Notes corpus

Any corpus exposing `(note_id, text)` works. `patient_id` is optional and enables
patient-clustered resampling and the copy-forward donor ordering that a future
stale-copy-forward operator would need (none is registered today); `timestamp` is optional.
**No label column is read anywhere in the core** — selecting phenotypes drives protect/target
behaviour through concept sets, not through labels.

Under the PhysioNet Credentialed Health Data Use Agreement, note text may not be committed or
redistributed. The publishable artifact is the edit script plus hashes, which anyone with their
own copy of the corpus can replay exactly.

## UMLS

**Needed by the concept layer only.** Segmentation, protection, dose accounting, the RENDER /
INPUT / LEXICAL / DISCOURSE operator suite, quality profiling and reporting run with no
terminology at all.

Release target: **2026AA**, unpacked so that `data/umls/2026AA/META/` exists.
`robustehr.concepts.umls.UmlsRelease.discover(Path("data/umls"))` finds the release by that
layout; the archive is not read directly. Files consumed, all under `META/`:

| File | Used for |
|---|---|
| `MRCONSO.RRF` | concept strings, term types (`AB`/`ACR` give abbreviations natively), source vocabularies |
| `MRSTY.RRF` | semantic types, for TUI filtering |
| `MRREL.RRF` | relationships — including MED-RT `may_treat` / `may_prevent`, which is how "antihypertensive medications" is derived without a second resource |
| `MRHIER.RRF` | bounded hierarchy traversal (SNOMED CT descendants) |
| `MRXNS_ENG.RRF` | normalized-string index, for deterministic seed-term → CUI resolution with no model and no threshold |
| `MRSAB.RRF` | source vocabulary metadata and versions, recorded in the lockfile |
| `MRRANK.RRF` | source/term ranking where a preferred form must be chosen |

The builders load these into a local DuckDB file (`pip install -e ".[terminology]"`) and freeze
identifier-only resources. **Runtime never touches UMLS** — no network, no UTS API, no
database — it matches frozen identifier sets.

### Derived edge lists without a CLI yet

`data/umls_isa_mth.json` (SNOMED CT `isa` plus MTH `RN` edges, for phenotype closure) and
`data/umls_facets.json` (MED-RT `may_treat` / `may_prevent`, RxNorm `tradename_of` /
`has_ingredient`, SNOMED parents) are produced by two builders that have no CLI subcommand:

```bash
pip install -e ".[terminology]"
python - <<'PY'
from pathlib import Path
from robustehr.concepts import facets, hierarchy
from robustehr.concepts.umls import UmlsRelease
release = UmlsRelease.discover(Path("data/umls"))
hierarchy.build(release, Path("data/umls_isa_mth.json"))
facets.build(release, Path("data/umls_facets.json"))
PY
```

Both are optional: without them `--phenotype` falls back to the disorder closure and
`Phenotype.facet_sizes` is empty. `data/snomed_el/cui_snomed.json` is a third derived file
with **no builder in the repository at all** — see `snomed_el/README.md`.

### Licensing

Under the UMLS Metathesaurus License Agreement the source content is not redistributable, so
the shipped resources withhold restricted surface strings and keep only identifiers (CUI, TUI,
SNOMED concept ID, RxCUI), provenance, and a `surface_sha256`. Resolving those identifiers back
to strings is the reader's own licensed lookup against their own UMLS release; no byte of
licensed content leaves this machine, and runtime never needs the strings at all.

ATC class names are WHO copyright and are never shipped; MED-RT and EPC classes serve the same
purpose and are US Government work.

| Resource | Where | Licence | Redistributable? |
|---|---|---|---|
| UMLS Metathesaurus 2026AA | `umls/` | UMLS Metathesaurus License Agreement | no |
| MIMIC-IV notes and everything derived (assertion gold, review TSVs) | `golden_notes.csv`, `assertion_gold_mimic/` | PhysioNet Credentialed Health Data Use Agreement | no |
| SNOMED CT Entity Linking Challenge | `snomed_el/` | PhysioNet DUA | no |
| NegEx test set, BioScope, CASI | `negex/`, `bioscope/`, `casi/` | none attached upstream — treated as restricted | no |
| DrugBank exports | `drugs/` | DrugBank academic terms | no |
| Meta-Inventory of Medical Abbreviations | `lexicon/` | CC-BY 4.0, but 71.7% UMLS-LRABR-derived — built locally | no |
| MTSamples | `mtsamples/` | CC0 1.0 | yes, but not needed by `src/`; kept out for size |

One derived statistic ships inside the package: `src/robustehr/resources/clinical_salience.json`,
a per-token-type share of occurrences inside expert-annotated clinical spans over the 272
challenge notes. It carries no note text, span, identifier or token sequence and cannot be
inverted to a note; it is published as an aggregate measurement, on the same footing as the
recall figures in `validation/measurements/`, under the authors' reading of the DUA.

## Caches (auto-created, safe to delete)

`llm_cache/` (completions keyed by model and prompt; `ROBUSTEHR_LLM_CACHE` overrides the
location), `openrouter_cache/` (the validation annotation scripts' `--cache`),
`concept_cache/` (mention offsets and CUIs, never text), `pipeline_audit/` (scratch for
`validation/pipeline/scripts/pipeline_audit.py`).

## What works with no data at all

The core install (`pip install -e .`) runs `robustehr describe`, `run`, `replay`, `compare`
and `target` on any `(note_id, text)` CSV — for example `examples/demo_notes.csv` — with no
terminology, no credentials and no network. Table 1's document, section, header, sentence,
list, whitespace, placeholder, token and character levels populate; the concept and assertion
levels report "not measured" rather than zero. This is enforced by `tests/test_core_only.py`.
The `[clinical]` extra adds the assertion level and the SEMANTIC channel;
`pheno=` targets also run on the core install, on the shipped surface forms alone (the
diagnosis as written); `quickumls_index/` + `snomed_el/` + `umls_isa_mth.json` add the concept
side of a phenotype target and unlock `cat=`, `tui=` and `concept` targets; `lexicon/` is
optional (`--lexicon`).
