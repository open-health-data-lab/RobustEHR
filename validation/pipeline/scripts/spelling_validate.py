#!/usr/bin/env python
"""What fraction of `near_miss_edit1` tokens are actually misspellings?

**The number this script exists to produce, and why the field cannot ship
without it.** `by_level.token.near_miss_edit1` counts alphabetic content tokens
that neither vocabulary carries and that sit one edit from a term one of them
does. That is a *candidate* definition, and three things satisfy it without
being errors:

    real vocabulary the lexicons miss   `refills`, `mellitus`, `hepatology`
    clinical shorthand                  `angap`, `eomi`, `dmii`, `outpt`
    junk in the terminology             a token near a UMLS string like `hngap`

So the field is named for what was measured. It becomes a misspelling rate the
day this script publishes a precision, and not before — the same gate the
phenotype concept sets pass through in `validation/methodology/14`.

**Why an LLM adjudicates.** "Is `creat` a misspelling of `cheat`, an
abbreviation for creatinine, or a word?" is a judgement about clinical usage,
and no rule available here settles it. The alternative is a clinician's time on
several hundred tokens, which this makes cheap to prepare and easy to check: the
sample is deterministic, the verdicts are cached, and `--review` writes the same
sample as a file a human can overrule.

**What leaves the machine.** One token and its nearest lexicon neighbour, with
no surrounding text. That is the minimum the question needs and it carries no
context, but it is still corpus-derived: `data/` only, and the disclosure in
`robustehr.llm.configure` applies.

Writes `validation/measurements/spelling_precision.json`: counts, verdicts by
category, and the precision. Never note text beyond the sampled tokens
themselves, which are the object of the measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

#: What a verdict may be. `misspelling` is the numerator; everything else is a
#: named way for the measure to be wrong, because "precision 0.31" is far less
#: useful than "precision 0.31, and 0.44 of the rest are abbreviations".
VERDICTS = ("misspelling", "abbreviation", "real_word", "unclear")

PROMPT = """You are adjudicating candidate misspellings from clinical discharge summaries.

For each token below you are given the token as it appeared and the closest term
in a reference vocabulary (general English plus a UMLS-derived clinical list).
The token is absent from both vocabularies and is exactly one edit from the
neighbour shown. The neighbour is often NOT what the author meant -- it is
whatever happened to be one edit away.

Classify each token:

  misspelling   a mistyping of a real word. The intended word may or may not be
                the neighbour shown.
  abbreviation  clinical or institutional shorthand, written as intended
                (AnGap, EOMI, DMII, outpt, nebs, soln, q6h).
  real_word     a correct word or term the vocabularies simply do not carry
                (refills, mellitus, hepatology, tunneled, nontender).
  unclear       genuinely cannot be decided from the token alone.

Prefer `abbreviation` and `real_word` over `misspelling` when uncertain: the
measurement this feeds is a claim about how often the automatic filter is RIGHT,
and an adjudicator biased toward agreeing with it produces a flattering number
rather than a true one.

Answer with one line per token, in the order given, formatted exactly:

INDEX<TAB>VERDICT

Tokens:
{items}
"""


def sample(surfaces: dict[str, int], size: int) -> list[str]:
    """A deterministic sample of distinct surfaces.

    Hash-ranked rather than randomly drawn, for the reason every selection in
    this package is: `random` and `hash()` are banned under `src/` and a sample
    that changes between runs cannot be re-adjudicated. Rank by BLAKE2b of the
    surface, take the first `size`.
    """
    ranked = sorted(surfaces, key=lambda w: hashlib.blake2b(w.encode(), digest_size=8).digest())
    return ranked[:size]


def adjudicate(tokens: list[tuple[str, str | None]], model: str | None, batch: int) -> list[str]:
    """One verdict per token, from the configured model, cached by prompt."""
    from robustehr.llm import complete, configure

    config = configure(model)
    verdicts: list[str] = []
    for start in range(0, len(tokens), batch):
        chunk = tokens[start : start + batch]
        items = "\n".join(
            f"{i}\t{word}\tnearest: {near or '(none)'}" for i, (word, near) in enumerate(chunk)
        )
        reply = complete(config, PROMPT.format(items=items))
        got: dict[int, str] = {}
        for line in reply.splitlines():
            parts = line.replace("\t", " ").split()
            if len(parts) >= 2 and parts[0].strip(".:").isdigit():
                verdict = parts[-1].strip().lower()
                if verdict in VERDICTS:
                    got[int(parts[0].strip(".:"))] = verdict
        # A missing line is `unclear`, not a dropped row: the denominator must
        # stay the sample size, or precision is computed over whatever the model
        # happened to answer.
        verdicts.extend(got.get(i, "unclear") for i in range(len(chunk)))
    return verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--limit", type=int, default=200, help="notes to scan")
    parser.add_argument("--sample", type=int, default=200, help="distinct surfaces to adjudicate")
    parser.add_argument("--lexicon", type=Path, default=Path("data/lexicon/clinical_tokens.txt"))
    parser.add_argument("--model", default=None, help="OpenRouter model id; no default")
    parser.add_argument("--batch", type=int, default=40)
    parser.add_argument(
        "--review",
        type=Path,
        default=None,
        help="write the sample as a TSV for human adjudication and stop. "
        "Corpus-derived: keep it under data/.",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("validation/measurements/spelling_precision.json")
    )
    args = parser.parse_args(argv)

    from robustehr.corpus import read_documents
    from robustehr.lexicon import load_clinical_lexicon
    from robustehr.metrics.spelling import deletion_index, nearest, profile_near_miss

    if not args.lexicon.exists():
        print(f"no clinical lexicon at {args.lexicon}", file=sys.stderr)
        return 2
    lexicon = load_clinical_lexicon(args.lexicon)

    surfaces: Counter[str] = Counter()
    notes = 0
    for doc in read_documents(args.corpus, limit=args.limit):
        notes += 1
        surfaces.update(profile_near_miss(doc, lexicon, args.lexicon).surfaces)
    if not surfaces:
        print("no near-miss surfaces found", file=sys.stderr)
        return 1

    index = deletion_index(args.lexicon)
    chosen = sample(dict(surfaces), args.sample)
    pairs = [(w, nearest(w, index)) for w in chosen]

    if args.review is not None:
        args.review.parent.mkdir(parents=True, exist_ok=True)
        lines = ["token\tnearest\toccurrences\tverdict"]
        lines += [f"{w}\t{n or ''}\t{surfaces[w]}\t" for w, n in pairs]
        args.review.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {len(pairs)} rows to {args.review} — corpus-derived, keep under data/")
        return 0

    try:
        verdicts = adjudicate(pairs, args.model, args.batch)
    except Exception as exc:  # report and exit, never half-write
        print(f"adjudication unavailable: {exc}", file=sys.stderr)
        return 1

    counts = Counter(verdicts)
    misspellings = counts["misspelling"]
    hapax = [w for w, _ in pairs if surfaces[w] == 1]
    hapax_hits = sum(
        1
        for (w, _), v in zip(pairs, verdicts, strict=True)
        if v == "misspelling" and surfaces[w] == 1
    )
    # Two precisions, because the sample is of TYPES and the reported field
    # counts OCCURRENCES. They differ a lot and the gap is the finding: the
    # frequent near-miss surfaces are the vocabulary ones (`refills` 26 times,
    # `creat` 7), so weighting by occurrence drags precision down. A ratio
    # estimator over a uniform type sample is what carries the type answer to
    # the token population.
    occurrences = sum(surfaces[w] for w, _ in pairs)
    weighted = sum(
        surfaces[w] for (w, _), v in zip(pairs, verdicts, strict=True) if v == "misspelling"
    )
    payload: dict[str, Any] = {
        "question": "what fraction of near_miss_edit1 surfaces are misspellings?",
        "corpus": args.corpus.name,
        "notes_scanned": notes,
        "distinct_surfaces": len(surfaces),
        "sampled": len(pairs),
        "model": args.model,
        "verdicts": dict(counts.most_common()),
        "precision_by_type": round(misspellings / len(pairs), 4),
        "precision_by_occurrence": round(weighted / occurrences, 4) if occurrences else None,
        "precision_hapax_only": round(hapax_hits / len(hapax), 4) if hapax else None,
        "hapax_in_sample": len(hapax),
        "occurrences_in_sample": occurrences,
        "note": (
            "precision of the AUTOMATIC filter, adjudicated by a model rather "
            "than a clinician. `by_type` samples distinct surfaces uniformly; "
            "`by_occurrence` is the ratio estimator that applies to the "
            "`near_miss_edit1` TOTAL, which counts occurrences, and is the "
            "lower of the two because frequent near-misses are vocabulary. "
            "Both bound what the field may be called: until they are high it is "
            "a candidate count, not a misspelling rate. `--review` writes the "
            "same deterministic sample as a TSV for human adjudication, which "
            "supersedes this."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    width = max(len(v) for v in counts)
    for verdict, n in counts.most_common():
        print(f"  {verdict:<{width}}  {n:>4}  {n / len(pairs):.3f}")
    print(
        f"\nprecision by type {payload['precision_by_type']}  "
        f"by occurrence {payload['precision_by_occurrence']}  "
        f"hapax only {payload['precision_hapax_only']}"
    )
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
