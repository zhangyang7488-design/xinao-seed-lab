"""T5 — discuss (natural language) → propose_close/respond CAS → explicit promote_to_task.

Coverage required by kaigong slice T5:
- natural-language body discussion does not auto-create Task
- propose_close / respond with optimistic version CAS
- promote_to_task idempotent only after ACCEPTED + matching decision_hash
- error promotion rejection (no closure / hash mismatch)
- Stop freezes new promote/dispatch
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xinao_coordination import CoordinationService
from xinao_coordination.cli import build_parser, execute
from xinao_coordination.errors import ConflictError, InvalidTransitionError


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "t5_canary.sqlite3"


@pytest.fixture
def svc(db_path: Path) -> CoordinationService:
    return CoordinationService(db_path)


def _open_chat(svc: CoordinationService, suffix: str) -> tuple[str, int]:
    opened = svc.open_thread(
        actor="grok_4_5",
        title=f"t5-chat-{suffix}",
        body=f"闲聊正文 {suffix}：今天天气不错，先随便聊聊方案边界。",
        idempotency_key=f"t5-open-{suffix}",
    )
    thread = opened["thread"]
    assert isinstance(thread, dict)
    return str(thread["thread_id"]), int(thread["version"])


def _accept_via_propose_respond(
    svc: CoordinationService,
    *,
    suffix: str,
    decision_hash: str,
) -> str:
    thread_id, version = _open_chat(svc, suffix)
    svc.post_message(
        actor="codex",
        thread_id=thread_id,
        body=f"回应闲聊 {suffix}：同意先谈清再钉合同。",
        kind="reply",
        expected_version=version,
        idempotency_key=f"t5-post-{suffix}",
    )
    current = svc.get_thread(thread_id)["thread"]
    assert isinstance(current, dict)
    proposed = svc.propose_close(
        actor="grok_4_5",
        thread_id=thread_id,
        decision_hash=decision_hash,
        summary="propose consensus",
        proposal_id=f"prop-{suffix}",
        expected_version=int(current["version"]),
        unresolved_points=[],
        idempotency_key=f"t5-propose-{suffix}",
    )
    assert proposed["action"] == "thread.propose_close"
    assert proposed["thread"]["state"] == "CLOSING"
    after = proposed["thread"]
    assert isinstance(after, dict)
    responded = svc.respond(
        actor="codex",
        thread_id=thread_id,
        decision_hash=decision_hash,
        summary="peer accepts same hash",
        proposal_id=f"prop-{suffix}",
        expected_version=int(after["version"]),
        idempotency_key=f"t5-respond-{suffix}",
    )
    assert responded["action"] == "thread.respond"
    assert responded["thread"]["state"] == "ACCEPTED"
    assert responded["decision_hash"] == decision_hash
    return thread_id


def test_chat_natural_language_does_not_auto_create_task(svc: CoordinationService) -> None:
    thread_id, version = _open_chat(svc, "no-auto-task")
    svc.post_message(
        actor="codex",
        thread_id=thread_id,
        body="纯讨论，不该产生任何 Task。",
        kind="note",
        expected_version=version,
        idempotency_key="t5-chat-note",
    )
    tasks = svc.list_tasks(limit=50)
    assert tasks["count"] == 0
    assert tasks["tasks"] == []
    # still no promote without explicit call
    with pytest.raises(InvalidTransitionError, match="ACCEPTED|auto-promote"):
        svc.promote_to_task(
            actor="codex",
            source_thread_id=thread_id,
            decision_hash="ghost",
            title="should fail",
            goal="chat alone is not enough",
            idempotency_key="t5-chat-promote-reject",
        )
    assert svc.list_tasks(limit=50)["count"] == 0


def test_closure_version_conflict_rejects_stale_respond(svc: CoordinationService) -> None:
    thread_id, version = _open_chat(svc, "cas-close")
    svc.post_message(
        actor="codex",
        thread_id=thread_id,
        body="counter for CAS",
        kind="counter",
        expected_version=version,
        idempotency_key="t5-cas-post",
    )
    current = svc.get_thread(thread_id)["thread"]
    assert isinstance(current, dict)
    stale_version = int(current["version"])
    proposed = svc.propose_close(
        actor="grok_4_5",
        thread_id=thread_id,
        decision_hash="hash-cas-v1",
        summary="first vote",
        expected_version=stale_version,
        idempotency_key="t5-cas-propose",
    )
    assert proposed["thread"]["state"] == "CLOSING"
    # Stale expected_version (pre-propose) must CAS-fail on respond
    with pytest.raises(ConflictError, match="version|mismatch"):
        svc.respond(
            actor="codex",
            thread_id=thread_id,
            decision_hash="hash-cas-v1",
            summary="stale version respond",
            expected_version=stale_version,
            idempotency_key="t5-cas-stale-respond",
        )
    # Fresh version with correct hash succeeds
    live = svc.get_thread(thread_id)["thread"]
    assert isinstance(live, dict)
    ok = svc.respond(
        actor="codex",
        thread_id=thread_id,
        decision_hash="hash-cas-v1",
        summary="fresh version respond",
        expected_version=int(live["version"]),
        idempotency_key="t5-cas-fresh-respond",
    )
    assert ok["thread"]["state"] == "ACCEPTED"


def test_promote_without_closure_rejected(svc: CoordinationService) -> None:
    thread_id, _ = _open_chat(svc, "no-close")
    with pytest.raises(InvalidTransitionError, match="ACCEPTED|auto-promote"):
        svc.promote_to_task(
            actor="grok_4_5",
            source_thread_id=thread_id,
            decision_hash="anything",
            title="illegal",
            goal="must close first",
            idempotency_key="t5-promote-open-reject",
        )
    # CLOSING (one vote only) still not enough
    svc.propose_close(
        actor="grok_4_5",
        thread_id=thread_id,
        decision_hash="half-hash",
        summary="only one side",
        idempotency_key="t5-half-propose",
    )
    assert svc.get_thread(thread_id)["thread"]["state"] == "CLOSING"
    with pytest.raises(InvalidTransitionError, match="ACCEPTED|auto-promote"):
        svc.promote_to_task(
            actor="codex",
            source_thread_id=thread_id,
            decision_hash="half-hash",
            title="still illegal",
            goal="need mutual accept",
            idempotency_key="t5-promote-closing-reject",
        )


def test_promote_decision_hash_mismatch_rejected(svc: CoordinationService) -> None:
    thread_id = _accept_via_propose_respond(svc, suffix="hash-mm", decision_hash="correct-hash")
    with pytest.raises(ConflictError, match="decision_hash"):
        svc.promote_to_task(
            actor="codex",
            source_thread_id=thread_id,
            decision_hash="wrong-hash",
            title="bad hash",
            goal="cas gate",
            idempotency_key="t5-promote-hash-reject",
        )


def test_explicit_promote_to_task_idempotent(svc: CoordinationService) -> None:
    thread_id = _accept_via_propose_respond(svc, suffix="idem", decision_hash="dec-idem-1")
    first = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="dec-idem-1",
        title="promoted work",
        goal="execute accepted decision",
        writer_scope="canary",
        acceptance="pytest-t5",
        budget="bounded",
        stop_scope="global",
        idempotency_key="t5-promote-idem",
    )
    assert first["ok"] is True
    assert first["action"] == "task.promote"
    assert first["task"]["state"] == "queued"
    assert first["task"]["source_thread_id"] == thread_id
    assert first["task"]["consensus_status"] == "accepted"
    assert first["task"]["metadata"]["promoted"] is True
    assert first["decision_hash"] == "dec-idem-1"
    replay = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="dec-idem-1",
        title="promoted work",
        goal="execute accepted decision",
        writer_scope="canary",
        acceptance="pytest-t5",
        budget="bounded",
        stop_scope="global",
        idempotency_key="t5-promote-idem",
    )
    assert replay["replayed"] is True
    assert replay["task"]["task_id"] == first["task"]["task_id"]
    # Only one task exists (no chat auto-task + idempotent promote)
    assert svc.list_tasks(limit=50)["count"] == 1


def test_stop_freezes_promote_and_new_dispatch(svc: CoordinationService) -> None:
    thread_id = _accept_via_propose_respond(svc, suffix="stop-a", decision_hash="stop-hash-a")
    promoted = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="stop-hash-a",
        title="active then freeze",
        goal="will cancel",
        idempotency_key="t5-stop-promote-1",
    )
    task_id = str(promoted["task"]["task_id"])
    stop = svc.user_stop(actor="user", reason="T5 stop freeze", idempotency_key="t5-stop-raise")
    assert stop["active"] is True
    assert task_id in stop["canceled_tasks"]
    assert svc.get_task(task_id)["task"]["state"] == "canceled"

    other = _accept_via_propose_respond(svc, suffix="stop-b", decision_hash="stop-hash-b")
    with pytest.raises(InvalidTransitionError, match="stop is active"):
        svc.promote_to_task(
            actor="codex",
            source_thread_id=other,
            decision_hash="stop-hash-b",
            title="blocked by stop",
            goal="frozen",
            idempotency_key="t5-stop-blocked-promote",
        )
    # Stop does not auto-clear
    assert svc.stop_status()["active"] is True
    cleared = svc.clear_stop(actor="user", reason="explicit resume", idempotency_key="t5-stop-clear")
    assert cleared["active"] is False
    after = svc.promote_to_task(
        actor="codex",
        source_thread_id=other,
        decision_hash="stop-hash-b",
        title="after clear",
        goal="unfrozen",
        idempotency_key="t5-after-clear-promote",
    )
    assert after["task"]["state"] == "queued"


def test_cli_propose_respond_promote_parity(svc: CoordinationService, db_path: Path) -> None:
    opened = svc.open_thread(
        actor="grok_4_5",
        title="cli-t5",
        body="cli natural language body",
        idempotency_key="t5-cli-open",
    )
    thread_id = str(opened["thread"]["thread_id"])
    version = int(opened["thread"]["version"])
    parser = build_parser()

    propose_args = parser.parse_args(
        [
            "--db",
            str(db_path),
            "propose-close",
            "--actor",
            "grok_4_5",
            "--thread-id",
            thread_id,
            "--decision-hash",
            "cli-hash",
            "--summary",
            "cli propose",
            "--expected-version",
            str(version),
            "--idempotency-key",
            "t5-cli-propose",
        ]
    )
    proposed = execute(propose_args, CoordinationService(db_path))
    assert proposed["action"] == "thread.propose_close"
    assert proposed["thread"]["state"] == "CLOSING"
    close_version = int(proposed["thread"]["version"])

    respond_args = parser.parse_args(
        [
            "--db",
            str(db_path),
            "respond",
            "--actor",
            "codex",
            "--thread-id",
            thread_id,
            "--decision-hash",
            "cli-hash",
            "--summary",
            "cli respond",
            "--expected-version",
            str(close_version),
            "--idempotency-key",
            "t5-cli-respond",
        ]
    )
    responded = execute(respond_args, CoordinationService(db_path))
    assert responded["thread"]["state"] == "ACCEPTED"

    promote_args = parser.parse_args(
        [
            "--db",
            str(db_path),
            "promote",
            "--actor",
            "codex",
            "--source-thread-id",
            thread_id,
            "--decision-hash",
            "cli-hash",
            "--title",
            "cli promoted",
            "--goal",
            "parity",
            "--idempotency-key",
            "t5-cli-promote",
        ]
    )
    promoted = execute(promote_args, CoordinationService(db_path))
    assert promoted["ok"] is True
    assert promoted["task"]["source_thread_id"] == thread_id
