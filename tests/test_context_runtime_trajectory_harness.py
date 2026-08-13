from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = (
    REPO_ROOT / "evals" / "context_runtime_trajectory" / "run_context_runtime_trajectory.py"
)
SCHEMA_PATH = REPO_ROOT / "evals" / "context_runtime_trajectory" / "receipt.schema.json"


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "context_runtime_trajectory_harness", HARNESS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_receipt_is_isolated_machine_readable_and_claim_bounded(tmp_path: Path) -> None:
    harness = _load_harness()
    operation_root = tmp_path / "operation"
    receipt = harness.run_contract(operation_root)

    assert receipt["schema_version"] == "s.context_runtime_trajectory_receipt.v1"
    assert receipt["mode"] == "contract"
    assert receipt["evidence_level"] == "deterministic_contract"
    assert receipt["claim_class"] == "context_contract_only"
    assert receipt["status"] == "passed"
    assert receipt["runtime_claim_allowed"] is False
    assert receipt["summary"]["selected"] == 4
    assert receipt["summary"]["passed"] == 4
    assert receipt["summary"]["failed"] == 0
    assert receipt["summary"]["ineligible"] == 0
    assert receipt["isolation"] == {
        "operation_scoped": True,
        "production_store_used": False,
        "production_codex_home_used": False,
        "separate_case_roots": True,
        "separate_enabled_and_empty_stores": True,
        "network_or_model_called": False,
    }
    assert {
        "model_used_rehydrated_context_correctly",
        "zero_tool_or_external_effect_in_a_model_turn",
        "fresh_compact_or_resume_app_server_protocol",
        "longitudinal_reduction_of_user_correction_burden",
    }.issubset(receipt["claim_boundary"]["does_not_prove"])
    for case in receipt["cases"]:
        assert case["status"] == "passed"
        assert case["runtime_claim_allowed"] is False
        assert case["failed_assertions"] == []
        assert case["assertions"]
        assert all(case["assertions"].values())
        assert not Path(case["case_root"]).is_absolute()


def test_fresh_ablation_recovers_nonce_only_from_enabled_store(tmp_path: Path) -> None:
    harness = _load_harness()
    receipt = harness.run_contract(
        tmp_path / "operation",
        r"^CTX_FRESH_ENABLED_VS_EMPTY_STORE$",
    )

    assert receipt["summary"]["selected"] == 1
    case = receipt["cases"][0]
    assert case["case_id"] == "CTX_FRESH_ENABLED_VS_EMPTY_STORE"
    assert case["evidence"]["nonce_recovery"] == {"enabled": 3, "empty": 0}
    assert (
        case["evidence"]["matched_source_ref_count"]
        == case["evidence"]["expected_source_ref_count"]
    )
    assert case["evidence"]["claim_scope"] == "mechanical_rehydration_delta_only"


def test_contract_case_pattern_fails_closed_when_it_selects_nothing(tmp_path: Path) -> None:
    harness = _load_harness()
    with pytest.raises(ValueError, match="selected no contract cases"):
        harness.run_contract(tmp_path / "operation", r"^DOES_NOT_EXIST$")


def test_operation_root_cannot_enter_production_context_or_codex_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _load_harness()
    production_context = tmp_path / "production-context"
    production_home = tmp_path / "production-home"
    production_context.mkdir()
    production_home.mkdir()
    monkeypatch.setattr(
        harness.context_runtime,
        "DEFAULT_CONTEXT_FABRIC_ROOT",
        production_context,
    )
    monkeypatch.setattr(
        harness.context_runtime,
        "DEFAULT_ALLOWED_CODEX_HOMES",
        {str(production_home): "s-primary"},
    )

    context_target = production_context / "must-not-create"
    home_target = production_home / "must-not-create"
    with pytest.raises(ValueError, match="production context or Codex homes"):
        harness.run_contract(context_target)
    with pytest.raises(ValueError, match="production context or Codex homes"):
        harness.run_contract(home_target)
    assert not context_target.exists()
    assert not home_target.exists()


def test_live_mode_is_typed_ineligible_and_never_inherits_contract_pass(tmp_path: Path) -> None:
    harness = _load_harness()
    receipt = harness.run_live(
        tmp_path / "live-operation",
        codex_path=None,
        s_codex_home=None,
        b_codex_home=None,
        working_dir=None,
        hook_sink=None,
    )

    assert receipt["mode"] == "live"
    assert receipt["evidence_level"] == "live_app_server_and_hook_sink"
    assert receipt["claim_class"] == "context_live_ineligible"
    assert receipt["status"] == "ineligible"
    assert receipt["runtime_claim_allowed"] is False
    assert receipt["cases"] == []
    assert "live_driver" in receipt["eligibility"]["missing_or_unverified"]
    assert receipt["claim_boundary"]["proves"] == [
        "live_mode_failed_closed_before_model_or_protocol_claim"
    ]


def test_cli_writes_receipt_and_uses_documented_exit_codes(tmp_path: Path) -> None:
    contract_root = tmp_path / "contract-operation"
    contract_output = tmp_path / "receipts" / "contract.json"
    contract = subprocess.run(
        [
            sys.executable,
            str(HARNESS_PATH),
            "--mode",
            "contract",
            "--operation-root",
            str(contract_root),
            "--output",
            str(contract_output),
            "--case-pattern",
            r"^CTX_AC_CLEANROOM_DENIED$",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert contract.returncode == 0, contract.stderr
    contract_receipt = json.loads(contract_output.read_text(encoding="utf-8"))
    assert contract_receipt["status"] == "passed"
    assert contract_receipt["summary"]["selected"] == 1
    assert json.loads(contract.stdout)["schema_version"] == contract_receipt["schema_version"]

    live_output = tmp_path / "receipts" / "live.json"
    live = subprocess.run(
        [
            sys.executable,
            str(HARNESS_PATH),
            "--mode",
            "live",
            "--operation-root",
            str(tmp_path / "live-operation"),
            "--output",
            str(live_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert live.returncode == 3, live.stderr
    live_receipt = json.loads(live_output.read_text(encoding="utf-8"))
    assert live_receipt["status"] == "ineligible"
    assert live_receipt["runtime_claim_allowed"] is False


def test_receipt_schema_accepts_contract_and_live_receipts(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    harness = _load_harness()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    contract = harness.run_contract(
        tmp_path / "contract-operation",
        r"^CTX_CORRUPT_CONTEXT_FAILS_OPEN_TO_L0$",
    )
    live = harness.run_live(
        tmp_path / "live-operation",
        codex_path=None,
        s_codex_home=None,
        b_codex_home=None,
        working_dir=None,
        hook_sink=None,
    )
    jsonschema.validate(contract, schema)
    jsonschema.validate(live, schema)
