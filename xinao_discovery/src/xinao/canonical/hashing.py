"""Content hashing over canonical bytes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

import rfc8785

from .jcs import to_json_value

_ORDERED_JSON_STREAM_V1 = b"xinao.ordered_json_stream.v1\0"


class _HashSink:
    """Minimal bytes sink accepted by the public ``rfc8785.dump`` API."""

    __slots__ = ("_digest",)

    def __init__(self) -> None:
        self._digest = hashlib.sha256()

    def write(self, value: bytes) -> int:
        self._digest.update(value)
        return len(value)

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    """Return lowercase SHA-256 hex over RFC 8785 UTF-8 bytes."""

    sink = _HashSink()
    rfc8785.dump(to_json_value(value), sink)
    return sink.hexdigest()


def ordered_json_stream_sha256(values: Iterable[Any]) -> str:
    """Hash an ordered JSON-value stream without materializing one large JCS array.

    Each item is converted through the canonical domain-value adapter, encoded by
    this explicitly versioned JSON profile, and length framed before hashing.  The
    stream item count is framed last, so order, item boundaries, and cardinality
    are all bound by the digest.  This is deliberately not named or represented
    as RFC 8785.
    """

    digest = hashlib.sha256()
    digest.update(_ORDERED_JSON_STREAM_V1)
    count = 0
    for value in values:
        encoded = json.dumps(
            to_json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
        digest.update(encoded)
        count += 1
    digest.update(count.to_bytes(8, byteorder="big", signed=False))
    return digest.hexdigest()
