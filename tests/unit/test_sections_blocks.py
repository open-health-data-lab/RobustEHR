"""Section assembly, list blocks and aligned value blocks."""

from __future__ import annotations

import pytest

from robustehr.segment.blocks import (
    BlockStyle,
    ListStyle,
    detect_aligned_blocks,
    detect_lists,
    list_style_counts,
)
from robustehr.segment.headers import SECTION_KINDS, detect_headers
from robustehr.segment.lines import split_lines
from robustehr.segment.sections import (
    PREAMBLE_ID,
    build_sections,
    section_at,
    sections_named,
)
from tests.fixtures.clinical import FORMATS
from tests.fixtures.notes import FIXTURES


def sections_of(text: str):  # type: ignore[no-untyped-def]
    lines = split_lines(text)
    return build_sections(text, detect_headers(text, lines, kinds=SECTION_KINDS))


class TestSectionAssembly:
    def test_preamble_is_kept(self) -> None:
        """Text before the first header is a real section.

        Dropping it would silently exclude letter salutations and metadata
        blocks from every section-scoped operator.
        """
        text = "Some opening text.\nAllergies:\nNone\n"
        sections = sections_of(text)
        assert sections[0].canonical_id == PREAMBLE_ID
        assert sections[0].body_text(text) == "Some opening text.\n"

    def test_headerless_note_is_one_section(self) -> None:
        text = FORMATS["ward_nursing"].text
        sections = sections_of(text)
        assert len(sections) == 1
        assert sections[0].canonical_id == PREAMBLE_ID
        assert sections[0].full == sections[0].body
        assert sections[0].text(text) == text

    def test_standalone_header_owns_until_the_next(self) -> None:
        text = "Allergies:\nPenicillin\nShellfish\nSocial History:\nNonsmoker\n"
        allergies = sections_named(sections_of(text), "allergies")[0]
        assert allergies.body_text(text) == "\nPenicillin\nShellfish\n"

    def test_inline_header_owns_only_its_line(self) -> None:
        """Otherwise `Service: MEDICINE` would swallow the rest of the note."""
        text = "Service: MEDICINE\nAllergies:\nNone\n"
        service = sections_named(sections_of(text), "service")[0]
        assert service.text(text) == "Service: MEDICINE\n"

    def test_last_section_runs_to_end_of_document(self) -> None:
        text = "Allergies:\nNone\nSocial History:\nNonsmoker, no alcohol.\n"
        last = sections_of(text)[-1]
        assert last.full.end == len(text)

    def test_sections_do_not_exceed_the_document(self) -> None:
        for name, fixture in FORMATS.items():
            for section in sections_of(fixture.text):
                assert section.full.end <= len(fixture.text), name
                assert section.body.start >= section.full.start, name

    def test_markdown_depth_nests(self) -> None:
        """`# Title` contains `## Section`, so the title must not be closed by it."""
        text = FORMATS["markdown_clinic"].text
        sections = sections_of(text)
        title = next(s for s in sections if s.header and s.header.raw_name.startswith("Rheum"))
        assert title.depth == 0
        assert "Assessment and Plan" in title.text(text)

    def test_section_at_returns_the_deepest_match(self) -> None:
        text = FORMATS["markdown_clinic"].text
        sections = sections_of(text)
        target = text.index("no active synovitis")
        found = section_at(sections, target)
        assert found is not None
        assert found.header is not None
        assert found.header.raw_name == "Objective"


class TestListDetection:
    def test_numbered_items(self) -> None:
        text = "Past Medical History:\n1. Hypertension\n2. Diabetes\n3. CKD\n"
        blocks = detect_lists(text, split_lines(text))
        assert len(blocks) == 1
        assert blocks[0].style is ListStyle.NUMBERED
        assert len(blocks[0]) == 3

    def test_style_change_starts_a_new_block(self) -> None:
        """A numbered medication list and a dashed instruction list are two
        units, which is what keeps per-style eligibility honest."""
        text = "1. First\n2. Second\n- Third\n- Fourth\n"
        blocks = detect_lists(text, split_lines(text))
        assert [b.style for b in blocks] == [ListStyle.NUMBERED, ListStyle.DASH]

    def test_hash_problem_list(self) -> None:
        text = "#Pneumonia: improving\n#Diabetes: stable\n"
        blocks = detect_lists(text, split_lines(text))
        # `#Pneumonia` has no space after the marker, so it is prose, not a list.
        assert blocks == ()

    def test_hash_problem_list_with_space(self) -> None:
        text = "# Pneumonia, improving\n# Diabetes, stable\n"
        blocks = detect_lists(text, split_lines(text))
        assert len(blocks) == 1 and blocks[0].style is ListStyle.HASH

    def test_deid_as_list_number_is_not_an_item(self) -> None:
        """`___. Cholecystectomy` — de-identification consumed the number."""
        text = FIXTURES["deid_as_list_number"]
        blocks = detect_lists(text, split_lines(text))
        items = [i for b in blocks for i in b.items]
        assert len(items) == 2  # only the surviving "1." and "2."

    def test_style_counts_are_reported_separately(self) -> None:
        text = "1. A\n2. B\n- C\n"
        counts = list_style_counts(detect_lists(text, split_lines(text)))
        assert counts["numbered"] == 2
        assert counts["dash"] == 1
        assert counts["asterisk"] == 0

    def test_marker_and_content_spans_are_exact(self) -> None:
        text = "1. Hypertension\n"
        item = detect_lists(text, split_lines(text))[0].items[0]
        assert item.marker.surface(text) == "1."
        assert item.content.surface(text) == " Hypertension"


class TestAlignedBlocks:
    def test_self_labelling_lab_line(self) -> None:
        """`WBC-6.9 RBC-4.46` — each value carries its own label."""
        text = "WBC-6.9 RBC-4.46 Hgb-12.8 Hct-38.2\n"
        blocks = detect_aligned_blocks(text, split_lines(text))
        assert len(blocks) == 1
        assert blocks[0].style is BlockStyle.ALIGNED_SPACES
        assert blocks[0].self_labelling

    def test_position_dependent_columns(self) -> None:
        """Values held only by position; re-spacing destroys the association."""
        text = "Date       Temp       BP         HR\n01/01      37.0       142/88     78\n"
        blocks = detect_aligned_blocks(text, split_lines(text))
        assert blocks and not blocks[0].self_labelling

    def test_one_unsafe_line_makes_the_block_unsafe(self) -> None:
        text = "Name       Value      Units\nWBC-6.9 RBC-4.46 Hgb-12.8\n"
        blocks = detect_aligned_blocks(text, split_lines(text))
        assert not blocks[0].self_labelling

    def test_pipe_and_tab_styles(self) -> None:
        text = FORMATS["tabular_export"].text
        styles = {b.style for b in detect_aligned_blocks(text, split_lines(text))}
        assert BlockStyle.PIPE_TABLE in styles
        assert BlockStyle.TAB_DELIMITED in styles

    def test_prose_is_not_an_aligned_block(self) -> None:
        text = "The patient denies chest pain and reports mild dyspnea.\n"
        assert detect_aligned_blocks(text, split_lines(text)) == ()

    def test_column_gaps_are_counted_for_the_dose_denominator(self) -> None:
        text = "Na-138     K-4.1      Cl-102\n"
        block = detect_aligned_blocks(text, split_lines(text))[0]
        assert block.column_gaps == 2


@pytest.mark.parametrize("name", sorted(FORMATS))
class TestBlockGeneralization:
    def test_detection_stays_in_bounds(self, name: str) -> None:
        text = FORMATS[name].text
        lines = split_lines(text)
        for block in detect_lists(text, lines):
            assert block.span.end <= len(text)
            for item in block.items:
                assert item.marker.end <= item.content.start
        for block in detect_aligned_blocks(text, lines):
            assert block.span.end <= len(text)
            assert block.lines
