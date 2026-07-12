"""APSW-backed embedded database and schema management."""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import apsw

from .errors import CoordinationError

DEFAULT_STATE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination")
SCHEMA_VERSION = 3
MIN_SAFE_WAL_SQLITE = (3, 51, 3)


SCHEMA_V1 = r"""
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'OPEN','ACTIVE','CLOSING','ACCEPTED','REJECTED','EACH_CLOSED','ESCALATED','EXPIRED'
    )),
    opened_by TEXT NOT NULL CHECK(opened_by IN ('user','grok_4_5','codex')),
    version INTEGER NOT NULL CHECK(version >= 1),
    rounds INTEGER NOT NULL DEFAULT 0 CHECK(rounds >= 0),
    max_rounds INTEGER NOT NULL CHECK(max_rounds > 0),
    opened_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    close_resolution_key TEXT,
    close_reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json))
) STRICT;

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    sender TEXT NOT NULL CHECK(sender IN ('user','grok_4_5','codex')),
    recipient TEXT NOT NULL CHECK(recipient IN ('user','grok_4_5','codex','*')),
    kind TEXT NOT NULL CHECK(kind IN (
        'propose','ask','inform','counter','challenge','clarify','correct','reply','note','system'
    )),
    body TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE(sender, idempotency_key)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_messages_thread_created
ON messages(thread_id, created_at_ms, message_id);

CREATE TABLE IF NOT EXISTS closure_votes (
    thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    actor TEXT NOT NULL CHECK(actor IN ('grok_4_5','codex')),
    decision TEXT NOT NULL CHECK(decision IN ('accept','reject','each_close','escalate_to_user')),
    resolution_key TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(thread_id, actor)
) STRICT;

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    context_id TEXT NOT NULL,
    title TEXT NOT NULL,
    goal TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'queued','leased','running','paused','completed','failed','canceled'
    )),
    assigned_role TEXT NOT NULL DEFAULT 'admin' CHECK(assigned_role = 'admin'),
    dispatched_by TEXT NOT NULL CHECK(dispatched_by IN ('user','grok_4_5','codex')),
    source_thread_id TEXT REFERENCES threads(thread_id),
    consensus_status TEXT NOT NULL CHECK(consensus_status IN (
        'accepted','explicit_non_consensus','not_required'
    )),
    priority INTEGER NOT NULL DEFAULT 100,
    available_at_ms INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts > 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at_ms INTEGER,
    control_epoch INTEGER NOT NULL DEFAULT 0 CHECK(control_epoch >= 0),
    version INTEGER NOT NULL CHECK(version >= 1),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    result_summary TEXT,
    failure_reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    CHECK((state IN ('leased','running') AND lease_token IS NOT NULL AND lease_owner IS NOT NULL
           AND lease_expires_at_ms IS NOT NULL)
          OR (state NOT IN ('leased','running') AND lease_token IS NULL AND lease_owner IS NULL
              AND lease_expires_at_ms IS NULL))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_tasks_claim
ON tasks(state, available_at_ms, priority, created_at_ms);
CREATE INDEX IF NOT EXISTS idx_tasks_source_thread ON tasks(source_thread_id);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    uri TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT,
    size_bytes INTEGER CHECK(size_bytes IS NULL OR size_bytes >= 0),
    created_by TEXT NOT NULL CHECK(created_by IN ('user','grok_4_5','codex','admin')),
    created_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    UNIQUE(task_id, uri)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id, created_at_ms);

CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    stream_type TEXT NOT NULL CHECK(stream_type IN ('thread','task','notification','system')),
    stream_id TEXT NOT NULL,
    stream_version INTEGER NOT NULL CHECK(stream_version >= 1),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL CHECK(actor IN ('user','grok_4_5','codex','admin','system')),
    schema_version TEXT NOT NULL,
    causation_id TEXT,
    correlation_id TEXT,
    trace_id TEXT,
    span_id TEXT,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    occurred_at_ms INTEGER NOT NULL,
    idempotency_key TEXT,
    UNIQUE(stream_type, stream_id, stream_version)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, seq);

CREATE TABLE IF NOT EXISTS notification_outbox (
    notification_id TEXT PRIMARY KEY,
    recipient TEXT NOT NULL CHECK(recipient IN ('user','grok_4_5','codex','admin','*')),
    topic TEXT NOT NULL,
    aggregate_type TEXT NOT NULL CHECK(aggregate_type IN ('thread','task','system')),
    aggregate_id TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','leased','delivered','dead')),
    available_at_ms INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK(max_attempts > 0),
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    delivered_at_ms INTEGER,
    last_error TEXT,
    CHECK((status = 'leased' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL
           AND lease_expires_at_ms IS NOT NULL)
          OR (status <> 'leased' AND lease_owner IS NULL AND lease_token IS NULL
              AND lease_expires_at_ms IS NULL))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_outbox_claim
ON notification_outbox(status, recipient, available_at_ms, created_at_ms);

CREATE TABLE IF NOT EXISTS receipts (
    item_type TEXT NOT NULL CHECK(item_type IN ('message','task','notification','event')),
    item_id TEXT NOT NULL,
    actor TEXT NOT NULL CHECK(actor IN ('user','grok_4_5','codex','admin')),
    receipt_type TEXT NOT NULL CHECK(receipt_type IN ('observed','acted_on')),
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(item_type, item_id, actor, receipt_type)
) STRICT;

CREATE TABLE IF NOT EXISTS idempotency (
    actor TEXT NOT NULL CHECK(actor IN ('user','grok_4_5','codex','admin','system')),
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(actor, operation, idempotency_key)
) STRICT;
"""

SCHEMA_V2 = r"""
CREATE TABLE IF NOT EXISTS agent_operations (
    operation_id TEXT PRIMARY KEY,
    context_id TEXT NOT NULL,
    actor TEXT NOT NULL CHECK(actor IN ('user','codex')),
    target_role TEXT NOT NULL DEFAULT 'grok_4_5' CHECK(target_role = 'grok_4_5'),
    session_name TEXT NOT NULL,
    cwd TEXT NOT NULL,
    prompt TEXT NOT NULL,
    operation_token TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'queued','running','retry_wait','cancel_requested','waiting_input','uncertain',
        'completed','failed','canceled','deadline_exceeded'
    )),
    request_id TEXT,
    provider_prompt_id TEXT,
    acpx_record_id TEXT,
    agent_session_id TEXT,
    collector_pid INTEGER CHECK(collector_pid IS NULL OR collector_pid > 0),
    collector_start_time_ms INTEGER,
    owner_pid INTEGER CHECK(owner_pid IS NULL OR owner_pid > 0),
    owner_start_time_ms INTEGER,
    owner_generation INTEGER,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at_ms INTEGER,
    control_epoch INTEGER NOT NULL DEFAULT 0 CHECK(control_epoch >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 1 CHECK(max_attempts > 0),
    replay_safe INTEGER NOT NULL DEFAULT 0 CHECK(replay_safe IN (0,1)),
    available_at_ms INTEGER NOT NULL,
    deadline_at_ms INTEGER NOT NULL,
    submitted_at_ms INTEGER NOT NULL,
    started_at_ms INTEGER,
    updated_at_ms INTEGER NOT NULL,
    last_progress_at_ms INTEGER,
    completed_at_ms INTEGER,
    stop_reason TEXT,
    result_text TEXT,
    error TEXT,
    event_log_path TEXT,
    stderr_log_path TEXT,
    version INTEGER NOT NULL CHECK(version >= 1),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    UNIQUE(actor, idempotency_key),
    CHECK((lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at_ms IS NULL)
          OR (lease_owner IS NOT NULL AND lease_token IS NOT NULL
              AND lease_expires_at_ms IS NOT NULL))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_agent_operations_reconcile
ON agent_operations(state, available_at_ms, deadline_at_ms, submitted_at_ms);
CREATE INDEX IF NOT EXISTS idx_agent_operations_session
ON agent_operations(session_name, submitted_at_ms);

CREATE TABLE IF NOT EXISTS agent_operation_artifacts (
    artifact_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES agent_operations(operation_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    uri TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT,
    size_bytes INTEGER CHECK(size_bytes IS NULL OR size_bytes >= 0),
    created_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    UNIQUE(operation_id, uri)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_agent_operation_artifacts_operation
ON agent_operation_artifacts(operation_id, created_at_ms);
"""

# v3: first-class task attempt history + worker registry.
# Additive only (CREATE IF NOT EXISTS). Does not rewrite tasks/artifacts rows.
# Artifacts remain task-scoped; attempt linkage is via task_attempts + optional metadata.
SCHEMA_V3 = r"""
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'admin' CHECK(role IN ('admin','system','agent')),
    status TEXT NOT NULL CHECK(status IN ('online','offline','stale')),
    last_seen_at_ms INTEGER NOT NULL,
    last_task_id TEXT,
    last_lease_token TEXT,
    hostname TEXT,
    pid INTEGER CHECK(pid IS NULL OR pid > 0),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_workers_status
ON workers(status, last_seen_at_ms);

CREATE TABLE IF NOT EXISTS task_attempts (
    attempt_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1),
    worker_id TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'leased','running','completed','failed','expired','canceled','requeued'
    )),
    started_at_ms INTEGER NOT NULL,
    finished_at_ms INTEGER,
    lease_expires_at_ms INTEGER,
    result_summary TEXT,
    failure_reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    UNIQUE(task_id, attempt_no),
    UNIQUE(lease_token)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_task_attempts_task
ON task_attempts(task_id, attempt_no);
CREATE INDEX IF NOT EXISTS idx_task_attempts_worker
ON task_attempts(worker_id, started_at_ms);
CREATE INDEX IF NOT EXISTS idx_task_attempts_open
ON task_attempts(state, started_at_ms);
"""


def _version_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    return tuple(int(p) for p in parts[:3])  # type: ignore[return-value]


def default_db_path() -> Path:
    configured = os.environ.get("XINAO_COORD_DB")
    return Path(configured) if configured else DEFAULT_STATE_ROOT / "coordination.sqlite3"


def _dict_row(cursor: apsw.Cursor, row: tuple[object, ...]) -> dict[str, Any]:
    names = [column[0] for column in cursor.get_description()]
    return dict(zip(names, row, strict=True))


def rows_as_dicts(cursor: apsw.Cursor) -> list[dict[str, Any]]:
    return list(cursor)


def row_as_dict(cursor: apsw.Cursor) -> dict[str, Any] | None:
    return cursor.fetchone()


def scalar(cursor: apsw.Cursor) -> object:
    row = row_as_dict(cursor)
    if row is None:
        raise CoordinationError("scalar query returned no rows")
    return next(iter(row.values()))


class Database:
    """Opens short-lived connections so independent processes share one durable database."""

    def __init__(self, path: str | Path | None = None, *, busy_timeout_ms: int = 8_000) -> None:
        self.path = Path(path) if path else default_db_path()
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if _version_tuple(apsw.sqlite_lib_version()) < MIN_SAFE_WAL_SQLITE:
            raise CoordinationError(
                "SQLite runtime is older than the WAL safety floor",
                details={
                    "runtime": apsw.sqlite_lib_version(),
                    "required": ".".join(map(str, MIN_SAFE_WAL_SQLITE)),
                },
            )
        self.initialize()

    def connect(self) -> apsw.Connection:
        conn = apsw.Connection(str(self.path))
        conn.set_row_trace(_dict_row)
        conn.set_busy_timeout(self.busy_timeout_ms)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def initialize(self) -> None:
        conn = self.connect()
        try:
            mode = scalar(conn.execute("PRAGMA journal_mode=WAL"))
            if str(mode).lower() != "wal":
                raise CoordinationError("Could not enable SQLite WAL mode", details={"journal_mode": mode})
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = int(scalar(conn.execute("PRAGMA user_version")))
                if current > SCHEMA_VERSION:
                    raise CoordinationError(
                        "Database schema is newer than this program",
                        details={"database": current, "program": SCHEMA_VERSION},
                    )
                if current == 0:
                    conn.execute(SCHEMA_V1)
                    conn.execute(
                        "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_name',?)",
                        ("xinao.dual_brain_coordination",),
                    )
                    current = 1
                if current == 1:
                    conn.execute(SCHEMA_V2)
                    current = 2
                if current == 2:
                    conn.execute(SCHEMA_V3)
                    current = 3
                conn.execute(f"PRAGMA user_version={current}")
                conn.execute("COMMIT")
            except BaseException:
                with contextlib.suppress(apsw.SQLError):
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    @contextlib.contextmanager
    def write(self) -> Iterator[apsw.Connection]:
        conn = self.connect()
        delay = 0.01
        try:
            for attempt in range(6):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    break
                except apsw.BusyError:
                    if attempt == 5:
                        raise
                    time.sleep(delay)
                    delay *= 2
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                with contextlib.suppress(apsw.SQLError):
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    @contextlib.contextmanager
    def read(self) -> Iterator[apsw.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def execute_read(self, sql: str, bindings: Sequence[object] | None = None) -> list[dict[str, Any]]:
        with self.read() as conn:
            return rows_as_dicts(conn.execute(sql, bindings or ()))

    def health(self) -> dict[str, object]:
        with self.read() as conn:
            quick = scalar(conn.execute("PRAGMA quick_check"))
            foreign = list(conn.execute("PRAGMA foreign_key_check"))
            journal = scalar(conn.execute("PRAGMA journal_mode"))
            schema = int(scalar(conn.execute("PRAGMA user_version")))
        return {
            "ok": quick == "ok" and not foreign and schema == SCHEMA_VERSION,
            "database": str(self.path),
            "sqlite": apsw.sqlite_lib_version(),
            "apsw": apsw.apsw_version(),
            "journal_mode": journal,
            "schema_version": schema,
            "quick_check": quick,
            "foreign_key_violations": len(foreign),
        }

    def backup_to(self, destination: str | Path) -> dict[str, object]:
        """Create a consistent online backup through SQLite's backup API."""

        target = Path(destination).resolve()
        if target.exists():
            raise CoordinationError("backup destination already exists", details={"destination": str(target)})
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        output = apsw.Connection(str(target))
        try:
            with output.backup("main", source, "main") as backup:
                while not backup.done:
                    backup.step(256)
        finally:
            output.close()
            source.close()
        verification = Database(target).health()
        return {
            "ok": bool(verification["ok"]),
            "source": str(self.path),
            "destination": str(target),
            "verification": verification,
        }
