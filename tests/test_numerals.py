"""The number speller, and the numbers it must refuse.

`lexical.numeral_to_word` claims to change how a number is WRITTEN without
changing what it IS. That claim rests entirely on this module, so the golden
table below is the operator's contract rather than a smoke test.
"""

from __future__ import annotations

import pytest

from robustehr.numerals import MAX_SPELLABLE, is_spellable, spell


class TestSpelling:
    """US clinical style: no `and`, no comma, exactly the spec's examples."""

    @pytest.mark.parametrize(
        ("digits", "words"),
        [
            ("0", "zero"),
            ("5", "five"),
            ("7", "seven"),
            ("10", "ten"),
            ("13", "thirteen"),
            ("17", "seventeen"),
            ("25", "twenty-five"),
            ("30", "thirty"),
            ("40", "forty"),
            ("64", "sixty-four"),
            ("99", "ninety-nine"),
            ("100", "one hundred"),
            # The spec's own example. num2words renders this as "one hundred
            # and twenty"; the connective is normalised away.
            ("120", "one hundred twenty"),
            ("650", "six hundred fifty"),
            ("1000", "one thousand"),
            # And this one carries a comma in num2words' output, which would add
            # a punctuation token to a run that claims to be changing numerals.
            ("1250", "one thousand two hundred fifty"),
            ("999999", "nine hundred ninety-nine thousand nine hundred ninety-nine"),
        ],
    )
    def test_golden_table(self, digits: str, words: str) -> None:
        assert spell(digits) == words

    def test_no_british_connectives_anywhere(self) -> None:
        """Swept rather than sampled: one stray `and` is one wrong edit."""
        for value in range(0, 2001):
            words = spell(str(value))
            assert words is not None
            assert " and " not in words, f"{value} -> {words}"
            assert "," not in words, f"{value} -> {words}"


class TestRefusals:
    """Unspellable is ineligible, never approximated.

    Each of these would be a semantic change reported as a representation
    change, which is the one thing the operator's contract forbids.
    """

    @pytest.mark.parametrize(
        ("surface", "why"),
        [
            ("4.46", "a decimal has no single written form"),
            ("0.5", "same"),
            ("007", "leading zeros are information no spelling keeps"),
            ("00", "same"),
            ("1000000", "above six digits it is an identifier, not a quantity"),
            ("12-15", "a range is not one numeral"),
            ("5mg", "not a bare numeral"),
            ("", "nothing to spell"),
            ("abc", "not a numeral"),
        ],
    )
    def test_refused(self, surface: str, why: str) -> None:
        assert spell(surface) is None, why
        assert not is_spellable(surface)

    def test_the_ceiling_is_inclusive(self) -> None:
        assert spell(str(MAX_SPELLABLE)) is not None
        assert spell(str(MAX_SPELLABLE + 1)) is None


def test_eligibility_and_conversion_cannot_disagree() -> None:
    """`is_spellable` is `spell` — one function, so a dose is never short.

    If eligibility used a different rule from conversion, a unit could be
    selected and then found unconvertible: the operator would propose fewer
    edits than the framework selected units for, and the realized dose would
    silently fall below the requested one.
    """
    for value in [*range(0, 500), 1234, 99999, 1000000]:
        surface = str(value)
        assert is_spellable(surface) == (spell(surface) is not None)
