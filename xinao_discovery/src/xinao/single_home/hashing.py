"""Content hashing via the repository RFC 8785 canonical primitive.

Does not implement a private canonicalizer or json.dumps fallback hash.
"""

from __future__ import annotations

import re
from typing import Any

from xinao.canonical import canonical_sha256

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def content_sha256(value: Any) -> str:
    """Return lowercase SHA-256 hex over RFC 8785 UTF-8 bytes."""

    return canonical_sha256(value)


def require_sha256(name: str, value: Any) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be 64 lowercase hex")
    return value
