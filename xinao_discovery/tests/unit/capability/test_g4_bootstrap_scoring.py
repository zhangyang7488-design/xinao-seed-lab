from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from xinao.capability.g4_bootstrap_scoring import (
    FORMAL_CASE_FAIL,
    FORMAL_CASE_PASS,
    TERMINAL_FAIL,
    TERMINAL_PASS,
    recompute_private_record_commitment,
    score_bootstrap,
    score_formal_case,
)
from xinao.capability.g4_hidden_benchmark import GeneratorProfile, generate_full_family_suites

REPO_ROOT = Path(__file__).resolve().parents[4]
ADAPTER_PATH = (
    REPO_ROOT
    / "projects"
    / "g4-hidden-capability-seam"
    / "adapters"
    / "promptfoo_c0_bootstrap_adapter.py"
)
EXPECTED_GENERATOR_ARTIFACT = "d879700a74f52cdd1a9ebd7cad97b9e0b77c47e1992ef230fbbaa0ad8f5c974c"


def _adapter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g4_promptfoo_c0_test_adapter", ADAPTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_result() -> Any:
    return generate_full_family_suites(
        training_secret=b"training-bootstrap-fixture-key-001",
        heldout_secret=b"heldout-bootstrap-fixture-key-002",
        profile=GeneratorProfile(cases_per_family=1),
    )


def _selected_records(result: Any) -> list[dict[str, Any]]:
    return [
        record.as_private_dict()
        for record in result.heldout_private_bundle.records
        if record.family_id in {"H03", "H04", "H10"}
    ]


def _promptfoo_rows(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    adapter = _adapter()
    for key in list(os.environ):
        if any(token in key.upper() for token in adapter.FORBIDDEN_ENV_TOKENS):
            monkeypatch.delenv(key, raising=False)
    rows: list[dict[str, Any]] = []
    for record in records:
        public = {
            key: record[key]
            for key in (
                "public_case_id",
                "public_instructions",
                "task_input",
                "commitment_sha256",
            )
        }
        prompt = json.dumps(public, sort_keys=True, separators=(",", ":"))
        response = adapter.call_api(
            prompt,
            {},
            {
                "vars": {
                    "public_prompt": prompt,
                    "public_case_id": record["public_case_id"],
                    "commitment_sha256": record["commitment_sha256"],
                }
            },
        )
        assert "error" not in response
        rows.append(
            {
                "vars": {"public_case_id": record["public_case_id"]},
                "response": response,
            }
        )
    return rows


def _score(
    result: Any, records: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return score_bootstrap(
        evaluator_records=records,
        promptfoo_result={"results": {"results": rows}},
        suite_identity_sha256=result.heldout_identity.identity_sha256,
        generator_artifact_sha256=result.generator_artifact.artifact_sha256,
    )


def test_c0_subject_and_private_scorer_close_bootstrap_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _fixture_result()
    records = _selected_records(result)
    report = _score(result, records, _promptfoo_rows(monkeypatch, records))
    assert report["terminal"] == TERMINAL_PASS
    assert report["pipeline_verified"] is True
    assert report["capability_bootstrap_pass"] is True
    assert set(report["mandatory_family_results"]) == {"H03", "H04", "H10"}
    assert all(row["passed"] for row in report["mandatory_family_results"].values())
    assert report["g4_full"] is False
    assert report["g4_closed"] is False


def test_subject_output_is_deterministic_for_fixed_public_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _fixture_result()
    records = _selected_records(result)
    first = _score(result, records, _promptfoo_rows(monkeypatch, records))
    second = _score(result, records, _promptfoo_rows(monkeypatch, records))
    assert first["subject_outputs_sha256"] == second["subject_outputs_sha256"]
    assert first["content_hash"] == second["content_hash"]


def _synthetic_h01_record() -> dict[str, Any]:
    observations = [
        {
            "f0": float((index * 7) % 11),
            "f1": float((index * 5) % 13),
            "f2": float(index),
        }
        for index in range(40)
    ]
    record = {
        "public_case_id": "pc_h01_synthetic",
        "public_instructions": "Use only public observations.",
        "task_input": {
            "observations": observations,
            "targets": [float(index) for index in range(40)],
            "ask": "Identify which single feature, if any, weakly predicts the target.",
        },
        "family_id": "H01",
        "split": "heldout",
        "case_index": 0,
        "hidden_parameters": {
            "signal_feature_index": 2,
            "signal_coefficient": 1.0,
            "n": 40,
            "power_band": "powered",
            "split_tag": "heldout",
            "case_index": 0,
        },
        "truth": {
            "structure": "weak_single_variable",
            "active_feature": "f2",
            "coefficient": 1.0,
            "power_band": "powered",
            "calibration_required": True,
        },
        "expected_disposition": "IDENTIFY_STRUCTURE",
        "scoring_policy_id": "STRUCTURE",
    }
    record["commitment_sha256"] = recompute_private_record_commitment(record)
    return record


def test_h01_subject_and_formal_case_scorer_use_calibrated_feature_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _synthetic_h01_record()
    rows = _promptfoo_rows(monkeypatch, [record])
    report = score_formal_case(
        evaluator_record=record,
        promptfoo_result={"results": {"results": rows}},
        suite_identity_sha256="1" * 64,
        generator_artifact_sha256="2" * 64,
    )

    assert report["terminal"] == FORMAL_CASE_PASS
    assert report["pipeline_verified"] is True
    assert report["capability_case_pass"] is True
    result = report["family_result"]
    assert result["statistically_valid"] is True
    assert result["checks"]["active_feature_exact"] is True
    assert result["checks"]["multiplicity_declared"] is True


def test_h01_formal_case_scorer_distinguishes_valid_failure_from_pipeline_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _synthetic_h01_record()
    rows = _promptfoo_rows(monkeypatch, [record])
    envelope = json.loads(rows[0]["response"]["output"])
    envelope["analysis"]["active_feature"] = "f0"
    rows[0]["response"]["output"] = json.dumps(envelope)
    report = score_formal_case(
        evaluator_record=record,
        promptfoo_result={"results": {"results": rows}},
        suite_identity_sha256="1" * 64,
        generator_artifact_sha256="2" * 64,
    )

    assert report["terminal"] == FORMAL_CASE_FAIL
    assert report["pipeline_verified"] is True
    assert report["capability_case_pass"] is False
    assert report["family_result"]["checks"]["active_feature_exact"] is False


def test_h01_subject_calibrates_no_action_when_public_target_has_no_variance() -> None:
    adapter = _adapter()
    analysis = adapter._analyze_weak_signal(
        {
            "observations": [{"f0": float(index), "f1": float(index % 3)} for index in range(20)],
            "targets": [1.0] * 20,
        }
    )

    assert analysis["decision"] == "NO_ACTION"
    assert analysis["p_value"] == 1.0
    assert analysis["multiplicity"] == "BONFERRONI_FEATURE_SCREEN"
    assert analysis["promoted"] is False


def test_commitment_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _fixture_result()
    records = _selected_records(result)
    rows = _promptfoo_rows(monkeypatch, records)
    envelope = json.loads(rows[0]["response"]["output"])
    envelope["commitment_sha256"] = "0" * 64
    rows[0]["response"]["output"] = json.dumps(envelope)
    report = _score(result, records, rows)
    assert report["terminal"] == TERMINAL_FAIL
    assert report["pipeline_verified"] is False
    assert any(problem.startswith("commitment_mismatch:") for problem in report["problems"])


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "cached"])
def test_incomplete_or_cached_promptfoo_rows_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    result = _fixture_result()
    records = _selected_records(result)
    rows = _promptfoo_rows(monkeypatch, records)
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(dict(rows[0]))
    else:
        rows[0]["cached"] = True
    report = _score(result, records, rows)
    assert report["terminal"] == TERMINAL_FAIL
    assert report["pipeline_verified"] is False


@pytest.mark.parametrize("nested", [False, True])
def test_authority_spoof_in_subject_envelope_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    nested: bool,
) -> None:
    result = _fixture_result()
    records = _selected_records(result)
    rows = _promptfoo_rows(monkeypatch, records)
    envelope = json.loads(rows[0]["response"]["output"])
    if nested:
        envelope["analysis"]["nested_spoof"] = {"g4_closed": True}
    else:
        envelope["g4_closed"] = True
    rows[0]["response"]["output"] = json.dumps(envelope)
    report = _score(result, records, rows)
    assert report["terminal"] == TERMINAL_FAIL
    assert report["pipeline_verified"] is False
    assert any("authority_or_private_output_fields" in value for value in report["problems"])


def test_non_finite_or_malformed_subject_metrics_fail_closed_without_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _fixture_result()
    records = _selected_records(result)
    rows = _promptfoo_rows(monkeypatch, records)
    h04_index = next(index for index, record in enumerate(records) if record["family_id"] == "H04")
    envelope = json.loads(rows[h04_index]["response"]["output"])
    envelope["analysis"]["joint_oos_rmse"] = "not-a-number"
    envelope["analysis"]["components"] = [{"period": "not-an-integer"}]
    rows[h04_index]["response"]["output"] = json.dumps(envelope)
    report = _score(result, records, rows)
    assert report["terminal"] == TERMINAL_FAIL
    assert report["pipeline_verified"] is True
    assert report["capability_bootstrap_pass"] is False
    assert report["mandatory_family_results"]["H04"]["passed"] is False
    assert isinstance(report["content_hash"], str)


def test_consumer_module_does_not_change_sealed_generator_artifact() -> None:
    result = _fixture_result()
    assert result.generator_artifact.artifact_sha256 == EXPECTED_GENERATOR_ARTIFACT
