# Building a phenotype target, end to end

Everything needed to take a phenotype from a SNOMED seed to a target a
perturbation can aim at, in the order it runs, with what each stage can and
cannot fix. Adding a phenotype means declaring a seed and running this; nothing
here is specific to the phenotypes that happen to ship.

The method is described in
[methodology 17](../methodology/17-phenotype-association-method.md) (the method
stated once) and, for how each part was decided, the development record's
chapters [13](../record/methodology/13-phenotype-concept-sets.md),
[14](../record/methodology/14-phenotype-concept-association.md) and
[16](../record/methodology/16-phenotype-surface-anchoring.md) (the surface
warrant). This file is the operational companion: what to run, in what order,
and what each artifact is for.

## The shape of it

A target admits a span of text on either of two warrants.

**Concept space.** The span's concept is in the phenotype's set. The set is
built by traversing UMLS relations from a seed, extended with terms a model
proposes and a lookup grounds. It reaches everything the terminology connects.

**Surface space.** The span matches a declared string. This reaches what the
terminology does not connect — an organism has no subsumption path to the
disease it causes, a qualifier has none to the disease it qualifies, and a term
a clinician writes may have no UMLS string at all.

Neither is sufficient. The first misses `Clostridium difficile` and
`metastatic`; the second cannot generalise beyond what was written down. The
pipeline builds both and the audit measures the union.

## Stages

Every stage is idempotent and every one writes an artifact. LLM stages cache on
`(model, prompt)`, so a re-run with the cache present is offline and free.

```
                    ┌─ 1 closure ────┐
  seeds ────────────┤                ├─ 3 vet ─ 4 reconcile ─┐
                    └─ 2 propose ────┘                       ├─ concept set
                                    └─ 7 ungrounded ─┐       │
                                                     ├─ surface set
                    5 anchors ─ 6 review ────────────┘
                                                             │
                    8 specificity ─ 9 gap audit ─ 10 measure ┘
```

### 1. Closure candidates — `phenotype_closure.py`

Deterministic. Walks one hop from every member of the expanded set and emits
candidates with their hop kind, support and reaching members.

*Reaches:* anything connected by `isa` or `MTH RN`.
*Cannot reach:* organisms, qualifiers, and anything whose relation to the
phenotype is not subsumption. No parameter fixes this; stage 5 does.

### 2. Term proposal — `phenotype_propose.py`

A model proposes clinical terms per facet; each is grounded to a CUI by lookup
against the local release. Supplies the facets no relation reaches — symptom,
finding, procedure, laboratory.

Five facets: `diagnosis`, `symptom`, `finding`, `procedure`, `lab_result`. The
first asks what else this condition is called, which every other facet's prompt
forbids — and which the hierarchy is assumed to supply, for phenotypes where it
does not. `alcohol_use_disorder` ships on SNOMED's *Harmful pattern of use of
alcohol* while the record still says `alcohol dependence`, and before this facet
existed neither warrant reached the older names.

*Reaches:* terms that exist as UMLS strings.
*Cannot reach:* terms that do not. Those are kept as `terms_unmatched` and
recovered at stage 7.

**Do not lower `--wanted`.** It was 25 and that was the binding constraint on
recall: a ceiling cannot tell a model running out of real terms from one running
out of room, and only the first is a fact about the phenotype. Two passes
downstream exist to remove what does not belong.

### 3. Vetting — `phenotype_vet.py`

A model judges each candidate against its phenotype. Precision-biased by
construction: asked "does this belong", a model drops what it cannot justify.

Use `--revet` when the criterion changes. The incremental path only asks about
concepts never seen, so editing the criterion is otherwise a no-op.

### 4. Reconciliation — `phenotype_reconcile.py`

The counterweight, and the stage most easily left out by mistake. A stronger
model revisits the **drops only**, under a recall-biased criterion, and a keep
here overrides a drop. Nothing kept is revisited, so this stage cannot lower
recall.

Two passes with opposite biases, both recorded, is auditable in a way one pass
with a tuned threshold is not: each override names the model and the reason, so
a reader judges the disagreement rather than the tuning.

Drops whose stated reason already cites breadth or wrong kind are not re-asked.
Re-litigating `Ferricyanides` wastes a request and invites a stronger model to
argue its way back to it.

### 5. Surface anchors — `phenotype_anchors.py`

A model lists the ways the diagnosis is *written*. These become evidence
whatever the matcher grounds them to, or whether it grounds them at all.

The prompt insists on elliptical forms, and the insistence is load-bearing.
Asked plainly, a model returns `clostridioides difficile infection` and not
`c. diff` — the textbook phrasings rather than what notes contain, which is
precisely backwards for this purpose.

### 6. Anchor review — study-side

Anchors are directly actionable: they corrupt characters wherever they match,
with no grounding step to catch an error. So they are reviewed before shipping,
and the review is **recall-biased like stage 4, not precision-biased like stage
3**. Drop a form only where it has an established different clinical meaning a
reader could plausibly intend — `ra` is room air as often as rheumatoid
arthritis, and the cue lexicon exists to resolve exactly that. Do not drop a
form for being partial or informal. `lupus`, `mets` and `rheumatoid` are what
clinicians type.

A first pass reviewed on the precision criterion and dropped all three. The gap
audit found the cost immediately: `history of lupus` and `active lupus flare`
became unreachable because `lupus` had been judged incomplete.

The review sheet lists every decision with its reason. The resource's
`vetted_by` is `llm` until an author has curated forms by hand (`llm+hand`, the
shipped state) or a clinician has read the sheet end to end (`llm+clinician`),
and every run manifest that targets a phenotype records which state it ran
under.

### 7. Ungrounded recovery — `phenotype_ungrounded.py`

Deterministic. Promotes stage 2's `terms_unmatched` into the anchor resource at
tier `associated`.

These are not model noise. They are `omental caking`, `pericolic fat stranding`,
`positive hepatojugular reflux`, and — for the phenotype whose definition it
is — `preserved left ventricular ejection fraction`. They failed to ground
because no UMLS string matches them, which is a fact about the vocabulary rather
than a verdict on the term, and a pipeline ending in a CUI had nowhere to put
them.

Only ungrounded terms are promoted. A grounded term is already in the set
through its CUI, and adding its surface too counts one piece of evidence twice.

### 8. Specificity screen — `phenotype_specificity.py`

Counts how many unrelated phenotype families each associative concept spans.
**Reported, not applied.** Under a per-token-capped dose at rate 1.00 every
eligible span gets exactly one edit, so a broad set costs the diagnosis no
coverage; what it costs is knowing which span was the diagnosis, and
`Evidence.tier` answers that without deleting anything. Pass `--out` into the
resources directory to apply it, and expect to justify the removal against a
reach measurement.

### 9. Gap audit — `phenotype_gap_audit.py`

The only stage that can find what all the others missed. Takes a term list
written **outside** the pipeline and reports, per term, which warrant caught it
or that none did.

A list derived from the sets can only confirm what the sets hold, so the input
must be independent: a different model, a different question, and written before
the result is known. A study supplies its own, because which terms a clinician
writes is a property of a corpus and a specialty that this package has not
measured.

### 10. Measurement — the rest

`phenotype_set_audit.py`, `phenotype_runtime_sets.py`, `phenotype_link_audit.py`,
`phenotype_corpus_coverage.py`, `phenotype_eval.py`. Run after any stage above
changes a set, in that order. `phenotype_runtime_sets.py` in particular is
gated by a test that fails when the published sizes and a fresh build disagree.

## Running it

From a checkout with `data/` populated. Every LLM stage needs
`OPENROUTER_API_KEY`; none ships a default model.

```bash
python validation/phenotype/scripts/phenotype_closure.py
ROBUSTEHR_LLM_MODEL=<cheap>  python validation/phenotype/scripts/phenotype_propose.py
ROBUSTEHR_LLM_MODEL=<cheap>  python validation/phenotype/scripts/phenotype_vet.py --facet proposed
ROBUSTEHR_LLM_MODEL=<cheap>  python validation/phenotype/scripts/phenotype_vet.py --facet closure
ROBUSTEHR_LLM_MODEL=<strong> python validation/phenotype/scripts/phenotype_reconcile.py --facet closure
ROBUSTEHR_LLM_MODEL=<cheap>  python validation/phenotype/scripts/phenotype_anchors.py
# stage 6: review the anchors, study-side
python validation/phenotype/scripts/phenotype_ungrounded.py
python validation/phenotype/scripts/phenotype_specificity.py
python validation/phenotype/scripts/phenotype_gap_audit.py --terms <your_terms.tsv>
```

Then stage 10, then
`pytest tests/test_phenotype_links.py tests/test_phenotype_vetting.py tests/test_phenotype_closure.py tests/test_phenotype_anchors.py`.

## What still has no stage

**The numeric channel.** `lvef 25%`, `bmi 35 kg/m2`, `fasting glucose 168
mg/dl`, `sbp persistently > 160`. A phenotype assignment carried by a value and
a unit is reachable by neither warrant: there is no concept for the number and
no fixed string to anchor. The gap audit reports these as gaps and that is the
honest state. They are a large share of what remains unreachable, and closing
them needs a different instrument from anything here.

**Compositional phrases.** `biopsy confirms metastatic adenocarcinoma`,
`symmetric inflammatory polyarthritis`. The head is recognisable and the whole
phrase is not, so whether they are caught depends on the matcher's span
resolution rather than on the sets.

**Transfer.** Every term list in the pipeline reflects how a diagnosis is
written in the literature a model was trained on. Whether that matches a given
corpus is what the gap audit measures and nothing here assumes.
