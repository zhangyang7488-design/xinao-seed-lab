from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "wave2_mainchain_hygiene.py"


def load_module():
    spec = importlib.util.spec_from_file_location("wave2_mainchain_hygiene", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _seed_runtime(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "source_frontier_durable_consumer" / "temporal_activity_latest.json",
        {
            "schema_version": "xinao.test.block3",
            "status": "source_frontier_module_consumed",
            "source_gap_open": False,
            "consumed_batch_ids": ["a", "b", "c"],
            "remaining_batch_ids": [],
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "source_family_wave_scheduler" / "temporal_activity_latest.json",
        {
            "schema_version": "xinao.test.block4",
            "status": "source_family_wave_scheduler_ready",
            "artifact_acceptance_queue": {"accepted_artifact_count": 7},
            "claim_card_staging_queue": {"source_families": ["official", "github"]},
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "phase0_reusable_kernel" / "temporal_activity_latest.json",
        {
            "schema_version": "xinao.test.block5",
            "status": "phase0_reusable_kernel_ready",
            "kernel_objects": {"landed_count": 4, "object_count": 4},
            "new_work_id_thin_bind": {"bind_without_hand_solder": True},
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "temporal_activity_no_window_dp_worker_pool_phase3_20260704" / "latest.json",
        {
            "background": {
                "not_30_minute_runner": True,
                "sleep_seconds_1800_default_main_loop_allowed": False,
                "task_backlog_triggers_dispatch": True,
                "ready_frontier_triggers_dispatch": True,
                "terminal_worker_triggers_fan_in": True,
                "draft_staging_triggers_merge": True,
                "source_gap_triggers_source_lane": True,
                "next_frontier_triggers_next_wave": True,
            },
            "phase1_payload_summary": {
                "target_width": 12,
                "target_width_source": "dynamic_width_scheduler",
                "width_decision_reason": "target_width=12 from provider headroom",
                "actual_dispatched_width": 12,
                "draft_count": 8,
                "true_dp_draft_count": 8,
                "staged_count": 8,
                "merged_count": 1,
                "spend_entry_count": 12,
                "merge_artifact": "merge.md",
            },
            "no_window_execution": {"start_worker_script_hidden": True},
        },
    )
    _write_json(
        runtime
        / "state"
        / "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
        / "event_queue"
        / "latest.json",
        {
            "queue_id": "codex_s.333.temporal_activity.event_queue",
            "queue_depth": 0,
            "loop_epoch": 3,
            "not_30_minute_runner": True,
            "sleep_seconds_1800_default_main_loop_allowed": False,
        },
    )
    _write_json(
        runtime
        / "state"
        / "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
        / "legacy_runner_downgrade"
        / "latest.json",
        {
            "runner_30min_cancelled_or_frozen": True,
            "same_default_loop_reference_only": True,
            "overnight_runner_reference_only": True,
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json",
        {
            "status": "default_main_loop_trigger_candidate_verifier_ready",
            "adoption_state": "runtime_trigger_candidate_verifier_ready",
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "loop_runtime_state" / "latest.json",
        {"stop": {"stop_allowed": False, "derived": True}},
    )
    _write_json(
        runtime / "state" / "temporal_codex_task_worker" / "latest.json",
        {
            "status": "polling",
            "pid": 1234,
            "task_queue": "xinao-codex-task-default",
            "process_alive": True,
        },
    )
    _write_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {
            "status": "codex_native_provider_scheduler_ready",
            "validation": {"passed": True},
            "provider_registry": {
                "providers": [
                    {"provider_id": "codex_exec", "status": "ready", "switchable": True},
                    {"provider_id": "deepseek_dp", "status": "ready", "switchable": True},
                    {"provider_id": "qwen_dashscope", "status": "ready", "switchable": True},
                ]
            },
            "scheduler_decision": {"route_policy": {"draft": ["qwen_dashscope", "deepseek_dp"]}},
        },
    )


def _seed_repo(repo: Path) -> None:
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "Start-XinaoTemporalCodexWorker.ps1").write_text(
        "Start-Process -WindowStyle Hidden -RedirectStandardOutput out -RedirectStandardError err\n"
        "not_completion_decision\n",
        encoding="utf-8",
    )
    phase3 = repo / "services" / "agent_runtime" / "temporal_activity_no_window_dp_worker_pool_phase3.py"
    phase3.parent.mkdir(parents=True, exist_ok=True)
    phase3.write_text(
        "subprocess.CREATE_NO_WINDOW\nSTARTF_USESHOWWINDOW\nSW_HIDE\n",
        encoding="utf-8",
    )
    scheduler = repo / "services" / "agent_runtime" / "codex_native_provider_scheduler_phase4.py"
    scheduler.write_text("CREATE_NO_WINDOW\nSTARTF_USESHOWWINDOW\n", encoding="utf-8")


def _seed_sources(anchor: Path, planning: Path) -> None:
    anchor.mkdir(parents=True)
    for name in [
        "AUTHORITY_READ_ORDER.txt",
        "新系统独立并行_自由发散外部研究总稿_20260701.txt",
        "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
        "XINAO_333_固定锚点.txt",
    ]:
        (anchor / name).write_text(f"{name}\n", encoding="utf-8")
    planning.write_text("块3 -> 块4 -> 块5 -> 块2\n", encoding="utf-8")


def test_wave2_mainchain_hygiene_refreshes_main_route(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "新系统"
    planning = tmp_path / "planning.txt"
    _seed_runtime(runtime)
    _seed_repo(repo)
    _seed_sources(anchor, planning)
    monkeypatch.setattr(
        module,
        "process_window_snapshot",
        lambda: {
            "windows_probe_supported": True,
            "visible_disallowed_console_count": 0,
            "visible_codex_s_terminal_count": 1,
            "visible_disallowed_console_processes": [],
            "visible_terminal_windows": [],
            "probe_error": "",
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        planning_text=planning,
        wave_id="test-wave2",
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.wave2_mainchain_hygiene.v1"
    assert payload["validation"]["passed"] is True
    assert payload["black_window_probe"]["black_window_issue_handled"] is True
    assert payload["memo_gap_refresh"]["counts"] == {
        "total_targets": 13,
        "landed_or_migrated": 13,
        "partial": 0,
        "gap": 0,
    }
    assert payload["default_main_loop_hygiene"]["thirty_minute_runner"]["sleep_1800_default_main_loop_allowed"] is False
    assert payload["next_frontier_machine_actions"]["stop_allowed"] is False
    assert (runtime / "state" / "wave2_mainchain_hygiene" / "latest.json").is_file()
    assert (runtime / "state" / "default_main_loop_hygiene" / "latest.json").is_file()
    assert (runtime / "readback" / "zh" / "wave_block2_mainchain_hygiene_20260704.md").is_file()
