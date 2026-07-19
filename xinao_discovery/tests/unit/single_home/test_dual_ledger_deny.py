"""Negative tests: dual class import DENY and exact HOME_MODULE identity."""

from __future__ import annotations

import pytest

from xinao.single_home.dual_home_deny import (
    GOVERNED_LEDGER_HOME_MODULE,
    assert_single_home_import_set,
    deny_dual_ledger_classes,
    deny_dual_power_plan_homes,
    deny_forbidden_import_paths,
)
from xinao.single_home.errors import DualHomeDenyError
from xinao.single_home.facets import claim_as_global_trial_ledger
from xinao.single_home.global_trial_ledger import GlobalTrialLedger


def test_single_home_class_accepted() -> None:
    deny_dual_ledger_classes([GlobalTrialLedger])


def test_dual_distinct_classes_denied() -> None:
    class OtherLedger:
        LOGICAL_OBJECT_ID = "xinao.global_trial_ledger.v1"
        HOME_MODULE = "drafts.xinao.g3.global_trial_ledger"

    with pytest.raises(DualHomeDenyError) as ei:
        deny_dual_ledger_classes([GlobalTrialLedger, OtherLedger])
    assert ei.value.code == "DUAL_LEDGER_CLASS_FORBIDDEN"


def test_wrong_logical_id_denied() -> None:
    class Fake:
        LOGICAL_OBJECT_ID = "xinao.some_other_ledger.v1"
        HOME_MODULE = "xinao.single_home.global_trial_ledger"

    with pytest.raises(DualHomeDenyError) as ei:
        deny_dual_ledger_classes([Fake])
    assert ei.value.code == "DUAL_LEDGER_CLASS_FORBIDDEN"


def test_forbidden_parallel_home_modules_denied() -> None:
    with pytest.raises(DualHomeDenyError) as ei:
        deny_forbidden_import_paths(
            [
                "xinao.single_home.global_trial_ledger",
                "drafts.xinao.gates.g5_global_trial_ledger",
            ]
        )
    assert ei.value.code == "FORBIDDEN_PARALLEL_HOME"


def test_dual_wave1_ledger_imports_denied() -> None:
    with pytest.raises(DualHomeDenyError) as ei:
        assert_single_home_import_set(
            [
                "drafts.xinao.g3.global_trial_ledger",
                "drafts.xinao.gates.g5_global_trial_ledger",
            ]
        )
    assert ei.value.code in {
        "DUAL_LEDGER_CLASS_FORBIDDEN",
        "FORBIDDEN_PARALLEL_HOME",
    }


def test_dual_power_plan_homes_denied() -> None:
    with pytest.raises(DualHomeDenyError) as ei:
        deny_dual_power_plan_homes(
            [
                "drafts.xinao.g3.power_plan_version",
                "drafts.xinao.gates.g5_power_plan",
            ]
        )
    assert ei.value.code in {
        "DUAL_LEDGER_CLASS_FORBIDDEN",
        "FORBIDDEN_PARALLEL_HOME",
    }


def test_single_home_import_set_ok() -> None:
    assert_single_home_import_set(
        [
            "xinao.single_home.global_trial_ledger",
            "xinao.single_home.power_plan",
            "xinao.single_home.ess_report",
        ]
    )


def test_market_lab_not_o34() -> None:
    with pytest.raises(DualHomeDenyError) as ei:
        claim_as_global_trial_ledger("write_research_trial_ledger")
    assert ei.value.code == "MARKET_LAB_NOT_O34"


def test_research_error_budget_not_second_ledger() -> None:
    with pytest.raises(DualHomeDenyError) as ei:
        claim_as_global_trial_ledger("ResearchErrorBudgetPolicy")
    assert ei.value.code == "FACET_IS_NOT_LEDGER"


def test_research_question_keep_distinct() -> None:
    with pytest.raises(DualHomeDenyError) as ei:
        claim_as_global_trial_ledger("ResearchQuestion")
    assert ei.value.code == "F4_RESEARCH_QUESTION_KEEP_DISTINCT"


def test_arbitrary_evil_home_module_denied() -> None:
    """Hard negative: deny_dual_ledger_classes must not accept arbitrary HOME_MODULE."""

    class Evil:
        LOGICAL_OBJECT_ID = "xinao.global_trial_ledger.v1"
        HOME_MODULE = "evil.module.totally_wrong"

    with pytest.raises(DualHomeDenyError) as ei:
        deny_dual_ledger_classes([Evil])
    assert ei.value.code == "BAD_HOME_MODULE"
    assert GOVERNED_LEDGER_HOME_MODULE in str(ei.value)
