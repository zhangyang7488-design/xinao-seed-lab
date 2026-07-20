"""Phase-gated V3 foundation controller primitives.

V1 and V2 remain replayable historical workflows.  V3 treats the complete
``foundation_closure_pack.v4`` as the only proof root that may authorize
``AUTONOMOUS_RESEARCH``.  The expensive F1-F4 replay runs in a dedicated
activity; lightweight reconciliation never promotes a bare boolean.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from temporalio import activity, workflow
from temporalio.common import VersioningBehavior
from temporalio.exceptions import ActivityError, TemporalError

from services.agent_runtime.foundation_continuous_workflow import (
    DEFAULT_EXTERNAL_MODEL,
    DEFAULT_EXTERNAL_PROVIDER_ID,
    DEFAULT_EXTERNAL_TASK_QUEUE,
    DEFAULT_RUNTIME_ROOT,
    _accept_external_signal,
    _activity_options,
    _apply_control,
    _bounded_seconds,
    _canonical_hash,
    _child_snapshot,
    _parent_snapshot,
    _resolve_runtime_ref,
    _validate_control,
    _write_json_once,
    persist_foundation_state,
    verify_external_wave_result,
)
from services.agent_runtime.foundation_continuous_workflow_v2 import (
    _read_bound_object,
    verify_roll_forward_manifest_v2,
)

with workflow.unsafe.imports_passed_through():
    from xinao.canonical import canonical_sha256
    from xinao.foundation.assertion_verifier_registry import (
        FOUNDATION_BLOCK_IDS,
        canonical_blueprint_path,
        validate_authority_snapshot,
    )
    from xinao.foundation.closure import (
        derive_foundation_closure_report,
        verify_foundation_closure_report,
    )

PARENT_WORKFLOW_NAME_V3 = "FoundationContinuousWorkflowV3"
CHILD_WORKFLOW_NAME_V3 = "FoundationWaveChildWorkflowV3"
FOUNDATION_CONSTRUCTION = "FOUNDATION_CONSTRUCTION"
AUTONOMOUS_RESEARCH = "AUTONOMOUS_RESEARCH"
_EXECUTION_PHASES = frozenset({FOUNDATION_CONSTRUCTION, AUTONOMOUS_RESEARCH})
_PACK_SCHEMA = "xinao.foundation_closure_pack.v4"
_PROOF_SCHEMA = "xinao.foundation_closure_gate_proof.v3"
_STATE_SCHEMA = "xinao.foundation_continuous_state.v3"
_CHILD_STATE_SCHEMA = "xinao.foundation_wave_child_state.v3"
_LONG_PROOF_TIMEOUT_SECONDS = 7_200


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _read_evidence_ref(
    runtime_root: Path,
    pack_root: Path,
    raw: object,
    *,
    label: str,
    expected_relative: str | None = None,
    allow_outside_pack: bool = False,
) -> tuple[Path, dict[str, Any], str]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{label} evidence ref must be an object")
    path_value = raw.get("path")
    sha256 = raw.get("sha256")
    size_bytes = raw.get("size_bytes")
    if (
        not isinstance(path_value, str)
        or not path_value.strip()
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
        or not isinstance(size_bytes, int)
        or size_bytes < 0
    ):
        raise ValueError(f"{label} evidence identity is invalid")
    path = _resolve_runtime_ref(runtime_root, path_value).resolve()
    if not path.is_file():
        raise ValueError(f"{label} evidence file does not exist: {path}")
    if not allow_outside_pack and not _inside(path, pack_root):
        raise ValueError(f"{label} evidence escaped the closure pack")
    if expected_relative is not None and path != (pack_root / expected_relative).resolve():
        raise ValueError(f"{label} evidence path is not canonical")
    raw_bytes = path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if len(raw_bytes) != size_bytes or digest != sha256:
        raise ValueError(f"{label} evidence bytes do not match their identity")
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} evidence is not valid JSON") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{label} evidence must be a JSON object")
    return path, value, digest


def _physical_inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": _file_sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(
            (candidate for candidate in root.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(root).as_posix(),
        )
    ]


def _verifier_source_sha256() -> str:
    return canonical_sha256(
        {
            "verify_pack": inspect.getsource(_verify_foundation_closure_pack_objects_v3),
            "read_ref": inspect.getsource(_read_evidence_ref),
            "inventory": inspect.getsource(_physical_inventory),
            "proof_validator": inspect.getsource(validate_foundation_closure_gate_proof_v3),
        }
    )


def _same_ref(left: object, right: object) -> bool:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return False
    return all(left.get(key) == right.get(key) for key in ("path", "sha256", "size_bytes"))


def _verify_foundation_closure_pack_objects_v3(
    *,
    runtime_root: Path,
    pack_path: Path,
    manifest: Mapping[str, Any],
    pack_file_sha256: str,
) -> dict[str, Any]:
    """Replay one complete closure pack into a content-addressed gate proof."""

    if pack_path.name != "foundation_closure_pack.json":
        raise ValueError("foundation closure pack manifest name is invalid")
    pack_root = pack_path.parent.resolve()
    manifest_body = dict(manifest)
    recorded_pack_sha256 = manifest_body.pop("pack_sha256", None)
    if (
        manifest.get("schema_version") != _PACK_SCHEMA
        or not isinstance(recorded_pack_sha256, str)
        or canonical_sha256(manifest_body) != recorded_pack_sha256
    ):
        raise ValueError("foundation closure pack content identity is invalid")

    blueprint_path = canonical_blueprint_path().resolve()
    blueprint_ref = manifest.get("blueprint_ref")
    bound_blueprint_path, _, blueprint_file_sha256 = _read_evidence_ref(
        runtime_root,
        pack_root,
        blueprint_ref,
        label="foundation blueprint",
        allow_outside_pack=True,
    )
    if bound_blueprint_path != blueprint_path:
        raise ValueError("foundation closure pack is not bound to the current blueprint")

    report_input_path, report_input, report_input_file_sha256 = _read_evidence_ref(
        runtime_root,
        pack_root,
        manifest.get("report_input_ref"),
        label="foundation report input",
        expected_relative="foundation_closure_report_input.json",
    )
    report_path, report, report_file_sha256 = _read_evidence_ref(
        runtime_root,
        pack_root,
        manifest.get("report_ref"),
        label="foundation report",
        expected_relative="foundation_closure_report.json",
    )
    verification_path, verification, verification_file_sha256 = _read_evidence_ref(
        runtime_root,
        pack_root,
        manifest.get("verification_ref"),
        label="foundation verification",
        expected_relative="foundation_closure_verification.json",
    )
    authority_ref = manifest.get("authority_snapshot_manifest_ref")
    compiler_ref = manifest.get("compiler_code_manifest_ref")
    if not _same_ref(authority_ref, compiler_ref):
        raise ValueError("compiler and authority manifest identities differ")
    authority_path, authority_manifest, authority_file_sha256 = _read_evidence_ref(
        runtime_root,
        pack_root,
        authority_ref,
        label="foundation authority snapshot",
        expected_relative="authority_snapshot/authority_manifest.json",
    )
    current_authority = validate_authority_snapshot(authority_path, require_live_match=True)
    if current_authority != authority_manifest:
        raise ValueError("foundation authority snapshot validation changed its identity")

    receipts = manifest.get("fresh_assertion_bundle_receipt_refs")
    if not isinstance(receipts, Mapping) or set(receipts) != set(FOUNDATION_BLOCK_IDS):
        raise ValueError("foundation closure pack receipt inventory is not exact F1-F4")
    receipt_file_sha256: dict[str, str] = {}
    for block_id in FOUNDATION_BLOCK_IDS:
        _, receipt, receipt_sha256 = _read_evidence_ref(
            runtime_root,
            pack_root,
            receipts[block_id],
            label=f"foundation receipt {block_id}",
            expected_relative=f"fresh_assertion_bundle_receipts/{block_id}.json",
        )
        if (
            receipt.get("schema_version") != "xinao.fresh_assertion_bundle_receipt.v3"
            or receipt.get("block_id") != block_id
            or receipt.get("double_fresh_bytes_equal") is not True
            or not _same_ref(receipt.get("compiler_code_manifest_ref"), authority_ref)
        ):
            raise ValueError(f"foundation receipt is not a verified fresh bundle: {block_id}")
        receipt_file_sha256[block_id] = receipt_sha256

    if (
        not _same_ref(report_input.get("blueprint_ref"), blueprint_ref)
        or not _same_ref(report.get("blueprint_ref"), blueprint_ref)
        or not _same_ref(report_input.get("compiler_code_manifest_ref"), authority_ref)
        or not _same_ref(report_input.get("authority_snapshot_manifest_ref"), authority_ref)
    ):
        raise ValueError("foundation report source bindings differ from the closure pack")
    rebuilt_report = derive_foundation_closure_report(
        dict(report_input),
        blueprint_path=blueprint_path,
    )
    if rebuilt_report != report:
        raise ValueError("foundation report does not equal its current canonical derivation")
    replay = verify_foundation_closure_report(dict(report), blueprint_path=blueprint_path)
    if replay != verification:
        raise ValueError("foundation verification does not equal the current independent replay")
    verification_checks = verification.get("checks")
    report_blocks = report.get("block_reports")
    if (
        verification.get("schema_version") != "xinao.foundation_closure_verification.v1"
        or verification.get("ok") is not True
        or verification.get("foundation_closed") is not True
        or not isinstance(verification_checks, Mapping)
        or not verification_checks
        or not all(value is True for value in verification_checks.values())
        or not isinstance(report_blocks, Mapping)
        or set(report_blocks) != set(FOUNDATION_BLOCK_IDS)
        or any(
            not isinstance(report_blocks[block_id], Mapping)
            or report_blocks[block_id].get("status") != "VERIFIED"
            for block_id in FOUNDATION_BLOCK_IDS
        )
        or report.get("status") != "VERIFIED"
        or report.get("bindings_complete") is not True
        or report.get("canonical_bundle_replay_verified") is not True
        or report.get("all_required_assertions_pass") is not True
        or report.get("foundation_closed") is not True
        or report.get("formal_research_allowed") is not True
        or report.get("formal_research_gate") != "OPEN"
        or report.get("legacy_a_g_gate_used") is not False
        or report.get("manual_override_used") is not False
    ):
        raise ValueError("foundation report is not a verified F1-F4 closure")

    report_input_blocks = report_input.get("block_reports")
    if not isinstance(report_input_blocks, Mapping) or set(report_input_blocks) != set(
        FOUNDATION_BLOCK_IDS
    ):
        raise ValueError("foundation report input block inventory is not exact F1-F4")
    artifact_count = sum(
        len(report_input_blocks[block_id].get("artifact_hashes") or {})
        for block_id in FOUNDATION_BLOCK_IDS
    )
    assertion_count = sum(
        len(report_input_blocks[block_id].get("assertion_results") or {})
        for block_id in FOUNDATION_BLOCK_IDS
    )
    input_hashes = report_input.get("input_hashes")
    if (
        manifest.get("artifact_count") != artifact_count
        or manifest.get("assertion_count") != assertion_count
        or not isinstance(input_hashes, Mapping)
        or manifest.get("retained_input_material_count") != len(input_hashes)
        or manifest.get("retained_artifact_material_count") != artifact_count
        or manifest.get("source_materials_self_contained") is not True
        or manifest.get("foundation_closed") is not True
        or manifest.get("fresh_process_verified") is not True
        or manifest.get("fresh_assertion_bundle_verified") is not True
    ):
        raise ValueError("foundation closure pack summary does not match its report inventory")

    inventory = _physical_inventory(pack_root)
    proof_core = {
        "schema_version": _PROOF_SCHEMA,
        "status": "VERIFIED",
        "allowed_execution_phase": AUTONOMOUS_RESEARCH,
        "foundation_block_ids": list(FOUNDATION_BLOCK_IDS),
        "closure_pack_ref": str(pack_path),
        "closure_pack_file_sha256": pack_file_sha256,
        "closure_pack_content_sha256": recorded_pack_sha256,
        "closure_pack_inventory_count": len(inventory),
        "closure_pack_inventory_sha256": canonical_sha256(inventory),
        "report_input_ref": str(report_input_path),
        "report_input_file_sha256": report_input_file_sha256,
        "report_ref": str(report_path),
        "report_file_sha256": report_file_sha256,
        "report_artifact_sha256": str(report["artifact_hash"]),
        "verification_ref": str(verification_path),
        "verification_file_sha256": verification_file_sha256,
        "blueprint_ref": str(blueprint_path),
        "blueprint_file_sha256": blueprint_file_sha256,
        "authority_manifest_ref": str(authority_path),
        "authority_manifest_file_sha256": authority_file_sha256,
        "authority_manifest_content_sha256": str(authority_manifest["content_sha256"]),
        "fresh_receipt_file_sha256": receipt_file_sha256,
        "input_hashes_sha256": canonical_sha256(input_hashes),
        "verifier_source_sha256": _verifier_source_sha256(),
    }
    return {**proof_core, "content_sha256": canonical_sha256(proof_core)}


@activity.defn(name="xinao.foundation.v3.verify_closure_pack")
def verify_foundation_closure_pack_v3(payload: dict[str, Any]) -> dict[str, Any]:
    """Long-running complete F1-F4 proof activity; never runs inside reconcile."""

    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT)).resolve()
    pack_path, manifest, pack_file_sha256 = _read_bound_object(
        runtime_root,
        payload.get("foundation_closure_pack_ref"),
        payload.get("foundation_closure_pack_sha256"),
    )
    with contextlib.suppress(RuntimeError):
        activity.heartbeat("closure-pack-loaded", pack_file_sha256)
    proof = _verify_foundation_closure_pack_objects_v3(
        runtime_root=runtime_root,
        pack_path=pack_path.resolve(),
        manifest=manifest,
        pack_file_sha256=pack_file_sha256,
    )
    operation_id = str(payload.get("operation_id") or "foundation-v3").strip()
    proof_path = (
        runtime_root
        / "state"
        / "foundation_continuous"
        / operation_id
        / "closure_gate_proofs"
        / f"{proof['content_sha256']}.json"
    )
    _write_json_once(proof_path, proof)
    with contextlib.suppress(RuntimeError):
        activity.heartbeat("closure-proof-persisted", proof["content_sha256"])
    return {
        "ok": True,
        "proof": proof,
        "proof_ref": str(proof_path),
        "proof_sha256": _file_sha256(proof_path),
    }


def validate_foundation_closure_gate_proof_v3(
    *,
    runtime_root: Path,
    proof_binding: Mapping[str, Any],
    frontier: Mapping[str, Any],
) -> dict[str, Any]:
    """Lightweight current-state validation of a previously replayed proof."""

    _, proof, _ = _read_bound_object(
        runtime_root,
        proof_binding.get("proof_ref"),
        proof_binding.get("proof_sha256"),
    )
    proof_core = dict(proof)
    content_sha256 = proof_core.pop("content_sha256", None)
    if (
        proof.get("schema_version") != _PROOF_SCHEMA
        or proof.get("status") != "VERIFIED"
        or proof.get("allowed_execution_phase") != AUTONOMOUS_RESEARCH
        or proof.get("foundation_block_ids") != list(FOUNDATION_BLOCK_IDS)
        or canonical_sha256(proof_core) != content_sha256
        or proof_binding.get("content_sha256") != content_sha256
        or proof.get("verifier_source_sha256") != _verifier_source_sha256()
        or proof.get("closure_pack_ref") != frontier.get("foundation_closure_pack_ref")
        or proof.get("closure_pack_file_sha256") != frontier.get("foundation_closure_pack_sha256")
    ):
        raise ValueError("foundation closure gate proof identity is stale or invalid")
    pack_path = _resolve_runtime_ref(runtime_root, proof["closure_pack_ref"]).resolve()
    if not pack_path.is_file() or _file_sha256(pack_path) != proof["closure_pack_file_sha256"]:
        raise ValueError("foundation closure pack changed after gate verification")
    inventory = _physical_inventory(pack_path.parent)
    if len(inventory) != proof.get("closure_pack_inventory_count") or canonical_sha256(
        inventory
    ) != proof.get("closure_pack_inventory_sha256"):
        raise ValueError("foundation closure pack inventory changed after verification")
    blueprint_path = canonical_blueprint_path().resolve()
    if str(blueprint_path) != proof.get("blueprint_ref") or _file_sha256(
        blueprint_path
    ) != proof.get("blueprint_file_sha256"):
        raise ValueError("canonical blueprint changed after closure verification")
    authority_path = Path(str(proof.get("authority_manifest_ref") or "")).resolve()
    authority = validate_authority_snapshot(authority_path, require_live_match=True)
    if _file_sha256(authority_path) != proof.get("authority_manifest_file_sha256") or authority.get(
        "content_sha256"
    ) != proof.get("authority_manifest_content_sha256"):
        raise ValueError("live authority changed after closure verification")
    return proof


def evaluate_foundation_phase_gate_v3(
    *,
    execution_phase: str,
    closure_pack_candidate: bool,
    verified_proof: Mapping[str, Any] | None,
    foundation_closed_projection: bool,
    recorded_closure: Mapping[str, Any] | None,
    wait_seconds: int,
) -> dict[str, Any]:
    """Pure phase transition: construction -> proof milestone -> autonomous."""

    if execution_phase not in _EXECUTION_PHASES:
        raise ValueError("foundation frontier execution phase is invalid")
    recorded = dict(recorded_closure or {})
    proof = dict(verified_proof or {})
    if not proof:
        if foundation_closed_projection:
            return {
                "action": "WAIT",
                "reason": "FOUNDATION_CLOSED_PROJECTION_WITHOUT_VERIFIED_PROOF",
                "execution_phase": execution_phase,
                "formal_research_allowed": False,
                "wait_seconds": wait_seconds,
            }
        if closure_pack_candidate:
            return {
                "action": "VERIFY_CLOSURE_PROOF",
                "reason": "FOUNDATION_CLOSURE_PACK_REQUIRES_FULL_REPLAY",
                "execution_phase": execution_phase,
                "formal_research_allowed": False,
            }
        if execution_phase == FOUNDATION_CONSTRUCTION:
            return {
                "action": "ALLOW_CONSTRUCTION_CANARY",
                "reason": "FOUNDATION_CONSTRUCTION_ONLY",
                "execution_phase": execution_phase,
                "formal_research_allowed": False,
            }
        return {
            "action": "WAIT",
            "reason": "FOUNDATION_CLOSURE_PROOF_REQUIRED",
            "execution_phase": execution_phase,
            "formal_research_allowed": False,
            "wait_seconds": wait_seconds,
        }

    proof_identity = str(proof.get("content_sha256") or "")
    if not foundation_closed_projection:
        return {
            "action": "MILESTONE",
            "reason": "INDEPENDENTLY_VERIFIED_F1_F4_CLOSURE_PACK",
            "execution_phase": FOUNDATION_CONSTRUCTION,
            "formal_research_allowed": False,
            "foundation_closure_proof_content_sha256": proof_identity,
            "foundation_closure_pack_file_sha256": proof["closure_pack_file_sha256"],
            "foundation_closure_pack_content_sha256": proof["closure_pack_content_sha256"],
            "wait_seconds": wait_seconds,
        }
    if recorded.get("foundation_closure_proof_content_sha256") != proof_identity:
        return {
            "action": "WAIT",
            "reason": "RECORDED_CLOSURE_PROOF_IDENTITY_MISMATCH",
            "execution_phase": execution_phase,
            "formal_research_allowed": False,
            "wait_seconds": wait_seconds,
        }
    if execution_phase != AUTONOMOUS_RESEARCH:
        return {
            "action": "WAIT",
            "reason": "FOUNDATION_CLOSED_REQUIRES_AUTONOMOUS_RESEARCH_FRONTIER",
            "execution_phase": execution_phase,
            "formal_research_allowed": False,
            "wait_seconds": wait_seconds,
        }
    return {
        "action": "ALLOW_AUTONOMOUS_RESEARCH",
        "reason": "CURRENT_F1_F4_CLOSURE_PROOF_VERIFIED",
        "execution_phase": execution_phase,
        "formal_research_allowed": True,
        "foundation_closure_proof_content_sha256": proof_identity,
    }


@activity.defn(name="xinao.foundation.v3.inspect_phase_gate")
def inspect_foundation_phase_gate_v3(payload: dict[str, Any]) -> dict[str, Any]:
    """Read the frontier and proof receipt before any allocation or dispatch."""

    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT)).resolve()
    frontier_path, frontier, frontier_sha256 = _read_bound_object(
        runtime_root,
        payload.get("frontier_ref"),
        payload.get("frontier_sha256"),
    )
    execution_phase = str(frontier.get("execution_phase") or "")
    pack_ref = frontier.get("foundation_closure_pack_ref")
    pack_sha256 = frontier.get("foundation_closure_pack_sha256")
    if bool(pack_ref) != bool(pack_sha256):
        raise ValueError("foundation closure pack identity is partial")
    legacy_refs = {
        "foundation_closure_report_ref",
        "foundation_closure_verification_ref",
        "blueprint_snapshot_ref",
    }
    if not pack_ref and any(frontier.get(key) for key in legacy_refs):
        raise ValueError("scattered closure proof is not admitted by the V3 gate")
    proof_binding = payload.get("foundation_closure_gate_proof")
    proof = None
    if isinstance(proof_binding, Mapping) and proof_binding:
        proof = validate_foundation_closure_gate_proof_v3(
            runtime_root=runtime_root,
            proof_binding=proof_binding,
            frontier=frontier,
        )
    decision = evaluate_foundation_phase_gate_v3(
        execution_phase=execution_phase,
        closure_pack_candidate=bool(pack_ref and pack_sha256),
        verified_proof=proof,
        foundation_closed_projection=payload.get("foundation_closed") is True,
        recorded_closure=(
            payload.get("foundation_closure")
            if isinstance(payload.get("foundation_closure"), Mapping)
            else None
        ),
        wait_seconds=_bounded_seconds(frontier.get("wait_seconds"), default=300),
    )
    return {
        **decision,
        "frontier_ref": str(frontier_path),
        "frontier_sha256": frontier_sha256,
        "foundation_closure_pack_ref": str(pack_ref or ""),
        "foundation_closure_pack_sha256": str(pack_sha256 or ""),
    }


def _valid_sha256_v3(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _normalize_proof_binding_v3(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("V3 closure proof binding must be an object")
    binding = {
        key: str(value.get(key) or "")
        for key in (
            "proof_ref",
            "proof_sha256",
            "content_sha256",
            "closure_pack_ref",
            "closure_pack_file_sha256",
            "closure_pack_content_sha256",
        )
    }
    if (
        not binding["proof_ref"]
        or not _valid_sha256_v3(binding["proof_sha256"])
        or not _valid_sha256_v3(binding["content_sha256"])
        or not binding["closure_pack_ref"]
        or not _valid_sha256_v3(binding["closure_pack_file_sha256"])
        or not _valid_sha256_v3(binding["closure_pack_content_sha256"])
    ):
        raise ValueError("V3 closure proof binding identity is incomplete")
    return binding


def _initial_child_state_v3(initial: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = str(initial.get("operation_id") or "").strip()
    wave_id = str(initial.get("wave_id") or "").strip()
    correlation_id = str(initial.get("correlation_id") or "").strip()
    execution_phase = str(initial.get("execution_phase") or "")
    if not operation_id or not wave_id or not correlation_id:
        raise ValueError("operation_id, wave_id, and correlation_id are required")
    if execution_phase != AUTONOMOUS_RESEARCH:
        raise ValueError("V3 external workers require AUTONOMOUS_RESEARCH")
    frontier_ref = str(initial.get("frontier_ref") or "").strip()
    frontier_sha256 = str(initial.get("frontier_sha256") or "").lower()
    if not frontier_ref or not _valid_sha256_v3(frontier_sha256):
        raise ValueError("V3 external workers require a hash-bound frontier")
    proof_binding = _normalize_proof_binding_v3(initial.get("foundation_closure_gate_proof"))
    return {
        "schema_version": _CHILD_STATE_SCHEMA,
        "operation_id": operation_id,
        "runtime_root": str(initial.get("runtime_root") or DEFAULT_RUNTIME_ROOT),
        "execution_phase": execution_phase,
        "frontier_ref": frontier_ref,
        "frontier_sha256": frontier_sha256,
        "foundation_closure_gate_proof": proof_binding,
        "wave_id": wave_id,
        "wave_sequence": int(initial.get("wave_sequence") or 0),
        "correlation_id": correlation_id,
        "payload_ref": str(initial.get("payload_ref") or ""),
        "payload_sha256": str(initial.get("payload_sha256") or ""),
        "external_task_queue": str(
            initial.get("external_task_queue") or DEFAULT_EXTERNAL_TASK_QUEUE
        ),
        "external_provider_id": str(
            initial.get("external_provider_id") or DEFAULT_EXTERNAL_PROVIDER_ID
        ),
        "external_model": str(initial.get("external_model") or DEFAULT_EXTERNAL_MODEL),
        "submission_timeout_seconds": _bounded_seconds(
            initial.get("submission_timeout_seconds"), default=3_600
        ),
        "status": "REQUESTED",
        "external_started": {},
        "external_completed": {},
        "external_failed": {},
        "verification": {},
        "signal_audit": {},
        "duplicate_signals": 0,
        "signal_conflicts": [],
        "cancel_requested": False,
        "last_state_ref": "",
        "last_state_hash": "",
        "revision": 1,
    }


@activity.defn(name="xinao.foundation.v3.verify_wave_result")
def verify_external_wave_result_v3(payload: dict[str, Any]) -> dict[str, Any]:
    """Revalidate the live closure proof before accepting one formal wave result."""

    if payload.get("execution_phase") != AUTONOMOUS_RESEARCH:
        raise ValueError("V3 formal wave result has an invalid execution phase")
    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT)).resolve()
    _, frontier, _ = _read_bound_object(
        runtime_root,
        payload.get("frontier_ref"),
        payload.get("frontier_sha256"),
    )
    proof = validate_foundation_closure_gate_proof_v3(
        runtime_root=runtime_root,
        proof_binding=_normalize_proof_binding_v3(payload.get("foundation_closure_gate_proof")),
        frontier=frontier,
    )
    result = verify_external_wave_result(payload)
    return {
        **result,
        "execution_phase": AUTONOMOUS_RESEARCH,
        "foundation_closure_proof_content_sha256": proof["content_sha256"],
    }


@workflow.defn(
    name=CHILD_WORKFLOW_NAME_V3,
    versioning_behavior=VersioningBehavior.PINNED,
)
class FoundationWaveChildWorkflowV3:
    """Phase-qualified external wave; construction work cannot enter this type."""

    @workflow.init
    def __init__(self, initial: dict[str, Any]) -> None:
        self._state = _initial_child_state_v3(initial)

    @workflow.signal(name="external_started")
    def external_started(self, payload: dict[str, Any]) -> None:
        _accept_external_signal(self._state, "started", payload)

    @workflow.signal(name="external_completed")
    def external_completed(self, payload: dict[str, Any]) -> None:
        _accept_external_signal(self._state, "completed", payload)

    @workflow.signal(name="external_failed")
    def external_failed(self, payload: dict[str, Any]) -> None:
        _accept_external_signal(self._state, "failed", payload)

    @workflow.query(name="state")
    def state(self) -> dict[str, Any]:
        return _child_snapshot(self._state)

    async def _persist(self) -> None:
        receipt = await workflow.execute_activity(
            persist_foundation_state,
            {
                "runtime_root": self._state["runtime_root"],
                "operation_id": self._state["operation_id"],
                "entity_kind": "wave-v3",
                "entity_id": self._state["wave_id"],
                "snapshot": _child_snapshot(self._state),
            },
            **_activity_options(),
        )
        self._state["last_state_ref"] = receipt["artifact_ref"]
        self._state["last_state_hash"] = receipt["snapshot_hash"]

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        del initial
        self._state["workflow_id"] = workflow.info().workflow_id
        self._state["run_id"] = workflow.info().run_id
        await self._persist()
        try:
            try:
                await workflow.wait_condition(
                    lambda: bool(
                        self._state["external_completed"] or self._state["external_failed"]
                    ),
                    timeout=timedelta(seconds=int(self._state["submission_timeout_seconds"])),
                )
            except asyncio.TimeoutError:
                self._state["external_failed"] = {
                    "error_type": "EXTERNAL_SUBMISSION_TIMEOUT",
                    "message": "no completed external one-shot arrived inside the wave window",
                }
                self._state["status"] = "EXTERNAL_TIMEOUT"
                self._state["revision"] += 1
            if self._state["external_failed"]:
                await self._persist()
                await workflow.wait_condition(workflow.all_handlers_finished)
                return _child_snapshot(self._state)
            completed = dict(self._state["external_completed"])
            try:
                verification = await workflow.execute_activity(
                    verify_external_wave_result_v3,
                    {
                        "runtime_root": self._state["runtime_root"],
                        "operation_id": self._state["operation_id"],
                        "execution_phase": self._state["execution_phase"],
                        "frontier_ref": self._state["frontier_ref"],
                        "frontier_sha256": self._state["frontier_sha256"],
                        "foundation_closure_gate_proof": self._state[
                            "foundation_closure_gate_proof"
                        ],
                        "wave_id": self._state["wave_id"],
                        "correlation_id": self._state["correlation_id"],
                        "result_ref": completed["result_ref"],
                        "result_sha256": completed["result_sha256"],
                        "payload_ref": self._state["payload_ref"],
                        "payload_sha256": self._state["payload_sha256"],
                        "external_task_queue": self._state["external_task_queue"],
                        "external_provider_id": self._state["external_provider_id"],
                        "external_model": self._state["external_model"],
                        "external_workflow_id": completed["workflow_id"],
                        "external_run_id": completed["run_id"],
                    },
                    **_activity_options(),
                )
            except ActivityError as exc:
                self._state["external_failed"] = {
                    "error_type": "EXTERNAL_RESULT_VERIFICATION_FAILED",
                    "message": str(exc)[:400],
                }
                self._state["status"] = "VERIFY_FAILED"
            else:
                self._state["verification"] = verification
                self._state["status"] = "COMPLETED"
            self._state["revision"] += 1
            await self._persist()
            await workflow.wait_condition(workflow.all_handlers_finished)
            return _child_snapshot(self._state)
        except asyncio.CancelledError:
            self._state["cancel_requested"] = True
            self._state["status"] = "CANCELLING"
            self._state["revision"] += 1
            started = self._state.get("external_started") or {}
            external_workflow_id = str(started.get("workflow_id") or "")
            if external_workflow_id:
                external = workflow.get_external_workflow_handle(
                    external_workflow_id,
                    run_id=str(started.get("run_id") or "") or None,
                )
                with contextlib.suppress(TemporalError):
                    await external.cancel(reason="foundation V3 parent stopped current wave")
            self._state["status"] = "CANCELED"
            with contextlib.suppress(TemporalError, asyncio.CancelledError):
                await asyncio.shield(self._persist())
            raise


def _validate_state_invariants_v3(state: Mapping[str, Any]) -> None:
    if state.get("schema_version") != _STATE_SCHEMA:
        raise ValueError("V3 state schema is invalid")
    gate_state = str(state.get("gate_state") or "")
    execution_phase = str(state.get("execution_phase") or "")
    if gate_state not in {
        FOUNDATION_CONSTRUCTION,
        "MILESTONE_RECORDED",
        AUTONOMOUS_RESEARCH,
    }:
        raise ValueError("V3 gate state is invalid")
    if execution_phase not in _EXECUTION_PHASES:
        raise ValueError("V3 state execution phase is invalid")
    for field in ("closed_work_keys_by_phase", "failed_work_keys_by_phase"):
        values = state.get(field)
        if (
            not isinstance(values, Mapping)
            or set(values) != set(_EXECUTION_PHASES)
            or any(not isinstance(values[phase], list) for phase in _EXECUTION_PHASES)
        ):
            raise ValueError(f"V3 {field} inventory is not phase exact")
    counts = state.get("formal_route_counts")
    if (
        not isinstance(counts, Mapping)
        or set(counts) != {"allocation", "delegate", "worker"}
        or any(
            not isinstance(counts[key], int) or counts[key] < 0
            for key in ("allocation", "delegate", "worker")
        )
    ):
        raise ValueError("V3 formal route counters are invalid")
    proof_raw = state.get("foundation_closure_gate_proof")
    proof = _normalize_proof_binding_v3(proof_raw) if proof_raw else None
    closed = state.get("foundation_closed") is True
    closure = state.get("foundation_closure")
    if not isinstance(closure, Mapping):
        raise ValueError("V3 foundation closure state must be an object")
    milestone_revision = int(state.get("milestone_recorded_revision") or 0)
    formal_revision = int(state.get("formal_gate_opened_revision") or 0)
    if closed:
        if proof is None or gate_state == FOUNDATION_CONSTRUCTION or milestone_revision < 1:
            raise ValueError("V3 closed projection lacks its proof milestone")
        if closure.get("foundation_closure_proof_content_sha256") != proof["content_sha256"]:
            raise ValueError("V3 closure projection differs from its proof binding")
    elif gate_state != FOUNDATION_CONSTRUCTION or execution_phase != FOUNDATION_CONSTRUCTION:
        raise ValueError("V3 phase advanced without a recorded closure")
    if gate_state == AUTONOMOUS_RESEARCH:
        if (
            not closed
            or execution_phase != AUTONOMOUS_RESEARCH
            or formal_revision <= milestone_revision
        ):
            raise ValueError("V3 autonomous gate history boundary is invalid")
    elif execution_phase != FOUNDATION_CONSTRUCTION or formal_revision != 0:
        raise ValueError("V3 formal phase projection advanced before its gate")


def _initial_state_v3(initial: Mapping[str, Any]) -> dict[str, Any]:
    resume = initial.get("resume_state")
    if isinstance(resume, Mapping):
        state = json.loads(json.dumps(resume))
        if state.get("schema_version") != _STATE_SCHEMA:
            raise ValueError("V3 continuation requires a V3 state snapshot")
        state["run_generation"] = int(state.get("run_generation") or 0) + 1
        state["cycles_since_continue_as_new"] = 0
        state["current_wave"] = None
        state["status"] = "RECONCILING"
        state["next_wake_at"] = ""
        state["revision"] = int(state.get("revision") or 0) + 1
        _validate_state_invariants_v3(state)
        return state

    operation_id = str(initial.get("operation_id") or "").strip()
    frontier_ref = str(initial.get("frontier_ref") or "").strip()
    frontier_sha256 = str(initial.get("frontier_sha256") or "").lower()
    roll_forward_ref = str(initial.get("roll_forward_manifest_ref") or "").strip()
    roll_forward_sha256 = str(initial.get("roll_forward_manifest_sha256") or "").lower()
    owner_generation = int(initial.get("owner_generation") or 0)
    if (
        not operation_id
        or not frontier_ref
        or not _valid_sha256_v3(frontier_sha256)
        or not roll_forward_ref
        or not _valid_sha256_v3(roll_forward_sha256)
        or owner_generation < 1
    ):
        raise ValueError("hash-bound frontier and roll-forward identities are required")
    state = {
        "schema_version": _STATE_SCHEMA,
        "operation_id": operation_id,
        "runtime_root": str(initial.get("runtime_root") or DEFAULT_RUNTIME_ROOT),
        "frontier_ref": frontier_ref,
        "frontier_sha256": frontier_sha256,
        "scope": "foundation",
        "owner_generation": owner_generation,
        "run_generation": 0,
        "roll_forward_manifest_ref": roll_forward_ref,
        "roll_forward_manifest_sha256": roll_forward_sha256,
        "roll_forward_verification": {},
        "execution_phase": FOUNDATION_CONSTRUCTION,
        "gate_state": FOUNDATION_CONSTRUCTION,
        "foundation_closed": False,
        "foundation_closure": {},
        "foundation_closure_gate_proof": {},
        "milestone_recorded_revision": 0,
        "formal_gate_opened_revision": 0,
        "closed_work_keys_by_phase": {
            FOUNDATION_CONSTRUCTION: [],
            AUTONOMOUS_RESEARCH: [],
        },
        "failed_work_keys_by_phase": {
            FOUNDATION_CONSTRUCTION: [],
            AUTONOMOUS_RESEARCH: [],
        },
        "batch_execution_phase": "",
        "formal_route_counts": {"allocation": 0, "delegate": 0, "worker": 0},
        "status": "PENDING",
        "current_wave": None,
        "last_wave_result": {},
        "last_decision": {},
        "last_state_ref": "",
        "last_state_hash": "",
        "cycles_since_continue_as_new": 0,
        "max_cycles_per_run": max(
            1,
            min(int(initial.get("max_cycles_per_run") or 100), 1_000),
        ),
        "paused": bool(initial.get("paused", False)),
        "stop_requested": False,
        "idle_cycles": 0,
        "default_wait_seconds": _bounded_seconds(initial.get("default_wait_seconds"), default=300),
        "next_wake_at": "",
        "wake_revision": 0,
        "material_signal_ids": [],
        "material_signal_errors": [],
        "duplicate_material_signals": 0,
        "control_audit": [],
        "revision": 1,
    }
    _validate_state_invariants_v3(state)
    return state


def _continuation_input_v3(state: Mapping[str, Any]) -> dict[str, Any]:
    _validate_state_invariants_v3(state)
    compact = json.loads(json.dumps(state))
    compact["current_wave"] = None
    compact["last_decision"] = {
        key: value
        for key, value in dict(compact.get("last_decision") or {}).items()
        if key != "wave"
    }
    _validate_state_invariants_v3(compact)
    return {"resume_state": compact}


def _closure_proof_binding_v3(result: Mapping[str, Any]) -> dict[str, str]:
    proof = result.get("proof")
    if not isinstance(proof, Mapping):
        raise ValueError("closure proof activity did not return a proof object")
    binding = {
        "proof_ref": str(result.get("proof_ref") or ""),
        "proof_sha256": str(result.get("proof_sha256") or ""),
        "content_sha256": str(proof.get("content_sha256") or ""),
        "closure_pack_ref": str(proof.get("closure_pack_ref") or ""),
        "closure_pack_file_sha256": str(proof.get("closure_pack_file_sha256") or ""),
        "closure_pack_content_sha256": str(proof.get("closure_pack_content_sha256") or ""),
    }
    return _normalize_proof_binding_v3(binding)


@workflow.defn(
    name=PARENT_WORKFLOW_NAME_V3,
    versioning_behavior=VersioningBehavior.PINNED,
)
class FoundationContinuousWorkflowV3:
    """PINNED phase gate; formal work is impossible before a proof boundary."""

    @workflow.init
    def __init__(self, initial: dict[str, Any]) -> None:
        self._state = _initial_state_v3(initial)

    @workflow.query(name="state")
    def state(self) -> dict[str, Any]:
        return _parent_snapshot(self._state)

    @workflow.signal(name="material_changed")
    def material_changed(self, payload: dict[str, Any]) -> None:
        signal_id = str(payload.get("signal_id") or "").strip() or _canonical_hash(payload)
        if signal_id in self._state["material_signal_ids"]:
            self._state["duplicate_material_signals"] += 1
            return
        new_ref = str(payload.get("frontier_ref") or "").strip()
        new_sha256 = str(payload.get("frontier_sha256") or "").lower()
        if (new_ref or new_sha256) and (not new_ref or not _valid_sha256_v3(new_sha256)):
            self._state["material_signal_errors"].append(
                {
                    "signal_id": signal_id,
                    "reason": "FRONTIER_IDENTITY_PARTIAL_OR_INVALID",
                }
            )
            self._state["revision"] += 1
            return
        if new_ref:
            self._state["frontier_ref"] = new_ref
            self._state["frontier_sha256"] = new_sha256
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
                "entity_kind": "parent-v3",
                "entity_id": workflow.info().workflow_id,
                "snapshot": _parent_snapshot(self._state),
            },
            **_activity_options(),
        )
        self._state["last_state_ref"] = receipt["artifact_ref"]
        self._state["last_state_hash"] = receipt["snapshot_hash"]

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

    async def _wait_after(self, decision: Mapping[str, Any]) -> None:
        self._state["status"] = "WAITING"
        await self._persist()
        await self._wait(
            _bounded_seconds(
                decision.get("wait_seconds"),
                default=int(self._state["default_wait_seconds"]),
            )
        )

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
                    or int(self._state["cycles_since_continue_as_new"])
                    >= int(self._state["max_cycles_per_run"])
                ):
                    await workflow.wait_condition(workflow.all_handlers_finished)
                    workflow.continue_as_new(_continuation_input_v3(self._state))
                if self._state["paused"]:
                    self._state["status"] = "PAUSED"
                    await self._persist()
                    await workflow.wait_condition(
                        lambda: bool(not self._state["paused"] or self._state["stop_requested"])
                    )
                    continue

                self._state["status"] = "INSPECTING_PHASE_GATE"
                try:
                    decision = await workflow.execute_activity(
                        inspect_foundation_phase_gate_v3,
                        {
                            "runtime_root": self._state["runtime_root"],
                            "frontier_ref": self._state["frontier_ref"],
                            "frontier_sha256": self._state["frontier_sha256"],
                            "foundation_closed": self._state["foundation_closed"],
                            "foundation_closure": self._state["foundation_closure"],
                            "foundation_closure_gate_proof": self._state[
                                "foundation_closure_gate_proof"
                            ],
                        },
                        **_activity_options(),
                    )
                except ActivityError as exc:
                    decision = {
                        "action": "WAIT",
                        "reason": "PHASE_GATE_INSPECTION_FAILED",
                        "formal_research_allowed": False,
                        "error": str(exc)[:400],
                        "wait_seconds": self._state["default_wait_seconds"],
                    }
                self._state["last_decision"] = dict(decision)
                self._state["cycles_since_continue_as_new"] += 1
                self._state["revision"] += 1
                action = str(decision.get("action") or "WAIT")

                if action == "VERIFY_CLOSURE_PROOF":
                    self._state["status"] = "VERIFYING_CLOSURE_PROOF"
                    try:
                        proof_result = await workflow.execute_activity(
                            verify_foundation_closure_pack_v3,
                            {
                                "runtime_root": self._state["runtime_root"],
                                "operation_id": self._state["operation_id"],
                                "foundation_closure_pack_ref": decision[
                                    "foundation_closure_pack_ref"
                                ],
                                "foundation_closure_pack_sha256": decision[
                                    "foundation_closure_pack_sha256"
                                ],
                            },
                            **_activity_options(timeout_seconds=_LONG_PROOF_TIMEOUT_SECONDS),
                        )
                        binding = _closure_proof_binding_v3(proof_result)
                    except (ActivityError, ValueError) as exc:
                        failed = {
                            "action": "WAIT",
                            "reason": "CLOSURE_PROOF_VERIFICATION_FAILED",
                            "formal_research_allowed": False,
                            "error": str(exc)[:400],
                            "wait_seconds": self._state["default_wait_seconds"],
                        }
                        self._state["last_decision"] = failed
                        await self._wait_after(failed)
                        continue
                    self._state["foundation_closure_gate_proof"] = binding
                    self._state["status"] = "CLOSURE_PROOF_VERIFIED"
                    self._state["revision"] += 1
                    await self._persist()
                    continue

                if action == "MILESTONE":
                    if self._state["gate_state"] != FOUNDATION_CONSTRUCTION:
                        raise RuntimeError("closure milestone can only leave construction once")
                    self._state["foundation_closed"] = True
                    self._state["foundation_closure"] = {
                        key: value
                        for key, value in decision.items()
                        if key.startswith("foundation_closure_")
                    }
                    self._state["gate_state"] = "MILESTONE_RECORDED"
                    self._state["scope"] = "mainline-global"
                    self._state["status"] = "MILESTONE_RECORDED"
                    self._state["milestone_recorded_revision"] = int(self._state["revision"]) + 1
                    self._state["revision"] += 1
                    await self._wait_after(decision)
                    continue

                if action == "ALLOW_AUTONOMOUS_RESEARCH":
                    if self._state["gate_state"] != AUTONOMOUS_RESEARCH:
                        if self._state["gate_state"] != "MILESTONE_RECORDED":
                            raise RuntimeError(
                                "autonomous research requires a recorded closure milestone"
                            )
                        self._state["gate_state"] = AUTONOMOUS_RESEARCH
                        self._state["execution_phase"] = AUTONOMOUS_RESEARCH
                        self._state["status"] = "FORMAL_GATE_OPENED"
                        self._state["formal_gate_opened_revision"] = (
                            int(self._state["revision"]) + 1
                        )
                        self._state["revision"] += 1
                        await self._persist()
                        continue
                    unavailable = {
                        **dict(decision),
                        "action": "WAIT",
                        "reason": "AUTONOMOUS_COMPILER_UNAVAILABLE",
                        "formal_research_allowed": False,
                        "wait_seconds": self._state["default_wait_seconds"],
                    }
                    self._state["last_decision"] = unavailable
                    await self._wait_after(unavailable)
                    continue

                await self._wait_after(decision)
        except asyncio.CancelledError:
            self._state["stop_requested"] = True
            self._state["status"] = "CANCELED"
            self._state["revision"] += 1
            with contextlib.suppress(TemporalError, asyncio.CancelledError):
                await asyncio.shield(self._persist())
            raise


def temporal_exports_v3() -> tuple[list[type], list[Any]]:
    """Explicit V3 registry; existing V1/V2 workflow types remain separate."""

    return (
        [FoundationContinuousWorkflowV3, FoundationWaveChildWorkflowV3],
        [
            inspect_foundation_phase_gate_v3,
            persist_foundation_state,
            verify_foundation_closure_pack_v3,
            verify_external_wave_result_v3,
            verify_roll_forward_manifest_v2,
        ],
    )


__all__ = [
    "AUTONOMOUS_RESEARCH",
    "CHILD_WORKFLOW_NAME_V3",
    "FOUNDATION_CONSTRUCTION",
    "FoundationContinuousWorkflowV3",
    "FoundationWaveChildWorkflowV3",
    "PARENT_WORKFLOW_NAME_V3",
    "_continuation_input_v3",
    "_initial_child_state_v3",
    "_initial_state_v3",
    "_validate_state_invariants_v3",
    "evaluate_foundation_phase_gate_v3",
    "inspect_foundation_phase_gate_v3",
    "temporal_exports_v3",
    "validate_foundation_closure_gate_proof_v3",
    "verify_foundation_closure_pack_v3",
    "verify_external_wave_result_v3",
]
