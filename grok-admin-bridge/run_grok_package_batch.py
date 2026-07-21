#!/usr/bin/env python3
"""Run one bounded heterogeneous Grok package batch through singleton contracts."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable
import uuid


DIRECT_ROUTE_TRANSPORT_ID = "direct-grok-worker-pool"
DIRECT_ROUTE_PROVIDER_ID = "grok_acpx_headless"
DIRECT_ROUTE_PROFILE_REF = "grok.com.cached_profile"
EXPECTED_PACKAGE_IDENTITY_SCHEMA = "xinao.worker_package_identity.v2"
EXPECTED_PACKAGE_BATCH_SCHEMA = "xinao.worker_package_batch.v3"
EXPECTED_DISPATCH_ENVELOPE_SCHEMA = "xinao.worker_dispatch_envelope.v2"
EXPECTED_LOGICAL_CANDIDATE_CONSUMER_ID = "worker_candidate_producer"
EXPECTED_LOGICAL_CANDIDATE_EFFECT_CONTRACT = {
    "schema_version": "xinao.worker_candidate_effect_contract.v1",
    "effect_kind": "candidate_artifact_write",
    "output_boundary": "allowed_output_root",
    "authority": False,
    "completion_claim_allowed": False,
}


def _require_dispatch_contract_pin(contract: Any) -> None:
    """Fail on selector API/schema drift instead of inventing compatibility."""

    expected = {
        "PACKAGE_IDENTITY_SCHEMA": EXPECTED_PACKAGE_IDENTITY_SCHEMA,
        "PACKAGE_BATCH_SCHEMA": EXPECTED_PACKAGE_BATCH_SCHEMA,
        "DISPATCH_ENVELOPE_SCHEMA": EXPECTED_DISPATCH_ENVELOPE_SCHEMA,
        "LOGICAL_CANDIDATE_CONSUMER_ID": EXPECTED_LOGICAL_CANDIDATE_CONSUMER_ID,
        "LOGICAL_CANDIDATE_EFFECT_CONTRACT": (
            EXPECTED_LOGICAL_CANDIDATE_EFFECT_CONTRACT
        ),
    }
    for field, expected_value in expected.items():
        observed = getattr(contract, field, None)
        if observed != expected_value:
            raise RuntimeError(
                "S dispatch_economics contract pin drifted: "
                f"field={field};expected={expected_value!r};observed={observed!r}"
            )
    for name in (
        "build_dispatch_outcome_event",
        "claim_dispatch_route",
        "plan_package_frontier",
        "validate_candidate_consumer_binding",
        "validate_dispatch_envelope",
        "validate_dispatch_route_claim",
    ):
        if not callable(getattr(contract, name, None)):
            raise RuntimeError(
                f"S dispatch_economics contract seam missing: callable={name}"
            )


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _contains_reparse_component(path: Path) -> bool:
    cursor = path
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    while True:
        try:
            if cursor.is_symlink():
                return True
            is_junction = getattr(cursor, "is_junction", None)
            if callable(is_junction) and is_junction():
                return True
            attributes = int(getattr(os.lstat(cursor), "st_file_attributes", 0))
            if attributes & reparse_flag:
                return True
        except OSError:
            return True
        if cursor.parent == cursor:
            return False
        cursor = cursor.parent


def _require_exact_candidate_cwd(
    *,
    package: dict[str, Any],
    candidate_cwd: Path,
    selector_root: Path,
    runtime_root: Path,
) -> Path:
    """Recheck an S-admitted candidate boundary immediately before spawn.

    This is deliberately not an admission policy.  The only allow-base decision
    comes from S ``validate_candidate_consumer_binding``; this helper protects
    the returned exact path against drift, aliasing, and reparse TOCTOU.
    """

    logical = str(package.get("allowed_output_root") or "").strip()
    if not logical:
        raise ValueError("candidate allowed_output_root is empty")
    if any(part in {".", ".."} for part in logical.replace("\\", "/").split("/")):
        raise ValueError("candidate allowed_output_root contains dot path traversal")
    lexical = Path(os.path.abspath(logical))
    bound = Path(os.path.abspath(os.fspath(candidate_cwd)))
    if not _same_path(lexical, bound):
        raise ValueError("candidate effective cwd drifted from allowed_output_root")
    if not bound.is_dir():
        raise ValueError(
            f"candidate effective cwd is not an existing directory: {bound}"
        )
    if _contains_reparse_component(bound):
        raise ValueError(
            "candidate effective cwd traverses a symlink, junction, or reparse point"
        )
    physical = bound.resolve(strict=True)
    if not _same_path(bound, physical):
        raise ValueError("candidate effective cwd resolves outside its exact boundary")

    source_cwd = Path(str(package.get("cwd") or "")).resolve(strict=True)
    if _is_within(physical, source_cwd):
        raise ValueError("candidate effective cwd must be isolated from source cwd")
    grok_repo = Path(__file__).resolve().parents[1]
    if _is_within(physical, grok_repo):
        raise ValueError("candidate effective cwd cannot be inside the Grok repository")
    selector = selector_root.resolve(strict=True)
    if _is_within(physical, selector):
        raise ValueError(
            "candidate effective cwd cannot be inside the selector repository"
        )
    runtime = runtime_root.resolve(strict=False)
    runtime_state = runtime / "state"
    if _same_path(physical, runtime) or _is_within(physical, runtime_state):
        raise ValueError("candidate effective cwd cannot be a runtime authority root")
    return physical


def _candidate_cwds_from_binding(
    *,
    binding: dict[str, Any],
    packages: dict[str, dict[str, Any]],
    route_choice_sha256: str,
    physical_consumer_id: str,
    selector_root: Path,
    runtime_root: Path,
) -> dict[str, Path]:
    if (
        binding.get("schema_version") != "xinao.worker_candidate_consumer_binding.v1"
        or binding.get("leg") != "A"
        or binding.get("logical_consumer_id") != EXPECTED_LOGICAL_CANDIDATE_CONSUMER_ID
        or binding.get("logical_effect_contract")
        != EXPECTED_LOGICAL_CANDIDATE_EFFECT_CONTRACT
        or binding.get("physical_consumer_id") != physical_consumer_id
        or binding.get("model_invocation_allowed") is not True
        or binding.get("authority") is not False
        or binding.get("completion_claim_allowed") is not False
        or (binding.get("route_choice") or {}).get("choice_sha256")
        != route_choice_sha256
    ):
        raise ValueError(
            "candidate consumer binding does not own this leg-A model start"
        )
    rows = binding.get("boundaries")
    if not isinstance(rows, list):
        raise TypeError("candidate consumer binding boundaries must be an array")
    candidate_base_raw = str(binding.get("candidate_output_base") or "").strip()
    if not candidate_base_raw:
        raise ValueError("candidate consumer binding has no admitted candidate base")
    candidate_base = Path(candidate_base_raw).resolve(strict=True)
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("candidate consumer binding boundary must be an object")
        package_id = str(row.get("package_id") or "")
        if not package_id or package_id in by_id:
            raise ValueError("candidate consumer binding package identity is invalid")
        by_id[package_id] = row
    if set(by_id) != set(packages):
        raise ValueError("candidate consumer binding package set drifted")

    result: dict[str, Path] = {}
    for package_id, package in packages.items():
        if (
            package.get("logical_consumer_id") != EXPECTED_LOGICAL_CANDIDATE_CONSUMER_ID
            or package.get("logical_effect_contract")
            != EXPECTED_LOGICAL_CANDIDATE_EFFECT_CONTRACT
            or "consumer_id" in package
            or "physical_consumer_id" in package
            or "validated_physical_consumer_id" in package
        ):
            raise ValueError("neutral package manifest binds a physical consumer")
        boundary = by_id[package_id]
        if boundary.get("allowed_output_root") != package.get("allowed_output_root"):
            raise ValueError("candidate consumer logical output boundary drifted")
        effective_cwd = _require_exact_candidate_cwd(
            package=package,
            candidate_cwd=Path(str(boundary.get("physical_output_root") or "")),
            selector_root=selector_root,
            runtime_root=runtime_root,
        )
        if _same_path(effective_cwd, candidate_base) or not _is_within(
            effective_cwd, candidate_base
        ):
            raise ValueError(
                "candidate effective cwd escaped the S-admitted candidate base"
            )
        result[package_id] = effective_cwd
    return result


def _require_route_claim_binding(
    claim: dict[str, Any],
    *,
    route_choice_sha256: str,
    physical_consumer_id: str,
) -> None:
    if (
        claim.get("leg") != "A"
        or claim.get("choice_sha256") != route_choice_sha256
        or claim.get("physical_consumer_id") != physical_consumer_id
        or claim.get("model_invocation_allowed") is not True
    ):
        raise ValueError("leg-A model start is not owned by this durable route claim")


def _require_direct_route_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Reject B/fake route choices before any provider process can start."""

    if envelope.get("leg") != "A":
        raise ValueError(
            "direct Grok package runner requires a leg-A dispatch envelope"
        )
    selected = envelope.get("validated_selected_candidate")
    if not isinstance(selected, dict):
        raise ValueError(
            "direct Grok package runner requires validated route selection"
        )
    expected = {
        "provider_id": DIRECT_ROUTE_PROVIDER_ID,
        "profile_ref": DIRECT_ROUTE_PROFILE_REF,
        "transport_id": DIRECT_ROUTE_TRANSPORT_ID,
    }
    for field, value in expected.items():
        if selected.get(field) != value:
            raise ValueError(
                f"direct Grok package route mismatch: field={field};"
                f"expected={value};observed={selected.get(field)}"
            )
    if envelope.get("validated_execution_adapter") is not None:
        raise ValueError(
            "direct Grok package runner cannot consume a provider route adapter"
        )
    route_choice = envelope.get("validated_route_choice")
    if not isinstance(route_choice, dict) or route_choice.get("leg") != "A":
        raise ValueError(
            "direct Grok package runner requires an exact leg-A route_choice"
        )
    if route_choice.get("selection_decision_sha256") != envelope.get(
        "selection", {}
    ).get("decision_sha256"):
        raise ValueError("direct Grok package route_choice decision drifted")
    return {
        "selected_route": selected,
        "route_choice": route_choice,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _common_dependency_arg(dependency: object) -> str:
    """Encode typed dependencies deterministically across the PS string seam."""

    if isinstance(dependency, str):
        return dependency
    if not isinstance(dependency, dict):
        raise TypeError("package dependency must be a string or typed object")
    return _canonical_bytes(dependency).decode("utf-8")


def _runtime_worker_dependencies(
    packages: dict[str, dict[str, Any]],
) -> dict[str, set[str]]:
    """Return only in-batch edges that a provider terminal may release.

    Owner-adopted and effect-verified edges carry exact immutable pins in a
    validated execution seal.  A provider terminal can never manufacture
    either fact, so those edges are deliberately absent from this runtime map.
    """

    batch_ids = set(packages)
    result: dict[str, set[str]] = {}
    for package_id, package in packages.items():
        dependencies: set[str] = set()
        for raw in package.get("depends_on", []):
            if not isinstance(raw, dict):
                raise TypeError("validated package dependency must be a typed object")
            dependency_id = str(raw.get("package_id") or "").strip()
            condition = str(raw.get("condition") or "").strip()
            if condition == "worker_terminal" and dependency_id in batch_ids:
                dependencies.add(dependency_id)
        result[package_id] = dependencies
    return result


def _pending_dependency_state(
    package_id: str,
    *,
    runtime_dependencies: dict[str, set[str]],
    provider_satisfied: set[str],
    failed: set[str],
    blocked: set[str],
) -> tuple[bool, set[str]]:
    dependencies = runtime_dependencies[package_id]
    blockers = dependencies & (failed | blocked)
    return dependencies <= provider_satisfied, blockers


def _atomic_bytes(path: Path, raw: bytes, *, replace: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FileExistsError(f"immutable package artifact already exists: {path}")
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


def _atomic_json(path: Path, value: object, *, replace: bool = False) -> str:
    raw = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )
    return _atomic_bytes(path, raw, replace=replace)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _identifier(prefix: str) -> str:
    from datetime import datetime

    return f"{prefix}_{datetime.now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _operation_id(package: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        _canonical_bytes(
            {
                "package_id": package["package_id"],
                "work_key": package["work_key"],
                "package_identity_sha256": package["package_identity_sha256"],
            }
        )
    ).hexdigest()
    return f"op_direct_package_{digest[:32]}"


def _hash_bound_ref(path: Path, expected_sha256: str | None = None) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    observed = _sha(resolved)
    if expected_sha256 and observed != expected_sha256:
        raise ValueError(
            f"hash-bound artifact drifted: {resolved}; "
            f"expected={expected_sha256}; observed={observed}"
        )
    return {"path": str(resolved), "sha256": observed}


def _package_artifact_ref(
    package: dict[str, Any], field: str, *, expected_sha256_field: str | None = None
) -> dict[str, str]:
    raw = package.get(field)
    if not isinstance(raw, dict) or set(raw) != {"path", "sha256"}:
        raise ValueError(f"package {field} must be one exact hash-bound artifact ref")
    expected = str(raw.get("sha256") or "").strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError(f"package {field}.sha256 is invalid")
    if expected_sha256_field is not None:
        package_expected = str(package.get(expected_sha256_field) or "").strip().lower()
        if package_expected != expected:
            raise ValueError(
                f"package {field}.sha256 does not match {expected_sha256_field}"
            )
    return _hash_bound_ref(Path(str(raw.get("path") or "")), expected)


def _candidate_write_domain(candidate_root: Path) -> str:
    """Name the physical candidate boundary without granting an authority domain."""

    normalized = str(candidate_root.resolve(strict=True)).replace("\\", "/").rstrip("/")
    if not normalized:
        raise ValueError("candidate output root is empty")
    return "candidate_output_root:" + normalized.casefold()


def _extract_cli_final_text(cli_json_path: Path, lane_meta: dict[str, Any]) -> str:
    """Reproduce the provider validator's exact effective-output selection."""

    payload = _load_object(cli_json_path, "provider CLI JSON")
    source = str(lane_meta.get("effective_output_source") or "").strip()
    if source == "structuredOutput":
        structured = payload.get("structuredOutput")
        if not isinstance(structured, dict):
            raise ValueError("structuredOutput final value must be an object")
        return json.dumps(
            structured,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    if source == "text":
        text = payload.get("text")
        if text is None:
            return ""
        if not isinstance(text, str):
            raise ValueError("provider CLI text final value must be a string")
        return text
    raise ValueError(
        f"provider lane effective_output_source is unsupported: {source!r}"
    )


def _locate_common_receipt(
    summary: dict[str, Any], lane: dict[str, Any]
) -> tuple[Path, str] | None:
    candidates: list[Path] = []
    explicit = str(summary.get("common_adapter_receipt_path") or "").strip()
    if explicit:
        candidates.append(Path(explicit))
    evidence_dir = str(lane.get("evidence_dir") or "").strip()
    if evidence_dir:
        candidates.append(Path(evidence_dir) / "common_adapter_receipt.json")
    expected = str(summary.get("common_adapter_receipt_sha256") or "").strip().lower()
    for candidate in candidates:
        if candidate.is_file():
            observed = _sha(candidate)
            if expected and observed != expected:
                raise ValueError(
                    "common adapter receipt hash drifted: "
                    f"expected={expected}; observed={observed}"
                )
            return candidate.resolve(strict=True), observed
    return None


def _terminal_side_effect_id(
    *, logical_operation_id: str, attempt: int, dispatch_id: str
) -> str:
    return (
        "se:worker-terminal:"
        f"{logical_operation_id}:attempt-{int(attempt)}:retry-{dispatch_id}"
    )


def _build_worker_terminal_event(
    *,
    builder: Callable[..., dict[str, Any]],
    package: dict[str, Any],
    result: dict[str, Any],
    package_manifest_ref: dict[str, str],
    dispatch_envelope_ref: dict[str, str],
    leg: str,
) -> dict[str, Any]:
    return builder(
        event_type="worker_terminal",
        parent_work_key=package["parent_work_key"],
        work_key=package["work_key"],
        package_id=package["package_id"],
        package_manifest_ref=package_manifest_ref,
        dispatch_envelope_ref=dispatch_envelope_ref,
        logical_operation_id=result["operation_id"],
        leg=leg,
        role=package["role"],
        artifact_refs=list(result["event_artifact_refs"]),
        common_attempt_ref={
            "path": result["common_attempt_ref"],
            "sha256": result["common_attempt_sha256"],
        },
        common_contract_ref={
            "path": result["common_contract_ref"],
            "sha256": result["common_contract_sha256"],
        },
    )


def _run_package(
    *,
    package: dict[str, Any],
    candidate_cwd: Path,
    manifest_path: Path,
    manifest_sha256: str,
    dispatch_envelope_path: Path,
    dispatch_envelope_sha256: str,
    dispatch_script: Path,
    pwsh: str,
    runtime_root: Path,
    model: str,
    selection_path: Path,
    selection_sha256: str,
    dispatch_epoch: dict[str, Any],
    selector_root: Path,
    selector_python: Path,
    route_claim_evidence_ref: str,
    route_choice_sha256: str,
    physical_consumer_id: str,
    validate_dispatch_route_claim: Callable[..., dict[str, Any]],
    timeout_sec: int,
    validate_attempt_receipt: Callable[[dict[str, Any], dict[str, Any]], Any],
) -> dict[str, Any]:
    package_id = str(package["package_id"])
    effective_cwd = _require_exact_candidate_cwd(
        package=package,
        candidate_cwd=candidate_cwd,
        selector_root=selector_root,
        runtime_root=runtime_root,
    )
    route_claim_validation = validate_dispatch_route_claim(
        route_claim_evidence_ref=route_claim_evidence_ref,
        dispatch_envelope_ref={
            "path": str(dispatch_envelope_path),
            "sha256": dispatch_envelope_sha256,
        },
    )
    _require_route_claim_binding(
        route_claim_validation,
        route_choice_sha256=route_choice_sha256,
        physical_consumer_id=physical_consumer_id,
    )
    if package.get("write_domains"):
        raise ValueError(
            "candidate-only package cannot pass authority write domains to leg A"
        )
    rules_ref = _package_artifact_ref(
        package,
        "rules_ref",
        expected_sha256_field="rules_sha256",
    )
    candidate_write_domain = _candidate_write_domain(effective_cwd)
    dispatch_id = _identifier("cdx")
    pool_id = _identifier("gwp")
    operation_id = _operation_id(package)
    command = [
        pwsh,
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(dispatch_script),
        "-N",
        "1",
        "-PromptFile",
        str(package["prompt_ref"]["path"]),
        "-Cwd",
        str(effective_cwd),
        "-Model",
        model,
        "-SelectionPath",
        str(selection_path),
        "-ExpectedSelectionDecisionSha256",
        selection_sha256,
        "-RuntimeRoot",
        str(runtime_root),
        "-DispatchEpochId",
        str(dispatch_epoch["epoch_id"]),
        "-DispatchEpochSource",
        "neutral_package_manifest",
        "-QuotaSnapshotId",
        str(dispatch_epoch["quota_snapshot_id"]),
        "-QuotaSnapshotRef",
        str(dispatch_epoch["quota_snapshot_ref"]),
        "-QuotaSnapshotSha256",
        str(dispatch_epoch["quota_snapshot_sha256"]),
        "-QuotaResolutionStatus",
        "sealed_manifest",
        "-CommonWorkKey",
        str(package["work_key"]),
        "-CommonOperationId",
        operation_id,
        "-CommonTaskContractRef",
        f"{manifest_path}#sha256={manifest_sha256}",
        "-CommonCorrelationId",
        str(package["parent_work_key"]),
        "-CommonSubjectManifestSha256",
        manifest_sha256,
        "-CommonContextManifestPath",
        str(package["context_manifest_ref"]["path"]),
        "-CommonRulesFile",
        rules_ref["path"],
        "-CommonRulesSha256",
        rules_ref["sha256"],
        "-CommonCandidateOutputRoot",
        str(effective_cwd),
        "-CommonPhase",
        str(package["phase"]),
        "-CommonAdapterRoot",
        str(selector_root),
        "-CommonPythonExe",
        str(selector_python),
        "-MinResultChars",
        str(package["acceptance"]["min_result_chars"]),
        "-TimeoutSec",
        str(min(timeout_sec, int(package["timeout_sec"]))),
        "-DispatchId",
        dispatch_id,
        "-PoolId",
        pool_id,
        "-Quiet",
        "-CommonWriteDomains",
        candidate_write_domain,
    ]
    if package["acceptance"]["required_result_markers"]:
        command.append("-RequiredResultMarkers")
        command.extend(
            str(marker) for marker in package["acceptance"]["required_result_markers"]
        )
    if package["acceptance"]["require_json_object"]:
        command.append("-RequireJsonObject")
        command.extend(
            ["-JsonSchemaPath", str(package["acceptance"]["json_schema_ref"]["path"])]
        )
    if package["depends_on"]:
        command.append("-CommonDependsOn")
        command.extend(
            _common_dependency_arg(dependency) for dependency in package["depends_on"]
        )
    prior = package.get("prior_attempt_receipt_ref")
    if isinstance(prior, dict) and prior.get("path"):
        command.extend(["-CommonPriorAttemptReceiptPath", str(prior["path"])])
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(30, min(timeout_sec, int(package["timeout_sec"])) + 60),
    )
    pool_summary = (
        runtime_root / "state" / "grok_worker_pool" / pool_id / "pool_summary.json"
    )
    result: dict[str, Any] = {
        "package_id": package_id,
        "work_key": package["work_key"],
        "operation_id": operation_id,
        "dispatch_id": dispatch_id,
        "pool_id": pool_id,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
        "pool_summary_ref": str(pool_summary),
    }
    if not pool_summary.is_file():
        result.update(
            status="failed", failure="singleton dispatch did not produce a pool summary"
        )
        return result
    summary = _load_object(pool_summary, "pool summary")
    if (
        summary.get("n") != 1
        or summary.get("model") != model
        or summary.get("selection_decision_sha256") != selection_sha256
    ):
        result.update(status="failed", failure="singleton pool identity drifted")
        return result
    rows = summary.get("results")
    if summary.get("reuse_skipped_execution") is True:
        result.update(
            status="reused",
            pool_summary_sha256=_sha(pool_summary),
            reuse_disposition=summary.get("reuse_disposition"),
        )
        return result
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        result.update(
            status="failed", failure="singleton pool did not expose one terminal lane"
        )
        return result
    lane = dict(rows[0])
    meta_path = Path(str(lane.get("meta_path") or ""))
    try:
        located_common = _locate_common_receipt(summary, lane)
    except (OSError, ValueError) as exc:
        result.update(status="failed", failure=f"common receipt invalid: {exc}")
        return result
    if located_common is None:
        result.update(
            status="failed", failure="terminal lane has no valid common receipt"
        )
        return result
    common_receipt_path, common_receipt_sha = located_common
    common = _load_object(common_receipt_path, "common adapter receipt")
    attempt_path = Path(
        str((common.get("artifact_paths") or {}).get("attempt_receipt") or "")
    )
    attempt_sha = str(
        (common.get("artifact_sha256") or {}).get("attempt_receipt") or ""
    )
    contract_path = Path(
        str((common.get("artifact_paths") or {}).get("logical_contract") or "")
    )
    contract_sha = str(
        (common.get("artifact_sha256") or {}).get("logical_contract") or ""
    )
    if (
        common.get("work_key") != package["work_key"]
        or common.get("logical_operation_id") != operation_id
        or not attempt_path.is_file()
        or _sha(attempt_path) != attempt_sha
        or not contract_path.is_file()
        or _sha(contract_path) != contract_sha
    ):
        result.update(
            status="failed", failure="common receipt package identity drifted"
        )
        return result
    contract = _load_object(contract_path, "common logical contract")
    attempt_receipt = _load_object(attempt_path, "common attempt receipt")
    try:
        validate_attempt_receipt(contract, attempt_receipt)
    except (TypeError, ValueError) as exc:
        result.update(status="failed", failure=f"common attempt receipt invalid: {exc}")
        return result
    if (
        contract.get("logical_operation_id") != operation_id
        or contract.get("work_key") != package["work_key"]
        or attempt_receipt.get("logical_operation_id") != operation_id
        or attempt_receipt.get("work_key") != package["work_key"]
    ):
        result.update(
            status="failed", failure="common contract or attempt identity drifted"
        )
        return result
    attempt_number = attempt_receipt.get("attempt")
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 1
    ):
        result.update(status="failed", failure="common attempt number is invalid")
        return result

    output_root = effective_cwd
    attempt_root = output_root / f"attempt-{attempt_number:04d}-{dispatch_id}"
    artifact_refs: list[dict[str, str]] = [
        _hash_bound_ref(common_receipt_path, common_receipt_sha),
        _hash_bound_ref(attempt_path, attempt_sha),
        _hash_bound_ref(contract_path, contract_sha),
        _hash_bound_ref(pool_summary),
    ]
    provider_output_ref: dict[str, str] | None = None
    provider_cli_ref: dict[str, str] | None = None
    provider_meta_ref: dict[str, str] | None = None
    provider_output_error = ""
    try:
        provider_meta_ref = _hash_bound_ref(meta_path)
        expected_meta_sha = (
            str(common.get("provider_evidence_sha256") or "").strip().lower()
        )
        expected_meta_path = str(common.get("provider_evidence_ref") or "").strip()
        if expected_meta_sha and provider_meta_ref["sha256"] != expected_meta_sha:
            raise ValueError(
                "provider metadata does not match common receipt evidence hash"
            )
        if expected_meta_path and (
            Path(expected_meta_path).resolve(strict=False)
            != Path(provider_meta_ref["path"]).resolve(strict=False)
        ):
            raise ValueError(
                "provider metadata does not match common receipt evidence path"
            )
        meta = _load_object(meta_path, "provider lane metadata")
        cli_json = Path(str(meta.get("cli_json") or ""))
        provider_cli_ref = _hash_bound_ref(cli_json)
        final_text = _extract_cli_final_text(cli_json, meta)
        provider_output_path = attempt_root / "provider-output"
        provider_output_sha = _atomic_bytes(
            provider_output_path, final_text.encode("utf-8")
        )
        provider_output_ref = {
            "path": str(provider_output_path.resolve(strict=True)),
            "sha256": provider_output_sha,
        }
        expected_output_sha = str(
            (attempt_receipt.get("output") or {}).get("content_sha256") or ""
        ).lower()
        if provider_output_sha != expected_output_sha:
            raise ValueError(
                "provider-output sha256 does not match common attempt output.content_sha256: "
                f"expected={expected_output_sha}; observed={provider_output_sha}"
            )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        provider_output_error = str(exc)

    if provider_output_error:
        result.update(
            status="failed",
            failure=provider_output_error,
            common_attempt_ref=str(attempt_path),
            common_attempt_sha256=attempt_sha,
            common_contract_ref=str(contract_path),
            common_contract_sha256=contract_sha,
            attempt=attempt_number,
        )
        return result
    for ref in (provider_output_ref, provider_cli_ref, provider_meta_ref):
        if ref is not None and ref not in artifact_refs:
            artifact_refs.append(ref)

    envelope = {
        "schema_version": "xinao.worker_package_result.v2",
        "package_id": package_id,
        "work_key": package["work_key"],
        "parent_work_key": package["parent_work_key"],
        "logical_operation_id": operation_id,
        "attempt": attempt_number,
        "dispatch_id": dispatch_id,
        "pool_id": pool_id,
        "role": package["role"],
        "selection_decision_sha256": selection_sha256,
        "package_manifest_ref": _hash_bound_ref(manifest_path, manifest_sha256),
        "dispatch_envelope_ref": _hash_bound_ref(
            dispatch_envelope_path, dispatch_envelope_sha256
        ),
        "common_adapter_receipt_ref": _hash_bound_ref(
            common_receipt_path, common_receipt_sha
        ),
        "common_attempt_ref": _hash_bound_ref(attempt_path, attempt_sha),
        "common_contract_ref": _hash_bound_ref(contract_path, contract_sha),
        "provider_output_ref": provider_output_ref,
        "artifact_refs": artifact_refs,
        "authority": False,
        "completion_claim_allowed": False,
    }
    envelope_path = attempt_root / "package-result.json"
    envelope_sha = _atomic_json(envelope_path, envelope)
    artifact_refs.append(
        {"path": str(envelope_path.resolve(strict=True)), "sha256": envelope_sha}
    )
    result.update(
        status="terminal_ready",
        terminal_recordable=True,
        package_result_ref=str(envelope_path),
        package_result_sha256=envelope_sha,
        provider_output_ref=provider_output_ref,
        common_attempt_ref=str(attempt_path),
        common_attempt_sha256=attempt_sha,
        common_contract_ref=str(contract_path),
        common_contract_sha256=contract_sha,
        common_adapter_receipt_ref=str(common_receipt_path),
        common_adapter_receipt_sha256=common_receipt_sha,
        attempt=attempt_number,
        event_artifact_refs=artifact_refs,
        pool_summary_sha256=_sha(pool_summary),
    )
    return result


def _append_task_run_event(
    *,
    task_run_cli: Path,
    task_run_root: Path,
    task_run_id: str,
    event_path: Path,
    event_sha256: str,
    work_key: str,
    package_id: str,
    logical_operation_id: str,
    attempt: int,
    dispatch_id: str,
    provider_accepted: bool,
    provider_exit_code: int,
) -> None:
    terminal_label = "accepted" if provider_accepted else "rejected"
    exit_code = 0 if provider_accepted else (provider_exit_code or 3)
    command = [
        sys.executable,
        str(task_run_cli),
        "--root",
        str(task_run_root),
        "event",
        "--run-id",
        task_run_id,
        "--event-id",
        f"evt-dispatch-{event_sha256[:32]}",
        "--actor",
        "grok-worker-pool",
        "--kind",
        "result",
        "--phase",
        "worker_terminal",
        "--summary",
        (
            f"provider {terminal_label} package {package_id}; "
            f"operation={logical_operation_id}; attempt={attempt}; retry={dispatch_id}"
        ),
        "--evidence-ref",
        f"{event_path}#sha256={event_sha256}",
        "--target",
        work_key,
        "--exit-code",
        str(exit_code),
        "--retry-class",
        "none",
        "--side-effect-id",
        _terminal_side_effect_id(
            logical_operation_id=logical_operation_id,
            attempt=attempt,
            dispatch_id=dispatch_id,
        ),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"task-run append failed exit={completed.returncode}: {completed.stderr.strip()}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dispatch-envelope",
        "--manifest",
        dest="dispatch_envelope",
        type=Path,
        required=True,
    )
    parser.add_argument("--selector-root", type=Path, required=True)
    parser.add_argument("--selector-python", type=Path, required=True)
    parser.add_argument("--dispatch-script", type=Path, required=True)
    parser.add_argument("--pwsh", default="pwsh")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--selection-path", type=Path, required=True)
    parser.add_argument("--checkpoint-path", type=Path, required=True)
    parser.add_argument("--task-run-cli", type=Path, required=True)
    parser.add_argument("--task-run-root", type=Path, required=True)
    parser.add_argument("--task-run-id", required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--timeout-sec", type=int, default=600)
    args = parser.parse_args()

    selector_root = args.selector_root.resolve(strict=True)
    sys.path.insert(0, str(selector_root))
    dispatch_contract = importlib.import_module(
        "services.agent_runtime.dispatch_economics"
    )
    _require_dispatch_contract_pin(dispatch_contract)
    build_dispatch_outcome_event = dispatch_contract.build_dispatch_outcome_event
    claim_dispatch_route = dispatch_contract.claim_dispatch_route
    plan_package_frontier = dispatch_contract.plan_package_frontier
    validate_candidate_consumer_binding = (
        dispatch_contract.validate_candidate_consumer_binding
    )
    validate_dispatch_envelope = dispatch_contract.validate_dispatch_envelope
    validate_dispatch_route_claim = dispatch_contract.validate_dispatch_route_claim
    from services.agent_runtime.execution_contract import (  # type: ignore
        validate_attempt_receipt,
    )

    dispatch_envelope_path = args.dispatch_envelope.resolve(strict=True)
    dispatch_envelope_sha = _sha(dispatch_envelope_path)
    dispatch_envelope_raw = _load_object(
        dispatch_envelope_path, "worker dispatch envelope"
    )
    dispatch_envelope = validate_dispatch_envelope(dispatch_envelope_raw)
    direct_route = _require_direct_route_envelope(dispatch_envelope)
    manifest_path = Path(dispatch_envelope["package_manifest_ref"]["path"]).resolve(
        strict=True
    )
    manifest_sha = _sha(manifest_path)
    validated = dispatch_envelope["validated_package_manifest"]
    if dispatch_envelope["selection"]["model_id"] != args.model:
        raise ValueError(
            "dispatch envelope model does not match explicit launcher model"
        )
    selection_path = args.selection_path.resolve(strict=True)
    if str(selection_path) != str(
        Path(dispatch_envelope["selection"]["receipt_ref"]).resolve(strict=True)
    ):
        raise ValueError("dispatch envelope selection path mismatch")
    selection_sha = str(dispatch_envelope["selection"]["decision_sha256"])
    checkpoint_path = args.checkpoint_path.resolve(strict=True)
    task_run_cli = args.task_run_cli.resolve(strict=True)
    task_run_root = args.task_run_root.resolve(strict=True)
    task_run_id = str(args.task_run_id).strip()
    if not task_run_id:
        raise ValueError("task-run id must be non-empty")
    task_run_dir = (task_run_root / task_run_id).resolve(strict=True)
    if not task_run_dir.is_dir():
        raise ValueError(f"task-run directory missing: {task_run_dir}")

    admitted_ids = set(dispatch_envelope["package_ids"])
    frontier = plan_package_frontier(validated)
    planned_worker_ids = {
        str(row["package_id"])
        for row in frontier["admitted"]
        if row["candidate_only"] is True and row["execution_seal_ready"] is True
    }
    outside_frontier = sorted(admitted_ids - planned_worker_ids)
    if outside_frontier:
        raise ValueError(
            "dispatch envelope contains packages outside the planned worker frontier: "
            + ",".join(outside_frontier)
        )
    packages = {
        str(row["package_id"]): row
        for row in validated["packages"]
        if str(row["package_id"]) in admitted_ids
    }
    if set(packages) != admitted_ids:
        raise ValueError(
            "dispatch envelope package identities drifted after validation"
        )
    physical_consumer_id = str(dispatch_envelope["validated_physical_consumer_id"])
    requested_output_roots = {
        package_id: package["allowed_output_root"]
        for package_id, package in packages.items()
    }
    candidate_binding = validate_candidate_consumer_binding(
        dispatch_envelope_raw,
        physical_consumer_id=physical_consumer_id,
        expected_leg="A",
        requested_output_roots=requested_output_roots,
    )
    candidate_cwds = _candidate_cwds_from_binding(
        binding=candidate_binding,
        packages=packages,
        route_choice_sha256=direct_route["route_choice"]["choice_sha256"],
        physical_consumer_id=physical_consumer_id,
        selector_root=selector_root,
        runtime_root=args.runtime_root,
    )
    if _sha(manifest_path) != manifest_sha:
        raise ValueError("neutral package manifest changed during leg-A admission")

    dispatch_envelope_ref = {
        "path": str(dispatch_envelope_path),
        "sha256": dispatch_envelope_sha,
    }
    route_claim = claim_dispatch_route(
        dispatch_envelope_ref=dispatch_envelope_ref,
        checkpoint_path=checkpoint_path,
        task_run_dir=task_run_dir,
        task_run_cli=task_run_cli,
        holder_id=f"grok-leg-a:{os.getpid()}",
    )
    if route_claim.get("status") not in {"won", "reused"}:
        raise ValueError("leg-A durable route claim did not reach won or reused")
    _require_route_claim_binding(
        route_claim,
        route_choice_sha256=direct_route["route_choice"]["choice_sha256"],
        physical_consumer_id=physical_consumer_id,
    )
    route_claim_evidence_ref = str(route_claim.get("route_claim_evidence_ref") or "")
    if not route_claim_evidence_ref:
        raise ValueError("leg-A durable route claim has no evidence ref")
    route_claim_validation = validate_dispatch_route_claim(
        route_claim_evidence_ref=route_claim_evidence_ref,
        dispatch_envelope_ref=dispatch_envelope_ref,
    )
    _require_route_claim_binding(
        route_claim_validation,
        route_choice_sha256=direct_route["route_choice"]["choice_sha256"],
        physical_consumer_id=physical_consumer_id,
    )
    runtime_dependencies = _runtime_worker_dependencies(packages)
    pending = set(packages)
    provider_satisfied: set[str] = set()
    provider_accepted: set[str] = set()
    reused: set[str] = set()
    failed: set[str] = set()
    blocked: set[str] = set()
    results: dict[str, dict[str, Any]] = {}
    active: dict[Future[dict[str, Any]], str] = {}
    max_parallel = int(validated["limits"]["max_parallel"])
    fan_in_capacity = int(validated["limits"]["fan_in_capacity"])
    backpressure_cycles = 0

    def submit(executor: ThreadPoolExecutor, package_id: str) -> None:
        package = packages[package_id]
        future = executor.submit(
            _run_package,
            package=package,
            candidate_cwd=candidate_cwds[package_id],
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha,
            dispatch_envelope_path=dispatch_envelope_path,
            dispatch_envelope_sha256=dispatch_envelope_sha,
            dispatch_script=args.dispatch_script.resolve(strict=True),
            pwsh=args.pwsh,
            runtime_root=args.runtime_root.resolve(strict=False),
            model=args.model,
            selection_path=selection_path,
            selection_sha256=selection_sha,
            dispatch_epoch=dispatch_envelope["dispatch_epoch"],
            selector_root=selector_root,
            selector_python=args.selector_python.resolve(strict=True),
            route_claim_evidence_ref=route_claim_evidence_ref,
            route_choice_sha256=direct_route["route_choice"]["choice_sha256"],
            physical_consumer_id=physical_consumer_id,
            validate_dispatch_route_claim=validate_dispatch_route_claim,
            timeout_sec=args.timeout_sec,
            validate_attempt_receipt=validate_attempt_receipt,
        )
        active[future] = package_id
        pending.remove(package_id)

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        while pending or active:
            progress = True
            while progress:
                progress = False
                for package_id in sorted(
                    pending, key=lambda value: packages[value]["lane_index"]
                ):
                    ready, blocked_by = _pending_dependency_state(
                        package_id,
                        runtime_dependencies=runtime_dependencies,
                        provider_satisfied=provider_satisfied,
                        failed=failed,
                        blocked=blocked,
                    )
                    if blocked_by:
                        pending.remove(package_id)
                        blocked.add(package_id)
                        results[package_id] = {
                            "package_id": package_id,
                            "work_key": packages[package_id]["work_key"],
                            "status": "blocked_dependency",
                            "blocked_by": sorted(blocked_by),
                        }
                        progress = True
                        break
                    if ready and len(active) < max_parallel:
                        submit(executor, package_id)
                        progress = True
                        break
            if not active:
                if pending:
                    raise RuntimeError("package frontier stalled after validated DAG")
                break
            done, _ = wait(tuple(active), return_when=FIRST_COMPLETED)
            ordered_done = sorted(
                done, key=lambda future: packages[active[future]]["lane_index"]
            )
            if len(ordered_done) > fan_in_capacity:
                backpressure_cycles += 1
            for future in ordered_done[:fan_in_capacity]:
                package_id = active.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "package_id": package_id,
                        "work_key": packages[package_id]["work_key"],
                        "status": "failed",
                        "failure": f"{type(exc).__name__}: {exc}",
                    }
                results[package_id] = result
                if result.get("status") == "reused":
                    reused.add(package_id)
                    provider_satisfied.add(package_id)
                    continue
                if result.get("terminal_recordable") is not True:
                    failed.add(package_id)
                    continue
                try:
                    package = packages[package_id]
                    event = _build_worker_terminal_event(
                        builder=build_dispatch_outcome_event,
                        package=package,
                        result=result,
                        package_manifest_ref={
                            "path": str(manifest_path),
                            "sha256": manifest_sha,
                        },
                        dispatch_envelope_ref={
                            "path": str(dispatch_envelope_path),
                            "sha256": dispatch_envelope_sha,
                        },
                        leg=str(dispatch_envelope["leg"]),
                    )
                    event_path = Path(result["package_result_ref"]).with_name(
                        "worker-terminal-event.json"
                    )
                    event_sha = _atomic_json(event_path, event)
                    _append_task_run_event(
                        task_run_cli=task_run_cli,
                        task_run_root=task_run_root,
                        task_run_id=task_run_id,
                        event_path=event_path,
                        event_sha256=event_sha,
                        work_key=str(package["work_key"]),
                        package_id=package_id,
                        logical_operation_id=str(result["operation_id"]),
                        attempt=int(result["attempt"]),
                        dispatch_id=str(result["dispatch_id"]),
                        provider_accepted=event["provider_accepted"] is True,
                        provider_exit_code=int(result["exit_code"]),
                    )
                    result["worker_terminal_event_ref"] = str(event_path)
                    result["worker_terminal_event_sha256"] = event_sha
                    if event["provider_accepted"] is True:
                        result["status"] = "accepted"
                        provider_accepted.add(package_id)
                        provider_satisfied.add(package_id)
                    else:
                        result["status"] = "rejected"
                        failed.add(package_id)
                except Exception as exc:
                    result["status"] = "failed"
                    result["failure"] = (
                        f"worker terminal recording failed: {type(exc).__name__}: {exc}"
                    )
                    failed.add(package_id)

    ordered_results = [
        results[str(row["package_id"])]
        for row in validated["packages"]
        if str(row["package_id"]) in packages
    ]
    summary = {
        "schema_version": "xinao.grok_worker_package_batch_result.v2",
        "package_manifest_ref": {"path": str(manifest_path), "sha256": manifest_sha},
        "dispatch_envelope_ref": {
            "path": str(dispatch_envelope_path),
            "sha256": dispatch_envelope_sha,
        },
        "validated_manifest_sha256": validated["validated_manifest_sha256"],
        "selection_decision_sha256": selection_sha,
        "alternative_group_sha256": direct_route["route_choice"][
            "alternative_group_sha256"
        ],
        "route_choice_sha256": direct_route["route_choice"]["choice_sha256"],
        "route_transport_id": direct_route["selected_route"]["transport_id"],
        "dispatch_route_claim": {
            "status": route_claim["status"],
            "alternative_group_sha256": route_claim["alternative_group_sha256"],
            "choice_sha256": route_claim["choice_sha256"],
            "route_claim_evidence_ref": route_claim_evidence_ref,
        },
        "dispatch_epoch": {
            "epoch_id": dispatch_envelope["dispatch_epoch"]["epoch_id"],
            "quota_snapshot_id": dispatch_envelope["dispatch_epoch"][
                "quota_snapshot_id"
            ],
            "quota_snapshot_ref": dispatch_envelope["dispatch_epoch"][
                "quota_snapshot_ref"
            ],
            "quota_snapshot_sha256": dispatch_envelope["dispatch_epoch"][
                "quota_snapshot_sha256"
            ],
        },
        "max_parallel": max_parallel,
        "fan_in_capacity": fan_in_capacity,
        "backpressure_cycles": backpressure_cycles,
        "provider_accepted_package_ids": sorted(provider_accepted),
        "reused_package_ids": sorted(reused),
        "satisfied_package_ids": sorted(provider_satisfied),
        "failed_package_ids": sorted(failed),
        "blocked_package_ids": sorted(blocked),
        "results": ordered_results,
        "all_packages_satisfied": len(provider_satisfied) == len(packages),
        "authority": False,
        "completion_claim_allowed": False,
    }
    summary_sha = _atomic_json(args.summary_output.resolve(strict=False), summary)
    print(
        json.dumps(
            {
                "summary_ref": str(args.summary_output.resolve(strict=True)),
                "summary_sha256": summary_sha,
                "provider_accepted": len(provider_accepted),
                "reused": len(reused),
                "failed": len(failed),
                "blocked": len(blocked),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if len(provider_satisfied) == len(packages) else 2


if __name__ == "__main__":
    raise SystemExit(main())
