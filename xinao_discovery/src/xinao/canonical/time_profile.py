"""Pinned RFC3339 UTC timestamp profile for hash-bearing records."""

from __future__ import annotations

import re
from datetime import UTC, datetime

UTC_MILLISECOND_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})\.(?P<millis>\d{3})Z$"
)


def format_utc(value: datetime) -> str:
    """Normalize an aware datetime to UTC with exactly millisecond precision."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime is not allowed")
    normalized = value.astimezone(UTC)
    if normalized.microsecond % 1000:
        raise ValueError("timestamp is not aligned to the millisecond profile")
    millis = normalized.microsecond // 1000
    return normalized.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_utc(value: str) -> datetime:
    """Parse the exact Xinao UTC timestamp string profile."""

    match = UTC_MILLISECOND_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("timestamp must use YYYY-MM-DDTHH:MM:SS.sssZ")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError("invalid UTC timestamp") from exc
