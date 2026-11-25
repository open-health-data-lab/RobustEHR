"""What a run writes down: minimal replacements, parameters, per-token damage."""

from __future__ import annotations

import json

import pytest

from robustehr.cli import main
from robustehr.config import ConfigError, Recipe
from robustehr.document import Document
from robustehr.ops import registry
from robustehr.runner import apply_operator, severity_ladder
from robustehr.store import minimal_edit, read_edits, replay, write_run
from robustehr.types import Edit, ReflowPolicy, Span
from tests.fixtures.clinical import FORMATS

NOTES = tuple(FORMATS.values())[:6]
AIM_NOTE = "examples/aim_note.csv"


def _edit(start: int, end: int, replacement: str, **extra: object) -> Edit:
    return Edit(
        start=start,
        end=end,
        replacement=replacement,
        op_id="input.typo",
        unit_id=f"word:{start}:{end}",
        rank=0,
        reflow=ReflowPolicy.VERBATIM,
        **extra,
    )


class TestMinimalEdit:
    def test_a_retyped_word_keeps_only_the_changed_letter(self):
        source = "known hypertension today"
        trimmed = minimal_edit(_edit(6, 18, "hupertension"), source)
        assert (trimmed.start, trimmed.end, trimmed.replacement) == (7, 8, "u")

    def test_a_deleted_letter_becomes_a_deletion(self):
        trimmed = minimal_edit(_edit(0, 5, "wrds"), "words")
        assert (trimmed.start, trimmed.end, trimmed.replacement) == (1, 2, "")

    def test_a_doubled_letter_stays_a_replacement_not_an_insertion(self):
        trimmed = minimal_edit(_edit(0, 3, "abbc"), "abc")
        assert trimmed.end > trimmed.start
        assert "abc"[: trimmed.start] + trimmed.replacement + "abc"[trimmed.end :] == "abbc"

    def test_a_transposition_keeps_the_two_letters_it_swaps(self):
        trimmed = minimal_edit(_edit(0, 5, "wrods"), "words")
        assert (trimmed.start, trimmed.end, trimmed.replacement) == (1, 3, "ro")

    def test_a_copying_edit_is_left_alone(self):
        edit = _edit(4, 4, "", copy_from=Span(0, 3))
        assert minimal_edit(edit, "abc def") is edit

    def test_a_reflowed_edit_is_left_alone(self):
        edit = Edit(start=0, end=5, replacement="wards", op_id="x", unit_id="u", rank=0)
        assert edit.reflow is not ReflowPolicy.VERBATIM
        assert minimal_edit(edit, "words") is edit


def _typo_run(tmp_path, *, with_texts: bool):
    registry.register_builtins()
    operator = registry.get("input.typo")()
    doses, edits, texts = [], [], {}
    for note in NOTES:
        doc = Document.from_text(note.text, uid=note.id)
        texts[note.id] = note.text
        for severity in severity_ladder("0.30"):
            result = apply_operator(doc, operator, operator.meta, severity, run_id="t")
            doses.append(result.dose)
            edits.append(result.apply_result.applied)
    manifest = write_run(
        tmp_path,
        run_id="t",
        doses=doses,
        edits=edits,
        corpus="fixtures",
        texts=texts if with_texts else None,
    )
    return manifest, texts


class TestEditScriptCarriesNoWords:
    def test_no_typo_replacement_is_longer_than_the_change(self, tmp_path):
        manifest, _ = _typo_run(tmp_path, with_texts=True)
        rows = read_edits(tmp_path)
        assert rows
        assert manifest["replacement_form"] == "minimal_diff"
        assert manifest["cells_stored_as_proposed"] == 0
        assert max(len(r.replacement) for r in rows) == 1
        assert all(r.end - r.start == 1 for r in rows)

    def test_the_trimmed_script_still_replays_byte_for_byte(self, tmp_path):
        _, texts = _typo_run(tmp_path, with_texts=True)
        results = replay(tmp_path, texts)
        assert results
        assert all(r.verified for r in results)

    def test_without_the_notes_nothing_is_trimmed_and_the_manifest_says_so(self, tmp_path):
        manifest, texts = _typo_run(tmp_path, with_texts=False)
        assert manifest["replacement_form"] == "as_proposed"
        assert max(len(r.replacement) for r in read_edits(tmp_path)) > 1
        assert all(r.verified for r in replay(tmp_path, texts))

    def test_the_cli_always_writes_the_minimal_form(self, tmp_path):
        out = tmp_path / "run"
        assert (
            main(
                [
                    "run",
                    "--corpus",
                    AIM_NOTE,
                    "--out",
                    str(out),
                    "--operators",
                    "input.typo",
                    "--severities",
                    "0.50",
                ]
            )
            == 0
        )
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["replacement_form"] == "minimal_diff"
        assert manifest["replacement_chars_by_operator"]["input.typo"] == manifest["edits"]
        assert main(["replay", "--run", str(out), "--corpus", AIM_NOTE]) == 0


def _doses(out):
    return [json.loads(line) for line in (out / "dose.jsonl").read_text().splitlines()]


class TestOperatorParameters:
    def _run(self, tmp_path, *extra):
        out = tmp_path / "run"
        code = main(
            [
                "run",
                "--corpus",
                AIM_NOTE,
                "--out",
                str(out),
                "--operators",
                "input.typo",
                "input.ocr_confusion",
                "--severities",
                "0.50",
                *list(extra),
            ]
        )
        return code, out

    def test_a_parameter_reaches_its_operator_and_only_that_one(self, tmp_path):
        code, out = self._run(tmp_path, "--param", "input.ocr_confusion:max_edits_per_token=1")
        assert code == 0
        by_op = {d["op_id"]: d for d in _doses(out)}
        assert by_op["input.ocr_confusion"]["params"] == "max_edits_per_token=1"
        assert by_op["input.typo"]["params"] == ""
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["operator_params"] == {"input.ocr_confusion": {"max_edits_per_token": 1}}

    def test_the_cap_makes_every_edited_token_a_single_position_edit(self, tmp_path):
        _, capped = self._run(
            tmp_path / "a", "--param", "input.ocr_confusion:max_edits_per_token=1"
        )
        _, free = self._run(tmp_path / "b")
        capped_ocr = next(d for d in _doses(capped) if d["op_id"] == "input.ocr_confusion")
        free_ocr = next(d for d in _doses(free) if d["op_id"] == "input.ocr_confusion")
        assert capped_ocr["tokens_edited"] > 0
        assert capped_ocr["tokens_edited_once"] == capped_ocr["tokens_edited"]
        assert free_ocr["applied_n"] >= free_ocr["tokens_edited"]
        assert free_ocr["tokens_edited_once"] <= free_ocr["tokens_edited"]

    def test_an_unset_parameter_leaves_the_run_unchanged(self, tmp_path):
        _, plain = self._run(tmp_path / "a")
        _, other = self._run(tmp_path / "b", "--param", "input.ocr_confusion:max_edits_per_token=1")
        typo = lambda out: next(d for d in _doses(out) if d["op_id"] == "input.typo")  # noqa: E731
        assert typo(plain)["output_sha256"] == typo(other)["output_sha256"]

    def test_a_flag_and_a_python_bool_seed_alike(self, tmp_path):
        code, out = self._run(tmp_path, "--param", "input.typo:include_mixed=true")
        assert code == 0
        assert next(d for d in _doses(out) if d["op_id"] == "input.typo")["params"] == (
            "include_mixed=True"
        )

    @pytest.mark.parametrize(
        "bad", ["max_edits_per_token=1", "input.ocr_confusion:max_edits_per_token", "nope.op:k=1"]
    )
    def test_a_malformed_or_stray_parameter_is_refused(self, tmp_path, bad, capsys):
        code, _ = self._run(tmp_path, "--param", bad)
        assert code == 2
        assert "parameter" in capsys.readouterr().err

    def test_a_recipe_carries_parameters(self):
        recipe = Recipe.parse(
            {
                "corruptions": ["input.ocr_confusion"],
                "params": {"input.ocr_confusion": {"max_edits_per_token": 1}},
            }
        )
        recipe.check()
        assert recipe.params == {"input.ocr_confusion": {"max_edits_per_token": 1}}
        assert recipe.to_manifest()["params"] == {"input.ocr_confusion": {"max_edits_per_token": 1}}

    def test_a_recipe_refuses_parameters_for_an_operator_it_does_not_run(self):
        recipe = Recipe.parse(
            {"corruptions": ["input.typo"], "params": {"input.ocr_confusion": {"mode": "glyph"}}}
        )
        with pytest.raises(ConfigError, match="does not run"):
            recipe.check()

    def test_a_recipe_refuses_a_float_parameter(self):
        with pytest.raises(ConfigError, match="string, an integer or a boolean"):
            Recipe.parse({"corruptions": ["input.typo"], "params": {"input.typo": {"x": 0.5}}})


class TestReachByTier:
    def test_evidence_is_reported_by_tier_beside_the_totals(self, tmp_path):
        out = tmp_path / "run"
        assert (
            main(
                [
                    "run",
                    "--corpus",
                    AIM_NOTE,
                    "--out",
                    str(out),
                    "--operators",
                    "input.typo",
                    "--severities",
                    "1.00",
                    "--target",
                    "pheno=hypertension",
                ]
            )
            == 0
        )
        (dose,) = _doses(out)
        declared = dose["evidence_n_by_tier"]["hypertension"]
        touched = dose["evidence_touch_by_tier"]["hypertension"]
        assert sum(declared.values()) >= dose["evidence_n"]["hypertension"] > 0
        assert set(touched) <= set(declared)
        assert all(touched[tier] <= declared[tier] for tier in touched)
        assert sum(touched.values()) == dose["evidence_touch"]["hypertension"]

    def test_an_agnostic_run_reports_no_tiers(self, tmp_path):
        out = tmp_path / "run"
        assert (
            main(["run", "--corpus", AIM_NOTE, "--out", str(out), "--operators", "input.typo"]) == 0
        )
        assert all(d["evidence_n_by_tier"] == {} for d in _doses(out))


class TestEmptyAimIsAnnounced:
    def test_a_concept_aim_with_no_index_warns(self, tmp_path, capsys):
        out = tmp_path / "run"
        code = main(
            [
                "run",
                "--corpus",
                AIM_NOTE,
                "--out",
                str(out),
                "--operators",
                "input.typo",
                "--target",
                "cat=medication",
                "--index",
                str(tmp_path / "no_index_here"),
                "--lexicon",
                str(tmp_path / "no_lexicon_here"),
            ]
        )
        err = capsys.readouterr().err
        assert code == 0
        assert "admitted no unit for input.typo" in err
        assert "no QuickUMLS index was found" in err

    def test_an_unaimed_run_stays_quiet(self, tmp_path, capsys):
        out = tmp_path / "run"
        args = ["run", "--corpus", AIM_NOTE, "--out", str(out), "--operators", "input.typo"]
        assert main(args) == 0
        assert "warning" not in capsys.readouterr().err
