"""S5/T9: record thin adapter implementation landed (mock canary; no live recreate)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\S5_temporal_adapter_landed_latest.json")
T9 = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\T9_temporal_promoted_canary_latest.json")


def main() -> int:
    t9 = json.loads(T9.read_text(encoding="utf-8")) if T9.exists() else {}
    payload = {
        "schema_version": "xinao.kaigong_wave.S5_temporal_adapter_landed.v1",
        "phase": "S5",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "executor": "composer_admin_night_run",
        "implementation_landed": True,
        "design_only": False,
        "adapter_exists": (REPO / "adapters" / "temporal").exists(),
        "package_exists": (REPO / "src" / "xinao_coordination" / "temporal").exists(),
        "config_exists": (REPO / "configs" / "modules" / "temporal.toml").exists(),
        "live_workflow_start_attempted": False,
        "live_temporal_recreate": False,
        "completion_claim_allowed": False,
        "product_closed": False,
        "t9_canary_ref": str(T9),
        "t9_verdict": t9.get("verdict"),
        "surfaces": [
            "service.temporal_status",
            "service.temporal_start_promoted",
            "cli temporal-status",
            "cli temporal-start-promoted",
            "mcp temporal_status",
            "mcp temporal_start_promoted",
        ],
        "tests_added": "tests/test_t9_temporal_promoted_adapter.py",
        "repo": str(REPO),
        "verdict": "PASS_SCOPED_IMPLEMENTATION" if t9.get("verdict") == "PASS_SCOPED_CANARY" else "PARTIAL",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(OUT), "verdict": payload["verdict"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
