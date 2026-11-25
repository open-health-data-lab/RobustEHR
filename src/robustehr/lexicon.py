"""Is this token clinical?

A vocabulary has two quite different jobs here, and conflating them was a design
error worth naming.

**Generation** — deciding what a plausible corruption of a word looks like —
mostly does not need one. Phonotactics and acoustic proximity are algorithms, and
morpheme rules generate across the whole lexicon. A vocabulary is needed there
only where the error being modelled is itself lexicon-constrained, as speech
recognition is.

**Measurement** — deciding whether a perturbation landed on clinical content — is
the job that matters for RobustEHR, and it needs a real terminology. A typo in
``the`` and a typo in ``obese`` are the same operator at the same dose and mean
entirely different things; a result that cannot tell them apart is not measuring
what it claims.

The primary method is therefore the standard, citable one: **dictionary lookup
against a versioned terminology, filtered by semantic type**. UMLS strings from
concepts in McCray's clinical semantic groups, built by
:mod:`robustehr.concepts.umls`. This is what MetaMap, cTAKES and QuickUMLS all do
at core, and it is reproducible by anyone with the same release.

A morphological classifier remains, but **only as a labelled fallback for
installations with no terminology**, and its cost is measured rather than
assumed. Against the UMLS 2026AA labels over the 11,767 word types in 200
development notes (``robustehr concepts validate``, recorded in
``validation/measurements/lexicon_fallback.json``): precision 0.607, recall 0.103,
F1 0.175.

Token coverage tells the same story more starkly. The terminology classifies
54.3% of running tokens as clinical; the fallback manages 3.4%. It misses
``tablet``, ``blood``, ``pain``, ``discharge``, ``patient``, ``history`` — every
clinical word that carries no diagnostic morphology, which is most of them.

The two error directions are not symmetric, and reading them as if they were
would misstate the result. Among the 360 disagreements where the heuristic says
clinical and the terminology does not, the recurrent ones are almost all *real
clinical vocabulary the extraction misses*: derived adjectival forms whose noun
is present but whose adjective is not (``hyperkalemic``, ``euvolemic``,
``dysarthric``, ``hypercarbic``, ``hypodensity``), and specialty names
(``gastroenterology``, ``hepatology``). Genuine heuristic errors are the
minority — ``interaction`` and ``interactive``, where the ``inter-`` prefix rule
fires on ordinary English.

So 0.607 understates the heuristic and overstates the terminology, and the real
lesson is about the *reference*: single-word concept lookup under-covers
morphological derivation. That is a known limitation of dictionary matching and
the reason NLM's normalized index exists; closing it is future work on the
terminology tier, not on the fallback. It is also why this is reported as an
agreement study rather than an accuracy study.

The recall figure has no such defence. Missing ``blood``, ``pain`` and
``patient`` is not a reference artifact.

**Read 54.3% as an upper bound, not as the clinical-content rate.** Over half of
content words being clinical is not plausible for a discharge summary, and the
reason is that word-level lookup cannot be made accurate: UMLS carries ``one``,
``well``, ``normal``, ``stairs`` and ``walking`` as Disorder concepts, the same
semantic group as ``dyspnea``. Frequency, source count and semantic group were
each tested as discriminators and each failed. The resolution is concept-level
matching in context, validated against gold spans — see docs/ROADMAP.md §4.

Reporting all of it is the point. A run without a terminology is not silently
degraded: ``lexicon_source`` records which method was used, unclassified tokens
are counted as ``unknown`` rather than folded into non-clinical, and the numbers
above say what the difference costs.

The eventual refinement is narrower still — not merely *clinical*, but *related
to the phenotype under study* — which is what the concept layer adds on top.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from robustehr.categories import categories_of, tuis_for
from robustehr.resources import load_yaml
from robustehr.segment.tokens import Token, TokenKind


class TokenClass(StrEnum):
    CLINICAL = "clinical"
    NON_CLINICAL = "non_clinical"
    STRUCTURAL = "structural"
    """Headers, list markers, de-identification masks: not language."""
    NUMERIC = "numeric"
    UNKNOWN = "unknown"
    """No evidence either way. Deliberately distinct from ``NON_CLINICAL``."""


class Evidence(StrEnum):
    """Which method decided a classification.

    Recorded per token so that a report can say how much of a result rests on
    the terminology and how much on the fallback.
    """

    TERMINOLOGY = "terminology"
    """Matched the UMLS-derived clinical vocabulary. The primary method."""
    CLOSED_CLASS = "closed_class"
    """An English function word. A genuinely finite class, so a list is right."""
    MORPHOLOGY = "morphology"
    """Clinical affix, with no terminology installed. P=0.61, R=0.10 — see the
    module docstring. Present so a run without UMLS still yields *something*,
    not because it is adequate."""
    STRUCTURE = "structure"
    NONE = "none"


LEXICON_RESOURCE = "lexicon.yaml"


@dataclass(frozen=True, slots=True)
class Morphology:
    """Affix signals for the algorithmic tier, loaded from a hashed resource."""

    clinical_suffixes: tuple[str, ...]
    clinical_prefixes: tuple[str, ...]
    closed_class: frozenset[str]
    min_word_length: int
    min_stem_after_prefix: int


@lru_cache(maxsize=1)
def load_morphology() -> Morphology:
    raw: dict[str, Any] = load_yaml(LEXICON_RESOURCE)
    suffixes = tuple(str(s) for group in raw["clinical_suffixes"].values() for s in group)
    closed = frozenset(str(w) for group in raw["closed_class"].values() for w in group)
    return Morphology(
        clinical_suffixes=suffixes,
        clinical_prefixes=tuple(str(p) for p in raw["clinical_prefixes"]),
        closed_class=closed,
        min_word_length=int(raw["min_word_length"]),
        min_stem_after_prefix=int(raw["min_stem_after_prefix"]),
    )


class Specificity(StrEnum):
    """How strongly a clinical token's surface form implies clinical content.

    Terminology membership is not the same as being clinical evidence. UMLS
    contains ``one`` as a Finding, ``date`` as a Pharmacologic Substance and
    ``home`` as a Health Care Activity, and counting an edit to ``one`` as a hit
    on clinical content would inflate every landing measurement in the package.

    This is reported, not resolved. Whether ``discharge`` is clinical depends on
    whether it heads *purulent discharge* or *discharge summary*, and no
    word-level classifier can tell. Concept-level matching in context can, and
    that is what the concept layer is for; until then the ambiguity is surfaced
    so a reader can see how much of a result rests on it.
    """

    SPECIFIC = "specific"
    """Rare in general English, so its presence implies clinical content."""
    AMBIGUOUS = "ambiguous"
    """Also an ordinary English word (``blood``, ``pain``, ``normal``).

    Still clinical — just weaker evidence, and counted separately.
    """


@dataclass(frozen=True, slots=True)
class Classification:
    token_class: TokenClass
    evidence: Evidence
    specificity: Specificity | None = None
    """Set only when ``token_class`` is ``CLINICAL``."""

    @property
    def is_clinical(self) -> bool:
        return self.token_class is TokenClass.CLINICAL

    @property
    def is_measured(self) -> bool:
        """Did anything actually decide this, or is it merely unclassified?"""
        return self.evidence is not Evidence.NONE


def clinical_by_morphology(word: str) -> bool:
    """Does this word carry clinical morphology?

    Pure algorithm. Recognises ``cholecystectomy`` and ``hypogammaglobulinemia``
    without either appearing in any list, which is the property that lets the
    classifier follow the vocabulary into a new specialty.
    """
    morphology = load_morphology()
    lowered = word.lower()
    if len(lowered) < morphology.min_word_length:
        return False
    if lowered.endswith(morphology.clinical_suffixes):
        return True
    # A prefix modifies rather than heads, so it is weaker evidence and needs a
    # substantial stem behind it: "subtotal" is clinical, "subject" is not.
    return any(
        lowered.startswith(prefix)
        and len(lowered) - len(prefix) >= morphology.min_stem_after_prefix
        for prefix in morphology.clinical_prefixes
    )


@dataclass(frozen=True, slots=True)
class Lexicon:
    """Classifies tokens as clinical or not, with graceful degradation.

    ``clinical`` and ``general`` are optional. Supplied from the concept layer's
    UMLS build or by the user; absent, classification falls back to morphology
    and closed-class exclusion, which cover a useful fraction with high
    precision.
    """

    clinical: frozenset[str] = frozenset()
    ambiguous: frozenset[str] = frozenset()
    """Clinical tokens that are also ordinary English. Subset of ``clinical``."""
    tuis: Mapping[str, frozenset[str]] = field(default_factory=dict)
    """UMLS semantic types per token, e.g. ``{"warfarin": {"T121", "T109"}}``.

    The primary axis. A target names *what kind* of thing to hit — medications,
    diagnoses, symptoms, anatomy — and that selectivity is the package's actual
    product, since the corruption mechanisms are target-agnostic by nature.

    Semantic types rather than Semantic Groups, because groups put Disease or
    Syndrome and Sign or Symptom in the same bucket and a phenotyping study needs
    them apart. See :mod:`robustehr.categories`.
    """
    general: frozenset[str] = frozenset()
    source: str = "morphology-only"
    """Which vocabulary this is, recorded in every dose record.

    ``umls-2026AA`` when a terminology is installed; ``morphology-only``
    otherwise. The distinction belongs in the output, not in a footnote.
    """
    release: str = ""

    @property
    def has_vocabulary(self) -> bool:
        return bool(self.clinical)

    def _by_kind(self, token: Token) -> Classification | None:
        if token.kind in {TokenKind.PLACEHOLDER, TokenKind.DIVIDER}:
            return Classification(TokenClass.STRUCTURAL, Evidence.STRUCTURE)
        if token.kind is TokenKind.NUMBER:
            return Classification(TokenClass.NUMERIC, Evidence.STRUCTURE)
        if not token.is_content:
            return Classification(TokenClass.STRUCTURAL, Evidence.STRUCTURE)
        return None

    def classify(self, token: Token) -> Classification:
        by_kind = self._by_kind(token)
        if by_kind is not None:
            return by_kind

        word = token.lower
        if word in self.clinical:
            return Classification(
                TokenClass.CLINICAL,
                Evidence.TERMINOLOGY,
                Specificity.AMBIGUOUS if word in self.ambiguous else Specificity.SPECIFIC,
            )
        if word in load_morphology().closed_class:
            return Classification(TokenClass.NON_CLINICAL, Evidence.CLOSED_CLASS)
        if clinical_by_morphology(word):
            # Clinical morphology is by definition not ordinary English, so a
            # word reaching here is specific whether or not a vocabulary exists.
            return Classification(TokenClass.CLINICAL, Evidence.MORPHOLOGY, Specificity.SPECIFIC)
        if self.has_vocabulary or word in self.general:
            # A terminology was consulted and the word is absent, which is
            # itself evidence — unlike the fallback, where absence means only
            # that no affix matched.
            return Classification(TokenClass.NON_CLINICAL, Evidence.TERMINOLOGY)
        # No vocabulary and no morphology: genuinely unknown. Saying so is more
        # useful than guessing non-clinical, and it is what tells a reader how
        # much of a result rests on unclassified tokens.
        return Classification(TokenClass.UNKNOWN, Evidence.NONE)

    def semantic_types(self, word: str) -> frozenset[str]:
        return self.tuis.get(word.lower(), frozenset())

    def in_categories(self, word: str, *names: str) -> bool:
        """Does this token belong to any of the named semantic categories?

        The question that replaced "is this word clinical". ``in_categories(w,
        "medication")`` has a crisp answer; "is it clinical" does not.
        """
        return bool(self.semantic_types(word) & tuis_for(*names))

    def categories(self, word: str) -> frozenset[str]:
        """Which named categories this token belongs to, possibly none."""
        return categories_of(self.semantic_types(word))

    def classify_word(self, word: str) -> Classification:
        """Classify a bare word, for callers that hold no ``Token``."""
        lowered = word.lower()
        if lowered in self.clinical:
            return Classification(
                TokenClass.CLINICAL,
                Evidence.TERMINOLOGY,
                Specificity.AMBIGUOUS if lowered in self.ambiguous else Specificity.SPECIFIC,
            )
        if lowered in load_morphology().closed_class:
            return Classification(TokenClass.NON_CLINICAL, Evidence.CLOSED_CLASS)
        if clinical_by_morphology(lowered):
            return Classification(TokenClass.CLINICAL, Evidence.MORPHOLOGY, Specificity.SPECIFIC)
        if self.has_vocabulary:
            return Classification(TokenClass.NON_CLINICAL, Evidence.TERMINOLOGY)
        return Classification(TokenClass.UNKNOWN, Evidence.NONE)

    def counts(self, tokens: tuple[Token, ...]) -> dict[str, int]:
        """Class counts over a token sequence, for the dose record."""
        out: dict[str, int] = dict.fromkeys((c.value for c in TokenClass), 0)
        for token in tokens:
            out[self.classify(token).token_class.value] += 1
        return out


def load_clinical_lexicon(path: Path) -> Lexicon:
    """Load the locally built UMLS-derived vocabulary.

    Built by ``robustehr concepts build-lexicon`` from the user's own UMLS
    installation. Not shipped: UMLS strings are licensed content, so what
    travels with the package is the builder and the manifest hash, which is
    enough for a reader with the same release to reproduce it exactly.
    """
    manifest_path = path.with_suffix(".manifest.json")
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    clinical: set[str] = set()
    ambiguous: set[str] = set()
    tuis: dict[str, frozenset[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.rstrip("\n")
        if not entry.strip():
            continue
        # `token[<TAB>groups[<TAB>tier]]`. The trailing columns are optional so
        # that a hand-written vocabulary is just a list of words.
        fields = entry.split("\t")
        token = fields[0].strip().lower()
        clinical.add(token)
        if len(fields) > 1 and fields[1].strip():
            tuis[token] = frozenset(t for t in fields[1].strip().split("|") if t)
        if len(fields) > 2 and fields[2].strip() == Specificity.AMBIGUOUS.value:
            ambiguous.add(token)
    release = str(manifest.get("umls_release", "unknown"))
    return Lexicon(
        clinical=frozenset(clinical),
        ambiguous=frozenset(ambiguous),
        tuis=tuis,
        source=f"umls-{release}",
        release=release,
    )


#: The default: no terminology, morphology and closed-class only. Adequate for a
#: structure-only run; not adequate for a clinical-content claim.
DEFAULT_LEXICON = Lexicon()


__all__ = [
    "DEFAULT_LEXICON",
    "LEXICON_RESOURCE",
    "Classification",
    "Evidence",
    "Lexicon",
    "Morphology",
    "Specificity",
    "TokenClass",
    "clinical_by_morphology",
    "load_clinical_lexicon",
    "load_morphology",
]
