from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    logical_contract_sha256,
)
from services.agent_runtime.g4_batch_execution import adjudicate_g4_batch_execution
from xinao.capability.g4_batch import (
    G4BatchError,
    build_g4_batch,
    validate_g4_batch,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _batch() -> dict:
    return build_g4_batch(
        campaign_id="g4-campaign-1",
        batch_id="batch-1",
        batch_sequence=1,
        work_key="g4:batch-1",
        cell_ids=["H01:C1:S1", "H02:C1:S1"],
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


def _contract(batch: dict, *, provider: str, model: str, transport: str) -> dict:
    return {
        "schema_version": LOGICAL_CONTRACT_VERSION,
        "logical_operation_id": f"execute:{batch['batch_id']}:{provider}",
        "work_key": batch["work_key"],
        "task_contract_ref": f"batch.json#sha256={batch['content_hash']}",
        "parent_operation_id": "g4-campaign-1",
        "correlation_id": batch["batch_id"],
        "input_sha256": batch["content_hash"],
        "context_sha256": "b" * 64,
        "rules_sha256": "c" * 64,
        "output_contract_sha256": "d" * 64,
        "selection": {
            "provider_id": provider,
            "profile_ref": f"{provider}.profile",
            "model_id": model,
            "transport_id": transport,
            "capability_binding_sha256": "e" * 64,
        },
        "effect_mode": "read_only",
        "idempotency_key": f"g4:{batch['batch_id']}:{provider}",
        "deadline": {
            "owner": "worker-bus",
            "mode": "relative_from_activity_start",
            "seconds": 1800,
        },
        "cancellation_generation": 0,
    }


def _receipt(contract: dict) -> dict:
    selection = contract["selection"]
    return {
        "schema_version": ATTEMPT_RECEIPT_VERSION,
        "contract_sha256": logical_contract_sha256(contract),
        "consumer_id": "g4-batch-test-worker",
        "logical_operation_id": contract["logical_operation_id"],
        "work_key": contract["work_key"],
        "attempt": 1,
        "observed": {
            **selection,
            "rules_sha256": contract["rules_sha256"],
            "runtime_version": "test-runtime-v1",
            "execution_location": "test:local",
            "executor_id": "test-worker-1",
        },
        "terminal_state": "completed",
        "stop_reason": "EndTurn",
        "output": {
            "format": "json_object",
            "content_sha256": "f" * 64,
            "chars": 1200,
            "schema_sha256": contract["output_contract_sha256"],
            "schema_valid": True,
            "markers_ok": True,
            "substantive": True,
        },
        "invocations": [
            {
                "invocation": 1,
                "state": "accepted",
                "observed_model": selection["model_id"],
                "stop_reason": "EndTurn",
                "output_sha256": "f" * 64,
                "output_chars": 1200,
                "total_tokens": 100,
            }
        ],
        "usage": {
            "invocation_count": 1,
            "total_tokens": 100,
            "accepted_tokens": 100,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
        "lineage": {
            "workflow_id": "g4-campaign-1",
            "lane_id": "batch-1",
            "parent_operation_id": contract["parent_operation_id"],
            "correlation_id": contract["correlation_id"],
            "session_id": "test-session",
        },
        "provider_contract_version": "xinao.test.execution_contract.v1",
        "provider_evidence_ref": "D:/evidence/g4/provider-result.json",
        "provider_evidence_sha256": "0" * 64,
        "provider_evidence_valid": True,
        "replayed": False,
    }


def test_one_scientific_batch_is_not_bound_to_any_provider_or_quota() -> None:
    batch = _batch()

    assert batch["route_binding"] == {
        "scope": "batch_only",
        "selection_source": "canonical_worker_bus_route_receipt",
        "campaign_provider_locked": False,
        "full_campaign_capacity_precommit_required": False,
    }
    serialized = str(batch).lower()
    assert "provider_id" not in serialized
    assert "transport_id" not in serialized
    assert "api_key" not in serialized
    assert "quota" not in serialized


def test_same_batch_can_use_two_replaceable_worker_routes() -> None:
    batch = _batch()
    first_contract = _contract(
        batch,
        provider="grok",
        model="grok-4.5",
        transport="direct-worker-pool",
    )
    second_contract = _contract(
        batch,
        provider="codex",
        model="gpt-5.6",
        transport="codex-worker",
    )

    first = adjudicate_g4_batch_execution(
        batch_manifest=batch,
        logical_contract=first_contract,
        attempt_receipt=_receipt(first_contract),
    )
    second = adjudicate_g4_batch_execution(
        batch_manifest=batch,
        logical_contract=second_contract,
        attempt_receipt=_receipt(second_contract),
    )

    assert first["batch_execution_accepted"] is True
    assert second["batch_execution_accepted"] is True
    assert first["batch_manifest_sha256"] == second["batch_manifest_sha256"]
    assert first["selected_route_for_this_batch"] != second["selected_route_for_this_batch"]
    assert first["provider_binding_scope"] == "batch_attempt_only"
    assert second["campaign_provider_locked"] is False
    assert second["full_campaign_capacity_precommit_required"] is False
    assert second["api_quota_is_campaign_gate"] is False
    assert second["global_wait_allowed"] is False
    assert first["attempt_receipt_sha256"] != second["attempt_receipt_sha256"]


def test_fresh_cli_consumes_common_receipt_without_campaign_route_lock(
    tmp_path: Path,
) -> None:
    batch = _batch()
    contract = _contract(
        batch,
        provider="grok",
        model="grok-4.5",
        transport="direct-worker-pool",
    )
    batch_path = tmp_path / "batch.json"
    contract_path = tmp_path / "logical-contract.json"
    receipt_path = tmp_path / "attempt-receipt.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    receipt_path.write_text(json.dumps(_receipt(contract)), encoding="utf-8")
    env = dict(os.environ)
    env["XINAO_RESEARCH_RUNTIME_ROOT"] = str(tmp_path)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "xinao_discovery" / "src"),
            env.get("PYTHONPATH", ""),
        ]
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_g4_batch_execution_admission.py"),
            "--batch-manifest",
            str(batch_path),
            "--logical-contract",
            str(contract_path),
            "--attempt-receipt",
            str(receipt_path),
            "--op-root",
            str(tmp_path / "operation"),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    report_path = Path(result["report_path"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result["batch_execution_accepted"] is True
    assert report["provider_binding_scope"] == "batch_attempt_only"
    assert report["campaign_provider_locked"] is False
    assert report["full_campaign_capacity_precommit_required"] is False
    assert report["global_wait_allowed"] is False
    assert report["g4_full"] is False
    assert report["g5_closed"] is False
    assert report["formal_research_allowed"] is False


def test_batch_contract_rejects_embedded_route_identity() -> None:
    batch = _batch()
    forged = copy.deepcopy(batch)
    forged["provider_id"] = "some-api"
    with pytest.raises(G4BatchError, match="fields do not match"):
        validate_g4_batch(forged)


def test_attempt_receipt_must_bind_the_exact_batch_hash() -> None:
    batch = _batch()
    contract = _contract(
        batch,
        provider="grok",
        model="grok-4.5",
        transport="direct-worker-pool",
    )
    contract["input_sha256"] = "9" * 64
    report = adjudicate_g4_batch_execution(
        batch_manifest=batch,
        logical_contract=contract,
        attempt_receipt=_receipt(contract),
    )

    assert report["batch_execution_accepted"] is False
    assert "BATCH_INPUT_HASH_MISMATCH" in report["reason_codes"]


def test_campaign_wide_provider_capacity_preflight_is_retired() -> None:
    source = (REPO_ROOT / "scripts" / "run_g4_full_capacity_preflight.py").read_text(
        encoding="utf-8"
    )

    assert "RETIRED_FULL_CAMPAIGN_PROVIDER_CAPACITY_PREFLIGHT" in source
    assert "10_206" not in source
    assert "DEFAULT_RELAY" not in source
    assert "--quota-query" not in source
    assert "--launcher" not in source

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_g4_full_capacity_preflight.py"),
            "--launcher",
            "must-not-run",
            "--quota-query",
            "must-not-run",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert result["reason_code"] == "RETIRED_FULL_CAMPAIGN_PROVIDER_CAPACITY_PREFLIGHT"
    assert result["provider_invocation_performed"] is False
    assert result["quota_query_performed"] is False
    assert result["hidden_outcome_access"] is False
