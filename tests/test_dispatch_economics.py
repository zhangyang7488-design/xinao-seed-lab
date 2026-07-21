from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest
from services.agent_runtime.dispatch_economics import (
    DispatchEconomicsError,
    build_dispatch_outcome_event,
    build_route_choice_identity,
    build_worker_package_identity,
    claim_dispatch_route,
    neutral_output_contract_sha256,
    plan_package_frontier,
    project_dispatch_outcomes,
    validate_candidate_consumer_binding,
    validate_dispatch_envelope,
    validate_dispatch_route_claim,
    validate_package_batch_manifest,
)
from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    canonical_json_bytes,
    logical_contract_sha256,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
    GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
    GROK_DOCKER_CONSUMER_ID,
    build_direct_worker_pool_logical_contract,
    build_grok_docker_route_adapter_binding,
    direct_worker_pool_capability_binding,
    direct_worker_pool_context_binding_sha256,
    direct_worker_pool_output_contract,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _sha(path)


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha(path)}


def _context_manifest(path: Path, *, content_sha: str) -> str:
    content = "bounded\n"
    content_bytes = content.encode("utf-8")
    source_identity = [
        {
            "path": "input.txt",
            "sha256": content_sha,
            "bytes": len(content_bytes),
        }
    ]
    slice_row = {
        "selector": {"kind": "line_range", "start": 1, "end": 1},
        "line_start": 1,
        "line_end": 1,
        "content_sha256": content_sha,
        "content_bytes": len(content_bytes),
        "content": content,
    }
    identity_slice = dict(slice_row)
    identity_slice.pop("content")
    context_identity = {
        "schema_version": "xinao.context_slice_identity.v1",
        "sources": [
            {
                "path": "input.txt",
                "source_sha256": content_sha,
                "source_bytes": len(content_bytes),
                "slices": [identity_slice],
            }
        ],
    }
    return _write_json(
        path,
        {
            "schema_version": "xinao.context_slice_manifest.v1",
            "authority": False,
            "completion_claim_allowed": False,
            "spec_sha256": "a" * 64,
            "source_manifest_sha256": hashlib.sha256(
                canonical_json_bytes(source_identity)
            ).hexdigest(),
            "context_sha256": hashlib.sha256(canonical_json_bytes(context_identity)).hexdigest(),
            "total_content_bytes": len(content_bytes),
            "sources": [
                {
                    "path": "input.txt",
                    "source_sha256": content_sha,
                    "source_bytes": len(content_bytes),
                    "slices": [slice_row],
                }
            ],
            "false_green_deny": "fixture context is input only",
        },
    )


def _fixture(
    tmp_path: Path,
    *,
    dependency_condition: str = "owner_adopted",
    second_candidate_only: bool = True,
    parent_work_key: str = "parent-work",
    first_package_id: str = "p1",
    second_package_id: str = "p2",
    first_work_key: str = "wk-1",
    second_work_key: str = "wk-2",
) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "evidence" / "packages"
    (output / first_package_id).mkdir(parents=True)
    (output / second_package_id).mkdir(parents=True)
    prompt_one = source / "p1.md"
    prompt_two = source / "p2.md"
    prompt_one.write_text("package one\n", encoding="utf-8")
    prompt_two.write_text("package two\n", encoding="utf-8")
    input_file = source / "input.txt"
    input_file.write_bytes(b"bounded\n")
    context = source / "context.json"
    context_sha = _context_manifest(context, content_sha=_sha(input_file))
    rules = source / "rules.txt"
    rules.write_text("bounded worker rules\n", encoding="utf-8")
    quota = source / "quota.json"
    quota_sha = _write_json(
        quota,
        {
            "schema_version": "xinao.quota_dispatch_epoch_snapshot.v1",
            "snapshot_id": "quota-snapshot-1",
            "epoch_id": "epoch-1",
            "freshness": "fresh",
        },
    )
    selection = source / "selection.json"
    selected_candidate = {
        "provider_id": "grok_acpx_headless",
        "profile_ref": "grok.com.cached_profile",
        "model_id": "grok-4.5",
        "transport_id": "direct-grok-worker-pool",
        "declared_active": True,
        "healthy": True,
        "positive_benefit": True,
    }
    selection_receipt: dict[str, object] = {
        "schema_version": "xinao.supervisor_worker_decision_receipt.v1",
        "decision": "selected",
        "selected_candidate": selected_candidate,
    }
    selection_receipt["decision_sha256"] = hashlib.sha256(
        canonical_json_bytes(selection_receipt)
    ).hexdigest()
    selection_sha = _write_json(
        selection,
        selection_receipt,
    )

    def package(
        package_id: str,
        work_key: str,
        prompt: Path,
        dependencies: list[object],
        *,
        candidate_only: bool,
    ) -> dict[str, object]:
        acceptance = {
            "min_result_chars": 1,
            "required_result_markers": ["OK"],
            "require_json_object": False,
        }
        identity = build_worker_package_identity(
            package_id=package_id,
            work_key=work_key,
            parent_work_key=parent_work_key,
            work_class="local_audit",
            role=f"role-{package_id}",
            phase="EXPLORE",
            input_sha256=_sha(input_file),
            context_sha256=context_sha,
            rules_sha256=_sha(rules),
            output_contract_sha256=neutral_output_contract_sha256(acceptance),
            write_domains=[] if candidate_only else [f"owner:{package_id}"],
            candidate_only=candidate_only,
        )
        return {
            **identity,
            "prompt_ref": {"path": str(prompt), "sha256": _sha(prompt)},
            "context_manifest_ref": {"path": str(context), "sha256": context_sha},
            "rules_ref": {"path": str(rules), "sha256": _sha(rules)},
            "input_refs": [{"path": str(input_file), "sha256": _sha(input_file)}],
            "allowed_output_root": str(output / package_id),
            "cwd": str(source),
            "depends_on": dependencies,
            "acceptance": acceptance,
            "timeout_sec": 60,
        }

    dependency = {
        "package_id": first_package_id,
        "condition": dependency_condition,
        "result_selector": {
            "worker_terminal": "primary_artifact",
            "owner_adopted": "outcome_artifact",
            "authority_applied": "authority_artifact",
            "effect_verified": "effect_artifact",
        }[dependency_condition],
        "pin": None,
    }
    manifest = {
        "schema_version": "xinao.worker_package_batch.v3",
        "authority": False,
        "completion_claim_allowed": False,
        "parent_work_key": parent_work_key,
        "candidate_output_base": str(output),
        "graph_revision": 1,
        "predecessor_manifest_ref": None,
        "reseal_of": None,
        "affected_cone": [],
        "limits": {
            "max_parallel": 2,
            "fan_in_capacity": 1,
            "candidate_ingestion_capacity": 2,
        },
        "packages": [
            package(
                first_package_id,
                first_work_key,
                prompt_one,
                [],
                candidate_only=True,
            ),
            package(
                second_package_id,
                second_work_key,
                prompt_two,
                [dependency],
                candidate_only=second_candidate_only,
            ),
        ],
    }
    return {
        "root": tmp_path,
        "manifest": manifest,
        "quota_ref": {"path": str(quota), "sha256": quota_sha},
        "selection_ref": {"path": str(selection), "sha256": selection_sha},
        "selected_candidate": selected_candidate,
        "selection_decision_sha256": selection_receipt["decision_sha256"],
    }


def _seal_dispatch(
    fixture: dict[str, object],
    *,
    manifest: dict[str, object] | None = None,
    package_ids: list[str] | None = None,
    suffix: str = "",
    path_rewriter: Callable[[str], str] | None = None,
) -> tuple[dict[str, str], dict[str, str], dict[str, object]]:
    root = Path(fixture["root"])
    body = copy.deepcopy(manifest or fixture["manifest"])
    manifest_path = root / f"manifest{suffix}.json"
    manifest_sha = _write_json(manifest_path, body)
    manifest_path_text = str(manifest_path)
    if path_rewriter:
        manifest_path_text = path_rewriter(manifest_path_text)
    manifest_ref = {"path": manifest_path_text, "sha256": manifest_sha}
    quota_ref = copy.deepcopy(fixture["quota_ref"])
    selection_ref = copy.deepcopy(fixture["selection_ref"])
    if path_rewriter:
        quota_ref["path"] = path_rewriter(str(quota_ref["path"]))
        selection_ref["path"] = path_rewriter(str(selection_ref["path"]))
    selected = fixture["selected_candidate"]
    envelope = {
        "schema_version": "xinao.worker_dispatch_envelope.v2",
        "authority": False,
        "completion_claim_allowed": False,
        "leg": "A",
        "package_manifest_ref": manifest_ref,
        "dispatch_epoch": {
            "epoch_id": "epoch-1",
            "quota_snapshot_id": "quota-snapshot-1",
            "quota_snapshot_ref": quota_ref["path"],
            "quota_snapshot_sha256": quota_ref["sha256"],
        },
        "selection": {
            "receipt_ref": selection_ref["path"],
            "receipt_sha256": selection_ref["sha256"],
            "decision_sha256": fixture["selection_decision_sha256"],
            **{
                key: selected[key]
                for key in ("provider_id", "profile_ref", "model_id", "transport_id")
            },
        },
        "package_ids": package_ids or ["p1"],
    }
    envelope["route_choice"] = build_route_choice_identity(
        package_manifest_sha256=manifest_ref["sha256"],
        package_ids=envelope["package_ids"],
        epoch_id="epoch-1",
        leg="A",
        selection_decision_sha256=str(fixture["selection_decision_sha256"]),
        route_decision_binding_sha256=hashlib.sha256(
            canonical_json_bytes(
                {
                    "decision_sha256": fixture["selection_decision_sha256"],
                    "route_identity_sha256": hashlib.sha256(
                        canonical_json_bytes(
                            {
                                field: selected[field]
                                for field in (
                                    "provider_id",
                                    "profile_ref",
                                    "model_id",
                                    "transport_id",
                                )
                            }
                        )
                    ).hexdigest(),
                }
            )
        ).hexdigest(),
    )
    envelope_path = root / f"envelope{suffix}.json"
    envelope_sha = _write_json(envelope_path, envelope)
    envelope_path_text = str(envelope_path)
    if path_rewriter:
        envelope_path_text = path_rewriter(envelope_path_text)
    return manifest_ref, {"path": envelope_path_text, "sha256": envelope_sha}, envelope


def _route_selection_receipt(transport_id: str) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "xinao.supervisor_worker_decision_receipt.v1",
        "decision": "selected",
        "selected_candidate": {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": "grok-4.5",
            "transport_id": transport_id,
            "declared_active": True,
            "healthy": True,
            "positive_benefit": True,
        },
    }
    receipt["decision_sha256"] = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    return receipt


def _a_b_dispatch_refs(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, str], dict[str, object], dict[str, str], bytes]:
    from scripts.build_worker_package_batch import build_route_bound_dispatch_envelope

    fixture = _fixture(tmp_path / "dispatch")
    manifest_ref, a_ref, a_envelope = _seal_dispatch(fixture)
    manifest_bytes = Path(str(manifest_ref["path"])).read_bytes()
    b_receipt = _route_selection_receipt("temporal-docker-langgraph")
    b_selection_path = Path(fixture["root"]) / "source" / "selection-b.json"
    b_selection_sha = _write_json(b_selection_path, b_receipt)
    quota = json.loads(Path(str(fixture["quota_ref"]["path"])).read_text(encoding="utf-8"))
    b_envelope = build_route_bound_dispatch_envelope(
        leg="B",
        manifest_ref=manifest_ref,
        package_ids=["p1"],
        epoch_id="epoch-1",
        snapshot=quota,
        snapshot_ref=fixture["quota_ref"],
        selection=b_receipt,
        selection_ref={"path": str(b_selection_path), "sha256": b_selection_sha},
    )
    b_path = Path(fixture["root"]) / "envelope-b.json"
    b_ref = {"path": str(b_path), "sha256": _write_json(b_path, b_envelope)}
    return a_envelope, a_ref, b_envelope, b_ref, manifest_bytes


def _logical_contract(
    fixture: dict[str, object],
    *,
    package: dict[str, object],
    manifest_ref: dict[str, str],
    operation_id: str,
) -> dict[str, object]:
    route_selected = fixture["selected_candidate"]
    context = json.loads(
        Path(str(package["context_manifest_ref"]["path"])).read_text(encoding="utf-8")
    )
    acceptance = package["acceptance"]
    schema_ref = acceptance.get("json_schema_ref")
    provider_output_contract = direct_worker_pool_output_contract(
        min_result_chars=int(acceptance["min_result_chars"]),
        required_result_markers=list(acceptance["required_result_markers"]),
        require_json_object=acceptance["require_json_object"] is True,
        json_schema_sha256=(str(schema_ref["sha256"]) if schema_ref else ""),
    )
    provider_output_contract_sha256 = hashlib.sha256(
        canonical_json_bytes(provider_output_contract)
    ).hexdigest()
    capability_binding = direct_worker_pool_capability_binding(
        selection_decision_sha256=str(fixture["selection_decision_sha256"]),
        output_contract_sha256=provider_output_contract_sha256,
    )
    selected = {
        **{
            field: route_selected[field]
            for field in ("provider_id", "profile_ref", "model_id", "transport_id")
        },
        "capability_binding_sha256": hashlib.sha256(
            canonical_json_bytes(capability_binding)
        ).hexdigest(),
    }
    contract = build_direct_worker_pool_logical_contract(
        work_key=str(package["work_key"]),
        operation_id=operation_id,
        task_contract_ref=f"{manifest_ref['path']}#sha256={manifest_ref['sha256']}",
        parent_operation_id="parent-operation",
        correlation_id="correlation-1",
        provider_id=str(route_selected["provider_id"]),
        profile_ref=str(route_selected["profile_ref"]),
        model_id=str(route_selected["model_id"]),
        frozen_input_sha256=str(package["prompt_ref"]["sha256"]),
        frozen_context_sha256=str(context["context_sha256"]),
        subject_manifest_sha256=str(manifest_ref["sha256"]),
        rules_sha256=str(package["rules_sha256"]),
        output_contract_sha256=provider_output_contract_sha256,
        capability_binding=capability_binding,
        write=True,
        deadline_seconds=1800,
    )
    assert contract["selection"] == selected
    return contract


def _attempt_receipt(
    fixture: dict[str, object],
    *,
    contract: dict[str, object],
    package: dict[str, object],
    output_sha: str,
    attempt: int,
    total_tokens: int,
    accepted: bool,
) -> dict[str, object]:
    selected = contract["selection"]
    state = "accepted" if accepted else "failed"
    return {
        "schema_version": ATTEMPT_RECEIPT_VERSION,
        "contract_sha256": logical_contract_sha256(contract),
        "consumer_id": (
            GROK_DIRECT_WORKER_POOL_CONSUMER_ID
            if selected["transport_id"] == GROK_DIRECT_WORKER_POOL_TRANSPORT_ID
            else GROK_DOCKER_CONSUMER_ID
        ),
        "logical_operation_id": contract["logical_operation_id"],
        "work_key": package["work_key"],
        "attempt": attempt,
        "observed": {
            **selected,
            "rules_sha256": contract["rules_sha256"],
            "runtime_version": "0.2.101",
            "execution_location": "docker:houtai-gongren",
            "executor_id": "container-1",
        },
        "terminal_state": "completed" if accepted else "failed",
        "stop_reason": "EndTurn" if accepted else "provider_failed",
        "output": {
            "format": (
                "json_object" if package["acceptance"]["require_json_object"] is True else "text"
            ),
            "content_sha256": output_sha,
            "chars": 120 if accepted else 0,
            "schema_sha256": contract["output_contract_sha256"],
            "schema_valid": accepted,
            "markers_ok": accepted,
            "substantive": accepted,
        },
        "invocations": [
            {
                "invocation": 1,
                "state": state,
                "observed_model": selected["model_id"],
                "stop_reason": "EndTurn" if accepted else "provider_failed",
                "output_sha256": output_sha,
                "output_chars": 120 if accepted else 0,
                "total_tokens": total_tokens,
            }
        ],
        "usage": {
            "invocation_count": 1,
            "total_tokens": total_tokens,
            "accepted_tokens": total_tokens if accepted else 0,
            "cancelled_tokens": 0,
            "failed_tokens": 0 if accepted else total_tokens,
        },
        "lineage": {
            "workflow_id": "workflow-1",
            "lane_id": "lane-1",
            "parent_operation_id": "parent-operation",
            "correlation_id": "correlation-1",
            "session_id": "session-1",
        },
        "provider_contract_version": "xinao.grok.shared_execution_contract.v1",
        "provider_evidence_ref": "D:/evidence/native-provider.json",
        "provider_evidence_sha256": "f" * 64,
        "provider_evidence_valid": True,
        "replayed": False,
    }


def _worker_event(
    fixture: dict[str, object],
    *,
    package_id: str,
    manifest_ref: dict[str, str],
    envelope_ref: dict[str, str],
    attempt_number: int = 1,
    total_tokens: int = 100,
    accepted: bool = True,
    suffix: str = "",
    borrow_contract_as_output: bool = False,
) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
    root = Path(fixture["root"])
    manifest = fixture["manifest"]
    package = next(row for row in manifest["packages"] if row["package_id"] == package_id)
    operation_id = f"op-{package_id}"
    contract = _logical_contract(
        fixture,
        package=package,
        manifest_ref=manifest_ref,
        operation_id=operation_id,
    )
    contract_path = root / f"contract-{package_id}{suffix}.json"
    contract_sha = _write_json(contract_path, contract)
    output_path = root / f"output-{package_id}{suffix}.json"
    output_sha = _write_json(output_path, {"result": "OK", "attempt": attempt_number})
    artifact_ref = {"path": str(output_path), "sha256": output_sha}
    if borrow_contract_as_output:
        output_sha = contract_sha
        artifact_ref = {"path": str(contract_path), "sha256": contract_sha}
    receipt = _attempt_receipt(
        fixture,
        contract=contract,
        package=package,
        output_sha=output_sha,
        attempt=attempt_number,
        total_tokens=total_tokens,
        accepted=accepted,
    )
    attempt_path = root / f"attempt-{package_id}{suffix}.json"
    attempt_sha = _write_json(attempt_path, receipt)
    event = build_dispatch_outcome_event(
        event_type="worker_terminal",
        parent_work_key=str(package["parent_work_key"]),
        work_key=str(package["work_key"]),
        package_id=package_id,
        package_manifest_ref=manifest_ref,
        dispatch_envelope_ref=envelope_ref,
        logical_operation_id=operation_id,
        leg="A",
        role=str(package["role"]),
        artifact_refs=[artifact_ref],
        common_attempt_ref={"path": str(attempt_path), "sha256": attempt_sha},
        common_contract_ref={"path": str(contract_path), "sha256": contract_sha},
    )
    event_path = root / f"worker-event-{package_id}{suffix}.json"
    event_ref = {"path": str(event_path), "sha256": _write_json(event_path, event)}
    return event, event_ref, artifact_ref


def _owner_event(
    fixture: dict[str, object],
    *,
    provider_ref: dict[str, str],
    artifact_ref: dict[str, str],
    suffix: str = "",
) -> tuple[dict[str, object], dict[str, str]]:
    root = Path(fixture["root"])
    event = build_dispatch_outcome_event(
        event_type="owner_verdict",
        role="codex_owner",
        artifact_refs=[artifact_ref],
        provider_event_ref=provider_ref,
        owner_verdict="adopted",
        owner_effort={"redo_tokens": 0},
    )
    path = root / f"owner-event{suffix}.json"
    return event, {"path": str(path), "sha256": _write_json(path, event)}


def _owner_adoption_event(
    fixture: dict[str, object],
    *,
    owner_verdict_ref: dict[str, str],
    artifact_ref: dict[str, str],
    suffix: str = "",
) -> tuple[dict[str, object], dict[str, str]]:
    root = Path(fixture["root"])
    event = build_dispatch_outcome_event(
        event_type="owner_adopted",
        role="codex_owner",
        artifact_refs=[artifact_ref],
        owner_verdict_event_ref=owner_verdict_ref,
    )
    path = root / f"owner-adopted-event{suffix}.json"
    return event, {"path": str(path), "sha256": _write_json(path, event)}


def _authority_event(
    fixture: dict[str, object],
    *,
    owner_adopted_ref: dict[str, str],
    artifact_ref: dict[str, str],
    work_key: str = "wk-1",
    suffix: str = "",
) -> tuple[dict[str, object], dict[str, str]]:
    root = Path(fixture["root"])
    readback = root / f"authority-readback{suffix}.json"
    readback_sha = _write_json(
        readback,
        {
            "schema_version": "xinao.authority_apply_readback.v1",
            "authority": False,
            "completion_claim_allowed": False,
            "work_key": work_key,
            "applied": True,
            "subject": "refs/heads/main",
            "observed_value": artifact_ref["sha256"],
            "applied_artifact_refs": [artifact_ref],
        },
    )
    event = build_dispatch_outcome_event(
        event_type="authority_applied",
        role="codex_owner",
        artifact_refs=[artifact_ref],
        owner_adopted_event_ref=owner_adopted_ref,
        authority_readback_ref={"path": str(readback), "sha256": readback_sha},
    )
    path = root / f"authority-applied-event{suffix}.json"
    return event, {"path": str(path), "sha256": _write_json(path, event)}


def _effect_event(
    fixture: dict[str, object],
    *,
    authority_ref: dict[str, str],
    artifact_ref: dict[str, str],
    work_key: str = "wk-1",
    suffix: str = "",
) -> tuple[dict[str, object], dict[str, str]]:
    root = Path(fixture["root"])
    readback = root / f"readback{suffix}.json"
    readback_sha = _write_json(
        readback,
        {
            "schema_version": "xinao.work_unit_finalizer_evidence.v1",
            "authority": False,
            "completion_claim_allowed": False,
            "kind": "runtime_consumer",
            "work_key": work_key,
            "readback_verified": True,
            "subject": artifact_ref["path"],
            "observed_value": artifact_ref["sha256"],
        },
    )
    event = build_dispatch_outcome_event(
        event_type="effect_verified",
        role="runtime_consumer",
        artifact_refs=[artifact_ref],
        authority_applied_event_ref=authority_ref,
        consumer_readback_ref={"path": str(readback), "sha256": readback_sha},
    )
    path = root / f"effect-event{suffix}.json"
    return event, {"path": str(path), "sha256": _write_json(path, event)}


def _task_event(
    *,
    phase: str,
    target: str,
    evidence_ref: dict[str, str],
    ordinal: int,
    side_effect_id: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "codex.verified-task-run.v1",
        "run_id": "run-1",
        "event_id": f"event-{ordinal}",
        "timestamp": f"2026-07-21T00:00:{ordinal:02d}Z",
        "actor": "codex-owner",
        "kind": "result",
        "phase": phase,
        "summary": phase,
        "target": target,
        "evidence_refs": [f"{evidence_ref['path']}#sha256={evidence_ref['sha256']}"],
        "exit_code": 0,
        "retry_class": "none",
        "side_effect_id": side_effect_id or f"side-effect-{ordinal}",
    }


def _write_run(run: Path, events: list[dict[str, object]]) -> None:
    run.mkdir(parents=True, exist_ok=True)
    _write_json(run / "task.json", {"run_id": "run-1"})
    _write_json(run / "state.json", {"run_id": "run-1", "events_count": len(events)})
    (run / "events.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in events),
        encoding="utf-8",
    )


def test_typed_owner_dependency_cannot_be_released_by_provider_terminal(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    validated = validate_package_batch_manifest(fixture["manifest"])
    assert validated["graph_revision"] == 1
    assert validated["packages"][1]["depends_on"][0]["condition"] == "owner_adopted"

    first = plan_package_frontier(validated)
    assert [row["package_id"] for row in first["admitted"]] == ["p1"]

    _, provider_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
    )
    provider_only = plan_package_frontier(validated, outcome_event_refs=[provider_ref])
    assert provider_only["admitted"] == []
    assert provider_only["conditionally_ready_package_ids"] == ["p2"]

    _, owner_ref = _owner_event(
        fixture,
        provider_ref=provider_ref,
        artifact_ref=artifact_ref,
    )
    assert (
        plan_package_frontier(validated, outcome_event_refs=[provider_ref, owner_ref])["admitted"]
        == []
    )
    _, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
    )
    owner_ready = plan_package_frontier(
        validated, outcome_event_refs=[provider_ref, owner_ref, adopted_ref]
    )
    assert [row["package_id"] for row in owner_ready["admitted"]] == ["p2"]
    dependency = owner_ready["admitted"][0]["depends_on"][0]
    assert dependency["pin"]["event_ref"] == adopted_ref
    assert dependency["pin"]["artifact_ref"] == artifact_ref
    assert owner_ready["admitted"][0]["execution_seal_ready"] is True


def test_legacy_string_dependency_means_owner_adopted_not_worker_terminal(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["manifest"]["packages"][1]["depends_on"] = ["p1"]
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    validated = validate_package_batch_manifest(fixture["manifest"])
    dependency = validated["packages"][1]["depends_on"][0]
    assert dependency["condition"] == "owner_adopted"
    _, provider_ref, _ = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
    )
    assert plan_package_frontier(validated, outcome_event_refs=[provider_ref])["admitted"] == []


def test_caller_declared_adoption_cannot_replace_typed_owner_event(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(DispatchEconomicsError, match="typed owner_adopted events"):
        plan_package_frontier(
            fixture["manifest"],
            terminal_package_ids=["p1"],
            adopted_package_ids=["p1"],
        )


@pytest.mark.parametrize("condition", ["worker_terminal", "authority_applied", "effect_verified"])
def test_each_dependency_condition_requires_its_exact_typed_fact(
    tmp_path: Path, condition: str
) -> None:
    fixture = _fixture(tmp_path, dependency_condition=condition)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    _, provider_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
    )
    _, owner_ref = _owner_event(
        fixture,
        provider_ref=provider_ref,
        artifact_ref=artifact_ref,
    )
    _, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
    )
    refs = [provider_ref]
    if condition in {"authority_applied", "effect_verified"}:
        assert plan_package_frontier(fixture["manifest"], outcome_event_refs=refs)["admitted"] == []
        _, authority_ref = _authority_event(
            fixture,
            owner_adopted_ref=adopted_ref,
            artifact_ref=artifact_ref,
        )
        refs.extend([owner_ref, adopted_ref, authority_ref])
    if condition == "effect_verified":
        assert plan_package_frontier(fixture["manifest"], outcome_event_refs=refs)["admitted"] == []
        _, effect_ref = _effect_event(
            fixture,
            authority_ref=authority_ref,
            artifact_ref=artifact_ref,
        )
        refs.append(effect_ref)
    result = plan_package_frontier(fixture["manifest"], outcome_event_refs=refs)
    assert [row["package_id"] for row in result["admitted"]] == ["p2"]


def test_rejected_worker_terminal_cannot_release_primary_result_dependency(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, dependency_condition="worker_terminal")
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    _, rejected_ref, _ = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
        accepted=False,
    )
    result = plan_package_frontier(fixture["manifest"], outcome_event_refs=[rejected_ref])
    assert result["admitted"] == []
    assert result["conditionally_ready_package_ids"] == ["p2"]


def test_owner_authority_effect_states_cannot_be_skipped_or_faked(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    _, provider_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
    )
    _, owner_ref = _owner_event(
        fixture,
        provider_ref=provider_ref,
        artifact_ref=artifact_ref,
    )
    _, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
    )

    discarded = build_dispatch_outcome_event(
        event_type="owner_verdict",
        role="codex_owner",
        artifact_refs=[artifact_ref],
        provider_event_ref=provider_ref,
        owner_verdict="discarded",
        owner_effort={"redo_tokens": 0},
    )
    discarded_path = tmp_path / "discarded-verdict.json"
    discarded_ref = {
        "path": str(discarded_path),
        "sha256": _write_json(discarded_path, discarded),
    }
    with pytest.raises(DispatchEconomicsError, match="non-discarded owner verdict"):
        build_dispatch_outcome_event(
            event_type="owner_adopted",
            role="codex_owner",
            artifact_refs=[artifact_ref],
            owner_verdict_event_ref=discarded_ref,
        )

    with pytest.raises(DispatchEconomicsError, match="explicit owner adoption"):
        build_dispatch_outcome_event(
            event_type="authority_applied",
            role="codex_owner",
            artifact_refs=[artifact_ref],
            owner_adopted_event_ref=owner_ref,
            authority_readback_ref=artifact_ref,
        )

    with pytest.raises(DispatchEconomicsError, match="explicit authority application"):
        build_dispatch_outcome_event(
            event_type="effect_verified",
            role="runtime_consumer",
            artifact_refs=[artifact_ref],
            authority_applied_event_ref=adopted_ref,
            consumer_readback_ref=artifact_ref,
        )


def test_dependency_pin_requires_exact_state_event_and_artifact(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, dependency_condition="authority_applied")
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    _, provider_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
    )
    _, owner_ref = _owner_event(
        fixture,
        provider_ref=provider_ref,
        artifact_ref=artifact_ref,
    )
    _, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
    )
    _, authority_ref = _authority_event(
        fixture,
        owner_adopted_ref=adopted_ref,
        artifact_ref=artifact_ref,
    )

    wrong_state = copy.deepcopy(fixture["manifest"])
    wrong_state["packages"][1]["depends_on"][0]["pin"] = {
        "event_ref": adopted_ref,
        "artifact_ref": artifact_ref,
    }
    with pytest.raises(DispatchEconomicsError, match="typed condition"):
        validate_package_batch_manifest(wrong_state)

    other = tmp_path / "other-artifact.json"
    other_ref = {"path": str(other), "sha256": _write_json(other, {"result": "other"})}
    wrong_artifact = copy.deepcopy(fixture["manifest"])
    wrong_artifact["packages"][1]["depends_on"][0]["pin"] = {
        "event_ref": authority_ref,
        "artifact_ref": other_ref,
    }
    with pytest.raises(DispatchEconomicsError, match="selected result"):
        validate_package_batch_manifest(wrong_artifact)

    wrong_event_hash = copy.deepcopy(fixture["manifest"])
    wrong_event_hash["packages"][1]["depends_on"][0]["pin"] = {
        "event_ref": {**authority_ref, "sha256": "0" * 64},
        "artifact_ref": artifact_ref,
    }
    with pytest.raises(DispatchEconomicsError, match="sha256 mismatch"):
        validate_package_batch_manifest(wrong_event_hash)


def test_candidate_ingestion_and_owner_authority_fan_in_are_separate(tmp_path: Path) -> None:
    candidate = _fixture(tmp_path / "candidate", second_candidate_only=True)
    owner = _fixture(tmp_path / "owner", second_candidate_only=False)
    for fixture, expected in ((candidate, ["p1"]), (owner, ["p1"])):
        # p1 is candidate-only and remains dispatchable even when owner authority is saturated.
        result = plan_package_frontier(
            fixture["manifest"],
            pending_owner_authority_count=1,
            pending_candidate_ingestion_count=0,
        )
        assert [row["package_id"] for row in result["admitted"]] == expected
        assert result["owner_fan_in_free_slots"] == 0
        assert result["candidate_ingestion_free_slots"] == 1

    no_dependency = copy.deepcopy(owner["manifest"])
    no_dependency["packages"][1]["depends_on"] = []
    result = plan_package_frontier(
        no_dependency,
        pending_owner_authority_count=1,
        pending_candidate_ingestion_count=0,
    )
    assert [row["package_id"] for row in result["admitted"]] == ["p1"]
    assert result["pending_owner_ready_package_ids"] == ["p2"]

    _, _, owner_envelope = _seal_dispatch(
        owner,
        manifest=no_dependency,
        package_ids=["p2"],
        suffix="-owner",
    )
    with pytest.raises(DispatchEconomicsError, match="owner-authority packages"):
        validate_dispatch_envelope(owner_envelope)

    _, _, unpinned_envelope = _seal_dispatch(
        candidate,
        package_ids=["p2"],
        suffix="-unpinned",
    )
    with pytest.raises(DispatchEconomicsError, match="without executable result pins"):
        validate_dispatch_envelope(unpinned_envelope)


def test_same_work_key_reseal_binds_predecessor_and_exact_affected_cone(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture, suffix="-r1")
    revision_one = validate_package_batch_manifest(fixture["manifest"])
    _, provider_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
    )
    _, owner_ref = _owner_event(
        fixture,
        provider_ref=provider_ref,
        artifact_ref=artifact_ref,
    )
    _, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
    )
    revision_two = copy.deepcopy(fixture["manifest"])
    revision_two.update(
        graph_revision=2,
        predecessor_manifest_ref=manifest_ref,
        reseal_of={
            "package_id": "p2",
            "package_identity_sha256": revision_one["packages"][1]["package_identity_sha256"],
            "graph_revision": 1,
        },
        affected_cone=["p2"],
    )
    revision_two["packages"][1]["depends_on"][0]["pin"] = {
        "event_ref": adopted_ref,
        "artifact_ref": artifact_ref,
    }
    validated = validate_package_batch_manifest(revision_two)
    assert validated["packages"][1]["work_key"] == "wk-2"
    assert (
        validated["packages"][1]["package_seal_sha256"]
        != revision_one["packages"][1]["package_seal_sha256"]
    )
    assert validated["packages"][1]["execution_seal_ready"] is True
    assert (
        validated["packages"][0]["package_seal_sha256"]
        == revision_one["packages"][0]["package_seal_sha256"]
    )
    frontier = plan_package_frontier(validated)
    assert [row["package_id"] for row in frontier["admitted"]] == ["p2"]

    empty_reseal = copy.deepcopy(revision_two)
    empty_reseal["packages"][1]["depends_on"][0]["pin"] = None
    with pytest.raises(DispatchEconomicsError, match="did not change a result pin"):
        validate_package_batch_manifest(empty_reseal)

    wrong_cone = copy.deepcopy(revision_two)
    wrong_cone["affected_cone"] = ["p1", "p2"]
    with pytest.raises(DispatchEconomicsError, match="affected_cone"):
        validate_package_batch_manifest(wrong_cone)

    new_work = copy.deepcopy(revision_two)
    new_work["packages"][1]["work_key"] = "wk-new"
    with pytest.raises(DispatchEconomicsError, match="work_key|identity"):
        validate_package_batch_manifest(new_work)


def test_neutral_manifest_bytes_are_shared_across_host_and_docker_path_resolvers(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "physical")
    physical_root = str(Path(fixture["root"]))
    logical_root = "D:/XINAO_RESEARCH_RUNTIME/evidence/shared"

    def to_logical(value: str) -> str:
        return value.replace(physical_root, logical_root).replace("\\", "/")

    logical_manifest = copy.deepcopy(fixture["manifest"])
    for package in logical_manifest["packages"]:
        package["prompt_ref"]["path"] = to_logical(package["prompt_ref"]["path"])
        package["context_manifest_ref"]["path"] = to_logical(
            package["context_manifest_ref"]["path"]
        )
        package["input_refs"][0]["path"] = to_logical(package["input_refs"][0]["path"])
        package["allowed_output_root"] = to_logical(package["allowed_output_root"])
        package["cwd"] = to_logical(package["cwd"])
    fixture["manifest"] = logical_manifest
    manifest_ref, _, envelope = _seal_dispatch(
        fixture,
        manifest=logical_manifest,
        path_rewriter=to_logical,
    )
    raw_bytes = (Path(fixture["root"]) / "manifest.json").read_bytes()

    def host_resolver(logical: str) -> Path:
        return Path(logical.replace(logical_root, physical_root))

    def docker_resolver(logical: str) -> Path:
        # The physical temp root stands in for Docker's /evidence mount.
        return Path(logical.replace(logical_root, physical_root))

    host = validate_dispatch_envelope(envelope, path_resolver=host_resolver)
    docker_envelope = copy.deepcopy(envelope)
    docker_envelope["leg"] = "B"
    docker_candidate = {
        **fixture["selected_candidate"],
        "transport_id": "temporal-docker-langgraph",
    }
    docker_receipt: dict[str, object] = {
        "schema_version": "xinao.supervisor_worker_decision_receipt.v1",
        "decision": "selected",
        "selected_candidate": docker_candidate,
    }
    docker_receipt["decision_sha256"] = hashlib.sha256(
        canonical_json_bytes(docker_receipt)
    ).hexdigest()
    docker_selection_path = Path(fixture["root"]) / "selection-b.json"
    docker_selection_sha = _write_json(docker_selection_path, docker_receipt)
    docker_envelope["selection"] = {
        "receipt_ref": to_logical(str(docker_selection_path)),
        "receipt_sha256": docker_selection_sha,
        "decision_sha256": docker_receipt["decision_sha256"],
        **{
            key: docker_candidate[key]
            for key in ("provider_id", "profile_ref", "model_id", "transport_id")
        },
    }
    docker_envelope["execution_adapter"] = build_grok_docker_route_adapter_binding(docker_receipt)
    docker_route = docker_envelope["execution_adapter"]
    docker_envelope["route_choice"] = build_route_choice_identity(
        package_manifest_sha256=manifest_ref["sha256"],
        package_ids=docker_envelope["package_ids"],
        epoch_id="epoch-1",
        leg="B",
        selection_decision_sha256=str(docker_receipt["decision_sha256"]),
        route_decision_binding_sha256=str(docker_route["route_decision_binding_sha256"]),
    )
    docker = validate_dispatch_envelope(docker_envelope, path_resolver=docker_resolver)
    assert (
        host["validated_package_manifest"]["validated_manifest_sha256"]
        == docker["validated_package_manifest"]["validated_manifest_sha256"]
    )
    assert host["validated_package_manifest"]["packages"][0]["prompt_ref"]["path"].startswith(
        logical_root
    )
    assert (Path(fixture["root"]) / "manifest.json").read_bytes() == raw_bytes
    assert manifest_ref["path"].startswith(logical_root)


def test_manifest_rejects_identity_and_hash_drift_before_execution(tmp_path: Path) -> None:
    duplicate = _fixture(tmp_path / "duplicate")["manifest"]
    duplicate["packages"][1]["package_id"] = "p1"
    with pytest.raises(DispatchEconomicsError, match="duplicate package_id"):
        validate_package_batch_manifest(duplicate)

    drift = _fixture(tmp_path / "drift")["manifest"]
    prompt = Path(drift["packages"][0]["prompt_ref"]["path"])
    prompt.write_text("changed after seal\n", encoding="utf-8")
    with pytest.raises(DispatchEconomicsError, match="prompt_ref sha256 mismatch"):
        validate_package_batch_manifest(drift)

    missing_rules = _fixture(tmp_path / "missing-rules")["manifest"]
    missing_rules["packages"][0].pop("rules_ref")
    with pytest.raises(DispatchEconomicsError, match="rules_ref"):
        validate_package_batch_manifest(missing_rules)

    rules_drift = _fixture(tmp_path / "rules-drift")["manifest"]
    rules_drift["packages"][0]["rules_ref"]["sha256"] = "0" * 64
    with pytest.raises(DispatchEconomicsError, match="rules_ref sha256 mismatch"):
        validate_package_batch_manifest(rules_drift)

    acceptance_drift = _fixture(tmp_path / "acceptance-drift")["manifest"]
    acceptance_drift["packages"][0]["acceptance"]["min_result_chars"] = 2
    with pytest.raises(
        DispatchEconomicsError,
        match="output_contract_sha256 does not bind acceptance",
    ):
        validate_package_batch_manifest(acceptance_drift)


def test_json_package_requires_hash_bound_schema_before_provider(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)["manifest"]
    acceptance = manifest["packages"][0]["acceptance"]
    acceptance["require_json_object"] = True
    with pytest.raises(DispatchEconomicsError, match="json_schema_ref"):
        validate_package_batch_manifest(manifest)

    schema = tmp_path / "result.schema.json"
    schema_sha = _write_json(
        schema,
        {"type": "object", "required": ["marker"], "properties": {"marker": {"type": "string"}}},
    )
    acceptance["json_schema_ref"] = {"path": str(schema), "sha256": schema_sha}
    package = manifest["packages"][0]
    package.update(
        build_worker_package_identity(
            package_id=str(package["package_id"]),
            work_key=str(package["work_key"]),
            parent_work_key=str(package["parent_work_key"]),
            work_class=str(package["work_class"]),
            role=str(package["role"]),
            phase=str(package["phase"]),
            input_sha256=str(package["input_sha256"]),
            context_sha256=str(package["context_sha256"]),
            rules_sha256=str(package["rules_sha256"]),
            output_contract_sha256=neutral_output_contract_sha256(acceptance),
            write_domains=list(package["write_domains"]),
            candidate_only=package["candidate_only"] is True,
        )
    )
    assert (
        validate_package_batch_manifest(manifest)["packages"][0]["acceptance"]["json_schema_ref"][
            "sha256"
        ]
        == schema_sha
    )


def test_worker_terminal_a_maps_neutral_context_and_acceptance_to_direct_contract(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    package = fixture["manifest"]["packages"][0]
    schema_path = tmp_path / "direct-result.schema.json"
    schema_sha256 = _write_json(
        schema_path,
        {
            "type": "object",
            "required": ["result"],
            "properties": {"result": {"type": "string"}},
        },
    )
    package["acceptance"] = {
        **package["acceptance"],
        "require_json_object": True,
        "json_schema_ref": {"path": str(schema_path), "sha256": schema_sha256},
    }
    package.update(
        build_worker_package_identity(
            package_id=str(package["package_id"]),
            work_key=str(package["work_key"]),
            parent_work_key=str(package["parent_work_key"]),
            work_class=str(package["work_class"]),
            role=str(package["role"]),
            phase=str(package["phase"]),
            input_sha256=str(package["input_sha256"]),
            context_sha256=str(package["context_sha256"]),
            rules_sha256=str(package["rules_sha256"]),
            output_contract_sha256=neutral_output_contract_sha256(package["acceptance"]),
            write_domains=list(package["write_domains"]),
            candidate_only=True,
        )
    )
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    context = json.loads(Path(package["context_manifest_ref"]["path"]).read_text(encoding="utf-8"))
    provider_output_contract = direct_worker_pool_output_contract(
        min_result_chars=package["acceptance"]["min_result_chars"],
        required_result_markers=package["acceptance"]["required_result_markers"],
        require_json_object=package["acceptance"]["require_json_object"],
        json_schema_sha256=schema_sha256,
    )
    provider_output_sha256 = hashlib.sha256(
        canonical_json_bytes(provider_output_contract)
    ).hexdigest()
    capability = direct_worker_pool_capability_binding(
        selection_decision_sha256=str(fixture["selection_decision_sha256"]),
        output_contract_sha256=provider_output_sha256,
    )
    operation_id = "op-p1-direct-provider-map"
    contract = build_direct_worker_pool_logical_contract(
        work_key=str(package["work_key"]),
        operation_id=operation_id,
        task_contract_ref=f"{manifest_ref['path']}#sha256={manifest_ref['sha256']}",
        parent_operation_id="parent-operation",
        correlation_id="correlation-1",
        provider_id=str(fixture["selected_candidate"]["provider_id"]),
        profile_ref=str(fixture["selected_candidate"]["profile_ref"]),
        model_id=str(fixture["selected_candidate"]["model_id"]),
        frozen_input_sha256=str(package["prompt_ref"]["sha256"]),
        frozen_context_sha256=str(context["context_sha256"]),
        subject_manifest_sha256=str(manifest_ref["sha256"]),
        rules_sha256=str(package["rules_sha256"]),
        output_contract_sha256=provider_output_sha256,
        capability_binding=capability,
        write=True,
        deadline_seconds=60,
    )
    contract_path = tmp_path / "direct-contract.json"
    contract_ref = {"path": str(contract_path), "sha256": _write_json(contract_path, contract)}
    output_path = tmp_path / "direct-output.json"
    output_sha = _write_json(output_path, {"result": "OK"})
    attempt = _attempt_receipt(
        fixture,
        contract=contract,
        package=package,
        output_sha=output_sha,
        attempt=1,
        total_tokens=10,
        accepted=True,
    )
    attempt["output"]["schema_sha256"] = provider_output_sha256
    attempt_path = tmp_path / "direct-attempt.json"
    attempt_ref = {"path": str(attempt_path), "sha256": _write_json(attempt_path, attempt)}

    event = build_dispatch_outcome_event(
        event_type="worker_terminal",
        parent_work_key=str(package["parent_work_key"]),
        work_key=str(package["work_key"]),
        package_id=str(package["package_id"]),
        package_manifest_ref=manifest_ref,
        dispatch_envelope_ref=envelope_ref,
        logical_operation_id=operation_id,
        leg="A",
        role=str(package["role"]),
        artifact_refs=[{"path": str(output_path), "sha256": output_sha}],
        common_attempt_ref=attempt_ref,
        common_contract_ref=contract_ref,
    )
    assert event["provider_accepted"] is True
    assert (
        event["provider_selection"]["capability_binding_sha256"]
        == contract["selection"]["capability_binding_sha256"]
    )


def test_provider_owner_effect_require_real_common_evidence_and_finalizer(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    worker, worker_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
        total_tokens=100,
    )
    owner, owner_ref = _owner_event(
        fixture,
        provider_ref=worker_ref,
        artifact_ref=artifact_ref,
    )
    adopted, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
    )
    authority, authority_ref = _authority_event(
        fixture,
        owner_adopted_ref=adopted_ref,
        artifact_ref=artifact_ref,
    )
    effect, effect_ref = _effect_event(
        fixture,
        authority_ref=authority_ref,
        artifact_ref=artifact_ref,
    )
    run = tmp_path / "run"
    provider_task = _task_event(
        phase="worker_terminal", target="wk-1", evidence_ref=worker_ref, ordinal=1
    )
    _write_run(run, [provider_task])
    provider_only = project_dispatch_outcomes(run)
    assert provider_only["summary"]["provider_accepted"] == 1
    assert provider_only["summary"]["owner_adopted"] == 0
    assert provider_only["outcome_chain_closed"] is False

    owner_task = _task_event(
        phase="owner_verdict", target="wk-1", evidence_ref=owner_ref, ordinal=2
    )
    _write_run(run, [provider_task, owner_task])
    owner_only = project_dispatch_outcomes(run)
    # A verdict is a decision fact, not an adoption fact.
    assert owner_only["summary"]["owner_adopted"] == 0
    assert owner_only["summary"]["effect_verified"] == 0
    assert owner_only["outcome_chain_closed"] is False

    adopted_task = _task_event(
        phase="owner_adopted", target="wk-1", evidence_ref=adopted_ref, ordinal=3
    )
    _write_run(run, [provider_task, owner_task, adopted_task])
    adopted_only = project_dispatch_outcomes(run)
    assert adopted_only["summary"]["owner_adopted"] == 1
    assert adopted_only["summary"]["authority_applied"] == 0
    assert adopted_only["outcome_chain_closed"] is False

    authority_task = _task_event(
        phase="authority_applied", target="wk-1", evidence_ref=authority_ref, ordinal=4
    )
    _write_run(run, [provider_task, owner_task, adopted_task, authority_task])
    authority_only = project_dispatch_outcomes(run)
    assert authority_only["summary"]["authority_applied"] == 1
    assert authority_only["summary"]["effect_verified"] == 0
    assert authority_only["outcome_chain_closed"] is False

    effect_task = _task_event(
        phase="effect_verified", target="wk-1", evidence_ref=effect_ref, ordinal=5
    )
    _write_run(run, [provider_task, owner_task, adopted_task, authority_task, effect_task])
    complete = project_dispatch_outcomes(run)
    assert worker["attempt_number"] == 1
    assert worker["graph_revision"] == 1
    assert worker["package_seal_sha256"]
    assert owner["owner_verdict"] == "adopted"
    assert adopted["owner_adopted"] is True
    assert authority["authority_applied"] is True
    assert effect["effect_verified"] is True
    assert complete["summary"]["authority_applied"] == 1
    assert complete["summary"]["effect_verified"] == 1
    assert complete["metrics"]["cost_per_verified_work_unit"] == 100
    assert complete["work_keys"][0]["parent_work_key"] == "parent-work"
    assert complete["work_keys"][0]["package_id"] == "p1"
    assert complete["metrics"]["accepted_artifact_ratio"] == 1.0
    assert complete["outcome_chain_closed"] is True
    assert "parent_complete" not in complete


def test_fake_accepted_receipt_and_control_evidence_as_output_are_rejected(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    package = fixture["manifest"]["packages"][0]
    fake = tmp_path / "fake-attempt.json"
    fake_sha = _write_json(
        fake,
        {
            "schema_version": ATTEMPT_RECEIPT_VERSION,
            "work_key": "wk-1",
            "accepted": True,
        },
    )
    contract = _logical_contract(
        fixture,
        package=package,
        manifest_ref=manifest_ref,
        operation_id="op-p1",
    )
    contract_path = tmp_path / "fake-contract.json"
    contract_sha = _write_json(contract_path, contract)
    artifact = tmp_path / "fake-output.json"
    artifact_sha = _write_json(artifact, {"result": "OK"})
    with pytest.raises(DispatchEconomicsError, match="common attempt contract validation failed"):
        build_dispatch_outcome_event(
            event_type="worker_terminal",
            parent_work_key="parent-work",
            work_key="wk-1",
            package_id="p1",
            package_manifest_ref=manifest_ref,
            dispatch_envelope_ref=envelope_ref,
            logical_operation_id="op-p1",
            leg="A",
            role="role-p1",
            artifact_refs=[{"path": str(artifact), "sha256": artifact_sha}],
            common_attempt_ref={"path": str(fake), "sha256": fake_sha},
            common_contract_ref={"path": str(contract_path), "sha256": contract_sha},
        )

    with pytest.raises(DispatchEconomicsError, match="control evidence.*output artifact"):
        _worker_event(
            fixture,
            package_id="p1",
            manifest_ref=manifest_ref,
            envelope_ref=envelope_ref,
            borrow_contract_as_output=True,
        )


def test_effect_cannot_borrow_another_package_identity(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    _, worker_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
    )
    _, owner_ref = _owner_event(
        fixture,
        provider_ref=worker_ref,
        artifact_ref=artifact_ref,
    )
    _, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
    )
    _, authority_ref = _authority_event(
        fixture,
        owner_adopted_ref=adopted_ref,
        artifact_ref=artifact_ref,
    )
    with pytest.raises(
        DispatchEconomicsError, match="consumer readback is not typed runtime evidence"
    ):
        _effect_event(
            fixture,
            authority_ref=authority_ref,
            artifact_ref=artifact_ref,
            work_key="wk-2",
        )


def test_projection_rejects_duplicate_side_effect_and_out_of_order_chain(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    _, worker_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
    )
    _, owner_ref = _owner_event(
        fixture,
        provider_ref=worker_ref,
        artifact_ref=artifact_ref,
    )
    _, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
    )
    _, authority_ref = _authority_event(
        fixture,
        owner_adopted_ref=adopted_ref,
        artifact_ref=artifact_ref,
    )
    worker_task = _task_event(
        phase="worker_terminal",
        target="wk-1",
        evidence_ref=worker_ref,
        ordinal=1,
        side_effect_id="duplicate-effect",
    )
    owner_task = _task_event(
        phase="owner_verdict",
        target="wk-1",
        evidence_ref=owner_ref,
        ordinal=2,
        side_effect_id="duplicate-effect",
    )
    duplicate_run = tmp_path / "duplicate-run"
    _write_run(duplicate_run, [worker_task, owner_task])
    with pytest.raises(DispatchEconomicsError, match="duplicate typed task-run side_effect_id"):
        project_dispatch_outcomes(duplicate_run)

    ordered_worker = {**worker_task, "side_effect_id": "worker-effect"}
    ordered_owner = {**owner_task, "side_effect_id": "owner-effect"}
    out_of_order_run = tmp_path / "out-of-order-run"
    _write_run(out_of_order_run, [ordered_owner, ordered_worker])
    with pytest.raises(DispatchEconomicsError, match="predecessor is absent or out of order"):
        project_dispatch_outcomes(out_of_order_run)

    _, effect_ref = _effect_event(
        fixture,
        authority_ref=authority_ref,
        artifact_ref=artifact_ref,
        suffix="-terminal",
    )
    _, post_effect_ref, _ = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
        attempt_number=2,
        accepted=False,
        suffix="-post-effect",
    )
    terminal_run = tmp_path / "terminal-run"
    _write_run(
        terminal_run,
        [
            {**ordered_worker, "event_id": "terminal-1"},
            {**ordered_owner, "event_id": "terminal-2"},
            _task_event(
                phase="owner_adopted",
                target="wk-1",
                evidence_ref=adopted_ref,
                ordinal=3,
            ),
            _task_event(
                phase="authority_applied",
                target="wk-1",
                evidence_ref=authority_ref,
                ordinal=4,
            ),
            _task_event(
                phase="effect_verified",
                target="wk-1",
                evidence_ref=effect_ref,
                ordinal=5,
            ),
            _task_event(
                phase="worker_terminal",
                target="wk-1",
                evidence_ref=post_effect_ref,
                ordinal=6,
            ),
        ],
    )
    with pytest.raises(DispatchEconomicsError, match="after effect verification"):
        project_dispatch_outcomes(terminal_run)


def test_projection_rejects_duplicate_adoption_and_authority_before_adoption(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    _, worker_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
    )
    _, owner_ref = _owner_event(
        fixture,
        provider_ref=worker_ref,
        artifact_ref=artifact_ref,
    )
    _, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
        suffix="-one",
    )
    duplicate_adoption = build_dispatch_outcome_event(
        event_type="owner_adopted",
        role="codex_owner_recheck",
        artifact_refs=[artifact_ref],
        owner_verdict_event_ref=owner_ref,
    )
    duplicate_path = tmp_path / "owner-adopted-event-two.json"
    duplicate_ref = {
        "path": str(duplicate_path),
        "sha256": _write_json(duplicate_path, duplicate_adoption),
    }
    _, authority_ref = _authority_event(
        fixture,
        owner_adopted_ref=adopted_ref,
        artifact_ref=artifact_ref,
    )
    worker_task = _task_event(
        phase="worker_terminal", target="wk-1", evidence_ref=worker_ref, ordinal=1
    )
    owner_task = _task_event(
        phase="owner_verdict", target="wk-1", evidence_ref=owner_ref, ordinal=2
    )
    adopted_task = _task_event(
        phase="owner_adopted", target="wk-1", evidence_ref=adopted_ref, ordinal=3
    )
    duplicate_task = _task_event(
        phase="owner_adopted", target="wk-1", evidence_ref=duplicate_ref, ordinal=4
    )

    duplicate_run = tmp_path / "duplicate-adoption-run"
    _write_run(duplicate_run, [worker_task, owner_task, adopted_task, duplicate_task])
    with pytest.raises(DispatchEconomicsError, match="duplicate adoption events"):
        project_dispatch_outcomes(duplicate_run)

    authority_task = _task_event(
        phase="authority_applied", target="wk-1", evidence_ref=authority_ref, ordinal=4
    )
    out_of_order_run = tmp_path / "authority-before-adoption-run"
    _write_run(out_of_order_run, [worker_task, owner_task, authority_task, adopted_task])
    with pytest.raises(DispatchEconomicsError, match="authority apply predecessor.*out of order"):
        project_dispatch_outcomes(out_of_order_run)


def test_retry_costs_include_failed_attempt_before_verified_outcome(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest_ref, envelope_ref, _ = _seal_dispatch(fixture)
    failed, failed_ref, _ = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
        attempt_number=1,
        total_tokens=30,
        accepted=False,
        suffix="-failed",
    )
    accepted, accepted_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=manifest_ref,
        envelope_ref=envelope_ref,
        attempt_number=2,
        total_tokens=70,
        accepted=True,
        suffix="-accepted",
    )
    _, owner_ref = _owner_event(
        fixture,
        provider_ref=accepted_ref,
        artifact_ref=artifact_ref,
        suffix="-retry",
    )
    _, adopted_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_ref,
        artifact_ref=artifact_ref,
        suffix="-retry",
    )
    _, authority_ref = _authority_event(
        fixture,
        owner_adopted_ref=adopted_ref,
        artifact_ref=artifact_ref,
        suffix="-retry",
    )
    _, effect_ref = _effect_event(
        fixture,
        authority_ref=authority_ref,
        artifact_ref=artifact_ref,
        suffix="-retry",
    )
    assert failed["provider_accepted"] is False
    assert accepted["provider_accepted"] is True
    events = [
        _task_event(phase="worker_terminal", target="wk-1", evidence_ref=failed_ref, ordinal=1),
        _task_event(phase="worker_terminal", target="wk-1", evidence_ref=accepted_ref, ordinal=2),
        _task_event(phase="owner_verdict", target="wk-1", evidence_ref=owner_ref, ordinal=3),
        _task_event(phase="owner_adopted", target="wk-1", evidence_ref=adopted_ref, ordinal=4),
        _task_event(
            phase="authority_applied", target="wk-1", evidence_ref=authority_ref, ordinal=5
        ),
        _task_event(phase="effect_verified", target="wk-1", evidence_ref=effect_ref, ordinal=6),
    ]
    run = tmp_path / "retry-run"
    _write_run(run, events)
    projection = project_dispatch_outcomes(run)
    assert projection["metrics"]["total_tokens"] == 100
    assert projection["metrics"]["cost_per_verified_work_unit"] == 100
    assert projection["work_keys"][0]["attempt_count"] == 2
    assert projection["work_keys"][0]["failed_tokens"] == 30
    assert projection["outcome_chain_closed"] is True


def test_token_outcomes_do_not_mix_same_bare_work_key_across_parent_and_package(
    tmp_path: Path,
) -> None:
    first = _fixture(
        tmp_path / "first",
        parent_work_key="parent-a",
        first_work_key="shared-work",
    )
    first_manifest, first_envelope, _ = _seal_dispatch(first)
    _, first_provider_ref, first_artifact = _worker_event(
        first,
        package_id="p1",
        manifest_ref=first_manifest,
        envelope_ref=first_envelope,
        total_tokens=41,
    )
    _, first_owner_ref = _owner_event(
        first,
        provider_ref=first_provider_ref,
        artifact_ref=first_artifact,
    )
    _, first_adoption_ref = _owner_adoption_event(
        first,
        owner_verdict_ref=first_owner_ref,
        artifact_ref=first_artifact,
    )
    _, first_authority_ref = _authority_event(
        first,
        owner_adopted_ref=first_adoption_ref,
        artifact_ref=first_artifact,
        work_key="shared-work",
        suffix="-first",
    )
    _, first_effect_ref = _effect_event(
        first,
        authority_ref=first_authority_ref,
        artifact_ref=first_artifact,
        work_key="shared-work",
        suffix="-first",
    )

    second = _fixture(
        tmp_path / "second",
        parent_work_key="parent-b",
        first_package_id="q1",
        second_package_id="q2",
        first_work_key="shared-work",
        second_work_key="other-work",
    )
    second_manifest, second_envelope, _ = _seal_dispatch(
        second,
        package_ids=["q1"],
    )
    _, second_provider_ref, _ = _worker_event(
        second,
        package_id="q1",
        manifest_ref=second_manifest,
        envelope_ref=second_envelope,
        total_tokens=59,
    )
    run = tmp_path / "composite-identity-run"
    _write_run(
        run,
        [
            _task_event(
                phase="worker_terminal",
                target="shared-work",
                evidence_ref=first_provider_ref,
                ordinal=1,
            ),
            _task_event(
                phase="owner_verdict",
                target="shared-work",
                evidence_ref=first_owner_ref,
                ordinal=2,
            ),
            _task_event(
                phase="owner_adopted",
                target="shared-work",
                evidence_ref=first_adoption_ref,
                ordinal=3,
            ),
            _task_event(
                phase="authority_applied",
                target="shared-work",
                evidence_ref=first_authority_ref,
                ordinal=4,
            ),
            _task_event(
                phase="effect_verified",
                target="shared-work",
                evidence_ref=first_effect_ref,
                ordinal=5,
            ),
            _task_event(
                phase="worker_terminal",
                target="shared-work",
                evidence_ref=second_provider_ref,
                ordinal=6,
            ),
        ],
    )
    projection = project_dispatch_outcomes(run)
    rows = {
        (row["parent_work_key"], row["work_key"], row["package_id"]): row
        for row in projection["work_keys"]
    }
    assert set(rows) == {
        ("parent-a", "shared-work", "p1"),
        ("parent-b", "shared-work", "q1"),
    }
    assert rows[("parent-a", "shared-work", "p1")]["total_tokens"] == 41
    assert rows[("parent-a", "shared-work", "p1")]["effect_verified"] is True
    assert rows[("parent-b", "shared-work", "q1")]["total_tokens"] == 59
    assert rows[("parent-b", "shared-work", "q1")]["effect_verified"] is False
    assert projection["metrics"]["cost_per_verified_work_unit"] == 100


def test_a_b_consumers_accept_same_neutral_manifest_but_derive_physical_binding(
    tmp_path: Path,
) -> None:
    a_envelope, _, b_envelope, _, manifest_bytes = _a_b_dispatch_refs(tmp_path)
    admitted_base = tmp_path / "dispatch" / "evidence" / "packages"
    a = validate_candidate_consumer_binding(
        a_envelope,
        physical_consumer_id=GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
        expected_leg="A",
        allowed_candidate_bases=[admitted_base],
    )
    b = validate_candidate_consumer_binding(
        b_envelope,
        physical_consumer_id=GROK_DOCKER_CONSUMER_ID,
        expected_leg="B",
        allowed_candidate_bases=[admitted_base],
    )

    assert a["package_manifest_ref"] == b["package_manifest_ref"]
    assert Path(a["package_manifest_ref"]["path"]).read_bytes() == manifest_bytes
    assert a["logical_consumer_id"] == b["logical_consumer_id"]
    assert a["physical_consumer_id"] == GROK_DIRECT_WORKER_POOL_CONSUMER_ID
    assert b["physical_consumer_id"] == GROK_DOCKER_CONSUMER_ID
    assert a["boundaries"] == b["boundaries"]
    with pytest.raises(DispatchEconomicsError, match="outside the admitted D runtime"):
        validate_candidate_consumer_binding(
            a_envelope,
            physical_consumer_id=GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
            expected_leg="A",
        )
    with pytest.raises(DispatchEconomicsError, match="physical consumer"):
        validate_candidate_consumer_binding(
            a_envelope,
            physical_consumer_id=GROK_DOCKER_CONSUMER_ID,
            expected_leg="A",
            allowed_candidate_bases=[admitted_base],
        )
    with pytest.raises(DispatchEconomicsError, match="output root drifted"):
        validate_candidate_consumer_binding(
            b_envelope,
            physical_consumer_id=GROK_DOCKER_CONSUMER_ID,
            expected_leg="B",
            requested_output_roots={"p1": str(tmp_path / "dispatch" / "evidence")},
            allowed_candidate_bases=[admitted_base],
        )


def test_candidate_output_root_rejects_source_traversal_links_and_overlap(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    source = Path(str(fixture["manifest"]["packages"][0]["cwd"]))

    source_bound = copy.deepcopy(fixture["manifest"])
    source_bound["packages"][0]["allowed_output_root"] = str(source)
    with pytest.raises(DispatchEconomicsError, match="source cwd"):
        validate_package_batch_manifest(source_bound)

    arbitrary_base = copy.deepcopy(fixture["manifest"])
    arbitrary_base["candidate_output_base"] = str(source)
    arbitrary_child = source / "candidate"
    arbitrary_child.mkdir()
    arbitrary_base["packages"][0]["allowed_output_root"] = str(arbitrary_child)
    with pytest.raises(DispatchEconomicsError, match="source cwd"):
        validate_package_batch_manifest(arbitrary_base)

    traversal = copy.deepcopy(fixture["manifest"])
    traversal["packages"][0]["allowed_output_root"] = str(
        Path(str(traversal["packages"][0]["allowed_output_root"])) / ".." / "p2"
    )
    with pytest.raises(DispatchEconomicsError, match="dot path traversal"):
        validate_package_batch_manifest(traversal)

    overlap = copy.deepcopy(fixture["manifest"])
    first_root = Path(str(overlap["packages"][0]["allowed_output_root"]))
    nested = first_root / "nested"
    nested.mkdir()
    overlap["packages"][1]["allowed_output_root"] = str(nested)
    with pytest.raises(DispatchEconomicsError, match="must be disjoint"):
        validate_package_batch_manifest(overlap)

    link_target = tmp_path / "link-target"
    link_target.mkdir()
    link_path = tmp_path / "linked-output"
    try:
        link_path.symlink_to(link_target, target_is_directory=True)
    except OSError:
        return
    linked = copy.deepcopy(fixture["manifest"])
    linked["packages"][0]["allowed_output_root"] = str(link_path)
    with pytest.raises(DispatchEconomicsError, match="symlink or junction"):
        validate_package_batch_manifest(linked)


def test_dispatch_route_claim_is_cross_process_exclusive_and_winner_reuses(
    tmp_path: Path,
) -> None:
    from tests.test_action_resume_receipt import (
        _fixture as action_fixture,
    )
    from tests.test_action_resume_receipt import (
        _write_task_run_cli_fixture,
    )

    _, a_ref, _, b_ref, _ = _a_b_dispatch_refs(tmp_path)
    action = action_fixture(tmp_path / "action", work_key="parent-work")
    task_run_cli = tmp_path / "task_run_cli.py"
    _write_task_run_cli_fixture(task_run_cli)
    script = Path(__file__).resolve().parents[1] / "scripts" / "claim_worker_dispatch_route.py"

    def command(ref: dict[str, str], holder: str) -> list[str]:
        return [
            sys.executable,
            str(script),
            "--dispatch-envelope",
            ref["path"],
            "--dispatch-envelope-sha256",
            ref["sha256"],
            "--checkpoint",
            str(action["checkpoint"]),
            "--task-run-dir",
            str(action["run_dir"]),
            "--task-run-cli",
            str(task_run_cli),
            "--holder-id",
            holder,
        ]

    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    processes = [
        subprocess.Popen(
            command(a_ref, "process-a"),
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ),
        subprocess.Popen(
            command(b_ref, "process-b"),
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ),
    ]
    completed = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        completed.append((int(process.returncode or 0), stdout, stderr))
    assert sorted(row[0] for row in completed) == [0, 20]

    winner_index = next(index for index, row in enumerate(completed) if row[0] == 0)
    winner = json.loads(completed[winner_index][1])
    winner_ref = (a_ref, b_ref)[winner_index]
    retry = subprocess.run(
        command(winner_ref, "winner-retry"),
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert retry.returncode == 0, retry.stderr
    assert json.loads(retry.stdout)["status"] == "reused"

    validated = validate_dispatch_route_claim(
        route_claim_evidence_ref=winner["route_claim_evidence_ref"],
        dispatch_envelope_ref=winner_ref,
    )
    assert validated["alternative_group_sha256"] == winner["alternative_group_sha256"]
    events = [
        json.loads(line)
        for line in (Path(action["run_dir"]) / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    route_events = [row for row in events if row.get("phase") == "worker_route_claimed"]
    assert len(route_events) == 1
