from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _local_writer_entry(*, wave_id: str, task_id: str) -> dict[str, Any]:
    return {
        "entry_id": f"{wave_id}:local-worker-dispatch-ledger-writer",
        "wave_id": wave_id,
        "task_id": task_id,
        "lane_id": "local-worker-dispatch-ledger-writer",
        "agent_id": "codex_s_current_worker",
        "provider": "codex_s.worker_dispatch_ledger",
        "mode": "worker",
        "dispatch_time": _now_iso(),
        "poll_status": "succeeded",
        "artifact_refs": [],
        "fan_in_decision": "accepted_for_ledger_evidence_only",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_worker_dispatch_ledger(
    *,
    repo_root: str | Path,
    runtime_root: str | Path,
    wave_id: str,
    task_id: str,
    extra_entries: list[dict[str, Any]] | None = None,
    poll_scope_lane_id_prefixes: tuple[str, ...] = (),
    runtime_entrypoint_invocation: dict[str, Any] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    entries = [_local_writer_entry(wave_id=wave_id, task_id=task_id)]
    entries.extend(dict(entry) for entry in (extra_entries or []) if isinstance(entry, dict))
    if poll_scope_lane_id_prefixes:
        scoped = [
            entry
            for entry in entries
            if any(str(entry.get("lane_id") or "").startswith(prefix) for prefix in poll_scope_lane_id_prefixes)
        ]
    else:
        scoped = entries
    poll_entries = [entry for entry in scoped if str(entry.get("poll_status") or "") in {"succeeded", "failed", "blocked", "cancelled"}]
    succeeded_entries = [entry for entry in poll_entries if entry.get("poll_status") == "succeeded"]
    payload = {
        "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
        "status": "worker_dispatch_ledger_poll_ready",
        "repo_root": str(repo_root),
        "runtime_root": str(runtime_root),
        "wave_id": wave_id,
        "task_id": task_id,
        "source_kind": "worker_dispatch_ledger_poll",
        "poll_source": "worker_dispatch_ledger_poll",
        "dispatch_entries": scoped,
        "poll_entries": poll_entries,
        "succeeded_entries": succeeded_entries,
        "succeeded_entry_ids": [str(entry.get("entry_id") or "") for entry in succeeded_entries],
        "succeeded_count": len(succeeded_entries),
        "driver_synthetic_succeeded_allowed": False,
        "runtime_entrypoint_invocation": runtime_entrypoint_invocation or {},
        "poll_result_summary": {
            "entry_count": len(poll_entries),
            "succeeded_count": len(succeeded_entries),
            "polling_or_non_success_count": len(poll_entries) - len(succeeded_entries),
            "source_kind": "worker_dispatch_ledger_poll",
        },
        "output_paths": {
            "runtime_latest": str(Path(runtime_root) / "state" / "worker_dispatch_ledger" / "latest.json"),
            "poll_latest": str(Path(runtime_root) / "state" / "worker_dispatch_ledger" / "poll_latest.json"),
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    if write:
        _write_json(Path(payload["output_paths"]["runtime_latest"]), payload)
        _write_json(Path(payload["output_paths"]["poll_latest"]), payload)
    return payload
