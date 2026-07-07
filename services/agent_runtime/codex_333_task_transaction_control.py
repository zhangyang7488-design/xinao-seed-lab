from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import temporal_codex_task_workflow as temporal_workflow

SCHEMA_VERSION = "xinao.codex_s.333_task_transaction_control.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_333_TASK_TRANSACTION_CONTROL_READY"
TASK_ID = "codex_333_task_transaction_control_20260706"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TEMPORAL_ADDRESS = "127.0.0.1:7233"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str, *, limit: int = 96) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value)).strip("._")
    cleaned = cleaned or "default"
    if len(cleaned) <= limit:
        return cleaned
    digest = hashlib.sha256(str(value).encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{cleaned[: limit - 13]}-{digest}"


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def replace_path_with_retry(tmp: Path, path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(25):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.04 * (attempt + 1))
    if last_error is not None:
        raise last_error


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


def output_paths(runtime: Path, control_id: str) -> dict[str, Path]:
    root = runtime / "state" / "codex_333_task_transaction_control"
    readback_root = runtime / "readback" / "zh"
    return {
        "latest": root / "latest.json",
        "record": root / "records" / f"{safe_stem(control_id)}.json",
        "readback": readback_root
        / f"codex_333_task_transaction_control_{safe_stem(control_id)}.md",
    }


def current_333_index(runtime: Path) -> dict[str, Any]:
    return read_json(runtime / "state" / "current_333_run_index" / "latest.json")


def current_workflow_ref(runtime: Path) -> dict[str, Any]:
    index = current_333_index(runtime)
    temporal = index.get("temporal") if isinstance(index.get("temporal"), dict) else {}
    selected_workflow = (
        temporal.get("selected_workflow")
        if isinstance(temporal.get("selected_workflow"), dict)
        else {}
    )
    liveness = (
        index.get("control_plane_liveness")
        if isinstance(index.get("control_plane_liveness"), dict)
        else {}
    )
    workflow_id = str(index.get("workflow_id") or temporal.get("workflow_id") or "")
    workflow_run_id = str(index.get("workflow_run_id") or temporal.get("workflow_run_id") or "")
    temporal_port_open = (
        temporal.get("port_open") is True
        or temporal.get("server_bound_visibility_list") is True
        or liveness.get("temporal_server_port_open") is True
    )
    return {
        "current_333_run_index_ref": str(
            runtime / "state" / "current_333_run_index" / "latest.json"
        ),
        "current_333_run_index_exists": bool(index),
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "temporal_address": str(temporal.get("address") or DEFAULT_TEMPORAL_ADDRESS),
        "temporal_port_open": temporal_port_open,
        "workflow_status": str(
            temporal.get("status")
            or selected_workflow.get("status")
            or index.get("current_state")
            or ""
        ),
        "task_queue": str(temporal.get("task_queue") or "xinao-codex-task-default"),
        "pending_activity_count": int(temporal.get("pending_activity_count") or 0),
        "not_completion_boundary": True,
    }


def signal_payload_for_control(
    *,
    routing_verb: str,
    assignment_dag_node_id: str = "",
    wave_id: str = "",
    reason: str = "",
    priority: int = 0,
    control_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "routing_verb": routing_verb,
        "control_id": control_id,
        "reason": reason,
        "priority": priority,
    }
    if assignment_dag_node_id:
        payload["assignment_dag_node_id"] = assignment_dag_node_id
    if wave_id:
        payload["wave_id"] = wave_id
    return temporal_workflow.normalize_task_control_signal(payload)


async def _send_temporal_signal(
    *,
    address: str,
    workflow_id: str,
    workflow_run_id: str,
    signal_payload: dict[str, Any],
) -> dict[str, Any]:
    from temporalio.client import Client

    client = await Client.connect(address)
    # The default 333 mainline frequently Continue-As-New rolls run_id. Task-control
    # signals target the current open execution by stable workflow_id to avoid
    # racing a run_id that just closed.
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("task_control", signal_payload)
    return {
        "status": "temporal_task_control_signal_sent",
        "workflow_id": workflow_id,
        "requested_workflow_run_id": workflow_run_id,
        "signal_name": "task_control",
        "live_temporal_signal": True,
    }


def send_temporal_signal(
    *,
    address: str,
    workflow_id: str,
    workflow_run_id: str,
    signal_payload: dict[str, Any],
    live_temporal_signal: bool,
) -> dict[str, Any]:
    if not live_temporal_signal:
        return {
            "status": "temporal_task_control_signal_not_sent_dry_run",
            "signal_name": "task_control",
            "live_temporal_signal": False,
            "reason": "live signal requires --live-temporal-signal",
        }
    if not workflow_id:
        return {
            "status": "temporal_task_control_signal_blocked",
            "signal_name": "task_control",
            "live_temporal_signal": True,
            "named_blocker": "CURRENT_333_WORKFLOW_ID_MISSING",
        }
    try:
        return asyncio.run(
            _send_temporal_signal(
                address=address,
                workflow_id=workflow_id,
                workflow_run_id=workflow_run_id,
                signal_payload=signal_payload,
            )
        )
    except Exception as exc:
        return {
            "status": "temporal_task_control_signal_failed",
            "signal_name": "task_control",
            "live_temporal_signal": True,
            "named_blocker": f"TEMPORAL_TASK_CONTROL_SIGNAL_FAILED:{exc.__class__.__name__}",
        }


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    routing_verb: str = "return_to_mainline",
    assignment_dag_node_id: str = "",
    wave_id: str = "",
    reason: str = "",
    priority: int = 0,
    control_id: str = "",
    live_temporal_signal: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    control_id = (
        control_id
        or f"{safe_stem(routing_verb)}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S')}"
    )
    paths = output_paths(runtime, control_id)
    workflow_ref = current_workflow_ref(runtime)
    signal_payload = signal_payload_for_control(
        routing_verb=routing_verb,
        assignment_dag_node_id=assignment_dag_node_id,
        wave_id=wave_id,
        reason=reason,
        priority=priority,
        control_id=control_id,
    )
    live_signal = send_temporal_signal(
        address=workflow_ref["temporal_address"],
        workflow_id=workflow_ref["workflow_id"],
        workflow_run_id=workflow_ref["workflow_run_id"],
        signal_payload=signal_payload,
        live_temporal_signal=live_temporal_signal,
    )
    supported = sorted(temporal_workflow.TASK_CONTROL_ROUTING_VERBS)
    checks = {
        "current_333_run_index_available": workflow_ref["current_333_run_index_exists"],
        "workflow_id_available": bool(workflow_ref["workflow_id"]),
        "temporal_task_control_signal_supported": hasattr(
            temporal_workflow.TemporalCodexTaskWorkflow,
            "task_control",
        ),
        "routing_verb_supported": signal_payload.get("valid_routing_verb") is True,
        "pause_cancel_are_after_current_wave": signal_payload.get("routing_verb")
        not in {"pause_after_current_wave", "cancel_after_current_wave"}
        or signal_payload.get("continue_same_task_signal") == {},
        "insert_and_return_use_continue_same_task_signal": signal_payload.get("routing_verb")
        not in {"insert_front", "return_to_mainline"}
        or bool(signal_payload.get("continue_same_task_signal")),
        "dry_run_default_for_destructive_signal": live_temporal_signal is False
        or live_signal.get("status") == "temporal_task_control_signal_sent",
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "status": "codex_333_task_transaction_control_ready"
        if all(checks.values())
        else "codex_333_task_transaction_control_blocked",
        "control_id": control_id,
        "repo_root": str(repo),
        "routing_verb": signal_payload.get("routing_verb"),
        "supported_routing_verbs": supported,
        "backend_transaction_required": True,
        "default_mainline": "RootIntentLoop / S Default Dynamic Loop",
        "temporal_signal_name": "task_control",
        "existing_temporal_signal_compat": [
            "continue_same_task",
            "drain_after_current_wave",
        ],
        "control_semantics": {
            "insert_front": "prepend urgent same-task work, then prior queued work remains",
            "pause_after_current_wave": "drain after the current wave; no fake completion",
            "cancel_after_current_wave": "cancel/drain after current wave; records user-requested cancel blocker",
            "resume": "clear drain request and allow queued continuation",
            "return_to_mainline": "enqueue assignment_dag/mainline continuation",
        },
        "workflow_ref": workflow_ref,
        "signal_payload": signal_payload,
        "live_signal": live_signal,
        "output_paths": {key: str(value) for key, value in paths.items()},
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    workflow_ref = (
        payload.get("workflow_ref") if isinstance(payload.get("workflow_ref"), dict) else {}
    )
    return "\n".join(
        [
            "# 333 task transaction control",
            "",
            SENTINEL,
            "",
            f"- status: `{payload.get('status')}`",
            f"- routing_verb: `{payload.get('routing_verb')}`",
            f"- workflow_id: `{workflow_ref.get('workflow_id')}`",
            f"- workflow_run_id: `{workflow_ref.get('workflow_run_id')}`",
            f"- live_signal: `{payload.get('live_signal', {}).get('status')}`",
            f"- validation_passed: {validation.get('passed')}",
            "- semantics: pause/cancel drain after current wave; insert returns to queued mainline; resume clears drain.",
            "- boundary: evidence/control signal only; not user completion.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--routing-verb", default="return_to_mainline")
    parser.add_argument("--assignment-dag-node-id", default="")
    parser.add_argument("--wave-id", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--priority", type=int, default=0)
    parser.add_argument("--control-id", default="")
    parser.add_argument("--live-temporal-signal", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        routing_verb=args.routing_verb,
        assignment_dag_node_id=args.assignment_dag_node_id,
        wave_id=args.wave_id,
        reason=args.reason,
        priority=args.priority,
        control_id=args.control_id,
        live_temporal_signal=args.live_temporal_signal,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
