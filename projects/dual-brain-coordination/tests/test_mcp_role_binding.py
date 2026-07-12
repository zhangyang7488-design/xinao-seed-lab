from __future__ import annotations

import asyncio
import inspect

import pytest

from xinao_coordination import mcp_server
from xinao_coordination.errors import AuthorizationError, ValidationError
from xinao_coordination.service import (
    MCP_ADMIN_ROLES,
    MCP_BOUND_ROLES,
    MCP_DISCUSSION_ROLES,
    MCP_USER_ROLES,
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
    mcp_server.operation_submit,
    mcp_server.operation_cancel,
    mcp_server.operation_reconcile,
    mcp_server.promote_to_task,
    mcp_server.stop_raise,
    mcp_server.stop_clear,
    mcp_server.amq_ingest,
    mcp_server.mbg_dispatch,
    mcp_server.mbg_finish,
    mcp_server.temporal_start_promoted,
)

# Default MCP surface is 38 tools (T2 + T5/T8/T9/AMQ). Extra experimental tools may land separately.
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


def configure(monkeypatch: pytest.MonkeyPatch, tmp_path, role: str) -> None:
    monkeypatch.setenv("XINAO_COORD_DB", str(tmp_path / "coordination.sqlite3"))
    monkeypatch.setenv("XINAO_COORD_ROLE", role)
    mcp_server.service.cache_clear()


def test_mcp_role_sets_match_service_layer() -> None:
    """CLI/MCP must share one role vocabulary from the service layer."""
    assert mcp_server.MCP_ROLES == MCP_BOUND_ROLES == frozenset({"codex", "grok_4_5", "admin", "user"})
    assert mcp_server.DISCUSSION_ROLES == MCP_DISCUSSION_ROLES == frozenset({"codex", "grok_4_5"})
    assert mcp_server.USER_ROLES == MCP_USER_ROLES == frozenset({"user"})
    assert frozenset({"admin"}) == MCP_ADMIN_ROLES
    assert "admin" not in MCP_DISCUSSION_ROLES
    assert "user" not in MCP_DISCUSSION_ROLES


def test_mutating_mcp_tools_do_not_accept_caller_supplied_actor() -> None:
    for tool in MUTATING_TOOLS:
        parameters = inspect.signature(tool).parameters
        assert "actor" not in parameters, f"{tool.__name__} must not accept actor"
        assert "worker_id" not in parameters, f"{tool.__name__} must not accept worker_id"
    assert "worker_id" not in inspect.signature(mcp_server.task_claim).parameters
    assert "recipient" not in inspect.signature(mcp_server.notification_pull).parameters


def test_agent_operations_are_not_on_default_mcp_surface() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in tools}
    missing = REQUIRED_DEFAULT_TOOLS - names
    assert not missing, f"missing required MCP tools: {sorted(missing)}"
    assert len(names) >= 40, f"expected default tool_count>=40, got {len(names)}"
    assert not {name for name in names if name.startswith("operation_")}


def test_missing_or_unknown_bound_role_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XINAO_COORD_ROLE", raising=False)
    with pytest.raises(ValidationError):
        mcp_server.bound_role()
    monkeypatch.setenv("XINAO_COORD_ROLE", "system")
    with pytest.raises(ValidationError):
        mcp_server.bound_role()
    # user is a valid bound role (stop_clear host); unknown roles still reject
    monkeypatch.setenv("XINAO_COORD_ROLE", "user")
    assert mcp_server.bound_role() == "user"


def test_grok_process_can_only_write_as_grok(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    configure(monkeypatch, tmp_path, "grok_4_5")
    opened = mcp_server.thread_open(title="bound", idempotency_key="open")
    thread_id = opened["thread"]["thread_id"]
    mcp_server.thread_post(
        thread_id=thread_id,
        body="counter",
        kind="counter",
        recipient="codex",
        idempotency_key="post",
    )
    observed = mcp_server.thread_get(thread_id)
    assert observed["messages"][-1]["sender"] == "grok_4_5"
    with pytest.raises(TypeError):
        mcp_server.thread_post(  # type: ignore[call-arg]
            actor="codex",
            thread_id=thread_id,
            body="spoof",
        )


def test_codex_process_can_only_write_as_codex(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    configure(monkeypatch, tmp_path, "codex")
    opened = mcp_server.thread_open(title="codex-bound", body="proposal", idempotency_key="open")
    assert opened["thread"]["opened_by"] == "codex"
    thread_id = opened["thread"]["thread_id"]
    with pytest.raises(TypeError):
        mcp_server.thread_open(  # type: ignore[call-arg]
            actor="grok_4_5",
            title="impersonate",
        )
    with pytest.raises(TypeError):
        mcp_server.thread_close(  # type: ignore[call-arg]
            actor="admin",
            thread_id=thread_id,
            decision="accept",
            resolution_key="r",
            summary="s",
        )


def test_admin_cannot_open_post_or_close_discussion(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    configure(monkeypatch, tmp_path, "admin")
    with pytest.raises(AuthorizationError) as open_exc:
        mcp_server.thread_open(title="admin cannot discuss")
    assert "admin" in str(open_exc.value).lower() or "cannot" in str(open_exc.value).lower()

    # Seed a thread as a brain so post/close targets exist; rebind to admin for denial.
    configure(monkeypatch, tmp_path, "codex")
    opened = mcp_server.thread_open(title="seed", body="seed", idempotency_key="seed-open")
    thread_id = opened["thread"]["thread_id"]

    configure(monkeypatch, tmp_path, "admin")
    with pytest.raises(AuthorizationError):
        mcp_server.thread_post(thread_id=thread_id, body="admin post", idempotency_key="admin-post")
    with pytest.raises(AuthorizationError):
        mcp_server.thread_close(
            thread_id=thread_id,
            decision="accept",
            resolution_key="r",
            summary="no",
            idempotency_key="admin-close",
        )
    with pytest.raises(AuthorizationError):
        mcp_server.promote_to_task(
            source_thread_id=thread_id,
            decision_hash="r",
            title="no",
            goal="no",
            idempotency_key="admin-promote",
        )
    with pytest.raises(AuthorizationError):
        mcp_server.propose_close(
            thread_id=thread_id,
            decision_hash="r",
            summary="no",
            idempotency_key="admin-propose-close",
        )
    with pytest.raises(AuthorizationError):
        mcp_server.respond(
            thread_id=thread_id,
            decision_hash="r",
            summary="no",
            idempotency_key="admin-respond",
        )


def test_role_specific_tools_reject_the_wrong_process(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    configure(monkeypatch, tmp_path, "admin")
    with pytest.raises(AuthorizationError):
        mcp_server.thread_open(title="admin cannot discuss")

    configure(monkeypatch, tmp_path, "codex")
    with pytest.raises(AuthorizationError):
        mcp_server.task_claim()

    configure(monkeypatch, tmp_path, "grok_4_5")
    with pytest.raises(AuthorizationError):
        mcp_server.operation_submit(prompt="cannot dispatch itself")
    with pytest.raises(AuthorizationError):
        mcp_server.task_claim()


def test_impersonation_kwargs_rejected_on_all_mutating_tools() -> None:
    """Caller-supplied actor/worker_id must never be accepted (冒充 actor 拒绝)."""
    for tool in MUTATING_TOOLS:
        sig = inspect.signature(tool)
        for banned in ("actor", "worker_id"):
            assert banned not in sig.parameters, f"{tool.__name__} exposes {banned}"


def test_notification_pull_cannot_spoof_recipient(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    configure(monkeypatch, tmp_path, "codex")
    # No recipient/worker_id knobs; bound role is the only identity.
    with pytest.raises(TypeError):
        mcp_server.notification_pull(  # type: ignore[call-arg]
            adapter_id="cli",
            recipient="admin",
        )
    with pytest.raises(TypeError):
        mcp_server.notification_pull(  # type: ignore[call-arg]
            adapter_id="cli",
            actor="admin",
        )


def test_stop_clear_only_user_bound_role(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """stop_clear is user-host only; brains/admin must not clear stop via MCP."""
    configure(monkeypatch, tmp_path, "codex")
    mcp_server.stop_raise(reason="freeze", idempotency_key="raise-for-clear")
    assert mcp_server.stop_status()["active"] is True

    for role in ("codex", "grok_4_5", "admin"):
        configure(monkeypatch, tmp_path, role)
        with pytest.raises(AuthorizationError) as exc:
            mcp_server.stop_clear(reason="spoof clear", idempotency_key=f"deny-{role}")
        assert "cannot clear stop" in str(exc.value).lower() or "clear stop" in str(exc.value).lower()
        assert mcp_server.stop_status()["active"] is True

    configure(monkeypatch, tmp_path, "user")
    cleared = mcp_server.stop_clear(reason="resume authorized", idempotency_key="user-clear")
    assert cleared["active"] is False
    assert mcp_server.stop_status()["active"] is False
    with pytest.raises(TypeError):
        mcp_server.stop_clear(  # type: ignore[call-arg]
            actor="user",
            reason="must not accept actor",
        )
    # user host still cannot discuss (DISCUSSION_ROLES only)
    with pytest.raises(AuthorizationError):
        mcp_server.thread_open(title="user cannot discuss", idempotency_key="user-open")


def test_user_bound_role_can_raise_stop_without_discussion_rights(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    configure(monkeypatch, tmp_path, "user")
    raised = mcp_server.stop_raise(
        reason="user freeze",
        cancel_active_tasks=False,
        idempotency_key="user-raise",
    )
    assert raised["active"] is True
    assert raised["canceled_tasks"] == []
    with pytest.raises(AuthorizationError):
        mcp_server.thread_open(title="still not a discussion role", idempotency_key="deny")
