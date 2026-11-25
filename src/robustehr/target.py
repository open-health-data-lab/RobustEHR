"""What to corrupt.

Corruption mechanisms are target-agnostic: a typo is a typo whether it lands on
``the`` or on ``warfarin``, and character deletion does not know what it deleted.
That is not a weakness to be fixed — it is what makes the mechanisms reusable.
The value of the package is in **selecting what gets hit**, so targeting is a
composable specification rather than a flag on an operator.

One agnostic mechanism set then serves many experiments::

    Categories("medication")              # does drug extraction survive dictation error?
    Categories("disease")                 # is the classifier reading the diagnosis...
    Not(Categories("disease"))            # ...or the surrounding text?
    Uncategorized()                       # control: corrupt only non-content
    AllOf(Categories("disease"), Section("history_of_present_illness"))

Two design decisions worth stating, because both are expensive to change later.

**Targets are span-based, not token-based.** Word-level lookup answers
*token → semantic types*; concept matching answers *span → concept → semantic
types*. Writing this against tokens would mean rewriting it when concept matching
lands, so :class:`TargetContext` resolves a span and the matcher behind it can be
swapped without touching any target.

**Every target has a stable ``canon()``.** Scope canon feeds the BLAKE2b seed, so
the canonical string is not cosmetic: change it and you change which units get
selected, which changes every stored edit script. Canon strings are sorted and
deduplicated so that logically identical targets are textually identical.

There is no ``clinical`` target defined from a word's *intrinsic* properties.
"Is this token clinical" is not answerable independent of context and use case:
general-English frequency, source-vocabulary count and semantic group each
failed to separate ``one``, ``well`` and ``stairs`` from ``dyspnea``. What the
grammar offers instead is naming a category, or :class:`Uncategorized` for the
complement, and one *measured* rule, :class:`ClinicalSalience`, written
``clinical`` in a target: how often a token falls inside a human-adjudicated
clinical span, in one named corpus, plus three clauses the measurement showed
were needed. It separates those cases (precision 0.89 at 25% coverage against
0.50 at 46% for "any mention", on the SNOMED CT Entity Linking gold) and it is
a statement about MIMIC-IV discharge summaries with a number attached, not a
definition of "clinical"; it carries its benchmark in the manifest. See
``validation/protocol.md`` §9.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from robustehr.categories import load_categories, tuis_for
from robustehr.concepts.matcher import MentionIndex
from robustehr.concepts.phenotype import PhenotypeIndex
from robustehr.lexical import LexicalClass, classify_lexical, resolve_tags
from robustehr.lexicon import DEFAULT_LEXICON, Lexicon
from robustehr.protect import ProtectionIndex, build_index
from robustehr.types import ProtectionClass, Span

if TYPE_CHECKING:  # pragma: no cover
    from robustehr.concepts.context import AssertionIndex
    from robustehr.document import Document


@dataclass(frozen=True, slots=True)
class TargetContext:
    """What a target is allowed to consult when resolving a span.

    The indirection that lets the matcher change without touching any target.
    Today ``semantic_types`` reads word-level lookup; once concept matching lands
    it reads resolved mentions, and every target keeps working.
    """

    doc: Document
    lexicon: Lexicon = DEFAULT_LEXICON
    protection: ProtectionIndex = field(default_factory=lambda: build_index([]))
    phenotypes: PhenotypeIndex = field(default_factory=PhenotypeIndex)
    """Declared phenotypes and their evidence spans over this document.

    Empty by default, which is ``phenotype_scope=agnostic`` — the mode most runs
    use, where the clinical layer is skipped entirely and every RENDER, INPUT,
    LEXICAL and DISCOURSE operator still works at full fidelity.
    """
    mentions: MentionIndex | None = None
    """Concept mentions, when a matcher has annotated the document.

    This is the swap the span-based design existed for: supplying it changes
    every target from word-level to concept-level resolution without a single
    target changing. Absent, resolution falls back to token lookup, and
    ``resolution`` records which was used so a result says so.
    """
    assertions: AssertionIndex | None = None
    """ConText output, when stage 8 has qualified the document.

    Only :class:`Governs` consults it. Absent, that target admits nothing —
    the same refusal :class:`Concept` makes with no matcher, and the runner
    raises rather than letting it look like a corpus with no cues.
    """

    @property
    def resolution(self) -> str:
        """``concept`` or ``token``, plus ``+assertion`` — recorded, because they differ.

        The suffix appears only when an assertion index was supplied, so every
        row written before this existed stays byte-identical.
        """
        base = "concept" if self.mentions is not None else "token"
        return base + "+assertion" if self.assertions is not None else base

    def semantic_types(self, span: Span) -> frozenset[str]:
        """UMLS semantic types over this span.

        Concept-level when mentions are available. The difference is not a
        refinement: ``chest pain`` resolves as one Sign or Symptom rather than
        an anatomy token beside a symptom token, and bare ``one`` resolves to
        nothing at all rather than to T033.
        """
        if self.mentions is not None:
            return self.mentions.semantic_types(span)
        out: set[str] = set()
        for token in self.doc.tokens.overlapping(span):
            out |= self.lexicon.semantic_types(token.lower)
        return frozenset(out)

    def categories(self, span: Span) -> frozenset[str]:
        """Named categories over this span, honouring lexical precedence."""
        if self.mentions is not None:
            return self.mentions.categories(span)
        out: set[str] = set()
        for token in self.doc.tokens.overlapping(span):
            if token.is_content:
                out |= {t for t in resolve_tags(token.lower, self.lexicon) if t in _CATEGORY_NAMES}
        return frozenset(out)

    def is_measured(self, span: Span) -> bool:
        """Was a vocabulary actually consulted for this span?

        Distinguishes "we looked and found no category" from "we could not look".
        Without it, an install with no terminology would report every span as
        uncategorized, turning absence of evidence into evidence of absence.
        """
        return self.mentions is not None or self.lexicon.has_vocabulary


@runtime_checkable
class Target(Protocol):
    """A predicate over spans, with a canonical form for the seed."""

    def admits(self, span: Span, ctx: TargetContext) -> bool: ...

    def canon(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Everything:
    """No restriction. The default, and the honest name for it."""

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        return True

    def canon(self) -> str:
        return "all"


@dataclass(frozen=True, slots=True)
class Categories:
    """Spans carrying content of any of the named semantic categories.

    ``Categories("medication")`` is the question that replaced "is this
    clinical": it has a crisp answer, and a gold standard that can score it.
    """

    names: tuple[str, ...]

    def __init__(self, *names: str) -> None:
        if not names:
            raise ValueError("Categories() needs at least one category name")
        tuis_for(*names)  # raises on an unknown name, before any run starts
        object.__setattr__(self, "names", tuple(sorted(set(names))))

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        return bool(set(self.names) & ctx.categories(span))

    def canon(self) -> str:
        return "cat=" + ",".join(self.names)


@dataclass(frozen=True, slots=True)
class SemanticTypes:
    """Spans carrying any of the named UMLS semantic types.

    Finer than :class:`Categories`, for a target the named categories do not
    express — a single TUI, or a set spanning several categories.
    """

    tuis: tuple[str, ...]

    def __init__(self, *tuis: str) -> None:
        if not tuis:
            raise ValueError("SemanticTypes() needs at least one semantic type")
        object.__setattr__(self, "tuis", tuple(sorted(set(tuis))))

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        return bool(ctx.semantic_types(span) & set(self.tuis))

    def canon(self) -> str:
        return "tui=" + ",".join(self.tuis)


@dataclass(frozen=True, slots=True)
class PhenotypeEvidence:
    """Spans that are evidence for any of the named declared phenotypes.

    What ``phenotype_scope=target`` composes onto every operator's existing
    target, which is why it is an ordinary :class:`Target` rather than a special
    case in the runner: ``AllOf(whatever_was_asked_for, PhenotypeEvidence(...))``
    restricts any operator to one phenotype's evidence without that operator
    knowing phenotypes exist.

    Naming no phenotype means *any declared one*, so a run configured with two
    phenotypes targets the union without having to repeat their names.
    """

    names: tuple[str, ...]

    def __init__(self, *names: str) -> None:
        object.__setattr__(self, "names", tuple(sorted(set(names))))

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        found = ctx.phenotypes.overlapping(span)
        if not self.names:
            return bool(found)
        wanted = set(self.names)
        return any(e.phenotype in wanted for e in found)

    def canon(self) -> str:
        return "pheno=" + (",".join(self.names) if self.names else "*")


@dataclass(frozen=True, slots=True)
class Uncategorized:
    """Spans in **no** semantic category — the complement, not "non-clinical".

    The honest form of what a clinical/non-clinical binary was reaching for, and
    the one use of it that survives scrutiny: a **control condition**. Corrupting
    only uncategorized text and showing that results do not move is evidence that
    a downstream effect came from content rather than from perturbation per se.

    Requires a vocabulary. Without one every span is unclassifiable, and
    admitting them all would silently turn "we could not tell" into "we
    determined there is nothing here".
    """

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        if not ctx.is_measured(span):
            return False
        return not ctx.semantic_types(span)

    def canon(self) -> str:
        return "uncategorized"


@dataclass(frozen=True, slots=True)
class Concept:
    """Spans overlapping a mention the concept matcher returned.

    **This is not a ``clinical`` target**, and the difference is worth stating
    because the names are close. "Is this token clinical" is a question about the
    world, and it is not answerable from intrinsic properties — general English
    frequency, source-vocabulary count and semantic group each failed to separate
    ``one``, ``well`` and ``stairs`` from ``dyspnea``. "Did the configured matcher
    return a mention here" is a question about *this run's instrument*, and it has
    an exact answer.

    Do not reach for this one when the question is "what is the clinical content
    of this note". Measured on the SNOMED CT Entity Linking gold, this target has
    precision 0.500 at 45.7% token coverage: it admits ``she``, ``you``,
    ``please`` and section headings, and roughly 30% of an edit budget spent
    through it reaches clinical content. Experiment 2 was built on it and had to
    be rebuilt. ``validation/protocol.md`` §9 has the numbers.

    That is what makes it the right atom for ``target: {mode: umls}``: the user
    is asking to corrupt what the tagger found, and the tagger is named in the
    manifest. ``not(concept)`` is the complement and is the ``non_umls`` mode.

    Distinct from :class:`Uncategorized`, which asks whether a span carries a
    *semantic type*. A mention whose CUI falls outside every declared category
    is a concept and is uncategorized at once, so the two are not complements of
    each other.

    Without a matcher this admits nothing — the same refusal
    :class:`Uncategorized` makes, and for the same reason: "no mentions were
    supplied" must not read as "there are no concepts here".
    """

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        if ctx.mentions is None:
            return False
        return bool(ctx.mentions.overlapping(span))

    def canon(self) -> str:
        return "concept"


@dataclass(frozen=True, slots=True)
class Lexical:
    """Spans containing a word of one of the named lexical classes.

    The axis orthogonal to :class:`Categories`. ``Lexical("function_word")`` is a
    far tighter control condition than :class:`Uncategorized`, because it selects
    grammar rather than merely "whatever the terminology missed" — and unlike
    every semantic target, it needs no terminology installed at all.
    """

    classes: tuple[str, ...]

    def __init__(self, *classes: str) -> None:
        if not classes:
            raise ValueError("Lexical() needs at least one lexical class")
        known = {c.value for c in LexicalClass}
        unknown = sorted(set(classes) - known)
        if unknown:
            raise ValueError(f"unknown lexical class {unknown!r}; known: {sorted(known)}")
        object.__setattr__(self, "classes", tuple(sorted(set(classes))))

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        wanted = set(self.classes)
        return any(
            classify_lexical(t.lower).value in wanted
            for t in ctx.doc.tokens.overlapping(span)
            if t.is_content
        )

    def canon(self) -> str:
        return "lex=" + ",".join(self.classes)


#: Longest labelled value worth scanning back over. Lab labels are short; the
#: bound keeps the overlap search O(1) instead of O(labels) per candidate.
_MAX_LABEL_WIDTH = 200

#: Labelled-value spans, memoised per document.
#:
#: `label_spans` walks the whole document. Calling it once per candidate unit
#: made the cost quadratic in eligible units — measured, not theorised: the
#: typographical arm ran 576s per condition and the homoglyph arm, with roughly
#: five times the units, was still on its first condition after 100 minutes.
#:
#: Keyed on `doc.sha256`, the digest of the note's text, which `Document`
#: already carries. `Document` is unhashable (it carries a dict) so it cannot be
#: a key itself, and `id()` — the obvious substitute — is banned here for good
#: reason: it varies with process memory, and a cache key that changes between
#: runs is the seed of a reproducibility bug even when, as here, it happens to
#: be locally safe.
#:
#: The digest is also the stronger key. Identity would treat a re-segmented copy
#: of the same note as a miss, and — the case that matters — every condition in
#: a sweep produces a *different* document under the *same* `uid`, so uid-keying
#: would serve the clean note's label spans to its corrupted twin. Content
#: cannot collide that way: same digest, same text, same spans.
_LABEL_CACHE: dict[str, tuple[tuple[tuple[int, int], ...], list[int]]] = {}


def _labelled_value_spans(doc: Any) -> tuple[tuple[tuple[int, int], ...], list[int]]:
    cached = _LABEL_CACHE.get(doc.sha256)
    if cached is not None:
        return cached

    from robustehr.concepts.structural import label_spans

    spans = tuple(sorted((s.start, s.end) for s in label_spans(doc, numeric_values_only=True)))
    starts = [s for s, _ in spans]
    if len(_LABEL_CACHE) > 4:
        # Documents are processed one at a time; a handful of entries covers the
        # working set and bounds the memory a long sweep can accumulate.
        _LABEL_CACHE.clear()
    _LABEL_CACHE[doc.sha256] = (spans, starts)
    return spans, starts


@dataclass(frozen=True, slots=True)
class ClinicalSalience:
    """Spans whose tokens are clinical content, by measurement rather than assumption.

    Built for concept-restricted corruption, where :class:`Concept` was assumed
    to mean "clinical" and measured not to: any-UMLS-mention admits 45.7% of a
    discharge summary's tokens at 0.500 precision, including ``she``, ``you``,
    ``please`` and section headings, and roughly 30% of an edit budget spent
    through it reaches clinical content. This rule scores 0.820 precision at
    28.0% coverage against a gold rate of 29.1%
    (``validation/protocol.md`` §9).

    **A union of four clauses, not a classifier.** Each exists because a
    measurement showed the previous rule failing, and each draws on a source that
    does not share the others' blind spot:

    1. ``salience >= threshold`` — validated against the SNOMED CT Entity Linking
       gold. Carries disorders, symptoms, findings, exam and lab analytes.
    2. **drug vocabulary** — the gold annotates only 27.2% of medication
       mentions, marking drugs in prose but not the structured discharge list.
       On salience alone, 21 of 23 common drugs are rejected: ``metoprolol``
       occurs 213 times in the training notes and never once inside a gold span.
       Corrupting clinical text while sparing every drug name is close to the
       opposite of what this experiment is for.
    3. **labelled values** — annotators are inconsistent on analytes: ``hct-``
       0.99 and ``na-`` 0.99, but ``amylase-`` 0.29 and ``lipase-`` 0.43. In a
       pancreatitis note those are the diagnostic results. Resolved
       *positionally*: a token inside a labelled-value span, never a token equal
       to one's text. The vocabulary form of this clause made ``Mg-1.9``
       (magnesium, a lab) admit every ``mg`` (milligram, a dose unit), and ``mg``
       became the single most-corrupted token in the corpus at 714 occurrences.
    4. **tagged and unseen** — a matcher mention whose surface the corpus never
       showed us and which is not ordinary English. Rare drugs and conditions
       absent from the annotated notes reach the experiment through here.

    Scoped, not universal. It does not resolve *purulent discharge* from
    *discharge summary*; it exploits that within one corpus most tokens are used
    one way. :func:`robustehr.salience.manifest` carries the corpus and digest
    into the run manifest, because a targeting claim without them is exactly what
    the first Experiment 2 asserted and it was wrong by a factor of three.
    """

    threshold: float = 0.50
    use_drugs: bool = True
    use_labelled_values: bool = True
    use_unseen_mentions: bool = True

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        from robustehr import salience as _sal

        tokens = [t for t in ctx.doc.tokens.overlapping(span) if t.is_content]
        if not tokens:
            return False

        # Ordered by cost as well as by evidence: the lexicon is a dict lookup,
        # the labelled-value test walks the document's structural spans.
        if any(_sal.salience(t.lower) >= self.threshold for t in tokens):
            return True
        if self.use_drugs and self._any_drug(tokens):
            return True
        if self.use_labelled_values and self._in_labelled_value(span, ctx):
            return True
        return self.use_unseen_mentions and self._unseen_mention(span, ctx, tokens)

    @staticmethod
    def _any_drug(tokens: list[Any]) -> bool:
        from robustehr.drugs import load_synonyms

        syn = load_synonyms()
        for token in tokens:
            # `hct-` style trailing hyphens are part of the token in a lab block;
            # a drug never carries one, so strip before lookup.
            word = token.lower.rstrip("-")
            if word in syn.to_generic or word in syn.to_brand:
                return True
        return False

    @staticmethod
    def _in_labelled_value(span: Span, ctx: TargetContext) -> bool:
        spans, starts = _labelled_value_spans(ctx.doc)
        if not spans:
            return False
        # Binary search rather than a scan: this runs once per candidate unit,
        # and a character-level operator over a 16k-character note proposes tens
        # of thousands of them.
        j = bisect_right(starts, span.end) - 1
        while j >= 0 and starts[j] >= span.start - _MAX_LABEL_WIDTH:
            begin, end = spans[j]
            if begin < span.end and span.start < end:
                return True
            j -= 1
        return False

    @staticmethod
    def _unseen_mention(span: Span, ctx: TargetContext, tokens: list[Any]) -> bool:
        from robustehr import salience as _sal
        from robustehr.lexical import general_english

        if ctx.mentions is None or not ctx.mentions.overlapping(span):
            return False
        seen, english = _sal.table(), general_english()
        return any(t.lower not in seen and t.lower not in english for t in tokens)

    def canon(self) -> str:
        parts = [f"salience>={self.threshold:g}"]
        if self.use_drugs:
            parts.append("drug")
        if self.use_labelled_values:
            parts.append("labelled")
        if self.use_unseen_mentions:
            parts.append("unseen")
        return "clinical(" + ",".join(parts) + ")"


@dataclass(frozen=True, slots=True)
class Structure:
    """Spans overlapping a structural element — de-id masks, headers, lab blocks.

    Targeting structure rather than content is how a whole class of confounds
    gets tested: if a formatting-only perturbation moves a result, the result was
    never about the clinical content.
    """

    classes: tuple[ProtectionClass, ...]

    def __init__(self, *classes: ProtectionClass) -> None:
        if not classes:
            raise ValueError("Structure() needs at least one protection class")
        object.__setattr__(self, "classes", tuple(sorted(set(classes), key=lambda c: c.value)))

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        return any(p.cls in self.classes for p in ctx.protection.covering(span))

    def canon(self) -> str:
        return "struct=" + ",".join(c.value for c in self.classes)


@dataclass(frozen=True, slots=True)
class Section:
    """Spans inside a named section.

    Restricting a fixed dose to one section localizes where evidence lives —
    corrupting only the HPI versus only the Discharge Diagnosis at identical
    severity is cheap and says something no whole-document sweep can.
    """

    name: str

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        return any(
            self.name in (s.name, s.canonical_id) and s.full.contains(span)
            for s in ctx.doc.sections
        )

    def canon(self) -> str:
        return f"section={self.name}"


@dataclass(frozen=True, slots=True)
class Not:
    """The complement of a target.

    ``Not(Categories("disease"))`` is the counterpart experiment to
    ``Categories("disease")``: corrupt everything *except* the diagnoses, at the
    same dose, and see whether the model was reading them at all.
    """

    target: Target

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        return not self.target.admits(span, ctx)

    def canon(self) -> str:
        return f"not({self.target.canon()})"


@dataclass(frozen=True, slots=True)
class Governs:
    """Spans inside an assertion cue that **governs** a span the inner target admits.

    The query an assertion operator actually needs: not "is this span evidence
    for hypertension" — a cue never is — but "does this cue decide the reading of
    a span that is". Without it, ``pheno=hypertension`` composed onto a SEMANTIC
    operator rejects every cue and reports zero eligible units on a note full of
    them, because :class:`PhenotypeEvidence` tests the unit's own span and the
    ``denies`` in ``denies hypertension`` is not itself evidence.

    ConText already computes the join: every :class:`~robustehr.concepts.context.
    Assertion` carries the cues that produced it, so this is a lookup rather than
    a proximity window. A window would have to pick a number; this does not.

    ``overlaps`` rather than equality so the target is not specific to the cue
    operators. For them it degenerates to equality — the unit *is* the cue — but
    it also makes ``all(lex=word;governs(pheno=htn))`` mean "typo the word that
    negates hypertension", which is a different and runnable experiment.
    """

    target: Target

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        if ctx.assertions is None:
            return False
        return any(
            any(cue.span.overlaps(span) for cue in assertion.cues)
            and self.target.admits(assertion.span, ctx)
            for assertion in ctx.assertions.assertions
        )

    def canon(self) -> str:
        return f"governs({self.target.canon()})"


@dataclass(frozen=True, slots=True)
class AllOf:
    """Every sub-target must admit the span."""

    targets: tuple[Target, ...]

    def __init__(self, *targets: Target) -> None:
        if not targets:
            raise ValueError("AllOf() needs at least one target")
        object.__setattr__(self, "targets", tuple(sorted(targets, key=lambda t: t.canon())))

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        return all(t.admits(span, ctx) for t in self.targets)

    def canon(self) -> str:
        return "all(" + ";".join(t.canon() for t in self.targets) + ")"


@dataclass(frozen=True, slots=True)
class AnyOf:
    """At least one sub-target must admit the span."""

    targets: tuple[Target, ...]

    def __init__(self, *targets: Target) -> None:
        if not targets:
            raise ValueError("AnyOf() needs at least one target")
        object.__setattr__(self, "targets", tuple(sorted(targets, key=lambda t: t.canon())))

    def admits(self, span: Span, ctx: TargetContext) -> bool:
        return any(t.admits(span, ctx) for t in self.targets)

    def canon(self) -> str:
        return "any(" + ";".join(t.canon() for t in self.targets) + ")"


_CATEGORY_NAMES = frozenset(load_categories())

EVERYTHING: Target = Everything()


def _split_composite(inner: str) -> list[str]:
    """Split ``a;b;not(c)`` on top-level semicolons only.

    A naive ``inner.split(";")`` would cut inside a nested ``all(...)``, so
    composites could not contain composites. Depth counting is enough here
    because the only grouping character is a parenthesis.
    """
    parts: list[str] = []
    depth = start = 0
    for position, character in enumerate(inner):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ValueError(f"unbalanced ')' in target {inner!r}")
        elif character == ";" and depth == 0:
            parts.append(inner[start:position])
            start = position + 1
    if depth:
        raise ValueError(f"unbalanced '(' in target {inner!r}")
    parts.append(inner[start:])
    return [p for p in (x.strip() for x in parts) if p]


def _parse_clinical(spec: str) -> ClinicalSalience:
    """``clinical(salience>=0.5,drug,labelled,unseen)``: the canon, parsed back.

    Each clause names one of the rule's four sources; a clause that is absent
    from the string is switched off, and the threshold is read from the
    ``salience>=`` clause. ``clinical(salience>=0.5)`` is therefore the salience
    lexicon alone, which is a different (and weaker) target than the default.
    """
    inner = spec[len("clinical(") : -1]
    parts = [p.strip() for p in inner.split(",") if p.strip()]
    threshold = 0.50
    flags = {"drug": False, "labelled": False, "unseen": False}
    for part in parts:
        if part.startswith("salience>="):
            threshold = float(part[len("salience>=") :])
        elif part in flags:
            flags[part] = True
        else:
            raise ValueError(
                f"unknown clinical clause {part!r} in {spec!r}; "
                "expected salience>=X, drug, labelled, unseen"
            )
    return ClinicalSalience(
        threshold=threshold,
        use_drugs=flags["drug"],
        use_labelled_values=flags["labelled"],
        use_unseen_mentions=flags["unseen"],
    )


def _parse_combinator(spec: str) -> Target:
    """``not(a)``, ``all(a;b)`` or ``any(a;b)``, recursing into each part."""
    head, _, rest = spec.partition("(")
    inner = rest[:-1]
    if head == "not":
        return Not(parse(inner))
    if head == "governs":
        return Governs(parse(inner))
    if head == "all":
        return AllOf(*(parse(part) for part in _split_composite(inner)))
    if head == "any":
        return AnyOf(*(parse(part) for part in _split_composite(inner)))
    raise ValueError(f"unknown target combinator {head!r} in {spec!r}")


def parse(spec: str) -> Target:  # noqa: PLR0911, PLR0912 - one return per target key
    """Build a target from a compact string, for the CLI and recipe files.

    **The grammar is exactly what `canon()` emits**, so every target round-trips:
    ``parse(t.canon()) == t``. That matters because a run's target is recorded in
    the manifest as its canon, and a recorded run that cannot be re-parsed is a
    result nobody can reproduce from its own artifact.

    Atoms: ``all``, ``concept``, ``clinical``, ``uncategorized``, ``cat=a,b``,
    ``tui=T047``, ``lex=class``, ``section=name``, ``struct=deid_placeholder``,
    ``pheno=name`` (or ``pheno=*`` for any declared phenotype). ``clinical`` is
    the measured :class:`ClinicalSalience` rule at its default threshold; its
    canon, ``clinical(salience>=0.5,drug,labelled,unseen)``, parses back too.

    Composites: ``all(a;b)``, ``any(a;b)``, ``not(a)``, ``governs(a)``. They
    nest, and the semicolon splits only at depth zero.

    The composite forms are reachable from the command line: without a grammar
    `AllOf` and `AnyOf` would exist, emit a canon, and be writable by nobody,
    and the only way to intersect two targets would be `--phenotype-scope
    target`, which composes exactly one of them.
    """
    spec = spec.strip()
    if spec in {"", "all"}:
        return EVERYTHING
    if spec == "uncategorized":
        return Uncategorized()
    if spec == "concept":
        return Concept()
    if spec == "clinical":
        return ClinicalSalience()
    if spec.startswith("clinical("):
        return _parse_clinical(spec)
    if spec.endswith(")"):
        return _parse_combinator(spec)
    key, sep, value = spec.partition("=")
    if not sep:
        raise ValueError(
            f"unrecognized target {spec!r}; expected all, concept, clinical, uncategorized, "
            "cat=..., tui=..., lex=..., section=..., struct=..., pheno=..., "
            "or a combinator all(...), any(...), not(...), governs(...)"
        )
    values = [v for v in value.split(",") if v]
    if key == "cat":
        return Categories(*values)
    if key == "tui":
        return SemanticTypes(*values)
    if key == "section":
        return Section(value)
    if key == "lex":
        return Lexical(*values)
    if key == "struct":
        return Structure(*(ProtectionClass(v) for v in values))
    if key == "pheno":
        # `*` is how PhenotypeEvidence canonicalises "any declared phenotype",
        # which is a different request from naming them all: a run configured
        # with two phenotypes targets their union without repeating the names.
        return PhenotypeEvidence(*([] if value.strip() == "*" else values))
    raise ValueError(f"unknown target key {key!r} in {spec!r}")


def phenotypes_named(target: Target) -> frozenset[str]:
    """Every phenotype a target depends on, including through combinators.

    **A target naming a phenotype that was never declared admits nothing**, and
    silently: `PhenotypeEvidence.admits` consults `ctx.phenotypes`, which is
    empty unless the run declared one, so `--target pheno=heart_failure` alone
    would report zero eligible units and look like a corpus with no medications
    rather than a configuration error. The caller uses this to declare what the
    target asked for, or to refuse.

    `pheno=*` names nothing and returns the empty set — it means *any declared
    phenotype*, so it constrains nothing about which must be declared, only that
    at least one is.
    """
    if isinstance(target, PhenotypeEvidence):
        return frozenset(target.names)
    if isinstance(target, (Not, Governs)):
        return phenotypes_named(target.target)
    if isinstance(target, (AllOf, AnyOf)):
        return frozenset().union(*(phenotypes_named(t) for t in target.targets))
    return frozenset()


def wants_any_phenotype(target: Target) -> bool:
    """Whether the target uses ``pheno=*`` anywhere — any declared phenotype."""
    if isinstance(target, PhenotypeEvidence):
        return not target.names
    if isinstance(target, (Not, Governs)):
        return wants_any_phenotype(target.target)
    if isinstance(target, (AllOf, AnyOf)):
        return any(wants_any_phenotype(t) for t in target.targets)
    return False


def governs_used(target: Target) -> bool:
    """Whether ``governs(...)`` appears anywhere, including through combinators.

    The runner refuses rather than running: a ``governs`` target with no
    assertion index admits nothing, which is indistinguishable from a document
    with no cues. That is the same silent-zero this whole target exists to fix,
    so it must not be reintroduced one level up.
    """
    if isinstance(target, Governs):
        return True
    if isinstance(target, Not):
        return governs_used(target.target)
    if isinstance(target, (AllOf, AnyOf)):
        return any(governs_used(t) for t in target.targets)
    return False


def parse_all(specs: Iterable[str]) -> Target:
    """Several ``--target`` specs, intersected.

    Repeating the option is the module's own composition convention, and it is
    what a user reaches for first: ``--target cat=medication --target
    pheno=heart_failure`` is the same target as
    ``--target 'all(cat=medication;pheno=heart_failure)'`` and reads better in a
    shell. Both forms produce the same `canon()`, so the manifest does not record
    which one was typed.
    """
    parsed = [parse(s) for s in specs]
    kept = [t for t in parsed if not isinstance(t, Everything)]
    if not kept:
        return EVERYTHING
    if len(kept) == 1:
        return kept[0]
    return AllOf(*kept)


def describe(target: Target) -> str:  # noqa: PLR0911 - one return per target kind
    """A human sentence for the report, so a reader need not parse canon."""
    if isinstance(target, Everything):
        return "every eligible unit"
    if isinstance(target, Categories):
        labels = load_categories()
        named = ", ".join(labels[n].label.lower() for n in target.names)
        return f"units carrying {named}"
    if isinstance(target, Uncategorized):
        return "units in no semantic category (control)"
    if isinstance(target, Concept):
        return "units overlapping a matched concept mention"
    if isinstance(target, SemanticTypes):
        return f"units carrying semantic types {', '.join(target.tuis)}"
    if isinstance(target, Lexical):
        return "units containing " + ", ".join(c.replace("_", " ") for c in target.classes)
    if isinstance(target, Section):
        return f"units inside the {target.name} section"
    if isinstance(target, Structure):
        return f"units overlapping {', '.join(c.value for c in target.classes)}"
    if isinstance(target, Governs):
        return f"units inside a cue governing [{describe(target.target)}]"
    if isinstance(target, Not):
        return f"units NOT matching [{describe(target.target)}]"
    if isinstance(target, AllOf):
        return " and ".join(f"[{describe(t)}]" for t in target.targets)
    if isinstance(target, AnyOf):
        return " or ".join(f"[{describe(t)}]" for t in target.targets)
    return target.canon()


__all__ = [
    "EVERYTHING",
    "AllOf",
    "AnyOf",
    "Categories",
    "ClinicalSalience",
    "Concept",
    "Everything",
    "Governs",
    "Lexical",
    "Not",
    "PhenotypeEvidence",
    "Section",
    "SemanticTypes",
    "Structure",
    "Target",
    "TargetContext",
    "Uncategorized",
    "describe",
    "governs_used",
    "parse",
    "parse_all",
    "phenotypes_named",
    "wants_any_phenotype",
]
