"""The benchmark history: tracking matcher performance across iterations."""

from __future__ import annotations

import json

import pytest

from robustehr.eval.benchmark import (
    DEFAULTS,
    HISTORY,
    LEADERBOARD,
    QUICKUMLS_DEFAULT_SEMTYPES,
    VALIDATION_CRITICAL,
    Entry,
    History,
)


def entry(label="x", **overrides) -> Entry:
    config = {**DEFAULTS, **overrides}
    return Entry(
        label=label,
        config=config,
        challenge_iou=overrides.pop("challenge_iou", 0.1),
        span_iou=0.2,
        category_recall={"disease": 0.7, "anatomy": 0.6},
        category_precision={"disease": 0.5, "anatomy": 0.3},
        notes_scored=25,
        gold_spans=1000,
    )


def test_default_config_inherits_quickumls_validation():
    assert entry().inherits_quickumls_validation


@pytest.mark.parametrize("field", VALIDATION_CRITICAL)
def test_changing_a_matching_parameter_forfeits_inheritance(field):
    """QuickUMLS's published evaluation covers its defaults, not our tuning.

    An entry that changes the algorithm owes its own evaluation, and the flag is
    what stops that being forgotten between a sweep and a manuscript.
    """
    altered = {field: 0.99 if isinstance(DEFAULTS[field], float) else "changed"}
    assert not entry(**altered).inherits_quickumls_validation


def test_window_is_not_validation_critical():
    """It changes how far a match may span, not how similarity is computed."""
    assert "window" not in VALIDATION_CRITICAL
    assert entry(window=9).inherits_quickumls_validation


def test_mean_category_recall_ignores_missing_categories():
    e = Entry(
        label="x",
        config=DEFAULTS,
        challenge_iou=0.1,
        span_iou=0.2,
        category_recall={"disease": 0.8, "anatomy": None},
        category_precision={},
        notes_scored=1,
        gold_spans=1,
    )
    assert e.mean_category_recall == 0.8


def test_history_round_trips(tmp_path):
    path = tmp_path / "history.json"
    history = History()
    history.add(entry("first"), stamp="2026-01-01")
    history.add(entry("second"), stamp="2026-01-02")
    history.save(path)
    reloaded = History.load(path)
    assert [e.label for e in reloaded.entries] == ["first", "second"]
    assert reloaded.entries[0].recorded == "2026-01-01"


def test_history_is_append_only(tmp_path):
    """The trajectory is the point; overwriting it would lose the comparison."""
    path = tmp_path / "history.json"
    history = History()
    history.add(entry("first"), stamp="2026-01-01")
    history.save(path)
    again = History.load(path)
    again.add(entry("second"), stamp="2026-01-02")
    again.save(path)
    assert len(History.load(path).entries) == 2


def test_best_selects_on_the_named_metric(tmp_path):
    history = History()
    history.add(entry("low", challenge_iou=0.05), stamp="2026-01-01")
    history.add(entry("high", challenge_iou=0.2), stamp="2026-01-01")
    assert history.best("challenge_iou").label == "high"


def test_best_is_none_on_an_empty_history():
    assert History().best() is None


def test_leaderboard_context_travels_with_the_history(tmp_path):
    """A score without the published comparison invites the wrong reading."""
    path = tmp_path / "history.json"
    History().save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["leaderboard"] == LEADERBOARD
    assert "validation" in payload["validation_note"].lower()
    assert payload["metric_challenge"] and payload["metric_category"]


def test_the_committed_history_is_readable():
    if not HISTORY.exists():
        pytest.skip("no benchmark history recorded yet")
    history = History.load(HISTORY)
    assert history.entries
    for e in history.entries:
        assert e.label and e.recorded
        assert e.challenge_iou is None or 0.0 <= e.challenge_iou <= 1.0


def test_both_metrics_are_tracked_because_they_can_diverge():
    """The reason a history exists rather than a single best number.

    A change improving the leaderboard score while degrading category recall is
    a regression for this package, and only recording both makes it visible.
    """
    if not HISTORY.exists():
        pytest.skip("no benchmark history recorded yet")
    history = History.load(HISTORY)
    assert all(e.category_recall for e in history.entries)
    assert any(e.challenge_iou is not None for e in history.entries)


# -- the asymmetry in inherited validation ----------------------------------


def test_narrowing_the_semtype_filter_inherits_validation():
    """A post-match filter: the output stays a subset of what was validated."""
    narrow = sorted(QUICKUMLS_DEFAULT_SEMTYPES)[:5]
    assert entry(accepted_semtypes=narrow).inherits_quickumls_validation


def test_widening_the_semtype_filter_forfeits_it():
    """Spans their evaluation never scored, so it owes its own."""
    assert not entry(accepted_semtypes=["T025", "T047"]).inherits_quickumls_validation


def test_a_summarised_filter_is_read_conservatively():
    """The history records a summary string; the set is not recoverable."""
    assert not entry(accepted_semtypes="robustehr:36").inherits_quickumls_validation


def test_the_quickumls_default_is_still_inheriting():
    assert entry(accepted_semtypes="quickumls_default").inherits_quickumls_validation
    assert entry(accepted_semtypes=None).inherits_quickumls_validation
