from __future__ import annotations

import json
from pathlib import Path

import pytest

from xinao_coordination.temporal import grok_parallel

REPO = Path(__file__).resolve().parents[1]


def test_default_temporal_grok_model_is_grok_4_5() -> None:
    assert grok_parallel.DEFAULT_MODEL == "grok-4.5"
    lane = grok_parallel.validate_ready_frontier(
        [{"lane_id": "audit", "prompt": "audit", "cwd": str(REPO)}],
        serial_reason="one indivisible default-model check",
    )[0]
    assert lane["model"] == "grok-4.5"


def test_grok_acpx_disables_terminal_by_internal_tool_id() -> None:
    config = json.loads((REPO / "provisioning" / "acpx-grok-config.json").read_text(encoding="utf-8"))
    args = config["agents"]["grok-build"]["args"]
    runner = (REPO / "provisioning" / "acpx-runtime" / "operation-runner.mjs").read_text(encoding="utf-8")
    disallowed_index = args.index("--disallowed-tools")
    assert args[disallowed_index + 1] == "run_terminal_cmd,run_terminal_command"
    assert "--disallowed-tools run_terminal_cmd,run_terminal_command agent stdio" in runner
    assert "--disallowed-tools Bash" not in runner


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
            "base_intake_path": str(base),
            "lane_results": [
                {
                    "ok": True,
                    "provider_id": grok_parallel.PROVIDER_ID,
                    "lane_id": "research",
                    "mode": "external_research",
                    "model": grok_parallel.DEFAULT_MODEL,
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
                    "operation_id": "op-2",
                    "operation_state": "completed",
                    "result_text": "independent audit result",
                    "artifacts": [{"sha256": "def"}],
                },
            ],
            "require_full_frontier": True,
        }
    )
    assert result["model"] == "grok-4.5"
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["intake"]["container_path"].startswith("/evidence/")
    intake = Path(result["intake"]["artifact_path"]).read_text(encoding="utf-8")
    assert grok_parallel.FANIN_SENTINEL in intake
    assert "mature source result" in intake
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["provider_id"] == grok_parallel.PROVIDER_ID
    assert manifest["model"] == "grok-4.5"
    assert manifest["lanes"][0]["operation_id"] == "op-1"


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
