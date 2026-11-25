"""Proportional allocation across strata, for concept-targeted experiments.

The property under test is not "the sampler is random" — it is that **every
stratum is corrupted at the same rate**. A uniform draw over a note whose
concepts are 130 medications and 13 devices takes zero devices often enough to
matter, and a result that then attributes degradation to a category is reading
its own sampling noise.
"""

from __future__ import annotations

from robustehr.rng import SeedMaterial, select, select_stratified
from robustehr.types import Span, Unit, UnitKind


def material(op_id: str = "test.op") -> SeedMaterial:
    return SeedMaterial(
        salt="rep0",
        note_uid="n1",
        note_sha256="0" * 64,
        op_id=op_id,
        op_version="1.0.0",
        params_canon="",
        scope_canon="target=all|pheno=agnostic",
        stage_index=0,
        unit_kind="word",
    )


def pool(sizes: dict[str, int]) -> tuple[list[Unit], dict[str, str]]:
    """``sizes`` units per stratum, plus the unit -> stratum map."""
    units: list[Unit] = []
    strata: dict[str, str] = {}
    offset = 0
    for name, n in sizes.items():
        for _ in range(n):
            span = Span(offset, offset + 5)
            unit = Unit(f"word:{offset}:{offset + 5}", UnitKind.WORD, span)
            units.append(unit)
            strata[unit.unit_id] = name
            offset += 10
    return units, strata


#: Deliberately lopsided, and the small ones are the point: they are where a
#: uniform draw goes to zero.
SIZES = {"medication": 130, "anatomy": 232, "disease": 143, "device": 13, "lab_result": 2}


class TestEveryStratumIsCorruptedAtTheSameRate:
    def test_large_strata_land_on_the_requested_rate(self) -> None:
        units, strata = pool(SIZES)
        chosen = select_stratified(units, 1, 10, material(), lambda u: strata[u.unit_id])
        hit = {name: 0 for name in SIZES}
        for unit in chosen:
            hit[strata[unit.unit_id]] += 1
        for name, size in SIZES.items():
            if size < 50:
                continue
            assert abs(hit[name] / size - 0.10) < 0.01, f"{name}: {hit[name]}/{size}"

    def test_small_strata_are_unbiased_across_notes(self) -> None:
        """The property rounding gets wrong, and the reason for the offset.

        A stratum of 2 units at 10% is owed 0.2. Rounding up gives it 1 in every
        note — a realized rate of 0.5, five times what was asked. Rounding down
        gives it 0 everywhere, which is the failure stratifying exists to fix.
        Averaged over notes the answer must come out at the requested rate, and
        that is what a per-(note, stratum) offset buys.
        """
        total_hit = total_size = 0
        for note in range(400):
            units, strata = pool({"tiny": 2})
            mat = SeedMaterial(
                salt="rep0",
                note_uid=f"n{note}",
                note_sha256=f"{note:064d}",
                op_id="test.op",
                op_version="1.0.0",
                params_canon="",
                scope_canon="target=all|pheno=agnostic",
                stage_index=0,
                unit_kind="word",
            )
            chosen = select_stratified(units, 1, 10, mat, lambda u, s=strata: s[u.unit_id])
            total_hit += len(chosen)
            total_size += len(units)
        rate = total_hit / total_size
        assert 0.07 < rate < 0.13, f"a 2-unit stratum realized {rate:.3f} against 0.10"

    def test_a_uniform_draw_does_not_manage_this(self) -> None:
        """Not a criticism of `select` — a demonstration that the two differ.

        If this ever stops failing, the stratified selector has stopped earning
        its place and the extra machinery should go.
        """
        units, strata = pool(SIZES)
        chosen = select(units, len(units) // 10, material())
        hit = {name: 0 for name in SIZES}
        for unit in chosen:
            hit[strata[unit.unit_id]] += 1
        rates = {n: hit[n] / SIZES[n] for n in SIZES}
        assert min(rates.values()) < 0.05, (
            f"uniform sampling happened to be even here ({rates}); pick a "
            "harder pool or drop the stratified selector"
        )


class TestFrameworkPropertiesSurvive:
    def test_severity_ladders_still_nest(self) -> None:
        """`selected(0.05)` must remain a subset of `selected(0.10)`.

        Stratification changes *how many* come from each stratum, not the rank
        order within one, so the nesting that makes a dose-response curve paired
        is preserved. Losing it would cost more than the stratification is worth.
        """
        units, strata = pool(SIZES)
        seen: set[str] = set()
        for numerator in (1, 2, 3, 5):
            chosen = select_stratified(
                units, numerator, 20, material(), lambda u: strata[u.unit_id]
            )
            ids = {u.unit_id for u in chosen}
            assert seen <= ids, f"{numerator}/20 broke nesting"
            seen = ids

    def test_result_is_independent_of_input_order(self) -> None:
        units, strata = pool(SIZES)
        forward = select_stratified(units, 1, 10, material(), lambda u: strata[u.unit_id])
        backward = select_stratified(
            list(reversed(units)), 1, 10, material(), lambda u: strata[u.unit_id]
        )
        assert forward == backward

    def test_output_is_in_document_order(self) -> None:
        units, strata = pool(SIZES)
        chosen = select_stratified(units, 1, 10, material(), lambda u: strata[u.unit_id])
        assert list(chosen) == sorted(chosen, key=lambda u: (u.span.start, u.span.end))

    def test_a_zero_dose_selects_nothing(self) -> None:
        units, strata = pool(SIZES)
        assert select_stratified(units, 0, 10, material(), lambda u: strata[u.unit_id]) == ()

    def test_units_with_no_stratum_are_not_dropped(self) -> None:
        """`_uncategorized` is a stratum, not a bin to discard."""
        units, _ = pool({"a": 20})
        chosen = select_stratified(units, 1, 10, material(), lambda _u: "_uncategorized")
        assert len(chosen) == 2
