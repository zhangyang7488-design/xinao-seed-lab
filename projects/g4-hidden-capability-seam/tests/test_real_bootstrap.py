from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from g4_hidden_capability_seam.real_vault import RealHiddenBootstrapVault  # noqa: E402
from g4_hidden_capability_seam.vault import SUBJECT_CAP  # noqa: E402


ADAPTER_PATH = ROOT / "adapters" / "promptfoo_c0_bootstrap_adapter.py"


def _adapter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("promptfoo_c0_bootstrap_test", ADAPTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clear_forbidden_env(monkeypatch: pytest.MonkeyPatch, adapter: ModuleType) -> None:
    for key in list(os.environ):
        if any(token in key.upper() for token in adapter.FORBIDDEN_ENV_TOKENS):
            monkeypatch.delenv(key, raising=False)


def test_public_only_adapter_discovers_functional_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter()
    _clear_forbidden_env(monkeypatch, adapter)
    table = [
        {"a": a, "b": b, "unused": unused}
        for unused in (0, 1)
        for a, b in ((0, 0), (0, 1), (1, 0), (1, 1))
    ]
    labels = [row["a"] ^ row["b"] for row in table]
    public = {
        "public_case_id": "pc_public_only",
        "public_instructions": "Find a compact reproducible relation.",
        "task_input": {"table": table, "labels": labels, "ask": "Find a compact rule."},
        "commitment_sha256": "1" * 64,
    }
    prompt = json.dumps(public, sort_keys=True, separators=(",", ":"))
    response = adapter.call_api(
        prompt,
        {},
        {
            "vars": {
                "public_prompt": prompt,
                "public_case_id": "pc_public_only",
                "commitment_sha256": "1" * 64,
            }
        },
    )
    envelope = json.loads(response["output"])
    assert envelope["analysis"]["decision"] == "STRUCTURE"
    assert envelope["analysis"]["active_columns"] == ["a", "b"]
    assert envelope["analysis"]["training_accuracy"] == 1.0
    assert "family_id" not in envelope
    assert "truth" not in envelope
    assert "g4_closed" not in envelope


def test_adapter_rejects_private_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter()
    monkeypatch.setenv("VAULT_LOCATOR", "forbidden")
    response = adapter.call_api("{}", {}, {"vars": {}})
    assert response == {"error": "subject_forbidden_environment"}


def test_real_hidden_vault_public_view_never_exposes_private_fields(tmp_path: Path) -> None:
    vault = RealHiddenBootstrapVault(tmp_path / "vault")
    initialized_truth = json.loads(vault.truth_path.read_text(encoding="utf-8"))
    initialized_meta = json.loads(vault.meta_path.read_text(encoding="utf-8"))
    assert initialized_truth["schema_version"] == ("xinao.g4.real_hidden_bootstrap.sealed_truth.v1")
    assert initialized_meta["schema_version"] == ("xinao.g4.real_hidden_bootstrap.vault_meta.v1")
    assert "synthetic_only" not in initialized_truth
    record = {
        "public_case_id": "pc_001",
        "family_id": "H03",
        "split": "heldout",
        "case_index": 0,
        "public_instructions": "Find a compact reproducible relation.",
        "task_input": {"table": [{"a": 0, "b": 0}], "labels": [0]},
        "hidden_parameters": {"private": True},
        "truth": {"active_columns": ["a", "b"]},
        "expected_disposition": "IDENTIFY_STRUCTURE",
        "scoring_policy_id": "scoring_policy.structure_match.v1",
        "commitment_sha256": "2" * 64,
    }
    deposited = vault.deposit_private_bundle(
        private_bundle={"records": [record]},
        suite_identity={"identity_sha256": "3" * 64},
        generator_artifact={"artifact_sha256": "4" * 64},
        selected_case_ids=["pc_001"],
    )
    assert deposited["ok"] is True
    public = vault.public_case_view("pc_001")
    assert public["ok"] is True
    assert "family_id" not in public
    assert "hidden_parameters" not in public
    assert "truth" not in public
    denied = vault.subject_read(capability=SUBJECT_CAP, public_case_id="pc_001")
    assert denied["ok"] is False
    assert denied["reason"] == "subject_vault_read_denied"
    _targets, target_set = vault._exact_controlled_vault_targets(expected_receipt=False)
    assert target_set["ok"] is True
    assert target_set["observed_target_names"] == [
        ".subject_denied",
        "sealed_truth.v1.json",
        "vault_meta.v1.json",
    ]
