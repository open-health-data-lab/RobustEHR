# Validation

How RobustEHR was validated, and what each measurement is allowed to claim.

`docs/` tells you how to use the package. This directory is for a reader asking whether
the method is sound: every component that was built rather than reused, every alternative
that was tried and rejected, and the artifact behind each number.

## The governing rule

**Every quantitative claim traces to a committed artifact under
[`measurements/`](measurements/), and a test fails if prose and artifact drift apart.**

That test is [`tests/test_methodology_docs.py`](tests/test_methodology_docs.py). It reads
the numbers out of the methodology chapters and compares them against the JSON. It is the
reason a claim here can be checked rather than taken on trust.

## Layout

| Path | What it holds |
|---|---|
| [`methodology/`](methodology/) | The written account, 11 chapters. Reviewer-facing: what was done, why the alternative was rejected, what was measured rather than assumed. |
| [`measurements/`](measurements/) | 68 committed artifacts, indexed by [`measurements/README.md`](measurements/README.md). Results the package produces about *itself*. |
| [`record/`](record/) | The development record: chapters and notes written while a component was built, kept for audit and cited by nothing. |
| [`protocol.md`](protocol.md) | The validation protocol: what each claim requires before it may be made. |
| [`pipeline/`](pipeline/) | Validation of the corruption and concept pipeline — segmentation, matching, assertion detection, targeting. |
| [`phenotype/`](phenotype/) | Validation of the phenotype concept-set layer: how the shipped sets were built, vetted and audited. |
| [`tests/`](tests/) | The consistency tests that keep prose and artifacts pinned together. |

## The two studies

**`pipeline/`** — is the instrument sound? Concept matching against the
[SNOMED CT Entity Linking Challenge](pipeline/scripts/challenge_metric.py), assertion
detection against NegEx and BioScope gold, our segmenter against PyRuSH, our tagger
head-to-head against medspaCy, and the ceiling measurements that decided whether a
component was worth building at all. Four discriminators were tried for the
clinical/non-clinical question; three failed, and the failures are reported because they
constrain what any future method can claim.

**`phenotype/`** — are the shipped concept sets right? `src/robustehr/resources/` carries
~4 MB of phenotype closure, vetting and proposal data that drives phenotype targeting.
This directory is how it was built and why it is trustworthy: deterministic SNOMED seed →
closure, MED-RT medications, LLM-proposed facets grounded and vetted, the evidence closure,
the link and set audits, and the [concept appendix](phenotype/appendix/) — identifiers
only, no licensed surface strings. A public package should not carry load-bearing resources
whose construction is undocumented.

## Running any of this

Most of these need data the package cannot ship. Restricted inputs live under `data/` and
are gitignored by default-deny:

- **UMLS Metathesaurus** (Metathesaurus Licence Agreement) — the concept layer, matching,
  and every phenotype script.
- **MIMIC-IV note text** (PhysioNet Credentialed Health Data Use Agreement) — the corpus
  measurements and the MIMIC assertion gold.
- **Public gold corpora** — NegEx and BioScope are fetched by
  [`pipeline/scripts/fetch_negex.py`](pipeline/scripts/fetch_negex.py) and
  [`fetch_bioscope.py`](pipeline/scripts/fetch_bioscope.py) and need no credentials.

Scripts that need an absent input skip rather than fabricate, and so do the tests that read
their artifacts. A skipped measurement is visible; a fabricated one is not.

Nothing here reaches a network except the two fetch scripts and the LLM-backed arms, which
require `OPENROUTER_API_KEY` and are opt-in.
