"""Disposition-bound freeze adapter over existing shadow_lifecycle consumer.

Builds a freeze request from a verified pool entry + Codex owner disposition,
then calls existing ``freeze_episode`` / ``freeze_portfolio_period``. Does not
copy the ledger, alter freeze semantics, loop the next period, or start
daemon/Temporal/Goal. Researchers still cannot write shadow state through this
module.

File-backed freeze trusts caller-supplied timestamps only:
``trusted_time_proof=false`` is always reported honestly for this path.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal

from xinao.canonical import canonical_sha256
from xinao.science.owner_disposition import (
    ACCOUNT_ACTION,
    ACCOUNT_NO_ACTION,
    OwnerDispositionError,
    disposition_information_set_hash,
    load_and_verify_disposition,
    require_period_account_identity,
)
from xinao.shadow_lifecycle.consumer import freeze_episode, freeze_portfolio_period
from xinao.shadow_lifecycle.store import StoreError

ADAPTER_MARKER: Final = "XINAO_DISPOSITION_FREEZE_ADAPTER_V1"
SPECIAL_NUMBER_RULE: Final = "special-number-rule.v1"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")

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


def _no_peek_guard(request: Mapping[str, Any]) -> None:
    for forbidden in ("outcome", "actual_special_number", "settlement", "settled"):
        if forbidden in request:
            raise FreezeAdapterError(
                "FREEZE_NO_PEEK_VIOLATION",
                f"request must not include {forbidden!r}",
            )


def _science_branch_from_disposition(
    *,
    disposition: Mapping[str, Any],
    pool_entry: Mapping[str, Any],
) -> dict[str, Any]:
    science_identity = disposition.get("science_identity")
    if science_identity not in ("SCIENCE_CANDIDATE", "POLICY_NO_ACTION"):
        raise FreezeAdapterError("FREEZE_SCIENCE_IDENTITY_INVALID", str(science_identity))
    knowledge_cutoff = disposition["knowledge_cutoff"]
    science: dict[str, Any] = {
        "science_decision_ref": f"science.disp.{disposition['episode_ref']}",
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

    episode_ref = str(disposition["episode_ref"])
    science = _science_branch_from_disposition(
        disposition=disposition,
        pool_entry=pool_entry,
    )

    request: dict[str, Any] = {
        "episode_ref": episode_ref,
        "science_decision": science,
        "account_decision": {
            "account_decision_ref": f"account.disp.{episode_ref}",
            "identity": account_identity,
        },
        # Binding fields for consumer receipt (additive; optional on consumer).
        "bound_result_sha256": pool_entry["result_sha256"],
        "bound_receipt_content_sha256": pool_entry["receipt_content_sha256"],
        "bound_pool_entry_content_hash": pool_entry["content_hash"],
        "bound_owner_artifact_sha256": _require_hex64(
            owner_artifact_sha256,
            "owner_artifact_sha256",
        ),
        "bound_policy_ref": pool_entry.get("policy_ref"),
        "disposition_adapter_marker": ADAPTER_MARKER,
        "trusted_time_proof": False,
    }

    if account_identity == ACCOUNT_ACTION:
        ticket = _build_action_ticket(disposition=disposition, pool_entry=pool_entry)
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
        # Explicit zero stake; no ticket.
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
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(request), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


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
    """Verify disposition + pool, build request, call real exclusive freeze consumer.

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
    request = build_freeze_request_from_disposition(
        pool_entry=pool_entry,
        disposition=disposition,
        owner_artifact_sha256=str(verified["owner_artifact_sha256"]),
    )

    if request_out is None:
        request_out = shadow_root.expanduser().resolve() / "generated" / "freeze_request.v1.json"
    write_freeze_request(request_out, request)

    try:
        if mode == "portfolio":
            result = freeze_portfolio_period(root=shadow_root, request_path=request_out)
        elif mode == "episode":
            result = freeze_episode(root=shadow_root, request_path=request_out)
        else:
            raise FreezeAdapterError("FREEZE_MODE_INVALID", str(mode))
    except (StoreError, ValueError) as exc:
        raise FreezeAdapterError("FREEZE_CONSUMER_REJECTED", str(exc)) from exc

    return {
        "ok": bool(result.get("ok", True)),
        "adapter_marker": ADAPTER_MARKER,
        "mode": mode,
        "phase": result.get("phase"),
        "episode_ref": result.get("episode_ref"),
        "frozen_episode_hash": result.get("frozen_episode_hash"),
        "period_index": result.get("period_index"),
        "account_identity": result.get("account_identity"),
        "bound_result_sha256": request["bound_result_sha256"],
        "bound_pool_entry_content_hash": request["bound_pool_entry_content_hash"],
        "bound_owner_artifact_sha256": request["bound_owner_artifact_sha256"],
        "request_path": str(request_out),
        "request_content_hash": request["request_content_hash"],
        "trusted_time_proof": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "next_action": result.get("next_action"),
        "auto_next_period": False,
        "auto_settle": False,
        "owner_disposition_authentic": True,
        "physical_owner_write_isolation": verified["physical_owner_write_isolation"],
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
    "FreezeAdapterError",
    "apply_freeze_from_disposition",
    "assert_no_control_plane_imports",
    "build_freeze_request_from_disposition",
    "write_freeze_request",
]
