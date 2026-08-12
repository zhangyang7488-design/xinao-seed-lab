from __future__ import annotations

import json
import sys
from pathlib import Path

from services.xinao_perpetual_c.controller import (
    PACKET_SCHEMA,
    PerpetualController,
    build_branch_initial_prompt,
    build_codex_arguments,
    build_codex_command,
    build_continuation_prompt,
    build_root_fusion_prompt,
    cleanroom_config_identity,
    parse_event_line,
    parse_lifecycle_state,
)


def test_lifecycle_parser_uses_last_explicit_receipt() -> None:
    text = "XINAO_LINEAGE_STATE: WAIT\nchanged world\nXINAO_LINEAGE_STATE: CONTINUE\n"
    assert parse_lifecycle_state(text) == "CONTINUE"
    assert parse_lifecycle_state("ABSTAIN is not parent completion") is None
    assert parse_lifecycle_state("XINAO_LINEAGE_STATE: invented") is None


def test_prompts_preserve_world_ownership_and_effect_boundary() -> None:
    branch = build_branch_initial_prompt(
        lineage_id="world-01", run_id="run-1", source_head="a" * 40
    )
    continuation = build_continuation_prompt(lineage_id="world-01")
    root = build_root_fusion_prompt(
        run_id="run-1",
        source_head="a" * 40,
        packet_relative_path="S_CONTROL_INPUTS/wave-000001",
        first_turn=True,
    )
    assert "S 不给你研究题" in branch
    assert "直接研究新澳" in branch
    assert "不是一次性报告任务" in branch
    assert "不得把任何结果推送、写回共享主仓" in branch
    assert "只续接生命周期，不给你选题" in continuation
    assert "上一 turn 的结束不关闭父对象" in continuation
    assert "不要按多数票" in root
    assert "S 不形成领域正解" in root
    for prompt in (branch, continuation, root):
        assert "XINAO_LINEAGE_STATE: CONTINUE" in prompt


def test_event_parser_ignores_launcher_banner_and_reads_thread() -> None:
    assert parse_event_line("CODEX C | one shared clean-room runtime") is None
    event = parse_event_line(json.dumps({"type": "thread.started", "thread_id": "abc"}).encode())
    assert event == {"type": "thread.started", "thread_id": "abc"}


def test_config_identity_excludes_only_generated_lineage_trust(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    baseline = (
        'model = "gpt-5.6-sol"\n\n'
        "[projects.'e:\\codex_cleanroom\\workspace']\n"
        'trust_level = "trusted"\n\n'
        "[windows]\n"
        'sandbox = "unelevated"\n'
    )
    dynamic = (
        'model = "gpt-5.6-sol"\n\n'
        "[projects.'e:\\codex_cleanroom\\workspace']\n"
        'trust_level = "trusted"\n\n'
        "[projects.'e:\\codex_cleanroom\\research-lineages\\run\\world-01']\n"
        'trust_level = "trusted"\n\n'
        "[windows]\n"
        'sandbox = "unelevated"\n'
    )
    config.write_text(baseline, encoding="utf-8")
    baseline_identity = cleanroom_config_identity(config)
    config.write_text(dynamic, encoding="utf-8")
    dynamic_identity = cleanroom_config_identity(config)
    assert dynamic_identity["raw_sha256"] != baseline_identity["raw_sha256"]
    assert dynamic_identity["semantic_sha256"] == baseline_identity["semantic_sha256"]
    assert dynamic_identity["dynamic_lineage_project_paths"] == [
        r"e:\codex_cleanroom\research-lineages\run\world-01"
    ]


def test_codex_command_pins_c_slot_workspace_model_and_resume(tmp_path: Path) -> None:
    config = {
        "powershell_path": "powershell.exe",
        "launcher_path": "Open-Codex-Cleanroom.ps1",
        "model": "gpt-5.6-sol",
        "model_reasoning_effort": "max",
    }
    codex_arguments = build_codex_arguments(
        config,
        last_message_path=tmp_path / "last.txt",
        session_id="11111111-1111-1111-1111-111111111111",
    )
    arguments_path = tmp_path / "codex_args.json"
    command = build_codex_command(
        config,
        workspace=tmp_path / "world-01",
        arguments_path=arguments_path,
    )
    assert command[command.index("-AccountSlot") + 1] == "C"
    assert command[command.index("-WorkDir") + 1] == str(tmp_path / "world-01")
    assert command[command.index("-CodexArgsFile") + 1] == str(arguments_path)
    assert codex_arguments[codex_arguments.index("-m") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="max"' in codex_arguments
    assert codex_arguments[codex_arguments.index("exec") + 1] == "resume"
    assert "11111111-1111-1111-1111-111111111111" in codex_arguments
    assert codex_arguments[-1] == "-"


def test_freeze_fusion_packet_copies_exact_candidate_bytes(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    root_workspace = tmp_path / "root"
    root_workspace.mkdir()
    branches = []
    for index in (1, 2):
        workspace = tmp_path / f"world-{index:02d}"
        workspace.mkdir()
        branches.append(
            {
                "lineage_id": f"world-{index:02d}",
                "role": "independent_world",
                "workspace": str(workspace),
            }
        )
    config = {
        "schema": "xinao.cleanroom-c.perpetual-run.v1",
        "run_id": "test-run",
        "run_dir": str(run_dir),
        "source_head": "a" * 40,
        "branch_lineages": branches,
        "root_lineage": {
            "lineage_id": "root-main",
            "role": "late_fusion_root",
            "workspace": str(root_workspace),
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    controller = PerpetualController(config_path)
    for index, spec in enumerate(branches, 1):
        turn_dir = run_dir / "lineages" / spec["lineage_id"] / "turns" / "turn-000001"
        attempt = turn_dir / "attempt-01"
        attempt.mkdir(parents=True)
        payload = f"candidate-{index}\nXINAO_LINEAGE_STATE: CONTINUE\n".encode()
        (attempt / "last_message.txt").write_bytes(payload)
        state = controller._lineage_states[spec["lineage_id"]]
        state.update(
            {
                "turns_completed": 1,
                "last_turn_dir": str(turn_dir),
                "session_id": f"session-{index}",
            }
        )
    controller_module = __import__("services.xinao_perpetual_c.controller", fromlist=["git_output"])
    original_git_output = controller_module.git_output
    controller_module.git_output = lambda *_args, **_kwargs: "a" * 40
    try:
        packet_dir, packet = controller.freeze_fusion_packet(
            {
                "waves_completed": 0,
                "consumed_turns": {"world-01": 0, "world-02": 0},
            }
        )
    finally:
        controller_module.git_output = original_git_output
    assert packet["manifest"]["schema"] == PACKET_SCHEMA
    assert (packet_dir / "CANDIDATE_01.txt").read_bytes().startswith(b"candidate-1")
    assert (packet_dir / "CANDIDATE_02.txt").read_bytes().startswith(b"candidate-2")
    manifest = json.loads((packet_dir / "PACKET_MANIFEST.json").read_text())
    assert manifest["candidate_authority"] is False
    assert manifest["s_content_adjudication"] is False


def test_execute_turn_streams_session_and_accepts_explicit_continue(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    workspace = tmp_path / "world-01"
    root_workspace = tmp_path / "root-main"
    workspace.mkdir()
    root_workspace.mkdir()
    branch = {
        "lineage_id": "world-01",
        "role": "independent_world",
        "workspace": str(workspace),
    }
    config = {
        "schema": "xinao.cleanroom-c.perpetual-run.v1",
        "run_id": "stream-test",
        "run_dir": str(run_dir),
        "source_head": "b" * 40,
        "branch_lineages": [branch],
        "root_lineage": {
            "lineage_id": "root-main",
            "role": "late_fusion_root",
            "workspace": str(root_workspace),
        },
        "powershell_path": "unused",
        "launcher_path": "unused",
        "model": "gpt-5.6-sol",
        "model_reasoning_effort": "max",
        "watchdog_seconds": 30,
        "retry_delays_seconds": [],
        "continuation_delay_seconds": 0,
        "park_poll_seconds": 1,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    controller = PerpetualController(config_path)
    monkeypatch.setattr(controller, "verify_control_body", lambda: None)

    def fake_command(_config, *, workspace, arguments_path):
        del _config, workspace
        code = (
            "import json,pathlib,sys\n"
            "args=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
            "last=pathlib.Path(args[args.index('-o')+1])\n"
            "print(json.dumps({'type':'thread.started','thread_id':'session-live'}),flush=True)\n"
            "print(json.dumps({'type':'turn.started'}),flush=True)\n"
            "last.write_text('world returned\\nXINAO_LINEAGE_STATE: CONTINUE\\n',encoding='utf-8')\n"
            "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':7}}),flush=True)\n"
        )
        return [sys.executable, "-c", code, str(arguments_path)]

    controller_module = __import__(
        "services.xinao_perpetual_c.controller", fromlist=["build_codex_command"]
    )
    monkeypatch.setattr(controller_module, "build_codex_command", fake_command)
    result = controller.execute_turn(spec=branch, prompt="research")
    state = controller._lineage_states["world-01"]
    assert result["outcome"] == "COMPLETED"
    assert result["lifecycle_state"] == "CONTINUE"
    assert state["session_id"] == "session-live"
    assert state["turns_completed"] == 1
    assert state["status"] == "TURN_COMPLETED"
