#!/usr/bin/env python
"""Annotate the sampled MIMIC spans on the assertion dimensions.

Three of stage 8's dimensions have no gold in any domain, and the synthetic
fixture gold could not supply one: negation-dense and hedge-poor, it carried 2
uncertain and 1 family spans. This annotates real clinical text so the operator
gate in `validation/methodology/12` rests on the distribution the package actually runs on.

**Authorisation and its limits.** MIMIC-IV note text is held under the PhysioNet
DUA, and disclosing it to a third party — an LLM API included — requires
authorisation, which was confirmed for this work. Authorisation to *annotate* is
not permission to *redistribute*, so:

* requests carry ``provider: {"data_collection": "deny"}``, which restricts
  OpenRouter to providers that do not retain or train on prompts;
* the key comes from ``OPENROUTER_API_KEY`` or the gitignored key file, never
  from an argument — arguments land in shell history and process listings;
* prompts and raw responses cache under ``data/``, which `.gitignore`
  default-denies, and no artifact under `docs/` receives note text.

**Windows, not whole notes.** A 1.05M context means a whole note *fits*, but
fitting is not annotating well: accuracy per item degrades when many items share
one long context, and this gold is what everything else is measured against.
Windows are built from **our own structure layer** rather than a character count
— measured over 40 notes, sections run a median of 46 characters with only 5%
above 2,000, so a section per window would be fragmentary and a blind character
cut would slice through them. Consecutive sections are packed to a cap, and a
section that alone exceeds the cap is split on our sentence boundaries.

**Every window carries its section header.** 80% of sections have one, and
headers are exactly where `historical` and `family` framing lives — `PAST MEDICAL
HISTORY:`, `FAMILY HISTORY:`. A window that lost its header would bias those two
dimensions downward, which are the two this corpus exists to measure.

**Determinism.** An LLM is not reproducible by re-running, so every response is
cached under a key derived from the model and the exact prompt. A second run with
the cache present is offline and byte-identical, which is what lets the frozen
gold sit underneath a deterministic scorer. The served model and generation id
are recorded per window: OpenRouter may route to a different snapshot than
requested, and an unrecorded substitution would silently change provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from robustehr.document import Document

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DIMENSIONS = ("negated", "uncertain", "historical", "family")

#: Characters per window. Chosen against the measured section distribution: it
#: packs the median section (46 chars) into useful company without letting the
#: 5% of sections above 2,000 dominate a prompt.
WINDOW_CHARS = 2000

#: Bounded retries. A window that still fails is reported, never dropped —
#: silently missing windows would bias the gold toward whatever annotates easily.
MAX_ATTEMPTS = 4


def api_key() -> str:
    """Environment first, then the gitignored file. Never an argument.

    **Every user supplies their own key; none ships with the package.** A CLI
    argument would put the key in shell history and in the process table, so it
    is not accepted from one, and it is not read from a file in the working
    directory either: a key picked up from wherever you happened to `cd` is a
    key that sends clinical text to a third party by accident.

    Nothing in `src/` calls this. The LLM arms are measurement scripts, and a
    key is needed only to *reproduce* those measurements, never to use the
    package: the numbers they produce are committed, the calls are cached, and
    the shipped detector is deterministic and offline.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key.strip()
    raise SystemExit(
        "No OpenRouter credentials found, and none ship with this package.\n"
        "  export OPENROUTER_API_KEY=sk-or-...\n"
        "Get one at https://openrouter.ai/keys. This is needed only to "
        "re-run the LLM comparison arms; the shipped detector needs no network."
    )


def windows(doc: Document, cap: int) -> list[tuple[int, int, str]]:
    """`(start, end, header)` windows packing consecutive sections up to `cap`.

    The header travels with the window rather than being packed into it, so a
    window that begins mid-section still tells the annotator which section it is
    in — which is the whole point of carrying it.
    """
    out: list[tuple[int, int, str]] = []
    start: int | None = None
    end = 0
    header = ""
    for section in doc.sections:
        label = (
            doc.text[section.header.span.start : section.header.span.end] if section.header else ""
        )
        size = section.full.end - section.full.start
        if size > cap:
            if start is not None:
                out.append((start, end, header))
                start = None
            # Too big to pack: split on our own sentence boundaries.
            piece_start = section.full.start
            for sentence in doc.sentences.sentences:
                if not (section.full.start <= sentence.span.start < section.full.end):
                    continue
                if sentence.span.end - piece_start >= cap:
                    out.append((piece_start, sentence.span.end, label))
                    piece_start = sentence.span.end
            if piece_start < section.full.end:
                out.append((piece_start, section.full.end, label))
            continue
        if start is None:
            start, header = section.full.start, label
        elif section.full.end - start > cap:
            out.append((start, end, header))
            start, header = section.full.start, label
        end = section.full.end
    if start is not None:
        out.append((start, end, header))
    return out


def mark(
    text: str,
    window: tuple[int, int],
    spans: list[dict[str, Any]],
    order: list[dict[str, Any]] | None = None,
) -> str:
    """The window with each span wrapped as ``《i:surface》``.

    Marking inline rather than listing spans separately means the annotator sees
    exactly which occurrence is meant — several spans in a note commonly share a
    surface, and a detached list cannot disambiguate them.

    ``order`` supplies the numbering while ``spans`` supplies the positions, so
    the reliability pass can renumber without disturbing the text.
    """
    start, end = window
    numbering = {id(s): i for i, s in enumerate(order or spans)}
    pieces: list[str] = []
    cursor = start
    for span in spans:
        pieces.append(text[cursor : span["start"]])
        pieces.append(f"《{numbering[id(span)]}:{text[span['start'] : span['end']]}》")
        cursor = span["end"]
    pieces.append(text[cursor:end])
    return "".join(pieces)


#: Share of sampled spans carrying no modifier at all, measured on the gold.
#: Stated in the prompt because the v1 arms over-called every dimension —
#: Gemini 2.5 Flash reached recall 1.0000 on negation at precision 0.4928, and
#: Flash-Lite labelled 299 of 1,000 spans uncertain against a gold of 119. A
#: model with no sense of the base rate treats "could this be modified?" as the
#: question, when the question is "is it".
UNMODIFIED_RATE = 0.70


def build_prompt(guideline: str, header: str, body: str, n: int, version: str = "v1") -> str:
    """The annotation prompt. `version` selects the wording, and it is a
    measured choice rather than a preference.

    **v1** built the gold. It states the task, inlines the guideline and asks
    for a JSON list per span. As a *detector* prompt it has a systematic flaw:
    nothing tells the model how rare modifiers are, and every arm run under it
    over-called — high recall, precision between 0.22 and 0.65.

    **v2** changes nothing about the guideline or the label set. It adds three
    things the error pattern asked for: the base rate, an explicit requirement
    that a modifier must *govern* this span rather than merely appear near it,
    and a tie-break toward the empty list. The span markup, the windowing and
    the JSON contract are identical, so v1 and v2 differ only in framing.

    Chosen on the **development** half and reported on held-out once. Iterating
    prompt wording against the test half is fitting the test half, and this
    repository has already had to withdraw one number for a subtler version of
    exactly that mistake.
    """
    head = (
        f"{guideline}\n\n"
        "---\n\n"
        f"Section: {header or '(no header)'}\n\n"
        f"Clinical text, with {n} spans marked as 《index:text》:\n\n"
        f"{body}\n\n"
        "---\n\n"
    )
    if version == "v1":
        return (
            head + f"For each marked span 0..{n - 1}, list the dimensions that apply. An "
            "empty list means affirmed, current, and the patient's.\n"
            'Reply with JSON only, no prose: {"0": ["negated"], "1": [], ...}\n'
            f"Allowed dimensions: {', '.join(DIMENSIONS)}"
        )
    return (
        head + f"For each marked span 0..{n - 1}, list the dimensions that apply.\n\n"
        f"MOST SPANS CARRY NONE. About {UNMODIFIED_RATE:.0%} of spans in this "
        "corpus are affirmed, current, and the patient's, and their answer is "
        "the empty list. Returning [] is the normal outcome, not a failure to "
        "find something.\n\n"
        "A dimension applies only if a cue in the text GOVERNS THIS SPAN. A cue "
        "in a different list item, a different row of a lab table, a different "
        "line, or a different section does not govern it. Neither does a cue "
        "that governs a neighbouring mention in the same sentence but not this "
        "one. Do not label a span because a modifier appears nearby; label it "
        "because the note applies that modifier to this mention.\n\n"
        "If you are weighing a dimension against no dimension, choose no "
        "dimension. A missed modifier is one error; an invented one changes "
        "what the note says.\n\n"
        "Example. In `Denies chest pain. Started lisinopril.` the span `chest "
        'pain` is ["negated"] and the span `lisinopril` is [] — the denial '
        "governs the first mention only.\n\n"
        'Reply with JSON only, no prose: {"0": ["negated"], "1": [], ...}\n'
        f"Allowed dimensions: {', '.join(DIMENSIONS)}"
    )


def call(prompt: str, model: str, key: str, cache: Path) -> dict[str, Any]:
    """One cached completion. The cache key is the model plus the exact prompt."""
    digest = hashlib.blake2b(f"{model}\x1f{prompt}".encode(), digest_size=16).hexdigest()
    hit = cache / f"{digest}.json"
    if hit.exists():
        return json.loads(hit.read_text(encoding="utf-8"))

    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "provider": {"data_collection": "deny"},
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "RobustEHR assertion gold",
        },
    )
    last = ""
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = json.load(response)
            hit.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(2**attempt)
    return {"error": last}


def parse(payload: dict[str, Any], n: int) -> dict[int, list[str]] | None:
    """Labels per span index, or ``None`` if the reply was unusable."""
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    out: dict[int, list[str]] = {}
    for index in range(n):
        value = raw.get(str(index), [])
        if not isinstance(value, list):
            value = []
        out[index] = sorted({d for d in value if d in DIMENSIONS})
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sample", type=Path, default=Path("data/assertion_gold_mimic/sample.json")
    )
    parser.add_argument("--corpus", type=Path, default=Path("data/golden_notes.csv"))
    parser.add_argument(
        "--guideline", type=Path, default=Path("docs/assertion-annotation-guideline.md")
    )
    parser.add_argument("--model", default="openai/gpt-5.6-luna")
    parser.add_argument("--cache", type=Path, default=Path("data/openrouter_cache"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--prompt-version",
        default="v1",
        choices=["v1", "v2"],
        help="v1 built the gold; v2 adds the base rate, a governance "
        "requirement and a tie-break toward the empty list. v2 was chosen on the "
        "development half; that sweep predates the measurement-artifact rule and "
        "was never committed, so the comparison is not reproducible from this "
        "repository. Re-run it before citing the choice.",
    )
    parser.add_argument(
        "--split-file", type=Path, default=Path("data/assertion_gold_mimic/split.json")
    )
    parser.add_argument(
        "--split",
        default=None,
        choices=["development", "held_out"],
        help="annotate one half only. Prompt selection must run on development, "
        "and restricting the call set is also what keeps that cheap",
    )
    parser.add_argument("--cap", type=int, default=WINDOW_CHARS)
    parser.add_argument("--out", type=Path, default=Path("data/assertion_gold_mimic/labels.json"))
    parser.add_argument(
        "--reverse-spans",
        action="store_true",
        help="number the spans in reverse within each window. This is the "
        "reliability pass: at temperature 0 an identical prompt returns an "
        "identical answer and measures nothing, so the second draw has to "
        "perturb something the label should not depend on. Order is the "
        "obvious candidate — a label that moves when the numbering is "
        "reversed was never stable",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    args = build_parser().parse_args(argv)

    from robustehr.corpus import read_documents

    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    wanted = set(sample["note_ids"])
    if args.split:
        from scripts.split_assertion_gold import load_split

        loaded = load_split(args.split_file, args.split)
        assert loaded is not None
        _spans, notes = loaded
        wanted &= {n for n, half in notes.items() if half == args.split}
        sample["spans"] = [s for s in sample["spans"] if s["note_id"] in wanted]
    by_note: dict[str, list[dict[str, Any]]] = {}
    for span in sample["spans"]:
        by_note.setdefault(span["note_id"], []).append(span)

    guideline = args.guideline.read_text(encoding="utf-8")
    key = api_key()
    args.cache.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, tuple[int, int], str, list[dict[str, Any]], str]] = []
    for doc in read_documents(args.corpus):
        if doc.uid not in wanted:
            continue
        spans = sorted(by_note[doc.uid], key=lambda s: (s["start"], s["end"]))
        for start, end, header in windows(doc, args.cap):
            inside = [s for s in spans if start <= s["start"] and s["end"] <= end]
            if not inside:
                continue
            # `mark` must still walk the window left to right, so reversal is
            # applied to the *numbering* rather than to the marking order.
            order = list(reversed(inside)) if args.reverse_spans else inside
            body = mark(doc.text, (start, end), inside, order)
            inside = order
            jobs.append(
                (
                    doc.uid,
                    (start, end),
                    header,
                    inside,
                    build_prompt(guideline, header, body, len(inside), args.prompt_version),
                )
            )

    covered = sum(len(j[3]) for j in jobs)
    print(f"{len(jobs)} windows covering {covered}/{len(sample['spans'])} spans", flush=True)

    def run(job: tuple[Any, ...]) -> dict[str, Any]:
        uid, window, _header, inside, prompt = job
        payload = call(prompt, args.model, key, args.cache)
        labels = parse(payload, len(inside))
        return {
            "note_id": uid,
            "window": list(window),
            "spans": inside,
            "labels": labels,
            "served_model": payload.get("model"),
            "generation_id": payload.get("id"),
            "error": payload.get("error") if labels is None else None,
        }

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, jobs))

    failed = [r for r in results if r["labels"] is None]
    annotated: list[dict[str, Any]] = []
    for result in results:
        if result["labels"] is None:
            continue
        for index, span in enumerate(result["spans"]):
            annotated.append({**span, "labels": result["labels"].get(index, [])})

    served = sorted({r["served_model"] for r in results if r["served_model"]})
    payload = {
        "model_requested": args.model,
        "model_served": served,
        "windows": len(jobs),
        "windows_failed": len(failed),
        "spans_annotated": len(annotated),
        "spans_in_sample": len(sample["spans"]),
        "window_cap_chars": args.cap,
        "items": annotated,
        "failures": [
            {"note_id": r["note_id"], "window": r["window"], "error": r["error"]} for r in failed
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    counts = {d: sum(1 for a in annotated if d in a["labels"]) for d in DIMENSIONS}
    print(f"annotated {len(annotated)} spans, {len(failed)} windows failed")
    print(f"served: {served}")
    print(f"label counts: {counts}")
    print(f"affirmed: {sum(1 for a in annotated if not a['labels'])}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
