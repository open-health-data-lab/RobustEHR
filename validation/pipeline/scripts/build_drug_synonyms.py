"""Build the generic-brand equivalence map from the DrugBank-derived CSVs.

    python validation/pipeline/scripts/build_drug_synonyms.py

Reads `data/drugs/drugs.csv` (generic names, 1,555 rows) and
`data/drugs/drugs_commercial_name.csv` (brand names, 5,152 rows), joins them on
`entity_id`, and writes `data/drugs/drug_synonyms.json` plus a shippable
manifest recording exactly what was dropped and why.

**The raw join is not usable.** 5,152 brand rows contain investigational
placeholders, brand names identical to their own generic, misspellings of the
generic, and brands that encode a delivery device. Substituting any of those
would break the guarantee `lexical.medication_rename` makes — same drug, same
dose, same route — so each is filtered, and each filter's yield is counted into
the manifest rather than applied silently.

Every filter below was chosen after inspecting what it removes. The comments
name the row that motivated it, because "drop multi-token brands" reads as
arbitrary tidying until you see that it is what stops `indacaterol` becoming
`Arcapta Neohaler` and losing the inhaler.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERICS_CSV = ROOT / "data" / "drugs" / "drugs.csv"
BRANDS_CSV = ROOT / "data" / "drugs" / "drugs_commercial_name.csv"
OUT_JSON = ROOT / "data" / "drugs" / "drug_synonyms.json"
MANIFEST = ROOT / "docs" / "measurements" / "drug_synonyms.manifest.json"

#: A single name token: letters, with internal hyphens or apostrophes allowed.
#: Excludes anything with a space, digit, comma or parenthesis.
_SINGLE_TOKEN = re.compile(r"^[A-Za-z][A-Za-z\-']*$")


def _read_generics() -> dict[str, tuple[str, str]]:
    """``entity_id -> (drugbank_id, generic name)``, keeping only those columns."""
    out: dict[str, tuple[str, str]] = {}
    with GENERICS_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out[row["entity_id"]] = (row["drugbank_id"].strip(), row["drug_name"].strip())
    return out


def _read_brands() -> dict[str, list[str]]:
    """``entity_id -> [commercial name, ...]``, keeping only those columns."""
    out: dict[str, list[str]] = defaultdict(list)
    with BRANDS_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out[row["entity_id"]].append(row["commercial_name"].strip())
    return out


#: Two edits is the ceiling for "this is the same name, spelt wrong". Real
#: brand/generic pairs are nowhere near each other — `furosemide`/`lasix` is 8
#: edits — so the threshold has enormous headroom and never fires on a genuine
#: pair. Measured on this source: it removes 1 row.
_MAX_TYPO_DISTANCE = 2


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein, iterative two-row. Small strings, called once per pair."""
    if abs(len(a) - len(b)) > _MAX_TYPO_DISTANCE:
        return _MAX_TYPO_DISTANCE + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _near_duplicate(generic: str, brand: str) -> bool:
    return _edit_distance(generic, brand) <= _MAX_TYPO_DISTANCE


#: Dose, route, frequency and formulation words that are also somebody's brand.
#: `english_vocabulary()` catches most of what needs catching, but the
#: sig vocabulary is exactly where a false substitution is most damaging —
#: rewriting `daily` as `Cetylpyridinium` destroys the dosing instruction while
#: reporting itself as a naming change — and several of these are abbreviations
#: no English word list contains.
_SIG_WORDS = frozenset(
    (
        "ac",
        "am",
        "bid",
        "capsule",
        "cream",
        "daily",
        "drop",
        "drops",
        "elixir",
        "gel",
        "hs",
        "inhaler",
        "injection",
        "iv",
        "nightly",
        "nocte",
        "od",
        "once",
        "patch",
        "pc",
        "peg",
        "pm",
        "po",
        "prn",
        "puff",
        "puffs",
        "qam",
        "qd",
        "qhs",
        "qid",
        "qod",
        "qpm",
        "sc",
        "solution",
        "spray",
        "subq",
        "supp",
        "suspension",
        "syrup",
        "tab",
        "tablet",
        "tablets",
        "tid",
        "top",
        "topical",
        "twice",
        "unit",
        "units",
        "weekly",
    )
)


def _refused_brand_surfaces() -> frozenset[str]:
    """Brand surfaces that must never be substituted into clinical prose.

    ``english_vocabulary()``, NOT ``general_english()``. The latter deliberately
    subtracts 2,686 clinically-typed words so that `wound` and `fever` stay
    available as clinical terms — which is right for its purpose and exactly
    wrong here, because `Daily` (a real mouthwash brand) is one of the words it
    subtracts. Using it dropped 46 brands and let `daily` through.
    """
    from robustehr.lexical import english_vocabulary

    return frozenset(english_vocabulary()) | _SIG_WORDS


def build() -> tuple[dict[str, object], Counter[str]]:  # noqa: PLR0912 - one branch per named filter
    generics = _read_generics()
    brands = _read_brands()
    english = _refused_brand_surfaces()
    dropped: Counter[str] = Counter()

    # Stage 1 — pairwise filters, each independent of the others.
    pairs: list[tuple[str, str, str]] = []  # (entity_id, generic, brand)
    for entity_id, (_, generic) in sorted(generics.items()):
        if not _SINGLE_TOKEN.match(generic):
            # `Thyroid, porcine`, `Insulin glargine`: a formulation or a
            # multi-word ingredient, not a substitutable single name.
            dropped["generic_not_single_token"] += 1
            continue
        for brand in sorted(brands.get(entity_id, ())):
            if "(" in brand or ";" in brand:
                # `(investigational; no established trade name)`
                dropped["placeholder_text"] += 1
                continue
            if not _SINGLE_TOKEN.match(brand):
                # `Arcapta Neohaler`, `Brimica Genuair`: the brand names a
                # DELIVERY SYSTEM. Substituting it in would change the route.
                dropped["brand_not_single_token"] += 1
                continue
            low_g, low_b = generic.lower(), brand.lower()
            if low_g == low_b:
                # `Nabumetone` listed as its own commercial name.
                dropped["brand_equals_generic"] += 1
                continue
            if low_g in low_b or low_b in low_g:
                # `M-paroxetine`, `Nabumetone-500`: strings derived from the
                # generic, not brands. Substituting one would produce a
                # near-duplicate rather than a different name.
                dropped["brand_derived_from_generic"] += 1
                continue
            if _near_duplicate(low_g, low_b):
                # `Fuosemide` for `Furosemide` — a misspelling in the source
                # data, which substring containment does not catch because the
                # missing `r` breaks it. Left in, `lexical.medication_rename`
                # would emit a TYPO and report it as a naming change; the two
                # are different operators and a result has to keep them apart.
                dropped["brand_is_misspelt_generic"] += 1
                continue
            if low_b in english:
                # `Burn`, `Major`, `Scrub`, `Handy`, `Lucky`: real OTC product
                # names that are also ordinary English. Substituting a generic
                # into one of these corrupts the prose around it.
                dropped["brand_is_english_word"] += 1
                continue
            pairs.append((entity_id, generic, brand))

    # Stage 2 — global ambiguity, which is only visible once all pairs are in.
    by_brand: dict[str, set[str]] = defaultdict(set)
    for _, generic, brand in pairs:
        by_brand[brand.lower()].add(generic.lower())
    # `Vasotec -> {enalapril, enalaprilat}`. The brand->generic direction cannot
    # choose without changing the drug, so the pair is refused in BOTH
    # directions rather than kept asymmetrically — an operator whose eligibility
    # depended on its mode would report two different denominators for one map.
    ambiguous_brands = {b for b, gens in by_brand.items() if len(gens) > 1}

    generic_names = {g.lower() for _, g, _ in pairs}
    # `iron`, `manganese`, `valerian` are both a generic and somebody's brand.
    # Unclassifiable by surface, so unusable in either direction.
    both = generic_names & set(by_brand)

    to_brand: dict[str, list[str]] = defaultdict(list)
    to_generic: dict[str, str] = {}
    for _, generic, brand in pairs:
        low_g, low_b = generic.lower(), brand.lower()
        if low_b in ambiguous_brands:
            dropped["brand_maps_to_many_generics"] += 1
            continue
        if low_g in both or low_b in both:
            dropped["surface_is_both_generic_and_brand"] += 1
            continue
        to_brand[low_g].append(brand)
        to_generic[low_b] = generic

    return (
        {
            "schema_version": "1.0",
            "source": {
                "generics": GENERICS_CSV.name,
                "brands": BRANDS_CSV.name,
                "generic_rows": len(generics),
                "brand_rows": sum(len(v) for v in brands.values()),
            },
            # Sorted throughout so the file is a pure function of its inputs and
            # its sha256 is stable across machines.
            "to_brand": {k: sorted(set(v)) for k, v in sorted(to_brand.items())},
            "to_generic": dict(sorted(to_generic.items())),
        },
        dropped,
    )


#: A probe, not a target. These are among the most frequent drug mentions in US
#: inpatient notes; whether the source data reaches them decides whether
#: `lexical.medication_rename` is a usable operator on a real corpus or a
#: demonstration. Measured into the manifest so the coverage question is
#: answered in the artifact rather than discovered during an experiment.
_COMMON_GENERICS = (
    "acetaminophen",
    "amiodarone",
    "amlodipine",
    "aspirin",
    "atorvastatin",
    "clopidogrel",
    "furosemide",
    "gabapentin",
    "heparin",
    "hydrochlorothiazide",
    "insulin",
    "levothyroxine",
    "lisinopril",
    "metformin",
    "metoprolol",
    "omeprazole",
    "pantoprazole",
    "prednisone",
    "sertraline",
    "warfarin",
)


def _coverage(payload: dict[str, object]) -> dict[str, object]:
    to_brand: dict[str, list[str]] = payload["to_brand"]  # type: ignore[assignment]
    covered = sorted(g for g in _COMMON_GENERICS if g in to_brand)
    return {
        "probe_n": len(_COMMON_GENERICS),
        "covered_n": len(covered),
        "missing": sorted(set(_COMMON_GENERICS) - set(covered)),
    }


def main() -> int:
    payload, dropped = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    OUT_JSON.write_text(text, encoding="utf-8")

    manifest = {
        "generics": len(payload["to_brand"]),
        "brands": len(payload["to_generic"]),
        "pairs": sum(len(v) for v in payload["to_brand"].values()),
        "dropped": dict(sorted(dropped.items())),
        "common_generic_coverage": _coverage(payload),
        "source": payload["source"],
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"  {manifest['generics']} generics <-> {manifest['brands']} brands")
    print(f"  {manifest['pairs']} pairs")
    for reason, count in manifest["dropped"].items():
        print(f"  dropped {count:5d}  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
