# RobustEHR

**Deterministic, dose-calibrated perturbation of clinical free text.**

Robustness claims in clinical NLP are usually made against loosely defined noise.
RobustEHR exists so that you can say something precise instead:

> We applied operator `X`, version `Y`, to eligible unit `Z` at a realized dose of `D`,
> using resource versions `R` — and the exact corpus can be regenerated from the
> original notes plus the published edit scripts.

It is measurement infrastructure. It does not try to prove any model is safe, and it
does not claim that its synthetic transformations reproduce the natural distribution of
EHR documentation errors.

---

## What it answers

Five questions that robustness studies usually leave open:

| Question | RobustEHR answer |
|---|---|
| What changed? | A named, versioned operator with a declared contract |
| How much changed? | Requested vs **realized** dose, over an explicit eligible unit |
| Compared to what denominator? | Each operator declares its eligible unit; applicability is reported per corpus |
| Did it touch clinical evidence? | Per-edit phenotype relatedness, measured — never assumed |
| Can someone else regenerate it? | Byte-identical replay from published edit scripts |

## Design commitments

- **Deterministic.** Every random choice is a pure function of content. No timestamp, no
  worker id, no batch index, no `hash()`, no unordered-set iteration, and no float on any
  control-flow path. Same input, same config → same bytes, on any platform.
- **Nested severities.** `selected(0.10) ⊆ selected(0.30) ⊆ selected(0.50)`, so dose-response
  curves are paired within a document instead of mixing dose with sampling noise.
- **Propose, then apply.** Operators never mutate text. They emit immutable edits against
  original offsets; one applier resolves conflicts under a canonical total order and
  produces a bidirectional character alignment.
- **Edit scripts are the artifact.** Perturbed clinical text is usually not redistributable.
  Edit scripts, dose tables and hashes are — so those are what you publish, and anyone with
  their own copy of the corpus can replay them exactly.
- **Labels are never required.** Choosing phenotypes decides whether related entities are
  *protected* or *targeted*. That needs concept sets, not gold labels.

## What can be corrupted

The full catalogue — every operator, the structural level it acts on, what it
simulates, and what it preserves — is
[`docs/corruption-catalogue.md`](docs/corruption-catalogue.md). It also
reconciles the original corruption taxonomy against what is implemented: what
was kept, what was restructured, and what is not built.

Three axes organise it, and they are independent:

* **level** — the unit touched (character → word → sentence → header → note),
  which is what a dose is a fraction *of*;
* **channel** — the process simulated (`render`, `input`, `discourse`,
  `semantic`), which is what a result is *about*;
* **contract** — what is preserved, which is what a result may *claim*.

**Aiming at a phenotype.** A `pheno=` target returns the spans that are evidence for
one phenotype, on either of two warrants: the span's concept is in the phenotype's
declared concept set, or its text is a declared form of the diagnosis, matched
on its spelling with case, spacing and punctuation ignored. The concept set reaches what the terminology connects; the surface forms
reach what it cannot — the causative organism, the qualifier that separates HFpEF
from HFrEF, the abbreviation the matcher produces no candidate for. Every evidence
span records which warrant and tier admitted it, and tiers are reported, never
selected on, so a result can say how much of the *diagnosis* it reached and not
only how much of the declared evidence: each dose row carries the evidence
declared and the evidence touched, in total and by tier (`evidence_n_by_tier`,
`evidence_touch_by_tier`). The run manifest records what the target was built
from. The method is stated once in
[`validation/methodology/17-phenotype-association-method.md`](validation/methodology/17-phenotype-association-method.md)
and its design in [`docs/targeting-design.md`](docs/targeting-design.md).

## Three levels of aim

Where a corruption lands is chosen apart from the operator. A run declares one
of three levels of aim, and every cell records which:

| Aim | `--target` | Eligible units | How it was validated |
|---|---|---|---|
| None | `all` (default) | every eligible unit in the note | edit placement over 1,388 MIMIC-IV notes: 32-34% of edits on clinical tokens, the corpus base rate (29.1%) |
| Clinical content | `clinical` | tokens the measured rule admits: salience >= 0.50, or a curated drug, or a labelled lab value, or an unseen matcher mention | the rule scored at token level on 49 held-out SNOMED CT challenge notes (precision 0.820, recall 0.789); placement 93-94% |
| One phenotype's evidence | `pheno=NAME` | spans that are evidence on either warrant: concept-set membership, or the diagnosis as written | set recall against 23,131 expert evidence spans over 22 phenotypes; reach reported per cell |

Aim applies to character- and token-level operators, whose units lie inside a
word. Structural operators take a section scope only, because a heading is not
a concept span. A recipe that asks otherwise is refused with a message. From
flags, an aim that admits nothing for an operator is recorded on each dose row
as `na_scope_empty` and a warning is printed, so a zero is never silent. Any
UMLS mention (`concept`) is not the clinical aim: measured, it admits 45.7% of a
discharge summary's tokens at precision 0.500, section headings included.

The same synthetic note under the three aims, with the words each aim may touch
and the dose record beside it, is section 6 of
[`examples/README.md`](examples/README.md). Without licensed terminology on the
machine, `pheno=` runs on the surface warrant alone and the manifest records
`warrants: [surface]`.

**What a phenotype set is made of.** A shipped concept set mixes identifiers
derived from the terminology (SNOMED CT seed and `isa` descendants, MED-RT
treatment relations, RxNorm identities) with identifiers a language model
proposed or a one-hop closure suggested, each gated by a vetting verdict; the
surface forms are author-written English, proposed by a language model,
reviewed by a second and curated by hand. Every row records which. There is no
clinician review of record, so a shipped set is a proposal to review for the
corpus it is aimed at before a result rests on it, and the manifest records the
review state.

## Operator contracts

Preservation is not a property of an operator in general — it is a property of
*(operator, span, document, phenotype definition)*. But a subset of operators genuinely
cannot alter clinical reference under any circumstances, and that difference is
machine-checkable rather than a matter of judgment:

| Contract | Guarantee | Discharged by |
|---|---|---|
| `CONTROL_NULL` | output ≡ input | byte equality |
| `INVARIANT_BY_CONSTRUCTION` | no clinical reference can change, ever, for any phenotype | property test `κ_op(apply(d)) == κ_op(d)` over the whole corpus |
| `CONDITIONALLY_PRESERVING` | preserving iff the edit misses clinical evidence | per-instance evidence-touch measurement |
| `REFERENCE_ALTERING_BY_DESIGN` | changing reference is the point | semantic-transition registry + expert audit |
| `REFERENCE_UNCONSTRAINED` | no claim made | — |
| `CONTROL_DESTRUCTIVE` | must destroy downstream performance | harness sanity check |

Vocabulary follows from this: **perturbation** for reference-preserving transformations,
**corruption** for reference-altering ones, **adversarial transformation** where no realism
is claimed.

## Installation

**Not yet on PyPI.** Install from a checkout:

```bash
git clone https://github.com/open-health-data-lab/RobustEHR.git
cd RobustEHR
python -m venv .venv && source .venv/bin/activate
pip install -e .                          # core: the full operator suite, no clinical deps
pip install -e ".[umls]"                  # + the concept matcher (QuickUMLS)
pip install -e ".[terminology]"           # + UMLS concept-set builder (DuckDB)
pip install -e ".[clinical]"              # + assertion detection (spaCy / medspaCy)
```

Python 3.11+. The core install has three dependencies, needs no terminology and
touches no network. The `benchmark` and `neural` extras install comparison arms
that only the scripts under `validation/` import.

### What needs a UMLS licence, and what does not

Installing the `umls` extra gives you the matcher, not the vocabulary. Concept
matching needs an index you build yourself from your own licensed copy of UMLS
([`data/quickumls_index/README.md`](data/quickumls_index/README.md)).

| You have | What runs |
|---|---|
| Core install only | Every operator; `describe`, `run`, `replay`, `compare` on structure and characters; `--target all`; `--target clinical` on the shipped salience table, drug list and lab labels; `--target pheno=NAME` on the surface forms alone, which reach the diagnosis as written and not its medications or findings |
| `clinical` extra | The above, plus assertion detection: the `semantic.*` operators and `--phenotype-scope protect` |
| `umls` extra and your own index | The above, plus concept matching: `--target cat=NAME`, `tui=`, `concept`, `uncategorized`; the concept side of `pheno=`; `concept-profile`; the concept rows of `describe` and `compare` |

Nothing fails silently when a layer is missing. A concept row that could not be
computed reads "Not measured", a `pheno=` run on surface forms alone says so on
stderr and writes `warrants: [surface]` in the manifest, and a target that
admitted nothing prints a warning naming the likely cause.

## Five-minute walkthrough

A complete run — characterise, corrupt, replay, compare — on 32 synthetic notes
that ship with the package. No UMLS licence, no data access, no credentials:

```bash
robustehr describe --corpus examples/demo_notes.csv --markdown       # Table 1: the clean corpus
robustehr run      --corpus examples/demo_notes.csv --out demorun/ \
                   --operators input.typo render.header_delete --severities 0.30
robustehr replay   --run demorun/ --corpus examples/demo_notes.csv   # every cell reproduces
robustehr describe --run demorun/ --corpus examples/demo_notes.csv --markdown   # Table 1 again, one column per cell
robustehr compare  --run demorun/ --corpus examples/demo_notes.csv --markdown   # what each note lost
```

Then the three levels of aim on one synthetic note, still on the core install:

```bash
robustehr run --corpus examples/aim_note.csv --out aim/none      --operators input.typo --severities 0.15
robustehr run --corpus examples/aim_note.csv --out aim/clinical  --operators input.typo --severities 0.15 --target clinical
robustehr run --corpus examples/aim_note.csv --out aim/phenotype --operators input.typo --severities 1 \
              --target pheno=hypertension --phenotype hypertension
```

Every command explained, with its real output, in
[`examples/README.md`](examples/README.md).

## Usage

The end-to-end flow — corpus, baseline, structure, concepts, assertion, dose,
injection, artifact, replay — is drawn and explained in
[`docs/pipeline.md`](docs/pipeline.md), which walks a corpus end to end. What
can be corrupted, row by row against the source taxonomy with implementation
status, is in
[`docs/corruption-taxonomy-status.md`](docs/corruption-taxonomy-status.md).

```bash
# 1. does each operator even apply to this corpus?  Settle this before any dose.
robustehr applicability  --corpus notes.csv

# 2. baseline. `describe` is Table 1, keyed by the structural LEVEL an
#    operator can target — document, section, header, sentence, list_item,
#    aligned_block, space_run, placeholder, span, token, character, assertion
#    — so every unit that can be corrupted has a measurement beside it. The
#    structural levels need NO terminology, which is what lets a reader
#    without a UMLS licence reproduce that half.
robustehr describe        --corpus notes.csv --markdown --phenotype hypertension
robustehr describe        --corpus notes.csv --per-note   # one row per note; data/ only
robustehr baseline        --corpus notes.csv     # degradation detail
robustehr concept-profile --corpus notes.csv --per-note --phenotype hypertension

# 3. corrupt. Two axes: the SCALE is the operator, the AIM is the span.
#    No aim (default), clinical content, or one phenotype's evidence...
robustehr run --corpus notes.csv --out run/ --operators input.typo --severities 0.10 0.30
robustehr run --corpus notes.csv --out run/ --operators input.typo --severities 0.10 0.30 --target clinical
robustehr run --corpus notes.csv --out run/ --operators input.typo --severities 0.10 0.30 \
    --target pheno=hypertension --phenotype hypertension
#    ...or the finer predicates the grammar composes, for a targeted ablation.
robustehr run --corpus notes.csv --out run/ \
    --operators input.typo --severities 0.10 0.30 \
    --target 'all(cat=medication;pheno=hypertension)'

#    An operator's own parameters are set per operator and recorded per cell.
#    Here OCR may misread at most one character of any word:
robustehr run --corpus notes.csv --out run/ --operators input.ocr_confusion --severities 0.10 \
    --param input.ocr_confusion:max_edits_per_token=1

# 3b. …or write the experiment down instead. See "Recipes" below.
robustehr run --corpus notes.csv --config recipe.yaml --out run/

# 4. …or several corruptions at once, merged onto one note.
robustehr run --corpus notes.csv --out run/ --compose \
    --operators input.typo discourse.sentence_delete --severities 0.30 \
    --emit-text data/corrupted/

# 5. verify every stored cell reconstructs to its recorded hash.
robustehr replay  --run run/ --corpus notes.csv

# 6. what did the corruption cost? Baseline and corrupted, SAME instrument.
robustehr describe --run run/ --corpus notes.csv --markdown       # Table 1: clean column, then one per cell
robustehr describe --run run/ --corpus notes.csv --out run/describe.json   # every level and quantile
robustehr compare  --run run/ --corpus notes.csv --markdown       # per note: edits, concepts lost, by category
```

`describe --run` and `compare` reconstruct each corrupted note by replaying its
edit script, so neither needs `--emit-text` and both provably describe the run
being reported. Both work with **no terminology at all** — every structural and
character level is measurable without a UMLS licence, which is the property that
lets a reader reproduce half of Table 1 and the whole of the before/after
comparison. With an index, `compare` adds the concept deltas.

## Recipes

Flags are fine for one operator. An experiment is easier to write down, and a
recipe is what the manifest records:

```yaml
seed: rep0
documents: {fraction: "0.50"}          # reproducible, and 0.25 ⊆ 0.50
corruptions: [input.typo, input.ocr_confusion]   # operator ids or family names
corruptions_per_document: {min: 1, max: 2}   # or 1, for a clean ablation
severity: medium                       # resolved against each operator's own ladder
params:                                # per operator; recorded on every dose row
  input.ocr_confusion: {max_edits_per_token: 1}
target:
  mode: clinical                       # random | clinical | umls | non_umls
```

This recipe runs on the core install and is
[`examples/recipe.yaml`](examples/recipe.yaml). With a QuickUMLS index,
`mode: umls` aims at concept mentions instead, optionally narrowed by
`semantic_categories: [medication]` and `phenotype: hypertension`. An aimed
recipe may list only character- and word-level operators; structural ones
(`corruptions: [structural]`) go in a recipe of their own with `mode: random`.

Three things this buys that the flags do not:

* **`severity: medium` means something different to every operator** — 10% of
  eligible words for `input.typo`, 50% of headers for `render.header_delete`,
  *two sections* for `discourse.section_duplicate`, which is not a rate at all.
  One global mapping would compare a mild dose against a severe one and call
  them the same condition.
* **Document selection nests.** `fraction: 0.25` is a subset of `fraction: 0.50`,
  so a corpus-size sweep is paired rather than mixing sample size with sampling
  noise. (`--limit` is not this: it takes the head of the file.)
* **Targeting cannot be forced onto structural corruptions.** A section header
  is not a concept span, so `target: {mode: umls}` on `render.header_delete`
  would select nothing and report a corpus-wide zero that reads as a finding.
  It is a configuration error with a message, never a silent no-op.

Severities are quoted strings, never YAML floats — `0.1 + 0.2 != 0.3`, and a
float on a control-flow path is how a dose-response curve stops being replayable.
The loader refuses one and names the fix.

`--emit-text` writes the corrupted notes. It refuses any path outside `data/`
unless you pass `--i-understand-the-licence`: corrupted text is derived from the
corpus and carries its restrictions, and a corrupted MIMIC note is still MIMIC.

**What a run writes.** Three files: `manifest.json`, `dose.jsonl` (one row per
note, operator and severity) and `edits.jsonl` (one row per applied edit). Every
field is defined in [`docs/run-artifact.md`](docs/run-artifact.md). An edit is
stored as offsets plus its minimal replacement: a typographical error on
`hypertension` is written as one position and one letter, never as the word. So
an edit script copies no span of a note. It is still derived from the corpus,
since an offset says where a word was and some replacements imply what stood
there (a brand name written over a generic names the drug). Share an edit
script on the terms your corpus sets for derived data; `docs/run-artifact.md`
lists what each operator's edits reveal.

Any corpus exposing `(note_id, text)` works. Optional `patient_id` enables copy-forward
operators and patient-clustered resampling; optional `timestamp` orders the copy-forward
donor. No label column is ever read by the core.

## Optional: LLM-backed semantic flips

The four SEMANTIC operators flip what a note asserts about a concept — `denies chest
pain` becomes `reports chest pain`. Each ships in two forms:

| operator | mechanism | needs |
|---|---|---|
| `semantic.negation_flip` | cue substitution from a lookup table | nothing, works offline |
| `semantic.negation_flip_llm` | the sentence is rewritten by a model you name | an OpenRouter key |

The table arm is precise and offline. The LLM arm handles what a substitution cannot —
agreeing a verb, dropping a stranded preposition, unpicking `no evidence of pneumonia or
effusion`, which has one cue and two findings.

### It is opt-in, and there is no default model

**Nothing calls out unless you name a model.** With `ROBUSTEHR_LLM_MODEL` unset the LLM
operators report zero eligible units and behave exactly as if the module were not
installed. There is deliberately no default: a default would mean your notes reach a
third party through a setting you never chose.

```bash
export OPENROUTER_API_KEY=sk-or-...          # your own key; none ships with the package
export ROBUSTEHR_LLM_MODEL=google/gemini-2.5-flash
```

> **Naming a model is a disclosure decision.** Running these operators sends the
> *sentence* around each cue to a third-party API. Requests carry
> `provider: {"data_collection": "deny"}`, which restricts OpenRouter to providers that do
> not retain or train on prompts — a mitigation, not a permission. Data held under a use
> agreement (MIMIC-IV under the PhysioNet DUA, for example) may require authorisation this
> package cannot grant you. The table operators need no network at all.

### Validate your model before you trust it — one command, no credentials

Model quality on this task varies enormously, and not in the way the names suggest. Two
models from the same vendor one tier apart scored **F1 0.33 and 0.97** on negation.

So check yours first, against the **synthetic gold that ships in the package** — 350
annotated spans over seven notes written from scratch, describing no real patient:

```bash
python validation/pipeline/scripts/validate_llm_model.py --model google/gemini-2.5-flash
```

```
model  google/gemini-2.5-flash
gold   packaged synthetic fixtures (no credentials needed) — 350 spans

  exact label set  293/350 = 0.8371
  negated     F1 0.8478  P 0.9750  R 0.7500  n=52   (shipped rules 0.7788)
  uncertain   F1 0.5000  P 0.6000  R 0.4286  n=14   (shipped rules 0.3810)
  historical  F1 0.2778  P 0.1786  R 0.6250  n=8   [too few positives to judge]
  family      F1 0.0000  P 0.0000  R 0.0000  n=1   [too few positives to judge]
  unmodified  F1 0.8967  P 0.9101  R 0.8836  n=275

  USABLE — negated F1 0.848 clears the 0.70 floor
```

It scores your model per dimension, compares against what the offline rule detector
already achieves, and gives a verdict. **If your model does not beat the rules, use the
rules** — they are free, offline and deterministic.

Read the result honestly: the packaged corpus is negation-dense and hedge-poor (52
negated spans against 14 uncertain, 8 historical, 1 family), so it judges negation
confidently and the rest weakly. It is a smoke test with real numbers. If you hold MIMIC
credentials, `--gold` and `--corpus` point the same script at the harder corpus the
published figures come from.

### Which model

**`google/gemini-2.5-flash` is the recommended default** — fast, ~$0.30/$2.50 per million
tokens, and it clears the bar on negation. Measured on the held-out MIMIC gold:

| model | `negated` | `uncertain` | `historical` | in / out per M |
|---|---:|---:|---:|---|
| `google/gemini-3.6-flash` | 0.970 | 0.886 | 0.865 | $1.50 / $7.50 |
| **`google/gemini-2.5-flash`** | 0.838 | 0.695 | 0.623 | $0.30 / $2.50 |
| `google/gemini-2.5-flash-lite` | 0.326 | 0.400 | 0.400 | $0.10 / $0.40 |
| *the shipped rule detector* | *0.608* | *0.442* | *0.294* | *free* |

Note the cliff rather than the ranking: **the cheapest tier scores below the offline rule
set on negation**, so "use a cheap LLM" is not one option. Note also that `3.6-flash` is
not a cheap model despite the name — five times `2.5-flash` on input.

### What runs automatically, and what stays reproducible

Every guard is automatic and per-edit; batch runs need no supervision:

- the reply is diffed against the original sentence and trimmed to **what actually
  changed**, so a model that touches only the cue emits a cue-sized edit;
- that span is checked against the **protection registry** — a rewrite reaching a
  de-identification placeholder or a lab block is refused;
- **line structure is preserved**, so a single-line reply cannot silently flatten a
  hard-wrapped note and smuggle in a second perturbation;
- anything that fails **falls back to the deterministic table edit**, so a dose is never
  silently short, and the fallback count is reported.

Replay stays exact. An operator is a *proposer*; a run's artifact is a list of concrete
`(start, end, replacement)` edits, and applying that list is byte-identical forever
whatever proposed it. Every completion is cached under the model id and the exact prompt,
so re-generating an edit script is offline and identical too. Record the **model id
beside the operator version** — an LLM edit is attributable from *(version, model, cache)*,
never from the version alone.

## Status and limitations

`0.2.0`, alpha. It is research software: the interfaces documented here are the
ones the validation studies and the companion study ran on, and anything that
changes what a run selects moves an operator version or the manifest, never
silently. Changes are listed in [`CHANGELOG.md`](CHANGELOG.md).

What is built: the edit engine, the determinism layer, the taxonomy and contract
lattice, the RENDER, INPUT, LEXICAL and DISCOURSE operators, the UMLS concept
layer, assertion qualification, and the SEMANTIC operators in table and LLM
form. What is not: [`docs/corruption-taxonomy-status.md`](docs/corruption-taxonomy-status.md)
names every unbuilt row of the source taxonomy: 13 implemented, 5 partial and
11 not built, of the 29 rows in `docs/source-taxonomy.md`.

Know these before you rest a result on it:

- **English only, and developed on one kind of note.** The header lexicon, the
  section grammar and the targeting resources were built on MIMIC-IV discharge
  summaries from one centre under one de-identification scheme. The structural
  layer was also run on a synthetic multi-format corpus and on dictated
  MTSamples reports; the concept and phenotype layers have no gold standard
  outside MIMIC.
- **Controlled perturbation, not simulated reality.** Each operator is
  motivated by a documented failure mode. A severity sweep does not reproduce
  the joint distribution of errors in any real corpus.
- **No clinician has reviewed the phenotype targets.** The concept sets and
  surface forms were proposed and vetted by language models and curated by the
  authors. Treat a shipped set as a proposal to review for your corpus.
  Measured recall per phenotype is printed by `robustehr taxonomy --phenotypes`.
- **A phenotype target reaches what is written, not what is measured.**
  Evidence carried by a value, an ejection fraction or a body-mass index, has
  no concept to match and no string to declare. Read reach by tier before
  calling a phenotype robust.
- **Entity linking is not competitive** (0.173 on the SNOMED CT challenge
  metric, below the leaderboard median). The matcher is used to place edits,
  not to code notes.
- **Coverage is not damage.** Operators are dosed on different units. OCR is
  dosed on character positions and, uncapped, can change several characters of
  one word; `tokens_edited` and `tokens_edited_once` on each dose row say how
  many words were hit and how many in a single position.

The full list, with the measurement behind each item, is
[`validation/methodology/09-limitations.md`](validation/methodology/09-limitations.md).
How each component was validated, and what each number may claim, is in
[`validation/`](validation/). Terms used across the documentation are defined
in [`docs/glossary.md`](docs/glossary.md).

## Licence and data

Apache-2.0.

RobustEHR ships no clinical text and no licensed terminology strings. The shipped concept
resources withhold restricted UMLS/SNOMED surface forms and retain identifiers only — CUIs,
plus a `surface_sha256` wherever a term drove a build decision, so a reader can confirm they
hold the same term without the term being redistributed. Resolving those identifiers back to
strings needs your own licensed access; the package never does it for you, and never needs to
at runtime, because matching runs against a frozen identifier set.

Two kinds of resource ship in the clear because no licence reaches them. The surface
resources — phenotype anchors and stop surfaces, header, cue and abbreviation lexicons,
the OCR, keyboard and phonetic tables — are author-written English derived from no
vocabulary. `clinical_salience.json` is a type-level statistic: for each of 8,668 token
types, the share of its occurrences that fell inside an expert-annotated clinical span in
the 272 SNOMED CT Entity Linking Challenge notes. It carries no note text, no span, no
document identifier and no sequence of tokens, and it cannot be inverted to any note; it is
published as an aggregate measurement on the same footing as the recall figures in
`validation/`, and the reading of the data use agreement that permits that is the
authors'.

If you use this repository with MIMIC-IV, note text is restricted under the PhysioNet
Credentialed Health Data Use Agreement and must never be committed. `data/` is
gitignored for that reason.

---

Built by the [Open Health Data Lab](https://github.com/open-health-data-lab).
