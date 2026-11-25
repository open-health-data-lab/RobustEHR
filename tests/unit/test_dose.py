"""Dose accounting: the conventions that stop a sweep producing wrong figures."""

from __future__ import annotations

from fractions import Fraction

import pytest

from robustehr.dose import (
    DoseRecord,
    DoseSpec,
    DoseStatus,
    as_pair,
    canonical_params,
    ratio,
    resolve_status,
    scope_canon,
)
from robustehr.types import SubUnitPolicy, UnitKind
from robustehr.version import SCHEMA_VERSION


def record(**overrides: object) -> DoseRecord:
    base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": "r1",
        "note_uid": "n1",
        "note_sha256": "a" * 64,
        "segmenter_version": "seg/1.0.0",
        "op_id": "render.header_delete",
        "op_version": "1.0.0+rabc",
        "severity_canon": "rate:0.3",
        "scope_canon": "target=all|pheno=agnostic",
        "stage_index": 0,
        "unit_kind": "header",
        "dose_kind": "rate",
        "total_n": 100,
        "scope_n": 100,
        "protected_n": 10,
        "eligible_n": 90,
        "requested_k": 27,
        "selected_n": 27,
        "proposed_n": 27,
        "applied_n": 25,
        "rejected_n": 2,
        "rejection_reasons": {"overlap": 2},
        "chars_removed": 300,
        "chars_added": 0,
        "lines_added": 0,
        "lines_removed": 0,
        "edit_cost": 300,
        "tokens_changed": 50,
        "tokens_total": 2000,
        "doc_chars": 12000,
        "status": DoseStatus.APPLIED,
        "output_sha256": "b" * 64,
        "output_identical": False,
    }
    base.update(overrides)
    return DoseRecord(**base)  # type: ignore[arg-type]


class TestNullIsNotZero:
    """Averaging zeros silently under-reports every operator that sometimes
    does not apply. A rate with no denominator is None, not 0."""

    def test_zero_denominator_gives_none(self) -> None:
        assert ratio(0, 0) is None
        assert ratio(5, 0) is None

    def test_inapplicable_cell_reports_null_rates(self) -> None:
        cell = record(total_n=0, scope_n=0, eligible_n=0, requested_k=0, applied_n=0)
        assert cell.achieved_eligible is None
        assert cell.achieved_total is None
        assert cell.eligibility_rate is None

    def test_zero_applied_with_eligible_units_is_a_real_zero(self) -> None:
        """A genuine zero and a null are different scientific claims."""
        cell = record(applied_n=0)
        assert cell.achieved_eligible == Fraction(0, 1)
        assert cell.achieved_eligible is not None


class TestExactRates:
    def test_rates_are_exact_fractions(self) -> None:
        assert record(applied_n=1, eligible_n=3).achieved_eligible == Fraction(1, 3)

    def test_rates_serialize_as_integer_pairs(self) -> None:
        """A float rate would make output byte-nonreproducible for no benefit."""
        assert as_pair(Fraction(1, 3)) == (1, 3)
        assert as_pair(None) is None

    def test_row_carries_no_floats(self) -> None:
        row = record().to_row()
        assert not any(isinstance(v, float) for v in row.values())


class TestDerivedMetrics:
    def test_dose_inflation_exposes_rounding(self) -> None:
        """Ceiling a sub-unit request pushes realized dose above nominal, which
        is exactly why figures plot achieved rather than requested."""
        cell = record(eligible_n=50, requested_k=1, applied_n=1)
        assert cell.achieved_eligible == Fraction(1, 50)
        assert cell.dose_inflation == Fraction(1, 1)

    def test_dose_inflation_is_null_when_nothing_was_requested(self) -> None:
        assert record(requested_k=0).dose_inflation is None

    def test_acer_is_edit_cost_over_document_length(self) -> None:
        assert record(edit_cost=120, doc_chars=12000).acer == Fraction(1, 100)

    def test_eligibility_rate_shows_how_much_was_withheld(self) -> None:
        cell = record(total_n=100, eligible_n=90)
        assert cell.eligibility_rate == Fraction(9, 10)


class TestStatus:
    def test_no_units_of_that_kind(self) -> None:
        assert (
            resolve_status(total_n=0, scope_n=0, eligible_n=0, requested_k=0, applied_n=0)
            is DoseStatus.NA_NO_ELIGIBLE
        )

    def test_scope_selected_nothing(self) -> None:
        """Kept distinct from NA_NO_ELIGIBLE so an applicability report can tell
        "this operator does not apply here" from "this scope does not"."""
        assert (
            resolve_status(total_n=50, scope_n=0, eligible_n=0, requested_k=0, applied_n=0)
            is DoseStatus.NA_SCOPE_EMPTY
        )

    def test_everything_protected(self) -> None:
        assert (
            resolve_status(total_n=50, scope_n=50, eligible_n=0, requested_k=0, applied_n=0)
            is DoseStatus.NA_ALL_PROTECTED
        )

    def test_rounded_to_zero(self) -> None:
        assert (
            resolve_status(total_n=50, scope_n=50, eligible_n=50, requested_k=0, applied_n=0)
            is DoseStatus.UNDER_DOSED
        )

    def test_all_edits_conflicted(self) -> None:
        assert (
            resolve_status(total_n=50, scope_n=50, eligible_n=50, requested_k=5, applied_n=0)
            is DoseStatus.NO_CHANGE
        )

    def test_saturated(self) -> None:
        assert (
            resolve_status(total_n=10, scope_n=10, eligible_n=10, requested_k=99, applied_n=10)
            is DoseStatus.SATURATED
        )

    def test_applicability_flag(self) -> None:
        assert record().is_applicable
        assert not record(status=DoseStatus.NA_NO_ELIGIBLE).is_applicable
        assert not record(status=DoseStatus.NA_ALL_PROTECTED).is_applicable
        assert record(status=DoseStatus.UNDER_DOSED).is_applicable


class TestSeedCanonicalization:
    def test_severity_is_refused_in_params(self) -> None:
        """Letting severity back in through a parameter dict would silently
        break nested severity ladders and start mixing dose with sampling noise."""
        for key in ("severity", "Severity", "rate", "dose", "k"):
            with pytest.raises(ValueError, match="deliberately excluded"):
                canonical_params({key: "0.3"})

    def test_params_are_order_stable(self) -> None:
        assert canonical_params({"b": 2, "a": 1}) == canonical_params({"a": 1, "b": 2})
        assert canonical_params({"mode": "delete", "cap": 3}) == "cap=3;mode=delete"

    def test_empty_params(self) -> None:
        assert canonical_params({}) == ""

    def test_scope_canon_is_order_stable(self) -> None:
        a = scope_canon(phenotype_scope="protect", phenotypes=("hfref", "hypertension"))
        b = scope_canon(phenotype_scope="protect", phenotypes=("hypertension", "hfref"))
        assert a == b
        assert "p=hfref,hypertension" in a

    def test_scope_canon_defaults(self) -> None:
        assert scope_canon() == "target=all|pheno=agnostic"


class TestDoseSpec:
    def test_rate_spec(self) -> None:
        spec = DoseSpec(UnitKind.HEADER, denominator_doc="canonical section headers")
        assert spec.dose_kind == "rate"
        assert spec.sub_unit_policy is SubUnitPolicy.CEIL

    def test_count_per_unit_requires_a_scope(self) -> None:
        with pytest.raises(ValueError, match="count_scope"):
            DoseSpec(UnitKind.SENTENCE, dose_kind="count_per_unit")

    def test_unknown_dose_kind_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown dose_kind"):
            DoseSpec(UnitKind.TOKEN, dose_kind="percentage")

    def test_denominator_doc_is_carried(self) -> None:
        """This sentence goes into the paper's methods table so a reader knows
        what "30%" was 30% of."""
        spec = DoseSpec(
            UnitKind.SPACE_RUN, denominator_doc="runs of two or more spaces between tokens"
        )
        assert "two or more spaces" in spec.denominator_doc
