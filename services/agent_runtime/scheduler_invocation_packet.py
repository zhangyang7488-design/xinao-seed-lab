from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.scheduler_invocation_packet.v1"
SENTINEL = "SENTINEL:XINAO_SCHEDULER_INVOCATION_PACKET_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
ADOPTION_STATE = "verifier_ready_but_not_hooked"
NO_ACTUAL_LANE_BLOCKER = "SCHEDULER_INVOCATION_PACKET_NO_ACTUAL_SPAWNED_LANE_REF"

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
READBACK_NAME = "scheduler_invocation_packet_20260703.md"

LANE_KINDS = {
    "current_parent_codex_subagent",
    "callable_scheduler_entrypoint_lane",
    "dp_sidecar_execution",
    "local_tool_lane",
    "temporal_activity_lane",
    "other_actual_lane",
}


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
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def json_ref(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return ref
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        ref.update({"json_valid": False, "json_error": str(exc)})
        return ref
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    ref.update(
        {
            "json_valid": True,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "sentinel": payload.get("sentinel"),
            "adoption_state": payload.get("adoption_state"),
            "validation_passed": validation.get("passed"),
            "runtime_enforced": payload.get("runtime_enforced"),
            "default_runtime_scheduler_invoked": payload.get(
                "default_runtime_scheduler_invoked"
            ),
            "completion_claim_allowed": payload.get("completion_claim_allowed"),
            "not_execution_controller": payload.get("not_execution_controller"),
        }
    )
    return ref


def output_paths(repo_root: Path, runtime_root: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(
            runtime_root / "state" / "scheduler_invocation_packet" / "latest.json"
        ),
        "runtime_readback_zh": str(runtime_root / "readback" / "zh" / READBACK_NAME),
        "schema": str(
            repo_root
            / "contracts"
            / "schemas"
            / "codex_s_scheduler_invocation_packet.v1.json"
        ),
        "writer": str(
            repo_root / "services" / "agent_runtime" / "scheduler_invocation_packet.py"
        ),
        "tests": str(
            repo_root / "tests" / "seedcortex" / "test_scheduler_invocation_packet.py"
        ),
        "verifier": str(repo_root / "scripts" / "verify_scheduler_invocation_packet.ps1"),
    }


def runtime_ref_paths(runtime_root: Path) -> dict[str, Path]:
    state = runtime_root / "state"
    return {
        "live_backend_watch": state / "codex_s_live_backend_watch" / "latest.json",
        "worker_dispatch_ledger": state / "worker_dispatch_ledger" / "latest.json",
        "parallel_fan_in_acceptance": state / "parallel_fan_in_acceptance" / "latest.json",
        "artifact_acceptance_queue": state / "artifact_acceptance_queue" / "latest.json",
        "durable_parallel_wave_packet": state / "durable_parallel_wave_packet" / "latest.json",
        "scheduler_spawned_lane_evidence": (
            state / "scheduler_spawned_lane_evidence" / "latest.json"
        ),
    }


def ref_value(value: str | None) -> dict[str, Any]:
    clean = str(value or "").strip()
    return {"ref": clean, "provided": bool(clean)}


def _parse_lane_arg(value: str) -> dict[str, Any]:
    raw = value.strip()
    if not raw:
        return {}
    if ":" in raw:
        lane_kind, lane_ref = raw.split(":", 1)
        lane_kind = lane_kind.strip() or "current_parent_codex_subagent"
        lane_ref = lane_ref.strip()
    else:
        lane_kind = "current_parent_codex_subagent"
        lane_ref = raw
    if lane_kind not in LANE_KINDS:
        lane_kind = "other_actual_lane"
    return {
        "lane_kind": lane_kind,
        "lane_ref": lane_ref,
        "actual_ref": True,
        "source": "caller_provided_actual_lane_ref",
        "spawned_by": "current_parent_codex_or_callable_scheduler_entrypoint",
        "poll_status": "dispatched",
        "dispatch_status": "dispatched",
        "not_execution_controller": True,
    }


def normalize_spawned_lanes(
    spawned_lanes: list[dict[str, Any] | str] | None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in spawned_lanes or []:
        if isinstance(item, str):
            lane = _parse_lane_arg(item)
        elif isinstance(item, dict):
            lane_ref = str(item.get("lane_ref") or item.get("ref") or "").strip()
            lane_kind = str(item.get("lane_kind") or "current_parent_codex_subagent").strip()
            if lane_kind not in LANE_KINDS:
                lane_kind = "other_actual_lane"
            lane = {
                "lane_kind": lane_kind,
                "lane_ref": lane_ref,
                "actual_ref": item.get("actual_ref", True) is True,
                "source": str(item.get("source") or "caller_provided_actual_lane_ref"),
                "spawned_by": str(
                    item.get("spawned_by")
                    or "current_parent_codex_or_callable_scheduler_entrypoint"
                ),
                "poll_status": str(item.get("poll_status") or "dispatched"),
                "dispatch_status": str(item.get("dispatch_status") or "dispatched"),
                "not_execution_controller": item.get("not_execution_controller", True) is True,
            }
            for optional_key in (
                "scheduler_invocation_ref",
                "poll_ref",
                "fan_in_ref",
                "evidence_ref",
                "readback_ref",
                "agent_id",
                "role",
            ):
                if item.get(optional_key):
                    lane[optional_key] = str(item[optional_key])
        else:
            lane = {}
        if lane.get("lane_ref"):
            normalized.append(lane)
    return normalized


def actual_lane_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    lanes = payload.get("spawned_lanes")
    if not isinstance(lanes, list):
        return []
    return [
        lane
        for lane in lanes
        if isinstance(lane, dict)
        and str(lane.get("lane_ref") or "").strip()
        and lane.get("actual_ref") is True
    ]


def _has_ref(ref: Any) -> bool:
    return isinstance(ref, dict) and bool(
        str(ref.get("ref") or ref.get("path") or ref.get("id") or "").strip()
    )


def build_validation(payload: dict[str, Any]) -> dict[str, Any]:
    lanes = actual_lane_refs(payload)
    lane_count = len(lanes)
    spawned_status = payload.get("status") == "spawned_lane_refs_recorded"
    blocked_status = payload.get("status") == "blocked/planned_only"
    scheduler_refs = (
        payload.get("scheduler_invocation_refs")
        if isinstance(payload.get("scheduler_invocation_refs"), dict)
        else {}
    )
    parent_ref = scheduler_refs.get("current_parent_codex_invocation_ref")
    callable_ref = scheduler_refs.get("callable_scheduler_invocation_ref")
    dp_launcher_ref = scheduler_refs.get("dp_launcher_ref")
    hook_ref = scheduler_refs.get("default_runtime_scheduler_hook_ref")
    poll_refs = payload.get("poll_refs") if isinstance(payload.get("poll_refs"), dict) else {}
    fan_in_refs = payload.get("fan_in_refs") if isinstance(payload.get("fan_in_refs"), dict) else {}
    evidence_refs = (
        payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), dict) else {}
    )
    readback_refs = (
        payload.get("readback_refs") if isinstance(payload.get("readback_refs"), dict) else {}
    )
    dp_lane_count = len(
        [lane for lane in lanes if lane.get("lane_kind") == "dp_sidecar_execution"]
    )
    scheduler_spawned_lane_refs = payload.get("scheduler_spawned_lane_refs")
    if not isinstance(scheduler_spawned_lane_refs, list):
        scheduler_spawned_lane_refs = []
    checks = {
        "schema_version_locked": payload.get("schema_version") == SCHEMA_VERSION,
        "sentinel_locked": payload.get("sentinel") == SENTINEL,
        "work_id_locked": payload.get("work_id") == WORK_ID,
        "route_profile_locked": payload.get("route_profile") == ROUTE_PROFILE,
        "adoption_state_not_promoted": payload.get("adoption_state") == ADOPTION_STATE,
        "legacy_5d33_reference_only": payload.get("legacy_5d33_role") == "reference_only",
        "legacy_5d33_owner_not_reused": payload.get("legacy_5d33_owner_reused") is False,
        "runtime_enforced_false": payload.get("runtime_enforced") is False,
        "default_runtime_scheduler_invoked_false": payload.get(
            "default_runtime_scheduler_invoked"
        )
        is False,
        "scheduler_invoked_matches_actual_lane_refs": payload.get("scheduler_invoked")
        is (lane_count > 0),
        "invoked_by_present_when_scheduler_invoked": (
            payload.get("scheduler_invoked") is not True
            or bool(str(payload.get("invoked_by") or "").strip())
        ),
        "invocation_scope_present_when_scheduler_invoked": (
            payload.get("scheduler_invoked") is not True
            or bool(str(payload.get("invocation_scope") or "").strip())
        ),
        "parent_dispatch_invoked_requires_parent_ref": (
            payload.get("parent_dispatch_invoked") is not True or _has_ref(parent_ref)
        ),
        "callable_scheduler_ref_bound_when_provided": (
            not _has_ref(callable_ref)
            or str(payload.get("callable_scheduler_invocation_ref") or "")
            == str(callable_ref.get("ref") or "")
        ),
        "default_runtime_scheduler_invoked_requires_hook_ref": (
            payload.get("default_runtime_scheduler_invoked") is not True or _has_ref(hook_ref)
        ),
        "completion_claim_blocked": payload.get("completion_claim_allowed") is False,
        "phase0_completion_claim_blocked": payload.get("phase0_completion_claim_allowed")
        is False,
        "not_execution_controller": payload.get("not_execution_controller") is True,
        "spawned_lanes_array": isinstance(payload.get("spawned_lanes"), list),
        "scheduler_spawned_lane_refs_array": isinstance(
            payload.get("scheduler_spawned_lane_refs"), list
        ),
        "spawned_lane_count_matches_actual_refs": payload.get("spawned_lane_count")
        == lane_count,
        "scheduler_spawned_lane_refs_match_actual_refs": len(scheduler_spawned_lane_refs)
        == lane_count,
        "actual_spawned_lane_ref_presence_matches_count": payload.get(
            "actual_spawned_lane_ref_present"
        )
        is (lane_count > 0),
        "current_parent_codex_subagent_refs_supported": payload.get(
            "current_parent_codex_subagent_ref_count"
        )
        == len([lane for lane in lanes if lane.get("lane_kind") == "current_parent_codex_subagent"]),
        "spawned_status_requires_actual_lane_ref": not spawned_status or lane_count > 0,
        "no_lane_refs_blocked_planned_only": lane_count > 0
        or (
            blocked_status
            and payload.get("named_blocker") == NO_ACTUAL_LANE_BLOCKER
            and payload.get("spawned_lane_count") == 0
        ),
        "no_lane_refs_cannot_pretend_spawned": not (
            lane_count == 0 and spawned_status
        ),
        "dp_sidecar_execution_lanes_spawned_requires_launcher_ref": (
            payload.get("dp_sidecar_execution_lanes_spawned") is not True
            or _has_ref(dp_launcher_ref)
        ),
        "dp_sidecar_execution_lanes_spawned_flag_matches_launcher": (
            payload.get("dp_sidecar_execution_lanes_spawned")
            == (dp_lane_count > 0 and _has_ref(dp_launcher_ref))
        ),
        "poll_refs_bound": bool(poll_refs.get("live_backend_watch_ref"))
        and bool(poll_refs.get("worker_dispatch_ledger_ref")),
        "fan_in_refs_bound": bool(fan_in_refs.get("parallel_fan_in_acceptance_ref"))
        and bool(fan_in_refs.get("artifact_acceptance_queue_ref"))
        and fan_in_refs.get("direct_fact_promotion_allowed") is False,
        "evidence_refs_bound": bool(evidence_refs.get("runtime_latest"))
        and bool(evidence_refs.get("schema"))
        and bool(evidence_refs.get("writer"))
        and bool(evidence_refs.get("tests"))
        and bool(evidence_refs.get("verifier")),
        "readback_refs_bound": bool(readback_refs.get("runtime_readback_zh"))
        and readback_refs.get("human_visible_readback_required") is True,
    }
    return {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()}


def build_scheduler_invocation_packet(
    *,
    repo_root: str | Path = DEFAULT_REPO_ROOT,
    runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
    spawned_lanes: list[dict[str, Any] | str] | None = None,
    current_parent_codex_invocation_ref: str = "",
    callable_scheduler_invocation_ref: str = "",
    default_runtime_scheduler_hook_ref: str = "",
    dp_launcher_ref: str = "",
    named_blocker: str | None = None,
    status: str | None = None,
    runtime_enforced: bool = False,
    default_runtime_scheduler_invoked: bool = False,
    legacy_5d33_owner_reused: bool = False,
    completion_claim_allowed: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    repo = Path(repo_root)
    runtime = Path(runtime_root)
    paths = output_paths(repo, runtime)
    ref_paths = runtime_ref_paths(runtime)
    runtime_refs = {name: json_ref(path) for name, path in ref_paths.items()}
    lanes = normalize_spawned_lanes(spawned_lanes)
    lane_count = len([lane for lane in lanes if lane.get("actual_ref") is True])
    parent_invocation = ref_value(current_parent_codex_invocation_ref)
    callable_invocation = ref_value(callable_scheduler_invocation_ref)
    dp_launcher = ref_value(dp_launcher_ref)
    dp_sidecar_lane_count = len(
        [lane for lane in lanes if lane.get("lane_kind") == "dp_sidecar_execution"]
    )
    has_actual_lanes = lane_count > 0
    parent_dispatch_invoked = has_actual_lanes and parent_invocation["provided"]
    invocation_scope = (
        "current_parent_codex_parallel_dispatch"
        if parent_dispatch_invoked
        else "callable_scheduler_invocation_packet"
        if has_actual_lanes and callable_invocation["provided"]
        else ""
    )
    invoked_by = (
        "codex_parent.current_turn_max_parallel_dispatch"
        if parent_dispatch_invoked
        else "services.agent_runtime.scheduler_invocation_packet"
        if has_actual_lanes
        else ""
    )
    packet_status = status or (
        "spawned_lane_refs_recorded" if has_actual_lanes else "blocked/planned_only"
    )
    blocker = (
        named_blocker
        if named_blocker is not None
        else ("" if has_actual_lanes else NO_ACTUAL_LANE_BLOCKER)
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "object_id": "scheduler_invocation_packet",
        "generated_at": now_iso(),
        "status": packet_status,
        "adoption_state": ADOPTION_STATE,
        "spawn_evidence_state": packet_status,
        "named_blocker": blocker,
        "scheduler_invoked": has_actual_lanes,
        "invoked_by": invoked_by,
        "invocation_scope": invocation_scope,
        "manual_parent_dispatch": parent_dispatch_invoked,
        "parent_dispatch_invoked": parent_dispatch_invoked,
        "callable_scheduler_invocation_ref": callable_invocation["ref"],
        "scheduler_invocation_refs": {
            "current_parent_codex_invocation_ref": parent_invocation,
            "callable_scheduler_invocation_ref": callable_invocation,
            "default_runtime_scheduler_hook_ref": ref_value(
                default_runtime_scheduler_hook_ref
            ),
            "dp_launcher_ref": dp_launcher,
            "refs_are_task_scoped_evidence": True,
            "refs_are_not_default_runtime_enforcement": True,
        },
        "spawned_lanes": lanes,
        "scheduler_spawned_lane_refs": lanes,
        "spawned_lane_count": lane_count,
        "actual_spawned_lane_ref_present": has_actual_lanes,
        "current_parent_codex_subagent_ref_count": len(
            [
                lane
                for lane in lanes
                if lane.get("lane_kind") == "current_parent_codex_subagent"
                and lane.get("actual_ref") is True
            ]
        ),
        "dp_sidecar_execution_lane_ref_count": dp_sidecar_lane_count,
        "dp_sidecar_execution_lanes_spawned": bool(
            dp_sidecar_lane_count > 0 and dp_launcher["provided"]
        ),
        "poll_refs": {
            "live_backend_watch_ref": runtime_refs["live_backend_watch"],
            "worker_dispatch_ledger_ref": runtime_refs["worker_dispatch_ledger"],
            "poll_required_before_fan_in": True,
            "poll_refs_are_evidence_only": True,
        },
        "fan_in_refs": {
            "parallel_fan_in_acceptance_ref": runtime_refs["parallel_fan_in_acceptance"],
            "artifact_acceptance_queue_ref": runtime_refs["artifact_acceptance_queue"],
            "fan_in_required_before_fact_promotion": True,
            "artifact_acceptance_queue_required": True,
            "direct_fact_promotion_allowed": False,
        },
        "evidence_refs": {
            **paths,
            "durable_parallel_wave_packet_latest": str(
                ref_paths["durable_parallel_wave_packet"]
            ),
            "scheduler_spawned_lane_evidence_latest": str(
                ref_paths["scheduler_spawned_lane_evidence"]
            ),
            "worker_dispatch_ledger_latest": str(ref_paths["worker_dispatch_ledger"]),
        },
        "readback_refs": {
            "runtime_readback_zh": paths["runtime_readback_zh"],
            "human_visible_readback_required": True,
        },
        "adoption_boundary": {
            "adoption_state": ADOPTION_STATE,
            "state_meaning_cn": (
                "这个对象能记录父 Codex 或可调用 scheduler 入口实际传入的 lane refs，"
                "并生成 schema/test/verifier/latest/readback；它还没有接入默认 runtime。"
            ),
            "missing_to_next_state_cn": (
                "需要默认主循环、Temporal/LangGraph 或 S runtime hook 每波真实调用该入口，"
                "并用 focused verifier 证明 trigger path、lane refs、poll、fan-in、evidence/readback 绑定。"
            ),
        },
        "legacy_5d33_role": "reference_only",
        "legacy_5d33_owner_reused": legacy_5d33_owner_reused,
        "runtime_enforced": runtime_enforced,
        "default_runtime_scheduler_invoked": default_runtime_scheduler_invoked,
        "completion_claim_allowed": completion_claim_allowed,
        "phase0_completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    payload["validation"] = build_validation(payload)
    if not payload["validation"]["passed"] and payload["status"] == "spawned_lane_refs_recorded":
        payload["status"] = "scheduler_invocation_packet_validation_blocked"
        payload["spawn_evidence_state"] = payload["status"]
    if write:
        write_json(Path(paths["runtime_latest"]), payload)
        write_text(Path(paths["runtime_readback_zh"]), render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    lanes = payload.get("spawned_lanes") if isinstance(payload.get("spawned_lanes"), list) else []
    lane_lines = [
        f"  - {lane.get('lane_kind')}: `{lane.get('lane_ref')}`"
        for lane in lanes
        if isinstance(lane, dict)
    ]
    if not lane_lines:
        lane_lines = ["  - 无 actual spawned lane ref；只能是 blocked/planned_only。"]
    return "\n".join(
        [
            "# Scheduler Invocation Packet readback",
            "",
            SENTINEL,
            "",
            f"- status: `{payload['status']}`",
            f"- named_blocker: `{payload['named_blocker']}`",
            f"- scheduler_invoked: {payload['scheduler_invoked']}",
            f"- invoked_by: `{payload['invoked_by']}`",
            f"- invocation_scope: `{payload['invocation_scope']}`",
            f"- parent_dispatch_invoked: {payload['parent_dispatch_invoked']}",
            f"- spawned_lane_count: {payload['spawned_lane_count']}",
            f"- current_parent_codex_subagent_ref_count: {payload['current_parent_codex_subagent_ref_count']}",
            f"- dp_sidecar_execution_lanes_spawned: {payload['dp_sidecar_execution_lanes_spawned']}",
            f"- runtime_enforced: {payload['runtime_enforced']}",
            f"- default_runtime_scheduler_invoked: {payload['default_runtime_scheduler_invoked']}",
            f"- completion_claim_allowed: {payload['completion_claim_allowed']}",
            f"- legacy_5d33_owner_reused: {payload['legacy_5d33_owner_reused']}",
            "- spawned_lanes:",
            *lane_lines,
            "",
            "- 这个对象只记录当前父 Codex / 可调用 scheduler 入口实际发起的 lane refs。",
            "- 没有 actual spawned lane ref 时，不允许写成 spawned，只能写 blocked/planned_only。",
            "- 旧 5d33 只能 reference_only；旧 owner/PASS/latest/completion gate 不可复用为 S 权威。",
            "- `runtime_enforced=false`，`default_runtime_scheduler_invoked=false`，它不是 execution controller。",
            "",
            f"- 能力采纳状态：{payload['adoption_state']}。",
            f"- 这代表：{payload['adoption_boundary']['state_meaning_cn']}",
            f"- 还缺什么才能进入下一状态：{payload['adoption_boundary']['missing_to_next_state_cn']}",
            "",
            f"- latest: `{payload['evidence_refs']['runtime_latest']}`",
            f"- verifier: `{payload['evidence_refs']['verifier']}`",
            "",
            SENTINEL,
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--spawned-lane", action="append", default=[])
    parser.add_argument("--current-parent-codex-invocation-ref", default="")
    parser.add_argument("--callable-scheduler-invocation-ref", default="")
    parser.add_argument("--default-runtime-scheduler-hook-ref", default="")
    parser.add_argument("--dp-launcher-ref", default="")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build_scheduler_invocation_packet(
        repo_root=args.repo_root,
        runtime_root=args.runtime_root,
        spawned_lanes=args.spawned_lane,
        current_parent_codex_invocation_ref=args.current_parent_codex_invocation_ref,
        callable_scheduler_invocation_ref=args.callable_scheduler_invocation_ref,
        default_runtime_scheduler_hook_ref=args.default_runtime_scheduler_hook_ref,
        dp_launcher_ref=args.dp_launcher_ref,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "spawned_lane_count": payload["spawned_lane_count"],
                "named_blocker": payload["named_blocker"],
                "runtime_latest": payload["evidence_refs"]["runtime_latest"],
                "runtime_readback_zh": payload["evidence_refs"]["runtime_readback_zh"],
                "validation_passed": payload["validation"]["passed"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
