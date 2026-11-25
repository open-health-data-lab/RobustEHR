"""Table 1 and Table 2, in the shape a methods section prints them.

**Why a second renderer.** `cli._describe_markdown` prints the whole
characterisation as a dozen tables, one per level, each with its own columns.
That is the right shape for auditing an instrument and the wrong shape for
reading a corpus: a reader who wants "how long is a note, how much of it is
clinical content, how much shorthand" has to hold four tables at once.

A journal Table 1 is ONE table with indented rows, and the indentation carries
the meaning — a sub-row is a decomposition of the row above it, not another
fact beside it. So `word_min3` sits under `content tokens` rather than in a
table of its own, and a reader can stop at any depth.

**Indentation in markdown.** Leading spaces in a table cell are stripped by
every renderer, so depth is drawn with `&nbsp;`. It renders on GitHub, in
VS Code, in pandoc and in a browser; in raw text it is visible but harmless,
which is the trade a table like this is worth.

**Table 2 is a different question and gets a different table.** Table 1 is what
the corpus is. Table 2 is what the phenotype layer FOUND in it, per phenotype
and by semantic category, beside the size of the set that was looking. Those
two numbers together are the only way to read a zero: `hfpef` declares 117
concepts and recovers no evidence from 217 positive notes, which is a fact
about the set, not about the notes.
"""

from __future__ import annotations

from typing import Any, TextIO

#: Sense bands in reporting order, mirrored from `metrics.ambiguity` so a
#: round-tripped payload renders in the order the measurement produced.
SENSE_BANDS = ("0", "1", "2-4", "5-9", "10+")

#: One level of indentation in a markdown table cell.
INDENT = "&nbsp;&nbsp;&nbsp;&nbsp;"

#: Levels in the order a reader descends a note, with the label each gets.
#:
#: `medication` sits immediately after `span` because it *decomposes* the
#: medication row of that level's category breakdown, rather than counting
#: something new. Placed anywhere else the two look like independent numbers
#: that happen to disagree.
LEVEL_LABELS: tuple[tuple[str, str], ...] = (
    ("document", "Document"),
    ("section", "Sections"),
    ("header", "Headers"),
    ("break", "Structural breaks"),
    ("sentence", "Sentences"),
    ("list_block", "Lists"),
    ("list_item", "List items"),
    ("aligned_block", "Aligned blocks"),
    ("space_run", "Column gaps (runs of 2+ spaces)"),
    ("word_space", "Word gaps (a single space between two words)"),
    ("placeholder", "De-identification placeholders"),
    ("span", "Concept mentions (spans)"),
    ("medication", "— of which medications, by how they are named"),
    ("numeric_value", "Numeric values"),
    ("clinical_content", "Content tokens, by clinical salience"),
    ("token", "Tokens"),
    ("character", "Characters"),
    ("assertion", "Assertion cues"),
)

#: What each level IS, in one line, keyed by the same names.
#:
#: Printed as a glossary beneath the table rather than as a column, because a
#: definition wraps and a table cell does not. Every one of these was a question
#: somebody actually had to ask — "sections versus headers" is not obvious from
#: two counts that differ by fourteen, and a reader who guesses wrong reads the
#: dose denominators wrong too.
LEVEL_DEFINITIONS: dict[str, str] = {
    "document": "The whole note.",
    "clinical_content": (
        "Content tokens split by **measured clinical salience** — the rate at which a "
        "token falls inside a span a clinician adjudicated as a clinical concept, on "
        "MIMIC-IV discharge summaries, plus a curated drug vocabulary for what that "
        "benchmark under-annotates (it marks only 27% of medication mentions). The level "
        "a *targeted* corruption is judged on: `clinical_share` says whether what changed "
        "was clinical content or prose. Untargeted corruption moves this share barely at "
        "all; clinically-targeted corruption moves it a great deal. `unmeasured` is kept "
        "separate rather than folded into either side. Method and limits — corpus-bound, "
        "token-level, context-blind — in `validation/protocol.md` §9."
    ),
    "section": (
        "A section-kind header **plus the body beneath it**, to the next header at the "
        "same or shallower depth. More sections than section-kind headers is normal: "
        "the text before the first header, and any gap between two sections, is tiled "
        "as `_preamble` / `_interstitial` so every character belongs to exactly one."
    ),
    "header": (
        "The heading **line itself** — label plus its colon, not the content under it. "
        "**Counted here as SECTION HEADERS only**, which is the population all three "
        "header operators run on. Heading-shaped lines that are not note structure — "
        "exam subsections (`HEENT:`, `CV:`) and pharmacy boilerplate (`Disp:`, "
        "`Refills:`, which appear in a quarter of notes) — are reported as a sub-row "
        'and excluded, because counting them made "delete 30% of headers" mean '
        "something different in every note. `Substantive` narrows once more, to "
        "headers with real content beneath them: a `Facility:` whose body is a "
        "de-identification mask is present to a parser and absent to a reader, so "
        "deleting it is a corruption nobody can observe."
    ),
    "break": (
        "The whitespace separating one block from the next — **not every newline**. A "
        "hard-wrapped sentence spans several lines and those newlines are continuations, "
        "not structure; boundaries interior to a list or lab table belong to other "
        "operators and are excluded here."
    ),
    "sentence": "Sentences over the token stream, split into narrative prose and layout lines.",
    "list_block": "A run of consecutive items sharing one marker style. One list, not one item.",
    "list_item": "A single marked item inside such a block.",
    "aligned_block": (
        "A run of lines whose **column layout carries meaning** — a lab table, or the "
        "`Name: ___   Unit No: ___` header. Re-spacing one can re-associate a value "
        "with the wrong label, which is why it is measured apart from prose whitespace."
    ),
    "space_run": (
        "A run of **two or more** horizontal spaces — the gap that holds a lab table's "
        "columns apart. Collapsing one to a single space loses the alignment but no "
        "word boundary, so it is reference-preserving."
    ),
    "word_space": (
        "A **single** space separating two words in prose — the gap that keeps `chest` "
        "and `pain` apart. Deleting one merges two words, which no token projection "
        "survives, so it is a different operator and a weaker contract than the "
        "column gaps above."
    ),
    "placeholder": "A de-identification mask, whatever convention the corpus uses.",
    "span": (
        "A concept mention returned by the matcher. A **span, not a token**: `acute on "
        "chronic systolic heart failure` is one mention over six tokens. Categories are "
        "listed as leaves; `disorder` and `procedure` are unions of leaves above them "
        "and are shown separately as rollups so nothing is counted twice."
    ),
    "medication": (
        "The `medication` category above, decomposed by how each mention is *written*. "
        "Not a second count of drugs — the same mentions, classified."
    ),
    "numeric_value": (
        "Integer tokens with an exact written form. Decimals and unit-bearing values "
        "are counted but excluded from the default denominator."
    ),
    "token": "Every token, including whitespace and punctuation; content tokens are the subset.",
    "character": "Every character in the note.",
    "assertion": "A negation, uncertainty, temporality or experiencer cue span.",
}

#: The four lexical classes, and what each actually tests. These names are read
#: wrongly by default — `out_of_vocabulary` sounds like "misspelled" and is
#: mostly clinical vocabulary — so the table says so rather than leaving a
#: reader to assume.
LEXICAL_CLASS_NOTES: tuple[tuple[str, str], ...] = (
    (
        "function_word",
        "A closed-class word — `the`, `of`, `was` — from the shipped function-word "
        "list. Grammar rather than content, and the tightest control condition "
        "available: corrupting only these should move nothing.",
    ),
    (
        "general_english",
        "In `english_vocabulary.txt`: 28,329 words with a wordfreq Zipf score of at "
        "least 3.0, i.e. ordinary written English, **with nothing subtracted**. A "
        "word here is common English; it may also be clinical (`fever`, `wound`, "
        "`stable` all qualify), so this is not the non-clinical class.",
    ),
    (
        "out_of_vocabulary",
        "**Not in that general-English list — which on clinical text mostly means "
        "clinical.** `furosemide`, `HFrEF` and `pneumothorax` all land here, and so "
        "do genuine misspellings and de-identification artifacts. It is a vocabulary "
        "statement, not an error rate; the near-miss row below is the closest thing "
        "to the latter, and carries its own precision caveat.",
    ),
    (
        "numeric_or_symbol",
        "A content token carrying no letter — a lab value, a dose, a date fragment.",
    ),
)


def _n(value: Any) -> str:
    """A count with thousands separators, or an em dash for a missing one."""
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _spread(block: dict[str, Any] | None, key: str = "n") -> str:
    """`median [p25-p75]`, the only summary this table uses for a per-note count.

    Means are never printed: note lengths are right-skewed, so a mean describes
    a note that does not exist.
    """
    if not isinstance(block, dict):
        return "—"
    stat = block.get(key)
    if not isinstance(stat, dict) or stat.get("median") is None:
        return "—"
    return f"{stat['median']:,} [{stat['p25']:,}-{stat['p75']:,}]"


def _total_int(block: dict[str, Any] | None, key: str = "n") -> int | None:
    """The raw total, for arithmetic. `_total` formats and cannot be summed."""
    if not isinstance(block, dict):
        return None
    stat = block.get(key)
    return stat.get("total") if isinstance(stat, dict) else None


def _total(block: dict[str, Any] | None, key: str = "n") -> str:
    if not isinstance(block, dict):
        return "—"
    stat = block.get(key)
    return _n(stat.get("total")) if isinstance(stat, dict) else "—"


def _share(value: Any) -> str:
    return "—" if value is None else f"{value:.3f}"


class _Rows:
    """Accumulates `(depth, label, per-note, total, share)` rows."""

    def __init__(self) -> None:
        self.rows: list[tuple[int, str, str, str, str]] = []

    def add(
        self, depth: int, label: str, spread: str = "", total: str = "", share: str = ""
    ) -> None:
        self.rows.append((depth, label, spread or "", total or "", share or ""))

    def render(self, write: Any) -> None:
        write("| Characteristic | Per note, median [IQR] | Total | Share |")
        write("|---|---:|---:|---:|")
        for depth, label, spread, total, share in self.rows:
            name = INDENT * depth + (label if depth else f"**{label}**")
            write(f"| {name} | {spread} | {total} | {share} |")


def _token_rows(rows: _Rows, token: dict[str, Any]) -> None:
    """The token level, decomposed so each operator's denominator is a sub-row.

    **Two denominators, and mixing them is a real error.** `word`, `numeric`,
    `alphanumeric` and `punctuation` partition ALL tokens — `_token_composition`
    walks `doc.tokens` — while `concept_covered`, `abbreviations` and the
    lexical classes are shares of CONTENT tokens. A first version divided
    everything by content and reported punctuation at 1.469 of the note, which
    is the kind of number a reader notices and a reviewer does not.
    """
    total = (token.get("n") or {}).get("total") or 1
    content_block = token.get("content") or {}
    content = content_block.get("total") or 1

    # Shares of ALL tokens.
    for key, label in (
        ("word", "Words"),
        ("word_min3", "≥3 chars — `input.typo` acts here"),
        ("word_min4", "≥4 chars — `control.char_shuffle` acts here"),
        ("ocr_confusable", "Holding an OCR-confusable glyph (exposure, not the dose)"),
        ("short_form", "Upper-case short forms (shape only)"),
        ("numeric", "Numeric"),
        ("alphanumeric", "Alphanumeric"),
        ("punctuation", "Punctuation"),
    ):
        if key in token:
            depth = 2 if key.startswith("word_min") or key == "ocr_confusable" else 1
            n = (token[key] or {}).get("total")
            rows.add(
                depth, label, _spread(token, key), _n(n), _share(None if n is None else n / total)
            )

    rows.add(
        1,
        "Content tokens",
        _spread(token, "content"),
        _n(content_block.get("total")),
        _share(content / total),
    )

    # Shares of CONTENT tokens, from here down.
    if "concept_covered" in token:
        covered = token["concept_covered"]
        rows.add(
            2,
            "Inside a UMLS concept",
            _spread(token, "concept_covered"),
            _n(covered.get("total")),
            _share(covered.get("share_of_content")),
        )
        for name, row in (token.get("concept_covered_by_category") or {}).items():
            rows.add(3, name, "", _n(row["tokens"]), _share(row["share_of_content"]))

    if "abbreviations" in token:
        abbrev = token["abbreviations"]
        rows.add(
            2,
            "Abbreviation-shaped",
            _spread(token, "abbreviations"),
            _n(abbrev.get("total")),
            _share(abbrev.get("share_of_content")),
        )
        for key, label in (
            ("abbreviations_ambiguous", "Ambiguous (≥2 UMLS senses)"),
            ("abbreviations_highly_ambiguous", "Highly ambiguous (≥5)"),
        ):
            block = token.get(key) or {}
            rows.add(
                3,
                label,
                _spread(token, key),
                _n(block.get("total")),
                _share(block.get("share_of_abbreviations")),
            )
        # Explicit band order. `json.dumps(sort_keys=True)` sorts them as
        # STRINGS, which puts `10+` between `1` and `2-4` and makes a monotone
        # distribution look like noise.
        bands = token.get("abbreviation_sense_bands") or {}
        for band in SENSE_BANDS:
            row = bands.get(band)
            if row:
                rows.add(4, f"{band} UMLS senses", "", _n(row["n"]), _share(row["share"]))

    if "near_miss_edit1" in token:
        near = token["near_miss_edit1"]
        rows.add(
            2,
            "Unrecognised, ≥4 chars (near-miss candidates)",
            _spread(token, "near_miss_candidates"),
            _total(token, "near_miss_candidates"),
        )
        rows.add(
            3,
            "Within one edit of a known term — NOT a misspelling rate",
            _spread(token, "near_miss_edit1"),
            _n(near["total"]),
        )
        rows.add(4, "Distinct surfaces", "", _n(near["distinct_surfaces"]))
        rows.add(4, "Distinct hapax — the usable subset", "", _n(near["distinct_hapax"]))

    partition = token.get("lexical_partition") or []
    if partition:
        rows.add(2, "Lexical class (partitions content tokens)")
        for name in partition:
            block = token.get(f"lex_{name}")
            if block:
                rows.add(3, name, "", _n(block["total"]), _share(block["share_of_content"]))


def _span_rows(rows: _Rows, span: dict[str, Any]) -> None:
    rows.add(1, "Distinct CUIs per note", _spread(span, "distinct_cuis_per_note"))
    rows.add(1, "Mentions per 1,000 content tokens", _spread(span, "per_1k_content_tokens"))
    lengths = span.get("token_lengths") or {}
    if lengths:
        rows.add(1, "Length in tokens — the bridge to the token level")
        for name, row in lengths.items():
            rows.add(2, f"{name} token(s)", "", _n(row["spans"]), _share(row["share"]))
    categories = span.get("by_category") or {}
    if categories:
        _category_rows(rows, categories)


def _category_rows(rows: _Rows, categories: dict[str, Any]) -> None:
    """Semantic categories, with the containing ones kept out of the distribution.

    **`disorder` is not a peer of `disease`, it is their union.** The category
    file defines `disease`, `symptom` and `finding` as *derived from* `disorder`,
    and `diagnostic_procedure` / `therapeutic_procedure` from `procedure`. Listed
    in one flat block the parents look like additional categories and every
    disease is counted twice — which is what made the old block sum to 1.4 and
    carry the unhelpful apology "(overlapping; sums past 1)".

    So the distribution is the **leaves**, and the parents are printed under it
    as rollups that explicitly do not add. The leaf set is still not a strict
    partition — `lab_measurement` shares a TUI with `lab_result` and another
    with `diagnostic_procedure` — so the header says "may overlap slightly"
    rather than claiming a partition it cannot deliver.
    """
    from robustehr.categories import load_categories

    try:
        parents = {name: c.parent for name, c in load_categories().items()}
    except Exception:  # pragma: no cover - category file always ships
        parents = {}
    rollups = {name for name in categories if name in set(parents.values()) - {None}}
    leaves = {k: v for k, v in categories.items() if k not in rollups}

    rows.add(1, "Semantic category (leaf categories; may overlap slightly)")
    for name, row in leaves.items():
        rows.add(2, name, "", _n(row["spans"]), _share(row["share_of_spans"]))
    if rollups:
        rows.add(1, "Rollups — these CONTAIN rows above and must not be added to them")
        for name in sorted(rollups):
            row = categories[name]
            children = sorted(c for c, p in parents.items() if p == name and c in categories)
            label = f"{name} (= {' + '.join(children)})" if children else name
            rows.add(2, label, "", _n(row["spans"]), _share(row["share_of_spans"]))


def _assertion_rows(rows: _Rows, assertion: dict[str, Any]) -> None:
    """Cues first — they are the operators' denominators — then the mentions."""
    rows.add(1, "Eligible cues per operator — the dose denominator")
    for op_id in assertion.get("operators", []):
        row = assertion.get(op_id)
        if row:
            rows.add(2, f"`{op_id}`", _spread(assertion, op_id), _n(row["eligible_cues"]))
    attributes = assertion.get("by_attribute") or {}
    if attributes:
        total = (assertion.get("mentions") or {}).get("total")
        rows.add(1, "Mentions carrying an attribute (a different population)", "", _n(total))
        for name, row in attributes.items():
            rows.add(2, name, "", _n(row["mentions"]), _share(row["share"]))


def table1(payload: dict[str, Any], write: Any) -> None:
    """The digestible Table 1: one table, indented, in reading order."""
    levels = payload.get("by_level") or {}
    write(f"# Table 1 — characteristics of {payload['corpus']}\n")
    write(
        f"**{payload['notes']:,} notes.** "
        "Rows are the structural levels an operator can target; indented rows "
        "decompose the row above them. `Share` is of the level's own "
        "denominator, named in the row. Medians with IQR, never means — note "
        "lengths are right-skewed, so a mean describes a note that does not "
        "exist.\n"
    )
    rows = _Rows()
    present: list[str] = []
    for key, label in LEVEL_LABELS:
        block = levels.get(key)
        if not block:
            continue
        present.append(key)
        rows.add(0, label, _spread(block), _total(block))
        _level_detail(rows, key, block)
    rows.render(write)

    if payload.get("unavailable"):
        write("\n**Not measured** (each with its reason, rather than reported as zero):\n")
        for name, reason in sorted(payload["unavailable"].items()):
            write(f"* `{name}` — {reason}")

    _glossary(present, write)


def _glossary(present: list[str], write: Any) -> None:
    """What each level means, under the table.

    A definition is a sentence and a table cell is not wide enough for one, so
    the two are separated rather than crammed together. Only levels that
    actually appeared are defined — a glossary listing rows the reader cannot
    see is noise.
    """
    definitions = [(k, LEVEL_DEFINITIONS[k]) for k in present if k in LEVEL_DEFINITIONS]
    if not definitions:
        return
    write("\n## What the lexical classes mean\n")
    write(
        "They partition **content tokens** and are named for what they test, "
        "which is vocabulary membership rather than correctness.\n"
    )
    for name, note in LEXICAL_CLASS_NOTES:
        write(f"**`{name}`** — {note}\n")

    write("\n## What each level is\n")
    write(
        'The level decides the **denominator of a dose**: "30%" means 30% of the '
        "eligible units *of that level*, so two operators at one severity touch "
        "very different amounts of text. Sub-rows naming an operator are that "
        "operator's own eligible count.\n"
    )
    labels = dict(LEVEL_LABELS)
    for key, text in definitions:
        write(f"**{labels.get(key, key)}** — {text}\n")


def _section_name_rows(rows: _Rows, header: dict[str, Any], top: int = 25) -> None:
    """Which named sections the corpus actually has, indented under the count.

    The header count says a note carries 27 section headers; it does not say
    that `discharge_medications` is in 99% of them and `code_status` in 4%. That
    difference decides what a header corruption is actually doing — deleting 30%
    of headers in a corpus where every note has the same twelve sections is a
    different experiment from one where the vocabulary is long-tailed.

    Share of notes rather than a total: a section appearing twice in one note is
    still one section that corpus has.
    """
    presence = header.get("_section_presence") or {}
    seen = {k: v for k, v in presence.items() if v.get("notes_with")}
    if not seen:
        return
    ordered = sorted(seen.items(), key=lambda kv: (-kv[1]["notes_with"], kv[0]))
    for name, row in ordered[:top]:
        rows.add(
            2,
            f"`{name}`",
            _n(row.get("body_chars_median")),
            _n(row["notes_with"]),
            f"{row['share_of_notes']:.3f}",
        )
    if len(ordered) > top:
        rows.add(2, f"_… {len(ordered) - top} further sections; see the JSON_")


def _medication_rows(rows: _Rows, block: dict[str, Any]) -> None:
    """How this corpus names its drugs, as a share of the mentions it names.

    **Which population is being described has to be on the row.** The count is
    UMLS medication mentions when a matcher ran and dictionary hits when one did
    not, and those differ by a factor of three on a real note — 129 against 46.
    Printed without saying which, the level silently contradicts
    `span.by_category.medication` two rows above it.
    """
    total = (block.get("n") or {}).get("total") or 0
    measured = ((block.get("concept_measured") or {}).get("total") or 0) > 0
    rows.add(
        1,
        "Population" + ("" if measured else " (no matcher — see note)"),
        "",
        "UMLS medication mentions" if measured else "drug-dictionary hits",
    )
    for field_name, label in (
        ("generic", "Named generically"),
        ("commercial", "Named commercially"),
        # Not a failure. A surface in neither dictionary, or in both, is one no
        # substitution can be confident about — `iron` is a generic and somebody's
        # brand, `Tylenol` is absent from the source data. See metrics/medications.py.
        ("unknown", "Representation undetermined"),
    ):
        n = (block.get(field_name) or {}).get("total")
        rows.add(
            2,
            label,
            _spread(block, field_name),
            _n(n),
            _share(None if n is None or not total else n / total),
        )
    n = (block.get("renameable") or {}).get("total")
    rows.add(
        1,
        "Substitutable — `lexical.medication_rename` acts here",
        _spread(block, "renameable"),
        _n(n),
        _share(None if n is None or not total else n / total),
    )


def _clinical_content_detail(rows: _Rows, block: dict[str, Any]) -> None:
    """Clinical / non-clinical / unmeasured, with shares of the measured part.

    The share denominator is deliberately `clinical + non_clinical` rather than
    the level total: `unmeasured` is a statement about the lexicon's coverage,
    not about the note, and dividing by it would let a corpus full of rare terms
    look less clinical than it is. It keeps its own row so the coverage is
    visible rather than assumed.
    """
    measured = (_total_int(block, "clinical") or 0) + (_total_int(block, "non_clinical") or 0)
    for field, label in (
        ("clinical", "Clinical — salience >= 0.50, or a curated drug"),
        ("non_clinical", "Non-clinical — ordinary English below that"),
    ):
        n = _total_int(block, field)
        rows.add(
            1,
            label,
            _spread(block, field),
            _total(block, field),
            _share(n / measured) if measured and n is not None else "",
        )
    rows.add(
        1,
        "Unmeasured — never seen often enough to score",
        _spread(block, "unmeasured"),
        _total(block, "unmeasured"),
    )


def _level_detail(  # noqa: PLR0912 - one branch per structural level
    rows: _Rows, key: str, block: dict[str, Any]
) -> None:
    """The indented sub-rows that decompose one level."""
    if key == "clinical_content":
        _clinical_content_detail(rows, block)
    elif key == "document":
        rows.add(1, "Lines", _spread(block, "lines"), _total(block, "lines"))
    elif key == "section":
        declared = block.get("canonical_declared")
        absent = len(block.get("canonical_absent") or [])
        if declared:
            rows.add(1, f"Canonical ids present, of {declared} declared", "", _n(declared - absent))
            rows.add(1, "Absent — a fact about the corpus, not a missing row", "", _n(absent))
    elif key == "header":
        rows.add(
            1,
            "Heading-shaped lines in total",
            _spread(block, "heading_lines"),
            _total(block, "heading_lines"),
        )
        rows.add(
            2,
            "Excluded — exam subsections, pharmacy boilerplate",
            _spread(block, "excluded_non_structural"),
            _total(block, "excluded_non_structural"),
        )
        rows.add(
            1,
            "Resolved to a named section",
            _spread(block, "canonical"),
            _total(block, "canonical"),
        )
        _section_name_rows(rows, block)
        rows.add(
            1,
            "Heuristic match, section unknown",
            _spread(block, "guessed"),
            _total(block, "guessed"),
        )
        rows.add(
            1,
            "Standalone, on its own line — `render.header_delete`",
            _spread(block, "standalone"),
            _total(block, "standalone"),
        )
        rows.add(
            2,
            "Inline (`Service: MEDICINE`) — deletion would take the value",
            _spread(block, "inline"),
            _total(block, "inline"),
        )
        rows.add(
            1,
            "Has another clinical name — `render.header_rename`",
            _spread(block, "renameable"),
            _total(block, "renameable"),
        )
        floor = (block.get("min_body_chars") or {}).get("median")
        rows.add(
            1,
            f"Substantive — at least {floor or 60} characters of body beneath it",
            _spread(block, "substantive"),
            _total(block, "substantive"),
        )
    elif key == "break":
        rows.add(
            1,
            "Paragraph (blank-line separated)",
            _spread(block, "paragraph"),
            _total(block, "paragraph"),
        )
        rows.add(1, "Line", _spread(block, "line"), _total(block, "line"))
    elif key == "list_block":
        rows.add(
            1,
            "Two or more items — render.list_to_prose",
            _spread(block, "multi_item"),
            _total(block, "multi_item"),
        )
    elif key == "word_space":
        rows.add(
            1, "All single spaces", _spread(block, "single_spaces"), _total(block, "single_spaces")
        )
        rows.add(1, "In layout, not prose", _spread(block, "in_layout"), _total(block, "in_layout"))
    elif key == "numeric_value":
        rows.add(1, "All numeric tokens", _spread(block, "total"), _total(block, "total"))
        rows.add(
            1,
            "Decimal — no exact written form",
            _spread(block, "decimal"),
            _total(block, "decimal"),
        )
        rows.add(
            1,
            "Unit-bearing — excluded unless mode=all",
            _spread(block, "unit_bearing"),
            _total(block, "unit_bearing"),
        )
    elif key == "medication":
        _medication_rows(rows, block)
    elif key == "sentence":
        rows.add(1, "Prose", _spread(block, "prose"), _total(block, "prose"))
        rows.add(1, "Layout (lab rows, lists)", _spread(block, "layout"), _total(block, "layout"))
    elif key == "placeholder":
        rows.add(1, "Per 1,000 characters", _spread(block, "per_1k_chars"))
    elif key == "span":
        _span_rows(rows, block)
    elif key == "token":
        _token_rows(rows, block)
    elif key == "character":
        for field, label2 in (
            ("alpha", "Alphabetic"),
            ("digit", "Digit"),
            ("whitespace", "Whitespace"),
            ("punctuation", "Punctuation"),
            # The character-error-rate denominator. `token.ocr_confusable`
            # counts the tokens exposed; this counts the positions dosed, and
            # a severity of 0.10 is 10% of THIS.
            ("ocr_confusable", "OCR-confusable positions — `input.ocr_confusion` acts here"),
        ):
            rows.add(1, label2, _spread(block, field), _total(block, field))
    elif key == "assertion":
        _assertion_rows(rows, block)


def table2(
    payload: dict[str, Any],
    # See `render`: `_distinct` may be absent, and this function is the one that
    # pops it with a `None` default.
    sets: dict[str, dict[str, int | None]],
    write: Any,
    runtime: dict[str, int] | None = None,
) -> None:
    """Table 2: what each phenotype's concept set is, and what it found.

    **Three numbers, kept apart because they have disagreed before.** `runtime`
    is what `concepts.phenotype.build` actually carries — the set `--target
    pheno=` selects and `index_document` tests mentions against. `declared` is
    the full faceted definition `phenotype_set_audit.json` counts. The table
    was born from their disagreement: `build()` once expanded only the disorder
    closure while the facets sat built and unloaded, so hypertension ran with
    361 of 1,074 audited concepts, hfpef with 8, and 1,388 MIMIC-IV notes
    returned zero medication, procedure, symptom or lab evidence for a reason
    no reader could see. Facets (vetting-gated) now load by default, so the two
    columns agree wherever the facet artifacts are installed — and a remaining
    gap is a fact worth reading, not a rendering choice.

    Reporting `declared` beside `found` alone would read as "the set is huge and
    finds nothing", which blames the wrong thing. Both columns, and any gap
    named under every table it affects.
    """
    by_group = payload.get("by_group") or {}
    live_sizes = runtime or {}
    write("# Table 2 — UMLS concepts per phenotype, declared and found\n")
    write(
        "`Runtime` is the set the annotator actually carries — seeds expanded "
        "through the SNOMED hierarchy plus the medication, finding and "
        "vetting-gated proposed facets, what `--target pheno=` selects. "
        "`Declared` is the full faceted definition from the audit. The two "
        "agree wherever the facet artifacts are installed; a difference means "
        "the runtime fell back to the disorder closure, and any zero in a "
        "category it never carried says nothing about the notes. `Found` is "
        "evidence recovered in the cohort of notes an expert labelled POSITIVE "
        "for that phenotype.\n"
    )
    for name in sorted(k for k in by_group if not k.startswith("_")):
        group = by_group[name]
        phenotypes = group["phenotypes"]
        if not phenotypes:
            continue
        by_pheno = ((group["by_level"].get("span") or {}).get("by_phenotype")) or {}
        write(f"\n## {name} — {group['notes']:,} positive notes\n")
        for phenotype in phenotypes:
            evidence = by_pheno.get(phenotype) or {}
            declared = dict(sets.get(phenotype) or {})
            # Distinct set size where the audit provides it; the category sum
            # double-counts multi-category concepts and is NOT the set size.
            distinct = declared.pop("_distinct", None)
            found = evidence.get("by_category") or {}
            spans = evidence.get("evidence_spans", 0)
            recall = evidence.get("measured_set_recall")
            live = live_sizes.get(phenotype)
            notes_with = evidence.get("notes_with_any", 0)
            # `_distinct` was the only nullable entry and it has been popped, but
            # filtering rather than asserting keeps this correct if another
            # optional key is ever added to the mapping.
            total_declared = (
                distinct
                if distinct is not None
                else sum(v for v in declared.values() if v is not None)
            )
            write(
                f"**`{phenotype}`** — {_n(live)} concepts at runtime of "
                f"{total_declared:,} declared; {spans:,} evidence spans found in "
                f"{notes_with:,} of these {group['notes']:,} notes "
                f"(set recall {'—' if recall is None else f'{recall:.3f}'}).\n"
            )
            if not declared and not found:
                write("_No concept set and no evidence._\n")
                continue
            head = "| Semantic category | Concepts declared | Evidence spans found"
            write(f"{head} | Spans per declared concept |")
            write("|---|---:|---:|---:|")
            for category in sorted(set(declared) | set(found)):
                d, f = declared.get(category, 0), found.get(category, 0)
                per = f"{f / d:.2f}" if d else "—"
                write(f"| {category} | {_n(d)} | {_n(f)} | {per} |")
            write(f"| **total** | **{_n(total_declared)}** | **{_n(spans)}** | |")
            if live is not None and live < total_declared:
                write(
                    f"\n_Only {_n(live)} of these {total_declared:,} concepts are loaded "
                    "at runtime — the facet artifacts were absent (or vetting dropped "
                    "concepts the audit still counts) when the runtime audit ran. A zero "
                    "in a category the runtime set never carried says nothing about the "
                    "notes._"
                )


def render(
    payload: dict[str, Any],
    # `int | None` because `_distinct` rides along in this mapping and the audit
    # does not always supply it — line 756 pops it with a `None` default and
    # falls back to the category sum. The signature said `int`, which made the
    # one caller that passes the real thing a type error.
    sets: dict[str, dict[str, int | None]],
    out: TextIO,
    runtime: dict[str, int] | None = None,
) -> None:
    """Both tables, to one stream."""

    def write(line: str = "") -> None:
        print(line, file=out)

    table1(payload, write)
    section_inventory(payload, write)
    if payload.get("by_group"):
        write("\n---\n")
        table2(payload, sets, write, runtime)


#: Levels that need a terminology index. Excluded from the post-corruption delta
#: table: measuring them would mean re-tagging every corrupted corpus (2.38 s a
#: note, five hours over 36 conditions) to answer a question the delta table is
#: not asking. Where the corruption LANDED in UMLS terms is derived for free
#: from the clean tags and the edit script — see `metrics/impact.py` — and the
#: baseline table carries the full concept characterisation.
CONCEPT_LEVELS = frozenset({"span", "medication", "assertion"})


def delta_table(
    baseline: dict[str, Any],
    corrupted: dict[str, Any],
    write: Any,
    title: str,
    subtitle: str = "",
) -> None:
    """What this corruption did to the corpus, level by level.

    A post-corruption table on its own is hard to read: nobody remembers that
    the clean corpus had 27 headers per note, so "14" means nothing. The
    question a condition answers is the *change*, so the change is the table and
    the two absolute values are the supporting columns.

    Both sides come from the same `assemble`, so a difference here is a
    difference the instrument can see rather than an artifact of measuring the
    two corpora differently.

    Rows that did not move are kept rather than filtered. The zeros are the
    result: `render.header_delete` moving the header and section levels *and
    nothing else* is the evidence that it isolated one corruption, which is
    exactly what Experiment 1 claims. A table showing only what changed could
    not make that claim.
    """
    write(f"# {title}\n")
    if subtitle:
        write(f"{subtitle}\n")
    write(
        "**Δ is corrupted minus baseline**, per note (median) and over the corpus "
        "(total). Levels needing a terminology index are excluded here; the "
        "baseline table carries them, and `concept_impact.json` beside this file "
        "reports which UMLS concepts this condition's edits landed on.\n"
    )
    base_levels = baseline.get("by_level") or {}
    corr_levels = corrupted.get("by_level") or {}

    rows: list[tuple[str, str, Any, Any, Any, Any]] = []
    for key, label in LEVEL_LABELS:
        if key in CONCEPT_LEVELS:
            continue
        before, after = base_levels.get(key), corr_levels.get(key)
        if not before or not after:
            continue
        rows.append((key, label, *_pair(before, after, "n")))
        for field_name, sub_label in _delta_fields(key, before, after):
            rows.append((key, f"{INDENT}{sub_label}", *_pair(before, after, field_name)))

    write("| Characteristic | Baseline | Corrupted | Δ per note | Δ total | Δ% |")
    write("|---|---:|---:|---:|---:|---:|")
    for _key, label, b_med, c_med, d_med, totals in rows:
        d_total, pct = totals
        name = label if label.startswith(INDENT) else f"**{label}**"
        write(
            f"| {name} | {_n(b_med)} | {_n(c_med)} | {_signed(d_med)} "
            f"| {_signed(d_total)} | {pct} |"
        )
    moved = sorted({k for k, _, _, _, d, _ in rows if isinstance(d, int) and d != 0})
    write("\n**Levels that moved:** " + (", ".join(f"`{m}`" for m in moved) or "_none_"))


#: Sub-rows per level, in reading order, with the label each gets. Raw field
#: names (`word_min3`, `heading_lines`) are precise and unreadable; the operator
#: each denominator belongs to is the thing a reader is looking for.
DELTA_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "document": (("lines", "Lines"),),
    "section": (
        ("canonical", "Named sections"),
        ("duplicable", "Duplicable — `discourse.section_duplicate`"),
    ),
    "header": (
        ("standalone", "Standalone — `render.header_delete`"),
        ("renameable", "With another clinical name — `render.header_rename`"),
        ("substantive", "Substantive (body >= 60 chars)"),
        ("heading_lines", "All heading-shaped lines"),
    ),
    "break": (("paragraph", "Paragraph breaks"), ("line", "Line breaks")),
    "sentence": (("prose", "Prose"), ("layout", "Layout (lab rows, lists)")),
    "list_block": (("multi_item", "Two or more items — `render.list_to_prose`"),),
    "list_item": (("blocks", "Blocks they sit in"),),
    "space_run": (("chars_in_runs", "Characters inside the runs"),),
    "word_space": (("single_spaces", "All single spaces"),),
    "numeric_value": (
        ("total", "All numeric tokens"),
        ("spellable", "Spellable integers"),
    ),
    "clinical_content": (
        ("clinical", "Clinical — salience >= 0.50, or a curated drug"),
        ("non_clinical", "Non-clinical — ordinary English below that"),
        ("unmeasured", "Unmeasured — never seen often enough to score"),
    ),
    "token": (
        ("content", "Content tokens"),
        ("word", "Words"),
        ("word_min3", ">=3 chars — `input.typo`"),
        ("ocr_confusable", "Holding a confusable glyph"),
    ),
    "character": (
        ("alpha", "Alphabetic"),
        ("digit", "Digit"),
        ("whitespace", "Whitespace"),
        ("ocr_confusable", "Confusable positions — `input.ocr_confusion`"),
    ),
}


def _delta_fields(key: str, before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, str]]:
    """Sub-fields worth a row, in a fixed order per level."""
    return [(f, label) for f, label in DELTA_FIELDS.get(key, ()) if f in before and f in after]


def _pair(before: dict[str, Any], after: dict[str, Any], field_name: str) -> tuple[Any, ...]:
    """`(baseline median, corrupted median, delta median, (delta total, pct))`."""
    b, a = before.get(field_name) or {}, after.get(field_name) or {}
    b_med, a_med = b.get("median"), a.get("median")
    b_tot, a_tot = b.get("total"), a.get("total")
    d_med = a_med - b_med if isinstance(b_med, int) and isinstance(a_med, int) else None
    d_tot = a_tot - b_tot if isinstance(b_tot, int) and isinstance(a_tot, int) else None
    if isinstance(d_tot, int) and isinstance(b_tot, int) and b_tot:
        pct = f"{d_tot / b_tot:+.1%}"
    else:
        pct = "—"
    return b_med, a_med, d_med, (d_tot, pct)


def _signed(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:+,}" if value else "0"
    return str(value)


def section_inventory(payload: dict[str, Any], write: Any, top: int = 40) -> None:
    """Which named sections this corpus actually has, and how common each is.

    The header level says *how many* section headers a note carries; this says
    *which ones*, and it is the table a reader needs before targeting a section
    or interpreting a header corruption. Deleting 30% of headers in a corpus
    where `discharge_medications` is in 99% of notes is a different experiment
    from one where it is in 12%.

    `share of notes` is the useful column rather than the total: a section that
    appears twice in one note (two `hospital_course` blocks) is still one
    section that corpus has, and the body length says whether it is a heading
    with content under it or an empty slot a target would find nothing in.
    """
    presence = ((payload.get("by_level") or {}).get("section") or {}).get("canonical_presence")
    if not presence:
        return
    seen = {k: v for k, v in presence.items() if v.get("notes_with")}
    if not seen:
        return
    write("\n## Section inventory — which named sections this corpus has\n")
    declared = ((payload.get("by_level") or {}).get("section") or {}).get("canonical_declared")
    write(
        f"**{len(seen)} of {declared} declared canonical sections occur.** "
        "Absence is a fact about the corpus, not a missing row — the sections "
        "the lexicon knows and these notes never use are listed after the table.\n"
    )
    write("| section | kind | notes with it | share of notes | body chars, median |")
    write("|---|---|---:|---:|---:|")
    ordered = sorted(seen.items(), key=lambda kv: (-kv[1]["notes_with"], kv[0]))
    for name, row in ordered[:top]:
        write(
            f"| `{name}` | {row.get('kind', '')} | {row['notes_with']:,} "
            f"| {row['share_of_notes']:.3f} | {_n(row.get('body_chars_median'))} |"
        )
    if len(ordered) > top:
        write(f"\n_{len(ordered) - top} further sections occur less often; see the JSON._")
    absent = ((payload.get("by_level") or {}).get("section") or {}).get("canonical_absent") or []
    if absent:
        write("\n**Declared but never seen:** " + ", ".join(f"`{a}`" for a in absent))
    unknown = ((payload.get("by_level") or {}).get("section") or {}).get(
        "non_canonical_ids_seen"
    ) or []
    if unknown:
        write(
            "\n**Seen but not in the lexicon:** "
            + ", ".join(f"`{u}`" for u in unknown[:15])
            + " — these are template headers the lexicon is behind on, which is a "
            "property of the lexicon rather than of the notes."
        )


__all__ = [
    "INDENT",
    "LEVEL_LABELS",
    "delta_table",
    "render",
    "section_inventory",
    "table1",
    "table2",
]
