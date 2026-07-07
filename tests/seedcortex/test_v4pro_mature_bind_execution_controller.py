import json
from pathlib import Path

from services.agent_runtime import v4pro_mature_bind_execution_controller as controller


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
            },
            "mature_bind_queue": [
                {
                    "task_id": "p0_010_post_continue_as_new_status_refresh",
                    "status": "ready",
                    "deliverable": "refresh run ids",
                    "runtime_evidence": ["D:/runtime/state/post_continue_as_new_status_refresh/latest.json"],
                    "verification": ["echo verify-ok"],
                    "acceptance": {
                        "success_decision": "accepted_for_binding",
                        "success_field": "post_continue_as_new_status_refresh_ready",
                    },
                }
            ],
            "resources": [{"path": "current.txt", "role": "entrypoint"}],
        },
    )


def _prime_runtime(runtime: Path, repo: Path) -> None:
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "status": "current_333_run_index_ready",
            "workflow_id": "codex-s-333-mainline-p0-test",
            "workflow_run_id": "run-current",
            "current_state": "running",
            "worker_status": {"status": "polling", "pid": 123, "process_alive": True, "pollers_seen": 1},
        },
    )
    _write_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {
            "provider_registry": {
                "providers": [
                    {
                        "provider_id": "deepseek_v4_pro",
                        "status": "ready",
                        "deepseek_v4_pro_main_worker_eligible": True,
                    }
                ]
            }
        },
    )
    (repo / "tools" / "codex-sdk-python" / ".venv" / "Scripts").mkdir(parents=True)
    (repo / "tools" / "codex-sdk-python" / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    (repo / "tools" / "universal_control_plane_v0").mkdir(parents=True)
    (repo / "tools" / "universal_control_plane_v0" / "universal_control_plane_v0.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )


def test_controller_enqueues_without_claiming_submit(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    task_root = tmp_path / "新系统"
    repo.mkdir()
    _write_task_package(task_root)
    _prime_runtime(runtime, repo)

    monkeypatch.setattr(
        controller.v4pro_policy,
        "shortcut_target",
        lambda path: {
            "exists": True,
            "path": str(path),
            "TargetPath": "wt.exe",
            "Arguments": '-w new -p "XINAO DeepSeek V4 Pro S Hardmode"',
            "WorkingDirectory": str(repo),
        },
    )
    monkeypatch.setattr(
        controller,
        "git_snapshot",
        lambda repo: {
            "commit_hash": "abc123def4567890",
            "branch": "main",
            "git_status_short": "",
            "git_clean": True,
            "push_target": "origin/main",
            "git_ok": True,
        },
    )
    monkeypatch.setattr(
        controller,
        "run_verification_commands",
        lambda commands, repo=None, timeout_sec=600: [
            {"command": str(commands[0]), "passed": False, "returncode": 1, "stdout_tail": "", "stderr_tail": "fail"}
        ],
    )

    payload = controller.build_controller(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_root,
        write=True,
        send_signal=False,
        run_verification=True,
        write_aaq=False,
    )

    assert payload["enqueue_ok"] is True
    assert payload["submit_status"] == "not_submitted"
    assert payload["submitted"] is False
    assert payload["submit_claim_allowed"] is False
    assert payload["is_execution_controller"] is True
    assert payload["not_execution_controller"] is False
    assert payload["named_blocker"] == "V4PRO_SUBMIT_CLOSURE_VERIFICATION_FAILED"
    assert payload["mature_bind_task_id"] == "p0_010_post_continue_as_new_status_refresh"
    assert (runtime / "state" / "v4pro_mature_bind_execution_controller" / "latest.json").is_file()


def test_controller_blocks_without_tool_surface(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    task_root = tmp_path / "新系统"
    repo.mkdir()
    _write_task_package(task_root)
    _prime_runtime(runtime, repo)
    monkeypatch.setattr(
        controller.v4pro_policy,
        "shortcut_target",
        lambda path: {"exists": False, "path": str(path)},
    )
    monkeypatch.setattr(controller, "git_snapshot", lambda repo: {"git_clean": True, "commit_hash": "", "push_target": ""})

    payload = controller.build_controller(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_root,
        write=False,
        run_verification=False,
        write_aaq=False,
    )

    assert payload["enqueue_ok"] is False
    assert payload["submit_status"] == "not_submitted"
    assert payload["controller_state"] == "blocked"
    assert "V4PRO" in payload["named_blocker"] or payload["named_blocker"] == "V4PRO_TOOL_BEARING_EXECUTOR_POLICY_NOT_BOUND"


def test_controller_idle_when_queue_empty(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    task_root = tmp_path / "新系统"
    repo.mkdir()
    _write_task_package(task_root)
    _write_json(
        runtime / "runs" / "episodes" / "p0_010_post_continue_as_new_status_refresh" / "artifact_acceptance.json",
        {
            "decisions": [
                {
                    "candidate_id": "p0_010_post_continue_as_new_status_refresh",
                    "status": "accepted",
                    "artifact_acceptance_decision": "accepted_for_binding",
                }
            ]
        },
    )

    payload = controller.build_controller(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_root,
        write=False,
        write_aaq=False,
    )

    assert payload["controller_state"] == "idle"
    assert payload["queue_empty"] is True
    assert payload["enqueue_ok"] is False