"""Propose the surface forms that ARE a phenotype's diagnosis.

The third direction of concept association, and the only one that does not go
through an identifier. Chapters 13 and 14 build a set by traversing relations
and by grounding proposed strings; both end in CUIs, and both therefore inherit
whatever the hierarchy cannot reach. An organism has no ``is-a`` path to the
disease it causes and a qualifier has none to the disease it qualifies, so
`Clostridium difficile` and `metastatic` are unreachable from their own
phenotypes at any hop count. They are also, respectively, the most decisive
string a reader uses for C. difficile infection and the word that makes a cancer
metastatic.

This script asks a model for those strings directly, in surface space, and
writes them to a resource the runtime matches literally.

**What it emits is candidates.** Same contract as `phenotype_closure.py`: this
produces a proposal, and admission is a separate reviewed pass. The header it
writes records which passes have run, so a set that has only been proposed
cannot be mistaken for one that has been vetted.

**Strings, never identifiers.** The model is asked for how clinicians write the
diagnosis, not for concepts, so nothing here needs grounding and nothing here
carries a UMLS string. That is also why the resource may ship in the clear while
the concept sets ship as hashed surfaces: this text is author-written, and the
Metathesaurus licence does not reach it.

Usage::

    export ROBUSTEHR_LLM_MODEL=openai/gpt-5.6-luna
    export OPENROUTER_API_KEY=...
    python validation/phenotype/scripts/phenotype_anchors.py
    python validation/phenotype/scripts/phenotype_anchors.py --phenotype hfref --phenotype hfpef
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from robustehr import llm
from robustehr.concepts.phenotype import load_definitions

#: Recommended for this pass: it is a generation task over a short prompt with a
#: strict output shape, run once per phenotype, which is what the cheap tier is
#: for. Overridden by ROBUSTEHR_LLM_MODEL; no default ships, because sending a
#: request to a third party is not a choice this package makes for you.
SUGGESTED_MODEL = "openai/gpt-5.6-luna"

DEFAULT_OUT = Path("src/robustehr/resources/phenotype_anchors.yaml")

#: Surfaces no phenotype admits as evidence, whatever concept they grounded to.
#:
#: Every one of these is a legitimate UMLS string for some in-set concept,
#: matched in entirely the wrong sense — `status` for "volume status" and
#: "status post", `secondary` for "secondary to hypoperfusion". They are
#: declared rather than derived because the general-English floor cannot reach
#: them: each carries a high-precision clinical semantic type, which is exactly
#: what `gen_general_english.py` subtracts from the list that floor consults.
#:
#: Kept short on purpose. A long list here is a sign the vetting criterion is
#: too loose and the concepts should be dropped from the set instead.
GLOBAL_STOP_SURFACES = (
    "status",
    "secondary",
    "light",
    "ice",
    "aspect",
    "doe",
    "present",
    "positive",
    "negative",
    "history",
)

PROMPT = """You are listing the ways a clinician writes one diagnosis in a discharge summary.

DIAGNOSIS: {label}

List every surface form a physician would write in a note to record THIS
condition: the full name, its common abbreviations with and without
punctuation, standard eponyms, and the causative organism or the qualifying
adjective where those are how the condition is actually named.

**Include the OTHER NAMES the record uses for this same condition**, not only
the one above. Terminologies rename conditions and notes keep the old names:
a problem list says "alcohol dependence" and "alcohol abuse" where the current
heading is "alcohol use disorder". Superseded names, near-equivalent diagnoses
a coder would treat as this phenotype, and named subtypes all belong here. A
list restricted to re-phrasings of the heading above misses most of what a
chart actually says.

**Include the SHORT forms clinicians actually write, not only the formal name.**
Notes are written in a hurry and the head noun is usually dropped. A problem
list says "C. diff", not "Clostridioides difficile infection"; it says
"metastatic disease" or just "mets", not "metastatic malignant neoplasm". If a
formal form is on your list, the elliptical forms clinicians write instead of it
belong on the list too. A list containing only textbook phrasings is wrong, and
it is the most common way this task is failed.

Rules:
- A form must, on its own, mean this diagnosis. If a reader could see the string
  and not know which condition is meant, leave it out.
- Include abbreviations clinicians actually type, including ones without
  periods or spaces.
- Include the bare organism name where the condition is named for its organism,
  and the bare qualifying adjective where the qualifier is what identifies the
  condition among its siblings.
- Do NOT include drugs, tests, lab values, symptoms, risk factors or
  complications. Those are associations, not the diagnosis.
- Do NOT include a form that is an ordinary English word used in its ordinary
  sense.
- Do NOT include a form that names a genuinely DIFFERENT condition — one a
  clinician would record separately from this one. A superseded or alternative
  name for the SAME condition is not that. {contrast}
- Lowercase everything. One form per line. No numbering, no commentary.

Reply with one surface form per line and nothing else."""

#: Phenotypes whose whole clinical point is a distinction from a sibling. Left
#: unguarded, a model lists `chf` and `heart failure` under both HFpEF and
#: HFrEF, and the anchor layer then makes the two indistinguishable — which is
#: the exact failure the phenotype pair exists to measure.
CONTRAST = {
    "hfpef": (
        "This is heart failure with PRESERVED ejection fraction. A form that "
        "means reduced ejection fraction, or that is silent about which, is a "
        "different phenotype."
    ),
    "hfref": (
        "This is heart failure with REDUCED ejection fraction. A form that "
        "means preserved ejection fraction, or that is silent about which, is a "
        "different phenotype."
    ),
    "type_1_diabetes": (
        "This is type 1 diabetes. A form meaning type 2, or one silent about "
        "type, is a different phenotype."
    ),
    "type_2_diabetes": (
        "This is type 2 diabetes. A form meaning type 1, or one silent about "
        "type, is a different phenotype."
    ),
    "deep_vein_thrombosis": (
        "This is venous thrombosis in a deep vein. Pulmonary embolism is a "
        "different phenotype, even though both are venous thromboembolism."
    ),
    "pulmonary_embolism": (
        "This is embolism in the pulmonary arteries. Deep vein thrombosis is a "
        "different phenotype, even though both are venous thromboembolism."
    ),
}


def propose(config: Any, name: str, label: str) -> list[str]:
    """Ask for one phenotype's surface forms.

    An empty list on failure rather than a raise: one unreachable phenotype
    should cost that phenotype's anchors, not the whole pass, and the header
    records which phenotypes were proposed so a gap is visible rather than
    silent.
    """
    prompt = PROMPT.format(label=label, contrast=CONTRAST.get(name, ""))
    try:
        reply = llm.complete(config, prompt)
    except llm.LlmUnavailable as exc:
        print(f"    LLM unavailable for {name}: {exc}", file=sys.stderr)
        return []
    seen: dict[str, None] = {}
    for line in reply.splitlines():
        form = line.strip().strip("-*•").strip().lower()
        # A model that ignores "no numbering" writes "1. hypertension"; strip the
        # marker rather than dropping the form.
        if form[:1].isdigit() and "." in form[:4]:
            form = form.split(".", 1)[1].strip()
        if not form or len(form) < 2 or "\t" in form:
            continue
        # Commentary is long and prose-shaped; a diagnosis surface is neither.
        if len(form) > 60 or form.count(" ") > 5:
            continue
        seen.setdefault(" ".join(form.split()), None)
    return list(seen)


def _existing(out: Path) -> dict[str, Any]:
    """Prior candidates, so a re-run proposes only what is missing."""
    if not out.exists():
        return {}
    loaded = yaml.safe_load(out.read_text(encoding="utf-8")) or {}
    return dict(loaded.get("phenotypes", {}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--phenotype", action="append", default=[])
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-propose phenotypes that already have candidates",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    definitions = load_definitions()
    names = args.phenotype or sorted(definitions)
    unknown = [n for n in names if n not in definitions]
    if unknown:
        parser.error(f"unknown phenotype(s) {unknown}")

    existing = _existing(args.out)
    todo = [n for n in names if args.refresh or n not in existing]
    if args.dry_run:
        print(f"would propose anchors for {len(todo)} phenotype(s): {', '.join(todo)}")
        return 0

    try:
        config = llm.configure()
    except llm.LlmUnavailable as exc:
        print(
            f"{exc}\nThis pass needs a model. Suggested: {SUGGESTED_MODEL}",
            file=sys.stderr,
        )
        return 2

    blocks = dict(existing)
    for name in todo:
        forms = propose(config, name, definitions[name].label)
        print(f"  {name}: {len(forms)} candidate surface(s)")
        prior = blocks.get(name, {})
        blocks[name] = {
            **prior,
            "anchors": forms,
            # `**prior` first so re-proposing replaces the anchors and leaves
            # everything else standing. The `associated` block in particular is
            # recovered from a different source by a different script, and a
            # re-propose that silently dropped it would look like the recovery
            # had never run.
            #
            # Stop surfaces are not proposed here. A model asked to list what a
            # diagnosis is NOT produces an unbounded list, and the ones that
            # matter are corpus-specific matcher accidents rather than clinical
            # facts. They are declared globally above and per-phenotype by hand.
            "stop_surfaces": list(prior.get("stop_surfaces", ())),
            "source": "llm",
            "pass": 1,
        }

    payload = {
        "schema_version": "1.0",
        "what": (
            "candidate surface forms that ARE each phenotype's diagnosis, matched "
            "literally against note text. A second warrant beside concept-set "
            "membership, admitting evidence the hierarchy cannot reach: the "
            "causative organism, the qualifying adjective, and abbreviations the "
            "matcher produces no candidate for."
        ),
        "licence": (
            "author-written English. No Metathesaurus string appears here, which "
            "is why this resource ships in the clear while the concept sets ship "
            "as identifiers with hashed surfaces."
        ),
        "passes": [{"pass": 1, "role": "propose", "model": config.model, "by": "llm"}],
        "vetted_by": "llm",
        "stop_surfaces": list(GLOBAL_STOP_SURFACES),
        "phenotypes": dict(sorted(blocks.items())),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True, width=88),
        encoding="utf-8",
    )
    total = sum(len(b.get("anchors", ())) for b in blocks.values())
    print(f"\n{args.out}: {len(blocks)} phenotypes, {total} candidate surfaces")
    print(json.dumps({"model": config.model, "proposed": len(todo)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
