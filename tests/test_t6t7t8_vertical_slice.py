"""T6 route + T7 agent ops envelope + T8 M-BG explicit dispatch vertical tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import accepted_thread
from xinao_coordination.errors import InvalidTransitionError, ValidationError
from xinao_coordination.models import RouteSignals, assess_route
from xinao_coordination.service import CoordinationService


def _promote(service: CoordinationService, suffix: str) -> str:
    thread_id = accepted_thread(service, suffix)
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash=f"resolution-{suffix}",
        title=f"t6t8 task {suffix}",
        goal="background disposable work",
        idempotency_key=f"promote-{suffix}",
    )
    task = promoted["task"]
    assert isinstance(task, dict)
    assert task["metadata"]["promoted"] is True
    return str(task["task_id"])


def test_t6_route_advisory_and_background() -> None:
    zero = assess_route(RouteSignals())
    assert zero.advisory_only is True
    assert zero.score_controls_execution is False
    assert zero.recommendation == "direct"

    bg = assess_route(RouteSignals(parallelism=0.9, uncertainty=0.1, latency_cost=0.1, impact=0.2))
    assert bg.recommendation == "background"
    assert bg.advisory_only is True
    assert "disposable_or_batch_background_fit" in bg.reasons

    forced = assess_route(RouteSignals(uncertainty=1, requested_mode="background"))
    assert forced.recommendation == "background"
    assert forced.overridden_by_request is True


def test_t7_agent_operation_submit_envelope(service: CoordinationService, db_path: Path) -> None:
    from xinao_coordination.agent_operations import AgentOperationStore

    store = AgentOperationStore(db_path)
    first = store.submit(
        actor="codex",
        prompt="t7 envelope",
        session_name="t7-session",
        cwd=Path(__file__).resolve().parents[1],
        idempotency_key="t7-key-1",
        metadata={"worker_contract": ["start", "heartbeat", "complete", "fail"]},
    )
    assert first["ok"] is True
    op = first["operation"]
    assert op["state"] == "queued"
    replay = store.submit(
        actor="codex",
        prompt="t7 envelope",
        session_name="t7-session",
        cwd=Path(__file__).resolve().parents[1],
        idempotency_key="t7-key-1",
        metadata={"worker_contract": ["start", "heartbeat", "complete", "fail"]},
    )
    assert replay["replayed"] is True
    assert replay["operation"]["operation_id"] == op["operation_id"]


def test_t8_mbg_status_defaults(service: CoordinationService) -> None:
    st = service.mbg_status()
    assert st["ok"] is True
    assert st["auto_dispatch"] is False
    assert st["policy"]["enabled"] is True
    assert st["policy"]["auto_dispatch"] is False
    assert st["policy"]["require_explicit_promote"] is True
    assert st["policy"]["stop_preempts"] is True
    assert st["temporal_owner"] is False


def test_t8_mbg_requires_promoted_task(service: CoordinationService) -> None:
    dispatched = service.dispatch_task(
        actor="codex",
        title="not promoted",
        goal="x",
        explicit_non_consensus=True,
        idempotency_key="non-promoted-1",
    )
    task_id = dispatched["task"]["task_id"]
    with pytest.raises(ValidationError):
        service.mbg_dispatch(actor="codex", task_id=task_id, idempotency_key="mbg-bad")


def test_t8_mbg_dispatch_idempotent_and_stop(service: CoordinationService) -> None:
    task_id = _promote(service, "mbg1")
    first = service.mbg_dispatch(actor="codex", task_id=task_id, idempotency_key="mbg-1")
    assert first["ok"] is True
    assert first["auto_dispatch"] is False
    assert first["spawned"] is False
    op_id = first["operation"]["operation_id"]
    second = service.mbg_dispatch(actor="codex", task_id=task_id, idempotency_key="mbg-1")
    assert second["replayed"] is True
    assert second["operation"]["operation_id"] == op_id

    service.user_stop(actor="user", reason="t8 stop test", idempotency_key="stop-mbg")
    with pytest.raises(InvalidTransitionError):
        service.mbg_dispatch(actor="codex", task_id=task_id, idempotency_key="mbg-after-stop")
    service.clear_stop(actor="user", reason="clear", idempotency_key="clear-mbg")


def test_t6_hybrid_route() -> None:
    result = assess_route(
        RouteSignals(
            complementarity=0.7,
            parallelism=0.7,
            novelty=0.5,
            uncertainty=0.4,
        )
    )
    assert result.recommendation == "hybrid"
    assert result.advisory_only is True
    assert result.score_controls_execution is False


def test_t8_mbg_disable_env(service: CoordinationService, monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = _promote(service, "dis")
    monkeypatch.setenv("XINAO_MBG_ENABLED", "0")
    st = service.mbg_status()
    assert st["policy"]["enabled"] is False
    with pytest.raises(InvalidTransitionError):
        service.mbg_dispatch(actor="codex", task_id=task_id, idempotency_key="dis-mbg")
    monkeypatch.setenv("XINAO_MBG_ENABLED", "1")
    # route/discuss still work while mbg off
    assert service.assess({"uncertainty": 0}).get("ok") is True


def test_t8_mbg_task_lease_lifecycle(
    service: CoordinationService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XINAO_MBG_SCRATCH_ROOT", str(tmp_path / "scratch2"))
    task_id = _promote(service, "lease1")
    dispatched = service.mbg_dispatch(actor="codex", task_id=task_id, idempotency_key="lease-mbg")
    assert dispatched["task"]["state"] == "running"
    lease = str(dispatched["lease_token"])
    assert lease
    assert dispatched["operation_lease_token"]
    finished = service.mbg_finish(
        actor="admin",
        task_id=task_id,
        lease_token=lease,
        result_summary="mbg done with evidence",
        evidence=[{"kind": "note", "text": "ok"}],
        success=True,
        idempotency_key="lease-fin",
    )
    assert finished["outcome"] == "completed"
    assert finished["task"]["state"] == "completed"
    assert finished["verification_status"] == "evidence_attached_not_independently_verified"
    opf = finished.get("operation_finish") or {}
    assert opf.get("ok") is True or opf.get("action") == "agent_operation.finish"


def test_t6t7t8_full_vertical(
    service: CoordinationService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XINAO_MBG_SCRATCH_ROOT", str(tmp_path / "scratch"))
    route = service.assess({"parallelism": 0.95, "uncertainty": 0.05, "latency_cost": 0.1, "impact": 0.2})
    assert route["recommendation"] == "background"
    assert route["advisory_only"] is True

    task_id = _promote(service, "vert")
    dispatched = service.mbg_dispatch(
        actor="codex",
        task_id=task_id,
        idempotency_key="vert-mbg",
    )
    assert dispatched["operation"]["state"] == "queued"
    assert dispatched["operation"]["metadata"]["m_bg"] is True
    assert dispatched["operation"]["metadata"]["task_id"] == task_id
    wt = dispatched["operation"]["metadata"].get("worktree_path")
    assert wt and Path(wt).is_dir()
    assert task_id in str(wt)

    status = service.mbg_status()
    assert status["in_flight_operations"] >= 1
