# NegEx test set (Chapman) — fetched, never committed

**What.** `Annotations-1-120.txt`: concept-level Affirmed/Negated assertions over 120
University of Pittsburgh reports of six types (2,365 rows scored), plus `negex_triggers.txt`.
The correctness gold for the negation dimension (`validation/pipeline/assertion-benchmarks.md`).
**Fetch.** No credentials:
    python validation/pipeline/scripts/fetch_negex.py        # default --dest data/negex
Writes the two files and `manifest.json` (SHA-256 per file, no timestamp).
**Licence.** None attached upstream (github.com/chapmanbe/negex), so the house rule applies:
treat exactly like MIMIC. Aggregates and hashes may ship; sentences may not.
**Needed by.** `validation/pipeline/scripts/assertion_accuracy.py` only.
**Never commit.** Denied by `data/*/*`; only this file is tracked.
