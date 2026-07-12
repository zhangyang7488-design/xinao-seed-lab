from __future__ import annotations

import pytest

from xinao_coordination import CoordinationService
from xinao_coordination.errors import AuthorizationError, NotFoundError, ValidationError


def test_doorbell_ack_is_not_model_read(service: CoordinationService) -> None:
    task = service.dispatch_task(
        actor="codex", title="notify", goal="separate semantics", idempotency_key="dispatch"
    )["task"]
    pulled = service.pull_notification(
        actor="admin",
        recipient="admin",
        adapter_id="test-doorbell",
        idempotency_key="pull",
    )
    assert pulled["notification"]["aggregate_id"] == task["task_id"]
    assert pulled["model_read"] is False
    ack = service.ack_notification(
        actor="admin",
        notification_id=pulled["notification"]["notification_id"],
        lease_token=pulled["lease_token"],
        idempotency_key="ack",
    )
    assert ack["doorbell_delivered"] is True
    assert ack["model_read"] is False


def test_receipt_requires_explicit_call(service: CoordinationService) -> None:
    task = service.dispatch_task(
        actor="codex", title="receipt", goal="existing item", idempotency_key="dispatch"
    )["task"]
    first = service.record_receipt(
        actor="codex", item_type="task", item_id=task["task_id"], receipt_type="observed"
    )
    second = service.record_receipt(
        actor="codex", item_type="task", item_id=task["task_id"], receipt_type="observed"
    )
    assert first["created"] is True
    assert second["created"] is False
    assert "not inferred" in first["meaning"]
    assert first["identity_assurance"] == "caller_declared_unverified"


def test_notification_lease_validates_duration_and_actor(service: CoordinationService) -> None:
    service.dispatch_task(actor="codex", title="notify", goal="auth", idempotency_key="dispatch")
    with pytest.raises(ValidationError):
        service.pull_notification(
            actor="admin",
            recipient="admin",
            adapter_id="adapter",
            lease_seconds=-1,
            idempotency_key="negative",
        )
    with pytest.raises(AuthorizationError):
        service.pull_notification(
            actor="admin",
            recipient="grok_4_5",
            adapter_id="adapter",
            idempotency_key="spoof-pull",
        )
    pulled = service.pull_notification(
        actor="admin",
        recipient="admin",
        adapter_id="adapter",
        idempotency_key="pull",
    )
    with pytest.raises(AuthorizationError):
        service.ack_notification(
            actor="user",
            notification_id=pulled["notification"]["notification_id"],
            lease_token=pulled["lease_token"],
            idempotency_key="spoof-ack",
        )
    service.ack_notification(
        actor="admin",
        notification_id=pulled["notification"]["notification_id"],
        lease_token=pulled["lease_token"],
        idempotency_key="ack",
    )


def test_receipt_rejects_nonexistent_target(service: CoordinationService) -> None:
    with pytest.raises(NotFoundError):
        service.record_receipt(actor="codex", item_type="task", item_id="missing")
