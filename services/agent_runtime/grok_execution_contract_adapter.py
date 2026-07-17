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
GROK_DOCKER_EXECUTION_LOCATION = "docker:houtai-gongren"
GROK_DOCKER_ROUTE_TRANSPORT_ID = "temporal-docker-langgraph"
GROK_MODEL_IDENTITY_BINDING_VERSION = "xinao.grok.model_identity_binding.v1"

# The CLI selector and the backend modelUsage identifier are separate identities.
# This Docker provider-seam binding is exact and intentionally asymmetric in
# ledger credit: a 4.5 call is productive but never earns Composer capability
# credit.  Both selectors still require their own exact raw modelUsage id.
_GROK_DOCKER_MODEL_IDENTITY_BINDINGS: dict[str, dict[str, object]] = {
    "grok-composer-2.5-fast": {
        "allowed_backend_model_ids": ["grok-composer-2.5-fast"],
        "capability_ledger": "composer_exact_capability",
        "composer_completion_credit": True,
    },
    "grok-4.5": {
        "allowed_backend_model_ids": ["grok-4.5"],
        "capability_ledger": "grok_45_productivity",
        "composer_completion_credit": False,
    },
}


def grok_docker_model_identity_binding(model_id: str) -> dict[str, object]:
    """Return the exact Docker selector-to-backend binding for one admitted model."""

    selected = str(model_id or "").strip()
    raw = _GROK_DOCKER_MODEL_IDENTITY_BINDINGS.get(selected)
    if raw is None:
        raise ValueError(
            f"no Docker Grok backend identity binding for selector: {selected or 'missing'}"
        )
    return {
        "schema_version": GROK_MODEL_IDENTITY_BINDING_VERSION,
        "binding_id": f"docker-houtai-gongren:{selected}",
        "provider_id": "grok_acpx_headless",
        "profile_ref": GROK_PROFILE_REF,
        "route_transport_id": GROK_DOCKER_ROUTE_TRANSPORT_ID,
        "provider_transport_id": GROK_TRANSPORT_ID,
        "execution_location": GROK_DOCKER_EXECUTION_LOCATION,
        "selected_model_id": selected,
        "allowed_backend_model_ids": list(raw["allowed_backend_model_ids"]),
        "capability_ledger": str(raw["capability_ledger"]),
        "composer_completion_credit": raw["composer_completion_credit"] is True,
    }


def expected_docker_grok_backend_models(model_id: str) -> list[str]:
    """Resolve the backend identity accepted in the canonical Docker runtime."""

    return list(grok_docker_model_identity_binding(model_id)["allowed_backend_model_ids"])


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
        "model_identity_binding": grok_docker_model_identity_binding(model_id),
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
    selected_model = str(contract["selection"]["model_id"])
    if observed_model != selected_model:
        raise ValueError(
            "Grok accepted logical identity disagrees with the selected contract: "
            f"selected={selected_model}, accepted={observed_model}"
        )
    expected_backend_models = expected_docker_grok_backend_models(selected_model)
    invocations: list[dict[str, object]] = []
    for index, raw in enumerate(invocation_evidence, start=1):
        usage = raw.get("usage") if isinstance(raw.get("usage"), Mapping) else {}
        total_tokens = int(usage.get("total_tokens") or 0)
        raw_observed_models = raw.get("observed_models")
        invocation_models = (
            [str(value) for value in raw_observed_models if str(value)]
            if isinstance(raw_observed_models, list)
            else []
        )
        if invocation_models and invocation_models != expected_backend_models:
            raise ValueError(
                "Grok invocation backend identity disagrees with the selected binding: "
                f"selected={selected_model}, required_backend={expected_backend_models}, "
                f"invocation={invocation_models}"
            )
        if total_tokens > 0 and invocation_models != expected_backend_models:
            raise ValueError(
                "Grok invocation with positive usage has no exact backend identity: "
                f"selected={selected_model}, required_backend={expected_backend_models}, "
                f"invocation={invocation_models}"
            )
        invocations.append(
            {
                "invocation": int(raw.get("invocation") or index),
                "state": _invocation_state(raw),
                "observed_model": selected_model,
                "stop_reason": str(raw.get("stop_reason") or ""),
                "output_sha256": str(raw.get("text_sha256") or ""),
                "output_chars": int(raw.get("text_chars") or 0),
                "total_tokens": total_tokens,
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
            "model_id": selected_model,
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
    "GROK_DOCKER_EXECUTION_LOCATION",
    "GROK_PROFILE_REF",
    "GROK_TRANSPORT_ID",
    "build_grok_attempt_receipt",
    "build_grok_logical_contract",
    "expected_docker_grok_backend_models",
    "grok_docker_model_identity_binding",
]
