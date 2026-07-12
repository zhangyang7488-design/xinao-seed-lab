"""T1+T2+T5 vertical slice: deliver → receive → discuss → close → promote.

Required scenarios:
- duplicate delivery idempotency
- role permissions
- CAS/version conflicts
- restart recovery
- Stop
- error promotion rejection
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from xinao_coordination import CoordinationService
from xinao_coordination.amq import AmqIngestor, AmqTransport
from xinao_coordination.amq.mapping import envelope_from_amq_message, payload_sha256
from xinao_coordination.cli import build_parser, execute
from xinao_coordination.errors import (
    AuthorizationError,
    ConflictError,
    InvalidTransitionError,
)

AMQ_BIN = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe")
CANARY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary")


def _amq_available() -> bool:
    return AMQ_BIN.is_file()


@pytest.fixture
def canary_db(tmp_path: Path) -> Path:
    # Prefer isolated tmp DB for unit correctness; canary path used in live smoke.
    return tmp_path / "coordination.sqlite3"


@pytest.fixture
def svc(canary_db: Path) -> CoordinationService:
    return CoordinationService(canary_db)


def _accept_thread(service: CoordinationService, suffix: str, resolution: str = "dec-v1") -> str:
    opened = service.open_thread(
        actor="grok_4_5",
        title=f"slice-{suffix}",
        body=f"proposal {suffix}",
        idempotency_key=f"open-{suffix}",
    )
    thread_id = str(opened["thread"]["thread_id"])
    service.post_message(
        actor="codex",
        thread_id=thread_id,
        body=f"counter {suffix}",
        kind="counter",
        idempotency_key=f"post-codex-{suffix}",
    )
    service.close_thread(
        actor="grok_4_5",
        thread_id=thread_id,
        decision="accept",
        resolution_key=resolution,
        summary="grok accepts",
        idempotency_key=f"close-g-{suffix}",
    )
    closed = service.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key=resolution,
        summary="codex accepts",
        idempotency_key=f"close-c-{suffix}",
    )
    assert closed["thread"]["state"] == "ACCEPTED"
    return thread_id


def test_role_admin_cannot_discuss_or_promote(svc: CoordinationService) -> None:
    with pytest.raises(AuthorizationError):
        svc.open_thread(actor="admin", title="nope", idempotency_key="admin-open")
    thread_id = _accept_thread(svc, "admin-gate")
    with pytest.raises(AuthorizationError):
        svc.promote_to_task(
            actor="admin",
            source_thread_id=thread_id,
            decision_hash="dec-v1",
            title="t",
            goal="g",
            idempotency_key="admin-promote",
        )


def test_cas_version_conflict_on_post(svc: CoordinationService) -> None:
    opened = svc.open_thread(actor="codex", title="cas", body="a", idempotency_key="cas-open")
    version = int(opened["thread"]["version"])
    thread_id = str(opened["thread"]["thread_id"])
    svc.post_message(
        actor="grok_4_5",
        thread_id=thread_id,
        body="b",
        expected_version=version,
        idempotency_key="cas-p1",
    )
    with pytest.raises(ConflictError):
        svc.post_message(
            actor="codex",
            thread_id=thread_id,
            body="stale",
            expected_version=version,
            idempotency_key="cas-p2",
        )


def test_duplicate_idempotency_open_and_promote(svc: CoordinationService) -> None:
    first = svc.open_thread(actor="codex", title="idem", body="x", idempotency_key="same-open")
    replay = svc.open_thread(actor="codex", title="idem", body="x", idempotency_key="same-open")
    assert replay["replayed"] is True
    assert replay["thread"]["thread_id"] == first["thread"]["thread_id"]
    with pytest.raises(ConflictError):
        svc.open_thread(actor="codex", title="changed", body="y", idempotency_key="same-open")

    thread_id = _accept_thread(svc, "idem-promote", resolution="hash-1")
    p1 = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="hash-1",
        title="work",
        goal="do it",
        idempotency_key="promote-same",
    )
    p2 = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="hash-1",
        title="work",
        goal="do it",
        idempotency_key="promote-same",
    )
    assert p2["replayed"] is True
    assert p2["task"]["task_id"] == p1["task"]["task_id"]


def test_error_promotion_rejected_when_not_accepted_or_hash_mismatch(svc: CoordinationService) -> None:
    opened = svc.open_thread(actor="grok_4_5", title="open-only", body="chat", idempotency_key="err-open")
    thread_id = str(opened["thread"]["thread_id"])
    with pytest.raises(InvalidTransitionError):
        svc.promote_to_task(
            actor="codex",
            source_thread_id=thread_id,
            decision_hash="anything",
            title="t",
            goal="g",
            idempotency_key="err-promote-open",
        )
    accepted = _accept_thread(svc, "hash-mismatch", resolution="correct-hash")
    with pytest.raises(ConflictError):
        svc.promote_to_task(
            actor="codex",
            source_thread_id=accepted,
            decision_hash="wrong-hash",
            title="t",
            goal="g",
            idempotency_key="err-promote-hash",
        )


def test_full_vertical_close_and_promote_lifecycle(svc: CoordinationService) -> None:
    thread_id = _accept_thread(svc, "lifecycle", resolution="life-v1")
    promoted = svc.promote_to_task(
        actor="grok_4_5",
        source_thread_id=thread_id,
        decision_hash="life-v1",
        title="promoted work",
        goal="execute accepted decision",
        writer_scope="canary",
        acceptance="pytest-evidence",
        idempotency_key="life-promote",
    )
    assert promoted["ok"] is True
    assert promoted["task"]["state"] == "queued"
    assert promoted["task"]["source_thread_id"] == thread_id
    assert promoted["task"]["consensus_status"] == "accepted"
    assert promoted["task"]["metadata"]["promoted"] is True
    claim = svc.claim_task(idempotency_key="life-claim")
    token = str(claim["lease_token"])
    svc.start_task(task_id=promoted["task"]["task_id"], lease_token=token, idempotency_key="life-start")
    done = svc.complete_task(
        task_id=promoted["task"]["task_id"],
        lease_token=token,
        result_summary="done",
        evidence=[{"kind": "vertical_slice", "ok": True}],
        idempotency_key="life-complete",
    )
    assert done["task"]["state"] == "completed"


def test_stop_blocks_promote_and_cancels_active(svc: CoordinationService) -> None:
    thread_id = _accept_thread(svc, "stop-case", resolution="stop-hash")
    promoted = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="stop-hash",
        title="will cancel",
        goal="g",
        idempotency_key="stop-promote",
    )
    task_id = str(promoted["task"]["task_id"])
    stop = svc.user_stop(actor="user", reason="user yelled stop", idempotency_key="stop-1")
    assert stop["active"] is True
    assert task_id in stop["canceled_tasks"]
    assert svc.get_task(task_id)["task"]["state"] == "canceled"
    other = _accept_thread(svc, "stop-block", resolution="block-hash")
    with pytest.raises(InvalidTransitionError):
        svc.promote_to_task(
            actor="codex",
            source_thread_id=other,
            decision_hash="block-hash",
            title="blocked",
            goal="g",
            idempotency_key="stop-blocked-promote",
        )
    # Stop does not auto-resume
    assert svc.stop_status()["active"] is True
    cleared = svc.clear_stop(actor="user", reason="resume authorized", idempotency_key="stop-clear")
    assert cleared["active"] is False
    again = svc.promote_to_task(
        actor="codex",
        source_thread_id=other,
        decision_hash="block-hash",
        title="after clear",
        goal="g",
        idempotency_key="after-clear-promote",
    )
    assert again["task"]["state"] == "queued"


def test_restart_recovery_from_backup(svc: CoordinationService, tmp_path: Path) -> None:
    thread_id = _accept_thread(svc, "restart", resolution="rest-v1")
    promoted = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="rest-v1",
        title="durable",
        goal="survive restart",
        idempotency_key="restart-promote",
    )
    task_id = str(promoted["task"]["task_id"])
    backup_path = tmp_path / "backup" / "coordination.sqlite3"
    svc.backup(backup_path)
    # Simulate process restart: new service instance on backup file
    restored = CoordinationService(backup_path)
    assert restored.get_thread(thread_id)["thread"]["state"] == "ACCEPTED"
    assert restored.get_task(task_id)["task"]["task_id"] == task_id
    assert restored.db.health()["foreign_key_violations"] == 0


def test_cli_promote_and_stop_parity(svc: CoordinationService, canary_db: Path) -> None:
    thread_id = _accept_thread(svc, "cli-parity", resolution="cli-hash")
    parser = build_parser()
    promote_args = parser.parse_args(
        [
            "--db",
            str(canary_db),
            "promote",
            "--actor",
            "codex",
            "--source-thread-id",
            thread_id,
            "--decision-hash",
            "cli-hash",
            "--title",
            "cli task",
            "--goal",
            "via cli",
            "--idempotency-key",
            "cli-promote",
        ]
    )
    result = execute(promote_args, CoordinationService(canary_db))
    assert result["ok"] is True
    assert result["task"]["source_thread_id"] == thread_id

    stop_args = parser.parse_args(
        [
            "--db",
            str(canary_db),
            "stop",
            "--actor",
            "user",
            "--reason",
            "cli stop",
            "--idempotency-key",
            "cli-stop",
        ]
    )
    stopped = execute(stop_args, CoordinationService(canary_db))
    assert stopped["active"] is True


def test_amq_envelope_mapping_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        envelope_from_amq_message({"id": "../evil", "from": "grok", "to": "codex", "body": "x"})
    env = envelope_from_amq_message(
        {
            "id": "2026-07-11T00-00-00Z_pid1_abc",
            "from": "grok",
            "to": "codex",
            "kind": "status",
            "body": "hello",
            "subject": "s",
        }
    )
    assert env["sender_role"] == "grok_4_5"
    assert env["recipient_role"] == "codex"
    assert env["payload_sha256"] == payload_sha256("hello", extra={"subject": "s", "kind": "status"})


@pytest.mark.skipif(not _amq_available(), reason="amq.exe not installed")
def test_amq_live_send_ingest_idempotent(tmp_path: Path) -> None:
    """Live AMQ → kernel ingest; duplicate logical ingest does not double-create work."""
    amq_root = tmp_path / "amq"
    transport = AmqTransport(bin_path=AMQ_BIN, root=amq_root)
    transport.init(["grok", "codex", "admin", "user"], force=True)
    db_path = tmp_path / "coord.sqlite3"
    service = CoordinationService(db_path)
    send1 = transport.send(
        me="grok",
        to="codex",
        body="vertical slice discuss body",
        subject="T1T2T5 canary",
        kind="status",
    )
    assert send1.get("id") or send1.get("message_id")
    ingestor = AmqIngestor(service, transport)
    first = ingestor.ingest_for_role(recipient_role="codex", limit=5)
    assert first["drained_count"] >= 1
    assert first["ingested"]
    thread_id = first["ingested"][0]["thread_id"]
    assert service.get_thread(thread_id)["thread"]["thread_id"] == thread_id
    # Second drain should be empty (already moved to cur)
    second = ingestor.ingest_for_role(recipient_role="codex", limit=5)
    assert second["drained_count"] == 0


@pytest.mark.skipif(not _amq_available(), reason="amq.exe not installed")
def test_canary_root_live_smoke_cli(tmp_path: Path) -> None:
    """Exercise canary AMQ root + kernel DB without touching production dual_brain_coordination."""
    canary_amq = CANARY_ROOT / "amq"
    canary_db = tmp_path / "canary_coord.sqlite3"  # avoid clobbering shared canary db mid-dev
    os.environ["XINAO_COORD_STOP_DIR"] = str(tmp_path / "stop")
    service = CoordinationService(canary_db)
    transport = AmqTransport(bin_path=AMQ_BIN, root=canary_amq)
    msg = transport.send(
        me="codex",
        to="grok",
        body="canary discuss",
        subject="canary-thread",
        kind="question",
    )
    assert msg
    result = AmqIngestor(service, transport).ingest_for_role(recipient_role="grok_4_5", limit=10)
    assert result["drained_count"] >= 1
    # complete discuss/close/promote path via service
    thread_id = result["ingested"][0]["thread_id"]
    service.post_message(
        actor="grok_4_5",
        thread_id=thread_id,
        body="ack canary",
        idempotency_key="canary-post-g",
    )
    # May already be ACTIVE; dual close
    service.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key="canary-dec",
        summary="ok",
        idempotency_key="canary-close-c",
    )
    closed = service.close_thread(
        actor="grok_4_5",
        thread_id=thread_id,
        decision="accept",
        resolution_key="canary-dec",
        summary="ok",
        idempotency_key="canary-close-g",
    )
    assert closed["thread"]["state"] == "ACCEPTED"
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="canary-dec",
        title="canary promoted",
        goal="prove vertical slice",
        idempotency_key="canary-promote",
    )
    assert promoted["task"]["state"] == "queued"
    evidence = {
        "thread_id": thread_id,
        "task_id": promoted["task"]["task_id"],
        "amq_message": msg,
        "stop_status": service.stop_status(),
    }
    out = CANARY_ROOT / "evidence" / "t1t2t5_live_smoke.json"
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
