> **Development record.** This document was written while the component it
> describes was being built and reads as a history. The method as it stands is
> in [`validation/methodology/`](../../methodology/); nothing here is cited by the
> manuscript. Kept so every decision can be audited.

# Abbreviation expansion: how the algorithm was chosen

Clinical shorthand is not a corner case in this corpus. **36.8% of every
expert-annotated span is a single token of two to six alphabetic characters.**
Any concept-matching pipeline that handles them badly handles a third of the
corpus badly.

This chapter documents how the algorithm was arrived at, because the route
matters more than the destination: the design that shipped is close to the
*opposite* of the one originally specified, and each reversal was forced by a
measurement made before the corresponding component was built.

## The principle: gate before building

The project's governing rule is to reuse validated tools and benchmark every
departure against the thing it departs from. Applied to a component that does not
exist yet, that rule has a corollary: **measure the achievable ceiling before
building, not the improvement afterwards.**

The reason is that a resolver graded only on its own before-and-after looks like
progress at any level of performance. "Recall rose 4 points" is compatible with
having captured 4 of an available 40 and with having captured 4 of an available
4.5. Only the ceiling distinguishes them, and only the ceiling can say that a
component is not worth building at all.

Four such gates were run. **All four changed what was built** — and two further
corrections came from questions rather than from tests, both recorded below
because a method chapter that lists only what worked is not a method chapter.

## Gate 1 — is a disambiguator warranted?

The original specification proposed a seven-rung disambiguation cascade: local
definition detection, monosemous inventory lookup, UMLS candidate retention,
anchor voting, conflict abstention, and a curated table as the last resort.

Before writing it, we measured what a *perfect* disambiguator could achieve.
For each abbreviation-shaped gold span, does the UMLS inventory contain **any**
candidate carrying the annotated category? Where it does not, no resolver at any
policy can recover that span.

| Over 8,520 abbreviation-shaped gold spans, 68-note test split | accuracy |
|---|---:|
| shipped matcher | 0.4346 |
| exact lookup, `min_match_length=2` | 0.4837 |
| **ceiling — a perfect disambiguator over UMLS** | **0.5511** |
| **unreachable at any policy** | **0.4489** |

**The entire seven-rung cascade competes for 6.7 percentage points.** Meanwhile
44.9% of the spans have no reachable candidate at all — 2,257 have no UMLS
candidate whatsoever:

```
creat 131   rbc 151   hgb 147   rdw 137   na 100   angap 93
phos 80     heent 68  neuro 68  monos 52  neuts 51  rdwsd 48
```

These are not ambiguous abbreviations awaiting disambiguation. They are **lab and
exam shorthand that UMLS does not contain as strings**. `creatinine` is in UMLS;
`creat` is not. `anion gap` is in UMLS; `angap` is not.

**Conclusion: clinical abbreviation resolution in this corpus is a vocabulary
problem, not a disambiguation problem.** The two call for opposite engineering. A
cascade selects among candidates that already exist and cannot help when the
candidate set is empty. The rungs invert — expansion first, disambiguation last
and small.

The specification had in fact computed this figure in its own validation section
and predicted 53.8% / 44.8% against the measured 55.11% / 44.89%. The arithmetic
was never wrong. The cascade had simply been ordered from a different table,
which sized the vocabulary gap at 3.12%.

### The 44.9% is three populations, not one

Sizing it as one number would have pointed at one fix. It has three:

| Population | Size | Examples | What it needs |
|---|---:|---|---|
| absent from every terminology | ~473 | `creat`, `angap`, `urean`, `rdwsd` | an expansion table |
| in UMLS, no category type | ~640 | `hgb`, `rbc`, `wbc`, `na`, `phos` | a **taxonomy** decision |
| not abbreviations at all | ~432 | `clear`, `left`, `stable`, `mild` | a candidate filter |

The middle group produced the `lab_measurement` category: UMLS types `hgb` as a
test *result* (T034) while the challenge annotators chose the *procedure* that
produces it (T059), and neither reading of `Hgb-9.9` is wrong. The third group
means the headline 44.9% is **inflated**, and the error runs in the direction
that flatters the result, which is the worst direction to be wrong in.

## The algorithm that follows

Split by **what evidence resolves the span**, not by whether context is involved.
The placement of these spans is what makes that question answerable:

| Where it sits | n | unreachable | Resolved by |
|---|---:|---:|---|
| label of a value — `Creat-1.1` | 2,152 | 63.8% | **structural position** |
| followed by a colon — `HEENT:` | 793 | 71.9% | structural position |
| inside a labelled-value line | 109 | 33.9% | structural position |
| free prose | 5,466 | 33.8% | vocabulary, then context |

**Half the unreachable spans are structurally anchored.** A token in the label
slot of `Creat-1.1` is a lab analyte because of *where it is* — no dictionary
sense and no surrounding prose are involved. This is a third answer that a
"context or no context" framing hides, and it is the largest single class.

| Sub-stage | Handles | Evidence | Ships |
|---|---|---|---|
| **3a structural** | `Creat-1.1` | position, from segmentation | on |
| **3b expansion** | `creat` → *creatinine* | a slot-scoped table | on |
| **3c anchor vote** | `RA` → room air \| right atrium | nearby surface words | on |

Two constraints govern the design and neither is a preference.

**Nothing rewrites text.** Every offset in this package is an offset into the
note as written, and the whole edit-script architecture depends on that. An
expander that substituted `creatinine` for `Creat` would invalidate every span in
the document. So the long form is a **lookup key**: it is resolved against the
terminology, and the resulting concept is attached to the *original* span with
the *original* surface.

**Cues are literal surface strings.** Disambiguating `RA` from the *concepts*
around it would require the candidate-generation stage's output, which requires
this stage — a cycle. Surface tokens come from segmentation, which precedes both.

### Slot scoping is the safety mechanism

The obvious objection to a context-free expansion table is that clinical
shorthand is ambiguous. It is — but ambiguity is a property of a form *in a
position*, not of a form.

| Form | In a value slot | In prose |
|---|---|---|
| `pt` | prothrombin time | the patient, or physical therapy |
| `ca` | calcium | cancer |
| `ph` | acidity | past history |

So the entry criterion is **monosemous within its slot**, not monosemous
outright. That admits `pt` and `ca`, which a global table would have to reject,
and still refuses `RA`, which is ambiguous even inside a slot. The structure has
already done the disambiguating, deterministically and for free.

## The baselines, and what each answers

Every claim below is measured against a named alternative on the same held-out
data. Three alternatives, because they answer three different objections.

### Baseline 1 — "leave the abbreviation intact and let the concept mapper decide"

The most natural objection. UMLS already carries five senses for `RA`; why not
let matching and ranking pick one?

Measured over 188 held-out occurrences of the seven cue-covered forms:

| Configuration | Coverage | Accuracy | What `RA` resolves to |
|---|---:|---:|---|
| matcher, `min_match_length=3` (shipped) | 0.223 | 0.738 | *nothing at all* |
| matcher, `min_match_length=2` | **0.904** | **0.318** | **refractory anemia, 66/66** |

**It does not work, and the failure has two distinct halves.**

At the shipped length floor the matcher never sees `RA` — a two-character token
is below the threshold, so 78% of these spans get no mention at all. Lowering the
floor to admit them raises coverage to 0.904 and **collapses accuracy to 0.318**.
It emits 5,000 additional mentions across the split and answers `RA` with
**C0002893, refractory anemia, in all 66 occurrences** — in a corpus where `RA`
is room air about 97% of the time.

The mechanism is the tiebreak. Among equally-scoring candidates the matcher
sorts by CUI, and `C0002893` sorts first. Deterministic, and wrong. **Determinism
is necessary, not sufficient** — a reproducibly wrong answer is still wrong, and
this is the measurement behind that principle.

### Baseline 2 — most-frequent sense

The standard floor in word-sense disambiguation: always answer with the sense a
form usually has. Fitted on `train`, reported on `test`.

Before building the anchor rung, we asked how much it could possibly add:

| | |
|---|---:|
| MFS accuracy on free-prose short forms | **0.8992** |
| total headroom | 0.1008 |
| **reachable headroom** | **0.0629** |
| unreachable (UMLS carries no such sense) | 0.0378 |

The split repeats the gate-1 distinction. A form the gold assigns several
concepts to while UMLS offers at most one — `fluid`, `intact`, `stable` — is not
a disambiguation problem. **So anchor voting competes for ~0.86% of the gold**,
and the rung is sized to that rather than to the ambition in the specification.

### Baseline 3 — the shipped structural emitter without expansion

For the expansion table, the relevant comparison is the component it extends.

## Results

Stage 3a and 3b, measured emitter-off versus emitter-on, 68-note test split:

| Category | Gold | Recall | Precision |
|---|---:|---|---|
| `procedure` | 7,851 | 0.3123 → **0.5016** | 0.3252 → **0.4256** |
| `lab_measurement` | 3,640 | 0.1047 → **0.4896** | 0.3040 → **0.6549** |

**+61% and +368% relative, with precision rising in both.** Recall and precision
moving together is unusual and has a cause: the emitter adds spans in a position
where the gold is dense rather than guessing more widely. Structural resolution
rises from 70.3% to **94.0%** of candidates.

Stage 3c, seven forms, 188 held-out occurrences:

| System | Coverage | Accuracy |
|---|---:|---:|
| matcher alone, `mml=2` | 0.904 | 0.318 |
| matcher alone, `mml=3` | 0.223 | 0.738 |
| **anchor vote** | **0.229** | **0.977** |

> **Where the phenotype surface warrant stops and this starts.** Chapter 16 lets
> a phenotype declare surface forms matched literally, which reaches
> abbreviations this stage cannot, because 3c replaces the concept on a span the
> matcher already returned and cannot create one. The two do not overlap, and
> the boundary is ambiguity. A form with one clinical sense — `cdiff`, `t2dm` —
> is declared as an anchor and matched outright. A form with two, resolvable
> only from context, is left to the vote here: the anchor review drops `ra`,
> `cp` and `pe` for exactly that reason, and `ra` is this section's own worked
> example. A literal matcher asked to decide room air against rheumatoid
> arthritis would corrupt the wrong span 97% of the time.
| most-frequent sense | 1.000 | 0.968 |

Against the matcher at equivalent coverage, the anchor vote is **+24 accuracy
points**. Against most-frequent sense it loses on the headline — and the
cross-tabulation is why it ships anyway:

| | count |
|---|---:|
| MFS wrong / **anchor rescued** | **3** |
| MFS wrong / anchor abstained | 2 |
| MFS wrong / anchor also wrong | 1 |
| MFS right / anchor broke it | 2 |
| MFS right / anchor agreed | 39 |
| MFS right / anchor abstained | 141 |

Net +1 on 188, which is noise. But **all three rescues are `RA` → right atrium
inside echocardiogram reports**, and that is not noise — it is a *correlated*
failure. A frequency prior fitted to room-air dominance is wrong on every echo
report; the cues are right on all of them.

**Most-frequent sense is a yardstick, not a shippable alternative.** It encodes
one corpus, and the three published `RA` priors disagree outright — CASI puts
right atrium at 0.788, Stetson room air at 0.859, Vanderbilt at 0.900. Its
confidence is not a usable abstention signal either: raising the Vanderbilt
threshold past τ = 0.80 *reduces* accuracy, and cross-corpus disagreement
concentrates exactly where the source corpus is most confident.

Cues are clinical knowledge, and clinical knowledge transports.

## A correction: the terminology records its own abbreviations

The chapter above says `creatinine` is in UMLS and `creat` is not, and treats
hand authoring as unavoidable. For **laboratory** shorthand that holds. For
**disease and procedure** abbreviations it does not, and the claim as first
written was wrong.

SNOMED's synonym convention is `ABBREV - full term`, so the terminology contains

```
HFrEF - heart failure with reduced ejection fraction    SNOMEDCT_US  SY
COPD - Chronic obstructive pulmonary disease            SNOMEDCT_US  SY
```

as ordinary atoms. Exact matching on `hfref` finds nothing — no atom *is*
`HFrEF` — so a failed lookup was read as absence. It was there, embedded, and
ICD-10-CM carries it too as `Heart failure with reduced ejection fraction
[HFrEF]`.

Splitting on the separator and keeping the monosemous half yields **4,015
abbreviations from 9,994 candidate atoms**, 927 rejected as ambiguous.
`hfref → 703272007` is the same code the gold uses; `htn → 38341003` is this
package's own hypertension phenotype seed. No clinician is asked what `NSTEMI`
means, and no reviewer has to check the answer.

### Monosemy in a terminology is not monosemy in usage

The first gate on the derived inventory found a hazard that generalises, and the
fix for it is the more interesting half.

`PT - Platinum` is the **only** `ABBREV - full term` atom for `PT`, so a monosemy
filter over the synonym set calls it unambiguous — while in clinical prose `pt`
overwhelmingly means *patient*. Unfiltered, the inventory scored 59.2% where it
fired and would have expanded a patient into a metal.

**A terminology's monosemy is a property of its synonym set, not of how
clinicians write.** So the second filter asks a different question: *is the short
form ambiguous as written?* — counting concepts that carry an atom equal to the
surface itself.

| Surface | Concepts as written | Verdict |
|---|---:|---|
| `pt` | 9 | rejected — the anchor vote owns it |
| `ca` | 5 | rejected |
| `ra` | 5 | rejected |
| `copd` | 3 | rejected |
| `hfref` | **0** | kept |
| `rdw` | **0** | kept |

Requiring **zero** rather than few is deliberate and does three things at once.
It excludes every ambiguous form by construction. It excludes forms the matcher
already resolves unaided, which need no entry. And what remains is exactly the
population an expansion table exists for: surfaces the terminology cannot reach
as written, that mean one thing when it can.

| | unfiltered | filtered |
|---|---:|---:|
| entries | 3,999 | **1,626** |
| unreachable gold spans covered | 306 (8.3%) | 209 (5.7%) |
| **of those, code matches gold** | **59.2%** | **80.4%** |

Fewer answers and 21 points more of them right. `pt → Platinum` is excluded *by
construction* rather than by a blocklist, which is what makes the filter
trustworthy on a corpus nobody has inspected.

Two consequences follow, and they divide the labour rather than replacing it:

- **The hand-authored table is not redundant.** `creat`, `angap`, `urean` and
  `rdwsd` are institutional laboratory shorthand absent from every terminology —
  which is precisely why gate 1 found them unreachable. They are underivable.
- **The derived inventory covers what the hand table never did**: disease and
  procedure abbreviations. `rdw` alone accounts for 137 of the 306 covered spans.

The artifact lives under `data/` with a committed manifest, because the short
forms are UMLS strings. Only the manifest ships.

## Entries name concepts, not strings

A second correction, from the same source. The first table mapped shorthand to a
long form and resolved *that* by string lookup, which has a defect by
construction: the long form is a **lookup key**, so a row expanding to a string
the terminology does not carry resolves to nothing and is dropped exactly as if
absent. Coverage in name only, and silent.

**14 of 99 shipped rows were dead that way.** `crp → C reactive protein` fails
where `c-reactive protein` works; `heent → head eyes ears nose and throat` fails
where `head and neck` works. The correct long form is not necessarily the
*expansion* — it is the nearest term the vocabulary contains.

Entries now carry a **SNOMED identifier** as the authoritative half, with the
long form kept as the reviewer's handle and a fallback. 89 of 97 anchor to a
code; the rest are concepts this release maps to none.

The original justification for a strings-only table — that identifiers would make
it a licensed derivative — was also wrong. `phenotypes.yaml` has shipped SNOMED
seed codes since the phenotype layer landed, on exactly the basis that the
licence constrains vocabulary *content* and a code is not content.
`validation/pipeline/scripts/check_expansions.py` reports any row resolving to nothing and exits
non-zero, so a dead row cannot return quietly.

## The stages have to be in the pipeline to count

Worth recording because it invalidated a claim rather than a number. For several
commits `resolve_labels` and the anchor vote were reachable only from evaluation
scripts, while the CLI called `ConceptMatcher.annotate` directly. **Every measured
gain described a configuration nothing in production used**, and the phenotype
layer in particular was built on unaided matcher output while the measurements
quoted a pipeline recovering 60% more procedures.

`concepts/pipeline.py::annotate_document` now composes the stages and is what
both the CLI and the evaluation scripts call. A composition reassembled at each
call site is one that some call site will get wrong, and the one that did was the
one that mattered. **A measurement is only a measurement of the shipped system if
the shipped system runs the same code.**

## What was built and then rejected

Recorded because a method chapter that lists only what worked is not a method
chapter.

**The `HEENT:` slot.** 793 gold spans, 71.9% unreachable, the largest structural
position with no handler. Built, and measured in isolation: **+0.0058 `procedure`
recall against −0.0117 `anatomy` and −0.0098 `disease` precision.** It was parked
with a stated prediction that the expansion table would rescue it. **The
prediction was tested and refuted** — with expansion on, the trade is unchanged.
Expanding `heent` does resolve it, to a body-system concept the annotators do not
mark in that position, so the emission is a false positive rather than a
recovery. It ships off, now for a measured reason.

**Schwartz–Hearst local definition detection.** scispaCy's `AbbreviationDetector`
finds in-text definitions such as `shortness of breath (SOB)`. Measured: **17 of
19,965 misses, 0.085%**, thirteen of them in a single echocardiogram report.
Discharge summaries rarely define their own shorthand. Kept as a published
negative result rather than as a pipeline stage.

**Lowering `min_match_length` to 2 as a standalone change.** See baseline 1: it
quadruples coverage and cuts accuracy by more than half.

## Defining "abbreviation" took three attempts

Every number in this chapter rests on a definition of the population, and the
first two were wrong in the direction that flatters the result. The sequence is
worth recording because the failure mode repeats.

**Mechanical** — any token of 2–6 alphabetic characters. Counts `clear`, `left`
and `small`. Gate 1 used this deliberately and reported the inflation rather
than removing it, so that the 44.9% headline carried its own caveat.

**Subtract the general-English list** — better, and still wrong by 71%. That
list *deliberately removes* the 2,686 words carrying a high-precision clinical
type, so `resolve_tags` can let the terminology speak for them. Correct for that
question; wrong for this one, because `stable`, `mild`, `wound` and `fever` are
absent from it and were each counted as abbreviations. The corpus count read
169,166 against a true 41,571.

The fix was recognising that **two different questions need two different
lists**, generated in one pass so they cannot drift: one answers *should the
terminology speak for this word*, the other *would a reader recognise it*.

**And the unfiltered list over-excludes.** `ra` is in it — Ra, the Egyptian god,
clears Zipf 3.0 — so the word list alone loses `RA`, along with `PO`, `MS`, `PE`,
`DM` and `BS`. **No frequency threshold separates these**: `ms` sits at Zipf 4.67
and `mild` at 4.11, so any cut that keeps the abbreviation admits the adjective.

The signal that works is orthographic, and bounded:

| Rule | Admits | Rejects |
|---|---|---|
| not in the English vocabulary | `hgb`, `creat`, `angap` | — |
| mixed case — a capital the author chose to put inside | `HFrEF`, `AnGap` | `Stable`, `BLOOD` |
| all capitals **and at most 3 characters** | `RA`, `PO`, `MS` | `BLOOD`, `STABLE` |

The length bound on the third rule is load-bearing: `BLOOD` is all-capitals in
every MIMIC lab line and alone contributed 1,813 spurious ambiguous tokens
before it was added.

The general lesson is the one the stage gates keep producing in a different
guise: **a definition that admits too much is not conservative, it is wrong**,
and it is wrong in the direction nobody checks.

## Limits

**The abbreviation population is defined orthographically, and all-capitals
prose is its residual cost.** A shouted three-letter heading is counted. Bounded,
and stated rather than discovered.

**The `HEENT:` slot is built and off.** Its value is gated behind evidence about
how the gold treats exam-subsection labels, not behind more vocabulary — the
prediction that the expansion table would rescue it was tested and refuted.

**The derived SNOMED inventory is built and not wired.** It needs the same slot
discipline the hand table has, and `pt → Platinum` is what happens without it.

**The expansion table is authored, and its provenance constrains it.** The
entries were written from standard orderable panels and physical-examination
systems, not transcribed from a corpus frequency ranking — the PhysioNet DUA
binds the *surfaces*, so a ranked list of MIMIC's most frequent abbreviations
would be a MIMIC derivative and could not ship. The corpus is used only to report
coverage. The table ships `reviewed: false` until a clinician has read every row,
and the package reports that flag next to any result it contributed to.

**Institutional shorthand is institutional.** `angap`, `urean` and `rdwsd` are
BIDMC conventions. The table is a reviewed default, replaceable via
`--expansions`, and `robustehr applicability` reports its coverage on any new
corpus.

**The stage-3c accuracy comparison rests on 43 answered cases.** The robust
finding is the coverage gap, not the third decimal.

**A cue must be discriminative, not merely associated.** `pe` was the one form
where the cues lost, and both errors were the same mistake — `exam` and
`examination` firing *physical examination* on a radiology order header and on
prose discussing an embolism. Those words co-occur with everything in a clinical
note. Removing the sense took `pe` to 3 of 3 and the rung from 0.933 to 0.977,
and the rule it yields is the useful output: a cue should be a word that would be
*surprising* under the competing reading.

**This corpus has little abbreviation ambiguity to resolve.** `RA` is 97.2% one
sense here; `cva`, `dm`, `sob` and `bs` are effectively monosemous. **The value
of a disambiguation rung is a property of the corpus as much as of the method** —
which is precisely why the published priors disagree, each corpus being skewed
differently. That is an argument for keeping the abstention accounting, which
makes the difference visible on any new corpus, rather than for tuning cues to
this one.
