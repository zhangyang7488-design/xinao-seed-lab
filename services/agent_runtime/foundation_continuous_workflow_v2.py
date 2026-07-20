"""Evidence-bound V2 controller on the existing Temporal worker.

V1 stays byte-for-byte replayable for its open history.  V2 imports the
canonical F4 policy from ``xinao.foundation.research_factory`` and only adapts
filesystem evidence to Temporal activities.  It does not add a scheduler,
watchdog, resident host process, or second lifecycle clock.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping

from temporalio import activity, workflow
from temporalio.exceptions import ActivityError, ChildWorkflowError, TemporalError

from services.agent_runtime.foundation_continuous_workflow import (
    DEFAULT_EXTERNAL_MODEL,
    DEFAULT_EXTERNAL_PROVIDER_ID,
    DEFAULT_EXTERNAL_TASK_QUEUE,
    DEFAULT_RUNTIME_ROOT,
    PARENT_WORKFLOW_NAME,
    FoundationContinuousWorkflowV1,
    FoundationWaveChildWorkflowV1,
    _activity_options,
    _apply_control,
    _bounded_seconds,
    _canonical_hash,
    _parent_snapshot,
    _resolve_runtime_ref,
    _validate_control,
    _write_json_once,
    persist_foundation_state,
)

with workflow.unsafe.imports_passed_through():
    from xinao.foundation.f4_snapshot_runtime import retained_path
    from xinao.foundation.research_candidate_source import (
        compile_f4_canary_candidate_snapshot,
        compile_f4_canary_candidate_source,
    )
    from xinao.foundation.research_factory import (
        ResearchWorkItem,
        admit_work_item,
        canonical_work_key,
        compile_research_candidate_snapshot,
        compile_research_portfolio_allocation,
        deterministic_fan_in,
        project_allocated_ready_frontier,
        research_factory_schema_payloads,
        select_dynamic_capacity,
        source_origin_index,
        source_projection_hash,
        validate_method_registry,
        verify_research_factory_artifacts,
    )
    from xinao.foundation.research_weight import verify_versioned_object
    from xinao.foundation.selection_manifest import (
        IndependentExpectedSelectionDomainManifestVersion,
        compile_default_independent_selection_manifest,
    )

    from services.agent_runtime.execution_contract import (
        ATTEMPT_RECEIPT_VERSION,
        LOGICAL_CONTRACT_VERSION,
        artifact_json_bytes,
        logical_contract_sha256,
        validate_attempt_receipt,
    )
    from services.agent_runtime.grok_execution_contract_adapter import (
        GROK_DOCKER_CONSUMER_ID,
        expected_docker_grok_backend_models,
        grok_docker_model_identity_binding,
        validate_grok_session_model_evidence,
    )

PARENT_WORKFLOW_NAME_V2 = "FoundationContinuousWorkflowV2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
F4_ALLOWED_READ_TOOLS = frozenset(
    {
        "grep",
        "list_dir",
        "read_file",
        "search_tool",
        "web_fetch",
        "web_search",
    }
)
F4_READONLY_CONTRACT_ID = "xinao.foundation.f4.readonly_lane.v1"
F4_METHOD_EXECUTABLE_SCHEMA = "xinao.f4_prompted_method_executable.v1"
F4_METHOD_EVIDENCE_RULE = "F4_EVIDENCE_BOUND_CANARY:{stage}:{work_key_last_12}"
F4_METHOD_PROTOCOL_ID = "xinao.f4_evidence_bound_canary_protocol.v1"
F4_METHOD_PROTOCOL_CHECKS = frozenset(
    {
        "BUNDLE_EQ",
        "INPUT_SCHEMA_VALID",
        "OUTPUT_SCHEMA_VALID",
        "STAGE_EQ",
        "WORK_KEY_EQ",
        "METHOD_EVIDENCE_RULE",
        "UPSTREAM_EQ",
    }
)
F4_FAILURE_CONTRACT_ID = "xinao.f4_failure_contract.v1"
F4_NON_VERIFIED_OUTCOMES = frozenset(
    {
        "CHANGES_REQUESTED",
        "FAILED",
        "FALSIFIED",
        "NO_ACTION",
        "PARTIAL",
        "REJECTED",
    }
)
F4_CANARY_NEGATIVE_CONTROLS = F4_METHOD_PROTOCOL_CHECKS


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value.lower()) is not None


def _external_worker_cwd(frontier: Mapping[str, Any]) -> str:
    """Resolve the supervisor-selected host cwd before any external dispatch."""

    raw = str(frontier.get("external_worker_cwd") or "").strip()
    if not raw:
        raise ValueError("F4 frontier requires an explicit supervisor-selected external worker cwd")
    path = Path(raw).resolve()
    if not path.is_dir():
        raise ValueError(f"F4 external worker cwd does not exist: {path}")
    return str(path)


def _write_bytes_once(path: Path, raw: bytes) -> None:
    """Persist immutable content-addressed bytes without changing their digest."""

    if path.is_file():
        if path.read_bytes() != raw:
            raise RuntimeError(f"immutable artifact identity conflict: {path}")
        return
    if os.environ.get("XINAO_F4_SNAPSHOT_MANIFEST", "").strip():
        raise RuntimeError(f"snapshot replay cannot create an input artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def _read_method_json(
    runtime_root: Path,
    materials: Mapping[str, Any],
    role: str,
) -> dict[str, Any]:
    material = materials.get(role)
    if not isinstance(material, Mapping):
        raise ValueError(f"method material is missing: {role}")
    path = _resolve_runtime_ref(runtime_root, material.get("artifact_ref"))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"method material is not valid JSON: {role}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"method material must be a JSON object: {role}")
    return value


def _validate_method_core_materials(
    runtime_root: Path,
    method_id: str,
    materials: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the five non-canary artifacts as one executable contract."""

    from jsonschema import Draft202012Validator

    executable = _read_method_json(runtime_root, materials, "executable")
    input_schema = _read_method_json(runtime_root, materials, "input_schema")
    output_schema = _read_method_json(runtime_root, materials, "output_schema")
    protocol = _read_method_json(runtime_root, materials, "verification_protocol")
    failure = _read_method_json(runtime_root, materials, "failure_contract")
    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator.check_schema(output_schema)
    if (
        executable.get("schema_version") != F4_METHOD_EXECUTABLE_SCHEMA
        or executable.get("method_id") != method_id
        or executable.get("method_evidence_rule") != F4_METHOD_EVIDENCE_RULE
        or not isinstance(executable.get("instructions"), list)
        or not executable.get("instructions")
        or not all(isinstance(value, str) and value.strip() for value in executable["instructions"])
    ):
        raise ValueError("method executable contract is invalid")
    checks = protocol.get("checks")
    if (
        protocol.get("protocol_id") != F4_METHOD_PROTOCOL_ID
        or not isinstance(checks, list)
        or len(checks) != len(set(map(str, checks)))
        or set(map(str, checks)) != F4_METHOD_PROTOCOL_CHECKS
    ):
        raise ValueError("method verification protocol is invalid")
    outcomes = failure.get("non_verified_outcomes")
    if (
        failure.get("contract_id") != F4_FAILURE_CONTRACT_ID
        or failure.get("on_binding_failure") != "REJECT_VERIFIED_OUTPUT"
        or not isinstance(outcomes, list)
        or set(map(str, outcomes)) != F4_NON_VERIFIED_OUTCOMES
    ):
        raise ValueError("method failure contract is invalid")
    return {
        "method_id": method_id,
        "protocol_id": F4_METHOD_PROTOCOL_ID,
        "protocol_checks": sorted(F4_METHOD_PROTOCOL_CHECKS),
    }


def _method_execution_verifier_sha256() -> str:
    return _canonical_hash(
        {
            "validate_execution": inspect.getsource(_validate_method_execution),
            "validate_input": inspect.getsource(_validate_method_input),
            "validate_core": inspect.getsource(_validate_method_core_materials),
            "read_material": inspect.getsource(_read_method_json),
            "executable_schema": F4_METHOD_EXECUTABLE_SCHEMA,
            "evidence_rule": F4_METHOD_EVIDENCE_RULE,
            "protocol_id": F4_METHOD_PROTOCOL_ID,
            "protocol_checks": sorted(F4_METHOD_PROTOCOL_CHECKS),
            "failure_contract_id": F4_FAILURE_CONTRACT_ID,
        }
    )


def _validate_method_contract_materials(
    runtime_root: Path,
    method_id: str,
    materials: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate all six artifacts and executed negative-control receipts."""

    core = _validate_method_core_materials(runtime_root, method_id, materials)
    canary = _read_method_json(runtime_root, materials, "canary_evidence")
    controls = canary.get("negative_controls")
    if (
        canary.get("status") != "VERIFIED"
        or canary.get("method_id") != method_id
        or canary.get("executable_sha256") != materials["executable"].get("sha256")
        or canary.get("input_schema_sha256") != materials["input_schema"].get("sha256")
        or canary.get("output_schema_sha256") != materials["output_schema"].get("sha256")
        or canary.get("verification_protocol_sha256")
        != materials["verification_protocol"].get("sha256")
        or canary.get("failure_contract_sha256") != materials["failure_contract"].get("sha256")
        or not isinstance(controls, list)
    ):
        raise ValueError("method canary evidence is invalid")
    observed_controls: set[str] = set()
    expected_verifier_sha256 = _method_execution_verifier_sha256()
    replay_binding = {
        "method_id": method_id,
        "method_admission_hash": "1" * 64,
        "method_executable_ref": materials["executable"].get("artifact_ref"),
        "method_executable_sha256": materials["executable"].get("sha256"),
        "method_material_bundle_sha256": "2" * 64,
        "materials": materials,
    }
    replayed_controls = generate_f4_method_negative_control_receipts(
        runtime_root,
        replay_binding,
    )
    for control in controls:
        if not isinstance(control, Mapping):
            raise TypeError("method canary negative control must be an object")
        check_id = str(control.get("check_id") or "")
        if check_id in observed_controls or control.get("status") != "REJECTED":
            raise ValueError("method canary negative control is invalid")
        evidence_path = _resolve_runtime_ref(runtime_root, control.get("evidence_ref"))
        expected = str(control.get("sha256") or "")
        if (
            not evidence_path.is_file()
            or not _valid_sha256(expected)
            or hashlib.sha256(evidence_path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("method canary negative control evidence drifted")
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("method canary negative control is not JSON") from exc
        if (
            not isinstance(evidence, dict)
            or evidence.get("check_id") != check_id
            or evidence.get("status") != "REJECTED"
            or evidence.get("expected_rejection") is not True
            or not _valid_sha256(evidence.get("input_sha256"))
            or evidence.get("observed_exception_type") not in {"ValueError", "ValidationError"}
            or not str(evidence.get("observed_exception_message") or "")
            or evidence.get("verifier_source_sha256") != expected_verifier_sha256
            or evidence != replayed_controls.get(check_id)
        ):
            raise ValueError("method canary negative control receipt is invalid")
        observed_controls.add(check_id)
    if observed_controls != F4_CANARY_NEGATIVE_CONTROLS:
        raise ValueError("method canary negative control set is incomplete")
    return {
        **core,
        "negative_controls": sorted(observed_controls),
        "verifier_source_sha256": expected_verifier_sha256,
    }


def _validate_method_registry_artifacts(
    runtime_root: Path,
    registrations: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Prove each admitted method hash from the actual runtime-root bytes."""

    normalized = validate_method_registry(registrations)
    materialized: dict[str, dict[str, Any]] = {}
    for method_id, raw in registrations.items():
        resolved = raw.get("resolved_content_hashes")
        if not isinstance(resolved, Mapping) or not resolved:
            raise ValueError(f"method admission has no resolved artifacts: {method_id}")
        registration = raw.get("registration")
        if not isinstance(registration, Mapping):
            raise ValueError(f"method admission registration is missing: {method_id}")
        fields = {
            "executable": ("executable_ref", "executable_sha256"),
            "input_schema": ("input_schema_ref", "input_schema_sha256"),
            "output_schema": ("output_schema_ref", "output_schema_sha256"),
            "verification_protocol": (
                "verification_protocol_ref",
                "verification_protocol_sha256",
            ),
            "failure_contract": (
                "failure_contract_ref",
                "failure_contract_sha256",
            ),
            "canary_evidence": (
                "canary_evidence_ref",
                "canary_evidence_sha256",
            ),
        }
        materials: dict[str, dict[str, str]] = {}
        observed_refs: set[str] = set()
        for role, (ref_field, hash_field) in fields.items():
            ref = str(registration.get(ref_field) or "")
            expected = str(registration.get(hash_field) or "")
            if ref in observed_refs or not _valid_sha256(expected):
                raise ValueError(f"method artifact identity is invalid: {method_id}:{role}")
            path = _resolve_runtime_ref(runtime_root, ref)
            if not path.is_file():
                raise ValueError(f"method artifact does not exist: {path}")
            artifact_raw = path.read_bytes()
            observed = hashlib.sha256(artifact_raw).hexdigest()
            if observed != expected or resolved.get(ref) != expected:
                raise ValueError(f"method artifact hash drifted: {path}")
            try:
                content_text = artifact_raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("method artifacts must be UTF-8 text") from exc
            snapshot = (
                runtime_root
                / "state"
                / "foundation_continuous"
                / "method_artifacts"
                / f"{observed}.artifact"
            )
            _write_bytes_once(snapshot, artifact_raw)
            materials[role] = {
                "artifact_ref": retained_path(snapshot),
                "sha256": observed,
                "content_text": content_text,
            }
            observed_refs.add(ref)
        if len(observed_refs) != len(fields):
            raise ValueError("method artifact refs must be distinct")
        contract_verification = _validate_method_contract_materials(
            runtime_root,
            method_id,
            materials,
        )
        bundle_core = {
            role: {
                "artifact_ref": value["artifact_ref"],
                "sha256": value["sha256"],
            }
            for role, value in sorted(materials.items())
        }
        materialized[method_id] = {
            "method_admission_hash": str(raw.get("admission_sha256") or ""),
            "materials": materials,
            "material_bundle_sha256": _canonical_hash(bundle_core),
            "contract_verification": contract_verification,
        }
    return normalized, materialized


def _verify_method_binding_snapshots(
    runtime_root: Path,
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-read immutable method snapshots at result collection time."""

    materials = binding.get("materials")
    if not isinstance(materials, Mapping) or set(materials) != {
        "executable",
        "input_schema",
        "output_schema",
        "verification_protocol",
        "failure_contract",
        "canary_evidence",
    }:
        raise ValueError("method binding material set is incomplete")
    normalized: dict[str, dict[str, str]] = {}
    for role, value in sorted(materials.items()):
        if not isinstance(value, Mapping):
            raise ValueError("method binding material must be an object")
        path = _resolve_runtime_ref(runtime_root, value.get("artifact_ref"))
        artifact_ref = retained_path(path)
        expected = str(value.get("sha256") or "")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("method binding snapshot hash drifted")
        normalized[str(role)] = {
            "artifact_ref": artifact_ref,
            "sha256": expected,
        }
    bundle_sha256 = _canonical_hash(normalized)
    if bundle_sha256 != binding.get("method_material_bundle_sha256"):
        raise ValueError("method binding bundle hash drifted")
    contract_verification = _validate_method_contract_materials(
        runtime_root,
        str(binding.get("method_id") or ""),
        materials,
    )
    return {
        "materials": normalized,
        "method_material_bundle_sha256": bundle_sha256,
        "contract_verification": contract_verification,
    }


def _validate_method_input(
    runtime_root: Path,
    binding: Mapping[str, Any],
    method_input: object,
) -> None:
    """Validate the actual stage input against the admitted immutable schema."""

    materials = binding.get("materials")
    if not isinstance(materials, Mapping):
        raise ValueError("method material binding is missing")
    schema = _read_method_json(runtime_root, materials, "input_schema")
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(method_input)


def _validate_method_execution(
    runtime_root: Path,
    binding: Mapping[str, Any],
    *,
    method_input: Mapping[str, Any],
    expected_method_input: Mapping[str, Any],
    method_output: object,
    response: Mapping[str, Any],
    stage: str,
    work_key: str,
) -> dict[str, Any]:
    """Run the admitted F4 checks instead of trusting a prompt-level claim."""

    from jsonschema import Draft202012Validator

    materials = binding.get("materials")
    if not isinstance(materials, Mapping):
        raise ValueError("method material binding is missing")
    _validate_method_core_materials(
        runtime_root,
        str(binding.get("method_id") or ""),
        materials,
    )
    for field in (
        "method_admission_hash",
        "method_executable_ref",
        "method_executable_sha256",
        "method_material_bundle_sha256",
    ):
        if str(response.get(field) or "") != str(binding.get(field) or ""):
            raise ValueError("method execution bundle binding does not match admission")
    if method_input != expected_method_input:
        raise ValueError("method input does not match stage dependencies")
    method_input_sha256 = _canonical_hash(method_input)
    if response.get("method_input_sha256") != method_input_sha256:
        raise ValueError("method execution input hash does not match dispatch")
    _validate_method_input(runtime_root, binding, method_input)
    output_schema = _read_method_json(runtime_root, materials, "output_schema")
    Draft202012Validator.check_schema(output_schema)
    Draft202012Validator(output_schema).validate(method_output)
    if not isinstance(method_output, Mapping):
        raise TypeError("method output must be an object")
    if method_output.get("applied") is not True:
        raise ValueError("method output did not apply the executable")
    if method_output.get("stage") != stage:
        raise ValueError("method output stage does not match dispatch")
    if method_output.get("work_key") != work_key:
        raise ValueError("method output work key does not match dispatch")
    executable = _read_method_json(runtime_root, materials, "executable")
    expected_evidence = F4_METHOD_EVIDENCE_RULE.format(
        stage=stage,
        work_key_last_12=work_key[-12:],
    )
    if method_output.get("method_evidence") != expected_evidence:
        raise ValueError("method output does not satisfy executable evidence rule")
    return {
        "method_input_sha256": method_input_sha256,
        "method_output_sha256": _canonical_hash(method_output),
        "protocol_id": F4_METHOD_PROTOCOL_ID,
        "protocol_checks": sorted(F4_METHOD_PROTOCOL_CHECKS),
        "method_evidence": expected_evidence,
        "executable_sha256": str(materials["executable"].get("sha256") or ""),
        "executable_schema_version": executable["schema_version"],
    }


def _build_method_input(
    *,
    stage: str,
    work_key: str,
    actor_id: str,
    method_binding: Mapping[str, Any],
    work_item_binding: Mapping[str, Any],
    producer: Mapping[str, Any],
    critique: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile the exact machine-validated input for one F4 stage."""

    return {
        "schema_version": "xinao.f4_method_input.v1",
        "work_key": work_key,
        "stage": stage,
        "actor_id": actor_id,
        "method_id": str(method_binding.get("method_id") or ""),
        "method_admission_hash": str(method_binding.get("method_admission_hash") or ""),
        "method_material_bundle_sha256": str(
            method_binding.get("method_material_bundle_sha256") or ""
        ),
        "work_item_content_sha256": str(work_item_binding.get("work_item_content_sha256") or ""),
        "upstream": {
            "producer_ref": str(producer.get("artifact_ref") or ""),
            "producer_sha256": str(producer.get("artifact_hash") or ""),
            "critique_ref": str(critique.get("critique_artifact_ref") or ""),
            "critique_sha256": str(critique.get("critique_artifact_hash") or ""),
        },
    }


def _f4_lane_result_json_schema(
    *,
    stage: str,
    lane_id: str,
    work_key: str,
    method_binding: Mapping[str, Any],
    method_input: Mapping[str, Any],
    method_input_sha256: str,
) -> dict[str, Any]:
    """Compile the exact structured-output contract submitted to Grok CLI."""

    properties: dict[str, Any] = {
        "work_key": {"const": work_key},
        "method_admission_hash": {"const": method_binding["method_admission_hash"]},
        "method_executable_ref": {"const": method_binding["method_executable_ref"]},
        "method_executable_sha256": {"const": method_binding["method_executable_sha256"]},
        "method_material_bundle_sha256": {"const": method_binding["method_material_bundle_sha256"]},
        "method_input_sha256": {"const": method_input_sha256},
        "method_output": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "applied": {"const": True},
                "stage": {"const": stage},
                "work_key": {"const": work_key},
                "method_evidence": {
                    "const": F4_METHOD_EVIDENCE_RULE.format(
                        stage=stage,
                        work_key_last_12=work_key[-12:],
                    )
                },
            },
            "required": ["applied", "stage", "work_key", "method_evidence"],
        },
    }
    if stage == "PRODUCER":
        properties.update(
            {
                "producer_id": {"const": lane_id},
                "status": {"enum": ["VERIFIED", "PARTIAL", "FAILED", "FALSIFIED", "NO_ACTION"]},
                "claim_refs": {"type": "array", "items": {"type": "string"}},
            }
        )
    elif stage == "CRITIQUE":
        properties.update(
            {
                "critic_id": {"const": lane_id},
                "target_artifact_ref": {"const": method_input["upstream"]["producer_ref"]},
                "target_artifact_hash": {"const": method_input["upstream"]["producer_sha256"]},
                "verdict": {"enum": ["APPROVED", "CHANGES_REQUESTED", "REJECTED"]},
                "finding_refs": {"type": "array", "items": {"type": "string"}},
            }
        )
    elif stage == "VERIFIER":
        properties.update(
            {
                "verifier_id": {"const": lane_id},
                "target_artifact_ref": {"const": method_input["upstream"]["producer_ref"]},
                "target_artifact_hash": {"const": method_input["upstream"]["producer_sha256"]},
                "target_critique_ref": {"const": method_input["upstream"]["critique_ref"]},
                "target_critique_hash": {"const": method_input["upstream"]["critique_sha256"]},
                "verdict": {"enum": ["VERIFIED", "PARTIAL", "REJECTED"]},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            }
        )
    else:
        raise ValueError(f"unsupported F4 stage: {stage}")
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": sorted(properties),
    }


def generate_f4_method_negative_control_receipts(
    runtime_root: Path,
    binding: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Execute every F4 protocol negative against the production checker."""

    from jsonschema import ValidationError

    work_key = "a" * 64
    base_input = {
        "schema_version": "xinao.f4_method_input.v1",
        "work_key": work_key,
        "stage": "PRODUCER",
        "actor_id": "negative-control-producer",
        "method_id": str(binding.get("method_id") or ""),
        "method_admission_hash": str(binding.get("method_admission_hash") or "1" * 64),
        "method_material_bundle_sha256": str(
            binding.get("method_material_bundle_sha256") or "2" * 64
        ),
        "work_item_content_sha256": "3" * 64,
        "upstream": {
            "producer_ref": "",
            "producer_sha256": "",
            "critique_ref": "",
            "critique_sha256": "",
        },
    }
    base_output = {
        "applied": True,
        "stage": "PRODUCER",
        "work_key": work_key,
        "method_evidence": (f"F4_EVIDENCE_BOUND_CANARY:PRODUCER:{work_key[-12:]}"),
    }
    base_response = {
        field: binding.get(field)
        for field in (
            "method_admission_hash",
            "method_executable_ref",
            "method_executable_sha256",
            "method_material_bundle_sha256",
        )
    }
    base_response["method_input_sha256"] = _canonical_hash(base_input)

    def clone(value: object) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    cases: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]] = {}
    response = clone(base_response)
    response["method_material_bundle_sha256"] = "0" * 64
    cases["BUNDLE_EQ"] = (
        clone(base_input),
        clone(base_input),
        {"response": response, "output": clone(base_output)},
        "bundle binding",
    )
    invalid_input = clone(base_input)
    invalid_input.pop("actor_id")
    response = clone(base_response)
    response["method_input_sha256"] = _canonical_hash(invalid_input)
    cases["INPUT_SCHEMA_VALID"] = (
        invalid_input,
        clone(invalid_input),
        {"response": response, "output": clone(base_output)},
        "required property",
    )
    invalid_output = clone(base_output)
    invalid_output.pop("applied")
    cases["OUTPUT_SCHEMA_VALID"] = (
        clone(base_input),
        clone(base_input),
        {"response": clone(base_response), "output": invalid_output},
        "required property",
    )
    invalid_output = clone(base_output)
    invalid_output["stage"] = "VERIFIER"
    cases["STAGE_EQ"] = (
        clone(base_input),
        clone(base_input),
        {"response": clone(base_response), "output": invalid_output},
        "stage does not match",
    )
    invalid_output = clone(base_output)
    invalid_output["work_key"] = "b" * 64
    cases["WORK_KEY_EQ"] = (
        clone(base_input),
        clone(base_input),
        {"response": clone(base_response), "output": invalid_output},
        "work key does not match",
    )
    invalid_output = clone(base_output)
    invalid_output["method_evidence"] = "invalid-method-evidence"
    cases["METHOD_EVIDENCE_RULE"] = (
        clone(base_input),
        clone(base_input),
        {"response": clone(base_response), "output": invalid_output},
        "evidence rule",
    )
    invalid_input = clone(base_input)
    invalid_input["upstream"]["producer_ref"] = "unexpected:producer"
    invalid_input["upstream"]["producer_sha256"] = "4" * 64
    response = clone(base_response)
    response["method_input_sha256"] = _canonical_hash(invalid_input)
    cases["UPSTREAM_EQ"] = (
        invalid_input,
        clone(base_input),
        {"response": response, "output": clone(base_output)},
        "stage dependencies",
    )

    verifier_sha256 = _method_execution_verifier_sha256()
    receipts: dict[str, dict[str, Any]] = {}
    for check_id, (method_input, expected_input, values, expected_message) in cases.items():
        try:
            _validate_method_execution(
                runtime_root,
                binding,
                method_input=method_input,
                expected_method_input=expected_input,
                method_output=values["output"],
                response=values["response"],
                stage="PRODUCER",
                work_key=work_key,
            )
        except (ValueError, TypeError, ValidationError) as exc:
            if expected_message not in str(exc):
                raise AssertionError(
                    f"negative control {check_id} rejected for the wrong reason: {exc}"
                ) from exc
            receipts[check_id] = {
                "check_id": check_id,
                "status": "REJECTED",
                "input_sha256": _canonical_hash(method_input),
                "expected_rejection": True,
                "observed_exception_type": type(exc).__name__,
                "observed_exception_message": str(exc),
                "verifier_source_sha256": verifier_sha256,
            }
        else:
            raise AssertionError(f"negative control unexpectedly passed: {check_id}")
    return receipts


def _verify_operation_spec(
    path: Path,
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove the registered operation spec contains the exact submitted task."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("operation spec must be a JSON object")
    if value.get("schema_version") == "xinao.grok.docker_native_cli.v1":
        task_prompt_sha256 = str(value.get("prompt_sha256") or "")
        execution_prompt_sha256 = str(value.get("execution_prompt_sha256") or "")
        if task_prompt_sha256 != expected.get("prompt_sha256") or not _valid_sha256(
            execution_prompt_sha256
        ):
            raise ValueError("Docker operation spec prompt binding drifted")
        checks = {
            "model": expected.get("requested_model"),
            "contract_id": expected.get("contract_id"),
            "write": expected.get("write"),
            "allowed_tools": expected.get("allowed_tools"),
        }
        if any(value.get(field) != wanted for field, wanted in checks.items()):
            raise ValueError("Docker operation spec lane contract drifted")
        if expected.get("permission_mode") != "approve-reads" or value.get("write") is not False:
            raise ValueError("Docker operation spec F4 read-only permission drifted")
        result_schema = value.get("result_json_schema")
        if (
            value.get("result_format") != expected.get("result_format")
            or not isinstance(result_schema, dict)
            or hashlib.sha256(artifact_json_bytes(result_schema)).hexdigest()
            != expected.get("result_json_schema_sha256")
            or value.get("result_json_schema_sha256") != expected.get("result_json_schema_sha256")
        ):
            raise ValueError("Docker operation spec structured-output contract drifted")
        return {
            "task_prompt_sha256": task_prompt_sha256,
            "full_prompt_sha256": execution_prompt_sha256,
        }
    full_prompt = str(value.get("prompt") or "")
    marker = "Task:\n"
    if marker not in full_prompt:
        raise ValueError("operation spec does not contain the task prompt marker")
    task_prompt = full_prompt.split(marker, 1)[1]
    task_prompt_sha256 = hashlib.sha256(task_prompt.encode("utf-8")).hexdigest()
    full_prompt_sha256 = hashlib.sha256(full_prompt.encode("utf-8")).hexdigest()
    if (
        task_prompt_sha256 != expected.get("prompt_sha256")
        or value.get("task_prompt_sha256") != task_prompt_sha256
        or value.get("full_prompt_sha256") != full_prompt_sha256
    ):
        raise ValueError("operation spec prompt binding drifted")
    checks = {
        "model": expected.get("requested_model"),
        "contract_id": expected.get("contract_id"),
        "write": expected.get("write"),
        "permission_mode": expected.get("permission_mode"),
        "allowed_tools": expected.get("allowed_tools"),
    }
    if any(value.get(field) != wanted for field, wanted in checks.items()):
        raise ValueError("operation spec lane contract drifted")
    return {
        "task_prompt_sha256": task_prompt_sha256,
        "full_prompt_sha256": full_prompt_sha256,
    }


def _verify_docker_common_lane_receipt(
    runtime_root: Path,
    lane: Mapping[str, Any],
    artifacts_by_name: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Independently bind Docker-native output to the common execution receipt."""

    required = {
        "logical_contract.json",
        "attempt_receipt.json",
        "cli_result.json",
        "operation-spec.json",
        "session_model_evidence.json",
        "final.txt",
    }
    if not required.issubset(artifacts_by_name):
        raise ValueError("Docker Grok lane common evidence artifacts are incomplete")
    logical_contract = lane.get("cross_seam_logical_contract")
    attempt_receipt = lane.get("cross_seam_attempt_receipt")
    if not isinstance(logical_contract, dict) or not isinstance(attempt_receipt, dict):
        raise TypeError("Docker Grok lane common contract or receipt is missing")
    verdict = validate_attempt_receipt(
        logical_contract,
        attempt_receipt,
        expected_consumer_id=GROK_DOCKER_CONSUMER_ID,
    )
    contract_sha256 = logical_contract_sha256(logical_contract)
    if not (
        verdict.accepted
        and lane.get("cross_seam_contract_version") == LOGICAL_CONTRACT_VERSION
        and lane.get("cross_seam_attempt_receipt_version") == ATTEMPT_RECEIPT_VERSION
        and lane.get("cross_seam_contract_sha256") == contract_sha256
    ):
        raise ValueError("Docker Grok lane common receipt was rejected")

    def artifact(name: str) -> tuple[Path, str]:
        item = artifacts_by_name[name]
        return Path(str(item["path"])).resolve(), str(item["sha256"])

    contract_path, contract_artifact_sha256 = artifact("logical_contract.json")
    receipt_path, receipt_sha256 = artifact("attempt_receipt.json")
    identity_path, identity_sha256 = artifact("cli_result.json")
    session_evidence_path, session_evidence_sha256 = artifact("session_model_evidence.json")
    operation_spec_path, operation_spec_sha256 = artifact("operation-spec.json")
    final_path, final_sha256 = artifact("final.txt")
    try:
        contract_on_disk = json.loads(contract_path.read_text(encoding="utf-8"))
        receipt_on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
        session_evidence_on_disk = json.loads(session_evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Docker Grok common evidence artifact is unreadable") from exc

    def same_ref(raw: object, expected_path: Path) -> bool:
        try:
            return _resolve_runtime_ref(runtime_root, raw).resolve() == expected_path
        except (OSError, ValueError):
            return False

    result_text = str(lane.get("result_text") or "")
    if not (
        contract_on_disk == logical_contract
        and receipt_on_disk == attempt_receipt
        and same_ref(lane.get("cross_seam_logical_contract_ref"), contract_path)
        and lane.get("cross_seam_logical_contract_artifact_sha256") == contract_artifact_sha256
        and same_ref(lane.get("cross_seam_attempt_receipt_ref"), receipt_path)
        and lane.get("cross_seam_attempt_receipt_sha256") == receipt_sha256
        and same_ref(lane.get("model_identity_ref"), identity_path)
        and lane.get("model_identity_sha256") == identity_sha256
        and session_evidence_on_disk == lane.get("session_model_evidence")
        and same_ref(lane.get("session_model_evidence_ref"), session_evidence_path)
        and lane.get("session_model_evidence_sha256") == session_evidence_sha256
        and same_ref(lane.get("operation_spec_ref"), operation_spec_path)
        and lane.get("operation_spec_sha256") == operation_spec_sha256
        and same_ref(lane.get("final_ref"), final_path)
        and lane.get("result_text_sha256") == final_sha256
        and hashlib.sha256(result_text.encode("utf-8")).hexdigest() == final_sha256
        and final_path.read_text(encoding="utf-8") == result_text
        and attempt_receipt.get("provider_evidence_ref")
        == str(lane.get("model_identity_ref") or "")
        and attempt_receipt.get("provider_evidence_sha256") == identity_sha256
        and (attempt_receipt.get("output") or {}).get("content_sha256") == final_sha256
    ):
        raise ValueError("Docker Grok lane common artifact binding drifted")
    return {
        "contract_sha256": contract_sha256,
        "contract_artifact_sha256": contract_artifact_sha256,
        "attempt_receipt_sha256": receipt_sha256,
        "provider_evidence_sha256": identity_sha256,
        "session_model_evidence_sha256": session_evidence_sha256,
        "operation_spec_sha256": operation_spec_sha256,
        "final_sha256": final_sha256,
    }


def _verify_lane_domain_bindings(
    runtime_root: Path,
    binding: Mapping[str, Any],
) -> None:
    _, work_item, _ = _read_bound_object(
        runtime_root,
        binding.get("work_item_ref"),
        binding.get("work_item_sha256"),
    )
    ResearchWorkItem.model_validate(work_item)
    if _canonical_hash(work_item) != binding.get("work_item_content_sha256"):
        raise ValueError("F4 work-item snapshot content drifted")
    _, active_surface, _ = _read_bound_object(
        runtime_root,
        binding.get("active_research_surface_ref"),
        binding.get("active_research_surface_sha256"),
    )
    _, portfolio_policy, _ = _read_bound_object(
        runtime_root,
        binding.get("research_portfolio_policy_ref"),
        binding.get("research_portfolio_policy_sha256"),
    )
    _, research_question, _ = _read_bound_object(
        runtime_root,
        binding.get("research_question_ref"),
        binding.get("research_question_sha256"),
    )
    _, candidate_snapshot, _ = _read_bound_object(
        runtime_root,
        binding.get("research_candidate_snapshot_ref"),
        binding.get("research_candidate_snapshot_sha256"),
    )
    _, portfolio_allocation, _ = _read_bound_object(
        runtime_root,
        binding.get("research_portfolio_allocation_ref"),
        binding.get("research_portfolio_allocation_sha256"),
    )
    if (
        not verify_versioned_object(active_surface)
        or active_surface.get("content_sha256")
        != binding.get("active_research_surface_content_sha256")
        or not verify_versioned_object(portfolio_policy)
        or portfolio_policy.get("content_sha256")
        != binding.get("research_portfolio_policy_content_sha256")
        or portfolio_policy.get("active_surface_ref") != active_surface.get("content_sha256")
        or not verify_versioned_object(research_question)
        or research_question.get("object_type") != "ResearchQuestion"
        or research_question.get("content_sha256")
        != binding.get("research_question_content_sha256")
        or not verify_versioned_object(candidate_snapshot)
        or candidate_snapshot.get("object_type") != "ResearchCandidateSnapshot"
        or candidate_snapshot.get("content_sha256")
        != binding.get("research_candidate_snapshot_content_sha256")
        or candidate_snapshot.get("research_question_ref")
        != research_question.get("content_sha256")
        or candidate_snapshot.get("active_surface_ref") != active_surface.get("content_sha256")
        or not verify_versioned_object(portfolio_allocation)
        or portfolio_allocation.get("object_type") != "ResearchPortfolioAllocation"
        or portfolio_allocation.get("content_sha256")
        != binding.get("research_portfolio_allocation_content_sha256")
        or portfolio_allocation.get("active_surface_ref") != active_surface.get("content_sha256")
        or portfolio_allocation.get("policy_ref") != portfolio_policy.get("content_sha256")
        or portfolio_allocation.get("candidate_snapshot_ref")
        != candidate_snapshot.get("content_sha256")
    ):
        raise ValueError("F4 research surface binding drifted")


def _read_bound_object(
    runtime_root: Path,
    ref: object,
    expected_sha256: object,
) -> tuple[Path, dict[str, Any], str]:
    path = _resolve_runtime_ref(runtime_root, ref)
    if not path.is_file():
        raise ValueError(f"bound object does not exist: {path}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not _valid_sha256(expected_sha256) or digest != str(expected_sha256).lower():
        raise ValueError(f"bound object hash mismatch: {path}")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"bound object must be a JSON object: {path}")
    return path, value, digest


def _closure_milestone(
    runtime_root: Path,
    frontier: Mapping[str, Any],
) -> dict[str, Any] | None:
    refs = (
        frontier.get("foundation_closure_report_ref"),
        frontier.get("foundation_closure_report_sha256"),
        frontier.get("foundation_closure_verification_ref"),
        frontier.get("foundation_closure_verification_sha256"),
        frontier.get("blueprint_snapshot_ref"),
        frontier.get("blueprint_snapshot_sha256"),
    )
    if not all(refs):
        return None
    report_path, report, report_file_hash = _read_bound_object(
        runtime_root,
        refs[0],
        refs[1],
    )
    verification_path, verification, verification_file_hash = _read_bound_object(
        runtime_root,
        refs[2],
        refs[3],
    )
    blueprint_path, _, blueprint_file_hash = _read_bound_object(
        runtime_root,
        refs[4],
        refs[5],
    )
    from xinao.foundation.closure import (
        FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
        verify_foundation_closure_report,
    )

    replay = verify_foundation_closure_report(report, blueprint_path=blueprint_path)
    recorded_hash = str(report.get("artifact_hash") or "").lower()
    report_body = dict(report)
    report_body.pop("artifact_hash", None)
    verifier_id = str(report.get("independent_verifier_id") or "")
    checks = {
        "report_schema": report.get("schema_version") == FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
        "report_verified": report.get("status") == "VERIFIED",
        "report_execution_ready": report.get("foundation_execution_ready") is True,
        "report_not_globally_closed": report.get("foundation_closed") is False,
        "formal_research_not_allowed": report.get("formal_research_allowed") is False,
        "formal_gate_closed": report.get("formal_research_gate") == "CLOSED",
        "legacy_gate_unused": report.get("legacy_a_g_gate_used") is False,
        "manual_override_unused": report.get("manual_override_used") is False,
        "report_hash_replays": _valid_sha256(recorded_hash)
        and _canonical_hash(report_body) == recorded_hash,
        "verification_schema": verification.get("schema_version")
        == "xinao.foundation_closure_verification.v1",
        "verification_replays": verification == replay,
        "verification_ok": replay.get("ok") is True,
        "verification_execution_ready": replay.get("foundation_execution_ready") is True,
        "verification_not_globally_closed": replay.get("foundation_closed") is False,
        "verification_artifact_hash_bound": str(replay.get("recorded_artifact_hash") or "").lower()
        == recorded_hash,
        "independent_verifier_bound": bool(verifier_id),
    }
    if not all(checks.values()):
        failed = ",".join(key for key, passed in checks.items() if not passed)
        raise ValueError(f"foundation closure proof rejected: {failed}")
    return {
        "action": "MILESTONE",
        "reason": "independently_verified_foundation_execution_ready_report",
        "foundation_closure_report_ref": str(report_path),
        "foundation_closure_report_sha256": report_file_hash,
        "foundation_closure_artifact_hash": recorded_hash,
        "foundation_closure_verification_ref": str(verification_path),
        "foundation_closure_verification_sha256": verification_file_hash,
        "foundation_closure_verifier_id": verifier_id,
        "blueprint_snapshot_ref": str(blueprint_path),
        "blueprint_snapshot_sha256": blueprint_file_hash,
        "checks": checks,
        "wait_seconds": _bounded_seconds(frontier.get("wait_seconds"), default=300),
    }


def _reconcile_wait_reason(
    frontier: Mapping[str, Any],
    *,
    milestone: Mapping[str, Any] | None,
    ready_keys: list[str],
    width: int,
) -> str:
    if ready_keys and not width:
        return "CAPACITY_BACKPRESSURE"
    if milestone is None and frontier.get("foundation_execution_ready") is True:
        return "BARE_FOUNDATION_EXECUTION_READY_REJECTED"
    if milestone is None and frontier.get("foundation_closed") is True:
        return "DEPRECATED_BARE_FOUNDATION_CLOSED_REJECTED"
    return "NO_READY_WORK"


def _replace_placeholders(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        return value
    if isinstance(value, list):
        return [_replace_placeholders(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, replacements) for key, item in value.items()}
    return value


@activity.defn(name="xinao.foundation.v2.verify_roll_forward")
def verify_roll_forward_manifest_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify the one-time V1 STOP -> V2 ownership handoff."""

    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT))
    manifest_path, manifest, manifest_hash = _read_bound_object(
        runtime_root,
        payload.get("manifest_ref"),
        payload.get("manifest_sha256"),
    )
    if manifest.get("schema_version") != "xinao.foundation_roll_forward.v1_to_v2":
        raise ValueError("roll-forward manifest schema is invalid")
    if str(manifest.get("successor_operation_id") or "") != str(payload.get("operation_id") or ""):
        raise ValueError("roll-forward successor operation identity mismatch")
    if int(manifest.get("owner_generation") or 0) != int(payload.get("owner_generation") or 0):
        raise ValueError("roll-forward owner generation mismatch")
    _, final_state, final_state_hash = _read_bound_object(
        runtime_root,
        manifest.get("predecessor_final_state_ref"),
        manifest.get("predecessor_final_state_sha256"),
    )
    history_path = _resolve_runtime_ref(
        runtime_root,
        manifest.get("predecessor_history_ref"),
    )
    history_raw = history_path.read_bytes()
    history_hash = hashlib.sha256(history_raw).hexdigest()
    if history_hash != str(manifest.get("predecessor_history_sha256") or ""):
        raise ValueError("roll-forward predecessor history hash mismatch")
    workflow_code_path = Path(__file__).with_name("foundation_continuous_workflow.py")
    workflow_code_hash = hashlib.sha256(workflow_code_path.read_bytes()).hexdigest()
    if (
        not _valid_sha256(manifest.get("predecessor_workflow_code_sha256"))
        or str(manifest.get("predecessor_workflow_code_sha256") or "").lower() != workflow_code_hash
    ):
        raise ValueError("roll-forward predecessor V1 workflow code hash mismatch")

    predecessor_workflow_id = str(manifest.get("predecessor_workflow_id") or "")
    predecessor_run_id = str(manifest.get("predecessor_run_id") or "")
    try:
        from temporalio.api.enums.v1 import EventType
        from temporalio.client import WorkflowHistory

        history_value = json.loads(history_raw.decode("utf-8"))
        temporal_history = WorkflowHistory.from_json(
            predecessor_workflow_id,
            history_value,
        )
        events = temporal_history.events
        if not events:
            raise ValueError("history has no events")
        first = events[0]
        last = events[-1]
        if first.event_type != EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED:
            raise ValueError("history does not start a workflow execution")
        if last.event_type != EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED:
            raise ValueError("history does not end in a completed workflow execution")
        started = first.workflow_execution_started_event_attributes
        if started.workflow_type.name != PARENT_WORKFLOW_NAME:
            raise ValueError("history workflow type is not V1")
        if started.original_execution_run_id != predecessor_run_id:
            raise ValueError("history run identity does not match the predecessor")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"roll-forward Temporal history is invalid: {exc}") from exc

    try:
        from temporalio.worker import Replayer

        asyncio.run(
            Replayer(
                workflows=[
                    FoundationContinuousWorkflowV1,
                    FoundationWaveChildWorkflowV1,
                ]
            ).replay_workflow(temporal_history)
        )
    except Exception as exc:
        raise ValueError("roll-forward Temporal history replay failed") from exc
    _, replay, replay_hash = _read_bound_object(
        runtime_root,
        manifest.get("predecessor_replay_ref"),
        manifest.get("predecessor_replay_sha256"),
    )
    stop_operation_id = str(manifest.get("stop_operation_id") or "")
    stop_records = [
        record
        for record in final_state.get("control_audit") or []
        if isinstance(record, dict)
        and record.get("operation_id") == stop_operation_id
        and record.get("action") == "STOP"
    ]
    checks = {
        "predecessor_workflow_id": predecessor_workflow_id
        == str(final_state.get("workflow_id") or ""),
        "predecessor_run_id": predecessor_run_id == str(final_state.get("run_id") or ""),
        "predecessor_stopped": final_state.get("status") == "STOPPED",
        "predecessor_has_no_current_wave": final_state.get("current_wave") is None,
        "predecessor_stop_audit_exact": len(stop_records) == 1,
        "predecessor_replay_schema": replay.get("schema_version")
        == "xinao.temporal_replay_proof.v1",
        "predecessor_replay_type": replay.get("proof_type") == "TEMPORAL_SDK_REPLAYER",
        "predecessor_replay_ok": replay.get("ok") is True,
        "predecessor_replay_workflow_type": replay.get("workflow_type") == PARENT_WORKFLOW_NAME,
        "predecessor_replay_workflow_id": replay.get("workflow_id") == predecessor_workflow_id,
        "predecessor_replay_run_id": replay.get("run_id") == predecessor_run_id,
        "predecessor_replay_history_bound": replay.get("history_sha256") == history_hash,
        "predecessor_replay_code_bound": replay.get("workflow_code_sha256") == workflow_code_hash,
        "predecessor_replay_event_count": replay.get("event_count") == len(events),
    }
    if not all(checks.values()):
        failed = ",".join(key for key, passed in checks.items() if not passed)
        raise ValueError(f"roll-forward manifest rejected: {failed}")
    return {
        "ok": True,
        "manifest_ref": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "predecessor_final_state_sha256": final_state_hash,
        "predecessor_history_sha256": history_hash,
        "predecessor_history_event_count": len(events),
        "predecessor_workflow_code_sha256": workflow_code_hash,
        "predecessor_replay_sha256": replay_hash,
        "checks": checks,
    }


@activity.defn(name="xinao.foundation.v2.reconcile")
def reconcile_foundation_frontier_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply canonical dedup and current capacity to the actual lane payload."""

    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT))
    frontier_path, frontier, frontier_hash = _read_bound_object(
        runtime_root,
        payload.get("frontier_ref"),
        payload.get("frontier_sha256"),
    )
    graph_path, graph, graph_file_hash = _read_bound_object(
        runtime_root,
        frontier.get("source_dependency_graph_ref"),
        frontier.get("source_dependency_graph_sha256"),
    )
    origins, graph_content_hash = source_origin_index(graph)
    observation_path, observation, observation_hash = _read_bound_object(
        runtime_root,
        frontier.get("capacity_observation_ref"),
        frontier.get("capacity_observation_sha256"),
    )
    if observation.get("schema_version") != "xinao.capacity_observation.v1":
        raise ValueError("capacity observation schema is invalid")
    if observation.get("verified_canary") is not True:
        raise ValueError("capacity observation is not canary verified")
    _, selection_manifest_raw, _ = _read_bound_object(
        runtime_root,
        frontier.get("selection_manifest_ref"),
        frontier.get("selection_manifest_sha256"),
    )
    selection_manifest = IndependentExpectedSelectionDomainManifestVersion.model_validate(
        selection_manifest_raw
    )
    current_selection_manifest = compile_default_independent_selection_manifest()
    if selection_manifest != current_selection_manifest:
        raise ValueError("selection manifest does not equal the current canonical compiler output")
    factory_manifest_path, factory_manifest, factory_manifest_file_hash = _read_bound_object(
        runtime_root,
        frontier.get("research_factory_manifest_ref"),
        frontier.get("research_factory_manifest_sha256"),
    )
    factory_verification = verify_research_factory_artifacts(
        research_factory_schema_payloads(),
        pinned_manifest=factory_manifest,
        expected_manifest_sha256=str(factory_manifest.get("content_sha256") or ""),
    )
    _, method_registry, _ = _read_bound_object(
        runtime_root,
        frontier.get("method_registry_ref"),
        frontier.get("method_registry_sha256"),
    )
    registrations = method_registry.get("registrations")
    if not isinstance(registrations, dict) or not registrations:
        raise ValueError("verified method registry is empty")
    _, method_materials = _validate_method_registry_artifacts(
        runtime_root,
        registrations,
    )
    active_surface_path, active_surface, active_surface_file_hash = _read_bound_object(
        runtime_root,
        frontier.get("active_research_surface_ref"),
        frontier.get("active_research_surface_sha256"),
    )
    portfolio_policy_path, portfolio_policy, portfolio_policy_file_hash = _read_bound_object(
        runtime_root,
        frontier.get("research_portfolio_policy_ref"),
        frontier.get("research_portfolio_policy_sha256"),
    )
    if active_surface.get(
        "object_type"
    ) != "ActiveResearchSurfaceVersion" or not verify_versioned_object(active_surface):
        raise ValueError("F4 active research surface is not a verified F3 object")
    if (
        portfolio_policy.get("object_type") != "ResearchPortfolioPolicyVersion"
        or not verify_versioned_object(portfolio_policy)
        or portfolio_policy.get("active_surface_ref") != active_surface.get("content_sha256")
    ):
        raise ValueError("F4 research portfolio policy is not bound to active surface")
    research_surface_binding = {
        "active_research_surface_ref": retained_path(active_surface_path),
        "active_research_surface_sha256": active_surface_file_hash,
        "active_research_surface_content_sha256": str(active_surface["content_sha256"]),
        "research_portfolio_policy_ref": retained_path(portfolio_policy_path),
        "research_portfolio_policy_sha256": portfolio_policy_file_hash,
        "research_portfolio_policy_content_sha256": str(portfolio_policy["content_sha256"]),
    }

    question_path, research_question, question_file_hash = _read_bound_object(
        runtime_root,
        frontier.get("research_question_ref"),
        frontier.get("research_question_sha256"),
    )
    frontier_schema = str(frontier.get("schema_version") or "")
    if frontier_schema == "xinao.foundation_continuous_frontier.v3":
        if "ready_frontier" in frontier:
            raise ValueError("strict frontier forbids caller-provided ready_frontier")
        source_snapshot_path, candidate_source_snapshot, source_snapshot_file_hash = (
            _read_bound_object(
                runtime_root,
                frontier.get("research_candidate_source_snapshot_ref"),
                frontier.get("research_candidate_source_snapshot_sha256"),
            )
        )
        source_entries = candidate_source_snapshot.get("candidate_entries")
        if not isinstance(source_entries, list) or not source_entries:
            raise ValueError("strict candidate source snapshot is empty")
        first_entry = source_entries[0]
        if not isinstance(first_entry, dict):
            raise TypeError("strict candidate source entry must be an object")
        first_work_item = ResearchWorkItem.model_validate(first_entry.get("work_item"))
        method_id = str(research_question.get("method_id") or "")
        current_source = compile_f4_canary_candidate_source(
            active_research_surface=active_surface,
            selection_manifest=selection_manifest,
            method_registry={"registrations": registrations},
            method_id=method_id,
            source_dependency_graph=graph,
            world_snapshot_hash=first_work_item.world_snapshot_hash,
            knowledge_cutoff=first_work_item.knowledge_cutoff,
        )
        if (
            research_question != current_source["research_question"]
            or candidate_source_snapshot != current_source["candidate_source_snapshot"]
        ):
            raise ValueError(
                "strict candidate source does not match the current 13-family compiler"
            )
        snapshot_path, candidate_snapshot, snapshot_file_hash = _read_bound_object(
            runtime_root,
            frontier.get("research_candidate_snapshot_ref"),
            frontier.get("research_candidate_snapshot_sha256"),
        )
        current_snapshot = compile_f4_canary_candidate_snapshot(
            research_question=research_question,
            candidate_source_snapshot=candidate_source_snapshot,
            active_research_surface=active_surface,
            selection_manifest=selection_manifest,
            method_registry={"registrations": registrations},
            method_id=method_id,
            source_dependency_graph=graph,
        )
        if candidate_snapshot != current_snapshot:
            raise ValueError(
                "strict research candidate snapshot does not match its generated source"
            )
        frontier_binding_mode = "STRICT_F3_SURFACE_SOURCE_BOUND"
    elif frontier_schema == "xinao.foundation_continuous_frontier.v2":
        raw_ready = frontier.get("ready_frontier")
        if not isinstance(raw_ready, list):
            raise TypeError("ready_frontier must be a list")
        snapshot_path, candidate_snapshot, snapshot_file_hash = _read_bound_object(
            runtime_root,
            frontier.get("research_candidate_snapshot_ref"),
            frontier.get("research_candidate_snapshot_sha256"),
        )
        current_snapshot = compile_research_candidate_snapshot(
            raw_ready,
            research_question=research_question,
            active_surface=active_surface,
            selection_manifest=selection_manifest.model_dump(mode="json"),
            method_registry=registrations,
            source_dependency_graph=graph,
        )
        if (
            not verify_versioned_object(candidate_snapshot)
            or candidate_snapshot.get("object_type") != "ResearchCandidateSnapshot"
            or candidate_snapshot != current_snapshot
        ):
            raise ValueError(
                "research candidate snapshot does not match its complete bound question"
            )
        frontier_binding_mode = "LEGACY_UNBOUND"
    else:
        raise ValueError("foundation frontier schema is not an admitted v2/v3 version")
    allocation_path, portfolio_allocation, allocation_file_hash = _read_bound_object(
        runtime_root,
        frontier.get("research_portfolio_allocation_ref"),
        frontier.get("research_portfolio_allocation_sha256"),
    )
    current_allocation = compile_research_portfolio_allocation(
        candidate_snapshot,
        active_surface=active_surface,
        portfolio_policy=portfolio_policy,
        source_dependency_graph=graph,
    )
    if (
        not verify_versioned_object(portfolio_allocation)
        or portfolio_allocation.get("object_type") != "ResearchPortfolioAllocation"
        or portfolio_allocation != current_allocation
    ):
        raise ValueError("research portfolio allocation does not match the canonical compiler")
    if frontier_binding_mode == "STRICT_F3_SURFACE_SOURCE_BOUND":
        rows_by_candidate = {
            str(row["candidate_id"]): row
            for row in candidate_snapshot.get("candidate_rows") or []
            if isinstance(row, dict)
        }
        raw_ready = [
            dict(rows_by_candidate[str(row["candidate_id"])]["entry"])
            for row in portfolio_allocation.get("allocations") or []
        ]
    if [_canonical_hash(entry) for entry in raw_ready] != portfolio_allocation.get(
        "ordered_entry_sha256s"
    ):
        raise ValueError("ready frontier is not the allocated canonical order")
    research_surface_binding.update(
        {
            "frontier_binding_mode": frontier_binding_mode,
            "research_question_ref": retained_path(question_path),
            "research_question_sha256": question_file_hash,
            "research_question_content_sha256": str(research_question["content_sha256"]),
            "research_candidate_snapshot_ref": retained_path(snapshot_path),
            "research_candidate_snapshot_sha256": snapshot_file_hash,
            "research_candidate_snapshot_content_sha256": str(candidate_snapshot["content_sha256"]),
            "research_portfolio_allocation_ref": retained_path(allocation_path),
            "research_portfolio_allocation_sha256": allocation_file_hash,
            "research_portfolio_allocation_content_sha256": str(
                portfolio_allocation["content_sha256"]
            ),
            "ready_frontier_sha256": str(portfolio_allocation["ready_frontier_sha256"]),
        }
    )
    if frontier_binding_mode == "STRICT_F3_SURFACE_SOURCE_BOUND":
        research_surface_binding.update(
            {
                "research_candidate_source_snapshot_ref": retained_path(source_snapshot_path),
                "research_candidate_source_snapshot_sha256": (source_snapshot_file_hash),
                "research_candidate_source_snapshot_content_sha256": str(
                    candidate_source_snapshot["content_sha256"]
                ),
            }
        )
    items: list[ResearchWorkItem] = []
    lane_templates_by_key: dict[str, dict[str, dict[str, Any]]] = {}
    work_items_by_key: dict[str, ResearchWorkItem] = {}
    work_item_bindings: dict[str, dict[str, str]] = {}
    for raw in raw_ready:
        if not isinstance(raw, dict):
            raise TypeError("ready frontier entry must be an object")
        item = ResearchWorkItem.model_validate(raw.get("work_item"))
        admit_work_item(
            item,
            selection_manifest=selection_manifest,
            method_registry=registrations,
        )
        lane_templates = raw.get("lane_templates")
        if not isinstance(lane_templates, dict) or set(lane_templates) != {
            "PRODUCER",
            "CRITIQUE",
            "VERIFIER",
        }:
            raise ValueError("ready frontier requires producer/critique/verifier lanes")
        if not all(
            isinstance(lane, dict) and str(lane.get("lane_id") or "")
            for lane in lane_templates.values()
        ):
            raise ValueError("ready frontier stage lane identity is missing")
        for stage_name, lane in lane_templates.items():
            if lane.get("write") is not False:
                raise ValueError("F4 research lanes must explicitly set write=false")
            allowed_tools = lane.get("allowed_tools")
            if not isinstance(allowed_tools, list) or not allowed_tools:
                raise ValueError("F4 research lane allowed_tools must be explicit")
            if set(map(str, allowed_tools)) - F4_ALLOWED_READ_TOOLS:
                raise ValueError("F4 research lane requested a non-read tool")
            prompt = str(lane.get("prompt") or "")
            required_tokens = {
                "PRODUCER": ("{{WORK_KEY}}",),
                "CRITIQUE": (
                    "{{WORK_KEY}}",
                    "{{PRODUCER_ARTIFACT_REF}}",
                    "{{PRODUCER_ARTIFACT_HASH}}",
                ),
                "VERIFIER": (
                    "{{WORK_KEY}}",
                    "{{PRODUCER_ARTIFACT_REF}}",
                    "{{PRODUCER_ARTIFACT_HASH}}",
                    "{{CRITIQUE_ARTIFACT_REF}}",
                    "{{CRITIQUE_ARTIFACT_HASH}}",
                ),
            }[stage_name]
            if any(token not in prompt for token in required_tokens):
                raise ValueError("F4 lane prompt is missing an evidence binding")
            if "method_output" in prompt or "method_evidence" in prompt:
                raise ValueError("F4 lane template must not prefill the method execution result")
        work_key = canonical_work_key(
            item,
            source_origin_by_ref=origins,
            source_projection_hash=source_projection_hash(
                graph,
                (item.source_ref, *item.source_dependency_refs),
            ),
        )
        declared = str(raw.get("work_key") or "")
        if declared and declared != work_key:
            raise ValueError("declared work key does not match canonical work identity")
        items.append(item)
        work_items_by_key[work_key] = item
        work_item_payload = item.model_dump(mode="json")
        work_item_content_sha256 = _canonical_hash(work_item_payload)
        work_item_path = (
            runtime_root
            / "state"
            / "foundation_continuous"
            / "work_items"
            / f"{work_item_content_sha256}.json"
        )
        _write_json_once(work_item_path, work_item_payload)
        work_item_bindings[work_key] = {
            "work_item_ref": retained_path(work_item_path),
            "work_item_sha256": hashlib.sha256(work_item_path.read_bytes()).hexdigest(),
            "work_item_content_sha256": work_item_content_sha256,
        }
        lane_templates_by_key.setdefault(
            work_key,
            {stage: dict(lane) for stage, lane in lane_templates.items()},
        )

    deduped = project_allocated_ready_frontier(
        portfolio_allocation,
        candidate_snapshot=candidate_snapshot,
        closed_work_keys=payload.get("closed_work_keys") or [],
        in_flight_work_keys=payload.get("in_flight_work_keys") or [],
    )
    ready_keys = list(deduped["ready_work_keys"])
    width = 0
    active_keys = [str(value) for value in payload.get("batch_expected_work_keys") or []]
    stage = str(payload.get("next_stage") or "PRODUCER").upper()
    if stage not in {"PRODUCER", "CRITIQUE", "VERIFIER"}:
        raise ValueError("next research stage is invalid")
    if active_keys:
        if any(key not in lane_templates_by_key for key in active_keys):
            raise ValueError("active batch work key is no longer present in frontier")
        selected = active_keys
        capacity = dict(payload.get("batch_capacity_decision") or {})
        if int(capacity.get("dispatch_width") or 0) != len(selected):
            raise ValueError("active batch width drifted from its capacity decision")
    else:
        capacity_input = {
            **observation,
            "ready_count": len(ready_keys),
            "queue_depth": max(
                int(observation.get("queue_depth") or 0),
                len(ready_keys),
            ),
            "previous_width": int(payload.get("previous_width") or 1),
            "succeeded": int(payload.get("succeeded") or 0),
            "failed": int(payload.get("failed") or 0),
            "partial": bool(payload.get("partial")),
        }
        capacity = select_dynamic_capacity(capacity_input)
        capacity["observation_ref"] = retained_path(observation_path)
        capacity["observation_sha256"] = observation_hash
        width = int(capacity["dispatch_width"])
        selected = ready_keys[:width]

    if selected:
        template_path, template, template_hash = _read_bound_object(
            runtime_root,
            frontier.get("payload_template_ref"),
            frontier.get("payload_template_sha256"),
        )
        prior_records = payload.get("batch_stage_records") or {}
        if not isinstance(prior_records, dict):
            raise TypeError("batch_stage_records must be an object")
        lanes: list[dict[str, Any]] = []
        lane_ids: list[str] = []
        lane_bindings: dict[str, dict[str, Any]] = {}
        method_bindings: dict[str, dict[str, Any]] = {}
        external_model = str(frontier.get("external_model") or DEFAULT_EXTERNAL_MODEL)
        external_worker_cwd = _external_worker_cwd(frontier)
        for key in selected:
            item = work_items_by_key[key]
            method_material = method_materials[item.method_id]
            executable_material = method_material["materials"]["executable"]
            method_binding = {
                "method_id": item.method_id,
                "method_admission_hash": item.method_admission_hash,
                "method_registration_hash": item.method_registration_hash,
                "method_executable_ref": str(executable_material["artifact_ref"]),
                "method_executable_sha256": str(executable_material["sha256"]),
                "method_material_bundle_sha256": str(method_material["material_bundle_sha256"]),
                "materials": method_material["materials"],
            }
            method_bindings[key] = method_binding
            work_item_binding = work_item_bindings[key]
            producer = (prior_records.get("PRODUCER") or {}).get(key) or {}
            critique = (prior_records.get("CRITIQUE") or {}).get(key) or {}
            replacements = {
                "{{WORK_KEY}}": key,
                "{{METHOD_ADMISSION_HASH}}": method_binding["method_admission_hash"],
                "{{METHOD_EXECUTABLE_REF}}": method_binding["method_executable_ref"],
                "{{METHOD_EXECUTABLE_SHA256}}": method_binding["method_executable_sha256"],
                "{{METHOD_MATERIAL_BUNDLE_SHA256}}": method_binding[
                    "method_material_bundle_sha256"
                ],
                "{{PRODUCER_ARTIFACT_REF}}": str(producer.get("artifact_ref") or ""),
                "{{PRODUCER_ARTIFACT_HASH}}": str(producer.get("artifact_hash") or ""),
                "{{CRITIQUE_ARTIFACT_REF}}": str(critique.get("critique_artifact_ref") or ""),
                "{{CRITIQUE_ARTIFACT_HASH}}": str(critique.get("critique_artifact_hash") or ""),
            }
            if stage in {"CRITIQUE", "VERIFIER"} and not replacements["{{PRODUCER_ARTIFACT_HASH}}"]:
                raise ValueError("critique/verifier stage is missing producer evidence")
            if stage in {"CRITIQUE", "VERIFIER"} and not replacements["{{PRODUCER_ARTIFACT_REF}}"]:
                raise ValueError("critique/verifier stage is missing producer artifact ref")
            if stage == "VERIFIER" and not replacements["{{CRITIQUE_ARTIFACT_HASH}}"]:
                raise ValueError("verifier stage is missing critique evidence")
            if stage == "VERIFIER" and not replacements["{{CRITIQUE_ARTIFACT_REF}}"]:
                raise ValueError("verifier stage is missing critique artifact ref")
            lane = _replace_placeholders(
                lane_templates_by_key[key][stage],
                replacements,
            )
            lane_id = str(lane["lane_id"])
            method_input = _build_method_input(
                stage=stage,
                work_key=key,
                actor_id=lane_id,
                method_binding=method_binding,
                work_item_binding=work_item_binding,
                producer=producer,
                critique=critique,
            )
            _validate_method_input(runtime_root, method_binding, method_input)
            method_input_sha256 = _canonical_hash(method_input)
            stage_envelope = {
                "PRODUCER": {
                    "producer_id": lane_id,
                    "status": "copy the exact requested producer status",
                    "claim_refs": "copy the exact requested claim_refs array",
                },
                "CRITIQUE": {
                    "critic_id": lane_id,
                    "target_artifact_ref": method_input["upstream"]["producer_ref"],
                    "target_artifact_hash": method_input["upstream"]["producer_sha256"],
                    "verdict": "copy the exact requested critique verdict",
                    "finding_refs": "copy the exact requested finding_refs array",
                },
                "VERIFIER": {
                    "verifier_id": lane_id,
                    "target_artifact_ref": method_input["upstream"]["producer_ref"],
                    "target_artifact_hash": method_input["upstream"]["producer_sha256"],
                    "target_critique_ref": method_input["upstream"]["critique_ref"],
                    "target_critique_hash": method_input["upstream"]["critique_sha256"],
                    "verdict": "copy the exact requested verifier verdict",
                    "evidence_refs": "copy the exact requested evidence_refs array",
                },
            }[stage]
            output_contract = {
                "fixed_top_level": {
                    "work_key": key,
                    **stage_envelope,
                    "method_admission_hash": method_binding["method_admission_hash"],
                    "method_executable_ref": method_binding["method_executable_ref"],
                    "method_executable_sha256": method_binding["method_executable_sha256"],
                    "method_material_bundle_sha256": method_binding[
                        "method_material_bundle_sha256"
                    ],
                    "method_input_sha256": method_input_sha256,
                },
                "required_method_output": {
                    "applied": True,
                    "stage": stage,
                    "work_key": key,
                    "method_evidence": (
                        "derive F4_EVIDENCE_BOUND_CANARY:<stage>:"
                        "<rightmost 12 characters of work_key>"
                    ),
                },
            }
            lane["prompt"] = (
                f"{lane['prompt']}\n\n"
                "METHOD_CONTRACT_V1\n"
                "Use the executable instructions and all bound schemas/protocols "
                "below. Return strict JSON matching the stage envelope and include "
                "the four method binding fields, method_input_sha256, and a derived "
                "method_output. Do not copy a prefilled method result: apply the "
                "executable evidence rule to this exact method_input.\n"
                + json.dumps(
                    {
                        "method_binding": method_binding,
                        "method_input": method_input,
                        "method_input_sha256": method_input_sha256,
                        "work_item_binding": work_item_binding,
                        "research_surface_binding": research_surface_binding,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\nOUTPUT_CONTRACT_V1\n"
                + json.dumps(
                    output_contract,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\nAll required data is inline. Do not call any tool or inspect "
                "the repository. Return one JSON object now, with no prose."
            ).strip()
            if str(lane.get("model") or external_model) != external_model:
                raise ValueError("F4 lane requested model differs from external model")
            lane["model"] = external_model
            lane["cwd"] = external_worker_cwd
            lane["contract_id"] = F4_READONLY_CONTRACT_ID
            lane["permission_mode"] = "approve-reads"
            lane["result_format"] = "json_object"
            lane["result_json_schema"] = _f4_lane_result_json_schema(
                stage=stage,
                lane_id=lane_id,
                work_key=key,
                method_binding=method_binding,
                method_input=method_input,
                method_input_sha256=method_input_sha256,
            )
            lane["prompt_sha256"] = hashlib.sha256(str(lane["prompt"]).encode("utf-8")).hexdigest()
            lane["method_binding"] = method_binding
            lane["method_input"] = method_input
            lane["method_input_sha256"] = method_input_sha256
            lanes.append(lane)
            lane_ids.append(lane_id)
            lane_bindings[lane_id] = {
                "work_key": key,
                "stage": stage,
                "actor_id": lane_id,
                "contract_id": F4_READONLY_CONTRACT_ID,
                "write": False,
                "allowed_tools": sorted(map(str, lane["allowed_tools"])),
                "permission_mode": "approve-reads",
                "requested_model": external_model,
                "requested_cwd": external_worker_cwd,
                "prompt_sha256": lane["prompt_sha256"],
                "result_format": lane["result_format"],
                "result_json_schema_sha256": hashlib.sha256(
                    artifact_json_bytes(lane["result_json_schema"])
                ).hexdigest(),
                "method_input": method_input,
                "method_input_sha256": method_input_sha256,
                **work_item_binding,
                **research_surface_binding,
            }
        identity = {
            "work_keys": selected,
            "lane_ids": lane_ids,
            "stage": stage,
            "capacity_decision": capacity,
            "source_dependency_graph_content_sha256": graph_content_hash,
            "selection_manifest_content_sha256": selection_manifest.content_hash,
            "research_factory_manifest_content_sha256": factory_verification[
                "manifest_content_sha256"
            ],
            "frontier_sha256": frontier_hash,
            "method_bindings_sha256": _canonical_hash(method_bindings),
            "work_item_bindings_sha256": _canonical_hash(work_item_bindings),
            "research_surface_binding_sha256": _canonical_hash(research_surface_binding),
            "lane_bindings_sha256": _canonical_hash(lane_bindings),
        }
        batch_hash = _canonical_hash(identity)
        operation_id = str(payload.get("operation_id") or "")
        supervisor_identity = {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": external_model,
            "transport_id": "temporal-docker-langgraph",
        }
        external_payload = {
            **template,
            "schema_version": "xinao.foundation_dynamic_wave.v2",
            "operation_id": f"{operation_id}:{batch_hash[:16]}",
            "parent_operation_id": operation_id,
            "correlation_id": f"{operation_id}:{batch_hash}",
            "grok_ready_frontier": lanes,
            "supervisor_routing": {
                "task_separable": True,
                "context_inheritance_required": False,
                "benefit_close": False,
                "candidates": [
                    {
                        **supervisor_identity,
                        "declared_active": True,
                        "healthy": True,
                        "positive_benefit": True,
                        "context_capable": False,
                        "health_basis": "bounded_f4_recovery_probe",
                    }
                ],
                "supervisor_choice": supervisor_identity,
            },
            "dynamic_capacity_decision": capacity,
            "canonical_work_keys": selected,
            "method_bindings": method_bindings,
            "work_item_bindings": work_item_bindings,
            "research_surface_binding": research_surface_binding,
            "lane_bindings": lane_bindings,
            "research_stage": stage,
            "grok_serial_reason": (
                "one evidence-bound F4 work item at current verified capacity"
                if len(lanes) == 1
                else ""
            ),
            "frontier_ref": retained_path(frontier_path),
            "frontier_sha256": frontier_hash,
            "source_dependency_graph_ref": retained_path(graph_path),
            "source_dependency_graph_sha256": graph_file_hash,
            "selection_manifest_ref": retained_path(
                _resolve_runtime_ref(
                    runtime_root,
                    frontier.get("selection_manifest_ref"),
                )
            ),
            "selection_manifest_sha256": str(frontier.get("selection_manifest_sha256") or ""),
            "selection_manifest_content_sha256": selection_manifest.content_hash,
            "method_registry_ref": retained_path(
                _resolve_runtime_ref(
                    runtime_root,
                    frontier.get("method_registry_ref"),
                )
            ),
            "method_registry_sha256": str(frontier.get("method_registry_sha256") or ""),
            "research_factory_manifest_ref": retained_path(factory_manifest_path),
            "research_factory_manifest_sha256": factory_manifest_file_hash,
            "research_factory_manifest_content_sha256": factory_verification[
                "manifest_content_sha256"
            ],
            "payload_template_ref": retained_path(template_path),
            "payload_template_sha256": template_hash,
        }
        output = (
            runtime_root
            / "state"
            / "foundation_continuous"
            / operation_id
            / "dispatch_payloads"
            / f"{batch_hash}.json"
        )
        _write_json_once(output, external_payload)
        return {
            "action": "DISPATCH_EXTERNAL",
            "reason": f"three_stage_pipeline_{stage.lower()}",
            "frontier_ref": retained_path(frontier_path),
            "frontier_sha256": frontier_hash,
            "source_dependency_graph_content_sha256": graph_content_hash,
            "dedup": deduped,
            "capacity_decision": capacity,
            "wave": {
                "wave_id": f"dynamic-{batch_hash}",
                "stage": stage,
                "work_keys": selected,
                "lane_ids": lane_ids,
                "method_bindings": method_bindings,
                "lane_bindings": lane_bindings,
                "payload_ref": retained_path(output),
                "payload_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "correlation_id": external_payload["correlation_id"],
                "submission_timeout_seconds": _bounded_seconds(
                    frontier.get("submission_timeout_seconds"),
                    default=3_600,
                ),
                "external_task_queue": str(
                    frontier.get("external_task_queue") or DEFAULT_EXTERNAL_TASK_QUEUE
                ),
                "external_provider_id": str(
                    frontier.get("external_provider_id") or DEFAULT_EXTERNAL_PROVIDER_ID
                ),
                "external_model": external_model,
                "capacity_decision": capacity,
            },
        }

    milestone = _closure_milestone(runtime_root, frontier)
    if milestone is not None and not payload.get("foundation_execution_ready"):
        return {
            **milestone,
            "frontier_ref": retained_path(frontier_path),
            "frontier_sha256": frontier_hash,
            "capacity_decision": capacity,
        }
    reason = _reconcile_wait_reason(
        frontier,
        milestone=milestone,
        ready_keys=ready_keys,
        width=width,
    )
    return {
        "action": "WAIT",
        "reason": reason,
        "frontier_ref": retained_path(frontier_path),
        "frontier_sha256": frontier_hash,
        "dedup": deduped,
        "capacity_decision": capacity,
        "wait_seconds": _bounded_seconds(frontier.get("wait_seconds"), default=300),
    }


def _verify_external_fanin_model_identity(
    fanin: Mapping[str, Any],
    *,
    expected_model: str,
) -> None:
    """Require the selected session model and its exact backend binding."""

    selected = str(expected_model or "").strip()
    if not selected:
        return
    if str(fanin.get("model") or "") != selected:
        raise ValueError("external model identity does not match dispatch")
    expected_binding = grok_docker_model_identity_binding(selected)
    expected_backend_models = expected_docker_grok_backend_models(selected)
    if (
        fanin.get("model_identity_ok") is not True
        or fanin.get("model_identity_binding") != expected_binding
        or fanin.get("observed_model") != expected_backend_models[0]
        or fanin.get("observed_models") != expected_backend_models
        or fanin.get("observed_backend_models") != expected_backend_models
    ):
        raise ValueError("external backend model identity does not match dispatch binding")


@activity.defn(name="xinao.foundation.v2.inspect_external_result")
def inspect_external_wave_result_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Build typed stage records from exact Grok lane artifacts."""

    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT))
    result_path, result, result_hash = _read_bound_object(
        runtime_root,
        payload.get("result_ref"),
        payload.get("result_sha256"),
    )
    result_body = result.get("result")
    fanin = result_body.get("grok_fanin") if isinstance(result_body, dict) else None
    if not isinstance(fanin, dict) or fanin.get("ok") is not True:
        raise ValueError("external Grok fan-in is not successful")
    manifest_path = _resolve_runtime_ref(runtime_root, fanin.get("manifest_path"))
    manifest_raw = manifest_path.read_bytes()
    manifest_hash = hashlib.sha256(manifest_raw).hexdigest()
    if (
        not _valid_sha256(fanin.get("manifest_sha256"))
        or str(fanin.get("manifest_sha256") or "").lower() != manifest_hash
    ):
        raise ValueError("external Grok fan-in manifest hash mismatch")
    manifest = json.loads(manifest_raw.decode("utf-8"))
    lanes = manifest.get("lanes") if isinstance(manifest, dict) else None
    if not isinstance(lanes, list):
        raise TypeError("external Grok fan-in manifest lanes are missing")
    expected_lane_ids = [str(value) for value in payload.get("lane_ids") or []]
    expected_work_keys = [str(value) for value in payload.get("work_keys") or []]
    stage = str(payload.get("stage") or "").upper()
    if stage not in {"PRODUCER", "CRITIQUE", "VERIFIER"}:
        raise ValueError("external result research stage is invalid")
    actual_lane_ids = [
        str(value.get("lane_id") or "") for value in lanes if isinstance(value, dict)
    ]
    if sorted(actual_lane_ids) != sorted(expected_lane_ids):
        raise ValueError("external Grok lane set does not match selected work")
    if len(expected_lane_ids) != len(expected_work_keys):
        raise ValueError("selected lane/work cardinality mismatch")
    if (
        int(fanin.get("ready_width") or 0) != len(expected_work_keys)
        or int(fanin.get("lane_count") or 0) != len(expected_work_keys)
        or int(manifest.get("ready_width") or 0) != len(expected_work_keys)
        or int(fanin.get("succeeded") or 0) != len(expected_work_keys)
        or int(fanin.get("failed") or 0) != 0
    ):
        raise ValueError("external ready width does not match dispatch manifest")
    expected_provider = str(payload.get("expected_provider_id") or "")
    expected_model = str(payload.get("expected_model") or "")
    if expected_provider and str(fanin.get("provider_id") or "") != expected_provider:
        raise ValueError("external provider identity does not match dispatch")
    _verify_external_fanin_model_identity(fanin, expected_model=expected_model)
    artifacts_by_lane: dict[str, list[dict[str, Any]]] = {}
    common_receipts_by_lane: dict[str, dict[str, Any]] = {}
    stage_records: dict[str, dict[str, Any]] = {}
    method_execution_receipts: dict[str, dict[str, Any]] = {}
    lane_to_work = dict(zip(expected_lane_ids, expected_work_keys, strict=True))
    prior = payload.get("prior_stage_records") or {}
    if not isinstance(prior, dict):
        raise TypeError("prior_stage_records must be an object")
    method_bindings = payload.get("method_bindings")
    if not isinstance(method_bindings, dict) or set(method_bindings) != set(expected_work_keys):
        raise ValueError("external result method bindings do not match selected work")
    lane_bindings = payload.get("lane_bindings")
    if not isinstance(lane_bindings, dict) or set(lane_bindings) != set(expected_lane_ids):
        raise ValueError("external result lane bindings do not match selected lanes")
    for lane in lanes:
        if not isinstance(lane, dict) or lane.get("operation_state") != "completed":
            raise ValueError("external Grok lane did not complete")
        lane_id = str(lane.get("lane_id") or "")
        expected_lane_binding = lane_bindings[lane_id]
        if not isinstance(expected_lane_binding, dict):
            raise TypeError("external expected lane binding must be an object")
        _verify_lane_domain_bindings(runtime_root, expected_lane_binding)
        expected_model = str(expected_lane_binding.get("requested_model") or "")
        expected_backend_models = expected_docker_grok_backend_models(expected_model)
        lane_contract_checks = {
            "contract_id": expected_lane_binding.get("contract_id"),
            "write": expected_lane_binding.get("write"),
            "allowed_tools": expected_lane_binding.get("allowed_tools"),
            "requested_model": expected_lane_binding.get("requested_model"),
            "observed_model": expected_backend_models[0],
            "prompt_sha256": expected_lane_binding.get("prompt_sha256"),
        }
        if any(lane.get(field) != wanted for field, wanted in lane_contract_checks.items()):
            raise ValueError("external Grok lane contract or prompt drifted")
        session_model_evidence = lane.get("session_model_evidence")
        if not isinstance(session_model_evidence, dict):
            raise ValueError("external Grok lane has no session model evidence")
        available_model_ids = session_model_evidence.get("availableModelIds")
        evidence_source = str(session_model_evidence.get("source") or "")
        expected_identity_binding = grok_docker_model_identity_binding(expected_model)
        if evidence_source == "acpx_runtime_status_after_turn":
            source_identity_ok = bool(
                all(
                    str(session_model_evidence.get(field) or "")
                    for field in ("acpxRecordId", "backendSessionId")
                )
                and session_model_evidence.get("currentModelId") == expected_model
            )
        elif evidence_source == "grok_session_summary_and_turn_events":
            try:
                validated_session_evidence = validate_grok_session_model_evidence(
                    session_model_evidence,
                    selected_model=expected_model,
                    session_id=str(lane.get("agent_session_id") or ""),
                )
            except ValueError:
                source_identity_ok = False
            else:
                source_identity_ok = bool(
                    session_model_evidence == validated_session_evidence
                    and lane.get("observed_backend_models") == expected_backend_models
                    and lane.get("model_identity_binding") == expected_identity_binding
                    and lane.get("model_identity_ok") is True
                )
        else:
            source_identity_ok = False
        if (
            lane.get("session_model_evidence_valid") is not True
            or not source_identity_ok
            or session_model_evidence.get("requestedModel") != expected_model
            or not isinstance(available_model_ids, list)
            or expected_model not in set(map(str, available_model_ids))
        ):
            raise ValueError("external Grok session model evidence is not attributable")
        bound: list[dict[str, Any]] = []
        artifact_names: list[str] = []
        final_path: Path | None = None
        final_hash = ""
        operation_spec_path: Path | None = None
        operation_spec_hash = ""
        model_identity_path: Path | None = None
        for raw in lane.get("artifacts") or []:
            if not isinstance(raw, dict):
                raise TypeError("external Grok lane artifact must be an object")
            path = _resolve_runtime_ref(runtime_root, raw.get("uri"))
            expected = str(raw.get("sha256") or "").lower()
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if not _valid_sha256(expected) or expected != actual:
                raise ValueError("external Grok lane artifact hash drifted")
            artifact_name = str(raw.get("name") or "")
            if not artifact_name:
                raise ValueError("external Grok lane artifact name is missing")
            artifact_names.append(artifact_name)
            bound.append(
                {
                    "name": artifact_name,
                    "path": str(path),
                    "sha256": actual,
                    "size_bytes": path.stat().st_size,
                }
            )
            if artifact_name == "final.txt":
                final_path = path
                final_hash = actual
            if artifact_name == "operation-spec.json":
                operation_spec_path = path
                operation_spec_hash = actual
            if artifact_name == "cli_result.json":
                model_identity_path = path
        if not bound:
            raise ValueError("external Grok lane has no bound artifacts")
        if len(artifact_names) != len(set(artifact_names)):
            raise ValueError("external Grok lane artifact names must be unique")
        bound_by_name = {str(item["name"]): item for item in bound}
        if final_path is None:
            raise ValueError("external Grok lane has no final.txt artifact")
        if operation_spec_path is None:
            raise ValueError("external Grok lane has no operation-spec artifact")
        if operation_spec_hash != str(lane.get("operation_spec_sha256") or ""):
            raise ValueError("external Grok operation-spec hash drifted")
        if evidence_source == "grok_session_summary_and_turn_events":
            if model_identity_path is None:
                raise ValueError("external Docker Grok lane has no raw model identity artifact")
            identity_payload = json.loads(model_identity_path.read_text(encoding="utf-8"))
            identity_model_usage = (
                identity_payload.get("modelUsage")
                if isinstance(identity_payload, dict)
                and isinstance(identity_payload.get("modelUsage"), dict)
                else {}
            )
            identity_observed_models = sorted(
                str(model)
                for model, stats in identity_model_usage.items()
                if isinstance(stats, dict) and int(stats.get("modelCalls") or 0) > 0
            )
            if (
                identity_observed_models != expected_backend_models
                or model_identity_path
                != _resolve_runtime_ref(runtime_root, lane.get("model_identity_ref"))
                or hashlib.sha256(model_identity_path.read_bytes()).hexdigest()
                != str(lane.get("model_identity_sha256") or "")
            ):
                raise ValueError("external Docker Grok raw model identity drifted")
        _verify_operation_spec(operation_spec_path, expected_lane_binding)
        if lane.get("cross_seam_contract_version") == LOGICAL_CONTRACT_VERSION:
            common_receipts_by_lane[lane_id] = _verify_docker_common_lane_receipt(
                runtime_root,
                lane,
                bound_by_name,
            )
        raw_text = final_path.read_text(encoding="utf-8").strip()
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            raw_text = "\n".join(lines[1:-1]).strip()
            if raw_text.startswith("json"):
                raw_text = raw_text[4:].lstrip()
        try:
            response = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError("external Grok final artifact is not strict JSON") from exc
        if not isinstance(response, dict):
            raise TypeError("external Grok final JSON must be an object")
        work_key = lane_to_work[lane_id]
        if str(response.get("work_key") or "") != work_key:
            raise ValueError("external Grok final work key does not match dispatch")
        method_binding = method_bindings[work_key]
        if not isinstance(method_binding, dict):
            raise TypeError("external result method binding must be an object")
        snapshot_verification = _verify_method_binding_snapshots(
            runtime_root,
            method_binding,
        )
        if not isinstance(method_binding, dict) or any(
            str(response.get(field) or "") != str(method_binding.get(field) or "")
            for field in (
                "method_admission_hash",
                "method_executable_ref",
                "method_executable_sha256",
                "method_material_bundle_sha256",
            )
        ):
            raise ValueError("external Grok final does not bind the admitted method")
        if (
            response.get("method_material_bundle_sha256")
            != snapshot_verification["method_material_bundle_sha256"]
        ):
            raise ValueError("external Grok final method material bundle drifted")
        if "method_output" not in response:
            raise ValueError("external Grok final has no admitted method output")
        method_input = expected_lane_binding.get("method_input")
        if not isinstance(method_input, dict):
            raise TypeError("external expected lane has no method input")
        prior_producer = (prior.get("PRODUCER") or {}).get(work_key) or {}
        prior_critique = (prior.get("CRITIQUE") or {}).get(work_key) or {}
        recomputed_method_input = _build_method_input(
            stage=stage,
            work_key=work_key,
            actor_id=lane_id,
            method_binding=method_binding,
            work_item_binding=expected_lane_binding,
            producer=prior_producer,
            critique=prior_critique,
        )
        if method_input != recomputed_method_input:
            raise ValueError("external method input does not match stage dependencies")
        method_input_sha256 = _canonical_hash(method_input)
        if (
            method_input_sha256 != expected_lane_binding.get("method_input_sha256")
            or response.get("method_input_sha256") != method_input_sha256
        ):
            raise ValueError("external Grok final method input binding drifted")
        method_execution_receipts[work_key] = _validate_method_execution(
            runtime_root,
            method_binding,
            method_input=method_input,
            expected_method_input=recomputed_method_input,
            method_output=response["method_output"],
            response=response,
            stage=stage,
            work_key=work_key,
        )
        runtime_identity = {
            "temporal_workflow_id": str(result.get("workflow_id") or ""),
            "temporal_run_id": str(result.get("run_id") or ""),
            "lane_id": lane_id,
            "provider_id": str(fanin.get("provider_id") or ""),
            "model": str(fanin.get("model") or ""),
        }
        if any(not value for value in runtime_identity.values()):
            raise ValueError("external Grok runtime identity is incomplete")
        if stage == "PRODUCER":
            status = str(response.get("status") or "").upper()
            if status not in {"VERIFIED", "PARTIAL", "FAILED", "FALSIFIED", "NO_ACTION"}:
                raise ValueError("producer status is invalid")
            record = {
                "work_key": work_key,
                "producer_id": str(response.get("producer_id") or ""),
                "artifact_ref": final_path.as_posix(),
                "artifact_hash": final_hash,
                "status": status,
                "claim_refs": sorted({str(value) for value in response.get("claim_refs") or []}),
                **runtime_identity,
            }
            if not record["producer_id"]:
                raise ValueError("producer identity is missing")
            if record["producer_id"] != lane_id:
                raise ValueError("producer identity does not equal declared lane")
        elif stage == "CRITIQUE":
            producer = (prior.get("PRODUCER") or {}).get(work_key) or {}
            target_ref = str(response.get("target_artifact_ref") or "")
            target_hash = str(response.get("target_artifact_hash") or "")
            if target_ref != producer.get("artifact_ref") or target_hash != producer.get(
                "artifact_hash"
            ):
                raise ValueError("critique does not bind the producer artifact")
            verdict = str(response.get("verdict") or "").upper()
            if verdict not in {"APPROVED", "CHANGES_REQUESTED", "REJECTED"}:
                raise ValueError("critique verdict is invalid")
            record = {
                "work_key": work_key,
                "critic_id": str(response.get("critic_id") or ""),
                "target_artifact_hash": target_hash,
                "critique_artifact_ref": final_path.as_posix(),
                "critique_artifact_hash": final_hash,
                "verdict": verdict,
                "finding_refs": sorted(
                    {str(value) for value in response.get("finding_refs") or []}
                ),
                **runtime_identity,
            }
            if not record["critic_id"]:
                raise ValueError("critic identity is missing")
            if record["critic_id"] != lane_id:
                raise ValueError("critic identity does not equal declared lane")
        else:
            producer = (prior.get("PRODUCER") or {}).get(work_key) or {}
            critique = (prior.get("CRITIQUE") or {}).get(work_key) or {}
            target_ref = str(response.get("target_artifact_ref") or "")
            target_hash = str(response.get("target_artifact_hash") or "")
            target_critique_ref = str(response.get("target_critique_ref") or "")
            target_critique = str(response.get("target_critique_hash") or "")
            if target_ref != producer.get("artifact_ref") or target_hash != producer.get(
                "artifact_hash"
            ):
                raise ValueError("verifier does not bind the producer artifact")
            if target_critique_ref != critique.get(
                "critique_artifact_ref"
            ) or target_critique != critique.get("critique_artifact_hash"):
                raise ValueError("verifier does not bind the critique artifact")
            verdict = str(response.get("verdict") or "").upper()
            if verdict not in {"VERIFIED", "PARTIAL", "REJECTED"}:
                raise ValueError("verifier verdict is invalid")
            record = {
                "work_key": work_key,
                "verifier_id": str(response.get("verifier_id") or ""),
                "target_artifact_hash": target_hash,
                "target_critique_hash": target_critique,
                "verification_artifact_ref": final_path.as_posix(),
                "verification_artifact_hash": final_hash,
                "verdict": verdict,
                "evidence_refs": sorted(
                    {str(value) for value in response.get("evidence_refs") or []}
                ),
                **runtime_identity,
            }
            if not record["verifier_id"]:
                raise ValueError("verifier identity is missing")
            if record["verifier_id"] != lane_id:
                raise ValueError("verifier identity does not equal declared lane")
        artifacts_by_lane[lane_id] = bound
        stage_records[work_key] = record
    return {
        "ok": True,
        "result_ref": str(result_path),
        "result_sha256": result_hash,
        "manifest_ref": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "stage": stage,
        "completed_work_keys": sorted(expected_work_keys),
        "lane_to_work_key": lane_to_work,
        "stage_records": stage_records,
        "method_execution_receipts": method_execution_receipts,
        "artifacts_by_lane": artifacts_by_lane,
        "common_receipts_by_lane": common_receipts_by_lane,
        "provider_id": str(fanin.get("provider_id") or ""),
        "model": str(fanin.get("model") or ""),
        "succeeded": int(fanin.get("succeeded") or 0),
        "failed": int(fanin.get("failed") or 0),
    }


@activity.defn(name="xinao.foundation.v2.finalize_fan_in")
def finalize_research_fan_in_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the canonical AND-policy and persist its content-bound report."""

    expected = [str(value) for value in payload.get("expected_work_keys") or []]
    records = payload.get("stage_records")
    if not isinstance(records, dict):
        raise TypeError("stage_records must be an object")
    producer = records.get("PRODUCER")
    critique = records.get("CRITIQUE")
    verifier = records.get("VERIFIER")
    if not all(isinstance(value, dict) for value in (producer, critique, verifier)):
        raise ValueError("producer, critique, and verifier records are required")
    fanin = deterministic_fan_in(
        list(producer.values()),
        critiques=list(critique.values()),
        verifications=list(verifier.values()),
        expected_work_keys=expected,
    )
    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT))
    method_bindings = payload.get("method_bindings")
    if not isinstance(method_bindings, dict) or set(method_bindings) != set(expected):
        raise ValueError("fan-in method bindings do not match expected work")
    for work_key in expected:
        binding = method_bindings[work_key]
        if not isinstance(binding, Mapping):
            raise TypeError("fan-in method binding must be an object")
        _verify_method_binding_snapshots(runtime_root, binding)
    operation_id = str(payload.get("operation_id") or "")
    content_hash = str(fanin["content_sha256"])
    path = (
        runtime_root
        / "state"
        / "foundation_continuous"
        / operation_id
        / "fanin"
        / f"{content_hash}.json"
    )
    _write_json_once(path, fanin)
    return {
        "ok": True,
        "fanin": fanin,
        "fanin_ref": str(path),
        "fanin_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _initial_state_v2(initial: Mapping[str, Any]) -> dict[str, Any]:
    resume = initial.get("resume_state")
    if isinstance(resume, dict):
        state = json.loads(json.dumps(resume))
        legacy_closed = state.pop("foundation_closed", False) is True
        prior_ready = state.get("foundation_execution_ready") is True
        prior_closure = bool(state.get("foundation_closure"))
        state["foundation_execution_ready"] = False
        state["foundation_closure"] = {}
        state["scope"] = "foundation"
        if legacy_closed:
            state["readiness_migration"] = {
                "reason": "DEPRECATED_FOUNDATION_CLOSED_REQUIRES_CURRENT_REPROOF",
                "requires_current_report": True,
            }
        elif prior_ready or prior_closure:
            state["readiness_migration"] = {
                "reason": "RESUMED_FOUNDATION_READINESS_REQUIRES_CURRENT_REPROOF",
                "requires_current_report": True,
            }
        else:
            state["readiness_migration"] = {}
        state["run_generation"] = int(state.get("run_generation") or 0) + 1
        state["waves_since_continue_as_new"] = 0
        state["current_wave"] = None
        state["status"] = "RECONCILING"
        state["next_wake_at"] = ""
        state["revision"] = int(state.get("revision") or 0) + 1
        return state
    operation_id = str(initial.get("operation_id") or "").strip()
    frontier_ref = str(initial.get("frontier_ref") or "").strip()
    frontier_sha256 = str(initial.get("frontier_sha256") or "").lower()
    roll_forward_ref = str(initial.get("roll_forward_manifest_ref") or "")
    roll_forward_hash = str(initial.get("roll_forward_manifest_sha256") or "").lower()
    owner_generation = int(initial.get("owner_generation") or 0)
    if (
        not operation_id
        or not frontier_ref
        or not _valid_sha256(frontier_sha256)
        or not roll_forward_ref
        or not _valid_sha256(roll_forward_hash)
        or owner_generation < 1
    ):
        raise ValueError("hash-bound frontier and roll-forward identities are required")
    return {
        "schema_version": "xinao.foundation_continuous_state.v2",
        "operation_id": operation_id,
        "runtime_root": str(initial.get("runtime_root") or DEFAULT_RUNTIME_ROOT),
        "frontier_ref": frontier_ref,
        "frontier_sha256": frontier_sha256,
        "scope": "foundation",
        "owner_generation": owner_generation,
        "run_generation": 0,
        "roll_forward_manifest_ref": roll_forward_ref,
        "roll_forward_manifest_sha256": roll_forward_hash,
        "roll_forward_verification": {},
        "status": "PENDING",
        "wave_sequence": 0,
        "waves_since_continue_as_new": 0,
        "max_waves_per_run": max(
            1,
            min(int(initial.get("max_waves_per_run") or 20), 1_000),
        ),
        "waves_completed": 0,
        "waves_failed": 0,
        "closed_work_keys": [],
        "failed_work_keys": [],
        "current_wave": None,
        "last_wave_result": {},
        "last_decision": {},
        "batch_expected_work_keys": [],
        "batch_stage": "IDLE",
        "batch_stage_records": {},
        "batch_capacity_decision": {},
        "last_fanin": {},
        "previous_width": 1,
        "previous_succeeded": 0,
        "previous_failed": 0,
        "previous_partial": False,
        "foundation_execution_ready": False,
        "foundation_closure": {},
        "readiness_migration": {},
        "paused": bool(initial.get("paused", False)),
        "stop_requested": False,
        "idle_cycles": 0,
        "default_wait_seconds": _bounded_seconds(
            initial.get("default_wait_seconds"),
            default=300,
        ),
        "next_wake_at": "",
        "wake_revision": 0,
        "material_signal_ids": [],
        "duplicate_material_signals": 0,
        "control_audit": [],
        "revision": 1,
    }


def _continuation_input_v2(state: Mapping[str, Any]) -> dict[str, Any]:
    compact = json.loads(json.dumps(state))
    compact["current_wave"] = None
    last = dict(compact.get("last_decision") or {})
    last.pop("wave", None)
    compact["last_decision"] = last
    return {"resume_state": compact}


@workflow.defn(name=PARENT_WORKFLOW_NAME_V2)
class FoundationContinuousWorkflowV2:
    """Durable foundation controller that continues at mainline-global scope."""

    @workflow.init
    def __init__(self, initial: dict[str, Any]) -> None:
        self._state = _initial_state_v2(initial)

    @workflow.query(name="state")
    def state(self) -> dict[str, Any]:
        return _parent_snapshot(self._state)

    @workflow.signal(name="material_changed")
    def material_changed(self, payload: dict[str, Any]) -> None:
        signal_id = str(payload.get("signal_id") or "").strip() or _canonical_hash(payload)
        if signal_id in self._state["material_signal_ids"]:
            self._state["duplicate_material_signals"] += 1
            return
        new_hash = str(payload.get("frontier_sha256") or "").lower()
        if _valid_sha256(new_hash):
            self._state["frontier_sha256"] = new_hash
        self._state["material_signal_ids"].append(signal_id)
        self._state["wake_revision"] += 1
        self._state["revision"] += 1

    @workflow.update(name="control")
    def control(self, command: dict[str, Any]) -> dict[str, Any]:
        return _apply_control(self._state, command)

    @control.validator
    def validate_control(self, command: dict[str, Any]) -> None:
        _validate_control(command)

    async def _persist(self) -> None:
        receipt = await workflow.execute_activity(
            persist_foundation_state,
            {
                "runtime_root": self._state["runtime_root"],
                "operation_id": self._state["operation_id"],
                "entity_kind": "parent-v2",
                "entity_id": workflow.info().workflow_id,
                "snapshot": _parent_snapshot(self._state),
            },
            **_activity_options(),
        )
        self._state["last_state_ref"] = receipt["artifact_ref"]
        self._state["last_state_hash"] = receipt["snapshot_hash"]
        current = self._state.get("current_wave")
        if isinstance(current, dict) and receipt.get("request_ref"):
            current["request_ref"] = receipt["request_ref"]

    async def _wait(self, seconds: int) -> None:
        before = int(self._state["wake_revision"])
        self._state["next_wake_at"] = (workflow.now() + timedelta(seconds=seconds)).isoformat()
        try:
            await workflow.wait_condition(
                lambda: bool(
                    self._state["stop_requested"]
                    or self._state["paused"]
                    or int(self._state["wake_revision"]) != before
                ),
                timeout=timedelta(seconds=seconds),
            )
        except asyncio.TimeoutError:
            self._state["idle_cycles"] += 1
        else:
            self._state["idle_cycles"] = 0
        self._state["next_wake_at"] = ""
        self._state["revision"] += 1

    async def _run_wave(self, wave_value: Mapping[str, Any]) -> None:
        wave = dict(wave_value)
        sequence = int(self._state["wave_sequence"]) + 1
        child = await workflow.start_child_workflow(
            FoundationWaveChildWorkflowV1.run,
            {
                "operation_id": self._state["operation_id"],
                "runtime_root": self._state["runtime_root"],
                "wave_id": wave["wave_id"],
                "wave_sequence": sequence,
                "correlation_id": wave["correlation_id"],
                "payload_ref": wave["payload_ref"],
                "payload_sha256": wave["payload_sha256"],
                "external_task_queue": wave["external_task_queue"],
                "external_provider_id": wave["external_provider_id"],
                "external_model": wave["external_model"],
                "submission_timeout_seconds": wave["submission_timeout_seconds"],
            },
            id=f"{workflow.info().workflow_id}-wave-{sequence:06d}",
            task_queue=workflow.info().task_queue,
            result_type=dict,
            cancellation_type=(workflow.ChildWorkflowCancellationType.WAIT_CANCELLATION_COMPLETED),
            parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
        )
        self._state["wave_sequence"] = sequence
        self._state["current_wave"] = {
            **wave,
            "wave_sequence": sequence,
            "child_workflow_id": child.id,
            "child_run_id": child.first_execution_run_id or "",
        }
        self._state["status"] = "WAITING_EXTERNAL"
        self._state["revision"] += 1
        await self._persist()
        stop_wait = asyncio.create_task(
            workflow.wait_condition(lambda: bool(self._state["stop_requested"]))
        )
        try:
            done, _ = await workflow.wait(
                [child, stop_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_wait in done and self._state["stop_requested"]:
                child.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError,
                    ChildWorkflowError,
                    TemporalError,
                ):
                    await child
                self._state["current_wave"] = None
                return
            try:
                child_result = await child
            except (ChildWorkflowError, TemporalError) as exc:
                child_result = {
                    "status": "CHILD_FAILED",
                    "external_failed": {
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:400],
                    },
                    "verification": {},
                }
        finally:
            if not stop_wait.done():
                stop_wait.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_wait
        verification = dict(child_result.get("verification") or {})
        compact: dict[str, Any] = {
            "wave_id": wave["wave_id"],
            "status": str(child_result.get("status") or "UNKNOWN"),
            "verification": verification,
            "external_failed": dict(child_result.get("external_failed") or {}),
        }
        if compact["status"] == "COMPLETED" and verification.get("ok") is True:
            try:
                inspection = await workflow.execute_activity(
                    inspect_external_wave_result_v2,
                    {
                        "runtime_root": self._state["runtime_root"],
                        "result_ref": verification["result_ref"],
                        "result_sha256": verification["result_sha256"],
                        "lane_ids": wave["lane_ids"],
                        "work_keys": wave["work_keys"],
                        "stage": wave["stage"],
                        "method_bindings": wave["method_bindings"],
                        "lane_bindings": wave["lane_bindings"],
                        "expected_provider_id": wave["external_provider_id"],
                        "expected_model": wave["external_model"],
                        "prior_stage_records": self._state["batch_stage_records"],
                    },
                    **_activity_options(),
                )
            except ActivityError as exc:
                compact["inspection_error"] = str(exc)[:400]
                self._state["waves_failed"] += 1
                self._state["previous_succeeded"] = 0
                self._state["previous_failed"] = len(wave["work_keys"])
                self._state["previous_partial"] = True
            else:
                compact["inspection"] = inspection
                stage = str(wave["stage"])
                self._state["batch_stage_records"][stage] = dict(inspection["stage_records"])
                self._state["waves_completed"] += 1
                if stage == "PRODUCER":
                    self._state["batch_stage"] = "CRITIQUE"
                elif stage == "CRITIQUE":
                    self._state["batch_stage"] = "VERIFIER"
                else:
                    finalized = await workflow.execute_activity(
                        finalize_research_fan_in_v2,
                        {
                            "runtime_root": self._state["runtime_root"],
                            "operation_id": self._state["operation_id"],
                            "expected_work_keys": self._state["batch_expected_work_keys"],
                            "stage_records": self._state["batch_stage_records"],
                            "method_bindings": wave["method_bindings"],
                        },
                        **_activity_options(),
                    )
                    self._state["last_fanin"] = {
                        "fanin_ref": finalized["fanin_ref"],
                        "fanin_sha256": finalized["fanin_sha256"],
                        "content_sha256": finalized["fanin"]["content_sha256"],
                    }
                    resolved = list(finalized["fanin"]["resolved_work_keys"])
                    unresolved = list(finalized["fanin"]["unresolved_work_keys"])
                    for key in resolved:
                        if key not in self._state["closed_work_keys"]:
                            self._state["closed_work_keys"].append(key)
                    self._state["previous_succeeded"] = len(resolved)
                    self._state["previous_failed"] = len(unresolved)
                    self._state["previous_partial"] = bool(unresolved)
                    self._state["batch_expected_work_keys"] = []
                    self._state["batch_stage"] = "IDLE"
                    self._state["batch_stage_records"] = {}
                    self._state["batch_capacity_decision"] = {}
        else:
            self._state["waves_failed"] += 1
            self._state["previous_succeeded"] = 0
            self._state["previous_failed"] = len(wave["work_keys"])
            self._state["previous_partial"] = True
        failed_stage = bool(compact.get("inspection_error")) or compact["status"] != ("COMPLETED")
        if failed_stage:
            self._state["batch_expected_work_keys"] = []
            self._state["batch_stage"] = "IDLE"
            self._state["batch_stage_records"] = {}
            self._state["batch_capacity_decision"] = {}
        decision = wave.get("capacity_decision") or {}
        self._state["previous_width"] = int(
            decision.get("capacity_tier") or self._state["previous_width"]
        )
        self._state["waves_since_continue_as_new"] += 1
        self._state["last_wave_result"] = compact
        self._state["current_wave"] = None
        self._state["status"] = "RECONCILING"
        self._state["revision"] += 1
        await self._persist()

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        del initial
        self._state["workflow_id"] = workflow.info().workflow_id
        self._state["run_id"] = workflow.info().run_id
        if not self._state["roll_forward_verification"]:
            self._state["roll_forward_verification"] = await workflow.execute_activity(
                verify_roll_forward_manifest_v2,
                {
                    "runtime_root": self._state["runtime_root"],
                    "operation_id": self._state["operation_id"],
                    "owner_generation": self._state["owner_generation"],
                    "manifest_ref": self._state["roll_forward_manifest_ref"],
                    "manifest_sha256": self._state["roll_forward_manifest_sha256"],
                },
                **_activity_options(),
            )
        await self._persist()
        try:
            while True:
                if self._state["stop_requested"]:
                    self._state["status"] = "STOPPED"
                    self._state["revision"] += 1
                    await self._persist()
                    await workflow.wait_condition(workflow.all_handlers_finished)
                    return _parent_snapshot(self._state)
                if self._state["current_wave"] is None and (
                    workflow.info().is_continue_as_new_suggested()
                    or int(self._state["waves_since_continue_as_new"])
                    >= int(self._state["max_waves_per_run"])
                ):
                    await workflow.wait_condition(workflow.all_handlers_finished)
                    workflow.continue_as_new(_continuation_input_v2(self._state))
                if self._state["paused"]:
                    self._state["status"] = "PAUSED"
                    await self._persist()
                    await workflow.wait_condition(
                        lambda: bool(not self._state["paused"] or self._state["stop_requested"])
                    )
                    continue
                decision = await workflow.execute_activity(
                    reconcile_foundation_frontier_v2,
                    {
                        "runtime_root": self._state["runtime_root"],
                        "operation_id": self._state["operation_id"],
                        "frontier_ref": self._state["frontier_ref"],
                        "frontier_sha256": self._state["frontier_sha256"],
                        "closed_work_keys": list(self._state["closed_work_keys"]),
                        "in_flight_work_keys": [],
                        "previous_width": self._state["previous_width"],
                        "succeeded": self._state["previous_succeeded"],
                        "failed": self._state["previous_failed"],
                        "partial": self._state["previous_partial"],
                        "foundation_execution_ready": self._state["foundation_execution_ready"],
                        "batch_expected_work_keys": self._state["batch_expected_work_keys"],
                        "next_stage": (
                            self._state["batch_stage"]
                            if self._state["batch_stage"] != "IDLE"
                            else "PRODUCER"
                        ),
                        "batch_stage_records": self._state["batch_stage_records"],
                        "batch_capacity_decision": self._state["batch_capacity_decision"],
                    },
                    **_activity_options(),
                )
                self._state["last_decision"] = dict(decision)
                self._state["revision"] += 1
                action = str(decision.get("action") or "WAIT")
                if action == "DISPATCH_EXTERNAL":
                    if not self._state["batch_expected_work_keys"]:
                        self._state["batch_expected_work_keys"] = list(
                            decision["wave"]["work_keys"]
                        )
                        self._state["batch_stage"] = "PRODUCER"
                        self._state["batch_stage_records"] = {}
                        self._state["batch_capacity_decision"] = dict(decision["capacity_decision"])
                    await self._run_wave(decision["wave"])
                    continue
                if action == "MILESTONE":
                    self._state["foundation_execution_ready"] = True
                    self._state["foundation_closure"] = {
                        key: value
                        for key, value in decision.items()
                        if key.startswith("foundation_closure_")
                    }
                    self._state["scope"] = "mainline-global"
                    self._state["status"] = "MILESTONE_RECORDED"
                else:
                    self._state["status"] = "WAITING"
                await self._persist()
                await self._wait(
                    _bounded_seconds(
                        decision.get("wait_seconds"),
                        default=int(self._state["default_wait_seconds"]),
                    )
                )
        except asyncio.CancelledError:
            self._state["stop_requested"] = True
            self._state["status"] = "CANCELED"
            self._state["revision"] += 1
            with contextlib.suppress(TemporalError, asyncio.CancelledError):
                await asyncio.shield(self._persist())
            raise


def temporal_exports_v2() -> tuple[list[type], list[Any]]:
    return (
        [FoundationContinuousWorkflowV2],
        [
            reconcile_foundation_frontier_v2,
            inspect_external_wave_result_v2,
            finalize_research_fan_in_v2,
            verify_roll_forward_manifest_v2,
        ],
    )


__all__ = [
    "FoundationContinuousWorkflowV2",
    "PARENT_WORKFLOW_NAME_V2",
    "_closure_milestone",
    "_continuation_input_v2",
    "_initial_state_v2",
    "finalize_research_fan_in_v2",
    "inspect_external_wave_result_v2",
    "reconcile_foundation_frontier_v2",
    "temporal_exports_v2",
    "verify_roll_forward_manifest_v2",
]
