"""Consume one G4 batch through the provider-neutral execution receipt seam."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.capability.g4_batch import validate_g4_batch
from xinao.capability.phase_conditions import (
    build_phase_control_state,
    execution_directives,
    human_summary_cn,
    legacy_claim_projection,
)

from services.agent_runtime.execution_contract import (
    canonical_json_bytes,
    logical_contract_sha256,
    validate_attempt_receipt,
    validate_logical_contract,
)

G4_BATCH_EXECUTION_REPORT_VERSION = "xinao.g4.batch_execution_admission.v1"


def adjudicate_g4_batch_execution(
    *,
    batch_manifest: Mapping[str, Any],
    logical_contract: Mapping[str, Any],
    attempt_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a scientific batch to one selected attempt, never to a campaign provider."""

    batch = validate_g4_batch(batch_manifest)
    contract = validate_logical_contract(logical_contract)
    reasons: list[str] = []
    if contract["work_key"] != batch["work_key"]:
        reasons.append("BATCH_WORK_KEY_MISMATCH")
    if contract["input_sha256"] != batch["content_hash"]:
        reasons.append("BATCH_INPUT_HASH_MISMATCH")
    verdict = validate_attempt_receipt(contract, attempt_receipt)
    reasons.extend(verdict.reason_codes)
    accepted = verdict.accepted and not reasons
    selection = dict(contract["selection"])
    attempt_receipt_sha256 = hashlib.sha256(canonical_json_bytes(dict(attempt_receipt))).hexdigest()
    phase_control = build_phase_control_state(
        observed_generation=canonical_sha256(
            {
                "schema_version": "xinao.g4.batch.phase_generation.v1",
                "batch_manifest_sha256": batch["content_hash"],
                "logical_contract_sha256": logical_contract_sha256(contract),
                "attempt_receipt_sha256": attempt_receipt_sha256,
                "receipt_verdict": {
                    "accepted": verdict.accepted,
                    "reason_codes": list(verdict.reason_codes),
                },
            }
        ),
        g4_engineering_allowed=True,
        g4_batch_execution_allowed=accepted,
        g4_full_evidence_complete=False,
        g5_design_allowed=True,
        g5_preregistration_allowed=True,
        g5_final_adjudication_complete=False,
        g6_formal_research_allowed=False,
    )
    directives = execution_directives(phase_control)
    legacy = legacy_claim_projection(phase_control)
    report: dict[str, Any] = {
        "schema_version": G4_BATCH_EXECUTION_REPORT_VERSION,
        "terminal": (
            "G4_BATCH_EXECUTION_RECEIPT_ACCEPTED"
            if accepted
            else "G4_BATCH_EXECUTION_RECEIPT_REJECTED"
        ),
        "batch_execution_accepted": accepted,
        "campaign_id": batch["campaign_id"],
        "batch_id": batch["batch_id"],
        "batch_sequence": batch["batch_sequence"],
        "work_key": batch["work_key"],
        "batch_manifest_sha256": batch["content_hash"],
        "logical_contract_sha256": logical_contract_sha256(contract),
        "attempt_receipt_sha256": attempt_receipt_sha256,
        "selected_route_for_this_batch": selection,
        "provider_binding_scope": "batch_attempt_only",
        "campaign_provider_locked": False,
        "full_campaign_capacity_precommit_required": False,
        "api_quota_is_campaign_gate": False,
        "reason_codes": list(dict.fromkeys(reasons)),
        "phase_control_state": phase_control,
        "execution_directives": directives,
        "human_status_cn": human_summary_cn(phase_control),
        "g4_full": legacy["g4_full"],
        "g4_closed": legacy["g4_closed"],
        "g5_closed": legacy["g5_closed"],
        "formal_research_allowed": legacy["formal_research_allowed"],
        "global_wait_allowed": directives["parent_global_wait_allowed"],
        "authority": False,
        "completion_claim_allowed": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return report


__all__ = [
    "G4_BATCH_EXECUTION_REPORT_VERSION",
    "adjudicate_g4_batch_execution",
]
