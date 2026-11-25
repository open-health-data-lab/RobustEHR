# Design overview

## The problem

Robustness claims in clinical NLP rest on undefined noise. Papers report that a
model "degrades under realistic perturbation" without specifying what changed,
how much, over what denominator, whether it touched clinical content, or how to
regenerate it. The perturbation is usually a script that was run once and not
released, so the claim is not reproducible even in principle.

A 2025–2026 literature sweep found counterfactual clinical benchmarks and
agentic-perturbation studies, but **no reusable deterministic toolkit**. That gap
is the contribution.

## Five questions

RobustEHR exists to make five questions answerable about any perturbation of
clinical free text:

| # | Question | Answered by |
|---|---|---|
| 1 | What changed? | immutable edit scripts against original offsets |
| 2 | How much? | dose accounting in exact integers, achieved ≠ requested |
| 3 | Over what denominator? | a per-operator `DoseSpec`, declared not implied |
| 4 | What kind of content did it touch? | semantic category per applied edit |
| 5 | Can it be regenerated exactly? | content-derived seeds, replay and verify |

Question 4 separates this from general-domain text-attack libraries
(TextAttack, TextFlint, nlpaug), which have no notion of clinical content.
Question 5 separates it from ad-hoc scripts.

## Architecture in one paragraph

Everything neural, licensed or network-dependent runs **once, offline**, into
hash-frozen artifacts. Runtime is dictionary matching plus deterministic rules,
so a run is byte-reproducible on a reviewer's laptop with no GPU and no UMLS
licence. Operators are **pure proposers**: they report which units they consider
eligible and emit immutable `Edit` objects against original offsets, and never
mutate text or sample. The framework owns scope filtering, protection
subtraction, `k` computation and hash-rank selection. If operators sampled,
nestedness and subset-invariance would be per-operator promises rather than
framework guarantees.

## Naming discipline

Used consistently, and it preempts an obvious objection:

- **perturbation** — reference-preserving
- **corruption** — reference-altering
- **adversarial transformation** — where no realism is claimed

Calling a whitespace change a "corruption" invites the criticism that the
taxonomy is inflated. The distinction is cheap to maintain and worth making.

## Positioning

The paper is **measurement infrastructure**, not "LLMs are brittle". The latter
is unsurprising and invites a "we knew that" review; the former is a
contribution a reviewer cannot dismiss on those grounds. The robustness sweep is
a demonstration section, not a second contribution.
