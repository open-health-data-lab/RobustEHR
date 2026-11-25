"""Applying one operator to one document, and accounting for what happened.

This is where the framework keeps the promises operators are not allowed to make
for themselves: scope filtering, protection subtraction, ``k`` computation and
hash-rank selection all happen here, once, for every operator.

The order is load-bearing and worth stating, because a different order changes
the reported denominator:

1. **All units** the operator declares eligible — ``total_n``.
2. **Scope filter** — ``scope_n``. Restricting to a section happens before
   protection so that ``protected_n`` counts what was withheld *inside the
   scope*, not across the whole document.
3. **Protection subtraction** — ``eligible_n``. A unit is withheld unless every
   protection covering it is soft and named in the operator's targets.
4. **k from severity**, in exact integer arithmetic over ``eligible_n``.
5. **Hash-rank selection**, which is what makes severity ladders nest.
6. **Propose**, then the applier resolves conflicts and reports ``applied_n``.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import TYPE_CHECKING, Any, TypedDict

from robustehr.categories import default_tuis, load_categories
from robustehr.concepts.matcher import MentionIndex
from robustehr.concepts.phenotype import PhenotypeIndex, protected_spans
from robustehr.document import Document
from robustehr.dose import DoseRecord, DoseStatus, canonical_params, resolve_status
from robustehr.edits import ApplyResult, apply_edits, levenshtein
from robustehr.lexical import resolve_tags
from robustehr.lexicon import DEFAULT_LEXICON, Lexicon
from robustehr.ops.base import OpContext, Operator, OperatorMeta, Scope
from robustehr.ops.registry import resolved_version
from robustehr.protect import ProtectionIndex, protect_document
from robustehr.protect.registry import build_index
from robustehr.rng import SeedMaterial, select, select_stratified, sha256_text
from robustehr.segment.tokens import tokenize
from robustehr.target import (
    AllOf,
    Everything,
    PhenotypeEvidence,
    Target,
    TargetContext,
    governs_used,
)
from robustehr.types import (
    Contract,
    CountSeverity,
    PhenotypeScope,
    RateSeverity,
    Severity,
    Span,
    Unit,
    UnitKind,
    requested_k,
)
from robustehr.version import SCHEMA_VERSION

if TYPE_CHECKING:  # pragma: no cover - the clinical extra is optional
    from robustehr.concepts.context import AssertionIndex


@dataclass(frozen=True, slots=True)
class OperatorResult:
    text: str
    dose: DoseRecord
    apply_result: ApplyResult

    @property
    def changed(self) -> bool:
        return self.text != "" and not self.apply_result.unchanged


def _in_scope(unit: Unit, ranges: tuple[Span, ...]) -> bool:
    return any(r.contains(unit.span) for r in ranges)


def _tokens_changed(before: str, after: str) -> int:
    """Token-level change count, as a magnitude alongside the character one.

    Deliberately a multiset difference rather than an alignment: it is a
    diagnostic reported next to ACER, not the primary intensity measure, and a
    full token alignment would cost more than it tells you.
    """
    left = [t.lower for t in tokenize(before).content()]
    right = [t.lower for t in tokenize(after).content()]
    counts: dict[str, int] = {}
    for token in left:
        counts[token] = counts.get(token, 0) + 1
    for token in right:
        counts[token] = counts.get(token, 0) - 1
    return sum(abs(v) for v in counts.values())


class _Landing(TypedDict):
    category_hits: dict[str, int]
    clinical_hits: int
    unknown_hits: int


def _landing_counts(doc, applied, lexicon) -> _Landing:  # type: ignore[no-untyped-def]
    """What kind of content did each applied edit land on?

    Reported per **semantic category** rather than as a clinical/non-clinical
    binary, because "clinical" is not a well-posed question and not what any use
    case wants to know. "This operator hit 12 medications and 3 diagnoses" is
    actionable; "it hit 40 clinical tokens" is not.

    An edit counts once per category it touches, so the counts overlap by design
    — ``dyspnea`` is both a symptom and a finding, and forcing a single label
    would discard real information.
    """
    known = set(load_categories())
    per_category: dict[str, int] = {}
    clinical = unknown = 0
    for edit in applied:
        words = {t.lower for t in doc.tokens.overlapping(edit.span)}
        categories: set[str] = set()
        for word in words:
            # resolve_tags applies the precedence: a general-English word is
            # reported as such rather than as whatever category UMLS also gives
            # it, so `home` does not count as a procedure hit.
            categories |= {t for t in resolve_tags(word, lexicon) if t in known}
        default_hit = any(lexicon.semantic_types(w) & default_tuis() for w in words)
        for category in categories:
            per_category[category] = per_category.get(category, 0) + 1
        if default_hit:
            clinical += 1
        elif not any(lexicon.classify_word(w).is_measured for w in words):
            unknown += 1
    return _Landing(
        category_hits=dict(sorted(per_category.items())),
        clinical_hits=clinical,
        unknown_hits=unknown,
    )


def _by_target(
    units: tuple[Unit, ...],
    target: Target,
    ctx: TargetContext,
) -> tuple[Unit, ...]:
    """Restrict units to those the target admits.

    An orthogonal modifier available to *every* operator, which is what makes
    "corrupt only the medications" a property of the run rather than a separate
    class of operator. It is also what makes a dose interpretable: the same
    operator at the same rate means something quite different depending on
    whether it landed on function words or on diagnoses.
    """
    if isinstance(target, Everything):
        return units
    return tuple(u for u in units if target.admits(u.span, ctx))


#: The strata a unit can be allocated across. One name today; the parameter is a
#: string rather than a boolean so a second stratifier (by section, by phenotype)
#: does not need a new keyword.
STRATIFIERS = ("semantic_category",)


def _stratum(unit: Unit, name: str, ctx: TargetContext) -> str:
    """Which stratum a unit belongs to, for proportional allocation.

    A concept can carry several categories — `dyspnea` is both a symptom and a
    finding — and a unit must land in exactly one stratum or proportional
    allocation stops being proportional. The **lexicographically first** category
    is used: arbitrary, deterministic, and stated, which is the honest form of a
    tie-break that has no principled answer. Units carrying no category share an
    `_uncategorized` stratum rather than being dropped.
    """
    if name != "semantic_category":  # pragma: no cover - guarded by the config layer
        raise ValueError(f"unknown stratifier {name!r}; known: {list(STRATIFIERS)}")
    categories = ctx.categories(unit.span)
    return min(categories) if categories else "_uncategorized"


def apply_operator(
    doc: Document,
    operator: Operator,
    meta: OperatorMeta,
    severity: Severity,
    *,
    scope: Scope | None = None,
    params: dict[str, object] | None = None,
    salt: str = "rep0",
    lexicon: Lexicon = DEFAULT_LEXICON,
    run_id: str = "run",
    stage_index: int = 0,
    protection: ProtectionIndex | None = None,
    phenotypes: PhenotypeIndex | None = None,
    phenotype_scope: PhenotypeScope = PhenotypeScope.AGNOSTIC,
    mentions: MentionIndex | None = None,
    assertions: AssertionIndex | None = None,
    stratify_by: str | None = None,
) -> OperatorResult:
    """Run one operator over one document and return text plus a dose record.

    ``phenotype_scope`` applies to **every** operator rather than to a
    phenotype-aware subset, which is the point: whether an edit landed on
    phenotype-related content is a property of where it landed, not of which
    operator proposed it. A whitespace collapse gets tagged exactly as a negation
    flip does.

    ``AGNOSTIC`` is first-class, not degraded. With no phenotype configured the
    clinical layer is skipped entirely, nothing here imports a matcher, and every
    RENDER, INPUT, LEXICAL and DISCOURSE operator runs at full fidelity.

    ``mentions`` is the concept index, when a matcher has annotated the
    document. It decides whether ``cat=`` / ``tui=`` / ``concept`` targets
    resolve at concept level or fall back to per-token lookup — the difference
    between ``chest pain`` resolving as one Sign or Symptom and as an anatomy
    token beside a symptom token. Which one applied is recorded on the dose row
    as ``target_resolution``, because a result that does not say cannot be
    compared with one that resolved differently.
    """
    scope = scope or Scope()
    params = params or {}
    evidence = phenotypes if phenotypes is not None else PhenotypeIndex()
    index = protection if protection is not None else protect_document(doc)
    if phenotype_scope is PhenotypeScope.PROTECT and evidence:
        # Every operator's eligible set shrinks by the same spans. Rebuilt rather
        # than mutated so the caller's index is not quietly altered between
        # operators, which would make results depend on run order.
        index = build_index([*index.spans, *protected_spans(evidence)])
    op_version = resolved_version(meta)

    material = SeedMaterial(
        salt=salt,
        note_uid=doc.uid,
        note_sha256=doc.sha256,
        op_id=meta.id,
        op_version=op_version,
        params_canon=canonical_params(params),
        scope_canon=scope.canon(),
        stage_index=stage_index,
        unit_kind=meta.dose.unit_kind.value,
    )
    fraction = severity.value if isinstance(severity, RateSeverity) else Fraction(0)
    ctx = OpContext(
        doc=doc,
        protection=index,
        scope=scope,
        params=params,
        material=material,
        lexicon=lexicon,
        severity_fraction=fraction,
    )

    all_units = tuple(operator.eligible(ctx))
    ranges = scope.restrict(doc)
    scoped = tuple(u for u in all_units if _in_scope(u, ranges))
    target = scope.resolved_target()
    if phenotype_scope is PhenotypeScope.TARGET and evidence:
        # Composed onto whatever was already asked for rather than replacing it,
        # so "corrupt medications" under target:[hypertension] means the
        # intersection — antihypertensives — not one or the other.
        target = AllOf(target, PhenotypeEvidence(*evidence.names))
    if assertions is None and governs_used(target):
        # Refuse rather than run. `Governs` with no index admits nothing, which
        # is indistinguishable from a document carrying no cues — and a note
        # full of cues reporting eligible_n=0 is exactly the failure this target
        # was added to fix. Unreachable for every target that existed before it.
        raise ValueError(
            "target governs(...) needs an assertion index; pass "
            "assertions=robustehr.concepts.pipeline.qualify_document(doc, mentions). "
            "Without it every cue is rejected and the run reports zero eligible "
            "units on a note full of cues"
        )
    target_ctx = TargetContext(
        doc=doc,
        lexicon=lexicon,
        protection=index,
        phenotypes=evidence,
        mentions=mentions,
        assertions=assertions,
    )
    scoped = _by_target(scoped, target, target_ctx)

    if meta.contract is Contract.CONTROL_NULL:
        # A null control cannot produce an edit, so nothing can be withheld from
        # it. Subtracting protection anyway would report eligible_n = 0 for the
        # one operator whose job is to demonstrate that the pipeline is quiet.
        eligible = scoped
    else:
        eligible = tuple(u for u in scoped if not index.blocks(u.span, meta.targets))

    k = requested_k(severity, len(eligible), meta.dose.sub_unit_policy)
    if stratify_by is not None and isinstance(severity, RateSeverity):
        # Proportional allocation per stratum instead of one uniform draw. Only
        # meaningful for a rate — a per-document count has no proportion to
        # allocate, so a count severity falls through to the uniform selector.
        selected = select_stratified(
            eligible,
            severity.value.numerator,
            severity.value.denominator,
            material,
            lambda u: _stratum(u, stratify_by, target_ctx),
        )
        k = len(selected)  # what proportional allocation actually asked for
    else:
        selected = select(eligible, k, material)
    proposed = tuple(operator.propose(ctx, selected))
    result = apply_edits(doc.text, proposed)

    status = resolve_status(
        total_n=len(all_units),
        scope_n=len(scoped),
        eligible_n=len(eligible),
        requested_k=k,
        applied_n=len(result.applied),
    )
    # A null control proposes nothing by design; that is success, not a failure
    # to change anything.
    if meta.contract is Contract.CONTROL_NULL:
        status = DoseStatus.APPLIED

    edited, edited_once = _token_damage(doc, result.applied)
    dose = DoseRecord(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        note_uid=doc.uid,
        note_sha256=doc.sha256,
        segmenter_version=doc.segmenter_version,
        op_id=meta.id,
        op_version=op_version,
        severity_canon=severity.canon(),
        scope_canon=scope.canon(),
        stage_index=stage_index,
        unit_kind=meta.dose.unit_kind.value,
        dose_kind=meta.dose.dose_kind,
        total_n=len(all_units),
        scope_n=len(scoped),
        protected_n=len(scoped) - len(eligible),
        eligible_n=len(eligible),
        requested_k=k,
        selected_n=len(selected),
        proposed_n=len(proposed),
        applied_n=len(result.applied),
        rejected_n=len(result.rejected),
        rejection_reasons=dict(result.rejection_counts),
        chars_removed=result.chars_removed,
        chars_added=result.chars_added,
        lines_added=result.lines_added,
        lines_removed=result.lines_removed,
        edit_cost=result.edit_cost,
        tokens_changed=_tokens_changed(doc.text, result.text),
        tokens_total=len(doc.tokens.content()),
        params=canonical_params(params),
        tokens_edited=edited,
        tokens_edited_once=edited_once,
        doc_chars=len(doc.text),
        status=status,
        output_sha256=sha256_text(result.text),
        output_identical=result.text == doc.text,
        resource_digests=dict(doc.resource_digests),
        **_landing_counts(doc, result.applied, lexicon),
        lexicon_source=lexicon.source,
        salt=salt,
        # `concept` or `token`. Without it a stored cell cannot say whether
        # `cat=medication` consulted the matcher or fell back to per-token
        # lookup, and the two select materially different spans.
        target_resolution=target_ctx.resolution,
        phenotype_scope=phenotype_scope.value,
        **_evidence_counts(evidence, result.applied),
    )
    return OperatorResult(text=result.text, dose=dose, apply_result=result)


def _token_damage(doc: Document, applied: Sequence[Any]) -> tuple[int, int]:
    """``(tokens edited, of which in exactly one character position)``.

    Only edits lying wholly inside one token count: a structural edit spanning a
    line has no per-token reading. The cost of an edit is the Levenshtein
    distance between what it replaced and what it wrote, so a whole-word typo
    replacement and a single-character OCR substitution both cost 1.
    """
    tokens = doc.tokens.content()
    starts = [t.span.start for t in tokens]
    cost: dict[int, int] = {}
    for edit in applied:
        if edit.copy_from is not None or edit.start == edit.end:
            continue
        i = bisect_right(starts, edit.start) - 1
        if i < 0 or edit.end > tokens[i].span.end:
            continue
        source = doc.text[edit.start : edit.end]
        cost[i] = cost.get(i, 0) + levenshtein(source, edit.replacement)
    changed = {i: c for i, c in cost.items() if c > 0}
    return len(changed), sum(1 for c in changed.values() if c == 1)


def _evidence_counts(evidence: PhenotypeIndex, applied: Sequence[Any]) -> dict[str, Any]:
    """Evidence available, evidence touched, and how much of it was affirmed.

    All three travel together because ``evidence_touch`` alone cannot be read.
    Zero against ``evidence_n = 0`` says the matcher found nothing; zero against
    ``evidence_n = 47`` says the operator stayed clear. Under ``protect`` those
    look identical in the touch column and opposite in meaning, which is the
    vacuous-zero failure the phenotype evaluation exists to bound.
    """
    if not evidence:
        return {}
    spans = [edit.span for edit in applied]
    touched = evidence.touched(spans)
    out: dict[str, Any] = {
        "evidence_n": {name: len(evidence.spans(name)) for name in evidence.names},
        "evidence_touch": touched,
        "evidence_n_by_tier": {name: evidence.declared_by_tier(name) for name in evidence.names},
        "evidence_touch_by_tier": {
            name: evidence.touched_by_tier(spans, name) for name in evidence.names
        },
    }
    # Omitted, not zeroed, when stage 8 never ran. An all-zero affirmed column
    # beside a non-zero touch column reads as "every touched mention was
    # negated", which is the opposite of what an absent contextualizer means.
    if not any(item.qualified for item in evidence.evidence):
        return out
    affirmed = {name: 0 for name in evidence.names}
    for item in evidence.evidence:
        if item.affirmed and any(item.span.overlaps(s) for s in spans):
            affirmed[item.phenotype] = affirmed.get(item.phenotype, 0) + 1
    out["evidence_touch_affirmed"] = affirmed
    return out


def severity_ladder(*literals: str) -> tuple[Severity, ...]:
    """Build a severity ladder from quoted literals.

    Quoted because the config layer refuses severities that arrive as YAML
    floats: ``0.1 + 0.2 != 0.3``, and a float on a control-flow path is how a
    dose-response curve stops being reproducible.

    ``count:N`` builds a per-document :class:`CountSeverity` instead of a rate,
    for operators whose quantity is a count rather than a fraction — section
    duplication asks for 1, 2 or 5 sections, and "50% of sections" would mean
    different things in notes of different length. Ladders still nest: hash-rank
    selection makes ``selected(1) ⊆ selected(2) ⊆ selected(5)`` for free.
    """
    return tuple(parse_severity(literal) for literal in literals)


def parse_severity(literal: str) -> Severity:
    """One severity literal: a quoted rate, or ``count:N`` per document."""
    if literal.startswith("count:"):
        digits = literal[len("count:") :]
        if not digits.isdigit():
            raise ValueError(f"count severity must be count:<non-negative int>, got {literal!r}")
        return CountSeverity(int(digits), UnitKind.DOCUMENT)
    return RateSeverity(literal)


__all__ = ["OperatorResult", "apply_operator", "parse_severity", "severity_ladder"]


def compose_operators(
    doc: Document,
    operators: Sequence[tuple[Operator, OperatorMeta]],
    severity: Severity,
    **kwargs: Any,
) -> OperatorResult:
    """Apply several operators to ONE document, in a single merged pass.

    **The gap this closes.** `cli.cmd_run` loops operators and calls
    :func:`apply_operator` once each, always against the *pristine* document, so
    N operators produced N independent edit scripts and never one composite
    note. A user asking for "typos AND a negation flip on the same note" could
    not get it, which is most of what layered real-world degradation looks like.

    **Single-pass merge, not sequential application.** Every operator proposes
    against the original offsets — which is already the architecture, operators
    being pure proposers of immutable edits — so the composite is the union of
    their proposals resolved once. Nothing is re-segmented or re-annotated
    between operators, and the stored edit script still references original
    offsets, so `replay` is unchanged: a composite cell is one edit list like
    any other.

    **Order-independent, which is stronger than promised.**
    `edits/apply.py::resolve` decides conflicts by a *content-derived total
    order*, not by the order proposals arrive, so composing ``a,b`` and ``b,a``
    yields the same bytes. The operator order is recorded in ``composed_of`` for
    provenance and has no effect on the outcome.

    **The losers are counted.** Two operators wanting the same span cannot both
    have it; the drop lands in ``conflicts_dropped`` rather than vanishing. A
    composite delivering less than the sum of its parts is expected — a
    composite delivering less *silently* would report a severity it did not
    achieve.
    """
    if not operators:
        raise ValueError("compose_operators needs at least one operator")

    # Parameters belong to one operator: they feed its seed, so handing every
    # part the same dict would reseed the operators that never read the key.
    params_by_op: Mapping[str, dict[str, object]] = kwargs.pop("params_by_op", None) or {}
    parts = [
        apply_operator(doc, op, meta, severity, params=params_by_op.get(meta.id), **kwargs)
        for op, meta in operators
    ]
    proposals = [edit for part in parts for edit in part.apply_result.applied]
    merged = apply_edits(doc.text, proposals)

    op_ids = tuple(meta.id for _, meta in operators)
    lexicon = kwargs.get("lexicon", DEFAULT_LEXICON)
    evidence = kwargs.get("phenotypes") or PhenotypeIndex()
    first = parts[0].dose
    # A composite is inapplicable only when EVERY part was; if one operator
    # found eligible units and simply proposed nothing, that is a zero dose and
    # must stay in the averages rather than being excluded as not-applicable.
    status = (
        DoseStatus.APPLIED
        if merged.applied
        else (
            DoseStatus.NA_NO_ELIGIBLE
            if all(p.dose.eligible_n == 0 for p in parts)
            else DoseStatus.APPLIED
        )
    )

    edited, edited_once = _token_damage(doc, merged.applied)
    dose = replace(
        first,
        op_id="composite(" + "+".join(op_ids) + ")",
        op_version="+".join(sorted({p.dose.op_version for p in parts})),
        # Denominators are summed across operators whose unit kinds differ —
        # tokens for one, sentences for another — so the sum counts different
        # things and `unit_kind` says `mixed` rather than implying otherwise.
        # A composite's interpretable numbers are its numerators and its bytes.
        unit_kind="mixed",
        dose_kind="+".join(sorted({p.dose.dose_kind for p in parts})),
        total_n=sum(p.dose.total_n for p in parts),
        scope_n=sum(p.dose.scope_n for p in parts),
        protected_n=sum(p.dose.protected_n for p in parts),
        eligible_n=sum(p.dose.eligible_n for p in parts),
        requested_k=sum(p.dose.requested_k for p in parts),
        selected_n=sum(p.dose.selected_n for p in parts),
        proposed_n=len(proposals),
        applied_n=len(merged.applied),
        rejected_n=len(merged.rejected),
        rejection_reasons=dict(merged.rejection_counts),
        conflicts_dropped=len(proposals) - len(merged.applied),
        composed_of=op_ids,
        chars_removed=merged.chars_removed,
        chars_added=merged.chars_added,
        lines_added=merged.lines_added,
        lines_removed=merged.lines_removed,
        edit_cost=merged.edit_cost,
        tokens_changed=_tokens_changed(doc.text, merged.text),
        tokens_edited=edited,
        tokens_edited_once=edited_once,
        status=status,
        output_sha256=sha256_text(merged.text),
        output_identical=merged.text == doc.text,
        **_landing_counts(doc, merged.applied, lexicon),
        **_evidence_counts(evidence, merged.applied),
    )
    return OperatorResult(text=merged.text, dose=dose, apply_result=merged)
