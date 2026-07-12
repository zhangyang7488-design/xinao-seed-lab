"""T9 Temporal promoted-task thin adapter — isolated; no live Temporal / M-KEEP / desktop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from temporalio.client import WorkflowExecutionStatus

from tests.conftest import accepted_thread
from xinao_coordination import database as database_module
from xinao_coordination.errors import AuthorizationError, InvalidTransitionError, ValidationError
from xinao_coordination.service import TASK_DISPATCHERS, CoordinationService
from xinao_coordination.temporal import activities as temporal_activities
from xinao_coordination.temporal.client import TemporalClient, reset_mock_registry
from xinao_coordination.temporal.envelope import envelope_from_kernel_task
from xinao_coordination.temporal.policy import temporal_policy
from xinao_coordination.temporal.workflow import (
    DEFAULT_LANGGRAPH_CHILD_QUEUE,
    DEFAULT_LANGGRAPH_CHILD_WORKFLOW,
    REQUIRED_LANGGRAPH_TRUE_CHECKS,
    _containerize_input_ref,
    build_langgraph_child_spec,
    summarize_langgraph_child,
)


def _promote(service: CoordinationService, suffix: str) -> str:
    thread_id = accepted_thread(service, suffix)
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash=f"resolution-{suffix}",
        title=f"t9 task {suffix}",
        goal="durable promoted work",
        idempotency_key=f"promote-{suffix}",
    )
    task = promoted["task"]
    assert isinstance(task, dict)
    return str(task["task_id"])


@pytest.fixture(autouse=True)
def _temporal_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XINAO_TEMPORAL_ENABLED", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_MOCK", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_LIVE", "0")
    reset_mock_registry()


def test_t9_temporal_status_disabled_by_default(
    service: CoordinationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XINAO_TEMPORAL_ENABLED", "0")
    st = service.temporal_status()
    assert st["ok"] is True
    assert st["auto_start_on_promote"] is False
    assert st["mbg_temporal_owner"] is False
    assert st["policy"]["enabled"] is False


def test_t9_temporal_status_mock_enabled(service: CoordinationService) -> None:
    st = service.temporal_status()
    assert st["ok"] is True
    assert st["policy"]["enabled"] is True
    assert st["policy"]["mock_mode"] is True
    assert st["policy"]["promoted_task_only"] is True
    assert st["promoted_queue"]["task_queue"] == "xinao-dualbrain-promoted-v1"


def test_t9_start_requires_promoted_task(service: CoordinationService) -> None:
    dispatched = service.dispatch_task(
        actor="codex",
        title="not promoted",
        goal="x",
        explicit_non_consensus=True,
        idempotency_key="t9-non-promoted",
    )
    task_id = dispatched["task"]["task_id"]
    with pytest.raises(ValidationError):
        service.temporal_start_promoted(actor="codex", task_id=task_id)


def test_t9_start_promoted_mock_idempotent(service: CoordinationService) -> None:
    task_id = _promote(service, "t9-1")
    first = service.temporal_start_promoted(
        actor="codex",
        task_id=task_id,
        idempotency_key="t9-start-1",
    )
    assert first["ok"] is True
    assert first["mode"] == "mock"
    assert first["workflow_id"].startswith("xinao-task-")
    assert first["replayed"] is False
    wf_id = first["workflow_id"]

    second = service.temporal_start_promoted(
        actor="codex",
        task_id=task_id,
        idempotency_key="t9-start-1",
    )
    assert second["replayed"] is True
    assert second["workflow_id"] == wf_id

    refreshed = service.get_task(task_id)["task"]
    meta = refreshed["metadata"]
    assert meta["temporal_workflow_id"] == wf_id
    assert meta["promoted"] is True
    assert meta["temporal_kernel_lease_token"]
    assert refreshed["state"] == "running"
    assert refreshed["lease_owner"].startswith("temporal:")


def test_t9_promoted_envelope_routes_to_canonical_langgraph_child(
    service: CoordinationService,
) -> None:
    task_id = _promote(service, "t9-child-envelope")
    task = service.get_task(task_id)["task"]
    assert isinstance(task, dict)
    policy = temporal_policy()
    envelope = envelope_from_kernel_task(
        task,
        workflow_type=str(policy["workflow_type"]),
        task_queue=str(policy["task_queue"]),
    )
    child = envelope.to_workflow_input()["langgraph_child"]
    assert isinstance(child, dict)
    assert child == {
        "enabled": True,
        "task_queue": DEFAULT_LANGGRAPH_CHILD_QUEUE,
        "workflow_type": DEFAULT_LANGGRAPH_CHILD_WORKFLOW,
        "input_ref": "/app/materials/phase0_test_input.md",
    }


def test_t9_promoted_envelope_carries_caller_derived_grok_frontier(
    service: CoordinationService,
) -> None:
    task_id = _promote(service, "t9-grok-frontier")
    task = service.get_task(task_id)["task"]
    assert isinstance(task, dict)
    task = {**task, "metadata": dict(task["metadata"])}
    task["metadata"]["grok_ready_frontier"] = [
        {"lane_id": "research", "mode": "external_research", "prompt": "find mature"},
        {"lane_id": "audit", "mode": "audit", "prompt": "audit handroll"},
    ]
    envelope = envelope_from_kernel_task(
        task,
        workflow_type="XinaoPromotedTaskWorkflowV1",
        task_queue="xinao-dualbrain-promoted-v1",
    ).to_workflow_input()
    assert [item["lane_id"] for item in envelope["grok_ready_frontier"]] == ["research", "audit"]
    assert envelope["grok_serial_reason"] == ""


def test_t9_child_spec_prefers_materialized_promoted_intake() -> None:
    spec = build_langgraph_child_spec(
        {
            "workflow_id": "xinao-task-example-g0",
            "langgraph_child": {
                "enabled": True,
                "input_ref": "/app/materials/phase0_test_input.md",
            },
        },
        step_index=2,
        started={
            "intake": {
                "ok": True,
                "container_path": "/evidence/state/promoted/example.md",
            }
        },
    )
    assert spec["workflow_id"] == "xinao-task-example-g0-langgraph-s2"
    assert spec["task_queue"] == DEFAULT_LANGGRAPH_CHILD_QUEUE
    assert spec["workflow_type"] == DEFAULT_LANGGRAPH_CHILD_WORKFLOW
    assert spec["input"]["input_path"] == "/evidence/state/promoted/example.md"
    assert spec["input"]["repo_root"] == "/app"
    assert spec["input"]["runtime_root"] == "/evidence"


@pytest.mark.parametrize(
    ("host_path", "container_path"),
    [
        (
            r"D:\XINAO_RESEARCH_RUNTIME\state\input.md",
            "/evidence/state/input.md",
        ),
        (
            r"E:\XINAO_RESEARCH_WORKSPACES\S\materials\input.md",
            "/app/materials/input.md",
        ),
        ("/evidence/state/input.md", "/evidence/state/input.md"),
    ],
)
def test_t9_containerizes_only_canonical_roots(host_path: str, container_path: str) -> None:
    assert _containerize_input_ref(host_path) == container_path


def test_t9_rejects_noncanonical_input_ref() -> None:
    with pytest.raises(ValueError, match="outside canonical"):
        _containerize_input_ref(r"C:\Users\xx363\Desktop\input.md")


def test_t9_langgraph_summary_requires_real_acceptance_evidence() -> None:
    spec = build_langgraph_child_spec(
        {"workflow_id": "xinao-task-example-g0"},
        step_index=0,
    )
    result = {name: True for name in REQUIRED_LANGGRAPH_TRUE_CHECKS}
    result.update(
        {
            "content_md": "real promoted input",
            "parallel_succeeded": 2,
            "worker_lane_provider": "grok_acpx_headless",
            "worker_lane_model": "grok-4.5",
            "grok_only_mode": True,
            "grok_fanin_ok": True,
            "grok_fanin_manifest_ref": "/evidence/state/grok/manifest.json",
            "grok_fanin_lane_count": 2,
            "non_grok_model_invocations": 0,
            "fallback_model_invocation_performed": False,
            "memory_model_bind_frozen": True,
            "pro_review_provider": "grok_acpx_headless",
            "proof_path": "/evidence/state/integrated_bus_proof/example.txt",
            "promotion_evidence_ref": "/evidence/readback/promotion.json",
            "pytest_slice_ref": "/evidence/state/pytest/latest.json",
        }
    )
    passed = summarize_langgraph_child(spec, result)
    assert passed["passed"] is True
    assert passed["not_applicable_checks"] == ["child_wf_ok"]
    assert passed["not_applicable_reason"] == "parent_temporal_langgraph_child"

    # The canonical integrated-bus workflow is itself the Temporal child that
    # the parent just awaited.  Its current live result intentionally has no
    # nested child_wf_ok field; that must not make a successful parent->child
    # execution fail acceptance.
    current_live_shape = dict(result)
    current_live_shape.pop("child_wf_ok")
    current_live = summarize_langgraph_child(spec, current_live_shape)
    assert current_live["passed"] is True
    assert current_live["checks"]["child_wf_ok"] is False
    assert current_live["not_applicable_checks"] == ["child_wf_ok"]

    failed_result = dict(result)
    failed_result["promotion_gate_passed"] = False
    failed = summarize_langgraph_child(spec, failed_result)
    assert failed["passed"] is False
    assert "promotion_gate_passed" in failed["failed_checks"]
    wrong_provider_result = dict(result)
    wrong_provider_result["worker_lane_provider"] = "qwen_prepaid_cheap_worker"
    wrong_provider = summarize_langgraph_child(
        spec,
        wrong_provider_result,
        required_worker_provider="grok_acpx_headless",
    )
    assert wrong_provider["passed"] is False
    assert "worker_lane_provider_matches_required" in wrong_provider["failed_checks"]
    required_grok = summarize_langgraph_child(
        spec,
        result,
        required_worker_provider="grok_acpx_headless",
    )
    assert required_grok["passed"] is True

    missing_explicit_zero = dict(result)
    missing_explicit_zero.pop("non_grok_model_invocations")
    strict_failure = summarize_langgraph_child(spec, missing_explicit_zero)
    assert strict_failure["passed"] is False
    assert "non_grok_model_invocations_zero" in strict_failure["failed_checks"]

    legacy_result = {
        key: value
        for key, value in result.items()
        if key
        not in {
            "child_wf_ok",
            "grok_only_mode",
            "grok_fanin_ok",
            "grok_fanin_manifest_ref",
            "grok_fanin_lane_count",
            "non_grok_model_invocations",
            "fallback_model_invocation_performed",
            "memory_model_bind_frozen",
            "pro_review_provider",
        }
    }
    legacy = summarize_langgraph_child(
        spec,
        legacy_result,
        strict_grok_only=False,
    )
    assert legacy["passed"] is True
    assert "grok_only_mode" not in legacy["checks"]

    legacy_old_build = summarize_langgraph_child(
        spec,
        legacy_result,
        strict_grok_only=False,
        legacy_require_child_wf=True,
    )
    assert legacy_old_build["passed"] is False
    assert legacy_old_build["failed_checks"] == ["child_wf_ok"]

    prefanned_result = dict(result)
    prefanned_result.update(
        {
            "worker_lane_mode": "grok_ready_frontier_fanin",
            "langgraph_send_wired": False,
            "child_wf_ok": False,
            "parallel_succeeded": 0,
        }
    )
    parent_fanin = {
        "ok": True,
        "provider_id": "grok_acpx_headless",
        "model": "grok-4.5",
        "succeeded": 2,
        "failed": 0,
        "lane_count": 2,
        "ready_width": 2,
    }
    prefanned = summarize_langgraph_child(
        spec,
        prefanned_result,
        required_worker_provider="grok_acpx_headless",
        parent_grok_fanin=parent_fanin,
    )
    assert prefanned["passed"] is True
    assert prefanned["checks"]["langgraph_send_wired"] is False
    assert prefanned["checks"]["parallel_succeeded"] is False
    assert prefanned["not_applicable_checks"] == [
        "child_wf_ok",
        "langgraph_send_wired",
        "parallel_succeeded",
    ]

    invalid_parent = summarize_langgraph_child(
        spec,
        prefanned_result,
        required_worker_provider="grok_acpx_headless",
        parent_grok_fanin={**parent_fanin, "succeeded": 0},
    )
    assert invalid_parent["passed"] is False
    assert "parent_grok_fanin_succeeded" in invalid_parent["failed_checks"]
    assert "langgraph_send_wired" in invalid_parent["failed_checks"]

    partial_parent = summarize_langgraph_child(
        spec,
        prefanned_result,
        required_worker_provider="grok_acpx_headless",
        parent_grok_fanin={
            **parent_fanin,
            "succeeded": 1,
            "failed": 1,
        },
    )
    assert partial_parent["passed"] is False
    assert "parent_grok_fanin_succeeded" in partial_parent["failed_checks"]
    assert "langgraph_send_wired" in partial_parent["failed_checks"]

    inflated_width_result = dict(prefanned_result)
    inflated_width_result["grok_fanin_lane_count"] = 5
    inflated_width = summarize_langgraph_child(
        spec,
        inflated_width_result,
        required_worker_provider="grok_acpx_headless",
        parent_grok_fanin={
            **parent_fanin,
            "lane_count": 0,
            "ready_width": 5,
        },
    )
    assert inflated_width["passed"] is False
    assert "parent_grok_fanin_width_present" in inflated_width["failed_checks"]
    assert "child_grok_width_matches_parent" in inflated_width["failed_checks"]


def test_t9_promoted_intake_is_real_task_material(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XINAO_PROMOTED_INTAKE_ARTIFACT_DIR", str(tmp_path))
    inp = temporal_activities.PromotedActivityInput(
        task_id="task-real-input",
        workflow_id="workflow-real-input",
        generation=3,
        immutable_intent_hash="intent-hash",
        title="真实标题",
        goal="真实目标",
        source_thread_id="thread-1",
        owner="codex",
        decision_hash="decision-hash",
        operation_id="start:task-real-input:g3",
    )
    result = temporal_activities.write_promoted_intake_artifact(inp)
    assert result["ok"] is True
    path = tmp_path / "task-real-input_g3.md"
    text = path.read_text(encoding="utf-8")
    assert "真实标题" in text
    assert "真实目标" in text
    assert result["sha256"]


def test_t9_started_activity_rejects_unmounted_intake_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XINAO_PROMOTED_INTAKE_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(temporal_activities.activity, "heartbeat", lambda *_: None)
    monkeypatch.setattr(temporal_activities, "_evidence_container_path", lambda *_: None)
    with pytest.raises(OSError, match="container_path=None"):
        asyncio.run(
            temporal_activities.record_promoted_started(
                {
                    "task_id": "task-unmounted",
                    "workflow_id": "workflow-unmounted",
                    "generation": 0,
                    "immutable_intent_hash": "intent",
                    "decision_hash": "decision",
                    "title": "title",
                    "goal": "goal",
                    "owner": "codex",
                    "promoted_only": True,
                    "operation_id": "start:task-unmounted:g0",
                }
            )
        )


def test_t9_step_write_failure_cannot_report_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(temporal_activities.activity, "heartbeat", lambda *_: None)
    monkeypatch.setattr(temporal_activities, "_activity_info_meta", lambda: {})
    monkeypatch.setattr(
        temporal_activities,
        "write_promoted_step_artifact",
        lambda *_, **__: {"ok": False, "error_type": "OSError"},
    )
    result = asyncio.run(
        temporal_activities.execute_promoted_step(
            {
                "task_id": "task-fail",
                "workflow_id": "workflow-fail",
                "generation": 0,
                "immutable_intent_hash": "intent",
                "decision_hash": "decision",
                "title": "title",
                "goal": "goal",
                "owner": "codex",
                "promoted_only": True,
                "operation_id": "step:task-fail:g0:0",
                "step_index": 0,
            }
        )
    )
    assert result["ok"] is False
    assert result["phase"] == "step_failed"


def test_t9_temporal_terminal_converges_kernel_task(
    service: CoordinationService,
    db_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = _promote(service, "t9-kernel-terminal")
    service.temporal_start_promoted(
        actor="codex",
        task_id=task_id,
        idempotency_key="t9-kernel-terminal-start",
    )
    task = service.get_task(task_id)["task"]
    assert task["state"] == "running"
    meta = task["metadata"]
    monkeypatch.setattr(database_module, "default_db_path", lambda: db_path)
    inp = temporal_activities.PromotedActivityInput(
        task_id=task_id,
        workflow_id=meta["temporal_workflow_id"],
        generation=0,
        immutable_intent_hash=meta["decision_hash"],
        title=task["title"],
        goal=task["goal"],
        source_thread_id=task["source_thread_id"],
        owner="codex",
        decision_hash=meta["decision_hash"],
        operation_id="finalize:test:completed",
        kernel_lease_token=meta["temporal_kernel_lease_token"],
    )
    hook = temporal_activities._try_kernel_terminal_hook(
        inp,
        terminal="completed",
        payload={"langgraph_children": [{"passed": True}], "step_evidence": [{}]},
    )
    assert hook["ok"] is True
    assert service.get_task(task_id)["task"]["state"] == "completed"


def test_t9_temporal_terminal_rejects_missing_kernel_lease_token() -> None:
    inp = temporal_activities.PromotedActivityInput(
        task_id="task_missing_token",
        workflow_id="xinao-task-task_missing_token-g0",
        generation=0,
        immutable_intent_hash="intent",
        title="missing token",
        goal="must not green without kernel convergence",
        source_thread_id=None,
        owner="codex",
        decision_hash="intent",
        operation_id="finalize:test:missing-token",
        kernel_lease_token="",
    )
    hook = temporal_activities._try_kernel_terminal_hook(
        inp,
        terminal="completed",
        payload={"langgraph_children": [{"passed": True}], "step_evidence": [{}]},
    )
    assert hook == {
        "ok": False,
        "required": True,
        "reason": "missing_kernel_lease_token",
    }


def test_t9_user_stop_signals_exact_live_temporal_workflow(
    service: CoordinationService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XINAO_TEMPORAL_MOCK", "0")
    monkeypatch.setenv("XINAO_TEMPORAL_LIVE", "1")
    task_id = _promote(service, "t9-stop-signal")
    signaled: list[tuple[str, str, str]] = []

    def fake_start(self, envelope):
        return {
            "ok": True,
            "workflow_id": envelope.workflow_id,
            "workflow_type": envelope.workflow_type,
            "task_queue": envelope.task_queue,
            "run_id": "live-run",
            "mode": "live",
            "replayed": False,
        }

    def fake_cancel(self, workflow_id: str, *, run_id: str, reason: str):
        signaled.append((workflow_id, run_id, reason))
        return {
            "ok": True,
            "workflow_id": workflow_id,
            "run_id": run_id,
            "signal": "request_cancel",
            "terminal_confirmed": True,
        }

    monkeypatch.setattr(TemporalClient, "start_promoted_workflow", fake_start)
    monkeypatch.setattr(TemporalClient, "request_cancel_promoted_workflow", fake_cancel)
    started = service.temporal_start_promoted(actor="codex", task_id=task_id)
    stopped = service.user_stop(
        actor="user",
        reason="test live stop",
        idempotency_key="t9-live-stop-replay",
    )
    assert signaled == [(started["workflow_id"], "live-run", "user_stop:test live stop")]
    assert stopped["temporal_cancel_all_ok"] is True
    assert service.get_task(task_id)["task"]["state"] == "canceled"

    replayed = service.user_stop(
        actor="user",
        reason="test live stop",
        idempotency_key="t9-live-stop-replay",
    )
    assert replayed["replayed"] is True
    assert replayed["temporal_cancel_all_ok"] is True
    assert signaled == [
        (started["workflow_id"], "live-run", "user_stop:test live stop"),
        (started["workflow_id"], "live-run", "user_stop:test live stop"),
    ]
    events = service.db.execute_read(
        "SELECT event_type FROM events WHERE event_type='TemporalCancelConfirmed'"
    )
    assert len(events) == 1


def test_t9_live_cancel_requires_native_terminal_confirmation(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeHandle:
        cancelled = False

        async def describe(self):
            status = WorkflowExecutionStatus.CANCELED if self.cancelled else WorkflowExecutionStatus.RUNNING
            return SimpleNamespace(run_id="run-live", status=status)

        async def signal(self, name: str, reason: str) -> None:
            calls.append(("signal", (name, reason)))

        async def cancel(self) -> None:
            calls.append(("cancel", None))
            self.cancelled = True

    class FakeClient:
        handle = FakeHandle()

        def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None):
            calls.append(("get", (workflow_id, run_id)))
            return self.handle

        async def close(self) -> None:
            calls.append(("close", None))

    async def fake_connect(_address: str, _namespace: str):
        return FakeClient()

    monkeypatch.setattr(
        "xinao_coordination.temporal.client._connect_live_client",
        fake_connect,
    )
    client = TemporalClient(
        address="127.0.0.1:7233",
        namespace="default",
        task_queue="queue",
        workflow_type="XinaoPromotedTaskWorkflowV1",
        mock_mode=False,
        live_connect=True,
    )

    result = asyncio.run(
        client._async_request_cancel_promoted_workflow_live("wf-live", "run-live", "user_stop:test")
    )

    assert result["ok"] is True
    assert result["terminal_confirmed"] is True
    assert result["status_after"] == "CANCELED"
    assert calls[:3] == [
        ("get", ("wf-live", "run-live")),
        ("signal", ("request_cancel", "user_stop:test")),
        ("cancel", None),
    ]


def test_t9_live_cancel_replay_is_idempotent_for_exact_canceled_run(monkeypatch) -> None:
    calls: list[str] = []

    class FakeHandle:
        async def describe(self):
            return SimpleNamespace(
                run_id="run-canceled",
                status=WorkflowExecutionStatus.CANCELED,
            )

        async def signal(self, *_args) -> None:
            calls.append("signal")

        async def cancel(self) -> None:
            calls.append("cancel")

    class FakeClient:
        def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None):
            assert (workflow_id, run_id) == ("wf-canceled", "run-canceled")
            return FakeHandle()

        async def close(self) -> None:
            pass

    async def fake_connect(_address: str, _namespace: str):
        return FakeClient()

    monkeypatch.setattr(
        "xinao_coordination.temporal.client._connect_live_client",
        fake_connect,
    )
    client = TemporalClient(
        address="127.0.0.1:7233",
        namespace="default",
        task_queue="queue",
        workflow_type="XinaoPromotedTaskWorkflowV1",
        mock_mode=False,
        live_connect=True,
    )

    result = asyncio.run(
        client._async_request_cancel_promoted_workflow_live("wf-canceled", "run-canceled", "repeat stop")
    )

    assert result["ok"] is True
    assert result["already_terminal"] is True
    assert result["terminal_confirmed"] is True
    assert calls == []


def test_t9_stop_blocks_temporal_start(service: CoordinationService) -> None:
    task_id = _promote(service, "t9-stop")
    service.user_stop(actor="user", reason="t9 stop", idempotency_key="t9-stop")
    with pytest.raises(InvalidTransitionError):
        service.temporal_start_promoted(actor="codex", task_id=task_id)
    service.clear_stop(actor="user", reason="clear", idempotency_key="t9-clear")


def test_t9_admin_cannot_start_temporal(service: CoordinationService) -> None:
    assert "admin" not in TASK_DISPATCHERS
    task_id = _promote(service, "t9-admin")
    with pytest.raises(AuthorizationError):
        service.temporal_start_promoted(actor="admin", task_id=task_id)


def test_t9_disabled_raises(service: CoordinationService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XINAO_TEMPORAL_ENABLED", "0")
    task_id = _promote(service, "t9-off")
    with pytest.raises(InvalidTransitionError):
        service.temporal_start_promoted(actor="codex", task_id=task_id)
