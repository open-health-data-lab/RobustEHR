# Lexicon construction

Three lexicons, built by different methods because they answer different
questions. Every token resolves to exactly one of: a semantic category, general
English, a function word, or out-of-vocabulary.

| Lexicon | Size | Source | Ships? |
|---|---|---|---|
| Clinical | **250,613** terms | UMLS 2026AA, filtered by semantic type | no — licensed |
| General English | **25,185** words | wordfreq, minus clinical | yes — Apache-2.0 |
| Function words | **275** words | hand-curated closed class | yes |

Overlap between general English and function words is **zero** by construction.
Overlap between general English and the clinical vocabulary is 4,627, confined
to `procedure` and `finding` by construction — see the precedence rule below.

## The clinical lexicon

English, non-suppressible, single-word strings from UMLS concepts whose semantic
type falls in one of eleven named categories. Three choices, each because the
alternative is harder to defend:

- **Semantic types, not a hand-picked list.** Membership is a lookup against a
  published, versioned terminology. A term either carries T121 or it does not.
- **Suppressible content excluded.** `SUPPRESS != 'N'` marks strings NLM flags
  as obsolete; including them inflates coverage with material the terminology
  itself disavows.
- **Two-character tokens excluded.** Every two-letter string is some element
  symbol in UMLS. Admitting them put `on` (3,806 occurrences) and `no` (3,483)
  at the top of the chemical category via nitric oxide. `mg`, `po` and `iv` are
  real and important, and they need the abbreviation resolver with abstention,
  not dictionary lookup, precisely because `no` is genuinely ambiguous.

Licensed strings never enter the repository. What ships is a manifest carrying
the release, counts and a SHA-256 over the sorted vocabulary, so a reader with
the same release can verify a bit-identical rebuild without licensed content
changing hands.

## The general-English lexicon, and three failed discriminators

The list answers a narrow question: **is this word ordinary English rather than
clinical content, in the context of a clinical note?** The qualifier is the
whole difficulty. `foot`, `chest`, `pain` and `blood` are ordinary English by
any frequency measure and are clinical content in a discharge summary.

Four signals were tried. Reporting the three that failed is not padding — it
constrains what any future method can claim.

All four are **intrinsic**: properties a word carries in a lexicon. A fifth,
**empirical** signal was added later for concept-restricted corruption —
*measured rate of falling inside an adjudicated clinical span* — and it
separates the hard cases these four cannot: `she` 0.00, `patient` 0.00,
`history` 0.00 against `pneumonia` 0.98, `hypertension` 0.99, `dyspnea` 0.94.
It is not a replacement for anything here, because it is corpus-bound and
requires gold annotations to build. See
[validation-protocol §9](../protocol.md#9-clinical-targeting-for-concept-restricted-corruption)
for its measurement, its scope, and the two failure modes that only whole-note
review exposed.

**1. General-English frequency alone — fails.** It ranks `blood` (Zipf 5.10) as
more ordinary than `normal` (5.01). Any cut that drops `normal` also drops
`blood`.

**2. Source-vocabulary count — fails.** `walking` appears in 14 UMLS sources,
`normal` in 11, and `po` in 1 while being genuinely clinical.

**3. UMLS Semantic Group — fails.** `one`, `well`, `normal`, `stairs` and
`history` all carry `DISO`, the same coarse group as `dyspnea` and `pneumonia`.
This is what forced the move from Semantic Groups to semantic **types**.

**4. Semantic type, high-precision categories only — works.** Subtracting
anatomy, disease, symptom, medication, device and lab_result from the common
English list is correct on 25 of a 26-word probe: `foot`, `chest`, `pain`,
`blood`, `hand`, `back` removed; `please`, `note`, `home`, `take` kept.

Only the *precise* categories are subtracted. `procedure` (via T058 Health Care
Activity) and `finding` (via T033) are where ordinary words accumulate, and
subtracting them would strip `home`, `take`, `report` and `new`.

## TF-IDF keyness: rejected as a gate, kept as a filter

Keyness is log(frequency in clinical text) − Zipf(general English). As a general
discriminator it **fails**: `foot` scores 0.63 against `home` at 0.59, and
`hand` (−0.20) and `back` (−0.11) fall below plainly ordinary words, because
the clinical and idiomatic senses are the same string.

It is clean above 1.5, where it catches the one failure mode the semantic-type
rule cannot see — clinical vocabulary that UMLS gives no precise type. Band
inspection is the calibration:

| Keyness | Examples | Character |
|---|---|---|
| ≥ 2.0 | `sig`, `po`, `mg`, `metastatic`, `lesion`, `rx` | clearly clinical |
| 1.5–2.0 | `rheumatoid`, `pitting`, `icu`, `exam`, `chronic` | clearly clinical |
| 1.2–1.5 | `bony`, `reflexes` \| `notable`, `moderate` | mixed |
| 1.0–1.2 | `swollen`, `severe` \| `initially`, `presents` | mixed |
| 0.8–1.0 | `smoker` \| `pleasant`, `excluded`, `increased` | mostly ordinary |

1.5 is where the character changes. It removed 187 words. The 1.0–1.5 band is
reported as suspects rather than acted on, because removal there would cost
ordinary words.

## The function-word lexicon

275 closed-class words: determiners, quantifiers, conjunctions, prepositions,
auxiliaries, pronouns, adverbs and particles. A genuinely finite class that does
not grow, which is the one situation where a hand-curated list is the right tool
rather than a shortcut.

Audited against the clinical vocabulary, which caught the error worth catching:
**`back` had been listed as a preposition and is anatomy in a note** (back pain).
Removed. Ten residual collisions remain and are UMLS artifacts rather than
genuine clinical words — `down` via Down syndrome, `ten` and `today` via some
drug — and are documented rather than chased.

A `discourse` group (`please`, `note`, `see`, `thanks`) was removed: those are
content words with low semantic weight rather than closed-class grammar, and
`noted`/`see` are used clinically. They resolve to general English instead.

## The precedence rule

```
function word  →  general English  →  semantic category  →  out-of-vocabulary
```

**A general-English word wins over any semantic category it also carries.** That
is not a concession, it is what the list is built to mean: words carrying a
high-precision clinical type were removed during the build precisely so they
never reach this rule, and clinical vocabulary UMLS mistyped was removed by
keyness. What survives and still collides is the residue — `home` (T058),
`take`, `report` — where the terminology over-reaches and ordinary English is
the better reading.

## Known residual errors

Reported rather than hidden, because they bound what the word-level layer can
claim:

- `times` is removed from general English because UMLS types it T047 Disease or
  Syndrome, though its keyness of 0.50 says it is ordinary.
- `date` carries T121 and so resolves as a medication.
- `sig`, `po`, `mg` resolve to out-of-vocabulary: correctly not ordinary
  English, but with no category, pending the abbreviation resolver.

All three are word-level failures that concept-level matching in context is
expected to remove, since none is a concept mention in a note.
