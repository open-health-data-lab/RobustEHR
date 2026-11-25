#!/usr/bin/env python
"""Derive an abbreviation inventory from SNOMED, instead of hand-authoring one.

**SNOMED already records its own abbreviations.** Its synonym convention is
``ABBREV - full term``, so the terminology contains

    HFrEF - heart failure with reduced ejection fraction     SNOMEDCT_US  SY
    COPD - Chronic obstructive pulmonary disease             SNOMEDCT_US  SY

as ordinary atoms. Exact matching on ``hfref`` finds nothing — no atom *is*
``HFrEF`` — while the mapping sits right there in the row. Splitting on the
separator recovers thousands of abbreviation-to-concept mappings that would
otherwise be written by hand, badly, one at a time.

This is what a properly ontologic expansion looks like: the vocabulary supplies
both the short form and the concept, so no clinician has to be asked what
``NSTEMI`` means and no reviewer has to check that the answer is right.

**Two filters, and the second is the one that matters.**

*Monosemy among the abbreviation atoms* is the obvious criterion: ``AF`` maps to
four concepts through this convention — amaurosis fugax, atrial fibrillation and
others — and a context-free table must refuse it.

It is not sufficient, and the failure is instructive. ``PT - Platinum`` is the
**only** ``ABBREV - full term`` atom for ``PT``, so that filter calls it
unambiguous — while in clinical prose ``pt`` overwhelmingly means *patient*.
**A terminology's monosemy is a property of its synonym set, not of how
clinicians write.** Unfiltered, this inventory would expand a patient into a
metal.

So the second filter asks a different question: **is the short form ambiguous
*as written*?** Count the concepts carrying an atom equal to the surface itself.
``pt`` has 9, ``ca`` 5, ``ra`` 5 — all rejected. ``hfref``, ``angap`` and ``rdw``
have 0, which is precisely why they need an expansion at all.

Requiring **zero** standalone concepts, rather than merely few, is deliberate and
does three things at once. It excludes every ambiguous form by construction. It
excludes forms the matcher already resolves unaided, which need no entry. And
what remains is exactly the population the table exists for: surfaces the
terminology cannot reach as written, that mean one thing when it can.

**Licensing: this artifact does not ship.** The short forms are UMLS strings, so
the derived table lives under ``data/`` with a committed builder and a manifest
hash, matching how the clinical lexicon is handled. Only the manifest travels.
The hand-authored ``lab_shorthand.yaml`` is the complement, not a duplicate: it
covers institutional laboratory shorthand — ``creat``, ``angap``, ``urean`` —
which is absent from every terminology and therefore underivable.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

#: Bounds on the abbreviation half of an `ABBREV - full term` atom.
MIN_CHARS, MAX_CHARS = 2, 10

#: How abbreviation-like the short half must look. Requiring it to be entirely
#: uppercase rejects `HFrEF`, `pH` and every other mixed-case clinical
#: abbreviation, which is most of the interesting ones; requiring a majority of
#: its letters to be uppercase keeps them and still rejects prose.
MIN_UPPER_RATIO = 0.5


def looks_like_an_abbreviation(short: str) -> bool:
    letters = [c for c in short if c.isalpha()]
    if not letters or not (MIN_CHARS <= len(short) <= MAX_CHARS):
        return False
    if " " in short.strip():
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= MIN_UPPER_RATIO


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--umls", type=Path, default=Path("data/umls"))
    parser.add_argument("--out", type=Path, default=Path("data/lexicon/abbrev_snomed.tsv"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("validation/measurements/abbrev_snomed.manifest.json")
    )
    args = parser.parse_args(argv)

    import duckdb

    from robustehr.concepts.umls import MRCONSO_COLUMNS, MRSTY_COLUMNS, UmlsRelease

    release = UmlsRelease.discover(args.umls)
    con = duckdb.connect(":memory:")
    source = (
        f"read_csv('{release.rrf('MRCONSO.RRF')}', delim='|', header=false, "
        f"quote='', names={MRCONSO_COLUMNS!r}, all_varchar=true)"
    )
    # ORDER BY on every aggregate: a tie broken by scan order is invisible to a
    # Python AST lint and would make the artifact non-reproducible.
    rows = con.execute(f"""
        SELECT split_part(str, ' - ', 1) AS short,
               list(DISTINCT cui ORDER BY cui) AS cuis,
               min(split_part(str, ' - ', 2)) AS long
        FROM {source}
        WHERE lat = 'ENG' AND suppress = 'N' AND sab = 'SNOMEDCT_US'
          AND str LIKE '% - %'
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    code_rows = con.execute(f"""
        SELECT cui, min(code) AS code FROM {source}
        WHERE sab = 'SNOMEDCT_US' AND suppress = 'N'
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    cui_code = {str(c): str(k) for c, k in code_rows}

    semtypes = con.execute(f"""
        SELECT cui, list(DISTINCT tui ORDER BY tui) FROM read_csv(
            '{release.rrf("MRSTY.RRF")}', delim='|', header=false, quote='',
            names={MRSTY_COLUMNS!r}, all_varchar=true)
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    cui_tuis = {str(c): [str(t) for t in ts] for c, ts in semtypes}

    # How many concepts carry an atom equal to the surface itself? Computed here
    # rather than through the matcher so the builder needs no index — and so the
    # answer is a property of the release rather than of a matcher setting.
    standalone = dict(
        con.execute(f"""
            SELECT lower(str) AS s, count(DISTINCT cui) AS n
            FROM {source}
            WHERE lat = 'ENG' AND suppress = 'N' AND length(str) BETWEEN 2 AND 10
            GROUP BY 1 ORDER BY 1
        """).fetchall()
    )

    kept, ambiguous, already_reachable = [], 0, 0
    for raw_short, cuis, long in rows:
        short = str(raw_short).strip()
        if not looks_like_an_abbreviation(short):
            continue
        unique = sorted({str(c) for c in cuis})
        if len(unique) > 1:
            ambiguous += 1
            continue
        # The filter that stops `pt` becoming Platinum. A surface the terminology
        # already reaches is either ambiguous (reject: the anchor vote owns it)
        # or resolved (reject: it needs no entry). Only the unreachable remain.
        if standalone.get(short.lower(), 0) > 0:
            already_reachable += 1
            continue
        cui = unique[0]
        if not cui_tuis.get(cui):
            continue
        kept.append((short.lower(), cui, cui_code.get(cui, ""), str(long).strip()))

    kept.sort()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        handle.write("short\tcui\tsnomed\tlong\n")
        for row in kept:
            handle.write("\t".join(row) + "\n")

    import hashlib

    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    manifest = {
        "artifact": str(args.out),
        "what": (
            "abbreviation -> concept, derived from SNOMED's own "
            "'ABBREV - full term' synonym convention"
        ),
        "why_not_committed": (
            "the short forms are UMLS strings. Only this manifest ships; rebuild "
            "the artifact locally from your own licensed release."
        ),
        "umls_release": release.version,
        "selection": (
            f"lat=ENG, suppress=N, sab=SNOMEDCT_US, str contains ' - ', short half "
            f"{MIN_CHARS}-{MAX_CHARS} chars with >= {MIN_UPPER_RATIO:.0%} of its "
            "letters uppercase, mapping to exactly one CUI carrying a semantic type"
        ),
        "candidate_atoms": len(rows),
        "kept": len(kept),
        "rejected_ambiguous_among_abbrev_atoms": ambiguous,
        "rejected_reachable_as_written": already_reachable,
        "why_the_second_filter": (
            "a terminology's monosemy is a property of its synonym set, not of "
            "how clinicians write. 'PT - Platinum' is the only ABBREV-form atom "
            "for PT, so monosemy alone admits it, while in prose pt means "
            "patient. Requiring zero standalone concepts excludes every "
            "ambiguous form by construction, excludes forms that need no entry, "
            "and leaves the population the table exists for."
        ),
        "sha256": digest,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
