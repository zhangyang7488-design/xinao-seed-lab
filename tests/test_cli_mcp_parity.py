"""T2: CLI and MCP adapters share CoordinationService; role gates are isomorphic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xinao_coordination import mcp_server
from xinao_coordination.cli import main
from xinao_coordination.errors import AuthorizationError
from xinao_coordination.service import CoordinationService, MCP_BOUND_ROLES, MCP_DISCUSSION_ROLES


def _configure_mcp(monkeypatch: pytest.MonkeyPatch, db_path: Path, role: str) -> None:
    monkeypatch.setenv("XINAO_COORD_DB", str(db_path))
    monkeypatch.setenv("XINAO_COORD_ROLE", role)
    mcp_server.service.cache_clear()


def test_cli_and_mcp_open_post_same_service_objects(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, capsys: object
) -> None:
    """Same DB + same inputs → same durable thread/message shape via both adapters."""
    # CLI path (trusted --actor)
    code = main(
        [
            "--db",
            str(db_path),
            "thread-open",
            "--actor",
            "grok_4_5",
            "--title",
            "parity",
            "--body",
            "from-cli",
            "--idempotency-key",
            "parity-open",
        ]
    )
    assert code == 0
    cli_open = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    thread_id = cli_open["thread"]["thread_id"]
    assert cli_open["thread"]["opened_by"] == "grok_4_5"
    assert cli_open["ok"] is True

    # MCP path reuses the same DB; bound role is codex posting to the CLI-opened thread
    _configure_mcp(monkeypatch, db_path, "codex")
    mcp_post = mcp_server.thread_post(
        thread_id=thread_id,
        body="from-mcp",
        kind="counter",
        idempotency_key="parity-post",
    )
    assert mcp_post["ok"] is True

    # CLI readback matches MCP state
    code = main(["--db", str(db_path), "thread-get", "--thread-id", thread_id])
    assert code == 0
    observed = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    senders = [m["sender"] for m in observed["messages"]]
    bodies = [m["body"] for m in observed["messages"]]
    assert "grok_4_5" in senders
    assert "codex" in senders
    assert "from-cli" in bodies
    assert "from-mcp" in bodies

    # Service layer direct read agrees (single source of truth)
    svc = CoordinationService(db_path)
    direct = svc.get_thread(thread_id)
    assert direct["thread"]["thread_id"] == thread_id
    assert len(direct["messages"]) == len(observed["messages"])


def test_cli_admin_cannot_open_or_post_discussion(db_path: Path, capsys: object) -> None:
    code = main(
        [
            "--db",
            str(db_path),
            "thread-open",
            "--actor",
            "admin",
            "--title",
            "forbidden",
            "--idempotency-key",
            "admin-open",
        ]
    )
    assert code == 2
    denied = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert denied["error"] == "authorization_denied"

    # Seed as brain, then admin post denied
    code = main(
        [
            "--db",
            str(db_path),
            "thread-open",
            "--actor",
            "codex",
            "--title",
            "seed",
            "--body",
            "seed",
            "--idempotency-key",
            "seed",
        ]
    )
    assert code == 0
    thread_id = json.loads(capsys.readouterr().out)["thread"]["thread_id"]  # type: ignore[attr-defined]

    code = main(
        [
            "--db",
            str(db_path),
            "thread-post",
            "--actor",
            "admin",
            "--thread-id",
            thread_id,
            "--body",
            "nope",
            "--idempotency-key",
            "admin-post",
        ]
    )
    assert code == 2
    denied_post = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert denied_post["error"] == "authorization_denied"


def test_cli_admin_cannot_close_discussion(db_path: Path, capsys: object) -> None:
    code = main(
        [
            "--db",
            str(db_path),
            "thread-open",
            "--actor",
            "codex",
            "--title",
            "close-deny",
            "--body",
            "seed",
            "--idempotency-key",
            "open",
        ]
    )
    assert code == 0
    thread_id = json.loads(capsys.readouterr().out)["thread"]["thread_id"]  # type: ignore[attr-defined]
    code = main(
        [
            "--db",
            str(db_path),
            "thread-close",
            "--actor",
            "admin",
            "--thread-id",
            thread_id,
            "--decision",
            "accept",
            "--resolution-key",
            "r",
            "--summary",
            "no",
            "--idempotency-key",
            "admin-close",
        ]
    )
    assert code == 2
    denied = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert denied["error"] == "authorization_denied"


def test_service_admin_post_and_close_denied(service: CoordinationService) -> None:
    opened = service.open_thread(actor="codex", title="svc-admin", body="x", idempotency_key="o")
    thread_id = opened["thread"]["thread_id"]
    with pytest.raises(AuthorizationError):
        service.post_message(actor="admin", thread_id=thread_id, body="no", idempotency_key="p")
    with pytest.raises(AuthorizationError):
        service.close_thread(
            actor="admin",
            thread_id=thread_id,
            decision="accept",
            resolution_key="r",
            summary="no",
            idempotency_key="c",
        )


def test_cli_impersonation_is_trusted_declaration_but_service_enforces_admin(
    db_path: Path, capsys: object
) -> None:
    """CLI --actor is trusted-local; still cannot invent admin discussion rights."""
    # Spoofing as grok via CLI is allowed (trusted ops) and lands as grok_4_5
    code = main(
        [
            "--db",
            str(db_path),
            "thread-open",
            "--actor",
            "grok_4_5",
            "--title",
            "trusted",
            "--idempotency-key",
            "trusted-open",
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["thread"]["opened_by"] == "grok_4_5"  # type: ignore[attr-defined]

    # But claiming actor=admin for discussion is still authorization_denied at service
    code = main(
        [
            "--db",
            str(db_path),
            "thread-open",
            "--actor",
            "admin",
            "--title",
            "fake-admin-discuss",
            "--idempotency-key",
            "fake-admin",
        ]
    )
    assert code == 2
    assert json.loads(capsys.readouterr().out)["error"] == "authorization_denied"  # type: ignore[attr-defined]


def test_mcp_bound_roles_cover_codex_grok_admin_user() -> None:
    assert MCP_BOUND_ROLES == frozenset({"codex", "grok_4_5", "admin", "user"})
    assert MCP_DISCUSSION_ROLES == frozenset({"codex", "grok_4_5"})
    assert "admin" not in MCP_DISCUSSION_ROLES
    assert "user" not in MCP_DISCUSSION_ROLES


def test_cli_and_mcp_authorization_errors_share_code(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, capsys: object
) -> None:
    """Parity: admin discuss denial via both adapters uses authorization_denied."""
    code = main(
        [
            "--db",
            str(db_path),
            "thread-open",
            "--actor",
            "admin",
            "--title",
            "x",
            "--idempotency-key",
            "cli-deny",
        ]
    )
    assert code == 2
    cli_err = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert cli_err["error"] == "authorization_denied"

    _configure_mcp(monkeypatch, db_path, "admin")
    with pytest.raises(AuthorizationError) as exc:
        mcp_server.thread_open(title="x", idempotency_key="mcp-deny")
    assert exc.value.code == "authorization_denied"
    assert exc.value.as_dict()["error"] == cli_err["error"]


def test_cli_and_mcp_stop_clear_same_active_false(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, capsys: object
) -> None:
    """CLI raise + MCP user stop_clear share service stop.active=false."""
    code = main(
        [
            "--db",
            str(db_path),
            "stop",
            "--actor",
            "user",
            "--reason",
            "parity freeze",
            "--idempotency-key",
            "parity-raise",
        ]
    )
    assert code == 0
    raised = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert raised["active"] is True

    _configure_mcp(monkeypatch, db_path, "user")
    cleared = mcp_server.stop_clear(reason="parity resume", idempotency_key="parity-clear")
    assert cleared["active"] is False

    code = main(["--db", str(db_path), "stop-status"])
    assert code == 0
    status = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert status["active"] is False


def test_user_mcp_stop_raise_matches_cli_no_cancel_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: object
) -> None:
    """User-bound MCP can raise Stop and preserve queued tasks like CLI --no-cancel-tasks."""
    cli_db = tmp_path / "cli-stop.sqlite3"
    mcp_db = tmp_path / "mcp-stop.sqlite3"
    cli_task = CoordinationService(cli_db).dispatch_task(
        actor="codex",
        title="cli queued",
        goal="remain queued",
        explicit_non_consensus=True,
        idempotency_key="cli-task",
    )["task"]
    mcp_task = CoordinationService(mcp_db).dispatch_task(
        actor="codex",
        title="mcp queued",
        goal="remain queued",
        explicit_non_consensus=True,
        idempotency_key="mcp-task",
    )["task"]

    code = main(
        [
            "--db",
            str(cli_db),
            "stop",
            "--actor",
            "user",
            "--reason",
            "cli preserve",
            "--no-cancel-tasks",
            "--idempotency-key",
            "cli-preserve",
        ]
    )
    assert code == 0
    cli_stop = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    _configure_mcp(monkeypatch, mcp_db, "user")
    mcp_stop = mcp_server.stop_raise(
        reason="mcp preserve",
        cancel_active_tasks=False,
        idempotency_key="mcp-preserve",
    )

    assert cli_stop["active"] is mcp_stop["active"] is True
    assert cli_stop["canceled_tasks"] == mcp_stop["canceled_tasks"] == []
    assert CoordinationService(cli_db).get_task(str(cli_task["task_id"]))["task"]["state"] == "queued"
    assert CoordinationService(mcp_db).get_task(str(mcp_task["task_id"]))["task"]["state"] == "queued"
