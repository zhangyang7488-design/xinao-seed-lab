"""T1+T2+T5 rollback & negative checklist (isolated tmp DB; never live stack).

Negative / rollback invariants:
1. AMQ disabled or binary missing → coordination kernel still usable
2. After Stop → no new promote (or dispatch)
3. Process restart → sqlite file recovers thread/task/stop meta
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xinao_coordination import CoordinationService
from xinao_coordination.amq.transport import AmqTransport, AmqTransportError
from xinao_coordination.errors import InvalidTransitionError


def _accept_thread(service: CoordinationService, suffix: str, resolution: str = "rb-v1") -> str:
    opened = service.open_thread(
        actor="grok_4_5",
        title=f"rollback-{suffix}",
        body=f"proposal {suffix}",
        idempotency_key=f"rb-open-{suffix}",
    )
    thread_id = str(opened["thread"]["thread_id"])
    service.post_message(
        actor="codex",
        thread_id=thread_id,
        body=f"counter {suffix}",
        kind="counter",
        idempotency_key=f"rb-post-{suffix}",
    )
    service.close_thread(
        actor="grok_4_5",
        thread_id=thread_id,
        decision="accept",
        resolution_key=resolution,
        summary="grok accepts",
        idempotency_key=f"rb-close-g-{suffix}",
    )
    closed = service.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key=resolution,
        summary="codex accepts",
        idempotency_key=f"rb-close-c-{suffix}",
    )
    assert closed["thread"]["state"] == "ACCEPTED"
    return thread_id


def test_kernel_usable_when_amq_disabled_or_missing(tmp_path: Path) -> None:
    """Disabling AMQ (no adapter call / missing bin) must not block kernel discuss→promote."""
    db_path = tmp_path / "kernel_no_amq.sqlite3"
    service = CoordinationService(db_path)

    # Kernel path with zero AMQ involvement
    thread_id = _accept_thread(service, "no-amq", resolution="no-amq-hash")
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="no-amq-hash",
        title="kernel-only task",
        goal="prove AMQ is optional thin adapter",
        idempotency_key="no-amq-promote",
    )
    assert promoted["ok"] is True
    assert promoted["task"]["state"] == "queued"
    assert promoted["task"]["metadata"]["promoted"] is True
    health = service.db.health()
    assert health["ok"] is True
    assert health["foreign_key_violations"] == 0

    # Explicit negative: missing amq binary fails transport only
    missing_bin = tmp_path / "not-installed" / "amq.exe"
    transport = AmqTransport(bin_path=missing_bin, root=tmp_path / "amq-root")
    with pytest.raises(AmqTransportError) as exc:
        transport.version()
    assert "missing" in str(exc.value).lower() or "amq" in str(exc.value).lower()

    # Kernel still works after failed AMQ probe
    opened = service.open_thread(
        actor="user",
        title="post-amq-fail",
        body="kernel independent",
        idempotency_key="post-amq-fail-open",
    )
    assert opened["thread"]["state"] in {"OPEN", "ACTIVE", "open", "active"} or opened["ok"] is True
    assert service.db.health()["ok"] is True


def test_stop_blocks_new_promote_and_dispatch(tmp_path: Path) -> None:
    """After user Stop: no new promote; no new dispatch; clear_stop is explicit only."""
    db_path = tmp_path / "stop_block.sqlite3"
    service = CoordinationService(db_path)

    accepted = _accept_thread(service, "pre-stop", resolution="pre-stop-hash")
    pre = service.promote_to_task(
        actor="codex",
        source_thread_id=accepted,
        decision_hash="pre-stop-hash",
        title="before stop",
        goal="allowed",
        idempotency_key="pre-stop-promote",
    )
    assert pre["task"]["state"] == "queued"

    stop = service.user_stop(actor="user", reason="rollback negative checklist", idempotency_key="rb-stop")
    assert stop["active"] is True
    assert service.stop_status()["active"] is True

    blocked_thread = _accept_thread(service, "during-stop", resolution="during-stop-hash")
    with pytest.raises(InvalidTransitionError) as promote_exc:
        service.promote_to_task(
            actor="codex",
            source_thread_id=blocked_thread,
            decision_hash="during-stop-hash",
            title="must not promote",
            goal="blocked by stop",
            idempotency_key="during-stop-promote",
        )
    assert "stop" in str(promote_exc.value).lower()

    with pytest.raises(InvalidTransitionError) as dispatch_exc:
        service.dispatch_task(
            actor="codex",
            title="direct dispatch blocked",
            goal="also blocked",
            idempotency_key="during-stop-dispatch",
        )
    assert "stop" in str(dispatch_exc.value).lower()

    # No auto-resume: status still active until clear
    assert service.stop_status()["active"] is True
    tasks_after = service.list_tasks(limit=50)["tasks"]
    assert isinstance(tasks_after, list)
    # only the pre-stop promote exists as a task from this fixture (may be canceled by stop)
    promote_ids = {str(pre["task"]["task_id"])}
    for t in tasks_after:
        if t.get("metadata", {}).get("promoted") and t["task_id"] not in promote_ids:
            # any extra promoted task during stop is a hard fail
            raise AssertionError(f"unexpected promote during stop: {t['task_id']}")

    cleared = service.clear_stop(actor="user", reason="explicit resume", idempotency_key="rb-stop-clear")
    assert cleared["active"] is False
    after = service.promote_to_task(
        actor="codex",
        source_thread_id=blocked_thread,
        decision_hash="during-stop-hash",
        title="after clear",
        goal="allowed again",
        idempotency_key="after-clear-promote",
    )
    assert after["task"]["state"] == "queued"


def test_restart_recovers_state_from_same_sqlite_file(tmp_path: Path) -> None:
    """Simulate process death/restart: new CoordinationService on same sqlite path recovers state."""
    db_path = tmp_path / "restart_coord.sqlite3"
    stop_dir = tmp_path / "stop"
    stop_dir.mkdir(parents=True, exist_ok=True)

    import os

    os.environ["XINAO_COORD_STOP_DIR"] = str(stop_dir)

    s1 = CoordinationService(db_path)
    thread_id = _accept_thread(s1, "restart", resolution="restart-hash")
    promoted = s1.promote_to_task(
        actor="grok_4_5",
        source_thread_id=thread_id,
        decision_hash="restart-hash",
        title="durable promote",
        goal="survive process restart",
        idempotency_key="restart-promote",
    )
    task_id = str(promoted["task"]["task_id"])
    s1.user_stop(actor="user", reason="freeze before restart", idempotency_key="restart-stop")
    assert s1.stop_status()["active"] is True
    health1 = s1.db.health()
    assert health1["ok"] is True
    del s1  # drop handle (process exit simulation)

    # Re-open same file (WAL companions auto-merged by SQLite on connect)
    s2 = CoordinationService(db_path)
    assert s2.db.health()["ok"] is True
    thread = s2.get_thread(thread_id)["thread"]
    assert thread["state"] == "ACCEPTED"
    assert thread["close_resolution_key"] == "restart-hash"
    task = s2.get_task(task_id)["task"]
    assert task["task_id"] == task_id
    assert task["source_thread_id"] == thread_id
    assert task["metadata"].get("promoted") is True
    # stop meta is durable in sqlite
    assert s2.stop_status()["active"] is True

    with pytest.raises(InvalidTransitionError):
        s2.promote_to_task(
            actor="codex",
            source_thread_id=thread_id,
            decision_hash="restart-hash",
            title="still blocked after restart",
            goal="stop must persist",
            idempotency_key="post-restart-blocked",
        )

    # Online backup also recovers on a separate path (ops recovery path)
    backup = tmp_path / "backup" / "coordination.sqlite3"
    s2.backup(backup)
    s3 = CoordinationService(backup)
    assert s3.get_thread(thread_id)["thread"]["state"] == "ACCEPTED"
    assert s3.get_task(task_id)["task"]["task_id"] == task_id
    assert s3.stop_status()["active"] is True
    assert s3.db.health()["foreign_key_violations"] == 0


def test_sqlite_files_exist_as_recovery_unit(tmp_path: Path) -> None:
    """Document/assert recovery unit: primary sqlite file is the durable authority."""
    db_path = tmp_path / "unit.sqlite3"
    service = CoordinationService(db_path)
    _accept_thread(service, "files", resolution="files-hash")
    assert db_path.is_file()
    # WAL may or may not exist depending on checkpoint timing; primary file is required
    assert service.db.health()["journal_mode"] in {"wal", "WAL", "delete"}
    # reopen without AMQ, without stop clear → still healthy
    reopened = CoordinationService(db_path)
    assert reopened.db.health()["ok"] is True
    listed = reopened.list_tasks(limit=10)
    assert listed["ok"] is True or "tasks" in listed
