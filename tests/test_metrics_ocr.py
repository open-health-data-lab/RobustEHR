"""The OCR baseline, and its pairing with the operator that injects the noise.

What makes this measurement worth having is not its absolute value — it is a
candidate count with the same kind of precision cost `near_miss_edit1` publishes
— but that it and `input.ocr_confusion` read the SAME table, one forward and one
backward. These tests assert that pairing, because if the two ever drifted apart
the before/after comparison would be measuring two different phenomena and
nothing in the output would say so.
"""

from __future__ import annotations

from robustehr.document import Document
from robustehr.lexicon import DEFAULT_LEXICON
from robustehr.metrics.ocr import profile_ocr
from robustehr.ocr import load_table
from robustehr.ops import registry
from robustehr.ops.base import Scope
from robustehr.runner import apply_operator, severity_ladder

CLEAN = (
    "The patient has a long history of hypertension and diabetes mellitus. "
    "Creatinine remains stable and the wound is healing without infection.\n"
)


def profile(text: str):  # type: ignore[no-untyped-def]
    return profile_ocr(Document.from_text(text, uid="n"), DEFAULT_LEXICON, None)


class TestTheTable:
    def test_the_inverse_is_the_transpose_of_the_forward(self) -> None:
        """Authored once, derived once. Two hand-written tables would drift."""
        table = load_table()
        for source, emitted in table.glyphs.items():
            for char in emitted:
                assert source in table.inverse_glyphs[char], f"{source}->{char} not invertible"

    def test_nothing_confuses_with_itself(self) -> None:
        """A self-mapping row proposes a no-op, which shortens a dose silently."""
        table = load_table()
        for source, emitted in table.glyphs.items():
            assert source not in emitted
        for src, dst in table.ligatures:
            assert src != dst

    def test_the_digit_rows_survive_the_move_to_yaml(self) -> None:
        """The clinically dangerous half, and the reason this is not `input.typo`."""
        glyphs = load_table().glyphs
        for digit, letter in (("0", "O"), ("1", "l"), ("5", "S"), ("8", "B")):
            assert letter in glyphs[digit]

    def test_the_resource_digest_reaches_the_operator_version(self) -> None:
        """Editing the table must be a version bump, not a silent change."""
        registry.register_builtins()
        op = registry.get("input.ocr_confusion")
        assert "+r" in registry.resolved_version(op.meta)


class TestBaseline:
    def test_clean_prose_has_no_suspects(self) -> None:
        assert profile(CLEAN).suspect == 0

    def test_injected_noise_is_detected(self) -> None:
        """The pairing, end to end: corrupt with the table, detect with its inverse."""
        registry.register_builtins()
        doc = Document.from_text(CLEAN, uid="n")
        op = registry.get("input.ocr_confusion")()
        result = apply_operator(
            doc, op, op.meta, severity_ladder("0.10")[0], scope=Scope(), salt="rep0"
        )
        assert profile(result.text).suspect > profile(CLEAN).suspect

    def test_real_words_are_never_suspects(self) -> None:
        """`burn` -> `bum` is a textbook OCR error and `burn` is still a word.

        Counting it would make the estimate a function of how many short words
        the note has rather than of how much noise it carries.
        """
        assert "burn" not in profile("The burn is healing.\n").surfaces

    def test_the_operator_denominator_is_reported_beside_the_estimate(self) -> None:
        """A note with no confusable positions cannot be corrupted, whatever the dose."""
        measured = profile(CLEAN)
        assert measured.confusable_chars > 0
        assert measured.suspect_rate == 0.0

    def test_an_empty_note_has_no_rate_rather_than_a_zero_one(self) -> None:
        assert profile("").suspect_rate is None

    def test_the_denominator_matches_what_the_operator_is_eligible_on(self) -> None:
        """The parity that makes a severity predictable from Table 1."""
        from robustehr.ops.base import OpContext
        from robustehr.protect.registry import protect_document

        registry.register_builtins()
        doc = Document.from_text(CLEAN, uid="n")
        ctx = OpContext(doc=doc, protection=protect_document(doc), scope=Scope())
        eligible = len(registry.get("input.ocr_confusion")().eligible(ctx))
        assert eligible == profile(CLEAN).confusable_chars
