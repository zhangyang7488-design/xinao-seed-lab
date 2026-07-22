"""Append-only ExposureLedger (hash-chained). Historical rewrites fail verification."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .canonical import canonical_json_sha256, sha256_hex
from .hash_chain import GENESIS_PREV, HashChainedLog
from .security_model import is_subject_eligible

LOG_KIND = "exposure_ledger.v1"
ADMISSION_PROOF_SCHEMA = "xinao.g4.hidden_capability_seam.exposure_admission_proof.v1"
EXPOSURE_ENTRY_BODY_KEYS = frozenset(
    {
        "principal_id",
        "role",
        "exposure_subject_identity_sha256",
        "exposure_kind",
        "object_ref",
        "note",
        "synthetic_only",
        "not_admission_evidence",
    }
)
# Authority-bearing or drifted fields rejected on every admitted exposure entry.
FORBIDDEN_EXPOSURE_BODY_KEYS = frozenset(
    {
        "authority",
        "admission",
        "g4_closed",
        "g5_active",
        "parent_complete",
        "real_hidden",
        "real_provider",
        "completion_claim_allowed",
        "score",
        "scoring",
        "truth",
        "seed",
        "answer",
        "heldout",
        "capability_result",
    }
)


def validate_exposure_entry_body(
    body: Any,
    *,
    expected_subject: str | None = None,
) -> dict[str, Any]:
    """Complete supported exposure-entry body schema for every admitted entry."""
    if not isinstance(body, dict):
        return {"ok": False, "reason": "exposure_entry_body_not_mapping"}
    keys = set(body)
    missing = sorted(EXPOSURE_ENTRY_BODY_KEYS - keys)
    if missing:
        return {
            "ok": False,
            "reason": "exposure_entry_body_missing_keys",
            "keys": missing,
        }
    extra = sorted(keys - EXPOSURE_ENTRY_BODY_KEYS)
    if extra:
        return {
            "ok": False,
            "reason": "exposure_entry_body_extra_keys",
            "keys": extra,
        }
    forbidden = sorted(keys & FORBIDDEN_EXPOSURE_BODY_KEYS)
    if forbidden:
        return {
            "ok": False,
            "reason": "exposure_entry_authority_bearing_fields",
            "keys": forbidden,
        }
    for field in (
        "principal_id",
        "role",
        "exposure_subject_identity_sha256",
        "exposure_kind",
        "object_ref",
        "note",
    ):
        if not isinstance(body.get(field), str):
            return {
                "ok": False,
                "reason": "exposure_entry_field_type_invalid",
                "field": field,
            }
    if body.get("synthetic_only") is not True:
        return {"ok": False, "reason": "exposure_entry_synthetic_only_not_true"}
    if body.get("not_admission_evidence") is not True:
        return {
            "ok": False,
            "reason": "exposure_entry_not_admission_evidence_not_true",
        }
    subject = body.get("exposure_subject_identity_sha256")
    if not subject or len(str(subject)) != 64:
        return {"ok": False, "reason": "exposure_entry_subject_identity_invalid"}
    if expected_subject is not None and subject != expected_subject:
        return {
            "ok": False,
            "reason": "exposure_entry_subject_binding_mismatch",
            "expected": expected_subject,
            "observed": subject,
        }
    return {"ok": True}


class ExposureLedger:
    def __init__(self, path: str | Path) -> None:
        self.log = HashChainedLog(path, log_kind=LOG_KIND)

    def record_exposure(
        self,
        *,
        principal_id: str,
        role: str,
        exposure_subject_identity_sha256: str,
        exposure_kind: str,
        object_ref: str,
        note: str = "",
    ) -> dict[str, Any]:
        body = {
            "principal_id": principal_id,
            "role": role,
            "exposure_subject_identity_sha256": exposure_subject_identity_sha256,
            "exposure_kind": exposure_kind,
            "object_ref": object_ref,
            "note": note,
            "synthetic_only": True,
            "not_admission_evidence": True,
        }
        body_check = validate_exposure_entry_body(body)
        if not body_check.get("ok"):
            raise ValueError(f"exposure_entry_schema_invalid:{body_check}")
        rec = self.log.append(body)
        # Flatten for eligibility consumers
        flat = {
            **body,
            "entry_index": rec["entry_index"],
            "entry_sha256": rec["entry_sha256"],
            "prev_sha256": rec["prev_sha256"],
        }
        return flat

    def verify(self) -> dict[str, Any]:
        return self.log.verify()

    def exposures(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for rec in self.log.entries():
            body = dict(rec["body"])
            body["entry_index"] = rec["entry_index"]
            body["entry_sha256"] = rec["entry_sha256"]
            body["prev_sha256"] = rec["prev_sha256"]
            out.append(body)
        return out

    def subject_eligibility(
        self,
        *,
        exposure_subject_identity_sha256: str,
        principal_id: str,
        suite_identity_sha256: str | None = None,
    ) -> dict[str, Any]:
        return is_subject_eligible(
            exposure_subject_identity_sha256=exposure_subject_identity_sha256,
            principal_id=principal_id,
            exposure_records=self.exposures(),
            suite_identity_sha256=suite_identity_sha256,
        )

    def reject_rewrite_attempt(self) -> dict[str, Any]:
        """Observable negative: any rewrite/delete/reorder fails verify after tamper."""
        return {
            "ok": False,
            "reason": "exposure_ledger_rewrite_forbidden",
            "note": "use verify() after external tamper to detect",
        }


def verify_exposure_admission_evidence(
    *,
    suite_envelope: dict[str, Any],
    state_dir: str | Path,
    ledger_path: str | Path,
    seal_path: str | Path,
    file_reader: Callable[[Path], bytes] | None = None,
) -> dict[str, Any]:
    """Verify the concrete ledger+seal consumed by suite admission.

    Evidence files must be ordinary sibling files of the atomic state DB.  The
    returned proof contains only relative file names and deterministic hashes,
    so it can be stored with the admitted identity and recomputed at every
    use-time transition.

    Ledger content is read exactly once into a captured byte snapshot. Chain
    verification, head/length, entry-body schema validation, subject binding,
    and proof SHA/size are all derived from those same bytes. Seal bytes are
    likewise captured once. Lock state is observed once. The current decision
    never re-opens either content file; later use-time transitions revalidate
    from their own fresh single snapshots.

    Honest threat model: ledger, seal, and lock are colocated and are not an
    external authenticated anchor. Unkeyed hashes do not defeat an actor who
    can rewrite the whole colocated object set consistently.
    """
    base = Path(state_dir).resolve()
    raw_ledger = Path(ledger_path)
    raw_seal = Path(seal_path)
    if raw_ledger.is_symlink() or raw_seal.is_symlink():
        return {"ok": False, "reason": "exposure_evidence_symlink_forbidden"}
    try:
        ledger = raw_ledger.resolve(strict=True)
        seal_file = raw_seal.resolve(strict=True)
    except OSError as exc:
        return {
            "ok": False,
            "reason": "exposure_evidence_missing_or_unresolvable",
            "error_class": type(exc).__name__,
        }
    if ledger.parent != base or seal_file.parent != base:
        return {
            "ok": False,
            "reason": "exposure_evidence_outside_atomic_state_directory",
        }
    if ledger == seal_file:
        return {"ok": False, "reason": "exposure_ledger_and_seal_must_be_distinct"}

    reader = file_reader or (lambda path: Path(path).read_bytes())
    try:
        seal_bytes = reader(seal_file)
    except (OSError, ValueError, TypeError) as exc:
        return {
            "ok": False,
            "reason": "exposure_seal_unreadable",
            "error_class": type(exc).__name__,
        }
    seal_sha = sha256_hex(seal_bytes)
    seal_size = len(seal_bytes)
    try:
        seal = json.loads(seal_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "reason": "exposure_seal_unreadable",
            "error_class": type(exc).__name__,
        }
    if not isinstance(seal, dict) or seal.get("log_kind") != LOG_KIND:
        return {"ok": False, "reason": "exposure_seal_log_kind_mismatch"}
    if seal.get("authority") is not False or seal.get("synthetic_only") is not True:
        return {"ok": False, "reason": "exposure_seal_non_authority_flags_drift"}

    exposure = ExposureLedger(ledger)
    try:
        sealed_log_path = Path(str(seal.get("log_path") or "")).resolve(strict=True)
        sealed_lock_path = Path(str(seal.get("lock_db_path") or "")).resolve(strict=True)
        current_lock_path = exposure.log.lock_db.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return {"ok": False, "reason": "exposure_seal_path_binding_mismatch"}
    # Windows may expose the same file through an 8.3 short-name spelling in
    # TEMP while resolve() returns its long-name spelling. Bind the seal to the
    # resolved file identities, not to one incidental textual spelling.
    if sealed_log_path != ledger or sealed_lock_path != current_lock_path:
        return {"ok": False, "reason": "exposure_seal_path_binding_mismatch"}
    if seal.get("chain_ok_at_seal") is not True:
        return {"ok": False, "reason": "exposure_seal_chain_status_not_true"}

    # Single ledger content read for this invocation.
    try:
        ledger_bytes = reader(ledger)
    except (OSError, ValueError, TypeError) as exc:
        return {
            "ok": False,
            "reason": "exposure_ledger_unreadable",
            "error_class": type(exc).__name__,
        }
    ledger_sha = sha256_hex(ledger_bytes)
    ledger_size = len(ledger_bytes)
    try:
        entries = HashChainedLog.parse_entries_from_bytes(ledger_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "reason": "exposure_ledger_snapshot_parse_failed",
            "error_class": type(exc).__name__,
        }
    chain = HashChainedLog.verify_parsed_entries(entries, log_kind=LOG_KIND, path=str(ledger))
    lock_view = exposure.log.sealed_head_from_lock()
    verified = exposure.log.verify_against_seal(seal, chain=chain, lock_view=lock_view)
    if not verified.get("ok"):
        return {
            "ok": False,
            "reason": "exposure_ledger_seal_verification_failed",
            "verification": verified,
        }
    expected_head = str(suite_envelope.get("exposure_ledger_sealed_head_contract") or "")
    if expected_head == GENESIS_PREV or verified.get("head_sha256") != expected_head:
        return {
            "ok": False,
            "reason": "suite_exposure_head_not_backed_by_verified_seal",
            "expected": expected_head,
            "observed": verified.get("head_sha256"),
        }
    if suite_envelope.get("exposure_ledger_initial_head_contract") != GENESIS_PREV:
        return {"ok": False, "reason": "exposure_initial_head_contract_not_genesis"}

    expected_subject = str(suite_envelope.get("exposure_subject_identity_sha256") or "")
    if not entries:
        return {"ok": False, "reason": "exposure_ledger_empty_at_admission"}
    wrong_subject_entries: list[int] = []
    schema_invalid_entries: list[dict[str, Any]] = []
    for index, record in enumerate(entries):
        body = record.get("body") if isinstance(record, dict) else None
        body_check = validate_exposure_entry_body(body, expected_subject=expected_subject)
        if not body_check.get("ok"):
            if body_check.get("reason") == "exposure_entry_subject_binding_mismatch":
                wrong_subject_entries.append(index)
            else:
                schema_invalid_entries.append({"entry_index": index, "detail": body_check})
    if schema_invalid_entries:
        return {
            "ok": False,
            "reason": "exposure_entry_payload_schema_invalid",
            "entries": schema_invalid_entries,
        }
    if wrong_subject_entries:
        return {
            "ok": False,
            "reason": "exposure_ledger_subject_binding_mismatch",
            "entry_indexes": wrong_subject_entries,
        }

    proof_core = {
        "schema_version": ADMISSION_PROOF_SCHEMA,
        "ledger_file": ledger.name,
        "seal_file": seal_file.name,
        "ledger_file_sha256": ledger_sha,
        "ledger_file_size": ledger_size,
        "seal_file_sha256": seal_sha,
        "seal_file_size": seal_size,
        "seal_sha256": seal.get("seal_sha256"),
        "expected_length": verified.get("length"),
        "expected_head_sha256": verified.get("head_sha256"),
        "exposure_subject_identity_sha256": expected_subject,
        "log_kind": LOG_KIND,
        "snapshot_model": "single_ledger_byte_snapshot_plus_single_seal_capture",
        "colocated_unkeyed_threat_model": (
            "ledger_seal_lock_colocated_not_external_authenticated_anchor"
        ),
        "authority": False,
        "synthetic_only": True,
    }
    proof = {
        **proof_core,
        "proof_sha256": canonical_json_sha256(proof_core),
    }
    return {
        "ok": True,
        "proof": proof,
        "verification": verified,
        "ledger_content_reads": 1,
        "seal_content_reads": 1,
    }
