"""AMQ new → kernel authority (one-time ingest with idempotency + hash isolation)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import ConflictError, CoordinationError, ValidationError
from ..service import CoordinationService
from .mapping import BadHashError, envelope_from_amq_message, role_to_handle
from .transport import AmqTransport


class AmqIngestor:
    """Pull raw AMQ messages into the coordination kernel; never invent Task state."""

    def __init__(self, service: CoordinationService, transport: AmqTransport | None = None) -> None:
        self.service = service
        self.transport = transport or AmqTransport()

    def ingest_for_role(
        self,
        *,
        recipient_role: str,
        limit: int = 20,
        open_if_missing: bool = True,
    ) -> dict[str, Any]:
        handle = role_to_handle(recipient_role)
        drained = self.transport.drain(me=handle, include_body=True, limit=limit)
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        quarantined: list[dict[str, Any]] = []
        for raw in drained:
            try:
                results.append(self.ingest_one(raw, open_if_missing=open_if_missing))
            except BadHashError as exc:
                path = self._isolate(raw, reason="bad_hash", details=exc.details)
                quarantined.append(
                    {
                        "ok": False,
                        "error": "bad_hash_isolated",
                        "message": str(exc),
                        "details": exc.details,
                        "quarantine_path": str(path),
                        "kernel_written": False,
                    }
                )
            except ConflictError as exc:
                # Same idempotency key, different payload — reject, do not create objects.
                path = self._isolate(
                    raw,
                    reason="idempotency_payload_conflict",
                    details=exc.details if isinstance(exc.details, dict) else {"message": str(exc)},
                )
                errors.append(
                    {
                        "ok": False,
                        "error": "idempotency_conflict",
                        "message": str(exc),
                        "details": exc.details,
                        "quarantine_path": str(path),
                        "kernel_written": False,
                    }
                )
            except CoordinationError as exc:
                errors.append(exc.as_dict())
            except (ValueError, ValidationError) as exc:
                details = getattr(exc, "details", None)
                path = self._isolate(
                    raw,
                    reason="ingest_rejected",
                    details=details if isinstance(details, dict) else {"message": str(exc)},
                )
                errors.append(
                    {
                        "ok": False,
                        "error": "ingest_rejected",
                        "message": str(exc),
                        "details": {
                            "raw_id": raw.get("id") or raw.get("message_id"),
                            **(details if isinstance(details, dict) else {}),
                        },
                        "quarantine_path": str(path),
                        "kernel_written": False,
                    }
                )
        return {
            "ok": not errors and not quarantined,
            "action": "amq.ingest",
            "recipient_role": recipient_role,
            "recipient_handle": handle,
            "drained_count": len(drained),
            "ingested": results,
            "errors": errors,
            "quarantined": quarantined,
            "receipt_stage": "PERSISTED",
            "note": "AMQ drain moved messages to cur; kernel is authoritative for discussion/task state",
        }

    def ingest_one(self, raw: dict[str, Any], *, open_if_missing: bool = True) -> dict[str, Any]:
        """Ingest a single raw AMQ message dict (also used for pure unit re-delivery tests)."""
        envelope = envelope_from_amq_message(raw, verify_hash=True)
        sender = envelope["sender_role"]
        if not sender:
            raise ValidationError("AMQ message missing sender", details={"envelope": envelope})
        if sender == "admin":
            raise ValidationError(
                "admin cannot open or post discussion via AMQ ingest",
                details={"message_id": envelope["message_id"]},
            )
        body = envelope["body_utf8"] or envelope["subject"] or f"[empty body] {envelope['message_id']}"
        thread_id = str(envelope.get("thread_id") or "")
        # Prefer producer idempotency_key; default amq:{message_id} gives per-message uniqueness.
        idem = str(envelope["idempotency_key"])

        # Prefer explicit kernel thread_id in context; AMQ p2p thread strings are not kernel ids.
        if thread_id and not str(thread_id).startswith("th_"):
            context_thread = ""
            ctx = envelope.get("context")
            if isinstance(ctx, dict):
                context_thread = str(ctx.get("thread_id") or "")
            thread_id = context_thread if context_thread.startswith("th_") else ""

        if not thread_id:
            if not open_if_missing:
                raise ValidationError("thread_id required when open_if_missing=false")
            opened = self.service.open_thread(
                actor=sender,
                title=envelope["subject"] or f"amq:{envelope['message_id']}",
                body=body,
                idempotency_key=f"{idem}:open",
                metadata={
                    "source": "amq",
                    "amq_message_id": envelope["message_id"],
                    "payload_sha256": envelope["payload_sha256"],
                    "operation_id": envelope["operation_id"],
                },
            )
            thread = opened["thread"]
            assert isinstance(thread, dict)
            thread_id = str(thread["thread_id"])
            kernel_result = opened
            action = "thread.open_via_amq"
            replayed = bool(opened.get("replayed"))
        else:
            kernel_result = self.service.post_message(
                actor=sender,
                thread_id=thread_id,
                body=body,
                kind=str(envelope["kernel_kind"]),
                recipient=str(envelope["recipient_role"] or "*"),
                idempotency_key=idem,
            )
            action = "thread.post_via_amq"
            replayed = bool(kernel_result.get("replayed"))

        # Explicit local attestation: adapter delivered raw mail into durable kernel objects.
        # Does NOT claim the target model has read anything.
        message_id = None
        if isinstance(kernel_result, dict):
            message_id = kernel_result.get("message_id")

        receipt = None
        if message_id and not replayed:
            try:
                receipt = self.service.record_receipt(
                    actor=sender,
                    item_type="message",
                    item_id=str(message_id),
                    receipt_type="acted_on",
                )
            except CoordinationError:
                receipt = None

        return {
            "ok": True,
            "action": action,
            "amq_message_id": envelope["message_id"],
            "operation_id": envelope["operation_id"],
            "idempotency_key": idem,
            "payload_sha256": envelope["payload_sha256"],
            "thread_id": thread_id,
            "kernel": kernel_result,
            "receipt": receipt,
            "receipt_stage": "PERSISTED",
            "replayed": replayed,
            "model_read": False,
            "kernel_written": not replayed,
        }

    def _isolate(
        self,
        raw: dict[str, Any],
        *,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> Path:
        return self.transport.write_quarantine(reason=reason, raw=raw, details=details or {})
