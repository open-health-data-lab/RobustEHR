"""How clinical a token is, measured rather than assumed.

`robustehr.lexical` answers *what kind of word is this* from intrinsic
properties — is it ordinary English, is it a function word. Three such
attributes were tried as clinical/non-clinical discriminators and all three
failed to separate ``one``, ``well`` and ``stairs`` from ``dyspnea``
(``validation/methodology/06-lexicon-construction.md``).

This module answers a different, narrower question: **in a named corpus, how
often does this token fall inside a span a clinician adjudicated as a clinical
concept?** That is empirical and it does separate those cases — ``she`` 0.00,
``patient`` 0.00, ``history`` 0.00 against ``pneumonia`` 0.98, ``hypertension``
0.99. Measured against the SNOMED CT Entity Linking gold on held-out notes:
precision 0.89 at 25% token coverage, against 0.50 at 46% for "any UMLS
mention" (``validation/protocol.md`` §9).

**It is not a definition of "clinical".** It cannot resolve *purulent discharge*
from *discharge summary*; what it exploits is that within one corpus and one
note type most tokens are used one way. The lexicon carries the corpus it was
measured on, and :func:`manifest` hands that to the run manifest so a result
cannot silently claim more than was validated.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

SALIENCE_RESOURCE = "clinical_salience.json"
MANIFEST_RESOURCE = "clinical_salience.manifest.json"

#: Adopted operating point. Chosen for precision rather than F1: peak F1 sits at
#: 0.40, but a corruption experiment samples a dose from whatever is eligible, so
#: what matters is that the edits made land on clinical content — not that every
#: clinical token is reachable. 0.50 gives 0.890 precision at 0.767 recall
#: against 0.852 / 0.812 at 0.40.
DEFAULT_THRESHOLD = 0.50


@lru_cache(maxsize=1)
def _payload() -> dict[str, Any]:
    text = resources.files("robustehr.resources").joinpath(SALIENCE_RESOURCE).read_text("utf-8")
    return dict(json.loads(text))


@lru_cache(maxsize=1)
def table() -> dict[str, float]:
    """`token -> salience`, lowercase keys."""
    return dict(_payload()["salience"])


@lru_cache(maxsize=1)
def prior() -> float:
    """Salience of a token the corpus never showed us.

    Deliberately below every usable threshold. An unseen token is not evidence of
    anything, and admitting it here would make the rule's behaviour depend on how
    much of the corpus happened to be annotated. Unseen clinical terms are
    admitted by a different clause — the drug vocabulary, or the tagged-and-OOV
    fallback — which is a claim about *that* evidence rather than about absence.
    """
    return float(_payload()["prior"])


def salience(token: str) -> float:
    """How often this token sits inside an adjudicated clinical span.

    Case-folded, because the lexicon is. Getting this wrong is not hypothetical:
    an early evaluation passed original-case tokens against lowercase keys, every
    capitalised word silently fell to the prior, and measured recall dropped from
    0.812 to 0.513 without anything looking broken.
    """
    return table().get(token.lower(), prior())


def is_clinical(token: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    return salience(token) >= threshold


@lru_cache(maxsize=1)
def manifest() -> dict[str, Any]:
    """Provenance for the run manifest: corpus, digest, validation pointer.

    Travels with every result that used this lexicon. `validation-protocol` §9
    requires a targeting claim to quote its rule, its lexicon digest and its
    benchmark; this is how the second and third get there.
    """
    text = resources.files("robustehr.resources").joinpath(MANIFEST_RESOURCE).read_text("utf-8")
    return dict(json.loads(text))


__all__ = [
    "DEFAULT_THRESHOLD",
    "MANIFEST_RESOURCE",
    "SALIENCE_RESOURCE",
    "is_clinical",
    "manifest",
    "prior",
    "salience",
    "table",
]
