from __future__ import annotations

import json
from pathlib import Path

from services.agent_runtime import next_frontier_continuation_supervisor as supervisor


def _candidate(*, wave_id: str, action: str, action_id: str = "action-1") -> dict:
    return {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "next_frontier_ready",
        "work_id": supervisor.WORK_ID,
        "parent_task_id": supervisor.WORK_ID,
        "task_id": "test_task",
        "routing": "continue_same_task",
        "wave_id": wave_id,
        "should_continue_loop": True,
        "stop_allowed": False,
        "next_frontier": [
            {
                "action_id": action_id,
                "action": action,
                "why": "test next action",
                "requires": ["runtime evidence"],
            }
        ],
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_execution_controller": True,
    }


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_promotes_candidate_to_canonical_and_dispatch_signal(tmp_path: Path) -> None:
    payload = supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=_candidate(
            wave_id="wave-1",
            action="evaluate_smoked_candidate_adapter_bindings_for_capability_gateway",
        ),
        source_kind="test",
        source_ref="test-ref",
    )

    assert payload["promotion_status"] == "promoted"
    assert payload["auto_continue_same_workflow"] is True
    assert (
        payload["auto_continue_same_task_signal"]["phase_execution"]["worker_kind"]
        == "implementation_worker"
    )
    canonical = _read(tmp_path / "state" / "next_frontier_machine_actions" / "latest.json")
    assert canonical["_continuation_supervisor"]["sequence"] == 1
    assert canonical["_continuation_supervisor"]["source_kind"] == "test"


def test_dedupes_same_candidate_without_sequence_bump(tmp_path: Path) -> None:
    candidate = _candidate(
        wave_id="wave-1",
        action="evaluate_smoked_candidate_adapter_bindings_for_capability_gateway",
    )
    first = supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=candidate,
        source_kind="test",
    )
    second = supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=candidate,
        source_kind="test",
    )

    assert first["sequence"] == 1
    assert second["promotion_status"] == "deduped"
    assert second["sequence"] == 1


def test_same_identity_old_canonical_is_upgraded_with_supervisor_metadata(tmp_path: Path) -> None:
    candidate = _candidate(
        wave_id="wave-1",
        action="evaluate_smoked_candidate_adapter_bindings_for_capability_gateway",
    )
    canonical_path = tmp_path / "state" / "next_frontier_machine_actions" / "latest.json"
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")

    payload = supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=candidate,
        source_kind="upgrade-test",
    )

    canonical = _read(canonical_path)
    assert payload["promotion_status"] == "promoted"
    assert payload["promotion_reason"] == "same_frontier_identity_metadata_upgrade"
    assert canonical["_continuation_supervisor"]["sentinel"] == supervisor.SENTINEL
    assert canonical["_continuation_supervisor"]["sequence"] == 1


def test_stale_lower_rank_action_does_not_overwrite_current_canonical(tmp_path: Path) -> None:
    high = _candidate(
        wave_id="wave-high",
        action="monitor_temporal_source_family_adapter_value_eval_activity",
        action_id="monitor",
    )
    low = _candidate(
        wave_id="wave-low",
        action="continue_source_frontier_claimcard_absorption",
        action_id="source-frontier",
    )
    supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=high,
        source_kind="test-high",
    )
    stale = supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=low,
        source_kind="test-low",
    )

    canonical = _read(tmp_path / "state" / "next_frontier_machine_actions" / "latest.json")
    assert stale["promotion_status"] == "stale_rejected"
    assert stale["auto_continue_same_workflow"] is True
    assert stale["named_blocker"] == ""
    assert stale["candidate_rejection_reason"] == "incoming_rank_10_below_current_rank_80"
    assert canonical["wave_id"] == "wave-high"
    assert (
        canonical["next_frontier"][0]["action"]
        == "monitor_temporal_source_family_adapter_value_eval_activity"
    )


def test_restart_recovery_reads_canonical_and_rebuilds_dispatch_intent(tmp_path: Path) -> None:
    supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=_candidate(
            wave_id="wave-recover",
            action="refresh_capability_gateway_snapshot_with_evaluated_source_candidates",
            action_id="refresh",
        ),
        source_kind="test",
    )

    recovered = supervisor.supervise_latest_next_frontier(
        runtime_root=tmp_path,
        source_kind="restart-test",
        workflow_id="wf",
        workflow_run_id="run",
    )

    assert recovered["auto_continue_same_workflow"] is True
    assert recovered["auto_continue_same_task_signal"]["workflow_id"] == "wf"
    dispatch = _read(
        tmp_path
        / "state"
        / "next_frontier_continuation_supervisor"
        / "dispatch_intent"
        / "latest.json"
    )
    assert dispatch["status"] == "next_frontier_dispatch_intent_ready"


def test_legacy_runtime_reference_is_rejected(tmp_path: Path) -> None:
    candidate = _candidate(
        wave_id="wave-legacy",
        action="monitor_temporal_source_family_adapter_value_eval_activity",
    )
    candidate["legacy_ref"] = r"D:\XINAO_CLEAN_RUNTIME\latest.json"

    payload = supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=candidate,
        source_kind="test",
    )

    assert payload["promotion_status"] == "legacy_rejected"
    assert payload["auto_continue_same_workflow"] is False
    assert "D_CLEAN_RUNTIME_REFERENCE_IN_HOT_PATH" in payload["named_blocker"]


def test_terminal_no_pending_action_still_updates_canonical(tmp_path: Path) -> None:
    open_candidate = _candidate(
        wave_id="wave-open",
        action="consume_source_frontier_batch",
        action_id="consume",
    )
    supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=open_candidate,
        source_kind="test",
    )
    terminal = {
        **open_candidate,
        "wave_id": "wave-terminal",
        "should_continue_loop": False,
        "next_frontier": [],
    }

    payload = supervisor.promote_candidate_next_frontier(
        runtime_root=tmp_path,
        candidate=terminal,
        source_kind="test",
    )

    canonical = _read(tmp_path / "state" / "next_frontier_machine_actions" / "latest.json")
    assert payload["promotion_status"] == "promoted"
    assert payload["auto_continue_same_workflow"] is False
    assert canonical["wave_id"] == "wave-terminal"
    assert canonical["should_continue_loop"] is False
