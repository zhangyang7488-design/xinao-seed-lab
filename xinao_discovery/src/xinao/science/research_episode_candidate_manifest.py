"""Pure ResearchEpisode candidate-manifest schema, constants, and validator.

Single source of truth for host package consumers (xinao-discovery wheel),
pool adapter, and image-side COPY of these exact bytes. No Docker/CLI deps.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

CANDIDATE_MANIFEST_SCHEMA: Final = "xinao.research_episode_candidate_manifest.v1"
CANDIDATE_MANIFEST_MARKER: Final = "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1"
CANDIDATE_MANIFEST_RELATIVE: Final = "candidate/candidate_manifest.v1.json"
AUTHORING_CONTRACT_SCHEMA: Final = (
    "xinao.research_episode_candidate_manifest_authoring_contract.v1"
)
ACCOUNT_RECOMMENDATION_VALUES: Final = frozenset(
    {
        "ACTION_CANDIDATE",
        "NO_ACTION_CANDIDATE",
        "NO_RECOMMENDATION",
    }
)
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_STAKE = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{4}$")
_ACTOR_INTENT_REQUIRED = frozenset(
    {
        "schema_version",
        "authored_at",
        "decision_kind",
        "stake",
        "research_rationale",
    }
)
_ACTOR_INTENT_OPTIONAL = frozenset(
    {
        "panel",
        "selected_number",
        "after_hit_response",
        "after_miss_response",
        "next_round_or_stop_response",
        "content_hash",
    }
)


class CandidateManifestError(ValueError):
    """Fail-closed candidate manifest rejection (package + native re-export)."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def module_source_path() -> Path:
    """Absolute path of this canonical module (for image seal / byte-identity checks)."""
    return Path(__file__).resolve()


def module_source_sha256() -> str:
    """Seal of these exact source bytes (release/image evidence pin)."""
    return hashlib.sha256(module_source_path().read_bytes()).hexdigest()


def candidate_manifest_authoring_contract() -> dict[str, Any]:
    """Return the syntax contract shown to a complete actor before lab authoring.

    This describes how to serialize the actor's own choice.  It deliberately
    supplies no decision, number, stake, rationale, method, or stop policy.
    """

    return {
        "schema_version": AUTHORING_CONTRACT_SCHEMA,
        "purpose": "SERIALIZE_ACTOR_AUTHORED_CHOICE_ONLY",
        "candidate_manifest_path": CANDIDATE_MANIFEST_RELATIVE,
        "candidate_manifest_schema": CANDIDATE_MANIFEST_SCHEMA,
        "candidate_manifest_marker": CANDIDATE_MANIFEST_MARKER,
        "required_top_level_fields": [
            "schema_version",
            "manifest_marker",
            "candidate_id",
            "candidate_version",
            "research_question",
            "research_object",
            "data_cutoff",
            "account_recommendation",
            "candidate_only",
            "owner_adopted",
        ],
        "required_top_level_one_of": [
            ["method_refs", "methods"],
            ["falsifiers", "limitations"],
            ["completion", "completion_claim_allowed"],
        ],
        "account_recommendation_values": sorted(ACCOUNT_RECOMMENDATION_VALUES),
        "complete_actor_recommendation_values": [
            "ACTION_CANDIDATE",
            "NO_ACTION_CANDIDATE",
        ],
        "account_branch_mapping": {
            "ACTION": "ACTION_CANDIDATE",
            "NO_ACTION": "NO_ACTION_CANDIDATE",
            "SIGNAL_ONLY_WITHOUT_ACCOUNT_CHOICE": "NO_RECOMMENDATION",
        },
        "actor_intent": {
            "location": "proposed",
            "schema_version": "xinao.actor_authored_behavior_intent.v1",
            "required_fields": sorted(_ACTOR_INTENT_REQUIRED),
            "optional_fields": sorted(_ACTOR_INTENT_OPTIONAL),
            "authored_at": "timezone-aware ISO-8601 time when the actor authored this choice",
            "research_rationale": "non-empty actor-authored rationale",
            "stake_format": "canonical decimal string with exactly four fractional digits",
            "ACTION": {
                "decision_kind": "ACTION",
                "stake": "strictly positive",
                "panel": "A or B",
                "selected_number": "integer 1..49",
            },
            "NO_ACTION": {
                "decision_kind": "NO_ACTION",
                "stake": "0.0000",
                "panel": None,
                "selected_number": None,
            },
            "content_hash": "optional; omit unless computed exactly by the canonical validator",
        },
        "candidate_authority": {
            "candidate_only": True,
            "owner_adopted": False,
            "completion": False,
            "forbidden_claims": [
                "account_identity",
                "science_disposition",
                "frozen",
                "parent_complete",
                "science_restored",
            ],
        },
        "legacy_aliases_forbidden": {
            "account_recommendation": ["ACTION", "RESEARCHER_ACCOUNT_NO_ACTION"],
            "actor_intent_fields": ["decision", "selection", "reasoning_one_line"],
        },
        "actor_choice_fields_supplied_by_contract": [],
    }


def _normalized_actor_intent_content(intent: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize exactly as ``ActorAuthoredBehaviorIntent.canonical_content``.

    This module is copied into the researcher image as a dependency-light
    validator, so it cannot import the lifecycle Pydantic model there.  The
    intent contains only JSON primitives; this normalizer mirrors the model's
    datetime JSON form and explicit ``null`` defaults before hashing.
    """

    authored = str(intent["authored_at"])
    try:
        parsed = datetime.fromisoformat(authored.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "authored_at"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "authored_at aware required"
        )
    authored_json = parsed.isoformat().replace("+00:00", "Z")
    return {
        "schema_version": intent["schema_version"],
        "authored_at": authored_json,
        "decision_kind": intent["decision_kind"],
        "panel": intent.get("panel"),
        "selected_number": intent.get("selected_number"),
        "stake": intent["stake"],
        "research_rationale": intent["research_rationale"],
        "after_hit_response": intent.get("after_hit_response"),
        "after_miss_response": intent.get("after_miss_response"),
        "next_round_or_stop_response": intent.get("next_round_or_stop_response"),
    }


def actor_intent_content_hash(intent: Mapping[str, Any]) -> str:
    normalized = _normalized_actor_intent_content(intent)
    raw = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_actor_authored_behavior_intent(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the only behavior payload a ResearchEpisode actor authors.

    Identity, bankroll, target/timing, objective odds/rule, and information-set
    provenance are intentionally forbidden here.  Those reality fields are
    mechanically joined later from the exact live attempt and portfolio.
    """

    intent = dict(payload)
    observed = set(intent)
    if (
        not _ACTOR_INTENT_REQUIRED.issubset(observed)
        or observed - _ACTOR_INTENT_REQUIRED - _ACTOR_INTENT_OPTIONAL
    ):
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID",
            "required/optional keys are invalid",
        )
    if intent.get("schema_version") != "xinao.actor_authored_behavior_intent.v1":
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "schema_version"
        )
    _normalized_actor_intent_content(intent)
    rationale = intent.get("research_rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "research_rationale"
        )
    for field in (
        "after_hit_response",
        "after_miss_response",
        "next_round_or_stop_response",
    ):
        response = intent.get(field)
        if response is not None and (not isinstance(response, str) or not response.strip()):
            raise CandidateManifestError(
                "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", field
            )
    stake = intent.get("stake")
    if not isinstance(stake, str) or _CANONICAL_STAKE.fullmatch(stake) is None:
        raise CandidateManifestError("CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "stake")
    try:
        amount = Decimal(stake)
    except InvalidOperation as exc:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "stake"
        ) from exc
    decision_kind = intent.get("decision_kind")
    if decision_kind == "ACTION":
        selected = intent.get("selected_number")
        if (
            amount <= 0
            or intent.get("panel") not in {"A", "B"}
            or type(selected) is not int
            or not 1 <= selected <= 49
        ):
            raise CandidateManifestError(
                "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "ACTION fields"
            )
    elif decision_kind == "NO_ACTION":
        if (
            amount != 0
            or intent.get("panel") is not None
            or intent.get("selected_number") is not None
        ):
            raise CandidateManifestError(
                "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "NO_ACTION fields"
            )
    else:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "decision_kind"
        )
    claimed = intent.get("content_hash")
    if claimed is not None and (
        not isinstance(claimed, str)
        or _HEX_SHA256.fullmatch(claimed) is None
        or claimed != actor_intent_content_hash(intent)
    ):
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID", "content_hash"
        )
    return intent


def validate_candidate_manifest(
    payload: Mapping[str, Any] | bytes,
    *,
    expected_episode_id: str | None = None,
    expected_attempt_cas_digest: str | None = None,
) -> dict[str, Any]:
    """Validate closed lab-authored candidate manifest schema (candidate-only)."""
    if isinstance(payload, (bytes, bytearray)):
        try:
            obj = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CandidateManifestError("CANDIDATE_MANIFEST_JSON_INVALID", str(exc)) from exc
    else:
        obj = dict(payload)
    if not isinstance(obj, dict):
        raise CandidateManifestError("CANDIDATE_MANIFEST_JSON_INVALID", "object required")
    if obj.get("schema_version") != CANDIDATE_MANIFEST_SCHEMA:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_SCHEMA_INVALID",
            str(obj.get("schema_version")),
        )
    if obj.get("manifest_marker") != CANDIDATE_MANIFEST_MARKER:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_MARKER_INVALID",
            str(obj.get("manifest_marker")),
        )
    for key in (
        "candidate_id",
        "candidate_version",
        "research_question",
        "research_object",
        "account_recommendation",
    ):
        if not isinstance(obj.get(key), str) or not str(obj.get(key)).strip():
            raise CandidateManifestError("CANDIDATE_MANIFEST_FIELD_INVALID", key)
    if obj.get("account_recommendation") not in ACCOUNT_RECOMMENDATION_VALUES:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_RECOMMENDATION_INVALID",
            str(obj.get("account_recommendation")),
        )
    data_cutoff = obj.get("data_cutoff")
    if not isinstance(data_cutoff, Mapping):
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_CUTOFF_INVALID", "data_cutoff object required"
        )
    if not isinstance(data_cutoff.get("as_of"), str) or not str(data_cutoff.get("as_of")).strip():
        raise CandidateManifestError("CANDIDATE_MANIFEST_CUTOFF_INVALID", "as_of required")
    material_refs = data_cutoff.get("material_refs") or []
    if not isinstance(material_refs, list):
        raise CandidateManifestError("CANDIDATE_MANIFEST_CUTOFF_INVALID", "material_refs list")
    for ref in material_refs:
        if not isinstance(ref, Mapping):
            raise CandidateManifestError("CANDIDATE_MANIFEST_CUTOFF_INVALID", "material_ref object")
        digest = ref.get("sha256")
        if not isinstance(digest, str) or _HEX_SHA256.fullmatch(digest) is None:
            raise CandidateManifestError("CANDIDATE_MANIFEST_CUTOFF_INVALID", "material_ref.sha256")
    methods = obj.get("method_refs") or obj.get("methods")
    if methods is None:
        raise CandidateManifestError("CANDIDATE_MANIFEST_METHODS_INVALID", "method_refs required")
    # Wild / overfit / black-box methods are allowed; only type-check structure.
    if not isinstance(methods, (list, Mapping, str)):
        raise CandidateManifestError("CANDIDATE_MANIFEST_METHODS_INVALID", type(methods).__name__)
    falsifiers = obj.get("falsifiers") or obj.get("limitations")
    if falsifiers is None:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_LIMITATIONS_INVALID", "falsifiers/limitations"
        )
    if not isinstance(falsifiers, list):
        raise CandidateManifestError("CANDIDATE_MANIFEST_LIMITATIONS_INVALID", "list required")
    # Candidate-only authority clamps (never Owner disposition / completion).
    if obj.get("owner_adopted") is not False:
        raise CandidateManifestError("CANDIDATE_MANIFEST_OWNER_ADOPTED_FORBIDDEN", "must be false")
    if obj.get("completion") is not False and obj.get("completion_claim_allowed") is not False:
        # Accept either key; both must be false when present. Require at least completion=false.
        if "completion" not in obj and "completion_claim_allowed" not in obj:
            raise CandidateManifestError(
                "CANDIDATE_MANIFEST_COMPLETION_MISSING", "completion=false"
            )
        if obj.get("completion") is True or obj.get("completion_claim_allowed") is True:
            raise CandidateManifestError("CANDIDATE_MANIFEST_COMPLETION_FORBIDDEN", "must be false")
    if obj.get("candidate_only") is not True:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_CANDIDATE_ONLY_REQUIRED", "candidate_only=true"
        )
    for forbidden, reason in (
        ("account_identity", "ACCOUNT_IDENTITY_FORBIDDEN"),
        ("science_disposition", "SCIENCE_DISPOSITION_FORBIDDEN"),
        ("frozen", "FREEZE_CLAIM_FORBIDDEN"),
        ("parent_complete", "PARENT_COMPLETE_FORBIDDEN"),
        ("science_restored", "SCIENCE_RESTORED_FORBIDDEN"),
    ):
        if obj.get(forbidden) not in {None, False}:
            raise CandidateManifestError(f"CANDIDATE_MANIFEST_{reason}", forbidden)
    if (
        expected_episode_id is not None
        and obj.get("episode_id") not in {None, expected_episode_id}
        and obj.get("episode_id") != expected_episode_id
    ):
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_EPISODE_MISMATCH",
            f"{obj.get('episode_id')}!={expected_episode_id}",
        )
    if (
        expected_attempt_cas_digest is not None
        and obj.get("attempt_cas_digest") not in {None, expected_attempt_cas_digest}
        and obj.get("attempt_cas_digest") != expected_attempt_cas_digest
    ):
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ATTEMPT_MISMATCH",
            f"{obj.get('attempt_cas_digest')}!={expected_attempt_cas_digest}",
        )
    # For an account-branch claim, ``proposed`` is the actor's sealed choice,
    # never a platform-authored full account decision.  NO_RECOMMENDATION stays
    # a legal signal-only candidate and need not carry any behavior intent.
    proposed = obj.get("proposed") or obj.get("proposed_numbers")
    if proposed is not None and not isinstance(proposed, (Mapping, list)):
        raise CandidateManifestError("CANDIDATE_MANIFEST_PROPOSED_INVALID", type(proposed).__name__)
    recommendation = str(obj["account_recommendation"])
    if recommendation in {"ACTION_CANDIDATE", "NO_ACTION_CANDIDATE"}:
        if not isinstance(proposed, Mapping):
            raise CandidateManifestError(
                "CANDIDATE_MANIFEST_ACTOR_INTENT_REQUIRED", recommendation
            )
        intent = validate_actor_authored_behavior_intent(proposed)
        expected_kind = "ACTION" if recommendation == "ACTION_CANDIDATE" else "NO_ACTION"
        if intent.get("decision_kind") != expected_kind:
            raise CandidateManifestError(
                "CANDIDATE_MANIFEST_ACTOR_INTENT_BRANCH_MISMATCH",
                f"recommendation={recommendation} intent={intent.get('decision_kind')}",
            )
    return obj


__all__ = [
    "ACCOUNT_RECOMMENDATION_VALUES",
    "AUTHORING_CONTRACT_SCHEMA",
    "CANDIDATE_MANIFEST_MARKER",
    "CANDIDATE_MANIFEST_RELATIVE",
    "CANDIDATE_MANIFEST_SCHEMA",
    "CandidateManifestError",
    "actor_intent_content_hash",
    "candidate_manifest_authoring_contract",
    "module_source_path",
    "module_source_sha256",
    "validate_actor_authored_behavior_intent",
    "validate_candidate_manifest",
]
