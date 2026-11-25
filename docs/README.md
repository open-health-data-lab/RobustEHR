# Docs

For someone using or extending the package. How the method was validated, and what
each number may claim, is in [`validation/`](../validation/).

| Document | What it answers |
|---|---|
| [`glossary.md`](glossary.md) | Every term the documentation uses, including the ones with more than one meaning, and how they map to the companion paper |
| [`run-artifact.md`](run-artifact.md) | Every field of the manifest, the dose record and the edit script, and what an edit script reveals about the notes |
| [`pipeline.md`](pipeline.md) | The flow a `robustehr run` takes, corpus in to replayable edit script out, with the module that owns each box |
| [`corruption-catalogue.md`](corruption-catalogue.md) | Every operator: level, channel, contract, what it simulates, what it preserves, how it is dosed |
| [`corruption-taxonomy-status.md`](corruption-taxonomy-status.md) | The source taxonomy's 29 rows reconciled against what is implemented, partial or not built |
| [`source-taxonomy.md`](source-taxonomy.md) | The a-priori corruption grid the package was designed against |
| [`nlp-hierarchy.md`](nlp-hierarchy.md) | The units of clinical text, character to document, and which module owns each level |
| [`categories.md`](categories.md) | The twelve semantic categories, their UMLS types and their evidence tier; why they overlap, and the one-per-word partition for tables |
| [`concept-matching-pipeline.md`](concept-matching-pipeline.md) | The nine stages from harmonisation to phenotype set membership, and what each is validated against |
| [`targeting-design.md`](targeting-design.md) | What a phenotype target is: set membership rather than linking, on two warrants |
| [`assertion-annotation-guideline.md`](assertion-annotation-guideline.md) | The guideline the assertion gold was annotated under |
