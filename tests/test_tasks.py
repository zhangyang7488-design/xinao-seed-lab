from __future__ import annotations

from pathlib import Path

import apsw
import pytest

from xinao_coordination import CoordinationService
from xinao_coordination.a2a_adapter import export_task_dict
from xinao_coordination.errors import LeaseError, ValidationError


def _dispatch(service: CoordinationService, key: str = "dispatch", **kwargs: object) -> str:
    result = service.dispatch_task(actor="codex", title="task", goal="goal", idempotency_key=key, **kwargs)
    return str(result["task"]["task_id"])


def test_full_task_lifecycle_requires_evidence(service: CoordinationService) -> None:
    task_id = _dispatch(service)
    claim = service.claim_task(idempotency_key="claim")
    token = str(claim["lease_token"])
    assert claim["task"]["task_id"] == task_id
    service.start_task(task_id=task_id, lease_token=token, idempotency_key="start")
    with pytest.raises(ValidationError):
        service.complete_task(
            task_id=task_id,
            lease_token=token,
            result_summary="done",
            evidence=[],
            idempotency_key="bad-complete",
        )
    result = service.complete_task(
        task_id=task_id,
        lease_token=token,
        result_summary="done",
        evidence=[{"kind": "pytest", "result": "pass"}],
        idempotency_key="complete",
    )
    assert result["task"]["state"] == "completed"
    assert result["verification_status"] == "evidence_attached_not_independently_verified"


def test_claim_idempotency_returns_same_lease(service: CoordinationService) -> None:
    _dispatch(service)
    first = service.claim_task(idempotency_key="claim")
    second = service.claim_task(idempotency_key="claim")
    assert first["lease_token"] == second["lease_token"]
    assert second["replayed"] is True


def test_pause_fences_old_worker_and_resume_requeues(service: CoordinationService) -> None:
    task_id = _dispatch(service)
    claim = service.claim_task(idempotency_key="claim")
    old_token = str(claim["lease_token"])
    paused = service.pause_task(actor="user", task_id=task_id, reason="takeover", idempotency_key="pause")
    assert paused["task"]["state"] == "paused"
    with pytest.raises(LeaseError):
        service.start_task(task_id=task_id, lease_token=old_token, idempotency_key="stale")
    service.resume_task(actor="user", task_id=task_id, reason="continue", idempotency_key="resume")
    new_claim = service.claim_task(idempotency_key="new-claim")
    assert new_claim["task"]["task_id"] == task_id
    assert new_claim["lease_token"] != old_token


def test_expired_lease_is_recovered_and_fenced(db_path: Path) -> None:
    now = [1_000_000]
    service = CoordinationService(db_path, clock_ms=lambda: now[0])
    task_id = _dispatch(service, max_attempts=3)
    first = service.claim_task(lease_seconds=1, idempotency_key="claim-1")
    old_token = str(first["lease_token"])
    now[0] += 1_001
    recovered = service.claim_task(lease_seconds=5, idempotency_key="claim-2")
    assert recovered["task"]["task_id"] == task_id
    assert recovered["task"]["attempt_count"] == 2
    assert recovered["recovered"]["requeued"] == 1
    assert recovered["lease_token"] != old_token
    with pytest.raises(LeaseError):
        service.start_task(task_id=task_id, lease_token=old_token, idempotency_key="old-start")


def test_retry_stops_at_max_attempts(db_path: Path) -> None:
    now = [1_000_000]
    service = CoordinationService(db_path, clock_ms=lambda: now[0])
    task_id = _dispatch(service, max_attempts=1)
    claim = service.claim_task(lease_seconds=1, idempotency_key="claim")
    now[0] += 1_001
    sweep = service.sweep()
    assert sweep["task_leases"]["failed"] == 1
    assert service.get_task(task_id)["task"]["state"] == "failed"
    assert claim["task"]["attempt_count"] == 1


def test_completion_transaction_rolls_back_on_duplicate_artifact(service: CoordinationService) -> None:
    task_id = _dispatch(service)
    claim = service.claim_task(idempotency_key="claim")
    token = str(claim["lease_token"])
    service.start_task(task_id=task_id, lease_token=token, idempotency_key="start")
    artifact = {"uri": "file:///D:/same.txt", "name": "same.txt"}
    with pytest.raises(apsw.ConstraintError):
        service.complete_task(
            task_id=task_id,
            lease_token=token,
            result_summary="should rollback",
            evidence=[{"kind": "test"}],
            artifacts=[artifact, artifact],
            idempotency_key="complete",
        )
    current = service.get_task(task_id)
    assert current["task"]["state"] == "running"
    assert current["artifacts"] == []


def test_register_local_artifact_hashes_real_file(service: CoordinationService, tmp_path: Path) -> None:
    task_id = _dispatch(service)
    artifact = tmp_path / "evidence.txt"
    artifact.write_text("evidence", encoding="utf-8")
    result = service.register_local_artifact(
        actor="codex",
        task_id=task_id,
        path=artifact,
        media_type="text/plain",
        idempotency_key="artifact",
    )
    assert result["artifact"]["sha256"] == hashlib_sha256(b"evidence")
    assert result["artifact"]["size_bytes"] == 8


def hashlib_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def test_a2a_export_uses_official_task_shape(service: CoordinationService) -> None:
    task_id = _dispatch(service)
    exported = export_task_dict(service, task_id)
    assert exported["id"] == task_id
    assert exported["status"]["state"] == "TASK_STATE_SUBMITTED"
    assert exported["metadata"]["xinao_assigned_role"] == "admin"


def test_task_event_versions_are_contiguous(service: CoordinationService) -> None:
    task_id = _dispatch(service)
    claim = service.claim_task(idempotency_key="claim")
    service.start_task(task_id=task_id, lease_token=str(claim["lease_token"]), idempotency_key="start")
    events = service.events(stream_type="task", stream_id=task_id)["events"]
    assert [event["stream_version"] for event in events] == [1, 2, 3]


def test_online_backup_is_integrity_checked(service: CoordinationService, tmp_path: Path) -> None:
    task_id = _dispatch(service)
    destination = tmp_path / "backup" / "coordination.sqlite3"
    result = service.backup(destination)
    assert result["ok"] is True
    restored = CoordinationService(destination)
    assert restored.get_task(task_id)["task"]["task_id"] == task_id
    assert restored.db.health()["foreign_key_violations"] == 0
