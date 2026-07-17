"""Independently verify the bounded F4 live-canary evidence pack.

This verifier is intentionally separate from the positive canary runner.  It
only reads immutable evidence, replays the six retained Temporal histories,
and emits a content-addressed assertion map beside (never inside) the source
pack.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import ntpath
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DUAL_BRAIN_SRC = REPO_ROOT / "projects" / "dual-brain-coordination" / "src"
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
for source_root in (REPO_ROOT, XINAO_SRC, DUAL_BRAIN_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    artifact_json_bytes,
    logical_contract_sha256,
    validate_attempt_receipt,
)
from services.agent_runtime.grok_execution_contract_adapter import GROK_DOCKER_CONSUMER_ID
from xinao.foundation.f4_snapshot_runtime import (
    file_sha256 as snapshot_file_sha256,
)
from xinao.foundation.f4_snapshot_runtime import (
    input_path,
    inside,
    load_object,
    readable_path,
    retained_path,
    same_path,
)

DEFAULT_PACK = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence"
    r"\xinao-f4-live-canary-20260714T144335Z"
)
HOST_EVIDENCE_ROOT = Path(
    os.environ.get("XINAO_EVIDENCE_HOST", r"D:\XINAO_RESEARCH_RUNTIME")
).resolve()
SCHEMA_VERSION = "xinao.f4_live_pack_independent_verification.v1"
ASSERTION_SCHEMA_VERSION = "xinao.content_addressed_assertion.v1"
EXPECTED_STAGES = ["PRODUCER", "CRITIQUE", "VERIFIER"] * 2
EXPECTED_WIDTHS = [1, 1, 1, 2, 2, 2]
EXPECTED_CAPACITY_REASONS = ["INITIAL_VERIFIED_CAPACITY"] * 3 + ["UPSHIFT_AFTER_FULL_SUCCESS"] * 3
EXPECTED_OPERATION_ARTIFACTS = {
    "events.ndjson",
    "final.txt",
    "manifest.json",
    "operation-spec.json",
    "stderr.log",
}
EXPECTED_MANIFEST_FILES = EXPECTED_OPERATION_ARTIFACTS - {"manifest.json"}
EXPECTED_DOCKER_OPERATION_ARTIFACTS = {
    "attempt_receipt.json",
    "cli_result.json",
    "final.txt",
    "logical_contract.json",
    "operation-spec.json",
}
LEGACY_ACPX_MODEL = "grok-4.5"
DOCKER_EXECUTION_LOCATION = "docker:houtai-gongren"
DOCKER_F4_MODEL = "grok-composer-2.5-fast"
DOCKER_MODEL_POLICY_ID = "xinao.grok.provider_model_routing.v2"


class VerificationError(ValueError):
    """Raised when source evidence is missing, mutable, or contradictory."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the stable JSON representation used by this verifier."""

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
    return snapshot_file_sha256(path)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = load_object(path)
    except (OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"JSON evidence is not an object: {path}")
    return value


def _resolve_ref(value: object) -> Path:
    text = str(value or "").strip()
    if not text:
        raise VerificationError("empty evidence ref")
    try:
        return readable_path(text, expect="file")
    except (OSError, RuntimeError) as original_exc:
        normalized = text.replace("\\", "/")
        if normalized.casefold().startswith("/evidence/"):
            relative = normalized[len("/evidence/") :]
            candidate = (HOST_EVIDENCE_ROOT / Path(relative)).resolve()
            try:
                candidate.relative_to(HOST_EVIDENCE_ROOT)
            except ValueError as exc:
                raise VerificationError(
                    f"container evidence ref escaped the host runtime root: {text}"
                ) from exc
            try:
                return readable_path(candidate, expect="file")
            except (OSError, RuntimeError) as exc:
                raise VerificationError(f"evidence ref is missing: {text}") from exc
        raise VerificationError(f"evidence ref is missing: {text}") from original_exc


def _require_inside(path: Path, root: Path, *, label: str) -> None:
    if not inside(path, root):
        raise VerificationError(f"{label} escaped the live pack: {path}")


def _same_path(left: object, right: object) -> bool:
    if same_path(left, right):
        return True
    try:
        return same_path(_resolve_ref(left), _resolve_ref(right))
    except VerificationError:
        return False


def _bound_file(
    ref: object,
    expected_sha256: object,
    *,
    expected_size: object | None = None,
    root: Path | None = None,
) -> Path:
    path = _resolve_ref(ref)
    if root is not None:
        _require_inside(path, root, label="bound evidence")
    expected = str(expected_sha256 or "").lower()
    actual = file_sha256(path)
    _require(len(expected) == 64 and actual == expected, f"evidence hash drifted: {path}")
    if expected_size is not None:
        _require(path.stat().st_size == int(expected_size), f"evidence size drifted: {path}")
    return path


def _evidence_ref(path: Path) -> dict[str, Any]:
    resolved = readable_path(path, expect="file")
    return {
        "path": retained_path(path),
        "sha256": file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _assertion(
    assertion_id: str,
    evidence_paths: Iterable[Path],
    observed: Mapping[str, Any],
) -> dict[str, Any]:
    refs_by_path = {retained_path(path): _evidence_ref(path) for path in evidence_paths}
    refs = [refs_by_path[key] for key in sorted(refs_by_path)]
    body = {
        "schema_version": ASSERTION_SCHEMA_VERSION,
        "assertion_id": assertion_id,
        "status": "PASS",
        "evidence_refs": refs,
        "evidence_set_sha256": canonical_sha256(refs),
        "observed": dict(observed),
    }
    return {**body, "assertion_sha256": canonical_sha256(body)}


def _parse_result_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        _require(len(lines) >= 3 and lines[-1].strip() == "```", "unterminated JSON fence")
        raw = "\n".join(lines[1:-1]).strip()
        if raw.startswith("json"):
            raw = raw[4:].lstrip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerificationError("operation final artifact is not strict JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError("operation final artifact is not a JSON object")
    return value


def _verify_artifact_manifest(pack: Path) -> tuple[dict[str, Any], Path, list[Path], str]:
    manifest_path = pack / "artifact_manifest.json"
    manifest = _load_object(manifest_path)
    _require(
        manifest.get("schema_version") == "xinao.f4_live_canary_artifact_manifest.v1",
        "unexpected live-pack manifest schema",
    )
    entries = manifest.get("artifacts")
    _require(isinstance(entries, list) and entries, "live-pack artifact list is empty")
    paths: list[Path] = []
    identities: list[dict[str, Any]] = []
    for raw in entries:
        _require(isinstance(raw, dict), "live-pack artifact entry is not an object")
        path = _bound_file(
            raw.get("path"),
            raw.get("sha256"),
            expected_size=raw.get("size_bytes"),
            root=pack,
        )
        paths.append(path)
        identities.append(
            {
                "path": path.relative_to(pack).as_posix(),
                "sha256": str(raw.get("sha256") or "").lower(),
                "size_bytes": int(raw.get("size_bytes") or 0),
            }
        )
    _require(len(paths) == len(set(paths)), "live-pack manifest contains duplicate paths")
    actual = {path.resolve() for path in pack.rglob("*") if path.is_file()}
    actual.discard(manifest_path.resolve())
    _require(actual == set(paths), "live-pack manifest does not equal the exact file set")
    return (
        manifest,
        manifest_path,
        paths,
        canonical_sha256(sorted(identities, key=lambda x: x["path"])),
    )


def _verify_receipt_file(pack: Path, receipt: Mapping[str, Any]) -> Path:
    path = _bound_file(
        receipt.get("receipt_ref"),
        receipt.get("receipt_sha256"),
        root=pack,
    )
    persisted = _load_object(path)
    projected = {
        key: value for key, value in receipt.items() if key not in {"receipt_ref", "receipt_sha256"}
    }
    _require(persisted == projected, "report receipt does not equal its persisted bytes")
    return path


def _verify_request(receipt: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    path = _resolve_ref(receipt.get("request_ref"))
    request = _load_object(path)
    body = dict(request)
    recorded = str(body.pop("request_hash", "")).lower()
    _require(recorded == canonical_sha256(body), "external request content hash drifted")
    _require(recorded == str(receipt.get("request_hash") or "").lower(), "request hash mismatch")
    return path, request


def _verify_payload(receipt: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    path = _bound_file(receipt.get("payload_ref"), receipt.get("payload_sha256"))
    return path, _load_object(path)


def _verify_transaction_receipt(
    pack: Path,
    receipt: Mapping[str, Any],
    result: Mapping[str, Any],
) -> list[Path]:
    _require(
        receipt.get("schema_version") == "xinao.f4_live_bridge_receipt.v2",
        "unexpected live bridge receipt schema",
    )
    bindings = {
        "handshake": ("handshake_ref", "handshake_sha256"),
        "identity": ("transaction_identity_ref", "transaction_identity_sha256"),
        "execution": ("transaction_execution_ref", "transaction_execution_sha256"),
        "attempt": ("transaction_attempt_ref", "transaction_attempt_sha256"),
        "outcome": ("attempt_outcome_ref", "attempt_outcome_sha256"),
    }
    paths: dict[str, Path] = {}
    values: dict[str, dict[str, Any]] = {}
    for label, (ref_name, hash_name) in bindings.items():
        path = _bound_file(
            receipt.get(ref_name),
            receipt.get(hash_name),
            root=pack,
        )
        paths[label] = path
        values[label] = _load_object(path)
    handshake = values["handshake"]
    identity = values["identity"]
    execution = values["execution"]
    attempt = values["attempt"]
    outcome = values["outcome"]
    request_hash = str(receipt.get("request_hash") or "")
    key_sha256 = hashlib.sha256(request_hash.encode("utf-8")).hexdigest()
    attempt_id = str(receipt.get("external_attempt_id") or "")
    first_run_id = str(receipt.get("external_first_execution_run_id") or "")
    bound_run_id = str(receipt.get("external_bound_run_id") or "")
    _require(
        handshake.get("schema_version") == "xinao.canonical_grok_transaction.started.v1"
        and handshake.get("transaction_key_sha256") == key_sha256
        and handshake.get("transaction_identity_sha256")
        == receipt.get("transaction_identity_sha256")
        and handshake.get("workflow_id") == receipt.get("external_workflow_id")
        and handshake.get("run_id") == bound_run_id
        and handshake.get("first_execution_run_id") == first_run_id
        and handshake.get("attempt_id") == attempt_id
        and handshake.get("execution_reused") == receipt.get("external_execution_reused"),
        "external handshake binding drifted",
    )
    _require(
        identity.get("schema_version") == "xinao.canonical_grok_transaction.identity.v1"
        and identity.get("transaction_key_sha256") == key_sha256
        and identity.get("payload_sha256") == receipt.get("payload_sha256")
        and identity.get("task_queue") == receipt.get("external_task_queue"),
        "external transaction identity drifted",
    )
    _require(
        execution.get("schema_version") == "xinao.canonical_grok_transaction.execution.v1"
        and execution.get("transaction_identity_sha256")
        == receipt.get("transaction_identity_sha256")
        and execution.get("workflow_id") == receipt.get("external_workflow_id")
        and execution.get("run_id") == bound_run_id
        and execution.get("first_execution_run_id") == first_run_id,
        "external execution binding drifted",
    )
    _require(
        attempt.get("schema_version") == "xinao.canonical_grok_transaction.attempt.v1"
        and attempt.get("attempt_id") == attempt_id
        and attempt.get("transaction_key_sha256") == key_sha256
        and outcome.get("schema_version") == "xinao.canonical_grok_transaction.attempt_outcome.v1"
        and outcome.get("status") == "accepted"
        and outcome.get("attempt_id") == attempt_id,
        "external attempt lifecycle drifted",
    )
    _require(
        result.get("attempt_id") == attempt_id
        and result.get("first_execution_run_id") == first_run_id
        and result.get("run_id") == bound_run_id
        and result.get("transaction_key_sha256") == key_sha256,
        "external result transaction binding drifted",
    )
    return list(paths.values())


def _attempt_file_names(files: Iterable[object]) -> set[str]:
    return {
        ntpath.basename(str(item.get("path") or "")) for item in files if isinstance(item, dict)
    }


def _portable_stem(value: object) -> str:
    return ntpath.splitext(ntpath.basename(str(value or "")))[0]


def _operation_route(lane: Mapping[str, Any]) -> tuple[str, str]:
    execution_location = lane.get("execution_location")
    if execution_location == DOCKER_EXECUTION_LOCATION:
        return DOCKER_EXECUTION_LOCATION, DOCKER_F4_MODEL
    if execution_location in (None, ""):
        return "legacy:acpx", LEGACY_ACPX_MODEL
    raise VerificationError(f"unsupported operation execution location: {execution_location}")


def _verify_attempt_manifest(
    pack: Path,
    lane: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> tuple[Path, dict[str, Any]]:
    manifest_entry = artifacts["manifest.json"]
    path = _bound_file(
        manifest_entry.get("uri"),
        manifest_entry.get("sha256"),
        expected_size=manifest_entry.get("size_bytes"),
        root=pack,
    )
    manifest = _load_object(path)
    operation_id = str(lane.get("operation_id") or "")
    _require(
        manifest.get("operation_id") == operation_id and manifest.get("request_id") == operation_id,
        "attempt manifest operation identity drifted",
    )
    _require(
        manifest.get("outcome") == "completed" and manifest.get("runner_exit_code") == 0,
        "attempt manifest is not a successful terminal run",
    )
    _require(
        manifest.get("requested_model") == LEGACY_ACPX_MODEL
        and manifest.get("requested_model_matches_spec") is True,
        "attempt manifest requested model drifted",
    )
    _require(
        manifest.get("session_model_evidence_valid") is True
        and manifest.get("raw_chain_of_thought_stored") is False,
        "attempt manifest model evidence or storage boundary failed",
    )
    files = manifest.get("files")
    _require(isinstance(files, list), "attempt manifest file list is missing")
    names = _attempt_file_names(files)
    _require(names == EXPECTED_MANIFEST_FILES, "attempt manifest file set drifted")
    for raw in files:
        _require(isinstance(raw, dict), "attempt manifest file entry is invalid")
        _bound_file(
            raw.get("path"),
            raw.get("sha256"),
            expected_size=raw.get("size_bytes"),
            root=pack,
        )
    return path, manifest


def _verify_model_identity(
    lane: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    for source in (lane, manifest):
        evidence = source.get("session_model_evidence")
        _require(isinstance(evidence, dict), "session model evidence is missing")
        available = evidence.get("availableModelIds")
        _require(
            source.get("session_model_evidence_valid") is True
            and evidence.get("source") == "acpx_runtime_status_after_turn"
            and evidence.get("requestedModel") == LEGACY_ACPX_MODEL
            and evidence.get("currentModelId") == LEGACY_ACPX_MODEL
            and isinstance(available, list)
            and LEGACY_ACPX_MODEL in available
            and bool(str(evidence.get("acpxRecordId") or ""))
            and bool(str(evidence.get("backendSessionId") or "")),
            f"session model evidence is not attributable to {LEGACY_ACPX_MODEL}",
        )
    _require(
        lane.get("session_model_evidence") == manifest.get("session_model_evidence"),
        "lane and attempt manifest disagree on session model evidence",
    )


def _verify_docker_model_identity(lane: Mapping[str, Any]) -> None:
    evidence = lane.get("session_model_evidence")
    _require(isinstance(evidence, dict), "Docker session model evidence is missing")
    available = evidence.get("availableModelIds")
    backend_models = evidence.get("backendModelIds")
    _require(
        lane.get("session_model_evidence_valid") is True
        and evidence.get("source") == "grok_cli_json_modelUsage"
        and evidence.get("requestedModel") == DOCKER_F4_MODEL
        and evidence.get("selectedSessionModel") == DOCKER_F4_MODEL
        and evidence.get("observedModelId") == DOCKER_F4_MODEL
        and evidence.get("modelUsageIds") == [DOCKER_F4_MODEL]
        and isinstance(available, list)
        and DOCKER_F4_MODEL in available
        and isinstance(backend_models, list)
        and backend_models == [DOCKER_F4_MODEL]
        and lane.get("observed_backend_models") == [DOCKER_F4_MODEL]
        and lane.get("model_identity_ok") is True
        and bool(str(evidence.get("backendSessionId") or "")),
        f"Docker session model evidence is not attributable to {DOCKER_F4_MODEL}",
    )


def _verify_docker_operation_spec(
    spec: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    operation_id: str,
    lane_id: str,
) -> None:
    result_schema = spec.get("result_json_schema")
    result_schema_sha256 = (
        hashlib.sha256(artifact_json_bytes(result_schema)).hexdigest()
        if isinstance(result_schema, dict)
        else ""
    )
    _require(
        spec.get("schema_version") == "xinao.grok.docker_native_cli.v1"
        and spec.get("operation_id") == operation_id
        and spec.get("lane_id") == lane_id
        and spec.get("contract_id") == "xinao.foundation.f4.readonly_lane.v1"
        and spec.get("write") is False
        and spec.get("model") == DOCKER_F4_MODEL
        and spec.get("allowed_tools") == ["read_file"]
        and spec.get("max_turns") is None
        and spec.get("result_format") == binding.get("result_format") == "json_object"
        and isinstance(result_schema, dict)
        and spec.get("result_json_schema_sha256")
        == binding.get("result_json_schema_sha256")
        == result_schema_sha256
        and spec.get("prompt_sha256") == binding.get("prompt_sha256"),
        "Docker operation-spec read-only/model contract drifted",
    )


def _verify_docker_operation(
    lane: Mapping[str, Any],
    binding: Mapping[str, Any],
    stage: str,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[Path], dict[str, Any]]:
    operation_id = str(lane.get("operation_id") or "")
    lane_id = str(lane.get("lane_id") or "")
    _require(
        set(artifacts) == EXPECTED_DOCKER_OPERATION_ARTIFACTS,
        "Docker operation artifact set drifted",
    )
    paths_by_name: dict[str, Path] = {}
    for name, raw in artifacts.items():
        _require(raw.get("operation_id") == operation_id, f"{name} operation identity drifted")
        paths_by_name[name] = _bound_file(
            raw.get("uri"),
            raw.get("sha256"),
            expected_size=raw.get("size_bytes"),
        )

    _verify_docker_model_identity(lane)

    spec_path = paths_by_name["operation-spec.json"]
    spec = _load_object(spec_path)
    _require(
        file_sha256(spec_path) == str(lane.get("operation_spec_sha256") or "").lower(),
        "Docker operation-spec hash binding drifted",
    )
    _verify_docker_operation_spec(
        spec,
        binding,
        operation_id=operation_id,
        lane_id=lane_id,
    )

    contract_path = paths_by_name["logical_contract.json"]
    receipt_path = paths_by_name["attempt_receipt.json"]
    identity_path = paths_by_name["cli_result.json"]
    contract = _load_object(contract_path)
    receipt = _load_object(receipt_path)
    identity = _load_object(identity_path)
    identity_model_usage = identity.get("modelUsage")
    _require(isinstance(identity_model_usage, dict), "Docker raw modelUsage is missing")
    identity_observed_models = sorted(
        str(model)
        for model, stats in identity_model_usage.items()
        if isinstance(stats, dict) and int(stats.get("modelCalls") or 0) > 0
    )
    embedded_contract = lane.get("cross_seam_logical_contract")
    embedded_receipt = lane.get("cross_seam_attempt_receipt")
    _require(contract == embedded_contract, "Docker logical contract artifact drifted")
    _require(receipt == embedded_receipt, "Docker attempt receipt artifact drifted")
    verdict = validate_attempt_receipt(
        contract,
        receipt,
        expected_consumer_id=GROK_DOCKER_CONSUMER_ID,
    )
    contract_sha256 = logical_contract_sha256(contract)
    receipt_observed = receipt.get("observed")
    receipt_invocations = receipt.get("invocations")
    _require(
        verdict.accepted
        and identity_observed_models == [DOCKER_F4_MODEL]
        and isinstance(receipt_observed, dict)
        and receipt_observed.get("model_id") == DOCKER_F4_MODEL
        and isinstance(receipt_invocations, list)
        and bool(receipt_invocations)
        and all(
            isinstance(invocation, dict) and invocation.get("observed_model") == DOCKER_F4_MODEL
            for invocation in receipt_invocations
        )
        and lane.get("cross_seam_contract_version") == LOGICAL_CONTRACT_VERSION
        and lane.get("cross_seam_attempt_receipt_version") == ATTEMPT_RECEIPT_VERSION
        and lane.get("cross_seam_contract_sha256") == contract_sha256
        and _same_path(lane.get("cross_seam_logical_contract_ref"), contract_path)
        and lane.get("cross_seam_logical_contract_artifact_sha256") == file_sha256(contract_path)
        and _same_path(lane.get("cross_seam_attempt_receipt_ref"), receipt_path)
        and lane.get("cross_seam_attempt_receipt_sha256") == file_sha256(receipt_path)
        and _same_path(lane.get("model_identity_ref"), identity_path)
        and lane.get("model_identity_sha256") == file_sha256(identity_path)
        and _same_path(receipt.get("provider_evidence_ref"), identity_path)
        and receipt.get("provider_evidence_sha256") == file_sha256(identity_path),
        "Docker common receipt or provider evidence binding drifted",
    )

    final_path = paths_by_name["final.txt"]
    response = _parse_result_object(final_path.read_text(encoding="utf-8"))
    final_sha256 = file_sha256(final_path)
    _require(
        response == _parse_result_object(str(lane.get("result_text") or ""))
        and _same_path(lane.get("final_ref"), final_path)
        and lane.get("result_text_sha256") == final_sha256
        and (receipt.get("output") or {}).get("content_sha256") == final_sha256,
        "Docker lane result text does not equal its common final artifact",
    )
    work_key = str(binding.get("work_key") or "")
    _require(response.get("work_key") == work_key, "operation result work key drifted")
    _require(
        isinstance(response.get("method_output"), dict)
        and response["method_output"].get("applied") is True
        and response["method_output"].get("stage") == stage
        and response["method_output"].get("work_key") == work_key,
        "operation method output is not bound to stage/work",
    )
    actor_field = {
        "PRODUCER": "producer_id",
        "CRITIQUE": "critic_id",
        "VERIFIER": "verifier_id",
    }[stage]
    _require(response.get(actor_field) == lane_id, "operation actor identity drifted")
    record = {
        "actor_id": lane_id,
        "final_ref": retained_path(final_path),
        "final_sha256": final_sha256,
        "operation_id": operation_id,
        "response": response,
        "stage": stage,
        "work_key": work_key,
    }
    return (
        record,
        list(paths_by_name.values()),
        {
            "operation_id": operation_id,
            "lane_id": lane_id,
            "stage": stage,
            "work_key": work_key,
            "model": DOCKER_F4_MODEL,
            "write": False,
            "execution_location": DOCKER_EXECUTION_LOCATION,
            "common_receipt_sha256": file_sha256(receipt_path),
        },
    )


def _verify_operation(
    pack: Path,
    lane: Mapping[str, Any],
    binding: Mapping[str, Any],
    stage: str,
) -> tuple[dict[str, Any], list[Path], dict[str, Any]]:
    operation_id = str(lane.get("operation_id") or "")
    lane_id = str(lane.get("lane_id") or "")
    _require(operation_id and lane_id, "operation or lane identity is missing")
    execution_location, expected_model = _operation_route(lane)
    expected = {
        "allowed_tools": ["read_file"],
        "contract_id": "xinao.foundation.f4.readonly_lane.v1",
        "model": expected_model,
        "observed_model": expected_model,
        "requested_model": expected_model,
        "write": False,
    }
    _require(
        all(lane.get(key) == value for key, value in expected.items()), "lane contract drifted"
    )
    if execution_location == DOCKER_EXECUTION_LOCATION:
        _require(
            lane.get("model_policy_id") == DOCKER_MODEL_POLICY_ID,
            "Docker model identity policy is stale",
        )
    _require(
        lane.get("ok") is True and lane.get("operation_state") == "completed",
        "lane did not complete successfully",
    )
    _require(
        binding.get("actor_id") == lane_id
        and binding.get("stage") == stage
        and binding.get("write") is False
        and binding.get("requested_model") == expected_model,
        "lane binding drifted",
    )
    raw_artifacts = lane.get("artifacts")
    _require(isinstance(raw_artifacts, list), "lane artifact list is missing")
    artifacts = {
        str(item.get("name") or ""): item for item in raw_artifacts if isinstance(item, dict)
    }
    if execution_location == DOCKER_EXECUTION_LOCATION:
        return _verify_docker_operation(lane, binding, stage, artifacts)
    _require(set(artifacts) == EXPECTED_OPERATION_ARTIFACTS, "operation artifact set drifted")
    paths: list[Path] = []
    for name, raw in artifacts.items():
        _require(raw.get("operation_id") == operation_id, f"{name} operation identity drifted")
        paths.append(
            _bound_file(
                raw.get("uri"),
                raw.get("sha256"),
                expected_size=raw.get("size_bytes"),
                root=pack,
            )
        )
    manifest_path, manifest = _verify_attempt_manifest(pack, lane, artifacts)
    _verify_model_identity(lane, manifest)
    spec_path = _resolve_ref(artifacts["operation-spec.json"].get("uri"))
    spec = _load_object(spec_path)
    _require(
        file_sha256(spec_path)
        == str(lane.get("operation_spec_sha256") or "").lower()
        == str(manifest.get("operation_spec_sha256") or "").lower(),
        "operation-spec hash binding drifted",
    )
    _require(
        spec.get("request_id") == operation_id
        and spec.get("contract_id") == "xinao.foundation.f4.readonly_lane.v1"
        and spec.get("write") is False
        and spec.get("model") == LEGACY_ACPX_MODEL
        and spec.get("allowed_tools") == ["read_file"]
        and spec.get("max_turns") == 1,
        "operation-spec read-only/model contract drifted",
    )
    final_path = _resolve_ref(artifacts["final.txt"].get("uri"))
    response = _parse_result_object(final_path.read_text(encoding="utf-8"))
    _require(
        response == _parse_result_object(str(lane.get("result_text") or "")),
        "lane result text does not equal final artifact",
    )
    work_key = str(binding.get("work_key") or "")
    _require(response.get("work_key") == work_key, "operation result work key drifted")
    _require(
        isinstance(response.get("method_output"), dict)
        and response["method_output"].get("applied") is True
        and response["method_output"].get("stage") == stage
        and response["method_output"].get("work_key") == work_key,
        "operation method output is not bound to stage/work",
    )
    actor_field = {
        "PRODUCER": "producer_id",
        "CRITIQUE": "critic_id",
        "VERIFIER": "verifier_id",
    }[stage]
    _require(response.get(actor_field) == lane_id, "operation actor identity drifted")
    record = {
        "actor_id": lane_id,
        "final_ref": retained_path(final_path),
        "final_sha256": file_sha256(final_path),
        "operation_id": operation_id,
        "response": response,
        "stage": stage,
        "work_key": work_key,
    }
    return (
        record,
        paths + [manifest_path],
        {
            "operation_id": operation_id,
            "lane_id": lane_id,
            "stage": stage,
            "work_key": work_key,
            "model": LEGACY_ACPX_MODEL,
            "write": False,
            "execution_location": execution_location,
        },
    )


def _verify_result_manifest(
    result: Mapping[str, Any],
    lanes: list[dict[str, Any]],
) -> Path:
    body = result.get("result")
    _require(isinstance(body, dict), "external result body is missing")
    fanin = body.get("grok_fanin")
    _require(isinstance(fanin, dict), "external result fan-in is missing")
    path = _bound_file(fanin.get("manifest_path"), fanin.get("manifest_sha256"))
    manifest = _load_object(path)
    persisted = manifest.get("lanes")
    _require(isinstance(persisted, list), "external fan-in manifest lanes are missing")
    by_id = {str(item.get("lane_id") or ""): item for item in lanes}
    _require(
        {str(item.get("lane_id") or "") for item in persisted if isinstance(item, dict)}
        == set(by_id),
        "external result and fan-in manifest lane sets differ",
    )
    for raw in persisted:
        _require(isinstance(raw, dict), "fan-in manifest lane is invalid")
        lane = by_id[str(raw.get("lane_id") or "")]
        _require(all(lane.get(key) == value for key, value in raw.items()), "fan-in lane drifted")
    return path


def _verify_operations(
    pack: Path,
    receipts: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, dict[str, Any]]], list[Path], list[dict[str, Any]], list[Path]]:
    stage_records: dict[str, dict[str, dict[str, Any]]] = {
        "PRODUCER": {},
        "CRITIQUE": {},
        "VERIFIER": {},
    }
    evidence: list[Path] = []
    operation_summary: list[dict[str, Any]] = []
    request_payload_paths: list[Path] = []
    operation_ids: set[str] = set()
    for receipt in receipts:
        receipt_path = _verify_receipt_file(pack, receipt)
        request_path, request = _verify_request(receipt)
        payload_path, payload = _verify_payload(receipt)
        result_path = _bound_file(
            receipt.get("result_ref"), receipt.get("result_sha256"), root=pack
        )
        result = _load_object(result_path)
        stage = str(receipt.get("research_stage") or "")
        bindings = payload.get("lane_bindings")
        _require(
            stage in stage_records and isinstance(bindings, dict), "payload stage/bindings invalid"
        )
        _require(
            payload.get("research_stage") == stage
            and request.get("payload_ref") == receipt.get("payload_ref")
            and request.get("payload_sha256") == receipt.get("payload_sha256"),
            "request/payload stage binding drifted",
        )
        capacity = payload.get("dynamic_capacity_decision")
        _require(isinstance(capacity, dict), "dynamic capacity decision is missing")
        _require(
            int(capacity.get("dispatch_width") or 0) == int(receipt.get("dispatch_width") or 0)
            and capacity.get("reason") == receipt.get("capacity_reason"),
            "receipt capacity decision drifted",
        )
        body = result.get("result")
        lanes = body.get("grok_lanes") if isinstance(body, dict) else None
        _require(isinstance(lanes, list), "external result lane list is missing")
        _require(
            len(lanes) == int(receipt.get("lane_count") or 0) == len(bindings),
            "external lane cardinality drifted",
        )
        _require(
            result.get("ok") is True
            and result.get("workflow_id") == receipt.get("external_workflow_id")
            and result.get("run_id") == receipt.get("external_bound_run_id")
            and result.get("worker_build_id") == receipt.get("worker_build_id")
            and result.get("worker_deployment_name") == receipt.get("worker_deployment_name"),
            "external result runtime identity drifted",
        )
        transaction_paths = _verify_transaction_receipt(pack, receipt, result)
        fanin_manifest_path = _verify_result_manifest(result, lanes)
        for lane in lanes:
            _require(isinstance(lane, dict), "external lane is invalid")
            lane_id = str(lane.get("lane_id") or "")
            binding = bindings.get(lane_id)
            _require(isinstance(binding, dict), "external lane has no payload binding")
            record, lane_paths, summary = _verify_operation(pack, lane, binding, stage)
            _require(record["operation_id"] not in operation_ids, "duplicate operation identity")
            operation_ids.add(record["operation_id"])
            _require(record["work_key"] not in stage_records[stage], "duplicate stage/work record")
            stage_records[stage][record["work_key"]] = record
            evidence.extend(lane_paths)
            operation_summary.append(summary)
        evidence.extend([receipt_path, result_path, fanin_manifest_path, *transaction_paths])
        request_payload_paths.extend([request_path, payload_path])
    _require(len(operation_ids) == 9, "live pack does not contain exactly nine operations")
    actual_operation_ids = {
        str(_load_object(path).get("operation_id") or _load_object(path).get("request_id") or "")
        for path in evidence
        if path.name == "operation-spec.json"
    }
    _require(actual_operation_ids == operation_ids, "operation-spec identity set drifted")
    return stage_records, evidence, operation_summary, request_payload_paths


def _verify_stage_bindings(
    records: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    work_sets = [set(records[stage]) for stage in ("PRODUCER", "CRITIQUE", "VERIFIER")]
    _require(work_sets[0] == work_sets[1] == work_sets[2], "stage work-key sets differ")
    _require(len(work_sets[0]) == 3, "expected exactly three closed work keys")
    producers: set[str] = set()
    critics: set[str] = set()
    verifiers: set[str] = set()
    for work_key in sorted(work_sets[0]):
        producer = records["PRODUCER"][work_key]
        critique = records["CRITIQUE"][work_key]
        verifier = records["VERIFIER"][work_key]
        p = producer["response"]
        c = critique["response"]
        v = verifier["response"]
        _require(p.get("status") == "VERIFIED", "producer did not verify")
        _require(
            c.get("verdict") == "APPROVED"
            and _same_path(c.get("target_artifact_ref"), producer["final_ref"])
            and str(c.get("target_artifact_hash") or "").lower() == producer["final_sha256"],
            "critique is not bound to the producer artifact",
        )
        _require(
            v.get("verdict") == "VERIFIED"
            and _same_path(v.get("target_artifact_ref"), producer["final_ref"])
            and str(v.get("target_artifact_hash") or "").lower() == producer["final_sha256"]
            and _same_path(v.get("target_critique_ref"), critique["final_ref"])
            and str(v.get("target_critique_hash") or "").lower() == critique["final_sha256"],
            "verification is not bound to producer and critique artifacts",
        )
        producers.add(str(producer["actor_id"]))
        critics.add(str(critique["actor_id"]))
        verifiers.add(str(verifier["actor_id"]))
    _require(
        producers.isdisjoint(critics)
        and producers.isdisjoint(verifiers)
        and critics.isdisjoint(verifiers),
        "producer, critic, and verifier identities overlap",
    )
    return {
        "closed_work_keys": sorted(work_sets[0]),
        "producer_ids": sorted(producers),
        "critic_ids": sorted(critics),
        "verifier_ids": sorted(verifiers),
    }


def _verify_fanin(
    fanin_refs: Iterable[Mapping[str, Any]],
    records: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> tuple[list[Path], list[dict[str, Any]]]:
    paths: list[Path] = []
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    all_work_keys: set[str] = set()
    for raw in fanin_refs:
        path = _bound_file(raw.get("fanin_ref"), raw.get("fanin_sha256"))
        value = _load_object(path)
        body = dict(value)
        content_hash = str(body.pop("content_sha256", "")).lower()
        _require(content_hash == canonical_sha256(body), "fan-in content hash drifted")
        _require(
            _portable_stem(retained_path(path)) == content_hash,
            "fan-in filename is not content addressed",
        )
        expected = {str(item) for item in value.get("expected_work_keys") or []}
        _require(expected and not expected & seen, "fan-in work groups overlap or are empty")
        seen |= expected
        all_work_keys |= expected
        _require(
            value.get("schema_version") == "xinao.deterministic_fan_in.v1"
            and value.get("completion_status") == "VERIFIED"
            and value.get("majority_vote_used") is False
            and set(value.get("accepted_work_keys") or []) == expected
            and set(value.get("resolved_work_keys") or []) == expected
            and not value.get("unresolved_work_keys")
            and not value.get("terminal_nonpositive_work_keys"),
            "fan-in is not an exact all-stage AND result",
        )
        _require(
            set(value.get("producer_ids") or [])
            == {records["PRODUCER"][key]["actor_id"] for key in expected}
            and set(value.get("critic_ids") or [])
            == {records["CRITIQUE"][key]["actor_id"] for key in expected}
            and set(value.get("verifier_ids") or [])
            == {records["VERIFIER"][key]["actor_id"] for key in expected},
            "fan-in actor identities do not match stage artifacts",
        )
        paths.append(path)
        summaries.append(
            {
                "content_sha256": content_hash,
                "expected_work_keys": sorted(expected),
                "majority_vote_used": False,
            }
        )
    _require(len(paths) == 2, "expected two deterministic fan-in artifacts")
    _require(all_work_keys == set(records["PRODUCER"]), "fan-in does not cover all work keys")
    return paths, summaries


async def _verify_temporal_histories(
    receipts: list[dict[str, Any]],
) -> tuple[list[Path], list[dict[str, Any]]]:
    for source_root in (REPO_ROOT, XINAO_SRC, DUAL_BRAIN_SRC):
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
    try:
        from temporalio.api.enums.v1 import EventType
        from temporalio.client import WorkflowHistory
        from temporalio.worker import Replayer
        from xinao_coordination.temporal.workflow import PROMOTED_WORKFLOWS
    except ImportError as exc:
        raise VerificationError(
            "Temporal replay dependencies are unavailable; use the canonical dual-brain venv"
        ) from exc

    replayer = Replayer(workflows=list(PROMOTED_WORKFLOWS))
    paths: list[Path] = []
    summaries: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for receipt in receipts:
        path = _bound_file(
            receipt.get("external_history_ref"),
            receipt.get("external_history_sha256"),
        )
        workflow_id = str(receipt.get("external_workflow_id") or "")
        run_id = str(receipt.get("external_terminal_run_id") or "")
        first_run_id = str(receipt.get("external_first_execution_run_id") or "")
        history = WorkflowHistory.from_json(workflow_id, _load_object(path))
        _require(bool(history.events), "external Temporal history is empty")
        first, last = history.events[0], history.events[-1]
        _require(
            first.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
            and last.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED,
            "external Temporal history is not a complete execution",
        )
        started = first.workflow_execution_started_event_attributes
        _require(
            started.workflow_type.name == "XinaoPromotedTaskWorkflowV1"
            and started.original_execution_run_id == first_run_id
            and run_id,
            "external Temporal history identity drifted",
        )
        replay = await replayer.replay_workflow(history, raise_on_replay_failure=False)
        _require(replay.replay_failure is None, "external Temporal history replay failed")
        identity = (workflow_id, run_id)
        _require(identity not in identities, "duplicate external Temporal execution")
        identities.add(identity)
        paths.append(path)
        summaries.append(
            {
                "event_count": len(history.events),
                "history_sha256": file_sha256(path),
                "run_id": run_id,
                "workflow_id": workflow_id,
                "workflow_type": started.workflow_type.name,
            }
        )
    _require(len(paths) == 6, "expected exactly six external Temporal histories")
    return paths, summaries


async def _verify_parent_history(
    report: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    try:
        from services.agent_runtime.foundation_continuous_workflow import (
            FoundationWaveChildWorkflowV1,
        )
        from services.agent_runtime.foundation_continuous_workflow_v2 import (
            FoundationContinuousWorkflowV2,
        )
        from temporalio.api.enums.v1 import EventType
        from temporalio.client import WorkflowHistory
        from temporalio.worker import Replayer
    except ImportError as exc:
        raise VerificationError(
            "Temporal parent-history replay dependencies are unavailable"
        ) from exc
    path = _bound_file(report.get("parent_history_ref"), report.get("parent_history_sha256"))
    workflow_id = str(report.get("parent_workflow_id") or "")
    run_id = str(report.get("parent_run_id") or "")
    history = WorkflowHistory.from_json(workflow_id, _load_object(path))
    _require(bool(history.events), "parent Temporal history is empty")
    first, last = history.events[0], history.events[-1]
    started = first.workflow_execution_started_event_attributes
    _require(
        first.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
        and last.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED
        and started.workflow_type.name == "FoundationContinuousWorkflowV2"
        and started.original_execution_run_id == run_id,
        "parent Temporal history identity or terminal event drifted",
    )
    replay = await Replayer(
        workflows=[FoundationContinuousWorkflowV2, FoundationWaveChildWorkflowV1]
    ).replay_workflow(history, raise_on_replay_failure=False)
    _require(replay.replay_failure is None, "parent Temporal history SDK replay failed")
    return path, {
        "event_count": len(history.events),
        "run_id": run_id,
        "sdk_replay": True,
        "workflow_id": workflow_id,
        "workflow_type": started.workflow_type.name,
    }


def _verify_restart_continuity(
    pack: Path,
    report: Mapping[str, Any],
) -> tuple[list[Path], dict[str, Any], list[Mapping[str, Any]]]:
    before_path = pack / "worker_restart" / "before_restart.json"
    restarted_path = pack / "worker_restart" / "restarted.json"
    before = _load_object(before_path)
    restarted = _load_object(restarted_path)
    terminal = report.get("terminal_state")
    _require(isinstance(terminal, dict), "terminal state is missing")
    before_closed = set(before.get("closed_work_keys") or [])
    terminal_closed = set(terminal.get("closed_work_keys") or [])
    _require(
        before.get("operation_id") == terminal.get("operation_id") == report.get("operation_id")
        and before.get("workflow_id")
        == terminal.get("workflow_id")
        == report.get("parent_workflow_id")
        and before.get("run_id") == terminal.get("run_id") == report.get("parent_run_id"),
        "worker restart changed parent execution identity",
    )
    _require(
        int(before.get("waves_completed") or 0) == 3
        and int(terminal.get("waves_completed") or 0) == 6
        and int(terminal.get("revision") or 0) > int(before.get("revision") or 0)
        and before_closed < terminal_closed
        and len(terminal_closed) == 3
        and terminal.get("status") == "STOPPED"
        and int(terminal.get("waves_failed") or 0) == 0,
        "worker restart did not preserve and advance parent state",
    )
    _require(
        restarted.get("schema_version") == "xinao.f4_v2_worker_restart.v1"
        and restarted.get("previous_identity")
        and restarted.get("current_identity")
        and restarted.get("previous_identity") != restarted.get("current_identity")
        and restarted.get("task_queue") == report.get("parent_task_queue"),
        "worker restart identity evidence drifted",
    )
    return (
        [before_path, restarted_path],
        {
            "closed_before": len(before_closed),
            "closed_after": len(terminal_closed),
            "revision_before": int(before.get("revision") or 0),
            "revision_after": int(terminal.get("revision") or 0),
            "waves_before": int(before.get("waves_completed") or 0),
            "waves_after": int(terminal.get("waves_completed") or 0),
        },
        [before.get("last_fanin") or {}, terminal.get("last_fanin") or {}],
    )


async def verify_live_pack(pack: Path) -> dict[str, Any]:
    pack = input_path(pack, expect="directory")
    _require(pack.is_dir(), f"live pack is missing: {pack}")
    manifest, manifest_path, manifest_files, artifact_set_hash = _verify_artifact_manifest(pack)
    report_path = _bound_file(
        manifest.get("report_ref"),
        manifest.get("report_sha256"),
        root=pack,
    )
    report = _load_object(report_path)
    _require(
        report.get("schema_version") == "xinao.f4_live_canary_report.v1"
        and report.get("status") == "VERIFIED",
        "live report schema/status drifted",
    )
    receipts = report.get("receipts")
    _require(isinstance(receipts, list) and len(receipts) == 6, "expected six live receipts")
    _require(all(isinstance(item, dict) for item in receipts), "live receipt is invalid")
    receipt_values = list(receipts)
    assertions: dict[str, dict[str, Any]] = {}
    assertions["artifact_manifest_exact_and_hash_bound"] = _assertion(
        "artifact_manifest_exact_and_hash_bound",
        [manifest_path],
        {"artifact_count": len(manifest_files), "artifact_set_sha256": artifact_set_hash},
    )
    assertions["report_hash_and_status_verified"] = _assertion(
        "report_hash_and_status_verified",
        [manifest_path, report_path],
        {"report_sha256": file_sha256(report_path), "status": report.get("status")},
    )

    # Verify provider identity and bound operation bytes before importing the
    # heavier Temporal replay environment.  A forged provider report must fail
    # for its own reason even when replay dependencies are unavailable.
    records, operation_paths, operation_summary, request_payload_paths = _verify_operations(
        pack, receipt_values
    )
    assertions["nine_operations_spec_result_manifest_bound"] = _assertion(
        "nine_operations_spec_result_manifest_bound",
        operation_paths + request_payload_paths,
        {"operation_count": len(operation_summary), "operations": operation_summary},
    )
    route_models = {
        str(item["execution_location"]): str(item["model"]) for item in operation_summary
    }
    assertions["all_operations_exact_route_models_read_only"] = _assertion(
        "all_operations_exact_route_models_read_only",
        operation_paths,
        {"operation_count": 9, "route_models": route_models, "write": False},
    )

    history_paths, history_summary = await _verify_temporal_histories(receipt_values)
    assertions["six_external_workflow_histories_replay"] = _assertion(
        "six_external_workflow_histories_replay",
        history_paths,
        {"history_count": len(history_summary), "histories": history_summary},
    )

    stages = [str(item.get("research_stage") or "") for item in receipt_values]
    widths = [int(item.get("dispatch_width") or 0) for item in receipt_values]
    reasons = [str(item.get("capacity_reason") or "") for item in receipt_values]
    _require(stages == EXPECTED_STAGES, "research stage sequence drifted")
    _require(widths == EXPECTED_WIDTHS, "dispatch width sequence drifted")
    _require(reasons == EXPECTED_CAPACITY_REASONS, "capacity reason sequence drifted")
    assertions["stage_width_capacity_sequence"] = _assertion(
        "stage_width_capacity_sequence",
        [report_path, *request_payload_paths],
        {"capacity_reasons": reasons, "stages": stages, "widths": widths},
    )

    identity_summary = _verify_stage_bindings(records)
    assertions["stage_binding_and_identity_separation"] = _assertion(
        "stage_binding_and_identity_separation",
        operation_paths,
        identity_summary,
    )

    restart_paths, restart_summary, fanin_refs = _verify_restart_continuity(pack, report)
    parent_history_path, parent_history_summary = await _verify_parent_history(report)
    assertions["worker_restart_continuity"] = _assertion(
        "worker_restart_continuity",
        [*restart_paths, parent_history_path, report_path],
        {**restart_summary, "parent_history": parent_history_summary},
    )

    fanin_paths, fanin_summary = _verify_fanin(fanin_refs, records)
    assertions["deterministic_fanin_without_majority_vote"] = _assertion(
        "deterministic_fanin_without_majority_vote",
        fanin_paths + operation_paths,
        {"fanin_count": len(fanin_paths), "fanins": fanin_summary},
    )

    _require(all(report.get("checks", {}).values()), "positive report contains a failed check")
    core = {
        "schema_version": SCHEMA_VERSION,
        "status": "VERIFIED",
        "verification_mode": "READ_ONLY_OFFLINE_REPLAY",
        "source_pack": retained_path(pack),
        "source_manifest_sha256": file_sha256(manifest_path),
        "source_report_sha256": file_sha256(report_path),
        "verifier_source_sha256": file_sha256(Path(__file__)),
        "assertion_count": len(assertions),
        "assertions": assertions,
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def write_verification(report: Mapping[str, Any], output_dir: Path) -> Path:
    digest = str(report.get("content_sha256") or "")
    _require(len(digest) == 64, "verification report is not content addressed")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{digest}.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        _require(path.read_text(encoding="utf-8") == payload, "verification output hash collision")
        return path
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir or args.pack.parent / f"{args.pack.name}-independent-verification"
    try:
        report = asyncio.run(verify_live_pack(args.pack))
        output = write_verification(report, output_dir)
    except VerificationError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "content_sha256": report["content_sha256"],
                "assertion_count": report["assertion_count"],
                "output": str(output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
