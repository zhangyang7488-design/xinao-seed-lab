from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import modular_dynamic_worker_pool_phase1 as phase1

SCHEMA_VERSION = "xinao.codex_s.overnight_parent_same_default_loop.v1"
SENTINEL = "SENTINEL:XINAO_OVERNIGHT_PARENT_SAME_DEFAULT_LOOP_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = "overnight_supervisor_loop_phase0_batch_20260704"
SUBSEGMENT_TASK_ID = "modular_dynamic_worker_pool_phase1_20260704"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
POP_PACKAGE = Path(
    r"C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"
    r"\intent_packages\grok_pop_parent_overnight_same_default_shape_20260704.json"
)
PHASE1_GLOBAL_DEFAULT = (
    DEFAULT_RUNTIME
    / "state"
    / "modular_dynamic_worker_pool_phase1"
    / "global_default"
    / "latest.json"
)
RUNTIME_SCOPE = "seed_cortex_parent_overnight_same_default_phase1_loop"
BACKGROUND_RUNNER_DOWNGRADE_FLAGS = {
    "watchdog_only": True,
    "disabled": True,
    "reference_only": True,
    "not_main_loop": True,
    "background_runner_only": True,
    "not_foreground_brain": True,
    "not_task_owner": True,
    "not_completion_boundary": True,
    "not_watch_owner": True,
    "requires_foreground_brain_fanin": True,
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def safe_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
    return cleaned.strip("-")[:140] or "wave"


def read_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{time.time_ns()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{time.time_ns()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / TASK_ID
    return {
        "state": state,
        "latest": state / "latest.json",
        "same_default_latest": state / "same_default_loop" / "latest.json",
        "records": state / "same_default_loop" / "records",
        "background_latest": state / "same_default_loop" / "background_latest.json",
        "parent_assignment": runtime / "state" / "worker_assignment" / f"{TASK_ID}.json",
        "global_assignment": runtime / "state" / "worker_assignment" / f"{WORK_ID}.json",
        "readback": runtime / "readback" / "zh" / "overnight_supervisor_loop_20260704.md",
        "background_log": state / "same_default_loop" / "background.log",
    }


def parse_deadline_epoch(value: str) -> float:
    if not value:
        return 0.0
    try:
        import datetime as dt

        normalized = value.replace("+08:00", "+0800")
        return dt.datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except Exception:
        return 0.0


def package_deadline_epoch(package: dict[str, Any]) -> float:
    context = package.get("parent_overnight_context")
    if not isinstance(context, dict):
        return 0.0
    return parse_deadline_epoch(str(context.get("deadline_at") or ""))


def pop_gate_ready(global_default: dict[str, Any]) -> bool:
    return (
        global_default.get("validation", {}).get("passed") is True
        and global_default.get("runtime_enforced") is True
        and int(global_default.get("enforced_wave_count") or 0) >= 3
        and int(global_default.get("metered_wave_count") or 0) >= 3
        and global_default.get("while_pop", {}).get("pop_ready") is True
    )


def rebind_assignments(
    *,
    runtime: Path,
    package: dict[str, Any],
    global_default: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    previous_parent = read_json(paths["parent_assignment"])
    previous_global = read_json(paths["global_assignment"])
    frozen_shape = package.get("frozen_default_execution_shape")
    if not isinstance(frozen_shape, dict):
        frozen_shape = {}
    parent_assignment = {
        "schema_version": "xinao.worker_assignment.v2.dag",
        "work_id": WORK_ID,
        "route_profile": "seed_cortex_phase0",
        "task_id": TASK_ID,
        "assignment_id": TASK_ID,
        "status": "overnight_parent_same_default_assignment_ready",
        "routing_verb": "pop_resume_parent",
        "source_intent_package_ref": str(POP_PACKAGE),
        "source_intent_package_id": POP_PACKAGE.name,
        "completed_subsegment_task_id": SUBSEGMENT_TASK_ID,
        "pop_gate_evidence_ref": str(PHASE1_GLOBAL_DEFAULT),
        "pop_gate_ready": pop_gate_ready(global_default),
        "active_default_provider": "codex_s.modular_dynamic_worker_pool_phase1",
        "active_shape": frozen_shape,
        "hot_path_shape": "parallel_draft->merge->writer",
        "dp_worker_role": "draft_main_worker_pool",
        "deadline_at": str(
            (package.get("parent_overnight_context") or {}).get("deadline_at") or ""
        ),
        "should_continue_loop": True,
        "foreground_poll_required": True,
        **BACKGROUND_RUNNER_DOWNGRADE_FLAGS,
        "forbidden_default_paths": [
            "overnight_slow_poll_accounting",
            "meta_rsi_productivity_v2_main",
            "local_stub_primary_draft",
            "watchdog_as_default_executor",
        ],
        "assignment_dag": {
            "current_active_node_id": "parent_same_default_phase1_wave",
            "next_ready_node_id": "parent_same_default_phase1_wave",
            "nodes": [
                {
                    "id": "pop_gate_verified",
                    "status": "ready",
                    "ref": str(PHASE1_GLOBAL_DEFAULT),
                },
                {
                    "id": "parent_same_default_phase1_wave",
                    "status": "ready",
                    "provider": "codex_s.modular_dynamic_worker_pool_phase1",
                    "hot_path": "parallel_draft->merge->writer",
                },
                {
                    "id": "parent_readback_and_next_wave",
                    "status": "ready",
                    "ref": str(paths["readback"]),
                },
            ],
        },
        "previous_assignment_task_id": previous_parent.get("task_id"),
        "previous_source_intent_package_ref": previous_parent.get("source_intent_package_ref"),
        "runtime_enforced": True,
        "runtime_enforced_scope": RUNTIME_SCOPE,
        "productivity_mode_v2": False,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    global_assignment = {
        **previous_global,
        "schema_version": previous_global.get("schema_version") or "xinao.worker_assignment.v2.dag",
        "work_id": WORK_ID,
        "route_profile": "seed_cortex_phase0",
        "task_id": previous_global.get("task_id") or SUBSEGMENT_TASK_ID,
        "active_parent_task_id": TASK_ID,
        "active_default_provider": "codex_s.modular_dynamic_worker_pool_phase1",
        "active_shape": frozen_shape,
        "hot_path_shape": "parallel_draft->merge->writer",
        "dp_worker_role": "draft_main_worker_pool",
        **BACKGROUND_RUNNER_DOWNGRADE_FLAGS,
        "source_intent_package_ref": str(POP_PACKAGE),
        "source_intent_package_id": POP_PACKAGE.name,
        "parent_worker_assignment_ref": str(paths["parent_assignment"]),
        "global_default_runtime_enforced_ref": str(PHASE1_GLOBAL_DEFAULT),
        "runtime_enforced": True,
        "runtime_enforced_scope": RUNTIME_SCOPE,
        "productivity_mode_v2": False,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["parent_assignment"], parent_assignment)
        write_json(paths["global_assignment"], global_assignment)
    return {
        "parent_assignment": parent_assignment,
        "global_assignment": global_assignment,
    }


def render_readback(payload: dict[str, Any]) -> str:
    wave = payload.get("parent_wave", {}) if isinstance(payload.get("parent_wave"), dict) else {}
    checks = payload.get("validation", {}).get("checks", {})
    return "\n".join(
        [
            "# overnight_supervisor_loop_20260704 回读",
            "",
            SENTINEL,
            "",
            f"- task_id: `{payload.get('task_id')}`",
            f"- status: `{payload.get('status')}`",
            f"- routing_verb: `{payload.get('routing_verb')}`",
            f"- deadline_at: `{payload.get('deadline_at')}`",
            f"- should_continue_loop: {payload.get('should_continue_loop')}",
            f"- background_runner_only: {payload.get('background_runner_only')}",
            f"- not_foreground_brain: {payload.get('not_foreground_brain')}",
            f"- not_task_owner: {payload.get('not_task_owner')}",
            f"- not_completion_boundary: {payload.get('not_completion_boundary')}",
            f"- requires_foreground_brain_fanin: {payload.get('requires_foreground_brain_fanin')}",
            f"- parent_assignment_rebound: {checks.get('parent_assignment_rebound')}",
            f"- global_assignment_same_default_shape: {checks.get('global_assignment_same_default_shape')}",
            f"- global_trigger_unified: {checks.get('global_trigger_unified')}",
            f"- parent_wave_uses_phase1_provider: {checks.get('parent_wave_uses_phase1_provider')}",
            f"- parent_wave_merge_spend_ready: {checks.get('parent_wave_merge_spend_ready')}",
            "- entry_provider: `codex_s.modular_dynamic_worker_pool_phase1`",
            "- hot_path: `parallel_draft->merge->writer`",
            f"- parent_wave_id: `{wave.get('wave_id', '')}`",
            f"- parent_wave_draft_count: {wave.get('draft_count')}",
            f"- parent_wave_merged_count: {wave.get('merged_count')}",
            f"- parent_wave_spend_entry_count: {wave.get('spend_entry_count')}",
            f"- parent_wave_total_tokens: {wave.get('total_tokens')}",
            f"- merge_artifact: `{wave.get('merge_artifact', '')}`",
            f"- foreground_brain_decision: `{wave.get('foreground_brain_decision_ref', '')}`",
            f"- named_blocker: `{payload.get('named_blocker')}`",
            "",
            "## 回答",
            "",
            "- 过夜父任务每波默认走 DP 草稿池 -> staging -> foreground brain fan-in merge -> writer。",
            f"- 父 assignment 绑定包：`{payload.get('source_intent_package_ref')}`。",
            "- global trigger 与 phase1 不再分裂：Gateway provider 是 runtime_enforced_global_default。",
            "- same_default_loop 只是后台发动机，不是前台主脑、不是任务 owner、不是完成边界。",
            "- meta_rsi/watchdog/local_stub 不是父任务主执行路径。",
            "",
            "## Evidence",
            "",
            f"- latest: `{payload.get('evidence_refs', {}).get('latest')}`",
            f"- parent_assignment: `{payload.get('evidence_refs', {}).get('parent_assignment')}`",
            f"- global_assignment: `{payload.get('evidence_refs', {}).get('global_assignment')}`",
            f"- phase1_latest: `{payload.get('evidence_refs', {}).get('phase1_latest')}`",
            f"- foreground_brain_decision: `{payload.get('evidence_refs', {}).get('foreground_brain_decision')}`",
            "",
            SENTINEL,
            "",
        ]
    )


def run_parent_wave(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    package_ref: str | Path = POP_PACKAGE,
    wave_id: str = "",
    target_width: int = 0,
    write: bool = True,
    max_parallel_workers: int | None = 12,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    package_path = Path(package_ref)
    package = read_json(package_path)
    paths = output_paths(runtime)
    global_default = read_json(PHASE1_GLOBAL_DEFAULT)
    assignment_refs = rebind_assignments(
        runtime=runtime,
        package=package,
        global_default=global_default,
        write=write,
    )
    deadline_epoch = package_deadline_epoch(package)
    now_epoch = time.time()
    wave_number = len(list(paths["records"].glob("*.json"))) + 1 if paths["records"].is_dir() else 1
    actual_wave_id = wave_id or f"{TASK_ID}-same-default-parent-wave-{wave_number:03d}"
    next_wave_id = (
        f"{TASK_ID}-same-default-parent-wave-{wave_number + 1:03d}"
        if (deadline_epoch <= 0 or now_epoch < deadline_epoch)
        else ""
    )
    phase_payload = phase1.run_wave(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=actual_wave_id,
        target_width=target_width,
        write=write,
        record_meta_rsi=False,
        require_external_draft=True,
        max_parallel_workers=max_parallel_workers,
        runtime_enforced=True,
        runtime_enforced_scope=RUNTIME_SCOPE,
        while_chain_id=f"{TASK_ID}.same_default_parent",
        while_wave_index=wave_number,
        while_wave_count=max(wave_number + 1, 999),
        previous_wave_id="",
        next_wave_id=next_wave_id,
    )
    assignment_refs = rebind_assignments(
        runtime=runtime,
        package=package,
        global_default=global_default,
        write=write,
    )
    gateway = read_json(runtime / "state" / "capability_gateway" / "latest.json")
    gateway_phase1 = {}
    for provider in gateway.get("providers", []) if isinstance(gateway, dict) else []:
        if isinstance(provider, dict) and provider.get("provider_id") == "codex_s.modular_dynamic_worker_pool_phase1":
            gateway_phase1 = provider
            break
    token_cost = phase_payload.get("token_cost_spend") if isinstance(phase_payload.get("token_cost_spend"), dict) else {}
    phase_evidence = phase_payload.get("evidence_refs") if isinstance(phase_payload.get("evidence_refs"), dict) else {}
    foreground_decision_ref = str(phase_evidence.get("foreground_brain_decision_latest") or "")
    foreground_decision = (
        phase_payload.get("foreground_brain_decision")
        if isinstance(phase_payload.get("foreground_brain_decision"), dict)
        else {}
    )
    parent_wave = {
        "wave_id": phase_payload.get("wave_id"),
        "phase1_provider": "codex_s.modular_dynamic_worker_pool_phase1",
        "runtime_enforced": phase_payload.get("runtime_enforced") is True,
        "metered": phase_payload.get("metered") is True,
        "draft_count": phase_payload.get("draft_count"),
        "merged_count": phase_payload.get("merged_count"),
        "spend_entry_count": phase_payload.get("spend_entry_count"),
        "total_tokens": token_cost.get("total_tokens"),
        "merge_artifact": phase_payload.get("merge_artifact"),
        "foreground_brain_decision_ref": foreground_decision_ref,
        "foreground_brain_decision_owner": foreground_decision.get("owner"),
        "source_entry_read_at": foreground_decision.get("source_entry_read_at"),
        "latest_ref": str(runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json"),
    }
    should_continue = bool(next_wave_id)
    checks = {
        "pop_gate_ready": pop_gate_ready(global_default),
        "parent_assignment_rebound": assignment_refs["parent_assignment"].get("source_intent_package_ref")
        == str(package_path),
        "global_assignment_same_default_shape": assignment_refs["global_assignment"].get("active_default_provider")
        == "codex_s.modular_dynamic_worker_pool_phase1",
        "global_trigger_unified": gateway_phase1.get("runtime_enforced") is True
        and gateway_phase1.get("adoption_state") == "runtime_enforced_global_default",
        "parent_wave_uses_phase1_provider": parent_wave["phase1_provider"]
        == "codex_s.modular_dynamic_worker_pool_phase1",
        "parent_wave_merge_spend_ready": int(parent_wave.get("merged_count") or 0) > 0
        and int(parent_wave.get("spend_entry_count") or 0) >= 3,
        "foreground_brain_decision_present": bool(foreground_decision_ref)
        and foreground_decision.get("owner") == "foreground_codex_brain",
        "same_default_loop_background_runner_only": all(
            value is True for value in BACKGROUND_RUNNER_DOWNGRADE_FLAGS.values()
        ),
        "meta_rsi_not_main": phase_payload.get("productivity_mode_v2") is False,
        "local_stub_not_primary": int(phase_payload.get("local_stub_draft_count") or 0)
        < int(phase_payload.get("true_dp_draft_count") or 0),
    }
    status = (
        "overnight_parent_same_default_wave_succeeded"
        if all(checks.values())
        else "overnight_parent_same_default_wave_blocked"
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": "seed_cortex_phase0",
        "task_id": TASK_ID,
        "routing_verb": "pop_resume_parent",
        "status": status,
        "source_intent_package_ref": str(package_path),
        "source_intent_package_id": package_path.name,
        "deadline_at": str((package.get("parent_overnight_context") or {}).get("deadline_at") or ""),
        "should_continue_loop": should_continue,
        "foreground_poll_required": True,
        **BACKGROUND_RUNNER_DOWNGRADE_FLAGS,
        "parent_wave": parent_wave,
        "parent_assignment": assignment_refs["parent_assignment"],
        "global_assignment": assignment_refs["global_assignment"],
        "gateway_phase1_provider": gateway_phase1,
        "phase1_payload_ref": parent_wave["latest_ref"],
        "named_blocker": "" if all(checks.values()) else "PARENT_SAME_DEFAULT_CHECK_FAILED",
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_execution_controller": True,
        "evidence_refs": {
            "latest": str(paths["latest"]),
            "same_default_latest": str(paths["same_default_latest"]),
            "parent_assignment": str(paths["parent_assignment"]),
            "global_assignment": str(paths["global_assignment"]),
            "phase1_latest": parent_wave["latest_ref"],
            "foreground_brain_decision": foreground_decision_ref,
            "readback": str(paths["readback"]),
        },
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()},
        "generated_at": now_iso(),
    }
    readback = render_readback(payload)
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["same_default_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(actual_wave_id)}.json", payload)
        write_text(paths["readback"], readback)
    return payload


def run_loop_until_deadline(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    package_ref: str | Path = POP_PACKAGE,
    sleep_seconds: int = 0,
    max_waves: int = 0,
    target_width: int = 0,
    max_parallel_workers: int | None = 12,
) -> dict[str, Any]:
    package = read_json(package_ref)
    deadline_epoch = package_deadline_epoch(package)
    waves: list[dict[str, Any]] = []
    wave_count = 0
    if not max_waves:
        return {
            "schema_version": f"{SCHEMA_VERSION}.loop",
            "sentinel": SENTINEL,
            "task_id": TASK_ID,
            "status": "overnight_parent_same_default_loop_disabled_reference_only",
            **BACKGROUND_RUNNER_DOWNGRADE_FLAGS,
            "wave_count": 0,
            "sleep_seconds": sleep_seconds,
            "sleep_1800_default_main_loop_allowed": False,
            "main_loop_replacement": "temporal_activity_event_queue_loop",
            "validation": {"passed": True},
            "waves": [],
            "generated_at": now_iso(),
        }
    while True:
        if deadline_epoch > 0 and time.time() >= deadline_epoch:
            break
        if max_waves and wave_count >= max_waves:
            break
        wave_count += 1
        waves.append(
            run_parent_wave(
                runtime_root=runtime_root,
                repo_root=repo_root,
                package_ref=package_ref,
                wave_id=f"{TASK_ID}-same-default-parent-loop-{wave_count:03d}",
                target_width=target_width,
                write=True,
                max_parallel_workers=max_parallel_workers,
            )
        )
        if max_waves and wave_count >= max_waves:
            break
        if deadline_epoch > 0 and time.time() + max(1, sleep_seconds) >= deadline_epoch:
            break
        if int(sleep_seconds or 0) > 0:
            time.sleep(max(1, sleep_seconds))
    return {
        "schema_version": f"{SCHEMA_VERSION}.loop",
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "overnight_parent_same_default_loop_exited",
        **BACKGROUND_RUNNER_DOWNGRADE_FLAGS,
        "sleep_seconds": sleep_seconds,
        "sleep_1800_default_main_loop_allowed": False,
        "main_loop_replacement": "temporal_activity_event_queue_loop",
        "wave_count": wave_count,
        "validation": {"passed": bool(waves) and all(w.get("validation", {}).get("passed") is True for w in waves)},
        "waves": [
            {
                "wave_id": wave.get("parent_wave", {}).get("wave_id"),
                "status": wave.get("status"),
                "validation_passed": wave.get("validation", {}).get("passed"),
            }
            for wave in waves
        ],
        "generated_at": now_iso(),
    }


def start_background_loop(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    package_ref: str | Path = POP_PACKAGE,
    sleep_seconds: int = 0,
    target_width: int = 0,
    max_parallel_workers: int = 12,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    args = [
        sys.executable,
        "-m",
        "services.agent_runtime.overnight_parent_same_default_loop",
        "--runtime-root",
        str(runtime),
        "--repo-root",
        str(repo),
        "--package-ref",
        str(package_ref),
        "--loop",
        "--sleep-seconds",
        str(sleep_seconds),
        "--target-width",
        str(target_width),
        "--max-parallel-workers",
        str(max_parallel_workers),
    ]
    payload = {
        "schema_version": f"{SCHEMA_VERSION}.background",
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "overnight_parent_same_default_background_disabled_reference_only",
        "pid": 0,
        **BACKGROUND_RUNNER_DOWNGRADE_FLAGS,
        "command": args,
        "sleep_seconds": sleep_seconds,
        "sleep_1800_default_main_loop_allowed": False,
        "main_loop_replacement": "temporal_activity_event_queue_loop",
        "target_width": target_width,
        "log_path": str(paths["background_log"]),
        "stderr_log_path": str(paths["background_log"].with_suffix(".err.log")),
        "source_intent_package_ref": str(package_ref),
        "validation": {"passed": True},
        "generated_at": now_iso(),
    }
    write_json(paths["background_latest"], payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--package-ref", default=str(POP_PACKAGE))
    parser.add_argument("--wave-id", default="")
    parser.add_argument("--target-width", type=int, default=0)
    parser.add_argument("--max-parallel-workers", type=int, default=12)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--start-background", action="store_true")
    parser.add_argument("--sleep-seconds", type=int, default=0)
    parser.add_argument("--max-waves", type=int, default=0)
    args = parser.parse_args(argv)
    if args.start_background:
        payload = start_background_loop(
            runtime_root=args.runtime_root,
            repo_root=args.repo_root,
            package_ref=args.package_ref,
            sleep_seconds=args.sleep_seconds,
            target_width=args.target_width,
            max_parallel_workers=args.max_parallel_workers,
        )
    elif args.loop:
        payload = run_loop_until_deadline(
            runtime_root=args.runtime_root,
            repo_root=args.repo_root,
            package_ref=args.package_ref,
            sleep_seconds=args.sleep_seconds,
            max_waves=args.max_waves,
            target_width=args.target_width,
            max_parallel_workers=args.max_parallel_workers,
        )
    else:
        payload = run_parent_wave(
            runtime_root=args.runtime_root,
            repo_root=args.repo_root,
            package_ref=args.package_ref,
            wave_id=args.wave_id,
            target_width=args.target_width,
            max_parallel_workers=args.max_parallel_workers,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
