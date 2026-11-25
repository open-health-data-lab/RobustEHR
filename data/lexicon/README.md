# Clinical lexicon and abbreviation tables — built from UMLS, never committed

**What.** `clinical_tokens.txt` (single-word clinical vocabulary with TUIs), `abbrev_snomed.tsv`
(SNOMED `ABBREV - full term` inventory), and the planned `abbrev_detect.tsv` /
`abbrev_senses_ds.tsv` from the Meta-Inventory of Medical Abbreviations
(`validation/record/abbreviation-resolver-spec.md`, section 4.1).
**Build.** Needs `pip install -e ".[terminology]"` and `data/umls/`:
    robustehr concepts build-lexicon --umls data/umls        # -> clinical_tokens.txt
    python validation/pipeline/scripts/build_abbrev_inventory.py --umls data/umls
The Meta-Inventory tables have no builder in the repository yet. Manifests (hashes only) live in
`validation/measurements/`.
**Licence.** UMLS strings (Metathesaurus License). Meta-Inventory: Zenodo record 4567594,
CC-BY 4.0, but 71.7% UMLS-LRABR-derived, so built locally and never redistributed.
**Needed by.** Every `--lexicon` option; `tests/test_lexical.py` skips without it. The CLI falls
back to its packaged general-English and morphology resources when this directory is empty.
**Never commit.** Denied by `data/*/*`; only this file is tracked.
