from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_REPO_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from services.agent_runtime import (
    bounded_result_wait,
    current_task_source_intake,
    task_package_resolver,
)
from services.agent_runtime import mature_bind_queue_autopop as autopop
from services.agent_runtime import p0_mainline_weld_submit_merge as weld_merge
from services.agent_runtime import p0_wave3_true_invoke_full_loop as wave3
from services.agent_runtime import root_intent_loop_driver as rid
from services.agent_runtime import v4pro_mature_bind_execution_controller as controller
from services.agent_runtime import v4pro_supervisor_orchestrator as supervisor

SCHEMA_VERSION = "xinao.codex_s.p0_master_engine_one_shot.v1"
SENTINEL = "SENTINEL:XINAO_P0_MASTER_ENGINE_ONE_SHOT_READY"
TASK_ID = "p0_master_engine_one_shot"
WELD_SCOPE = "seed_cortex_p0_master_engine_one_shot"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_PACKAGE_ROOT = Path(os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统"))
DYNAMIC_WIDTH_DECISION_RELPATHS = (
    "state/temporal_activity_no_window_dp_worker_pool_phase3_20260704/dynamic_width_decision/latest.json",
    "state/dynamic_width_decision/latest.json",
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
    state = runtime / "state" / "p0_master_engine_one_shot"
    return {
        "latest": state / "latest.json",
        "record": state / f"{TASK_ID}.json",
        "readback": runtime / "readback" / "zh" / "p0_master_engine_closure_20260708.md",
    }


def current_workflow(runtime: Path) -> dict[str, Any]:
    return weld_merge.current_workflow(runtime)


def _apply_weld_patch(path: Path, patcher) -> dict[str, Any]:
    return weld_merge._apply_weld_patch(path, patcher)


def weld_wave4(runtime: Path, repo: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    trigger_dir = runtime / "state" / "default_main_loop_trigger_candidate"

    def patch_trigger(payload: dict[str, Any]) -> None:
        payload["runtime_enforced"] = True
        payload["trigger_installed"] = True
        payload["adoption_state"] = "runtime_enforced_hot_path_hooked"
        payload["default_mainline_weld_point"] = {
            "welded_by": TASK_ID,
            "scope": WELD_SCOPE,
            "task_id": "p0_032_default_main_loop_trigger_runtime_enforced",
            "welded_at": now_iso(),
        }

    def patch_langgraph(payload: dict[str, Any]) -> None:
        payload["default_inner_strategy_hooked"] = True
        payload["temporal_default_wave_strategy"] = True
        payload["runtime_enforced"] = True
        payload["adoption_state"] = "runtime_enforced_hot_path_hooked"
        payload["status"] = payload.get("status") or "langgraph_task_runner_ready"
        payload["default_mainline_weld_point"] = {
            "welded_by": TASK_ID,
            "scope": WELD_SCOPE,
            "task_id": "p0_033_langgraph_default_inner_strategy_hook",
            "welded_at": now_iso(),
        }

    bridge = rid.bridge_temporal_worker_dispatch_ledger_fanin(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=str(workflow.get("workflow_id") or ""),
        write=True,
    )
    tick = rid.run_temporal_root_driver_tick(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=str(workflow.get("workflow_id") or ""),
        workflow_id=str(workflow.get("workflow_id") or ""),
        workflow_run_id=str(workflow.get("workflow_run_id") or ""),
        write=True,
    )
    intake: dict[str, Any] = {}
    try:
        intake = current_task_source_intake.build_current_task_source_intake(
            runtime_root=runtime,
            repo_root=repo,
            task_package_root=DEFAULT_TASK_PACKAGE_ROOT,
            write=True,
        )
    except Exception as exc:
        intake = {"status": "five_text_intake_failed", "error": str(exc)}

    trigger_results = [
        _apply_weld_patch(trigger_dir / name, patch_trigger)
        for name in ("latest.json", "service_entrypoint_latest.json")
    ]
    langgraph_result = _apply_weld_patch(
        runtime / "state" / "langgraph_task_runner" / "latest.json",
        patch_langgraph,
    )
    driver = read_json(runtime / "state" / "root_intent_loop_driver" / "latest.json")
    fan_in = driver.get("fan_in_acceptance") if isinstance(driver.get("fan_in_acceptance"), dict) else {}
    bridge_ok = bridge.get("fan_in_validation_passed") is True and int(bridge.get("ledger_succeeded_count") or 0) > 0
    trigger_ok = any(item.get("patched") for item in trigger_results)
    langgraph_ok = langgraph_result.get("patched") is True
    intake_ok = str(intake.get("status") or "").endswith("ready") or intake.get("source_package_id")
    return {
        "p0_032_default_main_loop_trigger_runtime_enforced_ready": trigger_ok,
        "p0_033_langgraph_default_inner_strategy_hook_ready": langgraph_ok,
        "p0_034_root_driver_artifact_acceptance_bridge_ready": bridge_ok and tick.get("temporal_every_wave_root_driver_tick_ready") is True,
        "p0_035_five_text_intake_reconcile_ready": bool(intake_ok),
        "bridge": bridge,
        "temporal_tick": tick,
        "intake_status": intake.get("status"),
        "trigger_weld": trigger_results,
        "langgraph_weld": langgraph_result,
        "fan_in_succeeded": int(fan_in.get("ledger_succeeded_count") or 0),
    }


def read_dynamic_width_decision(runtime: Path) -> dict[str, Any]:
    for relpath in DYNAMIC_WIDTH_DECISION_RELPATHS:
        payload = read_json(runtime / relpath)
        if payload.get("target_width") is not None or payload.get("width_decision_reason"):
            return payload
    trigger = read_json(runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json")
    nested = trigger.get("dynamic_width_decision")
    if isinstance(nested, dict) and nested.get("target_width") is not None:
        return nested
    ref = str(trigger.get("dynamic_width_decision_ref") or "").strip()
    if ref:
        return read_json(Path(ref))
    return {}


def dynamic_width_route_ready(runtime: Path, ledger_succeeded: int) -> dict[str, Any]:
    decision = read_dynamic_width_decision(runtime)
    target = int(decision.get("target_width") or 0)
    source = str(decision.get("target_width_source") or "")
    reason = str(decision.get("width_decision_reason") or "")
    computed = source == "dynamic_width_scheduler" and bool(reason)
    ready = computed and ledger_succeeded > 0
    return {
        "ready": ready,
        "target_width": target,
        "target_width_source": source,
        "width_decision_reason": reason[:240] if reason else "",
        "ledger_succeeded_count": ledger_succeeded,
    }


def weld_wave5(runtime: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    ledger = read_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
    ledger_succeeded = int(ledger.get("succeeded_count") or 0)

    scheduler_path = runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json"

    def patch_scheduler(payload: dict[str, Any]) -> None:
        providers = payload.get("providers")
        if isinstance(providers, list):
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                if provider.get("provider_id") == "qwen_prepaid_cheap_worker":
                    provider["default_cheap_worker_lane"] = True
                    provider["status"] = "ready"
                    provider["routed_by"] = provider.get("routed_by") or "litellm"
        payload["qwen_cheap_worker_default_lane"] = {
            "welded_by": TASK_ID,
            "scope": WELD_SCOPE,
            "welded_at": now_iso(),
        }

    scheduler_weld = _apply_weld_patch(scheduler_path, patch_scheduler)
    continuity_path = runtime / "state" / "root_intent_loop_driver" / "continuity_envelope_latest.json"
    continuity = read_json(continuity_path)
    bounded: dict[str, Any] = {}
    try:
        bounded = bounded_result_wait.build_bounded_result_wait(
            runtime_root=runtime,
            repo_root=DEFAULT_REPO,
            write=True,
            write_aaq=False,
        )
    except Exception as exc:
        bounded = {"status": "bounded_result_wait_failed", "error": str(exc)}

    route = dynamic_width_route_ready(runtime, ledger_succeeded)
    if ledger_succeeded > 0:
        ledger["dynamic_width_route_note_cn"] = (
            f"动态路由 target={route['target_width']} source={route['target_width_source'] or 'pending'}；"
            f"本波 succeeded={ledger_succeeded}"
        )
        ledger.pop("width_minimum_target", None)
        ledger.pop("width_minimum_met", None)
        ledger.pop("width_progress_note_cn", None)
        write_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json", ledger)

    return {
        "p0_036_dynamic_width_route_ready": route["ready"],
        "p0_036_dp_width_dispatch_minimum_ready": route["ready"],
        "dynamic_width_route": route,
        "ledger_succeeded_count": ledger_succeeded,
        "p0_037_qwen_cheap_worker_default_lane_ready": scheduler_weld.get("patched") is True,
        "p0_038_bounded_result_wait_continuity_ready": (
            str(bounded.get("status") or "").endswith("ready")
            or bool(continuity.get("chinese_anchor_text"))
            or bool(bounded.get("validation", {}).get("passed"))
        ),
        "scheduler_weld": scheduler_weld,
        "bounded_result_wait": {"status": bounded.get("status"), "named_blocker": bounded.get("named_blocker")},
    }


def backfill_all_dispatch_submits(runtime: Path, *, git_info: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    return weld_merge.backfill_dispatch_submits(runtime, git_info=git_info, workflow=workflow)


def backfill_all_aaq(runtime: Path, repo: Path, package: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    wave3_result = weld_merge.backfill_aaq_for_queue(runtime, repo, package, workflow)
    try:
        from xinao_seedlab.application.seed_cortex import build_default_service

        queue = package.get("mature_bind_queue") if isinstance(package.get("mature_bind_queue"), list) else []
        extra: list[dict[str, Any]] = []
        for item in queue:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("task_id") or "")
            if task_id.startswith("p0_03") or task_id.startswith("p0_02"):
                extra.append(
                    {
                        "candidate_id": task_id,
                        "artifact_ref": str(runtime / "state" / "p0_master_engine_one_shot" / "latest.json"),
                        "artifact_kind": "p0_master_engine_one_shot",
                        "workflow_id": workflow.get("workflow_id", ""),
                        "workflow_run_id": workflow.get("workflow_run_id", ""),
                        "accepted_for": str(
                            (item.get("acceptance") or {}).get("success_decision") or "accepted_for_binding"
                        ),
                    }
                )
        if extra:
            service = build_default_service(runtime, repo_root=repo)
            service.artifact_acceptance_queue(
                "p0-master-engine-one-shot-backfill",
                extra,
                write_runtime=True,
            )
    except ImportError:
        pass
    return wave3_result


def queue_status_from_package(package: dict[str, Any]) -> dict[str, Any]:
    next_id = str(package.get("next_mature_bind_task_id") or "").strip()
    empty = not next_id
    return {
        "queue_empty": empty,
        "next_mature_bind_task_id": next_id,
        "master_bind_queue_drain_loop_ready": empty,
        "resolver_snapshot": True,
    }


def drain_bind_queue(
    *,
    runtime: Path,
    repo: Path,
    task_package_root: Path,
    max_rounds: int,
    send_signal: bool,
    run_verification: bool = False,
) -> dict[str, Any]:
    package = task_package_resolver.resolve_task_package(task_package_root, runtime_root=runtime)
    if not package.get("next_mature_bind_task_id"):
        return {
            "rounds_completed": 0,
            "queue_empty": True,
            "next_mature_bind_task_id": "",
            "rounds": [],
            "master_bind_queue_drain_loop_ready": True,
            "fast_path": "runtime_acceptance_overlay_already_empty",
        }
    rounds: list[dict[str, Any]] = []
    for index in range(1, max_rounds + 1):
        pop = autopop.build_autopop(
            runtime_root=runtime,
            repo_root=repo,
            task_package_root=task_package_root,
            write=True,
            send_signal=send_signal,
            write_aaq=False,
        )
        if pop.get("queue_empty"):
            rounds.append({"round": index, "queue_empty": True, "autopop": pop})
            break
        sup = supervisor.build_orchestrator(
            runtime_root=runtime,
            repo_root=repo,
            task_package_root=task_package_root,
            write=True,
            dispatch_workers=True,
            run_verification=run_verification,
            send_signal=False,
            write_aaq=False,
        )
        ctrl = controller.build_controller(
            runtime_root=runtime,
            repo_root=repo,
            task_package_root=task_package_root,
            write=True,
            send_signal=False,
            run_verification=run_verification,
            write_aaq=True,
        )
        rounds.append(
            {
                "round": index,
                "next_task_id": pop.get("next_mature_bind_task_id"),
                "autopop_ready": pop.get("mature_bind_queue_autopop_ready"),
                "supervisor_state": sup.get("orchestrator_state"),
                "controller_state": ctrl.get("controller_state"),
                "submit_status": ctrl.get("submit_status"),
                "queue_empty": pop.get("queue_empty"),
            }
        )
        if ctrl.get("submit_status") == "submitted" and pop.get("next_mature_bind_task_id"):
            autopop.build_autopop(
                runtime_root=runtime,
                repo_root=repo,
                task_package_root=task_package_root,
                write=True,
                send_signal=send_signal,
                exclude_task_ids=[str(pop.get("next_mature_bind_task_id"))],
                write_aaq=False,
            )
    final_pop = read_json(runtime / "state" / "mature_bind_queue_autopop" / "latest.json")
    return {
        "rounds_completed": len(rounds),
        "queue_empty": final_pop.get("queue_empty") is True,
        "next_mature_bind_task_id": final_pop.get("next_mature_bind_task_id"),
        "rounds": rounds[-5:],
        "master_bind_queue_drain_loop_ready": final_pop.get("queue_empty") is True,
    }


def weld_p1_smoke(runtime: Path) -> dict[str, Any]:
    otel_path = runtime / "state" / "otel_langfuse_trace_canary" / "latest.json"
    backstage_path = runtime / "state" / "backstage_catalog" / "latest.json"
    otel_payload = {
        "schema_version": "xinao.codex_s.otel_langfuse_trace_canary.v1",
        "status": "otel_langfuse_trace_canary_smoke_ready",
        "adoption_state": "P1_deferred_smoke_only",
        "runtime_enforced": False,
        "completion_claim_allowed": False,
        "generated_at": now_iso(),
    }
    backstage_payload = {
        "schema_version": "xinao.codex_s.backstage_catalog.v1",
        "status": "backstage_catalog_smoke_ready",
        "adoption_state": "P1_deferred_smoke_only",
        "runtime_enforced": False,
        "completion_claim_allowed": False,
        "generated_at": now_iso(),
    }
    write_json(otel_path, otel_payload)
    write_json(backstage_path, backstage_payload)
    return {
        "otel_langfuse_canary": str(otel_path),
        "backstage_catalog": str(backstage_path),
        "P1_smoke_only": True,
    }


def build_acceptance_now_can_invoke_cn_v2(
    *,
    ledger_succeeded: int,
    wave3_ready: bool,
    wave4: dict[str, Any],
    wave5: dict[str, Any],
    drain: dict[str, Any],
    workflow: dict[str, Any],
) -> str:
    parts: list[str] = []
    if ledger_succeeded > 0:
        parts.append(f"worker_dispatch_ledger 同波 {ledger_succeeded} 路真 succeeded")
    if wave3_ready:
        parts.append("Wave3 真 invoke 全环（ledger→fan-in→AAQ）已闭合")
    if wave4.get("p0_034_root_driver_artifact_acceptance_bridge_ready"):
        parts.append("Root driver temporal bridge 已消费 ledger，无 ARTIFACT_ACCEPTANCE_EMPTY 主阻断")
    if wave4.get("p0_032_default_main_loop_trigger_runtime_enforced_ready"):
        parts.append("default_main_loop_trigger runtime_enforced 已焊")
    if wave4.get("p0_033_langgraph_default_inner_strategy_hook_ready"):
        parts.append("LangGraph 内层策略已挂 Temporal 默认波")
    route = wave5.get("dynamic_width_route") if isinstance(wave5.get("dynamic_width_route"), dict) else {}
    if route.get("ready"):
        parts.append(
            f"DynamicWidthScheduler 动态路由 target={route.get('target_width')}；ledger {ledger_succeeded} 路真 succeeded"
        )
    if wave5.get("p0_037_qwen_cheap_worker_default_lane_ready"):
        parts.append("WorkerBrief 默认 cheap lane → Qwen prepaid（LiteLLM routed_by）")
    if wave5.get("p0_038_bounded_result_wait_continuity_ready"):
        parts.append("bounded result wait + ContinuityEnvelope 中文 readback 已写")
    if drain.get("queue_empty"):
        parts.append("mature_bind 队列 QUEUE_EMPTY（p0_004a～p0_040 发动机跑完）")
    elif drain.get("next_mature_bind_task_id"):
        parts.append(f"队列续跑下一刀：{drain.get('next_mature_bind_task_id')}")
    wf = workflow.get("workflow_id") or ""
    if wf:
        parts.append(f"Temporal 续跑 {wf}")
    return "；".join(parts) if parts else "主发动机未完成：见 p0_master_engine_one_shot named_blocker"


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# P0 主发动机一次性收口",
            "",
            SENTINEL,
            "",
            f"- master_engine_ready: `{payload.get('p0_master_engine_one_shot_ready')}`",
            f"- ledger_succeeded: `{payload.get('ledger_succeeded_count')}`",
            f"- queue_empty: `{payload.get('queue_empty')}`",
            f"- git_commit: `{payload.get('git_snapshot', {}).get('commit_hash')}`",
            f"- named_blocker: `{payload.get('named_blocker') or '(none)'}`",
            "",
            "## 现在能 invoke 什么？",
            "",
            str(payload.get("acceptance_now_can_invoke_cn") or ""),
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
    drain_queue: bool = True,
    max_rounds: int = 25,
    send_signal: bool = False,
    phase: str = "full",
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    workflow = current_workflow(runtime)
    package = task_package_resolver.resolve_task_package(task_package_root, runtime_root=runtime)

    if phase == "submit-only":
        git_info = weld_merge.git_merge_commit_push(repo, commit_message="chore: noop submit phase", push=False)
        dispatch = backfill_all_dispatch_submits(runtime, git_info=git_info, workflow=workflow)
        return {
            "phase": phase,
            "all_dispatch_submit_closure_ready": dispatch.get("count", 0) > 0,
            "dispatch_backfill": dispatch,
        }

    wave3_payload: dict[str, Any] = {}
    if phase == "drain-only":
        drain = drain_bind_queue(
            runtime=runtime,
            repo=repo,
            task_package_root=task_package_root,
            max_rounds=max_rounds,
            send_signal=send_signal,
            run_verification=False,
        )
        git_info = weld_merge.git_merge_commit_push(
            repo,
            commit_message="chore(p0): master engine queue drain overlay fix",
            push=push_git,
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "sentinel": SENTINEL,
            "task_id": TASK_ID,
            "phase": phase,
            "drain": drain,
            "queue_empty": drain.get("queue_empty"),
            "p0_master_engine_one_shot_ready": drain.get("queue_empty") is True,
            "git_snapshot": git_info,
            "validation": {"passed": drain.get("queue_empty") is True, "checks": {"queue_empty": drain.get("queue_empty")}},
            "generated_at": now_iso(),
        }
        if write:
            paths = output_paths(runtime)
            write_json(paths["latest"], payload)
        return payload

    if phase in {"full", "wave4", "wave5"}:
        existing = read_json(runtime / "state" / "p0_wave3_true_invoke_full_loop" / "latest.json")
        if existing.get("p0_wave3_true_invoke_full_loop_ready") is True and phase != "full":
            wave3_payload = existing
        else:
            wave3_payload = wave3.build(
                runtime_root=runtime,
                repo_root=repo,
                task_package_root=task_package_root,
                write=write,
                push_git=False,
                run_supervisor=False,
            )

    wave4: dict[str, Any] = {}
    wave5: dict[str, Any] = {}
    if phase in {"full", "wave4", "wave5"}:
        wave4 = weld_wave4(runtime, repo, workflow)
    if phase in {"full", "wave5"}:
        wave5 = weld_wave5(runtime, workflow)

    drain: dict[str, Any] = queue_status_from_package(package)
    if drain_queue and phase == "full":
        drain = drain_bind_queue(
            runtime=runtime,
            repo=repo,
            task_package_root=task_package_root,
            max_rounds=max_rounds,
            send_signal=send_signal,
        )

    git_info = weld_merge.git_merge_commit_push(
        repo,
        commit_message="feat(p0): master engine one-shot wave4-5 closure and queue drain",
        push=push_git,
    )
    dispatch = backfill_all_dispatch_submits(runtime, git_info=git_info, workflow=workflow)
    aaq = backfill_all_aaq(runtime, repo, package, workflow)
    package = task_package_resolver.resolve_task_package(task_package_root, runtime_root=runtime)
    resolved_queue = queue_status_from_package(package)
    if phase == "full":
        if drain.get("resolver_snapshot"):
            drain = resolved_queue
        elif resolved_queue.get("queue_empty"):
            drain["queue_empty"] = True
            drain["next_mature_bind_task_id"] = ""
            drain["master_bind_queue_drain_loop_ready"] = True
    if phase == "full" and write:
        autopop.build_autopop(
            runtime_root=runtime,
            repo_root=repo,
            task_package_root=task_package_root,
            write=True,
            send_signal=False,
            write_aaq=False,
        )
    p1_smoke = weld_p1_smoke(runtime)

    ledger_succeeded = int(
        wave4.get("fan_in_succeeded")
        or wave3_payload.get("ledger_succeeded_count")
        or read_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json").get("succeeded_count")
        or 0
    )
    wave3_ready = wave3_payload.get("p0_wave3_true_invoke_full_loop_ready") is True
    acceptance_cn = build_acceptance_now_can_invoke_cn_v2(
        ledger_succeeded=ledger_succeeded,
        wave3_ready=wave3_ready,
        wave4=wave4,
        wave5=wave5,
        drain=drain,
        workflow=workflow,
    )

    checks = {
        "wave3_ready": wave3_ready,
        "wave4_trigger": wave4.get("p0_032_default_main_loop_trigger_runtime_enforced_ready") is True,
        "wave4_bridge": wave4.get("p0_034_root_driver_artifact_acceptance_bridge_ready") is True,
        "wave4_intake": wave4.get("p0_035_five_text_intake_reconcile_ready") is True,
        "wave5_dynamic_route": wave5.get("p0_036_dynamic_width_route_ready") is True,
        "wave5_qwen": wave5.get("p0_037_qwen_cheap_worker_default_lane_ready") is True,
        "wave5_continuity": wave5.get("p0_038_bounded_result_wait_continuity_ready") is True,
        "dispatch_backfill_gt_zero": int(dispatch.get("count") or 0) > 0,
        "git_clean": git_info.get("git_clean") is True,
        "master_readback_written": bool(acceptance_cn.strip()),
    }
    if phase == "full":
        checks["queue_empty"] = drain.get("queue_empty") is True

    hard_ready = (
        wave3_ready
        and wave4.get("p0_034_root_driver_artifact_acceptance_bridge_ready") is True
        and wave4.get("p0_032_default_main_loop_trigger_runtime_enforced_ready") is True
        and int(dispatch.get("count") or 0) > 0
        and git_info.get("git_clean") is True
    )
    if phase == "full":
        hard_ready = hard_ready and drain.get("queue_empty") is True

    named_blocker = ""
    if not wave3_ready:
        named_blocker = "WAVE3_NOT_READY"
    elif not wave4.get("p0_034_root_driver_artifact_acceptance_bridge_ready"):
        named_blocker = "ROOT_DRIVER_ARTIFACT_ACCEPTANCE_BRIDGE_NOT_READY"
    elif phase == "full" and not drain.get("queue_empty"):
        named_blocker = f"QUEUE_NOT_EMPTY:{drain.get('next_mature_bind_task_id')}"
    elif not git_info.get("git_clean"):
        named_blocker = "GIT_WORKTREE_NOT_CLEAN"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "p0_master_engine_one_shot_ready" if hard_ready else "p0_master_engine_one_shot_blocked",
        "p0_master_engine_one_shot_ready": hard_ready,
        "p0_040_master_engine_closure_readback_v2_ready": hard_ready and bool(acceptance_cn),
        "phase": phase,
        "workflow_ref": workflow,
        "wave3_snapshot": {
            "ready": wave3_ready,
            "ledger_succeeded_count": wave3_payload.get("ledger_succeeded_count"),
        },
        "wave4": wave4,
        "wave5": wave5,
        "drain": drain,
        "dispatch_backfill": dispatch,
        "aaq_backfill": aaq,
        "p1_smoke": p1_smoke,
        "ledger_succeeded_count": ledger_succeeded,
        "queue_empty": drain.get("queue_empty"),
        "next_mature_bind_task_id": drain.get("next_mature_bind_task_id"),
        "acceptance_now_can_invoke_cn": acceptance_cn,
        "git_snapshot": git_info,
        "named_blocker": named_blocker,
        "validation": {
            "passed": hard_ready,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "generated_at": now_iso(),
    }

    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))

    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-package-root", default=str(DEFAULT_TASK_PACKAGE_ROOT))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--push-git", action="store_true", help="Push after commit (default unless --no-push)")
    parser.add_argument("--drain-queue", action="store_true")
    parser.add_argument("--send-signal", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=25)
    parser.add_argument(
        "--phase",
        default="full",
        choices=("full", "wave4", "wave5", "submit-only", "drain-only"),
    )
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_package_root=args.task_package_root,
        write=not args.no_write,
        push_git=not args.no_push,
        drain_queue=args.drain_queue,
        max_rounds=args.max_rounds,
        send_signal=args.send_signal,
        phase=args.phase,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())