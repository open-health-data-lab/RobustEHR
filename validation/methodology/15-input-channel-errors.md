# Input-channel errors: typing, scanning and dictation are three processes

**Manuscript section:** Taxonomy, Dose and intensity

**Core claim:** typographical and OCR corruption are not two intensities of one
perturbation. They have disjoint error models where it matters clinically, one
of them is inexpressible per character, and they are dosed over different
denominators — so a single "character noise" operator would have been a claim
about scanned documents made using a keyboard's geometry.

---

## 1. Why a reviewer will ask

Three operators occupy the INPUT channel. All three change characters inside
words, all three run at comparable severities, and all three are conditionally
preserving:

| operator | error model | dose denominator |
|---|---|---|
| `input.typo` | QWERTY adjacency | eligible **words** (alphabetic, ≥3 chars) |
| `input.ocr_confusion` | visual glyph shape | eligible **characters** (confusable positions inside tokens of ≥2) |
| `input.phonetic_confusion` | generative morpheme rules + a phonotactic gate | eligible tokens where a rule fires |

Presented as a table of severities they look like one operator with three
settings. They are not, and the difference is checkable rather than asserted.

## 2. The error models are disjoint where it matters

A typing model asks *which keys are adjacent*; an OCR model asks *which glyphs
look alike*. The two agree in places — `n`/`h`, `t`/`f` and `i`/`j` are both
neighbouring keys and similar shapes, about 16% of the confusion table — and
that overlap is a fact about Latin script rather than a defect in either model.

The part that does not overlap is the part that matters. **Digit-for-letter
confusion** — `0→O`, `5→S`, `1→l`, `8→B` — is what turns a potassium of `5.1`
into `S.1` and a creatinine of `1.0` into `l.O`. It is the substitution a
downstream extractor is least able to recover from, and it appears **nowhere**
in a keyboard-adjacency model: `0` and `O` are opposite ends of the keyboard.

This is asserted in code, not in prose. `tests/test_ops_ocr.py::TestOcrIsNotATypo`
extracts every digit↔letter pair from the confusion table and asserts each is
absent from `input.typo`'s `_ADJACENT`:

```python
digit_pairs = [
    (src, dst)
    for src, opts in _OCR_CONFUSIONS.items()
    for dst in opts
    if src.isdigit() != dst.isdigit()
]
assert digit_pairs, "no digit-letter confusion: the dangerous case is unmodelled"
for src, dst in digit_pairs:
    assert dst.lower() not in _ADJACENT.get(src.lower(), "")
```

If someone ever folded OCR into the typo operator's mode list, that test fails.

## 3. OCR is not expressible per character

The ligature set — `rn→m`, `cl→d`, `vv→w`, `li→h` — merges two glyphs into one
and therefore **changes token length**. No single-character substitution model
can produce it, which is the second reason `input.typo`'s four modes
(substitute, transpose, delete, double) cannot subsume OCR: `delete` shortens a
token by removing a character, `ligature` shortens it by *replacing two with
one*, and only the second is what a scanner does.

Length change is also the clinically distinct failure. A substitution leaves the
token boundaries intact and a fuzzy matcher can often recover; a merge moves
every subsequent character and breaks alignment against a gold span.

## 4. The denominators differ because the processes differ

This is the part most easily got wrong, and it changes what a published number
means.

- **Typing errors are events per word typed.** A typist commits errors at some
  rate per word, so `input.typo` is dosed over **eligible words** and "10%"
  means one word in ten acquires an error.
- **Scanning errors are events per character scanned.** An OCR engine misreads
  glyphs at some rate per glyph, so `input.ocr_confusion` is dosed over
  **eligible character positions** and "10%" means one confusable character in
  ten is misread. That is the **character error rate (CER)** the OCR literature
  reports, which is what makes the number comparable to published engine
  accuracies at all.

Eligibility is confined to positions *inside* a token of two or more characters
in both cases, because that is where input errors land. What differs is what
"10%" counts, not where it lands.

Two operators reporting the same severity therefore mean different things, and
each states which in its `denominator_doc`. Both baselines sit in Table 1 beside
the level they belong to: `token.word_min3` for typing, `character.ocr_confusable`
for scanning.

A character denominator has one failure mode a word denominator does not, and
the operator carries `max_edits_per_token` to bound it. Severity is a fraction of
*eligible* units, so a saturating rate against a narrow target puts every
confusable position in a token in scope at once, and the output is the token
replaced by same-length noise rather than misread. Capping at one edit per token
restores the single-character misreading this section argues for, at any
severity, and leaves the uncapped denominator in place for corpus-wide runs.

The character denominator is part of the operator's version: the unit kind is
seed material, so a build dosed over words would produce a different edit script
from the same note, and the version says which was run.

## 5. The identification side splits the same way

Every corruption in this package has a matching identification capability, and
the INPUT channel is no exception:

| baseline | estimates | shares its model with |
|---|---|---|
| `metrics.spelling.profile_near_miss` | pre-existing **typing** noise: OOV tokens within one Damerau edit of a known term | — (edit distance is not the typo operator's model) |
| `metrics.ocr.profile_ocr` | pre-existing **scanning** noise: OOV tokens reachable from a known term by one *inverse OCR confusion* | **the operator's own table**, read backwards |

The second is the tighter pairing, deliberately. The confusion table lives in
`resources/ocr_confusions.yaml` and is read by both sides — forward to inject,
inverse to detect — so a baseline and an injection cannot be measuring different
phenomena. It also means the table's digest reaches `op_version`: editing it is
a version bump, where a table living inside a module changed previously reported
results silently.

Both estimates are **candidate counts, not corrected rates**, and must be read
that way. For the typing estimator the cost is published: precision 0.096 by
occurrence and 0.526 on hapax surfaces (`validation/measurements/spelling_precision.json`),
and an injection–recovery slope of 0.7401 against a `[0.90, 1.10]` gate — a
systematic 26% under-count, recorded in `validation/record/methodology/11-lexical-normalization.md`
rather than corrected for.

The OCR estimator has the same shape of limitation and one of its own worth
stating plainly: at higher doses it **under-counts by construction**, because a
word that received two substitutions is no longer one inverse edit from a real
word. It is an instrument for detecting *whether* scanning noise is present and
watching it move, not for measuring how much.

It also cannot see the dangerous half. `5.1` misread as `S.1` is exactly the
error the digit rows exist to inject, and a number that came off a scanner wrong
still looks like a number — there is no lexicon to check it against. Digit-bearing
tokens are therefore excluded from the estimate rather than counted badly. The
injection reaches them; the detection does not, and the asymmetry is the honest
statement of what this baseline is for.

## 6. What follows for a result

- Never pool `input.typo` and `input.ocr_confusion` at "the same severity". They
  are different processes at different denominators; plot them as separate arms.
- Quote `character.ocr_confusable` beside any OCR result. A note with few
  confusable positions cannot be heavily corrupted whatever severity is
  requested, and `dose.achieved_eligible` will say so.
- Treat the pre-existing estimates as stratifiers, never as addends — the rule
  `validation/protocol.md` applies to every baseline in the package. A
  corpus that already looks scanned is a different population, not a corpus with
  a head start on the dose.
