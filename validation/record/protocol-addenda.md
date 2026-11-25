> **Development record.** This document was written while the component it
> describes was being built and reads as a history. The method as it stands is
> in [`validation/methodology/`](../methodology/); nothing here is cited by the
> manuscript. Kept so every decision can be audited.

# Protocol §10 — the two addenda, as written

### Addendum to §10 — the closure pass (added after the evidence audit)

The manual evidence audit (`data/phenotype_review/evidence_audit.md`) found
the decisive surface of a phenotype call frequently grounding to a CUI one
relation outside the set — a brand where the ingredient is a member, a
sibling ("diastolic heart failure" beside the hfpef seed), a cross-branch
parent ("Neoplasm Metastasis" above the 1,080 site-specific disorder-facet
members). Because the
corruption experiment's treatment must hit the mention the call rides on,
the sets are closed over that neighborhood, in two layers with different
warrants:

1. **RxNorm identity closure — automatic.** Admitted medication ingredients
   expand to their `tradename_of`/`has_ingredient` CUIs (tier `identity`).
   The relation is identity-preserving and the ingredient's verdict already
   covers its forms; the expansion runs AFTER the vetting gate so a dropped
   ingredient drops its whole family.
2. **Hierarchy closure — candidates, vetted, strict-gated.**
   `validation/phenotype/scripts/phenotype_closure.py` generates the bounded one-hop neighborhood
   (corpus-blind; parents at any support, siblings need convergent support,
   umbrella parents capped, isolates individually declared and recorded).
   `phenotype_vet.py --facet closure` triages under a targeting-evidence
   criterion; clinician adjudication through the §10 review flow is REQUIRED
   before a manuscript run (`vetted_by: llm+clinician`). The built sets admit
   only candidates ∩ kept — with no verdict row, nothing is admitted, a
   deliberate deviation from the proposed facet's fallback, because closure
   candidates are raw graph output.

Misgroundings stay out by construction: the vet judges each candidate's own
preferred term, so "CHF"'s false grounding (Congenital Hepatic Fibrosis) can
never be "fixed" by set widening; `tests/test_phenotype_closure.py` freezes
that guarantee alongside the decisive-surface fixtures. The corpus enters
only at validation: the `near_miss` block of the coverage artifact reports
how prevalent one-relation-away mentions were and how much the closed set
captures.

### Addendum to §10 — the surface warrant (pass 5)

The closure addendum above closes the sets over the *identifier* neighbourhood:
a brand beside its ingredient, a sibling beside a seed, a cross-branch parent.
That repairs every case where the concept exists and the walk simply had not
reached it.

Two kinds of decisive string are not that case. *Clostridium difficile* is a
Bacterium and *metastatic* is a qualifier; neither has a subsumption path to the
disorder it names, because the relations that connect them — `causative_agent_of`,
and for a qualifier no relation at all — are not the edges a closure walks.
Widening the neighbourhood does not reach them at any hop count, and a facet
filter keeping disorders correctly drops them on sight. They are nonetheless how
the two diagnoses are usually written, and for the heart-failure pair the
qualifier *is* the distinction between the phenotypes.

**Pass 5 — surface anchors, proposed then reviewed.**
`validation/phenotype/scripts/phenotype_anchors.py` asks a model for the forms a
clinician writes to mean each diagnosis, and writes them as candidates. A review
pass decides which ship; both passes are named in the resource header. A span
matching a declared anchor is evidence whatever the matcher grounded it to, or
whether it grounded it at all — which also reaches abbreviations no earlier
stage can, since the cue lexicon replaces a concept on a span already found and
cannot create one.

The same resource declares **stop surfaces**: strings that are refused as
evidence however they grounded, because they are ordinary language in a
non-clinical sense. That is a decision about a string rather than about a
concept, so it belongs here and not in vetting, which judges the concept and
finds nothing wrong with it.

The pass is gated like the others: `vetted_by` reads `llm` until a clinician has
read the review sheet end to end, and every result naming a `pheno=` target
reports which state it ran under. The barrier is lower here than for a concept
set — an anchor list is roughly a dozen forms per phenotype and can be read in a
sitting — and the consequence of an error is more direct, since an anchor
corrupts characters wherever it matches with no grounding step in between.

Anchors ship readable while concept sets ship as identifiers with hashed
surfaces. The difference is licensing and not policy: an anchor list is
author-written English derived from no vocabulary, so the Metathesaurus
agreement does not reach it, and a reader cannot check an anchor set they cannot
see.
