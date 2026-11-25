# Validation

The full protocol is in [`validation/protocol.md`](../protocol.md);
this file is the manuscript-facing summary of what is claimed and how.

## The claim is narrower than "we can do clinical NER"

It is: **when we say an edit landed on a medication, it landed on a
medication.** That is what a robustness result depends on, and it is what gets a
number.

## Two experiments, and only one is the package's claim

**Experiment A — tagger quality.** Standard NER/linking evaluation: map gold
labels onto our categories via the declared crosswalk, report strict and relaxed
P/R/F1 per anchored category with cluster-bootstrap CIs by `patient_id`. This is
the number a reviewer asks for. It is not, alone, what the package needs.

**Experiment B — targeting fidelity.** For edits placed under a target of
category *X*, what fraction overlap a gold span whose crosswalked label is *X*?

```
targeting_precision(X) = |edits on X hitting a gold X span| / |edits on X|
```

**Precision gates; recall informs** — the opposite of the usual NER emphasis, and
it needs stating explicitly in the methods. A tagger with mediocre recall still
supports a sound experiment: missing a medication only means fewer medications
were corrupted than possible, which the dose accounting already reports as
achieved versus requested. A tagger with poor *precision* means the corruption
did not land where the results claim, and every downstream conclusion inherits
that error.

## Crosswalk to gold standards

| Gold standard | Corpus | Size | Anchors |
|---|---|---|---|
| **SNOMED CT Entity Linking Challenge** | 272 MIMIC-IV discharge notes | 75,491 annotations of 6,595 concepts as released (74,808 / 6,624 as published), 6 clinical annotators, ~70% double-annotated | disorder, procedure, anatomy |
| **n2c2 2018 Track 2** | MIMIC-III discharge summaries | ~500 notes | medication |
| i2b2/VA 2010 | Partners, BIDMC, UPMC | 170 train / 256 test | disorder, procedure, medication (partial) |
| ShARe/CLEF 2013–14 | clinical notes | 298 notes | disorder, plus the assertion layer |

The SNOMED challenge is primary: same corpus family as the development notes, so
it tests the tagger on the text it will actually run on. Its one gap is that it
carries **no medications** — deliberately only three SNOMED hierarchies — which
is why n2c2 2018 is not optional.

## The ablation ladder

Each rung is a method change measured on the same gold spans, so the value of
each addition is a number rather than an argument.

| Rung | Method | Question |
|---|---|---|
| L0 | word-level lookup | what does the cheap method cost? |
| L1 | + concept matching (QuickUMLS) | does multi-word matching remove bare-token false positives? |
| L2 | + overlap resolution | how much do nested mentions matter? |
| L3 | + ConText qualification | **measured** — negated-class F1 0.9289 on the NegEx test set against a 0.0000 majority floor; 30.1% of gold phenotype evidence is non-affirmed. See [12-context-qualification](12-context-qualification.md) |
| L4 | + RobustEHR structural boundaries | **yes, and the fix is ours** — de-identification instability 0.0000 against PyRuSH's 0.1429, and the corpus-scale non-affirmed rate moves 34.7% → 30.1% on identical spans. See [12-context-qualification](12-context-qualification.md) |

L0 → L1 is the decisive rung: it is predicted to remove the `stairs` / `one` /
`date` failures that word-level lookup cannot, and it settles the T033 question.
L4 is motivated by an already-reproduced finding.

## What is inherited from QuickUMLS, and what is not

Re-deriving a published result is waste, and which parts transfer is settled by
reading the implementation rather than by argument. `accepted_semtypes` is a
**post-match filter** — applied after ngram generation, simstring lookup and
similarity scoring, as a rejection of candidate concepts. Restricting it cannot
create a span, move a boundary or change a score; it can only remove candidates.

Our output is therefore a **strict subset** of the validated default output.

| Quantity | Inherited? |
|---|---|
| Per-semantic-type matching behaviour | **yes** — the algorithm is untouched |
| Category grouping (union of TUIs) | n/a — a set operation, tested not validated |
| Published P/R on ShARe/CLEF, THYME | **cite, do not repeat** |
| Behaviour on UMLS 2026AA | no |
| Behaviour on MIMIC-IV discharge notes | no |
| Targeting precision | no — a metric never computed |

So no new NER validation is required for the semantic-type restriction itself.
Only the delta is measured, which is one run rather than a re-derivation.

**The guarantee is conditional**: changing `threshold`, `similarity_name`,
`min_match_length` or `overlapping_criteria` alters the matching algorithm rather
than filtering its output, and forfeits the inheritance. Each is pinned in the
run manifest for that reason.

**And the shipped configuration has forfeited it.** `overlapping_criteria` is set
to `length` rather than QuickUMLS's `score`, because preferring the longest match
is what stops `shortness of breath` fragmenting into `breath`. So the matcher
owes its own evaluation rather than inheriting one — which the head-to-head
against medspaCy and scispaCy, and the challenge score, are what discharge. This
is a real cost of the retune and is recorded as such: `benchmark_history.json`
carries `inherits_quickumls_validation: false` from entry 22 onward.

## Software verification

Nine levels, eight running in CI, with level 7 (job-count invariance) marked not
applicable until parallel execution exists rather than reported as passing. See
[02-determinism](02-determinism.md).

Release gates: replay hash agreement 100%; offset round-trip 100%; serial ≡
parallel 100%; null-control identity 100%; protected-span violations 0;
injection–recovery slope within [0.90, 1.10] with R² > 0.90.

## Statistical conventions

Cluster-bootstrap by `patient_id`, never by note. For any binary classification
arm, **MCC primary**, with sensitivity and specificity reported *separately*
because corruption typically moves them in opposite directions and that
asymmetry is the finding. F1 reported because the field expects it, never
primary under class imbalance. McNemar's exact test for paired binary
correctness, since everything is paired. One pre-registered primary endpoint,
FDR control within operator families, the rest labelled exploratory.

## Two threats that need pre-empting

**Contamination.** MIMIC-IV discharge summaries are plausibly in LLM pretraining
data, so corruption partially breaks memorization and a performance drop could
reflect lost *memorization* rather than lost *robustness*. A memorization probe
is required, testing whether the drop correlates with memorization score. If it
does, that is a major finding; if not, the reviewer's best objection is defused.

**Sampling-noise floor.** LLMs are stochastic. Every stability number must be
reported relative to a k ≥ 3 repeat baseline at severity 0, paired with
`control.identity` at every severity. Otherwise one publishes "corruption caused
4% instability" for a model with 6% run-to-run instability. This is, in my
judgement, the single most likely fatal flaw in the demonstration as scoped.

## Results: the validation run

Executed against the SNOMED CT Entity Linking Challenge — 272 MIMIC-IV
discharge notes, 75,491 expert annotations, 6,595 concepts, six clinical
annotators, ~70% double-annotated. Artifact:
`validation/measurements/snomed_ablation.json`.

### The bound on every absolute number

Only **25.7% of content tokens** sit inside any annotated span. The challenge
annotates selected concepts, not every clinical word, so a tagger finding a real
mention the annotators did not mark is scored as imprecise.

**Absolute targeting precision is therefore a lower bound**, and the
rung-to-rung delta is the interpretable result. This is stated wherever the
numbers appear, and the coverage figure is written into the artifact so it
cannot be separated from them.

### L0 → L1: what concept matching is worth

| Category | L0 | L1 | Δ precision | L0 recall | L1 recall |
|---|---|---|---|---|---|
| `symptom` | 0.483 | **0.705** | **+0.222** | 0.709 | 0.722 |
| `anatomy` | 0.190 | **0.274** | **+0.084** | 0.688 | 0.610 |
| `disease` | 0.554 | **0.593** | +0.038 | 0.747 | 0.737 |
| `procedure` | 0.339 | **0.367** | +0.028 | 0.301 | 0.274 |
| `disorder` | **0.610** | 0.505 | −0.104 | 0.616 | 0.719 |
| `finding` | **0.363** | 0.256 | −0.107 | 0.272 | 0.434 |
| `clinical_any` | **0.473** | 0.432 | −0.042 | 0.747 | 0.650 |

The result is a clean split: **concept matching improves every specific
category and reduces precision on every broad one.**

The gains are mechanistic. `symptom` gains 22 precision points because
`chest pain` resolves as a single Sign or Symptom mention rather than an anatomy
token adjacent to a symptom token — precisely the ambiguity word-level lookup
was shown to be structurally unable to resolve.

The losses come with **rising recall**: `disorder` 0.616→0.719, `finding`
0.272→0.434. Against a non-exhaustive reference, precision down with recall up
is the signature of finding more genuine mentions that were not annotated — a
method that were simply wrong would lose both. So the broad-category drop is
read as a property of the reference rather than a regression, and it is why no
absolute figure is quoted without the coverage caveat beside it.

**Practical consequence for the package**: use concept resolution for specific
category targets, which is where robustness experiments actually operate
("corrupt the medications", "corrupt the diagnoses but not the symptoms"). The
broad `clinical_any` default is the one case where the two are close enough that
the choice does not carry the result.

### The T033 decision, settled by measurement

The exclusion of T033 "Finding" from the default union was adopted provisionally
on word-level evidence, and against the practice of QuickUMLS, MedMentions
ST21pv and the challenge's own `clinical finding` hierarchy. The rung that
admits it settles the question:

| `clinical_any` union | Precision | Recall | F1 | Selected |
|---|---|---|---|---|
| **without T033** | **0.432** | 0.650 | **0.519** | 117,744 |
| with T033 | 0.358 | 0.705 | 0.475 | 155,453 |

Excluding T033 yields **higher precision and higher F1**. Precision is the
gating metric here, so **the exclusion stands — now on measured grounds.**
Admitting T033 buys 5.5 recall points for 7.4 precision points and 37,709 extra
selected units, and a use case wanting findings can still name the category
explicitly. What the measurement settles is the unnamed default alone.

This is the template the taxonomy uses for every judgement call: state it, mark
it provisional, and let a measurement close it.

## What may and may not be claimed about the matcher

The concept matcher was also scored on the **challenge's own metric** —
character IoU macro-averaged by concept class — so that "how do we compare" has
a number. It does not flatter us, and the number is reported rather than framed
away.

| System | Character IoU, macro by class |
|---|---|
| KIRI (winner, dictionary-based) | 0.4202 |
| SNOBERT (encoder-based) | 0.4194 |
| MITEL-UNIUD (decoder-based) | 0.3777 |
| median of all final submissions | 0.2572 |
| **ours, shipped configuration** | **0.1750** |
| ours, QuickUMLS defaults | 0.1561 |

All RobustEHR rows: 68-note test split, `validation/pipeline/scripts/benchmark_sweep.py`, scoped to
concepts carrying a SNOMED code. `GoldCorpus.split()` filters both the gold
spans and the notes to the requested split; scoring over notes with no gold
would roughly halve every absolute figure while leaving the ordering intact,
which is why the split is pinned by a test.

**RobustEHR is not a competitive entity linker and does not claim to be.** At
0.175 against a 0.257 median it would have placed below the middle of the field,
and against KIRI's 0.4202 it is not close. Two things are worth separating.

Span detection is not the weakness. Spans alone reach **0.4312** against the same
gold — comparable to the winning *end-to-end* score. The collapse from 0.4312 to
0.1750 is a **disambiguation** failure, and the classification of it is direct:
of the predictions that land on a gold span, 67% name the wrong concept.

The comparison is also not quite like-for-like, and that is stated rather than
used. KIRI is **supervised on this corpus**; our matcher is an untrained
dictionary lookup. Re-running KIRI's released solution on our split gives 0.4131
end-to-end and **0.7405 span-only**, so it beats us on both dimensions — the
supervision gap is real and the honest reading is that it buys a great deal.

### The claim that survives: recall against expert annotation

Against a reference covering 25.7% of tokens, **recall is the interpretable
direction**. If an expert marked a span and the matcher found it, that is
unambiguous; if the matcher marked one the expert did not, the reference cannot
say whether it is wrong or merely unannotated.

Corpus-wide, all 272 notes and 75,491 gold spans (`snomed_ablation.json`,
`split: all`) — a different and larger denominator than the 68-note test-split
figures quoted elsewhere in this document:

| Category | Gold spans | Recovered | Recall |
|---|---|---|---|
| `disease` | 15,332 | 11,299 | **0.737** |
| `symptom` | 8,155 | 5,885 | **0.722** |
| `disorder` | 40,176 | 28,889 | **0.719** |
| `anatomy` | 7,185 | 4,383 | 0.610 |
| `finding` | 18,040 | 7,833 | 0.434 |
| `procedure` | 26,157 | 7,155 | **0.274** |

So the defensible statement is: *the matcher recovers roughly three quarters of
expert-annotated disease, symptom and disorder mentions, and three in five
anatomical ones, on the same corpus family the package targets.* Procedures are
the clear weakness at 0.274 and are reported as such rather than averaged away.

### Why this is sufficient for what the package does — and where it is not

Typing a span as a medication does not require resolving *which* medication, so
category-level targeting does not inherit the entity-linking shortfall. That is
the task these numbers validate.

**The phenotype layer is where it would bite**, because a phenotype was a set of
CUIs and therefore needed concept identity. The design response is the one the
architecture always specified: a phenotype is matched against **its own curated,
reviewed term list** by exact dictionary matching, not by general-purpose linking
over three million concepts. A bounded, human-reviewed list is a different and
far more tractable problem than the one scored above, and it is validated
separately — the numbers here neither support nor condemn it.

That response is now literal rather than analogical, and it moved in the
direction this section anticipated. A phenotype target admits a span on either
of two warrants ([17](17-phenotype-association-method.md)): the concept set,
which does need identity and inherits whatever the linker gets wrong, or a
declared surface form matched literally, which needs none. The second warrant
is exactly "its own curated, reviewed term list by exact dictionary matching",
and it exists because two kinds of decisive string — the causative organism and
the qualifier — have no relation connecting them to the disorder they name, so
no amount of linking accuracy would have reached them.

**What that changes for this chapter's numbers.** The entity-linking shortfall
scored above still bounds the concept warrant and no longer bounds the target.
A phenotype whose diagnosis is written as an abbreviation the linker cannot
ground is now reachable through a surface the linker never sees. The
[gap audit](../phenotype/PIPELINE.md) measures the union against a term list
written outside the pipeline, which is the only measurement that scores the
target rather than one of its halves, and its residue is reported by cluster
because the clusters name missing instruments rather than missing entries.
