# Clinician phenotype review TSVs — contain UMLS strings, never committed

**What.** One `<phenotype>.tsv` per phenotype with the concept term in the clear beside its
CUI, facet, source (closure / med-rt / declared / proposed) and the model verdict, for a
licensed clinician to mark `y`/`n` in the keep column. Also `evidence_audit.md`, the manual
audit of which evidence a clinician's decision actually rested on.
**Build (export).** Needs `data/umls_isa_mth.json`, `data/umls_facets.json`, `data/snomed_el/`
and `data/umls/2026AA/META/MRCONSO.RRF`:
    python validation/phenotype/scripts/phenotype_export_review.py [--phenotype NAME ...]
**Ingest.** Verdicts go back as CUIs into `src/robustehr/resources/phenotype_vetting.yaml`:
    python validation/phenotype/scripts/phenotype_review_ingest.py --reviewer "<name>"
**Licence.** UMLS Metathesaurus License (terms in the clear). Only CUIs leave this directory.
**Needed by.** The vetting round trip in `validation/protocol.md` §10 and
`validation/protocol.md` §10. Nothing in `src/` reads it.
**Never commit.** Denied by `data/*/*`; only this file is tracked.
