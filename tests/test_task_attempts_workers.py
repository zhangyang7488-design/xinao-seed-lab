"""SCHEMA_V3: task_attempts + workers thin ledger write paths."""

from __future__ import annotations

from pathlib import Path

import apsw

from xinao_coordination import CoordinationService
from xinao_coordination.database import SCHEMA_V1, SCHEMA_V2, Database


def _dispatch(service: CoordinationService, key: str = "dispatch", **kwargs: object) -> str:
    result = service.dispatch_task(
        actor="codex", title="task", goal="goal", idempotency_key=key, **kwargs
    )
    return str(result["task"]["task_id"])


def test_schema_v3_fresh_db_has_attempts_and_workers(db_path: Path) -> None:
    db = Database(db_path)
    health = db.health()
    assert health["ok"] is True
    assert health["schema_version"] == 3
    with db.read() as conn:
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
    assert "task_attempts" in names
    assert "workers" in names
    assert "artifacts" in names


def test_v2_migrates_to_v3_preserving_rows(tmp_path: Path) -> None:
    path = tmp_path / "v2.sqlite3"
    conn = apsw.Connection(str(path))
    conn.execute(SCHEMA_V1)
    conn.execute(SCHEMA_V2)
    conn.execute("INSERT INTO meta(key,value) VALUES('sentinel','v2-preserved')")
    conn.execute("PRAGMA user_version=2")
    conn.close()

    db = Database(path)
    assert db.health()["schema_version"] == 3
    with db.read() as migrated:
        value = migrated.execute("SELECT value FROM meta WHERE key='sentinel'").fetchone()["value"]
        tables = {
            row["name"] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert value == "v2-preserved"
    assert "task_attempts" in tables
    assert "workers" in tables


def test_claim_start_complete_writes_attempt_and_worker(service: CoordinationService) -> None:
    task_id = _dispatch(service)
    claim = service.claim_task(worker_id="worker-alpha", idempotency_key="claim")
    token = str(claim["lease_token"])
    assert claim["attempt_id"]
    assert claim["task"]["attempt_count"] == 1

    service.start_task(task_id=task_id, lease_token=token, idempotency_key="start")
    mid = service.get_task(task_id)
    assert len(mid["attempts"]) == 1
    assert mid["attempts"][0]["state"] == "running"
    assert mid["attempts"][0]["worker_id"] == "worker-alpha"
    assert mid["attempts"][0]["attempt_no"] == 1

    done = service.complete_task(
        task_id=task_id,
        lease_token=token,
        result_summary="ok",
        evidence=[{"kind": "pytest", "result": "pass"}],
        artifacts=[{"uri": "file:///D:/tmp/out.txt", "name": "out.txt"}],
        idempotency_key="complete",
    )
    assert done["task"]["state"] == "completed"
    assert len(done["attempts"]) == 1
    assert done["attempts"][0]["state"] == "completed"
    assert done["attempts"][0]["result_summary"] == "ok"
    assert len(done["artifacts"]) == 1

    with service.db.read() as conn:
        worker = conn.execute(
            "SELECT * FROM workers WHERE worker_id=?", ("worker-alpha",)
        ).fetchone()
    assert worker is not None
    assert worker["status"] == "online"
    assert worker["last_task_id"] == task_id


def test_fail_retry_opens_second_attempt(service: CoordinationService) -> None:
    task_id = _dispatch(service, max_attempts=3)
    claim1 = service.claim_task(worker_id="w1", idempotency_key="c1")
    token1 = str(claim1["lease_token"])
    service.start_task(task_id=task_id, lease_token=token1, idempotency_key="s1")
    failed = service.fail_task(
        task_id=task_id,
        lease_token=token1,
        error="boom",
        retryable=True,
        idempotency_key="f1",
    )
    assert failed["retry"] is True
    assert failed["attempts"][0]["state"] == "requeued"

    claim2 = service.claim_task(worker_id="w2", idempotency_key="c2")
    token2 = str(claim2["lease_token"])
    service.start_task(task_id=task_id, lease_token=token2, idempotency_key="s2")
    got = service.get_task(task_id)
    assert got["task"]["attempt_count"] == 2
    assert len(got["attempts"]) == 2
    assert got["attempts"][1]["worker_id"] == "w2"
    assert got["attempts"][1]["state"] == "running"


def test_lease_expire_marks_attempt_expired(db_path: Path) -> None:
    now = [1_000_000]
    service = CoordinationService(db_path, clock_ms=lambda: now[0])
    task_id = _dispatch(service, max_attempts=1)
    claim = service.claim_task(worker_id="exp-w", lease_seconds=1, idempotency_key="claim")
    token = str(claim["lease_token"])
    assert token
    now[0] += 1_001
    sweep = service.sweep()
    assert sweep["task_leases"]["failed"] == 1
    got = service.get_task(task_id)
    assert got["task"]["state"] == "failed"
    assert len(got["attempts"]) == 1
    assert got["attempts"][0]["state"] == "expired"
    assert got["attempts"][0]["failure_reason"] == "lease_exhausted"


def test_stop_does_not_rewrite_finished_requeued_attempt_history(
    service: CoordinationService,
) -> None:
    task_id = _dispatch(service, key="dispatch-requeue-stop", max_attempts=3)
    claim = service.claim_task(worker_id="requeue-w", idempotency_key="requeue-claim")
    token = str(claim["lease_token"])
    service.start_task(task_id=task_id, lease_token=token, idempotency_key="requeue-start")
    failed = service.fail_task(
        task_id=task_id,
        lease_token=token,
        error="retryable",
        retryable=True,
        idempotency_key="requeue-fail",
    )
    before = failed["attempts"][0]
    assert before["state"] == "requeued"
    assert before["finished_at_ms"] is not None

    service.user_stop(
        actor="user",
        reason="stop queued task without rewriting history",
        idempotency_key="requeue-stop",
    )
    after = service.get_task(task_id)["attempts"][0]

    assert after["state"] == "requeued"
    assert after["finished_at_ms"] == before["finished_at_ms"]
    assert after["failure_reason"] == before["failure_reason"]
