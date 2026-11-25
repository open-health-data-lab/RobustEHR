# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-11-24

The release the companion study's tables can be rebuilt from, and the first one
made public. Nothing here changes which units an existing run selects or the
text it produces: operator versions and the seed specification are unchanged.
What changes is what a run writes down.

### Changed

- **An edit script no longer stores the words it corrupted.** A replacement is
  written as its minimal difference from the text it replaces
  (`store.minimal_edit`): a typographical error on a twelve-letter word was
  stored as the whole word with one letter changed, and is now one offset and
  one letter. At 15% of words, the old form put 15% of a note's words into the
  script. `write_run` applies each cell's trimmed edits and compares the result
  with the cell's `output_sha256` before writing; a cell that does not
  reproduce is stored as proposed and counted. The manifest gains
  `replacement_form`, `cells_stored_as_proposed` and
  `replacement_chars_by_operator`. Scripts written by 0.1.0 replay unchanged.
  `edits_sha256` differs from 0.1.0 for the same run; `output_sha256` of every
  cell does not.
- **The documentation no longer says an edit script holds only offsets and
  hashes.** `docs/run-artifact.md` states what each operator's stored
  replacement implies about the note, so a script can be judged before it is
  shared.
- `SCHEMA_VERSION` is `1.1`: dose rows carry the five fields below.

### Added

- **Operator parameters from the command line and from a recipe.**
  `--param OPERATOR:KEY=VALUE` (repeatable) and a recipe's `params:` mapping.
  `max_edits_per_token` on `input.ocr_confusion`, the cap the phenotype-aimed
  arms of the companion study ran under, was reachable only from Python. A
  parameter for an operator that is not in the run is refused.
- **Dose rows record the parameters and the damage per token.** `params` is
  the canonical parameter string that feeds the seed. `tokens_edited` and
  `tokens_edited_once` count the tokens an arm changed and how many of them in
  a single character position, which is what separates an OCR arm capped at
  one edit per token from an uncapped one at the same severity.
- **Phenotype evidence is reported by tier on every dose row.**
  `evidence_n_by_tier` and `evidence_touch_by_tier` split the declared and
  touched evidence by how each span was admitted. The functions existed and
  nothing called them.
- **One category per word.** `categories.primary_category` returns the single
  category a concept is counted under, by a precedence declared in
  `semantic_categories.yaml` (`exclusive_order`), and keeps `no_concept` (no
  concept covers the word) apart from `uncategorized` (a concept matched, of no
  listed type). `categories.display_groups` groups them for reading. The
  companion study's Table 1 used this partition from a script of its own;
  `phenotype_density_tables.py` now calls the package.
- **A warning when an aim admits nothing.** `--target cat=medication` with no
  QuickUMLS index exited 0 with zero edits and nothing on stderr. The dose
  table already said `na_scope_empty`; the terminal now says so too, with the
  likely cause.
- An `umls` install extra for the concept matcher, which had been arriving
  only as a dependency of `clinical`.
- `docs/run-artifact.md`, every field of the manifest, dose record and edit
  script; `docs/glossary.md`, every term, including the ones used in more than
  one sense and their names in the companion paper; `examples/recipe.yaml`.
- A "Status and limitations" section and a table of what runs without a UMLS
  licence, in the README.

### Fixed

- The recipe in the README and in `examples/README.md` combined structural
  operators with an aim and was refused by the loader as written.
- `docs/categories.md` did not say that categories overlap, and its prevalence
  table reads as though it should sum.
- The typographical-error operator's rules (three letters or more, one
  interior character) were stated in two background documents and not in the
  operator catalogue.
- Five statements about what runs without licensed terminology disagreed
  across `README.md`, `examples/README.md`, `data/README.md` and
  `docs/pipeline.md`.

### Added in 0.2.0, written before it was numbered

- **The three levels of aim are all reachable from the command line and from a
  recipe.** `--target clinical` (recipe `mode: clinical`) selects the measured
  clinical-content rule, `target.ClinicalSalience`, which was previously only
  constructible from Python; its canon
  `clinical(salience>=0.5,drug,labelled,unseen)` parses back, and each clause
  is a switch. `--target all` (no aim) and `--target pheno=NAME` were already
  grammar atoms.
- **`pheno=` targets run without licensed terminology.** When the `isa`
  hierarchy or the crosswalk is absent, `robustehr run` builds each declared
  phenotype from its surface forms alone (`concepts.phenotype.surface_only`),
  says so on stderr, and the manifest's `targeting` block records
  `warrants: ["surface"]` rather than `["concept", "surface"]`. A missing
  QuickUMLS index no longer aborts a phenotype run; the concept warrant simply
  finds nothing and the artifact says which target it was.
- **`describe --run --markdown`** prints the characterisation instrument side by
  side: the clean corpus, then one column per (operator, severity) cell, each
  reconstructed from its edit script.
- `examples/aim_note.csv`, one synthetic note, and `examples/README.md` section
  6, the same note under the three aims with the dose record of each.

## [0.1.0] — 2026-09-23

First release. The interfaces below are the ones the validation studies and the
companion study ran on.

### Added

- **The phenotype target admits evidence on two warrants.** A `pheno=` target
  returns a span when its concept is in the phenotype's declared concept set
  *or* when its text is a declared surface form of the diagnosis matched
  literally (`concepts/surface.py`, `resources/phenotype_anchors.yaml`). The
  surface warrant reaches what no closure over a disorder hierarchy can: the
  causative organism, the qualifier, the abbreviation the matcher produced no
  candidate for; it also carries the model-proposed terms no vocabulary string
  matched, at tier `associated`, and the stop surfaces refused on either
  warrant. Every evidence span records the warrant and tier that admitted it;
  tiers are reported, never selected on. Stated once in
  `validation/methodology/17-phenotype-association-method.md`.
- **A `targeting` block in the run manifest** (`concepts/phenotype.py:
  targeting_manifest`). The digest of every packaged targeting resource, present
  or `"absent"`; a `targeting_digest` over the anchor resource's phenotype
  blocks and global stop surfaces, which ignores the review ledger so a
  provenance edit is not read as a change of method; the review state of the
  anchors and of the vetting; and the digests of the locally built terminology
  inputs. `null` for an agnostic run. The same block travels in
  `concept-profile` and `compare` payloads.
- **`VETTED_BY`** (`concepts/surface.py`): the three review states an anchor
  resource may declare — `llm`, `llm+hand`, `llm+clinician` — validated at load.
- **`input.ocr_confusion` takes `max_edits_per_token`.** A rate over characters
  is the right denominator for a page and the wrong one for a word; at a
  saturating severity over a narrow target an uncapped dose replaces a token
  with same-length noise. With the cap at 1 the operator emits one misread per
  token at any severity, which is the configuration for an arm aimed at one
  phenotype's evidence. Unset, the parameter reaches no canon and nothing moves.
- **`input.typo` takes `include_mixed`.** Alphanumeric tokens (`DM2`, `T2DM`,
  `A1c`) tokenize as MIXED and are otherwise invisible to the operator. Off by
  default; its denominator says what the flag admits.

### Changed

- **Every CLI command builds evidence on both warrants.** `run`,
  `concept-profile`, `describe` and `compare` go through one helper that passes
  the note text to `index_document`. Under a phenotype target or scope the
  eligible set is what the method defines, so `requested_k` and the hash-ranked
  selection follow it: an edit script generated under a `pheno=` target by an
  earlier build is not *regenerated* by this one, and its manifest cannot say
  why, which is what the `targeting` block fixes going forward. `replay
  --verify` of any existing artifact is unaffected — replay re-applies stored
  edits and checks hashes; it does not re-select. Agnostic runs are
  byte-identical. `SPEC_VERSION` is unchanged.
- **`input.ocr_confusion` is `2.1.0`.** Behaviour, table and denominator are
  unchanged; the confusion table's comment on the uppercase block now
  describes the block, and the file is hashed into the operator version.
- A concept profile's `distinct_cuis` no longer counts the empty CUI that
  anchor-tier evidence carries.

## [Unreleased — before 0.1.0]

### Added

- **`governs(...)`, a target that aims at the cue rather than the evidence.** An
  assertion operator aimed at a phenotype selected nothing. `PhenotypeEvidence`
  tests the unit's own span, and for a SEMANTIC operator the unit *is* the cue:
  the `denies` in `denies hypertension` is not evidence for hypertension, so
  `--phenotype-scope target` with any `semantic.*` operator rejected every cue
  and reported `eligible_n = 0` on a note carrying dozens. The run completed and
  the corpus came out byte-identical to the baseline, so the failure was visible
  only in the dose ledger. No test covered the combination.

  `governs(a)` admits a span inside a cue whose ConText scope covers a span `a`
  admits. It is a lookup rather than a proximity window — ConText already records
  which cues produced each span's attributes — so it picks no character distance.
  It composes: `all(lex=word;governs(pheno=hypertension))` aims a typo at the
  word that negates hypertension.

  **No operator version moves.** Neither `meta.version` nor `meta.resources`
  changes, `SeedMaterial` is untouched, and `scope_canon` still emits `sel=` only
  when the target restricts something, so every stored edit script reparses and
  reproduces. `TargetContext` gains a defaulted `assertions` field and
  `apply_operator` a keyword-only `assertions=`; neither reaches a canon. The
  `resolution` property appends `+assertion` only when an index is supplied, so
  rows written before this stay byte-identical.

  Because a `governs(...)` target with no assertion index admits nothing — the
  same silent zero — the runner raises rather than running. A configuration error
  must not present as a finding.

### Changed

- **`cues_in` is memoized.** It is a pure function returning an immutable tuple,
  so unlike the pipeline caches beside it a cached result cannot be mutated by a
  later caller. The four cue-flip operators each call it with identical arguments
  while enumerating the same note, and an experiment aiming them at fifteen
  phenotypes in turn did sixty identical ConText passes over one discharge
  summary. The cache holds four notes.

### Fixed

- **`semantic.uncertainty_flip` was fabricating care-plan facts.** It enumerated
  HYPOTHETICAL alongside POSSIBLE_EXISTENCE, on the argument that "a hedge and a
  condition are the same move for this channel". An audit of the emitted edits
  says otherwise: ConText's HYPOTHETICAL catches conditional and future *care
  planning*, and flipping those to the actual mood states facts the note does not
  contain -- `as needed` -> `scheduled` changes a medication order, `return` ->
  `presented` asserts an encounter that did not happen, `risks of` ->
  `complications of` asserts an outcome. Fourteen of fifty sampled edits left the
  assertion layer this way and every one was HYPOTHETICAL, against zero in the
  negation arm.

  A care instruction is not a hedge about whether the patient has the condition,
  which is the only thing a phenotyping task asks. The operator now enumerates
  POSSIBLE_EXISTENCE only -- which is also the only half the BioScope F1 0.2511
  was measured on, so the reported detector quality now describes what the
  operator actually does. The version holds at `1.0.0`: `meta.resources` is
  untouched, so `resolved_version` stays `1.0.0+r70ac9237`, and no artifact had
  run the operator before this.

- **The four `semantic.*` operators were editing scope terminators.**
  `_cues_for_category` filtered cues on category and not on direction, so
  ConText's TERMINATE rules — which mark where a cue *stops* reaching and assert
  nothing themselves — were handed to the flip table. It has no entry for any of
  them, so they took the category default: `negated._default` is the empty
  string, which **deleted `but`**, and `historical._default` is `current`, which
  rewrote **`presentation` into `current`**. Measured over 40 MIMIC discharge
  summaries that was 250 of 1,359 cues, so roughly a fifth of any arm would have
  been a discourse edit carrying a SEMANTIC contract and counted in a denominator
  documented as "negation cues".

  Fixed in `_cues_for_category`, so the four LLM twins inherit it through their
  `super().eligible(ctx)` call. Unconditional rather than a mode: editing a
  terminator is never the perturbation these operators claim to apply. The
  version holds at `1.0.0` — no artifact in this project or its companion study
  has ever run a `semantic.*` operator, so nothing is reseeded. Only
  `denominator_doc` moves, which reaches `taxonomy.yaml` and not the seed.

- **`input.ocr_confusion` takes `max_edits_per_token`.** A character-rate dose is
  the right denominator for a page and the wrong one for a word: at a saturating
  severity over a narrow target the operator substituted every confusable
  position in a token at once, turning `Hypertension` into `Hvpcrfousj0h` — the
  term deleted and replaced with same-length noise rather than misread. The cap
  keeps at most that many of a token's positions, ranked by the key `select()`
  already uses, so it narrows the eligible set without fighting the draw that
  follows and severity ladders still nest.

  **The operator version stays at `2.0.0`.** Behaviour on the default path is
  unchanged, and `params_canon` is built from the dict the caller passed rather
  than from operator defaults, so a run that does not name the parameter
  reproduces byte-for-byte. Bumping the version would have reseeded every
  existing OCR run to no purpose. Only `denominator_doc` moves, which is
  documentation, reaches `taxonomy.yaml`, and is not part of the seed.

### Changed

- **The taxonomy reconciliation is recounted against the source it reconciles.** The a
  priori taxonomy the package was designed against is restored as `docs/source-taxonomy.md`
  (29 substantive rows, numbered). `docs/corruption-taxonomy-status.md` now carries exactly
  those 29 rows, each classified once — **13 implemented, 5 partial, 11 not built** — and
  `docs/corruption-catalogue.md` §5 has three countable tables that sum to 29. The previous
  summary said 30 rows and 14/3/13; the status table had grown to 33 rows by splitting
  source rows, had dropped the source's "social history corruption" row, and described
  `render.bullet_to_prose` with `render.list_to_prose`'s behaviour. Two rows changed
  category on the recount: sentence duplication rose from not built to partial
  (`discourse.section_duplicate` exists), medication substitution fell from implemented to
  partial (the source's own example, same-class substitution, is not built).
  `TestCatalogueArithmetic` counts all three tables and asserts 29.
- Documentation names only registered operators and existing paths: `render.lab_block_collapse`
  (not `aligned_block_collapse`), `validation/protocol.md` (not `validation-protocol.md`),
  and the never-registered `discourse.stale_copy_forward`, `factual.medication_swap`,
  `render.line_rewrap`, `numeric_format`, `unit_conversion`, `synonym_sameconcept` and
  `assertion_restyle` are no longer cited as if they existed. The catalogue says 28
  operators, not 21; `docs/nlp-hierarchy.md` no longer says nine are registered.
- Prose that had drifted from its committed artifact is reconciled to the artifact and says
  so: the cue-detection and flip-recovery tables in `validation/pipeline/assertion-benchmarks.md`
  (`cue_detection.json`, `assertion_flip_recovery.json`), the phenotype-evaluation narrative in
  `validation/measurements/README.md` (`phenotype_eval.json`, 22 phenotypes), the artifact
  format in `validation/methodology/02-determinism.md` (JSONL, not Parquet), and the ACER
  spread in `04-dose-accounting.md`, now marked as a development-run figure with no committed
  artifact. The temporality and experiencer operators' `simulates` strings (and the
  regenerated `taxonomy.yaml`) no longer say "no gold in any domain": there is no *published*
  gold, and this project's held-out MIMIC gold now measures them.
- The core install has three dependencies, not four (README, CONTRIBUTING, examples).
- `data/README.md` documents the unpacked `data/umls/2026AA/META/` layout the code actually
  reads (it previously described a zipped `data/UMLS/` that `UmlsRelease` cannot open), the two
  derived edge lists that have no CLI yet, the caches, a licence table, and what the core
  install runs with no data at all.

### Added

- Placeholder directories under `data/` — `umls`, `quickumls_index`, `snomed_el`, `negex`,
  `bioscope`, `drugs`, `lexicon`, `casi`, `assertion_gold_mimic`, `phenotype_review`,
  `mtsamples` — each tracked only through a README that says what goes there, where to get
  it, how to build it, which features need it and under what licence. `.gitignore` re-admits
  the directories by name and a shared `data/*/*` rule keeps their contents ignored; the
  belt-and-braces directory globs moved above the `data/` block because git takes the last
  matching rule. `manuscript/` and `old_manuscript/` are ignored.
- `validation/measurements/corpus/` — the corpus characterisation artifacts (aggregate counts
  only, no note text): Table 1 over the 1,388 MIPA discharge summaries, the edit-placement
  measurement, and the cross-corpus runs over MTSamples and the synthetic multi-format demo
  corpus produced by `validation/pipeline/scripts/corpus_characterisation.py`.
- `validation/pipeline/scripts/mtsamples_corpus.py` — deterministic `(note_id, text)` sample
  of the CC0 MTSamples transcriptions, the real non-MIMIC corpus the cross-corpus runs use.

### Fixed

- A placeholder directory that holds only a README no longer counts as a present QuickUMLS
  index or challenge corpus: `ConceptMatcher` and the data-gated tests check for the index's
  own files, so a fresh clone skips those tests as before instead of failing on the README.

- **The package is now `robustehr` (was `ehrrobust`).** Import `robustehr`, install
  `robustehr`, run `robustehr`. The repository, the organisation and the project had said
  RobustEHR for some time; only the Python package disagreed. There is no compatibility
  alias: nothing has been released, so there is no installed base to break, and a shim
  would preserve the ambiguity the rename exists to remove.
- The LLM environment variables follow: `EHRROBUST_LLM_MODEL` and `EHRROBUST_LLM_CACHE`
  are now `ROBUSTEHR_LLM_MODEL` and `ROBUSTEHR_LLM_CACHE`.
- `robustehr describe --group-map` accepts a path to a YAML file as well as a label set
  packaged in `resources/label_groups.yaml`. Your annotation project was never going to be
  in this package; append `#setname` if the file declares more than one.

### Added

- `robustehr.concepts.annotate.annotate_corpus` — corpus-level concept tagging, cached by
  note hash, parallel across processes, and keyed on the matcher configuration so changing
  a threshold invalidates the cache rather than silently mixing two configurations into one
  measurement. It previously lived in an experiment script that four other scripts reached
  into.
- `validation/` gathers the studies that validate the package: the methodology chapters,
  the measurement artifacts they cite, the scripts that produce them, and the tests that
  keep prose and artifact pinned together.
- `data/notes.sql` — the extraction query for the development corpus. Note text cannot be
  published; the query that selects it can, which is what lets a credentialed reader
  reproduce the corpus the published edit scripts replay against.
- `CONTRIBUTING.md`, `CITATION.cff`, this changelog.

### Removed

- The MIPA evaluation harness, the three experiments, the manuscript tables and the GCP
  deployment scripts. They are one study rather than part of the instrument, and they now
  live in a separate repository that depends on this one.
- The `evaluation` and `cloud` extras, and the `ehrrobust-mipa` console script, which
  existed only for that harness.
- The `./openrouterapi.txt` credential fallback. A library that picks up a key from its
  working directory sends your notes to a third party because of where you happened to run
  it. `OPENROUTER_API_KEY` is the only source.

### Fixed

- `robustehr describe`'s Table 2 renderer declared `dict[str, int]` for a mapping that
  carries an optional `_distinct` entry it already popped with a `None` default.
- `quantiles` was annotated `list[int]` while receiving per-note ratio fields; it is now
  `Sequence[float]`, which is covariant and so still accepts a `list[int]`.
- The category validation sheets were generated into their pre-`validation/` location, and
  the staleness test guarded on the old path — so it skipped rather than failed. Both fixed;
  the check runs again.
- The README and `data/README.md` documented a `concepts materialize` command that has
  never existed. They now describe what actually ships: identifiers only, plus a
  `surface_sha256` where a term drove a build decision.
