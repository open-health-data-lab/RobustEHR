# Phenotype concept sets in the MIPA corpus

Generated — do not hand-edit:

```bash
python validation/phenotype/scripts/phenotype_link_audit.py --facets --full
python validation/phenotype/scripts/phenotype_corpus_coverage.py
```

Corpus: 1,388 MIMIC-IV discharge summaries (mention cache `6e56a7c3a64d53ff`), 18,610 distinct CUIs corpus-wide. Concept sets are the vetting-gated runtime sets (`phenotype_vetting.yaml` sha `da3a2c09ef1d5411`).

`declared` is what `build()` carries; `reachable` is what the matcher recovers from a concept's own preferred name; `observed` is what the corpus contains at least one mention of. An unobserved-but-reachable concept is one ICU discharge summaries do not write — expected, and a fact about the corpus. An unreachable one is a pipeline gap. `head90` is how many concepts carry 90% of the phenotype's mentions — evidence is expected to concentrate heavily.

**This table measures the concept warrant alone, and `reachable` is therefore a floor rather than the pipeline's reach.** Evidence is admitted on either of two warrants: a concept-set membership, which is what is counted here, or a declared surface form matched literally. A concept the matcher cannot recover from its own preferred name is counted unreachable in this column even when a declared anchor reaches the same text — which is the case the anchors exist for, since an organism or a qualifier has no `is-a` path to a disorder set at any hop count. Read the surface warrant from `validation/measurements/phenotype_gap_audit.json`, and the two together from methodology 16; neither column below moves when an anchor is added or removed.

| phenotype | declared | reachable | observed | obs. share | notes w/ any | head90 | unobs. reachable | unobs. unreachable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hypertension | 3167 | 2202 | 302 | 10% | 97% | 75 | 1940 | 925 |
| rheumatoid_arthritis | 3044 | 1912 | 209 | 7% | 89% | 50 | 1720 | 1115 |
| fever | 2712 | 1415 | 120 | 4% | 98% | 28 | 1304 | 1288 |
| metastatic_cancer | 2292 | 1931 | 179 | 8% | 92% | 39 | 1771 | 342 |
| heart_failure | 2218 | 1596 | 270 | 12% | 95% | 79 | 1359 | 589 |
| depression | 1533 | 1220 | 189 | 12% | 87% | 68 | 1044 | 300 |
| hfref | 1399 | 1013 | 208 | 15% | 93% | 61 | 825 | 366 |
| diabetes_mellitus | 1333 | 1088 | 117 | 9% | 67% | 19 | 981 | 235 |
| chronic_kidney_disease | 1284 | 563 | 85 | 7% | 99% | 17 | 497 | 702 |
| chest_pain | 1187 | 855 | 179 | 15% | 99% | 37 | 700 | 308 |
| hfpef | 1177 | 829 | 156 | 13% | 97% | 40 | 688 | 333 |
| systemic_lupus_erythematosus | 1023 | 588 | 112 | 11% | 95% | 26 | 488 | 423 |
| type_2_diabetes | 890 | 702 | 101 | 11% | 71% | 19 | 609 | 180 |
| obesity | 860 | 362 | 25 | 3% | 91% | 6 | 344 | 491 |
| dyspnea | 778 | 440 | 84 | 11% | 93% | 21 | 362 | 332 |
| dementia | 687 | 600 | 79 | 12% | 53% | 30 | 527 | 81 |
| atrial_fibrillation | 581 | 414 | 93 | 16% | 94% | 22 | 335 | 153 |
| pulmonary_embolism | 518 | 324 | 65 | 13% | 96% | 19 | 265 | 188 |
| type_1_diabetes | 415 | 279 | 58 | 14% | 89% | 16 | 229 | 128 |
| deep_vein_thrombosis | 354 | 308 | 35 | 10% | 52% | 10 | 277 | 42 |
| clostridioides_difficile | 196 | 152 | 47 | 24% | 94% | 10 | 109 | 40 |
| alcohol_use_disorder | 184 | 146 | 34 | 18% | 44% | 10 | 116 | 34 |

## Label-positive cohorts

For phenotypes with expert labels: how much of the set the positive notes instantiate, and the enrichment screen. Median enrichment is the note-rate ratio (positive vs rest) across observed concepts; flags are concepts as common outside the cohort as in it — a review queue, not a precision measurement (labels are per-admission and ICU notes co-report comorbidities).

| phenotype | positive notes | observed in cohort | cohort notes w/ any | median enrichment | flagged non-specific |
|---|---:|---:|---:|---:|---:|
| alcohol_use_disorder | 155 | 27 | 86% | 6.69 | 1 |
| clostridioides_difficile | 124 | 41 | 98% | 3.89 | 10 |
| deep_vein_thrombosis | 340 | 29 | 85% | 3.08 | 3 |
| dementia | 102 | 59 | 100% | 4.74 | 2 |
| depression | 679 | 182 | 100% | 3.13 | 6 |
| hfpef | 217 | 117 | 100% | 1.79 | 7 |
| hfref | 122 | 140 | 99% | 3.43 | 8 |
| hypertension | 940 | 288 | 100% | 2.0 | 9 |
| metastatic_cancer | 168 | 137 | 99% | 19.61 | 8 |
| obesity | 286 | 22 | 100% | 3.84 | 3 |
| pulmonary_embolism | 340 | 58 | 100% | 1.65 | 14 |
| rheumatoid_arthritis | 164 | 127 | 99% | 2.47 | 5 |
| systemic_lupus_erythematosus | 113 | 76 | 100% | 3.73 | 4 |
| type_1_diabetes | 135 | 46 | 99% | 3.07 | 7 |
| type_2_diabetes | 393 | 89 | 98% | 7.58 | 3 |

the cohort screen compares note-rates between label-positive and other notes. Labels are per-admission and ICU notes co-report comorbidities, so a flagged concept may still belong in the set — this is a review queue, NOT a precision measurement, and it does not close the union-precision gap in validation/methodology/14 §5. Flag rule: enrichment < 1.5 and present in >= 5% of non-positive notes.

## Recovered evidence (the closure's measured effect)

The headline column is **notes w/ recovered evidence**: notes containing at least one mention of an adjudicated closure keep or an RxNorm identity variant — evidence the pre-closure `pheno=` target could not reach. The candidate pool is deliberately broad (one corpus-blind graph hop), so its own mention prevalence saturates; mentions of dropped candidates are correctly rejected noise, not a residual gap.

| phenotype | scope | notes w/ recovered evidence | closure-keep mentions | notes w/ closure keep | notes w/ identity variant |
|---|---|---:|---:|---:|---:|
| alcohol_use_disorder | label_positive_cohort (155) | **12%** | 27 | 18 | 0 |
| atrial_fibrillation | whole_corpus (1388) | **42%** | 234 | 105 | 566 |
| chest_pain | whole_corpus (1388) | **55%** | 430 | 236 | 684 |
| chronic_kidney_disease | whole_corpus (1388) | **92%** | 4,092 | 1265 | 220 |
| clostridioides_difficile | label_positive_cohort (124) | **61%** | 10 | 7 | 76 |
| deep_vein_thrombosis | label_positive_cohort (340) | **19%** | 101 | 65 | 0 |
| dementia | label_positive_cohort (102) | **50%** | 26 | 20 | 39 |
| depression | label_positive_cohort (679) | **99%** | 1,379 | 620 | 559 |
| diabetes_mellitus | whole_corpus (1388) | **45%** | 3,256 | 589 | 359 |
| dyspnea | whole_corpus (1388) | **19%** | 418 | 251 | 23 |
| fever | whole_corpus (1388) | **80%** | 8 | 6 | 1106 |
| heart_failure | whole_corpus (1388) | **73%** | 1,023 | 488 | 910 |
| hfpef | label_positive_cohort (217) | **98%** | 1,178 | 206 | 184 |
| hfref | label_positive_cohort (122) | **97%** | 187 | 85 | 116 |
| hypertension | label_positive_cohort (940) | **88%** | 429 | 235 | 805 |
| metastatic_cancer | label_positive_cohort (168) | **96%** | 940 | 160 | 57 |
| obesity | label_positive_cohort (286) | **89%** | 42 | 18 | 254 |
| pulmonary_embolism | label_positive_cohort (340) | **76%** | 207 | 113 | 237 |
| rheumatoid_arthritis | label_positive_cohort (164) | **89%** | 9 | 7 | 146 |
| systemic_lupus_erythematosus | label_positive_cohort (113) | **92%** | 100 | 49 | 93 |
| type_1_diabetes | label_positive_cohort (135) | **93%** | 1,114 | 118 | 100 |
| type_2_diabetes | label_positive_cohort (393) | **92%** | 1,718 | 330 | 245 |
