"""Disposition-bound freeze adapter over existing shadow_lifecycle consumer.

Builds a freeze request from a verified pool entry + Codex owner disposition,
then calls existing ``freeze_episode`` / ``freeze_portfolio_period``. Does not
copy the ledger, alter freeze semantics, loop the next period, or start
daemon/Temporal/Goal. Researchers still cannot write shadow state through this
module.

Research identity is sealed as a content-addressed
``xinao.research_freeze_binding.v1`` side object. Its raw hash is embedded in
immutable ``science_decision_ref`` / ``account_decision_ref`` (and ACTION
``information_set_hash``) so it participates in ``frozen.content_hash``.
Receipt binding fields remain display-only and are not authority.

File-backed freeze trusts caller-supplied timestamps only:
``trusted_time_proof=false`` is always reported honestly for this path.

Library/worker outputs never self-certify Owner authenticity.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal

from xinao.canonical import canonical_sha256
from xinao.science.owner_disposition import (
    ACCOUNT_ACTION,
    ACCOUNT_NO_ACTION,
    OWNER_CHANNEL_AUTHORITY_UNPROVEN,
    OwnerDispositionError,
    disposition_information_set_hash,
    load_and_verify_disposition,
    require_period_account_identity,
)
from xinao.shadow_lifecycle.consumer import freeze_episode, freeze_portfolio_period
from xinao.shadow_lifecycle.store import (
    PortfolioPeriodPhase,
    StoreError,
    derive_portfolio_head,
    load_feedback,
    load_frozen,
    load_portfolio,
    load_seat,
    load_settled,
    period_directory,
    resolve_root,
)

ADAPTER_MARKER: Final = "XINAO_DISPOSITION_FREEZE_ADAPTER_V1"
SPECIAL_NUMBER_RULE: Final = "special-number-rule.v1"
RESEARCH_BINDING_SCHEMA: Final = "xinao.research_freeze_binding.v1"
RESEARCH_BINDING_MARKER: Final = "XINAO_RESEARCH_FREEZE_BINDING_V1"
RESEARCH_BINDING_REF_PREFIX: Final = "research-binding.sha256:"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINDING_REF_RE = re.compile(rf"{re.escape(RESEARCH_BINDING_REF_PREFIX)}([0-9a-f]{{64}})")

# Import-surface guard: this module must not pull Temporal/Goal control planes.
_FORBIDDEN_IMPORT_TOKENS: Final = frozenset(
    {
        "temporalio",
        "temporal",
        "root_intent_loop",
        "GoalWorkflow",
    }
)


class FreezeAdapterError(ValueError):
    """Fail-closed freeze adapter rejection."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _require_hex64(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise FreezeAdapterError("FREEZE_HASH_INVALID", f"{label} must be lowercase sha256")
    return value


def _raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _no_peek_guard(request: Mapping[str, Any]) -> None:
    for forbidden in ("outcome", "actual_special_number", "settlement", "settled"):
        if forbidden in request:
            raise FreezeAdapterError(
                "FREEZE_NO_PEEK_VIOLATION",
                f"request must not include {forbidden!r}",
            )


def research_binding_path(shadow_root: Path, binding_sha256: str) -> Path:
    digest = _require_hex64(binding_sha256, "research_binding_sha256")
    base = resolve_root(shadow_root)
    return base / "objects" / "research_binding" / "sha256" / digest[:2] / f"{digest}.json"


def encode_research_binding_bytes(body: Mapping[str, Any]) -> bytes:
    if "content_hash" in body or "research_binding_sha256" in body:
        raise FreezeAdapterError(
            "RESEARCH_BINDING_SELF_HASH_FORBIDDEN",
            "binding body must not embed its own hash",
        )
    return (json.dumps(dict(body), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _normalized_executable_intent(disposition: Mapping[str, Any]) -> dict[str, Any]:
    """Closed executable account intent sealed into the research binding."""

    account_identity = require_period_account_identity(disposition)
    if account_identity == ACCOUNT_ACTION:
        executable = disposition.get("executable_account_decision")
        if not isinstance(executable, Mapping):
            raise FreezeAdapterError(
                "ACTION_REQUIRES_EXECUTABLE_DECISION",
                "cannot seal ACTION intent without structured executable decision",
            )
        intent: dict[str, Any] = {
            "account_identity": ACCOUNT_ACTION,
            "panel": executable["panel"],
            "selected_number": executable["selected_number"],
            "stake": str(executable["stake"]),
            "rule_ref": str(executable["rule_ref"]),
            "odds_version_ref": str(executable["odds_version_ref"]),
            "baseline_ref": str(executable["baseline_ref"]),
            "risk_policy_ref": str(executable["risk_policy_ref"]),
            "target_ref": str(executable["target_ref"]),
            "target_open_time": str(executable["target_open_time"]),
            "freeze_deadline": str(executable["freeze_deadline"]),
            "frozen_at": str(executable["frozen_at"]),
            "knowledge_cutoff": str(executable["knowledge_cutoff"]),
        }
        if executable.get("ticket_ref") is not None:
            intent["ticket_ref"] = str(executable["ticket_ref"])
        if executable.get("information_set_ref") is not None:
            intent["information_set_ref"] = str(executable["information_set_ref"])
        return intent

    binding = disposition.get("no_action_period_binding")
    if not isinstance(binding, Mapping):
        raise FreezeAdapterError(
            "NO_ACTION_BINDING_REQUIRED",
            "cannot seal NO_ACTION intent without no_action_period_binding",
        )
    return {
        "account_identity": ACCOUNT_NO_ACTION,
        "selected_number": None,
        "stake": "0.0000",
        "rule_ref": str(binding["rule_ref"]),
        "odds_version_ref": str(binding["odds_version_ref"]),
        "target_ref": str(binding["target_ref"]),
        "target_open_time": str(binding["target_open_time"]),
        "freeze_deadline": str(binding["freeze_deadline"]),
        "frozen_at": str(binding["frozen_at"]),
        "knowledge_cutoff": str(binding["knowledge_cutoff"]),
    }


def build_portfolio_binding_from_shadow(shadow_root: Path) -> dict[str, Any]:
    """Derive closed portfolio/head identity from the live sealed shadow root."""

    base = resolve_root(shadow_root)
    try:
        seat = load_seat(base)
        portfolio = load_portfolio(base)
        head = derive_portfolio_head(base)
    except StoreError as exc:
        raise FreezeAdapterError("PORTFOLIO_HEAD_INSPECT_FAILED", str(exc)) from exc

    if head.period_index == 0:
        intended = 1
        prior_settled: str | None = None
        prior_feedback: str | None = None
    elif head.phase in {PortfolioPeriodPhase.MISSING, PortfolioPeriodPhase.INIT}:
        intended = head.period_index
        if intended == 1:
            prior_settled = None
            prior_feedback = None
        else:
            try:
                prior_root = period_directory(base, intended - 1)
                prior_settled = load_settled(prior_root).content_hash
                prior_feedback = load_feedback(prior_root).content_hash
            except StoreError as exc:
                raise FreezeAdapterError(
                    "PORTFOLIO_PRIOR_HEAD_UNAVAILABLE",
                    str(exc),
                ) from exc
    elif head.phase == PortfolioPeriodPhase.FEEDBACK_SEALED:
        intended = head.period_index + 1
        prior_settled = head.settled_episode_hash
        prior_feedback = head.feedback_hash
    else:
        raise FreezeAdapterError(
            "FREEZE_PORTFOLIO_HEAD_NOT_READY",
            f"portfolio cannot freeze while head is {head.phase.value}",
        )

    return {
        "portfolio_ref": portfolio.portfolio_ref,
        "portfolio_content_hash": portfolio.content_hash,
        "seat_id": seat.seat_id,
        "seat_content_hash": seat.content_hash,
        "head_period_index": head.period_index,
        "head_phase": head.phase.value,
        "prior_settled_episode_hash": prior_settled,
        "prior_feedback_hash": prior_feedback,
        "intended_next_period_index": intended,
    }


def assert_portfolio_binding_matches_shadow(
    *,
    disposition: Mapping[str, Any],
    shadow_root: Path,
) -> dict[str, Any]:
    """Require exact portfolio/head equality before any binding/request/freeze write."""

    claimed = disposition.get("portfolio_binding")
    if not isinstance(claimed, Mapping):
        raise FreezeAdapterError(
            "PORTFOLIO_BINDING_REQUIRED",
            "portfolio mode disposition must carry closed portfolio_binding",
        )
    live = build_portfolio_binding_from_shadow(shadow_root)
    # Exact field equality (portfolio A disposition must fail on portfolio B).
    for key in (
        "portfolio_ref",
        "portfolio_content_hash",
        "seat_id",
        "seat_content_hash",
        "head_period_index",
        "head_phase",
        "prior_settled_episode_hash",
        "prior_feedback_hash",
        "intended_next_period_index",
    ):
        if claimed.get(key) != live.get(key):
            raise FreezeAdapterError(
                "PORTFOLIO_HEAD_BINDING_MISMATCH",
                f"{key}: disposition={claimed.get(key)!r} live={live.get(key)!r}",
            )
    if int(claimed["intended_next_period_index"]) != int(disposition["period_index"]):
        raise FreezeAdapterError(
            "PORTFOLIO_BINDING_PERIOD_MISMATCH",
            "intended_next_period_index disagrees with disposition.period_index",
        )
    return live


def build_research_freeze_binding(
    *,
    pool_entry: Mapping[str, Any],
    disposition: Mapping[str, Any],
    owner_artifact_sha256: str,
    portfolio_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the immutable research freeze binding body (no self-hash)."""

    owner_hash = _require_hex64(owner_artifact_sha256, "owner_artifact_sha256")
    executable_intent = _normalized_executable_intent(disposition)
    body: dict[str, Any] = {
        "schema_version": RESEARCH_BINDING_SCHEMA,
        "binding_marker": RESEARCH_BINDING_MARKER,
        "result_sha256": str(pool_entry["result_sha256"]),
        "receipt_content_sha256": str(pool_entry["receipt_content_sha256"]),
        "pool_entry_content_hash": str(pool_entry["content_hash"]),
        "policy_ref": str(pool_entry["policy_ref"]),
        "owner_artifact_sha256": owner_hash,
        "period_index": int(disposition["period_index"]),
        "episode_ref": str(disposition["episode_ref"]),
        "target_ref": str(disposition["target_ref"]),
        "science_disposition": str(disposition["science_disposition"]),
        "account_identity": str(disposition["account_identity"]),
        "science_identity": str(disposition["science_identity"]),
        "knowledge_cutoff": str(disposition["knowledge_cutoff"]),
        "executable_account_intent": executable_intent,
        # Flat episode mode keeps portfolio identity explicitly absent (not faked).
        "portfolio_binding": dict(portfolio_binding) if portfolio_binding is not None else None,
        "scientific_promotion": False,
        "owner_adopted": False,
    }
    return body


def write_research_binding_exclusive(
    *,
    shadow_root: Path,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    """Content-addressed exclusive write of the research freeze binding side object."""

    raw = encode_research_binding_bytes(body)
    digest = _raw_sha256(raw)
    path = research_binding_path(shadow_root, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
    except FileExistsError as exc:
        existing = path.read_bytes()
        if existing != raw:
            raise FreezeAdapterError(
                "RESEARCH_BINDING_CAS_CONFLICT",
                f"binding {digest} already sealed with different bytes",
            ) from exc
        return {
            "research_binding_sha256": digest,
            "path": str(path),
            "bytes_written": False,
            "body": dict(body),
        }
    return {
        "research_binding_sha256": digest,
        "path": str(path),
        "bytes_written": True,
        "body": dict(body),
    }


def load_research_binding(shadow_root: Path, binding_sha256: str) -> dict[str, Any]:
    """Load and re-verify a content-addressed research freeze binding."""

    digest = _require_hex64(binding_sha256, "research_binding_sha256")
    path = research_binding_path(shadow_root, digest)
    if not path.is_file():
        raise FreezeAdapterError("RESEARCH_BINDING_MISSING", digest)
    raw = path.read_bytes()
    if _raw_sha256(raw) != digest:
        raise FreezeAdapterError("RESEARCH_BINDING_BYTES_TAMPERED", digest)
    if path.name != f"{digest}.json" or path.parent.name != digest[:2]:
        raise FreezeAdapterError("RESEARCH_BINDING_PATH_MISMATCH", str(path))
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreezeAdapterError("RESEARCH_BINDING_JSON_INVALID", str(exc)) from exc
    if not isinstance(payload, dict):
        raise FreezeAdapterError("RESEARCH_BINDING_JSON_INVALID", "object required")
    if payload.get("schema_version") != RESEARCH_BINDING_SCHEMA:
        raise FreezeAdapterError(
            "RESEARCH_BINDING_SCHEMA_DRIFT",
            str(payload.get("schema_version")),
        )
    if payload.get("binding_marker") != RESEARCH_BINDING_MARKER:
        raise FreezeAdapterError(
            "RESEARCH_BINDING_MARKER_INVALID",
            str(payload.get("binding_marker")),
        )
    return payload


def extract_research_binding_hash_from_refs(
    *,
    science_decision_ref: str,
    account_decision_ref: str,
) -> str:
    sci = _BINDING_REF_RE.search(science_decision_ref)
    acc = _BINDING_REF_RE.search(account_decision_ref)
    if sci is None or acc is None:
        raise FreezeAdapterError(
            "RESEARCH_BINDING_REF_MISSING",
            "science_decision_ref and account_decision_ref must embed "
            f"{RESEARCH_BINDING_REF_PREFIX}<hash>",
        )
    if sci.group(1) != acc.group(1):
        raise FreezeAdapterError(
            "RESEARCH_BINDING_REF_MISMATCH",
            "science/account decision refs disagree on binding hash",
        )
    return sci.group(1)


def extract_research_binding_hash_from_frozen(frozen: Any) -> str:
    return extract_research_binding_hash_from_refs(
        science_decision_ref=str(frozen.science_decision.science_decision_ref),
        account_decision_ref=str(frozen.account_decision.account_decision_ref),
    )


def expected_next_period_index(shadow_root: Path) -> int:
    """Compute the legal next portfolio period without creating directories."""

    base = resolve_root(shadow_root)
    head = derive_portfolio_head(base)
    if head.period_index == 0:
        return 1
    if head.phase in {PortfolioPeriodPhase.MISSING, PortfolioPeriodPhase.INIT}:
        return head.period_index
    if head.phase == PortfolioPeriodPhase.FEEDBACK_SEALED:
        return head.period_index + 1
    raise FreezeAdapterError(
        "FREEZE_PORTFOLIO_HEAD_NOT_READY",
        f"portfolio cannot freeze while head is {head.phase.value}",
    )


def _science_branch_from_disposition(
    *,
    disposition: Mapping[str, Any],
    pool_entry: Mapping[str, Any],
    research_binding_sha256: str,
) -> dict[str, Any]:
    science_identity = disposition.get("science_identity")
    if science_identity not in ("SCIENCE_CANDIDATE", "POLICY_NO_ACTION"):
        raise FreezeAdapterError("FREEZE_SCIENCE_IDENTITY_INVALID", str(science_identity))
    knowledge_cutoff = disposition["knowledge_cutoff"]
    binding_token = f"{RESEARCH_BINDING_REF_PREFIX}{research_binding_sha256}"
    science: dict[str, Any] = {
        # Binding token is the sealed authority link; candidate_ref stays policy_ref.
        "science_decision_ref": binding_token,
        "identity": science_identity,
        "knowledge_cutoff": knowledge_cutoff,
        "rationale_ref": disposition["rationale_ref"],
    }
    if science_identity == "SCIENCE_CANDIDATE":
        science["candidate_ref"] = str(pool_entry["policy_ref"])
    return science


def _build_action_ticket(
    *,
    disposition: Mapping[str, Any],
    pool_entry: Mapping[str, Any],
    research_binding_sha256: str,
) -> dict[str, Any]:
    executable = disposition.get("executable_account_decision")
    if not isinstance(executable, Mapping):
        raise FreezeAdapterError(
            "ACTION_REQUIRES_EXECUTABLE_DECISION",
            "cannot build ACTION ticket without structured executable decision",
        )
    result_sha256 = str(pool_entry["result_sha256"])
    receipt_content_sha256 = str(pool_entry["receipt_content_sha256"])
    target_ref = str(executable["target_ref"])
    info_hash = disposition_information_set_hash(
        result_sha256=result_sha256,
        receipt_content_sha256=receipt_content_sha256,
        target_ref=target_ref,
        research_binding_sha256=research_binding_sha256,
    )
    ticket_ref = executable.get("ticket_ref") or f"account-ticket.{disposition['episode_ref']}"
    information_set_ref = (
        executable.get("information_set_ref")
        or f"information.result.{result_sha256[:16]}.{target_ref}"
    )
    return {
        "ticket_ref": str(ticket_ref),
        "target_ref": target_ref,
        "target_open_time": str(executable["target_open_time"]),
        "freeze_deadline": str(executable["freeze_deadline"]),
        "knowledge_cutoff": str(executable["knowledge_cutoff"]),
        "frozen_at": str(executable["frozen_at"]),
        "panel": executable["panel"],
        "selected_number": executable["selected_number"],
        "stake": str(executable["stake"]),
        "rule_ref": SPECIAL_NUMBER_RULE,
        "odds_version_ref": str(executable["odds_version_ref"]),
        "baseline_ref": str(executable["baseline_ref"]),
        "risk_policy_ref": str(executable["risk_policy_ref"]),
        "information_set_ref": str(information_set_ref),
        "information_set_hash": info_hash,
    }


def build_freeze_request_from_disposition(
    *,
    pool_entry: Mapping[str, Any],
    disposition: Mapping[str, Any],
    owner_artifact_sha256: str,
    research_binding_sha256: str,
) -> dict[str, Any]:
    """Build a shadow consumer freeze request dict (AccountRiskTicket path for ACTION)."""

    account_identity = require_period_account_identity(disposition)
    if disposition.get("result_sha256") != pool_entry.get("result_sha256"):
        raise FreezeAdapterError(
            "FREEZE_POOL_DISPOSITION_MISMATCH",
            "result_sha256 disagree",
        )
    if disposition.get("pool_entry_content_hash") != pool_entry.get("content_hash"):
        raise FreezeAdapterError(
            "FREEZE_POOL_ENTRY_HASH_MISMATCH",
            "pool_entry_content_hash disagree",
        )

    binding_hash = _require_hex64(research_binding_sha256, "research_binding_sha256")
    binding_token = f"{RESEARCH_BINDING_REF_PREFIX}{binding_hash}"
    episode_ref = str(disposition["episode_ref"])
    science = _science_branch_from_disposition(
        disposition=disposition,
        pool_entry=pool_entry,
        research_binding_sha256=binding_hash,
    )

    request: dict[str, Any] = {
        "episode_ref": episode_ref,
        "science_decision": science,
        "account_decision": {
            # Same immutable binding token enters account_decision_ref.
            "account_decision_ref": binding_token,
            "identity": account_identity,
        },
        # Display-only receipt fields (not freeze-seal authority).
        "bound_result_sha256": pool_entry["result_sha256"],
        "bound_receipt_content_sha256": pool_entry["receipt_content_sha256"],
        "bound_pool_entry_content_hash": pool_entry["content_hash"],
        "bound_owner_artifact_sha256": _require_hex64(
            owner_artifact_sha256,
            "owner_artifact_sha256",
        ),
        "bound_policy_ref": pool_entry.get("policy_ref"),
        "bound_research_binding_sha256": binding_hash,
        "disposition_adapter_marker": ADAPTER_MARKER,
        "trusted_time_proof": False,
    }

    if account_identity == ACCOUNT_ACTION:
        ticket = _build_action_ticket(
            disposition=disposition,
            pool_entry=pool_entry,
            research_binding_sha256=binding_hash,
        )
        request["bound_account_ticket"] = ticket
        request["target_ref"] = ticket["target_ref"]
        request["target_open_time"] = ticket["target_open_time"]
        request["freeze_deadline"] = ticket["freeze_deadline"]
        request["frozen_at"] = ticket["frozen_at"]
        request["position_journal_group_ref"] = f"journal.position.{episode_ref}"
    elif account_identity == ACCOUNT_NO_ACTION:
        binding = disposition.get("no_action_period_binding")
        if not isinstance(binding, Mapping):
            raise FreezeAdapterError(
                "NO_ACTION_BINDING_REQUIRED",
                "missing no_action_period_binding",
            )
        request["account_decision"]["rule_ref"] = str(binding["rule_ref"])
        request["account_decision"]["odds_version_ref"] = str(binding["odds_version_ref"])
        request["target_ref"] = str(binding["target_ref"])
        request["target_open_time"] = str(binding["target_open_time"])
        request["freeze_deadline"] = str(binding["freeze_deadline"])
        request["frozen_at"] = str(binding["frozen_at"])
        if "bound_account_ticket" in request or "bound_frozen_decision" in request:
            raise FreezeAdapterError("NO_ACTION_MUST_NOT_BIND_TICKET", "ticket present")
    else:
        raise FreezeAdapterError("PERIOD_ACCOUNT_IDENTITY_REQUIRED", str(account_identity))

    _no_peek_guard(request)
    request["request_content_hash"] = canonical_sha256(
        {k: v for k, v in request.items() if k != "request_content_hash"}
    )
    return request


def write_freeze_request(path: Path, request: Mapping[str, Any]) -> Path:
    """Legacy non-authoritative display write. Prefer content-addressed evidence.

    Must never be the consumer's authority input for disposition-bound freezes.
    """

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(request), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def freeze_request_evidence_path(shadow_root: Path, request_content_hash: str) -> Path:
    digest = _require_hex64(request_content_hash, "request_content_hash")
    base = resolve_root(shadow_root)
    return base / "objects" / "freeze_request" / "sha256" / digest[:2] / f"{digest}.json"


def write_freeze_request_evidence_exclusive(
    *,
    shadow_root: Path,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Content-addressed exclusive freeze-request evidence (display-only, not authority)."""

    body = dict(request)
    raw = (json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = _raw_sha256(raw)
    # Prefer sealed request_content_hash when present; path digest is still raw bytes.
    content_hash = str(body.get("request_content_hash") or digest)
    if body.get("request_content_hash") is not None:
        _require_hex64(body["request_content_hash"], "request_content_hash")
    path = freeze_request_evidence_path(shadow_root, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
    except FileExistsError as exc:
        existing = path.read_bytes()
        if existing != raw:
            raise FreezeAdapterError(
                "FREEZE_REQUEST_EVIDENCE_CAS_CONFLICT",
                f"request evidence {digest} already sealed with different bytes",
            ) from exc
        return {
            "request_evidence_sha256": digest,
            "request_content_hash": content_hash,
            "path": str(path),
            "bytes_written": False,
            "authority_input": False,
        }
    return {
        "request_evidence_sha256": digest,
        "request_content_hash": content_hash,
        "path": str(path),
        "bytes_written": True,
        "authority_input": False,
    }


def _assert_period_matches(
    *,
    disposition: Mapping[str, Any],
    mode: Literal["episode", "portfolio"],
    shadow_root: Path,
) -> int:
    claimed = disposition.get("period_index")
    if type(claimed) is not int or claimed < 1:
        raise FreezeAdapterError("FREEZE_PERIOD_INVALID", str(claimed))
    if mode == "episode":
        # Flat episode roots only carry period_index=1 semantics.
        if claimed != 1:
            raise FreezeAdapterError(
                "FREEZE_EPISODE_PERIOD_MUST_BE_ONE",
                f"flat episode freeze only allows period_index=1, got {claimed}",
            )
        return 1
    expected = expected_next_period_index(shadow_root)
    if claimed != expected:
        raise FreezeAdapterError(
            "FREEZE_PERIOD_MISMATCH",
            f"disposition.period_index={claimed} portfolio next period={expected}",
        )
    return expected


def _iso_z(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    text = str(value)
    return text.replace("+00:00", "Z") if text.endswith("+00:00") else text


def _assert_frozen_matches_disposition_and_binding(
    *,
    frozen: Any,
    disposition: Mapping[str, Any],
    binding: Mapping[str, Any],
    portfolio_binding: Mapping[str, Any] | None,
    mode: Literal["episode", "portfolio"],
) -> None:
    """Post-freeze: immutable ticket/decision must match sealed disposition + binding."""

    intent = binding.get("executable_account_intent")
    if not isinstance(intent, Mapping):
        raise FreezeAdapterError(
            "RESEARCH_BINDING_EXECUTABLE_MISSING",
            "binding lacks executable_account_intent",
        )
    account_identity = str(disposition["account_identity"])
    if str(frozen.account_decision.identity.value) != account_identity:
        raise FreezeAdapterError(
            "FROZEN_ACCOUNT_IDENTITY_MISMATCH",
            f"frozen={frozen.account_decision.identity.value} disposition={account_identity}",
        )
    if str(intent.get("account_identity")) != account_identity:
        raise FreezeAdapterError(
            "BINDING_EXECUTABLE_IDENTITY_MISMATCH",
            str(intent.get("account_identity")),
        )
    if str(frozen.target_ref) != str(disposition["target_ref"]):
        raise FreezeAdapterError("FROZEN_TARGET_MISMATCH", str(frozen.target_ref))
    if str(frozen.target_ref) != str(intent.get("target_ref")):
        raise FreezeAdapterError("FROZEN_BINDING_TARGET_MISMATCH", str(intent.get("target_ref")))
    if _iso_z(frozen.target_open_time) != str(intent.get("target_open_time")):
        raise FreezeAdapterError("FROZEN_TARGET_OPEN_MISMATCH", _iso_z(frozen.target_open_time))
    if _iso_z(frozen.freeze_deadline) != str(intent.get("freeze_deadline")):
        raise FreezeAdapterError("FROZEN_DEADLINE_MISMATCH", _iso_z(frozen.freeze_deadline))
    if _iso_z(frozen.frozen_at) != str(intent.get("frozen_at")):
        raise FreezeAdapterError("FROZEN_AT_MISMATCH", _iso_z(frozen.frozen_at))
    if str(frozen.rule_ref) != str(intent.get("rule_ref")):
        raise FreezeAdapterError("FROZEN_RULE_MISMATCH", str(frozen.rule_ref))
    if str(frozen.odds_version_ref) != str(intent.get("odds_version_ref")):
        raise FreezeAdapterError("FROZEN_ODDS_MISMATCH", str(frozen.odds_version_ref))
    if str(frozen.science_decision.identity.value) != str(disposition["science_identity"]):
        raise FreezeAdapterError(
            "FROZEN_SCIENCE_IDENTITY_MISMATCH",
            str(frozen.science_decision.identity.value),
        )
    if int(frozen.period_index) != int(disposition["period_index"]):
        raise FreezeAdapterError(
            "FROZEN_PERIOD_MISMATCH",
            f"frozen={frozen.period_index} disposition={disposition['period_index']}",
        )

    if account_identity == ACCOUNT_ACTION:
        ticket = frozen.bound_account_ticket
        if ticket is None:
            raise FreezeAdapterError("FROZEN_TICKET_MISSING", "ACTION requires bound ticket")
        for field in (
            "selected_number",
            "stake",
            "panel",
            "rule_ref",
            "odds_version_ref",
            "baseline_ref",
            "risk_policy_ref",
            "target_ref",
        ):
            if getattr(ticket, field) != intent.get(field) and str(getattr(ticket, field)) != str(
                intent.get(field)
            ):
                raise FreezeAdapterError(
                    "FROZEN_TICKET_EXECUTABLE_MISMATCH",
                    f"{field}: ticket={getattr(ticket, field)!r} intent={intent.get(field)!r}",
                )
        if _iso_z(ticket.target_open_time) != str(intent.get("target_open_time")):
            raise FreezeAdapterError("FROZEN_TICKET_OPEN_MISMATCH", _iso_z(ticket.target_open_time))
        if _iso_z(ticket.freeze_deadline) != str(intent.get("freeze_deadline")):
            raise FreezeAdapterError(
                "FROZEN_TICKET_DEADLINE_MISMATCH",
                _iso_z(ticket.freeze_deadline),
            )
        if _iso_z(ticket.frozen_at) != str(intent.get("frozen_at")):
            raise FreezeAdapterError("FROZEN_TICKET_FROZEN_AT_MISMATCH", _iso_z(ticket.frozen_at))
        if str(frozen.account_decision.stake) != str(intent.get("stake")):
            raise FreezeAdapterError(
                "FROZEN_ACCOUNT_STAKE_MISMATCH",
                str(frozen.account_decision.stake),
            )
        executable = disposition.get("executable_account_decision")
        if isinstance(executable, Mapping):
            if int(ticket.selected_number) != int(executable["selected_number"]):
                raise FreezeAdapterError(
                    "FROZEN_TICKET_NUMBER_MISMATCH",
                    f"ticket={ticket.selected_number} disposition={executable['selected_number']}",
                )
            if str(ticket.stake) != str(executable["stake"]):
                raise FreezeAdapterError(
                    "FROZEN_TICKET_STAKE_MISMATCH",
                    f"ticket={ticket.stake} disposition={executable['stake']}",
                )
    else:
        if frozen.bound_account_ticket is not None:
            raise FreezeAdapterError("FROZEN_NO_ACTION_HAS_TICKET", "ticket present")
        if str(frozen.account_decision.stake) != "0.0000":
            raise FreezeAdapterError(
                "FROZEN_NO_ACTION_STAKE_MISMATCH",
                str(frozen.account_decision.stake),
            )
        if str(frozen.account_decision.rule_ref) != str(intent.get("rule_ref")):
            raise FreezeAdapterError(
                "FROZEN_NO_ACTION_RULE_MISMATCH",
                str(frozen.account_decision.rule_ref),
            )
        if str(frozen.account_decision.odds_version_ref) != str(intent.get("odds_version_ref")):
            raise FreezeAdapterError(
                "FROZEN_NO_ACTION_ODDS_MISMATCH",
                str(frozen.account_decision.odds_version_ref),
            )

    if mode == "portfolio":
        if portfolio_binding is None:
            raise FreezeAdapterError("PORTFOLIO_BINDING_REQUIRED", "missing verified binding")
        if str(frozen.portfolio_ref) != str(portfolio_binding["portfolio_ref"]):
            raise FreezeAdapterError(
                "FROZEN_PORTFOLIO_REF_MISMATCH",
                str(frozen.portfolio_ref),
            )
        if str(frozen.seat_id) != str(portfolio_binding["seat_id"]):
            raise FreezeAdapterError("FROZEN_SEAT_ID_MISMATCH", str(frozen.seat_id))
        binding_pb = binding.get("portfolio_binding")
        if not isinstance(binding_pb, Mapping):
            raise FreezeAdapterError(
                "RESEARCH_BINDING_PORTFOLIO_MISSING",
                "portfolio binding not sealed into research binding",
            )
        if binding_pb.get("portfolio_ref") != portfolio_binding["portfolio_ref"]:
            raise FreezeAdapterError(
                "RESEARCH_BINDING_PORTFOLIO_MISMATCH",
                str(binding_pb.get("portfolio_ref")),
            )
    elif (
        disposition.get("portfolio_binding") is not None
        or binding.get("portfolio_binding") is not None
    ):
        raise FreezeAdapterError(
            "EPISODE_MODE_PORTFOLIO_BINDING_FORBIDDEN",
            "flat episode mode must not fake portfolio identity",
        )


def apply_freeze_from_disposition(
    *,
    pool_root: Path,
    owner_state_root: Path,
    disposition_path: Path,
    shadow_root: Path,
    mode: Literal["episode", "portfolio"] = "portfolio",
    result_sha256: str | None = None,
    request_out: Path | None = None,
) -> dict[str, Any]:
    """Verify disposition + pool, seal research binding, call exclusive freeze consumer.

    Authority input to the consumer is an in-memory closed request mapping — never
    a mutable freeze_request path. Optional request evidence is content-addressed
    and display-only.

    Stops at FROZEN / awaiting independent outcome. Does not settle, feedback, or
    open the next period.
    """

    try:
        verified = load_and_verify_disposition(
            disposition_path=disposition_path,
            owner_state_root=owner_state_root,
            pool_root=pool_root,
            result_sha256=result_sha256,
        )
    except OwnerDispositionError as exc:
        raise FreezeAdapterError(exc.reason_code, exc.detail) from exc

    pool_entry = verified["pool_entry"]
    disposition = verified["disposition"]
    expected_period = _assert_period_matches(
        disposition=disposition,
        mode=mode,
        shadow_root=shadow_root,
    )

    # Portfolio/head exact binding BEFORE any binding/request/freeze write.
    portfolio_binding: dict[str, Any] | None = None
    if mode == "portfolio":
        portfolio_binding = assert_portfolio_binding_matches_shadow(
            disposition=disposition,
            shadow_root=shadow_root,
        )
    elif disposition.get("portfolio_binding") is not None:
        raise FreezeAdapterError(
            "EPISODE_MODE_PORTFOLIO_BINDING_FORBIDDEN",
            "flat episode mode must not carry portfolio_binding",
        )

    binding_body = build_research_freeze_binding(
        pool_entry=pool_entry,
        disposition=disposition,
        owner_artifact_sha256=str(verified["owner_artifact_sha256"]),
        portfolio_binding=portfolio_binding,
    )
    sealed_binding = write_research_binding_exclusive(
        shadow_root=shadow_root,
        body=binding_body,
    )
    binding_hash = str(sealed_binding["research_binding_sha256"])

    request = build_freeze_request_from_disposition(
        pool_entry=pool_entry,
        disposition=disposition,
        owner_artifact_sha256=str(verified["owner_artifact_sha256"]),
        research_binding_sha256=binding_hash,
    )
    # Closed deep-copied in-memory authority mapping for the consumer.
    # Display/evidence paths and later mutation of caller structures cannot fork it.
    authority_request = copy.deepcopy(request)

    evidence = write_freeze_request_evidence_exclusive(
        shadow_root=shadow_root,
        request=authority_request,
    )
    # Optional legacy display path; never used as consumer authority input.
    if request_out is None:
        request_out = (
            shadow_root.expanduser().resolve()
            / "generated"
            / f"freeze_request.{evidence['request_evidence_sha256'][:16]}.v1.json"
        )
    write_freeze_request(request_out, authority_request)

    try:
        if mode == "portfolio":
            result = freeze_portfolio_period(
                root=shadow_root,
                request=copy.deepcopy(authority_request),
            )
        elif mode == "episode":
            result = freeze_episode(
                root=shadow_root,
                request=copy.deepcopy(authority_request),
            )
        else:
            raise FreezeAdapterError("FREEZE_MODE_INVALID", str(mode))
    except (StoreError, ValueError) as exc:
        raise FreezeAdapterError("FREEZE_CONSUMER_REJECTED", str(exc)) from exc

    # Read back formal frozen artifact and prove binding entered content_hash fields.
    if mode == "portfolio":
        period_root = period_directory(resolve_root(shadow_root), int(result["period_index"]))
    else:
        period_root = resolve_root(shadow_root)
    frozen = load_frozen(period_root)
    frozen_binding_hash = extract_research_binding_hash_from_frozen(frozen)
    if frozen_binding_hash != binding_hash:
        raise FreezeAdapterError(
            "RESEARCH_BINDING_FROZEN_MISMATCH",
            f"written={binding_hash} frozen={frozen_binding_hash}",
        )
    if int(result.get("period_index", expected_period)) != expected_period:
        raise FreezeAdapterError(
            "FREEZE_PERIOD_MISMATCH",
            f"consumer period={result.get('period_index')} expected={expected_period}",
        )
    reloaded = load_research_binding(shadow_root, frozen_binding_hash)
    if reloaded.get("result_sha256") != pool_entry.get("result_sha256"):
        raise FreezeAdapterError("RESEARCH_BINDING_POOL_MISMATCH", "result_sha256")
    if reloaded.get("owner_artifact_sha256") != verified["owner_artifact_sha256"]:
        raise FreezeAdapterError("RESEARCH_BINDING_OWNER_MISMATCH", "owner_artifact_sha256")
    if int(reloaded.get("period_index", -1)) != int(disposition["period_index"]):
        raise FreezeAdapterError("RESEARCH_BINDING_PERIOD_MISMATCH", "period_index")

    _assert_frozen_matches_disposition_and_binding(
        frozen=frozen,
        disposition=disposition,
        binding=reloaded,
        portfolio_binding=portfolio_binding,
        mode=mode,
    )

    return {
        "ok": bool(result.get("ok", True)),
        "adapter_marker": ADAPTER_MARKER,
        "mode": mode,
        "phase": result.get("phase"),
        "episode_ref": result.get("episode_ref"),
        "frozen_episode_hash": result.get("frozen_episode_hash") or frozen.content_hash,
        "period_index": result.get("period_index"),
        "account_identity": result.get("account_identity"),
        "bound_result_sha256": authority_request["bound_result_sha256"],
        "bound_pool_entry_content_hash": authority_request["bound_pool_entry_content_hash"],
        "bound_owner_artifact_sha256": authority_request["bound_owner_artifact_sha256"],
        "research_binding_sha256": binding_hash,
        "research_binding_path": sealed_binding["path"],
        "science_decision_ref": frozen.science_decision.science_decision_ref,
        "account_decision_ref": frozen.account_decision.account_decision_ref,
        "request_path": str(request_out),
        "request_evidence_path": evidence["path"],
        "request_evidence_sha256": evidence["request_evidence_sha256"],
        "request_evidence_authority_input": False,
        "request_content_hash": authority_request["request_content_hash"],
        "portfolio_binding": portfolio_binding,
        "trusted_time_proof": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "next_action": result.get("next_action"),
        "auto_next_period": False,
        "auto_settle": False,
        # Honest library authority surface (never authenticates Codex).
        "owner_channel_authority": OWNER_CHANNEL_AUTHORITY_UNPROVEN,
        "path_separated_from_pool": True,
        "physical_owner_write_isolation_verified": False,
        "owner_disposition_authentic": False,
        "consumer_result": result,
    }


def assert_no_control_plane_imports() -> None:
    """Self-check: module must not import Temporal/Goal control-plane packages."""

    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0].lower())
    forbidden_hits = sorted(imported & {t.lower() for t in _FORBIDDEN_IMPORT_TOKENS})
    if forbidden_hits:
        raise FreezeAdapterError(
            "CONTROL_PLANE_IMPORT_SUSPECT",
            f"imports={forbidden_hits}",
        )


__all__ = [
    "ADAPTER_MARKER",
    "RESEARCH_BINDING_MARKER",
    "RESEARCH_BINDING_REF_PREFIX",
    "RESEARCH_BINDING_SCHEMA",
    "FreezeAdapterError",
    "apply_freeze_from_disposition",
    "assert_no_control_plane_imports",
    "assert_portfolio_binding_matches_shadow",
    "build_freeze_request_from_disposition",
    "build_portfolio_binding_from_shadow",
    "build_research_freeze_binding",
    "expected_next_period_index",
    "extract_research_binding_hash_from_frozen",
    "extract_research_binding_hash_from_refs",
    "freeze_request_evidence_path",
    "load_research_binding",
    "research_binding_path",
    "write_freeze_request",
    "write_freeze_request_evidence_exclusive",
    "write_research_binding_exclusive",
]
