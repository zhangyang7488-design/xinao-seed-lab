"""Kernel notification outbox → AMQ send (adapter delivery only)."""

from __future__ import annotations

from typing import Any

from ..service import CoordinationService
from .mapping import payload_sha256, role_to_handle
from .transport import AmqTransport


class AmqOutbox:
    """Deliver pending kernel notifications as AMQ mail. ACK ≠ model read."""

    def __init__(
        self,
        service: CoordinationService,
        transport: AmqTransport | None = None,
        *,
        adapter_id: str = "amq-canary",
    ) -> None:
        self.service = service
        self.transport = transport or AmqTransport()
        self.adapter_id = adapter_id

    def flush_for_role(
        self,
        *,
        sender_role: str,
        recipient_role: str,
        max_items: int = 10,
    ) -> dict[str, Any]:
        sender_handle = role_to_handle(sender_role)
        recipient_handle = role_to_handle(recipient_role)
        delivered: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        # Adapter pulls the recipient's notification outbox, then delivers via AMQ as sender_handle.
        pull_actor = recipient_role
        for _ in range(max_items):
            pull = self.service.pull_notification(
                actor=pull_actor,
                recipient=recipient_role,
                adapter_id=self.adapter_id,
                lease_seconds=60,
                idempotency_key=None,
            )
            notification = pull.get("notification")
            if not notification:
                break
            assert isinstance(notification, dict)
            ntf_id = str(notification["notification_id"])
            lease = str(pull["lease_token"])
            payload = notification.get("payload") or {}
            body = (
                f"[kernel-notify] topic={notification.get('topic')} "
                f"aggregate={notification.get('aggregate_type')}:{notification.get('aggregate_id')} "
                f"payload={payload}"
            )
            subject = str(notification.get("topic") or "notice")
            kind = "status"
            body_hash = payload_sha256(body, extra={"subject": subject, "kind": kind})
            try:
                send_result = self.transport.send(
                    me=sender_handle,
                    to=recipient_handle,
                    body=body,
                    subject=subject,
                    kind=kind,
                    context={
                        "notification_id": ntf_id,
                        "aggregate_type": notification.get("aggregate_type"),
                        "aggregate_id": notification.get("aggregate_id"),
                        "payload_sha256": body_hash,
                        "idempotency_key": f"amq-outbox:{ntf_id}",
                        "operation_id": ntf_id,
                    },
                )
                ack = self.service.ack_notification(
                    actor=pull_actor,
                    notification_id=ntf_id,
                    lease_token=lease,
                    idempotency_key=f"amq-outbox-ack:{ntf_id}",
                )
                delivered.append(
                    {
                        "notification_id": ntf_id,
                        "amq": send_result,
                        "ack": ack,
                        "payload_sha256": body_hash,
                        "receipt_stage": "ADAPTER_DELIVERED",
                        "model_read": False,
                    }
                )
            except Exception as exc:  # surface but keep remaining queue
                errors.append(
                    {
                        "notification_id": ntf_id,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                break

        return {
            "ok": not errors,
            "action": "amq.outbox.flush",
            "sender_role": sender_role,
            "recipient_role": recipient_role,
            "delivered": delivered,
            "errors": errors,
            "note": "ADAPTER_DELIVERED never means target model observed the message",
        }
