"""T6–T8 fault injection / negative tests (isolated tmp DB; no live Temporal / M-KEEP / desktop).

Negative invariants:
1. M-BG max_parallel capacity → reject further dispatch (ConflictError)
2. admin actor cannot mbg_dispatch (AuthorizationError; TASK_DISPATCHERS = user|brains only)
3. start_transport without experimental flag → ValidationError
4. route recommendation=background never controls execution (score_controls_execution=false)
5. mbg_finish with wrong lease_token → LeaseError
6. mbg_finish success=False → task.state=failed
7. old lease_token after mbg_finish → LeaseError (fenced)
"""

from __future__ import annotations

import pytest

from xinao_coordination.errors import (
    AuthorizationError,
    ConflictError,
    LeaseError,
    ValidationError,
)
from xinao_coordination.models import RouteSignals, assess_route
from xinao_coordination.service import CoordinationService, TASK_DISPATCHERS
from tests.conftest import accepted_thread


def _promote(service: CoordinationService, suffix: str) -> str:
    thread_id = accepted_thread(service, suffix)
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash=f"resolution-{suffix}",
        title=f"t6t8-fi task {suffix}",
        goal="fault injection disposable work",
        idempotency_key=f"promote-fi-{suffix}",
    )
    task = promoted["task"]
    assert isinstance(task, dict)
    assert task["metadata"]["promoted"] is True
    return str(task["task_id"])


def _mbg_dispatch_running(
    service: CoordinationService, suffix: str, *, idem: str
) -> tuple[str, str]:
    """Promote + mbg_dispatch; return (task_id, task lease_token)."""
    task_id = _promote(service, suffix)
    dispatched = service.mbg_dispatch(
        actor="codex",
        task_id=task_id,
        idempotency_key=idem,
    )
    assert dispatched["ok"] is True
    assert dispatched["task"]["state"] == "running"
    lease = str(dispatched["lease_token"] or "")
    assert lease
    return task_id, lease


def test_mbg_max_parallel_capacity_rejects(
    service: CoordinationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When in_flight >= max_parallel, further mbg_dispatch raises ConflictError."""
    monkeypatch.setenv("XINAO_MBG_MAX_PARALLEL", "1")
    monkeypatch.delenv("XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS", raising=False)

    task_a = _promote(service, "cap-a")
    first = service.mbg_dispatch(
        actor="codex",
        task_id=task_a,
        idempotency_key="fi-cap-1",
    )
    assert first["ok"] is True
    assert first["spawned"] is False

    status = service.mbg_status()
    assert status["policy"]["max_parallel"] == 1
    assert status["in_flight_operations"] >= 1
    assert status["capacity_remaining"] == 0

    task_b = _promote(service, "cap-b")
    with pytest.raises(ConflictError, match="max_parallel|capacity") as exc:
        service.mbg_dispatch(
            actor="codex",
            task_id=task_b,
            idempotency_key="fi-cap-2",
        )
    details = getattr(exc.value, "details", None) or {}
    assert details.get("max_parallel") == 1
    assert int(details.get("in_flight", 0)) >= 1


def test_admin_cannot_mbg_dispatch(service: CoordinationService) -> None:
    """Permission model: TASK_DISPATCHERS excludes admin → AuthorizationError."""
    assert "admin" not in TASK_DISPATCHERS

    task_id = _promote(service, "admin-deny")
    with pytest.raises(AuthorizationError, match="admin cannot M-BG dispatch") as exc:
        service.mbg_dispatch(
            actor="admin",
            task_id=task_id,
            idempotency_key="fi-admin-mbg",
        )
    details = getattr(exc.value, "details", None) or {}
    allowed = details.get("allowed") or []
    assert "admin" not in allowed
    assert "codex" in allowed


def test_start_transport_requires_experimental_flag(
    service: CoordinationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start_transport=True without XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS → ValidationError."""
    monkeypatch.delenv("XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS", raising=False)
    monkeypatch.setenv("XINAO_MBG_MAX_PARALLEL", "4")

    task_id = _promote(service, "transport-deny")
    with pytest.raises(ValidationError, match="start_transport|EXPERIMENTAL") as exc:
        service.mbg_dispatch(
            actor="codex",
            task_id=task_id,
            idempotency_key="fi-transport-no-flag",
            start_transport=True,
        )
    details = getattr(exc.value, "details", None) or {}
    assert details.get("start_transport") is True


def test_route_background_does_not_control_execution(service: CoordinationService) -> None:
    """T6: background recommendation is advisory; score never gates execution."""
    pure = assess_route(
        RouteSignals(parallelism=0.9, uncertainty=0.1, latency_cost=0.1, impact=0.2)
    )
    assert pure.recommendation == "background"
    assert pure.advisory_only is True
    assert pure.score_controls_execution is False

    via_service = service.assess(
        {
            "parallelism": 0.95,
            "uncertainty": 0.05,
            "latency_cost": 0.1,
            "impact": 0.2,
        }
    )
    assert via_service["recommendation"] == "background"
    assert via_service.get("advisory_only") is True
    assert via_service.get("score_controls_execution") is False


def test_mbg_finish_wrong_lease_token_rejected(
    service: CoordinationService, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mbg_finish with wrong lease_token must raise LeaseError; task stays running."""
    monkeypatch.setenv("XINAO_MBG_SCRATCH_ROOT", str(tmp_path / "scratch-wrong-lease"))
    task_id, good_lease = _mbg_dispatch_running(
        service, "fin-wrong-lease", idem="fi-fin-wrong-lease-disp"
    )
    wrong = f"wrong-{good_lease}"
    assert wrong != good_lease

    with pytest.raises(LeaseError, match="lease token|does not match"):
        service.mbg_finish(
            actor="admin",
            task_id=task_id,
            lease_token=wrong,
            result_summary="should not finish",
            evidence=[{"kind": "note", "text": "bad lease"}],
            success=True,
            idempotency_key="fi-fin-wrong-lease",
        )

    current = service.get_task(task_id)["task"]
    assert current["state"] == "running"
    assert current["lease_token"] == good_lease


def test_mbg_finish_fail_path_sets_task_failed(
    service: CoordinationService, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mbg_finish(success=False) → outcome=failed and task.state=failed (retryable=False)."""
    monkeypatch.setenv("XINAO_MBG_SCRATCH_ROOT", str(tmp_path / "scratch-fail-path"))
    task_id, lease = _mbg_dispatch_running(
        service, "fin-fail", idem="fi-fin-fail-disp"
    )

    finished = service.mbg_finish(
        actor="admin",
        task_id=task_id,
        lease_token=lease,
        result_summary="worker crashed",
        evidence=[{"kind": "note", "text": "fail path"}],
        success=False,
        error="injected failure for fault test",
        idempotency_key="fi-fin-fail",
    )
    assert finished["ok"] is True
    assert finished["outcome"] == "failed"
    assert finished["task"]["state"] == "failed"
    assert finished["task"]["lease_token"] is None
    reason = finished["task"].get("failure_reason") or ""
    assert "injected failure" in reason or "worker crashed" in reason

    current = service.get_task(task_id)["task"]
    assert current["state"] == "failed"
    assert current["lease_token"] is None


def test_mbg_finish_old_token_after_finish_rejected(
    service: CoordinationService, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After successful mbg_finish, reusing the old lease_token must be rejected."""
    monkeypatch.setenv("XINAO_MBG_SCRATCH_ROOT", str(tmp_path / "scratch-old-token"))
    task_id, lease = _mbg_dispatch_running(
        service, "fin-old-tok", idem="fi-fin-old-tok-disp"
    )

    first = service.mbg_finish(
        actor="admin",
        task_id=task_id,
        lease_token=lease,
        result_summary="mbg done first finish",
        evidence=[{"kind": "note", "text": "first"}],
        success=True,
        idempotency_key="fi-fin-old-tok-1",
    )
    assert first["outcome"] == "completed"
    assert first["task"]["state"] == "completed"
    assert first["task"]["lease_token"] is None

    with pytest.raises(LeaseError):
        service.mbg_finish(
            actor="admin",
            task_id=task_id,
            lease_token=lease,
            result_summary="stale reuse",
            evidence=[{"kind": "note", "text": "stale"}],
            success=True,
            idempotency_key="fi-fin-old-tok-2",
        )

    # Also reject old token on the fail path after completed.
    with pytest.raises(LeaseError):
        service.mbg_finish(
            actor="admin",
            task_id=task_id,
            lease_token=lease,
            result_summary="stale fail reuse",
            evidence=[{"kind": "note", "text": "stale-fail"}],
            success=False,
            error="stale",
            idempotency_key="fi-fin-old-tok-3",
        )

    current = service.get_task(task_id)["task"]
    assert current["state"] == "completed"
    assert current["lease_token"] is None
