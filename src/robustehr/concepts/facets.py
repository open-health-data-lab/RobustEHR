"""A phenotype is more than its disorder closure: medications, and findings.

**The gap this closes, stated as a measurement.** Every shipped concept set was a
descendant closure of a *disease* concept, so it could not contain a drug or a
symptom by construction. Audited:

    depression     206 disorders, 13 findings,   0 medications
    hfpef            8 disorders,  0 findings,   0 medications
    hypertension   301 disorders, 21 findings,   0 medications

A clinician asked which concepts belong to depression would name sertraline
before they named *Recurrent depressive disorder, current episode moderate*. A
perturbation aimed at "the depression content of this note" that leaves every
antidepressant untouched is aimed at the wrong thing.

**Three facets, and they are not equally derivable. That asymmetry is the finding
here, not an implementation detail.**

``DISORDER``
    Descendant closure of the seeds over ``SNOMEDCT_US isa`` union ``MTH RN``. Works;
    this is what the package already had.

``MEDICATION``
    ``MED-RT`` ``may_treat`` / ``may_prevent``, 15,352 edges. Works well — the
    depression facet is amitriptyline, bupropion, citalopram, desvenlafaxine and
    108 more. Needs one addition to be usable, below.

``FINDING``
    **Not derivable from UMLS relations, and this was measured rather than
    assumed.** Carried by ``load_proposals``: clinical terms named, then grounded
    against the release. Asked for the findings of Heart failure (C0018801),
    UMLS itself offers:

    * ``has_associated_finding`` (SNOMEDCT_US) -> *H/O: heart failure*, *Family
      history of heart failure*, *Heart failure excluded* — assertion variants
      of the disease itself, not its symptoms;
    * ``has_manifestation`` (OMIM) -> *3-Methylglutaconic Aciduria Type V*,
      *Arrhythmogenic Right Ventricular Dysplasia* — the inverse relation,
      diseases that manifest heart failure, and genetic ones at that;
    * ``cause_of`` (SNOMEDCT_US) -> two complications.

    Nothing anywhere returns dyspnea, oedema, orthopnea. Pretending otherwise
    would have shipped the OMIM output above under a scientific-sounding
    relation name.

**Minimal lift, and why it is per facet.** MED-RT attaches treatments to the
disease concepts clinicians code, which are not always the specific ones a
phenotype seeds. ``hfpef`` has no ``may_treat`` edge at all; its parent *Heart
failure* has 108. So a facet that comes back empty is retried one ``isa`` step up,
and again, to a bounded number of hops.

It is **minimal** — escalation stops the moment the facet is non-empty — because
lifting is not free. ``depression`` at hop 0 is 112 antidepressants; at hop 1 it
reaches *Mental disorder* and becomes 302 concepts of every psychotropic class.
Taking the nearest ancestor that carries treatment evidence keeps the specific
answer where one exists and reaches for a general one only where none does.

**Lift can still be wrong, which is why nothing here ships unvetted.**
``clostridioides_difficile`` has no treatment edge; one hop up yields
*ciprofloxacin* — a drug that **causes** C. difficile rather than treating it.
No structural rule catches that; it needs a clinician, or a model standing in for
one.

**But vetting everything would be theatre, and the first attempt was.** The raw
medication candidates across 22 phenotypes are 1,746 concepts, and feeding all of
them to a model is not review — it is a rubber stamp with a token cost. Two
deterministic reductions come first, and they are not tidying:

*Ingredient collapse.* 100 of hypertension's 241 candidates are RxNorm **precise
ingredients**: *amlodipine besylate* and *amlodipine benzoate* beside
*amlodipine*. These are not clinical decisions, they are salt forms of one. A
verdict is taken once per ingredient and inherited by its variants, which are
**kept in the set** — a note writing "amlodipine besylate" must still match.
1,746 candidates become 969 decisions.

*Provenance.* MED-RT is a curated NLM terminology. A drug it links to the
phenotype's **own seed concept** is asserted by that source, and re-judging it
with a cheap model substitutes weaker evidence for stronger. What actually needs
review is what *we* inferred:

======== ================================================ =====
tier     the edge starts at                               n
======== ================================================ =====
seed     the phenotype's own seed concept — MED-RT's claim   447
closure  a descendant of the seed — our expansion            228
lift     an ancestor of the seed — our escalation            294
======== ================================================ =====

So 522 concepts are vetted rather than 1,746, and the scope is phenotype
dependent in the way that matters: ``type_2_diabetes`` is entirely seed-asserted
and needs no review at all, while ``hfpef`` (63) and ``metastatic_cancer`` (166)
are entirely lifted and need all of it. Ciprofloxacin-for-C.-difficile sits in
the ``lift`` tier, which is the tier this split exists to catch.

Every concept carries its tier, so a reader can see *why* each is in the set.
See ``validation/phenotype/scripts/phenotype_vet.py``.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from robustehr.concepts.hierarchy import Hierarchy
from robustehr.resources import register_external

#: Where the cached facet edges live. Derived from licensed UMLS content, so it
#: is gitignored and never travels with the package.
DEFAULT_EDGES = Path("data/umls_facets.json")


def _edges_digest() -> str:
    """``sha256`` of the locally built edge list, or ``"absent"``."""
    import hashlib

    if not DEFAULT_EDGES.is_file():
        return "absent"
    return hashlib.sha256(DEFAULT_EDGES.read_bytes()).hexdigest()


register_external(DEFAULT_EDGES.name, _edges_digest)

#: How far up the `isa` chain a facet may reach before giving up. Three hops from
#: a phenotype seed is already a whole discipline ("Mental disorder", "Infectious
#: disease"), so this is a ceiling rather than a target.
MAX_LIFT = 3


class Facet(StrEnum):
    """What kind of evidence a concept is for a phenotype."""

    DISORDER = "disorder"
    MEDICATION = "medication"
    FINDING = "finding"


@dataclass(frozen=True, slots=True)
class FacetEdges:
    """The relation caches a facet expansion needs.

    ``parents`` is inverted from **SNOMEDCT_US ``isa`` alone**, not from the
    expansion hierarchy. Lifting through ``MTH RN`` would climb the same
    unvetted edges that made *Vascular diseases* a descendant of pulmonary
    embolism — going up, that mistake reaches further and faster.
    """

    treats: dict[str, tuple[str, ...]]
    """Disease CUI -> drug CUIs, from MED-RT ``may_treat`` / ``may_prevent``."""
    parents: dict[str, tuple[str, ...]]
    """Child CUI -> parent CUIs, SNOMEDCT_US ``isa`` only."""
    ingredient_of: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """RxNorm precise-ingredient CUI -> its base ingredient CUI(s).

    *amlodipine besylate* -> *amlodipine*, so that vetting takes one verdict
    per ingredient rather than one per salt; the variants stay in the set so
    text naming a salt still matches.
    """
    variants: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """RxNorm ingredient CUI -> its brand and product CUIs.

    ``tradename_of`` and ``has_ingredient``: *furosemide* -> *Lasix*,
    *furosemide 20 MG*. The matcher grounds those surfaces to those CUIs, and
    a set that holds only the ingredient fails membership for exactly the
    mentions clinicians write — the evidence-audit finding this field exists
    to close. Identity-preserving by relation semantics, so the ingredient's
    verdict covers them (the vetting prompt already asserts as much for salt
    and ester forms)."""

    def ingredient(self, cui: str) -> str:
        """The concept a verdict is taken on: the base ingredient where there is one."""
        bases = self.ingredient_of.get(cui)
        return min(bases) if bases else cui

    def variants_of(self, cui: str) -> tuple[str, ...]:
        """Brand and product CUIs of an ingredient, or nothing for a non-ingredient."""
        return self.variants.get(cui, ())

    def ancestors(self, seeds: frozenset[str], hops: int) -> frozenset[str]:
        """The seeds plus everything within ``hops`` ``isa`` steps above them."""
        seen: set[str] = set(seeds)
        frontier: deque[tuple[str, int]] = deque((s, 0) for s in seeds)
        while frontier:
            node, depth = frontier.popleft()
            if depth >= hops:
                continue
            for parent in self.parents.get(node, ()):
                if parent not in seen:
                    seen.add(parent)
                    frontier.append((parent, depth + 1))
        return frozenset(seen)


@dataclass(frozen=True, slots=True)
class FacetSet:
    """One facet's concepts, and how far it had to reach to find them."""

    facet: Facet
    cuis: frozenset[str]
    lift: int
    """``isa`` hops above the disorder closure that produced this. 0 is direct."""
    source: str
    """The rule that generated it, recorded so a reader can re-derive the set."""
    provenance: dict[str, str] = field(default_factory=dict)
    """CUI -> ``seed`` | ``closure`` | ``lift``. Decides what needs vetting."""

    def needs_review(self) -> frozenset[str]:
        """Concepts *we* inferred.

        Excludes both ends: seed is MED-RT's own assertion about the
        phenotype, and declared was named by a human precisely because no
        edge existed to infer from. ``identity`` is excluded too — a brand or
        product form of an admitted ingredient carries that ingredient's
        verdict (the vetting prompt says so in as many words), and putting
        thousands of dose forms in front of a reviewer would bury the rows
        that need judgement. What is left is expansion and escalation — ours,
        and the only part a review can improve.
        """
        return frozenset(
            c for c, tier in self.provenance.items() if tier not in ("seed", "declared", "identity")
        )

    def to_row(self) -> dict[str, Any]:
        tiers: dict[str, int] = {}
        for tier in self.provenance.values():
            tiers[tier] = tiers.get(tier, 0) + 1
        return {
            "facet": self.facet.value,
            "n": len(self.cuis),
            "lift": self.lift,
            "source": self.source,
            "by_provenance": dict(sorted(tiers.items())),
        }


def medications(
    seed_cuis: frozenset[str],
    disorder_cuis: frozenset[str],
    edges: FacetEdges,
    *,
    declared: tuple[str, ...] = (),
    vetted: frozenset[str] | None = None,
    max_lift: int = MAX_LIFT,
) -> FacetSet:
    """Drugs that may treat or prevent the phenotype, at minimal lift, with tiers.

    Returns the first non-empty result walking up from the disorder closure. An
    empty set after ``max_lift`` hops is a real answer and is returned rather
    than widened until something appears.

    ``vetted``, when supplied, is the admissible set from the frozen verdicts
    (:func:`load_vetting`): a derived drug outside it was reviewed and rejected
    and is excluded here. Passing ``None`` returns the unvetted candidates,
    which is what the vetting script itself needs.

    Each drug is tagged with where its edge started — ``seed``, ``closure`` or
    ``lift`` — because that decides whether it needs review. See the module
    docstring; the short version is that a MED-RT assertion about the phenotype
    itself is better evidence than anything a re-judging pass could add, while a
    drug reached by climbing to an ancestor is our inference and is where
    ciprofloxacin-for-C.-difficile comes from.
    """

    def drugs_of(pool: frozenset[str]) -> set[str]:
        return {d for cui in pool for d in edges.treats.get(cui, ())}

    for lift in range(max_lift + 1):
        pool = edges.ancestors(disorder_cuis, lift) if lift else disorder_cuis
        found = drugs_of(pool)
        # Escalation depends on `found` ALONE. Letting `declared` satisfy this
        # returned at lift 0 with three hand-named drugs and silently discarded
        # the 108 heart-failure treatments hfpef exists to inherit — a declared
        # seed is a supplement to the derived facet, never a substitute for it.
        if not found:
            continue
        from_seed = drugs_of(seed_cuis & pool)
        from_closure = drugs_of(disorder_cuis) - from_seed
        provenance = {
            cui: ("seed" if cui in from_seed else "closure" if cui in from_closure else "lift")
            for cui in found
        }
        # Vetting verdicts are APPLIED here, not merely recorded. `vetted` is the
        # admissible set for this facet; anything derived and not in it was
        # reviewed and rejected. `declared` is exempt because it was named after
        # the review and never went through it.
        admitted = frozenset(found) if vetted is None else frozenset(found) & vetted
        # `declared` wins over whatever tier a concept would otherwise get: it
        # was named by a human because the vocabulary had no edge to infer from,
        # and re-deriving it is exactly what could not be done.
        provenance = {c: t for c, t in provenance.items() if c in admitted}
        provenance |= dict.fromkeys(declared, "declared")
        members = admitted | frozenset(declared)
        identity = _identity_variants(members, edges)
        provenance |= dict.fromkeys(identity, "identity")
        return FacetSet(
            Facet.MEDICATION,
            members | identity,
            lift,
            "MED-RT may_treat|may_prevent + declared" + ("" if vetted is None else " (vetted)"),
            provenance,
        )
    fallback = frozenset(declared)
    identity = _identity_variants(fallback, edges)
    return FacetSet(
        Facet.MEDICATION,
        fallback | identity,
        max_lift,
        "MED-RT may_treat|may_prevent + declared",
        dict.fromkeys(declared, "declared") | dict.fromkeys(identity, "identity"),
    )


def _identity_variants(members: frozenset[str], edges: FacetEdges) -> frozenset[str]:
    """The RxNorm brand and product CUIs of every member, minus the members.

    Applied AFTER the vetting gate, so identity rides only on admitted
    ingredients: a reviewer's drop removes the ingredient and its whole family
    in one verdict, and a keep admits the surfaces notes actually write —
    "Lasix", "furosemide 20 MG" — which the evidence audit found grounding to
    brand and product CUIs a set of bare ingredients can never contain.
    """
    return frozenset(v for cui in members for v in edges.variants_of(cui)) - members


def findings(
    seeds: tuple[str, ...],
    hierarchy: Hierarchy,
    code_to_cuis: dict[str, list[str]],
    *,
    max_depth: int = 0,
) -> FacetSet:
    """The **declared** finding seeds, and by default only the seeds.

    No relation traversal, because UMLS has none that works — see the module
    docstring.

    **Expansion is off by default.** A symptom's descendant closure is every
    variety of that symptom in the terminology, and almost none of them are
    specific to the phenotype that named the seed: at depth 6,
    `clostridioides_difficile` draws **346** findings from two seeds
    (*diarrhoea*, *abdominal pain*) against a disorder facet of 10, and
    `heart_failure` draws 363 — the same over-reach that makes *Vascular
    diseases* a descendant of pulmonary embolism, one level down.

    The finding facet's breadth comes from ``load_proposals`` instead: terms a
    clinician would name, each grounded against the release, so every concept
    in it traces to a named term and is reviewable. A declared seed is a
    deliberate single addition rather than the origin of a few hundred concepts;
    ``max_depth`` is available for a phenotype that genuinely wants the subtypes,
    and it must be asked for.
    """
    seed_cuis = [cui for code in seeds for cui in code_to_cuis.get(code, ())]
    if not seed_cuis:
        return FacetSet(Facet.FINDING, frozenset(), 0, "declared finding seeds")
    return FacetSet(
        Facet.FINDING,
        frozenset(seed_cuis)
        if max_depth == 0
        else hierarchy.descendants(*seed_cuis, max_depth=max_depth),
        0,
        f"declared finding seeds (depth {max_depth})",
    )


def build(release: Any, out: Path) -> dict[str, Any]:
    """Materialize the MED-RT treatment edges and the SNOMED parent index.

    **Edge direction is verified, not reasoned about.** In ``MRREL`` a row's
    ``rela`` describes ``cui2``'s relation *to* ``cui1``, so ``cui1=C0011570``
    (Depressive disorder), ``rela='may_treat'`` means *cui2 may treat
    depression* — the drug is ``cui2``. Reading it the other way is silent: it
    produces a well-formed map keyed by drug, every phenotype lookup misses, and
    every facet comes back empty, which looks exactly like a vocabulary that has
    no treatment relations. That is the bug this docstring exists to prevent
    recurring; it cost a full pass to find.
    """
    import duckdb

    from robustehr.concepts.hierarchy import MRREL_COLUMNS
    from robustehr.concepts.umls import MRCONSO_COLUMNS

    con = duckdb.connect(":memory:")
    treats_rows = con.execute(f"""
        SELECT DISTINCT cui1 AS disease, cui2 AS drug
        FROM read_csv('{release.rrf("MRREL.RRF")}', delim='|', header=false,
                      quote='', names={MRREL_COLUMNS!r}, all_varchar=true)
        WHERE suppress = 'N' AND sab = 'MED-RT'
          AND rela IN ('may_treat', 'may_prevent')
    """).fetchall()
    parent_rows = con.execute(f"""
        SELECT DISTINCT cui2 AS child, cui1 AS parent
        FROM read_csv('{release.rrf("MRREL.RRF")}', delim='|', header=false,
                      quote='', names={MRREL_COLUMNS!r}, all_varchar=true)
        WHERE suppress = 'N' AND sab = 'SNOMEDCT_US' AND rela = 'isa'
    """).fetchall()
    # Salt and ester forms onto their base ingredient, restricted to concepts
    # RxNorm actually types as IN — otherwise `form_of` walks on into drug
    # products and a verdict on one ingredient would swallow whole formularies.
    #
    # Direction verified, not reasoned about, and it is the OPPOSITE of the
    # MED-RT convention two queries up: here `cui1` is the ingredient and `cui2`
    # the variant — `amlodipine --form_of--> amlodipine besylate`. Joining the
    # other way returns zero rows, which is the loud failure; what is dangerous
    # is that dropping precise ingredients outright produces almost the same
    # COUNT as collapsing them, so a silent inversion looks like it worked.
    ingredient_rows = con.execute(f"""
        WITH base AS (
            SELECT DISTINCT cui FROM read_csv('{release.rrf("MRCONSO.RRF")}', delim='|',
                header=false, quote='', names={MRCONSO_COLUMNS!r}, all_varchar=true)
            WHERE sab = 'RXNORM' AND tty = 'IN'
        )
        SELECT DISTINCT r.cui2 AS variant, r.cui1 AS ingredient
        FROM read_csv('{release.rrf("MRREL.RRF")}', delim='|', header=false,
                      quote='', names={MRREL_COLUMNS!r}, all_varchar=true) r
        JOIN base ON base.cui = r.cui1
        WHERE r.suppress = 'N' AND r.sab = 'RXNORM'
          AND r.rela IN ('form_of', 'precise_ingredient_of')
          AND r.cui1 <> r.cui2
    """).fetchall()
    # Brand and product CUIs of each ingredient — the RxNorm identity closure.
    # Same direction convention as the query above (`cui1` is the ingredient,
    # verified against furosemide: C0016860 --tradename_of--> C0699992 Lasix,
    # C0016860 --has_ingredient--> C0986198 furosemide 20 MG), and the same
    # `tty='IN'` anchor so the closure starts only at true ingredients and one
    # verdict never swallows an unrelated formulary.
    variant_rows = con.execute(f"""
        WITH base AS (
            SELECT DISTINCT cui FROM read_csv('{release.rrf("MRCONSO.RRF")}', delim='|',
                header=false, quote='', names={MRCONSO_COLUMNS!r}, all_varchar=true)
            WHERE sab = 'RXNORM' AND tty = 'IN'
        )
        SELECT DISTINCT r.cui1 AS ingredient, r.cui2 AS variant
        FROM read_csv('{release.rrf("MRREL.RRF")}', delim='|', header=false,
                      quote='', names={MRREL_COLUMNS!r}, all_varchar=true) r
        JOIN base ON base.cui = r.cui1
        WHERE r.suppress = 'N' AND r.sab = 'RXNORM'
          AND r.rela IN ('tradename_of', 'has_ingredient')
          AND r.cui1 <> r.cui2
    """).fetchall()

    treats: dict[str, set[str]] = {}
    for disease, drug in treats_rows:
        treats.setdefault(str(disease), set()).add(str(drug))
    parents: dict[str, set[str]] = {}
    for child, parent in parent_rows:
        parents.setdefault(str(child), set()).add(str(parent))
    ingredient_of: dict[str, set[str]] = {}
    for variant, ingredient in ingredient_rows:
        ingredient_of.setdefault(str(variant), set()).add(str(ingredient))
    variants: dict[str, set[str]] = {}
    for ingredient, variant in variant_rows:
        variants.setdefault(str(ingredient), set()).add(str(variant))

    payload = {
        "treats_relation": "MED-RT may_treat|may_prevent (cui1=disease, cui2=drug)",
        "parents_relation": "SNOMEDCT_US isa only — MTH RN is not climbed, see FacetEdges",
        "variants_relation": (
            "RXNORM tradename_of|has_ingredient (cui1=IN ingredient, cui2=brand/product)"
        ),
        "diseases_with_a_treatment": len(treats),
        "treatment_edges": sum(len(v) for v in treats.values()),
        "children_with_a_parent": len(parents),
        "ingredient_variants": len(ingredient_of),
        "ingredients_with_variants": len(variants),
        "variant_edges": sum(len(v) for v in variants.values()),
        "treats": {k: sorted(v) for k, v in sorted(treats.items())},
        "parents": {k: sorted(v) for k, v in sorted(parents.items())},
        "ingredient_of": {k: sorted(v) for k, v in sorted(ingredient_of.items())},
        "variants": {k: sorted(v) for k, v in sorted(variants.items())},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return {
        k: v
        for k, v in payload.items()
        if k not in ("treats", "parents", "ingredient_of", "variants")
    }


def load(path: Path = DEFAULT_EDGES) -> FacetEdges:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return FacetEdges(
        treats={k: tuple(v) for k, v in raw["treats"].items()},
        parents={k: tuple(v) for k, v in raw["parents"].items()},
        ingredient_of={k: tuple(v) for k, v in raw.get("ingredient_of", {}).items()},
        variants={k: tuple(v) for k, v in raw.get("variants", {}).items()},
    )


__all__ = [
    "DEFAULT_EDGES",
    "MAX_LIFT",
    "Facet",
    "FacetEdges",
    "FacetSet",
    "build",
    "findings",
    "load",
    "load_closure",
    "load_proposals",
    "load_vetting",
    "medications",
]


def load_proposals(path: str = "phenotype_proposals.yaml") -> dict[str, dict[str, frozenset[str]]]:
    """Grounded proposal CUIs, as ``{phenotype: {facet: cuis}}``.

    The knowledge-first half of the layer.
    `validation/phenotype/scripts/phenotype_propose.py` asks a model for clinical
    *terms*, resolves each against the local release, and
    freezes the identifiers here; this reads them back. No model is contacted at
    load time and none needs to be reachable — the artifact is CUIs.

    Keyed by the facet a concept was **assigned** to by its semantic type, not
    by the one it was proposed under. Those disagree often (a third of grounded
    terms), and the assigned facet is the one that describes what the concept is.
    """
    from robustehr.resources import load_yaml

    raw = load_yaml(path)
    out: dict[str, dict[str, set[str]]] = {}
    for name, by_proposed in (raw or {}).get("phenotypes", {}).items():
        for row in by_proposed.values():
            for facet, cuis in row.get("cuis_by_assigned_facet", {}).items():
                out.setdefault(name, {}).setdefault(facet, set()).update(cuis)
    return {n: {f: frozenset(c) for f, c in v.items()} for n, v in out.items()}


def load_closure(path: str = "phenotype_closure.yaml") -> dict[str, frozenset[str]]:
    """Closure CANDIDATES per phenotype, as ``{phenotype: cuis}``.

    Written by `validation/phenotype/scripts/phenotype_closure.py`: the bounded one-hop neighborhood
    of each set (parents everywhere, siblings in the disorder top region and
    the small declared facets), plus any explicitly declared hierarchy
    isolates. Candidates only — admission additionally requires a `closure`
    vetting verdict, and `phenotype.build` intersects the two. An install
    without the file simply has no closure facet.
    """
    from robustehr.resources import load_yaml

    try:
        raw = load_yaml(path)
    except FileNotFoundError:
        return {}
    return {
        name: frozenset(row.get("candidates", {}))
        for name, row in (raw or {}).get("phenotypes", {}).items()
    }


def load_vetting(path: str = "phenotype_vetting.yaml") -> dict[str, dict[str, frozenset[str]]]:
    """Frozen vetting verdicts, as ``{phenotype: {facet: kept_cuis}}``.

    Written by `validation/phenotype/scripts/phenotype_vet.py` and consumed by
    :func:`robustehr.concepts.phenotype.build`: ``kept`` gates the medication and
    proposed facets and is the sole admission for closure candidates. A verdict
    nothing consumed would be decorative — the file drops *ciprofloxacin* from
    `clostridioides_difficile`, a drug that causes the condition, and only this
    consumer keeps it out of the set.

    ``kept`` already includes the seed-asserted concepts that were never
    reviewed, so it is the complete admissible set for that facet rather than a
    list of review outcomes.
    """
    from robustehr.resources import load_yaml

    raw = load_yaml(path)
    return {
        name: {facet: frozenset(row.get("kept", ())) for facet, row in by_facet.items()}
        for name, by_facet in (raw or {}).get("phenotypes", {}).items()
    }
