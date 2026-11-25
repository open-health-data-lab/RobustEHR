# Methodology

Submission-ready accounts of each methodological decision in RobustEHR, written
so they can be lifted into a manuscript with minimal rewriting. Each file states
what was done, why the alternative was rejected, and what was measured rather
than assumed.

These differ from `docs/` in audience. `docs/` is for someone using or extending
the package; this folder is for a reviewer asking whether the method is sound.

| File | Manuscript section | Core claim |
|---|---|---|
| [01-design-overview](01-design-overview.md) | Introduction, Architecture | Robustness claims rest on undefined noise; five questions make a perturbation specifiable |
| [02-determinism](02-determinism.md) | Architecture | Byte-identical reproduction across runs, platforms and institutions, without storing text |
| [03-taxonomy-and-contracts](03-taxonomy-and-contracts.md) | Taxonomy | Preservation is a property of the (operator, span, document, phenotype) tuple, except where it is machine-provable |
| [04-dose-accounting](04-dose-accounting.md) | Dose and intensity | "30%" is meaningless without a denominator; achieved ≠ requested and only achieved is interpretable |
| [05-semantic-categories](05-semantic-categories.md) | Concept layer | "Is this word clinical" is unanswerable *intrinsically*; category, phenotype association, and — for one corpus — measured salience are |
| [06-lexicon-construction](06-lexicon-construction.md) | Concept layer | Three lexicons, four discriminators tried, two kept, each failure measured |
| [07-targeting](07-targeting.md) | Architecture | Mechanisms are target-agnostic; selectivity is the contribution |
| [08-validation](08-validation.md) | Validation | Targeting precision gates; recall informs. Crosswalks to four gold standards |
| [09-limitations](09-limitations.md) | Discussion | Claims explicitly not made |
| [15-input-channel-errors](15-input-channel-errors.md) | Taxonomy, Dose and intensity | Typing and scanning are different processes, not different intensities: disjoint error models on the digit rows, one inexpressible per character, and dosed over words versus characters |
| [17-phenotype-association-method](17-phenotype-association-method.md) | Concept layer, Targeting, Validation | The phenotype target: a span is evidence on either of two warrants; how each is built, what each cannot reach, and what a result reports |

## The phenotype target

[17](17-phenotype-association-method.md) states the method once: a target admits
a span on either of two warrants, how the concept set and the surface set are
built, what each cannot reach, and what a result must report. The operational
companion is [validation/phenotype/PIPELINE.md](../phenotype/PIPELINE.md), every
stage in the order it runs; what ships is in
[phenotype-concept-table](../phenotype/phenotype-concept-table.md) and what the
corpus contains in
[phenotype-corpus-coverage](../phenotype/phenotype-corpus-coverage.md). Adding a
phenotype means declaring a seed and running the pipeline.

What a *model* then does with a corrupted target is a question about a
particular model and protocol, not a property of the target, and is reported
separately.

## The development record

Six further chapters were written while their components were built and read as
a history — the abbreviation stage, lexical normalization, context
qualification, and the three parts of the phenotype target. They are kept, with
the protocol addenda and the measurement chronicle, in
[`validation/record/`](../record/), so every decision can be audited back to the
measurement that made it. Nothing there is cited by the manuscript.

## The governing principle: reuse, and benchmark every departure

**Reuse a proven tool. Where we depart from it, measure the departure against it.**

Not a preference — a constraint on what may be claimed. A component written here
instead of reused owes an explanation, and a component *modified* from a reused
one owes a number showing the modification helped. "We improved it" is not a
finding; "on the same corpus and metric, ours recovers 25% more mentions than the
stock configuration" is.

This has already changed decisions in both directions:

| Decision | Reused | Written | Benchmarked against |
|---|---|---|---|
| Concept matching | QuickUMLS via medspaCy | configuration only | stock medspaCy, scispaCy — see [08-validation](08-validation.md) |
| Semantic categories | UMLS semantic types | the category grouping | SNOMED CT Entity Linking Challenge |
| General-English lexicon | `wordfreq` | the clinical subtraction | UMLS-derived ground truth |
| Clinical/non-clinical | — | a morphology heuristic | **measured, failed, demoted** (P 0.607, R 0.099) |
| Sentence segmentation | *rejected* PyRuSH | our structural layer | de-identification probe showed PyRuSH fails on masked placeholders |

The fourth row is the point. A hand-written affix heuristic looked reasonable
until it was measured against the terminology, at which point it was demoted to a
labelled fallback with its cost published. The measurement is what made the
decision, and the same standard applies to anything built from here.

### What this requires

Every departure needs a corpus to measure on, and that constraint is real: a
component nobody can benchmark is a component nobody should trust. Where no
benchmark exists the honest options are to find one, construct one, or scope the
claim to what can be shown — never to assert the improvement.

## Reporting conventions used throughout

- **Measured, not asserted.** Every quantitative claim in these files traces to a
  committed artifact under `validation/measurements/`, and a test fails if prose and
  artifact drift apart.
- **Null is not zero.** An inapplicable operator reports `null`, never `0`;
  averaging zeros under-reports every operator on a corpus where it sometimes
  does not apply.
- **Absolute counts beside every rate.** No stratum below ~50 positives is
  reported as a rate alone.
- **Cluster-bootstrap by patient**, never by note. Clinical corpora repeat
  patients and copy-forward makes their notes genuinely correlated.
- **Failed approaches are reported.** Four discriminators were tried for the
  clinical/non-clinical question and three failed; the failures are in
  [06-lexicon-construction](06-lexicon-construction.md) because they constrain
  what any future method can claim.
