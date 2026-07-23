"""Provider-neutral G4 experiment-batch contracts.

The complete G4 campaign is evidence debt, not one provider transaction.  Each
batch binds the scientific protocol and ledger position while deliberately
leaving provider, model, transport, endpoint, and quota selection to the
current worker bus.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from xinao.canonical import canonical_sha256

G4_BATCH_SCHEMA_VERSION = "xinao.g4.experiment_batch.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_ROUTE_KEYS = frozenset(
    {
        "api",
        "api_key",
        "endpoint",
        "launcher",
        "model_id",
        "provider",
        "provider_id",
        "quota",
        "relay",
        "transport_id",
    }
)
_HASH_FIELDS = (
    "campaign_contract_sha256",
    "suite_sha256",
    "evaluator_sha256",
    "policy_sha256",
    "preregistration_sha256",
    "power_plan_sha256",
    "stopping_rule_sha256",
    "retry_policy_sha256",
    "holdout_budget_sha256",
    "global_trial_ledger_snapshot_sha256",
)


class G4BatchError(ValueError):
    """A G4 batch contract is malformed or contains campaign route binding."""


def _sha256(field: str, value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise G4BatchError(f"{field} must be 64 lowercase hex")
    return value


def _text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise G4BatchError(f"{field} must be non-empty text")
    return value


def _forbidden_route_paths(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            child_path = f"{path}.{key}"
            if normalized in _FORBIDDEN_ROUTE_KEYS:
                findings.append(child_path)
            findings.extend(_forbidden_route_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_forbidden_route_paths(child, path=f"{path}[{index}]"))
    return findings


def build_g4_batch(
    *,
    campaign_id: str,
    batch_id: str,
    batch_sequence: int,
    work_key: str,
    cell_ids: Sequence[str],
    campaign_contract_sha256: str,
    suite_sha256: str,
    evaluator_sha256: str,
    policy_sha256: str,
    preregistration_sha256: str,
    power_plan_sha256: str,
    stopping_rule_sha256: str,
    retry_policy_sha256: str,
    holdout_budget_sha256: str,
    global_trial_ledger_ref: str,
    global_trial_ledger_snapshot_sha256: str,
) -> dict[str, Any]:
    """Build one scientific batch with no campaign-wide execution route."""

    payload: dict[str, Any] = {
        "schema_version": G4_BATCH_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "batch_id": batch_id,
        "batch_sequence": batch_sequence,
        "work_key": work_key,
        "cell_ids": list(cell_ids),
        "campaign_contract_sha256": campaign_contract_sha256,
        "suite_sha256": suite_sha256,
        "evaluator_sha256": evaluator_sha256,
        "policy_sha256": policy_sha256,
        "preregistration_sha256": preregistration_sha256,
        "power_plan_sha256": power_plan_sha256,
        "stopping_rule_sha256": stopping_rule_sha256,
        "retry_policy_sha256": retry_policy_sha256,
        "holdout_budget_sha256": holdout_budget_sha256,
        "global_trial_ledger_ref": global_trial_ledger_ref,
        "global_trial_ledger_snapshot_sha256": (global_trial_ledger_snapshot_sha256),
        "route_binding": {
            "scope": "batch_only",
            "selection_source": "canonical_worker_bus_route_receipt",
            "campaign_provider_locked": False,
            "full_campaign_capacity_precommit_required": False,
        },
        "authority": False,
        "completion_claim_allowed": False,
    }
    payload["content_hash"] = canonical_sha256(payload)
    return validate_g4_batch(payload)


def validate_g4_batch(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the exact batch contract and reject embedded route identities."""

    data = dict(raw)
    expected_keys = {
        "schema_version",
        "campaign_id",
        "batch_id",
        "batch_sequence",
        "work_key",
        "cell_ids",
        *_HASH_FIELDS,
        "global_trial_ledger_ref",
        "route_binding",
        "authority",
        "completion_claim_allowed",
        "content_hash",
    }
    if set(data) != expected_keys:
        raise G4BatchError("G4 batch fields do not match the v1 contract")
    if data.get("schema_version") != G4_BATCH_SCHEMA_VERSION:
        raise G4BatchError("unexpected G4 batch schema_version")
    for field in (
        "campaign_id",
        "batch_id",
        "work_key",
        "global_trial_ledger_ref",
    ):
        _text(field, data.get(field))
    sequence = data.get("batch_sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise G4BatchError("batch_sequence must be an integer >= 1")
    cell_ids = data.get("cell_ids")
    if (
        not isinstance(cell_ids, list)
        or not cell_ids
        or any(not isinstance(value, str) or not value for value in cell_ids)
        or len(cell_ids) != len(set(cell_ids))
    ):
        raise G4BatchError("cell_ids must be a non-empty unique string array")
    for field in _HASH_FIELDS:
        _sha256(field, data.get(field))
    route_binding = data.get("route_binding")
    if route_binding != {
        "scope": "batch_only",
        "selection_source": "canonical_worker_bus_route_receipt",
        "campaign_provider_locked": False,
        "full_campaign_capacity_precommit_required": False,
    }:
        raise G4BatchError("route_binding must remain batch-only and provider-neutral")
    if data.get("authority") is not False or data.get("completion_claim_allowed") is not False:
        raise G4BatchError("a batch contract cannot claim authority or G4 completion")
    forbidden = _forbidden_route_paths(
        {key: value for key, value in data.items() if key != "route_binding"}
    )
    if forbidden:
        raise G4BatchError(f"campaign route fields are forbidden: {sorted(forbidden)}")
    recorded = _sha256("content_hash", data.get("content_hash"))
    body = {key: value for key, value in data.items() if key != "content_hash"}
    if canonical_sha256(body) != recorded:
        raise G4BatchError("G4 batch content_hash mismatch")
    return data


__all__ = [
    "G4_BATCH_SCHEMA_VERSION",
    "G4BatchError",
    "build_g4_batch",
    "validate_g4_batch",
]
