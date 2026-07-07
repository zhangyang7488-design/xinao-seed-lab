from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from services.agent_runtime import bounded_result_wait
from services.agent_runtime import codex_s_direct_worker_lane as direct_lane
from services.agent_runtime import codex_s_live_backend_watch as live_watch
from services.agent_runtime import task_package_resolver
from services.agent_runtime import ucp_tool_surface_resolver as ucp_resolver
from services.agent_runtime import v4pro_mature_bind_execution_controller as exec_controller
from services.agent_runtime import v4pro_tool_bearing_executor_policy as v4pro_policy


SCHEMA_VERSION = "xinao.codex_s.v4pro_supervisor_orchestrator.v1"
SENTINEL = "SENTINEL:XINAO_V4PRO_SUPERVISOR_ORCHESTRATOR_READY"
TASK_ID = "p0_014_v4pro_supervisor_orchestrator"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_PACKAGE_ROOT = Path(os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统"))

MATURE_ARCHITECTURE_REFS = [
    {
        "pattern": "langgraph_supervisor",
        "source": "LangGraph / LangChain multi-agent supervisor",
        "url": "https://docs.langchain.com/oss/python/langchain/multi-agent/subagents-personal-assistant",
        "claim": "One supervisor brain routes to specialized workers and fans results back in.",
    },
    {
        "pattern": "temporal_durable_orchestration",
        "source": "Temporal durable workflow + activity chain",
        "url": "https://temporal.io/blog/of-course-you-can-build-dynamic-ai-agents-with-temporal",
        "claim": "Workflow owns state migration; activities are idempotent tool/worker steps.",
    },
    {
        "pattern": "kubernetes_reconcile_loop",
        "source": "Kubernetes controller reconcile loop",
        "url": "https://kubernetes.io/docs/concepts/architecture/controller/",
        "claim": "Observe desired vs actual state and keep reconciling until aligned or named_blocker.",
    },
]

SUPERVISOR_PROVIDER_ID = "deepseek_v4_pro"
WORKER_POOL = {
    "qwen_prepaid_cheap_worker": {
        "provider_cli": "qwen",
        "role": "cheap_parallel_worker",
        "modes": ["draft", "eval", "extraction"],
        "may_mutate_repo": False,
        "may_bind_hot_path": False,
    },
    "deepseek_v4_pro": {
        "provider_cli": "dp",
        "role": "supervisor_hard_executor",
        "modes": ["audit", "contradiction"],
        "may_mutate_repo": True,
        "may_bind_hot_path": True,
    },
}

HOT_PATH_BIND_ALLOWLIST = (
    "state/v4pro_supervisor_orchestrator/latest.json",
    "state/v4pro_mature_bind_execution_controller/latest.json",
    "state/mature_bind_queue_autopop/latest.json",
    "state/v4pro_tool_bearing_executor_policy/latest.json",
    "state/bounded_result_wait/latest.json",
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
    state = runtime / "state" / "v4pro_supervisor_orchestrator"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "hot_path_binds": state / "hot_path_binds",
        "worker_dispatches": state / "worker_dispatches",
        "readback": runtime / "readback" / "zh" / "v4pro_supervisor_orchestrator_20260707.md",
        "capability_manifest": runtime
        / "capabilities"
        / "codex_s.v4pro_supervisor_orchestrator"
        / "manifest.json",
    }


def assess_chain_health(runtime: Path) -> dict[str, Any]:
    current = read_json(runtime / "state" / "current_333_run_index" / "latest.json")
    bounded = read_json(runtime / "state" / "bounded_result_wait" / "latest.json")
    continuity = read_json(runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json")
    controller = read_json(runtime / "state" / "v4pro_mature_bind_execution_controller" / "latest.json")
    worker = current.get("worker_status") if isinstance(current.get("worker_status"), dict) else {}
    blockers = continuity.get("active_blockers") if isinstance(continuity.get("active_blockers"), list) else []
    return {
        "workflow_id": str(current.get("workflow_id") or ""),
        "workflow_run_id": str(current.get("workflow_run_id") or ""),
        "worker_polling": str(worker.get("status") or "") == "polling",
        "bounded_result_wait_ready": bounded.get("bounded_result_wait_ready") is True,
        "bounded_named_blocker": str(bounded.get("named_blocker") or ""),
        "continuity_validation_passed": continuity.get("validation", {}).get("passed") is True,
        "continuity_blocker_count": len(blockers),
        "execution_controller_state": str(controller.get("controller_state") or ""),
        "execution_submit_status": str(controller.get("submit_status") or ""),
        "execution_enqueue_ok": controller.get("enqueue_ok") is True,
        "needs_chain_repair": (
            not continuity.get("validation", {}).get("passed")
            or bool(bounded.get("named_blocker"))
            or str(worker.get("status") or "") != "polling"
        ),
        "needs_mature_bind_tick": controller.get("queue_empty") is not True
        and controller.get("submit_status") != "submitted",
    }


def plan_orchestration(health: dict[str, Any], *, dispatch_workers: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if health.get("needs_chain_repair"):
        actions.append({"action": "chain_repair", "owner": SUPERVISOR_PROVIDER_ID, "priority": 1})
    actions.append({"action": "execution_controller_tick", "owner": SUPERVISOR_PROVIDER_ID, "priority": 2})
    if health.get("needs_mature_bind_tick"):
        actions.append({"action": "mature_bind_submit_gate", "owner": SUPERVISOR_PROVIDER_ID, "priority": 3})
    if dispatch_workers:
        actions.append(
            {
                "action": "dispatch_worker",
                "owner": SUPERVISOR_PROVIDER_ID,
                "worker": "qwen_prepaid_cheap_worker",
                "mode": "eval",
                "priority": 4,
            }
        )
        actions.append(
            {
                "action": "dispatch_worker",
                "owner": SUPERVISOR_PROVIDER_ID,
                "worker": "deepseek_v4_pro",
                "mode": "audit",
                "priority": 5,
            }
        )
    actions.append({"action": "hot_path_self_bind", "owner": SUPERVISOR_PROVIDER_ID, "priority": 6})
    return sorted(actions, key=lambda item: int(item.get("priority") or 0))


def repair_chain(*, runtime: Path, repo: Path) -> dict[str, Any]:
    bounded = bounded_result_wait.build_bounded_result_wait(
        runtime_root=runtime,
        repo_root=repo,
        write=True,
        write_aaq=False,
    )
    continuity = bounded.get("continuity_router") if isinstance(bounded.get("continuity_router"), dict) else {}
    driver = bounded.get("root_intent_loop_driver") if isinstance(bounded.get("root_intent_loop_driver"), dict) else {}
    return {
        "bounded_result_wait_ready": bounded.get("bounded_result_wait_ready") is True,
        "continuity_regenerated": continuity.get("validation_passed") is True,
        "driver_rebound": driver.get("rebound") is True,
        "named_blocker": str(bounded.get("named_blocker") or ""),
    }


def run_execution_controller_tick(
    *,
    runtime: Path,
    repo: Path,
    task_package_root: Path,
    send_signal: bool,
    run_verification: bool,
) -> dict[str, Any]:
    payload = exec_controller.build_controller(
        runtime_root=runtime,
        repo_root=repo,
        task_package_root=task_package_root,
        write=True,
        send_signal=send_signal,
        run_verification=run_verification,
        write_aaq=False,
    )
    return {
        "controller_state": str(payload.get("controller_state") or ""),
        "submit_status": str(payload.get("submit_status") or ""),
        "enqueue_ok": payload.get("enqueue_ok") is True,
        "submitted": payload.get("submitted") is True,
        "named_blocker": str(payload.get("named_blocker") or ""),
        "mature_bind_task_id": str(payload.get("mature_bind_task_id") or ""),
    }


def dispatch_supervised_worker(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    worker_key: str,
    mode: str,
    objective: str,
    input_text: str,
    write: bool,
    dp_invoker: Any = None,
    qwen_invoker: Any = None,
) -> dict[str, Any]:
    spec = WORKER_POOL.get(worker_key, {})
    provider = str(spec.get("provider_cli") or "auto")
    if mode not in spec.get("modes", []):
        return {
            "worker": worker_key,
            "mode": mode,
            "status": "blocked",
            "named_blocker": "SUPERVISOR_WORKER_MODE_NOT_ALLOWED",
        }
    payload = direct_lane.invoke_direct_worker_lane(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=wave_id,
        lane_id=f"{wave_id}-{worker_key}-{mode}",
        mode=mode,
        provider=provider,
        objective=objective,
        input_text=input_text,
        write=write,
        dp_invoker=dp_invoker,
        qwen_invoker=qwen_invoker,
    )
    lane = payload.get("worker_lane_result") if isinstance(payload.get("worker_lane_result"), dict) else {}
    return {
        "worker": worker_key,
        "mode": mode,
        "provider": provider,
        "status": str(payload.get("status") or ""),
        "lane_status": str(lane.get("status") or ""),
        "named_blocker": str(payload.get("named_blocker") or lane.get("named_blocker") or ""),
        "artifact_ref": str(lane.get("artifact_ref") or ""),
        "supervisor_fan_in_required": True,
        "direct_repo_write_allowed": spec.get("may_mutate_repo") is True,
    }


def apply_hot_path_self_binds(
    *,
    runtime: Path,
    repo: Path,
    orchestrator_ready: bool,
    supervisor_policy_ready: bool,
    write: bool,
) -> list[dict[str, Any]]:
    binds: list[dict[str, Any]] = []
    if not orchestrator_ready or not supervisor_policy_ready:
        return binds
    stamp = now_iso()
    for relative in HOT_PATH_BIND_ALLOWLIST:
        path = runtime / relative.replace("/", "\\") if os.name == "nt" else runtime / relative
        if not path.is_file():
            binds.append({"relative": relative, "bound": False, "reason": "latest_missing"})
            continue
        payload = read_json(path)
        bind_marker = {
            "bound_by": TASK_ID,
            "supervisor_provider_id": SUPERVISOR_PROVIDER_ID,
            "bound_at": stamp,
            "runtime_enforced_scope": "v4pro_supervisor_orchestrated_hot_path",
            "may_mutate_default_hot_path": True,
            "submit_still_requires_closure_bundle": True,
        }
        payload["supervisor_hot_path_bind"] = bind_marker
        payload["supervisor_orchestrator_ref"] = str(runtime / "state" / "v4pro_supervisor_orchestrator" / "latest.json")
        if write:
            write_json(path, payload)
        binds.append({"relative": relative, "bound": True, "bind_marker": bind_marker})
    return binds


def collect_hot_path_snapshot(runtime: Path) -> list[dict[str, Any]]:
    return [live_watch.hot_path_ref(runtime, relative) for relative in live_watch.HOT_PATH_RELATIVE_PATHS]


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V4Pro Supervisor Orchestrator",
            "",
            SENTINEL,
            "",
            f"- supervisor_provider_id: `{payload.get('supervisor_provider_id')}`",
            f"- orchestrator_state: `{payload.get('orchestrator_state')}`",
            f"- chain_repair_performed: `{payload.get('chain_repair_performed')}`",
            f"- worker_dispatch_count: `{len(payload.get('worker_dispatches') or [])}`",
            f"- hot_path_bind_count: `{len(payload.get('hot_path_binds') or [])}`",
            f"- execution_submit_status: `{payload.get('execution_controller', {}).get('submit_status')}`",
            f"- named_blocker: `{payload.get('named_blocker') or '(none)'}`",
            "",
            "V4Pro = supervisor brain；千问=便宜并行工人；V4Pro hardmode=改仓/绑热路径/提交闭环。",
            "能排队 ≠ 已提交；热路径自绑 ≠ 用户完成。",
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
    service = build_default_service(runtime, repo_root=repo)
    aaq = service.artifact_acceptance_queue(
        "p0-014-v4pro-supervisor-orchestrator",
        [
            {
                "candidate_id": TASK_ID,
                "artifact_ref": str(paths["latest"]),
                "artifact_kind": "v4pro_supervisor_orchestrator",
                "workflow_id": str(payload.get("chain_health", {}).get("workflow_id") or ""),
                "workflow_run_id": str(payload.get("chain_health", {}).get("workflow_run_id") or ""),
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


def build_orchestrator(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_package_root: str | Path = DEFAULT_TASK_PACKAGE_ROOT,
    write: bool = True,
    send_signal: bool = False,
    run_verification: bool = False,
    dispatch_workers: bool = False,
    write_aaq: bool = True,
    repair_fn: Callable[..., dict[str, Any]] | None = None,
    controller_fn: Callable[..., dict[str, Any]] | None = None,
    worker_dispatch_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    task_root = Path(task_package_root)
    paths = output_paths(runtime)

    task_package_snapshot = task_package_resolver.resolve_task_package(
        task_root,
        runtime_root=runtime,
    )

    policy = v4pro_policy.build_policy(runtime_root=runtime, repo_root=repo, write=write, write_aaq=False)
    tool_surface = ucp_resolver.resolve_ucp_tool_surface(
        evidence_runtime_root=runtime,
        repo_root=repo,
    )
    if not policy.get("tool_bearing_executor_eligible"):
        payload = {
            "schema_version": SCHEMA_VERSION,
            "sentinel": SENTINEL,
            "task_id": TASK_ID,
            "status": "v4pro_supervisor_orchestrator_blocked",
            "v4pro_supervisor_orchestrator_ready": False,
            "orchestrator_state": "blocked",
            "supervisor_provider_id": SUPERVISOR_PROVIDER_ID,
            "named_blocker": str(policy.get("named_blocker") or "V4PRO_TOOL_BEARING_EXECUTOR_POLICY_NOT_BOUND"),
            "is_execution_controller": True,
            "not_execution_controller": False,
            "completion_claim_allowed": False,
            "generated_at": now_iso(),
        }
        if write:
            write_json(paths["latest"], payload)
            write_text(paths["readback"], render_readback(payload))
        return payload

    if not tool_surface.get("ready"):
        payload = {
            "schema_version": SCHEMA_VERSION,
            "sentinel": SENTINEL,
            "task_id": TASK_ID,
            "status": "v4pro_supervisor_orchestrator_blocked",
            "v4pro_supervisor_orchestrator_ready": False,
            "orchestrator_state": "blocked",
            "supervisor_provider_id": SUPERVISOR_PROVIDER_ID,
            "tool_surface": tool_surface,
            "named_blocker": str(tool_surface.get("named_blocker") or "CODEX_WORKER_UCP_TOOL_SURFACE_MISSING"),
            "is_execution_controller": True,
            "not_execution_controller": False,
            "completion_claim_allowed": False,
            "generated_at": now_iso(),
        }
        if write:
            write_json(paths["latest"], payload)
            write_text(paths["readback"], render_readback(payload))
        return payload

    health = assess_chain_health(runtime)
    plan = plan_orchestration(health, dispatch_workers=dispatch_workers)
    wave_id = f"{TASK_ID}-{now_iso().replace(':', '').replace('+', '-')}"

    repair_result: dict[str, Any] = {}
    if health.get("needs_chain_repair"):
        repair_callable = repair_fn or repair_chain
        repair_result = repair_callable(runtime=runtime, repo=repo)

    controller_callable = controller_fn or run_execution_controller_tick
    controller_result = controller_callable(
        runtime=runtime,
        repo=repo,
        task_package_root=Path(task_package_root),
        send_signal=send_signal,
        run_verification=run_verification,
    )

    worker_results: list[dict[str, Any]] = []
    if dispatch_workers:
        dispatch_callable = worker_dispatch_fn or dispatch_supervised_worker
        diagnosis_text = json.dumps(
            {"chain_health": health, "repair_result": repair_result, "controller_result": controller_result},
            ensure_ascii=False,
        )
        worker_results.append(
            dispatch_callable(
                runtime=runtime,
                repo=repo,
                wave_id=wave_id,
                worker_key="qwen_prepaid_cheap_worker",
                mode="eval",
                objective="评估当前主链健康并列出需要 V4Pro 修复的 blocker",
                input_text=diagnosis_text,
                write=write,
            )
        )
        worker_results.append(
            dispatch_callable(
                runtime=runtime,
                repo=repo,
                wave_id=wave_id,
                worker_key="deepseek_v4_pro",
                mode="audit",
                objective="审计默认热路径绑定缺口并给出可执行薄绑建议",
                input_text=diagnosis_text,
                write=write,
            )
        )
        if write:
            for index, item in enumerate(worker_results, start=1):
                write_json(paths["worker_dispatches"] / f"{wave_id}-worker-{index}.json", item)

    hot_path_binds = apply_hot_path_self_binds(
        runtime=runtime,
        repo=repo,
        orchestrator_ready=True,
        supervisor_policy_ready=True,
        write=write,
    )
    if write and hot_path_binds:
        write_json(paths["hot_path_binds"] / f"{wave_id}.json", {"wave_id": wave_id, "binds": hot_path_binds})

    named_blocker = str(controller_result.get("named_blocker") or repair_result.get("named_blocker") or "")
    orchestrator_state = "orchestrating"
    if controller_result.get("submitted"):
        orchestrator_state = "submit_closed"
    elif controller_result.get("enqueue_ok"):
        orchestrator_state = "enqueued_awaiting_closure"
    elif named_blocker:
        orchestrator_state = "blocked"

    checks = {
        "v4pro_supervisor_policy_ready": policy.get("tool_bearing_executor_eligible") is True,
        "chain_health_assessed": bool(health),
        "orchestration_plan_emitted": bool(plan),
        "execution_controller_tick_ran": bool(controller_result),
        "submit_implies_enqueue": (not controller_result.get("submitted"))
        or controller_result.get("enqueue_ok") is True,
        "supervisor_is_execution_controller": True,
    }
    ready = all(checks.values())

    if controller_result.get("submitted"):
        next_action = "本波 mature-bind 已闭环提交；supervisor 可 autopop 下一任务。"
    elif controller_result.get("enqueue_ok"):
        next_action = "已入队；V4Pro hardmode 改仓/跑 verifier 后重跑 orchestrator 验 closure。"
    elif health.get("needs_chain_repair"):
        next_action = "主链已尝试自修；检查 repair_result 与 worker 回执。"
    else:
        next_action = "继续 reconcile 或开启 --dispatch-workers 让千问/V4 并行诊断。"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "v4pro_supervisor_orchestrator_ready" if ready else "v4pro_supervisor_orchestrator_blocked",
        "v4pro_supervisor_orchestrator_ready": ready,
        "orchestrator_state": orchestrator_state,
        "supervisor_provider_id": SUPERVISOR_PROVIDER_ID,
        "supervisor_role": "supervisor_brain_planner_dispatcher_merge_owner",
        "dp_is_second_brain": False,
        "worker_pool": WORKER_POOL,
        "tool_surface": tool_surface,
        "runtime_roots_contract": "contracts/codex-s-runtime-roots.v1.json",
        "mature_architecture_refs": MATURE_ARCHITECTURE_REFS,
        "task_package_snapshot": {
            "resolution": str(task_package_snapshot.get("resolution") or ""),
            "next_mature_bind_task_id": str(task_package_snapshot.get("next_mature_bind_task_id") or ""),
            "mature_bind_queue_ready": task_package_snapshot.get("mature_bind_queue_ready") is True,
            "package_digest": str(task_package_snapshot.get("package_digest") or ""),
        },
        "minimal_bootstrap_mode": not dispatch_workers and not run_verification and not send_signal,
        "chain_health": health,
        "orchestration_plan": plan,
        "chain_repair_performed": bool(repair_result),
        "chain_repair": repair_result,
        "execution_controller": controller_result,
        "worker_dispatches": worker_results,
        "hot_path_snapshot": collect_hot_path_snapshot(runtime),
        "hot_path_binds": hot_path_binds,
        "named_blocker": named_blocker,
        "next_machine_action_cn": next_action,
        "validation": {
            "passed": ready,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "acceptance": {
            "accepted_for": "accepted_for_binding",
            "artifact_acceptance_decision": "accepted_for_binding",
            "success_field": "v4pro_supervisor_orchestrator_ready",
            "success_decision": "accepted_for_binding",
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
                "provider_id": "codex_s.v4pro_supervisor_orchestrator",
                "status": "registered",
                "task_id": TASK_ID,
                "runtime_latest": str(paths["latest"]),
                "readback": str(paths["readback"]),
                "is_execution_controller": True,
                "supervisor_provider_id": SUPERVISOR_PROVIDER_ID,
                "completion_claim_allowed": False,
                "generated_at": now_iso(),
            },
        )
        if write_aaq and ready:
            payload["artifact_acceptance"] = write_artifact_acceptance(runtime, repo, payload, paths)
            write_json(paths["latest"], payload)
            write_json(paths["record"], payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v4pro-supervisor-orchestrator")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-package-root", default=str(DEFAULT_TASK_PACKAGE_ROOT))
    parser.add_argument("--send-signal", action="store_true")
    parser.add_argument("--run-verification", action="store_true")
    parser.add_argument("--dispatch-workers", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-aaq", action="store_true")
    args = parser.parse_args(argv)
    payload = build_orchestrator(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_package_root=args.task_package_root,
        write=not args.no_write,
        send_signal=args.send_signal,
        run_verification=args.run_verification,
        dispatch_workers=args.dispatch_workers,
        write_aaq=not args.no_aaq,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("v4pro_supervisor_orchestrator_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())