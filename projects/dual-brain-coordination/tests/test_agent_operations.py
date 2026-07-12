from __future__ import annotations

import os
from pathlib import Path

import apsw
import pytest

from xinao_coordination.agent_operations import AgentOperationStore
from xinao_coordination.agent_worker import (
    finish_cancel_before_start,
    record_transport_fenced,
    run,
)
from xinao_coordination.database import SCHEMA_V1
from xinao_coordination.errors import ConflictError, InvalidTransitionError, LeaseError


def submit(store: AgentOperationStore, suffix: str = "one") -> dict[str, object]:
    return store.submit(
        actor="codex",
        prompt=f"review {suffix}",
        session_name="brain-main",
        cwd=Path.cwd(),
        idempotency_key=f"submit-{suffix}",
    )


def test_submit_is_durable_and_idempotent(db_path: Path) -> None:
    store = AgentOperationStore(db_path)
    first = submit(store)
    replay = submit(store)
    assert first["operation"]["operation_id"] == replay["operation"]["operation_id"]
    assert replay["replayed"] is True
    assert first["operation"]["request_id"] == first["operation"]["operation_id"]
    assert first["operation"]["replay_safe"] == 0
    with pytest.raises(ConflictError):
        store.submit(
            actor="codex",
            prompt="different",
            session_name="brain-main",
            cwd=Path.cwd(),
            idempotency_key="submit-one",
        )


def test_expired_running_lease_is_fenced_without_blind_replay(db_path: Path) -> None:
    now = [1_000_000]
    store = AgentOperationStore(db_path, clock_ms=lambda: now[0])
    operation_id = submit(store)["operation"]["operation_id"]
    first = store.claim(operation_id, worker_id="worker-a", lease_seconds=1)
    first_token = first["lease_token"]
    first_epoch = first["control_epoch"]
    store.mark_running(
        operation_id,
        lease_token=first_token,
        control_epoch=first_epoch,
        worker_id="worker-a",
        collector_pid=101,
        collector_start_time_ms=now[0],
        event_log_path="D:/events-a.ndjson",
        stderr_log_path="D:/stderr-a.log",
    )
    now[0] += 1_001
    with pytest.raises(InvalidTransitionError):
        store.claim(operation_id, worker_id="worker-b", lease_seconds=60)
    uncertain = store.get(operation_id)["operation"]
    assert uncertain["state"] == "uncertain"
    assert uncertain["stop_reason"] == "transport_outcome_unknown"
    with pytest.raises(LeaseError):
        store.finish(
            operation_id,
            lease_token=first_token,
            control_epoch=first_epoch,
            outcome="completed",
            stop_reason="late",
        )
    next_operation_id = str(submit(store, "next")["operation"]["operation_id"])
    with pytest.raises(LeaseError):
        store.claim(next_operation_id, worker_id="worker-c", lease_seconds=60)


def test_cancel_request_is_durable_and_bumps_control_epoch(db_path: Path) -> None:
    store = AgentOperationStore(db_path)
    operation_id = submit(store)["operation"]["operation_id"]
    claimed = store.claim(operation_id, worker_id="worker", lease_seconds=60)
    before = claimed["operation"]["control_epoch"]
    canceled = store.request_cancel(operation_id, actor="codex", reason="user requested")
    assert canceled["operation"]["state"] == "cancel_requested"
    assert canceled["operation"]["control_epoch"] == before + 1
    assert canceled["operation"]["lease_token"] == claimed["lease_token"]
    with pytest.raises(LeaseError):
        store.finish(
            operation_id,
            lease_token=claimed["lease_token"],
            control_epoch=claimed["control_epoch"],
            outcome="completed",
            stop_reason="late completion",
        )
    repeated = store.request_cancel(operation_id, actor="codex", reason="repeat")
    assert repeated["already_requested"] is True
    assert repeated["operation"]["control_epoch"] == canceled["operation"]["control_epoch"]


def test_worker_consumes_cancel_that_races_handoff(db_path: Path) -> None:
    store = AgentOperationStore(db_path)
    operation_id = str(submit(store)["operation"]["operation_id"])
    claimed = store.claim(operation_id, worker_id="launcher", lease_seconds=60)
    lease_token = str(claimed["lease_token"])
    store.request_cancel(operation_id, actor="codex", reason="handoff race")

    assert finish_cancel_before_start(store, operation_id, lease_token) is True
    current = store.get(operation_id)["operation"]
    assert current["state"] == "canceled"
    assert current["stop_reason"] == "canceled_before_transport_start"
    assert current["lease_token"] is None


def test_cancel_lease_expiry_cannot_remain_permanently_requested(db_path: Path) -> None:
    now = [2_000_000]
    store = AgentOperationStore(db_path, clock_ms=lambda: now[0])
    operation_id = str(submit(store)["operation"]["operation_id"])
    store.claim(operation_id, worker_id="launcher", lease_seconds=1)
    store.request_cancel(operation_id, actor="codex", reason="cancel handoff")
    now[0] += 1_001

    sweep = store.sweep()
    current = store.get(operation_id)["operation"]
    assert sweep["expired_agent_operation_leases"] == 1
    assert current["state"] == "canceled"
    assert current["stop_reason"] == "canceled_before_transport_start"
    assert current["lease_token"] is None


def test_record_transport_refreshes_only_cancel_epoch(db_path: Path) -> None:
    store = AgentOperationStore(db_path)
    operation_id = str(submit(store)["operation"]["operation_id"])
    claimed = store.claim(operation_id, worker_id="worker", lease_seconds=60)
    store.mark_running(
        operation_id,
        lease_token=str(claimed["lease_token"]),
        control_epoch=int(claimed["control_epoch"]),
        worker_id="worker",
        collector_pid=101,
        collector_start_time_ms=1,
        event_log_path="D:/events.ndjson",
        stderr_log_path="D:/stderr.log",
    )
    canceled = store.request_cancel(operation_id, actor="codex", reason="concurrent cancel")
    epoch = record_transport_fenced(
        store,
        operation_id,
        str(claimed["lease_token"]),
        int(claimed["control_epoch"]),
        acpx_record_id="record",
        agent_session_id="session",
    )
    assert epoch == canceled["operation"]["control_epoch"]
    current = store.get(operation_id)["operation"]
    assert current["acpx_record_id"] == "record"
    assert current["state"] == "cancel_requested"


def test_deadline_before_transport_is_terminal(db_path: Path) -> None:
    now = [3_000_000]
    store = AgentOperationStore(db_path, clock_ms=lambda: now[0])
    operation = store.submit(
        actor="codex",
        prompt="deadline",
        session_name="deadline",
        cwd=Path.cwd(),
        deadline_seconds=1,
        idempotency_key="deadline",
    )["operation"]
    now[0] += 1_001
    sweep = store.sweep()
    current = store.get(str(operation["operation_id"]))["operation"]
    assert sweep["deadline_prestart_completions"] == 1
    assert current["state"] == "deadline_exceeded"
    assert current["stop_reason"] == "deadline_before_transport_start"


def test_worker_marks_running_before_transport_spawn(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AgentOperationStore(db_path)
    operation_id = str(
        store.submit(
            actor="codex",
            prompt="bridge ordering",
            session_name="ordering",
            cwd=tmp_path,
            idempotency_key="bridge-ordering",
        )["operation"]["operation_id"]
    )
    runtime_path = tmp_path / "runtime.js"
    node_path = tmp_path / "node.exe"
    runner_path = tmp_path / "runner.mjs"
    for path in (runtime_path, node_path, runner_path):
        path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(
        "xinao_coordination.agent_worker.read_acpx_runtime",
        lambda: {"node": node_path, "runner": runner_path, "runtime_module": runtime_path},
    )
    observed: dict[str, object] = {}

    def fail_spawn(*args: object, **kwargs: object) -> None:
        current = store.get(operation_id)["operation"]
        observed["state"] = current["state"]
        observed["collector_pid"] = current["collector_pid"]
        raise OSError("isolated spawn failure")

    monkeypatch.setattr("xinao_coordination.agent_worker.subprocess.Popen", fail_spawn)
    assert run(operation_id, db_path) == 2
    assert observed == {"state": "running", "collector_pid": os.getpid()}
    current = store.get(operation_id)["operation"]
    assert current["state"] == "failed"
    assert current["stop_reason"] == "runner_spawn_failed"
    assert current["attempt_count"] == 1


def test_v1_database_migrates_without_losing_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "v1.sqlite3"
    conn = apsw.Connection(str(path))
    conn.execute(SCHEMA_V1)
    conn.execute("INSERT INTO meta(key,value) VALUES('sentinel','preserved')")
    conn.execute("PRAGMA user_version=1")
    conn.close()

    store = AgentOperationStore(path)
    assert store.db.health()["schema_version"] == 3
    with store.db.read() as migrated:
        value = migrated.execute("SELECT value FROM meta WHERE key='sentinel'").fetchone()["value"]
        tables = {row["name"] for row in migrated.execute("SELECT name FROM sqlite_master")}
    assert value == "preserved"
    assert "agent_operations" in tables
    assert "agent_operation_artifacts" in tables
    assert "task_attempts" in tables
    assert "workers" in tables
