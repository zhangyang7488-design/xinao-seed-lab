"""Deterministic, fail-closed G5 statistical-validity consumers.

This package is a capability surface, not an admission authority.  It keeps
statistical protocols distinct and reports HOLD until the real G4 result and all
G5 evidence are present and final.
"""

from __future__ import annotations

from .adjudication import (
    TERMINAL_HOLD,
    TERMINAL_READY,
    adjudicate_g5,
    build_family_definition,
    build_power_evidence,
    build_trial_ledger_evidence,
    evaluate_operational_replications,
    evaluate_power_and_ess,
    required_effective_n,
    validate_statistical_independence_evidence,
)
from .error_control import ErrorControlError, evaluate_error_control
from .holdout import HoldoutExposureError, HoldoutExposureLedger
from .null_runner import (
    NullRunnerError,
    run_public_null_smoke,
    validate_full_pipeline_null_report,
)

__all__ = [
    "TERMINAL_HOLD",
    "TERMINAL_READY",
    "ErrorControlError",
    "HoldoutExposureError",
    "HoldoutExposureLedger",
    "NullRunnerError",
    "adjudicate_g5",
    "build_family_definition",
    "build_power_evidence",
    "build_trial_ledger_evidence",
    "evaluate_error_control",
    "evaluate_operational_replications",
    "evaluate_power_and_ess",
    "required_effective_n",
    "run_public_null_smoke",
    "validate_full_pipeline_null_report",
    "validate_statistical_independence_evidence",
]
