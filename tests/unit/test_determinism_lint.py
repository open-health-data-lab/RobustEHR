"""Static bans on constructs that silently break reproducibility.

Each of these is a real hazard rather than a style preference, and each has bitten
somebody in a published pipeline. Enforcing them by AST rather than by review means
they cannot creep back in.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from robustehr.rng import SeedMaterial

SRC = Path(__file__).resolve().parents[2] / "src" / "robustehr"

#: These bans exist so a corrupted corpus is a pure function of
#: (corpus, operator, severity, salt) — the guarantee the whole method rests on.
#:
#: Every exemption that used to live here named a file in `robustehr.evaluation`,
#: the MIPA harness: an HTTP client whose outputs are model responses at
#: `temperature=0.5` and were never reproducible in the first place. That harness
#: is now its own package, so the exemptions left with it and the ban applies to
#: the corruption engine without qualification.
#:
#: Keep it that way. A new entry in any of these sets is a claim that some part
#: of the engine may read a clock or an unseeded RNG, and there is no such part.

#: `rng.py` imports `random` to construct seeded `Random` instances, never to
#: draw from the module-level generator.
_ALLOW_RANDOM_IMPORT = {"rng.py"}

#: Nothing in the corruption engine may read wall clock. Not for a progress
#: line, not for a duration — a timing call is one refactor away from a seed.
_ALLOW_WALL_CLOCK: set[str] = set()

#: Nothing needs a non-ASCII-safe regex construct.
_ALLOW_UNICODE_REGEX: set[str] = set()


def source_files() -> list[Path]:
    """Every module in the package, and never an empty list.

    `rglob` over a directory that does not exist returns nothing rather than
    raising, so a mistyped or renamed `SRC` would parametrize this whole class
    with zero cases and report a green run for a check that examined nothing.
    The package was renamed once already (`ehrrobust` to `robustehr`); this is
    the guard that would have caught it.
    """
    found = sorted(SRC.rglob("*.py"))
    if not found:
        raise AssertionError(
            f"no source files under {SRC} — the determinism lint is scanning nothing. "
            "Fix SRC rather than deleting this check."
        )
    return found


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
class TestBannedConstructs:
    def test_no_builtin_hash_or_id(self, path: Path) -> None:
        """`hash()` and `id()` vary with PYTHONHASHSEED and process memory."""
        offenders = [
            node.lineno
            for node in ast.walk(parse(path))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"hash", "id"}
        ]
        assert not offenders, f"{path.name}: builtin hash()/id() at lines {offenders}; use hashlib"

    def test_no_unseeded_random_module(self, path: Path) -> None:
        """Only `robustehr.rng` may touch `random`, and only through a seeded wrapper."""
        if path.name in _ALLOW_RANDOM_IMPORT:
            return
        offenders = []
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.Import):
                offenders += [
                    n.lineno for n in [node] if any(a.name == "random" for a in node.names)
                ]
            elif isinstance(node, ast.ImportFrom) and node.module == "random":
                offenders.append(node.lineno)
        assert not offenders, f"{path.name}: imports `random` at {offenders}; use robustehr.rng"

    def test_no_numpy_randomness(self, path: Path) -> None:
        """NumPy's global RNG is process state, not content."""
        text = path.read_text(encoding="utf-8")
        assert "np.random" not in text and "numpy.random" not in text, (
            f"{path.name}: numpy randomness is banned; use robustehr.rng"
        )

    def test_no_unicode_dependent_regex_classes(self, path: Path) -> None:
        r"""`\w`, `\b`, `\s` and `\d` depend on the Unicode database version.

        Two machines on different CPython point releases can disagree about what
        matches, which would silently change every dose denominator.

        Only *code* string literals are scanned. Docstrings are excluded on
        purpose: several of them quote the banned shorthands while explaining
        why a naive implementation using them is wrong, and a lint that punishes
        its own rationale is one people delete.
        """
        if path.name in _ALLOW_UNICODE_REGEX:
            return
        tree = parse(path)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        banned = (r"\w", r"\b", r"\s", r"\d", r"\W", r"\B", r"\S", r"\D")
        offenders: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            offenders += [(node.lineno, token) for token in banned if token in node.value]
        assert not offenders, (
            f"{path.name}: unicode-dependent regex class(es) {offenders}; "
            f"use explicit classes like [A-Za-z0-9_] or compile with re.ASCII"
        )

    def test_no_wall_clock(self, path: Path) -> None:
        """A timestamp anywhere near a seed makes runs unreproducible."""
        if path.name in _ALLOW_WALL_CLOCK:
            return
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.ImportFrom) and node.module in {"time", "datetime"}:
                pytest.fail(f"{path.name}:{node.lineno} imports {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in {"time", "datetime"}, (
                        f"{path.name}:{node.lineno} imports {alias.name}"
                    )


class TestSeedMaterialContract:
    def test_severity_is_absent_from_seed_material(self) -> None:
        """Nested severity ladders depend on severity being outside the key.

        If severity ever enters the seed, `selected(0.10) ⊆ selected(0.30)`
        silently stops holding and every dose-response curve starts mixing dose
        with resampling noise.
        """
        fields = set(SeedMaterial.__dataclass_fields__)
        assert "severity" not in fields
        assert not any("sever" in f for f in fields), fields


#: Shipped data files. The AST lint globs `*.py` only, so a banned construct
#: written into a resource evades every check above it.
RESOURCES = SRC / "resources"


def resource_files() -> list[Path]:
    return sorted(RESOURCES.rglob("*.yaml"))


@pytest.mark.parametrize("path", resource_files(), ids=lambda p: p.name)
def test_resources_carry_no_unicode_dependent_regex_classes(path: Path) -> None:
    r"""The same ban, applied where an AST lint cannot see.

    `\w`, `\b`, `\s` and `\d` depend on the Unicode database version, so two
    machines on different CPython point releases can disagree about what
    matches. Every rule above enforces that in Python source — and a pattern
    shipped in YAML would slip past all of them, which is exactly the gap the
    abbreviation spec flagged before the cue lexicon was written.

    Scans *values*, not comments: several resource headers legitimately quote the
    banned shorthands while explaining why they are banned, and a lint that
    punishes its own rationale is one people delete.
    """
    banned = (r"\w", r"\b", r"\s", r"\d", r"\W", r"\B", r"\S", r"\D")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))

    def walk(node: object, trail: str = "") -> list[tuple[str, str]]:
        if isinstance(node, dict):
            return [hit for k, v in node.items() for hit in walk(v, f"{trail}.{k}")]
        if isinstance(node, list):
            return [hit for i, v in enumerate(node) for hit in walk(v, f"{trail}[{i}]")]
        if isinstance(node, str):
            return [(trail, token) for token in banned if token in node]
        return []

    offenders = walk(loaded)
    assert not offenders, (
        f"{path.name}: unicode-dependent regex class(es) at {offenders}; "
        "resource values are compared literally, so a pattern here is either "
        "dead or non-deterministic"
    )
