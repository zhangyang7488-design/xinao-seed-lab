import importlib.util
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT
    / "services"
    / "agent_runtime"
    / "loop_runtime_state_supervisor_worker_pool_phase2.py"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "contracts"
    / "schemas"
    / "codex_s_loop_runtime_state_supervisor_worker_pool_phase2.v1.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("phase2", MODULE_PATH)
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


def _fake_phase1_payload(runtime: Path, wave_id: str, *, blocked: bool = False) -> dict[str, Any]:
    merge_artifact = runtime / "merge" / f"{wave_id}.md"
    merge_artifact.parent.mkdir(parents=True, exist_ok=True)
    merge_artifact.write_text(
        "# merge\n\n## Progress This Wave\n\n## Adopted Drafts\n",
        encoding="utf-8",
    )
    latest = runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json"
    decision = (
        runtime
        / "state"
        / "modular_dynamic_worker_pool_phase1"
        / "foreground_brain_decision"
        / "latest.json"
    )
    latest.parent.mkdir(parents=True, exist_ok=True)
    decision.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text("{}\n", encoding="utf-8")
    decision.write_text("{}\n", encoding="utf-8")
    true_dp = 0 if blocked else 5
    local_stub = 5 if blocked else 0
    lane_results = []
    for index in range(1, 6):
        lane_results.append(
            {
                "lane_id": f"{wave_id}-draft-{index:02d}",
                "mode": "draft",
                "objective": "draft",
                "status": "succeeded" if not blocked else "blocked",
                "selected_carrier_provider_id": "legacy.deepseek_dp_sidecar"
                if not blocked
                else "seed_cortex.local_draft_artifact_provider",
                "artifact_ref": str(merge_artifact),
                "provider_invocation_ref": str(runtime / "provider.json"),
                "provider_latest_ref": str(runtime / "provider_latest.json"),
                "usage": {"latency_ms": 100},
                "named_blocker": "",
            }
        )
    return {
        "wave_id": wave_id,
        "status": "modular_dynamic_worker_pool_phase1_wave_merged"
        if not blocked
        else "modular_dynamic_worker_pool_phase1_wave_blocked",
        "validation": {"passed": not blocked, "checks": {}},
        "target_width": 8,
        "actual_dispatched_width": 8,
        "actual_completed_width": 8 if not blocked else 3,
        "mode_counts": {
            "draft": 5,
            "eval": 1,
            "contradiction": 1,
            "audit": 1,
            "extraction": 0,
            "citation_verify": 0,
            "search": 0,
            "provider_probe": 0,
            "search_assist": 0,
        },
        "draft_count": 5,
        "true_dp_draft_count": true_dp,
        "local_stub_draft_count": local_stub,
        "staged_count": 5,
        "merged_count": 1 if not blocked else 0,
        "spend_entry_count": 8 if not blocked else 0,
        "provider_tier_usage": {"cheap": 8},
        "token_cost_spend": {"total_tokens": 1000, "metered_usage_entry_count": 8},
        "rate_limit_error": "",
        "named_blocker": "",
        "merge_artifact": str(merge_artifact),
        "lane_results": lane_results,
        "artifact_acceptance_queue": {
            "output_paths": {"runtime_latest": str(runtime / "aaq.json")}
        },
        "readback_refs": {"runtime_readback_zh": str(runtime / "readback.md")},
        "evidence_refs": {
            "runtime_latest": str(latest),
            "draft_staging_queue_latest": str(runtime / "draft_queue.json"),
            "foreground_brain_decision_latest": str(decision),
        },
    }


def test_schema_requires_loop_runtime_state_stop_and_queue_fields() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.loop_runtime_state_supervisor_worker_pool_phase2.v1"
    )
    assert "active_workers" in schema["required"]
    assert "task_backlog" in schema["required"]
    assert "ready_frontier" in schema["required"]
    assert "stop" in schema["required"]
    assert schema["properties"]["stop"]["properties"]["derived"]["const"] is True


def test_queue_consumer_tick_writes_loop_runtime_state_with_derived_stop_false(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    monkeypatch.setattr(module, "authority_anchor_facts", _fake_anchor_facts)
    monkeypatch.setattr(module.phase1, "scan_source_entry", lambda root: _fake_source_entry())
    monkeypatch.setattr(
        module.phase1,
        "run_wave",
        lambda **kwargs: _fake_phase1_payload(runtime, kwargs["wave_id"]),
    )

    payload = module.run_queue_consumer_tick(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase2-test-wave-001",
        target_width=8,
        max_parallel_workers=3,
        successor_delay_seconds=60,
        write=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["background"]["main_loop"] == "task_queue_worker_pool_consumer"
    assert payload["task_backlog"]
    assert payload["draft_staging"]["staged_count"] == 5
    assert payload["draft_staging"]["merged_count"] == 1
    assert payload["capacity_by_lane_class"]["dp_draft"]["draft_is_primary"] is True
    assert payload["capacity_by_lane_class"]["dynamic_width_record"]["queue_depth"] >= 1
    assert payload["stop"]["derived"] is True
    assert payload["stop"]["stop_allowed"] is False
    assert payload["stop"]["reason_flags"]["task_backlog"] is True
    assert Path(payload["identity"]["checkpoint_ref"]).is_file()
    assert (runtime / "readback" / "zh" / f"{module.TASK_ID}.md").is_file()


def test_missing_external_dp_provider_becomes_named_blocker(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    monkeypatch.setattr(module, "authority_anchor_facts", _fake_anchor_facts)
    monkeypatch.setattr(module.phase1, "scan_source_entry", lambda root: _fake_source_entry())
    monkeypatch.setattr(
        module.phase1,
        "run_wave",
        lambda **kwargs: _fake_phase1_payload(runtime, kwargs["wave_id"], blocked=True),
    )

    payload = module.run_queue_consumer_tick(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase2-blocked-wave-001",
        target_width=8,
        max_parallel_workers=3,
        write=True,
    )

    assert payload["validation"]["passed"] is False
    assert payload["blockers"]
    assert payload["blockers"][0]["named_blocker"] == "DEEPSEEK_PROVIDER_NOT_CONFIGURED"
    assert payload["stop"]["derived"] is True
    assert payload["stop"]["stop_allowed"] is False
