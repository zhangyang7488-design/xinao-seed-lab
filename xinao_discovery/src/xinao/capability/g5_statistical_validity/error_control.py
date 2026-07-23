"""Procedure-specific online error-control verification.

Alpha spending and LOND are intentionally separate protocols.  E-processes are
not accepted through a generic numeric balance: a future e-process integration
must bring its own typed verifier and assumptions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from xinao.canonical import canonical_sha256

ALPHA_SPENDING = "SEQUENTIAL_FWER_ALPHA_SPENDING"
ONLINE_FDR_LOND = "ONLINE_FDR_LOND"
ALPHA_SPENDING_PROCEDURE = "SEQUENTIAL_BONFERRONI_ALPHA_SPENDING_V1"
LOND_PROCEDURE = "LOND_JAVANMARD_MONTANARI_V1"


class ErrorControlError(ValueError):
    """Invalid or unsupported error-control evidence."""


def _probability(name: str, value: Any, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ErrorControlError(f"{name} must be a finite number")
    parsed = float(value)
    lower_ok = parsed >= 0 if allow_zero else parsed > 0
    if not math.isfinite(parsed) or not lower_ok or parsed > 1:
        interval = "[0,1]" if allow_zero else "(0,1]"
        raise ErrorControlError(f"{name} must be in {interval}")
    return parsed


def _sha256(name: str, value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ErrorControlError(f"{name} must be 64 lowercase hex")
    return value


def _exact_hash(payload: Mapping[str, Any]) -> None:
    expected = canonical_sha256(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    if _sha256("content_hash", payload.get("content_hash")) != expected:
        raise ErrorControlError("content_hash mismatch")


def evaluate_error_control(
    protocol: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Recompute one supported sequential testing trace.

    ``allocation`` is the frozen alpha-spending schedule for sequential FWER and
    the beta schedule for LOND.  Its sum must not exceed ``family_alpha``.
    """

    data = dict(protocol)
    forbidden = {"alpha_or_e_budget", "e_budget", "mode"}.intersection(data)
    if forbidden:
        raise ErrorControlError(
            f"generic or ambiguous budget fields forbidden: {sorted(forbidden)}"
        )
    _exact_hash(data)

    regime = data.get("regime")
    procedure_id = data.get("procedure_id")
    assumption_class = data.get("assumption_class")
    if regime == ALPHA_SPENDING:
        if procedure_id != ALPHA_SPENDING_PROCEDURE:
            raise ErrorControlError("alpha-spending procedure_id is not the pinned implementation")
        if assumption_class != "ARBITRARY_DEPENDENCE":
            raise ErrorControlError(
                "sequential Bonferroni requires ARBITRARY_DEPENDENCE declaration"
            )
    elif regime == ONLINE_FDR_LOND:
        if procedure_id != LOND_PROCEDURE:
            raise ErrorControlError("LOND procedure_id is not the pinned implementation")
        if assumption_class not in {"INDEPENDENT_P_VALUES", "POSITIVE_DEPENDENCE_PRDS"}:
            raise ErrorControlError("LOND requires an explicit supported dependence assumption")
    else:
        raise ErrorControlError(
            "unsupported regime; DISABLED and generic e-process balances cannot pass"
        )

    family_alpha = _probability("family_alpha", data.get("family_alpha"))
    preregistration_sha256 = _sha256("preregistration_sha256", data.get("preregistration_sha256"))
    hypothesis_order = data.get("hypothesis_order")
    allocation = data.get("allocation")
    if not isinstance(hypothesis_order, list) or not hypothesis_order:
        raise ErrorControlError("hypothesis_order must be a non-empty frozen list")
    if any(not isinstance(item, str) or not item for item in hypothesis_order):
        raise ErrorControlError("hypothesis_order entries must be non-empty strings")
    if len(set(hypothesis_order)) != len(hypothesis_order):
        raise ErrorControlError("hypothesis_order must not contain duplicates")
    if not isinstance(allocation, list) or len(allocation) != len(hypothesis_order):
        raise ErrorControlError("allocation must align exactly with hypothesis_order")
    schedule = [
        _probability(f"allocation[{index}]", value) for index, value in enumerate(allocation)
    ]
    if math.fsum(schedule) > family_alpha + 1e-12:
        raise ErrorControlError("frozen allocation exceeds family_alpha")
    if len(observations) != len(hypothesis_order):
        raise ErrorControlError("observation count must equal the frozen hypothesis count")

    rejections_before = 0
    verified: list[dict[str, Any]] = []
    for index, (hypothesis_id, beta, raw) in enumerate(
        zip(hypothesis_order, schedule, observations, strict=True),
        start=1,
    ):
        observation = dict(raw)
        if observation.get("hypothesis_id") != hypothesis_id:
            raise ErrorControlError(f"observation {index} violates frozen hypothesis order")
        p_value = _probability(
            f"observations[{index}].p_value", observation.get("p_value"), allow_zero=True
        )
        threshold = beta if regime == ALPHA_SPENDING else beta * (rejections_before + 1)
        declared = _probability(
            f"observations[{index}].declared_threshold",
            observation.get("declared_threshold"),
        )
        if not math.isclose(declared, threshold, rel_tol=0.0, abs_tol=1e-12):
            raise ErrorControlError(f"observation {index} threshold does not recompute")
        rejected = p_value <= threshold
        if observation.get("rejected") is not rejected:
            raise ErrorControlError(f"observation {index} rejection decision does not recompute")
        verified.append(
            {
                "index": index,
                "hypothesis_id": hypothesis_id,
                "p_value": p_value,
                "threshold": threshold,
                "rejected": rejected,
                "rejections_before": rejections_before,
            }
        )
        rejections_before += int(rejected)

    report: dict[str, Any] = {
        "schema_version": "xinao.g5.error_control_receipt.v1",
        "regime": regime,
        "procedure_id": procedure_id,
        "assumption_class": assumption_class,
        "family_alpha": family_alpha,
        "preregistration_sha256": preregistration_sha256,
        "hypothesis_count": len(hypothesis_order),
        "rejection_count": rejections_before,
        "allocation_sum": math.fsum(schedule),
        "verified_observations": verified,
        "passed": True,
        "generic_alpha_or_e_balance": False,
        "e_process_supported_by_this_receipt": False,
        "authority": False,
        "completion_claim_allowed": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return report
