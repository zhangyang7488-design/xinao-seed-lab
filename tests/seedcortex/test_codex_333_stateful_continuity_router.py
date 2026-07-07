import json
from pathlib import Path

from services.agent_runtime import codex_333_stateful_continuity_router as module

from xinao_seedlab.cli.__main__ import main as cli_main


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _source_files(root: Path) -> list[Path]:
    names = [
        "01_总说明_本项目是什么_20260707.txt",
        "02_P0_底座全自动任务落地_20260707.txt",
        "03_P1_任务落地_20260707.txt",
    ]
    files = []
    for index, name in enumerate(names, start=1):
        path = root / name
        body = [
            f"source {index}",
            "TEMPORAL_SERVER_NOT_RUNNING",
            "r7 已完成",
            "ClaimCard GAA-P0-003: Prompt continuity 是假连续性",
            "应落地工件:",
            "stateful_continuity_router.v1",
            "禁止 把 Qwen/DP 当主链",
        ]
        _write_text(path, "\n".join(body) + "\n")
        files.append(path)
    return files


def _seed_runtime(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "status": "current_333_run_index_ready",
            "workflow_id": "unit-workflow",
            "workflow_run_id": "unit-run",
            "current_state": "running",
            "reconciliation": {"reconciled": True},
            "temporal": {
                "server_bound_visibility_list": True,
                "selected_workflow": {"status": "WORKFLOW_EXECUTION_STATUS_RUNNING"},
                "pending_activity_count": 1,
            },
            "control_plane_liveness": {"temporal_server_port_open": True},
        },
    )
    _write_json(
        runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json",
        {
            "status": "s_tool_registry_ready",
            "provider_ids": [
                "codex_s.333_task_transaction_control",
                "qwen_prepaid_cheap_worker",
                "legacy.deepseek_dp_sidecar",
            ],
        },
    )
    _write_json(
        runtime / "state" / "codex_333_task_transaction_control" / "latest.json",
        {"status": "codex_333_task_transaction_control_ready", "validation": {"passed": True}},
    )
    _write_json(
        runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json",
        {
            "status": "default_main_loop_trigger_task_scoped_runtime_enforced",
            "trigger_truth_chain": {"ready": True},
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json",
        {
            "status": "modular_dynamic_worker_pool_phase1_wave_merged",
            "target_width_source": "dynamic_width_scheduler",
            "actual_dispatched_width": 9,
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "dynamic_width_policy" / "latest.json",
        {
            "status": "dynamic_width_policy_ready",
            "target_width_source": "explicit_assignment_dag_work_package",
            "actual_dispatched_width": 9,
            "fixed_width_literal_used": False,
            "recomputed_each_wave": True,
        },
    )
    _write_json(
        runtime / "state" / "333_sleep_watch_p0_landing" / "latest.json",
        {
            "status": "333_sleep_watch_p0_landing_ready",
            "validation": {
                "passed": True,
                "checks": {"provider_realness_gate_rejects_fake": True},
            },
        },
    )


def test_stateful_continuity_router_reads_sources_and_classifies_claims(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    source_files = _source_files(tmp_path / "source")
    _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        source_files=source_files,
        write=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["source_package"]["file_count"] == 3
    assert payload["source_package"]["all_files_read_full"] is True
    assert payload["validation"]["checks"]["current_p0_three_text_default"] is True
    assert payload["current_user_intent_object"]["source_package_id"] == (
        "current_p0_three_text_20260707"
    )
    assert payload["current_user_intent_object"]["backend_transaction_required"] is True
    assert "三份 20260707 文本" in payload["current_user_intent_object"]["plain_zh"]
    assert "P0-1.current_333_run_index" in payload["accepted_claim_ids"]
    assert "P0-2.tool_registry_and_task_control" in payload["accepted_claim_ids"]
    assert "P0-5.dynamic_width_evidence" in payload["accepted_claim_ids"]
    assert any(
        item["claim_id"] == "stale.TEMPORAL_SERVER_NOT_RUNNING" for item in payload["stale_claims"]
    )
    assert payload["active_blockers"][0]["blocker_name"] == "BACKGROUND_ACTIVITY_RUNNING"
    assert payload["next_required_artifact"] == "host_dialogue_gate_trace.v1"
    assert Path(payload["output_paths"]["latest"]).is_file()
    assert Path(payload["output_paths"]["readback"]).is_file()


def test_cli_invokes_stateful_continuity_router(tmp_path: Path, capsys) -> None:
    runtime = tmp_path / "runtime"
    source_files = _source_files(tmp_path / "source")
    _seed_runtime(runtime)

    argv = [
        "333-stateful-continuity-router",
        "--runtime-root",
        str(runtime),
        "--repo-root",
        str(tmp_path / "repo"),
    ]
    for path in source_files:
        argv.extend(["--source-file", str(path)])

    exit_code = cli_main(argv)
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["validation"]["passed"] is True
    assert output["source_package"]["all_files_read_full"] is True


def test_stateful_continuity_router_advances_after_legacy_freeze(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    source_files = _source_files(tmp_path / "source")
    _seed_runtime(runtime)
    _write_json(
        runtime / "state" / "codex_333_host_dialogue_gate_trace" / "latest.json",
        {
            "status": "host_dialogue_gate_trace_ready",
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "codex_333_legacy_freeze_manifest" / "latest.json",
        {
            "status": "legacy_freeze_manifest_ready",
            "validation": {"passed": True},
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        source_files=source_files,
        write=False,
    )

    assert "P0.host_dialogue_gate_trace" in payload["accepted_claim_ids"]
    assert "P0.legacy_freeze_manifest" in payload["accepted_claim_ids"]
    assert "P0.legacy_reference_only_runtime_guard" in payload["accepted_claim_ids"]
    assert payload["next_required_artifact"] == "control_vs_evidence_boundary_contract.v1"


def test_stateful_continuity_router_advances_after_control_boundary(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    source_files = _source_files(tmp_path / "source")
    _seed_runtime(runtime)
    _write_json(
        runtime / "state" / "codex_333_host_dialogue_gate_trace" / "latest.json",
        {
            "status": "host_dialogue_gate_trace_ready",
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "codex_333_legacy_freeze_manifest" / "latest.json",
        {
            "status": "legacy_freeze_manifest_ready",
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "codex_333_control_vs_evidence_boundary_contract" / "latest.json",
        {
            "status": "control_vs_evidence_boundary_contract_ready",
            "validation": {"passed": True},
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        source_files=source_files,
        write=False,
    )

    assert "P0.control_vs_evidence_boundary_contract" in payload["accepted_claim_ids"]
    assert payload["next_required_artifact"] == "lane_lifecycle_metric_contract.v1"


def test_stateful_continuity_router_surfaces_current_index_named_blocker(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    source_files = _source_files(tmp_path / "source")
    _seed_runtime(runtime)
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "status": "current_333_run_index_blocked",
            "current_state": "blocked",
            "reconciliation": {"reconciled": False, "named_blocker": "TEMPORAL_WORKER_NOT_POLLING"},
            "temporal": {"server_bound_visibility_list": True},
            "control_plane_liveness": {
                "temporal_server_port_open": True,
                "named_blocker": "TEMPORAL_WORKER_NOT_POLLING",
            },
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        source_files=source_files,
        write=False,
    )

    assert payload["validation"]["checks"]["current_p0_three_text_default"] is True
    assert payload["active_blockers"][0]["blocker_name"] == "TEMPORAL_WORKER_NOT_POLLING"
