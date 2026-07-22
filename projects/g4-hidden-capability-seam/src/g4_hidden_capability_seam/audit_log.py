"""Append-only audit/run log with deterministic verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .hash_chain import HashChainedLog

LOG_KIND = "audit_run_log.v1"


class AuditRunLog:
    def __init__(self, path: str | Path) -> None:
        self.log = HashChainedLog(path, log_kind=LOG_KIND)

    def append_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "event_type": event_type,
            "payload": payload,
            "synthetic_only": True,
            "not_capability_evidence": True,
            "authority": False,
        }
        return self.log.append(body)

    def verify(self) -> dict[str, Any]:
        return self.log.verify()

    def entries(self) -> list[dict[str, Any]]:
        return self.log.entries()

    def detect_truncation(self, expected_min_length: int) -> dict[str, Any]:
        return self.log.detect_truncation(expected_min_length=expected_min_length)
