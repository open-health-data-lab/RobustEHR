"""Anchor voting: the abstention rules, which are the whole design.

The rung answers when exactly one sense's cues fire and says nothing otherwise.
Everything worth testing is about the *otherwise*: a rung that guesses when the
evidence is mixed is worse than one that stays quiet, because a wrong concept
propagates into phenotype membership while a missing one is visible as coverage.
"""

from __future__ import annotations

import pytest

from robustehr.concepts.anchors import (
    CUES_RESOURCE,
    CueEntry,
    Outcome,
    Sense,
    _check_consistency,
    load_cues,
)
from robustehr.resources import resource_sha256
from robustehr.types import Span


def vote_on(text: str, form: str = "RA"):
    index = text.index(form)
    return load_cues().vote(text, Span(index, index + len(form)))


class TestTheVote:
    def test_one_sense_firing_resolves(self) -> None:
        assert vote_on("Sats 98% on RA overnight.").sense == "room air"

    def test_the_other_sense_resolves_too(self) -> None:
        """Both directions, or the cue list is just a keyword for one answer."""
        assert vote_on("History of RA on methotrexate.").sense == "rheumatoid arthritis"

    def test_no_cues_abstains(self) -> None:
        result = vote_on("Patient with RA.")
        assert result.outcome is Outcome.NO_CUES
        assert result.sense is None

    def test_conflicting_cues_abstain(self) -> None:
        """The case that matters most: mixed evidence must not become a guess.

        `matcher._rank` shows the alternative — it breaks ties alphabetically by
        CUI and answers `RA` with *refractory anemia* on 287 room-air gold spans.
        Deterministic, and wrong.
        """
        result = vote_on("RA with joint swelling, saturating well on oxygen.")
        assert result.outcome is Outcome.CONFLICT
        assert result.sense is None
        assert len(result.fired) > 1

    def test_a_form_with_no_entry_gets_no_opinion(self) -> None:
        """Distinct from abstention: this rung simply does not cover it."""
        assert vote_on("The patient had a CBC drawn.", form="CBC").outcome is (
            Outcome.NOT_AMBIGUOUS
        )

    def test_the_window_is_bounded(self) -> None:
        """A cue far away is not evidence, or every note resolves to everything."""
        far = "RA." + " filler" * 30 + " oxygen saturation"
        assert vote_on(far).outcome is Outcome.NO_CUES

    def test_the_window_looks_both_ways(self) -> None:
        """`on RA` and `RA sat 98%` are both decisive; word order is not evidence."""
        assert vote_on("RA, sats 97%.").sense == "room air"
        assert vote_on("Oxygen saturation 97% on RA.").sense == "room air"

    def test_matching_is_case_insensitive(self) -> None:
        assert vote_on("SATS 98% ON RA.").sense == "room air"


class TestTheCueSetRefusesWhatCannotDecide:
    def test_a_cue_shared_between_senses_is_refused(self) -> None:
        """It fires both, which conflicts, which abstains — coverage in name only."""
        with pytest.raises(ValueError, match="claimed by both"):
            _check_consistency(
                {
                    "xx": CueEntry(
                        "xx",
                        (
                            Sense("a", ("shared",)),
                            Sense("b", ("shared",)),
                        ),
                        held_out=True,
                    )
                }
            )

    def test_a_sense_with_no_cues_is_refused(self) -> None:
        with pytest.raises(ValueError, match="has no cues"):
            _check_consistency({"xx": CueEntry("xx", (Sense("a", ()),), held_out=True)})

    def test_a_regex_shaped_cue_is_refused(self) -> None:
        """Cues are compared as literal tokens, so a pattern here is dead code."""
        with pytest.raises(ValueError, match="not a literal word token"):
            _check_consistency({"xx": CueEntry("xx", (Sense("a", (r"sat.*",)),), held_out=True)})


class TestTheShippedCues:
    def test_every_form_is_marked_held_out(self) -> None:
        """In-sample cues score whatever their author wants them to.

        Any form whose cues were written after reading its gold instances must be
        excluded from reported accuracy, and the flag is how that is enforced.
        """
        for entry in load_cues().entries.values():
            assert isinstance(entry.held_out, bool)

    def test_cues_are_sorted(self) -> None:
        """Loaded as sorted tuples, never sets — iteration order is not evidence."""
        for entry in load_cues().entries.values():
            for sense in entry.senses:
                assert list(sense.cues) == sorted(sense.cues)

    def test_the_digest_pins_the_file(self) -> None:
        assert load_cues().sha256 == resource_sha256(CUES_RESOURCE)

    def test_ra_carries_all_three_clinically_real_senses(self) -> None:
        senses = {s.name for s in load_cues().entries["ra"].senses}
        assert senses == {"room air", "rheumatoid arthritis", "right atrium"}
