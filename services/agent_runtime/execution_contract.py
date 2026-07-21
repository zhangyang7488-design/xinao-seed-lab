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
COMMON_DISPATCH_DISPOSITION_VERSION = "xinao.execution.common_dispatch_disposition.v1"

IDENTICAL_WORK_DISPOSITIONS = frozenset(
    {
        "LIVE_IDENTICAL",
        "ACCEPTED_IDENTICAL_REUSE",
        "TERMINAL_FAILED_NEW_PROOF",
        "SAME_PIN_NO_NEW_PROOF",
    }
)
EXECUTION_PHASES = frozenset({"EXPLORE", "CONSTRUCT", "VERIFY", "LAND"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "timed_out"})
_INVOCATION_STATES = frozenset({"accepted", "rejected", "failed", "cancelled", "timed_out"})
_CONSUMER_STATUSES = frozenset(
    {
        "complete",
        "boundary_verified_non_parent_owner",
        "adapting",
        "partial",
        "legacy",
        "out_of_scope",
    }
)


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


def build_common_receipt_binding(
    logical_contract: Mapping[str, object],
    *,
    lane_id: str,
    attempt_receipt_sha256: str,
    attempt_receipt: Mapping[str, object] | None = None,
    work_key: str = "",
    package_manifest_sha256: str = "",
) -> dict[str, str]:
    """Build the one producer/consumer receipt-set member representation."""

    contract = validate_logical_contract(logical_contract)
    binding = {
        "lane_id": _require_text(lane_id, "lane_id"),
        "contract_sha256": logical_contract_sha256(contract),
        "attempt_receipt_sha256": _require_sha256(
            attempt_receipt_sha256,
            "attempt_receipt_sha256",
        ),
    }
    package_bound = bool(work_key or package_manifest_sha256)
    if package_bound:
        bound_work_key = _require_text(work_key, "work_key")
        bound_lane_id = binding["lane_id"]
        bound_manifest_sha256 = _require_sha256(
            package_manifest_sha256,
            "package_manifest_sha256",
        )
        if bound_work_key != contract["work_key"]:
            raise ExecutionContractError("receipt binding work_key disagrees with logical contract")
        task_contract_ref = _require_text(
            contract.get("task_contract_ref"),
            "task_contract_ref",
        )
        _, separator, task_contract_sha256 = task_contract_ref.rpartition("#sha256=")
        if not separator or not _SHA256_RE.fullmatch(task_contract_sha256):
            raise ExecutionContractError(
                "package-bound task_contract_ref must carry one lowercase sha256"
            )
        if task_contract_sha256 != bound_manifest_sha256:
            raise ExecutionContractError(
                "task_contract_ref disagrees with package_manifest_sha256"
            )
        if attempt_receipt is None:
            raise ExecutionContractError("package-bound receipt binding requires attempt_receipt")
        attempt = _validate_attempt_shape(attempt_receipt)
        lineage = _require_mapping(attempt.get("lineage"), "lineage")
        if lineage.get("lane_id") != bound_lane_id:
            raise ExecutionContractError("attempt receipt lineage lane_id drifted")
        if attempt.get("work_key") != bound_work_key:
            raise ExecutionContractError("attempt receipt work_key drifted")
        binding.update(
            {
                "work_key": bound_work_key,
                "package_manifest_sha256": bound_manifest_sha256,
            }
        )
    return binding


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


def _identical_work_pin_preimage(
    contract: Mapping[str, object],
    *,
    subject_manifest_sha256: str,
) -> dict[str, object]:
    logical = validate_logical_contract(contract)
    subject_sha = _require_sha256(subject_manifest_sha256, "subject_manifest_sha256")
    return {
        "work_key": logical["work_key"],
        "frozen_hashes": {
            "input_sha256": logical["input_sha256"],
            "context_sha256": logical["context_sha256"],
            "rules_sha256": logical["rules_sha256"],
            "output_contract_sha256": logical["output_contract_sha256"],
        },
        "subject_manifest_sha256": subject_sha,
        "capability_binding_sha256": logical["selection"]["capability_binding_sha256"],
    }


def identical_work_pin_sha256(
    contract: Mapping[str, object],
    *,
    subject_manifest_sha256: str,
) -> str:
    """Hash the complete immutable identity used only for dispatch dedupe.

    The pin is deliberately narrower than the logical contract digest but never
    collapses the four frozen contract hashes, the subject manifest, or the
    selected capability binding. Reuse still requires validating the prior
    attempt receipt against the *current* full logical contract.
    """

    preimage = _identical_work_pin_preimage(
        contract,
        subject_manifest_sha256=subject_manifest_sha256,
    )
    return hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()


def _derived_classification(
    disposition: str,
    *,
    pin_sha256: str,
    reason_codes: Sequence[str],
    attempt_receipt_sha256: str = "",
) -> dict[str, object]:
    if disposition not in IDENTICAL_WORK_DISPOSITIONS:
        raise ExecutionContractError(f"unsupported identical-work disposition: {disposition}")
    return {
        "disposition": disposition,
        "identical_work_pin_sha256": pin_sha256,
        "dispatch_allowed": disposition == "TERMINAL_FAILED_NEW_PROOF",
        "skip_execution": disposition == "ACCEPTED_IDENTICAL_REUSE",
        "authority": False,
        "completion_claim_allowed": False,
        "attempt_receipt_sha256": attempt_receipt_sha256,
        "reason_codes": list(dict.fromkeys(str(value) for value in reason_codes if str(value))),
    }


def classify_identical_work_disposition(
    contract: Mapping[str, object],
    *,
    subject_manifest_sha256: str,
    live_pins: Sequence[str] = (),
    prior_accepted: Sequence[Mapping[str, object]] = (),
    prior_terminal_failed: Sequence[Mapping[str, object]] = (),
    new_proof_sha256: str = "",
) -> dict[str, object] | None:
    """Classify caller-supplied identical history without reading state or dispatching.

    ``None`` means there is no identical history and the ordinary first-dispatch
    path remains responsible. This helper never owns retries or acceptance.
    """

    logical = validate_logical_contract(contract)
    pin = identical_work_pin_sha256(
        logical,
        subject_manifest_sha256=subject_manifest_sha256,
    )
    normalized_live = {
        _require_sha256(value, f"live_pins[{index}]") for index, value in enumerate(live_pins)
    }
    if pin in normalized_live:
        return _derived_classification(
            "LIVE_IDENTICAL",
            pin_sha256=pin,
            reason_codes=("IDENTICAL_PIN_ALREADY_LIVE",),
        )

    same_pin_seen = False
    invalid_accept_reasons: list[str] = []
    for index, raw in enumerate(prior_accepted):
        record = _require_mapping(raw, f"prior_accepted[{index}]")
        prior_contract = _require_mapping(
            record.get("logical_contract"),
            f"prior_accepted[{index}].logical_contract",
        )
        prior_subject = _require_sha256(
            record.get("subject_manifest_sha256"),
            f"prior_accepted[{index}].subject_manifest_sha256",
        )
        prior_pin = identical_work_pin_sha256(
            prior_contract,
            subject_manifest_sha256=prior_subject,
        )
        if prior_pin != pin:
            continue
        same_pin_seen = True
        receipt = _require_mapping(
            record.get("attempt_receipt"),
            f"prior_accepted[{index}].attempt_receipt",
        )
        try:
            verdict = validate_attempt_receipt(logical, receipt)
        except ExecutionContractError as exc:
            invalid_accept_reasons.append(f"PRIOR_RECEIPT_INVALID:{exc}")
            continue
        if verdict.accepted:
            receipt_sha = hashlib.sha256(artifact_json_bytes(receipt)).hexdigest()
            return _derived_classification(
                "ACCEPTED_IDENTICAL_REUSE",
                pin_sha256=pin,
                reason_codes=("CURRENT_CONTRACT_VALIDATED_PRIOR_ACCEPT",),
                attempt_receipt_sha256=receipt_sha,
            )
        invalid_accept_reasons.extend(verdict.reason_codes)

    failed_proofs: set[str] = set()
    failed_pin_seen = False
    for index, raw in enumerate(prior_terminal_failed):
        record = _require_mapping(raw, f"prior_terminal_failed[{index}]")
        prior_pin = _require_sha256(
            record.get("identical_work_pin_sha256"),
            f"prior_terminal_failed[{index}].identical_work_pin_sha256",
        )
        terminal_state = _require_text(
            record.get("terminal_state"),
            f"prior_terminal_failed[{index}].terminal_state",
        )
        if terminal_state not in {"failed", "cancelled", "timed_out", "rejected"}:
            raise ExecutionContractError(
                f"prior_terminal_failed[{index}].terminal_state is not a failure"
            )
        proof = _require_sha256(
            record.get("proof_sha256"),
            f"prior_terminal_failed[{index}].proof_sha256",
        )
        if prior_pin == pin:
            same_pin_seen = True
            failed_pin_seen = True
            failed_proofs.add(proof)

    new_proof = _require_sha256(new_proof_sha256, "new_proof_sha256") if new_proof_sha256 else ""
    if failed_pin_seen and new_proof and new_proof not in failed_proofs:
        return _derived_classification(
            "TERMINAL_FAILED_NEW_PROOF",
            pin_sha256=pin,
            reason_codes=("NOVEL_FAILURE_PROOF_BOUND",),
        )
    if same_pin_seen:
        reasons = invalid_accept_reasons or [
            "FAILED_PIN_HAS_NO_NOVEL_PROOF"
            if failed_pin_seen
            else "IDENTICAL_PIN_HAS_NO_CURRENT_ACCEPT"
        ]
        return _derived_classification(
            "SAME_PIN_NO_NEW_PROOF",
            pin_sha256=pin,
            reason_codes=reasons,
        )
    return None


def _normalize_write_domain(value: object, field: str) -> str:
    text = _require_text(value, field).strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    normalized = text.rstrip("/").casefold()
    if not normalized:
        raise ExecutionContractError(f"{field} must identify a write domain")
    return normalized


def _normalize_execution_unit(raw: Mapping[str, object], field: str) -> dict[str, object]:
    unit = _require_mapping(raw, field)
    unit_id = _require_text(unit.get("unit_id"), f"{field}.unit_id")
    phase = _require_text(unit.get("phase"), f"{field}.phase")
    if phase not in EXECUTION_PHASES:
        raise ExecutionContractError(f"{field}.phase is unsupported")
    domains_raw = unit.get("write_domains")
    depends_raw = unit.get("depends_on")
    if not isinstance(domains_raw, list):
        raise ExecutionContractError(f"{field}.write_domains must be an array")
    if not isinstance(depends_raw, list):
        raise ExecutionContractError(f"{field}.depends_on must be an array")
    domains = {
        _normalize_write_domain(value, f"{field}.write_domains[{index}]")
        for index, value in enumerate(domains_raw)
    }
    if phase == "LAND" and not domains:
        raise ExecutionContractError(f"{field}.LAND requires at least one write domain")
    depends = {
        _require_text(value, f"{field}.depends_on[{index}]")
        for index, value in enumerate(depends_raw)
    }
    return {
        "unit_id": unit_id,
        "phase": phase,
        "write_domains": domains,
        "depends_on": depends,
    }


def may_run_concurrent(
    unit_a: Mapping[str, object],
    unit_b: Mapping[str, object],
) -> bool:
    """Allow concurrency unless a dependency or normalized write-domain fence overlaps."""

    left = _normalize_execution_unit(unit_a, "unit_a")
    right = _normalize_execution_unit(unit_b, "unit_b")
    if left["unit_id"] == right["unit_id"]:
        return False
    if left["unit_id"] in right["depends_on"] or right["unit_id"] in left["depends_on"]:
        return False
    return not bool(left["write_domains"] & right["write_domains"])


def build_common_dispatch_disposition(
    contract: Mapping[str, object],
    *,
    subject_manifest_sha256: str,
    phase: str,
    write_domains: Sequence[str],
    depends_on: Sequence[str],
    classification: Mapping[str, object] | None,
) -> dict[str, object]:
    """Bind one derived dedupe/fence record to the common authority objects."""

    logical = validate_logical_contract(contract)
    if classification is None:
        raise ExecutionContractError("classification is required for an identical-work disposition")
    classified = _require_mapping(classification, "classification")
    disposition = _require_text(classified.get("disposition"), "classification.disposition")
    if disposition not in IDENTICAL_WORK_DISPOSITIONS:
        raise ExecutionContractError("classification disposition is unsupported")
    pin = identical_work_pin_sha256(
        logical,
        subject_manifest_sha256=subject_manifest_sha256,
    )
    if classified.get("identical_work_pin_sha256") != pin:
        raise ExecutionContractError("classification pin does not match the current contract")
    unit = _normalize_execution_unit(
        {
            "unit_id": logical["logical_operation_id"],
            "phase": phase,
            "write_domains": list(write_domains),
            "depends_on": list(depends_on),
        },
        "dispatch_unit",
    )
    preimage = _identical_work_pin_preimage(
        logical,
        subject_manifest_sha256=subject_manifest_sha256,
    )
    return {
        "schema_version": COMMON_DISPATCH_DISPOSITION_VERSION,
        "authority": False,
        "completion_claim_allowed": False,
        "contract_sha256": logical_contract_sha256(logical),
        "work_key": logical["work_key"],
        "logical_operation_id": logical["logical_operation_id"],
        "identical_work_pin_sha256": pin,
        **preimage,
        "phase": unit["phase"],
        "write_domains": sorted(unit["write_domains"]),
        "depends_on": sorted(unit["depends_on"]),
        "disposition": disposition,
        "dispatch_allowed": classified.get("dispatch_allowed") is True,
        "skip_execution": classified.get("skip_execution") is True,
        "attempt_receipt_sha256": str(classified.get("attempt_receipt_sha256") or ""),
        "reason_codes": list(classified.get("reason_codes") or []),
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


def _registry_session_ids(payload: Mapping[str, object]) -> set[str]:
    return {
        str(payload.get(key) or "").strip()
        for key in ("sessionId", "session_id", "backendSessionId")
        if str(payload.get(key) or "").strip()
    }


def _validate_registry_session_identity(
    evidence: Mapping[str, object],
    *,
    selected_model: str,
    expected_session_ids: set[str],
    catalog: Mapping[str, object],
    repo_root: Path,
    field: str,
) -> set[str]:
    from services.agent_runtime.grok_execution_contract_adapter import (
        validate_grok_session_model_evidence,
    )

    refs = evidence.get("session_identity_evidence")
    if not isinstance(refs, list) or not refs:
        raise ExecutionContractError(f"{field} lacks session_identity_evidence")
    observed_session_ids: set[str] = set()
    for index, raw_ref in enumerate(refs):
        _, payload = _verified_registry_json(
            raw_ref,
            catalog=catalog,
            repo_root=repo_root,
            field=f"{field}.session_identity_evidence[{index}]",
        )
        try:
            validate_grok_session_model_evidence(
                payload,
                selected_model=selected_model,
                session_id=str(payload.get("backendSessionId") or ""),
            )
        except ValueError as exc:
            raise ExecutionContractError(
                f"{field} has invalid session model identity evidence"
            ) from exc
        observed_session_ids.update(_registry_session_ids(payload))
    if not expected_session_ids or observed_session_ids != expected_session_ids:
        raise ExecutionContractError(
            f"{field} session identity is not bound to the raw provider execution"
        )
    return observed_session_ids


def _validate_registry_terminal_receipts(
    evidence: Mapping[str, object],
    *,
    selected_model: str,
    expected_session_ids: set[str],
    catalog: Mapping[str, object],
    repo_root: Path,
    field: str,
) -> set[str]:
    refs = evidence.get("terminal_receipt_evidence")
    if not isinstance(refs, list) or not refs:
        raise ExecutionContractError(f"{field} lacks terminal_receipt_evidence")
    receipt_session_ids: set[str] = set()
    for index, raw_ref in enumerate(refs):
        _, payload = _verified_registry_json(
            raw_ref,
            catalog=catalog,
            repo_root=repo_root,
            field=f"{field}.terminal_receipt_evidence[{index}]",
        )
        observed = _require_mapping(payload.get("observed"), f"{field}.receipt.observed")
        output = _require_mapping(payload.get("output"), f"{field}.receipt.output")
        usage = _require_mapping(payload.get("usage"), f"{field}.receipt.usage")
        lineage = _require_mapping(payload.get("lineage"), f"{field}.receipt.lineage")
        invocations = payload.get("invocations")
        session_id = _require_text(lineage.get("session_id"), f"{field}.receipt.session_id")
        receipt_session_ids.add(session_id)
        final_invocation = (
            _require_mapping(invocations[-1], f"{field}.receipt.final_invocation")
            if isinstance(invocations, list) and invocations
            else {}
        )
        receipt_ok = bool(
            payload.get("schema_version") == ATTEMPT_RECEIPT_VERSION
            and payload.get("terminal_state") == "completed"
            and str(payload.get("stop_reason") or "").lower() == "endturn"
            and payload.get("provider_evidence_valid") is True
            and observed.get("model_id") == selected_model
            and output.get("substantive") is True
            and output.get("markers_ok") is True
            and output.get("schema_valid") is True
            and int(output.get("chars") or 0) >= 256
            and isinstance(output.get("content_sha256"), str)
            and _SHA256_RE.fullmatch(str(output.get("content_sha256") or ""))
            and int(usage.get("invocation_count") or 0) >= 1
            and int(usage.get("accepted_tokens") or 0) > 0
            and int(usage.get("total_tokens") or 0) >= int(usage.get("accepted_tokens") or 0)
            and final_invocation.get("state") == "accepted"
            and str(final_invocation.get("stop_reason") or "").lower() == "endturn"
            and int(final_invocation.get("total_tokens") or 0) > 0
            and int(final_invocation.get("output_chars") or 0) >= 256
        )
        if not receipt_ok:
            raise ExecutionContractError(
                f"{field} terminal receipt does not prove accepted substantive completion"
            )
    if not expected_session_ids or receipt_session_ids != expected_session_ids:
        raise ExecutionContractError(
            f"{field} terminal receipt is not bound to the raw provider execution"
        )
    return receipt_session_ids


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
        composer_binding.get("allowed_backend_model_ids") == ["grok-4.5-build"]
        and composer_binding.get("session_model_id") == "grok-composer-2.5-fast"
        and composer_binding.get("session_evidence_required") is True
        and composer_binding.get("capability_ledger") == "composer_exact_capability"
        and composer_binding.get("composer_completion_credit") is True
        and grok45_binding.get("allowed_backend_model_ids") == ["grok-4.5-build"]
        and grok45_binding.get("session_model_id") == "grok-4.5"
        and grok45_binding.get("session_evidence_required") is True
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
        raw_session_ids: set[str] = set()
        for raw_index, raw_ref in enumerate(raw_refs):
            _, raw_payload = _verified_registry_json(
                raw_ref,
                catalog=catalog,
                repo_root=repo_root,
                field=f"{field}.raw_identity_evidence[{raw_index}]",
            )
            raw_models.update(_registry_observed_models(raw_payload))
            raw_session_ids.update(_registry_session_ids(raw_payload))
        _validate_registry_session_identity(
            evidence,
            selected_model="grok-4.5",
            expected_session_ids=raw_session_ids,
            catalog=catalog,
            repo_root=repo_root,
            field=field,
        )
        _validate_registry_terminal_receipts(
            evidence,
            selected_model="grok-4.5",
            expected_session_ids=raw_session_ids,
            catalog=catalog,
            repo_root=repo_root,
            field=field,
        )
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
        parent_completion_authority = item.get("parent_completion_authority")
        if status == "boundary_verified_non_parent_owner":
            if parent_completion_authority is not False:
                raise ExecutionContractError(
                    f"boundary verified consumer must explicitly deny parent authority: {consumer_id}"
                )
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
        replay_times: list[datetime] = []
        for index, evidence_ref in enumerate(replay):
            try:
                evidence, _ = _verified_registry_json(
                    evidence_ref,
                    catalog=catalog,
                    repo_root=repo_root,
                    field=f"{consumer_id}.replay_evidence[{index}]",
                )
                replay_times.append(
                    _registry_timestamp(
                        evidence.get("observed_at"),
                        f"{consumer_id}.replay_evidence[{index}].observed_at",
                    )
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
            try:
                claim_binding = grok_docker_model_identity_binding(requested_model)
            except ValueError as exc:
                raise ExecutionContractError(
                    f"unsupported completion claim model for {consumer_id}"
                ) from exc
            expected_claim_models = sorted(
                str(model) for model in claim_binding.get("allowed_backend_model_ids") or []
            )
            if (
                claim.get("ledger") != claim_binding.get("capability_ledger")
                or allowed_models != expected_claim_models
                or claim_binding.get("session_evidence_required") is not True
            ):
                raise ExecutionContractError(
                    f"completion claim identity binding drifted for {consumer_id}"
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
                    raw_session_ids: set[str] = set()
                    for raw_index, raw_ref in enumerate(raw_refs):
                        _, raw_payload = _verified_registry_json(
                            raw_ref,
                            catalog=catalog,
                            repo_root=repo_root,
                            field=f"{field}.raw_identity_evidence[{raw_index}]",
                        )
                        raw_models.update(_registry_observed_models(raw_payload))
                        raw_session_ids.update(_registry_session_ids(raw_payload))
                    _validate_registry_session_identity(
                        evidence,
                        selected_model=requested_model,
                        expected_session_ids=raw_session_ids,
                        catalog=catalog,
                        repo_root=repo_root,
                        field=field,
                    )
                    _validate_registry_terminal_receipts(
                        evidence,
                        selected_model=requested_model,
                        expected_session_ids=raw_session_ids,
                        catalog=catalog,
                        repo_root=repo_root,
                        field=field,
                    )
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
            latest_replay = max(replay_times) if replay_times else None
            newer_blocker = latest_negative is not None and (
                latest_positive is None or latest_negative >= latest_positive
            )
            if newer_blocker:
                reason_codes.append("EXACT_MODEL_IDENTITY_DRIFT")
            replay_stale = latest_replay is None or bool(
                (latest_positive is not None and latest_replay < latest_positive)
                or (latest_negative is not None and latest_replay < latest_negative)
            )
            if replay_stale:
                reason_codes.append("REPLAY_EVIDENCE_STALE")
            completion_claim_allowed = bool(
                conformance_status == "complete"
                and test_files_exist
                and replay_valid
                and positive_times
                and not newer_blocker
                and not replay_stale
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
                "parent_completion_authority": parent_completion_authority is True,
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
    "COMMON_DISPATCH_DISPOSITION_VERSION",
    "CONSUMER_REGISTRY_VERSION",
    "EXECUTION_PHASES",
    "ExecutionContractError",
    "IDENTICAL_WORK_DISPOSITIONS",
    "LOGICAL_CONTRACT_VERSION",
    "ReceiptVerdict",
    "aggregate_attempt_receipts",
    "build_common_receipt_binding",
    "build_common_dispatch_disposition",
    "canonical_json_bytes",
    "classify_identical_work_disposition",
    "identical_work_pin_sha256",
    "logical_contract_sha256",
    "may_run_concurrent",
    "reconcile_execution",
    "validate_attempt_receipt",
    "validate_consumer_registry",
    "validate_logical_contract",
]
