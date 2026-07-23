"""Pre-outcome producer tests for the provider-neutral G4 batch seam."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from xinao.canonical import canonical_sha256
from xinao.capability.g4_preregistration import (
    REQUEST_SCHEMA,
    TERMINAL_HOLD,
    TERMINAL_READY,
    G4FamilyBatchError,
    build_split_manifest,
    prepare_g4_preregistration,
    validate_g4_preregistration_package,
)
from xinao.single_home.power_plan import build_power_plan

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "prepare_g4_batch_preregistration.py"
PREPARED_AT = "2026-07-23T14:00:00.000Z"


def _sha(character: str) -> str:
    return character * 64


def _request(*, power_status: str = "ADEQUATE") -> dict[str, object]:
    split = build_split_manifest(
        split_manifest_id="split-formal-fresh-001",
        suite_version="suite-formal-v1",
        boundaries={
            "training": {
                "case_count": 12,
                "suite_commitment_sha256": _sha("1"),
            },
            "heldout": {
                "case_count": 12,
                "suite_commitment_sha256": _sha("2"),
            },
        },
        purge_cases=2,
        embargo_cases=2,
        holdout_exposure_budget=6,
    )
    power_plans = {
        family: build_power_plan(
            plan_id=f"power-{family}-001",
            family_id=family,
            mde=0.1,
            target_power=0.9,
            max_budget_trials=12,
            holdout_split_binding=split["content_hash"],
            serial_dependence_declared=True,
            status=power_status,
        )
        for family in ("H03", "H04", "H10")
    }
    return {
        "schema_version": REQUEST_SCHEMA,
        "campaign_id": "g4-formal-campaign-001",
        "batch_id": "g4-formal-batch-001",
        "batch_sequence": 1,
        "work_key": "g4:formal-batch-001",
        "campaign_preregistration_ref": "D:/evidence/g4/campaign-preregistration.json",
        "campaign_preregistration_sha256": _sha("3"),
        "families": ["H03", "H04", "H10"],
        "subject_configurations": ["C0-ALGO"],
        "batch_cells": [
            {
                "family_id": family,
                "public_case_id": f"pc_{family.lower()}_001",
                "subject_configuration": "C0-ALGO",
                "seed_id": seed_id,
            }
            for family in ("H03", "H04", "H10")
            for seed_id in (17, 42)
        ],
        "split_manifest": split,
        "power_plans": power_plans,
        "frozen_bindings": {
            "suite_sha256": _sha("4"),
            "generator_sha256": _sha("5"),
            "evaluator_sha256": _sha("6"),
            "scoring_policy_sha256": _sha("7"),
            "subject_adapter_sha256": _sha("8"),
        },
        "unit_policy": {
            "unit_of_analysis": "INDEPENDENT_HELDOUT_CASE",
            "seed_role": "WITHIN_CASE_REPLICATION_NOT_INDEPENDENT_N",
            "fixed_seed_ids": [17, 42],
            "model_identity_policy": "PIN_EXACT_OBSERVED_IDENTITY",
        },
        "budget_policy": {
            "max_batch_executions": 6,
            "max_outcome_accesses": 6,
        },
        "stopping_policy": {
            "kind": "FIXED_BUDGET_NO_EARLY_SUCCESS",
            "allow_early_success_stop": False,
            "underpowered_terminal": "UNDERPOWERED",
        },
        "analysis_policy": {
            "primary_endpoint_policy_sha256": _sha("9"),
            "threshold_policy_sha256": _sha("a"),
            "contingency_policy_sha256": _sha("b"),
            "deviation_policy_sha256": _sha("c"),
            "power_analysis_policy_sha256_by_family": {
                "H03": _sha("d"),
                "H04": _sha("e"),
                "H10": _sha("f"),
            },
        },
        "campaign_contract_sha256": _sha("0"),
        "retry_policy_sha256": _sha("1"),
        "global_trial_ledger_ref": "D:/evidence/g4/global-trial-ledger.json",
        "global_trial_ledger_snapshot_sha256": _sha("2"),
        "declared_prior_outcome_receipts": [],
        "reused_outcome_evidence_ids": [],
    }


def _prepare(
    request: dict[str, object],
    **kwargs: object,
) -> dict[str, object]:
    return prepare_g4_preregistration(
        request,
        prepared_at_utc=PREPARED_AT,
        **kwargs,
    )


def test_ready_builds_preregistration_and_pending_obligations() -> None:
    result = _prepare(_request())

    assert result["terminal"] == TERMINAL_READY
    assert result["receipt"]["outcome_accessed"] is False
    assert result["preregistration"]["registered_before_outcome_access"] is True
    assert result["preregistration"]["g4_full"] is False
    assert result["batch_manifest"]["schema_version"] == "xinao.g4.experiment_batch.v1"
    assert (
        result["batch_manifest"]["preregistration_sha256"]
        == result["preregistration"]["content_hash"]
    )
    assert (
        result["batch_manifest"]["power_plan_sha256"]
        == result["preregistration"]["power_plan_set_sha256"]
    )
    assert (
        result["batch_manifest"]["stopping_rule_sha256"]
        == result["preregistration"]["stopping_rule_sha256"]
    )
    assert (
        result["batch_manifest"]["holdout_budget_sha256"]
        == result["preregistration"]["holdout_budget_sha256"]
    )
    assert result["batch_manifest"]["retry_policy_sha256"] == _sha("1")
    ledger = result["obligation_ledger"]
    assert ledger["planned_cells"] == 6
    assert ledger["completed_cells"] == 0
    assert ledger["remaining_cells"] == 6
    assert ledger["all_outcomes_unopened"] is True
    assert {row["family_id"] for row in ledger["obligations"]} == {"H03", "H04", "H10"}
    assert {row["subject_configuration"] for row in ledger["obligations"]} == {"C0-ALGO"}
    assert {row["seed_id"] for row in ledger["obligations"]} == {17, 42}
    assert all("repeat_index" not in row for row in ledger["obligations"])
    assert all(row["status"] == "PENDING" for row in ledger["obligations"])
    assert all(row["result_sha256"] is None for row in ledger["obligations"])
    assert result["batch_manifest"]["cell_ids"] == [
        row["obligation_id"] for row in ledger["obligations"]
    ]


@pytest.mark.parametrize("surface", ["obligation_ledger", "batch_manifest"])
def test_self_consistent_package_surface_tamper_is_rejected(surface: str) -> None:
    result = _prepare(_request())
    tampered = deepcopy(result[surface])
    if surface == "obligation_ledger":
        tampered["remaining_cells"] -= 1
    else:
        tampered["preregistration_sha256"] = _sha("f")
    body = {key: value for key, value in tampered.items() if key != "content_hash"}
    tampered["content_hash"] = canonical_sha256(body)

    with pytest.raises(
        G4FamilyBatchError,
        match="does not match",
    ):
        validate_g4_preregistration_package(
            request=result["request"],
            preregistration=result["preregistration"],
            obligation_ledger=(
                tampered if surface == "obligation_ledger" else result["obligation_ledger"]
            ),
            batch_manifest=(tampered if surface == "batch_manifest" else result["batch_manifest"]),
        )


def test_planned_power_is_hold_and_never_publishes_preregistration() -> None:
    result = _prepare(_request(power_status="PLANNED"))

    assert result["terminal"] == TERMINAL_HOLD
    assert result["receipt"]["problems"] == ["POWER_PLAN_NOT_ADEQUATE"]
    assert result["receipt"]["preregistration_included"] is False
    assert result["request"] is None
    assert result["preregistration"] is None
    assert result["obligation_ledger"] is None
    assert result["batch_manifest"] is None


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        (
            "declared_prior_outcome_receipts",
            ["event424-outcome"],
            "RETROSPECTIVE_OUTCOME_ACCESS_FORBIDDEN",
        ),
        (
            "reused_outcome_evidence_ids",
            ["event424-report"],
            "RETROSPECTIVE_EVIDENCE_REUSE_FORBIDDEN",
        ),
    ],
)
def test_retrospective_event424_adoption_is_hold(
    field: str,
    value: list[str],
    problem: str,
) -> None:
    request = _request()
    request[field] = value

    result = _prepare(request)

    assert result["terminal"] == TERMINAL_HOLD
    assert result["receipt"]["problems"] == [problem]
    assert result["receipt"]["outcome_accessed"] is False


def test_owner_known_outcome_receipt_forces_hold_even_if_request_claims_fresh() -> None:
    result = _prepare(
        _request(),
        known_prior_outcome_receipts=["event424-outcome"],
    )

    assert result["terminal"] == TERMINAL_HOLD
    assert result["receipt"]["problems"] == ["RETROSPECTIVE_OUTCOME_ACCESS_FORBIDDEN"]


def test_previously_exposed_suite_commitment_forces_hold() -> None:
    result = _prepare(
        _request(),
        forbidden_suite_commitments=[_sha("2")],
    )

    assert result["terminal"] == TERMINAL_HOLD
    assert result["receipt"]["problems"] == ["SUITE_COMMITMENT_REUSE"]


def test_seed_repetitions_cannot_be_declared_as_independent_observations() -> None:
    request = _request()
    request["unit_policy"]["seed_role"] = "INDEPENDENT_N"

    result = _prepare(request)

    assert result["terminal"] == TERMINAL_HOLD
    assert result["receipt"]["problems"] == ["BAD_SEED_ROLE"]


def test_each_case_configuration_requires_the_complete_fixed_seed_set() -> None:
    request = _request()
    request["batch_cells"] = [
        cell
        for cell in request["batch_cells"]
        if not (cell["family_id"] == "H03" and cell["seed_id"] == 42)
    ]

    result = _prepare(request)

    assert result["terminal"] == TERMINAL_HOLD
    assert result["receipt"]["problems"] == ["INCOMPLETE_WITHIN_CASE_SEEDS"]


def test_campaign_wide_10206_capacity_is_not_a_batch_gate() -> None:
    request = _request()
    request["budget_policy"] = {
        "max_batch_executions": 6,
        "max_outcome_accesses": 6,
    }

    result = _prepare(request)

    assert result["terminal"] == TERMINAL_READY
    assert result["obligation_ledger"]["planned_cells"] == 6


def test_power_plan_must_bind_exact_split_hash() -> None:
    request = _request()
    bad_plan = dict(request["power_plans"]["H03"])
    bad_plan["holdout_split_binding"] = "different-split"
    from xinao.single_home.power_plan import compute_content_hash

    bad_plan["content_hash"] = compute_content_hash(bad_plan)
    request["power_plans"]["H03"] = bad_plan

    result = _prepare(request)

    assert result["terminal"] == TERMINAL_HOLD
    assert result["receipt"]["problems"] == ["POWER_PLAN_SPLIT_MISMATCH"]


def test_split_commitments_must_be_unique() -> None:
    request = _request()
    split = deepcopy(request["split_manifest"])
    split["boundaries"]["heldout"]["suite_commitment_sha256"] = _sha("1")
    split["content_hash"] = "0" * 64
    request["split_manifest"] = split

    result = _prepare(request)

    assert result["terminal"] == TERMINAL_HOLD
    assert result["receipt"]["problems"] == ["SUITE_COMMITMENT_REUSE"]


def test_cli_is_real_consumer_and_package_is_append_only(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    package_root = tmp_path / "prepared"
    command = [
        sys.executable,
        str(SCRIPT),
        "--request",
        str(request_path),
        "--package-root",
        str(package_root),
    ]

    environment = {
        **os.environ,
        "XINAO_RESEARCH_RUNTIME_ROOT": str(tmp_path),
    }
    first = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout)
    assert summary["terminal"] == TERMINAL_READY
    assert sorted(summary["published"]) == [
        "batch_manifest.v1.json",
        "obligation_ledger.v1.json",
        "preparation_receipt.v1.json",
        "preregistration.v1.json",
        "request.v1.json",
    ]
    assert (
        json.loads((package_root / "preparation_receipt.v1.json").read_text(encoding="utf-8"))[
            "outcome_accessed"
        ]
        is False
    )

    second = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert second.returncode != 0
    assert "package root already exists" in second.stderr


def test_cli_hold_publishes_receipt_only(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(_request(power_status="PLANNED")),
        encoding="utf-8",
    )
    package_root = tmp_path / "hold"

    process = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--request",
            str(request_path),
            "--package-root",
            str(package_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "XINAO_RESEARCH_RUNTIME_ROOT": str(tmp_path),
        },
    )

    assert process.returncode == 2
    assert sorted(path.name for path in package_root.iterdir()) == ["preparation_receipt.v1.json"]
    receipt = json.loads((package_root / "preparation_receipt.v1.json").read_text(encoding="utf-8"))
    assert receipt["terminal"] == TERMINAL_HOLD
    assert receipt["preregistration_included"] is False


def test_cli_rejects_package_root_outside_runtime(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    escaped_root = tmp_path.parent / f"{tmp_path.name}-outside-runtime"

    process = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--request",
            str(request_path),
            "--package-root",
            str(escaped_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "XINAO_RESEARCH_RUNTIME_ROOT": str(tmp_path),
        },
    )

    assert process.returncode != 0
    assert "package root must remain under D:" in process.stderr
    assert not escaped_root.exists()
