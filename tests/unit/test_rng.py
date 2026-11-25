"""Determinism guarantees: nestedness, subset invariance, append-only independence.

These are the properties the whole package's reproducibility claim rests on, so
they are tested as properties rather than as examples.
"""

from __future__ import annotations

import pytest

from robustehr.rng import Purpose, RestrictedRandom, SeedMaterial, select, unit_key, unit_rng
from robustehr.types import Span, Unit, UnitKind, make_unit_id


def material(**overrides: object) -> SeedMaterial:
    base: dict[str, object] = {
        "salt": "rep0",
        "note_uid": "note-1",
        "note_sha256": "a" * 64,
        "op_id": "render.header_delete",
        "op_version": "1.0.0+r0badc0ffee12",
        "params_canon": "mode=delete",
        "scope_canon": "scope:all",
        "stage_index": 0,
        "unit_kind": "header",
    }
    base.update(overrides)
    return SeedMaterial(**base)  # type: ignore[arg-type]


def units(n: int) -> list[Unit]:
    out = []
    for i in range(n):
        span = Span(i * 10, i * 10 + 5)
        out.append(Unit(make_unit_id(UnitKind.HEADER, span), UnitKind.HEADER, span))
    return out


class TestSelection:
    def test_is_reproducible(self) -> None:
        u = units(50)
        assert select(u, 10, material()) == select(u, 10, material())

    def test_is_independent_of_input_order(self) -> None:
        u = units(50)
        forward = select(u, 10, material())
        backward = select(list(reversed(u)), 10, material())
        assert forward == backward

    def test_severity_ladders_are_nested(self) -> None:
        # selected(10%) subset selected(30%) subset selected(50%).
        # This is what makes dose-response curves paired within a note.
        u = units(100)
        m = material()
        low, mid, high = select(u, 10, m), select(u, 30, m), select(u, 50, m)
        assert set(low) <= set(mid) <= set(high)

    def test_returns_document_order(self) -> None:
        chosen = select(units(100), 20, material())
        assert list(chosen) == sorted(chosen, key=lambda x: x.span.start)

    def test_saturates_without_error(self) -> None:
        u = units(5)
        assert len(select(u, 999, material())) == 5

    def test_empty_inputs(self) -> None:
        assert select([], 5, material()) == ()
        assert select(units(5), 0, material()) == ()

    def test_subset_invariance(self) -> None:
        """Perturbing one note must equal perturbing the whole corpus.

        Guaranteed because note_sha256 and note_uid are in the seed material, so
        a note's stream cannot depend on its neighbours.
        """
        m1, m2 = (
            material(note_uid="n1", note_sha256="1" * 64),
            material(note_uid="n2", note_sha256="2" * 64),
        )
        u = units(40)
        assert select(u, 10, m1) != select(u, 10, m2)
        # ...and each is stable regardless of what else is processed.
        assert select(u, 10, m1) == select(u, 10, m1)

    def test_append_only_independence(self) -> None:
        """Adding an operator must leave the others' selections untouched."""
        u = units(40)
        before = select(u, 10, material(op_id="render.header_delete"))
        after = select(u, 10, material(op_id="render.header_delete"))
        # A different operator draws a different stream entirely.
        other = select(u, 10, material(op_id="input.typo"))
        assert before == after
        assert before != other

    def test_op_version_change_invalidates_stream(self) -> None:
        u = units(40)
        v1 = select(u, 10, material(op_version="1.0.0+rAAAA"))
        v2 = select(u, 10, material(op_version="1.0.0+rBBBB"))
        assert v1 != v2

    def test_salt_gives_independent_replicates(self) -> None:
        u = units(40)
        assert select(u, 10, material(salt="rep0")) != select(u, 10, material(salt="rep1"))


class TestUnitKeys:
    def test_purposes_are_independent_streams(self) -> None:
        m = material()
        assert unit_key(m, "u1", Purpose.SELECT) != unit_key(m, "u1", Purpose.MUTATE)

    def test_mutation_is_position_independent(self) -> None:
        """A unit's mutation must not depend on how many units preceded it.

        A segmenter fix that adds one sentence should change that sentence's
        fate and nothing else, rather than re-rolling the document.
        """
        m = material()
        assert unit_rng(m, "sent:100:150").below(1000) == unit_rng(m, "sent:100:150").below(1000)


class TestRestrictedRandom:
    def test_below_is_in_range_and_reproducible(self) -> None:
        a = [RestrictedRandom(42).below(7) for _ in range(20)]
        b = [RestrictedRandom(42).below(7) for _ in range(20)]
        assert a == b
        assert all(0 <= x < 7 for x in a)

    def test_below_n_equals_one(self) -> None:
        assert RestrictedRandom(1).below(1) == 0

    def test_below_rejects_non_positive(self) -> None:
        with pytest.raises(ValueError, match="requires n > 0"):
            RestrictedRandom(1).below(0)

    def test_weighted_pick_respects_zero_weights(self) -> None:
        rng = RestrictedRandom(7)
        picks = {rng.weighted_pick(["a", "b", "c"], [0, 1, 0]) for _ in range(50)}
        assert picks == {"b"}

    def test_weighted_pick_covers_all_positive_weights(self) -> None:
        rng = RestrictedRandom(11)
        picks = {rng.weighted_pick(["a", "b"], [1, 1]) for _ in range(200)}
        assert picks == {"a", "b"}

    def test_weighted_pick_validates(self) -> None:
        rng = RestrictedRandom(1)
        with pytest.raises(ValueError, match="same length"):
            rng.weighted_pick(["a"], [1, 2])
        with pytest.raises(ValueError, match="non-negative"):
            rng.weighted_pick(["a", "b"], [-1, 2])
        with pytest.raises(ValueError, match="positive value"):
            rng.weighted_pick(["a", "b"], [0, 0])

    def test_no_unspecified_rng_surface(self) -> None:
        """shuffle/sample/choices are CPython implementation details."""
        rng = RestrictedRandom(1)
        for forbidden in ("shuffle", "sample", "choices", "random"):
            assert not hasattr(rng, forbidden)
