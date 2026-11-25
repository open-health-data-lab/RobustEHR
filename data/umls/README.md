# UMLS Metathesaurus 2026AA — local only, never committed

**What.** The UMLS release every terminology-derived artifact is built from: the clinical
lexicon, the QuickUMLS index, the `isa` edge list, the MED-RT/RxNorm facets, the SNOMED crosswalk.
**Get it.** https://uts.nlm.nih.gov/ (free UTS account; accept the licence). Download
`umls-2026AA-metathesaurus-full.zip` and unpack it here so that
`data/umls/2026AA/META/MRCONSO.RRF` exists. The code reads `<root>/<version>/META/`
(`robustehr.concepts.umls.UmlsRelease`), not the zip. Files read: MRCONSO, MRSTY, MRREL,
MRHIER, MRXNS_ENG, MRSAB, MRRANK. The `umls-2026AA-full.zip` bundle needs a MetamorphoSys
subset first; the metathesaurus-full download skips that step.
**Licence.** UMLS Metathesaurus License Agreement. Not redistributable.
**Needed by.** `robustehr concepts build-lexicon --umls data/umls`, `robustehr eval crosswalk`,
`validation/pipeline/scripts/build_abbrev_inventory.py`, and the derived JSON builds listed in
`../README.md`. The core install (describe / run / replay / compare) never touches it.
**Never commit.** Denied by `data/*/*`, `*.RRF`, `*.zip`, `**/umls/`; only this file is tracked.
