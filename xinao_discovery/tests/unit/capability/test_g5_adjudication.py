from __future__ import annotations

import copy
import math

import pytest

from xinao.canonical import canonical_sha256
from xinao.capability.g5_statistical_validity import (
    TERMINAL_HOLD,
    HoldoutExposureLedger,
    adjudicate_g5,
    build_family_definition,
    build_power_evidence,
    build_trial_ledger_evidence,
    evaluate_operational_replications,
    evaluate_power_and_ess,
    required_effective_n,
)
from xinao.capability.g5_statistical_validity.adjudication import G5AdjudicationError
from xinao.capability.phase_conditions import build_phase_control_state
from xinao.single_home.ess_report import build_ess_report
from xinao.single_home.global_trial_ledger import GlobalTrialLedger
from xinao.single_home.hashing import content_sha256
from xinao.single_home.power_plan import build_power_plan, compute_content_hash


def _sealed(value: dict) -> dict:
    result = dict(value)
    result["content_hash"] = canonical_sha256(result)
    return result


def _g4_route_ready_without_full_results() -> dict:
    return _sealed(
        {
            "schema_version": "xinao.g4.bounded_family_route_advisory.v2",
            "terminal": "G4_BOUNDED_FAMILY_ROUTE_READY_NO_OUTCOME_ACCESS",
            "g4_full": False,
            "g4_closed": False,
            "authority": False,
            "phase_control_state": build_phase_control_state(
                observed_generation="a" * 64,
                g4_engineering_allowed=True,
                g4_batch_execution_allowed=True,
                g4_full_evidence_complete=False,
                g5_design_allowed=True,
                g5_preregistration_allowed=True,
                g5_final_adjudication_complete=False,
                g6_formal_research_allowed=False,
            ),
        }
    )


def test_g5_treats_tampered_upstream_phase_as_hold_not_exception() -> None:
    g4 = _g4_route_ready_without_full_results()
    tampered = copy.deepcopy(g4)
    tampered["phase_control_state"]["conditions"][0]["message"] = "stop everything"
    tampered["content_hash"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "content_hash"}
    )

    report = adjudicate_g5(g4_report=tampered)

    assert report["terminal"] == TERMINAL_HOLD
    assert report["g5_statistical_validity_ready"] is False
    assert report["checks"]["g4_phase_control_valid"] is False
    assert any(reason.startswith("G4_PHASE_CONTROL_INVALID:") for reason in report["reasons"])
    assert report["execution_directives"]["g4_batch_runner"] == "UNKNOWN"
    assert report["execution_directives"]["g5_design"] == "EXECUTE"
    assert report["execution_directives"]["parent_global_wait_allowed"] is False


def _power_pair() -> tuple[dict, dict]:
    plan = build_power_plan(
        plan_id="plan-1",
        family_id="family-1",
        mde=0.5,
        target_power=0.8,
        max_budget_trials=100,
        holdout_split_binding="split-frozen-v1",
        serial_dependence_declared=False,
        status="ADEQUATE",
    )
    ess = build_ess_report(
        ess_report_id="ess-1",
        power_plan_ref=plan["plan_id"],
        power_plan_hash=compute_content_hash(plan),
        nominal_n=100,
        effective_n=50,
        serial_dependence_adjusted=False,
        input_hashes={"snapshot": content_sha256({"n": 100})},
    )
    return plan, ess


def test_power_requirement_and_achieved_power_are_recomputed() -> None:
    plan, ess = _power_pair()
    evidence = build_power_evidence(
        power_plan=plan,
        ess_report=ess,
        alpha=0.05,
        sidedness="TWO_SIDED",
    )
    assert evidence["required_effective_n"] == required_effective_n(
        standardized_mde=0.5,
        alpha=0.05,
        target_power=0.8,
        sidedness="TWO_SIDED",
    )
    result = evaluate_power_and_ess(
        power_plan=plan,
        ess_report=ess,
        power_evidence=evidence,
    )
    assert result["passed"] is True
    assert result["achieved_power"] >= result["target_power"]
    assert result["input_schemas_final"] is False


def test_power_receipt_tampering_is_denied() -> None:
    plan, ess = _power_pair()
    evidence = build_power_evidence(
        power_plan=plan,
        ess_report=ess,
        alpha=0.05,
        sidedness="TWO_SIDED",
    )
    tampered = dict(evidence)
    tampered["achieved_power"] = 0.99
    tampered["content_hash"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "content_hash"}
    )
    with pytest.raises(G5AdjudicationError, match="achieved_power does not recompute"):
        evaluate_power_and_ess(
            power_plan=plan,
            ess_report=ess,
            power_evidence=tampered,
        )


def test_operational_identity_diversity_is_not_statistical_independence() -> None:
    report = evaluate_operational_replications(
        [
            {
                "replication_id": "r1",
                "dataset_snapshot_sha256": "1" * 64,
                "split_sha256": "2" * 64,
                "seed_sha256": "3" * 64,
                "model_identity": "model-a",
                "verifier_id": "verifier-a",
                "evidence_sha256": "4" * 64,
            },
            {
                "replication_id": "r2",
                "dataset_snapshot_sha256": "5" * 64,
                "split_sha256": "6" * 64,
                "seed_sha256": "7" * 64,
                "model_identity": "model-b",
                "verifier_id": "verifier-b",
                "evidence_sha256": "8" * 64,
            },
        ]
    )
    assert report["operational_diversity_sufficient"] is True
    assert report["statistical_independence_proved"] is False


def test_trial_ledger_wrapper_checks_terminal_coverage_without_pinning_draft_schema() -> None:
    ledger = GlobalTrialLedger()
    ledger.register("wk-1", {"status": "REGISTERED", "family_id": "family-1"})
    incomplete = build_trial_ledger_evidence(ledger, observed_work_keys=["wk-1"])
    assert incomplete["all_registered_trials_terminal"] is False
    assert incomplete["source_schema_final"] is False
    ledger.append_terminal("wk-1", "NO_ACTION", family_id="family-1")
    complete = build_trial_ledger_evidence(ledger, observed_work_keys=["wk-1"])
    assert complete["all_registered_trials_terminal"] is True
    assert complete["source_schema_final"] is False


def test_trial_ledger_requires_exact_observed_set_and_one_terminal() -> None:
    ledger = GlobalTrialLedger()
    ledger.register("wk-1", {"status": "REGISTERED"})
    ledger.append_terminal("wk-1", "NO_ACTION")
    ledger.register("wk-2", {"status": "REGISTERED"})
    ledger.append_terminal("wk-2", "FAILED")
    partial = build_trial_ledger_evidence(ledger, observed_work_keys=["wk-1"])
    assert partial["observed_work_keys_exact"] is False
    assert partial["silent_unregistered_trials"] == 1
    ledger.append_terminal("wk-1", "SUCCEEDED")
    duplicate = build_trial_ledger_evidence(ledger, observed_work_keys=["wk-1", "wk-2"])
    assert duplicate["exactly_one_terminal_per_trial"] is False
    assert duplicate["all_registered_trials_terminal"] is False


def test_route_ready_without_full_g4_results_keeps_g5_and_g6_closed() -> None:
    report = adjudicate_g5(g4_report=_g4_route_ready_without_full_results())
    assert report["terminal"] == TERMINAL_HOLD
    assert report["g5_closed"] is False
    assert report["g6_closed"] is False
    assert report["g4_closed"] is False
    assert report["foundation_closed"] is False
    assert report["formal_admission"] is False
    assert report["parent_complete"] is False
    assert "G4_FULL_CLOSED" in report["reasons"]
    assert report["mature_protocol_boundaries"]["public_null_smoke_is_g5_evidence"] is False
    assert report["execution_directives"]["g4_batch_runner"] == "EXECUTE"
    assert report["execution_directives"]["g5_design"] == "EXECUTE"
    assert report["execution_directives"]["g5_preregistration"] == "EXECUTE"
    assert report["execution_directives"]["g5_final_claim"] == "OPEN"
    assert report["execution_directives"]["g6_formal_research"] == "DENY"
    assert report["execution_directives"]["parent_global_wait_allowed"] is False
    assert "不等于冻结全部 G5 工作" in report["phase_control_state"]["conditions"][5]["message"]


def test_malformed_error_receipt_fails_to_hold_instead_of_crashing() -> None:
    malformed = _sealed(
        {
            "schema_version": "xinao.g5.error_control_receipt.v1",
            "regime": "ONLINE_FDR_LOND",
            "passed": True,
            "generic_alpha_or_e_balance": False,
        }
    )
    report = adjudicate_g5(
        g4_report=_g4_route_ready_without_full_results(),
        error_control_receipt=malformed,
    )
    assert report["terminal"] == TERMINAL_HOLD
    assert report["checks"]["error_control_passed"] is False
    assert any(reason.startswith("ERROR_CONTROL_INVALID:") for reason in report["reasons"])


def test_provisional_power_and_trial_schema_cannot_be_laundered_by_other_green_checks() -> None:
    plan, ess = _power_pair()
    power_evidence = build_power_evidence(
        power_plan=plan,
        ess_report=ess,
        alpha=0.05,
        sidedness="TWO_SIDED",
    )
    ledger = GlobalTrialLedger()
    ledger.register("wk-1", {"status": "REGISTERED", "family_id": "family-1"})
    ledger.append_terminal("wk-1", "NO_ACTION", family_id="family-1")
    trial = build_trial_ledger_evidence(ledger, observed_work_keys=["wk-1"])
    family = build_family_definition(
        family_id="family-1",
        hypothesis_order=["h1"],
        definition={"scope": "test"},
        selection_rule="frozen-before-outcome",
    )
    holdout_ledger = HoldoutExposureLedger(
        ledger_id="holdout-1",
        split_binding="split-frozen-v1",
        preregistration_sha256="9" * 64,
        max_accesses=0,
    )
    report = adjudicate_g5(
        g4_report=_g4_route_ready_without_full_results(),
        power_plan=plan,
        ess_report=ess,
        power_evidence=power_evidence,
        trial_ledger_disclosure=trial,
        family_definition=family,
        holdout_snapshot=holdout_ledger.snapshot(),
    )
    assert report["g5_closed"] is False
    assert report["checks"]["power_ess_passed"] is True
    assert report["checks"]["power_ess_schemas_final"] is False
    assert report["checks"]["trial_ledger_complete"] is True
    assert report["checks"]["trial_ledger_schema_final"] is False


def test_required_effective_n_rejects_invalid_sidedness() -> None:
    with pytest.raises(G5AdjudicationError, match="sidedness"):
        required_effective_n(
            standardized_mde=0.5,
            alpha=0.05,
            target_power=0.8,
            sidedness="MAYBE",
        )


def test_g4_report_content_hash_is_enforced() -> None:
    report = _g4_route_ready_without_full_results()
    report["g4_closed"] = True
    with pytest.raises(G5AdjudicationError, match="content_hash mismatch"):
        adjudicate_g5(g4_report=report)


def test_power_evidence_uses_finite_math() -> None:
    result = required_effective_n(
        standardized_mde=0.5,
        alpha=0.05,
        target_power=0.8,
        sidedness="TWO_SIDED",
    )
    assert isinstance(result, int) and result > 0 and math.isfinite(result)
