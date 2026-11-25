"""Document assembly: layer consistency, provenance, degenerate inputs."""

from __future__ import annotations

import unicodedata

import pytest

from robustehr.document import Document, UnicodeFormError
from robustehr.segment.deid import DeidScheme
from robustehr.segment.patterns import SEGMENTER_VERSION
from robustehr.types import Span
from tests.fixtures.clinical import FORMATS


class TestConstruction:
    def test_text_is_never_mutated(self) -> None:
        text = FORMATS["mimic_discharge"].text
        assert Document.from_text(text, uid="t").text == text

    def test_sha256_identifies_the_note(self) -> None:
        a = Document.from_text("same text", uid="one")
        b = Document.from_text("same text", uid="two")
        c = Document.from_text("other text", uid="three")
        assert a.sha256 == b.sha256 != c.sha256

    def test_scheme_can_be_pinned(self) -> None:
        text = FORMATS["mimic_discharge"].text
        assert Document.from_text(text, uid="t").deid.scheme is DeidScheme.UNDERSCORE_RUN
        pinned = Document.from_text(text, uid="t", deid_scheme=DeidScheme.NONE)
        assert pinned.deid.count == 0

    def test_non_nfc_input_is_refused_not_normalized(self) -> None:
        """Normalizing would itself be a perturbation.

        It changes offsets and character counts, applied before any operator ran
        and recorded in no dose record. The caller has to decide.
        """
        decomposed = unicodedata.normalize("NFD", "œdème périphérique")
        assert decomposed != unicodedata.normalize("NFC", decomposed)
        with pytest.raises(UnicodeFormError, match="not NFC"):
            Document.from_text(decomposed, uid="t")

    def test_nfc_input_is_accepted(self) -> None:
        text = FORMATS["french_consultation"].text
        assert Document.from_text(text, uid="t").text == text


class TestProvenance:
    def test_carries_segmenter_and_resource_versions(self) -> None:
        """A segmenter change or a resource swap is a breaking change to every
        previously reported denominator, so both travel with the document."""
        provenance = Document.from_text("Allergies:\nNone\n", uid="n1").provenance()
        assert provenance["note_uid"] == "n1"
        assert provenance["segmenter_version"] == SEGMENTER_VERSION
        assert provenance["deid_scheme"] == "underscore_run" or "deid_scheme" in provenance
        digests = [v for k, v in provenance.items() if k.startswith("resource:")]
        assert digests and all(len(d) == 64 for d in digests)

    def test_unit_counts_cover_every_denominator(self) -> None:
        counts = Document.from_text(FORMATS["complex_discharge"].text, uid="t").unit_counts()
        assert counts["chars"] > 5000
        for key in (
            "tokens",
            "content_tokens",
            "sentences",
            "prose_sentences",
            "section_headers",
            "sections",
            "list_items",
            "deid_placeholders",
        ):
            assert counts[key] > 0, key


@pytest.mark.parametrize("name", sorted(FORMATS))
class TestLayerConsistency:
    def test_every_layer_stays_within_the_document(self, name: str) -> None:
        doc = Document.from_text(FORMATS[name].text, uid=name)
        limit = len(doc.text)
        spans: list[Span] = [
            *(line.span for line in doc.lines.lines),
            *(t.span for t in doc.tokens),
            *(s.span for s in doc.sentences.sentences),
            *(s.full for s in doc.sections),
            *(h.span for h in doc.headers),
            *(p.span for p in doc.deid.placeholders),
            *(b.span for b in doc.lists),
            *(b.span for b in doc.aligned),
        ]
        assert spans
        for span in spans:
            assert 0 <= span.start <= span.end <= limit

    def test_sections_tile_the_document(self, name: str) -> None:
        """Every character belongs to some section.

        A gap silently excludes that text from every section-scoped operator and
        makes the section denominator disagree with the character count.
        """
        doc = Document.from_text(FORMATS[name].text, uid=name)
        covered = bytearray(len(doc.text))
        for section in doc.sections:
            for i in range(section.full.start, section.full.end):
                covered[i] = 1
        uncovered = [i for i, flag in enumerate(covered) if not flag]
        assert not uncovered, f"{name}: {len(uncovered)} characters in no section"

    def test_top_level_sections_start_and_end_the_document(self, name: str) -> None:
        doc = Document.from_text(FORMATS[name].text, uid=name)
        top = sorted((s for s in doc.sections if s.depth == 0), key=lambda s: s.full.start)
        assert top
        assert top[0].full.start == 0
        assert top[-1].full.end == len(doc.text)

    def test_section_lookup_agrees_with_section_spans(self, name: str) -> None:
        doc = Document.from_text(FORMATS[name].text, uid=name)
        for probe in range(0, len(doc.text), max(len(doc.text) // 20, 1)):
            found = doc.section_at(probe)
            assert found is not None
            assert found.full.start <= probe < found.full.end

    def test_sentence_lookup_agrees_with_sentence_spans(self, name: str) -> None:
        doc = Document.from_text(FORMATS[name].text, uid=name)
        for sentence in doc.sentences.sentences:
            assert doc.sentence_at(sentence.span.start) is sentence


class TestDegenerateInputs:
    @pytest.mark.parametrize("text", ["", "\n", "   ", "a", "___", "|", "\t", "\n\n\n"])
    def test_construction_survives(self, text: str) -> None:
        doc = Document.from_text(text, uid="t")
        assert doc.text == text
        assert "".join(t.surface(text) for t in doc.tokens) == text
        assert doc.unit_counts()["chars"] == len(text)

    def test_empty_document(self) -> None:
        doc = Document.from_text("", uid="t")
        assert doc.is_empty
        assert len(doc.sentences) == 0
        assert doc.sections == ()
        assert doc.section_at(0) is None
