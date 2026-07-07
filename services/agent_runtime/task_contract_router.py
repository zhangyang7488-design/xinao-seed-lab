from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.task_contract_router.v1"
SENTINEL = "SENTINEL:XINAO_TASK_CONTRACT_ROUTER_READY"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID = "p0_007_default_main_loop_trigger_bind"
P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID = "p0_008_worker_dispatch_real_receipt"
P0_010_POST_CONTINUE_AS_NEW_STATUS_REFRESH_TASK_ID = "p0_010_post_continue_as_new_status_refresh"
P0_011_V4PRO_TOOL_BEARING_EXECUTOR_POLICY_TASK_ID = "p0_011_v4pro_tool_bearing_executor_policy"
P0_012_MATURE_BIND_QUEUE_AUTOPOP_TASK_ID = "p0_012_mature_bind_queue_autopop_next_task"
P0_006_CURRENT_TASK_SOURCE_INTAKE_TASK_ID = "p0_006_current_three_text_source_intake"
P0_013_V4PRO_MATURE_BIND_EXECUTION_CONTROLLER_TASK_ID = "p0_013_v4pro_mature_bind_execution_controller"
P0_014_V4PRO_SUPERVISOR_ORCHESTRATOR_TASK_ID = "p0_014_v4pro_supervisor_orchestrator"


def canonical_repo_root() -> Path:
    # Keep the logical S path; Path.resolve() expands the Windows junction to
    # the legacy physical target and pollutes runtime evidence.
    return Path(
        os.environ.get("XINAO_CANONICAL_REPO_ROOT")
        or os.environ.get("XINAO_S_REPO_ROOT")
        or os.getcwd()
    ).absolute()


CANONICAL_REPO_ROOT = canonical_repo_root()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-")[:180] or "task-contract"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _current_333_run_index(runtime: Path) -> dict[str, Any]:
    current = _read_json(runtime / "state" / "current_333_run_index" / "latest.json")
    if (
        current.get("status") == "current_333_run_index_ready"
        and str(current.get("workflow_id") or "").strip()
        and str(current.get("workflow_run_id") or "").strip()
    ):
        return current
    return {}


def _workflow_binding(input_payload: dict[str, Any], runtime: Path) -> dict[str, Any]:
    input_workflow_id = str(input_payload.get("workflow_id") or "").strip()
    input_workflow_run_id = str(
        input_payload.get("workflow_run_id") or input_payload.get("run_id") or ""
    ).strip()
    current = _current_333_run_index(runtime)
    current_workflow_id = str(current.get("workflow_id") or "").strip()
    current_workflow_run_id = str(current.get("workflow_run_id") or "").strip()
    current_available = bool(current_workflow_id and current_workflow_run_id)
    current_alias = input_workflow_id.endswith("-current")
    missing_run = not input_workflow_run_id
    missing_workflow = not input_workflow_id
    same_workflow = bool(input_workflow_id and input_workflow_id == current_workflow_id)
    use_current = current_available and (
        missing_workflow or missing_run or current_alias or same_workflow
    )
    if use_current:
        return {
            "workflow_id": current_workflow_id,
            "workflow_run_id": current_workflow_run_id,
            "source": "current_333_run_index",
            "current_333_run_index_ref": str(
                runtime / "state" / "current_333_run_index" / "latest.json"
            ),
            "input_workflow_id": input_workflow_id,
            "input_workflow_run_id": input_workflow_run_id,
            "current_333_run_index_available": True,
        }
    return {
        "workflow_id": input_workflow_id,
        "workflow_run_id": input_workflow_run_id,
        "source": "input_payload",
        "current_333_run_index_ref": str(
            runtime / "state" / "current_333_run_index" / "latest.json"
        ),
        "input_workflow_id": input_workflow_id,
        "input_workflow_run_id": input_workflow_run_id,
        "current_333_run_index_available": current_available,
    }


def _phase_execution(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("phase_execution") if isinstance(payload.get("phase_execution"), dict) else {}


def _work_package(payload: dict[str, Any]) -> dict[str, Any]:
    phase_execution = _phase_execution(payload)
    if isinstance(phase_execution.get("work_package"), dict):
        return phase_execution["work_package"]
    return payload.get("work_package") if isinstance(payload.get("work_package"), dict) else {}


def _verification(payload: dict[str, Any]) -> list[str]:
    phase_execution = _phase_execution(payload)
    raw = (
        phase_execution.get("verification")
        if isinstance(phase_execution.get("verification"), list)
        else payload.get("verification")
    )
    if not isinstance(raw, list):
        for candidate in (
            phase_execution.get("mature_bind_task"),
            payload.get("mature_bind_task"),
            payload.get("next_mature_bind_task"),
        ):
            if isinstance(candidate, dict) and isinstance(candidate.get("verification"), list):
                raw = candidate["verification"]
                break
    if not isinstance(raw, list):
        task_package = payload.get("task_package") if isinstance(payload.get("task_package"), dict) else {}
        candidate = task_package.get("next_mature_bind_task")
        if isinstance(candidate, dict) and isinstance(candidate.get("verification"), list):
            raw = candidate["verification"]
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _mature_bind_task(payload: dict[str, Any]) -> dict[str, Any]:
    phase_execution = _phase_execution(payload)
    for value in (
        phase_execution.get("mature_bind_task"),
        payload.get("mature_bind_task"),
        payload.get("next_mature_bind_task"),
    ):
        if isinstance(value, dict):
            return value
    task_package = payload.get("task_package") if isinstance(payload.get("task_package"), dict) else {}
    value = task_package.get("next_mature_bind_task")
    return value if isinstance(value, dict) else {}


def _worker_kind(payload: dict[str, Any]) -> str:
    phase_execution = _phase_execution(payload)
    return str(
        phase_execution.get("worker_kind")
        or payload.get("worker_kind")
        or payload.get("phase_worker_kind")
        or ""
    ).strip()


def _phase_scope(payload: dict[str, Any]) -> str:
    phase_execution = _phase_execution(payload)
    return str(phase_execution.get("phase_scope") or payload.get("phase_scope") or "").strip()


def _node_id(payload: dict[str, Any]) -> str:
    return str(
        payload.get("assignment_dag_node_id")
        or payload.get("dag_next_ready_node_id")
        or _work_package(payload).get("next_ready_node_id")
        or ""
    ).strip()


def is_explicit_execution_task(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if (
        payload.get("preemptive_task_control_consumed_before_default_bootstrap") is True
        or payload.get("task_control_insert_front") is True
        or payload.get("preempt_default_bootstrap") is True
        or payload.get("explicit_user_task_control") is True
    ):
        return True
    if _mature_bind_task(payload):
        return True
    if _worker_kind(payload) == "implementation_worker" and _work_package(payload):
        node_id = _node_id(payload)
        phase_scope = _phase_scope(payload)
        if not node_id.startswith("next-frontier:"):
            return node_id.startswith("p0_") or phase_scope.startswith("p0_")
    return False


def infer_delivery_target(payload: dict[str, Any]) -> dict[str, Any]:
    mature_bind = _mature_bind_task(payload)
    if mature_bind:
        acceptance = (
            mature_bind.get("acceptance")
            if isinstance(mature_bind.get("acceptance"), dict)
            else {}
        )
        return {
            "delivery_id": safe_id(str(mature_bind.get("task_id") or "mature-bind-task")),
            "deliverable": str(mature_bind.get("deliverable") or "mature carrier binding"),
            "success_field": str(acceptance.get("success_field") or "mature_binding_ready"),
            "success_decision": str(
                acceptance.get("success_decision")
                or mature_bind.get("success_decision")
                or "accepted_for_binding"
            ),
            "failure_blocker": str(
                mature_bind.get("fallback_or_blocker") or "MATURE_BIND_TASK_BLOCKED"
            ),
            "replace_target": str(mature_bind.get("replace_target") or ""),
            "replacement": str(mature_bind.get("mature_carrier") or ""),
            "thin_adapter": str(mature_bind.get("thin_adapter") or ""),
            "default_mainline_binding": str(mature_bind.get("default_mainline_binding") or ""),
            "runtime_evidence": mature_bind.get("runtime_evidence")
            if isinstance(mature_bind.get("runtime_evidence"), list)
            else [],
        }
    text = " ".join(
        str(part)
        for part in (
            payload.get("user_goal"),
            _node_id(payload),
            _phase_scope(payload),
            _work_package(payload).get("objective"),
        )
        if part
    ).lower()
    if "p0_007_default_main_loop_trigger_bind" in text or "p0_007" in text:
        return {
            "delivery_id": P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID,
            "deliverable": "Live r9 WorkerBrief queue consumed by Temporal main tick and default trigger",
            "success_field": "default_main_loop_trigger_runtime_enforced",
            "success_decision": "accepted_for_binding",
            "failure_blocker": "DEFAULT_MAIN_LOOP_TRIGGER_NOT_EVERY_WAVE_ENFORCED",
            "replace_target": "explicit delivery contracts that skip main_execution_loop_tick",
            "replacement": "Temporal main_execution_loop_tick_activity plus default trigger activity",
        }
    if "p0_008_worker_dispatch_real_receipt" in text or "p0_008" in text:
        return {
            "delivery_id": P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID,
            "deliverable": "Worker dispatch ledger succeeds only from real WorkerBrief provider receipts",
            "success_field": "worker_dispatch_real_receipt_ready",
            "success_decision": "accepted_for_binding",
            "failure_blocker": "WORKER_DISPATCH_LEDGER_HAS_NO_REAL_PROVIDER_RECEIPT",
            "replace_target": "worker_dispatch_ledger self-written or phase1 succeeded counts",
            "replacement": "WorkerBriefQueue -> ProviderScheduler -> execute_worker_turn -> WorkerDispatchLedger receipts",
        }
    if "litellm" in text or "p0_004" in text or "provider" in text:
        return {
            "delivery_id": "p0_004_litellm_default_binding",
            "deliverable": "ProviderScheduler default route bound to LiteLLM Router",
            "success_field": "routed_by=litellm",
            "success_decision": "accepted_for_binding",
            "failure_blocker": "LITELLM_NOT_ON_DEFAULT_PATH",
            "replace_target": "ProviderScheduler hand-rolled gateway",
            "replacement": "LiteLLM Router",
        }
    return {
        "delivery_id": safe_id(_phase_scope(payload) or _node_id(payload) or str(payload.get("task_id") or "")),
        "deliverable": str(_work_package(payload).get("objective") or payload.get("user_goal") or "task delivery"),
        "success_field": "usable_artifact",
        "success_decision": "accepted_for_delivery",
        "failure_blocker": "TASK_CONTRACT_DELIVERY_BLOCKED",
        "replace_target": "",
        "replacement": "",
    }


def bounded_delivery_retry_policy() -> dict[str, Any]:
    return {
        "policy_id": "bounded_delivery_retry",
        "scope": "same_deliverable_only",
        "max_attempts": 3,
        "max_recursive_repairs": 2,
        "retry_same_deliverable_on_failure": True,
        "continue_to_next_task_only_after": [
            "accepted_for_binding",
            "accepted_for_delivery",
        ],
        "failure_terminal_state": "named_blocker",
        "next_frontier_on_failure": False,
        "empty_retry_forbidden": True,
    }


def build_contract(input_payload: dict[str, Any], *, runtime_root: str | Path = DEFAULT_RUNTIME, write: bool = True) -> dict[str, Any]:
    runtime = Path(runtime_root)
    workflow_binding = _workflow_binding(input_payload, runtime)
    explicit = is_explicit_execution_task(input_payload)
    mature_bind = _mature_bind_task(input_payload)
    delivery = infer_delivery_target(input_payload) if explicit else {}
    contract_id = safe_id(
        str(delivery.get("delivery_id") or _phase_scope(input_payload) or _node_id(input_payload) or input_payload.get("task_id") or "task")
    )
    validation_checks = {
        "explicit_task_detected": explicit,
        "work_package_present": (bool(_work_package(input_payload)) or bool(mature_bind))
        if explicit
        else True,
        "verification_present": bool(_verification(input_payload)) if explicit else True,
        "frontier_disabled_for_explicit_task": explicit,
        "mature_bind_task_has_verifier": (
            bool(mature_bind.get("verification")) if mature_bind else True
        ),
        "bounded_delivery_retry_ready": (
            bounded_delivery_retry_policy()["next_frontier_on_failure"] is False
        ),
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "execution_contract_ready" if explicit else "no_explicit_execution_contract",
        "contract_id": contract_id,
        "task_id": str(input_payload.get("task_id") or ""),
        "workflow_id": workflow_binding["workflow_id"],
        "workflow_run_id": workflow_binding["workflow_run_id"],
        "workflow_binding": workflow_binding,
        "explicit_execution_task": explicit,
        "contract_source": "task_control_or_assignment" if explicit else "none",
        "node_id": _node_id(input_payload),
        "worker_kind": _worker_kind(input_payload),
        "phase_scope": _phase_scope(input_payload),
        "work_package": {
            "objective": str(_work_package(input_payload).get("objective") or ""),
            "next_ready_node_id": str(_work_package(input_payload).get("next_ready_node_id") or ""),
        },
        "mature_bind_task": mature_bind,
        "verification": _verification(input_payload),
        "delivery_contract": delivery,
        "execution_policy": {
            "default_north_star": "user_x_to_delivered_y",
            "normal_path": "router_to_workers_to_local_executor_to_verifier_to_aaq",
            "task_shape": "one_deliverable_one_binding_one_verifier",
            "mature_bind_queue_consumed": bool(_mature_bind_task(input_payload)),
            "default_acceptance_decisions": [
                "accepted_for_binding",
                "accepted_for_delivery",
            ],
            "exception_acceptance_decision": "accepted_for_next_frontier",
            "next_frontier_default_outlet": False,
            "frontier_is_exception_path": True,
            "ledger_is_background_evidence_not_user_path": True,
            "canonical_repo_root": str(canonical_repo_root()),
            "tool_bearing_patch_executor_enabled": explicit,
            "cheap_worker_repo_mutation_allowed": explicit,
            "retry_policy": bounded_delivery_retry_policy(),
        },
        "workflow_switches": {
            "disable_default_dp_worker_pool_wave": explicit,
            "disable_source_family_wave_scheduler": explicit,
            "disable_phase0_reusable_kernel": explicit,
            "disable_wave2_mainchain_hygiene": explicit,
            "disable_source_frontier_workerpool_closure": explicit,
            "disable_next_frontier_continuation_supervisor": explicit,
            "frontier_auto_continue_allowed": not explicit,
        },
        "validation": {
            "passed": all(validation_checks.values()),
            "checks": validation_checks,
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "created_at": now_iso(),
    }
    payload["contract_digest"] = _sha256_json(payload)
    if write:
        record_path = runtime / "state" / "task_contract_router" / "records" / f"{contract_id}.json"
        latest_path = runtime / "state" / "task_contract_router" / "latest.json"
        write_json(record_path, payload)
        payload["record_path"] = str(record_path)
        payload["latest_path"] = str(latest_path)
        write_json(record_path, payload)
        write_json(latest_path, payload)
    return payload


def apply_contract_to_payload(input_payload: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(contract, dict) or contract.get("status") != "execution_contract_ready":
        return dict(input_payload)
    switches = contract.get("workflow_switches") if isinstance(contract.get("workflow_switches"), dict) else {}
    repo_root = str(canonical_repo_root())
    output = dict(input_payload)
    phase_execution = (
        dict(output.get("phase_execution"))
        if isinstance(output.get("phase_execution"), dict)
        else {}
    )
    phase_execution["repo_root"] = repo_root
    if isinstance(contract.get("mature_bind_task"), dict) and contract.get("mature_bind_task"):
        phase_execution["mature_bind_task"] = contract["mature_bind_task"]
    for key, value in switches.items():
        if key.startswith("disable_"):
            output[key] = value is True
    delivery_contract = (
        contract.get("delivery_contract") if isinstance(contract.get("delivery_contract"), dict) else {}
    )
    mature_bind = (
        contract.get("mature_bind_task") if isinstance(contract.get("mature_bind_task"), dict) else {}
    )
    output.update(
        {
            "task_contract_router_activity": contract,
            "task_contract_id": str(contract.get("contract_id") or ""),
            "execution_contract_ready": True,
            "frontier_auto_continue_allowed": switches.get("frontier_auto_continue_allowed") is True,
            "tool_bearing_patch_executor_enabled": True,
            "cheap_worker_repo_mutation_allowed": True,
            "repo_root": repo_root,
            "workspace_hint": repo_root,
            "phase_execution": phase_execution,
            "delivery_contract": delivery_contract,
            "mature_bind_task": mature_bind,
            "forbid_background_self_proof_without_deliverable": True,
        }
    )
    contract_identity_text = " ".join(
        str(value)
        for value in (
            contract.get("contract_id"),
            contract.get("phase_scope"),
            contract.get("node_id"),
            delivery_contract.get("delivery_id") if isinstance(delivery_contract, dict) else "",
            mature_bind.get("task_id") if isinstance(mature_bind, dict) else "",
        )
        if value
    )
    if P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID in contract_identity_text:
        output.update(
            {
                "force_default_main_loop_tick": True,
                "default_main_loop_trigger_bind_required": True,
                "current_worker_brief_queue_required": True,
                "bind_provider_worker_pool": True,
                "phase1_target_width": 3,
                "phase1_max_parallel_workers": 3,
                "current_worker_brief_queue_ref": str(
                    Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
                    / "state"
                    / "worker_brief_queue"
                    / "latest.json"
                ),
            }
        )
    if P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID in contract_identity_text:
        output.update(
            {
                "execute_worker_turn": True,
                "execute_codex_worker": False,
                "worker_dispatch_real_receipt_required": True,
                "worker_brief_real_receipt_required": True,
                "current_worker_brief_queue_required": True,
                "force_default_main_loop_tick": True,
                "bind_provider_worker_pool": False,
                "phase1_target_width": 0,
                "phase1_max_parallel_workers": 0,
                "disable_default_trigger_provider_worker_pool": True,
                "worker_brief_dispatch_limit": 3,
                "require_dp_receipt": True,
                "current_worker_brief_queue_ref": str(
                    Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
                    / "state"
                    / "worker_brief_queue"
                    / "latest.json"
                ),
                "worker_dispatch_ledger_real_receipt_ref": str(
                    Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
                    / "state"
                    / "worker_dispatch_ledger"
                    / "latest.json"
                ),
            }
        )
    if P0_010_POST_CONTINUE_AS_NEW_STATUS_REFRESH_TASK_ID in contract_identity_text:
        output.update(
            {
                "post_continue_as_new_status_refresh_required": True,
                "post_continue_as_new_status_refresh_write_aaq": True,
                "execute_worker_turn": False,
                "execute_codex_worker": False,
                "local_deterministic_mature_bind_service": True,
            }
        )
    if P0_011_V4PRO_TOOL_BEARING_EXECUTOR_POLICY_TASK_ID in contract_identity_text:
        output.update(
            {
                "v4pro_tool_bearing_executor_policy_required": True,
                "execute_worker_turn": False,
                "execute_codex_worker": False,
                "local_deterministic_mature_bind_service": True,
            }
        )
    if P0_012_MATURE_BIND_QUEUE_AUTOPOP_TASK_ID in contract_identity_text:
        output.update(
            {
                "mature_bind_queue_autopop_required": True,
                "mature_bind_queue_autopop_exclude_task_ids": [
                    P0_012_MATURE_BIND_QUEUE_AUTOPOP_TASK_ID
                ],
                "execute_worker_turn": False,
                "execute_codex_worker": False,
                "local_deterministic_mature_bind_service": True,
            }
        )
    if P0_006_CURRENT_TASK_SOURCE_INTAKE_TASK_ID in contract_identity_text:
        output.update(
            {
                "current_task_source_intake_required": True,
                "execute_worker_turn": False,
                "execute_codex_worker": False,
                "local_deterministic_mature_bind_service": True,
            }
        )
    if P0_013_V4PRO_MATURE_BIND_EXECUTION_CONTROLLER_TASK_ID in contract_identity_text:
        output.update(
            {
                "v4pro_mature_bind_execution_controller_required": True,
                "v4pro_mature_bind_execution_controller_send_signal": True,
                "v4pro_mature_bind_execution_controller_run_verification": True,
                "execute_worker_turn": False,
                "execute_codex_worker": False,
                "local_deterministic_mature_bind_service": True,
            }
        )
    if P0_014_V4PRO_SUPERVISOR_ORCHESTRATOR_TASK_ID in contract_identity_text:
        output.update(
            {
                "v4pro_supervisor_orchestrator_required": True,
                "v4pro_supervisor_orchestrator_run_verification": True,
                "v4pro_supervisor_orchestrator_send_signal": True,
                "execute_worker_turn": False,
                "execute_codex_worker": False,
                "local_deterministic_mature_bind_service": True,
            }
        )
    return output
