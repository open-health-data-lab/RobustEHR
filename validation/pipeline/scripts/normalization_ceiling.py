#!/usr/bin/env python
"""V0 for stage 4: is lexical normalization worth building?

The fourth gate, and the same question as the others: **how much is left to
recover, before anything is built to recover it.**

Stage 4 exists because a note writes `hyperkalemic` where the terminology holds
`hyperkalemia`, and `renal` where it holds `kidney`. NLM built the instrument for
exactly this — ``MRXNS_ENG`` is the Metathesaurus indexed by *normalized* string,
where normalization lowercases, strips inflection, drops stopwords and sorts the
remaining words. So the reuse rule applies in its strongest form: the component
already exists, and the only question is what it buys here.

**Only the note side needs normalizing.** ``MRXNS_ENG`` ships the terminology
already normalized, so this measures a lookup rather than a matching algorithm.

The note-side approximation has to *agree* with NLM's `luinorm`, not merely
resemble it — a key that differs by one character matches nothing. Rather than
reimplement it, the gate generates a small set of **candidate** normalizations
per surface and counts a hit if any of them lands. That makes the result an
**upper bound**: a real normalizer produces one key, not several, so it can only
do worse. An upper bound is the right shape for a gate, because a small one
closes the question.

The candidates are the sorted-lowercase form and the same with one inflectional
ending stripped per word. Both are tried because stripping is not always right:
`shortness` becomes `shortnes` under a naive `-s` rule, while `luinorm` leaves it
alone, and a gate that only tried the stripped form would report a miss the
instrument would not make.

What the gate answers, over gold spans the shipped matcher currently misses:

* how many would a normalized lookup reach at all;
* of those, how many reach the **right** concept rather than merely some concept;
* and what the residue looks like, since that is what stage 4 cannot fix.
"""

from __future__ import annotations

import argparse
import json
import re
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.concepts.matcher import ConceptMatcher
from robustehr.concepts.pipeline import annotate_document
from robustehr.document import Document
from robustehr.eval import snomed_el

#: Inflectional endings stripped by the conservative approximation, longest
#: first so `-ies` is tried before `-s`. Derivational morphology (`-ic`, `-al`,
#: `-ous`) is deliberately absent: `hyperkalemic -> hyperkalemia` is a change of
#: part of speech, not an inflection, and treating it as one would let the gate
#: claim recoveries a normalizer would not make.
SUFFIXES = ("ies", "ing", "ed", "es", "s")

#: Longest normalized string worth indexing. Beyond this the entry is a full
#: drug-ingredient list rather than a term, and no note surface will match it.
MAX_NSTR_CHARS = 80

_WORD = re.compile(r"[A-Za-z0-9]+")


def _strip(word: str) -> str:
    for suffix in SUFFIXES:
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def normalizations(surface: str) -> tuple[str, ...]:
    """Candidate normalized keys for one surface.

    Sorting the words is what makes `heart failure` and `failure, heart` the
    same key, and is why ``MRXNS_ENG`` is word-sorted in the first place.

    Two candidates rather than one, for the reason in the module docstring: a
    naive inflection strip disagrees with `luinorm` on words like `shortness`,
    and trying both keeps the gate an upper bound instead of silently reporting
    misses the real instrument would not make.
    """
    words = [m.group(0) for m in _WORD.finditer(surface.lower())]
    if not words:
        return ()
    plain = " ".join(sorted(words))
    stripped = " ".join(sorted(_strip(w) for w in words))
    return (plain,) if plain == stripped else (plain, stripped)


def build_index(release: Any, max_chars: int) -> dict[str, set[str]]:
    """Normalized string -> the concepts carrying it."""
    import duckdb

    con = duckdb.connect(":memory:")
    rows = con.execute(f"""
        SELECT nstr, list(DISTINCT cui ORDER BY cui) FROM read_csv(
            '{release.rrf("MRXNS_ENG.RRF")}', delim='|', header=false, quote='',
            names=['lat', 'nstr', 'cui', 'lui', 'sui', 'extra'], all_varchar=true)
        WHERE lat = 'ENG' AND length(nstr) <= {max_chars}
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    return {str(n): {str(c) for c in cuis} for n, cuis in rows}


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/snomed_el"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--umls", type=Path, default=Path("data/umls"))
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--split", default="test")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    from robustehr.concepts.umls import UmlsRelease

    corpus = snomed_el.load(args.root, limit=args.limit)
    if args.split:
        corpus = corpus.split(args.split)
    cui_to_codes = json.loads((args.root / "cui_snomed.json").read_text(encoding="utf-8"))
    normalized = build_index(UmlsRelease.discover(args.umls), MAX_NSTR_CHARS)

    matcher = ConceptMatcher(args.index)
    missed = 0
    reachable = 0
    correct = 0
    residue: Counter[str] = Counter()
    for note_id, text in sorted(corpus.notes.items()):
        doc = Document.from_text(text, uid=note_id)
        found = annotate_document(doc, matcher)
        covered: set[int] = set()
        for mention in found.mentions:
            covered.update(range(mention.span.start, mention.span.end))
        for gold in corpus.for_note(note_id):
            if any(i in covered for i in range(gold.span.start, gold.span.end)):
                continue
            missed += 1
            cuis: set[str] = set()
            for key in normalizations(gold.surface):
                cuis |= normalized.get(key, set())
            if not cuis:
                residue[gold.surface.strip().lower()] += 1
                continue
            reachable += 1
            if any(gold.concept_id in cui_to_codes.get(c, ()) for c in cuis):
                correct += 1

    payload = {
        "question": "How many currently-missed gold spans would a normalized lookup reach?",
        "instrument": (
            "MRXNS_ENG, NLM's Metathesaurus indexed by normalized string. The "
            "terminology side ships already normalized, so this measures a "
            "lookup rather than a matching algorithm."
        ),
        "note_side_approximation": (
            f"sorted lowercase words, and the same with one of {list(SUFFIXES)} "
            "stripped per word. A hit on EITHER candidate counts, which makes "
            "this an UPPER bound: a real normalizer produces one key, not two. "
            "Derivational morphology is excluded, so `hyperkalemic -> "
            "hyperkalemia` is not counted by either candidate."
        ),
        "notes": len(corpus.notes),
        "normalized_keys": len(normalized),
        "missed_spans": missed,
        "reachable_by_normalization": reachable,
        "reach_rate": round(reachable / missed, 4) if missed else None,
        "correct_concept": correct,
        "precision_when_reached": round(correct / reachable, 4) if reachable else None,
        "ceiling_gain": round(correct / missed, 4) if missed else None,
        "top_residue": dict(residue.most_common(25)),
        "how_to_read": (
            "ceiling_gain is the share of currently-missed spans a perfect "
            "normalizer would recover with the right concept. It is the whole "
            "budget for stage 4, and the residue is what stage 4 cannot fix."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
