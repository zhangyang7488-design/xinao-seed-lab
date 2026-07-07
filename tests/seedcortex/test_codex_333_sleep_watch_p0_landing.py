from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.agent_runtime import codex_333_sleep_watch_p0_landing as landing

WORKFLOW_ID = "333-sleep-watch-source-package-20260705-r1"
RUN_ID = "019f32eb-46fa-7d94-9234-39904a68d914"
WAVE_ID = "333-sleep-watch-source-package-20260705-r1-wave-03-parallel_draft_batch_bind"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def provider_record(provider_id: str, *, mode: str, invocation_id: str) -> dict[str, Any]:
    if provider_id == "qwen_prepaid_cheap_worker":
        return {
            "provider_payload": {
                "provider_id": provider_id,
                "selected_carrier_provider_id": provider_id,
                "mode": mode,
                "invocation_id": invocation_id,
                "provider_invocation_performed": True,
                "model_invocation_performed": True,
                "local_stub": False,
                "raw_response_ref": f"raw/{invocation_id}.json",
                "usage": {"total_tokens": 10},
            }
        }
    return {
        "provider_id": provider_id,
        "selected_carrier_provider_id": provider_id,
        "mode": mode,
        "invocation_id": invocation_id,
        "provider_invocation_performed": True,
        "model_invocation_performed": True,
        "local_stub": False,
        "raw_response_ref": f"raw/{invocation_id}.json",
        "usage": {"total_tokens": 10},
    }


def setup_runtime(tmp_path: Path) -> tuple[Path, Path, list[Path], Path, Path, Path]:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    source_root = tmp_path / "source"
    source_files = []
    for index, name in enumerate(
        [
            "333_DEFAULT_CHAIN_EVOLUTION_QWEN_DP_AUDIT_20260705.txt",
            "333_DEFAULT_CHAIN_GLOBAL_REPAIR_PACKAGE_20260705.txt",
            "333_GLOBAL_CAPABILITY_ISLAND_INVENTORY_QWEN_DP_20260705.txt",
            "333_S_HANDOFF_MERGED_LANDABLE_PACKAGE_QWEN_DP_20260705.txt",
            "GLOBAL_MAINCHAIN_CONFLICT_AUDIT_QWEN_DP_ONLY_20260705.txt",
        ],
        start=1,
    ):
        path = source_root / name
        write_text(path, f"source file {index}\nall read\n")
        source_files.append(path)
    foreground_watch = tmp_path / "foreground_watch.txt"
    max_mature = tmp_path / "max_mature.txt"
    write_text(foreground_watch, "watch semantics\n")
    write_text(max_mature, "mature component map\n")

    write_text(repo / "scripts" / "hardmode" / "Invoke-CodexSWorkerLane.ps1", "param()\n")
    write_text(repo / "services" / "agent_runtime" / "codex_s_direct_worker_lane.py", "# direct lane\n")
    write_text(
        repo / "services" / "agent_runtime" / "codex_333_task_transaction_control.py",
        "# task transaction control\n",
    )
    write_text(
        repo / "services" / "agent_runtime" / "codex_333_stateful_continuity_router.py",
        "# stateful continuity router\n",
    )
    write_text(repo / "src" / "xinao_seedlab" / "cli" / "__main__.py", "# cli\n")
    write_text(repo / "services" / "mcp" / "xinao_mcp_server.py", "# mcp\n")

    write_json(
        runtime / "state" / "worker_assignment" / "xinao_seed_cortex_phase0_20260701.json",
        {
            "explicit_work_package_lane_ids": landing.CRITICAL_P0_LANE_IDS,
            "work_package_next_ready_node_id": landing.NODE_ID,
        },
    )
    write_json(
        runtime / "state" / "default_auto_dispatch" / "latest.json",
        {
            "status": "auto_dispatch_ingress_enqueued",
            "workflow_id": WORKFLOW_ID,
            "workflow_run_id": RUN_ID,
            "wave_id": WAVE_ID,
            "next_wave_id": f"{WORKFLOW_ID}-wave-04-parallel_draft_batch_bind",
            "current_wave_index": 3,
            "runtime_enforced": True,
        },
    )
    dispatch_entries = []
    lane_specs = [
        ("333-sw-p0-current-run-index", "qwen_prepaid_cheap_worker", "draft"),
        ("333-sw-p0-toolregistry-index", "qwen_prepaid_cheap_worker", "extraction"),
        ("333-sw-p0-provider-realness-gate", "legacy.deepseek_dp_sidecar", "contradiction"),
        ("333-sw-p0-dynamic-width-evidence", "qwen_prepaid_cheap_worker", "eval"),
        ("333-sw-p0-capability-absorption", "legacy.deepseek_dp_sidecar", "audit"),
    ]
    for lane_id, provider_id, mode in lane_specs:
        record_root = (
            runtime / "state" / "modular_dynamic_worker_pool_phase1" / "qwen_worker_invocation" / "records"
            if provider_id == "qwen_prepaid_cheap_worker"
            else runtime / "state" / "dp_sidecar_execution_provider" / "records"
        )
        record_path = record_root / f"{lane_id}.json"
        write_json(record_path, provider_record(provider_id, mode=mode, invocation_id=lane_id))
        dispatch_entries.append(
            {
                "entry_id": f"{WAVE_ID}:phase1-lane-{lane_id}",
                "wave_id": WAVE_ID,
                "lane_id": f"phase1-lane-{lane_id}",
                "provider": provider_id,
                "mode": mode,
                "poll_status": "succeeded",
                "artifact_refs": [str(record_path)],
            }
        )
    write_json(
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
        {
            "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
            "wave_id": WAVE_ID,
            "succeeded_count": 5,
            "dispatch_entries": dispatch_entries,
            "summary": {"entry_count": 5},
            "phase1_binding": {
                "workflow_id": WORKFLOW_ID,
                "workflow_run_id": RUN_ID,
                "ledger_succeeded_matches_completed": True,
                "actual_completed_width": 5,
            },
        },
    )
    write_json(
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        {
            "status": "artifact_acceptance_queue_ready",
            "episode_id": f"episode-{WAVE_ID}",
            "accepted_artifact_count": 1,
            "unique_accepted_artifact_count": 1,
            "completion_claim_allowed": False,
            "decisions": [
                {
                    "workflow_id": WORKFLOW_ID,
                    "workflow_run_id": RUN_ID,
                    "status": "accepted",
                    "artifact_ref": "artifact.md",
                }
            ],
        },
    )
    write_json(
        runtime / "state" / "dynamic_width_policy" / "latest.json",
        {
            "target_width": 5,
            "requested_target_width": 5,
            "actual_dispatched_width": 5,
            "actual_completed_width": 5,
            "target_width_source": "explicit_assignment_dag_work_package",
            "width_decision_reason": "test",
            "width_decision_inputs": {"explicit_lane_count": 5},
            "recomputed_each_wave": True,
            "fixed_width_literal_used": False,
            "operator_cap_applied": False,
            "wave_id": WAVE_ID,
        },
    )
    write_json(
        runtime / "state" / "capability_gateway" / "latest.json",
        {"status": "capability_gateway_snapshot_ready", "providers": []},
    )
    write_json(
        runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json",
        {
            "schema_version": "xinao.codex_s.default_main_loop_trigger_candidate.v1",
            "status": "default_main_loop_trigger_task_scoped_runtime_enforced",
            "runtime_enforced": True,
            "runtime_enforced_scope": "seed_cortex_default_main_loop_trigger_qwen_dp_worker_pool",
            "no_stop_wave_consumption_refs": {
                "ready": True,
                "refs_are_not_execution_controllers": True,
            },
            "validation": {
                "passed": True,
                "checks": {
                    "current_333_run_index_consumed_by_default_trigger": True,
                    "tool_registry_consumed_by_default_trigger": True,
                    "no_stop_wave_consumption_refs_bound": True,
                },
            },
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_execution_controller": True,
        },
    )
    write_json(
        runtime / "capabilities" / "codex_s.provider_scheduler" / "manifest.json",
        {
            "provider_id": "codex_s.provider_scheduler",
            "capability_kinds": ["provider_scheduler"],
            "validation": {"passed": True},
            "runtime_enforced": False,
        },
    )
    official = tmp_path / "external" / "official" / "temporalio__temporal"
    official.mkdir(parents=True)
    return runtime, repo, source_files, foreground_watch, max_mature, tmp_path / "external"


def test_temporal_describe_parser_separates_workflow_and_pending_activity_type() -> None:
    parsed = landing._parse_temporal_describe(
        """
Execution Info:
  WorkflowId            333-sleep-watch-source-package-20260705-r1
  RunId                 019f32eb-46fa-7d94-9234-39904a68d914
  Type                  TemporalCodexTaskWorkflow
  TaskQueue             xinao-codex-task-default
  StateTransitionCount  424
  HistoryLength         667

Pending Activities: 1

  ActivityId          103
  Type                codex_worker_turn_activity
  State               Started

Pending Child Workflows: 0
""",
    )

    assert parsed["workflow_type"] == "TemporalCodexTaskWorkflow"
    assert parsed["pending_activity_count"] == 1
    assert parsed["pending_activity_types"] == ["codex_worker_turn_activity"]


def test_provider_realness_gate_prefers_selected_carrier_over_preferred_provider(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    lane_bindings = []
    for lane_id, preferred_provider, mode in [
        ("333-sw-p0-current-run-index", "qwen_prepaid_cheap_worker", "draft"),
        ("333-sw-p0-toolregistry-index", "qwen_prepaid_cheap_worker", "extraction"),
        ("333-sw-p0-provider-realness-gate", "legacy.deepseek_dp_sidecar", "contradiction"),
        ("333-sw-p0-dynamic-width-evidence", "qwen_prepaid_cheap_worker", "eval"),
        ("333-sw-p0-capability-absorption", "legacy.deepseek_dp_sidecar", "audit"),
    ]:
        write_json(
            runtime / "state" / "dp_sidecar_execution_provider" / "records" / f"{lane_id}.json",
            provider_record("legacy.deepseek_dp_sidecar", mode=mode, invocation_id=lane_id),
        )
        lane_bindings.append(
            {
                "lane_id": lane_id,
                "source_wave_id": WAVE_ID,
                "mode": mode,
                "preferred_provider_id": preferred_provider,
                "selected_carrier_provider_id": "legacy.deepseek_dp_sidecar",
                "status": "succeeded",
                "artifact_ref": str(
                    runtime
                    / "state"
                    / "dp_sidecar_execution_provider"
                    / "results"
                    / f"{lane_id}.{mode}.json"
                ),
                "outputs_to_staging_only": True,
                "direct_repo_write_allowed": False,
                "artifact_acceptance_required": True,
                "not_execution_controller": True,
            }
        )

    gate = landing.build_provider_realness_gate(
        runtime=runtime,
        current_index={
            "workflow_scoped_evidence": {
                "wave_id": WAVE_ID,
                "lane_bindings": lane_bindings,
            }
        },
    )

    assert gate["status"] == "provider_realness_gate_ready"
    assert gate["validation"]["passed"] is True
    assert {
        result["record"]["selected_carrier_provider_id"]
        for result in gate["critical_results"]
    } == {"legacy.deepseek_dp_sidecar"}


def test_333_sleep_watch_p0_landing_writes_index_registry_and_gates(tmp_path: Path) -> None:
    runtime, repo, source_files, foreground_watch, max_mature, external = setup_runtime(tmp_path)
    payload = landing.build(
        runtime_root=runtime,
        repo_root=repo,
        workflow_id=WORKFLOW_ID,
        source_files=source_files,
        foreground_watch_ref=foreground_watch,
        max_mature_component_ref=max_mature,
        external_mature_root=external,
        temporal_probe_override={
            "address": "127.0.0.1:7233",
            "port_open": True,
            "workflow_id": WORKFLOW_ID,
            "workflow_run_id": RUN_ID,
            "status": "Running",
            "task_queue": "xinao-codex-task-default",
            "workflow_type": "TemporalCodexTaskWorkflow",
            "history_length": 451,
            "state_transition_count": 280,
            "pending_activity_count": 1,
            "pending_activity_types": ["codex_worker_turn_activity"],
            "describe_returncode": 0,
            "list_returncode": 0,
            "named_blocker": "",
        },
    )

    assert payload["validation"]["passed"] is True
    assert payload["source_package"]["five_text_files_read"] is True
    assert payload["source_package"]["max_mature_component_ref"]["read_in_full"] is True
    assert payload["source_package"]["max_mature_component_resolution"]["fallback_used"] is False
    assert payload["completion_claim_allowed"] is False
    assert payload["current_333_run_index"]["reconciliation"]["reconciled"] is True
    assert payload["default_mainline_hardened"] is True
    assert payload["missing_binding"] == ""
    assert payload["default_mainline_binding"]["hardened"] is True
    assert payload["validation"]["checks"]["default_mainline_consumes_current_index_and_tool_registry"] is True

    registry_path = Path(payload["output_paths"]["tool_registry"])
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for provider_id in landing.REQUIRED_TOOL_REGISTRY_IDS:
        assert provider_id in registry["provider_ids"]
    assert registry["validation"]["checks"]["legacy_freeze_manifest_exposed"] is True
    assert registry["validation"]["checks"]["control_vs_evidence_boundary_contract_exposed"] is True
    continuity = [
        provider
        for provider in registry["providers"]
        if provider["provider_id"] == "codex_s.333_stateful_continuity_router"
    ][0]
    assert "forbidden_narrowing" in continuity["capability_kinds"]
    assert continuity["five_layer_status"]["connected_to_333"] == (
        "source_package_intent_continuity_read_model"
    )
    control_boundary = [
        provider
        for provider in registry["providers"]
        if provider["provider_id"] == "codex_s.333_control_vs_evidence_boundary_contract"
    ][0]
    assert "latest_json_not_authority" in control_boundary["capability_kinds"]
    assert control_boundary["five_layer_status"]["connected_to_333"] == (
        "default_trigger_no_stop_refs_and_continuity_read_model"
    )
    task_control = [
        provider
        for provider in registry["providers"]
        if provider["provider_id"] == "codex_s.333_task_transaction_control"
    ][0]
    assert "pause_after_current_wave" in task_control["capability_kinds"]
    assert task_control["five_layer_status"]["connected_to_333"] == (
        "current_workflow_task_control_signal"
    )

    realness = payload["provider_realness_gate"]
    assert realness["validation"]["checks"]["critical_lanes_model_invoked"] is True
    assert realness["validation"]["checks"]["critical_lanes_not_local_stub"] is True
    assert realness["validation"]["checks"]["local_stub_fixture_rejected"] is True
    assert realness["validation"]["checks"]["model_false_fixture_rejected"] is True

    widths = payload["dynamic_width_evidence"]["widths"]
    assert widths["configured_width"] == 5
    assert widths["requested_width"] == 5
    assert widths["dispatched_width"] == 5
    assert widths["completed_width"] == 5
    assert widths["unique_accepted_artifact_count"] == 1

    pipeline = payload["capability_absorption_pipeline"]
    assert pipeline["report_only_inventory"] is False
    assert pipeline["candidate_count"] >= 1
    assert set(pipeline["candidates"][0]["absorption_state"]) == {
        "candidate",
        "smoke",
        "policy",
        "thin_bind",
        "333",
        "AAQ",
    }

    task_bound = payload["task_bound_jsonl_evidence"]
    assert task_bound["status"] == "assignment_dag_node_evidence_written"
    assert task_bound["validation"]["passed"] is True
    jsonl_path = Path(task_bound["jsonl_ref"])
    assert jsonl_path.is_file()
    last_line = jsonl_path.read_text(encoding="utf-8").splitlines()[-1]
    jsonl_record = json.loads(last_line)
    assert jsonl_record["task_id"] == landing.WORK_ID
    assert jsonl_record["node_id"] == landing.NODE_ID
    assert jsonl_record["workflow_id"] == WORKFLOW_ID
    assert jsonl_record["workflow_run_id"] == RUN_ID
    assert jsonl_record["completion_claim_allowed"] is False


def test_333_sleep_watch_p0_landing_prefers_workflow_scoped_evidence_over_stale_latest(
    tmp_path: Path,
) -> None:
    runtime, repo, source_files, foreground_watch, max_mature, external = setup_runtime(tmp_path)
    lane_bindings = []
    for lane_id, provider_id, mode in [
        ("333-sw-p0-current-run-index", "qwen_prepaid_cheap_worker", "draft"),
        ("333-sw-p0-toolregistry-index", "qwen_prepaid_cheap_worker", "extraction"),
        ("333-sw-p0-provider-realness-gate", "legacy.deepseek_dp_sidecar", "contradiction"),
        ("333-sw-p0-dynamic-width-evidence", "qwen_prepaid_cheap_worker", "eval"),
        ("333-sw-p0-capability-absorption", "legacy.deepseek_dp_sidecar", "audit"),
    ]:
        artifact_root = (
            runtime / "state" / "modular_dynamic_worker_pool_phase1" / "qwen_worker_invocation" / "artifacts"
            if provider_id == "qwen_prepaid_cheap_worker"
            else runtime / "state" / "dp_sidecar_execution_provider" / "results"
        )
        artifact_ref = artifact_root / f"{lane_id}.{mode}.json"
        write_json(artifact_ref, {"lane_id": lane_id, "mode": mode})
        lane_bindings.append(
            {
                "lane_id": lane_id,
                "source_wave_id": WAVE_ID,
                "mode": mode,
                "preferred_provider_id": provider_id,
                "status": "succeeded",
                "artifact_ref": str(artifact_ref),
                "outputs_to_staging_only": True,
                "direct_repo_write_allowed": False,
                "artifact_acceptance_required": True,
                "not_execution_controller": True,
            }
        )

    workflow_dir = (
        runtime
        / "state"
        / "task_bound_evidence"
        / landing.WORK_ID
        / "assignment_dag"
        / "workflow_runs"
        / WORKFLOW_ID
        / RUN_ID
    )
    write_json(
        workflow_dir / f"{landing.NODE_ID}.latest.json",
        {
            "status": "assignment_dag_node_evidence_written",
            "workflow_id": WORKFLOW_ID,
            "workflow_run_id": RUN_ID,
            "wave_id": WAVE_ID,
            "assignment_dag_node_id": landing.NODE_ID,
            "lane_count": 5,
            "lane_bindings": lane_bindings,
            "completion_claim_allowed": False,
        },
    )
    write_json(
        runtime
        / "state"
        / "modular_dynamic_worker_pool_phase1"
        / "fan_in_staging_merge_spend"
        / "workflow_runs"
        / WORKFLOW_ID
        / RUN_ID
        / "latest.json",
        {
            "status": "fan_in_staging_merge_spend_ready",
            "workflow_id": WORKFLOW_ID,
            "workflow_run_id": RUN_ID,
            "wave_id": WAVE_ID,
            "staged_count": 1,
            "merged_count": 1,
            "spend_entry_count": 5,
            "accepted_artifact_count": 1,
            "unique_accepted_artifact_count": 1,
            "completion_claim_allowed": False,
        },
    )
    write_json(
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
        {
            "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
            "wave_id": "stale-other-wave",
            "succeeded_count": 0,
            "phase1_binding": {
                "workflow_id": "stale-other-workflow",
                "workflow_run_id": "stale-other-run",
                "ledger_succeeded_matches_completed": False,
            },
        },
    )
    write_json(
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        {
            "status": "artifact_acceptance_queue_ready",
            "episode_id": "stale-other-wave",
            "accepted_artifact_count": 10,
            "unique_accepted_artifact_count": 10,
            "completion_claim_allowed": False,
            "decisions": [{"workflow_id": "stale-other-workflow", "workflow_run_id": "stale-other-run"}],
        },
    )

    payload = landing.build(
        runtime_root=runtime,
        repo_root=repo,
        workflow_id=WORKFLOW_ID,
        source_files=source_files,
        foreground_watch_ref=foreground_watch,
        max_mature_component_ref=max_mature,
        external_mature_root=external,
        temporal_probe_override={
            "address": "127.0.0.1:7233",
            "port_open": True,
            "workflow_id": WORKFLOW_ID,
            "workflow_run_id": RUN_ID,
            "status": "Running",
            "task_queue": "xinao-codex-task-default",
            "workflow_type": "TemporalCodexTaskWorkflow",
            "history_length": 451,
            "state_transition_count": 280,
            "pending_activity_count": 1,
            "pending_activity_types": ["codex_worker_turn_activity"],
            "describe_returncode": 0,
            "list_returncode": 0,
            "named_blocker": "",
        },
    )

    current = payload["current_333_run_index"]
    assert payload["validation"]["passed"] is True
    assert current["reconciliation"]["reconciled"] is True
    assert current["reconciliation"]["latest_alias_used"] is False
    assert current["workflow_scoped_evidence"]["ready"] is True
    assert current["worker_dispatch_ledger"]["wave_id"] == WAVE_ID
    assert current["worker_dispatch_ledger"]["succeeded_count"] == 5
    assert current["artifact_acceptance_queue"]["unique_accepted_artifact_count"] == 1


def test_333_sleep_watch_p0_landing_writes_task_bound_evidence_with_default_blocker(
    tmp_path: Path,
) -> None:
    runtime, repo, source_files, foreground_watch, max_mature, external = setup_runtime(tmp_path)
    write_json(
        runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json",
        {
            "schema_version": "xinao.codex_s.default_main_loop_trigger_candidate.v1",
            "status": "default_main_loop_trigger_candidate_blocked",
            "runtime_enforced": False,
            "no_stop_wave_consumption_refs": {
                "ready": False,
                "refs_are_not_execution_controllers": True,
            },
            "validation": {
                "passed": False,
                "checks": {
                    "current_333_run_index_consumed_by_default_trigger": False,
                    "tool_registry_consumed_by_default_trigger": False,
                    "no_stop_wave_consumption_refs_bound": False,
                },
            },
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_execution_controller": True,
        },
    )

    payload = landing.build(
        runtime_root=runtime,
        repo_root=repo,
        workflow_id=WORKFLOW_ID,
        source_files=source_files,
        foreground_watch_ref=foreground_watch,
        max_mature_component_ref=max_mature,
        external_mature_root=external,
        temporal_probe_override={
            "address": "127.0.0.1:7233",
            "port_open": True,
            "workflow_id": WORKFLOW_ID,
            "workflow_run_id": RUN_ID,
            "status": "Running",
            "task_queue": "xinao-codex-task-default",
            "workflow_type": "TemporalCodexTaskWorkflow",
            "history_length": 451,
            "state_transition_count": 280,
            "pending_activity_count": 1,
            "pending_activity_types": ["codex_worker_turn_activity"],
            "describe_returncode": 0,
            "list_returncode": 0,
            "named_blocker": "",
        },
    )

    assert payload["validation"]["passed"] is True
    assert payload["status"] == (
        "333_sleep_watch_p0_landing_evidence_written_default_mainline_blocked"
    )
    assert payload["default_mainline_hardened"] is False
    assert payload["named_blocker"] == (
        "DEFAULT_MAINLINE_CURRENT_INDEX_TOOLREGISTRY_CONSUMPTION_NOT_PROVEN"
    )
    assert payload["missing_binding"]
    assert payload["next_machine_action"]
    assert (
        payload["validation"]["checks"][
            "default_mainline_consumes_current_index_and_tool_registry"
        ]
        is False
    )
    assert payload["validation"]["checks"]["default_mainline_hardened_or_named_blocker"] is True

    task_bound = payload["task_bound_jsonl_evidence"]
    assert task_bound["status"] == "assignment_dag_node_evidence_written"
    assert task_bound["validation"]["passed"] is True
    assert task_bound["phase_boundary_ready"] is False
    assert task_bound["default_mainline_hardened"] is False
    assert task_bound["named_blocker"] == payload["named_blocker"]
    assert task_bound["completion_claim_allowed"] is False


def test_333_sleep_watch_p0_landing_accepts_root_driver_task_scoped_enforcement(
    tmp_path: Path,
) -> None:
    runtime, repo, source_files, foreground_watch, max_mature, external = setup_runtime(tmp_path)
    write_json(
        runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json",
        {
            "schema_version": "xinao.codex_s.default_main_loop_trigger_candidate.v1",
            "status": "default_main_loop_trigger_candidate_verifier_ready",
            "runtime_enforced": False,
            "runtime_enforced_scope": "",
            "no_stop_wave_consumption_refs": {
                "ready": True,
                "refs_are_not_execution_controllers": True,
            },
            "validation": {
                "passed": True,
                "checks": {
                    "current_333_run_index_consumed_by_default_trigger": True,
                    "tool_registry_consumed_by_default_trigger": True,
                    "no_stop_wave_consumption_refs_bound": True,
                },
            },
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_execution_controller": True,
        },
    )
    write_json(
        runtime / "state" / "root_intent_loop_driver" / "latest.json",
        {
            "schema_version": "xinao.codex_s.root_intent_loop_driver.v1",
            "status": "root_intent_loop_driver_runtime_enforced",
            "runtime_enforced": True,
            "default_trigger_enforcement": {
                "runtime_enforced": True,
                "trigger_enforced": True,
            },
            "validation": {
                "passed": True,
                "checks": {
                    "default_trigger_enforced_for_task": True,
                    "scheduler_default_runtime_enforced": True,
                },
            },
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )

    payload = landing.build(
        runtime_root=runtime,
        repo_root=repo,
        workflow_id=WORKFLOW_ID,
        source_files=source_files,
        foreground_watch_ref=foreground_watch,
        max_mature_component_ref=max_mature,
        external_mature_root=external,
        temporal_probe_override={
            "address": "127.0.0.1:7233",
            "port_open": True,
            "workflow_id": WORKFLOW_ID,
            "workflow_run_id": RUN_ID,
            "status": "Running",
            "task_queue": "xinao-codex-task-default",
            "workflow_type": "TemporalCodexTaskWorkflow",
            "history_length": 451,
            "state_transition_count": 280,
            "pending_activity_count": 1,
            "pending_activity_types": ["codex_worker_turn_activity"],
            "describe_returncode": 0,
            "list_returncode": 0,
            "named_blocker": "",
        },
    )

    assert payload["validation"]["passed"] is True
    assert payload["default_mainline_hardened"] is True
    assert payload["default_mainline_binding"]["runtime_enforcement_source"] == (
        "root_intent_loop_driver.default_trigger_enforcement"
    )
    assert payload["default_mainline_binding"]["root_driver_runtime_enforced"] is True
    assert (
        payload["validation"]["checks"][
            "default_mainline_consumes_current_index_and_tool_registry"
        ]
        is True
    )


def test_max_mature_component_requested_path_falls_back_without_silent_alias(
    tmp_path: Path,
) -> None:
    requested = tmp_path / "Desktop" / "最大成熟组件能力最大化.txt"
    fallback = tmp_path / "Desktop" / "旧系统" / "最大成熟组件能力最大化.txt"
    write_text(fallback, "mature fallback map\n")

    source = landing.build_source_package(
        source_files=[],
        foreground_watch_ref=tmp_path / "watch.txt",
        max_mature_ref=requested,
        max_mature_fallback_refs=(fallback,),
    )

    assert source["max_mature_component_requested_ref"]["exists"] is False
    assert source["max_mature_component_ref"]["path"] == str(fallback)
    assert source["max_mature_component_ref"]["read_in_full"] is True
    assert source["max_mature_component_resolution"] == {
        "requested_path": str(requested),
        "resolved_path": str(fallback),
        "requested_exists": False,
        "fallback_used": True,
        "named_blocker": "",
    }
