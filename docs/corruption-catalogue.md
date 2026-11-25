# The corruption catalogue

What RobustEHR can perturb in a clinical note, at which structural level, and
what each perturbation is claimed to preserve.

This document also **reconciles the original corruption taxonomy** against what
the package actually implements — what was kept, what was restructured, what was
merged, and what is not built. If you designed that taxonomy, [§5](#5-what-happened-to-the-original-taxonomy)
is the section that answers "where did my rows go".

---

## 1. Three axes, not one

The source taxonomy organises corruptions by a **domain** column —
structural / syntactic / semantic — crossed with a phenotype-preserving versus
phenotype-altering split. That is two facts about a corruption. The package
carries three, because the second and third are independent:

| axis | question it answers | why it is separate |
|---|---|---|
| **level** | *what unit is touched* — character, word, sentence, header, whole note | decides what a dose is a fraction **of** |
| **channel** | *what real-world process is simulated* — render, input, discourse, semantic | decides what a result is **about** |
| **contract** | *what is preserved* | decides what a result may **claim** |

Your "domain" column mostly maps to **channel**; your preserving/altering split
maps to **contract**, but with more resolution — see §1.3.

### 1.1 Level — what unit is touched

The level is not decoration. It is the **denominator of the dose**: "30%" means
30% of the eligible units *of that level*, so an operator at the `header` level
and one at the `word` level running at the same severity touch wildly different
amounts of text. Every level is separately measured in the baseline (§4).

```
document ── whole note
  └ section ── a header and the body beneath it
      └ header ── the heading line itself
      └ sentence
          └ list_item
          └ space_run ── a run of ≥2 spaces (column layout)
          └ word ── alphabetic content token
              └ token ── any token, including numerals
                  └ character
  ⟂ placeholder ── de-identification marker (cuts across the tree)
  ⟂ assertion ── a concept mention plus its negation/uncertainty/time/experiencer
```

`placeholder` and `assertion` are marked ⟂ because they do not nest: a
de-identification marker can sit inside a header or a sentence, and an assertion
is a *property of a span* rather than a span size.

### 1.2 Channel — what is being simulated

| channel | the real process | operators |
|---|---|---|
| `render` | the note **displayed or exported** differently | 10 |
| `input` | the note **captured** wrongly — typed, dictated, scanned | 3 |
| `discourse` | the note **shortened or repeated** — summarised, truncated, bloated | 3 |
| `semantic` | the note's **clinical assertions** altered | 8 |
| `control` | neither — the two calibration operators | 2 |
| `lexical` | the note **worded** differently — same referent, other name | 2 |
| `factual`, `adversarial` | declared, **nothing built yet** | 0 |

### 1.3 Contract — what may be claimed

Your taxonomy had two buckets: phenotype-preserving and phenotype-altering. The
package uses six, because the middle of that spectrum is where the interesting
operators live and collapsing it loses the distinction a robustness claim needs.

| contract | meaning | your bucket |
|---|---|---|
| `invariant_by_construction` | preservation is **machine-checkable**: a stated projection of the note is provably unchanged | preserving |
| `conditionally_preserving` | preservation depends on **where it landed** — a typo in `the` is harmless, a typo in `obese` destroys the only evidence token | preserving |
| `reference_altering_by_design` | the operator's **purpose** is to change what the note asserts | altering |
| `reference_unconstrained` | no claim either way | — |
| `control_null` | changes nothing; the floor | — |
| `control_destructive` | destroys meaning; the ceiling | — |

**Why `conditionally_preserving` matters.** Your taxonomy put "typographical
error" under phenotype-preserving. That is true on average and false in the
cases that decide a result: a typo landing on the one token carrying a phenotype
does alter it. The contract says so, and `dose.clinical_hits` /
`dose.category_hits` report where each run's edits actually landed, so the
condition is measured per run rather than assumed once in a table.

---

## 2. The operator catalogue

28 operators. `severity` is a fraction of **eligible units at that level** —
see §3.

### render — the note displayed or exported differently

| operator | level | contract | simulates |
|---|---|---|---|
| `render.header_style` | header | invariant | capitalisation conventions differing between institutions (`upper`/`lower`/`title`) |
| `render.header_delete` | header | conditionally preserving | an export or template that dropped section headings |
| `render.header_rename` | header | conditionally preserving | a template or institution that names the same section differently |
| `render.bullet_to_prose` | list_item | invariant | a note pasted out of a structured editor into plain prose |
| `render.list_to_prose` | list_block | invariant | a structured problem list pasted into a free-text field |
| `render.break_removal` | paragraph | conditionally preserving | an export that did not carry line structure |
| `render.space_delete` | char | conditionally preserving | word boundaries lost to copy-paste or PDF text extraction |
| `render.whitespace_collapse` | space_run | invariant | a renderer or clipboard that does not preserve column alignment |
| `render.lab_block_collapse` | space_run | invariant | an export or viewer that does not preserve column alignment in lab tables |
| `render.deid_restyle` | placeholder | invariant | a corpus de-identified under a different convention |

Three pairs here look like duplicates and are not. **`header_delete` vs
`header_rename`**: deletion takes any header the detector found, renaming
requires a lexicon hit, because a heuristic match has no canonical section and
therefore no equivalence class to rename within. **`bullet_to_prose` vs
`list_to_prose`**: same channel, different denominator — the first is dosed per
`list_item` and strips markers where it lands, the second per `list_block` and
joins the whole list with `; `, because a half-joined list is not a thing that
happens. **`whitespace_collapse` vs `space_delete`**: collapsing a run of two or
more spaces to one is invariant under `content_tokens` and never removes the
last separator; deleting that separator merges two content tokens, which no
token projection can survive.

### input — the note captured wrongly

| operator | level | contract | simulates |
|---|---|---|---|
| `input.typo` | word | conditionally preserving | keyboard typing errors (`substitute`/`transpose`/`delete`/`double`) |
| `input.ocr_confusion` | char | conditionally preserving | OCR on a scanned or faxed chart (`glyph`/`ligature`) |
| `input.phonetic_confusion` | token | reference-altering | speech-recognition and dictation substitution |

`input.typo` acts on alphabetic words of **three or more characters** and
changes **one interior character**: the first and last letters carry most of a
word's recognisability, so they are kept. The one exception is `transpose` on
the second-to-last letter, which swaps it with the last. Two-letter words such
as `MI` or `PE` are therefore out of its reach, and alphanumeric abbreviations
such as `DM2` or `A1c` are too unless `include_mixed` is set.
`input.ocr_confusion` acts on tokens of two or more characters, digits
included, at any position.

`input.ocr_confusion` is **shape-based, not keyboard-based** — `m`/`rn` are
opposite ends of a keyboard and nearly identical in print. It reaches digits on
purpose (`98.8` → `q8.8`, `153` → `1S3`, `50` → `5D`), because an OCR engine
reads whatever is on the page and a rule that withheld lab values would model
only the harmless half.

Note the **level difference between `input.typo` and `input.ocr_confusion`**,
which is not a detail: typing errors are events per word typed, so typo is dosed
over eligible words; scanning errors are events per character scanned, so OCR is
dosed over eligible character positions — the character-error-rate convention of
the OCR literature. Two operators reporting "10%" therefore mean two different
things, and each `denominator_doc` says which. Eligibility stays inside words in
both cases. The full argument for why these are separate operators rather than
two modes of one is `validation/methodology/15-input-channel-errors.md`.

A character rate is the right denominator for a page and the wrong one for a
word, and `input.ocr_confusion` takes **`max_edits_per_token`** to say so. At a
saturating severity over a narrow target — every span of one phenotype's
evidence, say — an uncapped character dose substitutes every confusable position
in a token at once, and `Hypertension` comes back as `Hvpcrfousj0h`: the term
deleted and replaced with noise of the same length, which is a redaction rather
than a misreading. With the cap at 1 the operator emits what it documents,
`patient` → `patlent`, at any severity, which is the configuration for an arm
aimed at one phenotype's evidence. The parameter is absent by default, so a run
that does not ask for it selects and emits what it would without it. The table
carries lowercase, digit and uppercase rows; the uppercase block is what lets
the operator reach `HTN`, `HFpEF` or `DVT`, the forms in which several
diagnoses are usually written.

**Setting an operator's parameters.** The modes in the tables, and the two
parameters named above, are set per operator and recorded on every dose row
(`params`):

```bash
robustehr run ... --operators input.ocr_confusion input.typo \
    --param input.ocr_confusion:max_edits_per_token=1 \
    --param input.typo:include_mixed=true --param input.typo:mode=transpose
```

In a recipe, `params: {input.ocr_confusion: {max_edits_per_token: 1}}`. From
Python, `apply_operator(..., params={"max_edits_per_token": 1})`. A parameter
feeds the operator's seed, so a run that sets one draws different units from a
run that does not, and an operator given no parameter behaves exactly as it
did before parameters could be set.

### lexical — the same thing said with different words

| operator | level | contract | simulates |
|---|---|---|---|
| `lexical.numeral_to_word` | number | conditionally preserving | a dictated or template-written note that spells numbers out (`bare`/`all`) |
| `lexical.medication_rename` | mention | conditionally preserving | a clinician or institution that names drugs the other way round (`flip`/`to_brand`/`to_generic`) |

What separates this channel from RENDER and INPUT is intent: nobody's scanner
produced `Tylenol` where the chart said `acetaminophen`. A lexical operator
therefore either preserves the referent exactly — same value, same drug — or it
belongs on the SEMANTIC channel instead, so both refuse to act where the
equivalence is unavailable rather than approximating one.

`lexical.numeral_to_word` defaults to `bare`, which excludes unit-bearing values:
`5 days` converts, `650 mg` does not. Spelling out a dose moves the number out
of the `<value><unit>` shape every dose parser keys on, which would conflate
"cannot read written numbers" with "cannot find the dose". `all` runs the other
experiment.

`lexical.medication_rename` needs `data/drugs/drug_synonyms.json`, built by
`validation/pipeline/scripts/build_drug_synonyms.py` from the DrugBank-derived CSVs — the map is
derived from a licensed source, so it is built locally rather than shipped, the
same rule the concept lockfiles follow. Without it the operator reports zero
eligible units rather than failing.

### discourse — the note shortened

| operator | level | contract | simulates |
|---|---|---|---|
| `discourse.sentence_delete` | sentence | reference-altering | summarization loss and terse documentation |
| `discourse.truncate` | document | reference-altering | context-window limits and EHR free-text field caps (`tail`/`head`/`middle`) |
| `discourse.section_duplicate` | section | conditionally preserving | copy-paste note bloat that repeats a section verbatim |

`discourse.section_duplicate` is the one operator dosed as a **count rather than
a rate** — `count:1`, `count:2`, `count:5`. "Duplicate 50% of sections" would be
four sections in one note and eleven in another, which is not a comparable
experimental condition. Ladders still nest: selection is hash-rank over the same
eligible set, so the section duplicated at `count:1` is still duplicated at
`count:5`.

### semantic — clinical assertions altered

Four dimensions × two mechanisms. The rule-based arm substitutes cues; the `_llm`
arm rewrites the clause with a configured model, keeping a minimal-diff edit and
a deterministic fallback.

| operator | flips | detector quality |
|---|---|---|
| `semantic.negation_flip` `_llm` | negated ⇄ present | **0.929** negated-F1 on NegEx gold, κ 0.74 |
| `semantic.uncertainty_flip` `_llm` | hedged ⇄ definite | out-of-domain only: F1 0.251 (P 0.855, R 0.147) |
| `semantic.temporality_shift` `_llm` | past ⇄ current | **no gold in any domain**; κ 0.41 on synthetic |
| `semantic.experiencer_shift` `_llm` | relative ⇄ patient | **no gold**; κ 0.22 — shipped with its detector quality disclosed |

**Read the detector quality as part of the operator.** A temporality flip is
only as trustworthy as the temporality detector that found the cue, and two of
these four have no gold standard anywhere. That is carried in the operator's own
metadata rather than in a footnote, so it appears beside the dose.

### control — the calibration floor and ceiling

| operator | level | contract | purpose |
|---|---|---|---|
| `control.identity` | document | null | changes nothing — the floor any metric must sit at |
| `control.char_shuffle` | word | destructive | destroys meaning — the ceiling |

Without these, a robustness curve has no scale. Every result is reported against
them.

---

## 3. Dose: how severity works, and how it differs from your table

Your taxonomy suggested severities per row — "10, 30, 50% of headers", "1, 3, 5%
sentences". The package implements the same idea with one change that matters.

**Severity is a fraction of `eligible_n`, not of the document.** A note with no
bullet lists has zero eligible units for `render.bullet_to_prose`; running it at
50% is not a 50% corruption, it is an **inapplicable** operator, and the run
reports `NA_NO_ELIGIBLE` rather than a zero that would be averaged in.

Every run records the whole chain, so a dose that could not be delivered is
visible rather than silently rounded:

```
total_n  →  scope_n  →  protected_n  →  eligible_n  →  requested_k  →  applied_n
  all       after       withheld by      what the      what the        what
  units     --target    protection       operator      severity        landed
                        (de-id, etc.)    can act on    asked for
```

**Check applicability before choosing a severity:**

```bash
robustehr applicability --corpus notes.csv
```

Your suggested severities remain good defaults. The package does not hard-code
them, because the right severity depends on the corpus — a note format with 6
headers and one with 60 are not comparable at "30% of headers".

---

## 4. How this connects to the baseline description

**The catalogue and the baseline are organised by the same levels**, so every
unit an operator can target has a measurement beside it. That is checkable
rather than aspirational: `robustehr describe` emits
`_unmeasured_levels_with_operators`, and it is empty.

```bash
robustehr describe --corpus notes.csv --markdown --phenotype hypertension
```

On five MIMIC discharge summaries:

| level | operators | median per note |
|---|---:|---|
| document | 2 | 15588 chars, 435 lines |
| section | – | 33 (33 canonical, 25 distinct ids) |
| header | 2 | 46 (**45 canonical, 3 guessed, 2 grammars**) |
| sentence | 1 | 338 (**205 prose, 110 layout**) |
| list_item | 1 | 74 across 39 blocks |
| space_run | 2 | 7 runs, 61 chars, longest 17 |
| placeholder | 1 | 73, scheme `underscore_run`, 4 per 1k chars |
| word | 2 | by lexical class + short forms |
| token | 1 | 6134 (2530 content) |
| character | – | 11236 alpha, 466 digit, 1234 punctuation |
| assertion | 8 | 2329 (1904 unmodified, 248 negated, 78 uncertain) |

**The distinctions are the point, not the counts.** "46 headers" does not predict
what `render.header_style` will do; "45 canonical, 3 guessed" does. "338
sentences" misleads when 110 of them are lab rows rather than prose, and
`discourse.sentence_delete` removing one of those does something different.

Add `--cui-map` for every concept mention as `(note_uid, cui, span, tuis,
categories)` — identifiers and offsets only, never the matched surface.

Then, after corrupting, the **same instrument** runs on both sides:

```bash
robustehr compare --run run/ --corpus notes.csv --markdown
```

That is what makes a delta meaningful: a change the baseline table can see is a
change a downstream model sees too.

---

## 5. What happened to the original taxonomy

The taxonomy this package was designed against is reproduced, row for row, in
[source-taxonomy.md](source-taxonomy.md): **29 substantive rows**. Reconciled
honestly against what is registered: **13 implemented, 5 partial, 11 not built**,
plus seven operators the source did not name. The three tables below sum to 29;
`tests/unit/test_operators.py::TestCatalogueArithmetic` counts them and compares
the result with the summary line here and with
[corruption-taxonomy-status.md](corruption-taxonomy-status.md), because a summary
line that drifts from the tables under it is how a coverage claim gets quoted
wrong. Row numbers are the source's.

### Kept and implemented (13)

| # | source row | operator | note |
|---|---|---|---|
| 1 | Section header deletion | `render.header_delete` | as specified; standalone headers only, so deleting a header never takes an inline value with it |
| 2 | Section header renaming | `render.header_rename` | as specified — 58 canonical sections × 2–10 clinical variants from `headers.yaml`; a lexicon hit is required, because a heuristic header has no equivalence class to rename within |
| 3 | Bullet-to-prose conversion | `render.bullet_to_prose`, `render.list_to_prose` | **two denominators** — per `list_item` (strip markers) and per `list_block` (join with `; `, the source's example), because "30% of a list" is not a thing that happens to a list |
| 4 | Loss of text structure | `render.break_removal`, `render.whitespace_collapse`, `render.lab_block_collapse` | one operator per kind of structure the row names: breaks (replaced by a single space so no two words merge; hard-wrap continuations and list/lab interiors excluded), prose space runs, and column padding inside aligned blocks |
| 5 | Spacing loss | `render.space_delete` | as specified (`Denies chest pain` → `Denies chestpain`); single spaces between content tokens in prose only |
| 11 | Numeral ⇄ textual | `lexical.numeral_to_word` | as specified (`EF 30 %` → `EF thirty %`) via num2words; `bare` mode excludes unit-bearing values, `all` includes them |
| 15 | Typographical error | `input.typo` | 4 of the source's 6 modes (`substitute`, `transpose`, `delete`, `double`); "insert random character" folded into substitute |
| 18 | Homoglyphs | `input.ocr_confusion` | **expanded** — the source names `App1e` and `rn`→`m`; the operator adds a digit⇄letter table because lab values are where OCR does clinical damage, and is dosed per character (CER), not per word |
| 19 | Sentence deletion | `discourse.sentence_delete` | as specified; prose sentences only |
| 20 | Negation deletion / insertion | `semantic.negation_flip` + `_llm` | as specified, plus an LLM rewrite arm |
| 21 | Uncertainty flip | `semantic.uncertainty_flip` + `_llm` | as specified, plus an LLM arm |
| 22 | Temporality shift | `semantic.temporality_shift` + `_llm` | as specified, plus an LLM arm |
| 27 | Mistaken use of homophones | `input.phonetic_confusion` | **method changed** — the source names the Datamuse API; the operator *generates* from morpheme rules, so it works offline, is deterministic, and covers terms no curated list contains (`hypogammaglobulinemia`/`hyper-`) |

### Partial — the row exists but narrower than the source (5)

| # | source row | what exists | what is missing |
|---|---|---|---|
| 6 | Sentence duplication | `discourse.section_duplicate` re-inserts a whole section verbatim, count-dosed (1, 2, 5) | sentence-level duplication and the source's "repetitions per paragraph" dose |
| 14 | Abbreviations | the **inventory and expansion table are built** and measured; `robustehr ambiguity` reports the load | no operator that expands or contracts abbreviations in text |
| 16 | Capitalization | header-level only, via `render.header_style` | body-text capitalisation, random-case |
| 23 | Sensitive attributes / demographic inconsistency | `semantic.experiencer_shift` moves a finding between patient and relative | sex, race, age, disability, SES, orientation and pronouns as **spans to flip** — a different mechanism |
| 29 | Medication name substitution | `lexical.medication_rename`: generic ⇄ brand for the SAME drug | the source's own example, same-class substitution (`Warfarin` → `Apixaban`), which changes the drug and belongs on the SEMANTIC channel under a different contract |

### Not built (11)

| # | source row | why not, in one line |
|---|---|---|
| 7 | Punctuation loss | not started |
| 8 | Punctuation gain | not started |
| 9 | Paraphrasing | an LLM paraphrase is not deterministic; a rule-based one does not exist |
| 10 | Use of synonyms | needs a same-concept synonym source with measured precision; none vetted |
| 12 | Spacing (intra-word) | not started |
| 13 | Spelling error | a plausible misspelling needs an error corpus rather than a rule; the package has the **measurement** (`metrics.spelling.profile_near_miss`, published with its precision) but no injector |
| 17 | Diacritic | not started (rare in English clinical text) |
| 24 | Social history corruption | no baseline is operationalisable and no gold exists |
| 25 | Word deletion | not started |
| 26 | Word order | not started |
| 28 | Embedding-based substitution | the GloVe method the source proposed is not deterministic across builds and was rejected |

Two halves are worth singling out because the machinery for them exists:

- **Same-class drug substitution** (row 29's missing half) is what remains of the
  medication row after `lexical.medication_rename` took the generic ⇄ brand half.
  The two are deliberately separate operators: renaming preserves the drug,
  substituting a class-mate does not, so they belong to different contracts and
  cannot share a severity. The concept layer already supplies same-class
  medication sets per phenotype.
- **Corpus-derived spelling errors** (row 13) are not the same as `input.typo`. A
  typo is mechanical; a misspelling is a *word people actually get wrong*.

### Added — operators the source taxonomy did not name (7)

| operator | why it was added |
|---|---|
| `control.identity` | the null floor — without it a robustness curve has no zero |
| `control.char_shuffle` | the destructive ceiling — without it, no scale |
| `discourse.truncate` | context-window limits and EHR field caps are a real, common truncation the source did not cover |
| `render.deid_restyle` | corpora de-identified under different conventions are a portability problem specific to this domain |
| `render.lab_block_collapse` | column alignment in lab tables behaves differently from prose whitespace (serves row 4) |
| `render.list_to_prose` | row 3 at the denominator it needs: per list block, join with `; ` |
| `discourse.section_duplicate` | row 6's benign control for copy-forward, dosed as a count rather than a rate |

The two controls are the most consequential addition. The source listed
corruptions; it did not list the two runs that make the others interpretable.

### The structural change: targeting is separate from the operator

Your taxonomy embedded *what to hit* in the corruption ("10% of `> 2` letter
words", "eligible assertions"). The package **splits that out**, because the same
mechanism aimed at different content answers different questions:

```bash
robustehr run --operators input.typo --target 'all(cat=medication;pheno=hypertension)'
```

Same operator, same severity, aimed differently — measured on MIMIC:

| target | edits applied | concepts lost |
|---|---:|---:|
| `all` | 512 | −147 |
| `cat=medication` | 42 | −32 |

That separation is why the catalogue has 28 operators rather than one per
(mechanism × target) pair, and it is the largest structural departure from the
original design. See [targeting-design.md](targeting-design.md).

---

## 6. Composing corruptions

Your taxonomy is a list of single corruptions. Real degradation layers, and the
pipeline supports that:

```bash
robustehr run --corpus notes.csv --out run/ --compose \
    --operators input.ocr_confusion render.whitespace_collapse discourse.sentence_delete \
    --severities 0.30 --emit-text data/corrupted/
```

Every operator proposes against the **pristine** note and the proposals are
merged once. Two consequences worth knowing:

- **Order does not matter.** Conflicts resolve by a content-derived total order,
  so `a,b` and `b,a` produce identical bytes.
- **Collisions are counted.** A sentence delete swallows spans a token operator
  wanted; those land in `dose.conflicts_dropped` rather than vanishing. A
  composite that delivers less than the sum of its parts is expected — one that
  delivers less *silently* would report a severity it never achieved.

---

## 7. Where to go next

| you want | read |
|---|---|
| run it on a corpus | [pipeline.md](pipeline.md) |
| aim a corruption precisely | [targeting-design.md](targeting-design.md) |
| the phenotype concept sets | [phenotype-concept-table.md](../validation/phenotype/phenotype-concept-table.md) |
| the whole data flow | [pipeline.md](pipeline.md) |
| why a contract is what it is | [../methodology/03-taxonomy-and-contracts.md](../validation/methodology/03-taxonomy-and-contracts.md) |
| why dose has a denominator | [../methodology/04-dose-accounting.md](../validation/methodology/04-dose-accounting.md) |
