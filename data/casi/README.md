# CASI — UMN Clinical Abbreviation Sense Inventory, never committed

**What.** 37,500 sense-annotated abbreviation instances (75 short forms) over de-identified
clinical notes: evaluation gold for the abbreviation resolver
(`validation/record/abbreviation-resolver-spec.md`, sections 2.1 and 4). Derived table: `casi_gold.tsv`.
**Get it.** University of Minnesota Digital Conservancy, "Clinical Abbreviation Sense
Inventory" (Moon, Pakhomov, Melton), handle 11299/137703. Download the anonymised dataset here
by hand; nothing in the repository fetches it.
**Build.** No builder exists yet; the spec defines the `casi_gold.tsv` columns.
**Licence.** No attached open licence and it contains note text, so it is treated exactly like
MIMIC.
**Needed by.** The abbreviation-resolver evaluation only. Nothing in `src/` reads it.
**Never commit.** Denied by `data/*/*`; only this file is tracked.
