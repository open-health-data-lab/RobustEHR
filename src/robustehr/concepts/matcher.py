"""Concept-level matching: spans, not tokens.

Word-level lookup answers *is this token in a vocabulary*. That question has no
good answer, for reasons measured at length elsewhere: ``chest`` and ``pain`` are
each ambiguous, ``stairs`` is a Disorder concept, ``one`` carries T033. Concept
matching answers a different and better-posed question — *does this span of text
mention a concept* — and most of the word-level failures disappear because they
were never mentions.

    chest pain            -> C0008031, one mention, Sign or Symptom
    atrial fibrillation   -> C0344434, one mention
    one                   -> no mention

It also returns a **CUI**, which is what the phenotype layer needs. A phenotype
is a curated set of concepts, not a semantic type, so "is this token associated
with heart failure" is answerable at this level and unanswerable at the last one.

**Reuse, not reimplementation.** The matcher is QuickUMLS (Soldaini & Goharian
2016) via ``medspacy-quickumls``: simstring approximate matching over an index
built from the local UMLS release. Writing our own would mean validating our own;
using theirs means citing a published evaluation and measuring only the delta.
See ``validation/protocol.md`` for exactly which parts of that validation
transfer and which do not.

**Determinism.** Matching is deterministic given a fixed index and fixed
parameters, so the reproducibility guarantee holds — but it is conditional in a
way word-level lookup was not, and the condition is recorded rather than assumed:
``threshold``, ``similarity_name`` and ``min_match_length`` all change what
matches, so they are pinned in :class:`MatcherConfig` and hashed into the run
manifest. Results are sorted into a canonical order before use, because a
matcher's iteration order is not part of its contract.

**One confound this package in particular must own.** QuickUMLS matching is
*approximate*: a corruption that perturbs a term can flip whether it matches. For
a package whose entire purpose is perturbing terms, that is a measurement target
rather than a footnote — the L0→L4 ablation is what quantifies it.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from robustehr.categories import categories_of, load_categories
from robustehr.types import Span

#: Where the locally built index lives by default. Derived from licensed UMLS
#: content, so it is gitignored and never travels with the package.
DEFAULT_INDEX = Path("data/quickumls_index")


@dataclass(frozen=True, slots=True)
class MatcherConfig:
    """Everything that changes what matches, pinned for the manifest.

    These are not tuning knobs to be adjusted per run. QuickUMLS's published
    validation is inherited only while the matching algorithm is untouched;
    changing any field here forfeits that and obliges a fresh evaluation, which
    is why they are recorded in the run manifest rather than left implicit.
    """

    threshold: float = 0.7
    similarity_name: str = "jaccard"
    overlapping_criteria: str = "score"
    min_match_length: int = 3
    window: int = 5
    accepted_semtypes: frozenset[str] | None = field(default=None)
    """Semantic types QuickUMLS may return. ``None`` keeps its own 27 defaults.

    Leaving this at ``None`` filters twice with two different filters, and the
    mismatch loses terms. ``wbc`` resolves to T025 Cell, which belongs to
    RobustEHR's ``anatomy`` category but is absent from QuickUMLS's defaults, so
    it was discarded before any category logic could see it.

    Note the asymmetry for inherited validation. *Narrowing* this filter yields a
    subset of the validated output and inherits QuickUMLS's evaluation;
    *widening* it past their defaults yields spans they never scored, and owes
    its own measurement like any other configuration change.
    """

    trim_affixes: bool = False
    """Strip leading and trailing function words from every matched span.

    Only meaningful with ``overlapping_criteria='length'``, and the reason that
    pairing exists. Preferring the longest match is what stops
    ``shortness of breath`` fragmenting into ``breath``, but it also lets a match
    run one word too far — ``and vitamin D deficiency`` for
    ``vitamin D deficiency``. Trimming closed-class affixes recovers the span
    without giving up the longer match, because no UMLS concept begins or ends
    with a conjunction.
    """

    preferred_cuis: frozenset[str] | None = field(default=None, compare=False)
    """Concepts to favour when candidates tie on similarity.

    A **tie-break only** — never a filter, and never able to promote a worse
    match over a better one. That restriction is what makes it safe: at equal
    similarity the choice among candidates was arbitrary anyway (we broke it by
    CUI, i.e. alphabetically), so replacing an arbitrary rule with an informed
    one cannot cost accuracy.

    The case it was built for: gold marks ``diabetes`` as *Diabetes Mellitus*
    (C0011849) and we returned C0011847, *Diabetes* — a concept with **no SNOMED
    code at all**, absent from the SNOMED hierarchy entirely. A concept outside
    SNOMED cannot be a member of a SNOMED-seeded phenotype set under any closure,
    so preferring a SNOMED-linked candidate at equal similarity is free.

    Supplied by the caller rather than loaded here, so the matcher stays
    independent of which vocabulary a particular study cares about.
    """

    def canon(self) -> str:
        semtypes = "default" if self.accepted_semtypes is None else str(len(self.accepted_semtypes))
        preferred = "none" if self.preferred_cuis is None else str(len(self.preferred_cuis))
        return (
            f"quickumls:{self.similarity_name}:{self.threshold}:"
            f"{self.min_match_length}:{self.window}:{self.overlapping_criteria}:"
            f"semtypes={semtypes}:trim={int(self.trim_affixes)}:prefer={preferred}"
        )


@dataclass(frozen=True, slots=True)
class Mention:
    """One concept mention: a span of text linked to a UMLS concept."""

    span: Span
    cui: str
    tuis: frozenset[str]
    similarity: float
    surface: str = field(compare=False, default="")

    @property
    def categories(self) -> frozenset[str]:
        return categories_of(self.tuis)

    @property
    def is_exact(self) -> bool:
        """Did the surface match the terminology exactly?

        Worth separating: an approximate match on already-corrupted text is
        weaker evidence than an exact one, and the difference is the confound
        the ablation exists to measure.
        """
        return self.similarity >= 1.0


@dataclass(frozen=True, slots=True)
class MentionIndex:
    """Concept mentions over one document, queryable by span."""

    mentions: tuple[Mention, ...]

    def overlapping(self, span: Span) -> tuple[Mention, ...]:
        return tuple(m for m in self.mentions if m.span.overlaps(span))

    def semantic_types(self, span: Span) -> frozenset[str]:
        out: set[str] = set()
        for mention in self.overlapping(span):
            out |= mention.tuis
        return frozenset(out)

    def categories(self, span: Span) -> frozenset[str]:
        return categories_of(self.semantic_types(span))

    def __len__(self) -> int:
        return len(self.mentions)


def index_present(path: Path) -> bool:
    """Is there a QuickUMLS index at ``path``, as opposed to a placeholder?

    ``data/quickumls_index/`` ships as a directory holding only a README that
    says how to build the index, so ``path.exists()`` is true on every fresh
    clone. An index is present when the directory holds anything else — the
    installer writes ``language.flag`` and two databases — so a README-only
    directory reports absent and gets the same message a missing one does.
    """
    if not path.is_dir():
        return False
    return any(child.name != "README.md" for child in path.iterdir())


def quickumls_available() -> bool:
    """Is the `terminology` extra actually importable?

    Checked separately from whether the index exists, because those fail for
    different reasons and only one of them is the user's data; an index present
    without the package would otherwise raise `ModuleNotFoundError` from
    `annotate`, several frames below the command the user typed.
    """
    return importlib.util.find_spec("quickumls") is not None


class ConceptMatcher:
    """Wraps QuickUMLS and returns mentions in a canonical order."""

    def __init__(
        self,
        index: Path = DEFAULT_INDEX,
        config: MatcherConfig | None = None,
        *,
        align_semtypes: bool = True,
    ) -> None:
        # Resolved here, not at load time: the load guard changes directory, so
        # a relative path would resolve against the wrong root.
        self.index = Path(index).resolve()
        config = config or MatcherConfig()
        if align_semtypes and config.accepted_semtypes is None:
            # Align QuickUMLS's filter with RobustEHR's categories. Left at
            # their defaults the two filters disagree and the mismatch silently
            # loses terms: `wbc` is T025 Cell, which belongs to our `anatomy`
            # but not to their 27, so it was discarded before any category logic
            # could see it. Measured on the challenge, alignment raises category
            # recall from 0.559 to 0.570.
            config = replace(config, accepted_semtypes=default_semtypes())
        self.config = config
        if not quickumls_available():
            raise ModuleNotFoundError(
                "concept matching needs the terminology extra: "
                "pip install 'robustehr[terminology]'. Structural levels need no "
                "terminology and are measured without it."
            )
        if not index_present(self.index):
            raise FileNotFoundError(
                f"no QuickUMLS index at {self.index}. Build one with "
                f"`python -m quickumls.install -L -U -E ENG <umls>/META {self.index}`"
            )
        self._matcher: Any = None

    def _load(self) -> Any:
        if self._matcher is None:
            # The guard has to cover construction as well as import: nltk's
            # dependencies load lazily, so `defusedxml` arrives when QuickUMLS
            # is instantiated rather than when it is imported.
            with _neutral_cwd():
                from quickumls import QuickUMLS

                self._matcher = QuickUMLS(
                    str(self.index),
                    threshold=self.config.threshold,
                    similarity_name=self.config.similarity_name,
                    overlapping_criteria=self.config.overlapping_criteria,
                    min_match_length=self.config.min_match_length,
                    window=self.config.window,
                    **(
                        {"accepted_semtypes": set(self.config.accepted_semtypes)}
                        if self.config.accepted_semtypes is not None
                        else {}
                    ),
                )
        return self._matcher

    def annotate(self, text: str) -> MentionIndex:
        """Find concept mentions, best match per span, in document order.

        ``best_match=True`` resolves overlaps so that ``chest pain`` wins over
        ``chest`` and ``pain`` separately — the longest-match behaviour that is
        the whole point of matching spans rather than tokens.
        """
        groups = self._load().match(text, best_match=True, ignore_syntax=False)
        mentions = []
        for group in groups:
            if not group:
                continue
            # A group is candidate concepts for one span, ranked by similarity.
            # Sorting explicitly rather than trusting iteration order: the
            # matcher's ordering is not part of its contract, and this feeds a
            # reproducibility claim.
            best = sorted(group, key=self._rank)[0]
            span = Span(int(best["start"]), int(best["end"]))
            if self.config.trim_affixes:
                trimmed = trim_function_affixes(span, text)
                if trimmed is None:
                    continue
                if trimmed != span:
                    best = self._rematch(text, trimmed, best)
                span = trimmed
            mentions.append(
                Mention(
                    span=span,
                    cui=str(best["cui"]),
                    tuis=frozenset(str(t) for t in best["semtypes"]),
                    similarity=float(best["similarity"]),
                    surface=text[span.start : span.end],
                )
            )
        mentions.sort(key=lambda m: (m.span.start, m.span.end, m.cui))
        return MentionIndex(tuple(mentions))

    def _rematch(self, text: str, span: Span, current: dict[str, Any]) -> dict[str, Any]:
        """Re-query a trimmed span, and keep the better concept.

        Trimming alone fixes the span but not the concept, and the concept was
        the thing that went wrong. Under ``overlapping_criteria='length'``
        QuickUMLS prefers the longest ngram *before* comparing similarity, so a
        longer approximate match displaces a shorter exact one: in
        ``her chest pain`` it returns C0029537 at 0.857 and discards
        ``chest pain`` -> C0008031 at 1.000. The exact match is plainly the right
        answer, and it is unreachable because ``her`` was in the window.

        Re-running the matcher on the trimmed text recovers it. The replacement
        is accepted only on **strictly higher similarity**, so this can raise
        match quality and never lower it, and it runs only for spans that
        actually carried a function-word affix.
        """
        surface = text[span.start : span.end]
        candidates = [c for group in self._load().match(surface, best_match=True) for c in group]
        exact = [c for c in candidates if str(c["ngram"]) == surface]
        if not exact:
            return current
        better = sorted(exact, key=self._rank)[0]
        return better if float(better["similarity"]) > float(current["similarity"]) else current

    def _rank(self, candidate: dict[str, Any]) -> tuple[float, int, str]:
        """Candidate order: similarity first, then preference, then CUI.

        The final CUI term is not a preference — it is what makes the choice
        *reproducible* when everything above it ties. A matcher's own iteration
        order is not part of its contract, and this feeds a determinism claim.
        """
        preferred = self.config.preferred_cuis
        cui = str(candidate["cui"])
        rank = 0 if preferred is None or cui in preferred else 1
        return (-float(candidate["similarity"]), rank, cui)


#: Word characters for affix trimming. Explicit rather than ``\w``, which is
#: Unicode-dependent and therefore locale-dependent — banned by the AST lint for
#: exactly that reason.
_WORD = re.compile(r"[A-Za-z0-9]+")


def trim_function_affixes(span: Span, text: str) -> Span | None:
    """Drop leading and trailing closed-class words from a matched span.

    The correction for over-extension under ``overlapping_criteria='length'``.
    No UMLS concept starts or ends with a conjunction or determiner, so a match
    that does has run past the concept, and the extra token is the matcher's
    rather than the terminology's.

    Interior function words are untouched — ``shortness of breath`` keeps its
    ``of``, which is the whole reason the longest match was worth preferring.

    Returns ``None`` if nothing survives, which happens when the match was a
    function word outright; the caller drops the mention.
    """
    from robustehr.lexicon import load_morphology

    closed = load_morphology().closed_class
    inner = text[span.start : span.end]
    words = [(m.start() + span.start, m.end() + span.start) for m in _WORD.finditer(inner)]
    if not words:
        return None
    lo, hi = 0, len(words)
    while lo < hi and text[words[lo][0] : words[lo][1]].lower() in closed:
        lo += 1
    while hi > lo and text[words[hi - 1][0] : words[hi - 1][1]].lower() in closed:
        hi -= 1
    if lo >= hi:
        return None
    start, end = words[lo][0], words[hi - 1][1]
    return span if (start, end) == (span.start, span.end) else Span(start, end)


@contextmanager
def _neutral_cwd() -> Iterator[None]:
    """Import QuickUMLS from outside the project directory.

    QuickUMLS pulls in nltk, which installs a meta-path finder refusing any
    module whose file resolves to somewhere under the current working directory.
    The intent is to stop a stray ``regex.py`` in your working directory from
    shadowing the real one. The implementation tests
    ``Path(spec.origin).relative_to(Path.cwd())``, which is true for *anything*
    beneath the cwd — including ``.venv/`` when the virtualenv lives inside the
    project, which is the common layout and this project's.

    So every installed package looks like a working-directory module and the
    guard fires on ``regex``, then ``defusedxml``, then whatever nltk reaches
    for next. It cannot be sidestepped by removing the finder beforehand,
    because nltk installs it partway through its own import.

    Changing directory is the escape the guard itself anticipates — its source
    notes that the cwd is "resolved dynamically (respects process chdir)". The
    change is held for one import and restored in a finally, and matchers are
    loaded once and cached, so this runs at most twice per process.
    """
    import os
    import tempfile

    previous = os.getcwd()
    os.chdir(tempfile.gettempdir())
    try:
        yield
    finally:
        os.chdir(previous)


@lru_cache(maxsize=1)
def default_semtypes() -> frozenset[str]:
    """Every semantic type any RobustEHR category claims.

    The union rather than the default subset: a category excluded from
    ``clinical_any`` is still reachable by name, so the matcher has to return it.
    """
    return frozenset(t for c in load_categories().values() for t in c.tuis)


@lru_cache(maxsize=2)
def load_matcher(index: str = str(DEFAULT_INDEX)) -> ConceptMatcher:
    """Cached matcher. Loading the index costs seconds, so do it once."""
    return ConceptMatcher(Path(index))


__all__ = [
    "DEFAULT_INDEX",
    "ConceptMatcher",
    "MatcherConfig",
    "Mention",
    "MentionIndex",
    "default_semtypes",
    "load_matcher",
]
