"""Translate already-validated Grok evidence into the common seam contract."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    canonical_json_bytes,
    logical_contract_sha256,
    validate_attempt_receipt,
    validate_logical_contract,
)

GROK_PROFILE_REF = "grok.com.cached_profile"
GROK_TRANSPORT_ID = "grok_cli_json"
GROK_DOCKER_CONSUMER_ID = "canonical_docker_grok_worker"


def _sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_grok_logical_contract(
    *,
    workflow_id: str,
    lane_id: str,
    operation_id: str,
    correlation_id: str,
    parent_operation_id: str,
    task_contract_ref: str,
    provider_id: str,
    model_id: str,
    execution_prompt_sha256: str,
    context_sha256: str,
    rules_sha256: str,
    output_contract_sha256: str,
    capability_policy: Mapping[str, object],
    allowed_tools: Sequence[str],
    cli_policy_version: str,
    write: bool,
    deadline_seconds: int,
) -> dict[str, Any]:
    """Build the selected logical contract without provider-observed result data."""

    work_key = correlation_id or task_contract_ref or workflow_id
    capability_binding = {
        "allowed_tools": list(allowed_tools),
        "capability_policy": dict(capability_policy),
        "cli_policy_version": cli_policy_version,
    }
    contract = {
        "schema_version": LOGICAL_CONTRACT_VERSION,
        "logical_operation_id": operation_id,
        "work_key": work_key,
        "task_contract_ref": task_contract_ref,
        "parent_operation_id": parent_operation_id,
        "correlation_id": correlation_id,
        "input_sha256": execution_prompt_sha256,
        "context_sha256": context_sha256,
        "rules_sha256": rules_sha256,
        "output_contract_sha256": output_contract_sha256,
        "selection": {
            "provider_id": provider_id,
            "profile_ref": GROK_PROFILE_REF,
            "model_id": model_id,
            "transport_id": GROK_TRANSPORT_ID,
            "capability_binding_sha256": _sha256(capability_binding),
        },
        "effect_mode": "authorized_write" if write else "read_only",
        "idempotency_key": operation_id,
        "deadline": {
            "owner": "temporal",
            "mode": "relative_from_activity_start",
            "seconds": int(deadline_seconds),
        },
        "cancellation_generation": 0,
    }
    return validate_logical_contract(contract)


def _invocation_state(item: Mapping[str, object]) -> str:
    if item.get("effective_output_accepted") is True:
        return "accepted"
    stop_reason = str(item.get("stop_reason") or "").strip().lower()
    if stop_reason == "cancelled":
        return "cancelled"
    failure_kind = str(item.get("failure_kind") or "none").strip().lower()
    if failure_kind not in {"", "none"} or int(item.get("return_code") or 0) != 0:
        return "failed"
    return "rejected"


def build_grok_attempt_receipt(
    *,
    logical_contract: Mapping[str, object],
    attempt: int,
    invocation_evidence: Sequence[Mapping[str, object]],
    invocation_accounting: Mapping[str, object],
    observed_model: str,
    observed_rules_sha256: str,
    runtime_version: str,
    execution_location: str,
    executor_id: str,
    result_format: str,
    result_text_sha256: str,
    result_text_chars: int,
    output_schema_sha256: str,
    schema_valid: bool,
    markers_ok: bool,
    substantive: bool,
    stop_reason: str,
    workflow_id: str,
    lane_id: str,
    parent_operation_id: str,
    correlation_id: str,
    session_id: str,
    provider_contract_version: str,
    provider_evidence_ref: str,
    provider_evidence_sha256: str,
    provider_evidence_valid: bool,
    replayed: bool,
) -> dict[str, Any]:
    """Create a common receipt only after the Grok-native contract has passed."""

    contract = validate_logical_contract(logical_contract)
    invocations: list[dict[str, object]] = []
    for index, raw in enumerate(invocation_evidence, start=1):
        usage = raw.get("usage") if isinstance(raw.get("usage"), Mapping) else {}
        invocation_model = str(raw.get("selected_model") or observed_model)
        invocations.append(
            {
                "invocation": int(raw.get("invocation") or index),
                "state": _invocation_state(raw),
                "observed_model": invocation_model,
                "stop_reason": str(raw.get("stop_reason") or ""),
                "output_sha256": str(raw.get("text_sha256") or ""),
                "output_chars": int(raw.get("text_chars") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
            }
        )
    receipt = {
        "schema_version": ATTEMPT_RECEIPT_VERSION,
        "contract_sha256": logical_contract_sha256(contract),
        "consumer_id": GROK_DOCKER_CONSUMER_ID,
        "logical_operation_id": contract["logical_operation_id"],
        "work_key": contract["work_key"],
        "attempt": int(attempt),
        "observed": {
            "provider_id": contract["selection"]["provider_id"],
            "profile_ref": GROK_PROFILE_REF,
            "model_id": observed_model,
            "transport_id": GROK_TRANSPORT_ID,
            "capability_binding_sha256": contract["selection"]["capability_binding_sha256"],
            "rules_sha256": observed_rules_sha256,
            "runtime_version": runtime_version,
            "execution_location": execution_location,
            "executor_id": executor_id,
        },
        "terminal_state": "completed",
        "stop_reason": stop_reason,
        "output": {
            "format": result_format,
            "content_sha256": result_text_sha256,
            "chars": int(result_text_chars),
            "schema_sha256": output_schema_sha256,
            "schema_valid": bool(schema_valid),
            "markers_ok": bool(markers_ok),
            "substantive": bool(substantive),
        },
        "invocations": invocations,
        "usage": {
            "invocation_count": int(invocation_accounting.get("invocation_count") or 0),
            "total_tokens": int(invocation_accounting.get("total_tokens") or 0),
            "accepted_tokens": int(invocation_accounting.get("accepted_tokens") or 0),
            "cancelled_tokens": int(invocation_accounting.get("cancelled_tokens") or 0),
            "failed_tokens": int(invocation_accounting.get("failed_tokens") or 0),
        },
        "lineage": {
            "workflow_id": workflow_id,
            "lane_id": lane_id,
            "parent_operation_id": parent_operation_id,
            "correlation_id": correlation_id,
            "session_id": session_id,
        },
        "provider_contract_version": provider_contract_version,
        "provider_evidence_ref": provider_evidence_ref,
        "provider_evidence_sha256": provider_evidence_sha256,
        "provider_evidence_valid": bool(provider_evidence_valid),
        "replayed": bool(replayed),
    }
    verdict = validate_attempt_receipt(
        contract,
        receipt,
        expected_consumer_id=GROK_DOCKER_CONSUMER_ID,
    )
    if not verdict.accepted:
        raise ValueError(
            "Grok evidence did not satisfy the common execution receipt: "
            + ",".join(verdict.reason_codes)
        )
    return receipt


__all__ = [
    "GROK_DOCKER_CONSUMER_ID",
    "GROK_PROFILE_REF",
    "GROK_TRANSPORT_ID",
    "build_grok_attempt_receipt",
    "build_grok_logical_contract",
]
