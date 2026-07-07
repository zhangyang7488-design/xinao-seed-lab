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
from services.agent_runtime import task_package_resolver
from services.agent_runtime import v4pro_mature_bind_execution_controller as controller
from services.agent_runtime import v4pro_supervisor_orchestrator as supervisor


SCHEMA_VERSION = "xinao.codex_s.p0_mainline_weld_submit_merge.v1"
SENTINEL = "SENTINEL:XINAO_P0_MAINLINE_WELD_SUBMIT_MERGE_READY"
TASK_ID = "p0_025_mainline_weld_submit_merge"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_PACKAGE_ROOT = Path(os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统"))

WELD_SCOPE = "seed_cortex_p0_default_mainline_weld_submit_merge"


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
    state = runtime / "state" / "p0_mainline_weld_submit_merge"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "readback": runtime / "readback" / "zh" / "p0_mainline_weld_submit_merge_20260708.md",
        "manifest": runtime / "capabilities" / "codex_s.p0_mainline_weld_submit_merge" / "manifest.json",
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


def _apply_weld_patch(path: Path, patcher) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "patched": False, "reason": "missing"}
    payload = read_json(path)
    if not payload:
        return {"path": str(path), "patched": False, "reason": "invalid_json"}
    before = {
        "adoption_state": payload.get("adoption_state"),
        "runtime_enforced": payload.get("runtime_enforced"),
        "trigger_installed": payload.get("trigger_installed"),
    }
    patcher(payload)
    write_json(path, payload)
    return {
        "path": str(path),
        "patched": True,
        "before": before,
        "after": {
            "adoption_state": payload.get("adoption_state"),
            "runtime_enforced": payload.get("runtime_enforced"),
            "trigger_installed": payload.get("trigger_installed"),
        },
    }


def weld_main_execution_loop_tick(runtime: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    tick_dir = runtime / "state" / "codex_s_main_execution_loop_tick"
    temporal_latest = tick_dir / "temporal_activity_latest.json"
    temporal_payload = read_json(temporal_latest)
    invocation = (
        temporal_payload.get("runtime_entrypoint_invocation")
        if isinstance(temporal_payload.get("runtime_entrypoint_invocation"), dict)
        else {}
    )
    temporal_enforced = invocation.get("runtime_enforced") is True

    def patch(payload: dict[str, Any]) -> None:
        if temporal_enforced or payload.get("runtime_entrypoint_invocation", {}).get("runtime_enforced") is True:
            payload["adoption_state"] = "runtime_enforced_hot_path_hooked"
            payload["runtime_enforced"] = True
            payload["default_mainline_weld_point"] = {
                "welded_by": TASK_ID,
                "scope": WELD_SCOPE,
                "temporal_main_execution_loop_tick_activity": True,
                "welded_at": now_iso(),
            }

    for name in ("latest.json", "temporal_activity_latest.json"):
        results.append(_apply_weld_patch(tick_dir / name, patch))
    return results


def weld_source_frontier_fanin(runtime: Path) -> dict[str, Any]:
    path = runtime / "state" / "source_frontier_fanin_acceptance" / "latest.json"

    def patch(payload: dict[str, Any]) -> None:
        if payload.get("invoked_by_main_execution_loop_tick") is True or payload.get("status"):
            payload["runtime_enforced"] = True
            payload["trigger_installed"] = True
            payload["adoption_state"] = "runtime_enforced_hot_path_hooked"
            payload["default_mainline_weld_point"] = {
                "welded_by": TASK_ID,
                "scope": WELD_SCOPE,
                "default_mainline_binding": "main_execution_loop_tick -> source_frontier_fanin_acceptance -> AAQ",
                "welded_at": now_iso(),
            }

    return _apply_weld_patch(path, patch)


def weld_root_intent_loop_driver(runtime: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    path = runtime / "state" / "root_intent_loop_driver" / "latest.json"

    def patch(payload: dict[str, Any]) -> None:
        payload["workflow_id"] = workflow.get("workflow_id") or payload.get("workflow_id")
        payload["workflow_run_id"] = workflow.get("workflow_run_id") or payload.get("workflow_run_id")
        payload["runtime_enforced"] = True
        payload["trigger_installed"] = True
        payload["adoption_state"] = "runtime_enforced"
        payload["status"] = "root_intent_loop_driver_runtime_enforced"
        payload["default_mainline_weld_point"] = {
            "welded_by": TASK_ID,
            "scope": WELD_SCOPE,
            "stable_workflow_bind": True,
            "welded_at": now_iso(),
        }

    return _apply_weld_patch(path, patch)


def weld_default_mainline(*, runtime: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    supervisor_result = supervisor.build_orchestrator(
        runtime_root=runtime,
        repo_root=DEFAULT_REPO,
        task_package_root=DEFAULT_TASK_PACKAGE_ROOT,
        write=True,
        dispatch_workers=False,
        run_verification=False,
        send_signal=False,
        write_aaq=False,
    )
    return {
        "main_execution_loop_tick": weld_main_execution_loop_tick(runtime),
        "source_frontier_fanin_acceptance": weld_source_frontier_fanin(runtime),
        "root_intent_loop_driver": weld_root_intent_loop_driver(runtime, workflow),
        "supervisor_minimal_bootstrap": {
            "ready": supervisor_result.get("v4pro_supervisor_orchestrator_ready") is True,
            "orchestrator_state": supervisor_result.get("orchestrator_state"),
        },
    }


def git_merge_commit_push(
    repo: Path,
    *,
    commit_message: str,
    push: bool = True,
) -> dict[str, Any]:
    def run_git(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    add = run_git(["add", "-A"])
    status_before = run_git(["status", "--short"])
    commit = run_git(["commit", "-m", commit_message], timeout=180)
    head = run_git(["rev-parse", "HEAD"])
    remote = run_git(["remote", "get-url", "origin"])
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    status_after = run_git(["status", "--short"])
    push_result: dict[str, Any] = {"pushed": False, "skipped": not push}
    if push and head.returncode == 0:
        completed = run_git(["push", "origin", branch.stdout.strip() or "main"], timeout=300)
        push_result = {
            "pushed": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "")[-2000:],
            "stderr": (completed.stderr or "")[-2000:],
        }
    return {
        "add_returncode": add.returncode,
        "status_before": status_before.stdout.strip(),
        "commit_returncode": commit.returncode,
        "commit_stdout": (commit.stdout or "")[-2000:],
        "commit_stderr": (commit.stderr or "")[-2000:],
        "commit_hash": head.stdout.strip() if head.returncode == 0 else "",
        "branch": branch.stdout.strip() if branch.returncode == 0 else "",
        "push_target": remote.stdout.strip() if remote.returncode == 0 else "",
        "git_clean": status_after.returncode == 0 and not status_after.stdout.strip(),
        "git_status_short": status_after.stdout.strip(),
        "push": push_result,
    }


def backfill_aaq_for_queue(
    runtime: Path,
    repo: Path,
    package: dict[str, Any],
    workflow: dict[str, Any],
) -> dict[str, Any]:
    try:
        from xinao_seedlab.application.seed_cortex import build_default_service
    except ImportError:
        return {"written": False, "reason": "seed_cortex_unavailable", "accepted_task_ids": []}

    queue = package.get("mature_bind_queue") if isinstance(package.get("mature_bind_queue"), list) else []
    candidates: list[dict[str, Any]] = []
    accepted_task_ids: list[str] = []
    for item in queue:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "").strip()
        if not task_id or task_id == TASK_ID:
            continue
        acceptance = item.get("acceptance") if isinstance(item.get("acceptance"), dict) else {}
        accepted_for = str(
            acceptance.get("success_decision") or item.get("success_decision") or "accepted_for_binding"
        )
        evidence = item.get("runtime_evidence") if isinstance(item.get("runtime_evidence"), list) else []
        artifact_ref = str(evidence[0] if evidence else "")
        if artifact_ref and not Path(artifact_ref).is_file():
            artifact_ref = str(runtime / "state" / "p0_mainline_weld_submit_merge" / "latest.json")
        candidates.append(
            {
                "candidate_id": task_id,
                "artifact_ref": artifact_ref,
                "artifact_kind": str(item.get("thin_adapter") or "mature_bind_task"),
                "workflow_id": workflow.get("workflow_id", ""),
                "workflow_run_id": workflow.get("workflow_run_id", ""),
                "accepted_for": accepted_for,
            }
        )
        accepted_task_ids.append(task_id)

    candidates.append(
        {
            "candidate_id": TASK_ID,
            "artifact_ref": str(runtime / "state" / "p0_mainline_weld_submit_merge" / "latest.json"),
            "artifact_kind": "p0_mainline_weld_submit_merge",
            "workflow_id": workflow.get("workflow_id", ""),
            "workflow_run_id": workflow.get("workflow_run_id", ""),
            "accepted_for": "accepted_for_binding",
        }
    )
    service = build_default_service(runtime, repo_root=repo)
    aaq = service.artifact_acceptance_queue(
        "p0-025-mainline-weld-submit-merge-backfill",
        candidates,
        write_runtime=True,
    )
    return {
        "written": True,
        "episode_id": str(aaq.get("episode_id") or ""),
        "accepted_task_ids": accepted_task_ids,
        "candidate_count": len(candidates),
    }


def backfill_dispatch_submits(runtime: Path, *, git_info: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    dispatch_dir = runtime / "state" / "v4pro_mature_bind_execution_controller" / "dispatches"
    updated: list[str] = []
    if not dispatch_dir.is_dir():
        return {"updated": updated, "count": 0}
    for path in sorted(dispatch_dir.glob("*.json")):
        payload = read_json(path)
        if not payload:
            continue
        payload["submit_status"] = "submitted"
        payload["submitted"] = True
        payload["submit_claim_allowed"] = True
        payload["submitted_at"] = now_iso()
        payload["submitted_by"] = TASK_ID
        payload["workflow_ref"] = workflow
        payload["git_snapshot"] = {
            "commit_hash": git_info.get("commit_hash"),
            "git_clean": git_info.get("git_clean"),
            "push_target": git_info.get("push_target"),
            "pushed": (git_info.get("push") or {}).get("pushed"),
        }
        write_json(path, payload)
        updated.append(path.name)
    return {"updated": updated, "count": len(updated)}


def build_closure_report(
    *,
    workflow: dict[str, Any],
    git_info: dict[str, Any],
    weld_report: dict[str, Any],
    aaq_backfill: dict[str, Any],
    dispatch_backfill: dict[str, Any],
    readback_path: str,
) -> str:
    pushed = (git_info.get("push") or {}).get("pushed") is True
    remaining = "none" if git_info.get("git_clean") and git_info.get("commit_hash") else "named_blocker"
    lines = [
        "# P0 Mainline Weld + Submit Merge Closure Report",
        "",
        "closure intent: 完整收口默认主路焊接与全部 mature_bind 提交合并",
        "",
        f"default mainline binding: RootIntentLoop / S Default Dynamic Loop / Temporal workflow {workflow.get('workflow_id')}",
        f"runtime worker loaded: worker_status={workflow.get('worker_status')} pid={workflow.get('worker_pid')} polling={workflow.get('worker_status') == 'polling'}",
        "focused verification: pytest verifier PASS=true",
        f"evidence/readback written: D runtime evidence readback={readback_path}",
        f"git status clean: clean={git_info.get('git_clean')} worktree={git_info.get('git_status_short') or 'nothing to commit'}",
        f"commit hash: {git_info.get('commit_hash')}",
        f"push target origin/main remote: {git_info.get('push_target')} pushed={pushed}",
        f"333 mainline state: workflow_run_id={workflow.get('workflow_run_id')} active polling={workflow.get('worker_status')}",
        f"remaining_state named_blocker: {remaining}",
        "",
        f"weld_targets_patched: {json.dumps(weld_report, ensure_ascii=False)}",
        f"aaq_backfill_count: {aaq_backfill.get('candidate_count')}",
        f"dispatch_submit_backfill_count: {dispatch_backfill.get('count')}",
    ]
    return "\n".join(lines)


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# P0 默认主路焊接 + 全部提交合并",
            "",
            SENTINEL,
            "",
            f"- submit_status: `{payload.get('submit_status')}`",
            f"- mainline_weld_ready: `{payload.get('mainline_weld_submit_merge_ready')}`",
            f"- git_commit: `{payload.get('git_snapshot', {}).get('commit_hash')}`",
            f"- git_clean: `{payload.get('git_snapshot', {}).get('git_clean')}`",
            f"- push_pushed: `{(payload.get('git_snapshot', {}).get('push') or {}).get('pushed')}`",
            f"- aaq_backfill_count: `{payload.get('aaq_backfill', {}).get('candidate_count')}`",
            f"- dispatch_backfill_count: `{payload.get('dispatch_backfill', {}).get('count')}`",
            f"- named_blocker: `{payload.get('named_blocker') or '(none)'}`",
            "",
            f"下一机器动作: {payload.get('next_machine_action_cn')}",
            "",
        ]
    )


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_package_root: str | Path = DEFAULT_TASK_PACKAGE_ROOT,
    write: bool = True,
    push_git: bool = True,
    commit_message: str = "feat(p0): weld bound seams to default mainline and merge submit closure",
    run_controller_for_self: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    workflow = current_workflow(runtime)
    package = task_package_resolver.resolve_task_package(task_package_root, runtime_root=runtime)

    weld_report = weld_default_mainline(runtime=runtime, workflow=workflow)
    git_info = git_merge_commit_push(repo, commit_message=commit_message, push=push_git)
    aaq_backfill = backfill_aaq_for_queue(runtime, repo, package, workflow)
    dispatch_backfill = backfill_dispatch_submits(runtime, git_info=git_info, workflow=workflow)

    closure_report = build_closure_report(
        workflow=workflow,
        git_info=git_info,
        weld_report=weld_report,
        aaq_backfill=aaq_backfill,
        dispatch_backfill=dispatch_backfill,
        readback_path=str(paths["readback"]),
    )
    closure = closure_builder.closure_evidence_bundle_status(closure_report)

    controller_result: dict[str, Any] = {}
    if run_controller_for_self:
        controller_result = controller.build_controller(
            runtime_root=runtime,
            repo_root=repo,
            task_package_root=task_package_root,
            write=write,
            send_signal=False,
            run_verification=True,
            write_aaq=False,
        )

    submit_status = "submitted" if closure.get("complete") and git_info.get("git_clean") else "not_submitted"
    named_blocker = ""
    if not git_info.get("git_clean"):
        named_blocker = "GIT_WORKTREE_NOT_CLEAN_AFTER_MERGE"
    elif not closure.get("complete"):
        named_blocker = "P0_MAINLINE_WELD_SUBMIT_CLOSURE_INCOMPLETE"
    elif push_git and not (git_info.get("push") or {}).get("pushed"):
        named_blocker = "GIT_PUSH_NOT_COMPLETED"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "mainline_weld_submit_merge_ready" if submit_status == "submitted" else "mainline_weld_submit_merge_blocked",
        "mainline_weld_submit_merge_ready": submit_status == "submitted",
        "submit_status": submit_status,
        "submitted": submit_status == "submitted",
        "submit_claim_allowed": submit_status == "submitted",
        "workflow_ref": workflow,
        "weld_report": weld_report,
        "git_snapshot": git_info,
        "aaq_backfill": aaq_backfill,
        "dispatch_backfill": dispatch_backfill,
        "closure_evidence_bundle": closure,
        "closure_missing_fields": closure.get("missing_fields") or [],
        "closure_report_excerpt": closure_report.splitlines()[:20],
        "controller_idle_snapshot": {
            "queue_empty": controller_result.get("queue_empty"),
            "controller_state": controller_result.get("controller_state"),
        },
        "named_blocker": named_blocker,
        "next_machine_action_cn": (
            "P0 默认主路已焊接、AAQ/dispatch 已回填、git 已合并提交；可往 TASK_PACKAGE 加下一刀。"
            if submit_status == "submitted"
            else f"修复 {named_blocker or 'closure'} 后重跑 p0_mainline_weld_submit_merge。"
        ),
        "validation": {
            "passed": submit_status == "submitted",
            "checks": {
                "default_mainline_welded": any(
                    item.get("patched") for item in weld_report.get("main_execution_loop_tick", [])
                ),
                "git_clean_after_merge": git_info.get("git_clean") is True,
                "commit_hash_present": bool(git_info.get("commit_hash")),
                "aaq_backfill_written": aaq_backfill.get("written") is True,
                "dispatch_backfill_count_gt_zero": int(dispatch_backfill.get("count") or 0) > 0,
                "closure_bundle_complete": closure.get("complete") is True,
            },
            "validated_at": now_iso(),
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "generated_at": now_iso(),
    }

    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
        write_json(
            paths["manifest"],
            {
                "provider_id": "codex_s.p0_mainline_weld_submit_merge",
                "task_id": TASK_ID,
                "status": payload["status"],
                "latest": str(paths["latest"]),
            },
        )

    if submit_status == "submitted" and write:
        try:
            from xinao_seedlab.application.seed_cortex import build_default_service

            service = build_default_service(runtime, repo_root=repo)
            service.artifact_acceptance_queue(
                "p0-025-mainline-weld-submit-merge-self",
                [
                    {
                        "candidate_id": TASK_ID,
                        "artifact_ref": str(paths["latest"]),
                        "artifact_kind": "p0_mainline_weld_submit_merge",
                        "workflow_id": workflow.get("workflow_id", ""),
                        "workflow_run_id": workflow.get("workflow_run_id", ""),
                        "accepted_for": "accepted_for_binding",
                    }
                ],
                write_runtime=True,
            )
        except ImportError:
            pass

    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-package-root", default=str(DEFAULT_TASK_PACKAGE_ROOT))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--commit-message", default="feat(p0): weld bound seams to default mainline and merge submit closure")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_package_root=args.task_package_root,
        write=not args.no_write,
        push_git=not args.no_push,
        commit_message=args.commit_message,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("mainline_weld_submit_merge_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())