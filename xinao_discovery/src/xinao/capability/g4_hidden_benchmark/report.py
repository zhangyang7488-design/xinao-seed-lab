"""Terminal report helper for the generator package (non-authoritative HOLD)."""

from __future__ import annotations

from typing import Any

from .constants import NON_CLAIMS, TERMINAL_POSITIVE
from .generator import family_inventory
from .types import FullFamilyGeneratorResult
from .verification import verify_full_family_result


def terminal_ready_report(
    result: FullFamilyGeneratorResult,
) -> dict[str, Any]:
    """Return only the HOLD terminal meaning with all authority/completion flags false.

    This helper does not claim G4 closure, admission, scoring, provider use, or
    parent completion. It only reports that a real domain-core generator artifact
    is constructible in-process for custodian binding.
    """
    verification = verify_full_family_result(result)
    terminal = TERMINAL_POSITIVE if verification["ok"] else "BLOCKED"
    report: dict[str, Any] = {
        "terminal": terminal,
        "WORKER_TERMINAL": terminal,
        "family_inventory": list(family_inventory()),
        "family_count": len(family_inventory()),
        "verification": verification,
        **dict(NON_CLAIMS),
    }
    if verification["ok"]:
        report["training_identity_sha256"] = result.training_identity.identity_sha256
        report["heldout_identity_sha256"] = result.heldout_identity.identity_sha256
        report["generator_artifact_sha256"] = result.generator_artifact.artifact_sha256
        report["non_collision_attestation_sha256"] = (
            result.non_collision_attestation.attestation_sha256
        )
    return report
