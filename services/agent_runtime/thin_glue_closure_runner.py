"""Alias — 闭环已并入 thin_glue_loop；本模块保持兼容 import."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_loop import run_thin_glue_loop
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME


def run_thin_glue_closure(
    input_path: Path,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    prefer_docker: bool = True,
    probe_gateway: bool = True,
) -> dict[str, Any]:
    return run_thin_glue_loop(
        input_path,
        runtime_root=runtime_root,
        repo_root=repo_root,
        prefer_docker=prefer_docker,
        invoke_gateway_chat=False,
        write=True,
    )


def main(argv: list[str] | None = None) -> int:
    from services.agent_runtime.thin_glue_loop import main as loop_main

    return loop_main(argv)