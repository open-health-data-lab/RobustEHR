# Taxonomy and the contract lattice

## The correction the taxonomy needed

The folk split is "phenotype-preserving" versus "phenotype-altering". It is
wrong as stated, and the reason is worth being precise about, because the
observation behind it is sound.

Preservation is generally a property of the **(operator, span, document,
phenotype)** tuple, not of the operator. A whitespace collapse is preserving
here and altering there depending on where it lands. But *some* operators can
never alter clinical reference, for any phenotype, in any document, because
their edits are confined to character classes carrying no clinical content.

Those are different **strengths of guarantee**, and the difference is
machine-verifiable rather than a matter of judgement.

## Six contracts, ordered by how the guarantee is discharged

| Contract | Guarantee | Discharged by | Failure is |
|---|---|---|---|
| `CONTROL_NULL` | output ≡ input | byte equality | a bug |
| `INVARIANT_BY_CONSTRUCTION` | no clinical reference can change, ever | **κ property test over corpus × all severities** | a bug |
| `CONDITIONALLY_PRESERVING` | preserving if the edit misses evidence | per-instance measurement | a reported rate |
| `REFERENCE_ALTERING_BY_DESIGN` | changing reference is the point | transition registry + expert audit | invalid-edit rate |
| `REFERENCE_UNCONSTRAINED` | no claim made | — | n/a |
| `CONTROL_DESTRUCTIVE` | must destroy performance | harness sanity check | a broken harness |

## What makes the strongest tier real

Each `INVARIANT_BY_CONSTRUCTION` operator declares a canonicalizer **κ** that
projects away exactly what the operator is permitted to touch. CI asserts

```
κ_op(apply(d)) == κ_op(d)
```

across the corpus at every severity. This is stronger than a declaration in a
table: it is a claim CI can falsify. An operator whose κ test fails on one note
is demoted to `CONDITIONALLY_PRESERVING` automatically — **the taxonomy
self-corrects.**

| Operator | κ projects away |
|---|---|
| `render.whitespace_collapse` | all inter-token whitespace |
| `render.deid_restyle` | de-id spans → a single sentinel token |
| `render.header_style` | header casing, colon form, inline/standalone position |

`CONDITIONALLY_PRESERVING` operators declare a weaker but still testable
semantic invariant: `lexical.numeral_to_word` must preserve the parsed value (it
refuses any numeral whose written form does not round-trip); `lexical.medication_rename`
the drug (generic ⇄ brand of the same ingredient, never a class-mate);
`render.header_rename` the canonical section id; `render.break_removal` every
content token (a break becomes one space, never nothing).

## The result that justifies the whole apparatus

`render.deid_restyle` is `INVARIANT_BY_CONSTRUCTION` — κ proves no clinical
reference can move. Holding a note fixed and varying **only** the
de-identification convention, medspaCy ConText flips its negation verdict on an
active, controlled diagnosis in **three of six conventions**, including MIMIC-IV's
`___` and MIMIC-III's `[** **]`.

The mechanism is visible in the sentence count: masked placeholders defeat
sentence segmentation, merging two list items, so a negation cue in item 1 takes
scope over the diagnosis in item 2. Two non-masked controls confirm the mask is
the cause rather than the list structure.

A perturbation that provably cannot change meaning changes the answer. That is
the thesis, demonstrated on a real, widely used tool. Reproduction:
`validation/pipeline/scripts/probe_deid_assertion.py`.

## Orthogonal modifiers, not operator classes

`target`, `phenotype_scope`, `section` and `protect` apply to **every** operator.
There is consequently no "phenotype-dependent operator" column in the taxonomy:
any operator becomes phenotype-targeted by configuring the run. The SEMANTIC and
FACTUAL channels additionally *require* the clinical layer to locate a cue or
value to rewrite — that is a dependency, not a taxonomic class.

This collapses the preserving/altering folk split into something measurable: an
operator × phenotype evidence-touch matrix, computable on any corpus, for any
user-defined phenotype, with no labels.

## Single source of truth

The taxonomy lives in one machine-readable file. From it are generated the CLI
listing, the documentation table, the paper's operator table, the property-test
parametrization, and the config schema's allowed values. A taxonomy change is a
single reviewable diff that cannot desynchronize, and a lockfile drift test
fails if the generated artifacts fall out of step.
