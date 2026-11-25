"""Surface anchoring: the diagnosis as a clinician writes it, whatever CUI it carries.

**Why a third direction exists at all.** Chapters 13 and 14 of the methodology
build a phenotype's target in *concept space* — seeds, crosswalked to CUIs,
expanded through relations, vetted. A perturbation aimed at that target operates
in *surface space*, on characters in a note. Those are not the same
neighbourhood, and two structural properties of the terminology guarantee they
never will be:

* **A disease set cannot reach its own causative organism.** `Clostridium
  difficile` is a Bacterium. It has no ``is-a`` path to *C. difficile colitis* at
  any hop count, and a facet filter keeping disorders drops it on sight. Yet it
  is the single most decisive string a reader uses.
* **A disease set cannot reach its own qualifier.** `metastatic`, `systolic`,
  `reduced` and `diastolic` are modifier concepts. The words carrying the
  distinction between HFpEF and HFrEF are qualifiers, and no walk over a disorder
  hierarchy returns one.

Neither is an oversight in the closure, and neither is fixable by tuning support
or hop count: the edges do not exist to traverse. The honest response is to stop
defining the target by identifier alone and admit a second, independent warrant.

**What an anchor is.** A literal surface form that *is* the diagnosis. Membership
is tested against the written text rather than against a concept set, so an
anchor admits evidence the matcher grounded to an out-of-set CUI, to the wrong
CUI, or to no CUI at all. That last case is the abbreviation gap: ``cdiff`` and
``t2dm`` produce no candidate for stage 3c to re-ground, because stage 3c
replaces the concept on a span the matcher already found and cannot create one.

**What an anchor is not.** It is not a repair for a misgrounding. `CHF` grounding
to *Congenital Hepatic Fibrosis* stays a matcher error and is pinned out by
negative fixtures; widening a set to cover it would hide the fault. An anchor
matches the surface it declares, exactly, and grounds nothing.

**Licensing.** Anchors are author-written English, not Metathesaurus strings.
The package ships concept sets as identifiers with hashed surfaces because UMLS
strings are licensed; that restriction does not reach text this project wrote,
so the anchor resource ships in the clear. The distinction is the reason the
resource carries no CUIs.

**Stop surfaces, the opposite move.** A set member can be inert or harmful
because of how its surface behaves rather than because of what the concept
means. ``status`` is a legitimate UMLS string for an in-set concept and matches
"volume status", "activity status" and "status post"; ``secondary`` matches
"secondary to hypoperfusion". Rejecting them is a matcher-layer decision about a
surface, not a vetting decision about a concept, and it belongs here rather than
in the closure.

Two mechanisms, because one does not cover the class:

* **A declared list**, per phenotype and global. Required for surfaces that carry
  a high-precision clinical semantic type and are therefore *absent* from the
  general-English vocabulary by construction — ``secondary``, ``ice``, ``doe``.
  No derivation reaches them; they have to be named.
* **A general-English floor**, so a phenotype added tomorrow gets some
  protection before anyone curates it: a single-token surface that is ordinary
  English is not evidence unless the phenotype anchors it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import pairwise
from typing import Any

from robustehr.lexical import general_english
from robustehr.resources import load_yaml
from robustehr.types import Span

ANCHORS_RESOURCE = "phenotype_anchors.yaml"

#: The review states an anchor resource may declare, and what each means.
#:
#: ``llm``: forms proposed and reviewed by language models only.
#: ``llm+hand``: an author curated forms by hand after the model passes; this is
#: editorial review, not a clinician's review of record.
#: ``llm+clinician``: a clinician has read the review sheet end to end.
#:
#: Absent means the resource predates the field. It is reported as ``"absent"``
#: and never coerced to ``llm``, because a target built under an undeclared
#: state is a different treatment from one built under a declared one.
VETTED_BY: tuple[str, ...] = ("llm", "llm+hand", "llm+clinician")

#: What counts as *inside a word* when deciding an anchor's boundaries.
#:
#: Explicit rather than ``\b``, which is defined in terms of ``\w`` and therefore
#: moves with the Unicode database version. Two machines on different CPython
#: point releases would disagree about what matched, and every dose denominator
#: downstream would move with them. The AST lint bans the shorthand for exactly
#: this reason; see ``tests/unit/test_determinism_lint.py``.
_WORD_CHAR = "[A-Za-z0-9]"

#: Whitespace between the tokens of a multi-word anchor. Also explicit, also
#: because ``\s`` is Unicode-dependent. A newline counts: clinical text wraps
#: mid-diagnosis and "heart\nfailure" is the same phrase.
_GAP = "[ \\t\\r\\n]+"


@dataclass(frozen=True, slots=True)
class AnchorSet:
    """One phenotype's surface warrant: what to admit, and what to refuse.

    ``anchors`` are matched case-insensitively against note text. ``stop_surfaces``
    are refused as concept mentions however they grounded. A surface appearing in
    both is a declaration error and is rejected at load, because the two blocks
    make contradictory claims about the same string.
    """

    phenotype: str
    anchors: tuple[str, ...] = ()
    associated: tuple[str, ...] = ()
    """Clinical terms that ARE evidence but are not the diagnosis, and do not ground.

    The propose-then-ground direction asks a model for the terms a clinician
    associates with a phenotype and resolves each against UMLS by string lookup.
    The terms that do not resolve are not model noise — `omental caking`,
    `pericolic fat stranding`, `positive hepatojugular reflux`, `fruity breath
    odor`, and, for the phenotype whose whole definition it is, `preserved left
    ventricular ejection fraction`. They fail because no UMLS string matches
    them, which is a property of the vocabulary and not a verdict on the term.

    A term that cannot be grounded can still be matched. Carried here, such terms
    enter the target as evidence on the surface warrant at tier ``associated``
    rather than ``anchor``: they support the phenotype without being its name,
    and the reach gate distinguishes the two, because an arm that flattened every
    associated finding while leaving the diagnosis intact has not tested what it
    claims to.
    """
    stop_surfaces: frozenset[str] = field(default_factory=frozenset)

    @property
    def declared(self) -> bool:
        """Whether this phenotype has a surface warrant at all.

        Empty and absent are different states, as everywhere else in this
        package. A phenotype with no anchors falls back to CUI membership alone,
        which is the pre-anchor behaviour, and the coverage artifact reports it
        rather than letting it look like a phenotype whose diagnosis is never
        written.
        """
        return bool(self.anchors or self.associated)


def _pattern_for(anchors: tuple[str, ...]) -> re.Pattern[str] | None:
    """One alternation over every anchor, longest first.

    Longest-first matters: ``type 2 diabetes`` and ``diabetes`` may both be
    anchors, and Python's alternation takes the first branch that matches rather
    than the longest, so a shorter anchor listed earlier would truncate the span
    and leave the rest of the diagnosis uncorrupted.
    """
    if not anchors:
        return None
    branches = []
    for anchor in sorted(anchors, key=lambda a: (-len(a), a)):
        body = _anchor_pattern(anchor)
        if body:
            branches.append(body)
    if not branches:
        return None
    body = "|".join(branches)
    return re.compile(
        f"(?<!{_WORD_CHAR})(?:{body})(?!{_WORD_CHAR})",
        re.IGNORECASE,
    )


#: Separator inside an abbreviation, where the period is optional.
#:
#: Enumeration does not work here and was tried. A model listing the ways
#: `Clostridioides difficile infection` is written returned `c. diff`, `c diff`
#: and `cdiff` but not `c.diff`, which is the form notes most often use — and
#: the miss was invisible until the corpora were audited word by word: 30% of
#: `C. diff` occurrences went uncorrupted while the arm reported 99% reach,
#: because the spans it did declare were all treated.
#:
#: The variants are mechanical, so the matcher generates them rather than asking
#: for them. A separator run containing a period matches with or without either
#: the period or the space; one that is only whitespace still requires
#: whitespace, so `heart failure` does not start matching `heartfailure`.
_DOTTED_GAP = "[. \t\r\n]*"

#: Between the letters of an initialism: punctuation may vary but may not
#: disappear. See `_anchor_pattern` for the collision this prevents.
_DOTTED_SEPARATOR = "[. \t\r\n]+"

#: Runs of letters and digits, and everything between them.
_RUN = re.compile("[A-Za-z0-9]+")


def _anchor_pattern(anchor: str) -> str:
    """One anchor as a regex, with punctuation variants folded in.

    **A separator may vanish only when a neighbouring run is more than one
    character long**, and that condition is not fussiness. Without it, an
    initialism collapses onto an ordinary word: `h.a.d.`, the anchor for
    HIV-associated dementia, matched `had`, and dementia's typo arm went from
    227 edited notes to 484 — every note containing the past tense of "have".
    `m.i.d.` would take `mid` the same way.

    `c. diff` is safe because `diff` is four characters, so nothing else in the
    corpus collapses onto it. A run of single letters has no such protection,
    and the undotted form of a real initialism is almost always listed as its
    own anchor anyway — `sle`, `ftd` and `lbd` all are — so requiring the
    separator here costs nothing and stops the collision.
    """
    runs = list(_RUN.finditer(anchor))
    if not runs:
        return ""
    parts = [re.escape(runs[0].group(0))]
    for previous, current in pairwise(runs):
        separator = anchor[previous.end() : current.start()]
        substantial = len(previous.group(0)) > 1 or len(current.group(0)) > 1
        if "." in separator and substantial:
            parts.append(_DOTTED_GAP)
        elif "." in separator:
            # Initialism: the punctuation may vary, but something must separate
            # the letters or `h.a.d.` becomes `had`.
            parts.append(_DOTTED_SEPARATOR)
        else:
            parts.append(_GAP)
        parts.append(re.escape(current.group(0)))
    return "".join(parts)


@lru_cache(maxsize=256)
def _compiled(anchors: tuple[str, ...]) -> re.Pattern[str] | None:
    return _pattern_for(anchors)


def anchor_spans(text: str, anchors: AnchorSet, tier: str = "anchor") -> tuple[Span, ...]:
    """Every literal occurrence of one of this phenotype's declared surfaces.

    ``tier`` picks the block: ``anchor`` for the diagnosis as written,
    ``associated`` for clinical terms that support it without naming it. They
    are matched separately rather than as one alternation because the reach gate
    turns on the difference — an arm that flattened every associated finding and
    left the diagnosis intact has not tested the phenotype, and a single merged
    pattern could not tell the caller that.

    Non-overlapping and left-to-right, which `re.finditer` gives for free and
    which is what the caller needs: two surfaces matching the same characters
    are one piece of evidence, not two, and counting them twice would inflate
    the denominator of every reach measurement.
    """
    forms = anchors.associated if tier == "associated" else anchors.anchors
    pattern = _compiled(forms)
    if pattern is None:
        return ()
    return tuple(Span(start=m.start(), end=m.end()) for m in pattern.finditer(text))


def parse_anchors(raw: Any) -> dict[str, AnchorSet]:
    """Validate and normalise a loaded anchor resource.

    Separate from :func:`load_anchors` so the validation is reachable without
    writing a file into the package tree — the clash rule below is the kind of
    thing that is only ever exercised by a test if testing it is cheap.
    """
    if not raw or "phenotypes" not in raw:
        return {}
    state = raw.get("vetted_by")
    if state is not None and str(state) not in VETTED_BY:
        raise ValueError(
            f"vetted_by {state!r} is not one of {VETTED_BY}. The review state is "
            "reported in every manifest that targets a phenotype, so it has to be "
            "one a reader can look up."
        )
    out: dict[str, AnchorSet] = {}
    for name, block in sorted(raw["phenotypes"].items()):
        anchors = tuple(str(a).strip().lower() for a in block.get("anchors", ()) if str(a).strip())
        associated = tuple(
            str(a).strip().lower() for a in block.get("associated", ()) if str(a).strip()
        )
        # A form cannot be both the diagnosis and merely associated with it, and
        # the tier decides whether the reach gate counts it. Anchor wins, since
        # it is the stronger and the hand-reviewed claim.
        associated = tuple(a for a in associated if a not in set(anchors))
        stops = frozenset(
            str(s).strip().lower() for s in block.get("stop_surfaces", ()) if str(s).strip()
        )
        clash = set(anchors) & stops
        if clash:
            raise ValueError(
                f"{name}: {sorted(clash)} declared as both anchor and stop surface. "
                "The two blocks make contradictory claims about the same string; "
                "one of them is wrong and the resource cannot say which."
            )
        out[str(name)] = AnchorSet(
            phenotype=str(name),
            anchors=anchors,
            associated=associated,
            stop_surfaces=frozenset(stops),
        )
    return out


@lru_cache(maxsize=1)
def load_anchors() -> dict[str, AnchorSet]:
    """The shipped surface anchors, by phenotype.

    Returns an empty mapping when the resource has not been built, which is the
    same degradation the facet artifacts use: an install without it keeps the
    pre-anchor behaviour rather than failing.
    """
    try:
        raw: Any = load_yaml(ANCHORS_RESOURCE)
    except FileNotFoundError:
        return {}
    return parse_anchors(raw)


@lru_cache(maxsize=1)
def global_stop_surfaces() -> frozenset[str]:
    """Surfaces no phenotype admits, however they grounded.

    Separate from the per-phenotype block because these are properties of the
    string rather than of any one phenotype: ``status`` is the wrong sense in
    every set that contains it.
    """
    try:
        raw: Any = load_yaml(ANCHORS_RESOURCE)
    except FileNotFoundError:
        return frozenset()
    if not raw:
        return frozenset()
    return frozenset(str(s).strip().lower() for s in raw.get("stop_surfaces", ()) if str(s).strip())


@lru_cache(maxsize=1)
def anchor_provenance() -> dict[str, Any]:
    """How the shipped anchor resource was reviewed, for the run manifest.

    ``vetted_by`` is one of :data:`VETTED_BY` or ``"absent"``; ``passes`` is the
    resource's own ledger of who did what, in order.
    """
    try:
        raw: Any = load_yaml(ANCHORS_RESOURCE)
    except FileNotFoundError:
        return {"vetted_by": "absent", "passes": [], "schema_version": "absent"}
    if not raw:
        return {"vetted_by": "absent", "passes": [], "schema_version": "absent"}
    return {
        "vetted_by": str(raw.get("vetted_by") or "absent"),
        "passes": [dict(p) for p in raw.get("passes", ())],
        "schema_version": str(raw.get("schema_version") or "absent"),
    }


def targeting_digest_of(raw: Any) -> str:
    """SHA-256 of what an anchor resource *targets*, ignoring how it was built.

    Covers every phenotype's anchors, associated terms and stop surfaces, and
    the global stop surfaces — exactly the strings that decide which spans a
    ``pheno=`` target admits or refuses. Excludes the review ledger, the
    ``vetted_by`` state and the per-block provenance fields, so a provenance
    edit does not look like a change of method. ``"absent"`` for an empty or
    missing resource.
    """
    if not raw or "phenotypes" not in raw:
        return "absent"
    sets = parse_anchors(raw)
    canonical = {
        "phenotypes": {
            name: {
                "anchors": list(a.anchors),
                "associated": list(a.associated),
                "stop_surfaces": sorted(a.stop_surfaces),
            }
            for name, a in sorted(sets.items())
        },
        "stop_surfaces": sorted(
            str(s).strip().lower() for s in raw.get("stop_surfaces", ()) if str(s).strip()
        ),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def targeting_digest() -> str:
    """The targeting digest of the shipped anchor resource, or ``"absent"``."""
    try:
        raw: Any = load_yaml(ANCHORS_RESOURCE)
    except FileNotFoundError:
        return "absent"
    return targeting_digest_of(raw)


def anchors_for(phenotype: str) -> AnchorSet:
    """This phenotype's surface warrant, or an empty one."""
    return load_anchors().get(phenotype, AnchorSet(phenotype=phenotype))


def is_stopped(surface: str, anchors: AnchorSet) -> bool:
    """Whether this matched surface should be refused as evidence.

    Three tests, in order of how much they were curated:

    1. The phenotype anchors it. Never stopped — an explicit declaration that
       this string *is* the diagnosis outranks every heuristic below, which is
       what makes the floor safe to apply broadly.
    2. It is declared a stop surface, globally or by this phenotype.
    3. **The floor.** A single token that is ordinary English. The shipped
       general-English list has already subtracted words carrying a
       high-precision clinical type, so ``aspirin``, ``fever``, ``pain`` and
       ``wound`` are absent from it and survive this test. That subtraction is
       what makes the floor usable at all: the unsubtracted vocabulary would
       refuse half the medication facet.

    Multi-token surfaces are never stopped by the floor. ``chest pain`` in a
    hypertension set is a closure-precision problem — a real concept, correctly
    matched, that is an association rather than a cue — and tightening the
    vetting criterion is where it belongs. Refusing it here would be this layer
    silently editing the concept set.
    """
    text = surface.strip().lower()
    if not text:
        return True
    if text in anchors.anchors or text in anchors.associated:
        return False
    if text in anchors.stop_surfaces or text in global_stop_surfaces():
        return True
    return " " not in text and text in general_english()


__all__ = [
    "ANCHORS_RESOURCE",
    "VETTED_BY",
    "AnchorSet",
    "anchor_provenance",
    "anchor_spans",
    "anchors_for",
    "global_stop_surfaces",
    "is_stopped",
    "load_anchors",
    "parse_anchors",
    "targeting_digest",
    "targeting_digest_of",
]
