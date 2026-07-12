from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts import verify_houtai_gongren_restart_resume as canary
from temporalio.api.enums.v1 import EventType, TimeoutType
from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import WorkflowExecutionStatus


def _identity(*, pid: int = 10, started_at: str = "2026-07-12T00:00:00Z") -> dict:
    return {
        "id": "a" * 64,
        "created": "2026-07-11T00:00:00Z",
        "pid": pid,
        "started_at": started_at,
        "status": "running",
        "health": "healthy",
        "image_id": "sha256:image",
        "path": "python",
        "args": ["-m", "worker"],
        "compose_project": "xinao-base",
        "compose_service": "houtai-gongren",
        "compose_file": str(canary.REPO / "docker-compose.yml"),
        "config_hash": "config",
        "mounts": [{"source": "D:/runtime", "destination": "/evidence", "rw": True}],
    }


def test_static_identity_ignores_only_runtime_generation() -> None:
    before = _identity()
    after = _identity(pid=20, started_at="2026-07-12T00:01:00Z")

    assert canary._static_identity(before) == canary._static_identity(after)
    assert before["pid"] != after["pid"]
    assert before["started_at"] != after["started_at"]


def test_docker_identity_selects_fields_without_environment(monkeypatch) -> None:
    mounts = [
        {"Source": "E:/repo", "Destination": "/app", "RW": False},
        {"Source": "D:/runtime", "Destination": "/evidence", "RW": True},
    ]
    lines = [
        "a" * 64,
        "2026-07-11T00:00:00Z",
        "100",
        "2026-07-12T00:00:00Z",
        "running",
        "healthy",
        "sha256:image",
        "python",
        json.dumps(["-m", "worker"]),
        "xinao-base",
        "houtai-gongren",
        str(canary.REPO / "docker-compose.yml"),
        "config",
        json.dumps(mounts),
    ]

    def fake_run(command, *, timeout=60):
        assert "Config.Env" not in " ".join(command)
        return SimpleNamespace(returncode=0, stdout="\n".join(lines), stderr="")

    monkeypatch.setattr(canary, "_run", fake_run)
    value = canary.docker_identity()

    assert value["pid"] == 100
    assert [item["destination"] for item in value["mounts"]] == ["/app", "/evidence"]
    assert "env" not in value


def test_queue_readiness_requires_all_workflow_and_activity_pollers_fresh() -> None:
    after = datetime.now(UTC)
    recent = (after + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    snapshot = {
        queue: {
            kind: {
                "pollers": [{"identity": "1@container", "last_access_time": recent}],
                "backlog": 0,
            }
            for kind in ("workflow", "activity")
        }
        for queue in canary.ALL_QUEUES
    }

    assert canary._queues_ready(snapshot, after=after) is True
    snapshot[canary.ALL_QUEUES[0]]["activity"]["pollers"] = []
    assert canary._queues_ready(snapshot, after=after) is False


def test_rollback_refuses_identity_drift(monkeypatch) -> None:
    before = _identity()
    drifted = {**_identity(), "image_id": "sha256:other", "status": "exited"}
    called = False

    def fake_run(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(canary, "_run", fake_run)
    result = canary._rollback_start_if_exact_stopped(pre=before, current=drifted)

    assert result["attempted"] is False
    assert "identity drift" in result["reason"]
    assert called is False


def test_event_rows_reports_retry_start_to_close_timeout_and_attempt_lineage() -> None:
    scheduled = HistoryEvent(
        event_id=53,
        event_type=EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED,
    )
    scheduled.event_time.FromDatetime(datetime(2026, 7, 12, 0, 42, tzinfo=UTC))
    scheduled.activity_task_scheduled_event_attributes.activity_type.name = "search"
    started = HistoryEvent(
        event_id=54,
        event_type=EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED,
    )
    started.event_time.FromDatetime(datetime(2026, 7, 12, 0, 47, 1, tzinfo=UTC))
    attrs = started.activity_task_started_event_attributes
    attrs.scheduled_event_id = 53
    attrs.identity = "1@container123"
    attrs.attempt = 2
    attrs.last_failure.message = "activity StartToClose timeout"
    attrs.last_failure.source = "Server"
    attrs.last_failure.timeout_failure_info.timeout_type = TimeoutType.TIMEOUT_TYPE_START_TO_CLOSE

    rows = canary._event_rows(SimpleNamespace(events=[scheduled, started]))
    lineage = canary._attempt_two_restart_lineage(
        rows,
        post_started=datetime(2026, 7, 12, 0, 42, 8, tzinfo=UTC),
        worker_identity_fragment="container123",
    )

    assert rows[1]["scheduled_event_id"] == 53
    assert rows[1]["last_failure_timeout_type"] == "TIMEOUT_TYPE_START_TO_CLOSE"
    assert rows[1]["last_failure_message"] == "activity StartToClose timeout"
    assert lineage == [
        {
            "started_event_id": 54,
            "scheduled_event_id": 53,
            "activity_type": "search",
            "attempt": 2,
            "worker_identity": "1@container123",
            "started_at": "2026-07-12T00:47:01Z",
            "last_failure_timeout_type": "TIMEOUT_TYPE_START_TO_CLOSE",
            "last_failure_message": "activity StartToClose timeout",
        }
    ]


def test_blast_radius_gate_allows_only_exact_canary_run() -> None:
    exact = {
        "workflow_id": "wf-canary",
        "run_id": "run-canary",
        "workflow_type": canary.WORKFLOW_TYPE,
        "task_queue": canary.WORKFLOW_QUEUE,
        "status": "RUNNING",
    }
    unrelated = {
        **exact,
        "workflow_id": "wf-unrelated",
        "run_id": "run-unrelated",
    }

    assert canary._blast_radius_gate([], expected_workflow=None) is True
    assert canary._blast_radius_gate([exact], expected_workflow=("wf-canary", "run-canary")) is True
    assert (
        canary._blast_radius_gate([exact, unrelated], expected_workflow=("wf-canary", "run-canary"))
        is False
    )
    assert canary._blast_radius_gate([unrelated], expected_workflow=None) is False


def test_all_temporal_terminal_states_are_recognized() -> None:
    assert canary.TERMINAL == {
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.TERMINATED,
        WorkflowExecutionStatus.CONTINUED_AS_NEW,
        WorkflowExecutionStatus.TIMED_OUT,
    }


def test_cancel_waits_for_terminal_and_continued_as_new_is_already_terminal() -> None:
    class FakeHandle:
        def __init__(self, statuses):
            self.statuses = list(statuses)
            self.cancel_calls = 0

        async def describe(self):
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return SimpleNamespace(status=status)

        async def cancel(self):
            self.cancel_calls += 1

    running = FakeHandle([WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.CANCELED])
    canceled = asyncio.run(canary._cancel_handle_to_terminal(running))
    assert canceled == {
        "status_before": "RUNNING",
        "cancel_requested": True,
        "status_after": "CANCELED",
        "terminal_confirmed": True,
    }
    assert running.cancel_calls == 1

    continued = FakeHandle([WorkflowExecutionStatus.CONTINUED_AS_NEW])
    already_terminal = asyncio.run(canary._cancel_handle_to_terminal(continued))
    assert already_terminal["status_after"] == "CONTINUED_AS_NEW"
    assert already_terminal["terminal_confirmed"] is True
    assert continued.cancel_calls == 0


def test_active_workflow_snapshot_filters_to_canonical_queues() -> None:
    now = datetime.now(UTC)
    rows = [
        SimpleNamespace(
            id="canonical",
            run_id="run-1",
            workflow_type=canary.WORKFLOW_TYPE,
            task_queue=canary.WORKFLOW_QUEUE,
            status=WorkflowExecutionStatus.RUNNING,
            start_time=now,
        ),
        SimpleNamespace(
            id="other-queue",
            run_id="run-2",
            workflow_type="OtherWorkflow",
            task_queue="other-queue",
            status=WorkflowExecutionStatus.RUNNING,
            start_time=now,
        ),
    ]

    class AsyncRows:
        def __aiter__(self):
            self.iterator = iter(rows)
            return self

        async def __anext__(self):
            try:
                return next(self.iterator)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeClient:
        def list_workflows(self, query):
            assert query == 'ExecutionStatus = "Running"'
            return AsyncRows()

    snapshot = asyncio.run(canary._active_canonical_workflows(FakeClient()))
    assert [item["workflow_id"] for item in snapshot] == ["canonical"]


def test_cleanup_targets_exact_workflow_run(monkeypatch) -> None:
    captured = {}

    class FakeHandle:
        async def describe(self):
            return SimpleNamespace(status=WorkflowExecutionStatus.CANCELED)

        async def cancel(self):
            raise AssertionError("already-terminal exact run must not be canceled again")

    class FakeClient:
        def get_workflow_handle(self, workflow_id, *, run_id):
            captured.update(workflow_id=workflow_id, run_id=run_id)
            return FakeHandle()

    async def fake_connect(*_args, **_kwargs):
        return FakeClient()

    monkeypatch.setattr(canary.Client, "connect", staticmethod(fake_connect))
    result = asyncio.run(canary._cancel_exact_running("wf-exact", "run-exact"))

    assert captured == {"workflow_id": "wf-exact", "run_id": "run-exact"}
    assert result["status_after"] == "CANCELED"
    assert result["terminal_confirmed"] is True
