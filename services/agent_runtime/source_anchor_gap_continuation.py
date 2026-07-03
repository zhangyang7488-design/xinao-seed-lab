from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.source_anchor_gap_continuation.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_SOURCE_ANCHOR_GAP_CONTINUATION_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
NODE_ID = "source_anchor_gap_continuation"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")

ANCHOR_TEXTS = {
    "total_draft": "新系统独立并行_自由发散外部研究总稿_20260701.txt",
    "max_benefit_parallel_slice": "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
    "step_program": "新系统步骤程序_大骨架_并行研究收口_20260702.txt",
    "preconstruction_merge": "新系统前置材料_收口合并_20260702.txt",
}

RUNTIME_REF_PATHS = {
    "live_backend_watch": r"state\codex_s_live_backend_watch\latest.json",
    "default_hot_path_intake": r"state\default_hot_path_intake\latest.json",
    "artifact_acceptance_queue": r"state\artifact_acceptance_queue\latest.json",
    "metaminute_preflight_reflection": r"state\metaminute_preflight_reflection\latest.json",
    "default_parallelism_policy": r"state\default_parallelism_policy\latest.json",
    "parallel_dispatch_plan": r"state\parallel_dispatch_plan\latest.json",
    "parallel_fan_in_acceptance": r"state\parallel_fan_in_acceptance\latest.json",
    "seed_lab_total_execution_kernel": r"state\seed_lab_total_execution_kernel\latest.json",
    "seed_lab_correction_intake": r"state\seed_lab_correction_intake\latest.json",
}

MAIN_EXECUTION_LOOP = [
    "restore",
    "dispatch",
    "poll",
    "fan_in",
    "verify_evidence_readback",
    "recompute_capacity",
    "next_wave",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def replace_path_with_retry(tmp: Path, path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(25):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.04 * (attempt + 1))
    if last_error is not None:
        raise last_error


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


def file_ref(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return ref
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    ref.update(
        {
            "byte_count": len(data),
            "line_count": len(text.splitlines()),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
            "last_write_time": dt.datetime.fromtimestamp(
                path.stat().st_mtime, tz=dt.datetime.now().astimezone().tzinfo
            ).isoformat(timespec="seconds"),
        }
    )
    return ref


def json_ref(path: Path) -> dict[str, Any]:
    ref = file_ref(path)
    if not path.is_file():
        return ref
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        ref.update({"json_valid": False, "json_error": str(exc)})
        return ref
    validation = payload.get("validation") if isinstance(payload, dict) else None
    ref.update(
        {
            "json_valid": True,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "sentinel": payload.get("sentinel"),
            "validation_passed": validation.get("passed")
            if isinstance(validation, dict)
            else None,
            "foreground_poll_required": payload.get("foreground_poll_required"),
            "not_execution_controller": payload.get("not_execution_controller"),
        }
    )
    return ref


def source_anchors(anchor_root: Path) -> dict[str, Any]:
    refs = {key: file_ref(anchor_root / name) for key, name in ANCHOR_TEXTS.items()}
    required_keys = ("total_draft", "max_benefit_parallel_slice")
    required_present = anchor_root.is_dir() and all(
        refs[key]["exists"] for key in required_keys
    )
    return {
        "anchor_package_root": str(anchor_root),
        "source_anchor_role": "desktop current human intent package",
        "text_refs": refs,
        "required_text_refs": list(required_keys),
        "optional_text_refs": [
            key for key in refs.keys() if key not in set(required_keys)
        ],
        "source_anchor_complete": required_present,
    }


def runtime_refs(runtime: Path) -> dict[str, dict[str, Any]]:
    return {key: json_ref(runtime / relative) for key, relative in RUNTIME_REF_PATHS.items()}


def output_paths(repo: Path, runtime: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(
            runtime / "state" / "source_anchor_gap_continuation" / "latest.json"
        ),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / "source_anchor_gap_continuation_20260702.md"
        ),
        "schema": str(
            repo / "contracts" / "schemas" / "codex_s_source_anchor_gap_continuation.v1.json"
        ),
        "writer": str(repo / "services" / "agent_runtime" / "source_anchor_gap_continuation.py"),
        "tests": str(repo / "tests" / "seedcortex" / "test_source_anchor_gap_continuation.py"),
        "verifier": str(repo / "scripts" / "verify_source_anchor_gap_continuation.ps1"),
    }


def decide_next_loop_packet(
    *,
    live_backend_foreground_poll_required: bool,
    explicit_user_stop_requested: bool,
    continuation_mode_active: bool,
    source_anchor_complete: bool,
    runtime_ref_complete: bool,
) -> dict[str, Any]:
    if live_backend_foreground_poll_required:
        return {
            "should_continue_loop": False,
            "front_gate": "live_backend_watch_front_gate",
            "continue_dispatch_expected": False,
            "inactive_reason": "live_backend_watch_requires_foreground_poll_first",
            "action": "poll live backend until terminal or no-growth, then run source-anchor gap continuation",
            "named_blocker": "",
        }
    if explicit_user_stop_requested:
        return {
            "should_continue_loop": False,
            "front_gate": "explicit_user_stop_override",
            "continue_dispatch_expected": False,
            "inactive_reason": "explicit_user_stop",
            "action": "do not continue until user resumes",
            "named_blocker": "",
        }
    if not continuation_mode_active:
        return {
            "should_continue_loop": False,
            "front_gate": "ordinary_checkpoint_stop_allowed",
            "continue_dispatch_expected": False,
            "inactive_reason": "ordinary_discussion_without_no_stop_intent",
            "action": "ordinary discussion can stop; do not manufacture worker evidence",
            "named_blocker": "",
        }
    if not source_anchor_complete:
        return {
            "should_continue_loop": False,
            "front_gate": "source_anchor_gap_continuation",
            "continue_dispatch_expected": False,
            "inactive_reason": "source_anchor_missing",
            "action": "restore or name missing desktop anchor package before dispatch",
            "named_blocker": "CODEX_S_SOURCE_ANCHOR_MISSING",
        }
    if not runtime_ref_complete:
        return {
            "should_continue_loop": False,
            "front_gate": "source_anchor_gap_continuation",
            "continue_dispatch_expected": False,
            "inactive_reason": "runtime_ref_missing_or_invalid",
            "action": "repair focused runtime evidence refs before dispatch",
            "named_blocker": "CODEX_S_RUNTIME_REF_GAP",
        }
    return {
        "should_continue_loop": True,
        "front_gate": "source_anchor_gap_continuation",
        "continue_dispatch_expected": True,
        "inactive_reason": "",
        "action": (
            "restore -> recompute max-benefit frontier -> dispatch useful independent lanes "
            "-> poll -> fan-in -> verify/evidence/readback -> recompute -> next wave"
        ),
        "named_blocker": "",
    }


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    continuation_mode_active: bool = False,
    explicit_user_stop_requested: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    anchors = source_anchors(Path(anchor_package_root))
    refs = runtime_refs(runtime)
    live_backend_foreground_poll_required = (
        refs["live_backend_watch"].get("foreground_poll_required") is True
    )
    required_ref_names = [
        "live_backend_watch",
        "default_hot_path_intake",
        "artifact_acceptance_queue",
        "metaminute_preflight_reflection",
        "default_parallelism_policy",
        "parallel_dispatch_plan",
        "parallel_fan_in_acceptance",
    ]
    runtime_ref_complete = all(
        refs[name].get("exists") is True and refs[name].get("json_valid") is True
        for name in required_ref_names
    )
    next_packet = decide_next_loop_packet(
        live_backend_foreground_poll_required=live_backend_foreground_poll_required,
        explicit_user_stop_requested=explicit_user_stop_requested,
        continuation_mode_active=continuation_mode_active,
        source_anchor_complete=anchors["source_anchor_complete"],
        runtime_ref_complete=runtime_ref_complete,
    )
    checks = {
        "live_backend_watch_read": refs["live_backend_watch"].get("exists") is True
        and refs["live_backend_watch"].get("json_valid") is True,
        "source_anchor_complete": anchors["source_anchor_complete"],
        "runtime_ref_complete": runtime_ref_complete,
        "ordinary_discussion_can_stop": True,
        "current_no_stop_task_requires_continuation_mode": continuation_mode_active,
        "explicit_stop_overrides": (
            next_packet["front_gate"] == "explicit_user_stop_override"
            if explicit_user_stop_requested
            else True
        ),
        "continue_dispatch_requires_no_live_backend": (
            not next_packet["continue_dispatch_expected"]
            or live_backend_foreground_poll_required is False
        ),
        "stop_guard_not_execution_controller": True,
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "node_id": NODE_ID,
        "status": "source_anchor_gap_continuation_ready",
        "generated_at": now_iso(),
        "adoption_state": "verifier_ready_but_not_hooked",
        "source_anchors": anchors,
        "runtime_refs": refs,
        "source_anchor_complete": anchors["source_anchor_complete"],
        "runtime_ref_complete": runtime_ref_complete,
        "continuation_mode_active": continuation_mode_active,
        "explicit_user_stop_requested": explicit_user_stop_requested,
        "live_backend_foreground_poll_required": live_backend_foreground_poll_required,
        "ordinary_discussion_can_stop": True,
        "no_stop_intent_required_for_dynamic_loop": True,
        "continue_dispatch_expected": next_packet["continue_dispatch_expected"],
        "next_loop_packet": next_packet,
        "stop_guard_layer": "source_anchor_gap_continuation",
        "stop_guard_layer_not_execution_controller": True,
        "main_execution_loop": MAIN_EXECUTION_LOOP,
        "legacy_5d33_transport_pattern_allowed": True,
        "legacy_5d33_authority_allowed": False,
        "output_paths": output_paths(repo, runtime),
        "validation": {"passed": all(checks.values()), "checks": checks},
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        write_json(Path(payload["output_paths"]["runtime_latest"]), payload)
        write_text(Path(payload["output_paths"]["runtime_readback_zh"]), render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Codex S Source Anchor Gap Continuation readback",
            "",
            SENTINEL,
            "",
            f"- status: `{payload['status']}`",
            f"- adoption_state: `{payload['adoption_state']}`",
            f"- source_anchor_complete: {payload['source_anchor_complete']}",
            f"- runtime_ref_complete: {payload['runtime_ref_complete']}",
            f"- continuation_mode_active: {payload['continuation_mode_active']}",
            f"- continue_dispatch_expected: {payload['continue_dispatch_expected']}",
            "",
            "这是一层 Stop 后门守护，不是主执行流程、不是事实源、不是完成判断、不是执行控制器。",
            "live watch / source-anchor gap 只是防停证据层；真正主流程仍是 restore -> dispatch -> poll -> fan-in -> verify/evidence/readback -> recompute -> next_wave。",
            "5d33 的耐久事务/worker/result-wait 只能作为 transport pattern 参考，不能复用旧 owner/PASS/completion gate/latest 权威。",
            "",
            "## next_loop_packet",
            "",
            f"- front_gate: `{payload['next_loop_packet']['front_gate']}`",
            f"- action: {payload['next_loop_packet']['action']}",
            f"- named_blocker: `{payload['next_loop_packet']['named_blocker']}`",
            "",
            SENTINEL,
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--continuation-mode-active", action="store_true")
    parser.add_argument("--explicit-user-stop", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        continuation_mode_active=args.continuation_mode_active,
        explicit_user_stop_requested=args.explicit_user_stop,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "continue_dispatch_expected": payload["continue_dispatch_expected"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
