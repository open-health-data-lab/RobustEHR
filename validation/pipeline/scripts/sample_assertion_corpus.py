#!/usr/bin/env python
"""Sample notes and spans for the MIMIC assertion gold, reproducibly.

The synthetic fixture gold answered what it could and then ran out of evidence:
negation-dense and hedge-poor, it carried 52 negated spans against 2 uncertain
and 1 family, so three of five dimensions could not be scored at all. This
samples real clinical text to replace that instrument.

**Hash-rank, not `random.sample`.** `rng.select` (`robustehr/rng.py:97`) ranks by
BLAKE2b over a declared salt, which is specified, version-independent and
order-independent — `rng.py:22` records why CPython's sampling algorithms are not.
Every other script in this repository takes a sorted *prefix* rather than a
sample (`eval/snomed_el.py:171`), so this is the first genuine note-level sample
and it follows the house rule rather than inventing one.

**Two sampling stages, both hash-ranked:**

* **notes** — 100 of 1,388, keyed on `note_id`;
* **spans** — 10 per note from the pipeline's own mentions, filtered to clinical
  semantic categories.

The category filter is the one design choice worth defending. Sampling *all*
mentions would spend most of the annotation budget on spans no assertion layer is
meant to qualify; sampling on ConText's output would build a gold that can never
contain its false negatives. `categories_of` is computed from UMLS semantic types
and is **independent of ConText**, so it narrows the population without leaking
the detector's decisions into the gold.

**Sizing.** 10 spans per note is not arbitrary. Against the dimension rates in
`phenotype_assertion.json`, 1,000 spans puts every dimension above the
10-positive floor `assertion_gold_eval.py` requires before it will report
precision and recall — including `uncertain` at ~18, which a 500-span budget
would leave at 9 and unscoreable. That is the exact failure the fixture gold hit.

Output goes to `data/`, which `.gitignore` default-denies: this carries
note-derived offsets and surfaces, and the PhysioNet DUA bars redistributing
them regardless of what may be done with them locally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from pathlib import Path
from typing import Any

from robustehr.categories import categories_of
from robustehr.concepts.matcher import ConceptMatcher
from robustehr.concepts.pipeline import annotate_document
from robustehr.corpus import read_documents
from robustehr.rng import SeedMaterial, select
from robustehr.types import Span, Unit, UnitKind, make_unit_id

#: Categories whose spans an assertion layer is meant to qualify. Independent of
#: ConText — derived from UMLS semantic types — so filtering on it cannot bias
#: the gold toward or away from the detector's own decisions.
CLINICAL = frozenset(
    {
        "disorder",
        "disease",
        "finding",
        "symptom",
        "procedure",
        "medication",
        "therapeutic_procedure",
        "diagnostic_procedure",
    }
)

#: Fixed, recorded, and part of the manifest. Changing it changes the sample.
DEFAULT_SALT = "assertion-gold-2026AA"


def _material(salt: str, stage: str, note_uid: str = "corpus") -> SeedMaterial:
    """Seed material for a sampling stage.

    `SeedMaterial` is shaped for operators, so the operator-ish fields carry the
    sampling stage instead. What matters is that the tuple is canonical and
    recorded: the same salt and stage always produce the same ranking.
    """
    return SeedMaterial(
        salt=salt,
        note_uid=note_uid,
        note_sha256="",
        op_id=f"sample.{stage}",
        op_version="1.0.0",
        params_canon="",
        scope_canon="",
        stage_index=0,
        unit_kind=UnitKind.DOCUMENT.value,
    )


def sample_notes(paths: Path, salt: str, k: int) -> list[Any]:
    """`k` notes by hash rank over `note_id`."""
    documents = list(read_documents(paths))
    units = [
        Unit(
            make_unit_id(UnitKind.DOCUMENT, Span(0, len(d.text))) + f"|{d.uid}",
            UnitKind.DOCUMENT,
            Span(0, len(d.text)),
        )
        for d in documents
    ]
    by_unit = {u.unit_id: d for u, d in zip(units, documents, strict=True)}
    chosen = select(units, k, _material(salt, "notes"))
    return [by_unit[u.unit_id] for u in chosen]


def sample_spans(
    doc: Any, matcher: ConceptMatcher, salt: str, per_note: int
) -> list[dict[str, Any]]:
    """`per_note` clinical mentions from one note, by hash rank."""
    seen: dict[tuple[int, int], Any] = {}
    for mention in annotate_document(doc, matcher).mentions:
        key = (mention.span.start, mention.span.end)
        if key in seen or not (categories_of(mention.tuis) & CLINICAL):
            continue
        seen[key] = mention
    units = [
        Unit(make_unit_id(UnitKind.WORD, m.span), UnitKind.WORD, m.span) for m in seen.values()
    ]
    chosen = select(units, per_note, _material(salt, "spans", doc.uid))
    picked = {(u.span.start, u.span.end) for u in chosen}
    return [
        {
            "note_id": doc.uid,
            "start": m.span.start,
            "end": m.span.end,
            "surface": doc.text[m.span.start : m.span.end],
            "cui": m.cui,
            "categories": sorted(categories_of(m.tuis) & CLINICAL),
        }
        for key, m in sorted(seen.items())
        if key in picked
    ]


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument("--index", type=Path, default=Path("data/quickumls_index"))
    parser.add_argument("--notes", type=int, default=100)
    parser.add_argument("--spans-per-note", type=int, default=10)
    parser.add_argument("--salt", default=DEFAULT_SALT)
    parser.add_argument("--out", type=Path, default=Path("data/assertion_gold_mimic"))
    args = parser.parse_args(argv)

    documents = sample_notes(args.corpus, args.salt, args.notes)
    matcher = ConceptMatcher(args.index)
    spans: list[dict[str, Any]] = []
    for doc in documents:
        spans.extend(sample_spans(doc, matcher, args.salt, args.spans_per_note))

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "salt": args.salt,
        "corpus": str(args.corpus),
        "notes_requested": args.notes,
        "notes_sampled": len(documents),
        "spans_per_note": args.spans_per_note,
        "spans_sampled": len(spans),
        "note_ids": sorted(d.uid for d in documents),
        "spans": spans,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    (args.out / "sample.json").write_text(text + "\n", encoding="utf-8")

    manifest = {
        "salt": args.salt,
        "sampler": "robustehr.rng.select — BLAKE2b hash rank, not random.sample",
        "notes_sampled": len(documents),
        "spans_sampled": len(spans),
        "span_filter": sorted(CLINICAL),
        "why_this_filter": (
            "derived from UMLS semantic types, so it is independent of ConText. "
            "Sampling on the detector's own output would build a gold that "
            "cannot contain its false negatives."
        ),
        "sample_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "restricted": True,
        "licence": (
            "MIMIC-IV under the PhysioNet Credentialed Health Data Use "
            "Agreement. sample.json carries note-derived surfaces and must "
            "never be committed; data/ is default-deny in .gitignore."
        ),
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({k: v for k, v in manifest.items() if k != "licence"}, indent=2, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
