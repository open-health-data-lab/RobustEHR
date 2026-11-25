# Assertion annotation guideline

The rules for labelling a span's assertion status on four dimensions. This
document is the annotation instrument: `validation/pipeline/scripts/annotate_assertions.py` inlines
it into every prompt, so the rules an annotator follows and the rules a reviewer
reads cannot drift apart.

**It is committed before any label is assigned**, and that ordering is
deliberate. The first assertion gold in this project was annotated while the
rules were still being written, and one guideline error — labelling *person*
mentions as `family` — was nearly reported as a detector failure before it was
caught. A rule discovered mid-annotation contaminates every label taken before
it.

## What is being labelled

A **span** is a clinical mention located by stages 5–7 — a disorder, finding,
symptom, procedure or medication. The question for each is:

> From the chart's perspective, what does this note assert about this thing?

The four dimensions are those `concepts.context.qualify` emits, so the gold and
the detector are answering the same question in the same vocabulary. **They
co-occur**: `no history of X` is both `negated` and `historical`.

| Dimension | Applies when |
|---|---|
| `negated` | The note says this is **absent**. |
| `uncertain` | **Not asserted as present now** — hedged (possible, probable, cannot be excluded, being ruled out) *or* conditional (PRN, "if", return precautions, future plans). |
| `historical` | Framed as **past** rather than the current episode. |
| `family` | The finding belongs to **someone other than the patient**. |

**No label means affirmed, current, and the patient's.** That is the majority
case by a wide margin; the annotation task is to find the exceptions.

## The rules that decide hard cases

These exist because each one changed a label during the fixture annotation.

### 1. `family` is about the finding, not the person

`family` means *the finding on this span belongs to someone other than the
patient*. A **person mention is not a finding with an experiencer**.

- *"Informant: mother"* — the span `mother` is **not** `family`. It is a person,
  and no clinical finding is being attributed.
- *"Father with myocardial infarction"* — the span `myocardial infarction` **is**
  `family`.
- *"brought in by mother with 3 days of fever"* — `fever` is **the child's**, so
  it is **not** `family`. The mother is the person who brought the patient in.

The third case is the one that matters most: a cue naming a relative does not
make the findings around it that relative's.

### 2. Morphology is not negation

- A **single word** that names a normal state through negative morphology —
  `nontender`, `nondistended`, `afebrile`, `unremarkable` — is **affirmed**. It
  asserts a normal finding; it does not negate a mentioned one.
- A **multi-word span that swallows its own cue** — `not indicated`, `not
  elevated`, `no airspace opacities` — is **negated**, because the finding it
  names is the thing being denied.

### 3. `historical` records framing, not biology

A condition introduced by *"history of"*, *"h/o"*, *"status post"*, or sitting
under a **Past Medical History** header is `historical` **even when it is also
currently active**. Ischemic cardiomyopathy does not stop existing because the
note filed it under history.

The dimension records how the note *frames* the mention. That is what an
assertion layer can observe and what a temporality operator would rewrite.

### 3a. `uncertain` covers hedges **and** conditionals

Hedges and conditionals are **one label**, and an annotator should not try to
distinguish them.

| construction | example | label |
|---|---|---|
| hedge | *"possible pneumonia"*, *"cannot exclude PE"*, *"pneumonia vs atelectasis"* | `uncertain` |
| conditional | *"Tylenol PRN for pain"*, *"return if you develop fever"*, *"should he deteriorate"* | `uncertain` |
| future plan | *"repeat echocardiogram in twelve months"* | `uncertain` |

**The test is one question: does the note assert this is present now?** If not —
whether because the author is hedging or because the claim is contingent on
something that has not happened — the label is `uncertain`.

**Why they were merged.** This stage exists to modify the asserted presence of a
concept: pneumonia as absent, possible, or someone else's. A hedge and a
condition are the same move against that purpose, and the operator that flips
presence does identical work in both.

The two were reliably *distinguishable as judgements* — in the MIMIC gold they
co-occurred on 4 of 119 spans and two independent annotators disagreed about
which applied on **1 span in 136**. What failed was the vocabulary. The cue
surfaces are shared:

| cue | hedging use | conditional use |
|---|---:|---:|
| `may` | 134 | 50 |
| `should` | 5 | 63 |
| `can` | 13 | 27 |
| `could` | 22 | 14 |
| `likely` | 177 | 1 |

The same modal signals either reading depending on what follows it, so the split
forced an arbitrary majority-use ruling on every shared modal. Merging removed
that ruling and cue detection improved: F1 0.663 and 0.647 for the two separate
dimensions against **0.733** merged, on held-out notes.

### 4. Rule-out is `uncertain`, not `negated`

*"CTA obtained to rule out PE"* means PE is **suspected**, so `PE` is
`uncertain`. Only an explicit finding of absence — *"no evidence of PE"* — is
`negated`. The two are opposite verdicts and the distinction is where a cue-based
detector is most likely to be wrong, so it must not be blurred here.

### 5. Orders and plans

- An **active order** is affirmed: *"Continue metformin"* → `metformin` affirmed.
- A **conditional or as-needed** order is `uncertain`: *"Acetaminophen PRN"*,
  *"Trial of NG feeds if oral intake remains poor"*, *"Return if worsening"*.
- A **future scheduled** item is `uncertain`: *"repeat echocardiogram in
  twelve months"*.

### 6. Section headers carry framing

A span under `FAMILY HISTORY:` inherits `family`; one under `PAST MEDICAL
HISTORY:` inherits `historical`. This is why the annotation windows always carry
their section header — a window that lost its header would systematically
under-label both dimensions.

## Deciding when the note is genuinely ambiguous

Label what the note **says**, not what is clinically likely. If a span could
defensibly take a dimension or not, prefer **not** labelling it: a gold that
over-labels makes a detector look better at recall than it is, and recall is the
weaker side of every dimension measured so far.

## Scope of this guideline

It covers the four dimensions `qualify` emits. It does **not** cover
conditionality or resolution status, which the PRD's richer scheme names but
medspaCy's English rule set has no category for — an annotation nothing could be
scored against would be effort spent for no measurement.
