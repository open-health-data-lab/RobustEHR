"""One entry point that runs the concept-matching stages in order.

Until this existed, stages 3a, 3b and 3c were reachable only from evaluation
scripts, and the CLI called :meth:`ConceptMatcher.annotate` directly. So every
measured gain described a configuration nothing in production used — the
phenotype layer in particular was built on bare matcher output while the
measurements quoted a pipeline that recovered 59% more procedures.

That gap is the reason this module is a single function rather than a
convention. A composition that has to be reassembled at each call site is one
that some call sites will get wrong, and the one that did was the one that
mattered.

The order is the pipeline's order and is not arbitrary:

1. **candidate generation and ranking** — the matcher over the whole document.
2. **structural expansion** (3a/3b) — spans the matcher cannot reach, because a
   label like ``Creat`` is below its length floor and absent from the
   terminology. Added, never overriding.
3. **contextual disambiguation** (3c) — for spans whose surface is a known
   ambiguous form, replace the concept when nearby words decide it, and leave it
   alone when they do not.

Stage 3 only *adds* mentions or *replaces* a concept on an existing span. It
never removes one and never edits text: every span here is an offset into the
note as written.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from robustehr.concepts.anchors import CueLexicon, load_cues
from robustehr.concepts.matcher import ConceptMatcher, Mention, MentionIndex
from robustehr.concepts.structural import resolve_labels
from robustehr.document import Document


def annotate_document(
    doc: Document,
    matcher: ConceptMatcher,
    *,
    structural: bool = True,
    expand: bool = True,
    disambiguate: bool = True,
    include_exam_labels: bool = False,
) -> MentionIndex:
    """Concept mentions over one document, with the stage-3 recovery applied.

    Every flag defaults to the measured-best configuration rather than to the
    most conservative one, because a default nobody benchmarks is a default
    nobody should trust. ``include_exam_labels`` is the exception: it was built,
    measured in isolation, and does not pay for itself.
    """
    mentions = list(matcher.annotate(doc.text).mentions)
    if structural:
        mentions += [
            m
            for m in resolve_labels(
                doc,
                matcher,
                expand=expand,
                include_exam_labels=include_exam_labels,
            )
            if isinstance(m, Mention)
        ]
    if disambiguate:
        mentions = _apply_cues(doc, matcher, mentions, load_cues())
    mentions.sort(key=lambda m: (m.span.start, m.span.end, m.cui))
    return MentionIndex(tuple(mentions))


def _apply_cues(
    doc: Document,
    matcher: ConceptMatcher,
    mentions: list[Mention],
    lexicon: CueLexicon,
) -> list[Mention]:
    """Replace a concept where nearby words decide an ambiguous short form.

    The cue file names senses in **English, not in CUIs** — a cue list carrying
    concept identifiers would be a terminology derivative and could not ship. So
    a resolved sense is a *long form*, and it reaches a concept the same way an
    expansion does: by being looked up. Stage 3b and stage 3c differ only in how
    the long form is chosen, which is why they share this path.

    A vote that abstains leaves the mention exactly as it was. Abstention here
    means "no opinion", not "delete" — the matcher's answer may still be right,
    and discarding it would trade a possible error for a certain miss.
    """
    out: list[Mention] = []
    resolved: dict[str, tuple[str, frozenset[str]]] = {}
    for mention in mentions:
        vote = lexicon.vote(doc.text, mention.span)
        if not vote.resolved or vote.sense is None:
            out.append(mention)
            continue
        if vote.sense not in resolved:
            found = matcher.annotate(vote.sense).mentions
            whole = [m for m in found if m.span.end - m.span.start == len(vote.sense)]
            resolved[vote.sense] = (whole[0].cui, whole[0].tuis) if whole else ("", frozenset())
        cui, tuis = resolved[vote.sense]
        # Span and surface stay as they are in the note; only the concept moves.
        out.append(mention if not tuis else replace(mention, cui=cui, tuis=tuis))
    return out


def mention_index(doc: Document, matcher: Any | None, **kwargs: Any) -> MentionIndex:
    """``annotate_document``, tolerating a matcher that was never built.

    ``phenotype_scope=agnostic`` runs must not require a UMLS index, so callers
    that may or may not have one get an empty index rather than a branch.
    """
    if matcher is None:
        return MentionIndex(())
    return annotate_document(doc, matcher, **kwargs)


def qualify_document(doc: Document, mentions: MentionIndex) -> Any:
    """Stage 8 over a document's mentions, using *our* sentence boundaries.

    A sibling of `annotate_document` rather than part of it. Detection and
    assertion stay separable because that is what makes each measurable on its
    own: `assertion_accuracy.json` scores assertion against supplied gold spans,
    which is only meaningful while the two are not fused. So this returns a
    span-keyed `AssertionIndex` beside the `MentionIndex`, never a field on
    `Mention`.

    **Why our boundaries and not PyRuSH's.** ConText scopes a cue to a sentence,
    so the segmenter decides how far a negation reaches. Measured, not assumed:

    * on the NegEx gold the two are **identical** (0.9289 F1 both) — every row
      there is one sentence, so the question cannot arise;
    * on multi-sentence structured text, `assertion_deid_invariance.json` gives
      our boundaries **1.0000 accuracy at 0.0000 instability** against PyRuSH's
      **0.6071 at 0.2500** — PyRuSH merges list items under three
      de-identification conventions, including MIMIC-III's and MIMIC-IV's, and a
      negation cue in one item then marks an active diagnosis in the next.

    Returns an empty index when medspaCy is absent, so an install without the
    ``clinical`` extra degrades the way `mention_index` does for the matcher.
    """
    from robustehr.concepts.context import AssertionIndex

    spans = tuple(m.span for m in mentions.mentions)
    if not spans:
        return AssertionIndex()
    try:
        from robustehr.concepts.context import qualify
    except ImportError:  # pragma: no cover - clinical extra not installed
        return AssertionIndex()
    boundaries = tuple(s.span.start for s in doc.sentences.sentences)
    return qualify(doc.text, spans, boundaries=boundaries)


__all__ = ["annotate_document", "mention_index", "qualify_document"]
