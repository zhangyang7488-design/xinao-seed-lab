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
MODEL_POLICY_ID = "xinao.grok.provider_model_routing.v1"
DEFAULT_MODEL = "grok-composer-2.5-fast"
LEGACY_DEFAULT_MODEL = "grok-4.5"
ESCALATION_MODEL = "grok-4.5"
ALLOWED_MODELS = frozenset({DEFAULT_MODEL, ESCALATION_MODEL})
DEFAULT_ROUTE_ROLE = "default_background_worker"
ESCALATION_ROUTE_ROLE = "grok_4_5_escalation_worker"
ESCALATION_REASONS = frozenset(
    {
        "acceptance_failure",
        "architecture_review",
        "cross_aggregate_change",
        "explicit_model_override",
        "external_research_required",
        "history_compatibility",
        "runtime_policy_default",
        "schema_failure",
        "security_boundary",
        "task_ambiguity",
        "worker_conflict",
    }
)
DEFAULT_CWD = Path(r"E:\XINAO_RESEARCH_WORKSPACES\S")
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_EVIDENCE_ROOT = DEFAULT_RUNTIME / "state" / "dual_brain_coordination" / "grok_temporal"
DEFAULT_GROK_HOME = Path(r"C:\Users\xx363\.grok-bg-workers")
DEFAULT_ISOLATED_WRITE_ROOT = DEFAULT_RUNTIME / "worktrees"
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


def resolve_provider_model(raw: object, *, default_model: str = DEFAULT_MODEL) -> str:
    """Resolve one explicit Grok-provider model and reject silent provider drift."""

    fallback = str(default_model or DEFAULT_MODEL).strip()
    if fallback not in ALLOWED_MODELS:
        raise ValueError(f"unsupported Grok provider default model: {fallback}")
    model = str(raw or fallback).strip()
    if model not in ALLOWED_MODELS:
        raise ValueError(f"unsupported Grok provider model: {model}")
    return model


def _model_route_fields(item: dict[str, Any], *, default_model: str) -> dict[str, Any]:
    explicit_model = bool(str(item.get("model") or "").strip())
    model = resolve_provider_model(item.get("model"), default_model=default_model)
    reason = str(item.get("escalation_reason") or "").strip()
    if model == ESCALATION_MODEL:
        reason = reason or ("explicit_model_override" if explicit_model else "runtime_policy_default")
        if reason not in ESCALATION_REASONS:
            raise ValueError(f"unsupported Grok 4.5 escalation_reason: {reason}")
    elif reason:
        raise ValueError("escalation_reason is only valid for the Grok 4.5 escalation model")
    return {
        "model": model,
        "requested_model": model,
        "model_policy_id": MODEL_POLICY_ID,
        "model_route_role": (
            ESCALATION_ROUTE_ROLE if model == ESCALATION_MODEL else DEFAULT_ROUTE_ROLE
        ),
        "is_escalated": model == ESCALATION_MODEL,
        "escalation_reason": reason,
    }


def validate_ready_frontier(
    raw: object,
    *,
    serial_reason: str = "",
    default_model: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    """Validate caller-derived ready work; never invent a standing lane count."""

    if not isinstance(raw, list) or not raw:
        return []
    if len(raw) > PROVIDER_CAPACITY_CEILING:
        raise ValueError(f"ready frontier exceeds provider capacity ceiling {PROVIDER_CAPACITY_CEILING}")
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
        cwd = Path(str(item.get("cwd") or DEFAULT_CWD)).resolve()
        write = bool(item.get("write", False))
        if write:
            isolated_root = Path(
                os.environ.get("XINAO_GROK_ISOLATED_WRITE_ROOT", str(DEFAULT_ISOLATED_WRITE_ROOT))
            ).resolve()
            try:
                cwd.relative_to(isolated_root)
            except ValueError as exc:
                raise ValueError(
                    f"write-enabled Grok lane must stay under isolated worktree root: {isolated_root}"
                ) from exc
        lane = {
            **item,
            "lane_id": lane_id,
            "prompt": prompt,
            "mode": str(item.get("mode") or "implementation").strip(),
            **_model_route_fields(item, default_model=default_model),
            "cwd": str(cwd),
            "write": write,
            "max_turns": max(1, min(40, int(item.get("max_turns") or 16))),
            "deadline_seconds": max(60, min(7_200, int(item.get("deadline_seconds") or 1_800))),
        }
        lanes.append(lane)
    if len(lanes) == 1 and not serial_reason.strip():
        raise ValueError("a one-lane ready frontier requires a concrete serial_reason")
    models = {str(lane["model"]) for lane in lanes}
    if len(models) > 1:
        raise ValueError("one Grok ready frontier cannot mix Composer and Grok 4.5 models")
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
        and str(item.get("model") or "") in ALLOWED_MODELS
        and str(item.get("requested_model") or "") == str(item.get("model") or "")
        and str(item.get("observed_model") or "") == str(item.get("requested_model") or "")
        and item.get("model_identity_ok") is True
        and bool(str(item.get("agent_session_id") or "").strip())
        and bool(str(item.get("model_identity_ref") or "").strip())
        and bool(str(item.get("model_identity_sha256") or "").strip())
        and bool(str(item.get("result_text") or "").strip())
    )


def _find_session_summary(grok_home: Path, session_id: str) -> Path | None:
    sessions = grok_home / "sessions"
    if not sessions.is_dir() or not session_id or _safe(session_id) != session_id:
        return None
    matches = [
        project_dir / session_id / "summary.json"
        for project_dir in sessions.iterdir()
        if project_dir.is_dir() and (project_dir / session_id / "summary.json").is_file()
    ]
    return matches[0] if len(matches) == 1 else None


def materialize_model_identity(
    *,
    workflow_id: str,
    lane_id: str,
    operation_id: str,
    operation_request_id: str,
    session_id: str,
    requested_model: str,
    cwd: str,
    grok_home: Path | None = None,
) -> dict[str, Any]:
    """Persist redacted requested-vs-observed Grok session identity evidence."""

    home = Path(
        grok_home or os.environ.get("XINAO_GROK_HOME", str(DEFAULT_GROK_HOME))
    ).resolve()
    summary_path = _find_session_summary(home, session_id)
    summary: dict[str, Any] = {}
    summary_raw = b""
    if summary_path is not None:
        try:
            summary_raw = summary_path.read_bytes()
            loaded = json.loads(summary_raw.decode("utf-8"))
            if isinstance(loaded, dict):
                summary = loaded
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            summary = {}
            summary_raw = b""
    observed_model = str(summary.get("current_model_id") or "").strip()
    session_request_id = str(summary.get("request_id") or "").strip()
    configured_home = str(summary.get("grok_home") or "").strip()
    grok_home_match = bool(configured_home) and configured_home.casefold() == str(home).casefold()
    model_identity_ok = bool(
        summary_path
        and session_id
        and requested_model in ALLOWED_MODELS
        and observed_model == requested_model
        and grok_home_match
    )
    evidence = {
        "schema_version": "xinao.grok.model_identity.v1",
        "policy_id": MODEL_POLICY_ID,
        "provider_id": PROVIDER_ID,
        "workflow_id": workflow_id,
        "lane_id": lane_id,
        "operation_id": operation_id,
        "operation_request_id": operation_request_id,
        "agent_session_id": session_id,
        "session_request_id": session_request_id,
        "requested_model": requested_model,
        "observed_model": observed_model,
        "model_identity_ok": model_identity_ok,
        "grok_home": str(home),
        "grok_home_match": grok_home_match,
        "cwd": cwd,
        "session_summary_path": str(summary_path or ""),
        "session_summary_sha256": _hash_bytes(summary_raw) if summary_raw else "",
        "session_summary_size_bytes": len(summary_raw),
        "raw_conversation_stored": False,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    evidence_path = (
        DEFAULT_EVIDENCE_ROOT
        / _safe(workflow_id)
        / "lanes"
        / _safe(lane_id)
        / "model_identity.json"
    )
    _write_json_atomic(evidence_path, evidence)
    evidence_raw = evidence_path.read_bytes()
    return {
        **evidence,
        "model_identity_ref": str(evidence_path),
        "model_identity_sha256": _hash_bytes(evidence_raw),
        "model_identity_size_bytes": len(evidence_raw),
    }


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
        "model_policy_id": lane["model_policy_id"],
        "model_route_role": lane["model_route_role"],
        "is_escalated": lane["is_escalated"],
        "escalation_reason": lane["escalation_reason"],
        "max_turns": lane["max_turns"],
        # Grok ACP currently reports MCP reads through the generic UseTool
        # permission kind, so approve-reads rejects legitimate research turns.
        # The task boundary and post-run evidence carry read/write intent.
        "permission_mode": "approve-all",
        "non_interactive_permissions": "fail",
        "no_progress_seconds": min(900, lane["deadline_seconds"]),
    }
    correlation_id = str(payload.get("correlation_id") or "").strip()
    parent_operation_id = str(payload.get("parent_operation_id") or "").strip()
    if correlation_id:
        metadata["correlation_id"] = correlation_id
    if parent_operation_id:
        metadata["parent_operation_id"] = parent_operation_id
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
            activity.heartbeat({"operation_id": operation_id, "lane_id": lane_id, "state": state})
            if state in TERMINAL_STATES or state == "uncertain":
                identity: dict[str, Any] = {
                    "requested_model": lane["model"],
                    "observed_model": "",
                    "model_identity_ok": False,
                    "agent_session_id": str(current.get("agent_session_id") or ""),
                    "model_identity_ref": "",
                    "model_identity_sha256": "",
                }
                if state == "completed":
                    # Grok writes summary.json at turn close.  Give the official
                    # session store a bounded flush window, then fail closed.
                    for _ in range(20):
                        identity = await asyncio.to_thread(
                            materialize_model_identity,
                            workflow_id=workflow_id,
                            lane_id=lane_id,
                            operation_id=operation_id,
                            operation_request_id=str(current.get("request_id") or ""),
                            session_id=str(current.get("agent_session_id") or ""),
                            requested_model=lane["model"],
                            cwd=lane["cwd"],
                        )
                        if identity.get("session_summary_path"):
                            break
                        await asyncio.sleep(0.25)
                    identity_path = Path(str(identity.get("model_identity_ref") or ""))
                    if identity_path.is_file():
                        await asyncio.to_thread(
                            store.add_artifact,
                            operation_id,
                            name=identity_path.name,
                            uri=str(identity_path),
                            media_type="application/json",
                            sha256=str(identity["model_identity_sha256"]),
                            size_bytes=int(identity["model_identity_size_bytes"]),
                            metadata={
                                "kind": "grok_model_identity",
                                "requested_model": lane["model"],
                                "observed_model": str(identity.get("observed_model") or ""),
                            },
                        )
                    view = await asyncio.to_thread(store.get, operation_id)
                    current = view["operation"]
                    assert isinstance(current, dict)
                result = {
                    "ok": (
                        state == "completed"
                        and bool(current.get("result_text"))
                        and identity.get("model_identity_ok") is True
                    ),
                    "policy_id": POLICY_ID,
                    "model_policy_id": MODEL_POLICY_ID,
                    "provider_id": PROVIDER_ID,
                    "workflow_id": workflow_id,
                    "lane_id": lane_id,
                    "mode": lane["mode"],
                    "model": lane["model"],
                    "requested_model": lane["model"],
                    "observed_model": str(identity.get("observed_model") or ""),
                    "model_identity_ok": identity.get("model_identity_ok") is True,
                    "agent_session_id": str(identity.get("agent_session_id") or ""),
                    "model_identity_ref": str(identity.get("model_identity_ref") or ""),
                    "model_identity_sha256": str(identity.get("model_identity_sha256") or ""),
                    "model_route_role": lane["model_route_role"],
                    "is_escalated": lane["is_escalated"],
                    "escalation_reason": lane["escalation_reason"],
                    "operation_id": operation_id,
                    "operation_state": state,
                    "result_text": str(current.get("result_text") or ""),
                    "stop_reason": str(current.get("stop_reason") or ""),
                    "artifacts": view.get("artifacts") or [],
                    "replayed": bool(submitted.get("replayed")),
                }
                if correlation_id:
                    result["correlation_id"] = correlation_id
                if parent_operation_id:
                    result["parent_operation_id"] = parent_operation_id
                return result
            if activity.is_cancelled():
                await _request_cancel(store, operation_id, "Temporal activity cancelled")
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        await _request_cancel(store, operation_id, "Temporal activity cancelled")
        raise


def _materialize_fanin(payload: dict[str, Any]) -> dict[str, Any]:
    workflow_id = str(payload.get("workflow_id") or "").strip()
    correlation_id = str(payload.get("correlation_id") or "").strip()
    parent_operation_id = str(payload.get("parent_operation_id") or "").strip()
    base_path = Path(str(payload.get("base_intake_path") or "")).resolve()
    base_path.relative_to(DEFAULT_RUNTIME.resolve())
    results = [item for item in payload.get("lane_results", []) if isinstance(item, dict)]
    successful = [item for item in results if is_completed_grok_lane(item)]
    require_full_frontier = payload.get("require_full_frontier") is True
    if not workflow_id or not successful:
        raise ValueError("workflow_id and at least one successful Grok lane are required")
    if require_full_frontier and len(successful) != len(results):
        raise ValueError("all Grok lanes must be completed with attributable non-empty results")
    models = sorted({str(item["observed_model"]) for item in successful})
    if len(models) != 1 or models[0] not in ALLOWED_MODELS:
        raise ValueError("one Grok fan-in must contain one attested provider model")
    model = models[0]
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
        "schema_version": "xinao.grok.temporal_acpx_fanin.v2",
        "sentinel": FANIN_SENTINEL,
        "policy_id": POLICY_ID,
        "model_policy_id": MODEL_POLICY_ID,
        "provider_id": PROVIDER_ID,
        "model": model,
        "models": models,
        "model_identity_ok": all(item.get("model_identity_ok") is True for item in successful),
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
                "requested_model": item.get("requested_model"),
                "observed_model": item.get("observed_model"),
                "model_identity_ok": item.get("model_identity_ok") is True,
                "agent_session_id": item.get("agent_session_id"),
                "model_identity_ref": item.get("model_identity_ref"),
                "model_identity_sha256": item.get("model_identity_sha256"),
                "model_route_role": item.get("model_route_role"),
                "is_escalated": item.get("is_escalated") is True,
                "escalation_reason": item.get("escalation_reason"),
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
    if correlation_id:
        manifest["correlation_id"] = correlation_id
    if parent_operation_id:
        manifest["parent_operation_id"] = parent_operation_id
    _write_json_atomic(manifest_path, manifest)
    result = {
        "ok": True,
        "provider_id": PROVIDER_ID,
        "model": model,
        "models": models,
        "model_policy_id": MODEL_POLICY_ID,
        "model_identity_ok": all(item.get("model_identity_ok") is True for item in successful),
        "manifest_path": str(manifest_path),
        "lane_count": len(results),
        "ready_width": len(results),
        "succeeded": len(successful),
        "failed": len(results) - len(successful),
        "intake": {
            "ok": True,
            "artifact_path": str(intake_path),
            "container_path": ("/evidence/" + intake_path.relative_to(DEFAULT_RUNTIME).as_posix()),
            "sha256": _hash_bytes(intake_raw),
            "size_bytes": len(intake_raw),
        },
    }
    if correlation_id:
        result["correlation_id"] = correlation_id
    if parent_operation_id:
        result["parent_operation_id"] = parent_operation_id
    return result


@activity.defn(name="xinao.grok.materialize_acpx_fanin")
async def materialize_grok_acpx_fanin(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_materialize_fanin, payload)


GROK_TEMPORAL_ACTIVITIES = (execute_grok_acpx_lane, materialize_grok_acpx_fanin)

__all__ = [
    "ALLOWED_MODELS",
    "BACKGROUND_ALLOWED_TOOLS",
    "DEFAULT_MODEL",
    "DEFAULT_ROUTE_ROLE",
    "ESCALATION_MODEL",
    "ESCALATION_REASONS",
    "ESCALATION_ROUTE_ROLE",
    "FANIN_SENTINEL",
    "GROK_TEMPORAL_ACTIVITIES",
    "LEGACY_DEFAULT_MODEL",
    "MODEL_POLICY_ID",
    "POLICY_ID",
    "PROVIDER_CAPACITY_CEILING",
    "PROVIDER_ID",
    "execute_grok_acpx_lane",
    "is_completed_grok_lane",
    "materialize_grok_acpx_fanin",
    "materialize_model_identity",
    "resolve_background_allowed_tools",
    "resolve_provider_model",
    "validate_ready_frontier",
]
