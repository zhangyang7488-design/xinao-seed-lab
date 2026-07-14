"""Content hashing over canonical bytes."""

from __future__ import annotations

import hashlib
from typing import Any

from .jcs import canonical_dumps


def canonical_sha256(value: Any) -> str:
    """Return lowercase SHA-256 hex over RFC 8785 UTF-8 bytes."""

    return hashlib.sha256(canonical_dumps(value)).hexdigest()
