#!/usr/bin/env python
"""Fetch BioScope — the only freely available gold for the *uncertainty* attribute.

`assertion_accuracy.json` validates one of stage 8's five attributes. The NegEx
gold carries `Affirmed`/`Negated` and nothing else, so `is_uncertain`,
`is_historical`, `is_hypothetical` and `is_family` are emitted and **disclosed as
unvalidated** rather than claimed. This script closes one of those four.

BioScope annotates negation and **speculation** scopes over three subcorpora.
Two facts about it determine what can be done with it, and both are worth knowing
before the numbers:

**The clinical subcorpus is unusable.** `clinical_records_anon.xml` carries 872
negation and 1,137 speculation cues over radiology reports — and every token is
replaced by ``*``. The structure survives, the words do not. The bundled README
directs the user to obtain the raw 2007 CMC challenge text separately and re-merge
it. Without that access there is no clinical text here, only clinical *structure*.

**So the usable gold is out of domain.** `abstracts.xml` (1,757 negation, 2,694
speculation) and `full_papers.xml` (378 / 682) are real text — but they are
biomedical *scientific writing*, and medspaCy's ConText rules are clinical rules.
Hedging in an abstract (*"suggesting that"*, *"these results indicate"*) is not
hedging in a radiology report (*"cannot exclude"*, *"versus"*). A weak score here
may be a domain mismatch rather than a weak rule set, and the accompanying
scorer measures **negation on the same corpus** precisely so that the domain
shift is controlled: both dimensions face the same genre, so the difference
between them isolates the dimension.

Licensing: the archive contains no LICENSE, COPYING or terms file. Handled under
the same rule as the NegEx gold and CASI — treat exactly like MIMIC. It lives in
`data/`, which is default-deny in `.gitignore`, and no derived artifact may carry
sentence text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

URL = "https://rgai.inf.u-szeged.hu/sites/rgai.inf.u-szeged.hu/files/bioscope.zip"

#: Members extracted. The clinical file is pulled too, so the de-worded claim in
#: this module's docstring can be verified rather than taken on trust.
WANTED = (
    "abstracts.xml",
    "full_papers.xml",
    "clinical_merger/clinical_records_anon.xml",
)


def summarize(path: Path) -> dict[str, object]:
    """Cue counts, and whether the subcorpus actually carries words.

    The word check has to run over *text content*, not the raw file: XML markup
    is full of letters (``sentence``, ``xcope``, ``negation``), so a byte-level
    test calls the de-worded clinical file real text and the manifest then
    asserts something false.
    """
    payload = path.read_text(encoding="utf-8", errors="replace")
    content = "".join(node.itertext()).strip() if (node := ET.parse(path).getroot()) else ""
    letters = sum(ch.isalpha() for ch in content)
    stars = content.count("*")
    return {
        "negation_cues": payload.count('cue type="negation"'),
        "speculation_cues": payload.count('cue type="speculation"'),
        "text_chars": len(content),
        "letters_in_text": letters,
        "asterisks_in_text": stars,
        # De-worded means every token became '*': letters vanish and asterisks
        # dominate what is left.
        "has_real_text": letters > stars,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=Path("data/bioscope"))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="use an already-downloaded bioscope.zip instead of fetching. The "
        "host presents a certificate chain Python's trust store rejects on some "
        "networks, where `curl -L` succeeds and urllib does not; passing the "
        "file explicitly is preferred to disabling verification",
    )
    args = parser.parse_args(argv)

    args.dest.mkdir(parents=True, exist_ok=True)
    archive = args.dest / "bioscope.zip"
    if args.archive is not None:
        print(f"using supplied archive {args.archive}", file=sys.stderr)
        archive.write_bytes(args.archive.read_bytes())
    elif archive.exists() and not args.force:
        print(f"present, skipping download: {archive}", file=sys.stderr)
    else:
        print(f"fetching {URL}", file=sys.stderr)
        request = urllib.request.Request(URL, headers={"User-Agent": "robustehr-fetch"})
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            archive.write_bytes(response.read())

    files: dict[str, object] = {
        "bioscope.zip": {
            "url": URL,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "bytes": archive.stat().st_size,
        }
    }
    with zipfile.ZipFile(archive) as zf:
        for member in WANTED:
            target = args.dest / Path(member).name
            target.write_bytes(zf.read(member))
            entry = {
                "member": member,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "bytes": target.stat().st_size,
            }
            entry.update(summarize(target))
            files[target.name] = entry

    manifest = {
        "corpus": "BioScope (Vincze et al.)",
        "purpose": (
            "gold for the uncertainty attribute, which the NegEx gold cannot "
            "supply because it labels only Affirmed/Negated."
        ),
        "licence": (
            "NONE FOUND in the archive — no LICENSE, COPYING or terms file. "
            "Handled under this project's rule for unlicensed corpora, set for "
            "CASI: treat exactly like MIMIC. data/ only, gitignored, aggregates "
            "and hashes committed, never sentence text."
        ),
        "domain_caveat": (
            "the usable subcorpora are biomedical scientific writing, not "
            "clinical notes, and medspaCy's ConText rules are clinical rules. "
            "Any score here is OUT OF DOMAIN and must be labelled so. The "
            "clinical subcorpus is de-worded — every token is '*' — and needs "
            "the 2007 CMC challenge text, obtained separately, to reconstitute."
        ),
        "files": files,
    }
    (args.dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
