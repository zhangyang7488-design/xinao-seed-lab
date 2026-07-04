from services.agent_runtime.temporal_codex_task_workflow import (
    TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE,
    TemporalCodexTaskWorkflow,
    embedded_workerbrief_bridge_activity_from_main_loop_tick,
    main_loop_tick_workerbrief_bridge_view,
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


def test_continuation_workerpool_closure_patch_marker_is_declared() -> None:
    policy = temporal_patch_marker_policy()

    assert (
        policy["patch_markers"]["seed_cortex_continuation_workerpool_closure"]
        == TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE
    )
