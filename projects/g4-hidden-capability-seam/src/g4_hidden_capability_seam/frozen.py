"""Frozen input verification (pre/post)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .canonical import raw_bytes_sha256_file, write_json

FROZEN_CONTEXT_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\codex_task_runs\composer25-mainline-continuous-20260717\evidence\g4_hidden_capability_seam_v1_event422\dispatch_inputs\frozen_context.v1.json"
)
SUBJECT_MANIFEST_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\codex_task_runs\composer25-mainline-continuous-20260717\evidence\g4_hidden_capability_seam_v1_event422\dispatch_inputs\subject_manifest.v1.json"
)


def verify_frozen_context() -> dict[str, Any]:
    ctx = json.loads(FROZEN_CONTEXT_PATH.read_text(encoding="utf-8"))
    results = []
    bad = 0
    for inp in ctx.get("inputs", []):
        path = inp["path"]
        expected_sha = inp["sha256"]
        expected_bytes = inp["bytes"]
        p = Path(path)
        if not p.exists():
            results.append(
                {
                    "role": inp["role"],
                    "status": "MISSING",
                    "path": path,
                    "expected_sha256": expected_sha,
                }
            )
            bad += 1
            continue
        actual_sha, actual_bytes = raw_bytes_sha256_file(p)
        ok = actual_sha == expected_sha and actual_bytes == expected_bytes
        if not ok:
            bad += 1
        results.append(
            {
                "role": inp["role"],
                "status": "OK" if ok else "MISMATCH",
                "path": path,
                "expected_sha256": expected_sha,
                "actual_sha256": actual_sha,
                "expected_bytes": expected_bytes,
                "actual_bytes": actual_bytes,
            }
        )
    return {
        "schema_version": "xinao.g4.hidden_capability_seam.frozen_verify.v1",
        "ok": bad == 0,
        "bad_count": bad,
        "total": len(results),
        "results": results,
        "frozen_context_path": str(FROZEN_CONTEXT_PATH),
        "authority": False,
    }


def write_frozen_receipt(path: str | Path, phase: str) -> dict[str, Any]:
    receipt = verify_frozen_context()
    receipt["phase"] = phase
    write_json(path, receipt)
    return receipt
