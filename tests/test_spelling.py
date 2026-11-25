"""The near-miss measure, and the negative control that keeps it honest.

A detector that fires on everything and a detector that fires on nothing are
both useless, and the failure modes are opposite. So both directions are pinned:
clean text must produce zero, and text corrupted by exactly one edit must
produce one hit per corrupted token.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from robustehr.document import Document
from robustehr.lexicon import Lexicon, load_clinical_lexicon
from robustehr.metrics.spelling import (
    MIN_LENGTH,
    _delete1,
    _within_one_edit,
    deletion_index,
    nearest,
    profile_near_miss,
)

#: Ordinary words, all at least `MIN_LENGTH`, all in the shipped English list.
CLEAN = ["patient", "history", "chronic", "stable", "reports", "denies"]

#: The same words with one substitution each. Chosen so that no result is itself
#: a word — a mangling that lands on another real word is not a near-miss, it is
#: a different word, and the measure is correct to miss it.
MANGLED = ["patiemt", "histzry", "chronjc", "stqble", "repxrts", "deniws"]


@pytest.fixture
def vocabulary(tmp_path: Path) -> tuple[Lexicon, Path]:
    """A hand-written clinical vocabulary — the format `load_clinical_lexicon`
    accepts when the trailing columns are omitted."""
    path = tmp_path / "terms.txt"
    path.write_text("furosemide\nlisinopril\nmetoprolol\n", encoding="utf-8")
    return load_clinical_lexicon(path), path


def test_the_index_generates_every_candidate_and_confirms_none_of_them():
    """One direction of the theorem holds, and the other is why confirmation
    exists.

    Completeness: two strings within one edit ALWAYS have intersecting delete-1
    neighbourhoods, so nothing is missed. Soundness: the converse is false, so
    an intersection alone would admit pairs that are not within one edit.
    """
    words = ["abdominal", "abdomnial", "abdomina", "abdominals", "abdominel", "chest"]
    for a in words:
        for b in words:
            if _within_one_edit(a, b):
                assert _delete1(a) & _delete1(b), f"{a}/{b} missed by the generator"
    # The witness for the failing direction, and the reason `nearest` filters
    # rather than trusting an intersection: `abdominal` and `abdomnial` share
    # the deletion `abdomnal` and are two Levenshtein edits apart.
    assert _delete1("abdominal") & _delete1("abdomnial")


def test_transposition_counts_because_it_is_the_commonest_typo():
    """Damerau, not plain Levenshtein.

    `abdomnial` for `abdominal` is one transposition and TWO Levenshtein edits.
    Filtering on `levenshtein == 1` rejected exactly the case a misspelling
    measure most needs, while the candidate generator had already found it.
    """
    from robustehr.edits.apply import levenshtein

    assert levenshtein("abdominal", "abdomnial") == 2
    assert _within_one_edit("abdominal", "abdomnial")
    # Non-adjacent swaps are a different distance and are not admitted.
    assert not _within_one_edit("abcd", "dbca")


def test_clean_text_produces_no_near_miss(vocabulary):
    """The negative control. Words every vocabulary carries are not candidates
    at all, so they cannot be near-misses."""
    lexicon, path = vocabulary
    doc = Document.from_text(" ".join(CLEAN) + "\n", uid="clean")
    profile = profile_near_miss(doc, lexicon, path)
    assert profile.candidates == 0
    assert profile.near_miss == 0
    # No candidates means no rate, not a rate of zero: a note with nothing
    # unrecognised has nothing to be right or wrong about.
    assert profile.near_miss_rate is None


def test_one_edit_corruptions_are_all_found(vocabulary):
    """The positive control. Every token is one substitution from a word the
    English list carries, so every token must be flagged."""
    lexicon, path = vocabulary
    doc = Document.from_text(" ".join(MANGLED) + "\n", uid="mangled")
    profile = profile_near_miss(doc, lexicon, path)
    assert profile.candidates == len(MANGLED)
    assert profile.near_miss == len(MANGLED)
    assert profile.near_miss_rate == 1


def test_clinical_terms_in_the_lexicon_are_not_candidates(vocabulary):
    """A term the clinical vocabulary carries is known, however unlike English.

    Without the clinical half of the vocabulary `furosemide` would be
    unrecognised AND one edit from `furosemid`-shaped junk, so it would be
    counted as a probable misspelling of nothing.
    """
    lexicon, path = vocabulary
    doc = Document.from_text("furosemide lisinopril metoprolol\n", uid="drugs")
    assert profile_near_miss(doc, lexicon, path).candidates == 0


def test_short_tokens_are_excluded_because_everything_is_near_them(vocabulary):
    """Below `MIN_LENGTH` the measure is vacuous: `qid` is one edit from `aid`,
    `bid`, `did`, `qed`. Counting those would swamp the real signal with
    abbreviations, which `robustehr ambiguity` already measures properly."""
    lexicon, path = vocabulary
    assert MIN_LENGTH == 4
    doc = Document.from_text("xqd zpt jrm\n", uid="short")
    assert profile_near_miss(doc, lexicon, path).candidates == 0


def test_nearest_is_deterministic_and_reproducible(vocabulary):
    """The neighbour is what a human adjudicator reads, so it cannot depend on
    hash order. Sorted candidates from a sorted index."""
    _, path = vocabulary
    index = deletion_index(path)
    first = [nearest(w, index) for w in MANGLED]
    assert first == [nearest(w, index) for w in MANGLED]
    assert all(n is not None for n in first)
