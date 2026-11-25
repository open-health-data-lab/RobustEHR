"""Phenotype evidence over a document: declaration, expansion, and lookup.

The runtime half of the phenotype layer. Declaring a phenotype and expanding it
through the hierarchy is a build-time concern; this is what a *run* consults, and
it is deliberately small — given a document's concept mentions and a set of
declared phenotypes, which spans are evidence for which phenotype.

**Why this is a run-level concern and not an operator one.** Whether a
perturbation landed on phenotype-related content has to be knowable for *every*
operator, including ones with nothing clinical about them. A whitespace collapse,
an ASR confusion and a negation flip all need the same answer to "did this touch
hypertension?", and the answer is a property of *where the edit landed* rather
than of which operator proposed it. So phenotype relatedness is an attribute
attached to every applied edit, and :class:`~robustehr.types.PhenotypeScope` is a
property of the run.

**Set membership, not linking.** Evidence is "this mention's concept is in the
phenotype's set", never "which of 3.1 million concepts is this". The difference
is measured: set recall 0.698 against 0.175 for open-vocabulary linking on the
same notes. See ``docs/targeting-design.md``.

**Assertion is carried, never filtered on.** 30.1% of gold phenotype evidence is
non-affirmed, so the attribute matters — but a negated mention is still a mention
whose corruption changes what the note says, so ``protect`` withholds it and
``target`` corrupts it exactly as it would an affirmed one. Assertion travels
alongside the evidence for *reporting*; it never decides eligibility.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from robustehr.concepts import surface
from robustehr.concepts.hierarchy import Hierarchy
from robustehr.concepts.matcher import MentionIndex
from robustehr.protect.registry import ProtectedSpan, Strength
from robustehr.resources import load_yaml, optional_resource_sha256
from robustehr.types import ProtectionClass, Span


@dataclass(frozen=True, slots=True)
class Phenotype:
    """A declared concept set: seeds plus their descendant closure.

    Materialized in **both** identifier systems on purpose. Our matcher emits
    CUIs and gold standards carry source codes, so testing each side in its own
    namespace avoids a lossy round trip that would otherwise be scored as a
    matcher error.
    """

    name: str
    seed_codes: tuple[str, ...]
    """Source identifiers, as a clinician would name them."""
    concept_cuis: frozenset[str]
    """What mentions are tested against — they carry CUIs natively."""
    concept_codes: frozenset[str]
    """What annotations are tested against — they carry source codes natively."""
    facet_sizes: Mapping[str, int] = field(default_factory=dict)
    """Concepts contributed by each facet, or empty when none were loaded.

    Empty and ``{"disorder": n, "medication": 0, ...}`` are different states and
    a reader has to be able to tell them apart: the first means the facet
    artifacts were absent, the second means they were consulted and this
    phenotype genuinely has no drugs. Reporting either as a bare total is how
    the facets came to be built and never loaded.
    """
    facet_cuis: Mapping[str, frozenset[str]] = field(default_factory=dict)
    """Which concepts each facet contributed, not merely how many.

    :attr:`facet_sizes` records counts, and counts are where the facet
    information stopped: a mention became an `Evidence` record through a flat
    membership test, so by the time anything downstream saw it the tier that
    admitted it was gone. An experiment could then say "we corrupted this
    phenotype's evidence" but never *which* evidence — whether it reached the
    diagnosis or spent its whole dose on symptoms the patient happened to have.

    Kept as sets rather than a CUI-to-tier mapping because the facets are a
    lattice and not a partition: a concept can arrive through more than one, and
    flattening to one label at build time would pick a winner silently.
    :meth:`tier_of` picks it explicitly, at the point of use, in a documented
    order.
    """
    anchors: Any = None
    """This phenotype's surface warrant, a :class:`~robustehr.concepts.surface.AnchorSet`.

    ``None`` means the anchor resource was absent, which degrades to CUI
    membership alone — the pre-anchor behaviour. Typed loosely to keep the
    import out of this module's header; see :func:`build`.
    """

    @property
    def size(self) -> int:
        return len(self.concept_cuis)

    def contains(self, cui: str) -> bool:
        return cui in self.concept_cuis

    def tier_of(self, cui: str) -> str:
        """Which facet admitted this concept, most specific first.

        The order is ``disorder``, ``medication``, ``finding``, ``proposed``,
        ``closure``, and it is a claim about *evidential directness* rather than
        about set size: a concept in the disorder closure is the disease itself
        or a subtype of it, while one arriving only through the one-hop
        neighbourhood is a lateral relative. Where a concept is in both, the
        stronger warrant is the honest label.

        Returns ``"unknown"`` when the facet artifacts were never loaded, which
        is distinct from ``"closure"`` and must stay distinct: one says the
        concept came in weakly, the other says nobody asked.
        """
        if not self.facet_cuis:
            return "unknown"
        for tier in ("disorder", "medication", "finding", "proposed", "closure"):
            if cui in self.facet_cuis.get(tier, frozenset()):
                return tier
        return "unknown"


def declare(
    name: str,
    seed_codes: Sequence[str],
    hierarchy: Hierarchy,
    code_to_cuis: dict[str, list[str]],
    cui_to_codes: dict[str, list[str]],
    *,
    max_depth: int = 6,
) -> Phenotype:
    """Expand seed codes to a concept set through the hierarchy.

    **A source code can carry more than one CUI**, and taking the first is a
    silent failure: ``84114007`` (Heart failure) maps to both ``C0018801``, the
    concept with the descendants, and ``C1959583``, a childless duplicate.
    Picking arbitrarily collapsed heart failure to a one-element set that matched
    nothing, and reported that as "no evidence exists". Every CUI a seed code
    carries is therefore a seed.
    """
    seed_cuis = [cui for code in seed_codes for cui in code_to_cuis.get(code, ())]
    cuis = hierarchy.descendants(*seed_cuis, max_depth=max_depth)
    codes = {code for cui in cuis for code in cui_to_codes.get(cui, ())}
    return Phenotype(
        name=name,
        seed_codes=tuple(seed_codes),
        concept_cuis=cuis,
        concept_codes=frozenset(codes | set(seed_codes)),
    )


def load_maps(root: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Source code -> every CUI carrying it, and the inverse.

    Both directions are one-to-many. Flattening either loses concepts, which is
    what :func:`declare` documents.
    """
    cui_to_codes: dict[str, list[str]] = json.loads(
        (root / "cui_snomed.json").read_text(encoding="utf-8")
    )
    code_to_cuis: dict[str, list[str]] = {}
    for cui, codes in sorted(cui_to_codes.items()):
        for code in codes:
            code_to_cuis.setdefault(code, []).append(cui)
    return code_to_cuis, cui_to_codes


@dataclass(frozen=True, slots=True)
class Definition:
    """A declared phenotype, before expansion.

    Carries its own measured recall because every protect-mode result is
    conditional on it. A phenotype whose evidence the matcher only finds 45% of
    supports a much weaker claim than one at 91%, and burying that in a separate
    document is how it gets forgotten.
    """

    name: str
    label: str
    seeds: tuple[str, ...]
    finding_seeds: tuple[str, ...] = ()
    """Seeds for the FINDING facet, declared because they cannot be derived.

    UMLS has no relation that answers "what are the findings of heart failure".
    Asked, it offers ``has_associated_finding`` (*H/O: heart failure*, *Family
    history of heart failure* — assertion variants of the disease itself) and
    OMIM's ``has_manifestation`` (the inverse relation: genetic syndromes that
    manifest heart failure). Neither returns dyspnea. So the symptoms of a
    phenotype are named, then expanded by the same descendant closure as the
    disorder facet — deterministic given the seeds, with the seeds curated.
    See ``concepts/facets.py``.
    """
    medication_seeds: tuple[str, ...] = ()
    """Extra drug **CUIs** for the MEDICATION facet, where the vocabulary lags.

    MED-RT supplies the facet, and it is a curated source, but curation has a
    date. SGLT2 inhibitors carry no ``may_treat`` edge to heart failure in
    2026AA, so ``empagliflozin`` was unreachable from any seed however the
    closure was walked — the relation does not exist to traverse. Declaring the
    concept is the only honest fix; inferring it would mean loosening the
    traversal until something appeared, which is how *ciprofloxacin* arrived for
    C. difficile.

    CUIs rather than SNOMED codes, because drugs live in RxNorm and a SNOMED
    code would need a crosswalk that loses ingredients. Still identifiers only.
    """
    measured_set_recall: float | None = None
    measured_set_precision: float | None = None
    gold_evidence_spans: int | None = None
    measured_union_recall: float | None = None
    """Recall over the set a ``pheno=X`` target actually selects: every facet.

    **Not a better version of** :attr:`measured_set_recall`, **and not
    comparable to it.** The two have different denominators, by up to two orders
    of magnitude: `hfpef` has 7 gold spans in its disorder facet and 777 in the
    union, so 0.000 -> 0.781 is not an improvement in finding heart failure with
    preserved ejection fraction. It is a different question answered over a much
    larger evidence base.

    What it bounds is **targeting coverage** — how much of the set a corruption
    aimed at this phenotype can actually reach — which is what this package
    does. It does not bound phenotype identification: recovering *sodium* or
    *fatigue* is not evidence of C. difficile, and both are in that union.

    Its one unambiguous benefit is that it exists at all for the three
    phenotypes whose disorder facet the corpus could not measure
    (`rheumatoid_arthritis` 2 spans -> 372, `systemic_lupus_erythematosus`
    1 -> 374, `clostridioides_difficile` 1 -> 933).
    """
    union_gold_spans: int | None = None
    """The union's denominator. Reported because the two recalls do not share one."""
    max_depth: int | None = None
    """Override the file-wide closure depth for this phenotype alone.

    Needed because one bad edge can poison one seed and no other. Pulmonary
    embolism reaches *Vascular Diseases* (C0042373) through a single ``MTH RN``
    hop, and at the shipped depth of 6 its set is 9,712 concepts with a measured
    precision of 0.049. Bounding that one phenotype to depth 1 costs recall
    (0.67 -> 0.36) and buys a set that means what it says (precision 0.77).

    A global depth cannot express this: lowering it for everyone would gut the
    phenotypes whose closures are well behaved.
    """
    cohorts: tuple[str, ...] = ()
    """Named groups this phenotype belongs to, e.g. ``mipa``.

    Lets a study select its whole panel without restating it, and records which
    definitions exist to serve which study.
    """
    note: str = ""


@lru_cache(maxsize=1)
def load_definitions() -> dict[str, Definition]:
    """The shipped phenotype definitions, by name.

    Identifiers only — no UMLS strings ship with the package.
    """
    raw = load_yaml("phenotypes.yaml")
    return {
        str(d["name"]): Definition(
            name=str(d["name"]),
            label=str(d["label"]),
            seeds=tuple(str(x) for x in d["seeds"]),
            finding_seeds=tuple(str(x) for x in d.get("finding_seeds", ())),
            medication_seeds=tuple(str(x) for x in d.get("medication_seeds", ())),
            measured_set_recall=d.get("measured_set_recall"),
            measured_set_precision=d.get("measured_set_precision"),
            gold_evidence_spans=d.get("gold_evidence_spans"),
            measured_union_recall=d.get("measured_union_recall"),
            union_gold_spans=d.get("union_gold_spans"),
            max_depth=d.get("max_depth"),
            cohorts=tuple(str(c) for c in d.get("cohorts", ())),
            note=str(d.get("note", "")).strip(),
        )
        for d in raw["phenotypes"]
    }


def in_cohort(name: str) -> tuple[str, ...]:
    """Every declared phenotype belonging to a named cohort, e.g. ``mipa``."""
    return tuple(n for n, d in load_definitions().items() if name in d.cohorts)


def build(
    names: Sequence[str],
    hierarchy: Hierarchy,
    code_to_cuis: dict[str, list[str]],
    cui_to_codes: dict[str, list[str]],
    *,
    max_depth: int = 6,
    facets: bool = True,
) -> list[Phenotype]:
    """Expand named shipped definitions into concept sets.

    ``facets`` folds in the MEDICATION and FINDING facets when their artifacts
    are present. **It defaults on because the alternative was a silent hole.**
    Those facets are built, vetted and measured — hypertension declares 1,074
    concepts and 53 of hfpef's are drugs — and nothing consumed them, so a run
    carried only the disorder closure: 361 concepts for hypertension, 8 for
    hfpef, and over 1,388 MIMIC notes zero medication, procedure, symptom or lab
    evidence. That made ``--target 'all(cat=medication;pheno=heart_failure)'``
    the empty set for a reason no reader could see from the artifact.

    Missing artifacts are not an error. `data/umls_facets.json` is derived from
    a licensed release, so an install without it falls back to the disorder
    closure — the same behaviour as before, now reported rather than assumed:
    :attr:`Phenotype.facet_sizes` is empty and says so.
    """
    definitions = load_definitions()
    unknown = [n for n in names if n not in definitions]
    if unknown:
        raise KeyError(f"unknown phenotype(s) {unknown}; known: {sorted(definitions)}")
    edges = _load_facet_edges() if facets else None
    # Absent resource means an empty mapping, so a phenotype simply gets no
    # anchors and falls back to CUI membership. Same degradation as the facets.
    declared_anchors = surface.load_anchors()
    return [
        replace(
            _with_facets(
                declare(
                    name,
                    definitions[name].seeds,
                    hierarchy,
                    code_to_cuis,
                    cui_to_codes,
                    # The definition's own bound wins where it has one — a phenotype
                    # whose closure is poisoned at a given depth stays bounded however
                    # the caller was configured.
                    max_depth=definitions[name].max_depth or max_depth,
                ),
                definitions[name],
                hierarchy,
                code_to_cuis,
                cui_to_codes,
                edges,
            ),
            anchors=declared_anchors.get(name),
        )
        for name in names
    ]


NONSPECIFIC_RESOURCE = "phenotype_nonspecific.yaml"


@lru_cache(maxsize=1)
def load_nonspecific() -> frozenset[str]:
    """Concepts that appear across too many unrelated phenotypes to discriminate.

    The measured form of an argument methodology 14 already makes in prose: a
    concept true of most hospitalized patients associates with every phenotype
    at once and therefore with none. Stated that way it is a vetting
    instruction, and a model applying it one concept at a time cannot see how
    many *other* sets the same concept sits in. Counted across the declared
    panel, it becomes a property of the terminology rather than a judgement, and
    it needs no corpus to establish.

    "Unrelated" is load-bearing and is computed, not assumed. `heart_failure`,
    `hfpef` and `hfref` share concepts because they are the same disease
    family — penalising that overlap would delete the very concepts those
    phenotypes are built from. The screen counts distinct *families*, grouped by
    seed ancestry in the hierarchy; see ``phenotype_specificity.py``.

    Empty when the resource has not been built, which leaves the sets exactly as
    they were. Same degradation as the facets and the anchors.
    """
    try:
        raw: Any = load_yaml(NONSPECIFIC_RESOURCE)
    except FileNotFoundError:
        return frozenset()
    if not raw:
        return frozenset()
    return frozenset(str(c) for c in raw.get("cuis", ()))


#: Every packaged resource a ``pheno=`` target is built from. Named in the run
#: manifest whether or not it ships, so two corpora built under different
#: targets are distinguishable from their artifacts alone.
TARGETING_RESOURCES: tuple[str, ...] = (
    "phenotypes.yaml",
    "phenotype_vetting.yaml",
    "phenotype_closure.yaml",
    "phenotype_proposals.yaml",
    surface.ANCHORS_RESOURCE,
    NONSPECIFIC_RESOURCE,
)


def _file_digest(path: Path | None) -> str:
    """``sha256`` of a locally built input, or ``"absent"``."""
    if path is None or not path.is_file():
        return "absent"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def surface_only(names: Sequence[str]) -> list[Phenotype]:
    """The declared phenotypes on the surface warrant alone.

    What a run gets when no licensed terminology is on the machine: each
    phenotype carries its declared surface forms and an empty concept set, so
    ``pheno=`` targets the diagnosis as written and nothing the concept warrant
    would add (medications, findings, hierarchy descendants). The manifest
    records ``warrants: ["surface"]`` so the artifact says which target it was.
    """
    definitions = load_definitions()
    unknown = [n for n in names if n not in definitions]
    if unknown:
        raise KeyError(f"unknown phenotype(s) {unknown}; known: {sorted(definitions)}")
    return [
        Phenotype(
            name=name,
            seed_codes=tuple(definitions[name].seeds),
            concept_cuis=frozenset(),
            concept_codes=frozenset(),
            anchors=surface.anchors_for(name),
        )
        for name in names
    ]


def targeting_manifest(
    *,
    isa: Path | None = None,
    crosswalk: Path | None = None,
    warrants: Sequence[str] = ("concept", "surface"),
) -> dict[str, Any]:
    """What a phenotype target was built from, for the run manifest.

    A ``pheno=`` target is a function of resources no operator version covers:
    the declared definitions, the vetting verdicts, the closure candidates, the
    proposals, the surface anchors and the locally built terminology inputs.
    Under the same operator version and salt, two runs built under different
    targets select different units, so the artifact has to say which target
    produced it. Every key is present in every manifest; ``"absent"`` is a
    reportable value and is never omitted.
    """
    from robustehr.concepts import facets as facets_mod

    provenance = surface.anchor_provenance()
    vetting: Any = None
    try:
        vetting = load_yaml("phenotype_vetting.yaml")
    except FileNotFoundError:
        vetting = None
    return {
        "warrants": list(warrants),
        "resources": {name: optional_resource_sha256(name) for name in TARGETING_RESOURCES},
        "targeting_digest": surface.targeting_digest(),
        "anchors_vetted_by": provenance["vetted_by"],
        "vetting_vetted_by": str((vetting or {}).get("vetted_by") or "absent"),
        "external": {
            "umls_facets.json": _file_digest(facets_mod.DEFAULT_EDGES),
            "umls_isa": _file_digest(isa),
            "crosswalk": _file_digest(crosswalk / "cui_snomed.json" if crosswalk else None),
        },
    }


def _load_facet_edges() -> Any | None:
    """The MED-RT/SNOMED edge list, or ``None`` when it has not been built."""
    from robustehr.concepts import facets as facets_mod

    if not facets_mod.DEFAULT_EDGES.exists():
        return None
    return facets_mod.load(facets_mod.DEFAULT_EDGES)


def _with_facets(  # noqa: PLR0917 - one argument per input the facets need
    phenotype: Phenotype,
    definition: Definition,
    hierarchy: Hierarchy,
    code_to_cuis: dict[str, list[str]],
    cui_to_codes: dict[str, list[str]],
    edges: Any | None,
) -> Phenotype:
    """Add the medication and finding facets to a disorder closure.

    The vetted set gates the medication facet AND the proposed facet, so
    concepts a reviewer rejected stay rejected — this adds the audited facets,
    not the raw candidates. Proposals without a vetting row pass wholesale
    (same fallback the medication facet uses), so an install whose vetting file
    predates the proposed pass keeps the old behaviour rather than emptying.
    """
    if edges is None:
        return phenotype

    from robustehr.concepts import facets as facets_mod

    vetting = facets_mod.load_vetting()
    proposals = facets_mod.load_proposals()
    name = phenotype.name

    medication = facets_mod.medications(
        frozenset(phenotype.seed_codes and _seed_cuis(definition.seeds, code_to_cuis)),
        phenotype.concept_cuis,
        edges,
        declared=definition.medication_seeds,
        vetted=vetting.get(name, {}).get(facets_mod.Facet.MEDICATION.value),
    )
    finding = facets_mod.findings(definition.finding_seeds, hierarchy, code_to_cuis, max_depth=0)
    proposed = proposals.get(name, {})
    extra = frozenset().union(*proposed.values()) if proposed else frozenset()
    vetted_proposed = vetting.get(name, {}).get("proposed")
    if vetted_proposed is not None:
        extra &= vetted_proposed

    # The closure facet is STRICT-gated, deviating from the absent-row-passes
    # pattern above on purpose: proposals carry an LLM's clinical judgement,
    # but closure candidates are raw graph output (every parent and top-region
    # sibling of every member), and admitting them unjudged would put
    # "Congenital Hepatic Fibrosis" one bad harvest away from a heart-failure
    # set. No vetting row means nothing is admitted.
    closure = facets_mod.load_closure().get(name, frozenset()) & vetting.get(name, {}).get(
        "closure", frozenset()
    )

    # The specificity screen subtracts from the DERIVED facets only. A concept
    # in the disorder closure is the phenotype's own identity — it is the
    # disease or a subtype of it — and a concept cannot be too unspecific to be
    # itself. Everything below arrived by association, and association is where
    # a term shared across unrelated phenotypes stops carrying information.
    #
    # **It ships absent, so this is normally a no-op, and that is the decision
    # rather than an oversight.** The screen was built to reduce dilution, on
    # the argument that a character spent on `fatigue` is one not spent on the
    # diagnosis. That argument holds for a rate-limited dose and not for the one
    # these experiments use: at rate 1.00 with a per-token cap every eligible
    # span receives exactly one edit, so a broader set costs the diagnosis
    # nothing. What a broad set actually costs is interpretability — which of
    # the spans the corruption hit was the diagnosis — and `Evidence.tier`
    # answers that per span, without deleting anything first.
    #
    # Deleting is also the harder move to undo. A concept removed here is
    # invisible downstream, while a concept kept and labelled can be conditioned
    # on by any later analysis. Where the evidence says recall is the binding
    # constraint, measuring beats filtering.
    unspecific = load_nonspecific()
    if unspecific:
        medication = replace(medication, cuis=medication.cuis - unspecific)
        finding = replace(finding, cuis=finding.cuis - unspecific)
        extra -= unspecific
        closure -= unspecific

    added = medication.cuis | finding.cuis | extra | closure
    if not added:
        return phenotype
    cuis = phenotype.concept_cuis | added
    codes = {code for cui in added for code in cui_to_codes.get(cui, ())}
    # Sizes and memberships are built from the same five expressions in the same
    # order, so a facet cannot be counted in one and forgotten in the other.
    contributed: dict[str, frozenset[str]] = {
        "disorder": phenotype.concept_cuis,
        "medication": medication.cuis,
        "finding": finding.cuis,
        "proposed": extra,
        "closure": closure,
    }
    return replace(
        phenotype,
        concept_cuis=cuis,
        concept_codes=phenotype.concept_codes | frozenset(codes),
        facet_sizes={tier: len(members) for tier, members in contributed.items()},
        facet_cuis=contributed,
    )


def _seed_cuis(seeds: Sequence[str], code_to_cuis: dict[str, list[str]]) -> frozenset[str]:
    return frozenset(cui for code in seeds for cui in code_to_cuis.get(code, ()))


@dataclass(frozen=True, slots=True)
class Evidence:
    """One span that is evidence for one phenotype."""

    span: Span
    phenotype: str
    cui: str
    assertion: frozenset[str] = field(default=frozenset())
    """ConText attributes — ``negated``, ``historical``, ``family``, and so on.

    Reported, never acted on. See the module docstring.

    Empty means affirmed **only when** :attr:`qualified`; otherwise it means
    stage 8 never reached this span.
    """
    qualified: bool = False
    """Whether stage 8 returned a verdict for this span at all.

    Without it, an empty :attr:`assertion` conflates *affirmed* with *never
    asked*, and a run with no medspaCy installed would report 100% affirmed
    evidence rather than admitting it does not know. That is the vacuous-zero
    failure `dose.evidence_touch` exists to prevent, one level down.

    Carrying an attribute implies a verdict, so this is forced true whenever
    :attr:`assertion` is non-empty and the contradictory state cannot be built.
    """
    tier: str = "unknown"
    """Which warrant admitted this span: a facet name, or ``anchor``.

    ``anchor`` means the span matched a declared surface form and carries no
    concept at all — :attr:`cui` is empty for those, and that is the point. The
    remaining values are facet names from :meth:`Phenotype.tier_of`.

    **Last field on purpose.** Every existing caller builds an `Evidence`
    positionally, in this repository and in the studies that consume it, so a
    field inserted anywhere earlier would silently rebind `assertion` to a tier
    string. Appending is the one placement that cannot break a caller that has
    not been recompiled against it.

    Reported, never filtered on by the target grammar. ``pheno=X`` admits every
    tier exactly as it did before this field existed, so arm names, stored edit
    scripts and severity seeds are untouched. What the tier buys is that an arm
    can finally say *which* evidence it reached: an operator reporting full
    coverage of declared evidence while touching none of the written diagnosis
    is reporting the wrong number, and nothing in the dose record revealed it.
    """

    def __post_init__(self) -> None:
        if self.assertion and not self.qualified:
            object.__setattr__(self, "qualified", True)

    @property
    def affirmed(self) -> bool:
        """Qualified, and carrying no attribute. Unqualified is not affirmed."""
        return self.qualified and not self.assertion


@dataclass(frozen=True, slots=True)
class PhenotypeIndex:
    """Evidence spans over one document, queryable by span.

    Empty is a legitimate state and is **not** the same as "no phenotype
    configured" — :attr:`names` distinguishes them. That distinction is load
    bearing: under ``protect`` an empty index means every operator runs
    unrestricted and ``evidence_touch`` reads zero, which is indistinguishable
    from a real zero unless the caller knows a phenotype was asked for.
    """

    evidence: tuple[Evidence, ...] = ()
    names: tuple[str, ...] = ()
    """Every phenotype that was *declared*, including ones with no evidence here."""

    def overlapping(self, span: Span) -> tuple[Evidence, ...]:
        return tuple(e for e in self.evidence if e.span.overlaps(span))

    def spans(self, phenotype: str | None = None) -> tuple[Span, ...]:
        """Evidence spans, optionally for one phenotype, deduplicated and ordered."""
        chosen = {e.span for e in self.evidence if phenotype is None or e.phenotype == phenotype}
        return tuple(sorted(chosen, key=lambda s: (s.start, s.end)))

    def relatedness(self, span: Span) -> dict[str, dict[str, Any]]:
        """The per-edit tag: for every declared phenotype, did this edit touch it?

        Every declared phenotype appears, including the ones that did not match,
        because ``intersects_evidence: false`` is a measurement and a missing key
        is not.
        """
        hits: dict[str, list[Evidence]] = {name: [] for name in self.names}
        for e in self.overlapping(span):
            hits.setdefault(e.phenotype, []).append(e)
        out: dict[str, dict[str, Any]] = {}
        for name in sorted(hits):
            found = sorted(hits[name], key=lambda e: (e.span.start, e.span.end, e.cui))
            if not found:
                out[name] = {"intersects_evidence": False}
                continue
            qualified = [e for e in found if e.qualified]
            out[name] = {
                "intersects_evidence": True,
                "cuis": [e.cui for e in found],
                "tiers": sorted({e.tier for e in found}),
                "assertion": sorted({a for e in found for a in e.assertion}),
                # Null rather than false when stage 8 never ran: "not affirmed"
                # and "not asked" are different claims and only one is ours.
                "affirmed": any(e.affirmed for e in qualified) if qualified else None,
                "assertion_qualified": bool(qualified),
            }
        return out

    def touched(self, spans: Iterable[Span]) -> dict[str, int]:
        """Evidence spans intersected by any of ``spans``, per phenotype.

        The aggregate behind ``evidence_touch``. Counts **evidence spans hit**
        rather than edits landed, so one operator making three edits inside one
        mention scores 1 — the quantity of interest is how much of the
        phenotype's evidence was disturbed, not how busy the operator was.
        """
        edits = tuple(spans)
        counts = {name: 0 for name in self.names}
        for e in self.evidence:
            if any(e.span.overlaps(s) for s in edits):
                counts[e.phenotype] = counts.get(e.phenotype, 0) + 1
        return counts

    def declared_by_tier(self, phenotype: str | None = None) -> dict[str, int]:
        """Evidence spans available per tier, before anything was corrupted.

        The denominator half of reach. An arm reporting that it touched every
        declared evidence span has said nothing about whether it reached the
        diagnosis until this is reported beside it.
        """
        counts: dict[str, int] = {}
        for e in self.evidence:
            if phenotype is not None and e.phenotype != phenotype:
                continue
            counts[e.tier] = counts.get(e.tier, 0) + 1
        return counts

    def touched_by_tier(
        self, spans: Iterable[Span], phenotype: str | None = None
    ) -> dict[str, int]:
        """The numerator half: evidence spans intersected, per tier.

        Counts spans hit rather than edits landed, matching :meth:`touched`, so
        the two divide cleanly into a reach fraction.
        """
        edits = tuple(spans)
        counts: dict[str, int] = {}
        for e in self.evidence:
            if phenotype is not None and e.phenotype != phenotype:
                continue
            if any(e.span.overlaps(s) for s in edits):
                counts[e.tier] = counts.get(e.tier, 0) + 1
        return counts

    def __len__(self) -> int:
        return len(self.evidence)

    def __bool__(self) -> bool:
        """True when a phenotype was *declared*, even if nothing matched."""
        return bool(self.names)


def index_document(
    mentions: MentionIndex,
    phenotypes: Sequence[Phenotype],
    *,
    assertions: dict[Span, frozenset[str]] | None = None,
    text: str | None = None,
) -> PhenotypeIndex:
    """Which spans are evidence for which declared phenotype.

    A mention may be evidence for more than one phenotype, and that is recorded
    rather than resolved: overlapping phenotypes are a real property of clinical
    concepts, and the cross-phenotype overlap matrix is a reported output.

    ``assertions`` holds **only spans stage 8 actually qualified** — the shape
    `context.AssertionIndex.as_map` returns. Membership is therefore the
    qualified flag: a span absent from it is unknown, not affirmed. Passing
    ``None`` leaves every evidence span unqualified, which is the honest state
    for a run without the ``clinical`` extra.

    **Two warrants, not one.** A span is evidence when its concept is in the
    phenotype's set, *or* when it literally spells the diagnosis. Passing
    ``text`` enables the second; omitting it is the pre-anchor behaviour and is
    still correct, just narrower. The surface warrant is what reaches an
    organism or a qualifier, neither of which a disorder hierarchy can return,
    and what reaches an abbreviation the matcher produced no candidate for.

    Where both warrants cover the same characters the concept wins, because it
    carries a CUI and the anchor does not. An anchor span is emitted only where
    no concept-derived evidence for that same phenotype already overlaps it, so
    the two cannot double-count one piece of evidence into a reach denominator.
    """
    qualified = assertions or {}
    found: list[Evidence] = []
    for mention in mentions.mentions:
        for pheno in phenotypes:
            if not pheno.contains(mention.cui):
                continue
            if pheno.anchors is not None and surface.is_stopped(mention.surface, pheno.anchors):
                continue
            found.append(
                Evidence(
                    span=mention.span,
                    phenotype=pheno.name,
                    cui=mention.cui,
                    tier=pheno.tier_of(mention.cui),
                    assertion=qualified.get(mention.span, frozenset()),
                    qualified=mention.span in qualified,
                )
            )
    if text is not None:
        found += _anchor_evidence(text, phenotypes, found, qualified)
    found.sort(key=lambda e: (e.span.start, e.span.end, e.phenotype, e.cui))
    return PhenotypeIndex(evidence=tuple(found), names=tuple(sorted({p.name for p in phenotypes})))


def _anchor_evidence(
    text: str,
    phenotypes: Sequence[Phenotype],
    concept_evidence: Sequence[Evidence],
    qualified: Mapping[Span, frozenset[str]],
) -> list[Evidence]:
    """Declared surface forms that no concept-derived evidence already covers.

    Kept separate from the mention loop because it answers a different question
    over a different input — characters rather than candidates — and because the
    overlap test needs the concept evidence to exist first.
    """
    covered: dict[str, list[Span]] = {}
    for e in concept_evidence:
        covered.setdefault(e.phenotype, []).append(e.span)
    out: list[Evidence] = []
    for pheno in phenotypes:
        if pheno.anchors is None or not pheno.anchors.declared:
            continue
        # Anchors first, then associated terms, and each round adds to what the
        # next must avoid. A diagnosis and a finding can share characters —
        # "preserved left ventricular ejection fraction" sits inside the phrase
        # naming the phenotype — and the stronger tier has to win, or the reach
        # gate would count the diagnosis as an association.
        claimed = list(covered.get(pheno.name, ()))
        for tier in ("anchor", "associated"):
            for span in surface.anchor_spans(text, pheno.anchors, tier):
                if any(span.overlaps(other) for other in claimed):
                    continue
                claimed.append(span)
                out.append(
                    Evidence(
                        span=span,
                        phenotype=pheno.name,
                        cui="",
                        tier=tier,
                        assertion=qualified.get(span, frozenset()),
                        qualified=span in qualified,
                    )
                )
    return out


def protected_spans(index: PhenotypeIndex) -> list[ProtectedSpan]:
    """Evidence spans as protection entries, for ``phenotype_scope=protect``.

    **SOFT, not HARD.** HARD means atomic — replaceable whole, never edited
    internally — and exists to stop an operator fabricating PHI-shaped text
    inside a de-identification mask. Phenotype evidence needs the opposite
    treatment: it must be withheld from operators *entirely*, which is what a
    SOFT protection no operator declares as a target achieves. An operator that
    explicitly declares ``PHENOTYPE_EVIDENCE`` can still reach it, which is how
    ``target`` mode's operators are permitted through the same registry.
    """
    return [
        ProtectedSpan(
            span=span,
            cls=ProtectionClass.PHENOTYPE_EVIDENCE,
            strength=Strength.SOFT,
            reason=f"evidence for phenotype {name}",
        )
        for name in index.names
        for span in index.spans(name)
    ]


__all__ = [
    "Definition",
    "Evidence",
    "Phenotype",
    "PhenotypeIndex",
    "build",
    "declare",
    "index_document",
    "load_definitions",
    "load_maps",
    "protected_spans",
    "targeting_manifest",
]
