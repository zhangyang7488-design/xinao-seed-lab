import json
from pathlib import Path

from services.agent_runtime import post_continue_as_new_status_refresh as refresh


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_post_continue_status_refresh_aligns_current_and_bounded_wait(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    workflow_id = "codex-s-333-mainline-p0-test"
    workflow_run_id = "run-after-continue-as-new"

    def fake_reconciler_build(**kwargs):
        _write_json(
            runtime / "state" / "current_333_run_index" / "latest.json",
            {
                "status": "current_333_run_index_ready",
                "workflow_id": workflow_id,
                "workflow_run_id": workflow_run_id,
                "current_state": "running",
                "worker_status": {"status": "polling", "process_alive": True},
                "reconciliation": {"named_blocker": ""},
            },
        )
        return {"status": "codex_333_run_reconciler_ready"}

    def fake_bounded_wait(**kwargs):
        _write_json(
            runtime / "state" / "bounded_result_wait" / "latest.json",
            {
                "status": "bounded_result_wait_ready",
                "bounded_result_wait_ready": True,
                "current_state": "running",
                "current_workflow_id": workflow_id,
                "current_workflow_run_id": workflow_run_id,
            },
        )
        return {"status": "bounded_result_wait_ready", "bounded_result_wait_ready": True}

    monkeypatch.setattr(refresh.codex_333_run_reconciler, "build", fake_reconciler_build)
    monkeypatch.setattr(refresh.bounded_result_wait, "build_bounded_result_wait", fake_bounded_wait)

    payload = refresh.build_post_continue_as_new_status_refresh(
        runtime_root=runtime,
        repo_root=repo,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        refresh_source="unit_test",
        write=True,
        write_aaq=False,
    )

    assert payload["post_continue_as_new_status_refresh_ready"] is True
    assert payload["current_workflow_run_id"] == workflow_run_id
    assert payload["bounded_result_wait_run_id"] == workflow_run_id
    assert payload["validation"]["checks"]["current_and_bounded_run_aligned"] is True
    assert (runtime / "state" / "post_continue_as_new_status_refresh" / "latest.json").is_file()
    readback = (
        runtime / "readback" / "zh" / "post_continue_as_new_status_refresh_20260707.md"
    ).read_text(encoding="utf-8")
    assert refresh.SENTINEL in readback


def test_post_continue_status_refresh_blocks_on_run_drift(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_reconciler_build(**kwargs):
        _write_json(
            runtime / "state" / "current_333_run_index" / "latest.json",
            {
                "status": "current_333_run_index_ready",
                "workflow_id": "workflow",
                "workflow_run_id": "new-run",
            },
        )
        return {"status": "codex_333_run_reconciler_ready"}

    def fake_bounded_wait(**kwargs):
        _write_json(
            runtime / "state" / "bounded_result_wait" / "latest.json",
            {
                "status": "bounded_result_wait_ready",
                "bounded_result_wait_ready": True,
                "current_workflow_run_id": "old-run",
            },
        )
        return {"status": "bounded_result_wait_ready"}

    monkeypatch.setattr(refresh.codex_333_run_reconciler, "build", fake_reconciler_build)
    monkeypatch.setattr(refresh.bounded_result_wait, "build_bounded_result_wait", fake_bounded_wait)

    payload = refresh.build_post_continue_as_new_status_refresh(
        runtime_root=runtime,
        repo_root=repo,
        workflow_id="workflow",
        workflow_run_id="new-run",
        write=False,
        write_aaq=False,
    )

    assert payload["post_continue_as_new_status_refresh_ready"] is False
    assert payload["named_blocker"] == "POST_CONTINUE_AS_NEW_STATUS_REFRESH_NOT_BOUND"
    assert payload["validation"]["checks"]["current_and_bounded_run_aligned"] is False
