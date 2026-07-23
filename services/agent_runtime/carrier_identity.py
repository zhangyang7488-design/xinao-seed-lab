"""Resolve one coherent source carrier without guessing from the process cwd."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT_ENV = "XINAO_CODEX_S_REPO_ROOT"
_HOST_WORKSPACE_MARKER = "XINAO_RESEARCH_WORKSPACES"


def _container_repo_for_host_path(raw: str | Path) -> Path | None:
    normalized = str(raw).replace("\\", "/")
    container_repo = Path("/app")
    if _HOST_WORKSPACE_MARKER in normalized and container_repo.is_dir():
        return container_repo.resolve()
    return None


def _require_existing_directory(raw: str | Path, *, source: str) -> Path:
    path = Path(str(raw))
    if path.is_dir():
        return path.resolve()
    container_repo = _container_repo_for_host_path(raw)
    if container_repo is not None:
        return container_repo
    raise FileNotFoundError(f"{source} does not name an available repository carrier: {raw}")


def repository_root_from_anchor(anchor: str | Path) -> Path:
    """Find the repository that physically contains the loaded source file."""

    current = Path(anchor).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (
            (candidate / "services" / "__init__.py").is_file()
            and (candidate / "services" / "agent_runtime" / "__init__.py").is_file()
        ):
            return candidate
    raise RuntimeError(f"cannot derive repository carrier from loaded source: {anchor}")


def resolve_code_carrier_root(
    explicit: str | Path | None = None,
    *,
    anchor: str | Path = __file__,
) -> Path:
    """Resolve explicit/env carrier first, otherwise bind to the loaded code carrier."""

    if explicit is not None and str(explicit).strip():
        return _require_existing_directory(explicit, source="explicit repository root")
    configured = os.environ.get(REPO_ROOT_ENV, "").strip()
    if configured:
        return _require_existing_directory(configured, source=REPO_ROOT_ENV)
    return repository_root_from_anchor(anchor)
