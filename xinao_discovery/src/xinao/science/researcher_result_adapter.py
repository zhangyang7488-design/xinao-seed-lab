"""Fail-closed researcher result -> science PolicyCandidateVersion adapter.

Binds verified ``xinao.research_candidate.v2`` result bytes to a matching
``xinao.skill_research_receipt.v2`` receipt, then mints one content-addressed
``PolicyCandidateVersion`` accepted by the existing science portfolio consumer.

Production success result key set is pinned to the formal producer
(``docker/xinao-researcher/entrypoint.py``) object written into
``result.json``. After #159 that object intentionally carries both
``provider_session_id_present`` / ``provider_request_id_present`` and the raw
``provider_session_id`` / ``provider_request_id`` strings. The host runtime
exact-key allowlist in ``xinao_runtime._validate_material_result_binding`` still
lists only the ``*_present`` flags — that lagging consumer seam is outside this
adapter's write domain. This adapter does **not** silently drop or invent a
third key set: production success fixtures and exact-key validation follow the
producer formal result object (with raw ids).

This adapter:

- does not invent a policy ``decision_map`` from research prose;
- does not admit a single candidate as a full ``ActiveSet``;
- does not claim science progress / parent completion;
- does not create a second store or control plane.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.science.portfolio import DecisionSignature, PolicyCandidateVersion, PolicyRole

RESEARCH_CANDIDATE_SCHEMA: Final = "xinao.research_candidate.v2"
SKILL_RESEARCH_RECEIPT_SCHEMA: Final = "xinao.skill_research_receipt.v2"
CONTAINER_RESULT_SCHEMA: Final = "xinao.researcher_container_result.v2"
ADAPTER_BINDING_KIND: Final = "XINAO_RESEARCHER_RESULT_ADAPTER_V1"
ADAPTER_MARKER: Final = "XINAO_RESEARCHER_RESULT_ADAPTER_CANDIDATE_V1"
ROUTE_CLASS_SCIENTIFIC_RESEARCHER: Final = "scientific_researcher"

# Producer formal success keys (entrypoint result.json). Reconciled seam: raw
# provider_*_id fields are part of the sealed production result object.
PRODUCTION_SUCCESS_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "status",
        "reason_codes",
        "candidate",
        "request_sha256",
        "prompt_sha256",
        "output_schema_sha256",
        "material_bundle_id",
        "material_manifest_sha256",
        "material_packet_sha256",
        "effective_prompt_sha256",
        "material_refs_available",
        "provider",
        "requested_model",
        "provider_stop_reason",
        "provider_num_turns",
        "provider_session_id_present",
        "provider_request_id_present",
        "provider_session_id",
        "provider_request_id",
        "provider_model_usage",
        "usage",
        "completion_claim_allowed",
        "science_restored",
        "parent_complete",
    }
)

# Sealed skill receipt keys written before transport-only path/hash fields.
PRODUCTION_SUCCESS_RECEIPT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "run_id",
        "status",
        "candidate",
        "reason_codes",
        "release_id",
        "release_manifest_path",
        "release_manifest_sha256",
        "execution_pointer_sha256",
        "execution_pointer_generation",
        "execution_activation_txn_id",
        "skill_bundle_tree_sha256",
        "package_version",
        "capability_version",
        "required_bootstrap_protocol",
        "image_id",
        "container_id",
        "container_exit_code",
        "container_terminal_attestation",
        "container_security",
        "provider_egress",
        "container_removed",
        "request_sha256",
        "base_prompt_sha256",
        "output_schema_sha256",
        "material_bundle_id",
        "material_manifest_path",
        "material_manifest_sha256",
        "material_packet_sha256",
        "effective_prompt_sha256",
        "material_source_refs",
        "material_prompt_binding_verified",
        "material_use_claim_bound",
        "result_sha256",
        "result_path",
        "created_at",
        "route_class",
        "ordinary_worker_chain_used",
        "provider_evidence",
        "auth_handle_identity_unchanged",
        "user_operations_required",
        "owner_adopted",
        "research_progress_claim_allowed",
        "science_restored",
        "parent_complete",
        "completion_claim_allowed",
    }
)

# Transport-only keys that may appear on returned receipts but are not sealed.
_RECEIPT_TRANSPORT_ONLY_KEYS: Final[frozenset[str]] = frozenset({"receipt_path", "receipt_sha256"})

# Observation / host-path fields that must not move policy identity.
_RECEIPT_VOLATILE_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "result_path",
        "created_at",
        "container_id",
        "container_removed",
        "release_manifest_path",
        "material_manifest_path",
        "material_source_refs",
        "container_security",
        "provider_egress",
    }
)

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BUNDLE_ID = re.compile(r"^xinao-material-bundle-sha256:[0-9a-f]{64}$")
_MATERIAL_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_ALLOWED_STATUSES = frozenset({"CANDIDATE_READY", "INSUFFICIENT_EVIDENCE"})
_RESEARCH_CANDIDATE_REQUIRED_KEYS = frozenset(
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
_RESEARCH_CANDIDATE_OPTIONAL_KEYS = frozenset(
    {
        "account_identity",
        "complete_actor_behavior_intent",
        "executable_account_decision",
        "no_action_intent",
    }
)
_RESEARCHER_EXECUTABLE_CORE_KEYS = frozenset(
    {
        "panel",
        "selected_number",
        "stake",
        "target_ref",
        "target_open_time",
        "freeze_deadline",
        "knowledge_cutoff",
        "odds_version_ref",
        "baseline_ref",
        "risk_policy_ref",
        "rule_ref",
    }
)
_RESEARCHER_NO_ACTION_CORE_KEYS = frozenset(
    {
        "target_ref",
        "target_open_time",
        "freeze_deadline",
        "knowledge_cutoff",
        "odds_version_ref",
        "rule_ref",
    }
)
_ACTOR_INTENT_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "authored_at",
        "decision_kind",
        "stake",
        "research_rationale",
    }
)
_ACTOR_INTENT_OPTIONAL_KEYS = frozenset(
    {
        "panel",
        "selected_number",
        "after_hit_response",
        "after_miss_response",
        "next_round_or_stop_response",
        "content_hash",
    }
)
_CANONICAL_STAKE = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{4}$")
_PROVIDER_EVIDENCE_KEYS = frozenset(
    {
        "stop_reason",
        "num_turns",
        "session_id_present",
        "request_id_present",
        "model_usage",
        "usage",
    }
)
_MATERIAL_REF_KEYS = frozenset({"material_id", "sha256"})
_EVIDENCE_KEYS = frozenset({"material_id", "finding", "locator"})
_MAX_PROVIDER_ID_BYTES = 4096
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 100_000


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
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise ResearcherResultAdapterError(reason_code, f"{label} must be lowercase sha256")
    return value


def _require_text(value: object, reason_code: str, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ResearcherResultAdapterError(reason_code, f"{label} must be non-empty UTF-8 text")
    return value


def _plain_json_text(
    value: object, *, nonempty: bool = False, maximum_bytes: int | None = None
) -> bool:
    if not isinstance(value, str) or "\x00" in value or (nonempty and not value):
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return maximum_bytes is None or len(encoded) <= maximum_bytes


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


def _validate_actor_behavior_intent(value: object) -> dict[str, Any]:
    intent = _require_mapping(
        value,
        "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID",
        "complete_actor_behavior_intent",
    )
    observed = set(intent)
    if (
        not _ACTOR_INTENT_REQUIRED_KEYS.issubset(observed)
        or observed - _ACTOR_INTENT_REQUIRED_KEYS - _ACTOR_INTENT_OPTIONAL_KEYS
    ):
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID",
            "intent required/optional keys are invalid",
        )
    if intent.get("schema_version") != "xinao.actor_authored_behavior_intent.v1":
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID", "schema_version"
        )
    authored_text = _require_text(
        intent.get("authored_at"),
        "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID",
        "authored_at",
    )
    _parse_aware_timestamp(authored_text, "actor intent authored_at")
    # Preserve a non-UTC offset exactly as the Pydantic intent model does while
    # still normalizing UTC ``+00:00`` to ``Z`` for its JSON hash form.
    authored_at = datetime.fromisoformat(authored_text.replace("Z", "+00:00"))
    _require_text(
        intent.get("research_rationale"),
        "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID",
        "research_rationale",
    )
    for field in (
        "after_hit_response",
        "after_miss_response",
        "next_round_or_stop_response",
    ):
        response = intent.get(field)
        if response is not None and not _plain_json_text(response, nonempty=True):
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID", field
            )
    stake = intent.get("stake")
    if not isinstance(stake, str) or _CANONICAL_STAKE.fullmatch(stake) is None:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID", "stake"
        )
    try:
        amount = Decimal(stake)
    except InvalidOperation as exc:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID", "stake"
        ) from exc
    kind = intent.get("decision_kind")
    if kind == "ACTION":
        number = intent.get("selected_number")
        if (
            amount <= 0
            or intent.get("panel") not in {"A", "B"}
            or type(number) is not int
            or not 1 <= number <= 49
        ):
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID", "ACTION fields"
            )
    elif kind == "NO_ACTION":
        if (
            amount != 0
            or intent.get("panel") is not None
            or intent.get("selected_number") is not None
        ):
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID", "NO_ACTION fields"
            )
    else:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID", "decision_kind"
        )
    content_hash = intent.get("content_hash")
    if content_hash is not None:
        _require_hex64(
            content_hash,
            "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID",
            "content_hash",
        )
        body = {
            "schema_version": intent.get("schema_version"),
            "authored_at": authored_at.isoformat().replace("+00:00", "Z"),
            "decision_kind": intent.get("decision_kind"),
            "panel": intent.get("panel"),
            "selected_number": intent.get("selected_number"),
            "stake": intent.get("stake"),
            "research_rationale": intent.get("research_rationale"),
            "after_hit_response": intent.get("after_hit_response"),
            "after_miss_response": intent.get("after_miss_response"),
            "next_round_or_stop_response": intent.get("next_round_or_stop_response"),
        }
        if content_hash != canonical_sha256(body):
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID", "content_hash mismatch"
            )
    return intent


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


def _strict_json_int(value: str) -> int:
    if len(value.lstrip("-")) > 128:
        raise ValueError("JSON integer exceeds 128 digits")
    return int(value)


def _strict_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON float forbidden")
    return parsed


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key forbidden: {key}")
        result[key] = value
    return result


def _validate_json_shape(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > _MAX_JSON_DEPTH:
            raise ValueError(f"JSON depth exceeds {_MAX_JSON_DEPTH}")
        if nodes > _MAX_JSON_NODES:
            raise ValueError(f"JSON nodes exceed {_MAX_JSON_NODES}")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def strict_json_loads(text: str) -> Any:
    """Parse JSON with duplicate-key rejection and finite-number discipline."""

    parsed = json.loads(
        text,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON number forbidden: {token}")
        ),
        parse_int=_strict_json_int,
        parse_float=_strict_json_float,
        object_pairs_hook=_strict_json_object,
    )
    _validate_json_shape(parsed)
    return parsed


def _require_empty_reason_codes(value: object, *, surface: str) -> list[Any]:
    if value != []:
        raise ResearcherResultAdapterError(
            "REASON_CODES_MUST_BE_EMPTY",
            f"{surface}.reason_codes must be an empty list for success",
        )
    return []


def _validate_text_list(value: object, *, key: str) -> list[str]:
    if not isinstance(value, list) or any(not _plain_json_text(item) for item in value):
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_TEXT_LIST_INVALID",
            key,
        )
    return list(value)


def _validate_material_refs_and_evidence(
    candidate: Mapping[str, Any],
    *,
    available_ids: Sequence[str] | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Exact nested material_refs_used / evidence_used validation with binding."""

    available: set[str] | None
    if available_ids is None:
        available = None
    else:
        available = set()
        for item in available_ids:
            if not isinstance(item, str) or _MATERIAL_ID.fullmatch(item) is None:
                raise ResearcherResultAdapterError(
                    "RESULT_MATERIAL_REFS_AVAILABLE_INVALID",
                    str(item),
                )
            if item in available:
                raise ResearcherResultAdapterError(
                    "RESULT_MATERIAL_REFS_AVAILABLE_DUPLICATED",
                    item,
                )
            available.add(item)

    refs = candidate.get("material_refs_used")
    if not isinstance(refs, list):
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_MATERIAL_REFS_INVALID",
            "list required",
        )
    used_ids: list[str] = []
    normalized_refs: list[dict[str, str]] = []
    for ref in refs:
        if not isinstance(ref, Mapping) or set(ref) != _MATERIAL_REF_KEYS:
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_MATERIAL_REFS_INVALID",
                str(ref),
            )
        material_id = ref.get("material_id")
        digest = ref.get("sha256")
        if (
            not isinstance(material_id, str)
            or not isinstance(digest, str)
            or _MATERIAL_ID.fullmatch(material_id) is None
            or _HEX_SHA256.fullmatch(digest) is None
            or material_id != f"sha256:{digest}"
        ):
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_MATERIAL_REF_PATTERN_INVALID",
                str(material_id),
            )
        if available is not None and material_id not in available:
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_MATERIAL_REF_UNKNOWN",
                material_id,
            )
        if material_id in used_ids:
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_MATERIAL_REF_DUPLICATED",
                material_id,
            )
        used_ids.append(material_id)
        normalized_refs.append({"material_id": material_id, "sha256": digest})

    if available is not None and available and not used_ids:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_MATERIAL_USE_UNBOUND",
            str(candidate.get("material_bundle_id")),
        )

    evidence = candidate.get("evidence_used")
    if not isinstance(evidence, list):
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_EVIDENCE_INVALID",
            "list required",
        )
    evidence_ids: list[str] = []
    normalized_evidence: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != _EVIDENCE_KEYS:
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_EVIDENCE_INVALID",
                str(item),
            )
        material_id = item.get("material_id")
        finding = item.get("finding")
        locator = item.get("locator")
        if (
            not isinstance(material_id, str)
            or _MATERIAL_ID.fullmatch(material_id) is None
            or material_id not in used_ids
        ):
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_EVIDENCE_REF_UNKNOWN",
                str(material_id),
            )
        if not _plain_json_text(finding, nonempty=True) or not _plain_json_text(
            locator, nonempty=True
        ):
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_EVIDENCE_INVALID",
                material_id,
            )
        evidence_ids.append(material_id)
        normalized_evidence.append(
            {
                "material_id": material_id,
                "finding": str(finding),
                "locator": str(locator),
            }
        )

    if available is not None and available and not evidence:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_EVIDENCE_USE_UNBOUND",
            str(candidate.get("material_bundle_id")),
        )
    if set(evidence_ids) != set(used_ids):
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_EVIDENCE_BINDING_INVALID",
            json.dumps(
                {"evidence_ids": sorted(set(evidence_ids)), "material_refs_used": sorted(used_ids)},
                sort_keys=True,
            ),
        )
    return normalized_refs, normalized_evidence


def _validate_research_candidate(
    candidate: Mapping[str, Any] | object,
    *,
    available_ids: Sequence[str] | None = None,
    expected_status: str | None = None,
    expected_question: str | None = None,
    expected_as_of: str | None = None,
    expected_bundle_id: str | None = None,
) -> dict[str, Any]:
    payload = _require_mapping(candidate, "RESEARCH_CANDIDATE_SCHEMA_INVALID", "candidate")
    observed_keys = set(payload)
    if (
        not _RESEARCH_CANDIDATE_REQUIRED_KEYS.issubset(observed_keys)
        or observed_keys - _RESEARCH_CANDIDATE_REQUIRED_KEYS - _RESEARCH_CANDIDATE_OPTIONAL_KEYS
    ):
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_FIELDS_INVALID",
            "candidate required/optional keys are invalid",
        )
    if payload.get("schema_version") != RESEARCH_CANDIDATE_SCHEMA:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_SCHEMA_DRIFT",
            str(payload.get("schema_version")),
        )
    status = payload.get("status")
    if status not in _ALLOWED_STATUSES:
        raise ResearcherResultAdapterError("RESEARCH_CANDIDATE_STATUS_INVALID", str(status))
    if expected_status is not None and status != expected_status:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_STATUS_DRIFT",
            f"candidate={status} expected={expected_status}",
        )
    question = _require_text(
        payload.get("research_question"),
        "RESEARCH_CANDIDATE_FIELDS_INVALID",
        "question",
    )
    as_of = payload.get("as_of")
    _parse_aware_timestamp(as_of, "as_of")
    bundle_id = payload.get("material_bundle_id")
    if not isinstance(bundle_id, str) or _BUNDLE_ID.fullmatch(bundle_id) is None:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_BUNDLE_ID_INVALID",
            str(bundle_id),
        )
    if expected_question is not None and question != expected_question:
        raise ResearcherResultAdapterError("RESEARCH_CANDIDATE_REQUEST_DRIFT", "question")
    if expected_as_of is not None and as_of != expected_as_of:
        raise ResearcherResultAdapterError("RESEARCH_CANDIDATE_REQUEST_DRIFT", "as_of")
    if expected_bundle_id is not None and bundle_id != expected_bundle_id:
        raise ResearcherResultAdapterError("RESEARCH_CANDIDATE_BUNDLE_DRIFT", "material_bundle_id")
    executable = payload.get("executable_account_decision")
    no_action_intent = payload.get("no_action_intent")
    has_action = executable is not None
    has_no_action = no_action_intent is not None
    if has_action and has_no_action:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_DECISION_BRANCH_CONFLICT",
            "candidate cannot author both ACTION and NO_ACTION",
        )
    if status == "INSUFFICIENT_EVIDENCE" and (has_action or has_no_action):
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_DECISION_STATUS_INVALID",
            "INSUFFICIENT_EVIDENCE cannot author an account decision",
        )
    declared_identity = payload.get("account_identity")
    if status == "INSUFFICIENT_EVIDENCE" and declared_identity is not None:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_ACCOUNT_IDENTITY_INVALID",
            "INSUFFICIENT_EVIDENCE cannot declare account_identity",
        )
    expected_identity = (
        "ACTION" if has_action else "RESEARCHER_ACCOUNT_NO_ACTION" if has_no_action else None
    )
    if declared_identity is not None and expected_identity is None:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_DECISION_BRANCH_INVALID",
            "account_identity requires one authored account decision branch",
        )
    if declared_identity is not None and declared_identity != expected_identity:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_ACCOUNT_IDENTITY_INVALID",
            f"declared={declared_identity!r} branch={expected_identity!r}",
        )
    if executable is not None:
        executable_map = _require_mapping(
            executable,
            "RESEARCH_CANDIDATE_EXECUTABLE_INVALID",
            "executable_account_decision",
        )
        if set(executable_map) != _RESEARCHER_EXECUTABLE_CORE_KEYS:
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_EXECUTABLE_INVALID",
                "executable_account_decision keys are not exact",
            )
        if status != "CANDIDATE_READY":
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_EXECUTABLE_STATUS_INVALID",
                str(status),
            )
    if no_action_intent is not None:
        no_action_map = _require_mapping(
            no_action_intent,
            "RESEARCH_CANDIDATE_NO_ACTION_INVALID",
            "no_action_intent",
        )
        if set(no_action_map) != _RESEARCHER_NO_ACTION_CORE_KEYS:
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_NO_ACTION_INVALID",
                "no_action_intent keys are not exact",
            )
        if status != "CANDIDATE_READY":
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_NO_ACTION_STATUS_INVALID",
                str(status),
            )
    actor_intent_raw = payload.get("complete_actor_behavior_intent")
    actor_intent = (
        _validate_actor_behavior_intent(actor_intent_raw)
        if actor_intent_raw is not None
        else None
    )
    if status == "INSUFFICIENT_EVIDENCE" and actor_intent is not None:
        raise ResearcherResultAdapterError(
            "RESEARCH_CANDIDATE_ACTOR_INTENT_STATUS_INVALID", str(status)
        )
    if actor_intent is not None and (has_action or has_no_action):
        projected_kind = "ACTION" if has_action else "NO_ACTION"
        if actor_intent["decision_kind"] != projected_kind:
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_ACTOR_INTENT_BRANCH_MISMATCH", "decision_kind"
            )
        if has_action and (
            actor_intent.get("panel") != executable_map.get("panel")
            or actor_intent.get("selected_number") != executable_map.get("selected_number")
            or actor_intent.get("stake") != executable_map.get("stake")
        ):
            raise ResearcherResultAdapterError(
                "RESEARCH_CANDIDATE_ACTOR_INTENT_BRANCH_MISMATCH", "ACTION choice"
            )
    if not _plain_json_text(payload.get("summary"), nonempty=True):
        raise ResearcherResultAdapterError("RESEARCH_CANDIDATE_SUMMARY_INVALID", "summary")
    for key in (
        "hypotheses",
        "competing_explanations",
        "methods",
        "counterevidence",
        "limitations",
        "next_evidence",
    ):
        _validate_text_list(payload.get(key), key=key)
    _validate_material_refs_and_evidence(payload, available_ids=available_ids)
    return payload


def _load_result(result_bytes: bytes) -> dict[str, Any]:
    try:
        text = result_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearcherResultAdapterError("RESEARCH_RESULT_JSON_INVALID", str(exc)) from exc
    try:
        parsed = strict_json_loads(text)
    except (json.JSONDecodeError, ValueError, RecursionError, UnicodeError) as exc:
        raise ResearcherResultAdapterError(
            "RESEARCH_RESULT_JSON_INVALID",
            str(exc),
        ) from exc
    return _require_mapping(parsed, "RESEARCH_RESULT_JSON_INVALID", "result")


def _validate_success_result(result: Mapping[str, Any]) -> dict[str, Any]:
    if set(result) != PRODUCTION_SUCCESS_RESULT_KEYS:
        missing = sorted(PRODUCTION_SUCCESS_RESULT_KEYS - set(result))
        unknown = sorted(set(result) - PRODUCTION_SUCCESS_RESULT_KEYS)
        raise ResearcherResultAdapterError(
            "RESULT_FIELDS_INVALID",
            f"missing={missing}; unknown={unknown}",
        )
    if result.get("schema_version") != CONTAINER_RESULT_SCHEMA:
        raise ResearcherResultAdapterError(
            "RESULT_SCHEMA_DRIFT",
            str(result.get("schema_version")),
        )
    _forbid_progress_claims(result, surface="result")
    status = result.get("status")
    if status not in _ALLOWED_STATUSES:
        raise ResearcherResultAdapterError("RESULT_STATUS_INVALID", str(status))
    _require_empty_reason_codes(result.get("reason_codes"), surface="result")
    for key in (
        "request_sha256",
        "prompt_sha256",
        "output_schema_sha256",
        "material_manifest_sha256",
        "material_packet_sha256",
        "effective_prompt_sha256",
    ):
        _require_hex64(result.get(key), "RESULT_HASH_FIELD_INVALID", key)
    bundle_id = result.get("material_bundle_id")
    if not isinstance(bundle_id, str) or _BUNDLE_ID.fullmatch(bundle_id) is None:
        raise ResearcherResultAdapterError("RESULT_BUNDLE_ID_INVALID", str(bundle_id))
    available = result.get("material_refs_available")
    if not isinstance(available, list):
        raise ResearcherResultAdapterError(
            "RESULT_MATERIAL_REFS_AVAILABLE_INVALID",
            "list required",
        )
    if (
        result.get("provider") != "grok"
        or result.get("requested_model") != "grok-4.5"
        or result.get("provider_stop_reason") != "EndTurn"
        or type(result.get("provider_num_turns")) is not int
        or result.get("provider_num_turns") != 1
        or result.get("provider_session_id_present") is not True
        or result.get("provider_request_id_present") is not True
        or result.get("completion_claim_allowed") is not False
        or result.get("science_restored") is not False
        or result.get("parent_complete") is not False
    ):
        raise ResearcherResultAdapterError(
            "RESULT_PROVIDER_BOUNDARY_INVALID",
            "provider/model/completion fields",
        )
    for key in ("provider_session_id", "provider_request_id"):
        if not _plain_json_text(
            result.get(key),
            nonempty=True,
            maximum_bytes=_MAX_PROVIDER_ID_BYTES,
        ):
            raise ResearcherResultAdapterError("RESULT_PROVIDER_ID_INVALID", key)
    model_usage = result.get("provider_model_usage")
    if not isinstance(model_usage, Mapping) or set(model_usage) != {"grok-4.5-build"}:
        raise ResearcherResultAdapterError(
            "RESULT_PROVIDER_MODEL_USAGE_INVALID",
            "exact grok-4.5-build key required",
        )
    usage = result.get("usage")
    if not isinstance(usage, Mapping):
        raise ResearcherResultAdapterError("RESULT_USAGE_INVALID", "object required")
    total_tokens = usage.get("total_tokens")
    if type(total_tokens) is not int or total_tokens <= 0:
        raise ResearcherResultAdapterError("RESULT_USAGE_INVALID", "total_tokens")

    candidate = _validate_research_candidate(
        result.get("candidate"),
        available_ids=available,
        expected_status=str(status),
        expected_bundle_id=str(bundle_id),
    )
    return {
        "status": str(status),
        "candidate": candidate,
        "material_bundle_id": str(bundle_id),
        "material_refs_available": list(available),
    }


def _stable_receipt_identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Receipt pins that may enter policy identity (no volatile observations)."""

    stable: dict[str, Any] = {}
    for key, value in receipt.items():
        if key in _RECEIPT_TRANSPORT_ONLY_KEYS or key in _RECEIPT_VOLATILE_TOP_LEVEL_KEYS:
            continue
        stable[key] = value
    # Stable subset of provider_egress (pins only; no live observation fingerprints).
    egress = receipt.get("provider_egress")
    if isinstance(egress, Mapping):
        stable["provider_egress_pins"] = {
            key: egress.get(key)
            for key in (
                "internal_network_name",
                "internal_network_id",
                "proxy_image_id",
                "proxy_endpoint",
                "allowlist_sha256",
                "proxy_config_sha256",
                "proxy_env_is_routing_hint_only",
                "dify_cross_project",
                "tls_interception",
                "source_provider_egress_runtime_verified",
                "completion_claim_allowed",
            )
            if key in egress
        }
    # Stable security posture without host mount paths.
    security = receipt.get("container_security")
    if isinstance(security, Mapping):
        stable["container_security_pins"] = {
            key: security.get(key)
            for key in (
                "readonly_rootfs",
                "cap_drop",
                "security_opt",
                "network_mode",
                "pids_limit",
                "memory",
                "nano_cpus",
                "privileged",
                "restart_policy",
                "tmpfs",
            )
            if key in security
        }
    return stable


def _validate_success_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_status: str,
    expected_result_sha: str,
    expected_candidate: Mapping[str, Any],
) -> dict[str, Any]:
    transport = {key: receipt[key] for key in _RECEIPT_TRANSPORT_ONLY_KEYS if key in receipt}
    core = {key: value for key, value in receipt.items() if key not in _RECEIPT_TRANSPORT_ONLY_KEYS}
    if set(core) != PRODUCTION_SUCCESS_RECEIPT_KEYS:
        missing = sorted(PRODUCTION_SUCCESS_RECEIPT_KEYS - set(core))
        unknown = sorted(set(core) - PRODUCTION_SUCCESS_RECEIPT_KEYS)
        raise ResearcherResultAdapterError(
            "RECEIPT_FIELDS_INVALID",
            f"missing={missing}; unknown={unknown}",
        )
    if core.get("schema_version") != SKILL_RESEARCH_RECEIPT_SCHEMA:
        raise ResearcherResultAdapterError(
            "RECEIPT_SCHEMA_DRIFT",
            str(core.get("schema_version")),
        )
    _forbid_progress_claims(core, surface="receipt")
    if core.get("status") != expected_status:
        raise ResearcherResultAdapterError(
            "RESULT_RECEIPT_STATUS_DRIFT",
            f"result={expected_status} receipt={core.get('status')}",
        )
    _require_empty_reason_codes(core.get("reason_codes"), surface="receipt")
    if core.get("route_class") != ROUTE_CLASS_SCIENTIFIC_RESEARCHER:
        raise ResearcherResultAdapterError(
            "RECEIPT_ROUTE_CLASS_INVALID",
            str(core.get("route_class")),
        )
    if core.get("ordinary_worker_chain_used") is not False:
        raise ResearcherResultAdapterError(
            "RECEIPT_ORDINARY_WORKER_CHAIN_FORBIDDEN",
            str(core.get("ordinary_worker_chain_used")),
        )
    observed_result_sha = _require_hex64(
        core.get("result_sha256"),
        "RECEIPT_RESULT_HASH_INVALID",
        "result_sha256",
    )
    if observed_result_sha != expected_result_sha:
        raise ResearcherResultAdapterError(
            "RESULT_RECEIPT_HASH_DRIFT",
            f"observed={observed_result_sha} expected={expected_result_sha}",
        )
    run_id = _require_text(core.get("run_id"), "RECEIPT_RUN_ID_INVALID", "run_id")
    for key in (
        "release_manifest_sha256",
        "execution_pointer_sha256",
        "skill_bundle_tree_sha256",
        "request_sha256",
        "base_prompt_sha256",
        "output_schema_sha256",
        "material_manifest_sha256",
        "material_packet_sha256",
        "effective_prompt_sha256",
    ):
        _require_hex64(core.get(key), "RECEIPT_HASH_FIELD_INVALID", key)
    for key in (
        "release_id",
        "execution_activation_txn_id",
        "package_version",
        "capability_version",
        "image_id",
        "result_path",
        "created_at",
        "release_manifest_path",
        "material_manifest_path",
    ):
        _require_text(core.get(key), "RECEIPT_PIN_INVALID", key)
    # Producer seal: REQUIRED_BOOTSTRAP_PROTOCOL = 2 (JSON integer). Reject bool/float/str.
    bootstrap_protocol = core.get("required_bootstrap_protocol")
    if type(bootstrap_protocol) is not int or bootstrap_protocol != 2:
        raise ResearcherResultAdapterError(
            "RECEIPT_BOOTSTRAP_PROTOCOL_INVALID",
            (
                "required_bootstrap_protocol must be exact JSON integer 2; "
                f"got {type(bootstrap_protocol).__name__} {bootstrap_protocol!r}"
            ),
        )
    if type(core.get("execution_pointer_generation")) is not int:
        raise ResearcherResultAdapterError(
            "RECEIPT_PIN_INVALID",
            "execution_pointer_generation",
        )
    if type(core.get("container_exit_code")) is not int or core.get("container_exit_code") != 0:
        raise ResearcherResultAdapterError("RECEIPT_CONTAINER_EXIT_INVALID", "exit code")
    if core.get("material_prompt_binding_verified") is not True:
        raise ResearcherResultAdapterError(
            "RECEIPT_MATERIAL_BINDING_INVALID",
            "material_prompt_binding_verified",
        )
    if not isinstance(core.get("material_use_claim_bound"), bool):
        raise ResearcherResultAdapterError(
            "RECEIPT_MATERIAL_BINDING_INVALID",
            "material_use_claim_bound",
        )
    if core.get("auth_handle_identity_unchanged") is not True:
        raise ResearcherResultAdapterError("RECEIPT_AUTH_HANDLE_INVALID", "auth handle")
    if core.get("user_operations_required") != []:
        raise ResearcherResultAdapterError(
            "RECEIPT_USER_OPERATIONS_INVALID",
            str(core.get("user_operations_required")),
        )
    provider_evidence = core.get("provider_evidence")
    if (
        not isinstance(provider_evidence, Mapping)
        or set(provider_evidence) != _PROVIDER_EVIDENCE_KEYS
    ):
        raise ResearcherResultAdapterError(
            "RECEIPT_PROVIDER_EVIDENCE_INVALID",
            "keys are not exact",
        )
    if (
        provider_evidence.get("stop_reason") != "EndTurn"
        or provider_evidence.get("num_turns") != 1
        or provider_evidence.get("session_id_present") is not True
        or provider_evidence.get("request_id_present") is not True
    ):
        raise ResearcherResultAdapterError(
            "RECEIPT_PROVIDER_EVIDENCE_INVALID",
            "provider terminal evidence",
        )
    receipt_candidate = _validate_research_candidate(
        core.get("candidate"),
        expected_status=expected_status,
        expected_bundle_id=str(expected_candidate.get("material_bundle_id")),
        expected_question=str(expected_candidate.get("research_question")),
        expected_as_of=str(expected_candidate.get("as_of")),
    )
    if canonical_sha256(expected_candidate) != canonical_sha256(receipt_candidate):
        raise ResearcherResultAdapterError(
            "RESULT_RECEIPT_CANDIDATE_DRIFT",
            "candidate object bytes disagree",
        )
    stable = _stable_receipt_identity(core)
    return {
        "run_id": run_id,
        "receipt_stable_sha256": canonical_sha256(stable),
        "candidate": receipt_candidate,
        "transport": transport,
    }


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
    observed_result_sha = raw_sha256(raw_result)
    expected_result_sha = _require_hex64(
        receipt_obj.get("result_sha256"),
        "RECEIPT_RESULT_HASH_INVALID",
        "result_sha256",
    )
    if observed_result_sha != expected_result_sha:
        raise ResearcherResultAdapterError(
            "RESULT_RECEIPT_HASH_DRIFT",
            f"observed={observed_result_sha} expected={expected_result_sha}",
        )

    result = _load_result(raw_result)
    validated_result = _validate_success_result(result)
    validated_receipt = _validate_success_receipt(
        receipt_obj,
        expected_status=validated_result["status"],
        expected_result_sha=observed_result_sha,
        expected_candidate=validated_result["candidate"],
    )
    return {
        "result_sha256": observed_result_sha,
        "receipt_content_sha256": validated_receipt["receipt_stable_sha256"],
        "run_id": validated_receipt["run_id"],
        "status": validated_result["status"],
        "candidate": validated_result["candidate"],
        "knowledge_cutoff": _parse_aware_timestamp(
            validated_result["candidate"]["as_of"],
            "as_of",
        ),
    }


def mint_policy_candidate_from_verified_binding(
    binding: Mapping[str, Any],
) -> PolicyCandidateVersion:
    """Mint one content-addressed PolicyCandidateVersion from a verified binding.

    The decision_map_ref is an explicit not-projected sentinel bound to the result
    hash. Research prose is never compiled into an action decision_map.

    Policy identity (policy_ref + content_hash) binds result bytes and stable
    receipt pins only. Volatile receipt observations (paths, timestamps,
    container ids, live egress fingerprints, host mounts) do not move identity.
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
        "route_class": ROUTE_CLASS_SCIENTIFIC_RESEARCHER,
        "provider_id_key_seam": (
            "producer_formal_result_includes_raw_provider_session_and_request_ids;"
            "runtime_exact_allowlist_lags_present_flags_only"
        ),
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
    "PRODUCTION_SUCCESS_RECEIPT_KEYS",
    "PRODUCTION_SUCCESS_RESULT_KEYS",
    "RESEARCH_CANDIDATE_SCHEMA",
    "ROUTE_CLASS_SCIENTIFIC_RESEARCHER",
    "SKILL_RESEARCH_RECEIPT_SCHEMA",
    "ResearcherResultAdapterError",
    "adapt_researcher_result_to_policy_candidate",
    "mint_policy_candidate_from_verified_binding",
    "raw_sha256",
    "strict_json_loads",
    "verify_researcher_result_against_receipt",
]
