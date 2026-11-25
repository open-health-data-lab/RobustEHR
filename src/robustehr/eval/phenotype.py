"""Can we find a declared phenotype's evidence? Measured against expert spans.

The phenotype layer's own validation, and it needed inventing because the obvious
objection to it is fair: a concept set is *declared*, so how do we know the
declaration finds anything?

The answer available here is that the SNOMED CT Entity Linking Challenge
annotates a **concept identifier** per span. Declare a phenotype as a seed
concept plus its ``isa`` descendants, and the gold spans whose concept falls in
that closure are that phenotype's evidence **as an expert marked it**. Recall
against those spans is a real measurement of a real phenotype, on real notes,
without anyone annotating a phenotype corpus.

Two recalls are reported, and keeping them apart is the point:

* **span recall** — did we find the text at all? What a corruption operator
  needs in order to reach the token.
* **set recall** — did we find it *and* assign a concept inside the phenotype
  set? What ``phenotype_scope`` needs in order to be correct.

The gap between them is the cost of concept-assignment error, expressed in the
units the phenotype layer actually cares about rather than as a global linking
score.

**The asymmetry that matters is on the protect side.** A missed mention under
``phenotype_scope=protect`` is never added to the protection registry, so an
operator corrupts it and the run still reports ``evidence_touch = 0`` — the
measurement and the protection read the same span set, so a vacuous zero is
indistinguishable from a real one. Set recall is what bounds that, and it is why
it is reported next to every protect-mode result rather than assumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from robustehr.concepts.hierarchy import Hierarchy
from robustehr.eval.snomed_el import GoldCorpus, GoldSpan


@dataclass(frozen=True, slots=True)
class Phenotype:
    """A declared concept set: seeds plus their descendant closure."""

    name: str
    seed_codes: tuple[str, ...]
    """SNOMED identifiers, as a clinician would name them."""
    concept_cuis: frozenset[str]
    """The set our *predictions* are tested against — they carry CUIs natively."""
    concept_codes: frozenset[str]
    """The set the *gold* is tested against — it carries SNOMED codes natively."""

    @property
    def size(self) -> int:
        return len(self.concept_cuis)


def declare(
    name: str,
    seed_codes: tuple[str, ...],
    hierarchy: Hierarchy,
    code_to_cuis: dict[str, list[str]],
    cui_to_codes: dict[str, list[str]],
    *,
    max_depth: int = 6,
) -> Phenotype:
    """Expand seed SNOMED codes to a concept set through the CUI hierarchy.

    The set is materialized in **both** identifier systems on purpose. Our
    matcher emits CUIs and the gold carries SNOMED codes, so testing each side
    in its own namespace avoids a lossy round trip that would otherwise be
    scored as a matcher error.

    **A SNOMED code can carry more than one CUI**, and taking the first is a
    silent failure: ``84114007`` (Heart failure) maps to both ``C0018801``, the
    concept with the descendants, and ``C1959583``, a childless duplicate.
    Picking arbitrarily collapsed heart failure to a one-element set. Every CUI
    a seed code carries is therefore a seed.
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


@dataclass(frozen=True, slots=True)
class PhenotypeScore:
    """How much of one phenotype's expert-marked evidence we recovered."""

    phenotype: str
    concept_set_size: int
    gold_spans: int
    span_found: int
    """Gold evidence spans our matcher located at all."""
    set_found: int
    """Gold evidence spans located *and* assigned a concept inside the set."""
    claimed: int = 0
    """Spans **we** called evidence — our mention carried a CUI inside the set."""
    claimed_correct: int = 0
    """Claimed spans an expert also annotated with a concept inside the set."""

    @property
    def span_recall(self) -> float | None:
        return self.span_found / self.gold_spans if self.gold_spans else None

    @property
    def set_recall(self) -> float | None:
        return self.set_found / self.gold_spans if self.gold_spans else None

    @property
    def set_precision(self) -> float | None:
        """Of what we called this phenotype's evidence, how much a clinician would.

        **Recall alone cannot detect an over-broad concept set, and the failure
        is not hypothetical.** Seeding on Pulmonary embolism (59282003) at depth
        6 expands to 9,712 concepts, because one ``MTH RN`` edge makes *Vascular
        Diseases* (C0042373) a descendant of it. That set posts a set recall of
        0.796 — better than five of the eight shipped phenotypes — while being
        clinically meaningless. Recall rises monotonically with closure size, so
        without a counterpart "expand harder" always appears to win.
        `concepts/hierarchy.py` said exactly that when it rejected the all-source
        union; the counterpart just was never put in the harness.

        **The reference has to be independent of the set being scored, and my
        first attempt was not.** Scoring a claimed span correct when the gold
        concept falls in the *same* closure is circular: the 9,712-concept set
        contains the concepts an annotator used for the spans it grabbed, so it
        scored 0.823 and the blow-up passed. A set cannot be its own answer key.

        So the key is the seed's **SNOMEDCT_US ``isa`` closure** — the single
        editorially coherent clinical hierarchy, and the one the gold is
        annotated in. A claimed span counts as correct only if the expert
        annotated it with a concept a SNOMED clinician would place under the
        seed. `MTH RN` is what the phenotype set is being *tested for*, so it
        cannot also be what does the testing.

        Read with :attr:`set_recall`, never instead of it: the reference is
        deliberately the stricter hierarchy, so precision is a lower bound.
        """
        return self.claimed_correct / self.claimed if self.claimed else None

    @property
    def set_f1(self) -> float | None:
        precision, recall = self.set_precision, self.set_recall
        if not precision or not recall:
            return None
        return 2 * precision * recall / (precision + recall)

    def to_row(self) -> dict[str, Any]:
        def r(value: float | None) -> float | None:
            return round(value, 4) if value is not None else None

        return {
            "phenotype": self.phenotype,
            "concept_set_size": self.concept_set_size,
            "gold_spans": self.gold_spans,
            "span_found": self.span_found,
            "set_found": self.set_found,
            "claimed": self.claimed,
            "claimed_correct": self.claimed_correct,
            "span_recall": r(self.span_recall),
            "set_recall": r(self.set_recall),
            "set_precision": r(self.set_precision),
            "set_f1": r(self.set_f1),
        }


def evidence_spans(corpus: GoldCorpus, phenotype: Phenotype) -> tuple[GoldSpan, ...]:
    """Gold spans an expert annotated with a concept inside the phenotype."""
    return tuple(s for s in corpus.spans if s.concept_id in phenotype.concept_codes)


def load_maps(root: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """SNOMED code -> every CUI carrying it, and the inverse.

    Both directions are one-to-many. Flattening either one loses concepts, which
    is what ``declare`` documents.
    """
    cui_to_codes: dict[str, list[str]] = json.loads(
        (root / "cui_snomed.json").read_text(encoding="utf-8")
    )
    code_to_cuis: dict[str, list[str]] = {}
    for cui, codes in sorted(cui_to_codes.items()):
        for code in codes:
            code_to_cuis.setdefault(code, []).append(cui)
    return code_to_cuis, cui_to_codes


__all__ = [
    "Phenotype",
    "PhenotypeScore",
    "declare",
    "evidence_spans",
    "load_maps",
]
