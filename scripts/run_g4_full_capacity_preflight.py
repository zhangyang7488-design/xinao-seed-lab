"""Measure a public-only G4 subject route and adjudicate full-campaign capacity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
if str(XINAO_SRC) not in sys.path:
    sys.path.insert(0, str(XINAO_SRC))

from xinao.canonical import canonical_sha256  # noqa: E402
from xinao.capability.g4_capacity import (  # noqa: E402
    adjudicate_capacity,
    build_subject_prompt,
    normalize_relay_measurement,
    raw_text_sha256,
    select_size_stratified_cases,
)
from xinao.capability.g4_hidden_benchmark import (  # noqa: E402
    GeneratorProfile,
    generate_split_suite,
)
from xinao.capability.g4_hidden_benchmark.artifact import (  # noqa: E402
    build_generator_artifact,
)
from xinao.capability.g4_hidden_benchmark.constants import SPLIT_TRAINING  # noqa: E402

DEFAULT_LAUNCHER = Path(r"C:\Users\xx363\CodexLaunchers\Invoke-Codex-OpenAiRelayWorker.ps1")
DEFAULT_QUOTA_QUERY = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\quota_query\Get-AIQuota.ps1")
DEFAULT_RELAY_EVIDENCE = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\openai_relay_worker")
REQUIRED_CAMPAIGN_CELLS = 10_206


def _write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _public_training_cases() -> tuple[Any, Any, Any, list[dict[str, Any]]]:
    artifact = build_generator_artifact()
    manifest, _training_private_bundle, identity = generate_split_suite(
        secret=secrets.token_bytes(32),
        split=SPLIT_TRAINING,
        profile=GeneratorProfile(cases_per_family=1),
        generator_artifact_sha256=artifact.artifact_sha256,
    )
    cases = [case.as_public_dict() for case in manifest.cases]
    return artifact, manifest, identity, cases


def prepare(op_root: Path, *, model: str, max_tokens: int, timeout_sec: int) -> dict[str, Any]:
    artifact, manifest, identity, cases = _public_training_cases()
    selected = select_size_stratified_cases(cases)
    prompts: list[dict[str, Any]] = []
    for index, selection in enumerate(selected, start=1):
        prompt = build_subject_prompt(selection["case"], subject_configuration="C2-FRONTIER")
        prompt_path = op_root / "public_prompts" / f"{index:02d}_{selection['stratum']}.json"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        # No trailing newline: the file bytes and actual launcher prompt text have one identity.
        prompt_path.write_text(prompt, encoding="utf-8", newline="\n")
        prompts.append(
            {
                "index": index,
                "stratum": selection["stratum"],
                "public_case_id": selection["case"]["public_case_id"],
                "public_bytes": selection["public_bytes"],
                "prompt_path": str(prompt_path),
                "prompt_sha256": raw_text_sha256(prompt),
            }
        )
    plan: dict[str, Any] = {
        "schema_version": "xinao.g4.capacity_calibration_plan.v1",
        "calibration_class": "B_non_heldout_public_synthetic_workload_shape_telemetry",
        "subject_configuration": "C2-FRONTIER",
        "selected_model": model,
        "max_tokens_per_call": max_tokens,
        "timeout_sec_per_call": timeout_sec,
        "sample_strategy": "deterministic_low_median_high_public_payload_bytes",
        "sample_count": len(prompts),
        "prompts": prompts,
        "training_identity_sha256": identity.identity_sha256,
        "training_public_manifest_sha256": manifest.public_manifest_sha256,
        "generator_artifact_sha256": artifact.artifact_sha256,
        "training_private_bundle_persisted": False,
        "subject_received_training_private_material": False,
        "heldout_identity_persisted": False,
        "heldout_case_materialized": False,
        "heldout_outcome_access": False,
        "hidden_outcome_access": False,
        "scoring_executed": False,
        "authority": False,
        "completion_claim_allowed": False,
    }
    plan["content_hash"] = canonical_sha256(plan)
    _write_json(op_root / "calibration_plan.v1.json", plan)
    return plan


def _invoke_relay(
    *,
    launcher: Path,
    prompt: dict[str, Any],
    model: str,
    max_tokens: int,
    timeout_sec: int,
    operation_id: str,
) -> tuple[int, Path]:
    dispatch_id = f"g4cap_{operation_id}_{prompt['index']:02d}"
    summary = DEFAULT_RELAY_EVIDENCE / f"dispatch_{dispatch_id}" / "dispatch_summary.json"
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(launcher),
        "-WorkKey",
        "wk:FOUNDATION:g4-capability-full-family-closed-report:capacity-calibration",
        "-LogicalOperationId",
        operation_id,
        "-PromptFile",
        str(prompt["prompt_path"]),
        "-Model",
        model,
        "-MaxTokens",
        str(max_tokens),
        "-TimeoutSec",
        str(timeout_sec),
        "-MinResultChars",
        "2",
        "-DispatchId",
        dispatch_id,
        "-Quiet",
    ]
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec + 60,
        check=False,
        shell=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TEMP": os.environ.get("TEMP", ""),
            "TMP": os.environ.get("TMP", ""),
        },
    )
    return process.returncode, summary


def _measurement_from_summary(prompt: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    if not summary_path.is_file():
        return {
            "ok": False,
            "stratum": prompt["stratum"],
            "prompt_bytes": prompt["public_bytes"],
            "prompt_sha256": prompt["prompt_sha256"],
            "problems": ["dispatch_summary_missing"],
        }
    dispatch = json.loads(summary_path.read_text(encoding="utf-8"))
    workers = dispatch.get("workers") or []
    meta_path = Path(str(workers[0].get("meta_path") or "")) if len(workers) == 1 else Path()
    if not meta_path.is_file():
        return {
            "ok": False,
            "stratum": prompt["stratum"],
            "prompt_bytes": prompt["public_bytes"],
            "prompt_sha256": prompt["prompt_sha256"],
            "dispatch_summary_path": str(summary_path),
            "dispatch_summary_sha256": _file_sha256(summary_path),
            "problems": ["relay_meta_missing"],
        }
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    result_path = Path(str(meta.get("result_path") or ""))
    raw_path = Path(str(meta.get("raw_response_path") or ""))
    result_readback = result_path.is_file() and meta.get("result_sha256") == _file_sha256(
        result_path
    )
    raw_readback = raw_path.is_file() and meta.get("raw_response_sha256") == _file_sha256(raw_path)
    measurement = normalize_relay_measurement(
        dispatch,
        meta,
        expected_prompt_sha256=prompt["prompt_sha256"],
        stratum=str(prompt["stratum"]),
        prompt_bytes=int(prompt["public_bytes"]),
        result_hash_readback=result_readback,
        raw_hash_readback=raw_readback,
    )
    measurement.update(
        {
            "dispatch_summary_path": str(summary_path),
            "dispatch_summary_sha256": _file_sha256(summary_path),
            "meta_path": str(meta_path),
            "meta_sha256": _file_sha256(meta_path),
        }
    )
    return measurement


def _query_quota(path: Path) -> dict[str, Any]:
    process = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(path), "-Json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        shell=False,
    )
    if process.returncode != 0:
        return {
            "schema_version": "xinao.g4.capacity.quota_query_failure.v1",
            "ok": False,
            "returncode": process.returncode,
            "stderr_tail": process.stderr[-1000:],
        }
    parsed = json.loads(process.stdout)
    parsed["capacity_role"] = "advisory_percentage_only_unless_absolute_fields_present"
    return parsed


def _hard_bounds_from_quota(quota: dict[str, Any]) -> dict[str, Any]:
    return {
        "available_tokens": quota.get("hard_available_tokens"),
        "max_calls": quota.get("hard_max_calls"),
        "wall_clock_ms": quota.get("hard_wall_clock_ms"),
        "source": quota.get("hard_capacity_source"),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    op_root = _allowed_op_root(args.op_root)
    reused_attempt = args.reuse_attempt_root is not None
    if reused_attempt:
        source_plan_path = args.reuse_attempt_root / "calibration_plan.v1.json"
        if not source_plan_path.is_file():
            raise SystemExit("reused attempt calibration plan missing")
        plan = json.loads(source_plan_path.read_text(encoding="utf-8"))
        if not args.source_operation_id:
            raise SystemExit("--source-operation-id is required with --reuse-attempt-root")
        if args.dispatch:
            raise SystemExit("reused attempt cannot dispatch new provider calls")
        _write_json(
            op_root / "reused_attempt_binding.v1.json",
            {
                "schema_version": "xinao.g4.capacity.reused_attempt_binding.v1",
                "source_attempt_root": str(args.reuse_attempt_root),
                "source_plan_path": str(source_plan_path),
                "source_plan_sha256": _file_sha256(source_plan_path),
                "source_operation_id": args.source_operation_id,
                "new_provider_calls": 0,
                "authority": False,
                "completion_claim_allowed": False,
            },
        )
    else:
        source_plan_path = op_root / "calibration_plan.v1.json"
        plan = prepare(
            op_root,
            model=args.model,
            max_tokens=args.max_tokens,
            timeout_sec=args.timeout_sec,
        )
    measurements: list[dict[str, Any]] = []
    invocation_results: list[dict[str, Any]] = []
    if reused_attempt:
        for prompt in plan["prompts"]:
            dispatch_id = f"g4cap_{args.source_operation_id}_{prompt['index']:02d}"
            summary_path = (
                DEFAULT_RELAY_EVIDENCE / f"dispatch_{dispatch_id}" / "dispatch_summary.json"
            )
            measurement = _measurement_from_summary(prompt, summary_path)
            measurements.append(measurement)
            invocation_results.append(
                {
                    "index": prompt["index"],
                    "reused": True,
                    "source_operation_id": args.source_operation_id,
                    "summary_path": str(summary_path),
                    "measurement_ok": measurement.get("ok") is True,
                }
            )
    elif args.dispatch:
        if not args.launcher.is_file():
            raise SystemExit("stable relay launcher missing")
        for prompt in plan["prompts"]:
            returncode, summary_path = _invoke_relay(
                launcher=args.launcher,
                prompt=prompt,
                model=args.model,
                max_tokens=args.max_tokens,
                timeout_sec=args.timeout_sec,
                operation_id=args.operation_id,
            )
            measurement = _measurement_from_summary(prompt, summary_path)
            measurements.append(measurement)
            invocation_results.append(
                {
                    "index": prompt["index"],
                    "returncode": returncode,
                    "summary_path": str(summary_path),
                    "measurement_ok": measurement.get("ok") is True,
                }
            )
    if args.quota_snapshot is not None:
        if not args.quota_snapshot.is_file():
            raise SystemExit("quota snapshot missing")
        quota = json.loads(args.quota_snapshot.read_text(encoding="utf-8"))
        quota_source_path = args.quota_snapshot
    else:
        quota = _query_quota(args.quota_query)
        quota_source_path = op_root / "quota_snapshot.v1.json"
    _write_json(op_root / "quota_snapshot.v1.json", quota)
    report = adjudicate_capacity(
        measurements=measurements,
        quota_snapshot=quota,
        required_campaign_cells=REQUIRED_CAMPAIGN_CELLS,
        hard_bounds=_hard_bounds_from_quota(quota),
    )
    report.update(
        {
            "operation_id": args.operation_id,
            "calibration_plan_path": str(source_plan_path),
            "calibration_plan_content_hash": plan["content_hash"],
            "invocation_results": invocation_results,
            "reused_attempt": reused_attempt,
            "new_provider_calls": 0 if reused_attempt else len(invocation_results),
            "relay_launcher_path": str(args.launcher),
            "relay_launcher_sha256": _file_sha256(args.launcher),
            "quota_query_path": str(args.quota_query),
            "quota_query_sha256": _file_sha256(args.quota_query),
            "quota_snapshot_source_path": str(quota_source_path),
            "quota_snapshot_source_sha256": _file_sha256(quota_source_path),
        }
    )
    report["content_hash"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "content_hash"}
    )
    _write_json(op_root / "capacity_adjudication.v1.json", report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--op-root", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--dispatch", action="store_true")
    parser.add_argument("--reuse-attempt-root", type=Path)
    parser.add_argument("--source-operation-id", default="")
    parser.add_argument("--quota-snapshot", type=Path)
    parser.add_argument("--launcher", type=Path, default=DEFAULT_LAUNCHER)
    parser.add_argument("--quota-query", type=Path, default=DEFAULT_QUOTA_QUERY)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = run(args)
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return (
        0
        if report.get("terminal")
        in {
            "G4_FULL_CAPACITY_HOLD_VERIFIED",
            "G4_FULL_CAPACITY_MEASURED_FEASIBLE_NO_OUTCOME_ACCESS",
        }
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
