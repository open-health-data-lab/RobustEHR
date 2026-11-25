"""Targeting: what gets corrupted, and the canon that feeds the seed."""

from __future__ import annotations

import json

import pytest

from robustehr.document import Document
from robustehr.lexicon import DEFAULT_LEXICON, load_clinical_lexicon
from robustehr.ops.base import Scope
from robustehr.target import (
    EVERYTHING,
    AllOf,
    AnyOf,
    Categories,
    Everything,
    Lexical,
    Not,
    SemanticTypes,
    Structure,
    TargetContext,
    Uncategorized,
    describe,
    parse,
)
from robustehr.types import ProtectionClass, Span, TargetMode


@pytest.fixture
def lexicon(tmp_path):
    path = tmp_path / "clinical_tokens.txt"
    path.write_text(
        "\n".join(
            [
                "warfarin\tT121\tspecific",
                "lisinopril\tT121\tspecific",
                "hypertension\tT047\tspecific",
                "pneumonia\tT047\tspecific",
                "dyspnea\tT184\tspecific",
                "chest\tT029\tspecific",
            ]
        ),
        encoding="utf-8",
    )
    path.with_suffix(".manifest.json").write_text(
        json.dumps({"umls_release": "2026AA"}), encoding="utf-8"
    )
    return load_clinical_lexicon(path)


@pytest.fixture
def ctx(lexicon):
    doc = Document.from_text(
        "Started warfarin for hypertension with dyspnea and chest tightness.\n", uid="t"
    )
    return TargetContext(doc=doc, lexicon=lexicon)


def word(ctx: TargetContext, text: str) -> Span:
    token = next(t for t in ctx.doc.tokens if t.lower == text)
    return token.span


# -- selection --------------------------------------------------------------


def test_categories_select_only_their_kind(ctx):
    assert Categories("medication").admits(word(ctx, "warfarin"), ctx)
    assert not Categories("medication").admits(word(ctx, "hypertension"), ctx)
    assert Categories("disease").admits(word(ctx, "hypertension"), ctx)
    assert not Categories("disease").admits(word(ctx, "dyspnea"), ctx)
    assert Categories("symptom").admits(word(ctx, "dyspnea"), ctx)


def test_categories_union_across_names(ctx):
    both = Categories("medication", "disease")
    assert both.admits(word(ctx, "warfarin"), ctx)
    assert both.admits(word(ctx, "hypertension"), ctx)


def test_unknown_category_fails_before_the_run(ctx):
    """A typo in a target must not silently select nothing."""
    with pytest.raises(ValueError, match="unknown semantic categor"):
        Categories("medicaton")


def test_semantic_types_allow_finer_control(ctx):
    assert SemanticTypes("T047").admits(word(ctx, "hypertension"), ctx)
    assert not SemanticTypes("T047").admits(word(ctx, "warfarin"), ctx)


def test_uncategorized_is_the_complement(ctx):
    assert Uncategorized().admits(word(ctx, "with"), ctx)
    assert not Uncategorized().admits(word(ctx, "warfarin"), ctx)


def test_uncategorized_admits_nothing_without_a_vocabulary(ctx):
    """Absence of evidence must not become evidence of absence.

    With no terminology installed nothing can be categorized, so treating
    everything as uncategorized would silently turn "we could not look" into
    "we looked and found nothing".
    """
    blind = TargetContext(doc=ctx.doc, lexicon=DEFAULT_LEXICON)
    assert not Uncategorized().admits(word(blind, "with"), blind)
    assert not Uncategorized().admits(word(blind, "warfarin"), blind)


def test_not_inverts(ctx):
    target = Not(Categories("disease"))
    assert target.admits(word(ctx, "warfarin"), ctx)
    assert not target.admits(word(ctx, "hypertension"), ctx)


def test_all_of_and_any_of(ctx):
    assert AnyOf(Categories("medication"), Categories("disease")).admits(word(ctx, "warfarin"), ctx)
    assert not AllOf(Categories("medication"), Categories("disease")).admits(
        word(ctx, "warfarin"), ctx
    )


def test_everything_admits_everything(ctx):
    assert Everything().admits(word(ctx, "with"), ctx)
    assert Everything().admits(Span(0, 1), ctx)


# -- canon, which feeds the seed -------------------------------------------


def test_canon_is_order_independent():
    """Logically identical targets must be textually identical.

    Canon feeds the BLAKE2b seed, so two spellings of the same target would
    otherwise select different units.
    """
    assert (
        Categories("disease", "medication").canon() == Categories("medication", "disease").canon()
    )
    assert (
        AnyOf(Categories("disease"), Categories("medication")).canon()
        == AnyOf(Categories("medication"), Categories("disease")).canon()
    )


def test_canon_deduplicates():
    assert Categories("disease", "disease").canon() == Categories("disease").canon()


def test_canon_shapes():
    assert Categories("medication").canon() == "cat=medication"
    assert SemanticTypes("T047").canon() == "tui=T047"
    assert Uncategorized().canon() == "uncategorized"
    assert Not(Categories("disease")).canon() == "not(cat=disease)"
    assert EVERYTHING.canon() == "all"


def test_scope_canon_is_unchanged_without_a_target():
    """Adding targeting must not invalidate previously recorded edit scripts.

    A run with no target has to produce the canon it always did, therefore the
    same seed, therefore the same edits.
    """
    assert Scope().canon() == "target=all|pheno=agnostic"
    assert "sel=" not in Scope().canon()


def test_scope_canon_records_the_target():
    assert Scope(target=Categories("medication")).canon().endswith("|sel=cat=medication")


def test_legacy_target_mode_still_resolves():
    """`target_mode` keeps working for one release, mapped honestly.

    NONCLINICAL_ONLY always meant "in no category", not "determined to be
    non-clinical", so that is what it maps to.
    """
    resolved = Scope(target_mode=TargetMode.NONCLINICAL_ONLY).resolved_target()
    assert isinstance(resolved, Uncategorized)
    assert isinstance(Scope().resolved_target(), Everything)


def test_section_folds_into_the_resolved_target():
    resolved = Scope(section="assessment", target=Categories("disease")).resolved_target()
    assert isinstance(resolved, AllOf)
    assert {t.canon() for t in resolved.targets} == {"cat=disease", "section=assessment"}


# -- parsing and description -----------------------------------------------


@pytest.mark.parametrize(
    "spec",
    ["all", "uncategorized", "cat=medication", "cat=disease,medication", "tui=T047", "section=hpi"],
)
def test_parse_round_trips_through_canon(spec):
    parsed = parse(spec)
    assert parse(parsed.canon()).canon() == parsed.canon()


def test_parse_rejects_nonsense():
    with pytest.raises(ValueError, match="unrecognized target"):
        parse("medications please")
    with pytest.raises(ValueError, match="unknown target key"):
        parse("colour=blue")


def test_parse_structure():
    target = parse("struct=deid_placeholder,section_header")
    assert isinstance(target, Structure)
    assert ProtectionClass.DEID_PLACEHOLDER in target.classes
    assert ProtectionClass.SECTION_HEADER in target.classes


def test_parse_rejects_an_unknown_protection_class():
    with pytest.raises(ValueError, match="deid"):
        parse("struct=deid")


def test_describe_is_readable():
    assert describe(Categories("medication")) == "units carrying medications"
    assert "control" in describe(Uncategorized())
    assert describe(EVERYTHING) == "every eligible unit"


# -- the lexical axis -------------------------------------------------------


def test_lexical_target_needs_no_terminology(ctx):
    """The one content target that works with no vocabulary installed."""
    blind = TargetContext(doc=ctx.doc, lexicon=DEFAULT_LEXICON)
    assert Lexical("function_word").admits(word(blind, "with"), blind)
    assert not Lexical("function_word").admits(word(blind, "warfarin"), blind)


def test_lexical_classes_separate_grammar_from_content(ctx):
    assert Lexical("function_word").admits(word(ctx, "with"), ctx)
    assert not Lexical("general_english").admits(word(ctx, "with"), ctx)
    assert Lexical("out_of_vocabulary").admits(word(ctx, "warfarin"), ctx)


def test_lexical_rejects_an_unknown_class():
    with pytest.raises(ValueError, match="unknown lexical class"):
        Lexical("stopword")


def test_lexical_canon_and_parse():
    assert Lexical("function_word").canon() == "lex=function_word"
    assert parse("lex=function_word").canon() == "lex=function_word"


def test_lexical_and_category_compose(ctx):
    """The suspect zone: ordinary English that a terminology also claims."""
    suspect = AllOf(Categories("medication"), Lexical("general_english"))
    assert not suspect.admits(word(ctx, "warfarin"), ctx)
