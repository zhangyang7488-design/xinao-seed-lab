import json
from pathlib import Path

from services.agent_runtime import current_task_source_intake as intake

from xinao_seedlab.application.seed_cortex import build_default_service


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_task_package(root: Path) -> None:
    root.mkdir(parents=True)
    for name, text in {
        "01.txt": "project summary\n",
        "02.txt": "p0 execution entrypoint\n",
        "03.txt": "p1 gate context\n",
    }.items():
        (root / name).write_text(text, encoding="utf-8")
    _write_json(
        root / "TASK_PACKAGE.json",
        {
            "schema_version": "xinao.codex_s.task_package_manifest.v1",
            "package_mode": "current_three_text_p0",
            "entrypoint": "02.txt",
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
                {
                    "task_id": "p0_006_current_three_text_source_intake",
                    "status": "ready",
                    "deliverable": "three text SourceLedger and WorkerBrief queue",
                    "verification": ["pytest tests/seedcortex/test_current_task_source_intake.py"],
                    "acceptance": {
                        "success_decision": "accepted_for_delivery",
                        "success_field": "current_task_source_intake_ready",
                    },
                },
            ],
            "resources": [
                {"path": "01.txt", "role": "project_summary"},
                {"path": "02.txt", "role": "p0_execution_entrypoint"},
                {"path": "03.txt", "role": "p1_gate_context"},
            ],
        },
    )


def _accept(runtime: Path, task_id: str, decision: str) -> None:
    _write_json(
        runtime / "runs" / "episodes" / task_id / "artifact_acceptance.json",
        {
            "decisions": [
                {
                    "candidate_id": task_id,
                    "status": "accepted",
                    "artifact_acceptance_decision": decision,
                    "artifact_ref": f"{task_id}/latest.json",
                    "workflow_id": "workflow-r9",
                    "workflow_run_id": "run-r9",
                }
            ]
        },
    )


def test_current_task_source_intake_writes_sourceledger_and_workerbrief_queue(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    task_root = tmp_path / "新系统"
    repo.mkdir()
    _write_task_package(task_root)
    _accept(runtime, "p0_004a_provider_lane_index", "accepted_for_binding")
    _accept(runtime, "p0_005_mature_binding_gap_ledger", "accepted_for_delivery")
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "status": "current_333_run_index_ready",
            "workflow_id": "workflow-r9",
            "workflow_run_id": "run-r9",
            "temporal": {"running_workflow_count": 1, "mainline_candidate_count": 1},
            "worker_status": {"status": "polling"},
        },
    )
    _write_json(
        runtime / "state" / "task_contract_router" / "latest.json",
        {
            "status": "execution_contract_ready",
            "contract_id": "p0_006_current_three_text_source_intake",
            "workflow_id": "workflow-r9",
            "workflow_run_id": "run-r9",
            "validation": {"passed": True},
        },
    )

    payload = intake.build_current_task_source_intake(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_root,
        write=True,
    )
    service = build_default_service(runtime, repo_root=repo)
    aaq = service.artifact_acceptance_queue(
        "p0-006-current-task-source-intake-accepted",
        [
            {
                "candidate_id": "p0_006_current_three_text_source_intake",
                "artifact_ref": payload["output_paths"]["latest"],
                "artifact_kind": "current_task_source_intake",
                "workflow_id": "workflow-r9",
                "workflow_run_id": "run-r9",
                "accepted_for": "accepted_for_delivery",
                "artifact_acceptance_decision": "accepted_for_delivery",
            }
        ],
        write_runtime=True,
    )

    source_ledger = json.loads(
        (runtime / "state" / "source_ledger" / "latest.json").read_text(encoding="utf-8")
    )
    worker_brief_queue = json.loads(
        (runtime / "state" / "worker_brief_queue" / "latest.json").read_text(encoding="utf-8")
    )
    compat_worker_brief = json.loads(
        (runtime / "state" / "worker_brief" / "latest.json").read_text(encoding="utf-8")
    )
    readback = Path(payload["output_paths"]["readback"]).read_text(encoding="utf-8")

    assert payload["status"] == "current_task_source_intake_ready"
    assert payload["validation"]["passed"] is True
    assert payload["task_package"]["next_mature_bind_task_id"] == "p0_006_current_three_text_source_intake"
    assert payload["source_entry_count"] == 3
    assert source_ledger["status"] == "source_ledger_ready"
    assert source_ledger["entry_count"] == 3
    assert "current_p0_three_text_20260707" in json.dumps(source_ledger, ensure_ascii=False)
    assert worker_brief_queue["status"] == "worker_brief_queue_ready"
    assert worker_brief_queue["brief_count"] == 3
    assert worker_brief_queue["brief_count"] == source_ledger["entry_count"]
    assert worker_brief_queue["dispatch_ready"] is True
    assert worker_brief_queue["next_frontier_default_outlet"] is False
    assert compat_worker_brief["brief_count"] == worker_brief_queue["brief_count"]
    assert all(brief["source_ledger_entry_id"] for brief in worker_brief_queue["briefs"])
    assert aaq["accepted_for_delivery_count"] == 1
    assert aaq["accepted_for_next_frontier_only"] is False
    assert "现在能 invoke 什么" in readback


def test_current_task_source_intake_replays_after_router_advances(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    task_root = tmp_path / "新系统"
    repo.mkdir()
    _write_task_package(task_root)
    _accept(runtime, "p0_006_current_three_text_source_intake", "accepted_for_delivery")
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "status": "current_333_run_index_ready",
            "workflow_id": "workflow-r9",
            "workflow_run_id": "run-r9",
            "temporal": {"running_workflow_count": 1, "mainline_candidate_count": 1},
            "worker_status": {"status": "polling"},
        },
    )
    _write_json(
        runtime / "state" / "task_contract_router" / "latest.json",
        {
            "status": "execution_contract_ready",
            "contract_id": "p0_008_worker_dispatch_real_receipt",
            "workflow_id": "workflow-r9",
            "workflow_run_id": "run-r9",
            "validation": {"passed": True},
        },
    )

    payload = intake.build_current_task_source_intake(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_root,
        write=True,
    )

    source_ledger = json.loads(
        (runtime / "state" / "source_ledger" / "latest.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "current_task_source_intake_ready"
    assert payload["validation"]["checks"]["contract_ready"] is True
    assert payload["task_contract_router"]["contract_id"] == "p0_008_worker_dispatch_real_receipt"
    assert source_ledger["entry_count"] == 3
    assert "current_p0_three_text_20260707" in json.dumps(source_ledger, ensure_ascii=False)
