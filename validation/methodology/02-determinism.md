# Determinism and reproducibility

The central claim: **corrupted text and edit scripts are byte-identical across
runs, platforms, Python versions and institutions.** Everything else in the
package depends on this being true rather than approximately true.

## Seed derivation

Selection is driven by a BLAKE2b hash over content-derived material:

```
SPEC ‖ salt ‖ note_uid ‖ note_sha256 ‖ op_id ‖ op_version ‖ params ‖ scope ‖ stage ‖ unit_kind ‖ unit_id
```

Absent **by construction**: timestamp, worker id, batch index, note ordinal,
Python's `hash()`, and set iteration order. Four properties fall out free:

- corrupting one note is identical to corrupting a corpus of 1,388
- adding an operator leaves every other operator's edits untouched
- `-j1` and `-j8` produce identical output
- a second institution reproduces the first institution's bytes

## Severity is excluded from the seed

Deliberate, and it is a methodological choice with a trade-off that belongs in
the methods section rather than buried in code.

Because severity is not seed material, the selected set **nests**:
`selected(0.10) ⊆ selected(0.30) ⊆ selected(0.50)`. A dose-response curve
therefore becomes a within-note paired comparison with far lower variance than
independent draws would give.

The cost: severity levels are not independent samples. Variance across the
ladder is understated, so **`salt` replicates are required** to estimate it.
Reporting a dose-response curve without replicates would understate uncertainty.

## Hash-ranking, not `random.sample`

Selection ranks units by hash and takes the top `k`. CPython's sampling
algorithms are implementation details that have changed across versions, so
`random.sample` with a fixed seed is not a cross-version guarantee. Hash-ranking
is.

## No floats on any control-flow path

`0.1 + 0.2 != 0.3`, and `repr(float)` has changed across CPython releases.
Therefore:

- severities are `Fraction`/`Decimal` parsed from **quoted** literals
- the YAML loader **rejects** a severity that parsed as a YAML float
- `k` is exact integer arithmetic over the eligible count
- rates serialize as `(numerator, denominator)` integer pairs, never as floats

An AST lint enforces the absence of `hash()`, set iteration and `\s`/`\w` in
determinism-sensitive regexes.

## Scope of the claim, stated honestly

Corrupted text and the run artifact are byte-identical. The store writes JSONL
(`dose.jsonl`, `edits.jsonl`) plus a sorted-key `manifest.json` precisely because
columnar containers such as Parquet are *not* byte-reproducible — compression
metadata and thread counts leak in. Per-record SHA-256 makes content verifiable
regardless of container. Over-claiming here is what a reviewer catches.

## Verification levels

| Level | Check |
|---|---|
| 0 | Golden fixtures with checked-in SHA-256 |
| 1 | Re-run identity across `PYTHONHASHSEED=0` and `=1` |
| 2 | Subset invariance — one note ≡ its row in a full run |
| 3 | Append-only independence — adding an operator changes nothing else |
| 4 | Nestedness — `sel(.10) ⊆ sel(.30) ⊆ sel(.50)` |
| 5 | Alignment round-trip — `dst_to_src(src_to_dst(i)) == i` |
| 6 | Protection invariants — no partial edit into a HARD span |
| 7 | Job-count invariance — `-j1 ≡ -j8` |
| 8 | Contract invariants — κ across corpus × all severities |

Eight of nine run in CI today; level 7 is not applicable until parallel
execution exists, and is reported as such rather than as passing.

## Why this enables the publishable artifact

1.2 GB of corrupted MIMIC notes cannot be redistributed under the PhysioNet
data use agreement. **Edit scripts, dose tables and hashes can**, because they
contain only offsets and short replacement strings. Determinism is what makes
that substitution lossless: `robustehr replay --run <run>/ --corpus <your own
copy>` reproduces every byte and checks each recorded `output_sha256`.
