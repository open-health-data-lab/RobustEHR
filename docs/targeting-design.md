# Targeting: set membership, on two warrants

The question this settles: **for phenotype-based corruption, what does a target
have to be able to do?**

Not general concept linking, which is harder than necessary and measurably weak,
and not category typing, which is too coarse. A phenotype target answers a
narrower question — *is this span evidence for this phenotype?* — and it answers
it on two warrants: membership of a declared concept set, or a declared surface
form matched literally. The first is set membership rather than linking, which is
what makes the layer tractable; the second reaches what no concept set can.

## Two kinds of corruption, two different requirements

| Corruption | Example | What it needs |
|---|---|---|
| **phenotype-agnostic** | "corrupt all medications" | a span's **semantic type** |
| **phenotype-based** | "corrupt evidence for hypertension" | whether a span is **evidence for the phenotype**: its concept is in the declared set, or its text is a declared form of the diagnosis |

The first is solved and measured: category targeting via semantic types, with
mean recall 0.606 against medspaCy's 0.490 and scispaCy's 0.398.

The second is what remains, and the design question is what it actually requires.

## Linking and set membership are different problems

This distinction is the whole argument, and it is easy to miss because both are
called "concept recognition".

**Linking**: given a span, choose the single best concept from ~3.1 million.
**Set membership**: given a span, decide whether it matches any member of a
curated set of a few hundred strings.

They differ in difficulty by orders of magnitude, and our own numbers show it.

Measured on 12 test notes, 6,841 predictions:

| Outcome | Share |
|---|---|
| lands on a gold span **and** names the right concept | 14.9% |
| lands on a gold span, **wrong** concept | 30.5% |
| lands on no gold span | 54.6% |

**Of the predictions that found the right text, 67% named the wrong concept.**
That is the entire span-to-concept collapse — 0.4406 span IoU down to 0.1733
under the configuration this analysis ran on, 0.4312 down to 0.1750 under the
shipped one — and it is a *disambiguation* failure, not a detection failure. With three million
candidates sharing surface forms, choosing among them without training data is
the hard part.

Set membership never asks that question. Matching `lisinopril` against a
400-term hypertension evidence list does not require deciding which of the 14
UMLS concepts containing "lisinopril" is meant — it requires deciding whether the
span is in the list. Ambiguity inside a curated list is bounded and reviewable;
ambiguity across the terminology is not.

## What the concept errors actually are

Terminology first, because the question turns on it: **"concept" means the exact
CUI** (or SNOMED identifier). "Wrong concept" means we assigned a different
identifier than the gold annotation, not that we found the wrong text.

Classified over 1,419 wrong-concept cases on 8 test notes, under the
configuration scoring 0.4406 span / 0.1733 concept. What this establishes is the
*proportions*, which is what the corrections below were designed against:

| Class | Share | Example |
|---|---|---|
| our span is a **fragment** of the gold span | **52%** | gold `vitamin D deficiency`; we matched `vit D` → *vitamin D*, and `deficiency` → *Malnutrition* |
| **same span, different concept** | 40% | `CKD` → we say *Chronic Kidney Diseases*, gold says *Chronic kidney disease stage 3* |
| our span is wider than gold | 6% | |
| partial overlap | 3% | |

**53% still carry the correct category** despite the wrong concept — which is
precisely why category recall (0.606) is three and a half times the concept score
(0.175).

Within the 40% "same span" class the errors are of two very different kinds:

**Granularity** — the same clinical entity at different specificity.
`diverticulosis` → *Diverticulosis* against gold's *Diverticulosis of large
intestine*; `cancer` → *Malignant Neoplasms* against *Malignant tumor of colon*;
`knee arthroscopy` → *Diagnostic arthroscopy of knee* against *Arthroscopy of
knee*. The gold annotator used surrounding context to pick the specific concept;
we matched the string in isolation.

**Genuine sense errors** — a different entity entirely. `NAD` → *nicotinamide
adenine dinucleotide* where the note means **no abnormality detected**. `III` →
*external pyramidal layer* where it is the stage in *CKD stage 3*. `HEENT` →
*HEENT* where gold says *Physical examination*.

None of these are crosswalk artifacts: **0 of 1,419 shared the same UMLS CUI as
gold**, so they are real disagreements rather than SNOMED-vs-UMLS bookkeeping.

## Does linking the phenotype to CUIs rescue this?

Partly, and the part that does not is the dangerous one.

**Granularity errors are absorbed.** A phenotype concept set is built by
expanding seeds through UMLS synonymy and the hierarchy, so a CKD phenotype
contains *Chronic Kidney Diseases* **and** *CKD stage 3*. Assigning the general
concept where gold chose the specific one still lands inside the set. This is the
larger part of the "same span" class and it costs nothing.

**Fragmentation is not absorbed, and it fails silently.** Gold marks
`vitamin D deficiency`; we emit `vit D` → *vitamin D*. A vitamin-D-deficiency
phenotype set contains the deficiency concept, not the vitamin, so the mention is
**missed**.

**Sense errors are not absorbed either, and they fail loudly.** If any phenotype
set contains nicotinamide adenine dinucleotide, every `NAD` in a physical exam —
meaning *no abnormality detected* — becomes a corruption target.

### Why the miss is worse than the false positive

A false positive corrupts something it should not have and the dose record shows
an edit that landed where the user asked. Wrong, but visible.

A miss under `phenotype_scope=protect` is worse. Protect mode adds the
phenotype's evidence spans to the protection registry and then asserts
`evidence_touch == 0`. If a mention was never found, it was never protected, an
operator corrupts it, and the run **still reports evidence_touch = 0** — because
the measurement and the protection share the same faulty span set. The guarantee
does not fail; it silently becomes vacuous.

That is the strongest argument in this document for set membership over linking.
Exact multi-word matching against a declared list matches `vitamin D deficiency`
**as a unit**, which removes the 52% fragmentation class outright, and a curated
clinical list would never contain nicotinamide adenine dinucleotide as
hypertension evidence, which removes the sense-error class.

It also means the phenotype layer owes one specific validation that general
matching does not: **protect-mode completeness**. Asserting `evidence_touch == 0`
is not sufficient, because a vacuous zero looks identical to a real one. The
target's recall has to be established independently — by clinician review and
concept-set overlap against published definitions — and reported next to any
protect-mode result.

## Why categories alone are not enough

Tempting, since category targeting already works. It fails because categories are
the wrong granularity for a phenotype.

`Categories("disease")` selects every disease mention in the note — pneumonia,
diabetes, hypertension alike. A hypertension experiment that corrupts all three
is not a hypertension experiment. And phenotype evidence spans *several*
categories at once: hypertension is evidenced by a diagnosis (`disease`), by
antihypertensives (`medication`), and by blood-pressure values (numeric, no
category at all). No category expression captures that set, and no combination of
categories excludes the other diseases.

So category → phenotype association cannot be derived from categories. The
association has to be **declared**, which is what a concept set is.

## The design: two warrants over declared resources

A **phenotype target** is a rule that, given a note, returns the spans that are
evidence for one phenotype. It admits a span on either of two warrants:

```
evidence(s, P)  ⟺  cui(s) ∈ C_P   ∨   text(s) ∈ S_P
                   concept warrant     surface warrant
```

`C_P` is the phenotype's **concept set**: a SNOMED seed expanded through the
`isa` hierarchy and `MTH RN` to a bounded depth; medications through MED-RT
`may_treat` / `may_prevent`, with RxNorm identity variants; terms a language
model proposes per facet, grounded to CUIs by lookup against the local release;
and a one-hop evidence closure. Every generated candidate is gated by a frozen
vetting verdict (`phenotype_vetting.yaml`), and a closure candidate with no
verdict is not admitted.

`S_P` is the phenotype's **surface set** (`phenotype_anchors.yaml`): the ways the
diagnosis is written, reviewed with a recall bias; the proposed terms that no
vocabulary string matched, carried at tier `associated`; and the **stop
surfaces** — strings that are legitimate vocabulary entries for an in-set concept
and ordinary language in the note (`status`, `secondary`) — which are refused on
either warrant, together with a general-English floor for single-token surfaces
no phenotype anchors.

The concept warrant runs over the matcher's mentions and never asks which of 3.1
million concepts a span is; it asks whether the CUI the matcher assigned is in a
set of a few hundred to a few thousand. The surface warrant runs over the note
text and consults no terminology at all, which is why it reaches the causative
organism (*C. difficile* is a Bacterium, with no `isa` path to the infection),
the qualifier (*preserved* and *reduced* carry the whole HFpEF/HFrEF
distinction, and no walk over a disorder hierarchy returns a qualifier), and the
abbreviation the matcher produced no candidate for (`t2dm`, `cdiff`). Where both
warrants cover the same characters the concept wins, so one piece of evidence is
counted once.

Every admitted span records the warrant and **tier** that admitted it —
`anchor`, `disorder`, `medication`, `finding`, `proposed`, `closure`,
`associated` — and tiers are reported, never selected on: a `pheno=X` target
admits every tier, and what the tier buys is that reach becomes divisible, so a
result can say what share of the phenotype's *diagnosis* a perturbation reached
rather than only what share of its declared evidence.

The evidence spans then serve three run-level roles: **protect** withholds them
from every operator, **target** restricts every operator to them, and
**measure** reports evidence-touch per operator. A run that targets a phenotype
records, in its manifest's `targeting` block, the digest of every resource the
target was built from (present or `absent`), a digest over the strings the
anchor resource admits and refuses, the review state of the anchors and the
vetting (`llm`, `llm+hand` or `llm+clinician`), and the digests of the locally
built terminology inputs. Two corpora built under different targets are
distinguishable from their artifacts alone.

The path deliberately **does not run through general linking**. A target only
has to recognise its own evidence.

## What this means for the concept score

It does not bound the phenotype layer, because the phenotype layer does not do
that task. The number bounds a capability the layer does not use: *given an
arbitrary span, name which of 3.1 million concepts it is.*

That is worth stating precisely rather than as a let-off. Three claims, three
different pieces of evidence:

| Claim | Evidence | Status |
|---|---|---|
| we type spans by category as well as or better than peers | SNOMED gold, 3 systems | **measured** — 0.606 vs 0.490 vs 0.398 |
| we link arbitrary spans to concepts | SNOMED gold, challenge metric | **measured, weak** — 0.175 |
| we find a declared phenotype's evidence | SNOMED gold, 8 phenotypes | **measured** — set recall 0.698 |

The third is the one the phenotype layer rests on, and it has its own
validation rather than inheriting either of the others: every stage beneath it
is built or deliberately empty, and re-running reproduces every phenotype to four
decimal places. `heart_failure` at 0.449 on the concept warrant is a real gap and
a stage-3 one only in appearance: that stage expands *slot-scoped* short forms — a
label before a value, or before a colon — and `HFrEF` in these notes is running
prose. Prose abbreviations are what the surface warrant is for. See
`validation/protocol.md` §0 for the ladder and what each rung of "validated"
means.

## Measuring the third claim

The obvious objection to a declared concept set is that it is *declared*, so how
would anyone know it finds anything? The answer is in data already on disk.

The challenge annotates a **concept identifier** per span. Declare a phenotype as
a seed concept plus its `isa` descendants, and the gold spans whose concept falls
in that closure are that phenotype's evidence **as an expert marked it**. That
gives a real phenotype, on real notes, scored against expert annotation, with
nobody annotating a phenotype corpus.

Two recalls, and keeping them apart is the point:

* **span recall** — did we find the text? What an operator needs to reach the token.
* **set recall** — did we find it *and* assign a concept inside the set? What
  `phenotype_scope` needs to be correct.

Measured over the 68-note test split, `validation/phenotype/scripts/phenotype_eval.py`:

| Phenotype | gold spans | span recall | set recall |
|---|---:|---:|---:|
| hypertension | 197 | 0.995 | 0.817 |
| chest pain | 210 | 0.890 | 0.614 |
| dyspnea | 187 | 0.984 | 0.914 |
| fever | 137 | 0.978 | 0.774 |
| diabetes mellitus | 121 | 0.686 | 0.397 |
| chronic kidney disease | 45 | 1.000 | 0.889 |
| heart failure | 49 | 0.857 | 0.449 |
| atrial fibrillation | 52 | 0.904 | 0.731 |
| **macro** | **998** | **0.912** | **0.698** |

**Set recall is 4.0× the general linking score of 0.175 on the same corpus.**
That is the argument of this document turned into a number: the phenotype layer
does not inherit the linking result because it does not do the linking task, and
the gap between 0.698 and 0.173 is how much easier bounded membership is than
open-vocabulary disambiguation.

The worst row is worth reading rather than averaging away. **Heart failure at
0.449** is almost entirely `HFrEF` and `CHFrEF`, which produce no match at all —
the abbreviation gap, priced. It is not fixed by better linking; it is fixed by
the abbreviation resolver, and until then it is a bound on this number rather
than something smoothed out of it.

### Set recall is never reported alone

Recall of a declared set rises monotonically with the size of the set, so
"expand harder" always appears to win. Any expansion strategy therefore has to
be paired with a specificity check, and one is available without new annotation:
these eight phenotypes are clinically distinct, so a gold span claimed as
evidence by **two** of them is one of them being wrong.

| expansion | mean set size | gold evidence claimed | cross-phenotype contamination |
|---|---:|---:|---:|
| SNOMED `isa` only | 118 | 934 | 0 |
| **SNOMED `isa` + `MTH` `RN`** | **202** | **998** | **0** |
| union of all sources' `isa` | 434 | 994 | **28** |

The union of every source vocabulary is the intuitive way to get "the whole UMLS
hierarchy", and it is the wrong one. It triples the closure, claims *fewer* true
evidence spans than the Metathesaurus-native layer, and conflates hypertension
with heart failure across 28 gold spans. Bigger closure, worse phenotype.

### Failures present as empty results

In this subsystem a wrong extraction is rarely an error: reading the `isa`
relation backwards yields an ancestor closure that is non-empty, correctly typed
and full of related concepts; taking one of the several CUIs a SNOMED code
carries can collapse a phenotype to a childless concept that matches no gold
span, which reads as "no evidence exists" rather than as a lookup failure. Both
are pinned by tests (`tests/test_hierarchy.py`, `tests/test_phenotype_links.py`),
and the general rule is the one `protect` mode already illustrates: anything
that can return nothing needs a positive control.

## What a CUI is, exactly — and what the hierarchy does with it

Worth settling precisely, because the whole absorption argument turns on it.

A **CUI** is a UMLS Concept Unique Identifier: one identifier per *meaning*,
gathering every string from every source vocabulary that expresses it. It is not
one identifier per word and not one per source code.

Granularity is where the intuition usually breaks. `Diverticulosis` and
`Diverticulosis of large intestine` are **different meanings**, so they are
different CUIs — verified against the local 2026AA release:

```
'Diverticulosis'                    -> C1510475
'Diverticulosis of large intestine' -> C4518471
'Chronic kidney disease'            -> C1561643
'Chronic kidney disease stage 3'    -> C2316787
```

They are not synonyms and UMLS will never merge them. What connects them is a
**relation**, and that relation is what a phenotype set is built on:

```
C1510475 --isa--> C4518471     rel=CHD  sab=SNOMEDCT_US
C1561643 --isa--> C2316787     rel=CHD  sab=SNOMEDCT_US
```

So a CKD phenotype seeded at `C1561643` contains `C2316787` by descent, and
matching the general concept where the annotator chose the specific one lands
inside the set anyway. That claim is now checked rather than asserted.

The corollary is a real limit: **closure can only absorb concepts that
participate in the hierarchy** — and one of the most common errors involves a
concept that participates in none of them.

Gold marks `diabetes` as *Diabetes Mellitus* (C0011849). We returned C0011847,
*Diabetes*, which carries **no SNOMED code at all** and appears nowhere in the
SNOMED `isa` graph. Worse, it appears nowhere in *any* source vocabulary's `isa`
graph: its only hierarchical edges in the entire release come from `PSY`.
Expanding to the union of all sources does not reach it.

What does reach it is the layer that is easy to overlook, because UMLS is usually
described as an integration of other people's hierarchies. It has one of its
own. `SAB='MTH'` marks relations the Metathesaurus **asserts itself** rather than
inherits, and among its 453,230 broader/narrower edges is exactly the one needed:

```
C0011847  --RN-->  C0011849        sab=MTH
Diabetes           Diabetes Mellitus
```

So the phenotype closure runs over **`SNOMEDCT_US` `isa` ∪ `MTH` `RN`**. The
clinical hierarchy supplies editorial coherence; the Metathesaurus layer supplies
reach into concepts no source vocabulary places in a tree.

Its contribution is worth stating precisely, because the headline metric
understates it. Holding the matcher fixed at `length + trim`:

| closure | gold evidence identified | set recall |
|---|---:|---:|
| SNOMED `isa` | 934 | 0.671 |
| + `MTH` `RN` | **998** | 0.678 |
| + `MTH` `RN`, ties broken toward SNOMED | 998 | **0.698** |

`MTH` barely moves recall and that is not the point: it moves the **denominator**,
identifying 64 gold spans as phenotype evidence that the SNOMED hierarchy alone
never claimed. A more complete definition of what the phenotype *is* matters more
here than a better score against a narrower one — under `protect`, evidence that
was never in the set is evidence that was never protected.

The tie-break is what converts the new reach into recall, and diabetes is where
both show up: 0.217 under SNOMED alone, 0.231 once `MTH` connects C0011847, and
0.397 once ties stop being broken alphabetically.

## The right approach to correct the concept errors

Three error classes, three different corrections, each measured rather than
argued. None of them is "link better".

### Fragmentation (52%) — prefer the longest match, then repair the span

`shortness of breath` matched only `breath`, so a dyspnea phenotype missed it
entirely. QuickUMLS's `overlapping_criteria='length'` fixes the fragmentation but
introduces two new faults, and both needed handling before it was a net gain:

| Fault | Example | Correction |
|---|---|---|
| the span runs one word too far | `and vitamin D deficiency` | trim leading/trailing **function words** — no UMLS concept begins or ends with a conjunction |
| a longer *approximate* match displaces a shorter *exact* one | `her chest pain` → C0029537 at 0.857, discarding `chest pain` → C0008031 at 1.000 | **re-match the trimmed span**, and accept the replacement only on strictly higher similarity |

The second is the subtle one. Trimming alone fixes the span but leaves the wrong
concept attached, and the concept was what went wrong. Re-querying the trimmed
text recovers the exact match that the wider window had hidden; the
strictly-higher-similarity condition means the step can raise match quality and
never lower it.

The three together are `overlapping_criteria='length', trim_affixes=True`:

```
score       : 'chest pain'->C0008031   'breath'->C0225386          'vitamin D deficiency'->C0042870
length      : 'her chest pain'->C0029537  (shortness of breath lost)  'and vitamin D deficiency'
length+trim : 'chest pain'->C0008031   'shortness of breath'->C0013404  'vitamin D deficiency'->C0042870
```

### Granularity, where closure cannot reach (part of the 40%) — break ties toward the vocabulary in play

Gold marks `diabetes` as *Diabetes Mellitus* (C0011849); we returned C0011847,
*Diabetes*. Both are exact string matches at similarity 1.000, so the choice
between them was decided by our tie-break — which was alphabetical order.

Replacing an arbitrary rule with an informed one is free, and the informed rule
follows from the design: a concept with no SNOMED code cannot be a member of a
SNOMED-seeded phenotype set under any closure. `preferred_cuis` therefore breaks
**ties only** — it can never promote a worse match over a better one, which is
what keeps it from being gold-fitting.

### Sense errors (the rest of the 40%) — abstain, do not resolve

`NAD` as *nicotinamide adenine dinucleotide* where the note means *no
abnormality detected*. This class is not a ranking problem and no tie-break
touches it. It belongs to the abbreviation resolver, whose design commitment is
**abstention over accuracy**: the accuracy–coverage curve is the reported figure,
because a resolver that abstains on `RA` is more useful here than one that
guesses right 74% of the time.

The `heart_failure` row prices the gap in the meantime — `HFrEF` and `CHFrEF`
produce no match at all, and that is most of its 0.449.

## Does the phenotype layer need an assertion layer?

The intuitive answer is obviously yes — "no evidence of pneumonia" is not
evidence of pneumonia. The intuitive answer is also wrong about *where* it
matters, and getting that right changes what gets built.

**Not for eligibility.** Under `protect`, every mention of the phenotype is
withheld from every operator, and a negated mention is still a mention whose
corruption changes what the note says; protecting it is correct. Under `target`,
a negated mention is still phenotype-related text, and corrupting it is still a
phenotype-targeted corruption. Neither mode's eligibility decision changes with
assertion status.

**Yes for reporting**, and the quantity settles it. Running medspaCy ConText over
the gold evidence spans (`validation/phenotype/scripts/phenotype_assertion.py`):

| | spans | share |
|---|---:|---:|
| affirmed | 653 | 69.9% |
| negated | 166 | 17.8% |
| historical | 65 | 7.0% |
| hypothetical | 32 | 3.4% |
| family | 20 | 2.1% |
| uncertain | 17 | 1.8% |
| **non-affirmed** | 281 | **30.1%** |

68 notes, 934 evidence spans. Attributes co-occur, so the rows sum to more than
the non-affirmed count.

**30.1% of expert-annotated phenotype evidence is not an affirmed statement
about the patient now**, and `fever` is the extreme at 46.0% — `denies fever` in
review of systems. An `evidence_touch` table that collapses those into one count
reports something much less useful than it appears to.

On the same 934 spans, PyRuSH boundaries give 34.7% against 30.1% on the
package's own, so about 4.6 points of the PyRuSH figure is cue leakage across
list and header boundaries rather than clinical fact — most of it `historical`.
`comparison_pyrush_boundaries` in the artifact isolates it.

So ConText gets wired, as an **attribute carried alongside each evidence span**
rather than a filter in front of it. `evidence_touch` becomes a breakdown by
assertion, and the corruption of negated evidence stops being indistinguishable
from the corruption of asserted evidence.

The dependency also has to be honest about a result this package already
measured: `probe_deid_assertion.py` shows ConText's verdict flipping under a
provably reference-preserving de-identification restyle, on the MIMIC-III and
MIMIC-IV conventions specifically. That is why stage 8 is fed **our** sentence
boundaries rather than PyRuSH's — measured in `assertion_deid_invariance.json`,
where ours scores 1.0000 accuracy at 0.0000 instability across seven
de-identification conventions against PyRuSH's 0.6071 at 0.2500. Results are
conditioned on **formatting condition**, of which the de-identification scheme is
one part and, at corpus scale, a small one.

### Aiming *at* the cue: the `governs(...)` atom

Everything above is about assertion as an attribute of evidence. The inverse
question — corrupt the cue that *decides* a phenotype's reading — needed a target
the grammar did not have, and its absence was silent rather than loud.

`PhenotypeEvidence` tests the unit's own span. For a SEMANTIC operator the unit
is the cue, and the `denies` in `denies hypertension` is not itself evidence for
hypertension, so `--phenotype-scope target` with any `semantic.*` operator
rejected every cue and reported `eligible_n = 0` on a note full of them. The run
completed and the corpus came out identical to the baseline.

`governs(a)` admits a span lying inside a cue whose ConText scope covers a span
that `a` admits:

```bash
robustehr run --operators semantic.negation_flip \
  --target 'governs(pheno=hypertension)'
```

This is a lookup, not a proximity window — ConText already records which cues
produced each span's attributes, so nothing here has to pick a character
distance. It composes like any other target, so
`all(lex=word;governs(pheno=hypertension))` means "typo the word that negates
hypertension", which is a different and runnable experiment.

Because a `governs(...)` target with no assertion index would admit nothing —
the same silent zero — the runner **raises** rather than running when one is
missing. A configuration error must not present as a finding.

## How the phenotype layer gets validated

Set membership is easier to *do* than linking, and also easier to *validate*,
because the failure modes decompose:

1. **Is the target complete?** Set recall and span recall against the
   challenge gold (`phenotype_eval.json`); the gap audit against an
   independently written term list, by warrant (`phenotype_gap_audit.json`);
   and clinician review of the built sets and anchors, recorded per concept
   and in the resources' `vetted_by` state. Recall of a curated set is a
   review problem, not a modelling problem.
2. **Does matching find the declared evidence?** Concept matching is
   validated per stage (`validation/protocol.md` §0); surface matching is
   exact, case-insensitive and word-bounded, and is tested without any
   terminology (`tests/test_phenotype_anchors.py`).
3. **Are the assertions right?** ShARe/CLEF 2014 supplies gold contextual
   attributes — negation, experiencer, temporality — over disorder spans. This
   is the piece most likely to be wrong and it has a public benchmark.
4. **Is the evidence-touch measurement sound?** Falsifiable directly: run any
   operator under `phenotype_scope=protect` and assert evidence-touch is zero.

None of those requires solving general entity linking, and each has either a
public benchmark or a machine-checkable invariant.

## Honest limits

**A curated list is not free of ambiguity.** `RA` is room air as often as
rheumatoid arthritis. An anchor is dropped only where it carries an established
different clinical meaning a reader could plausibly intend, never for being
partial or informal, and the stop surfaces refuse strings whose vocabulary
sense is not the note's — the abstention discipline used elsewhere in this
package, and the reason `RA` is the project's standing example.

**Reach is bounded by what the resources declare.** Measured against an
independently written term list, what stays unreachable clusters: phenotype
assignments carried by a value and a unit (`lvef 25%`, `bmi 35`), laboratory
assertions (`anti-ccp positive`), and compositional phrases. That is a property
of representing a phenotype as concepts and surfaces at all, and a phenotype's
reported evidence-touch is conditional on the target that produced it — which is
why the manifest names the target and every result reports reach by tier.

**This raises the cost of adding a phenotype.** Declaring and reviewing a
concept set is real work, where general linking would have been free. That is a
genuine tradeoff, accepted because the free option measures 0.175.
