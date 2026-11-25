"""`input.ocr_confusion`: shape-based misreading, as a scanner makes it.

The INPUT channel models the note being *captured* wrongly. `input.typo` covers
keyboard slips and `input.phonetic_confusion` covers mis-hearing; neither covers
the third way clinical text enters a record, which is a scanned or faxed page
read by an OCR engine.

The distinction is not cosmetic. A typo model asks which keys are adjacent; OCR
asks which glyphs look alike, and the two disagree almost everywhere — `m` and
`rn` sit at opposite ends of a keyboard and are nearly identical in print.
"""

from __future__ import annotations

import pytest

from robustehr.document import Document
from robustehr.ops.input import _OCR_CONFUSIONS, _OCR_LIGATURES, OcrConfusion
from robustehr.runner import apply_operator, severity_ladder

NOTE = (
    "HISTORY OF PRESENT ILLNESS:\n"
    "Patient with treatment for burn to the left hand. Temp 98.8, K 5.1,\n"
    "creatinine 1.0. Started on Droperidol with good response over 3 days.\n"
)


def run(mode: str, severity: str = "1.00"):
    doc = Document.from_text(NOTE, uid="ocr")
    op = OcrConfusion()
    return doc, apply_operator(
        doc, op, op.meta, severity_ladder(severity)[0], params={"mode": mode}
    )


class TestOcrIsNotATypo:
    def test_the_distinctive_confusions_are_absent_from_the_keyboard_model(self):
        """The property that makes this a separate operator, stated exactly.

        Some pairs are BOTH shape-similar and keyboard-adjacent — `n`/`h`,
        `t`/`f`, `i`/`j` — and 16% of the table coincides that way. That
        overlap is a real fact about Latin script, not a defect, so asserting a
        ratio would be asserting a number I picked.

        The substantive claim is narrower and checkable: the confusions that
        make OCR *clinically* distinctive — digit-for-letter, which turns a lab
        value into a word — exist nowhere in a keyboard-adjacency model. If they
        did, this operator would be a mode of `input.typo`.
        """
        from robustehr.ops.input import _ADJACENT

        digit_pairs = [
            (src, dst)
            for src, opts in _OCR_CONFUSIONS.items()
            for dst in opts
            if src.isdigit() != dst.isdigit()
        ]
        assert digit_pairs, "no digit-letter confusion: the dangerous case is unmodelled"
        for src, dst in digit_pairs:
            assert dst.lower() not in _ADJACENT.get(src.lower(), ""), (
                f"{src}->{dst} is keyboard-adjacent; input.typo already covers it"
            )

    def test_ligatures_change_token_length(self):
        """`rn` -> `m` is the OCR error a per-character model cannot express,
        and the one a downstream tokeniser cannot absorb."""
        assert any(len(src) != len(dst) for src, dst in _OCR_LIGATURES)


class TestReachesTheDangerousSpans:
    def test_digits_are_in_scope(self):
        """OCR reads whatever is on the page, including the lab values.

        A numeric-protection rule that withheld them would model only the
        harmless half of the phenomenon: a potassium of 5.1 misread as S.1 is
        the substitution an extractor is least able to recover from.
        """
        doc, result = run("glyph")
        touched = [
            e
            for e in result.apply_result.applied
            if any(c.isdigit() for c in doc.text[e.start : e.end])
        ]
        assert touched, "no digit was ever reached; numeric protection is blocking OCR"

    def test_the_operator_declares_the_classes_it_reaches(self):
        """Declared, not bypassed. Reaching a protected class requires saying so
        in `targets`; the protection registry refuses otherwise."""
        from robustehr.types import ProtectionClass

        assert ProtectionClass.NUMERIC_VALUE in OcrConfusion.meta.targets
        assert ProtectionClass.LAB_BLOCK in OcrConfusion.meta.targets


class TestDeterminismAndDose:
    @pytest.mark.parametrize("mode", ["glyph", "ligature"])
    def test_same_input_same_bytes(self, mode):
        first = run(mode)[1]
        second = run(mode)[1]
        assert first.dose.output_sha256 == second.dose.output_sha256

    @pytest.mark.parametrize("mode", ["glyph", "ligature"])
    def test_dose_denominators_are_monotonic(self, mode):
        dose = run(mode)[1].dose
        assert dose.applied_n <= dose.eligible_n <= dose.scope_n <= dose.total_n

    def test_eligibility_requires_a_confusable_glyph(self):
        """A token with nothing confusable in it must not be counted eligible.

        Otherwise the dose denominator includes units the operator can never
        act on, and every severity computed against it understates what was
        delivered — the failure `eligible_n` exists to prevent.
        """
        doc = Document.from_text("xx zz xx zz\n", uid="none")
        op = OcrConfusion()
        from robustehr.ops.base import OpContext, Scope
        from robustehr.protect.registry import protect_document

        ctx = OpContext(doc=doc, protection=protect_document(doc), scope=Scope())
        assert all(
            any(c in _OCR_CONFUSIONS for c in u.span.surface(doc.text)) for u in op.eligible(ctx)
        )

    def test_a_zero_dose_changes_nothing(self):
        doc, result = run("glyph", severity="0.00")
        assert result.text == doc.text


class TestPerTokenCap:
    """`max_edits_per_token` bounds what a character dose does to one word.

    Without it, a saturating severity over a narrow target substitutes every
    confusable position in a token at once — `Hypertension` -> `Hvpcrfousj0h`,
    which is a redaction wearing the operator's name rather than a misreading.
    """

    @staticmethod
    def _eligible(params):
        from robustehr.ops.base import OpContext, Scope
        from robustehr.protect.registry import protect_document

        doc = Document.from_text(NOTE, uid="ocr")
        ctx = OpContext(doc=doc, protection=protect_document(doc), scope=Scope(), params=params)
        return doc, OcrConfusion().eligible(ctx)

    def test_absent_parameter_changes_nothing(self):
        """The default path must stay identical, or every earlier run is invalid."""
        _, without = self._eligible({"mode": "glyph"})
        _, zero = self._eligible({"mode": "glyph", "max_edits_per_token": 0})
        assert [u.unit_id for u in without] == [u.unit_id for u in zero]

    def test_the_cap_reduces_the_denominator(self):
        _, uncapped = self._eligible({"mode": "glyph"})
        _, capped = self._eligible({"mode": "glyph", "max_edits_per_token": 1})
        assert len(capped) < len(uncapped)

    def test_at_most_one_position_per_token(self):
        doc, capped = self._eligible({"mode": "glyph", "max_edits_per_token": 1})
        per_token = {}
        for token in doc.tokens:
            hits = [u for u in capped if token.span.start <= u.span.start < token.span.end]
            per_token[token.span.start] = len(hits)
        assert per_token and max(per_token.values()) <= 1

    def test_a_capped_word_keeps_most_of_itself(self):
        """The property the parameter exists for, asserted on the text."""
        doc = Document.from_text(NOTE, uid="ocr")
        op = OcrConfusion()
        result = apply_operator(
            doc,
            op,
            op.meta,
            severity_ladder("1.00")[0],
            params={"mode": "glyph", "max_edits_per_token": 1},
        )
        for token in doc.tokens:
            before = token.span.surface(doc.text)
            after = result.text[token.span.start : token.span.end]
            changed = sum(1 for a, b in zip(before, after, strict=True) if a != b)
            assert changed <= 1, f"{before!r} -> {after!r}"

    def test_the_cap_is_deterministic(self):
        doc = Document.from_text(NOTE, uid="ocr")
        op = OcrConfusion()
        params = {"mode": "glyph", "max_edits_per_token": 1}
        runs = [
            apply_operator(doc, op, op.meta, severity_ladder("1.00")[0], params=params)
            for _ in range(2)
        ]
        assert runs[0].dose.output_sha256 == runs[1].dose.output_sha256

    def test_severity_ladders_still_nest_under_the_cap(self):
        """The cap is severity-free, so a lower rate stays a subset of a higher one."""
        doc = Document.from_text(NOTE, uid="ocr")
        op = OcrConfusion()
        params = {"mode": "glyph", "max_edits_per_token": 1}
        spans = []
        for literal in ("0.05", "0.10", "0.15"):
            result = apply_operator(doc, op, op.meta, severity_ladder(literal)[0], params=params)
            spans.append({(e.start, e.end) for e in result.apply_result.applied})
        assert spans[0] <= spans[1] <= spans[2]

    def test_eligible_works_without_seed_material(self):
        """The baseline describers build a bare context; the cap must not need one."""
        _, capped = self._eligible({"mode": "glyph", "max_edits_per_token": 1})
        assert capped
