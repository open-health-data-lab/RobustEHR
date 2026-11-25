"""Is a string pronounceable as English?

A morpheme rule can splice two legal pieces into an illegal whole. ``pre`` and
``prednisone`` both look like a match, but ``post`` + ``dnisone`` yields
``postdnisone``, whose ``stdn`` cluster is not a sound sequence English permits.
No speech recogniser could emit it and no typist would produce it, so rejecting
it needs *phonology*, not a dictionary: the string is impossible independently
of whether any word happens to exist.

This is deliberately a general algorithm rather than a list of bad outputs.
Listing the failures found on one corpus fixes exactly those failures; encoding
the constraint that produced them fixes the ones nobody has hit yet, in any
vocabulary and any specialty.

The model is standard syllable phonotactics:

* a word-initial consonant run is a syllable **onset** and must be one English
  allows — a closed set, not a sonority heuristic, because sonority alone
  admits ``dn`` and English does not;
* a word-medial run splits into a **coda** for the preceding syllable and an
  **onset** for the next, and is legal if *some* split works;
* a word-final run is a **coda**, where English is famously permissive
  (``sixths``, ``twelfths``), so length alone bounds it.

That asymmetry is the whole discriminating power: onsets are restrictive, and
a spliced junction usually fails there.
"""

from __future__ import annotations

from functools import lru_cache
from itertools import pairwise

_VOWELS = frozenset("aeiouy")

#: Consonant clusters English permits at the start of a syllable. A closed
#: linguistic fact about the language, not a list derived from any corpus.
#: Written as an explicit tuple rather than a split string so each group stays
#: readable and reviewable; these are linguistic facts about English, not data
#: derived from any corpus.
_ONSETS: frozenset[str] = frozenset(
    (
        # stop or fricative + liquid or glide
        "pl",
        "pr",
        "bl",
        "br",
        "tr",
        "dr",
        "tw",
        "dw",
        "kl",
        "kr",
        "cl",
        "cr",
        "gl",
        "gr",
        "gw",
        "kw",
        "qu",
        "fl",
        "fr",
        "thr",
        "shr",
        "sl",
        "sw",
        "vr",
        # s + consonant, and s + consonant + liquid
        "sp",
        "st",
        "sk",
        "sc",
        "sm",
        "sn",
        "sf",
        "sph",
        "spl",
        "spr",
        "str",
        "skr",
        "scr",
        "squ",
        "sthm",
        # digraphs and their liquid extensions
        "ch",
        "sh",
        "th",
        "ph",
        "wh",
        "gh",
        "rh",
        "chr",
        "chl",
        "phr",
        "phl",
        "schr",
        "schw",
        "sch",
        "shw",
        # historically licensed onsets that survive in clinical vocabulary
        "kn",
        "gn",
        "pn",
        "ps",
        "pt",
        "mn",
        "xy",
        "tz",
    )
)

#: Sonority classes, low to high. Used only for codas, where the constraint is
#: a falling profile rather than membership of a fixed set.
_SONORITY: dict[str, int] = {
    **dict.fromkeys("ptkbdgqc", 1),
    **dict.fromkeys("fvszxh", 2),
    **dict.fromkeys("mn", 3),
    **dict.fromkeys("lr", 4),
    **dict.fromkeys("wjy", 5),
}

_MAX_FINAL_CODA = 5  # "twelfths" is an ordinary word
_MAX_MEDIAL_RUN = 4


def _legal_onset(cluster: str) -> bool:
    return len(cluster) <= 1 or cluster in _ONSETS


def _legal_coda(cluster: str, *, final: bool) -> bool:
    if len(cluster) <= 1:
        return True
    if final:
        # English permits long final codas through inflection. Bound by length
        # rather than by profile, since "sixths" and "twelfths" are ordinary.
        return len(cluster) <= _MAX_FINAL_CODA
    # A medial coda must fall in sonority: "st" closes a syllable, "std" cannot.
    scores = [_SONORITY.get(ch, 2) for ch in cluster]
    return all(a > b for a, b in pairwise(scores))


def _runs(text: str) -> list[tuple[int, str]]:
    """Consonant runs as ``(start_index, cluster)``."""
    out: list[tuple[int, str]] = []
    start: int | None = None
    for index, char in enumerate(text):
        if char in _VOWELS:
            if start is not None:
                out.append((start, text[start:index]))
                start = None
        elif start is None:
            start = index
    if start is not None:
        out.append((start, text[start:]))
    return out


def _run_is_legal(cluster: str, *, at_start: bool, at_end: bool) -> bool:
    """Is one consonant run legal in its position?"""
    if at_start:
        return _legal_onset(cluster)
    if at_end:
        return _legal_coda(cluster, final=True)
    if len(cluster) > _MAX_MEDIAL_RUN:
        return False
    # Legal if the run divides into a closing coda and an opening onset
    # somewhere. Onsets are the restrictive side, which is where a spliced
    # junction usually fails.
    return any(
        _legal_coda(cluster[:cut], final=False) and _legal_onset(cluster[cut:])
        for cut in range(len(cluster) + 1)
    )


@lru_cache(maxsize=8192)
def is_pronounceable(word: str) -> bool:
    """Could this string be an English word, phonologically speaking?

    Says nothing about whether it *is* a word — ``hypotrophy`` and ``brillig``
    both pass. It rejects only strings no speaker could articulate, which is the
    right gate for a substitution claiming to model a mis-hearing or a
    mistyping. Deciding wordhood is a separate question with a separate gate.
    """
    text = "".join(ch for ch in word.lower() if ch.isalpha())
    if not text:
        return False
    if not any(ch in _VOWELS for ch in text):
        return len(text) <= 4  # an acronym, not a word

    return all(
        _run_is_legal(
            cluster,
            at_start=start == 0,
            at_end=start + len(cluster) == len(text),
        )
        for start, cluster in _runs(text)
    )


__all__ = ["is_pronounceable"]
