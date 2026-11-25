"""The targeting rule Experiment 2 rests on.

Every assertion here corresponds to a measurement in `validation-protocol` §9 or
to a failure that measurement exposed. The rule replaced `Concept()` because
`Concept()` was assumed to mean "clinical" and does not, so a test suite that
only checked it *runs* would repeat the original mistake.
"""

from __future__ import annotations

import pytest

from robustehr import salience
from robustehr.document import Document
from robustehr.drugs import load_synonyms
from robustehr.target import ClinicalSalience, Concept, TargetContext
from robustehr.types import Span


def ctx(text: str) -> tuple[Document, TargetContext]:
    doc = Document.from_text(text, uid="t")
    return doc, TargetContext(doc=doc)


def span_of(doc: Document, text: str, needle: str) -> Span:
    start = text.index(needle)
    return Span(start, start + len(needle))


def admits(rule: ClinicalSalience, text: str, needle: str) -> bool:
    doc, context = ctx(text)
    return rule.admits(span_of(doc, text, needle), context)


# -- the lexicon ----------------------------------------------------------


def test_lexicon_loads_and_is_lowercase_keyed() -> None:
    table = salience.table()
    assert len(table) > 5_000
    assert all(k == k.lower() for k in list(table)[:500])


def test_salience_is_case_folded() -> None:
    """An early evaluation compared original-case tokens against lowercase keys.

    Every capitalised word fell silently to the prior and measured recall dropped
    0.812 -> 0.513 with nothing appearing broken. Case folding is load-bearing.
    """
    assert salience.salience("Hypertension") == salience.salience("hypertension")
    assert salience.salience("HYPERTENSION") == salience.salience("hypertension")


def test_unseen_tokens_sit_at_the_prior_below_every_threshold() -> None:
    """An unseen token must be admitted by evidence, not by absence of it."""
    assert salience.salience("zzzznotaword") == salience.prior()
    assert salience.prior() < salience.DEFAULT_THRESHOLD


@pytest.mark.parametrize(
    "token", ["hypertension", "pneumonia", "dyspnea", "edema", "copd", "delirium"]
)
def test_clinical_terms_score_high(token: str) -> None:
    assert salience.salience(token) >= 0.80


@pytest.mark.parametrize("token", ["she", "he", "patient", "history", "sig", "bid", "please"])
def test_prose_and_scaffolding_score_low(token: str) -> None:
    assert salience.salience(token) < 0.10


def test_manifest_carries_its_corpus_and_digest() -> None:
    """A targeting claim without these is what the first Experiment 2 asserted."""
    m = salience.manifest()
    assert "MIMIC-IV" in m["corpus"]
    assert len(m["sha256"]) == 64
    assert m["notes"] == 272


# -- the target -----------------------------------------------------------

NOTE = (
    "History of Present Illness:\n"
    "She was admitted with hypertension and delirium. "
    "Please continue metoprolol at home today.\n"
    "Amylase-1166 Lipase-1828 Hct-35.1\n"
)


def test_selects_diagnoses() -> None:
    rule = ClinicalSalience()
    assert admits(rule, NOTE, "hypertension")
    assert admits(rule, NOTE, "delirium")


@pytest.mark.parametrize("word", ["She", "Please", "admitted", "today", "home"])
def test_rejects_prose(word: str) -> None:
    assert not admits(ClinicalSalience(), NOTE, word)


def test_rejects_the_section_header() -> None:
    """Header spans are matcher mentions, so `Concept()` admits them.

    Corrupting them under the label "concept-targeted" confounds Experiment 2
    with Experiment 1's structural arms — a design failure, not a precision one.
    """
    assert not admits(ClinicalSalience(), NOTE, "History of Present Illness")


@pytest.mark.skipif(
    not load_synonyms(),
    reason="drug_synonyms.json not built; run validation/pipeline/scripts/build_drug_synonyms.py",
)
def test_selects_a_drug_the_gold_never_annotates() -> None:
    """`metoprolol` occurs 213 times in the training notes, never inside a span.

    On salience alone 21 of 23 common drugs are rejected, because the annotators
    marked drugs in prose but not the structured medication list.
    """
    assert salience.salience("metoprolol") < salience.DEFAULT_THRESHOLD
    assert admits(ClinicalSalience(), NOTE, "metoprolol")
    assert not admits(ClinicalSalience(use_drugs=False), NOTE, "metoprolol")


def test_selects_an_analyte_the_annotators_were_inconsistent_about() -> None:
    """`amylase-` scores 0.29, `hct-` 0.99 — in a pancreatitis note both matter."""
    assert salience.salience("amylase-") < salience.DEFAULT_THRESHOLD
    assert admits(ClinicalSalience(), NOTE, "Amylase-")
    assert not admits(ClinicalSalience(use_labelled_values=False), NOTE, "Amylase-")


def test_the_labelled_value_clause_is_positional_not_lexical() -> None:
    """The bug that made `mg` the most-corrupted token in the corpus.

    A vocabulary form of this clause let `Mg-1.9` (magnesium, a lab result) admit
    every `mg` (milligram, a dose unit) anywhere in the note — 714 occurrences.
    A dose unit outside a labelled value must stay out.
    """
    text = "Metoprolol 25 mg PO BID\nMg-1.9 Na-140\n"
    rule = ClinicalSalience()
    assert not admits(rule, text, "mg PO"[:2])  # the dose unit
    assert admits(rule, text, "Mg-")  # the lab analyte


def test_empty_and_whitespace_spans_admit_nothing() -> None:
    _, context = ctx(NOTE)
    assert not ClinicalSalience().admits(Span(0, 0), context)


# -- against the rule it replaced -----------------------------------------


def test_it_is_strictly_narrower_than_concept_on_prose() -> None:
    """`Concept()` admits 45.7% of a discharge summary at 0.500 precision."""
    doc, context = ctx(NOTE)
    concept, clinical = Concept(), ClinicalSalience()
    for word in ("She", "Please", "admitted"):
        s = span_of(doc, NOTE, word)
        # Without a matcher `Concept` admits nothing, so this compares the
        # *decision*, not the wiring: the clinical rule rejects prose outright.
        assert not clinical.admits(s, context)
        assert not concept.admits(s, context)


# -- canon ----------------------------------------------------------------


def test_canon_records_every_clause() -> None:
    """Canon feeds the BLAKE2b seed, so it must distinguish rule variants.

    Two runs whose targets differ must not share an edit script.
    """
    assert ClinicalSalience().canon() == "clinical(salience>=0.5,drug,labelled,unseen)"
    assert ClinicalSalience(use_drugs=False).canon() == "clinical(salience>=0.5,labelled,unseen)"
    assert ClinicalSalience(threshold=0.6).canon().startswith("clinical(salience>=0.6")


def test_canon_differs_from_concept() -> None:
    assert ClinicalSalience().canon() != Concept().canon()


def test_threshold_changes_canon_and_therefore_the_seed() -> None:
    assert ClinicalSalience(threshold=0.4).canon() != ClinicalSalience(threshold=0.5).canon()
