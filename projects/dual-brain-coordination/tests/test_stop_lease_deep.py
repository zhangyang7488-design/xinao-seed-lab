"""G11 deep stop / lease fencing — service API only, tmp DB.

Coverage (deeper than T5/T8/T9 smoke):
1. stop active → mbg_dispatch and temporal_start_promoted both rejected
2. clear_stop explicit → promote / mbg / temporal start allowed again
3. expired lease → complete_task rejected (fencing; no silent success)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import accepted_thread
from xinao_coordination.agent_operations import AgentOperationStore
from xinao_coordination.errors import InvalidTransitionError, LeaseError, ValidationError
from xinao_coordination.service import CoordinationService
from xinao_coordination.temporal.client import reset_mock_registry


def _promote(service: CoordinationService, suffix: str) -> str:
    thread_id = accepted_thread(service, suffix)
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash=f"resolution-{suffix}",
        title=f"g11 task {suffix}",
        goal="stop/lease deep fence",
        idempotency_key=f"g11-promote-{suffix}",
    )
    task = promoted["task"]
    assert isinstance(task, dict)
    assert task["metadata"]["promoted"] is True
    return str(task["task_id"])


@pytest.fixture(autouse=True)
def _g11_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XINAO_MBG_ENABLED", "1")
    monkeypatch.setenv("XINAO_MBG_SCRATCH_ROOT", str(tmp_path / "mbg_scratch"))
    monkeypatch.setenv("XINAO_TEMPORAL_ENABLED", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_MOCK", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_LIVE", "0")
    monkeypatch.setenv(
        "XINAO_COORD_STOP_DIR",
        str(tmp_path / "stop_mirror"),
    )
    reset_mock_registry()


def test_stop_rejects_mbg_and_temporal_start(service: CoordinationService) -> None:
    """After user_stop, neither M-BG dispatch nor Temporal start may proceed."""
    task_mbg = _promote(service, "stop-mbg")
    task_tmp = _promote(service, "stop-tmp")

    # baseline: both starts work while stop is clear
    assert service.stop_status()["active"] is False
    ok_mbg = service.mbg_dispatch(actor="codex", task_id=task_mbg, idempotency_key="g11-mbg-pre")
    assert ok_mbg["ok"] is True
    ok_tmp = service.temporal_start_promoted(actor="codex", task_id=task_tmp, idempotency_key="g11-tmp-pre")
    assert ok_tmp["ok"] is True

    # fresh tasks so stop freezes queued promotees without depending on prior bind
    task_mbg2 = _promote(service, "stop-mbg2")
    task_tmp2 = _promote(service, "stop-tmp2")

    raised = service.user_stop(
        actor="user",
        reason="G11 stop fence mbg+temporal",
        idempotency_key="g11-stop-raise-1",
    )
    assert raised["active"] is True
    assert raised["resumes_automatically"] is False
    assert service.stop_status()["active"] is True
    # active queued/running tasks are canceled by stop
    assert service.get_task(task_mbg2)["task"]["state"] == "canceled"
    assert service.get_task(task_tmp2)["task"]["state"] == "canceled"

    with pytest.raises(InvalidTransitionError, match="stop is active"):
        service.mbg_dispatch(actor="codex", task_id=task_mbg2, idempotency_key="g11-mbg-blocked")
    with pytest.raises(InvalidTransitionError, match="stop is active"):
        service.temporal_start_promoted(actor="codex", task_id=task_tmp2, idempotency_key="g11-tmp-blocked")

    # stop does not auto-clear
    assert service.stop_status()["active"] is True


def test_clear_stop_allows_promote_then_mbg_and_temporal(
    service: CoordinationService,
) -> None:
    """clear_stop is required; after clear, promote + mbg + temporal start work again."""
    blocked_thread = accepted_thread(service, "g11-blocked")
    service.user_stop(
        actor="user",
        reason="G11 freeze promote",
        idempotency_key="g11-stop-raise-2",
    )
    assert service.stop_status()["active"] is True

    with pytest.raises(InvalidTransitionError, match="stop is active"):
        service.promote_to_task(
            actor="codex",
            source_thread_id=blocked_thread,
            decision_hash="resolution-g11-blocked",
            title="blocked promote",
            goal="must wait for clear",
            idempotency_key="g11-promote-while-stop",
        )
    with pytest.raises(InvalidTransitionError, match="stop is active"):
        # any residual task id would also be blocked; use a synthetic queued path via dispatch
        # after stop cancel, dispatch itself is frozen
        service.dispatch_task(
            actor="codex",
            title="frozen dispatch",
            goal="no",
            explicit_non_consensus=True,
            idempotency_key="g11-dispatch-while-stop",
        )

    cleared = service.clear_stop(
        actor="user",
        reason="G11 explicit resume",
        idempotency_key="g11-stop-clear-2",
    )
    assert cleared["active"] is False
    assert service.stop_status()["active"] is False

    # same accepted thread can now promote
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=blocked_thread,
        decision_hash="resolution-g11-blocked",
        title="after clear promote",
        goal="unfrozen",
        idempotency_key="g11-promote-after-clear",
    )
    task_id = str(promoted["task"]["task_id"])
    assert promoted["task"]["state"] == "queued"
    assert promoted["task"]["metadata"]["promoted"] is True

    mbg = service.mbg_dispatch(actor="codex", task_id=task_id, idempotency_key="g11-mbg-after-clear")
    assert mbg["ok"] is True
    assert mbg["operation"]["state"] == "queued"

    # separate promoted task for temporal (mbg binds running lease on first task)
    task_tmp = _promote(service, "g11-tmp-after-clear")
    temporal = service.temporal_start_promoted(
        actor="codex",
        task_id=task_tmp,
        idempotency_key="g11-tmp-after-clear",
    )
    assert temporal["ok"] is True
    assert temporal["mode"] == "mock"
    assert temporal["workflow_id"].startswith("xinao-task-")


def test_expired_lease_complete_rejected(db_path: Path) -> None:
    """complete_task with an expired lease token is fenced (LeaseError), not completed."""
    now = [1_700_000_000_000]
    service = CoordinationService(db_path, clock_ms=lambda: now[0])

    dispatched = service.dispatch_task(
        actor="codex",
        title="g11 lease expiry",
        goal="must not complete after lease death",
        explicit_non_consensus=True,
        idempotency_key="g11-dispatch-lease",
    )
    task_id = str(dispatched["task"]["task_id"])

    claim = service.claim_task(lease_seconds=1, idempotency_key="g11-claim")
    token = str(claim["lease_token"])
    assert claim["task"]["task_id"] == task_id
    service.start_task(task_id=task_id, lease_token=token, idempotency_key="g11-start")
    assert service.get_task(task_id)["task"]["state"] == "running"

    # advance past lease_expires_at_ms without reclaim/sweep
    now[0] += 1_500

    with pytest.raises(LeaseError, match="lease expired"):
        service.complete_task(
            task_id=task_id,
            lease_token=token,
            result_summary="late complete must fail",
            evidence=[{"kind": "g11", "result": "should-not-land"}],
            idempotency_key="g11-expired-complete",
        )

    current = service.get_task(task_id)["task"]
    # still running until sweep/reclaim recovers; never silently completed
    assert current["state"] == "running"
    assert current["result_summary"] is None

    # reclaim fences old token; old complete remains rejected
    recovered = service.claim_task(lease_seconds=30, idempotency_key="g11-reclaim")
    assert recovered["task"]["task_id"] == task_id
    assert recovered["lease_token"] != token
    with pytest.raises(LeaseError):
        service.complete_task(
            task_id=task_id,
            lease_token=token,
            result_summary="stale token after reclaim",
            evidence=[{"kind": "g11", "result": "stale"}],
            idempotency_key="g11-stale-complete",
        )


def test_stop_then_clear_epoch_and_status_surface(service: CoordinationService) -> None:
    """Stop epoch advances; mbg/temporal status surfaces stop_active consistently."""
    before = service.stop_status()
    assert before["active"] is False
    epoch0 = int(before["epoch"])

    raised = service.user_stop(actor="user", reason="G11 epoch", idempotency_key="g11-epoch-raise")
    assert raised["active"] is True
    assert int(raised["epoch"]) == epoch0 + 1
    assert service.mbg_status()["stop_active"] is True
    assert service.temporal_status()["stop_active"] is True

    cleared = service.clear_stop(actor="user", reason="G11 epoch clear", idempotency_key="g11-epoch-clear")
    assert cleared["active"] is False
    # clear does not auto-promote or re-queue canceled work
    assert service.stop_status()["active"] is False
    assert service.mbg_status()["stop_active"] is False
    assert service.temporal_status()["stop_active"] is False


def test_user_stop_converges_attempt_worker_and_bound_operation(
    service: CoordinationService,
) -> None:
    temporal_task = _promote(service, "g11-stop-ledger-temporal")
    temporal = service.temporal_start_promoted(
        actor="codex",
        task_id=temporal_task,
        idempotency_key="g11-stop-ledger-temporal-start",
    )
    temporal_view = service.get_task(temporal_task)
    assert temporal_view["task"]["state"] == "running"
    assert temporal_view["attempts"][0]["state"] == "running"
    temporal_worker = f"temporal:{temporal['workflow_id']}"

    mbg_task = _promote(service, "g11-stop-ledger-mbg")
    mbg = service.mbg_dispatch(
        actor="codex",
        task_id=mbg_task,
        idempotency_key="g11-stop-ledger-mbg-dispatch",
    )
    operation_id = str(mbg["operation"]["operation_id"])

    stopped = service.user_stop(
        actor="user",
        reason="G11 converge all execution ledgers",
        idempotency_key="g11-stop-ledger-raise",
    )

    assert stopped["agent_cancel_all_ok"] is True
    temporal_after = service.get_task(temporal_task)
    assert temporal_after["task"]["state"] == "canceled"
    attempt = temporal_after["attempts"][0]
    assert attempt["state"] == "canceled"
    assert attempt["finished_at_ms"] is not None
    assert attempt["failure_reason"].startswith("user_stop:")
    worker = service.db.execute_read(
        "SELECT status,last_lease_token FROM workers WHERE worker_id=?",
        (temporal_worker,),
    )[0]
    assert worker["status"] == "stale"
    assert worker["last_lease_token"] is None

    operation = AgentOperationStore(service.db.path).get(operation_id)["operation"]
    assert operation["state"] == "canceled"
    assert operation["lease_token"] is None
    assert operation["completed_at_ms"] is not None


def test_user_stop_rejects_unimplemented_scoped_semantics(service: CoordinationService) -> None:
    with pytest.raises(ValidationError, match="scoped Stop is not implemented"):
        service.user_stop(actor="user", reason="must not fake scope", scope="task-123")

    assert service.stop_status()["active"] is False
