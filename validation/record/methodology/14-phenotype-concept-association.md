> **Development record.** This document was written while the component it
> describes was being built and reads as a history. The method as it stands is
> in [`validation/methodology/`](../../methodology/); nothing here is cited by the
> manuscript. Kept so every decision can be audited.

# Building phenotype–concept associations: two directions, and what each costs

Targeting a perturbation at "the heart-failure content of this note" needs a
list of concepts that count as heart failure. Chapter 13 describes one way to
build it — a SNOMED seed expanded through `isa` — and that way is sound and
incomplete. This chapter is the concept-space method, the measurements that
decided it, and the parts that are not deterministic and say so.

> **This chapter used to say it was the full method. It is not.** Both
> directions below end in a set of identifiers, and a perturbation aimed at that
> set operates on characters. Two kinds of decisive string — the causative
> organism and the qualifying adjective — are unreachable from a disorder set at
> any hop count, because the edges that connect them are not subsumption edges.
> A third direction, declaring the surface forms that *are* the diagnosis, is
> [chapter 16](16-phenotype-surface-anchoring.md). Read this chapter as what
> concept space can deliver, and that one as what it cannot.

The resulting counts are in
[validation/phenotype/phenotype-concept-table.md](../phenotype/phenotype-concept-table.md).

## 1. Why one direction is not enough

A phenotype's concept set is built **outward from a seed** by traversing UMLS
relations. That works for two facets and fails completely for four, and the
failure is a property of the terminology rather than of the traversal.

| facet | source | works? |
|---|---|---|
| disorder | `SNOMEDCT_US isa` ∪ `MTH RN` descendant closure | yes |
| medication | `MED-RT may_treat` / `may_prevent`, 15,352 edges | yes |
| symptom, finding | — | **no relation exists** |
| procedure, laboratory | — | **no relation exists** |

This was measured, not assumed. Asked for the findings of *Heart failure*
(C0018801), UMLS offers:

* `has_associated_finding` (SNOMEDCT_US) → *H/O: heart failure*, *Family history
  of heart failure*, *Heart failure excluded* — assertion variants of the
  disease itself, not its symptoms;
* `has_manifestation` (OMIM) → *3-Methylglutaconic Aciduria Type V*,
  *Arrhythmogenic Right Ventricular Dysplasia* — the inverse relation, and
  genetic diseases at that;
* `cause_of` (SNOMEDCT_US) → two complications.

Nothing anywhere returns dyspnoea, oedema or orthopnoea. Before the second
direction existed, the `procedure` column held **one concept across all 22
phenotypes**.

## 2. The second direction: propose, then ground

A clinician does not *derive* "echocardiogram belongs to heart failure" from a
relation. They know it. So the second half of the method asks for that knowledge
and then anchors it:

```
propose  ──►  ground  ──►  expand  ──►  vet  ──►  freeze
```

**The model proposes strings, never identifiers.** Asked for CUIs a model
returns confident, well-formed, wrong ones — `C0018801` is memorable enough to
be hallucinated. Asked for clinical *terms* it answers from what it knows, and
the identifier is then resolved by exact lookup against the local release. Every
identifier that ships came from UMLS.

**Grounding rate is the feasibility measurement.** Of 1,831 terms proposed
across 22 phenotypes × 4 categories, **1,334 ground (72.9%)**.

| | symptom | finding | procedure | laboratory |
|---|---|---|---|---|
| heart_failure | 23/24 | 14/19 | 17/20 | 22/25 |
| hypertension | 21/21 | 15/20 | 14/24 | 17/22 |
| clostridioides_difficile | 19/21 | 11/21 | 12/18 | 14/14 |

The 413 ungrounded terms are **listed in the clear** in
`resources/phenotype_proposals.yaml`, precisely because they are *not* in UMLS
and so are model output rather than vocabulary content: *bibasilar crackles*,
*accordion sign*, *pericolic fat stranding*, *colonic wall thickening*. These
are real radiology and examination phrases the terminology does not carry as
single concepts, and they are the method's error bar. A grounded term is by
definition a UMLS string and ships as `surface_sha256`.

### 2.1 The proposed category is a hint, not a gate

The first implementation required a term proposed as a `symptom` to carry T184.
It scored **8/24** on heart failure — and the rejects were *peripheral edema*,
*paroxysmal nocturnal dyspnea*, *jugular venous distension*. All three are
correct; UMLS types them T033 Finding. The mirror case appeared in the same run:
*abdominal tenderness* and *rebound tenderness*, proposed as findings, are typed
T184.

The T184/T033 boundary is not one clinical knowledge tracks, and UMLS applies it
inconsistently. The gate was measuring itself. Grounding into any clinical type
and assigning by the type the concept turns out to have took the same run from
**61.7% to 81.5%** on the pilot pair.

The disagreement is now reported rather than discarded — 701 of 1,334 concepts
land in a different category from the one they were proposed under:

| drift | n |
|---|---:|
| `lab_result → procedure` | 338 |
| `symptom → finding` | 144 |
| `symptom → disease` | 112 |
| `finding → disease` | 76 |

`lab_result → procedure` is the largest and is structural: UMLS types an analyte
as T059 Laboratory Procedure, which the assignment order gives to `procedure`.

## 3. Vetting, scoped to what we inferred

Generation produces candidates, and one of them is instructive.
`clostridioides_difficile` has no MED-RT treatment edge, so its medication facet
lifts one `isa` step and returns **ciprofloxacin** — a drug that *causes*
C. difficile. The relation is real, the traversal correct, the answer clinically
wrong. No structural rule catches that.

But vetting all 1,746 medication candidates with a model would be a rubber
stamp. Two deterministic reductions come first:

**Ingredient collapse.** 100 of hypertension's 241 candidates are RxNorm precise
ingredients — *amlodipine besylate* and *amlodipine benzoate* beside
*amlodipine*. A verdict is taken once per ingredient and inherited by its salt
forms, which stay in the set so a note writing the salt still matches. 1,746 →
1,030 decisions.

**Provenance.** MED-RT is a curated NLM terminology, so a drug it links to the
phenotype's *own seed* is its assertion; re-judging that with a cheap model
substitutes weaker evidence for stronger. Only our inference is reviewed:

| tier | the edge starts at | n |
|---|---|---:|
| `seed` | the phenotype's own seed — MED-RT's claim | 447 |
| `closure` | a descendant of the seed — our expansion | 228 |
| `lift` | an ancestor of the seed — our escalation | 294 |

**556 concepts reviewed rather than 1,746**, and the scope is phenotype
dependent in the way that matters: `type_2_diabetes` needed no review at all,
`hfpef` all 63, `metastatic_cancer` all 166.

The acid test passed — ciprofloxacin was dropped, *"known cause of C diff"* —
and the model also made its own error, dropping **diuretics from HFrEF** as "not
routinely used". Its other HFpEF/HFrEF distinctions were sound (ACE inhibitors,
digoxin, inotropes and nitrates kept for HFrEF, dropped for HFpEF). The schema
records `vetted_by: llm` and keeps that distinct from a clinician's name,
because the two support different claims. **No set here is clinician-signed.**

`validation/phenotype/scripts/phenotype_export_review.py` writes `data/phenotype_review/<name>.tsv`
for that review: term in the clear beside its identifier, facet, source and
provenance tier. It refuses to write outside `data/`, and decisions return as
CUI lists, so the round trip is licence-safe in both directions.

## 4. Where the vocabulary is simply behind

SGLT2 inhibitors carry no `may_treat` edge to heart failure in 2026AA.
*Empagliflozin* was unreachable from any seed however the closure was walked —
the relation does not exist to traverse. `medication_seeds` names such concepts
by CUI. Inferring them instead would mean loosening the traversal until
something appeared, which is exactly how ciprofloxacin arrived.

## 5. Two measurements, two denominators

`measured_set_recall` scores the **disorder facet** against the SNOMED CT Entity
Linking Challenge test split. `measured_union_recall` scores what a `pheno=X`
target actually selects — every facet unioned. **The table below is the
2026-08-06 measurement, taken before the proposed-facet vetting gate and the
evidence closure (§6–§7)**; the union denominators it shows (hfpef 777,
hypertension 886) describe sets that no longer ship. The re-measured values
against the closed sets (2026-08-18) live in `phenotypes.yaml` and
`validation/measurements/phenotype_eval.json` — macro union recall moved 0.659 →
0.669, and the denominator moves with the set, so the two dates are not
comparable row by row.

**They are not comparable, and the second is not a better version of the
first.** The denominators differ by up to two orders of magnitude:

| phenotype | disorder n | R | union n | R |
|---|---:|---:|---:|---:|
| hfpef | 7 | 0.000 | 777 | 0.781 |
| clostridioides_difficile | 1 | — | 933 | 0.472 |
| hypertension | 197 | 0.817 | 886 | 0.731 |
| dementia | 15 | 0.867 | 61 | 0.541 |

HFpEF's 0.000 → 0.781 is *not* an improvement in finding heart failure with
preserved ejection fraction. It answers a different question over a much larger
evidence base. Union recall bounds **targeting coverage** — how much of the set
a corruption aimed at this phenotype can reach — which is what this package
does. It does not bound phenotype *identification*: recovering *sodium* or
*fatigue* is not evidence of C. difficile, and both are in that union.

Its one unambiguous benefit is that it exists at all for the three phenotypes
the corpus could not measure through their disorder facet
(`rheumatoid_arthritis` 2 spans → 372, `systemic_lupus_erythematosus` 1 → 374,
`clostridioides_difficile` 1 → 933).

**Union precision is not measurable here and is reported null.** Precision needs
an answer key independent of the set being scored, and the only one available is
the seed's SNOMEDCT_US `isa` closure — a *disease* closure, which no medication
or procedure concept can fall inside. Scored against it the union reads 0.000
for five phenotypes: that is the key being wrong for the set, not the set being
imprecise, and calling it a conservative bound would dress up a broken
measurement. The disorder facet remains the specificity anchor, and chapter 13
explains why that anchor needed inventing.

## 6. Vetting extended to every generated concept, and what the corpus shows

§3 scoped vetting to the inferred medication tiers, which left an asymmetry the
audit eventually made visible: the medication facet was generate→vet→gate while
the 1,204 proposed concepts entered every set wholesale. The same pass now
covers them (`validation/phenotype/scripts/phenotype_vet.py --facet proposed`), one decision per
CUI — nothing is seed-asserted, because everything is model-generated — under a
criterion per *assigned* facet whose shared acid test is the proposed-facet
analogue of ciprofloxacin: **a concept true of most hospitalized patients — a
CBC, a chest X-ray, fatigue — associates with every phenotype at once and
therefore with none.**

All 1,204 candidates were decided (zero undecided): **876 kept, 328 dropped
(27.2%)**. The cut landed where the criterion says it should — in the exclusive
partition the `procedure` column fell 292 → 213 (screening panels, routine
imaging), and hypertension keeps 3 procedures of the 26 proposed. One phenotype
paid a structural price: dropping 15 of `clostridioides_difficile`'s proposals
briefly took its set to 45, below the 50-concept floor; the closure layer
returned it to 189 the same day and the waiver was removed
(`tests/test_phenotype_links.py` records the episode in its comment).

The verdicts are load-bearing, not decorative: `build()` intersects the
proposed union with the kept set (`concepts/phenotype.py`), the audit and the
runtime artifact regenerate through the same gate, and
`tests/test_phenotype_vetting.py` asserts a dropped CUI is absent from the
built set. Runtime and declared columns of Table 2 now agree (hypertension
3,146/3,146 where they once read 361/1,074; verified equal for all 22
phenotypes).

**What the corpus instantiates**
(`validation/measurements/phenotype_corpus_coverage.json`, over the mention cache of
all 1,388 notes). Observed coverage of the declared sets runs 9%–62%, and the
three-column reading is the point: for hypertension, 517 of 609 concepts are
reachable by their own name, 103 are ever observed, and the 418
reachable-but-unseen are conditions ICU discharge summaries do not write — a
fact about the corpus, not the set. The 88 unreachable ones are the pipeline's
own gap. Evidence concentrates exactly as expected: 5–29 concepts carry 90% of
any phenotype's mentions, while `notes_with_any` stays high (0.965 for
hypertension) — broad sets, narrow heads.

**The enrichment screen, and what it is not.** For labelled phenotypes, each
observed concept's note-rate in the label-positive cohort against the rest:
median enrichment is above 1 for every phenotype (1.29 pulmonary embolism to
21.7 metastatic cancer), and the flagged tail is precisely the shared-symptom
concepts a clinician would predict — chest pain, dyspnea, headache, nausea,
fatigue. Labels are per-admission and ICU notes co-report comorbidities, so
this is a **review queue, not a precision measurement**; §5's null stands.

## 7. The evidence closure: the same concept under a different identifier

A manual audit of 14 note-phenotype pairs (its detail lives with the review
material, since it quotes notes) found that where the sets failed to cover the
phenotype call's decision basis, the failure was usually not a missing
concept but a missing *identifier*: the matcher grounded the decisive surface
to a CUI one relation outside the set. "Lasix" grounds to the brand CUI while
the ingredient is a member; "diastolic heart failure" grounds to a sibling of
the hfpef seed; "metastasis" — written in 831 of 1,388 corpus notes — grounds
to a concept with **no `isa` edge in any source vocabulary**, above the 1,080
site-specific disorder-facet members. For a corruption experiment whose treatment is
"corrupt the phenotype's concepts", every such miss leaves the decision basis
intact and biases the result toward an uninterpretable null.

That diagnosis was right about the audited cases and incomplete as a general
account. A missing identifier is recoverable, because the concept exists and the
walk can be widened to reach it. A missing **surface** is not: where the
decisive string denotes an organism or a qualifier rather than a disorder, no
widening of a disorder hierarchy returns it, and the two layers below cannot
either. That residue is [chapter 16](16-phenotype-surface-anchoring.md).

The fix for the identifier half is the standard value-set curation loop, applied
uniformly and corpus-blind, in two layers with different warrants:

**RxNorm identity closure, automatic.** Every admitted medication ingredient
carries its `tradename_of` and `has_ingredient` CUIs (98,601 edges from 4,764
`tty=IN` ingredients in the local release), at provenance tier `identity`,
expanded AFTER the vetting gate so a rejected ingredient drops its whole
family. The relation is identity-preserving, and the vetting prompt already
asserted the policy for salt and ester forms; brands and products are the
same policy one relation wider. Identity variants are reported as their own
tier in every audit, because they multiply counts (12,921 of the 18,074-CUI
union) without multiplying decisions.

**Hierarchy closure, vetted and strict-gated.** `validation/phenotype/scripts/phenotype_closure.py`
generates the bounded one-hop neighborhood of each set over the isa+MTH-RN
graph: parents from every member at any support (a parent generalizes its
child by construction — that is how "Metastatic Renal Cell Cancer" arrives
above a single member), siblings only from the disorder top region and the
small declared facets and only with support from two or more members, umbrella
parents (>100 children) never expanded through, and the two hierarchy
isolates the audit surfaced ("diastolic congestive heart failure", "Gastric
Bypass") declared individually — a declaration adds a candidate, never a
member. Each bound was set by measurement, not taste: unrestricted sibling
expansion produced 72k candidates of deep-leaf noise; the shipped rules
produce 13,846. The model triaged all of them under a targeting-evidence
criterion — *would a clinician reading this term take it as evidence FOR this
phenotype* — and kept **994 (7.2%)**, between 6 and 104 per phenotype; 11
unparseable verdicts were excluded, never admitted. The built sets admit only
candidates that carry a keep verdict: with no verdict row nothing is
admitted, a deliberate inversion of the proposed facet's fallback, because
closure candidates are raw graph output. Clinician adjudication through the
standard review export is required before the sets claim
`vetted_by: llm+clinician`.

**The causal probe.** Whether a model's call actually rides on the recovered
evidence — as opposed to on an EF number, a lab value, or contextual prose that
concept-targeted corruption never touches — is not a property of the concept sets
and cannot be settled here. It needs a model, a protocol and a corpus, and the
answer is specific to all three. It is measured downstream, against the MIPA
protocol, and reported with that experiment rather than in this chapter.

What matters for the sets themselves is that the question became *askable*. Before
the closure, corrupting everything the pre-closure target could reach left the
recovered evidence untouched, so a null result would have been uninterpretable —
indistinguishable from a target that simply missed what it was aiming at.

**What the closure measurably changed.** All twelve decisive surfaces from
the audit now fall inside their target sets, frozen as regression fixtures
(`tests/test_phenotype_closure.py`), while the audit's two misgroundings —
"CHF" grounding to *Congenital Hepatic Fibrosis*, "DM Type II" to *Split cord
malformation type II* — are pinned OUT of every set by negative fixtures: an
abbreviation error must not be repaired by set widening. Self-name
reachability of the faceted sets rose to 0.60–0.97 across the panel
(0.71–0.94 for the audit-exposed four). Corpus-wide, **88–96% of
label-positive notes for the audit-exposed phenotypes contain at least one
mention of recovered evidence** — an adjudicated closure keep or an identity
variant the pre-closure target could not reach (hfpef 94%, hfref 96%,
metastatic cancer 91%, type 2 diabetes 92%, hypertension 88%); the coverage
artifact reports the full table and its caveats. The concept floor holds
again for every phenotype with no waiver.

## 8. Limitations

- **No set is clinician-reviewed yet.** Vetting is `vetted_by: llm`, and the
  model demonstrably errs (diuretics/HFrEF). The review surface is generated —
  `data/phenotype_review/*.tsv`, model drops sorted first with reasons — and
  `validation/phenotype/scripts/phenotype_review_ingest.py` folds verdicts back with a `reviewer`
  field and counts every override, which becomes this chapter's
  model-vs-clinician disagreement rate when the review lands.
- **The validation corpus is not MIMIC.** Recall transfers only as far as the
  challenge notes resemble the target corpus.
- **Union precision is unmeasured** (§5), so an over-broad facet would not be
  caught the way the pulmonary-embolism blow-up was. The enrichment screen
  (§6) queues suspicious concepts for review but is not a precision
  measurement and does not close this gap. The cross-phenotype specificity
  screen below bounds one corner of it and no more.
- **Per-concept vetting cannot see a concept's other memberships.** §6's acid
  test — a concept true of most hospitalized patients associates with every
  phenotype at once and therefore with none — is the right criterion applied
  where it cannot be evaluated: a model judging `fatigue` against depression
  does not know it has already been admitted to eleven other sets. Counted
  across the declared panel the property is measurable and needs no corpus.
  `validation/phenotype/scripts/phenotype_specificity.py` scores each
  associative concept by how many unrelated phenotype *families* it spans,
  grouped so that related phenotypes are not penalised for the overlap they
  exist to express, and collapsed to the ingredient so that one admitted drug
  is not counted once per dose form.

  The threshold is set high, and the height is a division of labour rather than
  a tuning choice. At five families a term is what sick inpatients have and the
  removal is beyond argument; lower thresholds sweep in judgements about how
  much a cardiovascular agent narrows the field, which belong to the vetting
  criterion where a model can weigh them concept by concept. The full ladder
  ships in `validation/measurements/phenotype_specificity.json`. The disorder
  facet is never screened, since a concept cannot be too unspecific to be
  itself, and neither is anything declared by hand — `medication_seeds` exists
  precisely because no edge existed to infer from, and an automatic screen
  overriding it would delete the curation the declaration was for.

  **The screen is reported and not applied.** It was built on the argument that
  a character spent on `fatigue` is one not spent on the diagnosis, and that
  argument holds for a rate-limited dose rather than for a saturating one: at
  rate 1.00 with a per-token cap, every eligible span receives exactly one edit,
  so a broader set costs the diagnosis no coverage at all. What a broad set
  costs is knowing which spans the corruption hit, and `Evidence.tier` (chapter
  16) answers that per span without removing anything. A concept deleted here is
  invisible to every later analysis; one kept and labelled can be conditioned
  on. Where recall is the binding constraint — and §7 says it is, since the
  decisive strings were mostly never *generated* rather than wrongly kept —
  measuring is the better instrument. The flagged list ships beside the ladder
  so a study that wants the narrower set can apply it and say so.
- **Grounding is exact-match on a blunt normaliser** — lowercase, punctuation
  stripped. A looser one would raise the 72.9% by matching things that are not
  the same concept, which is the one error this pipeline cannot detect
  downstream: a wrongly grounded term looks exactly like a correct one.
- **The proposal step is not deterministic at generation time.** It is cached and
  frozen to identifiers, so every *downstream* run is reproducible from the
  artifact without a model, but re-running the proposal on a new release may
  return different terms.
- **Facet counts are floors, not ceilings**, and the ceiling that made them so
  has been raised. Proposals asked for 25 terms per category on the reasoning
  that a low limit keeps a model on common terms rather than padding with
  rarities. That is true of the terms a model adds last and says nothing about
  what it leaves out. Asked for 25 findings for alcohol use disorder it returned
  19, and the withdrawal syndrome — `delirium tremens`, `tongue fasciculations`,
  CIWA scoring, withdrawal seizures — was not among them; the gap audit scored
  that phenotype at 30% and its misses were almost entirely that omission.

  A ceiling cannot distinguish a model running out of real terms from one
  running out of room, and only the first is a fact about the phenotype. The
  limit is now 60 and settable, the prompt asks for completeness and forbids
  padding separately, and the two passes that remove what does not belong —
  vetting and the specificity screen — are downstream of it by design. The cost
  of asking for too many is a longer review; the cost of asking for too few was
  silent until something measured it.
- **The closure's bounds are measured choices, not theorems.** One hop,
  support ≥ 2 for siblings, fan-out ≤ 100 for parents: each was set by
  observing the candidate volume it produced, and a documentation variant two
  hops out is invisible to it. The two declared isolates show the mechanism's
  edge — and its honest repair path.
- **Identity variants include dead weight.** Many RxNorm product CUIs carry
  no non-suppressed English surface (faceted surface coverage runs 0.47–1.0
  per set), so they can never match and merely sit in the denominator. They
  are inert for targeting and reported as their own tier.
- **The numeric channel remains outside concept representation.** EF
  percentages, BMI, A1c and assay-positivity statements carry phenotype
  assignments no CUI set can reach; the evidence audit documents the cases,
  and no closure addresses them.
