# Glossary

Terms as this repository uses them. Where a word has more than one meaning
here, each is listed.

## Running a corruption

**Operator.** One named, versioned transformation, such as `input.typo`.
Listed by `robustehr taxonomy`.

**Unit.** What an operator counts and selects: a word, a character position,
a header, a sentence. The unit is the denominator of the dose.

**Level.** Three unrelated uses. (1) The *structural level* of a unit, from
character to document. (2) The *level of aim*: none, clinical content, or one
phenotype's evidence. (3) In a recipe, a *severity level* name (`low`,
`medium`, `high`).

**Channel.** The process an operator simulates: `render`, `input`, `lexical`,
`discourse`, `semantic`, or `control`.

**Contract.** What an operator's output may claim about the note's meaning.
See the README, "Operator contracts".

**Severity.** How much is asked for: a rate over eligible units (`0.10`) or a
count per note (`count:2`). **Dose** is what was done; the dose record keeps
requested and realized apart.

**Coverage and damage.** *Coverage* is the share of units an operator was
asked to touch. *Damage* is how much of each touched unit changed. They
differ: an OCR arm at a given coverage may change several characters of one
word. `tokens_edited_once` and `acer` on the dose row measure damage.

**Cell.** One note under one operator at one severity. One row of
`dose.jsonl`.

**Salt.** A replicate label. The same salt always draws the same units.

**Recipe.** A YAML file describing a run, passed with `--config`.

**Edit script.** `edits.jsonl`: the applied edits, as offsets and minimal
replacements. See [run-artifact.md](run-artifact.md).

**Replay.** Rebuilding corrupted notes from an edit script and your own copy
of the notes, and checking each against its recorded hash.

## Choosing where edits land

**Scope.** Four unrelated uses. (1) *Section scope*: restrict an operator to
named sections. (2) *Phenotype scope* (`--phenotype-scope`): whether declared
evidence is ignored (`agnostic`), withheld from every operator (`protect`), or
the only thing eligible (`target`). (3) The `scope` string on a dose row: the
canonical description of the aim that feeds the seed. (4) In assertion
detection, the stretch of a sentence a cue governs.

**Aim** or **target.** The rule that decides which units are eligible, given
with `--target`. The three levels of aim are `all`, `clinical` and
`pheno=NAME`. In a recipe the same choice is `target.mode`: `random` (no aim),
`clinical`, `umls` (concept mentions) or `non_umls`.

**Atom.** One predicate in a target expression, such as `cat=medication` or
`pheno=hypertension`. Atoms combine with `all(a;b)`, `any(a;b)` and `not(a)`.

**Clinical.** Three unrelated uses. (1) The `clinical` aim: tokens a measured
rule calls clinical content. (2) The `clinical` install extra: assertion
detection. (3) `clinical_any`: the union of the default semantic categories,
used when a target names a concept but no category.

**Protection.** Spans an operator may not edit unless it declares their class:
de-identification placeholders, numeric values, dosages, headers, list
markers, assertion cues.

## Concepts and categories

**Concept.** A UMLS concept, identified by a CUI. **Mention**: a span of a
note the matcher linked to a concept.

**Semantic category.** A named set of UMLS semantic types, such as
`medication`. Categories overlap: a concept can be in several. Defined in
`resources/semantic_categories.yaml`; see [categories.md](categories.md).

**Primary category.** The one category a concept is counted under in a table
whose rows must sum, by a fixed precedence (`robustehr.categories.primary_category`).
`no_concept` means no concept covers the word; `uncategorized` means a concept
matched and none of its types is in the partition.

**Display group.** Primary categories grouped for reading: Diseases and
diagnoses; Signs, symptoms and findings; Procedures and tests; Medications;
Anatomy; Other.

**Facet.** Within a phenotype's concept set, why a concept is there:
`disorder`, `medication`, `finding`, `proposed` or `closure`.

**Closure.** Concepts one relation away from a phenotype's seed set, proposed
as candidates and kept only if vetted.

## Phenotype evidence

**Phenotype target.** For one phenotype, the spans of a note that count as
evidence for it.

**Warrant.** The reason a span counts as evidence. *Concept warrant*: the
span's concept is in the phenotype's concept set. *Surface warrant*: the
span's text matches a form declared for the phenotype.

**Concept set.** The CUIs declared for a phenotype
(`resources/phenotypes.yaml` and the files it is built from).

**Surface form.** A word or phrase matched by how it is spelled, with case,
spacing and punctuation ignored. A word list, in plain terms.

**Anchor.** Four uses. (1) A surface form that *names the diagnosis*
(`hypertension`, `HTN`). (2) The `anchor` tier. (3) The `anchored` evidence
level of a semantic category, meaning a gold standard validates it; unrelated.
(4) The integer `anchor` field of an edit, which says which side an insertion
attaches to; unrelated.

**Associated** (surface form). A phrase listed for a phenotype that is
related to it without naming it, and that no vocabulary string matched.

**Stop surface.** An ordinary word refused as evidence even when the matcher
links it to a concept in the set.

<a id="tier"></a>**Tier.** Two unrelated uses. (1) For phenotype evidence,
how a span was admitted: one of the five facets under the concept warrant, or
`anchor` or `associated` under the surface warrant. Reported in
`evidence_n_by_tier`; never used to select. (2) For a semantic category, how
well its boundary is validated: `anchored`, `derived` or `unanchored`.

**Reach.** The share of a phenotype's evidence an aimed arm touched:
`evidence_touch / evidence_n`, in total or by tier.

**Set recall.** The share of expert-annotated evidence spans a phenotype
target finds. Printed by `robustehr taxonomy --phenotypes`.

**Nonspecific** (concept). A concept that sits in the sets of several
unrelated phenotypes, such as fatigue. An optional screen
(`phenotype_nonspecific.yaml`) can remove such concepts from the derived
facets. It ships absent, so shipped sets keep them and the tier of each span
says what kind of evidence it is.

## Terms in the companion paper

The study that applied this package to phenotyping with language models uses
plainer words for the same things.

| Companion paper | Here |
|---|---|
| Experiment 1: whole note | `--target all` |
| Experiment 2: clinical words | `--target clinical` |
| Experiment 3: phenotype-targeted | `--target pheno=NAME`, severity `1` |
| Typographical errors | `input.typo` |
| OCR errors | `input.ocr_confusion`. Capped at one character per word in Experiment 3 (`max_edits_per_token=1`), uncapped in Experiments 1 and 2 |
| Coverage | severity, as a rate over eligible words |
| Characters changed, % of note | `acer` |
| Concept set / word list | concept warrant / surface warrant |
| Word list: diagnosis names | `anchor` surface forms |
| Word list: associated phrases | `associated` surface forms |
| Category of a corrupted word | primary category, shown by display group |
| "Other" | the `other` display group: `device`, `uncategorized` and `no_concept` |
| "Not specific" | a word the target *did* select that neither names the diagnosis nor is in the phenotype's word list. Such words are selected because the nonspecific screen above ships absent |
| Churn; true cases lost | computed from model outputs by the study, not by this package |
