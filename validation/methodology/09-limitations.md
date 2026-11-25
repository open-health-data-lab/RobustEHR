# Limitations and claims not made

Stated plainly, because each is an objection a reviewer would otherwise raise.

## Claims not made

**Not "realistic noise" in aggregate.** Each operator is *motivated by* a
documented failure mode, but the joint distribution of a severity sweep
resembles no real corpus. The package generates controlled perturbations, not
simulated reality.

**No external validity beyond the development setting.** English, discharge
summaries, one de-identification scheme, one institution's conventions. The
synthetic multi-format corpus (32 notes, 23 specialties, 8 de-identification
schemes, 5 languages) is what the segmentation layer was built against, and it
is a robustness measure for the *tooling*, not evidence of clinical
generalization.

**Not safety.** This measures input-perturbation sensitivity. It says nothing
about deployment risk, harm, or clinical appropriateness.

**The tool measures robustness; it does not improve it.** No claim is made that
training on corrupted text helps.

**No population estimates.** F1 and PPV are not transportable across prevalence.
Where a corpus is prevalence-enriched that is stated, and sensitivity and
specificity are the quantities reported as transportable.

## Measured limitations of the current implementation

**Word-level tagging is an upper bound, not a rate.** Word-level lookup marks
54.3% of content tokens as clinical, which is not plausible for a discharge
summary. The figure is reported as an upper bound and nothing depends on it.
Concept-level matching is the resolution.

**Three known residual tagging errors**, each a word-level artifact: `times`
removed from general English because UMLS types it a disease; `date` resolving
as a medication via T121; `sig`/`po`/`mg` resolving to out-of-vocabulary pending
the abbreviation resolver.

**The morphological fallback is poor and its cost is published**: precision
0.607, recall 0.103, F1 0.175 against the terminology, with token coverage 3.4%
against 54.3%. It exists so a run without a terminology yields something, not
because it is adequate, and `lexicon_source` records which method was used.

**T033 is excluded provisionally** on word-level evidence, against the practice
of QuickUMLS, MedMentions and the SNOMED challenge. The measurement that would
settle it is specified but not yet run.

**Derived categories are not independently validated.** disease versus symptom
is clinically necessary and no corpus adjudicates it; results carry the tier.

**Two unanchored categories** — device and lab_result — have no gold standard at
all and never carry a headline claim.

## Scope limitations recorded rather than hidden

**Table corruption is absent** because the development corpus contains no tabs
and only 10.3% of notes contain any `|`. Recorded as an explicit scope
limitation rather than silently omitted.

**Diacritic stripping was cut** after measuring zero non-ASCII letters in a
400-note sample — not low yield, *zero*. Folded into unicode normalization and
reported as eligibility = 0 in an appendix.

**Demographic swap was cut from v1.** It is a fairness question needing its own
ethics framing, and burying a fairness audit inside a robustness taxonomy
invites the criticism that we generated synthetic notes asserting false things
about protected groups.

**Non-deterministic operators are rejected outright** — LLM paraphrase,
backtranslation, network-dependent homophone lookup. One non-deterministic
operator would undermine the package's central claim.

## Methodological trade-offs accepted

**Nested severity ladders reduce variance but are not independent draws.** Salt
replicates are required to estimate variance across the ladder; reporting a
dose-response curve without them understates uncertainty.

**Parquet container bytes are not reproducible** even though content is.
Per-record SHA-256 makes content verifiable; the container is not claimed.

**QuickUMLS matching is approximate.** Deterministic given a fixed index and
threshold, so reproducibility holds — but a corruption that perturbs a term can
flip a match, which for this package specifically is a confound to measure
rather than ignore.
