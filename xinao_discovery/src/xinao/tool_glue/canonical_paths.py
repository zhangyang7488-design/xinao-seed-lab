"""One-home path discovery for tool-glue projection scripts.

Canonical updater bytes live inside the installed/packaged module tree so a
fresh checkout and a wheel install share the same discovery rule.  The
Situation Island path remains the production/default consumer entry; it is a
same-byte operational projection of the canonical resource, never a fragile
``parents[N]`` walk from an editable worktree layout.
"""

from __future__ import annotations

import hashlib
import os
import stat
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
_REPARSE_ATTRIBUTE = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def is_reparse_point(path: Path) -> bool:
    """Return True when ``path`` itself is a symlink or Windows reparse point.

    Uses non-following lstat so a reparse leaf is detected without opening its target.
    """

    try:
        info = path.lstat()
    except OSError:
        return False
    if path.is_symlink() or stat.S_ISLNK(info.st_mode):
        return True
    attributes = int(getattr(info, "st_file_attributes", 0))
    return bool(attributes & _REPARSE_ATTRIBUTE)


def _absolute_lexical(path: Path) -> Path:
    """Absolute path without resolving the final component through a reparse."""

    return Path(os.path.abspath(str(path)))


def _resolve_plain_contained_directory(path: Path, *, root: Path, label: str) -> Path:
    """Resolve one directory under ``root``; reject reparse points and escapes."""

    lexical = _absolute_lexical(path)
    root_abs = _absolute_lexical(root)
    if lexical.exists() or lexical.is_symlink():
        if is_reparse_point(lexical):
            raise CanonicalPathError(
                "OPERATIONAL_PARENT_REPARSE",
                f"{label} is a reparse point: {lexical}",
            )
        if not lexical.is_dir():
            raise CanonicalPathError(
                "OPERATIONAL_PARENT_INVALID",
                f"{label} is not a plain directory: {lexical}",
            )
        resolved = lexical.resolve()
        root_resolved = root_abs.resolve() if root_abs.exists() else root_abs
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise CanonicalPathError(
                "OPERATIONAL_PARENT_ESCAPE",
                f"{label} escapes island root containment: {resolved}",
            ) from exc
        return resolved
    try:
        lexical.relative_to(root_abs if not root_abs.exists() else root_abs.resolve())
    except ValueError as exc:
        raise CanonicalPathError(
            "OPERATIONAL_PARENT_ESCAPE",
            f"{label} escapes island root containment: {lexical}",
        ) from exc
    return lexical


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
    """Return the production/default SI operational updater entry.

    Parent directories are containment-checked without allowing reparse escape.
    The operational leaf is returned as a literal path and is never resolved into
    a foreign symlink/reparse target.
    """

    root = DEFAULT_ISLAND_ROOT if island_root is None else island_root
    root_abs = _absolute_lexical(root)
    if root_abs.exists() or root_abs.is_symlink():
        if is_reparse_point(root_abs):
            raise CanonicalPathError(
                "OPERATIONAL_ISLAND_REPARSE",
                f"island root is a reparse point: {root_abs}",
            )
        root_abs = root_abs.resolve()
    scripts = _resolve_plain_contained_directory(
        root_abs / "scripts",
        root=root_abs,
        label="operational scripts directory",
    )
    leaf = scripts / _CANONICAL_UPDATER_NAME
    if is_reparse_point(leaf):
        raise CanonicalPathError(
            "OPERATIONAL_UPDATER_REPARSE",
            (
                "operational updater leaf is a symlink/reparse point; "
                f"refuse to follow or mutate its target: {leaf}"
            ),
        )
    return leaf


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
    "is_reparse_point",
    "operational_updater_path",
    "package_resources_dir",
    "resolve_production_updater_path",
    "sha256_file",
]
