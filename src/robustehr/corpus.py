"""Reading a corpus of notes.

The ingestion contract is deliberately minimal: any source exposing
``(note_id, text)``. ``patient_id`` and ``timestamp`` are optional and unlock
specific features when present — patient-clustered resampling and the
copy-forward donor ordering respectively — but nothing requires them.

**No label column is read anywhere.** Not "labels are optional and we ignore
them if absent"; the core never looks. Phenotype configuration selects concepts
to protect or target, which needs concept sets rather than document labels, and
keeping labels out of the core is what makes the package usable on the
unlabelled corpora that are the overwhelming majority.

Column names vary across institutions more than the data does, so a small set of
aliases is accepted for each field and the resolved mapping is reported rather
than guessed at silently.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from robustehr.document import Document

#: Accepted spellings for each field, in priority order. Institutions differ on
#: these far more than the underlying data does.
ALIASES: dict[str, tuple[str, ...]] = {
    "note_id": ("note_id", "note_uid", "id", "doc_id", "document_id", "row_id", "uid"),
    # `note_corrupted` and `note_text` are what the downstream evaluation harness
    # writes, so a generated dataset is readable by the package that made it.
    "text": (
        "text",
        "note_text",
        "note_corrupted",
        "note",
        "body",
        "content",
        "report_text",
    ),
    "patient_id": ("patient_id", "subject_id", "pat_id", "mrn", "person_id"),
    "timestamp": ("timestamp", "charttime", "chartdate", "note_datetime", "date", "storetime"),
}


class CorpusError(ValueError):
    """The corpus could not be read as ``(note_id, text)``."""


@dataclass(frozen=True, slots=True)
class Record:
    note_id: str
    text: str
    patient_id: str | None = None
    timestamp: str | None = None


@dataclass(frozen=True, slots=True)
class ColumnMap:
    """Which source columns were used for which field.

    Reported in the run manifest. A silent column guess that happens to be wrong
    produces a corpus-wide error that is invisible in the output, so the mapping
    is always recorded.
    """

    note_id: str
    text: str
    patient_id: str | None = None
    timestamp: str | None = None

    @classmethod
    def resolve(cls, columns: list[str]) -> ColumnMap:
        lowered = {name.lower().strip(): name for name in columns}
        found: dict[str, str | None] = {}
        for field, aliases in ALIASES.items():
            found[field] = next((lowered[a] for a in aliases if a in lowered), None)
        if found["text"] is None:
            raise CorpusError(
                f"no text column found among {columns!r}; expected one of {ALIASES['text']}"
            )
        if found["note_id"] is None:
            raise CorpusError(
                f"no note identifier found among {columns!r}; expected one of {ALIASES['note_id']}"
            )
        return cls(
            note_id=found["note_id"],
            text=found["text"],
            patient_id=found["patient_id"],
            timestamp=found["timestamp"],
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "note_id": self.note_id,
            "text": self.text,
            "patient_id": self.patient_id,
            "timestamp": self.timestamp,
        }


def _rows_csv(path: Path) -> Iterator[dict[str, str]]:
    # Clinical notes routinely exceed the default 128 KiB field limit, and the
    # resulting error names neither the file nor the note.
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def _rows_jsonl(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _rows_parquet(path: Path) -> Iterator[dict[str, str]]:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    for batch in table.to_batches():
        yield from batch.to_pylist()


READERS = {
    ".csv": _rows_csv,
    ".tsv": _rows_csv,
    ".jsonl": _rows_jsonl,
    ".ndjson": _rows_jsonl,
    ".json": _rows_jsonl,
    ".parquet": _rows_parquet,
}


def _rows_txt_dir(path: Path) -> Iterator[dict[str, Any]]:
    """One record per ``.txt`` file in a directory.

    Closes the loop that ``run --emit-text`` opened: it writes one file per
    (note, operator, severity) as ``{uid}__{op}__{severity}.txt``, and until now
    nothing could read them back, so a user working from emitted text rather
    than from edit scripts could corrupt a corpus and not re-describe it.

    The full stem is the note id, `__` separators included. That keeps every
    cell distinct — three severities of one note are three records, not one
    read three times — and it keeps the reader dumb: parsing the operator and
    severity back out would be inventing a schema the filename does not
    guarantee. ``describe --run`` is the path that knows about cells.

    Sorted, so a directory listing's order does not reach the output.
    """
    for file in sorted(path.glob("*.txt")):
        yield {"note_id": file.stem, "text": file.read_text(encoding="utf-8")}


def read_records(path: Path, *, limit: int | None = None) -> tuple[list[Record], ColumnMap]:
    """Read ``(note_id, text)`` records, plus the resolved column mapping."""
    if path.is_dir():
        return _read_txt_dir(path, limit=limit)
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise CorpusError(
            f"unsupported corpus format {path.suffix!r}; expected one of "
            f"{sorted(READERS)}, or a directory of .txt files"
        )
    rows = reader(path)
    try:
        first = next(iter(rows))
    except StopIteration:
        raise CorpusError(f"{path} contains no rows") from None
    mapping = ColumnMap.resolve(list(first.keys()))

    records: list[Record] = []
    for row in (first, *rows):
        text = row.get(mapping.text)
        if not text:
            continue
        records.append(
            Record(
                note_id=str(row[mapping.note_id]),
                text=str(text),
                patient_id=(
                    str(row[mapping.patient_id])
                    if mapping.patient_id and row.get(mapping.patient_id) is not None
                    else None
                ),
                timestamp=(
                    str(row[mapping.timestamp])
                    if mapping.timestamp and row.get(mapping.timestamp) is not None
                    else None
                ),
            )
        )
        if limit is not None and len(records) >= limit:
            break
    return records, mapping


def _read_txt_dir(path: Path, *, limit: int | None) -> tuple[list[Record], ColumnMap]:
    records: list[Record] = []
    for row in _rows_txt_dir(path):
        if not row["text"]:
            continue
        records.append(Record(note_id=str(row["note_id"]), text=str(row["text"])))
        if limit is not None and len(records) >= limit:
            break
    if not records:
        raise CorpusError(f"{path} contains no readable .txt files")
    return records, ColumnMap(note_id="filename", text="file contents")


def select_records(
    records: Sequence[Record],
    *,
    n: int | None = None,
    fraction: Fraction | None = None,
    salt: str = "rep0",
) -> tuple[Record, ...]:
    """Choose which notes to corrupt, reproducibly and nestedly.

    **Not ``--limit``, and the difference matters.** ``--limit`` takes the first
    N rows of the file, which is a smoke test: it correlates with whatever the
    file is sorted by — admission date, service, note type — so any result over
    it is a result about the head of a file. This is a hash-rank sample over the
    whole corpus, the same mechanism :func:`robustehr.rng.select` uses for units
    within a note, and it has the same two properties:

    * **reproducible** — the same corpus and salt give the same notes, on any
      machine, with no state carried between runs;
    * **nested** — ``fraction=0.25`` selects a subset of ``fraction=0.50``, so a
      corpus-size sweep is paired rather than mixing sample size with sampling
      noise. That is the same reason severity ladders nest one level down.

    Returned in corpus order, not rank order, so downstream output reads in the
    order the file does.
    """
    if n is not None and fraction is not None:
        raise CorpusError("document selection takes n or fraction, not both")
    if not records:
        return ()
    if n is None and fraction is None:
        return tuple(records)
    if fraction is not None:
        if not 0 <= fraction <= 1:
            raise CorpusError(f"fraction must be in [0, 1], got {fraction}")
        # Exact integer arithmetic, ceiling — the same `SubUnitPolicy.CEIL`
        # convention severities use, so `fraction: 0.01` on 50 notes selects one
        # rather than silently selecting none.
        wanted = -((-fraction.numerator * len(records)) // fraction.denominator)
    else:
        # Narrowed by the two guards above: n and fraction are not both set,
        # and not both None.
        n = n or 0
        if n < 0:
            raise CorpusError(f"n must be non-negative, got {n}")
        wanted = n
    wanted = min(wanted, len(records))
    if wanted == len(records):
        return tuple(records)

    keyed = sorted(
        records,
        key=lambda r: (
            hashlib.blake2b(f"{salt}\x1fdocument\x1f{r.note_id}".encode(), digest_size=16).digest(),
            r.note_id,
        ),
    )
    chosen = {r.note_id for r in keyed[:wanted]}
    return tuple(r for r in records if r.note_id in chosen)


def read_documents(path: Path, *, limit: int | None = None) -> Iterator[Document]:
    """Read and segment a corpus.

    Notes that are not in NFC are reported and skipped rather than normalized:
    silently rewriting the input would make every offset in the output refer to
    text the user does not have.
    """
    records, _ = read_records(path, limit=limit)
    for record in records:
        yield Document.from_text(record.text, uid=record.note_id)


__all__ = [
    "ALIASES",
    "ColumnMap",
    "CorpusError",
    "Record",
    "read_documents",
    "read_records",
    "select_records",
]
