"""Versioned contract for the isolated OpenHands command endpoint.

The workflow is intentionally tiny.  Temporal remains the durable scheduler;
the Activity owns every Docker and command side effect.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

SCHEMA_VERSION = "xinao.openhands.execute.v1"
WORKFLOW_NAME = "XinaoOpenHandsExecuteWorkflowV1"
ACTIVITY_NAME = "xinao.openhands.execute_command"
TASK_QUEUE = "xinao-openhands-execution-v1"
IMAGE = (
    "ghcr.io/openhands/agent-server@"
    "sha256:b31ac1a1865efd48966d95fdcc4cbd097883d2a63348bc582e3d2448318fef52"
)
SDK_VERSION = "1.35.0"
CONTROL_NETWORK = "xinao_sandbox_control_v1"
PER_REQUEST_NETWORK_PREFIX = "xinao_oh_req_v1"
NETWORK_ENDPOINT_ID = "openhands-execution-network-v1"
BROKER_CONTAINER_NAME = "mowei-zhixing"
BROKER_ENDPOINT_ID = "openhands-execution-broker-v1"
MAX_COMMAND_CHARS = 16_000
MAX_TIMEOUT_SECONDS = 300
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def validate_execute_request(payload: object) -> dict[str, Any]:
    """Return the canonical request; reject model-controlled infrastructure knobs."""

    if not isinstance(payload, dict):
        raise TypeError("execute request must be an object")
    allowed = {
        "schema_version",
        "operation_key",
        "command",
        "timeout_seconds",
        "parent_operation_id",
        "parent_workflow_id",
        "lane_id",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unsupported execute request fields: {unknown}")
    if str(payload.get("schema_version") or SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ValueError("unsupported execute request schema")
    operation_key = str(payload.get("operation_key") or "").strip()
    if not _SAFE_KEY.fullmatch(operation_key):
        raise ValueError("operation_key must be 1-80 safe characters")
    command = str(payload.get("command") or "")
    if not command.strip() or len(command) > MAX_COMMAND_CHARS:
        raise ValueError(f"command must be 1-{MAX_COMMAND_CHARS} characters")
    timeout_seconds = int(payload.get("timeout_seconds") or 60)
    if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be 1-{MAX_TIMEOUT_SECONDS}")
    canonical = {
        "schema_version": SCHEMA_VERSION,
        "operation_key": operation_key,
        "command": command,
        "timeout_seconds": timeout_seconds,
        "parent_operation_id": str(payload.get("parent_operation_id") or "").strip(),
        "parent_workflow_id": str(payload.get("parent_workflow_id") or "").strip(),
        "lane_id": str(payload.get("lane_id") or "").strip(),
    }
    for field in ("parent_operation_id", "parent_workflow_id", "lane_id"):
        if not canonical[field]:
            raise ValueError(f"{field} is required and must be process-bound")
    return canonical


def execute_request_hash(payload: object) -> str:
    canonical = validate_execute_request(payload)
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@workflow.defn(name=WORKFLOW_NAME)
class XinaoOpenHandsExecuteWorkflowV1:
    """Durably invoke exactly one isolated command Activity."""

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = validate_execute_request(payload)
        request_hash = execute_request_hash(request)
        result = await workflow.execute_activity(
            ACTIVITY_NAME,
            request,
            result_type=dict,
            start_to_close_timeout=timedelta(seconds=request["timeout_seconds"] + 150),
            heartbeat_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(
                maximum_attempts=2,
                non_retryable_error_types=["ValueError", "TypeError"],
            ),
        )
        if not isinstance(result, dict) or result.get("request_hash") != request_hash:
            raise RuntimeError("OpenHands Activity result is not bound to this request")
        return result


__all__ = [
    "ACTIVITY_NAME",
    "BROKER_CONTAINER_NAME",
    "BROKER_ENDPOINT_ID",
    "CONTROL_NETWORK",
    "IMAGE",
    "NETWORK_ENDPOINT_ID",
    "PER_REQUEST_NETWORK_PREFIX",
    "SCHEMA_VERSION",
    "SDK_VERSION",
    "TASK_QUEUE",
    "WORKFLOW_NAME",
    "XinaoOpenHandsExecuteWorkflowV1",
    "execute_request_hash",
    "validate_execute_request",
]
