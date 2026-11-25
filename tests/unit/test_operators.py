"""Operator contracts, and the framework guarantees operators do not have to keep.

The contract tests are the point of the whole lattice. An
``INVARIANT_BY_CONSTRUCTION`` operator claims it can never alter clinical
reference, for any phenotype, in any document — and that claim is discharged
here, against every note format at every severity, rather than asserted in a
table. An operator that fails is not excused; it is demoted.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from robustehr import kappa, taxonomy
from robustehr.document import Document
from robustehr.dose import DoseStatus
from robustehr.ops import Scope, all_ids, all_operators, get, resolved_version
from robustehr.ops.base import Operator
from robustehr.resources import resource_bytes
from robustehr.runner import apply_operator, severity_ladder
from robustehr.types import Contract, PhenotypeScope, ProtectionClass
from tests.fixtures.clinical import FORMATS

LADDER = severity_ladder("0.10", "0.30", "0.50", "1")
NOTES = sorted(FORMATS)
OPS = list(all_operators())


def run(op_cls, doc: Document, severity, **params):  # type: ignore[no-untyped-def]
    return apply_operator(doc, op_cls(), op_cls.meta, severity, params=params or {})


class TestRegistry:
    def test_builtins_are_registered(self) -> None:
        assert "render.deid_restyle" in all_ids()
        assert "control.identity" in all_ids()

    def test_ids_are_sorted_not_set_ordered(self) -> None:
        assert list(all_ids()) == sorted(all_ids())

    def test_ids_are_namespaced(self) -> None:
        assert all("." in op_id for op_id in all_ids())

    def test_operators_satisfy_the_protocol(self) -> None:
        assert all(isinstance(cls(), Operator) for cls in OPS)

    def test_resource_digests_fold_into_the_version(self) -> None:
        """A lexicon swap must invalidate the affected seeds, not silently
        change previously reported results."""
        styled = get("render.header_style")
        assert "+r" in resolved_version(styled.meta)
        assert resolved_version(get("control.identity").meta) == "1.0.0"


@pytest.mark.parametrize("op_cls", OPS, ids=lambda c: c.id)
@pytest.mark.parametrize("name", NOTES)
class TestContracts:
    def test_invariant_operators_never_alter_reference(self, op_cls, name: str) -> None:  # type: ignore[no-untyped-def]
        """The proof obligation behind INVARIANT_BY_CONSTRUCTION.

        Checked at every severity, because an operator can be invariant at full
        dose and not at partial dose — restyling only some masks produces a
        mixed-convention document, which is exactly where a careless projection
        reports a spurious violation.
        """
        if op_cls.meta.contract is not Contract.INVARIANT_BY_CONSTRUCTION:
            pytest.skip("contract does not claim invariance")
        doc = Document.from_text(FORMATS[name].text, uid=name)
        for severity in LADDER:
            result = run(op_cls, doc, severity)
            assert kappa.holds(op_cls.meta.canonicalizer, doc.text, result.text), (
                f"{op_cls.id} violated {op_cls.meta.canonicalizer} on {name} at {severity.canon()}"
            )

    def test_null_control_never_changes_anything(self, op_cls, name: str) -> None:  # type: ignore[no-untyped-def]
        if op_cls.meta.contract is not Contract.CONTROL_NULL:
            pytest.skip("not a null control")
        doc = Document.from_text(FORMATS[name].text, uid=name)
        for severity in LADDER:
            result = run(op_cls, doc, severity)
            assert result.text == doc.text
            assert result.dose.output_identical
            assert result.dose.applied_n == 0

    def test_output_is_deterministic(self, op_cls, name: str) -> None:  # type: ignore[no-untyped-def]
        doc = Document.from_text(FORMATS[name].text, uid=name)
        a = run(op_cls, doc, LADDER[1])
        b = run(op_cls, doc, LADDER[1])
        assert a.text == b.text
        assert a.dose.output_sha256 == b.dose.output_sha256

    def test_masks_survive_unless_the_operator_targets_them(self, op_cls, name: str) -> None:  # type: ignore[no-untyped-def]
        """Fabricating PHI-shaped text is the one thing no contract permits."""
        if ProtectionClass.DEID_PLACEHOLDER in op_cls.meta.targets:
            pytest.skip("operator legitimately rewrites masks")
        doc = Document.from_text(FORMATS[name].text, uid=name)
        result = run(op_cls, doc, LADDER[-1])
        before = Document.from_text(doc.text, uid="b").deid.count
        after = Document.from_text(result.text, uid="a").deid.count
        assert after == before


class TestFrameworkGuarantees:
    """Properties the runner keeps so that operators do not have to."""

    def test_severity_ladders_nest(self) -> None:
        """selected(0.10) ⊆ selected(0.30) ⊆ selected(0.50).

        What makes dose-response curves paired within a document rather than a
        mixture of dose and resampling noise.
        """
        doc = Document.from_text(FORMATS["complex_discharge"].text, uid="c")
        op_cls = get("render.whitespace_collapse")
        applied = []
        for severity in LADDER:
            result = run(op_cls, doc, severity)
            applied.append({e.span for e in result.apply_result.applied})
        for smaller, larger in pairwise(applied):
            assert smaller <= larger

    def test_higher_severity_never_applies_less(self) -> None:
        doc = Document.from_text(FORMATS["complex_discharge"].text, uid="c")
        op_cls = get("render.deid_restyle")
        counts = [run(op_cls, doc, s).dose.applied_n for s in LADDER]
        assert counts == sorted(counts)

    def test_subset_invariance(self) -> None:
        """Perturbing one note must not depend on what else is processed."""
        text = FORMATS["mimic_discharge"].text
        op_cls = get("render.header_style")
        alone = run(op_cls, Document.from_text(text, uid="n1"), LADDER[1]).text
        again = run(op_cls, Document.from_text(text, uid="n1"), LADDER[1]).text
        assert alone == again

    def test_note_identity_changes_the_selection(self) -> None:
        text = FORMATS["complex_discharge"].text
        op_cls = get("render.whitespace_collapse")
        a = run(op_cls, Document.from_text(text, uid="n1"), LADDER[1])
        b = run(op_cls, Document.from_text(text, uid="n2"), LADDER[1])
        assert a.dose.applied_n == b.dose.applied_n
        assert a.text != b.text  # same dose, different units chosen

    def test_protection_is_reported_not_hidden(self) -> None:
        doc = Document.from_text(FORMATS["mimic_discharge"].text, uid="m")
        result = run(get("render.header_style"), doc, LADDER[-1])
        assert result.dose.protected_n > 0
        assert result.dose.eligible_n + result.dose.protected_n == result.dose.scope_n

    def test_scope_restricts_and_is_recorded(self) -> None:
        doc = Document.from_text(FORMATS["mimic_discharge"].text, uid="m")
        op_cls = get("render.whitespace_collapse")
        full = apply_operator(doc, op_cls(), op_cls.meta, LADDER[-1])
        scoped = apply_operator(
            doc, op_cls(), op_cls.meta, LADDER[-1], scope=Scope(section="physical_examination")
        )
        assert scoped.dose.scope_n < full.dose.scope_n
        assert "section=physical_examination" in scoped.dose.scope_canon

    def test_phenotype_scope_requires_naming_a_phenotype(self) -> None:
        """ "Phenotype-related" is undefined without saying which phenotype."""
        with pytest.raises(ValueError, match="requires at least one"):
            Scope(phenotype_scope=PhenotypeScope.PROTECT)


class TestDoseReporting:
    def test_inapplicable_operator_is_flagged_not_scored_zero(self) -> None:
        """A note with no masks must not contribute a zero to the restyler's mean."""
        doc = Document.from_text(FORMATS["ward_nursing"].text, uid="w")
        result = run(get("render.deid_restyle"), doc, LADDER[-1])
        assert result.dose.status is DoseStatus.NA_NO_ELIGIBLE
        assert result.dose.achieved_eligible is None
        assert not result.dose.is_applicable

    def test_full_severity_reaches_every_eligible_unit(self) -> None:
        doc = Document.from_text(FORMATS["mimic_discharge"].text, uid="m")
        result = run(get("render.whitespace_collapse"), doc, LADDER[-1])
        assert result.dose.applied_n == result.dose.eligible_n
        assert result.dose.achieved_eligible == 1

    def test_record_serializes_without_floats(self) -> None:
        doc = Document.from_text(FORMATS["mimic_discharge"].text, uid="m")
        row = run(get("render.deid_restyle"), doc, LADDER[1]).dose.to_row()
        assert not any(isinstance(v, float) for v in row.values())
        assert row["op_id"] == "render.deid_restyle"


class TestDeidRestyle:
    @pytest.mark.parametrize(
        "mode", ["bracket_star", "angle_tag", "square_tag", "curly_tag", "xxx", "redacted"]
    )
    def test_every_mode_produces_recognizable_masks(self, mode: str) -> None:
        doc = Document.from_text(FORMATS["mimic_discharge"].text, uid="m")
        result = run(get("render.deid_restyle"), doc, LADDER[-1], mode=mode)
        assert result.text != doc.text
        assert kappa.holds("content_tokens_masked_deid", doc.text, result.text)

    def test_typed_source_labels_are_carried_over(self) -> None:
        """`<GP_NAME>` says what was removed; that survives a restyle to another
        typed scheme and is what makes typed→untyped provably lossy."""
        doc = Document.from_text(FORMATS["nhs_letter"].text, uid="n")
        result = run(get("render.deid_restyle"), doc, LADDER[-1], mode="square_tag")
        assert "[GP_NAME]" in result.text

    def test_untyped_source_invents_a_neutral_label(self) -> None:
        doc = Document.from_text(FORMATS["mimic_discharge"].text, uid="m")
        result = run(get("render.deid_restyle"), doc, LADDER[-1], mode="angle_tag")
        assert "<REDACTED>" in result.text

    def test_masks_inside_lab_blocks_are_reachable(self) -> None:
        """MIMIC lab lines are full of masks; declaring only DEID_PLACEHOLDER
        would leave them unreachable and silently halve eligibility."""
        doc = Document.from_text(FORMATS["mimic_discharge"].text, uid="m")
        result = run(get("render.deid_restyle"), doc, LADDER[-1])
        assert result.dose.eligible_n == doc.deid.count


class TestTaxonomyDoesNotDrift:
    """The generated taxonomy must match what the code actually declares.

    Keeping a reviewable table and typed declarations in sync by hand
    guarantees they diverge; committing the generated file like a lockfile and
    asserting equality here means the artifact reviewers read cannot disagree
    with what ran.
    """

    def test_committed_file_matches_the_code(self) -> None:
        on_disk = resource_bytes(taxonomy.TAXONOMY_FILE).decode("utf-8")
        assert on_disk == taxonomy.to_yaml(), (
            "taxonomy.yaml is stale; regenerate with `robustehr taxonomy --yaml > src/robustehr/resources/taxonomy.yaml`"
        )

    def test_every_operator_appears(self) -> None:
        listed = {entry["id"] for entry in taxonomy.build()["operators"]}
        assert listed == set(all_ids())

    def test_invariant_operators_name_a_checkable_projection(self) -> None:
        """An invariance claim with no projection is an assertion, not a proof."""
        for entry in taxonomy.build()["operators"]:
            if entry["contract"] == Contract.INVARIANT_BY_CONSTRUCTION.value:
                assert "canonicalizer" in entry, entry["id"]
                kappa.get(entry["canonicalizer"])  # raises if unknown

    def test_every_operator_documents_its_denominator(self) -> None:
        """This sentence is what tells a reader what "30%" was 30% of."""
        for entry in taxonomy.build()["operators"]:
            assert entry["denominator"].strip(), entry["id"]


class TestCatalogueDoesNotDrift:
    """Every operator must appear in the user-facing catalogue.

    `docs/corruption-catalogue.md` is what a user reads to decide what to
    corrupt. An operator that ships without a row there is one nobody will find,
    and prose drifts from code silently — `input.ocr_confusion` existed for a
    commit before anything documented it.
    """

    def test_every_operator_has_a_catalogue_entry(self) -> None:
        from pathlib import Path

        catalogue = Path(__file__).resolve().parents[2] / "docs" / "corruption-catalogue.md"
        text = catalogue.read_text(encoding="utf-8")
        missing = [
            op_id
            for op_id in all_ids()
            # `_llm` variants are documented as a suffix on their base row,
            # which is how they are meant to be read: same flip, other mechanism.
            if op_id not in text and op_id.replace("_llm", "") not in text
        ]
        assert not missing, f"operators absent from docs/corruption-catalogue.md: {missing}"


class TestCatalogueArithmetic:
    """The reconciliation summary must match the tables under it.

    `docs/corruption-catalogue.md` opens section 5 with "N implemented, M
    partial, K not built". That line is the one a reader quotes, and it was
    wrong twice: once written from memory (12/6/12 against tables holding
    9/6/15), and once against a source that was never recounted — the summary
    said 30 rows while the source taxonomy (`docs/source-taxonomy.md`) has 29
    and the status table had grown to 33 by splitting rows. All three tables
    are counted now, and their sum must equal the source's row count.
    """

    SOURCE_ROWS = 29  # docs/source-taxonomy.md — `git show 050a009^:prd/taxonomy.md`

    def test_the_summary_matches_the_tables(self) -> None:
        import re
        from pathlib import Path

        docs = Path(__file__).resolve().parents[2] / "docs"
        doc = (docs / "corruption-catalogue.md").read_text(encoding="utf-8")
        tail = doc[doc.index("### Kept and implemented") :]

        def table_rows(start: str, end: str) -> int:
            block = tail[tail.index(start) : tail.index(end)]
            rows = [
                line
                for line in block.splitlines()
                if line.startswith("|") and not re.match(r"\|[-: ]+\|", line)
            ]
            return len(rows) - 1  # drop the header row

        implemented = table_rows("### Kept and implemented", "### Partial")
        partial = table_rows("### Partial", "### Not built")
        not_built = table_rows("### Not built", "Two halves are worth singling out")
        claimed = re.search(r"\*\*(\d+) implemented, (\d+) partial, (\d+) not built\*\*", doc)
        assert claimed, "the reconciliation summary line is missing"
        said_impl, said_part, said_nb = (int(g) for g in claimed.groups())
        assert said_impl == implemented, f"summary says {said_impl}, table has {implemented}"
        assert said_part == partial, f"summary says {said_part}, table has {partial}"
        assert said_nb == not_built, f"summary says {said_nb}, table has {not_built}"
        assert implemented + partial + not_built == self.SOURCE_ROWS

        # The source itself must still have that many numbered rows.
        source = (docs / "source-taxonomy.md").read_text(encoding="utf-8")
        numbered = re.findall(r"^\| (\d+) \| ", source, flags=re.MULTILINE)
        assert [int(n) for n in numbered] == list(range(1, self.SOURCE_ROWS + 1))

    def test_status_table_classifies_every_source_row_once(self) -> None:
        """The status document carries the same 29 rows, numbered and classified once each."""
        import re
        from collections import Counter
        from pathlib import Path

        docs = Path(__file__).resolve().parents[2] / "docs"
        status = (docs / "corruption-taxonomy-status.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| (\d+) \| (✅|🟡|❌) \|", status, flags=re.MULTILINE)
        assert sorted(int(n) for n, _ in rows) == list(range(1, self.SOURCE_ROWS + 1))
        counts = Counter(mark for _, mark in rows)
        claimed = re.search(
            r"\*\*(\d+) implemented[ ,·]+(\d+) partial[ ,·]+(\d+) not built\*\*", status
        )
        assert claimed
        assert (counts["✅"], counts["🟡"], counts["❌"]) == tuple(int(g) for g in claimed.groups())

    def test_both_catalogues_agree(self) -> None:
        """Two documents describe the same 29 rows and must not disagree.

        `corruption-catalogue.md` explains the axes; `corruption-taxonomy-status.md`
        is the original taxonomy row-for-row. They were written at different
        times and already diverged once: gender-pronoun inconsistency was
        `partial` in one and `not built` in the other, which is the kind of
        contradiction a reader resolves by believing whichever they opened.
        """
        import re
        from pathlib import Path

        docs = Path(__file__).resolve().parents[2] / "docs"
        pattern = r"\*\*(\d+) implemented[ ,·]+(\d+) partial[ ,·]+(\d+) not built\*\*"
        counts = []
        for name in ("corruption-catalogue.md", "corruption-taxonomy-status.md"):
            found = re.search(pattern, (docs / name).read_text(encoding="utf-8"))
            assert found, f"{name} has no summary line"
            counts.append(found.groups())
        assert counts[0] == counts[1], f"catalogues disagree: {counts}"
