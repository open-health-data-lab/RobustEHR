"""Concept-tag a whole corpus, cached on disk and spread across cores.

`MentionCache` and `ConceptMatcher` handle one document. This handles a corpus,
which is a different problem: tagging costs ~2.4 s/note and is 86% of the concept
pipeline, so a full characterisation of a few dozen corpora is a multi-day job
run single-threaded and a one-off run cached.

Three properties make that tractable, and they are the reason this lives in the
package rather than in whichever script needed it first:

* **cached** by note hash, so a note already tagged under this matcher
  configuration is never tagged again — across conditions, across runs, and
  across experiments;
* **parallel** across processes, because QuickUMLS is CPU-bound and single
  threaded, so threads buy nothing;
* **keyed on the matcher config**, so changing a threshold invalidates the cache
  rather than silently mixing two configurations into one measurement.

The last one is the correctness property. A cache keyed on note hash alone would
serve a note tagged at `threshold=0.7` to a run asking for `0.9` and the mixture
would never surface in the output.

No wall clock is read here, deliberately: `tests/unit/test_determinism_lint.py`
bans `time` and `datetime` across the package, and a progress timer is not worth
an exemption to a rule that exists to keep every code path a pure function of its
inputs. Callers that want elapsed time can measure the call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["annotate_corpus"]


def annotate_corpus(
    docs: list[Any],
    index: Path,
    cache_root: Path,
    *,
    workers: int = 1,
    label: str = "corpus",
    verbose: bool = True,
) -> dict[str, Any]:
    """Return `{doc.uid: mentions}` for every document that tagged successfully.

    Documents already in the cache are returned without re-tagging. Documents
    that miss are tagged — in this process when `workers <= 1`, otherwise across
    `workers` spawned processes — and then read back through the same cache, so
    the parallel and serial paths return byte-identical results.
    """
    from robustehr.concepts.cache import MentionCache
    from robustehr.concepts.matcher import ConceptMatcher

    matcher = ConceptMatcher(index)
    cache = MentionCache.open(cache_root, matcher)

    pending = [d for d in docs if cache.get(d) is None]
    cached = len(docs) - len(pending)
    if verbose:
        print(
            f"  {label}: {cached}/{len(docs)} already tagged, {len(pending)} to do",
            flush=True,
        )
    if pending:
        _annotate_pending(pending, index, cache_root, workers)

    out: dict[str, Any] = {}
    for doc in docs:
        found = cache.get(doc)
        if found is not None:
            out[doc.uid] = found
    return out


def _annotate_pending(pending: list[Any], index: Path, cache_root: Path, workers: int) -> None:
    """Fill the cache for the notes that miss, in parallel or in this process."""
    if workers <= 1:
        from robustehr.concepts.cache import MentionCache
        from robustehr.concepts.matcher import ConceptMatcher

        matcher = ConceptMatcher(index)
        cache = MentionCache.open(cache_root, matcher)
        for doc in pending:
            cache.annotate(doc, matcher)
        return

    import multiprocessing as mp

    # Each worker loads its own QuickUMLS index once and then drains a share of
    # the notes. Passing (uid, text) rather than Document keeps what crosses the
    # process boundary small and picklable.
    payload = [(d.uid, d.text) for d in pending]
    chunks = [payload[i::workers] for i in range(workers)]
    ctx = mp.get_context("spawn")
    procs = [
        ctx.Process(target=_worker, args=(chunk, str(index), str(cache_root)))
        for chunk in chunks
        if chunk
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()
        if proc.exitcode:
            raise SystemExit(f"concept worker failed with exit code {proc.exitcode}")


def _worker(payload: list[tuple[str, str]], index: str, cache_root: str) -> None:
    from robustehr.concepts.cache import MentionCache
    from robustehr.concepts.matcher import ConceptMatcher
    from robustehr.document import Document

    matcher = ConceptMatcher(Path(index))
    cache = MentionCache.open(Path(cache_root), matcher)
    for uid, text in payload:
        cache.annotate(Document.from_text(text, uid=uid), matcher)
