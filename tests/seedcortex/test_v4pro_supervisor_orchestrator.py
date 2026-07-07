import json
from pathlib import Path

from services.agent_runtime import v4pro_supervisor_orchestrator as orchestrator


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _prime_runtime(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "workflow_id": "codex-s-333-mainline-p0-test",
            "workflow_run_id": "run-current",
            "worker_status": {"status": "polling", "pid": 1, "process_alive": True},
        },
    )
    _write_json(
        runtime / "state" / "bounded_result_wait" / "latest.json",
        {"bounded_result_wait_ready": True, "named_blocker": ""},
    )
    _write_json(
        runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json",
        {"validation": {"passed": True}, "active_blockers": []},
    )
    _write_json(
        runtime / "state" / "v4pro_mature_bind_execution_controller" / "latest.json",
        {
            "controller_state": "blocked",
            "submit_status": "not_submitted",
            "enqueue_ok": True,
            "queue_empty": False,
            "named_blocker": "V4PRO_SUBMIT_CLOSURE_INCOMPLETE",
        },
    )
    _write_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {"provider_registry": {"providers": [{"provider_id": "deepseek_v4_pro"}]}},
    )
    for relative in orchestrator.HOT_PATH_BIND_ALLOWLIST:
        _write_json(runtime / relative.replace("/", "\\"), {"status": "ready"})


def test_supervisor_orchestrator_plans_workers_and_controller_tick(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    _prime_runtime(runtime)

    monkeypatch.setattr(
        orchestrator.v4pro_policy,
        "shortcut_target",
        lambda path: {
            "exists": True,
            "Arguments": "XINAO DeepSeek V4 Pro S Hardmode",
            "WorkingDirectory": str(repo),
        },
    )
    monkeypatch.setattr(orchestrator.v4pro_policy, "git_clean", lambda repo: True)

    payload = orchestrator.build_orchestrator(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=tmp_path / "pkg",
        write=True,
        dispatch_workers=False,
        write_aaq=False,
        repair_fn=lambda **kwargs: {"bounded_result_wait_ready": True, "named_blocker": ""},
        controller_fn=lambda **kwargs: {
            "controller_state": "blocked",
            "submit_status": "not_submitted",
            "enqueue_ok": True,
            "submitted": False,
            "named_blocker": "V4PRO_SUBMIT_CLOSURE_INCOMPLETE",
            "mature_bind_task_id": "p0_010_post_continue_as_new_status_refresh",
        },
    )

    assert payload["v4pro_supervisor_orchestrator_ready"] is True
    assert payload["is_execution_controller"] is True
    assert payload["dp_is_second_brain"] is False
    assert payload["supervisor_provider_id"] == "deepseek_v4_pro"
    assert any(
        item["action"] == "execution_controller_tick" for item in payload["orchestration_plan"]
    )
    assert payload["execution_controller"]["submit_status"] == "not_submitted"
    assert len(payload["hot_path_binds"]) >= 1
    latest = read_json(runtime / "state" / "v4pro_supervisor_orchestrator" / "latest.json")
    assert latest["orchestrator_state"] == "enqueued_awaiting_closure"


def test_supervisor_dispatches_qwen_and_v4_workers(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    _prime_runtime(runtime)
    monkeypatch.setattr(
        orchestrator.v4pro_policy,
        "shortcut_target",
        lambda path: {
            "exists": True,
            "Arguments": "XINAO DeepSeek V4 Pro S Hardmode",
            "WorkingDirectory": str(repo),
        },
    )
    monkeypatch.setattr(orchestrator.v4pro_policy, "git_clean", lambda repo: True)

    calls: list[str] = []

    def fake_worker(**kwargs):
        calls.append(str(kwargs.get("worker_key")))
        return {
            "worker": kwargs.get("worker_key"),
            "status": "direct_worker_lane_ready",
            "named_blocker": "",
        }

    payload = orchestrator.build_orchestrator(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=tmp_path / "pkg",
        write=False,
        dispatch_workers=True,
        write_aaq=False,
        repair_fn=lambda **kwargs: {},
        controller_fn=lambda **kwargs: {
            "submit_status": "not_submitted",
            "enqueue_ok": False,
            "submitted": False,
            "named_blocker": "",
        },
        worker_dispatch_fn=fake_worker,
    )

    assert "qwen_prepaid_cheap_worker" in calls
    assert "deepseek_v4_pro" in calls
    assert len(payload["worker_dispatches"]) == 2


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
