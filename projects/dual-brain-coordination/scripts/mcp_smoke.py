"""Launch a fresh stdio MCP process and verify tool discovery plus a real call."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Default (non-experimental) surface is currently 38 tools. Prefer floor over exact
# equality so additive tools do not hard-fail smoke until the floor is raised.
MIN_DEFAULT_TOOL_COUNT = 40

# Mutating / identity-sensitive tools must never expose caller-supplied actor or worker_id.
# Includes experimental operation_* names so schema checks apply if that surface is enabled.
MUTATING_TOOLS = {
    "amq_ingest",
    "artifact_register_local",
    "mbg_dispatch",
    "mbg_finish",
    "notification_ack",
    "notification_pull",
    "operation_cancel",
    "operation_reconcile",
    "operation_submit",
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

# Core tools that must always be present on the default surface.
REQUIRED_TOOLS = frozenset(
    {
        "amq_ingest",
        "coordination_status",
        "mbg_status",
        "promote_to_task",
        "route_assess",
        "stop_status",
        "task_claim",
        "task_complete",
        "task_dispatch",
        "task_export_a2a",
        "temporal_status",
        "thread_open",
    }
)


def schema_properties(tool: Any) -> set[str]:
    schema = tool.inputSchema
    return set(schema.get("properties", {}))


def _stdio_parameters(
    project: Path,
    db: Path,
    launcher: Path,
    role: str,
    *,
    direct: bool,
    runtime_root: Path | None = None,
) -> StdioServerParameters:
    env = {
        **os.environ,
        "XINAO_COORD_DB": str(db),
        "XINAO_COORD_ROLE": role,
        "PYTHONPATH": str(project / "src")
        + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
    }
    if direct:
        # Direct module launch: contract surface without managed packaging hash gate.
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", "xinao_coordination.mcp_server"],
            env=env,
            cwd=str(project),
        )
    managed_args = [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launcher),
        "-Target",
        "mcp",
    ]
    if runtime_root is not None:
        managed_args.extend(["-RuntimeRoot", str(runtime_root)])
    return StdioServerParameters(
        command="pwsh.exe",
        args=managed_args,
        env=env,
    )


async def run(
    project: Path,
    db: Path,
    launcher: Path,
    role: str,
    *,
    direct: bool = False,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    parameters = _stdio_parameters(
        project,
        db,
        launcher,
        role,
        direct=direct,
        runtime_root=runtime_root,
    )
    async with (
        stdio_client(parameters) as (reader, writer),
        ClientSession(reader, writer) as session,
    ):
        initialized = await session.initialize()
        listed = await session.list_tools()
        names = sorted(tool.name for tool in listed.tools)
        surface_rows = [
            {"name": tool.name, "input_schema": tool.inputSchema}
            for tool in sorted(listed.tools, key=lambda item: item.name)
        ]
        surface_sha256 = hashlib.sha256(
            json.dumps(surface_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        forbidden_schema_parameters = {
            tool.name: sorted(schema_properties(tool) & {"actor", "worker_id"})
            for tool in listed.tools
            if tool.name in MUTATING_TOOLS and schema_properties(tool) & {"actor", "worker_id"}
        }
        notification_pull = next(
            (tool for tool in listed.tools if tool.name == "notification_pull"),
            None,
        )
        notification_pull_exposes_recipient = bool(
            notification_pull is not None and "recipient" in schema_properties(notification_pull)
        )
        status = await session.call_tool("coordination_status", {})
        payload = json.loads(status.content[0].text)
    missing_required = sorted(REQUIRED_TOOLS - set(names))
    tool_count = len(names)
    return {
        "ok": (
            not missing_required
            and tool_count >= MIN_DEFAULT_TOOL_COUNT
            and payload.get("ok") is True
            and payload.get("mcp_bound_role") == role
            and not forbidden_schema_parameters
            and not notification_pull_exposes_recipient
        ),
        "server_name": initialized.serverInfo.name,
        "server_version": initialized.serverInfo.version,
        "tool_count": tool_count,
        "min_default_tool_count": MIN_DEFAULT_TOOL_COUNT,
        "tools": names,
        "tool_surface_sha256": surface_sha256,
        "required_tools_present": sorted(REQUIRED_TOOLS & set(names)),
        "missing_tools": missing_required,
        "forbidden_schema_parameters": forbidden_schema_parameters,
        "notification_pull_exposes_recipient": notification_pull_exposes_recipient,
        "expected_bound_role": role,
        "launch_mode": "direct" if direct else "managed",
        "generation_id": payload.get("generation_id"),
        "source_fingerprint": payload.get("source_fingerprint"),
        "status": payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--role", choices=("codex", "grok_4_5", "admin"), default="codex")
    parser.add_argument(
        "--runtime-root",
        type=Path,
        help="Use an isolated managed-generation root without changing the active current.json.",
    )
    parser.add_argument(
        "--launcher",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "provisioning" / "Invoke-XinaoCoordManaged.ps1",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Launch python -m xinao_coordination.mcp_server (skip managed packaging hash gate)",
    )
    args = parser.parse_args()
    result = asyncio.run(
        run(
            args.project.resolve(),
            args.db.resolve(),
            args.launcher.resolve(),
            args.role,
            direct=args.direct,
            runtime_root=args.runtime_root.resolve() if args.runtime_root else None,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
