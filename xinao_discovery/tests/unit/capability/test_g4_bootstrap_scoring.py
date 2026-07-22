from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from xinao.capability.g4_bootstrap_scoring import TERMINAL_FAIL, TERMINAL_PASS, score_bootstrap
from xinao.capability.g4_hidden_benchmark import GeneratorProfile, generate_full_family_suites

REPO_ROOT = Path(__file__).resolve().parents[4]
ADAPTER_PATH = (
    REPO_ROOT
    / "projects"
    / "g4-hidden-capability-seam"
    / "adapters"
    / "promptfoo_c0_bootstrap_adapter.py"
)
EXPECTED_GENERATOR_ARTIFACT = "9a1f577d1199734813e1055d49283b7c02018d98b8d01c41334de9a0bcbf5fc4"


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
