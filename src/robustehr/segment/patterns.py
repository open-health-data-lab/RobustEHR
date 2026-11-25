"""Shared, frozen character classes.

Every pattern in the segmentation layer is built from these rather than from
``\\w``/``\\d``/``\\s``. Those shorthands are Unicode-database dependent, so two
machines on different CPython point releases can disagree about what matches —
which would silently change every dose denominator in the package.

These strings are part of the segmenter's published contract. Changing one is a
breaking change to every previously reported dose, and must bump
``SEGMENTER_VERSION``.
"""

from __future__ import annotations

#: Bumped whenever any pattern or segmentation rule in this package changes.
#: Stamped into every dose record so a reader can tell which denominator applied.
SEGMENTER_VERSION = "seg/1.0.0"

# --- Regex class *fragments*. Only ever interpolated inside `[...]`. ---------
# These are not usable for Python membership tests: `"1" in DIGIT` asks whether
# "1" is one of the literal characters '0', '-', '9'. Use the frozensets below
# for that. Keeping the two families visibly distinct is deliberate — conflating
# them is a silent correctness bug, not a type error.
DIGIT = "0-9"
LOWER = "a-z"
UPPER = "A-Z"
ALPHA = "A-Za-z"
ALNUM = "A-Za-z0-9"
WORD = "A-Za-z0-9_"

# --- Character *sets*. Only ever used for `ch in ...` membership tests. -------
DIGITS = frozenset("0123456789")
LOWERS = frozenset("abcdefghijklmnopqrstuvwxyz")
UPPERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
LETTERS = LOWERS | UPPERS
ALNUMS = LETTERS | DIGITS
WORD_CHARS = ALNUMS | {"_"}

#: Horizontal whitespace. The development corpus contains zero tab characters,
#: but tabs are accepted so the segmenter is not corpus-specific.
HSPACE = " \t"

#: Sentence-terminating punctuation, as used in clinical prose.
TERMINATORS = ".?!"

#: Characters that open or close a bracketed aside.
OPENERS = "([{"
CLOSERS = ")]}"

__all__ = [
    "ALNUM",
    "ALNUMS",
    "ALPHA",
    "CLOSERS",
    "DIGIT",
    "DIGITS",
    "HSPACE",
    "LETTERS",
    "LOWER",
    "LOWERS",
    "OPENERS",
    "SEGMENTER_VERSION",
    "TERMINATORS",
    "UPPER",
    "UPPERS",
    "WORD",
    "WORD_CHARS",
]
