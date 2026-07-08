"""SUNSET stub wave5 — durable supervisor → integrated_bus_worker_daemon + runner."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.durable_default_chain_supervisor.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_DURABLE_DEFAULT_CHAIN_SUPERVISOR_SUNSET_STUB_V1"
TASK_ID = "xinao_seed_cortex_phase0_20260701"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_QUEUE = "xinao-integrated-langgraph-plugin-queue"


def build_supervisor_tick(*, runtime_root: Path = DEFAULT_RUNTIME, repo_root: Path = DEFAULT_REPO, write: bool = True, **kwargs: Any) -> dict[str, Any]:
    del kwargs
    from services.agent_runtime.integrated_bus_runner import run_integrated_bus

    try:
        bus = run_integrated_bus(None, runtime_root=runtime_root, repo_root=repo_root, temporal=False, mainline_default=True)
        passed = bus.get("validation", {}).get("passed") is True
    except Exception as exc:
        bus = {"error": str(exc)}
        passed = False
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "durable_default_chain_supervisor_sunset",
        "handroll_intact": False,
        "integrated_bus_default": True,
        "task_queue": DEFAULT_TASK_QUEUE,
        "integrated_bus": bus,
        "validation": {"passed": passed},
        "acceptance_now_can_invoke_cn": "supervisor sunset → integrated_bus_v2 local invoke",
    }
    if write:
        out = runtime_root / "state" / "codex_s_durable_default_chain_supervisor" / "latest.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["latest_ref"] = str(out)
    return payload


def build(**kwargs: Any) -> dict[str, Any]:
    return build_supervisor_tick(**kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build_supervisor_tick(
        runtime_root=Path(args.runtime_root),
        repo_root=Path(args.repo_root),
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())