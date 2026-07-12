from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from xinao_coordination import CoordinationService


class TaskControlMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self._temp = tempfile.TemporaryDirectory()
        self.service = CoordinationService(Path(self._temp.name) / "state.sqlite3")
        result = self.service.dispatch_task(
            actor="codex",
            title="state machine",
            goal="preserve task invariants",
            max_attempts=50,
            idempotency_key="dispatch",
        )
        self.task_id = result["task"]["task_id"]
        self.state = "queued"
        self.token: str | None = None
        self.counter = 0

    def key(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter}"

    @precondition(lambda self: self.state == "queued")
    @rule()
    def claim(self) -> None:
        result = self.service.claim_task(idempotency_key=self.key("claim"))
        assert result["task"]["task_id"] == self.task_id
        self.state = "leased"
        self.token = str(result["lease_token"])

    @precondition(lambda self: self.state == "leased")
    @rule()
    def start(self) -> None:
        assert self.token
        self.service.start_task(
            task_id=self.task_id,
            lease_token=self.token,
            idempotency_key=self.key("start"),
        )
        self.state = "running"

    @precondition(lambda self: self.state in {"leased", "running"})
    @rule()
    def heartbeat(self) -> None:
        assert self.token
        self.service.heartbeat_task(
            task_id=self.task_id,
            lease_token=self.token,
            idempotency_key=self.key("heartbeat"),
        )

    @precondition(lambda self: self.state in {"queued", "leased", "running"})
    @rule()
    def pause(self) -> None:
        self.service.pause_task(
            actor="user",
            task_id=self.task_id,
            reason="state-machine",
            idempotency_key=self.key("pause"),
        )
        self.state = "paused"
        self.token = None

    @precondition(lambda self: self.state == "paused")
    @rule()
    def resume(self) -> None:
        self.service.resume_task(
            actor="user",
            task_id=self.task_id,
            reason="state-machine",
            idempotency_key=self.key("resume"),
        )
        self.state = "queued"

    @precondition(lambda self: self.state in {"leased", "running"})
    @rule()
    def retry(self) -> None:
        assert self.token
        self.service.fail_task(
            task_id=self.task_id,
            lease_token=self.token,
            error="generated retry",
            retryable=True,
            idempotency_key=self.key("retry"),
        )
        self.state = "queued"
        self.token = None

    @invariant()
    def projection_and_event_versions_match(self) -> None:
        task = self.service.get_task(self.task_id)["task"]
        assert task["state"] == self.state
        assert (task["lease_token"] is not None) == (self.state in {"leased", "running"})
        events = self.service.events(stream_type="task", stream_id=self.task_id)["events"]
        assert events[-1]["stream_version"] == task["version"]
        assert [event["stream_version"] for event in events] == list(range(1, task["version"] + 1))

    def teardown(self) -> None:
        self._temp.cleanup()


TestTaskControl = TaskControlMachine.TestCase
TestTaskControl.settings = settings(max_examples=20, stateful_step_count=30, deadline=None)
