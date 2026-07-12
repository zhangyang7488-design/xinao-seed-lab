"""Durable state and fencing for asynchronous external-agent turns."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import apsw

from .database import Database, row_as_dict, rows_as_dicts
from .errors import (
    ConflictError,
    CoordinationError,
    InvalidTransitionError,
    LeaseError,
    NotFoundError,
    ValidationError,
)

TERMINAL_STATES = {"completed", "failed", "canceled", "deadline_exceeded"}
RECONCILABLE_STATES = {
    "queued",
    "running",
    "retry_wait",
    "cancel_requested",
    "waiting_input",
    "uncertain",
}
OUTCOMES = frozenset(TERMINAL_STATES)
SCHEMA_TAG = "xinao.agent_operation.v1"


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _decode(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json"))
    return result


class AgentOperationStore:
    """Owns durable operation state; transport execution stays in a thin adapter."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.db = Database(db_path)
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    def now_ms(self) -> int:
        return int(self._clock_ms())

    def _operation_from_conn(self, conn: apsw.Connection, operation_id: str) -> dict[str, Any] | None:
        return _decode(
            row_as_dict(
                conn.execute(
                    "SELECT * FROM agent_operations WHERE operation_id=?",
                    (operation_id,),
                )
            )
        )

    def _append_event(
        self,
        conn: apsw.Connection,
        *,
        operation_id: str,
        version: int,
        event_type: str,
        actor: str,
        payload: dict[str, object],
        now: int,
        idempotency_key: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO events(
                event_id,stream_type,stream_id,stream_version,event_type,actor,schema_version,
                correlation_id,payload_json,occurred_at_ms,idempotency_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _id("evt"),
                "system",
                operation_id,
                version,
                event_type,
                actor,
                SCHEMA_TAG,
                operation_id,
                _canonical(payload),
                now,
                idempotency_key,
            ),
        )

    def submit(
        self,
        *,
        actor: str,
        prompt: str,
        session_name: str,
        cwd: str | Path,
        deadline_seconds: int = 1_800,
        max_attempts: int = 1,
        replay_safe: bool = False,
        idempotency_key: str,
        metadata: dict[str, object] | None = None,
        operation_id: str | None = None,
    ) -> dict[str, object]:
        if actor not in {"user", "codex"}:
            raise ValidationError("agent operation actor must be user or codex", details={"actor": actor})
        if not prompt.strip() or not session_name.strip() or not idempotency_key.strip():
            raise ValidationError("prompt, session_name, and idempotency_key are required")
        if deadline_seconds <= 0 or max_attempts <= 0:
            raise ValidationError("deadline_seconds and max_attempts must be positive")
        resolved_cwd = str(Path(cwd).resolve())
        request = {
            "actor": actor,
            "prompt": prompt,
            "session_name": session_name,
            "cwd": resolved_cwd,
            "deadline_seconds": deadline_seconds,
            "max_attempts": max_attempts,
            "replay_safe": replay_safe,
            "metadata": metadata or {},
        }
        request_hash = _hash(request)
        now = self.now_ms()
        with self.db.write() as conn:
            existing = row_as_dict(
                conn.execute(
                    """
                    SELECT operation_id,request_hash FROM agent_operations
                    WHERE actor=? AND idempotency_key=?
                    """,
                    (actor, idempotency_key),
                )
            )
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ConflictError(
                        "idempotency key was reused with a different agent operation",
                        details={"idempotency_key": idempotency_key},
                    )
                operation = self._operation_from_conn(conn, existing["operation_id"])
                return {
                    "ok": True,
                    "action": "agent_operation.submit",
                    "operation": operation,
                    "replayed": True,
                }
            op_id = operation_id or _id("op")
            token = f"XINAO_OPERATION_ID={op_id}"
            conn.execute(
                """
                INSERT INTO agent_operations(
                    operation_id,context_id,actor,target_role,session_name,cwd,prompt,operation_token,
                    request_hash,idempotency_key,state,max_attempts,available_at_ms,deadline_at_ms,
                    submitted_at_ms,updated_at_ms,version,metadata_json,request_id,replay_safe
                ) VALUES(?,? ,?,'grok_4_5',?,?,?,?,?,?,'queued',?,?,?,?,?,1,?,?,?)
                """,
                (
                    op_id,
                    op_id,
                    actor,
                    session_name,
                    resolved_cwd,
                    prompt,
                    token,
                    request_hash,
                    idempotency_key,
                    max_attempts,
                    now,
                    now + deadline_seconds * 1_000,
                    now,
                    now,
                    _canonical(metadata or {}),
                    op_id,
                    int(replay_safe),
                ),
            )
            self._append_event(
                conn,
                operation_id=op_id,
                version=1,
                event_type="AgentOperationSubmitted",
                actor=actor,
                payload={"target_role": "grok_4_5", "session_name": session_name},
                now=now,
                idempotency_key=idempotency_key,
            )
            operation = self._operation_from_conn(conn, op_id)
        return {
            "ok": True,
            "action": "agent_operation.submit",
            "operation": operation,
            "replayed": False,
        }

    def get(self, operation_id: str) -> dict[str, object]:
        with self.db.read() as conn:
            operation = self._operation_from_conn(conn, operation_id)
            if not operation:
                raise NotFoundError("agent operation not found", details={"operation_id": operation_id})
            artifacts = [
                _decode(row) or {}
                for row in rows_as_dicts(
                    conn.execute(
                        """
                        SELECT * FROM agent_operation_artifacts
                        WHERE operation_id=? ORDER BY created_at_ms,artifact_id
                        """,
                        (operation_id,),
                    )
                )
            ]
        return {"ok": True, "operation": operation, "artifacts": artifacts}

    def list(self, *, state: str | None = None, limit: int = 100) -> dict[str, object]:
        if limit <= 0 or limit > 1_000:
            raise ValidationError("limit must be between 1 and 1000")
        bindings: list[object] = []
        where = ""
        if state:
            where = "WHERE state=?"
            bindings.append(state)
        bindings.append(limit)
        with self.db.read() as conn:
            operations = [
                _decode(row) or {}
                for row in rows_as_dicts(
                    conn.execute(
                        f"SELECT * FROM agent_operations {where} ORDER BY submitted_at_ms DESC LIMIT ?",
                        bindings,
                    )
                )
            ]
        return {"ok": True, "operations": operations}

    def _expire_lease(self, conn: apsw.Connection, operation: dict[str, Any], now: int) -> dict[str, Any]:
        expires = operation.get("lease_expires_at_ms")
        if expires is None or int(expires) > now:
            return operation
        prior_state = str(operation["state"])
        state = prior_state
        completed_at_ms = operation["completed_at_ms"]
        stop_reason = operation["stop_reason"]
        error = operation["error"] or "reconcile lease expired"
        if prior_state == "cancel_requested":
            if operation["collector_pid"] is None:
                state = "canceled"
                completed_at_ms = now
                stop_reason = "canceled_before_transport_start"
            else:
                state = "uncertain"
                completed_at_ms = None
                stop_reason = "cancel_outcome_unknown"
        elif prior_state == "running" or (
            prior_state == "waiting_input" and operation["collector_pid"] is not None
        ):
            state = "uncertain"
            completed_at_ms = None
            stop_reason = "transport_outcome_unknown"
        version = int(operation["version"]) + 1
        conn.execute(
            """
            UPDATE agent_operations
            SET state=?,lease_owner=NULL,lease_token=NULL,lease_expires_at_ms=NULL,
                completed_at_ms=?,stop_reason=?,error=?,updated_at_ms=?,version=?
            WHERE operation_id=? AND version=? AND lease_token=?
            """,
            (
                state,
                completed_at_ms,
                stop_reason,
                error,
                now,
                version,
                operation["operation_id"],
                operation["version"],
                operation["lease_token"],
            ),
        )
        if conn.changes() != 1:
            raise ConflictError("agent operation changed while expiring its lease")
        self._append_event(
            conn,
            operation_id=operation["operation_id"],
            version=version,
            event_type="AgentOperationLeaseExpired",
            actor="system",
            payload={"prior_owner": operation["lease_owner"], "state": state},
            now=now,
        )
        refreshed = self._operation_from_conn(conn, operation["operation_id"])
        assert refreshed is not None
        return refreshed

    def _claim_locked(
        self,
        conn: apsw.Connection,
        operation: dict[str, Any],
        *,
        worker_id: str,
        lease_seconds: int,
        now: int,
    ) -> tuple[str, dict[str, Any]]:
        operation_id = str(operation["operation_id"])
        if operation["state"] in TERMINAL_STATES:
            raise InvalidTransitionError(
                "terminal agent operation cannot be claimed", details={"state": operation["state"]}
            )
        if operation["state"] == "uncertain":
            raise InvalidTransitionError(
                "uncertain agent operation requires external verification before another attempt",
                details={"state": operation["state"]},
            )
        if operation["state"] not in {"queued", "retry_wait"}:
            raise InvalidTransitionError(
                "agent operation is not claimable", details={"state": operation["state"]}
            )
        if int(operation["available_at_ms"]) > now:
            raise InvalidTransitionError("agent operation is not available yet")
        if int(operation["attempt_count"]) >= int(operation["max_attempts"]):
            raise InvalidTransitionError("agent operation attempt limit has been reached")
        if operation["lease_token"]:
            raise LeaseError(
                "agent operation already has an active reconcile lease",
                details={"lease_owner": operation["lease_owner"]},
            )
        active = row_as_dict(
            conn.execute(
                """
                SELECT operation_id FROM agent_operations
                WHERE operation_id<>? AND session_name=? AND cwd=?
                  AND (
                    state='uncertain'
                    OR (state IN ('running','cancel_requested') AND lease_expires_at_ms>?)
                  )
                LIMIT 1
                """,
                (operation_id, operation["session_name"], operation["cwd"], now),
            )
        )
        if active:
            raise LeaseError(
                "another agent operation is active for this session",
                details={"active_operation_id": active["operation_id"]},
            )
        token = _id("lease")
        version = int(operation["version"]) + 1
        conn.execute(
            """
            UPDATE agent_operations
            SET lease_owner=?,lease_token=?,lease_expires_at_ms=?,updated_at_ms=?,version=?
            WHERE operation_id=? AND version=? AND lease_token IS NULL
            """,
            (
                worker_id,
                token,
                now + lease_seconds * 1_000,
                now,
                version,
                operation_id,
                operation["version"],
            ),
        )
        if conn.changes() != 1:
            raise LeaseError("agent operation claim lost a concurrent race")
        self._append_event(
            conn,
            operation_id=operation_id,
            version=version,
            event_type="AgentOperationClaimed",
            actor="system",
            payload={"worker_id": worker_id, "lease_expires_at_ms": now + lease_seconds * 1_000},
            now=now,
        )
        claimed = self._operation_from_conn(conn, operation_id)
        assert claimed is not None
        return token, claimed

    def claim(self, operation_id: str, *, worker_id: str, lease_seconds: int = 60) -> dict[str, object]:
        if not worker_id.strip() or lease_seconds <= 0:
            raise ValidationError("worker_id and positive lease_seconds are required")
        now = self.now_ms()
        deferred_error: CoordinationError | None = None
        token: str | None = None
        claimed: dict[str, Any] | None = None
        with self.db.write() as conn:
            operation = self._operation_from_conn(conn, operation_id)
            if not operation:
                deferred_error = NotFoundError(
                    "agent operation not found", details={"operation_id": operation_id}
                )
            else:
                operation = self._expire_lease(conn, operation, now)
                try:
                    token, claimed = self._claim_locked(
                        conn,
                        operation,
                        worker_id=worker_id,
                        lease_seconds=lease_seconds,
                        now=now,
                    )
                except CoordinationError as exc:
                    deferred_error = exc
        if deferred_error is not None:
            raise deferred_error
        assert token is not None and claimed is not None
        return {
            "ok": True,
            "action": "agent_operation.claim",
            "lease_token": token,
            "control_epoch": claimed["control_epoch"],
            "operation": claimed,
        }

    def mark_running(
        self,
        operation_id: str,
        *,
        lease_token: str,
        control_epoch: int,
        worker_id: str,
        collector_pid: int,
        collector_start_time_ms: int,
        event_log_path: str,
        stderr_log_path: str,
    ) -> dict[str, object]:
        now = self.now_ms()
        with self.db.write() as conn:
            operation = self._leased(conn, operation_id, lease_token, control_epoch, now)
            if operation["state"] == "cancel_requested":
                raise InvalidTransitionError("canceled agent operation must not start")
            if operation["state"] not in {"queued", "retry_wait", "uncertain", "running"}:
                raise InvalidTransitionError(
                    "agent operation cannot start from current state", details={"state": operation["state"]}
                )
            version = int(operation["version"]) + 1
            attempt_count = int(operation["attempt_count"]) + (operation["state"] != "running")
            conn.execute(
                """
                UPDATE agent_operations
                SET state='running',lease_owner=?,collector_pid=?,collector_start_time_ms=?,event_log_path=?,
                    stderr_log_path=?,attempt_count=?,started_at_ms=COALESCE(started_at_ms,?),
                    last_progress_at_ms=?,updated_at_ms=?,version=?
                WHERE operation_id=? AND version=? AND lease_token=?
                """,
                (
                    worker_id,
                    collector_pid,
                    collector_start_time_ms,
                    event_log_path,
                    stderr_log_path,
                    attempt_count,
                    now,
                    now,
                    now,
                    version,
                    operation_id,
                    operation["version"],
                    lease_token,
                ),
            )
            if conn.changes() != 1:
                raise LeaseError("agent operation start lost its lease")
            self._append_event(
                conn,
                operation_id=operation_id,
                version=version,
                event_type="AgentOperationStarted",
                actor="system",
                payload={"collector_pid": collector_pid, "attempt_count": attempt_count},
                now=now,
            )
            current = self._operation_from_conn(conn, operation_id)
        return {"ok": True, "action": "agent_operation.start", "operation": current}

    def record_transport(
        self,
        operation_id: str,
        *,
        lease_token: str,
        control_epoch: int,
        request_id: str | None = None,
        provider_prompt_id: str | None = None,
        acpx_record_id: str | None = None,
        agent_session_id: str | None = None,
        owner_pid: int | None = None,
        owner_start_time_ms: int | None = None,
        owner_generation: int | None = None,
        result_text: str | None = None,
    ) -> dict[str, object]:
        now = self.now_ms()
        with self.db.write() as conn:
            operation = self._leased(conn, operation_id, lease_token, control_epoch, now)
            version = int(operation["version"]) + 1
            values = {
                "request_id": request_id if request_id is not None else operation["request_id"],
                "provider_prompt_id": (
                    provider_prompt_id if provider_prompt_id is not None else operation["provider_prompt_id"]
                ),
                "acpx_record_id": (
                    acpx_record_id if acpx_record_id is not None else operation["acpx_record_id"]
                ),
                "agent_session_id": (
                    agent_session_id if agent_session_id is not None else operation["agent_session_id"]
                ),
                "owner_pid": owner_pid if owner_pid is not None else operation["owner_pid"],
                "owner_start_time_ms": (
                    owner_start_time_ms
                    if owner_start_time_ms is not None
                    else operation["owner_start_time_ms"]
                ),
                "owner_generation": (
                    owner_generation if owner_generation is not None else operation["owner_generation"]
                ),
                "result_text": result_text if result_text is not None else operation["result_text"],
            }
            conn.execute(
                """
                UPDATE agent_operations
                SET request_id=?,provider_prompt_id=?,acpx_record_id=?,agent_session_id=?,owner_pid=?,
                    owner_start_time_ms=?,owner_generation=?,result_text=?,last_progress_at_ms=?,
                    updated_at_ms=?,version=?
                WHERE operation_id=? AND version=? AND lease_token=?
                """,
                (
                    *values.values(),
                    now,
                    now,
                    version,
                    operation_id,
                    operation["version"],
                    lease_token,
                ),
            )
            if conn.changes() != 1:
                raise LeaseError("agent operation progress lost its lease")
            self._append_event(
                conn,
                operation_id=operation_id,
                version=version,
                event_type="AgentOperationProgressed",
                actor="system",
                payload={"request_id": values["request_id"]},
                now=now,
            )
            current = self._operation_from_conn(conn, operation_id)
        return {"ok": True, "action": "agent_operation.progress", "operation": current}

    def heartbeat(
        self,
        operation_id: str,
        *,
        lease_token: str,
        control_epoch: int,
        lease_seconds: int = 60,
        made_progress: bool = False,
    ) -> dict[str, object]:
        if lease_seconds <= 0:
            raise ValidationError("lease_seconds must be positive")
        now = self.now_ms()
        with self.db.write() as conn:
            operation = self._leased(conn, operation_id, lease_token, control_epoch, now)
            version = int(operation["version"]) + 1
            progress_at = now if made_progress else operation["last_progress_at_ms"]
            conn.execute(
                """
                UPDATE agent_operations
                SET lease_expires_at_ms=?,last_progress_at_ms=?,updated_at_ms=?,version=?
                WHERE operation_id=? AND version=? AND lease_token=? AND control_epoch=?
                """,
                (
                    now + lease_seconds * 1_000,
                    progress_at,
                    now,
                    version,
                    operation_id,
                    operation["version"],
                    lease_token,
                    control_epoch,
                ),
            )
            if conn.changes() != 1:
                raise LeaseError("agent operation heartbeat lost its lease or control epoch")
            current = self._operation_from_conn(conn, operation_id)
        return {"ok": True, "action": "agent_operation.heartbeat", "operation": current}

    def request_cancel(self, operation_id: str, *, actor: str, reason: str) -> dict[str, object]:
        if actor not in {"user", "codex"} or not reason.strip():
            raise ValidationError("valid actor and cancellation reason are required")
        now = self.now_ms()
        with self.db.write() as conn:
            operation = self._operation_from_conn(conn, operation_id)
            if not operation:
                raise NotFoundError("agent operation not found", details={"operation_id": operation_id})
            if operation["state"] in TERMINAL_STATES:
                return {
                    "ok": True,
                    "action": "agent_operation.cancel",
                    "operation": operation,
                    "already_terminal": True,
                }
            if operation["state"] == "cancel_requested":
                return {
                    "ok": True,
                    "action": "agent_operation.cancel",
                    "operation": operation,
                    "already_requested": True,
                }
            version = int(operation["version"]) + 1
            safe_pre_start_cancel = (
                operation["state"] in {"queued", "retry_wait", "waiting_input"}
                and operation["lease_token"] is None
                and operation["collector_pid"] is None
            )
            target_state = "canceled" if safe_pre_start_cancel else "cancel_requested"
            completed_at_ms = now if safe_pre_start_cancel else None
            conn.execute(
                """
                UPDATE agent_operations
                SET state=?,control_epoch=control_epoch+1,error=?,completed_at_ms=?,updated_at_ms=?,version=?
                WHERE operation_id=? AND version=?
                """,
                (
                    target_state,
                    reason,
                    completed_at_ms,
                    now,
                    version,
                    operation_id,
                    operation["version"],
                ),
            )
            if conn.changes() != 1:
                raise ConflictError("agent operation changed while requesting cancellation")
            self._append_event(
                conn,
                operation_id=operation_id,
                version=version,
                event_type=(
                    "AgentOperationCanceledBeforeStart"
                    if safe_pre_start_cancel
                    else "AgentOperationCancelRequested"
                ),
                actor=actor,
                payload={"reason": reason},
                now=now,
            )
            current = self._operation_from_conn(conn, operation_id)
        return {"ok": True, "action": "agent_operation.cancel", "operation": current}

    def finish(
        self,
        operation_id: str,
        *,
        lease_token: str,
        control_epoch: int,
        outcome: Literal["completed", "failed", "canceled", "deadline_exceeded"],
        stop_reason: str,
        result_text: str | None = None,
        error: str | None = None,
        retryable: bool = False,
        retry_delay_seconds: int = 0,
    ) -> dict[str, object]:
        if outcome not in OUTCOMES:
            raise ValidationError("invalid agent operation outcome", details={"outcome": outcome})
        now = self.now_ms()
        with self.db.write() as conn:
            operation = self._leased(conn, operation_id, lease_token, control_epoch, now)
            if operation["state"] == "cancel_requested" and outcome == "completed":
                raise InvalidTransitionError(
                    "cancel-requested operation cannot be completed by the prior worker"
                )
            state = outcome
            available_at_ms = operation["available_at_ms"]
            completed_at_ms: int | None = now
            if (
                outcome == "failed"
                and retryable
                and int(operation["attempt_count"]) < int(operation["max_attempts"])
            ):
                state = "retry_wait"
                available_at_ms = now + max(0, retry_delay_seconds) * 1_000
                completed_at_ms = None
            version = int(operation["version"]) + 1
            conn.execute(
                """
                UPDATE agent_operations
                SET state=?,available_at_ms=?,completed_at_ms=?,stop_reason=?,result_text=?,error=?,
                    lease_owner=NULL,lease_token=NULL,lease_expires_at_ms=NULL,
                    updated_at_ms=?,last_progress_at_ms=?,version=?
                WHERE operation_id=? AND version=? AND lease_token=?
                """,
                (
                    state,
                    available_at_ms,
                    completed_at_ms,
                    stop_reason,
                    result_text,
                    error,
                    now,
                    now,
                    version,
                    operation_id,
                    operation["version"],
                    lease_token,
                ),
            )
            if conn.changes() != 1:
                raise LeaseError("agent operation finish lost its lease")
            self._append_event(
                conn,
                operation_id=operation_id,
                version=version,
                event_type=(
                    "AgentOperationRetryScheduled" if state == "retry_wait" else "AgentOperationFinished"
                ),
                actor="system",
                payload={"state": state, "stop_reason": stop_reason},
                now=now,
            )
            current = self._operation_from_conn(conn, operation_id)
        return {"ok": True, "action": "agent_operation.finish", "operation": current}

    def mark_uncertain(
        self,
        operation_id: str,
        *,
        lease_token: str,
        control_epoch: int,
        error: str,
    ) -> dict[str, object]:
        now = self.now_ms()
        with self.db.write() as conn:
            operation = self._leased(conn, operation_id, lease_token, control_epoch, now)
            version = int(operation["version"]) + 1
            conn.execute(
                """
                UPDATE agent_operations
                SET state='uncertain',error=?,lease_owner=NULL,lease_token=NULL,
                    lease_expires_at_ms=NULL,updated_at_ms=?,version=?
                WHERE operation_id=? AND version=? AND lease_token=? AND control_epoch=?
                """,
                (
                    error,
                    now,
                    version,
                    operation_id,
                    operation["version"],
                    lease_token,
                    control_epoch,
                ),
            )
            if conn.changes() != 1:
                raise LeaseError("agent operation uncertainty update lost its lease")
            self._append_event(
                conn,
                operation_id=operation_id,
                version=version,
                event_type="AgentOperationUncertain",
                actor="system",
                payload={"error": error},
                now=now,
            )
            current = self._operation_from_conn(conn, operation_id)
        return {"ok": True, "action": "agent_operation.uncertain", "operation": current}

    def add_artifact(
        self,
        operation_id: str,
        *,
        name: str,
        uri: str,
        media_type: str,
        sha256: str,
        size_bytes: int,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if not name.strip() or not uri.strip() or size_bytes < 0:
            raise ValidationError("artifact name, uri, and non-negative size are required")
        now = self.now_ms()
        with self.db.write() as conn:
            operation = self._operation_from_conn(conn, operation_id)
            if not operation:
                raise NotFoundError("agent operation not found", details={"operation_id": operation_id})
            existing = row_as_dict(
                conn.execute(
                    """
                    SELECT * FROM agent_operation_artifacts
                    WHERE operation_id=? AND uri=?
                    """,
                    (operation_id, uri),
                )
            )
            if existing:
                return {"ok": True, "action": "agent_operation.artifact", "artifact": _decode(existing)}
            artifact_id = _id("artifact")
            conn.execute(
                """
                INSERT INTO agent_operation_artifacts(
                    artifact_id,operation_id,name,uri,media_type,sha256,size_bytes,created_at_ms,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    artifact_id,
                    operation_id,
                    name,
                    uri,
                    media_type,
                    sha256,
                    size_bytes,
                    now,
                    _canonical(metadata or {}),
                ),
            )
            version = int(operation["version"]) + 1
            conn.execute(
                "UPDATE agent_operations SET updated_at_ms=?,version=? WHERE operation_id=? AND version=?",
                (now, version, operation_id, operation["version"]),
            )
            if conn.changes() != 1:
                raise ConflictError("agent operation changed while registering an artifact")
            self._append_event(
                conn,
                operation_id=operation_id,
                version=version,
                event_type="AgentOperationArtifactRegistered",
                actor="system",
                payload={"artifact_id": artifact_id, "uri": uri},
                now=now,
            )
            artifact = _decode(
                row_as_dict(
                    conn.execute(
                        "SELECT * FROM agent_operation_artifacts WHERE artifact_id=?",
                        (artifact_id,),
                    )
                )
            )
        return {"ok": True, "action": "agent_operation.artifact", "artifact": artifact}

    def release(self, operation_id: str, *, lease_token: str) -> dict[str, object]:
        now = self.now_ms()
        with self.db.write() as conn:
            operation = self._leased(conn, operation_id, lease_token, None, now)
            version = int(operation["version"]) + 1
            conn.execute(
                """
                UPDATE agent_operations
                SET lease_owner=NULL,lease_token=NULL,lease_expires_at_ms=NULL,updated_at_ms=?,version=?
                WHERE operation_id=? AND version=? AND lease_token=?
                """,
                (now, version, operation_id, operation["version"], lease_token),
            )
            if conn.changes() != 1:
                raise LeaseError("agent operation release lost its lease")
            self._append_event(
                conn,
                operation_id=operation_id,
                version=version,
                event_type="AgentOperationLeaseReleased",
                actor="system",
                payload={"prior_owner": operation["lease_owner"]},
                now=now,
            )
            current = self._operation_from_conn(conn, operation_id)
        return {"ok": True, "action": "agent_operation.release", "operation": current}

    def _leased(
        self,
        conn: apsw.Connection,
        operation_id: str,
        lease_token: str,
        control_epoch: int | None,
        now: int,
    ) -> dict[str, Any]:
        operation = self._operation_from_conn(conn, operation_id)
        if not operation:
            raise NotFoundError("agent operation not found", details={"operation_id": operation_id})
        if operation["lease_token"] != lease_token or int(operation["lease_expires_at_ms"] or 0) <= now:
            raise LeaseError("invalid or expired agent operation lease")
        if control_epoch is not None and int(operation["control_epoch"]) != control_epoch:
            raise LeaseError(
                "agent operation control epoch changed",
                details={
                    "expected_control_epoch": control_epoch,
                    "actual_control_epoch": operation["control_epoch"],
                },
            )
        return operation

    def sweep(self) -> dict[str, object]:
        now = self.now_ms()
        expired = 0
        deadline_cancel_requests = 0
        deadline_prestart_completions = 0
        orphan_cancel_resolutions = 0
        with self.db.write() as conn:
            ids = [
                row["operation_id"]
                for row in rows_as_dicts(
                    conn.execute(
                        """
                        SELECT operation_id FROM agent_operations
                        WHERE lease_expires_at_ms IS NOT NULL AND lease_expires_at_ms<=?
                        """,
                        (now,),
                    )
                )
            ]
            for operation_id in ids:
                operation = self._operation_from_conn(conn, operation_id)
                assert operation is not None
                self._expire_lease(conn, operation, now)
                expired += 1
            orphan_cancels = rows_as_dicts(
                conn.execute(
                    """
                    SELECT * FROM agent_operations
                    WHERE state='cancel_requested' AND lease_token IS NULL
                    """
                )
            )
            for operation in orphan_cancels:
                state = "canceled" if operation["collector_pid"] is None else "uncertain"
                stop_reason = (
                    "canceled_before_transport_start" if state == "canceled" else "cancel_outcome_unknown"
                )
                version = int(operation["version"]) + 1
                conn.execute(
                    """
                    UPDATE agent_operations
                    SET state=?,completed_at_ms=?,stop_reason=?,updated_at_ms=?,version=?
                    WHERE operation_id=? AND version=? AND state='cancel_requested'
                      AND lease_token IS NULL
                    """,
                    (
                        state,
                        now if state == "canceled" else None,
                        stop_reason,
                        now,
                        version,
                        operation["operation_id"],
                        operation["version"],
                    ),
                )
                if conn.changes() != 1:
                    continue
                self._append_event(
                    conn,
                    operation_id=operation["operation_id"],
                    version=version,
                    event_type="AgentOperationOrphanCancelResolved",
                    actor="system",
                    payload={"state": state, "stop_reason": stop_reason},
                    now=now,
                )
                orphan_cancel_resolutions += 1
            deadline_rows = rows_as_dicts(
                conn.execute(
                    """
                    SELECT * FROM agent_operations
                    WHERE deadline_at_ms<=? AND state NOT IN (
                        'completed','failed','canceled','deadline_exceeded','cancel_requested','uncertain'
                    )
                    """,
                    (now,),
                )
            )
            for operation in deadline_rows:
                safe_prestart = operation["lease_token"] is None and operation["collector_pid"] is None
                target_state = "deadline_exceeded" if safe_prestart else "cancel_requested"
                version = int(operation["version"]) + 1
                conn.execute(
                    """
                    UPDATE agent_operations
                    SET state=?,control_epoch=control_epoch+1,error='deadline reached',
                        completed_at_ms=?,stop_reason=?,updated_at_ms=?,version=?
                    WHERE operation_id=? AND version=?
                    """,
                    (
                        target_state,
                        now if safe_prestart else None,
                        "deadline_before_transport_start" if safe_prestart else None,
                        now,
                        version,
                        operation["operation_id"],
                        operation["version"],
                    ),
                )
                if conn.changes() != 1:
                    continue
                self._append_event(
                    conn,
                    operation_id=operation["operation_id"],
                    version=version,
                    event_type=(
                        "AgentOperationDeadlineExceededBeforeStart"
                        if safe_prestart
                        else "AgentOperationDeadlineReached"
                    ),
                    actor="system",
                    payload={"prior_state": operation["state"]},
                    now=now,
                )
                if safe_prestart:
                    deadline_prestart_completions += 1
                else:
                    deadline_cancel_requests += 1
        return {
            "ok": True,
            "expired_agent_operation_leases": expired,
            "deadline_cancel_requests": deadline_cancel_requests,
            "deadline_prestart_completions": deadline_prestart_completions,
            "orphan_cancel_resolutions": orphan_cancel_resolutions,
        }
