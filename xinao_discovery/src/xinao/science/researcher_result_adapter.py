"""Fail-closed researcher result -> science PolicyCandidateVersion adapter.

Binds verified ``xinao.research_candidate.v2`` result bytes to a matching
``xinao.skill_research_receipt.v2`` receipt, then mints one content-addressed
``PolicyCandidateVersion`` accepted by the existing science portfolio consumer.

This adapter:

- does not invent a policy ``decision_map`` from research prose;
- does not admit a single candidate as a full ``ActiveSet``;
- does not claim science progress / parent completion;
- does not create a second store or control plane.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.science.portfolio import DecisionSignature, PolicyCandidateVersion, PolicyRole

RESEARCH_CANDIDATE_SCHEMA: Final = "xinao.research_candidate.v2"
SKILL_RESEARCH_RECEIPT_SCHEMA: Final = "xinao.skill_research_receipt.v2"
CONTAINER_RESULT_SCHEMA: Final = "xinao.researcher_container_result.v2"
ADAPTER_BINDING_KIND: Final = "XINAO_RESEARCHER_RESULT_ADAPTER_V1"
ADAPTER_MARKER: Final = "XINAO_RESEARCHER_RESULT_ADAPTER_CANDIDATE_V1"

_HEX64 = frozenset("0123456789abcdef")
_ALLOWED_STATUSES = frozenset({"CANDIDATE_READY", "INSUFFICIENT_EVIDENCE"})
_RESEARCH_CANDIDATE_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "research_question",
        "as_of",
        "material_bundle_id",
        "material_refs_used",
        "summary",
        "hypotheses",
        "competing_explanations",
        "methods",
        "evidence_used",
        "counterevidence",
        "limitations",
        "next_evidence",
    }
)


class ResearcherResultAdapterError(ValueError):
    """Fail-closed adapter rejection with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def raw_sha256(data: bytes) -> str:
    """Return lowercase SHA-256 over raw file bytes (receipt.result_sha256 profile)."""

    return hashlib.sha256(data).hexdigest()


def _require_mapping(value: object, reason_code: str, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ResearcherResultAdapterError(reason_code, f"{label} must be a JSON object")
    return dict(value)


def _require_hex64(value: object, reason_code: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in _HEX64 for ch in value):
        raise ResearcherResultAdapterError(reason_code, f"{label} must be lowercase sha256")
    return value


def _require_text(value: object, reason_code: str, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ResearcherResultAdapterError(reason_code, f"{label} must be non-empty UTF-8 text")
    return value


def _parse_aware_timestamp(value: object, label: str) -> datetime:
    text = _require_text(value, "RESEARCH_CANDIDATE_AS_OF_INVALID", label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_AS_OF_INVALID", f"{label} must be ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_AS_OF_INVALID", f"{label} must be timezone-aware"
        )
    return parsed.astimezone(UTC)


def _forbid_progress_claims(payload: Mapping[str, Any], *, surface: str) -> None:
    for key in (
        "completion_claim_allowed",
        "research_progress_claim_allowed",
        "science_restored",
        "parent_complete",
        "owner_adopted",
    ):
        if key in payload and payload[key] is not False:
            raise ResearcherResultAdapterError(
                "SCIENCE_PROGRESS_CLAIM_FORBIDDEN",
                f"{surface}.{key} must be false or absent",
            )


def _validate_research_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    payload = _require_mapping(candidate, "RESEARCH_CANDIDATE_SCHEMA_INVALID", "candidate")
    if set(payload) != _RESEARCH_CANDIDATE_KEYS:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_FIELDS_INVALID",
            "candidate keys are not exact",
        )
    if payload.get("schema_version") != RESEARCH_CANDIDATE_SCHEMA:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_SCHEMA_DRIFT",
            str(payload.get("schema_version")),
        )
    status = payload.get("status")
    if status not in _ALLOWED_STATUSES:
        raise ResearcherResultAdapterError("RESEARCH_CANDIDATE_STATUS_INVALID", str(status))
    _require_text(payload.get("research_question"), "RESEARCH_CANDIDATE_FIELDS_INVALID", "question")
    _parse_aware_timestamp(payload.get("as_of"), "as_of")
    _require_text(
        payload.get("material_bundle_id"),
        "RESEARCH_CANDIDATE_FIELDS_INVALID",
        "material_bundle_id",
    )
    _require_text(payload.get("summary"), "RESEARCH_CANDIDATE_FIELDS_INVALID", "summary")
    for key in (
        "hypotheses",
        "competing_explanations",
        "methods",
        "counterevidence",
        "limitations",
        "next_evidence",
        "material_refs_used",
        "evidence_used",
    ):
        if not isinstance(payload.get(key), list):
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_FIELDS_INVALID",
                f"{key} must be a list",
            )
    return payload


def _load_result(result_bytes: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(result_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearcherResultAdapterError(
            "RESEARCH_RESULT_JSON_INVALID",
            str(exc),
        ) from exc
    return _require_mapping(parsed, "RESEARCH_RESULT_JSON_INVALID", "result")


def verify_researcher_result_against_receipt(
    result_bytes: bytes,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify raw result bytes against a skill research receipt (fail-closed).

    Returns a normalized binding dict used only for minting identity.
    """

    if not isinstance(result_bytes, (bytes, bytearray)):
        raise ResearcherResultAdapterError("RESEARCH_RESULT_BYTES_INVALID", "bytes required")
    raw_result = bytes(result_bytes)
    if not raw_result:
        raise ResearcherResultAdapterError("RESEARCH_RESULT_BYTES_INVALID", "empty result")

    receipt_obj = _require_mapping(receipt, "RECEIPT_SCHEMA_INVALID", "receipt")
    if receipt_obj.get("schema_version") != SKILL_RESEARCH_RECEIPT_SCHEMA:
        raise ResearcherResultAdapterError(
            "RECEIPT_SCHEMA_DRIFT",
            str(receipt_obj.get("schema_version")),
        )
    _forbid_progress_claims(receipt_obj, surface="receipt")

    expected_result_sha = _require_hex64(
        receipt_obj.get("result_sha256"),
        "RECEIPT_RESULT_HASH_INVALID",
        "result_sha256",
    )
    observed_result_sha = raw_sha256(raw_result)
    if observed_result_sha != expected_result_sha:
        raise ResearcherResultAdapterError(
            "RESULT_RECEIPT_HASH_DRIFT",
            f"observed={observed_result_sha} expected={expected_result_sha}",
        )

    result = _load_result(raw_result)
    if result.get("schema_version") != CONTAINER_RESULT_SCHEMA:
        raise ResearcherResultAdapterError(
            "RESULT_SCHEMA_DRIFT",
            str(result.get("schema_version")),
        )
    _forbid_progress_claims(result, surface="result")

    status = result.get("status")
    if status not in _ALLOWED_STATUSES:
        raise ResearcherResultAdapterError("RESULT_STATUS_INVALID", str(status))
    if receipt_obj.get("status") != status:
        raise ResearcherResultAdapterError(
            "RESULT_RECEIPT_STATUS_DRIFT",
            f"result={status} receipt={receipt_obj.get('status')}",
        )

    result_candidate = _validate_research_candidate(result.get("candidate"))
    if result_candidate.get("status") != status:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_STATUS_DRIFT",
            f"candidate={result_candidate.get('status')} result={status}",
        )
    receipt_candidate = _validate_research_candidate(receipt_obj.get("candidate"))
    if canonical_sha256(result_candidate) != canonical_sha256(receipt_candidate):
        raise ResearcherResultAdapterError(
            "RESULT_RECEIPT_CANDIDATE_DRIFT",
            "candidate object bytes disagree",
        )

    run_id = _require_text(receipt_obj.get("run_id"), "RECEIPT_RUN_ID_INVALID", "run_id")
    # Receipt identity excludes transport-only return fields that are not sealed on disk.
    sealed_receipt = {
        key: value
        for key, value in receipt_obj.items()
        if key not in {"receipt_path", "receipt_sha256"}
    }
    receipt_content_sha256 = canonical_sha256(sealed_receipt)
    return {
        "result_sha256": observed_result_sha,
        "receipt_content_sha256": receipt_content_sha256,
        "run_id": run_id,
        "status": status,
        "candidate": result_candidate,
        "knowledge_cutoff": _parse_aware_timestamp(result_candidate["as_of"], "as_of"),
    }


def mint_policy_candidate_from_verified_binding(
    binding: Mapping[str, Any],
) -> PolicyCandidateVersion:
    """Mint one content-addressed PolicyCandidateVersion from a verified binding.

    The decision_map_ref is an explicit not-projected sentinel bound to the result
    hash. Research prose is never compiled into an action decision_map.
    """

    result_sha256 = _require_hex64(
        binding.get("result_sha256"),
        "BINDING_RESULT_HASH_INVALID",
        "result_sha256",
    )
    receipt_content_sha256 = _require_hex64(
        binding.get("receipt_content_sha256"),
        "BINDING_RECEIPT_HASH_INVALID",
        "receipt_content_sha256",
    )
    run_id = _require_text(binding.get("run_id"), "BINDING_RUN_ID_INVALID", "run_id")
    status = binding.get("status")
    if status not in _ALLOWED_STATUSES:
        raise ResearcherResultAdapterError("BINDING_STATUS_INVALID", str(status))
    candidate = _validate_research_candidate(binding.get("candidate"))
    knowledge_cutoff = binding.get("knowledge_cutoff")
    if not isinstance(knowledge_cutoff, datetime):
        knowledge_cutoff = _parse_aware_timestamp(candidate.get("as_of"), "as_of")
    elif knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None:
        raise ResearcherResultAdapterError(
            "BINDING_KNOWLEDGE_CUTOFF_INVALID",
            "knowledge_cutoff must be timezone-aware",
        )

    candidate_content_sha256 = canonical_sha256(candidate)
    # Explicit non-projection sentinel: not derived from research prose endpoints.
    decision_map_ref = f"xinao.not_projected.research_candidate.v2:{result_sha256}"
    policy_ref = f"science.research_candidate.v2.sha256:{result_sha256}"
    family_id = f"researcher-result.v2:{candidate['material_bundle_id']}"
    probe_trace_hash = canonical_sha256(
        [
            ADAPTER_BINDING_KIND,
            result_sha256,
            receipt_content_sha256,
            candidate_content_sha256,
            status,
        ]
    )
    semantic_config = {
        "binding_kind": ADAPTER_BINDING_KIND,
        "adapter_marker": ADAPTER_MARKER,
        "research_candidate_schema": RESEARCH_CANDIDATE_SCHEMA,
        "skill_research_receipt_schema": SKILL_RESEARCH_RECEIPT_SCHEMA,
        "container_result_schema": CONTAINER_RESULT_SCHEMA,
        "result_sha256": result_sha256,
        "receipt_content_sha256": receipt_content_sha256,
        "candidate_content_sha256": candidate_content_sha256,
        "run_id": run_id,
        "status": status,
        "research_question_sha256": canonical_sha256(candidate["research_question"]),
        "material_bundle_id": candidate["material_bundle_id"],
        "decision_map_projected": False,
        "active_set_admitted": False,
        "science_progress_claimed": False,
        "completion_claim_allowed": False,
    }
    return PolicyCandidateVersion(
        policy_ref=policy_ref,
        family_id=family_id,
        role=PolicyRole.SUBSTANTIVE,
        knowledge_cutoff=knowledge_cutoff,
        decision_signature=DecisionSignature(
            mechanism="RESEARCH_CANDIDATE_RECEIPT_BOUND_NOT_PROJECTED",
            feature_visibility=("research_candidate_v2_identity",),
            time_scale="RESEARCH_ONLY_NOT_PROJECTED",
            update_policy="IMMUTABLE_RESULT_RECEIPT_BINDING",
            abstention_rule="NO_ACTION_MAP_UNTIL_EXPLICIT_PROJECTION",
            action_support="NOT_PROJECTED",
            decision_map_ref=decision_map_ref,
            probe_target_count=1,
            # Non-vacuous identity probe: the sealed research artifact itself.
            probe_action_count=1,
            probe_trace_hash=probe_trace_hash,
        ),
        semantic_config=semantic_config,
    ).with_content_hash()


def adapt_researcher_result_to_policy_candidate(
    result_bytes: bytes,
    receipt: Mapping[str, Any],
) -> PolicyCandidateVersion:
    """Verify result+receipt, then mint one portfolio-accepted candidate identity."""

    binding = verify_researcher_result_against_receipt(result_bytes, receipt)
    return mint_policy_candidate_from_verified_binding(binding)


__all__ = [
    "ADAPTER_BINDING_KIND",
    "ADAPTER_MARKER",
    "CONTAINER_RESULT_SCHEMA",
    "RESEARCH_CANDIDATE_SCHEMA",
    "SKILL_RESEARCH_RECEIPT_SCHEMA",
    "ResearcherResultAdapterError",
    "adapt_researcher_result_to_policy_candidate",
    "mint_policy_candidate_from_verified_binding",
    "raw_sha256",
    "verify_researcher_result_against_receipt",
]
