> **Development record.** This document was written while the component it
> describes was being built and reads as a history. The method as it stands is
> in [`validation/methodology/`](../methodology/); nothing here is cited by the
> manuscript. Kept so every decision can be audited.

# Protocol §0 — how the stage-3 gate changed the design

### Stage 3 — how a gate changed the design

The clearest argument in this document for measuring before building.

`abbreviation-resolver-spec.md` required a **V0 gate**: measure the achievable
ceiling before writing any of the subsystem. The gate ran, and it inverted the
design.

| | accuracy over 8,520 abbreviation-shaped gold spans |
|---|---:|
| shipped matcher | 0.4346 |
| exact lookup, `min_match_length=2` | 0.4837 |
| **ceiling — a perfect disambiguator over UMLS** | **0.5511** |
| **unreachable at any policy** | **0.4489** |

The spec proposed a seven-rung disambiguation cascade. Every rung of it competes
for **6.7 percentage points**, because that is the whole gap between exact lookup
and a perfect disambiguator.

Meanwhile 44.9% of these spans have no UMLS candidate carrying the right category
at all — `creat` (131 occurrences), `rbc` (151), `hgb` (147), `rdw` (137),
`angap` (93), `heent` (68). Those are not ambiguous abbreviations awaiting
disambiguation; they are **lab and exam shorthand UMLS does not contain as
strings**. `creatinine` is in UMLS, `creat` is not.

So the conclusion, and the redirection: **clinical abbreviation resolution in
this corpus is a vocabulary problem, not a disambiguation problem.** A cascade
picks among candidates that already exist and cannot help when the candidate set
is empty. The component worth building is a **surface-form expansion table**,
which the spec had relegated to its final rung.

That is what a gate is for. It cost an afternoon and stopped a seven-rung
subsystem being built to chase 6.7 points while 44.9% went untouched.

