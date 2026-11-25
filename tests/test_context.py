"""Stage 8: the ConText bridge, its offsets, and the states it must keep apart.

The module shipped with a corpus-scale stability gate and no unit tests at all,
which is the wrong way round: a flip rate answers "did the verdict move", and
these answer "does the component mean what its callers assume". Three of the
properties below are load-bearing rather than decorative.

**Absence is not affirmation.** `qualify` drops a span it cannot convert, and
`attributes_for` returns an empty set for a span that was never qualified — the
same empty set an affirmed span returns. Every caller that reads `affirmed`
without checking `is_qualified` will silently report unknown as healthy, which
is how `evidence_touch_affirmed` came to read 100% affirmed in every artifact
the package produced.

**Offsets are into the note as written.** ConText reports its modifier and scope
positions as *token* indices; the package's contract is character offsets. A
conversion error here would put a SEMANTIC operator's edit on the wrong
characters, and nothing downstream could detect it.

**Order is part of the contract.** spaCy populates extensions in document order
but exposes them through structures whose iteration order is not promised. The
abbreviation work already caught scispaCy emitting in address order — eight
processes, eight hashes — so canonical sorting is asserted rather than assumed.
"""

from __future__ import annotations

import pytest

from robustehr.types import Span

context = pytest.importorskip("robustehr.concepts.context", reason="needs the clinical extra")

qualify = context.qualify
Assertion = context.Assertion
AssertionIndex = context.AssertionIndex


#: One cue governing three targets. `tests/fixtures/notes.py` carries the same
#: shape for the corpus-level fixtures; repeated here so this file stands alone.
SHARED_CUE = "Review of Systems:\nDenies chest pain, shortness of breath, and fever."


def span_of(text: str, needle: str) -> Span:
    at = text.index(needle)
    return Span(at, at + len(needle))


class TestQualify:
    def test_a_negation_cue_reaches_every_target_it_scopes(self) -> None:
        """One `Denies` over three findings is three negated mentions, not one."""
        spans = tuple(
            span_of(SHARED_CUE, s) for s in ("chest pain", "shortness of breath", "fever")
        )
        index = qualify(SHARED_CUE, spans)
        assert len(index) == 3
        assert all("negated" in a.attributes for a in index.assertions)

    def test_an_affirmed_span_carries_no_attributes(self) -> None:
        text = "The patient has hypertension, controlled."
        span = span_of(text, "hypertension")
        found = qualify(text, (span,)).at(span)
        assert found is not None
        assert found.attributes == frozenset()
        assert found.affirmed

    def test_empty_input_is_an_empty_index_not_an_error(self) -> None:
        index = qualify("anything at all", ())
        assert len(index) == 0
        assert index.coverage is None, "no request and total failure are different facts"

    def test_results_are_in_canonical_order(self) -> None:
        """Sorted by offset, whatever order the pipeline emitted them in."""
        spans = tuple(
            span_of(SHARED_CUE, s) for s in ("fever", "chest pain", "shortness of breath")
        )
        index = qualify(SHARED_CUE, spans)
        offsets = [(a.span.start, a.span.end) for a in index.assertions]
        assert offsets == sorted(offsets)

    def test_nested_spans_keep_the_widest(self) -> None:
        """spaCy rejects overlapping entities, so the narrower one is dropped.

        Dropping it is a real loss and the point of `coverage`: the caller must
        be able to see that a span it asked about has no verdict.
        """
        text = "No evidence of acute pulmonary embolism."
        wide = span_of(text, "acute pulmonary embolism")
        narrow = span_of(text, "pulmonary embolism")
        index = qualify(text, (wide, narrow))
        assert index.is_qualified(wide)
        assert not index.is_qualified(narrow)
        assert index.requested_n == 2
        assert index.coverage == 0.5


class TestAbsenceIsNotAffirmation:
    """The distinction `evidence_touch_affirmed` was silently collapsing."""

    def test_an_unqualified_span_is_not_reported_as_affirmed(self) -> None:
        text = "The patient has hypertension."
        index = qualify(text, (span_of(text, "hypertension"),))
        elsewhere = Span(0, 3)
        assert not index.is_qualified(elsewhere)
        assert index.attributes_for(elsewhere) == frozenset()
        assert index.at(elsewhere) is None, "the empty set must not be mistaken for a verdict"

    def test_as_map_carries_only_qualified_spans(self) -> None:
        text = "No evidence of acute pulmonary embolism."
        wide = span_of(text, "acute pulmonary embolism")
        narrow = span_of(text, "pulmonary embolism")
        mapping = qualify(text, (wide, narrow)).as_map()
        assert wide in mapping
        assert narrow not in mapping, "membership is the qualified flag downstream"


class TestCues:
    def test_a_cue_span_points_at_the_characters_that_produced_it(self) -> None:
        """Token indices converted back to offsets into the note as written."""
        span = span_of(SHARED_CUE, "chest pain")
        found = qualify(SHARED_CUE, (span,)).at(span)
        assert found is not None
        assert found.cues, "a negated span must name what negated it"
        cue = found.cues[0]
        assert SHARED_CUE[cue.span.start : cue.span.end] == "Denies"
        assert cue.category == "NEGATED_EXISTENCE"
        assert cue.scope.start >= cue.span.end, "a FORWARD cue scopes after itself"

    def test_one_cue_over_three_targets_is_one_unit(self) -> None:
        """The dose denominator counts cues, not the mentions they reach."""
        spans = tuple(
            span_of(SHARED_CUE, s) for s in ("chest pain", "shortness of breath", "fever")
        )
        index = qualify(SHARED_CUE, spans)
        assert len(index) == 3
        assert len(context.cues(index)) == 1
        units = context.cue_units(index)
        assert len(units) == 1
        assert units[0].kind.value == "assertion"

    def test_cues_become_soft_protections(self) -> None:
        """Corrupting `no` reverses meaning, so a cue is withheld by default."""
        span = span_of(SHARED_CUE, "fever")
        protections = context.cue_protections(qualify(SHARED_CUE, (span,)))
        assert len(protections) == 1
        assert protections[0].cls.value == "assertion_cue"
        assert protections[0].strength.value == "soft"


class TestBoundaries:
    """CTX-B: ConText scopes to a sentence, so the segmenter decides reach."""

    def test_supplied_boundaries_stop_a_cue_leaking_into_the_next_item(self) -> None:
        """PyRuSH merges these two list items; our segmenter does not.

        Measured at scale in `assertion_deid_invariance.json`, where supplying
        our boundaries scores 1.0000 accuracy against PyRuSH's 0.6071.
        """
        from robustehr.document import Document

        text = (
            "ASSESSMENT:\n"
            "   1.  No evidence of acute\n"
            "       pneumonia on imaging.\n"
            "   2.  ___ has hypertension,   controlled.\n"
        )
        span = span_of(text, "hypertension")
        doc = Document.from_text(text, uid="t")
        boundaries = tuple(s.span.start for s in doc.sentences.sentences)
        assert "negated" not in qualify(text, (span,), boundaries=boundaries).attributes_for(span)

    def test_a_genuine_negation_survives_supplied_boundaries(self) -> None:
        """The previous test must not be passing by never firing at all."""
        from robustehr.document import Document

        text = "IMPRESSION:\nNo evidence of pulmonary embolism.\n"
        span = span_of(text, "pulmonary embolism")
        doc = Document.from_text(text, uid="t")
        boundaries = tuple(s.span.start for s in doc.sentences.sentences)
        assert "negated" in qualify(text, (span,), boundaries=boundaries).attributes_for(span)


class TestDeterminism:
    def test_two_processes_agree_byte_for_byte(self) -> None:
        """A reproducibility claim needs the pipeline pinned, not just sorted."""
        import json
        import subprocess
        import sys
        import textwrap

        program = (
            textwrap.dedent(
                """
            import json, warnings
            warnings.filterwarnings("ignore")
            from robustehr.concepts.context import qualify
            from robustehr.types import Span
            text = %r
            spans = tuple(
                Span(text.index(s), text.index(s) + len(s))
                for s in ("chest pain", "shortness of breath", "fever")
            )
            index = qualify(text, spans)
            print(json.dumps([
                [a.span.start, a.span.end, sorted(a.attributes),
                 [[c.category, c.literal, c.span.start, c.span.end] for c in a.cues]]
                for a in index.assertions
            ], sort_keys=True))
            """
            )
            % SHARED_CUE
        )

        runs = [
            subprocess.run(
                [sys.executable, "-P", "-c", program], capture_output=True, text=True, check=True
            ).stdout.strip()
            for _ in range(2)
        ]
        assert runs[0] == runs[1]
        assert json.loads(runs[0]), "the test is vacuous if nothing was qualified"


class TestEvidenceInvariant:
    """`Evidence` must not be constructible in the contradictory state."""

    def test_an_assertion_implies_a_verdict(self) -> None:
        from robustehr.concepts.phenotype import Evidence

        item = Evidence(Span(0, 5), "dyspnea", "C1", frozenset({"negated"}))
        assert item.qualified, "carrying an attribute means stage 8 ran"
        assert not item.affirmed

    def test_no_assertion_and_no_verdict_is_not_affirmed(self) -> None:
        from robustehr.concepts.phenotype import Evidence

        item = Evidence(Span(0, 5), "dyspnea", "C1")
        assert not item.qualified
        assert not item.affirmed, "never asked is not the same as asked and clear"


class TestAssertionGold:
    """The frozen fixture gold — a committed resource, so it needs invariants.

    Its labels are an LLM-assisted judgement and cannot be regenerated by
    re-running anything, which is precisely why they are frozen. These tests
    guard the properties a stale or hand-edited file would break.
    """

    def test_every_span_matches_the_fixture_text(self) -> None:
        """Offsets are into the fixture as written; a drift here silently
        re-points every label at the wrong words."""
        from robustehr.resources import load_yaml
        from tests.fixtures.clinical import FORMATS

        gold = load_yaml("assertion_gold.yaml")
        for item in gold["items"]:
            text = FORMATS[item["fixture"]].text
            assert text[item["start"] : item["end"]] == item["surface"], item

    def test_labels_are_drawn_from_the_declared_dimensions(self) -> None:
        from robustehr.resources import load_yaml

        gold = load_yaml("assertion_gold.yaml")
        allowed = set(gold["dimensions"])
        for item in gold["items"]:
            assert set(item["labels"]) <= allowed, item

    def test_counts_in_the_header_match_the_items(self) -> None:
        """The header is what documentation quotes, so it must not drift."""
        from robustehr.resources import load_yaml

        gold = load_yaml("assertion_gold.yaml")
        assert gold["n_items"] == len(gold["items"])
        assert gold["n_affirmed"] == sum(1 for i in gold["items"] if not i["labels"])
        for dimension, count in gold["label_counts"].items():
            assert count == sum(1 for i in gold["items"] if dimension in i["labels"]), dimension

    def test_the_dimensions_are_the_ones_stage_8_reports(self) -> None:
        """A gold labelling something `qualify` never emits cannot be scored."""
        from robustehr.resources import load_yaml

        gold = load_yaml("assertion_gold.yaml")
        assert set(gold["dimensions"]) == set(context._NAMES.values())
