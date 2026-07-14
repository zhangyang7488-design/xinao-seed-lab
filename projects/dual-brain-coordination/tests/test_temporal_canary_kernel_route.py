from __future__ import annotations

from adapters.temporal.canary_start_workflow import create_kernel_backed_canary_task


class _FakeService:
    def __init__(self) -> None:
        self.promote_kwargs: dict[str, object] = {}

    def open_thread(self, **_kwargs: object) -> dict[str, object]:
        return {"thread": {"thread_id": "thread-canary"}}

    def close_thread(self, **_kwargs: object) -> dict[str, object]:
        return {"ok": True}

    def promote_to_task(self, **kwargs: object) -> dict[str, object]:
        self.promote_kwargs = kwargs
        return {"task": {"task_id": "task-canary"}}


def test_canary_preserves_grok_frontier_in_kernel_task() -> None:
    service = _FakeService()
    frontier = [
        {"lane_id": "audit", "prompt": "audit"},
        {"lane_id": "research", "prompt": "research"},
    ]
    task_id = create_kernel_backed_canary_task(
        service,
        {
            "title": "strict route",
            "goal": "verify kernel-backed Grok route",
            "owner": "codex",
            "decision_hash": "decision-canary",
            "correlation_id": "corr-canary",
            "operation_id": "parent-op-canary",
            "grok_ready_frontier": frontier,
            "langgraph_child": {"enabled": True, "task_queue": "child-q"},
        },
        seed="strict-route",
    )
    assert task_id == "task-canary"
    metadata = service.promote_kwargs["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["grok_ready_frontier"] == frontier
    assert metadata["langgraph_child"] == {"enabled": True, "task_queue": "child-q"}
    assert metadata["correlation_id"] == "corr-canary"
    assert metadata["parent_operation_id"] == "parent-op-canary"
