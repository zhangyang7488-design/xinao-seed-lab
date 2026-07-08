"""Sunset registry — 段绿旁路登记，不硬删手搓."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_REPO

REGISTRY_REL = Path("materials/authority_glue/thin_glue_sunset_registry.v1.json")


def load_sunset_registry(repo_root: Path | None = None) -> dict[str, Any]:
    repo = repo_root or DEFAULT_REPO
    path = repo / REGISTRY_REL
    if not path.is_file():
        return {"schema_version": "xinao.thin_glue_sunset_registry.v1", "entries": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "xinao.thin_glue_sunset_registry.v1", "entries": []}
    return payload if isinstance(payload, dict) else {"entries": []}


def summarize_sunset_registry(repo_root: Path | None = None) -> dict[str, Any]:
    registry = load_sunset_registry(repo_root)
    entries = registry.get("entries") if isinstance(registry.get("entries"), list) else []
    active: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        env_flag = str(entry.get("env_flag") or "")
        flag_val = os.environ.get(env_flag, "1") if env_flag else "1"
        bypass_on = flag_val.strip().lower() not in {"0", "false", "no", "off"}
        active.append(
            {
                "id": entry.get("id"),
                "handroll_module": entry.get("handroll_module"),
                "thin_module": entry.get("thin_module"),
                "env_flag": env_flag,
                "bypass_active": bypass_on,
                "registry_status": entry.get("status"),
            }
        )
    bypass_count = sum(1 for item in active if item.get("bypass_active"))
    return {
        "handroll_intact": registry.get("handroll_intact", False),
        "facade_hard_redirect_default": registry.get("facade_hard_redirect_default", True),
        "facade_modules": registry.get("facade_modules", []),
        "delete_policy": registry.get("delete_policy"),
        "entry_count": len(active),
        "bypass_active_count": bypass_count,
        "entries": active,
        "registry_path": str((repo_root or DEFAULT_REPO) / REGISTRY_REL),
        "retired_archive": registry.get("retired_archive"),
        "acceptance_cli": registry.get("acceptance_cli"),
        "status_cli": registry.get("status_cli"),
    }