# Measurements

Every quantitative claim in `validation/methodology/` and in the manuscript traces
to a file here, and `validation/tests/test_methodology_docs.py` fails when the two
drift apart. Each artifact answers one question; the script that produces it is
named in the artifact's own `generated_by`, `question` or `what` field, and lives
under `validation/pipeline/scripts/` or `validation/phenotype/scripts/`. Scripts
that need restricted data skip rather than fabricate, and the artifacts they
would have written are absent rather than empty.

The narrative of how each measurement came to be taken, with every correction, is
the development record: [`validation/record/measurements-chronicle.md`](../record/measurements-chronicle.md).

## The concept pipeline

| Artifact | Question it answers |
|---|---|
| `clinical_lexicon.manifest.json` | What the clinical vocabulary was built from: UMLS release, semantic types, 250,613 tokens, ambiguity source |
| `lexicon_fallback.json` | How well the morphology heuristic classifies unknown tokens as clinical (precision 0.607, recall 0.103) — the reason it is a labelled fallback |
| `category_prevalence.json` | Share of content tokens per semantic category in the corpus |
| `snomed_ablation.json` | What each matcher configuration rung buys, on the challenge gold, from QuickUMLS defaults to the shipped policy |
| `challenge_metric_scoped.json` | The SNOMED CT Entity Linking Challenge score on the challenge's own metric (0.173; span detection alone 0.441). `challenge_metric.json` is its superseded sibling, kept so the correction is auditable |
| `benchmark_history.json` | Every configuration scored during development, with the leaderboard reference |
| `head_to_head.json` | Per-category recall and precision of the shipped tagger against stock medspaCy and the scispaCy linker on 12 notes and 3,777 expert spans |
| `structural_labels.json` | What recovering laboratory-panel labels by structural position buys (lab-measurement recall 0.469 against 0.106 matcher-alone) |
| `abbreviation_ceiling.json` | Over 8,520 abbreviation-shaped gold spans: shipped 0.435, exact lookup 0.484, a perfect disambiguator 0.551, unreachable 0.449 |
| `abbreviation_load.json` | How many tokens are abbreviation-shaped and how ambiguous each is, before any operator runs |
| `abbrev_snomed.manifest.json` | The abbreviations SNOMED records through its own `ABBREV - full term` convention, and why the derived list is not committed |
| `expansion_coverage.json` | Whether every entry of the shorthand table resolves to a concept in the installed release |
| `disambiguation_ceiling.json`, `anchor_vote.json` | How much contextual disambiguation can add once most-frequent sense has run, and whether authored cues beat it on held-out data |
| `normalization_ceiling.json`, `spelling_methods.json`, `spelling_precision.json` | The two lexical-normalization instruments measured and not built: reach, precision and recovery |
| `segmentation_baseline.json` | Agreement between the package's sentence boundaries and PyRuSH over 200 notes, with the disagreement taxonomy |
| `protection_audit.json` | Whether the protection registry identifies its classes correctly, and which classes cannot be validated |
| `pipeline_audit.json` | The end-to-end check: parse, baseline, corrupt, re-measure |
| `baseline_profile.json` | The document-quality baseline on the development corpus: pre-existing typos, wrap, de-identification density |

## Assertion (stage 8)

| Artifact | Question it answers |
|---|---|
| `assertion_accuracy.json` | Negated-class F1 on the NegEx test set for the shipped ConText configuration and its comparators (0.929; negspaCy 0.939) |
| `deid_assertion_probe.json`, `assertion_deid_invariance.json` | Whether a verdict changes when only the de-identification convention changes, on stock medspaCy and on the package's boundaries |
| `assertion_stability.json` | Whether an assertion survives a perturbation proved not to change clinical reference |
| `assertion_disagreement.json`, `scope_accuracy.json` | Where the package's boundaries change a concept's assertion, and whether the change is right |
| `assertion_gold_mimic.json`, `assertion_gold_mimic_heldout.json`, `assertion_gold_eval.json`, `assertion_gold_profile.json` | The language-model-annotated MIMIC-IV assertion gold: agreement, held-out F1 per dimension, and what kind of concept carries each assertion |
| `assertion_error_analysis.json`, `assertion_examples.json` | Why stage 8 is wrong when it is wrong, with worked spans |
| `cue_detection.json`, `missing_cues.json`, `cue_direction_sweep.json`, `header_frame_sweep.json`, `header_frame_sweep_heldout.json`, `scope_boundary_sweep.json`, `scope_termination_sweep.json`, `scope_termination_sweep_heldout.json` | The extended cue set and scope rules: what each rule buys on held-out data |
| `context_rule_inventory.json` | What each of stage 8's attributes is made of, counted in triggers rather than rules |
| `assertion_flip_recovery.json`, `assertion_invention.json` | Whether the semantic operators change the dimension they claim to, and whether they ever add a modifier to a plainly asserted concept (35 of 51,031) |
| `assertion_llm_eval.json`, `validate_llm_model.json`, `assertion_neural_eval.json`, `assertion_finetune.json` | The optional language-model arm's gate, and the encoder baselines it is compared with |

## The phenotype target

| Artifact | Question it answers |
|---|---|
| `phenotype_eval.json` | Do we find the evidence an expert annotated for a declared phenotype: span recall and set recall, per phenotype and macro |
| `phenotype_link_audit.json`, `phenotype_link_audit_facets.json` | Does every declared phenotype resolve to a non-empty, surface-bearing concept set, all the way to text |
| `phenotype_set_audit.json`, `phenotype_runtime_sets.json`, `phenotype_density.json` | What is in each concept set by facet and category, what the runtime annotator carries, and what fraction of it the corpus writes |
| `phenotype_reconcile.json`, `phenotype_specificity.json`, `phenotype_ungrounded.json` | The reconciliation pass over vetting drops; the cross-phenotype specificity screen; the proposed terms no vocabulary string matched, carried on the surface warrant |
| `phenotype_corpus_coverage.json` | Per phenotype: declared, reachable and observed concepts in the development corpus, mention concentration, the enrichment screen |
| `phenotype_gap_audit.json` | Reach measured against an independently written term list, by warrant: what the target finds and what stays unreachable |
| `phenotype_assertion.json` | How much expert-annotated phenotype evidence is negated, historical or attributed to someone other than the patient (30.1%) |
| `clinical_targeting.json` | The measured salience rule behind clinical-term targeting (precision 0.820, recall 0.789 against 272 adjudicated notes) |
| `drug_synonyms.manifest.json` | The generic–brand map's provenance; the map itself is built locally |
| `phenotype_nonspecific_candidates.yaml` | Candidates for the specificity screen; the screen is reported and not applied |

## Corpus characterisation

`corpus/` holds the instrument run on three corpora: `mipa_table1.json`/`.md`
(the development corpus), `mtsamples_characterisation.json`,
`demo_characterisation.json` (the synthetic corpus), `mipa_edit_placement.json`
(where edits land, untargeted against concept-targeted) and
`mipa_targeting_showcase.md`.

## What is safe to commit here

Aggregates only. No note text, no span text, no document identifier that
resolves to a restricted record. An artifact that would need any of those is
written under `data/` and gitignored.
