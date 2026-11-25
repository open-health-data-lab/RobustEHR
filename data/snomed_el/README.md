# SNOMED CT Entity Linking Challenge — PhysioNet credentialed, never committed

**What.** 272 MIMIC-IV discharge notes with 75,491 expert SNOMED CT annotations: the primary
anchor for targeting precision and concept recall (`src/robustehr/eval/snomed_el.py`).
**Get it.** https://physionet.org/content/snomed-ct-entity-challenge/ (credentialed account and
data use agreement). Place `train_notes.csv` and `train_annotations.csv` here.
**Derived files.** `concept_tui.json` (SNOMED code → TUIs): `robustehr eval crosswalk --root
data/snomed_el --umls data/umls`. `cui_snomed.json` (CUI ↔ SNOMED codes) is read by
`concepts/structural.py`, `concepts/phenotype.py`, `eval/phenotype.py` and `metrics/ambiguity.py`,
but NO script in this repository produces it yet: derive it from MRCONSO rows with
`SAB='SNOMEDCT_US'` (CUI, CODE) until a builder is added.
**Licence.** PhysioNet Credentialed Health Data Use Agreement (MIMIC-derived).
**Needed by.** `eval snomed`, every `--crosswalk` option, phenotype targeting, and the
abbreviation/ambiguity validation scripts. Not needed by the core install.
**Never commit.** Denied by `data/*/*`; only this file is tracked.
