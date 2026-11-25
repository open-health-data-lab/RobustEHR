> **Development record.** This document was written while the component it
> describes was being built and reads as a history. The method as it stands is
> in [`validation/methodology/`](../../methodology/); nothing here is cited by the
> manuscript. Kept so every decision can be audited.

# Context qualification: stability, correctness, and the difference between them

Stage 8 asks a question the preceding stages deliberately do not: *given that
this span mentions pneumonia, is the note saying the patient has it?* It matters
here because **30.1% of expert-annotated phenotype evidence carries an assertion
modifier** — it is not a plain statement that the patient has this thing, now —
so an `evidence_touch` count that collapses `denies chest pain` into `severe
chest pain` reports something much less useful than it appears to.

Throughout this chapter a span is **modified** when it carries at least one of
the four dimensions and **unmodified** otherwise; *unmodified* is what ConText
and this codebase call `affirmed`. The term is *modifier* rather than
*non-affirmed* because the latter is false for two of the four — `historical`
and `family` both affirm the concept and merely relocate it, in time and in
person respectively. Some older artifacts still key this quantity as
`non_affirmed`; it is the same measurement.

The instrument is medspaCy's ConText — an implementation of Chapman's algorithm,
published and evaluated. The rule applied to QuickUMLS applies here: cite an
evaluated component and measure only the delta, rather than write a rule set and
owe a validation.

This chapter records how that component was validated, and one methodological
point that generalises past this stage.

> Where this stage sits in the run — corpus, baseline, structure, concepts,
> assertion, dose, injection, artifact, replay — is drawn in
> [`docs/pipeline.md`](../../docs/pipeline.md). Stage 8's output is the SEMANTIC
> channel's **dose denominator**, which is why its own error rate has to be
> reported beside every dose it denominates.

## The point that generalises: a stable component can be a wrong one

Stage 8 was first gated on **invariance**. Five operators carry the contract
`INVARIANT_BY_CONSTRUCTION`: each declares a canonicalizer κ, and CI proves
`κ(apply(d)) == κ(d)` over the corpus at every severity, so no clinical
reference can change under them. If an assertion flips under one, the assertion
layer is reading something that is not clinical content, and every result
conditioned on assertion inherits that as a confound. The measured flip rate is
**0.0039** on the shipped configuration (0.0033 on medspaCy's own segmenter — the
two differ in composition far more than in total, and the decomposition is below).

That is a real result, and it is not a validation. **A contextualizer that
marked every span affirmed would score a perfect 0.0000 on this gate** while
being wrong on every negation in the corpus. Invariance is a property of an
instrument's *response to noise*; it says nothing about the signal. A component
needs both measurements, and the stability gate was the one that happened to be
cheap because the package already owned the perturbation operators.

Stated generally: *for any component gated on robustness, ask what score a
trivially wrong version would get.* Where the answer is "a perfect one", the
gate is not a validation and a second instrument is owed.

## The correctness benchmark

**Gold.** Chapman's NegEx test set — 2,376 concept-level assertions over
discharge summaries, of which 2,365 locate cleanly. Each row is a concept
*within* a sentence, which is exactly the shape this stage consumes: spans
supplied from outside, so the measurement isolates assertion from detection.
20.8% are negated. It is also the gold this algorithm family was developed
against, so a number on it is comparable to the literature rather than only to
ourselves.

**The floor is high, and that decides the metric.** Always-affirmed scores
**0.7924 accuracy** while getting every negation wrong. Accuracy cannot separate
a working contextualizer from a broken one here, so **negated-class F1 is the
headline** and accuracy is reported only beside it.

### What is a baseline here, and what is not

Worth stating before the table, because the stage-8 ladder originally listed
"medspaCy ConText" as the *baseline compared against* for a stage whose instrument
**is** medspaCy ConText. You cannot baseline a component against itself, and the
row was incoherent.

The correct decomposition:

| Arm | What it is |
|---|---|
| majority class, cue window | **floors** — what you get for free, and what a naive method gets |
| dependency parse | an **alternative algorithmic family** — no cue list at all |
| negspaCy | an **independent implementation** of the same published algorithm |
| ConText + PyRuSH vs ConText + our boundaries | an **internal ablation** — one engine, two inputs |

medspaCy ConText is the **instrument this package ships**, under the reuse rule:
cite an evaluated component, do not reimplement it, and measure only what you
change. What we change is its *input* — the sentence boundaries it scopes cues
to — so the CTX pair is an ablation of our own modification, not a comparison
against a rival tool. The genuinely external comparisons are negspaCy and the
parser.

Six arms, ordered from free to shipped:

| Arm | accuracy | precision | recall | **F1** |
|---|---:|---:|---:|---:|
| negspaCy — independent NegEx implementation | 0.9742 | 0.9283 | 0.9491 | **0.9386** |
| **medspaCy ConText, our boundaries (shipped)** | 0.9696 | 0.9021 | 0.9572 | **0.9289** |
| medspaCy ConText, PyRuSH boundaries | 0.9696 | 0.9021 | 0.9572 | 0.9289 |
| dependency parse | 0.9277 | 0.9211 | 0.7128 | 0.8037 |
| cue window, ±8 tokens | 0.7252 | 0.4269 | 0.9450 | 0.5881 |
| majority class — always affirmed | 0.7924 | 0.0000 | 0.0000 | 0.0000 |

Three things in this table are worth more than the ranking.

**Spotting a cue is easy; scoping it is the whole problem.** The window arm
reaches 0.945 recall at 0.427 precision. Nearly every negation has a cue nearby;
what a flat window cannot do is decide how far that cue reaches. The gap from
0.588 to 0.929 is what cue-scope resolution buys, and it is almost entirely
precision.

**The dependency arm inverts that profile, and the reason is linguistic.**
0.921 precision at 0.713 recall. English parses *"No pericardial effusion"* as a
**determiner** and reserves the `neg` relation for *"not"*, which is rare in
clinical prose; and *"denies fever"* carries its negation in the lexical verb,
where no parse relation marks it at all. A textbook `neg`-only detector scores
**0.0000** on this gold. The arm reported here is deliberately the strongest fair
version — it also accepts a negating determiner anywhere on the mention's head
chain — because reporting the 0.0000 would have been a straw man. What remains
unreachable is the lexical case, and that gap is the empirical reason this field
built cue-based systems instead of using parsers.

**The independent implementation is the arm that makes the reuse argument
checkable.** negspaCy is a separate codebase implementing the same published
algorithm. Its landing within a point of medspaCy is evidence about *Chapman's
method*; a divergence would have been evidence about *one implementation*. No
configuration of our own component could have distinguished those.

### negspaCy scores higher, and is still not what ships

It wins by roughly one F1 point and matches the shipped arm on invariance. The
benchmark is nonetheless structurally unable to show the reason it is not the
component to use: **negspaCy detects negation and nothing else.** ConText
returns four dimensions, and the package needs temporality and experiencer for
phenotype reporting — negation is 17.8 of the 30.1 modified points, so
choosing the single-dimension winner discards the other 12.3 — and needs cue and
scope spans to give the SEMANTIC operator channel a dose denominator.

The trade is four dimensions and an operator channel against one F1 point on one
dimension. The number is reported rather than buried, because it is the honest
cost of that choice and because a future version needing only negation should
know which component to reach for.

## Segmentation: a promise that was documented, contradicted in code, and never measured

Four documents, the CTX-B ablation rung and the L4 evaluation rung all state
that ConText must be fed **this package's** structural boundaries rather than
PyRuSH's. The shipped code enabled PyRuSH. Neither the promise nor the
contradiction had a number attached.

**The NegEx gold cannot settle it, and the tie it produces is not evidence.**
The two arms score identically to four decimal places, because every row of that
gold is a single sentence containing its concept: there is no second sentence
for a cue to leak into, and both segmenters return the same one boundary. The
instrument has no power. Reporting 0.0000 as "our boundaries do not help" would
be a misreading of an experiment that could not have detected the effect.

**The effect is measurable where the structure exists.** Seven templates — each
placing a negation cue and its target in different structural units — crossed
with seven de-identification conventions. The question has an answer known in
advance and needs no gold: *a placeholder carries no clinical meaning, so
swapping one convention for another cannot change what a note says.* An arm
whose verdict moves with the convention is reading formatting, not medicine.

| Arm | accuracy | instability |
|---|---:|---:|
| **ConText, our boundaries** | **1.0000** | **0.0000** |
| negspaCy | 1.0000 | 0.0000 |
| dependency parse | 0.8571 | 0.0000 |
| ConText, PyRuSH boundaries | 0.7755 | 0.1429 |
| cue window | 0.6122 | 0.1429 |

PyRuSH merges two list items under `___` and `[** **]` — the MIMIC-IV and
MIMIC-III conventions, the formatting of the most widely used clinical corpora
in the field — and a negation cue in item 1 then marks an active diagnosis in
item 2. The dependency arm is stable and loses `lexical_negation`, exactly the
failure the gold predicted.

At corpus scale the same substitution moves the modifier rate on gold
phenotype evidence from **34.7% to 30.1%** over an identical 934 spans —
`historical` alone drops from 90 to 65. Roughly 4.6 points of what was previously
reported as clinical fact was cue leakage across list and header boundaries.

### The templates said it was a clean win. The corpus says it is a trade

This is the part worth reading twice, because the seven-template result above is
not the whole picture and a paper that stopped there would be wrong.

Running the invariance gate over 20 real notes, both segmenters on identical
spans, decomposes by operator instead of aggregating:

| Operator | our boundaries | PyRuSH |
|---|---:|---:|
| `render.header_style` | **0.0000** | 0.0020 |
| `render.lab_block_collapse` | **0.0000** | 0.0026 |
| `render.whitespace_collapse` | **0.0026** | 0.0044 |
| `render.bullet_to_prose` | **0.0050** | 0.0072 |
| `render.deid_restyle` | 0.0116 | **0.0001** |
| **overall** | 0.0039 | 0.0033 |

**Our segmenter wins four of five and loses the fifth badly**, and the mechanism
is the same property in both directions. It models list, header and lab-block
structure, so perturbing those structures cannot move it — two operators go to
*exactly* zero. It also models **de-identification placeholders**, which means
the placeholder convention is an input to its own rules, so restyling one
convention into another changes its boundaries and the assertion moves with them.
PyRuSH models neither, so lists move it and restyling barely does.

The overall figures are close and their composition is completely different,
which is why they must be read per operator. And the honest statement about the
de-identification claim is narrower than the templates suggested: **our
boundaries are more accurate under a change of convention and less stable under
one.**

**The methodological point is the one this project already learned once.**
`probe_deid_assertion.py` found a real mechanism on one constructed note and
mis-ranked its causes; corpus-scale replication corrected it. The seven templates
here are a constructed set too, they showed 0.0000 instability, and the corpus
found 0.0116 on the operator those templates were specifically built around. A
constructed example is good for demonstrating that a mechanism exists and bad for
estimating how much of it there is — including when we construct it ourselves.

> **This supersedes the 42.9% figure** carried in earlier drafts. Two things
> changed: the sample (12 notes and 133 spans, against 68 and 934) and the
> segmenter. `comparison_pyrush_boundaries` in the artifact isolates the
> segmenter's share so the attribution is checkable rather than asserted.

## Does our modification actually move UMLS concepts, and is it right?

The CTX pair is an ablation of the one thing we change about a reused component,
so it owes the strongest evidence in this chapter. Two existing measurements are
insufficient, in opposite ways: the NegEx gold reports the arms as *identical*
(single sentences, no boundary to cross), and `phenotype_assertion.json` shows
the modifier rate moving 34.7% → 30.1% over 934 gold spans but says only that
it moved, not that the moves were improvements.

**So the question is asked directly on UMLS concept spans.** Over 20 notes and
**13,981 matched concept spans**, the two arms assign a different attribute to
**673 — 4.8%.** The modification is not cosmetic; it changes the assertion on
about one concept in twenty. The attributes involved are `negated` 361,
`historical` 204, `uncertain` 122, `family` 32.

**Which arm is right needs a referee, and there is no in-domain assertion gold.**
There is something better suited to this particular question: the note's own
structure. ConText assigns an attribute because a cue took scope over a target.
If the cue and the target sit in different **list items**, or on opposite sides of
a **section header**, then the cue did not govern that target — that is a fact
about the document, not an opinion about an annotation. The structural layer
deciding it is hand-written, versioned and validated against PyRuSH at stage 2,
so the referee is a measured component rather than a fresh judgement.

| | spans |
|---|---:|
| structure favours **our boundaries** | **181** |
| structure favours PyRuSH | 41 |
| **undecided** — cue and target share every unit | **451** |
| decidable share | 0.330 |
| **ours, of those decided** | **0.815** |

**The undecided count is the honest headline, not the win rate.** Two thirds of
the disagreement lies where document structure has no authority, and nothing here
licenses a claim about it. What can be claimed is narrow and now measured: *where
the note's own structure can rule, it rules for the boundaries we ship, four times
out of five.*

The failures it catches are ordinary rather than exotic. `C0011570` (depression)
and `C0003467` (anxiety) are marked `historical+negated` by stock ConText because
a `history` cue reached them from a **different list item**; several concepts are
negated by a `no` that lies in a **different section**. Separation reasons split
108 list-item-versus-prose, 60 different-list-items, 54 different-sections.

## The four dimensions are not peers

The component exposes `negated`, `historical`, `family` and `uncertain` as a flat
four-tuple, which reads as four comparable signals. The
lexical coverage behind them differs by roughly 14x — and **rule count is the
wrong unit for measuring it**. A medspaCy rule may carry a token pattern matching
a whole list, so the 102 rules expand to **271 triggers**:

| Attribute | ConText category | rules | **triggers** | cues/note | status |
|---|---|---:|---:|---:|---|
| `negated` | NEGATED_EXISTENCE | 69 | **145** | 26.9 | **validated** — F1 0.9289 on NegEx gold |
| `uncertain` | POSSIBLE_EXISTENCE + HYPOTHETICAL | 27 | **65** | 9.4 | MIMIC gold — κ 0.283, cue F1 0.733 |
| `family` | FAMILY | 1 | **51** | 3.7 | MIMIC gold — κ 0.798, cue F1 0.864 |
| `historical` | HISTORICAL | 5 | **10** | 5.0 | MIMIC gold — κ 0.312, cue F1 0.707 |

`uncertain` spans two ConText categories because this package reports four
dimensions where ConText has five; the merge is argued above. The rule inventory
artifact keeps ConText's own five keys and records the mapping, so a disagreement
can still be traced to the category that produced it.

**A correction, because this repository asserted the opposite.** Experiencer was
described here as resting on "the single literal `family`", with *"Father with
myocardial infarction"* given as an example of what it therefore misses. That is
wrong. The rule is *named* `family` and its pattern carries a **51-term kinship
list** from `aunt` to `wife`; `father` is in it. On the development corpus the
category fires **3.7 times per note in 100% of notes**, most often on
`family`, `father`, `brother`, `mother`.

The error came from counting rules where triggers were the meaningful unit, and
it inverted the ranking: experiencer is the **second best resourced** category,
not the worst. A second claim fell with it — that `Hx` was absent from the
HISTORICAL rules. Its pattern is `[history, hx, hist, ho]`. (`status post`
genuinely is absent, and is ordinary clinical usage.) There is also no PSEUDONEGATION category in the
English rule set, so *"no change"* and *"not only"* are handled only implicitly
by longest-match pruning, and no CONDITIONAL category, which is why
conditionality cannot be produced by this instrument at all.

`context_rule_inventory.json` regenerates the table from the installed rule file
so it stays honest across medspaCy versions.

### Uncertainty: the one of the four that could be measured, and what it showed

BioScope is the only freely available gold for speculation. Two facts about it
shape the result.

**Its clinical subcorpus is unusable.** `clinical_records_anon.xml` carries 872
negation and 1,137 speculation cues over radiology reports, and every token is
`*` — 0 letters against 42,514 asterisks. Reconstituting it needs the 2007 CMC
challenge text, obtained separately. What remains is biomedical *abstracts*:
real words, wrong genre.

**So negation was scored on the same sentences, as a control.** Both dimensions
face the identical genre shift, which makes two different comparisons legible:

| | negation | uncertainty |
|---|---:|---:|
| NegEx, clinical | **0.9289** | *no gold* |
| BioScope abstracts | **0.6111** | **0.2511** |
| precision / recall on BioScope | 0.581 / 0.645 | **0.855 / 0.147** |

**The domain shift alone costs 0.318 F1** — same engine, same attribute, only the
genre changed. Any uncertainty number read against the clinical negation figure
would be measuring mostly that.

**Within the corpus, uncertainty is still well below negation, and its shape says
why.** Precision 0.855 against recall 0.147: when ConText fires `uncertain` it is
almost always right, and it misses six hedges in seven. That is exactly the
signature of a *clinical* hedging inventory meeting *scientific* hedging — 18
rules built for `possible`, `cannot exclude`, `versus`, facing `suggesting that`,
`these results indicate`, `may reflect`.

**So `is_uncertain` stays disclosed rather than promoted.** What changed is that
it is now disclosed with a measured characterisation instead of a rule count: the
rules are precise and narrow, and no in-domain gold exists to say how narrow they
are on clinical text. `is_historical`, `is_hypothetical` and `is_family` have no
gold at all, in or out of domain, and remain rule-count disclosures.

> **Superseded below.** That last sentence was true when written and is not
> anymore: the MIMIC gold gives all four reported dimensions in-domain clinical
> gold, and `is_hypothetical` is no longer reported separately at all. The
> paragraph is kept because it records the state that motivated building the
> gold, and deleting it would hide why the gold exists.

## Absence is not affirmation

One implementation detail with a measurement attached, because it silently
falsified every artifact the package had produced.

`Evidence.assertion` is a `frozenset`, and `affirmed` was defined as "empty".
But `qualify` drops a span it cannot convert or that a wider span already
covers, and nothing had ever passed assertions into the phenotype index at all —
so every evidence span in every run carried an empty set, and
`evidence_touch_affirmed` **reported 100% affirmed in every artifact this package
had ever written**.

The fix is a `qualified` flag distinct from the attribute set, with three
consequences:

- `affirmed` means *qualified and carrying no attribute*; unqualified is
  unknown, and unknown is not healthy.
- `evidence_touch_affirmed` is **omitted rather than zeroed** when stage 8 did
  not run. An all-zero affirmed column beside a non-zero touch column would read
  as "every touched mention was negated" — the opposite of what it means.
- An `Evidence` carrying an attribute is forced qualified at construction, so
  the contradictory state cannot be built.

Measured coverage on real notes is **0.9987 to 1.0000**, so the drop is rare —
but "rare" is a measurement and "zero" was an assumption, and the field now
reports which one it is.

> **Worked examples and the full baseline comparison** live in
> [`validation/pipeline/assertion-benchmarks.md`](../pipeline/assertion-benchmarks.md): what one
> annotated span looks like, the five baselines side by side on three
> instruments, and the error taxonomy from the real MIMIC spans.

## Four dimensions, not five

ConText emits five attributes; this package reports **four**. `is_hypothetical`
and `is_uncertain` both map to `uncertain`, and the merge follows from what the
stage is for.

**The stage modifies the asserted presence of a concept** — pneumonia as
*absent*, *possible*, or *someone else's*. Against that purpose, a hedge
(`possible pneumonia`) and a condition (`Tylenol PRN`) are the same move: neither
asserts the finding is present now, and an operator flipping presence does
identical work in both.

**The separation was also unenforceable in the vocabulary.** The two are cleanly
distinct *as judgements* — two independent annotators disagreed about which
applied on **1 span in 136**, and the labels co-occurred on 4 of 119 spans. But
their cues are shared: `may` appears 134 times as a hedge and 50 as a permission,
`should` 5 and 63, `can` 13 and 27. A lexicon cannot assign those, so the split
forced an arbitrary majority-use ruling on every shared modal.

**The merge is measured, not assumed, and it helps.** Cue detection on held-out
notes, merged `uncertain` against the two dimensions it replaces:

| | stock F1 | extended F1 |
|---|---:|---:|
| `uncertain` (separate) | 0.487 | 0.663 |
| `hypothetical` (separate) | 0.408 | 0.647 |
| **`uncertain` (merged)** | 0.469 | **0.733** |

The merged extended arm beats either separate one, because the shared modals no
longer have to be assigned to one side. Inter-annotator κ is unchanged at 0.890,
so nothing was lost in annotation reliability, and the positive count rises from
41 to 119 — above the reporting floor with margin.

**Nothing was re-annotated.** The raw annotations from both models keep the two
labels apart; the merge is a projection applied at freeze time, so the gold
re-derives for free and can be un-merged if the distinction is ever wanted back.
ConText's own categories also survive on `Cue.category`, so the provenance of any
individual decision stays recoverable.

## The MIMIC gold, and what it overturned

The fixture gold answered what it could and then ran out of evidence. A second
gold was built on **real MIMIC-IV discharge summaries** — 100 notes and 1,000
spans, both hash-ranked with `rng.select`, spans filtered to clinical semantic
categories by a rule independent of ConText so the sample cannot inherit the
detector's decisions.

### What kind of concept carries a modifier

A per-dimension F1 treats every span as interchangeable, and this corpus shows
they are not. Categories were assigned by `categories.categories_of` from UMLS
semantic types **at sampling time, before annotation**, so the mix is a property
of the sample rather than a description written to fit it. Where a span carries a
broad and a narrow label the narrow one is reported, so the rows partition the
1,000 spans exactly:

| category | n | **modified** | `negated` | `uncertain` | `historical` | `family` | detector exact |
|---|---:|---:|---:|---:|---:|---:|---:|
| finding | 274 | 32.9% | 10.2% | 12.4% | 10.6% | 1.1% | 67.9% |
| medication | 201 | 17.4% | 3.0% | 10.0% | 4.5% | 0.0% | 79.1% |
| disease | 185 | **41.1%** | 8.6% | 14.6% | **17.8%** | 2.7% | 72.4% |
| procedure | 122 | 18.9% | **0.0%** | 10.7% | 8.2% | 0.0% | 76.2% |
| diagnostic procedure | 84 | 15.5% | 1.2% | 4.8% | 9.5% | 0.0% | **81.0%** |
| symptom | 76 | **61.8%** | **35.5%** | **25.0%** | 4.0% | 0.0% | **64.5%** |
| therapeutic procedure | 58 | 20.7% | 5.2% | 3.5% | 12.1% | 1.7% | 75.9% |

**"Modified", not "non-affirmed" and not "positive".** The first column is the
*union* of the four modifier columns, so they do not sum to it — modifiers
co-occur, and 12 of the 296 modified spans carry two, giving 308 label instances
over 296 spans. Its complement, *unmodified*, is what ConText and this codebase
call `affirmed`.

*Non-affirmed* was the earlier term here and it is **false for two of the four**.
`historical` does not withhold the assertion — *history of hypertension* affirms
the hypertension and places it in the past; `family` affirms the finding in
someone else. Only `negated` genuinely withholds and `uncertain` only partly, so
*non-affirmed* is accurate only with the trailing qualifier *about the patient
now*, which drops off whenever the term is used alone. What all four do is
**modify the asserted presence of the concept**, which is precisely what the
SEMANTIC operators flip. *Positive* is avoided for an unrelated reason: it
inverts between frames, since clinically *positive for pneumonia* is an
**unmodified** span while the scorer's `gold_positives` for `negated` counts the
clinically negative ones.

The overall rate — **29.6% modified** — lands within half a point of the 30.1% of
expert-annotated phenotype evidence that is not an affirmed statement about the
patient now, in the SNOMED entity-linking gold — the figure this chapter opens
with. Two corpora, two
annotation efforts, the same measure, and no shared method: the second is
independent corroboration of the first, and together they are the reason the
stage exists.

**Modifier load varies more than four-fold across concept types.** Symptoms are
61.8% modified and 35.5% negated — three times the corpus rate — because the
review of systems is where clinicians explicitly deny things. Procedures are
**never** negated, 0 of 122: a note records what happened, not what did not.
Diseases carry the historical mass at 17.8%, since past medical history is a list
of diseases rather than symptoms.

Two consequences for how any number in this chapter should be read.

**A negation figure is only interpretable beside its concept mix.** A detector
evaluated on symptoms alone would look far stronger than the same detector on a
realistic mix, and published negation results rarely state which they had. This
is also the most likely explanation for the NegEx-versus-MIMIC gap: curated
sentence-level golds over-represent exactly the prose constructions negation
detectors were built for.

**Detector reliability tracks modifier density inversely** — 81.0% exact
agreement on diagnostic procedures against 64.5% on symptoms, a 16.5-point spread
around a pooled 73.3%. The stage is most reliable where there is least to detect.
A robustness dose measured through it therefore carries different confidence
depending on which concepts it touched, which is why
`assertion_gold_profile.json` ships beside the headline numbers rather than as a
footnote to them.

**It is annotated, and counter-annotated.** Two independent frontier models
(`openai/gpt-5.6-luna`, then `openai/gpt-5.6-terra`) over identical spans and the
identical guideline, which was committed **before** any label was assigned. Both
bounds are reported, and they are the difference between a gold standard and one
model's opinion:

| | negated | uncertain | historical | family |
|---|---:|---:|---:|---:|
| **inter-annotator κ** (two models) | **0.913** | **0.890** | **0.845** | **0.899** |
| intra-annotator κ (order reversed) | 0.966 | 0.903 | 0.904 | 0.947 |

Exact label-set agreement is 0.933 between annotators and 0.958 within one. Every
dimension is "almost perfect" on Landis–Koch, so **the gold is not the limiting
factor** — which is what licenses reading the detector's disagreement as the
detector's failing.

**Only the inter-annotator row is a ceiling, and "ceiling" means something
specific.** A detector cannot be shown to agree with the gold better than the
gold agrees with itself: where two independent readers disagree about whether a
span is `historical`, *correct* is undefined for that span, and a detector score
computed over it measures the yardstick as much as the instrument. So κ 0.845
bounds what any `historical` detector could demonstrate on this corpus, however
good it is. The intra-annotator row bounds something weaker — that one rater
repeats itself, which a consistently wrong rater also does. Running only the
second pass would have looked like validation and established nothing; that is
why a second model was run at all.

Three caveats travel with the number, because these are not clinician
annotations. The annotators are **LLMs**, so two models sharing a training
distribution can agree on the same mistake in a way two clinicians would not,
making the ceiling plausibly *optimistic*. **Agreement is not accuracy** — κ 0.913
on `negated` says the readings coincide, not that either matches what the author
meant. And **`family` rests on 9 positives**, so its 0.899 is real but fragile.

What this licenses is narrow and worth stating exactly: *where two independent
annotators agree and the detector does not, the detector is the outlier.* That is
enough to rank arms and locate errors. It is not enough to call any label
correct.

**And it overturned the fixture gold's headline finding.** Detector agreement
against the two golds:

| Dimension | fixture κ | **MIMIC κ** | precision | recall |
|---|---:|---:|---:|---:|
| `family` | 0.22 | **0.798** | — | — |
| `negated` | 0.74 | 0.581 | 0.574 | 0.667 |
| `uncertain` | 0.34 | 0.283 | 0.694 | 0.210 |
| `historical` | 0.41 | 0.178 | 0.846 | **0.111** |

**`experiencer_shift` was cut from v1 on a number that was wrong.** The fixture
gold's κ 0.22 rested on *one* gold positive and a guideline error; on real text
with nine, `family` is the **best-agreeing** dimension at 0.798. The cut is
retracted — and the lesson is the one the corpus was built to test: a corpus that
cannot supply positives cannot support a verdict, and reporting κ on single
digits invited exactly this.

**The real failure is recall, and it is lopsided.** `historical` precision 0.846
against recall **0.111** — the detector finds 13 of 99. That is the signature of
missing triggers, not mis-scoped ones, and it was confirmed directly: `s/p`,
`status post` and `nil` produce **no cue at all** in the stock rule set, and occur
327 times across the 100 sampled notes. Adding them (`assertion_extensions.yaml`,
opt-in) takes `historical` κ from 0.178 to **0.317** and recall from 0.111 to
**0.222** — doubled — while leaving the other four dimensions untouched.

> **A prior that was measured and then rejected.** 46 of the 88 missed
> `historical` spans sit inside an explicitly historical section, which suggested
> a section-level default. It is not implemented, on the principle that assertion
> is a property of a **span in its context** and not of the header above it: a
> Past Medical History section routinely lists conditions that are currently
> active, and a blanket prior would assert something the note does not. The
> localisation is kept as a diagnostic; the shortcut is not taken.

## Is the SEMANTIC channel ready? One row per operator

Stage 8 exists to serve four perturbation operators. Each rewrites a cue in order
to flip one dimension, so **each inherits its detector's quality directly**: an
operator anchored on a detector that fires on the wrong spans edits the wrong
spans. The channel's readiness is therefore a per-dimension question, not one
question, and this is the table that answers it.

All four are now **built** (`src/robustehr/ops/semantic.py`), and each is measured
on two axes that must be read together: does the operator change the attribute,
and can the detector it anchors on be trusted to have set that attribute?

| Operator | Dimension | **flip rate** | collateral | detector κ (MIMIC) | detector recall |
|---|---|---:|---:|---:|---:|
| `semantic.temporality_shift` | `historical` | **1.0000** | 0.0000 | 0.178 → 0.317 ext | 0.111 → 0.222 ext |
| `semantic.uncertainty_flip` | `uncertain` | **1.0000** | 0.0000 | 0.363 | 0.293 |
| `semantic.negation_flip` | `negated` | **0.9808** | 0.0087 | 0.581 | 0.667 |
| `semantic.experiencer_shift` | `family` | 0.8312 | 0.0043 | **0.798** | — |

**The operators work; the detectors are the constraint.** Flip rates of 0.83–1.00
at collateral ≤0.0087 say the rewrite does what it claims and does not spill into
neighbouring dimensions. What bounds each operator is the column beside it: an
operator anchored on a detector with recall 0.111 will only ever perturb the 11%
of historical spans that detector found, and the dose accounting will report a
clean, fully-applied run over a denominator that was itself a ninth of the truth.

That is the honest statement of what these four are: **precise instruments over
incomplete eligibility**, and the eligibility is measured rather than assumed.

Read the last two columns together. Eligibility is ample for every dimension —
all five fire in 100% of notes — so **no operator here is blocked for want of
material**. What separates them is whether the detector puts the attribute on the
right span, and only negation does so with substantial agreement.

**`semantic.experiencer_shift` is the clearest case for not building.** On the
fixture gold, ConText marks **8 spans family where 1 is warranted**, and the
mechanism is specific: *"brought in by mother with 3 days of fever"* makes
`mother` a FORWARD cue that scopes over the child's **own** symptoms, so `fever`,
`decreased oral intake` and `breathing` are attributed to the mother. An
experiencer-shift operator anchored here would rewrite the patient's presenting
complaint as somebody else's — which is not a controlled perturbation, it is a
fabrication, and the dose accounting would report it as a clean edit.

**`semantic.uncertainty_flip` is blocked differently.** The detector is precise
where it fires and simply does not fire often enough: 0 predictions against 2
gold spans here, recall 0.147 on BioScope. An operator would run at a fraction of
its nominal dose and the shortfall would be invisible.

**`negation_flip` is the one to build first**, and its evidence is the strongest
in the package: clinical gold, an independent implementation agreeing within a
point, and κ 0.74 against a separate reading.

### The fixture gold, and what it is not

`assertion_gold.yaml` is 350 spans over 7 synthetic fixtures, annotated on all
four dimensions and shipped **in the repository**. It was built first because it
needs no permission: the fixtures were written from scratch, whereas disclosing
MIMIC-IV note text to a third party — an LLM API included — requires
authorisation under the PhysioNet DUA. A companion MIMIC gold was built
afterwards once that authorisation was confirmed, and the two answer different
questions; only this one is publishable, because permission to annotate is not
permission to redistribute.

**It is a second opinion, not a ground truth.** The annotator is an LLM with
prior exposure to this codebase, so κ measures agreement between two imperfect
raters and is reported on that footing; a high κ means the rules behave
predictably enough to anchor an operator, not that they are right. Two further
limits are load-bearing:

- **The corpus is negation-dense and hedge-poor.** 52 negated spans against 2
  uncertain and 1 family, so three dimensions cannot be scored at all here and
  report counts and κ only. The `family` row in particular rests on a single
  positive; what it demonstrates is the *false-positive* pattern, not a recall.
- **One correction was needed to the guideline itself**, and separating it from
  the detector's errors mattered. A first pass labelled *person* mentions
  (`mother` as informant) as family, which is a category error — a person is not
  a finding with an experiencer. Fixing it moved family from 5 gold positives to
  1 and left ConText's over-scoping standing as the real effect.

On this corpus stock PyRuSH scores **κ 0.7646 on negation against our boundaries'
0.7365** — the opposite direction to the MIMIC result. The sample is small and
the fixtures are short, so this is not evidence against the segmenter
substitution, but it is recorded rather than dropped.

## Detection, measured on its own terms

Every figure above scores at the **span** level — did this mention get the right
attribute — which conflates two abilities. A cue never found and a cue found but
mis-scoped produce the identical wrong span. The span numbers *suggest* detection
is the problem (`historical` precision 0.846 against recall 0.111) but cannot
prove it.

So the cues themselves were annotated: 11,239 cue occurrences over 886 windows of
the same 100 notes, and cue detection scored directly — a predicted cue matches a
gold cue when their spans overlap and the dimension agrees, greedy one-to-one.
The comparison includes a **lexicon floor**: every literal in medspaCy's rule file
matched as a bare substring, with no scope logic whatsoever.

Scored on the **40 held-out notes**, so the extended arm is estimated out of
sample:

| Dimension | arm | precision | recall | **F1** |
|---|---|---:|---:|---:|
| **negated** | **medspaCy extended** | 0.797 | **0.843** | **0.819** |
| | negspaCy | **0.917** | 0.691 | 0.788 |
| | medspaCy stock | 0.796 | 0.737 | 0.765 |
| | *lexicon floor* | 0.817 | 0.676 | *0.740* |
| **uncertain** | **medspaCy extended** | 0.706 | **0.761** | **0.733** |
| | medspaCy stock | 0.870 | 0.321 | 0.469 |
| | *lexicon floor* | 0.882 | 0.196 | *0.321* |
| **historical** | **medspaCy extended** | 0.624 | **0.814** | **0.707** |
| | medspaCy stock | 0.677 | 0.378 | 0.485 |
| | *lexicon floor* | 0.744 | 0.305 | *0.433* |
| **family** | **medspaCy stock** | 0.793 | **0.950** | **0.864** |
| | *lexicon floor* | 0.791 | 0.329 | *0.465* |

negspaCy attempts negation only, so it has no row on the other three — the same
single-dimension limit that decided which component ships.

> **These numbers replace a first run that was wrong**, and the error is worth
> recording because it ran the wrong way. The gold locator matched cue strings by
> bare substring, so `no` matched inside *normal*, *nodules*, *none* and
> *Diagnosis* — five gold cues where one was real. Inflated gold counts as missed
> recall, so **every detector looked worse than it is**: negation recall read
> 0.536 against the corrected 0.729. Word boundaries are now applied per edge,
> and only where the edge is alphanumeric, so cues like `(-)` and `?` still
> match. Every qualitative conclusion below survived the correction; the negation
> figures did not.

Four findings, and the floor is what makes three of them visible.

**For negation, the engine buys 1.4 F1 points** over a bare substring match —
0.759 against 0.745. The whole scope-resolution apparatus adds almost nothing to
cue *detection*; the vocabulary is what makes negation work. (This does not
contradict the span-level finding that scope resolution matters enormously —
there the window baseline reached 0.945 recall at 0.427 precision. Detection and
scoping are different jobs, and ConText earns its place in the second.)
negspaCy leads on F1 through much higher precision, consistent with its 0.9386
on the NegEx gold.

**Before the merge, ConText was worse than the floor on `hypothetical`** — 0.404
against 0.417.
Its scope pruning discards cues a substring match keeps. That is a repair
direction nothing else in this chapter would have surfaced.

**For `uncertain` and `family` the engine clearly earns its place**: 0.480 against
0.143, and 0.875 against 0.446. Both are carried by multi-token *patterns* rather
than literals, which a literal-only floor cannot see — the 51-term kinship list
is exactly this, and `family` is the best-detected dimension in the package at
0.983 recall.

**The cue extension's gain is larger here than at the span level**: `historical`
F1 0.481 → **0.674**, recall 0.370 → **0.627**. `s/p` and `status post` are not a
marginal addition; they are a substantial share of how temporality is written in
discharge summaries.

**Recall is the bottleneck in two of four dimensions** — `uncertain` 0.321 and
`historical` 0.378 before the extension — while precision holds at 0.68–0.87
throughout. That is the shape of a vocabulary problem, and it
is the conclusion the span-level analysis reached, now demonstrated rather than
inferred. Negation and experiencer are **not** in that group: at 0.729 and 0.983
recall their limits lie elsewhere.

### Closing the vocabulary gap, and what it costs

The cue gold makes the gap addressable rather than merely visible: it names the
surface forms that carry each dimension, so the missing ones can be counted
instead of guessed. Mined on **60 development notes** with a floor of six
occurrences, then scored on the **40 held-out notes** — a note-level split,
because a vocabulary mined from half of one note's sentences has still seen the
other half's phrasing.

| Dimension | stock F1 | **extended F1** | precision | recall |
|---|---:|---:|---|---|
| `uncertain` | 0.469 | **0.733** | 0.870 → 0.706 | 0.321 → **0.761** |
| `historical` | 0.485 | **0.707** | 0.677 → 0.624 | 0.378 → **0.814** |
| `negated` | 0.765 | **0.819** | 0.796 → 0.797 | 0.737 → **0.843** |
| `family` | 0.864 | 0.864 | unchanged | unchanged |

**`prn` alone accounted for 258 missed cues** on the development notes — as-needed
and interval dosing is conditional administration, and the stock set carries only
the spelled-out `as needed`. `recent` accounted for 51 historical misses, `may`
36 uncertain.

**It is a recall-for-precision trade everywhere except negation**, where recall
rises 11 points at no precision cost. Elsewhere precision falls 5–17 points to
buy 24–48 points of recall. Whether that trade is right depends on the use: for
an operator's *eligibility* it is clearly right, since a cue never found is a
perturbation never applied; for reporting a modifier *rate* it inflates the
numerator and the stock arm is the conservative choice. Both arms ship and the
default is stock.

**What was rejected matters as much as what was kept**, and the rejections are in
the resource with their counts:

- **`-`, 202 occurrences** — a bare dash marks a negative exam finding, and also
  every bullet, range and hyphen. Adopting it trades the entire precision column.
- **`normal`, `unremarkable`** — these assert a normal finding rather than
  negating a mentioned one; as cues they would negate every normal result.
- **`non-distended`, `non-tender`, `anicteric`** — morphologically negative single
  words, which this project's own annotation guideline (rule 2) labels
  **affirmed**. The annotator marked them against our guideline. Kept out, and
  the disagreement recorded rather than resolved silently in the rules' favour.

`may` was assigned to uncertainty and withheld from hypotheticality, a ruling the
merge made unnecessary:
it is far commoner as a hedge than as a permission, and a token in both
categories makes them fight.

## Three families of detector, and where each one wins

Everything above measures one detector family: a published rule algorithm and its
ablations. That was the right place to start, under the reuse rule this chapter
opens with. It is not where the argument can stop, because **the rules reached
their ceiling and it was possible to say so with a number.** A cue-direction
sweep bought `historical` +0.060 held out; the scope-termination fix that the
error analysis pointed straight at gained 0.029 on development and *lost* 0.074
held out. ConText implements a 2001 algorithm, and the honest move is to measure
the gap to what else exists.

Three families, identical held-out spans, identical gold — 400 spans, 40 notes:

| arm | deterministic | `negated` | `uncertain` | `historical` |
|---|:-:|---:|---:|---:|
| ConText stock | yes | 0.615 | 0.308 | 0.191 |
| ConText + mined cues | yes | 0.608 | 0.442 | 0.294 |
| **ConText + cues + header cue** | yes | 0.608 | 0.442 | **0.525** |
| BERT i2b2, zero-shot | yes | 0.725 | 0.053 | — |
| **BERT i2b2, distilled on this gold** | yes | **0.815** | 0.518 | 0.382 |
| **Bio_ClinicalBERT, distilled** | yes | 0.538 | **0.659** | 0.410 |
| Gemini 2.5 Flash | no | 0.838 | 0.695 | 0.623 |
| **Gemini 3.6 Flash** | no | **0.970** | **0.886** | **0.865** |
| *annotator ceiling* | | *0.941* | *0.895* | *0.897* |

Four findings, none of which was the expected one.

**Each dimension has a different best detector, and a different reason.**
`negated` is won by an encoder distilled from this gold; `uncertain` by a
different encoder; `historical` by a rule. A claim that any one family "is
better" would be an artefact of which dimension was measured.

**The gold is supervision, and 600 spans of it distil.** The gold is two frontier
models agreeing at κ 0.845–0.913. An LLM cannot sit in a package promising
replayable edit scripts — the AST lint bans `random`, `hash()` and wall-clock
from `src/`, and an API call is neither offline nor hashable into an operator
version. An encoder can: fixed weights, greedy argmax, and two consecutive runs
verified byte-identical. So `LLM annotates → encoder distils → deterministic
detector ships` is the architecture the constraint forces, and negation reaching
0.815 from 47 training examples says it survives contact with a thin gold.

**Rules beat every encoder on `historical`, and the reason is not sentiment.**
The evidence for that dimension is *structural* — 21 of 32 misses have no cue
anywhere in the span's sentence, and most sit under a header saying the section
is past. A header is layout, not language. Sixty-one training examples cannot
teach a transformer to read a layout that five lines of rule read exactly. This
is the dimension with **no published baseline in any assertion benchmark**,
because the i2b2 task has no temporality class at all.

**The prompt was a larger lever than the model, and it was ours.** The first LLM
arms over-called everything, and the cause was a prompt written to *construct the
gold* rather than to *detect*: it never stated that ~70% of spans carry no
modifier. Adding the base rate, a requirement that a cue must govern the span
rather than sit near it, and a tie-break toward the empty list moved 2.5 Flash's
negation from 0.660 to 0.838 — precision 0.493 to 0.775. That was chosen on the
development half and reported on held-out once, for the reason this chapter
records twice already.

### The number that had to be checked rather than published

Gemini 3.6 Flash reaches κ 0.967 on negation against a gold whose two annotators
agreed at 0.936. **A detector cannot be more correct than its gold.** What a
third model can be is more similar to annotator 1 than annotator 2 was, which
would make the figure an artefact of shared bias.

Scored against each annotator separately, on identical spans: 0.9500 against
annotator 1 (the gold), 0.9450 against annotator 2, where the two annotators
agree with each other at 0.9525. It agrees with each about as well as they agree
with each other — a **third rater of equivalent quality**, not a model tracking
one annotator's idiosyncrasies.

This is the strongest evidence an LLM-annotated gold can support, and it is still
not proof. Three models could share a bias no clinician would, and nothing in
this corpus could detect that. It is the reason the ceiling row is labelled
*annotator*, not *human*.

## What performance would be publishable, and against which claim

The question a reviewer asks depends entirely on what is being claimed, and the
two possible claims have thresholds an order of magnitude apart.

### If the claim were "a better assertion detector"

Then the bar is well established and we are nowhere near it.

| Reference point | Task | Reported |
|---|---|---|
| NegEx (Chapman 2001) | negation, sentence-level | ~0.84 precision / 0.82 recall |
| ConText (Harkema 2009) | negation | ~0.90+ F1; temporality and experiencer materially lower |
| i2b2 2010 assertion challenge | 6-class span assertion | best systems ~0.936 micro-F1 |
| ShARe/CLEF 2014 Task 2 | per-attribute | negation ~0.90+; other attributes lower |
| Transformer negation models | negation | 0.95+ F1 on i2b2 |

Against that, our negation figures are **0.9289 F1 on the NegEx gold** —
competitive — and on the MIMIC gold **0.608 from rules, 0.815 from an encoder
distilled on this gold, 0.970 from a frontier LLM**. Only the last is near the
published transformer numbers, and it is not a shippable component here.

The distilled encoder at 0.815 is the figure that changes the shape of this
comparison: it is a deterministic, offline detector trained on **47 negated
examples**, so it is neither competitive with i2b2-scale supervision nor
dismissible. The other dimensions remain far below any published reference —
which for `historical` is unavoidable, since **no published reference exists**.

Two caveats keep the comparison honest in both directions. The published figures
are on *curated benchmark* corpora with human adjudication, and ours is on
unfiltered MIMIC discharge summaries annotated by two LLMs — a harder and more
heterogeneous setting, so the numbers are not directly comparable. But that cuts
the other way too: **a lower number on a harder corpus is still a lower number**,
and nothing here licenses claiming parity.

### The claim this package actually makes

RobustEHR is measurement infrastructure. The contribution is not a better
contextualizer — it explicitly reuses one, and the reuse rule says a cited
component may be used and a modified one owes a number. The claim is that
**robustness results conditioned on assertion inherit the detector's error, and
nobody reports that bound.**

For that claim the threshold is different, and it is a threshold on *disclosure*
rather than on performance:

1. **The gold must be credible.** Two independent annotators at κ 0.845–0.913
   with the guideline fixed before annotation, plus an intra-annotator bound.
   That is the part a reviewer will attack, and it is the part that holds.
2. **The bound must be reported per dimension, not aggregated.** `negated` at
   0.815 and `historical` at 0.525 cannot share a sentence, and neither could
   the 0.608 and 0.294 they replaced.
3. **Anything fitted must be held out** — and that now covers four fitted
   things, not one: the cue extension, the cue directions, the prompt wording and
   the encoder weights. All are chosen on the development notes and reported on
   the held-out ones once. The split is note-level because a span-level one
   leaked: 97 of 100 notes had spans in both halves.
4. **The detector family must be disclosed with the number.** A reader comparing
   this stage to a published system needs to know whether the figure came from a
   rule set, a distilled encoder or an API call, because the three differ in
   reproducibility rather than only in accuracy. Every table in this chapter
   carries that column.
5. **Operator claims must be bounded by detector claims.** `temporality_shift`
   flips 100% of what it is given and is given 11% of the truth. Reporting the
   first without the second would be the exact failure this chapter documents.

On that reading the weak dimensions are **findings, not embarrassments**: a
robustness study that conditions on `historical` is resting on a detector with
0.111 recall, and that is worth publishing precisely because it is not currently
disclosed anywhere.

**What would change the calculus.** If a reviewer requires in-domain parity with
i2b2, the honest options are to obtain i2b2/n2c2 assertion data and report on it
directly, or to narrow the paper's assertion claims to negation, where the NegEx
figure is defensible. Both are preferable to presenting 0.178 beside a citation
of 0.936 without saying they measure different things on different corpora.

## What is not built, and why the reader is told

**ShARe/CLEF 2014 Task 2 was the promised benchmark** and is not used. It
requires credentialed access, and two of its six required metrics —
conditionality macro-F1 and cue-span F1 — cannot be produced by an instrument
whose English rule set has no CONDITIONAL category. It remains named future work
with its six-metric list intact, including its explicit prohibition on
collapsing them into a single contextualization score.

**The CTX-A→CTX-I ablation ladder is reported at two rungs, not nine.** CTX-A
and CTX-B are measured above. Rungs C–I — section priors, orthogonal dimension
mapping, target-compatibility rules, conflict detection, abstention, validated
cue extensions — are a research programme, and listing them as pending work
would overstate how close they are.

**Uncertainty has no gold here.** BioScope carries speculation annotations and
would supply one; until it is run, `uncertain` stays in the disclosed column with
its 18 rules.
