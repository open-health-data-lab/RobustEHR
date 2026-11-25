"""Deterministic seeding and unit selection.

Everything random in RobustEHR is a pure function of content. There is no
timestamp, no worker id, no batch index, no note ordinal, no ``hash()``, and no
iteration over an unordered set anywhere on this path.

Three properties fall out of that, and each is asserted by the verification
suite rather than hoped for:

* **Subset invariance** — perturbing one note gives byte-identical output to
  perturbing the whole corpus, because ``note_sha256`` is in the seed material.
* **Append-only independence** — adding an operator to a recipe leaves every
  other operator's edits untouched, because ``op_id`` and ``op_version`` are in
  the seed material.
* **Nested severities** — ``selected(0.10) ⊆ selected(0.30) ⊆ selected(0.50)``,
  because the ranking key deliberately *excludes* severity. Severity levels are
  therefore paired within a note, which sharply reduces dose-response variance.
  The trade-off is that levels are not independent draws, so variance estimates
  need explicit ``salt`` replicates. That is a methodological choice and belongs
  in the paper's methods section.

Why hash-ranking rather than ``random.sample``: CPython's sampling algorithms
are implementation details that have changed across releases (``sample``
rejecting sets in 3.11, ``choices`` using float cumulative weights, ``randrange``
argument handling in 3.10/3.12). BLAKE2b is specified, version-independent,
order-independent, and parallel-friendly.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from robustehr.types import Unit
from robustehr.version import SPEC_VERSION

_FS = "\x1f"  # ASCII unit separator; cannot occur in any of the fields below


class Purpose:
    """Independent derived streams for the same unit."""

    SELECT = "select"
    MUTATE = "mutate"
    ORDER = "order"


@dataclass(frozen=True, slots=True)
class SeedMaterial:
    """The complete, canonical input to every derived random value.

    ``severity`` is deliberately absent. Including it would make each severity
    level an independent draw and destroy the nesting property described in the
    module docstring. For the same reason ``params_canon`` must be the
    operator's parameters *with severity excluded* — the runner is responsible
    for that split, and :func:`robustehr.dose.canonical_params` enforces it.
    """

    salt: str
    note_uid: str
    note_sha256: str
    op_id: str
    op_version: str
    params_canon: str
    scope_canon: str
    stage_index: int
    unit_kind: str

    def bytes_for(self, purpose: str) -> bytes:
        return _FS.join(
            [
                SPEC_VERSION,
                self.salt,
                self.note_uid,
                self.note_sha256,
                self.op_id,
                self.op_version,
                self.params_canon,
                self.scope_canon,
                str(self.stage_index),
                self.unit_kind,
                purpose,
            ]
        ).encode("utf-8")


def unit_key(material: SeedMaterial, unit_id: str, purpose: str = Purpose.SELECT) -> bytes:
    """A 16-byte key for one unit. Independent of every other unit."""
    return hashlib.blake2b(
        material.bytes_for(purpose) + _FS.encode() + unit_id.encode("utf-8"),
        digest_size=16,
    ).digest()


def select(units: Sequence[Unit], k: int, material: SeedMaterial) -> tuple[Unit, ...]:
    """Choose ``k`` units by stable hash rank, returned in document order.

    The ranking is a total order over ``(unit_key, unit_id)``, so ties are
    impossible and the result is independent of the input order. Because
    severity is not part of the key, the selection at a lower rate is a strict
    prefix of the selection at a higher rate.
    """
    if k <= 0 or not units:
        return ()
    ranked = sorted(units, key=lambda u: (unit_key(material, u.unit_id), u.unit_id))
    chosen = ranked[: min(k, len(ranked))]
    return tuple(sorted(chosen, key=lambda u: (u.span.start, u.span.end, u.unit_id)))


def select_stratified(
    units: Sequence[Unit],
    numerator: int,
    denominator: int,
    material: SeedMaterial,
    stratum_of: Callable[[Unit], str],
) -> tuple[Unit, ...]:
    """Select the same *proportion* from every stratum, not the same total.

    :func:`select` draws uniformly from the whole eligible pool. Over a large
    pool that is proportional in expectation, but per note it is not: a document
    with 129 medications and 12 devices, sampled uniformly at 10%, might take
    two devices or none, and the realized corruption rate per category swings
    wildly on exactly the small categories a result most wants to compare.

    This allocates ``numerator/denominator`` of **each** stratum separately, so
    every category is corrupted at the same rate by construction and no category
    can be disproportionately hit. That is what a concept-targeted experiment
    needs when it intends to attribute degradation to a category rather than to
    how the sampler happened to fall.

    **Rounding is the whole difficulty, and both obvious answers are wrong.**
    A stratum of 5 units at 10% is owed 0.5 units. Rounding up gives every small
    category *double* its share — measured on MIMIC, ``lab_result`` (43
    mentions) came out at 0.209 against a 0.10 target. Rounding down gives it
    zero, which is the failure stratifying was supposed to fix. Either way a
    small category is corrupted at a rate the experiment did not ask for, and
    "no category disproportionately corrupted" is false in one direction or the
    other.

    So the fractional part is resolved by a **fixed per-(note, stratum) offset**
    drawn from the same hash as everything else::

        k_s = floor(rate * n_s + u_s),    u_s in [0, 1)

    A stratum owed 0.5 units gets one in about half the notes and none in the
    rest, so the *corpus* rate converges on the requested one while no single
    note is systematically over- or under-corrupted. Three properties follow,
    and each is why this form was chosen over the alternatives:

    * **unbiased per stratum** — ``E[k_s] = rate * n_s`` exactly, for every
      stratum size, which is the property the experiment actually needs;
    * **nesting survives** — ``u_s`` does not depend on severity and ``floor``
      is monotone, so raising the rate can only ever add units:
      ``selected(0.05) ⊆ selected(0.10)`` still holds, and dose-response stays
      paired within a note;
    * **deterministic and order-independent** — ``u_s`` comes from the note's
      own seed material, strata are processed in sorted order, and members are
      ranked by the same key :func:`select` uses.
    """
    if numerator <= 0 or not units or denominator <= 0:
        return ()
    by_stratum: dict[str, list[Unit]] = {}
    for unit in units:
        by_stratum.setdefault(stratum_of(unit), []).append(unit)

    chosen: list[Unit] = []
    for name in sorted(by_stratum):
        members = by_stratum[name]
        # `u_s` as an exact rational over the same denominator, so the whole
        # computation stays in integers and no float reaches a control-flow
        # path — the rule this package keeps everywhere else.
        offset = int.from_bytes(unit_key(material, f"\x1fstratum\x1f{name}"), "big")
        k = (numerator * len(members) + offset % denominator) // denominator
        ranked = sorted(members, key=lambda u: (unit_key(material, u.unit_id), u.unit_id))
        chosen.extend(ranked[: min(k, len(ranked))])
    # A unit can belong to one stratum only, but the caller decides that; dedupe
    # defensively so a stratum function that returns overlapping labels cannot
    # produce the same edit twice.
    seen: set[str] = set()
    unique: list[Unit] = []
    for unit in chosen:
        if unit.unit_id not in seen:
            seen.add(unit.unit_id)
            unique.append(unit)
    return tuple(sorted(unique, key=lambda u: (u.span.start, u.span.end, u.unit_id)))


class RestrictedRandom:
    """A deliberately small RNG surface.

    Only the primitives whose behaviour is specified rather than
    implementation-defined are exposed. ``shuffle``, ``sample`` and ``choices``
    are absent on purpose — see the module docstring.
    """

    __slots__ = ("_rng",)

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def bits(self, n: int) -> int:
        return self._rng.getrandbits(n)

    def below(self, n: int) -> int:
        """Uniform integer in ``[0, n)``, by rejection sampling on raw bits.

        Implemented directly rather than via ``randrange`` so the result cannot
        drift with CPython's internal changes.
        """
        if n <= 0:
            raise ValueError("below() requires n > 0")
        if n == 1:
            return 0
        width = (n - 1).bit_length()
        while True:
            candidate = self._rng.getrandbits(width)
            if candidate < n:
                return candidate

    def pick(self, items: Sequence[object]) -> object:
        if not items:
            raise ValueError("pick() from an empty sequence")
        return items[self.below(len(items))]

    def weighted_pick(self, items: Sequence[object], weights: Sequence[int]) -> object:
        """Weighted choice using integer cumulative weights.

        ``random.choices`` builds float cumulative weights and bisects them,
        which makes the outcome sensitive to floating-point representation.
        """
        if len(items) != len(weights):
            raise ValueError("items and weights must be the same length")
        if any(w < 0 for w in weights):
            raise ValueError("weights must be non-negative")
        total = sum(weights)
        if total <= 0:
            raise ValueError("weights must sum to a positive value")
        target = self.below(total)
        cumulative = 0
        for item, weight in zip(items, weights, strict=True):
            cumulative += weight
            if target < cumulative:
                return item
        raise AssertionError("unreachable")  # pragma: no cover


def unit_rng(
    material: SeedMaterial, unit_id: str, purpose: str = Purpose.MUTATE
) -> RestrictedRandom:
    """A per-unit RNG, not a per-document stream.

    Deriving from the unit key rather than from a running stream means the
    mutation chosen for a unit does not depend on how many units preceded it. A
    segmenter fix upstream that adds one sentence then changes that sentence's
    fate and nothing else, instead of re-rolling the whole document.
    """
    key = unit_key(material, unit_id, purpose)
    return RestrictedRandom(int.from_bytes(key[:8], "big"))


def stream_seed(material: SeedMaterial, purpose: str = Purpose.MUTATE) -> int:
    """A document-level seed, for the rare operator with no natural unit."""
    return int.from_bytes(
        hashlib.blake2b(material.bytes_for(purpose), digest_size=8).digest(), "big"
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "Purpose",
    "RestrictedRandom",
    "SeedMaterial",
    "select",
    "select_stratified",
    "sha256_text",
    "stream_seed",
    "unit_key",
    "unit_rng",
]
