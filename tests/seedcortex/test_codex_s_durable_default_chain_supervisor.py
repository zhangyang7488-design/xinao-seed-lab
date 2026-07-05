import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "codex_s_durable_default_chain_supervisor.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_s_durable_default_chain_supervisor", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_source_tree(source_root: Path) -> Path:
    source_root.mkdir(parents=True, exist_ok=True)
    for name in [
        "AUTHORITY_READ_ORDER.txt",
        "当前源文本增量_20260704.txt",
        "根意图分工.txt",
        "XINAO_333_固定锚点.txt",
        "新系统独立并行_自由发散外部研究总稿_20260701.txt",
        "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
    ]:
        (source_root / name).write_text(f"{name}\nRootIntentLoop\nWorkerBrief\nFanIn\n", encoding="utf-8")
    package = source_root.parent / "stage_package.txt"
    package.write_text("超大块阶段验证与投递包\n默认不停\n", encoding="utf-8")
    return package


def test_supervisor_once_writes_heartbeat_ledger_and_readback(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    source_root = tmp_path / "source"
    repo.mkdir(parents=True, exist_ok=True)
    package = _write_source_tree(source_root)

    payload = module.run_supervisor(
        runtime=runtime,
        repo=repo,
        source_root=source_root,
        package_path=package,
        supervisor_wave_id="durable-supervisor-test-wave",
        parent_wave_id="parent-wave",
        task_queue="test-task-queue",
        poll_seconds=1,
        min_dispatch_interval_seconds=60,
        max_cycles=1,
        once=True,
        no_dispatch=True,
        workflow_timeout_seconds=1,
        python_exe="python",
    )

    assert payload["schema_version"] == "xinao.codex_s.durable_default_chain_supervisor.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_CODEX_S_DURABLE_DEFAULT_CHAIN_SUPERVISOR_V1"
    assert payload["default_transaction_chain"] == "RootIntentLoop / S Default Dynamic Loop"
    assert payload["source_package"]["stage_package_ref"]["exists"] is True
    assert payload["source_package"]["authority_existing_count"] == 6
    assert payload["dispatch_supervision"]["dispatch_attempted_this_cycle"] is False
    assert payload["heartbeat"]["background_keepalive"] is True
    assert payload["heartbeat"]["polling_continues"] is True
    assert payload["stop"]["stop_allowed"] is False
    assert payload["dispatch_supervision"]["pass_report_substitute_allowed"] is False
    assert payload["repair_plan"]["continue_main_loop"] is True
    assert payload["completion_claim_allowed"] is False
    assert payload["not_execution_controller"] is True

    output = payload["output_paths"]
    for key in [
        "latest",
        "wave_latest",
        "cycle",
        "heartbeat_latest",
        "repair_plan",
        "worker_dispatch_ledger_wave",
        "activity_ledger",
        "readback_zh",
    ]:
        assert Path(output[key]).is_file(), key


def test_supervisor_resumes_cycle_index_after_restart(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    source_root = tmp_path / "source"
    repo.mkdir(parents=True, exist_ok=True)
    package = _write_source_tree(source_root)
    wave_id = "durable-supervisor-test-wave"
    existing = module.output_paths(runtime, wave_id, f"{wave_id}-cycle-000002")
    Path(existing["cycle"]).parent.mkdir(parents=True, exist_ok=True)
    Path(existing["cycle"]).write_text("{}", encoding="utf-8")

    assert module.next_cycle_index(runtime, wave_id) == 3

    payload = module.run_supervisor(
        runtime=runtime,
        repo=repo,
        source_root=source_root,
        package_path=package,
        supervisor_wave_id=wave_id,
        parent_wave_id="parent-wave",
        task_queue="test-task-queue",
        poll_seconds=1,
        min_dispatch_interval_seconds=60,
        max_cycles=1,
        once=True,
        no_dispatch=True,
        workflow_timeout_seconds=1,
        python_exe="python",
    )

    assert payload["cycle_index"] == 3
    assert payload["cycle_id"].endswith("cycle-000003")


def test_supervisor_blocks_second_autonomous_dispatch_without_hard_acceptance(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    source_root = tmp_path / "source"
    repo.mkdir(parents=True, exist_ok=True)
    package = _write_source_tree(source_root)
    wave_id = "durable-supervisor-test-wave"
    existing = module.output_paths(runtime, wave_id, f"{wave_id}-cycle-000001")
    Path(existing["cycle"]).parent.mkdir(parents=True, exist_ok=True)
    Path(existing["cycle"]).write_text(
        json.dumps(
            {
                "dispatch_supervision": {
                    "dispatch_attempted_this_cycle": True,
                    "dispatch_result": {"dispatch_attempted": True, "succeeded": True},
                }
            }
        ),
        encoding="utf-8",
    )

    payload = module.run_supervisor(
        runtime=runtime,
        repo=repo,
        source_root=source_root,
        package_path=package,
        supervisor_wave_id=wave_id,
        parent_wave_id="parent-wave",
        task_queue="test-task-queue",
        poll_seconds=1,
        min_dispatch_interval_seconds=0,
        max_cycles=1,
        once=True,
        no_dispatch=False,
        workflow_timeout_seconds=1,
        python_exe="python",
        max_autonomous_dispatches=1,
    )

    assert payload["dispatch_supervision"]["dispatch_attempted_this_cycle"] is False
    gate = payload["dispatch_supervision"]["hard_acceptance_dispatch_gate"]
    assert gate["status"] == "dispatch_blocked_hard_acceptance_required"
    assert gate["prior_autonomous_dispatch_count"] == 1
    assert gate["next_dispatch_allowed"] is False
    assert payload["repair_plan"]["repair_required"] is True
    assert any(
        item["blocker_name"] == "HARD_ACCEPTANCE_REQUIRED_BEFORE_NEXT_AUTONOMOUS_DISPATCH"
        for item in payload["repair_plan"]["repair_items"]
    )


def test_build_workflow_command_binds_live_temporal_and_source_refs(tmp_path: Path) -> None:
    module = _load_module()
    command = module.build_workflow_command(
        python_exe="python",
        runtime=tmp_path / "runtime",
        repo=tmp_path / "repo",
        source_refs=["package.txt", "AUTHORITY_READ_ORDER.txt"],
        task_queue="xinao-codex-task-default",
        workflow_id="wf-1",
        user_goal="durable polling",
    )

    assert "-m" in command
    assert "services.agent_runtime.temporal_codex_task_workflow" in command
    assert "--live-temporal" in command
    assert "--workflow-id" in command
    assert "wf-1" in command
    assert command.count("--source-ref") == 2
    assert "--execute-codex-worker" in command
    assert "--codex-worker-task-id" in command
    assert "wf-1.source-bound.codex-worker" in command
    assert "--codex-worker-prompt" in command
    prompt = command[command.index("--codex-worker-prompt") + 1]
    assert "durable default chain" in prompt
    assert "RESULT_XINAO_TASK_BOUND_CODEX_WORKER_OK" in prompt
    assert "package.txt" in prompt
    assert "--human-egress-route" in command
    assert "grok_report_only" in command
    assert "--segment-boundary-headless" in command
    assert "--phase4-skip-codex-exec-canary" in command
    assert "--phase4-skip-qwen-canary" in command
