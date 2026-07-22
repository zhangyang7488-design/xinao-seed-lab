"""Independent evaluator: separate process/state root; isolation interface checks only.

Does not score real hidden outcomes. Synthetic isolation verification only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import SYNTHETIC_LABEL
from .canonical import canonical_json_sha256, write_json
from .objects import validate_object
from .security_model import scan_forbidden_public_payload
from .vault import EVALUATOR_CAP, SUBJECT_CAP, SealedTruthVault


class IndependentEvaluator:
    def __init__(self, *, state_root: str | Path, vault: SealedTruthVault) -> None:
        self.state_root = Path(state_root).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.vault = vault
        self.results_path = self.state_root / "evaluator_results.v1.jsonl"

    def code_identity(self) -> str:
        # Stable synthetic code identity for bundle binding
        return canonical_json_sha256(
            {
                "module": "g4_hidden_capability_seam.evaluator",
                "role": "independent_evaluator",
                "synthetic_isolation_check_only": True,
            }
        )

    def verify_isolation_interface(
        self,
        *,
        run_envelope: dict[str, Any],
        public_manifest: dict[str, Any],
        promptfoo_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []

        envelope_validation = validate_object(run_envelope, "ImmutableRunEnvelope")
        findings.append(
            {
                "id": "immutable_run_envelope_identity_valid",
                "ok": envelope_validation.get("ok") is True,
                "reason": envelope_validation.get("reason"),
            }
        )

        # 1) envelope terminal cannot be pass on abort/timeout
        term = str(run_envelope.get("terminal_status") or "")
        if term in {"timeout", "killed", "aborted", "provider_error", "scorer_error"}:
            if run_envelope.get("promoted_to_pass"):
                findings.append({"id": "timeout_kill_promoted_to_pass", "ok": False})
            else:
                findings.append({"id": "timeout_kill_fail_closed", "ok": True})

        # 2) public surfaces free of vault/truth
        for name, payload in (
            ("manifest", public_manifest),
            ("envelope", run_envelope),
            ("promptfoo_config", promptfoo_config or {}),
        ):
            leaks = scan_forbidden_public_payload(payload)
            critical = [
                p
                for p in leaks
                if any(
                    x in p.lower()
                    for x in (
                        "vault_locator",
                        "seed",
                        ".truth",
                        "answer",
                        "family_identity",
                        "scorer_feature",
                        "scorer_credential",
                        "rejection_label",
                    )
                )
            ]
            findings.append(
                {
                    "id": f"public_surface_clean:{name}",
                    "ok": len(critical) == 0,
                    "leaks": critical,
                }
            )

        # 3) subject cannot read vault
        for case in public_manifest.get("public_cases", []):
            cid = case["public_case_id"]
            subj = self.vault.subject_read(capability=SUBJECT_CAP, public_case_id=cid)
            findings.append(
                {
                    "id": f"subject_vault_denied:{cid}",
                    "ok": subj.get("ok") is False
                    and subj.get("reason") == "subject_vault_read_denied",
                }
            )
            # evaluator can view synthetic truth
            ev = self.vault.evaluator_view(capability=EVALUATOR_CAP, public_case_id=cid)
            findings.append(
                {
                    "id": f"evaluator_vault_ok:{cid}",
                    "ok": ev.get("ok") is True and ev.get("synthetic") is True,
                }
            )
            # commitment match
            if ev.get("ok"):
                cm = self.vault.verify_commitment(cid, case["commitment_sha256"])
                findings.append({"id": f"commitment_match:{cid}", "ok": cm.get("ok") is True})

        # 4) scoring disabled / hidden not consumed
        findings.append(
            {
                "id": "scoring_disabled",
                "ok": public_manifest.get("scoring_enabled") is False
                and run_envelope.get("scoring_enabled") is False,
            }
        )
        findings.append(
            {
                "id": "hidden_not_consumed",
                "ok": public_manifest.get("hidden_cases_consumed") is False
                and run_envelope.get("hidden_cases_consumed") is False,
            }
        )

        # 5) synthetic claims only
        findings.append(
            {
                "id": "not_real_h01_h14_claim",
                "ok": run_envelope.get("not_capability_result") is not False
                and public_manifest.get("not_admission") is True,
            }
        )

        # 6) authority flags remain false
        findings.append(
            {
                "id": "authority_flags_false",
                "ok": run_envelope.get("authority") is False
                and run_envelope.get("g4_closed") is False
                and run_envelope.get("g5_active") is False,
            }
        )

        all_ok = all(f.get("ok") for f in findings)
        result = {
            "schema_version": "xinao.g4.hidden_capability_seam.evaluator_isolation_result.v1",
            "ok": all_ok,
            "findings": findings,
            "state_root": str(self.state_root),
            "evaluator_code_identity_sha256": self.code_identity(),
            "synthetic_only": True,
            "label": SYNTHETIC_LABEL,
            "real_scoring": False,
            "not_admission": True,
            "authority": False,
            "g4_closed": False,
            "g5_active": False,
        }
        with self.results_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            fh.write("\n")
        write_json(self.state_root / "latest_isolation_result.v1.json", result)
        return result

    def reject_error_truth_leak(self, error_payload: dict[str, Any]) -> dict[str, Any]:
        leaks = scan_forbidden_public_payload(error_payload)
        critical = [
            p
            for p in leaks
            if any(
                x in p.lower()
                for x in ("truth", "answer", "seed", "vault", "family_identity", "scorer_")
            )
        ]
        return {
            "ok": False if critical else True,
            "allowed": len(critical) == 0,
            "reason": "provider_scorer_error_truth_leak" if critical else None,
            "leaks": critical,
        }

    def reject_authority_spoof(self, claim: dict[str, Any]) -> dict[str, Any]:
        bad_keys = (
            "g4_closed",
            "g5_active",
            "authority_applied",
            "final_report_pass",
            "admission",
            "parent_complete",
            "preregistration_frozen_as_authority",
        )
        spoof = []
        for k in bad_keys:
            if claim.get(k) is True:
                spoof.append(k)
        if str(claim.get("terminal_state") or "").upper() in {
            "G4_CLOSED",
            "G5_ACTIVE",
            "ADMISSION_PASS",
            "FOUNDATION_COMPLETE",
            "CAPABILITY_PASS",
        }:
            spoof.append("terminal_state")
        return {
            "ok": len(spoof) == 0,
            "allowed": len(spoof) == 0,
            "reason": "authority_g4_g5_final_report_write_spoof" if spoof else None,
            "spoof": spoof,
        }
