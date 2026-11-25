"""Edit application: conflict resolution, alignment round-trip, reflow contract."""

from __future__ import annotations

import pytest

from robustehr.edits import RejectionReason, apply_edits, levenshtein
from robustehr.types import Anchor, Edit, ReflowPolicy, Span

TEXT = "The patient denies chest pain and reports mild dyspnea on exertion."


def edit(start: int, end: int, replacement: str, **kw: object) -> Edit:
    base: dict[str, object] = {"op_id": "test.op", "unit_id": f"u:{start}:{end}"}
    base.update(kw)
    return Edit(start=start, end=end, replacement=replacement, **base)  # type: ignore[arg-type]


class TestApplication:
    def test_no_edits_is_identity(self) -> None:
        result = apply_edits(TEXT, [])
        assert result.text == TEXT
        assert result.unchanged
        assert result.alignment.src_to_dst(10) == 10

    def test_single_replacement(self) -> None:
        result = apply_edits(TEXT, [edit(12, 18, "reports")])
        assert result.text.startswith("The patient reports chest pain")
        assert result.chars_removed == 6
        assert result.chars_added == 7

    def test_disjoint_edits_compose(self) -> None:
        result = apply_edits(TEXT, [edit(4, 11, "pt"), edit(12, 18, "reports")])
        assert result.text.startswith("The pt reports chest pain")
        assert len(result.applied) == 2

    def test_insertion_and_deletion(self) -> None:
        result = apply_edits("abc", [edit(0, 0, ">>"), edit(1, 2, "")])
        assert result.text == ">>ac"

    def test_output_independent_of_proposal_order(self) -> None:
        a, b, c = edit(4, 11, "pt"), edit(12, 18, "reports"), edit(19, 24, "CP")
        assert (
            apply_edits(TEXT, [a, b, c]).text
            == apply_edits(TEXT, [c, a, b]).text
            == apply_edits(TEXT, [b, c, a]).text
        )

    def test_out_of_bounds_rejected(self) -> None:
        result = apply_edits("abc", [edit(0, 99, "x")])
        assert result.text == "abc"
        assert result.rejected[0].reason is RejectionReason.OUT_OF_BOUNDS

    def test_noop_replacement_rejected(self) -> None:
        result = apply_edits(TEXT, [edit(0, 3, "The")])
        assert result.rejected[0].reason is RejectionReason.NO_CHANGE


class TestConflictResolution:
    def test_first_in_total_order_wins(self) -> None:
        keeper = edit(0, 10, "AAA", op_id="a.op")
        loser = edit(5, 15, "BBB", op_id="b.op")
        result = apply_edits(TEXT, [loser, keeper])
        assert result.applied == (keeper,)
        assert result.rejected[0].edit == loser
        assert result.rejected[0].reason is RejectionReason.OVERLAP

    def test_op_priority_beats_offset_ties(self) -> None:
        low = edit(0, 10, "LOW", op_id="z.op", op_priority=0)
        high = edit(0, 10, "HIGH", op_id="a.op", op_priority=5)
        result = apply_edits(TEXT, [high, low])
        assert result.applied == (low,)  # lower op_priority wins

    def test_adjacent_edits_do_not_conflict(self) -> None:
        result = apply_edits(TEXT, [edit(0, 3, "A"), edit(3, 4, "-")])
        assert len(result.applied) == 2

    def test_group_is_atomic(self) -> None:
        """If one member cannot land, none of them may."""
        blocker = edit(0, 10, "BLOCK", op_id="a.op")
        member1 = edit(20, 24, "x1", op_id="b.op", group_id="g1")
        member2 = edit(5, 9, "x2", op_id="b.op", group_id="g1")  # conflicts with blocker
        result = apply_edits(TEXT, [blocker, member1, member2])
        assert result.applied == (blocker,)
        assert {r.edit for r in result.rejected} == {member1, member2}
        assert RejectionReason.GROUP_MEMBER_REJECTED.value in result.rejection_counts

    def test_viable_group_lands_together(self) -> None:
        m1 = edit(0, 3, "A", group_id="g1")
        m2 = edit(20, 24, "B", group_id="g1")
        result = apply_edits(TEXT, [m1, m2])
        assert len(result.applied) == 2

    def test_boundary_insertions_coexist_with_replacement(self) -> None:
        result = apply_edits(
            "abcdef",
            [
                edit(2, 2, "<", anchor=Anchor.LEFT, op_id="a.op"),
                edit(2, 4, "XY", op_id="b.op"),
                edit(2, 2, ">", anchor=Anchor.RIGHT, op_id="c.op"),
            ],
        )
        assert result.text == "ab<XY>ef"


class TestReflowContract:
    def test_preserve_rejects_line_count_change(self) -> None:
        """The trap this exists to close.

        A sentence span on hard-wrapped text contains newlines. Replacing it
        with single-line text would silently also apply a structure-flattening
        corruption, contaminating any claim that the operator was isolated.
        """
        text = "denies chest\npain and fever"
        result = apply_edits(text, [edit(0, 17, "reports chest pain")])
        assert result.text == text
        assert result.rejected[0].reason is RejectionReason.REFLOW_VIOLATION

    def test_preserve_accepts_matching_line_count(self) -> None:
        text = "denies chest\npain and fever"
        result = apply_edits(text, [edit(0, 17, "reports ches\npain")])
        assert len(result.applied) == 1

    def test_flatten_opts_in(self) -> None:
        text = "denies chest\npain and fever"
        result = apply_edits(text, [edit(0, 17, "reports chest pain", reflow=ReflowPolicy.FLATTEN)])
        assert result.text == "reports chest pain and fever"
        assert result.lines_removed == 1
        assert result.lines_added == 0

    def test_verbatim_requires_single_line(self) -> None:
        result = apply_edits("a\nb", [edit(0, 3, "x", reflow=ReflowPolicy.VERBATIM)])
        assert result.rejected[0].reason is RejectionReason.REFLOW_VIOLATION


class TestAlignment:
    def test_round_trip_for_unedited_characters(self) -> None:
        result = apply_edits(TEXT, [edit(12, 18, "reports")])
        align = result.alignment
        for i in range(len(TEXT)):
            if 12 <= i < 18:
                continue
            mapped = align.src_to_dst(i)
            assert mapped is not None
            assert align.dst_to_src(mapped) == i

    def test_edited_characters_map_to_none(self) -> None:
        result = apply_edits(TEXT, [edit(12, 18, "reports")])
        assert all(result.alignment.src_to_dst(i) is None for i in range(12, 18))

    def test_deleted_span_maps_to_none(self) -> None:
        result = apply_edits(TEXT, [edit(12, 18, "")])
        assert result.alignment.src_span_to_dst(Span(12, 18)) is None

    def test_surviving_span_contracts(self) -> None:
        # Replace "chest" inside "chest pain"; the span should shrink to "pain".
        result = apply_edits(TEXT, [edit(19, 24, "")])
        mapped = result.alignment.src_span_to_dst(Span(19, 29))
        assert mapped is not None
        assert result.text[mapped.start : mapped.end] == " pain"

    def test_identity_alignment(self) -> None:
        result = apply_edits(TEXT, [])
        assert result.alignment.src_to_dst(0) == 0
        assert result.alignment.src_to_dst(len(TEXT) - 1) == len(TEXT) - 1
        assert result.alignment.src_to_dst(len(TEXT)) is None

    def test_offsets_survive_multiple_edits(self) -> None:
        result = apply_edits(TEXT, [edit(4, 11, "pt"), edit(34, 41, "notes")])
        tail = result.alignment.src_to_dst(60)
        assert tail is not None
        assert result.text[tail] == TEXT[60]

    def test_runs_are_merged(self) -> None:
        result = apply_edits(TEXT, [])
        assert len(result.alignment.lengths) == 1


class TestEditCost:
    def test_levenshtein_basics(self) -> None:
        assert levenshtein("", "") == 0
        assert levenshtein("abc", "abc") == 0
        assert levenshtein("abc", "") == 3
        assert levenshtein("kitten", "sitting") == 3

    def test_cost_accumulates_over_edits(self) -> None:
        result = apply_edits(TEXT, [edit(12, 18, "denied"), edit(4, 11, "patinet")])
        assert result.edit_cost == levenshtein("denies", "denied") + levenshtein(
            "patient", "patinet"
        )

    @pytest.mark.parametrize("replacement", ["", "x", "much longer replacement string"])
    def test_char_accounting(self, replacement: str) -> None:
        result = apply_edits(TEXT, [edit(4, 11, replacement)])
        assert result.chars_removed == 7
        assert result.chars_added == len(replacement)
        assert len(result.text) == len(TEXT) - 7 + len(replacement)
