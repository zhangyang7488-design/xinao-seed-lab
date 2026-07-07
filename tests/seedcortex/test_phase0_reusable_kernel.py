import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "phase0_reusable_kernel.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("phase0_reusable_kernel", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_anchor(anchor: Path) -> None:
    anchor.mkdir(parents=True, exist_ok=True)
    files = {
        "AUTHORITY_READ_ORDER.txt": "read order\n333\n",
        "新系统独立并行_自由发散外部研究总稿_20260701.txt": "20260701\nreplay\nprovider\n",
        "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt": "20260702\nPhase0\nFrontierCandidate\n",
    }
    for name, text in files.items():
        (anchor / name).write_text(text, encoding="utf-8")


def _seed_manifest_anchor(anchor: Path) -> None:
    anchor.mkdir(parents=True, exist_ok=True)
    files = [
        "01_总说明_本项目是什么_20260707.txt",
        "02_P0_底座全自动任务落地_20260707.txt",
        "03_P1_任务落地_20260707.txt",
    ]
    for name in files:
        (anchor / name).write_text(f"{name}\ncurrent P0 package\n", encoding="utf-8")
    (anchor / "TASK_PACKAGE.json").write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.task_package_manifest.v1",
                "package_id": "current-system-p0-20260707",
                "resources": [
                    {"path": name, "role": "current_task_source"} for name in files
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _seed_runtime(runtime: Path) -> Path:
    _write_json(runtime / "state" / "fan_in_acceptance_queue" / "latest.json", {"validation": {"passed": True}, "not_execution_controller": True})
    _write_json(runtime / "state" / "artifact_acceptance_queue" / "latest.json", {"accepted_artifact_count": 7, "validation": {"passed": True}, "not_execution_controller": True})
    _write_json(runtime / "state" / "source_family_wave_scheduler" / "temporal_activity_latest.json", {"validation": {"passed": True}, "not_execution_controller": True})
    _write_json(runtime / "state" / "next_frontier_machine_actions" / "latest.json", {"validation": {"passed": True}, "not_execution_controller": True})
    _write_json(runtime / "state" / "frontier_portfolio_snapshot" / "latest.json", {"validation": {"passed": True}, "not_execution_controller": True})
    _write_json(runtime / "state" / "lane_result_review" / "latest.json", {"validation": {"passed": True}, "not_execution_controller": True})
    _write_json(runtime / "state" / "reward_signal" / "latest.json", {"validation": {"passed": True}, "not_execution_controller": True})
    _write_json(
        runtime / "runs" / "episodes" / "source-family-wave-wave4-source-family-default-lane-20260704-wave-01-ingress" / "workflow_entry.json",
        {"status": "episode_workflow_entry_ready"},
    )
    _write_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {
            "provider_registry": {
                "providers": [
                    {"provider_id": "codex_exec", "status": "ready", "switchable": True},
                    {"provider_id": "codex_sdk", "status": "ready", "switchable": True},
                    {"provider_id": "qwen_dashscope", "status": "ready", "switchable": True},
                ]
            },
            "scheduler_decision": {"route_policy": {"source_family_research": ["search", "qwen"]}},
            "validation": {"passed": True},
        },
    )
    spec = runtime / "specs" / "max_benefit_dynamic_loop_authority_20260702.v1.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("authority\n", encoding="utf-8")
    return spec


def test_phase0_reusable_kernel_builds_task_scoped_acceptance(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchor(anchor)
    spec = _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        anchor_package_root=anchor,
        spec_path=spec,
        wave_id="unit-block5",
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.phase0_reusable_kernel.v1"
    assert payload["status"] == "phase0_reusable_kernel_ready"
    assert payload["task_id"] == "wave5_phase0_reusable_kernel_20260704"
    assert payload["routing"] == "continue_same_task"
    assert payload["kernel_objects"]["object_count"] == 4
    assert payload["kernel_objects"]["landed_count"] == 4
    assert payload["kernel_objects"]["frontier_four_objects_available"] is True
    assert payload["provider_swap_replay"]["provider_swap_requires_domain_rewrite"] is False
    assert payload["provider_swap_replay"]["switchable_ready_provider_count"] >= 3
    assert payload["new_work_id_thin_bind"]["bind_without_hand_solder"] is True
    assert payload["next_frontier_machine_actions"]["should_continue_loop"] is True
    assert payload["next_frontier_machine_actions"]["stop_allowed"] is False
    assert payload["completion_claim_allowed"] is False
    assert payload["validation"]["passed"] is True

    for path in [
        runtime / "state" / "phase0_reusable_kernel" / "latest.json",
        runtime / "state" / "phase0_reusable_kernel" / "kernel_objects" / "latest.json",
        runtime / "state" / "phase0_reusable_kernel" / "new_work_id_thin_bind" / "latest.json",
        runtime / "capabilities" / "codex_s.phase0_reusable_kernel" / "manifest.json",
        runtime / "readback" / "zh" / "wave_block5_phase0_reusable_kernel_20260704.md",
    ]:
        assert path.is_file(), path


def test_phase0_reusable_kernel_manifest_package_is_default_authority(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_manifest_anchor(anchor)
    spec = _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        anchor_package_root=anchor,
        spec_path=spec,
        wave_id="unit-block5-manifest",
        write=True,
    )

    forbidden = [
        "AUTHORITY_READ_ORDER",
        "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702",
        "新系统独立并行_自由发散外部研究总稿_20260701",
    ]
    latest_text = (
        runtime / "state" / "phase0_reusable_kernel" / "latest.json"
    ).read_text(encoding="utf-8")
    worker_assignment = payload["worker_assignment"]
    source_package = payload["source_package"]
    gap = payload["next_frontier_machine_actions"]["source_frontier_gap"]
    assert payload["validation"]["passed"] is True
    assert source_package["manifest_driven"] is True
    assert source_package["all_required_sources_read_full"] is True
    assert worker_assignment["primary_authority_mode"] == "task_package_manifest"
    assert worker_assignment["primary_authority_path"] == str(anchor / "TASK_PACKAGE.json")
    assert gap["manifest_driven"] is True
    assert gap["gap_scope"] == "current_manifest_task_package_after_phase0_reusable_kernel"
    assert all(pattern not in latest_text for pattern in forbidden)
