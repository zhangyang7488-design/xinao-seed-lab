"""Admin night-run checkpoint rollup (evidence index only; no product close)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\admin_night_checkpoint_20260712.json")


def main() -> int:
    pytest = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    evidence = {
        "T9_temporal_promoted_canary_latest.json": Path(
            r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\T9_temporal_promoted_canary_latest.json"
        ).exists(),
        "S5_temporal_adapter_landed_latest.json": Path(
            r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\S5_temporal_adapter_landed_latest.json"
        ).exists(),
        "T1T2T5_e2e_canary.json": Path(
            r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\T1T2T5_e2e_canary.json"
        ).exists(),
        "T6T7T8_e2e_canary.json": Path(
            r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\T6T7T8_e2e_canary.json"
        ).exists(),
        "l0_snapshot/manifest.json": Path(
            r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\l0_snapshot\manifest.json"
        ).exists(),
        "l0_hypothesis_register_latest.json": Path(
            r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\l0_hypothesis_register_latest.json"
        ).exists(),
        "codex_L0_backtest_numbers.json": Path(
            r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\codex_L0_backtest_numbers.json"
        ).exists(),
        "prod_amq_missing": not Path(
            r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq"
        ).exists(),
    }
    payload = {
        "schema_version": "xinao.kaigong_wave.admin_night_checkpoint.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "executor": "composer_admin_night_run",
        "task_id": "task_a515b3522f464522a085dc7f98be9ac1",
        "completion_claim_allowed": False,
        "pytest": {
            "exit_code": pytest.returncode,
            "stdout_tail": pytest.stdout.strip()[-500:],
        },
        "evidence_exists": evidence,
        "ready_frontier": [
            "S1_W2_prod_amq_init (user gate)",
            "S3_dual_source_runtime_refresh",
            "S7_E4_full_walkforward_M2_M4",
            "S5_live_temporal_worker_registration (XINAO_TEMPORAL_LIVE=1)",
            "overnight_S0S8_progress_index_refresh",
            "phase_lock_PAUSED_ALL_clear (Codex)",
        ],
        "repo": str(REPO),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(OUT)}, ensure_ascii=False))
    return 0 if pytest.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())