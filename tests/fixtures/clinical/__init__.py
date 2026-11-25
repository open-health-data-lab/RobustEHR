"""A deliberately varied synthetic clinical corpus.

The development corpus is one narrow thing: MIMIC-IV discharge summaries from a
single US academic centre, hard-wrapped at 63 characters, masked with ``___``,
in American English, containing no tabs and no tables. Real clinical text is
nothing like that uniform. Plenty of clinicians write free prose with no
template at all — outpatient visits especially — and structure, vocabulary,
abbreviation density and punctuation habits vary sharply by setting and by
specialty.

Tuning a segmenter against one style produces a package that works beautifully
there and silently misbehaves everywhere else, so every structural guarantee is
tested against this whole corpus rather than against MIMIC alone. An invariant
that holds only for templated inpatient text is a bug, not a property of
clinical language.

The corpus deliberately varies along five axes at once:

**Setting** — inpatient, outpatient, emergency, critical care, procedural,
community, virtual.

**Specialty** — vocabulary, measurement conventions and note conventions differ
enormously between, say, obstetrics (G/P notation, gestational age), oncology
(staging, regimens, cycle numbers), psychiatry (mental status exam, verbatim
patient quotes) and dermatology (lesion morphology, body-site maps).

**Structure** — from fully templated with pick-list residue, through
problem-oriented and semi-structured, down to a single unbroken paragraph or a
two-line addendum.

**Serialization** — hard wrap or none, tabs, pipe tables, markdown, all-caps
legacy output, and eight different de-identification conventions.

**Language and quality** — American and British English, French, mixed
French/English as written in Quebec, dictation artifacts, and the typos and
inconsistencies that are present in real records and that the document quality
profile has to measure rather than assume away.

All text is written from scratch and describes no real patient, so the corpus is
public: it backs golden tests, documentation examples and the sample renderings
in shareable reports, none of which may contain restricted text.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SyntheticNote:
    """A note plus the facts a segmenter has to cope with."""

    id: str
    text: str
    setting: str
    """Where care happened: inpatient, outpatient, emergency, critical_care,
    procedural, community, virtual."""
    specialty: str
    note_type: str
    structure: str
    """How much scaffolding the author used: templated, problem_oriented,
    semi_structured, free_text, dictated, telegraphic, letter, tabular."""
    source_style: str
    deid_scheme: str
    hard_wrapped: bool
    language: str
    stresses: str
    """What this note is here to break."""


from tests.fixtures.clinical.acute import NOTES as _ACUTE  # noqa: E402
from tests.fixtures.clinical.community import NOTES as _COMMUNITY  # noqa: E402
from tests.fixtures.clinical.inpatient import NOTES as _INPATIENT  # noqa: E402
from tests.fixtures.clinical.outpatient import NOTES as _OUTPATIENT  # noqa: E402
from tests.fixtures.clinical.procedural import NOTES as _PROCEDURAL  # noqa: E402

_ALL: tuple[SyntheticNote, ...] = (
    *_INPATIENT,
    *_OUTPATIENT,
    *_ACUTE,
    *_PROCEDURAL,
    *_COMMUNITY,
)

#: Every note, keyed by id.
FORMATS: dict[str, SyntheticNote] = {note.id: note for note in _ALL}

if len(FORMATS) != len(_ALL):  # pragma: no cover - guards a copy-paste mistake
    raise RuntimeError("duplicate synthetic note id")

SETTINGS: tuple[str, ...] = tuple(sorted({n.setting for n in _ALL}))
SPECIALTIES: tuple[str, ...] = tuple(sorted({n.specialty for n in _ALL}))
STRUCTURES: tuple[str, ...] = tuple(sorted({n.structure for n in _ALL}))
LANGUAGES: tuple[str, ...] = tuple(sorted({n.language for n in _ALL}))
DEID_SCHEMES: tuple[str, ...] = tuple(sorted({n.deid_scheme for n in _ALL}))


def notes_where(**criteria: str) -> tuple[SyntheticNote, ...]:
    """Select notes by any combination of declared attributes."""
    return tuple(
        note
        for note in _ALL
        if all(getattr(note, field) == value for field, value in criteria.items())
    )


__all__ = [
    "DEID_SCHEMES",
    "FORMATS",
    "LANGUAGES",
    "SETTINGS",
    "SPECIALTIES",
    "STRUCTURES",
    "SyntheticNote",
    "notes_where",
]
