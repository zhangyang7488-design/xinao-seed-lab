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
    assert (
        payload["decision"]["selected_workflow"]["workflow_id"] == "codex-s-333-mainline-20260706"
    )
    assert payload["mainline_candidate_count"] == 1
    assert payload["no_signal_sent"] is True

    current_path = Path(payload["output_paths"]["current_index_latest"])
    current = json.loads(current_path.read_text(encoding="utf-8"))
    assert current["status"] == "current_333_run_index_ready"
    assert current["workflow_id"] == "codex-s-333-mainline-20260706"
    assert current["reconciler_schema_version"] == reconciler.SCHEMA_VERSION
    assert current["completion_claim_allowed"] is False
    assert current["control_plane_liveness"]["mode"] == "pure_liveness_read_model"
    assert current["control_plane_liveness"]["model_invocation_performed"] is False
    assert current["control_plane_liveness"]["no_provider_worker_dispatch"] is True

    manifest = json.loads(
        Path(payload["output_paths"]["capability_manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["provider_id"] == "codex_s.333_run_reconciler"
    assert "current_333_run_index_writer" in manifest["capability_kinds"]
    assert "pure_liveness_heartbeat" in manifest["capability_kinds"]

    registry = json.loads(
        Path(payload["output_paths"]["tool_registry"]).read_text(encoding="utf-8")
    )
    assert "codex_s.333_run_reconciler" in registry["provider_ids"]
    provider = [
        item
        for item in registry["providers"]
        if item["provider_id"] == "codex_s.333_run_reconciler"
    ][0]
    assert provider["five_layer_status"]["connected_to_333"] == (
        "current_333_run_index_reconcile_before_foreground_watch"
    )
    assert payload["control_plane_liveness"]["status"] == "control_plane_liveness_ready"
    assert payload["control_plane_liveness"]["no_codex_or_v4pro_supervisor_call"] is True
    assert payload["validation"]["checks"]["control_plane_liveness_no_model_invocation"] is True
    assert payload["validation"]["checks"]["control_plane_liveness_no_worker_dispatch"] is True


def test_run_reconciler_accepts_pollers_when_status_pid_is_stale(tmp_path: Path) -> None:
    stale_pid_but_polling = {
        **worker_status(),
        "pid": 19612,
        "process_alive": False,
        "pollers_seen": 2,
    }

    payload = reconciler.build(
        runtime_root=tmp_path / "runtime",
        repo_root=tmp_path / "repo",
        running_workflows_override=[
            workflow("codex-s-333-mainline-20260706", "run-main"),
        ],
        port_open_override=True,
        worker_status_override=stale_pid_but_polling,
    )

    assert payload["validation"]["passed"] is True
    assert payload["decision"]["selected"] is True
    assert payload["decision"]["named_blocker"] == ""
    current = json.loads(
        Path(payload["output_paths"]["current_index_latest"]).read_text(encoding="utf-8")
    )
    assert current["status"] == "current_333_run_index_ready"
    assert current["workflow_id"] == "codex-s-333-mainline-20260706"
    assert current["worker_status"]["pollers_seen"] == 2


def test_read_worker_status_overrides_stale_pid_with_live_process(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = tmp_path / "runtime"
    status_path = runtime / "state" / "temporal_codex_task_worker" / "status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(
            {
                "status": "polling",
                "pid": 19612,
                "process_alive": False,
                "task_queue": reconciler.DEFAULT_TASK_QUEUE,
                "temporal_address": reconciler.DEFAULT_TEMPORAL_ADDRESS,
                "pollers_seen": 4,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reconciler,
        "find_temporal_worker_processes",
        lambda task_queue: [
            {
                "pid": 26120,
                "parent_pid": 25184,
                "executable_path": str(
                    reconciler.DEFAULT_REPO / ".venv" / "Scripts" / "python.exe"
                ),
                "command_line": (
                    f"{reconciler.DEFAULT_REPO}\\.venv\\Scripts\\python.exe "
                    "-m services.agent_runtime.temporal_codex_task_workflow "
                    f"--worker --task-queue {task_queue}"
                ),
                "launched_from_s_venv": True,
            }
        ],
    )

    status = reconciler.read_worker_status(
        runtime,
        temporal_address=reconciler.DEFAULT_TEMPORAL_ADDRESS,
        task_queue=reconciler.DEFAULT_TASK_QUEUE,
    )

    assert status["process_alive"] is True
    assert status["pid"] == 26120
    assert status["detected_worker_process_count"] == 1


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

    current = json.loads(
        Path(payload["output_paths"]["current_index_latest"]).read_text(encoding="utf-8")
    )
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

    current = json.loads(
        Path(payload["output_paths"]["current_index_latest"]).read_text(encoding="utf-8")
    )
    assert current["status"] == "current_333_run_index_blocked"
    assert current["workflow_id"] == ""
    assert current["reconciliation"]["named_blocker"] == "AMBIGUOUS_ACTIVE_333_MAINLINE"
    assert (
        current["reconciliation"]["ambiguous_candidates_require_user_or_controller_decision"]
        is True
    )


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
    assert payload["control_plane_liveness"]["status"] == "control_plane_liveness_ready"
    assert payload["control_plane_liveness"]["named_blocker"] == "NO_ACTIVE_333_MAINLINE"
    assert payload["control_plane_liveness"]["no_signal_sent"] is True
    assert payload["control_plane_liveness"]["model_invocation_performed"] is False
    assert {item["role"] for item in payload["classified_workflows"]} == {
        "temporary_probe_or_ad_hoc"
    }


def test_run_reconciler_liveness_degrades_without_worker_polling(tmp_path: Path) -> None:
    stale_worker = {
        **worker_status(),
        "status": "not_running",
        "process_alive": False,
        "pollers_seen": 0,
    }

    payload = reconciler.build(
        runtime_root=tmp_path / "runtime",
        repo_root=tmp_path / "repo",
        running_workflows_override=[],
        port_open_override=True,
        worker_status_override=stale_worker,
    )

    liveness = payload["control_plane_liveness"]
    assert payload["decision"]["named_blocker"] == "TEMPORAL_WORKER_NOT_POLLING"
    assert liveness["status"] == "control_plane_liveness_degraded"
    assert liveness["validation"]["checks"]["worker_seen_alive_or_polling"] is False
    assert liveness["model_invocation_performed"] is False
    assert liveness["no_provider_worker_dispatch"] is True
