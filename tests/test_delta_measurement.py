"""Measuring a corrupted corpus with the same instrument as the clean one.

The whole value of a before/after table is that both sides are comparable. One
detector here is **document-adaptive** and quietly broke that:
:func:`~robustehr.segment.wrap.wrap_width` is the p90 of a note's own line
lengths, so a corruption that joins lines widens the margin,
:func:`~robustehr.segment.wrap.wraps_into_next` then accepts fewer lines as
hard-wrap continuations, and genuine continuations are reclassified as breaks.

The consequence was not subtle. Over 1,388 MIMIC-IV notes, removing 30% of the
structural breaks reported **+5.0% more breaks**, and severity 1.0 reported
-52.9% where the truth was -95.2%. Every severity of that arm was wrong in a
direction that reads as a finding rather than a fault.

Asserted on the shipped synthetic notes rather than the restricted corpus: the
artifact is a property of hard-wrapped clinical prose with *varying* line
lengths, which several of the fixtures have. A fixture with uniform line lengths
cannot reproduce it — the p90 has nowhere to move — which is itself worth
knowing if this file ever needs a new note.
"""

from __future__ import annotations

import pytest

from robustehr.document import Document
from robustehr.metrics.describe import level_characteristics
from robustehr.ops import registry
from robustehr.ops.base import Scope
from robustehr.runner import apply_operator, severity_ladder
from robustehr.segment.wrap import wrap_width
from tests.fixtures.clinical import FORMATS

#: Fixtures whose wrap column moves enough for the artifact to appear. Named
#: rather than discovered so a fixture edit that removes the property fails here
#: instead of silently making the test vacuous.
ADAPTIVE = ("cardiology_dictated", "psychiatry_clinic", "operative_note", "long_term_care")


def corrupt(text: str, severity: str) -> Document:
    registry.register_builtins()
    op = registry.get("render.break_removal")()
    doc = Document.from_text(text, uid="n")
    result = apply_operator(
        doc, op, op.meta, severity_ladder(severity)[0], scope=Scope(), salt="rep0"
    )
    return Document.from_text(result.text, uid="n")


def breaks(doc: Document, width: int | None = None) -> int:
    return int(level_characteristics(doc, wrap_width=width)["break"]["n"])


@pytest.mark.parametrize("name", ADAPTIVE)
class TestTheInstrumentMustNotMoveWithTheCorruption:
    def test_joining_lines_widens_the_measured_wrap_column(self, name: str) -> None:
        """The mechanism, so the fix has something concrete to point at."""
        text = FORMATS[name].text
        clean = Document.from_text(text, uid="n")
        assert wrap_width(corrupt(text, "1").lines) > wrap_width(clean.lines)

    def test_unpinned_measurement_understates_or_inverts_the_drop(self, name: str) -> None:
        """The bug itself, kept so nobody removes the pin as redundant.

        Adaptive measurement reports at least as many breaks as pinned
        measurement, and on these fixtures often *more than the clean note had*.
        """
        text = FORMATS[name].text
        clean = Document.from_text(text, uid="n")
        width = wrap_width(clean.lines)
        corrupted = corrupt(text, "0.30")
        assert breaks(corrupted) > breaks(corrupted, width), (
            f"{name}: the adaptive artifact no longer reproduces, so the "
            "pinned assertions below are testing nothing"
        )

    def test_pinning_the_clean_width_makes_the_delta_negative(self, name: str) -> None:
        text = FORMATS[name].text
        clean = Document.from_text(text, uid="n")
        width = wrap_width(clean.lines)
        before, after = breaks(clean, width), breaks(corrupt(text, "0.30"), width)
        assert after < before, f"{name}: {before} -> {after}; removing breaks must reduce them"

    def test_the_drop_is_monotone_in_severity(self, name: str) -> None:
        text = FORMATS[name].text
        clean = Document.from_text(text, uid="n")
        width = wrap_width(clean.lines)
        counts = [breaks(corrupt(text, s), width) for s in ("0.30", "0.50", "1")]
        assert counts == sorted(counts, reverse=True), f"{name}: {counts}"
        assert counts[-1] < breaks(clean, width)

    def test_pinning_a_note_to_its_own_width_changes_nothing(self, name: str) -> None:
        """The parameter must not alter the baseline it is compared against."""
        clean = Document.from_text(FORMATS[name].text, uid="n")
        assert breaks(clean, wrap_width(clean.lines)) == breaks(clean)


def test_only_the_break_level_is_adaptive() -> None:
    """`break` is the one detector calibrated on the note it measures.

    If a second level ever becomes width-sensitive this fails, which is the
    point: the delta table's premise is that both sides share one instrument.
    """
    doc = Document.from_text(FORMATS["cardiology_dictated"].text, uid="n")
    plain = level_characteristics(doc)
    pinned = level_characteristics(doc, wrap_width=wrap_width(doc.lines) * 3)
    assert {k for k in plain if plain[k] != pinned.get(k)} == {"break"}
