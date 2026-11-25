"""Structural breaks: the boundaries `render.break_removal` is dosed over.

The detector's whole job is to separate a boundary from a hard-wrap
continuation. Get that wrong in either direction and the operator is a different
corruption than it claims: too permissive and it re-flows wrapped prose, too
strict and it never fires on the note style it exists for.
"""

from __future__ import annotations

from robustehr.document import Document
from robustehr.segment.breaks import break_counts, detect_breaks
from robustehr.segment.lines import split_lines

NOTE = """Chief Complaint:
Chest pain

History of Present Illness:
The patient is a 64 year old man with a long history of hypertension
who presents with substernal chest pressure radiating to the left arm.

Medications:
1. Lisinopril 10 mg PO daily
2. Metoprolol 25 mg PO BID

Labs:
WBC-6.9   RBC-4.46   Hgb-12.8
Na-140    K-4.1      Cl-104

Assessment and Plan:
Likely unstable angina.
"""


def doc() -> Document:
    return Document.from_text(NOTE, uid="n1")


class TestWhatIsABreak:
    def test_a_hard_wrap_continuation_is_not_a_break(self) -> None:
        """The load-bearing case, and the reason `wraps_into_next` is reused.

        The HPI runs across two lines mid-sentence. Treating that newline as
        structure would make `render.break_removal` a re-wrapping operator on
        every hard-wrapped note in MIMIC — which is all of them.
        """
        text = doc().text
        for brk in doc().breaks:
            before = text[max(0, brk.span.start - 25) : brk.span.start]
            assert not before.endswith("history of hypertension"), (
                "a wrapped sentence was counted as a structural break"
            )

    def test_a_header_boundary_is_a_break(self) -> None:
        pairs = {(b.before_line, b.after_line) for b in doc().breaks}
        assert (0, 1) in pairs, "the boundary under a standalone header is structure"

    def test_blank_line_separated_paragraphs_are_breaks(self) -> None:
        assert any(b.is_paragraph for b in doc().breaks)
        counts = break_counts(doc().breaks)
        assert counts["paragraph"] + counts["line"] == counts["n"]


class TestExclusions:
    """Boundaries that belong to another operator's denominator.

    Counting them here would let one severity be delivered twice under two
    names — a list joined by `render.list_to_prose` and again by
    `render.break_removal`.
    """

    def test_list_interiors_are_excluded(self) -> None:
        d = doc()
        item_lines = {item.line_idx for block in d.lists for item in block.items}
        for brk in d.breaks:
            assert not (brk.before_line in item_lines and brk.after_line in item_lines), (
                f"break {brk.before_line}->{brk.after_line} is interior to a list"
            )

    def test_lab_block_interiors_are_excluded(self) -> None:
        d = doc()
        for block in d.aligned:
            lines = set(block.lines)
            for brk in d.breaks:
                assert not (brk.before_line in lines and brk.after_line in lines), (
                    "a break was counted inside an aligned block"
                )

    def test_the_boundary_ENDING_a_block_is_kept(self) -> None:
        """A list is still separated from what follows it, and losing that matters."""
        d = doc()
        last_item = max(item.line_idx for block in d.lists for item in block.items)
        assert any(b.before_line == last_item for b in d.breaks)


class TestSpan:
    def test_the_span_is_only_whitespace(self) -> None:
        """The replacement is a single space, so the span must hold nothing else."""
        text = doc().text
        for brk in doc().breaks:
            assert text[brk.span.start : brk.span.end].strip() == ""

    def test_replacing_every_break_with_a_space_merges_no_words(self) -> None:
        d = doc()
        out = []
        cursor = 0
        for brk in d.breaks:
            out.append(d.text[cursor : brk.span.start])
            out.append(" ")
            cursor = brk.span.end
        out.append(d.text[cursor:])
        flat = "".join(out)
        assert "armMedications" not in flat
        assert "arm. Medications:" in flat


class TestDegenerate:
    def test_empty_and_single_line_documents_have_no_breaks(self) -> None:
        assert detect_breaks("", split_lines("")) == ()
        assert detect_breaks("one line", split_lines("one line")) == ()

    def test_unwrapped_prose_breaks_at_every_line(self) -> None:
        """A note that is not hard-wrapped has real structure at every newline.

        `wrap_width` returns a large value for such a note, so nothing looks
        like a continuation — which is correct, not a degenerate case.
        """
        text = "Short one.\nShort two.\nShort three.\n"
        breaks = detect_breaks(text, split_lines(text))
        assert len(breaks) == 2
