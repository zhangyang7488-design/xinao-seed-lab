from __future__ import annotations

import pytest

from xinao_coordination import CoordinationService
from xinao_coordination.errors import (
    AuthorizationError,
    ConflictError,
    InvalidTransitionError,
)

from .conftest import accepted_thread


def test_admin_has_no_discussion_space(service: CoordinationService) -> None:
    with pytest.raises(AuthorizationError):
        service.open_thread(actor="admin", title="forbidden")
    opened = service.open_thread(actor="codex", title="seed", body="seed", idempotency_key="admin-seed")
    thread_id = opened["thread"]["thread_id"]
    with pytest.raises(AuthorizationError):
        service.post_message(actor="admin", thread_id=thread_id, body="forbidden", idempotency_key="admin-post")
    with pytest.raises(AuthorizationError):
        service.close_thread(
            actor="admin",
            thread_id=thread_id,
            decision="accept",
            resolution_key="r",
            summary="no",
            idempotency_key="admin-close",
        )


def test_accept_requires_matching_votes_from_both_brains(service: CoordinationService) -> None:
    opened = service.open_thread(actor="grok_4_5", title="x", idempotency_key="o")
    thread_id = opened["thread"]["thread_id"]
    first = service.close_thread(
        actor="grok_4_5",
        thread_id=thread_id,
        decision="accept",
        resolution_key="r1",
        summary="yes",
        idempotency_key="c1",
    )
    assert first["thread"]["state"] == "CLOSING"
    mismatch = service.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key="r2",
        summary="different",
        idempotency_key="c2",
    )
    assert mismatch["thread"]["state"] == "CLOSING"
    final = service.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key="r1",
        summary="same resolution",
        idempotency_key="c3",
    )
    assert final["thread"]["state"] == "ACCEPTED"


def test_user_authority_can_close_without_fake_peer_vote(service: CoordinationService) -> None:
    opened = service.open_thread(actor="user", title="authority", idempotency_key="open")
    result = service.close_thread(
        actor="user",
        thread_id=opened["thread"]["thread_id"],
        decision="reject",
        resolution_key="user-decision",
        summary="stop",
        idempotency_key="close",
    )
    assert result["thread"]["state"] == "REJECTED"
    assert result["thread"]["close_reason"] == "user_authority:reject"


def test_task_keeps_exact_source_thread_id_regression(service: CoordinationService) -> None:
    thread_id = accepted_thread(service, "source")
    result = service.dispatch_task(
        actor="codex",
        title="work",
        goal="keep source",
        source_thread_id=thread_id,
        task_id="task_regression",
        idempotency_key="dispatch-source",
    )
    assert result["task"]["task_id"] == "task_regression"
    assert result["task"]["source_thread_id"] == thread_id
    assert result["task"]["consensus_status"] == "accepted"


def test_nonaccepted_thread_requires_honest_override(service: CoordinationService) -> None:
    opened = service.open_thread(actor="codex", title="open", idempotency_key="open")
    thread_id = opened["thread"]["thread_id"]
    with pytest.raises(InvalidTransitionError):
        service.dispatch_task(
            actor="codex",
            title="bad",
            goal="bad",
            source_thread_id=thread_id,
            idempotency_key="bad",
        )
    result = service.dispatch_task(
        actor="codex",
        title="honest",
        goal="explicit override",
        source_thread_id=thread_id,
        explicit_non_consensus=True,
        idempotency_key="honest",
    )
    assert result["task"]["consensus_status"] == "explicit_non_consensus"


def test_optimistic_version_rejects_stale_post(service: CoordinationService) -> None:
    opened = service.open_thread(actor="codex", title="v", idempotency_key="open")
    thread = opened["thread"]
    service.post_message(
        actor="grok_4_5",
        thread_id=thread["thread_id"],
        body="new",
        expected_version=thread["version"],
        idempotency_key="p1",
    )
    with pytest.raises(ConflictError):
        service.post_message(
            actor="codex",
            thread_id=thread["thread_id"],
            body="stale",
            expected_version=thread["version"],
            idempotency_key="p2",
        )


def test_idempotency_replays_and_rejects_payload_change(service: CoordinationService) -> None:
    first = service.open_thread(actor="codex", title="one", idempotency_key="same")
    replay = service.open_thread(actor="codex", title="one", idempotency_key="same")
    assert replay["thread"]["thread_id"] == first["thread"]["thread_id"]
    assert replay["replayed"] is True
    with pytest.raises(ConflictError):
        service.open_thread(actor="codex", title="different", idempotency_key="same")


def test_ttl_sweep_expires_thread(db_path: object) -> None:
    now = [1_000_000]
    service = CoordinationService(db_path, clock_ms=lambda: now[0])
    opened = service.open_thread(actor="codex", title="ttl", ttl_seconds=1, idempotency_key="open")
    thread_id = opened["thread"]["thread_id"]
    now[0] += 1_001
    result = service.sweep()
    assert result["expired_threads"] == 1
    assert service.get_thread(thread_id)["thread"]["state"] == "EXPIRED"
    with pytest.raises(InvalidTransitionError):
        service.post_message(
            actor="codex",
            thread_id=thread_id,
            body="late",
            idempotency_key="late",
        )


def test_expiry_is_committed_before_post_or_close_error(db_path: object) -> None:
    now = [1_000_000]
    service = CoordinationService(db_path, clock_ms=lambda: now[0])
    opened = service.open_thread(actor="codex", title="ttl-race", ttl_seconds=1, idempotency_key="open")
    thread_id = opened["thread"]["thread_id"]
    now[0] += 1_001
    with pytest.raises(InvalidTransitionError):
        service.post_message(
            actor="grok_4_5",
            thread_id=thread_id,
            body="too late",
            idempotency_key="late-post",
        )
    assert service.get_thread(thread_id)["thread"]["state"] == "EXPIRED"
    with pytest.raises(InvalidTransitionError):
        service.close_thread(
            actor="grok_4_5",
            thread_id=thread_id,
            decision="accept",
            resolution_key="late",
            summary="too late",
            idempotency_key="late-close",
        )
