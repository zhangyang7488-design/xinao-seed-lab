"""Lightweight episode event helpers for dual-container MCP/host receipts.

Append-only JSONL evidence under attempt-local paths. Not a ledger or shadow store.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append_event(path: Path | str, event: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": _utc_now(),
        **dict(event),
        "completion_claim_allowed": False,
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with target.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def read_events(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events
