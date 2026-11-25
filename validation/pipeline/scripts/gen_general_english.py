#!/usr/bin/env python
"""Generate the general-English word list shipped with the package.

The list answers one question: **is this word ordinary English rather than
clinical content, in the context of a clinical note?** That qualifier is the
whole difficulty. ``foot``, ``chest``, ``pain`` and ``blood`` are ordinary
English by any frequency measure, and in a discharge summary every one of them is
clinical content.

Three signals were tried. The first two are kept; the third is demoted.

1. **General-English frequency** (``wordfreq``). Necessary — a word nobody uses
   is not ordinary English — and nowhere near sufficient, since it ranks
   ``blood`` (Zipf 5.10) as more ordinary than ``normal`` (5.01).

2. **Clinical semantic type** (UMLS, high-precision categories only). The
   discriminator that works: subtract every word carrying anatomy, disease,
   symptom, medication, device or lab_result. On a 26-word probe it is correct 25
   times — ``foot``, ``chest``, ``pain``, ``blood``, ``hand``, ``back`` removed;
   ``please``, ``note``, ``home``, ``take`` kept.

   Only the *high-precision* categories are subtracted. ``procedure`` (via T058
   Health Care Activity) and ``finding`` (via T033) are the noisy ones, and
   subtracting them would strip ``home``, ``take``, ``report`` and ``new`` —
   ordinary English that UMLS happens to carry. Keeping them is also the
   precedence rule: **where a general-English word is also in a UMLS category,
   general English wins.**

3. **TF-IDF keyness** — log(frequency in clinical text) minus Zipf(general
   English). Intuitive, and measured here as a *failure* when used as a gate:
   ``foot`` scores 0.63 against ``home`` at 0.59, and ``hand`` (-0.20) and
   ``back`` (-0.11) fall below plainly ordinary words, because their clinical and
   idiomatic senses are the same string.

   So keyness is not a *general* discriminator. It is used only where it is
   demonstrably clean — a **high-confidence removal** above 1.5 — for the one
   failure mode rule 2 cannot see: words that are plainly clinical but which UMLS
   gives no precise semantic type. Inspecting the bands is the calibration:

     >= 2.0   sig, po, mg, metastatic, lesion, regimen, rx        clearly clinical
     1.5-2.0  rheumatoid, pitting, bp, icu, exam, chronic, ef     clearly clinical
     1.2-1.5  tablets, fungal, bony, reflexes | notable, moderate  mixed
     1.0-1.2  swollen, superficial, severe | initially, presents   mixed
     0.8-1.0  smoker, symmetrical | pleasant, excluded, increased  mostly ordinary
     0.6-0.8  bacteria | discussed, overnight, upright             ordinary

   1.5 is where the character changes. Below it the band is mixed and removal
   would cost ordinary words, so the 1.0-1.5 band is reported as suspects rather
   than acted on.

   The residual error this leaves is ``times``: removed by rule 2 because UMLS
   types it T047 Disease or Syndrome, though its keyness of 0.50 says it is
   ordinary. Cases like it are listed in the manifest rather than silently
   accepted.

Function words are subtracted as well, since they are a separate lexical class
and no word should satisfy two classes at once.

Keyness needs a corpus; without ``--corpus`` the list is still produced and only
the diagnostic is skipped, so the shipped artifact never depends on holding
licensed notes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from wordfreq import top_n_list, zipf_frequency

from robustehr.lexicon import load_clinical_lexicon, load_morphology

OUT = Path("src/robustehr/resources/general_english.txt")
LEXICON = Path("data/lexicon/clinical_tokens.txt")
VOCABULARY = Path("src/robustehr/resources/english_vocabulary.txt")

MIN_ZIPF = 3.0
POOL = 60_000

#: Categories whose membership means "clinical content, not ordinary English".
#:
#: Deliberately excludes `procedure` and `finding`, which carry T058 and T033 —
#: the two types where ordinary words accumulate.
PRECISE_CATEGORIES = ("anatomy", "disease", "symptom", "medication", "device", "lab_result")

#: Keyness above which a word is removed as clinical vocabulary UMLS missed.
#: Calibrated by band inspection — see the module docstring.
REMOVE_KEYNESS = 1.5

#: Keyness above which a *kept* word is reported for review but not removed.
SUSPECT_KEYNESS = 1.0


def clinical_keyness(corpus: Path, limit: int) -> dict[str, float]:
    """log10(freq in clinical text) - Zipf(general English), per word.

    A diagnostic, not a gate. See the module docstring for why.
    """
    from robustehr.corpus import read_documents
    from robustehr.segment.tokens import TokenKind

    freq: Counter[str] = Counter()
    for doc in read_documents(corpus, limit=limit):
        for token in doc.tokens:
            if token.kind is TokenKind.WORD and token.is_content and token.lower.isalpha():
                freq[token.lower] += 1
    total = sum(freq.values()) or 1
    return {
        word: round(math.log10(n / total * 1e9) - zipf_frequency(word, "en"), 3)
        for word, n in freq.items()
        if zipf_frequency(word, "en") > 0
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=None, help="for the keyness diagnostic")
    parser.add_argument("--limit", type=int, default=400)
    args = parser.parse_args(argv)

    if not LEXICON.exists():
        print(f"error: {LEXICON} not found; run `robustehr concepts build-lexicon` first")
        return 1
    lexicon = load_clinical_lexicon(LEXICON)
    function_words = load_morphology().closed_class

    common = [
        w
        for w in top_n_list("en", POOL)
        if w.isalpha() and len(w) > 1 and zipf_frequency(w, "en") >= MIN_ZIPF
    ]
    removed_clinical: list[str] = []
    words: list[str] = []
    for word in common:
        if word in function_words:
            continue
        if any(c in PRECISE_CATEGORIES for c in lexicon.categories(word)):
            removed_clinical.append(word)
            continue
        words.append(word)
    words.sort()

    keyness = clinical_keyness(args.corpus, args.limit) if args.corpus else {}
    removed_keyness = sorted(w for w in words if keyness.get(w, 0.0) >= REMOVE_KEYNESS)
    words = [w for w in words if keyness.get(w, 0.0) < REMOVE_KEYNESS]
    suspects = sorted(
        ((keyness[w], w) for w in words if SUSPECT_KEYNESS <= keyness.get(w, 0.0) < REMOVE_KEYNESS),
        reverse=True,
    )

    # The unfiltered vocabulary, emitted alongside because a *different*
    # question needs it. `general_english.txt` answers "should the terminology
    # speak for this word" and therefore subtracts clinically-typed words on
    # purpose. "Is this an English word at all" must not subtract them: `stable`,
    # `mild`, `wound` and `fever` are ordinary English and are gone from the
    # filtered list, so using that list to decide what is an abbreviation counts
    # them as abbreviations. Two questions, two files.
    VOCABULARY.write_text("\n".join(sorted(common)) + "\n", encoding="utf-8")
    VOCABULARY.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "source": f"wordfreq {version('wordfreq')}",
                "license": "Apache-2.0",
                "min_zipf": MIN_ZIPF,
                "rule": (
                    "common English at Zipf >= 3.0, with nothing subtracted. The "
                    "question is whether a reader would recognise the word, not "
                    "whether a terminology also claims it."
                ),
                "used_for": (
                    "deciding what is not an abbreviation. Distinct from "
                    "general_english.txt, which subtracts clinically-typed words "
                    "so that resolve_tags lets the terminology speak for them — "
                    "correct there, and wrong here."
                ),
                "words": len(common),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    body = "\n".join(words)
    OUT.write_text(body + "\n", encoding="utf-8")
    OUT.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "source": f"wordfreq {version('wordfreq')}",
                "license": "Apache-2.0",
                "min_zipf": MIN_ZIPF,
                "rule": (
                    "common English, minus function words, minus words carrying a "
                    f"high-precision clinical category ({', '.join(PRECISE_CATEGORIES)})"
                ),
                "words": len(words),
                "removed_by_semantic_type": len(removed_clinical),
                "removed_by_semantic_type_examples": sorted(removed_clinical)[:40],
                "removed_by_keyness": len(removed_keyness),
                "removed_by_keyness_examples": removed_keyness[:40],
                "remove_keyness_threshold": REMOVE_KEYNESS,
                "keyness_suspects": [{"word": w, "keyness": k} for k, w in suspects[:40]],
                "keyness_note": (
                    "Keyness removes only above 1.5, where band inspection shows "
                    "the words are unambiguously clinical. It is not a general "
                    "discriminator: foot scores 0.63 against home at 0.59, and "
                    "hand and back fall below plainly ordinary words. The 1.0-1.5 "
                    "band is kept and listed here for review."
                ),
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(words):,} words to {OUT}")
    print(f"  removed {len(removed_clinical):,} carrying a precise clinical type")
    print(f"  removed {len(removed_keyness):,} by keyness >= {REMOVE_KEYNESS}")
    if suspects:
        print(f"  {len(suspects)} kept words flagged by keyness for review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
