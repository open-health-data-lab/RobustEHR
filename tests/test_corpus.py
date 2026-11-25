"""Corpus ingestion: column aliasing, formats, and what is deliberately absent."""

from __future__ import annotations

import json

import pytest

from robustehr.corpus import ALIASES, ColumnMap, CorpusError, read_documents, read_records


def write_csv(tmp_path, header: str, *rows: str):
    path = tmp_path / "notes.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_resolves_mimic_column_names():
    mapping = ColumnMap.resolve(["note_id", "subject_id", "hadm_id", "charttime", "text"])
    assert mapping.note_id == "note_id"
    assert mapping.text == "text"
    assert mapping.patient_id == "subject_id"
    assert mapping.timestamp == "charttime"


def test_resolves_alternative_spellings():
    mapping = ColumnMap.resolve(["DOC_ID", "Report_Text", "MRN"])
    assert (mapping.note_id, mapping.text, mapping.patient_id) == ("DOC_ID", "Report_Text", "MRN")
    assert mapping.timestamp is None


def test_missing_text_column_names_the_columns():
    with pytest.raises(CorpusError, match="no text column"):
        ColumnMap.resolve(["note_id", "label"])


def test_missing_id_column_is_an_error():
    with pytest.raises(CorpusError, match="no note identifier"):
        ColumnMap.resolve(["text", "label"])


def test_label_columns_are_never_read(tmp_path):
    """Labels are not merely optional — the core does not look for them.

    A ``label`` column must not become a field, an alias, or a silent
    dependency. The package has to work on unlabelled corpora, which are the
    overwhelming majority.
    """
    assert not any("label" in alias for aliases in ALIASES.values() for alias in aliases)
    path = write_csv(tmp_path, "note_id,text,label", "n1,Patient is well.,1")
    records, mapping = read_records(path)
    assert mapping.to_dict() == {
        "note_id": "note_id",
        "text": "text",
        "patient_id": None,
        "timestamp": None,
    }
    assert records[0].note_id == "n1"
    assert not hasattr(records[0], "label")


def test_reads_jsonl(tmp_path):
    path = tmp_path / "notes.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"note_id": "a", "text": "First note."},
                {"note_id": "b", "text": "Second note."},
            ]
        ),
        encoding="utf-8",
    )
    records, _ = read_records(path)
    assert [r.note_id for r in records] == ["a", "b"]


def test_first_row_is_not_consumed_by_column_detection(tmp_path):
    """Resolving the mapping reads a row; that row must still be returned."""
    path = write_csv(tmp_path, "note_id,text", "n1,alpha", "n2,beta", "n3,gamma")
    records, _ = read_records(path)
    assert [r.note_id for r in records] == ["n1", "n2", "n3"]


def test_limit_bounds_the_read(tmp_path):
    path = write_csv(tmp_path, "note_id,text", *(f"n{i},note {i}" for i in range(10)))
    records, _ = read_records(path, limit=3)
    assert len(records) == 3


def test_empty_text_rows_are_skipped(tmp_path):
    path = write_csv(tmp_path, "note_id,text", "n1,", "n2,real content")
    records, _ = read_records(path)
    assert [r.note_id for r in records] == ["n2"]


def test_unsupported_format_is_refused(tmp_path):
    path = tmp_path / "notes.docx"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(CorpusError, match="unsupported corpus format"):
        read_records(path)


def test_empty_corpus_is_refused(tmp_path):
    path = tmp_path / "notes.csv"
    path.write_text("note_id,text\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="no rows"):
        read_records(path)


def test_documents_carry_the_note_id(tmp_path):
    path = write_csv(tmp_path, "note_id,text", "n1,Patient denies chest pain.")
    docs = list(read_documents(path))
    assert docs[0].uid == "n1"
    assert docs[0].text.startswith("Patient denies")
