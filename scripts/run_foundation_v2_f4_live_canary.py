#!/usr/bin/env python3
"""Run the bounded positive F4 V2 canary on isolated Temporal queues.

The script is a finite callback bridge, not a daemon.  It runs one width-1
producer/critique/verifier batch, recreates the isolated V2 worker, then runs
one width-2 batch.  A bounded recovery ladder continues serving compensation
waves instead of starving the controller after a content-level rejection.
Canonical V1 and the Docker LangGraph worker are only observed/consumed;
neither is recreated by this script.
"""

from __future__ import annotations

# ruff: noqa: E402,I001 -- standalone entrypoint exposes repository packages first.

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_BOOT_REPO = Path(__file__).resolve().parents[1]
for _candidate in (_BOOT_REPO, _BOOT_REPO / "xinao_discovery" / "src"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from services.agent_runtime.foundation_continuous_workflow import (
    FoundationWaveChildWorkflowV1,
    persist_foundation_state,
    verify_external_wave_result,
)
from services.agent_runtime.foundation_continuous_workflow_v2 import (
    FoundationContinuousWorkflowV2,
    finalize_research_fan_in_v2,
    generate_f4_method_negative_control_receipts,
    inspect_external_wave_result_v2,
    reconcile_foundation_frontier_v2,
    verify_roll_forward_manifest_v2,
)
from temporalio.client import Client
from temporalio.worker import Worker
from xinao.canonical import canonical_sha256
from xinao.foundation.research_candidate_source import (
    compile_f4_canary_candidate_snapshot,
    compile_f4_canary_candidate_source,
)
from xinao.foundation.research_factory import (
    admit_open_method,
    compile_research_portfolio_allocation,
    research_factory_artifact_manifest,
)
from xinao.foundation.selection_manifest import (
    compile_default_independent_selection_manifest,
)

REPO = _BOOT_REPO
RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
EVIDENCE_PARENT = RUNTIME / "projects" / "xinao_discovery" / "evidence"
DUAL_PROJECT = REPO / "projects" / "dual-brain-coordination"
DUAL_PYTHON = DUAL_PROJECT / ".venv" / "Scripts" / "python.exe"
CANONICAL_RUNNER = DUAL_PROJECT / "scripts" / "run_canonical_grok_transaction.py"
CANONICAL_DEPLOYMENT_MANIFEST = (
    DUAL_PROJECT / "adapters" / "temporal" / "canonical_grok_host_deployment.v1.json"
)
V1_WORKFLOW_SOURCE = (
    REPO / "services" / "agent_runtime" / "foundation_continuous_workflow.py"
)
ROLL_FORWARD_SOURCE = (
    EVIDENCE_PARENT / "xinao-v2-cutover-canary-20260714T202853" / "roll_forward_manifest.json"
)
F3_PACK = EVIDENCE_PARENT / "xinao-f3-evidence-20260714T200713"
WORLD_SNAPSHOT_SHA256 = "758d953f24cf99bed074f18797172f5b96ec1b336cdd0d87fd189a0124339a0c"
KNOWLEDGE_CUTOFF = "2026-07-14T00:00:00Z"
CANONICAL_PROCESS_TIMEOUT_SECONDS = 1_900.0
CANONICAL_HANDSHAKE_TIMEOUT_SECONDS = 120.0
CANONICAL_CANCEL_TIMEOUT_SECONDS = 30.0
TERMINAL_WORKFLOW_STATUSES = frozenset(
    {"CANCELED", "COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"}
)
TRANSACTION_KEY_SEMANTICS = (
    "same_key_reconnects_exact_execution;new_execution_requires_new_key"
)
F4_DOCKER_MODEL = "grok-composer-2.5-fast"
MAX_WORKER_A_REQUESTS = 8
MAX_WORKER_B_REQUESTS = 12
WAVE_SETTLE_TIMEOUT_SECONDS = 180.0


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)
    return str(path), hashlib.sha256(raw).hexdigest()


def canonical_deployment_seal() -> dict[str, object]:
    manifest = json.loads(CANONICAL_DEPLOYMENT_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("canonical Grok deployment manifest must be an object")
    expected_hashes = manifest.get("source_hashes")
    if not isinstance(expected_hashes, dict) or not expected_hashes:
        raise ValueError("canonical Grok deployment manifest has no source hashes")
    actual_hashes = {
        str(relative): file_sha256(DUAL_PROJECT / str(relative)) for relative in expected_hashes
    }
    digest = hashlib.sha256(
        json.dumps(
            actual_hashes,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        actual_hashes != expected_hashes
        or manifest.get("source_digest_sha256") != digest
        or manifest.get("build_id") != digest[:32]
        or manifest.get("use_worker_versioning") is not True
    ):
        raise ValueError("canonical Grok deployment seal drifted")
    return {
        "deployment_name": str(manifest["deployment_name"]),
        "build_id": str(manifest["build_id"]),
        "source_digest_sha256": digest,
        "manifest_ref": str(CANONICAL_DEPLOYMENT_MANIFEST),
        "manifest_sha256": file_sha256(CANONICAL_DEPLOYMENT_MANIFEST),
        "source_count": len(actual_hashes),
    }


def versioned_source_graph(source_count: int) -> dict[str, object]:
    core: dict[str, object] = {
        "object_type": "SourceDependencyGraphVersion",
        "sources": [
            {
                "source_id": f"source-{index}",
                "origin_cluster_id": f"origin-{index}",
            }
            for index in range(source_count)
        ],
        "origin_clusters": [
            {
                "origin_cluster_id": f"origin-{index}",
                "member_source_ids": [f"source-{index}"],
            }
            for index in range(source_count)
        ],
        "edges": [],
        "summary": {
            "independent_origin_cluster_count": source_count,
            "source_count": source_count,
        },
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"SourceDependencyGraphVersion@{digest[:16]}",
        "content_sha256": digest,
    }


def build_method(pack: Path) -> tuple[dict[str, Any], str, str, str]:
    method_id = "method.f4-evidence-bound-canary.v1"
    artifacts: dict[str, object] = {
        "executable": {
            "schema_version": "xinao.f4_prompted_method_executable.v1",
            "method_id": method_id,
            "method_evidence_rule": ("F4_EVIDENCE_BOUND_CANARY:{stage}:{work_key_last_12}"),
            "instructions": [
                "Read the complete bound method material supplied in the prompt.",
                "Preserve the exact work key, actor identity, and upstream refs.",
                "Derive method_evidence from the executable rule and actual method_input.",
            ],
        },
        "input_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "schema_version": {"const": "xinao.f4_method_input.v1"},
                "work_key": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "stage": {"enum": ["PRODUCER", "CRITIQUE", "VERIFIER"]},
                "actor_id": {"type": "string", "minLength": 1},
                "method_id": {"const": method_id},
                "method_admission_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "method_material_bundle_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "work_item_content_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "upstream": {
                    "type": "object",
                    "properties": {
                        "producer_ref": {"type": "string"},
                        "producer_sha256": {"type": "string"},
                        "critique_ref": {"type": "string"},
                        "critique_sha256": {"type": "string"},
                    },
                    "required": [
                        "producer_ref",
                        "producer_sha256",
                        "critique_ref",
                        "critique_sha256",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": [
                "schema_version",
                "work_key",
                "stage",
                "actor_id",
                "method_id",
                "method_admission_hash",
                "method_material_bundle_sha256",
                "work_item_content_sha256",
                "upstream",
            ],
            "additionalProperties": False,
        },
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "applied": {"const": True},
                "stage": {"enum": ["PRODUCER", "CRITIQUE", "VERIFIER"]},
                "work_key": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "method_evidence": {"type": "string", "minLength": 12},
            },
            "required": ["applied", "stage", "work_key", "method_evidence"],
            "additionalProperties": False,
        },
        "verification_protocol": {
            "checks": [
                "BUNDLE_EQ",
                "INPUT_SCHEMA_VALID",
                "METHOD_EVIDENCE_RULE",
                "OUTPUT_SCHEMA_VALID",
                "STAGE_EQ",
                "UPSTREAM_EQ",
                "WORK_KEY_EQ",
            ],
            "protocol_id": "xinao.f4_evidence_bound_canary_protocol.v1",
        },
        "failure_contract": {
            "contract_id": "xinao.f4_failure_contract.v1",
            "on_binding_failure": "REJECT_VERIFIED_OUTPUT",
            "non_verified_outcomes": [
                "CHANGES_REQUESTED",
                "FAILED",
                "FALSIFIED",
                "NO_ACTION",
                "PARTIAL",
                "REJECTED",
            ],
        },
    }
    refs: dict[str, str] = {}
    digests: dict[str, str] = {}
    for role, value in artifacts.items():
        ref, digest = write_json(pack / "inputs" / "method" / f"{role}.json", value)
        refs[role] = ref
        digests[ref] = digest
    materials = {
        role: {
            "artifact_ref": refs[role],
            "sha256": digests[refs[role]],
        }
        for role in (
            "executable",
            "input_schema",
            "output_schema",
            "verification_protocol",
            "failure_contract",
        )
    }
    negative_receipts = generate_f4_method_negative_control_receipts(
        RUNTIME,
        {
            "method_id": method_id,
            "method_admission_hash": "1" * 64,
            "method_executable_ref": materials["executable"]["artifact_ref"],
            "method_executable_sha256": materials["executable"]["sha256"],
            "method_material_bundle_sha256": "2" * 64,
            "materials": materials,
        },
    )
    negative_controls: list[dict[str, str]] = []
    for check_id, receipt in sorted(negative_receipts.items()):
        ref, digest = write_json(
            pack / "inputs" / "method" / "negative-controls" / f"{check_id}.json",
            receipt,
        )
        negative_controls.append(
            {
                "check_id": check_id,
                "status": "REJECTED",
                "evidence_ref": ref,
                "sha256": digest,
            }
        )
    canary_evidence = {
        "status": "VERIFIED",
        "method_id": method_id,
        "executable_sha256": digests[refs["executable"]],
        "input_schema_sha256": digests[refs["input_schema"]],
        "output_schema_sha256": digests[refs["output_schema"]],
        "verification_protocol_sha256": digests[refs["verification_protocol"]],
        "failure_contract_sha256": digests[refs["failure_contract"]],
        "negative_controls": negative_controls,
    }
    canary_ref, canary_digest = write_json(
        pack / "inputs" / "method" / "canary_evidence.json",
        canary_evidence,
    )
    refs["canary_evidence"] = canary_ref
    digests[canary_ref] = canary_digest
    registration = {
        "method_id": method_id,
        "method_kind": "evidence-bound-runtime-canary",
        "executable_ref": refs["executable"],
        "executable_sha256": digests[refs["executable"]],
        "input_schema_ref": refs["input_schema"],
        "input_schema_sha256": digests[refs["input_schema"]],
        "output_schema_ref": refs["output_schema"],
        "output_schema_sha256": digests[refs["output_schema"]],
        "verification_protocol_ref": refs["verification_protocol"],
        "verification_protocol_sha256": digests[refs["verification_protocol"]],
        "failure_contract_ref": refs["failure_contract"],
        "failure_contract_sha256": digests[refs["failure_contract"]],
        "source_refs": ("local:f4-positive-canary",),
        "deterministic_seed_policy": "work key and immutable snapshots bind every turn",
        "canary_evidence_ref": refs["canary_evidence"],
        "canary_evidence_sha256": digests[refs["canary_evidence"]],
    }
    admission = admit_open_method(registration, resolved_content_hashes=digests)
    return (
        admission,
        canonical_sha256(admission["registration"]),
        str(admission["admission_sha256"]),
        refs["output_schema"],
    )


def work_item(
    index: int,
    *,
    registration_hash: str,
    admission_hash: str,
    selection_hash: str,
    output_schema_ref: str,
) -> dict[str, object]:
    return {
        "schema_version": "xinao.research_work_item.v2",
        "physical_role": "ACTIVE_SETTLEMENT",
        "kind": "f4-positive-runtime-canary",
        "source_ref": f"source-{index}",
        "source_dependency_refs": [],
        "active_settlement_refs": [f"BO000{index + 1}"],
        "upstream_work_keys": [],
        "intent_slice": f"F4:positive-canary:{index}",
        "selection_manifest_hash": selection_hash,
        "method_id": "method.f4-evidence-bound-canary.v1",
        "method_registration_hash": registration_hash,
        "method_admission_hash": admission_hash,
        "world_snapshot_hash": hashlib.sha256(b"f4-live-world").hexdigest(),
        "input_snapshot_hashes": [hashlib.sha256(f"f4-live-input:{index}".encode()).hexdigest()],
        "knowledge_cutoff": "2026-07-14T00:00:00Z",
        "budget_ref": "budget:f4-positive-canary",
        "error_budget_ledger_ref": "ledger:f4-positive-canary",
        "output_schema_ref": output_schema_ref,
        "handoff_schema_ref": "xinao.agent_handoff.v1",
        "evidence_schema_ref": "xinao.evidence_manifest.v1",
        "correlation_id": f"f4-positive-canary:{index}",
        "expected_information_gain": "prove live durable three-stage execution",
        "evidence_requirements": ["actual-grok-model", "operation-spec", "temporal-history"],
        "authority_scope": ["read:bound-canary-material"],
        "write_boundary": "READ_ONLY_WORKER",
    }


def prepare_inputs(
    pack: Path,
    *,
    operation_id: str,
    external_queue: str,
) -> dict[str, str]:
    graph = versioned_source_graph(3)
    graph_ref, graph_hash = write_json(
        pack / "inputs" / "source_dependency_graph.json",
        graph,
    )
    capacity_ref, capacity_hash = write_json(
        pack / "inputs" / "capacity_observation.json",
        {
            "schema_version": "xinao.capacity_observation.v1",
            "host_state": "available",
            "available_slots": 2,
            "queue_depth": 13,
            "verified_canary": True,
        },
    )
    selection = compile_default_independent_selection_manifest()
    selection_ref, selection_hash = write_json(
        pack / "inputs" / "selection_manifest.json",
        selection.model_dump(mode="json"),
    )
    factory_ref, factory_hash = write_json(
        pack / "inputs" / "research_factory_manifest.json",
        research_factory_artifact_manifest(),
    )
    admission, _, _, _ = build_method(pack)
    registrations = {
        "method.f4-evidence-bound-canary.v1": admission,
    }
    registry_ref, registry_hash = write_json(
        pack / "inputs" / "method_registry.json",
        {"registrations": registrations},
    )
    template_ref, template_hash = write_json(
        pack / "inputs" / "payload_template.json",
        {
            "require_full_grok_frontier": True,
            "langgraph_child": {
                "enabled": True,
                "task_queue": "xinao-integrated-langgraph-plugin-queue",
                "workflow_type": "XinaoIntegratedBusWorkflow",
            },
        },
    )
    active_surface = F3_PACK / "f3_active_research_surface.v1.json"
    portfolio_policy = F3_PACK / "f3_research_portfolio_policy.v1.json"
    active_surface_value = json.loads(active_surface.read_text(encoding="utf-8"))
    portfolio_policy_value = json.loads(portfolio_policy.read_text(encoding="utf-8"))
    source = compile_f4_canary_candidate_source(
        active_research_surface=active_surface_value,
        selection_manifest=selection,
        method_registry={"registrations": registrations},
        method_id="method.f4-evidence-bound-canary.v1",
        source_dependency_graph=graph,
        world_snapshot_hash=WORLD_SNAPSHOT_SHA256,
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
    )
    question_ref, question_hash = write_json(
        pack / "inputs" / "research_question.json",
        source["research_question"],
    )
    source_snapshot_ref, source_snapshot_hash = write_json(
        pack / "inputs" / "research_candidate_source_snapshot.json",
        source["candidate_source_snapshot"],
    )
    candidate_snapshot = compile_f4_canary_candidate_snapshot(
        research_question=source["research_question"],
        candidate_source_snapshot=source["candidate_source_snapshot"],
        active_research_surface=active_surface_value,
        selection_manifest=selection,
        method_registry={"registrations": registrations},
        method_id="method.f4-evidence-bound-canary.v1",
        source_dependency_graph=graph,
    )
    snapshot_ref, snapshot_hash = write_json(
        pack / "inputs" / "research_candidate_snapshot.json",
        candidate_snapshot,
    )
    allocation = compile_research_portfolio_allocation(
        candidate_snapshot,
        active_surface=active_surface_value,
        portfolio_policy=portfolio_policy_value,
        source_dependency_graph=graph,
    )
    allocation_ref, allocation_hash = write_json(
        pack / "inputs" / "research_portfolio_allocation.json",
        allocation,
    )
    frontier_ref, frontier_hash = write_json(
        pack / "inputs" / "frontier.json",
        {
            "schema_version": "xinao.foundation_continuous_frontier.v3",
            "foundation_closed": False,
            "source_dependency_graph_ref": graph_ref,
            "source_dependency_graph_sha256": graph_hash,
            "capacity_observation_ref": capacity_ref,
            "capacity_observation_sha256": capacity_hash,
            "selection_manifest_ref": selection_ref,
            "selection_manifest_sha256": selection_hash,
            "research_factory_manifest_ref": factory_ref,
            "research_factory_manifest_sha256": factory_hash,
            "method_registry_ref": registry_ref,
            "method_registry_sha256": registry_hash,
            "active_research_surface_ref": str(active_surface),
            "active_research_surface_sha256": file_sha256(active_surface),
            "research_portfolio_policy_ref": str(portfolio_policy),
            "research_portfolio_policy_sha256": file_sha256(portfolio_policy),
            "research_question_ref": question_ref,
            "research_question_sha256": question_hash,
            "research_candidate_source_snapshot_ref": source_snapshot_ref,
            "research_candidate_source_snapshot_sha256": source_snapshot_hash,
            "research_candidate_snapshot_ref": snapshot_ref,
            "research_candidate_snapshot_sha256": snapshot_hash,
            "research_portfolio_allocation_ref": allocation_ref,
            "research_portfolio_allocation_sha256": allocation_hash,
            "payload_template_ref": template_ref,
            "payload_template_sha256": template_hash,
            "external_task_queue": external_queue,
            "external_provider_id": "grok_acpx_headless",
            "external_model": F4_DOCKER_MODEL,
            "submission_timeout_seconds": 1_800,
            "wait_seconds": 3_600,
        },
    )
    roll_forward = json.loads(ROLL_FORWARD_SOURCE.read_text(encoding="utf-8"))
    replay_candidate = json.loads(
        ROLL_FORWARD_SOURCE.with_name("predecessor_replay_proof.json").read_text(
            encoding="utf-8"
        )
    )
    current_v1_hash = file_sha256(V1_WORKFLOW_SOURCE)
    replay_candidate["workflow_code_sha256"] = current_v1_hash
    replay_candidate["verified_at"] = datetime.now(UTC).isoformat()
    replay_ref, replay_hash = write_json(
        pack / "inputs" / "predecessor_replay_proof.current_revision.json",
        replay_candidate,
    )
    roll_forward["successor_operation_id"] = operation_id
    roll_forward["predecessor_workflow_code_sha256"] = current_v1_hash
    roll_forward["predecessor_replay_ref"] = replay_ref
    roll_forward["predecessor_replay_sha256"] = replay_hash
    roll_forward_ref, roll_forward_hash = write_json(
        pack / "inputs" / "roll_forward_manifest.json",
        roll_forward,
    )
    return {
        "frontier_ref": frontier_ref,
        "frontier_sha256": frontier_hash,
        "roll_forward_manifest_ref": roll_forward_ref,
        "roll_forward_manifest_sha256": roll_forward_hash,
    }


def verify_request(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("external wave request must be an object")
    body = dict(value)
    request_hash = str(body.pop("request_hash", ""))
    if canonical_sha256(body) != request_hash:
        raise ValueError("external wave request hash drifted")
    payload_path = Path(str(value["payload_ref"]))
    if file_sha256(payload_path) != value["payload_sha256"]:
        raise ValueError("external wave payload hash drifted")
    return value


async def wait_for_file(path: Path, *, timeout_seconds: float) -> None:
    async with asyncio.timeout(timeout_seconds):
        while not path.is_file():
            await asyncio.sleep(0.2)


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _prepare_handshake(pack: Path, request_hash: str) -> tuple[Path, str]:
    bridge_root = (pack / "bridge").resolve()
    bridge_root.mkdir(parents=True, exist_ok=True)
    for _ in range(16):
        nonce = secrets.token_hex(32)
        path = bridge_root / f"{request_hash}.{nonce[:16]}.handshake.json"
        if not path.exists():
            return path, nonce
    raise RuntimeError("could not allocate a unique canonical transaction handshake")


async def _wait_for_handshake_or_exit(
    process: asyncio.subprocess.Process,
    handshake_path: Path,
    *,
    timeout_seconds: float,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.001, timeout_seconds)
    while True:
        if handshake_path.is_file():
            return
        if process.returncode is not None:
            raise RuntimeError(
                f"canonical Grok process exited before handshake: {process.returncode}"
            )
        if loop.time() >= deadline:
            raise TimeoutError("canonical Grok handshake deadline exceeded")
        await asyncio.sleep(0.1)


def _validate_started_handshake(
    handshake_path: Path,
    *,
    expected_nonce: str,
    expected_queue: str,
    transaction_key: str,
    expected_payload_sha256: str,
    external_run_root: Path,
) -> tuple[dict[str, Any], dict[str, Path]]:
    started = _read_json_object(handshake_path, label="canonical transaction handshake")
    required = (
        "task_id",
        "workflow_id",
        "run_id",
        "first_execution_run_id",
        "task_queue",
        "attempt_id",
        "run_dir",
        "transaction_dir",
        "transaction_identity_sha256",
        "transaction_key_sha256",
    )
    if started.get("schema_version") != "xinao.canonical_grok_transaction.started.v1":
        raise ValueError("canonical transaction handshake schema drifted")
    if any(not str(started.get(name) or "").strip() for name in required):
        raise ValueError("canonical transaction handshake is missing required identity")
    if started.get("handshake_nonce") != expected_nonce:
        raise ValueError("canonical transaction handshake nonce mismatch")
    if started.get("task_queue") != expected_queue:
        raise ValueError("canonical transaction handshake queue mismatch")

    key_sha256 = hashlib.sha256(transaction_key.encode("utf-8")).hexdigest()
    if started.get("transaction_key_sha256") != key_sha256:
        raise ValueError("canonical transaction handshake key mismatch")
    attempt_id = str(started["attempt_id"])
    if re.fullmatch(r"attempt-[0-9]{4}", attempt_id) is None:
        raise ValueError("canonical transaction handshake attempt id is invalid")

    run_root = external_run_root.resolve()
    transaction_dir = Path(str(started["transaction_dir"])).resolve()
    expected_transaction_dir = run_root / f"canonical-grok-key-{key_sha256[:20]}"
    if transaction_dir != expected_transaction_dir:
        raise ValueError("canonical transaction handshake transaction directory drifted")
    run_dir = Path(str(started["run_dir"])).resolve()
    if run_dir != transaction_dir / "attempts" / attempt_id:
        raise ValueError("canonical transaction handshake attempt directory drifted")
    if not run_dir.is_dir():
        raise ValueError("canonical transaction attempt directory does not exist")

    identity_path = transaction_dir / "identity.json"
    execution_path = transaction_dir / "execution.json"
    attempt_path = run_dir / "attempt.json"
    identity = _read_json_object(identity_path, label="canonical transaction identity")
    execution = _read_json_object(execution_path, label="canonical transaction execution")
    attempt = _read_json_object(attempt_path, label="canonical transaction attempt")
    identity_sha256 = file_sha256(identity_path)
    if identity_sha256 != started["transaction_identity_sha256"]:
        raise ValueError("canonical transaction identity hash mismatch")
    identity_expected = {
        "schema_version": "xinao.canonical_grok_transaction.identity.v1",
        "transaction_key_semantics": TRANSACTION_KEY_SEMANTICS,
        "transaction_key_sha256": key_sha256,
        "payload_sha256": expected_payload_sha256,
        "task_queue": expected_queue,
    }
    if any(identity.get(name) != value for name, value in identity_expected.items()):
        raise ValueError("canonical transaction identity binding drifted")
    execution_expected = {
        "schema_version": "xinao.canonical_grok_transaction.execution.v1",
        "transaction_key_semantics": TRANSACTION_KEY_SEMANTICS,
        "transaction_identity_sha256": identity_sha256,
        "task_queue": expected_queue,
        "task_id": started["task_id"],
        "workflow_id": started["workflow_id"],
        "run_id": started["run_id"],
        "first_execution_run_id": started["first_execution_run_id"],
    }
    if any(execution.get(name) != value for name, value in execution_expected.items()):
        raise ValueError("canonical transaction execution binding drifted")
    attempt_expected = {
        "schema_version": "xinao.canonical_grok_transaction.attempt.v1",
        "attempt_id": attempt_id,
        "transaction_identity_sha256": identity_sha256,
        "transaction_key_sha256": key_sha256,
    }
    if any(attempt.get(name) != value for name, value in attempt_expected.items()):
        raise ValueError("canonical transaction attempt binding drifted")
    return started, {
        "transaction_dir": transaction_dir,
        "run_dir": run_dir,
        "identity_path": identity_path,
        "execution_path": execution_path,
        "attempt_path": attempt_path,
        "result_path": run_dir / "result.json",
        "attempt_outcome_path": run_dir / "attempt_outcome.json",
    }


async def _cancel_exact_chain(
    client: Client,
    started: dict[str, Any],
    *,
    timeout_seconds: float = CANONICAL_CANCEL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    first_run_id = str(started["first_execution_run_id"])
    outcome: dict[str, Any] = {
        "workflow_cancel_attempted": True,
        "workflow_cancel_requested": False,
        "workflow_terminal_confirmed": False,
        "workflow_cancel_confirmed": False,
        "workflow_cancel_terminal_status": "",
        "workflow_cancel_terminal_run_id": "",
        "workflow_cancel_error_type": "",
        "workflow_cancel_chain_identity_ok": False,
    }
    handle = client.get_workflow_handle(
        str(started["workflow_id"]),
        first_execution_run_id=first_run_id,
    )
    rpc_timeout = timedelta(seconds=max(0.001, min(5.0, timeout_seconds)))
    try:
        async with asyncio.timeout(max(0.001, timeout_seconds)):
            try:
                await handle.cancel(
                    reason="F4 canary owner exiting before verified bridge completion",
                    rpc_timeout=rpc_timeout,
                )
                outcome["workflow_cancel_requested"] = True
            except Exception as exc:
                outcome["workflow_cancel_error_type"] = type(exc).__name__
            while True:
                description = await handle.describe(rpc_timeout=rpc_timeout)
                raw_info = getattr(description, "raw_info", None)
                observed_first = str(getattr(raw_info, "first_run_id", "") or "")
                if observed_first != first_run_id:
                    outcome["workflow_cancel_error_type"] = (
                        "WorkflowChainIdentityMismatch"
                    )
                    return outcome
                outcome["workflow_cancel_chain_identity_ok"] = True
                status = str(
                    getattr(getattr(description, "status", None), "name", "") or ""
                )
                execution = getattr(raw_info, "execution", None)
                outcome["workflow_cancel_terminal_run_id"] = str(
                    getattr(execution, "run_id", "") or ""
                )
                outcome["workflow_cancel_terminal_status"] = status
                if status in TERMINAL_WORKFLOW_STATUSES:
                    outcome["workflow_terminal_confirmed"] = True
                    outcome["workflow_cancel_confirmed"] = status == "CANCELED"
                    return outcome
                await asyncio.sleep(0.1)
    except TimeoutError:
        if not outcome["workflow_cancel_error_type"]:
            outcome["workflow_cancel_error_type"] = "TimeoutError"
    except Exception as exc:
        if not outcome["workflow_cancel_error_type"]:
            outcome["workflow_cancel_error_type"] = type(exc).__name__
    return outcome


async def _stop_process_after_cleanup(
    process: asyncio.subprocess.Process,
    *,
    cleanup: dict[str, Any] | None,
    grace_seconds: float = 5.0,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "process_exit_code": process.returncode,
        "process_terminated": False,
        "process_killed": False,
        "temporal_terminal_confirmed_before_process_stop": bool(
            cleanup and cleanup.get("workflow_terminal_confirmed") is True
        ),
    }
    if process.returncode is not None:
        return result
    try:
        async with asyncio.timeout(max(0.001, grace_seconds)):
            result["process_exit_code"] = await process.wait()
            return result
    except TimeoutError:
        pass
    try:
        process.terminate()
        result["process_terminated"] = True
    except ProcessLookupError:
        result["process_exit_code"] = process.returncode
        return result
    try:
        async with asyncio.timeout(5.0):
            result["process_exit_code"] = await process.wait()
            return result
    except TimeoutError:
        process.kill()
        result["process_killed"] = True
        result["process_exit_code"] = await process.wait()
        return result


async def _describe_and_fetch_terminal_history(
    client: Client,
    started: dict[str, Any],
) -> tuple[Any, str]:
    workflow_id = str(started["workflow_id"])
    first_run_id = str(started["first_execution_run_id"])
    chain_handle = client.get_workflow_handle(
        workflow_id,
        first_execution_run_id=first_run_id,
    )
    description = await chain_handle.describe(rpc_timeout=timedelta(seconds=5))
    raw_info = getattr(description, "raw_info", None)
    if str(getattr(raw_info, "first_run_id", "") or "") != first_run_id:
        raise ValueError("external workflow chain identity drifted")
    status = str(getattr(getattr(description, "status", None), "name", "") or "")
    if status != "COMPLETED":
        raise ValueError(f"external workflow is not completed: {status}")
    execution = getattr(raw_info, "execution", None)
    terminal_run_id = str(getattr(execution, "run_id", "") or "")
    if not terminal_run_id:
        raise ValueError("external workflow terminal run id is missing")
    terminal_handle = client.get_workflow_handle(
        workflow_id,
        run_id=terminal_run_id,
        first_execution_run_id=first_run_id,
    )
    return await terminal_handle.fetch_history(), terminal_run_id


def _validate_result_envelope(
    result_path: Path,
    *,
    started: dict[str, Any],
    paths: dict[str, Path],
    request: dict[str, Any],
    external_queue: str,
    expected_deployment: dict[str, object],
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = _read_json_object(result_path, label="canonical Grok result")
    expected = {
        "payload_sha256": request["payload_sha256"],
        "task_queue": external_queue,
        "task_id": started["task_id"],
        "workflow_id": started["workflow_id"],
        "run_id": started["run_id"],
        "first_execution_run_id": started["first_execution_run_id"],
        "attempt_id": started["attempt_id"],
        "run_dir": str(paths["run_dir"]),
        "transaction_dir": str(paths["transaction_dir"]),
        "transaction_identity_sha256": started["transaction_identity_sha256"],
        "transaction_key_sha256": started["transaction_key_sha256"],
        "transaction_key_semantics": TRANSACTION_KEY_SEMANTICS,
        "execution_reused": started.get("execution_reused"),
        "worker_deployment_name": expected_deployment["deployment_name"],
        "worker_build_id": expected_deployment["build_id"],
    }
    if result.get("ok") is not True or any(
        result.get(name) != value for name, value in expected.items()
    ):
        raise ValueError("canonical Grok result envelope does not match request/attempt")
    outcome = _read_json_object(
        paths["attempt_outcome_path"],
        label="canonical transaction attempt outcome",
    )
    outcome_expected = {
        "schema_version": "xinao.canonical_grok_transaction.attempt_outcome.v1",
        "status": "accepted",
        "attempt_id": started["attempt_id"],
        "transaction_identity_sha256": started["transaction_identity_sha256"],
        "transaction_key_sha256": started["transaction_key_sha256"],
        "transaction_key_semantics": TRANSACTION_KEY_SEMANTICS,
        "workflow_id": started["workflow_id"],
        "first_execution_run_id": started["first_execution_run_id"],
    }
    if any(outcome.get(name) != value for name, value in outcome_expected.items()):
        raise ValueError("canonical transaction attempt outcome drifted")
    return result, outcome


async def wait_for_next_request(
    request_root: Path,
    processed: set[str],
    *,
    timeout_seconds: float,
) -> tuple[Path, dict[str, Any]]:
    async with asyncio.timeout(timeout_seconds):
        while True:
            for path in sorted(request_root.glob("*.json")):
                value = verify_request(path)
                request_hash = str(value["request_hash"])
                if request_hash not in processed:
                    return path, value
            await asyncio.sleep(0.25)


def signal_id(request_hash: str, kind: str, identity: str) -> str:
    return hashlib.sha256(f"{request_hash}:{kind}:{identity}".encode()).hexdigest()


async def process_one_wave(
    client: Client,
    *,
    pack: Path,
    request_root: Path,
    processed: set[str],
    external_queue: str,
    db_path: Path,
    external_run_root: Path,
    expected_deployment: dict[str, object],
) -> dict[str, Any]:
    request_path, request = await wait_for_next_request(
        request_root,
        processed,
        timeout_seconds=120,
    )
    request_hash = str(request["request_hash"])
    handshake_path, handshake_nonce = _prepare_handshake(pack, request_hash)
    stdout_path = pack / "bridge" / f"{request_hash}.stdout.txt"
    stderr_path = pack / "bridge" / f"{request_hash}.stderr.txt"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    callback = client.get_workflow_handle(
        str(request["callback_workflow_id"]),
        run_id=str(request["callback_run_id"]),
    )
    process: asyncio.subprocess.Process | None = None
    started: dict[str, Any] | None = None
    paths: dict[str, Path] | None = None
    cleanup: dict[str, Any] = {}
    loop = asyncio.get_running_loop()
    process_deadline = loop.time() + CANONICAL_PROCESS_TIMEOUT_SECONDS
    try:
        with (
            stdout_path.open("wb") as stdout_handle,
            stderr_path.open("wb") as stderr_handle,
        ):
            process = await asyncio.create_subprocess_exec(
                str(DUAL_PYTHON),
                str(CANONICAL_RUNNER),
                "--payload",
                str(request["payload_ref"]),
                "--db",
                str(db_path),
                "--run-root",
                str(external_run_root),
                "--task-queue",
                external_queue,
                "--transaction-key",
                request_hash,
                "--handshake-path",
                str(handshake_path),
                "--handshake-nonce",
                handshake_nonce,
                "--timeout-seconds",
                "1800",
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=creationflags,
            )
            await _wait_for_handshake_or_exit(
                process,
                handshake_path,
                timeout_seconds=CANONICAL_HANDSHAKE_TIMEOUT_SECONDS,
            )
            started, paths = _validate_started_handshake(
                handshake_path,
                expected_nonce=handshake_nonce,
                expected_queue=external_queue,
                transaction_key=request_hash,
                expected_payload_sha256=str(request["payload_sha256"]),
                external_run_root=external_run_root,
            )
            await callback.signal(
                str(request["callback_signals"]["started"]),
                {
                    "signal_id": signal_id(
                        request_hash,
                        "started",
                        str(started["run_id"]),
                    ),
                    "wave_id": request["wave_id"],
                    "workflow_id": started["workflow_id"],
                    "run_id": started["run_id"],
                    "task_queue": started["task_queue"],
                },
            )
            remaining = max(0.001, process_deadline - loop.time())
            async with asyncio.timeout(remaining):
                return_code = await process.wait()

        if return_code != 0:
            raise RuntimeError(f"canonical Grok process failed: {return_code}")
        if paths is None or started is None or not paths["result_path"].is_file():
            raise RuntimeError("canonical Grok process exited without its bound result")
        result, _ = _validate_result_envelope(
            paths["result_path"],
            started=started,
            paths=paths,
            request=request,
            external_queue=external_queue,
            expected_deployment=expected_deployment,
        )
        history, terminal_run_id = await _describe_and_fetch_terminal_history(
            client,
            started,
        )
        history_ref, history_hash = write_json(
            pack / "histories" / f"external-{request_hash}.json",
            history.to_json_dict(),
        )
        result_hash = file_sha256(paths["result_path"])
        await callback.signal(
            str(request["callback_signals"]["completed"]),
            {
                "signal_id": signal_id(
                    request_hash,
                    "completed",
                    result_hash,
                ),
                "wave_id": request["wave_id"],
                "workflow_id": started["workflow_id"],
                "run_id": started["run_id"],
                "result_ref": str(paths["result_path"]),
                "result_sha256": result_hash,
            },
        )
        payload = _read_json_object(
            Path(str(request["payload_ref"])),
            label="external wave payload",
        )
        receipt = {
            "schema_version": "xinao.f4_live_bridge_receipt.v2",
            "request_ref": str(request_path),
            "request_hash": request_hash,
            "payload_ref": request["payload_ref"],
            "payload_sha256": request["payload_sha256"],
            "research_stage": payload["research_stage"],
            "dispatch_width": payload["dynamic_capacity_decision"]["dispatch_width"],
            "capacity_reason": payload["dynamic_capacity_decision"]["reason"],
            "callback_workflow_id": request["callback_workflow_id"],
            "callback_run_id": request["callback_run_id"],
            "external_workflow_id": started["workflow_id"],
            "external_run_id": started["run_id"],
            "external_bound_run_id": started["run_id"],
            "external_first_execution_run_id": started["first_execution_run_id"],
            "external_terminal_run_id": terminal_run_id,
            "external_task_queue": started["task_queue"],
            "external_attempt_id": started["attempt_id"],
            "external_execution_reused": started.get("execution_reused"),
            "worker_deployment_name": result["worker_deployment_name"],
            "worker_build_id": result["worker_build_id"],
            "handshake_ref": str(handshake_path),
            "handshake_sha256": file_sha256(handshake_path),
            "transaction_identity_ref": str(paths["identity_path"]),
            "transaction_identity_sha256": file_sha256(paths["identity_path"]),
            "transaction_execution_ref": str(paths["execution_path"]),
            "transaction_execution_sha256": file_sha256(paths["execution_path"]),
            "transaction_attempt_ref": str(paths["attempt_path"]),
            "transaction_attempt_sha256": file_sha256(paths["attempt_path"]),
            "attempt_outcome_ref": str(paths["attempt_outcome_path"]),
            "attempt_outcome_sha256": file_sha256(paths["attempt_outcome_path"]),
            "result_ref": str(paths["result_path"]),
            "result_sha256": result_hash,
            "external_history_ref": history_ref,
            "external_history_sha256": history_hash,
            "lane_count": result["result"]["grok_fanin"]["lane_count"],
            "observed_model": result["result"]["grok_fanin"]["observed_model"],
        }
        receipt_ref, receipt_hash = write_json(
            pack / "bridge" / f"{request_hash}.receipt.json",
            receipt,
        )
        processed.add(request_hash)
        return {
            **receipt,
            "receipt_ref": receipt_ref,
            "receipt_sha256": receipt_hash,
        }
    except BaseException as exc:
        original = exc
        recovery_error = ""
        if process is not None and process.returncode is None and started is None:
            remaining = max(0.001, process_deadline - loop.time())
            try:
                await _wait_for_handshake_or_exit(
                    process,
                    handshake_path,
                    timeout_seconds=remaining,
                )
                started, paths = _validate_started_handshake(
                    handshake_path,
                    expected_nonce=handshake_nonce,
                    expected_queue=external_queue,
                    transaction_key=request_hash,
                    expected_payload_sha256=str(request["payload_sha256"]),
                    external_run_root=external_run_root,
                )
            except BaseException as recovery_exc:
                recovery_error = type(recovery_exc).__name__
                if process.returncode is None:
                    remaining = max(0.001, process_deadline - loop.time())
                    try:
                        async with asyncio.timeout(remaining):
                            await process.wait()
                    except TimeoutError:
                        pass
        if process is not None and process.returncode is None and started is not None:
            cleanup = await _cancel_exact_chain(client, started)
        if process is not None and process.returncode is None:
            cleanup.update(
                await _stop_process_after_cleanup(
                    process,
                    cleanup=cleanup or None,
                )
            )
        stderr_hash = (
            hashlib.sha256(stderr_path.read_bytes()).hexdigest()
            if stderr_path.is_file()
            else hashlib.sha256(b"").hexdigest()
        )
        error_identity = hashlib.sha256(
            (
                f"{type(original).__name__}:{original}:{stderr_hash}:"
                f"{recovery_error}"
            ).encode("utf-8")
        ).hexdigest()
        failed_signal_error = ""
        try:
            await callback.signal(
                str(request["callback_signals"]["failed"]),
                {
                    "signal_id": signal_id(request_hash, "failed", error_identity),
                    "wave_id": request["wave_id"],
                    "error_type": type(original).__name__,
                    "message": str(original),
                },
            )
        except BaseException as signal_exc:
            failed_signal_error = type(signal_exc).__name__
        try:
            write_json(
                pack / "bridge" / f"{request_hash}.failure.json",
                {
                    "schema_version": "xinao.f4_live_bridge_failure.v1",
                    "request_hash": request_hash,
                    "error_type": type(original).__name__,
                    "error_message": str(original),
                    "stderr_sha256": stderr_hash,
                    "handshake_ref": str(handshake_path),
                    "handshake_present": handshake_path.is_file(),
                    "trusted_started_identity": started is not None,
                    "recovery_error_type": recovery_error,
                    "failed_signal_error_type": failed_signal_error,
                    **cleanup,
                },
            )
        except Exception:
            pass
        raise


async def wait_for_closed_count(
    handle: Any,
    expected: int,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    async with asyncio.timeout(timeout_seconds):
        while True:
            state = await handle.query("state")
            if (
                len(state.get("closed_work_keys") or []) >= expected
                and state.get("batch_stage") == "IDLE"
                and state.get("current_wave") is None
            ):
                return state
            await asyncio.sleep(0.5)


def _closed_and_idle(state: dict[str, Any], expected: int) -> bool:
    return (
        len(state.get("closed_work_keys") or []) >= expected
        and state.get("batch_stage") == "IDLE"
        and state.get("current_wave") is None
    )


async def _wait_for_closed_or_next_request(
    handle: Any,
    expected: int,
    *,
    request_root: Path,
    processed: set[str],
    timeout_seconds: float = WAVE_SETTLE_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], bool]:
    """Wait until the target closes or the controller publishes compensation work."""

    async with asyncio.timeout(timeout_seconds):
        while True:
            state = await handle.query("state")
            if _closed_and_idle(state, expected):
                return state, True
            for path in sorted(request_root.glob("*.json")):
                request = verify_request(path)
                if str(request["request_hash"]) not in processed:
                    return state, False
            await asyncio.sleep(0.25)


async def _process_until_closed(
    client: Client,
    handle: Any,
    *,
    expected_closed: int,
    minimum_requests: int,
    max_requests: int,
    pack: Path,
    request_root: Path,
    processed: set[str],
    external_queue: str,
    db_path: Path,
    external_run_root: Path,
    expected_deployment: dict[str, object],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Serve a minimum canary batch plus bounded compensation waves."""

    receipts: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    for _ in range(max_requests):
        receipts.append(
            await process_one_wave(
                client,
                pack=pack,
                request_root=request_root,
                processed=processed,
                external_queue=external_queue,
                db_path=db_path,
                external_run_root=external_run_root,
                expected_deployment=expected_deployment,
            )
        )
        state, closed = await _wait_for_closed_or_next_request(
            handle,
            expected_closed,
            request_root=request_root,
            processed=processed,
        )
        if len(receipts) >= minimum_requests and closed:
            return receipts, state
    raise TimeoutError(
        f"F4 compensation request budget exhausted before {expected_closed} work keys closed"
    )


async def _cancel_parent_before_worker_exit(
    handle: Any,
    *,
    pack: Path,
    phase: str,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "schema_version": "xinao.f4_parent_cleanup.v1",
        "phase": phase,
        "cancel_requested": False,
        "terminal_confirmed": False,
        "terminal_status": "",
        "first_execution_run_id": "",
        "terminal_run_id": "",
        "error_type": "",
    }
    try:
        async with asyncio.timeout(max(0.001, timeout_seconds)):
            try:
                await handle.cancel(
                    reason="bounded F4 canary failed before verified completion",
                    rpc_timeout=timedelta(seconds=5),
                )
                outcome["cancel_requested"] = True
            except Exception as exc:
                outcome["error_type"] = type(exc).__name__
            while True:
                description = await handle.describe(
                    rpc_timeout=timedelta(seconds=5)
                )
                raw_info = getattr(description, "raw_info", None)
                outcome["first_execution_run_id"] = str(
                    getattr(raw_info, "first_run_id", "") or ""
                )
                execution = getattr(raw_info, "execution", None)
                outcome["terminal_run_id"] = str(
                    getattr(execution, "run_id", "") or ""
                )
                status = str(
                    getattr(getattr(description, "status", None), "name", "") or ""
                )
                outcome["terminal_status"] = status
                if status in TERMINAL_WORKFLOW_STATUSES:
                    outcome["terminal_confirmed"] = True
                    break
                await asyncio.sleep(0.1)
    except TimeoutError:
        if not outcome["error_type"]:
            outcome["error_type"] = "TimeoutError"
    except Exception as exc:
        if not outcome["error_type"]:
            outcome["error_type"] = type(exc).__name__
    write_json(pack / "worker_cleanup" / f"{phase}.json", outcome)
    if outcome["terminal_confirmed"] is not True:
        raise RuntimeError("F4 parent workflow cleanup was not terminal-confirmed")
    return outcome


def worker(
    client: Client,
    *,
    queue: str,
    identity: str,
    executor: ThreadPoolExecutor,
) -> Worker:
    return Worker(
        client,
        task_queue=queue,
        workflows=[FoundationContinuousWorkflowV2, FoundationWaveChildWorkflowV1],
        activities=[
            persist_foundation_state,
            verify_external_wave_result,
            verify_roll_forward_manifest_v2,
            reconcile_foundation_frontier_v2,
            inspect_external_wave_result_v2,
            finalize_research_fan_in_v2,
        ],
        activity_executor=executor,
        identity=identity,
        max_concurrent_workflow_tasks=4,
        max_concurrent_activities=8,
        max_concurrent_workflow_task_polls=2,
        max_concurrent_activity_task_polls=2,
        graceful_shutdown_timeout=timedelta(seconds=15),
    )


async def run(pack: Path, *, temporal_address: str) -> dict[str, Any]:
    stamp = pack.name.rsplit("-", 1)[-1].lower()
    operation_id = f"xinao-f4-live-{stamp}"
    parent_queue = f"xinao-f4-v2-{stamp}"
    external_queue = f"xinao-f4-grok-{stamp}"
    parent_workflow_id = f"xinao-f4-v2-parent-{stamp}"
    deployment_seal = canonical_deployment_seal()
    inputs = prepare_inputs(
        pack,
        operation_id=operation_id,
        external_queue=external_queue,
    )
    initial = {
        "operation_id": operation_id,
        "runtime_root": str(RUNTIME),
        **inputs,
        "owner_generation": 1,
        "max_waves_per_run": 20,
        "default_wait_seconds": 3_600,
    }
    client = await Client.connect(temporal_address, namespace="default")
    request_root = RUNTIME / "state" / "foundation_continuous" / operation_id / "requests"
    external_run_root = pack / "external_transactions"
    db_path = pack / "coordination.sqlite3"
    processed: set[str] = set()
    receipts: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        async with worker(
            client,
            queue=parent_queue,
            identity=f"f4-v2-worker-a@{stamp}",
            executor=executor,
        ):
            handle = await client.start_workflow(
                FoundationContinuousWorkflowV2.run,
                initial,
                id=parent_workflow_id,
                task_queue=parent_queue,
            )
            try:
                first_receipts, first_batch = await _process_until_closed(
                    client,
                    handle,
                    expected_closed=1,
                    minimum_requests=3,
                    max_requests=MAX_WORKER_A_REQUESTS,
                    pack=pack,
                    request_root=request_root,
                    processed=processed,
                    external_queue=external_queue,
                    db_path=db_path,
                    external_run_root=external_run_root,
                    expected_deployment=deployment_seal,
                )
                receipts.extend(first_receipts)
                write_json(
                    pack / "worker_restart" / "before_restart.json",
                    first_batch,
                )
            except BaseException:
                cleanup_task = asyncio.create_task(
                    _cancel_parent_before_worker_exit(
                        handle,
                        pack=pack,
                        phase="worker-a-failure",
                    )
                )
                await asyncio.shield(cleanup_task)
                raise

        async with worker(
            client,
            queue=parent_queue,
            identity=f"f4-v2-worker-b@{stamp}",
            executor=executor,
        ):
            write_json(
                pack / "worker_restart" / "restarted.json",
                {
                    "schema_version": "xinao.f4_v2_worker_restart.v1",
                    "restarted_at": datetime.now(UTC).isoformat(),
                    "task_queue": parent_queue,
                    "previous_identity": f"f4-v2-worker-a@{stamp}",
                    "current_identity": f"f4-v2-worker-b@{stamp}",
                },
            )
            try:
                final_receipts, complete_state = await _process_until_closed(
                    client,
                    handle,
                    expected_closed=3,
                    minimum_requests=3,
                    max_requests=MAX_WORKER_B_REQUESTS,
                    pack=pack,
                    request_root=request_root,
                    processed=processed,
                    external_queue=external_queue,
                    db_path=db_path,
                    external_run_root=external_run_root,
                    expected_deployment=deployment_seal,
                )
                receipts.extend(final_receipts)
                await handle.execute_update(
                    "control",
                    {
                        "operation_id": f"stop-{stamp}",
                        "action": "STOP",
                        "reason": "bounded positive F4 canary completed",
                    },
                )
                terminal = await handle.result()
            except BaseException:
                cleanup_task = asyncio.create_task(
                    _cancel_parent_before_worker_exit(
                        handle,
                        pack=pack,
                        phase="worker-b-failure",
                    )
                )
                await asyncio.shield(cleanup_task)
                raise

    parent_history = await handle.fetch_history()
    parent_history_ref, parent_history_hash = write_json(
        pack / "histories" / "parent.json",
        parent_history.to_json_dict(),
    )
    widths = [int(item["dispatch_width"]) for item in receipts]
    stages = [str(item["research_stage"]) for item in receipts]
    reasons = [str(item["capacity_reason"]) for item in receipts]
    lane_count = sum(int(item["lane_count"]) for item in receipts)
    observed_models = sorted({str(item["observed_model"]) for item in receipts})
    checks = {
        "six_external_workflows": len(receipts) == 6,
        "nine_grok_operations": lane_count == 9,
        "stage_sequence": stages == ["PRODUCER", "CRITIQUE", "VERIFIER"] * 2,
        "width_sequence": widths == [1, 1, 1, 2, 2, 2],
        "capacity_reasons": reasons
        == ["INITIAL_VERIFIED_CAPACITY"] * 3 + ["UPSHIFT_AFTER_FULL_SUCCESS"] * 3,
        "observed_model": observed_models == [F4_DOCKER_MODEL],
        "canonical_worker_build": all(
            item["worker_deployment_name"] == deployment_seal["deployment_name"]
            and item["worker_build_id"] == deployment_seal["build_id"]
            for item in receipts
        ),
        "all_three_work_items_closed": len(complete_state["closed_work_keys"]) == 3,
        "worker_restart_preserved_state": terminal["waves_completed"] == 6,
        "terminal_stopped": terminal["status"] == "STOPPED",
    }
    report = {
        "schema_version": "xinao.f4_live_canary_report.v1",
        "status": "VERIFIED" if all(checks.values()) else "PARTIAL",
        "operation_id": operation_id,
        "parent_workflow_id": parent_workflow_id,
        "parent_run_id": terminal["run_id"],
        "parent_task_queue": parent_queue,
        "external_task_queue": external_queue,
        "canonical_worker_deployment": deployment_seal,
        "receipts": receipts,
        "parent_history_ref": parent_history_ref,
        "parent_history_sha256": parent_history_hash,
        "terminal_state": terminal,
        "checks": checks,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    report_ref, report_hash = write_json(pack / "f4_live_canary_report.json", report)
    artifacts = []
    for path in sorted(item for item in pack.rglob("*") if item.is_file()):
        if path.name == "artifact_manifest.json":
            continue
        artifacts.append(
            {
                "path": str(path),
                "sha256": file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    write_json(
        pack / "artifact_manifest.json",
        {
            "schema_version": "xinao.f4_live_canary_artifact_manifest.v1",
            "report_ref": report_ref,
            "report_sha256": report_hash,
            "artifacts": artifacts,
        },
    )
    if report["status"] != "VERIFIED":
        failed = [key for key, value in checks.items() if not value]
        raise RuntimeError(f"F4 live canary incomplete: {failed}")
    return report


def run_preflight(pack: Path) -> dict[str, Any]:
    stamp = pack.name.rsplit("-", 1)[-1].lower()
    operation_id = f"xinao-f4-preflight-{stamp}"
    external_queue = f"xinao-f4-grok-preflight-{stamp}"
    deployment_seal = canonical_deployment_seal()
    inputs = prepare_inputs(
        pack,
        operation_id=operation_id,
        external_queue=external_queue,
    )
    roll_forward = verify_roll_forward_manifest_v2(
        {
            "runtime_root": str(RUNTIME),
            "manifest_ref": inputs["roll_forward_manifest_ref"],
            "manifest_sha256": inputs["roll_forward_manifest_sha256"],
            "operation_id": operation_id,
            "owner_generation": 1,
        }
    )
    decision = reconcile_foundation_frontier_v2(
        {
            "runtime_root": str(RUNTIME),
            "operation_id": operation_id,
            "frontier_ref": inputs["frontier_ref"],
            "frontier_sha256": inputs["frontier_sha256"],
            "previous_width": 1,
            "succeeded": 0,
            "failed": 0,
        }
    )
    payload_path = Path(str(decision["wave"]["payload_ref"]))
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    lane = payload["grok_ready_frontier"][0]
    prompt = str(lane["prompt"])
    contract_start = prompt.index('{"method_binding"')
    contract_text = prompt[contract_start:]
    decoder = json.JSONDecoder()
    contract, contract_end = decoder.raw_decode(contract_text)
    output_marker = "\nOUTPUT_CONTRACT_V1\n"
    output_start = contract_text.index(output_marker, contract_end) + len(output_marker)
    output_contract, _ = decoder.raw_decode(contract_text[output_start:])
    canary_content = json.loads(
        contract["method_binding"]["materials"]["canary_evidence"]["content_text"]
    )
    checks = {
        "roll_forward_verified": roll_forward.get("ok") is True,
        "dispatch_external": decision.get("action") == "DISPATCH_EXTERNAL",
        "initial_width_one": decision["capacity_decision"]["dispatch_width"] == 1,
        "initial_capacity_reason": decision["capacity_decision"]["reason"]
        == "INITIAL_VERIFIED_CAPACITY",
        "one_lane": len(payload["grok_ready_frontier"]) == 1,
        "method_contract_json_valid": isinstance(contract, dict),
        "method_input_hash_bound": lane["method_input_sha256"]
        == canonical_sha256(lane["method_input"])
        == contract["method_input_sha256"],
        "seven_negative_controls_bound": len(canary_content["negative_controls"]) == 7,
        "closed_book_instruction_bound": (
            "Do not call any tool" in prompt and "Return one JSON object now" in prompt
        ),
        "output_contract_bound": (
            output_contract["fixed_top_level"]["work_key"] == lane["method_input"]["work_key"]
            and output_contract["required_method_output"]["stage"] == "PRODUCER"
        ),
        "canonical_worker_deployment_sealed": bool(
            deployment_seal["build_id"] and deployment_seal["source_digest_sha256"]
        ),
    }
    report = {
        "schema_version": "xinao.f4_live_preflight_report.v1",
        "status": "VERIFIED" if all(checks.values()) else "PARTIAL",
        "operation_id": operation_id,
        "canonical_worker_deployment": deployment_seal,
        "roll_forward": roll_forward,
        "decision": {
            "action": decision["action"],
            "dispatch_width": decision["capacity_decision"]["dispatch_width"],
            "capacity_reason": decision["capacity_decision"]["reason"],
            "lane_ids": decision["wave"]["lane_ids"],
            "payload_ref": str(payload_path),
            "payload_sha256": decision["wave"]["payload_sha256"],
        },
        "checks": checks,
    }
    write_json(pack / "f4_live_preflight_report.json", report)
    if report["status"] != "VERIFIED":
        raise RuntimeError("F4 live preflight did not satisfy all checks")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--temporal-address", default="127.0.0.1:7233")
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    pack = args.pack
    if pack is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        pack = EVIDENCE_PARENT / f"xinao-f4-live-canary-{stamp}"
    pack.mkdir(parents=True, exist_ok=False)
    if args.preflight_only:
        report = run_preflight(pack.resolve())
    else:
        report = asyncio.run(run(pack.resolve(), temporal_address=args.temporal_address))
    print(
        json.dumps(
            {
                "status": report["status"],
                "operation_id": report["operation_id"],
                "parent_workflow_id": report.get("parent_workflow_id"),
                "pack": str(pack.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
