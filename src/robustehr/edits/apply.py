"""Conflict resolution and application of an edit script.

Operators propose; this module disposes. It is the only place in the package
that produces perturbed text, which is what makes composition well-defined:
every operator emits edits against the same coordinate system and never sees
another operator's output.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from robustehr.edits.align import Alignment, AlignmentBuilder
from robustehr.types import Edit, ReflowPolicy


class RejectionReason(StrEnum):
    OVERLAP = "overlap"
    GROUP_MEMBER_REJECTED = "group_member_rejected"
    REFLOW_VIOLATION = "reflow_violation"
    OUT_OF_BOUNDS = "out_of_bounds"
    NO_CHANGE = "no_change"


@dataclass(frozen=True, slots=True)
class RejectedEdit:
    edit: Edit
    reason: RejectionReason
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ApplyResult:
    text: str
    alignment: Alignment
    applied: tuple[Edit, ...]
    rejected: tuple[RejectedEdit, ...]
    chars_removed: int
    chars_added: int
    edit_cost: int
    lines_added: int
    lines_removed: int
    rejection_counts: dict[str, int] = field(default_factory=dict)

    @property
    def unchanged(self) -> bool:
        return not self.applied


def levenshtein(a: str, b: str) -> int:
    """Edit distance between two short strings.

    Only ever called on the source and replacement of a single edit — a word, a
    header, a sentence — never on whole documents. Whole-document Levenshtein
    over a 100k-cell sweep would be ~10^13 cell updates; the edit script's
    induced alignment makes it unnecessary.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (ca != cb),
                )
            )
        previous = current
    return previous[-1]


def _reflow_violation(edit: Edit, source: str, replacement: str) -> str | None:
    """Check an edit against its declared line-structure contract.

    ``PRESERVE`` is the default precisely so that an operator has to *opt in* to
    changing line structure. Without this check a sentence-level rewrite on
    hard-wrapped text silently doubles as a structure-flattening corruption, and
    any claim that the operator's effect was isolated is false.
    """
    match edit.reflow:
        case ReflowPolicy.FLATTEN:
            return None
        case ReflowPolicy.PRESERVE:
            src_lines = source.count("\n")
            dst_lines = replacement.count("\n")
            if src_lines != dst_lines:
                return (
                    f"reflow=PRESERVE but newline count changed "
                    f"({src_lines} -> {dst_lines}); declare FLATTEN if intended"
                )
            return None
        case ReflowPolicy.VERBATIM:
            if "\n" in source or "\n" in replacement:
                return "reflow=VERBATIM is only valid for single-line spans"
            return None
    raise AssertionError(f"unhandled reflow policy {edit.reflow!r}")  # pragma: no cover


def _group_items(edits: Sequence[Edit]) -> list[tuple[tuple, list[Edit]]]:
    """Bundle grouped edits into atomic items, ordered by their first member.

    A ``group_id`` marks an all-or-nothing set: an operator that must make three
    coordinated changes (say, a cue rewrite plus two agreement fixes) cannot be
    allowed to land one of them.
    """
    singles: list[tuple[tuple, list[Edit]]] = []
    groups: dict[str, list[Edit]] = {}
    for edit in edits:
        if edit.group_id is None:
            singles.append((edit.sort_key, [edit]))
        else:
            groups.setdefault(edit.group_id, []).append(edit)
    items = singles
    for members in groups.values():
        members.sort(key=lambda e: e.sort_key)
        items.append((members[0].sort_key, members))
    items.sort(key=lambda item: item[0])
    return items


def _check(  # noqa: PLR0911 - one return per named rejection reason
    edit: Edit, text: str, accepted: Sequence[Edit], siblings: Sequence[Edit]
) -> RejectedEdit | None:
    """Validate one edit against the document and everything already accepted."""
    if edit.end > len(text):
        return RejectedEdit(
            edit,
            RejectionReason.OUT_OF_BOUNDS,
            f"end={edit.end} exceeds document length {len(text)}",
        )
    if edit.copy_from is not None and edit.copy_from.end > len(text):
        return RejectedEdit(
            edit,
            RejectionReason.OUT_OF_BOUNDS,
            f"copy_from end={edit.copy_from.end} exceeds document length {len(text)}",
        )
    source = text[edit.start : edit.end]
    replacement = edit.text_for(text)
    if source == replacement:
        return RejectedEdit(edit, RejectionReason.NO_CHANGE)
    violation = _reflow_violation(edit, source, replacement)
    if violation is not None:
        return RejectedEdit(edit, RejectionReason.REFLOW_VIOLATION, violation)
    if any(edit.conflicts_with(other) for other in accepted):
        return RejectedEdit(edit, RejectionReason.OVERLAP)
    if any(edit.conflicts_with(other) for other in siblings if other is not edit):
        return RejectedEdit(edit, RejectionReason.OVERLAP, "conflicts within its own group")
    return None


def resolve(text: str, proposals: Sequence[Edit]) -> tuple[list[Edit], list[RejectedEdit]]:
    """Decide which proposals land, greedily in canonical total order.

    The first edit to claim a range wins; later overlapping proposals are
    rejected with a reason. Because the order is total and content-derived, the
    outcome does not depend on the order operators ran in, on worker count, or
    on dict iteration. Grouped edits are all-or-nothing.
    """
    accepted: list[Edit] = []
    rejected: list[RejectedEdit] = []

    for _key, members in _group_items(proposals):
        problems = [
            problem
            for edit in members
            if (problem := _check(edit, text, accepted, members)) is not None
        ]
        if problems:
            reasons = {p.edit.edit_id: p for p in problems}
            rejected.extend(
                reasons.get(edit.edit_id, RejectedEdit(edit, RejectionReason.GROUP_MEMBER_REJECTED))
                for edit in members
            )
            continue
        accepted.extend(members)

    accepted.sort(key=lambda e: e.sort_key)
    return accepted, rejected


def apply_edits(text: str, edits: Iterable[Edit]) -> ApplyResult:
    """Resolve conflicts, apply the survivors, and emit the alignment map."""
    accepted, rejected = resolve(text, list(edits))

    out: list[str] = []
    builder = AlignmentBuilder()
    cursor = 0  # position in the source
    written = 0  # position in the output
    chars_removed = 0
    chars_added = 0
    edit_cost = 0
    lines_before = 0
    lines_after = 0

    for edit in accepted:
        if edit.start > cursor:
            run = text[cursor : edit.start]
            out.append(run)
            builder.add_run(cursor, written, len(run))
            written += len(run)
            cursor = edit.start
        source = text[edit.start : edit.end]
        replacement = edit.text_for(text)
        out.append(replacement)
        written += len(replacement)
        cursor = max(cursor, edit.end)
        chars_removed += len(source)
        chars_added += len(replacement)
        edit_cost += levenshtein(source, replacement)
        lines_before += source.count("\n")
        lines_after += replacement.count("\n")

    if cursor < len(text):
        run = text[cursor:]
        out.append(run)
        builder.add_run(cursor, written, len(run))
        written += len(run)

    result_text = "".join(out)
    counts: dict[str, int] = {}
    for item in rejected:
        counts[item.reason.value] = counts.get(item.reason.value, 0) + 1

    return ApplyResult(
        text=result_text,
        alignment=builder.build(len(text), len(result_text)),
        applied=tuple(accepted),
        rejected=tuple(rejected),
        chars_removed=chars_removed,
        chars_added=chars_added,
        edit_cost=edit_cost,
        lines_added=lines_after,
        lines_removed=lines_before,
        rejection_counts=counts,
    )


__all__ = [
    "ApplyResult",
    "RejectedEdit",
    "RejectionReason",
    "apply_edits",
    "levenshtein",
]
