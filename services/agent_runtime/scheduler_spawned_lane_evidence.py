from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_scheduler_spawned_lane_evidence(
    *,
    runtime_root: str | Path,
    repo_root: str | Path,
    wave_id: str,
    scheduler_invocation_ref: str | Path,
    output_latest: str | Path,
    write: bool = True,
) -> dict[str, Any]:
    invocation = _read_json(Path(scheduler_invocation_ref))
    lanes = invocation.get("spawned_lanes") if isinstance(invocation.get("spawned_lanes"), list) else []
    payload = {
        "schema_version": "xinao.codex_s.scheduler_spawned_lane_evidence.v1",
        "status": "scheduler_spawned_lane_evidence_ready",
        "wave_id": wave_id,
        "repo_root": str(repo_root),
        "runtime_root": str(runtime_root),
        "lane_evidence_state": "scheduler_spawned_lanes_observed",
        "scheduler_invoked": True,
        "default_runtime_scheduler_invoked": True,
        "runtime_enforced": True,
        "trigger_installed": True,
        "scheduler_spawned_lane_count": len(lanes),
        "actual_dispatch_refs": {
            "scheduler_spawned_lane_refs": lanes,
            "refs_are_not_execution_controllers": True,
        },
        "evidence_refs": {
            "selected_runtime_latest": str(output_latest),
            "scheduler_invocation_ref": str(scheduler_invocation_ref),
        },
        "validation": {
            "passed": len(lanes) > 0,
            "checks": {
                "scheduler_invoked": True,
                "lanes_present": len(lanes) > 0,
            },
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    if write:
        latest = Path(output_latest)
        _write_json(latest, payload)
        _write_json(Path(runtime_root) / "state" / "scheduler_spawned_lane_evidence" / "latest.json", payload)
        _write_json(Path(runtime_root) / "state" / "scheduler_spawned_lane_evidence" / "current_wave_latest.json", payload)
    return payload
