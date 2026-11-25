"""Persisting a run, and reproducing it from what was persisted.

This module is what makes the work publishable. 1.2 GB of corrupted MIMIC-IV
notes cannot be redistributed under the PhysioNet data use agreement, but **edit
scripts can**, because an edit is an offset pair plus a short replacement string
— a few characters of clinical text at most, and usually none at all for the
structural operators.

So the released artifact is edits, dose tables and hashes; a reader with their
own licensed copy of the corpus runs ``robustehr replay`` and reconstructs every
corrupted byte, with each note's ``output_sha256`` checked against the recorded
value. Determinism is what makes that substitution lossless rather than
approximate.

Three honesty constraints are enforced here rather than left to discipline:

* **No span of a note is copied into the script.** A replacement string is
  bounded by :data:`MAX_REPLACEMENT_CHARS`, and writing refuses on anything
  longer. An operator that needed to emit a whole paragraph would be a
  redistribution channel wearing an edit script's clothes.
* **A replacement is stored as its minimal difference.** An operator that
  retypes a word proposes the whole word, one letter changed. Stored as
  proposed, a typo arm at 15% of words would write 15% of the note's words into
  the script, each one letter off. :func:`minimal_edit` strips the characters
  the replacement shares with what it replaces, so the script keeps the changed
  position and the new character and nothing else. The stored edits reproduce
  the same bytes, which :func:`write_run` checks cell by cell before writing.
* **What remains is still derived from the corpus, and the docs say so.** An
  offset says where a word was; a brand name written over a generic says which
  drug stood there. See ``docs/run-artifact.md`` for what each operator's
  replacement implies about its source.
* **Parquet container bytes are not claimed reproducible.** Compression metadata
  and thread counts leak into them. Per-record SHA-256 makes content verifiable
  regardless of container, which is the honest form of the claim.
"""

from __future__ import annotations

import json
import platform
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from robustehr.dose import DoseRecord
from robustehr.edits import apply_edits
from robustehr.rng import sha256_text
from robustehr.types import Anchor, Edit, ProtectionClass, ReflowPolicy, Span
from robustehr.version import SCHEMA_VERSION, __version__

#: Longest replacement string an edit may carry into the store.
#:
#: Not a performance limit. Edit scripts are redistributable *because* they carry
#: offsets rather than text, and that property has to be enforced rather than
#: assumed: without a cap, an operator that replaced whole sentences would turn
#: the artifact into a copy of the corpus.
MAX_REPLACEMENT_CHARS = 120


class RedistributionError(ValueError):
    """An edit carried more text than an edit script is allowed to carry."""


@dataclass(frozen=True, slots=True)
class EditRow:
    """One applied edit, flattened for storage."""

    run_id: str
    note_uid: str
    note_sha256: str
    op_id: str
    """The operator that PROPOSED this edit."""
    cell_id: str
    """The run cell this edit belongs to, which is what replay groups by.

    Identical to :attr:`op_id` for an ordinary run, and different under
    ``--compose``: the cell is ``composite(a+b)`` while each edit still records
    the operator that made it. Keeping both is what lets a reader see the mix
    inside a composite — how many edits each operator actually landed — while
    replay still finds the cell. Collapsing them onto one field would either
    lose the provenance or break the lookup, and it broke the lookup: composite
    cells reconstructed from zero edits and verified 0 of 2.
    """
    op_version: str
    severity: str
    scope: str
    stage_index: int
    edit_id: str
    start: int
    end: int
    replacement: str
    unit_id: str
    rank: int
    op_priority: int
    anchor: int
    reflow: str
    targets: str
    group_id: str | None
    copy_from_start: int | None = None
    """Source range for a copying edit; the reason such an edit is storable.

    A duplication inserts text already present in the note. Carried in
    ``replacement`` it would put clinical text into the edit script and break
    the redistribution guarantee `MAX_REPLACEMENT_CHARS` exists to protect. As
    two offsets it carries none.
    """
    copy_from_end: int | None = None

    @classmethod
    def of(cls, edit: Edit, dose: DoseRecord, source: str | None = None) -> EditRow:
        """Flatten one applied edit. With ``source``, store its minimal difference."""
        if source is not None:
            edit = minimal_edit(edit, source)
        if len(edit.replacement) > MAX_REPLACEMENT_CHARS:
            raise RedistributionError(
                f"{edit.op_id} produced a {len(edit.replacement)}-character replacement, "
                f"over the {MAX_REPLACEMENT_CHARS} limit. Edit scripts are "
                "redistributable only because they carry offsets rather than text."
            )
        return cls(
            run_id=dose.run_id,
            note_uid=dose.note_uid,
            note_sha256=dose.note_sha256,
            op_id=edit.op_id,
            cell_id=dose.op_id,
            op_version=dose.op_version,
            severity=dose.severity_canon,
            scope=dose.scope_canon,
            stage_index=dose.stage_index,
            edit_id=edit.edit_id,
            start=edit.start,
            end=edit.end,
            replacement=edit.replacement,
            unit_id=edit.unit_id,
            rank=edit.rank,
            op_priority=edit.op_priority,
            anchor=int(edit.anchor),
            reflow=edit.reflow.value,
            targets="|".join(sorted(t.value for t in edit.targets)),
            group_id=edit.group_id,
            copy_from_start=None if edit.copy_from is None else edit.copy_from.start,
            copy_from_end=None if edit.copy_from is None else edit.copy_from.end,
        )

    def to_edit(self) -> Edit:
        return Edit(
            start=self.start,
            end=self.end,
            replacement=self.replacement,
            op_id=self.op_id,
            unit_id=self.unit_id,
            rank=self.rank,
            op_priority=self.op_priority,
            anchor=Anchor(self.anchor),
            reflow=ReflowPolicy(self.reflow),
            group_id=self.group_id,
            targets=frozenset(ProtectionClass(t) for t in self.targets.split("|") if t),
            copy_from=(
                None
                if self.copy_from_start is None or self.copy_from_end is None
                else Span(self.copy_from_start, self.copy_from_end)
            ),
        )


def minimal_edit(edit: Edit, source: str) -> Edit:
    """The same change with the characters it does not change stripped off.

    ``source`` is the note the edit was proposed against. The common prefix and
    suffix of the replaced text and its replacement are removed and the offsets
    moved inwards to match, so ``hypertension -> hupertension`` over twelve
    characters becomes ``y -> u`` over one.

    Left as proposed when trimming could change what applying it produces: a
    copying edit, whose text is offsets already; a reflowed edit, whose wrapping
    depends on the whole replacement; and a change that would trim to a pure
    insertion, which orders differently against a neighbouring edit.
    """
    if edit.copy_from is not None or edit.reflow is not ReflowPolicy.VERBATIM:
        return edit
    old, new = source[edit.start : edit.end], edit.replacement
    limit = min(len(old), len(new))
    head = 0
    while head < limit and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < limit - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    if head + tail >= len(old):
        # Nothing of the original span would be left to replace. Keep one
        # character of it so the edit stays a replacement.
        if head:
            head -= 1
        elif tail:
            tail -= 1
    if not head and not tail:
        return edit
    return replace(
        edit,
        start=edit.start + head,
        end=edit.end - tail,
        replacement=new[head : len(new) - tail],
    )


def environment() -> dict[str, str]:
    """What produced this run, for the manifest.

    Recorded so a reproduction mismatch can be diagnosed rather than merely
    observed. None of it feeds the seed — that is the point of the determinism
    design — but knowing which Python built an artifact is worth having when a
    hash disagrees.
    """
    return {
        "robustehr": __version__,
        "schema_version": SCHEMA_VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def write_run(
    path: Path,
    *,
    run_id: str,
    doses: Sequence[DoseRecord],
    edits: Sequence[Sequence[Edit]],
    corpus: str,
    extra: dict[str, Any] | None = None,
    texts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Write dose records, edit scripts and a manifest.

    ``edits[i]`` are the applied edits for ``doses[i]``. JSONL rather than
    Parquet for the edit table: it is byte-reproducible, which Parquet is not,
    and the whole value of this artifact is that a reader can verify it.

    ``texts`` maps ``note_uid`` to the note each cell was run on. With it, every
    replacement is stored as its minimal difference (:func:`minimal_edit`), and
    only after the trimmed edits have been applied and found to give the cell's
    recorded ``output_sha256``; a cell that does not reproduce is stored as
    proposed. Without it nothing can be trimmed, and the manifest says which
    happened under ``replacement_form``.
    """
    if len(doses) != len(edits):
        raise ValueError(f"{len(doses)} dose records against {len(edits)} edit lists")
    path.mkdir(parents=True, exist_ok=True)

    dose_rows = [d.to_row() for d in doses]
    edit_rows: list[dict[str, Any]] = []
    as_proposed = 0
    for dose, group in zip(doses, edits, strict=True):
        source = None if texts is None else texts.get(dose.note_uid)
        rows = [EditRow.of(edit, dose, source) for edit in group]
        if source is not None and rows:
            rebuilt = apply_edits(source, tuple(r.to_edit() for r in rows))
            if sha256_text(rebuilt.text) != dose.output_sha256:
                rows = [EditRow.of(edit, dose) for edit in group]
                as_proposed += 1
        elif rows:
            as_proposed += 1
        edit_rows.extend(asdict(r) for r in rows)
    replacement_chars: dict[str, int] = {}
    for row in edit_rows:
        replacement_chars[row["op_id"]] = replacement_chars.get(row["op_id"], 0) + len(
            row["replacement"]
        )

    dose_text = "\n".join(json.dumps(r, sort_keys=True, default=str) for r in dose_rows)
    edit_text = "\n".join(json.dumps(r, sort_keys=True, default=str) for r in edit_rows)
    (path / "dose.jsonl").write_text(dose_text + "\n", encoding="utf-8")
    (path / "edits.jsonl").write_text(edit_text + "\n", encoding="utf-8")

    manifest = {
        "run_id": run_id,
        "corpus": corpus,
        "environment": environment(),
        "notes": len({d.note_uid for d in doses}),
        "cells": len(doses),
        "edits": len(edit_rows),
        "dose_sha256": sha256_text(dose_text),
        "edits_sha256": sha256_text(edit_text),
        "resource_digests": dict(sorted(doses[0].resource_digests.items())) if doses else {},
        # No span of a note is copied into the script. What a replacement
        # still implies about the text it replaced is in docs/run-artifact.md.
        "contains_note_text": False,
        "max_replacement_chars": MAX_REPLACEMENT_CHARS,
        "replacement_form": (
            "as_proposed"
            if texts is None
            else ("minimal_diff" if not as_proposed else "minimal_diff_with_exceptions")
        ),
        "cells_stored_as_proposed": as_proposed,
        "replacement_chars_by_operator": dict(sorted(replacement_chars.items())),
        **(extra or {}),
    }
    (path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def read_edits(path: Path) -> list[EditRow]:
    """Read an edit script, tolerating scripts written before ``cell_id`` existed.

    An edit script written without ``cell_id`` is read with the operator as the
    cell, which is what the cell was. Defaulting rather than failing keeps every
    already-published edit script replayable.
    """
    lines = (path / "edits.jsonl").read_text(encoding="utf-8").splitlines()
    rows = []
    for line in lines:
        if not line.strip():
            continue
        raw = json.loads(line)
        raw.setdefault("cell_id", raw["op_id"])
        rows.append(EditRow(**raw))
    return rows


def read_doses(path: Path) -> list[dict[str, Any]]:
    lines = (path / "dose.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Outcome of reconstructing one cell from its stored edit script."""

    note_uid: str
    op_id: str
    severity: str
    expected_sha256: str
    actual_sha256: str

    @property
    def verified(self) -> bool:
        return self.expected_sha256 == self.actual_sha256


def replay(
    path: Path,
    texts: dict[str, str],
) -> list[ReplayResult]:
    """Reconstruct every stored cell from its edits and check the hashes.

    ``texts`` maps ``note_uid`` to the reader's own copy of the note. Notes not
    supplied are skipped rather than failed: a partial corpus is a normal
    situation, and reporting a false mismatch for a note nobody has would make
    the check useless.
    """
    by_cell: dict[tuple[str, str, str, str], list[EditRow]] = {}
    for row in read_edits(path):
        by_cell.setdefault((row.note_uid, row.cell_id, row.severity, row.scope), []).append(row)

    expected = {
        (str(d["note_uid"]), str(d["op_id"]), str(d["severity"]), str(d["scope"])): str(
            d["output_sha256"]
        )
        for d in read_doses(path)
    }

    results = []
    for cell, want in sorted(expected.items()):
        note_uid = cell[0]
        if note_uid not in texts:
            continue
        rows = by_cell.get(cell, [])
        applied = apply_edits(texts[note_uid], tuple(r.to_edit() for r in rows))
        results.append(
            ReplayResult(
                note_uid=note_uid,
                op_id=cell[1],
                severity=cell[2],
                expected_sha256=want,
                actual_sha256=sha256_text(applied.text),
            )
        )
    return results


def verify_note_hashes(path: Path, texts: dict[str, str]) -> list[str]:
    """Confirm the reader's corpus is the one the run was produced from.

    Returns the uids that disagree. Checking this before replay turns "your
    output does not match" into "your input does not match", which is a
    different problem with a different fix.
    """
    mismatched = []
    seen: set[str] = set()
    for dose in read_doses(path):
        uid = str(dose["note_uid"])
        if uid in seen or uid not in texts:
            continue
        seen.add(uid)
        if sha256_text(texts[uid]) != str(dose["note_sha256"]):
            mismatched.append(uid)
    return sorted(mismatched)


def iter_texts(records: Iterable[Any]) -> dict[str, str]:
    """Build the uid → text map ``replay`` expects from corpus records."""
    return {r.note_id: r.text for r in records}


__all__ = [
    "MAX_REPLACEMENT_CHARS",
    "EditRow",
    "RedistributionError",
    "ReplayResult",
    "environment",
    "iter_texts",
    "minimal_edit",
    "read_doses",
    "read_edits",
    "replay",
    "verify_note_hashes",
    "write_run",
]
