"""Thin Temporal seam to the existing durable ACPX -> Grok worker transport.

Temporal owns scheduling and retries.  AgentOperationStore owns the external
turn identity/evidence.  This module deliberately owns neither a pool nor a
process launcher.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio import activity

from xinao_coordination.agent_controller import AgentOperationController
from xinao_coordination.agent_operations import TERMINAL_STATES, AgentOperationStore
from xinao_coordination.database import default_db_path

POLICY_ID = "xinao.grok.temporal_acpx.v1"
PROVIDER_ID = "grok_acpx_headless"
DEFAULT_MODEL = "grok-4.5"
DEFAULT_CWD = Path(r"E:\XINAO_RESEARCH_WORKSPACES\S")
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_EVIDENCE_ROOT = (
    DEFAULT_RUNTIME / "state" / "dual_brain_coordination" / "grok_temporal"
)
PROVIDER_CAPACITY_CEILING = 32
FANIN_SENTINEL = "XINAO_GROK_TEMPORAL_FANIN_V1"
BACKGROUND_ALLOWED_TOOLS = frozenset(
    {
        "grep",
        "list_dir",
        "read_file",
        "search_tool",
        "use_tool",
        "web_fetch",
        "web_search",
    }
)
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(value: object, *, limit: int = 100) -> str:
    cleaned = _SAFE_RE.sub("_", str(value or "").strip())
    return (cleaned or "unknown")[:limit]


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def validate_ready_frontier(
    raw: object,
    *,
    serial_reason: str = "",
) -> list[dict[str, Any]]:
    """Validate caller-derived ready work; never invent a standing lane count."""

    if not isinstance(raw, list) or not raw:
        return []
    if len(raw) > PROVIDER_CAPACITY_CEILING:
        raise ValueError(
            f"ready frontier exceeds provider capacity ceiling {PROVIDER_CAPACITY_CEILING}"
        )
    lanes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"ready frontier lane {index} must be an object")
        lane_id = str(item.get("lane_id") or f"lane-{index}").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not lane_id or lane_id in seen or not prompt:
            raise ValueError(f"invalid/duplicate ready frontier lane at index {index}")
        seen.add(lane_id)
        lane = {
                **item,
                "lane_id": lane_id,
                "prompt": prompt,
                "mode": str(item.get("mode") or "implementation").strip(),
                "model": str(item.get("model") or DEFAULT_MODEL).strip(),
                "cwd": str(Path(str(item.get("cwd") or DEFAULT_CWD)).resolve()),
                "write": bool(item.get("write", False)),
                "max_turns": max(1, min(40, int(item.get("max_turns") or 16))),
                "deadline_seconds": max(
                    60, min(7_200, int(item.get("deadline_seconds") or 1_800))
                ),
            }
        lanes.append(lane)
    if len(lanes) == 1 and not serial_reason.strip():
        raise ValueError("a one-lane ready frontier requires a concrete serial_reason")
    return lanes


def _operation_id(workflow_id: str, lane_id: str) -> str:
    digest = hashlib.sha256(f"{workflow_id}\n{lane_id}".encode()).hexdigest()[:32]
    return f"op_grok_temporal_{digest}"


def resolve_background_allowed_tools(raw: object) -> list[str]:
    """Return the fixed background surface; callers may only request a subset."""

    if raw is None:
        return sorted(BACKGROUND_ALLOWED_TOOLS)
    if not isinstance(raw, list):
        raise TypeError("allowed_tools must be a list when provided")
    requested = {str(item).strip() for item in raw if str(item).strip()}
    unsafe = sorted(requested - BACKGROUND_ALLOWED_TOOLS)
    if unsafe:
        raise ValueError(f"background Grok lane requested tools outside fixed surface: {unsafe}")
    return sorted(requested)


def is_completed_grok_lane(item: object) -> bool:
    """Accept only durable, attributable Grok lane results."""

    if not isinstance(item, dict):
        return False
    return (
        item.get("ok") is True
        and str(item.get("provider_id") or "") == PROVIDER_ID
        and bool(str(item.get("lane_id") or "").strip())
        and str(item.get("operation_state") or "") == "completed"
        and bool(str(item.get("operation_id") or "").strip())
        and str(item.get("model") or "").lower().startswith("grok")
        and bool(str(item.get("result_text") or "").strip())
    )


async def _request_cancel(store: AgentOperationStore, operation_id: str, reason: str) -> None:
    await asyncio.to_thread(
        store.request_cancel,
        operation_id,
        actor="codex",
        reason=reason,
    )


@activity.defn(name="xinao.grok.execute_acpx_lane")
async def execute_grok_acpx_lane(payload: dict[str, Any]) -> dict[str, Any]:
    """Submit/reattach one ACPX operation and heartbeat until its durable terminal."""

    workflow_id = str(payload.get("workflow_id") or "").strip()
    lane = validate_ready_frontier(
        [payload], serial_reason=str(payload.get("serial_reason") or "activity_lane")
    )[0]
    lane_id = lane["lane_id"]
    if not workflow_id:
        raise ValueError("workflow_id is required")
    db_path = Path(str(payload.get("db_path") or default_db_path())).resolve()
    operation_id = _operation_id(workflow_id, lane_id)
    session_name = f"temporal-{_safe(workflow_id, limit=56)}-{_safe(lane_id, limit=32)}"
    metadata: dict[str, object] = {
        "temporal_workflow_id": workflow_id,
        "temporal_lane_id": lane_id,
        "mode": lane["mode"],
        "model": lane["model"],
        "max_turns": lane["max_turns"],
        # Grok ACP currently reports MCP reads through the generic UseTool
        # permission kind, so approve-reads rejects legitimate research turns.
        # The task boundary and post-run evidence carry read/write intent.
        "permission_mode": "approve-all",
        "non_interactive_permissions": "fail",
        "no_progress_seconds": min(900, lane["deadline_seconds"]),
    }
    metadata["allowed_tools"] = resolve_background_allowed_tools(lane.get("allowed_tools"))
    controller = AgentOperationController(db_path)
    store = controller.store
    try:
        submitted = await asyncio.to_thread(
            controller.submit_and_start,
            actor="codex",
            prompt=lane["prompt"],
            session_name=session_name,
            cwd=lane["cwd"],
            deadline_seconds=lane["deadline_seconds"],
            max_attempts=1 if lane["write"] else 2,
            replay_safe=not lane["write"],
            idempotency_key=f"temporal-grok:{workflow_id}:{lane_id}",
            metadata=metadata,
            operation_id=operation_id,
        )
        operation = submitted.get("operation")
        if not isinstance(operation, dict):
            raise RuntimeError("ACPX operation submission returned no operation")
        operation_id = str(operation["operation_id"])
        while True:
            view = await asyncio.to_thread(store.get, operation_id)
            current = view["operation"]
            assert isinstance(current, dict)
            state = str(current.get("state") or "")
            activity.heartbeat(
                {"operation_id": operation_id, "lane_id": lane_id, "state": state}
            )
            if state in TERMINAL_STATES or state == "uncertain":
                return {
                    "ok": state == "completed" and bool(current.get("result_text")),
                    "policy_id": POLICY_ID,
                    "provider_id": PROVIDER_ID,
                    "workflow_id": workflow_id,
                    "lane_id": lane_id,
                    "mode": lane["mode"],
                    "model": lane["model"],
                    "operation_id": operation_id,
                    "operation_state": state,
                    "result_text": str(current.get("result_text") or ""),
                    "stop_reason": str(current.get("stop_reason") or ""),
                    "artifacts": view.get("artifacts") or [],
                    "replayed": bool(submitted.get("replayed")),
                }
            if activity.is_cancelled():
                await _request_cancel(store, operation_id, "Temporal activity cancelled")
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        await _request_cancel(store, operation_id, "Temporal activity cancelled")
        raise


def _materialize_fanin(payload: dict[str, Any]) -> dict[str, Any]:
    workflow_id = str(payload.get("workflow_id") or "").strip()
    base_path = Path(str(payload.get("base_intake_path") or "")).resolve()
    base_path.relative_to(DEFAULT_RUNTIME.resolve())
    results = [item for item in payload.get("lane_results", []) if isinstance(item, dict)]
    successful = [item for item in results if is_completed_grok_lane(item)]
    require_full_frontier = payload.get("require_full_frontier") is True
    if not workflow_id or not successful:
        raise ValueError("workflow_id and at least one successful Grok lane are required")
    if require_full_frontier and len(successful) != len(results):
        raise ValueError(
            "all Grok lanes must be completed with attributable non-empty results"
        )
    models = sorted({str(item["model"]) for item in successful})
    model = models[0] if len(models) == 1 else "grok-mixed"
    root = DEFAULT_EVIDENCE_ROOT / _safe(workflow_id) / "fanin"
    intake_path = root / "grok_fanin_input.md"
    manifest_path = root / "manifest.json"
    sections = [
        f"<!-- {FANIN_SENTINEL} -->",
        "<!-- grok_manifest_path="
        + "/evidence/"
        + manifest_path.relative_to(DEFAULT_RUNTIME).as_posix()
        + " -->",
        base_path.read_text(encoding="utf-8", errors="replace").rstrip(),
        "",
        "# Grok ready-frontier fan-in",
    ]
    for item in successful:
        sections.extend(
            [
                "",
                f"## {item.get('lane_id')} ({item.get('mode')})",
                "",
                str(item.get("result_text") or "").rstrip(),
            ]
        )
    root.mkdir(parents=True, exist_ok=True)
    intake_raw = ("\n".join(sections).rstrip() + "\n").encode("utf-8")
    intake_path.write_bytes(intake_raw)
    manifest = {
        "schema_version": "xinao.grok.temporal_acpx_fanin.v1",
        "sentinel": FANIN_SENTINEL,
        "policy_id": POLICY_ID,
        "provider_id": PROVIDER_ID,
        "model": model,
        "models": models,
        "workflow_id": workflow_id,
        "ok": len(successful) == len(results),
        "ready_width": len(results),
        "succeeded": len(successful),
        "failed": len(results) - len(successful),
        "serial_reason": str(payload.get("serial_reason") or ""),
        "lanes": [
            {
                "lane_id": item.get("lane_id"),
                "mode": item.get("mode"),
                "model": item.get("model"),
                "operation_id": item.get("operation_id"),
                "operation_state": item.get("operation_state"),
                "artifacts": item.get("artifacts") or [],
            }
            for item in results
        ],
        "base_intake_path": str(base_path),
        "intake_path": str(intake_path),
        "intake_sha256": _hash_bytes(intake_raw),
        "generated_at": datetime.now(UTC).isoformat(),
        "completion_claim_allowed": False,
    }
    _write_json_atomic(manifest_path, manifest)
    return {
        "ok": True,
        "provider_id": PROVIDER_ID,
        "model": model,
        "models": models,
        "manifest_path": str(manifest_path),
        "lane_count": len(results),
        "ready_width": len(results),
        "succeeded": len(successful),
        "failed": len(results) - len(successful),
        "intake": {
            "ok": True,
            "artifact_path": str(intake_path),
            "container_path": (
                "/evidence/" + intake_path.relative_to(DEFAULT_RUNTIME).as_posix()
            ),
            "sha256": _hash_bytes(intake_raw),
            "size_bytes": len(intake_raw),
        },
    }


@activity.defn(name="xinao.grok.materialize_acpx_fanin")
async def materialize_grok_acpx_fanin(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_materialize_fanin, payload)


GROK_TEMPORAL_ACTIVITIES = (execute_grok_acpx_lane, materialize_grok_acpx_fanin)

__all__ = [
    "BACKGROUND_ALLOWED_TOOLS",
    "DEFAULT_MODEL",
    "FANIN_SENTINEL",
    "GROK_TEMPORAL_ACTIVITIES",
    "POLICY_ID",
    "PROVIDER_CAPACITY_CEILING",
    "PROVIDER_ID",
    "execute_grok_acpx_lane",
    "is_completed_grok_lane",
    "materialize_grok_acpx_fanin",
    "resolve_background_allowed_tools",
    "validate_ready_frontier",
]
