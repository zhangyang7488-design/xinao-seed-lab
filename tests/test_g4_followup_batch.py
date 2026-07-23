from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from xinao.canonical import canonical_sha256
from xinao.capability.g4_preregistration import (
    REQUEST_SCHEMA,
    build_split_manifest,
    prepare_g4_preregistration,
)
from xinao.single_home.power_plan import build_power_plan

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "prepare_g4_followup_batch.py"
PREPARE_SCRIPT = REPO_ROOT / "scripts" / "prepare_g4_batch_preregistration.py"


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha(character: str) -> str:
    return character * 64


def _campaign_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    followup = _load_script(SCRIPT, "g4_followup_batch_test")
    publisher = _load_script(PREPARE_SCRIPT, "g4_prepare_batch_test")
    runtime = tmp_path / "runtime"
    root = runtime / "campaign"
    root.mkdir(parents=True)
    monkeypatch.setenv("XINAO_RESEARCH_RUNTIME_ROOT", str(runtime))

    campaign = {
        "h01_h14_sample_design": [
            {
                "family_id": "H01",
                "n": 2,
                "p0": 0.5,
                "p1": 0.8,
                "attained_power": 0.82,
            }
        ]
    }
    campaign_path = root / "campaign_preregistration_source.v1.json"
    acceptance_path = root / "owner_acceptance_source.v1.json"
    _write_json(campaign_path, campaign)
    _write_json(acceptance_path, {"accepted": True})

    case_id = "pc_h01_001"
    commitment = _sha("a")
    public_cases_path = root / "subject" / "public_cases.v1.jsonl"
    public_cases_path.parent.mkdir(parents=True)
    public_cases_path.write_text(
        json.dumps(
            {
                "public_case_id": case_id,
                "public_prompt": json.dumps(
                    {
                        "public_case_id": case_id,
                        "public_instructions": "Use public input only.",
                        "task_input": {"values": [1, 2, 3]},
                        "commitment_sha256": commitment,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "commitment_sha256": commitment,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    case_index = {
        "campaign_id": "campaign-1",
        "case_ids_by_family": {"H01": [case_id]},
        "outcome_accessed": False,
    }
    _write_json(root / "owner" / "planned_case_index.v1.json", case_index)

    seeds = [17, 42]
    c0_cells = [
        {
            "family_id": "H01",
            "public_case_id": case_id,
            "subject_configuration": "C0-ALGO",
            "seed_id": seed,
        }
        for seed in seeds
    ]
    c1_cells = [
        {
            **cell,
            "subject_configuration": "C1-CHEAP",
        }
        for cell in c0_cells
    ]
    ledger_path = root / "ledger" / "global_trial_ledger_export.v1.json"
    _write_json(
        ledger_path,
        {
            "work_keys": [
                f"g4:campaign-1:{canonical_sha256(cell)}" for cell in [*c0_cells, *c1_cells]
            ]
        },
    )

    split = build_split_manifest(
        split_manifest_id="campaign-1:split",
        suite_version="1",
        boundaries={
            "training": {
                "case_count": 1,
                "suite_commitment_sha256": _sha("1"),
            },
            "heldout": {
                "case_count": 1,
                "suite_commitment_sha256": _sha("2"),
            },
        },
        purge_cases=0,
        embargo_cases=0,
        holdout_exposure_budget=4,
    )
    design = campaign["h01_h14_sample_design"][0]
    power_plan = build_power_plan(
        plan_id="campaign-1:H01:accepted-v7",
        family_id="H01",
        mde=0.3,
        target_power=0.8,
        max_budget_trials=2,
        holdout_split_binding=split["content_hash"],
        serial_dependence_declared=True,
        status="ADEQUATE",
    )
    first_request = {
        "schema_version": REQUEST_SCHEMA,
        "campaign_id": "campaign-1",
        "batch_id": "batch-c0-1",
        "batch_sequence": 1,
        "work_key": "g4:batch-c0-1",
        "campaign_preregistration_ref": str(campaign_path),
        "campaign_preregistration_sha256": followup._raw_sha256(campaign_path),
        "families": ["H01"],
        "subject_configurations": ["C0-ALGO"],
        "batch_cells": c0_cells,
        "split_manifest": split,
        "power_plans": {"H01": power_plan},
        "frozen_bindings": {
            "suite_sha256": _sha("4"),
            "generator_sha256": _sha("5"),
            "evaluator_sha256": _sha("6"),
            "scoring_policy_sha256": _sha("7"),
            "subject_adapter_sha256": _sha("8"),
            "subject_public_cases_sha256": followup._raw_sha256(public_cases_path),
        },
        "unit_policy": {
            "unit_of_analysis": "INDEPENDENT_HELDOUT_CASE",
            "seed_role": "WITHIN_CASE_REPLICATION_NOT_INDEPENDENT_N",
            "fixed_seed_ids": seeds,
            "model_identity_policy": "PIN_EXACT_OBSERVED_IDENTITY",
        },
        "budget_policy": {
            "max_batch_executions": 2,
            "max_outcome_accesses": 2,
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
            "power_analysis_policy_sha256_by_family": {"H01": canonical_sha256(design)},
        },
        "campaign_contract_sha256": _sha("d"),
        "retry_policy_sha256": _sha("e"),
        "global_trial_ledger_ref": str(ledger_path),
        "global_trial_ledger_snapshot_sha256": followup._raw_sha256(ledger_path),
        "declared_prior_outcome_receipts": [],
        "reused_outcome_evidence_ids": [],
    }
    prepared = prepare_g4_preregistration(
        first_request,
        prepared_at_utc="2026-07-24T00:00:00.000Z",
    )
    publisher.publish_preparation_package(
        package_root=root / "first_batch_preregistration",
        result=prepared,
    )
    initialization = {
        "schema_version": followup.INITIALIZATION_SCHEMA,
        "campaign_id": "campaign-1",
        "package_root": str(root),
        "source_campaign_preregistration_sha256": followup._raw_sha256(campaign_path),
        "source_owner_acceptance_sha256": followup._raw_sha256(acceptance_path),
        "subject_public_cases": {"sha256": followup._raw_sha256(public_cases_path)},
        "heldout_identity_sha256": _sha("4"),
        "evaluator_family_support": {"supported_families": ["H01"]},
        "vault_lockdown_verified": True,
        "outcome_accessed": False,
        "evaluator_invoked": False,
    }
    initialization["content_hash"] = canonical_sha256(initialization)
    _write_json(root / "initialization_receipt.v1.json", initialization)
    adapter = tmp_path / "qwen_adapter.py"
    adapter.write_text("def invoke(prompt):\n    return prompt\n", encoding="utf-8")
    return followup, root, adapter


def test_followup_batch_freezes_one_configuration_and_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    followup, root, adapter = _campaign_fixture(tmp_path, monkeypatch)

    summary = followup.freeze_followup_batch(
        campaign_package_root=root,
        batch_id="batch-c1-2",
        batch_sequence=2,
        work_key="g4:batch-c1-2",
        families=["H01"],
        configuration="C1-CHEAP",
        case_offset=0,
        cases_per_family=1,
        subject_adapter=adapter,
    )

    package = Path(summary["package_root"])
    request = json.loads((package / "request.v1.json").read_text(encoding="utf-8"))
    receipt = json.loads((package / "followup_freeze_receipt.v1.json").read_text(encoding="utf-8"))
    assert summary["terminal"] == "G4_PREREGISTRATION_READY_NO_OUTCOME_ACCESS"
    assert request["subject_configurations"] == ["C1-CHEAP"]
    assert {cell["subject_configuration"] for cell in request["batch_cells"]} == {"C1-CHEAP"}
    assert request["frozen_bindings"]["subject_adapter_sha256"] == followup._raw_sha256(
        package / receipt["subject_adapter_snapshot"]
    )
    assert receipt["registered_before_outcome_access"] is True
    assert receipt["outcome_accessed"] is False


def test_followup_batch_rejects_known_outcome_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    followup, root, adapter = _campaign_fixture(tmp_path, monkeypatch)

    with pytest.raises(followup.FollowupBatchError, match="outcome access"):
        followup.freeze_followup_batch(
            campaign_package_root=root,
            batch_id="batch-c1-2",
            batch_sequence=2,
            work_key="g4:batch-c1-2",
            families=["H01"],
            configuration="C1-CHEAP",
            case_offset=0,
            cases_per_family=1,
            subject_adapter=adapter,
            known_prior_outcome_receipts=["outcome-receipt-1"],
        )


def test_followup_adapter_snapshot_uses_one_immutable_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    followup, root, adapter = _campaign_fixture(tmp_path, monkeypatch)
    original_read_bytes = Path.read_bytes
    adapter_reads = 0

    def unstable_adapter_read(path: Path) -> bytes:
        nonlocal adapter_reads
        if path.resolve() == adapter.resolve():
            adapter_reads += 1
            return (
                b"def invoke(prompt):\n    return {'snapshot': 1}\n"
                if adapter_reads == 1
                else b"def invoke(prompt):\n    return {'snapshot': 2}\n"
            )
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", unstable_adapter_read)
    summary = followup.freeze_followup_batch(
        campaign_package_root=root,
        batch_id="batch-c1-2",
        batch_sequence=2,
        work_key="g4:batch-c1-2",
        families=["H01"],
        configuration="C1-CHEAP",
        case_offset=0,
        cases_per_family=1,
        subject_adapter=adapter,
    )

    package = Path(summary["package_root"])
    request = json.loads((package / "request.v1.json").read_text(encoding="utf-8"))
    receipt = json.loads((package / "followup_freeze_receipt.v1.json").read_text(encoding="utf-8"))
    snapshot = package / receipt["subject_adapter_snapshot"]
    assert adapter_reads == 1
    assert (
        followup._raw_sha256(snapshot)
        == request["frozen_bindings"]["subject_adapter_sha256"]
        == receipt["subject_adapter_sha256"]
    )


def test_followup_rejects_cells_already_frozen_by_an_existing_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    followup, root, adapter = _campaign_fixture(tmp_path, monkeypatch)
    followup.freeze_followup_batch(
        campaign_package_root=root,
        batch_id="batch-c1-2",
        batch_sequence=2,
        work_key="g4:batch-c1-2",
        families=["H01"],
        configuration="C1-CHEAP",
        case_offset=0,
        cases_per_family=1,
        subject_adapter=adapter,
    )

    with pytest.raises(followup.FollowupBatchError, match="overlap"):
        followup.freeze_followup_batch(
            campaign_package_root=root,
            batch_id="batch-c1-3",
            batch_sequence=3,
            work_key="g4:batch-c1-3",
            families=["H01"],
            configuration="C1-CHEAP",
            case_offset=0,
            cases_per_family=1,
            subject_adapter=adapter,
        )


def test_followup_rejects_outcome_opened_campaign_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    followup, root, adapter = _campaign_fixture(tmp_path, monkeypatch)
    initialization_path = root / "initialization_receipt.v1.json"
    initialization = json.loads(initialization_path.read_text(encoding="utf-8"))
    initialization["outcome_accessed"] = True
    initialization["content_hash"] = canonical_sha256(
        {key: value for key, value in initialization.items() if key != "content_hash"}
    )
    _write_json(initialization_path, initialization)

    with pytest.raises(followup.FollowupBatchError, match="pre-outcome"):
        followup.freeze_followup_batch(
            campaign_package_root=root,
            batch_id="batch-c1-2",
            batch_sequence=2,
            work_key="g4:batch-c1-2",
            families=["H01"],
            configuration="C1-CHEAP",
            case_offset=0,
            cases_per_family=1,
            subject_adapter=adapter,
        )
