"""Execute one preregistered C0-ALGO batch through the pinned offline runner.

The runner consumes only package-local subject-safe public payloads. Hidden
outcomes remain sealed and the evaluator is never invoked by this command.
Each preregistered seed cell receives a distinct Promptfoo execution and
receipt even when the deterministic C0 subject returns identical outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
SEAM_SRC = REPO_ROOT / "projects" / "g4-hidden-capability-seam" / "src"
for source_root in (str(REPO_ROOT), str(XINAO_SRC), str(SEAM_SRC)):
    if source_root not in sys.path:
        sys.path.insert(0, source_root)

from g4_hidden_capability_seam.canonical import write_json  # noqa: E402
from g4_hidden_capability_seam.promptfoo_runner import (  # noqa: E402
    PINNED_DIGEST,
    PINNED_IMAGE,
    PROMPTFOO_OUTPUT_BASENAME,
    build_promptfoo_config,
    default_denied_roots,
    run_promptfoo_offline,
)
from g4_hidden_capability_seam.real_vault import (  # noqa: E402
    RealHiddenBootstrapVault,
)
from services.agent_runtime.execution_contract import (  # noqa: E402
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    canonical_json_bytes,
    logical_contract_sha256,
    validate_attempt_receipt,
)
from services.agent_runtime.g4_batch_execution import (  # noqa: E402
    adjudicate_g4_batch_execution,
)
from xinao.canonical import canonical_sha256  # noqa: E402
from xinao.capability.g4_hidden_benchmark.public_safety import (  # noqa: E402
    scan_forbidden_public_keys,
    scan_h03_public_hints,
    scan_h04_public_hints,
)
from xinao.capability.g4_preregistration import (  # noqa: E402
    validate_g4_preregistration_package,
)

EXECUTION_RECEIPT_SCHEMA = "xinao.g4.c0_batch_subject_execution.v1"
LOCAL_PROVIDER_ID = "local-c0-algo"
LOCAL_PROFILE_REF = "g4.c0_algo.promptfoo_offline.v1"
LOCAL_MODEL_ID = "c0-algo-no-llm"
LOCAL_TRANSPORT_ID = "promptfoo-0.121.18-offline"
OUTPUT_CONTRACT = {
    "schema_version": EXECUTION_RECEIPT_SCHEMA,
    "required": [
        "batch_manifest_sha256",
        "cells",
        "subject_invocation_count",
        "outcome_accessed",
        "evaluator_invoked",
    ],
}


class C0BatchExecutionError(ValueError):
    """The preregistered C0 batch cannot be executed without boundary drift."""


def _raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise C0BatchExecutionError(f"{path} must contain one JSON object")
    return value


def _new_operation_root(path: Path) -> Path:
    target = path.resolve()
    runtime = Path(r"D:\XINAO_RESEARCH_RUNTIME").resolve()
    try:
        target.relative_to(runtime)
    except ValueError as exc:
        raise C0BatchExecutionError("op_root must remain under D:\\XINAO_RESEARCH_RUNTIME") from exc
    if target.exists():
        raise C0BatchExecutionError(f"op_root already exists: {target}")
    target.mkdir(parents=True)
    return target


def _load_public_rows(
    path: Path,
    *,
    expected_sha256: str,
    cells: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if _raw_sha256(path) != expected_sha256:
        raise C0BatchExecutionError("subject public cases hash drifted")
    rows: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) != {
            "public_case_id",
            "public_prompt",
            "commitment_sha256",
        }:
            raise C0BatchExecutionError(f"subject public row {line_number} has schema drift")
        case_id = str(row["public_case_id"])
        if not case_id or case_id in rows:
            raise C0BatchExecutionError("subject public case IDs are invalid")
        prompt = json.loads(str(row["public_prompt"]))
        if not isinstance(prompt, dict) or set(prompt) != {
            "public_case_id",
            "public_instructions",
            "task_input",
            "commitment_sha256",
        }:
            raise C0BatchExecutionError(f"subject public prompt {case_id} has schema drift")
        if (
            prompt["public_case_id"] != case_id
            or prompt["commitment_sha256"] != row["commitment_sha256"]
        ):
            raise C0BatchExecutionError(f"subject public prompt {case_id} binding drifted")
        forbidden = scan_forbidden_public_keys(prompt)
        if forbidden:
            raise C0BatchExecutionError(
                f"subject public prompt {case_id} leaks forbidden keys: {forbidden}"
            )
        rows[case_id] = row
    selected_ids = {str(cell["public_case_id"]) for cell in cells}
    missing = sorted(selected_ids - set(rows))
    if missing:
        raise C0BatchExecutionError(f"batch public cases are missing: {missing}")
    family_by_case = {str(cell["public_case_id"]): str(cell["family_id"]) for cell in cells}
    for case_id in selected_ids:
        prompt = json.loads(str(rows[case_id]["public_prompt"]))
        family = family_by_case[case_id]
        if family == "H03" and scan_h03_public_hints(prompt):
            raise C0BatchExecutionError(f"H03 public hints leaked for {case_id}")
        if family == "H04" and scan_h04_public_hints(prompt):
            raise C0BatchExecutionError(f"H04 public hints leaked for {case_id}")
    return rows


def _logical_contract(
    *,
    batch: Mapping[str, Any],
    batch_path: Path,
    request: Mapping[str, Any],
    public_rows: Mapping[str, Mapping[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    prompts = [
        str(public_rows[str(cell["public_case_id"])]["public_prompt"])
        for cell in request["batch_cells"]
    ]
    adapter_sha256 = str(request["frozen_bindings"]["subject_adapter_sha256"])
    capability_binding_sha256 = canonical_sha256(
        {
            "adapter_sha256": adapter_sha256,
            "promptfoo_image": PINNED_IMAGE,
            "promptfoo_image_id": PINNED_DIGEST,
            "runner": LOCAL_PROFILE_REF,
        }
    )
    contract = {
        "schema_version": LOGICAL_CONTRACT_VERSION,
        "logical_operation_id": f"g4-c0:{batch['batch_id']}:{run_id}",
        "work_key": batch["work_key"],
        "task_contract_ref": f"{batch_path}#sha256={batch['content_hash']}",
        "parent_operation_id": batch["campaign_id"],
        "correlation_id": batch["batch_id"],
        "input_sha256": hashlib.sha256(canonical_json_bytes(prompts)).hexdigest(),
        "context_sha256": canonical_sha256(
            {
                "suite_sha256": batch["suite_sha256"],
                "subject_public_cases_sha256": request["frozen_bindings"][
                    "subject_public_cases_sha256"
                ],
            }
        ),
        "rules_sha256": canonical_sha256(
            {
                "unit_policy": request["unit_policy"],
                "budget_policy": request["budget_policy"],
                "stopping_policy": request["stopping_policy"],
            }
        ),
        "output_contract_sha256": canonical_sha256(OUTPUT_CONTRACT),
        "selection": {
            "provider_id": LOCAL_PROVIDER_ID,
            "profile_ref": LOCAL_PROFILE_REF,
            "model_id": LOCAL_MODEL_ID,
            "transport_id": LOCAL_TRANSPORT_ID,
            "capability_binding_sha256": capability_binding_sha256,
        },
        "effect_mode": "read_only",
        "idempotency_key": f"{batch['work_key']}:c0:{run_id}",
        "deadline": {
            "owner": "g4-c0-batch-runner",
            "mode": "relative_from_activity_start",
            "seconds": 900,
        },
        "cancellation_generation": 0,
    }
    logical_contract_sha256(contract)
    return contract


def _write_one_public_case(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            dict(row),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _extract_subject_output(
    output_path: Path,
    *,
    public_row: Mapping[str, Any],
) -> dict[str, Any]:
    data = _read_json(output_path)
    results = data.get("results")
    rows = results.get("results") if isinstance(results, Mapping) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise C0BatchExecutionError("Promptfoo output must contain exactly one result row")
    response = rows[0].get("response")
    if not isinstance(response, Mapping) or response.get("cached") is True:
        raise C0BatchExecutionError("Promptfoo subject response is missing or cached")
    output = response.get("output")
    if not isinstance(output, str) or not output:
        raise C0BatchExecutionError("Promptfoo subject output is empty")
    envelope = json.loads(output)
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "public_case_id",
        "commitment_sha256",
        "subject_configuration",
        "analysis",
    }:
        raise C0BatchExecutionError("C0 subject output schema drifted")
    if (
        envelope["schema_version"] != "xinao.g4.bootstrap.c0_subject_output.v1"
        or envelope["public_case_id"] != public_row["public_case_id"]
        or envelope["commitment_sha256"] != public_row["commitment_sha256"]
        or envelope["subject_configuration"] != "C0-ALGO"
        or not isinstance(envelope["analysis"], dict)
    ):
        raise C0BatchExecutionError("C0 subject output binding drifted")
    return {
        "sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "chars": len(output),
        "schema_version": envelope["schema_version"],
    }


def _attempt_receipt(
    *,
    contract: Mapping[str, Any],
    execution_receipt_path: Path,
    execution_receipt_sha256: str,
    cells: Sequence[Mapping[str, Any]],
    run_id: str,
    runtime_version: str,
) -> dict[str, Any]:
    selection = dict(contract["selection"])
    total_chars = sum(int(cell["subject_output_chars"]) for cell in cells)
    receipt = {
        "schema_version": ATTEMPT_RECEIPT_VERSION,
        "contract_sha256": logical_contract_sha256(contract),
        "consumer_id": "g4-c0-promptfoo-batch-consumer",
        "logical_operation_id": contract["logical_operation_id"],
        "work_key": contract["work_key"],
        "attempt": 1,
        "observed": {
            **selection,
            "rules_sha256": contract["rules_sha256"],
            "runtime_version": runtime_version,
            "execution_location": "docker:local-promptfoo-offline",
            "executor_id": PINNED_DIGEST,
        },
        "terminal_state": "completed",
        "stop_reason": "NativeBatchExecutionCompleted",
        "output": {
            "format": "json_object",
            "content_sha256": execution_receipt_sha256,
            "chars": total_chars,
            "schema_sha256": contract["output_contract_sha256"],
            "schema_valid": True,
            "markers_ok": True,
            "substantive": total_chars > 0,
        },
        "invocations": [
            {
                "invocation": index,
                "state": "accepted",
                "observed_model": LOCAL_MODEL_ID,
                "stop_reason": "NativeExecutionCompleted",
                "output_sha256": cell["subject_output_sha256"],
                "output_chars": cell["subject_output_chars"],
                "total_tokens": 0,
            }
            for index, cell in enumerate(cells, 1)
        ],
        "usage": {
            "invocation_count": len(cells),
            "total_tokens": 0,
            "accepted_tokens": 0,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
        "lineage": {
            "workflow_id": str(contract["parent_operation_id"]),
            "lane_id": str(contract["correlation_id"]),
            "parent_operation_id": str(contract["parent_operation_id"]),
            "correlation_id": str(contract["correlation_id"]),
            "session_id": run_id,
        },
        "provider_contract_version": "xinao.g4.c0_promptfoo.execution_contract.v1",
        "provider_evidence_ref": str(execution_receipt_path),
        "provider_evidence_sha256": execution_receipt_sha256,
        "provider_evidence_valid": True,
        "replayed": False,
    }
    verdict = validate_attempt_receipt(contract, receipt)
    if not verdict.accepted:
        raise C0BatchExecutionError(
            f"local C0 attempt receipt was rejected: {verdict.reason_codes}"
        )
    return receipt


def execute(*, package_root: Path, op_root: Path, run_id: str) -> dict[str, Any]:
    package = package_root.resolve()
    operation = _new_operation_root(op_root)
    prereg_root = package / "first_batch_preregistration"
    request_path = prereg_root / "request.v1.json"
    preregistration_path = prereg_root / "preregistration.v1.json"
    ledger_path = prereg_root / "obligation_ledger.v1.json"
    batch_path = prereg_root / "batch_manifest.v1.json"
    request = _read_json(request_path)
    preregistration = _read_json(preregistration_path)
    obligation_ledger = _read_json(ledger_path)
    batch = _read_json(batch_path)
    validated = validate_g4_preregistration_package(
        request=request,
        preregistration=preregistration,
        obligation_ledger=obligation_ledger,
        batch_manifest=batch,
    )
    request = validated["request"]
    batch = validated["batch_manifest"]
    if request["subject_configurations"] != ["C0-ALGO"]:
        raise C0BatchExecutionError("this runner accepts only an exact C0-ALGO batch")
    public_cases_path = package / "subject" / "public_cases.v1.jsonl"
    adapter_path = package / "subject" / "adapter" / "promptfoo_c0_bootstrap_adapter.py"
    frozen = request["frozen_bindings"]
    if _raw_sha256(adapter_path) != frozen["subject_adapter_sha256"]:
        raise C0BatchExecutionError("subject adapter snapshot hash drifted")
    public_rows = _load_public_rows(
        public_cases_path,
        expected_sha256=str(frozen["subject_public_cases_sha256"]),
        cells=request["batch_cells"],
    )
    contract = _logical_contract(
        batch=batch,
        batch_path=batch_path,
        request=request,
        public_rows=public_rows,
        run_id=run_id,
    )
    contract_path = operation / "logical_contract.v1.json"
    write_json(contract_path, contract)
    execution_adapter = operation / "adapters" / "promptfoo_c0_bootstrap_adapter.py"
    execution_adapter.parent.mkdir(parents=True, exist_ok=True)
    execution_adapter.write_bytes(adapter_path.read_bytes())
    if _raw_sha256(execution_adapter) != frozen["subject_adapter_sha256"]:
        raise C0BatchExecutionError("operation adapter snapshot hash drifted")

    vault_root = package / "vault"
    vault = RealHiddenBootstrapVault(vault_root)
    cell_receipts: list[dict[str, Any]] = []
    with vault.hold_verified_locked_phase(expected_receipt=True) as live_lock:
        if live_lock.get("ok") is not True:
            raise C0BatchExecutionError(f"vault live lock verification failed: {live_lock}")
        for index, (cell, obligation) in enumerate(
            zip(
                request["batch_cells"],
                validated["obligation_ledger"]["obligations"],
                strict=True,
            ),
            1,
        ):
            cell_root = operation / "cells" / f"{index:04d}_{obligation['obligation_id']}"
            source_cases = cell_root / "source" / "public_cases.jsonl"
            case_id = str(cell["public_case_id"])
            _write_one_public_case(source_cases, public_rows[case_id])
            config = build_promptfoo_config(
                config_dir=cell_root / "promptfoo" / "config",
                adapter_path=execution_adapter,
                cases_path=source_cases,
            )
            state_root = cell_root / "promptfoo" / "state"
            output_path = cell_root / "promptfoo" / "output" / PROMPTFOO_OUTPUT_BASENAME
            evaluator_root = cell_root / "evaluator"
            allowed_roots = [
                Path(config["config_path"]).parent,
                state_root,
                output_path.parent,
            ]
            denied_roots = default_denied_roots(
                vault_root=vault_root,
                evaluator_root=evaluator_root,
                op_root=cell_root,
            )
            runner = run_promptfoo_offline(
                config_path=Path(config["config_path"]),
                state_root=state_root,
                output_path=output_path,
                adapter_host_path=execution_adapter,
                expected_adapter_sha256=str(frozen["subject_adapter_sha256"]),
                timeout_s=180,
                run_id=f"{run_id}-cell-{index:04d}",
                package_owner="g4_c0_formal_batch_v1",
                op_root=cell_root,
                vault_root=vault_root,
                evaluator_root=evaluator_root,
                allowed_roots=allowed_roots,
                denied_roots=denied_roots,
                expected_case_ids=[case_id],
                expected_config_sha256=str(config["config_sha256"]),
                expected_cases_sha256=str(config["cases_sha256"]),
            )
            if runner.get("ok") is not True:
                raise C0BatchExecutionError(
                    f"C0 subject execution failed for cell {index}: {runner}"
                )
            subject_output = _extract_subject_output(
                output_path,
                public_row=public_rows[case_id],
            )
            runner_receipt_path = state_root / "promptfoo_run_receipt.v1.json"
            cell_receipts.append(
                {
                    "obligation_id": obligation["obligation_id"],
                    "family_id": cell["family_id"],
                    "public_case_id": case_id,
                    "subject_configuration": cell["subject_configuration"],
                    "seed_id": cell["seed_id"],
                    "public_prompt_sha256": hashlib.sha256(
                        str(public_rows[case_id]["public_prompt"]).encode("utf-8")
                    ).hexdigest(),
                    "raw_output_ref": str(output_path),
                    "raw_output_sha256": _raw_sha256(output_path),
                    "raw_output_bytes": output_path.stat().st_size,
                    "subject_output_sha256": subject_output["sha256"],
                    "subject_output_chars": subject_output["chars"],
                    "subject_output_schema_version": subject_output["schema_version"],
                    "runner_receipt_ref": str(runner_receipt_path),
                    "runner_receipt_sha256": _raw_sha256(runner_receipt_path),
                    "subject_invocation_performed": True,
                    "outcome_accessed": False,
                }
            )

    execution_receipt = {
        "schema_version": EXECUTION_RECEIPT_SCHEMA,
        "run_id": run_id,
        "campaign_id": batch["campaign_id"],
        "batch_id": batch["batch_id"],
        "work_key": batch["work_key"],
        "batch_manifest_sha256": batch["content_hash"],
        "logical_contract_sha256": logical_contract_sha256(contract),
        "subject_public_cases_sha256": frozen["subject_public_cases_sha256"],
        "subject_adapter_sha256": frozen["subject_adapter_sha256"],
        "promptfoo_image": PINNED_IMAGE,
        "promptfoo_image_id": PINNED_DIGEST,
        "cells": cell_receipts,
        "subject_invocation_count": len(cell_receipts),
        "distinct_execution_cells": len({cell["obligation_id"] for cell in cell_receipts}),
        "seed_role": request["unit_policy"]["seed_role"],
        "repeated_public_input_deterministic": all(
            len(
                {
                    cell["subject_output_sha256"]
                    for cell in cell_receipts
                    if cell["public_case_id"] == case_id
                }
            )
            == 1
            for case_id in {cell["public_case_id"] for cell in cell_receipts}
        ),
        "subject_output_set_sha256": canonical_sha256(
            [cell["subject_output_sha256"] for cell in cell_receipts]
        ),
        "token_usage_applicable": False,
        "vault_lock_verified_during_execution": True,
        "outcome_accessed": False,
        "evaluator_invoked": False,
        "authority": False,
        "g4_full": False,
        "g4_closed": False,
        "g5_closed": False,
        "parent_complete": False,
    }
    execution_receipt["content_hash"] = canonical_sha256(execution_receipt)
    execution_receipt_path = operation / "execution_receipt.v1.json"
    write_json(execution_receipt_path, execution_receipt)
    execution_receipt_sha256 = _raw_sha256(execution_receipt_path)
    runtime_version = "promptfoo-0.121.18"
    attempt = _attempt_receipt(
        contract=contract,
        execution_receipt_path=execution_receipt_path,
        execution_receipt_sha256=execution_receipt_sha256,
        cells=cell_receipts,
        run_id=run_id,
        runtime_version=runtime_version,
    )
    attempt_path = operation / "attempt_receipt.v1.json"
    write_json(attempt_path, attempt)
    admission = adjudicate_g4_batch_execution(
        batch_manifest=batch,
        logical_contract=contract,
        attempt_receipt=attempt,
    )
    if admission["batch_execution_accepted"] is not True:
        raise C0BatchExecutionError(f"C0 batch admission rejected: {admission['reason_codes']}")
    admission_path = operation / "batch_execution_admission.v1.json"
    write_json(admission_path, admission)
    return {
        "ok": True,
        "run_id": run_id,
        "op_root": str(operation),
        "batch_id": batch["batch_id"],
        "batch_manifest_sha256": batch["content_hash"],
        "subject_invocation_count": len(cell_receipts),
        "distinct_execution_cells": len(cell_receipts),
        "attempt_receipt_sha256": _raw_sha256(attempt_path),
        "execution_receipt_sha256": execution_receipt_sha256,
        "batch_execution_accepted": True,
        "outcome_accessed": False,
        "evaluator_invoked": False,
        "g4_closed": False,
        "parent_complete": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--op-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = execute(
        package_root=args.package_root,
        op_root=args.op_root,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
