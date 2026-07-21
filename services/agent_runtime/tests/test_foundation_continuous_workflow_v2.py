from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from services.agent_runtime import foundation_continuous_workflow as foundation_v1
from services.agent_runtime import foundation_continuous_workflow_v2 as foundation_v2
from services.agent_runtime.foundation_continuous_workflow import (
    FoundationContinuousWorkflowV1,
    FoundationWaveChildWorkflowV1,
    persist_foundation_state,
    verify_external_wave_result,
)
from services.agent_runtime.foundation_continuous_workflow_v2 import (
    FoundationContinuousWorkflowV2,
    _initial_state_v2,
    _validate_method_registry_artifacts,
    finalize_research_fan_in_v2,
    generate_f4_method_negative_control_receipts,
    inspect_external_wave_result_v2,
    reconcile_foundation_frontier_v2,
    verify_roll_forward_manifest_v2,
)
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from xinao.canonical import canonical_sha256
from xinao.foundation.research_candidate_source import (
    compile_f4_canary_candidate_snapshot,
    compile_f4_canary_candidate_source,
)
from xinao.foundation.research_factory import (
    admit_open_method,
    compile_research_candidate_snapshot,
    compile_research_portfolio_allocation,
    dedupe_ready_frontier,
    finalize_research_candidate_question,
    research_factory_artifact_manifest,
)

SELECTED_MODEL = foundation_v1.DEFAULT_EXTERNAL_MODEL
BACKEND_MODELS = foundation_v2.expected_docker_grok_backend_models(SELECTED_MODEL)
BACKEND_MODEL = BACKEND_MODELS[0]


def _write(path: Path, value: object) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def _versioned_graph(source_count: int = 4) -> dict[str, object]:
    sources = [
        {"source_id": f"source-{index}", "origin_cluster_id": f"origin-{index}"}
        for index in range(source_count)
    ]
    core: dict[str, object] = {
        "object_type": "SourceDependencyGraphVersion",
        "sources": sources,
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


def _versioned_f3_object(object_type: str, **payload: object) -> dict[str, object]:
    core: dict[str, object] = {
        "object_type": object_type,
        "schema_version": "xinao.research-weight-foundation-object.v1",
        "semantic_role": "RESEARCH_RESOURCE_SHARE",
        **payload,
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"{object_type}@{digest[:16]}",
        "content_sha256": digest,
    }


def _work(
    index: int,
    registration_hash: str,
    admission_hash: str,
    selection_manifest_hash: str,
    output_schema_ref: str,
) -> dict[str, object]:
    return {
        "schema_version": "xinao.research_work_item.v2",
        "physical_role": "ACTIVE_SETTLEMENT",
        "kind": "foundation-canary",
        "source_ref": f"source-{index}",
        "source_dependency_refs": [],
        "active_settlement_refs": ["BO0001"],
        "upstream_work_keys": [],
        "intent_slice": f"F4:canary:{index}",
        "selection_manifest_hash": selection_manifest_hash,
        "method_id": "method.f4-canary.v1",
        "method_registration_hash": registration_hash,
        "method_admission_hash": admission_hash,
        "world_snapshot_hash": "2" * 64,
        "input_snapshot_hashes": [f"{index + 3:x}" * 64],
        "knowledge_cutoff": "2026-07-14T00:00:00Z",
        "budget_ref": "budget:f4-canary",
        "error_budget_ledger_ref": "ledger:f4-canary",
        "output_schema_ref": output_schema_ref,
        "handoff_schema_ref": "xinao.agent_handoff.v1",
        "evidence_schema_ref": "xinao.evidence_manifest.v1",
        "correlation_id": f"f4-canary:{index}",
        "expected_information_gain": "verify durable three-stage research",
        "evidence_requirements": ["d-drive-artifact"],
        "authority_scope": ["read:fixture"],
        "write_boundary": "READ_ONLY_WORKER",
    }


def _admitted_method(root: Path) -> tuple[dict[str, object], str, str]:
    refs: dict[str, str] = {}
    digests: dict[str, str] = {}
    artifact_values = {
        "executable": {
            "schema_version": "xinao.f4_prompted_method_executable.v1",
            "method_id": "method.f4-canary.v1",
            "method_evidence_rule": ("F4_EVIDENCE_BOUND_CANARY:{stage}:{work_key_last_12}"),
            "instructions": [
                "Apply the F4 canary method to the exact bound method_input.",
                "Derive method_evidence from the executable rule.",
            ],
        },
        "input-schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "schema_version": {"const": "xinao.f4_method_input.v1"},
                "work_key": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "stage": {"enum": ["PRODUCER", "CRITIQUE", "VERIFIER"]},
                "actor_id": {"type": "string", "minLength": 1},
                "method_id": {"const": "method.f4-canary.v1"},
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
        "output-schema": {
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
        "verification-protocol": {
            "protocol_id": "xinao.f4_evidence_bound_canary_protocol.v1",
            "checks": [
                "BUNDLE_EQ",
                "INPUT_SCHEMA_VALID",
                "METHOD_EVIDENCE_RULE",
                "OUTPUT_SCHEMA_VALID",
                "STAGE_EQ",
                "UPSTREAM_EQ",
                "WORK_KEY_EQ",
            ],
        },
        "failure-contract": {
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
    for name, artifact_value in artifact_values.items():
        ref, digest = _write(
            root / "method-artifacts" / f"{name}.json",
            artifact_value,
        )
        refs[name] = ref
        digests[ref] = digest
    materials = {
        role: {
            "artifact_ref": refs[name],
            "sha256": digests[refs[name]],
        }
        for role, name in {
            "executable": "executable",
            "input_schema": "input-schema",
            "output_schema": "output-schema",
            "verification_protocol": "verification-protocol",
            "failure_contract": "failure-contract",
        }.items()
    }
    negative_receipts = generate_f4_method_negative_control_receipts(
        root,
        {
            "method_id": "method.f4-canary.v1",
            "method_admission_hash": "1" * 64,
            "method_executable_ref": materials["executable"]["artifact_ref"],
            "method_executable_sha256": materials["executable"]["sha256"],
            "method_material_bundle_sha256": "2" * 64,
            "materials": materials,
        },
    )
    negative_controls: list[dict[str, str]] = []
    for check_id, receipt in sorted(negative_receipts.items()):
        ref, digest = _write(
            root / "method-artifacts" / "negative-controls" / f"{check_id}.json",
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
    canary_value = {
        "status": "VERIFIED",
        "method_id": "method.f4-canary.v1",
        "executable_sha256": digests[refs["executable"]],
        "input_schema_sha256": digests[refs["input-schema"]],
        "output_schema_sha256": digests[refs["output-schema"]],
        "verification_protocol_sha256": digests[refs["verification-protocol"]],
        "failure_contract_sha256": digests[refs["failure-contract"]],
        "negative_controls": negative_controls,
    }
    canary_ref, canary_digest = _write(
        root / "method-artifacts" / "canary-evidence.json",
        canary_value,
    )
    refs["canary-evidence"] = canary_ref
    digests[canary_ref] = canary_digest
    registration = {
        "method_id": "method.f4-canary.v1",
        "method_kind": "foundation-canary",
        "executable_ref": refs["executable"],
        "executable_sha256": digests[refs["executable"]],
        "input_schema_ref": refs["input-schema"],
        "input_schema_sha256": digests[refs["input-schema"]],
        "output_schema_ref": refs["output-schema"],
        "output_schema_sha256": digests[refs["output-schema"]],
        "verification_protocol_ref": refs["verification-protocol"],
        "verification_protocol_sha256": digests[refs["verification-protocol"]],
        "failure_contract_ref": refs["failure-contract"],
        "failure_contract_sha256": digests[refs["failure-contract"]],
        "source_refs": ("fixture:f4-canary",),
        "deterministic_seed_policy": "seed is recorded per experiment",
        "canary_evidence_ref": refs["canary-evidence"],
        "canary_evidence_sha256": digests[refs["canary-evidence"]],
    }
    admission = admit_open_method(registration, resolved_content_hashes=digests)
    return (
        admission,
        canonical_sha256(admission["registration"]),
        str(admission["admission_sha256"]),
    )


def _method_binding(root: Path) -> dict[str, object]:
    admission, registration_hash, admission_hash = _admitted_method(root)
    _, materialized = _validate_method_registry_artifacts(
        root,
        {"method.f4-canary.v1": admission},
    )
    material = materialized["method.f4-canary.v1"]
    executable = material["materials"]["executable"]
    return {
        "method_id": "method.f4-canary.v1",
        "method_admission_hash": admission_hash,
        "method_registration_hash": registration_hash,
        "method_executable_ref": executable["artifact_ref"],
        "method_executable_sha256": executable["sha256"],
        "method_material_bundle_sha256": material["material_bundle_sha256"],
        "materials": material["materials"],
    }


def _lane_templates(index: int) -> dict[str, dict[str, object]]:
    return {
        "PRODUCER": {
            "lane_id": f"producer-{index}",
            "mode": "audit",
            "model": SELECTED_MODEL,
            "write": False,
            "allowed_tools": ["read_file"],
            "prompt": '{"work_key":"{{WORK_KEY}}","producer_id":"producer-%d",'
            '"status":"VERIFIED","claim_refs":[]}' % index,
        },
        "CRITIQUE": {
            "lane_id": f"critic-{index}",
            "mode": "audit",
            "model": SELECTED_MODEL,
            "write": False,
            "allowed_tools": ["read_file"],
            "prompt": '{"work_key":"{{WORK_KEY}}","critic_id":"critic-%d",'
            '"target_artifact_ref":"{{PRODUCER_ARTIFACT_REF}}",'
            '"target_artifact_hash":"{{PRODUCER_ARTIFACT_HASH}}",'
            '"verdict":"APPROVED","finding_refs":[]}' % index,
        },
        "VERIFIER": {
            "lane_id": f"verifier-{index}",
            "mode": "audit",
            "model": SELECTED_MODEL,
            "write": False,
            "allowed_tools": ["read_file"],
            "prompt": '{"work_key":"{{WORK_KEY}}","verifier_id":"verifier-%d",'
            '"target_artifact_ref":"{{PRODUCER_ARTIFACT_REF}}",'
            '"target_artifact_hash":"{{PRODUCER_ARTIFACT_HASH}}",'
            '"target_critique_ref":"{{CRITIQUE_ARTIFACT_REF}}",'
            '"target_critique_hash":"{{CRITIQUE_ARTIFACT_HASH}}",'
            '"verdict":"VERIFIED","evidence_refs":[]}' % index,
        },
    }


def _runtime_fixture(
    root: Path,
    *,
    item_count: int,
    foundation_closed: bool = False,
) -> tuple[Path, str]:
    graph = _versioned_graph(item_count)
    graph_ref, graph_hash = _write(root / "graph.json", graph)
    observation_ref, observation_hash = _write(
        root / "capacity.json",
        {
            "schema_version": "xinao.capacity_observation.v1",
            "host_state": "available",
            "available_slots": 8,
            "queue_depth": item_count,
            "verified_canary": True,
        },
    )
    from xinao.foundation.selection_manifest import (
        compile_default_independent_selection_manifest,
    )

    selection_manifest = compile_default_independent_selection_manifest()
    selection_ref, selection_hash = _write(
        root / "selection-manifest.json",
        selection_manifest.model_dump(mode="json"),
    )
    factory_manifest_ref, factory_manifest_hash = _write(
        root / "research-factory-manifest.json",
        research_factory_artifact_manifest(),
    )
    registration, registration_hash, admission_hash = _admitted_method(root)
    registrations = {"method.f4-canary.v1": registration}
    registry_ref, registry_hash = _write(
        root / "methods.json",
        {"registrations": registrations},
    )
    active_surface = _versioned_f3_object(
        "ActiveResearchSurfaceVersion",
        rows=[
            {
                "family_id": "special-number",
                "active_component_ids": ["BO0001"],
                "active_component_count": 1,
                "research_resource_share": "0.9",
                "surface_state": "ACTIVE",
            }
        ],
    )
    active_surface_ref, active_surface_hash = _write(
        root / "active-research-surface.json",
        active_surface,
    )
    portfolio_policy = _versioned_f3_object(
        "ResearchPortfolioPolicyVersion",
        active_surface_ref=active_surface["content_sha256"],
        exploration_share="0.1",
        exploitation_share="0.9",
    )
    portfolio_policy_ref, portfolio_policy_hash = _write(
        root / "research-portfolio-policy.json",
        portfolio_policy,
    )
    template_ref, template_hash = _write(
        root / "payload-template.json",
        {
            "require_full_grok_frontier": True,
            "langgraph_child": {
                "enabled": True,
                "task_queue": "xinao-integrated-langgraph-plugin-queue",
                "workflow_type": "XinaoIntegratedBusWorkflow",
            },
        },
    )
    ready = [
        {
            "work_item": _work(
                index,
                registration_hash,
                admission_hash,
                selection_manifest.content_hash,
                str(registration["registration"]["output_schema_ref"]),
            ),
            "lane_templates": _lane_templates(index),
        }
        for index in range(item_count)
    ]
    question = finalize_research_candidate_question(
        question_id="question:f4-v2-fixture",
        candidate_generator_id="generator:f4-v2-fixture.v1",
        candidate_generator_source_sha256="a" * 64,
        active_surface_ref=str(active_surface["content_sha256"]),
        selection_manifest_ref=selection_manifest.content_hash,
        method_registry_sha256=canonical_sha256(registrations),
        source_dependency_graph_ref=str(graph["content_sha256"]),
        candidate_specs=[
            {
                "candidate_id": f"candidate-{index:04d}",
                "work_item": entry["work_item"],
                "lane_templates_sha256": canonical_sha256(entry["lane_templates"]),
                "portfolio_lane": "EXPLOITATION",
            }
            for index, entry in enumerate(ready)
        ],
    )
    question_ref, question_hash = _write(root / "research-question.json", question)
    candidate_snapshot = compile_research_candidate_snapshot(
        ready,
        research_question=question,
        active_surface=active_surface,
        selection_manifest=selection_manifest.model_dump(mode="json"),
        method_registry=registrations,
        source_dependency_graph=graph,
    )
    snapshot_ref, snapshot_hash = _write(
        root / "research-candidate-snapshot.json",
        candidate_snapshot,
    )
    allocation = compile_research_portfolio_allocation(
        candidate_snapshot,
        active_surface=active_surface,
        portfolio_policy=portfolio_policy,
        source_dependency_graph=graph,
    )
    allocation_ref, allocation_hash = _write(
        root / "research-portfolio-allocation.json",
        allocation,
    )
    frontier = {
        "schema_version": "xinao.foundation_continuous_frontier.v2",
        "external_model": SELECTED_MODEL,
        "external_worker_cwd": str(root.resolve()),
        "foundation_closed": foundation_closed,
        "source_dependency_graph_ref": graph_ref,
        "source_dependency_graph_sha256": graph_hash,
        "capacity_observation_ref": observation_ref,
        "capacity_observation_sha256": observation_hash,
        "selection_manifest_ref": selection_ref,
        "selection_manifest_sha256": selection_hash,
        "research_factory_manifest_ref": factory_manifest_ref,
        "research_factory_manifest_sha256": factory_manifest_hash,
        "method_registry_ref": registry_ref,
        "method_registry_sha256": registry_hash,
        "active_research_surface_ref": active_surface_ref,
        "active_research_surface_sha256": active_surface_hash,
        "research_portfolio_policy_ref": portfolio_policy_ref,
        "research_portfolio_policy_sha256": portfolio_policy_hash,
        "research_question_ref": question_ref,
        "research_question_sha256": question_hash,
        "research_candidate_snapshot_ref": snapshot_ref,
        "research_candidate_snapshot_sha256": snapshot_hash,
        "research_portfolio_allocation_ref": allocation_ref,
        "research_portfolio_allocation_sha256": allocation_hash,
        "payload_template_ref": template_ref,
        "payload_template_sha256": template_hash,
        "ready_frontier": ready,
        "wait_seconds": 3_600,
    }
    frontier_path = root / "frontier.json"
    _, frontier_hash = _write(frontier_path, frontier)
    return frontier_path, frontier_hash


def _strict_runtime_fixture(
    root: Path,
) -> tuple[Path, str, dict[str, object], dict[str, object]]:
    frontier_path, _ = _runtime_fixture(root, item_count=13)
    frontier = json.loads(frontier_path.read_text(encoding="utf-8"))
    graph = json.loads(
        Path(str(frontier["source_dependency_graph_ref"])).read_text(encoding="utf-8")
    )
    selection_value = json.loads(
        Path(str(frontier["selection_manifest_ref"])).read_text(encoding="utf-8")
    )
    from xinao.foundation.selection_manifest import (
        IndependentExpectedSelectionDomainManifestVersion,
    )

    selection_manifest = IndependentExpectedSelectionDomainManifestVersion.model_validate(
        selection_value
    )
    registrations = json.loads(
        Path(str(frontier["method_registry_ref"])).read_text(encoding="utf-8")
    )["registrations"]
    family_components: dict[str, set[str]] = {}
    for specification in selection_manifest.specifications:
        family_components.setdefault(specification.family_id, set()).update(
            specification.component_baseline_ids
        )
    family_ids = sorted(family_components)
    shares = ["0.069230769230"] * 12 + ["0.069230769240"]
    active_surface = _versioned_f3_object(
        "ActiveResearchSurfaceVersion",
        rows=[
            {
                "family_id": family_id,
                "active_component_ids": sorted(family_components[family_id]),
                "active_component_count": len(family_components[family_id]),
                "research_resource_share": share,
                "surface_state": "ACTIVE",
            }
            for family_id, share in zip(family_ids, shares, strict=True)
        ],
        summary={"family_count": 13, "by_surface_state": {"ACTIVE": 13}},
    )
    active_surface_ref, active_surface_hash = _write(
        Path(str(frontier["active_research_surface_ref"])),
        active_surface,
    )
    portfolio_policy = _versioned_f3_object(
        "ResearchPortfolioPolicyVersion",
        active_surface_ref=active_surface["content_sha256"],
        exploration_share="0.1",
        exploitation_share="0.9",
    )
    portfolio_policy_ref, portfolio_policy_hash = _write(
        Path(str(frontier["research_portfolio_policy_ref"])),
        portfolio_policy,
    )
    source = compile_f4_canary_candidate_source(
        active_research_surface=active_surface,
        selection_manifest=selection_manifest,
        method_registry={"registrations": registrations},
        method_id="method.f4-canary.v1",
        source_dependency_graph=graph,
        world_snapshot_hash="9" * 64,
        knowledge_cutoff="2026-07-14T00:00:00.000Z",
    )
    question_ref, question_hash = _write(
        Path(str(frontier["research_question_ref"])),
        source["research_question"],
    )
    source_snapshot_ref, source_snapshot_hash = _write(
        root / "research-candidate-source-snapshot.json",
        source["candidate_source_snapshot"],
    )
    candidate_snapshot = compile_f4_canary_candidate_snapshot(
        research_question=source["research_question"],
        candidate_source_snapshot=source["candidate_source_snapshot"],
        active_research_surface=active_surface,
        selection_manifest=selection_manifest,
        method_registry={"registrations": registrations},
        method_id="method.f4-canary.v1",
        source_dependency_graph=graph,
    )
    candidate_snapshot_ref, candidate_snapshot_hash = _write(
        Path(str(frontier["research_candidate_snapshot_ref"])),
        candidate_snapshot,
    )
    allocation = compile_research_portfolio_allocation(
        candidate_snapshot,
        active_surface=active_surface,
        portfolio_policy=portfolio_policy,
        source_dependency_graph=graph,
    )
    allocation_ref, allocation_hash = _write(
        Path(str(frontier["research_portfolio_allocation_ref"])),
        allocation,
    )
    frontier.update(
        {
            "schema_version": "xinao.foundation_continuous_frontier.v3",
            "active_research_surface_ref": active_surface_ref,
            "active_research_surface_sha256": active_surface_hash,
            "research_portfolio_policy_ref": portfolio_policy_ref,
            "research_portfolio_policy_sha256": portfolio_policy_hash,
            "research_question_ref": question_ref,
            "research_question_sha256": question_hash,
            "research_candidate_source_snapshot_ref": source_snapshot_ref,
            "research_candidate_source_snapshot_sha256": source_snapshot_hash,
            "research_candidate_snapshot_ref": candidate_snapshot_ref,
            "research_candidate_snapshot_sha256": candidate_snapshot_hash,
            "research_portfolio_allocation_ref": allocation_ref,
            "research_portfolio_allocation_sha256": allocation_hash,
        }
    )
    frontier.pop("ready_frontier")
    _, frontier_hash = _write(frontier_path, frontier)
    return frontier_path, frontier_hash, candidate_snapshot, allocation


async def _completed_v1_history(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    queue = "foundation-v1-roll-forward-fixture"
    workflow_id = "foundation-v1"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with Worker(
                env.client,
                task_queue=queue,
                workflows=[FoundationContinuousWorkflowV1],
                activities=[persist_foundation_state],
                activity_executor=executor,
            ):
                handle = await env.client.start_workflow(
                    FoundationContinuousWorkflowV1.run,
                    {
                        "operation_id": "roll-forward-v1-fixture",
                        "runtime_root": str(root),
                        "frontier_ref": str(root / "unused-frontier.json"),
                        "paused": True,
                    },
                    id=workflow_id,
                    task_queue=queue,
                )
                for _ in range(200):
                    state = await handle.query("state")
                    if state.get("status") == "PAUSED":
                        break
                    await asyncio.sleep(0.01)
                else:
                    raise AssertionError("V1 fixture never reached PAUSED")
                await handle.execute_update(
                    "control",
                    {
                        "operation_id": "cutover-stop-1",
                        "action": "STOP",
                        "reason": "version cutover",
                    },
                )
                final_state = await handle.result()
                history = await handle.fetch_history()
                return final_state, history.to_json_dict()


def _roll_forward_fixture(root: Path, operation_id: str) -> tuple[Path, str]:
    final_state, history_value = asyncio.run(_completed_v1_history(root))
    final_state_ref, final_state_hash = _write(
        root / "v1-final-state.json",
        final_state,
    )
    history_ref, history_hash = _write(root / "v1-history.json", history_value)
    history_event_count = len(history_value["events"])
    workflow_code_hash = hashlib.sha256(Path(foundation_v1.__file__).read_bytes()).hexdigest()
    replay_ref, replay_hash = _write(
        root / "v1-replay.json",
        {
            "schema_version": "xinao.temporal_replay_proof.v1",
            "proof_type": "TEMPORAL_SDK_REPLAYER",
            "ok": True,
            "workflow_type": "FoundationContinuousWorkflowV1",
            "workflow_id": final_state["workflow_id"],
            "run_id": final_state["run_id"],
            "history_sha256": history_hash,
            "workflow_code_sha256": workflow_code_hash,
            "event_count": history_event_count,
        },
    )
    manifest = {
        "schema_version": "xinao.foundation_roll_forward.v1_to_v2",
        "successor_operation_id": operation_id,
        "owner_generation": 1,
        "predecessor_workflow_id": final_state["workflow_id"],
        "predecessor_run_id": final_state["run_id"],
        "predecessor_workflow_code_sha256": workflow_code_hash,
        "predecessor_final_state_ref": final_state_ref,
        "predecessor_final_state_sha256": final_state_hash,
        "predecessor_history_ref": history_ref,
        "predecessor_history_sha256": history_hash,
        "predecessor_replay_ref": replay_ref,
        "predecessor_replay_sha256": replay_hash,
        "stop_operation_id": "cutover-stop-1",
    }
    path = root / "roll-forward.json"
    _, digest = _write(path, manifest)
    return path, digest


def _external_stage_result(
    root: Path,
    *,
    stage: str,
    lane_id: str,
    method_binding: dict[str, object],
    response: dict[str, object],
    include_method_output: bool = True,
) -> tuple[Path, str, dict[str, object]]:
    work_key = str(response["work_key"])
    stage_key = stage.lower()
    task_prompt = f"evidence-bound fixture prompt:{stage}:{lane_id}"
    prompt_sha256 = hashlib.sha256(task_prompt.encode("utf-8")).hexdigest()
    full_prompt = f"[Coordination metadata]\nfixture-token\nTask:\n{task_prompt}"
    result_json_schema = {"type": "object"}
    result_json_schema_sha256 = canonical_sha256(result_json_schema)
    required_result_markers = [f"F4_EVIDENCE_BOUND_CANARY:{stage}:{work_key[-12:]}"]
    operation_spec_ref, operation_spec_hash = _write(
        root / "external" / stage_key / lane_id / "operation-spec.json",
        {
            "prompt": full_prompt,
            "task_prompt_sha256": prompt_sha256,
            "full_prompt_sha256": hashlib.sha256(full_prompt.encode("utf-8")).hexdigest(),
            "model": SELECTED_MODEL,
            "contract_id": "xinao.foundation.f4.readonly_lane.v1",
            "write": False,
            "permission_mode": "approve-reads",
            "allowed_tools": ["read_file"],
            "result_format": "json_object",
            "result_json_schema_sha256": result_json_schema_sha256,
            "min_result_chars": 256,
            "required_result_markers": required_result_markers,
        },
    )
    work_item = _work(
        0,
        str(method_binding["method_registration_hash"]),
        str(method_binding["method_admission_hash"]),
        "1" * 64,
        "schema:fixture-output.v1",
    )
    work_item["correlation_id"] = f"fixture:{work_key}"
    work_item_content_hash = canonical_sha256(work_item)
    work_item_ref, work_item_hash = _write(
        root / "external" / "domain-bindings" / f"{work_item_content_hash}.json",
        work_item,
    )
    active_surface = _versioned_f3_object(
        "ActiveResearchSurfaceVersion",
        rows=[
            {
                "family_id": "special-number",
                "active_component_ids": ["BO0001"],
                "active_component_count": 1,
                "research_resource_share": "0.9",
                "surface_state": "ACTIVE",
            }
        ],
    )
    active_surface_ref, active_surface_hash = _write(
        root / "external" / "domain-bindings" / "active-surface.json",
        active_surface,
    )
    portfolio_policy = _versioned_f3_object(
        "ResearchPortfolioPolicyVersion",
        active_surface_ref=active_surface["content_sha256"],
        exploration_share="0.1",
        exploitation_share="0.9",
    )
    portfolio_policy_ref, portfolio_policy_hash = _write(
        root / "external" / "domain-bindings" / "portfolio-policy.json",
        portfolio_policy,
    )
    research_question = _versioned_f3_object(
        "ResearchQuestion",
        scope_complete=True,
    )
    research_question_ref, research_question_hash = _write(
        root / "external" / "domain-bindings" / "research-question.json",
        research_question,
    )
    candidate_snapshot = _versioned_f3_object(
        "ResearchCandidateSnapshot",
        research_question_ref=research_question["content_sha256"],
        active_surface_ref=active_surface["content_sha256"],
    )
    candidate_snapshot_ref, candidate_snapshot_hash = _write(
        root / "external" / "domain-bindings" / "candidate-snapshot.json",
        candidate_snapshot,
    )
    portfolio_allocation = _versioned_f3_object(
        "ResearchPortfolioAllocation",
        policy_ref=portfolio_policy["content_sha256"],
        active_surface_ref=active_surface["content_sha256"],
        candidate_snapshot_ref=candidate_snapshot["content_sha256"],
        ready_frontier_sha256="7" * 64,
    )
    portfolio_allocation_ref, portfolio_allocation_hash = _write(
        root / "external" / "domain-bindings" / "portfolio-allocation.json",
        portfolio_allocation,
    )
    method_input = {
        "schema_version": "xinao.f4_method_input.v1",
        "work_key": work_key,
        "stage": stage,
        "actor_id": lane_id,
        "method_id": str(method_binding["method_id"]),
        "method_admission_hash": str(method_binding["method_admission_hash"]),
        "method_material_bundle_sha256": str(method_binding["method_material_bundle_sha256"]),
        "work_item_content_sha256": work_item_content_hash,
        "upstream": {
            "producer_ref": str(response.get("target_artifact_ref") or ""),
            "producer_sha256": str(response.get("target_artifact_hash") or ""),
            "critique_ref": str(response.get("target_critique_ref") or ""),
            "critique_sha256": str(response.get("target_critique_hash") or ""),
        },
    }
    method_input_sha256 = canonical_sha256(method_input)
    response_binding: dict[str, object] = {
        "method_admission_hash": method_binding["method_admission_hash"],
        "method_executable_ref": method_binding["method_executable_ref"],
        "method_executable_sha256": method_binding["method_executable_sha256"],
        "method_material_bundle_sha256": method_binding["method_material_bundle_sha256"],
        "method_input_sha256": method_input_sha256,
    }
    if include_method_output:
        response_binding["method_output"] = {
            "applied": True,
            "stage": stage,
            "work_key": work_key,
            "method_evidence": (f"F4_EVIDENCE_BOUND_CANARY:{stage}:{work_key[-12:]}"),
        }
    final_response = {**response_binding, **response}
    lane_binding: dict[str, object] = {
        "work_key": work_key,
        "stage": stage,
        "actor_id": lane_id,
        "contract_id": "xinao.foundation.f4.readonly_lane.v1",
        "write": False,
        "allowed_tools": ["read_file"],
        "permission_mode": "approve-reads",
        "requested_model": SELECTED_MODEL,
        "prompt_sha256": prompt_sha256,
        "result_format": "json_object",
        "result_json_schema_sha256": result_json_schema_sha256,
        "min_result_chars": 256,
        "required_result_markers": required_result_markers,
        "method_input": method_input,
        "method_input_sha256": method_input_sha256,
        "work_item_ref": work_item_ref,
        "work_item_sha256": work_item_hash,
        "work_item_content_sha256": work_item_content_hash,
        "active_research_surface_ref": active_surface_ref,
        "active_research_surface_sha256": active_surface_hash,
        "active_research_surface_content_sha256": active_surface["content_sha256"],
        "research_portfolio_policy_ref": portfolio_policy_ref,
        "research_portfolio_policy_sha256": portfolio_policy_hash,
        "research_portfolio_policy_content_sha256": portfolio_policy["content_sha256"],
        "research_question_ref": research_question_ref,
        "research_question_sha256": research_question_hash,
        "research_question_content_sha256": research_question["content_sha256"],
        "research_candidate_snapshot_ref": candidate_snapshot_ref,
        "research_candidate_snapshot_sha256": candidate_snapshot_hash,
        "research_candidate_snapshot_content_sha256": candidate_snapshot["content_sha256"],
        "research_portfolio_allocation_ref": portfolio_allocation_ref,
        "research_portfolio_allocation_sha256": portfolio_allocation_hash,
        "research_portfolio_allocation_content_sha256": portfolio_allocation["content_sha256"],
        "ready_frontier_sha256": portfolio_allocation["ready_frontier_sha256"],
    }
    final_path = root / "external" / stage_key / lane_id / "final.txt"
    final_ref, final_hash = _write(final_path, final_response)
    manifest_ref, manifest_hash = _write(
        root / "external" / stage_key / "manifest.json",
        {
            "ready_width": 1,
            "lanes": [
                {
                    "lane_id": lane_id,
                    "operation_state": "completed",
                    "contract_id": lane_binding["contract_id"],
                    "write": False,
                    "allowed_tools": lane_binding["allowed_tools"],
                    "requested_model": SELECTED_MODEL,
                    "observed_model": BACKEND_MODEL,
                    "session_model_evidence": {
                        "source": "acpx_runtime_status_after_turn",
                        "requestedModel": SELECTED_MODEL,
                        "currentModelId": SELECTED_MODEL,
                        "availableModelIds": [SELECTED_MODEL],
                        "acpxRecordId": f"acpx-{lane_id}",
                        "backendSessionId": f"backend-{lane_id}",
                    },
                    "session_model_evidence_valid": True,
                    "prompt_sha256": prompt_sha256,
                    "result_format": "json_object",
                    "result_json_schema_sha256": result_json_schema_sha256,
                    "min_result_chars": 256,
                    "required_result_markers": required_result_markers,
                    "operation_spec_sha256": operation_spec_hash,
                    "artifacts": [
                        {
                            "name": "operation-spec.json",
                            "uri": operation_spec_ref,
                            "sha256": operation_spec_hash,
                        },
                        {
                            "name": "final.txt",
                            "uri": final_ref,
                            "sha256": final_hash,
                        },
                    ],
                }
            ],
        },
    )
    return_path = root / "external" / stage_key / "result.json"
    return_ref, return_hash = _write(
        return_path,
        {
            "workflow_id": f"workflow-{stage_key}",
            "run_id": f"run-{stage_key}",
            "result": {
                "grok_fanin": {
                    "ok": True,
                    "manifest_path": manifest_ref,
                    "manifest_sha256": manifest_hash,
                    "ready_width": 1,
                    "lane_count": 1,
                    "provider_id": "grok_acpx_headless",
                    "model": SELECTED_MODEL,
                    "model_identity_ok": True,
                    "model_identity_binding": (
                        foundation_v2.grok_docker_model_identity_binding(SELECTED_MODEL)
                    ),
                    "observed_model": BACKEND_MODEL,
                    "observed_models": BACKEND_MODELS,
                    "observed_backend_models": BACKEND_MODELS,
                    "succeeded": 1,
                    "failed": 0,
                }
            },
        },
    )
    assert return_ref == str(return_path)
    return return_path, return_hash, lane_binding


def test_plan_dispatch_materializes_exact_decision_width(tmp_path: Path) -> None:
    from jsonschema import Draft202012Validator, ValidationError

    frontier, frontier_hash = _runtime_fixture(tmp_path, item_count=4)
    decision = reconcile_foundation_frontier_v2(
        {
            "runtime_root": str(tmp_path),
            "operation_id": "f4-v2-test",
            "frontier_ref": str(frontier),
            "frontier_sha256": frontier_hash,
            "previous_width": 1,
            "succeeded": 1,
            "failed": 0,
        }
    )
    assert decision["capacity_decision"]["dispatch_width"] == 2
    assert len(decision["wave"]["work_keys"]) == 2
    payload = json.loads(Path(decision["wave"]["payload_ref"]).read_text(encoding="utf-8"))
    assert payload["research_stage"] == "PRODUCER"
    assert len(payload["grok_ready_frontier"]) == 2
    assert payload["canonical_work_keys"] == decision["wave"]["work_keys"]
    for lane in payload["grok_ready_frontier"]:
        assert lane["result_format"] == "json_object"
        assert "min_result_chars" not in lane
        assert "required_result_markers" not in lane
        schema = lane["result_json_schema"]
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        with pytest.raises(ValidationError):
            validator.validate({})
        with pytest.raises(ValidationError):
            validator.validate("```json\n{}\n```")
        binding = payload["lane_bindings"][lane["lane_id"]]
        assert binding["result_format"] == "json_object"
        assert (
            binding["result_json_schema_sha256"]
            == hashlib.sha256(foundation_v2.artifact_json_bytes(schema)).hexdigest()
        )
        assert "required_result_markers" not in binding


def test_v3_dispatch_uses_exact_f3_source_allocation_prefix(tmp_path: Path) -> None:
    frontier, frontier_hash, candidate_snapshot, allocation = _strict_runtime_fixture(tmp_path)
    frontier_value = json.loads(frontier.read_text(encoding="utf-8"))
    graph = json.loads(
        Path(str(frontier_value["source_dependency_graph_ref"])).read_text(encoding="utf-8")
    )
    legacy = dedupe_ready_frontier(
        [row["entry"]["work_item"] for row in candidate_snapshot["candidate_rows"]],
        source_dependency_graph=graph,
    )
    assert legacy["ready_work_keys"] != allocation["ready_work_keys"]

    decision = reconcile_foundation_frontier_v2(
        {
            "runtime_root": str(tmp_path),
            "operation_id": "f4-v3-strict-test",
            "frontier_ref": str(frontier),
            "frontier_sha256": frontier_hash,
            "previous_width": 1,
            "succeeded": 1,
            "failed": 0,
        }
    )
    assert decision["capacity_decision"]["dispatch_width"] == 2
    assert decision["wave"]["work_keys"] == allocation["ready_work_keys"][:2]
    payload = json.loads(Path(decision["wave"]["payload_ref"]).read_text(encoding="utf-8"))
    assert payload["canonical_work_keys"] == allocation["ready_work_keys"][:2]
    assert (
        payload["research_surface_binding"]["frontier_binding_mode"]
        == "STRICT_F3_SURFACE_SOURCE_BOUND"
    )
    assert (
        payload["research_surface_binding"]["research_candidate_source_snapshot_content_sha256"]
        == candidate_snapshot["candidate_source_snapshot_ref"]
    )

    unknown = json.loads(frontier.read_text(encoding="utf-8"))
    unknown["schema_version"] = "xinao.foundation_continuous_frontier.v4"
    unknown_ref, unknown_hash = _write(tmp_path / "unknown-frontier.json", unknown)
    with pytest.raises(ValueError, match="not an admitted v2/v3 version"):
        reconcile_foundation_frontier_v2(
            {
                "runtime_root": str(tmp_path),
                "operation_id": "f4-v3-unknown-schema-negative",
                "frontier_ref": unknown_ref,
                "frontier_sha256": unknown_hash,
            }
        )

    tampered = json.loads(frontier.read_text(encoding="utf-8"))
    tampered["ready_frontier"] = []
    _, tampered_hash = _write(frontier, tampered)
    with pytest.raises(ValueError, match="forbids caller-provided ready_frontier"):
        reconcile_foundation_frontier_v2(
            {
                "runtime_root": str(tmp_path),
                "operation_id": "f4-v3-raw-ready-negative",
                "frontier_ref": str(frontier),
                "frontier_sha256": tampered_hash,
            }
        )


def test_partial_capacity_downshifts_and_bare_closed_is_rejected(tmp_path: Path) -> None:
    frontier, frontier_hash = _runtime_fixture(
        tmp_path,
        item_count=1,
        foundation_closed=True,
    )
    decision = reconcile_foundation_frontier_v2(
        {
            "runtime_root": str(tmp_path),
            "operation_id": "f4-v2-test",
            "frontier_ref": str(frontier),
            "frontier_sha256": frontier_hash,
            "previous_width": 2,
            "succeeded": 1,
            "failed": 1,
            "partial": True,
            "closed_work_keys": [],
        }
    )
    assert decision["capacity_decision"]["capacity_tier"] == 1
    assert decision["wave"]["capacity_decision"]["dispatch_width"] == 1

    value = json.loads(frontier.read_text(encoding="utf-8"))
    value["ready_frontier"] = []
    active_surface_value = json.loads(
        Path(str(value["active_research_surface_ref"])).read_text(encoding="utf-8")
    )
    portfolio_policy_value = json.loads(
        Path(str(value["research_portfolio_policy_ref"])).read_text(encoding="utf-8")
    )
    source_graph_value = json.loads(
        Path(str(value["source_dependency_graph_ref"])).read_text(encoding="utf-8")
    )
    selection_value = json.loads(
        Path(str(value["selection_manifest_ref"])).read_text(encoding="utf-8")
    )
    registrations = json.loads(Path(str(value["method_registry_ref"])).read_text(encoding="utf-8"))[
        "registrations"
    ]
    empty_question = finalize_research_candidate_question(
        question_id="question:f4-v2-empty-fixture",
        candidate_generator_id="generator:f4-v2-fixture.v1",
        candidate_generator_source_sha256="a" * 64,
        active_surface_ref=str(active_surface_value["content_sha256"]),
        selection_manifest_ref=str(selection_value["content_hash"]),
        method_registry_sha256=canonical_sha256(registrations),
        source_dependency_graph_ref=str(source_graph_value["content_sha256"]),
        candidate_specs=[],
    )
    _, empty_question_hash = _write(
        Path(str(value["research_question_ref"])),
        empty_question,
    )
    value["research_question_sha256"] = empty_question_hash
    empty_snapshot = compile_research_candidate_snapshot(
        [],
        research_question=empty_question,
        active_surface=active_surface_value,
        selection_manifest=selection_value,
        method_registry=registrations,
        source_dependency_graph=source_graph_value,
    )
    _, empty_snapshot_hash = _write(
        Path(str(value["research_candidate_snapshot_ref"])),
        empty_snapshot,
    )
    value["research_candidate_snapshot_sha256"] = empty_snapshot_hash
    empty_allocation = compile_research_portfolio_allocation(
        empty_snapshot,
        active_surface=active_surface_value,
        portfolio_policy=portfolio_policy_value,
        source_dependency_graph=source_graph_value,
    )
    _, empty_allocation_hash = _write(
        Path(str(value["research_portfolio_allocation_ref"])),
        empty_allocation,
    )
    value["research_portfolio_allocation_sha256"] = empty_allocation_hash
    _, empty_hash = _write(frontier, value)
    waiting = reconcile_foundation_frontier_v2(
        {
            "runtime_root": str(tmp_path),
            "operation_id": "f4-v2-test",
            "frontier_ref": str(frontier),
            "frontier_sha256": empty_hash,
        }
    )
    assert waiting["action"] == "WAIT"
    assert waiting["reason"] == "DEPRECATED_BARE_FOUNDATION_CLOSED_REJECTED"


def test_frozen_route_quote_never_reaches_temporal_dispatch(tmp_path: Path) -> None:
    frontier, _ = _runtime_fixture(tmp_path, item_count=1)
    value = json.loads(frontier.read_text(encoding="utf-8"))
    value["ready_frontier"][0]["work_item"]["physical_role"] = "FROZEN_AGENT_ROUTE_QUOTE"
    _, frozen_hash = _write(frontier, value)

    with pytest.raises(ValueError, match="ACTIVE_SETTLEMENT"):
        reconcile_foundation_frontier_v2(
            {
                "runtime_root": str(tmp_path),
                "operation_id": "f4-v2-frozen-negative",
                "frontier_ref": str(frontier),
                "frontier_sha256": frozen_hash,
            }
        )


def test_roll_forward_requires_exact_stopped_predecessor(tmp_path: Path) -> None:
    manifest, digest = _roll_forward_fixture(tmp_path, "f4-v2-test")
    result = verify_roll_forward_manifest_v2(
        {
            "runtime_root": str(tmp_path),
            "operation_id": "f4-v2-test",
            "owner_generation": 1,
            "manifest_ref": str(manifest),
            "manifest_sha256": digest,
        }
    )
    assert result["ok"] is True

    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["owner_generation"] = 2
    _, drifted = _write(manifest, value)
    try:
        verify_roll_forward_manifest_v2(
            {
                "runtime_root": str(tmp_path),
                "operation_id": "f4-v2-test",
                "owner_generation": 1,
                "manifest_ref": str(manifest),
                "manifest_sha256": drifted,
            }
        )
    except ValueError as exc:
        assert "generation" in str(exc)
    else:
        raise AssertionError("drifted owner generation was accepted")


def test_roll_forward_rejects_non_temporal_history_even_when_rehashed(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _roll_forward_fixture(tmp_path, "f4-v2-invalid-history")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    history_path = Path(manifest["predecessor_history_ref"])
    _, history_hash = _write(history_path, {"not_temporal_history": True})
    manifest["predecessor_history_sha256"] = history_hash

    replay_path = Path(manifest["predecessor_replay_ref"])
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay["history_sha256"] = history_hash
    replay["event_count"] = 0
    _, replay_hash = _write(replay_path, replay)
    manifest["predecessor_replay_sha256"] = replay_hash
    _, manifest_hash = _write(manifest_path, manifest)

    with pytest.raises(ValueError, match="Temporal history"):
        verify_roll_forward_manifest_v2(
            {
                "runtime_root": str(tmp_path),
                "operation_id": "f4-v2-invalid-history",
                "owner_generation": 1,
                "manifest_ref": str(manifest_path),
                "manifest_sha256": manifest_hash,
            }
        )


def test_external_result_rejects_manifest_modified_after_result(
    tmp_path: Path,
) -> None:
    work_key = "f" * 64
    method_binding = _method_binding(tmp_path)
    result_path, result_hash, lane_binding = _external_stage_result(
        tmp_path,
        stage="PRODUCER",
        lane_id="producer-manifest-drift",
        method_binding=method_binding,
        response={
            "work_key": work_key,
            "producer_id": "producer-manifest-drift",
            "status": "VERIFIED",
            "claim_refs": [],
        },
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest_path = Path(result["result"]["grok_fanin"]["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["ready_width"] = 2
    _write(manifest_path, manifest)

    with pytest.raises(ValueError, match="manifest hash"):
        inspect_external_wave_result_v2(
            {
                "runtime_root": str(tmp_path),
                "result_ref": str(result_path),
                "result_sha256": result_hash,
                "lane_ids": ["producer-manifest-drift"],
                "work_keys": [work_key],
                "stage": "PRODUCER",
                "method_bindings": {work_key: method_binding},
                "lane_bindings": {"producer-manifest-drift": lane_binding},
                "prior_stage_records": {},
            }
        )


def test_three_external_stages_bind_artifacts_and_finalize_without_vote(
    tmp_path: Path,
) -> None:
    work_key = "a" * 64
    method_binding = _method_binding(tmp_path)
    producer_path, producer_result_hash, producer_lane_binding = _external_stage_result(
        tmp_path,
        stage="PRODUCER",
        lane_id="producer-0",
        method_binding=method_binding,
        response={
            "work_key": work_key,
            "producer_id": "producer-0",
            "status": "VERIFIED",
            "claim_refs": ["claim:one"],
        },
    )
    producer = inspect_external_wave_result_v2(
        {
            "runtime_root": str(tmp_path),
            "result_ref": str(producer_path),
            "result_sha256": producer_result_hash,
            "lane_ids": ["producer-0"],
            "work_keys": [work_key],
            "stage": "PRODUCER",
            "method_bindings": {work_key: method_binding},
            "lane_bindings": {"producer-0": producer_lane_binding},
            "prior_stage_records": {},
        }
    )
    producer_record = producer["stage_records"][work_key]

    critique_path, critique_result_hash, critique_lane_binding = _external_stage_result(
        tmp_path,
        stage="CRITIQUE",
        lane_id="critic-0",
        method_binding=method_binding,
        response={
            "work_key": work_key,
            "critic_id": "critic-0",
            "target_artifact_ref": producer_record["artifact_ref"],
            "target_artifact_hash": producer_record["artifact_hash"],
            "verdict": "APPROVED",
            "finding_refs": [],
        },
    )
    critique = inspect_external_wave_result_v2(
        {
            "runtime_root": str(tmp_path),
            "result_ref": str(critique_path),
            "result_sha256": critique_result_hash,
            "lane_ids": ["critic-0"],
            "work_keys": [work_key],
            "stage": "CRITIQUE",
            "method_bindings": {work_key: method_binding},
            "lane_bindings": {"critic-0": critique_lane_binding},
            "prior_stage_records": {"PRODUCER": producer["stage_records"]},
        }
    )
    critique_record = critique["stage_records"][work_key]

    verifier_path, verifier_result_hash, verifier_lane_binding = _external_stage_result(
        tmp_path,
        stage="VERIFIER",
        lane_id="verifier-0",
        method_binding=method_binding,
        response={
            "work_key": work_key,
            "verifier_id": "verifier-0",
            "target_artifact_ref": producer_record["artifact_ref"],
            "target_artifact_hash": producer_record["artifact_hash"],
            "target_critique_ref": critique_record["critique_artifact_ref"],
            "target_critique_hash": critique_record["critique_artifact_hash"],
            "verdict": "VERIFIED",
            "evidence_refs": [],
        },
    )
    verifier = inspect_external_wave_result_v2(
        {
            "runtime_root": str(tmp_path),
            "result_ref": str(verifier_path),
            "result_sha256": verifier_result_hash,
            "lane_ids": ["verifier-0"],
            "work_keys": [work_key],
            "stage": "VERIFIER",
            "method_bindings": {work_key: method_binding},
            "lane_bindings": {"verifier-0": verifier_lane_binding},
            "prior_stage_records": {
                "PRODUCER": producer["stage_records"],
                "CRITIQUE": critique["stage_records"],
            },
        }
    )
    final = finalize_research_fan_in_v2(
        {
            "runtime_root": str(tmp_path),
            "operation_id": "f4-three-stage-test",
            "expected_work_keys": [work_key],
            "stage_records": {
                "PRODUCER": producer["stage_records"],
                "CRITIQUE": critique["stage_records"],
                "VERIFIER": verifier["stage_records"],
            },
            "method_bindings": {work_key: method_binding},
        }
    )

    assert final["fanin"]["accepted_work_keys"] == [work_key]
    assert final["fanin"]["unresolved_work_keys"] == []
    assert final["fanin"]["majority_vote_used"] is False
    assert Path(final["fanin_ref"]).is_file()


def test_external_result_requires_schema_valid_method_output(tmp_path: Path) -> None:
    work_key = "c" * 64
    method_binding = _method_binding(tmp_path)
    result_path, result_hash, lane_binding = _external_stage_result(
        tmp_path,
        stage="PRODUCER",
        lane_id="producer-no-method-output",
        method_binding=method_binding,
        include_method_output=False,
        response={
            "work_key": work_key,
            "producer_id": "producer-no-method-output",
            "status": "VERIFIED",
            "claim_refs": [],
        },
    )

    with pytest.raises(ValueError, match="no admitted method output"):
        inspect_external_wave_result_v2(
            {
                "runtime_root": str(tmp_path),
                "result_ref": str(result_path),
                "result_sha256": result_hash,
                "lane_ids": ["producer-no-method-output"],
                "work_keys": [work_key],
                "stage": "PRODUCER",
                "method_bindings": {work_key: method_binding},
                "lane_bindings": {"producer-no-method-output": lane_binding},
                "prior_stage_records": {},
            }
        )


def test_external_result_rejects_method_snapshot_drift(tmp_path: Path) -> None:
    work_key = "d" * 64
    method_binding = _method_binding(tmp_path)
    result_path, result_hash, lane_binding = _external_stage_result(
        tmp_path,
        stage="PRODUCER",
        lane_id="producer-method-drift",
        method_binding=method_binding,
        response={
            "work_key": work_key,
            "producer_id": "producer-method-drift",
            "status": "VERIFIED",
            "claim_refs": [],
        },
    )
    executable_snapshot = Path(method_binding["materials"]["executable"]["artifact_ref"])
    executable_snapshot.write_text("drifted", encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot hash drifted"):
        inspect_external_wave_result_v2(
            {
                "runtime_root": str(tmp_path),
                "result_ref": str(result_path),
                "result_sha256": result_hash,
                "lane_ids": ["producer-method-drift"],
                "work_keys": [work_key],
                "stage": "PRODUCER",
                "method_bindings": {work_key: method_binding},
                "lane_bindings": {"producer-method-drift": lane_binding},
                "prior_stage_records": {},
            }
        )


def test_critique_cannot_bind_a_different_producer_artifact(tmp_path: Path) -> None:
    work_key = "b" * 64
    method_binding = _method_binding(tmp_path)
    producer_path, producer_result_hash, producer_lane_binding = _external_stage_result(
        tmp_path,
        stage="PRODUCER",
        lane_id="producer-1",
        method_binding=method_binding,
        response={
            "work_key": work_key,
            "producer_id": "producer-1",
            "status": "VERIFIED",
            "claim_refs": [],
        },
    )
    producer = inspect_external_wave_result_v2(
        {
            "runtime_root": str(tmp_path),
            "result_ref": str(producer_path),
            "result_sha256": producer_result_hash,
            "lane_ids": ["producer-1"],
            "work_keys": [work_key],
            "stage": "PRODUCER",
            "method_bindings": {work_key: method_binding},
            "lane_bindings": {"producer-1": producer_lane_binding},
            "prior_stage_records": {},
        }
    )
    critique_path, critique_result_hash, critique_lane_binding = _external_stage_result(
        tmp_path,
        stage="CRITIQUE",
        lane_id="critic-1",
        method_binding=method_binding,
        response={
            "work_key": work_key,
            "critic_id": "critic-1",
            "target_artifact_ref": producer["stage_records"][work_key]["artifact_ref"],
            "target_artifact_hash": "0" * 64,
            "verdict": "APPROVED",
            "finding_refs": [],
        },
    )
    with pytest.raises(ValueError, match="method input does not match stage dependencies"):
        inspect_external_wave_result_v2(
            {
                "runtime_root": str(tmp_path),
                "result_ref": str(critique_path),
                "result_sha256": critique_result_hash,
                "lane_ids": ["critic-1"],
                "work_keys": [work_key],
                "stage": "CRITIQUE",
                "method_bindings": {work_key: method_binding},
                "lane_bindings": {"critic-1": critique_lane_binding},
                "prior_stage_records": {"PRODUCER": producer["stage_records"]},
            }
        )


def test_reconcile_rejects_self_consistent_selection_manifest_tamper(
    tmp_path: Path,
) -> None:
    frontier_path, _ = _runtime_fixture(tmp_path, item_count=1)
    frontier = json.loads(frontier_path.read_text(encoding="utf-8"))
    selection_path = Path(str(frontier["selection_manifest_ref"]))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    specification = selection["specifications"][0]
    specification["play_name"] = "SELF_CONSISTENT_TAMPER"
    specification["content_hash"] = canonical_sha256(
        {key: value for key, value in specification.items() if key != "content_hash"}
    )
    selection["content_hash"] = canonical_sha256(
        {key: value for key, value in selection.items() if key != "content_hash"}
    )
    _, selection_file_hash = _write(selection_path, selection)
    frontier["selection_manifest_sha256"] = selection_file_hash
    _, frontier_hash = _write(frontier_path, frontier)

    with pytest.raises(ValueError, match="current canonical compiler output"):
        reconcile_foundation_frontier_v2(
            {
                "runtime_root": str(tmp_path),
                "operation_id": "tampered-selection-manifest",
                "frontier_ref": str(frontier_path),
                "frontier_sha256": frontier_hash,
            }
        )


def test_method_registry_allows_distinct_refs_with_identical_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission, _, _ = _admitted_method(tmp_path)
    registration = dict(admission["registration"])
    resolved = dict(admission["resolved_content_hashes"])
    input_path = Path(str(registration["input_schema_ref"]))
    output_path = Path(str(registration["output_schema_ref"]))
    output_path.write_bytes(input_path.read_bytes())
    shared_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    registration["output_schema_sha256"] = shared_hash
    resolved[str(output_path)] = shared_hash
    updated = admit_open_method(registration, resolved_content_hashes=resolved)
    monkeypatch.setattr(
        foundation_v2,
        "_validate_method_contract_materials",
        lambda *_args, **_kwargs: {"ok": True},
    )

    _, materialized = _validate_method_registry_artifacts(
        tmp_path,
        {"method.f4-canary.v1": updated},
    )
    materials = materialized["method.f4-canary.v1"]["materials"]
    assert materials["input_schema"]["sha256"] == materials["output_schema"]["sha256"]


@pytest.mark.parametrize(
    ("method_output_patch", "message"),
    [
        ({"stage": "VERIFIER"}, "stage does not match dispatch"),
        ({"work_key": "0" * 64}, "work key does not match dispatch"),
        ({"method_evidence": "abcdefghijkl"}, "executable evidence rule"),
    ],
)
def test_method_execution_rejects_schema_valid_semantic_drift(
    tmp_path: Path,
    method_output_patch: dict[str, object],
    message: str,
) -> None:
    work_key = "d" * 64
    method_binding = _method_binding(tmp_path)
    method_output = {
        "applied": True,
        "stage": "PRODUCER",
        "work_key": work_key,
        "method_evidence": (f"F4_EVIDENCE_BOUND_CANARY:PRODUCER:{work_key[-12:]}"),
        **method_output_patch,
    }
    result_path, result_hash, lane_binding = _external_stage_result(
        tmp_path,
        stage="PRODUCER",
        lane_id="producer-semantic-drift",
        method_binding=method_binding,
        response={
            "work_key": work_key,
            "producer_id": "producer-semantic-drift",
            "method_output": method_output,
            "status": "VERIFIED",
            "claim_refs": [],
        },
    )

    with pytest.raises(ValueError, match=message):
        inspect_external_wave_result_v2(
            {
                "runtime_root": str(tmp_path),
                "result_ref": str(result_path),
                "result_sha256": result_hash,
                "lane_ids": ["producer-semantic-drift"],
                "work_keys": [work_key],
                "stage": "PRODUCER",
                "method_bindings": {work_key: method_binding},
                "lane_bindings": {"producer-semantic-drift": lane_binding},
                "prior_stage_records": {},
            }
        )


@pytest.mark.parametrize("mutation", ["duplicate-final", "missing-model-evidence"])
def test_external_lane_rejects_ambiguous_artifact_or_model_identity(
    tmp_path: Path,
    mutation: str,
) -> None:
    work_key = "e" * 64
    method_binding = _method_binding(tmp_path)
    result_path, _, lane_binding = _external_stage_result(
        tmp_path,
        stage="PRODUCER",
        lane_id="producer-identity-negative",
        method_binding=method_binding,
        response={
            "work_key": work_key,
            "producer_id": "producer-identity-negative",
            "status": "VERIFIED",
            "claim_refs": [],
        },
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest_path = Path(str(result["result"]["grok_fanin"]["manifest_path"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lane = manifest["lanes"][0]
    if mutation == "duplicate-final":
        final_artifact = next(value for value in lane["artifacts"] if value["name"] == "final.txt")
        lane["artifacts"].append(dict(final_artifact))
        expected = "artifact names must be unique"
    else:
        lane.pop("session_model_evidence")
        lane.pop("session_model_evidence_valid")
        expected = "no session model evidence"
    _, manifest_hash = _write(manifest_path, manifest)
    result["result"]["grok_fanin"]["manifest_sha256"] = manifest_hash
    _, result_hash = _write(result_path, result)

    with pytest.raises(ValueError, match=expected):
        inspect_external_wave_result_v2(
            {
                "runtime_root": str(tmp_path),
                "result_ref": str(result_path),
                "result_sha256": result_hash,
                "lane_ids": ["producer-identity-negative"],
                "work_keys": [work_key],
                "stage": "PRODUCER",
                "method_bindings": {work_key: method_binding},
                "lane_bindings": {"producer-identity-negative": lane_binding},
                "prior_stage_records": {},
            }
        )


def test_v2_workflow_uses_same_temporal_worker_and_stops_cleanly(tmp_path: Path) -> None:
    operation_id = "f4-v2-workflow-test"
    frontier, frontier_hash = _runtime_fixture(tmp_path, item_count=0)
    manifest, manifest_hash = _roll_forward_fixture(tmp_path, operation_id)
    initial = {
        "operation_id": operation_id,
        "runtime_root": str(tmp_path),
        "frontier_ref": str(frontier),
        "frontier_sha256": frontier_hash,
        "roll_forward_manifest_ref": str(manifest),
        "roll_forward_manifest_sha256": manifest_hash,
        "owner_generation": 1,
        "default_wait_seconds": 3_600,
    }
    assert _initial_state_v2(initial)["owner_generation"] == 1

    async def exercise() -> dict[str, object]:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    env.client,
                    task_queue="xinao-mainline-canary-queue",
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
                ):
                    handle = await env.client.start_workflow(
                        FoundationContinuousWorkflowV2.run,
                        initial,
                        id="foundation-v2-time-skip",
                        task_queue="xinao-mainline-canary-queue",
                    )
                    for _ in range(200):
                        state = await handle.query("state")
                        if state.get("status") == "WAITING":
                            break
                        await asyncio.sleep(0.01)
                    await handle.execute_update(
                        "control",
                        {
                            "operation_id": "test-stop",
                            "action": "STOP",
                            "reason": "test complete",
                        },
                    )
                    return await handle.result()

    terminal = asyncio.run(exercise())
    assert terminal["status"] == "STOPPED"
    assert terminal["roll_forward_verification"]["ok"] is True
