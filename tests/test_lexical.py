"""The lexical axis: what kind of English word, independent of any terminology."""

from __future__ import annotations

from pathlib import Path

import pytest

from robustehr.lexical import (
    LexicalClass,
    classify_lexical,
    general_english,
    resolve_tags,
)
from robustehr.lexicon import load_clinical_lexicon, load_morphology


def test_function_words_are_recognised():
    for word in ("the", "and", "was", "which", "of", "not"):
        assert classify_lexical(word) is LexicalClass.FUNCTION_WORD, word


def test_general_english_content_words():
    for word in ("please", "note", "home", "take", "report", "continue"):
        assert classify_lexical(word) is LexicalClass.GENERAL_ENGLISH, word


def test_ordinary_words_that_are_clinical_in_a_note_are_not_general_english():
    """The whole difficulty, in one test.

    `foot`, `chest`, `pain` and `blood` are ordinary English by any frequency
    measure and are clinical content in a discharge summary. They must not be in
    the general-English list, or the precedence rule would tag them as ordinary.
    """
    for word in ("foot", "chest", "pain", "blood", "hand", "back", "head"):
        assert word not in general_english(), word
        assert classify_lexical(word) is not LexicalClass.GENERAL_ENGLISH, word


def test_back_is_not_a_function_word():
    """It reads as a preposition and is anatomy in a note (back pain)."""
    assert classify_lexical("back") is not LexicalClass.FUNCTION_WORD


def test_clinical_vocabulary_umls_missed_is_not_general_english():
    """Removed by keyness: plainly clinical, but UMLS gives no precise type."""
    for word in ("sig", "po", "mg", "metastatic", "bilateral", "biopsy"):
        assert word not in general_english(), word


def test_clinical_jargon_is_out_of_vocabulary():
    """Technical terms are not ordinary English, which is the useful signal."""
    for word in ("warfarin", "dyspnea", "cholecystectomy"):
        assert classify_lexical(word) is LexicalClass.OUT_OF_VOCABULARY, word


def test_function_words_are_excluded_from_general_english():
    """A word must satisfy exactly one lexical class.

    Function words are subtracted from the general-English list at build time,
    so the precedence never has to arbitrate between them.
    """
    assert "the" not in general_english()
    assert classify_lexical("the") is LexicalClass.FUNCTION_WORD


def test_classification_is_case_insensitive():
    assert classify_lexical("The") is classify_lexical("the")
    assert classify_lexical("WARFARIN") is classify_lexical("warfarin")


def test_the_list_is_a_reasonable_size():
    words = general_english()
    assert 20_000 < len(words) < 30_000
    assert all(w.islower() for w in words)


def test_no_function_word_is_in_the_clinical_vocabulary(tmp_path):
    """The two axes must not silently double-count grammar as content.

    Verified against the real build in the commit that added this: zero of the
    118 closed-class words leak into the UMLS-derived vocabulary, because the
    builder subtracts them.
    """
    artifact = Path("data/lexicon/clinical_tokens.txt")
    if not artifact.exists():
        pytest.skip("clinical vocabulary not built")
    lexicon = load_clinical_lexicon(artifact)
    precise = ("anatomy", "disease", "symptom", "medication", "device", "lab_result")
    # UMLS types a handful of grammar words through oddities — `down` via Down
    # syndrome, `ten` via some drug. What must not happen is a genuinely
    # anatomical word like `back` sitting in the function-word list.
    leaked = sorted(
        w
        for w in load_morphology().closed_class
        if any(c in precise for c in lexicon.categories(w))
    )
    assert "back" not in leaked
    assert len(leaked) < 15, leaked


def test_the_axes_are_orthogonal(tmp_path):
    """A token can be both general English and clinically categorized.

    That overlap is the point: `home`, `take` and `new` carry a UMLS semantic
    type *and* are ordinary English, and those are exactly the terms where
    category membership deserves least trust.
    """
    artifact = Path("data/lexicon/clinical_tokens.txt")
    if not artifact.exists():
        pytest.skip("clinical vocabulary not built")
    lexicon = load_clinical_lexicon(artifact)
    suspect = [
        w
        for w in ("home", "take", "report", "new", "times")
        if lexicon.categories(w) and classify_lexical(w) is LexicalClass.GENERAL_ENGLISH
    ]
    assert suspect, "expected some category members to also be ordinary English"


# -- the precedence rule ----------------------------------------------------


def test_general_english_takes_precedence_over_a_umls_category():
    """`home` carries T058 Health Care Activity and is ordinary English.

    Where the two collide the general-English reading wins, because the list is
    built so that only over-reaching categories can still collide with it.
    """
    artifact = Path("data/lexicon/clinical_tokens.txt")
    if not artifact.exists():
        pytest.skip("clinical vocabulary not built")
    lexicon = load_clinical_lexicon(artifact)
    assert "procedure" in lexicon.categories("home")
    assert resolve_tags("home", lexicon) == frozenset({"general_english"})


def test_clinical_words_still_resolve_to_their_category():
    artifact = Path("data/lexicon/clinical_tokens.txt")
    if not artifact.exists():
        pytest.skip("clinical vocabulary not built")
    lexicon = load_clinical_lexicon(artifact)
    assert resolve_tags("warfarin", lexicon) == frozenset({"medication"})
    assert "anatomy" in resolve_tags("chest", lexicon)
    assert "symptom" in resolve_tags("pain", lexicon)


def test_function_words_never_carry_a_category():
    artifact = Path("data/lexicon/clinical_tokens.txt")
    if not artifact.exists():
        pytest.skip("clinical vocabulary not built")
    lexicon = load_clinical_lexicon(artifact)
    for word in ("the", "and", "however", "was"):
        assert resolve_tags(word, lexicon) == frozenset({"function_word"}), word
