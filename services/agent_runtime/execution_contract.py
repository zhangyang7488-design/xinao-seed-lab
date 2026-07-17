"""Provider-neutral cross-seam execution contracts and receipts.

This module is intentionally deterministic.  It owns no scheduling, retries,
I/O, provider selection, or authorization.  Provider adapters must validate
their native evidence first and may only then translate it into this common
receipt shape.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

LOGICAL_CONTRACT_VERSION = "xinao.execution.logical_contract.v1"
ATTEMPT_RECEIPT_VERSION = "xinao.execution.attempt_receipt.v1"
CONSUMER_REGISTRY_VERSION = "xinao.execution.consumer_registry.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "timed_out"})
_INVOCATION_STATES = frozenset({"accepted", "rejected", "failed", "cancelled", "timed_out"})
_CONSUMER_STATUSES = frozenset({"complete", "adapting", "partial", "legacy", "out_of_scope"})


class ExecutionContractError(ValueError):
    """The common execution contract is malformed or internally inconsistent."""


@dataclass(frozen=True)
class ReceiptVerdict:
    accepted: bool
    reason_codes: tuple[str, ...]


def canonical_json_bytes(value: object) -> bytes:
    """Return the sole hashing representation for common execution records."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def artifact_json_bytes(value: object) -> bytes:
    """Return the stable on-disk JSON representation for evidence artifacts."""

    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutionContractError(f"{field} must be an object")
    return dict(value)


def _require_text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ExecutionContractError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise ExecutionContractError(f"{field} must be non-empty")
    return value


def _require_sha256(value: object, field: str, *, allow_empty: bool = False) -> str:
    text = _require_text(value, field, allow_empty=allow_empty)
    if not text and allow_empty:
        return text
    if not _SHA256_RE.fullmatch(text):
        raise ExecutionContractError(f"{field} must be a lowercase sha256")
    return text


def _require_nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionContractError(f"{field} must be a non-negative integer")
    return value


def validate_logical_contract(raw: Mapping[str, object]) -> dict[str, Any]:
    """Validate the stable logical operation selected before provider effects."""

    contract = _require_mapping(raw, "logical_contract")
    allowed = {
        "schema_version",
        "logical_operation_id",
        "work_key",
        "task_contract_ref",
        "parent_operation_id",
        "correlation_id",
        "input_sha256",
        "context_sha256",
        "rules_sha256",
        "output_contract_sha256",
        "selection",
        "effect_mode",
        "idempotency_key",
        "deadline",
        "cancellation_generation",
        "supersedes",
    }
    unknown = sorted(set(contract) - allowed)
    if unknown:
        raise ExecutionContractError(f"unsupported logical contract fields: {unknown}")
    required = allowed - {"supersedes"}
    missing = sorted(required - set(contract))
    if missing:
        raise ExecutionContractError(f"missing logical contract fields: {missing}")
    if contract.get("schema_version") != LOGICAL_CONTRACT_VERSION:
        raise ExecutionContractError("unsupported logical contract schema_version")
    for field in ("logical_operation_id", "work_key", "idempotency_key"):
        _require_text(contract.get(field), field)
    for field in ("task_contract_ref", "parent_operation_id", "correlation_id"):
        _require_text(contract.get(field), field, allow_empty=True)
    for field in ("input_sha256", "context_sha256", "rules_sha256", "output_contract_sha256"):
        _require_sha256(contract.get(field), field)
    supersedes = contract.get("supersedes")
    if supersedes is not None:
        _require_sha256(supersedes, "supersedes")

    selection = _require_mapping(contract.get("selection"), "selection")
    selection_fields = {
        "provider_id",
        "profile_ref",
        "model_id",
        "transport_id",
        "capability_binding_sha256",
    }
    if set(selection) != selection_fields:
        raise ExecutionContractError("selection fields do not match the v1 contract")
    for field in ("provider_id", "profile_ref", "model_id", "transport_id"):
        _require_text(selection.get(field), f"selection.{field}")
    _require_sha256(
        selection.get("capability_binding_sha256"),
        "selection.capability_binding_sha256",
    )

    if contract.get("effect_mode") not in {"read_only", "authorized_write"}:
        raise ExecutionContractError("effect_mode must be read_only or authorized_write")
    deadline = _require_mapping(contract.get("deadline"), "deadline")
    if set(deadline) != {"owner", "mode", "seconds"}:
        raise ExecutionContractError("deadline fields do not match the v1 contract")
    _require_text(deadline.get("owner"), "deadline.owner")
    if deadline.get("mode") not in {"relative_from_activity_start", "absolute"}:
        raise ExecutionContractError("unsupported deadline.mode")
    seconds = _require_nonnegative_int(deadline.get("seconds"), "deadline.seconds")
    if seconds <= 0:
        raise ExecutionContractError("deadline.seconds must be positive")
    _require_nonnegative_int(
        contract.get("cancellation_generation"),
        "cancellation_generation",
    )
    return contract


def logical_contract_sha256(raw: Mapping[str, object]) -> str:
    """Hash a logical contract; self-referential digest fields are forbidden."""

    if "contract_sha256" in raw:
        raise ExecutionContractError("logical contract must not contain its own digest")
    contract = validate_logical_contract(raw)
    return hashlib.sha256(canonical_json_bytes(contract)).hexdigest()


def _validate_usage(raw: object, field: str = "usage") -> dict[str, int]:
    usage = _require_mapping(raw, field)
    expected = {
        "invocation_count",
        "total_tokens",
        "accepted_tokens",
        "cancelled_tokens",
        "failed_tokens",
    }
    if set(usage) != expected:
        raise ExecutionContractError(f"{field} fields do not match the v1 receipt")
    normalized = {
        key: _require_nonnegative_int(usage.get(key), f"{field}.{key}") for key in expected
    }
    if normalized["total_tokens"] != (
        normalized["accepted_tokens"] + normalized["cancelled_tokens"] + normalized["failed_tokens"]
    ):
        raise ExecutionContractError(f"{field} token partition does not balance")
    return normalized


def _validate_attempt_shape(raw: Mapping[str, object]) -> dict[str, Any]:
    receipt = _require_mapping(raw, "attempt_receipt")
    required = {
        "schema_version",
        "contract_sha256",
        "consumer_id",
        "logical_operation_id",
        "work_key",
        "attempt",
        "observed",
        "terminal_state",
        "stop_reason",
        "output",
        "invocations",
        "usage",
        "lineage",
        "provider_contract_version",
        "provider_evidence_ref",
        "provider_evidence_sha256",
        "provider_evidence_valid",
        "replayed",
    }
    if set(receipt) != required:
        missing = sorted(required - set(receipt))
        unknown = sorted(set(receipt) - required)
        raise ExecutionContractError(
            f"attempt receipt fields mismatch; missing={missing}, unknown={unknown}"
        )
    if receipt.get("schema_version") != ATTEMPT_RECEIPT_VERSION:
        raise ExecutionContractError("unsupported attempt receipt schema_version")
    _require_sha256(receipt.get("contract_sha256"), "contract_sha256")
    for field in ("consumer_id", "logical_operation_id", "work_key", "provider_contract_version"):
        _require_text(receipt.get(field), field)
    attempt = _require_nonnegative_int(receipt.get("attempt"), "attempt")
    if attempt <= 0:
        raise ExecutionContractError("attempt must be positive")

    observed = _require_mapping(receipt.get("observed"), "observed")
    observed_fields = {
        "provider_id",
        "profile_ref",
        "model_id",
        "transport_id",
        "capability_binding_sha256",
        "rules_sha256",
        "runtime_version",
        "execution_location",
        "executor_id",
    }
    if set(observed) != observed_fields:
        raise ExecutionContractError("observed fields do not match the v1 receipt")
    for field in (
        "provider_id",
        "profile_ref",
        "model_id",
        "transport_id",
        "runtime_version",
        "execution_location",
        "executor_id",
    ):
        _require_text(observed.get(field), f"observed.{field}")
    _require_sha256(observed.get("capability_binding_sha256"), "observed.capability_binding_sha256")
    _require_sha256(observed.get("rules_sha256"), "observed.rules_sha256")

    terminal_state = receipt.get("terminal_state")
    if terminal_state not in _TERMINAL_STATES:
        raise ExecutionContractError("unsupported terminal_state")
    _require_text(receipt.get("stop_reason"), "stop_reason", allow_empty=True)

    output = _require_mapping(receipt.get("output"), "output")
    output_fields = {
        "format",
        "content_sha256",
        "chars",
        "schema_sha256",
        "schema_valid",
        "markers_ok",
        "substantive",
    }
    if set(output) != output_fields:
        raise ExecutionContractError("output fields do not match the v1 receipt")
    _require_text(output.get("format"), "output.format")
    _require_sha256(output.get("content_sha256"), "output.content_sha256")
    _require_sha256(output.get("schema_sha256"), "output.schema_sha256")
    _require_nonnegative_int(output.get("chars"), "output.chars")
    for field in ("schema_valid", "markers_ok", "substantive"):
        if not isinstance(output.get(field), bool):
            raise ExecutionContractError(f"output.{field} must be boolean")

    invocations = receipt.get("invocations")
    if not isinstance(invocations, list) or not invocations:
        raise ExecutionContractError("invocations must be a non-empty array")
    normalized_invocations: list[dict[str, Any]] = []
    invocation_ids: set[int] = set()
    for index, raw_invocation in enumerate(invocations):
        invocation = _require_mapping(raw_invocation, f"invocations[{index}]")
        fields = {
            "invocation",
            "state",
            "observed_model",
            "stop_reason",
            "output_sha256",
            "output_chars",
            "total_tokens",
        }
        if set(invocation) != fields:
            raise ExecutionContractError(f"invocations[{index}] fields do not match v1")
        invocation_id = _require_nonnegative_int(
            invocation.get("invocation"), f"invocations[{index}].invocation"
        )
        if invocation_id <= 0 or invocation_id in invocation_ids:
            raise ExecutionContractError("invocation ids must be unique positive integers")
        invocation_ids.add(invocation_id)
        if invocation.get("state") not in _INVOCATION_STATES:
            raise ExecutionContractError(f"invocations[{index}].state is unsupported")
        _require_text(invocation.get("observed_model"), f"invocations[{index}].observed_model")
        _require_text(
            invocation.get("stop_reason"),
            f"invocations[{index}].stop_reason",
            allow_empty=True,
        )
        _require_sha256(invocation.get("output_sha256"), f"invocations[{index}].output_sha256")
        _require_nonnegative_int(
            invocation.get("output_chars"), f"invocations[{index}].output_chars"
        )
        _require_nonnegative_int(
            invocation.get("total_tokens"), f"invocations[{index}].total_tokens"
        )
        normalized_invocations.append(invocation)

    usage = _validate_usage(receipt.get("usage"))
    if usage["invocation_count"] != len(normalized_invocations):
        raise ExecutionContractError("usage.invocation_count does not match invocations")
    if usage["total_tokens"] != sum(int(item["total_tokens"]) for item in normalized_invocations):
        raise ExecutionContractError("usage.total_tokens does not match invocation totals")
    class_sums = {
        "accepted_tokens": sum(
            int(item["total_tokens"])
            for item in normalized_invocations
            if item["state"] == "accepted"
        ),
        "cancelled_tokens": sum(
            int(item["total_tokens"])
            for item in normalized_invocations
            if item["state"] in {"cancelled", "timed_out"}
        ),
        "failed_tokens": sum(
            int(item["total_tokens"])
            for item in normalized_invocations
            if item["state"] in {"failed", "rejected"}
        ),
    }
    if any(usage[key] != value for key, value in class_sums.items()):
        raise ExecutionContractError("usage token classes do not match invocation states")

    lineage = _require_mapping(receipt.get("lineage"), "lineage")
    lineage_fields = {
        "workflow_id",
        "lane_id",
        "parent_operation_id",
        "correlation_id",
        "session_id",
    }
    if set(lineage) != lineage_fields:
        raise ExecutionContractError("lineage fields do not match the v1 receipt")
    for field in lineage_fields:
        _require_text(lineage.get(field), f"lineage.{field}", allow_empty=True)
    _require_text(receipt.get("provider_evidence_ref"), "provider_evidence_ref")
    _require_sha256(receipt.get("provider_evidence_sha256"), "provider_evidence_sha256")
    if not isinstance(receipt.get("provider_evidence_valid"), bool):
        raise ExecutionContractError("provider_evidence_valid must be boolean")
    if not isinstance(receipt.get("replayed"), bool):
        raise ExecutionContractError("replayed must be boolean")
    return receipt


def validate_attempt_receipt(
    contract: Mapping[str, object],
    receipt: Mapping[str, object],
    *,
    expected_consumer_id: str | None = None,
) -> ReceiptVerdict:
    """Validate a provider-approved receipt against the selected logical contract."""

    logical = validate_logical_contract(contract)
    attempt = _validate_attempt_shape(receipt)
    reasons: list[str] = []
    if attempt["contract_sha256"] != logical_contract_sha256(logical):
        reasons.append("CONTRACT_DIGEST_MISMATCH")
    if expected_consumer_id and attempt["consumer_id"] != expected_consumer_id:
        reasons.append("CONSUMER_MISMATCH")
    if attempt["logical_operation_id"] != logical["logical_operation_id"]:
        reasons.append("OPERATION_MISMATCH")
    if attempt["work_key"] != logical["work_key"]:
        reasons.append("WORK_KEY_MISMATCH")

    selection = logical["selection"]
    observed = attempt["observed"]
    for field in (
        "provider_id",
        "profile_ref",
        "model_id",
        "transport_id",
        "capability_binding_sha256",
    ):
        if observed[field] != selection[field]:
            reasons.append(f"OBSERVED_{field.upper()}_MISMATCH")
    if observed["rules_sha256"] != logical["rules_sha256"]:
        reasons.append("OBSERVED_RULES_MISMATCH")
    if any(item["observed_model"] != selection["model_id"] for item in attempt["invocations"]):
        reasons.append("INVOCATION_MODEL_MISMATCH")

    output = attempt["output"]
    usage = attempt["usage"]
    if output["schema_sha256"] != logical["output_contract_sha256"]:
        reasons.append("OUTPUT_CONTRACT_MISMATCH")
    if attempt["terminal_state"] != "completed":
        reasons.append("NON_COMPLETED_TERMINAL_STATE")
    if attempt["provider_evidence_valid"] is not True:
        reasons.append("PROVIDER_EVIDENCE_REJECTED")
    if usage["accepted_tokens"] <= 0:
        reasons.append("NO_ACCEPTED_TOKENS")
    if not any(item["state"] == "accepted" for item in attempt["invocations"]):
        reasons.append("NO_ACCEPTED_INVOCATION")
    if output["chars"] <= 0 or not output["substantive"]:
        reasons.append("NON_SUBSTANTIVE_OUTPUT")
    if not output["schema_valid"]:
        reasons.append("OUTPUT_SCHEMA_REJECTED")
    if not output["markers_ok"]:
        reasons.append("OUTPUT_MARKERS_REJECTED")
    return ReceiptVerdict(accepted=not reasons, reason_codes=tuple(dict.fromkeys(reasons)))


def aggregate_attempt_receipts(receipts: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Aggregate every receipt without dropping failed or cancelled token classes."""

    normalized = [_validate_attempt_shape(item) for item in receipts]
    return {
        "receipt_count": len(normalized),
        "invocation_count": sum(int(item["usage"]["invocation_count"]) for item in normalized),
        "total_tokens": sum(int(item["usage"]["total_tokens"]) for item in normalized),
        "accepted_tokens": sum(int(item["usage"]["accepted_tokens"]) for item in normalized),
        "cancelled_tokens": sum(int(item["usage"]["cancelled_tokens"]) for item in normalized),
        "failed_tokens": sum(int(item["usage"]["failed_tokens"]) for item in normalized),
    }


def reconcile_execution(
    contract: Mapping[str, object],
    receipts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Close only the latest accepted attempt; every other state remains unresolved."""

    logical = validate_logical_contract(contract)
    normalized = [_validate_attempt_shape(item) for item in receipts]
    if not normalized:
        return {"state": "unresolved", "reason_codes": ["NO_RECEIPTS"], "attempt": 0}
    attempts = [int(item["attempt"]) for item in normalized]
    if len(attempts) != len(set(attempts)):
        return {
            "state": "unresolved",
            "reason_codes": ["DUPLICATE_ATTEMPT"],
            "attempt": max(attempts),
        }
    latest = max(normalized, key=lambda item: int(item["attempt"]))
    verdict = validate_attempt_receipt(logical, latest)
    return {
        "state": "accepted" if verdict.accepted else "unresolved",
        "reason_codes": list(verdict.reason_codes),
        "attempt": int(latest["attempt"]),
        "contract_sha256": logical_contract_sha256(logical),
    }


def _registry_path(repo_root: Path, raw: object, field: str) -> Path:
    text = _require_text(raw, field)
    path = Path(text)
    return path if path.is_absolute() else repo_root / path


def _registry_evidence(
    raw: object,
    *,
    catalog: Mapping[str, object],
    field: str,
) -> dict[str, Any]:
    if isinstance(raw, str) and raw in catalog:
        evidence = _require_mapping(catalog[raw], f"evidence_catalog.{raw}")
        evidence["evidence_id"] = raw
        return evidence
    if isinstance(raw, str):
        return {"path": raw}
    return _require_mapping(raw, field)


def _verified_registry_json(
    raw: object,
    *,
    catalog: Mapping[str, object],
    repo_root: Path,
    field: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = _registry_evidence(raw, catalog=catalog, field=field)
    path = _registry_path(repo_root, evidence.get("path"), f"{field}.path")
    declared = _require_sha256(evidence.get("sha256"), f"{field}.sha256")
    if not path.is_file():
        raise ExecutionContractError(f"registered evidence missing: {path}")
    payload_raw = path.read_bytes()
    if hashlib.sha256(payload_raw).hexdigest() != declared:
        raise ExecutionContractError(f"registered evidence hash drifted: {path}")
    try:
        payload = json.loads(payload_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionContractError(f"registered evidence is not JSON: {path}") from exc
    return evidence, _require_mapping(payload, field)


def _registry_observed_models(payload: Mapping[str, object]) -> list[str]:
    model_usage = payload.get("modelUsage")
    if isinstance(model_usage, Mapping):
        return sorted(
            str(model)
            for model, stats in model_usage.items()
            if isinstance(stats, Mapping) and int(stats.get("modelCalls") or 0) > 0
        )
    observed = payload.get("observed_models")
    if isinstance(observed, list):
        return sorted(str(model) for model in observed if str(model))
    invocations = payload.get("cli_invocations")
    if isinstance(invocations, list):
        return sorted(
            {
                str(model)
                for invocation in invocations
                if isinstance(invocation, Mapping)
                for model in (
                    invocation.get("observed_models")
                    if isinstance(invocation.get("observed_models"), list)
                    else []
                )
                if str(model)
            }
        )
    return []


def _registry_timestamp(raw: object, field: str) -> datetime:
    text = _require_text(raw, field)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise ExecutionContractError(f"{field} must be an ISO-8601 timestamp") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def validate_consumer_registry(
    registry: Mapping[str, object],
    *,
    repo_root: Path,
) -> dict[str, object]:
    """Derive effective consumer status from source, hashes, and raw identity evidence."""

    data = _require_mapping(registry, "consumer_registry")
    if data.get("schema_version") != CONSUMER_REGISTRY_VERSION:
        raise ExecutionContractError("unsupported consumer registry schema_version")
    if data.get("logical_contract_version") != LOGICAL_CONTRACT_VERSION:
        raise ExecutionContractError("consumer registry logical contract version drifted")
    if data.get("attempt_receipt_version") != ATTEMPT_RECEIPT_VERSION:
        raise ExecutionContractError("consumer registry receipt version drifted")
    identity_binding_ref = _require_mapping(
        data.get("provider_identity_binding_contract"),
        "provider_identity_binding_contract",
    )
    if (
        identity_binding_ref.get("schema_version")
        != "xinao.execution.provider_identity_binding_ref.v1"
    ):
        raise ExecutionContractError("provider identity binding ref schema drifted")
    binding_source = _require_text(
        identity_binding_ref.get("authority_source_path"),
        "provider_identity_binding_contract.authority_source_path",
    )
    binding_entrypoint = _require_text(
        identity_binding_ref.get("authority_entrypoint"),
        "provider_identity_binding_contract.authority_entrypoint",
    )
    binding_scope = _require_text(
        identity_binding_ref.get("execution_scope"),
        "provider_identity_binding_contract.execution_scope",
    )
    binding_test = _require_text(
        identity_binding_ref.get("conformance_test"),
        "provider_identity_binding_contract.conformance_test",
    )
    productivity_evidence = identity_binding_ref.get("current_productivity_evidence")
    if not isinstance(productivity_evidence, list) or not productivity_evidence:
        raise ExecutionContractError(
            "provider identity binding requires current productivity evidence"
        )
    if binding_entrypoint != "grok_docker_model_identity_binding":
        raise ExecutionContractError("provider identity binding authority entrypoint drifted")
    if binding_scope != "docker:houtai-gongren":
        raise ExecutionContractError("provider identity binding execution scope drifted")
    if not _registry_path(repo_root, binding_source, "identity_binding.source").is_file():
        raise ExecutionContractError("provider identity binding authority source is missing")
    binding_test_path = binding_test.split("::", 1)[0]
    if not _registry_path(repo_root, binding_test_path, "identity_binding.test").is_file():
        raise ExecutionContractError("provider identity binding conformance test is missing")
    consumers = data.get("consumers")
    if not isinstance(consumers, list) or not consumers:
        raise ExecutionContractError("consumer registry must contain consumers")
    catalog = _require_mapping(data.get("evidence_catalog") or {}, "evidence_catalog")
    from services.agent_runtime.grok_execution_contract_adapter import (
        grok_docker_model_identity_binding,
    )

    composer_binding = grok_docker_model_identity_binding("grok-composer-2.5-fast")
    grok45_binding = grok_docker_model_identity_binding("grok-4.5")
    if not (
        composer_binding.get("allowed_backend_model_ids") == ["grok-composer-2.5-fast"]
        and composer_binding.get("capability_ledger") == "composer_exact_capability"
        and composer_binding.get("composer_completion_credit") is True
        and grok45_binding.get("capability_ledger") == "grok_45_productivity"
        and grok45_binding.get("composer_completion_credit") is False
    ):
        raise ExecutionContractError("provider identity binding ledger separation drifted")
    expected_grok45_backends = sorted(
        str(model) for model in grok45_binding.get("allowed_backend_model_ids") or []
    )
    if not expected_grok45_backends or len(expected_grok45_backends) != len(
        set(expected_grok45_backends)
    ):
        raise ExecutionContractError("Grok 4.5 backend identity binding is invalid")
    for index, evidence_ref in enumerate(productivity_evidence):
        field = f"provider_identity_binding_contract.current_productivity_evidence[{index}]"
        evidence, payload = _verified_registry_json(
            evidence_ref,
            catalog=catalog,
            repo_root=repo_root,
            field=field,
        )
        raw_refs = evidence.get("raw_identity_evidence")
        if not isinstance(raw_refs, list) or not raw_refs:
            raise ExecutionContractError(f"{field} lacks raw_identity_evidence")
        raw_models: set[str] = set()
        for raw_index, raw_ref in enumerate(raw_refs):
            _, raw_payload = _verified_registry_json(
                raw_ref,
                catalog=catalog,
                repo_root=repo_root,
                field=f"{field}.raw_identity_evidence[{raw_index}]",
            )
            raw_models.update(_registry_observed_models(raw_payload))
        declared_models = sorted(
            str(model)
            for model in (
                evidence.get("observed_models")
                if isinstance(evidence.get("observed_models"), list)
                else []
            )
        )
        payload_models = _registry_observed_models(payload)
        if not (
            evidence.get("requested_model") == "grok-4.5"
            and evidence.get("capability_ledger") == "grok_45_productivity"
            and evidence.get("composer_completion_credit") is False
            and evidence.get("completion_claim_allowed") is True
            and declared_models == expected_grok45_backends
            and sorted(raw_models) == expected_grok45_backends
            and sorted(payload_models) == expected_grok45_backends
        ):
            raise ExecutionContractError(
                f"{field} does not prove the current Grok 4.5 productivity identity"
            )
    seen: set[str] = set()
    reports: list[dict[str, object]] = []
    for raw in consumers:
        item = _require_mapping(raw, "consumer")
        consumer_id = _require_text(item.get("consumer_id"), "consumer.consumer_id")
        if consumer_id in seen:
            raise ExecutionContractError(f"duplicate consumer_id: {consumer_id}")
        seen.add(consumer_id)
        status = item.get("status")
        if status not in _CONSUMER_STATUSES:
            raise ExecutionContractError(f"unsupported status for {consumer_id}")
        conformance_status = str(item.get("conformance_status") or status)
        if conformance_status not in _CONSUMER_STATUSES:
            raise ExecutionContractError(f"unsupported conformance_status for {consumer_id}")
        source_path = _require_text(item.get("source_path"), "consumer.source_path")
        _require_text(item.get("entrypoint"), "consumer.entrypoint")
        _require_text(item.get("role"), "consumer.role")
        _require_text(item.get("contract_mode"), "consumer.contract_mode")
        _require_text(item.get("status_reason"), "consumer.status_reason")
        if not isinstance(item.get("writes_effects"), bool):
            raise ExecutionContractError(f"writes_effects must be boolean for {consumer_id}")
        tests = item.get("conformance_tests")
        replay = item.get("replay_evidence")
        canaries = item.get("fresh_canary_evidence")
        current_positive = item.get("current_positive_canary_evidence") or []
        superseded = item.get("superseded_evidence") or []
        negative = item.get("negative_canary_evidence") or []
        blocking = item.get("blocking_evidence") or []
        for field, value in (
            ("conformance_tests", tests),
            ("replay_evidence", replay),
            ("fresh_canary_evidence", canaries),
            ("current_positive_canary_evidence", current_positive),
            ("superseded_evidence", superseded),
            ("negative_canary_evidence", negative),
            ("blocking_evidence", blocking),
        ):
            if not isinstance(value, list):
                raise ExecutionContractError(f"{field} must be an array for {consumer_id}")
        exists = _registry_path(repo_root, source_path, "consumer.source_path").is_file()
        if status != "out_of_scope" and not exists:
            raise ExecutionContractError(
                f"registered source missing for {consumer_id}: {source_path}"
            )
        reason_codes: list[str] = []
        test_files_exist = bool(tests)
        for index, selector in enumerate(tests):
            selector_text = _require_text(selector, f"{consumer_id}.conformance_tests[{index}]")
            selector_path = selector_text.split("::", 1)[0]
            if not _registry_path(repo_root, selector_path, "conformance_test.path").is_file():
                test_files_exist = False
        if conformance_status == "complete" and not test_files_exist:
            reason_codes.append("CONFORMANCE_EVIDENCE_MISSING")

        evidence_files_exist = True
        replay_valid = bool(replay)
        for index, evidence_ref in enumerate(replay):
            try:
                _verified_registry_json(
                    evidence_ref,
                    catalog=catalog,
                    repo_root=repo_root,
                    field=f"{consumer_id}.replay_evidence[{index}]",
                )
            except ExecutionContractError:
                replay_valid = False
                evidence_files_exist = False
        if not replay_valid and item.get("completion_claim") is not None:
            reason_codes.append("REPLAY_EVIDENCE_INVALID")

        for index, evidence_ref in enumerate(superseded):
            try:
                _verified_registry_json(
                    evidence_ref,
                    catalog=catalog,
                    repo_root=repo_root,
                    field=f"{consumer_id}.superseded_evidence[{index}]",
                )
            except ExecutionContractError:
                evidence_files_exist = False
                reason_codes.append("SUPERSEDED_EVIDENCE_INVALID")

        completion_claim = item.get("completion_claim")
        completion_claim_allowed = False
        if completion_claim is not None:
            claim = _require_mapping(completion_claim, f"{consumer_id}.completion_claim")
            _require_text(claim.get("ledger"), f"{consumer_id}.completion_claim.ledger")
            requested_model = _require_text(
                claim.get("requested_model"),
                f"{consumer_id}.completion_claim.requested_model",
            )
            allowed_raw = claim.get("allowed_observed_models")
            if not isinstance(allowed_raw, list) or not allowed_raw:
                raise ExecutionContractError(
                    f"allowed_observed_models must be a non-empty array for {consumer_id}"
                )
            allowed_models = sorted(
                _require_text(value, f"{consumer_id}.allowed_observed_models")
                for value in allowed_raw
            )
            positive_times: list[datetime] = []
            for index, evidence_ref in enumerate(current_positive):
                field = f"{consumer_id}.current_positive_canary_evidence[{index}]"
                try:
                    evidence, _ = _verified_registry_json(
                        evidence_ref,
                        catalog=catalog,
                        repo_root=repo_root,
                        field=field,
                    )
                    raw_refs = evidence.get("raw_identity_evidence")
                    if not isinstance(raw_refs, list) or not raw_refs:
                        raise ExecutionContractError(f"{field} lacks raw_identity_evidence")
                    raw_models: set[str] = set()
                    for raw_index, raw_ref in enumerate(raw_refs):
                        _, raw_payload = _verified_registry_json(
                            raw_ref,
                            catalog=catalog,
                            repo_root=repo_root,
                            field=f"{field}.raw_identity_evidence[{raw_index}]",
                        )
                        raw_models.update(_registry_observed_models(raw_payload))
                    declared_models = sorted(
                        str(model)
                        for model in (
                            evidence.get("observed_models")
                            if isinstance(evidence.get("observed_models"), list)
                            else []
                        )
                    )
                    if (
                        evidence.get("completion_claim_allowed") is not True
                        or str(evidence.get("requested_model") or "") != requested_model
                        or sorted(raw_models) != allowed_models
                        or declared_models != allowed_models
                    ):
                        raise ExecutionContractError(f"{field} does not prove exact model identity")
                    positive_times.append(
                        _registry_timestamp(evidence.get("observed_at"), f"{field}.observed_at")
                    )
                except ExecutionContractError:
                    evidence_files_exist = False
            if not positive_times:
                reason_codes.append("CURRENT_POSITIVE_CANARY_MISSING")

            negative_times: list[datetime] = []
            negative_ids: set[str] = set()
            for index, evidence_ref in enumerate(negative):
                field = f"{consumer_id}.negative_canary_evidence[{index}]"
                try:
                    evidence, payload = _verified_registry_json(
                        evidence_ref,
                        catalog=catalog,
                        repo_root=repo_root,
                        field=field,
                    )
                    observed_models = _registry_observed_models(payload) or sorted(
                        str(model)
                        for model in (
                            evidence.get("observed_models")
                            if isinstance(evidence.get("observed_models"), list)
                            else []
                        )
                    )
                    payload_requested = str(
                        payload.get("model") or payload.get("requested_model") or ""
                    )
                    if payload_requested and payload_requested != requested_model:
                        raise ExecutionContractError(f"{field} requested model drifted")
                    if sorted(observed_models) == allowed_models:
                        raise ExecutionContractError(f"{field} is not negative identity evidence")
                    negative_times.append(
                        _registry_timestamp(evidence.get("observed_at"), f"{field}.observed_at")
                    )
                    if evidence.get("evidence_id"):
                        negative_ids.add(str(evidence["evidence_id"]))
                except ExecutionContractError:
                    evidence_files_exist = False
                    reason_codes.append("NEGATIVE_EVIDENCE_INVALID")

            for index, blocker_raw in enumerate(blocking):
                blocker = _require_mapping(blocker_raw, f"{consumer_id}.blocking_evidence[{index}]")
                evidence_id = _require_text(
                    blocker.get("evidence_id"), f"{consumer_id}.blocking_evidence.evidence_id"
                )
                _require_text(
                    blocker.get("reason_code"), f"{consumer_id}.blocking_evidence.reason_code"
                )
                if evidence_id not in negative_ids:
                    reason_codes.append("BLOCKING_EVIDENCE_UNBOUND")

            latest_positive = max(positive_times) if positive_times else None
            latest_negative = max(negative_times) if negative_times else None
            newer_blocker = latest_negative is not None and (
                latest_positive is None or latest_negative >= latest_positive
            )
            if newer_blocker:
                reason_codes.append("EXACT_MODEL_IDENTITY_DRIFT")
            completion_claim_allowed = bool(
                conformance_status == "complete"
                and test_files_exist
                and replay_valid
                and positive_times
                and not newer_blocker
            )
            effective_status = "complete" if completion_claim_allowed else "partial"
        else:
            effective_status = str(status)
            if status == "complete":
                reason_codes.append("COMPLETION_CLAIM_MISSING")
                effective_status = "partial"

        if status == "complete" and effective_status != "complete":
            reasons = ",".join(dict.fromkeys(reason_codes)) or "UNEARNED_COMPLETE"
            raise ExecutionContractError(
                f"declared complete is not earned for {consumer_id}: {reasons}"
            )
        reports.append(
            {
                "consumer_id": consumer_id,
                "status": status,
                "declared_status": status,
                "effective_status": effective_status,
                "conformance_status": conformance_status,
                "completion_claim_allowed": completion_claim_allowed,
                "reason_codes": list(dict.fromkeys(reason_codes)),
                "source_exists": exists,
                "test_files_exist": test_files_exist,
                "evidence_files_exist": evidence_files_exist,
            }
        )
    return {
        "ok": True,
        "provider_identity_binding_contract_ok": True,
        "consumer_count": len(reports),
        "consumers": reports,
    }


__all__ = [
    "ATTEMPT_RECEIPT_VERSION",
    "CONSUMER_REGISTRY_VERSION",
    "ExecutionContractError",
    "LOGICAL_CONTRACT_VERSION",
    "ReceiptVerdict",
    "aggregate_attempt_receipts",
    "canonical_json_bytes",
    "logical_contract_sha256",
    "reconcile_execution",
    "validate_attempt_receipt",
    "validate_consumer_registry",
    "validate_logical_contract",
]
