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
        return []
    return [str(item) for item in raw if str(item).strip()]


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
    if _worker_kind(payload) == "implementation_worker" and _work_package(payload):
        node_id = _node_id(payload)
        phase_scope = _phase_scope(payload)
        if not node_id.startswith("next-frontier:"):
            return node_id.startswith("p0_") or phase_scope.startswith("p0_")
    return False


def infer_delivery_target(payload: dict[str, Any]) -> dict[str, Any]:
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


def build_contract(input_payload: dict[str, Any], *, runtime_root: str | Path = DEFAULT_RUNTIME, write: bool = True) -> dict[str, Any]:
    runtime = Path(runtime_root)
    explicit = is_explicit_execution_task(input_payload)
    delivery = infer_delivery_target(input_payload) if explicit else {}
    contract_id = safe_id(
        str(delivery.get("delivery_id") or _phase_scope(input_payload) or _node_id(input_payload) or input_payload.get("task_id") or "task")
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "execution_contract_ready" if explicit else "no_explicit_execution_contract",
        "contract_id": contract_id,
        "task_id": str(input_payload.get("task_id") or ""),
        "workflow_id": str(input_payload.get("workflow_id") or ""),
        "workflow_run_id": str(input_payload.get("workflow_run_id") or ""),
        "explicit_execution_task": explicit,
        "contract_source": "task_control_or_assignment" if explicit else "none",
        "node_id": _node_id(input_payload),
        "worker_kind": _worker_kind(input_payload),
        "phase_scope": _phase_scope(input_payload),
        "work_package": {
            "objective": str(_work_package(input_payload).get("objective") or ""),
            "next_ready_node_id": str(_work_package(input_payload).get("next_ready_node_id") or ""),
        },
        "verification": _verification(input_payload),
        "delivery_contract": delivery,
        "execution_policy": {
            "default_north_star": "user_x_to_delivered_y",
            "normal_path": "router_to_workers_to_local_executor_to_verifier_to_aaq",
            "frontier_is_exception_path": True,
            "ledger_is_background_evidence_not_user_path": True,
            "canonical_repo_root": str(canonical_repo_root()),
            "tool_bearing_patch_executor_enabled": explicit,
            "cheap_worker_repo_mutation_allowed": explicit,
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
            "passed": True,
            "checks": {
                "explicit_task_detected": explicit,
                "work_package_present": bool(_work_package(input_payload)) if explicit else True,
                "verification_present": bool(_verification(input_payload)) if explicit else True,
                "frontier_disabled_for_explicit_task": explicit,
            },
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
    for key, value in switches.items():
        if key.startswith("disable_"):
            output[key] = value is True
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
            "delivery_contract": contract.get("delivery_contract") if isinstance(contract.get("delivery_contract"), dict) else {},
        }
    )
    return output
