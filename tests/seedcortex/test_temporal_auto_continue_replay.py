from services.agent_runtime.temporal_codex_task_workflow import (
    TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_VALUE_EVAL,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_SMOKE,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_FINAL_READMODEL_FLUSH,
    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_POST_CLOSURE_FLUSH,
    TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTRACT_ROUTER,
    TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTROL_PREEMPTIVE_EXECUTOR,
    TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_LOOP_CONTINUE_AS_NEW,
    TemporalCodexTaskWorkflow,
    build_default_loop_continue_as_new_payload,
    compact_activity_for_history,
    default_loop_rollover_decision,
    is_preemptive_continue_same_task_signal,
    compact_phase3_activity_result,
    compact_temporal_history_result,
    embedded_workerbrief_bridge_activity_from_main_loop_tick,
    main_loop_tick_workerbrief_bridge_view,
    normalize_task_control_signal,
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


def test_task_control_insert_front_marks_preemptive_signal() -> None:
    control = normalize_task_control_signal(
        {
            "routing_verb": "insert_front",
            "control_id": "unit-p0-004",
            "continue_same_task_signal": {
                "assignment_dag_node_id": "p0_004_litellm_default_binding_closure",
                "worker_kind": "implementation_worker",
                "phase_scope": "p0_004_litellm_default_binding_closure",
                "work_package": {"objective": "bind LiteLLM default route"},
                "verification": ["verify routed_by=litellm"],
            },
        }
    )

    signal = control["continue_same_task_signal"]

    assert control["insert_front"] is True
    assert signal["task_control_insert_front"] is True
    assert signal["preempt_default_bootstrap"] is True
    assert signal["explicit_user_task_control"] is True
    assert is_preemptive_continue_same_task_signal(signal) is True


def test_next_frontier_auto_continue_waits_behind_preemptive_task_control() -> None:
    workflow = TemporalCodexTaskWorkflow()
    workflow.continue_same_task_signals.append(
        {
            "assignment_dag_node_id": "p0_004_litellm_default_binding_closure",
            "worker_kind": "implementation_worker",
            "phase_scope": "p0_004_litellm_default_binding_closure",
            "preempt_default_bootstrap": True,
        }
    )

    workflow._enqueue_next_frontier_continuation(
        {
            "auto_continue_same_workflow": True,
            "auto_continue_same_task_signal": {
                "assignment_dag_node_id": "next-frontier:adapter-smoke",
                "worker_kind": "implementation_worker",
                "phase_scope": "smoke_mature_carrier_adapter_candidates",
            },
        },
        {},
    )

    assert len(workflow.continue_same_task_signals) == 1
    assert (
        workflow.continue_same_task_signals[0]["assignment_dag_node_id"]
        == "p0_004_litellm_default_binding_closure"
    )


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
    assert (
        markers["seed_cortex_default_loop_continue_as_new"]
        == TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_LOOP_CONTINUE_AS_NEW
    )
    assert (
        markers["seed_cortex_task_control_preemptive_executor"]
        == TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTROL_PREEMPTIVE_EXECUTOR
    )
    assert (
        markers["seed_cortex_task_contract_router"]
        == TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTRACT_ROUTER
    )


class _WorkflowInfo:
    def __init__(
        self,
        *,
        history_length: int = 0,
        history_size: int = 0,
        suggested: bool = False,
    ) -> None:
        self._history_length = history_length
        self._history_size = history_size
        self._suggested = suggested

    def get_current_history_length(self) -> int:
        return self._history_length

    def get_current_history_size(self) -> int:
        return self._history_size

    def is_continue_as_new_suggested(self) -> bool:
        return self._suggested


def test_default_loop_history_budget_rollover_uses_dynamic_budget() -> None:
    decision = default_loop_rollover_decision(
        {"task_id": "unit", "default_loop_history_budget_ratio": 0.70},
        _WorkflowInfo(history_length=100, history_size=7_100_000),
        waves_completed_in_run=1,
        pending_signal_count=1,
        patch_enabled=True,
    )

    assert decision["policy"] == "default_loop_history_budget_rollover"
    assert decision["should_continue_as_new"] is True
    assert "estimated_history_budget_used" in decision["reasons"]
    assert decision["estimated_history_budget_used"] >= 0.70


def test_default_loop_history_budget_rollover_has_hard_wave_fuse() -> None:
    decision = default_loop_rollover_decision(
        {"task_id": "unit", "default_loop_max_waves_per_run": 4},
        _WorkflowInfo(history_length=100, history_size=1000),
        waves_completed_in_run=4,
        pending_signal_count=1,
        patch_enabled=True,
    )

    assert decision["should_continue_as_new"] is True
    assert "max_waves_per_run_fuse" in decision["reasons"]
    assert decision["max_waves_per_run_is_hard_fuse"] is True


def test_default_loop_rollover_decision_respects_disabled_or_no_pending() -> None:
    disabled = default_loop_rollover_decision(
        {"task_id": "unit", "default_loop_continue_as_new": False},
        _WorkflowInfo(suggested=True),
        waves_completed_in_run=99,
        pending_signal_count=1,
        patch_enabled=True,
    )
    no_pending = default_loop_rollover_decision(
        {"task_id": "unit"},
        _WorkflowInfo(suggested=True),
        waves_completed_in_run=99,
        pending_signal_count=0,
        patch_enabled=True,
    )

    assert disabled["should_continue_as_new"] is False
    assert no_pending["should_continue_as_new"] is False


def test_default_loop_continue_as_new_payload_carries_small_resume_state() -> None:
    large_text = "x" * 5000
    payload = build_default_loop_continue_as_new_payload(
        {
            "task_id": "unit",
            "runtime_root": "D:/runtime",
            "repo_root": "E:/repo",
            "workflow_id": "wf",
            "workflow_run_id": "run-1",
            "user_goal": large_text,
            "graph_result": {"large": large_text},
            "source_refs": [{"path": "C:/Desktop/input.txt", "digest": "abc"}],
            "followup_after_this": "C:/Desktop/333_当前收口_未处理后续_20260706.txt",
        },
        pending_signals=[
            {
                "assignment_dag_node_id": "next-node",
                "wave_id": "wave-5",
                "temporal_hot_path_wave_index": 5,
                "phase_execution": {
                    "worker_kind": "implementation_worker",
                    "phase_scope": "unit",
                    "work_package": {
                        "objective": large_text,
                        "next_ready_node_id": "next-node",
                        "work_items": [{"id": "next-node", "objective": large_text}],
                    },
                    "verification": ["python -m pytest tests/unit.py"],
                },
            }
        ],
        rollover_decision={
            "policy": "default_loop_history_budget_rollover",
            "should_continue_as_new": True,
            "reasons": ["estimated_history_budget_used"],
        },
        last_result={
            "completion_decision": {"status": "partial", "stop_allowed": False},
            "workflow_result_ref": "D:/runtime/state/workflow.json",
        },
        initial_worker_task_id="unit.codex-worker.initial",
    )

    resume = payload["default_loop_continue_as_new_resume_state"]
    pending = resume["pending_continue_same_task_signals"][0]
    encoded = __import__("json").dumps(payload, ensure_ascii=False)
    assert payload["codex_worker_task_id"] == "unit.codex-worker.initial"
    assert payload["default_loop_continue_generation"] == 1
    assert payload["followup_after_this"] == "C:/Desktop/333_当前收口_未处理后续_20260706.txt"
    assert resume["previous_run_id"] == "run-1"
    assert pending["assignment_dag_node_id"] == "next-node"
    assert pending["phase_execution"]["work_package"]["next_ready_node_id"] == "next-node"
    assert "graph_result" not in payload
    assert "x" * 1200 not in encoded


def test_default_loop_resume_state_restore_dedupes_pending_signal() -> None:
    workflow = TemporalCodexTaskWorkflow()
    resume_state = {
        "pending_continue_same_task_signals": [
            {
                "assignment_dag_node_id": "next-node",
                "wave_id": "wave-5",
                "temporal_hot_path_wave_index": 5,
            },
            {
                "assignment_dag_node_id": "next-node",
                "wave_id": "wave-5",
                "temporal_hot_path_wave_index": 5,
            },
        ]
    }

    workflow._restore_default_loop_continue_as_new_state(resume_state)

    assert workflow.continue_same_task_signals == [
        {
            "assignment_dag_node_id": "next-node",
            "wave_id": "wave-5",
            "temporal_hot_path_wave_index": 5,
        }
    ]


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
