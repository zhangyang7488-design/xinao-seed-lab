"""Cross-process atomic suite + run claim state via stdlib sqlite3.

Uses DELETE journal mode + BEGIN IMMEDIATE so concurrent claimers serialize.
UNIQUE(run_id) guarantees at most one side-effect slot per run. Suite
active/revoked status and the run claim share one use-time transaction boundary.
mark_side_effect_started rechecks suite active status in the same transaction.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from .canonical import canonical_json_sha256, write_json

SCHEMA_VERSION = "xinao.g4.hidden_capability_seam.atomic_state.v1"
START_TRANSITION_SCHEMA = "xinao.g4.hidden_capability_seam.run_claim_start_transition.v1"
BUSY_TIMEOUT_MS = 30_000


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        timeout=BUSY_TIMEOUT_MS / 1000.0,
        isolation_level=None,  # manual transactions
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    # DELETE journal avoids lingering -wal/-shm handles on Windows after close.
    # BEGIN IMMEDIATE still provides cross-process exclusive serialization.
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


class AtomicSeamState:
    """Single sqlite root for suite lifecycle and run idempotency."""

    def __init__(self, db_path: str | Path, *, max_attempts: int = 3) -> None:
        self.db_path = Path(db_path)
        self.max_attempts = max_attempts
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(self.db_path) as conn:
            # executescript auto-COMMITs; do not wrap it in an explicit transaction.
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS suite_identities (
                    suite_identity_sha256 TEXT PRIMARY KEY,
                    public_label TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','revoked')),
                    rotated_from TEXT,
                    payload_json TEXT NOT NULL,
                    created_at_unix REAL NOT NULL,
                    revoked_at_unix REAL,
                    revoke_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS rotation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_sha TEXT NOT NULL,
                    to_sha TEXT NOT NULL,
                    history_sha256 TEXT NOT NULL,
                    created_at_unix REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_claims (
                    run_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    route_identity_sha256 TEXT NOT NULL,
                    suite_identity_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    side_effect_started INTEGER NOT NULL DEFAULT 0,
                    side_effect_executed INTEGER NOT NULL DEFAULT 0,
                    record_sha256 TEXT NOT NULL,
                    start_transition_sha256 TEXT,
                    start_transition_at_unix REAL,
                    start_transition_nonce TEXT,
                    created_at_unix REAL NOT NULL,
                    updated_at_unix REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_attempts (
                    run_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at_unix REAL NOT NULL,
                    PRIMARY KEY (run_id, attempt_id)
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_run_claim_transition_columns(conn)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('max_attempts', ?)",
                (str(max_attempts),),
            )
            conn.execute("COMMIT")

    @staticmethod
    def _ensure_run_claim_transition_columns(conn: sqlite3.Connection) -> None:
        """Deterministic local migration for start-transition integrity columns.

        Pre-existing databases created before repair4 lack the transition columns.
        Missing transition material is never treated as valid at finalization.
        """
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(run_claims)").fetchall()}
        if "start_transition_sha256" not in cols:
            conn.execute("ALTER TABLE run_claims ADD COLUMN start_transition_sha256 TEXT")
        if "start_transition_at_unix" not in cols:
            conn.execute("ALTER TABLE run_claims ADD COLUMN start_transition_at_unix REAL")
        if "start_transition_nonce" not in cols:
            conn.execute("ALTER TABLE run_claims ADD COLUMN start_transition_nonce TEXT")

    @staticmethod
    def _expected_input_hash(
        *,
        run_id: str,
        attempt_id: str,
        route_identity_sha256: str,
        suite_identity_sha256: str,
    ) -> str:
        return canonical_json_sha256(
            {
                "attempt_id": attempt_id,
                "route_identity_sha256": route_identity_sha256,
                "run_id": run_id,
                "suite_identity_sha256": suite_identity_sha256,
            }
        )

    @classmethod
    def _build_start_transition_record(
        cls,
        *,
        run_id: str,
        attempt_id: str,
        route_identity_sha256: str,
        suite_identity_sha256: str,
        immutable_claim_hash: str,
        transition_at_unix: float,
        transition_nonce: str,
    ) -> dict[str, Any]:
        expected_input_hash = cls._expected_input_hash(
            run_id=run_id,
            attempt_id=attempt_id,
            route_identity_sha256=route_identity_sha256,
            suite_identity_sha256=suite_identity_sha256,
        )
        return {
            "schema_version": START_TRANSITION_SCHEMA,
            "run_id": run_id,
            "attempt_id": attempt_id,
            "suite_identity_sha256": suite_identity_sha256,
            "route_identity_sha256": route_identity_sha256,
            "expected_input_hash": expected_input_hash,
            "immutable_claim_hash": immutable_claim_hash,
            "status": "side_effect_started",
            "side_effect_started": True,
            "side_effect_executed": False,
            "transition_at_unix": transition_at_unix,
            "transition_nonce": transition_nonce,
        }

    def _admit_identity_payload(
        self,
        *,
        identity_kind: str,
        public_label: str,
        commitment_inputs: dict[str, Any],
        suite_identity_sha256: str | None,
        suite_envelope: dict[str, Any] | None,
        exposure_ledger_path: str | Path | None,
        exposure_seal_path: str | Path | None,
        rotated_from: str | None,
    ) -> dict[str, Any]:
        """Recompute/verify identity; never trust a bare caller-supplied hash."""
        from .canonical import identity_from_fields

        if identity_kind == "HiddenSuiteIdentityEnvelope" and suite_envelope is None:
            return {
                "ok": False,
                "reason": "full_suite_envelope_required",
            }
        if suite_envelope is not None:
            from .objects import (
                hidden_suite_registration_commitment_inputs,
                validate_object,
            )

            if identity_kind != "HiddenSuiteIdentityEnvelope":
                return {
                    "ok": False,
                    "reason": "suite_envelope_only_for_hidden_suite_identity",
                }
            v = validate_object(suite_envelope, "HiddenSuiteIdentityEnvelope")
            if not v.get("ok"):
                return {
                    "ok": False,
                    "reason": "suite_envelope_invalid",
                    "validation": v,
                }
            if public_label != suite_envelope.get("public_suite_label"):
                return {
                    "ok": False,
                    "reason": "suite_public_label_mismatch",
                    "expected": suite_envelope.get("public_suite_label"),
                    "supplied": public_label,
                }
            expected_inputs = hidden_suite_registration_commitment_inputs(suite_envelope)
            if commitment_inputs != expected_inputs:
                return {
                    "ok": False,
                    "reason": "suite_registration_commitment_inputs_mismatch",
                    "expected": expected_inputs,
                }
            sha = str(suite_envelope["suite_identity_sha256"])
            if suite_identity_sha256 is not None and suite_identity_sha256 != sha:
                return {
                    "ok": False,
                    "reason": "identity_hash_mismatch_or_drifted",
                    "expected": sha,
                    "supplied": suite_identity_sha256,
                }
            if exposure_ledger_path is None or exposure_seal_path is None:
                return {
                    "ok": False,
                    "reason": "verified_exposure_ledger_and_seal_required",
                }
            from .exposure_ledger import verify_exposure_admission_evidence

            exposure_admission = verify_exposure_admission_evidence(
                suite_envelope=suite_envelope,
                state_dir=self.db_path.parent,
                ledger_path=exposure_ledger_path,
                seal_path=exposure_seal_path,
            )
            if not exposure_admission.get("ok"):
                return {
                    "ok": False,
                    "reason": "exposure_admission_evidence_invalid",
                    "detail": exposure_admission,
                }
            env_rotated = suite_envelope.get("rotated_from")
            if rotated_from is not None and env_rotated != rotated_from:
                return {
                    "ok": False,
                    "reason": "rotated_from_mismatch",
                    "expected": rotated_from,
                    "observed": env_rotated,
                }
            ident = {
                "hash_profile": "canonical-json-v1+sha256",
                "kind": identity_kind,
                "identity_sha256": sha,
                "fields": {
                    "public_label": public_label,
                    "commitment_inputs": commitment_inputs,
                    "rotated_from": rotated_from if rotated_from is not None else env_rotated,
                },
                "suite_envelope": suite_envelope,
                "exposure_admission_proof": exposure_admission["proof"],
                "admission": "full_envelope_recomputed+verified_exposure_seal",
            }
            return {"ok": True, "identity": ident, "sha": sha}

        derived = identity_from_fields(
            identity_kind,
            {
                "public_label": public_label,
                "commitment_inputs": commitment_inputs,
                "rotated_from": rotated_from,
            },
        )
        sha = derived["identity_sha256"]
        if suite_identity_sha256 is not None and suite_identity_sha256 != sha:
            return {
                "ok": False,
                "reason": "identity_hash_mismatch_or_drifted",
                "expected": sha,
                "supplied": suite_identity_sha256,
            }
        ident = {
            "hash_profile": "canonical-json-v1+sha256",
            "kind": identity_kind,
            "identity_sha256": sha,
            "fields": {
                "public_label": public_label,
                "commitment_inputs": commitment_inputs,
                "rotated_from": rotated_from,
            },
            "admission": "derived_recomputed",
        }
        return {"ok": True, "identity": ident, "sha": sha}

    def register_identity(
        self,
        *,
        identity_kind: str,
        public_label: str,
        commitment_inputs: dict[str, Any],
        suite_identity_sha256: str | None = None,
        suite_envelope: dict[str, Any] | None = None,
        exposure_ledger_path: str | Path | None = None,
        exposure_seal_path: str | Path | None = None,
        rotated_from: str | None = None,
    ) -> dict[str, Any]:
        admitted = self._admit_identity_payload(
            identity_kind=identity_kind,
            public_label=public_label,
            commitment_inputs=commitment_inputs,
            suite_identity_sha256=suite_identity_sha256,
            suite_envelope=suite_envelope,
            exposure_ledger_path=exposure_ledger_path,
            exposure_seal_path=exposure_seal_path,
            rotated_from=rotated_from,
        )
        if not admitted.get("ok"):
            return admitted
        sha = admitted["sha"]
        ident = admitted["identity"]
        now = time.time()
        payload = json.dumps(ident, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM suite_identities WHERE suite_identity_sha256=?",
                (sha,),
            ).fetchone()
            if row is not None and row["status"] == "revoked":
                conn.execute("ROLLBACK")
                return {"ok": False, "reason": "identity_revoked", "identity_sha256": sha}
            # Revalidate exposure evidence as close as possible to the same
            # BEGIN IMMEDIATE commit. Filesystem evidence is not transactionally
            # locked with SQLite; mandatory use-time revalidation still applies.
            if suite_envelope is not None:
                from .exposure_ledger import verify_exposure_admission_evidence

                commit_window = verify_exposure_admission_evidence(
                    suite_envelope=suite_envelope,
                    state_dir=self.db_path.parent,
                    ledger_path=exposure_ledger_path,
                    seal_path=exposure_seal_path,
                )
                if not commit_window.get("ok") or commit_window.get("proof") != ident.get(
                    "exposure_admission_proof"
                ):
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "reason": "exposure_admission_evidence_commit_window_drift",
                        "detail": commit_window,
                    }
            conn.execute(
                """
                INSERT INTO suite_identities(
                    suite_identity_sha256, public_label, status, rotated_from,
                    payload_json, created_at_unix, revoked_at_unix, revoke_reason
                ) VALUES(?,?,?,?,?,?,NULL,NULL)
                ON CONFLICT(suite_identity_sha256) DO UPDATE SET
                    public_label=excluded.public_label,
                    status='active',
                    rotated_from=COALESCE(excluded.rotated_from, suite_identities.rotated_from),
                    payload_json=excluded.payload_json
                """,
                (sha, public_label, "active", rotated_from, payload, now),
            )
            conn.execute("COMMIT")
        return {"ok": True, "identity": ident, "status": "active"}

    def rotate(
        self,
        *,
        old_identity_sha256: str,
        public_label: str,
        commitment_inputs: dict[str, Any],
        identity_kind: str,
        new_suite_identity_sha256: str | None = None,
        new_suite_envelope: dict[str, Any] | None = None,
        exposure_ledger_path: str | Path | None = None,
        exposure_seal_path: str | Path | None = None,
    ) -> dict[str, Any]:
        admitted = self._admit_identity_payload(
            identity_kind=identity_kind,
            public_label=public_label,
            commitment_inputs=commitment_inputs,
            suite_identity_sha256=new_suite_identity_sha256,
            suite_envelope=new_suite_envelope,
            exposure_ledger_path=exposure_ledger_path,
            exposure_seal_path=exposure_seal_path,
            rotated_from=old_identity_sha256,
        )
        if not admitted.get("ok"):
            return admitted
        new_sha = admitted["sha"]
        new_ident = admitted["identity"]
        if new_sha == old_identity_sha256:
            return {"ok": False, "reason": "rotation_did_not_change_identity"}
        now = time.time()
        hist = canonical_json_sha256({"from": old_identity_sha256, "to": new_sha})
        payload = json.dumps(new_ident, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute(
                "SELECT * FROM suite_identities WHERE suite_identity_sha256=? AND status='active'",
                (old_identity_sha256,),
            ).fetchone()
            if old is None:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason": "old_identity_not_active"}
            # Re-verify stored old payload integrity at rotation time
            old_verify = self._verify_stored_suite_row(dict(old))
            if not old_verify.get("ok"):
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "old_identity_payload_invalid",
                    "detail": old_verify,
                }
            if new_suite_envelope is not None:
                from .exposure_ledger import verify_exposure_admission_evidence

                commit_window = verify_exposure_admission_evidence(
                    suite_envelope=new_suite_envelope,
                    state_dir=self.db_path.parent,
                    ledger_path=exposure_ledger_path,
                    seal_path=exposure_seal_path,
                )
                if not commit_window.get("ok") or commit_window.get("proof") != new_ident.get(
                    "exposure_admission_proof"
                ):
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "reason": "exposure_admission_evidence_commit_window_drift",
                        "detail": commit_window,
                    }
            conn.execute(
                """
                UPDATE suite_identities
                SET status='revoked', revoked_at_unix=?, revoke_reason='rotated'
                WHERE suite_identity_sha256=?
                """,
                (now, old_identity_sha256),
            )
            conn.execute(
                """
                INSERT INTO suite_identities(
                    suite_identity_sha256, public_label, status, rotated_from,
                    payload_json, created_at_unix, revoked_at_unix, revoke_reason
                ) VALUES(?,?, 'active', ?, ?, ?, NULL, NULL)
                """,
                (new_sha, public_label, old_identity_sha256, payload, now),
            )
            conn.execute(
                """
                INSERT INTO rotation_history(from_sha, to_sha, history_sha256, created_at_unix)
                VALUES(?,?,?,?)
                """,
                (old_identity_sha256, new_sha, hist, now),
            )
            conn.execute("COMMIT")
        return {
            "ok": True,
            "old_identity_sha256": old_identity_sha256,
            "new_identity": new_ident,
            "new_identity_sha256": new_sha,
            "rotated_from": old_identity_sha256,
            "status": "rotated",
        }

    def _verify_stored_suite_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Recompute/verify identity payload bound to the active row primary key."""
        from .canonical import identity_from_fields

        sha = str(row.get("suite_identity_sha256") or "")
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            return {"ok": False, "reason": "payload_json_corrupt", "error": type(exc).__name__}
        if payload.get("identity_sha256") != sha:
            return {
                "ok": False,
                "reason": "stored_identity_key_mismatch",
                "key": sha,
                "payload_identity": payload.get("identity_sha256"),
            }
        suite_envelope = payload.get("suite_envelope")
        if suite_envelope is not None:
            from .objects import (
                hidden_suite_registration_commitment_inputs,
                validate_object,
            )

            v = validate_object(suite_envelope, "HiddenSuiteIdentityEnvelope")
            if not v.get("ok"):
                return {"ok": False, "reason": "stored_suite_envelope_invalid", "validation": v}
            if suite_envelope.get("suite_identity_sha256") != sha:
                return {"ok": False, "reason": "stored_suite_envelope_identity_drift"}
            if payload.get("kind") != "HiddenSuiteIdentityEnvelope":
                return {"ok": False, "reason": "stored_suite_identity_kind_drift"}
            fields = payload.get("fields") or {}
            if fields.get("public_label") != suite_envelope.get("public_suite_label"):
                return {"ok": False, "reason": "stored_suite_public_label_drift"}
            expected_inputs = hidden_suite_registration_commitment_inputs(suite_envelope)
            if fields.get("commitment_inputs") != expected_inputs:
                return {"ok": False, "reason": "stored_suite_commitment_inputs_drift"}
            if row.get("public_label") != suite_envelope.get("public_suite_label"):
                return {"ok": False, "reason": "stored_suite_row_public_label_drift"}
            envelope_rotated_from = suite_envelope.get("rotated_from")
            if fields.get("rotated_from") != envelope_rotated_from:
                return {"ok": False, "reason": "stored_suite_rotated_from_drift"}
            if row.get("rotated_from") != envelope_rotated_from:
                return {"ok": False, "reason": "stored_suite_row_rotation_drift"}
            expected_payload_keys = {
                "hash_profile",
                "kind",
                "identity_sha256",
                "fields",
                "suite_envelope",
                "exposure_admission_proof",
                "admission",
            }
            if set(payload) != expected_payload_keys:
                return {"ok": False, "reason": "stored_suite_registry_payload_shape_drift"}
            if payload.get("admission") != ("full_envelope_recomputed+verified_exposure_seal"):
                return {"ok": False, "reason": "stored_suite_admission_mode_drift"}
            proof = payload.get("exposure_admission_proof")
            if not isinstance(proof, dict):
                return {"ok": False, "reason": "stored_exposure_admission_proof_missing"}
            from .exposure_ledger import verify_exposure_admission_evidence

            current = verify_exposure_admission_evidence(
                suite_envelope=suite_envelope,
                state_dir=self.db_path.parent,
                ledger_path=self.db_path.parent / str(proof.get("ledger_file") or ""),
                seal_path=self.db_path.parent / str(proof.get("seal_file") or ""),
            )
            if not current.get("ok") or current.get("proof") != proof:
                return {
                    "ok": False,
                    "reason": "stored_exposure_admission_proof_invalid_or_drifted",
                    "detail": current,
                }
            return {
                "ok": True,
                "admission": "full_envelope_recomputed+verified_exposure_seal",
            }
        if payload.get("kind") == "HiddenSuiteIdentityEnvelope":
            return {"ok": False, "reason": "stored_full_suite_envelope_missing"}
        fields = payload.get("fields") or {}
        expected = identity_from_fields(
            str(payload.get("kind") or "HiddenSuiteIdentityEnvelope"),
            fields,
        )["identity_sha256"]
        if expected != sha:
            return {
                "ok": False,
                "reason": "stored_identity_recompute_mismatch",
                "expected": expected,
                "key": sha,
            }
        return {"ok": True, "admission": "derived_recomputed"}

    def revoke(self, *, identity_sha256: str, reason: str) -> dict[str, Any]:
        now = time.time()
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM suite_identities WHERE suite_identity_sha256=?",
                (identity_sha256,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason": "unknown_identity"}
            if row["status"] == "revoked":
                conn.execute("COMMIT")
                return {"ok": True, "already_revoked": True, "identity_sha256": identity_sha256}
            conn.execute(
                """
                UPDATE suite_identities
                SET status='revoked', revoked_at_unix=?, revoke_reason=?
                WHERE suite_identity_sha256=?
                """,
                (now, reason, identity_sha256),
            )
            conn.execute("COMMIT")
        return {"ok": True, "revoked": True, "identity_sha256": identity_sha256}

    def may_start_run(self, *, suite_identity_sha256: str) -> dict[str, Any]:
        with _connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM suite_identities WHERE suite_identity_sha256=?",
                (suite_identity_sha256,),
            ).fetchone()
        if row is None:
            return {
                "ok": False,
                "allowed": False,
                "reason": "suite_identity_not_active",
                "suite_identity_sha256": suite_identity_sha256,
            }
        if row["status"] != "active":
            return {
                "ok": False,
                "allowed": False,
                "reason": "revoked_suite_cannot_start_new_run",
                "suite_identity_sha256": suite_identity_sha256,
            }
        verification = self._verify_stored_suite_row(dict(row))
        if not verification.get("ok"):
            return {
                "ok": False,
                "allowed": False,
                "reason": "suite_identity_admission_failed",
                "detail": verification,
                "suite_identity_sha256": suite_identity_sha256,
            }
        return {
            "ok": True,
            "allowed": True,
            "suite_identity_sha256": suite_identity_sha256,
        }

    def claim_run(
        self,
        *,
        run_id: str,
        attempt_id: str,
        route_identity_sha256: str,
        suite_identity_sha256: str,
    ) -> dict[str, Any]:
        """Use-time atomic decision: suite must be active AND run_id free.

        Winning claim inserts the only side-effect slot. Losing claimants receive
        a clean rejection without unhandled exceptions or corruption.
        """
        now = time.time()
        with _connect(self.db_path) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                suite = conn.execute(
                    "SELECT * FROM suite_identities WHERE suite_identity_sha256=?",
                    (suite_identity_sha256,),
                ).fetchone()
                if suite is None:
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "claimed": False,
                        "reason": "suite_identity_not_active",
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "side_effect_allowed": False,
                    }
                if suite["status"] == "revoked":
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "claimed": False,
                        "reason": "revoked_suite_cannot_start_new_run",
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "side_effect_allowed": False,
                    }
                # Use-time admission: recompute/verify stored identity; do not trust row key alone
                suite_verify = self._verify_stored_suite_row(dict(suite))
                if not suite_verify.get("ok"):
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "claimed": False,
                        "reason": "suite_identity_admission_failed",
                        "detail": suite_verify,
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "side_effect_allowed": False,
                    }
                existing = conn.execute(
                    "SELECT * FROM run_claims WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if existing is not None:
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "claimed": False,
                        "reason": "duplicate_run_id_second_side_effect_blocked",
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "existing": dict(existing),
                        "side_effect_allowed": False,
                    }
                att = conn.execute(
                    "SELECT 1 FROM run_attempts WHERE run_id=? AND attempt_id=?",
                    (run_id, attempt_id),
                ).fetchone()
                if att is not None:
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "claimed": False,
                        "reason": "duplicate_attempt_id",
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "side_effect_allowed": False,
                    }
                n_attempts = conn.execute(
                    "SELECT COUNT(*) AS c FROM run_attempts WHERE run_id=?",
                    (run_id,),
                ).fetchone()["c"]
                if int(n_attempts) >= self.max_attempts:
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "claimed": False,
                        "reason": "attempt_bound_exceeded",
                        "run_id": run_id,
                        "max_attempts": self.max_attempts,
                        "side_effect_allowed": False,
                    }
                record = {
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "route_identity_sha256": route_identity_sha256,
                    "suite_identity_sha256": suite_identity_sha256,
                    "status": "claimed",
                    "side_effect_started": False,
                    "side_effect_executed": False,
                }
                record_sha = canonical_json_sha256(record)
                conn.execute(
                    """
                    INSERT INTO run_claims(
                        run_id, attempt_id, route_identity_sha256, suite_identity_sha256,
                        status, side_effect_started, side_effect_executed, record_sha256,
                        created_at_unix, updated_at_unix
                    ) VALUES(?,?,?,?, 'claimed', 0, 0, ?, ?, ?)
                    """,
                    (
                        run_id,
                        attempt_id,
                        route_identity_sha256,
                        suite_identity_sha256,
                        record_sha,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO run_attempts(run_id, attempt_id, status, created_at_unix)
                    VALUES(?,?, 'claimed', ?)
                    """,
                    (run_id, attempt_id, now),
                )
                conn.execute("COMMIT")
                record["record_sha256"] = record_sha
                return {
                    "ok": True,
                    "claimed": True,
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "side_effect_allowed": True,
                    "record": record,
                }
            except sqlite3.IntegrityError:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                return {
                    "ok": False,
                    "claimed": False,
                    "reason": "duplicate_run_id_second_side_effect_blocked",
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "side_effect_allowed": False,
                }

    @staticmethod
    def _verify_run_claim_record(rec: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        """Recompute the immutable claim record bound by record_sha256."""
        row = dict(rec)
        immutable_claim = {
            "run_id": row.get("run_id"),
            "attempt_id": row.get("attempt_id"),
            "route_identity_sha256": row.get("route_identity_sha256"),
            "suite_identity_sha256": row.get("suite_identity_sha256"),
            "status": "claimed",
            "side_effect_started": False,
            "side_effect_executed": False,
        }
        expected = canonical_json_sha256(immutable_claim)
        if row.get("record_sha256") != expected:
            return {
                "ok": False,
                "reason": "run_claim_record_sha256_mismatch",
                "expected": expected,
                "observed": row.get("record_sha256"),
            }
        return {"ok": True, "record_sha256": expected}

    @classmethod
    def _verify_start_transition_record(cls, rec: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        """Require and recompute the start-transition integrity hash.

        A coordinated mutation of status + side_effect_started that leaves the
        original claim hash untouched must fail here. Blank, stale, malformed,
        or independently tampered transition hashes also fail closed.
        """
        row = dict(rec)
        claim_verify = cls._verify_run_claim_record(row)
        if not claim_verify.get("ok"):
            return {
                "ok": False,
                "reason": "run_claim_integrity_failed",
                "detail": claim_verify,
            }
        stored = row.get("start_transition_sha256")
        nonce = row.get("start_transition_nonce")
        at_unix = row.get("start_transition_at_unix")
        if stored in (None, "") or nonce in (None, "") or at_unix is None:
            return {
                "ok": False,
                "reason": "start_transition_hash_missing",
                "observed": stored,
            }
        try:
            at_unix_f = float(at_unix)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "reason": "start_transition_timestamp_malformed",
                "observed": at_unix,
            }
        if not isinstance(nonce, str) or len(nonce) < 16:
            return {
                "ok": False,
                "reason": "start_transition_nonce_malformed",
            }
        if int(row.get("side_effect_started") or 0) != 1:
            return {
                "ok": False,
                "reason": "start_transition_flag_mismatch",
            }
        if row.get("status") != "side_effect_started":
            return {
                "ok": False,
                "reason": "start_transition_status_mismatch",
                "observed": row.get("status"),
            }
        if int(row.get("side_effect_executed") or 0) != 0:
            return {
                "ok": False,
                "reason": "start_transition_executed_flag_drift",
            }
        transition = cls._build_start_transition_record(
            run_id=str(row.get("run_id") or ""),
            attempt_id=str(row.get("attempt_id") or ""),
            route_identity_sha256=str(row.get("route_identity_sha256") or ""),
            suite_identity_sha256=str(row.get("suite_identity_sha256") or ""),
            immutable_claim_hash=str(claim_verify["record_sha256"]),
            transition_at_unix=at_unix_f,
            transition_nonce=str(nonce),
        )
        expected = canonical_json_sha256(transition)
        if stored != expected:
            return {
                "ok": False,
                "reason": "start_transition_sha256_mismatch",
                "expected": expected,
                "observed": stored,
            }
        return {
            "ok": True,
            "start_transition_sha256": expected,
            "immutable_claim_hash": claim_verify["record_sha256"],
            "transition": transition,
        }

    def mark_side_effect_started(self, *, run_id: str) -> dict[str, Any]:
        """Durable transition before container start; crash-retry stays fail-closed.

        Atomically rechecks the associated suite is still active in the same
        BEGIN IMMEDIATE transaction (closes claim→revoke→start TOCTOU). Computes
        and persists the start-transition integrity hash chained from the
        immutable claim hash in the same transaction.
        """
        now = time.time()
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_run_claim_transition_columns(conn)
            rec = conn.execute(
                "SELECT * FROM run_claims WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if rec is None:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason": "run_not_claimed"}
            claim_verify = self._verify_run_claim_record(rec)
            if not claim_verify.get("ok"):
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "run_claim_integrity_failed",
                    "detail": claim_verify,
                    "run_id": run_id,
                    "side_effect_allowed": False,
                }
            if int(rec["side_effect_started"]) == 1 or int(rec["side_effect_executed"]) == 1:
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "side_effect_already_started_or_executed",
                    "run_id": run_id,
                }
            if rec["status"] != "claimed":
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "run_claim_transition_state_invalid",
                    "run_id": run_id,
                }
            # Claimed rows must not already carry a transition hash.
            if rec["start_transition_sha256"] not in (None, ""):
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "start_transition_hash_premature",
                    "run_id": run_id,
                }
            suite_sha = str(rec["suite_identity_sha256"])
            suite = conn.execute(
                "SELECT * FROM suite_identities WHERE suite_identity_sha256=?",
                (suite_sha,),
            ).fetchone()
            if suite is None:
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "suite_identity_not_active",
                    "run_id": run_id,
                    "suite_identity_sha256": suite_sha,
                    "side_effect_allowed": False,
                }
            if suite["status"] != "active":
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "revoked_suite_cannot_start_side_effect",
                    "run_id": run_id,
                    "suite_identity_sha256": suite_sha,
                    "suite_status": suite["status"],
                    "side_effect_allowed": False,
                }
            suite_verify = self._verify_stored_suite_row(dict(suite))
            if not suite_verify.get("ok"):
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "suite_identity_admission_failed",
                    "detail": suite_verify,
                    "run_id": run_id,
                    "side_effect_allowed": False,
                }
            nonce = secrets.token_hex(16)
            transition = self._build_start_transition_record(
                run_id=str(rec["run_id"]),
                attempt_id=str(rec["attempt_id"]),
                route_identity_sha256=str(rec["route_identity_sha256"]),
                suite_identity_sha256=str(rec["suite_identity_sha256"]),
                immutable_claim_hash=str(claim_verify["record_sha256"]),
                transition_at_unix=now,
                transition_nonce=nonce,
            )
            transition_sha = canonical_json_sha256(transition)
            conn.execute(
                """
                UPDATE run_claims
                SET side_effect_started=1,
                    status='side_effect_started',
                    start_transition_sha256=?,
                    start_transition_at_unix=?,
                    start_transition_nonce=?,
                    updated_at_unix=?
                WHERE run_id=?
                """,
                (transition_sha, now, nonce, now, run_id),
            )
            conn.execute("COMMIT")
        return {
            "ok": True,
            "run_id": run_id,
            "status": "side_effect_started",
            "start_transition_sha256": transition_sha,
            "immutable_claim_hash": claim_verify["record_sha256"],
        }

    def mark_side_effect(self, *, run_id: str) -> dict[str, Any]:
        """Finalize only an already-started side effect under active-suite checks.

        Requires and recomputes the exact start-transition hash before any
        finalization state change.
        """
        now = time.time()
        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_run_claim_transition_columns(conn)
            rec = conn.execute(
                "SELECT * FROM run_claims WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if rec is None:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason": "run_not_claimed"}
            claim_verify = self._verify_run_claim_record(rec)
            if not claim_verify.get("ok"):
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "run_claim_integrity_failed",
                    "detail": claim_verify,
                    "run_id": run_id,
                }
            if int(rec["side_effect_executed"]) == 1:
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "side_effect_already_executed",
                    "run_id": run_id,
                }
            if int(rec["side_effect_started"]) == 0:
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "side_effect_start_transition_required",
                    "run_id": run_id,
                }
            if rec["status"] != "side_effect_started":
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "side_effect_finalize_transition_state_invalid",
                    "run_id": run_id,
                }
            transition_verify = self._verify_start_transition_record(rec)
            if not transition_verify.get("ok"):
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "start_transition_integrity_failed",
                    "detail": transition_verify,
                    "run_id": run_id,
                }
            suite_sha = str(rec["suite_identity_sha256"])
            suite = conn.execute(
                "SELECT * FROM suite_identities WHERE suite_identity_sha256=?",
                (suite_sha,),
            ).fetchone()
            if suite is None or suite["status"] != "active":
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "revoked_or_missing_suite_cannot_finalize_side_effect",
                    "run_id": run_id,
                    "suite_identity_sha256": suite_sha,
                }
            suite_verify = self._verify_stored_suite_row(dict(suite))
            if not suite_verify.get("ok"):
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "reason": "suite_identity_admission_failed",
                    "detail": suite_verify,
                    "run_id": run_id,
                }
            conn.execute(
                """
                UPDATE run_claims
                SET side_effect_executed=1, status='side_effect_done', updated_at_unix=?
                WHERE run_id=?
                """,
                (now, run_id),
            )
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM run_claims WHERE side_effect_executed=1"
            ).fetchone()["c"]
            conn.execute("COMMIT")
        return {
            "ok": True,
            "run_id": run_id,
            "side_effect_count": int(count),
            "start_transition_sha256": transition_verify.get("start_transition_sha256"),
        }

    def status(self) -> dict[str, Any]:
        with _connect(self.db_path) as conn:
            run_count = conn.execute("SELECT COUNT(*) AS c FROM run_claims").fetchone()["c"]
            se_count = conn.execute(
                "SELECT COUNT(*) AS c FROM run_claims WHERE side_effect_executed=1"
            ).fetchone()["c"]
            se_started = conn.execute(
                "SELECT COUNT(*) AS c FROM run_claims WHERE side_effect_started=1"
            ).fetchone()["c"]
            active = conn.execute(
                "SELECT COUNT(*) AS c FROM suite_identities WHERE status='active'"
            ).fetchone()["c"]
            revoked = conn.execute(
                "SELECT COUNT(*) AS c FROM suite_identities WHERE status='revoked'"
            ).fetchone()["c"]
        return {
            "schema_version": SCHEMA_VERSION,
            "run_count": int(run_count),
            "side_effect_count": int(se_count),
            "side_effect_started_count": int(se_started),
            "active_suite_count": int(active),
            "revoked_suite_count": int(revoked),
            "max_attempts": self.max_attempts,
            "db_path": str(self.db_path),
            "authority": False,
        }

    def export_json_snapshot(self, path: str | Path) -> dict[str, Any]:
        """Non-authoritative JSON snapshot for object export (not used for CAS)."""
        with _connect(self.db_path) as conn:
            claims = [dict(r) for r in conn.execute("SELECT * FROM run_claims").fetchall()]
            suites = [dict(r) for r in conn.execute("SELECT * FROM suite_identities").fetchall()]
        snap = {
            "schema_version": "xinao.g4.hidden_capability_seam.run_idempotency_registry.v1",
            "max_attempts": self.max_attempts,
            "records": {c["run_id"]: c for c in claims},
            "suites": {s["suite_identity_sha256"]: s for s in suites},
            "side_effect_count": sum(1 for c in claims if int(c["side_effect_executed"]) == 1),
            "authority": False,
            "cas_backend": "sqlite3_delete_journal_begin_immediate",
            "cas_backend_note": (
                "DELETE journal + BEGIN IMMEDIATE cross-process serialization; "
                "not WAL. Colocated JSON projection is non-authoritative."
            ),
        }
        write_json(path, snap)
        return snap
