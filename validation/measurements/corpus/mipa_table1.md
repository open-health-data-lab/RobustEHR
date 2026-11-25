# Table 1 — characteristics of golden_notes.csv

**1,388 notes.** Rows are the structural levels an operator can target; indented rows decompose the row above them. `Share` is of the level's own denominator, named in the row. Medians with IQR, never means — note lengths are right-skewed, so a mean describes a note that does not exist.

| Characteristic | Per note, median [IQR] | Total | Share |
|---|---:|---:|---:|
| **Document** | 1 [1-1] | 1,388 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Lines | 322 [257-398] | 465,368 |  |
| **Sections** | 34 [31-38] | 48,698 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Canonical ids present, of 58 declared |  | 35 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Absent — a fact about the corpus, not a missing row |  | 23 |  |
| **Headers** | 27 [24-31] | 38,535 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Heading-shaped lines in total | 50 [40-59] | 70,208 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Excluded — exam subsections, pharmacy boilerplate | 23 [14-30] | 31,673 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Resolved to a named section | 27 [24-30] | 38,387 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`admission_date` | 41 | 1,388 | 1.000 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`allergies` | 48 | 1,388 | 1.000 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`date_of_birth` | 27 | 1,388 | 1.000 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`name` | 38 | 1,388 | 1.000 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`discharge_condition` | 129 | 1,386 | 0.999 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`service` | 10 | 1,386 | 0.999 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`attending` | 6 | 1,385 | 0.998 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`discharge_instructions` | 789 | 1,382 | 0.996 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`surgical_procedures` | 9 | 1,380 | 0.994 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`discharge_disposition` | 17 | 1,376 | 0.991 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`past_medical_history` | 410 | 1,369 | 0.986 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`history_present_illness` | 1,304 | 1,368 | 0.986 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`discharge_medications` | 983 | 1,367 | 0.985 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`followup_instructions` | 5 | 1,363 | 0.982 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`pertinent_results` | 441 | 1,360 | 0.980 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`social_history` | 5 | 1,354 | 0.976 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`discharge_diagnoses` | 66 | 1,353 | 0.975 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`family_history` | 99 | 1,353 | 0.975 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`chief_complaint` | 23 | 1,352 | 0.974 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`physical_examination` | 654 | 1,335 | 0.962 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`admission_medications` | 555 | 1,295 | 0.933 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`hospital_course` | 2,199 | 1,225 | 0.883 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`facility` | 7 | 733 | 0.528 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`imaging` | 184 | 701 | 0.505 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`laboratory_results` | 659 | 658 | 0.474 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;_… 10 further sections; see the JSON_ |  |  |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Heuristic match, section unknown | 0 [0-0] | 148 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Standalone, on its own line — `render.header_delete` | 21 [18-24] | 29,661 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Inline (`Service: MEDICINE`) — deletion would take the value | 6 [5-7] | 8,874 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Has another clinical name — `render.header_rename` | 23 [20-26] | 32,826 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Substantive — at least 60 characters of body beneath it | 12 [10-14] | 17,434 |  |
| **Structural breaks** | 157 [125-198] | 230,478 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Paragraph (blank-line separated) | 37 [30-47] | 55,163 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Line | 119 [91-155] | 175,315 |  |
| **Sentences** | 252 [200-318] | 365,470 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Prose | 168 [128-218] | 247,649 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Layout (lab rows, lists) | 82 [63-105] | 117,821 |  |
| **Lists** | 18 [12-27] | 28,270 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Two or more items — render.list_to_prose | 6 [3-8] | 8,511 |  |
| **List items** | 42 [26-61] | 62,388 |  |
| **Aligned blocks** | 9 [7-11] | 12,673 |  |
| **Column gaps (runs of 2+ spaces)** | 64 [42-90] | 96,803 |  |
| **Word gaps (a single space between two words)** | 749 [552-1,026] | 1,125,001 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;All single spaces | 1,611 [1,229-2,057] | 2,335,979 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;In layout, not prose | 351 [247-470] | 507,362 |  |
| **De-identification placeholders** | 63 [46-83] | 94,122 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Per 1,000 characters | 5 [5-7] |  |  |
| **Concept mentions (spans)** | 622 [474-780] | 891,293 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Distinct CUIs per note | 329 [275-397] |  |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Mentions per 1,000 content tokens | 344 [331-359] |  |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Length in tokens — the bridge to the token level |  |  |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;1 token(s) |  | 748,063 | 0.839 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;2 token(s) |  | 99,828 | 0.112 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3 token(s) |  | 34,919 | 0.039 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;4+ token(s) |  | 8,483 | 0.009 |
| &nbsp;&nbsp;&nbsp;&nbsp;Semantic category (leaf categories; may overlap slightly) |  |  |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;anatomy |  | 146,477 | 0.164 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;device |  | 20,102 | 0.023 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;diagnostic_procedure |  | 64,577 | 0.072 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;disease |  | 140,312 | 0.157 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;finding |  | 190,884 | 0.214 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;lab_measurement |  | 50,920 | 0.057 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;lab_result |  | 7,254 | 0.008 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;medication |  | 155,012 | 0.174 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;symptom |  | 49,479 | 0.056 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;therapeutic_procedure |  | 52,244 | 0.059 |
| &nbsp;&nbsp;&nbsp;&nbsp;Rollups — these CONTAIN rows above and must not be added to them |  |  |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;disorder (= disease + finding + symptom) |  | 380,675 | 0.427 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;procedure (= diagnostic_procedure + therapeutic_procedure) |  | 184,571 | 0.207 |
| **— of which medications, by how they are named** | 108 [81-139] | 155,012 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Population |  | UMLS medication mentions |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Named generically | 19 [11-28] | 28,996 | 0.187 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Named commercially | 7 [4-11] | 11,049 | 0.071 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Representation undetermined | 80 [61-101] | 114,967 | 0.742 |
| &nbsp;&nbsp;&nbsp;&nbsp;Substitutable — `lexical.medication_rename` acts here | 27 [17-38] | 40,045 | 0.258 |
| **Numeric values** | 105 [76-133] | 148,824 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;All numeric tokens | 191 [139-244] | 272,288 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Decimal — no exact written form | 38 [25-52] | 55,677 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Unit-bearing — excluded unless mode=all | 34 [23-47] | 50,166 |  |
| **Content tokens, by clinical salience** | 1,611 [1,228-2,045] | 2,329,159 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Clinical — salience >= 0.50, or a curated drug | 367 [279-482] | 541,240 | 0.242 |
| &nbsp;&nbsp;&nbsp;&nbsp;Non-clinical — ordinary English below that | 1,170 [895-1,497] | 1,698,388 | 0.758 |
| &nbsp;&nbsp;&nbsp;&nbsp;Unmeasured — never seen often enough to score | 58 [40-81] | 89,531 |  |
| **Tokens** | 4,477 [3,401-5,671] | 6,423,279 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Words | 1,599 [1,216-2,028] | 2,307,567 | 0.359 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;≥3 chars — `input.typo` acts here | 1,254 [957-1,597] | 1,818,582 | 0.283 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;≥4 chars — `control.char_shuffle` acts here | 977 [741-1,242] | 1,418,774 | 0.221 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Holding an OCR-confusable glyph (exposure, not the dose) | 1,608 [1,227-2,043] | 2,321,324 | 0.361 |
| &nbsp;&nbsp;&nbsp;&nbsp;Upper-case short forms (shape only) | 176 [121-230] | 250,085 | 0.039 |
| &nbsp;&nbsp;&nbsp;&nbsp;Numeric | 191 [139-244] | 272,289 | 0.042 |
| &nbsp;&nbsp;&nbsp;&nbsp;Alphanumeric | 14 [9-20] | 21,592 | 0.003 |
| &nbsp;&nbsp;&nbsp;&nbsp;Punctuation | 2,659 [2,020-3,386] | 3,821,831 | 0.595 |
| &nbsp;&nbsp;&nbsp;&nbsp;Content tokens | 1,801 [1,376-2,294] | 2,601,447 | 0.405 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Inside a UMLS concept | 753 [580-944] | 1,083,637 | 0.417 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;anatomy |  | 164,251 | 0.063 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;device |  | 22,760 | 0.009 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;diagnostic_procedure |  | 73,456 | 0.028 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;disease |  | 173,083 | 0.067 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;disorder |  | 470,693 | 0.181 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;finding |  | 238,257 | 0.092 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;lab_measurement |  | 55,175 | 0.021 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;lab_result |  | 8,162 | 0.003 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;medication |  | 209,655 | 0.081 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;procedure |  | 211,581 | 0.081 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;symptom |  | 59,358 | 0.023 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;therapeutic_procedure |  | 62,070 | 0.024 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Abbreviation-shaped | 202 [144-259] | 285,508 | 0.110 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Ambiguous (≥2 UMLS senses) | 83 [59-107] | 116,148 | 0.407 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Highly ambiguous (≥5) | 29 [19-41] | 42,431 | 0.149 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;0 UMLS senses |  | 99,193 | 0.347 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;1 UMLS senses |  | 70,167 | 0.246 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;2-4 UMLS senses |  | 73,717 | 0.258 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;5-9 UMLS senses |  | 11,823 | 0.041 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;10+ UMLS senses |  | 30,608 | 0.107 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Unrecognised, ≥4 chars (near-miss candidates) | 58 [41-78] | 86,559 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Within one edit of a known term — NOT a misspelling rate | 32 [22-43] | 46,438 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Distinct surfaces |  | 5,440 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Distinct hapax — the usable subset |  | 3,355 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Lexical class (partitions content tokens) |  |  |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;function_word |  | 650,865 | 0.250 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;general_english |  | 612,157 | 0.235 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;numeric_or_symbol |  | 272,288 | 0.105 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;out_of_vocabulary |  | 1,066,137 | 0.410 |
| **Characters** | 11,557 [8,800-14,774] | 16,731,456 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Alphabetic | 8,139 [6,179-10,441] | 11,872,460 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Digit | 391 [284-505] | 562,870 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Whitespace | 2,128 [1,658-2,724] | 3,116,425 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Punctuation | 802 [593-1,058] | 1,179,700 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;OCR-confusable positions — `input.ocr_confusion` acts here | 5,822 [4,413-7,496] | 8,490,171 |  |
| **Assertion cues** | 60 [46-77] | 87,444 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Eligible cues per operator — the dose denominator |  |  |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`semantic.negation_flip` | 35 [25-48] | 52,609 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`semantic.uncertainty_flip` | 9 [5-13] | 13,285 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`semantic.temporality_shift` | 10 [8-13] | 14,873 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`semantic.experiencer_shift` | 4 [3-6] | 6,677 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;Mentions carrying an attribute (a different population) |  | 896,110 |  |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;family |  | 9,137 | 0.010 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;historical |  | 16,632 | 0.019 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;negated |  | 76,434 | 0.085 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;uncertain |  | 24,927 | 0.028 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;unmodified |  | 768,980 | 0.858 |

## What the lexical classes mean

They partition **content tokens** and are named for what they test, which is vocabulary membership rather than correctness.

**`function_word`** — A closed-class word — `the`, `of`, `was` — from the shipped function-word list. Grammar rather than content, and the tightest control condition available: corrupting only these should move nothing.

**`general_english`** — In `english_vocabulary.txt`: 28,329 words with a wordfreq Zipf score of at least 3.0, i.e. ordinary written English, **with nothing subtracted**. A word here is common English; it may also be clinical (`fever`, `wound`, `stable` all qualify), so this is not the non-clinical class.

**`out_of_vocabulary`** — **Not in that general-English list — which on clinical text mostly means clinical.** `furosemide`, `HFrEF` and `pneumothorax` all land here, and so do genuine misspellings and de-identification artifacts. It is a vocabulary statement, not an error rate; the near-miss row below is the closest thing to the latter, and carries its own precision caveat.

**`numeric_or_symbol`** — A content token carrying no letter — a lab value, a dose, a date fragment.


## What each level is

The level decides the **denominator of a dose**: "30%" means 30% of the eligible units *of that level*, so two operators at one severity touch very different amounts of text. Sub-rows naming an operator are that operator's own eligible count.

**Document** — The whole note.

**Sections** — A section-kind header **plus the body beneath it**, to the next header at the same or shallower depth. More sections than section-kind headers is normal: the text before the first header, and any gap between two sections, is tiled as `_preamble` / `_interstitial` so every character belongs to exactly one.

**Headers** — The heading **line itself** — label plus its colon, not the content under it. **Counted here as SECTION HEADERS only**, which is the population all three header operators run on. Heading-shaped lines that are not note structure — exam subsections (`HEENT:`, `CV:`) and pharmacy boilerplate (`Disp:`, `Refills:`, which appear in a quarter of notes) — are reported as a sub-row and excluded, because counting them made "delete 30% of headers" mean something different in every note. `Substantive` narrows once more, to headers with real content beneath them: a `Facility:` whose body is a de-identification mask is present to a parser and absent to a reader, so deleting it is a corruption nobody can observe.

**Structural breaks** — The whitespace separating one block from the next — **not every newline**. A hard-wrapped sentence spans several lines and those newlines are continuations, not structure; boundaries interior to a list or lab table belong to other operators and are excluded here.

**Sentences** — Sentences over the token stream, split into narrative prose and layout lines.

**Lists** — A run of consecutive items sharing one marker style. One list, not one item.

**List items** — A single marked item inside such a block.

**Aligned blocks** — A run of lines whose **column layout carries meaning** — a lab table, or the `Name: ___   Unit No: ___` header. Re-spacing one can re-associate a value with the wrong label, which is why it is measured apart from prose whitespace.

**Column gaps (runs of 2+ spaces)** — A run of **two or more** horizontal spaces — the gap that holds a lab table's columns apart. Collapsing one to a single space loses the alignment but no word boundary, so it is reference-preserving.

**Word gaps (a single space between two words)** — A **single** space separating two words in prose — the gap that keeps `chest` and `pain` apart. Deleting one merges two words, which no token projection survives, so it is a different operator and a weaker contract than the column gaps above.

**De-identification placeholders** — A de-identification mask, whatever convention the corpus uses.

**Concept mentions (spans)** — A concept mention returned by the matcher. A **span, not a token**: `acute on chronic systolic heart failure` is one mention over six tokens. Categories are listed as leaves; `disorder` and `procedure` are unions of leaves above them and are shown separately as rollups so nothing is counted twice.

**— of which medications, by how they are named** — The `medication` category above, decomposed by how each mention is *written*. Not a second count of drugs — the same mentions, classified.

**Numeric values** — Integer tokens with an exact written form. Decimals and unit-bearing values are counted but excluded from the default denominator.

**Content tokens, by clinical salience** — Content tokens split by **measured clinical salience** — the rate at which a token falls inside a span a clinician adjudicated as a clinical concept, on MIMIC-IV discharge summaries, plus a curated drug vocabulary for what that benchmark under-annotates (it marks only 27% of medication mentions). The level a *targeted* corruption is judged on: `clinical_share` says whether what changed was clinical content or prose. Untargeted corruption moves this share barely at all; clinically-targeted corruption moves it a great deal. `unmeasured` is kept separate rather than folded into either side. Method and limits — corpus-bound, token-level, context-blind — in `docs/validation-protocol.md` §9.

**Tokens** — Every token, including whitespace and punctuation; content tokens are the subset.

**Characters** — Every character in the note.

**Assertion cues** — A negation, uncertainty, temporality or experiencer cue span.


## Section inventory — which named sections this corpus has

**35 of 58 declared canonical sections occur.** Absence is a fact about the corpus, not a missing row — the sections the lexicon knows and these notes never use are listed after the table.

| section | kind | notes with it | share of notes | body chars, median |
|---|---|---:|---:|---:|
| `admission_date` | metadata | 1,388 | 1.000 | 41 |
| `allergies` | clinical | 1,388 | 1.000 | 48 |
| `date_of_birth` | metadata | 1,388 | 1.000 | 27 |
| `name` | metadata | 1,388 | 1.000 | 38 |
| `discharge_condition` | clinical | 1,386 | 0.999 | 129 |
| `service` | metadata | 1,386 | 0.999 | 10 |
| `attending` | metadata | 1,385 | 0.998 | 6 |
| `discharge_instructions` | clinical | 1,382 | 0.996 | 789 |
| `surgical_procedures` | clinical | 1,380 | 0.994 | 9 |
| `discharge_disposition` | clinical | 1,376 | 0.991 | 17 |
| `past_medical_history` | clinical | 1,369 | 0.986 | 410 |
| `history_present_illness` | clinical | 1,368 | 0.986 | 1,304 |
| `discharge_medications` | clinical | 1,367 | 0.985 | 983 |
| `followup_instructions` | clinical | 1,363 | 0.982 | 5 |
| `pertinent_results` | clinical | 1,360 | 0.980 | 441 |
| `social_history` | clinical | 1,354 | 0.976 | 5 |
| `discharge_diagnoses` | clinical | 1,353 | 0.975 | 66 |
| `family_history` | clinical | 1,353 | 0.975 | 99 |
| `chief_complaint` | clinical | 1,352 | 0.974 | 23 |
| `physical_examination` | clinical | 1,335 | 0.962 | 654 |
| `admission_medications` | clinical | 1,295 | 0.933 | 555 |
| `hospital_course` | clinical | 1,225 | 0.883 | 2,199 |
| `facility` | clinical | 733 | 0.528 | 7 |
| `imaging` | clinical | 701 | 0.505 | 184 |
| `laboratory_results` | clinical | 658 | 0.474 | 659 |
| `assessment_plan` | clinical | 607 | 0.437 | 165 |
| `review_of_systems` | clinical | 443 | 0.319 | 61 |
| `transitional_issues` | clinical | 372 | 0.268 | 448 |
| `microbiology` | clinical | 233 | 0.168 | 211 |
| `past_surgical_history` | clinical | 216 | 0.156 | 113 |
| `past_oncologic_history` | clinical | 99 | 0.071 | 1,235 |
| `objective` | clinical | 9 | 0.006 | 53 |
| `subjective` | clinical | 3 | 0.002 | 41 |
| `discharge_date` | metadata | 1 | 0.001 | 5 |
| `sex` | metadata | 1 | 0.001 | 4 |

**Declared but never seen:** `admin_contact`, `discharge_status`, `exam_abdomen`, `exam_access`, `exam_cardiac`, `exam_extremities`, `exam_general`, `exam_gi`, `exam_gu`, `exam_heent`, `exam_msk`, `exam_neuro`, `exam_psych`, `exam_pulmonary`, `exam_skin`, `family_member`, `report_field`, `rx_dispense`, `rx_refills`, `rx_sig`, `unit_number`, `vital_signs`, `vitals_detail`

**Seen but not in the lexicon:** `_interstitial`, `_preamble` — these are template headers the lexicon is behind on, which is a property of the lexicon rather than of the notes.

---

# Table 2 — UMLS concepts per phenotype, declared and found

`Runtime` is the set the annotator actually carries — seeds expanded through the SNOMED hierarchy plus the medication, finding and vetting-gated proposed facets, what `--target pheno=` selects. `Declared` is the full faceted definition from the audit. The two agree wherever the facet artifacts are installed; a difference means the runtime fell back to the disorder closure, and any zero in a category it never carried says nothing about the notes. `Found` is evidence recovered in the cohort of notes an expert labelled POSITIVE for that phenotype.


## alcohol_abuse — 155 positive notes

**`alcohol_use_disorder`** — 82 concepts at runtime of 82 declared; 489 evidence spans found in 132 of these 155 notes (set recall 0.500).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 3 | 1 | 0.33 |
| disease | 48 | 243 | 5.06 |
| disorder | 69 | 470 | 6.81 |
| finding | 13 | 18 | 1.38 |
| lab_measurement | 4 | 1 | 0.25 |
| lab_result | 1 | 0 | 0.00 |
| medication | 5 | 17 | 3.40 |
| procedure | 6 | 2 | 0.33 |
| symptom | 8 | 209 | 26.12 |
| therapeutic_procedure | 2 | 1 | 0.50 |
| uncategorised | 1 | 0 | 0.00 |
| **total** | **82** | **489** | |

## c_diff_complication — 42 positive notes

**`clostridioides_difficile`** — 45 concepts at runtime of 45 declared; 720 evidence spans found in 42 of these 42 notes (set recall —).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 4 | 26 | 6.50 |
| disease | 13 | 71 | 5.46 |
| disorder | 35 | 535 | 15.29 |
| finding | 10 | 63 | 6.30 |
| lab_measurement | 2 | 17 | 8.50 |
| medication | 3 | 153 | 51.00 |
| procedure | 7 | 32 | 4.57 |
| symptom | 12 | 401 | 33.42 |
| therapeutic_procedure | 3 | 6 | 2.00 |
| **total** | **45** | **720** | |

## c_diff_past — 101 positive notes

**`clostridioides_difficile`** — 45 concepts at runtime of 45 declared; 1,345 evidence spans found in 99 of these 101 notes (set recall —).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 4 | 50 | 12.50 |
| disease | 13 | 83 | 6.38 |
| disorder | 35 | 1,060 | 30.29 |
| finding | 10 | 102 | 10.20 |
| lab_measurement | 2 | 20 | 10.00 |
| medication | 3 | 221 | 73.67 |
| procedure | 7 | 64 | 9.14 |
| symptom | 12 | 875 | 72.92 |
| therapeutic_procedure | 3 | 14 | 4.67 |
| **total** | **45** | **1,345** | |

## dementia — 102 positive notes

**`dementia`** — 346 concepts at runtime of 346 declared; 669 evidence spans found in 101 of these 102 notes (set recall 0.867).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 9 | 52 | 5.78 |
| disease | 296 | 416 | 1.41 |
| disorder | 311 | 510 | 1.64 |
| finding | 9 | 0 | 0.00 |
| lab_measurement | 3 | 0 | 0.00 |
| medication | 24 | 102 | 4.25 |
| procedure | 10 | 57 | 5.70 |
| symptom | 6 | 94 | 15.67 |
| uncategorised | 1 | 0 | 0.00 |
| **total** | **346** | **669** | |

## depression — 679 positive notes

**`depression`** — 375 concepts at runtime of 375 declared; 2,740 evidence spans found in 573 of these 679 notes (set recall 0.111).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 4 | 6 | 1.50 |
| disease | 218 | 70 | 0.32 |
| disorder | 252 | 1,112 | 4.41 |
| finding | 31 | 363 | 11.71 |
| lab_measurement | 3 | 6 | 2.00 |
| medication | 109 | 1,333 | 12.23 |
| procedure | 12 | 295 | 24.58 |
| symptom | 3 | 679 | 226.33 |
| therapeutic_procedure | 7 | 289 | 41.29 |
| uncategorised | 2 | 0 | 0.00 |
| **total** | **375** | **2,740** | |

## diabetes_type_1 — 135 positive notes

**`type_1_diabetes`** — 120 concepts at runtime of 120 declared; 1,292 evidence spans found in 131 of these 135 notes (set recall 0.625).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| anatomy | 2 | 0 | 0.00 |
| diagnostic_procedure | 13 | 56 | 4.31 |
| disease | 44 | 164 | 3.73 |
| disorder | 67 | 941 | 14.04 |
| finding | 15 | 16 | 1.07 |
| lab_measurement | 13 | 56 | 4.31 |
| lab_result | 1 | 0 | 0.00 |
| medication | 36 | 295 | 8.19 |
| procedure | 14 | 56 | 4.00 |
| symptom | 8 | 761 | 95.12 |
| **total** | **120** | **1,292** | |

## diabetes_type_2 — 393 positive notes

**`type_2_diabetes`** — 164 concepts at runtime of 164 declared; 1,418 evidence spans found in 346 of these 393 notes (set recall 0.222).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 11 | 88 | 8.00 |
| disease | 49 | 247 | 5.04 |
| disorder | 72 | 517 | 7.18 |
| finding | 15 | 33 | 2.20 |
| lab_measurement | 9 | 88 | 9.78 |
| lab_result | 1 | 0 | 0.00 |
| medication | 78 | 809 | 10.37 |
| procedure | 13 | 92 | 7.08 |
| symptom | 8 | 237 | 29.62 |
| therapeutic_procedure | 1 | 4 | 4.00 |
| **total** | **164** | **1,418** | |

## hfpef — 217 positive notes

**`hfpef`** — 96 concepts at runtime of 96 declared; 2,204 evidence spans found in 212 of these 217 notes (set recall 0.000).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 6 | 89 | 14.83 |
| disease | 17 | 325 | 19.12 |
| disorder | 36 | 1,478 | 41.06 |
| finding | 12 | 496 | 41.33 |
| lab_measurement | 1 | 0 | 0.00 |
| medication | 53 | 632 | 11.92 |
| procedure | 7 | 94 | 13.43 |
| symptom | 7 | 657 | 93.86 |
| therapeutic_procedure | 1 | 5 | 5.00 |
| **total** | **96** | **2,204** | |

## hfref — 122 positive notes

**`hfref`** — 126 concepts at runtime of 126 declared; 1,652 evidence spans found in 118 of these 122 notes (set recall 0.000).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 9 | 86 | 9.56 |
| disease | 14 | 136 | 9.71 |
| disorder | 38 | 776 | 20.42 |
| finding | 17 | 288 | 16.94 |
| lab_measurement | 1 | 0 | 0.00 |
| medication | 76 | 789 | 10.38 |
| procedure | 12 | 87 | 7.25 |
| symptom | 7 | 352 | 50.29 |
| therapeutic_procedure | 3 | 1 | 0.33 |
| **total** | **126** | **1,652** | |

## hypertension — 940 positive notes

**`hypertension`** — 609 concepts at runtime of 609 declared; 12,173 evidence spans found in 938 of these 940 notes (set recall 0.817).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 2 | 1 | 0.50 |
| disease | 343 | 3,210 | 9.36 |
| disorder | 390 | 7,358 | 18.87 |
| finding | 36 | 397 | 11.03 |
| lab_measurement | 1 | 0 | 0.00 |
| lab_result | 1 | 0 | 0.00 |
| medication | 213 | 4,329 | 20.32 |
| procedure | 3 | 486 | 162.00 |
| symptom | 11 | 3,751 | 341.00 |
| uncategorised | 2 | 0 | 0.00 |
| **total** | **609** | **12,173** | |

## metastatic_cancer — 168 positive notes

**`metastatic_cancer`** — 1,291 concepts at runtime of 1,291 declared; 1,549 evidence spans found in 157 of these 168 notes (set recall 0.463).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| anatomy | 2 | 0 | 0.00 |
| diagnostic_procedure | 11 | 92 | 8.36 |
| disease | 1,087 | 331 | 0.30 |
| disorder | 1,103 | 762 | 0.69 |
| finding | 4 | 23 | 5.75 |
| lab_measurement | 7 | 6 | 0.86 |
| medication | 165 | 662 | 4.01 |
| procedure | 22 | 125 | 5.68 |
| symptom | 12 | 408 | 34.00 |
| therapeutic_procedure | 11 | 33 | 3.00 |
| **total** | **1,291** | **1,549** | |

## obesity — 286 positive notes

**`obesity`** — 154 concepts at runtime of 154 declared; 746 evidence spans found in 266 of these 286 notes (set recall 1.000).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 3 | 0 | 0.00 |
| disease | 89 | 643 | 7.22 |
| disorder | 112 | 708 | 6.32 |
| finding | 16 | 11 | 0.69 |
| lab_measurement | 2 | 2 | 1.00 |
| lab_result | 1 | 2 | 2.00 |
| medication | 32 | 31 | 0.97 |
| procedure | 7 | 5 | 0.71 |
| symptom | 7 | 54 | 7.71 |
| therapeutic_procedure | 4 | 5 | 1.25 |
| uncategorised | 2 | 0 | 0.00 |
| **total** | **154** | **746** | |

## rheumatoid_arthritis — 164 positive notes

**`rheumatoid_arthritis`** — 416 concepts at runtime of 416 declared; 1,079 evidence spans found in 159 of these 164 notes (set recall —).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 7 | 2 | 0.29 |
| disease | 268 | 264 | 0.99 |
| disorder | 281 | 328 | 1.17 |
| finding | 9 | 4 | 0.44 |
| lab_measurement | 5 | 1 | 0.20 |
| medication | 123 | 712 | 5.79 |
| procedure | 10 | 39 | 3.90 |
| symptom | 4 | 60 | 15.00 |
| therapeutic_procedure | 3 | 37 | 12.33 |
| uncategorised | 2 | 0 | 0.00 |
| **total** | **416** | **1,079** | |

## sle — 113 positive notes

**`systemic_lupus_erythematosus`** — 120 concepts at runtime of 120 declared; 1,034 evidence spans found in 111 of these 113 notes (set recall —).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 7 | 19 | 2.71 |
| disease | 51 | 156 | 3.06 |
| disorder | 72 | 697 | 9.68 |
| finding | 13 | 53 | 4.08 |
| lab_measurement | 6 | 0 | 0.00 |
| lab_result | 1 | 0 | 0.00 |
| medication | 37 | 307 | 8.30 |
| procedure | 9 | 30 | 3.33 |
| symptom | 8 | 488 | 61.00 |
| therapeutic_procedure | 2 | 11 | 5.50 |
| uncategorised | 1 | 0 | 0.00 |
| **total** | **120** | **1,034** | |

## vte_complication — 39 positive notes

**`deep_vein_thrombosis`** — 270 concepts at runtime of 270 declared; 187 evidence spans found in 34 of these 39 notes (set recall 0.679).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 12 | 8 | 0.67 |
| disease | 244 | 167 | 0.68 |
| disorder | 254 | 179 | 0.70 |
| finding | 4 | 4 | 1.00 |
| lab_measurement | 12 | 8 | 0.67 |
| lab_result | 1 | 0 | 0.00 |
| medication | 2 | 0 | 0.00 |
| procedure | 13 | 8 | 0.62 |
| symptom | 6 | 8 | 1.33 |
| therapeutic_procedure | 1 | 0 | 0.00 |
| **total** | **270** | **187** | |
**`pulmonary_embolism`** — 131 concepts at runtime of 131 declared; 456 evidence spans found in 39 of these 39 notes (set recall 0.360).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 16 | 35 | 2.19 |
| disease | 34 | 17 | 0.50 |
| disorder | 60 | 278 | 4.63 |
| finding | 15 | 77 | 5.13 |
| lab_measurement | 11 | 9 | 0.82 |
| medication | 52 | 143 | 2.75 |
| procedure | 18 | 35 | 1.94 |
| symptom | 11 | 184 | 16.73 |
| therapeutic_procedure | 2 | 0 | 0.00 |
| uncategorised | 1 | 0 | 0.00 |
| **total** | **131** | **456** | |

## vte_past — 312 positive notes

**`deep_vein_thrombosis`** — 270 concepts at runtime of 270 declared; 766 evidence spans found in 242 of these 312 notes (set recall 0.679).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 12 | 32 | 2.67 |
| disease | 244 | 679 | 2.78 |
| disorder | 254 | 734 | 2.89 |
| finding | 4 | 30 | 7.50 |
| lab_measurement | 12 | 32 | 2.67 |
| lab_result | 1 | 0 | 0.00 |
| medication | 2 | 0 | 0.00 |
| procedure | 13 | 32 | 2.46 |
| symptom | 6 | 25 | 4.17 |
| therapeutic_procedure | 1 | 0 | 0.00 |
| **total** | **270** | **766** | |
**`pulmonary_embolism`** — 131 concepts at runtime of 131 declared; 3,546 evidence spans found in 310 of these 312 notes (set recall 0.360).

| Semantic category | Concepts declared | Evidence spans found | Spans per declared concept |
|---|---:|---:|---:|
| diagnostic_procedure | 16 | 150 | 9.38 |
| disease | 34 | 105 | 3.09 |
| disorder | 60 | 2,499 | 41.65 |
| finding | 15 | 646 | 43.07 |
| lab_measurement | 11 | 39 | 3.55 |
| medication | 52 | 888 | 17.08 |
| procedure | 18 | 159 | 8.83 |
| symptom | 11 | 1,748 | 158.91 |
| therapeutic_procedure | 2 | 9 | 4.50 |
| uncategorised | 1 | 0 | 0.00 |
| **total** | **131** | **3,546** | |
