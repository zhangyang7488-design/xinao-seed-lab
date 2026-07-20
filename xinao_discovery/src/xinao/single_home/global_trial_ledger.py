"""Single-home GlobalTrialLedger append-only pure interface (AF-005 / O34).

One logical object identity for G3 loop pure and G5 statistical disclosure.
Not market-lab trial ledger. No durable DB/outbox. Not ResearchErrorBudgetPolicy.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from xinao.single_home.errors import SingleHomeError
from xinao.single_home.field_contracts import assert_entry_fields, assert_export_fields
from xinao.single_home.hashing import content_sha256
from xinao.single_home.provisional_versions import (
    COORDINATES_WITH_PACKAGES,
    LOGICAL_OBJECT_IDS,
    SCHEMA_VERSIONS,
    STAGE_GATE,
    TERMINAL_STATUSES,
)

LOGICAL_OBJECT_ID = LOGICAL_OBJECT_IDS["GlobalTrialLedger"]


class GlobalTrialLedger:
    """Append-only pure ledger. Mutations never rewrite prior entries.

    This is the sole provisional home class. G3 and G5 consumers import here.
    """

    LOGICAL_OBJECT_ID = LOGICAL_OBJECT_ID
    COORDINATES_WITH = COORDINATES_WITH_PACKAGES
    HOME_MODULE = "xinao.single_home.global_trial_ledger"

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._by_work_key: dict[str, int] = {}
        self._seq = 0

    def register(self, work_key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(work_key, str) or not work_key:
            raise SingleHomeError("BAD_WORK_KEY", "work_key required")
        if not isinstance(payload, Mapping):
            raise SingleHomeError("BAD_PAYLOAD", "payload must be object")
        status = payload.get("status", "REGISTERED")
        if status not in TERMINAL_STATUSES:
            raise SingleHomeError("BAD_STATUS", f"unknown status {status!r}")
        body = {
            "work_key": work_key,
            "status": status,
            "family_id": payload.get("family_id"),
            "equivalence_cluster_id": payload.get("equivalence_cluster_id"),
            "path_kind": payload.get("path_kind", "PRIMARY"),
            "failure_reason": payload.get("failure_reason"),
            "payload_hash": content_sha256(dict(payload)),
            "meta": {
                k: v
                for k, v in payload.items()
                if k
                not in {
                    "status",
                    "family_id",
                    "equivalence_cluster_id",
                    "path_kind",
                    "failure_reason",
                }
            },
        }
        if work_key in self._by_work_key:
            existing = self._entries[self._by_work_key[work_key]]
            if existing["payload_hash"] != body["payload_hash"]:
                raise SingleHomeError(
                    "IDEMPOTENCE_CONFLICT",
                    "duplicate work_key with different payload rejected",
                )
            return deepcopy(existing)
        self._seq += 1
        entry = {"seq": self._seq, **body, "immutable": True}
        assert_entry_fields(entry)
        self._by_work_key[work_key] = len(self._entries)
        self._entries.append(entry)
        return deepcopy(entry)

    def append_terminal(self, work_key: str, status: str, **fields: Any) -> dict[str, Any]:
        if status not in TERMINAL_STATUSES:
            raise SingleHomeError("BAD_STATUS", f"unknown terminal {status!r}")
        if work_key not in self._by_work_key:
            raise SingleHomeError("UNREGISTERED", "silent unregistered trial forbidden")
        self._seq += 1
        entry = {
            "seq": self._seq,
            "work_key": work_key,
            "status": status,
            "family_id": fields.get("family_id"),
            "equivalence_cluster_id": fields.get("equivalence_cluster_id"),
            "path_kind": fields.get("path_kind", "PRIMARY"),
            "failure_reason": fields.get("failure_reason"),
            "payload_hash": content_sha256({"work_key": work_key, "status": status, **fields}),
            "meta": {},
            "immutable": True,
            "event": "TERMINAL",
        }
        assert_entry_fields(entry)
        self._entries.append(entry)
        return deepcopy(entry)

    def delete(self, work_key: str) -> None:
        raise SingleHomeError("APPEND_ONLY", "delete/rewrite history forbidden")

    def rewrite(self, work_key: str, payload: Mapping[str, Any]) -> None:
        raise SingleHomeError("APPEND_ONLY", "delete/rewrite history forbidden")

    def entries(self) -> list[dict[str, Any]]:
        return deepcopy(self._entries)

    def export_disclosure(self) -> dict[str, Any]:
        statuses = [e["status"] for e in self._entries]
        clusters = {
            e["equivalence_cluster_id"] for e in self._entries if e.get("equivalence_cluster_id")
        }
        discarded = sum(1 for s in statuses if s == "DISCARDED")
        failed = sum(1 for s in statuses if s in {"FAILED", "TIMEOUT"})
        export = {
            "schema_version": SCHEMA_VERSIONS["global_trial_ledger_export"],
            "logical_object_id": self.LOGICAL_OBJECT_ID,
            "total_trials": len({e["work_key"] for e in self._entries}),
            "valid_equivalence_clusters": len(clusters),
            "discarded_paths": discarded,
            "failed_or_timeout_paths": failed,
            "statuses_observed": sorted(set(statuses)),
            "work_keys": sorted({e["work_key"] for e in self._entries}),
            "export_hash": content_sha256(
                {"entries": [{k: e[k] for k in e if k != "meta"} for e in self._entries]}
            ),
            "stage_gate": STAGE_GATE,
            "authoritative": False,
            "not_market_lab_ledger": True,
            "no_durable_state": True,
            "coordinates_with_packages": list(COORDINATES_WITH_PACKAGES),
        }
        assert_export_fields(export)
        return export

    def assert_no_silent_path(self, observed_work_keys: list[str]) -> None:
        registered = set(self._by_work_key)
        for wk in observed_work_keys:
            if wk not in registered:
                raise SingleHomeError("SILENT_UNREGISTERED_TRIAL", f"unregistered {wk}")
