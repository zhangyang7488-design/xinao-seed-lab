"""Shared sunset payload for retired 333 / p0 handroll modules."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.sunset_module_stub.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_retired_module_payload(
    *,
    module_name: str,
    status: str,
    state_dir: str,
    write: bool = True,
    runtime_root: str | Path = r"D:\XINAO_RESEARCH_RUNTIME",
    validation_passed: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "module_name": module_name,
        "status": status,
        "handroll_intact": False,
        "sunset_stub": True,
        "completion_claim_allowed": False,
        "named_blocker": "MODULE_SUNSET_USE_INTEGRATED_BUS",
        "replacement": "integrated_bus_v2",
        "active_blockers": [],
        "validation": {"passed": validation_passed, "reason": "sunset_stub"},
        "generated_at": now_iso(),
    }
    if write:
        out_dir = runtime / "state" / state_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        latest = out_dir / "latest.json"
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["latest_ref"] = str(latest)
    return payload