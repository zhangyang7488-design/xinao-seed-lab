"""ResearchErrorBudgetPolicy is a REUSE facet, not a second ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xinao.single_home.errors import DualHomeDenyError
from xinao.single_home.facets import (
    RESEARCH_ERROR_BUDGET_POLICY_REF,
    RESEARCH_QUESTION_REF,
    ResearchErrorBudgetFacetRef,
    assert_not_ledger,
    claim_as_global_trial_ledger,
)

ROOT = Path(__file__).resolve().parent / "fixtures"


def test_facet_ref_flags() -> None:
    assert ResearchErrorBudgetFacetRef.IS_LEDGER is False
    assert ResearchErrorBudgetFacetRef.IS_GLOBAL_TRIAL_LEDGER is False
    assert RESEARCH_ERROR_BUDGET_POLICY_REF["is_global_trial_ledger"] is False
    assert RESEARCH_ERROR_BUDGET_POLICY_REF["is_second_ledger"] is False
    assert RESEARCH_ERROR_BUDGET_POLICY_REF["disposition"] == "REUSE_FACET_ONLY"


def test_assert_not_ledger_passes_for_facets() -> None:
    assert_not_ledger("ResearchErrorBudgetPolicy")
    assert_not_ledger("HoldoutExposureLedger")
    assert_not_ledger("StatisticalValidityReport")
    assert_not_ledger("ResearchQuestion")


def test_assert_not_ledger_fails_for_global_trial_ledger() -> None:
    with pytest.raises(DualHomeDenyError) as ei:
        assert_not_ledger("GlobalTrialLedger")
    assert ei.value.code == "IS_LEDGER"


def test_research_question_distinct_in_interface_json() -> None:
    data = json.loads((ROOT / "single_home_interface.v1.json").read_text(encoding="utf-8"))
    assert data["distinct_f4"]["ResearchQuestion"]["disposition"] == "KEEP_DISTINCT"
    assert RESEARCH_QUESTION_REF["g3_may_rewrite"] is False


def test_ownership_table_marks_budget_not_ledger() -> None:
    data = json.loads((ROOT / "ownership_table.g3_vs_g5.v1.json").read_text(encoding="utf-8"))
    row = next(r for r in data["rows"] if r["object"] == "ResearchErrorBudgetPolicy")
    assert row["is_ledger"] is False
    assert row["wave1_disposition"] == "REUSE_FACET_NOT_SECOND_LEDGER"


def test_claiming_family_budget_as_ledger_denied() -> None:
    with pytest.raises(DualHomeDenyError) as ei:
        claim_as_global_trial_ledger("FamilyErrorBudgetLedger")
    assert ei.value.code == "FACET_IS_NOT_LEDGER"
