"""主链读薄胶证据桥 — main tick 落盘 latest，不触发 spawn."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_mainline_spawn import thin_glue_mainline_seam_hint

SCHEMA_VERSION = "xinao.codex_s.thin_glue_mainline_bridge.v1"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def attach_thin_glue_bridge_evidence(runtime_root: Path) -> dict[str, Any]:
    readback_dir = runtime_root / "readback"
    loop_jsons = sorted(readback_dir.glob("thin_glue_loop_*.json"), reverse=True)
    spawn_jsons = sorted(readback_dir.glob("thin_glue_mainline_spawn_*.json"), reverse=True)
    latest_loop = loop_jsons[0] if loop_jsons else None
    latest_spawn = spawn_jsons[0] if spawn_jsons else None
    loop_passed = False
    if latest_loop and latest_loop.is_file():
        try:
            loop_passed = (
                json.loads(latest_loop.read_text(encoding="utf-8"))
                .get("validation", {})
                .get("passed")
                is True
            )
        except json.JSONDecodeError:
            loop_passed = False
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "thin_glue_mainline_seam": thin_glue_mainline_seam_hint(loop_passed=loop_passed),
        "latest_thin_glue_loop_readback": str(latest_loop) if latest_loop else None,
        "latest_thin_glue_spawn_readback": str(latest_spawn) if latest_spawn else None,
        "latest_thin_glue_loop_passed": loop_passed,
        "handroll_intact": False,
        "integrated_bus_default": True,
        "not_333_mainline": False,
        "invoke_default": "xinao-seedlab thin-glue --temporal",
    }
    try:
        from services.agent_runtime.thin_glue_status import build_thin_glue_status

        status = build_thin_glue_status(runtime_root=runtime_root, write=True)
        payload["thin_glue_status"] = {
            "passed": status.get("validation", {}).get("passed"),
            "green_layers": status.get("summary", {}).get("green"),
            "latest": str(runtime_root / "state" / "thin_glue_status" / "latest.json"),
        }
    except Exception:
        payload["thin_glue_status"] = {"skipped": True}
    out = runtime_root / "state" / "thin_glue_mainline_bridge" / "latest.json"
    _write_json(out, payload)
    payload["bridge_latest_path"] = str(out)
    return payload
