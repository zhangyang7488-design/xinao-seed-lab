from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    ExecutionContractError,
    artifact_json_bytes,
    logical_contract_sha256,
    reconcile_execution,
    validate_attempt_receipt,
    validate_consumer_registry,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    GROK_DOCKER_CONSUMER_ID,
    build_grok_attempt_receipt,
    build_grok_logical_contract,
    expected_docker_grok_backend_models,
    grok_docker_model_identity_binding,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "services" / "agent_runtime" / "schemas"
MAINLINE_ROOT = Path(r"C:\Users\xx363\Desktop\主线")
TOOL_GLUE_CONSTITUTION = MAINLINE_ROOT / "工具胶水宪法" / "软件工具胶水宪法_当前有效.txt"
CROSS_SEAM_PROTOCOL = MAINLINE_ROOT / "工具胶水宪法" / "跨接缝执行封套与一致性协议_当前有效.txt"
STABLE_MAINLINE_ENTRY = MAINLINE_ROOT / "00_先读我_主线入口与读取顺序.txt"


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


def test_grok_adapter_cannot_promote_provider_rejected_evidence() -> None:
    contract = build_grok_logical_contract(
        workflow_id="workflow-1",
        lane_id="lane-1",
        operation_id="op-1",
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


def test_docker_grok_identity_bindings_keep_productivity_and_composer_ledgers_separate() -> None:
    composer = grok_docker_model_identity_binding("grok-composer-2.5-fast")
    grok45 = grok_docker_model_identity_binding("grok-4.5")
    assert composer["allowed_backend_model_ids"] == ["grok-4.5-build"]
    assert composer["session_model_id"] == "grok-composer-2.5-fast"
    assert composer["session_evidence_required"] is True
    assert composer["capability_ledger"] == "composer_exact_capability"
    assert composer["composer_completion_credit"] is True
    assert grok45["allowed_backend_model_ids"] == ["grok-4.5"]
    assert grok45["session_model_id"] == "grok-4.5"
    assert grok45["session_evidence_required"] is True
    assert grok45["capability_ledger"] == "grok_45_productivity"
    assert grok45["composer_completion_credit"] is False
    assert grok45["execution_location"] == "docker:houtai-gongren"

    contract = build_grok_logical_contract(
        workflow_id="workflow-45",
        lane_id="lane-45",
        operation_id="op-45",
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

    receipt = build(["grok-4.5"])
    assert receipt["observed"]["model_id"] == "grok-4.5"
    assert receipt["invocations"][0]["observed_model"] == "grok-4.5"
    for raw_models in (
        ["grok-4.5-build"],
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
    assert report["consumer_count"] == 8
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
            "modelUsage": {"grok-4.5": {"modelCalls": 1}},
        },
    )
    productivity45_hash = _write_registry_evidence(
        productivity45,
        {"requested_model": "grok-4.5", "observed_models": ["grok-4.5"]},
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
                "observed_models": ["grok-4.5"],
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
    receipt = _terminal_registry_receipt(
        "grok-composer-2.5-fast", "session-composer"
    )
    receipt["terminal_state"] = "failed"
    receipt_ref["sha256"] = _write_registry_evidence(receipt_path, receipt)
    with pytest.raises(ExecutionContractError, match="declared complete is not earned"):
        validate_consumer_registry(registry, repo_root=tmp_path)


def test_consumer_registry_requires_replay_newer_than_bound_execution(
    tmp_path: Path,
) -> None:
    registry = _earned_registry_fixture(tmp_path)
    registry["evidence_catalog"]["replay"]["observed_at"] = (
        "2026-07-16T00:00:00+00:00"
    )
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
    session_evidence = _session_model_evidence(
        "grok-composer-2.5-fast", "session-1"
    )
    contract = build_grok_logical_contract(
        workflow_id="workflow-1",
        lane_id="lane-1",
        operation_id="op-1",
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
