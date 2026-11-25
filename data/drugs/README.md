# DrugBank-derived drug tables — licensed, never committed

**What.** `drugs.csv` (generic names: `entity_id`, `drugbank_id`, `drug_name`) and
`drugs_commercial_name.csv` (brand names keyed on `entity_id`), plus the built
`drug_synonyms.json` that `src/robustehr/drugs.py` reads for `lexical.medication_rename`.
**Get it.** DrugBank (https://go.drugbank.com/), academic account; export the two CSVs with
the columns above. Nothing in the repository downloads them.
**Build.**
    python validation/pipeline/scripts/build_drug_synonyms.py
Known issue: the script resolves paths from `Path(__file__).parents[1]` (= `validation/pipeline/`)
and must be pointed at the repository root before it finds this directory.
**Licence.** DrugBank terms of use (academic, non-commercial). Only the manifest ships
(`validation/measurements/drug_synonyms.manifest.json`).
**Needed by.** `lexical.medication_rename` via `robustehr.drugs`; without the file the operator
reports zero eligible units rather than failing. Not needed otherwise.
**Never commit.** Denied by `data/*/*`; only this file is tracked.
