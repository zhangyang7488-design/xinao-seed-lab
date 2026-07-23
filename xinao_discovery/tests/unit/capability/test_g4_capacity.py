from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from xinao.capability.g4_capacity import (
    TERMINAL_ROUTE_HOLD,
    TERMINAL_ROUTE_READY,
    adjudicate_capacity,
    build_subject_prompt,
    normalize_relay_measurement,
    select_size_stratified_cases,
    validate_public_case,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_retired_capacity_runner():
    script = REPO_ROOT / "scripts" / "run_g4_full_capacity_preflight.py"
    spec = importlib.util.spec_from_file_location("g4_capacity_preflight_tested", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(index: int, payload: str) -> dict[str, object]:
    return {
        "public_case_id": f"opaque-{index}",
        "public_instructions": "analyze observations",
        "task_input": {"observations": [payload]},
        "commitment_sha256": hashlib.sha256(f"case-{index}".encode()).hexdigest(),
    }


def _dispatch_meta(prompt_sha256: str, *, stratum: str) -> tuple[dict, dict]:
    meta = {
        "status": "ok",
        "http_status": 200,
        "model_invocation_observed": True,
        "selected_equals_observed": True,
        "model_identity_accepted": True,
        "prompt_sha256": prompt_sha256,
        "secret_material_recorded": False,
        "cannot_access_filesystem": True,
        "terminal_state": "completed",
        "duration_ms": {"low": 1000, "median": 1500, "high": 2000}[stratum],
        "provider_id": "provider",
        "transport_id": "direct-openai-compatible-relay",
        "selected_model": "model",
        "observed_model": "model",
        "api_style": "chat_completions",
        "provider_contract_sha256": "a" * 64,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "result_sha256": "b" * 64,
        "raw_response_sha256": "c" * 64,
    }
    dispatch = {"status": "ok", "workers": [{"ok": True}]}
    return dispatch, meta


def _measurement(stratum: str) -> dict:
    prompt_sha = hashlib.sha256(stratum.encode()).hexdigest()
    dispatch, meta = _dispatch_meta(prompt_sha, stratum=stratum)
    return normalize_relay_measurement(
        dispatch,
        meta,
        expected_prompt_sha256=prompt_sha,
        stratum=stratum,
        prompt_bytes=100,
        result_hash_readback=True,
        raw_hash_readback=True,
    )


def test_public_case_rejects_private_fields_recursively() -> None:
    case = _case(1, "small")
    case["task_input"] = {"nested": {"truth": "leak"}}
    result = validate_public_case(case)
    assert result["ok"] is False
    assert "forbidden:$.task_input.nested.truth" in result["problems"]


def test_three_size_strata_and_prompt_are_public_only() -> None:
    selected = select_size_stratified_cases(
        [_case(1, "x"), _case(2, "y" * 20), _case(3, "z" * 200), _case(4, "q" * 50)]
    )
    assert [row["stratum"] for row in selected] == ["low", "median", "high"]
    assert len({row["case"]["public_case_id"] for row in selected}) == 3
    prompt = build_subject_prompt(selected[0]["case"], subject_configuration="C2-FRONTIER")
    assert "hidden_parameters" not in prompt
    assert '"completion_claim_allowed":false' in prompt


def test_campaign_wide_provider_capacity_runner_is_a_no_effect_tombstone() -> None:
    runner = _load_retired_capacity_runner()

    assert runner.RETIREMENT_REASON == ("RETIRED_FULL_CAMPAIGN_PROVIDER_CAPACITY_PREFLIGHT")
    assert runner.REPLACEMENT == "scripts/run_g4_batch_execution_admission.py"
    assert runner.main(["--dispatch", "--launcher", "legacy-provider"]) == 2


def test_relay_measurement_fails_wrong_model_and_zero_usage() -> None:
    prompt_sha = "d" * 64
    dispatch, meta = _dispatch_meta(prompt_sha, stratum="low")
    meta["selected_equals_observed"] = False
    meta["usage"]["total_tokens"] = 0
    result = normalize_relay_measurement(
        dispatch,
        meta,
        expected_prompt_sha256=prompt_sha,
        stratum="low",
        prompt_bytes=10,
        result_hash_readback=True,
        raw_hash_readback=True,
    )
    assert result["ok"] is False
    assert "model_exact" in result["problems"]
    assert "positive_usage" in result["problems"]


def test_relay_measurement_requires_prompt_and_route_contract_evidence() -> None:
    prompt_sha = "d" * 64
    dispatch, meta = _dispatch_meta(prompt_sha, stratum="low")
    meta.pop("prompt_sha256")
    meta.pop("provider_contract_sha256")
    meta.pop("cannot_access_filesystem")
    result = normalize_relay_measurement(
        dispatch,
        meta,
        expected_prompt_sha256=prompt_sha,
        stratum="low",
        prompt_bytes=10,
        result_hash_readback=True,
        raw_hash_readback=True,
    )
    assert result["ok"] is False
    assert "prompt_hash_recorded" in result["problems"]
    assert "prompt_hash_exact" in result["problems"]
    assert "route_contract_pinned" in result["problems"]
    assert "filesystem_boundary_recorded" in result["problems"]


def test_percentage_only_quota_does_not_block_bounded_family_route() -> None:
    report = adjudicate_capacity(
        measurements=[_measurement("low"), _measurement("median"), _measurement("high")],
        quota_snapshot={"codex": {"remainingPercent": 59}},
        planned_batch_cells=3,
    )
    assert report["terminal"] == TERMINAL_ROUTE_READY
    assert report["route_evidence_ready_for_current_batch"] is True
    assert report["current_batch_execution_ready"] is True
    assert report["capacity_scope"] == "current_batch_only"
    assert report["campaign_provider_locked"] is False
    assert report["api_quota_is_campaign_gate"] is False
    assert report["absolute_capacity_available"] is False
    assert report["single_shot_capacity_required"] is False
    assert "QUOTA_TELEMETRY_PERCENTAGE_ONLY_ADVISORY" in report["advisories"]
    assert "QUOTA_TELEMETRY_PERCENTAGE_ONLY_ADVISORY" not in report["reasons"]
    assert report["authority_freeze_allowed"] is False
    assert report["global_wait_allowed"] is False
    assert report["hidden_outcome_access"] is False
    assert report["g4_closed"] is False
    assert report["execution_directives"] == {
        "g4_engineering": "EXECUTE",
        "g4_batch_runner": "EXECUTE",
        "g5_design": "EXECUTE",
        "g5_preregistration": "EXECUTE",
        "g5_final_claim": "OPEN",
        "g6_formal_research": "DENY",
        "parent_global_wait_allowed": False,
    }
    assert report["phase_control_state"]["actionable_frontier"] == [
        "g4_engineering_allowed",
        "g4_batch_execution_allowed",
        "g5_design_allowed",
        "g5_preregistration_allowed",
    ]
    assert "G5 设计=执行" in report["human_status_cn"]


def test_invalid_route_reasons_describe_failed_evidence() -> None:
    prompt_sha = "d" * 64
    dispatch, meta = _dispatch_meta(prompt_sha, stratum="low")
    meta.pop("prompt_sha256")
    meta.pop("provider_contract_sha256")
    meta.pop("cannot_access_filesystem")
    invalid = normalize_relay_measurement(
        dispatch,
        meta,
        expected_prompt_sha256=prompt_sha,
        stratum="low",
        prompt_bytes=10,
        result_hash_readback=True,
        raw_hash_readback=True,
    )
    report = adjudicate_capacity(
        measurements=[invalid, _measurement("median"), _measurement("high")],
        quota_snapshot={"codex": {"remainingPercent": 59}},
        planned_batch_cells=3,
    )
    assert "ROUTE_MEASUREMENT_PROMPT_HASH_NOT_RECORDED" in report["reasons"]
    assert "ROUTE_MEASUREMENT_PROMPT_HASH_NOT_EXACT" in report["reasons"]
    assert "ROUTE_MEASUREMENT_ROUTE_CONTRACT_NOT_PINNED" in report["reasons"]
    assert "ROUTE_MEASUREMENT_FILESYSTEM_BOUNDARY_NOT_RECORDED" in report["reasons"]
    assert "ROUTE_MEASUREMENT_PROMPT_HASH_RECORDED" not in report["reasons"]
    assert report["execution_directives"]["g4_engineering"] == "EXECUTE"
    assert report["execution_directives"]["g4_batch_runner"] == "HOLD_LOCAL_PREREQUISITE"
    assert report["execution_directives"]["g5_design"] == "EXECUTE"
    assert report["global_wait_allowed"] is False


def test_absolute_capacity_is_scoped_to_current_batch_planning() -> None:
    measurements = [_measurement("low"), _measurement("median"), _measurement("high")]
    report = adjudicate_capacity(
        measurements=measurements,
        quota_snapshot={
            "hard_available_tokens": 1_000_000,
            "hard_max_calls": 100_000,
            "hard_wall_clock_ms": 100_000_000,
        },
        planned_batch_cells=100,
        hard_bounds={
            "available_tokens": 1_000_000,
            "max_calls": 100_000,
            "wall_clock_ms": 100_000_000,
            "source": "owner-pinned-test-bound",
        },
    )
    assert report["terminal"] == TERMINAL_ROUTE_READY
    assert report["route_evidence_ready_for_current_batch"] is True
    assert report["current_batch_execution_ready"] is True
    assert report["absolute_capacity_available"] is True
    assert report["current_batch_capacity_observed_sufficient"] is True
    assert report["authority_freeze_allowed"] is False
    assert report["global_wait_allowed"] is False
    assert report["g4_full"] is False


def test_invalid_planned_batch_cells_rejected() -> None:
    with pytest.raises(ValueError, match="planned_batch_cells"):
        adjudicate_capacity(measurements=[], quota_snapshot={}, planned_batch_cells=0)


def test_zero_measurements_fail_closed_to_hold_instead_of_raising() -> None:
    report = adjudicate_capacity(
        measurements=[],
        quota_snapshot={"codex": {"remainingPercent": 59}},
        planned_batch_cells=3,
    )
    assert report["terminal"] == TERMINAL_ROUTE_HOLD
    assert "THREE_SIZE_STRATA_NOT_MEASURED" in report["reasons"]
    assert "ROUTE_MEASUREMENT_INVALID" not in report["reasons"]
    assert report["measured_max_tokens_per_call"] is None


def test_small_absolute_bound_holds_only_the_current_batch() -> None:
    report = adjudicate_capacity(
        measurements=[_measurement("low"), _measurement("median"), _measurement("high")],
        quota_snapshot={
            "hard_available_tokens": 1,
            "hard_max_calls": 1,
            "hard_wall_clock_ms": 1,
        },
        planned_batch_cells=100,
        hard_bounds={
            "available_tokens": 1,
            "max_calls": 1,
            "wall_clock_ms": 1,
            "source": "small-observed-bound",
        },
    )
    assert report["terminal"] == TERMINAL_ROUTE_HOLD
    assert report["route_evidence_ready_for_current_batch"] is True
    assert report["current_batch_execution_ready"] is False
    assert report["current_batch_capacity_observed_sufficient"] is False
    assert (
        "OBSERVED_TOKEN_CAPACITY_BELOW_CURRENT_BATCH_ESTIMATE" in report["batch_scheduling_holds"]
    )
    assert "OBSERVED_CALL_CAPACITY_BELOW_CURRENT_BATCH_ESTIMATE" in report["batch_scheduling_holds"]
    assert "OBSERVED_WALL_BOUND_BELOW_CURRENT_BATCH_ESTIMATE" in report["batch_scheduling_holds"]
    assert report["reasons"] == []
    assert report["family_power_plan_required"] is True
    assert report["full_report_requires_complete_campaign"] is True
    assert report["execution_directives"]["g4_engineering"] == "EXECUTE"
    assert report["execution_directives"]["g4_batch_runner"] == "HOLD_LOCAL_PREREQUISITE"
    assert report["execution_directives"]["g5_design"] == "EXECUTE"
    assert report["execution_directives"]["g5_preregistration"] == "EXECUTE"
    assert report["global_wait_allowed"] is False
