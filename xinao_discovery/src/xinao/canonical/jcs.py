"""The single RFC 8785 JCS surface used by Xinao."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import rfc8785
from pydantic import BaseModel

from .decimal_profile import format_decimal_exact
from .time_profile import format_utc


def to_json_value(value: Any) -> Any:
    """Convert supported domain values to an I-JSON-compatible structure."""

    if isinstance(value, BaseModel):
        return to_json_value(value.model_dump(mode="python"))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NaN and Infinity are forbidden by the canonical profile")
        return value
    if isinstance(value, Decimal):
        return format_decimal_exact(value)
    if isinstance(value, datetime):
        return format_utc(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        encoded = base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
        return f"base64url:{encoded}"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical object keys must be strings")
            result[key] = to_json_value(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_json_value(item) for item in value]
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_dumps(value: Any) -> bytes:
    """Return RFC 8785 canonical UTF-8 bytes."""

    return rfc8785.dumps(to_json_value(value))


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def canonical_loads(value: str | bytes) -> Any:
    """Load JSON while rejecting duplicate keys and non-finite numbers."""

    return json.loads(
        value,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite,
    )
