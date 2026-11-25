# What a run writes

`robustehr run --out DIR` writes three files and no note text:

| File | One row per | Purpose |
|---|---|---|
| `manifest.json` | run | what was run, on what, with which versions |
| `dose.jsonl` | note × operator × severity (a *cell*) | how much was asked for, how much was done, and where it landed |
| `edits.jsonl` | applied edit | the edit script: enough to rebuild every corrupted note |

`robustehr replay --run DIR --corpus NOTES` rebuilds each cell from
`edits.jsonl` and checks it against the cell's `output_sha256`.

Rates are written as integer pairs `[numerator, denominator]`, never as
floats, and `null` where the denominator is zero.

## `edits.jsonl`

| Field | Meaning |
|---|---|
| `run_id`, `note_uid`, `note_sha256` | the run, the note, and the SHA-256 of the note the offsets refer to |
| `op_id`, `op_version` | the operator that proposed the edit, and its version (resource digests included) |
| `cell_id` | the cell the edit belongs to. Equal to `op_id`, except under `--compose`, where it is `composite(a+b)` |
| `severity`, `scope` | the cell's severity and scope, as in `dose.jsonl` |
| `start`, `end` | character offsets into the **original** note, end exclusive |
| `replacement` | the text written over `[start, end)`. Empty for a deletion |
| `copy_from_start`, `copy_from_end` | for an edit that copies text already in the note (section duplication): the source range. The text itself is not stored |
| `unit_id` | the unit the operator selected, as `kind:start:end`, for example `word:274:286` |
| `rank` | the unit's position in the operator's selection order |
| `edit_id` | a digest identifying the proposed edit |
| `stage_index`, `op_priority`, `anchor`, `group_id`, `reflow`, `targets` | what the applier needs to order and place the edit exactly as the run did |

### Replacements are stored as their minimal difference

An operator that retypes a word proposes the whole word with one letter
changed. Written down like that, a typographical-error arm at 15% of words
would put 15% of the note's words into the edit script. So an edit is stored
with the characters it does not change stripped off:

```
proposed   start=274 end=286  replacement="hupertension"
stored     start=275 end=276  replacement="u"
```

`unit_id` keeps the word's boundaries. Before writing, each cell's trimmed
edits are applied and compared with the cell's `output_sha256`; a cell that
does not reproduce is stored as proposed and counted in the manifest under
`cells_stored_as_proposed`. Edits that copy, and edits whose replacement is
re-wrapped to the note's line width, are never trimmed.

### What an edit script reveals

An edit script copies no span of a note. It is still derived from the corpus,
and what it implies about the text depends on the operator. Lengths below
were measured on the 32 synthetic notes in `examples/demo_notes.csv` at
severity 0.30; `lexical.medication_rename` and the LLM operators made no edit
in that run and are described from their design:

| Operators | Stored replacement | What it implies about the note |
|---|---|---|
| `input.typo`, `input.ocr_confusion` | 1 character (2 for a transposition) | where words are; the new character, not the old one. A transposition or a doubled letter stores one or two original letters |
| `render.space_delete`, `render.header_delete`, `render.bullet_to_prose`, `discourse.sentence_delete`, `discourse.truncate` | empty | where a space, header, list marker or sentence was |
| `discourse.section_duplicate` | empty, with a source range | where a section starts and ends |
| `render.whitespace_collapse`, `render.break_removal`, `render.lab_block_collapse`, `render.list_to_prose` | 1–2 characters of whitespace or punctuation | layout only |
| `render.deid_restyle`, `render.header_style`, `render.header_rename` | a placeholder or a header, up to about 30 characters | that a placeholder or a recognised header stood there; a renamed header implies which |
| `semantic.*` (table form) | a cue, up to about 11 characters | that an assertion cue stood there, and what kind |
| `input.phonetic_confusion` | a few letters | part of the spelling of the word replaced |
| `lexical.numeral_to_word` | the number in words | the number that stood there |
| `lexical.medication_rename` | a drug name | which drug stood there |
| `control.char_shuffle` | the word's own letters, reordered | the letters of the word |
| `semantic.*_llm` | the changed part of a rewritten sentence | whatever the model rewrote; bounded by the 120-character cap |

No replacement may exceed 120 characters (`max_replacement_chars`); writing
refuses a longer one.

**Sharing.** Treat an edit script as data derived from the corpus. For a
corpus held under a data use agreement, share it on the terms the agreement
sets for derived data. Scripts from the first two rows carry positions and
substituted characters only; scripts from the last five rows say something
about the content they replaced. The manifest reports
`replacement_chars_by_operator`, the total number of replacement characters
each operator stored, so a script can be checked before it is shared.

## `dose.jsonl`

### Identity

| Field | Meaning |
|---|---|
| `schema_version` | version of this record layout |
| `run_id`, `note_uid`, `note_sha256` | as above |
| `segmenter_version` | version of the tokenizer and section grammar that defined the units |
| `op_id`, `op_version` | the operator, or `composite(a+b)`; its version |
| `params` | the operator's parameters as `key=value;...`, empty when none were set. Feeds the seed |
| `severity` | `rate:0.3` or `count:2` |
| `scope` | the canonical scope string that feeds the seed: target, phenotype scope, section |
| `salt` | the replicate label; a different salt draws different units |
| `stage_index` | 0 unless operators are chained |
| `composed_of` | under `--compose`, the operators merged into the cell |

### The dose chain

Each step is a subset of the one before.

| Field | Meaning |
|---|---|
| `unit_kind`, `dose_kind` | what the operator counts (`word`, `char`, `header`, ...) and whether severity is a rate or a count |
| `total_n` | units of that kind in the note |
| `scope_n` | of those, the units the scope and the aim admitted |
| `protected_n` | of those, the units protection withheld |
| `eligible_n` | `scope_n − protected_n`: the denominator of the dose |
| `requested_k` | the integer number of units the severity asked for |
| `selected_n`, `proposed_n` | units drawn, and edits the operator proposed for them |
| `applied_n` | edits that were applied: the realized dose |
| `rejected_n`, `rejection_reasons` | edits refused by the applier, by reason |
| `conflicts_dropped` | under `--compose`, edits lost to another operator |
| `status` | see below |

`status` keeps the kinds of "nothing happened" apart:

| Status | Meaning |
|---|---|
| `applied` | edits were made |
| `na_no_eligible` | the note has no unit of this kind (`total_n` = 0) |
| `na_scope_empty` | the scope or aim admitted none (`scope_n` = 0) |
| `na_all_protected` | protection withheld every admitted unit |
| `under_dosed` | the rate rounded to zero units |
| `no_change` | edits were proposed and none changed the text |
| `saturated` | more units were requested than were eligible |

The `na_*` cells are inapplicable and are excluded from averages; the others
are zeros and stay in.

### Realized intensity

| Field | Meaning |
|---|---|
| `achieved_eligible` | `applied_n / eligible_n`. The rate to plot |
| `achieved_total` | `applied_n / total_n` |
| `eligibility_rate` | `eligible_n / total_n` |
| `dose_inflation` | `applied_n / requested_k` |
| `chars_removed`, `chars_added` | characters deleted and written |
| `edit_cost`, `doc_chars`, `acer` | summed edit distance of the applied edits, the note's length, and their ratio: the share of the note's characters changed |
| `lines_added`, `lines_removed` | change in line count |
| `tokens_total`, `tokens_changed`, `token_change_rate` | content tokens in the note; how many differ after corruption (a multiset difference); their ratio |
| `tokens_edited` | tokens that contain at least one applied edit lying wholly inside them |
| `tokens_edited_once` | of those, tokens changed in exactly one character position |
| `output_sha256`, `output_identical` | SHA-256 of the corrupted note; whether it equals the original |

**Coverage is not damage.** Operators are dosed on different units, so the
same severity means different things. `input.typo` at 0.10 changes one
character in 10% of eligible words. `input.ocr_confusion` at 0.10 changes 10%
of confusable character *positions*, which can fall several times in one word.
`tokens_edited_once / tokens_edited` shows this per cell, and `acer` gives the
share of the note changed. To hold damage per word constant across operators,
cap OCR with `--param input.ocr_confusion:max_edits_per_token=1`.

### Where the edits landed

| Field | Meaning |
|---|---|
| `clinical_hits`, `nonclinical_hits`, `unknown_hits`, `clinical_hit_rate` | applied edits by whether they fell on clinical content |
| `category_hits` | applied edits per semantic category. Categories overlap, so these do not sum to `applied_n` |
| `lexicon_source` | which lexicon classified the tokens |
| `target_resolution` | `concept` if a concept index resolved the aim, `token` if it fell back to per-token lookup |

### Phenotype evidence

Empty unless a phenotype was declared (`--target pheno=NAME` or `--phenotype`).

| Field | Meaning |
|---|---|
| `phenotype_scope` | `agnostic`, `protect` or `target` |
| `evidence_n` | evidence spans each phenotype had in the note, before any edit |
| `evidence_touch` | of those, spans an applied edit intersected |
| `evidence_n_by_tier`, `evidence_touch_by_tier` | the same two counts split by tier (see the [glossary](glossary.md#tier)) |
| `evidence_touch_affirmed` | touched spans that were affirmed; present only when assertion detection ran |

Read reach by tier. `evidence_touch = evidence_n` says every declared span was
hit. It does not say the diagnosis was hit: a note whose declared evidence is
all medications can be fully touched while the written diagnosis, which the
target never matched, is intact. The `anchor` tier is the diagnosis as written.

## `manifest.json`

| Field | Meaning |
|---|---|
| `run_id`, `corpus`, `notes`, `cells`, `edits` | the run, the corpus file name, and counts |
| `environment` | package, schema and Python versions, platform |
| `operators`, `severities`, `salt`, `operator_params` | what was asked for |
| `target`, `phenotype_scope`, `phenotypes` | the aim, in canonical form |
| `targeting` | for a phenotype run, what the target was built from, including `warrants` (`[concept, surface]`, or `[surface]` without licensed terminology); otherwise null |
| `phenotype_measured_set_recall` | measured recall of each declared phenotype's target |
| `matcher` | the concept matcher's configuration, or that none was present |
| `recipe` | the recipe, if one was used |
| `column_map`, `limit`, `document_selection` | which columns were read, and how many notes of how many |
| `resource_digests`, `lexicon_source` | SHA-256 of the resources the segmenter read |
| `dose_sha256`, `edits_sha256` | SHA-256 of the two tables |
| `contains_note_text` | always `false`: no span of a note is copied |
| `max_replacement_chars` | the cap on a stored replacement (120) |
| `replacement_form` | `minimal_diff`; `minimal_diff_with_exceptions` if some cells were stored as proposed; `as_proposed` if the notes were not available when writing |
| `cells_stored_as_proposed` | how many cells were stored untrimmed |
| `replacement_chars_by_operator` | total replacement characters stored, per operator |

## Reading older runs

Edit scripts written by version 0.1.0 store replacements as proposed and
replay unchanged. Their dose rows lack `params`, `tokens_edited`,
`tokens_edited_once` and the two `_by_tier` fields.
