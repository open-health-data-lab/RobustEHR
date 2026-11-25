"""How per-note fields become corpus-level ones.

`by_level` decides, per field, whether it is a quantity to be summed and
described or a category to be counted. Getting that wrong is not a rendering
detail: a field that lands in the wrong branch either acquires a `total` that
means nothing or turns into a histogram with one key per note.
"""

from __future__ import annotations

from robustehr.metrics.describe import NoteRow, by_level

LEVEL = "clinical_content"


def rows(**fields: list[object]) -> list[NoteRow]:
    """One `NoteRow` per value, with every field varying together."""
    n = len(next(iter(fields.values())))
    return [
        NoteRow(
            note_uid=f"n{i}",
            units={},
            levels={LEVEL: {name: values[i] for name, values in fields.items()}},
            sections={},
            lexical={},
        )
        for i in range(n)
    ]


def test_counts_are_summed_and_described() -> None:
    block = by_level(rows(n=[10, 20, 30, 40]))[LEVEL]["n"]
    assert block["total"] == 100
    assert block["min"] == 10
    assert block["max"] == 40


def test_a_ratio_gets_a_distribution_and_no_total() -> None:
    """The regression: `clinical_share` became a 1,375-key float histogram.

    A share is not a quantity. Summing 1,388 per-note shares produces a number
    with no referent, and falling through to the categorical branch produces one
    dictionary key per distinct float — which is one per note, since no two
    notes share a ratio. Neither is readable, and the JSON is what a downstream
    statistical pipeline consumes.
    """
    block = by_level(rows(clinical_share=[0.0, 0.25, 0.5, 0.75]))[LEVEL]["clinical_share"]

    assert "total" not in block, "a sum of ratios has no referent"
    assert block["median"] == 0.5
    assert block["min"] == 0.0
    assert block["max"] == 0.75


def test_booleans_stay_categorical() -> None:
    """`bool` is an `int` in Python, so the numeric branch would swallow flags.

    A summed flag reports how many notes were true under a heading that reads
    like a token count.
    """
    block = by_level(rows(flag=[True, True, False]))[LEVEL]["flag"]
    assert block == {"False": 1, "True": 2}


def test_a_field_missing_from_some_notes_is_not_summed() -> None:
    """A partial field would otherwise report a total over an unstated subset."""
    block = by_level(rows(n=[5, None, 7]))[LEVEL]["n"]
    assert "total" not in block, "the denominator is not the corpus"
