"""The methodology folder quotes numbers; they must match the artifacts.

Written after a stale token-coverage figure survived in two documents because
the drift test asserted only one field. Submission prose is exactly where a
wrong number is most expensive, so every quantitative claim gets checked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from robustehr.categories import default_tuis, load_categories
from robustehr.lexical import general_english
from robustehr.lexicon import load_morphology

METHODOLOGY = Path("validation/methodology")
MEASUREMENTS = Path("validation/measurements")


def text(name: str) -> str:
    return (METHODOLOGY / name).read_text(encoding="utf-8")


def all_prose() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(METHODOLOGY.glob("*.md")))


def test_every_index_entry_exists():
    """A broken link in submission material is worse than a missing file."""
    index = text("README.md")
    for target in re.findall(r"\]\((\d\d-[a-z-]+)\.md\)", index):
        assert (METHODOLOGY / f"{target}.md").exists(), target


def test_lexicon_sizes_match_the_built_artifacts():
    prose = all_prose()
    assert f"{len(general_english()):,}" in prose, "general-English size is stale"
    assert str(len(load_morphology().closed_class)) in prose, "function-word count is stale"


def test_clinical_vocabulary_size_matches():
    manifest = MEASUREMENTS / "clinical_lexicon.manifest.json"
    if not manifest.exists():
        pytest.skip("clinical vocabulary not built")
    tokens = json.loads(manifest.read_text(encoding="utf-8"))["tokens"]
    assert f"{tokens:,}" in all_prose(), "clinical vocabulary size is stale"


def test_fallback_figures_match_the_measurement():
    path = MEASUREMENTS / "lexicon_fallback.json"
    if not path.exists():
        pytest.skip("fallback measurement not run")
    recorded = json.loads(path.read_text(encoding="utf-8"))
    prose = all_prose()
    for field, places in (
        ("precision", 3),
        ("recall", 3),
        ("f1", 3),
        ("reference_token_coverage", 1),
        ("fallback_token_coverage", 1),
    ):
        value = recorded[field]
        rendered = f"{value:.{places}f}" if places == 3 else f"{value * 100:.1f}%"
        assert rendered in prose, f"{field} ({rendered}) is stale in methodology/"


def test_category_count_matches():
    prose = text("05-semantic-categories.md")
    names = set(load_categories())
    for name in names:
        assert name in prose, f"category {name} is undocumented"
    # Removed categories must stay documented as removed, not silently vanish.
    for removed in ("chemical", "organism", "physiology"):
        assert removed in prose
        assert removed not in names


def test_no_stale_66_percent_anywhere():
    """The specific figure that drifted once. Cheap to assert, cheap to keep."""
    assert "66.0%" not in all_prose()
    assert "66% of content tokens" not in all_prose()


# -- the validation run -----------------------------------------------------

ABLATION = MEASUREMENTS / "snomed_ablation.json"


def ablation() -> dict:
    if not ABLATION.exists():
        pytest.skip("SNOMED ablation not run")
    return json.loads(ABLATION.read_text(encoding="utf-8"))


def test_ablation_figures_match_the_prose():
    """The validation numbers appear in three documents; all must agree."""
    recorded = ablation()
    prose = all_prose() + (Path("validation/measurements/README.md")).read_text(encoding="utf-8")
    rows = {(r["rung"], r["category"]): r for r in recorded["rungs"]}
    for category in ("symptom", "anatomy", "disease", "disorder"):
        for rung in ("L0", "L1"):
            value = rows[(rung, category)]["targeting_precision"]
            assert f"{value:.3f}" in prose, f"{rung}/{category} ({value:.3f}) is stale"


def test_the_gold_coverage_caveat_travels_with_the_numbers():
    """Absolute precision is a lower bound; the reason must not get separated."""
    recorded = ablation()
    coverage = recorded["gold_token_coverage"]["fraction"]
    assert 0.15 < coverage < 0.45, coverage
    assert "lower bound" in recorded["caveat"].lower()
    prose = all_prose() + (Path("validation/measurements/README.md")).read_text(encoding="utf-8")
    assert f"{coverage * 100:.1f}%" in prose


def test_the_t033_decision_is_recorded_as_measured():
    """Excluding T033 must remain what the gold standard supports.

    If a future change flips this, the exclusion in semantic_categories.yaml is
    no longer justified and must be revisited rather than silently kept.
    """
    recorded = ablation()
    rows = {(r["rung"], r["category"]): r for r in recorded["rungs"]}
    without = rows[("L1", "clinical_any")]
    with_t033 = rows[("L1F", "clinical_any")]
    assert without["targeting_precision"] > with_t033["targeting_precision"]
    assert without["f1"] > with_t033["f1"]
    # And the code still reflects the decision.
    assert "T033" not in default_tuis()


def test_concept_matching_helps_the_specific_categories():
    """The headline claim of the L0-to-L1 rung, asserted so it cannot rot."""
    recorded = ablation()
    rows = {(r["rung"], r["category"]): r for r in recorded["rungs"]}
    for category in ("symptom", "anatomy", "disease", "procedure"):
        l0 = rows[("L0", category)]["targeting_precision"]
        l1 = rows[("L1", category)]["targeting_precision"]
        assert l1 > l0, f"{category}: L1 {l1} no longer beats L0 {l0}"
