"""A cached, opt-in LLM client for operators that need one.

**Why this exists in `src/` at all.** Everything else in this package is a pure
function of its inputs and its committed resources. This is not, and the reason
is measured: on the held-out MIMIC gold a cheap model reads assertion at F1
0.865-0.970 where the shipped rules read 0.294-0.608. An operator that flips a
modifier by rewriting the sentence can do things a lookup table cannot — reflow a
clause, agree a verb, drop a stranded preposition — and the package would be
poorer for pretending otherwise.

**How it stays compatible with replayable edit scripts.** Operators are
*proposers*: the artifact a run produces is a list of concrete
``(start, end, replacement)`` edits, and applying that list is byte-identical
forever regardless of what proposed it. What an LLM breaks is not *replay* but
*regeneration* — and that is closed by caching every completion under a key
derived from the model id and the exact prompt. With the cache present a rerun
is offline and identical; without it, the first run calls out. This is the same
mechanism the assertion gold already uses, for the same reason.

Three properties follow, and all three are enforced here rather than documented
and hoped for:

* **Opt-in by construction.** No model configured means no client, which means
  the LLM operators report zero eligible units. They cannot fire by accident.
* **Note text leaves the machine.** Every request carries
  ``provider: {"data_collection": "deny"}``, which restricts OpenRouter to
  providers that do not retain or train on prompts. That is a mitigation, not a
  permission: a user running these operators on data held under a use agreement
  is making a disclosure, and `configure` says so.
* **Attribution needs three facts, not one.** An LLM operator's output is
  reproducible from *(operator version, model id, cache)*. The prompt template
  is a package resource so it hashes into the operator version; the model id and
  the cache digest are reported by `provenance` and belong in any artifact that
  names an LLM operator.

**No backoff, and that is a real constraint honestly stated.** `time` and
`datetime` cannot be imported anywhere under `src/` — the determinism lint
forbids it, because a timestamp near a seed makes runs unreproducible. So
retries here are immediate and bounded rather than exponential. A rate-limited
run fails with a message telling the user to run it again, and the cache makes
the second attempt cheap.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

#: Immediate retries. Not exponential: see the module docstring on wall-clock.
MAX_ATTEMPTS = 3

#: Environment variables. A model must be named explicitly — there is no default
#: model, because a default would mean a user's notes could reach a third party
#: through a setting they never chose.
MODEL_ENV = "ROBUSTEHR_LLM_MODEL"
KEY_ENV = "OPENROUTER_API_KEY"
CACHE_ENV = "ROBUSTEHR_LLM_CACHE"

DEFAULT_CACHE = Path("data/llm_cache")


class LlmUnavailable(RuntimeError):
    """No model configured, or no credentials. Callers degrade rather than fail."""


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """What an LLM-backed operator needs, and everything it is allowed to vary.

    `temperature` is fixed at zero and is not a field. A sampling temperature
    would make the *first* run of a given prompt unreproducible even in
    principle, and the cache would then be recording one draw from a
    distribution rather than the model's answer.
    """

    model: str
    cache: Path
    key: str

    def digest(self) -> str:
        """Identity of this configuration, minus the credential."""
        return hashlib.blake2b(self.model.encode("utf-8"), digest_size=8).hexdigest()


def _key() -> str:
    """The API key, from the environment. Never an argument, never a file.

    No file fallback: a library that picks up a credential from its working
    directory sends your notes to a third party because of where you happened
    to run it. The environment variable is the only source.
    """
    if found := os.environ.get(KEY_ENV):
        return found.strip()
    raise LlmUnavailable(
        f"No OpenRouter credentials: set {KEY_ENV}. None ships with this package, "
        "and none is read from the working directory."
    )


def configure(model: str | None = None, cache: Path | None = None) -> LlmConfig:
    """Resolve the client configuration, or raise `LlmUnavailable`.

    **Calling this is the disclosure decision.** A configured model means note
    text is sent to a third-party API. `provider.data_collection=deny` keeps it
    away from providers that retain prompts, and that is a mitigation rather
    than a permission — data held under a use agreement may need authorisation
    this package cannot grant.
    """
    name = model or os.environ.get(MODEL_ENV)
    if not name:
        raise LlmUnavailable(
            f"No LLM model configured. Set {MODEL_ENV} (for example "
            "'google/gemini-2.5-flash') or pass `llm_model` as an operator "
            "parameter. There is no default: sending note text to a third "
            "party is a choice this package will not make for you."
        )
    root = cache or Path(os.environ.get(CACHE_ENV) or DEFAULT_CACHE)
    return LlmConfig(model=name.strip(), cache=root, key=_key())


def available(model: str | None = None) -> bool:
    """Whether an LLM-backed operator can run at all, without raising."""
    try:
        configure(model)
    except LlmUnavailable:
        return False
    return True


def cache_key(config: LlmConfig, prompt: str) -> str:
    """Content address of one completion. Model and prompt, never the key."""
    material = f"{config.model}\x1f{prompt}".encode()
    return hashlib.blake2b(material, digest_size=16).hexdigest()


def complete(config: LlmConfig, prompt: str) -> str:
    """One completion, cached. Offline and byte-identical on a cache hit.

    Raises `LlmUnavailable` when the call fails after `MAX_ATTEMPTS`, so a
    caller can fall back to a deterministic path rather than aborting a corpus
    run on one bad response.
    """
    hit = config.cache / f"{cache_key(config, prompt)}.json"
    if hit.exists():
        payload = json.loads(hit.read_text(encoding="utf-8"))
        return str(payload["choices"][0]["message"]["content"])

    body = json.dumps(
        {
            "model": config.model,
            "temperature": 0,
            "provider": {"data_collection": "deny"},
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {config.key}",
            "Content-Type": "application/json",
            "X-Title": "RobustEHR semantic flip",
        },
    )
    last = ""
    for _attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
        # `http.client.HTTPException` covers RemoteDisconnected, which URLError
        # does NOT: a provider closing the socket mid-request raised straight
        # through the retry loop and killed the whole pass on one dropped
        # connection. OSError catches the rest of the socket-level failures.
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
            json.JSONDecodeError,
        ) as error:
            last = str(error)
            continue
        if "choices" not in payload:
            last = str(payload)[:200]
            continue
        config.cache.mkdir(parents=True, exist_ok=True)
        hit.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return str(payload["choices"][0]["message"]["content"])
    raise LlmUnavailable(
        f"{config.model} failed after {MAX_ATTEMPTS} attempts: {last}. "
        "Retries here are immediate rather than backed off, because the "
        "determinism lint forbids wall-clock under src/. Run again — cached "
        "completions make the retry cheap."
    )


def provenance(config: LlmConfig) -> dict[str, str]:
    """The facts an artifact must carry to make an LLM edit attributable.

    An operator version alone is not enough: two runs of the same operator
    against different models produce different edits from identical code. The
    model id belongs beside the version wherever an LLM operator is named.
    """
    return {
        "model": config.model,
        "config_digest": config.digest(),
        "cache": str(config.cache),
        "temperature": "0",
        "data_collection": "deny",
        "reproducibility": (
            "the emitted edit script replays byte-identically forever. "
            "Regenerating it needs either the cache or the same model."
        ),
    }


__all__ = [
    "DEFAULT_CACHE",
    "LlmConfig",
    "LlmUnavailable",
    "available",
    "cache_key",
    "complete",
    "configure",
    "provenance",
]
