# Contributing

## The one rule that is not negotiable

**Never commit clinical text, and never commit licensed terminology.**

`data/` is gitignored by default-deny — everything is excluded and a short allowlist
re-admits `README.md`, `notes.sql`, and one `README.md` per placeholder directory by name
(`!data/<dir>/` plus the shared `data/*/*` / `!data/*/README.md` pair). New global
directory patterns belong in the belt-and-braces group *above* the `data/` block — git
applies the last matching rule, so a global `**/umls/` placed below the block would silently
re-exclude `data/umls/README.md`. That shape is deliberate: an allowlist of
*extensions* is one unanticipated file type away from leaking. If you add a publishable
file under `data/`, add it to the allowlist by name; do not loosen the rule.

The same applies to derived data. A corrupted MIMIC note is still MIMIC. A prediction store
keyed by `hadm_id` is still restricted. `run[0-9]*/`, `*.sqlite`, `results/` and `*.zip` are
ignored for that reason.

## Setup

```bash
uv venv
uv pip install -e ".[dev]"
uv pip install -e ".[terminology,clinical]"   # concept layer and assertion detection
```

Python 3.11+. The core has three dependencies and needs no clinical extras; most of the
operator suite runs without a terminology at all, which is a property worth preserving.

## Before you push

```bash
ruff check src tests validation
ruff format --check src tests validation
mypy src/robustehr
pytest
```

CI runs the same four across {ubuntu, macOS} × {3.11, 3.12, 3.13}, plus the suite three
times under `PYTHONHASHSEED=0/1/random`. That last job is not a formality — see below.

## Determinism is a hard constraint, enforced by a test

Every random choice must be a pure function of content. `tests/unit/test_determinism_lint.py`
bans, by AST, across the whole package:

- `hash()` and `id()` — they vary with `PYTHONHASHSEED` and process memory
- `import random` outside `robustehr.rng`
- `time` and `datetime` — **anywhere**, including for a progress line
- floats on any control-flow path
- unordered-set iteration

The exemption lists are empty apart from `rng.py`. Adding an entry is a claim that some part
of the engine may read a clock or an unseeded RNG, and there is no such part. If the lint
blocks you, the answer is almost always to remove the dependency rather than the ban.

Severities must nest: `selected(0.10) ⊆ selected(0.30) ⊆ selected(0.50)`. A change that
breaks nesting turns a dose-response curve into sampling noise.

## Operators propose; they never mutate

An operator emits immutable `(start, end, replacement)` edits against *original* offsets.
One applier resolves conflicts under a canonical total order. This is what makes replay
byte-identical regardless of what proposed the edit — including a language model.

A new operator needs: a declared contract from the lattice in `README.md`, a structural
level (which is what its dose is a fraction *of*), an entry in `taxonomy.yaml`, a row in
`docs/corruption-catalogue.md`, and tests. `TestCatalogueArithmetic` checks the catalogue's
own counts, so the documentation cannot drift from the code silently.

## Claims need artifacts

Under `validation/`, every quantitative claim traces to a committed artifact in
`validation/measurements/`, and `validation/tests/test_methodology_docs.py` fails when prose
and artifact disagree. If you change a measurement, regenerate the artifact in the same
commit.

The governing principle is in
[`validation/methodology/README.md`](validation/methodology/README.md): reuse a proven tool,
and where you depart from it, measure the departure against it. "We improved it" is not a
finding. Failed approaches are reported rather than deleted — three of four discriminators
for the clinical/non-clinical question failed, and the failures constrain what any future
method can claim.

## Style

Line length 100. Ruff with `E,F,W,I,UP,B,SIM,RUF,PL`. Comments explain *why* a decision was
made, especially where the obvious alternative is wrong — that is the house style, and most
of the existing comments are there because something bit somebody.

Suppressions are per file and per rule, with the reasoning written down. A blanket
directory exemption hides the next real finding.
