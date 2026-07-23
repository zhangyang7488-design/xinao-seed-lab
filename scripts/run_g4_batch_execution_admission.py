"""Validate one G4 batch against a common worker-bus attempt receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
for path in (REPO_ROOT, XINAO_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.agent_runtime.g4_batch_execution import (  # noqa: E402
    adjudicate_g4_batch_execution,
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: Any) -> str:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _operation_root(path: Path) -> Path:
    resolved = path.resolve()
    runtime = Path(
        os.environ.get("XINAO_RESEARCH_RUNTIME_ROOT", r"D:\XINAO_RESEARCH_RUNTIME")
    ).resolve()
    try:
        resolved.relative_to(runtime)
    except ValueError as exc:
        raise SystemExit("op root must remain under D:\\XINAO_RESEARCH_RUNTIME") from exc
    if resolved.exists() and any(resolved.iterdir()):
        raise SystemExit("op root must be new or empty")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-manifest", type=Path, required=True)
    parser.add_argument("--logical-contract", type=Path, required=True)
    parser.add_argument("--attempt-receipt", type=Path, required=True)
    parser.add_argument("--op-root", type=Path, required=True)
    args = parser.parse_args()
    report = adjudicate_g4_batch_execution(
        batch_manifest=_read_json(args.batch_manifest),
        logical_contract=_read_json(args.logical_contract),
        attempt_receipt=_read_json(args.attempt_receipt),
    )
    op_root = _operation_root(args.op_root)
    report_path = op_root / "g4_batch_execution_admission.v1.json"
    report_file_sha256 = _write_json(report_path, report)
    result = {
        "terminal": report["terminal"],
        "batch_execution_accepted": report["batch_execution_accepted"],
        "provider_binding_scope": report["provider_binding_scope"],
        "campaign_provider_locked": report["campaign_provider_locked"],
        "full_campaign_capacity_precommit_required": report[
            "full_campaign_capacity_precommit_required"
        ],
        "human_status_cn": report["human_status_cn"],
        "report_path": str(report_path),
        "report_file_sha256": report_file_sha256,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if report["batch_execution_accepted"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
