"""Prepare one frozen direct WorkerPool common logical contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import exceptions as jsonschema_exceptions
from jsonschema import validators as jsonschema_validators

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.context_slice_manifest import load_context_slice_manifest
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


class ContractPreparationError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path, field: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
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
    frozen_context_sha256: str | None,
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
    context_manifest_file: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt_bytes = prompt_file.read_bytes()
    try:
        prompt_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"prompt_file is not valid UTF-8: {prompt_file}") from exc
    requested_context_sha256 = str(frozen_context_sha256 or "").strip()
    context_manifest: dict[str, Any] | None = None
    context_manifest_sha256 = ""
    if context_manifest_file is not None:
        context_manifest = load_context_slice_manifest(context_manifest_file)
        context_manifest_sha256 = _sha256_bytes(context_manifest_file.read_bytes())
        observed_context_sha256 = str(context_manifest["context_sha256"])
        if requested_context_sha256 and requested_context_sha256 != observed_context_sha256:
            raise ValueError("frozen_context_sha256 does not match validated context manifest")
        frozen_context_sha256 = observed_context_sha256
    elif not requested_context_sha256:
        raise ValueError("frozen_context_sha256 or a validated context_manifest_file is required")
    else:
        frozen_context_sha256 = requested_context_sha256
    selection_receipt = _load_json(selection_receipt_file, "selection_receipt")
    selected_raw = selection_receipt.get("selected_candidate")
    if not isinstance(selected_raw, Mapping):
        raise ValueError("selection_receipt.selected_candidate must be an object")
    selected = dict(selected_raw)
    selection_digest = str(selection_receipt.get("decision_sha256") or "")

    schema_digest = ""
    schema_binding_status = "not_requested"
    if require_json_object and json_schema_file is None:
        raise ContractPreparationError(
            "RESULT_SCHEMA_BOUND_OR_PREMODEL_REJECT",
            "RequireJsonObject requires a canonical JSON schema before model dispatch",
        )
    if json_schema_file is not None:
        try:
            schema = _load_json(json_schema_file, "json_schema_file")
            if schema.get("type") not in (None, "object"):
                raise jsonschema_exceptions.SchemaError("result schema must describe an object")
            validator_class = jsonschema_validators.validator_for(schema)
            validator_class.check_schema(schema)
            schema_digest = _sha256_bytes(json_schema_file.read_bytes())
        except (OSError, ValueError, jsonschema_exceptions.SchemaError) as exc:
            if isinstance(exc, ContractPreparationError):
                raise
            raise ContractPreparationError(
                "RESULT_SCHEMA_BOUND_OR_PREMODEL_REJECT",
                f"canonical result schema is missing or invalid: {json_schema_file}",
            ) from exc
        schema_binding_status = "bound"
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
        frozen_input_sha256=_sha256_bytes(prompt_bytes),
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
        "context_binding_mode": (
            "validated_context_slice_manifest"
            if context_manifest is not None
            else "caller_sha256_legacy"
        ),
        "context_manifest_file": (
            str(context_manifest_file) if context_manifest_file is not None else ""
        ),
        "context_manifest_sha256": context_manifest_sha256,
        "context_slice_spec_sha256": (
            str(context_manifest["spec_sha256"]) if context_manifest is not None else ""
        ),
        "context_source_manifest_sha256": (
            str(context_manifest["source_manifest_sha256"]) if context_manifest is not None else ""
        ),
        "context_total_content_bytes": (
            int(context_manifest["total_content_bytes"]) if context_manifest is not None else 0
        ),
        "subject_manifest_sha256": subject_manifest_sha256,
        "output_contract": output_contract,
        "output_contract_sha256": output_contract_sha256,
        "result_schema_preflight": {
            "status": schema_binding_status,
            "reason_code": "RESULT_SCHEMA_BOUND_OR_PREMODEL_REJECT",
            "model_tokens": 0,
        },
        "capability_binding": capability_binding,
        "capability_binding_sha256": contract["selection"]["capability_binding_sha256"],
    }
    return contract, manifest


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--selection-receipt", required=True, type=Path)
    parser.add_argument("--rules-file", type=Path, default=DEFAULT_RULES_FILE)
    parser.add_argument("--frozen-context-sha256", default="")
    parser.add_argument("--context-manifest-file", type=Path, default=None)
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
    try:
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
            context_manifest_file=args.context_manifest_file,
        )
    except ContractPreparationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "xinao.direct_worker_pool.contract_prepare_receipt.v1",
                    "ok": False,
                    "reason_code": exc.reason_code,
                    "model_tokens": 0,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(artifact_json_bytes(contract))
    receipt_path = args.receipt_output or args.output.with_name("contract_prepare_receipt.json")
    receipt_path.write_bytes(artifact_json_bytes(manifest))
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
