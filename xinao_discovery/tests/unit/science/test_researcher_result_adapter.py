"""Golden, drift, and consumer-binding tests for researcher result adapter."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from xinao.canonical import canonical_sha256
from xinao.science.portfolio import PolicyCandidateVersion, PolicyRole, admit_active_set
from xinao.science.researcher_result_adapter import (
    ADAPTER_MARKER,
    CONTAINER_RESULT_SCHEMA,
    RESEARCH_CANDIDATE_SCHEMA,
    SKILL_RESEARCH_RECEIPT_SCHEMA,
    ResearcherResultAdapterError,
    adapt_researcher_result_to_policy_candidate,
    raw_sha256,
    verify_researcher_result_against_receipt,
)

AS_OF = "2026-07-30T12:00:00.000Z"
MATERIAL_BUNDLE_ID = "xinao-material-bundle-sha256:" + ("ab" * 32)
MATERIAL_ID = "sha256:" + ("cd" * 32)
MATERIAL_SHA = "ef" * 32


def _candidate(**overrides: Any) -> dict[str, Any]:
    payload = {
        "schema_version": RESEARCH_CANDIDATE_SCHEMA,
        "status": "CANDIDATE_READY",
        "research_question": "What bounded mechanism is supported by the sealed materials?",
        "as_of": AS_OF,
        "material_bundle_id": MATERIAL_BUNDLE_ID,
        "material_refs_used": [{"material_id": MATERIAL_ID, "sha256": MATERIAL_SHA}],
        "summary": "Candidate-only research product; not an action policy.",
        "hypotheses": ["one hypothesis"],
        "competing_explanations": ["one competing explanation"],
        "methods": ["bounded material analysis"],
        "evidence_used": [
            {
                "material_id": MATERIAL_ID,
                "finding": "bounded finding",
                "locator": "whole file",
            }
        ],
        "counterevidence": [],
        "limitations": ["candidate evidence only"],
        "next_evidence": ["independent observation"],
    }
    payload.update(overrides)
    return payload


def _result_and_receipt(
    *,
    candidate: dict[str, Any] | None = None,
    status: str = "CANDIDATE_READY",
) -> tuple[bytes, dict[str, Any]]:
    cand = candidate if candidate is not None else _candidate(status=status)
    result = {
        "schema_version": CONTAINER_RESULT_SCHEMA,
        "status": status,
        "reason_codes": [],
        "candidate": cand,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
    }
    result_bytes = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    receipt = {
        "schema_version": SKILL_RESEARCH_RECEIPT_SCHEMA,
        "run_id": "xrr_20260730T120000_testrun01",
        "status": status,
        "candidate": copy.deepcopy(cand),
        "reason_codes": [],
        "result_sha256": raw_sha256(result_bytes),
        "result_path": "/tmp/does-not-matter/result.json",
        "created_at": "2026-07-30T12:01:00.000Z",
        "route_class": "scientific_researcher",
        "owner_adopted": False,
        "research_progress_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "completion_claim_allowed": False,
    }
    return result_bytes, receipt


def test_golden_verify_and_mint_is_deterministic_and_content_addressed() -> None:
    result_bytes, receipt = _result_and_receipt()
    first = adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    second = adapt_researcher_result_to_policy_candidate(result_bytes, copy.deepcopy(receipt))

    assert first == second
    assert first.content_hash is not None
    assert first.content_hash == first.compute_content_hash()
    assert first.role == PolicyRole.SUBSTANTIVE
    assert first.policy_ref == f"science.research_candidate.v2.sha256:{raw_sha256(result_bytes)}"
    assert first.decision_signature.decision_map_ref.startswith(
        "xinao.not_projected.research_candidate.v2:"
    )
    assert first.semantic_config["adapter_marker"] == ADAPTER_MARKER
    assert first.semantic_config["decision_map_projected"] is False
    assert first.semantic_config["active_set_admitted"] is False
    assert first.semantic_config["science_progress_claimed"] is False
    assert first.semantic_config["result_sha256"] == raw_sha256(result_bytes)
    assert first.knowledge_cutoff == datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    # Round-trip through the existing portfolio type consumer.
    accepted = PolicyCandidateVersion.model_validate(first.model_dump(mode="python"))
    assert accepted == first
    assert accepted.content_hash == first.content_hash


def test_result_hash_drift_is_rejected() -> None:
    result_bytes, receipt = _result_and_receipt()
    receipt["result_sha256"] = "0" * 64
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "RESULT_RECEIPT_HASH_DRIFT"


def test_schema_drift_on_receipt_and_candidate_is_rejected() -> None:
    result_bytes, receipt = _result_and_receipt()
    bad_receipt = copy.deepcopy(receipt)
    bad_receipt["schema_version"] = "xinao.skill_research_receipt.v1"
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, bad_receipt)
    assert err.value.reason_code == "RECEIPT_SCHEMA_DRIFT"

    drifted_candidate = _candidate(schema_version="xinao.research_candidate.v1")
    drifted_bytes, drifted_receipt = _result_and_receipt(candidate=drifted_candidate)
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(drifted_bytes, drifted_receipt)
    assert err.value.reason_code == "RESEARCH_CANDIDATE_SCHEMA_DRIFT"


def test_candidate_object_drift_between_result_and_receipt_is_rejected() -> None:
    result_bytes, receipt = _result_and_receipt()
    receipt["candidate"] = _candidate(summary="tampered summary not in result bytes")
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "RESULT_RECEIPT_CANDIDATE_DRIFT"


def test_progress_claims_are_fail_closed() -> None:
    result_bytes, receipt = _result_and_receipt()
    receipt["science_restored"] = True
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "SCIENCE_PROGRESS_CLAIM_FORBIDDEN"


def test_consumer_binding_accepts_identity_but_rejects_single_candidate_activeset() -> None:
    result_bytes, receipt = _result_and_receipt()
    policy = adapt_researcher_result_to_policy_candidate(result_bytes, receipt)

    # Existing portfolio consumer accepts the sealed identity.
    assert PolicyCandidateVersion.model_validate(policy.model_dump(mode="python")) == policy

    # Adapter must not auto-admit a single research candidate as a full ActiveSet.
    with pytest.raises((ValueError, ValidationError)):
        admit_active_set(
            active_set_ref="active-set.forbidden-single.v1",
            protocol_pin_ref="protocol.synthetic.v1",
            protocol_pin_sha256="a" * 64,
            admitted_at=datetime(2026, 7, 30, 11, 0, tzinfo=UTC),
            policies=(policy,),
            residual_axes=("research-only",),
        )


def test_does_not_fabricate_decision_map_from_research_prose() -> None:
    result_bytes, receipt = _result_and_receipt()
    policy = adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    prose = " ".join(
        [
            receipt["candidate"]["summary"],
            *receipt["candidate"]["hypotheses"],
            *receipt["candidate"]["methods"],
        ]
    )
    assert prose not in policy.decision_signature.decision_map_ref
    assert policy.decision_signature.decision_map_ref == (
        f"xinao.not_projected.research_candidate.v2:{raw_sha256(result_bytes)}"
    )
    assert "selected_number" not in policy.semantic_config
    assert "stake" not in policy.semantic_config
    # Probe identity is content-bound, not prose-compiled action endpoints.
    assert policy.decision_signature.probe_trace_hash == canonical_sha256(
        [
            "XINAO_RESEARCHER_RESULT_ADAPTER_V1",
            policy.semantic_config["result_sha256"],
            policy.semantic_config["receipt_content_sha256"],
            policy.semantic_config["candidate_content_sha256"],
            policy.semantic_config["status"],
        ]
    )


def test_verify_binding_exposes_hashes_without_mint_side_effects() -> None:
    result_bytes, receipt = _result_and_receipt()
    binding = verify_researcher_result_against_receipt(result_bytes, receipt)
    assert binding["result_sha256"] == raw_sha256(result_bytes)
    assert len(binding["receipt_content_sha256"]) == 64
    assert binding["run_id"] == receipt["run_id"]
    assert binding["status"] == "CANDIDATE_READY"
