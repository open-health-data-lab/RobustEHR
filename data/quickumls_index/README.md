# QuickUMLS index — built locally from UMLS, never committed

**What.** The simstring/unqlite index `robustehr.concepts.matcher.ConceptMatcher` loads to tag
concept mentions. Derived from licensed UMLS content.
**Build.** Needs QuickUMLS (`pip install -e ".[umls]"`) and an unpacked
release in `data/umls/` (see `../umls/README.md`), then:
    python -m quickumls.install -L -U -E ENG data/umls/2026AA/META data/quickumls_index
`data/quickumls_snomed/` is the same command over a MetamorphoSys subset restricted to
SNOMEDCT_US; only `validation/pipeline/scripts/benchmark_sweep.py` uses it.
**Licence.** Inherits the UMLS Metathesaurus License Agreement.
**Needed by.** Every `--index` option (`run`, `describe`, `compare` with `--phenotype` or
`pheno=` targets, `eval snomed`, `concepts classify/validate`) and most `validation/` scripts.
Not needed by the core install.
**Never commit.** Denied by `data/*/*`, `**/quickumls_index/`, `*.unqlite`, `*.db`.
