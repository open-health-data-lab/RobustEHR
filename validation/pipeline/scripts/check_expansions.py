#!/usr/bin/env python
"""Does every expansion entry reach a concept? A dead row is silent.

The long form in `lab_shorthand.yaml` is a **lookup key**, so a row expanding to
a string the terminology does not carry resolves to nothing and the mention is
dropped exactly as if the row were absent. It looks like coverage and delivers
none, and nothing else in the pipeline notices.

The first draft shipped 14 such rows out of 99. `crp -> C reactive protein`
fails where `c-reactive protein` works; `heent -> head eyes ears nose and
throat` fails where `head and neck` works. The correct long form is not
necessarily the *expansion* — it is the nearest term the vocabulary contains.

Run against any UMLS release. The answer is release-dependent, which is why this
is a script rather than a unit test: it needs a licensed index that CI does not
have.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

from robustehr.concepts.expansion import load_expansions
from robustehr.concepts.matcher import ConceptMatcher, MatcherConfig


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    outer = ConceptMatcher(args.index)
    # The same configuration `resolve_labels` resolves with, or the check
    # measures a path the pipeline does not take.
    inner = ConceptMatcher(
        args.index,
        MatcherConfig(
            threshold=1.0,
            min_match_length=1,
            accepted_semtypes=outer.config.accepted_semtypes,
        ),
    )
    table = load_expansions()
    live, dead = [], []
    for entry in table.entries:
        whole = [
            m
            for m in inner.annotate(entry.long).mentions
            if m.span.end - m.span.start == len(entry.long)
        ]
        row = {"short": entry.short, "long": entry.long, "slot": entry.slot.value}
        (live if whole else dead).append(row | ({"cui": whole[0].cui} if whole else {}))

    payload = {
        "question": "Does every expansion entry reach a concept in this UMLS release?",
        "why": (
            "the long form is a lookup key. A row expanding to a string the "
            "terminology does not carry resolves to nothing and is dropped "
            "exactly as if absent — coverage in name only, and silent."
        ),
        "resource_sha256": table.sha256,
        "reviewed": table.reviewed,
        "entries": len(table),
        "resolving": len(live),
        "dead": len(dead),
        "dead_entries": sorted(dead, key=lambda r: (r["slot"], r["short"])),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if dead else 0


if __name__ == "__main__":
    raise SystemExit(main())
