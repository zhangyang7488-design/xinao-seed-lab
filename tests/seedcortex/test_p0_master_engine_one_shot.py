from __future__ import annotations

import json
from pathlib import Path

from services.agent_runtime import p0_master_engine_one_shot as engine


def test_acceptance_v2_nonempty() -> None:
    text = engine.build_acceptance_now_can_invoke_cn_v2(
        ledger_succeeded=4,
        wave3_ready=True,
        wave4={"p0_034_root_driver_artifact_acceptance_bridge_ready": True},
        wave5={"p0_037_qwen_cheap_worker_default_lane_ready": True},
        drain={"queue_empty": True},
        workflow={"workflow_id": "wf-test"},
    )
    assert "4 路真 succeeded" in text
    assert "QUEUE_EMPTY" in text


def test_weld_wave4_bridge_on_fixture(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    wave_id = "wf-master"
    entries = [
        {
            "entry_id": f"{wave_id}:01",
            "wave_id": wave_id,
            "lane_id": "temporal-codex-worker-turn-a",
            "poll_status": "succeeded",
            "mode": "worker",
        }
    ]
    (tmp_path / "state" / "worker_dispatch_ledger").mkdir(parents=True)
    (tmp_path / "state" / "worker_dispatch_ledger" / "latest.json").write_text(
        json.dumps({"wave_id": wave_id, "succeeded_count": 1, "dispatch_entries": entries}),
        encoding="utf-8",
    )
    (tmp_path / "state" / "root_intent_loop_driver").mkdir(parents=True)
    (tmp_path / "state" / "root_intent_loop_driver" / "latest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "state" / "default_main_loop_trigger_candidate").mkdir(parents=True)
    (tmp_path / "state" / "default_main_loop_trigger_candidate" / "latest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "state" / "langgraph_task_runner").mkdir(parents=True)
    (tmp_path / "state" / "langgraph_task_runner" / "latest.json").write_text("{}", encoding="utf-8")

    result = engine.weld_wave4(tmp_path, repo, {"workflow_id": wave_id, "workflow_run_id": "run-1"})
    assert result["p0_034_root_driver_artifact_acceptance_bridge_ready"] is True