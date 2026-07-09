"""P0-S3/S4 task entry durable claim — Temporal SDK thin bind (no ps1 orchestrator)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233")
SCHEMA_VERSION = "xinao.task_entry.claim_durable.v1"
SENTINEL = "SENTINEL:XINAO_TASK_ENTRY_CLAIM_DURABLE_V1"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_intake(runtime: Path, task_id: str) -> tuple[dict[str, Any], Path]:
    state_root = runtime / "state" / "task_entry"
    latest_path = state_root / "latest.json"
    if task_id in {"", "latest"}:
        intake = read_json(latest_path)
        return intake, latest_path
    candidate = state_root / "intake" / f"{task_id}.json"
    if candidate.is_file():
        return read_json(candidate), latest_path
    intake = read_json(latest_path)
    if str(intake.get("task_id") or "") == task_id:
        return intake, latest_path
    raise FileNotFoundError(f"intake not found for task_id={task_id}")


def build_work_package(intake: dict[str, Any], latest_path: Path) -> dict[str, Any]:
    l1 = intake.get("l1_structured") or {}
    return {
        "objective": str(intake.get("intent_one_liner") or ""),
        "task_entry_id": str(intake.get("task_id") or ""),
        "entry_kind": str(intake.get("entry_kind") or ""),
        "source_kind": "grok_task_entry_intake",
        "intake_ref": str(latest_path),
        "acceptance": list(l1.get("acceptance") or []),
    }


async def claim_durable_async(
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    task_id: str = "latest",
    temporal_address: str = DEFAULT_ADDRESS,
    execute_codex_worker: bool = False,
) -> dict[str, Any]:
    from services.agent_runtime import temporal_codex_task_workflow as tcw

    intake, latest_path = resolve_intake(runtime_root, task_id)
    if not intake:
        raise FileNotFoundError("no staged intake; run Invoke-GrokTaskEntry first")

    resolved_task_id = str(intake.get("task_id") or task_id)
    claim_dir = runtime_root / "state" / "task_entry" / "durable_claim"
    claim_dir.mkdir(parents=True, exist_ok=True)
    wp = build_work_package(intake, latest_path)
    wp_file = claim_dir / f"work_package_{resolved_task_id}.json"
    write_json(wp_file, wp)

    material_refs: list[str] = []
    l0 = intake.get("l0_intake") or {}
    if isinstance(l0.get("material_refs"), list):
        material_refs = [str(x) for x in l0["material_refs"] if x]

    payload = {
        "runtime_root": str(runtime_root),
        "repo_root": str(repo_root),
        "task_id": resolved_task_id,
        "user_goal": wp["objective"],
        "mode": "partial",
        "address": temporal_address,
        "work_package_json": str(wp_file),
        "source_refs": material_refs,
        "execute_codex_worker": execute_codex_worker,
    }

    blockers: list[str] = []
    claim_state = "claim_blocked"
    durable_ref = ""
    wf_id = ""
    run_id = ""

    try:
        result = await tcw.run_live_temporal_workflow(payload)
        tcw.persist_workflow_result(runtime_root, result)
        tw_latest = runtime_root / "state" / "temporal_codex_task_workflow" / "latest.json"
        durable_ref = str(tw_latest) if tw_latest.is_file() else ""
        wf_id = str(result.get("workflow_id") or "")
        run_id = str(result.get("workflow_run_id") or "")
        server_bound = bool(result.get("server_bound"))
        workflow_open = bool(result.get("workflow_open"))
        temporal_live = bool(result.get("temporal_live_route"))
        # P0-S3 认领 = Temporal 耐久 owner 已接活（波内可仍在跑）
        if run_id and temporal_live and (server_bound or workflow_open):
            claim_state = "durable_claimed"
        else:
            claim_state = "claim_attempted_not_server_bound"
            blocker = str(result.get("named_blocker") or result.get("status") or "NOT_SERVER_BOUND")
            blockers.append(blocker)
    except Exception as exc:
        claim_state = "claim_failed"
        blockers.append(str(exc))

    intent = wp["objective"]
    intake_out = dict(intake)
    intake_out.update(
        {
            "claim_state": claim_state,
            "durable_claim_at": now(),
            "durable_evidence_ref": durable_ref,
            "temporal_workflow_id": wf_id,
            "temporal_workflow_run_id": run_id,
            "named_blockers": blockers,
            "readback_three_cn": [
                f"①入口读到：{intake.get('entry_kind')} / {intent}",
                f"②durable认领证据：{durable_ref or '无（' + claim_state + '）'}",
                f"③blocker：{'；'.join(blockers) if blockers else '无'}",
            ],
        }
    )
    write_json(latest_path, intake_out)
    claim_record = claim_dir / f"claim_{resolved_task_id}.json"
    write_json(claim_record, intake_out)

    report = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "generated_at": now(),
        "intake_task_id": resolved_task_id,
        "claim_state": claim_state,
        "carrier": "temporal_sdk_task_entry_claim",
        "temporal_address": temporal_address,
        "durable_evidence_ref": durable_ref,
        "temporal_workflow_id": wf_id,
        "temporal_workflow_run_id": run_id,
        "named_blockers": blockers,
        "work_package_ref": str(wp_file),
        "completion_claim_allowed": False,
        "not_user_completion": True,
    }
    write_json(claim_dir / "latest.json", report)
    return report


def claim_durable(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(claim_durable_async(**kwargs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P0 durable claim via Temporal SDK")
    parser.add_argument("--task-id", default="latest")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--execute-codex-worker", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = claim_durable(
            runtime_root=Path(args.runtime_root),
            repo_root=Path(args.repo_root),
            task_id=args.task_id,
            temporal_address=args.address,
            execute_codex_worker=args.execute_codex_worker,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("claim_state") == "durable_claimed" else 1
    except Exception as exc:
        print(json.dumps({"claim_state": "claim_failed", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())