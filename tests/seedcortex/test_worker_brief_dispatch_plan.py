from __future__ import annotations

import asyncio
import json
from pathlib import Path

from services.agent_runtime import temporal_codex_task_workflow


def test_worker_brief_dispatch_plan_builds_three_real_receipt_payloads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(temporal_codex_task_workflow, "SEED_CORTEX_RUNTIME_ROOT", runtime)
    source_dir = runtime / "sources"
    source_dir.mkdir(parents=True)
    sources = []
    for index, role in enumerate(
        ("project_boundary", "p0_execution_entrypoint", "p1_gate_context"),
        start=1,
    ):
        path = source_dir / f"{index:02d}_{role}.txt"
        path.write_text(f"{role}\ncurrent delivery intent\n", encoding="utf-8")
        sources.append((role, path))
    briefs = [
        {
            "worker_brief_id": f"current-p0-three-text:brief:{index:02d}",
            "source_package_id": "current_p0_three_text_20260707",
            "source_ledger_entry_id": f"source-entry-{index:02d}",
            "source_ref": str(path),
            "source_sha256": f"sha-{index:02d}",
            "source_role": role,
            "provider_candidates": ["qwen_prepaid_cheap_worker", "deepseek_dp"],
            "provider_route_key": "draft_extraction_classify_eval",
            "objective": f"bind {role}",
        }
        for index, (role, path) in enumerate(sources, start=1)
    ]
    queue_path = runtime / "state" / "worker_brief_queue" / "latest.json"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.worker_brief_queue.v1",
                "status": "worker_brief_queue_ready",
                "queue_id": "current-p0-three-text-worker-brief-queue",
                "source_package_id": "current_p0_three_text_20260707",
                "brief_count": 3,
                "dispatch_ready": True,
                "next_frontier_default_outlet": False,
                "briefs": briefs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    payload = {
        "runtime_root": str(runtime),
        "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
        "route_profile": temporal_codex_task_workflow.SEED_CORTEX_ROUTE_PROFILE,
        "workflow_id": "codex-s-333-mainline-p0-r9",
        "workflow_run_id": "run-r9",
        "phase_scope": "p0_008_worker_dispatch_real_receipt",
        "worker_brief_dispatch_limit": 3,
        "require_dp_receipt": True,
        "worker_dispatch_real_receipt_required": True,
        "worker_brief_real_receipt_required": True,
    }

    result = asyncio.run(temporal_codex_task_workflow.worker_brief_dispatch_plan_activity(payload))

    assert result["status"] == "worker_brief_dispatch_plan_ready"
    assert result["validation"]["passed"] is True
    assert result["planned_worker_count"] == 3
    assert result["dp_lane_assigned"] is True
    worker_payloads = result["worker_turn_payloads"]
    assert len(worker_payloads) == 3
    assert worker_payloads[0]["provider_route_key"] == "architecture_receipt_audit"
    assert {item["worker_brief_id"] for item in worker_payloads} == {
        brief["worker_brief_id"] for brief in briefs
    }
    assert all(item["execute_worker_turn"] is True for item in worker_payloads)
    assert all(item["execute_codex_worker"] is False for item in worker_payloads)
    assert all(item["worker_dispatch_real_receipt_required"] is True for item in worker_payloads)
    assert all(item["worker_brief_real_receipt_required"] is True for item in worker_payloads)
    assert all(
        temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER in item["codex_worker_prompt"]
        for item in worker_payloads
    )
    assert Path(result["output_paths"]["latest"]).is_file()
