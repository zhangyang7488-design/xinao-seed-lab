from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from services.agent_runtime.execution_contract import validate_attempt_receipt
from xinao.capability.g4_batch import build_g4_batch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_g4_c0_batch.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("g4_c0_batch_runner", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _batch() -> dict:
    return build_g4_batch(
        campaign_id="campaign-1",
        batch_id="batch-1",
        batch_sequence=1,
        work_key="g4:batch-1",
        cell_ids=["cell-1", "cell-2", "cell-3"],
        campaign_contract_sha256="1" * 64,
        suite_sha256="2" * 64,
        evaluator_sha256="3" * 64,
        policy_sha256="4" * 64,
        preregistration_sha256="5" * 64,
        power_plan_sha256="6" * 64,
        stopping_rule_sha256="7" * 64,
        retry_policy_sha256="8" * 64,
        holdout_budget_sha256="9" * 64,
        global_trial_ledger_ref="D:/evidence/g4/global-trial-ledger.json",
        global_trial_ledger_snapshot_sha256="a" * 64,
    )


def _request() -> dict:
    return {
        "batch_cells": [
            {
                "family_id": "H01",
                "public_case_id": "public-case-1",
                "subject_configuration": "C0-ALGO",
                "seed_id": seed,
            }
            for seed in (17, 42, 99)
        ],
        "frozen_bindings": {
            "subject_adapter_sha256": "b" * 64,
            "subject_public_cases_sha256": "c" * 64,
        },
        "unit_policy": {
            "unit_of_analysis": "INDEPENDENT_HELDOUT_CASE",
            "seed_role": "WITHIN_CASE_REPLICATION_NOT_INDEPENDENT_N",
            "fixed_seed_ids": [17, 42, 99],
            "model_identity_policy": "PIN_EXACT_OBSERVED_IDENTITY",
        },
        "budget_policy": {
            "max_batch_executions": 3,
            "max_outcome_accesses": 3,
        },
        "stopping_policy": {
            "kind": "FIXED_BUDGET_NO_EARLY_SUCCESS",
            "allow_early_success_stop": False,
            "underpowered_terminal": "UNDERPOWERED",
        },
    }


def _public_rows() -> dict:
    payload = {
        "public_case_id": "public-case-1",
        "public_instructions": "Use only public values.",
        "task_input": {"sequence": [1, 2, 3]},
        "commitment_sha256": "d" * 64,
    }
    return {
        "public-case-1": {
            "public_case_id": "public-case-1",
            "public_prompt": json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "commitment_sha256": "d" * 64,
        }
    }


def test_three_seed_cells_keep_distinct_invocations_without_fake_tokens(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    batch = _batch()
    request = _request()
    contract = runner._logical_contract(
        batch=batch,
        batch_path=tmp_path / "batch.json",
        request=request,
        public_rows=_public_rows(),
        run_id="run-1",
    )
    execution_receipt_path = tmp_path / "execution-receipt.json"
    execution_receipt_path.write_text('{"ok":true}\n', encoding="utf-8")
    cells = [
        {
            "obligation_id": f"cell-{index}",
            "raw_output_sha256": str(index) * 64,
            "raw_output_bytes": 100 + index,
            "subject_output_sha256": str(index) * 64,
            "subject_output_chars": 80 + index,
        }
        for index in range(1, 4)
    ]

    receipt = runner._attempt_receipt(
        contract=contract,
        execution_receipt_path=execution_receipt_path,
        execution_receipt_sha256=runner._raw_sha256(execution_receipt_path),
        cells=cells,
        run_id="run-1",
        runtime_version="promptfoo-0.121.18",
    )

    assert receipt["usage"] == {
        "invocation_count": 3,
        "total_tokens": 0,
        "accepted_tokens": 0,
        "cancelled_tokens": 0,
        "failed_tokens": 0,
    }
    assert [row["invocation"] for row in receipt["invocations"]] == [1, 2, 3]
    assert all(row["state"] == "accepted" for row in receipt["invocations"])
    assert validate_attempt_receipt(contract, receipt).accepted is True


def test_public_store_rejects_family_or_truth_leak(tmp_path: Path) -> None:
    runner = _load_runner()
    path = tmp_path / "public_cases.jsonl"
    leaked_prompt = {
        "public_case_id": "public-case-1",
        "public_instructions": "Use only public values.",
        "task_input": {"sequence": [1, 2, 3], "truth": [1, 0, 1]},
        "commitment_sha256": "d" * 64,
    }
    row = {
        "public_case_id": "public-case-1",
        "public_prompt": json.dumps(leaked_prompt),
        "commitment_sha256": "d" * 64,
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    try:
        runner._load_public_rows(
            path,
            expected_sha256=runner._raw_sha256(path),
            cells=_request()["batch_cells"],
        )
    except runner.C0BatchExecutionError as exc:
        assert "forbidden keys" in str(exc)
    else:
        raise AssertionError("private truth leak was accepted")
