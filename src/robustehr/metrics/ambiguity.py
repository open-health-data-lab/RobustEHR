"""How much ambiguous shorthand does this note carry, and which tokens are they?

A baseline-quality dimension in the same sense as the Document Quality Profile's
others: a property of the note **before any operator runs**, which conditions
what any downstream system can do with it. A discharge summary dense in
ambiguous abbreviations is harder for every reader, human or otherwise,
independently of anything this package does to it.

It earns a place next to misspelling rate and de-identification density because
it behaves like them — measurable per note, stable under re-measurement, and a
plausible **stratifier** for a robustness result. "Performance fell 6 points
under this operator" reads differently once you know the notes in the affected
tertile carried three times the ambiguous shorthand.

**Two headline numbers and a band above them.**

``abbreviations``        every abbreviation-shaped token in the note.
``ambiguous``            those carrying **2 or more** concepts as written. A
                         sense must be chosen, so every downstream reading of
                         the note depends on choosing it right.
``highly_ambiguous``     those carrying **5 or more**. Reported separately
                         because the two are not the same problem: a two-way
                         choice is often settled by one nearby word, while
                         ``pt`` at nine senses is not settled by anything short
                         of a resolver, and a note dense in these is hard in a
                         way a mean would hide.

Each token also gets an outcome, which partitions the same population by what
can be *done* rather than by how ambiguous it is:

``resolved``      one concept as written; the matcher handles it unaided.
``ambiguous``     several concepts; a sense must be chosen.
``expandable``    no concept as written, but a shipped table knows it — the
                  institutional shorthand stage 3b covers.
``unreachable``   no concept and no table entry. Not necessarily an
                  abbreviation at all; may simply be a word no terminology
                  carries.

**Senses are counted in UMLS concepts, with the SNOMED subset reported
alongside.** UMLS is the right denominator for "how ambiguous is this token",
because it is the space the matcher actually chooses among; the SNOMED count is
carried too because that is the space a phenotype set is declared in, and the
two differ — ``pt`` has 9 UMLS concepts and far fewer with a SNOMED code.

This module needs a terminology and the core profile deliberately does not, so
it lives beside :mod:`robustehr.metrics.dqp` rather than inside it. A run with
no concept layer configured still gets a full quality profile.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from robustehr.concepts.expansion import Slot, load_expansions
from robustehr.concepts.matcher import ConceptMatcher, MatcherConfig
from robustehr.document import Document
from robustehr.dose import as_pair, ratio
from robustehr.lexical import english_vocabulary
from robustehr.types import Span

#: Bounds of an abbreviation-shaped token, in characters. Matches the definition
#: the stage-3 gate used, so the two measurements describe the same population.
MIN_CHARS, MAX_CHARS = 2, 6

#: Concepts at which a surface counts as ambiguous, and as highly ambiguous.
#:
#: Two is the definition rather than a threshold: one concept is not a choice.
#: Five is a judgement, chosen because it separates forms a single nearby cue
#: can settle from forms where the candidate set is the problem — `pt` at nine
#: and `ra` at five behave differently from a two-way split. It is a reporting
#: band, never a control-flow boundary, so nothing downstream changes if a
#: reader prefers a different cut.
AMBIGUOUS_AT = 2
HIGHLY_AMBIGUOUS_AT = 5


#: Sense-count bands, in reporting order. `2-4` is where a nearby word usually
#: settles the choice and `10+` is where nothing short of a resolver does, so
#: the bands are the shape of the problem rather than an arbitrary binning.
SENSE_BANDS = ("0", "1", "2-4", "5-9", "10+")


def _band(senses: int) -> str:
    """Which reporting band a sense count falls in."""
    if senses == 0:
        return "0"
    if senses == 1:
        return "1"
    if senses < HIGHLY_AMBIGUOUS_AT:
        return "2-4"
    if senses < 10:
        return "5-9"
    return "10+"


class Outcome(StrEnum):
    """What the terminology can do with one abbreviation-shaped token."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    EXPANDABLE = "expandable"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One abbreviation-shaped token and what could be made of it."""

    span: Span
    surface: str
    outcome: Outcome
    senses: int
    """UMLS concepts carrying this surface as written — the ambiguity itself."""
    snomed_senses: int = 0
    """Of those, how many carry a SNOMED code.

    Carried because a phenotype set is declared in SNOMED while the matcher
    chooses among UMLS, so "ambiguous" has two defensible denominators and a
    reader should not have to guess which one produced a number.
    """

    @property
    def ambiguous(self) -> bool:
        return self.senses >= AMBIGUOUS_AT

    @property
    def highly_ambiguous(self) -> bool:
        return self.senses >= HIGHLY_AMBIGUOUS_AT


@dataclass(frozen=True, slots=True)
class AmbiguityProfile:
    """Abbreviation load for one note, with the ambiguous tokens themselves."""

    note_uid: str
    note_sha256: str
    content_tokens: int
    counts: dict[str, int] = field(default_factory=dict)
    occurrences: tuple[Occurrence, ...] = ()

    abbreviations: int = 0
    """Every abbreviation-shaped token — the first headline number."""
    ambiguous: int = 0
    """Those carrying two or more concepts — the second."""
    highly_ambiguous: int = 0
    """Those carrying five or more."""
    ambiguous_snomed: int = 0
    """Ambiguous when counted in SNOMED concepts rather than UMLS ones."""
    sense_bands: dict[str, int] = field(default_factory=dict)
    """How the ambiguity is distributed: `0`, `1`, `2-4`, `5-9`, `10+` senses.

    `ambiguous` collapses everything from two senses to twenty into one number,
    and those are not the same problem — a two-way choice is often settled by
    one nearby word, while a twenty-way one is not settled by anything short of
    a resolver. The band histogram is what lets a reader see which corpus they
    have without re-running with a different threshold.
    """

    @property
    def ambiguity_rate(self) -> Fraction | None:
        """Ambiguous tokens per abbreviation-shaped token.

        ``None`` rather than zero when the note contains no abbreviations at
        all — a note with nothing to be ambiguous about has no rate, and
        reporting 0 would place it alongside notes whose shorthand all resolved.
        """
        return ratio(self.ambiguous, self.abbreviations)

    @property
    def high_ambiguity_rate(self) -> Fraction | None:
        return ratio(self.highly_ambiguous, self.abbreviations)

    def most_ambiguous(self, limit: int = 10) -> list[tuple[str, int]]:
        """The worst offenders in this note, surface and sense count."""
        worst = {o.surface.lower(): o.senses for o in self.occurrences if o.ambiguous}
        return sorted(worst.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    @property
    def density(self) -> Fraction | None:
        """Ambiguous tokens per content token — comparable across note lengths."""
        return ratio(self.ambiguous, self.content_tokens)

    def ambiguous_surfaces(self) -> Counter[str]:
        """The ambiguous tokens themselves, by frequency."""
        return Counter(o.surface.lower() for o in self.occurrences if o.ambiguous)

    def to_row(self) -> dict[str, object]:
        return {
            "note_uid": self.note_uid,
            "note_sha256": self.note_sha256,
            "content_tokens": self.content_tokens,
            "abbreviations": self.abbreviations,
            "ambiguous": self.ambiguous,
            "highly_ambiguous": self.highly_ambiguous,
            "ambiguous_snomed": self.ambiguous_snomed,
            "counts": dict(sorted(self.counts.items())),
            "sense_bands": dict(sorted(self.sense_bands.items())),
            "ambiguity_rate": as_pair(self.ambiguity_rate),
            "high_ambiguity_rate": as_pair(self.high_ambiguity_rate),
            "density": as_pair(self.density),
            "most_ambiguous": self.most_ambiguous(),
            "ambiguous_surfaces": dict(sorted(self.ambiguous_surfaces().items())),
        }


#: Longest an all-capitals token may be and still override the English list.
#:
#: The rescue this exists for is `RA`, `PO`, `MS`, `PE`, `DM` and `BS` — genuine
#: abbreviations whose lowercase form is also an English word, so the word list
#: alone loses them. It is bounded at three characters because the collisions
#: that matter are short: `BLOOD` and `STABLE` are all-capitals in MIMIC lab
#: lines and headings and are plainly not abbreviations.
#:
#: No frequency threshold does this job. `ms` sits at Zipf 4.67 and `mild` at
#: 4.11, so any cut that keeps the abbreviation admits the adjective.
SHORT_CAPS_MAX = 3


def is_mixed_case(surface: str) -> bool:
    """An internal capital in a token that is not simply shouting.

    The orthographic signature of a clinical abbreviation: ``HFrEF`` and
    ``AnGap`` carry one, while ``Stable`` at a sentence start does not, and
    neither does ``BLOOD``. Initial capitalisation is a property of position in
    a sentence and says nothing; a capital *inside* a token, in a word that is
    not entirely capitals, is a deliberate choice by the author.
    """
    return any(c.isupper() for c in surface[1:]) and not surface.isupper()


def is_abbreviation_shaped(surface: str) -> bool:
    """One token, 2-6 characters, all alphabetic, and not ordinary English.

    The English exclusion is what stops `clear`, `stable` and `wound` being
    counted as abbreviations. Without it the population inflates by roughly a
    third, in the direction that flatters the result.

    It reads :func:`~robustehr.lexical.english_vocabulary`, **not**
    :func:`~robustehr.lexical.general_english`. The latter subtracts the 2,686
    words carrying a high-precision clinical type, so that `resolve_tags` lets
    the terminology speak for them — correct for that question, and wrong for
    this one, because it means `stable`, `mild`, `wound` and `fever` are absent
    and would each be counted as an abbreviation.

    **Casing overrides the word list, in two bounded ways.** A broader list
    over-excludes in the other direction: ``ra`` is in it — Ra, the Egyptian god,
    clears Zipf 3.0 — so the list alone loses ``RA``, the canonical ambiguous
    abbreviation in this corpus. The same is true of ``PO``, ``MS``, ``PE``,
    ``DM`` and ``BS``.

    So a token also counts as an abbreviation when it is **mixed case**
    (``HFrEF``, ``AnGap`` — a capital the author chose to put there) or when it
    is **all capitals and at most three characters** (``RA``, ``PO``). The length
    bound is what stops the second rule readmitting everything: ``BLOOD`` and
    ``STABLE`` are all-capitals in MIMIC lab lines and headings and are plainly
    not abbreviations.

    No frequency threshold does this job, which is why the rule is orthographic.
    ``ms`` sits at Zipf 4.67 and ``mild`` at 4.11, so any cut that keeps the
    abbreviation admits the adjective.
    """
    stripped = surface.strip()
    if not (MIN_CHARS <= len(stripped) <= MAX_CHARS and stripped.isalpha()):
        return False
    if stripped.lower() not in english_vocabulary():
        return True
    if is_mixed_case(stripped):
        return True
    return stripped.isupper() and len(stripped) <= SHORT_CAPS_MAX


@lru_cache(maxsize=1)
def _snomed_cuis() -> frozenset[str]:
    """CUIs that carry a SNOMED code, for the second sense count.

    Empty when the crosswalk is absent, in which case the SNOMED band reads 0
    and the UMLS counts are unaffected — a missing artifact must not silently
    change the headline numbers.
    """

    try:
        raw = json.loads(Path("data/snomed_el/cui_snomed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    return frozenset(raw)


@lru_cache(maxsize=4)
def _sense_lookup(index: Path) -> ConceptMatcher:
    """A permissive matcher used only to count senses, built once per index.

    Distinct from the caller's matcher in three ways that matter — no semantic
    type filter, no similarity threshold and a minimum match length of one —
    because the question is "how many concepts carry this surface", not "which
    concept does this span mean".

    Cached because it is not: instantiating QuickUMLS loads the whole index, and
    building one per note made `describe` take 24 seconds on five notes and
    would have made it unusable on a corpus.
    """
    return ConceptMatcher(
        index,
        MatcherConfig(threshold=1.0, min_match_length=1, accepted_semtypes=None),
        align_semtypes=False,
    )


def profile_ambiguity(
    doc: Document,
    matcher: ConceptMatcher,
    *,
    keep_occurrences: bool = True,
) -> AmbiguityProfile:
    """Count and locate the ambiguous shorthand in one note.

    Senses are counted **as written**: concepts carrying an atom equal to the
    surface itself. That is the same question the derived-inventory filter asks,
    and for the same reason — it is what a reader means by "this abbreviation is
    ambiguous", as opposed to a terminology-internal property of its synonym set.

    ``keep_occurrences=False`` reports counts only, for corpus sweeps where the
    per-token detail would dominate the output.
    """
    lookup = _sense_lookup(matcher.index)
    table = load_expansions()
    snomed_cuis = _snomed_cuis()
    senses: dict[str, tuple[int, int]] = {}
    found: list[Occurrence] = []
    counts: Counter[str] = Counter()
    bands: Counter[str] = Counter()

    for token in doc.tokens:
        if not token.is_content or not is_abbreviation_shaped(token.surface(doc.text)):
            continue
        surface = token.surface(doc.text)
        key = surface.lower()
        if key not in senses:
            groups = lookup._load().match(key, best_match=False, ignore_syntax=True)
            cuis = {str(c["cui"]) for g in groups for c in g if str(c["ngram"]).lower() == key}
            senses[key] = (len(cuis), sum(1 for c in cuis if c in snomed_cuis))
        n, n_snomed = senses[key]
        if n >= AMBIGUOUS_AT:
            outcome = Outcome.AMBIGUOUS
        elif n == 1:
            outcome = Outcome.RESOLVED
        elif any(table.expand(key, slot) for slot in Slot):
            outcome = Outcome.EXPANDABLE
        else:
            outcome = Outcome.UNREACHABLE
        counts[outcome.value] += 1
        bands[_band(n)] += 1
        if n >= AMBIGUOUS_AT:
            bands["ambiguous"] += 1
        if n >= HIGHLY_AMBIGUOUS_AT:
            bands["highly_ambiguous"] += 1
        if n_snomed >= AMBIGUOUS_AT:
            bands["ambiguous_snomed"] += 1
        if keep_occurrences:
            found.append(Occurrence(token.span, surface, outcome, n, n_snomed))

    return AmbiguityProfile(
        note_uid=doc.uid,
        note_sha256=doc.sha256,
        content_tokens=sum(1 for t in doc.tokens if t.is_content),
        abbreviations=sum(counts.values()),
        ambiguous=bands["ambiguous"],
        highly_ambiguous=bands["highly_ambiguous"],
        ambiguous_snomed=bands["ambiguous_snomed"],
        counts=dict(counts),
        sense_bands={k: v for k, v in bands.items() if k in SENSE_BANDS},
        occurrences=tuple(found),
    )


__all__ = [
    "AMBIGUOUS_AT",
    "HIGHLY_AMBIGUOUS_AT",
    "MAX_CHARS",
    "MIN_CHARS",
    "SENSE_BANDS",
    "SHORT_CAPS_MAX",
    "AmbiguityProfile",
    "Occurrence",
    "Outcome",
    "is_abbreviation_shaped",
    "is_mixed_case",
    "profile_ambiguity",
]
