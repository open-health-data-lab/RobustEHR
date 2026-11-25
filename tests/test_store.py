"""Persisting a run, and reproducing it from what was persisted."""

from __future__ import annotations

import json

import pytest

from robustehr.document import Document
from robustehr.ops import registry
from robustehr.runner import apply_operator, severity_ladder
from robustehr.store import (
    MAX_REPLACEMENT_CHARS,
    EditRow,
    RedistributionError,
    read_doses,
    read_edits,
    replay,
    verify_note_hashes,
    write_run,
)
from robustehr.types import Edit
from tests.fixtures.clinical import FORMATS

NOTES = tuple(FORMATS.values())[:6]


def make_run(tmp_path, notes=NOTES, severities=("0.30",)):
    registry.register_builtins()
    doses, edits, texts = [], [], {}
    ladder = severity_ladder(*severities)
    for note in notes:
        doc = Document.from_text(note.text, uid=note.id)
        texts[note.id] = note.text
        for op_id in ("input.typo", "render.whitespace_collapse", "control.identity"):
            op_cls = registry.get(op_id)
            operator = op_cls()
            for severity in ladder:
                result = apply_operator(doc, operator, operator.meta, severity, run_id="t")
                doses.append(result.dose)
                edits.append(result.apply_result.applied)
    manifest = write_run(tmp_path, run_id="t", doses=doses, edits=edits, corpus="fixtures")
    return manifest, texts


def test_a_stored_run_replays_byte_for_byte(tmp_path):
    """The claim the whole artifact rests on."""
    _, texts = make_run(tmp_path)
    results = replay(tmp_path, texts)
    assert results
    assert all(r.verified for r in results), [r.note_uid for r in results if not r.verified]


def test_replay_across_several_severities(tmp_path):
    _, texts = make_run(tmp_path, severities=("0.10", "0.30", "0.50"))
    results = replay(tmp_path, texts)
    assert len({r.severity for r in results}) == 3
    assert all(r.verified for r in results)


def test_replay_skips_notes_the_reader_does_not_have(tmp_path):
    """A partial corpus is normal; reporting a false mismatch would be useless."""
    _, texts = make_run(tmp_path)
    partial = dict(list(texts.items())[:2])
    results = replay(tmp_path, partial)
    assert {r.note_uid for r in results} == set(partial)
    assert all(r.verified for r in results)


def test_a_different_corpus_is_caught_before_replay(tmp_path):
    """Turns "your output differs" into "your input differs"."""
    _, texts = make_run(tmp_path)
    uid = next(iter(texts))
    tampered = dict(texts)
    tampered[uid] = texts[uid] + "\nAn extra line.\n"
    assert verify_note_hashes(tmp_path, tampered) == [uid]
    assert verify_note_hashes(tmp_path, texts) == []


def test_replay_detects_a_corrupted_edit_script(tmp_path):
    """If the artifact is altered, verification must fail rather than pass."""
    _, texts = make_run(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "edits.jsonl").read_text().splitlines()]
    typo = next(r for r in rows if r["op_id"] == "input.typo")
    typo["replacement"] = typo["replacement"] + "X"
    (tmp_path / "edits.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
    )
    assert any(not r.verified for r in replay(tmp_path, texts))


# -- the redistribution guard ----------------------------------------------


def test_a_long_replacement_is_refused(tmp_path):
    """Edit scripts are redistributable *because* they carry offsets, not text.

    An operator emitting whole paragraphs would turn the artifact into a copy of
    the corpus, so the limit is enforced at write time rather than trusted.
    """
    make_run(tmp_path)
    assert read_doses(tmp_path)
    edit = Edit(
        start=0,
        end=1,
        replacement="x" * (MAX_REPLACEMENT_CHARS + 1),
        op_id="test.oversized",
        unit_id="u0",
    )

    class FakeDose:
        run_id = note_uid = note_sha256 = op_version = "x"
        severity_canon = scope_canon = "x"
        stage_index = 0

    with pytest.raises(RedistributionError, match="redistributable"):
        EditRow.of(edit, FakeDose())  # type: ignore[arg-type]


def test_stored_replacements_stay_short(tmp_path):
    """Measured, not assumed: nothing patient-identifying fits in 120 chars."""
    make_run(tmp_path)
    rows = read_edits(tmp_path)
    assert rows
    assert max(len(r.replacement) for r in rows) <= MAX_REPLACEMENT_CHARS


def test_manifest_records_what_a_reader_needs(tmp_path):
    manifest, _ = make_run(tmp_path)
    assert manifest["contains_note_text"] is False
    assert manifest["cells"] > 0
    assert manifest["dose_sha256"] and manifest["edits_sha256"]
    assert manifest["environment"]["schema_version"]


def test_edit_rows_round_trip(tmp_path):
    make_run(tmp_path)
    for row in read_edits(tmp_path):
        edit = row.to_edit()
        assert edit.start == row.start
        assert edit.end == row.end
        assert edit.replacement == row.replacement
        assert edit.edit_id == row.edit_id


def test_writing_refuses_mismatched_inputs(tmp_path):
    with pytest.raises(ValueError, match="dose records against"):
        write_run(tmp_path, run_id="t", doses=[], edits=[[]], corpus="x")
