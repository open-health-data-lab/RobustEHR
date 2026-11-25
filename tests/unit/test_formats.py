"""Format-agnostic invariants across note types, vendors, schemes and languages.

The tests in ``test_segment.py`` and ``test_headers.py`` check behaviour against
properties measured on one corpus. These check that the *structural guarantees*
hold regardless of corpus — because a robustness tool that is itself brittle
across institutions is worthless, and because tuning a segmenter against a single
source is the easiest way to build exactly that.

An invariant here failing on one format is a bug in the segmenter, not a quirk
of the note.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from robustehr.segment.deid import DeidScheme, detect_scheme, index_deid, scheme_from_name
from robustehr.segment.headers import SECTION_KINDS, HeaderGrammar, detect_headers
from robustehr.segment.lines import split_lines
from robustehr.segment.tokens import TokenKind, tokenize
from robustehr.segment.wrap import build_reflow_view, wrap_width, wraps_into_next
from tests.fixtures.clinical import (
    FORMATS,
    LANGUAGES,
    SETTINGS,
    SPECIALTIES,
    STRUCTURES,
    SyntheticNote,
    notes_where,
)

ALL = sorted(FORMATS)


def note(name: str) -> SyntheticNote:
    return FORMATS[name]


@pytest.mark.parametrize("name", ALL)
class TestUniversalInvariants:
    """Guarantees that must hold for every note, in every format."""

    def test_lines_reconstruct_the_document(self, name: str) -> None:
        text = note(name).text
        lines = split_lines(text)
        assert "".join(line.full.surface(text) for line in lines.lines) == text

    def test_tokens_reconstruct_the_document(self, name: str) -> None:
        text = note(name).text
        assert "".join(t.surface(text) for t in tokenize(text)) == text

    def test_token_offsets_are_contiguous_and_complete(self, name: str) -> None:
        text = note(name).text
        tokens = tokenize(text).tokens
        assert tokens[0].span.start == 0
        assert tokens[-1].span.end == len(text)
        for prev, nxt in pairwise(tokens):
            assert prev.span.end == nxt.span.start

    def test_reflow_offsets_stay_in_range(self, name: str) -> None:
        text = note(name).text
        view = build_reflow_view(text, split_lines(text))
        for pos in range(len(view.text)):
            assert 0 <= view.to_raw(pos) <= len(text)

    def test_reflow_content_maps_back_to_the_same_character(self, name: str) -> None:
        text = note(name).text
        view = build_reflow_view(text, split_lines(text))
        for pos, ch in enumerate(view.text):
            if ch in " \n\t":
                continue  # may be a synthesized join
            assert text[view.to_raw(pos)] == ch

    def test_header_detection_terminates_and_stays_in_bounds(self, name: str) -> None:
        text = note(name).text
        for header in detect_headers(text, split_lines(text)):
            assert header.label.surface(text) == header.raw_name
            marker = header.marker.surface(text)
            if header.grammar is HeaderGrammar.MARKDOWN:
                assert set(marker) == {"#"}
                assert header.span.start == header.marker.start
            else:
                assert marker == ":"
                assert header.span.surface(text).endswith(":")
            assert header.span.contains(header.label)
            if header.value is not None:
                assert header.value.end <= len(text)


@pytest.mark.parametrize("name", ALL)
class TestDeidGeneralization:
    def test_declared_scheme_is_detected(self, name: str) -> None:
        """Auto-detection must recover the convention the note actually uses."""
        fixture = note(name)
        assert detect_scheme(fixture.text) is scheme_from_name(fixture.deid_scheme)

    def test_masks_are_atomic_tokens(self, name: str) -> None:
        """Whatever the convention, a mask must never be split.

        Fragmenting one lets a character operator mangle part of it, producing
        PHI-shaped text that was never in the record.
        """
        fixture = note(name)
        text = fixture.text
        index = index_deid(text)
        by_span = {t.span: t for t in tokenize(text)}
        for placeholder in index.placeholders:
            assert placeholder.span in by_span, placeholder.surface(text)
            assert by_span[placeholder.span].kind is TokenKind.PLACEHOLDER

    def test_typed_schemes_retain_their_label(self, name: str) -> None:
        fixture = note(name)
        index = index_deid(fixture.text)
        if not index.scheme.is_typed:
            assert all(p.type_label is None for p in index.placeholders)
            return
        # A typed mask says what was removed; that information is what makes
        # typed -> untyped restyling provably lossy.
        assert any(p.type_label for p in index.placeholders)


class TestCorpusBreadth:
    """The corpus must not silently narrow back toward one house style.

    Every one of these axes has already caught a bug that a MIMIC-only fixture
    set would have shipped, so they are asserted rather than assumed.
    """

    def test_settings_span_the_care_continuum(self) -> None:
        assert set(SETTINGS) >= {
            "inpatient",
            "outpatient",
            "emergency",
            "critical_care",
            "procedural",
            "community",
            "virtual",
        }

    def test_specialties_are_broad(self) -> None:
        # Vocabulary, measurement conventions and note habits differ sharply by
        # specialty; a handful of medicine notes is not a corpus.
        assert len(SPECIALTIES) >= 20

    def test_unstructured_notes_are_represented(self) -> None:
        """Plenty of clinicians use no template at all, outpatient especially."""
        assert set(STRUCTURES) >= {
            "templated",
            "problem_oriented",
            "semi_structured",
            "free_text",
            "dictated",
            "telegraphic",
            "letter",
            "tabular",
        }
        free = notes_where(structure="free_text")
        assert len(free) >= 4
        assert any(n.setting == "outpatient" for n in free)

    def test_notes_without_any_header_exist(self) -> None:
        headerless = [
            n
            for n in FORMATS.values()
            if not detect_headers(n.text, split_lines(n.text), kinds=SECTION_KINDS)
        ]
        assert len(headerless) >= 3, "no header-free notes: section logic is untested"

    def test_languages_and_scripts_vary(self) -> None:
        assert len(LANGUAGES) >= 4
        assert any(lang.startswith("fr") for lang in LANGUAGES)

    def test_note_lengths_span_orders_of_magnitude(self) -> None:
        lengths = sorted(len(n.text) for n in FORMATS.values())
        assert lengths[0] < 400, "no very short notes: degenerate denominators untested"
        assert lengths[-1] > 5000, "no long notes: real discharge summaries reach 33,000 chars"


class TestDeidSchemes:
    def test_every_declared_scheme_is_exercised(self) -> None:
        covered = {n.deid_scheme for n in FORMATS.values()}
        assert covered >= {
            "underscore_run",
            "bracket_star",
            "angle_tag",
            "square_tag",
            "xxx_run",
            "asterisk_run",
            "curly_tag",
            "none",
        }

    def test_unmasked_notes_are_not_given_a_scheme(self) -> None:
        """Guessing a scheme where there is none would invent protected spans."""
        assert detect_scheme(FORMATS["ward_nursing"].text) is DeidScheme.NONE
        assert index_deid(FORMATS["ward_nursing"].text).count == 0

    def test_bracket_star_is_not_read_as_a_square_tag(self) -> None:
        text = FORMATS["i2b2_discharge"].text
        counts = index_deid(text).scheme_counts
        assert counts["bracket_star"] > 0
        assert counts["square_tag"] == 0

    def test_type_labels_are_captured(self) -> None:
        index = index_deid(FORMATS["nhs_letter"].text)
        labels = {p.type_label for p in index.placeholders}
        assert "GP_NAME" in labels and "NHS_NUMBER" in labels

    def test_checkbox_residue_is_not_a_mask(self) -> None:
        """Templated forms are full of `[X]` and `[ ]`.

        Reading those as PHI masks would protect checkboxes while leaving the
        note's actual masks exposed — and it silently flipped the detected
        scheme on a real fixture before this was caught.
        """
        text = "Fetal movement:  [X] normal  [ ] decreased\nEDD: XX/XX/XXXX\n"
        assert detect_scheme(text) is DeidScheme.XXX_RUN
        assert index_deid(text).scheme_counts["square_tag"] == 0

    def test_pinning_a_scheme_overrides_detection(self) -> None:
        text = FORMATS["mimic_discharge"].text
        assert index_deid(text, DeidScheme.ANGLE_TAG).count == 0
        assert index_deid(text, DeidScheme.UNDERSCORE_RUN).count > 0


class TestWrapGeneralization:
    @pytest.mark.parametrize("name", [n for n in ALL if not FORMATS[n].hard_wrapped])
    def test_unwrapped_notes_produce_no_continuations(self, name: str) -> None:
        """An unwrapped export must not be silently re-flowed.

        Treating its long lines as wrapped would join independent statements and
        change the sentence denominator for every downstream operator.
        """
        text = note(name).text
        lines = split_lines(text)
        width = wrap_width(lines)
        joined = sum(1 for i in range(len(lines)) if wraps_into_next(text, lines, i, width))
        assert joined == 0, f"{name}: {joined} spurious continuations"

    @pytest.mark.parametrize("name", [n for n in ALL if FORMATS[n].hard_wrapped])
    def test_wrapped_notes_are_actually_joined(self, name: str) -> None:
        text = note(name).text
        view = build_reflow_view(text, split_lines(text))
        assert view.text.count("\n") < text.count("\n")


class TestLanguageGeneralization:
    def test_accented_text_survives_tokenization(self) -> None:
        """Diacritics have zero targets in MIMIC-IV but are load-bearing in
        French records, which is why the diacritic operator is kept with
        measured eligibility rather than deleted."""
        text = FORMATS["french_consultation"].text
        assert "œdème" in text and "Numéro" in text
        assert "".join(t.surface(text) for t in tokenize(text)) == text

    def test_french_section_labels_are_detected_as_headers(self) -> None:
        text = FORMATS["french_consultation"].text
        raw = {h.raw_name for h in detect_headers(text, split_lines(text))}
        assert "Motif de consultation" in raw
        assert "Examen physique" in raw

    def test_british_spellings_tokenize_normally(self) -> None:
        text = FORMATS["nhs_letter"].text
        lowered = {t.lower for t in tokenize(text)}
        assert {"oedema", "haemoglobin", "anaemia", "tachypnoeic"} <= lowered


class TestStructuralGeneralization:
    def test_tabs_are_preserved(self) -> None:
        """MIMIC-IV contains zero tabs; other exports are tab-delimited."""
        for name in ("epic_progress", "tabular_export"):
            text = FORMATS[name].text
            assert "\t" in text
            assert "".join(t.surface(text) for t in tokenize(text)) == text

    def test_pipe_tables_do_not_break_header_detection(self) -> None:
        text = FORMATS["tabular_export"].text
        raw = {h.raw_name for h in detect_headers(text, split_lines(text))}
        assert not any(name.startswith("|") for name in raw)

    def test_markdown_headings_do_not_masquerade_as_colon_headers(self) -> None:
        text = FORMATS["markdown_clinic"].text
        raw = {h.raw_name for h in detect_headers(text, split_lines(text))}
        assert "# Rheumatology Follow-up" not in raw

    def test_telegraphic_note_yields_no_false_headers(self) -> None:
        """Timestamped nursing entries contain no section structure at all."""
        text = FORMATS["ward_nursing"].text
        assert detect_headers(text, split_lines(text)) == ()


class TestDegenerateInputs:
    @pytest.mark.parametrize("text", ["", "\n", "   ", "\n\n\n", "a", "___", "|", "\t"])
    def test_segmentation_survives_degenerate_documents(self, text: str) -> None:
        lines = split_lines(text)
        assert "".join(t.surface(text) for t in tokenize(text)) == text
        view = build_reflow_view(text, lines)
        assert all(0 <= view.to_raw(i) <= len(text) for i in range(len(view.text)))
        assert detect_headers(text, lines) == ()
