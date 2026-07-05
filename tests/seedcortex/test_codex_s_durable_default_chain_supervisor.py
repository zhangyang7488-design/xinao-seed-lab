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


def test_dispatch_success_without_materialized_closure_is_not_progress(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    source_root = tmp_path / "source"
    repo.mkdir(parents=True, exist_ok=True)
    package = _write_source_tree(source_root)
    dispatch_gate = module.build_dispatch_gate(
        no_dispatch=False,
        interval_dispatch_due=True,
        prior_autonomous_dispatch_count=0,
        max_autonomous_dispatches=1,
        allow_evidence_only_dispatch=False,
        hard_acceptance=module.hard_acceptance_evidence(runtime),
    )

    payload = module.build_cycle_record(
        runtime=runtime,
        repo=repo,
        source_root=source_root,
        package_path=package,
        supervisor_wave_id="durable-supervisor-test-wave",
        parent_wave_id="parent-wave",
        cycle_index=1,
        poll_seconds=1,
        task_queue="test-task-queue",
        dispatch_result={"dispatch_attempted": True, "succeeded": True, "workflow_id": "wf-1"},
        dispatch_gate=dispatch_gate,
        no_dispatch=False,
    )

    progress = payload["progress_self_evolution"]["progress_ledger"]
    assert progress["artifact_delta_count"] == 0
    assert progress["AAQ_accepted_delta"] == 0
    assert progress["default_invoke_delta"] == 0
    assert progress["no_progress_reason"] == "supervisor_dispatch_success_without_materialized_artifact"
    assert payload["heartbeat"]["new_delta_count"] == 0
    assert payload["heartbeat"]["accepted_delta"] == 0
    assert payload["heartbeat"]["dispatch_success_is_materialized_progress"] is False
    assert payload["heartbeat"]["materialized_progress"] is False


def test_source_workerpool_materialization_rejects_synthetic_bounded_item(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    latest = runtime / "state" / "source_frontier_workerpool_closure" / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.v1",
                "status": "source_frontier_workerpool_closure_ready",
                "wave_id": "closure-wave",
                "source_batch_ids": ["bounded-current-source-delta-deadbeef"],
                "primary_source_batch_id": "bounded-current-source-delta-deadbeef",
                "merge": {"merge_artifact": "merged.md", "merged_count": 1},
                "artifact_acceptance_queue": {"accepted_artifact_count": 1},
                "provider_materialization": {
                    "qwen_or_deepseek_real_model_invoked": True,
                    "external_draft_model_invoked": True,
                    "real_worker_model_invocation_count": 1,
                    "qwen_real_model_invocation_count": 1,
                    "deepseek_dp_real_model_invocation_count": 0,
                    "external_cheap_draft_count": 1,
                    "local_stub_as_completion_attempted": False,
                    "spend_ledger_real_provider_entry_count": 1,
                },
                "next_frontier": {
                    "validation": {"passed": True},
                    "should_continue_loop": True,
                    "next_frontier_real_work_count": 1,
                },
                "completion_claim_allowed": False,
                "validation": {"passed": True},
            }
        ),
        encoding="utf-8",
    )

    evidence = module.source_workerpool_materialization_evidence(runtime)

    assert evidence["satisfied"] is False
    assert evidence["synthetic_item_used"] is True
    assert evidence["checks"]["synthetic_item_not_used"] is False
    assert evidence["artifact_delta_count"] == 0


def test_source_workerpool_materialization_rejects_local_stub_only_closure(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    latest = runtime / "state" / "source_frontier_workerpool_closure" / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.v1",
                "status": "source_frontier_workerpool_closure_ready",
                "wave_id": "closure-wave",
                "source_batch_ids": ["source-batch-real-001"],
                "primary_source_batch_id": "source-batch-real-001",
                "primary_worker_brief_id": "worker-brief-001",
                "merge": {"merge_artifact": "merged.md", "merged_count": 1},
                "artifact_acceptance_queue": {"accepted_artifact_count": 1},
                "provider_materialization": {
                    "qwen_or_deepseek_real_model_invoked": False,
                    "external_draft_model_invoked": False,
                    "real_worker_model_invocation_count": 0,
                    "qwen_real_model_invocation_count": 0,
                    "deepseek_dp_real_model_invocation_count": 0,
                    "external_cheap_draft_count": 0,
                    "local_stub_count": 2,
                    "local_stub_draft_count": 1,
                    "local_stub_as_completion_attempted": True,
                    "spend_ledger_real_provider_entry_count": 0,
                },
                "next_frontier": {
                    "validation": {"passed": True},
                    "should_continue_loop": True,
                    "next_frontier_real_work_count": 1,
                    "synthetic_item_used": False,
                },
                "completion_claim_allowed": False,
                "validation": {"passed": True},
            }
        ),
        encoding="utf-8",
    )

    evidence = module.source_workerpool_materialization_evidence(runtime)

    assert evidence["satisfied"] is False
    assert evidence["checks"]["real_qwen_or_deepseek_model_invoked"] is False
    assert evidence["checks"]["real_qwen_model_invoked"] is False
    assert evidence["checks"]["real_deepseek_dp_model_invoked"] is False
    assert evidence["checks"]["local_stub_not_used_as_completion"] is False
    assert evidence["artifact_delta_count"] == 0


def test_source_workerpool_materialization_counts_real_merge_aaq_next_frontier(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    latest = runtime / "state" / "source_frontier_workerpool_closure" / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.v1",
                "status": "source_frontier_workerpool_closure_ready",
                "wave_id": "closure-wave",
                "source_batch_ids": ["source-batch-real-001"],
                "primary_source_batch_id": "source-batch-real-001",
                "primary_worker_brief_id": "worker-brief-001",
                "merge": {"merge_artifact": "merged.md", "merged_count": 1},
                "artifact_acceptance_queue": {"accepted_artifact_count": 1},
                "provider_materialization": {
                    "qwen_or_deepseek_real_model_invoked": True,
                    "qwen_real_model_invoked": True,
                    "deepseek_dp_real_model_invoked": True,
                    "qwen_and_deepseek_real_model_invoked": True,
                    "external_draft_model_invoked": True,
                    "real_worker_model_invocation_count": 2,
                    "qwen_real_model_invocation_count": 1,
                    "deepseek_dp_real_model_invocation_count": 1,
                    "external_cheap_draft_count": 1,
                    "local_stub_as_completion_attempted": False,
                    "spend_ledger_real_provider_entry_count": 1,
                },
                "next_frontier": {
                    "validation": {"passed": True},
                    "should_continue_loop": True,
                    "next_frontier_real_work_count": 1,
                    "synthetic_item_used": False,
                },
                "output_paths": {
                    "aaq": "aaq.json",
                    "merge": "merge.json",
                    "next_frontier": "next_frontier.json",
                },
                "completion_claim_allowed": False,
                "validation": {"passed": True},
            }
        ),
        encoding="utf-8",
    )

    evidence = module.source_workerpool_materialization_evidence(runtime)
    hard = module.hard_acceptance_evidence(runtime)

    assert evidence["satisfied"] is True
    assert evidence["artifact_delta_count"] == 1
    assert evidence["aaq_accepted_count"] == 1
    assert evidence["merge_artifact_refs"] == ["merged.md"]
    assert evidence["real_worker_model_invocation_count"] == 2
    assert evidence["qwen_real_model_invocation_count"] == 1
    assert evidence["deepseek_dp_real_model_invocation_count"] == 1
    assert hard["satisfied"] is True
    assert hard["selected_evidence_kind"] == "source_frontier_workerpool_closure"


def test_supervisor_recognizes_hard_acceptance_before_requiring_new_wave(tmp_path: Path) -> None:
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
    evidence = runtime / "state" / "total_source_episode_entry" / "latest.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(
            {
                "wave_id": "total-source-episode-entry-20260705",
                "theme_family": "episode_entry",
                "can_invoke_now": {"capability": "codex_s.total_source_episode_entry"},
                "artifact_acceptance_queue": {"accepted_artifact_count": 1},
                "next_frontier": {"validation": {"passed": True}},
                "output_paths": {
                    "aaq_latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
                    "next_frontier_latest": str(runtime / "state" / "total_source_episode_entry" / "next_frontier" / "latest.json"),
                },
                "completion_claim_allowed": False,
                "validation": {"passed": True},
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

    gate = payload["dispatch_supervision"]["hard_acceptance_dispatch_gate"]
    assert payload["dispatch_supervision"]["dispatch_attempted_this_cycle"] is False
    assert gate["status"] == "dispatch_blocked_new_supervisor_wave_required_after_hard_acceptance"
    assert gate["hard_acceptance_required"] is False
    assert gate["hard_acceptance_satisfied"] is True
    assert gate["hard_acceptance_evidence"]["satisfied"] is True
    assert any(
        item["blocker_name"] == "NEW_SUPERVISOR_WAVE_REQUIRED_AFTER_HARD_ACCEPTANCE"
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
