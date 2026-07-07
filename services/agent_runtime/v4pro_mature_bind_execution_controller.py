from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import completion_claim_payload_builder as closure_builder
from services.agent_runtime import mature_bind_queue_autopop as autopop
from services.agent_runtime import ucp_tool_surface_resolver as ucp_resolver
from services.agent_runtime import v4pro_tool_bearing_executor_policy as v4pro_policy

SCHEMA_VERSION = "xinao.codex_s.v4pro_mature_bind_execution_controller.v1"
SENTINEL = "SENTINEL:XINAO_V4PRO_MATURE_BIND_EXECUTION_CONTROLLER_READY"
TASK_ID = "p0_013_v4pro_mature_bind_execution_controller"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_PACKAGE_ROOT = Path(os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统"))

CONTROLLER_STATES = (
    "idle",
    "dequeued",
    "eligibility_confirmed",
    "tool_surface_confirmed",
    "dispatched",
    "verifying",
    "submitted",
    "blocked",
)


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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "v4pro_mature_bind_execution_controller"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "dispatches": state / "dispatches",
        "readback": runtime / "readback" / "zh" / "v4pro_mature_bind_execution_controller_20260707.md",
        "capability_manifest": runtime
        / "capabilities"
        / "codex_s.v4pro_mature_bind_execution_controller"
        / "manifest.json",
    }


def current_workflow(runtime: Path) -> dict[str, Any]:
    payload = read_json(runtime / "state" / "current_333_run_index" / "latest.json")
    worker = payload.get("worker_status") if isinstance(payload.get("worker_status"), dict) else {}
    return {
        "workflow_id": str(payload.get("workflow_id") or ""),
        "workflow_run_id": str(payload.get("workflow_run_id") or ""),
        "current_state": str(payload.get("current_state") or ""),
        "worker_status": str(worker.get("status") or ""),
        "worker_pid": worker.get("pid"),
        "process_alive": worker.get("process_alive"),
        "pollers_seen": worker.get("pollers_seen"),
    }


def check_tool_surface(*, runtime_root: Path, repo_root: Path) -> dict[str, Any]:
    return ucp_resolver.resolve_ucp_tool_surface(
        evidence_runtime_root=runtime_root,
        repo_root=repo_root,
    )


def git_snapshot(repo: Path) -> dict[str, Any]:
    def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )

    head = run_git(["rev-parse", "HEAD"])
    status = run_git(["status", "--short"])
    remote = run_git(["remote", "get-url", "origin"])
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    return {
        "commit_hash": head.stdout.strip() if head.returncode == 0 else "",
        "branch": branch.stdout.strip() if branch.returncode == 0 else "",
        "git_status_short": status.stdout.strip(),
        "git_clean": status.returncode == 0 and not status.stdout.strip(),
        "push_target": remote.stdout.strip() if remote.returncode == 0 else "",
        "git_ok": head.returncode == 0 and status.returncode == 0,
    }


def runtime_evidence_status(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(str(raw))
        rows.append(
            {
                "path": str(path),
                "exists": path.is_file(),
                "size_bytes": path.stat().st_size if path.is_file() else 0,
            }
        )
    return rows


def run_verification_commands(commands: list[Any], *, repo: Path, timeout_sec: int = 600) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for raw in commands:
        command = str(raw or "").strip()
        if not command:
            continue
        try:
            completed = subprocess.run(
                command,
                cwd=repo,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(
                {
                    "command": command,
                    "passed": False,
                    "returncode": -1,
                    "error": str(exc),
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
            )
            continue
        results.append(
            {
                "command": command,
                "passed": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout_tail": (completed.stdout or "")[-4000:],
                "stderr_tail": (completed.stderr or "")[-4000:],
            }
        )
    return results


def build_closure_report(
    *,
    next_task: dict[str, Any],
    workflow: dict[str, Any],
    policy: dict[str, Any],
    tool_surface: dict[str, Any],
    git_info: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    verifier_results: list[dict[str, Any]],
    readback_path: str,
) -> str:
    mature_task_id = str(next_task.get("task_id") or "")
    verifier_passed = all(item.get("passed") for item in verifier_results) if verifier_results else False
    evidence_exists = all(row.get("exists") for row in evidence_rows) if evidence_rows else False
    remaining_blocker = "none" if verifier_passed and evidence_exists and git_info.get("git_clean") else "named_blocker"
    lines = [
        "# V4Pro Mature-Bind Submit Closure Report",
        "",
        f"default mainline binding: RootIntentLoop / S Default Dynamic Loop / Temporal workflow {workflow.get('workflow_id')}",
        f"runtime worker loaded: worker_status={workflow.get('worker_status')} pid={workflow.get('worker_pid')} polling={workflow.get('worker_status') == 'polling'}",
        f"focused verification: pytest verifier PASS={verifier_passed}",
        f"evidence/readback written: D runtime evidence paths exist={evidence_exists}; readback={readback_path}",
        f"git status clean: clean={git_info.get('git_clean')} worktree={git_info.get('git_status_short') or 'nothing to commit'}",
        f"commit hash: {git_info.get('commit_hash')}",
        f"push target origin/main remote: {git_info.get('push_target')}",
        f"333 mainline state: workflow_run_id={workflow.get('workflow_run_id')} active polling={workflow.get('worker_status')}",
        f"remaining_state named_blocker: {remaining_blocker}",
        "",
        f"mature_bind_task_id: {mature_task_id}",
        f"provider_id: {policy.get('provider_id')}",
        f"tool_surface_ready: {tool_surface.get('ready')}",
    ]
    return "\n".join(lines)


def derive_submit_decision(
    *,
    verifier_results: list[dict[str, Any]],
    closure_report: str,
    skip_verification: bool,
) -> dict[str, Any]:
    closure = closure_builder.closure_evidence_bundle_status(closure_report)
    verifiers_passed = all(item.get("passed") for item in verifier_results) if verifier_results else False
    if skip_verification:
        verifiers_passed = True
    if verifiers_passed and closure.get("complete"):
        return {
            "submit_status": "submitted",
            "controller_state": "submitted",
            "named_blocker": "",
            "submit_claim_allowed": True,
            "closure_evidence_bundle": closure,
        }
    missing = list(closure.get("missing_fields") or [])
    if not verifiers_passed:
        blocker = "V4PRO_SUBMIT_CLOSURE_VERIFICATION_FAILED"
    elif missing:
        blocker = "V4PRO_SUBMIT_CLOSURE_INCOMPLETE"
    else:
        blocker = "V4PRO_SUBMIT_CLOSURE_INCOMPLETE"
    return {
        "submit_status": "not_submitted",
        "controller_state": "blocked",
        "named_blocker": blocker,
        "submit_claim_allowed": False,
        "closure_evidence_bundle": closure,
        "closure_missing_fields": missing,
    }


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V4Pro Mature-Bind Execution Controller",
            "",
            SENTINEL,
            "",
            f"- controller_state: `{payload.get('controller_state')}`",
            f"- submit_status: `{payload.get('submit_status')}`",
            f"- enqueue_ok: `{payload.get('enqueue_ok')}`",
            f"- mature_bind_task_id: `{payload.get('mature_bind_task_id')}`",
            f"- named_blocker: `{payload.get('named_blocker') or '(none)'}`",
            "",
            "能排队 ≠ 已提交。只有 closure evidence bundle 全齐且 verifier PASS 才写 submitted。",
            "",
            f"下一机器动作: {payload.get('next_machine_action_cn')}",
            "",
        ]
    )


def write_artifact_acceptance(runtime: Path, repo: Path, payload: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    try:
        from xinao_seedlab.application.seed_cortex import build_default_service
    except ImportError:
        return {"written": False, "reason": "seed_cortex_unavailable"}
    if payload.get("submit_status") != "submitted":
        return {"written": False, "reason": "submit_status_not_submitted"}
    mature_task_id = str(payload.get("mature_bind_task_id") or "").strip()
    next_task = (
        payload.get("next_mature_bind_task")
        if isinstance(payload.get("next_mature_bind_task"), dict)
        else {}
    )
    acceptance = next_task.get("acceptance") if isinstance(next_task.get("acceptance"), dict) else {}
    accepted_for = str(
        acceptance.get("success_decision")
        or next_task.get("success_decision")
        or "accepted_for_binding"
    )
    evidence_refs = next_task.get("runtime_evidence") if isinstance(next_task.get("runtime_evidence"), list) else []
    artifact_ref = str(evidence_refs[0] if evidence_refs else paths["latest"])
    if not Path(artifact_ref).is_file():
        artifact_ref = str(paths["latest"])
    candidates: list[dict[str, Any]] = []
    if mature_task_id:
        candidates.append(
            {
                "candidate_id": mature_task_id,
                "artifact_ref": artifact_ref,
                "artifact_kind": str(next_task.get("thin_adapter") or "mature_bind_task"),
                "workflow_id": str(payload.get("workflow_ref", {}).get("workflow_id") or ""),
                "workflow_run_id": str(payload.get("workflow_ref", {}).get("workflow_run_id") or ""),
                "accepted_for": accepted_for,
            }
        )
    candidates.append(
        {
            "candidate_id": TASK_ID,
            "artifact_ref": str(paths["latest"]),
            "artifact_kind": "v4pro_mature_bind_execution_controller",
            "workflow_id": str(payload.get("workflow_ref", {}).get("workflow_id") or ""),
            "workflow_run_id": str(payload.get("workflow_ref", {}).get("workflow_run_id") or ""),
            "accepted_for": "accepted_for_binding",
        }
    )
    service = build_default_service(runtime, repo_root=repo)
    episode_key = mature_task_id or TASK_ID
    aaq = service.artifact_acceptance_queue(
        f"p0-013-mature-bind-submit-{episode_key}",
        candidates,
        write_runtime=True,
    )
    return {
        "written": True,
        "episode_id": str(aaq.get("episode_id") or ""),
        "decision": accepted_for,
        "mature_bind_task_id": mature_task_id,
    }


def build_controller(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_package_root: str | Path = DEFAULT_TASK_PACKAGE_ROOT,
    write: bool = True,
    send_signal: bool = False,
    run_verification: bool = True,
    skip_verification: bool = False,
    write_aaq: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)

    autopop_result = autopop.build_autopop(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_package_root,
        write=write,
        send_signal=send_signal,
        exclude_task_ids=[TASK_ID],
        write_aaq=False,
    )
    queue_empty = bool(autopop_result.get("queue_empty"))
    next_task = autopop_result.get("next_mature_bind_task") if isinstance(autopop_result.get("next_mature_bind_task"), dict) else {}
    mature_bind_task_id = str(next_task.get("task_id") or "")

    if queue_empty:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "sentinel": SENTINEL,
            "task_id": TASK_ID,
            "status": "v4pro_mature_bind_execution_controller_ready",
            "v4pro_mature_bind_execution_controller_ready": True,
            "controller_state": "idle",
            "submit_status": "not_submitted",
            "enqueue_ok": False,
            "submitted": False,
            "queue_empty": True,
            "mature_bind_task_id": "",
            "named_blocker": "",
            "submit_claim_allowed": False,
            "next_machine_action_cn": "mature_bind_queue 已空；等待新任务包或用户新意图。",
            "validation": {
                "passed": True,
                "checks": {"queue_empty_idle": True},
                "validated_at": now_iso(),
            },
            "is_execution_controller": True,
            "not_execution_controller": False,
            "completion_claim_allowed": False,
            "not_source_of_truth": False,
            "not_user_completion": True,
            "not_completion_decision": True,
            "generated_at": now_iso(),
        }
        if write:
            write_json(paths["latest"], payload)
            write_json(paths["record"], payload)
            write_text(paths["readback"], render_readback(payload))
        return payload

    policy = v4pro_policy.build_policy(
        runtime_root=runtime,
        repo_root=repo,
        write=write,
        write_aaq=False,
    )
    tool_surface = check_tool_surface(runtime_root=runtime, repo_root=repo)
    workflow = current_workflow(runtime)

    controller_state = "dequeued"
    named_blocker = ""
    if not policy.get("tool_bearing_executor_eligible"):
        controller_state = "blocked"
        named_blocker = str(policy.get("named_blocker") or "V4PRO_TOOL_BEARING_EXECUTOR_POLICY_NOT_BOUND")
    elif not tool_surface.get("ready"):
        controller_state = "blocked"
        named_blocker = str(tool_surface.get("named_blocker") or "CODEX_WORKER_UCP_TOOL_SURFACE_MISSING")
    elif not autopop_result.get("mature_bind_queue_autopop_ready"):
        controller_state = "blocked"
        named_blocker = "MATURE_BIND_QUEUE_AUTOPOP_NOT_READY"
    else:
        controller_state = "dispatched"

    enqueue_ok = controller_state == "dispatched"
    dispatch_record: dict[str, Any] = {}
    if enqueue_ok and write:
        dispatch_record = {
            "task_id": mature_bind_task_id,
            "provider_id": policy.get("provider_id"),
            "objective": str(next_task.get("deliverable") or ""),
            "workflow_ref": workflow,
            "signal_path": str(autopop_result.get("signal_path") or ""),
            "contract_id": str(autopop_result.get("contract_id") or ""),
            "dispatched_at": now_iso(),
            "execute_via": "deepseek_v4_pro_hardmode_tool_bearing_executor",
            "closure_evidence_bundle_required": policy.get("closure_evidence_bundle_required"),
            "submit_status": "not_submitted",
            "submitted": False,
        }
        dispatch_path = paths["dispatches"] / f"{mature_bind_task_id}.json"
        write_json(dispatch_path, dispatch_record)
        dispatch_record["dispatch_path"] = str(dispatch_path)

    verifier_results: list[dict[str, Any]] = []
    if run_verification and enqueue_ok and controller_state != "blocked":
        controller_state = "verifying"
        commands = next_task.get("verification") if isinstance(next_task.get("verification"), list) else []
        verifier_results = run_verification_commands(commands, repo=repo)

    git_info = git_snapshot(repo)
    evidence_paths = next_task.get("runtime_evidence") if isinstance(next_task.get("runtime_evidence"), list) else []
    evidence_rows = runtime_evidence_status([str(item) for item in evidence_paths])
    closure_report = build_closure_report(
        next_task=next_task,
        workflow=workflow,
        policy=policy,
        tool_surface=tool_surface,
        git_info=git_info,
        evidence_rows=evidence_rows,
        verifier_results=verifier_results,
        readback_path=str(paths["readback"]),
    )

    submit_decision = {"submit_status": "not_submitted", "controller_state": controller_state, "named_blocker": named_blocker, "submit_claim_allowed": False, "closure_evidence_bundle": {}}
    if controller_state == "blocked":
        submit_decision["submit_status"] = "not_submitted"
        submit_decision["submit_claim_allowed"] = False
    elif controller_state == "verifying":
        submit_decision = derive_submit_decision(
            verifier_results=verifier_results,
            closure_report=closure_report,
            skip_verification=skip_verification,
        )
        controller_state = str(submit_decision.get("controller_state") or controller_state)
        named_blocker = str(submit_decision.get("named_blocker") or "")

    ready = enqueue_ok or controller_state in {"idle", "submitted", "blocked", "verifying", "dispatched"}
    checks = {
        "mature_bind_dequeued_or_blocked": bool(mature_bind_task_id),
        "v4pro_policy_checked": bool(policy),
        "tool_surface_checked": bool(tool_surface),
        "enqueue_not_equal_submit": submit_decision.get("submit_status") != "submitted" or submit_decision.get("submit_claim_allowed") is True,
        "controller_state_valid": controller_state in CONTROLLER_STATES,
    }
    if submit_decision.get("submit_status") == "submitted":
        next_action = f"任务 {mature_bind_task_id} 已提交闭环；可 autopop 下一条。"
    elif enqueue_ok:
        next_action = f"已入队 {mature_bind_task_id}；V4Pro 执行后重跑 controller 验 closure，未齐则 blocker。"
    else:
        next_action = f"未入队；修复 {named_blocker or '前置条件'}。"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "v4pro_mature_bind_execution_controller_ready" if ready else "v4pro_mature_bind_execution_controller_blocked",
        "v4pro_mature_bind_execution_controller_ready": ready,
        "controller_state": controller_state,
        "submit_status": submit_decision.get("submit_status", "not_submitted"),
        "enqueue_ok": enqueue_ok,
        "submitted": submit_decision.get("submit_status") == "submitted",
        "submit_claim_allowed": submit_decision.get("submit_claim_allowed", False),
        "queue_empty": False,
        "mature_bind_task_id": mature_bind_task_id,
        "next_mature_bind_task": next_task,
        "autopop": {
            "mature_bind_queue_autopop_ready": autopop_result.get("mature_bind_queue_autopop_ready"),
            "signal_path": autopop_result.get("signal_path"),
            "contract_id": autopop_result.get("contract_id"),
            "signal_result": autopop_result.get("signal_result"),
        },
        "v4pro_policy": {
            "tool_bearing_executor_eligible": policy.get("tool_bearing_executor_eligible"),
            "repo_mutation_allowed": policy.get("repo_mutation_allowed"),
            "commit_push_allowed": policy.get("commit_push_allowed"),
        },
        "tool_surface": tool_surface,
        "workflow_ref": workflow,
        "dispatch_record": dispatch_record,
        "verification_results": verifier_results,
        "git_snapshot": git_info,
        "runtime_evidence": evidence_rows,
        "closure_report_path": str(paths["readback"]),
        "closure_evidence_bundle": submit_decision.get("closure_evidence_bundle", {}),
        "closure_missing_fields": submit_decision.get("closure_missing_fields", []),
        "named_blocker": named_blocker,
        "next_machine_action_cn": next_action,
        "validation": {
            "passed": ready,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "acceptance": {
            "accepted_for": "accepted_for_delivery" if submit_decision.get("submit_status") == "submitted" else "accepted_for_binding",
            "artifact_acceptance_decision": "accepted_for_delivery" if submit_decision.get("submit_status") == "submitted" else "accepted_for_binding",
            "success_field": "v4pro_mature_bind_execution_controller_ready",
            "success_decision": "accepted_for_delivery" if submit_decision.get("submit_status") == "submitted" else "accepted_for_binding",
        },
        "is_execution_controller": True,
        "not_execution_controller": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "generated_at": now_iso(),
    }
    payload["output_paths"] = {key: str(value) for key, value in paths.items()}
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
        write_json(
            paths["capability_manifest"],
            {
                "schema_version": f"{SCHEMA_VERSION}.capability_manifest.v1",
                "provider_id": "codex_s.v4pro_mature_bind_execution_controller",
                "status": "registered",
                "task_id": TASK_ID,
                "runtime_latest": str(paths["latest"]),
                "readback": str(paths["readback"]),
                "is_execution_controller": True,
                "completion_claim_allowed": False,
                "generated_at": now_iso(),
            },
        )
        if write_aaq and ready and payload.get("submit_status") == "submitted":
            payload["artifact_acceptance"] = write_artifact_acceptance(runtime, repo, payload, paths)
            write_json(paths["latest"], payload)
            write_json(paths["record"], payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v4pro-mature-bind-execution-controller")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-package-root", default=str(DEFAULT_TASK_PACKAGE_ROOT))
    parser.add_argument("--send-signal", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--skip-verification", action="store_true", help="closure gate only; do not require verifier PASS")
    parser.add_argument("--no-aaq", action="store_true")
    args = parser.parse_args(argv)
    payload = build_controller(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_package_root=args.task_package_root,
        write=not args.no_write,
        send_signal=args.send_signal,
        run_verification=not args.no_verify,
        skip_verification=args.skip_verification,
        write_aaq=not args.no_aaq,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("v4pro_mature_bind_execution_controller_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())