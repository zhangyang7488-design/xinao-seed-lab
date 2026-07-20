"""Reusable facets that are NOT ledgers (AF-005).

ResearchErrorBudgetPolicy is a foundation REUSE facet only.
F4 ResearchQuestion remains distinct. Neither is GlobalTrialLedger.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from xinao.single_home.errors import DualHomeDenyError
from xinao.single_home.provisional_versions import NOT_LEDGER_IDENTITIES

# Cite-only identity of the foundation facet (no runtime import of main tree required).
RESEARCH_ERROR_BUDGET_POLICY_REF: Final[Mapping[str, object]] = {
    "object_name": "ResearchErrorBudgetPolicy",
    "owner_module": "xinao.foundation.research_factory",
    "schema_version": "xinao.research_error_budget_policy.v1",
    "policy_ref": "research-error-budget.foundation.v1",
    "disposition": "REUSE_FACET_ONLY",
    "is_global_trial_ledger": False,
    "is_second_ledger": False,
    "catalog_identity": "NOT_O34",
}

RESEARCH_QUESTION_REF: Final[Mapping[str, object]] = {
    "object_name": "ResearchQuestion",
    "owner_module": "xinao.foundation.research_factory",
    "schema": "xinao.research_candidate_question.v1",
    "disposition": "KEEP_DISTINCT",
    "is_global_trial_ledger": False,
    "g3_may_rewrite": False,
}

MARKET_LAB_TRIAL_LEDGER_REF: Final[Mapping[str, object]] = {
    "object_name": "write_research_trial_ledger",
    "owner_module": "xinao_market_lab.research",
    "disposition": "REJECT_AS_O34_IDENTITY",
    "is_global_trial_ledger": False,
}


class ResearchErrorBudgetFacetRef:
    """Pointer to foundation budget facet — never a ledger class."""

    OBJECT_NAME = "ResearchErrorBudgetPolicy"
    IS_LEDGER = False
    IS_GLOBAL_TRIAL_LEDGER = False
    REF = RESEARCH_ERROR_BUDGET_POLICY_REF


def assert_not_ledger(name: str) -> None:
    """Pass when name is a known non-ledger facet/report; fail if it is the ledger."""

    if name == "GlobalTrialLedger":
        raise DualHomeDenyError(
            "IS_LEDGER",
            "GlobalTrialLedger is the single ledger identity, not a facet",
        )
    if name in NOT_LEDGER_IDENTITIES:
        return
    raise DualHomeDenyError(
        "UNKNOWN_IDENTITY",
        f"unknown identity for facet-vs-ledger check: {name!r}",
    )


def claim_as_global_trial_ledger(name: str) -> None:
    """Negative surface: claiming non-ledger identities as O34 always DENY."""

    if name == "GlobalTrialLedger":
        return
    if name == "write_research_trial_ledger":
        raise DualHomeDenyError(
            "MARKET_LAB_NOT_O34",
            "market-lab trial ledger is not O34 GlobalTrialLedger identity",
        )
    if name == "ResearchQuestion":
        raise DualHomeDenyError(
            "F4_RESEARCH_QUESTION_KEEP_DISTINCT",
            "F4 ResearchQuestion remains distinct; not a ledger and not G3 rewrite target",
        )
    if name in NOT_LEDGER_IDENTITIES:
        raise DualHomeDenyError(
            "FACET_IS_NOT_LEDGER",
            f"{name} is a reusable facet/report, not GlobalTrialLedger",
        )
    raise DualHomeDenyError(
        "UNKNOWN_LEDGER_CLAIM",
        f"unknown identity claim as GlobalTrialLedger: {name!r}",
    )
