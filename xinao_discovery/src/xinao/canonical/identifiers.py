"""RFC 9562 UUIDv7 generation and validation."""

from __future__ import annotations

import threading
from uuid import UUID

import uuid6

_UUID7_LOCK = threading.Lock()
UUID7_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


def generate_uuid7() -> str:
    """Generate a process-local monotonic UUIDv7 string.

    The lock protects the selected Python 3.12 backport, which does not claim
    thread safety. UUIDv7 remains an identifier with temporal locality, not a
    global causal-order primitive across workers or hosts.
    """

    with _UUID7_LOCK:
        return str(uuid6.uuid7())


def is_uuid7(value: str) -> bool:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        str(parsed) == value and parsed.version == 7 and parsed.variant == "specified in RFC 4122"
    )


def require_uuid7(value: str) -> str:
    if not is_uuid7(value):
        raise ValueError("value must be a lowercase hyphenated RFC 9562 UUIDv7")
    return value
