import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "source_frontier_fanin_acceptance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("source_frontier_fanin_acceptance", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_anchor(anchor: Path) -> None:
    anchor.mkdir(parents=True, exist_ok=True)
    files = {
        "AUTHORITY_READ_ORDER.txt": "read order\nFanInAcceptanceQueue\n",
        "新系统独立并行_自由发散外部研究总稿_20260701.txt": (
            "20260701 root\nPhase 0\nNextFrontier\n四对象\n"
        ),
        "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt": (
            "20260702 execution\nFanInAcceptanceQueue\nClaimCard\nArtifactAcceptanceQueue\n"
        ),
    }
    for name, text in files.items():
        (anchor / name).write_text(text, encoding="utf-8")


def test_source_frontier_fanin_acceptance_writes_default_hot_path_refs(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "Desktop" / "新系统"
    repo.mkdir()
    _seed_anchor(anchor)

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        wave_id="unit-wave",
        invoked_by_main_execution_loop_tick=True,
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.source_frontier_fanin_acceptance.v1"
    assert payload["status"] == "source_frontier_fanin_acceptance_ready"
    assert payload["adoption_state"] == "default_hot_path_ready"
    assert payload["work_id"] == "xinao_seed_cortex_phase0_20260701"
    assert payload["parent_task_id"] == "xinao_seed_cortex_phase0_20260701"
    assert payload["task_id"] == "wave3_20260702_absorption_slice_20260704"
    assert payload["routing"] == "continue_same_task"
    assert payload["runtime_enforced"] is False
    assert payload["trigger_installed"] is False
    assert payload["source_package"]["all_required_sources_read_full"] is True
    assert payload["worker_assignment"]["parent_task_id"] == "xinao_seed_cortex_phase0_20260701"
    assert payload["worker_assignment"]["task_id"] == "wave3_20260702_absorption_slice_20260704"
    assert payload["worker_assignment"]["routing"] == "continue_same_task"
    assert payload["worker_assignment"]["not_provider_scheduler_main_task"] is True
    assert payload["worker_assignment"]["while_driver"] == "event_backlog_frontier_driven"
    assert payload["worker_assignment"]["forbid_fixed_interval_main_loop"] is True
    assert payload["worker_assignment"]["no_side_queue_island"]["not_new_bypass_queue"] is True
    assert payload["fan_in_acceptance_queue"]["fan_in_is_default_heart"] is True
    assert payload["fan_in_acceptance_queue"]["not_new_bypass_queue"] is True
    assert "draft_staging" in payload["fan_in_acceptance_queue"]["connects_existing_chain"]
    assert payload["fan_in_acceptance_queue"]["accepted_edge_count"] >= 4
    assert payload["claim_card_staging_queue"]["non_local_source_family_count"] >= 2
    assert payload["artifact_acceptance_queue"]["accepted_artifact_count"] >= 4
    assert payload["artifact_acceptance_queue"]["claim_card_requires_source_ledger"] is True
    assert payload["episode_workflow_entry"]["workflow_owner"] == "Codex S foreground brain"
    assert payload["next_frontier_machine_actions"]["should_continue_loop"] is True
    assert payload["next_frontier_machine_actions"]["stop_allowed"] is False
    assert payload["next_frontier_machine_actions"]["sleep_1800_main_loop_allowed"] is False
    assert payload["next_frontier_machine_actions"]["source_frontier_gap"]["source_package_gap_open"] is True
    assert payload["default_hot_path_binding"]["provider_scheduler_main_task"] is False
    assert payload["default_hot_path_binding"]["fan_in_acceptance_queue_not_bypass_island"] is True
    assert payload["default_hot_path_binding"]["connects_existing_draft_staging_merge_aaq_next_frontier"] is True
    assert payload["completion_claim_allowed"] is False
    assert payload["validation"]["passed"] is True

    worker_assignment = runtime / "state" / "worker_assignment" / "wave3_20260702_absorption_slice_20260704.json"
    parent_link = runtime / "state" / "worker_assignment" / "xinao_seed_cortex_phase0_20260701.current_source_frontier_slice.json"
    fan_in = runtime / "state" / "fan_in_acceptance_queue" / "latest.json"
    parallel_fan_in = runtime / "state" / "parallel_fan_in_acceptance" / "latest.json"
    aaq = runtime / "state" / "artifact_acceptance_queue" / "latest.json"
    source_ledger = runtime / "state" / "source_ledger" / "latest.json"
    episode_entry = runtime / "runs" / "episodes" / "source-frontier-fanin-acceptance-unit-wave" / "workflow_entry.json"
    for path in [worker_assignment, parent_link, fan_in, parallel_fan_in, aaq, source_ledger, episode_entry]:
        assert path.is_file(), path

    assignment_payload = json.loads(worker_assignment.read_text(encoding="utf-8"))
    assert assignment_payload["assignment_dag"]["current_active_node_id"] == (
        "fan_in_acceptance_queue_default_heart"
    )
    assert assignment_payload["task_id"] == "wave3_20260702_absorption_slice_20260704"
    assert assignment_payload["parent_task_id"] == "xinao_seed_cortex_phase0_20260701"

    ledger_payload = json.loads(source_ledger.read_text(encoding="utf-8"))
    assert ledger_payload["entry_count"] >= 4
    assert ledger_payload["claim_card_hard_gate_enforced"] is True


def test_source_frontier_fanin_acceptance_shortens_long_worker_assignment_wave_path(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "Desktop" / "新系统"
    repo.mkdir()
    _seed_anchor(anchor)
    long_wave_id = (
        "codex-s-durable-default-chain-supervisor-20260704-night-sroute-fixed-"
        "continuation-b4e99ed-live-000001-wave-02-parallel_draft_batch_bind-"
        "source-frontier-fanin"
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        wave_id=long_wave_id,
        invoked_by_main_execution_loop_tick=True,
        write=True,
    )

    worker_assignment_wave = Path(payload["output_paths"]["worker_assignment_wave"])
    assert worker_assignment_wave.is_file()
    assert long_wave_id not in worker_assignment_wave.name
    assert module.short_wave_stem(long_wave_id) in worker_assignment_wave.name
    assert len(worker_assignment_wave.name) < 220

    worker_assignment_payload = json.loads(worker_assignment_wave.read_text(encoding="utf-8"))
    assert worker_assignment_payload["wave_id"] == long_wave_id


def test_durable_consumer_eats_wave3_batches_and_clears_source_gap(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "Desktop" / "新系统"
    repo.mkdir()
    _seed_anchor(anchor)

    payload = module.consume_source_frontier_backlog(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        wave_id="unit-consume",
        max_waves=len(module.SOURCE_FRONTIER_BATCHES),
        durable_activity_invoked=True,
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.source_frontier_durable_consumer.v1"
    assert payload["status"] == "source_frontier_module_consumed"
    assert payload["task_id"] == "wave3_20260702_absorption_slice_20260704"
    assert payload["parent_task_id"] == "xinao_seed_cortex_phase0_20260701"
    assert payload["routing"] == "continue_same_task"
    assert payload["while_driver"] == "event_backlog_frontier_driven"
    assert payload["durable_activity_invoked"] is True
    assert payload["source_gap_open"] is False
    assert payload["remaining_batch_ids"] == []
    assert payload["consumed_batch_ids"] == module.batch_ids()
    assert payload["validation"]["passed"] is True
    assert payload["completion_claim_allowed"] is False
    assert len(payload["wave_payload_refs"]) == len(module.SOURCE_FRONTIER_BATCHES)
    assert all(ref["fan_in_ref"] and ref["aaq_ref"] for ref in payload["wave_payload_refs"])

    consumer_latest = runtime / "state" / "source_frontier_durable_consumer" / "latest.json"
    lane_review = runtime / "state" / "lane_result_review" / "latest.json"
    reward_signal = runtime / "state" / "reward_signal" / "latest.json"
    next_frontier = runtime / "state" / "next_frontier_machine_actions" / "latest.json"
    readback = runtime / "readback" / "zh" / "source_frontier_durable_consumer_20260704.md"
    for path in [consumer_latest, lane_review, reward_signal, next_frontier, readback]:
        assert path.is_file(), path

    next_payload = json.loads(next_frontier.read_text(encoding="utf-8"))
    assert next_payload["should_continue_loop"] is False
    assert next_payload["stop_allowed"] is True
    assert next_payload["source_frontier_gap"]["source_package_gap_open"] is False
    assert next_payload["completion_claim_allowed"] is False

    rebuilt = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        wave_id="unit-after-consume",
        write=False,
    )
    assert rebuilt["validation"]["passed"] is True
    assert rebuilt["next_frontier_machine_actions"]["source_frontier_gap"][
        "source_package_gap_open"
    ] is False
