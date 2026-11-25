# Development record

Everything in this folder was written while the component it describes was being
built, and reads as a history: what was measured first, what that overturned, and
what replaced it. It is kept so that every decision in the package can be audited
back to the measurement that made it. Nothing here is cited by the manuscript; the
method as it stands is in [`validation/methodology/`](../methodology/) and the
artifacts it rests on in [`validation/measurements/`](../measurements/).

| Document | What it records |
|---|---|
| [`methodology/10-abbreviation-expansion.md`](methodology/10-abbreviation-expansion.md) | How the abbreviation stage was chosen: the ceiling gate, the baselines, and why a cascade became a lookup table |
| [`methodology/11-lexical-normalization.md`](methodology/11-lexical-normalization.md) | Two normalization instruments measured and not included |
| [`methodology/12-context-qualification.md`](methodology/12-context-qualification.md) | The assertion stage: stability, correctness, the segmenter, and the gold that was built |
| [`methodology/13-phenotype-concept-sets.md`](methodology/13-phenotype-concept-sets.md) | The disorder facet: seed → closure, and what set recall alone would have shipped |
| [`methodology/14-phenotype-concept-association.md`](methodology/14-phenotype-concept-association.md) | The facets no relation reaches: proposal, grounding, vetting, the evidence closure |
| [`methodology/16-phenotype-surface-anchoring.md`](methodology/16-phenotype-surface-anchoring.md) | Why a concept set cannot carry the organism or the qualifier, and the surface warrant that does |
| [`abbreviation-resolver-spec.md`](abbreviation-resolver-spec.md) | The build plan for a seven-rung resolver, gated before construction |
| [`protocol-stage3-gate.md`](protocol-stage3-gate.md) | The V0 gate measurement that redirected stage 3 |
| [`protocol-addenda.md`](protocol-addenda.md) | The closure pass and the surface warrant, as they were added to the protocol |
| [`measurements-chronicle.md`](measurements-chronicle.md) | The measurement artifacts narrated in the order they were taken, with every correction |
