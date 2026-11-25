> **Development record.** This document was written while the component it
> describes was being built and reads as a history. The method as it stands is
> in [`validation/methodology/`](../methodology/); nothing here is cited by the
> manuscript. Kept so every decision can be audited.

# Measurements

Results produced by RobustEHR about **itself**, committed so that the numbers
quoted in docstrings and in the manuscript stay attached to a run that produced
them. A figure in prose with no artifact behind it is a citation to a
measurement nobody made, and `tests/test_lexicon_terminology.py` fails if the
two drift apart.

Nothing here contains note text or licensed terminology strings — see
"What is safe to commit" below.

## `clinical_lexicon.manifest.json`

Identifies the UMLS-derived clinical vocabulary that runtime uses to decide
whether a token is clinical.

The vocabulary itself is **not** in this repository. UMLS strings are licensed
content under the UMLS Metathesaurus License Agreement, so the artifact is built
locally from the user's own installation into `data/lexicon/` (gitignored) by:

```
robustehr concepts build-lexicon --umls data/umls
```

What ships is this manifest. Its `sha256` covers the sorted vocabulary, so
anyone with the same release can confirm they rebuilt the identical file without
a byte of licensed content changing hands — the same deferred-materialization
pattern the concept lockfiles use.

| Field | Meaning |
|---|---|
| `umls_release` | Release the vocabulary was derived from, e.g. `2026AA` |
| `semantic_groups` | McCray Semantic Groups counted as clinical |
| `semantic_types` | Number of TUIs those groups expand to |
| `tokens` | Size of the derived vocabulary |
| `sha256` | Hash of the sorted vocabulary file |
| `extraction` | The selection rule, in one sentence |

## `lexicon_fallback.json`

What running **without** a terminology costs, measured rather than asserted.

RobustEHR classifies tokens as clinical by dictionary lookup against the
vocabulary above. When no terminology is installed it falls back to a
morphological affix heuristic. This file is the agreement study between the two,
over 200 development notes:

| | |
|---|---|
| Precision | 0.607 |
| Recall | **0.103** |
| F1 | 0.175 |
| Token coverage, terminology | 54.3% (an **upper bound**, see below) |
| Token coverage, fallback | 3.4% |

Regenerate with:

```
robustehr concepts validate --corpus <your corpus> --out validation/measurements/lexicon_fallback.json
```

Read the two error directions separately; they mean different things.

The recurrent disagreements where the heuristic says clinical and the
terminology does not are mostly *real clinical vocabulary the extraction
misses* — derived adjectival forms whose noun is present but whose adjective is
not (`hyperkalemic`, `euvolemic`, `dysarthric`), and specialty names. Genuine
heuristic errors are the minority. So the precision figure understates the
heuristic and points at a limitation of single-word concept lookup rather than
of the rules.

Recall has no such defence. The fallback misses `blood`, `pain`, `patient` and
`discharge` because they carry no diagnostic morphology, which is true of most
clinical words. That is why the terminology is the primary method and this is a
labelled degraded mode.

**Do not quote 54.3% as the clinical-content rate.** Over half of content words
being clinical is not plausible for a discharge summary. UMLS carries `one`,
`well`, `normal`, `stairs` and `walking` as Disorder concepts — the same semantic
group as `dyspnea` — and general-English frequency, source-vocabulary count and
semantic group were each tested as discriminators and each failed. Word-level
lookup is an upper bound; concept-level matching validated against gold spans is
the resolution. See `docs/ROADMAP.md` §4.

## `deid_assertion_probe.json`

The package's thesis, demonstrated on a real tool.

`render.deid_restyle` converts between de-identification conventions. It is
`INVARIANT_BY_CONSTRUCTION` — the canonicalizer `kappa.mask_deid` projects every
placeholder to one sentinel, and the property test proves that projection is
unchanged by the operator. **No clinical reference can move.** A note with `___`
and the same note with `<REDACTED>` say the same thing about the same patient.

medspaCy ConText disagrees. Same note, only the placeholder varying:

| Convention | Placeholder | Sentences | `hypertension` negated? | |
|---|---|---|---|---|
| MIMIC-IV | `___` | 4 | **true** | false negation |
| MIMIC-III | `[** Name **]` | 4 | **true** | false negation |
| angle redacted | `<REDACTED>` | 4 | **true** | false negation |
| XXX | `XXX` | 6 | false | correct |
| control | `Mr. Smith` | 7 | false | correct |
| control | `Patient` | 6 | false | correct |

Three of six conventions mark an **active, controlled diagnosis as absent**. The
mechanism is visible in the sentence count: masked placeholders defeat sentence
segmentation, merging two list items into one sentence, which lets the negation
cue in item 1 (`No evidence of acute pneumonia`) take scope over the diagnosis in
item 2. The two non-masked controls confirm the mask is the cause rather than the
list structure.

The two worst cases are the MIMIC-IV and MIMIC-III conventions — the formatting
of the most widely used clinical corpora in the field.

Three consequences for this project:

- It is direct evidence for the central claim. A provably reference-preserving,
  formatting-only perturbation flips a downstream clinical verdict, which is
  precisely the class of failure robustness studies do not currently measure.
- `render.deid_restyle` is not a trivial operator. It has the highest
  eligibility in the suite (a median of 64 spans per note, in 100% of notes),
  and this is what those spans can do.
- Structure must be segmented rather than delegated to a general sentence
  splitter, and the two later measurements make that concrete without making it
  simple. Feeding ConText our boundaries fixes the constructed de-identification
  cases outright (`assertion_deid_invariance.json`, 0.0000 instability against
  0.1429) and takes the *structural* operators toward zero at corpus scale —
  `header_style` and `lab_block_collapse` reach exactly 0.0000. It **costs**
  `deid_restyle`, which rises to 0.0116 against PyRuSH's 0.0001, because a
  segmenter that models de-identification placeholders necessarily reads the
  convention as input. Assertion results are conditioned on **formatting
  condition**, of which the de-identification scheme is one part — and which part
  dominates depends on which segmenter is in use, so it must be reported per
  operator rather than as one figure.

Reproduce with `medspacy` installed:

```
python validation/pipeline/scripts/probe_deid_assertion.py --out validation/measurements/deid_assertion_probe.json
```

The probe is deliberately outside the test suite: medspaCy is not a core
dependency, and a check whose purpose is to document another package's behaviour
must not gate this package's CI.

## `snomed_ablation.json`

The validation run. **SNOMED CT Entity Linking Challenge**: 272 MIMIC-IV
discharge notes, 75,491 expert annotations of 6,595 concepts, six clinical
annotators, ~70% double-annotated.

Regenerate with:

```
robustehr eval crosswalk          # once — needs a local UMLS release
robustehr eval snomed --out validation/measurements/snomed_ablation.json
```

### Read the caveat first

**The gold standard is not exhaustive over clinical content.** Only 25.7% of
content tokens sit inside any annotated span, because the challenge annotates
selected concepts rather than every clinical word. A tagger that finds a real
mention the annotators did not mark is scored as imprecise.

So **absolute targeting precision is a lower bound**, and the rung-to-rung delta
is the interpretable result. The figure travels with the artifact as
`gold_token_coverage` so the caveat cannot be separated from the numbers.

### L0 → L1: concept matching against word-level lookup

Targeting precision — of the units a category target selected, the fraction
overlapping a gold span of that category.

| Category | L0 | L1 | Δ | L0 recall | L1 recall |
|---|---|---|---|---|---|
| `symptom` | 0.483 | **0.705** | **+0.222** | 0.709 | 0.722 |
| `anatomy` | 0.190 | **0.274** | **+0.084** | 0.688 | 0.610 |
| `disease` | 0.554 | **0.593** | +0.038 | 0.747 | 0.737 |
| `procedure` | 0.339 | **0.367** | +0.028 | 0.301 | 0.274 |
| `disorder` | **0.610** | 0.505 | −0.104 | 0.616 | 0.719 |
| `finding` | **0.363** | 0.256 | −0.107 | 0.272 | 0.434 |
| `clinical_any` | **0.473** | 0.432 | −0.042 | 0.747 | 0.650 |

**Concept matching wins on every specific category and loses on every broad
one**, and the pattern is interpretable rather than mysterious.

On the specific categories it disambiguates: `symptom` gains 22 precision points
because `chest pain` resolves as one Sign or Symptom mention instead of an
anatomy token beside a symptom token, which is exactly the failure word-level
lookup could not fix.

On the broad categories precision falls **while recall rises** — `disorder`
0.616→0.719, `finding` 0.272→0.434. Against a non-exhaustive gold that
combination is what finding more genuine-but-unannotated mentions looks like: a
method that were simply wrong would lose recall too. The precision drop on broad
targets should therefore be read as an artifact of the reference rather than as
a regression, and it is the reason absolute numbers are not quoted alone.

### The T033 decision, settled

`finding` (T033) was excluded from the default union provisionally, on
word-level evidence, against the practice of QuickUMLS (27 default types),
MedMentions ST21pv (21) and the challenge's own `clinical finding` hierarchy.
The rung that admits it answers the question:

| `clinical_any` union | Precision | Recall | F1 | Units selected |
|---|---|---|---|---|
| **without T033** | **0.432** | 0.650 | **0.519** | 117,744 |
| with T033 | 0.358 | 0.705 | 0.475 | 155,453 |

Excluding T033 gives **higher precision and higher F1**. Since precision is the
gating metric for this package — a false mention means the corruption did not
land where the results claim — **the exclusion stands, now on measured grounds
rather than as a workaround.**

Admitting T033 buys 5.5 recall points for 7.4 precision points and 37,709 extra
selected units. A use case that wants findings can still name the category
explicitly; what the measurement settles is only the unnamed default.

## KIRI — the winner, re-run on our split

*(No `kiri_comparison.json` ships: reproducing it needs KIRI's released
solution and its trained assets, neither of which is ours to redistribute.
The numbers below come from a local re-run; the procedure is in the
faithfulness note above rather than in a committed artifact.)*

The comparison that removes the last caveat. KIRI's published pipeline (1st
place, dictionary-based) was cloned and executed on **the same 68-note test
split** we score ourselves on, rather than citing its leaderboard number against
different data.

**Faithfulness check first.** Three assets KIRI expects were unavailable and were
substituted: the SNOMED CT RF2 Challenge Edition (rebuilt from UMLS 2026AA
`MRCONSO`/`MRREL` — 235,785 concepts, 641,727 `isa` edges), the Athena/OHDSI
vocabulary (replaced by UMLS cross-source atoms sharing a CUI), and MIMIC-IV-Note
`discharge.csv.gz` (used only for a frequency cutoff, rescaled to note count).
The rebuild scores **0.4131** against their published private score of **0.4202**
— within 0.007, which suggests the substitutions are not distorting the result.

| System | Span detection | Concept-level (challenge metric) | Trained on this corpus? |
|---|---|---|---|
| KIRI, re-run on our split | **0.7405** | **0.4131** | **yes — 204 annotated notes** |
| KIRI, published private score | — | 0.4202 | yes |
| RobustEHR, at the time of this run | 0.4406 | 0.1733 | no — zero training data |
| RobustEHR, shipped configuration | 0.4312 | 0.1750 | no — zero training data |

Both RobustEHR rows are shown because the retune moved the two metrics in
opposite directions — concept IoU up, span IoU marginally down — and quoting only
the later one would hide that. Neither changes the conclusion below.

### KIRI beats us on both dimensions

Stated plainly, because an earlier version of this file claimed our span
detection "matched the winner". **That was wrong.** It compared our span-only
score against KIRI's span-*and*-concept score (0.4131), which is not
like-for-like. Measured properly, KIRI's span detection is **0.7405** — well
ahead of ours.

What the decomposition does show is how each system degrades when concept
naming is added to span finding:

| | span → concept | retained |
|---|---|---|
| KIRI | 0.7405 → 0.4131 | 56% |
| RobustEHR | 0.4406 → 0.1733 | 39% |
| RobustEHR, shipped | 0.4312 → 0.1750 | 41% |

So KIRI is better at locating mentions *and* loses less when it must also name
them. Both differences point at the same cause: KIRI **learned both from 204
labelled notes of this corpus**. It knows which strings are annotated as
mentions here, and which concept each maps to. RobustEHR has seen none of it.

### The comparison that is fair, and the one that is not

KIRI is a **supervised, task-specific** system. RobustEHR is a general-purpose
tool that must run on any corpus with no annotations, which is also true of
medspaCy and scispaCy. That is the peer group, and against it RobustEHR wins
clearly — mean category recall 0.614 against 0.490 and 0.398.

Against KIRI it loses, and should be expected to. The useful reading is not
"we are worse" but **"this is what supervision buys on this corpus"**: roughly
0.30 of span IoU and 0.24 of concept IoU. A user with labelled data for their
own corpus should train something like KIRI; a user without any should not
expect KIRI's numbers from any untrained system, ours included.

### A bug this comparison exposed

Every challenge score reported before this was computed on a broken split.
`GoldCorpus.split("test")` filtered the annotation *spans* but kept all 272
notes, so the matcher predicted over 272 notes of text while only 68 carried
gold — every mention in the other 204 counted as a false positive.

Fixing it moved our score from 0.0915 to **0.1733**, nearly double. The entries
in `benchmark_history.json` were all computed under the same bug, so they remain
valid *relative to each other* — the ranking of configurations is unaffected —
but their absolute values are understated. A test now asserts that a split
restricts notes as well as spans.

## `challenge_metric.json`

Where our matcher sits on the **challenge's own metric**, so "how do we compare"
has a number. Regenerate with `python validation/pipeline/scripts/challenge_metric.py`.

**This is a context measurement, not a competitive claim.** Four differences
travel with it and none is incidental:

- **Different task.** The challenge is concept-level entity linking over 6,595
  SNOMED concepts. RobustEHR needs category-level typing over 11 categories.
- **Different system class.** The winners are purpose-built and two of the three
  train on the challenge's training split. This is an untrained, off-the-shelf
  dictionary matcher at default parameters.
- **Different evaluation set.** The challenge's test set was held out and is not
  public; this scores the `test`-marked rows of the public release.
- **Concepts reached through UMLS.** QuickUMLS returns CUIs, gold is SNOMED, and
  a CUI is credited when any of its SNOMED codes matches — more forgiving than
  exact concept identity.

| System | Character IoU, macro by class |
|---|---|
| KIRI (dictionary-based) — winner | **0.4202** |
| SNOBERT (encoder-based) | 0.4194 |
| MITEL-UNIUD (decoder-based) | 0.3777 |
| median of all final submissions | 0.2572 |
| **ours — QuickUMLS, untrained, default** | **0.0748** |

Decomposed, to say *why* rather than just how much:

| Level | Score |
|---|---|
| concept identity (the challenge's task) | 0.0748 |
| **span detection only** | **0.1678** |
| category level, macro over 11 categories | 0.0935 † |

† Not a meaningful figure. Macro-averaging over 11 categories is dominated by
categories the gold barely contains — `device` has 2 annotations and the
challenge carries no medications at all — so those score 0 and drag the mean.
Reported only to prevent someone recomputing it and drawing the wrong
conclusion. The category-level numbers that mean something are the targeting
precisions in `snomed_ablation.json`, which are scored per category rather than
macro-averaged across them.

### What this actually tells us

**Off-the-shelf QuickUMLS is a weak entity linker**, and that is worth stating
plainly: at 0.075 against a 0.257 median it would have placed near the bottom of
the leaderboard. Span detection at 0.168 shows the shortfall is not only concept
assignment — the matcher over-predicts spans relative to what annotators marked,
consistent with the 25.7% gold coverage measured elsewhere.

This does **not** invalidate its use here, because RobustEHR does not need
concept-level linking to type a span as a medication or a disorder — and the
category-level targeting precisions are much stronger than this figure.

But it does carry a real warning for the phenotype layer. **A phenotype is a set
of CUIs**, so phenotype association needs accurate concept identity, and this
measurement says off-the-shelf matching will not supply it. That is a decision to
confront when the layer is built, not a detail to discover afterwards.

## `benchmark_history.json`

Append-only record of concept-matcher performance across iterations. Regenerate
or extend with `python validation/pipeline/scripts/benchmark_sweep.py`.

Two scores are tracked because **they can move in opposite directions**, and a
change that improves the leaderboard number while degrading category recall is a
regression for this package however it looks published. Only a history makes
that visible.

| Configuration | Challenge IoU | Span IoU | Mean category recall | Inherits QuickUMLS validation |
|---|---|---|---|---|
| baseline (defaults, all of UMLS) | 0.0546 | 0.1389 | 0.559 | yes |
| scoped: RobustEHR categories | 0.0671 | 0.1513 | 0.559 | yes |
| scoped: gold semantic types | 0.0675 | 0.1556 | 0.559 | yes |
| scoped: SNOMED only | 0.0546 | 0.1389 | 0.559 | yes |
| threshold 0.9 | 0.0635 | 0.1420 | 0.555 | no |
| threshold 1.0 (exact) | 0.0640 | 0.1425 | 0.554 | no |
| overlap by length | 0.0528 | 0.1329 | 0.568 | no |
| cosine similarity | 0.0366 | 0.1327 | **0.596** | no |
| min_match_length 5 | 0.0550 | 0.1389 | 0.471 | no |
| **exact + gold semantic types** | **0.0788** | **0.1591** | 0.554 | no |
| 0.9 + gold semantic types | 0.0783 | 0.1585 | 0.555 | no |

Context: KIRI (winner) 0.4202, median submission 0.2572.

### Trajectory so far

**Two regimes, and the boundary matters.** Entries 0–20 were computed under a
defect in `GoldCorpus.split()` that filtered gold *spans* to the requested split
but kept all 272 notes, so predictions were scored over notes with no gold at
all. Entries 21–28 are post-fix. The two are **not comparable in absolute
terms** — span IoU steps from ~0.15 to ~0.42 at the boundary, an artefact of the
fix rather than of any configuration. They are kept because the *relative*
ordering within each regime is what drove the decisions.

#### Post-fix regime (entries 21–28) — the current record

| Configuration | Challenge IoU | Span IoU | Category recall | Inherits validation |
|---|---|---|---|---|
| QuickUMLS defaults | 0.1561 | 0.4316 | 0.5947 | yes |
| overlap by length | 0.1574 | 0.3959 | 0.5891 | no |
| length + affix trim | 0.1611 | 0.4025 | 0.5890 | no |
| length + trim + re-match | 0.1747 | 0.4274 | 0.6047 | no |
| **+ SNOMED tie-break (shipped)** | **0.1750** | **0.4312** | **0.6063** | no |

**+12.1% on the challenge metric** since the post-fix baseline (0.1561 → 0.1750)
and **+2.0% on category recall** (0.5947 → 0.6063), with span IoU essentially
flat (0.4316 → 0.4312). `overlap by length` alone is a *regression* on both span
IoU and challenge IoU; it only becomes a gain once affix trimming and re-matching
are added, which is the clearest case in this file for measuring a change in
combination rather than in isolation.

#### Pre-fix regime (entries 0–20) — retained for the decisions it drove

| Configuration | Challenge IoU | Category recall | Inherits validation |
|---|---|---|---|
| baseline (defaults, all of UMLS) | 0.0546 | 0.559 | yes |
| scoped: gold semantic types | 0.0675 | 0.559 | yes |
| exact + gold semantic types | 0.0788 | 0.554 | no |
| **SNOMED-only index** | **0.0809** | 0.477 | **yes** |
| **SNOMED-only index + exact** | **0.0915** | 0.444 | no |
| default + min_match_length 2 | 0.0650 | 0.574 | no |
| aligned semtypes | 0.0662 | 0.570 | no |
| **aligned semtypes + mml 2** | 0.0643 | **0.588** | no |
| aligned + exact + mml 2 | 0.0761 | 0.583 | no |

Within this regime, +68% on the challenge metric (0.0546 → 0.0915) and +5.2% on
category recall (0.559 → 0.588). **Neither figure is the package's current
trajectory** — both are pre-fix. The live numbers are the post-fix table above.

### A bug found by diagnosis, not by tuning

The largest recall gain came from fixing an integration defect rather than
turning a knob. `ConceptMatcher` left QuickUMLS's `accepted_semtypes` at its own
27 defaults while RobustEHR filtered again by its 36 category types — **two
filters that disagree**. `wbc` resolves to T025 Cell, which belongs to `anatomy`
but not to QuickUMLS's defaults, so it was discarded before any category logic
could see it.

Aligning them is now the package default. It also fixed a subtler failure: at
`min_match_length` 3 the matcher extended a two-character abbreviation's span
into the adjacent value to reach the floor, producing `cl 104` as a single
mention. That is a wrong span, not a conservative one.

**Widening the semantic-type filter forfeits QuickUMLS's inherited validation**,
and the history now enforces the asymmetry: narrowing within their 27 keeps the
output a subset of what they scored and inherits it, going outside does not.

### The two metrics pull apart, and the package follows category recall

The best challenge configuration is the **worst** for category recall, and the
reverse. Aligning the matcher's vocabulary to SNOMED gains 0.037 challenge IoU
and loses 0.115 category recall, because SNOMED does not carry the RxNorm and
LOINC terms the `medication` and `lab_result` categories depend on.

**So the package keeps the full UMLS index.** The SNOMED-only configuration is
reported as *benchmark-optimal*, and is explicitly not the operating default —
adopting it would improve a number nobody uses at the cost of the capability the
package exists to provide. Recording both is what made the trade visible; a
single tracked number would have recommended the regression.

**It does not keep the default parameters, and an earlier version of this
paragraph wrongly said it did.** The shipped configuration is
`overlapping_criteria='length'` with affix trimming, re-matching and a SNOMED
tie-break. `overlapping_criteria` is one of the parameters whose change forfeits
QuickUMLS's published validation, so `benchmark_history.json` records
`inherits_quickumls_validation: false` from entry 22 onward. The package took on
its own evaluation obligation when it changed the overlap policy, and discharges
it through the head-to-head and the challenge score rather than by citation.

### What the sweep found

**Vocabulary alignment is the largest single lever** (+0.027 challenge IoU),
ahead of exact matching (+0.011) and semantic-type scope (+0.013).

**Exact matching beats approximate**, which vindicates the architecture's
original design. Threshold 1.0 outscores the 0.7 default at every scope, and the
best configuration is exact matching plus a semantic-type filter — **0.0788
against a 0.0546 baseline, a 44% improvement**.

**Scope matters more than similarity tuning.** Restricting predictions to
relevant semantic types is worth more (+0.013) than any threshold change at
fixed scope (+0.009). Requiring only a SNOMED code changes nothing, so it is the
semantic-type filter doing the work, not SNOMED membership.

**The two metrics diverge, exactly as feared.** Cosine similarity gives the best
category recall (0.596) and the *worst* challenge score (0.0366). A single
number would have hidden that; optimising for the leaderboard here would have
made the package worse at what it actually does.

### Where the remaining misses are

94% of missed gold spans are **single words**, and most are lab abbreviations —
`hgb`, `hct`, `creat`, `wbc`, `mcv`, `na`, `cl`, `mg`. The default
`min_match_length` of 3 cannot match the two-character ones at all, and lowering
it to 2 raises category recall from 0.554 to 0.569, with anatomy gaining most
(0.462 → 0.521) and procedures next (0.291 → 0.316).

This points at the abbreviation resolver as the next real lever rather than at
further parameter tuning: the misses are a vocabulary problem, not a similarity
problem.

### Two caveats on the best figure

`gold semantic types` reads the semantic types the annotators actually used,
which is mild overfitting to the benchmark. A fairer scope derives the same set
independently from SNOMED's three annotated hierarchies; the curated-category
scope is that approximation and costs only 0.0004 challenge IoU, so the
overfitting is small — but the best figure should be read as an upper bound.

Every tuned configuration is marked `inherits_quickumls_validation: false`.
QuickUMLS's published evaluation covers its defaults; a tuned configuration owes
its own, and adopting one means taking on that obligation rather than inheriting
a citation.

## `head_to_head.json`

**The comparison that matters for adoption.** Not the challenge leaderboard —
nobody choosing a clinical NLP tool asks whether it would have won a 2024
competition. They ask whether it is at least as good as what they would otherwise
use.

Three systems, the 12-note test split, 3,777 expert-annotated spans, same gold
and same metric:

- **RobustEHR** — QuickUMLS with the semantic-type filter aligned to our categories
- **medspaCy (stock)** — `medspacy.load` with QuickUMLS, default configuration
- **scispaCy (UMLS linker)** — `en_core_sci_sm` + `scispacy_linker`, abbreviations
  resolved, candidates above 0.85

RobustEHR and medspaCy share the same QuickUMLS index, so that pair isolates
configuration. scispaCy brings its own knowledge base and is a **linker rather
than a dictionary matcher** — a genuinely different approach, which is what makes
it worth having.

### Recall — expert-annotated mentions recovered

Four systems now, because the shipped pipeline and the bare matcher answer
different questions. **matcher only** is the like-for-like comparison with
medspaCy — same index, same algorithm, configuration alone. **full pipeline** is
what a user actually gets.

| Category | Gold | full pipeline | matcher only | medspaCy | scispaCy |
|---|---:|---|---|---|---|
| `disease` | 744 | **0.769** | 0.769 | 0.672 | 0.511 |
| `disorder` | 1,942 | **0.718** | 0.717 | 0.640 | 0.419 |
| `symptom` | 354 | **0.698** | 0.698 | 0.449 | 0.506 |
| `anatomy` | 384 | **0.583** | 0.578 | 0.443 | 0.380 |
| `procedure` | 1,334 | **0.498** | 0.310 | 0.248 | 0.170 |
| `lab_measurement` | 642 | **0.469** | 0.106 | 0.103 | 0.042 |
| **mean** | | **0.622** | 0.530 | 0.426 | 0.338 |

**Stage 3 is worth 9.3 recall points and 7.0 precision points over the matcher
alone**, and all of it lands in the two categories it targets: `procedure`
(0.310 → 0.498) and `lab_measurement` (0.106 → 0.469). The other four are
unchanged to three decimals, which is what a component confined to lab-panel and
exam positions should look like.

### Precision — and here scispaCy still leads

| Category | full pipeline | matcher only | medspaCy | scispaCy |
|---|---|---|---|---|
| **mean** | 0.480 | 0.411 | 0.395 | **0.529** |

scispaCy remains the more precise system, and the gap narrowed rather than
closed: 0.529 against 0.480. It is a conservative linker with a confidence
threshold and it declines matches the dictionary matchers make. Anyone whose
task rewards precision over completeness should still prefer it.

**These numbers are not comparable to the previous version of this table**, which
scored five categories. `lab_measurement` is a sixth, every system does badly on
it, and it therefore pulls all four means down — medspaCy from 0.490 to 0.426
without anything about medspaCy changing. The ranking is unaffected; the
magnitudes are not.

### The defensible claim, and its limit

*On the same corpus and gold standard, RobustEHR's concept tagger recovers
substantially more expert-annotated clinical mentions than either a stock
medspaCy pipeline or scispaCy's UMLS linker — 0.622 against 0.426 and 0.338 —
at precision above medspaCy and below scispaCy.*

The comparison isolates two different things and reports both. Against medspaCy,
the **matcher only** row shares the index and the algorithm, so 0.530 against
0.426 is a configuration result. The **full pipeline** row adds stage 3, which
medspaCy has no equivalent of, so 0.622 is a capability result and should be read
as one.

That is the right trade for this package: a missed mention means fewer units
corrupted, which the dose accounting already reports as achieved versus
requested, whereas a target that finds too little silently narrows every
experiment. It would be the wrong trade for a task that acts on each mention
individually.

Reproduce with `python validation/pipeline/scripts/head_to_head.py`.

## `phenotype_eval.json` — the measurement the phenotype layer owed

`docs/targeting-design.md` argued that phenotype targeting needs **set
membership** rather than general concept linking, and then listed "we find a
declared phenotype's evidence" as *not yet measured*. This is that measurement.

A phenotype is declared as a seed SNOMED concept plus its descendant closure.
The gold spans whose annotated concept falls in that closure are the phenotype's
evidence **as an expert marked it** — so a real phenotype gets scored against
expert annotation on real notes, with nobody annotating a phenotype corpus.

Two recalls, deliberately not collapsed:

- **span recall** — did we find the text? Bounds what an operator can reach.
- **set recall** — did we find it *and* assign a concept inside the set? Bounds
  whether `phenotype_scope` is correct.

Over the 68-note test split, 998 gold evidence spans, 8 phenotypes (the original
cut of this study): **span recall 0.912, set recall 0.698 macro**. The artifact
now committed, `phenotype_eval.json`, covers all **22 declared phenotypes** in the
same configuration and reports macro **span recall 0.8433 / set recall 0.4733**
on the disorder facet and **0.8642 / 0.6687** on the union facet (what a
`pheno=` target actually selects); the per-phenotype figures quoted below
(`heart_failure` 0.449 and so on) are unchanged in it, and the lower macro is the
effect of adding phenotypes with tiny gold support (hfpef, hfref, rheumatoid
arthritis, lupus, C. difficile) whose disorder-facet set recall is 0.0.

**These were labelled conditional on stages 3, 4 and 8, and all three have since
resolved — 3 built, 4 gated and deliberately empty, 8 built and validated. The
figures did not move.** Re-running in the recorded configuration reproduces every
phenotype to four decimal places. So the conditionality is discharged, and what
it predicted did not happen.

That includes the specific prediction. `heart_failure` at 0.449 was attributed to
an abbreviation failure — `HFrEF` and `CHFrEF` matching nothing — that stage 3
would fix. Stage 3 shipped and 0.449 is unchanged, because stage 3's expansion is
**slot-scoped**: it resolves a short form standing as the label of a value or
before a colon, and `HFrEF` in these notes is running prose. The attribution
named a real gap and the wrong owner.

Reproduce (the flags are not the script's defaults, and the artifact's `config`
string is the record of which were used):

```
python validation/phenotype/scripts/phenotype_eval.py --limit 300 --overlap length \
    --trim-affixes --prefer-snomed --out validation/measurements/phenotype_eval.json
```

Set recall is **4.0× the general linking score of 0.175 on the same corpus**,
which is the design argument turned into a number: bounded membership is a much
easier problem than open-vocabulary disambiguation, and the phenotype layer only
ever needed the former.

### Read this one with its denominator

Set recall rises monotonically with closure size, so any expansion strategy can
buy recall by claiming more concepts. It is therefore never reported without a
specificity check. These eight phenotypes are clinically distinct, so a gold span
claimed by two of them is one of them being wrong:

| closure | mean set size | gold evidence claimed | cross-phenotype contamination |
|---|---:|---:|---:|
| SNOMED `isa` only | 118 | 934 | 0 |
| **SNOMED `isa` + `MTH` `RN`** | **202** | **998** | **0** |
| union of all sources' `isa` | 434 | 994 | 28 |

The all-source union is the intuitive reading of "use the whole UMLS hierarchy"
and it loses on both axes: it claims fewer true evidence spans than the
Metathesaurus-native layer while conflating hypertension with heart failure
across 28 gold spans.

### `MTH` is a hierarchy, and it is easy to miss

UMLS is usually described as an integration of other vocabularies' hierarchies —
every edge in `MRREL` carries a `SAB`. But `SAB='MTH'` marks relations the
Metathesaurus **asserts itself**, 453,230 of them, and they reach concepts no
source vocabulary places in a tree.

The case that forced the discovery: annotators mark `diabetes` as *Diabetes
Mellitus* (C0011849); our matcher returned C0011847, *Diabetes*, which has no
SNOMED code and **no `isa` edge in any source vocabulary at all** — its only
hierarchical edges in the release come from `PSY`. Expanding to all sources does
not reach it. `MTH` records `C0011847 --RN--> C0011849` directly.

Adding it barely moves recall (0.671 → 0.678) and that is not its contribution:
it moves the **denominator**, identifying 64 gold spans as phenotype evidence
that the SNOMED hierarchy alone never claimed. Under `protect`, evidence that was
never in the set is evidence that was never protected, so a more complete
definition matters more than a better score against a narrower one.

### Two silent bugs this measurement surfaced

Both produced plausible output, which is the reason they are recorded.

**The `isa` direction was reversed.** `MRREL` reads *cui2 is a kind of cui1*.
Extracted backwards it yields an **ancestor** closure — non-empty, correctly
typed, full of related concepts, and measuring the opposite of what was intended.
Caught by a pair whose direction is known independently (`Diverticulosis` /
`Diverticulosis of large intestine`); pinned in `tests/test_hierarchy.py`.

**A SNOMED code can carry several CUIs.** `84114007` (Heart failure) maps to both
`C0018801`, which has the descendants, and `C1959583`, which is childless. Taking
the first collapsed heart failure to a one-element set matching no gold span, and
reported it as "no evidence exists" rather than as a lookup failure.

The pattern is the one `protect` mode already warns about: **in this subsystem
failures present as empty results rather than as errors**, so anything that can
return nothing needs a positive control.

## `phenotype_assertion.json` — is an assertion layer needed?

Measured rather than assumed, because the intuitive answer is right about the
question and wrong about where it applies.

Assertion does **not** change eligibility. Under `protect` every mention is
withheld regardless — a negated mention is still a mention whose corruption
changes what the note says. Under `target` every mention is corrupted regardless
— negated evidence is still phenotype-related text.

It changes **reporting**, and the quantity settles whether that is worth
building. medspaCy ConText over the gold evidence spans, 68 notes, 934 spans:

| | spans | share |
|---|---:|---:|
| affirmed | 653 | 69.9% |
| negated | 166 | 17.8% |
| historical | 65 | 7.0% |
| hypothetical | 32 | 3.4% |
| family | 20 | 2.1% |
| uncertain | 17 | 1.8% |
| **non-affirmed** | 281 | **30.1%** |

Attributes co-occur, so the rows sum to more than the non-affirmed count.

**30.1% of expert-annotated phenotype evidence is not an affirmed statement about
the patient now**, and `fever` is the extreme at 46.0% — `denies fever` in review
of systems. An `evidence_touch` table that collapses those reports much less than
it appears to.

**This supersedes 42.9%, and two things changed at once.** The old figure was 12
notes and 133 spans, scored with PyRuSH boundaries. On the *same* 934 spans
PyRuSH gives 34.7% against our segmenter's 30.1%, so about 4.6 points was cue
leakage across list and header boundaries rather than clinical fact — `historical`
alone drops from 90 spans to 65. The remainder is sample size.
`comparison_pyrush_boundaries` in the artifact carries both arms so the
attribution is checkable rather than asserted.

So ConText is wired as an **attribute carried alongside each evidence span**,
never as a filter in front of it — and it is fed **our** sentence boundaries
rather than PyRuSH's, which is the promise four documents made and none had
measured. `assertion_deid_invariance.json` is the measurement: across seven
de-identification conventions ours scores 1.0000 accuracy at 0.0000 instability,
PyRuSH 0.6071 at 0.2500.

## `abbreviation_ceiling.json` — V0, and it redirected the design

`docs/abbreviation-resolver-spec.md` puts a gate in front of the abbreviation
subsystem: measure the achievable ceiling *before* building, because a resolver
graded only against its own before-and-after looks like progress at any level of
performance. The gate fired, and the answer was not the one the spec assumed.

Over the 68-note test split, 8,520 abbreviation-shaped gold spans — **36.8% of
every gold span in the corpus**, so this is not a niche:

| | accuracy |
|---|---:|
| shipped matcher | 0.4346 |
| exact lookup, `min_match_length=2` | 0.4837 |
| **ceiling — a perfect disambiguator over UMLS** | **0.5511** |
| **unreachable at any policy** | **0.4489** |

**The budget for a disambiguation cascade is 6.7 percentage points.** The
spec proposed a seven-rung cascade — local definition detection, monosemous
inventory lookup, anchor voting, conflict abstention — and all of it competes for
those 6.7 points.

**44.9% of these spans have no UMLS candidate carrying the right category at
all**, and 2,257 have no UMLS candidate whatsoever. Look at what they are:

```
creat 131   rbc 151   hgb 147   rdw 137   na 100   angap 93
phos 80     heent 68  neuro 68  monos 52  neuts 51  rdwsd 48
```

These are not ambiguous abbreviations awaiting disambiguation. They are **lab and
exam shorthand that UMLS does not contain as strings**. `creatinine` is in UMLS;
`creat` is not. `anion gap` is in UMLS; `angap` is not.

### Where they sit decides how to fix them

"Does expansion need context?" turns out to have three answers, and the measured
placement is what shows it:

| Where it sits | n | unreachable | What disambiguates it |
|---|---:|---:|---|
| label of a value — `creat 1.1` | 2,152 | 63.8% | **structural position** |
| followed by a colon — `HEENT:` | 793 | 71.9% | **structural position** |
| inside a labelled-value line | 109 | 33.9% | structural position |
| free prose | 5,466 | 33.8% | sense inventory, then anchors |

**1,943 of the 3,825 unreachable spans — 50.8% — are structurally anchored.** A
token in the label slot of `creat 1.1` is a lab analyte because of *where it is*,
and stage 2 already computed that position. No dictionary sense and no
surrounding prose are involved. That class is invisible to a
"context vs no context" framing, and it is the biggest one.

### The finding

**Clinical abbreviation resolution in this corpus is a vocabulary problem, not a
disambiguation problem** — and the two call for opposite engineering.

A disambiguation cascade picks among candidates that already exist. It cannot
help when the candidate set is empty, which it is for nearly half of these spans.
What closes that gap is a **surface-form expansion table** — `creat` →
*creatinine*, `angap` → *anion gap*, `heent` → *head, eyes, ears, nose and
throat* — which the spec relegated to its last rung and treated as a mop-up.

The rungs invert. Expansion first, disambiguation second and small.

This is the V0 gate doing exactly its job: it cost an afternoon and it stopped us
building a seven-rung cascade to chase 6.7 points while the 44.9% went untouched.

### Caveats, both small and both stated

**1.6% of the spans (135) carry gold semantic types that map to none of our 11
categories** — `eomi`, `temp`, `fluid`, `cyst`, mostly T190/T042/T032. Those
count as unreachable by construction, so the true ceiling is at most 0.567 rather
than 0.551. It does not change the conclusion.

**The floor is measured on the isolated surface**, not in note context. A real
run has a window, a `min_match_length` that excludes two-character tokens, and
overlap resolution. So the floor figures are an upper bound on what the shipped
pipeline achieves in situ, which makes the 6.7-point budget an upper bound too.

**"Abbreviation-shaped" is mechanical** — one token, 2–6 alphabetic characters —
and deliberately so. It sweeps in ordinary words the annotators marked (`clear`,
`left`, `mild`, `neck`), which is a cost worth paying: a definition that required
judging what "is really an abbreviation" would put the finding at the mercy of
the judgement.

## `structural_labels.json` — stage 3a, finally with an artifact

`concepts/structural.py` recovers the label half of `Creat-1.1`. It has been in
the repo and tested since commit `34e34c4` and was quoted at "+35% procedure
recall" **from a commit message**, with nothing committed behind it. That is
precisely the failure this directory's opening rule names, so here is the
measurement.

Same matcher, same notes, same gold, emitter off then on, 68-note test split:

| Category | Gold | Recall off → on | Δ | Precision off → on | Δ |
|---|---:|---|---:|---|---:|
| **`lab_measurement`** | 3,640 | **0.1047 → 0.3025** | **+0.1978** | **0.3040 → 0.5422** | **+0.2382** |
| **`procedure`** | 7,851 | **0.3123 → 0.4149** | **+0.1026** | **0.3252 → 0.3815** | **+0.0563** |
| `anatomy` | 2,610 | 0.6322 → 0.6345 | +0.0023 | 0.2478 → 0.2328 | −0.0150 |
| `disorder` | 12,002 | 0.7304 → 0.7307 | +0.0003 | 0.4843 → 0.4810 | −0.0033 |
| `disease` | 4,819 | 0.7398 → 0.7398 | 0.0000 | 0.5478 → 0.5403 | −0.0075 |
| `symptom` | 2,187 | 0.6996 → 0.6996 | 0.0000 | 0.6707 → 0.6707 | 0.0000 |
| `lab_result` | 137 | 0.0657 → 0.0657 | 0.0000 | 0.0375 → 0.0233 | −0.0142 |

**Recall and precision rise together in both categories that move**, which is
unusual and has a cause: the emitter adds spans in a *position where the gold is
dense* rather than guessing more widely. The `procedure` commit-message figure
(0.3026 → 0.4071 on 20 notes) reproduces on the full split.

`lab_measurement` is the larger result and the one that justifies the category
existing. It nearly triples recall and adds 24 points of precision, because the
label slot of `Creat-1.1` is exactly what it names — and because it is indifferent
to whether the annotators typed that analyte as a result (T034) or as the
procedure producing it (T059). At 3,640 gold spans it is a bigger category than
`anatomy`, not a bookkeeping device.

The costs are small and real: `anatomy` and `lab_result` precision each fall
about 1.5 points, because a label slot occasionally holds something that is not
an analyte.

### The `HEENT:` slot is built, measured, and parked

The V0 placement survey found a second structural position: 793 gold spans
sitting on an exam-system label, 71.9% of them with no reachable UMLS candidate —
the largest structural slot with no handler at all. `exam_label_spans` handles
it, and finds 898 candidates over 68 distinct surfaces (`heent` 71, `neuro` 61,
`cv` 48, `skin` 46, `abdomen` 42, `ext` 38).

Measured **in isolation**, it does not pay for itself:

| Slot | `procedure` recall | `anatomy` precision | `disease` precision |
|---|---:|---:|---:|
| value labels — `Creat-1.1` | **+0.1026** | −0.0150 | −0.0075 |
| exam labels — `HEENT:` | +0.0059 | −0.0117 | −0.0101 |

So it is **off by default**, and the reason is not that the slot is a bad idea.
The gold spans it targets are exactly the ones no terminology carries — `heent`,
`neuro`, `ext` — so resolving them needs the **expansion table**, not the
emitter. Alone, the emitter can only add labels UMLS already had (`neck`,
`skin`, `abdomen`), which the matcher was largely finding in running prose
anyway; it contributes duplicates and their precision cost without the recall.

It should be switched on in the same change that lands the expansion table, and
re-measured then. Recording it now, off, is cheaper than rediscovering the slot
later — and the isolation measurement is what stops a bundled "structural
recovery" number hiding a component that contributes nothing.

One implementation trap worth keeping: exam labels are **inline** — the finding
follows on the same line — so filtering to standalone headers, which is the
intuitive reading of "the label sits alone in its slot", finds zero of them. The
first version did exactly that.

### With the expansion table

The table lands and closes most of the headroom below. Same on/off measurement,
68-note test split, `lab_shorthand.yaml` at 99 entries:

| Category | Gold | Recall off → on | Precision off → on |
|---|---:|---|---|
| **`procedure`** | 7,851 | **0.3123 → 0.5016** | **0.3252 → 0.4256** |
| **`lab_measurement`** | 3,640 | **0.1047 → 0.4896** | **0.3040 → 0.6549** |
| `anatomy` | 2,610 | 0.6322 → 0.6345 | 0.2478 → 0.2303 |
| others | | unchanged | −0.01 or less |

**`procedure` recall +61% relative, `lab_measurement` +368%**, with precision
rising in both. Structural resolution goes from **70.3% to 94.0%** of candidates.

The expansion contributes about as much again as the structural emitter did on
its own — which is the V0 gate's prediction holding up: the miss set was a
vocabulary gap, and vocabulary is what closed it.

### A prediction that was tested and failed

The exam slot was parked with a stated reason: its gold spans are the ones no
terminology carries, so it should become worthwhile *once the expansion table
lands*. **It did not.** With expansion on, the slot still buys only +0.0058
`procedure` recall against −0.0117 `anatomy` and −0.0098 `disease` precision.

Expanding `heent` to *head eyes ears nose and throat* does resolve it — to a
body-system concept the annotators do not mark in that position. So the emission
is a false positive rather than a recovery, and the slot stays off for a measured
reason rather than a provisional one. What would change the verdict is evidence
about how the gold treats exam-subsection labels, not more vocabulary.

Recorded because it was our own hypothesis and it was wrong.

### The headroom is the point

**Before the table: 3,247 label candidates, 2,282 resolved — 70.3%.** The
missing 29.7% was the
stage-3a expansion table's job: the emitter resolves a label by matching its
surface in isolation, so `creat` and `angap`, which are in no terminology,
resolve to nothing however well the structure identifies them. Structure finds
where they are; only vocabulary can say what they are.

## The phenotype-set family — declared, runtime, reachable, observed

Six artifacts describe the phenotype concept sets, and each answers exactly one
question; conflating any two of them has already produced a wrong table once
(the runtime/declared gap Table 2 was built to expose).

- **`phenotype_set_audit.json`** (`validation/phenotype/scripts/phenotype_set_audit.py`, rendered as
  `validation/phenotype/phenotype-concept-table.md`) — what each phenotype *declares*, by facet
  (how the concept got in) and by semantic category (what it is). Counts the
  SHIPPED sets: the LLM-proposed facet is gated by the vetting verdicts.
- **`phenotype_runtime_sets.json`** (`validation/phenotype/scripts/phenotype_runtime_sets.py`) —
  what `build()` actually *carries*, the denominator of every coverage number.
  Measured equal to the audited union for all 22 phenotypes on this install;
  `tests/test_phenotype_vetting.py` fails when it drifts from a fresh build.
- **`phenotype_link_audit.json`** (`validation/phenotype/scripts/phenotype_link_audit.py`) — can the
  matcher recover each concept *from its own preferred name*. Audits the bare
  disorder closure; the `--facets --full` variant writes
  **`phenotype_link_audit_facets.json`** over the full runtime sets with
  complete unreachable-CUI rosters, which the coverage report joins.
- **`phenotype_density.json`** (`validation/phenotype/scripts/phenotype_density_tables.py`,
  rendered into `data/experiments/baseline/phenotype_density.md` and
  `data/mipa_exp1/table1_sample/phenotype_density.md`, collected into the
  Table 1 family) — concepts declared vs observed per phenotype, for both
  denominators (1,388 notes and the 500 evaluated), with the UMLS validation
  column (`no MRSTY` = declared CUIs absent from the release; zero
  everywhere), surface coverage, and the observed concepts broken down by
  the shipped exclusive category partition.
- **`phenotype_corpus_coverage.json`** (`validation/phenotype/scripts/phenotype_corpus_coverage.py`,
  rendered as `validation/phenotype/phenotype-corpus-coverage.md`) — how much of each set the
  MIPA corpus *instantiates*: declared / reachable / observed, per-cohort
  observation, mention concentration (head90), and the enrichment screen —
  a review queue for non-specific concepts, explicitly not a precision
  measurement.
- **`phenotype_eval.json`** — the gold-span measurement over 68 annotated
  notes, described in its own section below. Coverage is not recall; that file
  is the recall side.

The vetting verdicts themselves ship as a resource, not a measurement:
`src/robustehr/resources/phenotype_vetting.yaml`, written by
`validation/phenotype/scripts/phenotype_vet.py` (LLM triage over the medication, proposed and
closure facets) and updated by `validation/phenotype/scripts/phenotype_review_ingest.py` (clinician
overrides, recorded with a `reviewer` field the model rows never carry).

Two closure artifacts joined the family after the evidence audit found
decisive surfaces grounding to CUIs one relation outside the sets:

- **`src/robustehr/resources/phenotype_closure.yaml`**
  (`validation/phenotype/scripts/phenotype_closure.py`) — closure CANDIDATES: the bounded one-hop
  neighborhood of each set over the isa+MTH-RN hierarchy (parents everywhere;
  siblings only in the disorder top region and the small declared facets;
  umbrella parents fan-out-capped; hierarchy isolates individually declared).
  Corpus-blind by construction. Candidates admit nothing by themselves: the
  built sets intersect them with the `closure` vetting verdicts (strict gate —
  no verdict row, no admission).
- The RxNorm identity closure needs no artifact of its own: it lives in
  `data/umls_facets.json` (`variants`: `tradename_of`/`has_ingredient` from
  `tty='IN'` ingredients) and expands admitted medication ingredients into
  their brand and product CUIs at tier `identity`, reported separately in the
  audits so dose-form fan-out never inflates a headline count.
- The corpus-facing effect is measured in `phenotype_corpus_coverage.json`'s
  `near_miss` block — the headline is `notes_with_recovered_evidence`: the
  share of positive notes mentioning an adjudicated closure keep or identity
  variant the pre-closure target could not reach (88–96% for the
  audit-exposed phenotypes).
## `clinical_targeting.json` — the Experiment 2 rule

- **`clinical_targeting.json`** (`validation/pipeline/scripts/validate_clinical_targeting.py`) —
  precision/recall/F1/coverage of candidate targeting rules against the held-out
  SNOMED-EL split; the measurement behind the adopted `ClinicalSalience` rule.
  Narrative in `validation/protocol.md` §9.
> Two artifacts that used to be documented here — `causal_probe*.json` and
> `edit_placement.json` — moved to the mipa-corrupt repository with the
> experiments that produce them. Both measure what a *model* did on a corrupted
> corpus, which is a downstream result rather than a measurement RobustEHR makes
> about itself.

## Artifacts without a section of their own

Three files here are referenced by scripts and tests but have no narrative entry,
which is recorded rather than left to be noticed:

- **`challenge_metric_scoped.json`** — the corrected-split challenge score under
  QuickUMLS defaults (68 notes, 23,131 gold spans, 0.1733 concept / 0.4406 span).
  Its superseded sibling `challenge_metric.json` (40 notes, 3,777 spans) was
  computed under the `split()` bug and is retained only so the correction is
  auditable. **Read the scoped one.**
- **`baseline_profile.json`** — the Document Quality Profile over the development
  corpus, described under the DQP heading above.
- **`category_prevalence.json`** — per-category gold prevalence, used to weight
  the ablation and to size which categories a measurement can actually resolve.

## `disambiguation_ceiling.json` + `anchor_vote.json` — stage 3c, gated then measured

The third V0-style gate in this stage, and the third time measuring first changed
what got built.

### The gate: how much is left for context to do?

Most-frequent sense — always answer with the sense a form usually has — needs no
cues, no inventory and no authoring. Fitted on `train`, reported on `test`, over
free-prose abbreviation-shaped spans only (structural slots are already resolved
by position, and general-English words are not abbreviations):

| | |
|---|---:|
| MFS accuracy | **0.8992** |
| total headroom | 0.1008 |
| **reachable headroom — the real budget** | **0.0629** |
| unreachable (UMLS carries no such sense) | 0.0378 |

The split matters and is the same distinction the stage-3 gate drew. A form the
gold assigns several concepts to while UMLS offers at most one — `fluid`,
`intact`, `stable` — is not a disambiguation problem: no policy over candidates
can select a candidate that does not exist. Counting it as headroom would promise
the rung something it can never deliver.

So anchor voting competes for **~0.86% of the gold**. The rung is sized to that.

### Baseline: leave the abbreviation intact and let the matcher decide

The most natural objection to building this rung at all — UMLS already carries
five senses for `RA`, so why not let matching and ranking pick one? Measured over
the same 188 held-out occurrences:

| Configuration | Coverage | Accuracy | `RA` resolves to |
|---|---:|---:|---|
| matcher, `min_match_length=3` (shipped) | 0.223 | 0.738 | *nothing at all* |
| matcher, `min_match_length=2` | **0.904** | **0.318** | **refractory anemia, 66/66** |

**It does not work, and the failure has two halves.** At the shipped length floor
the matcher never sees `RA` — a two-character token is below the threshold — so
78% of these spans get no mention. Lowering the floor to admit them raises
coverage to 0.904, emits 5,000 extra mentions across the split, and **collapses
accuracy to 0.318**. It answers `RA` with C0002893, *refractory anemia*, in every
one of 66 occurrences, in a corpus where `RA` is room air about 97% of the time.

The mechanism is the tiebreak: among equally-scoring candidates the matcher sorts
by CUI, and `C0002893` sorts first. Deterministic, and wrong — the measurement
behind the rule that **determinism is necessary, not sufficient**.

Against this baseline at equivalent coverage, the anchor vote is **+24 accuracy
points** (0.977 against 0.738).

### The result: worse on the headline, better where it matters

Seven forms, 188 held-out occurrences. Cues authored from clinical knowledge;
only the sense-name-to-concept binding is fitted, on train.

| | coverage | accuracy |
|---|---:|---:|
| anchor vote | 0.229 | **0.977** (42/43) |
| most-frequent sense | 1.000 | **0.968** (182/188) |

On the headline, MFS wins. The interesting number is the cross-tabulation:

| | count |
|---|---:|
| MFS wrong / **anchor rescued** | **3** |
| MFS wrong / anchor abstained | 2 |
| MFS wrong / anchor also wrong | 1 |
| MFS right / anchor broke it | 2 |
| MFS right / anchor agreed | 39 |
| MFS right / anchor abstained | 141 |

Net +1 on 188 — which is noise. But **all three rescues are `RA` → right atrium
inside echocardiogram reports**, and that is not noise, it is a *correlated*
failure. MFS is fitted to room-air dominance, so it is wrong on every echo
report; the cues are right on all of them.

### Why it ships on anyway

**Most-frequent sense is not the alternative.** It is a yardstick. It encodes one
corpus, and the three published `RA` priors disagree outright — CASI puts right
atrium at 0.788, Stetson room air at 0.859, Vanderbilt at 0.900. Shipping a
MIMIC-fitted prior would transport a MIMIC answer everywhere, and its confidence
is measurably not a usable abstention signal: raising the Vanderbilt threshold
past τ=0.80 *reduces* accuracy.

The real alternative is what the matcher does today: break ties alphabetically by
CUI, which answers `RA` with *refractory anemia*. Against that, 42/45 is a large
win, and 146 abstentions are 146 confident errors not made.

### Honest limits

- **The accuracy comparison rests on 45 answered cases.** The robust finding is
  the coverage gap; do not read the third decimal.
- **`pe` was the weak entry and was repaired**, which is the clearest example of
  what a cue must be. Both of its held-out errors were the same mistake: `exam`
  and `examination` firing *physical examination* on a radiology order header
  (`REASON FOR THIS EXAMINATION: Eval AD/PE`) and on prose discussing an
  embolism. Those words co-occur with everything in a clinical note, so they are
  **associated** with the sense rather than **discriminative** of it. Removing
  the sense entirely took `pe` to 3 of 3 and the rung to 0.977. `PE` meaning
  physical examination is a header usage that the structural layer resolves by
  position; in running prose it is the embolism.
- **This corpus has little abbreviation ambiguity to resolve.** `RA` is 97.2% one
  sense here; `cva`, `dm`, `sob` and `bs` are effectively monosemous. The rung's
  value is a property of the corpus as much as of the method, and on a corpus
  with genuinely balanced senses it would look very different. That is an
  argument for keeping the abstention accounting, which makes the difference
  visible, rather than for tuning the cues to this corpus.

## `abbrev_snomed.manifest.json` — SNOMED records its own abbreviations

The hand-authored table raised an obvious objection: why write these by hand at
all? **SNOMED already carries them.** Its synonym convention is
`ABBREV - full term`, so the terminology contains

```
HFrEF - heart failure with reduced ejection fraction    SNOMEDCT_US  SY
COPD - Chronic obstructive pulmonary disease            SNOMEDCT_US  SY
```

as ordinary atoms. Exact matching on `hfref` finds nothing — no atom *is*
`HFrEF` — while the mapping sits in the row. This was missed once and asserted as
"`hfref` is not in UMLS", which was wrong: it is there, embedded.

`validation/pipeline/scripts/build_abbrev_inventory.py` splits on the separator and keeps the
monosemous half. From 9,994 candidate atoms: **4,015 abbreviations mapping to
exactly one concept**, 927 rejected as ambiguous. `hfref → 703272007` — the same
code the gold uses. `htn → 38341003` — our hypertension phenotype seed.

The artifact lives under `data/` with a committed manifest, because the short
forms are UMLS strings. Only the manifest ships.

### Two filters, and the second is the one that matters

*Monosemy among the abbreviation atoms* is the obvious criterion, and it is not
sufficient. `PT - Platinum` is the **only** `ABBREV - full term` atom for `PT`,
so that filter calls it unambiguous — while in clinical prose `pt` overwhelmingly
means *patient*. **A terminology's monosemy is a property of its synonym set, not
of how clinicians write.**

The second filter asks a different question: **is the short form ambiguous *as
written*?** Count the concepts carrying an atom equal to the surface itself.

| Surface | Concepts as written | Verdict |
|---|---:|---|
| `pt` | 9 | rejected — the anchor vote owns it |
| `ca` | 5 | rejected |
| `ra` | 5 | rejected |
| `copd` | 3 | rejected |
| `hfref` | **0** | kept |
| `rdw` | **0** | kept |

Requiring **zero**, rather than merely few, does three things at once: it
excludes every ambiguous form by construction, it excludes forms the matcher
already resolves unaided and which need no entry, and what remains is exactly
the population the table exists for — surfaces the terminology cannot reach as
written, that mean one thing when it can.

| | before filter | after |
|---|---:|---:|
| entries | 3,999 | **1,626** |
| unreachable gold spans covered | 306 (8.3%) | 209 (5.7%) |
| **of those, code matches gold** | **59.2%** | **80.4%** |

Fewer answers, and 21 points more of them right. `pt → Platinum` is gone by
construction rather than by a blocklist, which is what makes the filter
trustworthy on a corpus nobody has looked at.

### What this changes

Two things follow, and they divide the labour rather than duplicating it:

- The hand-authored `lab_shorthand.yaml` is **not redundant**. Its entries —
  `creat`, `angap`, `urean`, `rdwsd` — are institutional laboratory shorthand
  absent from every terminology, which is why the stage-3 gate found them
  unreachable in the first place. They cannot be derived from anything.
- The derived inventory's real value is the disease and procedure abbreviations
  the hand table never covered (`hfref`, `copd`, `nstemi`, `dka`), and `rdw`
  alone accounts for 137 of the 306 covered spans. Wiring it needs the same slot
  discipline the hand table has, and that is not built.

Recorded now, with its gate, so the option is available and its hazard is on the
record rather than discovered later by a user whose notes say `pt`.

## `abbreviation_load.json` — abbreviation ambiguity as a baseline dimension

A property of the notes **before any operator runs**, in the same sense as
misspelling rate and de-identification density, and for the same reason: a note
dense in ambiguous shorthand is harder for every reader independently of anything
this package does to it. That makes it a plausible **stratifier** — "performance
fell 6 points under this operator" reads differently once you know the affected
tertile carried three times the ambiguous shorthand.

Two headline numbers and a band above them, over 200 development notes:

| | count | rate |
|---|---:|---:|
| abbreviation-shaped tokens | 41,571 | — |
| **ambiguous** — 2+ UMLS concepts as written | **16,985** | **0.409** |
| **highly ambiguous** — 5+ concepts | **6,481** | **0.156** |
| ambiguous counted in SNOMED concepts | 11,645 | 0.280 |

**Two clinical abbreviations in five are ambiguous, and one in six has five or
more readings.** The worst offenders are not the ones a clinician would name:

| surface | occurrences | senses |
|---|---:|---:|
| **`po`** | **4,684** | **15** |
| `pm` | 906 | 3 |
| `hct` | 425 | 2 |
| `mcv` | 360 | 3 |
| `ra` | 304 | 5 |
| `ct` | 326 | 4 |

`po` at fifteen senses dominates by an order of magnitude, and `RA` — the case
the literature and this project's own design discussion revolve around — is
sixth.

### Defining "abbreviation" took three attempts

The count is only as good as the definition, and the first two were wrong in the
direction that flatters the result. Recorded because the failures are the
instructive part.

**Attempt 1 — mechanical.** Any token of 2–6 alphabetic characters. Counted
`clear`, `left` and `small` as abbreviations. The stage-3 gate already flagged
this and reported the inflation rather than fixing it.

**Attempt 2 — subtract `general_english()`.** Better, and still wrong by 71%.
That list *deliberately removes* the 2,686 words carrying a high-precision
clinical type, so `resolve_tags` can let the terminology speak for them —
correct for that question, and wrong for this one, because it means `stable`,
`mild`, `wound` and `fever` are absent from it and were each counted as
abbreviations. The corpus count was **169,166** against a true 41,571.

The fix was to recognise that two different questions need two different lists.
`validation/pipeline/scripts/gen_general_english.py` now emits both from one pass, so they cannot
drift: `general_english.txt` (25,185 words, clinically subtracted) answers
*should the terminology speak for this word*, and `english_vocabulary.txt`
(28,329 words, nothing subtracted) answers *would a reader recognise it*.

**Attempt 3 — the word list over-excludes.** `ra` is *in* the English
vocabulary — Ra, the Egyptian god, clears Zipf 3.0 — so the list alone loses
`RA`, along with `PO`, `MS`, `PE`, `DM` and `BS`.

**No frequency threshold separates these.** `ms` sits at Zipf 4.67 and `mild` at
4.11, so any cut that keeps the abbreviation admits the adjective. The signal
that does work is orthographic:

| Rule | Admits | Rejects |
|---|---|---|
| not in the English vocabulary | `hgb`, `creat`, `angap`, `wbc` | — |
| mixed case — a capital the author chose | `HFrEF`, `AnGap` | `Stable`, `BLOOD` |
| all capitals **and ≤ 3 characters** | `RA`, `PO`, `MS` | `BLOOD`, `STABLE` |

The length bound on the third rule is what stops it readmitting everything:
`BLOOD` is all-capitals in every MIMIC lab line and alone contributed 1,813
spurious ambiguous tokens before it was added.

### Why two denominators

Senses are counted in **UMLS concepts**, with the SNOMED subset reported
alongside. UMLS is the right denominator for "how ambiguous is this token",
because it is the space the matcher actually chooses among; SNOMED is carried
too because that is the space a phenotype is declared in. The two differ by
about a third, and a reader should not have to guess which produced a number.

Reproduce with `robustehr ambiguity --corpus <notes> --per-note`, which also
emits each ambiguous token's span so they can be located rather than only
counted.

## The abbreviation ceiling moved, and the reason is the point

`abbreviation_ceiling.json` was re-run with stage 3 in the evaluation path. The
plan asserted the *ceiling* could not move, being a property of UMLS and the
gold. It moved — **0.5511 → 0.5697** — and the assertion was wrong in an
instructive way.

The ceiling asks whether any UMLS candidate carries the **annotated category**,
so it is a property of UMLS, the gold, **and our category taxonomy**. Adding
`lab_measurement` made a class of spans reachable that were not: the ones UMLS
types T034 while the annotators chose T059. That is population (b) of the
44.9% — the group that needed a taxonomy decision rather than a rung — and the
ceiling rising is that decision taking effect.

The floor rose too, from 0.4346 to **0.4533**, which is stage 3 arriving.

## `normalization_ceiling.json` — stage 4, gated and not built

The fourth gate, and the first to return a clear "no".

Stage 4 exists because a note writes `hyperkalemic` where the terminology holds
`hyperkalemia`. NLM built the instrument for it: **`MRXNS_ENG`** is the
Metathesaurus indexed by *normalized* string — lowercased, inflection-stripped,
stopword-dropped, word-sorted — so the reuse rule applies in its strongest form.
The component already exists; the only question is what it buys here.

Over the 68-note test split, against the **12,091,090** normalized keys in the
2026AA release:

| | |
|---|---:|
| gold spans the shipped pipeline misses | 3,557 |
| reachable by a normalized lookup | 2,376 (66.8%) |
| **…carrying the right concept** | **418** |
| **ceiling gain for stage 4** | **11.8% of the miss set** |

**418 spans is 1.8% of the corpus.** For scale, stage 3 delivered roughly 1,486
`procedure` spans and 1,401 `lab_measurement` spans on the same gold — seven
times as much, from a component the same discipline nearly talked us out of
building the wrong version of.

### The precision number is the more interesting one

A normalized lookup **reaches something 66.8% of the time and the right thing
17.6% of the time.** Normalization is lossy by design: sorting the words and
stripping inflection collapses distinct concepts onto one key, so a hit is
usually a collision rather than a recovery. Any real use would need a ranking
step on top, and that step would be competing for the 11.8%.

The measurement is deliberately an **upper bound** — the gate tries two candidate
normalizations per surface and counts a hit on either, where a real normalizer
produces one key. So 11.8% is the optimistic reading.

### What the residue says

The spans normalization cannot reach are not morphological variants at all:

```
rrr 49   ctropnt 37   gallops 34   eomi 31   clubbing 29   nontender 23
o2 sat 20   rle 16   ox3 15   wwp 15   xrt 9   bcx 9
```

Roughly half are abbreviations — stage 3's territory, and mostly the
institutional forms already known to be absent from every terminology. The rest
are exam findings (`clubbing`, `gallops`, `rebound`) that UMLS either lacks or
types outside our categories. Neither is a normalization problem.

### The decision

**Stage 4 is not built.** The ceiling is small, the instrument is imprecise, and
the residue points elsewhere. That is the gate doing its job for the fourth time,
and the first time the answer was to build nothing at all.

What would change it: a corpus with heavier derivational variation than discharge
summaries, or a use where 1.8% matters more than the noise a lossy key
introduces. Both are stated so the decision can be revisited on evidence rather
than re-argued.

## `spelling_methods.json` — the detector validated, the correctors compared

Two questions, both raised because the earlier stage-4 gate measured
*derivational* normalization and never asked about spelling.

### Is the misspelling estimator sound? It under-counts by a quarter

The Document Quality Profile calls a token a suspected misspelling when it is
unrecognized, alphabetic, at least four characters, and occurs once in the whole
corpus. A reasonable heuristic, and **it had never been checked**.

It can be, because the estimator and `input.typo` are **dual** — one injects at
measured dose, the other estimates. That is the injection–recovery design the
release gates already specify.

| severity | injected | detected |
|---|---:|---:|
| 0 | 0 | 531 |
| 0.01 | 557 | 951 |
| 0.02 | 1,091 | 1,350 |
| 0.05 | 2,697 | 2,519 |
| 0.10 | 5,372 | 4,508 |

**slope 0.7401, R² 1.0** against a gate of slope ∈ [0.90, 1.10]. **It fails.**

But the shape is the result. R² of 1.0 means the estimator is *perfectly linear*
and misses a **constant 26%** — it is a consistent under-count, not a noisy one.
Three mechanisms explain the loss and none is fixable by tuning: a typo can land
on another real word (`left` → `lift`) and stay recognized; it can produce a token
that occurs elsewhere and so is not hapax; and `MIN_MISSPELLING_LENGTH = 4`
excludes short words by design.

So the estimator is usable for **ranking notes** and stratifying results, and
must not be read as an absolute count. Stated that way rather than quietly
calibrated, because a 0.74 correction factor fitted on one corpus is a corpus
artifact.

### Which correction method? None of them well enough

Ground truth is exact — the operator knows what each word was before it corrupted
it — over 5,372 corrupted words:

| Method | Vocabulary | Coverage | Accuracy | **Recovery** |
|---|---:|---:|---:|---:|
| **english + clinical, edit-1** | 271,532 | 0.966 | 0.548 | **0.530** |
| english + clinical, edit-2 | 271,532 | 0.985 | 0.538 | 0.530 |
| english only, edit-1 | 28,329 | 0.837 | 0.558 | 0.467 |
| english + clinical, edit-1, no ranking | 271,532 | 0.580 | **0.744** | 0.432 |

`recovery` is correct over *all* corrupted words, and it is the metric that ranks
them: a corrector which always guesses turns every unrecognized clinical term
into a wrong word, so coverage bought by guessing is not a gain.

Three results, in order of usefulness:

**The clinical dictionary is worth 6 points** (0.467 → 0.530). Correcting clinical
text against a general dictionary is the mistake the comparison exists to
demonstrate, and the size of it is now measured.

**Edit distance 2 buys nothing.** Same recovery, more coverage, lower accuracy —
it finds more candidates and picks among them worse. Edit-1 is the right radius.

**And the best method is wrong nearly as often as it is right**: accuracy 0.548
when it answers. A correction stage would introduce roughly one wrong word for
every one it fixed.

Which is the answer to the stage-4-as-spelling question, and it is the same shape
as the stage-4-as-derivation answer: **the instrument is not good enough to be
worth the risk it adds.** Both are recorded so the decision rests on two
measurements rather than on a preference.

## `assertion_stability.json` — the assertion layer is confounded by formatting

The gate for stage 8, and the measurement this package is uniquely able to make.

Five operators carry the contract `INVARIANT_BY_CONSTRUCTION`. Each declares a
canonicalizer κ, and CI proves `κ(apply(d)) == κ(d)` over the corpus at every
severity — **no clinical reference can change under them**. Restyling a
de-identification placeholder, collapsing a run of spaces, or rewriting a bullet
as prose leaves what the note says about the patient exactly as it was.

So an assertion that flips under one of them is reading something that is not
clinical content. Over 20 development notes, ~14,600 mentions per operator, run
on **both** segmenters so the difference is attributed rather than guessed:

| Operator | our boundaries (shipped) | PyRuSH |
|---|---:|---:|
| `render.header_style` | **0.0000** | 0.0020 |
| `render.lab_block_collapse` | **0.0000** | 0.0026 |
| `render.whitespace_collapse` | **0.0026** | 0.0044 |
| `render.bullet_to_prose` | **0.0050** | 0.0072 |
| `render.deid_restyle` | 0.0116 | **0.0001** |
| **overall** | 0.0039 | 0.0033 |

**The overall figures are close and their composition is completely different**,
so they must be read per operator. And the transitions are the clinically serious
kind in both arms — affirmed → negated and negated → affirmed on text proved to
say the same thing.

### The segmenter trade, and the same property in both directions

Our segmenter models list, header and lab-block structure, so perturbing those
cannot move it: two operators go to **exactly zero**. It also models
**de-identification placeholders**, which makes the placeholder convention an
input to its own rules — so restyling one convention into another moves its
boundaries and the assertion moves with them, and `deid_restyle` rises to 0.0116
against PyRuSH's 0.0001. PyRuSH models neither, so list structure moves it and
restyling barely does.

There is no configuration here that is stable against everything, and saying so
is more useful than picking the arm that flatters the shipped default.

### This corrects our own earlier emphasis — twice

`deid_assertion_probe.json` found this mechanism on **one note** and concluded
that assertions must be reported *per de-identification scheme*. On PyRuSH at
corpus scale, de-id restyling turned out to be the *least* disruptive of the five
by two orders of magnitude, and the dominant cause was list and whitespace
structure. That was correction one.

Correction two is that the first correction was itself segmenter-specific. Under
the boundaries the package actually ships, `deid_restyle` is the **worst** of the
five, and the probe's original emphasis was closer to right than its corpus-scale
replacement — for a different reason than the probe gave.

**A constructed example is good for showing that a mechanism exists and bad for
estimating how much of it there is.** That applies to the seven templates in
`assertion_deid_invariance.json` too: they report 0.0000 instability for our
boundaries on the very operator this table puts at 0.0116.

### What it bounds

**0.39% is not a performance number, it is the size of a confound.** Any result
conditioned on assertion — every phenotype `evidence_touch` broken down by
affirmed versus negated — carries it. It is small in absolute terms and it is not
noise: it is systematic, reproducible, and concentrated in exactly the operators
this package applies on purpose.

### And it is not a validation

**A contextualizer that marked every span affirmed would score a perfect 0.0000
here** while being wrong on every negation in the corpus. Invariance describes an
instrument's response to noise; it says nothing about the signal. That is why
`assertion_accuracy.json` exists, and it generalises: *for any component gated on
robustness, ask what a trivially wrong version would score.* Where the answer is
"perfect", the gate is not a validation and a second instrument is owed.

## `assertion_accuracy.json` — six arms against published gold

The correctness measurement the stability gate cannot give. Chapman's NegEx test
set, 2,365 concept-level assertions over discharge summaries, 20.8% negated, each
concept sitting *inside* its sentence — the shape `qualify` consumes, so
assertion is measured in isolation from detection.

**The floor is high, and that decides the metric.** Always-affirmed scores 0.7924
accuracy while getting every negation wrong, so **negated-class F1 is the
headline** and accuracy is reported only beside it.

**What is a baseline and what is not.** medspaCy ConText is the instrument this
package *ships*, under the reuse rule — so it cannot also be the baseline it is
measured against, and the ladder row that once said so was incoherent. The floors
are majority class and the cue window; the external comparisons are negspaCy (an
independent implementation of the same algorithm) and the dependency parse (a
different algorithmic family). The two ConText rows are an **internal ablation**
of the one thing we change about the reused component — the sentence boundaries
it scopes cues to.

| Arm | accuracy | precision | recall | **F1** |
|---|---:|---:|---:|---:|
| negspaCy — independent NegEx implementation | 0.9742 | 0.9283 | 0.9491 | **0.9386** |
| **medspaCy ConText, our boundaries (shipped)** | 0.9696 | 0.9021 | 0.9572 | **0.9289** |
| medspaCy ConText, PyRuSH boundaries | 0.9696 | 0.9021 | 0.9572 | 0.9289 |
| dependency parse | 0.9277 | 0.9211 | 0.7128 | 0.8037 |
| cue window, ±8 tokens | 0.7252 | 0.4269 | 0.9450 | 0.5881 |
| majority class — always affirmed | 0.7924 | 0.0000 | 0.0000 | 0.0000 |

**Spotting a cue is easy; scoping it is the problem.** The window arm reaches
0.945 recall at 0.427 precision — nearly every negation has a cue nearby, and
what a flat window cannot do is decide how far it reaches. The 0.588 → 0.929 gap
is what cue-scope resolution buys, and it is almost all precision.

**The dependency arm inverts that, for a linguistic reason.** English parses
*"No pericardial effusion"* as a **determiner** and reserves `neg` for *"not"*,
which is rare in clinical prose; *"denies fever"* carries its negation in the
verb, where no parse relation marks it. A textbook `neg`-only detector scores
**0.0000** here. The arm reported is deliberately the strongest fair version —
it also accepts a negating determiner on the mention's head chain — because
reporting the 0.0000 would be a straw man. The residue is the lexical case, and
it is the empirical reason this field built cue systems rather than using parsers.

**negspaCy wins by a point and is still not what ships.** A separate codebase
implementing the same published algorithm, so its agreement is evidence about
*Chapman's method* rather than about one implementation — the arm that makes the
reuse argument checkable. It is not the component to use because it detects
negation *and nothing else*: ConText returns five dimensions, negation is only
17.8 of the 30.1 non-affirmed points, and the cue and scope spans are what give
the SEMANTIC channel a dose denominator. One F1 point on one dimension against
four dimensions and an operator channel.

**This gold cannot separate the two ConText arms**, and the tie is structural
rather than a result: every row is a single sentence, so no cue can leak across a
boundary and both segmenters return the same one. Reading 0.0000 as "our
boundaries do not help" would misread an experiment with no power to detect it.

Reproduce (needs the gold in `data/`, and `negspacy`):

```
python validation/pipeline/scripts/fetch_negex.py
python validation/pipeline/scripts/assertion_accuracy.py --out validation/measurements/assertion_accuracy.json
```

The NegEx repository carries **no licence**, so the gold is handled exactly like
MIMIC — `data/` only, and this artifact carries counts and metrics, never a
sentence.

## `assertion_deid_invariance.json` — where the segmenter question is answerable

Seven templates, each placing a negation cue and its target in different
structural units, crossed with seven de-identification conventions. The question
needs no gold: *a placeholder carries no clinical meaning, so swapping one
convention for another cannot change what a note says.* An arm whose verdict
moves with the convention is reading formatting, not medicine.

| Arm | accuracy | instability |
|---|---:|---:|
| **ConText, our boundaries** | **1.0000** | **0.0000** |
| negspaCy | 1.0000 | 0.0000 |
| dependency parse | 0.8571 | 0.0000 |
| ConText, PyRuSH boundaries | 0.7755 | 0.1429 |
| cue window | 0.6122 | 0.1429 |

Replacing the segmenter fixes these templates without touching a rule — which is
what four documents claimed and none had checked, and it is the L4 rung. The
dependency arm is stable and loses `lexical_negation`, precisely the failure the
gold predicted.

At corpus scale the same substitution moves the non-affirmed rate on gold
phenotype evidence from **34.7% to 30.1%** over identical spans, `historical`
alone dropping from 90 to 65 — so roughly 4.6 points of what was previously
reported as clinical fact was cue leakage across list and header boundaries.

> **Read this beside `assertion_stability.json`, which qualifies it.** These
> seven templates are a *constructed* set and they report 0.0000 instability for
> our boundaries. On 20 real notes the same segmenter scores **0.0116 on
> `deid_restyle`** against PyRuSH's 0.0001 — on the very operator the templates
> were built around. Our segmenter models de-identification placeholders, so the
> convention is an input to its own rules. The corpus-scale claim is narrower
> than this table: our boundaries are **more accurate under a change of
> convention and less stable under one**.

## `assertion_disagreement.json` — does our modification move UMLS concepts, and is it right?

Stage 8 reuses medspaCy's ConText engine and changes exactly one thing about it:
the sentence boundaries cues are scoped to. A departure from a reused tool owes a
number against that tool, and the two existing measurements cannot supply one —
`assertion_accuracy.json` reports the arms as identical because its gold is single
sentences, and `phenotype_assertion.json` shows the rate moving without showing
the moves were right.

Over 20 notes and **13,981 matched UMLS concept spans**, the arms assign a
different attribute to **673 — 4.8%**. Attributes involved: `negated` 361,
`historical` 204, `uncertain` 82, `hypothetical` 40, `family` 32.

**The referee is the note's own structure, not an annotator.** ConText assigns an
attribute because a cue took scope over a target; if the cue and target sit in
different list items or across a section header, the cue did not govern that
target. That is a fact about the document. The structural layer deciding it is
hand-written, versioned, and validated against PyRuSH at stage 2.

| | spans |
|---|---:|
| structure favours **our boundaries** | **181** |
| structure favours PyRuSH | 41 |
| **undecided** — cue and target share every unit | **451** |
| decidable share | 0.330 |
| **ours, of those decided** | **0.815** |

**The undecided count is the honest headline.** Two thirds of the disagreement
lies where structure has no authority and nothing here licenses a claim about it.
What can be claimed is narrow: *where the note's own structure can rule, it rules
for the boundaries we ship, four times out of five.*

The catches are ordinary. `C0011570` (depression) and `C0003467` (anxiety) marked
`historical+negated` by stock ConText because a `history` cue reached them from a
**different list item**; several concepts negated by a `no` in a **different
section**. Separation reasons: 108 list-item-versus-prose, 60 different list
items, 54 different sections.

## `scope_accuracy.json` — uncertainty, and the control that makes it readable

The only one of the four unvalidated attributes with freely available gold.
BioScope's **clinical subcorpus is unusable** — 872 negation and 1,137 speculation
cues over radiology reports, every token replaced by `*` (0 letters against 42,514
asterisks), reconstitutable only with the 2007 CMC text obtained separately. What
remains is biomedical abstracts: real words, wrong genre.

**So negation was scored on the same sentences as a control**, holding the genre
shift constant:

| | negation | uncertainty |
|---|---:|---:|
| NegEx, clinical | **0.9289** | *no gold* |
| BioScope abstracts | **0.6111** | **0.2511** |
| precision / recall on BioScope | 0.581 / 0.645 | **0.855 / 0.147** |

**The domain shift alone costs 0.318 F1** — same engine, same attribute, only the
genre changed. Any uncertainty figure read against the clinical negation number
would be measuring mostly that.

**Within the corpus uncertainty is still well below negation, and its shape says
why.** Precision 0.855 against recall 0.147: when ConText fires `uncertain` it is
almost always right and misses six hedges in seven — the signature of a *clinical*
hedging inventory (`possible`, `cannot exclude`, `versus`) meeting *scientific*
hedging (`suggesting that`, `these results indicate`).

`is_uncertain` therefore stays **disclosed rather than promoted**. What changed is
that the disclosure now carries a measured characterisation instead of a rule
count.

## `assertion_gold_eval.json` — is the SEMANTIC channel ready, per operator?

Stage 8 exists to serve four perturbation operators, and each inherits its
detector's quality directly: an operator anchored on a detector that fires on the
wrong spans edits the wrong spans. Readiness is therefore a per-dimension
question, and three of the five dimensions had **no gold at all** until this.

`assertion_gold.yaml` is 350 spans over 7 synthetic fixtures, labelled on all
five dimensions and shipped **in the repository**. It was built first because it
needs no permission — the fixtures were written from scratch, whereas disclosing
MIMIC-IV note text to a third party, an LLM API included, requires authorisation
under the PhysioNet DUA. A companion MIMIC gold followed once that was confirmed
(`assertion_gold_mimic.json`); only this one is publishable, because permission
to annotate is not permission to redistribute.

| Operator | Dimension | triggers | cues/note | in-domain gold | κ | Verdict |
|---|---|---:|---:|---|---:|---|
| `semantic.negation_flip` | `negated` | 145 | 26.9 | **NegEx, F1 0.9289** | **0.74** | **buildable** |
| `discourse.distractor_inject` (hypothetical) | `hypothetical` | 17 | 6.2 | none | 0.39 | conditional — recall 0.25 |
| `semantic.temporality_shift` | `historical` | 10 | 5.0 | none | 0.41 | conditional |
| `semantic.uncertainty_flip` | `uncertain` | 48 | 3.2 | none (0.2511 out of domain) | 0.00 | **not yet** |
| `semantic.experiencer_shift` | `family` | 51 | 3.7 | none | 0.22 | **do not build** |

**Eligibility is ample for every dimension** — all five fire in 100% of notes — so
nothing here is blocked for want of material. What separates them is whether the
attribute lands on the right span, and only negation does so with substantial
agreement.

**`experiencer_shift` is the clearest case for not building.** ConText marks 8
spans family where 1 is warranted, and the mechanism is specific: *"brought in by
mother with 3 days of fever"* makes `mother` a FORWARD cue scoping over the
child's **own** symptoms. An operator anchored here would rewrite the patient's
presenting complaint as somebody else's — a fabrication that dose accounting
would report as a clean edit.

**This gold is a second opinion, not a ground truth.** The annotator is an LLM
with prior exposure to this codebase, so κ measures agreement between two
imperfect raters. Two limits are load-bearing: the corpus is negation-dense and
hedge-poor (52 negated spans against 2 uncertain and 1 family, so three
dimensions report counts and κ only), and one **guideline** error had to be
separated from the detector's errors — a first pass labelled *person* mentions as
family, which is a category error, and fixing it moved family from 5 gold
positives to 1 while leaving ConText's over-scoping standing.

On these fixtures stock PyRuSH scores **κ 0.7646 on negation against our
boundaries' 0.7365** — the opposite direction to the MIMIC result. Small sample,
short notes; recorded rather than dropped.

## `context_rule_inventory.json` — the five attributes are not peers

`ATTRIBUTES` is a flat five-tuple, which reads as five comparable signals. The
lexical coverage behind them differs by roughly 14x — and **rule count is the
wrong unit**. A medspaCy rule may carry a token pattern matching a whole list, so
the 102 rules expand to **271 triggers**.

| Attribute | ConText category | rules | **triggers** | cues/note | status |
|---|---|---:|---:|---:|---|
| `negated` | NEGATED_EXISTENCE | 69 | **145** | 26.9 | **validated** — F1 0.9289 |
| `family` | FAMILY | 1 | **51** | 3.7 | disclosed, unvalidated |
| `uncertain` | POSSIBLE_EXISTENCE | 18 | **48** | 3.2 | **out of domain** — F1 0.2511, P 0.855 / R 0.147 (`scope_accuracy.json`) |
| `hypothetical` | HYPOTHETICAL | 9 | **17** | 6.2 | disclosed, unvalidated |
| `historical` | HISTORICAL | 5 | **10** | 5.0 | disclosed, unvalidated |

**This corrects a claim previously made here.** Experiencer was described as
resting on "the single literal `family`", with *"Father with myocardial
infarction"* as an example of what it misses. The rule is *named* `family`; its
pattern carries a 51-term kinship list including `father`, and the category fires
3.7 times per note in 100% of notes. Counting rules where triggers were the
meaningful unit inverted the ranking — experiencer is the second best resourced
category, not the worst. A second claim fell with it: `Hx` **is** covered, by the
`history` rule's `[history, hx, hist, ho]` pattern. `status post` genuinely is not.

There is no PSEUDONEGATION category in the English set, so *"no change"* is
handled only by longest-match pruning; and no CONDITIONAL category, which is why
conditionality — one of ShARe/CLEF 2014's six required metrics — cannot be
produced by this instrument at all.

Regenerated from the installed rule file, so the counts track whichever medspaCy
is in the environment rather than whichever one was current when this was
written.

Two consequences follow. A robustness experiment that perturbs formatting and
then measures an assertion-conditioned outcome is measuring the assertion layer's
brittleness as well as the model's, and must say so. And an operator declared
`INVARIANT_BY_CONSTRUCTION` is invariant with respect to **clinical reference**,
which is what κ proves — not with respect to every downstream tool's reading of
it. The contract lattice was always stated that precisely; this is the first
measurement showing why the precision mattered.

## What is safe to commit here

Everything in this directory is aggregate or metadata:

- **No note text.** Quoted word types are deduplicated vocabulary entries with
  corpus frequencies, and only types occurring at least
  `MIN_EXAMPLE_FREQUENCY` (5) times are quoted at all — a type seen once is not
  really an aggregate, and could in principle be an identifier that survived
  de-identification.
- **No licensed strings.** The manifest carries identifiers, counts and a hash;
  never vocabulary content.

Anything that would violate either rule belongs under `data/`, which is
default-deny in `.gitignore`.

## `segmentation_baseline.json` — the foundation, finally compared to something

Stage 2 of the pipeline is 2,178 lines across `segment/`, and until this it was
validated only against golden fixtures we wrote ourselves. Everything downstream
reads it — concept spans, ConText scope, section priors, and the eligible units
of half the operator suite — so self-validation was the wrong standard for the
most load-bearing component in the package.

**Why agreement and not a gold standard.** No clean public sentence-boundary gold
exists for MIMIC discharge summaries, and annotating one ourselves would make the
reference our own judgement again. So this measures agreement with **PyRuSH**
(what medspaCy ships, and what most clinical pipelines use) and classifies every
disagreement. The taxonomy is the result; the agreement figure alone would be
uninterpretable.

Over 200 notes: **52,809 boundaries against PyRuSH's 65,824, agreeing on 33,209
— Jaccard 0.389.**

That looks alarming and is not. The two systems disagree **by design**:

| Disagreement class | Ours only | PyRuSH only | Adjudication |
|---|---:|---:|---|
| line break, no terminal punctuation | 8,578 | 605 | ours — clinical notes are line-structured |
| de-id placeholder | 5,867 | 2,848 | ours |
| after a colon (header or label) | 3,958 | 334 | ours — `HEENT: PERRLA` is a unit |
| after terminal punctuation | 572 | 6,320 | PyRuSH, mostly |
| mid-line, no cue | 473 | 6,964 | ours — PyRuSH splits hard-wrapped prose |

The de-id row was a **hypothesis stated before the run**: our splitter is de-id
aware and PyRuSH is not, so PyRuSH should split spuriously at placeholders. It
does — cutting `Admission Date: ___ | Discharge Date:` inside the MIMIC header
block, because a placeholder looks like a sentence end to a splitter that does
not know what one is. `deid_assertion_probe.json` prices the consequence: a
spurious boundary lets a negation cue take scope over the next clause and flips
an active diagnosis to negated.

PyRuSH's 6,964 `mid-line, no cue` splits are the same failure wearing a different
hat — cuts inside hard-wrapped prose (`benadryl 50mg x2, | IV lorazepam`), where
the newline is a rendering artifact. That is exactly the wrapping the RENDER
channel perturbs, and it is why this package segments structure itself rather
than delegating to a sentence splitter.

### It found a bug of ours, which is the point

We were splitting lab lines at values written without a leading zero:

```
Lipase 54 / TB .   ||SPLIT||   5 / Alb 3.2
Cl 107 / CO2 21 / Glucose 79 / Lactate .   ||SPLIT||   9
```

The tokenizer merges `4.46` into a single atom so no boundary rule can see
inside it — that is the design the splitter relies on. It cannot merge a point
with no digit before it, so `.5` arrived as punctuation followed by a number, and
boundary confirmation accepted it because it deliberately admits a following
digit so that `2. Hypertension` still splits.

50 spurious boundaries across 200 notes. An entire error class our golden
fixtures never contained, found by running someone else's splitter over the same
text. Fixed, and pinned in `tests/unit/test_sentences.py`.

That is the argument for external baselines in one paragraph: not that PyRuSH is
better — the taxonomy says it is not, for this corpus — but that a component
graded only against its author's own fixtures is graded against its author's own
blind spots.

### Still owed

Section boundaries are not validated separately from sentences. **MedSecId**
(PhysioNet, section annotations over MIMIC-III) is the reference and needs
downloading.
