from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.prepare_direct_worker_pool_common_contract import prepare_contract
from services.agent_runtime.execution_contract import (
    canonical_json_bytes,
    validate_logical_contract,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_prepare_contract_binds_prompt_selection_rules_context_and_output(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_bytes("COMMON_CANARY_OK\r\n".encode())
    rules = tmp_path / "rules.txt"
    rules.write_bytes(b"rules-v1")
    selection = tmp_path / "selection.json"
    decision_sha = "f" * 64
    _write_json(
        selection,
        {
            "decision_sha256": decision_sha,
            "selected_candidate": {
                "provider_id": "grok_acpx_headless",
                "profile_ref": "grok.com.cached_profile",
                "model_id": "grok-4.5",
                "transport_id": "direct-grok-worker-pool",
            },
        },
    )
    frozen_context = "d" * 64
    subject = "b" * 64
    contract, manifest = prepare_contract(
        prompt_file=prompt,
        selection_receipt_file=selection,
        rules_file=rules,
        frozen_context_sha256=frozen_context,
        subject_manifest_sha256=subject,
        work_key="wk:common-canary",
        operation_id="op-common-canary",
        task_contract_ref="task-common-canary",
        parent_operation_id="parent",
        correlation_id="corr",
        min_result_chars=16,
        required_result_markers=["COMMON_CANARY_OK"],
        require_json_object=False,
        json_schema_file=None,
        write=False,
        deadline_seconds=300,
    )
    validate_logical_contract(contract)
    assert contract["input_sha256"] == hashlib.sha256(
        "COMMON_CANARY_OK\r\n".encode()
    ).hexdigest()
    assert contract["rules_sha256"] == hashlib.sha256(b"rules-v1").hexdigest()
    assert contract["selection"]["provider_id"] == "grok_acpx_headless"
    assert contract["selection"]["transport_id"] == "direct-grok-worker-pool"
    assert manifest["selection_decision_sha256"] == decision_sha
    assert manifest["frozen_context_sha256"] == frozen_context
    assert manifest["subject_manifest_sha256"] == subject
    assert manifest["output_contract"]["required_result_markers"] == [
        "COMMON_CANARY_OK"
    ]
    assert manifest["capability_binding"]["contract_mode"] == (
        "provider_v1_then_common_adapter"
    )
    expected_output_hash = hashlib.sha256(
        canonical_json_bytes(manifest["output_contract"])
    ).hexdigest()
    assert manifest["output_contract_sha256"] == expected_output_hash


def test_prepare_contract_binds_schema_to_json_requirement(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("{}", encoding="utf-8")
    rules = tmp_path / "rules.txt"
    rules.write_text("rules", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text('{"type":"object"}', encoding="utf-8")
    selection = tmp_path / "selection.json"
    _write_json(
        selection,
        {
            "decision_sha256": "f" * 64,
            "selected_candidate": {
                "provider_id": "grok_acpx_headless",
                "profile_ref": "grok.com.cached_profile",
                "model_id": "grok-4.5",
                "transport_id": "direct-grok-worker-pool",
            },
        },
    )
    _, manifest = prepare_contract(
        prompt_file=prompt,
        selection_receipt_file=selection,
        rules_file=rules,
        frozen_context_sha256="d" * 64,
        subject_manifest_sha256="b" * 64,
        work_key="wk:schema",
        operation_id="op-schema",
        task_contract_ref="",
        parent_operation_id="",
        correlation_id="",
        min_result_chars=1,
        required_result_markers=[],
        require_json_object=False,
        json_schema_file=schema,
        write=False,
        deadline_seconds=300,
    )
    assert manifest["output_contract"]["require_json_object"] is True
    assert manifest["output_contract"]["json_schema_sha256"] == hashlib.sha256(
        schema.read_bytes()
    ).hexdigest()
