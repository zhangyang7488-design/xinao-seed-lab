from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    IDENTICAL_WORK_DISPOSITIONS,
    LOGICAL_CONTRACT_VERSION,
    ExecutionContractError,
    _validate_registry_terminal_receipts,
    artifact_json_bytes,
    build_common_dispatch_disposition,
    classify_identical_work_disposition,
    identical_work_pin_sha256,
    logical_contract_sha256,
    may_run_concurrent,
    reconcile_execution,
    validate_attempt_receipt,
    validate_consumer_registry,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
    GROK_DOCKER_CONSUMER_ID,
    GROK_DOCKER_ROUTE_TRANSPORT_ID,
    build_direct_worker_pool_attempt_receipt,
    build_direct_worker_pool_logical_contract,
    build_grok_attempt_receipt,
    build_grok_docker_route_adapter_binding,
    build_grok_logical_contract,
    expected_docker_grok_backend_models,
    grok_docker_model_identity_binding,
    validate_grok_docker_route_adapter_binding,
    validate_grok_route_selection_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "services" / "agent_runtime" / "schemas"
MAINLINE_ROOT = Path(r"C:\Users\xx363\Desktop\主线")
TOOL_GLUE_CONSTITUTION = MAINLINE_ROOT / "工具胶水宪法" / "软件工具胶水宪法_当前有效.txt"
CROSS_SEAM_PROTOCOL = MAINLINE_ROOT / "工具胶水宪法" / "跨接缝执行封套与一致性协议_当前有效.txt"
STABLE_MAINLINE_ENTRY = MAINLINE_ROOT / "00_先读我_主线入口与读取顺序.txt"


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
    receipt["decision_sha256"] = hashlib.sha256(
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return receipt


def test_docker_route_adapter_separates_selector_route_from_provider_transport() -> None:
    receipt = _route_selection_receipt(GROK_DOCKER_ROUTE_TRANSPORT_ID)
    route = validate_grok_route_selection_receipt(
        receipt,
        expected_route_transport_id=GROK_DOCKER_ROUTE_TRANSPORT_ID,
    )
    binding = build_grok_docker_route_adapter_binding(receipt)
    assert route["route_identity"]["transport_id"] == "temporal-docker-langgraph"
    assert binding["route_transport_id"] == "temporal-docker-langgraph"
    assert binding["provider_transport_id"] == "grok_cli_json"
    assert binding["route_identity_sha256"] == route["route_identity_sha256"]
    assert len(str(binding["adapter_binding_sha256"])) == 64
    assert (
        validate_grok_docker_route_adapter_binding(
            binding,
            route_selection_receipt=receipt,
        )
        == binding
    )

    contract = build_grok_logical_contract(
        workflow_id="wf-route-adapter",
        lane_id="lane-route-adapter",
        operation_id="op-route-adapter",
        work_key="wk-route-adapter",
        correlation_id="corr-route-adapter",
        parent_operation_id="parent-route-adapter",
        task_contract_ref="manifest.json#sha256=" + "1" * 64,
        provider_id="grok_acpx_headless",
        model_id="grok-4.5",
        execution_prompt_sha256="2" * 64,
        context_sha256="3" * 64,
        rules_sha256="4" * 64,
        output_contract_sha256="5" * 64,
        capability_policy={"planning": "auto"},
        allowed_tools=[],
        cli_policy_version="grok-cli-effective-output-v7",
        write=False,
        deadline_seconds=600,
        route_adapter_binding_sha256=str(binding["adapter_binding_sha256"]),
    )
    assert contract["selection"]["transport_id"] == "grok_cli_json"
    assert contract["selection"]["capability_binding_sha256"] != binding["adapter_binding_sha256"]


def test_docker_route_adapter_rejects_direct_route_fake_capability_and_drift() -> None:
    direct = _route_selection_receipt("direct-grok-worker-pool")
    with pytest.raises(ValueError, match="transport_id"):
        build_grok_docker_route_adapter_binding(direct)

    fake_capability = _route_selection_receipt(GROK_DOCKER_ROUTE_TRANSPORT_ID)
    fake_capability["selected_candidate"]["capability_binding_sha256"] = "a" * 64
    fake_capability.pop("decision_sha256")
    fake_capability["decision_sha256"] = hashlib.sha256(
        json.dumps(
            fake_capability,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="must not claim provider capability"):
        build_grok_docker_route_adapter_binding(fake_capability)

    receipt = _route_selection_receipt(GROK_DOCKER_ROUTE_TRANSPORT_ID)
    binding = build_grok_docker_route_adapter_binding(receipt)
    drifted = copy.deepcopy(binding)
    drifted["provider_transport_id"] = "fake_adapter"
    with pytest.raises(ValueError, match="adapter binding drifted"):
        validate_grok_docker_route_adapter_binding(
            drifted,
            route_selection_receipt=receipt,
        )


def _session_model_evidence(model: str, session_id: str) -> dict[str, object]:
    backend_models = expected_docker_grok_backend_models(model)
    return {
        "source": "grok_session_summary_and_turn_events",
        "requestedModel": model,
        "selectedSessionModel": model,
        "currentModelId": model,
        "turnModelIds": [model],
        "observedModelId": backend_models[0],
        "modelUsageIds": backend_models,
        "backendModelIds": backend_models,
        "expectedBackendModelIds": backend_models,
        "backendSessionId": session_id,
        "sessionCwd": "/app",
        "sessionGrokHome": "/grok-home/.grok",
        "sessionSummaryRef": f"/grok-home/.grok/sessions/test/{session_id}/summary.json",
        "sessionSummarySha256": "a" * 64,
        "sessionEventsRef": f"/grok-home/.grok/sessions/test/{session_id}/events.jsonl",
        "sessionEventsSha256": "b" * 64,
    }


def _contract() -> dict[str, object]:
    return {
        "schema_version": LOGICAL_CONTRACT_VERSION,
        "logical_operation_id": "op-1",
        "work_key": "work-1",
        "task_contract_ref": "task-contract-1",
        "parent_operation_id": "parent-1",
        "correlation_id": "correlation-1",
        "input_sha256": "1" * 64,
        "context_sha256": "2" * 64,
        "rules_sha256": "3" * 64,
        "output_contract_sha256": "4" * 64,
        "selection": {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": "grok-composer-2.5-fast",
            "transport_id": "grok_cli_json",
            "capability_binding_sha256": "5" * 64,
        },
        "effect_mode": "read_only",
        "idempotency_key": "op-1",
        "deadline": {
            "owner": "temporal",
            "mode": "relative_from_activity_start",
            "seconds": 1800,
        },
        "cancellation_generation": 0,
    }


def _receipt() -> dict[str, object]:
    contract = _contract()
    return {
        "schema_version": ATTEMPT_RECEIPT_VERSION,
        "contract_sha256": logical_contract_sha256(contract),
        "consumer_id": GROK_DOCKER_CONSUMER_ID,
        "logical_operation_id": "op-1",
        "work_key": "work-1",
        "attempt": 1,
        "observed": {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": "grok-composer-2.5-fast",
            "transport_id": "grok_cli_json",
            "capability_binding_sha256": "5" * 64,
            "rules_sha256": "3" * 64,
            "runtime_version": "0.2.101",
            "execution_location": "docker:houtai-gongren",
            "executor_id": "container-1",
        },
        "terminal_state": "completed",
        "stop_reason": "EndTurn",
        "output": {
            "format": "json_object",
            "content_sha256": "6" * 64,
            "chars": 1200,
            "schema_sha256": "4" * 64,
            "schema_valid": True,
            "markers_ok": True,
            "substantive": True,
        },
        "invocations": [
            {
                "invocation": 1,
                "state": "rejected",
                "observed_model": "grok-composer-2.5-fast",
                "stop_reason": "EndTurn",
                "output_sha256": "7" * 64,
                "output_chars": 300,
                "total_tokens": 5,
            },
            {
                "invocation": 2,
                "state": "accepted",
                "observed_model": "grok-composer-2.5-fast",
                "stop_reason": "EndTurn",
                "output_sha256": "6" * 64,
                "output_chars": 1200,
                "total_tokens": 7,
            },
        ],
        "usage": {
            "invocation_count": 2,
            "total_tokens": 12,
            "accepted_tokens": 7,
            "cancelled_tokens": 0,
            "failed_tokens": 5,
        },
        "lineage": {
            "workflow_id": "workflow-1",
            "lane_id": "lane-1",
            "parent_operation_id": "parent-1",
            "correlation_id": "correlation-1",
            "session_id": "session-1",
        },
        "provider_contract_version": "xinao.grok.shared_execution_contract.v1",
        "provider_evidence_ref": "D:/evidence/cli_result.json",
        "provider_evidence_sha256": "8" * 64,
        "provider_evidence_valid": True,
        "replayed": False,
    }


def test_machine_schemas_accept_the_common_contract_and_receipt() -> None:
    logical_schema = json.loads(
        (SCHEMA_ROOT / "execution_logical_contract.v1.schema.json").read_text(encoding="utf-8")
    )
    receipt_schema = json.loads(
        (SCHEMA_ROOT / "execution_attempt_receipt.v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(logical_schema)
    Draft202012Validator.check_schema(receipt_schema)
    Draft202012Validator(logical_schema).validate(_contract())
    Draft202012Validator(receipt_schema).validate(_receipt())


def test_logical_contract_hash_is_order_independent_and_self_field_free() -> None:
    contract = _contract()
    reversed_contract = dict(reversed(list(contract.items())))
    assert logical_contract_sha256(contract) == logical_contract_sha256(reversed_contract)
    with pytest.raises(ExecutionContractError, match="must not contain its own digest"):
        logical_contract_sha256({**contract, "contract_sha256": "9" * 64})


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("provider_id", "other", "OBSERVED_PROVIDER_ID_MISMATCH"),
        ("profile_ref", "other", "OBSERVED_PROFILE_REF_MISMATCH"),
        ("model_id", "grok-4.5", "OBSERVED_MODEL_ID_MISMATCH"),
        ("transport_id", "other", "OBSERVED_TRANSPORT_ID_MISMATCH"),
        ("rules_sha256", "9" * 64, "OBSERVED_RULES_MISMATCH"),
        ("capability_binding_sha256", "9" * 64, "OBSERVED_CAPABILITY_BINDING_SHA256_MISMATCH"),
    ],
)
def test_attempt_receipt_rejects_selected_observed_drift(
    field: str,
    value: str,
    reason: str,
) -> None:
    receipt = _receipt()
    receipt["observed"][field] = value
    verdict = validate_attempt_receipt(_contract(), receipt)
    assert verdict.accepted is False
    assert reason in verdict.reason_codes


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("cancelled", "NON_COMPLETED_TERMINAL_STATE"),
        ("schema", "OUTPUT_SCHEMA_REJECTED"),
        ("markers", "OUTPUT_MARKERS_REJECTED"),
        ("short", "NON_SUBSTANTIVE_OUTPUT"),
        ("provider", "PROVIDER_EVIDENCE_REJECTED"),
    ],
)
def test_attempt_receipt_rejects_non_effective_output(mutation: str, reason: str) -> None:
    receipt = _receipt()
    if mutation == "cancelled":
        receipt["terminal_state"] = "cancelled"
    elif mutation == "schema":
        receipt["output"]["schema_valid"] = False
    elif mutation == "markers":
        receipt["output"]["markers_ok"] = False
    elif mutation == "short":
        receipt["output"]["substantive"] = False
    else:
        receipt["provider_evidence_valid"] = False
    verdict = validate_attempt_receipt(_contract(), receipt)
    assert verdict.accepted is False
    assert reason in verdict.reason_codes


def test_attempt_receipt_requires_complete_token_partition() -> None:
    receipt = _receipt()
    receipt["usage"]["failed_tokens"] = 4
    with pytest.raises(ExecutionContractError, match="token partition does not balance"):
        validate_attempt_receipt(_contract(), receipt)


def test_non_token_native_execution_can_close_with_an_accepted_invocation() -> None:
    receipt = _receipt()
    receipt["invocations"] = [
        {
            "invocation": 1,
            "state": "accepted",
            "observed_model": "grok-composer-2.5-fast",
            "stop_reason": "NativeExecutionCompleted",
            "output_sha256": "6" * 64,
            "output_chars": 1200,
            "total_tokens": 0,
        }
    ]
    receipt["usage"] = {
        "invocation_count": 1,
        "total_tokens": 0,
        "accepted_tokens": 0,
        "cancelled_tokens": 0,
        "failed_tokens": 0,
    }

    verdict = validate_attempt_receipt(_contract(), receipt)

    assert verdict.accepted is True
    assert "NO_ACCEPTED_TOKENS" not in verdict.reason_codes


def test_reconciliation_only_closes_the_latest_accepted_attempt() -> None:
    first = _receipt()
    first["terminal_state"] = "failed"
    second = _receipt()
    second["attempt"] = 2
    assert reconcile_execution(_contract(), [first, second])["state"] == "accepted"
    second["terminal_state"] = "timed_out"
    decision = reconcile_execution(_contract(), [first, second])
    assert decision["state"] == "unresolved"
    assert "NON_COMPLETED_TERMINAL_STATE" in decision["reason_codes"]


def test_identical_work_pin_binds_all_frozen_hashes_subject_and_capability() -> None:
    subject = "9" * 64
    baseline = identical_work_pin_sha256(_contract(), subject_manifest_sha256=subject)
    reordered = dict(reversed(list(_contract().items())))
    assert identical_work_pin_sha256(reordered, subject_manifest_sha256=subject) == baseline

    for field in ("input_sha256", "context_sha256", "rules_sha256", "output_contract_sha256"):
        drifted = copy.deepcopy(_contract())
        drifted[field] = "a" * 64
        assert identical_work_pin_sha256(drifted, subject_manifest_sha256=subject) != baseline
    capability_drift = copy.deepcopy(_contract())
    capability_drift["selection"]["capability_binding_sha256"] = "a" * 64
    assert identical_work_pin_sha256(capability_drift, subject_manifest_sha256=subject) != baseline
    assert identical_work_pin_sha256(_contract(), subject_manifest_sha256="a" * 64) != baseline


def test_identical_reuse_requires_current_contract_receipt_validation() -> None:
    subject = "9" * 64
    current = _contract()
    prior = {
        "logical_contract": _contract(),
        "attempt_receipt": _receipt(),
        "subject_manifest_sha256": subject,
    }
    accepted = classify_identical_work_disposition(
        current,
        subject_manifest_sha256=subject,
        prior_accepted=[prior],
    )
    assert accepted is not None
    assert accepted["disposition"] == "ACCEPTED_IDENTICAL_REUSE"
    assert accepted["skip_execution"] is True
    assert accepted["completion_claim_allowed"] is False

    # Deadline is deliberately outside the identical-work pin, but it changes
    # the authoritative contract digest. A stale receipt therefore cannot reuse.
    changed_contract = copy.deepcopy(current)
    changed_contract["deadline"]["seconds"] = 900
    rejected = classify_identical_work_disposition(
        changed_contract,
        subject_manifest_sha256=subject,
        prior_accepted=[prior],
    )
    assert rejected is not None
    assert rejected["disposition"] == "SAME_PIN_NO_NEW_PROOF"
    assert rejected["skip_execution"] is False


def test_identical_work_live_and_failed_proof_dispositions_do_not_burn_reseals() -> None:
    subject = "9" * 64
    pin = identical_work_pin_sha256(_contract(), subject_manifest_sha256=subject)
    live = classify_identical_work_disposition(
        _contract(),
        subject_manifest_sha256=subject,
        live_pins=[pin],
    )
    assert live is not None and live["disposition"] == "LIVE_IDENTICAL"
    assert live["dispatch_allowed"] is False

    prior_failed = [
        {
            "identical_work_pin_sha256": pin,
            "terminal_state": "failed",
            "proof_sha256": "a" * 64,
        }
    ]
    same = classify_identical_work_disposition(
        _contract(),
        subject_manifest_sha256=subject,
        prior_terminal_failed=prior_failed,
        new_proof_sha256="a" * 64,
    )
    assert same is not None and same["disposition"] == "SAME_PIN_NO_NEW_PROOF"
    assert same["dispatch_allowed"] is False
    novel = classify_identical_work_disposition(
        _contract(),
        subject_manifest_sha256=subject,
        prior_terminal_failed=prior_failed,
        new_proof_sha256="b" * 64,
    )
    assert novel is not None and novel["disposition"] == "TERMINAL_FAILED_NEW_PROOF"
    assert novel["dispatch_allowed"] is True


def test_phase_fence_is_dependency_and_overlapping_domain_only() -> None:
    explore = {
        "unit_id": "explore-a",
        "phase": "EXPLORE",
        "write_domains": [],
        "depends_on": [],
    }
    verify = {
        "unit_id": "verify-b",
        "phase": "VERIFY",
        "write_domains": [],
        "depends_on": [],
    }
    assert may_run_concurrent(explore, verify) is True
    dependent = {**verify, "depends_on": ["explore-a"]}
    assert may_run_concurrent(explore, dependent) is False

    land_a = {
        "unit_id": "land-a",
        "phase": "LAND",
        "write_domains": [r"C:\Mainline\G1"],
        "depends_on": [],
    }
    land_same = {
        "unit_id": "land-b",
        "phase": "LAND",
        "write_domains": ["c:/mainline/g1/"],
        "depends_on": [],
    }
    land_disjoint = {
        "unit_id": "land-c",
        "phase": "LAND",
        "write_domains": ["c:/mainline/g2"],
        "depends_on": [],
    }
    assert may_run_concurrent(land_a, land_same) is False
    assert may_run_concurrent(land_a, land_disjoint) is True
    with pytest.raises(ExecutionContractError, match="LAND.*write domain"):
        may_run_concurrent(
            {**land_a, "write_domains": []},
            land_disjoint,
        )


def test_common_dispatch_disposition_is_derived_and_never_completion_authority() -> None:
    subject = "9" * 64
    pin = identical_work_pin_sha256(_contract(), subject_manifest_sha256=subject)
    classification = classify_identical_work_disposition(
        _contract(),
        subject_manifest_sha256=subject,
        live_pins=[pin],
    )
    artifact = build_common_dispatch_disposition(
        _contract(),
        subject_manifest_sha256=subject,
        phase="VERIFY",
        write_domains=[],
        depends_on=["construct-1"],
        classification=classification,
    )
    assert artifact["disposition"] in IDENTICAL_WORK_DISPOSITIONS
    assert artifact["authority"] is False
    assert artifact["completion_claim_allowed"] is False
    assert artifact["contract_sha256"] == logical_contract_sha256(_contract())
    assert artifact["identical_work_pin_sha256"] == pin


def _direct_pool_lane_evidence() -> dict[str, object]:
    return {
        "run_id": "c25-direct-1",
        "lane_id": "lane_00",
        "status": "accepted",
        "outcome": "accepted",
        "effective_output_accepted": True,
        "requested_model": "grok-4.5",
        "session_model": "grok-4.5",
        "model_identity_ok": True,
        "backend_model_identity_ok": True,
        "session_model_identity_ok": True,
        "session_turn_model_identity_ok": True,
        "session_evidence_ok": True,
        "usage_accounting_complete": True,
        "usage_is_incomplete": False,
        "stop_reason": "EndTurn",
        "result_text_sha256": "a" * 64,
        "result_text_chars": 512,
        "structured_output_present": False,
        "json_schema_requested": False,
        "schema_instance_valid": None,
        "observed_rules_sha256": "3" * 64,
        "observed_capability_binding_sha256": "",
        "session_id": "session-direct-1",
        "usage": {"total_tokens": 99},
    }


def test_direct_worker_pool_builders_emit_valid_common_accepted_receipt() -> None:
    subject = "9" * 64
    contract = build_direct_worker_pool_logical_contract(
        work_key="work-direct-1",
        operation_id="op-direct-1",
        task_contract_ref="task-direct-1",
        parent_operation_id="parent-1",
        correlation_id="correlation-1",
        provider_id="grok_acpx_headless",
        profile_ref="grok.com.cached_profile",
        model_id="grok-4.5",
        frozen_input_sha256="1" * 64,
        frozen_context_sha256="2" * 64,
        subject_manifest_sha256=subject,
        rules_sha256="3" * 64,
        output_contract_sha256="4" * 64,
        capability_binding={
            "selection_receipt_sha256": "5" * 64,
            "required_markers": ["STATUS="],
        },
        write=False,
        deadline_seconds=600,
    )
    lane = _direct_pool_lane_evidence()
    lane["observed_capability_binding_sha256"] = contract["selection"]["capability_binding_sha256"]
    receipt = build_direct_worker_pool_attempt_receipt(
        logical_contract=contract,
        attempt=1,
        lane_evidence=lane,
        runtime_version="0.2.103",
        pool_id="gwp-direct-1",
        provider_contract_version="xinao.grok.shared_execution_contract.v1",
        provider_evidence_ref="D:/gwp/lane_00/latest.json",
        provider_evidence_sha256="8" * 64,
    )
    verdict = validate_attempt_receipt(
        contract,
        receipt,
        expected_consumer_id=GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
    )
    assert verdict.accepted is True
    assert contract["input_sha256"] == "1" * 64
    assert contract["context_sha256"] != "2" * 64
    assert receipt["consumer_id"] == "direct_grok_worker_pool"
    assert receipt["observed"]["transport_id"] == "direct-grok-worker-pool"
    assert receipt["usage"]["accepted_tokens"] == 99


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("session_model", "grok-composer-2.5-fast", "session model"),
        ("model_identity_ok", False, "identity"),
        ("usage_accounting_complete", False, "usage accounting"),
        ("effective_output_accepted", False, "provider-native"),
        ("stop_reason", "MaxTurns", "EndTurn"),
        ("session_id", "", "session identity"),
    ],
)
def test_direct_worker_pool_common_receipt_fails_closed_on_native_drift(
    field: str, value: object, reason: str
) -> None:
    contract = build_direct_worker_pool_logical_contract(
        work_key="work-direct-1",
        operation_id="op-direct-1",
        task_contract_ref="task-direct-1",
        parent_operation_id="parent-1",
        correlation_id="correlation-1",
        provider_id="grok_acpx_headless",
        profile_ref="grok.com.cached_profile",
        model_id="grok-4.5",
        frozen_input_sha256="1" * 64,
        frozen_context_sha256="2" * 64,
        subject_manifest_sha256="9" * 64,
        rules_sha256="3" * 64,
        output_contract_sha256="4" * 64,
        capability_binding={"selection_receipt_sha256": "5" * 64},
        write=False,
        deadline_seconds=600,
    )
    lane = _direct_pool_lane_evidence()
    lane["observed_capability_binding_sha256"] = contract["selection"]["capability_binding_sha256"]
    lane[field] = value
    with pytest.raises(ValueError, match=reason):
        build_direct_worker_pool_attempt_receipt(
            logical_contract=contract,
            attempt=1,
            lane_evidence=lane,
            runtime_version="0.2.103",
            pool_id="gwp-direct-1",
            provider_contract_version="xinao.grok.shared_execution_contract.v1",
            provider_evidence_ref="D:/gwp/lane_00/latest.json",
            provider_evidence_sha256="8" * 64,
        )


def test_direct_worker_pool_contract_rejects_unbound_subject_hash() -> None:
    with pytest.raises(ValueError, match="subject_manifest_sha256"):
        build_direct_worker_pool_logical_contract(
            work_key="work-direct-1",
            operation_id="op-direct-1",
            task_contract_ref="task-direct-1",
            parent_operation_id="parent-1",
            correlation_id="correlation-1",
            provider_id="grok_acpx_headless",
            profile_ref="grok.com.cached_profile",
            model_id="grok-4.5",
            frozen_input_sha256="1" * 64,
            frozen_context_sha256="2" * 64,
            subject_manifest_sha256="not-a-sha",
            rules_sha256="3" * 64,
            output_contract_sha256="4" * 64,
            capability_binding={"selection_receipt_sha256": "5" * 64},
            write=False,
            deadline_seconds=600,
        )


def test_grok_adapter_cannot_promote_provider_rejected_evidence() -> None:
    contract = build_grok_logical_contract(
        workflow_id="workflow-1",
        lane_id="lane-1",
        operation_id="op-1",
        work_key="work-1",
        correlation_id="work-1",
        parent_operation_id="parent-1",
        task_contract_ref="",
        provider_id="grok_acpx_headless",
        model_id="grok-composer-2.5-fast",
        execution_prompt_sha256="1" * 64,
        context_sha256="2" * 64,
        rules_sha256="3" * 64,
        output_contract_sha256="4" * 64,
        capability_policy={"planning": "auto"},
        allowed_tools=[],
        cli_policy_version="grok-cli-effective-output-v7",
        write=False,
        deadline_seconds=1800,
    )
    invocation = {
        "invocation": 1,
        "effective_output_accepted": True,
        "failure_kind": "none",
        "return_code": 0,
        "observed_models": ["grok-4.5-build"],
        "stop_reason": "EndTurn",
        "text_sha256": "6" * 64,
        "text_chars": 1200,
        "usage": {"total_tokens": 7},
    }

    def build(
        invocation_value: dict[str, object],
        *,
        provider_valid: bool,
        session_evidence: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return build_grok_attempt_receipt(
            logical_contract=contract,
            attempt=1,
            invocation_evidence=[invocation_value],
            invocation_accounting={
                "invocation_count": 1,
                "total_tokens": 7,
                "accepted_tokens": 7,
                "cancelled_tokens": 0,
                "failed_tokens": 0,
            },
            observed_model="grok-composer-2.5-fast",
            observed_rules_sha256="3" * 64,
            runtime_version="0.2.101",
            execution_location="docker:houtai-gongren",
            executor_id="container-1",
            result_format="json_object",
            result_text_sha256="6" * 64,
            result_text_chars=1200,
            output_schema_sha256="4" * 64,
            schema_valid=True,
            markers_ok=True,
            substantive=True,
            stop_reason="EndTurn",
            workflow_id="workflow-1",
            lane_id="lane-1",
            parent_operation_id="parent-1",
            correlation_id="work-1",
            session_id="session-1",
            provider_contract_version="xinao.grok.shared_execution_contract.v1",
            provider_evidence_ref="D:/evidence/cli_result.json",
            provider_evidence_sha256="8" * 64,
            provider_evidence_valid=provider_valid,
            session_model_evidence=session_evidence
            or _session_model_evidence("grok-composer-2.5-fast", "session-1"),
            replayed=False,
        )

    with pytest.raises(ValueError, match="PROVIDER_EVIDENCE_REJECTED"):
        build(invocation, provider_valid=False)

    forged_backend = {**invocation, "observed_models": ["grok-4.5"]}
    with pytest.raises(ValueError, match="backend identity disagrees"):
        build(forged_backend, provider_valid=True)

    forged_session = _session_model_evidence("grok-composer-2.5-fast", "session-1")
    forged_session["currentModelId"] = "grok-4.5"
    with pytest.raises(ValueError, match="session model evidence mismatch"):
        build(invocation, provider_valid=True, session_evidence=forged_session)


def test_grok_logical_contract_keeps_canonical_work_key_distinct_from_batch_correlation() -> None:
    contract = build_grok_logical_contract(
        workflow_id="workflow-batch",
        lane_id="lane-canonical",
        operation_id="op-canonical",
        work_key="canonical-work-key",
        correlation_id="batch-correlation-id",
        parent_operation_id="parent-batch",
        task_contract_ref="D:/evidence/package.json#sha256=" + "a" * 64,
        provider_id="grok_acpx_headless",
        model_id="grok-4.5",
        execution_prompt_sha256="1" * 64,
        context_sha256="2" * 64,
        rules_sha256="3" * 64,
        output_contract_sha256="4" * 64,
        capability_policy={"planning": "auto"},
        allowed_tools=[],
        cli_policy_version="grok-cli-effective-output-v7",
        write=False,
        deadline_seconds=1800,
    )
    assert contract["work_key"] == "canonical-work-key"
    assert contract["correlation_id"] == "batch-correlation-id"
    assert contract["task_contract_ref"].endswith("a" * 64)

    with pytest.raises(ValueError, match="work_key must be explicit"):
        build_grok_logical_contract(
            workflow_id="workflow-batch",
            lane_id="lane-missing",
            operation_id="op-missing",
            work_key="",
            correlation_id="batch-correlation-id",
            parent_operation_id="parent-batch",
            task_contract_ref="D:/evidence/package.json#sha256=" + "a" * 64,
            provider_id="grok_acpx_headless",
            model_id="grok-4.5",
            execution_prompt_sha256="1" * 64,
            context_sha256="2" * 64,
            rules_sha256="3" * 64,
            output_contract_sha256="4" * 64,
            capability_policy={"planning": "auto"},
            allowed_tools=[],
            cli_policy_version="grok-cli-effective-output-v7",
            write=False,
            deadline_seconds=1800,
            require_explicit_work_key=True,
        )


def test_docker_grok_identity_bindings_keep_productivity_and_composer_ledgers_separate() -> None:
    composer = grok_docker_model_identity_binding("grok-composer-2.5-fast")
    grok45 = grok_docker_model_identity_binding("grok-4.5")
    assert composer["allowed_backend_model_ids"] == ["grok-4.5-build"]
    assert composer["session_model_id"] == "grok-composer-2.5-fast"
    assert composer["session_evidence_required"] is True
    assert composer["capability_ledger"] == "composer_exact_capability"
    assert composer["composer_completion_credit"] is True
    assert grok45["allowed_backend_model_ids"] == ["grok-4.5-build"]
    assert grok45["session_model_id"] == "grok-4.5"
    assert grok45["session_evidence_required"] is True
    assert grok45["capability_ledger"] == "grok_45_productivity"
    assert grok45["composer_completion_credit"] is False
    assert grok45["execution_location"] == "docker:houtai-gongren"

    contract = build_grok_logical_contract(
        workflow_id="workflow-45",
        lane_id="lane-45",
        operation_id="op-45",
        work_key="work-45",
        correlation_id="work-45",
        parent_operation_id="parent-45",
        task_contract_ref="",
        provider_id="grok_acpx_headless",
        model_id="grok-4.5",
        execution_prompt_sha256="1" * 64,
        context_sha256="2" * 64,
        rules_sha256="3" * 64,
        output_contract_sha256="4" * 64,
        capability_policy={"planning": "auto"},
        allowed_tools=[],
        cli_policy_version="grok-cli-effective-output-v7",
        write=False,
        deadline_seconds=1800,
    )

    def build(raw_models: list[str]) -> dict[str, object]:
        invocation = {
            "invocation": 1,
            "effective_output_accepted": True,
            "failure_kind": "none",
            "return_code": 0,
            "observed_models": raw_models,
            "stop_reason": "EndTurn",
            "text_sha256": "6" * 64,
            "text_chars": 1200,
            "usage": {"total_tokens": 7},
        }
        return build_grok_attempt_receipt(
            logical_contract=contract,
            attempt=1,
            invocation_evidence=[invocation],
            invocation_accounting={
                "invocation_count": 1,
                "total_tokens": 7,
                "accepted_tokens": 7,
                "cancelled_tokens": 0,
                "failed_tokens": 0,
            },
            observed_model="grok-4.5",
            observed_rules_sha256="3" * 64,
            runtime_version="0.2.101",
            execution_location="docker:houtai-gongren",
            executor_id="container-45",
            result_format="text",
            result_text_sha256="6" * 64,
            result_text_chars=1200,
            output_schema_sha256="4" * 64,
            schema_valid=True,
            markers_ok=True,
            substantive=True,
            stop_reason="EndTurn",
            workflow_id="workflow-45",
            lane_id="lane-45",
            parent_operation_id="parent-45",
            correlation_id="work-45",
            session_id="session-45",
            provider_contract_version="xinao.grok.shared_execution_contract.v1",
            provider_evidence_ref="D:/evidence/grok45-cli-result.json",
            provider_evidence_sha256="8" * 64,
            provider_evidence_valid=True,
            session_model_evidence=_session_model_evidence("grok-4.5", "session-45"),
            replayed=False,
        )

    receipt = build(["grok-4.5-build"])
    assert receipt["observed"]["model_id"] == "grok-4.5"
    assert receipt["invocations"][0]["observed_model"] == "grok-4.5"
    for raw_models in (
        ["grok-4.5"],
        ["grok-composer-2.5-fast"],
        ["grok-4.5-build", "grok-composer-2.5-fast"],
    ):
        with pytest.raises(ValueError, match="backend identity disagrees"):
            build(raw_models)


def test_consumer_registry_requires_current_exact_evidence_for_complete_status() -> None:
    registry = json.loads(
        (ROOT / "services" / "agent_runtime" / "execution_consumers.v1.json").read_text(
            encoding="utf-8"
        )
    )
    evidence_catalog = registry["evidence_catalog"]
    productivity_refs = registry["provider_identity_binding_contract"][
        "current_productivity_evidence"
    ]
    if any(not Path(evidence_catalog[ref]["path"]).is_file() for ref in productivity_refs):
        pytest.skip("canonical operator evidence is unavailable on this runner")
    report = validate_consumer_registry(registry, repo_root=ROOT)
    assert report["ok"] is True
    assert report["consumer_count"] == 20
    exact_consumers = {
        "canonical_docker_grok_worker",
        "canonical_langgraph_grok_fanin",
        "integrated_bus_provider_promotion",
        "promoted_temporal_task_workflow",
        "foundation_v2_reconciliation",
    }
    assert {
        item["consumer_id"]
        for item in report["consumers"]
        if item["effective_status"] == "complete"
    } == exact_consumers
    for item in report["consumers"]:
        if item["consumer_id"] not in exact_consumers:
            continue
        assert item["declared_status"] == "complete"
        assert item["effective_status"] == "complete"
        assert item["conformance_status"] == "complete"
        assert item["completion_claim_allowed"] is True
        assert "EXACT_MODEL_IDENTITY_DRIFT" not in item["reason_codes"]
        assert item["evidence_files_exist"] is True
    inner = next(
        item
        for item in report["consumers"]
        if item["consumer_id"] == "codex_inner_profile_consumer"
    )
    assert inner["declared_status"] == "partial"
    assert inner["effective_status"] == "partial"
    assert inner["completion_claim_allowed"] is False
    boundary_consumers = {
        item["consumer_id"]: item
        for item in report["consumers"]
        if item["declared_status"] == "boundary_verified_non_parent_owner"
    }
    assert set(boundary_consumers) == {
        "action_resume_preaction_guard",
        "audit_adjudication_repair_gate",
        "current_science_temporal_entry",
        "g4_batch_preregistration_producer",
        "g4_provider_neutral_batch_admission",
        "global_frontier_reconciliation_v4",
        "problem_transition_task_run_adapter",
        "system_awareness_task_run_scanner",
        "worktree_carrier_resolver",
        "worktree_lifecycle_record_producer",
        "worktree_lifecycle_scanner",
    }
    assert all(
        item["effective_status"] == "boundary_verified_non_parent_owner"
        and item["completion_claim_allowed"] is False
        and item["parent_completion_authority"] is False
        for item in boundary_consumers.values()
    )
    science = boundary_consumers["current_science_temporal_entry"]
    assert science["conformance_status"] == "complete"
    science_source = next(
        item
        for item in registry["consumers"]
        if item["consumer_id"] == "current_science_temporal_entry"
    )
    assert science_source["legacy_parent_gate_consumed"] is False
    assert science_source["research_progress_authority"] is False
    assert science_source["replay_evidence"]
    assert science_source["current_positive_canary_evidence"]
    assert science_source["negative_canary_evidence"]
    assert science_source["fresh_canary_evidence"]
    by_id = {item["consumer_id"]: item for item in registry["consumers"]}
    for consumer_id in (
        "foundation_v2_reconciliation",
        "g4_batch_preregistration_producer",
        "g4_provider_neutral_batch_admission",
    ):
        assert by_id[consumer_id]["authority_scope"] == "LEGACY_PARENT_G0_G8"
        assert by_id[consumer_id]["usable_as_current_science_parent"] is False
        assert by_id[consumer_id]["parent_completion_authority"] is False
    forged = copy.deepcopy(registry)
    incomplete = next(
        item
        for item in forged["consumers"]
        if item["consumer_id"] == "canonical_docker_grok_worker"
    )
    incomplete["current_positive_canary_evidence"] = []
    with pytest.raises(ExecutionContractError, match="declared complete is not earned"):
        validate_consumer_registry(forged, repo_root=ROOT)


def _write_registry_evidence(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(artifact_json_bytes(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_registry_terminal_receipt_uses_exact_contract_and_provider_bytes(
    tmp_path: Path,
) -> None:
    contract_path = tmp_path / "logical_contract.json"
    receipt_path = tmp_path / "attempt_receipt.json"
    contract_sha = _write_registry_evidence(contract_path, _contract())
    receipt_sha = _write_registry_evidence(receipt_path, _receipt())
    evidence = {
        "logical_contract_evidence": ["contract"],
        "terminal_receipt_evidence": ["receipt"],
    }
    catalog = {
        "contract": {"path": str(contract_path), "sha256": contract_sha},
        "receipt": {"path": str(receipt_path), "sha256": receipt_sha},
    }

    assert _validate_registry_terminal_receipts(
        evidence,
        selected_model="grok-composer-2.5-fast",
        expected_session_ids={"session-1"},
        expected_provider_sha256s={"8" * 64},
        catalog=catalog,
        repo_root=tmp_path,
        field="strong_registry_fixture",
    ) == {"session-1"}
    with pytest.raises(ExecutionContractError, match="substantive completion"):
        _validate_registry_terminal_receipts(
            evidence,
            selected_model="grok-composer-2.5-fast",
            expected_session_ids={"session-1"},
            expected_provider_sha256s={"9" * 64},
            catalog=catalog,
            repo_root=tmp_path,
            field="strong_registry_fixture",
        )


def _terminal_registry_receipt(selected_model: str, session_id: str) -> dict[str, object]:
    return {
        "schema_version": ATTEMPT_RECEIPT_VERSION,
        "terminal_state": "completed",
        "stop_reason": "EndTurn",
        "provider_evidence_valid": True,
        "observed": {"model_id": selected_model},
        "output": {
            "chars": 300,
            "content_sha256": "a" * 64,
            "markers_ok": True,
            "schema_valid": True,
            "substantive": True,
        },
        "usage": {
            "invocation_count": 1,
            "accepted_tokens": 100,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
            "total_tokens": 100,
        },
        "lineage": {"session_id": session_id},
        "invocations": [
            {
                "state": "accepted",
                "stop_reason": "EndTurn",
                "total_tokens": 100,
                "output_chars": 300,
            }
        ],
    }


def _earned_registry_fixture(tmp_path: Path) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "worker.py"
    test_file = tmp_path / "test_worker.py"
    source.write_text("pass\n", encoding="utf-8")
    test_file.write_text("def test_worker(): pass\n", encoding="utf-8")
    replay = tmp_path / "replay.json"
    raw = tmp_path / "cli_result.json"
    raw45 = tmp_path / "grok45_cli_result.json"
    productivity45 = tmp_path / "grok45_productivity.json"
    session_composer = tmp_path / "composer_session_identity.json"
    session45 = tmp_path / "grok45_session_identity.json"
    receipt_composer = tmp_path / "composer_terminal_receipt.json"
    receipt45 = tmp_path / "grok45_terminal_receipt.json"
    positive = tmp_path / "positive.json"
    negative = tmp_path / "negative.json"
    replay_hash = _write_registry_evidence(replay, {"replay": "ok"})
    raw_hash = _write_registry_evidence(
        raw,
        {
            "sessionId": "session-composer",
            "stopReason": "EndTurn",
            "text": "x" * 300,
            "usage": {"total_tokens": 100},
            "modelUsage": {"grok-4.5-build": {"modelCalls": 1}},
        },
    )
    raw45_hash = _write_registry_evidence(
        raw45,
        {
            "sessionId": "session-45",
            "stopReason": "EndTurn",
            "text": "x" * 300,
            "usage": {"total_tokens": 100},
            "modelUsage": {"grok-4.5-build": {"modelCalls": 1}},
        },
    )
    productivity45_hash = _write_registry_evidence(
        productivity45,
        {"requested_model": "grok-4.5", "observed_models": ["grok-4.5-build"]},
    )
    session_composer_hash = _write_registry_evidence(
        session_composer,
        _session_model_evidence("grok-composer-2.5-fast", "session-composer"),
    )
    session45_hash = _write_registry_evidence(
        session45,
        _session_model_evidence("grok-4.5", "session-45"),
    )
    receipt_composer_hash = _write_registry_evidence(
        receipt_composer,
        _terminal_registry_receipt("grok-composer-2.5-fast", "session-composer"),
    )
    receipt45_hash = _write_registry_evidence(
        receipt45,
        _terminal_registry_receipt("grok-4.5", "session-45"),
    )
    positive_hash = _write_registry_evidence(positive, {"canary": "positive"})
    negative_hash = _write_registry_evidence(
        negative,
        {
            "model": "grok-composer-2.5-fast",
            "observed_models": ["grok-composer-2.5-fast"],
        },
    )
    return {
        "schema_version": "xinao.execution.consumer_registry.v1",
        "logical_contract_version": LOGICAL_CONTRACT_VERSION,
        "attempt_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "provider_identity_binding_contract": {
            "schema_version": "xinao.execution.provider_identity_binding_ref.v1",
            "authority_source_path": str(source),
            "authority_entrypoint": "grok_docker_model_identity_binding",
            "execution_scope": "docker:houtai-gongren",
            "conformance_test": str(test_file),
            "current_productivity_evidence": ["productivity45"],
        },
        "evidence_catalog": {
            "replay": {
                "path": str(replay),
                "sha256": replay_hash,
                "observed_at": "2026-07-18T00:01:00+00:00",
            },
            "raw": {"path": str(raw), "sha256": raw_hash},
            "raw45": {"path": str(raw45), "sha256": raw45_hash},
            "session_composer": {
                "path": str(session_composer),
                "sha256": session_composer_hash,
            },
            "session45": {"path": str(session45), "sha256": session45_hash},
            "receipt_composer": {
                "path": str(receipt_composer),
                "sha256": receipt_composer_hash,
            },
            "receipt45": {"path": str(receipt45), "sha256": receipt45_hash},
            "productivity45": {
                "path": str(productivity45),
                "sha256": productivity45_hash,
                "requested_model": "grok-4.5",
                "observed_models": ["grok-4.5-build"],
                "capability_ledger": "grok_45_productivity",
                "composer_completion_credit": False,
                "completion_claim_allowed": True,
                "raw_identity_evidence": ["raw45"],
                "session_identity_evidence": ["session45"],
                "terminal_receipt_evidence": ["receipt45"],
            },
            "positive": {
                "path": str(positive),
                "sha256": positive_hash,
                "observed_at": "2026-07-18T00:00:00+00:00",
                "requested_model": "grok-composer-2.5-fast",
                "observed_models": ["grok-4.5-build"],
                "completion_claim_allowed": True,
                "raw_identity_evidence": ["raw"],
                "session_identity_evidence": ["session_composer"],
                "terminal_receipt_evidence": ["receipt_composer"],
            },
            "negative": {
                "path": str(negative),
                "sha256": negative_hash,
                "observed_at": "2026-07-17T00:00:00+00:00",
                "requested_model": "grok-composer-2.5-fast",
                "observed_models": ["grok-4.5-build"],
                "completion_claim_allowed": False,
            },
        },
        "consumers": [
            {
                "consumer_id": "fixture",
                "source_path": str(source),
                "entrypoint": "run",
                "role": "worker",
                "contract_mode": "fixture",
                "status": "complete",
                "conformance_status": "complete",
                "status_reason": "fixture",
                "writes_effects": False,
                "completion_claim": {
                    "ledger": "composer_exact_capability",
                    "requested_model": "grok-composer-2.5-fast",
                    "allowed_observed_models": ["grok-4.5-build"],
                },
                "conformance_tests": [str(test_file)],
                "replay_evidence": ["replay"],
                "current_positive_canary_evidence": ["positive"],
                "superseded_evidence": [],
                "negative_canary_evidence": ["negative"],
                "blocking_evidence": [
                    {"evidence_id": "negative", "reason_code": "EXACT_MODEL_IDENTITY_DRIFT"}
                ],
                "fresh_canary_evidence": [],
            }
        ],
    }


def test_consumer_registry_requires_newer_hash_bound_exact_raw_identity(tmp_path: Path) -> None:
    registry = _earned_registry_fixture(tmp_path)
    report = validate_consumer_registry(registry, repo_root=tmp_path)
    item = report["consumers"][0]
    assert item["effective_status"] == "complete"
    assert item["completion_claim_allowed"] is True

    raw_ref = registry["evidence_catalog"]["raw"]
    raw_path = Path(raw_ref["path"])
    raw_ref["sha256"] = _write_registry_evidence(
        raw_path,
        {"modelUsage": {"grok-composer-2.5-fast": {"modelCalls": 1}}},
    )
    with pytest.raises(ExecutionContractError, match="declared complete is not earned"):
        validate_consumer_registry(registry, repo_root=tmp_path)


def test_consumer_registry_cross_binds_raw_session_and_terminal_receipt(
    tmp_path: Path,
) -> None:
    registry = _earned_registry_fixture(tmp_path)
    session_ref = registry["evidence_catalog"]["session_composer"]
    session_path = Path(session_ref["path"])
    session_ref["sha256"] = _write_registry_evidence(
        session_path,
        _session_model_evidence("grok-composer-2.5-fast", "different-session"),
    )
    with pytest.raises(ExecutionContractError, match="declared complete is not earned"):
        validate_consumer_registry(registry, repo_root=tmp_path)

    registry = _earned_registry_fixture(tmp_path / "terminal")
    receipt_ref = registry["evidence_catalog"]["receipt_composer"]
    receipt_path = Path(receipt_ref["path"])
    receipt = _terminal_registry_receipt("grok-composer-2.5-fast", "session-composer")
    receipt["terminal_state"] = "failed"
    receipt_ref["sha256"] = _write_registry_evidence(receipt_path, receipt)
    with pytest.raises(ExecutionContractError, match="declared complete is not earned"):
        validate_consumer_registry(registry, repo_root=tmp_path)


def test_consumer_registry_requires_replay_newer_than_bound_execution(
    tmp_path: Path,
) -> None:
    registry = _earned_registry_fixture(tmp_path)
    registry["evidence_catalog"]["replay"]["observed_at"] = "2026-07-16T00:00:00+00:00"
    with pytest.raises(ExecutionContractError, match="REPLAY_EVIDENCE_STALE"):
        validate_consumer_registry(registry, repo_root=tmp_path)


def test_superseded_or_missing_evidence_cannot_earn_complete(tmp_path: Path) -> None:
    registry = _earned_registry_fixture(tmp_path)
    consumer = registry["consumers"][0]
    consumer["superseded_evidence"] = consumer["current_positive_canary_evidence"]
    consumer["current_positive_canary_evidence"] = []
    with pytest.raises(ExecutionContractError, match="CURRENT_POSITIVE_CANARY_MISSING"):
        validate_consumer_registry(registry, repo_root=tmp_path)

    registry = _earned_registry_fixture(tmp_path / "missing")
    registry["evidence_catalog"]["replay"]["path"] = str(tmp_path / "absent.json")
    with pytest.raises(ExecutionContractError, match="REPLAY_EVIDENCE_INVALID"):
        validate_consumer_registry(registry, repo_root=tmp_path)


def test_foundation_consumer_accepts_only_hash_bound_docker_common_artifacts(
    tmp_path: Path,
) -> None:
    from services.agent_runtime.foundation_continuous_workflow_v2 import (
        _verify_docker_common_lane_receipt,
        _verify_operation_spec,
    )

    operation_root = tmp_path / "operations" / "op-1"
    operation_root.mkdir(parents=True)
    final_text = '{"status":"VERIFIED","work_key":"work-1"}'
    final_raw = final_text.encode("utf-8")
    final_sha256 = hashlib.sha256(final_raw).hexdigest()
    identity = {
        "stopReason": "EndTurn",
        "sessionId": "session-1",
        "modelUsage": {"grok-4.5-build": {"modelCalls": 1}},
    }
    identity_raw = artifact_json_bytes(identity)
    identity_sha256 = hashlib.sha256(identity_raw).hexdigest()
    identity_path = operation_root / "cli_result.json"
    identity_path.write_bytes(identity_raw)
    session_evidence = _session_model_evidence("grok-composer-2.5-fast", "session-1")
    contract = build_grok_logical_contract(
        workflow_id="workflow-1",
        lane_id="lane-1",
        operation_id="op-1",
        work_key="work-1",
        correlation_id="work-1",
        parent_operation_id="parent-1",
        task_contract_ref="xinao.foundation.f4.readonly_lane.v1",
        provider_id="grok_acpx_headless",
        model_id="grok-composer-2.5-fast",
        execution_prompt_sha256="1" * 64,
        context_sha256="2" * 64,
        rules_sha256="3" * 64,
        output_contract_sha256="4" * 64,
        capability_policy={"planning": "auto"},
        allowed_tools=["read_file"],
        cli_policy_version="grok-cli-effective-output-v7",
        write=False,
        deadline_seconds=1800,
    )
    receipt = build_grok_attempt_receipt(
        logical_contract=contract,
        attempt=1,
        invocation_evidence=[
            {
                "invocation": 1,
                "effective_output_accepted": True,
                "failure_kind": "none",
                "return_code": 0,
                "observed_models": ["grok-4.5-build"],
                "stop_reason": "EndTurn",
                "text_sha256": final_sha256,
                "text_chars": len(final_text),
                "usage": {"total_tokens": 7},
            }
        ],
        invocation_accounting={
            "invocation_count": 1,
            "total_tokens": 7,
            "accepted_tokens": 7,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
        observed_model="grok-composer-2.5-fast",
        observed_rules_sha256="3" * 64,
        runtime_version="0.2.101",
        execution_location="docker:houtai-gongren",
        executor_id="container-1",
        result_format="json_object",
        result_text_sha256=final_sha256,
        result_text_chars=len(final_text),
        output_schema_sha256="4" * 64,
        schema_valid=True,
        markers_ok=True,
        substantive=True,
        stop_reason="EndTurn",
        workflow_id="workflow-1",
        lane_id="lane-1",
        parent_operation_id="parent-1",
        correlation_id="work-1",
        session_id="session-1",
        provider_contract_version="xinao.grok.shared_execution_contract.v1",
        provider_evidence_ref=str(identity_path),
        provider_evidence_sha256=identity_sha256,
        provider_evidence_valid=True,
        session_model_evidence=session_evidence,
        replayed=False,
    )
    result_schema = {"type": "object"}
    result_schema_sha256 = hashlib.sha256(artifact_json_bytes(result_schema)).hexdigest()
    operation_spec = {
        "schema_version": "xinao.grok.docker_native_cli.v1",
        "model": "grok-composer-2.5-fast",
        "contract_id": "xinao.foundation.f4.readonly_lane.v1",
        "write": False,
        "allowed_tools": ["read_file"],
        "prompt_sha256": "5" * 64,
        "execution_prompt_sha256": "1" * 64,
        "result_format": "json_object",
        "result_json_schema": result_schema,
        "result_json_schema_sha256": result_schema_sha256,
    }
    values = {
        "logical_contract.json": artifact_json_bytes(contract),
        "attempt_receipt.json": artifact_json_bytes(receipt),
        "operation-spec.json": artifact_json_bytes(operation_spec),
        "session_model_evidence.json": artifact_json_bytes(session_evidence),
        "final.txt": final_raw,
    }
    paths = {"cli_result.json": identity_path}
    for name, raw in values.items():
        path = operation_root / name
        path.write_bytes(raw)
        paths[name] = path
    artifacts = {
        name: {
            "name": name,
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in paths.items()
    }
    lane = {
        "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "cross_seam_attempt_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "cross_seam_contract_sha256": logical_contract_sha256(contract),
        "cross_seam_logical_contract": contract,
        "cross_seam_logical_contract_ref": str(paths["logical_contract.json"]),
        "cross_seam_logical_contract_artifact_sha256": artifacts["logical_contract.json"]["sha256"],
        "cross_seam_attempt_receipt": receipt,
        "cross_seam_attempt_receipt_ref": str(paths["attempt_receipt.json"]),
        "cross_seam_attempt_receipt_sha256": artifacts["attempt_receipt.json"]["sha256"],
        "model_identity_ref": str(identity_path),
        "model_identity_sha256": identity_sha256,
        "session_model_evidence": session_evidence,
        "session_model_evidence_ref": str(paths["session_model_evidence.json"]),
        "session_model_evidence_sha256": artifacts["session_model_evidence.json"]["sha256"],
        "agent_session_id": "session-1",
        "operation_spec_ref": str(paths["operation-spec.json"]),
        "operation_spec_sha256": artifacts["operation-spec.json"]["sha256"],
        "final_ref": str(paths["final.txt"]),
        "result_text": final_text,
        "result_text_sha256": final_sha256,
    }
    expected_binding = {
        "requested_model": "grok-composer-2.5-fast",
        "contract_id": "xinao.foundation.f4.readonly_lane.v1",
        "write": False,
        "allowed_tools": ["read_file"],
        "permission_mode": "approve-reads",
        "prompt_sha256": "5" * 64,
        "result_format": "json_object",
        "result_json_schema_sha256": result_schema_sha256,
    }

    _verify_operation_spec(paths["operation-spec.json"], expected_binding)
    accepted = _verify_docker_common_lane_receipt(tmp_path, lane, artifacts)
    assert accepted["attempt_receipt_sha256"] == artifacts["attempt_receipt.json"]["sha256"]

    paths["final.txt"].write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact binding drifted"):
        _verify_docker_common_lane_receipt(tmp_path, lane, artifacts)


def test_cross_seam_protocol_is_one_constitution_incorporated_appendix() -> None:
    if not all(
        path.is_file()
        for path in (TOOL_GLUE_CONSTITUTION, CROSS_SEAM_PROTOCOL, STABLE_MAINLINE_ENTRY)
    ):
        pytest.skip("canonical mainline material is unavailable on this runner")
    constitution = TOOL_GLUE_CONSTITUTION.read_text(encoding="utf-8")
    protocol = CROSS_SEAM_PROTOCOL.read_text(encoding="utf-8")
    stable_entry = STABLE_MAINLINE_ENTRY.read_text(encoding="utf-8")
    assert "SENTINEL:XINAO_CROSS_SEAM_EXECUTION_ENVELOPE_PROTOCOL_V1" in protocol
    assert str(CROSS_SEAM_PROTOCOL) in constitution
    assert "唯一跨接缝窄域附录" in constitution
    assert "唯一跨接缝窄域附录" in stable_entry
    assert "外部成熟完整性不是产品名词清单" in protocol
    assert "不创造任务授权" in protocol and "第二控制面" in protocol


def test_cross_seam_protocol_has_no_web_answer_or_enterprise_gate_template() -> None:
    if not CROSS_SEAM_PROTOCOL.is_file():
        pytest.skip("canonical mainline material is unavailable on this runner")
    protocol = CROSS_SEAM_PROTOCOL.read_text(encoding="utf-8")
    assert "http://" not in protocol and "https://" not in protocol
    for phrase in ("我会先", "我已经读取", "你可以直接", "别被吓到", "REQUIRE_APPROVAL"):
        assert phrase not in protocol
