# Semantic categories

## Why "is this word clinical" was abandoned as an *intrinsic* question

The question is too broad to answer from a word's properties alone. Three
independent attributes were tested as discriminators — general-English
frequency, source-vocabulary count, semantic group — and all three failed to
separate `one`, `well`, `normal` and `stairs` from `dyspnea` and `pneumonia`
— see [06-lexicon-construction](06-lexicon-construction.md).

The failure is structural rather than a matter of picking a better filter:
`stairs` is a Disorder concept because of *difficulty climbing stairs*;
`discharge` is clinical in *purulent discharge* and administrative in *discharge
summary*. No word-level classifier can resolve these from the lexicon, because
the ambiguity is not in the classifier.

It is also not what most use cases want. Nobody asks to "corrupt the clinical
words"; they ask to corrupt the medications, or the diagnoses but not the
symptoms.

Two questions replace it for targeting, and between them they cover what most of
a robustness experiment needs:

1. **What semantic category does this term belong to?**
2. **Is it associated with a given phenotype?** — the concept layer.

Neither requires a universal definition of "clinical".

## What changed: the question is answerable *empirically*

Experiment 2 needed something the two replacements do not provide — "corrupt the
clinical content and not the prose" — and the obvious proxy, *restrict to UMLS
mentions*, was measured and does not deliver it. Full result:
[validation-protocol §9](../protocol.md#9-clinical-targeting-for-concept-restricted-corruption).

The three attributes above are all **intrinsic**: properties of a word in a
lexicon. A fourth kind of attribute was not tried — an **empirical** one, of the
form *how often is this token actually inside a span a clinician adjudicated as
clinical?* Measured against the SNOMED CT Entity Linking Challenge annotations
over MIMIC-IV discharge summaries, on held-out notes:

| rule | precision | recall | F1 | coverage |
|---|---:|---:|---:|---:|
| any UMLS mention | 0.500 | 0.785 | 0.611 | 45.7% |
| mention ∧ not general-English | 0.551 | 0.648 | 0.596 | 34.2% |
| **salience ≥ 0.50** | **0.890** | 0.767 | **0.824** | **25.0%** |

Gold rate is 29.1% of word tokens, so the salience rule selects about as much
text as an annotator marks; "any UMLS mention" selects 1.6× that.

This does **not** overturn the paragraph above. `discharge` is still ambiguous in
principle, and salience cannot resolve *purulent discharge* from *discharge
summary*. What it exploits is narrower and should be stated as such: within one
corpus and one note type, most tokens are used one way, and the rate is
measurable. The claim is about MIMIC-IV discharge summaries, not about English.

### Three limits that travel with it

- **Corpus-specific.** Trained and validated on MIMIC-IV discharge summaries.
  Radiology reports, outpatient letters, or another institution require
  re-measurement, not reuse.
- **Context-blind.** Token-level by construction. The 0.89 precision reflects
  that words are mostly monosemous *in this corpus*, not that the ambiguity was
  solved.
- **Inherits the benchmark's blind spots.** This is not hypothetical — it bit,
  and the correction is [below](#the-benchmark-does-not-annotate-everything).

## The benchmark does not annotate everything

A salience lexicon learns the annotators' *scope*, not the language. Measured
per category, the SNOMED EL gold covers our mentions very unevenly:

| our category | in gold | | our category | in gold |
|---|---:|---|---|---:|
| symptom | 80.6% | | disorder | 56.9% |
| diagnostic_procedure | 74.7% | | therapeutic_procedure | 54.9% |
| lab_measurement | 72.0% | | **device** | **33.6%** |
| disease | 70.8% | | **medication** | **27.2%** |

The medication gap is not a modelling artefact and it is not subtle: **21 of 23
common drugs would be rejected as non-clinical** — `metoprolol` appears 213
times in the training notes and *never once* inside a gold span, because the
annotators marked drugs in prose (`heparin`, `lasix`) but not the structured
discharge-medication list. A rule built on salience alone corrupts clinical text
while systematically sparing every drug name, which is close to the opposite of
what a clinical robustness experiment should do.

The same failure appears on laboratory analytes, from annotator inconsistency
rather than scope: `hct-`, `hgb-`, `na-`, `creat-` score 0.95–0.99, while
`amylase-` scores 0.29 and `lipase-` 0.43. In a pancreatitis note those are the
diagnostic results.

**So the rule is not salience alone.** Each additional clause exists because a
measurement showed the previous rule failing, and each is grounded in a source
that does not share the benchmark's blind spot:

```
salience ≥ 0.50                        empirical, validated above
∨ token ∈ curated drug vocabulary      gold annotates 27% of medications
∨ token inside a structural lab span   annotators inconsistent on analytes
∨ (mention ∧ unseen ∧ not general-English)   unseen clinical terms
```

Two failure modes were found by reading whole annotated notes, and **neither was
visible in precision, recall or F1** — which is the argument for doing it:

1. Salience alone excluded almost every drug (above).
2. The lab-analyte clause is positional — a token *inside* a labelled-value
   span — rather than a match on the analyte's surface form. Matched by surface,
   `Mg-1.9` (magnesium, a lab) makes every `mg` (milligram, a dose unit)
   eligible, and `mg` becomes the single most-corrupted token in the corpus at
   714 occurrences.

Residual gaps, documented rather than papered over: multi-word generics
(`Ferrous Sulfate`) are missed because the drug vocabulary is single-token by
construction; `lipase-` is still missed where it is not parsed as a labelled
value. Both *reduce* clinical coverage, so they bias the experiment toward
finding no effect — the conservative direction.

## The twelve categories

```
anatomy
device
disorder
├── disease
├── symptom
└── finding   (excluded from clinical_any)
lab_result
lab_measurement   (spans T034 and T059 — deliberately overlaps both below)
medication
procedure
├── therapeutic_procedure
└── diagnostic_procedure
```

**`lab_measurement` is the one category defined by a disagreement rather than by
a distinction.** UMLS types `hgb` as T034, a test *result*; the SNOMED challenge
annotators chose a T059 concept, the *procedure* that produces it. Both readings
of `Hgb-9.9` are defensible, roughly 640 abbreviation-shaped gold spans turn on
it, and it is the largest single bucket of otherwise-correct matches scored
wrong. Neither convention is corrected, because neither is mistaken. The category
is how a user says *the analyte, however it is typed* without needing to know
which convention their corpus was annotated under.

It deliberately overlaps `lab_result` and `procedure`, which is why the taxonomy
permits a TUI to belong to several categories at once. Adding it changed no
existing measurement: T034 and T059 were already admitted through those two
parents, so `default_tuis()` is byte-identical and the matcher returns exactly
the same spans. It adds a row to every per-category report and moves nothing.

Granularity is the **semantic type (TUI), not the Semantic Group**. McCray's
groups put Disease or Syndrome (T047) and Sign or Symptom (T184) both in `DISO`,
so a group-level target cannot tell a diagnosis from a symptom — precisely the
distinction a phenotyping study turns on.

Categories removed after measurement, for irrelevance to notes rather than
indefensibility: `chemical` (matches were abbreviation collisions), `organism`
(149 of 99,788 terms ever occurred), `physiology` (overlapped disorder and
finding).

## Three tiers of evidence

Every gold standard is coarser than the distinctions a phenotyping study needs,
so categories are nested and each declares how strongly its boundary is
evidenced. The tier travels with every result.

| Tier | Categories | What may be claimed |
|---|---|---|
| **anchored** | disorder, procedure, anatomy, medication, lab_measurement | P/R/F1 against expert annotations |
| **derived** | disease, symptom, finding, therapeutic_procedure, diagnostic_procedure | the *parent's* metrics; the split is a deterministic refinement |
| **unanchored** | device, lab_result | usable, labelled, never a headline |

Splitting `disorder` into disease versus symptom is clinically necessary —
"missed the diagnosis" and "missed the symptom" are different failures — but no
corpus adjudicates that split, and claiming it validated because `disorder` is
would be exactly the overclaim the tiers prevent.

Two consistency checks run at load. A derived category's semantic types must be
a subset of its parent's, since a child escaping its parent would report results
under a boundary that does not contain them. And an anchored category must
declare a crosswalk, so "anchored" is a commitment rather than a label.

## T033 "Finding", and why the exclusion is provisional

T033 is in the taxonomy but quarantined in `finding` and excluded from the
default. The exclusion was adopted because bare `stairs`, `one`, `well` and
`normal` matched at word level — a symptom of word-level lookup rather than a
defect in the semantic type.

**The field disagrees with the exclusion**, and it is right to for span-level
work: QuickUMLS keeps T033 among its 27 default types, MedMentions ST21pv among
its 21, and the SNOMED challenge's `clinical finding` hierarchy is largely T033
territory. "Difficulty climbing stairs" is a legitimate finding; only bare
`stairs` was ever the problem.

The exclusion is therefore marked provisional with a protocol attached: run the
targeting-precision measurement with and without T033 on the SNOMED challenge
and keep whichever the gold standard supports. This is the template for every
judgement call in the taxonomy — state it, mark it provisional, let a
measurement close it.

## Exclusions subtract

An excluded category is usually a subset of an included parent, so merely
omitting it from the union does nothing: `finding` is part of `disorder`, and
leaving it out still admits T033 through the parent.

Exclusions therefore **subtract**. The consequence is that the unnamed default
is narrower than `disorder`, while naming a category explicitly always yields
exactly that category — targeting `disorder` does include findings, because that
is what the SNOMED hierarchy means.
