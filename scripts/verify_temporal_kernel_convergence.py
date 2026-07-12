"""Verify one live promoted Temporal run converged with the SQLite kernel.

This is deliberately a read-only verifier until the final atomic evidence write.
It binds the Temporal terminal, kernel task/attempt/event state, and the exact
D-drive artifact bytes instead of trusting a PASS label from either side.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio.client import Client

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
for candidate in (str(REPO), str(SRC)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from xinao_coordination.service import CoordinationService  # noqa: E402

DEFAULT_DB = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3"
)
DEFAULT_OUTPUT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\C08_temporal_kernel_convergence_latest.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(raw, encoding="utf-8")
    os.replace(temporary, path)


def evaluate_convergence(
    *,
    workflow_status: str,
    workflow_result: dict[str, Any],
    task_view: dict[str, Any],
    events: list[dict[str, Any]],
    artifact_probe: dict[str, Any],
) -> dict[str, Any]:
    task = task_view.get("task") if isinstance(task_view.get("task"), dict) else {}
    attempts = [item for item in task_view.get("attempts", []) if isinstance(item, dict)]
    artifacts = [item for item in task_view.get("artifacts", []) if isinstance(item, dict)]
    finalize = (
        workflow_result.get("finalize")
        if isinstance(workflow_result.get("finalize"), dict)
        else {}
    )
    kernel = finalize.get("kernel") if isinstance(finalize.get("kernel"), dict) else {}
    steps = [item for item in workflow_result.get("step_evidence", []) if isinstance(item, dict)]
    children = [
        item for item in workflow_result.get("langgraph_children", []) if isinstance(item, dict)
    ]
    step_artifact = (
        steps[0].get("artifact")
        if steps and isinstance(steps[0].get("artifact"), dict)
        else {}
    )
    db_artifact = artifacts[0] if len(artifacts) == 1 else {}
    completed_events = [item for item in events if item.get("event_type") == "TaskCompleted"]
    started_events = [
        item for item in events if item.get("event_type") == "TemporalWorkflowStarted"
    ]
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}

    expected_sha = str(step_artifact.get("sha256") or "").lower()
    expected_size = int(step_artifact.get("size_bytes") or 0)
    actual_sha = str(artifact_probe.get("sha256") or "").lower()
    actual_size = int(artifact_probe.get("size_bytes") or 0)
    checks = {
        "workflow_completed": workflow_status.endswith("COMPLETED"),
        "workflow_result_ok": workflow_result.get("ok") is True,
        "workflow_terminal_completed": workflow_result.get("terminal_status") == "completed",
        "kernel_hook_required": kernel.get("required") is True,
        "kernel_hook_ok": kernel.get("ok") is True,
        "kernel_hook_completed": kernel.get("state") == "completed",
        "task_completed": task.get("state") == "completed",
        "task_has_completed_at": int(task.get("completed_at_ms") or 0) > 0,
        "task_lease_cleared": not task.get("lease_owner") and not task.get("lease_token"),
        "one_completed_attempt": len(attempts) == 1 and attempts[0].get("state") == "completed",
        "one_temporal_started_event": len(started_events) == 1,
        "temporal_started_event_by_codex": len(started_events) == 1
        and started_events[0].get("actor") == "codex",
        "one_task_completed_event": len(completed_events) == 1,
        "task_temporal_mode_live": metadata.get("temporal_mode") == "live",
        "task_temporal_started_by_codex": metadata.get("temporal_started_by") == "codex",
        "task_workflow_identity_matches": metadata.get("temporal_workflow_id")
        == finalize.get("workflow_id"),
        "task_run_id_recorded": bool(str(metadata.get("temporal_run_id") or "")),
        "one_registered_artifact": len(artifacts) == 1,
        "step_artifact_registered": (
            step_artifact.get("sqlite_hook", {}).get("ok") is True
            if isinstance(step_artifact.get("sqlite_hook"), dict)
            else False
        ),
        "artifact_exists": artifact_probe.get("exists") is True,
        "artifact_hash_nonempty": bool(expected_sha),
        "artifact_hash_four_way_equal": bool(expected_sha)
        and expected_sha == actual_sha == str(db_artifact.get("sha256") or "").lower(),
        "artifact_size_four_way_equal": expected_size > 0
        and expected_size == actual_size == int(db_artifact.get("size_bytes") or 0),
        "langgraph_child_passed": len(children) == 1 and children[0].get("passed") is True,
        "langgraph_child_no_failed_checks": len(children) == 1
        and not (children[0].get("failed_checks") or []),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "ok": not failed,
        "verdict": "PASS" if not failed else "FAIL",
        "live_welded": not failed,
        "checks": checks,
        "failed_checks": failed,
        "workflow_status": workflow_status,
        "task_state": task.get("state"),
        "attempt_states": [item.get("state") for item in attempts],
        "event_types": [item.get("event_type") for item in events],
        "event_summaries": [
            {
                "event_type": item.get("event_type"),
                "actor": item.get("actor"),
                "idempotency_key": item.get("idempotency_key"),
            }
            for item in events
        ],
        "kernel_identity": {
            "temporal_mode": metadata.get("temporal_mode"),
            "temporal_started_by": metadata.get("temporal_started_by"),
            "temporal_workflow_id": metadata.get("temporal_workflow_id"),
            "temporal_run_id": metadata.get("temporal_run_id"),
            "kernel_lease_token_present": bool(metadata.get("temporal_kernel_lease_token")),
        },
        "artifact": {
            "path": artifact_probe.get("path"),
            "sha256": actual_sha,
            "size_bytes": actual_size,
            "db_artifact_id": db_artifact.get("artifact_id"),
        },
    }


async def _temporal_snapshot(
    *, address: str, namespace: str, workflow_id: str, run_id: str
) -> tuple[str, dict[str, Any]]:
    client = await Client.connect(address, namespace=namespace)
    handle = client.get_workflow_handle(workflow_id, run_id=run_id)
    description = await handle.describe()
    result = await handle.result()
    if not isinstance(result, dict):
        raise TypeError("Temporal workflow result must be an object")
    status = getattr(description.status, "name", None) or str(description.status)
    return str(status), result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    workflow_status, workflow_result = asyncio.run(
        _temporal_snapshot(
            address=args.address,
            namespace=args.namespace,
            workflow_id=args.workflow_id,
            run_id=args.run_id,
        )
    )
    service = CoordinationService(args.db)
    task_view = service.get_task(args.task_id)
    event_view = service.events(stream_type="task", stream_id=args.task_id, limit=200)
    events = [item for item in event_view.get("events", []) if isinstance(item, dict)]
    steps = [
        item for item in workflow_result.get("step_evidence", []) if isinstance(item, dict)
    ]
    step_artifact = (
        steps[0].get("artifact")
        if steps and isinstance(steps[0].get("artifact"), dict)
        else {}
    )
    artifact_path = Path(str(step_artifact.get("artifact_path") or ""))
    artifact_probe = {
        "path": str(artifact_path),
        "exists": artifact_path.is_file(),
        "sha256": _sha256(artifact_path) if artifact_path.is_file() else "",
        "size_bytes": artifact_path.stat().st_size if artifact_path.is_file() else 0,
    }
    evaluated = evaluate_convergence(
        workflow_status=workflow_status,
        workflow_result=workflow_result,
        task_view=task_view,
        events=events,
        artifact_probe=artifact_probe,
    )
    evidence = {
        "schema_version": "xinao.temporal_kernel_convergence.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "completion_claim_allowed": evaluated["ok"],
        "task_id": args.task_id,
        "workflow_id": args.workflow_id,
        "run_id": args.run_id,
        "address": args.address,
        "namespace": args.namespace,
        "db_path": str(args.db.resolve()),
        "source_hashes": {
            str(path.relative_to(REPO)): _sha256(path)
            for path in (
                REPO / "src" / "xinao_coordination" / "service.py",
                REPO / "src" / "xinao_coordination" / "temporal" / "activities.py",
                REPO / "src" / "xinao_coordination" / "temporal" / "workflow.py",
                REPO / "tests" / "test_t9_temporal_promoted_adapter.py",
                REPO / "scripts" / "verify_temporal_kernel_convergence.py",
            )
        },
        **evaluated,
    }
    _write_json_atomic(args.output, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
