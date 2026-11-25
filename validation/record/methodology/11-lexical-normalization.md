> **Development record.** This document was written while the component it
> describes was being built and reads as a history. The method as it stands is
> in [`validation/methodology/`](../../methodology/); nothing here is cited by the
> manuscript. Kept so every decision can be audited.

# Lexical normalization: explored, measured, and not included

Most clinical concept-matching pipelines carry a normalization step. This one
does not, and a reviewer is entitled to ask why. The answer is not that the
problem is absent — it is that **two independent measurements found the
available instruments not good enough to be worth the risk they add**, and a
step that degrades its own input is worse than no step.

This chapter records both, because a methods section that lists only the
components built is not a methods section.

## The problem is real

Two kinds of surface variation separate a note from a terminology:

**Derivational and inflectional.** A note writes `hyperkalemic` where UMLS holds
`hyperkalemia`, `renal` where it holds `kidney`, `chest pains` where it holds
`chest pain`.

**Typographic.** A note writes `creatnine`, `hypertenion`, `pneumonai`. The
development corpus carries a measured misspelling rate with a median of 0.004 —
low, but not zero, and it is a discharge-summary corpus rather than a dictated
one.

Both would be a normalization step's job. They were measured separately because
they are different problems with different instruments.

## Why it matters here more than elsewhere

**Stage 5 is not neural.** The matcher is QuickUMLS — simstring approximate
matching, Jaccard similarity over character 3-grams, threshold 0.7 — so surface
form is most of what it has to work with. A contextual embedding model degrades
gently as characters change; an n-gram matcher need not, and this one does not:

| Surface | Result |
|---|---|
| `hypertension` | 1.000 |
| `hypertensionn` — one insertion | **0.909, still matches** |
| `hypertenion` — one deletion | **no match at all** |
| `pneumonai` — one transposition | **no match at all** |
| `creatnine` — one deletion | **no match at all** |

An insertion *adds* n-grams while leaving the originals intact; a deletion
destroys three at once and drops similarity below threshold. So the pipeline is
measurably more robust to some character perturbations than to others, which is
precisely the kind of asymmetry a normalization step exists to remove.

That made the question worth measuring properly rather than settling by
convention.

## Measurement 1 — derivational normalization

**Instrument: `MRXNS_ENG`**, NLM's Metathesaurus indexed by normalized string —
lowercased, inflection-stripped, stopword-dropped, word-sorted. The reuse
principle applies in its strongest form here: the component already exists, is
maintained by the terminology's own publisher, and needs no reimplementation. The
only question is what it buys.

Over the 68-note test split, against 12,091,090 normalized keys:

| | |
|---|---:|
| gold spans the pipeline misses | 3,557 |
| reachable by a normalized lookup | 2,376 (66.8%) |
| **…carrying the right concept** | **418** |
| **ceiling** | **11.8% of the miss set** |

**418 spans is 1.8% of the corpus.** For scale, the abbreviation-expansion stage
recovered roughly 1,486 `procedure` and 1,401 `lab_measurement` spans on the same
gold — seven times as much.

**The precision figure decided it.** A normalized lookup reaches something 66.8%
of the time and the right thing **17.6%** of the time. Normalization is lossy by
construction: sorting the words and stripping inflection collapses distinct
concepts onto one key, so most hits are collisions rather than recoveries. Any
usable version needs a ranking step on top, and that step would be competing for
the same 11.8%.

The estimate is deliberately an **upper bound**. A naive inflection strip
disagrees with `luinorm` — `shortness` becomes `shortnes` while `luinorm` leaves
it alone — and a key that differs by one character matches nothing. Rather than
reimplement `luinorm`, the measurement generates two candidate normalizations per
surface and counts a hit on either, where a real normalizer produces one. So
11.8% is the optimistic reading.

**And the residue points elsewhere.** The spans a normalized lookup cannot reach
are not morphological variants:

```
rrr 49   ctropnt 37   gallops 34   eomi 31   clubbing 29   nontender 23
```

Roughly half are abbreviations — the previous stage's territory, mostly
institutional forms absent from every terminology. The rest are examination
findings UMLS either lacks or types outside our categories. Neither is a
normalization problem, so neither would be fixed by solving one.

## Measurement 2 — spelling correction

The second framing, and the one closer to what "normalization before concept
tagging" usually means.

**Ground truth is exact.** The corruption operator knows what each word was
before it changed it, so a corrector's answer is right or wrong with no
adjudication and no annotation. Over 5,372 corrupted words:

| Method | Vocabulary | Coverage | Accuracy | **Recovery** |
|---|---:|---:|---:|---:|
| **english + clinical, edit-1** | 271,532 | 0.966 | 0.548 | **0.530** |
| english + clinical, edit-2 | 271,532 | 0.985 | 0.538 | 0.530 |
| english only, edit-1 | 28,329 | 0.837 | 0.558 | 0.467 |
| english + clinical, edit-1, abstains on ties | 271,532 | 0.580 | **0.744** | 0.432 |

`recovery` — correct over *all* corrupted words — is what ranks them. Coverage
bought by guessing is not a gain, because a corrector that always answers turns
every unrecognized clinical term into a wrong word.

Three findings, in order of usefulness:

**A general dictionary is not enough, and the gap is 6 points.** Adding the
clinical vocabulary moves recovery from 0.467 to 0.530. This is the measured size
of a mistake that is easy to make by default, since every off-the-shelf corrector
ships with a general dictionary.

**Edit distance 2 buys nothing.** Identical recovery, wider coverage, lower
accuracy — it finds more candidates and chooses among them worse. Edit-1 is the
right radius, which is worth knowing because the wider search is the more
expensive one.

**The best method is wrong nearly as often as it is right.** Accuracy 0.548 when
it answers. A correction stage placed before concept matching would introduce
roughly one wrong word for every one it repaired, and the wrong ones are not
harmless: a corrected token that lands on a *different* real clinical term
produces a confident wrong concept where the uncorrected token would have
produced none.

## The decision

**Stage 4 is empty, and lexical variation is handled implicitly by the
approximate matching in stage 5.** That tolerance *is* the normalization, applied
at lookup rather than as a rewrite — which also preserves the architectural
invariant that nothing rewrites note text, since every offset in this package is
an offset into the note as written.

The decision is recorded as **subsumed**, not **missing**, because those are
different claims and only one is true.

## What we give up, stated rather than implied

**The asymmetry stays.** Insertions survive and deletions do not. For a package
whose purpose is injecting controlled perturbations, that is a confound it owns:
part of any measured degradation under `input.typo` is the matcher's own
brittleness rather than a downstream model's. `typo_sensitivity.json` quantifies
it per severity *and per mode*, because the four character operations are not
interchangeable and a single "typo rate" would hide exactly this.

**The estimator that reports the baseline is itself imperfect**, and was
validated rather than assumed. The Document Quality Profile's misspelling count
and `input.typo` are dual — one estimates, the other injects at measured dose —
so injection-recovery applies. It gives **slope 0.7401 with R² 1.0** against a
release gate of [0.90, 1.10]: it **fails**, missing a consistent 26%.

The shape is what makes it usable. R² of 1.0 means the under-count is systematic,
not noisy, so the estimator ranks notes reliably and must not be read as an
absolute count. Three mechanisms explain the loss and none is fixable by tuning:
a typo can land on another real word and stay recognized, it can produce a token
that occurs elsewhere and so is not a hapax, and the four-character minimum
excludes short words by design. No calibration factor is applied, because 0.74
fitted on one corpus is a property of that corpus.

## What would change the decision

Stated so it can be revisited on evidence rather than re-argued:

- **A corpus with heavier derivational variation** than discharge summaries —
  pathology or radiology narrative, or a non-English source where inflection
  carries more.
- **A dictated or typed corpus** with a materially higher error rate, where the
  53% recovery would act on a larger base.
- **A corrector that abstains well.** The abstaining variant already reaches
  0.744 accuracy at 0.580 coverage; a confidence signal good enough to keep that
  accuracy at higher coverage would change the arithmetic, and the
  accuracy–coverage curve is how it would be judged.
- **A neural matcher at stage 5.** The whole argument rests on n-gram matching
  being brittle in a particular direction. A contextual model would redistribute
  that brittleness and the measurement would have to be redone.
