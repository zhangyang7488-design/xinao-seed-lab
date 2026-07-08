"""SUNSET stub — 333 continuity router retired."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.agent_runtime._sunset_module_stub import build_retired_module_payload

TASK_ID = "codex_333_stateful_continuity_router_20260706"
STATE_NAME = "codex_333_stateful_continuity_router"


def build(
    *,
    runtime_root: str | Path = r"D:\XINAO_RESEARCH_RUNTIME",
    repo_root: str | Path | None = None,
    source_files: list[Path] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    del repo_root, source_files
    return build_retired_module_payload(
        module_name=STATE_NAME,
        status="codex_333_stateful_continuity_router_sunset",
        state_dir=STATE_NAME,
        runtime_root=runtime_root,
        write=write,
        validation_passed=True,
    )