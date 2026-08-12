from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from services.xinao_perpetual_world_compute.controller import (
    LEGACY_PACKET_SCHEMA,
    LEGACY_RUN_SCHEMA,
    LEGACY_STOP_SCHEMA,
    PACKET_SCHEMA,
    PARKED_LIFECYCLE_STATES,
    RUN_SCHEMA,
    TURN_SCHEMA,
    WAKE_SCHEMA,
    PerpetualController,
    PerpetualRuntimeError,
    _validate_recovery_pointer,
    build_branch_initial_prompt,
    build_codex_arguments,
    build_codex_command,
    build_continuation_prompt,
    build_parser,
    build_root_fusion_prompt,
    cleanroom_config_identity,
    exclusive_lock,
    parse_event_line,
    parse_lifecycle_state,
    quarantine_incomplete_fusion_packet,
    recover_runtime,
    select_runtime_root,
    sha256_bytes,
    sha256_file,
    stop_runtime,
    validate_account_slot,
    validate_lineage_runtime_repo,
    validate_recovery_account_slot,
    wake_runtime,
)


def make_test_controller(
    tmp_path: Path,
    *,
    run_id: str = "test-run",
    branch_count: int = 2,
    run_schema: str = RUN_SCHEMA,
) -> tuple[PerpetualController, list[dict[str, str]], Path]:
    run_dir = tmp_path / "run"
    root_workspace = tmp_path / "root-main"
    root_workspace.mkdir()
    branches: list[dict[str, str]] = []
    for index in range(1, branch_count + 1):
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
        "schema": run_schema,
        "account_slot": "C",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "source_head": "a" * 40,
        "branch_lineages": branches,
        "root_lineage": {
            "lineage_id": "root-main",
            "role": "late_fusion_root",
            "workspace": str(root_workspace),
        },
        "continuation_delay_seconds": 0,
        "park_poll_seconds": 0,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return PerpetualController(config_path), branches, root_workspace


def write_successful_attempt(
    controller: PerpetualController,
    *,
    lineage_id: str,
    turn_number: int,
    payload: bytes,
    attempt_number: int = 1,
) -> Path:
    turn_dir = controller.lineage_dir(lineage_id) / "turns" / f"turn-{turn_number:06d}"
    attempt_dir = turn_dir / f"attempt-{attempt_number:02d}"
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "last_message.txt").write_bytes(payload)
    (attempt_dir / "receipt.json").write_text(
        json.dumps(
            {
                "schema": controller.schemas["turn"],
                "run_id": controller.config["run_id"],
                "lineage_id": lineage_id,
                "turn_number": turn_number,
                "attempt_number": attempt_number,
                "exit_code": 0,
                "error_class": None,
                "session_id_observed": f"session-{lineage_id}",
                "last_message_sha256": sha256_bytes(payload),
            }
        ),
        encoding="utf-8",
    )
    return turn_dir


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


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
    assert "C clean-room" not in branch
    assert "account slot" not in branch.lower()
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


@pytest.mark.parametrize("account_slot", ["A", "C"])
def test_codex_command_pins_selected_slot_workspace_model_and_resume(
    tmp_path: Path, account_slot: str
) -> None:
    config = {
        "account_slot": account_slot,
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
    assert command[command.index("-AccountSlot") + 1] == account_slot
    assert command[command.index("-WorkDir") + 1] == str(tmp_path / "world-01")
    assert command[command.index("-CodexArgsFile") + 1] == str(arguments_path)
    assert codex_arguments[codex_arguments.index("-m") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="max"' in codex_arguments
    assert codex_arguments[codex_arguments.index("exec") + 1] == "resume"
    assert "11111111-1111-1111-1111-111111111111" in codex_arguments
    assert codex_arguments[-1] == "-"


def test_account_slot_is_a_selector_not_a_controller_mode() -> None:
    assert validate_account_slot("A") == "A"
    assert validate_account_slot("c") == "C"
    with pytest.raises(PerpetualRuntimeError, match="ACCOUNT_SLOT_MUST_BE_A_OR_C"):
        validate_account_slot("B")

    parser = build_parser()
    assert parser.parse_args(["start", "--account-slot", "A"]).account_slot == "A"
    assert parser.parse_args(["start", "--account-slot", "C"]).account_slot == "C"
    with pytest.raises(SystemExit):
        parser.parse_args(["start"])

    assert validate_recovery_account_slot({"account_slot": "A"}, expected="A") == "A"
    assert validate_recovery_account_slot({"account_slot": "C"}, expected=None) == "C"
    with pytest.raises(PerpetualRuntimeError, match="RECOVERY_ACCOUNT_SLOT_MISMATCH"):
        validate_recovery_account_slot({"account_slot": "C"}, expected="A")


def test_runtime_root_falls_back_to_one_legacy_pointer_without_making_it_the_protocol(
    tmp_path: Path,
) -> None:
    generic_root = tmp_path / "perpetual_world_compute"
    legacy_root = tmp_path / "perpetual_c"
    dedicated_a_root = tmp_path / "perpetual_a"
    assert (
        select_runtime_root(
            None,
            require_current=False,
            default_root=generic_root,
            legacy_root=legacy_root,
            dedicated_a_root=dedicated_a_root,
        )
        == generic_root
    )
    legacy_root.mkdir()
    (legacy_root / "current.json").write_text("{}", encoding="utf-8")
    assert (
        select_runtime_root(
            None,
            require_current=True,
            default_root=generic_root,
            legacy_root=legacy_root,
            dedicated_a_root=dedicated_a_root,
        )
        == legacy_root
    )
    generic_root.mkdir()
    (generic_root / "current.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PerpetualRuntimeError, match="MULTIPLE_CURRENT_RUNTIME_POINTERS"):
        select_runtime_root(
            None,
            require_current=True,
            default_root=generic_root,
            legacy_root=legacy_root,
            dedicated_a_root=dedicated_a_root,
        )


def test_runtime_root_discovers_dedicated_a_and_fails_closed_with_live_c(
    tmp_path: Path,
) -> None:
    generic_root = tmp_path / "perpetual_world_compute"
    legacy_c_root = tmp_path / "perpetual_c"
    dedicated_a_root = tmp_path / "perpetual_a"
    dedicated_a_root.mkdir()
    (dedicated_a_root / "current.json").write_text("{}", encoding="utf-8")

    assert (
        select_runtime_root(
            None,
            require_current=True,
            default_root=generic_root,
            legacy_root=legacy_c_root,
            dedicated_a_root=dedicated_a_root,
        )
        == dedicated_a_root
    )

    legacy_c_root.mkdir()
    (legacy_c_root / "current.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PerpetualRuntimeError, match="MULTIPLE_CURRENT_RUNTIME_POINTERS"):
        select_runtime_root(
            None,
            require_current=True,
            default_root=generic_root,
            legacy_root=legacy_c_root,
            dedicated_a_root=dedicated_a_root,
        )


def test_legacy_c_named_schema_is_compatibility_format_not_account_policy(
    tmp_path: Path, monkeypatch
) -> None:
    controller, branches, _ = make_test_controller(
        tmp_path,
        branch_count=1,
        run_schema=LEGACY_RUN_SCHEMA,
    )
    turn_dir = write_successful_attempt(
        controller,
        lineage_id="world-01",
        turn_number=1,
        payload=b"legacy candidate\nXINAO_LINEAGE_STATE: CONTINUE\n",
    )
    controller._lineage_states["world-01"].update(
        {
            "turns_completed": 1,
            "last_turn_dir": str(turn_dir),
            "last_completed_turn_dir": str(turn_dir),
            "session_id": "legacy-session",
        }
    )
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller", fromlist=["git_output"]
    )
    monkeypatch.setattr(controller_module, "git_output", lambda *_args, **_kwargs: "a" * 40)
    packet_dir, packet = controller.freeze_fusion_packet(
        {"waves_completed": 0, "consumed_turns": {"world-01": 0}}
    )
    assert packet_dir.is_dir()
    assert packet["manifest"]["schema"] == LEGACY_PACKET_SCHEMA
    assert controller.config["account_slot"] == "C"


def test_freeze_fusion_packet_uses_completed_receipts_and_is_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    controller, branches, _ = make_test_controller(tmp_path)
    for index, spec in enumerate(branches, 1):
        payload = f"candidate-{index}\nXINAO_LINEAGE_STATE: CONTINUE\n".encode()
        turn_dir = write_successful_attempt(
            controller,
            lineage_id=spec["lineage_id"],
            turn_number=1,
            payload=payload,
        )
        partial_turn = controller.lineage_dir(spec["lineage_id"]) / "turns" / "turn-000002"
        partial_attempt = partial_turn / "attempt-01"
        partial_attempt.mkdir(parents=True)
        (partial_attempt / "last_message.txt").write_text(
            "partial candidate that must never enter fusion", encoding="utf-8"
        )
        state = controller._lineage_states[spec["lineage_id"]]
        state.update(
            {
                "turns_completed": 1,
                "last_turn_dir": str(partial_turn),
                "last_completed_turn_dir": str(turn_dir),
                "session_id": f"session-{index}",
            }
        )
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller", fromlist=["git_output"]
    )
    monkeypatch.setattr(controller_module, "git_output", lambda *_args, **_kwargs: "a" * 40)
    fusion_state = {
        "waves_completed": 0,
        "consumed_turns": {"world-01": 0, "world-02": 0},
    }
    packet_dir, packet = controller.freeze_fusion_packet(fusion_state)
    assert packet["manifest"]["schema"] == PACKET_SCHEMA
    assert (packet_dir / "CANDIDATE_01.txt").read_bytes().startswith(b"candidate-1")
    assert (packet_dir / "CANDIDATE_02.txt").read_bytes().startswith(b"candidate-2")
    assert packet["selected_turns"] == {"world-01": 1, "world-02": 1}
    manifest = json.loads((packet_dir / "PACKET_MANIFEST.json").read_text())
    assert manifest["candidate_authority"] is False
    assert manifest["s_content_adjudication"] is False

    reused_dir, reused = controller.freeze_fusion_packet(fusion_state)
    assert reused_dir == packet_dir
    assert reused["manifest"]["manifest_sha256"] == packet["manifest"]["manifest_sha256"]

    (packet_dir / "CANDIDATE_01.txt").write_text("drift", encoding="utf-8")
    with pytest.raises(PerpetualRuntimeError, match="FUSION_PACKET_CANDIDATE_HASH_MISMATCH"):
        controller.freeze_fusion_packet(fusion_state)


def test_root_wave_does_not_commit_stopped_continuation_and_wait_is_parked(
    tmp_path: Path, monkeypatch
) -> None:
    controller, _, root_workspace = make_test_controller(tmp_path, branch_count=1)
    packet_dir = root_workspace / "S_CONTROL_INPUTS" / "wave-000001"
    packet_dir.mkdir(parents=True)
    results = iter(
        [
            {"outcome": "COMPLETED", "lifecycle_state": "CONTINUE"},
            {"outcome": "STOPPED"},
        ]
    )
    monkeypatch.setattr(
        controller,
        "_execute_root_prompt_with_recovery",
        lambda *_args, **_kwargs: next(results),
    )
    result = controller._run_root_wave("root-main", packet_dir)
    fusion_state = {
        "waves_completed": 0,
        "consumed_turns": {"world-01": 0},
        "pending_packet": {"wave_number": 1},
    }
    before = copy.deepcopy(fusion_state)
    packet = {
        "manifest": {"wave_number": 1, "manifest_sha256": "packet-sha"},
        "selected_turns": {"world-01": 1},
    }
    assert result == {"outcome": "STOPPED"}
    with pytest.raises(PerpetualRuntimeError, match="FUSION_WAVE_CANNOT_COMMIT"):
        controller._finalize_fusion_wave(fusion_state, packet_dir, packet, result)
    assert fusion_state == before
    assert "WAIT" in PARKED_LIFECYCLE_STATES

    controller._finalize_fusion_wave(
        fusion_state,
        packet_dir,
        packet,
        {"outcome": "COMPLETED", "lifecycle_state": "WAIT"},
    )
    assert fusion_state["waves_completed"] == 1
    assert fusion_state["consumed_turns"] == {"world-01": 1}
    assert fusion_state["pending_packet"] is None


def test_recovery_preserves_persisted_branch_wait_without_starting_a_turn(
    tmp_path: Path, monkeypatch
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    state = controller._lineage_states["world-01"]
    state.update(
        {
            "session_id": "session-world-01",
            "turns_completed": 1,
            "lifecycle_state": "WAIT",
            "status": "PARKED_WAIT",
        }
    )
    parked: list[tuple[str, str]] = []

    def fake_wait(lineage_id: str, status: str) -> bool:
        parked.append((lineage_id, status))
        controller._shutdown.set()
        return False

    monkeypatch.setattr(controller, "_wait_parked", fake_wait)
    monkeypatch.setattr(
        controller,
        "execute_turn",
        lambda **_kwargs: pytest.fail("persisted WAIT must not start a new branch turn"),
    )

    controller.branch_loop(branches[0])
    assert parked == [("world-01", "PARKED_WAIT")]


def test_recovery_preserves_persisted_root_pause_without_loading_a_wave(
    tmp_path: Path, monkeypatch
) -> None:
    controller, _, _ = make_test_controller(tmp_path, branch_count=1)
    state = controller._lineage_states["root-main"]
    state.update(
        {
            "session_id": "session-root-main",
            "turns_completed": 1,
            "lifecycle_state": "PAUSE",
            "status": "PARKED_PAUSE",
        }
    )
    parked: list[tuple[str, str]] = []

    def fake_wait(lineage_id: str, status: str) -> bool:
        parked.append((lineage_id, status))
        controller._shutdown.set()
        return False

    monkeypatch.setattr(controller, "_wait_parked", fake_wait)
    monkeypatch.setattr(
        controller,
        "_load_fusion_state",
        lambda: pytest.fail("persisted PAUSE must not load or start another fusion wave"),
    )

    controller.fusion_loop()
    assert parked == [("root-main", "PARKED_PAUSE")]


def test_lineage_runtime_accepts_descendant_commits_but_rejects_remotes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "lineage"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Perpetual C Test")
    git(repo, "config", "user.email", "perpetual-c-test@example.invalid")
    (repo / "candidate.txt").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", "candidate.txt")
    git(repo, "commit", "-m", "baseline")
    baseline = git(repo, "rev-parse", "HEAD")
    (repo / "candidate.txt").write_text("advanced candidate\n", encoding="utf-8")
    git(repo, "commit", "-am", "advance candidate")

    identity = validate_lineage_runtime_repo(repo, baseline)
    assert identity["source_head"] == baseline
    assert identity["head"] != baseline

    git(repo, "remote", "add", "origin", "https://example.invalid/repo.git")
    with pytest.raises(PerpetualRuntimeError, match="LINEAGE_REMOTE_MUST_BE_EMPTY"):
        validate_lineage_runtime_repo(repo, baseline)


def test_recovery_rejects_live_recorded_children_and_clears_dead_ones(
    tmp_path: Path, monkeypatch
) -> None:
    controller, _, _ = make_test_controller(tmp_path, branch_count=1)
    controller._lineage_states["world-01"]["active_pid"] = 12345
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller", fromlist=["is_process_alive"]
    )
    monkeypatch.setattr(controller_module, "is_process_alive", lambda pid: pid == 12345)
    with pytest.raises(PerpetualRuntimeError, match="ORPHAN_CHILDREN_ALIVE_BEFORE_RECOVERY"):
        controller.reject_live_orphaned_children()

    monkeypatch.setattr(controller_module, "is_process_alive", lambda _pid: False)
    controller.reject_live_orphaned_children()
    assert controller._lineage_states["world-01"]["active_pid"] is None
    persisted = json.loads(controller.lineage_state_path("world-01").read_text(encoding="utf-8"))
    assert persisted["active_pid"] is None


def test_quarantine_incomplete_fusion_packet_preserves_partial_directory(tmp_path: Path) -> None:
    controller, _, root_workspace = make_test_controller(tmp_path, branch_count=1)
    partial_packet = root_workspace / "S_CONTROL_INPUTS" / "wave-000001"
    partial_packet.mkdir(parents=True)

    receipt = quarantine_incomplete_fusion_packet(
        controller.config,
        recovery_id="recovery-000001-test",
    )

    assert receipt is not None
    assert receipt["reason"] == "PACKET_MANIFEST_MISSING"
    assert receipt["inventory"] == []
    assert not partial_packet.exists()
    quarantine_path = Path(receipt["quarantine_path"])
    assert quarantine_path.is_dir()
    assert quarantine_path.parent == root_workspace / "S_CONTROL_QUARANTINE"


def test_quarantine_refuses_packet_claimed_by_pending_transaction(tmp_path: Path) -> None:
    controller, _, root_workspace = make_test_controller(tmp_path, branch_count=1)
    partial_packet = root_workspace / "S_CONTROL_INPUTS" / "wave-000001"
    partial_packet.mkdir(parents=True)
    fusion_state_path = controller.lineage_dir("root-main") / "fusion_state.json"
    fusion_state_path.write_text(
        json.dumps(
            {
                "waves_completed": 0,
                "pending_packet": {"wave_number": 1, "packet_dir": str(partial_packet)},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PerpetualRuntimeError, match="INCOMPLETE_PACKET_IS_PENDING_TRANSACTION"):
        quarantine_incomplete_fusion_packet(
            controller.config,
            recovery_id="recovery-000001-test",
        )
    assert partial_packet.is_dir()


def test_exclusive_lock_preserves_body_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="body failure"):
        with exclusive_lock(tmp_path / "controller.lock"):
            raise OSError("body failure")


@pytest.mark.skipif(sys.platform != "win32", reason="recover_runtime is a Windows-only effect")
@pytest.mark.parametrize("run_schema", [RUN_SCHEMA, LEGACY_RUN_SCHEMA])
def test_recover_adopts_repaired_release_without_replacing_lineages(
    tmp_path: Path, monkeypatch, run_schema: str
) -> None:
    runtime_root = tmp_path / "runtime"
    run_dir = runtime_root / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    branch_workspace = tmp_path / "world-01"
    root_workspace = tmp_path / "root-main"
    branch_workspace.mkdir()
    root_workspace.mkdir()
    partial_packet = root_workspace / "S_CONTROL_INPUTS" / "wave-000001"
    partial_packet.mkdir(parents=True)
    old_release = run_dir / "controller_release.py"
    old_release.write_text("# old frozen release\n", encoding="utf-8")
    config = {
        "schema": run_schema,
        "account_slot": "C",
        "run_id": "run-1",
        "run_dir": str(run_dir),
        "source_repo": str(tmp_path / "source"),
        "source_head": "a" * 40,
        "launcher_path": str(tmp_path / "launcher.ps1"),
        "launcher_sha256": "launcher-sha",
        "shared_config_path": str(tmp_path / "config.toml"),
        "shared_config_sha256": "config-sha",
        "controller_release_path": str(old_release),
        "controller_release_sha256": sha256_file(old_release),
        "branch_lineages": [
            {
                "lineage_id": "world-01",
                "role": "independent_world",
                "workspace": str(branch_workspace),
            }
        ],
        "root_lineage": {
            "lineage_id": "root-main",
            "role": "late_fusion_root",
            "workspace": str(root_workspace),
        },
    }
    config_path = run_dir / "run_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    pointer = {
        "schema": run_schema,
        "run_id": "run-1",
        "run_dir": str(run_dir),
        "controller_pid": 111,
        "account_slot": "C",
        "started_at": "before",
    }
    runtime_root.mkdir(exist_ok=True)
    (runtime_root / "current.json").write_text(json.dumps(pointer), encoding="utf-8")
    (run_dir / "controller_state.json").write_text(
        json.dumps({"schema": "controller", "run_id": "run-1", "pid": 111, "status": "FAILED"}),
        encoding="utf-8",
    )

    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller",
        fromlist=["validate_recovery_identity"],
    )
    monkeypatch.setattr(
        controller_module, "validate_recovery_identity", lambda _config: {"ok": True}
    )
    monkeypatch.setattr(controller_module, "find_live_runtime_processes", lambda *_args: {})
    fake_process = SimpleNamespace(pid=4321, poll=lambda: None)
    monkeypatch.setattr(
        controller_module,
        "_spawn_detached_controller",
        lambda **_kwargs: (fake_process, Path(r"C:\runtime\python.exe")),
    )
    monkeypatch.setattr(
        controller_module,
        "_wait_for_controller_startup",
        lambda **_kwargs: {
            "schema": "controller",
            "run_id": "run-1",
            "pid": 4321,
            "status": "RUNNING",
        },
    )

    result = recover_runtime(
        SimpleNamespace(
            runtime_root=runtime_root,
            expected_account_slot="C",
            reason="repair completed-turn fusion race",
            adopt_current_release=True,
            startup_wait_seconds=1,
        )
    )

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["schema"] == run_schema
    assert updated["run_id"] == "run-1"
    assert updated["branch_lineages"] == config["branch_lineages"]
    assert updated["root_lineage"] == config["root_lineage"]
    assert updated["controller_release_path"] != str(old_release)
    assert Path(updated["controller_release_path"]).is_file()
    assert (
        sha256_file(Path(updated["controller_release_path"]))
        == updated["controller_release_sha256"]
    )
    assert old_release.read_text(encoding="utf-8") == "# old frozen release\n"
    assert updated["recovery_generation"] == 1
    assert updated["controller_release_history"][0]["path"] == str(old_release)
    assert result["controller_state"]["status"] == "RUNNING"
    assert result["pointer"]["controller_pid"] == 4321
    assert result["quarantined_incomplete_packet"]["reason"] == "PACKET_MANIFEST_MISSING"
    assert not partial_packet.exists()


def test_recovery_pointer_and_state_slot_mismatch_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    config = {
        "schema": RUN_SCHEMA,
        "account_slot": "C",
        "run_id": "run-1",
        "run_dir": str(run_dir),
    }
    pointer = {
        "run_id": "run-1",
        "run_dir": str(run_dir),
        "account_slot": "A",
    }
    with pytest.raises(PerpetualRuntimeError, match="RECOVERY_POINTER_ACCOUNT_SLOT_MISMATCH"):
        _validate_recovery_pointer(pointer, None, config, run_dir)

    pointer["account_slot"] = "C"
    state = {"run_id": "run-1", "account_slot": "A"}
    with pytest.raises(
        PerpetualRuntimeError, match="RECOVERY_CONTROLLER_STATE_ACCOUNT_SLOT_MISMATCH"
    ):
        _validate_recovery_pointer(pointer, state, config, run_dir)


def test_stop_runtime_fails_closed_when_controller_or_child_survives(
    tmp_path: Path, monkeypatch
) -> None:
    runtime_root = tmp_path / "runtime"
    run_dir = runtime_root / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (runtime_root / "current.json").write_text(
        json.dumps({"run_id": "run-1", "run_dir": str(run_dir), "controller_pid": 111}),
        encoding="utf-8",
    )
    (run_dir / "controller_state.json").write_text(
        json.dumps(
            {
                "schema": "xinao.cleanroom-c.perpetual-controller-state.v1",
                "run_id": "run-1",
                "pid": 111,
                "active_processes": {"world-01": 222},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run_config.json").write_text(
        json.dumps(
            {
                "schema": LEGACY_RUN_SCHEMA,
                "account_slot": "C",
                "run_id": "run-1",
                "run_dir": str(run_dir),
                "branch_lineages": [{"lineage_id": "world-01", "role": "independent_world"}],
                "root_lineage": {"lineage_id": "root-main", "role": "late_fusion_root"},
            }
        ),
        encoding="utf-8",
    )
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller", fromlist=["is_process_alive"]
    )
    monkeypatch.setattr(controller_module, "is_process_alive", lambda pid: pid in {111, 222})
    args = SimpleNamespace(runtime_root=runtime_root, reason="test", wait_seconds=0)
    with pytest.raises(PerpetualRuntimeError, match="STOP_INCOMPLETE_ACTIVE_PROCESSES"):
        stop_runtime(args)
    assert (run_dir / "STOP.json").is_file()
    stop_payload = json.loads((run_dir / "STOP.json").read_text(encoding="utf-8"))
    assert stop_payload["schema"] == LEGACY_STOP_SCHEMA
    assert stop_payload["account_slot"] == "C"
    assert stop_payload["scope"] == "current perpetual world-compute run"


def test_generic_a_wake_receipt_uses_account_neutral_schema(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    run_dir = runtime_root / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    (runtime_root / "current.json").write_text(
        json.dumps({"run_id": "run-a", "run_dir": str(run_dir)}), encoding="utf-8"
    )
    (run_dir / "run_config.json").write_text(
        json.dumps(
            {
                "schema": RUN_SCHEMA,
                "account_slot": "A",
                "run_id": "run-a",
                "run_dir": str(run_dir),
                "branch_lineages": [{"lineage_id": "world-01", "role": "independent_world"}],
                "root_lineage": {"lineage_id": "root-main", "role": "late_fusion_root"},
            }
        ),
        encoding="utf-8",
    )

    wake_runtime(
        SimpleNamespace(runtime_root=runtime_root, lineage_id="world-01", reason="new reality")
    )

    wake_payload = json.loads((run_dir / "wake" / "world-01.json").read_text(encoding="utf-8"))
    assert wake_payload["schema"] == WAKE_SCHEMA
    assert wake_payload["account_slot"] == "A"
    assert "cleanroom-c" not in wake_payload["schema"]


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
        "schema": LEGACY_RUN_SCHEMA,
        "account_slot": "C",
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
        "services.xinao_perpetual_world_compute.controller", fromlist=["build_codex_command"]
    )
    monkeypatch.setattr(controller_module, "build_codex_command", fake_command)
    result = controller.execute_turn(spec=branch, prompt="research")
    state = controller._lineage_states["world-01"]
    assert result["outcome"] == "COMPLETED"
    assert result["lifecycle_state"] == "CONTINUE"
    assert state["session_id"] == "session-live"
    assert state["turns_completed"] == 1
    assert state["status"] == "TURN_COMPLETED"
