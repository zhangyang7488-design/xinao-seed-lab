"""Negative tests: silent field drift DENY."""

from __future__ import annotations

import pytest

from xinao.single_home.errors import FieldDriftDenyError
from xinao.single_home.field_contracts import (
    assert_export_fields,
    assert_fields_match_contract,
    compare_field_sets,
)
from xinao.single_home.global_trial_ledger import GlobalTrialLedger
from xinao.single_home.provisional_versions import (
    ENTRY_REQUIRED_FIELDS,
    EXPORT_REQUIRED_FIELDS,
    POWER_PLAN_REQUIRED_FIELDS,
)


def test_export_matches_frozen_contract() -> None:
    led = GlobalTrialLedger()
    led.register("wk-1", {"status": "REGISTERED"})
    exp = led.export_disclosure()
    assert set(exp.keys()) == set(EXPORT_REQUIRED_FIELDS)


def test_silent_export_field_removal_denied() -> None:
    led = GlobalTrialLedger()
    led.register("wk-1", {"status": "REGISTERED"})
    exp = led.export_disclosure()
    drifted = dict(exp)
    del drifted["logical_object_id"]
    with pytest.raises(FieldDriftDenyError) as ei:
        assert_export_fields(drifted)
    assert ei.value.code == "SILENT_FIELD_DRIFT_FORBIDDEN"


def test_silent_export_extra_required_set_denied() -> None:
    led = GlobalTrialLedger()
    led.register("wk-1", {"status": "REGISTERED"})
    exp = led.export_disclosure()
    drifted = dict(exp)
    drifted["secret_second_truth_field"] = True
    with pytest.raises(FieldDriftDenyError) as ei:
        assert_export_fields(drifted)
    assert ei.value.code == "SILENT_FIELD_DRIFT_FORBIDDEN"


def test_g3_vs_g5_entry_field_sets_must_match_single_home() -> None:
    # Historical wave1 both used the same core entry keys; freeze equals single-home.
    g3_entry = {
        "seq",
        "work_key",
        "status",
        "family_id",
        "equivalence_cluster_id",
        "path_kind",
        "failure_reason",
        "payload_hash",
        "meta",
        "immutable",
    }
    g5_entry = set(g3_entry)
    compare_field_sets(
        left_name="wave1.g3.entry",
        left=g3_entry,
        right_name="wave1.g5.entry",
        right=g5_entry,
    )
    compare_field_sets(
        left_name="wave1.entry",
        left=g3_entry,
        right_name="single_home.entry",
        right=ENTRY_REQUIRED_FIELDS,
    )


def test_g3_vs_g5_power_plan_field_sets_must_match() -> None:
    g3_pp = set(POWER_PLAN_REQUIRED_FIELDS)
    g5_pp = set(POWER_PLAN_REQUIRED_FIELDS)
    compare_field_sets(
        left_name="wave1.g3.power_plan",
        left=g3_pp,
        right_name="wave1.g5.power_plan",
        right=g5_pp,
    )


def test_field_set_mismatch_denied() -> None:
    with pytest.raises(FieldDriftDenyError) as ei:
        compare_field_sets(
            left_name="home_a",
            left={"a", "b"},
            right_name="home_b",
            right={"a", "c"},
        )
    assert ei.value.code == "SILENT_FIELD_DRIFT_FORBIDDEN"


def test_missing_power_plan_required_denied() -> None:
    with pytest.raises(FieldDriftDenyError) as ei:
        assert_fields_match_contract(
            object_name="PowerPlanVersion",
            observed=["schema_version", "plan_id"],
            required=POWER_PLAN_REQUIRED_FIELDS,
        )
    assert ei.value.code == "SILENT_FIELD_DRIFT_FORBIDDEN"
