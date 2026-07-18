"""Package-owned compiler for current F4 contracts and bound evidence.

This is a zero-model compiler, not an adjudicator.  It emits the seven current
research-factory artifacts, the two supporting payloads, source bindings, a
compiler report, and an exact file manifest.  It deliberately emits neither a
PASS verdict nor a ResearchFactoryCanaryReport.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
EVIDENCE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence")
REQUIRED_TYPES = (
    "TypedHandoffSchemaVersion",
    "EvidenceSchemaVersion",
    "ValidationCourtInterfaceVersion",
    "ResearchWorkItemSchemaVersion",
    "DynamicCapacityPolicyVersion",
    "DedupPolicyVersion",
    "DeterministicFanInPolicyVersion",
)
SUPPORTING_TYPES = (
    "OpenMethodRegistrationSchemaVersion",
    "ResearchErrorBudgetPolicySchemaVersion",
)


class BuildError(ValueError):
    """Raised when an input is not current, attributable, or content-bound."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BuildError(message)


def _same_path(left: object, right: object) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"JSON input is not an object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    )
    return path


def file_binding(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    _require(resolved.is_file(), f"bound file is missing: {resolved}")
    return {
        "kind": "file",
        "path": str(resolved),
        "sha256": file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def directory_binding(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    _require(resolved.is_dir(), f"bound directory is missing: {resolved}")
    entries: list[dict[str, Any]] = []
    for item in sorted(
        (candidate for candidate in resolved.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(resolved).as_posix(),
    ):
        entries.append(
            {
                "relative_path": item.relative_to(resolved).as_posix(),
                "sha256": file_sha256(item),
                "size_bytes": item.stat().st_size,
            }
        )
    _require(entries, f"bound directory is empty: {resolved}")
    return {
        "kind": "directory_tree",
        "path": str(resolved),
        "file_count": len(entries),
        "total_size_bytes": sum(int(item["size_bytes"]) for item in entries),
        "tree_sha256": canonical_sha256(entries),
    }


def _validate_content_addressed_verification(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    value = _load_object(resolved)
    content_hash = str(value.get("content_sha256") or "").lower()
    core = dict(value)
    core.pop("content_sha256", None)
    _require(value.get("status") == "VERIFIED", f"verification is not VERIFIED: {resolved}")
    _require(
        len(content_hash) == 64
        and resolved.stem == content_hash
        and canonical_sha256(core) == content_hash,
        f"verification is not content-addressed: {resolved}",
    )
    return value


def discover_latest_verified(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_file():
        _validate_content_addressed_verification(resolved)
        return resolved
    _require(resolved.is_dir(), f"verification path is missing: {resolved}")
    candidates: list[Path] = []
    for candidate in resolved.glob("*.json"):
        try:
            _validate_content_addressed_verification(candidate)
        except BuildError:
            continue
        candidates.append(candidate)
    _require(candidates, f"no VERIFIED content-addressed verification in: {resolved}")
    return max(candidates, key=lambda item: (item.stat().st_mtime_ns, item.name))


def _verification_source_pack(value: Mapping[str, Any]) -> object:
    return value.get("source_pack_ref") or value.get("source_pack")


def _verification_manifest_hash(value: Mapping[str, Any]) -> str:
    return str(
        value.get("source_pack_manifest_sha256") or value.get("source_manifest_sha256") or ""
    ).lower()


def bind_verified_pack(
    *,
    label: str,
    pack: Path,
    manifest_name: str,
    verification: Path,
) -> dict[str, Any]:
    pack = pack.resolve()
    manifest = pack / manifest_name
    _require(pack.is_dir(), f"{label} pack is missing: {pack}")
    _require(manifest.is_file(), f"{label} pack manifest is missing: {manifest}")
    verification = discover_latest_verified(verification)
    verification_value = _validate_content_addressed_verification(verification)
    _require(
        _same_path(_verification_source_pack(verification_value), pack),
        f"{label} verification identifies another source pack",
    )
    _require(
        _verification_manifest_hash(verification_value) == file_sha256(manifest),
        f"{label} verification manifest binding drifted",
    )
    verification_binding = file_binding(verification)
    return {
        "label": label,
        "pack": directory_binding(pack),
        "pack_manifest": file_binding(manifest),
        "independent_verification": {
            **verification_binding,
            "schema_version": verification_value.get("schema_version"),
            "content_sha256": verification_value["content_sha256"],
            "verification_status": "VERIFIED",
        },
    }


def _behavior_summary_observation(path: Path) -> dict[str, Any]:
    value = _load_object(path)
    totals = value.get("totals")
    _require(isinstance(totals, dict), f"behavior summary totals missing: {path}")
    successes = int(totals.get("successes") or 0)
    failures = int(totals.get("failures") or 0)
    errors = int(totals.get("errors") or 0)
    _require(
        int(value.get("exit_code") or 0) == 0
        and not value.get("infrastructure_error")
        and successes > 0
        and failures == 0
        and errors == 0,
        f"behavior summary is not a successful regression: {path}",
    )
    suites = value.get("suites")
    suite_values = suites if isinstance(suites, list) else [suites]
    case_ids = sorted(
        {
            str(case_id)
            for suite in suite_values
            if isinstance(suite, dict)
            for case_id in suite.get("case_ids") or []
        }
    )
    return {
        "run_id": value.get("run_id"),
        "case_pattern": value.get("case_pattern"),
        "case_ids": case_ids,
        "successes": successes,
        "failures": failures,
        "errors": errors,
        "exit_code": 0,
    }


def discover_latest_successful_behavior_summary(root: Path) -> Path:
    resolved = root.resolve()
    _require(resolved.is_dir(), f"behavior regression root is missing: {resolved}")
    candidates: list[Path] = []
    for candidate in resolved.glob("*/summary.json"):
        try:
            _behavior_summary_observation(candidate)
        except BuildError:
            continue
        candidates.append(candidate)
    _require(candidates, f"no successful behavior summary under: {resolved}")
    return max(
        candidates,
        key=lambda item: (item.parent.name, item.stat().st_mtime_ns),
    )


def bind_behavior_summary(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    observed = _behavior_summary_observation(resolved)
    return {"label": "behavior_regression", "summary": file_binding(resolved), "observed": observed}


def compile_current_payloads() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    for path in (REPO_ROOT, XINAO_SRC):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    try:
        from xinao.foundation.research_factory import (
            F4_REQUIRED_ARTIFACT_TYPES,
            research_factory_schema_payloads,
            research_factory_supporting_payloads,
        )
        from xinao.foundation.research_weight import verify_versioned_object
    except ImportError as exc:
        raise BuildError("current research-factory compiler is unavailable") from exc
    required = research_factory_schema_payloads()
    supporting = research_factory_supporting_payloads()
    _require(tuple(F4_REQUIRED_ARTIFACT_TYPES) == REQUIRED_TYPES, "code F4 inventory drifted")
    _require(tuple(required) == REQUIRED_TYPES, "compiled required inventory drifted")
    _require(tuple(supporting) == SUPPORTING_TYPES, "compiled supporting inventory drifted")
    for object_type, value in {**required, **supporting}.items():
        _require(
            value.get("object_type") == object_type and verify_versioned_object(value),
            f"compiled payload is not content-addressed: {object_type}",
        )
    return required, supporting


def _materialize_payloads(
    output: Path,
    category: str,
    payloads: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for object_type, value in payloads.items():
        content_hash = str(value.get("content_sha256") or "")
        _require(len(content_hash) == 64, f"payload content hash missing: {object_type}")
        path = output / category / f"{object_type}.{content_hash}.json"
        _write_json(path, value)
        bindings.append(
            {
                "object_type": object_type,
                "version_id": value.get("version_id"),
                "content_sha256": content_hash,
                "file": file_binding(path),
            }
        )
    return bindings


def _exact_manifest(output: Path) -> dict[str, Any]:
    manifest_path = output / "artifact_manifest.json"
    entries: list[dict[str, Any]] = []
    for path in sorted(
        (
            candidate
            for candidate in output.rglob("*")
            if candidate.is_file() and candidate != manifest_path
        ),
        key=lambda candidate: candidate.relative_to(output).as_posix(),
    ):
        entries.append(
            {
                "relative_path": path.relative_to(output).as_posix(),
                "sha256": file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    core = {
        "schema_version": "xinao.f4_current_evidence_exact_manifest.v1",
        "pack_ref": str(output.resolve()),
        "artifact_count": len(entries),
        "artifacts": entries,
        "artifact_set_sha256": canonical_sha256(entries),
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def build_current_evidence_pack(
    *,
    output: Path,
    live_pack: Path,
    live_verification: Path,
    portfolio_pack: Path,
    portfolio_verification: Path,
    negative_pack: Path,
    negative_verification: Path,
    behavior_summary: Path,
) -> dict[str, Any]:
    output = output.resolve()
    _require(not output.exists(), f"output already exists: {output}")

    source_packs = [
        bind_verified_pack(
            label="live_three_stage_runtime",
            pack=live_pack,
            manifest_name="artifact_manifest.json",
            verification=live_verification,
        ),
        bind_verified_pack(
            label="portfolio_source_and_order",
            pack=portfolio_pack,
            manifest_name="evidence_manifest.json",
            verification=portfolio_verification,
        ),
        bind_verified_pack(
            label="negative_failure_cancel_recovery",
            pack=negative_pack,
            manifest_name="artifact_manifest.json",
            verification=negative_verification,
        ),
    ]
    behavior = bind_behavior_summary(behavior_summary)
    required, supporting = compile_current_payloads()

    output.mkdir(parents=True, exist_ok=False)
    required_bindings = _materialize_payloads(output, "required", required)
    supporting_bindings = _materialize_payloads(output, "supporting", supporting)
    source_core = {
        "schema_version": "xinao.f4_current_evidence_source_bindings.v1",
        "source_packs": source_packs,
        "behavior_regression": behavior,
    }
    source_bindings = {
        **source_core,
        "content_sha256": canonical_sha256(source_core),
    }
    source_bindings_path = _write_json(output / "source_bindings.json", source_bindings)

    compiler_source = (
        REPO_ROOT / "xinao_discovery" / "src" / "xinao" / "foundation" / "research_factory.py"
    )
    report_core = {
        "schema_version": "xinao.f4_current_evidence_compiler_report.v1",
        "compiled_at": datetime.now(UTC).isoformat(),
        "compilation_state": "MATERIALIZED_UNADJUDICATED",
        "pack_ref": str(output),
        "required_artifact_count": len(required_bindings),
        "required_artifacts": required_bindings,
        "supporting_payload_count": len(supporting_bindings),
        "supporting_payloads": supporting_bindings,
        "source_bindings": file_binding(source_bindings_path),
        "compiler_sources": {
            "builder": file_binding(Path(__file__)),
            "research_factory": file_binding(compiler_source),
        },
        "verdict_emitted": False,
        "canary_report_emitted": False,
        "model_invocations": 0,
    }
    report = {**report_core, "content_sha256": canonical_sha256(report_core)}
    report_path = _write_json(output / "compiler_report.json", report)
    manifest = _exact_manifest(output)
    manifest_path = _write_json(output / "artifact_manifest.json", manifest)
    return {
        "pack_ref": str(output),
        "compiler_report_ref": str(report_path),
        "compiler_report_sha256": file_sha256(report_path),
        "compiler_report_content_sha256": report["content_sha256"],
        "artifact_manifest_ref": str(manifest_path),
        "artifact_manifest_sha256": file_sha256(manifest_path),
        "artifact_manifest_content_sha256": manifest["content_sha256"],
        "manifest_artifact_count": manifest["artifact_count"],
        "required_artifact_count": len(required_bindings),
        "supporting_payload_count": len(supporting_bindings),
        "model_invocations": 0,
        "verdict_emitted": False,
    }


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--live-pack", type=Path, required=True)
    parser.add_argument("--live-verification", type=Path, required=True)
    parser.add_argument("--portfolio-pack", type=Path, required=True)
    parser.add_argument("--portfolio-verification", type=Path, required=True)
    parser.add_argument("--negative-pack", type=Path, required=True)
    parser.add_argument("--negative-verification", type=Path, required=True)
    parser.add_argument("--behavior-summary", type=Path, required=True)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    output = args.output_dir or EVIDENCE_ROOT / f"xinao-f4-current-source-{utc_stamp()}"
    result = build_current_evidence_pack(
        output=output,
        live_pack=args.live_pack,
        live_verification=args.live_verification,
        portfolio_pack=args.portfolio_pack,
        portfolio_verification=args.portfolio_verification,
        negative_pack=args.negative_pack,
        negative_verification=args.negative_verification,
        behavior_summary=args.behavior_summary,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
