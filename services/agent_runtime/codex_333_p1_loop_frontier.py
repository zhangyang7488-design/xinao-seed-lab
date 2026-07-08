"""SUNSET stub — 333 p1 loop frontier retired."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.agent_runtime._sunset_module_stub import build_retired_module_payload

STATE_NAME = "codex_333_p1_loop_frontier"


def build(*, runtime_root: str | Path = r"D:\XINAO_RESEARCH_RUNTIME", write: bool = True, **kwargs: Any) -> dict[str, Any]:
    del kwargs
    return build_retired_module_payload(
        module_name=STATE_NAME,
        status="codex_333_p1_loop_frontier_sunset",
        state_dir=STATE_NAME,
        runtime_root=runtime_root,
        write=write,
    )