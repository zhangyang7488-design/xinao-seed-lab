from __future__ import annotations

import json
from pathlib import Path

from services.agent_runtime import codex_333_run_reconciler as reconciler


def worker_status() -> dict:
    return {
        "status": "polling",
        "pid": 1234,
        "process_alive": True,
        "task_queue": reconciler.DEFAULT_TASK_QUEUE,
        "temporal_address": reconciler.DEFAULT_TEMPORAL_ADDRESS,
        "matches_task_queue": True,
    }


def workflow(
    workflow_id: str,
    run_id: str,
    *,
    start_time: str = "2026-07-06T09:00:00Z",
    task_queue: str = reconciler.DEFAULT_TASK_QUEUE,
) -> dict:
    return {
        "execution": {"workflowId": workflow_id, "runId": run_id},
        "type": {"name": reconciler.DEFAULT_WORKFLOW_TYPE},
        "status": "WORKFLOW_EXECUTION_STATUS_RUNNING",
        "taskQueue": task_queue,
        "startTime": start_time,
    }


def test_run_reconciler_selects_single_stable_mainline(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"

    payload = reconciler.build(
        runtime_root=runtime,
        repo_root=repo,
        running_workflows_override=[
            workflow("xinao-codex-task-default_temporal_tmpabc-20260706_120000", "run-tmp"),
            workflow("codex-s-333-mainline-20260706", "run-main"),
        ],
        port_open_override=True,
        worker_status_override=worker_status(),
    )

    assert payload["validation"]["passed"] is True
    assert payload["decision"]["selected"] is True
    assert payload["decision"]["named_blocker"] == ""
    assert payload["decision"]["selected_workflow"]["workflow_id"] == "codex-s-333-mainline-20260706"
    assert payload["mainline_candidate_count"] == 1
    assert payload["no_signal_sent"] is True

    current_path = Path(payload["output_paths"]["current_index_latest"])
    current = json.loads(current_path.read_text(encoding="utf-8"))
    assert current["status"] == "current_333_run_index_ready"
    assert current["workflow_id"] == "codex-s-333-mainline-20260706"
    assert current["reconciler_schema_version"] == reconciler.SCHEMA_VERSION
    assert current["completion_claim_allowed"] is False

    manifest = json.loads(Path(payload["output_paths"]["capability_manifest"]).read_text(encoding="utf-8"))
    assert manifest["provider_id"] == "codex_s.333_run_reconciler"
    assert "current_333_run_index_writer" in manifest["capability_kinds"]

    registry = json.loads(Path(payload["output_paths"]["tool_registry"]).read_text(encoding="utf-8"))
    assert "codex_s.333_run_reconciler" in registry["provider_ids"]
    provider = [
        item
        for item in registry["providers"]
        if item["provider_id"] == "codex_s.333_run_reconciler"
    ][0]
    assert provider["five_layer_status"]["connected_to_333"] == (
        "current_333_run_index_reconcile_before_foreground_watch"
    )


def test_run_reconciler_accepts_backend_control_plane_mainline(tmp_path: Path) -> None:
    payload = reconciler.build(
        runtime_root=tmp_path / "runtime",
        repo_root=tmp_path / "repo",
        running_workflows_override=[
            workflow("codex-s-backend-control-plane-20260706-2351", "run-control-plane"),
        ],
        port_open_override=True,
        worker_status_override=worker_status(),
    )

    assert payload["validation"]["passed"] is True
    assert payload["decision"]["selected"] is True
    assert payload["decision"]["selected_workflow"]["workflow_id"] == (
        "codex-s-backend-control-plane-20260706-2351"
    )
    assert payload["mainline_candidate_count"] == 1

    current = json.loads(Path(payload["output_paths"]["current_index_latest"]).read_text(encoding="utf-8"))
    assert current["status"] == "current_333_run_index_ready"
    assert current["workflow_id"] == "codex-s-backend-control-plane-20260706-2351"


def test_run_reconciler_blocks_ambiguous_active_mainline(tmp_path: Path) -> None:
    payload = reconciler.build(
        runtime_root=tmp_path / "runtime",
        repo_root=tmp_path / "repo",
        running_workflows_override=[
            workflow("codex-s-333-mainline-20260706-r1", "run-1"),
            workflow("codex-s-333-mainline-20260706-r2", "run-2"),
            workflow("xinao-codex-task-default_temporal_tmpabc-20260706_120000", "run-tmp"),
        ],
        port_open_override=True,
        worker_status_override=worker_status(),
    )

    assert payload["validation"]["passed"] is True
    assert payload["decision"]["selected"] is False
    assert payload["decision"]["named_blocker"] == "AMBIGUOUS_ACTIVE_333_MAINLINE"
    assert payload["mainline_candidate_count"] == 2
    assert payload["decision"]["temporary_workflows_ignored"] == 1

    current = json.loads(Path(payload["output_paths"]["current_index_latest"]).read_text(encoding="utf-8"))
    assert current["status"] == "current_333_run_index_blocked"
    assert current["workflow_id"] == ""
    assert current["reconciliation"]["named_blocker"] == "AMBIGUOUS_ACTIVE_333_MAINLINE"
    assert current["reconciliation"]["ambiguous_candidates_require_user_or_controller_decision"] is True


def test_run_reconciler_blocks_when_only_temporary_runs_exist(tmp_path: Path) -> None:
    payload = reconciler.build(
        runtime_root=tmp_path / "runtime",
        repo_root=tmp_path / "repo",
        running_workflows_override=[
            workflow("xinao-codex-task-default_temporal_tmpabc-20260706_120000", "run-tmp"),
            workflow("verify-temporal-worker-dispatch-ledger-activity-20260702", "run-verify"),
        ],
        port_open_override=True,
        worker_status_override=worker_status(),
    )

    assert payload["validation"]["passed"] is True
    assert payload["decision"]["selected"] is False
    assert payload["decision"]["named_blocker"] == "NO_ACTIVE_333_MAINLINE"
    assert payload["mainline_candidate_count"] == 0
    assert {item["role"] for item in payload["classified_workflows"]} == {
        "temporary_probe_or_ad_hoc"
    }
