"""FastMCP adapter; all correctness remains in CoordinationService."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from .a2a_adapter import export_task_dict
from .errors import AuthorizationError, ValidationError
from .service import (
    CoordinationService,
    MCP_ADMIN_ROLES,
    MCP_BOUND_ROLES,
    MCP_DISCUSSION_ROLES,
    MCP_OPERATOR_ROLES,
    MCP_USER_ROLES,
)

# Re-export single source of truth from the service layer (CLI/MCP parity).
MCP_ROLES = MCP_BOUND_ROLES
DISCUSSION_ROLES = MCP_DISCUSSION_ROLES
USER_ROLES = MCP_USER_ROLES

mcp = FastMCP(
    "xinao-dual-brain-coordination",
    instructions=(
        "Durable local discussion/task/artifact tools. Route assessment is advisory. "
        "Notification delivery never means a model read the item. This MCP process is bound to "
        "exactly one XINAO_COORD_ROLE; mutating tools never accept caller-supplied actor values."
    ),
)


@lru_cache(maxsize=1)
def service() -> CoordinationService:
    return CoordinationService(os.environ.get("XINAO_COORD_DB"))


@lru_cache(maxsize=1)
def operation_controller() -> Any:
    from .agent_controller import AgentOperationController

    return AgentOperationController(os.environ.get("XINAO_COORD_DB"))


def experimental_agent_operations_enabled() -> bool:
    return os.environ.get("XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def bound_role() -> str:
    role = os.environ.get("XINAO_COORD_ROLE", "").strip()
    if role not in MCP_ROLES:
        raise ValidationError(
            "MCP process requires a valid XINAO_COORD_ROLE",
            details={"allowed": sorted(MCP_ROLES)},
        )
    return role


def require_bound_role(allowed: frozenset[str], action: str) -> str:
    role = bound_role()
    if role not in allowed:
        raise AuthorizationError(
            f"bound role {role} cannot {action}",
            details={"allowed": sorted(allowed)},
        )
    return role


@mcp.tool()
def coordination_status() -> dict[str, object]:
    """Check database integrity, runtime versions, and queue counts."""
    result = service().status()
    result["mcp_bound_role"] = bound_role()
    result["role_assertion"] = "process_bound_mcp_role_not_caller_supplied"
    return result


@mcp.tool()
def coordination_backup(destination: str) -> dict[str, object]:
    """Create and integrity-check an online SQLite backup at a new path."""
    require_bound_role(MCP_OPERATOR_ROLES, "back up coordination state")
    return service().backup(destination)


@mcp.tool()
def coordination_sweep() -> dict[str, object]:
    """Expire TTL threads and recover expired task/notification leases."""
    require_bound_role(MCP_OPERATOR_ROLES, "sweep coordination state")
    return service().sweep()


@mcp.tool()
def route_assess(signals: dict[str, Any]) -> dict[str, object]:
    """Advisory net-benefit routing; this result never gates execution."""
    return service().assess(signals)


@mcp.tool()
def thread_open(
    title: str,
    body: str | None = None,
    ttl_seconds: int = 7200,
    max_rounds: int = 24,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return service().open_thread(
        actor=require_bound_role(DISCUSSION_ROLES, "open a discussion"),
        title=title,
        body=body,
        ttl_seconds=ttl_seconds,
        max_rounds=max_rounds,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def thread_post(
    thread_id: str,
    body: str,
    kind: str = "note",
    recipient: str = "*",
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return service().post_message(
        actor=require_bound_role(DISCUSSION_ROLES, "post to a discussion"),
        thread_id=thread_id,
        body=body,
        kind=kind,
        recipient=recipient,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def thread_close(
    thread_id: str,
    decision: str,
    resolution_key: str,
    summary: str,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return service().close_thread(
        actor=require_bound_role(DISCUSSION_ROLES, "vote on a discussion"),
        thread_id=thread_id,
        decision=decision,
        resolution_key=resolution_key,
        summary=summary,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def propose_close(
    thread_id: str,
    decision_hash: str,
    summary: str,
    decision: str = "accept",
    proposal_id: str | None = None,
    expected_version: int | None = None,
    unresolved_points: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """T5 PROPOSE_CLOSE. Does not create a Task — only records a closure proposal/vote."""
    return service().propose_close(
        actor=require_bound_role(DISCUSSION_ROLES, "propose close on a discussion"),
        thread_id=thread_id,
        decision_hash=decision_hash,
        summary=summary,
        decision=decision,
        proposal_id=proposal_id,
        expected_version=expected_version,
        unresolved_points=unresolved_points,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def respond(
    thread_id: str,
    decision_hash: str,
    summary: str,
    decision: str = "accept",
    proposal_id: str | None = None,
    expected_version: int | None = None,
    unresolved_points: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """T5 CLOSE_RESPONSE. Must cite same decision_hash; pass expected_version for CAS."""
    return service().respond(
        actor=require_bound_role(DISCUSSION_ROLES, "respond to a close proposal"),
        thread_id=thread_id,
        decision_hash=decision_hash,
        summary=summary,
        decision=decision,
        proposal_id=proposal_id,
        expected_version=expected_version,
        unresolved_points=unresolved_points,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def thread_get(thread_id: str) -> dict[str, object]:
    return service().get_thread(thread_id)


@mcp.tool()
def thread_list(state: str | None = None, limit: int = 100) -> dict[str, object]:
    return service().list_threads(state=state, limit=limit)


def operation_submit(
    prompt: str,
    session_name: str = "xinao-main",
    cwd: str = r"E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination",
    deadline_seconds: int = 1800,
    permission_mode: str = "approve-reads",
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """Queue a durable Grok ACP turn and return immediately without waiting for the model."""
    require_bound_role(MCP_OPERATOR_ROLES, "submit a Grok agent operation")
    return operation_controller().submit_and_start(
        actor="codex",
        prompt=prompt,
        session_name=session_name,
        cwd=cwd,
        deadline_seconds=deadline_seconds,
        max_attempts=1,
        replay_safe=False,
        idempotency_key=idempotency_key or f"mcp-operation-{os.urandom(16).hex()}",
        metadata={"permission_mode": permission_mode},
    )


def operation_get(operation_id: str) -> dict[str, object]:
    """Read durable state and evidence paths for a Grok ACP operation."""
    return operation_controller().store.get(operation_id)


def operation_list(state: str | None = None, limit: int = 100) -> dict[str, object]:
    """List durable Grok ACP operations."""
    return operation_controller().store.list(state=state, limit=limit)


def operation_cancel(operation_id: str, reason: str) -> dict[str, object]:
    """Persist a cancellation request; the worker verifies the provider terminal state."""
    require_bound_role(MCP_OPERATOR_ROLES, "cancel a Grok agent operation")
    return operation_controller().store.request_cancel(operation_id, actor="codex", reason=reason)


def operation_reconcile(
    operation_id: str | None = None,
    limit: int = 20,
    max_runtime_seconds: int = 120,
) -> dict[str, object]:
    """Run one bounded recovery pass; this command never starts a perpetual daemon."""
    require_bound_role(MCP_OPERATOR_ROLES, "reconcile Grok agent operations")
    return operation_controller().reconcile(
        operation_id,
        limit=limit,
        max_runtime_seconds=max_runtime_seconds,
    )


@mcp.tool()
def task_dispatch(
    title: str,
    goal: str,
    source_thread_id: str | None = None,
    explicit_non_consensus: bool = False,
    priority: int = 100,
    max_attempts: int = 3,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return service().dispatch_task(
        actor=require_bound_role(DISCUSSION_ROLES, "dispatch an Admin task"),
        title=title,
        goal=goal,
        source_thread_id=source_thread_id,
        explicit_non_consensus=explicit_non_consensus,
        priority=priority,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def task_list(state: str | None = None, limit: int = 100) -> dict[str, object]:
    return service().list_tasks(state=state, limit=limit)


@mcp.tool()
def task_get(task_id: str) -> dict[str, object]:
    return service().get_task(task_id)


@mcp.tool()
def task_claim(
    lease_seconds: int = 300,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return service().claim_task(
        worker_id=require_bound_role(MCP_ADMIN_ROLES, "claim an Admin task"),
        lease_seconds=lease_seconds,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def task_start(task_id: str, lease_token: str, idempotency_key: str | None = None) -> dict[str, object]:
    require_bound_role(MCP_ADMIN_ROLES, "start an Admin task")
    return service().start_task(task_id=task_id, lease_token=lease_token, idempotency_key=idempotency_key)


@mcp.tool()
def task_heartbeat(
    task_id: str,
    lease_token: str,
    lease_seconds: int = 300,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    require_bound_role(MCP_ADMIN_ROLES, "heartbeat an Admin task")
    return service().heartbeat_task(
        task_id=task_id,
        lease_token=lease_token,
        lease_seconds=lease_seconds,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def task_complete(
    task_id: str,
    lease_token: str,
    result_summary: str,
    evidence: list[dict[str, Any]],
    artifacts: list[dict[str, Any]] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    require_bound_role(MCP_ADMIN_ROLES, "complete an Admin task")
    return service().complete_task(
        task_id=task_id,
        lease_token=lease_token,
        result_summary=result_summary,
        evidence=evidence,
        artifacts=artifacts,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def task_fail(
    task_id: str,
    lease_token: str,
    error: str,
    retryable: bool = True,
    retry_delay_seconds: int = 0,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    require_bound_role(MCP_ADMIN_ROLES, "fail an Admin task")
    return service().fail_task(
        task_id=task_id,
        lease_token=lease_token,
        error=error,
        retryable=retryable,
        retry_delay_seconds=retry_delay_seconds,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def task_pause(task_id: str, reason: str, idempotency_key: str | None = None) -> dict[str, object]:
    return service().pause_task(
        actor=require_bound_role(DISCUSSION_ROLES, "pause an Admin task"),
        task_id=task_id,
        reason=reason,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def task_resume(task_id: str, reason: str, idempotency_key: str | None = None) -> dict[str, object]:
    return service().resume_task(
        actor=require_bound_role(DISCUSSION_ROLES, "resume an Admin task"),
        task_id=task_id,
        reason=reason,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def task_cancel(task_id: str, reason: str, idempotency_key: str | None = None) -> dict[str, object]:
    return service().cancel_task(
        actor=require_bound_role(DISCUSSION_ROLES, "cancel an Admin task"),
        task_id=task_id,
        reason=reason,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def artifact_register_local(
    task_id: str,
    path: str,
    name: str | None = None,
    media_type: str = "application/octet-stream",
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return service().register_local_artifact(
        actor=require_bound_role(MCP_ADMIN_ROLES, "register an Admin task artifact"),
        task_id=task_id,
        path=path,
        name=name,
        media_type=media_type,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def notification_pull(
    adapter_id: str,
    lease_seconds: int = 60,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    role = bound_role()
    return service().pull_notification(
        actor=role,
        recipient=role,
        adapter_id=adapter_id,
        lease_seconds=lease_seconds,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def notification_ack(
    notification_id: str,
    lease_token: str,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    return service().ack_notification(
        actor=bound_role(),
        notification_id=notification_id,
        lease_token=lease_token,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def receipt_record(
    item_type: str,
    item_id: str,
    receipt_type: str = "observed",
) -> dict[str, object]:
    return service().record_receipt(
        actor=bound_role(), item_type=item_type, item_id=item_id, receipt_type=receipt_type
    )


@mcp.tool()
def events_list(
    stream_type: str | None = None,
    stream_id: str | None = None,
    after_seq: int = 0,
    limit: int = 200,
) -> dict[str, object]:
    return service().events(
        stream_type=stream_type,
        stream_id=stream_id,
        after_seq=after_seq,
        limit=limit,
    )


@mcp.tool()
def task_export_a2a(task_id: str) -> dict[str, Any]:
    """Export the current durable task as the official A2A protobuf JSON shape."""
    return export_task_dict(service(), task_id)


@mcp.tool()
def promote_to_task(
    source_thread_id: str,
    decision_hash: str,
    title: str,
    goal: str,
    writer_scope: str = "default",
    acceptance: str | None = None,
    budget: str | None = None,
    stop_scope: str = "global",
    priority: int = 100,
    max_attempts: int = 3,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """Explicit promote only. Requires ACCEPTED thread + matching decision_hash. No chat auto-task."""
    return service().promote_to_task(
        actor=require_bound_role(DISCUSSION_ROLES, "promote a thread to task"),
        source_thread_id=source_thread_id,
        decision_hash=decision_hash,
        title=title,
        goal=goal,
        owner="admin",
        writer_scope=writer_scope,
        acceptance=acceptance,
        budget=budget,
        stop_scope=stop_scope,
        priority=priority,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def stop_raise(
    reason: str,
    scope: str = "global",
    cancel_active_tasks: bool = True,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """User/brain stop: freeze active tasks and reject new promote/dispatch until clear_stop."""
    return service().user_stop(
        actor=require_bound_role(MCP_USER_ROLES | DISCUSSION_ROLES, "raise stop"),
        reason=reason,
        scope=scope,
        cancel_active_tasks=cancel_active_tasks,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def stop_clear(reason: str, idempotency_key: str | None = None) -> dict[str, object]:
    """Explicit clear only — Stop never auto-resumes. Bound role must be user (not brains/admin)."""
    return service().clear_stop(
        actor=require_bound_role(USER_ROLES, "clear stop"),
        reason=reason,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def stop_status() -> dict[str, object]:
    return service().stop_status()


@mcp.tool()
def mbg_status() -> dict[str, object]:
    """T8 M-BG policy: enabled, auto_dispatch=false, stop_preempts, capacity."""
    return service().mbg_status()


@mcp.tool()
def mkeep_status() -> dict[str, object]:
    """T10 capability status: installed, default-off, observe-only, no timer."""
    return service().mkeep_status()


@mcp.tool()
def mkeep_observe(
    snapshot: dict[str, object],
    binding: dict[str, object] | None = None,
    expected_binding: dict[str, object] | None = None,
    pause_active: bool = False,
) -> dict[str, object]:
    """Classify one supplied snapshot; never inspect, resume, or mutate a live session."""
    return service().mkeep_observe(
        snapshot=snapshot,
        binding=binding,
        expected_binding=expected_binding,
        pause_active=pause_active,
    )


@mcp.tool()
def mbg_dispatch(
    task_id: str,
    session_name: str | None = None,
    cwd: str | None = None,
    deadline_seconds: int = 1800,
    max_attempts: int = 1,
    idempotency_key: str | None = None,
    start_transport: bool = False,
) -> dict[str, object]:
    """Explicit M-BG only. Requires promoted task. Default: queue operation, no Temporal."""
    return service().mbg_dispatch(
        actor=require_bound_role(DISCUSSION_ROLES, "M-BG dispatch"),
        task_id=task_id,
        session_name=session_name,
        cwd=cwd,
        deadline_seconds=deadline_seconds,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
        start_transport=start_transport,
    )


@mcp.tool()
def temporal_status() -> dict[str, object]:
    """T9 Temporal policy: mode (disabled/mock/live), connectivity, poller_count, queue probe.

    Live connect is env-only (XINAO_TEMPORAL_LIVE=1); promoted-only; auto_start_on_promote=false.
    """
    return service().temporal_status()


@mcp.tool()
def temporal_start_promoted(
    task_id: str,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """Explicit T9 only. Requires promoted task. Returns mode, run_id, replayed.

    Default mock registry; live via XINAO_TEMPORAL_LIVE=1 env only (no CLI --live flag).
    """
    return service().temporal_start_promoted(
        actor=require_bound_role(DISCUSSION_ROLES, "start promoted Temporal workflow"),
        task_id=task_id,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def mbg_finish(
    task_id: str,
    lease_token: str,
    result_summary: str,
    success: bool = True,
    error: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """Admin worker: close M-BG-bound Task (+ operation lease if still held)."""
    return service().mbg_finish(
        actor=require_bound_role(MCP_ADMIN_ROLES, "finish M-BG task"),
        task_id=task_id,
        lease_token=lease_token,
        result_summary=result_summary,
        success=success,
        error=error,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def amq_ingest(recipient_role: str | None = None, limit: int = 20) -> dict[str, object]:
    """Drain AMQ new mail for the bound role into the kernel (PERSISTED receipt stage)."""
    from .amq import AmqIngestor, AmqTransport

    role = bound_role()
    target = recipient_role or role
    if target != role and role != "codex":
        raise AuthorizationError(
            "bound role may only ingest its own mailbox unless codex operator",
            details={"bound": role, "requested": target},
        )
    return AmqIngestor(service(), AmqTransport()).ingest_for_role(
        recipient_role=target,
        limit=limit,
    )


if experimental_agent_operations_enabled():
    for _experimental_tool in (
        operation_submit,
        operation_get,
        operation_list,
        operation_cancel,
        operation_reconcile,
    ):
        mcp.tool()(_experimental_tool)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
