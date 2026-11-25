"""A persistent cache for concept annotation, because it dominates everything.

Measured on MIMIC-IV discharge summaries: ``annotate_document`` costs **2.38 s
per note** against 0.33 s for the ambiguity profile and 0.07 s for the concept
profile. Tagging one corpus of 1,388 notes is 55 minutes; characterising a
baseline plus 36 corruption conditions is 34 hours. Re-tagging the same
unchanged notes for a second experiment is 55 minutes nobody should spend twice.

So the annotation is written to disk, keyed by **what actually determines it**:

    <root>/<matcher-config digest>/<note sha256 first two>/<note sha256>.json

Both halves of the key are load-bearing. The note hash means corrupted text gets
its own entry rather than silently reusing the clean note's mentions — the whole
point of the experiment is that the corrupted text tags differently. The matcher
digest means changing the similarity threshold, the semantic-type filter or the
index invalidates every entry rather than mixing two configurations in one
result, which is the failure a cache keyed on text alone would produce and never
report.

**No note text is stored.** An entry holds offsets, CUIs, semantic types and
similarities — the same "identifiers and offsets, never surfaces" rule the CUI
map and the concept lockfiles follow. Surfaces are reconstructed from the
document the caller already holds, so a cache directory carries no more
redistribution risk than an edit script does.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from robustehr.concepts.matcher import Mention, MentionIndex
from robustehr.types import Span

if TYPE_CHECKING:  # pragma: no cover
    from robustehr.document import Document

#: Bump when the stored shape changes. An old entry is then a miss rather than a
#: misparse, so an upgrade costs a re-tag and never a wrong answer.
CACHE_VERSION = 1

DEFAULT_ROOT = Path("data") / "concept_cache"


@dataclass(frozen=True, slots=True)
class MentionCache:
    """Read-through cache of :func:`annotate_document` over a corpus."""

    root: Path
    config_digest: str
    hits: int = 0
    misses: int = 0

    @classmethod
    def open(cls, root: Path | str, matcher: Any) -> MentionCache:
        """Key on the matcher's pinned configuration, plus the index location.

        Two matchers with the same thresholds over different UMLS releases must
        not share entries, and the index path is the only handle on the release
        available here.
        """
        config = getattr(matcher, "config", None)
        canon = config.canon() if config is not None and hasattr(config, "canon") else "default"
        index = str(getattr(matcher, "index", "") or "")
        digest = hashlib.sha256(f"{CACHE_VERSION}\x1f{canon}\x1f{index}".encode()).hexdigest()[:16]
        return cls(root=Path(root), config_digest=digest)

    def _path(self, sha256: str) -> Path:
        return self.root / self.config_digest / sha256[:2] / f"{sha256}.json"

    def get(self, doc: Document) -> MentionIndex | None:
        """The stored annotation for this exact text, or ``None``.

        A corrupt or truncated entry — an interrupted write on a previous run —
        is treated as a miss and silently re-tagged. Raising instead would let
        one bad file stop a sweep that can trivially recover.
        """
        path = self._path(doc.sha256)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload["mentions"]
        except (json.JSONDecodeError, KeyError, OSError):  # pragma: no cover - defensive
            return None
        return MentionIndex(
            tuple(
                Mention(
                    span=Span(start, end),
                    cui=cui,
                    tuis=frozenset(tuis),
                    similarity=similarity,
                    # Reconstructed, never stored: the surface IS note text.
                    surface=doc.text[start:end],
                )
                for start, end, cui, tuis, similarity in rows
            )
        )

    def put(self, doc: Document, mentions: MentionIndex) -> None:
        """Store one annotation, atomically.

        Written to a temporary file and renamed, so a killed sweep leaves either
        a complete entry or none — never a half-written one that a later run
        would have to detect.
        """
        path = self._path(doc.sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CACHE_VERSION,
            "note_sha256": doc.sha256,
            "mentions": [
                [m.span.start, m.span.end, m.cui, sorted(m.tuis), m.similarity]
                for m in mentions.mentions
            ],
        }
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            os.replace(temp, path)
        except BaseException:  # pragma: no cover - defensive
            Path(temp).unlink(missing_ok=True)
            raise

    def annotate(self, doc: Document, matcher: Any, **kwargs: Any) -> MentionIndex:
        """Cached :func:`~robustehr.concepts.pipeline.annotate_document`."""
        from robustehr.concepts.pipeline import annotate_document

        found = self.get(doc)
        if found is not None:
            object.__setattr__(self, "hits", self.hits + 1)
            return found
        mentions = annotate_document(doc, matcher, **kwargs)
        self.put(doc, mentions)
        object.__setattr__(self, "misses", self.misses + 1)
        return mentions

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "root": str(self.root),
            "config_digest": self.config_digest,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 4) if total else None,
        }


__all__ = ["CACHE_VERSION", "DEFAULT_ROOT", "MentionCache"]
