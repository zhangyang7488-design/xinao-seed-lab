import json
from pathlib import Path

from services.agent_runtime import bounded_result_wait as brw


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _seed_runtime(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "status": "current_333_run_index_ready",
            "workflow_id": "codex-s-333-mainline-p0-test",
            "workflow_run_id": "run-test-001",
            "current_state": "running",
            "generated_at": "2026-07-07T22:00:00+08:00",
            "worker_status": {
                "status": "polling",
                "pid": 12345,
                "process_alive": True,
                "pollers_seen": 2,
            },
            "temporal": {
                "running_workflow_count": 1,
                "mainline_candidate_count": 1,
            },
            "reconciliation": {"named_blocker": "", "reconciled": True},
        },
    )
    _write_json(
        runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json",
        {
            "status": "s_tool_registry_ready",
            "provider_ids": [
                "codex_s.333_task_transaction_control",
                "qwen_prepaid_cheap_worker",
                "legacy.deepseek_dp_sidecar",
            ],
        },
    )
    _write_json(
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
        {
            "generated_at": "2026-07-07T22:05:00+08:00",
            "worker_dispatch_real_receipt_ready": True,
            "p0_008_worker_dispatch_real_receipt": {
                "required": True,
                "worker_dispatch_real_receipt_ready": True,
                "receipt_count": 3,
                "phase1_receipt_count": 0,
            },
        },
    )
    _write_json(
        runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json",
        {
            "runtime_enforced": True,
            "trigger_installed": True,
        },
    )
    _write_json(
        runtime / "state" / "worker_brief_queue" / "latest.json",
        {
            "status": "worker_brief_queue_ready",
            "brief_count": 3,
            "source_package_id": "current_p0_three_text_20260707",
        },
    )
    _write_json(
        runtime / "state" / "root_intent_loop_driver" / "latest.json",
        {
            "schema_version": "xinao.codex_s.root_intent_loop_driver.v1",
            "workflow_id": "old-driver-wave",
            "workflow_run_id": "",
            "wave_id": "old-wave",
        },
    )
    status_map = {
        "codex_333_task_transaction_control": "codex_333_task_transaction_control_ready",
        "default_main_loop_trigger_candidate": "default_main_loop_trigger_task_scoped_runtime_enforced",
        "modular_dynamic_worker_pool_phase1": "modular_dynamic_worker_pool_phase1_wave_merged",
        "dynamic_width_policy": "dynamic_width_policy_ready",
        "333_sleep_watch_p0_landing": "333_sleep_watch_p0_landing_ready",
        "codex_333_host_dialogue_gate_trace": "host_dialogue_gate_trace_ready",
        "codex_333_legacy_freeze_manifest": "legacy_freeze_manifest_ready",
        "codex_333_control_vs_evidence_boundary_contract": "control_vs_evidence_boundary_contract_ready",
    }
    for sub, status in status_map.items():
        _write_json(
            runtime / "state" / sub / "latest.json",
            {
                "status": status,
                "validation": {
                    "passed": True,
                    "checks": {"provider_realness_gate_rejects_fake": True},
                },
                "completion_claim_allowed": False,
                "trigger_truth_chain": {"ready": True},
            },
        )


def _source_files(tmp_path: Path) -> list[Path]:
    root = tmp_path / "sources"
    root.mkdir()
    files = []
    for name, body in {
        "01_总说明_本项目是什么_20260707.txt": "project boundary\n",
        "02_P0_底座全自动任务落地_20260707.txt": "p0 execution entrypoint\n",
        "03_P1_任务落地_20260707.txt": "p1 gate context\n",
    }.items():
        path = root / name
        path.write_text(body, encoding="utf-8")
        files.append(path)
    return files


def test_bounded_result_wait_builds_readback_and_rebinds_driver(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_runtime(runtime)

    payload = brw.build_bounded_result_wait(
        runtime_root=runtime,
        repo_root=repo,
        source_files=_source_files(tmp_path),
        write=True,
        write_aaq=False,
    )

    assert payload["bounded_result_wait_ready"] is True
    assert payload["current_state"] in {"running", "result_ready", "waiting"}
    assert payload["validation"]["checks"]["root_intent_loop_driver_rebound"] is True
    assert payload["validation"]["checks"]["continuity_router_regenerated"] is True

    latest = json.loads(
        (runtime / "state" / "bounded_result_wait" / "latest.json").read_text(encoding="utf-8")
    )
    assert latest["task_id"] == brw.TASK_ID
    assert latest["bounded_result_wait_ready"] is True

    driver = json.loads(
        (runtime / "state" / "root_intent_loop_driver" / "latest.json").read_text(encoding="utf-8")
    )
    assert driver["workflow_id"] == "codex-s-333-mainline-p0-test"
    assert driver["workflow_run_id"] == "run-test-001"

    readback = (runtime / "readback" / "zh" / "bounded_result_wait_20260707.md").read_text(
        encoding="utf-8"
    )
    assert "后台现在在干嘛" in readback
    assert "下一机器动作" in readback


def test_bounded_result_wait_marks_blocked_when_worker_not_polling(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_runtime(runtime)
    current = runtime / "state" / "current_333_run_index" / "latest.json"
    payload = json.loads(current.read_text(encoding="utf-8"))
    payload["worker_status"]["status"] = "stopped"
    payload["worker_status"]["process_alive"] = False
    current.write_text(json.dumps(payload), encoding="utf-8")

    result = brw.build_bounded_result_wait(
        runtime_root=runtime,
        repo_root=repo,
        write=False,
        write_aaq=False,
    )
    assert result["current_state"] == "blocked"
    assert result["named_blocker"] == "TEMPORAL_WORKER_NOT_POLLING"
