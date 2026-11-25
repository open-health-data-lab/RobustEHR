# The source taxonomy — the a priori design the package was built against

This is the corruption taxonomy drafted by the study team **before** any operator was
implemented. It is reproduced verbatim from the internal design document
(`prd/taxonomy.md`, removed from the working tree in commit `050a009`; recover the original
with `git show 050a009^:prd/taxonomy.md`). It is an internal document, not a published
source, and it is kept here so that the reconciliation in
[corruption-taxonomy-status.md](corruption-taxonomy-status.md) — which classifies every one
of its **29 substantive rows** as implemented, partial or not built — has a referent a reader
can check without leaving the repository.

Two things the implementation changed are worth knowing before reading it:

- the two-way "domain" column (structural / syntactic / semantic) crossed with the
  preserving / altering split became three independent axes — level, channel, contract
  (see [corruption-catalogue.md](corruption-catalogue.md) §1);
- the "what to hit" embedded in several rows ("10% of >2 letter words", "eligible
  assertions") became a separate `--target` argument, so one operator serves every target.

Row numbering below is added for the reconciliation; the tables are otherwise unchanged.

---

Phenotype preserving corruptions

1) Sentence / document level corruptions

| # | Domain | Corruption subtype | What it simulates | Deterministic method | Example transformation | Suggested severity |
|---| ----- | ----- | ----- | ----- | ----- | ----- |
| 1 | **Structural** | Section header deletion | Loss of note structure from EHR export or summarization | Regex-detect headers, remove selected headers only | `Past Medical History:` → removed, content preserved | 10, 30, 50 % of headers removed |
| 2 | **Structural** | Section header renaming | Non-standard section labels | Regex header replacement using synonym dictionary | `Assessment and Plan:` → `Clinical Impression:` | 10%, 30%, 50% headers |
| 3 | **Structural** | Bullet-to-prose conversion | Loss of list formatting | Regex-detect bullet lists, join with semicolons | `- COPD - HF - DM2` → `COPD; HF; DM2.` | 10%, 30%, 50% lists |
| 4 | **Structural** | Loss of text structure | Loss of breaks between sections | Remove line breaks, indentation, extra spacing |  | 10, 30, 50% of paragraphs |
| 5 | **Syntactic** | Spacing loss | Copy-paste loss of formatting | Remove spaces between words | `Denies chest pain -> Denieschestpain` | 10,30,50% of spaces |
| 6 | **Structural** | Sentence duplication | Copy-forward and note bloat | Duplicate selected sentence/block using seeded sampling | `Denies chest pain.` → repeated twice | 1, 3, 5 repetitions per paragraph |
|  |  |  |  |  |  |
| 7 | **Syntactic** | Punctuation loss (i.e. OCR) | Punctuation loss | Delete punctuation marks | `Remove “.”` | 10, 30, 50% punctuation marks |
| 8 | **Syntactic** | Punctuation gain (i.e. OCR) | Punctuation gain | Add random punctuation marks | `Add “,” or “!”` | 1,3,5 marks per paragraph |
| 9 | **Semantic** | Paraphrasing | Reflects varied language use in unstructured text | Hard to implement w/o complete tokenization | `Denies chest pain` \< \- \> `reports no chest pain` | 10%, 30%, 50% eligible assertions |
|  |  |  |  |  |  |

2) Word-level corruptions (Need to be able to do that in two modes : 1\) clinical 2\) non-clinical words)

| 10 | Semantic | Use of synonyms | Meaning preserving word change | Change candidate word for synonym (TextFooler or sketch engine w/ SNOMED-CT database?) | Anti-hypertensive medication \-\> hypotensive medication | 10%, 30%, 50% of candidate words |
|---| :---- | :---- | :---- | :---- | :---- | :---- |
| 11 | **Syntactic** | Switch between numeral and textual values | Numeral \-\> alphabetical usage variability | Deterministic transformation | `EF 30 % -> EF thirty percent` | 10%, 30%, 50% eligible values |
| 12 | **Syntactic** | Spacing | Misplaced spacing | `Add empty space in random words` | `Patient -> Pat_ient` | 10, 30, 50% of \> 3 letter words |
| 13 | **Syntactic** | Spelling error | Common spelling errors | Wikipedia corpus of common misspellings | Hemorrhage \-\> hemorage / hemorhage | 10, 30, 50% of candidate words |
| 14 | **Syntactic** | Abbreviations | Uneven use of abbreviations | Dictionary of common medical abbreviations (CASI UMN inventory or Meta-Inventory (https://zenodo.org/records/4567594) ) | MI \-\> myocardial infarction | 10, 30, 50% of candidates |

3) Token level perturbation (Need to be able to do that in two modes : 1\) clinical 2\) non-clinical words)

| 15 | Syntactic | Typographical error | Common typing mistakes | Insert / delete / replace / transpose / double letter / insert random character (TextBugger) | Random \-\> Randm \-\> Randmo \-\> Randcm \-\> Randoom \-\> Rand%m | 10, 30, 50 % of \> 2 letter words |
|---| :---- | :---- | :---- | :---- | :---- | :---- |
| 16 | **Syntactic** | Capitalization | Loss of capitalization | Remove all caps or random capitalization | The car \-\> the car \-\> tHe Car | 10, 30, 50% of letters |
| 17 | **Syntactic** | Diacritic | Loss of diacritic specificity | Remove all diacritic marks (rare in English) | Guillain-Barré \-\> Guillain-Barre | 10, 30, 50% of diacritic marks |
| 18 | **Syntactic** | Homoglyphs | OCR errors | Change frequent OCR mistakes | Apple \-\> App1e; rn \-\> m | 10, 30, 50% of characters |

### 

Potentially phenotype altering corruptions

For these, the pipeline must identify for a given phenotype of interest all its related entities to properly corrupt meaningful sections or words of a document.

1) Sentence level

| 19 | Structural | Sentence deletion / omission | Summarization loss | Delete selected sentences by seeded sampling | `History of acute pulmonary edema.` removed from note | 1%, 3%, 5% sentences |
|---| :---- | :---- | :---- | :---- | :---- | :---- |
|  |  |  |  |  |  |
| 20 | **Semantic / clinical** | Negation deletion / insertion | Lost / gained negation cue from ASR or summarization | Regex replace or inserts negated phrases before symptom dictionary | `Denies chest pain` \< \- \> `Reports chest pain` | 1%, 3%, 5% eligible assertions |
| 21 | **Semantic / clinical** | Uncertainty flip | Loss or addition of diagnostic uncertainty | Phrase dictionary for uncertainty cues | `Possible pneumonia` → `Pneumonia` | 1%, 3%, 5% eligible diagnoses |
| 22 | **Semantic / clinical** | Temporality shift | Current vs historical condition confusion | Regex mappings for temporal cues | `History of PE` → `Active PE` | 1%, 3%, 5% eligible temporal assertions |
| 23 | **Semantic / clinical** | Sensitive attributesSex / demographic inconsistency | Demographic contradiction | Sex or gender race or ethnicity Age Disability Socioeconomic status Sexual orientationPronoun and sex-specific term mapping | `male` → `female`; `prostate cancer` → `ovarian cancer` | 1%, 3%, 5% eligible spans |
| 24 | **Semantic / clinical** | Social history corruption | SDOH/substance-use documentation error | Phrase replacement dictionaries |  | 1%, 3%, 5% eligible social-history assertions |

### 

2) Word level

| 25 | Syntactic | Word deletion / omission | Summarization loss | Delete selected word by seeded sampling | `Ejection fraction -> removed from note` | 1, 3, 5% of words |
|---| :---- | :---- | :---- | :---- | :---- | :---- |
| 26 | **Structural** | Word order | Word order loss | Switch adjacent words | `Ejection fraction -> Fraction ejection` | 10,30,50% of words |
| 27 | **Semantic** | Mistaken use of homophones | Meaning preserving homophone | Change candidate word for homophone (datamuse API) | Ileum \-\> Ilium | 10, 30, 50% of candidate words |
| 28 | **Semantic** | Embedding-based substitutions | Synthetic | Switch word with adjacent word in vector space (GloVe) | `Denies chest pain -> Disowns chest pain` | 10, 30, 50 % words |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
| 29 | **Semantic / clinical** | Medication name substitution | Drug recognition or summarization error | Curated same-class / high-risk substitution dictionary | `Warfarin` → `Apixaban` | 1%, 3%, 5% eligible meds |

### 

