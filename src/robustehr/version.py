"""Version and specification identifiers.

``SPEC_VERSION`` is not the package version. It identifies the *determinism
specification*: the seed-derivation scheme, the edit total order, and the
selection algorithm. Changing it changes every previously produced edit script,
so it moves only when that contract genuinely breaks.
"""

from __future__ import annotations

__version__ = "0.2.0"

#: Determinism specification. Folded into every seed. See `robustehr.rng`.
SPEC_VERSION = "robustehr/seed/v1"

#: On-disk schema version for dose records, edit scripts and manifests.
SCHEMA_VERSION = "1.1"

__all__ = ["SCHEMA_VERSION", "SPEC_VERSION", "__version__"]
