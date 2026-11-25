> **Development record.** This document was written while the component it
> describes was being built and reads as a history. The method as it stands is
> in [`validation/methodology/`](../../methodology/); nothing here is cited by the
> manuscript. Kept so every decision can be audited.

# Phenotype concept sets: deterministic association, and what it costs

> **Scope.** This chapter covers the **disorder facet** — a SNOMED seed expanded
> through `isa` — which is where the method started and where its specificity
> measurement lives. A phenotype's SHIPPED set now also carries medications
> (with their RxNorm brand and product variants at the `identity` tier),
> vetted LLM-proposed symptoms, findings, procedures and laboratory concepts
> — four facet categories no relation can reach — and a vetted one-hop
> evidence closure, so the shipped hypertension set is 3,146 CUIs where this
> chapter's disorder facet is 361. Every number in this chapter is the
> disorder facet only. See
> [14-phenotype-concept-association](14-phenotype-concept-association.md) for the
> full method and [validation/phenotype/phenotype-concept-table.md](../phenotype/phenotype-concept-table.md)
> for the resulting counts.

Targeting a perturbation at *one phenotype* requires an answer to a question the
rest of the pipeline never asks: **which concepts count as evidence for
hypertension?** This chapter records how that association is built, how each set
is validated before it ships, and — since several of them are poor — what the
poor ones mean for a result computed with them.

> **Concepts are one of two warrants, not the only one.** Everything in this
> chapter tests membership by identifier. A perturbation aimed at the result
> operates on characters, and some decisive strings — an organism, a
> qualifier — have no subsumption path to the disorder they name, so no set
> built this way can contain them. Declared surface forms are the second
> warrant; see [chapter 16](16-phenotype-surface-anchoring.md). Where this
> chapter says "membership", read "membership by identifier".

The claim is deliberately narrow. This is not concept *normalisation* and not a
phenotyping algorithm: it does not decide whether a patient *has* the condition,
only whether a span of text is *about* it. Cohort identification needs
assertion, temporality, and usually structured data; a corruption operator needs
only to know which tokens to aim at.

## 1. Declaration and expansion

A phenotype is declared as a handful of **seed SNOMED CT concepts** and expanded
to their descendant closure. Nobody can enumerate every way a note says "chronic
kidney disease"; everybody can name the root.

```yaml
- name: dementia
  seeds: ["52448006"]        # Dementia
  cohorts: [mipa]
  measured_set_recall: 0.867
  measured_set_precision: 0.929
  gold_evidence_spans: 15
```

Expansion runs over **`SNOMEDCT_US isa` ∪ `MTH RN`**, bounded to depth 6. The
second edge set is load-bearing and easy to miss: `C0011847` (*Diabetes*) has no
`isa` edge in any source vocabulary, so without `MTH RN` every mention our
matcher resolves to it is unreachable from a SNOMED seed. The union across *all*
source vocabularies was measured and rejected — it triples the mean closure and
claims *fewer* gold spans, while making two clinically distinct phenotypes share
evidence.

Membership is tested in **both identifier systems**: our matcher emits CUIs and
the gold carries SNOMED codes, so materialising only one would score a namespace
round trip as a matcher error. And a seed code may carry more than one CUI —
`84114007` (Heart failure) carries both the concept with the descendants and a
childless duplicate, so taking the first collapses the phenotype to one element.
Every CUI a seed carries is a seed.

## 2. Two measurements, and why one alone is not enough

Each set is scored against the **SNOMED CT Entity Linking Challenge** test split
(68 notes, 23,131 expert-annotated spans). Gold spans whose annotated concept
falls in the closure are that phenotype's evidence *as an expert marked it* —
which is what makes this a real measurement without anyone annotating a
phenotype corpus.

| measure | question | what it bounds |
|---|---|---|
| **span recall** | did we find the text at all? | what an operator can reach |
| **set recall** | …and assign a concept inside the set? | whether `protect` is correct |
| **set precision** | of what we claimed, how much an expert agreed? | whether the set means its name |

**Set recall alone is not a safe criterion, and this is not hypothetical.**
Recall rises monotonically with closure size, so a set that swallows half the
terminology scores well on it. Seeding on *Pulmonary embolism* (59282003) at
depth 6 reaches *Vascular diseases* (C0042373) through a single `MTH RN` hop and
expands to **9,712 concepts**, posting set recall **0.669** — better than five of
the eight original phenotypes — while meaning nothing clinically.

The precision counterpart needs an **independent** answer key, and the obvious
one is circular. Scoring a claimed span correct when the annotated concept falls
in the *same* closure gave that 9,712-concept set a precision of **0.823**: a set
large enough to contain the concepts an annotator used for the spans it grabbed
becomes its own answer key. The key is therefore the seed's **`SNOMEDCT_US isa`
closure alone** — the single editorially coherent hierarchy, and the one the gold
is annotated in. `MTH RN` is what the set is being tested *for*, so it cannot
also do the testing. Against that key the blow-up scores **0.049**.

This is a lower bound by construction: the reference is the stricter hierarchy,
so a legitimately MTH-reached concept is scored against it. Read precision with
recall, never instead of it.

## 3. The depth bound

One bad edge poisons one seed and no other, so depth is a **per-phenotype**
setting where it needs to be. Pulmonary embolism:

| depth | concepts | set recall | set precision |
|---:|---:|---:|---:|
| 1 | 30 | 0.360 | **0.773** |
| 2 | 330 | 0.611 | 0.073 |
| 3 | 3,100 | 0.700 | 0.035 |
| 6 | 9,712 | 0.669 | 0.049 |

The bad edge is one hop out, and the phenotype ships bounded to depth 1. The
recall cost is real (0.67 → 0.36) and it buys a set that means what its name
says. A global depth cannot express this: lowering it for everyone would gut the
closures that are well behaved.

For the same reason DVT and PE are **two phenotypes**, not one — PE needs a bound
DVT does not. A study wanting both writes
`any(pheno=deep_vein_thrombosis;pheno=pulmonary_embolism)`.

## 4. The MIPA panel, measured

The fifteen MIPA-cohort phenotypes, on the split above. `n` is gold evidence
spans; `disorder-facet concepts` is this chapter's closure only — the shipped
sets are 2–10× larger after the later layers (see the scope note and
[validation/phenotype/phenotype-concept-table.md](../phenotype/phenotype-concept-table.md)).

| phenotype | seed | disorder-facet concepts | n | span R | set R | set P |
|---|---|---:|---:|---:|---:|---:|
| obesity | 414916001 | 99 | 19 | 1.000 | **1.000** | 0.760 |
| dementia | 52448006 | 280 | 15 | 1.000 | 0.867 | 0.929 |
| hypertension | 38341003 | 361 | 197 | 0.995 | 0.817 | 0.758 |
| deep_vein_thrombosis | 128053003 | 241 | 28 | 1.000 | 0.679 | 0.783 |
| type_1_diabetes | 46635009 | 36 | 8 | 0.625 | 0.625 | 0.625 |
| alcohol_use_disorder | 15167005 | 47 | 22 | 1.000 | 0.500 | 0.917 |
| metastatic_cancer | 128462008 | 1,080 | 54 | 0.982 | 0.463 | 0.926 |
| pulmonary_embolism | 59282003 † | 30 | 50 | 0.660 | 0.360 | 0.773 |
| type_2_diabetes | 44054006 | 41 | 54 | 0.778 | 0.222 | 0.667 |
| depression | 35489007 | 221 | 27 | 1.000 | 0.111 | 0.188 |
| hfpef | 446221000 | 8 | 7 | 0.714 | **0.000** | — |
| hfref | 703272007 | 8 | 4 | 0.000 | **0.000** | — |
| rheumatoid_arthritis | 69896004 | 257 | 2 | — | *null* | — |
| systemic_lupus_erythematosus | 55464009 | 38 | 1 | — | *null* | — |
| clostridioides_difficile | 186431008 | 10 | 1 | — | *null* | — |

† bounded to depth 1; see §3.

**A null recall is not a zero.** Three phenotypes have one or two gold spans in
this corpus — too few for a rate, and inventing one from n=1 would be worse than
declaring none. Their closures may work perfectly; nothing here establishes it.
A measured 0.000 is a different and much worse fact, and both appear above.

## 5. What the failures are, since three are instructive

**HFpEF and HFrEF fail differently, and the distinction is the diagnosis.**
HFpEF has span recall 0.714 — the text *is* found for 5 of 7 spans — and set
recall 0.000, so every one resolves to a concept outside the 8-concept closure:
this is concept assignment. HFrEF has span recall 0.000: the text is never found
at all. Both are the abbreviation-resolver gap, one stage apart. Their
declarations say DO NOT USE, and they stay declared so the failure is visible
rather than silently absent, and so they begin working when the resolver lands.

> These two are the clearest case for the second warrant, and the reason is
> structural rather than incidental. What separates HFpEF from HFrEF is
> *preserved* against *reduced*, and those are qualifiers — semantic type T080,
> with no subsumption path to any heart-failure disorder. No closure over a
> disorder hierarchy can contain the words that make the distinction, so no
> amount of set widening fixes these two. Declared surface forms can, and
> [chapter 16](16-phenotype-surface-anchoring.md) is where that is done. The
> numbers in §4 predate it.

**Type 2 diabetes at 0.222 is a specificity problem, not a matcher one.** Notes
write "diabetes"; annotators resolve it to type 2; the matcher returns a generic
diabetes concept that is *not* in the type-2 closure. Precision is 0.667, so what
it does claim is right. Adding the generic seed lifts recall to 0.397 and yields
exactly the 382-concept `diabetes_mellitus` set — it stops being type 2. The
choice is between a specific set that misses and a general set that is not the
phenotype, and it belongs to the study, not to us.

**Depression at 0.111 recall and 0.188 precision is weak in both directions,
which rules out the usual explanations.** Span recall is 1.000, so the text is
found every time; annotators mark depressive language with concepts outside the
*Depressive disorder* closure. Seeding *Major depressive disorder* instead scores
0.000 and adding it changes nothing, so the seed is not the problem. Any
depression result is unsupported until this is characterised.

## 6. Why the weak numbers are published rather than dropped

Two paths connect a concept set to a claim, and they fail differently.

Under **`phenotype_scope=protect`**, a mention the matcher never found is never
added to the protection registry, so an operator corrupts it — and the run still
reports `evidence_touch: 0`, because measurement and protection read the *same*
span set. A vacuous zero is indistinguishable from a real one. Set recall is
exactly what bounds that, which is why it travels in the definition file rather
than in a paper, and why a set below 0.6 (the flagging line §7 step 4 uses) should not be
used in protect mode.

Under **`target`**, low recall is a smaller problem: the operator perturbs less
evidence than intended, dose is under-delivered, and the direction of the error
is knowable.

So a phenotype's result is conditional on its measured recall in a way that is
not recoverable after the fact. Publishing 0.111 beside `depression` is not
candour for its own sake — it is the only thing that stops a null result being
read as robustness.

## 7. Adding a phenotype

The order matters: **measure, then declare**. Declaring first is how a set
ships with a recall nobody checked. (Steps 1–4 build and measure the disorder facet this chapter covers; steps
5–6 add the concept layers chapter 14 covers; step 7 the surface warrant of
chapter 16; steps 8–10 measure, audit and gate the result.)

1. **Find a seed.** `validation/phenotype/scripts/phenotype_link_audit.py` confirms a candidate code
   means what you think against your own release.
2. **Dry-run it**, before it exists in the definition file:
   ```bash
   python validation/phenotype/scripts/phenotype_eval.py --limit 300 --overlap length \
       --trim-affixes --prefer-snomed \
       --seed my_phenotype=12345678 --seed alternative=87654321
   ```
   Comparing candidates here is the point: `alcohol_use_disorder` ships on
   *Harmful pattern of use of alcohol* (47 concepts, R 0.500, P 0.917) rather
   than the broader *Alcohol use disorder* (80 concepts, R 0.419, P 0.733)
   because both were measured. The tighter set was also verified to already
   contain *Alcohol dependence* — adding that seed changes the closure by
   nothing — so it covers abuse and dependence as a comorbidity flag should.
3. **Check the closure did not blow up.** If precision is far below recall,
   sweep `--depth`; if a low depth is needed, declare `max_depth` and say why.
4. **Declare it** with both numbers, `gold_evidence_spans`, and a note if recall
   is below 0.6 or unmeasurable.
5. **Build the other facets.** `validation/phenotype/scripts/phenotype_propose.py` (LLM proposes
   terms, grounding against MRCONSO freezes CUIs), then
   `validation/phenotype/scripts/phenotype_vet.py --facet proposed`; `validation/phenotype/scripts/phenotype_closure.py`
   for the one-hop evidence-closure candidates, then
   `validation/phenotype/scripts/phenotype_vet.py --facet closure`. Medication identity variants
   attach automatically from `data/umls_facets.json`. Nothing un-vetted ships:
   the proposed facet is gated on its verdicts and the closure facet is
   strict-gated (no verdict row, nothing admitted).
6. **Reconcile the drops.** `validation/phenotype/scripts/phenotype_reconcile.py --facet closure`.
   Step 5 asks whether each concept belongs and is conservative when asked that
   way; this returns its rejections to a stronger model under the opposite bias,
   where a reinstatement overrides a rejection and nothing already accepted is
   revisited. Skipping it ships a set that is precise and under-sensitive, which
   is the error a corruption target can least afford.
7. **Build the surface warrant.** `validation/phenotype/scripts/phenotype_anchors.py` proposes the
   forms the diagnosis is *written* in; review them **recall-biased**, dropping
   only forms carrying an established different clinical meaning and never forms
   that are merely partial. Then
   `validation/phenotype/scripts/phenotype_ungrounded.py`, which recovers the
   terms step 5 proposed and could not ground — they are clinical findings with
   no vocabulary string, not model noise, and they enter at tier `associated`.
   See [16](16-phenotype-surface-anchoring.md); the whole method is
   [17](17-phenotype-association-method.md).
8. **Regenerate and re-measure.** `phenotype_set_audit.py`,
   `phenotype_runtime_sets.py`, `phenotype_link_audit.py --facets --full`,
   `phenotype_corpus_coverage.py`, and `phenotype_eval.py` for the union
   recall that travels back into the declaration.
9. **Audit against a list you did not build from.**
   `validation/phenotype/scripts/phenotype_gap_audit.py --terms <yours>`. Every
   other measurement here scores a set against itself; this one asks whether the
   target finds the terms a clinician writes, and it is the only step that can
   find what all the others missed. Read the gap clusters, not only the rate.
10. **Run the gates.** `pytest tests/test_phenotype_links.py
    tests/test_phenotype_vetting.py tests/test_phenotype_closure.py
    tests/test_phenotype_anchors.py` enforce the declaration shape, that
    verdicts gate the built sets, that the runtime-sets artifact matches a fresh
    build, and that the decisive-surface fixtures still pass on either warrant.
    `validation/phenotype/scripts/phenotype_link_audit.py` then checks the
    chain from declaration to text.

## 8. Limitations

- **The validation corpus is not MIMIC.** Set recall is measured on the SNOMED
  Entity Linking Challenge, and transfers only as far as its notes resemble the
  target corpus. Three MIPA conditions are effectively absent from it.
- **Set precision is a lower bound**, measured against the stricter hierarchy
  (§2). A concept legitimately reached through `MTH RN` counts against it.
- **Self-name reachability is not recall.** `validation/phenotype/scripts/phenotype_link_audit.py`
  reports whether the matcher can recover each concept from its own preferred
  term; it weights every concept equally, while real evidence is dominated by a
  few common ones. The two diverge in both directions — `chronic_kidney_disease`
  is 0.349 (bare disorder closure, `phenotype_link_audit.json`; the faceted-set audit is a different artifact) reachable and 0.889 recall, `heart_failure` 0.863 and 0.449 — so the
  audit answers "is this set wired up", never "will it find things".
- **No assertion filtering.** 30.1% of gold phenotype evidence is modified
  (negated, uncertain, historical, family). Assertion travels with the evidence
  for reporting and never decides eligibility — see chapter 12. For the two MIPA
  entries framed as history or complication, the assertion breakdown is the
  relevant reading, not the raw count.
- **Only identifiers ship.** `phenotypes.yaml` carries SNOMED codes and our own
  labels. No UMLS string is redistributed, so every closure is rebuilt from the
  reader's own licensed release.
