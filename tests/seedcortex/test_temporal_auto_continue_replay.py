from services.agent_runtime.temporal_codex_task_workflow import TemporalCodexTaskWorkflow


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
