import json
import os
import subprocess
import sys
from pathlib import Path

from xinao_seedlab.application.seed_cortex import build_default_service


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_durable_continuation_reconnect_writes_ledger_driven_next_wave(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    service = build_default_service(runtime, repo_root=repo)

    payload = service.durable_continuation_reconnect(
        task_id="durable_continuation_reconnect_20260703",
        workflow_id="durable-continuation-test",
        wave_id="durable-continuation-wave-01",
        intent="worker poll auto dispatch durable reconnect",
        worker_result_ref="repo://tests/seedcortex/test_durable_continuation_reconnect.py#worker",
        write_runtime=True,
    )

    assert payload["schema_version"] == "xinao.durable_continuation_reconnect.v1"
    assert payload["validation"]["passed"] is True
    assert payload["workflow_state"]["checkpoint_persisted"] is True
    assert payload["workflow_state"]["resumed_from_checkpoint"] is False
    assert payload["worker"]["worker_enabled"] is True
    assert payload["worker"]["legacy_5d33_reused"] is False
    assert payload["worker"]["local_runtime_shortcut_used"] is False
    assert payload["worker_poll"]["source_kind"] == "worker_dispatch_ledger_poll"
    assert payload["worker_poll"]["succeeded_count"] >= 1
    assert payload["worker_poll"]["synthetic_succeeded_count"] == 0
    assert payload["worker_poll"]["driver_synthetic_succeeded_allowed"] is False
    assert payload["fan_in_acceptance"]["accepted_edge_count"] == (
        payload["fan_in_acceptance"]["ledger_succeeded_count"]
    )
    assert payload["fan_in_acceptance"]["reused_main_chain_helper"] == (
        "services.agent_runtime.codex_max_capability_think_execute.write_lane_results_and_fan_in"
    )
    assert payload["main_chain_reuse"]["reused"] is True
    assert payload["main_chain_reuse"]["source_function"] == "write_lane_results_and_fan_in"
    assert payload["main_chain_reuse"]["validation_passed"] is True
    assert payload["auto_dispatch"]["next_wave_dispatched"] is True
    assert payload["auto_dispatch"]["dispatch_reason"] == "worker_ledger_succeeded"
    assert payload["default_auto_dispatch"]["default_enabled"] is True
    assert payload["default_auto_dispatch"]["main_chain_reused"] is True
    assert payload["default_auto_dispatch"]["projection_only"] is True
    assert payload["default_auto_dispatch"]["replaces_root_intent_loop_controller"] is False
    assert payload["default_auto_dispatch"]["hardcoded_scheduler_removed"] is True
    assert payload["default_auto_dispatch"]["manual_bridge_main_chain"] is False
    assert payload["live_watch"]["idle"] is False
    assert payload["live_watch"]["state"] != "idle"
    assert payload["live_watch"]["projection_only"] is True
    assert payload["live_watch"]["replaces_live_backend_watch"] is False
    assert payload["hook_seam"]["default_auto_dispatch_enabled"] is True
    assert payload["hook_seam"]["projection_only"] is True
    assert payload["hook_seam"]["replaces_root_intent_loop_controller"] is False
    assert payload["completion_claim_allowed"] is False

    for key in (
        "runtime_latest",
        "checkpoint_latest",
        "worker_dispatch_ledger_latest",
        "fan_in_latest",
        "next_wave_latest",
        "default_auto_dispatch_latest",
        "live_watch_latest",
        "hook_seam_latest",
        "parallel_fan_in_acceptance_latest",
        "parallel_lane_results_latest",
        "readback_zh",
    ):
        assert Path(payload["output_paths"][key]).is_file(), key

    live_watch = _read_json(Path(payload["output_paths"]["live_watch_latest"]))
    assert live_watch["idle"] is False
    assert live_watch["state"] != "idle"
    readback = Path(payload["output_paths"]["readback_zh"]).read_text(encoding="utf-8")
    assert "现在能 invoke 什么" in readback
    assert "default_auto_dispatch.enabled=true" in readback
    assert "write_lane_results_and_fan_in" in readback


def test_durable_continuation_resume_uses_checkpoint_for_next_wave(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    service = build_default_service(runtime, repo_root=repo)

    first = service.durable_continuation_reconnect(
        task_id="durable_continuation_reconnect_resume",
        workflow_id="durable-continuation-resume",
        wave_id="durable-continuation-wave-01",
        worker_result_ref="repo://first-worker-result",
        write_runtime=True,
    )
    resume = service.durable_continuation_reconnect(
        task_id="durable_continuation_reconnect_resume",
        resume_from_latest=True,
        worker_result_ref="repo://resume-worker-result",
        write_runtime=True,
    )

    assert first["auto_dispatch"]["next_wave_dispatched"] is True
    assert resume["validation"]["passed"] is True
    assert resume["workflow_state"]["resumed_from_checkpoint"] is True
    assert resume["workflow_state"]["previous_checkpoint_wave_id"] == "durable-continuation-wave-01"
    assert resume["wave_id"] == first["auto_dispatch"]["next_wave_id"]
    assert resume["main_chain_reuse"]["reused"] is True
    assert resume["auto_dispatch"]["dispatch_reason"] == "worker_ledger_succeeded"
    assert resume["live_watch"]["idle"] is False


def test_durable_continuation_does_not_synthesize_succeeded_without_worker_result(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    service = build_default_service(runtime, repo_root=repo)

    payload = service.durable_continuation_reconnect(
        task_id="durable_continuation_reconnect_blocked",
        workflow_id="durable-continuation-blocked",
        wave_id="durable-continuation-wave-01",
        worker_result_ref="",
        write_runtime=True,
    )

    assert payload["validation"]["passed"] is False
    assert payload["worker_poll"]["succeeded_count"] == 0
    assert payload["worker_poll"]["synthetic_succeeded_count"] == 0
    assert payload["auto_dispatch"]["next_wave_dispatched"] is False
    assert payload["auto_dispatch"]["dispatch_reason"] == (
        "blocked_waiting_worker_ledger_succeeded"
    )
    assert payload["live_watch"]["idle"] is False
    assert payload["completion_claim_allowed"] is False


def test_durable_continuation_reconnect_cli_invokes_service(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo_root = Path(__file__).resolve().parents[2]
    task_id = "durable_continuation_reconnect_cli"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src") + os.pathsep + str(repo_root)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "xinao_seedlab.cli.__main__",
            "--runtime-root",
            str(runtime),
            "--repo-root",
            str(repo_root),
            "durable-continuation-reconnect",
            "--task-id",
            task_id,
            "--workflow-id",
            "durable-continuation-cli",
            "--wave-id",
            "durable-continuation-cli-wave-01",
            "--worker-result-ref",
            "repo://tests/seedcortex/test_durable_continuation_reconnect.py#cli",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["task_id"] == task_id
    assert payload["validation"]["passed"] is True
    assert payload["auto_dispatch"]["dispatch_reason"] == "worker_ledger_succeeded"
    assert payload["main_chain_reuse"]["reused"] is True
    assert payload["default_auto_dispatch"]["default_enabled"] is True
    assert payload["live_watch"]["idle"] is False
    assert Path(payload["output_paths"]["runtime_latest"]).is_file()
    assert Path(payload["output_paths"]["default_auto_dispatch_latest"]).is_file()
