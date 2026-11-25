"""The P1 RENDER operators added after the structural layer settled."""

from __future__ import annotations

import pytest

from robustehr import kappa
from robustehr.document import Document
from robustehr.ops import registry
from robustehr.protect import protect_document
from robustehr.runner import apply_operator, severity_ladder
from robustehr.types import Contract

registry.register_builtins()
FULL = severity_ladder("1")[0]

LAB_NOTE = "LABS:\nNa    140    K     4.1\nCr    0.9    Hgb   12.2\n"
LIST_NOTE = "ASSESSMENT:\n1.  Pneumonia, treated.\n2.  Hypertension, stable.\n"
HEADER_NOTE = "HISTORY OF PRESENT ILLNESS:\nPatient reports dyspnea.\n\nFAMILY HISTORY:\nMother has diabetes.\n"


def run(op_id: str, text: str, severity=FULL):
    op = registry.get(op_id)()
    doc = Document.from_text(text, uid="t")
    return doc, apply_operator(doc, op, op.meta, severity)


# -- lab_block_collapse -----------------------------------------------------


def test_lab_collapse_removes_column_padding():
    _, result = run("render.lab_block_collapse", LAB_NOTE)
    assert result.changed
    assert "Na 140 K 4.1" in result.text
    assert "    " not in result.text


def test_lab_collapse_preserves_content_tokens():
    """Its declared contract, checked directly."""
    doc, result = run("render.lab_block_collapse", LAB_NOTE)
    assert kappa.holds("content_tokens", doc.text, result.text)


def test_lab_collapse_works_around_deid_masks():
    """The failure that drove the design to per-run units.

    Masks are HARD-protected, so a whole-line edit partially overlaps a
    protected span and is refused. An early version was eligible on 3 lines in
    60 notes for exactly this reason.
    """
    text = "Name:  ___                    Unit No:   ___\n"
    _, result = run("render.lab_block_collapse", text)
    assert result.dose.eligible_n > 0
    assert result.text.count("___") == 2


def test_lab_collapse_is_narrower_than_whitespace_collapse():
    """Different denominators, because they answer different questions.

    `whitespace_collapse` counts every space run in the note; this one counts
    only runs inside a detected aligned block. Conflating them would make "30%"
    mean two different things.
    """
    text = "The patient was seen   today.\nFollow up   in a week.\n"
    _, lab = run("render.lab_block_collapse", text)
    _, allws = run("render.whitespace_collapse", text)
    assert allws.dose.total_n > 0
    assert lab.dose.total_n < allws.dose.total_n


# -- bullet_to_prose --------------------------------------------------------


def test_markers_are_removed_and_content_kept():
    _, result = run("render.bullet_to_prose", LIST_NOTE)
    assert "Pneumonia, treated." in result.text
    assert "1." not in result.text


def test_marker_removal_takes_its_trailing_space():
    """Otherwise the residue reads as column alignment to the block detector."""
    _, result = run("render.bullet_to_prose", LIST_NOTE)
    assert "  Pneumonia" not in result.text


def test_bullet_to_prose_preserves_prose_but_not_content_tokens():
    """The projection has to be the narrower one, and here is why.

    A numbered marker tokenizes as a number, which counts as content, so
    `content_tokens` genuinely changes when the marker goes. What survives is
    the prose, and that is what the declared projection compares.
    """
    doc, result = run("render.bullet_to_prose", LIST_NOTE)
    assert kappa.holds("content_tokens_without_list_markers", doc.text, result.text)
    assert not kappa.holds("content_tokens", doc.text, result.text)


# -- header_delete ----------------------------------------------------------


def test_header_delete_removes_the_header_not_the_content():
    _, result = run("render.header_delete", HEADER_NOTE)
    assert result.changed
    assert "Mother has diabetes." in result.text
    assert "FAMILY HISTORY:" not in result.text


def test_header_delete_is_conditionally_preserving_not_invariant():
    """The distinction that makes this operator worth having.

    Deleting `Family History:` changes no content token, yet it merges the
    experiencer scope of what follows into the surrounding narrative — the
    diabetes stops belonging to the mother. Content survives; reference does
    not. Claiming INVARIANT_BY_CONSTRUCTION here would be false.
    """
    op = registry.get("render.header_delete")()
    assert op.meta.contract is Contract.CONDITIONALLY_PRESERVING
    assert op.meta.canonicalizer is None


def test_header_delete_skips_inline_headers():
    """Deleting the line would take the value with it."""
    text = "Chief Complaint: chest pain\n"
    _, result = run("render.header_delete", text)
    assert result.dose.eligible_n == 0
    assert "chest pain" in result.text


# -- shared ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op_id", "text"),
    [
        ("render.lab_block_collapse", LAB_NOTE),
        ("render.bullet_to_prose", LIST_NOTE),
        ("render.header_delete", HEADER_NOTE),
    ],
)
def test_no_edit_partially_overlaps_a_hard_protected_span(op_id, text):
    doc, result = run(op_id, text)
    index = protect_document(doc)
    op = registry.get(op_id)()
    for edit in result.apply_result.applied:
        assert not index.blocks(edit.span, op.meta.targets), edit


@pytest.mark.parametrize(
    ("op_id", "text"),
    [
        ("render.lab_block_collapse", LAB_NOTE),
        ("render.bullet_to_prose", LIST_NOTE),
        ("render.header_delete", HEADER_NOTE),
    ],
)
def test_severity_ladders_nest(op_id, text):
    """sel(.10) subset of sel(.50) subset of sel(1) — a framework guarantee."""
    selected = []
    for severity in severity_ladder("0.10", "0.50", "1"):
        _, result = run(op_id, text, severity)
        selected.append({e.span for e in result.apply_result.applied})
    assert selected[0] <= selected[1] <= selected[2]


@pytest.mark.parametrize(
    ("op_id", "text"),
    [
        ("render.lab_block_collapse", LAB_NOTE),
        ("render.bullet_to_prose", LIST_NOTE),
        ("render.header_delete", HEADER_NOTE),
    ],
)
def test_reruns_are_identical(op_id, text):
    first = run(op_id, text)[1]
    second = run(op_id, text)[1]
    assert first.text == second.text
    assert first.dose.output_sha256 == second.dose.output_sha256
