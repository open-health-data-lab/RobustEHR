"""A vetting verdict that nothing consumes is decorative. These make it load-bearing.

The failure these guard against actually happened: the medication vetting pass
correctly dropped *ciprofloxacin* from `clostridioides_difficile` — a drug that
causes the condition — and the concept stayed in every built set anyway, because
`build()` never read the verdict (see `facets.load_vetting`). The same hole was
then found again on the proposed facet: 1,204 LLM-proposed concepts entered the
shipped sets wholesale while their vetting pass didn't exist yet.

Two tiers, matching `test_phenotype_links.py`: resource-only tests always run;
tests that expand a real set need the licensed crosswalk and skip without it.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

from robustehr.concepts.facets import load_proposals, load_vetting
from robustehr.resources import load_yaml

ISA = Path("data/umls_isa_mth.json")
CROSSWALK = Path("data/snomed_el")

needs_terminology = pytest.mark.skipif(
    not (ISA.exists() and (CROSSWALK / "cui_snomed.json").exists()),
    reason="no local UMLS crosswalk or isa cache",
)

VETTING_RAW = (load_yaml("phenotype_vetting.yaml") or {}).get("phenotypes", {})
PROPOSED_ROWS = sorted(n for n, f in VETTING_RAW.items() if "proposed" in f)


def _script(name: str):
    """Import a validation script by path — `validation/` is not a package."""
    path = Path("validation") / "phenotype" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built():
    from robustehr.concepts import hierarchy
    from robustehr.concepts.phenotype import build, load_definitions, load_maps

    isa = hierarchy.load(ISA)
    code_to_cuis, cui_to_codes = load_maps(CROSSWALK)
    names = sorted(load_definitions())
    return {p.name: p for p in build(names, isa, code_to_cuis, cui_to_codes)}


class TestVerdictsGateTheSets:
    def test_the_proposed_facet_has_been_vetted(self) -> None:
        """Every phenotype with proposals must carry a proposed vetting row.

        Without this, the proposed facet unions wholesale — the exact
        "recorded and not applied" hole the medication facet fell into.
        """
        assert PROPOSED_ROWS, "no proposed vetting rows: run phenotype_vet.py --facet proposed"
        missing = sorted(set(load_proposals()) - set(PROPOSED_ROWS))
        assert not missing, f"proposals without a vetting row: {missing}"

    @pytest.mark.parametrize("name", PROPOSED_ROWS)
    def test_kept_is_a_subset_of_the_candidates(self, name: str) -> None:
        candidates = frozenset(c for cuis in load_proposals().get(name, {}).values() for c in cuis)
        kept = load_vetting()[name]["proposed"]
        assert kept <= candidates, f"{name}: kept concepts that were never proposed"

    @needs_terminology
    def test_a_dropped_proposed_cui_is_absent_from_the_built_set(self, built) -> None:
        """The anti-decorative test: at least one drop exists, and none survive."""
        checked = 0
        for name in PROPOSED_ROWS:
            reviewed = VETTING_RAW[name]["proposed"].get("reviewed", {})
            dropped = {c for c, v in reviewed.items() if v["verdict"] == "drop"}
            # A dropped CUI may still enter through ANOTHER facet — the disorder
            # closure, MED-RT, or the one-hop evidence closure — and that is not
            # a gate failure. Only a proposal with no other route must die.
            other_routes = built[name].concept_cuis - _proposed_only(name, built)
            for cui in dropped - other_routes:
                assert cui not in built[name].concept_cuis, (name, cui)
                checked += 1
        assert checked, "no dropped proposal was checkable; the gate is untested"

    @needs_terminology
    def test_ciprofloxacin_is_not_in_clostridioides_difficile(self, built) -> None:
        """The acid test from validation/methodology/14: a drug that CAUSES the phenotype."""
        assert "C0008809" not in built["clostridioides_difficile"].concept_cuis


def _proposed_only(name: str, built) -> frozenset[str]:
    """CUIs reachable only via the proposed facet, i.e. gated solely by vetting.

    It used to compute this as everything the facets added over a bare disorder
    build, which is every facet rather than the proposed one, so the caller's
    "other routes" collapsed to the disorder closure alone. A CUI dropped as a
    proposal while kept by the one-hop closure then read as a gate failure.

    Nothing exercised that until a phenotype had a concept in both states, and
    then it failed on a set that was correct. `Phenotype.facet_cuis` records
    membership per facet, so the question can now be asked directly instead of
    inferred from a difference.
    """
    facets = built[name].facet_cuis
    if not facets:  # facet artifacts absent; nothing was added by any of them
        return frozenset()
    others = frozenset().union(
        *(members for facet, members in facets.items() if facet != "proposed")
    )
    return frozenset(facets.get("proposed", frozenset())) - others


class TestRuntimeSetsArtifact:
    """`phenotype_runtime_sets.json` is the denominator of every coverage
    number, and it went stale once already: it recorded the pre-facet sizes
    (hfpef 8 instead of 117) for a week after `build()` changed."""

    ARTIFACT = Path("validation/measurements/phenotype_runtime_sets.json")

    @needs_terminology
    def test_the_published_sizes_match_a_fresh_build(self, built) -> None:
        import json

        if not self.ARTIFACT.exists():
            pytest.skip("runtime sets artifact not generated")
        sizes = json.loads(self.ARTIFACT.read_text(encoding="utf-8"))["runtime_set_size"]
        fresh = {name: len(p.concept_cuis) for name, p in built.items()}
        assert sizes == fresh, (
            "stale artifact: rerun validation/phenotype/scripts/phenotype_runtime_sets.py"
        )


class TestReviewIngestRoundTrip:
    def test_a_marked_tsv_updates_verdicts_and_kept(self, tmp_path: Path) -> None:
        ingest = _script("phenotype_review_ingest")
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        rows = [
            # A human overrides a model drop, drops a model keep, leaves one be.
            {
                "cui": "C1",
                "term": "alpha",
                "facet": "symptom",
                "source": "proposed",
                "provenance": "grounded",
                "llm_verdict": "drop",
                "llm_reason": "x",
                "keep": "y",
                "reviewer_note": "clinically core",
            },
            {
                "cui": "C2",
                "term": "beta",
                "facet": "symptom",
                "source": "proposed",
                "provenance": "grounded",
                "llm_verdict": "keep",
                "llm_reason": "x",
                "keep": "n",
                "reviewer_note": "nonspecific",
            },
            {
                "cui": "C3",
                "term": "gamma",
                "facet": "symptom",
                "source": "proposed",
                "provenance": "grounded",
                "llm_verdict": "keep",
                "llm_reason": "x",
                "keep": "",
                "reviewer_note": "",
            },
        ]
        with (reviews / "demo.tsv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
        out = tmp_path / "vetting.yaml"
        import yaml

        out.write_text(
            yaml.safe_dump(
                {
                    "vetted_by": "llm",
                    "phenotypes": {
                        "demo": {
                            "proposed": {
                                "kept": ["C2", "C3"],
                                "reviewed": {
                                    "C1": {"verdict": "drop", "reason": "x"},
                                    "C2": {"verdict": "keep", "reason": "x"},
                                    "C3": {"verdict": "keep", "reason": "x"},
                                },
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        rc = ingest.main(["--reviews", str(reviews), "--reviewer", "test", "--out", str(out)])
        assert rc == 0
        after = yaml.safe_load(out.read_text(encoding="utf-8"))
        row = after["phenotypes"]["demo"]["proposed"]
        assert sorted(row["kept"]) == ["C1", "C3"]
        assert row["reviewed"]["C1"]["reviewer"] == "test"
        assert "reviewer" not in row["reviewed"]["C3"], "an untouched verdict stays the model's"
        assert after["phenotypes"]["demo"]["clinician"] == {"decided": 2, "overrides": 2}
        assert after["vetted_by"] == "llm+clinician"
