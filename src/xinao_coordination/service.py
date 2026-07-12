"""Transactional domain service shared by the CLI and MCP adapters."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import apsw
from opentelemetry import trace
from pydantic import ValidationError as PydanticValidationError

from .database import Database, row_as_dict, rows_as_dicts, scalar
from .errors import (
    AuthorizationError,
    ConflictError,
    InvalidTransitionError,
    LeaseError,
    NotFoundError,
    ValidationError,
)
from .models import Actor, RouteAssessment, RouteSignals, assess_route

SCHEMA_TAG = "xinao.coordination.v1"
BRAINS = {Actor.GROK.value, Actor.CODEX.value}
DISCUSS_ACTORS = {Actor.USER.value, *BRAINS}
TASK_DISPATCHERS = {Actor.USER.value, *BRAINS}
# Process-bound MCP roles (single XINAO_COORD_ROLE per process). Shared with mcp_server
# so CLI/MCP role sets cannot drift. Discussion remains brain-only via MCP_DISCUSSION_ROLES;
# user host is bound for explicit stop_clear (and CLI --actor remains trusted-local for discuss).
MCP_USER_ROLES = frozenset({Actor.USER.value})
MCP_BOUND_ROLES = frozenset({Actor.CODEX.value, Actor.GROK.value, Actor.ADMIN.value, Actor.USER.value})
MCP_DISCUSSION_ROLES = frozenset(BRAINS)  # admin/user never discuss via MCP
MCP_ADMIN_ROLES = frozenset({Actor.ADMIN.value})
MCP_OPERATOR_ROLES = frozenset({Actor.CODEX.value})  # backup/sweep/ops
CLOSED_THREAD_STATES = {
    "ACCEPTED",
    "REJECTED",
    "EACH_CLOSED",
    "ESCALATED",
    "EXPIRED",
}
TERMINAL_TASK_STATES = {"completed", "failed", "canceled"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _request_hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _decode_json_fields(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    decoded = dict(row)
    for key in tuple(decoded):
        if key.endswith("_json") and decoded[key] is not None:
            decoded[key.removesuffix("_json")] = json.loads(decoded.pop(key))
    return decoded


def _actor(value: str | Actor) -> str:
    try:
        return Actor(value).value
    except ValueError as exc:
        raise ValidationError("unknown actor", details={"actor": str(value)}) from exc


class CoordinationService:
    """Small durable coordination kernel; it never invokes an LLM itself."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        import time

        self.db = Database(db_path)
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._tracer = trace.get_tracer("xinao_coordination", "0.1.0")

    def now_ms(self) -> int:
        return int(self._clock_ms())

    @staticmethod
    def assess(signals: RouteSignals | dict[str, object]) -> dict[str, object]:
        try:
            parsed = signals if isinstance(signals, RouteSignals) else RouteSignals.model_validate(signals)
        except PydanticValidationError as exc:
            raise ValidationError(
                "invalid route signals",
                details={
                    "errors": exc.errors(
                        include_url=False,
                        include_input=False,
                        include_context=False,
                    )
                },
            ) from exc
        result: RouteAssessment = assess_route(parsed)
        return {"ok": True, **result.model_dump()}

    def _append_event(
        self,
        conn: apsw.Connection,
        *,
        stream_type: str,
        stream_id: str,
        stream_version: int,
        event_type: str,
        actor: str,
        payload: dict[str, object],
        occurred_at_ms: int,
        idempotency_key: str | None = None,
        causation_id: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        event_id = _id("evt")
        span = trace.get_current_span().get_span_context()
        trace_id = f"{span.trace_id:032x}" if span.is_valid else None
        span_id = f"{span.span_id:016x}" if span.is_valid else None
        conn.execute(
            """
            INSERT INTO events(
                event_id,stream_type,stream_id,stream_version,event_type,actor,schema_version,
                causation_id,correlation_id,trace_id,span_id,payload_json,occurred_at_ms,idempotency_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                stream_type,
                stream_id,
                stream_version,
                event_type,
                actor,
                SCHEMA_TAG,
                causation_id,
                correlation_id,
                trace_id,
                span_id,
                _canonical(payload),
                occurred_at_ms,
                idempotency_key,
            ),
        )
        return event_id

    def _enqueue_notification(
        self,
        conn: apsw.Connection,
        *,
        recipient: str,
        topic: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, object],
        now: int,
    ) -> str:
        notification_id = _id("ntf")
        conn.execute(
            """
            INSERT INTO notification_outbox(
                notification_id,recipient,topic,aggregate_type,aggregate_id,payload_json,
                status,available_at_ms,created_at_ms
            ) VALUES(?,?,?,?,?,?,'pending',?,?)
            """,
            (
                notification_id,
                recipient,
                topic,
                aggregate_type,
                aggregate_id,
                _canonical(payload),
                now,
                now,
            ),
        )
        return notification_id

    def _idempotent(
        self,
        conn: apsw.Connection,
        *,
        actor: str,
        operation: str,
        key: str | None,
        request: dict[str, object],
        execute: Callable[[str], dict[str, object]],
    ) -> dict[str, object]:
        actual_key = key or _id("idem")
        digest = _request_hash(request)
        existing = row_as_dict(
            conn.execute(
                """
                SELECT request_hash,result_json FROM idempotency
                WHERE actor=? AND operation=? AND idempotency_key=?
                """,
                (actor, operation, actual_key),
            )
        )
        if existing:
            if existing["request_hash"] != digest:
                raise ConflictError(
                    "idempotency key was already used with a different request",
                    details={"actor": actor, "operation": operation, "idempotency_key": actual_key},
                )
            result = json.loads(existing["result_json"])
            result["replayed"] = True
            return result

        result = execute(actual_key)
        result.setdefault("ok", True)
        result["idempotency_key"] = actual_key
        result["replayed"] = False
        conn.execute(
            """
            INSERT INTO idempotency(
                actor,operation,idempotency_key,request_hash,result_json,created_at_ms
            ) VALUES(?,?,?,?,?,?)
            """,
            (actor, operation, actual_key, digest, _canonical(result), self.now_ms()),
        )
        return result

    @staticmethod
    def _require_actor(actor: str, allowed: set[str], action: str) -> None:
        if actor not in allowed:
            raise AuthorizationError(f"{actor} cannot {action}", details={"allowed": sorted(allowed)})

    @staticmethod
    def _check_expected(row: dict[str, Any], expected_version: int | None) -> None:
        if expected_version is not None and int(row["version"]) != expected_version:
            raise ConflictError(
                "optimistic version mismatch",
                details={"expected": expected_version, "actual": int(row["version"])},
            )

    def open_thread(
        self,
        *,
        actor: str | Actor,
        title: str,
        body: str | None = None,
        ttl_seconds: int = 7_200,
        max_rounds: int = 24,
        thread_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, DISCUSS_ACTORS, "open a brain discussion")
        if not title.strip():
            raise ValidationError("thread title must not be empty")
        if ttl_seconds <= 0 or max_rounds <= 0:
            raise ValidationError("ttl_seconds and max_rounds must be positive")
        request = {
            "thread_id": thread_id,
            "title": title,
            "body": body,
            "ttl_seconds": ttl_seconds,
            "max_rounds": max_rounds,
            "metadata": metadata or {},
        }
        with (
            self._tracer.start_as_current_span("coordination.thread.open"),
            self.db.write() as conn,
        ):

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                tid = thread_id or _id("th")
                conn.execute(
                    """
                    INSERT INTO threads(
                        thread_id,title,state,opened_by,version,rounds,max_rounds,
                        opened_at_ms,updated_at_ms,expires_at_ms,metadata_json
                    ) VALUES(?,?,'OPEN',?,1,0,?,?,?,?,?)
                    """,
                    (
                        tid,
                        title.strip(),
                        who,
                        max_rounds,
                        now,
                        now,
                        now + ttl_seconds * 1_000,
                        _canonical(metadata or {}),
                    ),
                )
                self._append_event(
                    conn,
                    stream_type="thread",
                    stream_id=tid,
                    stream_version=1,
                    event_type="ThreadOpened",
                    actor=who,
                    payload={"title": title.strip(), "ttl_seconds": ttl_seconds},
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=tid,
                )
                if body:
                    message_id = _id("msg")
                    conn.execute(
                        """
                        INSERT INTO messages(
                            message_id,thread_id,sender,recipient,kind,body,created_at_ms,idempotency_key
                        ) VALUES(?,?,?,'*','propose',?,?,?)
                        """,
                        (message_id, tid, who, body, now, f"{key}:initial"),
                    )
                    conn.execute(
                        """
                        UPDATE threads SET state='ACTIVE',rounds=1,version=2,updated_at_ms=?
                        WHERE thread_id=?
                        """,
                        (now, tid),
                    )
                    self._append_event(
                        conn,
                        stream_type="thread",
                        stream_id=tid,
                        stream_version=2,
                        event_type="MessagePosted",
                        actor=who,
                        payload={"message_id": message_id, "kind": "propose", "recipient": "*"},
                        occurred_at_ms=now,
                        idempotency_key=f"{key}:initial",
                        correlation_id=tid,
                    )
                    for recipient in sorted(BRAINS - {who}):
                        self._enqueue_notification(
                            conn,
                            recipient=recipient,
                            topic="thread.message",
                            aggregate_type="thread",
                            aggregate_id=tid,
                            payload={"thread_id": tid, "message_id": message_id},
                            now=now,
                        )
                thread = self._thread_from_conn(conn, tid)
                return {"action": "thread.open", "thread": thread}

            return self._idempotent(
                conn,
                actor=who,
                operation="thread.open",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def post_message(
        self,
        *,
        actor: str | Actor,
        thread_id: str,
        body: str,
        kind: str = "note",
        recipient: str = "*",
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, DISCUSS_ACTORS, "post to a brain discussion")
        allowed_kinds = {
            "propose",
            "ask",
            "inform",
            "counter",
            "challenge",
            "clarify",
            "correct",
            "reply",
            "note",
            "system",
        }
        if kind not in allowed_kinds:
            raise ValidationError("invalid message kind", details={"kind": kind})
        if recipient not in {Actor.USER.value, *BRAINS, "*"}:
            raise ValidationError("invalid discussion recipient", details={"recipient": recipient})
        if not body.strip():
            raise ValidationError("message body must not be empty")
        request = {
            "thread_id": thread_id,
            "body": body,
            "kind": kind,
            "recipient": recipient,
            "expected_version": expected_version,
        }
        with (
            self._tracer.start_as_current_span("coordination.thread.post"),
            self.db.write() as conn,
        ):

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                thread = self._thread_from_conn(conn, thread_id)
                if not thread:
                    raise NotFoundError("thread not found", details={"thread_id": thread_id})
                self._check_expected(thread, expected_version)
                if thread["state"] in CLOSED_THREAD_STATES:
                    raise InvalidTransitionError(
                        "cannot post to a closed thread", details={"state": thread["state"]}
                    )
                if int(thread["expires_at_ms"]) <= now:
                    self._expire_thread(conn, thread, now)
                    return {
                        "ok": False,
                        "action": "thread.post",
                        "error": "thread_expired",
                        "thread": self._thread_from_conn(conn, thread_id),
                    }
                if int(thread["rounds"]) >= int(thread["max_rounds"]):
                    self._expire_thread(conn, thread, now, reason="max_rounds")
                    return {
                        "ok": False,
                        "action": "thread.post",
                        "error": "thread_max_rounds",
                        "thread": self._thread_from_conn(conn, thread_id),
                    }
                message_id = _id("msg")
                new_version = int(thread["version"]) + 1
                conn.execute(
                    """
                    INSERT INTO messages(
                        message_id,thread_id,sender,recipient,kind,body,created_at_ms,idempotency_key
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (message_id, thread_id, who, recipient, kind, body, now, key),
                )
                conn.execute(
                    """
                    UPDATE threads
                    SET state='ACTIVE',rounds=rounds+1,version=?,updated_at_ms=?
                    WHERE thread_id=? AND version=?
                    """,
                    (new_version, now, thread_id, thread["version"]),
                )
                if conn.changes() != 1:
                    raise ConflictError("thread changed concurrently")
                event_id = self._append_event(
                    conn,
                    stream_type="thread",
                    stream_id=thread_id,
                    stream_version=new_version,
                    event_type="MessagePosted",
                    actor=who,
                    payload={"message_id": message_id, "kind": kind, "recipient": recipient},
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=thread_id,
                )
                recipients = BRAINS - {who} if recipient == "*" else {recipient}
                for target in sorted(recipients & BRAINS):
                    self._enqueue_notification(
                        conn,
                        recipient=target,
                        topic="thread.message",
                        aggregate_type="thread",
                        aggregate_id=thread_id,
                        payload={
                            "thread_id": thread_id,
                            "message_id": message_id,
                            "event_id": event_id,
                        },
                        now=now,
                    )
                return {
                    "action": "thread.post",
                    "message_id": message_id,
                    "thread": self._thread_from_conn(conn, thread_id),
                }

            result = self._idempotent(
                conn,
                actor=who,
                operation="thread.post",
                key=idempotency_key,
                request=request,
                execute=execute,
            )
        if result.get("error") == "thread_expired":
            raise InvalidTransitionError("thread expired", details={"thread_id": thread_id})
        if result.get("error") == "thread_max_rounds":
            raise InvalidTransitionError("thread reached max_rounds", details={"thread_id": thread_id})
        return result

    def close_thread(
        self,
        *,
        actor: str | Actor,
        thread_id: str,
        decision: str,
        resolution_key: str,
        summary: str,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, DISCUSS_ACTORS, "close a brain discussion")
        if decision not in {"accept", "reject", "each_close", "escalate_to_user"}:
            raise ValidationError("invalid closure decision", details={"decision": decision})
        if not resolution_key.strip() or not summary.strip():
            raise ValidationError("resolution_key and summary are required")
        request = {
            "thread_id": thread_id,
            "decision": decision,
            "resolution_key": resolution_key,
            "summary": summary,
            "expected_version": expected_version,
        }
        with (
            self._tracer.start_as_current_span("coordination.thread.close"),
            self.db.write() as conn,
        ):

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                thread = self._thread_from_conn(conn, thread_id)
                if not thread:
                    raise NotFoundError("thread not found", details={"thread_id": thread_id})
                self._check_expected(thread, expected_version)
                if thread["state"] in CLOSED_THREAD_STATES:
                    raise InvalidTransitionError(
                        "thread is already terminal", details={"state": thread["state"]}
                    )
                if int(thread["expires_at_ms"]) <= now:
                    self._expire_thread(conn, thread, now)
                    return {
                        "ok": False,
                        "action": "thread.close",
                        "error": "thread_expired",
                        "thread": self._thread_from_conn(conn, thread_id),
                    }

                if who == Actor.USER.value:
                    state = {
                        "accept": "ACCEPTED",
                        "reject": "REJECTED",
                        "each_close": "EACH_CLOSED",
                        "escalate_to_user": "ESCALATED",
                    }[decision]
                    reason = f"user_authority:{decision}"
                else:
                    conn.execute(
                        """
                        INSERT INTO closure_votes(
                            thread_id,actor,decision,resolution_key,summary,created_at_ms
                        ) VALUES(?,?,?,?,?,?)
                        ON CONFLICT(thread_id,actor) DO UPDATE SET
                            decision=excluded.decision,
                            resolution_key=excluded.resolution_key,
                            summary=excluded.summary,
                            created_at_ms=excluded.created_at_ms
                        """,
                        (thread_id, who, decision, resolution_key, summary, now),
                    )
                    votes = rows_as_dicts(
                        conn.execute(
                            "SELECT actor,decision,resolution_key FROM closure_votes WHERE thread_id=?",
                            (thread_id,),
                        )
                    )
                    if decision == "reject":
                        state, reason = "REJECTED", f"reject_by:{who}"
                    elif decision == "escalate_to_user":
                        state, reason = "ESCALATED", f"escalate_by:{who}"
                    else:
                        matching = {
                            vote["actor"]
                            for vote in votes
                            if vote["decision"] == decision and vote["resolution_key"] == resolution_key
                        }
                        if matching == BRAINS:
                            state = "ACCEPTED" if decision == "accept" else "EACH_CLOSED"
                            reason = f"mutual_{decision}:{resolution_key}"
                        else:
                            state, reason = "CLOSING", f"awaiting_peer:{decision}"

                new_version = int(thread["version"]) + 1
                conn.execute(
                    """
                    UPDATE threads
                    SET state=?,version=?,updated_at_ms=?,close_resolution_key=?,close_reason=?
                    WHERE thread_id=? AND version=?
                    """,
                    (
                        state,
                        new_version,
                        now,
                        resolution_key,
                        reason,
                        thread_id,
                        thread["version"],
                    ),
                )
                if conn.changes() != 1:
                    raise ConflictError("thread changed concurrently")
                self._append_event(
                    conn,
                    stream_type="thread",
                    stream_id=thread_id,
                    stream_version=new_version,
                    event_type="ThreadClosureRecorded",
                    actor=who,
                    payload={
                        "decision": decision,
                        "resolution_key": resolution_key,
                        "resulting_state": state,
                        "summary": summary,
                    },
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=thread_id,
                )
                for target in sorted(BRAINS - {who}):
                    self._enqueue_notification(
                        conn,
                        recipient=target,
                        topic="thread.closure",
                        aggregate_type="thread",
                        aggregate_id=thread_id,
                        payload={"thread_id": thread_id, "state": state, "decision": decision},
                        now=now,
                    )
                return {"action": "thread.close", "thread": self._thread_from_conn(conn, thread_id)}

            result = self._idempotent(
                conn,
                actor=who,
                operation="thread.close",
                key=idempotency_key,
                request=request,
                execute=execute,
            )
        if result.get("error") == "thread_expired":
            raise InvalidTransitionError("thread expired", details={"thread_id": thread_id})
        return result

    def propose_close(
        self,
        *,
        actor: str | Actor,
        thread_id: str,
        decision_hash: str,
        summary: str,
        decision: str = "accept",
        proposal_id: str | None = None,
        expected_version: int | None = None,
        unresolved_points: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """T5 PROPOSE_CLOSE: first-side closure proposal (decision_hash + optional CAS version).

        Natural-language discuss messages never create Tasks; only explicit promote_to_task does.
        """
        if not decision_hash.strip():
            raise ValidationError("decision_hash is required for propose_close")
        if not summary.strip():
            raise ValidationError("summary is required for propose_close")
        pid = (proposal_id or decision_hash).strip()
        points = list(unresolved_points or [])
        close_summary = summary.strip()
        if points:
            close_summary = f"{close_summary}\n[unresolved]={_canonical(points)}"
        result = self.close_thread(
            actor=actor,
            thread_id=thread_id,
            decision=decision,
            resolution_key=decision_hash.strip(),
            summary=close_summary,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        thread = result.get("thread")
        assert isinstance(thread, dict)
        result["action"] = "thread.propose_close"
        result["proposal_id"] = pid
        result["decision_hash"] = decision_hash.strip()
        result["closure_version"] = int(thread.get("version") or 0)
        result["unresolved_points"] = points
        return result

    def respond(
        self,
        *,
        actor: str | Actor,
        thread_id: str,
        decision_hash: str,
        summary: str,
        decision: str = "accept",
        proposal_id: str | None = None,
        expected_version: int | None = None,
        unresolved_points: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """T5 CLOSE_RESPONSE: peer vote must cite same decision_hash; stale version → ConflictError."""
        if not decision_hash.strip():
            raise ValidationError("decision_hash is required for respond")
        if not summary.strip():
            raise ValidationError("summary is required for respond")
        pid = (proposal_id or decision_hash).strip()
        points = list(unresolved_points or [])
        close_summary = summary.strip()
        if points:
            close_summary = f"{close_summary}\n[unresolved]={_canonical(points)}"
        result = self.close_thread(
            actor=actor,
            thread_id=thread_id,
            decision=decision,
            resolution_key=decision_hash.strip(),
            summary=close_summary,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        thread = result.get("thread")
        assert isinstance(thread, dict)
        result["action"] = "thread.respond"
        result["proposal_id"] = pid
        result["decision_hash"] = decision_hash.strip()
        result["closure_version"] = int(thread.get("version") or 0)
        result["unresolved_points"] = points
        return result

    def _thread_from_conn(self, conn: apsw.Connection, thread_id: str) -> dict[str, Any] | None:
        return _decode_json_fields(
            row_as_dict(conn.execute("SELECT * FROM threads WHERE thread_id=?", (thread_id,)))
        )

    def _expire_thread(
        self,
        conn: apsw.Connection,
        thread: dict[str, Any],
        now: int,
        *,
        reason: str = "ttl",
    ) -> None:
        version = int(thread["version"]) + 1
        conn.execute(
            """
            UPDATE threads SET state='EXPIRED',version=?,updated_at_ms=?,close_reason=?
            WHERE thread_id=? AND version=?
            """,
            (version, now, reason, thread["thread_id"], thread["version"]),
        )
        if conn.changes() == 1:
            self._append_event(
                conn,
                stream_type="thread",
                stream_id=thread["thread_id"],
                stream_version=version,
                event_type="ThreadExpired",
                actor="system",
                payload={"reason": reason},
                occurred_at_ms=now,
                correlation_id=thread["thread_id"],
            )

    def get_thread(self, thread_id: str, *, message_limit: int = 100) -> dict[str, object]:
        with self.db.read() as conn:
            thread = self._thread_from_conn(conn, thread_id)
            if not thread:
                raise NotFoundError("thread not found", details={"thread_id": thread_id})
            messages = rows_as_dicts(
                conn.execute(
                    """
                    SELECT message_id,thread_id,sender,recipient,kind,body,created_at_ms
                    FROM messages WHERE thread_id=?
                    ORDER BY created_at_ms,message_id LIMIT ?
                    """,
                    (thread_id, message_limit),
                )
            )
            votes = rows_as_dicts(
                conn.execute(
                    """
                    SELECT actor,decision,resolution_key,summary,created_at_ms
                    FROM closure_votes WHERE thread_id=? ORDER BY actor
                    """,
                    (thread_id,),
                )
            )
        return {"ok": True, "thread": thread, "messages": messages, "closure_votes": votes}

    def list_threads(self, *, state: str | None = None, limit: int = 100) -> dict[str, object]:
        sql = "SELECT * FROM threads"
        bindings: tuple[object, ...] = ()
        if state:
            sql += " WHERE state=?"
            bindings = (state,)
        sql += " ORDER BY updated_at_ms DESC LIMIT ?"
        bindings += (limit,)
        rows = [_decode_json_fields(row) for row in self.db.execute_read(sql, bindings)]
        return {"ok": True, "count": len(rows), "threads": rows}

    def _read_meta(self, conn: apsw.Connection, key: str) -> str | None:
        row = row_as_dict(conn.execute("SELECT value FROM meta WHERE key=?", (key,)))
        return None if row is None else str(row["value"])

    def _write_meta(self, conn: apsw.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def stop_status(self) -> dict[str, object]:
        with self.db.read() as conn:
            active = self._read_meta(conn, "stop.active") == "1"
            return {
                "ok": True,
                "action": "stop.status",
                "active": active,
                "epoch": int(self._read_meta(conn, "stop.epoch") or "0"),
                "reason": self._read_meta(conn, "stop.reason"),
                "actor": self._read_meta(conn, "stop.actor"),
                "at_ms": int(self._read_meta(conn, "stop.at_ms") or "0"),
                "scope": self._read_meta(conn, "stop.scope") or "global",
            }

    def mbg_status(self) -> dict[str, object]:
        """T8 M-BG policy surface: enabled, never auto_dispatch, stop preempts."""
        from .agent_operations import AgentOperationStore
        from .m_bg import count_active_operations, m_bg_policy

        policy = m_bg_policy()
        store = AgentOperationStore(self.db.path)
        in_flight = count_active_operations(store)
        stop = self.stop_status()
        return {
            "ok": True,
            "action": "mbg.status",
            "policy": policy,
            "in_flight_operations": in_flight,
            "capacity_remaining": max(0, int(policy["max_parallel"]) - in_flight),
            "stop_active": bool(stop.get("active")),
            "auto_dispatch": False,
            "temporal_owner": False,
        }

    def mkeep_status(self) -> dict[str, object]:
        """T10 read-only capability status; never starts a timer or process."""
        from .m_keep import m_keep_policy

        return {"ok": True, "action": "mkeep.status", "policy": m_keep_policy()}

    def mkeep_observe(
        self,
        *,
        snapshot: dict[str, Any],
        binding: dict[str, Any] | None = None,
        expected_binding: dict[str, Any] | None = None,
        pause_active: bool = False,
    ) -> dict[str, object]:
        """Classify one supplied snapshot; live-session recovery is intentionally absent."""
        from .m_keep import observe_snapshot

        return observe_snapshot(
            snapshot,
            binding=binding,
            expected_binding=expected_binding,
            stop_active=bool(self.stop_status().get("active")),
            pause_active=pause_active,
        )

    def mbg_dispatch(
        self,
        *,
        actor: str | Actor,
        task_id: str,
        session_name: str | None = None,
        cwd: str | Path | None = None,
        deadline_seconds: int = 1_800,
        max_attempts: int = 1,
        idempotency_key: str | None = None,
        start_transport: bool = False,
    ) -> dict[str, object]:
        """Explicit M-BG invoke: promoted Task → agent_operation queue (submit only by default).

        Does not auto-dispatch. Does not own Temporal. start_transport requires experimental flag.
        """
        from .agent_controller import AgentOperationController
        from .agent_operations import AgentOperationStore
        from .m_bg import (
            allocate_task_scratch,
            assert_may_dispatch,
            build_operation_prompt,
            count_active_operations,
            m_bg_policy,
        )

        who = _actor(actor)
        self._require_actor(who, TASK_DISPATCHERS, "M-BG dispatch")
        policy = m_bg_policy()
        if not policy.get("enabled"):
            raise InvalidTransitionError("M-BG policy disabled")
        if policy.get("auto_dispatch"):
            # belt: policy hard-codes false; never silent auto path
            raise InvalidTransitionError("M-BG auto_dispatch must remain false")

        task_view = self.get_task(task_id)
        task = task_view["task"]
        assert isinstance(task, dict)
        store = AgentOperationStore(self.db.path)
        in_flight = count_active_operations(store)
        stop = self.stop_status()
        assert_may_dispatch(
            stop_active=bool(stop.get("active")),
            task=task,
            in_flight=in_flight,
            max_parallel=int(policy["max_parallel"]),
        )

        key = (idempotency_key or f"mbg-{task_id}").strip()
        session = (session_name or f"mbg-{task_id}").strip()

        if cwd:
            workdir = str(Path(cwd).resolve())
            scratch = None
        else:
            scratch_path = allocate_task_scratch(task_id)
            workdir = str(scratch_path)
            scratch = workdir
        prompt = build_operation_prompt(task)
        meta = {
            "m_bg": True,
            "task_id": task_id,
            "auto_dispatch": False,
            "require_explicit_promote": True,
            "worktree_path": scratch,
            "decision_hash": (task.get("metadata") or {}).get("decision_hash")
            if isinstance(task.get("metadata"), dict)
            else None,
        }

        if start_transport:
            flag = os.environ.get("XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS", "").strip().lower()
            if flag not in {"1", "true", "yes"}:
                raise ValidationError(
                    "start_transport requires XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS=1",
                    details={"start_transport": True},
                )
            controller = AgentOperationController(self.db.path)
            submitted = controller.store.submit(
                actor=who if who in {"user", "codex"} else "codex",
                prompt=prompt,
                session_name=session,
                cwd=workdir,
                deadline_seconds=deadline_seconds,
                max_attempts=max_attempts,
                replay_safe=True,
                idempotency_key=key,
                metadata=meta,
            )
            # do not call ensure_transport/start in canary default — optional path only when flag set
            started = None
            if flag in {"1", "true", "yes"} and start_transport:
                try:
                    op = submitted.get("operation") or {}
                    op_id = str(op.get("operation_id") or "")
                    if op_id and not submitted.get("replayed"):
                        started = controller.start(op_id)
                except Exception as exc:  # pragma: no cover - transport optional
                    started = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
            return {
                "ok": True,
                "action": "mbg.dispatch",
                "policy": policy,
                "task_id": task_id,
                "operation": submitted.get("operation"),
                "replayed": submitted.get("replayed"),
                "started": started,
                "auto_dispatch": False,
            }

        # Default: queue operation only (T7 headless envelope durable), no process spawn
        submit_actor = who if who in {"user", "codex"} else "codex"
        submitted = store.submit(
            actor=submit_actor,
            prompt=prompt,
            session_name=session,
            cwd=workdir,
            deadline_seconds=deadline_seconds,
            max_attempts=max_attempts,
            replay_safe=True,
            idempotency_key=key,
            metadata=meta,
        )
        operation = submitted.get("operation")
        assert isinstance(operation, dict)
        op_id = str(operation.get("operation_id") or "")
        bind = self._bind_task_to_mbg_operation(
            task_id=task_id,
            operation_id=op_id,
            workdir=workdir,
            lease_seconds=max(60, min(deadline_seconds, 3600)),
            store=store,
            replayed=bool(submitted.get("replayed")),
        )
        return {
            "ok": True,
            "action": "mbg.dispatch",
            "policy": policy,
            "task_id": task_id,
            "operation": operation,
            "task": bind.get("task"),
            "lease_token": bind.get("lease_token"),
            "operation_lease_token": bind.get("operation_lease_token"),
            "control_epoch": bind.get("control_epoch"),
            "replayed": submitted.get("replayed"),
            "started": None,
            "spawned": False,
            "auto_dispatch": False,
            "note_cn": "operation 已登记并绑定 Task 租约(running)；未起 transport/Temporal",
        }

    def _bind_task_to_mbg_operation(
        self,
        *,
        task_id: str,
        operation_id: str,
        workdir: str,
        lease_seconds: int,
        store: Any,
        replayed: bool,
    ) -> dict[str, object]:
        """Bind promoted Task → M-BG operation under one lease-owned running state."""
        if not operation_id:
            raise ValidationError("operation_id required to bind M-BG task")
        worker_id = f"mbg:{operation_id[:16]}"

        # Read first (no nested write with store.claim)
        peek = self.get_task(task_id)["task"]
        assert isinstance(peek, dict)
        peek_meta = dict(peek.get("metadata") or {})
        if peek_meta.get("m_bg_operation_id") == operation_id and peek.get("lease_token"):
            return {
                "task": peek,
                "lease_token": peek.get("lease_token"),
                "operation_lease_token": peek_meta.get("m_bg_op_lease_token"),
                "control_epoch": peek_meta.get("m_bg_op_control_epoch"),
                "replayed_bind": True,
            }

        op_lease_token: str | None = peek_meta.get("m_bg_op_lease_token")  # type: ignore[assignment]
        op_epoch: int | None = peek_meta.get("m_bg_op_control_epoch")  # type: ignore[assignment]
        if not op_lease_token:
            # claim outside task write to avoid nested APSW write on same DB
            claimed = store.claim(operation_id, worker_id=worker_id, lease_seconds=lease_seconds)
            op_lease_token = str(claimed.get("lease_token") or "")
            op_epoch = int(claimed.get("control_epoch") or 0)

        with self.db.write() as conn:
            task = self._task_from_conn(conn, task_id)
            if not task:
                raise NotFoundError("task not found", details={"task_id": task_id})
            meta = dict(task.get("metadata") or {})
            if meta.get("m_bg_operation_id") == operation_id and task.get("lease_token"):
                return {
                    "task": task,
                    "lease_token": task.get("lease_token"),
                    "operation_lease_token": meta.get("m_bg_op_lease_token"),
                    "control_epoch": meta.get("m_bg_op_control_epoch"),
                    "replayed_bind": True,
                }
            if task["state"] not in {"queued", "leased", "running"}:
                raise InvalidTransitionError(
                    "task state not bindable for M-BG",
                    details={"state": task["state"], "task_id": task_id},
                )
            now = self.now_ms()
            task_token = str(task.get("lease_token") or _id("lease"))
            meta.update(
                {
                    "m_bg": True,
                    "m_bg_bound": True,
                    "m_bg_operation_id": operation_id,
                    "m_bg_worker_id": worker_id,
                    "worktree_path": workdir,
                    "m_bg_op_lease_token": op_lease_token,
                    "m_bg_op_control_epoch": op_epoch,
                }
            )
            version = int(task["version"]) + 1
            conn.execute(
                """
                UPDATE tasks SET state='running',lease_owner=?,lease_token=?,lease_expires_at_ms=?,
                    attempt_count=CASE WHEN state='queued' THEN attempt_count+1 ELSE attempt_count END,
                    version=?,updated_at_ms=?,metadata_json=?
                WHERE task_id=? AND version=?
                """,
                (
                    worker_id,
                    task_token,
                    now + lease_seconds * 1_000,
                    version,
                    now,
                    _canonical(meta),
                    task_id,
                    task["version"],
                ),
            )
            if conn.changes() != 1:
                raise ConflictError("task changed while binding M-BG operation")
            self._append_event(
                conn,
                stream_type="task",
                stream_id=task_id,
                stream_version=version,
                event_type="TaskMbgBound",
                actor="system",
                payload={
                    "operation_id": operation_id,
                    "worker_id": worker_id,
                    "worktree_path": workdir,
                },
                occurred_at_ms=now,
                correlation_id=task.get("context_id"),
            )
            bound = self._task_from_conn(conn, task_id)
            return {
                "task": bound,
                "lease_token": task_token,
                "operation_lease_token": op_lease_token,
                "control_epoch": op_epoch,
                "replayed_bind": False,
            }

    def mbg_finish(
        self,
        *,
        actor: str | Actor = Actor.ADMIN,
        task_id: str,
        lease_token: str,
        result_summary: str,
        evidence: list[dict[str, object]] | None = None,
        success: bool = True,
        error: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """Close M-BG bound Task (+ operation if still leased). Admin worker face."""
        from .agent_operations import AgentOperationStore

        who = _actor(actor)
        self._require_actor(who, {Actor.ADMIN.value}, "finish M-BG task")
        task_view = self.get_task(task_id)
        task = task_view["task"]
        assert isinstance(task, dict)
        meta = dict(task.get("metadata") or {})
        op_id = str(meta.get("m_bg_operation_id") or "")
        op_lease = str(meta.get("m_bg_op_lease_token") or "")
        op_epoch = int(meta.get("m_bg_op_control_epoch") or 0)
        evidence_list = evidence or [{"kind": "mbg_finish", "note": result_summary.strip() or "mbg finish"}]
        if success:
            finished = self.complete_task(
                actor=who,
                task_id=task_id,
                lease_token=lease_token,
                result_summary=result_summary,
                evidence=evidence_list,
                idempotency_key=idempotency_key,
            )
            outcome = "completed"
        else:
            finished = self.fail_task(
                actor=who,
                task_id=task_id,
                lease_token=lease_token,
                error=error or result_summary or "mbg failed",
                retryable=False,
                idempotency_key=idempotency_key,
            )
            outcome = "failed"
        op_finish: dict[str, object] | None = None
        if op_id and op_lease:
            try:
                store = AgentOperationStore(self.db.path)
                op_finish = store.finish(
                    op_id,
                    lease_token=op_lease,
                    control_epoch=op_epoch,
                    outcome=outcome,  # type: ignore[arg-type]
                    stop_reason="mbg_finish",
                    result_text=result_summary if success else None,
                    error=None if success else (error or result_summary),
                )
            except Exception as exc:
                op_finish = {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "note_cn": "Task 已闭合；operation finish 可选失败不回滚 Task",
                }
        return {
            "ok": True,
            "action": "mbg.finish",
            "task": finished.get("task"),
            "operation_finish": op_finish,
            "outcome": outcome,
            "verification_status": finished.get("verification_status")
            or "evidence_attached_not_independently_verified",
        }

    def temporal_status(self) -> dict[str, object]:
        """T9 Temporal policy surface: promoted-only, never auto-start, not governance owner."""
        from .m_bg import m_bg_policy
        from .temporal.client import TemporalClient, describe_promoted_queue
        from .temporal.policy import temporal_policy

        policy = temporal_policy()
        mbg = m_bg_policy()
        client = TemporalClient.from_policy(policy)
        queue = describe_promoted_queue(client)
        connectivity = queue.get("connectivity")
        if not isinstance(connectivity, dict):
            connectivity = client.connectivity_probe()
        if not policy.get("enabled"):
            mode = "disabled"
        elif policy.get("live_connect"):
            mode = "live"
        else:
            mode = "mock"
        raw_pollers = queue.get("poller_count", queue.get("pollers", 0))
        try:
            poller_count = int(raw_pollers)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            poller_count = 0
        stop = self.stop_status()
        return {
            "ok": True,
            "action": "temporal.status",
            "mode": mode,
            "live_connect": bool(policy.get("live_connect")),
            "connectivity": connectivity,
            "poller_count": poller_count,
            "policy": policy,
            "mbg_temporal_owner": bool(mbg.get("temporal_owner")),
            "auto_start_on_promote": False,
            "promoted_queue": queue,
            "stop_active": bool(stop.get("active")),
            "note_cn": "仅显式 temporal-start-promoted；chat/discuss 永不自动进 Temporal",
        }

    def temporal_start_promoted(
        self,
        *,
        actor: str | Actor,
        task_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """Explicit T9 invoke: promoted Task → Temporal workflow (mock or live)."""
        from .temporal.client import TemporalClient
        from .temporal.envelope import envelope_from_kernel_task
        from .temporal.policy import temporal_policy

        who = _actor(actor)
        self._require_actor(who, TASK_DISPATCHERS, "start promoted Temporal workflow")
        policy = temporal_policy()
        if not policy.get("enabled"):
            raise InvalidTransitionError("Temporal adapter disabled (XINAO_TEMPORAL_ENABLED=0)")
        if policy.get("auto_start_on_promote"):
            raise InvalidTransitionError("auto_start_on_promote must remain false")

        task_view = self.get_task(task_id)
        task = task_view["task"]
        assert isinstance(task, dict)
        stop = self.stop_status()
        if stop.get("active"):
            raise InvalidTransitionError(
                "stop is active; Temporal start preempted",
                details={"stop_preempts": True},
            )

        envelope = envelope_from_kernel_task(
            task,
            workflow_type=str(policy["workflow_type"]),
            task_queue=str(policy["task_queue"]),
        )
        request = {
            "task_id": task_id,
            "workflow_id": envelope.workflow_id,
            "generation": envelope.generation,
        }

        with self.db.write() as conn:

            def _execute(key: str) -> dict[str, object]:
                meta = dict(task.get("metadata") or {})
                if meta.get("temporal_workflow_id") == envelope.workflow_id and meta.get(
                    "temporal_started_at_ms"
                ):
                    return {
                        "ok": True,
                        "action": "temporal.start_promoted",
                        "task_id": task_id,
                        "workflow_id": envelope.workflow_id,
                        "workflow_type": envelope.workflow_type,
                        "task_queue": envelope.task_queue,
                        "generation": envelope.generation,
                        "immutable_intent_hash": envelope.immutable_intent_hash,
                        "mode": meta.get("temporal_mode") or "recorded",
                        "run_id": meta.get("temporal_run_id"),
                        "replayed": True,
                        "auto_start_on_promote": False,
                    }

                client = TemporalClient.from_policy(policy)
                started = client.start_promoted_workflow(envelope)
                now = self.now_ms()
                version = int(task.get("version") or 0) + 1
                lease_owner = f"temporal:{envelope.workflow_id}"[:240]
                lease_expires_at_ms = now + 60 * 60 * 1_000
                attempt_no = int(task.get("attempt_count") or 0) + 1
                meta.update(
                    {
                        "temporal_workflow_id": envelope.workflow_id,
                        "temporal_run_id": started.get("run_id"),
                        "temporal_mode": started.get("mode"),
                        "temporal_started_at_ms": now,
                        "temporal_started_by": who,
                        "temporal_kernel_lease_token": envelope.kernel_lease_token,
                    }
                )
                conn.execute(
                    """
                    UPDATE tasks SET metadata_json=?,state='running',lease_owner=?,
                        lease_token=?,lease_expires_at_ms=?,attempt_count=attempt_count+1,
                        updated_at_ms=?,version=?
                    WHERE task_id=? AND state='queued' AND version=?
                    """,
                    (
                        _canonical(meta),
                        lease_owner,
                        envelope.kernel_lease_token,
                        lease_expires_at_ms,
                        now,
                        version,
                        task_id,
                        int(task.get("version") or 0),
                    ),
                )
                if conn.changes() != 1:
                    raise ConflictError(
                        "task version changed during Temporal start",
                        details={"task_id": task_id},
                    )
                attempt_id = self._open_task_attempt(
                    conn,
                    task_id=task_id,
                    attempt_no=attempt_no,
                    worker_id=lease_owner,
                    lease_token=envelope.kernel_lease_token,
                    now=now,
                    lease_expires_at_ms=lease_expires_at_ms,
                )
                self._update_task_attempt_by_lease(
                    conn,
                    lease_token=envelope.kernel_lease_token,
                    now=now,
                    state="running",
                )
                self._append_event(
                    conn,
                    stream_type="task",
                    stream_id=task_id,
                    stream_version=version,
                    event_type="TemporalWorkflowStarted",
                    actor=who,
                    payload={
                        "workflow_id": envelope.workflow_id,
                        "workflow_type": envelope.workflow_type,
                        "task_queue": envelope.task_queue,
                        "generation": envelope.generation,
                        "mode": started.get("mode"),
                        "kernel_state": "running",
                        "lease_owner": lease_owner,
                        "attempt_id": attempt_id,
                    },
                    occurred_at_ms=now,
                    idempotency_key=f"{key}:event",
                    correlation_id=str(task.get("context_id") or task_id),
                )
                return {
                    "ok": True,
                    "action": "temporal.start_promoted",
                    "task_id": task_id,
                    "workflow_id": envelope.workflow_id,
                    "workflow_type": envelope.workflow_type,
                    "task_queue": envelope.task_queue,
                    "generation": envelope.generation,
                    "immutable_intent_hash": envelope.immutable_intent_hash,
                    "mode": started.get("mode"),
                    "run_id": started.get("run_id"),
                    "kernel_state": "running",
                    "lease_owner": lease_owner,
                    "auto_start_on_promote": False,
                    "replayed": bool(started.get("replayed")),
                }

            return self._idempotent(
                conn,
                actor=who,
                operation="temporal.start_promoted",
                key=idempotency_key or f"temporal-{envelope.workflow_id}",
                request=request,
                execute=_execute,
            )

    def user_stop(
        self,
        *,
        actor: str | Actor = Actor.USER,
        reason: str,
        scope: str = "global",
        idempotency_key: str | None = None,
        cancel_active_tasks: bool = True,
    ) -> dict[str, object]:
        """User-preemptive stop: block new dispatches and freeze active tasks.

        Stop does not auto-resume. clear_stop is a separate explicit call.
        """
        who = _actor(actor)
        self._require_actor(who, {Actor.USER.value, *BRAINS}, "raise stop")
        if not reason.strip():
            raise ValidationError("stop reason is required")
        if scope != "global":
            raise ValidationError(
                "scoped Stop is not implemented; use global rather than implying partial isolation",
                details={"scope": scope},
            )
        request = {"reason": reason, "scope": scope, "cancel_active_tasks": cancel_active_tasks}
        with (
            self._tracer.start_as_current_span("coordination.stop.raise"),
            self.db.write() as conn,
        ):

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                epoch = int(self._read_meta(conn, "stop.epoch") or "0") + 1
                self._write_meta(conn, "stop.active", "1")
                self._write_meta(conn, "stop.epoch", str(epoch))
                self._write_meta(conn, "stop.reason", reason.strip())
                self._write_meta(conn, "stop.actor", who)
                self._write_meta(conn, "stop.at_ms", str(now))
                self._write_meta(conn, "stop.scope", scope)
                canceled: list[str] = []
                temporal_workflows: list[dict[str, str]] = []
                agent_operations: list[dict[str, str]] = []
                if cancel_active_tasks:
                    rows = rows_as_dicts(
                        conn.execute(
                            """
                            SELECT task_id,version,control_epoch,context_id,state,metadata_json,
                                lease_owner,lease_token
                            FROM tasks
                            WHERE state IN ('queued','leased','running','paused')
                            ORDER BY task_id
                            """
                        )
                    )
                    for task in rows:
                        decoded = _decode_json_fields(task) or {}
                        metadata = decoded.get("metadata")
                        if not isinstance(metadata, dict):
                            metadata = {}
                        workflow_id = str(metadata.get("temporal_workflow_id") or "")
                        if workflow_id and str(metadata.get("temporal_mode") or "") == "live":
                            temporal_workflows.append(
                                {
                                    "task_id": str(task["task_id"]),
                                    "workflow_id": workflow_id,
                                    "run_id": str(metadata.get("temporal_run_id") or ""),
                                    "generation": str(task.get("control_epoch") or 0),
                                }
                            )
                        operation_id = str(metadata.get("m_bg_operation_id") or "")
                        if operation_id:
                            agent_operations.append(
                                {
                                    "task_id": str(task["task_id"]),
                                    "operation_id": operation_id,
                                    "lease_token": str(metadata.get("m_bg_op_lease_token") or ""),
                                }
                            )
                        version = int(task["version"]) + 1
                        conn.execute(
                            """
                            UPDATE tasks SET state='canceled',lease_owner=NULL,lease_token=NULL,
                                lease_expires_at_ms=NULL,control_epoch=control_epoch+1,
                                version=?,updated_at_ms=?,failure_reason=?
                            WHERE task_id=? AND version=?
                            """,
                            (
                                version,
                                now,
                                f"user_stop:{reason.strip()}",
                                task["task_id"],
                                task["version"],
                            ),
                        )
                        if conn.changes() != 1:
                            continue
                        self._cancel_open_task_attempts(
                            conn,
                            task_id=str(task["task_id"]),
                            now=now,
                            reason=f"user_stop:{reason.strip()}",
                        )
                        self._append_event(
                            conn,
                            stream_type="task",
                            stream_id=task["task_id"],
                            stream_version=version,
                            event_type="TaskCanceled",
                            actor=who,
                            payload={
                                "reason": f"user_stop:{reason.strip()}",
                                "stop_epoch": epoch,
                                "previous_state": task["state"],
                            },
                            occurred_at_ms=now,
                            correlation_id=task["context_id"],
                        )
                        canceled.append(str(task["task_id"]))
                self._append_event(
                    conn,
                    stream_type="system",
                    stream_id="stop",
                    stream_version=epoch,
                    event_type="UserStopRaised",
                    actor=who,
                    payload={"reason": reason.strip(), "scope": scope, "canceled": canceled},
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=f"stop-epoch-{epoch}",
                )
                # Mirror a human-readable stop flag under the canary stop dir when present.
                stop_dir = Path(
                    os.environ.get(
                        "XINAO_COORD_STOP_DIR",
                        r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\stop",
                    )
                )
                try:
                    stop_dir.mkdir(parents=True, exist_ok=True)
                    (stop_dir / "global.json").write_text(
                        _canonical(
                            {
                                "active": True,
                                "epoch": epoch,
                                "reason": reason.strip(),
                                "actor": who,
                                "at_ms": now,
                                "scope": scope,
                                "canceled_tasks": canceled,
                            }
                        ),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
                return {
                    "action": "stop.raise",
                    "active": True,
                    "epoch": epoch,
                    "reason": reason.strip(),
                    "scope": scope,
                    "canceled_tasks": canceled,
                    "temporal_workflows": temporal_workflows,
                    "agent_operations": agent_operations,
                    "resumes_automatically": False,
                }

            result = self._idempotent(
                conn,
                actor=who,
                operation="stop.raise",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

        temporal_requests: list[dict[str, object]] = []
        recorded = result.get("temporal_workflows")
        if isinstance(recorded, list):
            from .temporal.client import TemporalClient
            from .temporal.policy import temporal_policy

            policy = temporal_policy()
            client = TemporalClient(
                address=str(policy.get("address") or "127.0.0.1:7233"),
                namespace=str(policy.get("namespace") or "default"),
                task_queue=str(policy.get("task_queue") or "xinao-dualbrain-promoted-v1"),
                workflow_type=str(policy.get("workflow_type") or "XinaoPromotedTaskWorkflowV1"),
                mock_mode=False,
                live_connect=True,
            )
            items = [item for item in recorded if isinstance(item, dict)]

            def cancel_one(item: dict[str, object]) -> dict[str, object]:
                workflow_id = str(item.get("workflow_id") or "")
                run_id = str(item.get("run_id") or "")
                if not run_id:
                    return {
                        "ok": False,
                        "workflow_id": workflow_id,
                        "run_id": "",
                        "terminal_confirmed": False,
                        "error_type": "TemporalRunIdentityMissing",
                        "message": "recorded live workflow has no run_id; cancellation stayed read-only",
                    }
                try:
                    return client.request_cancel_promoted_workflow(
                        workflow_id,
                        run_id=run_id,
                        reason=f"user_stop:{reason.strip()}",
                    )
                except Exception as exc:
                    return {
                        "ok": False,
                        "workflow_id": workflow_id,
                        "run_id": run_id,
                        "terminal_confirmed": False,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:400],
                    }

            if items:
                width = min(len(items), max(1, (os.cpu_count() or 1) * 2))
                ordered: list[dict[str, object] | None] = [None] * len(items)
                with ThreadPoolExecutor(max_workers=width) as pool:
                    futures = {pool.submit(cancel_one, item): index for index, item in enumerate(items)}
                    for future in as_completed(futures):
                        ordered[futures[future]] = future.result()
                temporal_requests.extend(item for item in ordered if item is not None)

            stop_epoch = int(result.get("epoch") or 0)
            if temporal_requests:
                with self.db.write() as conn:
                    for item in temporal_requests:
                        workflow_id = str(item.get("workflow_id") or "")
                        run_id = str(item.get("run_id") or "")
                        confirmed = item.get("terminal_confirmed") is True
                        stream_id = f"stop-temporal:{workflow_id}:{run_id}"
                        event_type = "TemporalCancelConfirmed" if confirmed else "TemporalCancelUnconfirmed"
                        event_payload = {
                            "stop_epoch": stop_epoch,
                            "workflow_id": workflow_id,
                            "run_id": run_id,
                            "terminal_confirmed": confirmed,
                            "status_after": item.get("status_after"),
                            "error_type": item.get("error_type"),
                        }
                        previous = row_as_dict(
                            conn.execute(
                                """
                                SELECT stream_version,event_type,payload_json
                                FROM events
                                WHERE stream_type='system' AND stream_id=?
                                ORDER BY stream_version DESC LIMIT 1
                                """,
                                (stream_id,),
                            )
                        )
                        if (
                            previous is not None
                            and previous["event_type"] == event_type
                            and previous["payload_json"] == _canonical(event_payload)
                        ):
                            continue
                        stream_version = int(previous["stream_version"]) + 1 if previous is not None else 1
                        self._append_event(
                            conn,
                            stream_type="system",
                            stream_id=stream_id,
                            stream_version=stream_version,
                            event_type=event_type,
                            actor=who,
                            payload=event_payload,
                            occurred_at_ms=self.now_ms(),
                            idempotency_key=(
                                f"stop-temporal:{stop_epoch}:{workflow_id}:{run_id}:{stream_version}"
                            ),
                            correlation_id=f"stop-epoch-{stop_epoch}",
                        )
        result["temporal_cancel_requests"] = temporal_requests
        result["temporal_cancel_all_ok"] = all(
            item.get("ok") is True and item.get("terminal_confirmed") is True for item in temporal_requests
        )
        agent_requests: list[dict[str, object]] = []
        recorded_operations = result.get("agent_operations")
        if isinstance(recorded_operations, list):
            from .agent_operations import TERMINAL_STATES, AgentOperationStore
            from .agent_worker import finish_cancel_before_start

            store = AgentOperationStore(self.db.path, clock_ms=self._clock_ms)
            for item in recorded_operations:
                if not isinstance(item, dict):
                    continue
                operation_id = str(item.get("operation_id") or "")
                try:
                    requested = store.request_cancel(
                        operation_id,
                        actor="user" if who == Actor.USER.value else "codex",
                        reason=f"user_stop:{reason.strip()}",
                    )
                    operation = requested.get("operation")
                    lease_token = str(item.get("lease_token") or "")
                    if (
                        isinstance(operation, dict)
                        and operation.get("state") == "cancel_requested"
                        and operation.get("collector_pid") is None
                        and lease_token
                    ):
                        finish_cancel_before_start(store, operation_id, lease_token)
                        operation = store.get(operation_id).get("operation")
                        requested = {
                            **requested,
                            "operation": operation,
                            "consumed_before_transport_start": True,
                        }
                    state = str(operation.get("state") or "") if isinstance(operation, dict) else ""
                    agent_requests.append(
                        {
                            **requested,
                            "operation_id": operation_id,
                            "terminal_or_requested": state in TERMINAL_STATES or state == "cancel_requested",
                        }
                    )
                except Exception as exc:
                    agent_requests.append(
                        {
                            "ok": False,
                            "operation_id": operation_id,
                            "error_type": type(exc).__name__,
                            "message": str(exc)[:400],
                            "terminal_or_requested": False,
                        }
                    )
        result["agent_cancel_requests"] = agent_requests
        result["agent_cancel_all_ok"] = all(
            item.get("ok") is True and item.get("terminal_or_requested") is True for item in agent_requests
        )
        return result

    def clear_stop(
        self,
        *,
        actor: str | Actor = Actor.USER,
        reason: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """Explicit clear only — Stop never auto-resumes after raise."""
        who = _actor(actor)
        self._require_actor(who, {Actor.USER.value}, "clear stop")
        if not reason.strip():
            raise ValidationError("clear_stop reason is required")
        request = {"reason": reason}
        with (
            self._tracer.start_as_current_span("coordination.stop.clear"),
            self.db.write() as conn,
        ):

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                epoch = int(self._read_meta(conn, "stop.epoch") or "0")
                self._write_meta(conn, "stop.active", "0")
                self._write_meta(conn, "stop.clear_reason", reason.strip())
                self._write_meta(conn, "stop.clear_actor", who)
                self._write_meta(conn, "stop.clear_at_ms", str(now))
                self._append_event(
                    conn,
                    stream_type="system",
                    stream_id="stop",
                    stream_version=max(epoch, 1) + 1_000_000,
                    event_type="UserStopCleared",
                    actor=who,
                    payload={"reason": reason.strip(), "previous_epoch": epoch},
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=f"stop-epoch-{epoch}",
                )
                stop_dir = Path(
                    os.environ.get(
                        "XINAO_COORD_STOP_DIR",
                        r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\stop",
                    )
                )
                try:
                    stop_dir.mkdir(parents=True, exist_ok=True)
                    (stop_dir / "global.json").write_text(
                        _canonical(
                            {
                                "active": False,
                                "epoch": epoch,
                                "cleared_by": who,
                                "clear_reason": reason.strip(),
                                "at_ms": now,
                            }
                        ),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
                return {
                    "action": "stop.clear",
                    "active": False,
                    "epoch": epoch,
                    "reason": reason.strip(),
                }

            return self._idempotent(
                conn,
                actor=who,
                operation="stop.clear",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def promote_to_task(
        self,
        *,
        actor: str | Actor,
        source_thread_id: str,
        decision_hash: str,
        title: str,
        goal: str,
        owner: str = "admin",
        writer_scope: str = "default",
        acceptance: str | None = None,
        budget: str | None = None,
        stop_scope: str = "global",
        priority: int = 100,
        max_attempts: int = 3,
        task_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Explicit promote gate: only from accepted/closed consensus, never from chat alone.

        decision_hash must match the thread close_resolution_key (or be provided as the
        accepted resolution key). Admin cannot promote. Stop blocks new promotes.
        """
        who = _actor(actor)
        self._require_actor(who, TASK_DISPATCHERS, "promote a thread to task")
        if owner != Actor.ADMIN.value:
            raise ValidationError(
                "promoted tasks are assigned only to admin workers",
                details={"owner": owner},
            )
        if not decision_hash.strip():
            raise ValidationError("decision_hash is required for promote_to_task")
        if not source_thread_id.strip():
            raise ValidationError("source_thread_id is required for promote_to_task")

        thread_view = self.get_thread(source_thread_id)
        thread = thread_view["thread"]
        assert isinstance(thread, dict)
        if thread["state"] != "ACCEPTED":
            raise InvalidTransitionError(
                "promote_to_task requires ACCEPTED thread; chat does not auto-promote",
                details={"thread_state": thread["state"], "thread_id": source_thread_id},
            )
        resolution = str(thread.get("close_resolution_key") or "")
        if resolution != decision_hash.strip():
            raise ConflictError(
                "decision_hash does not match accepted close_resolution_key (CAS/version gate)",
                details={
                    "expected_decision_hash": resolution,
                    "provided": decision_hash.strip(),
                    "thread_id": source_thread_id,
                    "thread_version": thread.get("version"),
                },
            )

        meta = dict(metadata or {})
        meta.update(
            {
                "promoted": True,
                "decision_hash": decision_hash.strip(),
                "owner": owner,
                "writer_scope": writer_scope,
                "acceptance": acceptance,
                "budget": budget,
                "stop_scope": stop_scope,
            }
        )
        result = self.dispatch_task(
            actor=who,
            title=title,
            goal=goal,
            source_thread_id=source_thread_id,
            explicit_non_consensus=False,
            priority=priority,
            max_attempts=max_attempts,
            task_id=task_id,
            idempotency_key=idempotency_key,
            metadata=meta,
        )
        result["action"] = "task.promote"
        result["decision_hash"] = decision_hash.strip()
        result["promoted_from"] = source_thread_id
        return result

    def dispatch_task(
        self,
        *,
        actor: str | Actor,
        title: str,
        goal: str,
        source_thread_id: str | None = None,
        explicit_non_consensus: bool = False,
        priority: int = 100,
        max_attempts: int = 3,
        available_at_ms: int | None = None,
        task_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, TASK_DISPATCHERS, "dispatch an Admin task")
        if not title.strip() or not goal.strip():
            raise ValidationError("task title and goal must not be empty")
        if max_attempts <= 0:
            raise ValidationError("max_attempts must be positive")
        request = {
            "task_id": task_id,
            "title": title,
            "goal": goal,
            "source_thread_id": source_thread_id,
            "explicit_non_consensus": explicit_non_consensus,
            "priority": priority,
            "max_attempts": max_attempts,
            "available_at_ms": available_at_ms,
            "metadata": metadata or {},
        }
        with (
            self._tracer.start_as_current_span("coordination.task.dispatch"),
            self.db.write() as conn,
        ):

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                if self._read_meta(conn, "stop.active") == "1":
                    raise InvalidTransitionError(
                        "stop is active; new task dispatch/promote is rejected",
                        details={
                            "stop_epoch": self._read_meta(conn, "stop.epoch"),
                            "stop_reason": self._read_meta(conn, "stop.reason"),
                        },
                    )
                consensus_status = "not_required"
                context_id = source_thread_id or _id("ctx")
                if source_thread_id:
                    thread = self._thread_from_conn(conn, source_thread_id)
                    if not thread:
                        raise NotFoundError(
                            "source thread not found", details={"thread_id": source_thread_id}
                        )
                    if thread["state"] == "ACCEPTED":
                        consensus_status = "accepted"
                    elif explicit_non_consensus:
                        consensus_status = "explicit_non_consensus"
                    else:
                        raise InvalidTransitionError(
                            "source thread is not accepted; mark explicit_non_consensus to dispatch honestly",
                            details={"thread_state": thread["state"]},
                        )
                tid = task_id or _id("task")
                conn.execute(
                    """
                    INSERT INTO tasks(
                        task_id,context_id,title,goal,state,dispatched_by,source_thread_id,
                        consensus_status,priority,available_at_ms,max_attempts,version,
                        created_at_ms,updated_at_ms,metadata_json
                    ) VALUES(?,?,?,?,'queued',?,?,?,?,?,?,1,?,?,?)
                    """,
                    (
                        tid,
                        context_id,
                        title.strip(),
                        goal.strip(),
                        who,
                        source_thread_id,
                        consensus_status,
                        priority,
                        available_at_ms if available_at_ms is not None else now,
                        max_attempts,
                        now,
                        now,
                        _canonical(metadata or {}),
                    ),
                )
                event_id = self._append_event(
                    conn,
                    stream_type="task",
                    stream_id=tid,
                    stream_version=1,
                    event_type="TaskDispatched",
                    actor=who,
                    payload={
                        "title": title.strip(),
                        "source_thread_id": source_thread_id,
                        "consensus_status": consensus_status,
                        "priority": priority,
                    },
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=context_id,
                )
                notification_id = self._enqueue_notification(
                    conn,
                    recipient=Actor.ADMIN.value,
                    topic="task.queued",
                    aggregate_type="task",
                    aggregate_id=tid,
                    payload={"task_id": tid, "event_id": event_id, "priority": priority},
                    now=now,
                )
                return {
                    "action": "task.dispatch",
                    "task": self._task_from_conn(conn, tid),
                    "notification_id": notification_id,
                }

            return self._idempotent(
                conn,
                actor=who,
                operation="task.dispatch",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def _task_from_conn(self, conn: apsw.Connection, task_id: str) -> dict[str, Any] | None:
        return _decode_json_fields(
            row_as_dict(conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)))
        )

    def _artifacts_from_conn(self, conn: apsw.Connection, task_id: str) -> list[dict[str, Any]]:
        return [
            _decode_json_fields(row) or {}
            for row in rows_as_dicts(
                conn.execute(
                    "SELECT * FROM artifacts WHERE task_id=? ORDER BY created_at_ms,artifact_id",
                    (task_id,),
                )
            )
        ]

    def _attempts_from_conn(self, conn: apsw.Connection, task_id: str) -> list[dict[str, Any]]:
        return [
            _decode_json_fields(row) or {}
            for row in rows_as_dicts(
                conn.execute(
                    """
                    SELECT * FROM task_attempts
                    WHERE task_id=?
                    ORDER BY attempt_no ASC, started_at_ms ASC
                    """,
                    (task_id,),
                )
            )
        ]

    def _upsert_worker(
        self,
        conn: apsw.Connection,
        *,
        worker_id: str,
        now: int,
        task_id: str | None = None,
        lease_token: str | None = None,
        status: str = "online",
        role: str = "admin",
    ) -> None:
        """Thin worker registry write; idempotent upsert on worker_id."""
        existing = row_as_dict(
            conn.execute("SELECT worker_id, created_at_ms FROM workers WHERE worker_id=?", (worker_id,))
        )
        if existing is None:
            conn.execute(
                """
                INSERT INTO workers(
                    worker_id, role, status, last_seen_at_ms, last_task_id, last_lease_token,
                    hostname, pid, metadata_json, created_at_ms, updated_at_ms
                ) VALUES (?,?,?,?,?,?,NULL,NULL,'{}',?,?)
                """,
                (worker_id, role, status, now, task_id, lease_token, now, now),
            )
            return
        conn.execute(
            """
            UPDATE workers SET
                status=?,
                last_seen_at_ms=?,
                last_task_id=COALESCE(?, last_task_id),
                last_lease_token=COALESCE(?, last_lease_token),
                updated_at_ms=?
            WHERE worker_id=?
            """,
            (status, now, task_id, lease_token, now, worker_id),
        )

    def _open_task_attempt(
        self,
        conn: apsw.Connection,
        *,
        task_id: str,
        attempt_no: int,
        worker_id: str,
        lease_token: str,
        now: int,
        lease_expires_at_ms: int | None,
    ) -> str:
        attempt_id = _id("attempt")
        conn.execute(
            """
            INSERT INTO task_attempts(
                attempt_id, task_id, attempt_no, worker_id, lease_token, state,
                started_at_ms, finished_at_ms, lease_expires_at_ms,
                result_summary, failure_reason, metadata_json
            ) VALUES (?,?,?,?,?,'leased',?,NULL,?,NULL,NULL,'{}')
            """,
            (attempt_id, task_id, attempt_no, worker_id, lease_token, now, lease_expires_at_ms),
        )
        self._upsert_worker(
            conn,
            worker_id=worker_id,
            now=now,
            task_id=task_id,
            lease_token=lease_token,
            status="online",
        )
        return attempt_id

    def _update_task_attempt_by_lease(
        self,
        conn: apsw.Connection,
        *,
        lease_token: str,
        now: int,
        state: str | None = None,
        lease_expires_at_ms: int | None = None,
        finish: bool = False,
        result_summary: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        """Update the open attempt row matched by lease_token (no-op if missing)."""
        row = row_as_dict(
            conn.execute(
                "SELECT attempt_id, worker_id FROM task_attempts WHERE lease_token=?",
                (lease_token,),
            )
        )
        if row is None:
            return
        sets: list[str] = []
        bindings: list[object] = []
        if state is not None:
            sets.append("state=?")
            bindings.append(state)
        if lease_expires_at_ms is not None:
            sets.append("lease_expires_at_ms=?")
            bindings.append(lease_expires_at_ms)
        if finish:
            sets.append("finished_at_ms=?")
            bindings.append(now)
        if result_summary is not None:
            sets.append("result_summary=?")
            bindings.append(result_summary)
        if failure_reason is not None:
            sets.append("failure_reason=?")
            bindings.append(failure_reason)
        if not sets:
            return
        bindings.append(lease_token)
        conn.execute(
            f"UPDATE task_attempts SET {', '.join(sets)} WHERE lease_token=?",
            tuple(bindings),
        )
        self._upsert_worker(
            conn,
            worker_id=str(row["worker_id"]),
            now=now,
            status="online",
        )

    def _cancel_open_task_attempts(
        self,
        conn: apsw.Connection,
        *,
        task_id: str,
        now: int,
        reason: str,
    ) -> list[str]:
        """Converge every open execution ledger row when its task is stopped."""
        rows = rows_as_dicts(
            conn.execute(
                """
                SELECT attempt_id,worker_id FROM task_attempts
                WHERE task_id=? AND state IN ('leased','running')
                ORDER BY attempt_no
                """,
                (task_id,),
            )
        )
        attempt_ids: list[str] = []
        for row in rows:
            attempt_id = str(row["attempt_id"])
            worker_id = str(row["worker_id"])
            conn.execute(
                """
                UPDATE task_attempts
                SET state='canceled',finished_at_ms=COALESCE(finished_at_ms,?),
                    failure_reason=COALESCE(failure_reason,?)
                WHERE attempt_id=? AND state IN ('leased','running')
                """,
                (now, reason, attempt_id),
            )
            if conn.changes() != 1:
                continue
            conn.execute(
                """
                UPDATE workers SET status='stale',last_seen_at_ms=?,last_lease_token=NULL,
                    updated_at_ms=? WHERE worker_id=?
                """,
                (now, now, worker_id),
            )
            attempt_ids.append(attempt_id)
        return attempt_ids

    def _expire_task_leases(self, conn: apsw.Connection, now: int) -> dict[str, int]:
        expired = rows_as_dicts(
            conn.execute(
                """
                SELECT * FROM tasks
                WHERE state IN ('leased','running') AND lease_expires_at_ms <= ?
                ORDER BY task_id
                """,
                (now,),
            )
        )
        requeued = 0
        failed = 0
        for task in expired:
            terminal = int(task["attempt_count"]) >= int(task["max_attempts"])
            state = "failed" if terminal else "queued"
            version = int(task["version"]) + 1
            prev_token = task.get("lease_token")
            conn.execute(
                """
                UPDATE tasks SET state=?,lease_owner=NULL,lease_token=NULL,lease_expires_at_ms=NULL,
                    control_epoch=control_epoch+1,version=?,updated_at_ms=?,
                    failure_reason=CASE WHEN ?='failed' THEN 'lease_exhausted' ELSE failure_reason END
                WHERE task_id=? AND version=?
                """,
                (state, version, now, state, task["task_id"], task["version"]),
            )
            if conn.changes() != 1:
                continue
            if prev_token:
                self._update_task_attempt_by_lease(
                    conn,
                    lease_token=str(prev_token),
                    now=now,
                    state="expired" if terminal else "requeued",
                    finish=True,
                    failure_reason="lease_exhausted" if terminal else "lease_expired_requeue",
                )
            self._append_event(
                conn,
                stream_type="task",
                stream_id=task["task_id"],
                stream_version=version,
                event_type="TaskLeaseExpired",
                actor="system",
                payload={"resulting_state": state, "previous_owner": task["lease_owner"]},
                occurred_at_ms=now,
                correlation_id=task["context_id"],
            )
            if terminal:
                failed += 1
            else:
                requeued += 1
        return {"requeued": requeued, "failed": failed}

    def claim_task(
        self,
        *,
        actor: str | Actor = Actor.ADMIN,
        worker_id: str = "admin",
        lease_seconds: int = 300,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, {Actor.ADMIN.value}, "claim a task")
        if lease_seconds <= 0:
            raise ValidationError("lease_seconds must be positive")
        request = {"worker_id": worker_id, "lease_seconds": lease_seconds}
        with self._tracer.start_as_current_span("coordination.task.claim"), self.db.write() as conn:

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                recovered = self._expire_task_leases(conn, now)
                task = row_as_dict(
                    conn.execute(
                        """
                        SELECT * FROM tasks
                        WHERE state='queued' AND available_at_ms <= ?
                        ORDER BY priority ASC,created_at_ms ASC,task_id ASC LIMIT 1
                        """,
                        (now,),
                    )
                )
                if not task:
                    return {"action": "task.claim", "task": None, "recovered": recovered}
                token = _id("lease")
                version = int(task["version"]) + 1
                attempt_no = int(task["attempt_count"]) + 1
                lease_expires = now + lease_seconds * 1_000
                conn.execute(
                    """
                    UPDATE tasks SET state='leased',lease_owner=?,lease_token=?,lease_expires_at_ms=?,
                        attempt_count=attempt_count+1,version=?,updated_at_ms=?
                    WHERE task_id=? AND state='queued' AND version=?
                    """,
                    (
                        worker_id,
                        token,
                        lease_expires,
                        version,
                        now,
                        task["task_id"],
                        task["version"],
                    ),
                )
                if conn.changes() != 1:
                    raise ConflictError("task changed concurrently")
                attempt_id = self._open_task_attempt(
                    conn,
                    task_id=str(task["task_id"]),
                    attempt_no=attempt_no,
                    worker_id=worker_id,
                    lease_token=token,
                    now=now,
                    lease_expires_at_ms=lease_expires,
                )
                self._append_event(
                    conn,
                    stream_type="task",
                    stream_id=task["task_id"],
                    stream_version=version,
                    event_type="TaskClaimed",
                    actor=who,
                    payload={
                        "worker_id": worker_id,
                        "lease_seconds": lease_seconds,
                        "attempt_id": attempt_id,
                        "attempt_no": attempt_no,
                    },
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=task["context_id"],
                )
                return {
                    "action": "task.claim",
                    "task": self._task_from_conn(conn, task["task_id"]),
                    "lease_token": token,
                    "attempt_id": attempt_id,
                    "recovered": recovered,
                }

            return self._idempotent(
                conn,
                actor=who,
                operation="task.claim",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def _require_lease(
        self,
        task: dict[str, Any],
        lease_token: str,
        now: int,
        *,
        states: Iterable[str],
    ) -> None:
        if task["lease_token"] != lease_token:
            raise LeaseError("lease token does not match")
        if int(task["lease_expires_at_ms"]) <= now:
            raise LeaseError("lease expired", details={"lease_expires_at_ms": task["lease_expires_at_ms"]})
        if task["state"] not in set(states):
            raise InvalidTransitionError(
                "task is not in a lease-owned state", details={"state": task["state"]}
            )

    def start_task(
        self,
        *,
        actor: str | Actor = Actor.ADMIN,
        task_id: str,
        lease_token: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        return self._lease_transition(
            actor=actor,
            task_id=task_id,
            lease_token=lease_token,
            operation="task.start",
            allowed_states={"leased"},
            target_state="running",
            event_type="TaskStarted",
            idempotency_key=idempotency_key,
        )

    def heartbeat_task(
        self,
        *,
        actor: str | Actor = Actor.ADMIN,
        task_id: str,
        lease_token: str,
        lease_seconds: int = 300,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, {Actor.ADMIN.value}, "heartbeat a task")
        if lease_seconds <= 0:
            raise ValidationError("lease_seconds must be positive")
        request = {"task_id": task_id, "lease_token": lease_token, "lease_seconds": lease_seconds}
        with self.db.write() as conn:

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                task = self._task_from_conn(conn, task_id)
                if not task:
                    raise NotFoundError("task not found", details={"task_id": task_id})
                self._require_lease(task, lease_token, now, states={"leased", "running"})
                version = int(task["version"]) + 1
                conn.execute(
                    """
                    UPDATE tasks SET lease_expires_at_ms=?,version=?,updated_at_ms=?
                    WHERE task_id=? AND version=? AND lease_token=?
                    """,
                    (
                        now + lease_seconds * 1_000,
                        version,
                        now,
                        task_id,
                        task["version"],
                        lease_token,
                    ),
                )
                if conn.changes() != 1:
                    raise LeaseError("lease was fenced during heartbeat")
                self._update_task_attempt_by_lease(
                    conn,
                    lease_token=lease_token,
                    now=now,
                    lease_expires_at_ms=now + lease_seconds * 1_000,
                )
                owner = task.get("lease_owner")
                if owner:
                    self._upsert_worker(
                        conn,
                        worker_id=str(owner),
                        now=now,
                        task_id=task_id,
                        lease_token=lease_token,
                        status="online",
                    )
                self._append_event(
                    conn,
                    stream_type="task",
                    stream_id=task_id,
                    stream_version=version,
                    event_type="TaskHeartbeat",
                    actor=who,
                    payload={"lease_seconds": lease_seconds},
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=task["context_id"],
                )
                return {"action": "task.heartbeat", "task": self._task_from_conn(conn, task_id)}

            return self._idempotent(
                conn,
                actor=who,
                operation="task.heartbeat",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def _lease_transition(
        self,
        *,
        actor: str | Actor,
        task_id: str,
        lease_token: str,
        operation: str,
        allowed_states: set[str],
        target_state: str,
        event_type: str,
        idempotency_key: str | None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, {Actor.ADMIN.value}, operation)
        request = {"task_id": task_id, "lease_token": lease_token}
        with (
            self._tracer.start_as_current_span(f"coordination.{operation}"),
            self.db.write() as conn,
        ):

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                task = self._task_from_conn(conn, task_id)
                if not task:
                    raise NotFoundError("task not found", details={"task_id": task_id})
                self._require_lease(task, lease_token, now, states=allowed_states)
                version = int(task["version"]) + 1
                conn.execute(
                    """
                    UPDATE tasks SET state=?,version=?,updated_at_ms=?
                    WHERE task_id=? AND version=? AND lease_token=?
                    """,
                    (target_state, version, now, task_id, task["version"], lease_token),
                )
                if conn.changes() != 1:
                    raise LeaseError("lease was fenced during transition")
                if target_state == "running":
                    self._update_task_attempt_by_lease(
                        conn, lease_token=lease_token, now=now, state="running"
                    )
                self._append_event(
                    conn,
                    stream_type="task",
                    stream_id=task_id,
                    stream_version=version,
                    event_type=event_type,
                    actor=who,
                    payload={"state": target_state},
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=task["context_id"],
                )
                return {"action": operation, "task": self._task_from_conn(conn, task_id)}

            return self._idempotent(
                conn,
                actor=who,
                operation=operation,
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def complete_task(
        self,
        *,
        actor: str | Actor = Actor.ADMIN,
        task_id: str,
        lease_token: str,
        result_summary: str,
        evidence: list[dict[str, object]],
        artifacts: list[dict[str, object]] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, {Actor.ADMIN.value}, "complete a task")
        if not result_summary.strip() or not evidence:
            raise ValidationError("completion requires a result summary and non-empty evidence")
        request = {
            "task_id": task_id,
            "lease_token": lease_token,
            "result_summary": result_summary,
            "evidence": evidence,
            "artifacts": artifacts or [],
        }
        with (
            self._tracer.start_as_current_span("coordination.task.complete"),
            self.db.write() as conn,
        ):

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                task = self._task_from_conn(conn, task_id)
                if not task:
                    raise NotFoundError("task not found", details={"task_id": task_id})
                self._require_lease(task, lease_token, now, states={"running"})
                inserted = self._insert_artifacts(
                    conn, task_id=task_id, actor=who, artifacts=artifacts or [], now=now
                )
                version = int(task["version"]) + 1
                conn.execute(
                    """
                    UPDATE tasks SET state='completed',lease_owner=NULL,lease_token=NULL,
                        lease_expires_at_ms=NULL,version=?,updated_at_ms=?,completed_at_ms=?,
                        result_summary=?,failure_reason=NULL
                    WHERE task_id=? AND version=? AND lease_token=?
                    """,
                    (
                        version,
                        now,
                        now,
                        result_summary.strip(),
                        task_id,
                        task["version"],
                        lease_token,
                    ),
                )
                if conn.changes() != 1:
                    raise LeaseError("lease was fenced during completion")
                self._update_task_attempt_by_lease(
                    conn,
                    lease_token=lease_token,
                    now=now,
                    state="completed",
                    finish=True,
                    result_summary=result_summary.strip(),
                )
                event_id = self._append_event(
                    conn,
                    stream_type="task",
                    stream_id=task_id,
                    stream_version=version,
                    event_type="TaskCompleted",
                    actor=who,
                    payload={
                        "result_summary": result_summary.strip(),
                        "evidence": evidence,
                        "artifact_ids": [item["artifact_id"] for item in inserted],
                        "verification_status": "evidence_attached_not_independently_verified",
                    },
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=task["context_id"],
                )
                self._enqueue_notification(
                    conn,
                    recipient=task["dispatched_by"],
                    topic="task.completed",
                    aggregate_type="task",
                    aggregate_id=task_id,
                    payload={"task_id": task_id, "event_id": event_id},
                    now=now,
                )
                return {
                    "action": "task.complete",
                    "task": self._task_from_conn(conn, task_id),
                    "artifacts": self._artifacts_from_conn(conn, task_id),
                    "attempts": self._attempts_from_conn(conn, task_id),
                    "verification_status": "evidence_attached_not_independently_verified",
                }

            return self._idempotent(
                conn,
                actor=who,
                operation="task.complete",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def fail_task(
        self,
        *,
        actor: str | Actor = Actor.ADMIN,
        task_id: str,
        lease_token: str,
        error: str,
        retryable: bool = True,
        retry_delay_seconds: int = 0,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, {Actor.ADMIN.value}, "fail a task")
        if not error.strip() or retry_delay_seconds < 0:
            raise ValidationError("error is required and retry delay cannot be negative")
        request = {
            "task_id": task_id,
            "lease_token": lease_token,
            "error": error,
            "retryable": retryable,
            "retry_delay_seconds": retry_delay_seconds,
        }
        with self.db.write() as conn:

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                task = self._task_from_conn(conn, task_id)
                if not task:
                    raise NotFoundError("task not found", details={"task_id": task_id})
                self._require_lease(task, lease_token, now, states={"leased", "running"})
                retry = retryable and int(task["attempt_count"]) < int(task["max_attempts"])
                state = "queued" if retry else "failed"
                version = int(task["version"]) + 1
                conn.execute(
                    """
                    UPDATE tasks SET state=?,lease_owner=NULL,lease_token=NULL,lease_expires_at_ms=NULL,
                        control_epoch=control_epoch+1,version=?,updated_at_ms=?,available_at_ms=?,
                        failure_reason=?
                    WHERE task_id=? AND version=? AND lease_token=?
                    """,
                    (
                        state,
                        version,
                        now,
                        now + retry_delay_seconds * 1_000,
                        error.strip(),
                        task_id,
                        task["version"],
                        lease_token,
                    ),
                )
                if conn.changes() != 1:
                    raise LeaseError("lease was fenced during failure transition")
                self._update_task_attempt_by_lease(
                    conn,
                    lease_token=lease_token,
                    now=now,
                    state="requeued" if retry else "failed",
                    finish=True,
                    failure_reason=error.strip(),
                )
                self._append_event(
                    conn,
                    stream_type="task",
                    stream_id=task_id,
                    stream_version=version,
                    event_type="TaskRetryScheduled" if retry else "TaskFailed",
                    actor=who,
                    payload={"error": error.strip(), "retry": retry},
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=task["context_id"],
                )
                return {
                    "action": "task.fail",
                    "retry": retry,
                    "task": self._task_from_conn(conn, task_id),
                    "attempts": self._attempts_from_conn(conn, task_id),
                }

            return self._idempotent(
                conn,
                actor=who,
                operation="task.fail",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def pause_task(
        self,
        *,
        actor: str | Actor,
        task_id: str,
        reason: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, TASK_DISPATCHERS, "pause a task")
        if not reason.strip():
            raise ValidationError("pause reason is required")
        return self._control_task(
            actor=who,
            task_id=task_id,
            operation="task.pause",
            target_state="paused",
            allowed_states={"queued", "leased", "running"},
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def resume_task(
        self,
        *,
        actor: str | Actor,
        task_id: str,
        reason: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, TASK_DISPATCHERS, "resume a task")
        return self._control_task(
            actor=who,
            task_id=task_id,
            operation="task.resume",
            target_state="queued",
            allowed_states={"paused"},
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def cancel_task(
        self,
        *,
        actor: str | Actor,
        task_id: str,
        reason: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        self._require_actor(who, TASK_DISPATCHERS, "cancel a task")
        return self._control_task(
            actor=who,
            task_id=task_id,
            operation="task.cancel",
            target_state="canceled",
            allowed_states={"queued", "leased", "running", "paused"},
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def _control_task(
        self,
        *,
        actor: str,
        task_id: str,
        operation: str,
        target_state: str,
        allowed_states: set[str],
        reason: str,
        idempotency_key: str | None,
    ) -> dict[str, object]:
        request = {"task_id": task_id, "target_state": target_state, "reason": reason}
        with self.db.write() as conn:

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                task = self._task_from_conn(conn, task_id)
                if not task:
                    raise NotFoundError("task not found", details={"task_id": task_id})
                if task["state"] not in allowed_states:
                    raise InvalidTransitionError(
                        "task cannot enter requested state", details={"state": task["state"]}
                    )
                version = int(task["version"]) + 1
                prev_token = task.get("lease_token")
                conn.execute(
                    """
                    UPDATE tasks SET state=?,lease_owner=NULL,lease_token=NULL,lease_expires_at_ms=NULL,
                        control_epoch=control_epoch+1,version=?,updated_at_ms=?
                    WHERE task_id=? AND version=?
                    """,
                    (target_state, version, now, task_id, task["version"]),
                )
                if conn.changes() != 1:
                    raise ConflictError("task changed concurrently")
                if prev_token and target_state in {"paused", "canceled"}:
                    self._update_task_attempt_by_lease(
                        conn,
                        lease_token=str(prev_token),
                        now=now,
                        state="canceled" if target_state == "canceled" else "requeued",
                        finish=True,
                        failure_reason=reason,
                    )
                self._append_event(
                    conn,
                    stream_type="task",
                    stream_id=task_id,
                    stream_version=version,
                    event_type={
                        "paused": "TaskPaused",
                        "queued": "TaskResumed",
                        "canceled": "TaskCanceled",
                    }[target_state],
                    actor=actor,
                    payload={"reason": reason, "control_epoch": int(task["control_epoch"]) + 1},
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=task["context_id"],
                )
                return {"action": operation, "task": self._task_from_conn(conn, task_id)}

            return self._idempotent(
                conn,
                actor=actor,
                operation=operation,
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def _insert_artifacts(
        self,
        conn: apsw.Connection,
        *,
        task_id: str,
        actor: str,
        artifacts: list[dict[str, object]],
        now: int,
    ) -> list[dict[str, object]]:
        inserted: list[dict[str, object]] = []
        for spec in artifacts:
            uri = str(spec.get("uri") or "").strip()
            if not uri:
                raise ValidationError("artifact uri is required")
            artifact_id = str(spec.get("artifact_id") or _id("art"))
            name = str(spec.get("name") or Path(uri).name or artifact_id)
            media_type = str(spec.get("media_type") or "application/octet-stream")
            sha256 = spec.get("sha256")
            size_bytes = spec.get("size_bytes")
            metadata = spec.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise ValidationError("artifact metadata must be an object")
            conn.execute(
                """
                INSERT INTO artifacts(
                    artifact_id,task_id,name,uri,media_type,sha256,size_bytes,created_by,
                    created_at_ms,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    artifact_id,
                    task_id,
                    name,
                    uri,
                    media_type,
                    sha256,
                    size_bytes,
                    actor,
                    now,
                    _canonical(metadata),
                ),
            )
            inserted.append({"artifact_id": artifact_id, "uri": uri})
        return inserted

    def register_local_artifact(
        self,
        *,
        actor: str | Actor,
        task_id: str,
        path: str | Path,
        name: str | None = None,
        media_type: str = "application/octet-stream",
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise ValidationError("artifact path is not a file", details={"path": str(file_path)})
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        spec = {
            "uri": file_path.as_uri(),
            "name": name or file_path.name,
            "media_type": media_type,
            "sha256": digest.hexdigest(),
            "size_bytes": file_path.stat().st_size,
        }
        request = {"task_id": task_id, **spec}
        with self.db.write() as conn:

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                task = self._task_from_conn(conn, task_id)
                if not task:
                    raise NotFoundError("task not found", details={"task_id": task_id})
                inserted = self._insert_artifacts(conn, task_id=task_id, actor=who, artifacts=[spec], now=now)
                version = int(task["version"]) + 1
                conn.execute(
                    "UPDATE tasks SET version=?,updated_at_ms=? WHERE task_id=? AND version=?",
                    (version, now, task_id, task["version"]),
                )
                if conn.changes() != 1:
                    raise ConflictError("task changed concurrently")
                self._append_event(
                    conn,
                    stream_type="task",
                    stream_id=task_id,
                    stream_version=version,
                    event_type="ArtifactRegistered",
                    actor=who,
                    payload=inserted[0],
                    occurred_at_ms=now,
                    idempotency_key=key,
                    correlation_id=task["context_id"],
                )
                return {
                    "action": "artifact.register",
                    "artifact": self._artifacts_from_conn(conn, task_id)[-1],
                }

            return self._idempotent(
                conn,
                actor=who,
                operation="artifact.register",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def get_task(self, task_id: str) -> dict[str, object]:
        with self.db.read() as conn:
            task = self._task_from_conn(conn, task_id)
            if not task:
                raise NotFoundError("task not found", details={"task_id": task_id})
            artifacts = self._artifacts_from_conn(conn, task_id)
            attempts = self._attempts_from_conn(conn, task_id)
        return {"ok": True, "task": task, "artifacts": artifacts, "attempts": attempts}

    def list_tasks(self, *, state: str | None = None, limit: int = 100) -> dict[str, object]:
        sql = "SELECT * FROM tasks"
        bindings: tuple[object, ...] = ()
        if state:
            sql += " WHERE state=?"
            bindings = (state,)
        sql += " ORDER BY priority ASC,created_at_ms ASC LIMIT ?"
        bindings += (limit,)
        tasks = [_decode_json_fields(row) for row in self.db.execute_read(sql, bindings)]
        return {"ok": True, "count": len(tasks), "tasks": tasks}

    def sweep(self) -> dict[str, object]:
        now = self.now_ms()
        with self.db.write() as conn:
            expired_threads = rows_as_dicts(
                conn.execute(
                    """
                    SELECT * FROM threads
                    WHERE state NOT IN ('ACCEPTED','REJECTED','EACH_CLOSED','ESCALATED','EXPIRED')
                      AND expires_at_ms <= ?
                    """,
                    (now,),
                )
            )
            for thread in expired_threads:
                self._expire_thread(conn, thread, now)
            tasks = self._expire_task_leases(conn, now)
            outbox = self._expire_notification_leases(conn, now)
        if os.environ.get("XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }:
            from .agent_operations import AgentOperationStore

            agent_operations = AgentOperationStore(self.db.path, clock_ms=self._clock_ms).sweep()
        else:
            agent_operations = {
                "ok": True,
                "enabled": False,
                "action": "experimental_agent_operations_not_swept",
            }
        return {
            "ok": True,
            "action": "sweep",
            "expired_threads": len(expired_threads),
            "task_leases": tasks,
            "notification_leases": outbox,
            "agent_operations": agent_operations,
        }

    def _expire_notification_leases(self, conn: apsw.Connection, now: int) -> dict[str, int]:
        leased = rows_as_dicts(
            conn.execute(
                """
                SELECT notification_id,attempts,max_attempts FROM notification_outbox
                WHERE status='leased' AND lease_expires_at_ms <= ?
                """,
                (now,),
            )
        )
        pending = 0
        dead = 0
        for item in leased:
            state = "dead" if int(item["attempts"]) >= int(item["max_attempts"]) else "pending"
            conn.execute(
                """
                UPDATE notification_outbox SET status=?,lease_owner=NULL,lease_token=NULL,
                    lease_expires_at_ms=NULL,last_error='delivery_lease_expired'
                WHERE notification_id=? AND status='leased'
                """,
                (state, item["notification_id"]),
            )
            if state == "dead":
                dead += 1
            else:
                pending += 1
        return {"pending": pending, "dead": dead}

    def pull_notification(
        self,
        *,
        actor: str | Actor,
        recipient: str,
        adapter_id: str,
        lease_seconds: int = 60,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        if recipient not in {Actor.USER.value, Actor.ADMIN.value, *BRAINS}:
            raise ValidationError("invalid notification recipient")
        if who != recipient:
            raise AuthorizationError(
                "actor can only pull its own notifications",
                details={"actor": who, "recipient": recipient},
            )
        if lease_seconds <= 0:
            raise ValidationError("lease_seconds must be positive")
        if not adapter_id.strip() or "|" in adapter_id:
            raise ValidationError("adapter_id must be non-empty and must not contain '|'")
        request = {
            "recipient": recipient,
            "adapter_id": adapter_id,
            "lease_seconds": lease_seconds,
        }
        with self.db.write() as conn:

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                self._expire_notification_leases(conn, now)
                item = row_as_dict(
                    conn.execute(
                        """
                        SELECT * FROM notification_outbox
                        WHERE status='pending' AND recipient IN (?, '*') AND available_at_ms <= ?
                        ORDER BY created_at_ms,notification_id LIMIT 1
                        """,
                        (recipient, now),
                    )
                )
                if not item:
                    return {"action": "notification.pull", "notification": None}
                token = _id("notify_lease")
                conn.execute(
                    """
                    UPDATE notification_outbox SET status='leased',attempts=attempts+1,
                        lease_owner=?,lease_token=?,lease_expires_at_ms=?
                    WHERE notification_id=? AND status='pending'
                    """,
                    (
                        f"{who}|{adapter_id}",
                        token,
                        now + lease_seconds * 1_000,
                        item["notification_id"],
                    ),
                )
                if conn.changes() != 1:
                    raise ConflictError("notification changed concurrently")
                leased = _decode_json_fields(
                    row_as_dict(
                        conn.execute(
                            "SELECT * FROM notification_outbox WHERE notification_id=?",
                            (item["notification_id"],),
                        )
                    )
                )
                return {
                    "action": "notification.pull",
                    "notification": leased,
                    "lease_token": token,
                    "durable_delivery": True,
                    "model_read": False,
                }

            return self._idempotent(
                conn,
                actor=who,
                operation="notification.pull",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def ack_notification(
        self,
        *,
        actor: str | Actor,
        notification_id: str,
        lease_token: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        who = _actor(actor)
        request = {"notification_id": notification_id, "lease_token": lease_token}
        with self.db.write() as conn:

            def execute(key: str) -> dict[str, object]:
                now = self.now_ms()
                item = row_as_dict(
                    conn.execute(
                        "SELECT * FROM notification_outbox WHERE notification_id=?",
                        (notification_id,),
                    )
                )
                if not item:
                    raise NotFoundError("notification not found")
                if item["status"] != "leased" or item["lease_token"] != lease_token:
                    raise LeaseError("notification lease does not match")
                lease_actor = str(item["lease_owner"]).partition("|")[0]
                if lease_actor != who or item["recipient"] not in {who, "*"}:
                    raise AuthorizationError(
                        "notification lease belongs to a different recipient",
                        details={"actor": who, "recipient": item["recipient"]},
                    )
                if int(item["lease_expires_at_ms"]) <= now:
                    raise LeaseError("notification lease expired")
                conn.execute(
                    """
                    UPDATE notification_outbox SET status='delivered',delivered_at_ms=?,
                        lease_owner=NULL,lease_token=NULL,lease_expires_at_ms=NULL
                    WHERE notification_id=? AND status='leased' AND lease_token=?
                    """,
                    (now, notification_id, lease_token),
                )
                if conn.changes() != 1:
                    raise LeaseError("notification lease was fenced")
                return {
                    "action": "notification.ack",
                    "notification_id": notification_id,
                    "doorbell_delivered": True,
                    "model_read": False,
                    "note": "adapter delivery is not an observation receipt",
                }

            return self._idempotent(
                conn,
                actor=who,
                operation="notification.ack",
                key=idempotency_key,
                request=request,
                execute=execute,
            )

    def record_receipt(
        self,
        *,
        actor: str | Actor,
        item_type: str,
        item_id: str,
        receipt_type: str = "observed",
    ) -> dict[str, object]:
        who = _actor(actor)
        if item_type not in {"message", "task", "notification", "event"}:
            raise ValidationError("invalid receipt item_type")
        if receipt_type not in {"observed", "acted_on"}:
            raise ValidationError("invalid receipt_type")
        now = self.now_ms()
        with self.db.write() as conn:
            table, identifier, columns = {
                "message": ("messages", "message_id", "sender,recipient"),
                "task": ("tasks", "task_id", "dispatched_by,assigned_role"),
                "notification": ("notification_outbox", "notification_id", "recipient"),
                "event": ("events", "event_id", "actor AS event_actor"),
            }[item_type]
            target = row_as_dict(
                conn.execute(
                    f"SELECT {columns} FROM {table} WHERE {identifier}=?",
                    (item_id,),
                )
            )
            if not target:
                raise NotFoundError(
                    "receipt target not found",
                    details={"item_type": item_type, "item_id": item_id},
                )
            if item_type == "message":
                permitted = target["recipient"] in {who, "*"} and not (
                    target["recipient"] == "*" and target["sender"] == who
                )
            elif item_type == "task":
                permitted = who in {
                    target["dispatched_by"],
                    target["assigned_role"],
                    Actor.USER.value,
                }
            elif item_type == "notification":
                permitted = target["recipient"] in {who, "*"}
            else:
                permitted = True
            if not permitted:
                raise AuthorizationError(
                    "actor is not a recipient or owner of this item",
                    details={"actor": who, "item_type": item_type, "item_id": item_id},
                )
            conn.execute(
                """
                INSERT OR IGNORE INTO receipts(item_type,item_id,actor,receipt_type,created_at_ms)
                VALUES(?,?,?,?,?)
                """,
                (item_type, item_id, who, receipt_type, now),
            )
            created = conn.changes() == 1
        return {
            "ok": True,
            "action": "receipt.record",
            "created": created,
            "actor": who,
            "item_type": item_type,
            "item_id": item_id,
            "receipt_type": receipt_type,
            "meaning": "explicit local tool attestation; not inferred from doorbell delivery",
            "identity_assurance": "caller_declared_unverified",
        }

    def events(
        self,
        *,
        stream_type: str | None = None,
        stream_id: str | None = None,
        after_seq: int = 0,
        limit: int = 200,
    ) -> dict[str, object]:
        clauses = ["seq > ?"]
        bindings: list[object] = [after_seq]
        if stream_type:
            clauses.append("stream_type=?")
            bindings.append(stream_type)
        if stream_id:
            clauses.append("stream_id=?")
            bindings.append(stream_id)
        bindings.append(limit)
        rows = self.db.execute_read(
            "SELECT * FROM events WHERE " + " AND ".join(clauses) + " ORDER BY seq ASC LIMIT ?",
            tuple(bindings),
        )
        return {
            "ok": True,
            "count": len(rows),
            "events": [_decode_json_fields(row) for row in rows],
        }

    def status(self) -> dict[str, object]:
        health = self.db.health()
        with self.db.read() as conn:
            counts = {
                "threads": scalar(conn.execute("SELECT count(*) FROM threads")),
                "tasks": scalar(conn.execute("SELECT count(*) FROM tasks")),
                "queued_tasks": scalar(conn.execute("SELECT count(*) FROM tasks WHERE state='queued'")),
                "active_leases": scalar(
                    conn.execute("SELECT count(*) FROM tasks WHERE state IN ('leased','running')")
                ),
                "agent_operations": scalar(conn.execute("SELECT count(*) FROM agent_operations")),
                "active_agent_operations": scalar(
                    conn.execute(
                        """
                        SELECT count(*) FROM agent_operations
                        WHERE state IN ('running','cancel_requested')
                        """
                    )
                ),
                "pending_notifications": scalar(
                    conn.execute("SELECT count(*) FROM notification_outbox WHERE status='pending'")
                ),
                "events": scalar(conn.execute("SELECT count(*) FROM events")),
            }
        return {
            "ok": bool(health["ok"]),
            "health": health,
            "counts": counts,
            "architecture": "embedded_transactional_kernel",
            "a2a_semantics": True,
            "background_daemon": False,
            "route_policy": "replaceable_contextual_net_benefit_advisory",
            "role_assertion": "trusted_local_caller_declared_not_authentication",
            "generation_id": os.environ.get("XINAO_COORD_GENERATION_ID"),
            "source_fingerprint": os.environ.get("XINAO_COORD_SOURCE_FINGERPRINT"),
            "hard_gates": ["authority", "state", "idempotency", "lease_fencing", "evidence"],
        }

    def backup(self, destination: str | Path) -> dict[str, object]:
        return self.db.backup_to(destination)
