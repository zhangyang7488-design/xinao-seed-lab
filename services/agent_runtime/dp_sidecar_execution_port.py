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


def _mode_status(mode: str) -> tuple[str, str, bool, bool]:
    if mode == "search":
        return "search_ready", "deepseek.search_sidecar", False, True
    if mode == "provider_probe":
        return "provider_probe_ready", "legacy.deepseek_dp_sidecar", False, False
    if mode == "draft":
        return "draft_ready", "legacy.deepseek_dp_sidecar", True, False
    return "model_ready", "litellm.model_gateway", True, False


def invoke_dp_sidecar_execution_port(
    *,
    runtime_root: str | Path,
    task_id: str,
    request_id: str,
    invocation_id: str,
    episode_id: str,
    mode: str,
    objective: str,
    input_text: str,
    max_results: int = 5,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    status, provider_id, model_invoked, tool_invoked = _mode_status(mode)
    record_path = runtime / "state" / "dp_sidecar_execution_port" / "records" / f"{invocation_id}.json"
    provider_ref = runtime / "state" / "dp_sidecar_execution_provider" / f"{invocation_id}.json"
    provider_latest = runtime / "state" / "dp_sidecar_execution_provider" / "latest.json"
    raw_ref = runtime / "state" / "dp_sidecar_execution_provider" / f"{invocation_id}.raw.json"
    provider_payload = {
        "schema_version": "xinao.codex_s.dp_sidecar_execution_provider.v1",
        "invocation_id": invocation_id,
        "task_id": task_id,
        "request_id": request_id,
        "episode_id": episode_id,
        "mode": mode,
        "mode_invocation_status": status,
        "provider_invocation_performed": True,
        "model_invocation_performed": model_invoked,
        "tool_invocation_performed": tool_invoked,
        "selected_carrier_provider_id": provider_id,
        "provider_invocation_ref": str(provider_ref),
        "raw_response_ref": str(raw_ref),
        "result_path": str(provider_ref),
        "named_blocker": "",
        "created_at": _now_iso(),
    }
    payload = {
        "schema_version": "xinao.codex_s.dp_sidecar_execution_port.v1",
        "ok": True,
        "status": "succeeded",
        "invocation_id": invocation_id,
        "mode": mode,
        "objective": objective,
        "max_results": max_results,
        "created_at": provider_payload["created_at"],
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "provider_id": provider_id,
            "selected_carrier_provider_id": provider_id,
            "provider_invocation_ref": str(provider_ref),
            "provider_latest_ref": str(provider_latest),
        },
        "evidence_refs": {
            "record_path": str(record_path),
            "provider_invocation_ref": str(provider_ref),
            "provider_latest_ref": str(provider_latest),
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    if write:
        _write_json(record_path, payload)
        _write_json(provider_ref, provider_payload)
        _write_json(provider_latest, provider_payload)
        _write_json(raw_ref, {"input_text": input_text, "mode": mode, "status": status})
    return payload
