"""One-tool MCP facade for the Temporal-owned OpenHands execution endpoint."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from services.agent_runtime.openhands_execution_contract import (
    SCHEMA_VERSION,
    TASK_QUEUE,
    XinaoOpenHandsExecuteWorkflowV1,
    execute_request_hash,
    validate_execute_request,
)
from temporalio.client import Client

mcp = FastMCP(
    "xinao-sandbox-execution",
    instructions=(
        "Fixed-role command endpoint. Commands execute only in a fresh pinned OpenHands "
        "container owned by a Temporal Activity; no host shell, image, network, or volume "
        "selection is exposed."
    ),
)
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def _bound(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"MCP process requires bound {name}")
    return value


def _workflow_id(request: dict[str, Any]) -> str:
    parent = _SAFE_ID.sub("-", request["parent_operation_id"]).strip("-.")[:48]
    key = _SAFE_ID.sub("-", request["operation_key"]).strip("-.")[:48]
    digest = hashlib.sha256(
        f"{request['parent_operation_id']}\n{request['operation_key']}".encode()
    ).hexdigest()[:16]
    return f"xinao-openhands-{parent}-{key}-{digest}"


async def _submit(request: dict[str, Any]) -> dict[str, Any]:
    address = os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233").strip()
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default").strip()
    client = await Client.connect(address, namespace=namespace)
    workflow_id = _workflow_id(request)
    try:
        result = await client.execute_workflow(
            XinaoOpenHandsExecuteWorkflowV1.run,
            request,
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
    except Exception as exc:
        if type(exc).__name__ != "WorkflowAlreadyStartedError":
            raise
        result = await client.get_workflow_handle(workflow_id).result()
    if not isinstance(result, dict):
        raise RuntimeError("sandbox workflow returned a non-object result")
    expected_hash = execute_request_hash(request)
    if result.get("request_hash") != expected_hash:
        raise RuntimeError("operation_key replay payload mismatch")
    return result


@mcp.tool()
async def sandbox_execute(
    operation_key: str,
    command: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Execute one command in the pinned isolated sandbox; never on the host."""

    request = validate_execute_request(
        {
            "schema_version": SCHEMA_VERSION,
            "operation_key": operation_key,
            "command": command,
            "timeout_seconds": timeout_seconds,
            "parent_operation_id": _bound("XINAO_OPERATION_ID"),
            "parent_workflow_id": _bound("XINAO_TEMPORAL_PARENT_WORKFLOW_ID"),
            "lane_id": _bound("XINAO_TEMPORAL_LANE_ID"),
        }
    )
    return await _submit(request)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = ["mcp", "sandbox_execute"]
