"""Integrated bus modular nodes — thin-bind existing mature carriers (no 1:1 glue)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from services.agent_runtime.thin_glue_l4_search import derive_search_query, run_local_rg_search
from services.agent_runtime.thin_glue_l8_token_stack import compress_readback_fallback
from services.agent_runtime.thin_glue_stack import write_json


class BusTaskValidateModel(BaseModel):
    schema_version: str = Field(default="xinao.integrated_bus.validate.v1")
    source_path: str
    user_intent_cn: str
    content_chars: int
    pydantic_ok: bool = True


def run_validate_bus(*, input_path: str, content_md: str) -> dict[str, Any]:
    intent = next(
        (line.strip() for line in content_md.splitlines() if line.strip() and not line.startswith("#")),
        content_md[:120].strip() or "integrated_bus",
    )
    model = BusTaskValidateModel(
        source_path=input_path,
        user_intent_cn=intent[:500],
        content_chars=len(content_md),
    )
    return {
        "validate_ok": True,
        "task_package": model.model_dump(),
        "structured_by": "pydantic_validate",
    }


def run_search_bus(*, repo_root: Path, content_md: str, max_results: int = 6) -> dict[str, Any]:
    query = derive_search_query(content_md, fallback="integrated_bus")
    local = run_local_rg_search(repo_root, query, max_results=max_results)
    return {
        "search_ok": local.get("ok") is True,
        "search_query": query,
        "search_adapter": str(local.get("adapter") or "ripgrep"),
        "search_hit_count": int(local.get("hit_count") or 0),
        "search_hits": (local.get("hits") or [])[:max_results],
    }


def run_fanin_bus(
    state: dict[str, Any],
    *,
    runtime_root: Path,
    workflow_id: str = "",
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    ledger_dir = runtime_root / "state" / "source_ledger" / "integrated_bus"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "xinao.integrated_bus.fanin_slice.v1",
        "run_id": run_id,
        "workflow_id": workflow_id,
        "role": "integrated_bus_fanin",
        "intake_adapter": state.get("adapter"),
        "gateway_trace_ok": state.get("gateway_trace_ok"),
        "search_hit_count": state.get("search_hit_count"),
        "promotion_pending": True,
    }
    path = ledger_dir / f"fanin_{run_id}.json"
    write_json(path, record)
    latest = ledger_dir / "latest.json"
    write_json(latest, record)
    return {
        "fanin_ok": True,
        "fanin_evidence_ref": str(path),
        "source_ledger_latest": str(latest),
    }


def run_token_bus(*, summary_text: str, runtime_root: Path) -> dict[str, Any]:
    compressed = compress_readback_fallback(summary_text, max_chars=2000)
    out_dir = runtime_root / "readback" / "zh" / "integrated_bus"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    zh_path = out_dir / f"summary_{run_id}.md"
    zh_path.write_text(str(compressed.get("text") or ""), encoding="utf-8")
    return {
        "token_bus_ok": compressed.get("ok") is True,
        "readback_zh_ref": str(zh_path),
        "compression_adapter": str(compressed.get("adapter") or ""),
    }


def run_heal_bus(*, params: dict[str, Any]) -> dict[str, Any]:
    policy = params.get("temporal_retry_policy") or {
        "maximum_attempts": 3,
        "initial_interval_seconds": 2,
        "backoff_coefficient": 2.0,
    }
    return {
        "heal_bus_ok": True,
        "retry_policy": policy,
        "critic_edge": "langgraph_conditional_deferred",
    }