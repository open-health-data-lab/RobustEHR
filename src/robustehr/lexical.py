"""Is this ordinary English, and what kind?

A **second, orthogonal axis** to semantic category. Category answers *what kind
of clinical thing is this* from UMLS; lexical class answers *what kind of English
word is this* from sources that have nothing to do with a terminology. Keeping
them separate matters because a token can be both, and the overlap is the most
informative thing either axis produces.

The three classes are deliberately not one scale:

* :attr:`LexicalClass.FUNCTION_WORD` — determiners, prepositions, conjunctions,
  auxiliaries, pronouns. A genuinely finite class, which is the one situation
  where a hand-curated list is the right tool rather than a shortcut. Verified
  disjoint from the clinical vocabulary: zero of the 118 leak into it.
* :attr:`LexicalClass.GENERAL_ENGLISH` — ordinary content words, from a
  frequency list rather than a judgement. Redistributable, unlike UMLS, so it
  ships and runtime needs no frequency package.
* :attr:`LexicalClass.OUT_OF_VOCABULARY` — in neither list. Misspellings, rare
  technical terms, proper nouns, and the residue of de-identification.

**The overlap is the point.** ``home``, ``take``, ``report``, ``new`` and
``times`` all carry a UMLS semantic type *and* are ordinary English. Those are
precisely the terms where category membership is least trustworthy, and having
both axes lets a report say so instead of silently counting them as clinical
content. It is also what makes an honest control condition possible: corrupting
function words is a different experiment from corrupting general English content
words, and lumping them into one "non-clinical" bucket loses that.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from robustehr.resources import resource_bytes

GENERAL_ENGLISH_RESOURCE = "general_english.txt"
ENGLISH_VOCABULARY_RESOURCE = "english_vocabulary.txt"


class LexicalClass(StrEnum):
    """What kind of English word this is, independent of any terminology."""

    FUNCTION_WORD = "function_word"
    """Closed-class grammar words: the, and, of, was, which."""
    GENERAL_ENGLISH = "general_english"
    """Ordinary English content words — including ones UMLS also carries."""
    OUT_OF_VOCABULARY = "out_of_vocabulary"
    """In neither list: misspellings, rare terms, proper nouns, de-id residue."""


@lru_cache(maxsize=1)
def general_english() -> frozenset[str]:
    """The shipped general-English vocabulary.

    Zipf >= 3.0 from ``wordfreq`` — roughly the 28,000 words a general reader
    recognises. Regenerate with ``validation/pipeline/scripts/gen_general_english.py``.
    """
    return frozenset(
        line.strip().lower()
        for line in resource_bytes(GENERAL_ENGLISH_RESOURCE).decode("utf-8").splitlines()
        if line.strip()
    )


@lru_cache(maxsize=1)
def english_vocabulary() -> frozenset[str]:
    """Common English at Zipf >= 3.0, with **nothing subtracted**.

    A different question from :func:`general_english`, and the difference is
    load-bearing. That list answers *should the terminology speak for this
    word*, so it deliberately removes the 2,686 words carrying a high-precision
    clinical type — which means `stable`, `mild`, `wound` and `fever` are absent
    from it. Correct there.

    This one answers *would a reader recognise this word at all*, which must not
    subtract them. Using the filtered list for that question counts every
    ordinary clinical adjective as an abbreviation.

    Regenerate both with ``validation/pipeline/scripts/gen_general_english.py``; they come from one
    pass so they cannot drift apart.
    """
    return frozenset(
        line.strip().lower()
        for line in resource_bytes(ENGLISH_VOCABULARY_RESOURCE).decode("utf-8").splitlines()
        if line.strip()
    )


def resolve_tags(word: str, lexicon: object) -> frozenset[str]:
    """The final tag set for a word: exactly one lexical class, or its categories.

    The precedence is **function word, then general English, then semantic
    category**, and the middle step is the one that carries a decision.

    A word in the general-English list wins over any semantic category it also
    carries. That is not a concession — it is what the list is *built* to mean.
    Words carrying a high-precision clinical type (``foot``, ``chest``, ``pain``,
    ``blood``) were removed from it during the build precisely so they never
    reach this rule, and words carrying clinical vocabulary UMLS mistyped
    (``sig``, ``po``, ``mg``, ``metastatic``) were removed by keyness. What
    survives in the list and still carries a category is the residue —
    ``home`` (T058 Health Care Activity), ``take``, ``report`` — where the
    terminology is over-reaching and ordinary English is the better reading.

    Returns lexical classes and semantic categories in one set because a caller
    wants one answer per token, not two axes to reconcile at every use site.
    """
    lowered = word.lower()
    lexical = classify_lexical(lowered)
    if lexical is not LexicalClass.OUT_OF_VOCABULARY:
        return frozenset({lexical.value})
    categories = getattr(lexicon, "categories", None)
    found = categories(lowered) if callable(categories) else frozenset()
    return found or frozenset({LexicalClass.OUT_OF_VOCABULARY.value})


def classify_lexical(word: str) -> LexicalClass:
    """Which lexical class this word falls in.

    Function words are checked first: they are also general English, but naming
    a word a determiner is strictly more informative than naming it common.
    """
    from robustehr.lexicon import load_morphology

    lowered = word.lower()
    if lowered in load_morphology().closed_class:
        return LexicalClass.FUNCTION_WORD
    if lowered in general_english():
        return LexicalClass.GENERAL_ENGLISH
    return LexicalClass.OUT_OF_VOCABULARY


__all__ = [
    "ENGLISH_VOCABULARY_RESOURCE",
    "GENERAL_ENGLISH_RESOURCE",
    "LexicalClass",
    "classify_lexical",
    "english_vocabulary",
    "general_english",
    "resolve_tags",
]
