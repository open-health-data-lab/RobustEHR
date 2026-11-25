# Corruption taxonomy — implementation status

The taxonomy this package was designed against, row for row, with what RobustEHR
actually implements. The source is the a priori design document reproduced in
[source-taxonomy.md](source-taxonomy.md) — **29 substantive rows**, numbered there
and here identically. Every source row appears exactly once below and is
classified exactly once, so the summary line is arithmetic over this table
rather than a claim about it.

**13 implemented · 5 partial · 11 not built** — 29 source rows. The counts are
asserted by `tests/unit/test_operators.py::TestCatalogueArithmetic` against
[corruption-catalogue.md](corruption-catalogue.md) §5, so a summary that drifts
from the tables fails a test rather than reaching a manuscript.

| status | meaning |
|---|---|
| ✅ | implemented and covered by tests |
| 🟡 | partially implemented — the **missing half is named**, never glossed |
| ❌ | not built |

Two conventions differ from the original and are marked ⚠ where they apply:

- **Severity is a fraction of ELIGIBLE units, not of the document.** "30% of
  headers" means 30% of the headers this note actually has. A note with no
  bullet lists reports `NA_NO_ELIGIBLE` rather than a zero that gets averaged in.
- **Targeting is separated from the mechanism.** The source rows embed *what to
  hit* ("10% of >2 letter words"); the package takes that as a `--target`
  argument, so one operator serves every target. `input.typo` at 0.30 costs 147
  concepts against `--target all` and 32 against `--target cat=medication`.

Where one source row is served by two operators at different denominators, or
where the implemented half and the missing half of a row have different
mechanisms, that is said inside the row. No row is split into two rows, because
a split row is how a 29-row taxonomy gets reported as 33.

---

# Phenotype-preserving corruptions

## Sentence and document level (source rows 1–9)

| # | ✓ | Corruption subtype | What it simulates | Deterministic method | Example | Severity | Operator |
|---|---|---|---|---|---|---|---|
| 1 | ✅ | Section header deletion | Loss of note structure from EHR export or OCR | Header index from the segmenter, not regex; removes the header line, preserves the body | `Past Medical History:` → removed, content kept | 30/50/100% of **standalone headers** ⚠ | `render.header_delete` |
| 2 | ✅ | Section header renaming | Non-standard section labels | Renames to a clinically equivalent variant of the SAME canonical section, drawn from `headers.yaml` (58 sections × 2–10 variants). Requires a lexicon hit: a heuristic header has no equivalence class to rename within. Casing is carried over, so this is a rename and not also a capitalisation change | `Assessment and Plan:` → `Clinical Impression:` | 30/50/100% of renameable headers | `render.header_rename` |
| 3 | ✅ | Bullet-to-prose conversion | Loss of list formatting by export or OCR | Two operators at two denominators, because "30% of a list" is not a thing that happens to a list: `render.bullet_to_prose` strips the marker from a list **item**; `render.list_to_prose` joins a whole list **block** with `; ` (the source's example) | `- COPD - HF - DM2` → `COPD; HF; DM2.` | 30/50/100% of list items, or of list blocks | `render.bullet_to_prose`, `render.list_to_prose` |
| 4 | ✅ | Loss of text structure | Loss of breaks between sections, indentation and extra spacing | Three operators, one per kind of structure the source row names. Breaks: `render.break_removal` replaces the whitespace run between two blocks with ONE space so no two words merge; hard-wrap continuations and list/lab interiors are excluded. Extra spacing: `render.whitespace_collapse` collapses runs of ≥2 spaces in prose, `render.lab_block_collapse` collapses column padding inside aligned blocks | `...left arm.\n\nMedications:` → `...left arm. Medications:`; `Na    140` → `Na 140` | 30/50/100% of **breaks**; 10/30/50% of **space runs** ⚠ | `render.break_removal`, `render.whitespace_collapse`, `render.lab_block_collapse` |
| 5 | ✅ | Spacing loss | Copy-paste loss of formatting | Deletes single spaces between two content tokens, in prose sentences only — lab rows and aligned blocks are column structure, not word gaps | `Denies chest pain` → `Denies chestpain` | 10/20/30% of **word spaces** | `render.space_delete` |
| 6 | 🟡 | Sentence duplication | Copy-forward and note bloat | `discourse.section_duplicate` re-inserts a whole **section** verbatim, dosed as a count (1, 2, 5 sections) because "50% of sections" is four in one note and eleven in another. The content is identical, so it is the benign control for copy-forward | a section repeated | 1/2/5 sections | `discourse.section_duplicate` |
| | | | | ❌ **Missing:** sentence-level duplication and the source's "repetitions per paragraph" dose | | | |
| 7 | ❌ | Punctuation loss | Punctuation loss (OCR) | — | remove `.` | — | — |
| 8 | ❌ | Punctuation gain | Punctuation gain (OCR) | — | add `,` or `!` | — | — |
| 9 | ❌ | Paraphrasing | Varied language use | — (an LLM paraphrase would not be deterministic; see methodology 09) | `Denies chest pain` ⇄ `reports no chest pain` | — | — |

## Word level (source rows 10–14)

| # | ✓ | Corruption subtype | What it simulates | Deterministic method | Example | Severity | Operator |
|---|---|---|---|---|---|---|---|
| 10 | ❌ | Use of synonyms | Meaning-preserving word change | — | `anti-hypertensive` → `hypotensive` | — | — |
| 11 | ✅ | Numeral ⇄ textual | Numeral/alphabetical variability | Spells integers out via num2words, normalised to US style (no `and`, no comma). Refuses decimals, leading zeros and anything over six digits — no written form preserves those. `bare` mode excludes unit-bearing values so a drug dose keeps its `<value><unit>` shape; `all` includes them | `EF 30 %` → `EF thirty %` | 30/50/100% of **spellable numerals** | `lexical.numeral_to_word` |
| 12 | ❌ | Spacing (intra-word) | Misplaced spacing (OCR) | — | `Patient` → `Pat ient` | — | — |
| 13 | ❌ | Spelling error | Common spelling errors | — | `Hemorrhage` → `hemorage` | — | — |
| | | | | **Distinct from `input.typo`**: a typo is mechanical, a misspelling is a word people actually get wrong. The package has a misspelling *measurement* (`metrics.spelling.profile_near_miss`, published with its precision) but no operator that injects one, because a plausible misspelling needs an error corpus rather than a rule | | | |
| 14 | 🟡 | Abbreviations | Uneven use of abbreviations | The expansion table **is built and measured**; `robustehr ambiguity` reports the load and the ambiguity rate | — | — | *(measurement only)* |
| | | | | ❌ **Missing:** any operator that expands or contracts abbreviations in text | | | |

## Token level (source rows 15–18)

| # | ✓ | Corruption subtype | What it simulates | Deterministic method | Example | Severity | Operator |
|---|---|---|---|---|---|---|---|
| 15 | ✅ | Typographical error | Common typing mistakes | Keyboard-adjacency table; **interior positions only** — first and last characters carry most of a word's recognisability. Modes: `substitute`, `transpose`, `delete`, `double`; "insert random character" is folded into `substitute` | `Random` → `Randm` / `Randmo` / `Randcm` / `Randoom` | 5/10/15% of words ≥3 chars | `input.typo` |
| 16 | 🟡 | Capitalization | Loss of capitalization | **Headers only**: `render.header_style` re-cases a header label (`upper`/`lower`/`title`) | `PAST MEDICAL HISTORY:` → `Past Medical History:` | 10/30/50% of headers | `render.header_style` |
| | | | | ❌ **Missing:** body-text capitalisation and random-case | | | |
| 17 | ❌ | Diacritic | Loss of diacritic specificity | — | `Guillain-Barré` → `Guillain-Barre` | — | — |
| 18 | ✅ | Homoglyphs | OCR errors | Shape-confusion table + multi-character ligatures. **Expanded** beyond the source with a digit⇄letter table, because lab values are where OCR does clinical damage. Modes: `glyph` (preserves length), `ligature` (`rn`→`m`, `cl`→`d` — **changes** length, which is what breaks a tokeniser). Dosed per confusable **character**, not per word | `treatment` → `treatrnent`; `98.8` → `q8.8`; `153` → `1S3` | 5/10/15% of confusable positions | `input.ocr_confusion` |

---

# Phenotype-altering (or potentially altering) corruptions

## Sentence level (source rows 19–24)

| # | ✓ | Corruption subtype | What it simulates | Deterministic method | Example | Severity | Operator |
|---|---|---|---|---|---|---|---|
| 19 | ✅ | Sentence deletion | Summarization loss | Sentence index from the segmenter; BLAKE2b hash-ranked selection, never random; prose sentences only | `History of acute pulmonary edema.` removed | 10/30/50% of prose sentences | `discourse.sentence_delete` |
| 20 | ✅ | Negation deletion / insertion | Lost/gained negation cue | Cue substitution over ConText-detected assertion spans. **Plus an LLM rewrite arm** the source did not have | `Denies chest pain` ⇄ `Reports chest pain` | 10/30/50% of **eligible negation cues** ⚠ | `semantic.negation_flip` `_llm` |
| | | | | Detector quality: **F1 0.929** on the NegEx test set; 0.608 on held-out MIMIC gold (two-LLM annotation) | | | |
| 21 | ✅ | Uncertainty flip | Loss/addition of diagnostic uncertainty | Hedge-cue dictionary over detected spans, plus an LLM arm | `Possible pneumonia` → `Pneumonia` | 10/30/50% of eligible hedge cues | `semantic.uncertainty_flip` `_llm` |
| | | | | Detector quality: **F1 0.251 out of domain** (BioScope; P 0.855, R 0.147); 0.442 on held-out MIMIC gold with the extended cues | | | |
| 22 | ✅ | Temporality shift | Current vs historical confusion | Temporal-cue mappings over detected spans, plus an LLM arm | `History of PE` → `Active PE` | 10/30/50% of eligible temporal cues | `semantic.temporality_shift` `_llm` |
| | | | | Detector quality: **no published gold**; 0.294 F1 on held-out MIMIC gold, 0.525 with the section-header rule | | | |
| 23 | 🟡 | Sensitive attributes / demographic inconsistency | Demographic contradiction | `semantic.experiencer_shift` moves a finding between the patient and a relative | `Mother had breast cancer` → attributed to the patient | 10/30/50% of eligible experiencer cues | `semantic.experiencer_shift` `_llm` |
| | | | | Detector quality: **no published gold**; κ 0.22 on synthetic fixtures — cut from v1 and reinstated by explicit decision | | | |
| | | | | ❌ **Missing:** sex, race, age, disability, SES, orientation and pronouns as spans to flip — a different mechanism from experiencer | | | |
| 24 | ❌ | Social history corruption | SDOH / substance-use documentation error | — | — | — | — |

## Word level (source rows 25–29)

| # | ✓ | Corruption subtype | What it simulates | Deterministic method | Example | Severity | Operator |
|---|---|---|---|---|---|---|---|
| 25 | ❌ | Word deletion | Summarization loss | — | `Ejection fraction` → removed | — | — |
| 26 | ❌ | Word order | Word order loss | — | `Ejection fraction` → `Fraction ejection` | — | — |
| 27 | ✅ | Mistaken use of homophones | Meaning-altering homophone | **Method changed** — generated from morpheme rules rather than the Datamuse API: offline, deterministic, and reaches terms no curated list contains. Rules whose affixes collide with ordinary English are gated behind a vocabulary, else `discharge` → `dyscharge`; when no lexicon is present those rules are **skipped and counted** | `hypertension` ⇄ `hypotension`; `hypogammaglobulinemia` ⇄ `hyper-` | 10/30/50% of tokens a rule fires on | `input.phonetic_confusion` |
| 28 | ❌ | Embedding-based substitution | Synthetic | — | `Denies` → `Disowns` | — | — |
| 29 | 🟡 | Medication name substitution | Drug recognition or summarization error | `lexical.medication_rename` swaps generic ⇄ brand for the SAME drug. Dose, route and frequency survive by construction — the edit spans the name and nothing else. Multi-token names are refused on both sides, as are brands that are ordinary English words or that map to more than one generic | `Tylenol 650 mg PO q6h` → `acetaminophen 650 mg PO q6h` | 30/50/100% of **renameable medication mentions** | `lexical.medication_rename` |
| | | | | ❌ **Missing:** the source's own example — same-class substitution (`Warfarin` → `Apixaban`). That changes the drug, so it is a SEMANTIC edit under a different contract. **Highest-value unbuilt half**: the concept layer already supplies same-class medication sets per phenotype | | | |

---

# Added — operators the source taxonomy did not name

Seven. Three of them serve a source row above at a denominator the source did
not have (`render.list_to_prose` for row 3, `render.lab_block_collapse` for row
4, `discourse.section_duplicate` for row 6); four are new. The two controls are
the most consequential: the source listed corruptions but not the runs that make
the others interpretable.

| ✓ | Operator | What it simulates | Why it was added |
|---|---|---|---|
| ✅ | `control.identity` | nothing | **The null floor.** Without a run that changes nothing, a robustness curve has no zero and a "0.02 degradation" cannot be distinguished from measurement noise |
| ✅ | `control.char_shuffle` | nothing | **The destructive ceiling.** Without a run that destroys the text, no result has a scale |
| ✅ | `discourse.truncate` | context-window limits, EHR free-text field caps | A real and common truncation the source did not cover. Modes: `tail`, `head`, `middle` |
| ✅ | `render.deid_restyle` | a corpus de-identified under a different convention | A portability problem specific to this domain: `___` vs `[**Name**]` vs `<REDACTED>`. Nine modes |
| ✅ | `render.lab_block_collapse` | an export that does not preserve column alignment | Lab-table alignment behaves differently from prose whitespace and needs its own unit (serves row 4) |
| ✅ | `render.list_to_prose` | a structured problem list pasted into a free-text field | Row 3 at the denominator it needs: dosed per **list block** and joins with `; `, because a list either survived the paste or it did not |
| ✅ | `discourse.section_duplicate` | copy-paste note bloat | Row 6's benign control: content identical, so nothing is stale and any effect is attributable to redundancy alone. The one operator dosed as a **count** rather than a rate |

---

# Reading the status honestly

**What ✅ does and does not mean.** It means the operator exists, is registered,
is covered by tests, and appears in `robustehr taxonomy`. It does **not** mean
the corruption is validated as realistic — that is a separate claim, and for the
four semantic operators the detector-quality line above is the honest bound.
`temporality_shift` and `experiencer_shift` rest on detectors with no published
gold; a result resting on them is resting on a component validated only against
this project's own two-LLM annotation and should say so.

**Why 🟡 names the missing half.** A partial row reported as implemented is worse
than one reported as absent, because a reader plans around it. Each 🟡 above
states what exists and what does not, on separate lines. Two rows moved between
categories when the reconciliation was recounted against the source: sentence
duplication (row 6) rose from ❌ to 🟡 because `discourse.section_duplicate`
exists, and medication substitution (row 29) fell from ✅ to 🟡 because the
source's example is same-class substitution, which is not built.

**The severity column ⚠.** The source's suggested severities are preserved where
the denominator is the same; where the package dosed a row on a different unit,
the ladder shown is the operator's own (`low / medium / high`). Either way the
denominator is eligible units rather than the document. `dose.jsonl` records the
whole chain — `total_n → scope_n → protected_n → eligible_n → requested_k →
applied_n` — so a dose that could not be delivered is visible rather than
silently rounded down.

## Where to go next

| you want | read |
|---|---|
| the source taxonomy this table reconciles | [source-taxonomy.md](source-taxonomy.md) |
| how to run any of this | [pipeline.md](pipeline.md) |
| the axes and why they are separate | [corruption-catalogue.md](corruption-catalogue.md) |
| what a corpus looks like before corruption | `robustehr describe --markdown` |
| the phenotype concept sets | [phenotype-concept-table.md](../validation/phenotype/phenotype-concept-table.md) |
