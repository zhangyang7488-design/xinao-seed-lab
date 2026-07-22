"""Append-only hash-chained log with cross-process serialization and independent seal.

Appends are serialized via sqlite DELETE-journal BEGIN IMMEDIATE. JSONL bytes
are flushed and fsynced before the SQLite head is committed. A final seal
receipt retains expected head/length independently of the mutable JSONL so
whole-chain rewrite, truncation, deletion, reorder, and lost concurrent appends
are detected.

Threat model: the colocated lock DB + self-hashed seal is tamper-evident against
log-only alteration. It is not an external tamper-resistant trust anchor — an
actor who can replace both the log and the colocated lock/seal can forge a
consistent alternate chain.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .canonical import canonical_json_sha256, sha256_hex, write_json

GENESIS_PREV = "0" * 64
BUSY_TIMEOUT_MS = 30_000


class HashChainedLog:
    """Append-only JSONL log; each entry binds prev_sha256 + body -> entry_sha256."""

    def __init__(self, path: str | Path, *, log_kind: str) -> None:
        self.path = Path(path)
        self.log_kind = log_kind
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_db = self.path.with_suffix(self.path.suffix + ".lock.sqlite3")
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        self._init_lock_db()

    def _connect_lock(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.lock_db),
            timeout=BUSY_TIMEOUT_MS / 1000.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init_lock_db(self) -> None:
        with self._connect_lock() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS log_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO log_meta(key, value) VALUES('head_sha256', ?)",
                (GENESIS_PREV,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO log_meta(key, value) VALUES('length', '0')",
            )
            conn.execute("COMMIT")

    @staticmethod
    def parse_entries_from_text(text: str) -> list[dict[str, Any]]:
        """Parse JSONL entries from already-captured text (no filesystem re-read)."""
        if not text.strip():
            return []
        entries: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            entries.append(json.loads(line))
        return entries

    @staticmethod
    def parse_entries_from_bytes(raw: bytes) -> list[dict[str, Any]]:
        """Parse JSONL entries from already-captured bytes (no filesystem re-read)."""
        return HashChainedLog.parse_entries_from_text(raw.decode("utf-8"))

    @staticmethod
    def verify_parsed_entries(
        entries: list[dict[str, Any]],
        *,
        log_kind: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Verify chain integrity over an immutable in-memory entry list."""
        prev = GENESIS_PREV
        for i, rec in enumerate(entries):
            if rec.get("entry_index") != i:
                return {
                    "ok": False,
                    "reason": "entry_index_gap_or_reorder",
                    "at": i,
                }
            if rec.get("prev_sha256") != prev:
                return {
                    "ok": False,
                    "reason": "prev_sha256_mismatch",
                    "at": i,
                    "expected_prev": prev,
                    "observed_prev": rec.get("prev_sha256"),
                }
            body = rec.get("body")
            sealed = {
                "log_kind": rec.get("log_kind"),
                "entry_index": rec.get("entry_index"),
                "prev_sha256": rec.get("prev_sha256"),
                "body": body,
            }
            expected = canonical_json_sha256(sealed)
            if rec.get("entry_sha256") != expected:
                return {
                    "ok": False,
                    "reason": "entry_sha256_mismatch",
                    "at": i,
                    "expected": expected,
                    "observed": rec.get("entry_sha256"),
                }
            if rec.get("log_kind") != log_kind:
                return {"ok": False, "reason": "log_kind_mismatch", "at": i}
            prev = str(rec["entry_sha256"])
        result: dict[str, Any] = {
            "ok": True,
            "length": len(entries),
            "head_sha256": prev,
            "log_kind": log_kind,
        }
        if path is not None:
            result["path"] = path
        return result

    @staticmethod
    def verify_from_bytes(
        raw: bytes,
        *,
        log_kind: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Verify a hash chain from one captured byte snapshot."""
        try:
            entries = HashChainedLog.parse_entries_from_bytes(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return {
                "ok": False,
                "reason": "ledger_snapshot_parse_failed",
                "error_class": type(exc).__name__,
            }
        return HashChainedLog.verify_parsed_entries(entries, log_kind=log_kind, path=path)

    def _read_entries(self) -> list[dict[str, Any]]:
        return self.parse_entries_from_bytes(self.path.read_bytes())

    def head_sha256(self) -> str:
        entries = self._read_entries()
        if not entries:
            return GENESIS_PREV
        return str(entries[-1]["entry_sha256"])

    def length(self) -> int:
        return len(self._read_entries())

    def append(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._connect_lock() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Re-read under lock for cross-process serialization
            entries = self._read_entries()
            prev = GENESIS_PREV if not entries else str(entries[-1]["entry_sha256"])
            entry_index = len(entries)
            sealed = {
                "log_kind": self.log_kind,
                "entry_index": entry_index,
                "prev_sha256": prev,
                "body": body,
            }
            entry_sha = canonical_json_sha256(sealed)
            record = {**sealed, "entry_sha256": entry_sha}
            line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
                fh.write("\n")
                fh.flush()
                try:
                    import os

                    os.fsync(fh.fileno())
                except OSError:
                    # Fail closed: do not advance lock head without durable log bytes
                    conn.execute("ROLLBACK")
                    raise
            conn.execute(
                "INSERT OR REPLACE INTO log_meta(key, value) VALUES('head_sha256', ?)",
                (entry_sha,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO log_meta(key, value) VALUES('length', ?)",
                (str(entry_index + 1),),
            )
            conn.execute("COMMIT")
        return record

    def sealed_head_from_lock(self) -> dict[str, Any]:
        with self._connect_lock() as conn:
            head = conn.execute("SELECT value FROM log_meta WHERE key='head_sha256'").fetchone()
            length = conn.execute("SELECT value FROM log_meta WHERE key='length'").fetchone()
        return {
            "expected_head_sha256": head[0] if head else GENESIS_PREV,
            "expected_length": int(length[0]) if length else 0,
        }

    def write_seal_receipt(self, receipt_path: str | Path) -> dict[str, Any]:
        """Independently sealed expected head/length (not derived only from mutable log)."""
        lock_view = self.sealed_head_from_lock()
        chain = self.verify()
        if not chain.get("ok"):
            raise RuntimeError(f"cannot_seal_invalid_hash_chain:{chain.get('reason')}")
        if lock_view["expected_head_sha256"] != chain.get("head_sha256") or int(
            lock_view["expected_length"]
        ) != int(chain.get("length", -1)):
            raise RuntimeError("cannot_seal_hash_chain_lock_head_or_length_drift")
        body = {
            "schema_version": "xinao.g4.hidden_capability_seam.log_seal_receipt.v1",
            "log_kind": self.log_kind,
            "log_path": str(self.path),
            "expected_length": lock_view["expected_length"],
            "expected_head_sha256": lock_view["expected_head_sha256"],
            "lock_db_path": str(self.lock_db),
            "chain_ok_at_seal": True,
            "cas_backend": "sqlite3_delete_journal_begin_immediate",
            "threat_model": (
                "tamper_evident_against_log_only_alteration;"
                "not_external_tamper_resistant_trust_anchor"
            ),
            "authority": False,
            "synthetic_only": True,
        }
        body["seal_sha256"] = canonical_json_sha256(
            {k: v for k, v in body.items() if k != "seal_sha256"}
        )
        write_json(receipt_path, body)
        return body

    def verify_against_seal(
        self,
        seal: dict[str, Any],
        *,
        chain: dict[str, Any] | None = None,
        lock_view: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compare seal + optional lock against one chain result.

        When ``chain`` / ``lock_view`` are supplied they are used as-is so callers
        can bind verification to a single previously captured snapshot.
        """
        chain_result = chain if chain is not None else self.verify()
        if not chain_result.get("ok"):
            return {
                "ok": False,
                "reason": "chain_invalid",
                "chain": chain_result,
            }
        # Recompute seal body hash
        expected_seal = canonical_json_sha256({k: v for k, v in seal.items() if k != "seal_sha256"})
        if seal.get("seal_sha256") != expected_seal:
            return {"ok": False, "reason": "seal_receipt_tampered"}
        if int(seal.get("expected_length", -1)) != int(chain_result.get("length", -2)):
            return {
                "ok": False,
                "reason": "length_mismatch_vs_seal",
                "expected": seal.get("expected_length"),
                "observed": chain_result.get("length"),
            }
        if seal.get("expected_head_sha256") != chain_result.get("head_sha256"):
            return {
                "ok": False,
                "reason": "head_mismatch_vs_seal",
                "expected": seal.get("expected_head_sha256"),
                "observed": chain_result.get("head_sha256"),
            }
        # Detect whole-chain rewrite that rehashes consistently but disagrees with lock DB
        lock = lock_view if lock_view is not None else self.sealed_head_from_lock()
        if lock["expected_head_sha256"] != chain_result.get("head_sha256"):
            return {
                "ok": False,
                "reason": "head_mismatch_vs_independent_lock",
                "lock_head": lock["expected_head_sha256"],
                "log_head": chain_result.get("head_sha256"),
            }
        if int(lock["expected_length"]) != int(chain_result.get("length", -1)):
            return {
                "ok": False,
                "reason": "length_mismatch_vs_independent_lock",
                "lock_length": lock["expected_length"],
                "log_length": chain_result.get("length"),
            }
        return {
            "ok": True,
            "length": chain_result["length"],
            "head_sha256": chain_result["head_sha256"],
            "seal_sha256": seal.get("seal_sha256"),
        }

    def verify(self) -> dict[str, Any]:
        return self.verify_from_bytes(
            self.path.read_bytes(),
            log_kind=self.log_kind,
            path=str(self.path),
        )

    def entries(self) -> list[dict[str, Any]]:
        return self._read_entries()

    def detect_truncation(self, *, expected_min_length: int) -> dict[str, Any]:
        n = self.length()
        if n < expected_min_length:
            return {
                "ok": False,
                "reason": "audit_log_truncation",
                "length": n,
                "expected_min_length": expected_min_length,
            }
        return {"ok": True, "length": n, "expected_min_length": expected_min_length}


def file_fingerprint(path: str | Path) -> str:
    return sha256_hex(Path(path).read_bytes()) if Path(path).exists() else GENESIS_PREV
