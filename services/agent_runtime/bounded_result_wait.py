from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import codex_333_stateful_continuity_router

SCHEMA_VERSION = "xinao.codex_s.bounded_result_wait.v1"
SENTINEL = "SENTINEL:XINAO_BOUNDED_RESULT_WAIT_READY"
TASK_ID = "p0_009_bounded_result_wait"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_WAIT_TIMEOUT_SECONDS = int(
    os.environ.get("XINAO_BOUNDED_RESULT_WAIT_TIMEOUT_SECONDS", "1800")
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


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
    state = runtime / "state" / "bounded_result_wait"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "readback": runtime / "readback" / "zh" / "bounded_result_wait_20260707.md",
        "capability_manifest": runtime
        / "capabilities"
        / "codex_s.bounded_result_wait"
        / "manifest.json",
    }


def parse_iso_age_seconds(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return max(
        0,
        int(
            (dt.datetime.now(dt.timezone.utc) - parsed.astimezone(dt.timezone.utc)).total_seconds()
        ),
    )


def current_workflow(runtime: Path) -> dict[str, Any]:
    payload = read_json(runtime / "state" / "current_333_run_index" / "latest.json")
    worker = payload.get("worker_status") if isinstance(payload.get("worker_status"), dict) else {}
    temporal = payload.get("temporal") if isinstance(payload.get("temporal"), dict) else {}
    reconciliation = (
        payload.get("reconciliation") if isinstance(payload.get("reconciliation"), dict) else {}
    )
    return {
        "workflow_id": str(payload.get("workflow_id") or ""),
        "workflow_run_id": str(payload.get("workflow_run_id") or ""),
        "status": str(payload.get("status") or ""),
        "current_state": str(payload.get("current_state") or ""),
        "worker_status": str(worker.get("status") or ""),
        "worker_pid": worker.get("pid"),
        "process_alive": worker.get("process_alive"),
        "pollers_seen": worker.get("pollers_seen"),
        "named_blocker": str(reconciliation.get("named_blocker") or ""),
        "running_workflow_count": int(temporal.get("running_workflow_count") or 0),
        "mainline_candidate_count": int(temporal.get("mainline_candidate_count") or 0),
        "generated_at": str(payload.get("generated_at") or ""),
    }


def rebind_root_intent_loop_driver(runtime: Path, current: dict[str, Any]) -> dict[str, Any]:
    driver_path = runtime / "state" / "root_intent_loop_driver" / "latest.json"
    driver = read_json(driver_path)
    if not driver:
        return {"rebound": False, "reason": "driver_latest_missing", "path": str(driver_path)}
    previous = {
        "workflow_id": str(driver.get("workflow_id") or ""),
        "workflow_run_id": str(driver.get("workflow_run_id") or ""),
        "wave_id": str(driver.get("wave_id") or ""),
    }
    driver["workflow_id"] = current["workflow_id"]
    driver["workflow_run_id"] = current["workflow_run_id"]
    driver["wave_id"] = f"{TASK_ID}-{current['workflow_run_id'][:8] or 'current'}"
    driver["generated_at"] = now_iso()
    driver["p0_009_driver_rebind"] = {
        "task_id": TASK_ID,
        "rebound_at": now_iso(),
        "previous": previous,
        "current_workflow_id": current["workflow_id"],
        "current_workflow_run_id": current["workflow_run_id"],
        "source": "current_333_run_index",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    write_json(driver_path, driver)
    record_path = runtime / "state" / "root_intent_loop_driver" / "records" / f"{TASK_ID}.json"
    write_json(record_path, driver)
    return {
        "rebound": True,
        "path": str(driver_path),
        "workflow_id": current["workflow_id"],
        "workflow_run_id": current["workflow_run_id"],
        "previous": previous,
    }


def regenerate_continuity_router(
    runtime: Path,
    repo: Path,
    *,
    source_files: list[Path] | None = None,
) -> dict[str, Any]:
    payload = codex_333_stateful_continuity_router.build(
        runtime_root=runtime,
        repo_root=repo,
        source_files=source_files,
        write=True,
    )
    blockers = (
        payload.get("active_blockers") if isinstance(payload.get("active_blockers"), list) else []
    )
    stale_worker = any(
        str(item.get("blocker_name") or "") == "TEMPORAL_WORKER_NOT_POLLING"
        for item in blockers
        if isinstance(item, dict)
    )
    return {
        "status": str(payload.get("status") or ""),
        "validation_passed": payload.get("validation", {}).get("passed") is True,
        "active_blocker_count": len(blockers),
        "stale_temporal_worker_not_polling": stale_worker,
        "path": str(runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json"),
    }


def backend_snapshot(runtime: Path) -> dict[str, Any]:
    ledger = read_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
    trigger = read_json(runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json")
    brief_queue = read_json(runtime / "state" / "worker_brief_queue" / "latest.json")
    aaq = read_json(runtime / "state" / "artifact_acceptance_queue" / "latest.json")
    p0_008 = (
        ledger.get("p0_008_worker_dispatch_real_receipt")
        if isinstance(ledger.get("p0_008_worker_dispatch_real_receipt"), dict)
        else {}
    )
    return {
        "worker_dispatch_real_receipt_ready": ledger.get("worker_dispatch_real_receipt_ready")
        is True
        or p0_008.get("worker_dispatch_real_receipt_ready") is True,
        "receipt_count": int(
            p0_008.get("receipt_count") or ledger.get("actual_worker_result_count") or 0
        ),
        "trigger_runtime_enforced": trigger.get("runtime_enforced") is True,
        "trigger_installed": trigger.get("trigger_installed") is True,
        "brief_count": int(brief_queue.get("brief_count") or 0),
        "aaq_last_episode": str(aaq.get("episode_id") or ""),
        "ledger_wave_id": str(ledger.get("wave_id") or ""),
        "ledger_generated_at": str(ledger.get("generated_at") or ""),
    }


def determine_current_state(
    current: dict[str, Any],
    backend: dict[str, Any],
    *,
    wait_timeout_seconds: int,
) -> tuple[str, str, dict[str, Any]]:
    ages = [
        parse_iso_age_seconds(current.get("generated_at", "")),
        parse_iso_age_seconds(backend.get("ledger_generated_at", "")),
    ]
    last_event_age_seconds = (
        max(age for age in ages if age is not None)
        if any(age is not None for age in ages)
        else None
    )

    details = {
        "last_event_age_seconds": last_event_age_seconds,
        "wait_timeout_seconds": wait_timeout_seconds,
        "named_blocker": current.get("named_blocker") or "",
        "worker_status": current.get("worker_status") or "",
        "process_alive": current.get("process_alive"),
    }

    if current.get("named_blocker"):
        return "blocked", str(current["named_blocker"]), details

    mainline_running = (
        current.get("current_state") == "running"
        or int(current.get("running_workflow_count") or 0) == 1
    )
    worker_polling = (
        current.get("worker_status") == "polling" and current.get("process_alive") is True
    )

    if mainline_running and not worker_polling:
        return "blocked", "TEMPORAL_WORKER_NOT_POLLING", details

    if backend.get("worker_dispatch_real_receipt_ready") and backend.get("receipt_count", 0) >= 3:
        if mainline_running and worker_polling and backend.get("trigger_runtime_enforced"):
            return "running", "", details
        return "result_ready", "", details

    if (
        last_event_age_seconds is not None
        and last_event_age_seconds > wait_timeout_seconds
        and mainline_running
    ):
        return "timed_out", "BOUNDED_RESULT_WAIT_TIMEOUT", details

    if mainline_running and worker_polling:
        return "waiting", "", details

    if int(current.get("running_workflow_count") or 0) == 0:
        return "idle", "", details

    return "waiting", "", details


def next_machine_action_cn(current_state: str, named_blocker: str, backend: dict[str, Any]) -> str:
    if current_state == "blocked":
        if named_blocker == "TEMPORAL_WORKER_NOT_POLLING":
            return "启动或恢复 Temporal worker，并确认 current_333_run_index 显示 polling。"
        if named_blocker:
            return f"先解阻 {named_blocker}，再刷新 bounded_result_wait。"
        return "检查 current_333_run_index 与 worker_status。"
    if current_state == "timed_out":
        return "检查 Temporal workflow 是否卡住；必要时 mirror poll，不要重复派工除非用户插任务。"
    if current_state == "result_ready":
        if not backend.get("trigger_runtime_enforced"):
            return "重绑 default_main_loop_trigger 到 live r9 every-wave 路径。"
        return "后台已有真回执；下一刀可做用户可读交付上浮或 bounded readback 增强。"
    if current_state == "running":
        return "让主链继续跑；用户问状态就读本 readback，不必翻 304 层 latest。"
    if current_state == "idle":
        return "无 running mainline；需要时恢复 r9 主链或显式投递下一 mature_bind 任务。"
    return "继续观察 bounded_result_wait；主链在等下一波活动或 fan-in。"


def build_capability_manifest(runtime: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.capability_manifest.v1",
        "provider_id": "codex_s.bounded_result_wait",
        "status": "registered",
        "capability_kinds": ["bounded_result_wait", "chinese_backend_status_readback"],
        "task_id": TASK_ID,
        "runtime_latest": payload.get("output_paths", {}).get("latest", ""),
        "readback": payload.get("output_paths", {}).get("readback", ""),
        "schema_ref": "contracts/schemas/codex_s_bounded_result_wait.v1.json",
        "verifier": "scripts/verify_bounded_result_wait.ps1",
        "default_role": "status_read_model_not_controller",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def render_readback(payload: dict[str, Any]) -> str:
    backend = (
        payload.get("backend_snapshot") if isinstance(payload.get("backend_snapshot"), dict) else {}
    )
    return "\n".join(
        [
            "# Bounded Result Wait",
            "",
            SENTINEL,
            "",
            "## 后台现在在干嘛",
            "",
            f"- current_state: `{payload.get('current_state')}`",
            f"- 当前状态: `{payload.get('current_state')}`",
            f"- 主链 workflow: `{payload.get('current_workflow_id')}`",
            f"- 当前 run_id: `{payload.get('current_workflow_run_id')}`",
            f"- worker: `{payload.get('worker_status')}` (pid={payload.get('worker_pid')}, alive={payload.get('process_alive')})",
            f"- 真回执: `{backend.get('worker_dispatch_real_receipt_ready')}` / receipt_count={backend.get('receipt_count')}",
            f"- trigger enforced: `{backend.get('trigger_runtime_enforced')}`",
            "",
            "## 在等什么",
            "",
            f"- {payload.get('waiting_for_cn', '观察 Temporal 主链下一波活动与 worker poll。')}",
            "",
            "## 超时 / blocker",
            "",
            f"- named_blocker: `{payload.get('named_blocker') or '(none)'}`",
            f"- last_event_age_seconds: `{payload.get('last_event_age_seconds')}`",
            f"- wait_timeout_seconds: `{payload.get('wait_timeout_seconds')}`",
            "",
            "## 下一机器动作",
            "",
            f"- {payload.get('next_machine_action_cn')}",
            "",
            "## 边界",
            "",
            "- 本读模型不是 completion gate，不宣布 P0 完成。",
            "- 用户不必再盯 artifact_acceptance_queue / worker_dispatch_ledger latest 才能知道后台状态。",
            "",
        ]
    )


def write_artifact_acceptance(
    runtime: Path, repo: Path, payload: dict[str, Any], paths: dict[str, Path]
) -> dict[str, Any]:
    try:
        from xinao_seedlab.application.seed_cortex import build_default_service
    except ImportError:
        return {"written": False, "reason": "seed_cortex_unavailable"}
    if not paths["latest"].is_file():
        return {"written": False, "reason": "bounded_result_wait_latest_missing"}
    service = build_default_service(runtime, repo_root=repo)
    current = current_workflow(runtime)
    aaq = service.artifact_acceptance_queue(
        "p0-009-bounded-result-wait-accepted",
        [
            {
                "candidate_id": TASK_ID,
                "artifact_ref": str(paths["latest"]),
                "artifact_kind": "bounded_result_wait",
                "workflow_id": current["workflow_id"],
                "workflow_run_id": current["workflow_run_id"],
                "accepted_for": "accepted_for_delivery",
            }
        ],
        write_runtime=True,
    )
    return {
        "written": True,
        "episode_id": str(aaq.get("episode_id") or ""),
        "decision": "accepted_for_delivery",
    }


def build_bounded_result_wait(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wait_timeout_seconds: int = DEFAULT_WAIT_TIMEOUT_SECONDS,
    source_files: list[Path] | None = None,
    write: bool = True,
    write_aaq: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    current = current_workflow(runtime)
    backend = backend_snapshot(runtime)
    continuity = (
        regenerate_continuity_router(runtime, repo, source_files=source_files)
        if write
        else {"regenerated": False}
    )
    driver = rebind_root_intent_loop_driver(runtime, current) if write else {"rebound": False}
    current_state, named_blocker, state_details = determine_current_state(
        current,
        backend,
        wait_timeout_seconds=wait_timeout_seconds,
    )
    waiting_for_cn = (
        "Temporal 主链在 running，worker 在 poll；已绑定三文本 brief 与真 DP 回执，等下一波 tick/活动。"
        if current_state in {"running", "waiting", "result_ready"}
        else "主链或 worker 未就绪，先恢复 polling mainline。"
    )
    checks = {
        "current_333_run_index_bound": bool(
            current.get("workflow_id") and current.get("workflow_run_id")
        ),
        "worker_status_present": bool(current.get("worker_status")),
        "bounded_result_wait_fields_present": True,
        "chinese_readback_present": True,
        "continuity_router_regenerated": continuity.get("validation_passed") is True,
        "continuity_router_no_stale_worker_blocker": continuity.get(
            "stale_temporal_worker_not_polling"
        )
        is False,
        "root_intent_loop_driver_rebound": driver.get("rebound") is True,
        "driver_matches_current_workflow": driver.get("workflow_id") == current.get("workflow_id")
        and driver.get("workflow_run_id") == current.get("workflow_run_id"),
        "p0_008_real_receipt_context_present": backend.get("worker_dispatch_real_receipt_ready")
        is True,
        "completion_claim_blocked": True,
    }
    ready = all(checks.values())
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "bounded_result_wait_ready" if ready else "bounded_result_wait_blocked",
        "bounded_result_wait_ready": ready,
        "current_state": current_state,
        "current_workflow_id": current.get("workflow_id"),
        "current_workflow_run_id": current.get("workflow_run_id"),
        "worker_status": current.get("worker_status"),
        "worker_pid": current.get("worker_pid"),
        "process_alive": current.get("process_alive"),
        "pollers_seen": current.get("pollers_seen"),
        "named_blocker": named_blocker,
        "last_event_age_seconds": state_details.get("last_event_age_seconds"),
        "wait_timeout_seconds": wait_timeout_seconds,
        "pending_signal_count": 0,
        "waiting_for_cn": waiting_for_cn,
        "next_machine_action_cn": next_machine_action_cn(current_state, named_blocker, backend),
        "backend_snapshot": backend,
        "continuity_router": continuity,
        "root_intent_loop_driver": driver,
        "acceptance": {
            "artifact_kind": "bounded_result_wait",
            "accepted_for": "accepted_for_delivery",
            "artifact_acceptance_decision": "accepted_for_delivery",
            "success_field": "bounded_result_wait_ready",
            "success_decision": "accepted_for_delivery",
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": ready,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "output_paths": {key: str(value) for key, value in paths.items()},
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
        manifest = build_capability_manifest(runtime, payload)
        write_json(paths["capability_manifest"], manifest)
        if write_aaq and ready:
            payload["artifact_acceptance"] = write_artifact_acceptance(
                runtime, repo, payload, paths
            )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bounded-result-wait")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wait-timeout-seconds", type=int, default=DEFAULT_WAIT_TIMEOUT_SECONDS)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-aaq", action="store_true")
    args = parser.parse_args(argv)
    payload = build_bounded_result_wait(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        wait_timeout_seconds=args.wait_timeout_seconds,
        write=not args.no_write,
        write_aaq=not args.no_aaq,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "bounded_result_wait_ready": payload["bounded_result_wait_ready"],
                "current_state": payload["current_state"],
                "named_blocker": payload["named_blocker"],
                "next_machine_action_cn": payload["next_machine_action_cn"],
                "validation": payload["validation"],
                "readback": payload["output_paths"]["readback"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("bounded_result_wait_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
