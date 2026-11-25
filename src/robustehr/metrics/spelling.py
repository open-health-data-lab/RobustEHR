"""How many tokens look like a word that was *nearly* typed correctly?

**This is not a misspelling rate, and the distinction is the whole point.**
:mod:`robustehr.metrics.dqp` already reports ``unrecognized`` — alphabetic
content tokens in neither lexicon — and measured on 200 MIMIC notes that field
is dominated by vocabulary rather than error: ``daily`` (2,627 occurrences),
``tablet`` (2,390), ``refills``, ``acute``, ``bilateral``. A count of words no
resource happens to carry says more about the resources than about the notes.

A **near-miss** narrows it with a property of the token itself: alphabetic, at
least :data:`MIN_LENGTH` characters, absent from both vocabularies, and within
**edit distance 1** of a term one of them does carry. ``abdmoninal`` is one
character from ``abdominal``; ``daily`` is not one character from anything, so
it drops out. That is a much better filter than absence alone, and it is still
**not** a misspelling count: a rare drug name absent from both lexicons and one
character from a common word is a near-miss and a perfectly correct token.

So the field ships as ``near_miss_edit1``, and the gate it would have to pass to
be called anything else has now been run. On 200 MIMIC-IV discharge summaries,
``validation/pipeline/scripts/spelling_validate.py`` adjudicated a deterministic sample of 200 of
the 1,442 distinct near-miss surfaces:

    precision by distinct surface   0.425
    precision by OCCURRENCE         0.096   <- applies to the reported total
    precision on hapax surfaces     0.526

The middle number is the one that matters and it is the reason the name stays.
``near_miss_edit1`` counts occurrences, and the frequent near-misses are exactly
the wrong ones — ``refills`` 26 times, ``creat`` 7, ``supple`` 6 — so nine parts
in ten of the headline count are vocabulary the lexicons miss (0.365 of the
sample) or clinical shorthand (0.200). **Use ``distinct_hapax``**: restricted to
surfaces seen once in the whole corpus, precision roughly doubles to 0.526, and
that is the field a stratifier should be built on.

A clinician's adjudication supersedes the model's; ``--review`` writes the same
deterministic sample as a TSV for exactly that.

**One edit, Damerau.** Substitution, insertion, deletion **or an adjacent
transposition** — because transposition is the single most common typing error
and plain Levenshtein scores it 2, so a Levenshtein-only filter rejects
``abdomnial`` for ``abdominal``, which is precisely the case the measure exists
for.

Two strings within one edit always have intersecting delete-1 neighbourhoods,
so one index over the 265,823 known terms generates every candidate: 2.8M keys,
built in under three seconds. The converse does not hold — ``abdominal`` and
``abdomnial`` share ``abdomnal`` and are two Levenshtein edits apart — so every
candidate is confirmed by :func:`_within_one_edit` rather than trusted.

**Distance 2 is not reported.** Completeness there needs delete-2 neighbourhoods
on *both* sides: 15.5M keys and roughly half a gigabyte. No asymmetric shortcut
is sound, because a token two deletions from a term shares nothing with that
term's delete-1 set, and an incomplete distance-2 count would under-report by an
unknown amount. That is worse than not reporting one.

**Hapax crossing.** A near-miss used once in a corpus is far more likely to be
an error than one used two thousand times, so the corpus-level count is
reported beside the raw one. It is a second filter on the same population, not
a different measurement.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from robustehr.dose import ratio

if TYPE_CHECKING:  # pragma: no cover
    from fractions import Fraction

    from robustehr.document import Document
    from robustehr.lexicon import Lexicon

#: Shortest token treated as a near-miss candidate. Mirrors
#: :data:`robustehr.metrics.dqp.MIN_MISSPELLING_LENGTH` so the two measurements
#: describe the same population. Below four characters almost every unknown
#: token is an abbreviation rather than a misspelled word, and every short token
#: is within one edit of *something*: `pt` is one edit from `pi`, `at`, `p`.
MIN_LENGTH = 4


@dataclass(frozen=True, slots=True)
class NearMissProfile:
    """Near-miss load for one note."""

    note_uid: str
    content_tokens: int
    candidates: int = 0
    """Alphabetic content tokens of at least :data:`MIN_LENGTH` in neither
    vocabulary — the population `near_miss` selects from, and roughly what
    `dqp.unrecognized` counts."""
    near_miss: int = 0
    """Of those, within edit distance 1 of a term one vocabulary carries."""
    surfaces: Counter[str] = field(default_factory=Counter)
    """The near-miss tokens themselves, for the corpus-level hapax crossing and
    for `validation/pipeline/scripts/spelling_validate.py`. Note content: never emitted by a corpus
    summary, and `keep_surfaces=False` suppresses it entirely."""

    @property
    def near_miss_rate(self) -> Fraction | None:
        """Near-misses per candidate.

        ``None`` rather than zero when the note has no candidates at all: a note
        with nothing unrecognised has no rate, and 0 would place it beside notes
        whose unknown tokens were all real vocabulary.
        """
        return ratio(self.near_miss, self.candidates)


def _delete1(word: str) -> set[str]:
    """The word and every string one deletion from it.

    The index rests on one direction of an equivalence, and only one: if two
    strings are within one edit then their delete-1 neighbourhoods intersect. A
    substitution shows up as a shared deletion (``abc``/``axc`` both yield
    ``ac``), an insertion as the longer word's deletion equalling the shorter
    one, a transposition as a shared deletion of the moved character.

    **The converse is false**, which is why every candidate is confirmed.
    ``abdominal`` and ``abdomnial`` both yield ``abdomnal`` and are two
    Levenshtein edits apart. So the index is a complete *candidate generator*
    and :func:`_within_one_edit` is the filter.
    """
    return {word} | {word[:i] + word[i + 1 :] for i in range(len(word))}


def _within_one_edit(a: str, b: str) -> bool:
    """One substitution, insertion, deletion **or adjacent transposition**.

    Damerau rather than plain Levenshtein, because transposition is the single
    most common typing error and plain Levenshtein scores it 2. An earlier
    version filtered on ``levenshtein(a, b) == 1`` and therefore rejected
    ``abdomnial`` for ``abdominal`` — the exact case a misspelling measure most
    needs to catch — while the candidate generator had already found it.

    Adjacent only. Arbitrary transposition is a different distance with
    different behaviour, and the delete-1 index is not a complete generator
    for it.
    """
    from robustehr.edits.apply import levenshtein

    if levenshtein(a, b) == 1:
        return True
    if len(a) != len(b):
        return False
    differing = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
    return (
        len(differing) == 2
        and differing[1] == differing[0] + 1
        and a[differing[0]] == b[differing[1]]
        and a[differing[1]] == b[differing[0]]
    )


@lru_cache(maxsize=2)
def _known_terms(lexicon_path: Path | None) -> frozenset[str]:
    """Every term a near-miss can be near: general English plus the clinical set.

    Both, not either. English alone would call ``furosemide`` a candidate and
    then fail to find anything near it; the clinical lexicon alone would call
    ``the`` unrecognised.
    """
    from robustehr.lexical import english_vocabulary
    from robustehr.lexicon import load_clinical_lexicon

    terms = set(english_vocabulary())
    if lexicon_path is not None and lexicon_path.exists():
        terms |= set(load_clinical_lexicon(lexicon_path).clinical)
    return frozenset(w for w in terms if w.isalpha() and len(w) >= MIN_LENGTH)


@lru_cache(maxsize=2)
def deletion_index(lexicon_path: Path | None) -> dict[str, tuple[str, ...]]:
    """Delete-1 neighbourhood over the known terms, built once per vocabulary.

    Comparing each token against 265,823 terms directly is not viable — that is
    a full Levenshtein per pair, on every note — so the index inverts the
    problem: 2.8M keys, and a lookup is a handful of dict probes.

    Values are sorted tuples rather than sets so that the candidate a token is
    reported near is reproducible, not whichever the hash order surfaced.
    """
    index: dict[str, list[str]] = {}
    for term in sorted(_known_terms(lexicon_path)):
        for key in _delete1(term):
            index.setdefault(key, []).append(term)
    return {k: tuple(v) for k, v in index.items()}


def nearest(word: str, index: dict[str, tuple[str, ...]]) -> str | None:
    """The lexicographically first term at edit distance 1, or ``None``.

    Deterministic by construction: the index's values are sorted and the probe
    order is fixed, so the same token always names the same neighbour. That
    matters because the neighbour is what a human adjudicator reads when
    deciding whether the token was a misspelling of it.
    """
    found: set[str] = set()
    for key in _delete1(word):
        found.update(index.get(key, ()))
    candidates = sorted(c for c in found if c != word and _within_one_edit(word, c))
    return candidates[0] if candidates else None


def profile_near_miss(
    doc: Document,
    lexicon: Lexicon,
    lexicon_path: Path | None = None,
    *,
    keep_surfaces: bool = True,
) -> NearMissProfile:
    """Count the near-misses in one note.

    ``lexicon`` decides what counts as *known* for the candidate filter and
    ``lexicon_path`` builds the neighbourhood index. They are separate arguments
    because the caller already holds a loaded :class:`~robustehr.lexicon.Lexicon`
    and the index is cached across notes on the path.
    """
    from robustehr.metrics.dqp import unrecognized_words

    index = deletion_index(lexicon_path)
    known = _known_terms(lexicon_path)
    surfaces: Counter[str] = Counter()
    candidates = 0
    hits = 0
    seen: dict[str, bool] = {}
    for word in unrecognized_words(doc, lexicon):
        if not word.isalpha() or len(word) < MIN_LENGTH or word in known:
            continue
        candidates += 1
        if word not in seen:
            seen[word] = nearest(word, index) is not None
        if seen[word]:
            hits += 1
            if keep_surfaces:
                surfaces[word] += 1
    return NearMissProfile(
        note_uid=doc.uid,
        content_tokens=sum(1 for t in doc.tokens if t.is_content),
        candidates=candidates,
        near_miss=hits,
        surfaces=surfaces,
    )


__all__ = [
    "MIN_LENGTH",
    "NearMissProfile",
    "deletion_index",
    "nearest",
    "profile_near_miss",
]
