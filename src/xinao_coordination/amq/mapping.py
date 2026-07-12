"""AMQ envelope ↔ kernel role/kind mapping (no second control plane)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# AMQ agent handles are short; kernel uses role names.
ROLE_TO_HANDLE: dict[str, str] = {
    "user": "user",
    "grok_4_5": "grok",
    "codex": "codex",
    "admin": "admin",
}
HANDLE_TO_ROLE: dict[str, str] = {v: k for k, v in ROLE_TO_HANDLE.items()}

# AMQ kinds → kernel message kinds (kernel set is fixed by schema).
KIND_TO_KERNEL: dict[str, str] = {
    "brainstorm": "propose",
    "review_request": "ask",
    "review_response": "reply",
    "question": "ask",
    "answer": "reply",
    "decision": "inform",
    "status": "note",
    "todo": "note",
    "discuss": "note",
    "evidence": "inform",
    "propose_close": "system",
    "close_response": "system",
    "notice": "system",
}


class BadHashError(ValueError):
    """Declared payload hash does not match body; message must be quarantined."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def role_to_handle(role: str) -> str:
    if role in ROLE_TO_HANDLE:
        return ROLE_TO_HANDLE[role]
    if role in HANDLE_TO_ROLE:
        return role
    raise ValueError(f"unknown role for AMQ handle mapping: {role}")


def handle_to_role(handle: str) -> str:
    if handle in HANDLE_TO_ROLE:
        return HANDLE_TO_ROLE[handle]
    if handle in ROLE_TO_HANDLE:
        return handle
    raise ValueError(f"unknown AMQ handle: {handle}")


def kernel_kind(amq_kind: str | None) -> str:
    if not amq_kind:
        return "note"
    return KIND_TO_KERNEL.get(amq_kind.lower(), "note")


def payload_sha256(body: str, *, extra: dict[str, Any] | None = None) -> str:
    payload = {"body": body, **(extra or {})}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_SAFE_ID = re.compile(r"^[A-Za-z0-9._:@/-]{1,200}$")


def validate_message_id(message_id: str) -> str:
    if not message_id or not _SAFE_ID.match(message_id):
        raise ValueError(f"unsafe or empty message_id: {message_id!r}")
    if ".." in message_id or message_id.startswith(("/", "\\")):
        raise ValueError(f"path-like message_id rejected: {message_id!r}")
    return message_id


def _first_handle(value: Any) -> str:
    """AMQ CLI may emit `to`/`from` as str or list[str]."""
    if value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return ""
    text = str(value).strip()
    if "," in text and not text.startswith("["):
        return text.split(",", 1)[0].strip()
    return text


def _context_dict(raw: dict[str, Any]) -> dict[str, Any]:
    context = raw.get("context")
    if isinstance(context, dict):
        return context
    header = raw.get("header")
    if isinstance(header, dict):
        nested = header.get("context")
        if isinstance(nested, dict):
            return nested
    return {}


def declared_payload_sha256(raw: dict[str, Any], context: dict[str, Any] | None = None) -> str | None:
    """Optional producer-declared hash for integrity isolation."""
    ctx = context if context is not None else _context_dict(raw)
    for source in (ctx, raw, raw.get("header") if isinstance(raw.get("header"), dict) else {}):
        if not isinstance(source, dict):
            continue
        value = source.get("payload_sha256") or source.get("payload_hash")
        if value:
            return str(value).strip().lower()
    return None


def envelope_from_amq_message(raw: dict[str, Any], *, verify_hash: bool = True) -> dict[str, Any]:
    """Normalize AMQ CLI JSON into a stable ingest envelope.

    If the producer declares payload_sha256 and it mismatches the body-derived hash,
    raise BadHashError (caller must quarantine; kernel must not be written).
    """
    header = raw.get("header") if isinstance(raw.get("header"), dict) else {}
    message_id = str(
        raw.get("id")
        or raw.get("message_id")
        or raw.get("msg_id")
        or header.get("id")
        or ""
    )
    message_id = validate_message_id(message_id)
    sender_handle = _first_handle(
        raw.get("from") or raw.get("sender") or raw.get("me") or header.get("from")
    )
    recipient_handle = _first_handle(
        raw.get("to") or raw.get("recipient") or header.get("to")
    )
    body = str(raw.get("body") or raw.get("text") or "")
    kind = str(raw.get("kind") or header.get("kind") or "status")
    subject = str(raw.get("subject") or header.get("subject") or "")
    context = _context_dict(raw)
    thread_hint = str(
        raw.get("thread")
        or raw.get("thread_id")
        or header.get("thread")
        or context.get("thread_id")
        or ""
    )
    operation_id = str(
        raw.get("operation_id")
        or context.get("operation_id")
        or message_id
    )
    idempotency_key = str(
        raw.get("idempotency_key")
        or context.get("idempotency_key")
        or f"amq:{message_id}"
    )
    computed = payload_sha256(body, extra={"subject": subject, "kind": kind})
    declared = declared_payload_sha256(raw, context)
    if verify_hash and declared and declared != computed:
        raise BadHashError(
            "payload_sha256 mismatch; isolating message",
            details={
                "message_id": message_id,
                "declared": declared,
                "computed": computed,
            },
        )
    return {
        "schema_version": "xinao.amq.envelope.v1",
        "message_id": message_id,
        "thread_id": thread_hint,
        "sender_role": handle_to_role(sender_handle) if sender_handle else "",
        "recipient_role": handle_to_role(recipient_handle) if recipient_handle else "",
        "sender_handle": sender_handle,
        "recipient_handle": recipient_handle,
        "kind": kind,
        "kernel_kind": kernel_kind(kind),
        "reply_to": raw.get("refs") or raw.get("reply_to") or header.get("refs"),
        "operation_id": operation_id,
        "idempotency_key": idempotency_key,
        "payload_sha256": computed,
        "declared_payload_sha256": declared,
        "subject": subject,
        "body_utf8": body,
        "context": context,
        "raw": raw,
    }
