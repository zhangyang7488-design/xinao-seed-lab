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
            "1. RootIntentLoop 默认内核\n"
            "2. 外部研究发现：能力获取与 Agent OS\n"
            "2.1 MCP Registry\n"
            "3. 高噪声正期望搜索引擎\n"
            "3.1 防过拟合 / lockbox\n"
            "4. 第一批源文本主题\n"
            "4.1 第二批源文本主题\n"
            "4.2 第三批源文本主题\n"
            "4.3 第四批源文本主题\n"
            "4.4 第五批源文本主题\n"
            "4.5 第六批源文本主题\n"
            "4.6 第七批源文本主题\n"
            "4.7 第八批源文本主题\n"
            "4.8 第九批源文本主题\n"
            "4.9 第十批源文本主题\n"
        ),
        "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt": (
            "0. RootIntentLoop 默认内核\n"
            "1. 波内调度：最大收益动态并行\n"
            "12. 本轮来源与 ClaimCard 索引\n"
            "15. Lane3 私人/小众开源发现已写入 D 盘证据\n"
            "17.5.1 Resource Allocator\n"
        ),
    }
    for name, text in files.items():
        (anchor / name).write_text(text, encoding="utf-8")


def _seed_manifest_anchor(anchor: Path) -> None:
    anchor.mkdir(parents=True, exist_ok=True)
    files = {
        "01_current_summary.txt": (
            "1. 当前 P0 manifest 入口\n2. SourceLedger 当前包边界\n3. FanIn AAQ 当前验收\n"
        ),
        "02_current_p0.txt": (
            "1. P0 stable 333 default mainline\n"
            "2. WorkerBrief 当前任务包\n"
            "3. ProviderScheduler 当前路径\n"
            "4. result_wait bounded readback\n"
        ),
        "old_total_20260702.txt": "1. old topic must not be read\n",
        "TASK_PACKAGE.json": json.dumps(
            {
                "schema_version": "xinao.codex_s.task_package_manifest.v1",
                "package_mode": "current_system_p0",
                "resources": [
                    {"path": "01_current_summary.txt", "role": "current", "read": "full"},
                    {"path": "02_current_p0.txt", "role": "current", "read": "full"},
                    {
                        "path": "old_total_20260702.txt",
                        "role": "legacy",
                        "read": "reference_only",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    }
    for name, text in files.items():
        (anchor / name).write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_runtime_preconditions(runtime: Path) -> None:
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


def test_manifest_source_family_wave_does_not_replay_legacy_topic_cards(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "Desktop" / "新系统"
    repo.mkdir()
    _seed_manifest_anchor(anchor)
    _seed_runtime_preconditions(runtime)
    _write_json(
        runtime
        / "state"
        / "source_family_wave_scheduler"
        / "source_topic_claimcards"
        / "latest.json",
        {
            "claim_cards": [
                {
                    "object_type": "ClaimCard",
                    "candidate_id": "claim-old-topic",
                    "topic_family_id": "source20260702:L1:old",
                    "source_url": str(anchor / "old_total_20260702.txt") + "#L1",
                    "source_family": "source_frontier_topic_family",
                    "claim": "old topic",
                    "verification_need": "must not replay",
                    "accepted_for": "phase4_total_source_frontier_topic_family_absorption",
                    "claim_card_ref": str(anchor / "old_total_20260702.txt") + ":L1",
                }
            ]
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        wave_id="unit-manifest-source-family",
        invoked_by_main_execution_loop_tick=True,
        write=True,
    )

    source_ledger_raw = (runtime / "state" / "source_ledger" / "latest.json").read_text(
        encoding="utf-8"
    )
    source_urls = [
        str(card.get("source_url") or "")
        for card in payload["source_topic_claimcards"]["claim_cards"]
    ]
    assert payload["status"] == "source_family_wave_scheduler_ready"
    assert payload["source_package"]["manifest_driven"] is True
    assert payload["source_package"]["frontier_source_files"] == [
        "01_current_summary.txt",
        "02_current_p0.txt",
    ]
    assert payload["total_source_frontier_coverage"]["manifest_driven"] is True
    assert all(
        "old_total_20260702.txt" not in path
        for path in payload["total_source_frontier_coverage"]["source_files"]
    )
    assert payload["source_topic_claimcards"]["new_claim_card_count"] > 0
    assert all("old_total_20260702.txt" not in url for url in source_urls)
    assert "old_total_20260702.txt" not in source_ledger_raw


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
    assert payload["dynamic_width"]["fixed_width_literal_used"] is False
    assert payload["dynamic_width"]["formula"]
    assert payload["dynamic_width"]["actual_dispatched_width"] >= 5
    assert payload["worker_assignment"]["mode_counts"]["search"] >= 5
    assert payload["worker_assignment"]["mode_counts"]["read"] == 1
    assert payload["worker_assignment"]["mode_counts"]["audit"] == 1
    assert payload["worker_assignment"]["mode_counts"]["verify"] == 1
    assert payload["worker_assignment"]["mode_counts"]["draft"] == 1
    assert payload["worker_assignment"]["mode_counts"]["merge"] == 1
    assert payload["worker_assignment"]["source_family_lanes_do_not_steal_dp_draft_width"] is True
    assert payload["claim_card_staging_queue"]["non_local_source_family_count"] >= 4
    assert payload["source_family_search_evidence"]["true_source_output_count"] >= 5
    assert payload["source_family_search_evidence"]["candidate_shell_count"] == 0
    assert payload["source_topic_claimcards"]["new_claim_card_count"] > 0
    assert (
        payload["source_topic_claimcards"]["new_claim_card_count"]
        <= module.SOURCE_TOPIC_CLAIMCARD_BATCH_SIZE
    )
    assert payload["total_source_frontier_coverage"]["topic_family_count"] >= 5
    assert payload["total_source_frontier_coverage"]["covered_topic_family_count"] >= 1
    assert payload["total_source_frontier_coverage"]["remaining_topic_family_count"] >= 1
    assert payload["total_source_frontier_coverage"]["source_gap_open"] is True
    assert payload["total_source_frontier_coverage"]["next_source_family_batch"]
    assert payload["fan_in_acceptance_queue"]["fan_in_is_default_heart"] is True
    assert payload["fan_in_acceptance_queue"]["accepted_edge_count"] >= 5
    assert payload["artifact_acceptance_queue"]["accepted_artifact_count"] >= 5
    assert payload["source_ledger_ref"]["exists"] is True
    assert payload["mature_carrier_replacement_bindings"]["thin_bind_landed"] is True
    assert payload["mature_carrier_replacement_bindings"]["thin_bind_landed_count"] >= 2
    assert payload["mature_carrier_replacement_bindings"]["policy_only"] is False
    assert payload["mature_carrier_thin_bind_manifest"]["status"] == "ready"
    assert payload["mature_carrier_thin_bind_manifest"]["capability_id"] == (
        "codex_s.source_family_mature_carrier_thin_bind"
    )
    assert payload["next_frontier_machine_actions"]["should_continue_loop"] is True
    assert payload["next_frontier_machine_actions"]["stop_allowed"] is False
    assert (
        payload["next_frontier_machine_actions"]["source_frontier_gap"][
            "remaining_topic_family_count"
        ]
        >= 1
    )
    assert payload["next_frontier_machine_actions"]["next_frontier"][0]["action"] == (
        "continue_phase4_total_source_frontier_absorption"
    )
    assert payload["black_window_hygiene"]["s_temporal_worker_started_by_hidden_script"] is True
    assert payload["black_window_hygiene"]["legacy_clean_runtime_processes_reference_only"] is True
    assert payload["completion_claim_allowed"] is False
    assert payload["validation"]["passed"] is True

    expected_paths = [
        runtime / "state" / "source_family_wave_scheduler" / "latest.json",
        runtime / "state" / "source_family_wave_plan" / "latest.json",
        runtime
        / "state"
        / "source_family_wave_scheduler"
        / "source_topic_claimcards"
        / "latest.json",
        runtime / "state" / "claim_card_staging_queue" / "latest.json",
        runtime
        / "state"
        / "source_family_wave_scheduler"
        / "source_family_search_evidence"
        / "latest.json",
        runtime
        / "state"
        / "source_family_wave_scheduler"
        / "total_source_frontier_coverage"
        / "latest.json",
        runtime / "state" / "fan_in_acceptance_queue" / "latest.json",
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        runtime / "state" / "source_ledger" / "latest.json",
        runtime / "state" / "mature_carrier_replacement_bindings" / "latest.json",
        runtime
        / "capabilities"
        / "codex_s.source_family_mature_carrier_thin_bind"
        / "manifest.json",
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        runtime / "state" / "background_window_hygiene" / "latest.json",
        runtime / "readback" / "zh" / "wave_block4_20260701_frontier_20260704.md",
    ]
    for path in expected_paths:
        assert path.is_file(), path
