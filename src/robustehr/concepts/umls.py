"""UMLS Metathesaurus access, and the clinical lexicon derived from it.

A hand-written affix heuristic is not a defensible primary method for deciding
whether a token is clinical: the affix set is unvalidated, its coverage is
unmeasured, and it is exactly the kind of ad hoc rule a reviewer is right to
object to. The defensible method is the standard one
in the field — dictionary lookup against a versioned terminology, filtered by
semantic type — which is what MetaMap, cTAKES and QuickUMLS all do at core and
what can be cited.

So UMLS is the ground truth here, and the morphological classifier is demoted to
a *fallback for when no terminology is installed*, with its precision and recall
measured against the UMLS-derived labels and reported. That reframing is what
makes it publishable: not "we wrote some rules", but "we measured what the rules
cost relative to the terminology".

Three deliberate choices, each because the alternative is harder to defend:

* **Semantic groups, not a hand-picked TUI list.** McCray's Semantic Groups are
  a published, stable partition of the 127 UMLS semantic types into 15 coarse
  groups, and citing them beats justifying an arbitrary selection of TUIs.
* **NLM's own normalization.** ``MRXNS_ENG.RRF`` is the Metathesaurus normalized
  string index produced by the SPECIALIST Lexicon's ``luinorm``. Using NLM's
  normalization rather than inventing one means term matching is reproducible by
  anyone with the same release and needs no description beyond a citation.
* **Suppressible content is excluded.** ``SUPPRESS != 'N'`` marks strings NLM
  flags as obsolete or problematic; including them inflates coverage with
  material the terminology itself disavows.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: McCray's UMLS Semantic Groups (Bodenreider & McCray 2003), as the coarse
#: partition used to decide what counts as clinical content. Published and
#: stable, which is why this is a citation rather than a judgement call.
SEMANTIC_GROUPS: dict[str, str] = {
    "ACTI": "Activities & Behaviors",
    "ANAT": "Anatomy",
    "CHEM": "Chemicals & Drugs",
    "CONC": "Concepts & Ideas",
    "DEVI": "Devices",
    "DISO": "Disorders",
    "GENE": "Genes & Molecular Sequences",
    "GEOG": "Geographic Areas",
    "LIVB": "Living Beings",
    "OBJC": "Objects",
    "OCCU": "Occupations",
    "ORGA": "Organizations",
    "PHEN": "Phenomena",
    "PHYS": "Physiology",
    "PROC": "Procedures",
}

#: The groups that constitute *clinical content* for the purpose of deciding
#: whether a perturbation landed on something clinically meaningful.
#:
#: CONC, GEOG, OCCU and ORGA are excluded deliberately: they carry concepts like
#: "Monday", "Canada" and "hospital" which are in UMLS but are not the clinical
#: substance of a note, and including them would classify most of a document as
#: clinical and destroy the distinction the measurement exists to make.
CLINICAL_GROUPS: frozenset[str] = frozenset(
    {"ANAT", "CHEM", "DEVI", "DISO", "GENE", "LIVB", "PHEN", "PHYS", "PROC"}
)

#: Semantic types belonging to each group. Derived from the published Semantic
#: Groups file; stored here so the build needs no network access.
GROUP_BY_TUI: dict[str, str] = {}


def _register(group: str, *tuis: str) -> None:
    for tui in tuis:
        GROUP_BY_TUI[tui] = group


_register(
    "ANAT", "T017", "T029", "T023", "T030", "T031", "T022", "T025", "T026", "T018", "T021", "T024"
)
_register(
    "CHEM",
    "T116",
    "T195",
    "T123",
    "T122",
    "T118",
    "T103",
    "T120",
    "T104",
    "T200",
    "T196",
    "T126",
    "T131",
    "T125",
    "T129",
    "T130",
    "T197",
    "T114",
    "T109",
    "T121",
    "T192",
    "T127",
)
_register("DEVI", "T203", "T074", "T075")
_register(
    "DISO",
    "T020",
    "T190",
    "T049",
    "T019",
    "T047",
    "T050",
    "T033",
    "T037",
    "T048",
    "T191",
    "T046",
    "T184",
)
_register("GENE", "T087", "T088", "T028", "T085", "T086")
_register(
    "LIVB",
    "T100",
    "T011",
    "T008",
    "T194",
    "T007",
    "T012",
    "T204",
    "T099",
    "T013",
    "T004",
    "T096",
    "T016",
    "T015",
    "T001",
    "T101",
    "T098",
    "T097",
    "T014",
    "T010",
    "T005",
)
_register("PHEN", "T034", "T038", "T069", "T068", "T034", "T067", "T043", "T201", "T045", "T041")
_register("PHYS", "T043", "T201", "T045", "T041", "T044", "T032", "T040", "T042", "T039")
_register("PROC", "T060", "T065", "T058", "T059", "T063", "T062", "T061")
_register(
    "CONC",
    "T185",
    "T077",
    "T169",
    "T102",
    "T078",
    "T170",
    "T171",
    "T080",
    "T081",
    "T089",
    "T082",
    "T079",
)
_register("OCCU", "T091", "T090")
_register("ORGA", "T093", "T092", "T094", "T095")
_register("GEOG", "T083")
_register("OBJC", "T072", "T167", "T168", "T073")
_register("ACTI", "T052", "T053", "T056", "T051", "T064", "T055", "T066", "T057", "T054")

CLINICAL_TUIS: frozenset[str] = frozenset(
    tui for tui, group in GROUP_BY_TUI.items() if group in CLINICAL_GROUPS
)


#: RRF column names, from MRFILES.RRF. Named explicitly rather than positionally
#: so the queries read as terminology rather than as indices.
MRCONSO_COLUMNS: list[str] = [
    "cui",
    "lat",
    "ts",
    "lui",
    "stt",
    "sui",
    "ispref",
    "aui",
    "saui",
    "scui",
    "sdui",
    "sab",
    "tty",
    "code",
    "str",
    "srl",
    "suppress",
    "cvf",
]
MRSTY_COLUMNS: list[str] = ["cui", "tui", "stn", "sty", "atui", "cvf"]


@dataclass(frozen=True, slots=True)
class UmlsRelease:
    """A local, unpacked UMLS Metathesaurus release."""

    root: Path
    version: str

    @property
    def meta(self) -> Path:
        return self.root / self.version / "META"

    def rrf(self, name: str) -> Path:
        path = self.meta / name
        if not path.exists():
            raise FileNotFoundError(
                f"{name} not found under {self.meta}. RobustEHR needs the "
                f"Metathesaurus RRF files; see data/README.md."
            )
        return path

    @classmethod
    def discover(cls, root: Path) -> UmlsRelease:
        """Find the release directory under ``root`` (e.g. ``2026AA``)."""
        candidates = sorted(
            child.name for child in root.iterdir() if child.is_dir() and (child / "META").is_dir()
        )
        if not candidates:
            raise FileNotFoundError(
                f"no UMLS release directory containing META/ found under {root}"
            )
        return cls(root=root, version=candidates[-1])


def build_clinical_lexicon(
    release: UmlsRelease,
    *,
    con: Any,
    languages: tuple[str, ...] = ("ENG",),
    min_length: int = 3,
    closed_class: frozenset[str] = frozenset(),
) -> dict[str, int]:
    """Derive the single-token clinical vocabulary from a UMLS release.

    Returns counts for the build report. The lexicon itself is written into
    ``con`` as tables so that downstream steps query rather than materialize it.

    Two-character tokens are excluded, and that is a deliberate deferral rather
    than an oversight. Every two-letter string is some element symbol or
    abbreviation in UMLS, so admitting them put ``on`` (3,806 occurrences) and
    ``no`` (3,483) at the top of the ``chemical`` category via nitric oxide.
    Clinically important short forms — mg, po, iv — are real but need the
    abbreviation resolver with abstention, not dictionary lookup, because
    ``no`` is genuinely ambiguous between the word and the compound.

    The extraction is: English, non-suppressible strings from concepts whose
    semantic type falls in a clinical semantic group, restricted to those that
    are a single alphabetic word. Word-level rather than concept-level because
    the question being answered is "is *this token* clinical", which is what a
    character- or word-level perturbation needs to know.
    """
    mrconso = str(release.rrf("MRCONSO.RRF"))
    mrsty = str(release.rrf("MRSTY.RRF"))
    lang_list = ", ".join(f"'{lang}'" for lang in languages)
    tui_list = ", ".join(f"'{tui}'" for tui in sorted(CLINICAL_TUIS))

    con.execute(f"""
        CREATE OR REPLACE TABLE clinical_cui AS
        SELECT DISTINCT cui
        FROM read_csv('{mrsty}', delim='|', header=false, quote='',
                      names={MRSTY_COLUMNS!r}, all_varchar=true)
        WHERE tui IN ({tui_list})
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE clinical_string AS
        SELECT DISTINCT c.cui, c.str
        FROM read_csv('{mrconso}', delim='|', header=false, quote='',
                      names={MRCONSO_COLUMNS!r}, all_varchar=true) c
        JOIN clinical_cui u ON u.cui = c.cui
        WHERE c.lat IN ({lang_list})
          AND c.suppress = 'N'
          AND c.str IS NOT NULL
    """)

    # The token criterion is *single-word concept membership*: the string is a
    # complete concept name in its own right, not merely a word appearing inside
    # one. Splitting multi-word strings into their component tokens was tried
    # first and is far too permissive — it admits "and", "left", "with" and
    # "right", because those words occur inside clinical concept names. Requiring
    # the whole string to be the token is the criterion that actually matches the
    # question being asked of it: is *this word*, standing alone, clinical?
    #
    # A specificity ratio (clinical occurrences over total occurrences) was also
    # tried and rejected: UMLS is overwhelmingly clinical content, so nearly
    # every token scores above 0.9 and the ratio separates nothing.
    exclude = ", ".join(f"'{word}'" for word in sorted(closed_class))
    # Carry the **semantic types**, not just group membership or a clinical flag.
    #
    # "Is this token clinical" is not a well-posed question. What matters is what
    # kind of thing it names — a drug, a diagnosis, a symptom, an anatomical site
    # — and TUI granularity is what answers that. Semantic *Groups* are too
    # coarse: DISO contains both Disease or Syndrome (T047) and Sign or Symptom
    # (T184), so a group-level target cannot tell a diagnosis from a symptom.
    con.execute(f"""
        CREATE OR REPLACE TABLE single_word_clinical AS
        SELECT lower(c.str) AS token,
               string_agg(DISTINCT s.tui, '|' ORDER BY s.tui) AS tuis
        FROM clinical_string c
        JOIN read_csv('{mrsty}', delim='|', header=false, quote='',
                      names={MRSTY_COLUMNS!r}, all_varchar=true) s ON s.cui = c.cui
        WHERE regexp_full_match(c.str, '[A-Za-z]+')
          AND length(c.str) >= {min_length}
          AND lower(c.str) NOT IN ({exclude or "''"})
          AND s.tui IN ({tui_list})
        GROUP BY lower(c.str)
    """)

    return {
        "clinical_cuis": con.execute("SELECT count(*) FROM clinical_cui").fetchone()[0],
        "clinical_strings": con.execute("SELECT count(*) FROM clinical_string").fetchone()[0],
        "clinical_tokens": con.execute("SELECT count(*) FROM single_word_clinical").fetchone()[0],
    }


#: Zipf frequency at or above which a word is treated as ordinary English.
#:
#: Zipf 5.0 is 100 occurrences per million, which is the **~1,100 most frequent
#: English words**. That is the calibration, and it is stated this way because a
#: bare threshold is a magic number while a rank is interpretable.
#:
#: The cut separates a hand-labelled probe set almost perfectly: the most
#: ordinary word kept specific is ``chest`` (4.5), the least ordinary word
#: flagged ambiguous is ``patient`` (4.8). Deliberately not tuned to separate it
#: exactly — 5.0 is the round, defensible number and 4.75 would be overfitting
#: to 27 hand-picked words.
AMBIGUITY_ZIPF = 5.0


def _frequency_source() -> str:
    """Identify the frequency data, so a vocabulary records how it was split."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return f"wordfreq {version('wordfreq')}"
    except PackageNotFoundError:
        return "none"


def _specificity(tokens: list[str]) -> dict[str, str]:
    """Tag each token ``specific`` or ``ambiguous`` by general-English frequency.

    Reusing ``wordfreq`` rather than deriving a frequency list: it is Apache-2.0,
    ships its data offline, and its whole purpose is this question.

    Note what this is *not*. It is not a claim that ambiguous words are
    non-clinical — ``blood`` and ``pain`` land here and are plainly clinical. It
    is a claim that their presence is **weaker evidence** of clinical content
    than ``dyspnea``, because they are also ordinary English. That distinction is
    reported rather than resolved, and resolving it properly needs concept-level
    matching in context, which is what the concept layer adds.

    Without ``wordfreq`` installed every token is tagged ``specific`` and the
    manifest records ``ambiguity_source: none``, so a vocabulary built without it
    is visibly different rather than silently different.
    """
    try:
        from wordfreq import zipf_frequency
    except ImportError:
        return dict.fromkeys(tokens, "specific")
    return {
        token: ("ambiguous" if zipf_frequency(token, "en") >= AMBIGUITY_ZIPF else "specific")
        for token in tokens
    }


def _category_counts(rows: list[tuple[str, str]]) -> dict[str, int]:
    """Vocabulary size per named semantic category, for the build report."""
    from robustehr.categories import load_categories

    categories = load_categories()
    counts = dict.fromkeys(categories, 0)
    for _, tuis in rows:
        present = frozenset(t for t in (tuis or "").split("|") if t)
        for name, category in categories.items():
            if present & category.tuis:
                counts[name] += 1
    return dict(sorted(counts.items()))


def export_lexicon(con: Any, path: Path, release: UmlsRelease) -> dict[str, Any]:
    """Write the derived clinical vocabulary to a local artifact.

    **Not redistributable.** UMLS strings are licensed content, so the artifact
    is built locally from the user's own installation and is gitignored. What
    RobustEHR ships is the builder and the manifest hash, which is enough for a
    reader with the same release to reproduce it bit-for-bit — the same deferred
    materialization the concept lockfiles use.

    Each token is tagged ``specific`` or ``ambiguous``, because membership in the
    terminology is not the same as being clinical evidence. UMLS contains ``one``
    (Finding), ``date`` (Pharmacologic Substance) and ``home`` (Health Care
    Activity), and counting a typo in ``one`` as a hit on clinical content would
    inflate every landing measurement in the package.

    The split is computed here, at build time, so runtime needs neither
    ``wordfreq`` nor any frequency data — consistent with the rule that
    everything licensed or heavy happens once, offline.
    """
    rows = con.execute("SELECT token, tuis FROM single_word_clinical ORDER BY token").fetchall()
    tokens = [row[0] for row in rows]
    tiers = _specificity(tokens)
    body = "\n".join(f"{token}\t{tuis}\t{tiers[token]}" for token, tuis in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")

    ambiguous = sum(1 for tier in tiers.values() if tier == "ambiguous")
    manifest = {
        "umls_release": release.version,
        "semantic_groups": sorted(CLINICAL_GROUPS),
        "semantic_types": len(CLINICAL_TUIS),
        "tokens": len(tokens),
        "tokens_specific": len(tokens) - ambiguous,
        "tokens_ambiguous": ambiguous,
        "ambiguity_zipf": AMBIGUITY_ZIPF,
        "ambiguity_source": _frequency_source(),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "extraction": (
            "English, non-suppressible, single-word strings of concepts whose "
            "semantic type falls in a clinical semantic group"
        ),
        "columns": ["token", "semantic_types", "specificity"],
        "category_counts": _category_counts(rows),
    }
    path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


__all__ = [
    "CLINICAL_GROUPS",
    "CLINICAL_TUIS",
    "GROUP_BY_TUI",
    "SEMANTIC_GROUPS",
    "UmlsRelease",
    "build_clinical_lexicon",
    "export_lexicon",
]
