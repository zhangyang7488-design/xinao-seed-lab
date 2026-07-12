"""Promoted-task activities — side effects gated by operation_id + intent hash.

Registered on the Temporal Worker (G1). Kernel remains authority; these steps are
durable, idempotent-ish bookkeeping for the promoted-task workflow only.

execute_promoted_step (v2): writes a D-disk evidence artifact (path + sha256) and
best-effort hooks kernel SQLite artifacts/events when the task row exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from temporalio import activity
from temporalio.common import RetryPolicy

from .grok_parallel import GROK_TEMPORAL_ACTIVITIES

# Official pattern: Activity RetryPolicy on execute_activity (docs.temporal.io
# develop/python/activities/timeouts — Set an Activity Retry Policy).
DEFAULT_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
    non_retryable_error_types=["ValueError", "TypeError"],
)

DEFAULT_START_TO_CLOSE = timedelta(seconds=30)

# D-disk default; override with XINAO_PROMOTED_STEP_ARTIFACT_DIR for tests/canaries.
DEFAULT_PROMOTED_STEP_ARTIFACT_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\promoted_step_artifacts"
)
DEFAULT_PROMOTED_INTAKE_ARTIFACT_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\promoted_intake"
)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class PromotedActivityInput:
    """Single payload for activities (prefer one object over multi-args)."""

    task_id: str
    workflow_id: str
    generation: int
    immutable_intent_hash: str
    title: str
    goal: str
    source_thread_id: str | None
    owner: str
    decision_hash: str
    operation_id: str
    kernel_lease_token: str = ""
    promoted_only: bool = True
    note: str = ""

    @classmethod
    def from_workflow_input(
        cls,
        data: dict[str, Any],
        *,
        operation_id: str,
        note: str = "",
    ) -> PromotedActivityInput:
        if not isinstance(data, dict):
            raise TypeError("workflow input must be a dict")
        if not data.get("promoted_only", True):
            raise ValueError("activities refuse non-promoted payload")
        task_id = str(data.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("task_id required")
        intent = str(data.get("immutable_intent_hash") or "").strip()
        if not intent:
            raise ValueError("immutable_intent_hash required")
        return cls(
            task_id=task_id,
            workflow_id=str(data.get("workflow_id") or ""),
            generation=int(data.get("generation") or 0),
            immutable_intent_hash=intent,
            title=str(data.get("title") or ""),
            goal=str(data.get("goal") or ""),
            source_thread_id=(str(data["source_thread_id"]) if data.get("source_thread_id") else None),
            owner=str(data.get("owner") or "admin"),
            decision_hash=str(data.get("decision_hash") or intent),
            operation_id=operation_id,
            kernel_lease_token=str(data.get("kernel_lease_token") or ""),
            promoted_only=True,
            note=note,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _activity_info_meta() -> dict[str, Any]:
    info = activity.info()
    return {
        "activity_id": info.activity_id,
        "activity_type": info.activity_type,
        "attempt": info.attempt,
        "workflow_id": info.workflow_id,
        "workflow_run_id": info.workflow_run_id,
        "task_queue": info.task_queue,
    }


def _promoted_step_artifact_root() -> Path:
    configured = os.environ.get("XINAO_PROMOTED_STEP_ARTIFACT_DIR", "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_PROMOTED_STEP_ARTIFACT_ROOT


def _promoted_intake_artifact_root() -> Path:
    configured = os.environ.get("XINAO_PROMOTED_INTAKE_ARTIFACT_DIR", "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_PROMOTED_INTAKE_ARTIFACT_ROOT


def _safe_filename_part(value: str, *, max_len: int = 80) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", (value or "").strip())
    return (cleaned or "unknown")[:max_len]


def _actor_for_artifact(owner: str) -> str:
    allowed = {"user", "grok_4_5", "codex", "admin"}
    who = (owner or "").strip()
    return who if who in allowed else "admin"


def _evidence_container_path(path: Path) -> str | None:
    """Map canonical D-drive runtime artifacts into the Docker /evidence mount."""
    try:
        relative = path.resolve().relative_to(Path(r"D:\XINAO_RESEARCH_RUNTIME"))
    except ValueError:
        return None
    return "/evidence/" + relative.as_posix()


def _host_evidence_path(value: object) -> Path | None:
    """Resolve only canonical D-runtime evidence refs; reject all other host roots."""
    raw = str(value or "").strip().replace("/", "\\")
    runtime = Path(r"D:\XINAO_RESEARCH_RUNTIME").resolve()
    path = runtime / raw[len("\\evidence\\") :] if raw.casefold().startswith("\\evidence\\") else Path(raw)
    try:
        resolved = path.resolve()
        resolved.relative_to(runtime)
    except (OSError, ValueError):
        return None
    return resolved


def verify_langgraph_child_evidence(
    inp: PromotedActivityInput,
    child_summary: dict[str, Any],
) -> dict[str, Any]:
    """Read back child-owned D artifacts and bind them to the promoted task."""
    refs = {
        "input_path": child_summary.get("input_path"),
        "proof_path": child_summary.get("proof_path"),
        "promotion_evidence_ref": child_summary.get("promotion_evidence_ref"),
        "pytest_slice_ref": child_summary.get("pytest_slice_ref"),
    }
    files: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for name, ref in refs.items():
        path = _host_evidence_path(ref)
        if path is None:
            failures.append(f"{name}:outside_canonical_runtime")
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            failures.append(f"{name}:{type(exc).__name__}")
            continue
        files[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        if name == "input_path":
            text = raw.decode("utf-8", errors="replace")
            if inp.title and inp.title not in text:
                failures.append("input_path:title_mismatch")
            if inp.goal and inp.goal not in text:
                failures.append("input_path:goal_mismatch")
    if child_summary.get("passed") is not True:
        failures.append("child_summary:not_passed")
    return {
        "ok": not failures,
        "failures": failures,
        "files": files,
        "task_id": inp.task_id,
        "child_workflow_id": child_summary.get("workflow_id"),
    }


def write_promoted_intake_artifact(inp: PromotedActivityInput) -> dict[str, Any]:
    """Materialize the promoted task as the real L0 Markdown input for LangGraph."""
    root = _promoted_intake_artifact_root()
    task_part = _safe_filename_part(inp.task_id)
    path = root / f"{task_part}_g{inp.generation}.md"
    body = "\n".join(
        [
            "# Promoted task input",
            "",
            f"- task_id: {inp.task_id}",
            f"- workflow_id: {inp.workflow_id}",
            f"- generation: {inp.generation}",
            f"- owner: {inp.owner}",
            f"- immutable_intent_hash: {inp.immutable_intent_hash}",
            "",
            "## Title",
            "",
            inp.title,
            "",
            "## Goal",
            "",
            inp.goal,
            "",
        ]
    )
    try:
        root.mkdir(parents=True, exist_ok=True)
        raw = body.encode("utf-8")
        path.write_bytes(raw)
    except OSError as exc:
        return {
            "ok": False,
            "artifact_path": str(path),
            "container_path": None,
            "sha256": None,
            "size_bytes": None,
            "error_type": type(exc).__name__,
            "message": str(exc)[:240],
        }
    return {
        "ok": True,
        "artifact_path": str(path.resolve()),
        "container_path": _evidence_container_path(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _try_sqlite_artifact_hook(
    *,
    task_id: str,
    path: Path,
    owner: str,
    operation_id: str,
    step_index: int,
) -> dict[str, Any]:
    """Best-effort: register file into kernel artifacts + ArtifactRegistered event.

    Fail-open: missing DB, missing task, or any error is recorded — never raised.
    Temporal retries with the same operation_id are treated as already_registered
    when the kernel reports ConflictError (idempotency / unique uri).
    """
    try:
        from xinao_coordination.database import default_db_path
        from xinao_coordination.errors import ConflictError, NotFoundError
        from xinao_coordination.service import CoordinationService
    except Exception as exc:
        return {
            "ok": False,
            "reason": "import_error",
            "error_type": type(exc).__name__,
            "message": str(exc)[:240],
        }

    try:
        db_path = default_db_path()
        if not db_path.is_file():
            return {"ok": False, "reason": "db_missing", "db_path": str(db_path)}

        service = CoordinationService(db_path)
        try:
            task_view = service.get_task(task_id)
        except NotFoundError as exc:
            return {
                "ok": False,
                "reason": "task_not_found",
                "db_path": str(db_path),
                "error_type": type(exc).__name__,
                "message": str(exc)[:240],
            }
        except Exception as exc:
            return {
                "ok": False,
                "reason": "task_lookup_failed",
                "db_path": str(db_path),
                "error_type": type(exc).__name__,
                "message": str(exc)[:240],
            }
        if not isinstance(task_view, dict) or not task_view.get("ok"):
            return {
                "ok": False,
                "reason": "task_not_found",
                "db_path": str(db_path),
            }

        actor = _actor_for_artifact(owner)
        idem = f"promoted-step-artifact:{task_id}:{operation_id}:{step_index}"
        try:
            result = service.register_local_artifact(
                actor=actor,
                task_id=task_id,
                path=path,
                name=path.name,
                media_type="application/json",
                idempotency_key=idem,
            )
        except ConflictError as exc:
            # Retry / re-run: kernel already recorded this operation_id.
            return {
                "ok": True,
                "reason": "already_registered_or_idempotent",
                "db_path": str(db_path),
                "actor": actor,
                "idempotency_key": idem,
                "event_type": "ArtifactRegistered",
                "message": str(exc)[:240],
            }

        artifact = result.get("artifact") if isinstance(result, dict) else None
        artifact_id = None
        if isinstance(artifact, dict):
            artifact_id = artifact.get("artifact_id")
        return {
            "ok": True,
            "reason": "registered",
            "db_path": str(db_path),
            "artifact_id": artifact_id,
            "actor": actor,
            "idempotency_key": idem,
            "event_type": "ArtifactRegistered",
        }
    except Exception as exc:
        return {
            "ok": False,
            "reason": "register_failed",
            "error_type": type(exc).__name__,
            "message": str(exc)[:240],
        }


def write_promoted_step_artifact(
    inp: PromotedActivityInput,
    *,
    step_index: int,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write D-disk JSON evidence; return path + sha256 + optional sqlite hook.

    Pure side-effect helper (callable outside Temporal for unit tests). Does not
    raise on I/O or SQLite failures — returns structured status instead.

    Path is stable per (task_id, generation, step_index, operation_id) so Temporal
    activity retries overwrite the same file and remain SQLite-idempotent.
    """
    root = _promoted_step_artifact_root()
    stamp_ms = int(time.time() * 1000)
    stamp_iso = datetime.now(UTC).isoformat()
    op_part = _safe_filename_part(inp.operation_id.replace(":", "_"), max_len=120)
    task_part = _safe_filename_part(inp.task_id)
    # Stable name — no wall-clock suffix (retry-safe).
    filename = f"{task_part}_g{inp.generation}_s{step_index}_{op_part}.json"
    path = root / filename

    body: dict[str, Any] = {
        "schema": "xinao.promoted_step_artifact.v1",
        "written_at_utc": stamp_iso,
        "written_at_ms": stamp_ms,
        "task_id": inp.task_id,
        "workflow_id": inp.workflow_id,
        "generation": inp.generation,
        "step_index": step_index,
        "operation_id": inp.operation_id,
        "immutable_intent_hash": inp.immutable_intent_hash,
        "decision_hash": inp.decision_hash,
        "title": inp.title,
        "goal": inp.goal,
        "owner": inp.owner,
        "source_thread_id": inp.source_thread_id,
        "note": inp.note,
        "promoted_only": inp.promoted_only,
        "meta": meta or {},
    }
    try:
        root.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        path.write_bytes(raw)
        sha256 = hashlib.sha256(raw).hexdigest()
        size_bytes = len(raw)
    except OSError as exc:
        return {
            "ok": False,
            "artifact_path": str(path),
            "sha256": None,
            "size_bytes": None,
            "content_hash": None,
            "error_type": type(exc).__name__,
            "message": str(exc)[:240],
            "sqlite_hook": {"ok": False, "reason": "skipped_write_failed"},
        }

    sqlite_hook = _try_sqlite_artifact_hook(
        task_id=inp.task_id,
        path=path,
        owner=inp.owner,
        operation_id=inp.operation_id,
        step_index=step_index,
    )
    return {
        "ok": True,
        "artifact_path": str(path.resolve()),
        "sha256": sha256,
        "size_bytes": size_bytes,
        "content_hash": sha256,
        "sqlite_hook": sqlite_hook,
    }


@activity.defn(name="xinao.promoted.validate_envelope")
async def validate_promoted_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate promoted envelope; raise non-retryable ValueError on contract break."""
    inp = PromotedActivityInput.from_workflow_input(
        payload,
        operation_id=str(payload.get("operation_id") or "validate"),
    )
    activity.heartbeat({"phase": "validate", "task_id": inp.task_id})
    return {
        "ok": True,
        "phase": "validated",
        "task_id": inp.task_id,
        "immutable_intent_hash": inp.immutable_intent_hash,
        "generation": inp.generation,
        "meta": _activity_info_meta(),
    }


@activity.defn(name="xinao.promoted.record_started")
async def record_promoted_started(payload: dict[str, Any]) -> dict[str, Any]:
    """Record start of durable promoted work (idempotent by operation_id)."""
    inp = PromotedActivityInput.from_workflow_input(
        payload,
        operation_id=str(payload.get("operation_id") or "start"),
        note=str(payload.get("note") or ""),
    )
    activity.heartbeat({"phase": "started", "operation_id": inp.operation_id})
    intake = write_promoted_intake_artifact(inp)
    if intake.get("ok") is not True or not intake.get("container_path"):
        raise OSError(
            "failed to materialize promoted LangGraph intake: "
            f"{intake.get('error_type')}: {intake.get('message')}; "
            f"container_path={intake.get('container_path')}"
        )
    return {
        "ok": True,
        "phase": "started",
        "task_id": inp.task_id,
        "workflow_id": inp.workflow_id,
        "operation_id": inp.operation_id,
        "owner": inp.owner,
        "intake": intake,
        "meta": _activity_info_meta(),
    }


@activity.defn(name="xinao.promoted.execute_step")
async def execute_promoted_step(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one promoted work step; write D-disk artifact (path+sha256).

    Side-effect: JSON evidence under promoted_step_artifacts (or
    XINAO_PROMOTED_STEP_ARTIFACT_DIR). Best-effort SQLite artifact register when
    the coordination task row exists. Kernel remains SSOT for task transitions.
    """
    inp = PromotedActivityInput.from_workflow_input(
        payload,
        operation_id=str(payload.get("operation_id") or "step"),
        note=str(payload.get("note") or ""),
    )
    step_index = int(payload.get("step_index") or 0)
    activity.heartbeat(
        {
            "phase": "execute_step",
            "step_index": step_index,
            "operation_id": inp.operation_id,
        }
    )
    activity_meta = _activity_info_meta()
    child_summary = payload.get("langgraph_child")
    child_evidence = (
        verify_langgraph_child_evidence(inp, child_summary)
        if isinstance(child_summary, dict)
        else {"ok": True, "reason": "legacy_history_without_child"}
    )
    artifact_meta = {
        "activity": activity_meta,
        "langgraph_child": child_summary if isinstance(child_summary, dict) else None,
        "langgraph_evidence": child_evidence,
    }
    artifact = write_promoted_step_artifact(
        inp,
        step_index=step_index,
        meta=artifact_meta,
    )
    activity.heartbeat(
        {
            "phase": "execute_step_artifact",
            "step_index": step_index,
            "artifact_ok": bool(artifact.get("ok")),
            "sha256": artifact.get("sha256"),
        }
    )
    return {
        "ok": artifact.get("ok") is True and child_evidence.get("ok") is True,
        "phase": (
            "step_done" if artifact.get("ok") is True and child_evidence.get("ok") is True else "step_failed"
        ),
        "task_id": inp.task_id,
        "step_index": step_index,
        "operation_id": inp.operation_id,
        "title": inp.title,
        "goal": inp.goal,
        "meta": activity_meta,
        "langgraph_child": child_summary,
        "langgraph_evidence": child_evidence,
        "artifact": artifact,
    }


def _try_kernel_terminal_hook(
    inp: PromotedActivityInput,
    *,
    terminal: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Converge the kernel SSOT after a promoted Temporal terminal transition."""
    if not inp.kernel_lease_token:
        return {
            "ok": False,
            "required": True,
            "reason": "missing_kernel_lease_token",
        }
    try:
        from xinao_coordination.database import default_db_path
        from xinao_coordination.service import CoordinationService

        service = CoordinationService(default_db_path())
        task = service.get_task(inp.task_id)["task"]
        assert isinstance(task, dict)
        state = str(task.get("state") or "")
        if terminal == "completed":
            children = payload.get("langgraph_children")
            steps = payload.get("step_evidence")
            evidence = [
                {
                    "kind": "temporal_langgraph_children",
                    "workflow_id": inp.workflow_id,
                    "items": children if isinstance(children, list) else [],
                },
                {
                    "kind": "temporal_promoted_steps",
                    "workflow_id": inp.workflow_id,
                    "items": steps if isinstance(steps, list) else [],
                },
            ]
            result = service.complete_task(
                actor="admin",
                task_id=inp.task_id,
                lease_token=inp.kernel_lease_token,
                result_summary=(
                    "Temporal parent completed after canonical Docker LangGraph "
                    f"children={len(evidence[0]['items'])} steps={len(evidence[1]['items'])}"
                ),
                evidence=evidence,
                idempotency_key=f"temporal-terminal:{inp.workflow_id}:completed",
            )
        elif terminal == "failed":
            if state == "failed":
                return {"ok": True, "required": True, "state": state, "replayed": True}
            result = service.fail_task(
                actor="admin",
                task_id=inp.task_id,
                lease_token=inp.kernel_lease_token,
                error=str(payload.get("note") or "Temporal promoted workflow failed"),
                retryable=False,
                idempotency_key=f"temporal-terminal:{inp.workflow_id}:failed",
            )
        else:
            if state in {"canceled", "cancelled"}:
                return {"ok": True, "required": True, "state": state, "replayed": True}
            result = service.cancel_task(
                actor="codex",
                task_id=inp.task_id,
                reason=str(payload.get("note") or "Temporal promoted workflow cancelled"),
                idempotency_key=f"temporal-terminal:{inp.workflow_id}:cancelled",
            )
        current = result.get("task") if isinstance(result, dict) else None
        return {
            "ok": True,
            "required": True,
            "state": current.get("state") if isinstance(current, dict) else terminal,
            "action": result.get("action") if isinstance(result, dict) else None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "required": True,
            "error_type": type(exc).__name__,
            "message": str(exc)[:400],
        }


@activity.defn(name="xinao.promoted.finalize")
async def finalize_promoted_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Finalize promoted workflow (completed | cancelled | failed)."""
    inp = PromotedActivityInput.from_workflow_input(
        payload,
        operation_id=str(payload.get("operation_id") or "finalize"),
        note=str(payload.get("note") or ""),
    )
    terminal = str(payload.get("terminal_status") or "completed")
    if terminal not in {"completed", "cancelled", "failed"}:
        raise ValueError(f"invalid terminal_status: {terminal}")
    activity.heartbeat({"phase": "finalize", "terminal_status": terminal})
    kernel = _try_kernel_terminal_hook(inp, terminal=terminal, payload=payload)
    return {
        "ok": kernel.get("ok") is True,
        "phase": "finalized",
        "task_id": inp.task_id,
        "workflow_id": inp.workflow_id,
        "terminal_status": terminal,
        "operation_id": inp.operation_id,
        "note": inp.note,
        "kernel": kernel,
        "meta": _activity_info_meta(),
    }


# Explicit registry for Worker(activities=...)
PROMOTED_ACTIVITIES = (
    validate_promoted_envelope,
    record_promoted_started,
    execute_promoted_step,
    finalize_promoted_task,
    *GROK_TEMPORAL_ACTIVITIES,
)

__all__ = [
    "DEFAULT_ACTIVITY_RETRY",
    "DEFAULT_PROMOTED_INTAKE_ARTIFACT_ROOT",
    "DEFAULT_PROMOTED_STEP_ARTIFACT_ROOT",
    "DEFAULT_START_TO_CLOSE",
    "PROMOTED_ACTIVITIES",
    "PromotedActivityInput",
    "execute_promoted_step",
    "finalize_promoted_task",
    "record_promoted_started",
    "validate_promoted_envelope",
    "verify_langgraph_child_evidence",
    "write_promoted_intake_artifact",
    "write_promoted_step_artifact",
]
