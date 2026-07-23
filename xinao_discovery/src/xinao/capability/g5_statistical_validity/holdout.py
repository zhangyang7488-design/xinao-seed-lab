"""Budgeted holdout outcome-access ledger.

Every observation of a holdout-derived outcome consumes one access, even when
the downstream decision is NO_ACTION.  Replaying the exact same access receipt
is idempotent; a conflicting replay or an over-budget access fails closed.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from xinao.canonical import canonical_sha256


class HoldoutExposureError(ValueError):
    """Invalid, conflicting, or over-budget holdout access."""


def _sha256(name: str, value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise HoldoutExposureError(f"{name} must be 64 lowercase hex")
    return value


class HoldoutExposureLedger:
    """Pure in-memory receipt builder for a frozen holdout access budget."""

    def __init__(
        self,
        *,
        ledger_id: str,
        split_binding: str,
        preregistration_sha256: str,
        max_accesses: int,
    ) -> None:
        if not ledger_id or not split_binding:
            raise HoldoutExposureError("ledger_id and split_binding are required")
        if isinstance(max_accesses, bool) or not isinstance(max_accesses, int) or max_accesses < 0:
            raise HoldoutExposureError("max_accesses must be an integer >= 0")
        self.ledger_id = ledger_id
        self.split_binding = split_binding
        self.preregistration_sha256 = _sha256("preregistration_sha256", preregistration_sha256)
        self.max_accesses = max_accesses
        self._records: dict[str, dict[str, Any]] = {}
        self._revoked = False

    def debit(
        self,
        *,
        access_id: str,
        query_sha256: str,
        outcome_artifact_sha256: str,
        purpose: str,
        downstream_action: str,
    ) -> dict[str, Any]:
        if not access_id or not purpose or not downstream_action:
            raise HoldoutExposureError("access_id, purpose, and downstream_action are required")
        record = {
            "access_id": access_id,
            "query_sha256": _sha256("query_sha256", query_sha256),
            "outcome_artifact_sha256": _sha256("outcome_artifact_sha256", outcome_artifact_sha256),
            "purpose": purpose,
            "downstream_action": downstream_action,
            "preregistration_sha256": self.preregistration_sha256,
        }
        record["receipt_sha256"] = canonical_sha256(record)
        existing = self._records.get(access_id)
        if existing is not None:
            if existing != record:
                self._revoked = True
                raise HoldoutExposureError("conflicting replay for an existing access_id")
            return deepcopy(existing)
        if self._revoked or len(self._records) >= self.max_accesses:
            self._revoked = True
            raise HoldoutExposureError("holdout access budget exceeded")
        self._records[access_id] = record
        return deepcopy(record)

    def snapshot(self) -> dict[str, Any]:
        records = [self._records[key] for key in sorted(self._records)]
        body: dict[str, Any] = {
            "schema_version": "xinao.g5.holdout_exposure_ledger.v1",
            "ledger_id": self.ledger_id,
            "split_binding": self.split_binding,
            "preregistration_sha256": self.preregistration_sha256,
            "max_accesses": self.max_accesses,
            "accesses_used": len(records),
            "accesses_remaining": max(0, self.max_accesses - len(records)),
            "records": records,
            "revoked": self._revoked,
            "overexposed": self._revoked,
            "all_outcome_accesses_debited": not self._revoked,
            "no_action_is_free_access": False,
            "authority": False,
            "completion_claim_allowed": False,
        }
        body["content_hash"] = canonical_sha256(body)
        return body
