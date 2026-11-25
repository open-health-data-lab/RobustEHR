"""Assertion qualification: is this mention negated, historical, someone else's?

Stage 8, and the last stage of the concept-matching pipeline. It answers a
question the previous stages deliberately do not: *given that this span mentions
pneumonia, is the note saying the patient has it?*

**Reuse, not reimplementation.** The instrument is medspaCy's ConText — an
implementation of Chapman's algorithm - published, evaluated, and widely used. The
rule this package applies to QuickUMLS applies here: cite an evaluated component
and measure only the delta, rather than write a rule set and owe a validation.

**It qualifies our spans, not its own.** ConText normally runs after its own
entity matcher; here the spans come from stages 5-7, so the two are separable and
this stage is measured on assertion alone rather than on detection plus
assertion. That is also why `medspacy_target_matcher` is absent from the
pipeline built below.

**An attribute, never a filter.** 30.1% of expert-annotated phenotype evidence is
non-affirmed, so this matters — but it matters for *reporting*. Neither
`phenotype_scope=protect` nor `=target` changes its eligibility decision based on
assertion: a negated mention is still a mention whose corruption changes what the
note says, and still phenotype-related text. So the assertion travels beside
`evidence_touch` and never in front of it. That is settled in
`docs/targeting-design.md` on the measurement, not on intuition.

**Determinism needs care that the AST lint cannot give.** spaCy pipelines
populate extensions in document order but expose them through structures whose
iteration order is not part of any contract, and the abbreviation work already
found scispaCy emitting in address order — eight processes, eight different
hashes. Everything here is sorted into a canonical order before it is returned.

**The five attributes are not peers, and must not be read as if they were.**
medspaCy's English set is 102 rules but **271 triggers** — a rule may carry a
token pattern matching a whole list, so rule count is the wrong unit:

===================  ====================  =====  ========  =====================
attribute            ConText category      rules  triggers  status
===================  ====================  =====  ========  =====================
``is_negated``       NEGATED_EXISTENCE        69       145  **validated**, 0.9289
``is_family``        FAMILY                    1        51  disclosed
``is_uncertain``     POSSIBLE_EXISTENCE       18        48  out-of-domain, 0.2511
``is_hypothetical``  HYPOTHETICAL              9        17  disclosed
``is_historical``    HISTORICAL                5        10  disclosed
===================  ====================  =====  ========  =====================

The one-rule FAMILY category carries a **51-term kinship list** from ``aunt`` to
``wife``, so *"Father with myocardial infarction"* **is** detected, which a rule
count would deny. By triggers the imbalance is roughly
14x rather than 69x, and experiencer is the second best resourced category.

What that does not change is the column that governs what may be claimed. Only
negation has *in-domain* gold — `assertion_accuracy.json`, against Chapman's
NegEx test set, where a majority-class baseline scores 0.7924 accuracy and this
stage scores 0.9696 at 0.9289 negated-class F1. Uncertainty has BioScope, whose
clinical subcorpus is de-worded, leaving biomedical abstracts:
`scope_accuracy.json` scores it 0.2511 at precision 0.855 and recall 0.147 —
precise where it fires, blind to six hedges in seven — with negation on the same
sentences (0.6111) as the control for the genre shift. `historical`,
`historical` and `family` have no gold in any domain.

There is also no PSEUDONEGATION category in the English set, so ``no change`` and
``not only`` are handled only by longest-match pruning, and no CONDITIONAL
category at all. The counts regenerate into `context_rule_inventory.json` from
the installed rule file, so they stay honest across medspaCy versions.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from robustehr.concepts.matcher import _neutral_cwd
from robustehr.document import Document
from robustehr.protect.registry import ProtectedSpan, Strength
from robustehr.resources import load_yaml
from robustehr.types import ProtectionClass, Span, Unit, UnitKind, make_unit_id

#: ConText attributes read from each qualified span, in a fixed order.
#:
#: Sorted and frozen rather than discovered, so a medspaCy version that adds an
#: attribute cannot silently widen what this package reports.
#:
#: See the module docstring before treating these as five comparable signals:
#: they rest on 69, 18, 9, 5 and 1 rules respectively, and only the first has
#: been validated against gold.
ATTRIBUTES = ("is_negated", "is_historical", "is_family", "is_hypothetical", "is_uncertain")

#: How each maps into the vocabulary the rest of the package uses.
#:
#: **Five ConText attributes, four reported dimensions.** `is_hypothetical` and
#: `is_uncertain` both map to ``uncertain``, and the merge is deliberate.
#:
#: This stage exists to modify the **asserted presence of a concept** — pneumonia
#: as *absent*, *possible*, or *someone else's*. For that purpose "hedged"
#: (`possible pneumonia`) and "conditional" (`Tylenol PRN`) are the same move:
#: neither asserts the thing is present now, and an operator flipping presence
#: does the same work in both.
#:
#: Keeping them apart also created a conflict nothing could resolve. The two are
#: cleanly separable *as judgements* — two independent annotators disagreed about
#: which applied on 1 span in 136 — but their **cue vocabulary is shared**:
#: ``may`` appears 134 times as hedge and 50 as permission, ``should`` 5 and 63,
#: ``can`` 13 and 27. A lexicon cannot assign those, so the split forced an
#: arbitrary majority-use choice on every shared modal.
#:
#: ConText's own categories are preserved on `Cue.category`, so the provenance of
#: any given decision is still recoverable; only the reported dimension merges.
_NAMES = {
    "is_negated": "negated",
    "is_historical": "historical",
    "is_family": "family",
    "is_hypothetical": "uncertain",
    "is_uncertain": "uncertain",
}

#: The reported dimensions, deduplicated and order-stable. Callers must use this
#: rather than ``_NAMES.values()``, which now contains ``uncertain`` twice.
DIMENSIONS = tuple(dict.fromkeys(_NAMES.values()))


@dataclass(frozen=True, slots=True)
class Cue:
    """The modifier that decided an assertion, and the scope it took.

    ConText computes all of this, and keeping it is what gives
    `ProtectionClass.ASSERTION_CUE` and `UnitKind.ASSERTION` a producer: a flip
    operator needs to know *which characters* to rewrite, not merely that a span
    was negated, and cannot compute a dose otherwise.
    """

    category: str
    """ConText's own category, e.g. ``NEGATED_EXISTENCE``. Not remapped: this is
    provenance, and it should name what the rule file names."""
    direction: str
    literal: str
    """The rule that fired, e.g. ``deny``. Its identity for a shared rule table."""
    span: Span
    """The cue text itself — what a rewrite operator edits."""
    scope: Span
    """How far the cue reached. The confound `assertion_stability` measures lives
    here: a segmentation change moves this, and the verdict moves with it."""

    def canon(self) -> str:
        return f"{self.category}:{self.literal}@{self.span.start}-{self.span.end}"


@dataclass(frozen=True, slots=True)
class Assertion:
    """What ConText concluded about one span."""

    span: Span
    attributes: frozenset[str]
    """Empty means affirmed. Sorted on the way out, never a set literal.

    Empty here means *qualified and affirmed*. A span the pipeline never
    qualified does not appear in the index at all — see `AssertionIndex`."""
    cues: tuple[Cue, ...] = ()
    """The modifiers that produced `attributes`, in canonical order."""

    @property
    def affirmed(self) -> bool:
        return not self.attributes

    def canon(self) -> str:
        return "affirmed" if self.affirmed else "+".join(sorted(self.attributes))


@dataclass(frozen=True, slots=True)
class AssertionIndex:
    """Assertions over one document, queryable by span.

    **Absence is not affirmation.** `qualify` drops a span when spaCy cannot
    convert its offsets or when a wider span already covers it, so "not in this
    index" means *unknown*, not *affirmed*. Conflating the two is the same
    vacuous-zero failure `dose.evidence_touch` was written to prevent one level
    up — a component that qualified nothing would otherwise report a perfect
    100% affirmed. `requested_n` and `coverage` exist so a caller can tell.
    """

    assertions: tuple[Assertion, ...] = ()
    requested_n: int = 0
    """Distinct spans handed to `qualify`, whether or not they were qualified."""
    _by_span: dict[tuple[int, int], Assertion] = field(
        default_factory=dict, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        # Built once: `at()` runs per mention, and a linear scan is quadratic
        # at ~14,600 mentions a note.
        object.__setattr__(
            self, "_by_span", {(a.span.start, a.span.end): a for a in self.assertions}
        )

    def at(self, span: Span) -> Assertion | None:
        return self._by_span.get((span.start, span.end))

    def is_qualified(self, span: Span) -> bool:
        """Whether this span has a verdict at all. Check before trusting `affirmed`."""
        return (span.start, span.end) in self._by_span

    def attributes_for(self, span: Span) -> frozenset[str]:
        """Attributes, or empty for *either* affirmed or unqualified.

        Prefer `at()` or `is_qualified()` where the difference matters.
        """
        found = self.at(span)
        return found.attributes if found else frozenset()

    def as_map(self) -> dict[Span, frozenset[str]]:
        """Qualified spans only, in the shape `phenotype.index_document` wants."""
        return {a.span: a.attributes for a in self.assertions}

    @property
    def coverage(self) -> float | None:
        """Qualified share of what was requested. ``None`` when nothing was asked.

        Null rather than zero, per the project's null-is-not-zero rule: no
        request and total failure are different facts.
        """
        if not self.requested_n:
            return None
        return len(self.assertions) / self.requested_n

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {"affirmed": 0}
        for assertion in self.assertions:
            if assertion.affirmed:
                out["affirmed"] += 1
            for name in sorted(assertion.attributes):
                out[name] = out.get(name, 0) + 1
        return dict(sorted(out.items()))

    def __len__(self) -> int:
        return len(self.assertions)


def silence_pyrush() -> None:
    """Stop PyRuSH emitting a loguru DEBUG line per token.

    Module-level so the scripts that build their own medspaCy pipelines share it
    rather than each carrying a copy of the same try/except.
    """
    try:
        from loguru import logger

        logger.remove()
    except ImportError:  # pragma: no cover - loguru ships with medspacy
        pass


@lru_cache(maxsize=2)
def _pipeline(*, pyrush: bool = True) -> Any:
    """A ConText pipeline over spans we supply.

    ``medspacy_target_matcher`` is deliberately absent: the spans come from
    stages 5-7, so letting medspaCy find its own would measure detection and
    assertion together and this stage would inherit the other's errors.

    ``pyrush=False`` drops medspaCy's sentence splitter so `qualify` can install
    this package's own boundaries instead. That is the CTX-B rung: ConText scopes
    cues to a sentence, our segmenter is hand-written against clinical text where
    PyRuSH is measurably wrong, and `assertion_stability.json` shows the verdict
    moving with segmentation. Which one wins is a measurement, not an assumption
    — see `assertion_accuracy.json`.
    """
    silence_pyrush()
    # medspaCy pulls in QuickUMLS, which pulls in nltk, whose meta-path finder
    # refuses any module resolving under the cwd. Same escape ConceptMatcher uses.
    with _neutral_cwd():
        import medspacy

        enable = ["medspacy_pyrush", "medspacy_context"] if pyrush else ["medspacy_context"]
        return medspacy.load(medspacy_enable=enable)


def medspacy_available() -> bool:
    """Is the `clinical` extra actually importable?

    Checked here rather than by each caller. `medspacy` is imported inside
    `_pipeline`, so `import robustehr.concepts.context` succeeds whether or not
    the extra is installed — which meant a caller guarding the *module* import
    with `except ImportError` caught nothing, and the failure surfaced from the
    call instead. `robustehr describe` crashed that way on a core install, while
    the README promised it needed no terminology at all.

    Degrading here means every caller inherits the documented behaviour and a
    new one cannot get it wrong.
    """
    return importlib.util.find_spec("medspacy") is not None


def _cues_for(doc: Any) -> dict[tuple[int, int], list[Cue]]:
    """Modifier→target edges, keyed by the target's character offsets.

    ConText reports `modifier_span` and `scope_span` as *token* index pairs, so
    both are converted back to character offsets here — every offset this package
    exposes is a character offset into the note as written.
    """
    out: dict[tuple[int, int], list[Cue]] = {}
    graph = getattr(doc._, "context_graph", None)
    if graph is None:  # pragma: no cover - context always sets it
        return out
    for target, modifier in graph.edges:
        cue_tokens = doc[modifier.modifier_span[0] : modifier.modifier_span[1]]
        scope_tokens = doc[modifier.scope_span[0] : modifier.scope_span[1]]
        out.setdefault((target.start_char, target.end_char), []).append(
            Cue(
                category=str(modifier.category),
                direction=str(modifier.direction),
                literal=str(modifier.rule.literal),
                span=Span(cue_tokens.start_char, cue_tokens.end_char),
                scope=Span(scope_tokens.start_char, scope_tokens.end_char),
            )
        )
    return out


EXTENSIONS_RESOURCE = "assertion_extensions.yaml"


#: Rule fields this package passes through to medspaCy beyond trigger, category,
#: direction and pattern. `max_scope` and `terminated_by` are the two knobs that
#: bound how far a cue reaches, so a resource rule declaring them must reach the
#: constructor rather than be dropped.
#:
#: `terminated_by` is not accepted by medspaCy's own JSON schema, only by the
#: `ConTextRule` constructor, so it is set after construction.
_RULE_FIELDS = ("max_scope", "max_targets", "allowed_types", "excluded_types")


def _build_rules(rules: tuple[dict[str, Any], ...]) -> list[Any]:
    """`ConTextRule` objects from this package's YAML schema.

    **The narrowest part of the system until now.** Only `literal`, `category`,
    `direction` and `pattern` crossed this boundary, so a rule could not say how
    far it reaches or what stops it — and scope, not vocabulary, is what the
    error analysis blames for most span-level failures.

    Note the direction default. medspaCy's own is `BIDIRECTIONAL`; this loader
    defaulted to `FORWARD`, which was an unmeasured choice, and 33 of the 66
    held-out false negatives on the three weak dimensions are a cue sitting
    *after* its target that a FORWARD rule can never reach. The default stays
    explicit here so it is a decision rather than an accident.
    """
    from medspacy.context import ConTextRule

    built = []
    for rule in rules:
        made = ConTextRule(
            literal=str(rule["literal"]),
            category=str(rule["category"]),
            direction=str(rule.get("direction", "FORWARD")),
            pattern=rule.get("pattern"),
            **{f: rule[f] for f in _RULE_FIELDS if rule.get(f) is not None},
        )
        if terminators := rule.get("terminated_by"):
            made.terminated_by = set(terminators)
        built.append(made)
    return built


def _extension_config() -> dict[str, Any]:
    """The shipped extension resource: cue rules plus the scope policy."""
    return dict(load_yaml(EXTENSIONS_RESOURCE))


def _apply_scope_policy(pipe: Any, policy: dict[str, Any]) -> None:
    """Install terminator rules and say which categories they cut.

    **Scope has to be per-category, and the sweep is why.** Feeding ConText a
    boundary at every line start lifts negation F1 by 0.029 on development and
    cuts its false positives from 23 to 10 — and costs `historical` 0.139 and
    `uncertain` 0.165, because a hedge legitimately reaches across a wrapped
    line where a negation does not. `boundaries=` is global, so it cannot
    express that; `ConTextRule.terminated_by` can.

    A terminator here is an ordinary FORWARD rule in its own category, **not** a
    `TERMINATE` rule. A TERMINATE rule cuts every modifier it overlaps, which is
    the global behaviour again; naming the category in `terminated_by` on the
    rules that should stop cuts only those. medspaCy compares
    ``other.category.upper() not in self.rule.terminated_by``, so the categories
    are upper-cased here rather than trusting the resource to do it.
    """
    from medspacy.context import ConTextRule

    terminators = policy.get("terminators") or []
    if terminators:
        pipe.add(
            [
                ConTextRule(
                    literal=str(rule["literal"]),
                    category=str(rule["category"]),
                    direction=str(rule.get("direction", "FORWARD")),
                    pattern=rule.get("pattern"),
                )
                for rule in terminators
            ]
        )
    table = {
        str(category).upper(): {str(t).upper() for t in cut_by}
        for category, cut_by in (policy.get("terminated_by") or {}).items()
    }
    for rule in pipe.rules:
        if extra := table.get(str(rule.category).upper()):
            rule.terminated_by = set(rule.terminated_by) | extra


@lru_cache(maxsize=8)
def _extended_pipeline(*, pyrush: bool = True, config: str | None = None) -> Any:
    """The ConText pipeline with this package's extra rules added.

    `config` is the extension resource as a JSON string, present only so a sweep
    can try a variant without rewriting the shipped file; `None` means the
    resource itself. **It is part of the cache key**: cached on `pyrush` alone,
    a later argument would silently reuse the first configuration built for
    every subsequent call.

    **Opt-in, because adding rules forfeits the inherited validation.** The
    argument this package applies to QuickUMLS applies to itself: a reused
    component may be cited, a modified one owes a number. So the stock arm stays
    the default and every measurement reports both.

    The extras exist because the MIMIC gold measured *what* was missing rather
    than guessing: `s/p`, `status post` and `nil` produce no cue at all in the
    stock set and occur 327 times across the sampled notes.

    **Built fresh, never by mutating the cached stock pipeline.** An earlier
    version called `_pipeline()` and added rules to the result — which, because
    that function is `lru_cache`d, permanently turned the stock arm into the
    extended one. Both arms then reported 105 rules and every stock-versus-
    extended comparison would have been a component compared with itself.
    """
    silence_pyrush()
    with _neutral_cwd():
        import medspacy

        enable = ["medspacy_pyrush", "medspacy_context"] if pyrush else ["medspacy_context"]
        nlp = medspacy.load(medspacy_enable=enable)

    import json as _json

    resource = _extension_config() if config is None else _json.loads(config)
    pipe = nlp.get_pipe("medspacy_context")
    pipe.add(_build_rules(tuple(resource.get("cues") or [])))
    _apply_scope_policy(pipe, dict(resource.get("scope") or {}))
    return nlp


def qualify(
    text: str,
    spans: tuple[Span, ...],
    *,
    boundaries: tuple[int, ...] | None = None,
    extended: bool = False,
    config: str | None = None,
) -> AssertionIndex:
    """Assert each span, in canonical order.

    Spans are installed as entities so ConText's cue-scope logic applies to
    them. Character offsets convert with ``alignment_mode='expand'`` because a
    span may begin mid-token where our tokenizer and spaCy's disagree, and
    overlapping entities are rejected by spaCy, so nested spans are resolved by
    keeping the widest at each position rather than dropping the document.

    ``boundaries`` are character offsets at which a sentence starts. Supplying
    them replaces PyRuSH with this package's segmenter (the CTX-B rung); omitting
    them keeps medspaCy's default (CTX-A). A boundary that does not fall on a
    token start is ignored rather than forced, because a mid-token split would
    change tokenization and make the two arms incomparable.

    Spans that cannot be converted or that a wider span already covers are
    **absent from the result**, not silently affirmed; `AssertionIndex.coverage`
    reports how many were lost.
    """
    if not spans:
        return AssertionIndex()
    if not medspacy_available():
        # No clinical extra: return an empty index rather than raising, which is
        # the same degradation `mention_index` gives with no UMLS index.
        return AssertionIndex(requested_n=len(spans))
    nlp = (
        _extended_pipeline(pyrush=boundaries is None, config=config)
        if extended
        else _pipeline(pyrush=boundaries is None)
    )
    doc = nlp.make_doc(text)

    if boundaries is not None:
        starts = set(boundaries)
        for token in doc:
            token.is_sent_start = token.idx in starts
        if len(doc):  # spaCy requires the first token to open a sentence
            doc[0].is_sent_start = True

    wanted = sorted(set(spans), key=lambda s: (s.start, -s.end))
    kept: list[Any] = []
    for span in wanted:
        converted = doc.char_span(span.start, span.end, label="MENTION", alignment_mode="expand")
        if converted is None:
            continue
        if any(converted.start < e.end and e.start < converted.end for e in kept):
            continue
        kept.append(converted)
    doc.ents = kept
    for _, proc in nlp.pipeline:
        doc = proc(doc)

    by_target = _cues_for(doc)
    found = [
        Assertion(
            span=Span(ent.start_char, ent.end_char),
            attributes=frozenset(_NAMES[a] for a in ATTRIBUTES if bool(getattr(ent._, a, False))),
            cues=tuple(
                sorted(
                    by_target.get((ent.start_char, ent.end_char), ()),
                    key=lambda c: (c.span.start, c.span.end, c.category, c.literal),
                )
            ),
        )
        for ent in doc.ents
        if ent.label_ == "MENTION"
    ]
    # Canonical order. A pipeline's emission order is not part of its contract,
    # and this feeds a reproducibility claim.
    found.sort(key=lambda a: (a.span.start, a.span.end, a.canon()))
    return AssertionIndex(tuple(found), requested_n=len(wanted))


@lru_cache(maxsize=4)
def cues_in(
    text: str,
    *,
    boundaries: tuple[int, ...] | None = None,
    extended: bool = False,
    config: str | None = None,
) -> tuple[Cue, ...]:
    """Every assertion cue in a document, independent of any target span.

    **Memoized on its whole argument tuple**, which is safe in a way the
    pipeline caches above are not: this is a pure function of its inputs and
    returns an immutable tuple, so a cached result cannot be mutated by a later
    caller the way a cached spaCy pipeline could. The four cue-flip operators
    each call this with identical arguments while enumerating the same note, and
    an experiment aiming them at fifteen phenotypes in turn does so sixty times
    per note -- sixty identical ConText passes over one discharge summary. The
    cache holds four notes, which bounds it at a few hundred kilobytes.

    `cues` reports the cues that actually *governed* a mention, which is the
    right denominator when relating assertions to concepts. This reports the
    cues that are *present*, which is the right denominator for an operator:
    ``denies`` is editable whether or not a UMLS concept happens to follow it,
    and an operator whose eligibility depended on the matcher would silently
    shrink on a document the matcher covered poorly.

    It also means the SEMANTIC channel needs **medspaCy only** — no UMLS index,
    no QuickUMLS, no terminology licence. ConText populates
    ``context_graph.modifiers`` from the rule set alone; only the modifier →
    target *edges* require entities, and those are not consulted here.
    """
    if not medspacy_available():
        # No clinical extra: report no cues rather than raising, so Table 1's
        # assertion level reports zero and the SEMANTIC operators find zero
        # eligible units. Both are the documented degradation.
        return ()
    nlp = (
        _extended_pipeline(pyrush=boundaries is None, config=config)
        if extended
        else _pipeline(pyrush=boundaries is None)
    )
    doc = nlp.make_doc(text)
    if boundaries is not None:
        starts = set(boundaries)
        for token in doc:
            token.is_sent_start = token.idx in starts
        if len(doc):
            doc[0].is_sent_start = True
    doc.ents = []
    for _, proc in nlp.pipeline:
        doc = proc(doc)

    graph = getattr(doc._, "context_graph", None)
    if graph is None:  # pragma: no cover - context always sets it
        return ()
    found = [
        Cue(
            category=str(modifier.category),
            direction=str(modifier.direction),
            literal=str(modifier.rule.literal),
            span=Span(
                doc[modifier.modifier_span[0] : modifier.modifier_span[1]].start_char,
                doc[modifier.modifier_span[0] : modifier.modifier_span[1]].end_char,
            ),
            scope=Span(
                doc[modifier.scope_span[0] : modifier.scope_span[1]].start_char,
                doc[modifier.scope_span[0] : modifier.scope_span[1]].end_char,
            ),
        )
        for modifier in graph.modifiers
    ]
    return tuple(sorted(found, key=lambda c: (c.span.start, c.span.end, c.category, c.literal)))


def cues(index: AssertionIndex) -> tuple[Cue, ...]:
    """Every distinct cue in the document, deduplicated and in canonical order.

    One cue commonly governs several targets — *"Denies chest pain, shortness of
    breath, and fever"* is one ``deny`` over three mentions — so the cue list is
    shorter than the assertion list and it is the cue list that a rewriting
    operator enumerates. Deduplicated on the cue span rather than on identity,
    because the same rule firing at two places is two cues.
    """
    seen: dict[tuple[int, int], Cue] = {}
    for assertion in index.assertions:
        for cue in assertion.cues:
            seen.setdefault((cue.span.start, cue.span.end), cue)
    return tuple(
        sorted(seen.values(), key=lambda c: (c.span.start, c.span.end, c.category, c.literal))
    )


def cue_units(index: AssertionIndex) -> list[Unit]:
    """Assertion cues as eligible units — the dose denominator for stage 8.

    ``UnitKind.ASSERTION`` was declared in `types.py` with no producer, so
    `runner` could not compute ``requested_k`` for any SEMANTIC operator and the
    whole channel was blocked on this function. The four planned operators
    (`negation_flip`, `uncertainty_flip`, `temporality_shift`,
    `experiencer_shift`) each enumerate from here, then propose an edit over the
    cue span.

    The unit id is content-addressed on the cue's own text and category, not on
    its offsets alone, so that inserting a sentence earlier in the note changes
    that sentence's fate and leaves every other cue's selection untouched.
    """
    return [
        Unit(make_unit_id(UnitKind.ASSERTION, cue.span), UnitKind.ASSERTION, cue.span)
        for cue in cues(index)
    ]


def cue_protections(index: AssertionIndex) -> list[ProtectedSpan]:
    """Assertion cues as protection entries.

    **SOFT, and the reason differs from phenotype evidence.** A cue is not
    sensitive; it is *load-bearing*. Corrupting ``no`` in ``no evidence of
    pneumonia`` does not damage a span the reader cares about — it silently
    reverses the note's meaning, which turns a formatting perturbation into a
    factual one and breaks the contract lattice the whole package rests on. So
    a cue is withheld from operators that have not declared
    ``ASSERTION_CUE`` as a target, and reachable by the SEMANTIC operators that
    have, which is exactly what they exist to edit.
    """
    return [
        ProtectedSpan(
            span=cue.span,
            cls=ProtectionClass.ASSERTION_CUE,
            strength=Strength.SOFT,
            reason=f"{cue.category} cue {cue.literal!r} scoping {cue.scope.start}-{cue.scope.end}",
        )
        for cue in cues(index)
    ]


#: Structural relations, narrowest first. A cue and a target sitting in
#: different units of any of these cannot plausibly govern one another, and the
#: first match is reported because the narrowest separation is the informative
#: one — "different sections" says less than "different rows of a lab table".
_SEPARATIONS = ("list item", "aligned-block row", "line", "section")


def _list_item_of(doc: Document, offset: int) -> tuple[int, int] | None:
    """``(block, item)`` for the list item containing ``offset``, if any."""
    for block in doc.lists:
        for position, item in enumerate(block.items):
            if item.content.start <= offset < item.content.end:
                return (block.idx, position)
    return None


def _line_of(doc: Document, offset: int) -> int | None:
    for line in doc.lines.lines:
        if line.span.start <= offset <= line.span.end:
            return line.idx
    return None


def _section_of(doc: Document, offset: int) -> int | None:
    for section in doc.sections:
        if section.full.start <= offset < section.full.end:
            return section.idx
    return None


def _aligned_lines(doc: Document) -> frozenset[int]:
    """Line indices belonging to a table, lab block or other aligned block."""
    return frozenset(line for block in doc.aligned for line in block.lines)


def separation(doc: Document, cue: Span, target: Span) -> str | None:
    """Why the note's *structure* says this cue cannot govern this target.

    ``None`` means the structure does not object — the two share whatever units
    exist, and whether the cue applies is a question for the scope algorithm
    rather than for the layout.

    **This is a referee, not a detector.** ConText scopes cues to sentences, and
    a sentence in a discharge summary routinely spans a whole lab block or a
    bulleted problem list, because the text has no punctuation to split on. When
    that happens a single ``no`` reaches every mention below it. Measured on the
    held-out gold, **24 of 41 false positives had the cue and the target on
    different lines** — so layout, which the note's author used deliberately, is
    carrying a boundary the sentence splitter cannot see.

    Promoted from `validation/pipeline/scripts/assertion_disagreement.py`, where it adjudicated one
    segmenter against another, and widened from list items to lines and aligned
    blocks so it can adjudicate a prediction against gold.
    """
    cue_item, target_item = _list_item_of(doc, cue.start), _list_item_of(doc, target.start)
    if cue_item is not None and target_item is not None and cue_item != target_item:
        return "different list items"
    if (cue_item is None) != (target_item is None):
        return "one inside a list item, one outside"
    cue_line, target_line = _line_of(doc, cue.start), _line_of(doc, target.start)
    if cue_line != target_line:
        aligned = _aligned_lines(doc)
        if cue_line in aligned or target_line in aligned:
            return "different rows of an aligned block"
        return "different lines"
    if _section_of(doc, cue.start) != _section_of(doc, target.start):
        return "different sections"
    return None


__all__ = [
    "ATTRIBUTES",
    "DIMENSIONS",
    "Assertion",
    "AssertionIndex",
    "Cue",
    "cue_protections",
    "cue_units",
    "cues",
    "cues_in",
    "qualify",
    "separation",
]
