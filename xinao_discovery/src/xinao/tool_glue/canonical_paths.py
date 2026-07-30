"""One-home path discovery for tool-glue projection scripts.

Canonical updater bytes live inside the installed/packaged module tree so a
fresh checkout and a wheel install share the same discovery rule.  The
Situation Island path remains the production/default consumer entry; it is a
same-byte operational projection of the canonical resource, never a fragile
``parents[N]`` walk from an editable worktree layout.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class CanonicalPathError(RuntimeError):
    """Fail-closed path discovery error with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


DEFAULT_ISLAND_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island")
DEFAULT_OPERATIONAL_UPDATER_PATH = (
    DEFAULT_ISLAND_ROOT / "scripts" / "Update-CodexContextCatalog.ps1"
)
DEFAULT_MAINTENANCE_MAP_PATH = (
    DEFAULT_ISLAND_ROOT / "contracts" / "mainline_maintenance_map.v1.json"
)
DEFAULT_SCIENCE_PROJECTION_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\mainline_science_current\active_parent.current.json"
)
DEFAULT_OPERATIONAL_STATE_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\tool_glue_operational_projection"
)

_CANONICAL_UPDATER_NAME = "Update-CodexContextCatalog.ps1"
_RESOURCES_DIRNAME = "resources"


def package_resources_dir() -> Path:
    """Return the package-local resources directory (checkout or wheel)."""

    return Path(__file__).resolve().parent / _RESOURCES_DIRNAME


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_canonical_updater_path() -> Path:
    """Locate the versioned canonical updater resource.

    This path is valid in an editable checkout and in a wheel install.  It must
    never depend on repository-root parent walks such as ``parents[4]``.
    """

    candidate = package_resources_dir() / _CANONICAL_UPDATER_NAME
    if not candidate.is_file():
        raise CanonicalPathError(
            "CANONICAL_UPDATER_MISSING",
            f"canonical updater resource is missing: {candidate}",
        )
    return candidate.resolve()


def discover_projection_binding_verifier_path() -> Path:
    """Locate the formally selected replacement projection binding verifier."""

    candidate = Path(__file__).resolve().parent / "projection_binding_verifier.py"
    if not candidate.is_file():
        raise CanonicalPathError(
            "PROJECTION_BINDING_VERIFIER_MISSING",
            f"projection binding verifier is missing: {candidate}",
        )
    return candidate.resolve()


def operational_updater_path(*, island_root: Path | None = None) -> Path:
    """Return the production/default SI operational updater entry."""

    root = DEFAULT_ISLAND_ROOT if island_root is None else island_root
    return (root / "scripts" / _CANONICAL_UPDATER_NAME).resolve()


def assert_same_bytes(left: Path, right: Path, *, code: str, message: str) -> str:
    """Fail closed unless both files exist and share one SHA-256 digest."""

    if not left.is_file():
        raise CanonicalPathError(code, f"{message}: missing left={left}")
    if not right.is_file():
        raise CanonicalPathError(code, f"{message}: missing right={right}")
    left_digest = sha256_file(left)
    right_digest = sha256_file(right)
    if left_digest != right_digest:
        raise CanonicalPathError(
            code,
            f"{message}: left={left_digest} right={right_digest}",
        )
    return left_digest


def resolve_production_updater_path(*, island_root: Path | None = None) -> Path:
    """Return the SI operational updater after proving same-byte identity with canonical."""

    canonical = discover_canonical_updater_path()
    operational = operational_updater_path(island_root=island_root)
    assert_same_bytes(
        operational,
        canonical,
        code="OPERATIONAL_UPDATER_DRIFT",
        message=(
            "SI operational updater must be a same-byte projection of the "
            "package-canonical updater; run operational install/promote first"
        ),
    )
    return operational


__all__ = [
    "DEFAULT_ISLAND_ROOT",
    "DEFAULT_MAINTENANCE_MAP_PATH",
    "DEFAULT_OPERATIONAL_STATE_ROOT",
    "DEFAULT_OPERATIONAL_UPDATER_PATH",
    "DEFAULT_SCIENCE_PROJECTION_PATH",
    "CanonicalPathError",
    "assert_same_bytes",
    "discover_canonical_updater_path",
    "discover_projection_binding_verifier_path",
    "operational_updater_path",
    "package_resources_dir",
    "resolve_production_updater_path",
    "sha256_file",
]
