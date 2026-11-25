"""Dose accounting: what was asked for, what was eligible, what actually landed.

A severity is a request, not a result. "30%" means nothing until you say 30% of
*what*, how many of those the document contained, how many were withheld, and
how many edits survived conflict resolution. Every one of those numbers is
recorded per ``(note, operator, severity, scope)`` cell, as exact integers.

Three conventions here exist because their absence produces wrong figures rather
than missing ones:

* **Null is not zero.** An operator with no eligible units reports
  ``achieved = None``, never ``0``. Averaging zeros silently under-reports every
  operator across a corpus where it sometimes does not apply.
* **Plot achieved, never requested.** Sub-unit rounding, protection and conflict
  rejection all move the realized dose away from the request, so
  ``dose_inflation`` is a first-class field and figures use the achieved rate.
* **Rates serialize as integer pairs.** A float rate would make output
  byte-nonreproducible across platforms for no benefit; ``Fraction`` is exact
  and ``(numerator, denominator)`` round-trips.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction

from robustehr.types import SubUnitPolicy, UnitKind
from robustehr.version import SCHEMA_VERSION


class DoseStatus(StrEnum):
    APPLIED = "applied"
    NA_NO_ELIGIBLE = "na_no_eligible"
    """The document contained no unit of this kind that the operator could use.

    Distinct from a zero dose: the operator was not applicable here, and the
    cell must be excluded from averages rather than counted as "no effect".
    """
    NA_SCOPE_EMPTY = "na_scope_empty"
    """Units existed, but the requested scope selected none of them.

    Kept separate from NA_NO_ELIGIBLE so that "this operator does not apply to
    this corpus" and "this scope does not apply to this document" stay
    distinguishable in an applicability report.
    """
    NA_ALL_PROTECTED = "na_all_protected"
    """Units existed and were in scope, but every one was withheld."""
    SATURATED = "saturated"
    """More was requested than the document could supply."""
    UNDER_DOSED = "under_dosed"
    """Rounding produced zero applications despite a positive rate."""
    NO_CHANGE = "no_change"
    """Edits were proposed but none survived, so the output is identical."""


def ratio(numerator: int, denominator: int) -> Fraction | None:
    """An exact rate, or ``None`` when the denominator is zero.

    Returning ``None`` rather than ``0`` is load-bearing — see the module
    docstring.
    """
    if denominator == 0:
        return None
    return Fraction(numerator, denominator)


def as_pair(value: Fraction | None) -> tuple[int, int] | None:
    """Serialize a rate as integers, so output stays byte-reproducible."""
    if value is None:
        return None
    return (value.numerator, value.denominator)


@dataclass(frozen=True, slots=True)
class DoseSpec:
    """What an operator declares about its own denominator.

    ``denominator_doc`` is prose, and it is not decoration: it is the sentence
    that goes into the paper's methods table so a reader knows exactly what
    "30%" was 30% of.
    """

    unit_kind: UnitKind
    dose_kind: str = "rate"
    """``rate``, ``count_per_unit`` or ``count_per_doc``."""
    count_scope: UnitKind | None = None
    denominator_doc: str = ""
    sub_unit_policy: SubUnitPolicy = SubUnitPolicy.CEIL

    def __post_init__(self) -> None:
        if self.dose_kind not in {"rate", "count_per_unit", "count_per_doc"}:
            raise ValueError(f"unknown dose_kind {self.dose_kind!r}")
        if self.dose_kind == "count_per_unit" and self.count_scope is None:
            raise ValueError("count_per_unit requires a count_scope")


@dataclass(frozen=True, slots=True)
class DoseRecord:
    """One ``(note, operator, severity, scope)`` cell."""

    # -- provenance --------------------------------------------------------
    schema_version: str
    run_id: str
    note_uid: str
    note_sha256: str
    segmenter_version: str
    op_id: str
    op_version: str
    severity_canon: str
    scope_canon: str
    stage_index: int
    unit_kind: str
    dose_kind: str

    # -- denominators, integers only ---------------------------------------
    total_n: int
    """Units of this kind in the document, before any filter."""
    scope_n: int
    """After the scope filter."""
    protected_n: int
    """Removed by the protection registry."""
    eligible_n: int
    """scope ∩ ¬protected ∩ operator-specific eligibility."""

    # -- numerators --------------------------------------------------------
    requested_k: int
    selected_n: int
    proposed_n: int
    applied_n: int
    rejected_n: int
    rejection_reasons: dict[str, int]

    # -- magnitude ---------------------------------------------------------
    chars_removed: int
    chars_added: int
    lines_added: int
    lines_removed: int
    edit_cost: int
    """Sum of per-edit Levenshtein distance. Numerator of ACER."""
    tokens_changed: int
    tokens_total: int
    doc_chars: int

    status: DoseStatus
    output_sha256: str
    output_identical: bool
    resource_digests: dict[str, str] = field(default_factory=dict)

    # -- where the edits landed --------------------------------------------
    clinical_hits: int = 0
    """Applied edits overlapping a token classified clinical.

    The number that makes a dose interpretable. A typo operator at 30% means
    something entirely different depending on whether it landed on function
    words or on diagnostic terms, and reporting only the rate hides that.
    """
    category_hits: dict[str, int] = field(default_factory=dict)
    """Applied edits per semantic category — medication, disease, symptom, …

    The number that makes a dose interpretable, and the reason the package
    stopped asking whether a token is "clinical". Counts overlap by design: an
    edit on ``dyspnea`` is both a symptom and a finding.
    """
    nonclinical_hits: int = 0
    unknown_hits: int = 0
    """Edits on tokens no tier could classify. Kept separate from
    ``nonclinical_hits`` so that "measured non-clinical" and "no evidence" do
    not silently merge."""
    lexicon_source: str = "morphology-only"

    # -- reproduction ------------------------------------------------------
    salt: str = "rep0"
    """The run's seed salt. On the row, not only in the manifest.

    A `dose.jsonl` line is routinely read on its own — pooled across runs,
    filtered, replotted. Without the salt such a line cannot reproduce its own
    selection, which makes it a number with no provenance rather than a
    measurement.
    """
    target_resolution: str = "token"
    """``concept`` when a matcher supplied mentions, ``token`` otherwise.

    ``cat=medication`` means different things under the two: concept resolution
    answers *span -> concept -> semantic types*, token resolution answers
    *token -> semantic types* and cannot see a multi-word drug name at all.
    Recorded because two cells that resolved differently are not comparable and
    nothing else in the row would say so.
    """

    # -- parameters and per-token damage -------------------------------------
    params: str = ""
    """Canonical operator parameters (``key=value;...``), empty when none.

    The same string that feeds the seed. Recorded because two cells that differ
    only in a parameter, an OCR arm capped at one edit per token against an
    uncapped one, are different interventions under the same operator id,
    version and severity.
    """
    tokens_edited: int = 0
    """Tokens that contain at least one applied edit lying wholly inside them."""
    tokens_edited_once: int = 0
    """Of :attr:`tokens_edited`, those altered in exactly one character position.

    Coverage is not damage. A dose counted in character positions can land
    several times in one word, so two arms at the same nominal rate may differ
    in how much of each word survives. This pair makes that visible per cell.
    """

    # -- composition -------------------------------------------------------
    conflicts_dropped: int = 0
    """Edits lost to another operator when several were composed onto one note.

    Zero for a single-operator cell. Non-zero only under ``run --compose``,
    where each operator proposes against the pristine document and the merged
    list is resolved once: two operators wanting the same span cannot both have
    it, and the loser is counted here rather than vanishing.

    It belongs in the dose ledger for the same reason `rejected_n` does. A
    composite that delivers less than the sum of its parts is the expected case,
    not a bug — but a composite that delivers less *without saying so* would
    report a severity it did not achieve, which is the one thing this record
    exists to prevent.
    """
    composed_of: tuple[str, ...] = ()
    """The operator ids merged into this cell, in the order the user gave them.

    Recorded for provenance only. Conflict resolution is by a content-derived
    total order (`edits/apply.py::resolve`), so the composite is INVARIANT to
    this order — ``a,b`` and ``b,a`` produce the same bytes.
    """

    # -- phenotype relatedness ---------------------------------------------
    phenotype_scope: str = "agnostic"
    """Which run mode produced this cell. ``agnostic`` means no phenotype was
    configured and the three fields below carry no information."""
    evidence_n: dict[str, int] = field(default_factory=dict)
    """Evidence spans this phenotype had in the document, before any edit.

    The denominator ``evidence_touch`` needs, and the field that keeps a zero
    honest: ``evidence_touch = 0`` against ``evidence_n = 0`` says the matcher
    found nothing, which is a different claim from ``evidence_touch = 0``
    against ``evidence_n = 47``.
    """
    evidence_n_by_tier: dict[str, dict[str, int]] = field(default_factory=dict)
    """``evidence_n`` split by tier, per phenotype: how each span was admitted.

    Tiers are the concept facets (``disorder``, ``medication``, ``finding``,
    ``proposed``, ``closure``) and the two surface tiers (``anchor``, the
    diagnosis as written, and ``associated``). Reach is only readable by tier:
    an arm that touched every declared span may still have reached none of the
    written diagnosis, and the total cannot show that.
    """
    evidence_touch_by_tier: dict[str, dict[str, int]] = field(default_factory=dict)
    """``evidence_touch`` split by tier, per phenotype. Divides cleanly by
    :attr:`evidence_n_by_tier` into a reach fraction."""
    evidence_touch: dict[str, int] = field(default_factory=dict)
    """Evidence spans intersected by an applied edit, per phenotype.

    The empirical replacement for the folk preserving/altering split. Under
    ``protect`` this must be 0 by construction; under any other mode it is a
    measured rate, never an assumption.
    """
    evidence_touch_affirmed: dict[str, int] = field(default_factory=dict)
    """Of those, the ones on affirmed evidence.

    Reported separately because 30.1% of phenotype evidence is negated,
    historical, uncertain or someone else's, and an edit landing on
    ``denies chest pain`` means something different from one landing on
    ``severe chest pain``.

    **Absent, not zero, when stage 8 did not run.** An unqualified span is
    unknown rather than affirmed, so this key is omitted entirely rather than
    reported as all-zero — which beside a non-zero ``evidence_touch`` would read
    as "every touched mention was negated", the opposite of what it means.
    """

    # -- derived rates -----------------------------------------------------

    @property
    def achieved_eligible(self) -> Fraction | None:
        """The rate that figures should be plotted against."""
        return ratio(self.applied_n, self.eligible_n)

    @property
    def achieved_total(self) -> Fraction | None:
        return ratio(self.applied_n, self.total_n)

    @property
    def eligibility_rate(self) -> Fraction | None:
        """How much of the document this operator could even consider."""
        return ratio(self.eligible_n, self.total_n)

    @property
    def dose_inflation(self) -> Fraction | None:
        """Achieved over requested.

        Above 1 means rounding pushed the realized dose up — the expected
        consequence of ceiling a sub-unit request, and the reason figures use
        the achieved rate rather than the nominal one.
        """
        if self.requested_k == 0:
            return None
        return ratio(self.applied_n, self.requested_k)

    @property
    def acer(self) -> Fraction | None:
        """Aligned character edit rate: edit cost over document length.

        Named for what it is. It is the cost of the alignment *induced by the
        edit script*, not a global Levenshtein distance, which would be
        infeasible to compute over a full sweep and is not what this measures.
        """
        return ratio(self.edit_cost, self.doc_chars)

    @property
    def token_change_rate(self) -> Fraction | None:
        return ratio(self.tokens_changed, self.tokens_total)

    @property
    def clinical_hit_rate(self) -> Fraction | None:
        """Share of applied edits that landed on clinical content."""
        return ratio(self.clinical_hits, self.applied_n)

    def category_hit_rate(self, category: str) -> Fraction | None:
        """Share of applied edits that landed on one semantic category."""
        return ratio(self.category_hits.get(category, 0), self.applied_n)

    @property
    def is_applicable(self) -> bool:
        return self.status not in {
            DoseStatus.NA_NO_ELIGIBLE,
            DoseStatus.NA_SCOPE_EMPTY,
            DoseStatus.NA_ALL_PROTECTED,
        }

    def to_row(self) -> dict[str, object]:
        """A flat, serializable row. Rates become integer pairs."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "note_uid": self.note_uid,
            "note_sha256": self.note_sha256,
            "segmenter_version": self.segmenter_version,
            "op_id": self.op_id,
            "op_version": self.op_version,
            "severity": self.severity_canon,
            "scope": self.scope_canon,
            "stage_index": self.stage_index,
            "unit_kind": self.unit_kind,
            "dose_kind": self.dose_kind,
            "total_n": self.total_n,
            "scope_n": self.scope_n,
            "protected_n": self.protected_n,
            "eligible_n": self.eligible_n,
            "requested_k": self.requested_k,
            "selected_n": self.selected_n,
            "proposed_n": self.proposed_n,
            "applied_n": self.applied_n,
            "rejected_n": self.rejected_n,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
            "chars_removed": self.chars_removed,
            "chars_added": self.chars_added,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "edit_cost": self.edit_cost,
            "tokens_changed": self.tokens_changed,
            "tokens_total": self.tokens_total,
            "doc_chars": self.doc_chars,
            "achieved_eligible": as_pair(self.achieved_eligible),
            "achieved_total": as_pair(self.achieved_total),
            "eligibility_rate": as_pair(self.eligibility_rate),
            "dose_inflation": as_pair(self.dose_inflation),
            "acer": as_pair(self.acer),
            "token_change_rate": as_pair(self.token_change_rate),
            "clinical_hits": self.clinical_hits,
            "category_hits": dict(sorted(self.category_hits.items())),
            "nonclinical_hits": self.nonclinical_hits,
            "unknown_hits": self.unknown_hits,
            "lexicon_source": self.lexicon_source,
            "salt": self.salt,
            "target_resolution": self.target_resolution,
            "params": self.params,
            "tokens_edited": self.tokens_edited,
            "tokens_edited_once": self.tokens_edited_once,
            "conflicts_dropped": self.conflicts_dropped,
            "composed_of": list(self.composed_of),
            "phenotype_scope": self.phenotype_scope,
            "evidence_n": dict(sorted(self.evidence_n.items())),
            "evidence_touch": dict(sorted(self.evidence_touch.items())),
            "evidence_n_by_tier": _nested(self.evidence_n_by_tier),
            "evidence_touch_by_tier": _nested(self.evidence_touch_by_tier),
            "evidence_touch_affirmed": dict(sorted(self.evidence_touch_affirmed.items())),
            "clinical_hit_rate": as_pair(self.clinical_hit_rate),
            "status": self.status.value,
            "output_sha256": self.output_sha256,
            "output_identical": self.output_identical,
            "resource_digests": dict(sorted(self.resource_digests.items())),
        }


def _nested(counts: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """A two-level count table with both levels in sorted order."""
    return {name: dict(sorted(tiers.items())) for name, tiers in sorted(counts.items())}


def resolve_status(  # noqa: PLR0911 - one return per documented outcome
    *,
    total_n: int,
    scope_n: int,
    eligible_n: int,
    requested_k: int,
    applied_n: int,
) -> DoseStatus:
    """Classify a cell, keeping the several kinds of "nothing happened" apart.

    "The operator does not apply to this note", "the scope excluded everything",
    "protection withheld everything", "the rate rounded to zero" and "edits were
    proposed but all conflicted" have different meanings for an applicability
    report and for an average, so they are different statuses rather than a
    shared zero.
    """
    if total_n == 0:
        return DoseStatus.NA_NO_ELIGIBLE
    if scope_n == 0:
        return DoseStatus.NA_SCOPE_EMPTY
    if eligible_n == 0:
        return DoseStatus.NA_ALL_PROTECTED
    if requested_k == 0:
        return DoseStatus.UNDER_DOSED
    if applied_n == 0:
        return DoseStatus.NO_CHANGE
    if requested_k > eligible_n:
        return DoseStatus.SATURATED
    return DoseStatus.APPLIED


def canonical_params(params: dict[str, object]) -> str:
    """Canonicalize operator parameters for the seed material.

    **Severity must not appear here.** It is excluded from the seed so that
    severity ladders nest; letting it back in through a parameter dict would
    silently break that and start mixing dose with resampling noise. Any key
    that looks like a severity is rejected rather than quietly dropped.
    """
    for key in params:
        if "sever" in key.lower() or key.lower() in {"rate", "dose", "k"}:
            raise ValueError(
                f"{key!r} must not be part of params_canon: severity is deliberately "
                "excluded from the seed so that severity ladders nest"
            )
    return ";".join(f"{k}={params[k]}" for k in sorted(params))


def scope_canon(
    *,
    section: str | None = None,
    target_mode: str = "all",
    target: str = "all",
    phenotype_scope: str = "agnostic",
    phenotypes: tuple[str, ...] = (),
) -> str:
    """Canonical, order-stable scope string for the seed and the dose record.

    ``target`` is appended only when it restricts something, so a run with no
    target produces the same canon it always did — and therefore the same seed,
    and therefore the same edits. Adding a capability must not silently
    invalidate every edit script recorded before it existed.
    """
    parts = [f"target={target_mode}", f"pheno={phenotype_scope}"]
    if target and target != "all":
        parts.append(f"sel={target}")
    if section:
        parts.append(f"section={section}")
    if phenotypes:
        parts.append("p=" + ",".join(sorted(phenotypes)))
    return "|".join(parts)


def new_record_defaults() -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION}


__all__ = [
    "DoseRecord",
    "DoseSpec",
    "DoseStatus",
    "as_pair",
    "canonical_params",
    "new_record_defaults",
    "ratio",
    "resolve_status",
    "scope_canon",
]
