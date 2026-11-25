"""Concept-level matching, and the swap into the Target interface.

Every test needing the index skips without it: the index is built from licensed
UMLS content and cannot travel with the package, so CI must stay green without
one. What does *not* skip is the fallback behaviour, which is what most
installations will actually run.
"""

from __future__ import annotations

import pytest

from robustehr.concepts.matcher import (
    DEFAULT_INDEX,
    ConceptMatcher,
    MatcherConfig,
    Mention,
    MentionIndex,
    default_semtypes,
    index_present,
    trim_function_affixes,
)
from robustehr.document import Document
from robustehr.target import Categories, TargetContext, Uncategorized
from robustehr.types import Span

pytestmark = pytest.mark.filterwarnings("ignore")


def index_available() -> bool:
    return index_present(DEFAULT_INDEX)


needs_index = pytest.mark.skipif(not index_available(), reason="no QuickUMLS index built")


# -- pure, no index needed --------------------------------------------------


def test_config_canon_pins_everything_that_changes_matching():
    """QuickUMLS's published validation is inherited only while these hold."""
    canon = MatcherConfig().canon()
    for part in ("jaccard", "0.7", "3", "5", "score"):
        assert part in canon
    assert MatcherConfig(threshold=0.8).canon() != canon
    assert MatcherConfig(min_match_length=4).canon() != canon


def test_mention_index_resolves_by_span():
    mentions = MentionIndex(
        (
            Mention(Span(0, 10), "C0008031", frozenset({"T184"}), 1.0, "chest pain"),
            Mention(Span(20, 28), "C0043031", frozenset({"T121"}), 1.0, "warfarin"),
        )
    )
    assert mentions.semantic_types(Span(0, 5)) == frozenset({"T184"})
    assert mentions.categories(Span(20, 28)) == frozenset({"medication"})
    assert mentions.semantic_types(Span(12, 18)) == frozenset()


def test_exactness_is_distinguished():
    exact = Mention(Span(0, 8), "C1", frozenset({"T121"}), 1.0)
    fuzzy = Mention(Span(0, 8), "C1", frozenset({"T121"}), 0.8)
    assert exact.is_exact
    assert not fuzzy.is_exact


def test_context_reports_which_resolution_was_used():
    doc = Document.from_text("Chest pain.\n", uid="t")
    assert TargetContext(doc=doc).resolution == "token"
    assert TargetContext(doc=doc, mentions=MentionIndex(())).resolution == "concept"


def test_a_missing_index_says_how_to_build_one():
    with pytest.raises(FileNotFoundError, match=r"quickumls\.install"):
        ConceptMatcher(DEFAULT_INDEX / "does-not-exist")


def test_an_empty_mention_index_still_counts_as_measured():
    """A document with no concepts was still looked at.

    Otherwise `Uncategorized` would refuse to admit anything in a note that
    genuinely contains no clinical content, which is the opposite of correct.
    """
    doc = Document.from_text("The the the.\n", uid="t")
    ctx = TargetContext(doc=doc, mentions=MentionIndex(()))
    assert ctx.is_measured(Span(0, 3))
    assert Uncategorized().admits(Span(0, 3), ctx)


# -- with a built index -----------------------------------------------------


@needs_index
def test_multiword_terms_match_as_one_mention():
    """The point of matching spans rather than tokens."""
    matcher = ConceptMatcher()
    text = "Patient reports chest pain and atrial fibrillation."
    surfaces = {m.surface.lower() for m in matcher.annotate(text).mentions}
    assert "chest pain" in surfaces
    assert "atrial fibrillation" in surfaces


@needs_index
def test_annotation_is_deterministic():
    """Feeds a reproducibility claim, so iteration order cannot be trusted."""
    matcher = ConceptMatcher()
    text = "Started warfarin for atrial fibrillation with dyspnea on exertion."
    first = matcher.annotate(text).mentions
    second = matcher.annotate(text).mentions
    assert first == second
    assert list(first) == sorted(first, key=lambda m: (m.span.start, m.span.end, m.cui))


@needs_index
def test_concept_resolution_changes_what_a_target_selects():
    """L0 and L1 differ, which is why the ablation is worth running."""
    matcher = ConceptMatcher()
    doc = Document.from_text("Started warfarin for atrial fibrillation.\n", uid="t")
    ctx = TargetContext(doc=doc, mentions=matcher.annotate(doc.text))
    warfarin = next(t for t in doc.tokens if t.lower == "warfarin")
    assert Categories("medication").admits(warfarin.span, ctx)
    assert not Categories("anatomy").admits(warfarin.span, ctx)


@needs_index
def test_mentions_carry_a_cui_which_is_what_phenotypes_need():
    matcher = ConceptMatcher()
    mentions = matcher.annotate("Patient has atrial fibrillation.").mentions
    assert mentions
    assert all(m.cui.startswith("C") for m in mentions)


# -- semantic-type filter alignment -----------------------------------------
#
# These read config rather than match anything, but they construct a
# `ConceptMatcher`, and construction validates the index path. They sat under the
# "no index needed" heading and failed on any machine without one.


@needs_index
def test_the_quickumls_filter_is_aligned_with_our_categories_by_default():
    """Two filters that disagree lose terms silently.

    QuickUMLS's 27 default semantic types are not RobustEHR's. `wbc` resolves to
    T025 Cell, which belongs to `anatomy` but not to their defaults, so it was
    discarded before any category logic could see it.
    """
    assert "T025" in default_semtypes()
    assert ConceptMatcher(config=None).config.accepted_semtypes == default_semtypes()


@needs_index
def test_alignment_can_be_declined():
    matcher = ConceptMatcher(align_semtypes=False)
    assert matcher.config.accepted_semtypes is None


@needs_index
def test_an_explicit_filter_is_not_overridden():
    config = MatcherConfig(accepted_semtypes=frozenset({"T047"}))
    assert ConceptMatcher(config=config).config.accepted_semtypes == frozenset({"T047"})


def test_the_filter_reaches_categories_excluded_from_the_default():
    """`finding` is out of `clinical_any` but still reachable by name.

    The matcher has to return T033 or targeting `finding` would select nothing.
    """
    assert "T033" in default_semtypes()


def test_config_canon_records_the_filter():
    """It changes what matches, so it belongs in the seed material."""
    assert "semtypes=default" in MatcherConfig().canon()
    assert "semtypes=2" in MatcherConfig(accepted_semtypes=frozenset({"T047", "T033"})).canon()


@needs_index
def test_alignment_recovers_terms_quickumls_defaults_drop():
    text = "Labs: Hgb 12.2 WBC 8.4 Plt 250"
    aligned = {m.surface.lower() for m in ConceptMatcher().annotate(text).mentions}
    unaligned = {
        m.surface.lower() for m in ConceptMatcher(align_semtypes=False).annotate(text).mentions
    }
    assert "wbc" in aligned
    assert "wbc" not in unaligned


class TestAffixTrimming:
    """Recovering the span when longest-match runs one word too far.

    Preferring the longest match is what stops ``shortness of breath``
    fragmenting into ``breath`` — the single largest concept-error class at 52%.
    The cost is over-extension, and trimming closed-class affixes is the
    correction, because no UMLS concept begins or ends with a conjunction.
    """

    def test_leading_function_word_is_dropped(self) -> None:
        text = "and vitamin D deficiency"
        assert trim_function_affixes(Span(0, len(text)), text) == Span(4, len(text))

    def test_trailing_function_word_is_dropped(self) -> None:
        text = "chest pain and"
        assert trim_function_affixes(Span(0, len(text)), text) == Span(0, 10)

    def test_interior_function_words_survive(self) -> None:
        """``of`` is why the longer match was worth preferring in the first place."""
        text = "shortness of breath"
        assert trim_function_affixes(Span(0, len(text)), text) == Span(0, len(text))

    def test_all_function_words_yields_nothing(self) -> None:
        text = "and the"
        assert trim_function_affixes(Span(0, len(text)), text) is None

    def test_punctuation_only_yields_nothing(self) -> None:
        assert trim_function_affixes(Span(0, 3), "---") is None

    def test_offsets_are_absolute_not_span_relative(self) -> None:
        """The span is a window into the note, not a string of its own."""
        text = "Patient reports and chest pain today"
        assert trim_function_affixes(Span(16, 30), text) == Span(20, 30)

    def test_trimming_is_recorded_in_the_canon(self) -> None:
        """A configuration change that alters output must change the manifest."""
        assert MatcherConfig().canon() != MatcherConfig(trim_affixes=True).canon()


class TestPreferredCuis:
    """Breaking similarity ties toward a vocabulary, without becoming a filter.

    The safety property is that it is a *tie-break*: at equal similarity the
    choice was arbitrary anyway (alphabetical by CUI), so an informed rule cannot
    cost accuracy. Anything stronger would be fitting to the gold.
    """

    @staticmethod
    def _rank_with(preferred: frozenset[str] | None):
        matcher = ConceptMatcher.__new__(ConceptMatcher)
        matcher.config = MatcherConfig(preferred_cuis=preferred)
        return matcher._rank

    def test_similarity_outranks_preference(self) -> None:
        """A preferred concept must never displace a strictly better match."""
        rank = self._rank_with(frozenset({"C_WORSE"}))
        worse = {"cui": "C_WORSE", "similarity": 0.8}
        better = {"cui": "C_BETTER", "similarity": 1.0}
        assert sorted([worse, better], key=rank)[0] is better

    def test_preference_breaks_a_tie(self) -> None:
        rank = self._rank_with(frozenset({"C_ZZZ"}))
        preferred = {"cui": "C_ZZZ", "similarity": 1.0}
        alphabetical = {"cui": "C_AAA", "similarity": 1.0}
        assert sorted([alphabetical, preferred], key=rank)[0] is preferred

    def test_cui_still_breaks_remaining_ties(self) -> None:
        """Determinism does not depend on the preference set being decisive."""
        rank = self._rank_with(frozenset({"C_AAA", "C_BBB"}))
        a = {"cui": "C_AAA", "similarity": 1.0}
        b = {"cui": "C_BBB", "similarity": 1.0}
        assert sorted([b, a], key=rank)[0] is a

    def test_no_preference_is_alphabetical(self) -> None:
        rank = self._rank_with(None)
        a = {"cui": "C_AAA", "similarity": 1.0}
        b = {"cui": "C_BBB", "similarity": 1.0}
        assert sorted([b, a], key=rank)[0] is a

    def test_preference_size_is_recorded_in_the_canon(self) -> None:
        assert MatcherConfig().canon() != MatcherConfig(preferred_cuis=frozenset({"C1"})).canon()
