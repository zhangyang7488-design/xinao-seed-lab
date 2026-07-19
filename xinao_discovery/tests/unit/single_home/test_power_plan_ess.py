"""PowerPlan / ESS single-home validator tests including hard negatives."""

from __future__ import annotations

import pytest

from xinao.canonical import canonical_sha256
from xinao.single_home.errors import SingleHomeError
from xinao.single_home.ess_report import build_ess_report, validate_ess_report
from xinao.single_home.hashing import content_sha256
from xinao.single_home.power_plan import (
    build_power_plan,
    compute_content_hash,
    is_statistically_adequate,
    validate_power_plan,
)
from xinao.single_home.provisional_versions import SCHEMA_VERSIONS


def test_build_and_validate_power_plan() -> None:
    plan = build_power_plan(
        plan_id="pp-1",
        family_id="H03",
        mde=0.05,
        target_power=0.8,
        max_budget_trials=100,
        holdout_split_binding="split-v1",
        serial_dependence_declared=True,
        status="ADEQUATE",
    )
    assert plan["schema_version"] == SCHEMA_VERSIONS["power_plan_version"]
    assert is_statistically_adequate(plan) is True
    assert validate_power_plan(plan)["plan_id"] == "pp-1"


def test_strong_model_substitute_forbidden() -> None:
    with pytest.raises(SingleHomeError) as ei:
        build_power_plan(
            plan_id="pp-1",
            family_id="H03",
            mde=0.05,
            target_power=0.8,
            max_budget_trials=10,
            holdout_split_binding="split-v1",
            serial_dependence_declared=False,
            status="ADEQUATE",
            strong_model_confidence_substitute=True,
        )
    assert ei.value.code == "STRONG_MODEL_SUBSTITUTE_FORBIDDEN"


def test_ess_binds_power_plan_and_serial() -> None:
    plan = build_power_plan(
        plan_id="pp-1",
        family_id="H03",
        mde=0.1,
        target_power=0.9,
        max_budget_trials=50,
        holdout_split_binding="split-v2",
        serial_dependence_declared=True,
        status="PLANNED",
    )
    ih = {"fixture": content_sha256({"n": 40})}
    report = build_ess_report(
        ess_report_id="ess-1",
        power_plan_ref=plan["plan_id"],
        power_plan_hash=compute_content_hash(plan),
        nominal_n=100,
        effective_n=40,
        serial_dependence_adjusted=True,
        input_hashes=ih,
    )
    assert validate_ess_report(report, power_plan=plan)["effective_n"] == 40


def test_ess_serial_dependence_ignored_denied() -> None:
    plan = build_power_plan(
        plan_id="pp-1",
        family_id="H03",
        mde=0.1,
        target_power=0.9,
        max_budget_trials=50,
        holdout_split_binding="split-v2",
        serial_dependence_declared=True,
        status="PLANNED",
    )
    ih = {"fixture": content_sha256({"n": 40})}
    report = build_ess_report(
        ess_report_id="ess-1",
        power_plan_ref=plan["plan_id"],
        power_plan_hash=compute_content_hash(plan),
        nominal_n=100,
        effective_n=40,
        serial_dependence_adjusted=False,
        input_hashes=ih,
    )
    with pytest.raises(SingleHomeError) as ei:
        validate_ess_report(report, power_plan=plan)
    assert ei.value.code == "SERIAL_DEPENDENCE_IGNORED"


def test_ess_gt_nominal_denied() -> None:
    with pytest.raises(SingleHomeError) as ei:
        build_ess_report(
            ess_report_id="ess-1",
            power_plan_ref="pp-1",
            power_plan_hash=content_sha256({"x": 1}),
            nominal_n=10,
            effective_n=20,
            serial_dependence_adjusted=False,
            input_hashes={"fixture": content_sha256({"n": 20})},
        )
    assert ei.value.code == "ESS_GT_NOMINAL"


def test_content_sha256_reuses_rfc8785_canonical() -> None:
    """Hard negative close: single_home hashing must equal canonical_sha256."""

    payload = {"z": 1, "a": 0.0, "nested": {"k": [1, "甲"]}}
    assert content_sha256(payload) == canonical_sha256(payload)
    # 0.0 / -0.0 and 1 / 1.0 collapse under RFC8785 (json.dumps diverged).
    assert content_sha256(0.0) == content_sha256(-0.0) == canonical_sha256(0.0)
    assert content_sha256(1) == content_sha256(1.0) == canonical_sha256(1.0)
    assert content_sha256({"x": 1.0}) == content_sha256({"x": 1})
    assert content_sha256({"x": 0.0}) == content_sha256({"x": -0.0})


def test_bool_mde_and_budget_denied() -> None:
    with pytest.raises(SingleHomeError) as ei:
        build_power_plan(
            plan_id="pp-1",
            family_id="H03",
            mde=True,
            target_power=0.8,
            max_budget_trials=10,
            holdout_split_binding="split-v1",
            serial_dependence_declared=False,
            status="PLANNED",
        )
    assert ei.value.code == "BAD_MDE"

    with pytest.raises(SingleHomeError) as ei2:
        build_power_plan(
            plan_id="pp-1",
            family_id="H03",
            mde=0.05,
            target_power=0.8,
            max_budget_trials=True,
            holdout_split_binding="split-v1",
            serial_dependence_declared=False,
            status="PLANNED",
        )
    assert ei2.value.code == "BAD_BUDGET"


def test_bool_ess_nominal_effective_denied() -> None:
    with pytest.raises(SingleHomeError) as ei:
        build_ess_report(
            ess_report_id="ess-1",
            power_plan_ref="pp-1",
            power_plan_hash=content_sha256({"x": 1}),
            nominal_n=True,
            effective_n=True,
            serial_dependence_adjusted=False,
            input_hashes={"fixture": content_sha256({"n": 1})},
        )
    assert ei.value.code in {"BAD_NOMINAL_N", "BAD_ESS"}


def test_ess_wrong_power_plan_ref_denied_even_with_matching_hash() -> None:
    plan = build_power_plan(
        plan_id="pp-real",
        family_id="H03",
        mde=0.1,
        target_power=0.9,
        max_budget_trials=50,
        holdout_split_binding="split-v2",
        serial_dependence_declared=False,
        status="PLANNED",
    )
    ih = {"fixture": content_sha256({"n": 40})}
    report = build_ess_report(
        ess_report_id="ess-1",
        power_plan_ref="WRONG_REF",
        power_plan_hash=compute_content_hash(plan),
        nominal_n=100,
        effective_n=40,
        serial_dependence_adjusted=False,
        input_hashes=ih,
    )
    with pytest.raises(SingleHomeError) as ei:
        validate_ess_report(report, power_plan=plan)
    assert ei.value.code == "PLAN_REF_MISMATCH"


def test_tamper_content_hash_denied() -> None:
    plan = build_power_plan(
        plan_id="pp-1",
        family_id="H03",
        mde=0.05,
        target_power=0.8,
        max_budget_trials=10,
        holdout_split_binding="split-v1",
        serial_dependence_declared=False,
        status="PLANNED",
    )
    tampered = dict(plan)
    tampered["content_hash"] = "a" * 64
    with pytest.raises(SingleHomeError) as ei:
        validate_power_plan(tampered)
    assert ei.value.code == "TAMPER_HASH"

    report = build_ess_report(
        ess_report_id="ess-1",
        power_plan_ref=plan["plan_id"],
        power_plan_hash=compute_content_hash(plan),
        nominal_n=10,
        effective_n=5,
        serial_dependence_adjusted=False,
        input_hashes={"fixture": content_sha256({"n": 5})},
    )
    bad = dict(report)
    bad["content_hash"] = "b" * 64
    with pytest.raises(SingleHomeError) as ei2:
        validate_ess_report(bad)
    assert ei2.value.code == "TAMPER_HASH"


def test_replay_register_idempotent_and_conflict() -> None:
    """Replay same payload ok; different payload after success is conflict."""

    from xinao.single_home.global_trial_ledger import GlobalTrialLedger

    led = GlobalTrialLedger()
    payload = {"status": "REGISTERED", "family_id": "H03"}
    first = led.register("wk-replay", payload)
    second = led.register("wk-replay", payload)
    assert first["payload_hash"] == second["payload_hash"]
    with pytest.raises(SingleHomeError) as ei:
        led.register("wk-replay", {"status": "SUCCEEDED", "family_id": "H03"})
    assert ei.value.code == "IDEMPOTENCE_CONFLICT"
