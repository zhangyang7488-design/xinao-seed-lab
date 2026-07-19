"""Prepare one frozen direct WorkerPool common logical contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.execution_contract import (
    artifact_json_bytes,
    canonical_json_bytes,
    logical_contract_sha256,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    build_direct_worker_pool_logical_contract,
    direct_worker_pool_capability_binding,
    direct_worker_pool_output_contract,
)

DEFAULT_RULES_FILE = Path(r"C:\Users\xx363\Desktop\主线\工具胶水宪法\软件工具胶水宪法_当前有效.txt")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path, field: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(raw)


def prepare_contract(
    *,
    prompt_file: Path,
    selection_receipt_file: Path,
    rules_file: Path,
    frozen_context_sha256: str,
    subject_manifest_sha256: str,
    work_key: str,
    operation_id: str,
    task_contract_ref: str,
    parent_operation_id: str,
    correlation_id: str,
    min_result_chars: int,
    required_result_markers: Sequence[str],
    require_json_object: bool,
    json_schema_file: Path | None,
    write: bool,
    deadline_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt_text = prompt_file.read_bytes().decode("utf-8-sig")
    selection_receipt = _load_json(selection_receipt_file, "selection_receipt")
    selected_raw = selection_receipt.get("selected_candidate")
    if not isinstance(selected_raw, Mapping):
        raise ValueError("selection_receipt.selected_candidate must be an object")
    selected = dict(selected_raw)
    selection_digest = str(selection_receipt.get("decision_sha256") or "")

    schema_digest = ""
    if json_schema_file is not None:
        schema_digest = _sha256_bytes(json_schema_file.read_bytes())
    output_contract = direct_worker_pool_output_contract(
        min_result_chars=min_result_chars,
        required_result_markers=required_result_markers,
        require_json_object=require_json_object,
        json_schema_sha256=schema_digest,
    )
    output_contract_sha256 = _sha256_bytes(canonical_json_bytes(output_contract))
    capability_binding = direct_worker_pool_capability_binding(
        selection_decision_sha256=selection_digest,
        output_contract_sha256=output_contract_sha256,
    )
    contract = build_direct_worker_pool_logical_contract(
        work_key=work_key,
        operation_id=operation_id,
        task_contract_ref=task_contract_ref,
        parent_operation_id=parent_operation_id,
        correlation_id=correlation_id,
        provider_id=str(selected.get("provider_id") or ""),
        profile_ref=str(selected.get("profile_ref") or ""),
        model_id=str(selected.get("model_id") or ""),
        frozen_input_sha256=_sha256_bytes(prompt_text.encode("utf-8")),
        frozen_context_sha256=frozen_context_sha256,
        subject_manifest_sha256=subject_manifest_sha256,
        rules_sha256=_sha256_bytes(rules_file.read_bytes()),
        output_contract_sha256=output_contract_sha256,
        capability_binding=capability_binding,
        write=write,
        deadline_seconds=deadline_seconds,
    )
    manifest = {
        "schema_version": "xinao.direct_worker_pool.contract_prepare_receipt.v1",
        "authority": False,
        "completion_claim_allowed": False,
        "logical_contract_sha256": logical_contract_sha256(contract),
        "prompt_file": str(prompt_file),
        "prompt_sha256": contract["input_sha256"],
        "selection_receipt_file": str(selection_receipt_file),
        "selection_decision_sha256": selection_digest,
        "rules_file": str(rules_file),
        "rules_sha256": contract["rules_sha256"],
        "frozen_context_sha256": frozen_context_sha256,
        "subject_manifest_sha256": subject_manifest_sha256,
        "output_contract": output_contract,
        "output_contract_sha256": output_contract_sha256,
        "capability_binding": capability_binding,
        "capability_binding_sha256": contract["selection"]["capability_binding_sha256"],
    }
    return contract, manifest


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--selection-receipt", required=True, type=Path)
    parser.add_argument("--rules-file", type=Path, default=DEFAULT_RULES_FILE)
    parser.add_argument("--frozen-context-sha256", required=True)
    parser.add_argument("--subject-manifest-sha256", required=True)
    parser.add_argument("--work-key", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--task-contract-ref", default="")
    parser.add_argument("--parent-operation-id", default="")
    parser.add_argument("--correlation-id", default="")
    parser.add_argument("--min-result-chars", required=True, type=int)
    parser.add_argument("--required-result-marker", action="append", default=[])
    parser.add_argument("--require-json-object", action="store_true")
    parser.add_argument("--json-schema-file", type=Path, default=None)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--deadline-seconds", type=int, default=600)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt-output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    contract, manifest = prepare_contract(
        prompt_file=args.prompt_file,
        selection_receipt_file=args.selection_receipt,
        rules_file=args.rules_file,
        frozen_context_sha256=args.frozen_context_sha256,
        subject_manifest_sha256=args.subject_manifest_sha256,
        work_key=args.work_key,
        operation_id=args.operation_id,
        task_contract_ref=args.task_contract_ref,
        parent_operation_id=args.parent_operation_id,
        correlation_id=args.correlation_id,
        min_result_chars=args.min_result_chars,
        required_result_markers=list(args.required_result_marker),
        require_json_object=args.require_json_object,
        json_schema_file=args.json_schema_file,
        write=args.write,
        deadline_seconds=args.deadline_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(artifact_json_bytes(contract))
    receipt_path = args.receipt_output or args.output.with_name("contract_prepare_receipt.json")
    receipt_path.write_bytes(artifact_json_bytes(manifest))
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
