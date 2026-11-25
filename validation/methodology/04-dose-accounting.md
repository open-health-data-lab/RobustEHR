# Dose accounting

"We corrupted 30% of the note" is not a specification. Thirty percent **of
what** determines the experiment, and three conventions here exist because their
absence produces wrong figures rather than missing ones.

## The denominator chain

Every `(note, operator, severity, scope)` cell records the full chain as exact
integers:

```
total_n  →  scope_n  →  protected_n  →  eligible_n  →  requested_k  →  applied_n
```

- `total_n` — units of the operator's declared kind in the document
- `scope_n` — after the scope and target filter
- `protected_n` — withheld by the protection registry
- `eligible_n` — scope ∩ ¬protected ∩ operator-specific eligibility
- `requested_k` — exact integer arithmetic from severity over `eligible_n`
- `applied_n` — edits surviving conflict resolution

Order is load-bearing. Scope filtering precedes protection so that
`protected_n` counts what was withheld *inside the scope*, not across the
document.

## Null is not zero

An operator with no eligible units reports `achieved = null`, never `0`.
Averaging zeros silently under-reports every operator across a corpus where it
sometimes does not apply. Five distinct "nothing happened" outcomes are kept
apart because they mean different things to an applicability report:

| Status | Meaning |
|---|---|
| `na_no_eligible` | the operator does not apply to this note |
| `na_scope_empty` | units existed; the scope selected none |
| `na_all_protected` | units were in scope; every one was withheld |
| `under_dosed` | rounding produced zero applications despite a positive rate |
| `no_change` | edits were proposed; none survived conflict resolution |

## Plot achieved, never requested

Sub-unit rounding, protection and conflict rejection all move the realized dose
away from the request, so `dose_inflation = applied_n / requested_k` is a
first-class field and every figure uses the achieved rate.

**The calibration result (development run; no committed artifact).** At an
identical nominal severity of 0.30, measured aligned character edit rate (ACER)
on a development run was:

| Operator | ACER at nominal 0.30 |
|---|---|
| `render.deid_restyle` | 0.023 |
| `render.header_style` | 0.008 |
| `render.whitespace_collapse` | 0.004 |

A **6.5× spread**. "30% of X" is not comparable across operators, which is why
nominal severity cannot be the x-axis of a robustness curve. These three numbers
are not reproduced by any artifact under `validation/measurements/` and are not
quoted in the manuscript; the structural point survives without them, and the
corpus characterisation in `validation/measurements/corpus/` carries the
committed version of it (eligible units per operator per note).

## Baseline is a stratifier, never an addend

A note is already degraded before anything is done to it. Adding "existing
noise" to "injected noise" produces a quantity that means nothing, so the
Document Quality Profile is reported separately and used to **stratify**
results.

The hypothesis it exists to test is that already-degraded notes are more
fragile. If true that is a finding; either way it cannot be tested without
measuring baseline independently.

## Rates serialize as integer pairs

A float rate would make output byte-nonreproducible across platforms for no
benefit. `Fraction` is exact and `(numerator, denominator)` round-trips.

## Intensity measures

- **ACER** — sum of per-edit Levenshtein distance over document length. Named
  for what it is: the cost of the alignment *induced by the edit script*, not a
  global Levenshtein distance, which would be infeasible over a full sweep and
  is not what this measures.
- **token change rate** — a multiset difference, reported as a diagnostic
  beside ACER rather than as a primary measure.
- **landing counts** — applied edits per semantic category, which is what makes
  a dose interpretable at all.

## The baseline profile, measured

`robustehr baseline` reports three dimensions per note, each a rate over an
explicit denominator. On 200 development notes:

| Dimension | Metric | min | median | max |
|---|---|---|---|---|
| lexical | misspelling rate | 0.000 | **0.004** | 0.065 |
| lexical | unrecognized rate | 0.084 | 0.162 | 0.276 |
| structural | whitespace noise | 0.011 | 0.031 | 0.314 |
| de-identification | mask density | 0.011 | 0.034 | 0.090 |

Also: 200/200 hard-wrapped, 200/200 carrying more than one header grammar,
13/200 carrying more than one de-identification convention in a single note.

**The misspelling estimate is corpus-aware and refuses to guess without a
corpus.** This matters because the naive version was wrong in a way that would
have propagated into every stratified result. Counting every unrecognized token
as a misspelling put `daily` (2,627 occurrences), `tablet` (2,390), `acute` and
`bilateral` at the top of the list — clinical and administrative vocabulary
absent from both lexicons rather than errors. Restricting to hapax legomena
leaves `abdmoninal`, `abdomnial`, `abdompen`, `abnomalities`, and drops the
median rate from 7.5% to 0.4%.

A word used once in a corpus of hundreds of notes is a typo; a word used 2,000
times is vocabulary, however unrecognized. A single note cannot make that
distinction, so without corpus frequencies the field reports `null` rather than
falling back to the unrecognized count.

The unrecognized rate is retained separately as a legitimate quality signal in
its own right — a note dense with tokens no resource recognises is degraded
whether the cause is typing, jargon or de-identification residue.

### Structural separation from dose

`QualityProfile` and `DoseRecord` share no field that could be added together,
and a test asserts it. That is deliberate: the guarantee that baseline is a
stratifier rather than an addend should not depend on nobody making the mistake.
