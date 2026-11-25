# The phenotype–concept association method, stated once

How a phenotype becomes something a perturbation can aim at: what the object
is, how it is constructed, what each construction step can and cannot reach, and
what is left unreachable when they are all done. The measurements each decision
rests on are in the development record
([`validation/record/`](../record/)); this chapter is the method as it stands.

## 1. The object

A **phenotype target** is a rule that, given a clinical note, returns the spans
of text that constitute evidence for one phenotype.

It is not a phenotyping algorithm. It does not decide whether the patient has
the condition — that needs assertion, temporality and usually structured data.
It decides whether a span of text is *about* the condition, which is the
question a perturbation aimed at one phenotype has to answer before it can do
anything at all.

A target admits a span on either of two **warrants**:

$$
\text{evidence}(s, P) \iff \underbrace{\mathrm{cui}(s) \in C_P}_{\text{concept warrant}} \;\lor\; \underbrace{\mathrm{text}(s) \in S_P}_{\text{surface warrant}}
$$

where $C_P$ is the phenotype's concept set and $S_P$ its declared surface forms.
The two are independent constructions over different spaces, and the disjunction
is the whole design: each reaches evidence the other cannot.

Every admitted span records which warrant admitted it and at what **tier**, so
that coverage of the diagnosis is reportable separately from coverage of the
concepts merely associated with it.

## 2. Why one warrant is not enough

The concept warrant fails for a reason that is structural rather than
remediable. A concept set is built by traversing relations from a seed disorder,
and two kinds of decisive string have no such relation to traverse:

- **The causative organism.** *Clostridium difficile* is a Bacterium. The
  relation connecting it to *C. difficile infection* is `causative_agent_of`,
  which is not subsumption and is not in the hierarchy a closure walks. A facet
  filter keeping disorders correctly drops it — it is not a disease — and it is
  how the diagnosis is usually written.
- **The qualifier.** *Preserved* and *reduced* are qualifiers. In the
  heart-failure pair they carry the entire distinction between the two
  phenotypes, and no walk over a disorder hierarchy returns a qualifier.

Neither concept is rejected during vetting; neither is ever generated. Support
thresholds, fan-out bounds and hop counts are all irrelevant to them.

A third failure sits one stage earlier, in the matcher. An abbreviation that
produces no candidate cannot be repaired downstream: the cue lexicon replaces a
concept on a span already found, and the structural expander is scoped to
labelled-value slots. Neither can create a mention in prose.

The surface warrant addresses all three, because it consults no terminology.

## 3. Constructing the concept set $C_P$

Three sources, unioned, each gated.

**3.1 Relation traversal.** A SNOMED seed expanded through `isa` ∪ `MTH RN` to a
bounded depth gives the disorder facet. MED-RT `may_treat` and `may_prevent`
give medications; RxNorm identity relations expand an admitted ingredient to its
brands and dose forms. This reaches what the terminology connects and nothing
else — asked for the findings of heart failure it returns assertion variants of
heart failure, which is why 3.2 exists.

**3.2 Knowledge proposal, then grounding.** A model proposes clinical *terms*
per facet; each is resolved to a CUI by lookup against the local release. Terms
are asked for rather than identifiers, because a model asked for a CUI produces
well-formed wrong ones, and every identifier that results came from the
vocabulary rather than the model.

Grounding is the measurement and not a plumbing step: 1,334 of 1,831 terms
resolved. The 497 that did not are not discarded — see §4.3.

**3.3 The evidence closure.** A one-hop neighbourhood of the expanded set,
because a manual audit found the decisive surface frequently grounding to a CUI
one relation outside it. Strictly gated: raw graph output admitted unjudged
would put *Congenital Hepatic Fibrosis* one bad harvest from a heart-failure
set.

**3.4 Two gates with opposite biases.** Vetting asks, of each candidate, whether
it belongs; asked that way a model is conservative, and over 13,846 closure
candidates it dropped 12,841. Roughly two thirds of those drops cite breadth or
wrong kind and are correct. The remaining third is where a conservative pass
loses recall, so a **reconciliation pass** returns the drops to a stronger model
under the opposite bias, where a reinstatement overrides a rejection and nothing
already accepted is revisited. Both verdicts are recorded with the model that
made them, so the disagreement is auditable rather than tuned away.

Clinician overrides are recorded per concept and carry a reviewer field that
model verdicts never have.

## 4. Constructing the surface set $S_P$

**4.1 Diagnosis anchors.** A model lists the ways the diagnosis is *written*.
The prompt insists on elliptical forms, and the insistence is load-bearing:
asked plainly, a model returns `clostridioides difficile infection` and not
`c. diff` — textbook phrasings rather than what notes contain, which is exactly
backwards for this purpose.

**4.2 Anchor review, recall-biased.** Reviewing anchors is not reviewing
concepts. The candidates were generated for this purpose so there is no noise to
filter, and the cost of the two errors is reversed: a form wrongly kept costs
some off-target matching, a form wrongly dropped makes the diagnosis invisible
wherever it is written that way. A form is dropped only where it carries an
established *different* clinical meaning a reader could plausibly intend — `ra`
is room air as often as rheumatoid arthritis — never for being partial or
informal.

**4.3 Ungrounded terms.** The terms §3.2 could not resolve enter here. They are
not model noise: `omental caking`, `pericolic fat stranding`, `positive
hepatojugular reflux`, and, for the phenotype whose definition it is, `preserved
left ventricular ejection fraction`. They failed because no vocabulary string
matches them, which is a property of the vocabulary and not a verdict on the
term. A pipeline ending in an identifier had nowhere to put a true term with no
identifier; the surface warrant does. They enter at tier `associated`, never
`anchor`, so they support the diagnosis without being counted as it.

**4.4 Stop surfaces, the inverse.** A concept can be correctly in the set,
correctly matched, and still not be evidence, because the *string* it matched is
ordinary language in another sense. `status` matches "volume status";
`secondary` matches "secondary to hypoperfusion". This is a matcher-layer
judgement about a string, not a vetting judgement about a concept, so it belongs
with the surfaces. A declared list covers strings carrying a clinical semantic
type, which the general-English vocabulary subtracts by construction and no
derivation can reach; a general-English floor covers the rest, so a phenotype
added tomorrow is protected before anyone curates it.

## 5. Tiers

Every admitted span carries the warrant and facet that admitted it:

| tier | admitted by | meaning |
|---|---|---|
| `anchor` | surface | the diagnosis, as written |
| `disorder` | concept | the disease or a subtype |
| `medication` | concept | a drug treating or preventing it |
| `finding` | concept | a sign or symptom of it |
| `proposed` | concept | a term a model proposed, grounded |
| `closure` | concept | a one-hop neighbour of the set |
| `associated` | surface | a proposed term with no identifier |

Where both warrants cover the same characters the concept wins, and anchors are
matched before associated terms, so one piece of evidence is counted once and at
its strongest tier.

Tiers are **reported, never selected on**. A `pheno=X` target admits every
tier, so the tier reaches no seed and no target canon. What the tier buys is
that coverage becomes divisible: an arm reporting that it reached every declared
evidence span has said nothing about whether it reached the *diagnosis* until
the two are reported separately.

## 6. What the method cannot reach

Measured against a term list written by a model that built none of these
resources, asked a deliberately different question, and fixed before the result
was known. The residue is not a long tail of near-misses; it clusters, and the
clusters name missing instruments rather than missing entries.

- **Values and units.** `lvef 25%`, `bmi 35 kg/m2`, `fasting glucose 168 mg/dl`,
  `sbp persistently > 160`. A phenotype assignment carried by a number has no
  concept to match and no fixed string to declare. This is the largest cluster
  and it is a property of representing a phenotype as concepts and surfaces at
  all.
- **Laboratory assertions.** `anti-ccp positive`, `rf positive`. The analyte
  grounds; the assertion that makes it evidence does not.
- **Compositional phrases.** `biopsy confirms metastatic adenocarcinoma`. The
  head is recognisable and the whole is not, so whether these are caught depends
  on the matcher's span resolution rather than on either set.
- **Transfer.** Every term list reflects how a diagnosis is written in the
  literature a model was trained on. Whether that matches a given corpus is what
  the gap audit measures and what nothing here assumes.

## 7. What a result using this method must report

A run that targets a phenotype writes a `targeting` block into its manifest
(`robustehr.concepts.phenotype.targeting_manifest`), and a claim leaning on a
`pheno=` target reports it: the digest of every packaged targeting resource —
`phenotypes.yaml`, `phenotype_vetting.yaml`, `phenotype_closure.yaml`,
`phenotype_proposals.yaml`, `phenotype_anchors.yaml`, `phenotype_nonspecific.yaml`
— present or `absent`; a `targeting_digest` over the strings the anchor resource
admits and refuses, which ignores the review ledger so a provenance edit is not
read as a change of method; the review state of the anchors and of the vetting,
one of `llm`, `llm+hand` or `llm+clinician`; and the digests of the locally
built `umls_facets.json`, `isa` hierarchy and crosswalk. `absent` is a
reportable value, because a corpus built before a resource existed was built
under a different target. The claim also names the coverage artifact for the
corpus it ran on and the eval date behind any recall it quotes.

It also reports **reach by tier** rather than coverage of declared evidence
alone. The two differ, and the one that is easier to make large is not the one
that supports the claim.
