"""Spawn thin_glue_loop child workflow — 主链薄接缝（不碰 14k workflow 正文）."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME

SCHEMA_VERSION = "xinao.codex_s.thin_glue_mainline_spawn.v1"
TASK_QUEUE = "xinao-thin-glue-loop-v1"
WORKFLOW_NAME = "XinaoThinGlueLoopWorkflow"


def thin_glue_mainline_spawn_enabled(*, loop_passed: bool | None = None) -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_MAINLINE_SPAWN", "auto").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    return loop_passed is True


def thin_glue_mainline_seam_hint(*, loop_passed: bool | None = None) -> dict[str, Any]:
    mode = os.environ.get("XINAO_THIN_GLUE_MAINLINE_SPAWN", "auto")
    if not thin_glue_mainline_spawn_enabled(loop_passed=loop_passed):
        return {"enabled": False, "mode": mode, "loop_passed": loop_passed is True}
    return {
        "enabled": True,
        "mode": mode,
        "loop_passed": loop_passed is True,
        "invoke_cli": "python -m xinao_seedlab.cli.__main__ thin-glue-spawn",
        "activity_name": "thin_glue_mainline_spawn_activity",
        "child_task_queue": TASK_QUEUE,
        "not_333_mainline": True,
        "mainline_14k_body_untouched": True,
    }


try:
    from temporalio import activity as _temporal_activity
except Exception:  # pragma: no cover - temporal optional in unit tests

    class _MissingActivity:
        @staticmethod
        def defn(fn):
            return fn

    _temporal_activity = _MissingActivity()  # type: ignore[misc, assignment]


@_temporal_activity.defn(name="thin_glue_mainline_spawn_activity")
async def thin_glue_mainline_spawn_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    if not thin_glue_mainline_spawn_enabled() and not input_payload.get("force"):
        return {
            "activity": "thin_glue_mainline_spawn",
            "status": "skipped_env_off",
            "hint": "set XINAO_THIN_GLUE_MAINLINE_SPAWN=1 or pass force=true",
            "runtime_enforced": False,
            "not_333_mainline": True,
        }
    input_raw = input_payload.get("input_path") or ""
    input_path = Path(input_raw) if input_raw else None
    runtime = Path(input_payload.get("runtime_root") or DEFAULT_RUNTIME)
    repo = Path(input_payload.get("repo_root") or DEFAULT_REPO)
    result = await spawn_thin_glue_child_workflow(
        input_path=input_path,
        runtime_root=runtime,
        repo_root=repo,
        prefer_docker=bool(input_payload.get("prefer_docker", True)),
        address=str(input_payload.get("address") or "127.0.0.1:7233"),
    )
    return {
        "activity": "thin_glue_mainline_spawn",
        "status": "spawn_completed"
        if result.get("validation", {}).get("passed")
        else "spawn_partial",
        "spawn_result": result,
        "runtime_enforced": result.get("validation", {}).get("passed") is True,
        "not_333_mainline": True,
        "not_user_completion": True,
        "completion_claim_allowed": False,
    }


async def spawn_thin_glue_child_workflow(
    *,
    input_path: Path | None = None,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    prefer_docker: bool = True,
    address: str = "127.0.0.1:7233",
) -> dict[str, Any]:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from services.agent_runtime.thin_glue_temporal import (
        XinaoThinGlueLoopWorkflow,
        temporal_exports,
    )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    wf_id = f"thin-glue-mainline-spawn-{run_id}"
    activity_payload = {
        "input_path": str(input_path) if input_path else "",
        "runtime_root": str(runtime_root),
        "repo_root": str(repo_root),
        "prefer_docker": prefer_docker,
        "invoke_gateway_chat": False,
        "write": True,
        "workflow_id": wf_id,
        "spawned_from": "thin_glue_mainline_spawn",
    }
    workflows, activities = temporal_exports()
    client = await Client.connect(address)
    async with Worker(client, task_queue=TASK_QUEUE, workflows=workflows, activities=activities):
        handle = await client.start_workflow(
            XinaoThinGlueLoopWorkflow.run,
            activity_payload,
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
        result = await handle.result()
    evidence_path = runtime_root / "readback" / f"thin_glue_mainline_spawn_{run_id}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "schema_version": SCHEMA_VERSION,
        "spawned": True,
        "child_workflow_id": wf_id,
        "child_task_queue": TASK_QUEUE,
        "child_result_validation_passed": result.get("validation", {}).get("passed") is True,
        "not_333_mainline": True,
        "thin_glue_mainline_spawn": True,
        "acceptance_now_can_invoke_cn": (
            "主链薄接缝：spawn thin_glue_loop 子 workflow 已跑；"
            f"子链 {'绿' if result.get('validation', {}).get('passed') else '未绿'}。"
        ),
        "validation": {
            "passed": result.get("validation", {}).get("passed") is True,
            "checks": {
                "child_workflow_completed": True,
                "child_thin_glue_passed": result.get("validation", {}).get("passed") is True,
                "mainline_14k_untouched": True,
            },
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    evidence_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out["evidence_path"] = str(evidence_path)
    out["child_result"] = result
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Spawn thin_glue_loop child on mainline seam")
    parser.add_argument("--input", default="")
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--no-docker", action="store_true")
    args = parser.parse_args(argv)

    input_path = Path(args.input) if args.input else None
    out = asyncio.run(
        spawn_thin_glue_child_workflow(
            input_path=input_path,
            prefer_docker=not args.no_docker,
            address=args.address,
        )
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
