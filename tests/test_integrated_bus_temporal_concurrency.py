from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest
from services.agent_runtime import integrated_bus_runner as runner


def _envelope_ref(path: Path, content: bytes = b'{"sealed":true}\n') -> dict[str, str]:
    path.write_bytes(content)
    return {"path": str(path), "sha256": hashlib.sha256(content).hexdigest()}


def test_canonical_workflow_identity_is_stable_and_collision_resistant(
    tmp_path: Path,
) -> None:
    envelope_ref = _envelope_ref(tmp_path / "dispatch-envelope.json")

    first = runner._resolve_integrated_bus_workflow_identity(
        workflow_id_prefix="Xinao Integrated Bus",
        dispatch_envelope_ref=envelope_ref,
        dispatch_task_run_id="task/run:alpha",
    )
    repeated = runner._resolve_integrated_bus_workflow_identity(
        workflow_id_prefix="Xinao Integrated Bus",
        dispatch_envelope_ref=envelope_ref,
        dispatch_task_run_id="task/run:alpha",
    )
    normalized_collision = runner._resolve_integrated_bus_workflow_identity(
        workflow_id_prefix="Xinao Integrated Bus",
        dispatch_envelope_ref=envelope_ref,
        dispatch_task_run_id="task:run/alpha",
    )

    assert first == repeated
    assert first[1] == "canonical_stable"
    assert first[0].startswith("xinao-integrated-bus-canon-task-run-alpha-")
    assert first[0] != normalized_collision[0]
    assert len(first[0]) < 200


def test_canonical_workflow_identity_rejects_resealed_input_drift(tmp_path: Path) -> None:
    envelope_path = tmp_path / "dispatch-envelope.json"
    envelope_ref = _envelope_ref(envelope_path)
    envelope_path.write_bytes(b'{"sealed":false}\n')

    with pytest.raises(ValueError, match="drifted before Temporal submit"):
        runner._resolve_integrated_bus_workflow_identity(
            workflow_id_prefix="xinao-integrated-bus",
            dispatch_envelope_ref=envelope_ref,
            dispatch_task_run_id="task-run-1",
        )


def test_legacy_workflow_identity_remains_an_explicit_independent_sample() -> None:
    first = runner._resolve_integrated_bus_workflow_identity(
        workflow_id_prefix="xinao-integrated-bus",
        dispatch_envelope_ref=None,
        dispatch_task_run_id="",
    )
    second = runner._resolve_integrated_bus_workflow_identity(
        workflow_id_prefix="xinao-integrated-bus",
        dispatch_envelope_ref=None,
        dispatch_task_run_id="",
    )

    assert first[1] == second[1] == "legacy_uuid"
    assert first[0] != second[0]


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_workflow(self, workflow: object, initial: object, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        return {"workflow": "completed"}


def test_canonical_start_uses_explicit_conflict_and_reuse_policies() -> None:
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

    client = _RecordingClient()
    result, disposition = asyncio.run(
        runner._execute_integrated_bus_workflow(
            client,
            {"input": "sealed"},
            workflow_id="canonical-id",
            task_queue="shared-queue",
            canonical=True,
        )
    )

    assert result == {"workflow": "completed"}
    assert disposition == "submitted_or_attached_open"
    assert client.calls == [
        {
            "id": "canonical-id",
            "task_queue": "shared-queue",
            "id_conflict_policy": WorkflowIDConflictPolicy.USE_EXISTING,
            "id_reuse_policy": WorkflowIDReusePolicy.REJECT_DUPLICATE,
        }
    ]


def test_legacy_start_does_not_claim_canonical_duplicate_semantics() -> None:
    client = _RecordingClient()
    asyncio.run(
        runner._execute_integrated_bus_workflow(
            client,
            {"input": "independent"},
            workflow_id="sample-id",
            task_queue="shared-queue",
            canonical=False,
        )
    )

    assert client.calls == [{"id": "sample-id", "task_queue": "shared-queue"}]


class _CompletedHandle:
    async def result(self) -> dict[str, str]:
        return {"workflow": "prior-result"}


class _ClosedDuplicateClient:
    def __init__(self) -> None:
        self.handle_args: tuple[str, str | None] | None = None

    async def execute_workflow(self, workflow: object, initial: object, **kwargs: Any) -> dict:
        from temporalio.exceptions import WorkflowAlreadyStartedError

        raise WorkflowAlreadyStartedError(
            kwargs["id"],
            "XinaoIntegratedBusWorkflow",
            run_id="server-run-id",
        )

    def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None) -> object:
        self.handle_args = (workflow_id, run_id)
        return _CompletedHandle()


def test_canonical_closed_duplicate_reads_prior_result_without_rerun() -> None:
    client = _ClosedDuplicateClient()
    result, disposition = asyncio.run(
        runner._execute_integrated_bus_workflow(
            client,
            {"input": "sealed"},
            workflow_id="canonical-id",
            task_queue="shared-queue",
            canonical=True,
        )
    )

    assert result == {"workflow": "prior-result"}
    assert disposition == "reused_closed_result"
    assert client.handle_args == ("canonical-id", "server-run-id")


class _UseExistingClient:
    def __init__(self) -> None:
        self.executions: dict[str, asyncio.Task[dict[str, int]]] = {}
        self.started = 0

    async def _execute_once(self) -> dict[str, int]:
        self.started += 1
        await asyncio.sleep(0.02)
        return {"execution": self.started}

    async def execute_workflow(self, workflow: object, initial: object, **kwargs: Any) -> dict:
        workflow_id = str(kwargs["id"])
        task = self.executions.get(workflow_id)
        if task is None:
            task = asyncio.create_task(self._execute_once())
            self.executions[workflow_id] = task
        return await task


def test_same_canonical_identity_attaches_to_one_open_execution() -> None:
    async def exercise() -> tuple[list[tuple[dict[str, Any], str]], int]:
        client = _UseExistingClient()
        results = await asyncio.gather(
            *(
                runner._execute_integrated_bus_workflow(
                    client,
                    {"input": "sealed"},
                    workflow_id="same-canonical-id",
                    task_queue="shared-queue",
                    canonical=True,
                )
                for _ in range(2)
            )
        )
        return results, client.started

    results, started = asyncio.run(exercise())
    assert started == 1
    assert results == [
        ({"execution": 1}, "submitted_or_attached_open"),
        ({"execution": 1}, "submitted_or_attached_open"),
    ]


class _OverlapClient:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.both_active = asyncio.Event()

    async def execute_workflow(self, workflow: object, initial: object, **kwargs: Any) -> dict:
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.active == 2:
            self.both_active.set()
        await self.both_active.wait()
        await asyncio.sleep(0.01)
        self.active -= 1
        return {"workflow_id": kwargs["id"], "validation": {"passed": True}}


def test_temporal_runner_allows_distinct_canonical_work_to_overlap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from temporalio.client import Client

    client = _OverlapClient()

    async def fake_connect(cls: type, address: str) -> _OverlapClient:
        return client

    def fake_build_payload(
        result: dict[str, Any],
        *,
        workflow_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"workflow_id": workflow_id, "result": result}

    monkeypatch.setattr(Client, "connect", classmethod(fake_connect))
    monkeypatch.setattr(runner, "_load_params", lambda: {"task_queue": "shared-queue"})
    monkeypatch.setattr(runner, "_resolve_worker_ownership", lambda **kwargs: "docker_daemon")
    monkeypatch.setattr(
        runner,
        "_initial_state_for_docker_worker",
        lambda *args, **kwargs: {"input": "sealed"},
    )
    monkeypatch.setattr(runner, "_record_leg_b_worker_terminals", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "_build_payload", fake_build_payload)

    envelope_ref = _envelope_ref(tmp_path / "dispatch-envelope.json")

    async def exercise() -> list[dict[str, Any]]:
        calls = [
            runner.run_integrated_bus_temporal(
                tmp_path / f"input-{index}.txt",
                runtime_root=tmp_path / "runtime",
                repo_root=tmp_path,
                dispatch_envelope_ref=envelope_ref,
                dispatch_route_claim_ref="route-claim.json",
                dispatch_task_run_dir=tmp_path / f"task-{index}",
                dispatch_task_run_id=f"task-{index}",
            )
            for index in range(2)
        ]
        return await asyncio.wait_for(asyncio.gather(*calls), timeout=1.0)

    results = asyncio.run(exercise())
    assert client.peak == 2
    assert len({result["workflow_id"] for result in results}) == 2
    assert {result["temporal_workflow_id_mode"] for result in results} == {"canonical_stable"}


def test_retired_queue_lock_has_no_importable_module() -> None:
    retired = (
        Path(__file__).parents[1]
        / "services"
        / "agent_runtime"
        / "integrated_bus_temporal_client_queue.py"
    )
    assert not retired.exists()
