from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Evidence/progress runtime (Seed Cortex default).
DEFAULT_EVIDENCE_RUNTIME = Path(
    os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME")
)
COMPAT_RUNTIME_ENV_KEYS = (
    "XINAO_COMPAT_RUNTIME",
    "XINAO_COMPAT_RUNTIME_ROOT",
    "XINAO_UCP_TOOLS_RUNTIME_ROOT",
)
# Tests monkeypatch this module attribute; env override is layered in default_ucp_tools_runtime().
DEFAULT_UCP_TOOLS_RUNTIME = Path(r"D:\XINAO_CLEAN_RUNTIME")


def default_ucp_tools_runtime() -> Path:
    """Resolve UCP tools root at call time so CI/tests can override via env."""
    configured = os.environ.get("XINAO_UCP_TOOLS_RUNTIME_ROOT", "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_UCP_TOOLS_RUNTIME


def _path_exists(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def ucp_tools_runtime_candidates(
    *,
    evidence_runtime_root: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(label: str, root: Path) -> None:
        key = str(root)
        if key in seen:
            return
        seen.add(key)
        candidates.append((label, root))

    if evidence_runtime_root:
        add("evidence_runtime_root", Path(evidence_runtime_root))
    if repo_root:
        add("repo_root", Path(repo_root))
    add("default_ucp_tools_runtime", default_ucp_tools_runtime())
    for key in COMPAT_RUNTIME_ENV_KEYS:
        configured = os.environ.get(key, "").strip()
        if configured:
            add(f"env:{key}", Path(configured))
    return candidates


def resolve_ucp_tool_surface(
    *,
    evidence_runtime_root: str | Path = DEFAULT_EVIDENCE_RUNTIME,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    python_rel = Path("tools") / "codex-sdk-python" / ".venv" / "Scripts" / "python.exe"
    ucp_rel = Path("tools") / "universal_control_plane_v0" / "universal_control_plane_v0.py"
    launcher_rel = (
        Path("tools") / "universal_control_plane_v0" / "run_universal_control_plane_v0.ps1"
    )

    inspected: list[dict[str, Any]] = []
    selected_root: Path | None = None
    selected_label = ""
    python_path = Path()
    ucp_path = Path()
    launcher_path = Path()

    for label, root in ucp_tools_runtime_candidates(
        evidence_runtime_root=evidence_runtime_root,
        repo_root=repo_root,
    ):
        python_candidate = root / python_rel
        ucp_candidate = root / ucp_rel
        launcher_candidate = root / launcher_rel
        python_exists = _path_exists(python_candidate)
        ucp_exists = _path_exists(ucp_candidate)
        inspected.append(
            {
                "label": label,
                "tool_root": str(root),
                "python_exists": python_exists,
                "ucp_exists": ucp_exists,
                "launcher_exists": _path_exists(launcher_candidate),
                "python_path": str(python_candidate),
                "ucp_path": str(ucp_candidate),
            }
        )
        if python_exists and ucp_exists and selected_root is None:
            selected_root = root
            selected_label = label
            python_path = python_candidate
            ucp_path = ucp_candidate
            launcher_path = launcher_candidate

    ready = selected_root is not None
    return {
        "ready": ready,
        "tool_root": str(selected_root or ""),
        "tool_root_source": selected_label or "none",
        "evidence_runtime_root": str(evidence_runtime_root),
        "ucp_tools_runtime_root": str(selected_root or default_ucp_tools_runtime()),
        "python_exists": _path_exists(python_path),
        "ucp_exists": _path_exists(ucp_path),
        "launcher_exists": _path_exists(launcher_path),
        "python_path": str(python_path),
        "ucp_path": str(ucp_path),
        "launcher_path": str(launcher_path),
        "named_blocker": "" if ready else "CODEX_WORKER_UCP_TOOL_SURFACE_MISSING",
        "mature_resolve_order": [
            "evidence_runtime_root/tools",
            "repo_root/tools",
            "D:\\XINAO_CLEAN_RUNTIME/tools (ucp_tools_runtime_root)",
            "env:XINAO_UCP_TOOLS_RUNTIME_ROOT / XINAO_COMPAT_RUNTIME",
        ],
        "inspected_candidates": inspected,
        "compat_note": (
            "Progress/evidence stays on RESEARCH; UCP tool execution may bind to CLEAN compat root."
        ),
    }
