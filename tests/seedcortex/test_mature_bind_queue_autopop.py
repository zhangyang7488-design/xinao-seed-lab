import json
from pathlib import Path

from services.agent_runtime import mature_bind_queue_autopop as autopop


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_task_package(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "current.txt").write_text("current\n", encoding="utf-8")
    _write_json(
        root / "TASK_PACKAGE.json",
        {
            "schema_version": "xinao.codex_s.task_package_manifest.v1",
            "package_mode": "unit_current",
            "entrypoint": "current.txt",
            "execution_defaults": {
                "north_star": "user_x_to_deliverable_y",
                "task_shape": "one_deliverable_one_binding_one_verifier",
                "default_acceptance_decisions": [
                    "accepted_for_binding",
                    "accepted_for_delivery",
                ],
                "exception_acceptance_decision": "accepted_for_next_frontier",
                "next_frontier_default_outlet": False,
                "bounded_retry": {
                    "policy_id": "bounded_delivery_retry",
                    "scope": "same_deliverable_only",
                    "next_frontier_on_failure": False,
                },
            },
            "mature_bind_queue": [
                {
                    "task_id": "p0_010_post_continue_as_new_status_refresh",
                    "status": "ready",
                    "deliverable": "refresh run ids",
                    "verification": ["verify p0_010"],
                    "acceptance": {
                        "success_decision": "accepted_for_binding",
                        "success_field": "post_continue_as_new_status_refresh_ready",
                    },
                    "fallback_or_blocker": "POST_CONTINUE_AS_NEW_STATUS_REFRESH_NOT_BOUND",
                },
                {
                    "task_id": "p0_012_mature_bind_queue_autopop_next_task",
                    "status": "ready",
                    "deliverable": "autopop next",
                    "verification": ["verify p0_012"],
                    "acceptance": {
                        "success_decision": "accepted_for_binding",
                        "success_field": "mature_bind_queue_autopop_ready",
                    },
                },
            ],
            "resources": [{"path": "current.txt", "role": "entrypoint"}],
        },
    )


def test_mature_bind_queue_autopop_writes_signal_without_frontier(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    task_root = tmp_path / "新系统"
    repo.mkdir()
    _write_task_package(task_root)
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "status": "current_333_run_index_ready",
            "workflow_id": "codex-s-333-mainline-p0-test",
            "workflow_run_id": "run-current",
        },
    )

    payload = autopop.build_autopop(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_root,
        write=True,
        send_signal=False,
        exclude_task_ids=[autopop.TASK_ID],
        write_aaq=False,
    )

    assert payload["mature_bind_queue_autopop_ready"] is True
    assert payload["queue_empty"] is False
    assert payload["next_mature_bind_task_id"] == "p0_010_post_continue_as_new_status_refresh"
    assert payload["contract_id"] == "p0_010_post_continue_as_new_status_refresh"
    assert payload["auto_continue_same_workflow"] is True
    signal_path = Path(payload["signal_path"])
    assert signal_path.is_file()
    signal = json.loads(signal_path.read_text(encoding="utf-8"))
    assert signal["disable_next_frontier_continuation_supervisor"] is True
    assert signal["frontier_auto_continue_allowed"] is False
    assert signal["execute_worker_turn"] is False
    assert signal["mature_bind_task"]["task_id"] == "p0_010_post_continue_as_new_status_refresh"


def test_mature_bind_queue_autopop_reports_empty_after_acceptance_overlay(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    task_root = tmp_path / "新系统"
    repo.mkdir()
    _write_task_package(task_root)
    for task_id in (
        "p0_010_post_continue_as_new_status_refresh",
        "p0_012_mature_bind_queue_autopop_next_task",
    ):
        _write_json(
            runtime / "runs" / "episodes" / task_id / "artifact_acceptance.json",
            {
                "decisions": [
                    {
                        "candidate_id": task_id,
                        "status": "accepted",
                        "artifact_acceptance_decision": "accepted_for_binding",
                        "artifact_ref": f"{task_id}/latest.json",
                    }
                ]
            },
        )

    payload = autopop.build_autopop(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_root,
        write=False,
        send_signal=False,
        exclude_task_ids=[autopop.TASK_ID],
        write_aaq=False,
    )

    assert payload["mature_bind_queue_autopop_ready"] is True
    assert payload["queue_empty"] is True
    assert payload["next_mature_bind_task_id"] == ""
