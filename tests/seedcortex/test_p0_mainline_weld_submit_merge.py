from __future__ import annotations

import json
from pathlib import Path

from services.agent_runtime import p0_mainline_weld_submit_merge as merge


def test_weld_promotes_main_loop_tick_adoption(tmp_path: Path) -> None:
    tick_dir = tmp_path / "state" / "codex_s_main_execution_loop_tick"
    tick_dir.mkdir(parents=True)
    temporal_payload = {
        "runtime_entrypoint_invocation": {"runtime_enforced": True},
        "adoption_state": "verifier_ready_but_not_hooked",
    }
    (tick_dir / "temporal_activity_latest.json").write_text(
        json.dumps(temporal_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (tick_dir / "latest.json").write_text(
        json.dumps({"adoption_state": "verifier_ready_but_not_hooked"}, ensure_ascii=False),
        encoding="utf-8",
    )

    results = merge.weld_main_execution_loop_tick(tmp_path)
    assert all(item.get("patched") for item in results)

    latest = json.loads((tick_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["adoption_state"] == "runtime_enforced_hot_path_hooked"
    assert latest["runtime_enforced"] is True
    assert latest["default_mainline_weld_point"]["scope"] == merge.WELD_SCOPE


def test_closure_report_matches_bundle_fields(tmp_path: Path) -> None:
    workflow = {
        "workflow_id": "codex-s-test",
        "workflow_run_id": "run-1",
        "worker_status": "polling",
        "worker_pid": 123,
    }
    git_info = {
        "git_clean": True,
        "git_status_short": "",
        "commit_hash": "abc1234567890",
        "push_target": "https://example.com/repo.git",
        "push": {"pushed": True},
    }
    report = merge.build_closure_report(
        workflow=workflow,
        git_info=git_info,
        weld_report={},
        aaq_backfill={"candidate_count": 22},
        dispatch_backfill={"count": 10},
        readback_path=str(tmp_path / "readback.md"),
    )
    closure = merge.closure_builder.closure_evidence_bundle_status(report)
    assert closure["closure_intent"] is True
    assert closure["complete"] is True


def test_build_marks_submitted_when_git_clean_and_closure_complete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    task_pkg = tmp_path / "task_pkg"
    task_pkg.mkdir()

    (repo / ".git").mkdir()

    (runtime / "state" / "current_333_run_index").mkdir(parents=True)
    (runtime / "state" / "current_333_run_index" / "latest.json").write_text(
        json.dumps(
            {
                "workflow_id": "wf-1",
                "workflow_run_id": "run-1",
                "worker_status": {"status": "polling", "pid": 1, "process_alive": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (runtime / "state" / "codex_s_main_execution_loop_tick").mkdir(parents=True)
    (runtime / "state" / "codex_s_main_execution_loop_tick" / "temporal_activity_latest.json").write_text(
        json.dumps({"runtime_entrypoint_invocation": {"runtime_enforced": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (runtime / "state" / "codex_s_main_execution_loop_tick" / "latest.json").write_text("{}", encoding="utf-8")
    (runtime / "state" / "source_frontier_fanin_acceptance").mkdir(parents=True)
    (runtime / "state" / "source_frontier_fanin_acceptance" / "latest.json").write_text(
        json.dumps({"invoked_by_main_execution_loop_tick": True, "status": "ready"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (runtime / "state" / "root_intent_loop_driver").mkdir(parents=True)
    (runtime / "state" / "root_intent_loop_driver" / "latest.json").write_text("{}", encoding="utf-8")
    dispatch_dir = runtime / "state" / "v4pro_mature_bind_execution_controller" / "dispatches"
    dispatch_dir.mkdir(parents=True)
    (dispatch_dir / "p0_004a.json").write_text(
        json.dumps({"task_id": "p0_004a", "submit_status": "not_submitted"}, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest = {
        "mature_bind_queue": [
            {
                "task_id": "p0_004a_provider_lane_index",
                "status": "ready",
                "acceptance": {"success_decision": "accepted_for_binding"},
                "runtime_evidence": [],
            }
        ]
    }
    (task_pkg / "TASK_PACKAGE.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(merge.supervisor, "build_orchestrator", lambda **kwargs: {"v4pro_supervisor_orchestrator_ready": True})
    monkeypatch.setattr(
        merge,
        "git_merge_commit_push",
        lambda repo, **kwargs: {
            "git_clean": True,
            "git_status_short": "",
            "commit_hash": "deadbeef1234567890",
            "push_target": "origin",
            "push": {"pushed": True},
        },
    )
    monkeypatch.setattr(
        merge,
        "backfill_aaq_for_queue",
        lambda *args, **kwargs: {"written": True, "candidate_count": 2},
    )
    monkeypatch.setattr(merge.controller, "build_controller", lambda **kwargs: {"queue_empty": True, "controller_state": "idle"})

    payload = merge.build(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_pkg,
        write=True,
        push_git=False,
        run_controller_for_self=False,
    )
    assert payload["submit_status"] == "submitted"
    assert payload["mainline_weld_submit_merge_ready"] is True
    dispatch = json.loads((dispatch_dir / "p0_004a.json").read_text(encoding="utf-8"))
    assert dispatch["submit_status"] == "submitted"