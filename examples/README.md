# Walkthrough

A complete run in about five minutes, on a corpus that ships with the package.
No UMLS licence, no clinical data access, no credentials, no network.

Every command below was run against `demo_notes.csv` to produce the output shown.

---

## The demo corpus

[`demo_notes.csv`](demo_notes.csv) is 32 synthetic notes describing no real patient.
They are the same fixtures the test suite uses to check that the segmenter is not
tuned to one institution, so the corpus is deliberately varied: MIMIC and i2b2
discharge summaries, Epic progress notes, an NHS clinic letter, French-Canadian
consultations, radiology and pathology reports, a dialysis run sheet, home-care
nursing notes and a legacy all-capitals document — across 7 care settings, 23
specialties and 8 de-identification conventions.

It carries `setting`, `specialty`, `format`, `language` and `deid_scheme` columns
so you can slice results, but the engine only ever reads `note_id` and `text`.

> **Your own corpus** needs nothing more than `note_id` and `text`. Optional
> `patient_id` enables the copy-forward operators and patient-clustered
> resampling; optional `timestamp` orders the copy-forward donor. No label column
> is read by the core, ever.

---

## Install

Not yet on PyPI. Install from a checkout:

```bash
git clone https://github.com/open-health-data-lab/RobustEHR.git
cd RobustEHR
python -m venv .venv && source .venv/bin/activate    # Python 3.11+
pip install -e .
```

That is the **core** install: three dependencies, no terminology, no network. It
runs every step below. Where a licensed UMLS index adds something, the step
says what.

```bash
robustehr --version
```

---

## 1. What can this corpus even be corrupted with?

Settle applicability before choosing a dose. An operator that finds no eligible
units in your corpus will report a corpus-wide zero that reads like a finding.

```bash
robustehr applicability --corpus examples/demo_notes.csv
```

Reports, per structural level, how many units exist and what share of notes have
any. On the demo corpus that is 32 notes across 16 unit kinds. If `aligned_block`
is zero here, `render.lab_block_collapse` has nothing to act on and belongs in
no experiment you run on this corpus.

## 2. Characterise the corpus before touching it

`describe` is Table 1: one deterministic characterisation, organised by the
structural level an operator can target, so every unit that could be corrupted has
a measurement beside it.

```bash
robustehr describe --corpus examples/demo_notes.csv --markdown
```

```
# Table 1 — characteristics of demo_notes.csv

**32 notes.** Rows are the structural levels an operator can target …

| Characteristic | Per note, median [IQR] | Total | Share |
|---|---:|---:|---:|
| **Document** | 1 [1-1] | 32 |  |
|     Lines | … | … |  |
| **Sections** | … | … |  |
|     Canonical ids present, of 58 declared |  | … |  |
|     Absent — a fact about the corpus, not a missing row |  | … |  |
```

**This needs no terminology.** Every structural and character level is measurable
without a UMLS licence, which is what lets a reader without one reproduce this
half of the table. The concept and assertion rows read "Not measured" rather
than zero or disappearing: a corpus with no cues and a corpus nobody looked at
must not look alike.

## 3. Corrupt it

Two axes, and they are independent: the **scale** is the operator, the **target**
is the span.

```bash
robustehr run --corpus examples/demo_notes.csv --out demorun/ \
    --operators input.typo --severities 0.10 0.30
```

The manifest it prints is the point of the tool:

```
cells: 64
notes: 32
edits: 1439
severities: ["0.10", "0.30"]
document_selection: {"of": 32, "selected": 32}
contains_note_text: false
replacement_form: "minimal_diff"
edits_sha256: fb13af0fce98bf8e5f487c0279b6681e279af3dc1ffac438f4274c5f135cdaa4
dose_sha256:  a8002d3bdea284c314aa81fe076fae3b1a79e0d050781e962164d09ddf4d9cad
environment:  {"platform": "…", "python": "3.12.13", "robustehr": "0.2.0"}
resource_digests: {"headers.yaml": "a1da8482…", "sentences.yaml": "e27c7468…"}
```

Three things worth noticing:

- **`contains_note_text: false`.** The run directory holds offsets, counts,
  hashes and minimal replacements: each of these 1,439 typographical errors is
  stored as one position and one letter, not as the word it was made in. No
  span of a note is written unless you ask for it. The script is still derived
  from the corpus, and [`docs/run-artifact.md`](../docs/run-artifact.md) says
  what each operator's edits imply, so you can decide what to publish.
- **`edits: 1439`** is the *realized* dose. The requested severity was a fraction
  of each operator's own eligible unit; what actually landed is counted separately,
  and only the realized number is interpretable.
- **Severities nest.** The units selected at `0.10` are a subset of those at
  `0.30`, so this is a paired dose–response curve rather than two independent
  samples.

## 4. Prove it reproduces

```bash
robustehr replay --run demorun/ --corpus examples/demo_notes.csv
```

```json
{ "verified": 64, "failed": 0, "failures": [] }
```

Every cell was reconstructed from its edit script and matched against its recorded
hash. This is the property that lets you send `demorun/` to a collaborator who
holds their own copy of the corpus: they replay it and get byte-identical text,
without a single note crossing between you.

## 5. What did the corruption cost?

Measure the corrupted corpus with the *same instrument* as the clean one.

```bash
robustehr describe --run demorun/ --corpus examples/demo_notes.csv
robustehr compare  --run demorun/ --corpus examples/demo_notes.csv --markdown
```

`compare` reconstructs each corrupted note by replaying its edit script, so it
provably describes the run being reported — no `--emit-text` needed:

```
operator        sev  applied  concepts   delta  pheno d  by category
input.typo rate:0.1        6        42      -2       +0  anatomy -1, disease +1, finding -1, medication -1
input.typo rate:0.3       16        42      -7       +0  anatomy -4, disorder -2, finding -1, medication -1
input.typo rate:0.1      108       524     -31       +0  anatomy +2, device -2, diagnostic_procedure -4, disease -6
input.typo rate:0.3      322       524     -89       +0  anatomy -8, device -2, diagnostic_procedure -12, disease +1
```

Read the columns: `applied` is realized dose, `concepts` is what the note
contained before corruption, and `delta` is how many concept mentions the matcher
lost. The category breakdown is what tells you whether the damage landed on
medications or on connective prose — the difference between a robustness result
and a dilution result.

> The output above was produced with a QuickUMLS index. Without one this still
> runs and reports the structural comparison only; the concept columns are
> omitted rather than guessed.

## 6. Aim it three ways

Everything above is unaimed: edits land wherever the operator's eligible units
are. A run can instead declare one of three levels of aim, and all three run on
the core install. [`aim_note.csv`](aim_note.csv) is a four-line synthetic
brief hospital course about a patient with hypertension. The commands below
produced the output shown; `--emit-text` is only there so the note can be read
back, and it must point under `data/`.

```bash
robustehr run --corpus examples/aim_note.csv --out aim/none --operators input.typo \
    --severities 0.15 --salt figure5-0 --emit-text data/aim/none
robustehr run --corpus examples/aim_note.csv --out aim/clinical --operators input.typo \
    --severities 0.15 --salt figure5-0 --emit-text data/aim/clinical --target clinical
robustehr run --corpus examples/aim_note.csv --out aim/phenotype --operators input.typo \
    --severities 1 --salt figure5-0 --emit-text data/aim/phenotype \
    --target pheno=hypertension --phenotype hypertension
```

The dose record of each run (`dose.jsonl`) says what the aim admitted:

| aim | `scope` | in scope | withheld by protection | eligible | requested / applied | hypertension evidence touched |
|---|---|---:|---:|---:|---:|---:|
| none | `target=all` | 36 words | 5 | 31 | 5 / 5 | 0 of 2 |
| clinical content | `sel=clinical(salience>=0.5,drug,labelled,unseen)` | 12 | 0 | 12 | 2 / 2 | 0 of 2 |
| one phenotype's evidence | `sel=pheno=hypertension` | 3 | 0 | 3 | 3 / 3 | 2 of 2 |

Read down the eligible column: the whole note, then the clinical words, then
only `HTN` and `chronic hypertension`. The protection row is the header, the
de-identification placeholder and the age, which no aim may touch.

**No aim** spends its five edits anywhere:

```
Ms. ___ is a 72 year old woman with HTN, hyperlipidemia and osteoarthritis admitted woth pneumonia.
Her home lisinopril was conrinued and blpod pressure remained wdll controlled on tye floor.
```

**Clinical content** spends its two on clinical words, which may or may not be
about hypertension:

```
Discharge diagnoses: community acqyired pneumonia; cheonic hypertension, stable on lisinopril.
```

**One phenotype's evidence** touches the diagnosis and nothing else:

```
Ms. ___ is a 72 year old woman with HFN, hyperlipidemia and osteoarthritis admitted with pneumonia.
Discharge diagnoses: community acquired pneumonia; chromic htpertension, stable on lisinopril.
```

Two things to notice. `lisinopril` was not eligible under the phenotype aim:
it is evidence through the *concept* warrant (an antihypertensive in the
declared concept set), which needs the UMLS matcher. With no licensed
terminology on the machine the run says so on stderr, builds the target from
the declared surface forms alone, and writes `warrants: [surface]` into the
manifest's `targeting` block, so the artifact records the weaker target. And
the clinical aim is not `concept`: any UMLS mention was measured to admit
45.7% of a discharge summary's tokens, headings and pronouns included, which is
why the rule is a measured one (`validation/protocol.md` section 9).

With the terminology extras and a licensed index, the concept warrant joins
in and the finer predicates become available:

```bash
pip install -e ".[umls,terminology,clinical]"
python -m quickumls.install -L -U -E ENG <umls>/META data/quickumls_index
robustehr target 'all(cat=medication;pheno=hypertension)'   # explain a target, no data needed
```

## 7. The baseline table, and the same table after corruption

`describe` is the characterisation instrument. Run on the clean corpus it is
Table 1 (step 2). Run on a corruption run it reconstructs every cell from its
edit script and reports the same rows again, one column per cell, so a
corruption's cost is read against its own denominator:

```bash
robustehr describe --run demorun/ --corpus examples/demo_notes.csv --markdown
robustehr describe --run demorun/ --corpus examples/demo_notes.csv --out demorun/describe.json
```

```
| Characteristic, per note | Clean corpus | `input.typo@rate:0.3` | `render.header_delete@rate:0.3` |
|---|---:|---:|---:|
| Lines                     | 20 [14-27]    | 20 [14-27]    | 20 [13-27]    |
| Characters                | 848 [654-1163] | 848 [654-1163] | 848 [605-1163] |
| OCR-confusable characters | 511 [391-702] | 501 [387-689] | 497 [375-671] |
| Sections                  | 2 [1-5]       | 2 [1-5]       | 2 [1-4]       |
| Standalone headers        | 0 [0-3]       | 0 [0-3]       | 0 [0-2]       |
```

A typo changes no structural count and removes OCR-confusable characters;
header deletion removes headers, sections and the characters on the deleted
lines. The JSON form carries every level and every quantile. Every row shown
is measured without a terminology; the concept and assertion rows read "Not
measured" on an install without one.

## Writing the experiment down

Flags are fine for one operator. An experiment is easier to write down, and a
recipe is what the manifest records:

```yaml
# examples/recipe.yaml
seed: rep0
documents: {fraction: "0.50"}          # reproducible, and 0.25 ⊆ 0.50
corruptions: [input.typo, input.ocr_confusion]   # operator ids or family names
corruptions_per_document: {min: 1, max: 2}
severity: medium                       # resolved against each operator's own ladder
params:                                # per operator; recorded on every dose row
  input.ocr_confusion: {max_edits_per_token: 1}
target:
  mode: clinical                       # random | clinical | umls | non_umls
```

```bash
robustehr run --corpus examples/demo_notes.csv --config examples/recipe.yaml --out run/
```

This runs on the core install. With a QuickUMLS index, `mode: umls` aims at
concept mentions, optionally narrowed with `semantic_categories: [medication]`
and `phenotype: hypertension`. An aimed recipe may list only character- and
word-level operators: the loader refuses `corruptions: [structural]` under any
aim but `random`, because a header is not a concept span.

Severities are quoted strings, never YAML floats — `0.1 + 0.2 != 0.3`, and a float
on a control-flow path is how a dose–response curve stops being replayable. The
loader refuses one and names the fix.

---

## Where to go next

| You want | Read |
|---|---|
| every operator, level and contract | [`../docs/corruption-catalogue.md`](../docs/corruption-catalogue.md) |
| the end-to-end pipeline, drawn | [`../docs/pipeline.md`](../docs/pipeline.md) |
| how to aim a corruption precisely | [`../docs/targeting-design.md`](../docs/targeting-design.md) |
| what is implemented and what is not | [`../docs/corruption-taxonomy-status.md`](../docs/corruption-taxonomy-status.md) |
| whether the method is sound | [`../validation/`](../validation/) |
