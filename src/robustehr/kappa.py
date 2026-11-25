"""Canonicalizers: the proof obligation behind an invariant contract.

The taxonomy claims some operators can *never* alter clinical reference — not
for any phenotype, not in any document. That is a strong claim, and the whole
point of the contract lattice is that it is discharged by a machine rather than
asserted in a table.

The mechanism: each such operator names a projection ``κ`` that throws away
exactly what the operator is permitted to touch. The test suite then asserts

    κ(apply(operator, d)) == κ(d)

for every document in the corpus at every severity. An operator whose κ test
fails on even one note is demoted to ``CONDITIONALLY_PRESERVING`` — the taxonomy
self-corrects rather than shipping a false guarantee.

Choosing κ is where the honesty lives. A projection that throws away too much
proves nothing: ``lambda text: ""`` passes for every operator. So each one here
states what it *keeps*, and keeping the token sequence is the common core —
because if the sequence of clinical tokens is unchanged, no clinical reference
can have changed.
"""

from __future__ import annotations

from collections.abc import Callable

from robustehr.segment.blocks import detect_lists
from robustehr.segment.deid import SCHEME_PATTERNS, DeidScheme
from robustehr.segment.lines import split_lines
from robustehr.segment.tokens import tokenize

#: A canonicalizer maps text to a comparable projection.
Canonicalizer = Callable[[str], object]

_DEID_SENTINEL = "\x00DEID\x00"


def content_tokens(text: str) -> tuple[str, ...]:
    """The sequence of word, number and mixed tokens.

    Keeps every clinical token and its order; discards whitespace, punctuation
    and line structure. This is the projection for operators that only move
    whitespace around: if this is unchanged, the reading of the note is
    unchanged.
    """
    return tuple(t.lower for t in tokenize(text).content())


def content_tokens_masked_deid(text: str) -> tuple[str, ...]:
    """Content tokens with every de-identification mask reduced to a sentinel.

    The projection for mask restyling: ``___`` becoming ``[**Name**]`` is
    permitted, but the surrounding clinical tokens and the *positions* of the
    masks among them must be identical. Collapsing masks to one symbol rather
    than dropping them is deliberate — dropping them would let an operator
    delete a mask entirely and still pass.

    Masks are matched **across every known convention**, not just the document's
    dominant one. Restyling at a partial severity produces a genuinely
    mixed-convention document — some ``___``, some ``[**REDACTED**]`` — and a
    projection that only recognised the majority scheme would read the restyled
    minority as ordinary content tokens and report a spurious violation.
    """
    spans: list[tuple[int, int]] = []
    for scheme, pattern in SCHEME_PATTERNS:
        if scheme is DeidScheme.NONE:
            continue
        spans.extend(match.span() for match in pattern.finditer(text))
    spans.sort()

    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            continue  # already claimed by a more specific pattern
        merged.append((start, end))

    out: list[str] = []
    cursor = 0
    for start, end in merged:
        for token in tokenize(text[cursor:start]).content():
            out.append(token.lower)
        out.append(_DEID_SENTINEL)
        cursor = end
    for token in tokenize(text[cursor:]).content():
        out.append(token.lower)
    return tuple(out)


def content_tokens_casefolded(text: str) -> tuple[str, ...]:
    """Content tokens, case-folded.

    For operators that may change casing but nothing else. Note this is a
    genuinely weaker guarantee than :func:`content_tokens`: case carries meaning
    in clinical text — it is much of what separates an abbreviation from a word
    — so an operator using this projection can only claim invariance *up to
    case*, and the taxonomy records that.
    """
    return tuple(t.lower for t in tokenize(text).content())


def content_tokens_without_list_markers(text: str) -> tuple[str, ...]:
    """Content tokens with list markers projected away.

    The projection for marker stripping, and it needs to exist because
    ``content_tokens`` is the wrong one: a numbered marker like ``1.`` tokenizes
    as a *number*, which counts as content, so removing it changes the
    content-token sequence and the operator would be demoted on a technicality.

    What the operator actually guarantees is narrower and still worth stating:
    the prose survives untouched, and only the enumeration around it goes. This
    projection says exactly that by dropping the tokens the list detector
    identifies as markers, so the property test compares what remains.
    """
    lines = split_lines(text)
    marker_spans = [
        item.marker
        for block in detect_lists(text, lines)
        for item in block.items
        if not item.marker.is_empty
    ]
    return tuple(
        t.lower
        for t in tokenize(text).content()
        if not any(m.overlaps(t.span) for m in marker_spans)
    )


def token_multiset(text: str) -> tuple[tuple[str, int], ...]:
    """Content tokens as a sorted multiset, ignoring order.

    For operators that reorder whole blocks without editing them. Weaker than
    the sequence projection by exactly the amount of information order carries,
    which for a note with temporality-sensitive sections is not nothing — hence
    section reordering is *not* an invariant operator, and this projection
    exists only for block moves that are provably order-irrelevant.
    """
    counts: dict[str, int] = {}
    for token in content_tokens(text):
        counts[token] = counts.get(token, 0) + 1
    return tuple(sorted(counts.items()))


def identity(text: str) -> str:
    """The whole document. For null controls, where nothing may change."""
    return text


#: Named projections, referenced from ``taxonomy.yaml`` by these keys.
CANONICALIZERS: dict[str, Canonicalizer] = {
    "content_tokens_without_list_markers": content_tokens_without_list_markers,
    "content_tokens": content_tokens,
    "content_tokens_masked_deid": content_tokens_masked_deid,
    "content_tokens_casefolded": content_tokens_casefolded,
    "token_multiset": token_multiset,
    "identity": identity,
}


def get(name: str) -> Canonicalizer:
    if name not in CANONICALIZERS:
        raise KeyError(
            f"unknown canonicalizer {name!r}; known: {sorted(CANONICALIZERS)}. "
            "An INVARIANT_BY_CONSTRUCTION operator must name a projection that "
            "can be checked, otherwise the contract is only an assertion."
        )
    return CANONICALIZERS[name]


def holds(name: str, before: str, after: str) -> bool:
    projection = get(name)
    return projection(before) == projection(after)


__all__ = [
    "CANONICALIZERS",
    "Canonicalizer",
    "content_tokens",
    "content_tokens_casefolded",
    "content_tokens_masked_deid",
    "get",
    "holds",
    "identity",
    "token_multiset",
]
