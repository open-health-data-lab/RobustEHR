# BioScope corpus — fetched, never committed

**What.** Negation and speculation scopes over biomedical abstracts and full papers; the only
free gold for the `uncertain` dimension. The clinical subcorpus is de-worded upstream and
unusable (the `fetch_bioscope.py` docstring explains why).
**Fetch.** No credentials:
    python validation/pipeline/scripts/fetch_bioscope.py     # default --dest data/bioscope
Writes `abstracts.xml`, `full_papers.xml`, `clinical_records_anon.xml`, `manifest.json`.
**Licence.** No LICENSE in the archive (rgai.inf.u-szeged.hu); treated like MIMIC: counts and
hashes ship, sentence text never does.
**Needed by.** `validation/pipeline/scripts/scope_accuracy.py` only.
**Never commit.** Denied by `data/*/*`; only this file is tracked.
