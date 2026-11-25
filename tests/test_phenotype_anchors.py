"""The surface warrant: what an anchor admits, and what a stop surface refuses.

These run without a UMLS crosswalk or a QuickUMLS index. That is the point of
the layer — a surface match needs no terminology — and it means the anchor
behaviour is checked on every CI runner rather than only on a machine holding a
licensed release, which is where the concept-set fixtures skip.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from robustehr.concepts import surface
from robustehr.concepts.matcher import Mention, MentionIndex
from robustehr.concepts.phenotype import Evidence, Phenotype, index_document
from robustehr.concepts.surface import AnchorSet, anchor_spans, is_stopped
from robustehr.types import Span


def anchored(*forms: str, stops: tuple[str, ...] = ()) -> AnchorSet:
    return AnchorSet(phenotype="test", anchors=forms, stop_surfaces=frozenset(stops))


def surfaces(text: str, anchors: AnchorSet) -> list[str]:
    return [text[s.start : s.end] for s in anchor_spans(text, anchors)]


class TestAnchorMatching:
    def test_case_is_ignored(self) -> None:
        """Clinicians capitalise a diagnosis inconsistently and it means the same."""
        anchors = anchored("hypertension")
        assert surfaces("HTN? Hypertension. hypertension HYPERTENSION", anchors) == [
            "Hypertension",
            "hypertension",
            "HYPERTENSION",
        ]

    def test_a_match_must_be_a_whole_word(self) -> None:
        """Otherwise `pe` corrupts every `percutaneous` and `peripheral` in the note.

        This is the single highest-risk property of the layer: the abbreviations
        that make it worth having are also two and three characters long.
        """
        anchors = anchored("pe", "dm2")
        text = "PE confirmed. percutaneous approach, peripheral edema, DM2, notDM2x"
        assert surfaces(text, anchors) == ["PE", "DM2"]

    def test_internal_whitespace_is_flexible(self) -> None:
        """Clinical text wraps mid-diagnosis, and the phrase survives the wrap."""
        anchors = anchored("heart failure")
        assert surfaces("heart failure, heart  failure, heart\nfailure", anchors) == [
            "heart failure",
            "heart  failure",
            "heart\nfailure",
        ]

    def test_the_longest_anchor_wins(self) -> None:
        """A shorter anchor listed first must not truncate the diagnosis.

        Alternation takes the first branch that matches, not the longest, so
        without the length sort `type 2 diabetes` would be corrupted as
        `diabetes` and the words distinguishing it from type 1 would survive.
        """
        anchors = anchored("diabetes", "type 2 diabetes")
        assert surfaces("known type 2 diabetes here", anchors) == ["type 2 diabetes"]

    def test_punctuation_in_an_anchor_is_literal(self) -> None:
        """`c. diff` is a surface, not a pattern; the dot matches a dot."""
        anchors = anchored("c. diff", "c.diff")
        assert surfaces("c. diff and c.diff but not cxdiff", anchors) == ["c. diff", "c.diff"]

    def test_no_anchors_matches_nothing(self) -> None:
        """An empty warrant is a legitimate state, not an empty pattern that matches all."""
        assert anchor_spans("hypertension everywhere", anchored()) == ()

    def test_overlapping_occurrences_are_counted_once(self) -> None:
        """Two anchors over the same characters are one piece of evidence.

        Counting them twice would inflate the denominator of every reach
        measurement built on this layer.
        """
        anchors = anchored("diabetes mellitus", "mellitus")
        assert surfaces("diabetes mellitus", anchors) == ["diabetes mellitus"]


class TestStopSurfaces:
    def test_an_ordinary_english_single_token_is_refused(self) -> None:
        """The floor. `status` is in the shipped general-English list."""
        assert is_stopped("status", anchored("hypertension"))

    def test_a_clinical_single_token_survives_the_floor(self) -> None:
        """`aspirin` carries a high-precision type, so it is absent from that list.

        This is what makes the floor safe to apply to every phenotype: the
        subtraction has already been done, so the floor cannot refuse the
        medication facet wholesale.
        """
        assert not is_stopped("aspirin", anchored("hypertension"))
        assert not is_stopped("fever", anchored("hypertension"))

    def test_a_declared_stop_surface_is_refused(self) -> None:
        """For surfaces the floor cannot reach, because they carry a clinical type."""
        assert is_stopped("secondary", anchored("metastatic", stops=("secondary",)))

    def test_an_anchor_outranks_every_refusal(self) -> None:
        """An explicit declaration that this string IS the diagnosis wins.

        Without this, a phenotype whose diagnosis happens to be an ordinary
        English word would be silently unreachable by its own anchor.
        """
        assert not is_stopped("obesity", anchored("obesity"))
        assert not is_stopped("depression", anchored("depression"))

    def test_a_multi_token_surface_is_never_stopped_by_the_floor(self) -> None:
        """`chest pain` in a hypertension set is a closure-precision problem.

        A real concept, correctly matched, that is an association rather than a
        cue. Tightening the vetting criterion is where that belongs; refusing it
        here would be this layer silently editing the concept set.
        """
        assert not is_stopped("chest pain", anchored("hypertension"))

    def test_an_empty_surface_is_refused(self) -> None:
        assert is_stopped("   ", anchored("hypertension"))


class TestResourceIntegrity:
    def test_a_surface_cannot_be_both_anchor_and_stop(self) -> None:
        """The two blocks would make contradictory claims about one string.

        Caught at load rather than resolved by precedence: whichever way the
        runtime broke the tie, the resource would still be stating that a string
        both is and is not the diagnosis, and one of the two lines is wrong.
        """
        clashing = {"phenotypes": {"obesity": {"anchors": ["obese"], "stop_surfaces": ["obese"]}}}
        with pytest.raises(ValueError, match="both anchor and stop"):
            surface.parse_anchors(clashing)

    def test_parsing_lowercases_and_strips(self) -> None:
        """So a hand-edited resource cannot silently stop matching.

        Internal runs of whitespace are left alone because the pattern builder
        splits on them anyway, and collapsing them here would make the stored
        form differ from what the author wrote for no gain.
        """
        parsed = surface.parse_anchors(
            {"phenotypes": {"hfref": {"anchors": ["  HFrEF ", "Systolic  HF"]}}}
        )
        assert parsed["hfref"].anchors == ("hfref", "systolic  hf")

    def test_declared_distinguishes_empty_from_absent(self) -> None:
        """Same distinction `facet_sizes` draws, for the same reason."""
        assert not anchored().declared
        assert anchored("htn").declared

    def test_the_shipped_resource_loads_and_agrees_with_itself(self) -> None:
        """Skipped until the resource is built; a clash would raise at load."""
        loaded = surface.load_anchors()
        if not loaded:
            pytest.skip("phenotype_anchors.yaml has not been built")
        for name, anchors in loaded.items():
            assert not (set(anchors.anchors) & anchors.stop_surfaces), name
            assert all(a == a.strip().lower() for a in anchors.anchors), name


class TestEvidenceContract:
    def test_tier_is_the_last_field(self) -> None:
        """Every caller builds an Evidence positionally, here and downstream.

        A field inserted before `assertion` rebinds it to a tier string and the
        assertion layer silently empties. That happened once during this change
        and two tests caught it; this is the guard that names why.
        """
        built = Evidence(Span(0, 5), "hypertension", "C0020538", frozenset({"negated"}))
        assert built.assertion == frozenset({"negated"})
        assert built.qualified
        assert built.tier == "unknown"

    def test_unknown_is_not_closure(self) -> None:
        """One says the concept came in weakly, the other says nobody asked."""
        bare = Phenotype(
            name="hypertension",
            seed_codes=("38341003",),
            concept_cuis=frozenset({"C0020538"}),
            concept_codes=frozenset({"38341003"}),
        )
        assert bare.tier_of("C0020538") == "unknown"

    def test_tier_of_prefers_the_stronger_warrant(self) -> None:
        """A concept in two facets is labelled by the more direct one."""
        both = Phenotype(
            name="hfref",
            seed_codes=("703272007",),
            concept_cuis=frozenset({"C1"}),
            concept_codes=frozenset(),
            facet_cuis={"disorder": frozenset({"C1"}), "closure": frozenset({"C1"})},
        )
        assert both.tier_of("C1") == "disorder"


class TestIndexDocument:
    """Where the two warrants meet."""

    @staticmethod
    def phenotype(anchors: AnchorSet | None) -> Phenotype:
        return Phenotype(
            name="type_2_diabetes",
            seed_codes=("44054006",),
            concept_cuis=frozenset({"C0011860"}),
            concept_codes=frozenset({"44054006"}),
            facet_cuis={"disorder": frozenset({"C0011860"})},
            anchors=anchors,
        )

    def test_an_anchor_creates_evidence_the_matcher_never_found(self) -> None:
        """The abbreviation gap, closed.

        Stage 3c can only re-ground a span the matcher already returned, so an
        abbreviation producing no candidate is unreachable by every other stage.
        """
        text = "History of T2DM, well controlled."
        index = index_document(
            MentionIndex(mentions=()), [self.phenotype(anchored("t2dm"))], text=text
        )
        assert len(index) == 1
        assert index.evidence[0].tier == "anchor"
        assert index.evidence[0].cui == ""
        assert text[index.evidence[0].span.start : index.evidence[0].span.end] == "T2DM"

    def test_omitting_text_is_the_pre_anchor_behaviour(self) -> None:
        """Narrower, still correct. A caller that has not been updated is not broken."""
        index = index_document(MentionIndex(mentions=()), [self.phenotype(anchored("t2dm"))])
        assert len(index) == 0

    def test_a_concept_match_suppresses_the_overlapping_anchor(self) -> None:
        """One piece of evidence, not two, and the one carrying a CUI wins."""
        text = "diabetes mellitus type 2"
        mention = Mention(
            span=Span(0, len(text)),
            cui="C0011860",
            tuis=frozenset({"T047"}),
            similarity=1.0,
            surface=text,
        )
        index = index_document(
            MentionIndex(mentions=(mention,)),
            [self.phenotype(anchored("diabetes mellitus"))],
            text=text,
        )
        assert len(index) == 1
        assert index.evidence[0].tier == "disorder"
        assert index.evidence[0].cui == "C0011860"

    def test_a_stopped_surface_never_becomes_evidence(self) -> None:
        """`status` grounding to an in-set concept is a matcher accident."""
        text = "volume status stable"
        mention = Mention(
            span=Span(7, 13),
            cui="C0011860",
            tuis=frozenset({"T047"}),
            similarity=0.8,
            surface="status",
        )
        index = index_document(
            MentionIndex(mentions=(mention,)), [self.phenotype(anchored("t2dm"))], text=text
        )
        assert len(index) == 0

    def test_reach_divides_into_a_fraction(self) -> None:
        """Declared and touched share a denominator, per tier."""
        text = "T2DM and dm2 both documented."
        index = index_document(
            MentionIndex(mentions=()), [self.phenotype(anchored("t2dm", "dm2"))], text=text
        )
        assert index.declared_by_tier("type_2_diabetes") == {"anchor": 2}
        assert index.touched_by_tier([Span(0, 4)], "type_2_diabetes") == {"anchor": 1}


class TestPunctuationVariants:
    """A model enumerating abbreviations will miss one, so the matcher generates them.

    `c. diff`, `c diff` and `cdiff` were all proposed for C. difficile and
    `c.diff` was not — the form notes most often use. The miss was invisible
    until the corpora were audited word by word: 30% of `C. diff` occurrences
    went uncorrupted while the arm reported 99% reach, because every span it
    DID declare had been treated.
    """

    @staticmethod
    def surfaces(text: str, *forms: str) -> list[str]:
        anchors = AnchorSet(phenotype="test", anchors=forms)
        return [text[s.start : s.end] for s in anchor_spans(text, anchors)]

    def test_one_dotted_form_covers_its_variants(self) -> None:
        for written in ("c.diff", "c. diff", "c diff", "cdiff", "C Diff"):
            assert self.surfaces(f"positive for {written} today", "c. diff"), written

    def test_an_initialism_keeps_its_separators(self) -> None:
        """`s.l.e.` covers its punctuation variants but NOT the bare letters.

        Dropping the separators entirely is what let `h.a.d.` match `had`. The
        undotted spelling of a real initialism is listed as its own anchor —
        `sle` is — so nothing is lost by requiring something between the
        letters here.
        """
        assert self.surfaces("dx of s.l.e. noted", "s.l.e.") == ["s.l.e"]
        assert self.surfaces("dx of s l e noted", "s.l.e.") == ["s l e"]
        assert self.surfaces("dx of sle noted", "s.l.e.") == []
        assert self.surfaces("dx of sle noted", "s.l.e.", "sle") == ["sle"]

    def test_a_plain_space_still_requires_a_space(self) -> None:
        """The tolerance is for punctuation, not for word boundaries.

        Collapsing every separator would make `heart failure` match
        `heartfailure`, and from there any two-word anchor matches any
        concatenation of its parts.
        """
        assert self.surfaces("known heart failure here", "heart failure")
        assert self.surfaces("no heartfailure here", "heart failure") == []

    def test_an_initialism_does_not_collapse_onto_a_word(self) -> None:
        """`h.a.d.` is HIV-associated dementia. `had` is the past tense of have.

        The punctuation tolerance that lets `c. diff` cover `cdiff` will, left
        unguarded, let any dotted initialism cover its undotted spelling — and
        for three-letter initialisms that spelling is often an ordinary word.
        This was measured, not imagined: dementia's typo arm went from 227
        edited notes to 484, the difference being every note containing "had".

        A separator may vanish only when a neighbouring run is longer than one
        character, which is what makes `c. diff` safe and `h.a.d.` not. The
        undotted form of a real initialism is listed as its own anchor anyway.
        """
        anchors = AnchorSet(phenotype="test", anchors=("h.a.d.", "m.i.d."))
        assert anchor_spans("the patient had a fall", anchors) == ()
        assert anchor_spans("mid sternal chest pain", anchors) == ()
        assert anchor_spans("h.a.d. confirmed on testing", anchors)

    def test_the_shipped_anchors_hit_no_ordinary_english_word(self) -> None:
        """A sweep, because one collision was found by noticing an edit count.

        Every shipped anchor is matched against the general-English vocabulary;
        a hit means some phenotype would corrupt that word wherever it appears.
        """
        loaded = surface.load_anchors()
        if not loaded:
            pytest.skip("phenotype_anchors.yaml has not been built")
        from robustehr.lexical import english_vocabulary

        collisions = []
        for name, anchors in loaded.items():
            for word in english_vocabulary():
                if len(word) < 3:
                    continue
                hit = anchor_spans(f"the {word} was noted", anchors)
                if hit and word not in anchors.anchors:
                    collisions.append((name, word))
        assert not collisions[:20], f"anchors matching ordinary words: {collisions[:20]}"


class TestVettingState:
    """The review state is reported in every targeting manifest, so it is validated."""

    def test_parse_rejects_an_unknown_vetting_state(self) -> None:
        with pytest.raises(ValueError, match="vetted_by"):
            surface.parse_anchors({"vetted_by": "reviewed", "phenotypes": {}})

    def test_every_documented_state_parses(self) -> None:
        for state in surface.VETTED_BY:
            assert surface.parse_anchors({"vetted_by": state, "phenotypes": {}}) == {}

    def test_the_shipped_resource_declares_a_known_state(self) -> None:
        """And the state agrees with the resource's own ledger of passes."""
        provenance = surface.anchor_provenance()
        if provenance["vetted_by"] == "absent":
            pytest.skip("phenotype_anchors.yaml has not been built")
        assert provenance["vetted_by"] in surface.VETTED_BY
        by = {str(p.get("by")) for p in provenance["passes"]}
        if "hand" in by or "clinician" in by:
            assert provenance["vetted_by"] != "llm", "a hand pass is recorded but not declared"
        if provenance["vetted_by"] == "llm":
            assert by <= {"llm", "deterministic"}

    def test_block_provenance_fields_are_well_formed(self) -> None:
        """The per-phenotype fields are provenance the runtime never reads; they still
        have to name a pass the ledger declares, or they are a fourth vocabulary."""
        from robustehr.resources import load_yaml

        try:
            raw = load_yaml(surface.ANCHORS_RESOURCE)
        except FileNotFoundError:
            pytest.skip("phenotype_anchors.yaml has not been built")
        declared_passes = {int(p["pass"]) for p in raw.get("passes", ())}
        for name, block in raw["phenotypes"].items():
            if "source" in block:
                assert block["source"] in {"llm", "hand", "deterministic"}, name
            if "pass" in block:
                assert int(block["pass"]) in declared_passes, name
            if "reviewed_n" in block:
                assert int(block["reviewed_n"]) >= 0, name


class TestTargetingDigest:
    """The digest names what a target admits and refuses, and nothing else."""

    RAW: ClassVar[dict[str, Any]] = {
        "vetted_by": "llm",
        "passes": [{"by": "llm", "pass": 1}],
        "stop_surfaces": ["status"],
        "phenotypes": {
            "hypertension": {
                "anchors": ["htn"],
                "associated": ["elevated bp"],
                "stop_surfaces": [],
                "pass": 1,
                "reviewed_n": 3,
                "source": "llm",
            }
        },
    }

    def test_provenance_edits_do_not_move_it(self) -> None:
        before = surface.targeting_digest_of(self.RAW)
        edited = {
            **self.RAW,
            "vetted_by": "llm+hand",
            "passes": [{"by": "llm", "pass": 1}, {"by": "hand", "pass": 2}],
            "phenotypes": {
                "hypertension": {
                    **self.RAW["phenotypes"]["hypertension"],
                    "pass": 2,
                    "reviewed_n": 9,
                }
            },
        }
        assert surface.targeting_digest_of(edited) == before

    def test_an_added_anchor_moves_it(self) -> None:
        edited = {
            **self.RAW,
            "phenotypes": {
                "hypertension": {
                    **self.RAW["phenotypes"]["hypertension"],
                    "anchors": ["htn", "hbp"],
                }
            },
        }
        assert surface.targeting_digest_of(edited) != surface.targeting_digest_of(self.RAW)

    def test_a_global_stop_surface_moves_it(self) -> None:
        """Global stops are consulted on both warrants, so they are part of the target."""
        edited = {**self.RAW, "stop_surfaces": ["status", "history"]}
        assert surface.targeting_digest_of(edited) != surface.targeting_digest_of(self.RAW)

    def test_absent_is_a_reportable_value(self) -> None:
        assert surface.targeting_digest_of({}) == "absent"
        assert surface.targeting_digest_of(None) == "absent"

    def test_the_shipped_digest_is_a_hash_or_absent(self) -> None:
        digest = surface.targeting_digest()
        assert digest == "absent" or (len(digest) == 64 and int(digest, 16) >= 0)
