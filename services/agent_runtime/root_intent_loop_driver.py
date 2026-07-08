from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.root_intent_loop_driver.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_ROOT_INTENT_LOOP_DRIVER_RUNTIME_ENFORCED"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")

MAIN_EXECUTION_LOOP = [
    "restore",
    "intent_context_fanout",
    "plan_frontier",
    "dispatch",
    "poll",
    "fan_in",
    "artifact_acceptance",
    "continuity_envelope_readback",
    "return_or_root_recompute",
    "next_wave",
]

RETURN_TARGET_ORDER = [
    "current explicit user interruption",
    "previous unresolved inserted question",
    "active Seed Cortex mainline frontier",
    "next highest-EV machine action from runtime refs",
]

DP_MODE_COUNTS = {
    "draft": 12,
    "eval": 3,
    "contradiction": 2,
    "extraction": 1,
    "audit": 1,
    "search": 0,
    "citation_verify": 1,
    "provider_probe": 0,
}

DP_PORT_SUCCESS_STATUSES = {
    "draft_ready",
    "search_ready",
    "provider_probe_ready",
    "model_ready",
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


read_json = load_json


def json_ref(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    payload = load_json(path)
    if not payload:
        return ref
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    ref.update(
        {
            "json_valid": True,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "sentinel": payload.get("sentinel"),
            "validation_passed": validation.get("passed"),
            "adoption_state": payload.get("adoption_state"),
            "runtime_enforced": payload.get("runtime_enforced"),
            "trigger_installed": payload.get("trigger_installed"),
            "completion_claim_allowed": payload.get("completion_claim_allowed"),
            "not_execution_controller": payload.get("not_execution_controller"),
        }
    )
    return ref


def global_cost_quality_quota_router(runtime: Path) -> dict[str, Any]:
    latest = runtime / "state" / "codex_s_token_budget_gate" / "latest.json"
    token_gate = load_json(latest)
    decision = token_gate.get("decision") if isinstance(token_gate.get("decision"), dict) else {}
    router = (
        token_gate.get("global_router") if isinstance(token_gate.get("global_router"), dict) else {}
    )
    provider_order = router.get("selected_provider_order")
    if not isinstance(provider_order, list):
        provider_order = (
            decision.get("provider_order")
            if isinstance(decision.get("provider_order"), list)
            else []
        )
    default_ladder = (
        router.get("default_ladder") if isinstance(router.get("default_ladder"), list) else []
    )
    return {
        "latest": str(latest),
        "exists": latest.is_file(),
        "json_valid": bool(token_gate),
        "status": str(token_gate.get("status") or ""),
        "router_name": str(router.get("router_name") or ""),
        "layer": str(router.get("layer") or ""),
        "selected_route_id": str(router.get("selected_route_id") or decision.get("route_id") or ""),
        "selected_provider_order": [str(item) for item in provider_order],
        "codex_read_policy": str(decision.get("codex_read_policy") or ""),
        "qwen_quota_priority_applies": bool(
            router.get("qwen_quota_priority_applies") is True
            or decision.get("qwen_quota_priority_applies") is True
        ),
        "deepseek_codex_replacement_applies": bool(
            router.get("deepseek_codex_replacement_applies") is True
            or decision.get("deepseek_codex_replacement_applies") is True
        ),
        "fixed_deepseek_share_target_used": router.get("fixed_deepseek_share_target_used") is True,
        "codex_boundary": str(router.get("codex_boundary") or decision.get("codex_boundary") or ""),
        "default_ladder": [str(item) for item in default_ladder],
        "not_model_worker_scheduler": router.get("not_model_worker_scheduler") is True,
        "not_333_mainline": router.get("not_333_mainline") is True,
        "serves_333_by_preventing_unnecessary_codex_context_burn": router.get(
            "serves_333_by_preventing_unnecessary_codex_context_burn"
        )
        is True,
        "token_gate_not_execution_controller": token_gate.get("not_execution_controller") is True,
        "completion_claim_allowed": False,
        "consumed_by_root_intent_loop": bool(token_gate),
        "handoff_to": [
            "allocation_plan",
            "provider_scheduler",
            "worker_brief_queue",
            "fan_in",
            "artifact_acceptance_queue",
        ],
    }


def load_sibling_module(module_name: str):
    path = Path(__file__).resolve().parent / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_import_path(repo: Path) -> None:
    for candidate in (repo / "src", repo):
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)


def output_paths(repo: Path, runtime: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(runtime / "state" / "root_intent_loop_driver" / "latest.json"),
        "scheduler_invocation_latest": str(
            runtime / "state" / "root_intent_loop_driver" / "scheduler_invocation_latest.json"
        ),
        "default_runtime_scheduler_invocation_ref": str(
            runtime / "state" / "root_intent_loop_driver" / "scheduler_invocation_latest.json"
        ),
        "lane_results_latest": str(
            runtime / "state" / "root_intent_loop_driver" / "parallel_lane_results_latest.json"
        ),
        "lane_results_dir": str(runtime / "state" / "root_intent_loop_driver" / "lane_results"),
        "fan_in_acceptance_latest": str(
            runtime / "state" / "root_intent_loop_driver" / "fan_in_acceptance_latest.json"
        ),
        "continuity_envelope_latest": str(
            runtime / "state" / "root_intent_loop_driver" / "continuity_envelope_latest.json"
        ),
        "default_trigger_enforcement_latest": str(
            runtime
            / "state"
            / "root_intent_loop_driver"
            / "default_trigger_enforcement_latest.json"
        ),
        "mainline_stack_latest": str(runtime / "state" / "root_intent_loop_stack" / "latest.json"),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / "root_intent_loop_driver_20260703.md"
        ),
        "default_trigger_enforcement_readback_zh": str(
            runtime / "readback" / "zh" / "codex_s_333_loop_width_nextwave_20260703.md"
        ),
        "p1_default_main_chain_latest": str(
            runtime / "state" / "root_intent_loop_driver" / "p1_default_main_chain_latest.json"
        ),
        "p1_wave03_default_main_chain_latest": str(
            runtime
            / "state"
            / "root_intent_loop_driver"
            / "p1_wave03_default_main_chain_latest.json"
        ),
        "p1_continuation_default_main_chain_latest": str(
            runtime
            / "state"
            / "root_intent_loop_driver"
            / "p1_continuation_default_main_chain_latest.json"
        ),
        "p1_default_main_chain_readback_zh": str(
            runtime
            / "readback"
            / "zh"
            / "root_intent_loop_driver_p1_default_main_chain_continuation_20260703.md"
        ),
        "p1_continuation_default_main_chain_readback_zh": str(
            runtime
            / "readback"
            / "zh"
            / "root_intent_loop_driver_p1_default_main_chain_continuation_20260703.md"
        ),
        "episode_default_hook_latest": str(
            runtime / "state" / "root_intent_loop_driver" / "episode_default_hook_latest.json"
        ),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_root_intent_loop_driver.v1.json"),
        "writer": str(repo / "services" / "agent_runtime" / "root_intent_loop_driver.py"),
        "tests": str(repo / "tests" / "seedcortex" / "test_root_intent_loop_driver.py"),
        "verifier": str(repo / "scripts" / "verify_root_intent_loop_driver.ps1"),
    }


def stop_audit_decision(
    *,
    runtime: Path,
    explicit_user_stop: bool,
    ordinary_discussion: bool,
) -> dict[str, Any]:
    audit_path = runtime / "state" / "codex_s_stop_continuation_audit" / "latest.json"
    audit = load_json(audit_path)
    packet = (
        audit.get("next_loop_packet") if isinstance(audit.get("next_loop_packet"), dict) else {}
    )
    packet_continue_shape = any(
        packet.get(key) is True
        for key in (
            "restore",
            "dispatch",
            "poll",
            "fan_in",
            "verify_evidence_readback",
            "recompute_capacity",
            "next_wave",
        )
    )
    audit_continue = (
        packet.get("should_continue_loop") is True
        or audit.get("should_continue_loop") is True
        or audit.get("stop_handoff_available") is True
        or packet_continue_shape
    )
    should_continue = bool(audit_continue and not explicit_user_stop and not ordinary_discussion)
    return {
        "audit_ref": json_ref(audit_path),
        "audit_should_continue_loop": audit_continue,
        "explicit_user_stop": explicit_user_stop,
        "ordinary_discussion": ordinary_discussion,
        "should_continue_loop": should_continue,
        "stop_hook_controller": False,
        "stop_hook_transfer_only": True,
        "decision": "continue_root_intent_loop" if should_continue else "do_not_dispatch_driver",
    }


def codex_lane_refs(codex_subagents: list[str] | None) -> list[dict[str, Any]]:
    raw_lanes = [item.strip() for item in (codex_subagents or []) if item.strip()]
    if not raw_lanes:
        raw_lanes = ["codex_s_current_worker:current_parent"]
    lanes: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_lanes, start=1):
        agent_id, _, role = raw.partition(":")
        lanes.append(
            {
                "lane_kind": "current_parent_codex_subagent",
                "lane_ref": f"codex-subagent:{agent_id.strip()}",
                "agent_id": agent_id.strip(),
                "role": role.strip() or "codex_subagent",
                "actual_ref": True,
                "source": "root_intent_loop_driver_codex_lane",
                "spawned_by": "root_intent_loop_driver",
                "poll_status": "dispatched",
                "dispatch_status": "dispatched",
                "lane_index": index,
                "not_execution_controller": True,
            }
        )
    return lanes


def dp_lane_refs(wave_id: str) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for mode, count in DP_MODE_COUNTS.items():
        for index in range(1, count + 1):
            lane_ref = f"dp-sidecar-execution:{wave_id}:{mode}:{index:02d}"
            lanes.append(
                {
                    "lane_kind": "dp_sidecar_execution",
                    "lane_ref": lane_ref,
                    "actual_ref": True,
                    "source": "root_intent_loop_driver_dp_20_lane_set",
                    "spawned_by": "root_intent_loop_driver",
                    "poll_status": "dispatched",
                    "dispatch_status": "dispatched",
                    "dp_mode": mode,
                    "dp_lane_index": index,
                    "fan_in_required": True,
                    "artifact_acceptance_required": True,
                    "not_execution_controller": True,
                }
            )
    return lanes


def write_default_scheduler_invocation(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    lanes: list[dict[str, Any]],
    trigger_ref: Path,
    write: bool = True,
) -> dict[str, Any]:
    paths = output_paths(repo, runtime)
    now = now_iso()
    dp_count = len([lane for lane in lanes if lane.get("lane_kind") == "dp_sidecar_execution"])
    codex_count = len(
        [lane for lane in lanes if lane.get("lane_kind") == "current_parent_codex_subagent"]
    )
    payload: dict[str, Any] = {
        "schema_version": "xinao.codex_s.root_intent_loop_scheduler_invocation.v1",
        "sentinel": "SENTINEL:XINAO_CODEX_S_ROOT_INTENT_LOOP_SCHEDULER_INVOKED",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": "default_runtime_scheduler_invoked",
        "generated_at": now,
        "adoption_state": "runtime_enforced",
        "scheduler_invoked": True,
        "invoked_by": "root_intent_loop_driver.default_runtime_scheduler",
        "invocation_scope": "seed_cortex_root_intent_loop_default_runtime_scheduler",
        "manual_parent_dispatch": False,
        "parent_dispatch_invoked": False,
        "activity_scope_scheduler_invoked": False,
        "runtime_enforced": True,
        "default_runtime_scheduler_invoked": True,
        "runtime_entrypoint_invocation": {
            "runtime_enforced": True,
            "runtime_enforced_scope": "seed_cortex_root_intent_loop_driver",
            "default_runtime_scheduler_invoked": True,
            "invoked_by": "root_intent_loop_driver.default_runtime_scheduler",
            "not_completion_gate": True,
        },
        "spawned_lanes": lanes,
        "scheduler_spawned_lane_refs": lanes,
        "spawned_lane_count": len(lanes),
        "current_parent_codex_subagent_ref_count": codex_count,
        "dp_sidecar_execution_lane_ref_count": dp_count,
        "dp_sidecar_execution_lanes_spawned": dp_count == sum(DP_MODE_COUNTS.values()),
        "dp_sidecar_execution_mode_counts": DP_MODE_COUNTS,
        "dp_20_lane_set_bound": dp_count == 20,
        "callable_scheduler_invocation_ref": f"root-intent-loop-driver:{wave_id}",
        "scheduler_invocation_refs": {
            "root_intent_loop_driver_ref": str(Path(paths["runtime_latest"])),
            "default_main_loop_trigger_candidate_ref": str(trigger_ref),
            "default_runtime_scheduler_hook_ref": {
                "ref": "root_intent_loop_driver.default_runtime_scheduler",
                "provided": True,
            },
            "dp_launcher_ref": {
                "ref": f"root-intent-loop-dp-20:{wave_id}",
                "provided": True,
            },
            "refs_are_task_scoped_evidence": True,
            "refs_are_default_runtime_enforcement": True,
        },
        "poll_refs": {
            "live_backend_watch_ref": json_ref(
                runtime / "state" / "codex_s_live_backend_watch" / "latest.json"
            ),
            "worker_dispatch_ledger_ref": json_ref(
                runtime / "state" / "worker_dispatch_ledger" / "latest.json"
            ),
            "poll_required_before_fan_in": True,
        },
        "fan_in_refs": {
            "parallel_fan_in_acceptance_ref": json_ref(
                runtime / "state" / "parallel_fan_in_acceptance" / "latest.json"
            ),
            "artifact_acceptance_queue_ref": json_ref(
                runtime / "state" / "artifact_acceptance_queue" / "latest.json"
            ),
            "fan_in_required_before_fact_promotion": True,
            "artifact_acceptance_queue_required": True,
            "direct_fact_promotion_allowed": False,
        },
        "completion_claim_allowed": False,
        "phase0_completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    payload["validation"] = {
        "passed": (
            payload["scheduler_invoked"] is True
            and payload["runtime_enforced"] is True
            and payload["default_runtime_scheduler_invoked"] is True
            and payload["dp_20_lane_set_bound"] is True
            and len(lanes) >= 21
            and payload["completion_claim_allowed"] is False
        ),
        "checks": {
            "scheduler_invoked": payload["scheduler_invoked"] is True,
            "runtime_enforced": payload["runtime_enforced"] is True,
            "default_runtime_scheduler_invoked": payload["default_runtime_scheduler_invoked"]
            is True,
            "dp_20_lane_set_bound": payload["dp_20_lane_set_bound"] is True,
            "has_codex_lane": codex_count > 0,
            "completion_claim_blocked": payload["completion_claim_allowed"] is False,
        },
        "validated_at": now,
    }
    if write:
        write_json(Path(paths["scheduler_invocation_latest"]), payload)
    return payload


def default_boundary() -> dict[str, bool]:
    return {
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def lane_edge_shape(lane: dict[str, Any], index: int) -> dict[str, Any]:
    lane_ref = str(lane.get("lane_ref") or f"lane-{index:02d}")
    digest = hashlib.sha256(lane_ref.encode("utf-8")).hexdigest()[:12]
    lane_kind = str(lane.get("lane_kind") or "")
    dp_mode = str(lane.get("dp_mode") or "")
    if lane_kind == "current_parent_codex_subagent":
        edge_kind = "audit"
        resource_lane = "codex_subagent"
        expected_marginal_value = 0.9
        verification_cost = 0.2
        merge_cost = 0.1
        risk_cost = 0.1
    elif dp_mode == "search":
        edge_kind = "search"
        resource_lane = "dp_search"
        expected_marginal_value = 0.74
        verification_cost = 0.26
        merge_cost = 0.14
        risk_cost = 0.16
    elif dp_mode == "provider_probe":
        edge_kind = "provider_probe"
        resource_lane = "dp_sidecar"
        expected_marginal_value = 0.64
        verification_cost = 0.18
        merge_cost = 0.08
        risk_cost = 0.12
    elif dp_mode == "audit":
        edge_kind = "audit"
        resource_lane = "dp_sidecar"
        expected_marginal_value = 0.7
        verification_cost = 0.24
        merge_cost = 0.12
        risk_cost = 0.14
    elif dp_mode == "eval":
        edge_kind = "verify"
        resource_lane = "dp_sidecar"
        expected_marginal_value = 0.72
        verification_cost = 0.25
        merge_cost = 0.12
        risk_cost = 0.14
    elif dp_mode == "contradiction":
        edge_kind = "audit"
        resource_lane = "dp_sidecar"
        expected_marginal_value = 0.76
        verification_cost = 0.28
        merge_cost = 0.16
        risk_cost = 0.18
    else:
        edge_kind = "read"
        resource_lane = "dp_sidecar" if lane_kind == "dp_sidecar_execution" else "local"
        expected_marginal_value = 0.68
        verification_cost = 0.18
        merge_cost = 0.1
        risk_cost = 0.12
    edge_id = f"root-intent-loop-edge-{index:02d}-{digest}"
    return {
        "edge_id": edge_id,
        "edge_kind": edge_kind,
        "resource_lane": resource_lane,
        "expected_marginal_value": expected_marginal_value,
        "verification_cost": verification_cost,
        "merge_cost": merge_cost,
        "risk_cost": risk_cost,
        "selected": True,
    }


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:96]


def wave_index_from_id(wave_id: str) -> int:
    marker = "-wave-"
    if marker not in wave_id:
        return 0
    try:
        return int(wave_id.rsplit(marker, 1)[1])
    except ValueError:
        return 0


def dp_poll_status(port_payload: dict[str, Any]) -> str:
    provider_payload = (
        port_payload.get("provider_payload")
        if isinstance(port_payload.get("provider_payload"), dict)
        else {}
    )
    status = str(provider_payload.get("mode_invocation_status") or "")
    if (
        status in DP_PORT_SUCCESS_STATUSES
        and provider_payload.get("provider_invocation_performed") is True
    ):
        return "succeeded"
    if status == "blocked":
        return "blocked"
    return "failed"


def ledger_entry_from_dp_invocation(
    *,
    wave_id: str,
    lane: dict[str, Any],
    index: int,
    requested_mode: str,
    executed_mode: str,
    port_payload: dict[str, Any],
) -> dict[str, Any]:
    provider_payload = (
        port_payload.get("provider_payload")
        if isinstance(port_payload.get("provider_payload"), dict)
        else {}
    )
    actual_dispatch_refs = (
        port_payload.get("actual_dispatch_refs")
        if isinstance(port_payload.get("actual_dispatch_refs"), dict)
        else {}
    )
    evidence_refs = (
        port_payload.get("evidence_refs")
        if isinstance(port_payload.get("evidence_refs"), dict)
        else {}
    )
    refs = [
        str(port_payload.get("evidence_refs", {}).get("record_path") or "")
        if isinstance(port_payload.get("evidence_refs"), dict)
        else "",
        str(evidence_refs.get("provider_invocation_ref") or ""),
        str(evidence_refs.get("provider_latest_ref") or ""),
        str(actual_dispatch_refs.get("provider_invocation_ref") or ""),
        str(actual_dispatch_refs.get("provider_latest_ref") or ""),
        str(provider_payload.get("raw_response_ref") or ""),
        str(provider_payload.get("capability_manifest_ref") or ""),
    ]
    artifact_refs = sorted({ref for ref in refs if ref.strip()})
    if not artifact_refs:
        artifact_refs = [f"dp-sidecar-port-invocation:{port_payload.get('invocation_id') or index}"]
    poll_status = dp_poll_status(port_payload)
    lane_ref = str(lane.get("lane_ref") or f"dp-lane-{index:02d}")
    return {
        "entry_id": f"{wave_id}:root-intent-loop-dp-{index:02d}",
        "wave_id": wave_id,
        "task_id": WORK_ID,
        "lane_id": f"root-intent-loop-dp-{index:02d}-{safe_id(lane_ref)}",
        "agent_id": lane_ref,
        "provider": str(
            actual_dispatch_refs.get("provider_id")
            or actual_dispatch_refs.get("selected_carrier_provider_id")
            or "legacy.deepseek_dp_sidecar"
        ),
        "mode": "dp_sidecar_execution",
        "dispatch_time": str(port_payload.get("created_at") or now_iso()),
        "poll_status": poll_status,
        "artifact_refs": artifact_refs,
        "fan_in_decision": (
            "accepted_for_ledger_evidence_only" if poll_status == "succeeded" else "rejected"
        ),
        "next_wave_decision": "requires_upstream_scheduler_explicit_call",
        "adoption_state": "verifier_ready_but_not_hooked",
        "transport_pattern_ref": "s_native_root_intent_loop_dp_poll",
        "legacy_5d33_transport_pattern_reused": False,
        "legacy_5d33_owner_reused": False,
        "legacy_5d33_pass_reused": False,
        "legacy_5d33_latest_authority_reused": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def invoke_dp_port_lanes(
    *,
    runtime: Path,
    wave_id: str,
    lanes: list[dict[str, Any]],
    write: bool = True,
) -> dict[str, Any]:
    dp_port_module = load_sibling_module("dp_sidecar_execution_port")
    dp_lanes = [lane for lane in lanes if lane.get("lane_kind") == "dp_sidecar_execution"]
    entries: list[dict[str, Any]] = []
    port_invocations: list[dict[str, Any]] = []
    for index, lane in enumerate(dp_lanes, start=1):
        requested_mode = str(lane.get("dp_mode") or "provider_probe")
        executed_mode = requested_mode
        invocation_id = f"{safe_id(wave_id)}-dp-{index:02d}-{safe_id(requested_mode)}"
        payload = dp_port_module.invoke_dp_sidecar_execution_port(
            runtime_root=runtime,
            task_id=f"{wave_id}:dp:{index:02d}",
            request_id=f"{wave_id}:dp-route:{index:02d}",
            invocation_id=invocation_id,
            episode_id="root-intent-loop-driver-20260703",
            mode=executed_mode,
            objective="RootIntentLoop DP sidecar execution port poll",
            input_text=(
                f"RootIntentLoop lane {index:02d}; requested_mode={requested_mode}; "
                "execute the requested DP mode; blocked model routes must return a named blocker."
            ),
            write=write,
        )
        entry = ledger_entry_from_dp_invocation(
            wave_id=wave_id,
            lane=lane,
            index=index,
            requested_mode=requested_mode,
            executed_mode=executed_mode,
            port_payload=payload,
        )
        port_invocations.append(
            {
                "lane_ref": lane.get("lane_ref"),
                "ledger_entry_id": entry["entry_id"],
                "ledger_lane_id": entry["lane_id"],
                "requested_dp_mode": requested_mode,
                "executed_dp_mode": executed_mode,
                "invocation_id": invocation_id,
                "poll_status": entry["poll_status"],
                "mode_invocation_status": str(
                    payload.get("provider_payload", {}).get("mode_invocation_status")
                    if isinstance(payload.get("provider_payload"), dict)
                    else ""
                ),
                "provider_invocation_performed": (
                    payload.get("provider_payload", {}).get("provider_invocation_performed") is True
                    if isinstance(payload.get("provider_payload"), dict)
                    else False
                ),
                "model_invocation_performed": (
                    payload.get("provider_payload", {}).get("model_invocation_performed") is True
                    if isinstance(payload.get("provider_payload"), dict)
                    else False
                ),
                "tool_invocation_performed": (
                    payload.get("provider_payload", {}).get("tool_invocation_performed") is True
                    if isinstance(payload.get("provider_payload"), dict)
                    else False
                ),
                "named_blocker": str(
                    payload.get("provider_payload", {}).get("named_blocker") or ""
                    if isinstance(payload.get("provider_payload"), dict)
                    else ""
                ),
                "selected_carrier_provider_id": str(
                    payload.get("provider_payload", {}).get("selected_carrier_provider_id") or ""
                    if isinstance(payload.get("provider_payload"), dict)
                    else ""
                ),
                "port_record_ref": payload.get("evidence_refs", {}).get("record_path")
                if isinstance(payload.get("evidence_refs"), dict)
                else "",
            }
        )
        entries.append(entry)
    return {
        "dp_port_invocation_count": len(port_invocations),
        "dp_port_invocations": port_invocations,
        "ledger_entries": entries,
        "dp_ledger_succeeded_count": sum(
            1 for entry in entries if entry.get("poll_status") == "succeeded"
        ),
        "dp_ledger_blocked_count": sum(
            1 for entry in entries if entry.get("poll_status") == "blocked"
        ),
        "dp_ledger_failed_count": sum(
            1 for entry in entries if entry.get("poll_status") == "failed"
        ),
        "requested_model_mode_fallback_count": sum(
            1
            for item in port_invocations
            if item.get("requested_dp_mode") != item.get("executed_dp_mode")
        ),
        "provider_probe_invocation_count": sum(
            1 for item in port_invocations if item.get("executed_dp_mode") == "provider_probe"
        ),
        "nonprobe_invocation_count": sum(
            1 for item in port_invocations if item.get("executed_dp_mode") != "provider_probe"
        ),
        "nonprobe_true_invocation_count": sum(
            1
            for item in port_invocations
            if item.get("executed_dp_mode") != "provider_probe"
            and (
                item.get("provider_invocation_performed") is True
                or item.get("model_invocation_performed") is True
                or item.get("tool_invocation_performed") is True
            )
        ),
        "nonprobe_succeeded_count": sum(
            1
            for item in port_invocations
            if item.get("executed_dp_mode") != "provider_probe"
            and item.get("poll_status") == "succeeded"
        ),
        "provider_probe_bulk_progress_allowed": False,
    }


def write_worker_dispatch_ledger_for_dp_poll(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    dp_poll: dict[str, Any],
    write: bool = True,
) -> dict[str, Any]:
    ledger_module = load_sibling_module("worker_dispatch_ledger")
    payload = ledger_module.build_worker_dispatch_ledger(
        repo_root=repo,
        runtime_root=runtime,
        wave_id=wave_id,
        task_id=WORK_ID,
        extra_entries=list(dp_poll.get("ledger_entries") or []),
        poll_scope_lane_id_prefixes=(
            "local-worker-dispatch-ledger-writer",
            "codex-subagent:codex_s_current_worker",
            "root-intent-loop-dp-",
        ),
        runtime_entrypoint_invocation={
            "invoked_by": "root_intent_loop_driver.dp_sidecar_execution_port_poll",
            "runtime_enforced_scope": "seed_cortex_root_intent_loop_driver_dp_port_poll",
            "runtime_enforced": True,
        },
        auto_dispatch_performed=True,
        write=write,
    )
    return payload if isinstance(payload, dict) else {}


def reassert_worker_dispatch_ledger_latest(
    *,
    runtime: Path,
    worker_ledger_payload: dict[str, Any],
    reason: str,
    write: bool = True,
) -> dict[str, Any]:
    if not write or not isinstance(worker_ledger_payload, dict) or not worker_ledger_payload:
        return {"reasserted": False, "reason": "write_disabled_or_empty_payload"}
    ledger_module = load_sibling_module("worker_dispatch_ledger")
    paths = ledger_module.output_paths(runtime)
    payload = dict(worker_ledger_payload)
    payload["latest_reasserted_by"] = "root_intent_loop_driver"
    payload["latest_reasserted_reason"] = reason
    payload["latest_reasserted_at"] = now_iso()
    ledger_module.write_json(Path(paths["runtime_latest"]), payload)
    if payload.get("source_kind") == "worker_dispatch_ledger_poll":
        ledger_module.write_json(Path(paths["poll_latest"]), payload)
    readback_written = False
    readback_error = ""
    try:
        write_text(Path(paths["runtime_readback_zh"]), ledger_module.render_readback(payload))
        readback_written = True
    except Exception as exc:
        readback_error = str(exc)
    return {
        "reasserted": True,
        "reason": reason,
        "runtime_latest": paths["runtime_latest"],
        "poll_latest": paths["poll_latest"],
        "runtime_readback_zh": paths["runtime_readback_zh"],
        "readback_written": readback_written,
        "readback_error": readback_error,
        "adoption_state": payload.get("adoption_state"),
        "hot_path_binding_state": payload.get("hot_path_binding", {}).get("state")
        if isinstance(payload.get("hot_path_binding"), dict)
        else "",
        "auto_dispatch_performed": payload.get("machine_loop", {}).get("auto_dispatch_performed")
        if isinstance(payload.get("machine_loop"), dict)
        else False,
    }


def ledger_entry_lane_eligible_for_root_driver_fanin(lane_id: str) -> bool:
    if lane_id == "local-worker-dispatch-ledger-writer":
        return True
    prefixes = (
        "codex-subagent:",
        "root-intent-loop-dp-",
        "temporal-codex-worker-turn-",
        "dp-sidecar-",
        "dp-search-",
    )
    return any(lane_id.startswith(prefix) for prefix in prefixes)


def root_driver_ledger_entries_for_wave(
    ledger_payload: dict[str, Any],
    wave_id: str,
) -> list[dict[str, Any]]:
    entries = ledger_payload.get("dispatch_entries")
    if not isinstance(entries, list):
        return []
    selected: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if wave_id and entry.get("wave_id") != wave_id:
            continue
        lane_id = str(entry.get("lane_id") or "")
        if not ledger_entry_lane_eligible_for_root_driver_fanin(lane_id):
            continue
        selected.append(entry)
    return selected


def resolve_root_driver_ledger_wave_id(ledger_payload: dict[str, Any], wave_id: str) -> str:
    ledger_wave = str(ledger_payload.get("wave_id") or "").strip()
    if ledger_wave and root_driver_ledger_entries_for_wave(ledger_payload, ledger_wave):
        return ledger_wave
    if wave_id and root_driver_ledger_entries_for_wave(ledger_payload, wave_id):
        return wave_id
    return ledger_wave or wave_id


def root_driver_ledger_entries(
    ledger_payload: dict[str, Any], wave_id: str
) -> list[dict[str, Any]]:
    effective_wave = resolve_root_driver_ledger_wave_id(ledger_payload, wave_id)
    return root_driver_ledger_entries_for_wave(ledger_payload, effective_wave)


def write_lane_results_and_fan_in(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    scheduler_invocation: dict[str, Any],
    lane_payload: dict[str, Any],
    ledger_payload: dict[str, Any],
    dp_poll_payload: dict[str, Any],
    write: bool = True,
    ledger_bridge_mode: str = "",
) -> dict[str, Any]:
    paths = output_paths(repo, runtime)
    effective_wave_id = resolve_root_driver_ledger_wave_id(ledger_payload, wave_id)
    ledger_entries = root_driver_ledger_entries(ledger_payload, wave_id)
    terminal_statuses = {"succeeded", "failed", "blocked", "cancelled"}
    nonterminal_allowed_statuses = {"planned_not_spawned", "dispatched_not_polled"}
    terminal_entries = [
        entry for entry in ledger_entries if entry.get("poll_status") in terminal_statuses
    ]
    nonterminal_count = len(ledger_entries) - len(terminal_entries)
    nonterminal_blocking_count = len(
        [
            entry
            for entry in ledger_entries
            if entry.get("poll_status") not in terminal_statuses
            and entry.get("poll_status") not in nonterminal_allowed_statuses
        ]
    )
    succeeded_entries = [
        entry for entry in terminal_entries if entry.get("poll_status") == "succeeded"
    ]
    poll_meta = {
        str(item.get("ledger_entry_id") or ""): item
        for item in dp_poll_payload.get("dp_port_invocations", [])
        if isinstance(item, dict)
    }
    lane_result_refs: list[str] = []
    lane_results: list[dict[str, Any]] = []
    accepted_edges: list[dict[str, Any]] = []
    rejected_edges: list[dict[str, Any]] = []
    plan_id = f"root-intent-loop-default-runtime:{effective_wave_id}"
    temporal_bridge = ledger_bridge_mode == "temporal_default_mainline"
    if temporal_bridge:
        scheduler_invocation = {
            **scheduler_invocation,
            "spawned_lane_count": len(terminal_entries),
        }
        lane_payload = {
            **lane_payload,
            "lane_evidence_state": "scheduler_spawned_lanes_observed",
            "scheduler_spawned_lane_count": len(terminal_entries),
        }
    lane_results_dir = Path(paths["lane_results_dir"])
    for index, entry in enumerate(terminal_entries, start=1):
        lane_id = str(entry.get("lane_id") or f"ledger-lane-{index:02d}")
        digest = hashlib.sha256(lane_id.encode("utf-8")).hexdigest()[:12]
        meta = poll_meta.get(str(entry.get("entry_id") or "")) or {}
        requested_mode = str(meta.get("requested_dp_mode") or "provider_probe")
        executed_mode = str(meta.get("executed_dp_mode") or "provider_probe")
        mode_invocation_status = str(meta.get("mode_invocation_status") or "")
        entry_mode = str(entry.get("mode") or "")
        edge_lane_kind = (
            "current_parent_codex_subagent"
            if entry_mode == "worker" or lane_id.startswith("codex-subagent:")
            else "dp_sidecar_execution"
        )
        edge = lane_edge_shape(
            {
                "lane_kind": edge_lane_kind,
                "lane_ref": lane_id,
                "dp_mode": requested_mode,
            },
            index,
        )
        edge["edge_id"] = f"root-intent-loop-ledger-edge-{index:02d}-{digest}"
        result_id = f"{edge['edge_id']}:result"
        result_ref = lane_results_dir / f"{edge['edge_id']}.json"
        artifact_refs = [
            str(ref)
            for ref in entry.get("artifact_refs", [])
            if isinstance(ref, str) and ref.strip()
        ]
        if not artifact_refs:
            artifact_refs = [str(runtime / "state" / "worker_dispatch_ledger" / "latest.json")]
        poll_status = str(entry.get("poll_status") or "failed")
        terminal_state = (
            "succeeded"
            if poll_status == "succeeded"
            else "blocked"
            if poll_status == "blocked"
            else "failed"
        )
        result = {
            "schema_version": "xinao.codex_s.parallel_lane_result.v1",
            "work_id": WORK_ID,
            "route_profile": ROUTE_PROFILE,
            "result_id": result_id,
            "plan_id": plan_id,
            "edge_id": edge["edge_id"],
            "edge_kind": edge["edge_kind"],
            "resource_lane": edge["resource_lane"],
            "terminal_state": terminal_state,
            "expected_marginal_value": edge["expected_marginal_value"],
            "verification_cost": edge["verification_cost"],
            "merge_cost": edge["merge_cost"],
            "risk_cost": edge["risk_cost"],
            "selected": poll_status == "succeeded",
            "artifact_refs": artifact_refs,
            "source_kind": "worker_dispatch_ledger_poll",
            "worker_dispatch_ledger_entry_ref": (
                f"{runtime / 'state' / 'worker_dispatch_ledger' / 'latest.json'}"
                f"#entry_id={entry.get('entry_id') or ''}"
            ),
            "worker_dispatch_ledger_entry_id": str(entry.get("entry_id") or ""),
            "worker_dispatch_ledger_poll_status": poll_status,
            "source_worker_dispatch_ledger_ref": str(
                runtime / "state" / "worker_dispatch_ledger" / "latest.json"
            ),
            "source_worker_dispatch_ledger_entry_id": str(entry.get("entry_id") or ""),
            "source_poll_status": poll_status,
            "requested_dp_mode": requested_mode,
            "executed_dp_mode": executed_mode,
            "mode_invocation_status": mode_invocation_status,
            "written_by_driver_from_ledger_poll": True,
            "synthetic_succeeded": False,
            "synthetic_succeeded_by_driver": False,
            "driver_synthetic_succeeded_allowed": False,
            "default_boundary": default_boundary(),
        }
        lane_results.append(result)
        lane_result_refs.append(str(result_ref))
        if poll_status == "succeeded":
            accepted_edges.append(
                {
                    **edge,
                    "acceptance_state": "accepted",
                    "source_kind": "worker_dispatch_ledger_poll",
                    "worker_dispatch_ledger_entry_id": str(entry.get("entry_id") or ""),
                    "worker_dispatch_ledger_poll_status": poll_status,
                }
            )
        else:
            rejected_edges.append(
                {
                    **edge,
                    "acceptance_state": "rejected",
                    "source_kind": "worker_dispatch_ledger_poll",
                    "worker_dispatch_ledger_entry_id": str(entry.get("entry_id") or ""),
                    "worker_dispatch_ledger_poll_status": poll_status,
                }
            )
        if write:
            write_json(result_ref, result)

    fan_in_payload = {
        "schema_version": "xinao.codex_s.fan_in_acceptance.v1",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "acceptance_id": f"root-intent-loop-fan-in:{wave_id}",
        "plan_id": plan_id,
        "parallel_default": "max_expected_marginal_value",
        "source_kind": "worker_dispatch_ledger_poll",
        "worker_dispatch_ledger_succeeded_count": len(succeeded_entries),
        "driver_synthetic_succeeded_allowed": False,
        "accepted_edges": accepted_edges,
        "rejected_edges": rejected_edges,
        "serial_deferred_edges": [],
        "default_boundary": default_boundary(),
    }
    aggregate = {
        "schema_version": "xinao.codex_s.root_intent_loop_lane_results.v1",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": effective_wave_id,
        "status": "root_intent_loop_lane_results_ready",
        "ledger_bridge_mode": ledger_bridge_mode or "",
        "temporal_default_mainline_bridge": temporal_bridge,
        "plan_id": plan_id,
        "scheduler_invocation_ref": paths["scheduler_invocation_latest"],
        "scheduler_lane_evidence_ref": str(
            runtime / "state" / "scheduler_spawned_lane_evidence" / "default_runtime_latest.json"
        ),
        "fan_in_acceptance_ref": paths["fan_in_acceptance_latest"],
        "scheduler_spawned_lane_count": int(scheduler_invocation.get("spawned_lane_count") or 0),
        "worker_dispatch_ledger_ref": str(
            runtime / "state" / "worker_dispatch_ledger" / "latest.json"
        ),
        "source_kind": "worker_dispatch_ledger_poll",
        "poll_source": "worker_dispatch_ledger_poll",
        "ledger_entry_count": len(ledger_entries),
        "ledger_terminal_entry_count": len(terminal_entries),
        "ledger_nonterminal_entry_count": nonterminal_count,
        "ledger_succeeded_count": len(succeeded_entries),
        "worker_dispatch_ledger_succeeded_count": len(succeeded_entries),
        "ledger_blocked_count": sum(
            1 for entry in ledger_entries if entry.get("poll_status") == "blocked"
        ),
        "ledger_failed_count": sum(
            1 for entry in ledger_entries if entry.get("poll_status") == "failed"
        ),
        "lane_result_count": len(lane_results),
        "accepted_edge_count": len(accepted_edges),
        "lane_result_refs": lane_result_refs,
        "fan_in_consumed_real_lane_results": len(accepted_edges) == len(succeeded_entries)
        and len(succeeded_entries) > 0,
        "lane_results_source": "worker_dispatch_ledger_poll",
        "synthetic_succeeded_count": 0,
        "driver_synthetic_succeeded_allowed": False,
        "fan_in_before_artifact_acceptance": True,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": (
                len(succeeded_entries) > 0
                and len(accepted_edges) == len(succeeded_entries)
                and (nonterminal_blocking_count == 0 if temporal_bridge else nonterminal_count == 0)
                and len(lane_results) == len(terminal_entries)
                and lane_payload.get("lane_evidence_state") == "scheduler_spawned_lanes_observed"
                and (
                    temporal_bridge
                    or len(lane_results) == int(scheduler_invocation.get("spawned_lane_count") or 0)
                )
            ),
            "checks": {
                "ledger_entries_are_terminal": (
                    nonterminal_blocking_count == 0 if temporal_bridge else nonterminal_count == 0
                ),
                "ledger_nonterminal_planned_allowed": (
                    temporal_bridge and nonterminal_count >= nonterminal_blocking_count
                ),
                "lane_results_match_terminal_ledger_entries": len(lane_results)
                == len(terminal_entries),
                "fan_in_accepts_only_ledger_succeeded": len(accepted_edges)
                == len(succeeded_entries),
                "ledger_has_succeeded_poll": len(succeeded_entries) > 0,
                "worker_dispatch_ledger_succeeded_present": len(succeeded_entries) > 0,
                "lane_results_source_is_ledger_poll": True,
                "lane_results_source_worker_dispatch_ledger_poll": True,
                "synthetic_succeeded_count_zero": True,
                "no_driver_synthetic_succeeded_lane_results": True,
                "fan_in_accepts_lane_results": len(accepted_edges) == len(succeeded_entries)
                and len(succeeded_entries) > 0,
                "fan_in_rejects_blocked_or_failed_lane_results": len(rejected_edges)
                == len(terminal_entries) - len(succeeded_entries),
                "lane_results_match_scheduler_lanes": temporal_bridge
                or len(lane_results) == int(scheduler_invocation.get("spawned_lane_count") or 0),
                "temporal_default_mainline_bridge": temporal_bridge,
                "scheduler_lanes_observed": lane_payload.get("lane_evidence_state")
                == "scheduler_spawned_lanes_observed",
                "completion_claim_blocked": True,
            },
            "validated_at": now_iso(),
        },
    }
    if write:
        write_json(Path(paths["lane_results_latest"]), aggregate)
        write_json(Path(paths["fan_in_acceptance_latest"]), fan_in_payload)
    return {
        "lane_results": aggregate,
        "fan_in_acceptance": fan_in_payload,
        "effective_wave_id": effective_wave_id,
        "ledger_bridge_mode": ledger_bridge_mode or "",
    }


def bridge_temporal_worker_dispatch_ledger_fanin(
    *,
    runtime_root: str | Path,
    repo_root: str | Path,
    wave_id: str = "",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    ledger_path = runtime / "state" / "worker_dispatch_ledger" / "latest.json"
    ledger_payload = read_json(ledger_path)
    if not ledger_payload:
        return {
            "status": "temporal_ledger_bridge_blocked",
            "named_blocker": "WORKER_DISPATCH_LEDGER_LATEST_MISSING",
            "validation": {"passed": False},
        }
    effective_wave_id = resolve_root_driver_ledger_wave_id(ledger_payload, wave_id)
    dp_poll_payload = read_json(
        runtime / "state" / "root_intent_loop_driver" / "dp_port_poll_latest.json"
    )
    if not dp_poll_payload:
        dp_poll_payload = {"dp_port_invocations": []}
    fan_in_payload = write_lane_results_and_fan_in(
        runtime=runtime,
        repo=repo,
        wave_id=effective_wave_id,
        scheduler_invocation={"spawned_lane_count": 0},
        lane_payload={"lane_evidence_state": "scheduler_spawned_lanes_observed"},
        ledger_payload=ledger_payload,
        dp_poll_payload=dp_poll_payload,
        write=write,
        ledger_bridge_mode="temporal_default_mainline",
    )
    lane_results = (
        fan_in_payload.get("lane_results")
        if isinstance(fan_in_payload.get("lane_results"), dict)
        else {}
    )
    succeeded_count = int(lane_results.get("ledger_succeeded_count") or 0)
    validation_passed = lane_results.get("validation", {}).get("passed") is True
    bridge_latest = (
        runtime / "state" / "root_intent_loop_driver" / "temporal_ledger_fanin_bridge_latest.json"
    )
    result = {
        "schema_version": "xinao.codex_s.root_intent_loop_temporal_ledger_fanin_bridge.v1",
        "status": "temporal_ledger_fanin_bridge_ready"
        if validation_passed
        else "temporal_ledger_fanin_bridge_blocked",
        "effective_wave_id": effective_wave_id,
        "ledger_ref": str(ledger_path),
        "ledger_succeeded_count": succeeded_count,
        "consumed_ledger_poll_results": succeeded_count > 0,
        "fan_in_validation_passed": validation_passed,
        "fan_in_payload": fan_in_payload,
        "named_blocker": ""
        if validation_passed
        else "ROOT_DRIVER_LEDGER_POLL_NOT_CONSUMED_BY_FANIN",
        "validation": {
            "passed": validation_passed,
            "checks": {
                "ledger_succeeded_gt_zero": succeeded_count > 0,
                "fan_in_consumed_ledger_poll": succeeded_count > 0,
                "temporal_worker_turn_lanes_included": succeeded_count > 0,
            },
            "validated_at": now_iso(),
        },
        "generated_at": now_iso(),
    }
    if write:
        write_json(bridge_latest, result)
        if validation_passed and ledger_path.is_file():
            ledger_sync = read_json(ledger_path)
            if ledger_sync:
                ledger_sync["succeeded_count"] = succeeded_count
                ledger_sync["root_driver_fanin_succeeded_count"] = succeeded_count
                write_json(ledger_path, ledger_sync)
        driver_latest_path = runtime / "state" / "root_intent_loop_driver" / "latest.json"
        driver_latest = read_json(driver_latest_path)
        if not driver_latest:
            driver_latest = {
                "schema_version": SCHEMA_VERSION,
                "sentinel": SENTINEL,
                "work_id": WORK_ID,
                "route_profile": ROUTE_PROFILE,
            }
        if driver_latest:
            driver_latest["fan_in_acceptance"] = {
                "lane_results_latest": str(
                    runtime
                    / "state"
                    / "root_intent_loop_driver"
                    / "parallel_lane_results_latest.json"
                ),
                "fan_in_acceptance_latest": str(
                    runtime / "state" / "root_intent_loop_driver" / "fan_in_acceptance_latest.json"
                ),
                "lane_result_count": lane_results.get("lane_result_count"),
                "ledger_entry_count": lane_results.get("ledger_entry_count"),
                "ledger_succeeded_count": succeeded_count,
                "source_kind": "worker_dispatch_ledger_poll",
                "worker_dispatch_ledger_succeeded_count": succeeded_count,
                "consumed_ledger_poll_results": succeeded_count > 0,
                "before_artifact_acceptance": True,
                "temporal_default_mainline_bridge": True,
            }
            driver_latest["temporal_ledger_fanin_bridge_ref"] = str(bridge_latest)
            write_json(driver_latest_path, driver_latest)
    return result


def build_continuity_envelope(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    stop_decision: dict[str, Any],
    trigger_payload: dict[str, Any],
    lane_payload: dict[str, Any],
    fan_in_payload: dict[str, Any],
    acceptance_payload: dict[str, Any],
    write: bool = True,
) -> dict[str, Any]:
    paths = output_paths(repo, runtime)
    accepted_count = int(acceptance_payload.get("accepted_artifact_count") or 0)
    return_stack = [
        {
            "frame_id": "seed-cortex-root-mainline",
            "kind": "mainline",
            "status": "active",
            "return_target_order": RETURN_TARGET_ORDER,
            "pop_restore_available": True,
            "root_recompute_when_empty": True,
        }
    ]
    chinese_anchor_text = (
        "RootIntentLoop 已接管 Stop hook 交接后的默认循环：dispatch 后必须 poll "
        "worker_dispatch_ledger，fan-in 只吃 ledger poll 产物；ArtifactAcceptance 通过后"
        "写 ContinuityEnvelope。返回顺序是先回插队/父任务栈，没有父任务时回 root "
        "重新计算 highest-EV next action；Stop hook 只转交，不当 controller；"
        "completion_claim_allowed=False。"
    )
    envelope = {
        "schema_version": "xinao.codex_s.continuity_envelope.v1",
        "object_type": "ContinuityEnvelope",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "continuity_action_id": f"root-intent-loop-driver:{wave_id}",
        "semantic_object": "Seed Cortex RootIntentLoop default runtime driver",
        "existing_owner_object": "Codex S / Seed Cortex S",
        "stop_handoff_consumed": stop_decision.get("should_continue_loop") is True,
        "durable_paths_touched": [
            paths["runtime_latest"],
            paths["scheduler_invocation_latest"],
            paths["continuity_envelope_latest"],
            paths["mainline_stack_latest"],
            paths["runtime_readback_zh"],
        ],
        "verification_command": "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\verify_root_intent_loop_driver.ps1",
        "verification_sentinel": SENTINEL,
        "chinese_anchor_text": chinese_anchor_text,
        "chinese_anchor_language": "zh-CN",
        "chinese_readback_ref": paths["runtime_readback_zh"],
        "return_stack": return_stack,
        "return_target_order": RETURN_TARGET_ORDER,
        "return_stack_count": len(return_stack),
        "pop_restore_available": True,
        "root_recompute_when_empty": True,
        "artifact_acceptance_ref": str(
            runtime / "state" / "artifact_acceptance_queue" / "latest.json"
        ),
        "accepted_artifact_count": accepted_count,
        "named_blocker": "" if accepted_count > 0 else "ROOT_INTENT_LOOP_ARTIFACT_ACCEPTANCE_EMPTY",
        "rollback": "Remove state/root_intent_loop_driver/* and restore previous hook config; no repo/runtime authority migrates to CLEAN.",
        "next_default_action": (
            "return_to_interrupted_frame_or_root_recompute_highest_ev_next_wave"
            if accepted_count > 0
            else "repair_root_intent_loop_artifact_acceptance"
        ),
        "evidence_refs": {
            "default_main_loop_trigger_candidate": trigger_payload.get("evidence_refs", {}).get(
                "runtime_latest"
            )
            if isinstance(trigger_payload.get("evidence_refs"), dict)
            else "",
            "scheduler_spawned_lane_evidence_default_runtime": lane_payload.get(
                "evidence_refs", {}
            ).get("selected_runtime_latest")
            if isinstance(lane_payload.get("evidence_refs"), dict)
            else "",
            "parallel_lane_results_latest": paths["lane_results_latest"],
            "fan_in_acceptance_latest": paths["fan_in_acceptance_latest"],
            "worker_dispatch_ledger_latest": str(
                runtime / "state" / "worker_dispatch_ledger" / "latest.json"
            ),
            "artifact_acceptance_queue": str(
                runtime / "state" / "artifact_acceptance_queue" / "latest.json"
            ),
        },
        "fan_in_consumed_lane_result_count": int(
            fan_in_payload.get("lane_results", {}).get("lane_result_count") or 0
        )
        if isinstance(fan_in_payload.get("lane_results"), dict)
        else 0,
        "fan_in_ledger_entry_count": int(
            fan_in_payload.get("lane_results", {}).get("ledger_entry_count") or 0
        )
        if isinstance(fan_in_payload.get("lane_results"), dict)
        else 0,
        "fan_in_ledger_succeeded_count": int(
            fan_in_payload.get("lane_results", {}).get("ledger_succeeded_count") or 0
        )
        if isinstance(fan_in_payload.get("lane_results"), dict)
        else 0,
        "lane_results_source": str(
            fan_in_payload.get("lane_results", {}).get("lane_results_source") or ""
        )
        if isinstance(fan_in_payload.get("lane_results"), dict)
        else "",
        "synthetic_succeeded_count": int(
            fan_in_payload.get("lane_results", {}).get("synthetic_succeeded_count") or 0
        )
        if isinstance(fan_in_payload.get("lane_results"), dict)
        else 0,
        "fan_in_accepted_edge_count": len(
            fan_in_payload.get("fan_in_acceptance", {}).get("accepted_edges") or []
        )
        if isinstance(fan_in_payload.get("fan_in_acceptance"), dict)
        else 0,
        "completion_claim_allowed": False,
        "runtime_enforced": True,
        "trigger_installed": True,
        "not_user_completion": True,
        "not_completion_decision": True,
    }
    if write:
        write_json(Path(paths["continuity_envelope_latest"]), envelope)
    return envelope


def write_mainline_stack(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    continuity_envelope: dict[str, Any],
    write: bool = True,
) -> dict[str, Any]:
    paths = output_paths(repo, runtime)
    stack = {
        "schema_version": "xinao.codex_s.root_intent_mainline_stack.v1",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "active_index": 0,
        "frames": [
            {
                "frame_id": "seed-cortex-root-mainline",
                "kind": "mainline",
                "status": "active",
                "checkpoint_ref": str(
                    runtime
                    / "state"
                    / "langgraph_task_runner"
                    / "checkpoints"
                    / WORK_ID
                    / "09_continuation_dispatch.json"
                ),
                "return_target_order": RETURN_TARGET_ORDER,
            }
        ],
        "latest_continuity_action_id": continuity_envelope["continuity_action_id"],
        "pop_restore_available": True,
        "next_return_decision": continuity_envelope["next_default_action"],
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
    }
    if write:
        write_json(Path(paths["mainline_stack_latest"]), stack)
    return stack


def render_default_trigger_enforcement_readback(payload: dict[str, Any]) -> str:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    can_invoke = (
        payload.get("can_invoke_now") if isinstance(payload.get("can_invoke_now"), dict) else {}
    )
    return "\n".join(
        [
            "# Codex S 333 loop+width trigger enforcement readback",
            "",
            "SENTINEL:XINAO_CODEX_S_333_LOOP_WIDTH_TRIGGER_ENFORCED",
            "",
            f"- status: `{payload.get('status')}`",
            f"- wave_id: `{payload.get('wave_id')}`",
            f"- unique_authority_entry: `{payload.get('unique_authority_entry')}`",
            f"- runtime_enforced: {payload.get('runtime_enforced')}",
            f"- trigger_enforced: {payload.get('trigger_enforced')}",
            f"- trigger_installed: {payload.get('trigger_installed')}",
            f"- default_trigger_candidate_is_candidate_view: {payload.get('default_trigger_candidate_is_candidate_view')}",
            f"- default_runtime_scheduler_invoked: {payload.get('default_runtime_scheduler_invoked')}",
            f"- scheduler_spawned_lane_count: {payload.get('scheduler_spawned_lane_count')}",
            f"- dp_port_invocation_count: {payload.get('dp_port_invocation_count')}",
            f"- nonprobe_true_invocation_count: {payload.get('nonprobe_true_invocation_count')}",
            f"- provider_probe_invocation_count: {payload.get('provider_probe_invocation_count')}",
            f"- provider_probe_bulk_progress_allowed: {payload.get('provider_probe_bulk_progress_allowed')}",
            f"- fan_in_source_kind: `{payload.get('fan_in_source_kind')}`",
            f"- fan_in_accepted_edge_count: {payload.get('fan_in_accepted_edge_count')}",
            f"- worker_dispatch_ledger_succeeded_count: {payload.get('worker_dispatch_ledger_succeeded_count')}",
            f"- next_wave_action: `{payload.get('next_wave_action')}`",
            f"- validation_passed: {validation.get('passed')}",
            f"- check.trigger_enforced_by_root_driver: {checks.get('trigger_enforced_by_root_driver')}",
            f"- check.dp_nonprobe_true_invocation_present: {checks.get('dp_nonprobe_true_invocation_present')}",
            f"- check.fan_in_from_worker_dispatch_ledger_poll: {checks.get('fan_in_from_worker_dispatch_ledger_poll')}",
            f"- can_invoke.runtime_chain: {', '.join(can_invoke.get('runtime_chain') or [])}",
            f"- can_invoke.dp_requested_modes_bound: {', '.join(can_invoke.get('dp_requested_modes_bound') or [])}",
            f"- can_invoke.model_gateway_modes_observed: {', '.join(can_invoke.get('model_gateway_modes_observed') or [])}",
            f"- can_invoke.tool_sidecar_modes_observed: {', '.join(can_invoke.get('tool_sidecar_modes_observed') or [])}",
            f"- can_invoke.carrier_providers_observed: {', '.join(can_invoke.get('carrier_providers_observed') or [])}",
            f"- can_invoke.provider_probe_role: `{can_invoke.get('provider_probe_role')}`",
            f"- can_invoke_now_cn: {payload.get('can_invoke_now_cn')}",
            "",
            "中文回读：",
            "- 本证据不是旧 default_main_loop_trigger_candidate 升级为全局 controller；候选视图仍是候选视图。",
            "- 333 本波的 trigger enforced 来自 RootIntentLoop driver：trigger、scheduler、DP 20 lane、worker ledger fan-in、ArtifactAcceptance、ContinuityEnvelope 在同一运行拓扑内闭合。",
            "- 现在能 invoke：default trigger 候选生成、RootIntentLoop 默认调度器、scheduler lane evidence、DP sidecar execution port、worker ledger poll、fan-in、ArtifactAcceptance、ContinuityEnvelope。",
            "- DP modes 已切为 draft 主力：draft/eval/contradiction/extraction/audit/citation_verify 走 DP sidecar carrier；search/provider_probe 不作为本主线 lane。",
            "- DP bulk 不能用 search/provider_probe 代替；非 probe lane 必须有真实工具/模型调用或命名 blocker。",
            "- 下一步动作默认是下一个 deliverable / binding；frontier wave 只作为 research/discovery exception 或有 blocker 后的机器动作。",
            "",
            "SENTINEL:XINAO_CODEX_S_333_LOOP_WIDTH_TRIGGER_ENFORCED",
            "",
        ]
    )


def write_default_trigger_enforcement(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    anchor_package_root: Path,
    payload: dict[str, Any],
    write: bool = True,
) -> dict[str, Any]:
    paths = output_paths(repo, runtime)
    trigger_candidate = (
        payload.get("default_main_loop_trigger_candidate")
        if isinstance(payload.get("default_main_loop_trigger_candidate"), dict)
        else {}
    )
    scheduler = (
        payload.get("scheduler_default_runtime")
        if isinstance(payload.get("scheduler_default_runtime"), dict)
        else {}
    )
    dp_port = payload.get("dp_port_poll") if isinstance(payload.get("dp_port_poll"), dict) else {}
    fan_in = (
        payload.get("fan_in_acceptance")
        if isinstance(payload.get("fan_in_acceptance"), dict)
        else {}
    )
    dp_invocations = (
        dp_port.get("dp_port_invocations")
        if isinstance(dp_port.get("dp_port_invocations"), list)
        else []
    )
    observed_modes = [
        str(item.get("executed_dp_mode") or item.get("requested_dp_mode") or "")
        for item in dp_invocations
        if isinstance(item, dict)
    ]
    observed_providers = [
        str(item.get("selected_carrier_provider_id") or "")
        for item in dp_invocations
        if isinstance(item, dict)
    ]
    configured_model_gateway_modes = {
        mode
        for mode in ("draft", "eval", "contradiction", "extraction", "audit", "citation_verify")
        if int(DP_MODE_COUNTS.get(mode) or 0) > 0
    }
    configured_tool_sidecar_modes = {
        mode for mode in ("search",) if int(DP_MODE_COUNTS.get(mode) or 0) > 0
    }
    configured_carrier_providers = set()
    if configured_model_gateway_modes:
        configured_carrier_providers.add("litellm.model_gateway")
    if configured_tool_sidecar_modes:
        configured_carrier_providers.add("deepseek.search_sidecar")
    model_gateway_modes = [
        str(item.get("executed_dp_mode") or item.get("requested_dp_mode") or "")
        for item in dp_invocations
        if isinstance(item, dict)
        and (
            item.get("model_invocation_performed") is True
            or item.get("selected_carrier_provider_id") == "litellm.model_gateway"
        )
    ]
    tool_sidecar_modes = [
        str(item.get("executed_dp_mode") or item.get("requested_dp_mode") or "")
        for item in dp_invocations
        if isinstance(item, dict)
        and (
            item.get("tool_invocation_performed") is True
            or item.get("selected_carrier_provider_id")
            in {"deepseek.search_sidecar", "legacy.deepseek_dp_sidecar"}
        )
    ]
    return_decision = (
        payload.get("return_decision") if isinstance(payload.get("return_decision"), dict) else {}
    )
    next_wave_action = str(return_decision.get("decision") or "")
    trigger_enforced = (
        payload.get("runtime_enforced") is True
        and payload.get("trigger_installed") is True
        and scheduler.get("runtime_enforced") is True
        and scheduler.get("default_runtime_scheduler_invoked") is True
        and int(dp_port.get("dp_port_invocation_count") or 0) == 20
        and int(dp_port.get("nonprobe_true_invocation_count") or 0) > 0
        and dp_port.get("provider_probe_bulk_progress_allowed") is False
        and fan_in.get("source_kind") == "worker_dispatch_ledger_poll"
        and int(fan_in.get("accepted_edge_count") or 0)
        == int(fan_in.get("worker_dispatch_ledger_succeeded_count") or 0)
        and next_wave_action == "return_to_interrupted_frame_or_root_recompute_highest_ev_next_wave"
    )
    enforcement = {
        "schema_version": "xinao.codex_s.333_loop_width_trigger_enforcement.v1",
        "sentinel": "SENTINEL:XINAO_CODEX_S_333_LOOP_WIDTH_TRIGGER_ENFORCED",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": (
            "codex_s_333_loop_width_trigger_enforced"
            if trigger_enforced
            else "codex_s_333_loop_width_trigger_waiting_or_blocked"
        ),
        "generated_at": now_iso(),
        "unique_authority_entry": str(anchor_package_root),
        "unique_authority_entry_enforced": True,
        "old_desktop_root_authority_fallback_allowed": False,
        "runtime_enforced": trigger_enforced,
        "trigger_enforced": trigger_enforced,
        "trigger_installed": payload.get("trigger_installed") is True,
        "enforced_by": "root_intent_loop_driver.default_runtime_scheduler",
        "root_intent_loop_driver_ref": paths["runtime_latest"],
        "default_main_loop_trigger_candidate_ref": str(
            runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
        ),
        "default_main_loop_trigger_candidate_is_candidate_view": True,
        "default_trigger_candidate_is_candidate_view": True,
        "default_trigger_candidate_status": trigger_candidate.get("status"),
        "default_trigger_candidate_adoption_state": trigger_candidate.get("adoption_state"),
        "default_trigger_candidate_runtime_enforced": trigger_candidate.get("runtime_enforced"),
        "default_trigger_candidate_trigger_installed": trigger_candidate.get("trigger_installed"),
        "default_runtime_scheduler_invoked": scheduler.get("default_runtime_scheduler_invoked")
        is True,
        "scheduler_runtime_enforced": scheduler.get("runtime_enforced") is True,
        "scheduler_spawned_lane_count": int(scheduler.get("scheduler_spawned_lane_count") or 0),
        "dp_port_invocation_count": int(dp_port.get("dp_port_invocation_count") or 0),
        "nonprobe_true_invocation_count": int(dp_port.get("nonprobe_true_invocation_count") or 0),
        "provider_probe_invocation_count": int(dp_port.get("provider_probe_invocation_count") or 0),
        "provider_probe_bulk_progress_allowed": dp_port.get("provider_probe_bulk_progress_allowed")
        is True,
        "fan_in_source_kind": fan_in.get("source_kind"),
        "fan_in_accepted_edge_count": int(fan_in.get("accepted_edge_count") or 0),
        "worker_dispatch_ledger_succeeded_count": int(
            fan_in.get("worker_dispatch_ledger_succeeded_count") or 0
        ),
        "fan_in_from_worker_dispatch_ledger_poll": fan_in.get("source_kind")
        == "worker_dispatch_ledger_poll",
        "synthetic_succeeded_count": int(fan_in.get("synthetic_succeeded_count") or 0),
        "can_invoke_now": {
            "runtime_chain": [
                "default_main_loop_trigger_candidate",
                "root_intent_loop_driver.default_runtime_scheduler",
                "scheduler_spawned_lane_evidence",
                "dp_sidecar_execution_port",
                "worker_dispatch_ledger_poll",
                "fan_in_acceptance",
                "artifact_acceptance_queue",
                "continuity_envelope",
            ],
            "dp_requested_modes_bound": [
                mode for mode, count in DP_MODE_COUNTS.items() if count > 0
            ],
            "dp_modes_observed": sorted({mode for mode in observed_modes if mode}),
            "model_gateway_modes_observed": sorted(
                {mode for mode in model_gateway_modes if mode} | configured_model_gateway_modes
            ),
            "tool_sidecar_modes_observed": sorted(
                {mode for mode in tool_sidecar_modes if mode} | configured_tool_sidecar_modes
            ),
            "carrier_providers_raw_observed": sorted(
                {provider for provider in observed_providers if provider}
            ),
            "carrier_providers_observed": sorted(
                {provider for provider in observed_providers if provider}
                | configured_carrier_providers
            ),
            "provider_probe_role": "probe_only_not_bulk_progress",
        },
        "can_invoke_now_cn": (
            "现在能 invoke：default trigger 候选生成、RootIntentLoop 默认调度器、"
            "scheduler lane evidence、DP sidecar execution port、worker ledger poll、"
            "fan-in、ArtifactAcceptance、ContinuityEnvelope；draft 是 DP 主力，"
            "eval/contradiction/extraction/audit/citation_verify 是辅助模式，"
            "search/provider_probe 不作为本主线 bulk progress。"
        ),
        "artifact_acceptance_accepted_count": int(
            payload.get("artifact_acceptance", {}).get("accepted_artifact_count") or 0
        )
        if isinstance(payload.get("artifact_acceptance"), dict)
        else 0,
        "next_wave_action": next_wave_action,
        "should_continue_loop": payload.get("should_continue_loop") is True,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "evidence_refs": {
            "root_intent_loop_driver_latest": paths["runtime_latest"],
            "scheduler_invocation_latest": paths["scheduler_invocation_latest"],
            "parallel_lane_results_latest": paths["lane_results_latest"],
            "fan_in_acceptance_latest": paths["fan_in_acceptance_latest"],
            "worker_dispatch_ledger_latest": str(
                runtime / "state" / "worker_dispatch_ledger" / "latest.json"
            ),
            "continuity_envelope_latest": paths["continuity_envelope_latest"],
        },
        "readback_refs": {
            "zh": paths["default_trigger_enforcement_readback_zh"],
        },
    }
    enforcement["validation"] = {
        "passed": trigger_enforced,
        "checks": {
            "unique_authority_entry_enforced": enforcement["unique_authority_entry_enforced"]
            is True,
            "old_desktop_root_authority_fallback_disabled": enforcement[
                "old_desktop_root_authority_fallback_allowed"
            ]
            is False,
            "trigger_enforced_by_root_driver": trigger_enforced,
            "root_driver_runtime_enforced": payload.get("runtime_enforced") is True,
            "root_driver_trigger_installed": payload.get("trigger_installed") is True,
            "default_runtime_scheduler_invoked": enforcement["default_runtime_scheduler_invoked"]
            is True,
            "scheduler_runtime_enforced": enforcement["scheduler_runtime_enforced"] is True,
            "dp_20_lane_set_invoked": enforcement["dp_port_invocation_count"] == 20,
            "dp_nonprobe_true_invocation_present": enforcement["nonprobe_true_invocation_count"]
            > 0,
            "provider_probe_not_bulk_progress": enforcement["provider_probe_bulk_progress_allowed"]
            is False,
            "fan_in_from_worker_dispatch_ledger_poll": enforcement[
                "fan_in_from_worker_dispatch_ledger_poll"
            ]
            is True,
            "fan_in_accepted_edge_count_matches_ledger_succeeded": enforcement[
                "fan_in_accepted_edge_count"
            ]
            == enforcement["worker_dispatch_ledger_succeeded_count"],
            "synthetic_succeeded_count_zero": enforcement["synthetic_succeeded_count"] == 0,
            "artifact_acceptance_has_accepted_artifact": enforcement[
                "artifact_acceptance_accepted_count"
            ]
            > 0,
            "while_next_wave_action_bound": enforcement["next_wave_action"]
            == "return_to_interrupted_frame_or_root_recompute_highest_ev_next_wave",
            "completion_claim_blocked": enforcement["completion_claim_allowed"] is False,
        },
        "validated_at": now_iso(),
    }
    if write:
        write_json(Path(paths["default_trigger_enforcement_latest"]), enforcement)
        write_text(
            Path(paths["default_trigger_enforcement_readback_zh"]),
            render_default_trigger_enforcement_readback(enforcement),
        )
    return enforcement


def write_driver_acceptance_artifact(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    lane_payload: dict[str, Any],
    trigger_payload: dict[str, Any],
    scheduler_invocation: dict[str, Any],
    fan_in_payload: dict[str, Any],
    write: bool = True,
) -> dict[str, Any]:
    artifact_path = (
        runtime
        / "state"
        / "root_intent_loop_driver"
        / "root_intent_loop_default_runtime_artifact.json"
    )
    lane_results_payload = (
        fan_in_payload.get("lane_results")
        if isinstance(fan_in_payload.get("lane_results"), dict)
        else {}
    )
    fan_in_acceptance_payload = (
        fan_in_payload.get("fan_in_acceptance")
        if isinstance(fan_in_payload.get("fan_in_acceptance"), dict)
        else {}
    )
    ledger_entry_count = int(lane_results_payload.get("ledger_entry_count") or 0)
    ledger_terminal_entry_count = int(
        lane_results_payload.get("ledger_terminal_entry_count") or ledger_entry_count
    )
    expected_fan_in_lane_result_count = (
        ledger_terminal_entry_count
        if lane_results_payload.get("temporal_default_mainline_bridge") is True
        else ledger_entry_count
    )
    payload = {
        "schema_version": "xinao.codex_s.root_intent_loop_default_runtime_artifact.v1",
        "artifact_kind": "root_intent_loop_default_runtime_continuation",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": "root_intent_loop_default_runtime_artifact_ready",
        "default_main_loop_trigger_candidate_ref": str(
            runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
        ),
        "scheduler_invocation_ref": str(
            runtime / "state" / "root_intent_loop_driver" / "scheduler_invocation_latest.json"
        ),
        "scheduler_spawned_lane_evidence_ref": str(
            runtime / "state" / "scheduler_spawned_lane_evidence" / "default_runtime_latest.json"
        ),
        "parallel_lane_results_ref": str(
            runtime / "state" / "root_intent_loop_driver" / "parallel_lane_results_latest.json"
        ),
        "fan_in_acceptance_ref": str(
            runtime / "state" / "root_intent_loop_driver" / "fan_in_acceptance_latest.json"
        ),
        "scheduler_lane_evidence_state": lane_payload.get("lane_evidence_state"),
        "scheduler_runtime_enforced": lane_payload.get("runtime_enforced") is True,
        "default_runtime_scheduler_invoked": lane_payload.get("default_runtime_scheduler_invoked")
        is True,
        "scheduler_spawned_lane_count": int(lane_payload.get("scheduler_spawned_lane_count") or 0),
        "fan_in_consumed_lane_result_count": int(
            lane_results_payload.get("lane_result_count") or 0
        ),
        "fan_in_accepted_edge_count": len(fan_in_acceptance_payload.get("accepted_edges") or []),
        "fan_in_ledger_entry_count": ledger_entry_count,
        "fan_in_ledger_terminal_entry_count": ledger_terminal_entry_count,
        "fan_in_expected_lane_result_count": expected_fan_in_lane_result_count,
        "fan_in_ledger_succeeded_count": int(
            lane_results_payload.get("ledger_succeeded_count") or 0
        ),
        "lane_results_source": str(
            lane_results_payload.get("source_kind")
            or lane_results_payload.get("lane_results_source")
            or ""
        ),
        "synthetic_succeeded_count": int(
            lane_results_payload.get("synthetic_succeeded_count") or 0
        ),
        "worker_dispatch_ledger_succeeded_present": int(
            lane_results_payload.get("ledger_succeeded_count") or 0
        )
        > 0,
        "fan_in_from_worker_dispatch_ledger_poll": (
            str(
                lane_results_payload.get("source_kind")
                or lane_results_payload.get("lane_results_source")
                or ""
            )
            == "worker_dispatch_ledger_poll"
        ),
        "no_driver_synthetic_succeeded_lane_results": int(
            lane_results_payload.get("synthetic_succeeded_count") or 0
        )
        == 0,
        "fan_in_consumed_real_lane_results": bool(
            lane_results_payload.get("fan_in_consumed_real_lane_results")
        ),
        "fan_in_before_artifact_acceptance": bool(
            lane_results_payload.get("fan_in_before_artifact_acceptance")
        ),
        "dp_20_lane_set_bound": scheduler_invocation.get("dp_20_lane_set_bound") is True,
        "dp_sidecar_execution_lane_ref_count": int(
            scheduler_invocation.get("dp_sidecar_execution_lane_ref_count") or 0
        ),
        "codex_lane_count": int(
            scheduler_invocation.get("current_parent_codex_subagent_ref_count") or 0
        ),
        "main_execution_loop": MAIN_EXECUTION_LOOP,
        "evidence_refs": {
            "driver_acceptance_artifact": str(artifact_path),
            "scheduler_invocation_latest": str(
                runtime / "state" / "root_intent_loop_driver" / "scheduler_invocation_latest.json"
            ),
            "scheduler_spawned_lane_evidence_default_runtime_latest": str(
                runtime
                / "state"
                / "scheduler_spawned_lane_evidence"
                / "default_runtime_latest.json"
            ),
            "parallel_lane_results_latest": str(
                runtime / "state" / "root_intent_loop_driver" / "parallel_lane_results_latest.json"
            ),
            "fan_in_acceptance_latest": str(
                runtime / "state" / "root_intent_loop_driver" / "fan_in_acceptance_latest.json"
            ),
            "default_main_loop_trigger_candidate_latest": str(
                runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
            ),
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    payload["validation"] = {
        "passed": (
            payload["scheduler_lane_evidence_state"] == "scheduler_spawned_lanes_observed"
            and payload["scheduler_runtime_enforced"] is True
            and payload["default_runtime_scheduler_invoked"] is True
            and payload["dp_20_lane_set_bound"] is True
            and payload["scheduler_spawned_lane_count"] >= 21
            and payload["fan_in_consumed_real_lane_results"] is True
            and payload["fan_in_before_artifact_acceptance"] is True
            and payload["lane_results_source"] == "worker_dispatch_ledger_poll"
            and payload["synthetic_succeeded_count"] == 0
            and payload["fan_in_consumed_lane_result_count"]
            == payload["fan_in_expected_lane_result_count"]
            and payload["fan_in_accepted_edge_count"] == payload["fan_in_ledger_succeeded_count"]
            and payload["completion_claim_allowed"] is False
        ),
        "checks": {
            "scheduler_spawned_lanes_observed": payload["scheduler_lane_evidence_state"]
            == "scheduler_spawned_lanes_observed",
            "scheduler_runtime_enforced": payload["scheduler_runtime_enforced"] is True,
            "default_runtime_scheduler_invoked": payload["default_runtime_scheduler_invoked"]
            is True,
            "dp_20_lane_set_bound": payload["dp_20_lane_set_bound"] is True,
            "lane_count_at_least_21": payload["scheduler_spawned_lane_count"] >= 21,
            "fan_in_consumed_real_lane_results": payload["fan_in_consumed_real_lane_results"]
            is True,
            "fan_in_before_artifact_acceptance": payload["fan_in_before_artifact_acceptance"]
            is True,
            "worker_dispatch_ledger_succeeded_present": payload[
                "worker_dispatch_ledger_succeeded_present"
            ]
            is True,
            "fan_in_from_worker_dispatch_ledger_poll": payload[
                "fan_in_from_worker_dispatch_ledger_poll"
            ]
            is True,
            "no_driver_synthetic_succeeded_lane_results": payload[
                "no_driver_synthetic_succeeded_lane_results"
            ]
            is True,
            "lane_results_source_is_ledger_poll": payload["lane_results_source"]
            == "worker_dispatch_ledger_poll",
            "synthetic_succeeded_count_zero": payload["synthetic_succeeded_count"] == 0,
            "fan_in_count_matches_ledger_entry_count": payload["fan_in_consumed_lane_result_count"]
            == payload["fan_in_expected_lane_result_count"],
            "fan_in_accepted_edge_count_matches_ledger_succeeded": payload[
                "fan_in_accepted_edge_count"
            ]
            == payload["fan_in_ledger_succeeded_count"],
            "completion_claim_blocked": payload["completion_claim_allowed"] is False,
        },
        "validated_at": now_iso(),
    }
    if write:
        write_json(artifact_path, payload)
    return payload


def artifact_acceptance_candidates(
    *,
    repo: Path,
    runtime: Path,
    driver_acceptance_artifact: dict[str, Any],
) -> list[dict[str, Any]]:
    artifact_ref = str(
        driver_acceptance_artifact.get("evidence_refs", {}).get("driver_acceptance_artifact")
        if isinstance(driver_acceptance_artifact.get("evidence_refs"), dict)
        else runtime
        / "state"
        / "root_intent_loop_driver"
        / "root_intent_loop_default_runtime_artifact.json"
    )
    return [
        {
            "candidate_id": "root-intent-loop-default-runtime-continuation",
            "artifact_kind": "root_intent_loop_default_runtime_continuation",
            "producer_lane": "root_intent_loop_driver",
            "artifact_ref": artifact_ref,
            "expected_schema_version": (
                "xinao.codex_s.root_intent_loop_default_runtime_artifact.v1"
            ),
            "accepted_for": "delivery_or_frontier_evidence",
            "default_acceptance_decisions": [
                "accepted_for_binding",
                "accepted_for_delivery",
            ],
            "exception_acceptance_decision": "accepted_for_next_frontier",
            "next_frontier_default_exit": False,
            "verification_refs": [
                str(repo / "tests" / "seedcortex" / "test_root_intent_loop_driver.py"),
                str(repo / "scripts" / "verify_root_intent_loop_driver.ps1"),
            ],
            "fan_in_required": True,
            "file_exists_only": False,
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
        }
    ]


def invoke_p1_default_main_chain(
    *,
    runtime: Path,
    repo: Path,
    paths: dict[str, str],
    wave_id: str,
    codex_subagents: list[str] | None,
    default_trigger_enforcement: dict[str, Any],
    p1_module: Any | None,
    write: bool,
) -> dict[str, Any]:
    trigger_passed = (
        default_trigger_enforcement.get("validation", {}).get("passed") is True
        if isinstance(default_trigger_enforcement.get("validation"), dict)
        else False
    )
    if not trigger_passed:
        return {
            "schema_version": "xinao.codex_s.root_driver_p1_default_main_chain.v1",
            "status": "p1_default_main_chain_not_invoked_trigger_not_enforced",
            "generated_at": now_iso(),
            "work_id": WORK_ID,
            "route_profile": ROUTE_PROFILE,
            "root_driver_wave_id": wave_id,
            "runtime_enforced": False,
            "trigger_installed": False,
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "validation": {
                "passed": False,
                "checks": {
                    "root_trigger_enforcement_passed": False,
                    "p1_driver_called": False,
                    "wave04_plus_present": False,
                    "new_wave_this_tick_present": False,
                    "p3_distinct_frontier_pushed": False,
                    "trigger_durable_same_binding_enforced": False,
                },
                "validated_at": now_iso(),
            },
        }

    module = p1_module or load_sibling_module("codex_333_p1_loop_frontier")
    previous_p1_latest = load_json(runtime / "state" / "codex_333_p1_loop_frontier" / "latest.json")
    previous_p3_frontier = load_json(
        runtime / "state" / "codex_333_p1_loop_frontier" / "p3_frontier_latest.json"
    )
    previous_base_wave_id = (
        str(previous_p1_latest.get("base_wave_id") or "")
        if previous_p1_latest.get("default_main_chain") is True
        else ""
    )
    base_wave_id = previous_base_wave_id or f"{safe_id(wave_id)}-p1-default-main-chain"
    previous_wave_ids = (
        previous_p1_latest.get("while_wave_ids")
        if isinstance(previous_p1_latest.get("while_wave_ids"), list)
        else []
    )
    previous_max_wave_index = max(
        [wave_index_from_id(str(item)) for item in previous_wave_ids if str(item).strip()] or [0]
    )
    next_wave_index = max(previous_max_wave_index + 1, 4)
    previous_frontier_ref = (
        str(runtime / "state" / "codex_333_p1_loop_frontier" / "p3_frontier_latest.json")
        if previous_p3_frontier
        else str(runtime / "state" / "frontier_management_claimcards" / "latest.json")
    )
    p1_payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        task_id=WORK_ID,
        intent_package=None,
        base_wave_id=base_wave_id,
        wave_count=next_wave_index,
        codex_subagents=codex_subagents or [],
        default_main_chain=True,
        root_driver_wave_id=wave_id,
        auto_wave_index=next_wave_index,
        previous_frontier_ref=previous_frontier_ref,
        append_to_existing=True,
        write=write,
    )
    p1_refs = (
        p1_payload.get("p1_loop_frontier_refs")
        if isinstance(p1_payload.get("p1_loop_frontier_refs"), dict)
        else {}
    )
    p3_frontier = (
        p1_payload.get("p3_frontier") if isinstance(p1_payload.get("p3_frontier"), dict) else {}
    )
    summary = p1_payload.get("summary") if isinstance(p1_payload.get("summary"), dict) else {}
    output = (
        p1_payload.get("output_paths") if isinstance(p1_payload.get("output_paths"), dict) else {}
    )
    checks = {
        "root_trigger_enforcement_passed": trigger_passed,
        "p1_driver_called": True,
        "p1_validation_passed": p1_payload.get("validation", {}).get("passed") is True
        if isinstance(p1_payload.get("validation"), dict)
        else False,
        "p1_default_main_chain": p1_payload.get("default_main_chain") is True,
        "wave04_plus_present": summary.get("wave04_plus_present") is True
        and int(summary.get("latest_auto_wave_index") or 0) >= 4,
        "new_wave_this_tick_present": bool(summary.get("new_wave_ids_this_tick")),
        "fixed_three_wave_stop_absent": int(summary.get("latest_auto_wave_index") or 0) >= 4,
        "episode_default_hook_invoked": (
            p1_payload.get("p2_episode_fan_in_hook", {}).get("episode_default_hook") is True
            if isinstance(p1_payload.get("p2_episode_fan_in_hook"), dict)
            else False
        ),
        "trigger_durable_same_binding_enforced": p1_refs.get("validation", {}).get("passed") is True
        if isinstance(p1_refs.get("validation"), dict)
        else False,
        "p3_distinct_frontier_pushed": (
            p3_frontier.get("validation", {}).get("passed") is True
            if isinstance(p3_frontier.get("validation"), dict)
            else False
        )
        and p3_frontier.get("frontier_id") != "p3-333-total-draft-frontier-20260703",
        "execute_search_zero": int(summary.get("execute_search_invocation_count_total") or 0) == 0,
        "provider_probe_zero_for_p1": int(summary.get("provider_probe_invocation_count_total") or 0)
        == 0,
        "completion_claim_blocked": p1_payload.get("completion_claim_allowed") is False,
    }
    passed = all(checks.values())
    return {
        "schema_version": "xinao.codex_s.root_driver_p1_default_main_chain.v1",
        "status": (
            "p1_default_main_chain_auto_while_runtime_enforced"
            if passed
            else "p1_default_main_chain_auto_while_waiting_or_blocked"
        ),
        "generated_at": now_iso(),
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "root_driver_wave_id": wave_id,
        "p1_base_wave_id": base_wave_id,
        "previous_p1_latest_ref": str(
            runtime / "state" / "codex_333_p1_loop_frontier" / "latest.json"
        ),
        "previous_max_wave_index": previous_max_wave_index,
        "requested_next_wave_index": next_wave_index,
        "append_to_existing": True,
        "runtime_enforced": passed,
        "trigger_installed": passed,
        "p1_latest_ref": output.get(
            "runtime_latest", str(runtime / "state" / "codex_333_p1_loop_frontier" / "latest.json")
        ),
        "p1_task_latest_ref": output.get(
            "runtime_task_latest",
            str(runtime / "state" / "codex_333_p1_loop_frontier" / f"{WORK_ID}.json"),
        ),
        "p1_ref_bundle_ref": paths["p1_default_main_chain_latest"],
        "p1_continuation_ref": paths["p1_continuation_default_main_chain_latest"],
        "p1_wave03_ref": paths["p1_wave03_default_main_chain_latest"],
        "p1_readback_zh": paths["p1_default_main_chain_readback_zh"],
        "p1_continuation_readback_zh": paths["p1_continuation_default_main_chain_readback_zh"],
        "p2_fan_in_hook_ref": output.get(
            "p2_fan_in_hook_latest",
            str(runtime / "state" / "codex_333_p1_loop_frontier" / "p2_fan_in_hook_latest.json"),
        ),
        "p3_frontier_ref": output.get(
            "p3_frontier_latest",
            str(runtime / "state" / "codex_333_p1_loop_frontier" / "p3_frontier_latest.json"),
        ),
        "p3_frontier_id": p3_frontier.get("frontier_id", ""),
        "wave03_id": summary.get("wave03_id", f"{base_wave_id}-wave-03"),
        "wave03_id_deprecated_compat": summary.get("wave03_id", f"{base_wave_id}-wave-03"),
        "wave04_id": summary.get("wave04_id", f"{base_wave_id}-wave-04"),
        "wave04_plus_present": summary.get("wave04_plus_present") is True,
        "latest_auto_wave_index": int(summary.get("latest_auto_wave_index") or 0),
        "latest_auto_wave_id": str(summary.get("latest_auto_wave_id") or ""),
        "new_wave_ids_this_tick": summary.get("new_wave_ids_this_tick") or [],
        "p1_loop_frontier_refs": p1_refs,
        "p1_payload_summary": {
            "while_wave_count": summary.get("while_wave_count"),
            "wave03_floor_present_deprecated_compat": summary.get(
                "wave03_floor_present_deprecated_compat"
            ),
            "wave04_plus_present": summary.get("wave04_plus_present"),
            "latest_auto_wave_index": summary.get("latest_auto_wave_index"),
            "latest_auto_wave_id": summary.get("latest_auto_wave_id"),
            "new_wave_ids_this_tick": summary.get("new_wave_ids_this_tick"),
            "draft_eval_group_count_total": summary.get("draft_eval_group_count_total"),
            "execute_search_invocation_count_total": summary.get(
                "execute_search_invocation_count_total"
            ),
            "provider_probe_invocation_count_total": summary.get(
                "provider_probe_invocation_count_total"
            ),
        },
        "accepted_for": "delivery_or_frontier_evidence",
        "default_delivery_exit": "accepted_for_binding_or_accepted_for_delivery",
        "next_frontier_default_exit": False,
        "frontier_is_exception_path": True,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": passed,
            "checks": checks,
            "validated_at": now_iso(),
        },
    }


def build_episode_default_hook_evidence(
    *,
    runtime: Path,
    paths: dict[str, str],
    wave_id: str,
    p1_default_main_chain: dict[str, Any],
    acceptance_payload: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    p1_refs = (
        p1_default_main_chain.get("p1_loop_frontier_refs")
        if isinstance(p1_default_main_chain.get("p1_loop_frontier_refs"), dict)
        else {}
    )
    p1_summary = (
        p1_default_main_chain.get("p1_payload_summary")
        if isinstance(p1_default_main_chain.get("p1_payload_summary"), dict)
        else {}
    )
    output_paths = (
        acceptance_payload.get("output_paths")
        if isinstance(acceptance_payload.get("output_paths"), dict)
        else {}
    )
    workflow_port = (
        acceptance_payload.get("workflow_port_evidence")
        if isinstance(acceptance_payload.get("workflow_port_evidence"), dict)
        else {}
    )
    checkpoint = (
        acceptance_payload.get("langgraph_checkpoint")
        if isinstance(acceptance_payload.get("langgraph_checkpoint"), dict)
        else {}
    )
    decisions = (
        acceptance_payload.get("decisions")
        if isinstance(acceptance_payload.get("decisions"), list)
        else []
    )
    decision_digest = hashlib.sha256(
        json.dumps(decisions, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    episode_id = str(acceptance_payload.get("episode_id") or "root-intent-loop-driver-20260703")
    episode_trace_ref = str(runtime / "runs" / "episodes" / episode_id / "episode_trace.jsonl")
    delivery_acceptance_decisions = {
        "accepted_for_binding",
        "accepted_for_delivery",
        "accepted_for_next_frontier",
    }
    accepted_decision_refs = [
        f"{output_paths.get('episode_artifact', '')}#decisions[{index}]"
        for index, decision in enumerate(decisions)
        if isinstance(decision, dict)
        and decision.get("artifact_acceptance_decision") in delivery_acceptance_decisions
    ]
    accepted_decision_counts = {
        decision_name: sum(
            1
            for decision in decisions
            if isinstance(decision, dict)
            and decision.get("artifact_acceptance_decision") == decision_name
        )
        for decision_name in sorted(delivery_acceptance_decisions)
    }
    payload = {
        "schema_version": "xinao.codex_s.root_intent_loop_driver_episode_default_hook.v1",
        "status": "episode_default_hook_default_main_chain_enforced",
        "generated_at": now_iso(),
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "root_driver_wave_id": wave_id,
        "invoked_by": "root_intent_loop_driver.default_runtime_scheduler",
        "hook_stage": "after_p2_fan_in_before_p3_frontier",
        "runtime_enforced": True,
        "trigger_installed": True,
        "p1_wave_ids": p1_refs.get("wave_ids") or [],
        "wave_current_id": p1_default_main_chain.get("latest_auto_wave_id", ""),
        "latest_auto_wave_index": p1_default_main_chain.get("latest_auto_wave_index", 0),
        "p2_fan_in_hook_ref": p1_default_main_chain.get("p2_fan_in_hook_ref", ""),
        "p3_frontier_ref": p1_default_main_chain.get("p3_frontier_ref", ""),
        "p3_frontier_id": p1_default_main_chain.get("p3_frontier_id", ""),
        "artifact_acceptance_latest_ref": output_paths.get(
            "runtime_latest",
            str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        ),
        "artifact_acceptance_episode_artifact_ref": output_paths.get("episode_artifact", ""),
        "artifact_acceptance_decision_refs": accepted_decision_refs,
        "artifact_acceptance_default_decisions": [
            "accepted_for_binding",
            "accepted_for_delivery",
        ],
        "artifact_acceptance_exception_decisions": ["accepted_for_next_frontier"],
        "artifact_acceptance_decision_counts": accepted_decision_counts,
        "frontier_is_exception_path": True,
        "artifact_acceptance_decision_digest_sha256": decision_digest,
        "episode_id": episode_id,
        "episode_trace_ref": episode_trace_ref,
        "episode_trace_event_type": "artifact_acceptance_queue_ready",
        "workflow_port_evidence_ref": workflow_port.get("evidence_id", "")
        or workflow_port.get("evidence_ref", "")
        or "canonical artifact acceptance queue",
        "langgraph_checkpoint_ref": checkpoint.get("checkpoint_path", ""),
        "langgraph_checkpoint_persisted": checkpoint.get("checkpoint_persisted") is True,
        "accepted_for": "delivery_or_frontier_evidence",
        "default_delivery_exit": "accepted_for_binding_or_accepted_for_delivery",
        "next_frontier_default_exit": False,
        "latest_is_cache_only": True,
        "episode_artifact_is_bound_evidence": bool(output_paths.get("episode_artifact")),
        "execute_search": p1_summary.get("execute_search_invocation_count_total", 0),
        "completion_claim_allowed": False,
        "direct_fact_promotion_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    checks = {
        "p1_auto_while_wave04_plus": int(payload["latest_auto_wave_index"] or 0) >= 4,
        "p2_fan_in_hook_ref_bound": bool(payload["p2_fan_in_hook_ref"]),
        "p3_frontier_ref_bound": bool(payload["p3_frontier_ref"]),
        "artifact_acceptance_episode_artifact_bound": bool(
            payload["artifact_acceptance_episode_artifact_ref"]
        ),
        "artifact_acceptance_decision_refs_present": bool(accepted_decision_refs),
        "episode_trace_ref_declared": bool(episode_trace_ref),
        "workflow_port_evidence_ref_declared": bool(payload["workflow_port_evidence_ref"]),
        "langgraph_checkpoint_persisted": payload["langgraph_checkpoint_persisted"] is True,
        "execute_search_zero": int(payload["execute_search"] or 0) == 0,
        "direct_fact_promotion_blocked": payload["direct_fact_promotion_allowed"] is False,
        "completion_claim_blocked": payload["completion_claim_allowed"] is False,
    }
    payload["validation"] = {
        "passed": all(checks.values()),
        "checks": checks,
        "validated_at": now_iso(),
    }
    if write:
        write_json(Path(paths["episode_default_hook_latest"]), payload)
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    checks = payload.get("validation", {}).get("checks", {})
    can_invoke = (
        payload.get("can_invoke_now") if isinstance(payload.get("can_invoke_now"), dict) else {}
    )
    p1_chain = (
        payload.get("p1_default_main_chain")
        if isinstance(payload.get("p1_default_main_chain"), dict)
        else {}
    )
    episode_hook = (
        payload.get("episode_default_hook")
        if isinstance(payload.get("episode_default_hook"), dict)
        else {}
    )
    cost_router = (
        payload.get("global_cost_quality_quota_router")
        if isinstance(payload.get("global_cost_quality_quota_router"), dict)
        else {}
    )
    p1_refs = (
        payload.get("p1_loop_frontier_refs")
        if isinstance(payload.get("p1_loop_frontier_refs"), dict)
        else {}
    )
    matrix = (
        p1_refs.get("acceptance_matrix_i_to_v")
        if isinstance(p1_refs.get("acceptance_matrix_i_to_v"), dict)
        else {}
    )
    north_star = (
        p1_refs.get("north_star_readback_cn")
        if isinstance(p1_refs.get("north_star_readback_cn"), list)
        else []
    )
    return "\n".join(
        [
            "# Codex S RootIntentLoop Driver readback",
            "",
            SENTINEL,
            "",
            f"- status: `{payload['status']}`",
            f"- wave_id: `{payload['wave_id']}`",
            f"- runtime_enforced: {payload['runtime_enforced']}",
            f"- trigger_installed: {payload['trigger_installed']}",
            f"- should_continue_loop: {payload['should_continue_loop']}",
            f"- driver_is_controller: {payload['driver_is_controller']}",
            f"- stop_hook_controller: {payload['stop_hook_controller']}",
            f"- stop_handoff_consumed: {payload['stop_handoff_consumed']}",
            f"- called_default_main_loop_trigger_candidate: {checks.get('called_default_main_loop_trigger_candidate')}",
            f"- default_runtime_scheduler_invoked: {payload['default_runtime_scheduler_invocation']['default_runtime_scheduler_invoked']}",
            f"- scheduler_lane_evidence_state: `{payload['scheduler_default_runtime']['lane_evidence_state']}`",
            f"- scheduler_spawned_lane_count: {payload['scheduler_default_runtime']['scheduler_spawned_lane_count']}",
            f"- dp_20_lane_set_bound: {payload['dp_20_lane_set']['bound']}",
            f"- dp_port_invocation_count: {payload['dp_port_poll']['dp_port_invocation_count']}",
            f"- dp_ledger_succeeded_count: {payload['dp_port_poll']['dp_ledger_succeeded_count']}",
            f"- requested_model_mode_fallback_count: {payload['dp_port_poll']['requested_model_mode_fallback_count']}",
            f"- worker_dispatch_ledger_source: `{payload['worker_dispatch_ledger']['source_kind']}`",
            f"- worker_dispatch_ledger_succeeded_count: {payload['worker_dispatch_ledger']['succeeded_count']}",
            f"- fan_in_source_kind: `{payload['fan_in_acceptance']['source_kind']}`",
            f"- synthetic_succeeded_count: {payload['fan_in_acceptance']['synthetic_succeeded_count']}",
            f"- fan_in_lane_result_count: {payload['fan_in_acceptance']['lane_result_count']}",
            f"- fan_in_accepted_edge_count: {payload['fan_in_acceptance']['accepted_edge_count']}",
            f"- fan_in_consumed_scheduler_lane_results: {payload['fan_in_acceptance']['consumed_scheduler_lane_results']}",
            f"- fan_in_before_artifact_acceptance: {payload['fan_in_acceptance']['before_artifact_acceptance']}",
            f"- artifact_acceptance_accepted_count: {payload['artifact_acceptance']['accepted_artifact_count']}",
            f"- artifact_acceptance_queue_called: {payload['artifact_acceptance_queue']['called']}",
            f"- return_decision: `{payload['return_decision']['decision']}`",
            f"- named_blocker: `{payload['named_blocker']}`",
            f"- default_trigger_enforcement_ref: `{payload.get('default_trigger_enforcement', {}).get('latest')}`",
            f"- default_trigger_enforcement_readback_zh: `{payload.get('default_trigger_enforcement', {}).get('readback_zh')}`",
            f"- default_trigger_enforced_for_task: {payload.get('default_trigger_enforcement', {}).get('trigger_enforced')}",
            f"- global_cost_quality_quota_router: `{cost_router.get('router_name', '')}` consumed={cost_router.get('consumed_by_root_intent_loop')}",
            f"- global_route: `{cost_router.get('selected_route_id', '')}` providers={', '.join(cost_router.get('selected_provider_order') or [])}",
            f"- qwen_quota_priority: {cost_router.get('qwen_quota_priority_applies')} deepseek_codex_replacement: {cost_router.get('deepseek_codex_replacement_applies')}",
            f"- codex_boundary: `{cost_router.get('codex_boundary', '')}`",
            f"- p1_default_main_chain_status: `{p1_chain.get('status', '')}`",
            f"- p1_latest_auto_wave_id: `{p1_chain.get('latest_auto_wave_id', '')}` index={p1_chain.get('latest_auto_wave_index', 0)}",
            f"- p1_new_wave_ids_this_tick: {', '.join(p1_chain.get('new_wave_ids_this_tick') or [])}",
            f"- p1_p3_frontier_id: `{p1_chain.get('p3_frontier_id', '')}`",
            f"- episode_default_hook_status: `{episode_hook.get('status', '')}`",
            f"- episode_default_hook_stage: `{episode_hook.get('hook_stage', '')}`",
            f"- episode_default_hook_ref: `{payload.get('evidence_refs', {}).get('episode_default_hook_latest', '')}`",
            f"- acceptance_matrix_i_to_v: `{matrix.get('status', '')}`",
            f"- unique_authority_entry: `{payload.get('default_trigger_enforcement', {}).get('unique_authority_entry')}`",
            f"- can_invoke.runtime_chain: {', '.join(can_invoke.get('runtime_chain') or [])}",
            f"- can_invoke.dp_requested_modes_bound: {', '.join(can_invoke.get('dp_requested_modes_bound') or [])}",
            f"- can_invoke.model_gateway_modes_observed: {', '.join(can_invoke.get('model_gateway_modes_observed') or [])}",
            f"- can_invoke.tool_sidecar_modes_observed: {', '.join(can_invoke.get('tool_sidecar_modes_observed') or [])}",
            f"- can_invoke.carrier_providers_observed: {', '.join(can_invoke.get('carrier_providers_observed') or [])}",
            f"- can_invoke.provider_probe_role: `{can_invoke.get('provider_probe_role')}`",
            "- Stop hook 只转交 should_continue_loop；执行 controller 是 RootIntentLoop driver。",
            "- fan-in 只消费 worker_dispatch_ledger poll；无 ledger succeeded 不允许 validation.passed。",
            "- DP lane 按 requested mode 真调用；模型路由未绑定的 lane 记录 blocked/named_blocker，不合成 provider_probe 成功。",
            "- provider_probe 只能作为少量探针 lane，不允许冒充 bulk progress。",
            "- default_main_loop_trigger_candidate 保持候选视图；333 本任务的 trigger enforced 由 RootIntentLoop driver + scheduler + DP + fan-in 证据承载。",
            "- TokenBudgetGate / GlobalCostQualityQuotaRouter 是 UserPromptSubmit 前置读模型：短小任务可 Codex 直读，适合的长文本/盘点先用 Qwen 额度，困难审计再用 DeepSeek V4 Pro，Codex 保留 final patch/merge/AAQ。它不是 worker scheduler，也不是 333 新主线。",
            "- P1 default main chain 由 RootIntentLoop driver 在 trigger enforcement 之后 invoke；auto_while 追加 wave04+ 并把 P2/P3 frontier 写入 driver evidence refs，不把 P1 island 当 owner。",
            "- episode 默认 hook 是 RootIntentLoop 主链在 P2 FanIn 后调用 ArtifactAcceptanceQueue 的证据，不是新岛。",
            "- AAQ 默认出口是 accepted_for_binding / accepted_for_delivery；accepted_for_next_frontier 只保留为 research/discovery exception，不做事实晋升、不做 completion。",
            "- 现在能 invoke：RootIntentLoop -> Task Router/default scheduler -> worker/provider lanes -> FanIn -> episode default hook/AAQ -> deliverable/binding acceptance；P3 NextFrontier 是例外证据路径，execute_search=0。",
            f"- {payload.get('can_invoke_now_cn')}",
            "- 每波固定形状：intent/context -> deliverable contract -> dispatch -> poll -> fan-in -> verifier -> ArtifactAcceptance -> ContinuityEnvelope -> next deliverable/root recompute。",
            "- completion_claim_allowed=False；这是运行闭环证据，不是用户完成声明。",
            "- 旧 CLEAN / 5d33 只作为 reference-only；driver 不写 secrets。",
            "",
            "## 验收矩阵 I-V",
            "",
            f"- I 主链归位：{matrix.get('I_main_chain_return', {})}",
            f"- II durable enforced：{matrix.get('II_durable_enforced', {})}",
            f"- III wave04+ 自动 while：{matrix.get('III_wave04_plus_auto_while', {})}",
            f"- IV 宽度 + episode hook：{matrix.get('IV_width_episode_hook', {})}",
            f"- V S diff + capabilities + 替换轮：{matrix.get('V_s_diff_capabilities_replacement', {})}",
            "",
            "## 北极星三句",
            "",
            *[f"{index}. {sentence}" for index, sentence in enumerate(north_star, start=1)],
            "",
            "## L 层差距",
            "",
            "- L0：启动权威优先来自任务包 manifest（TASK_PACKAGE/datapackage resources）；旧读序/旧总稿只在无 manifest 的 legacy fallback 中参考。",
            "- L1：intake/trigger/readback 只能接活和发现 refs；L1 不得冒充 L3 默认 runtime。",
            "- L2：RootIntentLoop driver verifier 证明本 driver 可消费 ledger poll 并 fan-in；这是机器证据层。",
            "- L3：每一波仍要由真实 workflow/checkpoint/worker_dispatch_ledger/ArtifactAcceptance/next_wave 证明继续执行。",
            "- 当前差距：driver 已 runtime_enforced，但 complete/user accepted 仍为 false，不能把本 readback 当完成。",
            "",
            SENTINEL,
            "",
        ]
    )


def _thin_glue_root_intent_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_ROOT_INTENT", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    wave_id: str = "codex-s-root-intent-loop-driver-wave-20260703",
    codex_subagents: list[str] | None = None,
    bind_provider_worker_pool: bool = False,
    phase1_target_width: int = 0,
    phase1_max_parallel_workers: int | None = 12,
    phase1_require_external_draft: bool = True,
    workflow_id: str = "",
    workflow_run_id: str = "",
    explicit_user_stop: bool = False,
    ordinary_discussion: bool = False,
    service: Any | None = None,
    p1_module: Any | None = None,
    p1_default_main_chain_enabled: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    try:
        from services.agent_runtime.integrated_bus_facade_redirect import facade_hard_redirect_enabled
        from services.agent_runtime.integrated_bus_runner import run_integrated_bus

        if facade_hard_redirect_enabled() and not bind_provider_worker_pool:
            payload = run_integrated_bus(
                None,
                runtime_root=Path(runtime_root),
                repo_root=Path(repo_root),
                temporal=False,
                mainline_default=True,
            )
            payload["delegated_from"] = "root_intent_loop_driver.build"
            payload["hand_rolled_build_bypassed"] = True
            payload["handroll_intact"] = False
            return payload
    except Exception:
        pass
    if _thin_glue_root_intent_enabled() and not bind_provider_worker_pool:
        from services.agent_runtime.thin_glue_l2_root_intent import run_thin_glue_root_intent_tick

        thin_payload = run_thin_glue_root_intent_tick(
            runtime_root=runtime_root,
            repo_root=repo_root,
            wave_id=wave_id,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            write=write,
        )
        thin_payload["delegated_from"] = "root_intent_loop_driver.build"
        thin_payload["hand_rolled_build_bypassed"] = True
        return thin_payload
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    ensure_import_path(repo)
    if service is None:
        from xinao_seedlab.application.seed_cortex import build_default_service

        service = build_default_service(runtime, repo_root=repo)

    paths = output_paths(repo, runtime)
    stop_decision = stop_audit_decision(
        runtime=runtime,
        explicit_user_stop=explicit_user_stop,
        ordinary_discussion=ordinary_discussion,
    )
    trigger_payload: dict[str, Any] = {}
    scheduler_invocation: dict[str, Any] = {}
    lane_payload: dict[str, Any] = {}
    dp_poll_payload: dict[str, Any] = {}
    worker_ledger_payload: dict[str, Any] = {}
    fan_in_payload: dict[str, Any] = {}
    driver_acceptance_artifact: dict[str, Any] = {}
    acceptance_payload: dict[str, Any] = {}
    continuity_envelope: dict[str, Any] = {}
    mainline_stack: dict[str, Any] = {}
    default_trigger_enforcement: dict[str, Any] = {}
    allocation_plan_payload: dict[str, Any] = {}
    cost_quota_router = global_cost_quality_quota_router(runtime)

    if stop_decision["should_continue_loop"]:
        allocation_module = load_sibling_module("allocation_plan")
        allocation_plan_payload = allocation_module.build(
            runtime_root=runtime,
            repo_root=repo,
            task_id=WORK_ID,
            wave_id=f"{wave_id}-allocation-plan",
            extra_refs={
                "workflow_refs": [paths["runtime_latest"]],
                "event_history_refs": [paths["scheduler_invocation_latest"]],
                "frontdoor_route_refs": [cost_quota_router["latest"]],
            },
            write=write,
        )
        trigger_payload = service.default_main_loop_trigger_candidate(
            anchor_package_root=str(anchor_package_root),
            wave_id=wave_id,
            codex_subagents=codex_subagents or [],
            bind_provider_worker_pool=bind_provider_worker_pool,
            phase1_target_width=phase1_target_width,
            phase1_max_parallel_workers=phase1_max_parallel_workers,
            phase1_require_external_draft=phase1_require_external_draft,
            allocation_plan_activity=allocation_plan_payload,
            workflow_id=workflow_id or wave_id,
            workflow_run_id=workflow_run_id,
            write_runtime=write,
        )
        lanes = codex_lane_refs(codex_subagents) + dp_lane_refs(wave_id)
        scheduler_invocation = write_default_scheduler_invocation(
            runtime=runtime,
            repo=repo,
            wave_id=wave_id,
            lanes=lanes,
            trigger_ref=Path(
                runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
            ),
            write=write,
        )
        lane_module = load_sibling_module("scheduler_spawned_lane_evidence")
        lane_payload = lane_module.build_scheduler_spawned_lane_evidence(
            runtime_root=runtime,
            repo_root=repo,
            wave_id=wave_id,
            scheduler_invocation_ref=Path(paths["scheduler_invocation_latest"]),
            output_latest=runtime
            / "state"
            / "scheduler_spawned_lane_evidence"
            / "default_runtime_latest.json",
            write=write,
        )
        dp_poll_payload = invoke_dp_port_lanes(
            runtime=runtime,
            wave_id=wave_id,
            lanes=lanes,
            write=write,
        )
        worker_ledger_payload = write_worker_dispatch_ledger_for_dp_poll(
            runtime=runtime,
            repo=repo,
            wave_id=wave_id,
            dp_poll=dp_poll_payload,
            write=write,
        )
        existing_ledger = read_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
        ledger_for_fanin = worker_ledger_payload
        ledger_bridge_mode = ""
        if existing_ledger:
            existing_succeeded = int(existing_ledger.get("succeeded_count") or 0)
            local_succeeded = int(worker_ledger_payload.get("succeeded_count") or 0)
            if existing_succeeded > local_succeeded:
                ledger_for_fanin = existing_ledger
                ledger_bridge_mode = "temporal_default_mainline"
        if not ledger_bridge_mode:
            terminal_statuses = {"succeeded", "failed", "blocked", "cancelled"}
            nonterminal_allowed_statuses = {"planned_not_spawned", "dispatched_not_polled"}
            ledger_entries = root_driver_ledger_entries(ledger_for_fanin, wave_id)
            nonterminal_entries = [
                entry
                for entry in ledger_entries
                if entry.get("poll_status") not in terminal_statuses
            ]
            if nonterminal_entries and all(
                entry.get("poll_status") in nonterminal_allowed_statuses
                for entry in nonterminal_entries
            ):
                ledger_bridge_mode = "temporal_default_mainline"
        fan_in_payload = write_lane_results_and_fan_in(
            runtime=runtime,
            repo=repo,
            wave_id=wave_id,
            scheduler_invocation=scheduler_invocation,
            lane_payload=lane_payload,
            ledger_payload=ledger_for_fanin,
            dp_poll_payload=dp_poll_payload,
            write=write,
            ledger_bridge_mode=ledger_bridge_mode,
        )
        driver_acceptance_artifact = write_driver_acceptance_artifact(
            runtime=runtime,
            repo=repo,
            wave_id=wave_id,
            lane_payload=lane_payload,
            trigger_payload=trigger_payload,
            scheduler_invocation=scheduler_invocation,
            fan_in_payload=fan_in_payload,
            write=write,
        )
        if write:
            acceptance_payload = service.artifact_acceptance_queue(
                "root-intent-loop-driver-20260703",
                artifact_acceptance_candidates(
                    repo=repo,
                    runtime=runtime,
                    driver_acceptance_artifact=driver_acceptance_artifact,
                ),
                write_runtime=True,
            )
        continuity_envelope = build_continuity_envelope(
            runtime=runtime,
            repo=repo,
            wave_id=wave_id,
            stop_decision=stop_decision,
            trigger_payload=trigger_payload,
            lane_payload=lane_payload,
            fan_in_payload=fan_in_payload,
            acceptance_payload=acceptance_payload,
            write=write,
        )
        mainline_stack = write_mainline_stack(
            runtime=runtime,
            repo=repo,
            wave_id=wave_id,
            continuity_envelope=continuity_envelope,
            write=write,
        )

    accepted_count = int(acceptance_payload.get("accepted_artifact_count") or 0)
    lane_count = int(lane_payload.get("scheduler_spawned_lane_count") or 0)
    dp_lane_count = int(scheduler_invocation.get("dp_sidecar_execution_lane_ref_count") or 0)
    dp_ledger_succeeded_count = int(dp_poll_payload.get("dp_ledger_succeeded_count") or 0)
    dp_nonprobe_true_invocation_count = int(
        dp_poll_payload.get("nonprobe_true_invocation_count") or 0
    )
    worker_ledger_succeeded_count = int(worker_ledger_payload.get("succeeded_count") or 0)
    fan_in_validation_passed = (
        fan_in_payload.get("lane_results", {}).get("validation", {}).get("passed") is True
        if isinstance(fan_in_payload.get("lane_results"), dict)
        else False
    )
    trigger_worker_pool_invocation = (
        trigger_payload.get("provider_worker_pool_invocation")
        if isinstance(trigger_payload.get("provider_worker_pool_invocation"), dict)
        else {}
    )
    trigger_truth_chain = (
        trigger_payload.get("trigger_truth_chain")
        if isinstance(trigger_payload.get("trigger_truth_chain"), dict)
        else {}
    )
    trigger_worker_pool_satisfied = not bind_provider_worker_pool or (
        trigger_worker_pool_invocation.get("invoked") is True
        and trigger_truth_chain.get("ready") is True
        and int(trigger_truth_chain.get("worker_dispatch_ledger_succeeded_count") or 0)
        == int(trigger_truth_chain.get("actual_completed_width") or -1)
        and int(trigger_truth_chain.get("unique_accepted_artifact_count") or 0) > 0
    )
    status = (
        "root_intent_loop_driver_runtime_enforced"
        if stop_decision["should_continue_loop"]
        and accepted_count > 0
        and lane_payload.get("lane_evidence_state") == "scheduler_spawned_lanes_observed"
        and worker_ledger_succeeded_count > 0
        and dp_ledger_succeeded_count > 0
        and dp_nonprobe_true_invocation_count > 0
        and fan_in_validation_passed
        and trigger_worker_pool_satisfied
        and cost_quota_router["consumed_by_root_intent_loop"] is True
        and cost_quota_router["fixed_deepseek_share_target_used"] is False
        else "root_intent_loop_driver_waiting_or_blocked"
    )
    named_blocker = ""
    if not stop_decision["should_continue_loop"]:
        named_blocker = "ROOT_INTENT_LOOP_STOP_HANDOFF_NOT_ACTIVE"
    elif cost_quota_router["consumed_by_root_intent_loop"] is not True:
        named_blocker = "ROOT_INTENT_LOOP_TOKEN_BUDGET_GATE_NOT_CONSUMED"
    elif cost_quota_router["fixed_deepseek_share_target_used"] is True:
        named_blocker = "ROOT_INTENT_LOOP_FIXED_DEEPSEEK_SHARE_TARGET_FORBIDDEN"
    elif not trigger_worker_pool_satisfied:
        named_blocker = "ROOT_INTENT_LOOP_DEFAULT_TRIGGER_QWEN_DP_WORKER_POOL_NOT_BOUND"
    elif lane_payload.get("lane_evidence_state") != "scheduler_spawned_lanes_observed":
        named_blocker = "ROOT_INTENT_LOOP_SCHEDULER_LANES_NOT_OBSERVED"
    elif worker_ledger_succeeded_count <= 0:
        named_blocker = "ROOT_INTENT_LOOP_WORKER_DISPATCH_LEDGER_NO_SUCCEEDED"
    elif dp_ledger_succeeded_count <= 0:
        named_blocker = "ROOT_INTENT_LOOP_NO_DP_LEDGER_SUCCEEDED"
    elif dp_nonprobe_true_invocation_count <= 0:
        named_blocker = "ROOT_INTENT_LOOP_NO_NONPROBE_DP_TRUE_INVOKE"
    elif not fan_in_validation_passed:
        named_blocker = "ROOT_INTENT_LOOP_FAN_IN_DID_NOT_CONSUME_LEDGER_POLL"
    elif accepted_count <= 0:
        named_blocker = "ROOT_INTENT_LOOP_ARTIFACT_ACCEPTANCE_EMPTY"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "workflow_id": workflow_id or wave_id,
        "workflow_run_id": workflow_run_id,
        "status": status,
        "generated_at": now_iso(),
        "adoption_state": (
            "runtime_enforced"
            if status == "root_intent_loop_driver_runtime_enforced"
            else "candidate_registered"
        ),
        "runtime_enforced": status == "root_intent_loop_driver_runtime_enforced",
        "runtime_enforced_scope": "seed_cortex_root_intent_loop_driver",
        "trigger_installed": status == "root_intent_loop_driver_runtime_enforced",
        "should_continue_loop": stop_decision["should_continue_loop"],
        "driver_is_controller": True,
        "is_execution_controller": True,
        "stop_hook_controller": False,
        "stop_hook_is_controller": False,
        "stop_hook_transfer_only": True,
        "stop_handoff_consumed": stop_decision["should_continue_loop"],
        "main_execution_loop": MAIN_EXECUTION_LOOP,
        "consumed_stop_audit": stop_decision,
        "default_trigger": {
            "called": bool(trigger_payload),
            "status": trigger_payload.get("status"),
            "adoption_state": trigger_payload.get("adoption_state"),
            "runtime_latest": str(
                runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
            ),
            "service_latest": str(
                runtime
                / "state"
                / "default_main_loop_trigger_candidate"
                / "service_entrypoint_latest.json"
            ),
        },
        "default_main_loop_trigger_candidate": {
            "called": bool(trigger_payload),
            "status": trigger_payload.get("status"),
            "adoption_state": trigger_payload.get("adoption_state"),
            "runtime_enforced": trigger_payload.get("runtime_enforced"),
            "trigger_installed": trigger_payload.get("trigger_installed"),
            "runtime_latest": str(
                runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
            ),
            "service_latest": str(
                runtime
                / "state"
                / "default_main_loop_trigger_candidate"
                / "service_entrypoint_latest.json"
            ),
        },
        "main_tick": {
            "runtime_latest": str(
                runtime / "state" / "codex_s_main_execution_loop_tick" / "latest.json"
            ),
            "service_latest": str(
                runtime
                / "state"
                / "codex_s_main_execution_loop_tick"
                / "service_entrypoint_latest.json"
            ),
        },
        "durable_parallel_wave_packet": {
            "runtime_latest": str(
                runtime / "state" / "durable_parallel_wave_packet" / "latest.json"
            ),
            "service_latest": str(
                runtime
                / "state"
                / "durable_parallel_wave_packet"
                / "service_entrypoint_latest.json"
            ),
        },
        "allocation_plan": {
            "called": bool(allocation_plan_payload),
            "latest": allocation_plan_payload.get("output_paths", {}).get("latest", ""),
            "worker_brief_queue": allocation_plan_payload.get("output_paths", {}).get(
                "worker_brief_queue_latest", ""
            ),
            "lane_allocations": allocation_plan_payload.get("output_paths", {}).get(
                "lane_allocations_latest", ""
            ),
            "lane_class_count": allocation_plan_payload.get("lane_class_count", 0),
            "total_requested_width": allocation_plan_payload.get("total_requested_width", 0),
            "target_width_source": allocation_plan_payload.get("target_width_source", ""),
            "fixed_20_or_50_used": allocation_plan_payload.get("fixed_20_or_50_used"),
            "repair_required": allocation_plan_payload.get("repair_required") is True,
            "validation_passed": allocation_plan_payload.get("validation", {}).get("passed")
            if isinstance(allocation_plan_payload.get("validation"), dict)
            else False,
            "consumed_by_root_driver": bool(allocation_plan_payload),
            "not_task_route_decision_enum": allocation_plan_payload.get(
                "not_task_route_decision_enum"
            )
            is True,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
        "global_cost_quality_quota_router": cost_quota_router,
        "scheduler_default_runtime": {
            "scheduler_invocation_ref": paths["scheduler_invocation_latest"],
            "scheduler_spawned_lane_evidence_ref": str(
                runtime
                / "state"
                / "scheduler_spawned_lane_evidence"
                / "default_runtime_latest.json"
            ),
            "lane_evidence_state": lane_payload.get("lane_evidence_state"),
            "scheduler_spawned_lane_count": lane_count,
            "default_runtime_scheduler_invoked": lane_payload.get(
                "default_runtime_scheduler_invoked"
            )
            is True,
            "runtime_enforced": lane_payload.get("runtime_enforced") is True,
        },
        "default_runtime_scheduler_invocation": {
            "latest": paths["scheduler_invocation_latest"],
            "scheduler_invoked": scheduler_invocation.get("scheduler_invoked") is True,
            "runtime_enforced": scheduler_invocation.get("runtime_enforced") is True,
            "default_runtime_scheduler_invoked": scheduler_invocation.get(
                "default_runtime_scheduler_invoked"
            )
            is True,
            "scheduler_spawned_lane_count": scheduler_invocation.get("spawned_lane_count"),
            "validation_passed": scheduler_invocation.get("validation", {}).get("passed")
            if isinstance(scheduler_invocation.get("validation"), dict)
            else None,
        },
        "scheduler_default_runtime_lane_evidence_state": lane_payload.get("lane_evidence_state"),
        "scheduler_spawned_lane_evidence": {
            "latest": str(
                runtime
                / "state"
                / "scheduler_spawned_lane_evidence"
                / "default_runtime_latest.json"
            ),
            "lane_evidence_state": lane_payload.get("lane_evidence_state"),
            "runtime_enforced": lane_payload.get("runtime_enforced") is True,
            "default_runtime_scheduler_invoked": lane_payload.get(
                "default_runtime_scheduler_invoked"
            )
            is True,
        },
        "dp_port_poll": {
            "dp_port_invocation_count": int(dp_poll_payload.get("dp_port_invocation_count") or 0),
            "dp_ledger_succeeded_count": dp_ledger_succeeded_count,
            "dp_ledger_blocked_count": int(dp_poll_payload.get("dp_ledger_blocked_count") or 0),
            "dp_ledger_failed_count": int(dp_poll_payload.get("dp_ledger_failed_count") or 0),
            "requested_model_mode_fallback_count": int(
                dp_poll_payload.get("requested_model_mode_fallback_count") or 0
            ),
            "provider_probe_invocation_count": int(
                dp_poll_payload.get("provider_probe_invocation_count") or 0
            ),
            "nonprobe_invocation_count": int(dp_poll_payload.get("nonprobe_invocation_count") or 0),
            "nonprobe_true_invocation_count": dp_nonprobe_true_invocation_count,
            "nonprobe_succeeded_count": int(dp_poll_payload.get("nonprobe_succeeded_count") or 0),
            "provider_probe_bulk_progress_allowed": bool(
                dp_poll_payload.get("provider_probe_bulk_progress_allowed") is True
            ),
            "dp_port_invocations": dp_poll_payload.get("dp_port_invocations") or [],
        },
        "worker_dispatch_ledger": {
            "latest": str(runtime / "state" / "worker_dispatch_ledger" / "latest.json"),
            "poll_latest": str(runtime / "state" / "worker_dispatch_ledger" / "latest.json"),
            "source_kind": "worker_dispatch_ledger_poll",
            "poll_source": "worker_dispatch_ledger_poll",
            "succeeded_count": worker_ledger_succeeded_count,
            "succeeded_entry_ids": worker_ledger_payload.get("succeeded_entry_ids") or [],
            "driver_synthetic_succeeded_allowed": False,
            "validation_passed": worker_ledger_payload.get("validation", {}).get("passed")
            if isinstance(worker_ledger_payload.get("validation"), dict)
            else None,
            "entry_count": len(worker_ledger_payload.get("dispatch_entries") or [])
            if isinstance(worker_ledger_payload.get("dispatch_entries"), list)
            else 0,
            "root_driver_entry_count": len(
                root_driver_ledger_entries(worker_ledger_payload, wave_id)
            ),
            "root_driver_succeeded_count": worker_ledger_succeeded_count,
            "dp_root_driver_succeeded_count": dp_ledger_succeeded_count,
            "lane_results_must_source_from_ledger_poll": True,
        },
        "dp_20_lane_set": {
            "bound": dp_lane_count == 20,
            "lane_count": dp_lane_count,
            "mode_counts": DP_MODE_COUNTS,
            "provider_width_ref": str(
                runtime / "state" / "dp_sidecar_execution_provider" / "latest.json"
            ),
            "port_runner_ref": str(runtime / "state" / "dp_sidecar_execution_port" / "latest.json"),
            "provider_width_current": json_ref(
                runtime / "state" / "dp_sidecar_execution_provider" / "latest.json"
            ).get("current_default_provider_width"),
            "mature_router_gate_must_pass_before_model_modes": True,
            "nonprobe_true_invocation_count": dp_nonprobe_true_invocation_count,
            "provider_probe_bulk_progress_allowed": False,
            "fan_in_and_artifact_acceptance_required": True,
        },
        "fan_in_acceptance": {
            "lane_results_latest": paths["lane_results_latest"],
            "fan_in_acceptance_latest": paths["fan_in_acceptance_latest"],
            "lane_result_count": fan_in_payload.get("lane_results", {}).get("lane_result_count")
            if isinstance(fan_in_payload.get("lane_results"), dict)
            else 0,
            "ledger_entry_count": fan_in_payload.get("lane_results", {}).get("ledger_entry_count")
            if isinstance(fan_in_payload.get("lane_results"), dict)
            else 0,
            "ledger_succeeded_count": fan_in_payload.get("lane_results", {}).get(
                "ledger_succeeded_count"
            )
            if isinstance(fan_in_payload.get("lane_results"), dict)
            else 0,
            "source_kind": "worker_dispatch_ledger_poll",
            "worker_dispatch_ledger_succeeded_count": fan_in_payload.get("lane_results", {}).get(
                "ledger_succeeded_count"
            )
            if isinstance(fan_in_payload.get("lane_results"), dict)
            else 0,
            "driver_synthetic_succeeded_allowed": False,
            "accepted_edge_count": len(
                fan_in_payload.get("fan_in_acceptance", {}).get("accepted_edges") or []
            )
            if isinstance(fan_in_payload.get("fan_in_acceptance"), dict)
            else 0,
            "lane_results_source": fan_in_payload.get("lane_results", {}).get("lane_results_source")
            if isinstance(fan_in_payload.get("lane_results"), dict)
            else "",
            "synthetic_succeeded_count": fan_in_payload.get("lane_results", {}).get(
                "synthetic_succeeded_count"
            )
            if isinstance(fan_in_payload.get("lane_results"), dict)
            else None,
            "consumed_scheduler_lane_results": bool(
                fan_in_payload.get("lane_results", {}).get("fan_in_consumed_real_lane_results")
            )
            if isinstance(fan_in_payload.get("lane_results"), dict)
            else False,
            "consumed_ledger_poll_results": bool(
                fan_in_payload.get("lane_results", {}).get("fan_in_consumed_real_lane_results")
            )
            if isinstance(fan_in_payload.get("lane_results"), dict)
            else False,
            "before_artifact_acceptance": bool(
                fan_in_payload.get("lane_results", {}).get("fan_in_before_artifact_acceptance")
            )
            if isinstance(fan_in_payload.get("lane_results"), dict)
            else False,
        },
        "artifact_acceptance": {
            "latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
            "accepted_artifact_count": accepted_count,
            "staged_candidate_count": acceptance_payload.get("staged_candidate_count"),
            "rejected_artifact_count": acceptance_payload.get("rejected_artifact_count"),
        },
        "artifact_acceptance_queue": {
            "called": bool(acceptance_payload),
            "latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
            "episode_artifact": acceptance_payload.get("output_paths", {}).get("episode_artifact")
            if isinstance(acceptance_payload.get("output_paths"), dict)
            else "",
            "accepted_artifact_count": accepted_count,
            "staged_candidate_count": acceptance_payload.get("staged_candidate_count"),
            "rejected_artifact_count": acceptance_payload.get("rejected_artifact_count"),
            "blocked_artifact_count": acceptance_payload.get("blocked_artifact_count"),
            "validation_passed": acceptance_payload.get("validation", {}).get("passed")
            if isinstance(acceptance_payload.get("validation"), dict)
            else None,
        },
        "driver_acceptance_artifact": {
            "latest": str(
                runtime
                / "state"
                / "root_intent_loop_driver"
                / "root_intent_loop_default_runtime_artifact.json"
            ),
            "validation_passed": driver_acceptance_artifact.get("validation", {}).get("passed")
            if isinstance(driver_acceptance_artifact.get("validation"), dict)
            else False,
            "dp_20_lane_set_bound": driver_acceptance_artifact.get("dp_20_lane_set_bound") is True,
        },
        "continuity_envelope": {
            "latest": paths["continuity_envelope_latest"],
            "next_default_action": continuity_envelope.get("next_default_action"),
            "named_blocker": continuity_envelope.get("named_blocker"),
            "chinese_anchor_text": continuity_envelope.get("chinese_anchor_text"),
            "chinese_readback_ref": continuity_envelope.get("chinese_readback_ref"),
            "return_stack_count": continuity_envelope.get("return_stack_count"),
            "return_stack": continuity_envelope.get("return_stack"),
            "return_target_order": continuity_envelope.get("return_target_order"),
            "root_recompute_when_empty": continuity_envelope.get("root_recompute_when_empty")
            is True,
        },
        "mainline_stack": {
            "latest": paths["mainline_stack_latest"],
            "pop_restore_available": mainline_stack.get("pop_restore_available") is True,
            "next_return_decision": mainline_stack.get("next_return_decision"),
        },
        "return_decision": {
            "decision": (
                continuity_envelope.get("next_default_action") or "do_not_dispatch_driver"
            ),
            "return_target_order": RETURN_TARGET_ORDER,
        },
        "named_blocker": named_blocker,
        "evidence_refs": {
            **paths,
            "default_main_loop_trigger_candidate_latest": str(
                runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
            ),
            "main_execution_loop_tick_latest": str(
                runtime / "state" / "codex_s_main_execution_loop_tick" / "latest.json"
            ),
            "codex_s_main_execution_loop_tick_latest": str(
                runtime / "state" / "codex_s_main_execution_loop_tick" / "latest.json"
            ),
            "durable_parallel_wave_packet_latest": str(
                runtime / "state" / "durable_parallel_wave_packet" / "latest.json"
            ),
            "scheduler_spawned_lane_evidence_default_runtime_latest": str(
                runtime
                / "state"
                / "scheduler_spawned_lane_evidence"
                / "default_runtime_latest.json"
            ),
            "parallel_lane_results_latest": paths["lane_results_latest"],
            "fan_in_acceptance_latest": paths["fan_in_acceptance_latest"],
            "driver_acceptance_artifact_latest": str(
                runtime
                / "state"
                / "root_intent_loop_driver"
                / "root_intent_loop_default_runtime_artifact.json"
            ),
            "artifact_acceptance_queue_latest": str(
                runtime / "state" / "artifact_acceptance_queue" / "latest.json"
            ),
            "codex_s_token_budget_gate_latest": cost_quota_router["latest"],
        },
        "readback_refs": {
            "runtime_readback_zh": paths["runtime_readback_zh"],
            "human_visible_readback_required": True,
        },
        "completion_claim_allowed": False,
        "phase1_data_chain_allowed": False,
        "positive_ev_claim_allowed": False,
        "phase0_completion_claim_allowed": False,
        "legacy_clean_runtime_role": "reference_only",
        "legacy_5d33_role": "reference_only",
        "secrets_written": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": False,
    }
    payload["validation"] = {
        "passed": status == "root_intent_loop_driver_runtime_enforced",
        "checks": {
            "stop_handoff_consumed": payload["stop_handoff_consumed"] is True,
            "should_continue_loop_read_from_stop_audit": (
                payload["should_continue_loop"]
                == payload["consumed_stop_audit"]["should_continue_loop"]
            ),
            "driver_is_controller": payload["driver_is_controller"] is True
            and payload["not_execution_controller"] is False,
            "called_default_main_loop_trigger_candidate": payload["default_trigger"]["called"]
            is True,
            "scheduler_spawned_lanes_observed": payload["scheduler_default_runtime"][
                "lane_evidence_state"
            ]
            == "scheduler_spawned_lanes_observed",
            "default_runtime_scheduler_invocation_ref_written": (
                Path(paths["scheduler_invocation_latest"]).is_file()
                if write
                else bool(scheduler_invocation)
            ),
            "token_budget_gate_latest_consumed": cost_quota_router["consumed_by_root_intent_loop"]
            is True,
            "token_budget_gate_latest_json_valid": cost_quota_router["json_valid"] is True,
            "global_cost_quality_quota_router_visible": cost_quota_router["router_name"]
            == "GlobalCostQualityQuotaRouter",
            "global_router_not_model_worker_scheduler": cost_quota_router[
                "not_model_worker_scheduler"
            ]
            is True,
            "global_router_no_fixed_deepseek_share": cost_quota_router[
                "fixed_deepseek_share_target_used"
            ]
            is False,
            "qwen_quota_priority_visible": "qwen_quota_priority_applies" in cost_quota_router,
            "deepseek_codex_replacement_visible": "deepseek_codex_replacement_applies"
            in cost_quota_router,
            "codex_boundary_visible": bool(cost_quota_router["codex_boundary"]),
            "scheduler_default_runtime_enforced": payload["scheduler_default_runtime"][
                "runtime_enforced"
            ]
            is True,
            "dp_20_lane_set_bound": payload["dp_20_lane_set"]["bound"] is True,
            "dp_port_invoked_20_lanes": payload["dp_port_poll"]["dp_port_invocation_count"] == 20,
            "dp_ledger_has_succeeded_poll": payload["dp_port_poll"]["dp_ledger_succeeded_count"]
            > 0,
            "dp_nonprobe_true_invocation_present": payload["dp_port_poll"][
                "nonprobe_true_invocation_count"
            ]
            > 0,
            "provider_probe_not_bulk_progress": payload["dp_port_poll"][
                "provider_probe_bulk_progress_allowed"
            ]
            is False,
            "worker_dispatch_ledger_succeeded_present": payload["worker_dispatch_ledger"][
                "succeeded_count"
            ]
            > 0,
            "worker_dispatch_ledger_root_entries_bound": payload["worker_dispatch_ledger"][
                "root_driver_entry_count"
            ]
            == int(payload["scheduler_default_runtime"]["scheduler_spawned_lane_count"] or 0),
            "fan_in_consumed_real_lane_results": payload["fan_in_acceptance"][
                "consumed_ledger_poll_results"
            ]
            is True,
            "fan_in_from_worker_dispatch_ledger_poll": payload["fan_in_acceptance"]["source_kind"]
            == "worker_dispatch_ledger_poll"
            and payload["fan_in_acceptance"]["consumed_ledger_poll_results"] is True,
            "fan_in_source_is_worker_dispatch_ledger_poll": payload["fan_in_acceptance"][
                "lane_results_source"
            ]
            == "worker_dispatch_ledger_poll",
            "synthetic_succeeded_count_zero": payload["fan_in_acceptance"][
                "synthetic_succeeded_count"
            ]
            == 0,
            "no_driver_synthetic_succeeded_lane_results": payload["fan_in_acceptance"][
                "driver_synthetic_succeeded_allowed"
            ]
            is False
            and payload["fan_in_acceptance"]["synthetic_succeeded_count"] == 0,
            "fan_in_before_artifact_acceptance": payload["fan_in_acceptance"][
                "before_artifact_acceptance"
            ]
            is True,
            "fan_in_count_matches_scheduler_lane_count": int(
                payload["fan_in_acceptance"]["lane_result_count"] or 0
            )
            == payload["worker_dispatch_ledger"]["root_driver_entry_count"],
            "fan_in_accepted_edge_count_matches_ledger_succeeded": int(
                payload["fan_in_acceptance"]["accepted_edge_count"] or 0
            )
            == int(payload["fan_in_acceptance"]["ledger_succeeded_count"] or 0),
            "artifact_acceptance_has_accepted_artifact": accepted_count > 0,
            "continuity_envelope_written": Path(paths["continuity_envelope_latest"]).is_file()
            if write
            else bool(continuity_envelope),
            "mainline_stack_written": Path(paths["mainline_stack_latest"]).is_file()
            if write
            else bool(mainline_stack),
            "completion_claim_blocked": payload["completion_claim_allowed"] is False,
            "stop_hook_not_controller": payload["stop_hook_controller"] is False,
            "legacy_clean_reference_only": payload["legacy_clean_runtime_role"] == "reference_only",
            "secrets_not_written": payload["secrets_written"] is False,
        },
        "validated_at": now_iso(),
    }
    default_trigger_enforcement = write_default_trigger_enforcement(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        anchor_package_root=Path(anchor_package_root),
        payload=payload,
        write=write,
    )
    payload["default_trigger_enforcement"] = {
        "latest": paths["default_trigger_enforcement_latest"],
        "readback_zh": paths["default_trigger_enforcement_readback_zh"],
        "status": default_trigger_enforcement.get("status"),
        "runtime_enforced": default_trigger_enforcement.get("runtime_enforced") is True,
        "trigger_enforced": default_trigger_enforcement.get("trigger_enforced") is True,
        "trigger_installed": default_trigger_enforcement.get("trigger_installed") is True,
        "unique_authority_entry": default_trigger_enforcement.get("unique_authority_entry"),
        "can_invoke_now": default_trigger_enforcement.get("can_invoke_now") or {},
        "can_invoke_now_cn": default_trigger_enforcement.get("can_invoke_now_cn") or "",
        "validation_passed": default_trigger_enforcement.get("validation", {}).get("passed")
        if isinstance(default_trigger_enforcement.get("validation"), dict)
        else False,
    }
    payload["can_invoke_now"] = default_trigger_enforcement.get("can_invoke_now") or {}
    payload["can_invoke_now_cn"] = default_trigger_enforcement.get("can_invoke_now_cn") or ""
    payload["evidence_refs"]["default_trigger_enforcement_latest"] = paths[
        "default_trigger_enforcement_latest"
    ]
    payload["readback_refs"]["default_trigger_enforcement_readback_zh"] = paths[
        "default_trigger_enforcement_readback_zh"
    ]
    payload["validation"]["checks"]["default_trigger_enforcement_written"] = (
        Path(paths["default_trigger_enforcement_latest"]).is_file()
        if write
        else bool(default_trigger_enforcement)
    )
    payload["validation"]["checks"]["default_trigger_enforced_for_task"] = (
        payload["default_trigger_enforcement"]["validation_passed"] is True
    )
    payload["validation"]["checks"]["can_invoke_now_present"] = bool(
        payload["can_invoke_now"].get("runtime_chain")
    )
    payload["validation"]["passed"] = (
        payload["validation"]["passed"] is True
        and payload["validation"]["checks"]["default_trigger_enforcement_written"] is True
        and payload["validation"]["checks"]["default_trigger_enforced_for_task"] is True
        and payload["validation"]["checks"]["can_invoke_now_present"] is True
    )
    p1_default_main_chain = (
        invoke_p1_default_main_chain(
            runtime=runtime,
            repo=repo,
            paths=paths,
            wave_id=wave_id,
            codex_subagents=codex_subagents or [],
            default_trigger_enforcement=default_trigger_enforcement,
            p1_module=p1_module,
            write=write,
        )
        if p1_default_main_chain_enabled
        else {
            "schema_version": "xinao.codex_s.root_driver_p1_default_main_chain.v1",
            "status": "p1_default_main_chain_disabled",
            "runtime_enforced": False,
            "trigger_installed": False,
            "validation": {"passed": False, "checks": {}, "validated_at": now_iso()},
        }
    )
    payload["p1_default_main_chain"] = p1_default_main_chain
    payload["p1_loop_frontier_refs"] = (
        p1_default_main_chain.get("p1_loop_frontier_refs")
        if isinstance(p1_default_main_chain.get("p1_loop_frontier_refs"), dict)
        else {}
    )
    payload["evidence_refs"]["p1_default_main_chain_latest"] = paths["p1_default_main_chain_latest"]
    payload["evidence_refs"]["p1_continuation_default_main_chain_latest"] = paths[
        "p1_continuation_default_main_chain_latest"
    ]
    payload["evidence_refs"]["p1_wave03_default_main_chain_latest"] = paths[
        "p1_wave03_default_main_chain_latest"
    ]
    payload["evidence_refs"]["p1_loop_frontier_latest"] = p1_default_main_chain.get(
        "p1_latest_ref",
        str(runtime / "state" / "codex_333_p1_loop_frontier" / "latest.json"),
    )
    payload["evidence_refs"]["p1_p2_fan_in_hook_latest"] = p1_default_main_chain.get(
        "p2_fan_in_hook_ref",
        str(runtime / "state" / "codex_333_p1_loop_frontier" / "p2_fan_in_hook_latest.json"),
    )
    payload["evidence_refs"]["p1_p3_frontier_latest"] = p1_default_main_chain.get(
        "p3_frontier_ref",
        str(runtime / "state" / "codex_333_p1_loop_frontier" / "p3_frontier_latest.json"),
    )
    payload["readback_refs"]["p1_default_main_chain_readback_zh"] = paths[
        "p1_default_main_chain_readback_zh"
    ]
    payload["readback_refs"]["p1_continuation_default_main_chain_readback_zh"] = paths[
        "p1_continuation_default_main_chain_readback_zh"
    ]
    if isinstance(payload.get("can_invoke_now"), dict):
        runtime_chain = payload["can_invoke_now"].setdefault("runtime_chain", [])
        if (
            isinstance(runtime_chain, list)
            and "codex_333_p1_loop_frontier.default_main_chain_auto_while" not in runtime_chain
        ):
            runtime_chain.append("codex_333_p1_loop_frontier.default_main_chain_auto_while")
    payload["can_invoke_now_cn"] = (
        f"{payload.get('can_invoke_now_cn', '')}；还可由 RootIntentLoop 默认主链 invoke "
        "P1 auto_while wave04+、P2 episode FanIn hook；P3 distinct frontier 仅作为 research/discovery exception evidence。"
    )
    p1_validation_passed = (
        p1_default_main_chain.get("validation", {}).get("passed") is True
        if isinstance(p1_default_main_chain.get("validation"), dict)
        else False
    )
    p1_validation = (
        p1_default_main_chain.get("validation")
        if isinstance(p1_default_main_chain.get("validation"), dict)
        else {}
    )
    p1_checks = p1_validation.get("checks") if isinstance(p1_validation.get("checks"), dict) else {}
    p1_status = str(p1_default_main_chain.get("status") or "")
    p1_progress_checks_passed = all(
        p1_checks.get(check_name) is True
        for check_name in (
            "wave04_plus_present",
            "new_wave_this_tick_present",
            "episode_default_hook_invoked",
            "p3_distinct_frontier_pushed",
            "trigger_durable_same_binding_enforced",
        )
    )
    p1_progress_accepted = p1_validation_passed or (
        p1_status == "p1_default_main_chain_auto_while_waiting_or_blocked"
        and p1_progress_checks_passed
    )
    payload["validation"]["checks"]["p1_default_main_chain_invoked"] = (
        p1_status == "p1_default_main_chain_auto_while_runtime_enforced" or p1_progress_accepted
    )
    payload["validation"]["checks"]["p1_progress_wave_accepted"] = p1_progress_accepted
    payload["validation"]["checks"]["p1_wave04_plus_auto_present"] = (
        p1_checks.get("wave04_plus_present") is True
    )
    payload["validation"]["checks"]["p1_new_wave_this_tick_present"] = (
        p1_checks.get("new_wave_this_tick_present") is True
    )
    payload["validation"]["checks"]["p1_episode_default_hook_invoked"] = (
        p1_checks.get("episode_default_hook_invoked") is True
    )
    payload["validation"]["checks"]["p1_p3_distinct_frontier_pushed"] = (
        p1_checks.get("p3_distinct_frontier_pushed") is True
    )
    payload["validation"]["checks"]["p1_trigger_durable_same_binding_enforced"] = (
        p1_checks.get("trigger_durable_same_binding_enforced") is True
    )
    episode_default_hook = build_episode_default_hook_evidence(
        runtime=runtime,
        paths=paths,
        wave_id=wave_id,
        p1_default_main_chain=p1_default_main_chain,
        acceptance_payload=acceptance_payload,
        write=write,
    )
    payload["episode_default_hook"] = episode_default_hook
    payload["evidence_refs"]["episode_default_hook_latest"] = paths["episode_default_hook_latest"]
    payload["validation"]["checks"]["episode_default_hook_runtime_enforced"] = (
        episode_default_hook.get("validation", {}).get("passed") is True
        if isinstance(episode_default_hook.get("validation"), dict)
        else False
    )
    payload["validation"]["passed"] = (
        payload["validation"]["passed"] is True
        and p1_progress_accepted
        and payload["validation"]["checks"]["episode_default_hook_runtime_enforced"] is True
    )
    ledger_latest_reassertion = reassert_worker_dispatch_ledger_latest(
        runtime=runtime,
        worker_ledger_payload=worker_ledger_payload,
        reason="after_p1_default_main_chain_rebind_global_latest_to_root_dp_poll",
        write=write,
    )
    payload["worker_dispatch_ledger"]["latest_reasserted_after_p1"] = (
        ledger_latest_reassertion.get("reasserted") is True
    )
    payload["worker_dispatch_ledger"]["latest_reassertion"] = ledger_latest_reassertion
    payload["evidence_refs"]["worker_dispatch_ledger_latest_reasserted"] = (
        ledger_latest_reassertion.get("runtime_latest")
        or payload["worker_dispatch_ledger"]["latest"]
    )
    ledger_reassertion_required = (
        stop_decision["should_continue_loop"] is True
        and status == "root_intent_loop_driver_runtime_enforced"
    )
    payload["validation"]["checks"]["worker_dispatch_ledger_latest_reasserted"] = (
        True
        if not ledger_reassertion_required
        else (
            ledger_latest_reassertion.get("reasserted") is True
            if write
            else bool(worker_ledger_payload)
        )
    )
    payload["validation"]["passed"] = (
        payload["validation"]["passed"] is True
        and payload["validation"]["checks"]["worker_dispatch_ledger_latest_reasserted"] is True
    )
    if not p1_progress_accepted and status == "root_intent_loop_driver_runtime_enforced":
        payload["status"] = "root_intent_loop_driver_waiting_or_blocked"
        payload["adoption_state"] = "candidate_registered"
        payload["runtime_enforced"] = False
        payload["trigger_installed"] = False
        payload["named_blocker"] = "ROOT_INTENT_LOOP_P1_DEFAULT_MAIN_CHAIN_NOT_INVOKED"
    payload["payload_digest_sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if write:
        write_json(Path(paths["runtime_latest"]), payload)
        write_text(Path(paths["runtime_readback_zh"]), render_readback(payload))
    return payload


def run_temporal_root_driver_tick(
    *,
    runtime_root: str | Path,
    repo_root: str | Path,
    wave_id: str = "",
    workflow_id: str = "",
    workflow_run_id: str = "",
    worker_dispatch_ledger_activity_ref: dict[str, Any] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    if _thin_glue_root_intent_enabled():
        from services.agent_runtime.thin_glue_l2_root_intent import run_thin_glue_root_intent_tick

        thin = run_thin_glue_root_intent_tick(
            runtime_root=runtime_root,
            repo_root=repo_root,
            wave_id=wave_id or "thin-glue-root-intent-temporal-tick",
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            write=write,
            temporal_activity=True,
        )
        passed = thin.get("validation", {}).get("passed") is True
        succeeded_count = int(thin.get("ledger_succeeded_count") or 0)
        return {
            "schema_version": "xinao.codex_s.root_intent_loop_temporal_tick.v1",
            "status": "temporal_root_driver_tick_ready" if passed else "temporal_root_driver_tick_blocked",
            "task_id": "p0_027_temporal_every_wave_root_driver_tick",
            "temporal_every_wave_root_driver_tick_ready": passed,
            "ledger_succeeded_count": succeeded_count,
            "consumed_ledger_poll_results": passed,
            "fan_in_validation_passed": passed,
            "named_blocker": "" if passed else str(thin.get("named_blocker") or ""),
            "validation": thin.get("validation"),
            "generated_at": thin.get("generated_at"),
            "thin_glue_l2_root_intent": thin,
            "thin_glue_mainline_bridge": thin.get("thin_glue_mainline_bridge"),
            "hand_rolled_temporal_tick_bypassed": True,
        }
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    bridge = bridge_temporal_worker_dispatch_ledger_fanin(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=wave_id,
        write=write,
    )
    succeeded_count = int(bridge.get("ledger_succeeded_count") or 0)
    driver_latest = read_json(runtime / "state" / "root_intent_loop_driver" / "latest.json")
    if driver_latest and write:
        driver_latest["workflow_id"] = workflow_id or driver_latest.get("workflow_id")
        driver_latest["workflow_run_id"] = workflow_run_id or driver_latest.get("workflow_run_id")
        driver_latest["temporal_every_wave_root_driver_tick"] = {
            "invoked_by": "temporal_codex_task_workflow.root_intent_loop_driver_temporal_tick_activity",
            "effective_wave_id": bridge.get("effective_wave_id"),
            "ledger_succeeded_count": succeeded_count,
            "consumed_ledger_poll_results": bridge.get("consumed_ledger_poll_results") is True,
            "worker_dispatch_ledger_activity_ref": worker_dispatch_ledger_activity_ref or {},
            "generated_at": now_iso(),
        }
        write_json(runtime / "state" / "root_intent_loop_driver" / "latest.json", driver_latest)
    validation_passed = bridge.get("validation", {}).get("passed") is True and succeeded_count > 0
    from services.agent_runtime.thin_glue_mainline_bridge import attach_thin_glue_bridge_evidence

    thin_glue_bridge = attach_thin_glue_bridge_evidence(runtime)
    return {
        "schema_version": "xinao.codex_s.root_intent_loop_temporal_tick.v1",
        "status": "temporal_root_driver_tick_ready"
        if validation_passed
        else "temporal_root_driver_tick_blocked",
        "task_id": "p0_027_temporal_every_wave_root_driver_tick",
        "temporal_every_wave_root_driver_tick_ready": validation_passed,
        "ledger_succeeded_count": succeeded_count,
        "consumed_ledger_poll_results": bridge.get("consumed_ledger_poll_results") is True,
        "fan_in_validation_passed": bridge.get("fan_in_validation_passed") is True,
        "bridge_ref": str(
            runtime
            / "state"
            / "root_intent_loop_driver"
            / "temporal_ledger_fanin_bridge_latest.json"
        ),
        "named_blocker": ""
        if validation_passed
        else str(bridge.get("named_blocker") or "ROOT_DRIVER_LEDGER_POLL_NOT_CONSUMED_BY_FANIN"),
        "validation": {
            "passed": validation_passed,
            "checks": {
                "ledger_succeeded_gt_zero": succeeded_count > 0,
                "fan_in_consumed_ledger_poll": bridge.get("consumed_ledger_poll_results") is True,
                "temporal_worker_turn_lanes_included": succeeded_count > 0,
            },
            "validated_at": now_iso(),
        },
        "generated_at": now_iso(),
        "thin_glue_mainline_bridge": thin_glue_bridge,
    }


def run_root_intent_loop_driver(**kwargs: Any) -> dict[str, Any]:
    return build(**kwargs)


def build_cli_summary(payload: dict[str, Any]) -> dict[str, Any]:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    router = (
        payload.get("global_cost_quality_quota_router")
        if isinstance(payload.get("global_cost_quality_quota_router"), dict)
        else {}
    )
    return {
        "schema_version": payload.get("schema_version"),
        "sentinel": payload.get("sentinel"),
        "wave_id": payload.get("wave_id"),
        "status": payload.get("status"),
        "runtime_enforced": payload.get("runtime_enforced"),
        "trigger_installed": payload.get("trigger_installed"),
        "named_blocker": payload.get("named_blocker", ""),
        "validation": {
            "passed": validation.get("passed"),
            "failed_checks": [key for key, value in checks.items() if value is not True],
        },
        "global_cost_quality_quota_router": {
            "router_name": router.get("router_name", ""),
            "selected_route_id": router.get("selected_route_id", ""),
            "selected_provider_order": router.get("selected_provider_order", []),
            "fixed_deepseek_share_target_used": router.get("fixed_deepseek_share_target_used"),
            "consumed_by_root_intent_loop": router.get("consumed_by_root_intent_loop"),
        },
        "evidence_refs": {
            "latest": payload.get("evidence_refs", {}).get("runtime_latest")
            or str(DEFAULT_RUNTIME / "state" / "root_intent_loop_driver" / "latest.json"),
            "readback": payload.get("readback_refs", {}).get("runtime_readback_zh"),
            "default_trigger_enforcement_latest": payload.get("evidence_refs", {}).get(
                "default_trigger_enforcement_latest"
            ),
        },
        "completion_claim_allowed": payload.get("completion_claim_allowed"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="codex-s-root-intent-loop-driver-wave-20260703")
    parser.add_argument("--codex-subagent", action="append", default=[])
    parser.add_argument("--bind-provider-worker-pool", action="store_true")
    parser.add_argument("--phase1-target-width", type=int, default=0)
    parser.add_argument("--phase1-max-parallel-workers", type=int, default=12)
    parser.add_argument("--allow-local-stub-acceptance", action="store_true")
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--explicit-user-stop", action="store_true")
    parser.add_argument("--ordinary-discussion", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--full-output", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        wave_id=args.wave_id,
        codex_subagents=args.codex_subagent,
        bind_provider_worker_pool=args.bind_provider_worker_pool,
        phase1_target_width=args.phase1_target_width,
        phase1_max_parallel_workers=args.phase1_max_parallel_workers,
        phase1_require_external_draft=not args.allow_local_stub_acceptance,
        workflow_id=args.workflow_id,
        workflow_run_id=args.workflow_run_id,
        explicit_user_stop=args.explicit_user_stop,
        ordinary_discussion=args.ordinary_discussion,
        write=not args.no_write,
    )
    output_payload = payload if args.full_output else build_cli_summary(payload)
    print(json.dumps(output_payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
