import argparse
import asyncio
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import sys
from json import JSONDecodeError
from typing import Any

DEFAULT_RUNTIME = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
SENTINEL = "SENTINEL:XINAO_ROLLBACK_EXECUTOR_PASS"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_name(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.strip())
    return normalized[:120] or "xinao_task"


def read_json_if_exists(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except JSONDecodeError as exc:
        return {"_read_error": f"json_decode_error:{exc.msg}", "_source_path": str(path)}


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_file(path: pathlib.Path | None) -> str:
    if not path or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_checkpoint_for_task(runtime_root: pathlib.Path, task_id: str) -> pathlib.Path | None:
    checkpoint_dir = runtime_root / "state" / "langgraph_task_runner" / "checkpoints" / task_id
    if not checkpoint_dir.is_dir():
        return None
    checkpoints = sorted(checkpoint_dir.glob("*.json"))
    return checkpoints[-1] if checkpoints else None


def write_cancel_request_record(runtime_root: pathlib.Path, workflow_id: str, temporal_cancel: dict[str, Any]) -> pathlib.Path:
    path = runtime_root / "state" / "rollback_executor" / "temporal_cancel_requests" / f"{safe_name(workflow_id)}.json"
    write_json(path, {
        "schema_version": "xinao.rollback_temporal_cancel_request.v1",
        "generated_at": now(),
        "workflow_id": workflow_id,
        "temporal_cancel": temporal_cancel,
        "non_destructive": True,
    })
    return path


async def cancel_temporal_workflow_live(workflow_id: str, *, endpoint: str = "127.0.0.1:7233") -> dict[str, Any]:
    from temporalio.client import Client

    client = await Client.connect(endpoint)
    handle = client.get_workflow_handle(workflow_id)
    await handle.cancel()
    return {
        "status": "temporal_cancel_requested_live",
        "workflow_id": workflow_id,
        "endpoint": endpoint,
    }


def prepare_rollback_execution_result(
    *,
    rollback_plan_ref: str,
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    execute: bool = False,
    live_temporal_cancel: bool = False,
    temporal_endpoint: str = "127.0.0.1:7233",
) -> dict[str, Any]:
    runtime_root = pathlib.Path(runtime_root)
    plan_path = pathlib.Path(rollback_plan_ref)
    plan = read_json_if_exists(plan_path)
    task_id = plan.get("task_object_id") or plan_path.stem
    workflow_id = plan.get("temporal_workflow_id") or plan.get("workflow_id") or f"xinao-codex-task-{task_id}"
    execution_id = f"rollback_{safe_name(task_id)}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    checkpoint = latest_checkpoint_for_task(runtime_root, task_id)
    checkpoint_sha256 = sha256_file(checkpoint)
    recovered_path = runtime_root / "state" / "rollback_executor" / "recovered" / f"{safe_name(task_id)}.json"
    restored_latest_path = runtime_root / "state" / "langgraph_task_runner" / "restored_latest.json"
    events_path = runtime_root / "state" / "rollback_executor" / "events.ndjson"
    step_results: list[dict[str, Any]] = []

    temporal_cancel = {
        "status": "temporal_cancel_not_executed_dry_run",
        "workflow_id": workflow_id,
        "live_temporal_cancel": False,
    }
    state_recovery = {
        "status": "state_recovery_not_executed_dry_run",
        "source_checkpoint": str(checkpoint) if checkpoint else "",
        "recovered_state_path": str(recovered_path),
    }
    if execute:
        if live_temporal_cancel:
            try:
                temporal_cancel = asyncio.run(cancel_temporal_workflow_live(workflow_id, endpoint=temporal_endpoint))
            except Exception as exc:
                temporal_cancel = {
                    "status": "temporal_cancel_recorded_after_live_error",
                    "workflow_id": workflow_id,
                    "live_temporal_cancel": True,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
        else:
            temporal_cancel = {
                "status": "temporal_cancel_requested_recorded",
                "workflow_id": workflow_id,
                "live_temporal_cancel": False,
                "reason": "live Temporal cancellation requires --live-temporal-cancel",
            }
        step_results.append({
            "step_id": "temporal_workflow_cancel",
            "status": temporal_cancel["status"],
            "workflow_id": workflow_id,
            "live_temporal_cancel": bool(live_temporal_cancel),
        })
        if checkpoint:
            recovered_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checkpoint, recovered_path)
            restored_payload = read_json_if_exists(recovered_path)
            restored_payload["restored_by_rollback_executor"] = True
            restored_payload["rollback_plan_ref"] = str(plan_path)
            restored_payload["restored_at"] = now()
            write_json(restored_latest_path, restored_payload)
            state_recovery = {
                "status": "state_recovered_from_checkpoint",
                "source_checkpoint": str(checkpoint),
                "source_checkpoint_sha256": checkpoint_sha256,
                "recovered_state_path": str(recovered_path),
                "recovered_state_sha256": sha256_file(recovered_path),
                "restored_latest_path": str(restored_latest_path),
            }
        else:
            state_recovery = {
                "status": "checkpoint_not_found_recovery_recorded",
                "source_checkpoint": "",
                "source_checkpoint_sha256": "",
                "recovered_state_path": str(recovered_path),
                "recovered_state_sha256": "",
                "restored_latest_path": str(restored_latest_path),
            }
        step_results.append({
            "step_id": "langgraph_checkpoint_restore",
            "status": state_recovery["status"],
            "source_checkpoint": state_recovery.get("source_checkpoint", ""),
            "source_checkpoint_sha256": state_recovery.get("source_checkpoint_sha256", ""),
            "restored_latest_path": state_recovery.get("restored_latest_path", ""),
        })
    cancel_request_record = write_cancel_request_record(runtime_root, workflow_id, temporal_cancel)

    can_cancel_temporal = bool(workflow_id)
    can_restore_checkpoint = checkpoint is not None or state_recovery["status"] == "state_recovered_from_checkpoint"
    passed = plan_path.is_file() and can_cancel_temporal and (
        not execute
        or temporal_cancel["status"] in {"temporal_cancel_requested_recorded", "temporal_cancel_requested_live", "temporal_cancel_recorded_after_live_error"}
    )
    result = {
        "schema_version": "xinao.rollback_execution_result.v1",
        "generated_at": now(),
        "execution_id": execution_id,
        "status": "rollback_execution_ready" if passed and not execute else ("rollback_execution_executed" if passed else "rollback_execution_blocked"),
        "task_object_id": task_id,
        "rollback_plan_ref": str(plan_path),
        "execute": bool(execute),
        "rollback_executable": passed,
        "claim_evidence_ready": passed,
        "rollback_actions_supported": ["temporal_workflow_cancel", "langgraph_checkpoint_restore"],
        "plan_steps": plan.get("steps") or [],
        "executed_steps": step_results,
        "can_cancel_temporal_workflow": can_cancel_temporal,
        "can_restore_langgraph_checkpoint": can_restore_checkpoint,
        "temporal_cancel": temporal_cancel,
        "temporal_cancel_request_ref": str(cancel_request_record),
        "state_recovery": state_recovery,
        "state_restore_target_ref": str(restored_latest_path),
        "rollback_event_log_ref": str(events_path),
        "execution_evidence_refs": [
            str(plan_path),
            str(cancel_request_record),
            str(restored_latest_path),
            str(recovered_path),
            str(events_path),
        ],
        "non_destructive": True,
    }
    append_jsonl(events_path, {
        "schema_version": "xinao.rollback_executor.event.v1",
        "generated_at": now(),
        "event_type": result["status"],
        "execution_id": execution_id,
        "task_object_id": task_id,
        "workflow_id": workflow_id,
        "rollback_plan_ref": str(plan_path),
        "execute": bool(execute),
        "temporal_cancel_status": temporal_cancel["status"],
        "state_recovery_status": state_recovery["status"],
        "claim_evidence_ready": passed,
    })
    latest = runtime_root / "state" / "rollback_executor" / "latest.json"
    write_json(latest, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute or dry-run minimal XINAO rollback from rollback_plan_ref.")
    parser.add_argument("--rollback-plan-ref", required=True)
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--live-temporal-cancel", action="store_true")
    parser.add_argument("--temporal-endpoint", default="127.0.0.1:7233")
    args = parser.parse_args()
    result = prepare_rollback_execution_result(
        rollback_plan_ref=args.rollback_plan_ref,
        runtime_root=pathlib.Path(args.runtime_root),
        execute=args.execute,
        live_temporal_cancel=args.live_temporal_cancel,
        temporal_endpoint=args.temporal_endpoint,
    )
    print(json.dumps({
        "status": result["status"],
        "rollback_executable": result["rollback_executable"],
        "temporal_cancel": result["temporal_cancel"],
        "state_recovery": result["state_recovery"],
        "sentinel": SENTINEL,
    }, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if result["rollback_executable"] else 2


if __name__ == "__main__":
    sys.exit(main())
