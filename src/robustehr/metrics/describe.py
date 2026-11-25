"""Table 1: one deterministic characterisation of a clinical-note corpus.

**The gap this closes.** Five commands already measure a corpus — `baseline`
(degradation), `applicability` (unit counts), `concept-profile` (concepts),
`ambiguity` (abbreviations), `concepts classify` (token classes) — and each
emits its own JSON with its own denominators. Nothing produced the single table
a methods section opens with.

**One organisation, and it is the taxonomy's.** Table 1 is keyed by the
structural LEVEL an operator can target, so every unit that can be corrupted has
a measurement beside it and a reader can see which operators reach it. That is
checkable rather than aspirational: `_unmeasured_levels_with_operators` lists
any level with operators and no baseline, and must stay empty.

    document · section · header · sentence · list_item · aligned_block
    space_run · placeholder · span · token · character · assertion

One organisation, so that each fact appears once: a reader who finds two
paths to one number has to work out whether they mean the same thing.

**A concept mention is a SPAN, not a token, and that is its own level.** The
category and phenotype breakdowns live there. Putting them at the token level
made two true numbers look like a contradiction: 3,918 mentions over 12,399
content tokens reads as 32% of the note, and the real answer is neither that nor
anything derivable from it, because mentions overlap and run one to six tokens
long. So `span.token_lengths` is the bridge and `token.concept_covered` is the
question that division was trying to ask — content tokens lying inside at least
one mention, counted once each. On five MIMIC-IV notes that is 0.386.

**A count is not a denominator**, and two levels had to learn it. The `token`
level reports its COMPOSITION — `word_min3` *is* `input.typo`'s eligible set,
`ocr_confusable` *is* `input.ocr_confusion`'s. The `assertion` level reports
CUES per operator, not mentions carrying the attribute: a note may carry 355
negated mentions while `semantic.negation_flip` is eligible on 216 negation
cues, and neither number predicts the other — one cue scopes over several
mentions — so both are reported and labelled. See `_token_composition` and
`_add_assertion_level`.

**Medians with IQR, never means.** Note lengths are right-skewed — a discharge
summary is several times a progress note — so a mean describes a note that does
not exist. Nearest-rank rather than interpolated, because an interpolated
quantile of integer counts is a number no note has.

**Degrades by level, not silently.** Without a UMLS index the concept,
phenotype and assertion fields are absent and `unavailable` says why; every
structural level is unaffected. That is the guarantee `baseline` also carries:
the structural half must be reproducible by a reader without a licence.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from robustehr.document import Document
    from robustehr.metrics.ambiguity import AmbiguityProfile
    from robustehr.metrics.concepts import ConceptProfile
    from robustehr.metrics.spelling import NearMissProfile

#: Concepts per this many content tokens. A note is a few thousand.
DENSITY_BASE = 1000

#: Runs of >= this many horizontal whitespace characters — `render.py::_SPACE_RUN`
#: and `blocks.py::_COLUMN_GAP`, which is what `render.whitespace_collapse` and
#: `render.lab_block_collapse` are dosed over.
#:
#: **Two, not three, and tabs count.** This mirrored `metrics.dqp.WHITESPACE_RUN`
#: (3, spaces only) on the stated grounds that "a baseline that counted them
#: differently from the thing being corrupted would be measuring nothing" — and
#: then counted them differently anyway, because both operators use `[ \t]{2,}`.
#: The baseline under-reported every two-space run and every tab run in the
#: corpus, which is precisely the failure the comment warned about.
#:
#: `dqp.WHITESPACE_RUN` stays at 3 and is right to: it is a *stratifier* asking
#: "does column layout leak into this note's prose", where two spaces is
#: ordinary sentence spacing and three is a table. Different question, different
#: threshold, and they are no longer pretending to be the same one.
WHITESPACE_RUN = 2

#: The taxonomy's structural levels, and which operators act on each. Table 1
#: is organised by this so that **every unit an operator can target has a
#: baseline**. That was not true before: `space_run` carried two operators and
#: appeared nowhere in the table, so a user could corrupt something the
#: characterisation never counted.
#:
#: `character` and `section` have no operator of their own and are included
#: anyway — `character` is the substrate every edit is measured in, and
#: `section` is reachable through `--target section=...`.
LEVEL_OPERATORS: dict[str, tuple[str, ...]] = {
    "document": ("control.identity", "discourse.truncate"),
    "section": ("discourse.section_duplicate",),
    "header": ("render.header_style", "render.header_delete", "render.header_rename"),
    "sentence": ("discourse.sentence_delete",),
    "list_item": ("render.bullet_to_prose",),
    "list_block": ("render.list_to_prose",),
    # Structural breaks between blocks. Reported apart from `space_run` because
    # the two are different substances: a space run is horizontal layout inside
    # a line, a break is the vertical boundary between lines, and the operators
    # that act on them can neither reach nor substitute for each other.
    "break": ("render.break_removal",),
    "word_space": ("render.space_delete",),
    "numeric_value": ("lexical.numeral_to_word",),
    "medication": ("lexical.medication_rename",),
    "aligned_block": (),
    "space_run": ("render.whitespace_collapse", "render.lab_block_collapse"),
    "placeholder": ("render.deid_restyle",),
    # A concept mention IS a span, and a span is not a token: `acute on chronic
    # systolic heart failure` is one mention over six tokens. Reporting concepts
    # at the token level made the two look contradictory — 3,918 mentions over
    # 12,399 content tokens reads as 32% of the note, which is wrong in both
    # directions.
    #
    # No operator of its own, and reachable anyway: `--target cat=medication`
    # and `--target pheno=hfpef` both select spans, and every SEMANTIC operator
    # qualifies them. So it is a level in the same sense `section` is.
    "span": (),
    # `word` and `token` were two levels and are now one. Neither carried any
    # operator's actual denominator — the table said `token 6134` and
    # `word 2530` while typo was eligible on 1,796, ocr_confusion on 2,301 and
    # phonetic_confusion on 55. Two numbers, none of them the answer.
    #
    # The taxonomy agreed: all four character-mutating operators are
    # `layer=char`, three of the four use `UnitKind.WORD`, and `token` existed
    # for one operator whose unit is its own bespoke set. So one level, and it
    # reports COMPOSITION rather than a count — see `_token_composition`.
    "token": (
        "input.typo",
        "control.char_shuffle",
        "input.phonetic_confusion",
    ),
    "assertion": (
        "semantic.negation_flip",
        "semantic.uncertainty_flip",
        "semantic.temporality_shift",
        "semantic.experiencer_shift",
    ),
    "character": (),
}

#: `render.list_to_prose`'s floor, mirrored from the operator for the same
#: reason the length constants below are: a baseline that used a different one
#: would report a denominator the operator does not have.
LIST_JOIN_MIN_ITEMS = 2

#: A section header is "substantive" only if it has this many characters of body
#: under it.
#:
#: A discharge summary is full of headers with nothing beneath them — a
#: `Facility:` whose value is a de-identification mask, a `Discharge
#: Disposition:` holding one word, a heading followed immediately by the next
#: heading. Those are present to a parser and absent to a reader, and corrupting
#: one changes nothing anybody could notice. Counting them inflates every header
#: denominator with units whose corruption is unobservable, which makes a
#: dose-response curve flatter than the operator actually is.
#:
#: 60 characters is roughly one line of clinical prose. It is a convention, not
#: a measurement, so it is named here and reported beside the unfiltered count
#: rather than applied silently.
SUBSTANTIVE_BODY_CHARS = 60

#: Minimum lengths each operator requires, mirrored here so the composition row
#: PREDICTS its denominator rather than merely sitting near it.
#:
#: They differ, and assuming otherwise was wrong: a first version used one
#: constant and reported 1,807 where `char_shuffle` was eligible on 1,364.
TYPO_MIN_LENGTH = 3
SHUFFLE_MIN_LENGTH = 4
OCR_MIN_LENGTH = 2


def quantiles(values: Sequence[float]) -> dict[str, float | None]:
    """p25 / median / p75 over notes, plus the extremes.

    Nearest-rank rather than interpolated: an interpolated quantile of integer
    counts is a number no note has, and this table is read as "a typical note
    looks like this". Nearest-rank returns an element of the input, so the ratio
    fields (`clinical_share` and the other per-note shares) get a real observed
    value too rather than a synthesised one.
    """
    if not values:
        return {"p25": None, "median": None, "p75": None, "min": None, "max": None}
    ordered = sorted(values)
    n = len(ordered)
    return {
        "p25": ordered[n // 4],
        "median": ordered[n // 2],
        "p75": ordered[(3 * n) // 4],
        "min": ordered[0],
        "max": ordered[-1],
    }


@dataclass(frozen=True, slots=True)
class NoteRow:
    """Everything measured about one note, before aggregation."""

    note_uid: str
    units: dict[str, int]
    lexical: dict[str, int]
    levels: dict[str, dict[str, Any]] = field(default_factory=dict)
    sections: dict[str, int] = field(default_factory=dict)
    cues: dict[str, int] = field(default_factory=dict)
    concepts: ConceptProfile | None = None
    ambiguity: AmbiguityProfile | None = None
    near_miss: NearMissProfile | None = None
    deid_scheme: str = "none"
    wrap_width: int = 0
    header_styles: int = 0

    def to_row(self) -> dict[str, Any]:
        """This note's own numbers, in the same shape the corpus table uses.

        Not a second measurement — the same per-level dicts the aggregate is
        built from, before `quantiles` collapses them. A reader who wants to
        know which note carries the p75 header count can find it here, and the
        totals must reconcile by construction rather than by coincidence.

        `sections_present` is a sorted list rather than the length map: the
        aggregate needs body lengths to take a median, and a per-note row needs
        only to say which sections this note has.
        """
        row: dict[str, Any] = {
            "note_uid": self.note_uid,
            "by_level": {level: dict(fields) for level, fields in sorted(self.levels.items())},
            "sections_present": sorted(self.sections),
            "deid_scheme": self.deid_scheme,
            "wrap_width": self.wrap_width,
            "header_styles": self.header_styles,
        }
        token = row["by_level"].setdefault("token", {})
        for name, count in sorted(self.lexical.items()):
            token[f"lex_{name}"] = count
        if self.cues:
            row["by_level"].setdefault("assertion", {})["cues"] = dict(sorted(self.cues.items()))
        if self.concepts is not None:
            token["concept_covered"] = self.concepts.concept_tokens
            token["concept_covered_share_of_content"] = self.concepts.concept_token_share
            span = row["by_level"].setdefault("span", {})
            span["n"] = self.concepts.concepts
            span["distinct_cuis"] = self.concepts.distinct_cuis
            span["by_category"] = dict(sorted(self.concepts.by_category.items()))
            span["token_lengths"] = dict(sorted(self.concepts.span_token_lengths.items()))
        if self.ambiguity is not None:
            token["abbreviations"] = self.ambiguity.abbreviations
            token["abbreviations_ambiguous"] = self.ambiguity.ambiguous
            token["abbreviations_highly_ambiguous"] = self.ambiguity.highly_ambiguous
            token["abbreviation_sense_bands"] = dict(sorted(self.ambiguity.sense_bands.items()))
        if self.near_miss is not None:
            token["near_miss_candidates"] = self.near_miss.candidates
            token["near_miss_edit1"] = self.near_miss.near_miss
        return row


def load_group_map(name: str) -> dict[str, list[str]]:
    """Label-set column -> declared phenotypes.

    `name` is either a label set in the packaged `label_groups.yaml`, or a path
    to a YAML file of the same shape. Your annotation project is not going to be
    in this package, so the path form is the one most callers want; the packaged
    sets are worked examples that happen to be the ones this repository measures.

    A file containing exactly one label set is used without naming it. With more
    than one, append `#setname`.

    Raises `KeyError` on an unknown label set rather than falling back to
    name-matching: a silent fallback would point the wrong annotator at a group
    and produce a table that looks right.
    """
    import yaml

    from robustehr.resources import load_yaml

    spec, _, wanted = name.partition("#")
    path = Path(spec)
    if path.suffix in {".yaml", ".yml"} or path.exists():
        if not path.exists():
            raise KeyError(f"no such group map file: {spec}")
        declared = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not wanted:
            if len(declared) != 1:
                raise KeyError(
                    f"{spec} declares {sorted(declared)}; name one with "
                    f"'{spec}#<set>' rather than guessing"
                )
            wanted = next(iter(declared))
    else:
        declared = load_yaml("label_groups.yaml")
        wanted = spec
    if wanted not in declared:
        raise KeyError(f"unknown label set {wanted!r}; known: {sorted(declared)}")
    return {k: list(v or []) for k, v in declared[wanted]["columns"].items()}


def read_groups(path: Path, group_map: dict[str, list[str]] | None) -> dict[str, list[str]]:
    """Group name -> note uids, from a wide CSV of binary label columns.

    Groups OVERLAP by construction — a note positive for hypertension is often
    positive for depression too — so this is a set of overlapping cohorts, not a
    partition, and the group totals will exceed the corpus size. That is a
    property of the label set and is reported rather than resolved.

    A value counts as positive when it is not empty, `0` or `0.0`. MIPA writes
    both `0` and `0.0` in the same file, and treating the float as truthy would
    have made every note positive for every phenotype.
    """
    import csv

    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    skip = {"", "note_id", "subject_id", "hadm_id"}
    columns = [
        c
        for c in rows[0]
        if c not in skip and (group_map is None or c in group_map) and not c.startswith("_")
    ]
    if group_map is not None:
        columns = [c for c in columns if c in group_map]
    return {
        column: [r["note_id"] for r in rows if r.get(column) not in ("", "0", "0.0", None)]
        for column in columns
    }


def canonical_sections() -> dict[str, str]:
    """Every canonical section id the header lexicon declares, and its kind.

    58 of them, each named: a count of sections alone cannot answer the
    question a reader actually has — does this corpus carry a past medical
    history and a discharge medication list?

    The kind matters for reading the table: 45 are clinical content, 8 are
    metadata (`name`, `unit_number`, `admission_date`) and 4 are prescription
    boilerplate. A corpus missing `past_medical_history` is a different fact
    from one missing `rx_refills`.
    """
    from robustehr.resources import load_yaml

    declared = load_yaml("headers.yaml")["canonical"]
    return {name: (entry.get("kind") or "clinical") for name, entry in sorted(declared.items())}


def _section_presence(doc: Document) -> dict[str, int]:
    """Canonical section id -> body length in characters, for this note.

    Body length rather than a boolean: a `past_medical_history` header with an
    empty body is present to a parser and absent to a reader, and an operator
    targeting `section=past_medical_history` would find nothing in it.
    """
    found: dict[str, int] = {}
    for section in doc.sections:
        if section.canonical_id:
            # A section can appear twice (a note with two `hospital_course`
            # blocks); keep the longest, since that is the one a target reaches.
            body = len(section.body)
            found[section.canonical_id] = max(found.get(section.canonical_id, 0), body)
    return found


#: Which ConText cue category each SEMANTIC operator rewrites, and therefore
#: what its eligible set actually is. Mirrors `ops.semantic._CueFlip.categories`.
#:
#: This exists because the assertion level had the same fault the token level
#: had: it reported `negated 355`, which is a count of *mentions carrying the
#: attribute*, while `semantic.negation_flip` is eligible on *negation cues*.
#: Those are different populations and neither predicts the other — one cue can
#: scope over several mentions, and a mention can be negated by a cue in a
#: different clause.
CUE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "semantic.negation_flip": ("NEGATED_EXISTENCE",),
    "semantic.uncertainty_flip": ("POSSIBLE_EXISTENCE", "HYPOTHETICAL"),
    "semantic.temporality_shift": ("HISTORICAL",),
    "semantic.experiencer_shift": ("FAMILY",),
}

#: Which attribute each operator's flip is *reported as* in the mention counts.
CUE_ATTRIBUTE: dict[str, str] = {
    "semantic.negation_flip": "negated",
    "semantic.uncertainty_flip": "uncertain",
    "semantic.temporality_shift": "historical",
    "semantic.experiencer_shift": "family",
}


def _assertion_cues(doc: Document) -> dict[str, int]:
    """ConText cues by category — each SEMANTIC operator's eligible set.

    Needs the `clinical` extra and nothing else. Deliberately NOT the UMLS
    index: a negation cue is a property of the prose, so `negation_flip`'s
    denominator is reproducible by a reader with no terminology licence, and
    reporting it only alongside the concept layer would hide that.
    """
    try:
        from robustehr.concepts.context import cues_in
    except ImportError:  # pragma: no cover - clinical extra not installed
        return {}
    boundaries = tuple(s.span.start for s in doc.sentences.sentences)
    counts: Counter[str] = Counter()
    for cue in cues_in(doc.text, boundaries=boundaries):
        counts[cue.category] += 1
    return dict(counts)


def _token_composition(doc: Document) -> dict[str, int]:
    """The one `token` row, broken down so each operator's denominator is derivable.

    **A count is not a denominator, and that was the bug.** The table reported
    `token 6134` and `word 2530` while the operators that act on this level were
    eligible on 1,796 (`input.typo`), 2,301 (`input.ocr_confusion`) and 55
    (`input.phonetic_confusion`). A reader could not get from either number to
    what a severity of 0.30 would touch, which is the whole reason a baseline
    reports denominators.

    So the fields below are chosen to *reconstruct* those counts rather than to
    describe tokens in the abstract:

    * ``word_min3`` is `input.typo`; ``word_min4`` is `control.char_shuffle`.
      They are separate fields because the operators require different lengths,
      which a single constant got wrong by 443 units;
    * ``ocr_confusable`` counts *tokens* holding at least one confusable glyph.
      It is deliberately larger than the typo fields — it reaches digits and
      two-character tokens the typo operators cannot. The 544-token difference
      on one MIMIC note is `to`, `up`, `no`, `91`, `Q6H`, `PO`: short words,
      values and dosing abbreviations, which is the span class the
      digit-confusion table exists for. **It is no longer
      `input.ocr_confusion`'s denominator** — that operator is dosed per
      confusable *character* and its baseline is `character.ocr_confusable`.
      This field is kept because it answers a different and still useful
      question: how much of the note's vocabulary is exposed at all;
    * ``short_form`` is a *shape* count and is free. It is not the abbreviation
      measurement — that needs the terminology and lands beside the concept
      fields, because what matters clinically is how many resolve to more than
      one concept.

    `input.phonetic_confusion` is not derivable here: its eligibility is
    "a morpheme rule fires", which depends on the rule file and a vocabulary
    gate, not on token shape. Reporting a number that looked like its
    denominator would be worse than omitting one.
    """
    from robustehr.ocr import load_table
    from robustehr.segment.tokens import TokenKind

    glyphs = load_table().glyphs

    counts: dict[str, int] = dict.fromkeys(
        (
            "n",
            "content",
            "word",
            "word_min3",
            "word_min4",
            "alphanumeric",
            "numeric",
            "short_form",
            "punctuation",
            "ocr_confusable",
        ),
        0,
    )
    counts["n"] = len(doc.tokens)
    counts["content"] = len(doc.tokens.content())
    for token in doc.tokens:
        word = doc.text[token.span.start : token.span.end]
        if not word:
            continue
        # `TokenKind.WORD`, not "contains a letter". The typo operators filter on
        # the kind, so a mixed token like `Q6H` or `5mg` is NOT one of their
        # units — counting it as alphabetic overstated their denominator by 11
        # on one note, and would have overstated it silently on every other.
        if token.kind is TokenKind.WORD:
            counts["word"] += 1
            if len(word) >= TYPO_MIN_LENGTH:
                counts["word_min3"] += 1
            if len(word) >= SHUFFLE_MIN_LENGTH:
                counts["word_min4"] += 1
            if word.isupper() and 2 <= len(word) <= 5:
                counts["short_form"] += 1
        elif any(c.isalpha() for c in word) and any(c.isdigit() for c in word):
            counts["alphanumeric"] += 1
        elif any(c.isdigit() for c in word):
            counts["numeric"] += 1
        else:
            counts["punctuation"] += 1
        if len(word) >= OCR_MIN_LENGTH and any(c in glyphs for c in word):
            counts["ocr_confusable"] += 1
    return counts


def _ocr_confusable_chars(doc: Document) -> int:
    """`input.ocr_confusion`'s denominator: confusable character *positions*.

    Counted here from the same table the operator reads
    (:mod:`robustehr.ocr`), against the same ``MIN_LENGTH`` gate, so the
    baseline predicts the eligible count rather than merely resembling it.
    """
    from robustehr.ocr import load_table

    table = load_table()
    return sum(
        len(table.confusable_positions(doc.text[t.span.start : t.span.end]))
        for t in doc.tokens
        if len(t.span) >= OCR_MIN_LENGTH
    )


def _header_counts(doc: Document, canonical: int) -> dict[str, int]:
    """The header level, reporting what the header operators are actually dosed on.

    Three successive narrowings, each because the wider number is the wrong
    denominator for something:

    1. **heading-shaped lines** — everything the detector found, including exam
       subsections (`HEENT:`) and pharmacy boilerplate (`Disp:` alone appears in
       24.9% of notes). Descriptive, and nobody's denominator.
    2. **section headers** — SECTION and METADATA kinds, which is what all three
       header operators run on.
    3. **substantive** — of those, the ones with at least
       :data:`SUBSTANTIVE_BODY_CHARS` of body beneath them. A header with an
       empty or one-word body is present to a parser and absent to a reader, so
       deleting it is a corruption nobody can observe.

    Each is reported, so a reader can see the two gaps rather than having to
    trust one filtered number.
    """
    from robustehr.segment.headers import HeaderConfidence, load_lexicon

    lexicon = load_lexicon()
    section_headers = doc.section_headers()
    substantive_lines = {
        s.header.line_idx
        for s in doc.sections
        if s.header is not None and len(s.body) >= SUBSTANTIVE_BODY_CHARS
    }
    return {
        # `n` IS the section headers, not every heading-shaped line. All three
        # header operators run on this population, so it is the number a reader
        # multiplies by a severity. The wider count is kept as `heading_lines`
        # for transparency rather than promoted to the headline: it includes
        # exam subsections (`HEENT:`) and pharmacy boilerplate (`Disp:` appears
        # in a quarter of notes), which are heading-shaped and are not note
        # structure. Reporting those as "headers" made "delete 30% of headers"
        # mean something different in every note.
        "n": len(section_headers),
        "heading_lines": len(doc.headers),
        "canonical": sum(1 for h in section_headers if h.is_canonical),
        "guessed": sum(1 for h in section_headers if not h.is_canonical),
        "distinct_grammars": len({h.grammar for h in section_headers}),
        # `render.header_delete` — standalone only; deleting an inline
        # `Service: MEDICINE` would take the value with it.
        "standalone": sum(1 for h in section_headers if h.value is None or h.value.is_empty),
        "inline": sum(1 for h in section_headers if h.value is not None and not h.value.is_empty),
        # `render.header_rename` — needs a canonical id with another known name.
        # Not a subset of `standalone`: an inline header can be renamed but not
        # deleted, which is why these are two rows rather than a nested chain.
        "renameable": sum(
            1
            for h in section_headers
            if h.confidence is HeaderConfidence.LEXICON
            and lexicon.aliases_for(h.canonical_id, excluding=h.raw_name)
        ),
        # Headers a reader would actually notice losing. Reported rather than
        # enforced: no operator filters on it, so a dose stays a fraction of
        # `n`, and this says how much of `n` was worth corrupting.
        "substantive": sum(1 for h in section_headers if h.line_idx in substantive_lines),
        "min_body_chars": SUBSTANTIVE_BODY_CHARS,
        # Excluded from every header operator, reported so the gap between
        # `heading_lines` and `n` is accounted for rather than unexplained.
        "excluded_non_structural": len(doc.headers) - len(section_headers),
    }


def _word_space_counts(doc: Document) -> dict[str, int]:
    """`render.space_delete`'s denominator, and the two things it is not.

    A note's spaces divide three ways and only one of them is a word gap:
    single spaces between content tokens (this operator), runs of two or more
    holding a column apart (`render.whitespace_collapse`), and the newlines
    separating blocks (`render.break_removal`). Reporting them together would
    let one severity look like it covered all three.
    """
    from robustehr.segment.tokens import TokenKind

    tokens = doc.tokens.tokens
    prose = [s.span for s in doc.sentences.prose()]
    single = 0
    between_content = 0
    eligible = 0
    for idx in range(1, len(tokens) - 1):
        token = tokens[idx]
        if token.kind is not TokenKind.SPACE or len(token.span) != 1:
            continue
        single += 1
        if not (tokens[idx - 1].is_content and tokens[idx + 1].is_content):
            continue
        between_content += 1
        if any(s.contains(token.span) for s in prose):
            eligible += 1
    return {
        "n": eligible,
        "single_spaces": single,
        "between_content_tokens": between_content,
        # The gap between the last two is the layout share: spaces that separate
        # two content tokens but sit in a lab row or a list item rather than in
        # prose. Corrupting those is a different operator's business.
        "in_layout": between_content - eligible,
    }


def _numeric_counts(doc: Document) -> dict[str, int]:
    """Numeric expressions: how many, of what shape, and how many are dosages.

    `lexical.numeral_to_word` is dosed on the integers it can spell exactly, so
    the split is not decoration. A decimal (`4.46`) and a unit-bearing value
    (`650 mg`) are both numeric expressions and neither is eligible: the first
    has no unambiguous written form, the second is withheld as a `DOSAGE`
    because spelling out a drug dose is a materially more dangerous edit than
    spelling out an ejection fraction.
    """
    from robustehr.numerals import is_spellable
    from robustehr.protect.registry import protect_document
    from robustehr.segment.tokens import TokenKind
    from robustehr.types import ProtectionClass

    index = protect_document(doc)
    dosage_spans = [p.span for p in index.of_class(ProtectionClass.DOSAGE)]
    numbers = [t for t in doc.tokens if t.kind is TokenKind.NUMBER]
    integers = [t for t in numbers if "." not in doc.text[t.span.start : t.span.end]]
    spellable = [t for t in integers if is_spellable(doc.text[t.span.start : t.span.end])]
    with_unit = [t for t in spellable if any(t.span.overlaps(s) for s in dosage_spans)]
    return {
        # `bare` is the operator's default mode, so it is `n` — the number a
        # reader reaching for "30% of numerals" will multiply.
        "n": len(spellable) - len(with_unit),
        "spellable": len(spellable),
        "total": len(numbers),
        "integer": len(integers),
        "decimal": len(numbers) - len(integers),
        "unit_bearing": len(with_unit),
    }


def level_characteristics(
    doc: Document, *, wrap_width: int | None = None
) -> dict[str, dict[str, Any]]:
    """Per-level counts AND the characteristics that make each level distinct.

    A count alone does not characterise a level. "41 headers" says nothing
    about whether they are canonical or guessed, and an operator that restyles
    headers behaves entirely differently on the two. Each level therefore
    carries the property a reader needs in order to predict what corrupting it
    would do.
    """
    import re

    from robustehr.metrics.medications import profile_medications
    from robustehr.segment.breaks import break_counts, detect_breaks

    text = doc.text
    runs = re.findall(rf"[ \t]{{{WHITESPACE_RUN},}}", text)
    canonical = sum(1 for h in doc.section_headers() if h.is_canonical)
    return {
        "document": {
            "n": 1,
            # No `chars` here. The character level owns that count, and carrying
            # it in both places is the duplication this reorganisation exists to
            # remove — a reader who finds two paths to one number has to work
            # out whether they mean the same thing.
            "lines": len(doc.lines),
            "hard_wrapped": int(bool(getattr(doc, "wrap_width", 0))),
        },
        # Lexical classes are NOT emitted here. `assemble` emits them as
        # `lex_*` with a share of content tokens; carrying them twice put the
        # same 1,107 under `class_out_of_vocabulary` and `lex_out_of_vocabulary`.
        "token": _token_composition(doc),
        "character": {
            "n": len(text),
            "alpha": sum(1 for c in text if c.isalpha()),
            "digit": sum(1 for c in text if c.isdigit()),
            "whitespace": sum(1 for c in text if c.isspace()),
            "punctuation": sum(1 for c in text if not c.isalnum() and not c.isspace()),
            "non_ascii": sum(1 for c in text if ord(c) > 127),
            # `input.ocr_confusion`'s denominator. It lives here rather than
            # under `token` because the operator is dosed per confusable
            # character position — the character-error-rate convention — not per
            # token holding one. `token.ocr_confusable` still reports the token
            # count, which answers the different question of how much of the
            # vocabulary is exposed.
            "ocr_confusable": _ocr_confusable_chars(doc),
        },
        "space_run": {
            # The level two RENDER operators target.
            "n": len(runs),
            "chars_in_runs": sum(len(r) for r in runs),
            "longest": max((len(r) for r in runs), default=0),
        },
        "sentence": {
            "n": len(doc.sentences),
            # Layout lines are not prose. An operator deleting a "sentence"
            # that is really a lab row does something different, so the split
            # belongs in the baseline rather than being discovered afterwards.
            "prose": len(doc.sentences.prose()),
            "layout": len(doc.sentences) - len(doc.sentences.prose()),
        },
        "list_item": {"n": sum(len(b.items) for b in doc.lists), "blocks": len(doc.lists)},
        "list_block": {
            "n": len(doc.lists),
            # `render.list_to_prose`'s denominator: a one-item "list" is already
            # prose and joining it would only strip its marker, which is
            # `render.bullet_to_prose`'s job at the item level.
            "multi_item": sum(1 for b in doc.lists if len(b.items) >= LIST_JOIN_MIN_ITEMS),
            "distinct_styles": len({b.style for b in doc.lists}),
        },
        # Re-detected when a width is pinned. `wrap_width` is the p90 of the
        # note's OWN line lengths, so a corruption that joins lines raises it —
        # and a wider margin makes `wraps_into_next` accept fewer lines as
        # hard-wrap continuations, reclassifying genuine continuations as
        # breaks. Measured: removing 30% of breaks reported +46% MORE breaks,
        # because the instrument moved with the corruption. Pinning the clean
        # note's width makes the two measurements comparable, and the same
        # operator then reports -27%, which is the real effect.
        "break": break_counts(
            doc.breaks
            if wrap_width is None
            else detect_breaks(
                text, doc.lines, lists=doc.lists, aligned=doc.aligned, width=wrap_width
            )
        ),
        "word_space": _word_space_counts(doc),
        "numeric_value": _numeric_counts(doc),
        # Dictionary-only here on purpose: `level_characteristics` is the half
        # of Table 1 that needs no terminology, and a reader without a UMLS
        # licence must still get every structural denominator. `assemble` adds
        # the concept-anchored reading when a matcher has run, and
        # `concept_measured` says which one a row is.
        "medication": profile_medications(doc, keep_surfaces=False).as_row(),
        "header": _header_counts(doc, canonical),
        "section": {
            "n": len(doc.sections),
            "canonical": sum(1 for s in doc.sections if s.is_canonical),
            "distinct_canonical_ids": len({s.canonical_id for s in doc.sections if s.canonical_id}),
            # `discourse.section_duplicate`'s denominator. Differs from `n` only
            # for a degenerate empty section, but the operator filters on it and
            # a baseline that did not would be off by one wherever it happens.
            "duplicable": sum(1 for s in doc.sections if not s.full.is_empty),
        },
        "placeholder": {
            "n": doc.deid.count,
            "dividers": len(doc.deid.dividers),
            "scheme": doc.deid.scheme.value,
            "per_1k_chars": round(DENSITY_BASE * doc.deid.count / max(len(text), 1)),
        },
        "aligned_block": {
            "n": len(doc.aligned),
            "lines": sum(len(b.lines) for b in doc.aligned),
        },
    }


def _clinical_content(doc: Document) -> dict[str, Any]:
    """How much of this note is clinical content, by measured salience.

    The level a targeted experiment is judged on. Without it a Table 1 says how
    many tokens a note has and a delta says how many changed, and neither says
    whether what changed was clinical — which for `ClinicalSalience`-targeted
    corruption is the entire claim.

    "Clinical" here is the same evidence the targeting rule uses: the rate at
    which a token falls inside a span a clinician adjudicated as a clinical
    concept, measured on MIMIC-IV discharge summaries, plus the curated drug
    vocabulary that covers what the benchmark under-annotates. Reusing it means
    the table answers *did the rule do what it claims* rather than introducing a
    second, unvalidated notion of clinical that could agree with the rule by
    construction or disagree with it for no stated reason.

    `unmeasured` is its own bucket rather than being folded into either side. It
    is mostly rare clinical terms and de-identification artifacts, and silently
    assigning it would flatter whichever side received it.

    See `validation/protocol.md` §9 for the measurement and its limits —
    corpus-bound, token-level, and blind to context.
    """
    from robustehr import salience
    from robustehr.drugs import load_synonyms

    table = salience.table()
    threshold = salience.DEFAULT_THRESHOLD
    syn = load_synonyms()

    counts: Counter[str] = Counter()
    for token in doc.tokens.content():
        word = doc.text[token.span.start : token.span.end]
        if not any(c.isalpha() for c in word):
            continue
        lower = word.lower()
        bare = lower.rstrip("-")
        # Drug vocabulary is an OR, not a fallback. `ClinicalSalience` accepts a
        # span if salience clears the threshold *or* a drug matches, so a
        # classifier that only consults the vocabulary for tokens absent from
        # the lexicon disagrees with the rule it is meant to audit — and
        # disagrees precisely on medications, which SNOMED EL under-annotates
        # (27.2% of mentions) and therefore scores low rather than not at all:
        # `metoprolol` sits at 0.004, `acetaminophen` at 0.011. Under `elif`
        # those were counted as non-clinical, understating clinical content in
        # every table and mislabelling the drugs the targeted arm went after.
        is_drug = bare in syn.to_generic or bare in syn.to_brand
        if lower in table:
            clinical = table[lower] >= threshold or is_drug
            counts["clinical" if clinical else "non_clinical"] += 1
        elif is_drug:
            counts["clinical"] += 1
        else:
            counts["unmeasured"] += 1

    total = sum(counts.values())
    return {
        "n": total,
        "clinical": counts["clinical"],
        "non_clinical": counts["non_clinical"],
        "unmeasured": counts["unmeasured"],
        # Share of the *measured* tokens, so the unmeasured bucket cannot
        # deflate the headline number without being visible in its own row.
        "clinical_share": (
            counts["clinical"] / (counts["clinical"] + counts["non_clinical"])
            if counts["clinical"] + counts["non_clinical"]
            else 0.0
        ),
    }


def measure_note(  # noqa: PLR0917 - one argument per optional measurement layer
    doc: Document,
    lexicon: Any,
    profile: ConceptProfile | None = None,
    ambiguity: AmbiguityProfile | None = None,
    near_miss: NearMissProfile | None = None,
    mentions: Any = None,
    wrap_width: int | None = None,
) -> NoteRow:
    """One note's row. Terminology is optional and its absence is not an error.

    ``mentions`` upgrades the ``medication`` level from the dictionary-only
    reading :func:`level_characteristics` can produce without a licence to the
    concept-anchored one. **Both readings must never appear in one table.**
    Without this the level reported dictionary hits (46 on one MIMIC note) while
    ``span.by_category.medication`` reported matcher mentions (129), and nothing
    in the output reconciled them — the exact "two paths to one number" failure
    this module's docstring exists to prevent.
    """
    from robustehr.lexical import classify_lexical

    counts: Counter[str] = Counter()
    for token in doc.tokens.content():
        word = doc.text[token.span.start : token.span.end]
        if not any(c.isalpha() for c in word):
            counts["numeric_or_symbol"] += 1
            continue
        counts[classify_lexical(word).value] += 1
        if word.isupper() and 2 <= len(word) <= 5:
            # Upper-case short forms: the abbreviation load a reader needs
            # before trusting any concept count, since an unexpanded
            # abbreviation is a mention the matcher never sees.
            counts["upper_short_form"] += 1

    quality = None
    try:
        from robustehr.metrics.dqp import profile as dqp_profile

        quality = dqp_profile(doc, lexicon)
    except Exception:  # pragma: no cover - dqp needs a lexicon artifact
        quality = None

    levels = level_characteristics(doc, wrap_width=wrap_width)
    levels["clinical_content"] = _clinical_content(doc)
    if mentions is not None:
        from robustehr.metrics.medications import profile_medications

        levels["medication"] = profile_medications(doc, mentions, keep_surfaces=False).as_row()

    return NoteRow(
        note_uid=doc.uid,
        units=doc.unit_counts(),
        levels=levels,
        sections=_section_presence(doc),
        cues=_assertion_cues(doc),
        lexical=dict(counts) | ({"unrecognized": quality.unrecognized} if quality else {}),
        concepts=profile,
        ambiguity=ambiguity,
        near_miss=near_miss,
        deid_scheme=doc.deid.scheme.value if hasattr(doc.deid, "scheme") else "none",
        wrap_width=quality.wrap_width if quality else 0,
        header_styles=quality.header_styles if quality else 0,
    )


@dataclass(frozen=True, slots=True)
class Table1:
    """The assembled characterisation. Blocks are independently nullable."""

    notes: int
    levels: dict[str, Any]
    unavailable: dict[str, str] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "notes": self.notes,
            "by_level": self.levels,
            "unavailable": self.unavailable,
        }


def _unit(rows: list[NoteRow], key: str) -> dict[str, Any]:
    values = [r.units.get(key, 0) for r in rows]
    return {"total": sum(values), **quantiles(values)}


def by_level(rows: list[NoteRow]) -> dict[str, Any]:
    """Aggregate the per-level characteristics, and name each level's operators.

    Organising Table 1 by the taxonomy's own levels is what makes it auditable:
    a reader can check that every unit an operator can target has a baseline
    beside it, rather than trusting that the two lists happen to line up.
    """
    out: dict[str, Any] = {}
    keys = sorted({k for r in rows for k in r.levels})
    for level in keys:
        fields = sorted({f for r in rows for f in r.levels.get(level, {})})
        block: dict[str, Any] = {"operators": list(LEVEL_OPERATORS.get(level, ()))}
        for f in fields:
            values = [r.levels.get(level, {}).get(f) for r in rows]
            # `bool` is an `int` in Python, and a flag is a category, not a
            # quantity — summing it would report "how many notes were true"
            # under a heading that reads like a token count.
            numeric = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
            if numeric and len(numeric) == len(values):
                block[f] = quantiles(numeric)
                if all(isinstance(v, int) for v in values):
                    # Counts have a corpus total; ratios do not. Summing 1,388
                    # per-note shares yields a number with no referent, so a
                    # float field gets its distribution and no `total` — which
                    # is also what stops it falling through to the categorical
                    # branch below and becoming a 1,388-key histogram of
                    # stringified floats, as `clinical_share` did.
                    block[f] = {"total": sum(values), **block[f]}
            else:
                counts: Counter[str] = Counter(str(v) for v in values if v is not None)
                block[f] = dict(sorted(counts.items()))
        out[level] = block
    # A level with operators and no baseline is the failure this block exists
    # to make visible; `space_run` was exactly that before it was measured.
    #
    # `assertion` is excluded when it is absent, because it needs the concept
    # layer and its absence is already reported in `unavailable` with a reason.
    # "unmeasured because a dependency is missing" and "unmeasured because
    # nobody wrote it" are different facts, and listing the first here would
    # make the field noisy in exactly the configuration — no UMLS licence —
    # where a reader most needs it to mean something.
    out["_unmeasured_levels_with_operators"] = sorted(
        level
        for level, ops in LEVEL_OPERATORS.items()
        if ops and level not in keys and level != "assertion"
    )
    return out


def _add_abbreviation_load(token: dict[str, Any], profiles: list[AmbiguityProfile]) -> None:
    """Abbreviation load, at the token level where the abbreviations are.

    **Why this is not `short_form`.** The composition already carries
    `short_form` — upper-case, 2-5 characters — and that is a *shape* count,
    free of any terminology. This is a *terminology* measurement of the same
    region of the note: of the abbreviation-shaped tokens, how many resolve to
    more than one concept as written, and so force a sense choice on every
    downstream reader.

    The two populations are deliberately different and neither contains the
    other. `is_abbreviation_shaped` admits lower-case forms absent from English
    (`bibasilar`, `nkda`) and mixed case (`HFrEF`), which `short_form` misses;
    `short_form` admits six-character all-capitals headings that the English
    exclusion and the three-character capitals bound reject. Reporting the
    overlap would suggest one is a subset of the other.

    It lands beside the concept counts rather than in its own command because
    an unexpanded ambiguous abbreviation is a mention the matcher never sees —
    it is a ceiling on `concept_matched`, not an independent curiosity.
    """
    if not profiles:
        return
    from robustehr.metrics.ambiguity import SENSE_BANDS

    abbreviations = [p.abbreviations for p in profiles]
    total = sum(abbreviations)
    content = sum(p.content_tokens for p in profiles)
    outcomes: Counter[str] = Counter()
    bands: Counter[str] = Counter()
    for p in profiles:
        outcomes.update(p.counts)
        bands.update(p.sense_bands)
    token["abbreviations"] = {
        "total": total,
        # Two denominators, because two different questions get asked of this
        # number. Share of content tokens says how much of the note is
        # shorthand; share of abbreviations (below) says how much of the
        # shorthand is a problem. Reporting one and calling it the other is how
        # a 0.46 gets quoted as "46% of the note is ambiguous".
        "share_of_content": round(total / content, 4) if content else None,
        **quantiles(abbreviations),
    }
    for name, values in (
        ("abbreviations_ambiguous", [p.ambiguous for p in profiles]),
        ("abbreviations_highly_ambiguous", [p.highly_ambiguous for p in profiles]),
    ):
        token[name] = {
            "total": sum(values),
            "share_of_abbreviations": round(sum(values) / total, 4) if total else None,
            "share_of_content": round(sum(values) / content, 4) if content else None,
            **quantiles(values),
        }
    token["abbreviation_outcomes"] = {
        name: {"n": n, "share": round(n / total, 4) if total else None}
        for name, n in outcomes.most_common()
    }
    # The distribution `ambiguous` collapses. Two senses and twenty are not the
    # same problem and one threshold cannot say which corpus you have.
    token["abbreviation_sense_bands"] = {
        band: {
            "n": bands.get(band, 0),
            "share": round(bands.get(band, 0) / total, 4) if total else None,
        }
        for band in SENSE_BANDS
    }
    token["abbreviation_note"] = (
        "`ambiguous` is 2+ UMLS concepts carrying the surface as written, "
        "`highly_ambiguous` is 5+, and `sense_bands` is the distribution both "
        "collapse. Distinct from the free `short_form` shape count above: "
        "neither population contains the other."
    )


def _add_near_miss(token: dict[str, Any], profiles: list[NearMissProfile]) -> None:
    """Candidate misspellings, named for what was measured rather than for what
    a reader would like it to be.

    The field is `near_miss_edit1`, not `misspellings`. It counts alphabetic
    content tokens of four characters or more that no vocabulary carries and
    that sit one edit from a term one of them does — `abdmoninal` next to
    `abdominal`. That is a much sharper filter than `unrecognized`, which on 200
    MIMIC notes is dominated by `daily`, `tablet`, `acute` and `bilateral`, and
    it is still not a misspelling count: a rare drug name absent from both
    lexicons and one character from a common word satisfies the definition and
    is perfectly correct.

    `validation/pipeline/scripts/spelling_validate.py` is what converts the one into the other, by
    measuring precision on an adjudicated sample. Until that number exists the
    name stays honest.

    **The hapax cross is the second filter.** A near-miss occurring once in the
    corpus is far more likely to be an error than one occurring two thousand
    times, so both are reported. Neither is a rate on its own.
    """
    from robustehr.metrics.spelling import MIN_LENGTH

    if not profiles:
        return
    candidates = [p.candidates for p in profiles]
    hits = [p.near_miss for p in profiles]
    total_candidates = sum(candidates)
    corpus: Counter[str] = Counter()
    for p in profiles:
        corpus.update(p.surfaces)
    hapax = sorted(w for w, n in corpus.items() if n == 1)
    token["near_miss_candidates"] = {"total": total_candidates, **quantiles(candidates)}
    token["near_miss_edit1"] = {
        "total": sum(hits),
        "share_of_candidates": round(sum(hits) / total_candidates, 4) if total_candidates else None,
        "distinct_surfaces": len(corpus),
        "distinct_hapax": len(hapax),
        **quantiles(hits),
    }
    token["near_miss_note"] = (
        "NOT a misspelling rate, and the measured gap is large. A near-miss is "
        f"an alphabetic content token of {MIN_LENGTH} characters or more that "
        "neither vocabulary carries and is within one edit (Damerau) of a term "
        "one of them does. Adjudicated on 200 MIMIC-IV notes, precision is "
        "0.425 over distinct surfaces and 0.096 over OCCURRENCES — the total "
        "above is roughly nine parts vocabulary and shorthand to one part "
        "error, because the frequent near-misses are words the lexicons miss "
        "(`refills`, `mellitus`) and clinical shorthand (`angap`, `eomi`). "
        "USE `distinct_hapax`: seen once in the whole corpus, precision 0.526. "
        "See validation/measurements/spelling_precision.json. Edit distance 2 is not "
        "reported — a complete index needs delete-2 neighbourhoods on both "
        "sides (15.5M keys), and an incomplete one would under-report by an "
        "unknown amount."
    )


def _add_span_level(
    levels: dict[str, Any],
    profiles: list[ConceptProfile],
    phenotype_recall: dict[str, float | None],
) -> None:
    """The span level: what the concept layer found, counted as spans.

    A mention IS a span, and this is where it belongs. Reported at the token
    level, two true numbers look like a contradiction — 3,918 mentions over
    12,399 content tokens reads as 32% of the note, and the real figure is
    neither that nor anything derivable from it, because mentions
    overlap and vary in length. `span_token_lengths` is the bridge, and
    `token.concept_covered` is the answer to the question that division was
    trying to ask.
    """
    categories: Counter[str] = Counter()
    lengths: Counter[str] = Counter()
    pheno_spans: Counter[str] = Counter()
    pheno_notes: Counter[str] = Counter()
    pheno_categories: dict[str, Counter[str]] = {}
    for p in profiles:
        categories.update(p.by_category)
        lengths.update(p.span_token_lengths)
        for name, evidence in p.by_phenotype.items():
            pheno_spans[name] += evidence.spans
            if evidence.spans:
                pheno_notes[name] += 1
            if evidence.by_category:
                pheno_categories.setdefault(name, Counter()).update(evidence.by_category)

    mentions = [p.concepts for p in profiles]
    total = sum(mentions)
    densities = [
        round(DENSITY_BASE * p.concepts / p.content_tokens) if p.content_tokens else 0
        for p in profiles
    ]
    span = levels.setdefault("span", {"operators": list(LEVEL_OPERATORS.get("span", ()))})
    span["n"] = {"total": total, **quantiles(mentions)}
    # Per-note distinct CUIs only. A corpus-wide union would need every note's
    # CUI set held at once, which `ConceptProfile` deliberately does not carry.
    span["distinct_cuis_per_note"] = quantiles([p.distinct_cuis for p in profiles])
    span["per_1k_content_tokens"] = quantiles(densities)
    span["token_lengths"] = {
        k: {"spans": lengths[k], "share": round(lengths[k] / total, 4) if total else None}
        for k in sorted(lengths, key=lambda k: (len(k), k))
    }
    span["by_category"] = {
        name: {"spans": n, "share_of_spans": round(n / total, 4) if total else None}
        for name, n in categories.most_common()
    }
    span["by_category_note"] = (
        "shares sum to more than 1: a concept may carry several semantic types, "
        "so the categories overlap. See validation/phenotype/phenotype-concept-table.md for the "
        "exclusive partition."
    )
    if pheno_spans:
        span["by_phenotype"] = {
            name: {
                "evidence_spans": pheno_spans[name],
                "share_of_spans": round(pheno_spans[name] / total, 4) if total else None,
                "notes_with_any": pheno_notes.get(name, 0),
                "share_of_notes": round(pheno_notes.get(name, 0) / len(profiles), 4),
                "measured_set_recall": phenotype_recall.get(name),
                # What the evidence is MADE of. A hypertension count resting
                # entirely on `medication` is a different claim from one
                # resting on `disease`, and the span count cannot say which.
                "by_category": dict(pheno_categories.get(name, Counter()).most_common()),
            }
            for name in sorted(pheno_spans)
        }
        span["by_phenotype_note"] = (
            "a phenotype's count is bounded by its measured set recall: evidence "
            "never matched is evidence never counted here."
        )


def _add_concept_coverage(token: dict[str, Any], profiles: list[ConceptProfile]) -> None:
    """How much of the note is inside a concept, counted in TOKENS.

    This is the question "what percentage of tokens are UMLS concepts" actually
    asks, and dividing the span count by the token count does not answer it: a
    mention spans one to six tokens and mentions overlap. So a coverage mask is
    built per note and the tokens under it are counted, once each.

    Shares are of CONTENT tokens, not of all tokens. Punctuation is 60% of `n`
    and no concept covers it, so the all-token share would be a statement about
    how much punctuation the corpus has.
    """
    covered = [p.concept_tokens for p in profiles]
    content = sum(p.content_tokens for p in profiles)
    per_category: Counter[str] = Counter()
    for p in profiles:
        per_category.update(p.category_tokens)
    token["concept_covered"] = {
        "total": sum(covered),
        "share_of_content": round(sum(covered) / content, 4) if content else None,
        **quantiles(covered),
    }
    token["concept_covered_by_category"] = {
        name: {
            "tokens": n,
            "share_of_content": round(n / content, 4) if content else None,
        }
        for name, n in per_category.most_common()
    }
    token["concept_covered_note"] = (
        "tokens lying inside at least one concept mention, counted ONCE each — "
        "not the span count divided by the token count, which mentions overlap "
        "and vary in length make meaningless. Category rows overlap and sum to "
        "more than the total. Denominator is content tokens: punctuation is "
        "~60% of `n` and no concept covers it."
    )


def _add_assertion_level(levels: dict[str, Any], rows: list[NoteRow]) -> None:
    """The assertion level, keyed on each operator's ACTUAL eligible set.

    This level had the fault the token level had. It reported `negated 355` —
    a count of *mentions carrying the attribute* — while `semantic.negation_flip`
    is eligible on *negation cues*, of which this corpus has a different number.
    Neither predicts the other: one cue scopes over several mentions, and a
    mention can be negated by a cue in a clause the operator would not touch.

    So the cue counts come first and are labelled with the operator they belong
    to. They need the `clinical` extra and NOT a UMLS licence, which is why this
    runs before the concept early-return.
    """
    cues: Counter[str] = Counter()
    for row in rows:
        cues.update(row.cues)
    if not cues:
        return
    block: dict[str, Any] = {"operators": list(LEVEL_OPERATORS["assertion"])}
    for op_id, wanted in CUE_CATEGORIES.items():
        counts = [sum(r.cues.get(c, 0) for c in wanted) for r in rows]
        block[op_id] = {
            "cue_categories": list(wanted),
            "eligible_cues": sum(counts),
            **quantiles(counts),
        }
    # `n` is the CUE count, because a cue is this level's unit — `UnitKind.
    # ASSERTION`, what `_CueFlip.eligible` enumerates. Every other level's `n`
    # is its unit count and this one must mean the same thing, or the overview
    # row is comparing populations.
    per_note = [sum(r.cues.values()) for r in rows]
    block["n"] = {"total": sum(per_note), **quantiles(per_note)}
    block["n_note"] = (
        "`eligible_cues` IS the operator's denominator — the units a severity is "
        "a fraction of. The attribute counts below are a different population: "
        "mentions CARRYING the attribute, which one cue can produce several of."
    )
    levels["assertion"] = block


def _add_assertion_categories(levels: dict[str, Any], profiles: list[ConceptProfile]) -> None:
    """Attribute x semantic category, over mentions — and the assertion shares.

    "355 negated mentions" does not say whether a negation flip lands on a
    disease or on an anatomical site, and those are different corruptions with
    different downstream costs. This is the cross-tabulation that says so.
    """
    attributes: Counter[str] = Counter()
    crossed: dict[str, Counter[str]] = {}
    for p in profiles:
        attributes.update(p.assertion_counts)
        for name, by_category in p.assertion_by_category.items():
            crossed.setdefault(name, Counter()).update(by_category)
    if not attributes:
        return
    block = levels.setdefault("assertion", {"operators": list(LEVEL_OPERATORS["assertion"])})
    total = sum(attributes.values())
    # NOT `n`: `n` is the cue count, and these are mentions carrying an
    # attribute. Naming both `n` is how the two populations got confused.
    block["mentions"] = {"total": total}
    block["by_attribute"] = {
        name: {
            "mentions": n,
            "share": round(n / total, 4),
            "flipped_by": next(
                (op for op, attr in CUE_ATTRIBUTE.items() if attr == name),
                None,
            ),
            "by_category": dict(crossed.get(name, Counter()).most_common()),
        }
        for name, n in attributes.most_common()
    }
    block["modified_share"] = round(
        sum(v for k, v in attributes.items() if k != "unmodified") / total, 4
    )
    block["note"] = (
        "`unmodified` is what ConText calls affirmed. The complement is "
        "`modified`, not `non-affirmed`: `historical` and `family` both affirm "
        "the concept and merely relocate it. `flipped_by` is null for "
        "`unmodified` because every operator flips INTO it as well as out of it."
    )


def assemble(rows: list[NoteRow], phenotype_recall: dict[str, float | None]) -> Table1:
    """Aggregate per-note rows into ONE organisation: the taxonomy's levels.

    One organisation rather than a `by_level` block beside topical blocks
    (`size`, `structure`, `lexicon`, `concepts`, `assertion`, `phenotype`), so
    that no fact appears under two paths. Two
    organisations of one measurement is how a reader ends up quoting whichever
    they happened to find.
    """
    if not rows:
        return Table1(0, {}, {"corpus": "no readable notes"})

    levels = by_level(rows)
    # Lexical classes are a property of tokens, so they live at that level. The
    # four LexicalClass values partition the content tokens; `unrecognized` and
    # `short_form` annotate the same tokens and would take the total past 100%
    # if summed with them, so the partition is named explicitly.
    lex: Counter[str] = Counter()
    for row in rows:
        lex.update(row.lexical)
    total_content = levels["token"]["content"]["total"] or 1
    levels["token"]["lexical_partition"] = [
        "function_word",
        "general_english",
        "numeric_or_symbol",
        "out_of_vocabulary",
    ]
    for name, count in sorted(lex.items()):
        levels["token"][f"lex_{name}"] = {
            "total": count,
            "share_of_content": round(count / total_content, 4),
        }

    # Which of the 58 canonical sections this corpus carries. ABSENT ones are
    # reported explicitly: a section present in 0 of 5 notes is a finding about
    # the corpus, and a missing key is not — a reader scanning for
    # `past_medical_history` must be able to tell "not in these notes" from
    # "not measured".
    kinds = canonical_sections()
    present: Counter[str] = Counter()
    bodies: dict[str, list[int]] = {}
    for row in rows:
        for name, length in row.sections.items():
            present[name] += 1
            bodies.setdefault(name, []).append(length)
    levels["section"]["canonical_presence"] = {
        name: {
            "kind": kind,
            "notes_with": present.get(name, 0),
            "share_of_notes": round(present.get(name, 0) / len(rows), 4),
            "body_chars_median": quantiles(bodies.get(name, []))["median"],
        }
        for name, kind in kinds.items()
    }
    # Mirrored onto the header level too: that is where the "resolved to a named
    # section" count sits, and a reader asking WHICH sections is reading that
    # row rather than the section level two rows above.
    levels["header"]["_section_presence"] = levels["section"]["canonical_presence"]
    levels["section"]["canonical_absent"] = sorted(n for n in kinds if not present.get(n))
    levels["section"]["canonical_declared"] = len(kinds)
    # A header the segmenter recognised but that maps to no canonical id. High
    # counts here mean the lexicon is behind this corpus's templates, which is a
    # property of the lexicon rather than of the notes.
    levels["section"]["non_canonical_ids_seen"] = sorted(set(present) - set(kinds))

    _add_abbreviation_load(levels["token"], [r.ambiguity for r in rows if r.ambiguity])
    _add_near_miss(levels["token"], [r.near_miss for r in rows if r.near_miss])

    # The assertion level runs off CUES, which need the `clinical` extra and no
    # terminology at all. So it lands BEFORE the concept early-return: a reader
    # without a UMLS licence still gets every SEMANTIC operator's denominator.
    _add_assertion_level(levels, rows)

    profiles = [r.concepts for r in rows if r.concepts is not None]
    if not profiles:
        return Table1(
            len(rows),
            levels,
            {
                "span": "no UMLS index; a span is a concept mention and there are none to count",
                "token.concept_covered": (
                    "no UMLS index; every structural level above is unaffected"
                ),
                "token.abbreviations": (
                    "no UMLS index; `short_form` above is the free shape count, "
                    "which is a different population"
                ),
                "assertion.by_category": "requires the concept layer; the cue counts above do not",
                "span.by_phenotype": "requires the concept layer",
            },
        )

    _add_span_level(levels, profiles, phenotype_recall)
    _add_concept_coverage(levels["token"], profiles)
    _add_assertion_categories(levels, profiles)

    # Recomputed AFTER the assertion level lands, else it reports a level that
    # exists by the time anyone reads it.
    levels["_unmeasured_levels_with_operators"] = sorted(
        lv for lv, ops in LEVEL_OPERATORS.items() if ops and lv not in levels
    )
    return Table1(len(rows), levels)


__all__ = ["DENSITY_BASE", "NoteRow", "Table1", "assemble", "measure_note", "quantiles"]
