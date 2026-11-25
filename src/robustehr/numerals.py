"""Numerals written as words, and the numbers that must not be.

The identification half of `lexical.numeral_to_word`. Spelling is delegated to
**num2words**, an established library, rather than hand-rolled — the package's
own rule is to reuse a proven tool and measure any departure from it. Two
departures are made here, both deterministic and both stated:

1. **British connectives are dropped.** ``num2words`` renders 120 as ``one
   hundred and twenty`` and 1250 as ``one thousand, two hundred and fifty``.
   US clinical prose writes ``one hundred twenty``. More importantly the comma
   is a *second* perturbation: it adds a punctuation token, so a run at "30% of
   numerals" would also be changing punctuation, and no result could attribute
   the effect. The normalization is a pure string rewrite over num2words'
   output, applied identically every time.
2. **Not every number is spellable, and unspellable ones are ineligible rather
   than approximated.** See :func:`is_spellable`.

Which numbers are refused, and why each would be wrong to convert:

``4.46``
    A decimal has no single written form — *four point four six*, *four point
    forty-six* and *four and forty-six hundredths* are all defensible, and
    picking one would be inventing a convention rather than applying one.
``007``
    Leading zeros carry information in an identifier and no written form
    preserves them: ``seven`` is not ``007``.
``19891231``
    Above six digits a number in a clinical note is an identifier — an MRN, an
    accession, a date run together — not a quantity. Spelling those is not a
    representation change of the same value, it is noise, so the ceiling is set
    where quantities stop.

The eligibility test and the conversion share one function, so a number can
never be selected and then found unconvertible — that would silently short the
dose.
"""

from __future__ import annotations

import re

#: Above this, a bare integer in a clinical note is an identifier rather than a
#: quantity. Six digits comfortably covers every dose, lab value, weight, volume
#: and count that clinical prose spells out.
MAX_SPELLABLE = 999_999

#: A pure run of digits. Anything else — decimals, ranges, `5mg`, `12-15` — is
#: not a single numeral and is left to the tokenizer's other kinds.
_INTEGER = re.compile(r"^[0-9]+$")

#: `num2words` emits British connectives; clinical US prose does not use them.
#: Order matters: the comma form has to go before the bare `and`.
_BRITISH = ((", ", " "), (" and ", " "))


def is_spellable(surface: str) -> bool:
    """Can this surface be written as words with the value unchanged?

    The eligibility predicate for `lexical.numeral_to_word`, and the same one
    the baseline counts with — so ``numeric_value.spellable`` in Table 1 *is*
    the operator's denominator rather than a number that resembles it.
    """
    return spell(surface) is not None


def spell(surface: str) -> str | None:
    """``"30"`` -> ``"thirty"``, or ``None`` when the value would not survive.

    ``None`` rather than a best effort: an operator that guessed here would
    change what a number means while reporting that it had only changed how the
    number was written.
    """
    if not _INTEGER.match(surface):
        return None
    if len(surface) > 1 and surface[0] == "0":
        return None  # leading zeros are information, and no spelling keeps them
    value = int(surface)
    if value > MAX_SPELLABLE:
        return None
    from num2words import num2words

    words = num2words(value, lang="en")
    for source, replacement in _BRITISH:
        words = words.replace(source, replacement)
    return words


__all__ = ["MAX_SPELLABLE", "is_spellable", "spell"]
