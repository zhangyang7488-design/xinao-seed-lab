from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.sunset_deprecation.v1"
SENTINEL = "SENTINEL:XINAO_SUNSET_DEPRECATION_V1"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_sunset_payload(
    *,
    module_name: str,
    replacement_cn: str,
    replacement_command: str,
    overnight_evidence: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "sunset_deprecated",
        "module_name": module_name,
        "not_333_mainline": False,
        "completion_claim_allowed": False,
        "named_blocker": "MODULE_SUNSET_USE_THIN_GLUE_PATH",
        "replacement_cn": replacement_cn,
        "replacement_command": replacement_command,
        "overnight_evidence_ref": overnight_evidence,
        "generated_at": _now_iso(),
        "validation": {"passed": False, "reason": "sunset_module_no_longer_default"},
    }


def write_sunset_log(runtime_root: Path, module_name: str, payload: dict[str, Any]) -> Path:
    out = runtime_root / "sunset" / f"{module_name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out