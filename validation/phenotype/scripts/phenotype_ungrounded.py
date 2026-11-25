"""Recover the proposed terms that UMLS had no string for.

Chapter 14's second direction asks a model for the terms a clinician associates
with a phenotype and then resolves each against the local release by string
lookup. 1,334 of 1,831 resolved. The other 413 were recorded in
``phenotype_proposals.yaml`` under ``terms_unmatched``, described as the honest
error bar on the method, and then dropped.

Reading them says they are not an error bar. They are `omental caking`,
`pericolic fat stranding`, `ring-enhancing brain lesions`, `positive
hepatojugular reflux`, `fruity breath odor`, `accordion sign`, `yellowish
mucosal plaques` — and, for the phenotype whose entire definition it is,
`preserved left ventricular ejection fraction`. They failed because no UMLS
string matches them, not because they are wrong. A pipeline that ends in a CUI
has nowhere to put a true clinical term that has no CUI, so it discarded one in
four of the things it had just been told.

The surface warrant has somewhere to put them. A term that cannot be grounded
can still be matched literally, so these re-enter the target through
``phenotype_anchors.yaml`` at tier ``associated``: evidence for the phenotype,
not the name of it. The tier keeps them out of the diagnosis denominator, which
matters because an arm that corrupted every associated finding while leaving the
diagnosis intact has not tested what it claims to.

**This only promotes terms UMLS could not match.** A term that grounded is
already in the concept set through its CUI, where the matcher's normalisation
and the identity closure both reach it; adding its surface too would double-count
one piece of evidence. What lands here is exactly the residue.

Usage::

    python validation/phenotype/scripts/phenotype_ungrounded.py --dry-run
    python validation/phenotype/scripts/phenotype_ungrounded.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from robustehr.resources import load_yaml


def record_pass(resource: dict, entry: dict) -> bool:
    """Append a provenance entry once, numbering it after the last one.

    The ledger is the only record of how the resource was built, so a stage
    that appends unconditionally corrupts exactly the thing it exists to
    document: rerun the stage and the ledger claims two passes where one ran.
    That happened -- the shipped resource carried a byte-identical duplicate
    and a `pass: 0` that sorted before the passes it followed, so ordering the
    ledger by `pass` reconstructed the wrong build order.

    Identity is the entry minus its number, because the number is assigned
    here. Returns True when the entry was new.
    """
    passes = resource.setdefault("passes", [])
    identity = {k: v for k, v in entry.items() if k != "pass"}
    for existing in passes:
        if {k: v for k, v in existing.items() if k != "pass"} == identity:
            return False
    numbered = dict(entry)
    numbered["pass"] = max((p.get("pass", 0) for p in passes), default=0) + 1
    passes.append(numbered)
    return True


DEFAULT_ANCHORS = Path("src/robustehr/resources/phenotype_anchors.yaml")
DEFAULT_MEASUREMENT = Path("validation/measurements/phenotype_ungrounded.json")

#: Shortest term worth matching literally.
#:
#: A two- or three-character residue is almost always a truncation or an
#: abbreviation whose expansion belongs in the cue lexicon, and matching it
#: literally across a corpus would corrupt text that has nothing to do with the
#: phenotype. The real entries here are phrases.
MIN_LENGTH = 6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--anchors", type=Path, default=DEFAULT_ANCHORS)
    parser.add_argument("--measurement", type=Path, default=DEFAULT_MEASUREMENT)
    parser.add_argument("--min-length", type=int, default=MIN_LENGTH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    proposals: Any = load_yaml("phenotype_proposals.yaml")
    anchors: Any = yaml.safe_load(args.anchors.read_text(encoding="utf-8"))
    blocks = anchors["phenotypes"]

    promoted: dict[str, list[str]] = {}
    skipped_short: list[str] = []
    for name, facets in sorted(proposals["phenotypes"].items()):
        found: dict[str, None] = {}
        for facet_block in facets.values():
            for term in facet_block.get("terms_unmatched") or ():
                text = " ".join(str(term).strip().lower().split())
                if len(text) < args.min_length:
                    skipped_short.append(text)
                    continue
                found.setdefault(text, None)
        if found:
            promoted[name] = sorted(found)

    total = sum(len(v) for v in promoted.values())
    print(f"{total} ungrounded terms over {len(promoted)} phenotypes")
    for name in sorted(promoted):
        print(f"  {name:32s} {len(promoted[name]):3d}")
    if skipped_short:
        print(f"\nskipped {len(skipped_short)} shorter than {args.min_length} characters")

    measurement = {
        "what": (
            "model-proposed clinical terms that no UMLS string matched, promoted to "
            "the surface warrant at tier `associated` rather than discarded"
        ),
        "why": (
            "the propose-then-ground pipeline ends in a CUI and has nowhere to put a "
            "true clinical term that has none. These are findings, signs and "
            "investigations a clinician named; failing to ground is a property of the "
            "vocabulary, not a verdict on the term."
        ),
        "grounded": proposals["totals"]["grounded"],
        "unmatched": proposals["totals"]["unmatched"],
        "promoted": total,
        "min_length": args.min_length,
        "skipped_shorter_than_min": len(skipped_short),
        "per_phenotype": {k: len(v) for k, v in sorted(promoted.items())},
    }

    if args.dry_run:
        print("\ndry run: nothing written")
        print(json.dumps(measurement, indent=2, sort_keys=True)[:600])
        return 0

    for name, terms in promoted.items():
        block = blocks.setdefault(name, {"anchors": [], "stop_surfaces": []})
        # An anchor outranks an association: a term already declared as the
        # diagnosis must not be demoted into the tier that the reach gate
        # excludes from its denominator.
        declared = {str(a).strip().lower() for a in block.get("anchors", ())}
        block["associated"] = [t for t in terms if t not in declared]
    fresh = record_pass(
        anchors,
        {
            "role": "recover ungrounded proposals",
            "source": "phenotype_proposals.yaml terms_unmatched",
            "by": "deterministic",
        },
    )
    if not fresh:
        print("  (this pass is already in the ledger; not recording it twice)")
    args.anchors.write_text(
        yaml.safe_dump(anchors, sort_keys=True, allow_unicode=True, width=88), encoding="utf-8"
    )
    args.measurement.parent.mkdir(parents=True, exist_ok=True)
    args.measurement.write_text(json.dumps(measurement, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\n{args.anchors}")
    print(f"{args.measurement}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
