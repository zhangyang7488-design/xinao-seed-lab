from __future__ import annotations

import copy
import json
import shutil
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
    _build_attempt_runtime_binding,
    _compile_runtime_binding_views,
    _spawn_detached_controller,
    _turn_requires_runtime_binding,
    _validate_attempt_runtime_binding,
    _validate_existing_runtime_binding_identity,
    _validate_recovery_pointer,
    build_branch_initial_prompt,
    build_codex_arguments,
    build_codex_command,
    build_continuation_prompt,
    build_parser,
    build_root_fusion_prompt,
    build_trajectory_index,
    capture_workspace_artifacts,
    classify_body_incident_events,
    cleanroom_config_identity,
    create_world_isolated_launcher,
    exclusive_lock,
    find_live_runtime_processes,
    inspect_deep_evidence,
    parse_event_line,
    parse_lifecycle_state,
    prepare_reality_migration,
    quarantine_incomplete_fusion_packet,
    read_startup_state,
    reconcile_incomplete_attempts,
    recover_runtime,
    select_runtime_root,
    sha256_bytes,
    sha256_file,
    stop_runtime,
    validate_account_slot,
    validate_lineage_runtime_repo,
    validate_recovery_account_slot,
    wake_runtime,
    world_turn_quota_records_for_run,
)
from services.xinao_perpetual_world_compute.reality_migration import (
    migrate_live_reality_copy_first,
)
from services.xinao_perpetual_world_compute.runtime_binding import (
    build_world_runtime_binding_applied_receipt,
    world_runtime_binding_file_sha256,
)
from services.xinao_perpetual_world_compute.runtime_binding import (
    canonical_json_bytes as binding_json_bytes,
)


def test_read_startup_state_treats_windows_replace_access_denied_as_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "controller_state.json"
    calls = 0
    path_type = state_path.__class__
    original_read_text = path_type.read_text

    def flaky_read_text(self: Path, *args: object, **kwargs: object) -> str:
        nonlocal calls
        if self == state_path:
            calls += 1
            if calls == 1:
                raise PermissionError(13, "Permission denied", str(state_path))
            return json.dumps({"run_id": "run-1", "status": "RUNNING"})
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(path_type, "read_text", flaky_read_text)

    assert read_startup_state(state_path) is None
    assert read_startup_state(state_path) == {"run_id": "run-1", "status": "RUNNING"}


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


def attach_deep_evidence(controller: PerpetualController, attempt_dir: Path) -> str:
    raw_event = (
        json.dumps({"type": "turn.started"})
        + "\n"
        + json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item-1", "type": "agent_message", "text": "deep relation"},
            }
        )
        + "\n"
        + json.dumps({"type": "turn.completed", "usage": {"input_tokens": 7}})
        + "\n"
    ).encode("utf-8")
    stdout_path = attempt_dir / "exec_stdout.jsonl"
    stdout_path.write_bytes(raw_event)
    trajectory = build_trajectory_index(stdout_path, attempt_dir / "trajectory_index.jsonl")

    artifact_raw = b"branch artifact with exact bytes\n"
    artifact_sha = sha256_bytes(artifact_raw)
    blob_root = controller.run_dir / "deep-evidence" / "blobs" / "sha256"
    blob_path = blob_root / artifact_sha[:2] / artifact_sha
    blob_path.parent.mkdir(parents=True)
    blob_path.write_bytes(artifact_raw)
    artifact_manifest_path = attempt_dir / "artifact_manifest.json"
    artifact_manifest_path.write_text(
        json.dumps(
            {
                "schema": "xinao.cleanroom.world-compute-artifact-manifest.v1",
                "run_id": controller.config["run_id"],
                "lineage_id": attempt_dir.parents[2].name,
                "turn_number": int(attempt_dir.parent.name.removeprefix("turn-")),
                "attempt_number": int(attempt_dir.name.removeprefix("attempt-")),
                "source_workspace": str(
                    Path(
                        next(
                            item["workspace"]
                            for item in [
                                *controller.config["branch_lineages"],
                                controller.config["root_lineage"],
                            ]
                            if item["lineage_id"] == attempt_dir.parents[2].name
                        )
                    ).resolve()
                ),
                "source_head": controller.config["source_head"],
                "content_addressed_blob_root": str(blob_root),
                "complete": True,
                "safety_block_count": 0,
                "entries": [
                    {
                        "relative_path": "xinao/candidates/deep.txt",
                        "source_class": "UNTRACKED",
                        "state": "PRESENT",
                        "bytes": len(artifact_raw),
                        "sha256": artifact_sha,
                        "blob_path": str(blob_path),
                    }
                ],
                "exclusions": [],
                "gaps": [],
            }
        ),
        encoding="utf-8",
    )
    receipt_path = attempt_dir / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["stdout_sha256"] = sha256_file(stdout_path)
    receipt["deep_evidence"] = {
        "status": "AVAILABLE",
        "trajectory": trajectory,
        "artifacts": {
            "path": str(artifact_manifest_path),
            "sha256": sha256_file(artifact_manifest_path),
            "entry_count": 1,
            "exclusion_count": 0,
            "gap_count": 0,
            "safety_block_count": 0,
            "complete": True,
            "blob_root": str(blob_root),
        },
        "errors": [],
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return artifact_sha


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


def test_codex_command_carries_complete_runtime_binding_invocation(tmp_path: Path) -> None:
    config = {
        "account_slot": "A",
        "powershell_path": "powershell.exe",
        "launcher_path": "world-isolated.ps1",
    }
    binding = tmp_path / "runtime_binding.json"
    applied = tmp_path / "binding-applied.json"
    args_path = tmp_path / "codex_args.json"
    command = build_codex_command(
        config,
        workspace=tmp_path / "world-01",
        arguments_path=args_path,
        runtime_binding_path=binding,
        runtime_binding_sha256="a" * 64,
        runtime_binding_applied_path=applied,
        runtime_binding_invocation_nonce="b" * 32,
    )
    assert command[command.index("-WorldRuntimeBindingFile") + 1] == str(binding)
    assert command[command.index("-ExpectedWorldRuntimeBindingSha256") + 1] == "a" * 64
    assert command[command.index("-WorldRuntimeAppliedReceiptFile") + 1] == str(applied)
    assert command[command.index("-WorldRuntimeInvocationNonce") + 1] == "b" * 32
    with pytest.raises(
        PerpetualRuntimeError,
        match="WORLD_RUNTIME_BINDING_COMMAND_ARGUMENTS_INCOMPLETE",
    ):
        build_codex_command(
            config,
            workspace=tmp_path / "world-01",
            arguments_path=args_path,
            runtime_binding_path=binding,
        )


def test_controller_builds_and_revalidates_exact_attempt_runtime_binding(
    tmp_path: Path,
) -> None:
    run_id = "run-001"
    run_dir = tmp_path / "control" / "runs" / run_id
    workspace = tmp_path / "research-lineages" / run_id / "world-01"
    canonical = tmp_path / "canonical"
    (canonical / "xinao" / "reality" / "live").mkdir(parents=True)
    (canonical / "xinao" / "reality" / "live" / "seed.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    workspace.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    migration = migrate_live_reality_copy_first(
        canonical,
        live_reality_root=tmp_path / "runtime" / "live-reality",
        world_compute_root=tmp_path / "runtime" / "world-compute" / run_id,
        workspace_roots={"world-01": workspace},
    )
    launcher = run_dir / "world-isolated.ps1"
    launcher.write_text("# frozen launcher\n", encoding="utf-8")
    release = run_dir / "controller.py"
    release.write_text("# frozen controller\n", encoding="utf-8")
    binding_source = Path(
        __import__(
            "services.xinao_perpetual_world_compute.runtime_binding",
            fromlist=["__file__"],
        ).__file__
    )
    binding_release = run_dir / "runtime_binding.py"
    binding_release.write_bytes(binding_source.read_bytes())
    config: dict[str, object] = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "account_slot": "A",
        "source_head": "a" * 40,
        "launcher_path": str(launcher),
        "launcher_sha256": sha256_file(launcher),
        "controller_release_path": str(release),
        "controller_release_sha256": sha256_file(release),
        "controller_python": str(Path(sys.executable).resolve()),
        "controller_python_sha256": sha256_file(Path(sys.executable).resolve()),
        "runtime_binding_release_path": str(binding_release),
        "runtime_binding_release_sha256": sha256_file(binding_release),
        "reality_migration_manifest_path": migration["manifest_path"],
        "reality_migration_manifest_sha256": migration["manifest_sha256"],
        "reality_migration_id": migration["migration_id"],
        "branch_lineages": [
            {
                "lineage_id": "world-01",
                "role": "independent_world",
                "workspace": str(workspace),
            }
        ],
        "root_lineage": {
            "lineage_id": "world-01",
            "role": "independent_world",
            "workspace": str(workspace),
        },
        "runtime_binding_required": True,
        "runtime_binding_required_from_turn": {"world-01": 1},
    }
    compiled = _compile_runtime_binding_views(
        config=config,
        manifest_path=Path(str(migration["manifest_path"])),
    )
    config["runtime_binding_views"] = compiled["views"]
    attempt_dir = run_dir / "lineages" / "world-01" / "turns" / "turn-000001" / "attempt-01"
    attempt_dir.mkdir(parents=True)
    codex_args_path = attempt_dir / "codex_args.json"
    codex_args_path.write_bytes(
        binding_json_bytes(
            [
                "exec",
                "--strict-config",
                "--json",
                "-m",
                "gpt-5.6-sol",
                "-",
            ]
        )
    )
    lineage = config["branch_lineages"][0]  # type: ignore[index]
    binding, raw, binding_file_sha = _build_attempt_runtime_binding(
        config=config,
        spec=lineage,  # type: ignore[arg-type]
        attempt_dir=attempt_dir,
        turn_number=1,
        attempt_number=1,
        codex_args_path=codex_args_path,
    )
    assert (attempt_dir / "runtime_binding.json").read_bytes() == raw
    assert binding_file_sha == world_runtime_binding_file_sha256(binding)
    applied = build_world_runtime_binding_applied_receipt(
        binding=binding,
        binding_file_sha256=binding_file_sha,
        observed_environment=binding["environment"],
        launcher_pid=4242,
    )
    (attempt_dir / "binding-applied.json").write_bytes(binding_json_bytes(applied))
    reference = _validate_attempt_runtime_binding(
        config=config,
        spec=lineage,  # type: ignore[arg-type]
        attempt_dir=attempt_dir,
        turn_number=1,
        attempt_number=1,
        receipt=None,
    )
    assert reference["status"] == "AVAILABLE"
    _validate_attempt_runtime_binding(
        config=config,
        spec=lineage,  # type: ignore[arg-type]
        attempt_dir=attempt_dir,
        turn_number=1,
        attempt_number=1,
        receipt={"runtime_binding": reference},
    )
    assert _turn_requires_runtime_binding(config, lineage_id="world-01", turn_number=1)
    effective_code_file = Path(str(binding["effective_code_root"])) / "code" / "unexpected.py"
    effective_code_file.write_text("UNEXPECTED = True\n", encoding="utf-8")
    with pytest.raises(
        PerpetualRuntimeError,
        match="WORLD_RUNTIME_BINDING_APPLIED_EVIDENCE_INVALID:EFFECTIVE_CODE_TREE_SET_MISMATCH",
    ):
        _validate_attempt_runtime_binding(
            config=config,
            spec=lineage,  # type: ignore[arg-type]
            attempt_dir=attempt_dir,
            turn_number=1,
            attempt_number=1,
            receipt=None,
        )
    effective_code_file.unlink()
    (attempt_dir / "binding-applied.json").unlink()
    with pytest.raises(
        PerpetualRuntimeError,
        match="WORLD_RUNTIME_BINDING_APPLIED_EVIDENCE_MISSING",
    ):
        _validate_attempt_runtime_binding(
            config=config,
            spec=lineage,  # type: ignore[arg-type]
            attempt_dir=attempt_dir,
            turn_number=1,
            attempt_number=1,
            receipt=None,
        )


def test_existing_migration_recovery_ignores_legacy_source_drift_but_rechecks_targets(
    tmp_path: Path,
) -> None:
    run_id = "run-001"
    workspace = tmp_path / "research-lineages" / run_id / "world-01"
    canonical_live = tmp_path / "canonical" / "xinao" / "reality" / "live"
    workspace_live = workspace / "xinao" / "reality" / "live"
    canonical_live.mkdir(parents=True)
    workspace_live.mkdir(parents=True)
    (canonical_live / "seed.py").write_text("VALUE = 1\n", encoding="utf-8")
    (workspace_live / "seed.py").write_text("VALUE = 2\n", encoding="utf-8")
    migration = migrate_live_reality_copy_first(
        tmp_path / "canonical",
        live_reality_root=tmp_path / "runtime" / "live-reality",
        world_compute_root=tmp_path / "runtime" / "world-compute" / run_id,
        workspace_roots={"world-01": workspace},
    )
    config = {
        "run_id": run_id,
        "branch_lineages": [
            {
                "lineage_id": "world-01",
                "role": "independent_world",
                "workspace": str(workspace),
            }
        ],
        "root_lineage": {
            "lineage_id": "world-01",
            "role": "independent_world",
            "workspace": str(workspace),
        },
    }
    (canonical_live / "seed.py").write_text("VALUE = 3\n", encoding="utf-8")
    (workspace_live / "seed.py").write_text("VALUE = 4\n", encoding="utf-8")
    compiled = _compile_runtime_binding_views(
        config=config,
        manifest_path=Path(str(migration["manifest_path"])),
        verify_sources=False,
    )
    assert set(compiled["views"]) == {"world-01"}
    frozen_config = {
        **config,
        "runtime_binding_required": True,
        "reality_migration_manifest_path": compiled["manifest_path"],
        "reality_migration_manifest_sha256": compiled["manifest_sha256"],
        "reality_migration_id": compiled["migration_id"],
        "runtime_binding_views": compiled["views"],
    }
    assert _validate_existing_runtime_binding_identity(frozen_config) == compiled
    manifest_path = Path(str(migration["manifest_path"]))
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
    with pytest.raises(
        PerpetualRuntimeError,
        match="REALITY_MIGRATION_FROZEN_IDENTITY_DRIFT",
    ):
        _validate_existing_runtime_binding_identity(frozen_config)
    manifest_path.write_bytes(manifest_path.read_bytes().rstrip(b"\n"))
    with pytest.raises(PerpetualRuntimeError, match="REALITY_MIGRATION_READBACK_FAILED"):
        _compile_runtime_binding_views(
            config=config,
            manifest_path=Path(str(migration["manifest_path"])),
            verify_sources=True,
        )


def test_detached_controller_spawn_uses_and_rechecks_bound_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller_python = tmp_path / "bound-python.exe"
    controller_python.write_bytes(b"bound-python-v1\n")
    release = tmp_path / "controller_release.py"
    release.write_text("# frozen\n", encoding="utf-8")
    config = tmp_path / "run_config.json"
    config.write_text("{}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 1234

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller",
        fromlist=["subprocess"],
    )
    monkeypatch.setattr(controller_module.subprocess, "Popen", fake_popen)
    process, observed = _spawn_detached_controller(
        controller_python=controller_python,
        controller_python_sha256=sha256_file(controller_python),
        release_path=release,
        config_path=config,
        run_dir=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )
    assert process.pid == 1234
    assert observed == controller_python.resolve()
    assert captured["command"][0] == str(controller_python.resolve())  # type: ignore[index]

    controller_python.write_bytes(b"replacement-python\n")
    with pytest.raises(
        PerpetualRuntimeError,
        match="WORLD_BODY_CONTROLLER_PYTHON_CHANGED_BEFORE_SPAWN",
    ):
        _spawn_detached_controller(
            controller_python=controller_python,
            controller_python_sha256=sha256_file(controller_python)[:-1] + "0",
            release_path=release,
            config_path=config,
            run_dir=tmp_path,
            stdout_path=tmp_path / "stdout-2.log",
            stderr_path=tmp_path / "stderr-2.log",
        )


def test_world_launcher_enforces_workspace_write_without_changing_shared_launcher(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Open-Codex-Cleanroom.ps1"
    original = (
        b"before\r\n"
        b"& $codexExe --cd $launchWorkdir --dangerously-bypass-approvals-and-sandbox "
        b"@slotSpecificCodexArgs @CodexArgs\r\n"
        b"after\r\n"
    )
    source.write_bytes(original)
    destination = tmp_path / "run" / "Open-Codex-World-Isolated.ps1"

    receipt = create_world_isolated_launcher(source, destination)

    assert source.read_bytes() == original
    isolated = destination.read_text(encoding="utf-8")
    assert "--sandbox workspace-write" in isolated
    assert "sandbox_workspace_write.network_access=true" in isolated
    assert "--dangerously-bypass-approvals-and-sandbox" not in isolated
    assert receipt["writable_scope"] == "lineage_workspace_only"
    assert receipt["additional_writable_roots"] == []


def test_frozen_world_launcher_does_not_depend_on_later_source_launcher_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Open-Codex-Cleanroom.ps1"
    source.write_bytes(
        b"& $codexExe --cd $launchWorkdir --dangerously-bypass-approvals-and-sandbox "
        b"@slotSpecificCodexArgs @CodexArgs\n"
    )
    run_dir = tmp_path / "run"
    destination = run_dir / "Open-Codex-World-Isolated.ps1"
    receipt = create_world_isolated_launcher(source, destination)
    config = {
        "run_dir": str(run_dir),
        "launcher_path": str(destination),
        "launcher_source_path": str(source),
        "launcher_source_sha256": receipt["source_sha256"],
        "body_boundary": {
            "schema": "xinao.cleanroom.world-isolated-launcher.v1",
            "sandbox_mode": "workspace-write",
            "approval_policy": "never",
            "network_access": True,
            "writable_scope": "current_lineage_workspace_only",
            "additional_writable_roots": [],
            "s_repo_writable": False,
            "cleanroom_shared_body_writable": False,
            "account_config_writable": False,
            "body_incident_schema": "xinao.cleanroom.world-compute-body-incident.v1",
        },
    }
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller",
        fromlist=["validate_body_boundary_config"],
    )

    source.write_text("# later shared launcher release\n", encoding="utf-8")
    assert controller_module.validate_body_boundary_config(config) is not None
    destination.write_text("# drifted frozen launcher\n", encoding="utf-8")
    with pytest.raises(PerpetualRuntimeError, match="WORLD_BODY_LAUNCHER_SEMANTICS_INVALID"):
        controller_module.validate_body_boundary_config(config)


def test_live_cleanroom_launcher_freezes_to_valid_world_isolated_powershell(
    tmp_path: Path,
) -> None:
    source = Path(r"E:\CODEX_CLEANROOM\Open-Codex-Cleanroom.ps1")
    powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    if not source.is_file() or not powershell.is_file():
        pytest.skip("live Windows clean-room launcher is not present")
    destination = tmp_path / "Open-Codex-World-Isolated.ps1"
    create_world_isolated_launcher(source, destination)
    quoted_destination = str(destination).replace("'", "''")
    parser_command = (
        "$t=$null;$e=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{quoted_destination}',[ref]$t,[ref]$e)|Out-Null;"
        "if($e.Count){$e|% Message;exit 1}"
    )
    parse = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            parser_command,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert parse.returncode == 0, parse.stdout + parse.stderr


def test_live_cleanroom_launcher_freezes_mandatory_runtime_binding_surface(
    tmp_path: Path,
) -> None:
    source = Path(r"E:\CODEX_CLEANROOM\Open-Codex-Cleanroom.ps1")
    powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    if not source.is_file() or not powershell.is_file():
        pytest.skip("live Windows clean-room launcher is not present")
    destination = tmp_path / "Open-Codex-World-Bound.ps1"
    receipt = create_world_isolated_launcher(
        source,
        destination,
        require_runtime_binding=True,
    )
    raw = destination.read_bytes()
    assert receipt["runtime_binding_required"] is True
    assert b"$worldRuntimeBindingMandatory = $true" in raw
    assert b"WORLD_RUNTIME_BINDING_ENVIRONMENT_PROJECTION_MISMATCH" in raw
    quoted_destination = str(destination).replace("'", "''")
    parser_command = (
        "$t=$null;$e=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{quoted_destination}',[ref]$t,[ref]$e)|Out-Null;"
        "if($e.Count){$e|% Message;exit 1}"
    )
    parse = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            parser_command,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert parse.returncode == 0, parse.stdout + parse.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Codex Windows sandbox probe")
def test_pinned_cleanroom_codex_sandbox_allows_lineage_and_denies_shared_bodies(
    tmp_path: Path,
) -> None:
    codex = Path(
        r"E:\CODEX_CLEANROOM\runtime\codex-package\node_modules\@openai"
        r"\codex-win32-x64\vendor\x86_64-pc-windows-msvc\bin\codex.exe"
    )
    powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    if not codex.is_file() or not powershell.is_file():
        pytest.skip("Pinned clean-room Codex or Windows PowerShell is unavailable")
    workspace = tmp_path / "world-01"
    protected = tmp_path / "shared-body"
    workspace.mkdir()
    protected.mkdir()
    inside = workspace / "inside.txt"
    outside = protected / "outside.txt"

    def sandbox_write(target: Path) -> subprocess.CompletedProcess[str]:
        literal = str(target).replace("'", "''")
        return subprocess.run(
            [
                str(codex),
                "sandbox",
                "-P",
                ":workspace",
                "-C",
                str(workspace),
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Set-Content -LiteralPath '{literal}' -Value ok -NoNewline",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

    inside_result = sandbox_write(inside)
    outside_result = sandbox_write(outside)

    assert inside_result.returncode == 0, inside_result.stdout + inside_result.stderr
    assert inside.read_text(encoding="utf-8") == "ok"
    assert outside_result.returncode != 0
    assert not outside.exists()

    live_protected_roots = [
        Path(r"E:\CODEX_CLEANROOM\workspace"),
        Path(r"E:\XINAO_RESEARCH_WORKSPACES\S"),
        Path(r"E:\CODEX_CLEANROOM\codex-home"),
        Path(r"E:\CODEX_CLEANROOM\research-lineages"),
    ]
    probe_name = f".codex-world-body-probe-{tmp_path.name}.txt"
    for protected_root in live_protected_roots:
        if not protected_root.is_dir():
            continue
        target = protected_root / probe_name
        target.unlink(missing_ok=True)
        try:
            denied = sandbox_write(target)
            assert denied.returncode != 0
            assert not target.exists()
        finally:
            target.unlink(missing_ok=True)


def test_body_incident_classification_keeps_only_hash_bound_failure_metadata(
    tmp_path: Path,
) -> None:
    stdout_path = tmp_path / "exec_stdout.jsonl"
    workspace = tmp_path / "world-01"
    workspace.mkdir()
    protected = tmp_path / "protected-body.txt"
    inside = workspace / "inside.txt"
    rows = [
        {
            "type": "item.completed",
            "item": {
                "id": "read-failure",
                "type": "command_execution",
                "status": "failed",
                "exit_code": 1,
                "command": "read unrelated",
                "aggregated_output": "ordinary assertion failure",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "inside-failure",
                "type": "command_execution",
                "status": "failed",
                "exit_code": 1,
                "aggregated_output": f"Permission denied: {inside}",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "network-failure",
                "type": "command_execution",
                "status": "failed",
                "exit_code": 1,
                "aggregated_output": "database access denied by remote service",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "boundary-failure",
                "type": "command_execution",
                "status": "failed",
                "exit_code": 1,
                "command": "write protected body",
                "aggregated_output": f"Access is denied: {protected}",
            },
        },
    ]
    stdout_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    incidents = classify_body_incident_events(stdout_path, workspace=workspace)

    assert incidents == [
        {
            "event_sequence": 4,
            "item_id": "boundary-failure",
            "tool": "command_execution",
            "failure_class": "WRITE_DOMAIN_DENIED",
            "exit_code": 1,
            "matched_rule": "access is denied",
            "denied_target_scope": "OUTSIDE_LINEAGE_WORKSPACE",
            "denied_target_path_sha256": sha256_bytes(
                str(protected.resolve()).lower().encode("utf-8")
            ),
            "event_line_sha256": incidents[0]["event_line_sha256"],
        }
    ]
    assert "command" not in incidents[0]
    assert "aggregated_output" not in incidents[0]

    marker_only = {
        "type": "item.completed",
        "item": {
            "id": "prose-only",
            "type": "command_execution",
            "status": "failed",
            "exit_code": 1,
            "aggregated_output": "ordinary test says outside the workspace",
        },
    }
    stdout_path.write_text(json.dumps(marker_only) + "\n", encoding="utf-8")
    assert classify_body_incident_events(stdout_path, workspace=workspace) == []


def test_completed_turn_with_boundary_denial_is_parked_as_body_incident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    controller.config["body_boundary"] = {
        "sandbox_mode": "workspace-write",
        "approval_policy": "never",
        "additional_writable_roots": [],
    }
    controller.config["retry_delays_seconds"] = []
    controller.config["powershell_path"] = "unused"
    controller.config["launcher_path"] = "unused"
    controller.config["model"] = "gpt-5.6-sol"
    controller.config["model_reasoning_effort"] = "max"
    controller.config["watchdog_seconds"] = 30
    monkeypatch.setattr(controller, "verify_control_body", lambda: None)

    def fake_command(_config, *, workspace, arguments_path):
        del _config
        protected = Path(workspace).parent / "protected-body.txt"
        boundary_output = "Access is denied: " + str(protected)
        code = (
            "import json,pathlib,sys\n"
            "args=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
            "last=pathlib.Path(args[args.index('-o')+1])\n"
            "print(json.dumps({'type':'thread.started','thread_id':'session-body'}),flush=True)\n"
            "print(json.dumps({'type':'turn.started'}),flush=True)\n"
            "event={'type':'item.completed','item':{'id':'cmd-1',"
            "'type':'command_execution','status':'failed','exit_code':1,"
            + f"'aggregated_output':{boundary_output!r}}}}}\n"
            + "print(json.dumps(event),flush=True)\n"
            "last.write_text('do not adopt\\nXINAO_LINEAGE_STATE: CONTINUE\\n',encoding='utf-8')\n"
            "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':7}}),flush=True)\n"
        )
        return [sys.executable, "-c", code, str(arguments_path)]

    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller", fromlist=["build_codex_command"]
    )
    monkeypatch.setattr(controller_module, "build_codex_command", fake_command)

    result = controller.execute_turn(spec=branches[0], prompt="research")

    assert result["outcome"] == "FAILED"
    assert result["error_class"] == "BODY_INCIDENT"
    receipt = result["receipt"]
    assert receipt["body_incident"]["evidence_adoptable"] is False
    assert controller._lineage_states["world-01"]["status"] == "BODY_INCIDENT"
    assert controller._lineage_states["world-01"]["turns_completed"] == 0
    assert (result["attempt_dir"] / "body_incident.json").is_file()


@pytest.mark.parametrize(
    ("failure_mode", "expected_status"),
    [
        ("trajectory_failure", "PARTIAL"),
        ("artifact_gap", "PARTIAL"),
        ("both_failure", "UNAVAILABLE"),
    ],
)
def test_required_deep_evidence_failure_cannot_complete_or_enter_fusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    expected_status: str,
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    controller.config.update(
        {
            "deep_evidence_required": True,
            "retry_delays_seconds": [],
            "powershell_path": "unused",
            "launcher_path": "unused",
            "model": "gpt-5.6-sol",
            "model_reasoning_effort": "max",
            "watchdog_seconds": 30,
        }
    )
    monkeypatch.setattr(controller, "verify_control_body", lambda: None)

    def fake_command(_config, *, workspace, arguments_path):
        del _config, workspace
        code = (
            "import json,pathlib,sys\n"
            "args=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
            "last=pathlib.Path(args[args.index('-o')+1])\n"
            "print(json.dumps({'type':'thread.started','thread_id':'session-evidence'}),flush=True)\n"
            "last.write_text('candidate\\nXINAO_LINEAGE_STATE: CONTINUE\\n',encoding='utf-8')\n"
            "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':7}}),flush=True)\n"
        )
        return [sys.executable, "-c", code, str(arguments_path)]

    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller",
        fromlist=["build_codex_command"],
    )
    monkeypatch.setattr(controller_module, "build_codex_command", fake_command)

    if failure_mode in {"trajectory_failure", "both_failure"}:
        monkeypatch.setattr(
            controller_module,
            "build_trajectory_index",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                PerpetualRuntimeError("trajectory failed")
            ),
        )
    else:
        monkeypatch.setattr(
            controller_module,
            "build_trajectory_index",
            lambda *_args, **_kwargs: {"path": "trajectory", "sha256": "a" * 64},
        )
    if failure_mode == "both_failure":
        monkeypatch.setattr(
            controller_module,
            "capture_workspace_artifacts",
            lambda **_kwargs: (_ for _ in ()).throw(PerpetualRuntimeError("artifacts failed")),
        )
    else:
        monkeypatch.setattr(
            controller_module,
            "capture_workspace_artifacts",
            lambda **_kwargs: {
                "path": "artifacts",
                "sha256": "b" * 64,
                "complete": failure_mode != "artifact_gap",
            },
        )

    result = controller.execute_turn(spec=branches[0], prompt="research")

    assert result["outcome"] == "FAILED"
    assert result["error_class"] == "EVIDENCE_INCIDENT"
    assert result["receipt"]["deep_evidence"]["status"] == expected_status
    assert controller._lineage_states["world-01"]["turns_completed"] == 0
    assert controller._lineage_states["world-01"]["status"] == "EVIDENCE_INCIDENT"
    with pytest.raises(PerpetualRuntimeError, match="FUSION_SOURCE_HAS_NO_COMPLETED_TURN"):
        controller._completed_turn_candidate("world-01", controller._lineage_states["world-01"])


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

    parsed = parser.parse_args(
        [
            "recover",
            "--runtime-root",
            str(Path("runtime")),
            "--adopt-current-release",
            "--reality-migration-manifest",
            str(Path("MANIFEST.json")),
        ]
    )
    assert parsed.adopt_current_release is True
    assert parsed.reality_migration_manifest == Path("MANIFEST.json")


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


def test_recovery_evidence_boundary_preserves_legacy_unconsumed_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _, _ = make_test_controller(tmp_path, branch_count=1)
    payload = b"legacy turn without deep evidence\nXINAO_LINEAGE_STATE: WAIT\n"
    turn_dir = write_successful_attempt(
        controller,
        lineage_id="world-01",
        turn_number=1,
        payload=payload,
    )
    controller._lineage_states["world-01"].update(
        {
            "turns_completed": 1,
            "last_completed_turn_dir": str(turn_dir),
            "session_id": "legacy-session",
        }
    )
    controller.config["deep_evidence_required"] = True
    controller.config["deep_evidence_required_from_turn"] = {
        "world-01": 2,
        "root-main": 1,
    }
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller", fromlist=["git_output"]
    )
    monkeypatch.setattr(controller_module, "git_output", lambda *_args, **_kwargs: "a" * 40)

    packet_dir, packet = controller.freeze_fusion_packet(
        {"waves_completed": 0, "consumed_turns": {"world-01": 0}}
    )

    assert packet["selected_turns"] == {"world-01": 1}
    deep = json.loads((packet_dir / "DEEP_EVIDENCE_01.json").read_text(encoding="utf-8"))
    assert deep["availability"] == "UNAVAILABLE_LEGACY_TURN"


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


def test_fusion_packet_exposes_hash_bound_deep_event_and_artifact_on_demand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    turn_dir = write_successful_attempt(
        controller,
        lineage_id="world-01",
        turn_number=1,
        payload=b"thin candidate\nXINAO_LINEAGE_STATE: CONTINUE\n",
    )
    attempt_dir = turn_dir / "attempt-01"
    artifact_sha = attach_deep_evidence(controller, attempt_dir)
    controller._lineage_states["world-01"].update(
        {
            "turns_completed": 1,
            "last_completed_turn_dir": str(turn_dir),
            "session_id": "session-world-01",
        }
    )
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller", fromlist=["git_output"]
    )
    monkeypatch.setattr(controller_module, "git_output", lambda *_args, **_kwargs: "a" * 40)

    packet_dir, packet = controller.freeze_fusion_packet(
        {"waves_completed": 0, "consumed_turns": {"world-01": 0}}
    )
    entry = packet["manifest"]["entries"][0]
    assert entry["deep_evidence_availability"] == "AVAILABLE"
    assert entry["deep_evidence_path"] == "DEEP_EVIDENCE_01.json"
    assert (packet_dir / entry["deep_evidence_path"]).is_file()

    event = inspect_deep_evidence(
        packet_dir=packet_dir,
        candidate_index=1,
        event_sequence=2,
    )
    assert event["event"]["item"]["type"] == "agent_message"
    assert event["event"]["item"]["text"] == "deep relation"

    artifact = inspect_deep_evidence(
        packet_dir=packet_dir,
        candidate_index=1,
        artifact_sha256=artifact_sha.lower(),
    )
    assert Path(artifact["verified_blob_path"]).read_bytes() == (
        b"branch artifact with exact bytes\n"
    )
    navigation = inspect_deep_evidence(packet_dir=packet_dir, candidate_index=1)
    assert navigation["deep_evidence"]["query_command_prefix"][-2:] == [
        "--candidate-index",
        "1",
    ]


def test_workspace_artifact_capture_keeps_material_ignored_state_and_excludes_secrets(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    (repo / ".gitignore").write_text(
        "xinao/reality/live/\n__pycache__/\n.venv/\nother-ignored/\n",
        encoding="utf-8",
    )
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "baseline")
    source_head = git(repo, "rev-parse", "HEAD")

    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    live = repo / "xinao" / "reality" / "live"
    live.mkdir(parents=True)
    (live / "world.json").write_text('{"state":"live"}\n', encoding="utf-8")
    (repo / "auth.json").write_text('{"secret":"must-not-read"}\n', encoding="utf-8")
    (repo / "renamed-notes.txt").write_text(
        "api_key=sk-1234567890abcdefghijklmnop\n",
        encoding="utf-8",
    )
    cache = repo / "__pycache__"
    cache.mkdir()
    (cache / "generated.pyc").write_bytes(b"cache")
    venv = repo / ".venv"
    venv.mkdir()
    (venv / "large.bin").write_bytes(b"regenerable")
    other_ignored = repo / "other-ignored"
    other_ignored.mkdir()
    (other_ignored / "bulk.bin").write_bytes(b"not admitted")

    run_dir = tmp_path / "run"
    attempt_dir = run_dir / "lineages" / "world-01" / "turns" / "turn-000001" / "attempt-01"
    result = capture_workspace_artifacts(
        workspace=repo,
        run_id="test-run",
        source_head=source_head,
        run_dir=run_dir,
        lineage_id="world-01",
        turn_number=1,
        attempt_number=1,
        manifest_path=attempt_dir / "artifact_manifest.json",
    )
    manifest = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    included = {entry["relative_path"]: entry for entry in manifest["entries"]}
    excluded = {entry["relative_path"]: entry["reason"] for entry in manifest["exclusions"]}
    assert {"tracked.txt", "candidate.txt", "xinao/reality/live/world.json"} <= set(included)
    assert included["xinao/reality/live/world.json"]["source_class"] == "IGNORED_MATERIAL"
    assert (
        Path(included["candidate.txt"]["blob_path"]).read_bytes()
        == (repo / "candidate.txt").read_bytes()
    )
    assert excluded["auth.json"] == "FORBIDDEN_SECRET_OR_ACCOUNT_SURFACE"
    assert excluded["renamed-notes.txt"] == "SECRET_CONTENT_BLOCKED"
    assert excluded["__pycache__/generated.pyc"] == "REGENERABLE_CACHE"
    assert excluded[".venv/large.bin"] == "REGENERABLE_CACHE"
    assert excluded["other-ignored/bulk.bin"] == "IGNORED_NOT_ADMITTED_AS_RESEARCH_REALITY"
    assert result["safety_block_count"] == 1
    assert result["complete"] is False


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


@pytest.mark.parametrize("error_class", ["BODY_INCIDENT", "EVIDENCE_INCIDENT"])
def test_branch_loop_preserves_incident_class_while_parked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_class: str
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    controller._lineage_states["world-01"]["session_id"] = "session-world-01"
    parked: list[tuple[str, str]] = []

    monkeypatch.setattr(
        controller,
        "execute_turn",
        lambda **_kwargs: {"outcome": "FAILED", "error_class": error_class},
    )

    def fake_wait(lineage_id: str, status: str) -> bool:
        parked.append((lineage_id, status))
        controller._shutdown.set()
        return False

    monkeypatch.setattr(controller, "_wait_parked", fake_wait)
    controller.branch_loop(branches[0])
    assert parked == [("world-01", error_class)]


@pytest.mark.parametrize("error_class", ["BODY_INCIDENT", "EVIDENCE_INCIDENT"])
def test_root_recovery_preserves_incident_class_while_parked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_class: str
) -> None:
    controller, _, _ = make_test_controller(tmp_path, branch_count=1)
    parked: list[tuple[str, str]] = []
    monkeypatch.setattr(
        controller,
        "execute_turn",
        lambda **_kwargs: {"outcome": "FAILED", "error_class": error_class},
    )

    def fake_wait(lineage_id: str, status: str) -> bool:
        parked.append((lineage_id, status))
        return False

    monkeypatch.setattr(controller, "_wait_parked", fake_wait)
    result = controller._execute_root_prompt_with_recovery("root-main", "fusion")
    assert result == {"outcome": "STOPPED"}
    assert parked == [("root-main", f"ROOT_{error_class}")]


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


def test_reconcile_incomplete_attempts_finalizes_only_unambiguous_completed_turn(
    tmp_path: Path,
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    branch = branches[0]
    turn_dir = controller.lineage_dir("world-01") / "turns" / "turn-000001"
    attempt = turn_dir / "attempt-01"
    attempt.mkdir(parents=True)
    (attempt / "prompt.txt").write_text("research", encoding="utf-8")
    (attempt / "exec_stderr.txt").write_text("", encoding="utf-8")
    (attempt / "last_message.txt").write_text(
        "preserved result\nXINAO_LINEAGE_STATE: WAIT\n",
        encoding="utf-8",
    )
    (attempt / "command.json").write_text(json.dumps({"resume_session_id": None}), encoding="utf-8")
    (attempt / "exec_stdout.jsonl").write_text(
        json.dumps({"type": "thread.started", "thread_id": "session-recovered"})
        + "\n"
        + json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3}})
        + "\n",
        encoding="utf-8",
    )
    config = {
        **controller.config,
        "source_repo": str(tmp_path / "source"),
        "branch_lineages": [branch],
    }
    recovery_dir = controller.run_dir / "recovery" / "test"

    result = reconcile_incomplete_attempts(config, recovery_dir=recovery_dir)

    assert len(result["completed"]) == 1
    assert result["quarantined"] == []
    receipt = json.loads((attempt / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["completion_basis"] == "RECOVERED_TURN_COMPLETED_EVENT_AND_LIFECYCLE"
    assert receipt["process_exit_code_observed"] is False
    assert receipt["deep_evidence"]["status"] == "PARTIAL"
    state = json.loads(controller.lineage_state_path("world-01").read_text(encoding="utf-8"))
    assert state["turns_completed"] == 1
    assert state["session_id"] == "session-recovered"
    assert state["lifecycle_state"] == "WAIT"


def test_reconcile_incomplete_attempts_quarantines_failed_turn_in_place(
    tmp_path: Path,
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    attempt = controller.lineage_dir("world-01") / "turns" / "turn-000001" / "attempt-01"
    attempt.mkdir(parents=True)
    (attempt / "prompt.txt").write_text("research", encoding="utf-8")
    (attempt / "exec_stderr.txt").write_text("runtime failed", encoding="utf-8")
    (attempt / "exec_stdout.jsonl").write_text(
        json.dumps({"type": "turn.failed"}) + "\n", encoding="utf-8"
    )
    recovery_dir = controller.run_dir / "recovery" / "test"

    result = reconcile_incomplete_attempts(
        {**controller.config, "branch_lineages": branches},
        recovery_dir=recovery_dir,
    )

    assert result["completed"] == []
    assert len(result["quarantined"]) == 1
    assert not (attempt / "receipt.json").exists()
    assert (attempt / "recovery_disposition.json").is_file()
    state = json.loads(controller.lineage_state_path("world-01").read_text(encoding="utf-8"))
    assert state["turns_completed"] == 0
    assert state["status"] == "RECOVERY_QUARANTINED_INCOMPLETE_ATTEMPT"


def test_reconcile_failed_attempt_reuses_immutable_disposition(tmp_path: Path) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    attempt = controller.lineage_dir("world-01") / "turns" / "turn-000001" / "attempt-01"
    attempt.mkdir(parents=True)
    (attempt / "prompt.txt").write_text("research", encoding="utf-8")
    (attempt / "exec_stderr.txt").write_text("runtime failed", encoding="utf-8")
    (attempt / "exec_stdout.jsonl").write_text(
        json.dumps({"type": "turn.failed"}) + "\n", encoding="utf-8"
    )
    config = {**controller.config, "branch_lineages": branches}

    first = reconcile_incomplete_attempts(
        config,
        recovery_dir=controller.run_dir / "recovery" / "first",
    )
    disposition_path = attempt / "recovery_disposition.json"
    before = disposition_path.read_bytes()
    before_mtime = disposition_path.stat().st_mtime_ns
    second = reconcile_incomplete_attempts(
        config,
        recovery_dir=controller.run_dir / "recovery" / "second",
    )

    assert first["quarantined"][0]["reused"] is False
    assert second["quarantined"][0]["reused"] is True
    assert disposition_path.read_bytes() == before
    assert disposition_path.stat().st_mtime_ns == before_mtime


def test_reconcile_new_evidence_required_turn_cannot_be_laundered_to_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    attempt = controller.lineage_dir("world-01") / "turns" / "turn-000001" / "attempt-01"
    attempt.mkdir(parents=True)
    (attempt / "prompt.txt").write_text("research", encoding="utf-8")
    (attempt / "exec_stderr.txt").write_text("", encoding="utf-8")
    (attempt / "last_message.txt").write_text(
        "result\nXINAO_LINEAGE_STATE: WAIT\n", encoding="utf-8"
    )
    (attempt / "exec_stdout.jsonl").write_text(
        json.dumps({"type": "thread.started", "thread_id": "s1"})
        + "\n"
        + json.dumps({"type": "turn.completed"})
        + "\n",
        encoding="utf-8",
    )
    config = {
        **controller.config,
        "branch_lineages": branches,
        "source_head": "a" * 40,
        "deep_evidence_required": True,
        "deep_evidence_required_from_turn": {"world-01": 1, "root-main": 1},
    }
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller",
        fromlist=["capture_workspace_artifacts"],
    )
    monkeypatch.setattr(
        controller_module,
        "capture_workspace_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(PerpetualRuntimeError("capture unavailable")),
    )

    result = reconcile_incomplete_attempts(
        config,
        recovery_dir=controller.run_dir / "recovery" / "evidence",
    )

    assert result["completed"] == []
    assert result["quarantined"][0]["reason"] == (
        "REQUIRED_DEEP_EVIDENCE_UNAVAILABLE_DURING_RECOVERY"
    )
    assert not (attempt / "receipt.json").exists()
    state = json.loads(controller.lineage_state_path("world-01").read_text(encoding="utf-8"))
    assert state["turns_completed"] == 0
    assert state["status"] == "EVIDENCE_INCIDENT"


def test_reconcile_outside_workspace_denial_is_body_incident(tmp_path: Path) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    attempt = controller.lineage_dir("world-01") / "turns" / "turn-000001" / "attempt-01"
    attempt.mkdir(parents=True)
    (attempt / "prompt.txt").write_text("research", encoding="utf-8")
    (attempt / "exec_stderr.txt").write_text("", encoding="utf-8")
    (attempt / "last_message.txt").write_text(
        "result\nXINAO_LINEAGE_STATE: WAIT\n", encoding="utf-8"
    )
    outside = tmp_path / "outside" / "blocked.txt"
    (attempt / "exec_stdout.jsonl").write_text(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "status": "failed",
                    "aggregated_output": f"Access is denied: {outside}",
                },
            }
        )
        + "\n"
        + json.dumps({"type": "turn.completed"})
        + "\n",
        encoding="utf-8",
    )

    result = reconcile_incomplete_attempts(
        {**controller.config, "branch_lineages": branches},
        recovery_dir=controller.run_dir / "recovery" / "body",
    )

    assert result["completed"] == []
    assert result["quarantined"][0]["reason"] == "BODY_INCIDENT_DETECTED_DURING_RECOVERY"
    state = json.loads(controller.lineage_state_path("world-01").read_text(encoding="utf-8"))
    assert state["turns_completed"] == 0
    assert state["status"] == "BODY_INCIDENT"


def test_world_turn_quota_exempts_root_and_uses_four_account_slots(tmp_path: Path) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    controller.config["world_turn_concurrency_limit"] = 4
    controller.config["world_turn_quota_root"] = str(tmp_path / "quota")

    with controller.world_turn_quota_lease(branches[0]) as lease:
        assert lease is not None
        assert lease["counted"] is True
        assert lease["account_slot"] == "C"
        assert lease["limit"] == 4
        assert 1 <= lease["slot"] <= 4
    with controller.world_turn_quota_lease(controller.root_spec) as root_lease:
        assert root_lease == {"counted": False, "reason": "LATE_FUSION_ROOT_EXEMPT"}
    assert len(list((tmp_path / "quota" / "C").glob("world-turn-*.lock"))) <= 4


def test_world_turn_quota_remains_bound_when_controller_dies_but_child_lives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first, first_branches, _ = make_test_controller(
        tmp_path / "first", run_id="run-first", branch_count=1
    )
    second, second_branches, _ = make_test_controller(
        tmp_path / "second", run_id="run-second", branch_count=1
    )
    quota_root = tmp_path / "shared-quota"
    for controller in (first, second):
        controller.config["world_turn_concurrency_limit"] = 1
        controller.config["world_turn_quota_root"] = str(quota_root)
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller",
        fromlist=["is_process_alive"],
    )
    live_pids = {4242}
    monkeypatch.setattr(controller_module, "is_process_alive", lambda pid: pid in live_pids)

    lease = first.try_reserve_world_turn_quota(first_branches[0])
    assert lease is not None
    bound = first.bind_world_turn_quota_child(first_branches[0], child_pid=4242)
    assert bound is not None and bound["status"] == "BOUND"
    # Simulate an abrupt controller loss: no context-manager finalizer runs.
    first._world_turn_leases.clear()

    assert second.try_reserve_world_turn_quota(second_branches[0]) is None
    live_pids.clear()
    replacement = second.try_reserve_world_turn_quota(second_branches[0])
    assert replacement is not None
    assert replacement["lease_id"] != lease["lease_id"]


def test_recovery_liveness_reads_bound_child_from_durable_quota_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    controller.config["world_turn_concurrency_limit"] = 1
    controller.config["world_turn_quota_root"] = str(tmp_path / "quota")
    monkeypatch.setattr(
        "services.xinao_perpetual_world_compute.controller.is_process_alive",
        lambda pid: pid == 4242,
    )

    lease = controller.try_reserve_world_turn_quota(branches[0])
    assert lease is not None
    controller.bind_world_turn_quota_child(branches[0], child_pid=4242)
    controller._world_turn_leases.clear()

    assert find_live_runtime_processes({}, {}, controller.config) == {"quota.child.world-01": 4242}


def test_reserved_quota_record_remains_explicit_recovery_blocker(tmp_path: Path) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    controller.config["world_turn_concurrency_limit"] = 1
    controller.config["world_turn_quota_root"] = str(tmp_path / "quota")

    lease = controller.try_reserve_world_turn_quota(branches[0])
    assert lease is not None and lease["status"] == "RESERVED"
    records = world_turn_quota_records_for_run(controller.config)

    assert [(record["status"], record["lease_id"]) for record in records] == [
        ("RESERVED", lease["lease_id"])
    ]


def _write_uncommitted_receipt(
    controller: PerpetualController,
    *,
    error_class: str | None,
    outside_denial: Path | None = None,
) -> Path:
    attempt = controller.lineage_dir("world-01") / "turns" / "turn-000001" / "attempt-01"
    attempt.mkdir(parents=True)
    prompt = attempt / "prompt.txt"
    stdout = attempt / "exec_stdout.jsonl"
    stderr = attempt / "exec_stderr.txt"
    message = attempt / "last_message.txt"
    prompt.write_text("research", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    message.write_text("result\nXINAO_LINEAGE_STATE: WAIT\n", encoding="utf-8")
    rows: list[dict[str, object]] = []
    if outside_denial is not None:
        rows.append(
            {
                "type": "item.completed",
                "item": {
                    "id": "outside-write",
                    "type": "command_execution",
                    "status": "failed",
                    "exit_code": 1,
                    "aggregated_output": f"Access is denied: {outside_denial}",
                },
            }
        )
    rows.append({"type": "turn.completed"})
    stdout.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    body_incident = {"incident_id": "body-test-1"} if error_class == "BODY_INCIDENT" else None
    receipt = {
        "schema": controller.schemas["turn"],
        "run_id": controller.config["run_id"],
        "lineage_id": "world-01",
        "turn_number": 1,
        "attempt_number": 1,
        "exit_code": 0,
        "turn_status": "turn.completed",
        "session_id_observed": "session-1",
        "lifecycle_state": "WAIT",
        "error_class": error_class,
        "prompt_sha256": sha256_file(prompt),
        "stdout_sha256": sha256_file(stdout),
        "stderr_sha256": sha256_file(stderr),
        "last_message_sha256": sha256_file(message),
        "body_incident": body_incident,
        "deep_evidence": {"status": "NOT_CAPTURED_FAILED_ATTEMPT"},
    }
    (attempt / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return attempt


def test_reconcile_commits_receipt_written_before_lineage_state(tmp_path: Path) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    _write_uncommitted_receipt(controller, error_class=None)
    state_path = controller.lineage_state_path("world-01")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["active_pid"] = 12345
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = reconcile_incomplete_attempts(
        {**controller.config, "branch_lineages": branches},
        recovery_dir=controller.run_dir / "recovery" / "receipt-gap",
    )

    assert result["completed"] == []
    assert result["receipt_state_commits"][0]["disposition"] == "COMMIT_COMPLETED_TURN"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["turns_completed"] == 1
    assert state["active_pid"] is None
    assert state["session_id"] == "session-1"
    assert state["lifecycle_state"] == "WAIT"


def test_reconcile_receipted_body_incident_restores_park_idempotently(
    tmp_path: Path,
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    _write_uncommitted_receipt(
        controller,
        error_class="BODY_INCIDENT",
        outside_denial=tmp_path / "protected" / "blocked.txt",
    )
    config = {**controller.config, "branch_lineages": branches}
    state_path = controller.lineage_state_path("world-01")

    first = reconcile_incomplete_attempts(
        config,
        recovery_dir=controller.run_dir / "recovery" / "body-first",
    )
    before = state_path.read_bytes()
    second = reconcile_incomplete_attempts(
        config,
        recovery_dir=controller.run_dir / "recovery" / "body-second",
    )

    assert first["receipt_state_commits"][0]["reused"] is False
    assert second["receipt_state_commits"][0]["reused"] is True
    assert state_path.read_bytes() == before
    state = json.loads(before)
    assert state["turns_completed"] == 0
    assert state["status"] == "BODY_INCIDENT"


@pytest.mark.parametrize(
    "removed_name",
    ["trajectory_index.jsonl", "artifact_manifest.json", "artifact_blob"],
)
def test_reconcile_required_receipt_refuses_missing_or_drifted_deep_evidence(
    tmp_path: Path, removed_name: str
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    attempt = _write_uncommitted_receipt(controller, error_class=None)
    artifact_sha = attach_deep_evidence(controller, attempt)
    if removed_name == "artifact_blob":
        target = (
            controller.run_dir
            / "deep-evidence"
            / "blobs"
            / "sha256"
            / artifact_sha[:2]
            / artifact_sha
        )
    else:
        target = attempt / removed_name
    target.unlink()
    config = {
        **controller.config,
        "branch_lineages": branches,
        "deep_evidence_required": True,
        "deep_evidence_required_from_turn": {"world-01": 1, "root-main": 1},
    }

    with pytest.raises(PerpetualRuntimeError, match="RECOVERY_REQUIRED_"):
        reconcile_incomplete_attempts(
            config,
            recovery_dir=controller.run_dir / "recovery" / removed_name,
        )

    state = json.loads(controller.lineage_state_path("world-01").read_text(encoding="utf-8"))
    assert state["turns_completed"] == 0
    assert "recovery_state_commits" not in state


@pytest.mark.parametrize("error_class", [None, "BODY_INCIDENT"])
def test_reconcile_sealed_receipt_cannot_be_rewritten_after_state_commit(
    tmp_path: Path, error_class: str | None
) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    attempt = _write_uncommitted_receipt(
        controller,
        error_class=error_class,
        outside_denial=(tmp_path / "protected" / "blocked.txt") if error_class else None,
    )
    config = {**controller.config, "branch_lineages": branches}
    reconcile_incomplete_attempts(
        config,
        recovery_dir=controller.run_dir / "recovery" / "seal-first",
    )
    state_path = controller.lineage_state_path("world-01")
    state_before = state_path.read_bytes()
    receipt_path = attempt / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if error_class == "BODY_INCIDENT":
        receipt["body_incident"]["incident_id"] = "body-tampered"
    else:
        receipt["session_id_observed"] = "session-tampered"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(PerpetualRuntimeError, match="RECOVERY_STATE_COMMIT_RECEIPT_DRIFT"):
        reconcile_incomplete_attempts(
            config,
            recovery_dir=controller.run_dir / "recovery" / "seal-second",
        )

    assert state_path.read_bytes() == state_before


def test_reconcile_migrates_matching_scalar_recovery_seal_once(tmp_path: Path) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    _write_uncommitted_receipt(
        controller,
        error_class="BODY_INCIDENT",
        outside_denial=tmp_path / "protected" / "blocked.txt",
    )
    config = {**controller.config, "branch_lineages": branches}
    state_path = controller.lineage_state_path("world-01")
    reconcile_incomplete_attempts(
        config,
        recovery_dir=controller.run_dir / "recovery" / "scalar-source",
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.pop("recovery_state_commits")
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = reconcile_incomplete_attempts(
        config,
        recovery_dir=controller.run_dir / "recovery" / "scalar-migration",
    )

    migrated = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["receipt_state_commits"][0]["reused"] is True
    assert len(migrated["recovery_state_commits"]) == 1
    assert (
        migrated["recovery_state_commits"][0]["receipt_sha256"]
        == migrated["recovery_state_commit_receipt_sha256"]
    )


def test_reconcile_scalar_recovery_seal_rejects_receipt_rewrite(tmp_path: Path) -> None:
    controller, branches, _ = make_test_controller(tmp_path, branch_count=1)
    attempt = _write_uncommitted_receipt(
        controller,
        error_class="BODY_INCIDENT",
        outside_denial=tmp_path / "protected" / "blocked.txt",
    )
    config = {**controller.config, "branch_lineages": branches}
    state_path = controller.lineage_state_path("world-01")
    reconcile_incomplete_attempts(
        config,
        recovery_dir=controller.run_dir / "recovery" / "scalar-seal",
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.pop("recovery_state_commits")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    sealed_scalar_state = state_path.read_bytes()
    receipt_path = attempt / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["body_incident"]["incident_id"] = "body-tampered-after-scalar-seal"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(PerpetualRuntimeError, match="RECOVERY_STATE_COMMIT_RECEIPT_DRIFT"):
        reconcile_incomplete_attempts(
            config,
            recovery_dir=controller.run_dir / "recovery" / "scalar-drift",
        )

    assert state_path.read_bytes() == sealed_scalar_state


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
    launcher = tmp_path / "launcher.ps1"
    launcher.write_bytes(
        b"# frozen test launcher\n"
        b"& $codexExe --cd $launchWorkdir --dangerously-bypass-approvals-and-sandbox "
        b"@slotSpecificCodexArgs @CodexArgs\n"
        b'sandbox_mode = "danger-full-access"\n'
    )
    config = {
        "schema": run_schema,
        "account_slot": "C",
        "run_id": "run-1",
        "run_dir": str(run_dir),
        "source_repo": str(tmp_path / "source"),
        "source_head": "a" * 40,
        "launcher_path": str(launcher),
        "launcher_sha256": sha256_file(launcher),
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
    for lineage_id, role in (("world-01", "independent_world"), ("root-main", "late_fusion_root")):
        lineage_dir = run_dir / "lineages" / lineage_id
        lineage_dir.mkdir(parents=True)
        (lineage_dir / "state.json").write_text(
            json.dumps(
                {
                    "schema": "lineage",
                    "run_id": "run-1",
                    "lineage_id": lineage_id,
                    "role": role,
                    "turns_completed": 0,
                    "active_pid": None,
                }
            ),
            encoding="utf-8",
        )
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
    assert updated["deep_evidence_required"] is True
    assert updated["body_boundary"]["sandbox_mode"] == "workspace-write"
    assert updated["launcher_path"] != str(launcher)
    assert Path(updated["launcher_path"]).is_file()
    assert b"--sandbox workspace-write" in Path(updated["launcher_path"]).read_bytes()
    assert (
        b"--dangerously-bypass-approvals-and-sandbox"
        not in Path(updated["launcher_path"]).read_bytes()
    )
    assert result["release_adoption"]["body_boundary_adopted"] is True
    assert updated["deep_evidence_required_from_turn"] == {
        "root-main": 1,
        "world-01": 1,
    }
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


def _make_reality_migration_preparation_runtime(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, Path]]:
    runtime_root = tmp_path / "runtime"
    run_dir = runtime_root / "runs" / "run-1"
    source_repo = tmp_path / "source"
    clone_root = tmp_path / "lineages" / "run-1"
    workspaces = {
        "world-01": clone_root / "world-01",
        "root-main": clone_root / "root-main",
    }
    for path in (run_dir, source_repo, *workspaces.values()):
        path.mkdir(parents=True, exist_ok=True)
    config = {
        "schema": RUN_SCHEMA,
        "account_slot": "A",
        "run_id": "run-1",
        "run_dir": str(run_dir),
        "source_repo": str(source_repo),
        "source_head": "a" * 40,
        "clone_run_root": str(clone_root),
        "branch_lineages": [
            {
                "lineage_id": "world-01",
                "role": "independent_world",
                "workspace": str(workspaces["world-01"]),
            }
        ],
        "root_lineage": {
            "lineage_id": "root-main",
            "role": "late_fusion_root",
            "workspace": str(workspaces["root-main"]),
        },
    }
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "current.json").write_text(
        json.dumps(
            {
                "schema": RUN_SCHEMA,
                "run_id": "run-1",
                "run_dir": str(run_dir),
                "controller_pid": 9911,
                "account_slot": "A",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
    (run_dir / "controller_state.json").write_text(
        json.dumps(
            {
                "schema": "controller",
                "run_id": "run-1",
                "account_slot": "A",
                "pid": 9911,
                "status": "STOPPED",
                "active_processes": {},
            }
        ),
        encoding="utf-8",
    )
    for lineage_id in workspaces:
        lineage_dir = run_dir / "lineages" / lineage_id
        lineage_dir.mkdir(parents=True)
        (lineage_dir / "state.json").write_text(
            json.dumps(
                {
                    "schema": "lineage",
                    "run_id": "run-1",
                    "lineage_id": lineage_id,
                    "active_pid": None,
                    "turns_completed": 3,
                }
            ),
            encoding="utf-8",
        )
    (run_dir / "STOP.json").write_text(
        json.dumps({"schema": LEGACY_STOP_SCHEMA, "reason": "preserve stopped capacity"}),
        encoding="utf-8",
    )
    return runtime_root, run_dir, source_repo, workspaces


def test_prepare_reality_migration_is_offline_per_run_and_preserves_control_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root, run_dir, source_repo, workspaces = _make_reality_migration_preparation_runtime(
        tmp_path
    )
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller",
        fromlist=["prepare_reality_migration"],
    )
    monkeypatch.setattr(controller_module, "find_live_runtime_processes", lambda *_args: {})
    monkeypatch.setattr(
        controller_module,
        "validate_source_repo",
        lambda repo: {
            "root": str(repo),
            "head": "a" * 40,
            "branch": "main",
            "status_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        controller_module,
        "validate_lineage_runtime_repo",
        lambda workspace, source_head: {
            "workspace": str(workspace),
            "source_head": source_head,
            "head": source_head,
            "status_sha256": "c" * 64,
        },
    )
    migration_calls: list[dict[str, object]] = []

    def fake_migration(canonical_repo: Path, **kwargs: object) -> dict[str, object]:
        migration_calls.append({"canonical_repo": canonical_repo, **kwargs})
        manifest = Path(str(kwargs["world_compute_root"])) / "migrations" / "m1" / "MANIFEST.json"
        return {
            "manifest_path": str(manifest),
            "manifest_sha256": "d" * 64,
            "migration_id": "m1",
            "source_preserved": True,
        }

    fake_module = SimpleNamespace(migrate_live_reality_copy_first=fake_migration)
    fake_loader = SimpleNamespace(exec_module=lambda _module: None)
    monkeypatch.setattr(
        controller_module.importlib.util,
        "spec_from_file_location",
        lambda *_args, **_kwargs: SimpleNamespace(loader=fake_loader),
    )
    monkeypatch.setattr(
        controller_module.importlib.util,
        "module_from_spec",
        lambda _spec: fake_module,
    )
    control_paths = [
        runtime_root / "current.json",
        run_dir / "run_config.json",
        run_dir / "controller_state.json",
        run_dir / "STOP.json",
        *(run_dir / "lineages" / lineage_id / "state.json" for lineage_id in workspaces),
    ]
    before = {path: path.read_bytes() for path in control_paths}
    world_compute_base = tmp_path / "world-compute"
    result = prepare_reality_migration(
        SimpleNamespace(
            runtime_root=runtime_root,
            expected_account_slot="A",
            live_reality_root=tmp_path / "live-reality",
            world_compute_root=world_compute_base,
        )
    )

    assert result["status"] == "PREPARED_NOT_ADOPTED"
    assert result["controller_started"] is False
    assert result["run_config_changed"] is False
    assert result["current_pointer_changed"] is False
    assert Path(result["preparation_receipt"]).is_file()
    assert {path: path.read_bytes() for path in control_paths} == before
    assert len(migration_calls) == 1
    call = migration_calls[0]
    assert call["canonical_repo"] == source_repo.resolve()
    assert call["world_compute_root"] == (world_compute_base / "run-1").resolve()
    assert call["workspace_roots"] == {
        lineage_id: workspace.resolve() for lineage_id, workspace in workspaces.items()
    }
    assert call["active_child_pids"] == {}


def test_prepare_reality_migration_rejects_live_child_before_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root, run_dir, _source_repo, _workspaces = _make_reality_migration_preparation_runtime(
        tmp_path
    )
    controller_module = __import__(
        "services.xinao_perpetual_world_compute.controller",
        fromlist=["prepare_reality_migration"],
    )
    monkeypatch.setattr(
        controller_module,
        "find_live_runtime_processes",
        lambda *_args: {"lineage.child.world-01": 4455},
    )
    world_compute_base = tmp_path / "world-compute"

    with pytest.raises(PerpetualRuntimeError, match="REALITY_MIGRATION_REFUSED_LIVE_PROCESSES"):
        prepare_reality_migration(
            SimpleNamespace(
                runtime_root=runtime_root,
                expected_account_slot="A",
                live_reality_root=tmp_path / "live-reality",
                world_compute_root=world_compute_base,
            )
        )

    assert not world_compute_base.exists()
    assert not (run_dir / "reality-migration-preparation" / "receipt.json").exists()


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
