"""The LLM flip operators, tested without ever calling an LLM.

Every test here runs offline. The network path is exercised by
`validation/pipeline/scripts/assertion_flip_recovery.py` against a real model and recorded as a
measurement; what belongs in the suite is the machinery around the call — the
opt-in gate, the minimal diff, the protection refusal and the fallback — because
those are what stand between a model's reply and a clinical note.
"""

from __future__ import annotations

import pytest

from robustehr import llm
from robustehr.document import Document
from robustehr.ops import semantic, semantic_llm
from robustehr.ops.base import OpContext, Scope
from robustehr.protect.registry import protect_document
from robustehr.types import Span

NOTE = (
    "HPI: The patient denies chest pain and shortness of breath.\n"
    "PMH: History of hypertension.\n"
    "FHx: Father with myocardial infarction.\n"
)


def context(text: str = NOTE) -> OpContext:
    doc = Document.from_text(text, uid="t")
    return OpContext(doc=doc, protection=protect_document(doc), scope=Scope())


@pytest.fixture(autouse=True)
def _no_ambient_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own ROBUSTEHR_LLM_MODEL must not change what the suite proves."""
    monkeypatch.delenv(llm.MODEL_ENV, raising=False)
    monkeypatch.delenv(llm.KEY_ENV, raising=False)


class TestOptIn:
    def test_no_model_means_no_eligible_units(self) -> None:
        """The gate that makes these operators unable to fire by accident.

        An install with no model configured must behave exactly as it did before
        this module existed — no network, no units, no dose.
        """
        assert semantic_llm.NegationFlipLlm().eligible(context()) == []

    def test_the_table_operator_is_unaffected(self) -> None:
        """Same document, same cues: only the LLM arm is gated."""
        assert len(semantic.NegationFlip().eligible(context())) > 0

    def test_configure_refuses_to_invent_a_model(self) -> None:
        """There is deliberately no default model.

        A default would mean a user's notes could reach a third party through a
        setting nobody chose, which is not a decision this package makes for
        them.
        """
        with pytest.raises(llm.LlmUnavailable, match="No LLM model configured"):
            llm.configure()


class TestMinimalSpan:
    """The diff that keeps 'we showed it a sentence' from meaning 'it may edit one'."""

    def test_a_one_word_change_yields_a_one_word_edit(self) -> None:
        """And the shared *suffix* is trimmed too, not only the prefix.

        `denies` -> `reports` share a trailing `s`, so the minimal edit is
        `denie` -> `report`, five characters rather than six. That is the point:
        the edit is what actually changed, not what a word-level view would
        guess.
        """
        found = semantic_llm._minimal_span("the patient denies pain", "the patient reports pain", 0)
        assert found is not None
        span, replacement = found
        assert (span.start, span.end) == (12, 17)
        assert replacement == "report"

    def test_an_identical_reply_yields_no_edit(self) -> None:
        assert semantic_llm._minimal_span("no change here", "no change here", 0) is None

    def test_the_offset_is_carried(self) -> None:
        found = semantic_llm._minimal_span("denies pain", "reports pain", 100)
        assert found is not None
        assert found[0].start == 100

    def test_an_insertion_is_a_zero_width_span(self) -> None:
        found = semantic_llm._minimal_span("has pain", "has no pain", 0)
        assert found is not None
        span, replacement = found
        assert span.start == span.end
        assert replacement.strip() == "no"

    @pytest.mark.parametrize(
        ("original", "rewritten"),
        [
            ("a b c", "a X c"),
            ("prefix MIDDLE suffix", "prefix OTHER suffix"),
            ("same start end", "same finish end"),
        ],
    )
    def test_applying_the_minimal_edit_reproduces_the_reply(
        self, original: str, rewritten: str
    ) -> None:
        """The diff must be *correct*, not merely small."""
        found = semantic_llm._minimal_span(original, rewritten, 0)
        assert found is not None
        span, replacement = found
        assert original[: span.start] + replacement + original[span.end :] == rewritten


class TestFallback:
    def test_an_unavailable_model_falls_back_to_the_table_edit(self) -> None:
        """The failure policy: always propose something, never a bare miss.

        With no model configured `propose` still yields one edit per selected
        unit, and each is byte-identical to what the deterministic operator
        would have produced — so a dose is never silently short.
        """
        ctx = context()
        table_op, llm_op = semantic.NegationFlip(), semantic_llm.NegationFlipLlm()
        units = list(table_op.eligible(ctx))
        assert units

        from_table = list(table_op.propose(ctx, units))
        from_llm = list(llm_op.propose(ctx, units))

        assert len(from_llm) == len(from_table) == len(units)
        assert [(e.start, e.end, e.replacement) for e in from_llm] == [
            (e.start, e.end, e.replacement) for e in from_table
        ]

    def test_the_fallback_still_carries_the_llm_operator_id(self) -> None:
        """A fallback edit is still that operator's edit, and says so."""
        ctx = context()
        op = semantic_llm.NegationFlipLlm()
        units = list(semantic.NegationFlip().eligible(ctx))
        assert all(e.op_id == "semantic.negation_flip_llm" for e in op.propose(ctx, units))


class TestProtection:
    def test_an_edit_reaching_protected_text_is_refused(self) -> None:
        """The guard the runner cannot supply.

        The runner filters eligible *units* against protection; it never checks
        *edits*. An operator whose edit span is wider than its unit — which is
        exactly what a sentence rewrite is — has to check for itself, or it can
        rewrite a de-identification placeholder while declaring it only touches
        assertion cues.
        """
        ctx = context("HPI: On ___ the patient denies chest pain.\n")
        targets = semantic_llm.NegationFlipLlm.meta.targets
        refused = [
            p
            for p in ctx.protection.spans
            if not semantic_llm._preserves_protected(ctx, p.span, targets)
        ]
        assert refused, "this note must carry protections the operator may not touch"
        assert any("deid" in p.cls.value.lower() for p in refused)

    def test_a_span_touching_nothing_protected_is_permitted(self) -> None:
        """The operator can still edit ordinary prose."""
        ctx = context()
        cue = ctx.text.index("denies")
        assert semantic_llm._preserves_protected(
            ctx, Span(cue, cue + 6), semantic_llm.NegationFlipLlm.meta.targets
        )


class TestRegistration:
    def test_four_llm_operators_beside_four_table_ones(self) -> None:
        assert len(semantic_llm.OPERATORS) == len(semantic.OPERATORS) == 4

    def test_ids_name_the_mechanism(self) -> None:
        """No artifact should be ambiguous about which mechanism made an edit."""
        assert {op.id for op in semantic_llm.OPERATORS} == {
            "semantic.negation_flip_llm",
            "semantic.uncertainty_flip_llm",
            "semantic.temporality_shift_llm",
            "semantic.experiencer_shift_llm",
        }

    def test_the_prompt_is_a_hashed_resource(self) -> None:
        """Editing a prompt must be a version bump, not a silent change."""
        for op in semantic_llm.OPERATORS:
            assert semantic_llm.PROMPT_RESOURCE in op.resources

    def test_they_carry_the_same_contract_and_dose_as_the_table_arms(self) -> None:
        """Same units, same denominator: the two are comparable arms."""
        for llm_op, table_op in zip(semantic_llm.OPERATORS, semantic.OPERATORS, strict=True):
            assert llm_op.contract == table_op.contract
            assert llm_op.dose.unit_kind == table_op.dose.unit_kind
            assert llm_op.targets == table_op.targets


class TestCacheKey:
    def test_the_key_covers_model_and_prompt_and_not_the_credential(self) -> None:
        """Two models must not share a cached answer; two keys must."""
        from pathlib import Path

        a = llm.LlmConfig(model="vendor/one", cache=Path("x"), key="secret-a")
        b = llm.LlmConfig(model="vendor/two", cache=Path("x"), key="secret-a")
        c = llm.LlmConfig(model="vendor/one", cache=Path("x"), key="secret-b")
        assert llm.cache_key(a, "p") != llm.cache_key(b, "p")
        assert llm.cache_key(a, "p") == llm.cache_key(c, "p")
        assert llm.cache_key(a, "p") != llm.cache_key(a, "q")

    def test_provenance_names_the_model_and_never_the_key(self) -> None:
        """An LLM edit is attributable from (version, model, cache) — not version alone."""
        from pathlib import Path

        config = llm.LlmConfig(model="vendor/one", cache=Path("x"), key="secret")
        recorded = llm.provenance(config)
        assert recorded["model"] == "vendor/one"
        assert "secret" not in "".join(recorded.values())
