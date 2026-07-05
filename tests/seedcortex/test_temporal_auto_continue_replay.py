from services.agent_runtime.temporal_codex_task_workflow import (
    TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_VALUE_EVAL,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_SMOKE,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_FINAL_READMODEL_FLUSH,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_POST_CLOSURE_FLUSH,
    TemporalCodexTaskWorkflow,
    compact_activity_for_history,
    compact_phase3_activity_result,
    compact_temporal_history_result,
    embedded_workerbrief_bridge_activity_from_main_loop_tick,
    main_loop_tick_workerbrief_bridge_view,
    should_attempt_final_phase5_readmodel_flush,
    should_flush_phase5_next_frontier_after_workerpool_closure,
    should_invoke_source_family_adapter_value_eval,
    should_invoke_source_family_adapter_smoke,
    should_invoke_source_family_smoked_candidate_thin_bind,
    temporal_patch_marker_policy,
)


def test_assignment_auto_continue_enqueue_updates_workflow_state() -> None:
    workflow = TemporalCodexTaskWorkflow()

    workflow._enqueue_assignment_dag_auto_continue(
        {
            "auto_continue_same_workflow": True,
            "auto_continue_same_task_signal": {
                "wave_id": "wave-01",
                "temporal_hot_path_wave_index": 2,
            },
        }
    )

    assert workflow.continue_same_task_signals == [
        {"wave_id": "wave-01", "temporal_hot_path_wave_index": 2}
    ]


def test_ledger_auto_dispatch_enqueue_updates_workflow_state() -> None:
    workflow = TemporalCodexTaskWorkflow()

    workflow._enqueue_ledger_auto_dispatch(
        {
            "auto_continue_same_workflow": True,
            "auto_continue_same_task_signal": {
                "wave_id": "wave-02",
                "temporal_hot_path_wave_index": 3,
            },
        }
    )

    assert workflow.continue_same_task_signals == [
        {"wave_id": "wave-02", "temporal_hot_path_wave_index": 3}
    ]


def test_phase5_post_closure_flush_patch_is_registered() -> None:
    markers = temporal_patch_marker_policy()["patch_markers"]

    assert (
        markers["seed_cortex_source_family_phase5_post_closure_flush"]
        == TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_POST_CLOSURE_FLUSH
    )
    assert (
        markers["seed_cortex_source_family_phase5_final_readmodel_flush"]
        == TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_FINAL_READMODEL_FLUSH
    )
    assert (
        markers["seed_cortex_source_family_adapter_smoke"]
        == TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_SMOKE
    )
    assert (
        markers["seed_cortex_source_family_smoked_candidate_thin_bind"]
        == TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND
    )
    assert (
        markers["seed_cortex_source_family_adapter_value_eval"]
        == TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_VALUE_EVAL
    )


def test_phase5_next_frontier_flush_requires_sunset_and_closure_success() -> None:
    phase5 = {
        "activity": "source_family_mature_thin_bind_sunset",
        "sunset_validation_passed": True,
    }
    closure = {
        "activity": "source_frontier_workerpool_closure",
        "closure_validation_passed": True,
    }

    assert should_flush_phase5_next_frontier_after_workerpool_closure(phase5, closure)
    assert not should_flush_phase5_next_frontier_after_workerpool_closure({}, closure)
    assert not should_flush_phase5_next_frontier_after_workerpool_closure(
        {**phase5, "sunset_validation_passed": False},
        closure,
    )
    assert not should_flush_phase5_next_frontier_after_workerpool_closure(
        phase5,
        {**closure, "closure_validation_passed": False},
    )


def test_final_phase5_readmodel_flush_allows_prior_phase5_repair_result() -> None:
    failed_phase5 = {
        "activity": "source_family_mature_thin_bind_sunset",
        "sunset_validation_passed": False,
    }
    closure = {
        "activity": "source_frontier_workerpool_closure",
        "closure_validation_passed": True,
    }

    assert should_attempt_final_phase5_readmodel_flush(failed_phase5, closure)
    assert not should_attempt_final_phase5_readmodel_flush({}, closure)
    assert not should_attempt_final_phase5_readmodel_flush(
        failed_phase5,
        {**closure, "closure_validation_passed": False},
    )


def test_adapter_smoke_invokes_after_valid_phase5_with_candidates() -> None:
    phase5 = {
        "activity": "source_family_mature_thin_bind_sunset",
        "sunset_validation_passed": True,
        "candidate_adapter_smoke_count": 3,
    }

    assert should_invoke_source_family_adapter_smoke(phase5)
    assert not should_invoke_source_family_adapter_smoke(
        {**phase5, "candidate_adapter_smoke_count": 0}
    )
    assert not should_invoke_source_family_adapter_smoke(
        {**phase5, "sunset_validation_passed": False}
    )


def test_smoked_candidate_thin_bind_invokes_after_adapter_smoke_passes() -> None:
    adapter_smoke = {
        "activity": "source_family_adapter_smoke",
        "adapter_smoke_validation_passed": True,
        "passed_candidate_count": 3,
    }

    assert should_invoke_source_family_smoked_candidate_thin_bind(adapter_smoke)
    assert not should_invoke_source_family_smoked_candidate_thin_bind(
        {**adapter_smoke, "passed_candidate_count": 0}
    )
    assert not should_invoke_source_family_smoked_candidate_thin_bind(
        {**adapter_smoke, "adapter_smoke_validation_passed": False}
    )


def test_adapter_value_eval_invokes_after_thin_bind_passes() -> None:
    thin_bind = {
        "activity": "source_family_smoked_candidate_thin_bind",
        "thin_bind_validation_passed": True,
        "ready_binding_count": 3,
    }

    assert should_invoke_source_family_adapter_value_eval(thin_bind)
    assert not should_invoke_source_family_adapter_value_eval(
        {**thin_bind, "ready_binding_count": 0}
    )
    assert not should_invoke_source_family_adapter_value_eval(
        {**thin_bind, "thin_bind_validation_passed": False}
    )


def test_embedded_workerbrief_bridge_activity_from_main_loop_tick() -> None:
    bridge = embedded_workerbrief_bridge_activity_from_main_loop_tick(
        {
            "source_frontier_workerbrief_bridge": {
                "wave_id": "wave-02-source-frontier-workerbrief-bridge",
                "source_item_count": 1,
                "worker_brief_binding_count": 8,
                "source_frontier_delta": {"generated_bounded_item": True},
                "validation": {"passed": True},
                "output_paths": {
                    "latest": "D:/runtime/state/source_frontier_workerbrief_bridge/latest.json",
                    "temporal_activity_latest": "D:/runtime/state/source_frontier_workerbrief_bridge/temporal_activity_latest.json",
                    "wave": "D:/runtime/state/source_frontier_workerbrief_bridge/waves/wave-02-source-frontier-workerbrief-bridge.json",
                    "worker_brief_queue_latest": "D:/runtime/state/source_frontier_workerbrief_bridge/worker_brief_queue_latest.json",
                    "mapping_latest": "D:/runtime/state/source_frontier_workerbrief_bridge/mapping_latest.json",
                    "worker_dispatch_ledger_wave": "D:/runtime/state/worker_dispatch_ledger/waves/wave-02.json",
                    "worker_dispatch_ledger_activity": "D:/runtime/state/worker_dispatch_ledger/activity/wave-02.json",
                    "readback_zh": "D:/runtime/readback/zh/wave-02.md",
                },
            }
        }
    )

    assert bridge["activity"] == "source_frontier_workerbrief_bridge"
    assert bridge["bridge_validation_passed"] is True
    assert bridge["bridge_wave_id"] == "wave-02-source-frontier-workerbrief-bridge"
    assert bridge["worker_brief_binding_count"] == 8
    assert bridge["latest_alias_is_not_proof"] is True


def test_main_loop_tick_workerbrief_bridge_view_is_embeddable() -> None:
    view = main_loop_tick_workerbrief_bridge_view(
        {
            "source_frontier_workerbrief_bridge": {
                "wave_id": "wave-02-source-frontier-workerbrief-bridge",
                "status": "source_frontier_workerbrief_bridge_ready",
                "source_item_count": 1,
                "worker_brief_binding_count": 8,
                "source_frontier_delta": {"generated_bounded_item": True},
                "validation": {"passed": True},
                "output_paths": {
                    "latest": "D:/runtime/state/source_frontier_workerbrief_bridge/latest.json",
                    "temporal_activity_latest": "D:/runtime/state/source_frontier_workerbrief_bridge/temporal_activity_latest.json",
                    "wave": "D:/runtime/state/source_frontier_workerbrief_bridge/waves/wave-02-source-frontier-workerbrief-bridge.json",
                    "worker_brief_queue_latest": "D:/runtime/state/source_frontier_workerbrief_bridge/worker_brief_queue_latest.json",
                    "mapping_latest": "D:/runtime/state/source_frontier_workerbrief_bridge/mapping_latest.json",
                    "worker_dispatch_ledger_wave": "D:/runtime/state/worker_dispatch_ledger/waves/wave-02.json",
                    "worker_dispatch_ledger_activity": "D:/runtime/state/worker_dispatch_ledger/activity/wave-02.json",
                    "readback_zh": "D:/runtime/readback/zh/wave-02.md",
                },
                "large_runtime_only_field": {"not_returned": True},
            }
        }
    )

    bridge = embedded_workerbrief_bridge_activity_from_main_loop_tick(
        {"source_frontier_workerbrief_bridge": view}
    )

    assert "large_runtime_only_field" not in view
    assert bridge["bridge_validation_passed"] is True
    assert bridge["bridge_wave_id"] == "wave-02-source-frontier-workerbrief-bridge"
    assert bridge["source_bound_worker_brief_queue_ref"].endswith(
        "worker_brief_queue_latest.json"
    )


def test_live_temporal_history_result_compacts_large_worker_payloads() -> None:
    large_command = {"command": "rg source", "output": "x" * 5000}
    result = compact_temporal_history_result(
        {
            "activities": [
                {
                    "activity": "codex_worker_turn",
                    "status": "activity_gate_checked",
                    "worker_task_id": "worker-26",
                    "jsonl_path": "D:/runtime/codex-events.jsonl",
                    "final_path": "D:/runtime/final.md",
                    "work_package": {"lanes": [{"large": "y" * 5000}]},
                    "task_bound_worker_command_executions": [large_command],
                    "human_egress_filter": {
                        "status": "SEGMENT_BOUNDARY_USER_EGRESS_BLOCKED",
                        "jsonl_path": "D:/runtime/codex-events.jsonl",
                        "jobs_json_observe": {
                            "event_count": 9,
                            "command_executions": [large_command],
                            "command_execution_count": 1,
                            "token_usage": {"total_tokens": 42},
                        },
                    },
                }
            ],
            "segment_pass_next_worker": {
                "activity": "codex_worker_turn",
                "worker_task_id": "worker-26",
                "jsonl_path": "D:/runtime/codex-events.jsonl",
                "phase_execution": {"large": "z" * 5000},
            },
            "task_bound_worker_command_executions": [large_command],
            "jobs_json_observe_backend_readback": {
                "event_count": 9,
                "command_executions": [large_command],
                "command_execution_count": 1,
            },
        }
    )

    worker = result["activities"][0]
    assert worker["activity"] == "codex_worker_turn"
    assert worker["jsonl_path"] == "D:/runtime/codex-events.jsonl"
    assert "work_package" not in worker
    assert "phase_execution" not in result["segment_pass_next_worker"]
    assert result["task_bound_worker_command_execution_count"] == 1
    assert result["task_bound_worker_command_executions"] == []
    assert "command_executions" not in result["jobs_json_observe_backend_readback"]
    assert "command_executions" not in worker["human_egress_filter"]["jobs_json_observe"]


def test_codex_worker_activity_result_compacts_before_temporal_upload() -> None:
    large_command = {"command": "rg source", "output": "x" * 5000}
    payload = compact_activity_for_history(
        {
            "activity": "codex_worker_turn",
            "status": "activity_gate_checked",
            "worker_task_id": "worker-26",
            "jsonl_path": "D:/runtime/codex-events.jsonl",
            "final_path": "D:/runtime/final.md",
            "expected_marker_seen": True,
            "task_bound_worker": True,
            "work_package": {
                "files": ["services/agent_runtime/temporal_codex_task_workflow.py"],
                "work_items": [{"large": "y" * 5000}],
            },
            "verification": ["python -m pytest tests/test_temporal_codex_task_workflow.py"],
            "task_bound_worker_command_executions": [large_command],
            "jobs_json_observe": {
                "event_count": 9,
                "command_executions": [large_command],
                "command_execution_count": 1,
            },
            "activator_result": {"stdout": "z" * 5000},
        }
    )

    assert payload["expected_marker_seen"] is True
    assert payload["task_bound_worker"] is True
    assert payload["work_package"]["files"] == [
        "services/agent_runtime/temporal_codex_task_workflow.py"
    ]
    assert payload["verification"] == [
        "python -m pytest tests/test_temporal_codex_task_workflow.py"
    ]
    assert payload["task_bound_worker_command_execution_count"] == 1
    assert "command_executions" not in payload["jobs_json_observe"]
    assert "activator_result" not in payload
    assert "work_items" not in payload["work_package"]


def test_phase3_activity_result_compacts_full_worker_pool_payload() -> None:
    payload = compact_phase3_activity_result(
        {
            "activity": "dp_worker_pool_wave_activity",
            "status": "dp_worker_pool_wave_activity_ready",
            "wave_id": "event-wave-195",
            "phase1_latest_ref": "D:/runtime/state/modular/latest.json",
            "worker_dispatch_ledger_ref": "D:/runtime/state/ledger/latest.json",
            "tool_trace_evidence_ref": "D:/runtime/state/tool/latest.json",
            "actual_dispatched_width": 24,
            "actual_completed_width": 24,
            "draft_count": 13,
            "dynamic_width_decision": {
                "target_width": 24,
                "target_width_source": "dynamic_width_scheduler",
                "operator_cap_applied": False,
                "fixed_20_or_50_used": False,
                "scheduler_trace": {"large": "w" * 5000},
            },
            "capacity_observation": {
                "not_default_width": True,
                "not_permanent_cap": True,
                "provider_headroom_bound": True,
                "backlog_bound": True,
                "raw_snapshot": {"large": "v" * 5000},
            },
            "draft_artifacts_consumed": [{"large": "x" * 5000}],
            "phase1_payload": {"lane_results": [{"large": "y" * 5000}]},
            "activity_trace": {"large": "z" * 5000},
            "validation": {"passed": True, "checks": {"draft_count_positive": True}},
        }
    )

    assert payload["activity"] == "dp_worker_pool_wave_activity"
    assert payload["wave_id"] == "event-wave-195"
    assert payload["phase1_latest_ref"].endswith("latest.json")
    assert payload["actual_dispatched_width"] == 24
    assert payload["dynamic_width_decision"]["target_width_source"] == "dynamic_width_scheduler"
    assert payload["dynamic_width_decision"]["fixed_20_or_50_used"] is False
    assert "scheduler_trace" not in payload["dynamic_width_decision"]
    assert payload["capacity_observation"]["not_default_width"] is True
    assert "raw_snapshot" not in payload["capacity_observation"]
    assert payload["validation"]["passed"] is True
    assert "phase1_payload" not in payload
    assert "draft_artifacts_consumed" not in payload
    assert "activity_trace" not in payload


def test_continuation_workerpool_closure_patch_marker_is_declared() -> None:
    policy = temporal_patch_marker_policy()

    assert (
        policy["patch_markers"]["seed_cortex_continuation_workerpool_closure"]
        == TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE
    )
