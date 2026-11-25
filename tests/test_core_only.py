"""What must work with only the core install.

The README promises that `describe` needs no terminology and that a reader
without a UMLS licence can reproduce the structural half of Table 1. That claim
was false: `robustehr describe --markdown` crashed with `ModuleNotFoundError:
medspacy` on a core install, because `metrics.describe._assertion_cues` guarded
the *module* import of `concepts.context` while `medspacy` is imported lazily
inside the pipeline builder. The module imported fine, the guard never fired,
and the error surfaced from the call.

CI cannot catch this by omission, because the suite needs the clinical extra to
exercise the SEMANTIC operators at all. So absence is simulated here instead:
`importlib.util.find_spec` is patched to report medspaCy missing, which is the
one signal `medspacy_available` consults.
"""

from __future__ import annotations

import importlib.util

import pytest

from robustehr.document import Document

NOTE = (
    "CHIEF COMPLAINT: Chest pain.\n"
    "\n"
    "HISTORY OF PRESENT ILLNESS:\n"
    "Mr. ___ is a 64M with HTN and DM2 who presents with chest pain.\n"
    "He denies fever. Metoprolol 25 mg PO BID.\n"
    "\n"
    "DISCHARGE DIAGNOSES:\n"
    "1. Hypertension\n"
    "2. Type 2 diabetes\n"
)


@pytest.fixture
def no_terminology(monkeypatch):
    """Make the terminology extra look absent, however it is really installed."""
    real = importlib.util.find_spec

    def absent(name, *args, **kwargs):
        if name == "quickumls" or name.startswith("quickumls."):
            return None
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", absent)


@pytest.fixture
def no_medspacy(monkeypatch):
    """Make the clinical extra look absent, however it is really installed."""
    real = importlib.util.find_spec

    def absent(name, *args, **kwargs):
        if name == "medspacy" or name.startswith("medspacy."):
            return None
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", absent)


class TestAssertionLayerDegrades:
    def test_cues_in_returns_nothing_rather_than_raising(self, no_medspacy) -> None:
        from robustehr.concepts.context import cues_in

        assert cues_in(NOTE) == ()

    def test_qualify_returns_an_empty_index(self, no_medspacy) -> None:
        from robustehr.concepts.context import qualify
        from robustehr.types import Span

        index = qualify(NOTE, (Span(start=0, end=4),))
        assert not index.assertions
        assert index.requested_n == 1

    def test_availability_is_reported_honestly(self, no_medspacy) -> None:
        from robustehr.concepts.context import medspacy_available

        assert medspacy_available() is False


class TestTableOneNeedsNoTerminology:
    """The README's central accessibility claim, as an executable check."""

    def test_measure_note_survives_without_the_clinical_extra(self, no_medspacy) -> None:
        from robustehr.metrics.describe import measure_note

        row = measure_note(Document.from_text(NOTE, uid="n1"), None, None, None, None, None)
        assert row is not None

    def test_the_structural_levels_are_still_populated(self, no_medspacy) -> None:
        """Degrading must not mean measuring nothing."""
        from robustehr.metrics.describe import assemble, measure_note

        rows = [measure_note(Document.from_text(NOTE, uid="n1"), None, None, None, None, None)]
        table = assemble(rows, {})
        for level in ("document", "section", "header", "sentence", "token", "character"):
            assert level in table.levels, f"{level} missing from Table 1 on a core install"

    def test_the_assertion_level_reports_zero_not_absence(self, no_medspacy) -> None:
        """A measured zero and an unavailable instrument must not look alike.

        The assertion level is the one Table 1 row that needs the clinical extra.
        Without it the cue count is zero, which is honest; what would not be
        honest is the row vanishing, because a reader cannot tell a corpus with
        no cues from a corpus nobody looked at.
        """
        from robustehr.metrics.describe import measure_note

        row = measure_note(Document.from_text(NOTE, uid="n1"), None, None, None, None, None)
        assert row.cues == {}


class TestConceptLayerDegrades:
    """An index present without the extra must fail early and say what to do.

    This crashed as `ModuleNotFoundError: quickumls` from inside `annotate`,
    several frames below the command the user typed, because the CLI gated on
    whether the index *directory* existed and never on whether the package was
    importable. Two different failures, only one of them about the user's data.
    """

    def test_availability_is_reported_honestly(self, no_terminology) -> None:
        from robustehr.concepts.matcher import quickumls_available

        assert quickumls_available() is False

    def test_constructing_a_matcher_names_the_fix(self, no_terminology, tmp_path) -> None:
        from robustehr.concepts.matcher import ConceptMatcher

        index = tmp_path / "quickumls_index"
        index.mkdir()
        with pytest.raises(ModuleNotFoundError) as exc:
            ConceptMatcher(index)
        assert "robustehr[terminology]" in str(exc.value)

    def test_a_missing_index_still_names_its_own_fix(self, tmp_path) -> None:
        """The two failures must stay distinguishable."""
        from robustehr.concepts.matcher import ConceptMatcher, quickumls_available

        if not quickumls_available():
            pytest.skip("terminology extra not installed; the other error wins")
        with pytest.raises(FileNotFoundError) as exc:
            ConceptMatcher(tmp_path / "absent")
        assert "quickumls.install" in str(exc.value)
