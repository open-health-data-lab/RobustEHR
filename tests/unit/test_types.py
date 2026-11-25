"""Value-type invariants, especially the no-floats-on-control-flow rule."""

from __future__ import annotations

from fractions import Fraction

import pytest

from robustehr.types import (
    Anchor,
    CountSeverity,
    Edit,
    EditKind,
    RateSeverity,
    Span,
    SubUnitPolicy,
    UnitKind,
    requested_k,
)


class TestSpan:
    def test_rejects_inverted(self) -> None:
        with pytest.raises(ValueError, match="invalid span"):
            Span(10, 4)

    def test_overlap_is_half_open(self) -> None:
        assert not Span(0, 5).overlaps(Span(5, 10))
        assert Span(0, 6).overlaps(Span(5, 10))

    def test_empty_spans_never_overlap(self) -> None:
        assert not Span(5, 5).overlaps(Span(0, 10))
        assert not Span(5, 5).overlaps(Span(5, 5))

    def test_strictly_inside_excludes_boundaries(self) -> None:
        outer = Span(10, 20)
        assert Span(12, 15).strictly_inside(outer)
        assert not Span(10, 15).strictly_inside(outer)
        assert not Span(15, 20).strictly_inside(outer)


class TestSeverity:
    @pytest.mark.parametrize("literal", ["0", "1", "0.1", "0.30", "0.5", "1.0", "0.001"])
    def test_accepts_decimal_literals(self, literal: str) -> None:
        assert isinstance(RateSeverity(literal).value, Fraction)

    @pytest.mark.parametrize("literal", ["1.5", "-0.1", "30%", "1e-1", "abc", ""])
    def test_rejects_non_literals(self, literal: str) -> None:
        with pytest.raises(ValueError, match="severity must be"):
            RateSeverity(literal)

    def test_value_is_exact(self) -> None:
        # The whole reason severities are not floats.
        assert RateSeverity("0.1").value + RateSeverity("0.2").value == Fraction(3, 10)
        assert 0.1 + 0.2 != 0.3

    def test_canonical_form_is_stable(self) -> None:
        assert RateSeverity("0.30").canon() == RateSeverity("0.3").canon()
        assert RateSeverity("0.30").canon() == "rate:0.3"

    def test_count_severity_canon(self) -> None:
        assert CountSeverity(3, UnitKind.PARAGRAPH).canon() == "count:3:paragraph"


class TestRequestedK:
    def test_ceil_never_makes_low_severity_a_noop(self) -> None:
        # A 50-sentence note at 1% floors to zero, which manufactures a fake
        # flat region at the bottom of every dose-response curve.
        assert requested_k(RateSeverity("0.01"), 50, SubUnitPolicy.FLOOR) == 0
        assert requested_k(RateSeverity("0.01"), 50, SubUnitPolicy.CEIL) == 1

    @pytest.mark.parametrize(
        ("rate", "n", "expected"),
        [("0.10", 100, 10), ("0.30", 100, 30), ("0.5", 7, 4), ("0", 100, 0), ("1", 13, 13)],
    )
    def test_ceil_arithmetic(self, rate: str, n: int, expected: int) -> None:
        assert requested_k(RateSeverity(rate), n, SubUnitPolicy.CEIL) == expected

    def test_zero_eligible_yields_zero(self) -> None:
        assert requested_k(RateSeverity("0.50"), 0, SubUnitPolicy.CEIL) == 0

    def test_count_severity_scales_by_enclosing_unit(self) -> None:
        assert requested_k(CountSeverity(3, UnitKind.PARAGRAPH), 12, SubUnitPolicy.CEIL) == 36


class TestEdit:
    def _edit(self, **kw: object) -> Edit:
        base: dict[str, object] = {
            "start": 0,
            "end": 4,
            "replacement": "X",
            "op_id": "test.op",
            "unit_id": "token:0:4",
        }
        base.update(kw)
        return Edit(**base)  # type: ignore[arg-type]

    def test_kind_inference(self) -> None:
        assert self._edit().kind is EditKind.REPLACE
        assert self._edit(replacement="").kind is EditKind.DELETE
        assert self._edit(start=3, end=3, replacement="!").kind is EditKind.INSERT

    def test_rejects_noop(self) -> None:
        with pytest.raises(ValueError, match="no-op"):
            self._edit(start=3, end=3, replacement="")

    def test_edit_id_is_content_addressed(self) -> None:
        assert self._edit().edit_id == self._edit().edit_id
        assert self._edit().edit_id != self._edit(replacement="Y").edit_id

    def test_insertions_order_around_a_replacement(self) -> None:
        left = self._edit(start=5, end=5, replacement="L", anchor=Anchor.LEFT)
        mid = self._edit(start=5, end=9, replacement="M")
        right = self._edit(start=5, end=5, replacement="R", anchor=Anchor.RIGHT)
        assert [e.replacement for e in sorted([right, mid, left], key=lambda e: e.sort_key)] == [
            "L",
            "M",
            "R",
        ]

    def test_boundary_insertion_does_not_conflict(self) -> None:
        replace = self._edit(start=10, end=20)
        assert not self._edit(start=10, end=10, replacement="!").conflicts_with(replace)
        assert not self._edit(start=20, end=20, replacement="!").conflicts_with(replace)
        assert self._edit(start=15, end=15, replacement="!").conflicts_with(replace)

    def test_overlapping_replacements_conflict(self) -> None:
        assert self._edit(start=0, end=10).conflicts_with(self._edit(start=5, end=15))
        assert not self._edit(start=0, end=10).conflicts_with(self._edit(start=10, end=15))

    def test_sort_key_is_total_over_identical_proposals(self) -> None:
        a = self._edit(op_id="a.op")
        b = self._edit(op_id="b.op")
        assert a.sort_key != b.sort_key
