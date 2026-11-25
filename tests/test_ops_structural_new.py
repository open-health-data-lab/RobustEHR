"""The five structural operators `details/structural.md` specified.

Framework properties — nesting, protection, determinism, monotonic denominators
— are asserted generically over every registered operator in
`tests/unit/test_operators.py`. What is here is what is specific to each: the
thing it must do, and the thing it must not.
"""

from __future__ import annotations

import pytest

from robustehr.document import Document
from robustehr.ops import registry
from robustehr.ops.base import Scope
from robustehr.runner import apply_operator, severity_ladder

NOTE = """Chief Complaint:
Chest pain

History of Present Illness:
The patient is a 64 year old man with a long history of hypertension
who presents with substernal chest pressure radiating to the left arm.

Past Medical History:
1. Hypertension
2. Diabetes mellitus
3. Chronic kidney disease

Assessment and Plan:
Likely unstable angina.
"""


def run(op_id: str, severity: str, text: str = NOTE, **params: object):  # type: ignore[no-untyped-def]
    registry.register_builtins()
    op = registry.get(op_id)()
    doc = Document.from_text(text, uid="n")
    return doc, apply_operator(
        doc, op, op.meta, severity_ladder(severity)[0], scope=Scope(), salt="rep0", params=params
    )


class TestHeaderRename:
    def test_the_header_becomes_a_different_name_for_the_same_section(self) -> None:
        _, result = run("render.header_rename", "1")
        assert "Past Medical History:" not in result.text
        assert "Chest pain" in result.text, "body content must survive"

    def test_a_lexicon_hit_is_required(self) -> None:
        """A heuristic header has no canonical section, so no equivalence class.

        This is the asymmetry with `render.header_delete`, which can safely take
        a heuristic match: deleting needs no knowledge of what the header meant.
        """
        text = "Wobbly Improvised Label:\nsome content here\n"
        doc, result = run("render.header_rename", "1", text)
        assert result.dose.total_n == 0
        assert result.text == doc.text

    def test_casing_is_carried_over(self) -> None:
        """A rename must not also deliver a capitalisation change."""
        _, result = run("render.header_rename", "1", "PAST MEDICAL HISTORY:\nHypertension\n")
        first = result.text.splitlines()[0].rstrip(":")
        assert first.isupper(), first

    def test_a_header_is_never_renamed_to_the_name_it_has(self) -> None:
        """A no-op edit would still be counted, inflating the realized dose."""
        _, result = run("render.header_rename", "1")
        assert result.dose.applied_n == result.dose.requested_k


class TestListToProse:
    def test_items_are_joined_with_semicolons(self) -> None:
        _, result = run("render.list_to_prose", "1")
        assert "Hypertension; Diabetes mellitus; Chronic kidney disease" in result.text

    def test_the_denominator_is_blocks_not_items(self) -> None:
        """`details/structural.md`: severity is the percentage of identified LISTS."""
        doc, result = run("render.list_to_prose", "1")
        assert result.dose.total_n == len([b for b in doc.lists if len(b.items) >= 2])
        assert result.dose.unit_kind == "list_block"

    def test_a_single_item_list_is_not_eligible(self) -> None:
        """Nothing to join; stripping its marker is `render.bullet_to_prose`."""
        _, result = run("render.list_to_prose", "1", "Problems:\n1. Hypertension\n\nEnd.\n")
        assert result.dose.total_n == 0

    def test_an_indented_continuation_is_folded_in_not_dropped(self) -> None:
        """Walking items rather than lines would silently delete this text."""
        text = "Problems:\n1. Hypertension\n   poorly controlled\n2. Diabetes\n\nEnd.\n"
        _, result = run("render.list_to_prose", "1", text)
        assert "poorly controlled" in result.text


class TestBreakRemoval:
    def test_blocks_run_together(self) -> None:
        _, result = run("render.break_removal", "1")
        assert "left arm. Past Medical History:" in result.text

    def test_no_two_words_are_ever_merged(self) -> None:
        """The spec's explicit constraint: remove structure, not word boundaries."""
        _, result = run("render.break_removal", "1")
        assert "armPast" not in result.text
        for edit in result.apply_result.applied:
            assert edit.replacement == " "

    def test_the_dose_is_over_breaks_not_newlines(self) -> None:
        doc, result = run("render.break_removal", "0.50")
        assert result.dose.total_n == len(doc.breaks)
        assert result.dose.total_n < doc.text.count("\n"), (
            "every newline was counted; hard-wrap continuations must be excluded"
        )


class TestSpaceDelete:
    def test_two_words_merge(self) -> None:
        _, result = run("render.space_delete", "0.30")
        assert result.text != NOTE
        assert len(result.text) < len(NOTE)

    def test_only_single_spaces_between_content_tokens_are_eligible(self) -> None:
        doc, result = run("render.space_delete", "1")
        for edit in result.apply_result.applied:
            assert doc.text[edit.start : edit.end] == " "
            assert edit.replacement == ""

    def test_lab_layout_is_not_eligible(self) -> None:
        """A space in a lab row is column structure, not a word gap."""
        text = "Labs:\nWBC-6.9   RBC-4.46   Hgb-12.8\nNa-140    K-4.1     Cl-104\n"
        _, result = run("render.space_delete", "1", text)
        assert result.dose.total_n == 0


class TestSectionDuplicate:
    def test_a_section_is_repeated_verbatim(self) -> None:
        _, result = run("discourse.section_duplicate", "count:1")
        assert len(result.text) > len(NOTE)
        assert result.dose.applied_n == 1

    def test_the_dose_is_a_count_not_a_rate(self) -> None:
        for literal, expected in (("count:1", 1), ("count:2", 2)):
            _, result = run("discourse.section_duplicate", literal)
            assert result.dose.requested_k == expected
            assert result.dose.severity_canon == f"{literal}:document"

    def test_asking_for_more_sections_than_exist_saturates(self) -> None:
        """Reported as `saturated`, never silently rounded down without a word."""
        doc, result = run("discourse.section_duplicate", "count:5")
        assert result.dose.applied_n == len(doc.sections)
        assert result.dose.status.value == "saturated"

    def test_counts_nest(self) -> None:
        """The section duplicated at count:1 is still duplicated at count:5."""
        spans = {}
        for literal in ("count:1", "count:2", "count:5"):
            _, result = run("discourse.section_duplicate", literal)
            spans[literal] = {e.unit_id for e in result.apply_result.applied}
        assert spans["count:1"] <= spans["count:2"] <= spans["count:5"]

    def test_the_duplicate_keeps_its_own_header(self) -> None:
        """Glued to the previous line, the copied header would stop being one."""
        _, result = run("discourse.section_duplicate", "count:5")
        after = Document.from_text(result.text, uid="n")
        before = Document.from_text(NOTE, uid="n")
        assert len(after.section_headers()) > len(before.section_headers())


@pytest.mark.parametrize(
    "op_id",
    [
        "render.header_rename",
        "render.list_to_prose",
        "render.break_removal",
        "render.space_delete",
        "discourse.section_duplicate",
    ],
)
def test_a_zero_dose_is_a_no_op(op_id: str) -> None:
    doc, result = run(op_id, "0" if op_id != "discourse.section_duplicate" else "count:0")
    assert result.text == doc.text
    assert result.dose.applied_n == 0


class TestEditScriptsCarryNoNoteText:
    """The property that makes an edit script redistributable when the corpus is not.

    Two operators here produce output containing large amounts of the note —
    `render.list_to_prose` joins a whole list, `discourse.section_duplicate`
    repeats a whole section. Both are implemented so the *edit* carries none of
    it: the join edits only the gaps between items, and the duplication stores a
    `copy_from` offset pair. Written the obvious way instead, each would have
    put note text into `edits.jsonl`.

    `store.MAX_REPLACEMENT_CHARS` refuses that at write time. This asserts it at
    propose time, over every operator, so a new one cannot reintroduce the
    problem and only discover it on a real corpus.
    """

    @pytest.mark.parametrize(
        ("op_id", "severity"),
        [
            ("render.header_rename", "1"),
            ("render.list_to_prose", "1"),
            ("render.break_removal", "1"),
            ("render.space_delete", "1"),
            ("discourse.section_duplicate", "count:5"),
            ("render.bullet_to_prose", "1"),
            ("render.header_delete", "1"),
        ],
    )
    def test_no_replacement_approaches_the_redistribution_limit(
        self, op_id: str, severity: str
    ) -> None:
        from robustehr.store import MAX_REPLACEMENT_CHARS

        _, result = run(op_id, severity)
        for edit in result.apply_result.applied:
            assert len(edit.replacement) <= MAX_REPLACEMENT_CHARS, (
                f"{op_id} put {len(edit.replacement)} characters of the note into an edit"
            )

    def test_a_duplication_stores_offsets_rather_than_the_section(self) -> None:
        _, result = run("discourse.section_duplicate", "count:2")
        applied = result.apply_result.applied
        assert applied
        for edit in applied:
            assert edit.copy_from is not None
            # The only literal text is the separating newline.
            assert edit.replacement in ("", "\n")
