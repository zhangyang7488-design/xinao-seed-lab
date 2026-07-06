from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any


WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
SCHEMA_VERSION = "xinao.codex_s.worker_dispatch_ledger.v1"
SENTINEL = "SENTINEL:XINAO_WORKER_DISPATCH_LEDGER_VERIFIED_NOT_HOOKED"
LEDGER_ID = "codex-s-worker-dispatch-ledger-20260702"
DEFAULT_WAVE_ID = "codex-s-worker-dispatch-ledger-wave-20260702"
DEFAULT_TASK_ID = WORK_ID
DEFAULT_REPO_ROOT = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
ADOPTION_STATE = "verifier_ready_but_not_hooked"
HOT_PATH_ADOPTION_STATE = "runtime_enforced_hot_path_hooked"
HOT_PATH_BINDING_STATE = "hooked_runtime_entrypoint"
TERMINAL_POLL_STATUSES = {"succeeded", "failed", "blocked", "cancelled"}

REQUIRED_ENTRY_FIELDS = (
    "wave_id",
    "task_id",
    "lane_id",
    "agent_id",
    "provider",
    "mode",
    "dispatch_time",
    "poll_status",
    "artifact_refs",
    "fan_in_decision",
    "next_wave_decision",
    "adoption_state",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


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


def boundary_fields() -> dict[str, bool]:
    return {
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def adoption_boundary(adoption_state: str = ADOPTION_STATE) -> dict[str, str]:
    if adoption_state == HOT_PATH_ADOPTION_STATE:
        return {
            "adoption_state": adoption_state,
            "state_meaning_cn": (
                "本次 task-scoped runtime entrypoint 已把 worker_dispatch_ledger poll "
                "接到 RootIntentLoop/默认热链证据；这是热路径绑定证据，不是 controller、"
                "completion gate 或 source of truth。"
            ),
            "missing_to_next_state_cn": (
                "需要持续由默认 Temporal/LangGraph/S runtime 每波调用，并用事件历史、"
                "fan-in、AAQ 和中文 readback 证明；不能用单波 PASS 代替。"
            ),
        }
    return {
        "adoption_state": ADOPTION_STATE,
        "state_meaning_cn": (
            "已有 schema、writer、focused pytest、verifier、D runtime latest 和中文 readback；"
            "但还没有接入默认热路径、dispatch runtime、hook、API 或 durable workflow。"
        ),
        "missing_to_next_state_cn": (
            "需要由当前 S dispatch/API/workflow/hook 显式调用该 ledger writer，"
            "并用 focused verifier 证明触发路径；本任务不接入。"
        ),
    }


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


def output_paths(runtime_root: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(runtime_root / "state" / "worker_dispatch_ledger" / "latest.json"),
        "poll_latest": str(runtime_root / "state" / "worker_dispatch_ledger" / "poll_latest.json"),
        "runtime_readback_zh": str(
            runtime_root / "readback" / "zh" / "worker_dispatch_ledger_20260702.md"
        ),
    }


def repo_artifact_refs(repo_root: Path, runtime_root: Path) -> list[str]:
    paths = output_paths(runtime_root)
    return [
        str(repo_root / "services" / "agent_runtime" / "worker_dispatch_ledger.py"),
        str(repo_root / "contracts" / "schemas" / "codex_s_worker_dispatch_ledger.v1.json"),
        str(repo_root / "tests" / "seedcortex" / "test_worker_dispatch_ledger.py"),
        str(repo_root / "scripts" / "verify_worker_dispatch_ledger.ps1"),
        paths["runtime_latest"],
        paths["runtime_readback_zh"],
    ]


def _entry(
    *,
    wave_id: str,
    task_id: str,
    lane_id: str,
    agent_id: str,
    provider: str,
    mode: str,
    dispatch_time: str,
    poll_status: str,
    artifact_refs: list[str],
    fan_in_decision: str,
    next_wave_decision: str,
    transport_pattern_ref: str,
) -> dict[str, Any]:
    return {
        "entry_id": f"{wave_id}:{lane_id}",
        "wave_id": wave_id,
        "task_id": task_id,
        "lane_id": lane_id,
        "agent_id": agent_id,
        "provider": provider,
        "mode": mode,
        "dispatch_time": dispatch_time,
        "poll_status": poll_status,
        "artifact_refs": artifact_refs,
        "fan_in_decision": fan_in_decision,
        "next_wave_decision": next_wave_decision,
        "adoption_state": ADOPTION_STATE,
        "transport_pattern_ref": transport_pattern_ref,
        "legacy_5d33_transport_pattern_reused": True,
        "legacy_5d33_owner_reused": False,
        "legacy_5d33_pass_reused": False,
        "legacy_5d33_latest_authority_reused": False,
        **boundary_fields(),
    }


def temporal_worker_activity_entry(
    *,
    wave_id: str,
    task_id: str,
    worker_result: dict[str, Any],
    dispatch_time: str,
) -> dict[str, Any]:
    artifact_refs = [
        str(worker_result.get(key) or "")
        for key in (
            "jsonl_path",
            "final_path",
            "raw_final_path",
            "human_egress_filter_ref",
            "worker_assignment_ref",
        )
        if str(worker_result.get(key) or "").strip()
    ]
    if not artifact_refs:
        artifact_refs = [f"temporal_worker_result:{worker_result.get('worker_task_id') or task_id}"]
    status = str(worker_result.get("status") or "")
    poll_status = (
        "succeeded"
        if status == "activity_gate_checked"
        else "blocked"
        if status == "activity_blocked"
        else "failed"
    )
    entry = _entry(
        wave_id=wave_id,
        task_id=task_id,
        lane_id=f"temporal-codex-worker-turn-{safe_lane_suffix(str(worker_result.get('worker_task_id') or task_id))}",
        agent_id=str(worker_result.get("worker_task_id") or task_id),
        provider="temporal.codex_worker_turn_activity",
        mode="worker",
        dispatch_time=dispatch_time,
        poll_status=poll_status,
        artifact_refs=artifact_refs,
        fan_in_decision="accepted_for_ledger_evidence_only",
        next_wave_decision="requires_upstream_scheduler_explicit_call",
        transport_pattern_ref="temporal_codex_task_workflow_task_scoped_worker_result",
    )
    entry.update(
        {
            "worker_status": status,
            "worker_named_blocker": str(worker_result.get("named_blocker") or ""),
            "task_bound_worker": worker_result.get("task_bound_worker"),
            "expected_marker": str(worker_result.get("expected_marker") or ""),
            "expected_marker_seen": worker_result.get("expected_marker_seen"),
            "activator_ok": worker_result.get("activator_ok"),
            "jsonl_exists": worker_result.get("jsonl_exists"),
            "jsonl_path": str(worker_result.get("jsonl_path") or ""),
            "final_path": str(worker_result.get("final_path") or ""),
            "raw_final_path": str(worker_result.get("raw_final_path") or ""),
            "actual_provider_id": str(worker_result.get("actual_provider_id") or ""),
            "actual_provider_family": str(worker_result.get("actual_provider_family") or ""),
            "actual_carrier_provider_id": str(worker_result.get("actual_carrier_provider_id") or ""),
            "provider_router_active": worker_result.get("provider_router_active") is True,
            "provider_route_reason": str(worker_result.get("provider_route_reason") or ""),
            "execute_worker_turn": worker_result.get("execute_worker_turn") is True,
            "execute_codex_worker_legacy_alias": worker_result.get("execute_codex_worker_legacy_alias") is True,
            "legacy_execute_codex_worker_alias_consumed": (
                worker_result.get("legacy_execute_codex_worker_alias_consumed") is True
            ),
        }
    )
    return entry


def parse_subagent(value: str) -> dict[str, str]:
    if ":" in value:
        agent_id, role = value.split(":", 1)
    else:
        agent_id, role = value, "codex_subagent"
    return {
        "agent_id": agent_id.strip(),
        "role": role.strip() or "codex_subagent",
    }


def safe_lane_suffix(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:80]


def default_ledger_entries(
    *,
    repo_root: Path,
    runtime_root: Path,
    wave_id: str,
    task_id: str,
    dispatch_time: str,
    codex_subagents: list[str] | None = None,
) -> list[dict[str, Any]]:
    artifacts = repo_artifact_refs(repo_root, runtime_root)
    entries = [
        _entry(
            wave_id=wave_id,
            task_id=task_id,
            lane_id="local-worker-dispatch-ledger-writer",
            agent_id="codex_s_current_worker",
            provider="codex.local",
            mode="worker",
            dispatch_time=dispatch_time,
            poll_status="succeeded",
            artifact_refs=artifacts,
            fan_in_decision="accepted_for_ledger_evidence_only",
            next_wave_decision="no_auto_dispatch_not_hot_path",
            transport_pattern_ref="legacy_5d33_transport_pattern_reference_only",
        ),
    ]
    subagents = [parse_subagent(item) for item in (codex_subagents or []) if item.strip()]
    if subagents:
        for index, subagent in enumerate(subagents, start=1):
            role = safe_lane_suffix(subagent["role"])
            entries.append(
                _entry(
                    wave_id=wave_id,
                    task_id=task_id,
                    lane_id=f"codex-subagent-dispatch-record-{index}-{role}",
                    agent_id=subagent["agent_id"],
                    provider="codex.subagent",
                    mode="subagent",
                    dispatch_time=dispatch_time,
                    poll_status="dispatched",
                    artifact_refs=artifacts[:4],
                    fan_in_decision="staged_candidate_only",
                    next_wave_decision="requires_upstream_scheduler_explicit_call",
                    transport_pattern_ref="legacy_5d33_transport_pattern_reference_only",
                )
            )
    else:
        entries.append(
            _entry(
                wave_id=wave_id,
                task_id=task_id,
                lane_id="codex-subagent-dispatch-record",
                agent_id="codex_s_subagent_lane",
                provider="codex.subagent",
                mode="subagent",
                dispatch_time=dispatch_time,
                poll_status="planned_not_spawned",
                artifact_refs=artifacts[:4],
                fan_in_decision="not_applicable_not_spawned",
                next_wave_decision="requires_upstream_scheduler_explicit_call",
                transport_pattern_ref="legacy_5d33_transport_pattern_reference_only",
            )
        )
    entries.extend(
        [
        _entry(
            wave_id=wave_id,
            task_id=task_id,
            lane_id="dp-sidecar-dispatch-record",
            agent_id="deepseek_dp_sidecar_lane",
            provider="legacy.deepseek_dp_sidecar",
            mode="dp_sidecar_execution",
            dispatch_time=dispatch_time,
            poll_status="planned_not_spawned",
            artifact_refs=artifacts[:4],
            fan_in_decision="not_applicable_not_spawned",
            next_wave_decision="requires_upstream_scheduler_explicit_call",
            transport_pattern_ref="legacy_5d33_transport_pattern_reference_only",
        ),
        _entry(
            wave_id=wave_id,
            task_id=task_id,
            lane_id="dp-search-dispatch-record",
            agent_id="deepseek_search_sidecar_lane",
            provider="deepseek.search_sidecar",
            mode="dp_search",
            dispatch_time=dispatch_time,
            poll_status="planned_not_spawned",
            artifact_refs=artifacts[:4],
            fan_in_decision="not_applicable_not_spawned",
            next_wave_decision="requires_upstream_scheduler_explicit_call",
            transport_pattern_ref="legacy_5d33_transport_pattern_reference_only",
        ),
        ]
    )
    return entries


def build_validation(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("dispatch_entries", [])
    if not isinstance(entries, list):
        entries = []
    required_fields_present = all(
        isinstance(entry, dict) and all(field in entry for field in REQUIRED_ENTRY_FIELDS)
        for entry in entries
    )
    modes = {entry.get("mode") for entry in entries if isinstance(entry, dict)}
    artifact_text = "\n".join(
        ref
        for entry in entries
        if isinstance(entry, dict)
        for ref in entry.get("artifact_refs", [])
        if isinstance(ref, str)
    )
    fan_in_decisions = {
        entry.get("fan_in_decision") for entry in entries if isinstance(entry, dict)
    }
    next_wave_decisions = {
        entry.get("next_wave_decision") for entry in entries if isinstance(entry, dict)
    }
    runtime_invocation = payload.get("runtime_entrypoint_invocation", {})
    if not isinstance(runtime_invocation, dict):
        runtime_invocation = {}
    runtime_invoked = runtime_invocation.get("invoked") is True
    runtime_hooked_count = payload.get("summary", {}).get("hooked_runtime_entrypoint_count")
    poll_entries = payload.get("poll_entries", [])
    if not isinstance(poll_entries, list):
        poll_entries = []
    succeeded_entry_ids = payload.get("succeeded_entry_ids", [])
    if not isinstance(succeeded_entry_ids, list):
        succeeded_entry_ids = []

    def legacy_boundary_ok(entry: dict[str, Any]) -> bool:
        legacy_transport = entry.get("legacy_5d33_transport_pattern_reused")
        return (
            legacy_transport in {True, False}
            and entry.get("legacy_5d33_owner_reused") is False
            and entry.get("legacy_5d33_pass_reused") is False
            and entry.get("legacy_5d33_latest_authority_reused") is False
        )

    checks = {
        "schema_version_locked": payload.get("schema_version") == SCHEMA_VERSION,
        "work_id_locked": payload.get("work_id") == WORK_ID,
        "route_profile_locked": payload.get("route_profile") == ROUTE_PROFILE,
        "top_level_adoption_state_fixed": payload.get("adoption_state")
        in {ADOPTION_STATE, HOT_PATH_ADOPTION_STATE},
        "hot_path_adoption_requires_runtime_entrypoint": (
            payload.get("adoption_state") != HOT_PATH_ADOPTION_STATE
            or (
                runtime_invoked
                and runtime_invocation.get("runtime_enforced") is True
                and payload.get("source_kind") == "worker_dispatch_ledger_poll"
                and int(payload.get("succeeded_count") or 0) > 0
                and payload.get("hot_path_binding", {}).get("state") == HOT_PATH_BINDING_STATE
                and payload.get("hot_path_binding", {}).get("runtime_enforced") is True
                and payload.get("machine_loop", {}).get("auto_dispatch_performed") is True
            )
        ),
        "entry_adoption_state_fixed": all(
            isinstance(entry, dict) and entry.get("adoption_state") == ADOPTION_STATE
            for entry in entries
        ),
        "required_dispatch_fields_present": required_fields_present,
        "worker_subagent_dp_modes_present": {"worker", "subagent", "dp_sidecar_execution"}.issubset(
            modes
        ),
        "artifact_refs_nonempty": all(
            isinstance(entry, dict)
            and isinstance(entry.get("artifact_refs"), list)
            and bool(entry.get("artifact_refs"))
            for entry in entries
        ),
        "legacy_5d33_transport_only": all(
            isinstance(entry, dict) and legacy_boundary_ok(entry)
            for entry in entries
        ),
        "fan_in_never_accepts_completion": "completion_claim" not in fan_in_decisions,
        "next_wave_not_auto_hot_path": all(
            isinstance(decision, str)
            and decision
            in {
                "no_auto_dispatch_not_hot_path",
                "requires_upstream_scheduler_explicit_call",
                "ledger_succeeded_drives_default_auto_dispatch",
                "blocked_waiting_worker_result",
            }
            for decision in next_wave_decisions
        ),
        "durable_parallel_wave_packet_not_referenced": "durable_parallel_wave_packet"
        not in artifact_text,
        "runtime_paths_are_worker_dispatch_ledger": (
            payload.get("output_paths", {}).get("runtime_latest", "").endswith(
                r"state\worker_dispatch_ledger\latest.json"
            )
            or payload.get("output_paths", {}).get("runtime_latest", "").endswith(
                "state/worker_dispatch_ledger/latest.json"
            )
        )
        and (
            payload.get("output_paths", {}).get("runtime_readback_zh", "").endswith(
                r"readback\zh\worker_dispatch_ledger_20260702.md"
            )
            or payload.get("output_paths", {}).get("runtime_readback_zh", "").endswith(
                "readback/zh/worker_dispatch_ledger_20260702.md"
            )
        ),
        "completion_claim_blocked": payload.get("completion_claim_allowed") is False,
        "not_source_of_truth": payload.get("not_source_of_truth") is True,
        "not_completion_decision": payload.get("not_completion_decision") is True,
        "not_execution_controller": payload.get("not_execution_controller") is True,
        "runtime_entrypoint_invocation_boundary": (
            isinstance(runtime_invocation.get("invoked_by"), str)
            and isinstance(runtime_invocation.get("runtime_enforced_scope"), str)
            and runtime_invocation.get("not_execution_controller") is True
            and runtime_invocation.get("not_completion_gate") is True
        ),
        "runtime_entrypoint_count_matches_invocation": runtime_hooked_count
        == (1 if runtime_invoked else 0),
        "runtime_entrypoint_scope_present_when_invoked": (
            not runtime_invoked
            or (
                bool(runtime_invocation.get("invoked_by"))
                and bool(runtime_invocation.get("runtime_enforced_scope"))
                and runtime_invocation.get("runtime_enforced") is True
            )
        ),
        "poll_entries_terminal_when_present": all(
            isinstance(entry, dict)
            and str(entry.get("poll_status") or "") in TERMINAL_POLL_STATUSES
            and entry.get("source_kind") == "worker_dispatch_ledger_poll"
            and entry.get("poll_source") == "worker_dispatch_ledger_poll"
            for entry in poll_entries
        ),
        "succeeded_count_matches_poll_entries": int(payload.get("succeeded_count") or 0)
        == len(
            [
                entry
                for entry in poll_entries
                if isinstance(entry, dict) and entry.get("poll_status") == "succeeded"
            ]
        )
        == len(succeeded_entry_ids),
        "no_driver_synthetic_succeeded": (
            payload.get("driver_synthetic_succeeded_allowed") is False
            and all(
                isinstance(entry, dict)
                and entry.get("synthetic_succeeded_by_driver") is False
                for entry in poll_entries
            )
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "validated_at": now_iso(),
    }


def build_poll_entries(
    entries: list[dict[str, Any]],
    *,
    lane_id_prefixes: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not lane_id_prefixes:
        return []
    poll_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        lane_id = str(entry.get("lane_id") or "")
        if lane_id_prefixes and not lane_id.startswith(lane_id_prefixes):
            continue
        poll_status = str(entry.get("poll_status") or "")
        if poll_status not in TERMINAL_POLL_STATUSES:
            continue
        poll_entry = {
            **entry,
            "source_kind": "worker_dispatch_ledger_poll",
            "poll_source": "worker_dispatch_ledger_poll",
            "terminal_state": poll_status,
            "synthetic_succeeded_by_driver": False,
            "driver_synthetic_succeeded_allowed": False,
            "completion_claim_allowed": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
        }
        if poll_status == "succeeded":
            poll_entry["fan_in_decision"] = "accepted_for_next_wave_dispatch"
            poll_entry["next_wave_decision"] = "ledger_succeeded_drives_default_auto_dispatch"
        poll_entries.append(poll_entry)
    return poll_entries


def build_worker_dispatch_ledger(
    *,
    repo_root: str | Path = DEFAULT_REPO_ROOT,
    runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
    wave_id: str = DEFAULT_WAVE_ID,
    task_id: str = DEFAULT_TASK_ID,
    codex_subagents: list[str] | None = None,
    extra_entries: list[dict[str, Any]] | None = None,
    poll_scope_lane_id_prefixes: tuple[str, ...] = (),
    auto_dispatch_performed: bool = False,
    runtime_entrypoint_invocation: dict[str, Any] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    repo = Path(repo_root)
    runtime = Path(runtime_root)
    generated_at = now_iso()
    paths = output_paths(runtime)
    entries = default_ledger_entries(
        repo_root=repo,
        runtime_root=runtime,
        wave_id=wave_id,
        task_id=task_id,
        dispatch_time=generated_at,
        codex_subagents=codex_subagents,
    )
    entries.extend(list(extra_entries or []))
    runtime_invocation = dict(runtime_entrypoint_invocation or {})
    hooked_count = 1 if runtime_invocation.get("invoked_by") else 0
    poll_entries = build_poll_entries(
        entries,
        lane_id_prefixes=tuple(poll_scope_lane_id_prefixes or ()),
    )
    succeeded_entries = [
        entry for entry in poll_entries if entry.get("poll_status") == "succeeded"
    ]
    hot_path_runtime_enforced = (
        bool(poll_entries)
        and runtime_invocation.get("runtime_enforced") is True
        and auto_dispatch_performed is True
    )
    top_level_adoption_state = (
        HOT_PATH_ADOPTION_STATE if hot_path_runtime_enforced else ADOPTION_STATE
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "ledger_id": LEDGER_ID,
        "wave_id": wave_id,
        "task_id": task_id,
        "generated_at": generated_at,
        "status": (
            "worker_dispatch_ledger_poll_ready"
            if poll_entries
            else "worker_dispatch_ledger_verifier_passed_not_hooked"
        ),
        "ledger_role": "task_scoped_worker_subagent_dp_dispatch_read_model",
        "adoption_state": top_level_adoption_state,
        "adoption_boundary": adoption_boundary(top_level_adoption_state),
        "authority_boundary": {
            "is_controller": False,
            "is_completion_gate": False,
            "is_source_of_truth": False,
            "old_5d33_owner_pass_latest_authority_allowed": False,
        },
        "legacy_5d33_boundary": {
            "transport_pattern_reuse_allowed": True,
            "owner_reuse_allowed": False,
            "pass_reuse_allowed": False,
            "latest_authority_reuse_allowed": False,
            "compat_runtime_root": r"D:\XINAO_CLEAN_RUNTIME",
            "compat_runtime_role": "reference_only",
        },
        "dispatch_entries": entries,
        "runtime_entrypoint_invocation": {
            "invoked_by": str(runtime_invocation.get("invoked_by") or ""),
            "invoked": bool(runtime_invocation.get("invoked_by")),
            "runtime_enforced_scope": str(runtime_invocation.get("runtime_enforced_scope") or ""),
            "runtime_enforced": runtime_invocation.get("runtime_enforced") is True,
            "not_execution_controller": True,
            "not_completion_gate": True,
        },
        "hot_path_binding": {
            "state": HOT_PATH_BINDING_STATE
            if hot_path_runtime_enforced
            else ADOPTION_STATE,
            "runtime_enforced": hot_path_runtime_enforced,
            "runtime_enforced_scope": str(
                runtime_invocation.get("runtime_enforced_scope") or ""
            ),
            "source_kind": "worker_dispatch_ledger_poll",
            "default_auto_dispatch_allowed": bool(succeeded_entries),
            "top_level_adoption_state_remains_read_model": True,
        },
        "source_kind": "worker_dispatch_ledger_poll" if poll_entries else "dispatch_read_model",
        "poll_source": "worker_dispatch_ledger_poll" if poll_entries else "",
        "poll_entries": poll_entries,
        "succeeded_entries": succeeded_entries,
        "poll_result_summary": {
            "entry_count": len(poll_entries),
            "succeeded_count": len(succeeded_entries),
            "failed_or_blocked_count": len(poll_entries) - len(succeeded_entries),
            "source_kind": "worker_dispatch_ledger_poll",
        },
        "succeeded_count": len(succeeded_entries),
        "succeeded_entry_ids": [
            str(entry.get("entry_id") or "") for entry in succeeded_entries
        ],
        "driver_synthetic_succeeded_allowed": False,
        "summary": {
            "entry_count": len(entries),
            "poll_entry_count": len(poll_entries),
            "succeeded_count": len(succeeded_entries),
            "worker_entry_count": sum(entry["mode"] == "worker" for entry in entries),
            "subagent_entry_count": sum(entry["mode"] == "subagent" for entry in entries),
            "dp_sidecar_entry_count": sum(
                entry["mode"] == "dp_sidecar_execution" for entry in entries
            ),
            "spawned_external_agent_count": 0,
            "hooked_runtime_entrypoint_count": hooked_count,
        },
        "machine_loop": {
            "restore": "current_s_work_id_and_task_scope",
            "dispatch": "ledger_entries_recorded",
            "poll": "poll_status_recorded_per_entry",
            "fan_in": (
                "worker_dispatch_ledger_poll"
                if poll_entries
                else "ledger_evidence_only_not_completion"
            ),
            "verify_evidence_readback": "focused_pytest_and_verify_script",
            "recompute_capacity": (
                "default_auto_dispatch_capacity_recompute"
                if poll_entries
                else "not_performed_by_this_ledger"
            ),
            "next_wave": (
                "ledger_succeeded_drives_default_auto_dispatch"
                if succeeded_entries
                else "requires_upstream_scheduler_explicit_call"
            ),
            "auto_dispatch_performed": auto_dispatch_performed,
        },
        "output_paths": paths,
        "default_boundary": boundary_fields(),
        **boundary_fields(),
    }
    payload["validation"] = build_validation(payload)
    if not payload["validation"]["passed"]:
        payload["status"] = "worker_dispatch_ledger_validation_blocked"
    if write:
        write_json(Path(paths["runtime_latest"]), payload)
        if poll_entries:
            write_json(Path(paths["poll_latest"]), payload)
        write_text(Path(paths["runtime_readback_zh"]), render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    adoption = payload["adoption_boundary"]
    summary = payload["summary"]
    lines = [
        "# Worker Dispatch Ledger readback",
        "",
        "SENTINEL:CODEX_S_WORKER_DISPATCH_LEDGER_20260702",
        "",
        "## 当前状态",
        "",
        f"- status: `{payload['status']}`",
        f"- validation_passed: {payload['validation']['passed']}",
        f"- work_id: `{payload['work_id']}`",
        f"- wave_id: `{payload['wave_id']}`",
        f"- task_id: `{payload['task_id']}`",
        f"- entry_count: {summary['entry_count']}",
        "",
        "## 边界",
        "",
        f"- 能力采纳状态：{payload['adoption_state']}。",
        f"- 这代表：{adoption['state_meaning_cn']}",
        f"- 还缺什么才能进入下一状态：{adoption['missing_to_next_state_cn']}",
        "- 它不是 controller，不是 completion gate，不是 source of truth。",
        "- 旧 5d33 只复用 transport pattern；不复用 owner、PASS 或 latest authority。",
        "",
        "## Ledger entries",
        "",
    ]
    for entry in payload["dispatch_entries"]:
        lines.extend(
            [
                f"- lane_id: `{entry['lane_id']}`",
                f"  - provider: `{entry['provider']}`",
                f"  - mode: `{entry['mode']}`",
                f"  - poll_status: `{entry['poll_status']}`",
                f"  - fan_in_decision: `{entry['fan_in_decision']}`",
                f"  - next_wave_decision: `{entry['next_wave_decision']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## 输出路径",
            "",
            f"- latest: `{payload['output_paths']['runtime_latest']}`",
            f"- readback: `{payload['output_paths']['runtime_readback_zh']}`",
            "",
            payload["sentinel"],
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--wave-id", default=DEFAULT_WAVE_ID)
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--codex-subagent", action="append", default=[])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build_worker_dispatch_ledger(
        repo_root=args.repo_root,
        runtime_root=args.runtime_root,
        wave_id=args.wave_id,
        task_id=args.task_id,
        codex_subagents=args.codex_subagent,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "validation_passed": payload["validation"]["passed"],
                "adoption_state": payload["adoption_state"],
                "runtime_latest": payload["output_paths"]["runtime_latest"],
                "runtime_readback_zh": payload["output_paths"]["runtime_readback_zh"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(payload["sentinel"])
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
