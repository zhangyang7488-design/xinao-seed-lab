"""G27: CLI/MCP Temporal surface contract.

Locks the public surface only (no service.py edits):
1. temporal_status exists on both CLI and MCP
2. start is promoted-task-only (temporal-start-promoted / temporal_start_promoted)
3. default enabled is false (XINAO_TEMPORAL_ENABLED default 0)
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from xinao_coordination import mcp_server
from xinao_coordination.cli import build_parser, main
from xinao_coordination.errors import ValidationError
from xinao_coordination.service import CoordinationService
from xinao_coordination.temporal.client import reset_mock_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_mcp(monkeypatch: pytest.MonkeyPatch, db_path: Path, role: str) -> None:
    monkeypatch.setenv("XINAO_COORD_DB", str(db_path))
    monkeypatch.setenv("XINAO_COORD_ROLE", role)
    mcp_server.service.cache_clear()


def _cli_json(capsys: object, argv: list[str]) -> tuple[int, dict[str, object]]:
    code = main(argv)
    raw = capsys.readouterr().out  # type: ignore[attr-defined]
    return code, json.loads(raw)


def _dispatch_non_promoted(service: CoordinationService, suffix: str) -> str:
    dispatched = service.dispatch_task(
        actor="codex",
        title=f"g27 non-promoted {suffix}",
        goal="surface contract: must not start temporal",
        explicit_non_consensus=True,
        idempotency_key=f"g27-dispatch-{suffix}",
    )
    task = dispatched["task"]
    assert isinstance(task, dict)
    assert task.get("metadata", {}).get("promoted") is not True
    return str(task["task_id"])


# ---------------------------------------------------------------------------
# 1) temporal_status exists (CLI + MCP surface)
# ---------------------------------------------------------------------------


def test_cli_temporal_status_subcommand_exists() -> None:
    parser = build_parser()
    # argparse stores subparsers on the dest; probe via parse of known command.
    args = parser.parse_args(["temporal-status"])
    assert args.command == "temporal-status"


def test_cli_temporal_start_promoted_subcommand_exists() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "temporal-start-promoted",
            "--actor",
            "codex",
            "--task-id",
            "task_placeholder",
        ]
    )
    assert args.command == "temporal-start-promoted"
    assert args.actor == "codex"
    assert args.task_id == "task_placeholder"
    # Live is env-only; surface must not expose --live.
    assert not hasattr(args, "live")


def test_mcp_temporal_status_tool_exists() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert "temporal_status" in names
    assert "temporal_start_promoted" in names
    assert callable(mcp_server.temporal_status)
    assert callable(mcp_server.temporal_start_promoted)


def test_mcp_temporal_start_promoted_schema_is_promoted_start_only() -> None:
    """MCP mutator: task_id required; actor/worker_id/live not exposed."""
    params = inspect.signature(mcp_server.temporal_start_promoted).parameters
    assert "task_id" in params
    assert "actor" not in params
    assert "worker_id" not in params
    assert "live" not in params

    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {t.name: t for t in tools}
    props = set(by_name["temporal_start_promoted"].inputSchema.get("properties", {}))
    assert "task_id" in props
    assert not (props & {"actor", "worker_id", "live"})
    required = set(by_name["temporal_start_promoted"].inputSchema.get("required") or [])
    assert "task_id" in required


def test_temporal_mcp_schema_snapshots_match_live_surface() -> None:
    """Shipped MCP schema files must include and equal the registered Temporal tools."""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}
    schema_root = Path(__file__).resolve().parents[1] / "mcps" / "xinao-coordination" / "tools"

    for name in ("temporal_status", "temporal_start_promoted"):
        snapshot = json.loads((schema_root / f"{name}.json").read_text(encoding="utf-8"))
        assert snapshot == {
            "name": name,
            "description": by_name[name].description,
            "inputSchema": by_name[name].inputSchema,
        }


# ---------------------------------------------------------------------------
# 2) default enabled false (CLI + MCP status surface)
# ---------------------------------------------------------------------------


def test_cli_temporal_status_default_enabled_false(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, capsys: object
) -> None:
    # Explicit default contract: unset/0 → disabled. Do not inherit ambient ENABLED=1.
    monkeypatch.setenv("XINAO_TEMPORAL_ENABLED", "0")
    monkeypatch.setenv("XINAO_TEMPORAL_MOCK", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_LIVE", "0")
    reset_mock_registry()

    code, payload = _cli_json(capsys, ["--db", str(db_path), "temporal-status"])
    assert code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "disabled"
    assert payload["auto_start_on_promote"] is False
    policy = payload["policy"]
    assert isinstance(policy, dict)
    assert policy["enabled"] is False
    assert policy["promoted_task_only"] is True
    assert policy["auto_start_on_promote"] is False


def test_mcp_temporal_status_default_enabled_false(
    monkeypatch: pytest.MonkeyPatch, db_path: Path
) -> None:
    monkeypatch.setenv("XINAO_TEMPORAL_ENABLED", "0")
    monkeypatch.setenv("XINAO_TEMPORAL_MOCK", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_LIVE", "0")
    reset_mock_registry()
    _configure_mcp(monkeypatch, db_path, "codex")

    st = mcp_server.temporal_status()
    assert st["ok"] is True
    assert st["mode"] == "disabled"
    assert st["auto_start_on_promote"] is False
    policy = st["policy"]
    assert isinstance(policy, dict)
    assert policy["enabled"] is False
    assert policy["promoted_task_only"] is True


def test_pin_defaults_enabled_false() -> None:
    """provisioning pin documents ENABLED default 0 (surface config contract)."""
    pin_path = (
        Path(__file__).resolve().parents[1] / "provisioning" / "temporal_mcp_pin.json"
    )
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    defaults = pin["temporal_env"]["defaults"]
    assert defaults["XINAO_TEMPORAL_ENABLED"] == "0"
    assert defaults["XINAO_TEMPORAL_LIVE"] == "0"
    targets = pin["invoke"]["convenience_targets"]
    assert "temporal-status" in targets
    assert "temporal-start-promoted" in targets


# ---------------------------------------------------------------------------
# 3) start requires promoted (CLI + MCP)
# ---------------------------------------------------------------------------


def test_cli_temporal_start_requires_promoted(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, capsys: object, service: CoordinationService
) -> None:
    monkeypatch.setenv("XINAO_TEMPORAL_ENABLED", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_MOCK", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_LIVE", "0")
    reset_mock_registry()

    task_id = _dispatch_non_promoted(service, "cli")
    code, payload = _cli_json(
        capsys,
        [
            "--db",
            str(db_path),
            "temporal-start-promoted",
            "--actor",
            "codex",
            "--task-id",
            task_id,
            "--idempotency-key",
            "g27-cli-start-non-promoted",
        ],
    )
    assert code == 2
    assert payload["ok"] is False
    assert payload["error"] == "validation_error"
    assert "promoted" in str(payload.get("message", "")).lower()


def test_mcp_temporal_start_requires_promoted(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, service: CoordinationService
) -> None:
    monkeypatch.setenv("XINAO_TEMPORAL_ENABLED", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_MOCK", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_LIVE", "0")
    reset_mock_registry()
    _configure_mcp(monkeypatch, db_path, "codex")

    task_id = _dispatch_non_promoted(service, "mcp")
    with pytest.raises(ValidationError) as excinfo:
        mcp_server.temporal_start_promoted(
            task_id=task_id,
            idempotency_key="g27-mcp-start-non-promoted",
        )
    assert "promoted" in str(excinfo.value).lower()


def test_cli_temporal_start_disabled_when_default_enabled_false(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, capsys: object, service: CoordinationService
) -> None:
    """Even with a task id, default-disabled surface rejects start (invalid_transition)."""
    monkeypatch.setenv("XINAO_TEMPORAL_ENABLED", "0")
    monkeypatch.setenv("XINAO_TEMPORAL_MOCK", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_LIVE", "0")
    reset_mock_registry()

    task_id = _dispatch_non_promoted(service, "cli-off")
    code, payload = _cli_json(
        capsys,
        [
            "--db",
            str(db_path),
            "temporal-start-promoted",
            "--actor",
            "codex",
            "--task-id",
            task_id,
        ],
    )
    assert code == 2
    assert payload["ok"] is False
    assert payload["error"] == "invalid_transition"
