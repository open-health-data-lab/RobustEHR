# Targeting: did Experiment 2 actually hit clinical concepts?

Experiment 1 corrupts the whole document with no clinical target; Experiment 2
restricts the same operator, at the same severity, to spans the measured
`ClinicalSalience` rule accepts. If the two arms landed on the same kind of
token, the targeted arm is not a different condition and the comparison between
them means nothing — so this is the table that has to hold before any downstream
result can be read as being *about* clinical content.

Measured by diffing every corrupted corpus against the clean baseline over
**1,388 notes** and classifying each changed word-token with
the same evidence the targeting rule uses: the measured salience lexicon at a
0.50 threshold, plus the curated drug vocabulary. Using the rule's own evidence
answers *did the rule do what it claims*, rather than introducing a second,
unvalidated notion of clinical that could agree by construction.

## Where the edits landed

| Corruption | Severity | Clinical, exp1 | Clinical, exp2 | Enrichment | Non-clinical, exp1 | Non-clinical, exp2 |
|---|---|---:|---:|---:|---:|---:|
| `typographical_errors` | low | 32.1% | **93.7%** | **2.9x** | 64.0% | 1.6% |
| `typographical_errors` | medium | 32.2% | **93.7%** | **2.9x** | 63.8% | 1.6% |
| `typographical_errors` | high | 32.2% | **93.7%** | **2.9x** | 63.7% | 1.6% |
| `homoglyph_substitutions` | low | 33.8% | **93.3%** | **2.8x** | 61.6% | 1.2% |
| `homoglyph_substitutions` | medium | 33.0% | **93.5%** | **2.8x** | 62.5% | 1.2% |
| `homoglyph_substitutions` | high | 32.3% | **93.7%** | **2.9x** | 63.4% | 1.2% |

Experiment 1 spends **32%-34%** of its edit budget on clinical
tokens — which is the point of the control, because the SNOMED CT Entity Linking
gold independently puts clinical tokens at **29.1%** of word tokens in this
corpus. An untargeted operator hitting them at their base rate is the null
result this arm is supposed to produce, and it does.

Experiment 2 reaches **93%-94%**, and its non-clinical share falls by
roughly **53x**. The enrichment is stable across corruptions and
severities, so it is a property of the targeting rule and not of one operator or
one dose.

## What counts as clinical

| Class | Rule | Examples (salience) | Where it is wrong |
|---|---|---|---|
| **Clinical** | salience >= 0.50, **or** in the curated drug vocabulary | `hypertension` 0.99, `edema` 0.99, `metoprolol` 0.004 (drug) | Admits generic words that score high because they *co-occur* with findings: `left` 0.87, `right` 0.82, `normal` 0.61 — clinically weak in isolation. |
| **Non-clinical** | in the lexicon, below 0.50, and not a drug | `the` 0.04, `and` 0.03, `she` 0.001 | Contains genuinely clinical tokens the gold under-annotates. Lab assays fall either side of the threshold for no clinical reason: `hct-` 0.99 and `na-` 0.99, but `mcv-` 0.38, `lipase-` 0.44, `k-` 0.23. |
| **Unmeasured** | never seen often enough in the gold to score | rare terms, de-identification artifacts | Skewed *clinical* — mostly rare disorders and drug spellings — so folding it into either side would flatter that side. Reported separately for that reason. |

### Incomplete specificity, stated plainly

The rule measures **precision 0.820, recall 0.789, F1 0.804** against 272
MIMIC-IV discharge summaries adjudicated in the SNOMED CT Entity Linking
Challenge (75,491 spans). About **one token in five that it calls clinical would
not be adjudicated a clinical concept**, and about one in five that would be, it
misses. The errors are systematic, not random:

* **Co-occurrence, not meaning.** Salience is P(token lies inside an adjudicated
  span), so laterality and qualifier words score high because they sit *within*
  findings. `left` at 0.87 reflects `left ventricular hypertrophy`; it does not
  make `left` a clinical concept.
* **The gold under-annotates medications** — 27.2% of mentions, against 80.6%
  for symptoms and 70.8% for diseases. Hence the separate drug clause, and hence
  precision 0.820 is a **floor rather than an estimate**: every drug admitted by
  vocabulary and absent from the gold is scored against the rule.
* **Context-blind and corpus-bound.** One score per token type, identical in
  every sentence, derived from discharge summaries alone. It does not transfer
  unexamined to progress notes, radiology, or another institution.

This does not weaken the targeting comparison, because **both arms are classified
by the same rule**: a systematic error moves exp1 and exp2 together and cannot
manufacture a 2.9x gap. It does mean the absolute numbers should be read as
*share of tokens this rule calls clinical*, not *share of clinical content*.

### Specimen tokens

| Token | Salience | Classified | Note |
|---|---:|---|---|
| `hypertension` | 0.989 | clinical | core concept, correctly admitted |
| `edema` | 0.985 | clinical | core concept, correctly admitted |
| `pneumonia` | 0.983 | clinical | core concept, correctly admitted |
| `left` | 0.865 | clinical | **over-inclusive** — scores high by co-occurrence |
| `right` | 0.823 | clinical | **over-inclusive** — scores high by co-occurrence |
| `normal` | 0.608 | clinical | **over-inclusive** — scores high by co-occurrence |
| `metoprolol` | 0.004 | clinical | salience alone would reject it |
| `acetaminophen` | 0.011 | clinical | salience alone would reject it |
| `warfarin` | 0.243 | clinical | salience alone would reject it |
| `hct-` | 0.994 | clinical | correctly admitted |
| `na-` | 0.992 | clinical | correctly admitted |
| `mcv-` | 0.382 | non-clinical | **missed** — clinical, but below threshold |
| `lipase-` | 0.439 | non-clinical | **missed** — clinical, but below threshold |
| `k-` | 0.229 | non-clinical | **missed** — clinical, but below threshold |
| `the` | 0.035 | non-clinical | correctly excluded |
| `and` | 0.031 | non-clinical | correctly excluded |
| `she` | 0.001 | non-clinical | correctly excluded |

## The tokens themselves

From `typographical_errors/high` over 1,388 notes — the same rule at its
heaviest dose, where the token lists are least noisy. Counts are occurrences
corrupted.

### Experiment 1 — untargeted

**Most-corrupted clinical tokens** — `pain` (1,947), `left` (906), `right` (830), `normal` (715), `chronic` (607), `chest` (545), `disease` (479), `abdominal` (451), `clear` (421), `edema` (418), `creat-` (408), `nausea` (403)

**Most-corrupted non-clinical tokens** — `and` (7,679), `the` (6,175), `with` (4,822), `was` (4,269), `for` (3,320), `daily` (2,816), `blood` (2,266), `she` (2,099), `you` (1,676), `tablet` (1,646), `patient` (1,629), `your` (1,590)

### Experiment 2 — `ClinicalSalience`-targeted

**Most-corrupted clinical tokens** — `pain` (1,912), `left` (911), `right` (795), `normal` (731), `chronic` (547), `chest` (519), `clear` (457), `disease` (446), `edema` (431), `abdominal` (415), `rbc-` (414), `wbc-` (397)

**Most-corrupted non-clinical tokens** — `mcv-` (364), `abslymp-` (59), `abseos-` (54), `lipase-` (51), `absbaso-` (49), `absneut-` (44), `absmono-` (40), `count-` (35), `phosphate-` (30), `appear-clear` (26), `bands-` (24), `fluticasone-salmeterol` (21)

### Reading the residual

The contrast in the non-clinical rows is the result in miniature. Experiment
1's are ordinary English —
`and`, `the`, `with`, `was`, `for`, `daily` — function words and
narrative that carry no clinical content.

Experiment 2's residual is a different kind of token altogether —
`mcv-`, `abslymp-`, `abseos-`, `lipase-`, `absbaso-`, `absneut-`. These are laboratory
assay names carrying a trailing hyphen from the lab-block layout. They are
clinical in substance and the classifier scores them below threshold, which
means the **1-2% figure above overstates how much prose the targeted arm
hit**:
most of that residual is clinical content the lexicon under-scores, not English.

That is a limitation of the measurement reported against itself, and the reason
`unmeasured` is kept as its own bucket rather than folded into either side.
See `docs/validation-protocol.md` §9 for the rule, its lexicon digest and its
benchmark.

