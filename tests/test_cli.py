"""The command line, exercised end to end on synthetic notes."""

from __future__ import annotations

import csv
import json

import pytest

from robustehr.cli import build_parser, main
from tests.fixtures.clinical import FORMATS

#: Deterministic order — dict order follows the declaration order of the
#: fixture modules, so the CLI corpus is the same on every run.
NOTES = tuple(FORMATS.values())


@pytest.fixture
def corpus(tmp_path):
    """A CSV corpus drawn from the multi-format synthetic notes."""
    path = tmp_path / "corpus.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["note_id", "text"])
        for note in NOTES[:12]:
            writer.writerow([note.id, note.text])
    return path


@pytest.fixture
def lexicon_artifact(tmp_path):
    path = tmp_path / "clinical_tokens.txt"
    path.write_text(
        "\n".join(["aspirin", "pneumonia", "fever", "warfarin", "lisinopril"]),
        encoding="utf-8",
    )
    path.with_suffix(".manifest.json").write_text(
        json.dumps({"umls_release": "2026AA"}), encoding="utf-8"
    )
    return path


def test_parser_builds():
    assert build_parser().prog == "robustehr"


def test_taxonomy_lists_operators(capsys):
    assert main(["taxonomy"]) == 0
    out = capsys.readouterr().out
    assert "control.identity" in out
    assert "render.deid_restyle" in out


def test_taxonomy_describe_emits_the_full_entry(capsys):
    assert main(["taxonomy", "--describe", "render.deid_restyle"]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["id"] == "render.deid_restyle"
    assert entry["contract"] == "invariant_by_construction"


def test_taxonomy_describe_rejects_unknown_operator(capsys):
    assert main(["taxonomy", "--describe", "render.nonexistent"]) == 2
    assert "unknown operator" in capsys.readouterr().err


def test_applicability_reports_per_unit_counts(corpus, capsys):
    assert main(["applicability", "--corpus", str(corpus)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["notes"] == 12
    kinds = {row["unit_kind"] for row in report["units"]}
    assert {"lines", "tokens", "sentences", "sections"} <= kinds
    for row in report["units"]:
        assert 0.0 <= row["notes_with_any"] <= 1.0
        assert row["p25"] <= row["median"] <= row["p75"]


def test_applicability_writes_to_a_file(corpus, tmp_path):
    out = tmp_path / "nested" / "applicability.json"
    assert main(["applicability", "--corpus", str(corpus), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["notes"] == 12


def test_classify_records_which_method_decided(corpus, lexicon_artifact, capsys):
    assert (
        main(
            [
                "concepts",
                "classify",
                "--corpus",
                str(corpus),
                "--lexicon",
                str(lexicon_artifact),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["lexicon_source"] == "umls-2026AA"
    assert set(report["evidence"]) <= {
        "terminology",
        "closed_class",
        "morphology",
        "structure",
        "none",
    }


def test_classify_falls_back_and_says_so(corpus, tmp_path, capsys):
    """A missing artifact must degrade visibly, not silently."""
    assert (
        main(
            [
                "concepts",
                "classify",
                "--corpus",
                str(corpus),
                "--lexicon",
                str(tmp_path / "absent.txt"),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["lexicon_source"] == "morphology-only"
    assert "terminology" not in report["evidence"]


def test_validate_measures_the_fallback(corpus, lexicon_artifact, capsys):
    assert (
        main(
            [
                "concepts",
                "validate",
                "--corpus",
                str(corpus),
                "--lexicon",
                str(lexicon_artifact),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["reference"] == "umls-2026AA"
    assert report["n_types"] > 0
    assert report["tokens_total"] > report["n_types"]


def test_missing_corpus_exits_nonzero_with_a_message(capsys):
    assert main(["applicability", "--corpus", "does/not/exist.csv"]) == 1
    assert "error:" in capsys.readouterr().err


def test_unsupported_format_exits_nonzero(tmp_path, capsys):
    path = tmp_path / "notes.docx"
    path.write_text("x", encoding="utf-8")
    assert main(["applicability", "--corpus", str(path)]) == 1
    assert "unsupported corpus format" in capsys.readouterr().err


def test_segment_reports_structure(tmp_path, capsys):
    path = tmp_path / "note.txt"
    path.write_text(NOTES[0].text, encoding="utf-8")
    assert main(["segment", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["provenance"]["note_sha256"]
    assert report["provenance"]["segmenter_version"]
    assert report["units"]["tokens"] > 0


class TestRepeatedPhenotypeFlags:
    """`--phenotype a --phenotype b` must declare both.

    It declared only `b`. The option was `nargs="*"` without `action="extend"`,
    so each occurrence *replaced* the previous one, and the loss is the silent
    kind this package keeps having to design against: an undeclared phenotype is
    never counted, so the run reports no evidence for it — indistinguishable
    from a corpus that genuinely never mentions it. The space-separated spelling
    always worked, which is why it went unnoticed.
    """

    @pytest.mark.parametrize("command", ["run", "concept-profile"])
    def test_repeating_accumulates(self, command, tmp_path):
        args = build_parser().parse_args(
            [
                command,
                "--corpus",
                str(tmp_path),
                "--out",
                str(tmp_path),
                "--phenotype",
                "hypertension",
                "--phenotype",
                "heart_failure",
            ]
        )
        assert args.phenotype == ["hypertension", "heart_failure"]

    @pytest.mark.parametrize("command", ["run", "concept-profile"])
    def test_space_separated_still_works(self, command, tmp_path):
        args = build_parser().parse_args(
            [
                command,
                "--corpus",
                str(tmp_path),
                "--out",
                str(tmp_path),
                "--phenotype",
                "hypertension",
                "heart_failure",
            ]
        )
        assert args.phenotype == ["hypertension", "heart_failure"]

    @pytest.mark.parametrize("command", ["run", "concept-profile"])
    def test_absent_is_none_not_empty(self, command, tmp_path):
        """None means agnostic — no terminology is loaded at all. An empty list
        would be a declaration of nothing, which takes a different path."""
        args = build_parser().parse_args(
            [command, "--corpus", str(tmp_path), "--out", str(tmp_path)]
        )
        assert args.phenotype is None


class TestCompose:
    """Several operators onto one note, and the ledger that keeps it honest."""

    def _run(self, tmp_path, corpus, *extra):
        out = tmp_path / ("out" + str(len(extra)))
        assert (
            main(
                [
                    "run",
                    "--corpus",
                    str(corpus),
                    "--out",
                    str(out),
                    "--operators",
                    "input.typo",
                    "render.whitespace_collapse",
                    "--severities",
                    "0.50",
                    *extra,
                ]
            )
            == 0
        )
        return [json.loads(line) for line in (out / "dose.jsonl").read_text().splitlines()]

    def test_composing_yields_one_cell_per_severity(self, tmp_path, corpus):
        """Two operators, one note: two cells without --compose, one with."""
        single = self._run(tmp_path, corpus)
        composed = self._run(tmp_path, corpus, "--compose")
        assert len(composed) * 2 == len(single)
        assert all(d["op_id"].startswith("composite(") for d in composed)
        assert all(len(d["composed_of"]) == 2 for d in composed)

    def test_a_composite_carries_both_operators_edits(self, tmp_path, corpus):
        """The point of composing: one document bearing both corruptions.

        Asserted through the edit script rather than the counts, because a
        composite whose edits all came from one operator would still produce a
        plausible `applied_n`.
        """
        out = tmp_path / "both"
        assert (
            main(
                [
                    "run",
                    "--corpus",
                    str(corpus),
                    "--out",
                    str(out),
                    "--operators",
                    "input.typo",
                    "render.whitespace_collapse",
                    "--severities",
                    "0.50",
                    "--compose",
                ]
            )
            == 0
        )
        rows = [json.loads(x) for x in (out / "edits.jsonl").read_text().splitlines()]
        assert {r["op_id"] for r in rows} == {"input.typo", "render.whitespace_collapse"}
        # …and every one is filed under the composite cell, which is what replay
        # groups by. Storing the proposing operator as the cell key made every
        # composite reconstruct from zero edits.
        assert {r["cell_id"] for r in rows} == {"composite(input.typo+render.whitespace_collapse)"}

    def test_conflicts_are_counted_not_dropped_silently(self, tmp_path, corpus):
        """A sentence delete swallows spans a token operator wanted.

        Without a counter the composite would simply deliver less than asked and
        report the severity it requested — the exact failure the dose ledger
        exists to prevent.
        """
        out = tmp_path / "conflict"
        assert (
            main(
                [
                    "run",
                    "--corpus",
                    str(corpus),
                    "--out",
                    str(out),
                    "--operators",
                    "input.typo",
                    "discourse.sentence_delete",
                    "--severities",
                    "1.00",
                    "--compose",
                ]
            )
            == 0
        )
        doses = [json.loads(x) for x in (out / "dose.jsonl").read_text().splitlines()]
        assert any(d["conflicts_dropped"] > 0 for d in doses), (
            "deleting every sentence while typo-ing every token must collide"
        )
        for d in doses:
            assert d["applied_n"] + d["conflicts_dropped"] <= d["proposed_n"]

    def test_composition_is_order_independent(self, tmp_path, corpus):
        """`a,b` and `b,a` must produce the same bytes.

        Conflicts resolve by a content-derived total order (`edits/apply.py`),
        not by the order operators ran, so the composite is invariant. If that
        ever stops holding, two users running the same experiment with the
        operator list typed differently get different corpora.
        """
        forward = tmp_path / "fwd"
        reverse = tmp_path / "rev"
        for out, ops in (
            (forward, ["input.typo", "render.whitespace_collapse"]),
            (reverse, ["render.whitespace_collapse", "input.typo"]),
        ):
            assert (
                main(
                    [
                        "run",
                        "--corpus",
                        str(corpus),
                        "--out",
                        str(out),
                        "--operators",
                        *ops,
                        "--severities",
                        "0.50",
                        "--compose",
                    ]
                )
                == 0
            )
        hashes = []
        for out in (forward, reverse):
            doses = [json.loads(x) for x in (out / "dose.jsonl").read_text().splitlines()]
            hashes.append(sorted(d["output_sha256"] for d in doses))
        assert hashes[0] == hashes[1]


class TestEmitText:
    def test_refuses_to_write_outside_data(self, tmp_path, corpus):
        """Corrupted text carries the corpus's licence; a corrupted MIMIC note
        is still MIMIC. The default destination is the gitignored tree."""
        assert (
            main(
                [
                    "run",
                    "--corpus",
                    str(corpus),
                    "--out",
                    str(tmp_path / "o"),
                    "--operators",
                    "input.typo",
                    "--severities",
                    "0.30",
                    "--emit-text",
                    str(tmp_path / "leak"),
                ]
            )
            == 2
        )
        assert not (tmp_path / "leak").exists()

    def test_writes_when_the_licence_is_acknowledged(self, tmp_path, corpus):
        target = tmp_path / "acknowledged"
        assert (
            main(
                [
                    "run",
                    "--corpus",
                    str(corpus),
                    "--out",
                    str(tmp_path / "o2"),
                    "--operators",
                    "input.typo",
                    "--severities",
                    "0.30",
                    "--emit-text",
                    str(target),
                    "--i-understand-the-licence",
                ]
            )
            == 0
        )
        written = list(target.glob("*.txt"))
        assert written
        assert all(p.read_text(encoding="utf-8") for p in written)


class TestCompare:
    """Baseline vs corrupted, measured with the same instrument."""

    def test_compare_needs_a_run_and_reports_one_row_per_cell(self, tmp_path, corpus, capsys):
        run = tmp_path / "run"
        assert (
            main(
                [
                    "run",
                    "--corpus",
                    str(corpus),
                    "--out",
                    str(run),
                    "--operators",
                    "render.whitespace_collapse",
                    "--severities",
                    "0.30",
                    "0.50",
                ]
            )
            == 0
        )
        # No index in the test environment, so `compare` cannot run end to end
        # here; what is asserted is the contract it must satisfy — a row per
        # dose cell, keyed the way replay keys them. The measured behaviour is
        # exercised against MIMIC in validation/measurements/pipeline_audit.json.
        from robustehr.store import read_doses, read_edits

        doses = read_doses(run)
        edits = read_edits(run)
        cells = {(d["note_uid"], d["op_id"], d["severity"]) for d in doses}
        keyed = {(e.note_uid, e.cell_id, e.severity) for e in edits}
        assert keyed <= cells, "every edit must belong to a dose cell compare can find"

    def test_compare_is_registered_with_the_expected_flags(self):
        parser = build_parser()
        args = parser.parse_args(
            ["compare", "--run", "r", "--corpus", "c", "--markdown", "--phenotype", "hypertension"]
        )
        assert args.markdown and args.phenotype == ["hypertension"]


def test_every_command_the_readme_documents_actually_exists():
    """Documentation drift, caught mechanically.

    The README documented `robustehr profile`, `robustehr verify`, `--recipe`
    and `edits.parquet` — none of which ever existed. A reader following the
    quickstart hit a parser error on the second line. Prose drifts silently;
    this makes it fail a test instead.
    """
    import re
    from pathlib import Path

    readme = Path(__file__).resolve().parents[1] / "README.md"
    documented = set(re.findall(r"robustehr ([a-z][a-z-]+)", readme.read_text(encoding="utf-8")))
    parser = build_parser()
    actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
    real = set(actions[0].choices) if actions else set()
    assert documented <= real, f"README documents commands that do not exist: {documented - real}"


class TestDescribe:
    """Table 1 — organised by the taxonomy's levels, and only by those."""

    def test_structural_levels_need_no_terminology(self, corpus, capsys):
        """The licence guarantee, at the table level.

        Without an index the concept, assertion and phenotype fields are absent
        WITH A REASON, and every structural level is unaffected. Silently
        omitting them would make a corpus with no terminology installed look
        like a corpus with no concepts in it.
        """
        assert main(["describe", "--corpus", str(corpus), "--index", "/nonexistent"]) == 0
        report = json.loads(capsys.readouterr().out)
        levels = report["by_level"]
        assert levels["character"]["n"]["total"] > 0
        assert levels["token"]["word_min3"]["total"] > 0
        assert "concept_covered" not in levels["token"]
        assert "span" not in levels
        assert "no UMLS index" in report["unavailable"]["token.concept_covered"]
        assert "no UMLS index" in report["unavailable"]["span"]

    def test_no_fact_is_reported_twice(self, corpus, capsys):
        """One organisation, not two.

        `describe` used to emit a taxonomic `by_level` block beside six blocks
        of another design, and the same number appeared three times:
        `size.chars.total`, `by_level.character.n` and `by_level.document.chars`
        were all 45218. A reader who finds two paths to one number has to work
        out whether they mean the same thing, and a reader who finds three
        stops trusting the table.
        """
        assert main(["describe", "--corpus", str(corpus), "--index", "/nonexistent"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert set(report) == {
            "what",
            "corpus",
            "notes",
            "lexicon_source",
            "phenotypes",
            "by_level",
            "unavailable",
        }
        totals = {}
        for level, block in report["by_level"].items():
            if not isinstance(block, dict):
                continue
            for field, value in block.items():
                if isinstance(value, dict) and isinstance(value.get("total"), int):
                    totals.setdefault(value["total"], []).append(f"{level}.{field}")
        # Small counts collide innocently (two levels both having 3 of
        # something); a duplicated *large* count is a duplicated fact.
        duplicated = {n: where for n, where in totals.items() if n > 1000 and len(where) > 1}
        assert not duplicated, f"the same number is reported under several paths: {duplicated}"

    def test_the_composition_predicts_each_operator_denominator(self, corpus):
        """The property the word/token merge exists to deliver.

        The level used to be two rows — `token 6134` and `word 2530` — and
        NEITHER was any operator's eligible count: typo was on 1,796,
        char_shuffle on 1,364, ocr_confusion on 2,301. Without this test the
        merged row is just two numbers again, fewer of them.
        """
        from robustehr.corpus import read_documents
        from robustehr.document import Document
        from robustehr.metrics.describe import _token_composition
        from robustehr.ops import registry
        from robustehr.ops.base import OpContext, Scope
        from robustehr.protect.registry import protect_document

        registry.register_builtins()
        for record in read_documents(corpus, limit=4):
            doc = Document.from_text(record.text, uid=record.uid)
            ctx = OpContext(doc=doc, protection=protect_document(doc), scope=Scope())
            composition = _token_composition(doc)
            for op_id, field in [
                ("input.typo", "word_min3"),
                ("control.char_shuffle", "word_min4"),
            ]:
                eligible = len(registry.get(op_id)().eligible(ctx))
                assert eligible == composition[field], (
                    f"{record.uid}: {op_id} eligible on {eligible}, "
                    f"composition.{field} says {composition[field]}"
                )

    def test_every_level_baseline_predicts_its_operator_denominator(self, corpus):
        """The identification-corruption pairing, asserted rather than asserted-to.

        `LEVEL_OPERATORS` says which operators act on each level and
        `_unmeasured_levels_with_operators` proves each such level HAS a
        baseline. Neither proves the baseline is the right NUMBER — that is this
        test, and without it a level could carry a plausible count that no
        severity is ever a fraction of.

        Each row names the field a reader would multiply by a severity to
        predict what a run touches, and asserts it equals what the operator
        reports eligible on the same document.
        """
        from robustehr.corpus import read_documents
        from robustehr.document import Document
        from robustehr.metrics.describe import level_characteristics
        from robustehr.ops import registry
        from robustehr.ops.base import OpContext, Scope
        from robustehr.protect.registry import protect_document

        registry.register_builtins()
        pairs = [
            ("render.header_delete", "header", "standalone"),
            ("render.header_rename", "header", "renameable"),
            # `header.n` IS the section headers — the population all three
            # header operators run on. The wider "every heading-shaped line"
            # count lives in `heading_lines` and is nobody's denominator.
            ("render.header_style", "header", "n"),
            ("render.list_to_prose", "list_block", "multi_item"),
            ("render.bullet_to_prose", "list_item", "n"),
            ("render.break_removal", "break", "n"),
            ("render.space_delete", "word_space", "n"),
            ("discourse.section_duplicate", "section", "duplicable"),
            ("discourse.sentence_delete", "sentence", "prose"),
            ("input.ocr_confusion", "character", "ocr_confusable"),
            ("lexical.numeral_to_word", "numeric_value", "n"),
            ("lexical.medication_rename", "medication", "renameable"),
        ]
        for record in read_documents(corpus, limit=4):
            doc = Document.from_text(record.text, uid=record.uid)
            ctx = OpContext(doc=doc, protection=protect_document(doc), scope=Scope())
            levels = level_characteristics(doc)
            for op_id, level, field in pairs:
                eligible = len(registry.get(op_id)().eligible(ctx))
                assert eligible == levels[level][field], (
                    f"{record.uid}: {op_id} eligible on {eligible}, "
                    f"{level}.{field} says {levels[level][field]}"
                )

    def test_every_level_names_the_operators_that_can_reach_it(self, corpus, capsys):
        from robustehr.metrics.describe import LEVEL_OPERATORS

        assert main(["describe", "--corpus", str(corpus), "--index", "/nonexistent"]) == 0
        levels = json.loads(capsys.readouterr().out)["by_level"]
        assert levels["_unmeasured_levels_with_operators"] == []
        for name, expected in LEVEL_OPERATORS.items():
            if name in levels and name != "assertion":
                assert levels[name]["operators"] == list(expected)

    def test_absent_canonical_sections_are_reported_not_omitted(self, corpus, capsys):
        """Which of the 58, not how many.

        The baseline used to say "34 sections" and never *which*, which cannot
        answer the question a reader has: do these notes carry a past medical
        history and a discharge medication list? A missing key would answer
        "not measured" when the truth is "not in this corpus", so every
        declared id gets a row whether or not it was found.
        """
        from robustehr.metrics.describe import canonical_sections

        declared = canonical_sections()
        assert main(["describe", "--corpus", str(corpus), "--index", "/nonexistent"]) == 0
        section = json.loads(capsys.readouterr().out)["by_level"]["section"]
        presence = section["canonical_presence"]
        assert set(presence) == set(declared), "a declared section is missing a row"
        assert section["canonical_declared"] == len(declared)
        absent = {n for n, row in presence.items() if row["notes_with"] == 0}
        assert set(section["canonical_absent"]) == absent
        assert absent, "a corpus that carried all 58 would make this test vacuous"
        for name, row in presence.items():
            assert row["kind"] == declared[name]
            # Present means a body was measured; absent means no median exists.
            assert (row["body_chars_median"] is None) == (row["notes_with"] == 0)

    def test_abbreviation_load_degrades_with_a_reason(self, corpus, capsys):
        """It needs the terminology; the shape count beside it does not.

        Silently omitting the abbreviation fields would make a corpus with no
        index installed look like a corpus with no ambiguous shorthand, which is
        the inverse of the truth for clinical text.
        """
        assert main(["describe", "--corpus", str(corpus), "--index", "/nonexistent"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert "abbreviations" not in report["by_level"]["token"]
        assert "no UMLS index" in report["unavailable"]["token.abbreviations"]
        # The free half is unaffected: a shape count needs no terminology.
        assert report["by_level"]["token"]["short_form"]["total"] > 0

    def test_neither_abbreviation_population_contains_the_other(self):
        """`short_form` and `abbreviations` measure different things.

        Both live at the token level and a reader will be tempted to read one as
        a subset of the other. It is neither: `short_form` is upper-case and
        2-5 characters, while `is_abbreviation_shaped` excludes ordinary English
        and admits mixed case. Concrete witnesses in both directions, so the
        claim in the docstring is checked rather than asserted.
        """
        from robustehr.metrics.ambiguity import is_abbreviation_shaped

        def short_form(word: str) -> bool:
            return word.isupper() and 2 <= len(word) <= 5

        # BLOOD heads a MIMIC lab line: a shape count sees an abbreviation, the
        # terminology-facing definition correctly does not.
        assert short_form("BLOOD") and not is_abbreviation_shaped("BLOOD")
        # HFrEF is an abbreviation by anyone's reading, and is not upper-case.
        assert is_abbreviation_shaped("HFrEF") and not short_form("HFrEF")

    def test_abbreviation_aggregation_shares_by_abbreviation_not_by_token(self):
        """The denominator is the shorthand, not the note.

        A share of all tokens would move with note length rather than with
        shorthand density, which is the opposite of what the number is for.
        """
        from robustehr.metrics.ambiguity import AmbiguityProfile
        from robustehr.metrics.describe import _add_abbreviation_load

        token: dict[str, object] = {}
        _add_abbreviation_load(
            token,
            [
                AmbiguityProfile("a", "x", 100, {"ambiguous": 3, "resolved": 1}, (), 4, 3, 1),
                AmbiguityProfile("b", "y", 900, {"ambiguous": 1, "resolved": 5}, (), 6, 1, 0),
            ],
        )
        assert token["abbreviations"]["total"] == 10
        assert token["abbreviations_ambiguous"]["total"] == 4
        assert token["abbreviations_ambiguous"]["share_of_abbreviations"] == 0.4
        # Both denominators, because both questions get asked: 4 of 10
        # abbreviations, and 4 of 1000 content tokens.
        assert token["abbreviations_ambiguous"]["share_of_content"] == 0.004
        assert token["abbreviation_outcomes"] == {
            "resolved": {"n": 6, "share": 0.6},
            "ambiguous": {"n": 4, "share": 0.4},
        }

    def test_near_miss_names_what_was_measured(self, corpus, capsys):
        """The field is `near_miss_edit1`, and the note says why.

        Measured precision is 0.096 by occurrence: nine parts in ten of the
        count are vocabulary the lexicons miss and clinical shorthand. A field
        called `misspellings` carrying that number would be a wrong claim in a
        methods table, so the name and the caveat travel together.
        """
        assert main(["describe", "--corpus", str(corpus), "--index", "/nonexistent"]) == 0
        token = json.loads(capsys.readouterr().out)["by_level"]["token"]
        if "near_miss_edit1" not in token:
            pytest.skip("no clinical lexicon installed; the measure degrades by design")
        assert "misspelling" not in {k.lower() for k in token}
        note = token["near_miss_note"]
        assert "NOT a misspelling rate" in note
        assert "0.096" in note and "distinct_hapax" in note

    def test_per_note_rows_reconcile_with_the_corpus_totals(self, corpus, capsys):
        """The per-note view is the aggregate before `quantiles` collapsed it.

        If the two could drift they would be two measurements wearing one name,
        which is the duplication this table was reorganised to remove. So the
        totals are checked to be sums of exactly these rows.
        """
        assert (
            main(["describe", "--corpus", str(corpus), "--index", "/nonexistent", "--per-note"])
            == 0
        )
        report = json.loads(capsys.readouterr().out)
        rows = report["notes_detail"]
        assert len(rows) == report["notes"]
        assert all(r["note_uid"] for r in rows)
        for level, fieldname in [
            ("character", "n"),
            ("token", "n"),
            ("sentence", "n"),
            ("header", "n"),
        ]:
            summed = sum(r["by_level"][level][fieldname] for r in rows)
            assert summed == report["by_level"][level][fieldname]["total"], level
        assert "ote-derived" in report["notes_detail_note"]

    def test_per_note_is_deterministic(self, corpus, capsys):
        args = ["describe", "--corpus", str(corpus), "--index", "/nonexistent", "--per-note"]
        assert main(args) == 0
        first = capsys.readouterr().out
        assert main(args) == 0
        assert capsys.readouterr().out == first

    def test_token_coverage_is_not_the_span_count(self, corpus):
        """ "% of tokens that are concepts" is not mentions divided by tokens.

        A mention is a SPAN — `acute on chronic systolic heart failure` is one
        mention over six tokens, `pain` is one over one — so the division
        answers nothing. Coverage counts each token under a mention once, which
        is why it can be larger than the mention count (long spans) and can
        never exceed the content-token count (overlaps collapse).
        """
        from robustehr.concepts.matcher import Mention, MentionIndex
        from robustehr.document import Document
        from robustehr.metrics.concepts import profile_concepts
        from robustehr.types import Span

        text = "Patient has acute on chronic systolic heart failure and pain.\n"
        doc = Document.from_text(text, uid="cover")
        long_span = Span(text.index("acute"), text.index("failure") + len("failure"))
        short = Span(text.index("pain"), text.index("pain") + len("pain"))
        index = MentionIndex(
            mentions=(
                Mention(long_span, "C0018802", frozenset({"T047"}), 1.0),
                # Deliberately overlapping: `heart failure` inside the longer
                # span. Coverage must not double-count those tokens.
                Mention(
                    Span(text.index("heart"), text.index("failure") + len("failure")),
                    "C0018801",
                    frozenset({"T047"}),
                    1.0,
                ),
                Mention(short, "C0030193", frozenset({"T184"}), 1.0),
            )
        )
        profile = profile_concepts(doc, index)
        assert profile.concepts == 3, "three mention spans"
        # `acute on chronic systolic heart failure` is 6 tokens, `pain` is 1,
        # and the overlapping mention adds none.
        assert profile.concept_tokens == 7
        assert profile.span_token_lengths == {"4+": 1, "2": 1, "1": 1}
        assert profile.concept_tokens <= profile.content_tokens

    def test_assertion_level_reports_cues_not_attribute_counts(self, corpus, capsys):
        """The denominator of a SEMANTIC operator is its CUES.

        The level used to report `negated 355` — mentions carrying the
        attribute — while `semantic.negation_flip` is eligible on negation
        cues, of which this corpus has a different number. One cue scopes over
        several mentions, so neither predicts the other, and a severity of 0.30
        is a fraction of the cues.
        """
        from robustehr.metrics.describe import CUE_CATEGORIES

        assert main(["describe", "--corpus", str(corpus), "--index", "/nonexistent"]) == 0
        levels = json.loads(capsys.readouterr().out)["by_level"]
        assertion = levels.get("assertion")
        if not assertion or "n" not in assertion:
            pytest.skip("clinical extra not installed; the level degrades by design")
        # Cues need medspaCy and NOT a UMLS licence, so they are present here
        # even though the whole run has no index.
        for op_id, wanted in CUE_CATEGORIES.items():
            assert assertion[op_id]["cue_categories"] == list(wanted)
            assert assertion[op_id]["eligible_cues"] >= 0
        # `n` is the cue count, the same meaning `n` carries at every other
        # level: the units this level's operators enumerate.
        assert assertion["n"]["total"] == sum(
            assertion[op]["eligible_cues"] for op in CUE_CATEGORIES
        )
        # The attribute cross-tab needs the concept layer and is absent here,
        # with a reason rather than silently.
        assert "by_attribute" not in assertion

    @pytest.fixture
    def labels(self, tmp_path):
        """A wide binary label file over the first notes of the CLI corpus.

        Deliberately OVERLAPPING — note 0 is positive for both — because that is
        what a real phenotype label set looks like and the arithmetic has to
        survive it.
        """
        path = tmp_path / "labels.csv"
        uids = [n.id for n in NOTES[:12]]
        lines = ["note_id,alpha,beta,none"]
        for i, uid in enumerate(uids):
            alpha = 1 if i < 4 else 0
            beta = 1 if 2 <= i < 6 else 0
            # `0.0` as well as `0`: the MIPA file writes both, and treating the
            # float as truthy made every note positive for everything.
            none = "1" if (not alpha and not beta and i < 8) else "0.0"
            lines.append(f"{uid},{alpha},{beta},{none}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_cohorts_overlap_and_the_arithmetic_says_so(self, corpus, labels, capsys):
        """Groups are cohorts, not a partition.

        A note positive for hypertension is often positive for depression too,
        so memberships exceed notes. Presenting them as a partition would imply
        the group sizes should sum to the corpus, and a reader would go looking
        for the missing notes.
        """
        assert (
            main(
                [
                    "describe",
                    "--corpus",
                    str(corpus),
                    "--index",
                    "/nonexistent",
                    "--groups",
                    str(labels),
                ]
            )
            == 0
        )
        report = json.loads(capsys.readouterr().out)
        groups = report["by_group"]
        assert groups["alpha"]["notes"] == 4
        assert groups["beta"]["notes"] == 4
        coverage = groups["_coverage"]
        assert coverage["group_memberships"] == 4 + 4 + 2  # alpha, beta, none
        assert coverage["group_memberships"] > coverage["notes_in_at_least_one_group"]
        assert coverage["notes_in_no_group"] == 4

    def test_a_cohort_is_a_subset_of_the_same_measurements(self, corpus, labels, capsys):
        """Not a re-run: `assemble` over a subset of rows already measured.

        A describe invocation per group would annotate every note once per group
        it belongs to — on the MIPA labels, 4,003 passes over 1,387 notes — and
        would let a group's numbers disagree with the corpus's.
        """
        args = ["describe", "--corpus", str(corpus), "--index", "/nonexistent"]
        assert main([*args, "--per-note"]) == 0
        rows = {r["note_uid"]: r for r in json.loads(capsys.readouterr().out)["notes_detail"]}
        assert main([*args, "--groups", str(labels)]) == 0
        alpha = json.loads(capsys.readouterr().out)["by_group"]["alpha"]
        members = [r for uid, r in rows.items() if uid in {n.id for n in NOTES[:4]}]
        assert alpha["notes"] == len(members)
        assert alpha["by_level"]["character"]["n"]["total"] == sum(
            r["by_level"]["character"]["n"] for r in members
        )

    def test_the_label_map_is_a_resource_a_reviewer_can_read(self, corpus, labels, capsys):
        """Which annotator ran on which cohort decides the numbers.

        Getting it wrong produces a table that looks right, so the
        correspondence lives in `label_groups.yaml` and an unknown label set is
        an error rather than a silent fall back to name-matching.
        """
        from robustehr.metrics.describe import load_group_map

        mipa = load_group_map("mipa")
        assert mipa["sle"] == ["systemic_lupus_erythematosus"]
        # VTE is one label over two declared phenotypes; the cohort's evidence
        # is the union, which is what `any(pheno=...;pheno=...)` selects.
        assert mipa["vte_past"] == ["deep_vein_thrombosis", "pulmonary_embolism"]
        # The negative control names no phenotype, and that is not an omission.
        assert mipa["none"] == []
        assert (
            main(
                [
                    "describe",
                    "--corpus",
                    str(corpus),
                    "--index",
                    "/nonexistent",
                    "--groups",
                    str(labels),
                    "--group-map",
                    "not-a-label-set",
                ]
            )
            == 2
        )
        assert "cannot read groups" in capsys.readouterr().err

    def test_every_declared_phenotype_in_the_map_exists(self):
        """A typo in the map would point a cohort at nothing and report zero
        evidence, which is indistinguishable from a cohort whose notes genuinely
        carry none."""
        from robustehr.concepts.phenotype import load_definitions
        from robustehr.metrics.describe import load_group_map

        declared = set(load_definitions())
        named = {p for names in load_group_map("mipa").values() for p in names}
        assert named <= declared, f"map names undeclared phenotypes: {named - declared}"

    def test_one_document_per_cohort_and_the_same_bytes_every_time(self, corpus, labels, tmp_path):
        """The deliverable is a document per phenotype, reproducible from the CLI.

        Byte-identical across runs is the property that makes a cohort table
        quotable in a manuscript: a reviewer re-running the command must get the
        file the numbers came from, not a file that agrees to three decimals.
        """
        out = tmp_path / "cohorts"
        again = tmp_path / "cohorts_again"
        for target in (out, again):
            assert (
                main(
                    [
                        "describe",
                        "--corpus",
                        str(corpus),
                        "--index",
                        "/nonexistent",
                        "--groups",
                        str(labels),
                        "--group-out",
                        str(target),
                        "--out",
                        str(tmp_path / "table1.json"),
                    ]
                )
                == 0
            )
        names = sorted(p.name for p in out.iterdir())
        assert names == ["alpha.json", "alpha.md", "beta.json", "beta.md", "none.json", "none.md"]
        for name in names:
            assert (out / name).read_bytes() == (again / name).read_bytes(), name

        # A cohort document stands on its own: it names its own note count and
        # its own annotator, so it cannot be mistaken for the corpus table.
        alpha = (out / "alpha.md").read_text(encoding="utf-8")
        assert "cohort alpha" in alpha.splitlines()[0]
        assert "**4 notes.**" in alpha
        # The digestible Table 1: one indented table covering every level, not
        # the twelve audit tables. Seventeen cohorts x twelve tables is not a
        # comparison anyone makes.
        assert "| **Characters** |" in alpha and "| **Tokens** |" in alpha
        assert "canonical sections" not in alpha, "audit tables belong behind --detail"
        payload = json.loads((out / "alpha.json").read_text(encoding="utf-8"))
        assert payload["notes"] == 4
        assert payload["phenotypes"] == ["alpha"]

    def test_rerendering_from_a_table_reproduces_the_measuring_run(self, corpus, labels, tmp_path):
        """The documents are a pure function of the table, byte for byte.

        This is what makes the artifact quotable: the 1,388-note annotation
        pass takes ~76 minutes, and a reviewer re-rendering from the published
        table must get the same files rather than files that agree to three
        decimals.

        It caught a real defect. `unavailable` was joined in insertion order,
        and a payload that had been through `json.dumps(sort_keys=True)` came
        back alphabetical — so every re-rendered document differed from the
        measuring run's by exactly one line.
        """
        table = tmp_path / "table1.json"
        measured, rerendered = tmp_path / "measured", tmp_path / "rerendered"
        assert (
            main(
                [
                    "describe",
                    "--corpus",
                    str(corpus),
                    "--index",
                    "/nonexistent",
                    "--groups",
                    str(labels),
                    "--group-out",
                    str(measured),
                    "--out",
                    str(table),
                ]
            )
            == 0
        )
        # No --corpus at all: re-rendering must not read the notes.
        assert main(["describe", "--from-table", str(table), "--group-out", str(rerendered)]) == 0
        for path in sorted(measured.iterdir()):
            assert path.read_bytes() == (rerendered / path.name).read_bytes(), path.name

    def test_describe_needs_a_corpus_or_a_table(self, capsys):
        assert main(["describe"]) == 2
        assert "needs --corpus" in capsys.readouterr().err

    def test_quantiles_are_values_a_note_actually_has(self):
        """Nearest-rank, not interpolated. An interpolated median of integer
        counts is a number no note has, and this table is read as 'a typical
        note looks like this'."""
        from robustehr.metrics.describe import quantiles

        got = quantiles([1, 2, 3, 4, 5])
        assert got == {"p25": 2, "median": 3, "p75": 4, "min": 1, "max": 5}
        assert quantiles([])["median"] is None

    def test_empty_corpus_is_a_report_not_a_crash(self):
        from robustehr.metrics.describe import assemble

        table = assemble([], {})
        assert table.notes == 0
        assert table.unavailable


class TestTargetingProvenance:
    """A run that targets a phenotype says what the target was built from, and
    builds it on both warrants."""

    NOTE = "Assessment:\nHTN, well controlled. Continue home regimen.\n"

    @staticmethod
    def _phenotype():
        from robustehr.concepts.phenotype import Phenotype
        from robustehr.concepts.surface import AnchorSet

        return Phenotype(
            name="hypertension",
            seed_codes=("38341003",),
            concept_cuis=frozenset({"C0020538"}),
            concept_codes=frozenset({"38341003"}),
            anchors=AnchorSet(phenotype="hypertension", anchors=("htn",)),
        )

    @pytest.fixture
    def stubbed(self, monkeypatch, tmp_path):
        """No licensed index: the matcher finds nothing, so only the surface warrant can."""
        from robustehr import cli
        from robustehr.concepts import matcher, pipeline
        from robustehr.concepts.matcher import MentionIndex

        monkeypatch.setattr(
            cli, "_load_phenotypes", lambda args: [self._phenotype()] if args.phenotype else []
        )

        class NoMatcher:
            def __init__(self, path):
                self.path = path

        monkeypatch.setattr(matcher, "ConceptMatcher", NoMatcher)
        monkeypatch.setattr(pipeline, "annotate_document", lambda doc, m: MentionIndex(()))
        corpus = tmp_path / "corpus.csv"
        with corpus.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["note_id", "text"])
            writer.writerow(["note-htn", self.NOTE])
        return corpus

    def _run(self, corpus, tmp_path, *extra):
        out = tmp_path / "run"
        code = main(
            [
                "run",
                "--corpus",
                str(corpus),
                "--out",
                str(out),
                "--operators",
                "input.typo",
                "--severities",
                "1",
                "--no-assertions",
                "--index",
                str(tmp_path / "no-index"),
                *extra,
            ]
        )
        assert code == 0
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        doses = [
            json.loads(line)
            for line in (out / "dose.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        return manifest, doses

    def test_a_phenotype_run_records_the_targeting_block(self, stubbed, tmp_path):
        from robustehr.concepts import surface

        # The terminology inputs exist on this machine (their content is stubbed
        # away with `_load_phenotypes`), so the target is built on both warrants.
        isa, crosswalk = tmp_path / "isa.json", tmp_path / "crosswalk"
        isa.write_text("{}", encoding="utf-8")
        crosswalk.mkdir()
        manifest, _ = self._run(
            stubbed,
            tmp_path,
            "--phenotype",
            "hypertension",
            "--phenotype-scope",
            "target",
            "--isa",
            str(isa),
            "--crosswalk",
            str(crosswalk),
        )
        block = manifest["targeting"]
        assert block["warrants"] == ["concept", "surface"]
        assert block["targeting_digest"] == surface.targeting_digest()
        assert block["anchors_vetted_by"] in (*surface.VETTED_BY, "absent")
        assert block["vetting_vetted_by"] in (*surface.VETTED_BY, "absent")
        for section in ("resources", "external"):
            for name, digest in block[section].items():
                assert digest == "absent" or len(digest) == 64, (section, name, digest)
        assert set(block["resources"]) >= {"phenotype_anchors.yaml", "phenotype_vetting.yaml"}
        assert "phenotype_nonspecific.yaml" in block["resources"]

    def test_without_terminology_the_target_is_surface_only_and_says_so(
        self, monkeypatch, tmp_path, capsys
    ):
        """No isa, no crosswalk, no index: `pheno=` still works on the shipped
        surface forms, the manifest records the weaker warrant, and evidence is found."""
        corpus = tmp_path / "corpus.csv"
        with corpus.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["note_id", "text"])
            writer.writerow(["note-htn", self.NOTE])
        manifest, doses = self._run(
            corpus,
            tmp_path,
            "--phenotype",
            "hypertension",
            "--target",
            "pheno=hypertension",
            "--isa",
            str(tmp_path / "absent.json"),
            "--crosswalk",
            str(tmp_path / "absent"),
        )
        assert manifest["targeting"]["warrants"] == ["surface"]
        assert "surface warrant" in capsys.readouterr().err
        assert doses[0]["evidence_n"] == {"hypertension": 1}
        assert doses[0]["eligible_n"] >= 1

    def test_the_surface_warrant_reaches_selection_through_the_cli(self, stubbed, tmp_path):
        """The matcher found nothing; the abbreviation is still evidence and still
        the only thing a target-scope run may edit."""
        _, doses = self._run(
            stubbed, tmp_path, "--phenotype", "hypertension", "--phenotype-scope", "target"
        )
        assert doses, "no dose rows written"
        row = doses[0]
        assert row["evidence_n"] == {"hypertension": 1}
        assert row["eligible_n"] >= 1
        assert row["evidence_touch"] == {"hypertension": 1}

    def test_an_agnostic_run_records_no_targeting(self, stubbed, tmp_path):
        manifest, doses = self._run(stubbed, tmp_path)
        assert manifest["targeting"] is None
        assert doses[0]["evidence_touch"] == {}
