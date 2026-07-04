import importlib.util
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT
    / "services"
    / "agent_runtime"
    / "temporal_activity_no_window_dp_worker_pool_phase3.py"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "contracts"
    / "schemas"
    / "codex_s_temporal_activity_no_window_dp_worker_pool_phase3.v1.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("phase3", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_source_entry() -> dict[str, Any]:
    return {
        "source_entry_root": "C:\\Users\\xx363\\Desktop\\新系统",
        "source_entry_read_at": "2026-07-04T00:00:00+0800",
        "exists": True,
        "is_directory": True,
        "file_count": 1,
        "sampled_count": 1,
        "sampled_files": [{"name": "XINAO_333_固定锚点.txt", "path": "anchor"}],
        "source_entry_digest_sha256": "source-digest",
    }


def _fake_anchor_facts() -> dict[str, Any]:
    return {
        "anchors": [
            {"path": "anchor", "name": "XINAO_333_固定锚点.txt", "exists": True}
        ],
        "all_required_present": True,
        "digest_sha256": "anchor-digest",
        "read_at": "2026-07-04T00:00:00+0800",
    }


def _fake_phase1_payload(
    runtime: Path,
    wave_id: str,
    *,
    blocked: bool = False,
    dynamic_width_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = runtime / "state" / "modular_dynamic_worker_pool_phase1"
    latest = state / "latest.json"
    staging = state / "draft_staging_queue" / "latest.json"
    merge_latest = state / "merge_consumer" / "latest.json"
    spend = state / "spend_ledger" / "latest.json"
    merge_artifact = runtime / "merge" / f"{wave_id}.md"
    for path in [latest, staging, merge_latest, spend, merge_artifact]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    true_dp = 0 if blocked else 5
    local_stub = 5 if blocked else 0
    width_decision = dynamic_width_decision or {
        "target_width": 8,
        "target_width_source": "dynamic_width_scheduler",
        "width_decision_reason": "pytest dynamic width decision",
        "width_decision_inputs": {"source_sampled_count": 1},
        "width_candidates": {"independent_task_count": 8},
        "recomputed_each_wave": True,
        "operator_cap_applied": False,
    }
    target_width = int(width_decision.get("target_width") or 8)
    fake_mode_counts = {
        "draft": max(1, target_width - 3),
        "eval": 1,
        "contradiction": 1,
        "audit": 1,
    }
    lane_results = [
        {
            "lane_id": f"{wave_id}-draft-{index:02d}",
            "mode": "draft",
            "status": "succeeded" if not blocked else "blocked",
            "artifact_ref": str(merge_artifact),
            "provider_invocation_ref": str(runtime / f"provider-{index}.json"),
            "selected_carrier_provider_id": "legacy.deepseek_dp_sidecar"
            if not blocked
            else "seed_cortex.local_draft_artifact_provider",
            "usage": {"latency_ms": 100},
            "named_blocker": "",
        }
        for index in range(1, 6)
    ]
    return {
        "wave_id": wave_id,
        "status": "modular_dynamic_worker_pool_phase1_wave_merged"
        if not blocked
        else "modular_dynamic_worker_pool_phase1_wave_blocked",
        "validation": {"passed": not blocked, "checks": {}},
        "target_width": target_width,
        "target_width_source": width_decision.get("target_width_source"),
        "width_decision_reason": width_decision.get("width_decision_reason"),
        "width_decision_inputs": width_decision.get("width_decision_inputs") or {},
        "width_candidates": width_decision.get("width_candidates") or {},
        "recomputed_each_wave": width_decision.get("recomputed_each_wave") is True,
        "operator_cap_applied": width_decision.get("operator_cap_applied") is True,
        "dynamic_width_policy": {
            "target_width": target_width,
            "target_width_source": width_decision.get("target_width_source"),
            "width_decision_reason": width_decision.get("width_decision_reason"),
            "width_decision_inputs": width_decision.get("width_decision_inputs") or {},
            "width_candidates": width_decision.get("width_candidates") or {},
            "recomputed_each_wave": width_decision.get("recomputed_each_wave") is True,
            "operator_cap_applied": width_decision.get("operator_cap_applied") is True,
            "fixed_20_or_50_used": False,
        },
        "actual_dispatched_width": target_width,
        "actual_completed_width": target_width if not blocked else 2,
        "mode_counts": fake_mode_counts,
        "draft_count": 5,
        "true_dp_draft_count": true_dp,
        "local_stub_draft_count": local_stub,
        "staged_count": 5,
        "merged_count": 1 if not blocked else 0,
        "spend_entry_count": target_width if not blocked else 0,
        "provider_tier_usage": {"cheap": target_width},
        "token_cost_spend": {"total_tokens": 1000, "metered_usage_entry_count": target_width},
        "rate_limit_error": "",
        "named_blocker": "",
        "merge_artifact": str(merge_artifact),
        "lane_results": lane_results,
        "draft_staging_queue": {"staged_count": 5, "draft_count": 5},
        "merge_consumer": {"merged_count": 1 if not blocked else 0, "merge_artifact": str(merge_artifact)},
        "evidence_refs": {
            "runtime_latest": str(latest),
            "draft_staging_queue_latest": str(staging),
            "merge_consumer_latest": str(merge_latest),
            "spend_ledger_latest": str(spend),
        },
    }


def test_schema_requires_temporal_event_queue_and_stop_fields() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.temporal_activity_no_window_dp_worker_pool_phase3.v1"
    )
    assert "active_workers" in schema["required"]
    assert "task_backlog" in schema["required"]
    assert "ready_frontier" in schema["required"]
    assert "stop" in schema["required"]
    assert schema["properties"]["background"]["properties"]["main_loop"]["const"] == (
        "temporal_activity_event_queue_loop"
    )
    assert schema["properties"]["stop"]["properties"]["derived"]["const"] is True


def test_phase3_activity_sequence_writes_canonical_loop_state_and_disables_legacy_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    monkeypatch.setattr(module, "authority_anchor_facts", _fake_anchor_facts)
    monkeypatch.setattr(module.phase1, "scan_source_entry", lambda root=None: _fake_source_entry())
    monkeypatch.setattr(
        module.phase1,
        "run_wave",
        lambda **kwargs: _fake_phase1_payload(
            runtime,
            kwargs["wave_id"],
            dynamic_width_decision=kwargs.get("dynamic_width_decision"),
        ),
    )

    payload = module.run_activity_sequence(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase3-test-wave-001",
        target_width=8,
        max_parallel_workers=3,
        workflow_id="wf-phase3",
        workflow_run_id="run-phase3",
        task_queue="xinao-codex-task-default",
        worker_identity="pytest-worker",
        write=True,
    )

    assert payload["validation"]["passed"] is True
    loop_state = json.loads(
        (runtime / "state" / "loop_runtime_state" / "latest.json").read_text(encoding="utf-8")
    )
    assert loop_state["background"]["main_loop"] == "temporal_activity_event_queue_loop"
    assert loop_state["background"]["sleep_seconds_1800_default_main_loop_allowed"] is False
    assert loop_state["background"]["legacy_runners"]["runner_30min_cancelled_or_frozen"] is True
    assert loop_state["draft_staging"]["staged_count"] == 5
    assert loop_state["draft_staging"]["merged_count"] == 1
    assert loop_state["phase1_payload_summary"]["actual_dispatched_width"] >= 3
    assert loop_state["phase1_payload_summary"]["target_width_source"] == "dynamic_width_scheduler"
    assert loop_state["phase1_payload_summary"]["recomputed_each_wave"] is True
    assert loop_state["capacity_by_lane_class"]["dynamic_width_record"]["fixed_20_or_50_used"] is False
    assert loop_state["stop"]["derived"] is True
    assert loop_state["stop"]["stop_allowed"] is False
    assert loop_state["stop"]["reason_flags"]["task_backlog"] is True
    assert loop_state["temporal"]["workflow_id"] == "wf-phase3"
    assert "next_machine_action" in (
        runtime
        / "readback"
        / "zh"
        / f"{module.TASK_ID}.md"
    ).read_text(encoding="utf-8")


def test_missing_external_dp_provider_is_named_blocker(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    monkeypatch.setattr(module, "authority_anchor_facts", _fake_anchor_facts)
    monkeypatch.setattr(module.phase1, "scan_source_entry", lambda root=None: _fake_source_entry())
    monkeypatch.setattr(
        module.phase1,
        "run_wave",
        lambda **kwargs: _fake_phase1_payload(
            runtime,
            kwargs["wave_id"],
            blocked=True,
            dynamic_width_decision=kwargs.get("dynamic_width_decision"),
        ),
    )

    payload = module.run_activity_sequence(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase3-blocked-wave-001",
        target_width=8,
        max_parallel_workers=3,
        workflow_id="wf-phase3",
        workflow_run_id="run-phase3",
        write=True,
    )
    loop_state = payload["activities"]["loop_runtime_state_update_activity"]

    assert loop_state["phase1_payload_summary"]["named_blocker"] == "DEEPSEEK_PROVIDER_NOT_CONFIGURED"
    assert loop_state["blockers"][0]["named_blocker"] == "DEEPSEEK_PROVIDER_NOT_CONFIGURED"
    assert loop_state["acceptance"]["completion_claim_allowed"] is False
    assert loop_state["status"] == "phase3_temporal_activity_event_queue_wave_ready"
    assert loop_state["stop"]["derived"] is True
    assert loop_state["stop"]["stop_allowed"] is False
