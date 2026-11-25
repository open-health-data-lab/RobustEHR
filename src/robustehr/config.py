"""The user-facing recipe: what to corrupt, how much, and where.

Two modules have referenced ``robustehr.config`` since before it existed —
:class:`~robustehr.types.RateSeverity` says "config loaders must reject
severities that arrive as YAML floats", and :func:`~robustehr.runner.severity_ladder`
repeats it. This is that loader, and that rule is its first job.

The recipe separates three questions the CLI flags let a user blur together::

    WHAT should be corrupted?   -> corruptions:  family names or operator ids
    HOW MUCH?                   -> severity:     a level name, or a literal
    WHERE?                      -> target:       random / clinical / umls / non_umls, refined

plus two that decide the shape of the experiment: how much of the corpus is
touched at all (``documents``), and whether a note may receive more than one
operator (``corruptions_per_document``).

```yaml
seed: rep0
documents: {fraction: 0.50}
corruptions: [structural, input.typo]
corruptions_per_document: {min: 1, max: 2}
severity: medium
target:
  mode: umls
  semantic_categories: [medication, finding]
  phenotype: heart_failure
```

Three design rules, each because the obvious alternative produces a wrong number
rather than an error:

**Severities are strings.** ``severity: 0.1`` in YAML is a float, ``0.1 + 0.2 !=
0.3``, and a float on a control-flow path makes a dose-response curve
irreproducible across platforms. A float here is a hard error naming the fix,
not a silent cast.

**A named level resolves per operator.** "Medium" is 10% of eligible words for
`input.typo`, 50% of headers for `render.header_delete`, and *two sections* for
`discourse.section_duplicate` — which is not a rate at all. One global mapping
would compare a mild typo dose against a severe structural one and call them the
same condition. The per-operator ladders live on
:attr:`~robustehr.ops.base.OperatorMeta.severity_levels`.

**Targeting does not reach structural operators.** The reason is mechanical:
a section header is not a concept span,
so ``target: {mode: umls}`` applied to `render.header_delete` would select
nothing and report a corpus-wide zero that looks like a finding. Asking for it
is a configuration error with a message; it is never silently ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

from robustehr.ops.base import Layer
from robustehr.target import (
    AllOf,
    Categories,
    ClinicalSalience,
    Concept,
    Everything,
    Not,
    PhenotypeEvidence,
    Target,
)
from robustehr.types import Severity

#: Named severity levels, in order. Index into an operator's own ladder.
LEVELS = ("low", "medium", "high")

#: Targeting modes a recipe may name, and the target each maps to.
#: ``random`` is `Everything` rather than a mode of its own — the uniform
#: hash-rank draw over the whole eligible set already IS random targeting, and
#: giving it a separate mechanism would be a second sampler to keep honest.
#: ``clinical`` is the measured salience rule (`target.ClinicalSalience`): the
#: three levels of aim a study reports are ``random`` (no aim), ``clinical``
#: (clinical content) and ``umls`` refined by ``phenotype`` (one phenotype's
#: evidence); ``non_umls`` is the complement of any concept mention.
MODES = ("random", "umls", "non_umls", "clinical")

#: Layers whose operators accept a target. Everything else is structural, where
#: Targeting must not be forced onto these layers; see the module docstring.
TARGETABLE = frozenset({Layer.WORD, Layer.CHAR})


class ConfigError(ValueError):
    """A recipe that cannot be executed as written."""


@dataclass(frozen=True, slots=True)
class DocumentSelection:
    """How much of the corpus to corrupt. Notes not selected are unchanged."""

    n: int | None = None
    fraction: Fraction | None = None

    @classmethod
    def parse(cls, raw: Any) -> DocumentSelection:
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ConfigError("documents must be a mapping with 'n' or 'fraction'")
        unknown = sorted(set(raw) - {"n", "fraction"})
        if unknown:
            raise ConfigError(f"unknown documents key(s) {unknown}; expected n or fraction")
        if "n" in raw and "fraction" in raw:
            raise ConfigError("documents takes n or fraction, not both")
        if "n" in raw:
            return cls(n=_int(raw["n"], "documents.n"))
        if "fraction" in raw:
            return cls(fraction=_fraction(raw["fraction"], "documents.fraction"))
        return cls()


@dataclass(frozen=True, slots=True)
class PerDocument:
    """How many operators one note may receive.

    ``min == max == 1`` is the ablation mode: each corrupted note carries
    exactly one operator, so any difference between arms is attributable to that
    operator alone. Wider ranges model realistic degradation, where several
    documentation problems coexist — and the drawn set is recorded per note, so
    "realistic" does not mean "unaccountable".
    """

    minimum: int = 1
    maximum: int = 1

    @classmethod
    def parse(cls, raw: Any) -> PerDocument:
        if raw is None:
            return cls()
        if isinstance(raw, bool):  # bool is an int in Python; catch it before _int
            raise ConfigError("corruptions_per_document must be an integer or {min, max}")
        if isinstance(raw, int):
            n = _int(raw, "corruptions_per_document")
            return cls(n, n)
        if not isinstance(raw, dict):
            raise ConfigError("corruptions_per_document must be an integer or {min, max}")
        unknown = sorted(set(raw) - {"min", "max"})
        if unknown:
            raise ConfigError(f"unknown corruptions_per_document key(s) {unknown}")
        low = _int(raw.get("min", 1), "corruptions_per_document.min")
        high = _int(raw.get("max", low), "corruptions_per_document.max")
        if low > high:
            raise ConfigError(f"corruptions_per_document min {low} exceeds max {high}")
        return cls(low, high)

    @property
    def is_single(self) -> bool:
        return self.minimum == self.maximum == 1


@dataclass(frozen=True, slots=True)
class Targeting:
    """Where word- and character-level corruption is allowed to land."""

    mode: str = "random"
    semantic_categories: tuple[str, ...] = ()
    phenotype: str | None = None
    stratify_by: str | None = None
    """Allocate the dose proportionally across strata instead of one uniform draw.

    ``semantic_category`` is the one stratifier today. It answers the question a
    concept-targeted experiment actually asks: a uniform draw over a note whose
    concepts are 129 medications and 12 devices takes two devices or none, so
    the *realized rate per category* swings on exactly the small categories the
    result wants to compare. Stratifying corrupts every category at the same
    rate by construction, so degradation is attributable to the category rather
    than to how the sampler fell.
    """

    @classmethod
    def parse(cls, raw: Any) -> Targeting:
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ConfigError("target must be a mapping with a 'mode'")
        unknown = sorted(set(raw) - {"mode", "semantic_categories", "phenotype", "stratify_by"})
        if unknown:
            raise ConfigError(f"unknown target key(s) {unknown}")
        mode = str(raw.get("mode", "random"))
        if mode not in MODES:
            raise ConfigError(f"unknown target mode {mode!r}; expected one of {list(MODES)}")
        categories = tuple(str(c) for c in raw.get("semantic_categories", ()) or ())
        phenotype = raw.get("phenotype")
        stratify = raw.get("stratify_by")
        if stratify is not None:
            from robustehr.runner import STRATIFIERS

            if stratify not in STRATIFIERS:
                raise ConfigError(f"unknown stratify_by {stratify!r}; known: {list(STRATIFIERS)}")
            if mode != "umls":
                raise ConfigError(
                    f"stratify_by needs target mode 'umls', not {mode!r}: strata are "
                    "semantic categories, and outside the concept layer a unit has none"
                )
        if mode != "umls" and (categories or phenotype):
            raise ConfigError(
                f"target mode {mode!r} takes no semantic_categories or phenotype: "
                "both refine a set of UMLS concepts, and outside mode 'umls' there "
                "is no such set to refine"
            )
        return cls(
            mode,
            categories,
            str(phenotype) if phenotype else None,
            str(stratify) if stratify else None,
        )

    def to_target(self) -> Target:
        """The composable target this configuration denotes.

        The eligibility chain, left to right::

            UMLS / non-UMLS  ->  semantic category  ->  phenotype association

        With ``mode: umls`` and no refinement the target is
        :class:`~robustehr.target.Concept` alone, which is what makes §9's
        "preserve the natural distribution" true without any code: eligibility
        is restricted to concept spans and the selection is the same uniform
        hash-rank draw as everywhere else, so a document whose concepts are 70%
        medications receives about 70% of its perturbations on medications. A
        balanced draw would need a stratifier, and there is deliberately none.
        """
        if self.mode == "random":
            return Everything()
        if self.mode == "non_umls":
            return Not(Concept())
        if self.mode == "clinical":
            return ClinicalSalience()
        parts: list[Target] = [Concept()]
        if self.semantic_categories:
            parts.append(Categories(*self.semantic_categories))
        if self.phenotype:
            parts.append(PhenotypeEvidence(self.phenotype))
        return parts[0] if len(parts) == 1 else AllOf(*parts)


@dataclass(frozen=True, slots=True)
class Recipe:
    """A fully-specified corruption run."""

    corruptions: tuple[str, ...] = ()
    """Family names or operator ids, as written. Resolved by :meth:`operators`."""
    documents: DocumentSelection = field(default_factory=DocumentSelection)
    per_document: PerDocument = field(default_factory=PerDocument)
    severity: str = "medium"
    """A level name, a quoted rate literal, or ``count:N``."""
    target: Targeting = field(default_factory=Targeting)
    seed: str = "rep0"
    params: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    """Operator parameters, keyed by operator id: ``{input.typo: {mode: delete}}``."""
    source: str | None = None
    """Path the recipe was read from, for the manifest."""

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> Recipe:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.parse(raw, source=str(path))

    @classmethod
    def parse(cls, raw: Any, *, source: str | None = None) -> Recipe:
        if not isinstance(raw, dict):
            raise ConfigError("a recipe must be a YAML mapping")
        known = {
            "corruptions",
            "documents",
            "corruptions_per_document",
            "severity",
            "target",
            "seed",
            "params",
        }
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ConfigError(f"unknown recipe key(s) {unknown}; expected {sorted(known)}")
        corruptions = raw.get("corruptions") or ()
        if isinstance(corruptions, str):
            corruptions = [corruptions]
        return cls(
            corruptions=tuple(str(c) for c in corruptions),
            documents=DocumentSelection.parse(raw.get("documents")),
            per_document=PerDocument.parse(raw.get("corruptions_per_document")),
            severity=_severity_literal(raw.get("severity", "medium")),
            target=Targeting.parse(raw.get("target")),
            seed=str(raw.get("seed", "rep0")),
            params=_operator_params(raw.get("params")),
            source=source,
        )

    # -- resolution --------------------------------------------------------

    def operators(self) -> tuple[str, ...]:
        """Expand family names into operator ids, deduplicated and sorted.

        An empty ``corruptions`` list is an error rather than "everything". A
        recipe that says nothing about what to corrupt is far more likely to be
        a typo than a request for all 28 operators at once.
        """
        from robustehr.ops import registry

        registry.register_builtins()
        known = set(registry.all_ids())
        found: set[str] = set()
        for name in self.corruptions:
            if name in known:
                found.add(name)
                continue
            try:
                found.update(registry.resolve_family(name))
            except KeyError as exc:
                raise ConfigError(
                    f"unknown corruption {name!r}: not an operator id and not a "
                    f"family. Families: {sorted(registry.families())}"
                ) from exc
        if not found:
            raise ConfigError(
                "recipe selects no corruptions; name at least one operator id or family"
            )
        return tuple(sorted(found))

    def severity_for(self, op_id: str) -> Severity:
        """This recipe's severity, resolved against one operator's own ladder."""
        from robustehr.ops import registry
        from robustehr.runner import parse_severity

        if self.severity not in LEVELS:
            return parse_severity(self.severity)
        registry.register_builtins()
        ladder = registry.get(op_id).meta.severity_levels
        return parse_severity(ladder[LEVELS.index(self.severity)])

    def target_for(self, op_id: str) -> Target:
        """The target for one operator, honouring the structural exemption."""
        from robustehr.ops import registry

        registry.register_builtins()
        if registry.get(op_id).meta.layer in TARGETABLE:
            return self.target.to_target()
        return Everything()

    def operators_for(self, note_uid: str) -> tuple[str, ...]:
        """Which operators this particular note receives.

        Deterministic from ``(seed, note_uid)`` and nothing else — not from
        iteration order, not from position in the corpus — so two runs over the
        same recipe assign the same operators to the same notes even if the
        corpus was reordered or filtered between them.

        The count is drawn first, then the operators, by the same hash-rank the
        rest of the package selects with. That makes the draw **nested in the
        count**: a note given two operators at ``max: 2`` keeps both at
        ``max: 4`` and gains more, rather than being re-randomised, so widening
        the range is a paired comparison.
        """
        import hashlib

        ops = self.operators()
        if self.per_document.is_single and len(ops) == 1:
            return ops

        def key(label: str) -> bytes:
            return hashlib.blake2b(
                f"{self.seed}\x1f{note_uid}\x1f{label}".encode(), digest_size=16
            ).digest()

        span = self.per_document.maximum - self.per_document.minimum + 1
        count = self.per_document.minimum + int.from_bytes(key("count"), "big") % span
        count = min(count, len(ops))
        ranked = sorted(ops, key=lambda op: (key(op), op))
        return tuple(sorted(ranked[:count]))

    def check(self) -> None:
        """Reject a recipe that would run but not mean what it says.

        Called before any note is read, so a misconfiguration costs a second
        rather than a corpus sweep whose every cell reports zero.
        """
        from robustehr.ops import registry

        ops = self.operators()
        if self.target.mode != "random":
            structural = [op for op in ops if registry.get(op).meta.layer not in TARGETABLE]
            if structural:
                raise ConfigError(
                    f"target mode {self.target.mode!r} cannot apply to structural "
                    f"corruptions {structural}: a section header is not a concept "
                    "span, so the target would select nothing and report a zero "
                    "that reads as a finding. Split them into separate runs, or "
                    "use target mode 'random'."
                )
        if self.per_document.maximum > len(ops):
            raise ConfigError(
                f"corruptions_per_document max {self.per_document.maximum} exceeds "
                f"the {len(ops)} operator(s) selected; a note cannot receive more "
                "distinct operators than exist"
            )
        strangers = sorted(set(self.params) - set(ops))
        if strangers:
            raise ConfigError(
                f"params given for {strangers}, which this recipe does not run; it runs {list(ops)}"
            )
        for op_id in ops:
            self.severity_for(op_id)  # raises here rather than mid-sweep

    def to_manifest(self) -> dict[str, Any]:
        """Everything a reader needs to reconstruct the configuration."""
        return {
            "source": self.source,
            "seed": self.seed,
            "corruptions": list(self.corruptions),
            "operators": list(self.operators()),
            "documents": {
                "n": self.documents.n,
                "fraction": (
                    None if self.documents.fraction is None else str(self.documents.fraction)
                ),
            },
            "corruptions_per_document": {
                "min": self.per_document.minimum,
                "max": self.per_document.maximum,
            },
            "severity": self.severity,
            "params": {op: dict(sorted(p.items())) for op, p in sorted(self.params.items())},
            "target": {
                "mode": self.target.mode,
                "semantic_categories": list(self.target.semantic_categories),
                "phenotype": self.target.phenotype,
                "stratify_by": self.target.stratify_by,
                "canon": self.target.to_target().canon(),
            },
        }


# ---------------------------------------------------------------------------
# Scalar parsing
# ---------------------------------------------------------------------------


def _int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field_name} must be an integer, got {value!r}")
    if value < 0:
        raise ConfigError(f"{field_name} must be non-negative, got {value}")
    return value


def _fraction(value: Any, field_name: str) -> Fraction:
    """A fraction from a literal, never from a float.

    ``fraction: 0.5`` in YAML is a float and is refused for the same reason a
    float severity is: it is not exactly representable, so two runs on different
    platforms could select different numbers of notes from the same corpus.
    """
    if isinstance(value, float):
        raise ConfigError(
            f"{field_name} must be quoted so it is parsed exactly: "
            f'write "{value}" rather than {value}'
        )
    if isinstance(value, int) and not isinstance(value, bool):
        return Fraction(value)
    if not isinstance(value, str):
        raise ConfigError(f"{field_name} must be a quoted decimal literal, got {value!r}")
    from decimal import Decimal, InvalidOperation

    try:
        return Fraction(Decimal(value))
    except InvalidOperation as exc:
        raise ConfigError(f"{field_name} is not a decimal literal: {value!r}") from exc


def _operator_params(raw: Any) -> dict[str, dict[str, object]]:
    """``params:`` as written: a mapping of operator id to its own mapping.

    Values keep their YAML type, because an operator reads a flag only from a
    bool and a count only from an int. Floats are refused for the reason
    severities are: a float on a control-flow path is not reproducible.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError("params must map an operator id to its parameters")
    out: dict[str, dict[str, object]] = {}
    for op_id, values in raw.items():
        if not isinstance(values, dict):
            raise ConfigError(f"params for {op_id!r} must be a mapping of name to value")
        for key, value in values.items():
            if not isinstance(value, (str, int, bool)):
                raise ConfigError(
                    f"params {op_id}.{key} must be a string, an integer or a boolean, "
                    f"got {type(value).__name__}"
                )
        out[str(op_id)] = {str(k): v for k, v in values.items()}
    return out


def _severity_literal(value: Any) -> str:
    """A level name or an exact literal — never a YAML float."""
    if isinstance(value, float):
        raise ConfigError(
            "severity must be quoted so it is parsed exactly: "
            f'write "{value}" rather than {value}. A float severity is not '
            "reproducible across platforms, and a dose-response curve built on "
            "one cannot be replayed."
        )
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if not isinstance(value, str):
        raise ConfigError(f"severity must be a level name or a quoted literal, got {value!r}")
    return value


__all__ = [
    "LEVELS",
    "MODES",
    "TARGETABLE",
    "ConfigError",
    "DocumentSelection",
    "PerDocument",
    "Recipe",
    "Targeting",
]
