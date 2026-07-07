from __future__ import annotations

import json
from typing import Any


def _safe(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(_safe(key)): _safe(item) for key, item in value.items()}
    return value


def json_bytes(payload: Any) -> bytes:
    return json.dumps(_safe(payload), ensure_ascii=False).encode("utf-8")


def encode_responses_stream(
    request: dict[str, Any], response: dict[str, Any], usage: dict[str, Any]
) -> bytes:
    events = [
        {"type": "response.created", "request": _safe(request)},
        {"type": "response.output_text.delta", "delta": str(_safe(response.get("content", "")))},
        {"type": "response.completed", "usage": _safe(usage)},
    ]
    return b"".join(b"data: " + json_bytes(event) + b"\n\n" for event in events)
