"""MCP default-surface contract: tool floor, mutating schema negatives, smoke parity."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from xinao_coordination import mcp_server

# Keep in lockstep with scripts/mcp_smoke.py (default surface floor + mutators).
MIN_DEFAULT_TOOL_COUNT = 38

REQUIRED_DEFAULT_TOOLS = frozenset(
    {
        "amq_ingest",
        "artifact_register_local",
        "coordination_backup",
        "coordination_status",
        "coordination_sweep",
        "events_list",
        "mbg_dispatch",
        "mbg_finish",
        "mbg_status",
        "notification_ack",
        "notification_pull",
        "promote_to_task",
        "propose_close",
        "receipt_record",
        "respond",
        "route_assess",
        "stop_clear",
        "stop_raise",
        "stop_status",
        "task_cancel",
        "task_claim",
        "task_complete",
        "task_dispatch",
        "task_export_a2a",
        "task_fail",
        "task_get",
        "task_heartbeat",
        "task_list",
        "task_pause",
        "task_resume",
        "task_start",
        "temporal_start_promoted",
        "temporal_status",
        "thread_close",
        "thread_get",
        "thread_list",
        "thread_open",
        "thread_post",
    }
)

MUTATING_TOOLS = (
    mcp_server.thread_open,
    mcp_server.thread_post,
    mcp_server.thread_close,
    mcp_server.propose_close,
    mcp_server.respond,
    mcp_server.task_dispatch,
    mcp_server.task_claim,
    mcp_server.task_start,
    mcp_server.task_heartbeat,
    mcp_server.task_complete,
    mcp_server.task_fail,
    mcp_server.task_pause,
    mcp_server.task_resume,
    mcp_server.task_cancel,
    mcp_server.artifact_register_local,
    mcp_server.notification_pull,
    mcp_server.notification_ack,
    mcp_server.receipt_record,
    mcp_server.promote_to_task,
    mcp_server.stop_raise,
    mcp_server.stop_clear,
    mcp_server.amq_ingest,
    mcp_server.mbg_dispatch,
    mcp_server.mbg_finish,
    mcp_server.temporal_start_promoted,
    # experimental names still must not expose actor if registered
    mcp_server.operation_submit,
    mcp_server.operation_cancel,
    mcp_server.operation_reconcile,
)


def test_default_mcp_surface_has_at_least_38_tools_and_required_set() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert len(names) >= MIN_DEFAULT_TOOL_COUNT, (
        f"expected tool_count>={MIN_DEFAULT_TOOL_COUNT}, got {len(names)}: {sorted(names)}"
    )
    missing = REQUIRED_DEFAULT_TOOLS - names
    assert not missing, f"missing required MCP tools: {sorted(missing)}"
    assert not {name for name in names if name.startswith("operation_")}
    # Floor and required set must stay consistent with the actual 38-tool surface.
    assert len(REQUIRED_DEFAULT_TOOLS) == MIN_DEFAULT_TOOL_COUNT


def test_mutating_tools_schemas_reject_actor_and_worker_id() -> None:
    """Negative: mutating tools must not expose actor/worker_id in call signatures."""
    for tool in MUTATING_TOOLS:
        parameters = inspect.signature(tool).parameters
        assert "actor" not in parameters, f"{tool.__name__} must not accept actor"
        assert "worker_id" not in parameters, f"{tool.__name__} must not accept worker_id"


def test_notification_pull_schema_rejects_recipient() -> None:
    """Negative: notification_pull must not expose recipient (bound role only)."""
    parameters = inspect.signature(mcp_server.notification_pull).parameters
    assert "recipient" not in parameters
    assert "actor" not in parameters
    assert "worker_id" not in parameters


def test_list_tools_input_schema_matches_negative_contract() -> None:
    """Same negatives via MCP list_tools JSON Schema (what remote clients see)."""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}
    mutator_names = {
        "amq_ingest",
        "artifact_register_local",
        "mbg_dispatch",
        "mbg_finish",
        "notification_ack",
        "notification_pull",
        "promote_to_task",
        "propose_close",
        "receipt_record",
        "respond",
        "stop_clear",
        "stop_raise",
        "task_cancel",
        "task_claim",
        "task_complete",
        "task_dispatch",
        "task_fail",
        "task_heartbeat",
        "task_pause",
        "task_resume",
        "task_start",
        "temporal_start_promoted",
        "thread_close",
        "thread_open",
        "thread_post",
    }
    for name in mutator_names:
        assert name in by_name, f"missing mutator {name}"
        props = set(by_name[name].inputSchema.get("properties", {}))
        banned = props & {"actor", "worker_id"}
        assert not banned, f"{name} exposes forbidden schema params: {sorted(banned)}"
    pull_props = set(by_name["notification_pull"].inputSchema.get("properties", {}))
    assert "recipient" not in pull_props


def test_all_shipped_mcp_schema_snapshots_match_registered_tools() -> None:
    """Every delivered schema is an exact snapshot of the current FastMCP surface."""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    schema_root = Path(__file__).resolve().parents[1] / "mcps" / "xinao-coordination" / "tools"
    snapshots = {path.stem: path for path in schema_root.glob("*.json")}
    assert set(snapshots) == {tool.name for tool in tools}

    for tool in tools:
        observed = json.loads(snapshots[tool.name].read_text(encoding="utf-8"))
        assert observed == {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.inputSchema,
        }


def test_mcp_smoke_module_constants_align() -> None:
    """scripts/mcp_smoke.py constants stay aligned with this contract module."""
    import importlib.util

    smoke_path = Path(__file__).resolve().parents[1] / "scripts" / "mcp_smoke.py"
    spec = importlib.util.spec_from_file_location("mcp_smoke_under_test", smoke_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Avoid executing network/stdio entry; load source via exec of constants only is fragile —
    # full load is fine: mcp package is already a test dependency for live smoke.
    spec.loader.exec_module(module)
    assert module.MIN_DEFAULT_TOOL_COUNT == MIN_DEFAULT_TOOL_COUNT
    assert module.MIN_DEFAULT_TOOL_COUNT == 38
    assert "operation_submit" in module.MUTATING_TOOLS
    assert "mbg_dispatch" in module.MUTATING_TOOLS
    assert "temporal_start_promoted" in module.MUTATING_TOOLS
    assert "notification_pull" in module.MUTATING_TOOLS
