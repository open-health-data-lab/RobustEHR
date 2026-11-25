"""The Document Quality Profile: how degraded is this note already?

Every dose figure this package produces is uninterpretable without it. A note
arrives with misspellings, inconsistent headers, ragged wrapping and
de-identification residue, and a robustness result that ignores that is
attributing to the operator whatever the note brought with it.

**The profile is a stratifier, never an addend.** Adding "existing noise" to
"injected noise" produces a quantity that means nothing: the two are measured on
different scales, over different denominators, and one of them is a property of
the corpus rather than of the experiment. Results are stratified by baseline
tertile instead. The hypothesis this exists to test is that already-degraded
notes are more fragile — if true that is a finding, and it cannot be tested at
all without measuring baseline separately.

**Reported as a profile, not a score.** A single number hides which dimension
drove it, and the dimensions behave differently: a note can be lexically clean
and structurally chaotic, or the reverse, and those degrade a downstream model in
different ways. A composite is offered for convenience in stratification, and the
components are what get reported.

Three dimensions, each a rate over an explicit denominator:

* **lexical** — misspellings and unresolvable tokens
* **structural** — wrapping, whitespace, header consistency
* **deidentification** — mask density and scheme consistency
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction

from robustehr.document import Document
from robustehr.dose import ratio
from robustehr.lexical import LexicalClass, classify_lexical
from robustehr.lexicon import DEFAULT_LEXICON, Lexicon
from robustehr.segment.tokens import TokenKind

#: Shortest token treated as a candidate misspelling. Below this, an unknown
#: alphabetic string is far more likely an abbreviation or an initial than a
#: misspelled word, and the abbreviation resolver owns those.
MIN_MISSPELLING_LENGTH = 4

#: Corpus frequency at or below which an unrecognized token is treated as a
#: probable misspelling.
#:
#: Calibrated by inspection, and the calibration matters because the naive
#: version of this metric was wrong. Counting every unrecognized token as a
#: misspelling put ``daily`` (2,627 occurrences), ``tablet`` (2,390),
#: ``refills``, ``acute``, ``stable`` and ``bilateral`` at the top — clinical
#: and administrative vocabulary that is simply absent from both lexicons.
#: Restricting to hapax legomena leaves ``abdmoninal``, ``abdomnial``,
#: ``abdompen``, ``abnomalities`` and ``abnomral``, which is what was wanted.
#:
#: A word used once in a corpus of hundreds of notes is a typo; a word used
#: 2,000 times is vocabulary, however unrecognized.
MAX_MISSPELLING_FREQUENCY = 1

#: Runs of this many spaces or more count as whitespace noise rather than as
#: ordinary separation. Three, because two spaces after a full stop is a
#: convention rather than a defect.
WHITESPACE_RUN = 3


@dataclass(frozen=True, slots=True)
class QualityProfile:
    """Per-note baseline degradation, as exact counts plus derived rates.

    Counts rather than floats for the same reason the dose record uses them:
    a rate with no denominator cannot be pooled across notes, and a float is not
    byte-reproducible across platforms.
    """

    note_uid: str
    note_sha256: str

    # -- denominators ------------------------------------------------------
    content_tokens: int
    lines: int
    chars: int

    # -- lexical -----------------------------------------------------------
    unrecognized: int
    """Alphabetic content tokens in neither lexicon nor any semantic category.

    A quality signal in its own right — a note dense with tokens no resource
    recognises is degraded whether the cause is typing, jargon or de-identifi-
    cation residue — but **not** a misspelling count. Measured on 200 notes it
    is dominated by vocabulary rather than errors: ``daily``, ``tablet``,
    ``acute``, ``bilateral``.

    Note that ``warfarin`` does *not* count here: it is unknown to general
    English but carries a medication type, so the category check excludes it.
    """

    # -- structural --------------------------------------------------------
    whitespace_runs: int
    """Runs of >= WHITESPACE_RUN spaces — a marker of column layout leaking into prose."""
    wrap_width: int
    """Detected hard-wrap column, or 0 if the note is not hard-wrapped.

    Reported rather than reduced to a boolean because the width itself matters:
    a note wrapped at 65 and one wrapped at 80 present different sentence
    boundaries to a downstream segmenter.
    """
    ragged_line_variance: int
    """Population variance of line length, in characters. Integer for exactness."""
    header_styles: int
    """Distinct header grammars in one document. More than one means the note
    was assembled from several templates or authors."""

    # -- de-identification -------------------------------------------------
    deid_placeholders: int
    deid_schemes: int
    """Distinct masking conventions. More than one is itself a data-quality
    signal, and it changes how a downstream segmenter behaves."""
    suspected_misspellings: int | None = None
    """Unrecognized tokens rare enough in the corpus to be probable typos.

    ``None`` when no corpus frequency was supplied, because a single note
    cannot distinguish a typo from a term — both appear once. Requiring corpus
    context is what makes this a measurement rather than a guess, and reporting
    ``None`` rather than falling back to ``unrecognized`` keeps the two from
    being confused.
    """
    lexicon_source: str = "morphology-only"

    # -- derived rates -----------------------------------------------------

    @property
    def misspelling_rate(self) -> Fraction | None:
        """``None`` unless corpus frequencies were supplied — see the field."""
        if self.suspected_misspellings is None:
            return None
        return ratio(self.suspected_misspellings, self.content_tokens)

    @property
    def unrecognized_rate(self) -> Fraction | None:
        return ratio(self.unrecognized, self.content_tokens)

    @property
    def whitespace_noise_rate(self) -> Fraction | None:
        """Whitespace runs per line, so long notes are not penalised."""
        return ratio(self.whitespace_runs, self.lines)

    @property
    def is_hard_wrapped(self) -> bool:
        return self.wrap_width > 0

    @property
    def deid_density(self) -> Fraction | None:
        return ratio(self.deid_placeholders, self.content_tokens)

    @property
    def is_measured(self) -> bool:
        """Did a terminology inform the lexical dimension?

        Without one, ``suspected_misspellings`` counts every clinical term as a
        misspelling and the lexical dimension is meaningless. Reported so a
        consumer can drop it rather than average it in.
        """
        return self.lexicon_source != "morphology-only"

    def to_row(self) -> dict[str, object]:
        def pair(value: Fraction | None) -> tuple[int, int] | None:
            return None if value is None else (value.numerator, value.denominator)

        return {
            "note_uid": self.note_uid,
            "note_sha256": self.note_sha256,
            "content_tokens": self.content_tokens,
            "lines": self.lines,
            "chars": self.chars,
            "unrecognized": self.unrecognized,
            "suspected_misspellings": self.suspected_misspellings,
            "whitespace_runs": self.whitespace_runs,
            "wrap_width": self.wrap_width,
            "ragged_line_variance": self.ragged_line_variance,
            "header_styles": self.header_styles,
            "deid_placeholders": self.deid_placeholders,
            "deid_schemes": self.deid_schemes,
            "misspelling_rate": pair(self.misspelling_rate),
            "unrecognized_rate": pair(self.unrecognized_rate),
            "whitespace_noise_rate": pair(self.whitespace_noise_rate),
            "is_hard_wrapped": self.is_hard_wrapped,
            "deid_density": pair(self.deid_density),
            "lexicon_source": self.lexicon_source,
            "is_measured": self.is_measured,
        }


def unrecognized_words(doc: Document, lexicon: Lexicon) -> list[str]:
    """Alphabetic content words no resource recognises, in document order."""
    out = []
    for token in doc.tokens:
        if not token.is_content or token.kind is not TokenKind.WORD:
            continue
        word = token.lower
        if classify_lexical(word) is not LexicalClass.OUT_OF_VOCABULARY:
            continue
        if lexicon.categories(word):
            continue  # recognised clinical vocabulary, not a defect
        out.append(word)
    return out


def corpus_frequencies(docs: Iterable[Document], lexicon: Lexicon) -> Counter[str]:
    """Count unrecognized words across a corpus, for the misspelling estimate."""
    counts: Counter[str] = Counter()
    for doc in docs:
        counts.update(unrecognized_words(doc, lexicon))
    return counts


def profile(
    doc: Document,
    lexicon: Lexicon = DEFAULT_LEXICON,
    frequencies: Mapping[str, int] | None = None,
) -> QualityProfile:
    """Measure a note's baseline degradation, before any operator runs.

    ``frequencies`` comes from :func:`corpus_frequencies` over the corpus this
    note belongs to. Without it the misspelling estimate is reported as ``None``
    rather than guessed.
    """
    content = [t for t in doc.tokens if t.is_content]
    unknown = unrecognized_words(doc, lexicon)
    misspellings: int | None = None
    if frequencies is not None:
        misspellings = sum(
            1
            for w in unknown
            if w.isalpha()
            and len(w) >= MIN_MISSPELLING_LENGTH
            and frequencies.get(w, 0) <= MAX_MISSPELLING_FREQUENCY
        )

    lengths = [
        doc.lines[i].span.end - doc.lines[i].span.start
        for i in range(len(doc.lines))
        if not doc.lines[i].is_blank
    ] or [0]
    variance = int(statistics.pvariance(lengths)) if len(lengths) > 1 else 0

    return QualityProfile(
        note_uid=doc.uid,
        note_sha256=doc.sha256,
        content_tokens=len(content),
        lines=len(doc.lines),
        chars=len(doc.text),
        unrecognized=len(unknown),
        suspected_misspellings=misspellings,
        whitespace_runs=_whitespace_runs(doc.text),
        wrap_width=doc.view.wrap_width or 0,
        ragged_line_variance=variance,
        header_styles=len({h.kind for h in doc.headers}),
        deid_placeholders=doc.deid.count,
        deid_schemes=sum(1 for n in doc.deid.scheme_counts.values() if n),
        lexicon_source=lexicon.source,
    )


def _whitespace_runs(text: str, minimum: int = WHITESPACE_RUN) -> int:
    runs = 0
    current = 0
    for char in text:
        if char == " ":
            current += 1
        else:
            if current >= minimum:
                runs += 1
            current = 0
    return runs + (1 if current >= minimum else 0)


def tertiles(values: list[Fraction]) -> tuple[Fraction, Fraction]:
    """Cut points for stratifying results by baseline degradation.

    Tertiles rather than a median split because the interesting comparison is
    cleanest-third against dirtiest-third; a median split dilutes both.
    """
    if not values:
        raise ValueError("no values to stratify")
    ordered = sorted(values)
    return (ordered[len(ordered) // 3], ordered[(2 * len(ordered)) // 3])


__all__ = [
    "MAX_MISSPELLING_FREQUENCY",
    "MIN_MISSPELLING_LENGTH",
    "WHITESPACE_RUN",
    "QualityProfile",
    "corpus_frequencies",
    "profile",
    "tertiles",
    "unrecognized_words",
]
