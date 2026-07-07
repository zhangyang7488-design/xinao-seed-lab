"""Main-queue thin glue seam — activity 已焊进 14k worker；CLI 走已验证 spawn 路径."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

MAIN_TASK_QUEUE = "xinao-codex-task-default"
WORKFLOW_NAME = "XinaoThinGlueMainlineOrchestrator"


async def run_mainline_orchestrator(
    payload: dict[str, Any],
    *,
    address: str = "127.0.0.1:7233",
) -> dict[str, Any]:
    from services.agent_runtime.thin_glue_mainline_spawn import (
        spawn_thin_glue_child_workflow,
        thin_glue_mainline_spawn_enabled,
    )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    wf_id = f"thin-glue-mainline-orch-{run_id}"
    if not thin_glue_mainline_spawn_enabled() and not payload.get("force"):
        return {
            "workflow_id": wf_id,
            "task_queue": MAIN_TASK_QUEUE,
            "status": "skipped_env_off",
            "hint": "set XINAO_THIN_GLUE_MAINLINE_SPAWN=1 or pass --force",
            "validation": {"passed": False},
            "not_333_mainline": True,
        }

    input_raw = payload.get("input_path") or ""
    input_path = Path(input_raw) if input_raw else None
    spawn_result = await spawn_thin_glue_child_workflow(
        input_path=input_path,
        runtime_root=Path(payload.get("runtime_root") or r"D:\XINAO_RESEARCH_RUNTIME"),
        repo_root=Path(payload.get("repo_root") or r"E:\XINAO_RESEARCH_WORKSPACES\S"),
        prefer_docker=bool(payload.get("prefer_docker", True)),
        address=address,
    )
    passed = spawn_result.get("validation", {}).get("passed") is True
    out = {
        "workflow_id": wf_id,
        "task_queue": MAIN_TASK_QUEUE,
        "orchestrator_mode": "direct_child_spawn",
        "activity_on_main_worker": "thin_glue_mainline_spawn_activity",
        "main_worker_restart_required_for_activity_invoke": True,
        "spawn_result": spawn_result,
        "validation": {"passed": passed},
        "not_333_mainline": True,
        "acceptance_now_can_invoke_cn": (
            "主队列薄接缝：spawn 子链已跑；activity 已注册进 temporal_codex_task_workflow worker 列表。"
        ),
    }
    evidence = Path(payload.get("runtime_root") or r"D:\XINAO_RESEARCH_RUNTIME") / "readback" / f"{wf_id}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out["evidence_path"] = str(evidence)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run thin glue mainline orchestrator seam")
    parser.add_argument("--input", default="")
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--no-docker", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME

    payload = {
        "input_path": args.input,
        "runtime_root": str(DEFAULT_RUNTIME),
        "repo_root": str(DEFAULT_REPO),
        "prefer_docker": not args.no_docker,
        "force": args.force,
        "address": args.address,
    }
    out = asyncio.run(run_mainline_orchestrator(payload, address=args.address))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())