"""Materialize and replay one fail-closed DomainResearchAdmissionReport."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
if str(XINAO_SRC) not in sys.path:
    sys.path.insert(0, str(XINAO_SRC))

from xinao.admission import (  # noqa: E402
    REQUIRED_SOURCE_IDS,
    build_domain_research_admission_report,
    evidence_ref,
    verify_domain_research_admission_file,
)


def _write_json(path: Path, value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
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


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(UTC)


def run(
    *,
    op_root: Path,
    report_id: str,
    scope: str,
    realm: str,
    source_report_paths: dict[str, Path],
    issued_at: str,
    expires_at: str,
    producer_identity: str,
    verifier_identity: str,
    independence_evidence: Path,
    negative_test_paths: list[Path],
    replay_evidence: Path,
    materialization_receipt: Path | None = None,
) -> dict[str, Any]:
    independence_ref = evidence_ref(independence_evidence)
    report = build_domain_research_admission_report(
        report_id=report_id,
        scope=scope,
        realm=realm,
        source_report_paths=source_report_paths,
        report_model_tool_identities=[producer_identity, verifier_identity],
        independence_attestations=[
            {
                "producer_identity": producer_identity,
                "verifier_identity": verifier_identity,
                "independent": True,
                "evidence_refs": [independence_ref],
            }
        ],
        issued_at=issued_at,
        expires_at=expires_at,
        negative_test_refs=[evidence_ref(path) for path in negative_test_paths],
        replay_ref=evidence_ref(replay_evidence),
        materialization_receipt_ref=(
            evidence_ref(materialization_receipt) if materialization_receipt else None
        ),
    )
    report_path = op_root / "domain_research_admission_report.v1.json"
    report_file_sha256 = _write_json(report_path, report)
    verification = verify_domain_research_admission_file(
        report_path,
        expected_file_sha256=report_file_sha256,
        expected_scope=scope,
        expected_realm=realm,
        as_of=_parse_time(issued_at),
    )
    verification_file_sha256 = _write_json(
        op_root / "domain_research_admission_verification.v1.json", verification
    )
    manifest = {
        "schema_version": "xinao.g6_domain_admission_preflight_manifest.v1",
        "source_report_refs": {
            source_id: evidence_ref(source_report_paths[source_id])
            for source_id in REQUIRED_SOURCE_IDS
        },
        "report_ref": str(report_path),
        "report_file_sha256": report_file_sha256,
        "report_content_hash": report["content_hash"],
        "verification_file_sha256": verification_file_sha256,
        "verification_ok": verification["ok"],
        "formal_autonomous_domain_research_allowed": verification["allowed"],
        "decision": report["decision"],
        "g6_closed": verification["allowed"],
        "g7_closed": False,
        "g8_closed": False,
        "parent_complete": False,
    }
    manifest_file_sha256 = _write_json(op_root / "run_manifest.v1.json", manifest)
    return {
        "decision": report["decision"],
        "verification_ok": verification["ok"],
        "formal_autonomous_domain_research_allowed": verification["allowed"],
        "report_path": str(report_path),
        "report_file_sha256": report_file_sha256,
        "report_content_hash": report["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "failed_predicates": [
            item["predicate"] for item in report["predicate_results"] if not item["passed"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--op-root", type=Path, required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--realm", required=True)
    for source_id in REQUIRED_SOURCE_IDS:
        parser.add_argument(f"--{source_id.lower()}-report", type=Path, required=True)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--producer-identity", required=True)
    parser.add_argument("--verifier-identity", required=True)
    parser.add_argument("--independence-evidence", type=Path, required=True)
    parser.add_argument("--negative-test", type=Path, action="append", required=True)
    parser.add_argument("--replay-evidence", type=Path, required=True)
    parser.add_argument("--materialization-receipt", type=Path)
    args = parser.parse_args()
    sources = {
        source_id: getattr(args, f"{source_id.lower()}_report") for source_id in REQUIRED_SOURCE_IDS
    }
    result = run(
        op_root=_allowed_op_root(args.op_root),
        report_id=args.report_id,
        scope=args.scope,
        realm=args.realm,
        source_report_paths=sources,
        issued_at=args.issued_at,
        expires_at=args.expires_at,
        producer_identity=args.producer_identity,
        verifier_identity=args.verifier_identity,
        independence_evidence=args.independence_evidence,
        negative_test_paths=args.negative_test,
        replay_evidence=args.replay_evidence,
        materialization_receipt=args.materialization_receipt,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
