import json
from pathlib import Path

from services.agent_runtime import mature_binding_gap_ledger as ledger


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_task_package(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "current.txt").write_text("current task\n", encoding="utf-8")
    _write_json(
        root / "TASK_PACKAGE.json",
        {
            "schema_version": "xinao.codex_s.task_package_manifest.v1",
            "package_mode": "unit_current",
            "entrypoint": "current.txt",
            "mature_bind_queue": [
                {
                    "task_id": "p0_004a_provider_lane_index",
                    "status": "ready",
                    "deliverable": "provider lane index",
                    "verification": ["pytest"],
                    "acceptance": {
                        "success_decision": "accepted_for_binding",
                        "success_field": "provider_lane_index_ready",
                    },
                },
                {
                    "task_id": "p0_005_mature_binding_gap_ledger",
                    "status": "ready",
                    "deliverable": "gap ledger",
                    "verification": ["pytest"],
                    "acceptance": {
                        "success_decision": "accepted_for_delivery",
                        "success_field": "mature_binding_gap_ledger_ready",
                    },
                },
            ],
            "resources": [{"path": "current.txt", "role": "entrypoint"}],
        },
    )


def _seed_runtime(runtime: Path) -> None:
    workflow_id = "codex-s-333-mainline-p0-20260707-r9-task-package-resolver-global-hardened"
    run_id = "run-current"
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "status": "current_333_run_index_ready",
            "workflow_id": workflow_id,
            "workflow_run_id": run_id,
            "temporal": {"running_workflow_count": 1, "mainline_candidate_count": 1},
            "worker_status": {"status": "polling", "pollers_seen": 4},
        },
    )
    _write_json(
        runtime
        / "state"
        / "codex_native_provider_scheduler_phase4_20260704"
        / "provider_lane_index"
        / "latest.json",
        {
            "status": "provider_lane_index_ready",
            "binding_id": "p0_004a_provider_lane_index",
            "accepted_for": "accepted_for_binding",
            "artifact_acceptance_decision": "accepted_for_binding",
            "route_count": 6,
            "model_lane_count": 19,
        },
    )
    _write_json(
        runtime / "runs" / "episodes" / "p0-004a" / "artifact_acceptance.json",
        {
            "decisions": [
                {
                    "candidate_id": "p0_004a_provider_lane_index",
                    "status": "accepted",
                    "artifact_acceptance_decision": "accepted_for_binding",
                    "artifact_ref": "provider_lane_index/latest.json",
                    "workflow_id": workflow_id,
                    "workflow_run_id": run_id,
                }
            ]
        },
    )
    _write_json(
        runtime / "state" / "task_contract_router" / "latest.json",
        {
            "status": "execution_contract_ready",
            "contract_id": "p0_005_mature_binding_gap_ledger",
            "workflow_id": workflow_id,
            "workflow_run_id": run_id,
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        {
            "status": "artifact_acceptance_queue_ready",
            "accepted_for_binding_count": 1,
            "accepted_for_delivery_count": 0,
            "accepted_for_next_frontier_only": False,
            "decisions": [
                {
                    "candidate_id": "p0_004a_provider_lane_index",
                    "status": "accepted",
                    "artifact_acceptance_decision": "accepted_for_binding",
                    "artifact_ref": "provider_lane_index/latest.json",
                    "workflow_id": workflow_id,
                    "workflow_run_id": run_id,
                }
            ],
        },
    )
    _write_json(
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
        {
            "status": "worker_dispatch_ledger_poll_ready",
            "adoption_state": "runtime_enforced_hot_path_hooked",
            "dispatch_entries": [{"adoption_state": "verifier_ready_but_not_hooked"}],
            "summary": {"spawned_external_agent_count": 0},
            "succeeded_count": 21,
        },
    )
    _write_json(
        runtime / "state" / "root_intent_loop_driver" / "latest.json",
        {
            "status": "root_intent_loop_driver_ready",
            "workflow_id": "codex-s-root-intent-loop-driver-verify-20260703",
            "workflow_run_id": "",
        },
    )
    _write_json(
        runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json",
        {
            "status": "continuity_router_ready",
            "source_package_id": "current_p0_three_text_20260707",
            "named_blocker": "TEMPORAL_WORKER_NOT_POLLING",
        },
    )
    _write_json(
        runtime / "state" / "source_ledger" / "latest.json",
        {"status": "source_ledger_ready", "entry_count": 1, "entries": [{"source": "old"}]},
    )
    _write_json(
        runtime / "state" / "codex_333_control_vs_evidence_boundary_contract" / "latest.json",
        {"status": "ready", "source_package_root": "C:/Users/xx363/Desktop/新建文件夹/20260705"},
    )
    _write_json(
        runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json",
        {
            "status": "default_main_loop_trigger_candidate_ready",
            "runtime_enforced": False,
            "trigger_installed": False,
            "root_loop_every_wave_enforced": False,
            "base_tick_adoption_state": "verifier_ready_but_not_hooked",
        },
    )
    _write_json(
        runtime / "state" / "codex_s_main_execution_loop_tick" / "latest.json",
        {
            "status": "codex_s_main_execution_loop_tick_ready",
            "adoption_state": "verifier_ready_but_not_hooked",
            "invoked_worker_dispatch_ledger": {"status": "worker_dispatch_ledger_verifier_passed_not_hooked"},
        },
    )
    _write_json(
        runtime / "state" / "codex_333_p1_loop_frontier" / "latest.json",
        {"status": "frontier_ready"},
    )


def test_mature_binding_gap_ledger_classifies_runtime_and_names_lying_layers(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    task_root = tmp_path / "新系统"
    repo.mkdir()
    _write_task_package(task_root)
    _seed_runtime(runtime)

    payload = ledger.build_mature_binding_gap_ledger(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_root,
        write=True,
    )

    by_id = {item["state_id"]: item for item in payload["classifications"]}
    lying_ids = {item["state_id"] for item in payload["lying_layers"]}
    assert payload["status"] == "mature_binding_gap_ledger_ready"
    assert payload["validation"]["passed"] is True
    assert payload["task_package"]["next_mature_bind_task_id"] == "p0_005_mature_binding_gap_ledger"
    assert payload["task_contract_router"]["contract_id"] == "p0_005_mature_binding_gap_ledger"
    assert payload["p0_004a_provider_lane_index"]["bound"] is True
    assert by_id["worker_dispatch_ledger"]["category"] == "installed_not_bound"
    assert by_id["root_intent_loop_driver"]["category"] == "installed_not_bound"
    assert by_id["codex_333_stateful_continuity_router"]["category"] == "installed_not_bound"
    assert by_id["source_ledger"]["category"] == "installed_not_bound"
    assert "worker_dispatch_ledger" in lying_ids
    assert "root_intent_loop_driver" in lying_ids
    assert "codex_333_stateful_continuity_router" in lying_ids
    assert "source_ledger" in lying_ids
    assert payload["expected_missing_targets"]
    assert payload["completion_claim_allowed"] is False

    readback = Path(payload["output_paths"]["readback"]).read_text(encoding="utf-8")
    assert "哪层在撒谎" in readback
    assert "下一机器动作" in readback
