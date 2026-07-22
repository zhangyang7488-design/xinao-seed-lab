"""Case materializer: public cases only from SubjectPublicManifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import SYNTHETIC_LABEL
from .canonical import write_json
from .security_model import scan_forbidden_public_payload


def materialize_public_cases(
    *,
    manifest: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cases_path = out / "cases.jsonl"
    meta_path = out / "materialization_meta.v1.json"
    written = 0
    with cases_path.open("w", encoding="utf-8", newline="\n") as fh:
        for case in manifest.get("public_cases", []):
            row = {
                "public_case_id": case["public_case_id"],
                "public_prompt": case["public_prompt"],
                "commitment_sha256": case["commitment_sha256"],
                "schedule_slot": case.get("schedule_slot"),
                "vars": {
                    "public_case_id": case["public_case_id"],
                    "public_prompt": case["public_prompt"],
                    "commitment_sha256": case["commitment_sha256"],
                },
                "synthetic": True,
                "label": SYNTHETIC_LABEL,
                "not_admission": True,
                "not_discovery": True,
                "not_rejection_evidence": True,
            }
            leaks = scan_forbidden_public_payload(row)
            if leaks:
                return {
                    "ok": False,
                    "reason": "forbidden_keys_in_materialized_case",
                    "leaks": leaks,
                }
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            fh.write("\n")
            written += 1
    meta = {
        "schema_version": "xinao.g4.hidden_capability_seam.materialization.v1",
        "cases_path": str(cases_path),
        "case_count": written,
        "manifest_identity_sha256": manifest.get("manifest_identity_sha256"),
        "scoring_enabled": False,
        "hidden_cases_consumed": False,
        "synthetic_only": True,
        "label": SYNTHETIC_LABEL,
        "authority": False,
    }
    write_json(meta_path, meta)
    return {"ok": True, "meta": meta, "cases_path": str(cases_path)}
