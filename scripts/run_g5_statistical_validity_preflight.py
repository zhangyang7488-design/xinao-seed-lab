"""Consume current G4/G5 evidence and emit one fail-closed G5 adjudication."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
if str(XINAO_SRC) not in sys.path:
    sys.path.insert(0, str(XINAO_SRC))

from xinao.capability.g5_statistical_validity import (  # noqa: E402
    adjudicate_g5,
    run_public_null_smoke,
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return value


def _raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> str:
    text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _allowed_op_root(path: Path) -> Path:
    resolved = path.resolve()
    runtime = Path(r"D:\XINAO_RESEARCH_RUNTIME").resolve()
    try:
        resolved.relative_to(runtime)
    except ValueError as exc:
        raise SystemExit("op root must remain under D:\\XINAO_RESEARCH_RUNTIME") from exc
    if resolved.exists() and any(resolved.iterdir()):
        raise SystemExit("op root must be new or empty")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _reference_public_pipeline(_case: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "NO_ACTION",
        "claimed_discovery": False,
        "promoted": False,
        "reason": "public_pure_noise_reference_rejection",
    }


def run(
    *,
    g4_report_path: Path,
    op_root: Path,
    candidate_bundle_path: Path | None = None,
) -> dict[str, Any]:
    g4_report = _read_json(g4_report_path)
    bundle = _read_json(candidate_bundle_path) if candidate_bundle_path else {}
    public_smoke = run_public_null_smoke(_reference_public_pipeline)
    supplied_null = bundle.get("full_pipeline_null_report", public_smoke)
    report = adjudicate_g5(
        g4_report=g4_report,
        power_plan=bundle.get("power_plan"),
        ess_report=bundle.get("ess_report"),
        power_evidence=bundle.get("power_evidence"),
        trial_ledger_disclosure=bundle.get("trial_ledger_disclosure"),
        family_definition=bundle.get("family_definition"),
        error_control_receipt=bundle.get("error_control_receipt"),
        holdout_snapshot=bundle.get("holdout_snapshot"),
        full_pipeline_null_report=supplied_null,
        operational_replication_report=bundle.get("operational_replication_report"),
        statistical_independence_evidence=bundle.get("statistical_independence_evidence"),
    )
    g4_copy_sha = _write_json(op_root / "inputs" / "g4_report.json", g4_report)
    smoke_sha = _write_json(op_root / "public_null_smoke.v1.json", public_smoke)
    if candidate_bundle_path:
        _write_json(op_root / "inputs" / "candidate_bundle.json", bundle)
    report_sha = _write_json(op_root / "g5_adjudication.v1.json", report)
    manifest: dict[str, Any] = {
        "schema_version": "xinao.g5.preflight_run_manifest.v1",
        "g4_source_path": str(g4_report_path.resolve()),
        "g4_source_raw_sha256": _raw_sha256(g4_report_path),
        "g4_semantic_copy_file_sha256": g4_copy_sha,
        "candidate_bundle_source_path": (
            str(candidate_bundle_path.resolve()) if candidate_bundle_path else None
        ),
        "candidate_bundle_source_raw_sha256": (
            _raw_sha256(candidate_bundle_path) if candidate_bundle_path else None
        ),
        "public_null_smoke_file_sha256": smoke_sha,
        "g5_adjudication_file_sha256": report_sha,
        "terminal": report["terminal"],
        "g5_closed": report["g5_closed"],
        "authority": False,
        "completion_claim_allowed": False,
    }
    manifest_sha = _write_json(op_root / "run_manifest.v1.json", manifest)
    return {
        "terminal": report["terminal"],
        "g5_closed": report["g5_closed"],
        "report_path": str(op_root / "g5_adjudication.v1.json"),
        "report_file_sha256": report_sha,
        "manifest_file_sha256": manifest_sha,
        "reason_count": len(report["reasons"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--g4-report", type=Path, required=True)
    parser.add_argument("--op-root", type=Path, required=True)
    parser.add_argument("--candidate-bundle", type=Path)
    args = parser.parse_args()
    op_root = _allowed_op_root(args.op_root)
    result = run(
        g4_report_path=args.g4_report,
        op_root=op_root,
        candidate_bundle_path=args.candidate_bundle,
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
