# Targeting

## Mechanisms are target-agnostic

A typo is a typo whether it lands on `the` or on `warfarin`; character deletion
does not know what it deleted. Every mechanism in the RENDER and INPUT channels
is like this, and it is not a weakness to be fixed — it is what makes them
reusable across experiments.

The contribution is therefore not the mechanisms. It is **selecting what gets
hit**, which makes targeting a composable specification rather than a flag on an
operator. One agnostic mechanism set serves many experiments:

| Question | Target |
|---|---|
| Does drug extraction survive dictation error? | `Categories("medication")` |
| Is the classifier reading the diagnosis... | `Categories("disease")` |
| ...or the surrounding text? | `Not(Categories("disease"))` |
| Is this effect just perturbation per se? | `Uncategorized()` — control |
| Does de-identification style matter? | `Structure(DEID_PLACEHOLDER)` |
| Where does the evidence live? | `AllOf(Categories("disease"), Section("hpi"))` |

## The dose denominator follows the target

"30% of medication mentions" and "30% of all tokens" are different experiments.
The denominator is the **target's** unit count, which is what the dose
accounting exists to keep straight.

## Two design decisions worth their cost

**Targets are span-based, not token-based.** Word-level lookup answers *token →
semantic types*; concept matching answers *span → concept → semantic types*.
Writing targets against tokens would mean rewriting every one of them when
concept matching lands. The resolution context is span-typed, so the matcher can
be swapped underneath without touching a single target.

**Canon strings are stable and order-independent.** Scope canon feeds the
BLAKE2b seed, so the canonical string is not cosmetic — changing it changes
which units are selected, which changes every stored edit script. Canon strings
are sorted and deduplicated so that logically identical targets are textually
identical, and a run with no target produces the canon it always did, so adding
targeting did not invalidate previously recorded edit scripts. A test asserts
this.

## What is deliberately absent

There is no *general-purpose* `clinical` target. The question is not answerable
from a word's intrinsic properties independent of context and use case, so what
replaces it for ordinary targeting is naming a category, or `Uncategorized` for
the complement.

`Uncategorized` admits nothing when no vocabulary is installed. Without one
every span is unclassifiable, and admitting them all would silently turn "we
could not look" into "we looked and found nothing" — the error that makes an
unmeasured run look like a measured one.

### The one exception, and why it is narrow

`ClinicalSalience` exists for concept-restricted corruption, and it is scoped
tightly enough not to reopen the question above. It is **not** a claim that a
word is clinical; it is a claim that, *in MIMIC-IV discharge summaries*, this
token falls inside a human-adjudicated clinical span at a measured rate. That is
an empirical statement about one corpus, with a number attached, and it is
validated against the SNOMED CT Entity Linking gold — precision 0.89 at
coverage 25%, against 0.50 at 46% for "any UMLS mention"
([validation-protocol §9](../protocol.md#9-clinical-targeting-for-concept-restricted-corruption)).

Three properties keep it honest, and they are the reason it does not become the
retired binary by another name:

- **It names its corpus.** The manifest records the lexicon digest and the
  benchmark it was measured on. Applied elsewhere it is unvalidated, and the
  manifest says so.
- **It is a union of four clauses, not a classifier.** Salience covers what the
  benchmark annotates well; a curated drug vocabulary and a structural
  labelled-value test cover what it demonstrably does not (medications at 27.2%
  gold coverage, analytes inconsistently). Each clause exists because a
  measurement showed the previous rule failing.
- **It does not replace the category axis.** `Categories("medication")` is still
  how a user asks for drugs. `ClinicalSalience` answers a different question —
  "what is the clinical content of this note" — and only for the corpus it was
  measured on.

Notably, filtering on semantic category cannot do this job: **100% of the
mentions our matcher returns already carry a `clinical_any` category**, because
the matcher's TUI whitelist applies that filter upstream. The category axis has
no discriminating power left at the mention level, which is why a separate
mechanism was needed at all.

## The lexical axis

`Lexical("function_word")` is a tighter control condition than `Uncategorized`,
because it selects grammar rather than "whatever the terminology missed" — and
unlike every semantic target it needs no terminology installed at all.

The two axes are orthogonal, and their overlap is the informative part:

| | in a category | no category |
|---|---|---|
| **out_of_vocabulary** | `warfarin`, `dyspnea`, `mrsa` — strongest evidence | `anastamosis` — likely misspelling |
| **general_english** | `home`, `take`, `new` — the suspect zone | `please` — plain prose |
| **function_word** | *(empty by construction)* | `the`, `and`, `was` |

Collapsing that into a single "non-clinical" bucket is what the old
clinical/non-clinical binary did, and it is why the binary was retired.
