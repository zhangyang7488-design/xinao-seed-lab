from __future__ import annotations

import copy

import pytest

from xinao.capability.phase_conditions import (
    PhaseConditionError,
    PhaseConditionType,
    build_phase_control_state,
    condition_value,
    execution_directives,
    human_summary_cn,
    legacy_claim_projection,
    validate_phase_control_state,
)

GENERATION = "a" * 64


def _construction_state(**overrides: bool | None) -> dict:
    values: dict[str, bool | None] = {
        "g4_engineering_allowed": True,
        "g4_batch_execution_allowed": True,
        "g4_full_evidence_complete": False,
        "g5_design_allowed": True,
        "g5_preregistration_allowed": True,
        "g5_final_adjudication_complete": False,
        "g6_formal_research_allowed": False,
    }
    values.update(overrides)
    return build_phase_control_state(
        observed_generation=GENERATION,
        **values,
    )


def test_open_final_claims_do_not_freeze_constructible_work() -> None:
    state = _construction_state()
    directives = execution_directives(state)
    legacy = legacy_claim_projection(state)

    assert directives == {
        "g4_engineering": "EXECUTE",
        "g4_batch_runner": "EXECUTE",
        "g5_design": "EXECUTE",
        "g5_preregistration": "EXECUTE",
        "g5_final_claim": "OPEN",
        "g6_formal_research": "DENY",
        "parent_global_wait_allowed": False,
    }
    assert legacy == {
        "g4_full": False,
        "g4_closed": False,
        "g5_closed": False,
        "formal_research_allowed": False,
    }
    assert state["actionable_frontier"] == [
        "g4_engineering_allowed",
        "g4_batch_execution_allowed",
        "g5_design_allowed",
        "g5_preregistration_allowed",
    ]
    assert state["open_final_claims"] == [
        "g4_full_evidence_complete",
        "g5_final_adjudication_complete",
    ]
    assert state["global_wait_authority"] is False
    assert state["authority"] is False
    assert state["completion_claim_allowed"] is False
    assert state["parent_wait_claim_allowed"] is False
    assert [item["scope"] for item in state["conditions"]] == [
        "g4_engineering",
        "g4_batch",
        "g4_final_claim",
        "g5_design",
        "g5_preregistration",
        "g5_final_claim",
        "g6_formal_research",
    ]


def test_batch_hold_is_local_and_does_not_freeze_engineering_or_g5() -> None:
    state = _construction_state(g4_batch_execution_allowed=False)
    directives = execution_directives(state)

    assert directives["g4_engineering"] == "EXECUTE"
    assert directives["g4_batch_runner"] == "HOLD_LOCAL_PREREQUISITE"
    assert directives["g5_design"] == "EXECUTE"
    assert directives["g5_preregistration"] == "EXECUTE"
    assert directives["parent_global_wait_allowed"] is False
    assert condition_value(state, PhaseConditionType.G4_FULL_EVIDENCE_COMPLETE) is False


def test_final_admission_has_explicit_cross_phase_invariants() -> None:
    with pytest.raises(
        PhaseConditionError,
        match="final G5 adjudication requires complete G4 evidence",
    ):
        _construction_state(g5_final_adjudication_complete=True)

    with pytest.raises(
        PhaseConditionError,
        match="formal G6 admission requires complete G4 and G5 claims",
    ):
        _construction_state(g6_formal_research_allowed=True)

    final = _construction_state(
        g4_full_evidence_complete=True,
        g5_final_adjudication_complete=True,
        g6_formal_research_allowed=True,
    )
    assert execution_directives(final)["g6_formal_research"] == "ALLOW"


def test_typed_conditions_are_exact_hash_bound_and_tamper_evident() -> None:
    state = _construction_state()
    assert validate_phase_control_state(state) == state

    tampered = copy.deepcopy(state)
    tampered["conditions"][0]["message"] = "final false means stop everything"
    with pytest.raises(PhaseConditionError, match="message is not canonical"):
        validate_phase_control_state(tampered)

    duplicate = copy.deepcopy(state)
    duplicate["conditions"][1]["type"] = duplicate["conditions"][0]["type"]
    with pytest.raises(PhaseConditionError, match="condition types must be unique"):
        validate_phase_control_state(duplicate)


def test_human_summary_preserves_decision_meaning_in_chinese() -> None:
    summary = human_summary_cn(_construction_state(g4_batch_execution_allowed=False))

    assert "G4 工程=执行" in summary
    assert "G4 当前批次=仅局部前置未满足" in summary
    assert "G5 设计=执行" in summary
    assert "G5 最终裁决=未完成" in summary
    assert "G6 正式研究=禁止" in summary
    assert "不授权父级全局等待" in summary
