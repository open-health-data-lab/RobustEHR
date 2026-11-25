> **Development record.** This document was written while the component it
> describes was being built and reads as a history. The method as it stands is
> in [`validation/methodology/`](../../methodology/); nothing here is cited by the
> manuscript. Kept so every decision can be audited.

# Surface anchoring: the third direction, and why two were not enough

Chapters 13 and 14 build a phenotype's target in **concept space**. A SNOMED
seed is expanded through `isa`, a model proposes terms that are then grounded to
CUIs, and both paths end in the same place: a set of identifiers, and a
membership test against what the matcher grounded each span to.

Everything this package then does with that target operates in **surface
space** — characters in a note. A perturbation edits text; a protection registry
withholds text; the dose ledger counts characters. The two spaces are related by
the matcher, and the matcher is not a bijection.

This chapter is the third direction: declaring the surface forms that *are* a
diagnosis, and admitting a span as evidence when it matches one, whatever
identifier the matcher gave it. It also covers the inverse — refusing a matched
surface that is an ordinary word in the wrong sense — because both are decisions
about strings rather than about concepts, and they belong at the same layer.

## 1. Two gaps that no closure can close

The case for a third direction is not that the closure was built carelessly. It
is that two specific kinds of decisive string are unreachable from a disorder
set **by the structure of the terminology**, at any hop count, under any support
threshold.

**The causative organism.** *Clostridium difficile* is a Bacterium, semantic
type T007. *Clostridioides difficile infection* is a disorder. There is no `isa`
path between an organism and the disease it causes — the relation that connects
them is `causative_agent_of`, which is not a subsumption edge and is not in the
hierarchy the closure walks. A facet filter that keeps disorders drops the
organism on sight, and correctly so: it is not a disease. It is, however, how
the diagnosis is usually written.

**The qualifier.** *Metastatic* is a qualifier, semantic type T080, not a
neoplasm. So are *systolic*, *diastolic*, *reduced* and *preserved*. In the two
heart-failure phenotypes the qualifier is the entire distinction between them —
a note saying "heart failure" is silent about which, and the word that resolves
it is the one no disorder walk returns.

Neither concept is rejected during vetting. Neither is ever *generated*, so
there is nothing to reject. Raising `--min-support`, widening `--max-fanout` or
adding hops moves none of them, because the edges do not exist to traverse.

A third kind of gap sits one stage earlier, in the matcher rather than in the
closure. An abbreviation that produces no candidate cannot be repaired by
anything downstream: chapter 10's cue lexicon *replaces* the concept on a span
the matcher already returned, and the structural expander of
`lab_shorthand.yaml` is scoped to labelled-value and exam-label slots. Neither
can create a mention in running prose. A surface anchor can, because it does not
consult the matcher at all.

## 2. What an anchor is

A literal surface form, matched case-insensitively against note text with
explicit word boundaries. Nothing more.

```yaml
clostridioides_difficile:
  anchors: ['c. diff', 'c.diff', 'cdiff', 'clostridium difficile',
            'clostridioides difficile', 'pseudomembranous colitis']
```

Three properties follow, and each is a deliberate limit:

**An anchor grounds nothing.** It produces an `Evidence` record with an empty
CUI and tier `anchor`. It is a claim that these characters are the diagnosis,
not a claim about which concept they denote, and the package makes no attempt to
convert one into the other.

**An anchor is not a repair for a misgrounding.** `CHF` grounding to *Congenital
Hepatic Fibrosis* remains a matcher error, pinned out of every set by the
negative fixtures chapter 14 §7 describes. Widening a set to cover an
abbreviation error hides the fault; matching the surface exactly does not,
because the anchor matches `chf` and says nothing about what `chf` resolves to.

**Where both warrants cover the same characters, the concept wins.** An anchor
span is emitted only where no concept-derived evidence for that phenotype
already overlaps it. Two warrants over one piece of evidence is one piece of
evidence, and counting it twice would inflate the denominator of every coverage
measurement built on the layer. This is also why a phenotype whose closure
already covers its diagnosis shows very few anchor spans: for those phenotypes
the layer is correctly inert.

**Anchors ship in the clear, and concept sets do not.** The package ships
identifiers with hashed surfaces because Metathesaurus strings are licensed.
That restriction does not reach text this project wrote. An anchor list is
author-written English, contains no CUIs, and is not derived from any
vocabulary, so it ships readable — which it must, since a reader cannot check an
anchor set they cannot see.

## 3. Stop surfaces: the same layer, the opposite direction

A concept can be correctly in a set, correctly matched, and still not be
evidence — because the *string* it matched is ordinary language in a
non-clinical sense. `status` is a legitimate surface for an in-set concept and
occurs in "volume status", "activity status" and "status post". `secondary`
occurs in "secondary to hypoperfusion".

This is not a vetting failure. Vetting judges concepts, and the concept is fine.
It is a matcher-layer fact about a surface, and it belongs here.

Two mechanisms, because one does not cover the class:

**A declared list**, global and per-phenotype. Required for surfaces carrying a
high-precision clinical semantic type — `secondary`, `ice`, `doe` — because
those are *subtracted* from the general-English vocabulary by construction
(chapter 6), so no derivation from that list can reach them. They have to be
named. The list is kept short on purpose: a long one is evidence that the
vetting criterion is too loose and the concepts should be leaving the set
instead.

**A general-English floor**, so a phenotype added tomorrow is protected before
anyone curates it. A single-token surface that appears in
`resources/general_english.txt` is refused unless the phenotype anchors it. That
list has already had words carrying a high-precision clinical type removed, so
`aspirin`, `fever`, `pain` and `wound` survive the floor — which is exactly what
makes it safe to apply to every phenotype at once. An unsubtracted vocabulary
would refuse half the medication facet.

Multi-token surfaces are never refused by the floor. `chest pain` in a
hypertension set is a real concept, correctly matched, that is an association
rather than a cue; that is a closure-precision problem and tightening the
vetting criterion is where it belongs. Refusing it here would be this layer
silently editing the concept set, which is not its job.

An explicit anchor outranks every refusal, so a phenotype whose diagnosis
happens to be an ordinary English word — `obesity`, `depression` — is never
made unreachable by its own floor.

## 4. Evidence carries its tier

Before this chapter, `Evidence` recorded a span, a phenotype and a CUI. The
facet that admitted the concept was computed at build time, reported as a count
in `Phenotype.facet_sizes`, and then discarded: the runtime test was flat set
membership, so by the time anything downstream saw an evidence record, whether
it arrived as the disease itself or as a lateral neighbour was gone.

`Evidence.tier` carries it — a facet name, or `anchor`. Two consequences:

**Targeting does not change.** `pheno=X` admits every tier exactly as before and
`canon()` is unchanged, so stored edit scripts reparse, severity seeds are
untouched, and a run predating this chapter reproduces byte-identically. The
tier is reported, never filtered on.

**Coverage becomes divisible.** `PhenotypeIndex.declared_by_tier` and
`touched_by_tier` share a denominator, so a caller can state what share of a
phenotype's *diagnosis* a perturbation reached rather than only what share of
its declared evidence. Those are different numbers, and a method that could
report only the second was reporting the one that is easier to make large.

The field is the last on the dataclass, because every caller constructs an
`Evidence` positionally and a field inserted before `assertion` silently rebinds
it to a tier string. That is not hypothetical; it happened while this was being
written, and `tests/test_phenotype_anchors.py::TestEvidenceContract` is the
regression that names why.

## 5. Provenance, and what it is worth

Anchors are proposed by a language model and reviewed before they ship. Both
passes are recorded in the resource header, with the model named, and the
`vetted_by` field carries the same three states the concept sets use: `llm`,
`llm+clinician`, or absent.

The distinction matters more here than for a concept set, because an anchor is
*directly* actionable — it corrupts characters wherever it matches, with no
grounding step in between to catch an error. An anchor set is also small enough
to be read end to end, roughly a dozen forms per phenotype, so the barrier to
clinician review is low and there is correspondingly little excuse for skipping
it. Until a reviewer has signed, the header reads `llm` and
`validation/protocol.md` §10 requires any result leaning on a `pheno=` target to
say so.

## 6. Terms that do not ground, and the tier for them

The propose-then-ground direction of chapter 14 asks a model for the terms a
clinician associates with a phenotype and resolves each against the release by
string lookup. 1,334 of 1,831 resolved. The other 413 were recorded as the
method's error bar and discarded.

Reading them says otherwise. They are `omental caking`, `pericolic fat
stranding`, `ring-enhancing brain lesions`, `positive hepatojugular reflux`,
`accordion sign`, `fruity breath odor` — and, for the phenotype whose entire
definition it is, `preserved left ventricular ejection fraction`. Every one is a
finding a clinician would write. They failed because no UMLS string matches
them, which is a property of the vocabulary and not a verdict on the term, and a
pipeline that ends in a CUI had nowhere to put a true term that has none.

The surface warrant has somewhere to put them. `phenotype_ungrounded.py`
promotes them into this resource at tier `associated`: evidence for the
phenotype, not its name. The tier is not cosmetic — reach is measured over
diagnosis-bearing tiers only, so an arm that corrupted every associated finding
while leaving the diagnosis intact still reports as unaimed, which is the
confusion the tier exists to prevent.

Only ungrounded terms are promoted. A grounded term is already in the set
through its CUI, where the matcher's normalisation and the identity closure both
reach it; adding its surface as well would count one piece of evidence twice.

## 7. Reviewing anchors is not reviewing concepts

Both are LLM passes over a candidate list and the resemblance ends there. The
vetting pass of chapter 14 asks "does this concept belong" and is right to be
conservative: a wrongly admitted concept widens a set that already has
precision problems, and the candidate pool is mostly graph noise.

An anchor list is neither. Its candidates were generated *for* this purpose,
so there is no noise to filter, and the cost of the two errors is reversed. A
form wrongly kept costs some off-target matching. A form wrongly dropped makes
the diagnosis invisible wherever it is written that way — and the forms most
likely to be dropped for looking incomplete are exactly the ones a hurried
clinician types.

This was measured rather than reasoned about. A first review used the vetting
criterion and dropped `lupus`, `mets` and `rheumatoid` as partial. The gap audit
(§8) found the cost the same day: `history of lupus` and `active lupus flare`
became unreachable, because the only thing in them that could have matched was
the word that had just been judged incomplete.

So the anchor review drops a form only where it carries an established
*different* clinical meaning a reader could plausibly intend — `ra` is room air
as often as rheumatoid arthritis, and chapter 10's cue lexicon exists to resolve
that case properly. Being partial, informal or elliptical is not grounds.

## 8. The audit that can find what the rest cannot

Every list in the pipeline was written for it, so none can measure it. The
concept sets are the thing under test; the anchors were proposed to pass; the
associated terms were recovered into it. An audit built from any of them
confirms only that the target contains what it contains.

`phenotype_gap_audit.py` takes a term list from outside and reports, for each
term, which warrant caught it or that none did. The input has to be independent
on three axes — a model that built none of the resources, a question framed
differently from the one the anchors answer, and written before the result is
known — and it is supplied by the study rather than shipped, because which terms
a clinician writes is a property of a corpus and a specialty that this package
has not measured.

What it finds is not only a number. The gaps cluster, and the clusters name the
instruments that are missing: values and units (`lvef 25%`, `bmi 35 kg/m2`),
laboratory assertions (`anti-ccp positive`), and compositional phrases whose
head is recognisable but whose whole is not. None of those is addressed by a
wider concept set or a longer anchor list, which is exactly what makes the audit
worth running.

## 9. Limitations

- **Recall is bounded by what was proposed.** The review pass only removes; it
  cannot add a form nobody thought of. A diagnosis written in a way the proposer
  did not anticipate is still unreachable, and the gap audit is the only thing
  that will show it.
- **The numeric channel remains outside both warrants.** A phenotype assignment
  carried by a value and a unit has no concept to match and no fixed string to
  anchor. It is a large share of what the gap audit reports as unreachable, and
  closing it needs an instrument this chapter does not describe.
- **Anchors are exact strings, so a misspelling in the source text is missed.**
  This is deliberate — a fuzzy anchor would match the wrong diagnosis, and the
  failure would be invisible — but it means a corpus with poor transcription
  quality gets less from the layer than a clean one.
- **The floor is a vocabulary threshold, not a sense disambiguator.** It refuses
  ordinary single tokens wholesale rather than asking which sense was meant.
  Where a phenotype genuinely needs such a token, the anchor list is the
  override, and using it is a declaration a reader can check.
- **An anchor set is corpus-shaped whether or not it was built from a corpus.**
  The forms a proposer lists reflect how the diagnosis is written in the
  literature it was trained on. Transfer to a corpus with different local
  conventions is an assumption, and the per-phenotype coverage table is where it
  is tested.
- **Nothing here reaches the numeric channel.** Ejection-fraction percentages,
  BMI values and assay-positivity statements carry phenotype assignments that
  neither a CUI nor a surface form addresses. Chapter 14 §8 says the same, and
  this layer does not change it.
