from __future__ import annotations

import json
from pathlib import Path

from services.agent_runtime import p0_wave3_true_invoke_full_loop as wave3
from services.agent_runtime import root_intent_loop_driver as rid


def _write_ledger(tmp_path: Path, *, wave_id: str, succeeded_lanes: list[str]) -> None:
    entries = []
    for index, lane_id in enumerate(succeeded_lanes, start=1):
        entries.append(
            {
                "entry_id": f"{wave_id}:lane-{index:02d}",
                "wave_id": wave_id,
                "lane_id": lane_id,
                "poll_status": "succeeded",
                "artifact_refs": ["artifact.json"],
                "mode": "worker",
            }
        )
    payload = {
        "wave_id": wave_id,
        "succeeded_count": len(succeeded_lanes),
        "dispatch_entries": entries,
    }
    ledger_dir = tmp_path / "state" / "worker_dispatch_ledger"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_bridge_temporal_ledger_fanin_aligns_driver(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    wave_id = "codex-s-wave-02-bind"
    _write_ledger(
        tmp_path,
        wave_id=wave_id,
        succeeded_lanes=[
            "temporal-codex-worker-turn-p0_008-01",
            "temporal-codex-worker-turn-p0_008-02",
            "local-worker-dispatch-ledger-writer",
        ],
    )
    driver_dir = tmp_path / "state" / "root_intent_loop_driver"
    driver_dir.mkdir(parents=True)
    (driver_dir / "latest.json").write_text(
        json.dumps({"fan_in_acceptance": {"ledger_succeeded_count": 0}}, ensure_ascii=False),
        encoding="utf-8",
    )

    bridge = rid.bridge_temporal_worker_dispatch_ledger_fanin(
        runtime_root=tmp_path,
        repo_root=repo,
        wave_id="different-wave",
        write=True,
    )
    assert bridge["validation"]["passed"] is True
    assert bridge["ledger_succeeded_count"] == 3
    driver = json.loads((driver_dir / "latest.json").read_text(encoding="utf-8"))
    assert driver["fan_in_acceptance"]["ledger_succeeded_count"] == 3
    assert driver["fan_in_acceptance"]["consumed_ledger_poll_results"] is True


def test_p0_026_detects_alignment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    wave_id = "wf-wave3"
    _write_ledger(
        tmp_path,
        wave_id=wave_id,
        succeeded_lanes=[
            "temporal-codex-worker-turn-p0_008-01",
            "temporal-codex-worker-turn-p0_008-02",
            "local-worker-dispatch-ledger-writer",
        ],
    )
    driver_dir = tmp_path / "state" / "root_intent_loop_driver"
    driver_dir.mkdir(parents=True)
    (driver_dir / "latest.json").write_text(
        json.dumps({"fan_in_acceptance": {"ledger_succeeded_count": 0}}, ensure_ascii=False),
        encoding="utf-8",
    )
    rid.bridge_temporal_worker_dispatch_ledger_fanin(
        runtime_root=tmp_path,
        repo_root=repo,
        wave_id=wave_id,
        write=True,
    )
    result = wave3.run_p0_026_ledger_fanin_bridge(tmp_path, repo, {"workflow_id": wave_id})
    assert result["root_driver_ledger_poll_fanin_ready"] is True
    assert result["ledger_succeeded_count"] == 3


def test_acceptance_now_can_invoke_cn_nonempty() -> None:
    text = wave3.build_acceptance_now_can_invoke_cn(
        ledger_succeeded=3,
        fanin_aligned=True,
        litellm_ready=True,
        dp_pool_enforced=True,
        temporal_tick_ready=True,
        workflow={"workflow_id": "codex-s-test"},
    )
    assert "3 路真 succeeded" in text
    assert "litellm" in text
    assert "codex-s-test" in text
