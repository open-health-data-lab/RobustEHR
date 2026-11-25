"""Anchor voting: resolve an ambiguous short form, or abstain — stage 3c.

The last rung of abbreviation expansion, and the smallest. Its population is what
survives the two before it: a short form in running prose, where position gave no
help and the terminology offers more than one sense.

**A tie abstains.** Exactly one sense's cues firing resolves the mention; zero or
two or more returns nothing. There is no fallback to the most likely sense, and
that is the design rather than an omission — ``matcher._rank`` already
demonstrates the alternative, breaking ties alphabetically by CUI and thereby
answering ``RA`` with *refractory anemia* on 287 room-air gold spans.
Deterministic and wrong. Determinism is necessary, not sufficient.

**Cues are literal surface strings, and must be.** Disambiguating ``RA`` from the
*concepts* around it would require the candidate-generation stage's output, which
requires this stage — a cycle. Surface tokens come from segmentation, which runs
before both. This is an architectural constraint, not a simplification.

**A token window, not the sentence.** Sentence boundaries are measurably
sensitive to de-identification convention: ``probe_deid_assertion`` shows a
placeholder ending a sentence spuriously and a negation cue then crossing into
the next clause. Scoping cues to a sentence would make this rung's output depend
on which de-id scheme a corpus happened to use. A fixed token window does not.

**What it is worth, measured before it was built.** A most-frequent-sense prior
already reaches 0.8992 on this population, and only 6.29 of the remaining 10.08
points are reachable at all — the rest name senses UMLS does not carry. So this
rung competes for roughly 0.86% of the gold. It exists because a wrong answer on
these particular forms is clinically misleading in a way a missing answer is not,
not because the accuracy is where the value is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from robustehr.resources import load_yaml, resource_sha256
from robustehr.types import Span

CUES_RESOURCE = "abbrev_cues.yaml"

#: Word tokens for cue comparison. Explicit ASCII rather than ``\w``, which is
#: Unicode-dependent and banned by the determinism lint for that reason.
_WORD = re.compile(r"[A-Za-z0-9]+")


class Outcome(StrEnum):
    """What the vote concluded. Every mention gets exactly one."""

    RESOLVED = "resolved"
    NO_CUES = "no_cues"
    """No sense's cues appeared in the window."""
    CONFLICT = "conflict"
    """Two or more senses fired. The most informative kind of abstention."""
    NOT_AMBIGUOUS = "not_ambiguous"
    """The form has no cue entry; this rung has no opinion about it."""


@dataclass(frozen=True, slots=True)
class Sense:
    name: str
    cues: tuple[str, ...]
    """Sorted, so the resource cannot depend on iteration order."""


@dataclass(frozen=True, slots=True)
class CueEntry:
    short: str
    senses: tuple[Sense, ...]
    held_out: bool
    """False if the cues were authored after reading this form's gold instances.

    Such a form is excluded from reported accuracy: an in-sample cue list scores
    whatever its author wants it to.
    """
    note: str = ""


@dataclass(frozen=True, slots=True)
class Vote:
    """The outcome of one anchor vote."""

    outcome: Outcome
    sense: str | None = None
    fired: tuple[str, ...] = ()
    """Every sense whose cues appeared — length != 1 means abstention."""

    @property
    def resolved(self) -> bool:
        return self.outcome is Outcome.RESOLVED


@dataclass(frozen=True, slots=True)
class CueLexicon:
    entries: dict[str, CueEntry]
    window_tokens: int
    sha256: str

    def vote(self, text: str, span: Span) -> Vote:
        """Resolve the short form at ``span``, or abstain with a reason."""
        entry = self.entries.get(span.surface(text).strip().lower())
        if entry is None:
            return Vote(Outcome.NOT_AMBIGUOUS)
        window = _window_tokens(text, span, self.window_tokens)
        fired = tuple(
            sense.name for sense in entry.senses if any(cue in window for cue in sense.cues)
        )
        if len(fired) == 1:
            return Vote(Outcome.RESOLVED, sense=fired[0], fired=fired)
        return Vote(Outcome.CONFLICT if fired else Outcome.NO_CUES, fired=fired)

    def __len__(self) -> int:
        return len(self.entries)


def _window_tokens(text: str, span: Span, size: int) -> frozenset[str]:
    """Lowercased word tokens within ``size`` tokens either side of the span.

    Symmetric on purpose. A cue is as informative before the mention as after —
    ``on RA`` and ``RA sat 98%`` are both decisive — and an asymmetric window
    would encode an assumption about clinical word order that nothing supports.
    """
    before = [m.group(0).lower() for m in _WORD.finditer(text[: span.start])][-size:]
    after = [m.group(0).lower() for m in _WORD.finditer(text[span.end :])][:size]
    return frozenset(before + after)


@lru_cache(maxsize=1)
def load_cues() -> CueLexicon:
    raw = load_yaml(CUES_RESOURCE)
    entries: dict[str, CueEntry] = {}
    for short, body in raw["cues"].items():
        senses = tuple(
            Sense(name=str(s["sense"]), cues=tuple(sorted(str(c).lower() for c in s["cues"])))
            for s in body["senses"]
        )
        entries[str(short).lower()] = CueEntry(
            short=str(short).lower(),
            senses=senses,
            held_out=bool(body.get("held_out", False)),
            note=str(body.get("note", "")).strip(),
        )
    _check_consistency(entries)
    return CueLexicon(
        entries=entries,
        window_tokens=int(raw["window_tokens"]),
        sha256=resource_sha256(CUES_RESOURCE),
    )


def _check_consistency(entries: dict[str, CueEntry]) -> None:
    """Refuse a cue set that cannot decide.

    A cue shared between two senses of the same form can never resolve anything:
    it fires both, which is a conflict, which abstains. Shipping it would look
    like coverage while contributing only abstentions.
    """
    for short, entry in sorted(entries.items()):
        seen: dict[str, str] = {}
        for sense in entry.senses:
            if not sense.cues:
                raise ValueError(f"{short!r}: sense {sense.name!r} has no cues")
            for cue in sense.cues:
                if cue in seen and seen[cue] != sense.name:
                    raise ValueError(
                        f"{short!r}: cue {cue!r} is claimed by both "
                        f"{seen[cue]!r} and {sense.name!r}, so it can only ever "
                        "produce a conflict and never a resolution"
                    )
                seen[cue] = sense.name
                if not _WORD.fullmatch(cue):
                    raise ValueError(
                        f"{short!r}: cue {cue!r} is not a literal word token; "
                        "cues are compared as lowercased tokens, not patterns"
                    )


__all__ = [
    "CUES_RESOURCE",
    "CueEntry",
    "CueLexicon",
    "Outcome",
    "Sense",
    "Vote",
    "load_cues",
]
