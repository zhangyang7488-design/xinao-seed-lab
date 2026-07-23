"""Materialize and replay one fail-closed OperationalAssuranceReport."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
if str(XINAO_SRC) not in sys.path:
    sys.path.insert(0, str(XINAO_SRC))

from xinao.assurance import (  # noqa: E402
    REQUIRED_DIMENSIONS,
    build_operational_assurance_report,
    evidence_ref,
    verify_operational_assurance_file,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _write_json(path: Path, value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _allowed_op_root(path: Path, runtime_root: Path) -> Path:
    resolved = path.resolve()
    runtime = runtime_root.resolve()
    try:
        resolved.relative_to(runtime)
    except ValueError as exc:
        raise SystemExit(f"op root must remain under runtime root: {runtime}") from exc
    if resolved.exists() and any(resolved.iterdir()):
        raise SystemExit("op root must be new or empty")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _key_value(values: list[str], *, label: str, sha256_value: bool) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        key, separator, value = raw.partition("=")
        if not separator or not key or not value or key in result:
            raise SystemExit(f"{label} must use unique KEY=VALUE entries")
        normalized = value.lower() if sha256_value else value
        if sha256_value and _SHA256_RE.fullmatch(normalized) is None:
            raise SystemExit(f"{label} values must be lowercase sha256")
        result[key] = normalized
    if not result:
        raise SystemExit(f"{label} requires at least one KEY=VALUE entry")
    return result


def _dimension_paths(values: list[str]) -> dict[str, Path]:
    raw = _key_value(values, label="dimension evidence", sha256_value=False) if values else {}
    unknown = set(raw) - set(REQUIRED_DIMENSIONS)
    if unknown:
        raise SystemExit(f"unknown dimensions: {sorted(unknown)}")
    return {dimension: Path(path) for dimension, path in raw.items()}


def run(
    *,
    op_root: Path,
    report_id: str,
    scope: str,
    realm: str,
    source_commit: str,
    input_hashes: dict[str, str],
    artifact_hashes: dict[str, str],
    dimension_evidence_paths: dict[str, Path],
    producer_identity: str,
    verifier_identity: str,
    independence_evidence: Path,
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    report = build_operational_assurance_report(
        report_id=report_id,
        scope=scope,
        realm=realm,
        source_commit=source_commit,
        input_hashes=input_hashes,
        artifact_hashes=artifact_hashes,
        dimension_evidence_paths=dimension_evidence_paths,
        producer_identity=producer_identity,
        verifier_identity=verifier_identity,
        independence_evidence_ref=evidence_ref(independence_evidence),
        issued_at=issued_at,
        expires_at=expires_at,
    )
    report_path = op_root / "operational_assurance_report.v1.json"
    report_file_sha256 = _write_json(report_path, report)
    verification = verify_operational_assurance_file(
        report_path,
        expected_file_sha256=report_file_sha256,
        expected_scope=scope,
        expected_realm=realm,
        expected_source_commit=source_commit,
        as_of=datetime.now(UTC),
    )
    verification_path = op_root / "operational_assurance_verification.v1.json"
    verification_file_sha256 = _write_json(verification_path, verification)
    missing_or_unready = [
        dimension
        for dimension, source in report["dimension_sources"].items()
        if source["ready"] is not True
    ]
    manifest = {
        "schema_version": "xinao.g8_operational_assurance_preflight_manifest.v1",
        "source_commit": source_commit.lower(),
        "dimension_evidence_refs": {
            dimension: evidence_ref(path)
            for dimension, path in dimension_evidence_paths.items()
            if path.is_file()
        },
        "report_ref": str(report_path),
        "report_file_sha256": report_file_sha256,
        "report_content_hash": report["content_hash"],
        "verification_ref": str(verification_path),
        "verification_file_sha256": verification_file_sha256,
        "verification_ok": verification["ok"],
        "decision": verification["decision"],
        "g8_closed": verification["ready"],
        "missing_or_unready_dimensions": missing_or_unready,
        "live_shadow_claim_allowed": False,
        "parent_complete": False,
    }
    manifest_file_sha256 = _write_json(op_root / "run_manifest.v1.json", manifest)
    return {
        "decision": verification["decision"],
        "verification_ok": verification["ok"],
        "g8_closed": verification["ready"],
        "missing_or_unready_dimensions": missing_or_unready,
        "live_shadow_claim_allowed": False,
        "parent_complete": False,
        "report_path": str(report_path),
        "report_file_sha256": report_file_sha256,
        "report_content_hash": report["content_hash"],
        "verification_path": str(verification_path),
        "manifest_file_sha256": manifest_file_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--op-root", type=Path, required=True)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path(r"D:\XINAO_RESEARCH_RUNTIME"),
    )
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--realm", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--input-hash", action="append", default=[])
    parser.add_argument("--artifact-hash", action="append", default=[])
    parser.add_argument("--dimension-evidence", action="append", default=[])
    parser.add_argument("--producer-identity", required=True)
    parser.add_argument("--verifier-identity", required=True)
    parser.add_argument("--independence-evidence", type=Path, required=True)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.source_commit.lower()) is None:
        raise SystemExit("source commit must be a lowercase 40-character Git commit")
    result = run(
        op_root=_allowed_op_root(args.op_root, args.runtime_root),
        report_id=args.report_id,
        scope=args.scope,
        realm=args.realm,
        source_commit=args.source_commit.lower(),
        input_hashes=_key_value(args.input_hash, label="input hash", sha256_value=True),
        artifact_hashes=_key_value(args.artifact_hash, label="artifact hash", sha256_value=True),
        dimension_evidence_paths=_dimension_paths(args.dimension_evidence),
        producer_identity=args.producer_identity,
        verifier_identity=args.verifier_identity,
        independence_evidence=args.independence_evidence,
        issued_at=args.issued_at,
        expires_at=args.expires_at,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if args.require_ready and result["g8_closed"] is not True else 0


if __name__ == "__main__":
    raise SystemExit(main())
