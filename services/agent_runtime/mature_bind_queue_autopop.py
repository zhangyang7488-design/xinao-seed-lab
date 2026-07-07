from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import task_contract_router
from services.agent_runtime import task_package_resolver


SCHEMA_VERSION = "xinao.codex_s.mature_bind_queue_autopop.v1"
SENTINEL = "SENTINEL:XINAO_MATURE_BIND_QUEUE_AUTOPOP_READY"
TASK_ID = "p0_012_mature_bind_queue_autopop_next_task"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_PACKAGE_ROOT = Path(os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统"))


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "mature_bind_queue_autopop"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "signal": runtime / "state" / "task_control_signals" / "mature_bind_queue_autopop_next_task.json",
        "capability_manifest": runtime
        / "capabilities"
        / "codex_s.mature_bind_queue_autopop"
        / "manifest.json",
    }


def current_workflow(runtime: Path) -> dict[str, Any]:
    payload = read_json(runtime / "state" / "current_333_run_index" / "latest.json")
    return {
        "workflow_id": str(payload.get("workflow_id") or ""),
        "workflow_run_id": str(payload.get("workflow_run_id") or ""),
        "task_queue": "xinao-codex-task-default",
    }


def select_next_task(package: dict[str, Any], exclude_task_ids: set[str]) -> dict[str, Any]:
    queue = package.get("mature_bind_queue") if isinstance(package.get("mature_bind_queue"), list) else []
    terminal = task_package_resolver.TERMINAL_MATURE_BIND_DECISIONS
    for item in queue:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "").strip()
        if not task_id or task_id in exclude_task_ids:
            continue
        if str(item.get("status") or "").strip() == "ready":
            return item
    for item in queue:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "").strip()
        status = str(item.get("status") or "").strip()
        if task_id and task_id not in exclude_task_ids and status not in terminal and status != "blocked":
            return item
    return {}


def task_signal_for(next_task: dict[str, Any], workflow_ref: dict[str, Any], runtime: Path) -> dict[str, Any]:
    task_id = str(next_task.get("task_id") or "")
    return {
        "task_id": "xinao_seed_cortex_phase0_20260701",
        "route_profile": "seed_cortex_phase0",
        "source_kind": "mature_bind_queue_autopop",
        "explicit_user_task_control": True,
        "assignment_dag_node_id": task_id,
        "dag_next_ready_node_id": task_id,
        "wave_id": f"{task_id}-autopop-{now_iso().replace(':', '').replace('+', '-')}",
        "worker_kind": "implementation_worker",
        "phase_scope": task_id,
        "work_package": {
            "objective": str(next_task.get("deliverable") or ""),
            "next_ready_node_id": task_id,
        },
        "mature_bind_task": next_task,
        "verification": next_task.get("verification") if isinstance(next_task.get("verification"), list) else [],
        "workflow_id": workflow_ref.get("workflow_id", ""),
        "workflow_run_id": workflow_ref.get("workflow_run_id", ""),
        "task_queue": workflow_ref.get("task_queue", "xinao-codex-task-default"),
        "runtime_root": str(runtime),
        "execute_worker_turn": False,
        "execute_codex_worker": False,
        "bind_provider_worker_pool": False,
        "phase1_target_width": 0,
        "phase1_max_parallel_workers": 0,
        "disable_default_dp_worker_pool_wave": True,
        "disable_source_family_wave_scheduler": True,
        "disable_phase0_reusable_kernel": True,
        "disable_wave2_mainchain_hygiene": True,
        "disable_source_frontier_workerpool_closure": True,
        "disable_next_frontier_continuation_supervisor": True,
        "frontier_auto_continue_allowed": False,
    }


def write_artifact_acceptance(runtime: Path, repo: Path, payload: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    try:
        from xinao_seedlab.application.seed_cortex import build_default_service
    except ImportError:
        return {"written": False, "reason": "seed_cortex_unavailable"}
    service = build_default_service(runtime, repo_root=repo)
    aaq = service.artifact_acceptance_queue(
        "p0-012-mature-bind-queue-autopop-accepted",
        [
            {
                "candidate_id": TASK_ID,
                "artifact_ref": str(paths["latest"]),
                "artifact_kind": "mature_bind_queue_autopop",
                "workflow_id": str(payload.get("workflow_ref", {}).get("workflow_id") or ""),
                "workflow_run_id": str(payload.get("workflow_ref", {}).get("workflow_run_id") or ""),
                "accepted_for": "accepted_for_binding",
            }
        ],
        write_runtime=True,
    )
    return {
        "written": True,
        "episode_id": str(aaq.get("episode_id") or ""),
        "decision": "accepted_for_binding",
    }


def signal_workflow(workflow_id: str, signal_path: Path) -> dict[str, Any]:
    if not workflow_id:
        return {"sent": False, "reason": "workflow_id_missing"}
    completed = subprocess.run(
        [
            "temporal",
            "workflow",
            "signal",
            "--address",
            "127.0.0.1:7233",
            "--workflow-id",
            workflow_id,
            "--name",
            "continue_same_task",
            "--input-file",
            str(signal_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return {
        "sent": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def build_autopop(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_package_root: str | Path = DEFAULT_TASK_PACKAGE_ROOT,
    write: bool = True,
    send_signal: bool = False,
    exclude_task_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    write_aaq: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    package = task_package_resolver.resolve_task_package(
        task_package_root,
        runtime_root=runtime,
    )
    excluded = {str(item).strip() for item in (exclude_task_ids or []) if str(item).strip()}
    next_task = select_next_task(package, excluded)
    workflow_ref = current_workflow(runtime)
    paths = output_paths(runtime)
    signal_payload = task_signal_for(next_task, workflow_ref, runtime) if next_task else {}
    routed_payload: dict[str, Any] = {}
    contract: dict[str, Any] = {}
    if signal_payload:
        contract = task_contract_router.build_contract(signal_payload, runtime_root=runtime, write=write)
        routed_payload = task_contract_router.apply_contract_to_payload(signal_payload, contract)
        routed_payload["task_control_insert_front"] = True
        routed_payload["preempt_default_bootstrap"] = True
    signal_result = {"sent": False, "reason": "send_signal_false"}
    if write and routed_payload:
        write_json(paths["signal"], routed_payload)
    if send_signal and routed_payload:
        signal_result = signal_workflow(workflow_ref["workflow_id"], paths["signal"])
    checks = {
        "task_package_resolved": bool(package.get("mature_bind_queue_ready")),
        "next_task_selected_or_queue_empty": bool(next_task) or not package.get("next_mature_bind_task_id"),
        "workflow_ref_bound_or_queue_empty": bool(workflow_ref.get("workflow_id")) or not next_task,
        "contract_ready_or_queue_empty": contract.get("status") == "execution_contract_ready" or not next_task,
        "next_frontier_default_outlet_disabled": True,
    }
    ready = all(checks.values())
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "mature_bind_queue_autopop_ready" if ready else "mature_bind_queue_autopop_blocked",
        "mature_bind_queue_autopop_ready": ready,
        "queue_empty": not bool(next_task),
        "exclude_task_ids": sorted(excluded),
        "next_mature_bind_task_id": str(next_task.get("task_id") or ""),
        "next_mature_bind_task": next_task,
        "workflow_ref": workflow_ref,
        "contract_id": str(contract.get("contract_id") or ""),
        "signal_path": str(paths["signal"]) if routed_payload else "",
        "auto_continue_same_workflow": bool(ready and routed_payload and not send_signal),
        "auto_continue_same_task_signal": routed_payload if ready and routed_payload and not send_signal else {},
        "signal_result": signal_result,
        "validation": {
            "passed": ready,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "acceptance": {
            "accepted_for": "accepted_for_binding",
            "artifact_acceptance_decision": "accepted_for_binding",
            "success_field": "mature_bind_queue_autopop_ready",
            "success_decision": "accepted_for_binding",
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    payload["output_paths"] = {key: str(value) for key, value in paths.items()}
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_json(
            paths["capability_manifest"],
            {
                "schema_version": f"{SCHEMA_VERSION}.capability_manifest.v1",
                "provider_id": "codex_s.mature_bind_queue_autopop",
                "status": "registered",
                "task_id": TASK_ID,
                "runtime_latest": str(paths["latest"]),
                "signal": str(paths["signal"]),
                "completion_claim_allowed": False,
                "not_execution_controller": True,
                "generated_at": now_iso(),
            },
        )
        if write_aaq and ready:
            payload["artifact_acceptance"] = write_artifact_acceptance(runtime, repo, payload, paths)
            write_json(paths["latest"], payload)
            write_json(paths["record"], payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mature-bind-queue-autopop")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-package-root", default=str(DEFAULT_TASK_PACKAGE_ROOT))
    parser.add_argument("--send-signal", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--exclude-task-id", action="append", default=[])
    parser.add_argument("--no-aaq", action="store_true")
    args = parser.parse_args(argv)
    payload = build_autopop(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_package_root=args.task_package_root,
        write=not args.no_write,
        send_signal=args.send_signal,
        exclude_task_ids=args.exclude_task_id,
        write_aaq=not args.no_aaq,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("mature_bind_queue_autopop_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
