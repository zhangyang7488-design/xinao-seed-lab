from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from xinao_coordination import agent_controller
from xinao_coordination.temporal import grok_parallel

REPO = Path(__file__).resolve().parents[1]


def test_default_temporal_grok_model_is_composer_and_4_5_is_explicit() -> None:
    assert grok_parallel.DEFAULT_MODEL == "grok-composer-2.5-fast"
    lane = grok_parallel.validate_ready_frontier(
        [{"lane_id": "audit", "prompt": "audit", "cwd": str(REPO)}],
        serial_reason="one indivisible default-model check",
    )[0]
    assert lane["model"] == "grok-composer-2.5-fast"
    assert lane["model_route_role"] == grok_parallel.DEFAULT_ROUTE_ROLE
    assert lane["is_escalated"] is False

    escalated = grok_parallel.validate_ready_frontier(
        [
            {
                "lane_id": "research",
                "prompt": "external research",
                "cwd": str(REPO),
                "model": "grok-4.5",
                "escalation_reason": "external_research_required",
            }
        ],
        serial_reason="one explicit external-research unit",
    )[0]
    assert escalated["model"] == "grok-4.5"
    assert escalated["is_escalated"] is True
    assert escalated["escalation_reason"] == "external_research_required"


def test_ready_frontier_rejects_unknown_mixed_or_unisolated_write_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported Grok provider model"):
        grok_parallel.validate_ready_frontier(
            [{"lane_id": "bad", "prompt": "bad", "model": "grok-unknown"}],
            serial_reason="negative model canary",
        )
    with pytest.raises(ValueError, match="cannot mix"):
        grok_parallel.validate_ready_frontier(
            [
                {"lane_id": "one", "prompt": "one"},
                {"lane_id": "two", "prompt": "two", "model": "grok-4.5"},
            ]
        )
    with pytest.raises(ValueError, match="isolated worktree root"):
        grok_parallel.validate_ready_frontier(
            [{"lane_id": "write", "prompt": "write", "cwd": str(tmp_path), "write": True}],
            serial_reason="negative write-scope canary",
        )


def test_model_identity_uses_observed_grok_session_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = (tmp_path / "grok-home").resolve()
    summary = home / "sessions" / "encoded-cwd" / "session-composer" / "summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        json.dumps(
            {
                "current_model_id": grok_parallel.DEFAULT_MODEL,
                "request_id": "request-session",
                "grok_home": str(home),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(grok_parallel, "DEFAULT_EVIDENCE_ROOT", tmp_path / "evidence")
    identity = grok_parallel.materialize_model_identity(
        workflow_id="wf-identity",
        lane_id="lane-identity",
        operation_id="op-identity",
        operation_request_id="request-operation",
        session_id="session-composer",
        requested_model=grok_parallel.DEFAULT_MODEL,
        cwd=str(REPO),
        grok_home=home,
    )
    assert identity["observed_model"] == grok_parallel.DEFAULT_MODEL
    assert identity["model_identity_ok"] is True
    assert identity["raw_conversation_stored"] is False
    assert Path(identity["model_identity_ref"]).is_file()

    mismatch = grok_parallel.materialize_model_identity(
        workflow_id="wf-identity-mismatch",
        lane_id="lane-identity",
        operation_id="op-identity-mismatch",
        operation_request_id="request-operation",
        session_id="session-composer",
        requested_model=grok_parallel.ESCALATION_MODEL,
        cwd=str(REPO),
        grok_home=home,
    )
    assert mismatch["observed_model"] == grok_parallel.DEFAULT_MODEL
    assert mismatch["model_identity_ok"] is False


def test_acpx_transport_launcher_is_derived_from_the_live_project_root() -> None:
    legacy_fragment = "XINAO_RESEARCH_WORKSPACES" + "\\dual-brain-coordination"
    legacy_root = "E:" + "\\" + legacy_fragment
    assert REPO.resolve() == agent_controller.PROJECT_ROOT
    assert (REPO / "provisioning" / "Invoke-XinaoAcpxManaged.ps1").resolve() == agent_controller.ACPX_LAUNCHER
    assert legacy_fragment not in str(agent_controller.ACPX_LAUNCHER)
    provisioner = agent_controller.ACPX_LAUNCHER.read_text(encoding="utf-8-sig")
    assert "Split-Path -Parent $PSScriptRoot" in provisioner
    assert legacy_root not in provisioner


def test_acpx_transport_ensure_passes_the_live_project_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(agent_controller.subprocess, "run", fake_run)
    source = tmp_path / "requirements.source.toml"
    target = tmp_path / "requirements.toml"
    source.write_text(
        '[permission]\nrules = [{ action = "deny", tool = "bash", pattern = "*" }]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        agent_controller,
        "GROK_BACKGROUND_REQUIREMENTS_SOURCE",
        source,
    )
    monkeypatch.setattr(
        agent_controller,
        "GROK_BACKGROUND_REQUIREMENTS_TARGET",
        target,
    )
    agent_controller.AgentOperationController.ensure_transport()
    command = captured["command"]
    assert isinstance(command, list)
    root_index = command.index("-ProjectRoot")
    assert str(REPO.resolve()) == command[root_index + 1]
    assert str(agent_controller.ACPX_LAUNCHER) == command[command.index("-File") + 1]
    assert target.read_bytes() == source.read_bytes()


def test_background_grok_requirements_are_exact_and_atomic(tmp_path: Path) -> None:
    source = REPO / "provisioning" / "grok-background-requirements.v1.toml"
    target = tmp_path / "requirements.toml"
    assert agent_controller.ensure_background_grok_requirements(source, target) is True
    assert agent_controller.ensure_background_grok_requirements(source, target) is False
    assert target.read_bytes() == source.read_bytes()


def test_grok_acpx_uses_background_policy_and_defense_in_depth_shell_deny() -> None:
    config = json.loads((REPO / "provisioning" / "acpx-grok-config.json").read_text(encoding="utf-8"))
    args = config["agents"]["grok-build"]["args"]
    runner = (REPO / "provisioning" / "acpx-runtime" / "operation-runner.mjs").read_text(encoding="utf-8")
    deny_index = args.index("--deny")
    assert args[deny_index + 1] == "Bash(*)"
    disallowed_index = args.index("--disallowed-tools")
    assert args[disallowed_index + 1] == "run_terminal_cmd,run_terminal_command"
    assert '"--deny Bash(*) " +' in runner
    assert "`--tools ${allowedTools}" not in runner
    assert "--disallowed-tools run_terminal_cmd,run_terminal_command agent stdio" in runner
    assert 'const rejectHostExecution = kind === "execute";' in runner
    assert 'const outcome = rejectHostExecution ? "reject_always" : "allow_once";' in runner
    assert "onPermissionRequest: createBackgroundPermissionHandler(" in runner
    assert "permissionSummary," in runner


def test_ready_frontier_uses_input_width_and_requires_serial_reason(tmp_path: Path) -> None:
    raw = [
        {"lane_id": "research", "prompt": "research", "cwd": str(tmp_path)},
        {"lane_id": "audit", "prompt": "audit", "cwd": str(tmp_path)},
        {"lane_id": "test", "prompt": "test", "cwd": str(tmp_path)},
    ]
    lanes = grok_parallel.validate_ready_frontier(raw)
    assert [lane["lane_id"] for lane in lanes] == ["research", "audit", "test"]
    assert len(lanes) == len(raw)

    with pytest.raises(ValueError, match="serial_reason"):
        grok_parallel.validate_ready_frontier([raw[0]])
    assert (
        len(grok_parallel.validate_ready_frontier([raw[0]], serial_reason="one indivisible ready unit")) == 1
    )

    read_lane = grok_parallel.validate_ready_frontier([raw[0]], serial_reason="permission profile check")[0]
    assert read_lane["write"] is False


def test_ready_frontier_rejects_duplicate_or_capacity_overflow(tmp_path: Path) -> None:
    duplicate = [
        {"lane_id": "same", "prompt": "one", "cwd": str(tmp_path)},
        {"lane_id": "same", "prompt": "two", "cwd": str(tmp_path)},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        grok_parallel.validate_ready_frontier(duplicate)

    overflow = [
        {"lane_id": f"lane-{index}", "prompt": "work", "cwd": str(tmp_path)}
        for index in range(grok_parallel.PROVIDER_CAPACITY_CEILING + 1)
    ]
    with pytest.raises(ValueError, match="capacity ceiling"):
        grok_parallel.validate_ready_frontier(overflow)


def test_background_tool_surface_is_fixed_and_caller_can_only_shrink() -> None:
    expected = {
        "grep",
        "list_dir",
        "read_file",
        "search_tool",
        "use_tool",
        "web_fetch",
        "web_search",
    }
    assert expected == grok_parallel.BACKGROUND_ALLOWED_TOOLS
    assert set(grok_parallel.resolve_background_allowed_tools(None)) == expected
    assert grok_parallel.resolve_background_allowed_tools(["read_file", "use_tool"]) == [
        "read_file",
        "use_tool",
    ]
    with pytest.raises(ValueError, match="outside fixed surface"):
        grok_parallel.resolve_background_allowed_tools(["read_file", "search_replace"])


def test_terminal_negative_canary_is_adversarial_and_window_observed() -> None:
    canary = (REPO / "scripts" / "run_grok_background_window_canary.py").read_text(encoding="utf-8")
    runner = (REPO / "scripts" / "run_canonical_grok_transaction.py").read_text(encoding="utf-8")
    assert "negative phase of a bounded host-shell denial canary" in canary
    assert "positive phase of a bounded sandbox-capability canary" in canary
    assert "run_terminal_command exactly once" in canary
    assert "xinao-sandbox__sandbox_execute exactly once" in canary
    assert '"allowed_tools": ["read_file", "search_tool", "use_tool"]' in canary
    assert "observer.abort_event.is_set()" in canary
    assert "task.cancel()" in canary
    assert "new_visible_console_window_count" in canary
    assert 'negative.get("host_terminal_create_count") == 0' in canary
    assert 'negative.get("host_execute_rejection_count") == 1' in canary
    assert "negative_expected_error" in canary
    assert 'sandbox_proof.get("ok") is True' in canary
    assert 'run_dir / "started.json"' in runner
    assert "await handle.cancel(" in runner
    assert "rpc_timeout=rpc_timeout" in runner
    assert 'transaction.transaction_dir / "execution.json"' in runner
    assert '"workflow_terminal_confirmed"' in runner
    assert 'run_dir / "aborted.json"' in runner
    assert "default_model=draft_model(runtime_root=runtime_root)" in runner
    assert 'parser.add_argument("--host-task-queue"' in runner
    assert 'parser.add_argument("--langgraph-task-queue"' in runner
    assert 'parser.add_argument("--worker-deployment-name"' in runner


def test_managed_background_mcp_surface_disables_host_command_tools() -> None:
    import tomllib

    surface = tomllib.loads(
        (REPO / "provisioning" / "grok-background-tool-surface.v1.toml").read_text(encoding="utf-8")
    )
    servers = surface["mcp_servers"]
    assert servers["filesystem"]["enabled"] is False
    assert servers["commander"]["enabled"] is False
    sandbox = servers["xinao-sandbox"]
    assert sandbox["enabled"] is True
    assert sandbox["args"][-2:] == ["-m", "services.mcp.xinao_sandbox_mcp_server"]
    assert "hidden-stdio" in sandbox["command"]


def test_fanin_materializes_container_intake_and_lane_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    base = runtime / "state" / "intake.md"
    base.parent.mkdir(parents=True)
    base.write_text("title\ngoal\n", encoding="utf-8")
    monkeypatch.setattr(grok_parallel, "DEFAULT_RUNTIME", runtime)
    monkeypatch.setattr(
        grok_parallel,
        "DEFAULT_EVIDENCE_ROOT",
        runtime / "state" / "dual_brain_coordination" / "grok_temporal",
    )

    result = grok_parallel._materialize_fanin(
        {
            "workflow_id": "wf-demo",
            "correlation_id": "corr-demo",
            "parent_operation_id": "parent-op-demo",
            "base_intake_path": str(base),
            "lane_results": [
                {
                    "ok": True,
                    "provider_id": grok_parallel.PROVIDER_ID,
                    "lane_id": "research",
                    "mode": "external_research",
                    "model": grok_parallel.DEFAULT_MODEL,
                    "requested_model": grok_parallel.DEFAULT_MODEL,
                    "observed_model": grok_parallel.DEFAULT_MODEL,
                    "model_identity_ok": True,
                    "agent_session_id": "session-research",
                    "model_identity_ref": str(runtime / "identity-research.json"),
                    "model_identity_sha256": "1" * 64,
                    "operation_id": "op-1",
                    "operation_state": "completed",
                    "result_text": "mature source result",
                    "artifacts": [{"sha256": "abc"}],
                },
                {
                    "ok": True,
                    "provider_id": grok_parallel.PROVIDER_ID,
                    "lane_id": "audit",
                    "mode": "audit",
                    "model": grok_parallel.DEFAULT_MODEL,
                    "requested_model": grok_parallel.DEFAULT_MODEL,
                    "observed_model": grok_parallel.DEFAULT_MODEL,
                    "model_identity_ok": True,
                    "agent_session_id": "session-audit",
                    "model_identity_ref": str(runtime / "identity-audit.json"),
                    "model_identity_sha256": "2" * 64,
                    "operation_id": "op-2",
                    "operation_state": "completed",
                    "result_text": "independent audit result",
                    "artifacts": [{"sha256": "def"}],
                },
            ],
            "require_full_frontier": True,
        }
    )
    assert result["model"] == "grok-composer-2.5-fast"
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["intake"]["container_path"].startswith("/evidence/")
    intake = Path(result["intake"]["artifact_path"]).read_text(encoding="utf-8")
    assert grok_parallel.FANIN_SENTINEL in intake
    assert "mature source result" in intake
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["provider_id"] == grok_parallel.PROVIDER_ID
    assert manifest["model"] == "grok-composer-2.5-fast"
    assert manifest["model_identity_ok"] is True
    assert manifest["correlation_id"] == "corr-demo"
    assert manifest["parent_operation_id"] == "parent-op-demo"
    assert manifest["lanes"][0]["operation_id"] == "op-1"
    assert result["correlation_id"] == "corr-demo"
    assert result["parent_operation_id"] == "parent-op-demo"


@pytest.mark.parametrize(
    "bad_lane",
    [
        {
            "ok": False,
            "lane_id": "failed",
            "model": "grok-4.5",
            "operation_id": "op-failed",
            "operation_state": "failed",
            "result_text": "",
        },
        {
            "ok": True,
            "lane_id": "missing-state",
            "model": "grok-4.5",
            "operation_id": "op-missing-state",
            "result_text": "unproven result",
        },
        {
            "ok": True,
            "lane_id": "empty-result",
            "model": "grok-4.5",
            "operation_id": "op-empty-result",
            "operation_state": "completed",
            "result_text": "  ",
        },
    ],
)
def test_fanin_rejects_any_incomplete_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_lane: dict[str, object],
) -> None:
    runtime = tmp_path / "runtime"
    base = runtime / "state" / "intake.md"
    base.parent.mkdir(parents=True)
    base.write_text("base\n", encoding="utf-8")
    monkeypatch.setattr(grok_parallel, "DEFAULT_RUNTIME", runtime)
    monkeypatch.setattr(
        grok_parallel,
        "DEFAULT_EVIDENCE_ROOT",
        runtime / "state" / "dual_brain_coordination" / "grok_temporal",
    )
    valid_lane = {
        "ok": True,
        "provider_id": grok_parallel.PROVIDER_ID,
        "lane_id": "valid",
        "mode": "audit",
        "model": "grok-4.5",
        "requested_model": "grok-4.5",
        "observed_model": "grok-4.5",
        "model_identity_ok": True,
        "agent_session_id": "session-valid",
        "model_identity_ref": str(runtime / "identity-valid.json"),
        "model_identity_sha256": "3" * 64,
        "operation_id": "op-valid",
        "operation_state": "completed",
        "result_text": "verified result",
    }
    bad_lane = {"provider_id": grok_parallel.PROVIDER_ID, **bad_lane}

    with pytest.raises(ValueError, match="all Grok lanes"):
        grok_parallel._materialize_fanin(
            {
                "workflow_id": "wf-reject-incomplete",
                "base_intake_path": str(base),
                "lane_results": [valid_lane, bad_lane],
                "require_full_frontier": True,
            }
        )
    assert not (
        grok_parallel.DEFAULT_EVIDENCE_ROOT / "wf-reject-incomplete" / "fanin" / "manifest.json"
    ).exists()
