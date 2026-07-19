"""Identity pin tests for the single-home interface."""

from __future__ import annotations

import json
from pathlib import Path

from xinao.single_home.ess_report import HOME_MODULE as ESS_HOME_MODULE
from xinao.single_home.global_trial_ledger import (
    LOGICAL_OBJECT_ID,
    GlobalTrialLedger,
)
from xinao.single_home.power_plan import HOME_MODULE as POWER_PLAN_HOME_MODULE
from xinao.single_home.power_plan import LOGICAL_OBJECT_ID as PP_ID
from xinao.single_home.provisional_versions import (
    LOGICAL_OBJECT_IDS,
    SCHEMA_VERSIONS,
    STAGE_GATE,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_logical_object_id_is_stable() -> None:
    assert LOGICAL_OBJECT_ID == "xinao.global_trial_ledger.v1"
    assert LOGICAL_OBJECT_IDS["GlobalTrialLedger"] == GlobalTrialLedger.LOGICAL_OBJECT_ID
    assert LOGICAL_OBJECT_IDS["PowerPlanVersion"] == PP_ID


def test_export_schema_pin_shares_g5_path() -> None:
    led = GlobalTrialLedger()
    led.register("wk-1", {"status": "REGISTERED", "equivalence_cluster_id": "c1"})
    exp = led.export_disclosure()
    assert exp["schema_version"] == SCHEMA_VERSIONS["global_trial_ledger_export"]
    assert exp["schema_version"] == "xinao.gates.g5.global_trial_ledger_export.provisional.v1"
    assert exp["logical_object_id"] == LOGICAL_OBJECT_ID
    assert exp["authoritative"] is False
    assert exp["not_market_lab_ledger"] is True
    assert exp["no_durable_state"] is True
    assert exp["stage_gate"] == STAGE_GATE
    assert "PKG-CODE-G3-LOOP-CONTRACTS" in exp["coordinates_with_packages"]
    assert "PKG-CODE-G5-ADM-PURE-CORE" in exp["coordinates_with_packages"]


def test_home_module_constant() -> None:
    assert GlobalTrialLedger.HOME_MODULE == "xinao.single_home.global_trial_ledger"


def test_fixture_import_contract_matches_executable_single_home() -> None:
    interface = json.loads((FIXTURES / "single_home_interface.v1.json").read_text(encoding="utf-8"))
    assert interface["import_contract"]["allowed_single_home_root"] == "xinao.single_home"
    assert interface["logical_objects"]["GlobalTrialLedger"]["single_home_module"] == (
        GlobalTrialLedger.HOME_MODULE
    )
    assert interface["logical_objects"]["PowerPlanVersion"]["single_home_module"] == (
        POWER_PLAN_HOME_MODULE
    )
    assert interface["logical_objects"]["EffectiveSampleSizeReport"]["single_home_module"] == (
        ESS_HOME_MODULE
    )

    ownership = json.loads(
        (FIXTURES / "ownership_table.g3_vs_g5.v1.json").read_text(encoding="utf-8")
    )
    homes = {row["object"]: row["single_home"] for row in ownership["rows"]}
    assert homes["GlobalTrialLedger"] == f"{GlobalTrialLedger.HOME_MODULE}.GlobalTrialLedger"
    assert homes["PowerPlanVersion"] == POWER_PLAN_HOME_MODULE
    assert homes["EffectiveSampleSizeReport"] == ESS_HOME_MODULE
