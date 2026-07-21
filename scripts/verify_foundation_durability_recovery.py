#!/usr/bin/env python3
"""Bind a real Temporal Continue-As-New/checkpoint chain to a foundation run."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
CONTINUED = "EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW"
COMPLETED = "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"
FAILED_EVENTS = {
    "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED",
    "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED",
    "EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED",
    "EVENT_TYPE_WORKFLOW_EXECUTION_TIMED_OUT",
    "EVENT_TYPE_WORKFLOW_TASK_FAILED",
}
WINDOWLESS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _proof_evidence(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "sha256": None,
            "checkpoint_ok": False,
            "continue_as_new_wired": False,
            "episode_cache_ref_present": False,
        }
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key.strip()] = value.strip()
    return {
        "path": str(path),
        "exists": True,
        "sha256": _sha256(path),
        "checkpoint_ok": fields.get("checkpoint_ok", "").casefold() == "true",
        "continue_as_new_wired": (fields.get("continue_as_new_wired", "").casefold() == "true"),
        "episode_cache_ref_present": fields.get("episode_cache_ref", "").casefold()
        not in {"", "none"},
    }


def _proof_path(runtime_root: Path, workflow_id: str) -> Path:
    proof_stem = "".join(
        character if character.isalnum() or character in "-_." else "_" for character in workflow_id
    )[:120]
    return runtime_root / "state" / "integrated_bus_proof" / f"{proof_stem}.txt"


def _temporal_history(workflow_id: str, run_id: str, *, address: str) -> dict[str, Any]:
    command = [
        "temporal",
        "workflow",
        "show",
        "--address",
        address,
        "--namespace",
        "default",
        "--workflow-id",
        workflow_id,
        "--run-id",
        run_id,
        "--output",
        "json",
    ]
    proc = subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        creationflags=WINDOWLESS,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"temporal workflow show failed: {proc.stderr[-500:]}")
    value = json.loads(proc.stdout)
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise ValueError("Temporal history JSON has no events list")
    return value


def _checkpoint_records(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("checkpoint_ok") is True and value.get("checkpoint_thread_id"):
            found.append(value)
        for child in value.values():
            found.extend(_checkpoint_records(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_checkpoint_records(child))
    return found


def _decode_temporal_input(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    payloads = value.get("payloads")
    if not isinstance(payloads, list):
        return []
    decoded: list[Any] = []
    for payload in payloads:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), str):
            continue
        try:
            decoded.append(json.loads(base64.b64decode(payload["data"]).decode("utf-8")))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return decoded


def _continued_record(event: dict[str, Any], *, workflow_id: str) -> dict[str, Any]:
    attributes = event.get("workflowExecutionContinuedAsNewEventAttributes")
    if not isinstance(attributes, dict):
        raise ValueError("Continue-As-New attributes are missing")
    inputs = _decode_temporal_input(attributes.get("input"))
    state = inputs[0] if inputs else None
    if not isinstance(state, dict):
        raise ValueError("Continue-As-New state transfer is missing")
    checkpoints = _checkpoint_records(state.get("episode_cache"))
    matching = [item for item in checkpoints if item.get("checkpoint_thread_id") == workflow_id]
    return {
        "event_id": int(event.get("eventId", 0)),
        "new_run_id": str(attributes.get("newExecutionRunId") or ""),
        "episode_phase": int(state.get("episode_phase", -1)),
        "episode_max_phase": int(state.get("episode_max_phase", -1)),
        "continue_as_new_wired": state.get("continue_as_new_wired") is True,
        "episode_cache_present": isinstance(state.get("episode_cache"), dict),
        "checkpoint_count": len(checkpoints),
        "checkpoint_thread_matches": bool(matching),
        "checkpoint_ids": sorted(
            {str(item.get("checkpoint_id")) for item in matching if item.get("checkpoint_id")}
        ),
    }


def inspect_history_chain(
    *,
    workflow_id: str,
    initial_run_id: str,
    history_loader: Callable[[str, str], dict[str, Any]],
    max_runs: int = 8,
) -> dict[str, Any]:
    """Follow a bounded Temporal run chain and verify carried checkpoint state."""

    current_run_id = initial_run_id
    seen: set[str] = set()
    runs: list[dict[str, Any]] = []
    continuations: list[dict[str, Any]] = []
    failed_event_types: list[str] = []
    final_completed = False
    for _ in range(max_runs):
        if not current_run_id or current_run_id in seen:
            raise ValueError("Temporal run chain is empty or cyclic")
        seen.add(current_run_id)
        history = history_loader(workflow_id, current_run_id)
        events = history.get("events")
        if not isinstance(events, list) or not events:
            raise ValueError("Temporal run history is empty")
        event_types = [str(event.get("eventType")) for event in events if isinstance(event, dict)]
        failed_event_types.extend(item for item in event_types if item in FAILED_EVENTS)
        continued_events = [
            event
            for event in events
            if isinstance(event, dict) and event.get("eventType") == CONTINUED
        ]
        completed_events = [item for item in event_types if item == COMPLETED]
        run_record: dict[str, Any] = {
            "run_id": current_run_id,
            "history_event_count": len(events),
            "max_event_id": max(
                int(event.get("eventId", 0)) for event in events if isinstance(event, dict)
            ),
            "continued_as_new": bool(continued_events),
            "completed": bool(completed_events),
        }
        runs.append(run_record)
        if completed_events:
            if continued_events:
                raise ValueError("one run cannot be both completed and continued-as-new")
            final_completed = True
            break
        if len(continued_events) != 1:
            raise ValueError("non-final run must contain exactly one Continue-As-New event")
        continuation = _continued_record(continued_events[0], workflow_id=workflow_id)
        continuation["source_run_id"] = current_run_id
        continuations.append(continuation)
        current_run_id = str(continuation["new_run_id"])
    else:
        raise ValueError("Temporal run chain exceeded the bounded inspection limit")

    phases = [int(item["episode_phase"]) for item in continuations]
    maximum_phases = [int(item["episode_max_phase"]) for item in continuations]
    phase_progression_ok = (
        bool(phases)
        and bool(maximum_phases)
        and bool(
            phases == list(range(phases[0], phases[0] + len(phases)))
            and len(set(maximum_phases)) == 1
            and all(0 <= phase <= maximum_phases[0] for phase in phases)
        )
    )
    checkpoint_recovery_verified = bool(
        continuations
        and phase_progression_ok
        and all(
            item["continue_as_new_wired"]
            and item["episode_cache_present"]
            and item["checkpoint_thread_matches"]
            and item["checkpoint_ids"]
            for item in continuations
        )
    )
    return {
        "workflow_id": workflow_id,
        "initial_run_id": initial_run_id,
        "final_run_id": runs[-1]["run_id"],
        "run_count": len(runs),
        "history_event_count": sum(int(item["history_event_count"]) for item in runs),
        "initial_history_event_count": runs[0]["history_event_count"],
        "continue_as_new_event_count": len(continuations),
        "continue_as_new_verified": bool(continuations and final_completed),
        "checkpoint_recovery_verified": checkpoint_recovery_verified,
        "phase_progression_ok": phase_progression_ok,
        "final_completed": final_completed,
        "failed_event_types": sorted(set(failed_event_types)),
        "runs": runs,
        "continuations": continuations,
    }


def verify_durability_recovery(
    *,
    operation_id: str,
    workflow_id: str,
    initial_run_id: str,
    output_path: Path,
    runtime_root: Path = DEFAULT_RUNTIME,
    address: str = "127.0.0.1:7233",
) -> dict[str, Any]:
    chain = inspect_history_chain(
        workflow_id=workflow_id,
        initial_run_id=initial_run_id,
        history_loader=lambda wf, run: _temporal_history(wf, run, address=address),
    )
    proof_path = _proof_path(runtime_root, workflow_id)
    proof = _proof_evidence(proof_path)
    checks = {
        "continue_as_new_verified": chain["continue_as_new_verified"] is True,
        "checkpoint_recovery_verified": chain["checkpoint_recovery_verified"] is True,
        "final_completed": chain["final_completed"] is True,
        "no_failed_events": not chain["failed_event_types"],
        "d_disk_proof_exists": proof["exists"] is True,
        "d_disk_proof_checkpoint_bound": proof["checkpoint_ok"] is True,
        "d_disk_proof_continue_as_new_bound": proof["continue_as_new_wired"] is True,
        "d_disk_proof_episode_cache_bound": proof["episode_cache_ref_present"] is True,
    }
    payload = {
        "schema_version": "xinao.foundation_durability_recovery.v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "operation_id": operation_id,
        "ok": all(checks.values()),
        "checks": checks,
        **chain,
        "proof": proof,
    }
    _write_atomic(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--initial-run-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--address", default="127.0.0.1:7233")
    args = parser.parse_args()
    result = verify_durability_recovery(
        operation_id=args.operation_id,
        workflow_id=args.workflow_id,
        initial_run_id=args.initial_run_id,
        output_path=args.out,
        runtime_root=args.runtime_root,
        address=args.address,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
