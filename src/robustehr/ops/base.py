"""The operator protocol.

**Operators never sample.** They report which units they *could* act on, and
propose edits for the units the framework hands back. Scope filtering,
protection subtraction, ``k`` computation and hash-rank selection all live in
the runner.

That split is the single most important API decision in the package. If
operators sampled for themselves, then nested severity ladders, subset
invariance and append-only independence would each be a promise every operator
author had to keep, and one that quietly rotted the first time somebody reached
for ``random.choice``. As it stands they are properties of the framework, proved
once.

The second rule: operators are **pure proposers**. They receive an immutable
document, return immutable edits against original offsets, and never observe
another operator's output. Composition is therefore well-defined without any
operator knowing composition exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from typing import ClassVar, Protocol, runtime_checkable

from robustehr.categories import default_categories
from robustehr.document import Document
from robustehr.dose import DoseSpec, scope_canon
from robustehr.lexicon import DEFAULT_LEXICON, Lexicon
from robustehr.protect import ProtectionIndex
from robustehr.rng import RestrictedRandom, SeedMaterial, unit_rng
from robustehr.target import (
    EVERYTHING,
    AllOf,
    Categories,
    Everything,
    Section,
    Target,
    Uncategorized,
)
from robustehr.types import (
    Channel,
    Contract,
    Edit,
    PhenotypeScope,
    ProtectionClass,
    Span,
    TargetMode,
    Unit,
)


class Layer(StrEnum):
    """Rough execution tier, used only to order operators within a stage.

    Structural operators run before word- and character-level ones so that a
    section deletion does not have to contend with a typo inside the section it
    is about to remove.
    """

    STRUCTURE = "structure"
    SECTION = "section"
    SENTENCE = "sentence"
    WORD = "word"
    CHAR = "char"


#: The ladder an operator inherits when no external specification pins one.
#: Matches the historical `--severities` default, so behaviour is unchanged for
#: every operator that does not override it.
DEFAULT_SEVERITY_LEVELS: tuple[str, str, str] = ("0.10", "0.30", "0.50")

#: Priority by layer. Lower wins ties in the edit total order.
LAYER_PRIORITY: dict[Layer, int] = {
    Layer.STRUCTURE: 0,
    Layer.SECTION: 10,
    Layer.SENTENCE: 20,
    Layer.WORD: 30,
    Layer.CHAR: 40,
}


@dataclass(frozen=True, slots=True)
class Scope:
    """Which part of a document an operator may act on.

    Every modifier here applies to *every* operator; there is no such thing as a
    phenotype-specific operator, only a run with a phenotype scope. See the
    package documentation for why relatedness is a property of where an edit
    landed rather than a class of operator.
    """

    section: str | None = None
    target: Target = EVERYTHING
    """What to corrupt. See :mod:`robustehr.target`.

    The composable replacement for ``target_mode``: ``Categories("medication")``
    instead of a clinical/non-clinical binary that could not be answered.
    """
    target_mode: TargetMode = TargetMode.ALL
    """Deprecated. Retained so existing callers keep working for one release.

    ``CLINICAL_ONLY`` maps to every default category and ``NONCLINICAL_ONLY`` to
    :class:`~robustehr.target.Uncategorized`, which is the honest reading of what
    it always meant: not "this is non-clinical" but "this is in no category".
    """
    phenotype_scope: PhenotypeScope = PhenotypeScope.AGNOSTIC
    phenotypes: tuple[str, ...] = ()

    def resolved_target(self) -> Target:
        """The effective target, folding in a legacy ``target_mode``."""
        parts: list[Target] = []
        if not isinstance(self.target, Everything):
            parts.append(self.target)
        if self.target_mode is TargetMode.CLINICAL_ONLY:
            parts.append(Categories(*sorted(default_categories())))
        elif self.target_mode is TargetMode.NONCLINICAL_ONLY:
            parts.append(Uncategorized())
        if self.section is not None:
            parts.append(Section(self.section))
        if not parts:
            return EVERYTHING
        return parts[0] if len(parts) == 1 else AllOf(*parts)

    def __post_init__(self) -> None:
        if self.phenotype_scope is not PhenotypeScope.AGNOSTIC and not self.phenotypes:
            raise ValueError(
                f"phenotype_scope={self.phenotype_scope.value} requires at least one "
                "phenotype: 'phenotype-related' is undefined without naming which"
            )

    def canon(self) -> str:
        return scope_canon(
            section=self.section,
            target_mode=self.target_mode.value,
            target=self.target.canon(),
            phenotype_scope=self.phenotype_scope.value,
            phenotypes=self.phenotypes,
        )

    def restrict(self, doc: Document) -> tuple[Span, ...]:
        """The character ranges this scope admits, in document order."""
        if self.section is None:
            return (Span(0, len(doc.text)),) if doc.text else ()
        return tuple(s.full for s in doc.sections if self.section in (s.name, s.canonical_id))


@dataclass(frozen=True, slots=True)
class OpContext:
    """Everything an operator is allowed to see."""

    doc: Document
    protection: ProtectionIndex
    scope: Scope
    params: Mapping[str, object] = field(default_factory=dict)
    material: SeedMaterial | None = None
    lexicon: Lexicon = DEFAULT_LEXICON
    """Classifies tokens as clinical or not, and gates lexicon-constrained rules.

    Its main job is measurement rather than generation: a typo in ``the`` and a
    typo in ``obese`` are the same operator at the same dose and mean entirely
    different things. Without a supplied vocabulary it still classifies by
    morphology and closed-class exclusion, so the distinction is available at
    reduced recall rather than not at all.
    """
    severity_fraction: Fraction = Fraction(0)
    """The requested rate, for document-level operators only.

    An operator with exactly one unit gets no information from ``k``, so
    truncation needs the rate itself. It arrives here rather than through
    ``params`` because ``params`` feeds the seed, and severity is deliberately
    excluded from the seed so that severity ladders nest.
    """

    @property
    def text(self) -> str:
        return self.doc.text

    def rng(self, unit_id: str) -> RestrictedRandom:
        """A per-unit RNG for mutation choices.

        Derived from the unit's own content-addressed id, so the mutation chosen
        for a unit does not depend on how many units preceded it.
        """
        if self.material is None:
            raise RuntimeError("OpContext has no seed material; the runner must supply it")
        return unit_rng(self.material, unit_id)

    def param(self, key: str, default: object = None) -> object:
        return self.params.get(key, default)

    def str_param(self, key: str, default: str) -> str:
        value = self.params.get(key, default)
        return value if isinstance(value, str) else default

    def int_param(self, key: str, default: int) -> int:
        value = self.params.get(key, default)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    def bool_param(self, key: str, default: bool) -> bool:
        """A flag, and only a real bool counts.

        `int_param` explicitly rejects bools because `True` is an `int` in
        Python and a caller passing one meant a flag, not a 1. This is the
        other half of that: a caller passing 1 meant a count, so it does not
        silently become a flag either.
        """
        value = self.params.get(key, default)
        return value if isinstance(value, bool) else default


@runtime_checkable
class Operator(Protocol):
    """What every operator declares and implements.

    The class attributes are not documentation — they are consumed. ``dose``
    supplies the denominator, ``targets`` decides what the protection registry
    unlocks, ``contract`` decides which property test the operator must survive,
    and ``resources`` are hashed into ``version`` so a lexicon swap invalidates
    the affected seeds.
    """

    id: ClassVar[str]
    version: ClassVar[str]
    layer: ClassVar[Layer]
    channel: ClassVar[Channel]
    contract: ClassVar[Contract]
    dose: ClassVar[DoseSpec]
    targets: ClassVar[frozenset[ProtectionClass]]
    resources: ClassVar[tuple[str, ...]]
    meta: ClassVar[OperatorMeta]
    """The same facts as a frozen record, built by the registry on registration.

    Declared here because the runner and the taxonomy both consume it; leaving
    it off the protocol meant every call site had to assert its existence.
    """

    def eligible(self, ctx: OpContext) -> Sequence[Unit]:
        """Every unit this operator could act on, in document order.

        Must be a pure function of the context. The runner subtracts protection
        and applies scope, so an implementation should not attempt either.
        """
        ...

    def propose(self, ctx: OpContext, selected: Sequence[Unit]) -> Iterable[Edit]:
        """Edits for the units the framework selected. No sampling here."""
        ...


@dataclass(frozen=True, slots=True)
class OperatorMeta:
    """Static facts about an operator, for the taxonomy and the registry."""

    id: str
    version: str
    layer: Layer
    channel: Channel
    contract: Contract
    dose: DoseSpec
    targets: frozenset[ProtectionClass]
    resources: tuple[str, ...]
    canonicalizer: str | None = None
    """Name of the ``kappa`` projection proving an INVARIANT contract."""
    modes: tuple[str, ...] = ()
    simulates: str = ""
    severity_levels: tuple[str, str, str] = DEFAULT_SEVERITY_LEVELS
    """The operator's own ``low``, ``medium``, ``high`` severity literals.

    Named levels have to be per-operator or they are meaningless. "Medium" for
    typographical errors is 10% of eligible words; for header deletion it is 50%
    of headers; for section duplication it is two sections and not a rate at
    all. A single global mapping would compare a mild typo dose against a severe
    structural one and call them the same experimental condition.

    Literals, not floats, for the reason :class:`~robustehr.types.RateSeverity`
    is: the config layer resolves a name to this string and parses it exactly.
    Operators that have no externally specified ladder keep the package default
    and say so by not overriding it.
    """

    @property
    def priority(self) -> int:
        return LAYER_PRIORITY[self.layer]


def make_edit(
    op: OperatorMeta,
    unit: Unit,
    span: Span,
    replacement: str,
    *,
    rank: int = 0,
    **kwargs: object,
) -> Edit:
    """Build an edit with the operator's identity and priority already attached."""
    return Edit(
        start=span.start,
        end=span.end,
        replacement=replacement,
        op_id=op.id,
        unit_id=unit.unit_id,
        rank=rank,
        op_priority=op.priority,
        targets=op.targets,
        **kwargs,  # type: ignore[arg-type]
    )


__all__ = [
    "DEFAULT_SEVERITY_LEVELS",
    "LAYER_PRIORITY",
    "Layer",
    "OpContext",
    "Operator",
    "OperatorMeta",
    "Scope",
    "make_edit",
]
