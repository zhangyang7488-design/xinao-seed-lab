import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "source_family_wave_scheduler.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("source_family_wave_scheduler", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_anchor(anchor: Path) -> None:
    anchor.mkdir(parents=True, exist_ok=True)
    files = {
        "AUTHORITY_READ_ORDER.txt": "read order\n333\n",
        "新系统独立并行_自由发散外部研究总稿_20260701.txt": (
            "20260701 root\nFanIn validator\nNextFrontier\n"
        ),
        "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt": (
            "20260702 execution\nsource family\nClaimCard\nSourceLedger\n"
        ),
    }
    for name, text in files.items():
        (anchor / name).write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_source_family_wave_scheduler_writes_block4_default_lane(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "Desktop" / "新系统"
    repo.mkdir()
    _seed_anchor(anchor)
    _write_json(
        runtime / "state" / "temporal_codex_task_worker" / "latest.json",
        {"status": "started", "pid": 9416},
    )
    _write_json(
        runtime / "state" / "source_frontier_durable_consumer" / "latest.json",
        {
            "status": "source_frontier_module_consumed",
            "source_gap_open": False,
            "remaining_batch_ids": [],
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        wave_id="unit-block4",
        invoked_by_main_execution_loop_tick=True,
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.source_family_wave_scheduler.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_SOURCE_FAMILY_WAVE_SCHEDULER_READY"
    assert payload["status"] == "source_family_wave_scheduler_ready"
    assert payload["task_id"] == "wave4_20260701_frontier_source_family_20260704"
    assert payload["parent_task_id"] == "xinao_seed_cortex_phase0_20260701"
    assert payload["routing"] == "continue_same_task"
    assert payload["dynamic_width"]["target_width"] >= 1
    assert payload["dynamic_width"]["target_width"] != 20
    assert payload["dynamic_width"]["actual_dispatched_width"] >= 5
    assert payload["claim_card_staging_queue"]["non_local_source_family_count"] >= 4
    assert payload["fan_in_acceptance_queue"]["fan_in_is_default_heart"] is True
    assert payload["fan_in_acceptance_queue"]["accepted_edge_count"] >= 5
    assert payload["artifact_acceptance_queue"]["accepted_artifact_count"] >= 5
    assert payload["source_ledger_ref"]["exists"] is True
    assert payload["next_frontier_machine_actions"]["should_continue_loop"] is True
    assert payload["next_frontier_machine_actions"]["stop_allowed"] is False
    assert payload["next_frontier_machine_actions"]["next_frontier"][0]["action"] == (
        "enter_wave5_phase0_reusable_kernel"
    )
    assert payload["black_window_hygiene"]["s_temporal_worker_started_by_hidden_script"] is True
    assert payload["black_window_hygiene"]["legacy_clean_runtime_processes_reference_only"] is True
    assert payload["completion_claim_allowed"] is False
    assert payload["validation"]["passed"] is True

    expected_paths = [
        runtime / "state" / "source_family_wave_scheduler" / "latest.json",
        runtime / "state" / "source_family_wave_plan" / "latest.json",
        runtime / "state" / "claim_card_staging_queue" / "latest.json",
        runtime / "state" / "fan_in_acceptance_queue" / "latest.json",
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        runtime / "state" / "source_ledger" / "latest.json",
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        runtime / "state" / "background_window_hygiene" / "latest.json",
        runtime / "readback" / "zh" / "wave_block4_20260701_frontier_20260704.md",
    ]
    for path in expected_paths:
        assert path.is_file(), path
