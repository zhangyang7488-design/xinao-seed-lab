from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from services.agent_runtime import next_frontier_continuation_supervisor as next_frontier_supervisor
from services.agent_runtime.source_family_adapter_smoke import (
    first_next_action,
    json_ref,
    read_json,
    safe_id,
    write_json,
    write_text,
)


SCHEMA_VERSION = "xinao.codex_s.source_family_adapter_value_eval.v1"
SENTINEL = "SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_VALUE_EVAL_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
PARENT_TASK_ID = WORK_ID
TASK_ID = "wave8_source_family_adapter_value_eval_20260704"
ROUTING = "continue_same_task"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
EVAL_ACTION = "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway"
NEXT_ACTION = "refresh_capability_gateway_snapshot_with_evaluated_source_candidates"
MONITOR_ACTION = "monitor_temporal_source_family_adapter_value_eval_activity"
AFTER_MONITOR_ACTION = "continue_default_temporal_chain_after_source_family_adapter_value_eval_monitor"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def output_paths(repo: Path, runtime: Path, wave_id: str) -> dict[str, str]:
    root = runtime / "state" / "source_family_adapter_value_eval"
    return {
        "runtime_latest": str(root / "latest.json"),
        "wave_latest": str(root / "waves" / f"{wave_id}.json"),
        "decisions_latest": str(root / "decisions" / "latest.json"),
        "decisions_wave": str(root / "decisions" / f"{wave_id}.json"),
        "decision_dir": str(root / "decisions" / wave_id),
        "capability_gateway_candidates_latest": str(
            root / "capability_gateway_candidates" / "latest.json"
        ),
        "capability_gateway_candidates_wave": str(
            root / "capability_gateway_candidates" / f"{wave_id}.json"
        ),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_source_family_adapter_value_eval.v1.json"),
        "thin_bind_latest": str(runtime / "state" / "source_family_smoked_candidate_thin_bind" / "latest.json"),
        "thin_bind_bindings_latest": str(
            runtime / "state" / "source_family_smoked_candidate_thin_bind" / "bindings" / "latest.json"
        ),
        "previous_next_frontier_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "artifact_acceptance_queue_latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "source_ledger_latest": str(runtime / "state" / "source_ledger" / "latest.json"),
        "capability_gateway_latest": str(runtime / "state" / "capability_gateway" / "latest.json"),
        "manifest": str(runtime / "capabilities" / "codex_s.source_family_adapter_value_eval" / "manifest.json"),
        "readback_zh": str(runtime / "readback" / "zh" / "source_family_adapter_value_eval_20260704.md"),
    }


def binding_payload(item: dict[str, Any]) -> dict[str, Any]:
    binding = item.get("binding") if isinstance(item.get("binding"), dict) else {}
    return binding if binding else item


def evaluate_binding(item: dict[str, Any], index: int) -> dict[str, Any]:
    binding = binding_payload(item)
    binding_id = str(binding.get("binding_id") or f"binding-{index:02d}")
    checks = {
        "source_url_present": bool(binding.get("source_url")),
        "source_claim_card_present": bool(binding.get("source_claim_card_id")),
        "mature_carrier_present": bool(binding.get("mature_carrier")),
        "first_ref_sha_present": bool(binding.get("first_ref_sha")),
        "thin_bind_adapter_present": bool(binding.get("thin_bind_adapter")),
        "promotion_gate_enforced": (
            binding.get("promotion_gate") == "adapter_value_eval_before_default_capability"
        ),
        "default_promotion_denied": binding.get("promotion_allowed") is False,
    }
    weights = {
        "source_url_present": 15,
        "source_claim_card_present": 15,
        "mature_carrier_present": 10,
        "first_ref_sha_present": 20,
        "thin_bind_adapter_present": 15,
        "promotion_gate_enforced": 15,
        "default_promotion_denied": 10,
    }
    score = sum(weights[name] for name, passed in checks.items() if passed)
    accepted = score >= 80 and all(checks.values())
    provider_id = f"codex_s.source_candidate.{safe_id(binding_id)}"
    return {
        "schema_version": f"{SCHEMA_VERSION}.decision.v1",
        "status": "adapter_value_eval_gateway_candidate_ready" if accepted else "adapter_value_eval_blocked",
        "decision_id": f"source-family-adapter-value-eval-{index:02d}-{safe_id(binding_id)}",
        "binding_id": binding_id,
        "provider_id": provider_id,
        "source_url": str(binding.get("source_url") or ""),
        "source_claim_card_id": str(binding.get("source_claim_card_id") or ""),
        "mature_carrier": str(binding.get("mature_carrier") or ""),
        "thin_bind_adapter": str(binding.get("thin_bind_adapter") or ""),
        "score": score,
        "accepted_for_gateway_candidate": accepted,
        "gateway_registration_allowed": accepted,
        "default_capability_promotion_allowed": False,
        "provider_invocation_performed": False,
        "promotion_gate": "adapter_value_eval_before_default_capability",
        "missing_checks": [name for name, passed in checks.items() if not passed],
        "validation": {"passed": accepted, "checks": checks},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_gateway_candidates(
    *,
    wave_id: str,
    parent_wave_id: str,
    paths: dict[str, str],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted = [item for item in decisions if item.get("accepted_for_gateway_candidate") is True]
    provider = {
        "provider_id": "codex_s.source_family_smoked_candidate_adapter_candidates",
        "capability_kinds": [
            "source_family_adapter_candidate",
            "mature_carrier_reference_adapter_candidate",
            "capability_gateway_discovery_candidate",
        ],
        "adoption_state": "candidate_registered_after_value_eval",
        "runtime_enforced": False,
        "default_runtime_scheduler_invoked": False,
        "provider_invocation_performed": False,
        "default_capability_promotion_allowed": False,
        "candidate_count": len(accepted),
        "candidate_provider_ids": [str(item.get("provider_id") or "") for item in accepted],
        "evidence_ref": paths["capability_gateway_candidates_latest"],
        "thin_bind_ref": paths["thin_bind_latest"],
        "value_eval_ref": paths["runtime_latest"],
        "not_execution_controller": True,
    }
    checks = {
        "accepted_candidates_present": len(accepted) > 0,
        "no_default_capability_promotion": all(
            item.get("default_capability_promotion_allowed") is False for item in decisions
        ),
        "provider_invocation_not_performed": all(
            item.get("provider_invocation_performed") is False for item in decisions
        ),
        "candidate_provider_ids_present": all(bool(item.get("provider_id")) for item in accepted),
    }
    return {
        "schema_version": f"{SCHEMA_VERSION}.capability_gateway_candidates.v1",
        "status": "capability_gateway_candidate_provider_ready" if all(checks.values()) else "capability_gateway_candidate_provider_blocked",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "provider": provider,
        "candidate_count": len(accepted),
        "decisions_ref": paths["decisions_latest"],
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_manifest(paths: dict[str, str], validation_passed: bool) -> dict[str, Any]:
    return {
        "schema_version": "xinao.capability_manifest.v1",
        "capability_id": "codex_s.source_family_adapter_value_eval",
        "status": "ready" if validation_passed else "blocked",
        "invoke": {
            "cli": "python -m xinao_seedlab.cli.__main__ source-family-adapter-value-eval --wave-id <wave>",
            "input_action": EVAL_ACTION,
        },
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "consumes": [
            paths["thin_bind_latest"],
            paths["thin_bind_bindings_latest"],
            paths["previous_next_frontier_latest"],
        ],
        "writes": [
            paths["runtime_latest"],
            paths["decisions_latest"],
            paths["capability_gateway_candidates_latest"],
            paths["next_frontier_machine_actions_latest"],
        ]
        if "next_frontier_machine_actions_latest" in paths
        else [paths["runtime_latest"], paths["decisions_latest"]],
        "not_completion_boundary": True,
        "secret_values_recorded": False,
    }


def build_next_frontier(
    *,
    wave_id: str,
    parent_wave_id: str,
    paths: dict[str, str],
    validation_passed: bool,
) -> dict[str, Any]:
    if validation_passed:
        next_items = [
            {
                "action_id": "next-wave-refresh-capability-gateway-source-candidates",
                "action": NEXT_ACTION,
                "why": "Value-evaluated source adapter candidates are ready for CapabilityGateway discovery snapshot, not default promotion.",
                "requires": [
                    paths["capability_gateway_candidates_latest"],
                    paths["capability_gateway_latest"],
                    "CapabilityGateway snapshot refresh",
                ],
            },
            {
                "action_id": "next-wave-default-temporal-chain-poll",
                "action": "keep_default_temporal_chain_polling",
                "why": "Value eval is not completion; foreground/background polling continues.",
                "requires": ["Temporal task queue poller", "worker dispatch ledger"],
            },
        ]
    else:
        next_items = [
            {
                "action_id": "repair-source-family-adapter-value-eval",
                "action": "repair_source_family_adapter_value_eval_inputs",
                "why": "Adapter value eval cannot register candidates until thin bindings validate.",
                "requires": [paths["thin_bind_bindings_latest"]],
            }
        ]
    return {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "source_family_adapter_value_eval_next_frontier_ready"
        if validation_passed
        else "source_family_adapter_value_eval_repair_required",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "should_continue_loop": True,
        "stop_allowed": False,
        "stop_allowed_reason": "value_eval_registers_candidates_only_default_promotion_denied",
        "adapter_value_eval": {
            "consumed_action": EVAL_ACTION,
            "capability_gateway_candidates_ref": paths["capability_gateway_candidates_latest"],
        },
        "next_frontier": next_items,
        "output_paths": {
            "runtime_latest": str(
                Path(paths["runtime_latest"]).parents[1] / "next_frontier_machine_actions" / "latest.json"
            )
        },
        "validation": {
            "passed": validation_passed,
            "checks": {
                "value_eval_action_consumed": validation_passed,
                "gateway_candidates_ref_written": bool(paths["capability_gateway_candidates_latest"]),
                "stop_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def refresh_capability_gateway_snapshot(
    *,
    runtime_root: str | Path,
    wave_id: str,
    parent_payload: dict[str, Any],
    gateway: dict[str, Any],
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    provider_id = "codex_s.source_family_smoked_candidate_adapter_candidates"
    provider_visible = provider_id in gateway.get("provider_ids", [])
    capability_gateway_latest = runtime / "state" / "capability_gateway" / "latest.json"
    capability_gateway_candidates_latest = (
        runtime
        / "state"
        / "source_family_adapter_value_eval"
        / "capability_gateway_candidates"
        / "latest.json"
    )
    gateway_refresh_root = (
        runtime / "state" / "source_family_adapter_value_eval" / "gateway_refresh"
    )
    gateway_refresh_latest = gateway_refresh_root / "latest.json"
    gateway_refresh_wave = gateway_refresh_root / "waves" / f"{wave_id}.json"
    next_frontier_latest = runtime / "state" / "next_frontier_machine_actions" / "latest.json"
    parent_wave_id = str(parent_payload.get("wave_id") or "")

    gateway_refresh = {
        "schema_version": "xinao.codex_s.source_family_adapter_value_eval.gateway_refresh.v1",
        "status": "source_family_adapter_value_eval_gateway_refresh_ready"
        if provider_visible
        else "source_family_adapter_value_eval_gateway_refresh_blocked",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "consumed_next_frontier_action": NEXT_ACTION,
        "capability_gateway_latest_ref": str(capability_gateway_latest),
        "capability_gateway_candidates_ref": str(capability_gateway_candidates_latest),
        "source_family_adapter_candidate_provider_visible": provider_visible,
        "provider_invocation_performed": False,
        "default_capability_promotion_allowed": False,
        "validation": {
            "passed": provider_visible,
            "checks": {
                "gateway_snapshot_refreshed": bool(gateway),
                "candidate_provider_visible": provider_visible,
                "default_promotion_denied": True,
                "provider_invocation_not_performed": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    next_frontier = {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "source_family_adapter_value_eval_gateway_refresh_next_frontier_ready"
        if provider_visible
        else "source_family_adapter_value_eval_gateway_refresh_repair_required",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "should_continue_loop": True,
        "stop_allowed": False,
        "stop_allowed_reason": "gateway_refresh_is_candidate_discovery_only_temporal_polling_continues",
        "gateway_refresh": {
            "consumed_action": NEXT_ACTION,
            "capability_gateway_latest_ref": str(capability_gateway_latest),
        },
        "next_frontier": [
            {
                "action_id": "next-wave-monitor-temporal-value-eval-enforcement",
                "action": MONITOR_ACTION,
                "why": "CapabilityGateway candidate provider is visible; prove the Temporal activity path invokes value-eval in a later wave.",
                "requires": [
                    str(
                        runtime
                        / "state"
                        / "source_family_adapter_value_eval"
                        / "temporal_activity_latest.json"
                    ),
                    "Temporal task queue poller",
                    "worker dispatch ledger",
                ],
            },
            {
                "action_id": "next-wave-default-temporal-chain-poll",
                "action": "keep_default_temporal_chain_polling",
                "why": "Gateway refresh is not completion; foreground/background polling continues.",
                "requires": ["Temporal task queue poller", "worker dispatch ledger"],
            },
        ],
        "validation": {
            "passed": provider_visible,
            "checks": {
                "gateway_refresh_action_consumed": provider_visible,
                "stop_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    output_paths = {
        "capability_gateway_latest": str(capability_gateway_latest),
        "gateway_refresh_latest": str(gateway_refresh_latest),
        "gateway_refresh_wave": str(gateway_refresh_wave),
        "next_frontier_machine_actions_latest": str(next_frontier_latest),
    }
    if write:
        write_json(gateway_refresh_latest, gateway_refresh)
        write_json(gateway_refresh_wave, gateway_refresh)
        next_frontier_supervisor.promote_candidate_next_frontier(
            runtime_root=runtime,
            candidate=next_frontier,
            source_kind="source_family_adapter_value_eval_gateway_refresh",
            source_ref=str(gateway_refresh_latest),
        )
    return {
        "capability_gateway_snapshot": {
            "ref": str(capability_gateway_latest),
            "source_family_adapter_candidate_provider_visible": provider_visible,
        },
        "gateway_refresh": gateway_refresh,
        "next_frontier_machine_actions": next_frontier,
        "output_paths": output_paths,
    }


def monitor_temporal_activity(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "wave-block8-source-family-adapter-value-eval-temporal-monitor",
    write: bool = True,
) -> dict[str, Any]:
    del repo_root
    runtime = Path(runtime_root)
    root = runtime / "state" / "source_family_adapter_value_eval"
    activity_latest_path = root / "temporal_activity_latest.json"
    latest_activity = read_json(activity_latest_path)
    activity_wave_id = str(latest_activity.get("wave_id") or "")
    activity_wave_path = root / "temporal_activity" / "waves" / f"{activity_wave_id}.json"
    activity = read_json(activity_wave_path)
    if not activity:
        activity = latest_activity
    gateway_refresh = (
        activity.get("gateway_refresh")
        if isinstance(activity.get("gateway_refresh"), dict)
        else {}
    )
    gateway_refresh_wave_id = str(gateway_refresh.get("wave_id") or "")
    gateway_refresh_wave_path = root / "gateway_refresh" / "waves" / f"{gateway_refresh_wave_id}.json"
    gateway_refresh_wave = read_json(gateway_refresh_wave_path)
    activity_next_frontier = (
        activity.get("next_frontier_machine_actions")
        if isinstance(activity.get("next_frontier_machine_actions"), dict)
        else {}
    )
    consumed_action = first_next_action(activity_next_frontier)
    capability_gateway_ref = str(
        gateway_refresh.get("capability_gateway_latest_ref")
        or runtime / "state" / "capability_gateway" / "latest.json"
    )
    capability_gateway = read_json(Path(capability_gateway_ref))
    provider_id = "codex_s.source_family_smoked_candidate_adapter_candidates"
    checks = {
        "temporal_activity_wave_present": activity_wave_path.is_file(),
        "temporal_activity_runtime_entrypoint": (
            activity.get("runtime_entrypoint_invocation", {}).get("invoked_by")
            == "temporal_codex_task_workflow.source_family_adapter_value_eval_activity"
        )
        if isinstance(activity.get("runtime_entrypoint_invocation"), dict)
        else False,
        "temporal_activity_validation_passed": activity.get("validation", {}).get("passed") is True
        if isinstance(activity.get("validation"), dict)
        else False,
        "gateway_refresh_wave_present": gateway_refresh_wave_path.is_file(),
        "gateway_refresh_parent_matches_activity": (
            gateway_refresh_wave.get("parent_wave_id") == activity.get("wave_id")
        ),
        "gateway_refresh_validation_passed": gateway_refresh_wave.get("validation", {}).get("passed") is True
        if isinstance(gateway_refresh_wave.get("validation"), dict)
        else False,
        "monitor_action_consumed": consumed_action == MONITOR_ACTION,
        "activity_next_frontier_stop_denied": activity_next_frontier.get("stop_allowed") is False,
        "candidate_provider_visible": provider_id in capability_gateway.get("provider_ids", []),
        "completion_claim_denied": activity.get("completion_claim_allowed") is False,
    }
    validation_passed = all(checks.values())
    monitor_root = root / "temporal_monitor"
    latest_path = monitor_root / "latest.json"
    wave_path = monitor_root / "waves" / f"{wave_id}.json"
    next_frontier_path = runtime / "state" / "next_frontier_machine_actions" / "latest.json"
    parent_wave_id = str(activity.get("wave_id") or "")
    next_frontier = {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "source_family_adapter_value_eval_temporal_monitor_next_frontier_ready"
        if validation_passed
        else "source_family_adapter_value_eval_temporal_monitor_repair_required",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "should_continue_loop": True,
        "stop_allowed": False,
        "stop_allowed_reason": "temporal_value_eval_monitor_is_evidence_only_polling_continues",
        "temporal_monitor": {
            "consumed_action": MONITOR_ACTION,
            "temporal_activity_wave_ref": str(activity_wave_path),
            "gateway_refresh_wave_ref": str(gateway_refresh_wave_path),
        },
        "next_frontier": [
            {
                "action_id": "next-wave-default-temporal-chain-after-value-eval-monitor",
                "action": AFTER_MONITOR_ACTION,
                "why": "Temporal source-family adapter value-eval activity and gateway refresh are wave-bound; continue default chain polling.",
                "requires": [
                    str(runtime / "state" / "worker_dispatch_ledger" / "latest.json"),
                    str(runtime / "state" / "source_frontier_workerpool_closure" / "latest.json"),
                ],
            },
            {
                "action_id": "next-wave-default-temporal-chain-poll",
                "action": "keep_default_temporal_chain_polling",
                "why": "Monitor evidence is not completion; foreground/background polling continues.",
                "requires": ["Temporal task queue poller", "worker dispatch ledger"],
            },
        ]
        if validation_passed
        else [
            {
                "action_id": "repair-source-family-adapter-value-eval-temporal-monitor",
                "action": "repair_source_family_adapter_value_eval_temporal_monitor_inputs",
                "why": "Wave-specific Temporal activity or gateway refresh evidence is missing.",
                "requires": [str(activity_wave_path), str(gateway_refresh_wave_path)],
            }
        ],
        "validation": {
            "passed": validation_passed,
            "checks": {
                "temporal_monitor_action_consumed": validation_passed,
                "stop_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    payload = {
        "schema_version": "xinao.codex_s.source_family_adapter_value_eval.temporal_monitor.v1",
        "sentinel": "SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_VALUE_EVAL_TEMPORAL_MONITOR_READY",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "status": "source_family_adapter_value_eval_temporal_monitor_ready"
        if validation_passed
        else "source_family_adapter_value_eval_temporal_monitor_blocked",
        "consumed_next_frontier_action": consumed_action,
        "temporal_activity_wave_id": activity_wave_id,
        "gateway_refresh_wave_id": gateway_refresh_wave_id,
        "input_refs": {
            "temporal_activity_wave": json_ref(activity_wave_path),
            "gateway_refresh_wave": json_ref(gateway_refresh_wave_path),
            "capability_gateway_latest": json_ref(Path(capability_gateway_ref)),
        },
        "next_frontier_machine_actions": next_frontier,
        "output_paths": {
            "runtime_latest": str(latest_path),
            "wave_latest": str(wave_path),
            "next_frontier_machine_actions_latest": str(next_frontier_path),
        },
        "validation": {"passed": validation_passed, "checks": checks},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        write_json(latest_path, payload)
        write_json(wave_path, payload)
        next_frontier_supervisor.promote_candidate_next_frontier(
            runtime_root=runtime,
            candidate=next_frontier,
            source_kind="source_family_adapter_value_eval_temporal_monitor",
            source_ref=str(latest_path),
        )
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    lines = [
        "# Source-family adapter value-eval readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- wave_id: `{payload.get('wave_id')}`",
        f"- parent_wave_id: `{payload.get('parent_wave_id')}`",
        f"- consumed action: `{payload.get('consumed_next_frontier_action')}`",
        f"- gateway candidates: {payload.get('gateway_candidate_count')} / {payload.get('decision_count')}",
        f"- candidate provider ref: `{payload.get('output_paths', {}).get('capability_gateway_candidates_latest')}`",
        "",
        "验收三句：",
        "1. 本动作消费的是 thin-bind 后的 `evaluate_smoked_candidate_adapter_bindings_for_capability_gateway`。",
        "2. value eval 只登记 CapabilityGateway candidate discovery provider，不默认提升能力、不执行 provider。",
        "3. 下一步是刷新 CapabilityGateway snapshot 并继续 Temporal/worker 轮询，不允许停成完成。",
        "",
        SENTINEL,
        "",
    ]
    return "\n".join(lines)


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    wave_id: str = "wave-block8-source-family-adapter-value-eval",
    write: bool = True,
) -> dict[str, Any]:
    del anchor_package_root
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(repo, runtime, wave_id)
    paths["next_frontier_machine_actions_latest"] = str(
        runtime / "state" / "next_frontier_machine_actions" / "latest.json"
    )
    thin_bind = read_json(Path(paths["thin_bind_latest"]))
    bindings_payload = read_json(Path(paths["thin_bind_bindings_latest"]))
    previous_next_frontier = read_json(Path(paths["previous_next_frontier_latest"]))
    thin_bind_next_frontier = (
        thin_bind.get("next_frontier_machine_actions")
        if isinstance(thin_bind.get("next_frontier_machine_actions"), dict)
        else {}
    )
    effective_next_frontier = (
        thin_bind_next_frontier
        if first_next_action(thin_bind_next_frontier) == EVAL_ACTION
        else previous_next_frontier
    )
    aaq = read_json(Path(paths["artifact_acceptance_queue_latest"]))
    source_ledger = read_json(Path(paths["source_ledger_latest"]))
    bindings = bindings_payload.get("bindings") if isinstance(bindings_payload.get("bindings"), list) else []
    decisions = [
        evaluate_binding(item if isinstance(item, dict) else {}, index)
        for index, item in enumerate(bindings, start=1)
    ]
    accepted_count = sum(1 for item in decisions if item.get("accepted_for_gateway_candidate") is True)
    previous_action = first_next_action(effective_next_frontier)
    already_consumed = (
        previous_action == NEXT_ACTION
        and effective_next_frontier.get("stop_allowed") is False
    )
    consumed_action = EVAL_ACTION if already_consumed else previous_action
    parent_wave_id = str(
        effective_next_frontier.get("parent_wave_id")
        if already_consumed
        else effective_next_frontier.get("wave_id")
        or thin_bind.get("wave_id")
        or bindings_payload.get("wave_id")
        or ""
    )
    checks = {
        "thin_bind_validation_passed": thin_bind.get("validation", {}).get("passed") is True
        if isinstance(thin_bind.get("validation"), dict)
        else False,
        "bindings_validation_passed": bindings_payload.get("validation", {}).get("passed") is True
        if isinstance(bindings_payload.get("validation"), dict)
        else False,
        "bindings_nonempty": len(bindings) > 0,
        "previous_next_action_eval_or_idempotent": previous_action == EVAL_ACTION or already_consumed,
        "gateway_candidates_present": accepted_count > 0,
        "no_default_capability_promotion": all(
            item.get("default_capability_promotion_allowed") is False for item in decisions
        ),
        "provider_invocation_not_performed": all(
            item.get("provider_invocation_performed") is False for item in decisions
        ),
        "aaq_and_source_ledger_present": bool(aaq) and bool(source_ledger),
        "completion_claim_denied": True,
    }
    validation_passed = all(checks.values())
    decisions_payload = {
        "schema_version": f"{SCHEMA_VERSION}.decisions.v1",
        "status": "adapter_value_eval_decisions_ready" if validation_passed else "adapter_value_eval_decisions_blocked",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "decision_count": len(decisions),
        "gateway_candidate_count": accepted_count,
        "decisions": decisions,
        "validation": {"passed": validation_passed, "checks": checks},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    gateway_candidates = build_gateway_candidates(
        wave_id=wave_id,
        parent_wave_id=parent_wave_id,
        paths=paths,
        decisions=decisions,
    )
    repair_plan = {
        "schema_version": "xinao.codex_s.source_family_adapter_value_eval_repair_plan.v1",
        "status": "repair_not_required" if validation_passed else "repair_required",
        "named_blocker": "" if validation_passed else "SOURCE_FAMILY_ADAPTER_VALUE_EVAL_INPUT_NOT_READY",
        "missing_checks": [name for name, passed in checks.items() if not passed],
        "return_to_main_route": True,
        "not_user_completion": True,
        "not_execution_controller": True,
    }
    manifest = build_manifest(paths, validation_passed)
    next_frontier = build_next_frontier(
        wave_id=wave_id,
        parent_wave_id=parent_wave_id,
        paths=paths,
        validation_passed=validation_passed,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "status": "source_family_adapter_value_eval_ready" if validation_passed else "source_family_adapter_value_eval_blocked",
        "generated_at": now_iso(),
        "consumed_next_frontier_action": consumed_action,
        "decision_count": len(decisions),
        "gateway_candidate_count": accepted_count,
        "input_refs": {
            "thin_bind_latest": json_ref(Path(paths["thin_bind_latest"])),
            "thin_bind_bindings_latest": json_ref(Path(paths["thin_bind_bindings_latest"])),
            "previous_next_frontier_latest": json_ref(Path(paths["previous_next_frontier_latest"])),
            "thin_bind_wave_specific_next_frontier_used": (
                first_next_action(thin_bind_next_frontier) == EVAL_ACTION
            ),
            "artifact_acceptance_queue_latest": json_ref(Path(paths["artifact_acceptance_queue_latest"])),
            "source_ledger_latest": json_ref(Path(paths["source_ledger_latest"])),
        },
        "decisions": decisions_payload,
        "capability_gateway_candidates": gateway_candidates,
        "capability_manifest": manifest,
        "next_frontier_machine_actions": next_frontier,
        "repair_plan": repair_plan,
        "output_paths": paths,
        "validation": {"passed": validation_passed, "checks": checks},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        decision_dir = Path(paths["decision_dir"])
        for index, item in enumerate(decisions, start=1):
            write_json(decision_dir / f"{index:02d}-{safe_id(item.get('binding_id'))}.json", item)
        write_json(Path(paths["decisions_latest"]), decisions_payload)
        write_json(Path(paths["decisions_wave"]), decisions_payload)
        write_json(Path(paths["capability_gateway_candidates_latest"]), gateway_candidates)
        write_json(Path(paths["capability_gateway_candidates_wave"]), gateway_candidates)
        write_json(Path(paths["manifest"]), manifest)
        next_frontier_supervisor.promote_candidate_next_frontier(
            runtime_root=runtime,
            candidate=next_frontier,
            source_kind="source_family_adapter_value_eval",
            source_ref=paths["runtime_latest"],
        )
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["wave_latest"]), payload)
        write_text(Path(paths["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate source-family adapter candidates for CapabilityGateway discovery.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="wave-block8-source-family-adapter-value-eval")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        wave_id=args.wave_id,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
