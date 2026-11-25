"""How this corpus names its drugs: generically, commercially, or unclassifiably.

The corpus-level characterization `details/medication-synonyms.md` asks for —

    percentage of medication mentions expressed generically,
    percentage expressed using commercial names,
    percentage where representation cannot confidently be determined

— and, in the same record, `lexical.medication_rename`'s denominator.

Two ways in, because the package has to work at two licence levels:

* **with a concept matcher**, the mentions come from
  :func:`robustehr.concepts.pipeline.annotate_document`, filtered to the
  ``medication`` semantic category. This is the reading the PRD specifies —
  identification via UMLS, naming determined on top of it — and it is what makes
  the count a count of *medication mentions* rather than of dictionary hits.
* **without one**, every word token is looked up in the naming dictionary
  directly. That is the operator's actual eligibility path, so the baseline
  matches it; what is lost is the denominator. Without the matcher there is no
  answer to "how many medications did this note mention", only to "how many did
  we recognise", and :attr:`MedicationProfile.mentions_measured` says which
  question was answered rather than leaving a reader to assume.

The unknown share is the interesting number and should not be read as failure.
It has three separate causes worth keeping apart in a manuscript: drugs absent
from the source data, surfaces that are both a brand and a generic, and
multi-ingredient or device-bearing names the build deliberately refused. All
three mean "not confidently substitutable", which is what the operator needs;
only the first is a coverage gap.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from robustehr.drugs import Representation, load_synonyms

if TYPE_CHECKING:  # pragma: no cover
    from robustehr.document import Document

#: The semantic category a mention must carry to count as a medication. Read
#: from `semantic_categories.yaml` rather than hard-coded TUIs, so the
#: definition stays the one the rest of the package uses.
MEDICATION_CATEGORY = "medication"


@dataclass(frozen=True, slots=True)
class MedicationProfile:
    """One note's medication naming, and what could be substituted."""

    note_uid: str
    mentions: int
    generic: int
    commercial: int
    unknown: int
    eligible: int
    """Mentions with a confident equivalence — `lexical.medication_rename`'s
    denominator. Never larger than ``generic + commercial``, and usually equal:
    they differ only where a classified surface has no alternative to offer."""
    mentions_measured: bool
    """Whether a concept matcher supplied the mention set.

    ``False`` means the counts are over dictionary hits, so the shares are
    conditional on recognition and the denominator is not "medications in this
    note". Recorded rather than inferred, because the two readings differ by
    however much the dictionary misses."""
    surfaces: Counter[str] = field(default_factory=Counter)

    @property
    def shares(self) -> dict[str, float | None]:
        """The three percentages the PRD asks for, or ``None`` with no mentions."""
        if not self.mentions:
            return {"generic": None, "commercial": None, "unknown": None}
        return {
            "generic": self.generic / self.mentions,
            "commercial": self.commercial / self.mentions,
            "unknown": self.unknown / self.mentions,
        }

    def as_row(self) -> dict[str, Any]:
        return {
            "n": self.mentions,
            "generic": self.generic,
            "commercial": self.commercial,
            "unknown": self.unknown,
            "renameable": self.eligible,
            "concept_measured": int(self.mentions_measured),
        }


def _surfaces_from_mentions(doc: Document, mentions: Any) -> list[str]:
    from robustehr.categories import categories_of

    out: list[str] = []
    for mention in mentions:
        categories = getattr(mention, "categories", None)
        if categories is None:  # pragma: no cover - defensive across matcher versions
            categories = categories_of(mention.tuis)
        if MEDICATION_CATEGORY in categories:
            out.append(mention.span.surface(doc.text))
    return out


def _surfaces_from_tokens(doc: Document) -> list[str]:
    from robustehr.segment.tokens import TokenKind

    synonyms = load_synonyms()
    return [
        doc.text[t.span.start : t.span.end]
        for t in doc.tokens
        if t.kind is TokenKind.WORD
        and synonyms.classify(doc.text[t.span.start : t.span.end]) is not Representation.UNKNOWN
    ]


def profile_medications(
    doc: Document,
    mentions: Any = None,
    *,
    keep_surfaces: bool = True,
) -> MedicationProfile:
    """Classify every medication mention in one note as generic / commercial / unknown.

    ``mentions`` is a :class:`~robustehr.concepts.matcher.MentionIndex` when a
    matcher has run. Passing ``None`` is not an error; it selects the
    dictionary-only path and sets ``mentions_measured`` accordingly.
    """
    synonyms = load_synonyms()
    measured = mentions is not None
    surfaces = _surfaces_from_mentions(doc, mentions) if measured else _surfaces_from_tokens(doc)

    counts: Counter[Representation] = Counter()
    eligible = 0
    seen: Counter[str] = Counter()
    for surface in surfaces:
        representation = synonyms.classify(surface)
        counts[representation] += 1
        if synonyms.alternatives(surface):
            eligible += 1
            if keep_surfaces:
                seen[surface.lower()] += 1

    return MedicationProfile(
        note_uid=doc.uid,
        mentions=len(surfaces),
        generic=counts[Representation.GENERIC],
        commercial=counts[Representation.COMMERCIAL],
        unknown=counts[Representation.UNKNOWN],
        eligible=eligible,
        mentions_measured=measured,
        surfaces=seen,
    )


__all__ = ["MEDICATION_CATEGORY", "MedicationProfile", "profile_medications"]
