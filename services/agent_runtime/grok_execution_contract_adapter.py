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
GROK_DOCKER_ROUTE_ADAPTER_VERSION = "xinao.grok.route_provider_adapter.v1"
GROK_CLI_POLICY_VERSION = "grok-cli-effective-output-v7"
GROK_DOCKER_PACKAGE_CAPABILITY_POLICY = {
    "planning": "auto",
    "subagents": "auto",
    "external_research": "auto",
    "memory": "auto",
}
GROK_DIRECT_WORKER_POOL_CONSUMER_ID = "direct_grok_worker_pool"
GROK_DIRECT_WORKER_POOL_EXECUTION_LOCATION = "host:grok_worker_pool"
GROK_DIRECT_WORKER_POOL_TRANSPORT_ID = "direct-grok-worker-pool"
GROK_DIRECT_WORKER_POOL_CONTRACT_MODE = "provider_v1_then_common_adapter"
GROK_MODEL_IDENTITY_BINDING_VERSION = "xinao.grok.model_identity_binding.v2"

# The CLI session selector and the backend modelUsage identifier are separate
# identities.  Composer currently records the shared backend build identifier,
# while a directly selected Grok 4.5 session records its public model id.
# Completion credit still requires exact session summary + turn-event evidence;
# backend usage alone can never prove which selector the supervisor chose.
_GROK_DOCKER_MODEL_IDENTITY_BINDINGS: dict[str, dict[str, object]] = {
    "grok-composer-2.5-fast": {
        "allowed_backend_model_ids": ["grok-4.5-build"],
        "capability_ledger": "composer_exact_capability",
        "composer_completion_credit": True,
    },
    "grok-4.5": {
        "allowed_backend_model_ids": ["grok-4.5"],
        "capability_ledger": "grok_45_productivity",
        "composer_completion_credit": False,
    },
}


def _require_sha256_text(value: object, field: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{field} must be a lowercase sha256")
    return text


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
        "session_model_id": selected,
        "session_evidence_required": True,
        "allowed_backend_model_ids": list(raw["allowed_backend_model_ids"]),
        "capability_ledger": str(raw["capability_ledger"]),
        "composer_completion_credit": raw["composer_completion_credit"] is True,
    }


def expected_docker_grok_backend_models(model_id: str) -> list[str]:
    """Resolve the backend identity accepted in the canonical Docker runtime."""

    return list(grok_docker_model_identity_binding(model_id)["allowed_backend_model_ids"])


def validate_grok_session_model_evidence(
    evidence: Mapping[str, object],
    *,
    selected_model: str,
    session_id: str,
) -> dict[str, object]:
    """Validate the independent session-selector side of Docker model identity."""

    selected = str(selected_model or "").strip()
    expected_backend_models = expected_docker_grok_backend_models(selected)
    expected_scalars = {
        "source": "grok_session_summary_and_turn_events",
        "requestedModel": selected,
        "selectedSessionModel": selected,
        "currentModelId": selected,
        "observedModelId": expected_backend_models[0],
        "backendSessionId": str(session_id or "").strip(),
    }
    for field, expected in expected_scalars.items():
        if str(evidence.get(field) or "") != expected:
            raise ValueError(
                f"Grok session model evidence mismatch: field={field}, "
                f"expected={expected}, observed={evidence.get(field)}"
            )
    expected_lists = {
        "turnModelIds": [selected],
        "modelUsageIds": expected_backend_models,
        "backendModelIds": expected_backend_models,
        "expectedBackendModelIds": expected_backend_models,
    }
    for field, expected in expected_lists.items():
        if evidence.get(field) != expected:
            raise ValueError(
                f"Grok session model evidence mismatch: field={field}, "
                f"expected={expected}, observed={evidence.get(field)}"
            )
    for field in (
        "sessionSummaryRef",
        "sessionEventsRef",
        "sessionCwd",
        "sessionGrokHome",
    ):
        if not str(evidence.get(field) or "").strip():
            raise ValueError(f"Grok session model evidence is missing {field}")
    for field in ("sessionSummarySha256", "sessionEventsSha256"):
        value = str(evidence.get(field) or "")
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"Grok session model evidence has invalid {field}")
    return dict(evidence)


def _sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def validate_grok_route_selection_receipt(
    receipt: Mapping[str, object],
    *,
    expected_route_transport_id: str,
) -> dict[str, object]:
    """Validate one stable-selector route receipt without claiming provider capability.

    The selector owns only the exact route identity and its decision.  Provider
    transport and capability evidence are deliberately absent from this
    receipt and are bound later by the consumer-specific common adapter.
    """

    if not isinstance(receipt, Mapping):
        raise TypeError("Grok route selection receipt must be an object")
    value = dict(receipt)
    if value.get("schema_version") != "xinao.supervisor_worker_decision_receipt.v1":
        raise ValueError("Grok route selection receipt schema mismatch")
    if value.get("decision") != "selected":
        raise ValueError("Grok route selection receipt is not selected")
    decision_sha256 = _require_sha256_text(
        value.get("decision_sha256"),
        "decision_sha256",
    )
    decision_basis = dict(value)
    decision_basis.pop("decision_sha256", None)
    observed_decision_sha256 = hashlib.sha256(canonical_json_bytes(decision_basis)).hexdigest()
    if observed_decision_sha256 != decision_sha256:
        raise ValueError(
            "Grok route selection decision hash mismatch: "
            f"expected={decision_sha256};observed={observed_decision_sha256}"
        )

    selected_raw = value.get("selected_candidate")
    if not isinstance(selected_raw, Mapping):
        raise ValueError("Grok route selection selected_candidate is missing")
    selected = dict(selected_raw)
    if "capability_binding_sha256" in selected:
        raise ValueError("selector candidate must not claim provider capability_binding_sha256")
    route_identity = {
        "provider_id": str(selected.get("provider_id") or "").strip(),
        "profile_ref": str(selected.get("profile_ref") or "").strip(),
        "model_id": str(selected.get("model_id") or "").strip(),
        "transport_id": str(selected.get("transport_id") or "").strip(),
    }
    expected_identity = {
        "provider_id": "grok_acpx_headless",
        "profile_ref": GROK_PROFILE_REF,
        "transport_id": str(expected_route_transport_id or "").strip(),
    }
    for field, expected in expected_identity.items():
        if route_identity[field] != expected:
            raise ValueError(
                "Grok selector route identity mismatch: "
                f"field={field};expected={expected};observed={route_identity[field]}"
            )
    grok_docker_model_identity_binding(route_identity["model_id"])
    for fact in ("declared_active", "healthy", "positive_benefit"):
        if selected.get(fact) is not True:
            raise ValueError(f"Grok selected route is not eligible: {fact}")
    route_identity_sha256 = _sha256(route_identity)
    route_decision_binding_sha256 = _sha256(
        {
            "decision_sha256": decision_sha256,
            "route_identity_sha256": route_identity_sha256,
        }
    )
    return {
        "decision_sha256": decision_sha256,
        "route_identity": route_identity,
        "route_identity_sha256": route_identity_sha256,
        "route_decision_binding_sha256": route_decision_binding_sha256,
    }


def build_grok_docker_route_adapter_binding(
    route_selection_receipt: Mapping[str, object],
) -> dict[str, object]:
    """Seal the canonical B-route to the existing Grok CLI provider adapter."""

    selection = validate_grok_route_selection_receipt(
        route_selection_receipt,
        expected_route_transport_id=GROK_DOCKER_ROUTE_TRANSPORT_ID,
    )
    route_identity = dict(selection["route_identity"])
    binding: dict[str, object] = {
        "schema_version": GROK_DOCKER_ROUTE_ADAPTER_VERSION,
        "adapter_id": "canonical_docker_grok_route_to_cli_provider",
        "consumer_id": GROK_DOCKER_CONSUMER_ID,
        "execution_location": GROK_DOCKER_EXECUTION_LOCATION,
        "selection_decision_sha256": selection["decision_sha256"],
        "route_identity": route_identity,
        "route_identity_sha256": selection["route_identity_sha256"],
        "route_decision_binding_sha256": selection["route_decision_binding_sha256"],
        "route_transport_id": GROK_DOCKER_ROUTE_TRANSPORT_ID,
        "provider_transport_id": GROK_TRANSPORT_ID,
        "provider_model_identity_binding": grok_docker_model_identity_binding(
            str(route_identity["model_id"])
        ),
    }
    binding["adapter_binding_sha256"] = _sha256(binding)
    binding["provider_capability_binding_sha256"] = _sha256(
        {
            "allowed_tools": [],
            "capability_policy": dict(GROK_DOCKER_PACKAGE_CAPABILITY_POLICY),
            "cli_policy_version": GROK_CLI_POLICY_VERSION,
            "model_identity_binding": binding["provider_model_identity_binding"],
            "route_adapter_binding_sha256": binding["adapter_binding_sha256"],
        }
    )
    return binding


def validate_grok_docker_route_adapter_binding(
    binding: Mapping[str, object],
    *,
    route_selection_receipt: Mapping[str, object],
) -> dict[str, object]:
    """Fail closed unless B consumes the exact version-sealed route adapter."""

    if not isinstance(binding, Mapping):
        raise TypeError("Grok Docker route adapter binding must be an object")
    expected = build_grok_docker_route_adapter_binding(route_selection_receipt)
    observed = dict(binding)
    if observed != expected:
        raise ValueError("Grok Docker route adapter binding drifted")
    return expected


def direct_worker_pool_context_binding_sha256(
    *,
    frozen_context_sha256: str,
    subject_manifest_sha256: str,
) -> str:
    """Bind the frozen context and subject used by the common dedupe pin."""

    return _sha256(
        {
            "frozen_context_sha256": _require_sha256_text(
                frozen_context_sha256,
                "frozen_context_sha256",
            ),
            "subject_manifest_sha256": _require_sha256_text(
                subject_manifest_sha256,
                "subject_manifest_sha256",
            ),
        }
    )


def direct_worker_pool_output_contract(
    *,
    min_result_chars: int,
    required_result_markers: Sequence[str],
    require_json_object: bool,
    json_schema_sha256: str = "",
) -> dict[str, object]:
    """Return the exact output checks consumed by the host WorkerPool."""

    if isinstance(min_result_chars, bool) or int(min_result_chars) <= 0:
        raise ValueError("min_result_chars must be positive")
    markers = [str(value) for value in required_result_markers]
    if any(not value for value in markers):
        raise ValueError("required_result_markers must not contain empty values")
    schema_digest = str(json_schema_sha256 or "")
    if schema_digest:
        _require_sha256_text(schema_digest, "json_schema_sha256")
    return {
        "min_result_chars": int(min_result_chars),
        "required_result_markers": markers,
        "require_json_object": bool(require_json_object or schema_digest),
        "json_schema_sha256": schema_digest,
    }


def direct_worker_pool_capability_binding(
    *,
    selection_decision_sha256: str,
    output_contract_sha256: str,
) -> dict[str, object]:
    """Return the capability seam that the pool must consume before dispatch."""

    return {
        "consumer_id": GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
        "contract_mode": GROK_DIRECT_WORKER_POOL_CONTRACT_MODE,
        "lane_count": 1,
        "selection_decision_sha256": _require_sha256_text(
            selection_decision_sha256,
            "selection_decision_sha256",
        ),
        "output_contract_sha256": _require_sha256_text(
            output_contract_sha256,
            "output_contract_sha256",
        ),
    }


def build_grok_logical_contract(
    *,
    workflow_id: str,
    lane_id: str,
    operation_id: str,
    work_key: str = "",
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
    require_explicit_work_key: bool = False,
    route_adapter_binding_sha256: str = "",
) -> dict[str, Any]:
    """Build the selected logical contract without provider-observed result data."""

    canonical_work_key = str(work_key or "").strip()
    if require_explicit_work_key and not canonical_work_key:
        raise ValueError("work_key must be explicit; correlation fallback is forbidden")
    canonical_work_key = canonical_work_key or correlation_id or task_contract_ref or workflow_id
    capability_binding = {
        "allowed_tools": list(allowed_tools),
        "capability_policy": dict(capability_policy),
        "cli_policy_version": cli_policy_version,
        "model_identity_binding": grok_docker_model_identity_binding(model_id),
    }
    if route_adapter_binding_sha256:
        capability_binding["route_adapter_binding_sha256"] = _require_sha256_text(
            route_adapter_binding_sha256,
            "route_adapter_binding_sha256",
        )
    contract = {
        "schema_version": LOGICAL_CONTRACT_VERSION,
        "logical_operation_id": operation_id,
        "work_key": canonical_work_key,
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


def build_direct_worker_pool_logical_contract(
    *,
    work_key: str,
    operation_id: str,
    task_contract_ref: str,
    parent_operation_id: str,
    correlation_id: str,
    provider_id: str,
    profile_ref: str,
    model_id: str,
    frozen_input_sha256: str,
    frozen_context_sha256: str,
    subject_manifest_sha256: str,
    rules_sha256: str,
    output_contract_sha256: str,
    capability_binding: Mapping[str, object],
    write: bool,
    deadline_seconds: int,
) -> dict[str, Any]:
    """Build the host WorkerPool logical contract without provider observations."""

    _require_sha256_text(frozen_context_sha256, "frozen_context_sha256")
    _require_sha256_text(subject_manifest_sha256, "subject_manifest_sha256")
    if not isinstance(capability_binding, Mapping) or not capability_binding:
        raise ValueError("capability_binding must be a non-empty object")
    contract = {
        "schema_version": LOGICAL_CONTRACT_VERSION,
        "logical_operation_id": operation_id,
        "work_key": work_key,
        "task_contract_ref": task_contract_ref,
        "parent_operation_id": parent_operation_id,
        "correlation_id": correlation_id,
        "input_sha256": frozen_input_sha256,
        "context_sha256": direct_worker_pool_context_binding_sha256(
            frozen_context_sha256=frozen_context_sha256,
            subject_manifest_sha256=subject_manifest_sha256,
        ),
        "rules_sha256": rules_sha256,
        "output_contract_sha256": output_contract_sha256,
        "selection": {
            "provider_id": provider_id,
            "profile_ref": profile_ref,
            "model_id": model_id,
            "transport_id": GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
            "capability_binding_sha256": _sha256(dict(capability_binding)),
        },
        "effect_mode": "authorized_write" if write else "read_only",
        "idempotency_key": operation_id,
        "deadline": {
            "owner": "caller",
            "mode": "relative_from_activity_start",
            "seconds": int(deadline_seconds),
        },
        "cancellation_generation": 0,
    }
    return validate_logical_contract(contract)


def build_direct_worker_pool_attempt_receipt(
    *,
    logical_contract: Mapping[str, object],
    attempt: int,
    lane_evidence: Mapping[str, object],
    runtime_version: str,
    pool_id: str,
    provider_contract_version: str,
    provider_evidence_ref: str,
    provider_evidence_sha256: str,
) -> dict[str, Any]:
    """Translate one provider-native accepted host lane into a common receipt."""

    contract = validate_logical_contract(logical_contract)
    lane = dict(lane_evidence)
    if (
        lane.get("effective_output_accepted") is not True
        or lane.get("status") != "accepted"
        or lane.get("outcome") != "accepted"
    ):
        raise ValueError("direct WorkerPool provider-native acceptance is required")
    identity_flags = (
        "model_identity_ok",
        "backend_model_identity_ok",
        "session_model_identity_ok",
        "session_turn_model_identity_ok",
        "session_evidence_ok",
    )
    if any(lane.get(field) is not True for field in identity_flags):
        raise ValueError("direct WorkerPool identity evidence is incomplete")

    selection = contract["selection"]
    selected_model = str(selection["model_id"])
    requested_model = str(lane.get("requested_model") or "")
    session_model = str(lane.get("session_model") or "")
    if requested_model != selected_model or session_model != selected_model:
        raise ValueError(
            "direct WorkerPool session model does not match the selected logical contract"
        )
    if lane.get("usage_accounting_complete") is not True or lane.get("usage_is_incomplete") is True:
        raise ValueError("direct WorkerPool usage accounting is incomplete")
    usage_raw = lane.get("usage")
    usage = dict(usage_raw) if isinstance(usage_raw, Mapping) else {}
    total_tokens = int(usage.get("total_tokens") or 0)
    if total_tokens <= 0:
        raise ValueError("direct WorkerPool accepted lane has no positive token usage")
    observed_rules = str(lane.get("observed_rules_sha256") or "")
    if observed_rules != contract["rules_sha256"]:
        raise ValueError("direct WorkerPool observed rules do not match the logical contract")
    observed_capability = str(lane.get("observed_capability_binding_sha256") or "")
    if observed_capability != selection["capability_binding_sha256"]:
        raise ValueError(
            "direct WorkerPool observed capability binding does not match the logical contract"
        )
    stop_reason = str(lane.get("stop_reason") or "")
    if stop_reason != "EndTurn":
        raise ValueError("direct WorkerPool common acceptance requires EndTurn")
    result_sha256 = str(lane.get("result_text_sha256") or "")
    result_chars = int(lane.get("result_text_chars") or 0)
    session_id = str(lane.get("session_id") or "")
    lane_id = str(lane.get("lane_id") or "")
    run_id = str(lane.get("run_id") or "")
    if not session_id or not lane_id or not run_id:
        raise ValueError("direct WorkerPool session identity and lane lineage are required")
    schema_requested = lane.get("json_schema_requested") is True
    schema_valid = lane.get("schema_instance_valid") is True if schema_requested else True
    receipt = {
        "schema_version": ATTEMPT_RECEIPT_VERSION,
        "contract_sha256": logical_contract_sha256(contract),
        "consumer_id": GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
        "logical_operation_id": contract["logical_operation_id"],
        "work_key": contract["work_key"],
        "attempt": int(attempt),
        "observed": {
            "provider_id": selection["provider_id"],
            "profile_ref": selection["profile_ref"],
            "model_id": selected_model,
            "transport_id": GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
            "capability_binding_sha256": selection["capability_binding_sha256"],
            "rules_sha256": observed_rules,
            "runtime_version": runtime_version,
            "execution_location": GROK_DIRECT_WORKER_POOL_EXECUTION_LOCATION,
            "executor_id": run_id,
        },
        "terminal_state": "completed",
        "stop_reason": stop_reason,
        "output": {
            "format": "json_object" if lane.get("structured_output_present") is True else "text",
            "content_sha256": result_sha256,
            "chars": result_chars,
            "schema_sha256": contract["output_contract_sha256"],
            "schema_valid": schema_valid,
            "markers_ok": True,
            "substantive": result_chars > 0,
        },
        "invocations": [
            {
                "invocation": 1,
                "state": "accepted",
                "observed_model": selected_model,
                "stop_reason": stop_reason,
                "output_sha256": result_sha256,
                "output_chars": result_chars,
                "total_tokens": total_tokens,
            }
        ],
        "usage": {
            "invocation_count": 1,
            "total_tokens": total_tokens,
            "accepted_tokens": total_tokens,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
        "lineage": {
            "workflow_id": pool_id,
            "lane_id": lane_id,
            "parent_operation_id": contract["parent_operation_id"],
            "correlation_id": contract["correlation_id"],
            "session_id": session_id,
        },
        "provider_contract_version": provider_contract_version,
        "provider_evidence_ref": provider_evidence_ref,
        "provider_evidence_sha256": provider_evidence_sha256,
        "provider_evidence_valid": True,
        "replayed": False,
    }
    verdict = validate_attempt_receipt(
        contract,
        receipt,
        expected_consumer_id=GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
    )
    if not verdict.accepted:
        raise ValueError(
            "direct WorkerPool evidence did not satisfy the common execution receipt: "
            + ",".join(verdict.reason_codes)
        )
    return receipt


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
    session_model_evidence: Mapping[str, object],
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
    validate_grok_session_model_evidence(
        session_model_evidence,
        selected_model=selected_model,
        session_id=session_id,
    )
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
    "GROK_DIRECT_WORKER_POOL_CONSUMER_ID",
    "GROK_DIRECT_WORKER_POOL_CONTRACT_MODE",
    "GROK_DIRECT_WORKER_POOL_EXECUTION_LOCATION",
    "GROK_DIRECT_WORKER_POOL_TRANSPORT_ID",
    "GROK_CLI_POLICY_VERSION",
    "GROK_DOCKER_CONSUMER_ID",
    "GROK_DOCKER_EXECUTION_LOCATION",
    "GROK_DOCKER_ROUTE_ADAPTER_VERSION",
    "GROK_DOCKER_ROUTE_TRANSPORT_ID",
    "GROK_DOCKER_PACKAGE_CAPABILITY_POLICY",
    "GROK_PROFILE_REF",
    "GROK_TRANSPORT_ID",
    "build_grok_attempt_receipt",
    "build_grok_docker_route_adapter_binding",
    "build_grok_logical_contract",
    "build_direct_worker_pool_attempt_receipt",
    "build_direct_worker_pool_logical_contract",
    "direct_worker_pool_capability_binding",
    "direct_worker_pool_context_binding_sha256",
    "direct_worker_pool_output_contract",
    "expected_docker_grok_backend_models",
    "grok_docker_model_identity_binding",
    "validate_grok_session_model_evidence",
    "validate_grok_docker_route_adapter_binding",
    "validate_grok_route_selection_receipt",
]
