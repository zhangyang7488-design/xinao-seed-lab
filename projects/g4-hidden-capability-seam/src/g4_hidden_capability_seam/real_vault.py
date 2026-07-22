"""Real-identity bootstrap vault built on the accepted Windows ACL primitive.

The benchmark worlds remain synthetic, but their generator identity, secret-derived
suite identity, private parameters, and evaluator truth are real.  This class keeps
the event422 synthetic fixture type unchanged and reuses only its exact target-set,
identity-hold, ACL deny/lift/restore, and receipt-sealing machinery.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import write_json
from .vault import (
    CUSTODIAN_CAP,
    EVALUATOR_CAP,
    FINAL_TARGET_NAMES,
    PRE_RECEIPT_TARGET_NAMES,
    SUBJECT_CAP,
    SealedTruthVault,
)


REAL_BOOTSTRAP_LABEL = "REAL_HIDDEN_IDENTITY_SYNTHETIC_WORLD_G4_BOOTSTRAP_HOLD"


class RealHiddenBootstrapVault(SealedTruthVault):
    """Store one selected heldout suite while denying the subject read path."""

    def __init__(self, vault_root: str | Path) -> None:
        root = Path(vault_root).resolve()
        first_initialization = not root.exists() or not any(root.iterdir())
        super().__init__(root)
        if first_initialization:
            write_json(
                self.truth_path,
                {
                    "schema_version": "xinao.g4.real_hidden_bootstrap.sealed_truth.v1",
                    "benchmark_worlds_synthetic": True,
                    "real_hidden_identity": True,
                    "label": REAL_BOOTSTRAP_LABEL,
                    "suite_identity": None,
                    "generator_artifact": None,
                    "items": {},
                    "authority": False,
                    "g4_closed": False,
                },
            )
            write_json(
                self.meta_path,
                {
                    "schema_version": "xinao.g4.real_hidden_bootstrap.vault_meta.v1",
                    "vault_root": str(self.vault_root),
                    "subject_cap_allowed": False,
                    "evaluator_cap": EVALUATOR_CAP,
                    "custodian_cap": CUSTODIAN_CAP,
                    "benchmark_worlds_synthetic": True,
                    "real_hidden_identity": True,
                    "authority": False,
                    "g4_closed": False,
                },
            )

        existing = sorted(path.name for path in self.vault_root.iterdir())
        allowed_sets = {frozenset(PRE_RECEIPT_TARGET_NAMES), frozenset(FINAL_TARGET_NAMES)}
        if frozenset(existing) not in allowed_sets:
            raise RuntimeError("real_hidden_bootstrap_vault_target_set_not_exact")

    def deposit_private_bundle(
        self,
        *,
        private_bundle: dict[str, Any],
        suite_identity: dict[str, Any],
        generator_artifact: dict[str, Any],
        selected_case_ids: list[str],
        capability: str = CUSTODIAN_CAP,
    ) -> dict[str, Any]:
        if capability != CUSTODIAN_CAP:
            return {"ok": False, "reason": "deposit_denied"}
        if not selected_case_ids or len(selected_case_ids) != len(set(selected_case_ids)):
            return {"ok": False, "reason": "selected_case_ids_invalid"}
        records = private_bundle.get("records")
        if not isinstance(records, list):
            return {"ok": False, "reason": "private_bundle_records_missing"}
        by_id: dict[str, dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict):
                return {"ok": False, "reason": "private_record_not_mapping"}
            case_id = str(record.get("public_case_id") or "")
            if not case_id or case_id in by_id:
                return {"ok": False, "reason": "private_record_identity_invalid"}
            by_id[case_id] = record
        missing = sorted(set(selected_case_ids) - set(by_id))
        if missing:
            return {"ok": False, "reason": "selected_private_records_missing", "missing": missing}
        items: dict[str, dict[str, Any]] = {}
        for case_id in selected_case_ids:
            record = by_id[case_id]
            commitment = str(record.get("commitment_sha256") or "")
            if len(commitment) != 64 or any(char not in "0123456789abcdef" for char in commitment):
                return {"ok": False, "reason": "private_commitment_invalid", "case_id": case_id}
            if not isinstance(record.get("truth"), dict):
                return {"ok": False, "reason": "private_truth_missing", "case_id": case_id}
            if not isinstance(record.get("hidden_parameters"), dict):
                return {"ok": False, "reason": "hidden_parameters_missing", "case_id": case_id}
            items[case_id] = dict(record)
        data = self._read_truth_unlocked(expected_receipt=False)
        if data.get("items"):
            return {"ok": False, "reason": "vault_already_deposited"}
        data["suite_identity"] = dict(suite_identity)
        data["generator_artifact"] = dict(generator_artifact)
        data["items"] = items
        write_json(self.truth_path, data)
        return {
            "ok": True,
            "item_count": len(items),
            "selected_case_ids": list(selected_case_ids),
            "suite_identity_sha256": suite_identity.get("identity_sha256"),
            "generator_artifact_sha256": generator_artifact.get("artifact_sha256"),
            "real_hidden_identity": True,
            "benchmark_worlds_synthetic": True,
            "authority": False,
            "g4_closed": False,
        }

    def public_case_view(self, public_case_id: str) -> dict[str, Any]:
        data = self._read_truth_unlocked(expected_receipt=False)
        item = data.get("items", {}).get(public_case_id)
        if not isinstance(item, dict):
            return {"ok": False, "reason": "unknown_case"}
        return {
            "ok": True,
            "public_case_id": public_case_id,
            "public_instructions": item["public_instructions"],
            "task_input": item["task_input"],
            "commitment_sha256": item["commitment_sha256"],
            "authority": False,
            "g4_closed": False,
        }

    def evaluator_bundle(self, *, capability: str) -> dict[str, Any]:
        if capability != EVALUATOR_CAP:
            return {"ok": False, "reason": "evaluator_capability_invalid"}
        data = self._read_truth_unlocked(expected_receipt=True)
        return {
            "ok": True,
            "suite_identity": data.get("suite_identity"),
            "generator_artifact": data.get("generator_artifact"),
            "records": list((data.get("items") or {}).values()),
            "real_hidden_identity": True,
            "benchmark_worlds_synthetic": True,
            "authority": False,
            "g4_closed": False,
        }

    def subject_read(self, *, capability: str, public_case_id: str) -> dict[str, Any]:
        del capability
        return {
            "ok": False,
            "reason": "subject_vault_read_denied",
            "public_case_id": public_case_id,
            "vault_readable": False,
            "audited": True,
        }

    def status(self, *, expected_receipt: bool) -> dict[str, Any]:
        data = self._read_truth_unlocked(expected_receipt=expected_receipt)
        return {
            "schema_version": "xinao.g4.real_hidden_bootstrap.vault_status.v1",
            "object": "RealHiddenBootstrapVault",
            "item_count": len(data.get("items", {})),
            "benchmark_worlds_synthetic": True,
            "real_hidden_identity": True,
            "vault_root": str(self.vault_root),
            "subject_cap": SUBJECT_CAP,
            "authority": False,
            "g4_closed": False,
            "label": REAL_BOOTSTRAP_LABEL,
        }
