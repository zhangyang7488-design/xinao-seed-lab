"""Single-home provisional interface for GlobalTrialLedger / PowerPlan / ESS.

AF-005: exactly one logical object identity across G3 and G5 drafts.
Not authoritative; no durable state; no G6; completion_claim_allowed=false.
"""

from __future__ import annotations

from xinao.single_home.ess_report import build_ess_report, validate_ess_report
from xinao.single_home.global_trial_ledger import (
    LOGICAL_OBJECT_ID,
    TERMINAL_STATUSES,
    GlobalTrialLedger,
)
from xinao.single_home.power_plan import build_power_plan, validate_power_plan

__all__ = [
    "LOGICAL_OBJECT_ID",
    "TERMINAL_STATUSES",
    "GlobalTrialLedger",
    "build_ess_report",
    "build_power_plan",
    "validate_ess_report",
    "validate_power_plan",
]
