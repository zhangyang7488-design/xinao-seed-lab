"""Thin adapters for source-family mature-carrier candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceCandidateBinding:
    binding_id: str
    source_url: str
    source_claim_card_id: str
    mature_carrier: str
    first_ref_sha: str
    adapter_kind: str = "source_family_smoked_candidate_reference"

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "source_url": self.source_url,
            "source_claim_card_id": self.source_claim_card_id,
            "mature_carrier": self.mature_carrier,
            "first_ref_sha": self.first_ref_sha,
            "adapter_kind": self.adapter_kind,
            "thin_bind_adapter": "xinao_seedlab.adapters.source_candidate.SourceCandidateAdapter",
            "invoke": {
                "python": (
                    "from xinao_seedlab.adapters.source_candidate import SourceCandidateAdapter"
                ),
                "method": "SourceCandidateAdapter.bind_smoked_candidate",
            },
            "promotion_allowed": False,
            "promotion_gate": "adapter_value_eval_before_default_capability",
            "not_execution_controller": True,
        }


class SourceCandidateAdapter:
    """Normalizes a passed adapter-smoke result into a bounded binding."""

    @staticmethod
    def bind_smoked_candidate(smoke_result: dict[str, Any]) -> dict[str, Any]:
        validation = (
            smoke_result.get("validation")
            if isinstance(smoke_result.get("validation"), dict)
            else {}
        )
        probe = smoke_result.get("probe") if isinstance(smoke_result.get("probe"), dict) else {}
        git_probe = (
            probe.get("git_ls_remote") if isinstance(probe.get("git_ls_remote"), dict) else {}
        )
        first_ref_sha = str(git_probe.get("first_ref_sha") or "")
        binding = SourceCandidateBinding(
            binding_id=str(smoke_result.get("binding_id") or ""),
            source_url=str(smoke_result.get("source_url") or ""),
            source_claim_card_id=str(smoke_result.get("source_claim_card_id") or ""),
            mature_carrier=str(smoke_result.get("mature_carrier") or ""),
            first_ref_sha=first_ref_sha,
        )
        checks = {
            "smoke_result_passed": validation.get("passed") is True,
            "source_url_present": bool(binding.source_url),
            "source_claim_card_present": bool(binding.source_claim_card_id),
            "first_ref_sha_present": bool(binding.first_ref_sha),
            "not_promoted_by_adapter": True,
        }
        payload = {
            "schema_version": "xinao.seedcortex.source_candidate_binding.v1",
            "status": "source_candidate_binding_ready"
            if all(checks.values())
            else "source_candidate_binding_blocked",
            "binding": binding.to_dict(),
            "source_smoke_result": {
                "queue_id": smoke_result.get("queue_id"),
                "binding_id": smoke_result.get("binding_id"),
                "source_url": smoke_result.get("source_url"),
                "probe_mode": probe.get("probe_mode"),
                "live_network_invoked": probe.get("live_network_invoked"),
            },
            "validation": {"passed": all(checks.values()), "checks": checks},
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
        }
        return payload
