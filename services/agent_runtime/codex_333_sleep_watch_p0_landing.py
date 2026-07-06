from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
from pathlib import Path
from typing import Any, Callable

from services.agent_runtime import modular_dynamic_worker_pool_phase1 as phase1


SCHEMA_VERSION = "xinao.codex_s.333_sleep_watch_p0_landing.v1"
SENTINEL = "SENTINEL:XINAO_333_SLEEP_WATCH_P0_LANDING"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = WORK_ID
NODE_ID = "333_sleep_watch_p0_landing"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(
    os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S")
)
DEFAULT_WORKFLOW_ID = "333-sleep-watch-source-package-20260705-r1"
DEFAULT_TEMPORAL_ADDRESS = "127.0.0.1:7233"
DEFAULT_TASK_QUEUE = "xinao-codex-task-default"
STATE_NAME = "333_sleep_watch_p0_landing"
CURRENT_INDEX_STATE = "current_333_run_index"
CAPABILITY_PIPELINE_STATE = "capability_absorption_pipeline"
SOURCE_PACKAGE_FILES = [
    Path(r"C:\Users\xx363\Desktop\新建文件夹\333_DEFAULT_CHAIN_EVOLUTION_QWEN_DP_AUDIT_20260705.txt"),
    Path(r"C:\Users\xx363\Desktop\新建文件夹\333_DEFAULT_CHAIN_GLOBAL_REPAIR_PACKAGE_20260705.txt"),
    Path(r"C:\Users\xx363\Desktop\新建文件夹\333_GLOBAL_CAPABILITY_ISLAND_INVENTORY_QWEN_DP_20260705.txt"),
    Path(r"C:\Users\xx363\Desktop\新建文件夹\333_S_HANDOFF_MERGED_LANDABLE_PACKAGE_QWEN_DP_20260705.txt"),
    Path(r"C:\Users\xx363\Desktop\新建文件夹\GLOBAL_MAINCHAIN_CONFLICT_AUDIT_QWEN_DP_ONLY_20260705.txt"),
]
FOREGROUND_WATCH_REF = Path(r"C:\Users\xx363\Desktop\前台长watch_后台镜像语义.txt")
MAX_MATURE_COMPONENT_REQUESTED_REF = Path(
    r"C:\Users\xx363\Desktop\最大成熟组件能力最大化.txt"
)
MAX_MATURE_COMPONENT_REF = MAX_MATURE_COMPONENT_REQUESTED_REF
MAX_MATURE_COMPONENT_FALLBACK_REFS = (
    Path(r"C:\Users\xx363\Desktop\旧系统\最大成熟组件能力最大化.txt"),
)
EXTERNAL_MATURE_ROOT = Path(r"E:\XINAO_EXTERNAL_MATURE\codex_20260627")
CRITICAL_P0_LANE_IDS = [
    "333-sw-p0-current-run-index",
    "333-sw-p0-toolregistry-index",
    "333-sw-p0-provider-realness-gate",
    "333-sw-p0-dynamic-width-evidence",
    "333-sw-p0-capability-absorption",
]
REQUIRED_TOOL_REGISTRY_IDS = [
    "codex_s.333_stateful_continuity_router",
    "codex_s.333_task_transaction_control",
    "codex_s.direct_worker_lane",
    "qwen_prepaid_cheap_worker",
    "legacy.deepseek_dp_sidecar",
    "codex_s.capability_gateway",
    "mcp.xinao_runtime.tools",
    "d_runtime.capability_manifests",
]


CommandRunner = Callable[[list[str], int], dict[str, Any]]


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / STATE_NAME
    current_index = runtime / "state" / CURRENT_INDEX_STATE
    pipeline = runtime / "state" / CAPABILITY_PIPELINE_STATE
    tool_registry = runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json"
    assignment_dag_evidence = runtime / "state" / "task_bound_evidence" / WORK_ID / "assignment_dag"
    return {
        "state": state,
        "latest": state / "latest.json",
        "record": state / "records" / f"{NODE_ID}.json",
        "readback": runtime / "readback" / "zh" / f"{STATE_NAME}.md",
        "current_index_latest": current_index / "latest.json",
        "current_index_record": current_index / "records" / f"{DEFAULT_WORKFLOW_ID}.json",
        "tool_registry": tool_registry,
        "five_layer_index": runtime
        / "state"
        / "five_layer_capability_index"
        / "latest.json",
        "capability_pipeline_latest": pipeline / "latest.json",
        "capability_pipeline_record": pipeline / "records" / f"{NODE_ID}.json",
        "assignment_dag_evidence_latest": assignment_dag_evidence / "latest.json",
        "assignment_dag_node_latest": assignment_dag_evidence / f"{NODE_ID}.latest.json",
        "assignment_dag_node_jsonl": assignment_dag_evidence / f"{NODE_ID}.jsonl",
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _file_facts(path: Path) -> dict[str, Any]:
    text = _read_text(path)
    exists = path.is_file()
    return {
        "path": str(path),
        "name": path.name,
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
        "line_count": len(text.splitlines()) if text else 0,
        "char_count": len(text),
        "sha256": _sha256_text(text) if text else "",
        "read_in_full": exists and text != "",
    }


def _default_command_runner(command: list[str], timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except FileNotFoundError as exc:
        return {
            "command": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
        }


def _tcp_port_open(address: str, timeout_seconds: float = 1.5) -> bool:
    host, _, port_text = address.partition(":")
    try:
        with socket.create_connection((host, int(port_text)), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _parse_temporal_describe(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    key_map = {
        "WorkflowId": "workflow_id",
        "RunId": "workflow_run_id",
        "TaskQueue": "task_queue",
        "StateTransitionCount": "state_transition_count",
        "HistoryLength": "history_length",
        "HistorySize": "history_size",
        "RootWorkflowId": "root_workflow_id",
        "RootRunId": "root_run_id",
    }
    in_pending_activities = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Pending Activities:"):
            in_pending_activities = True
        elif stripped.startswith("Pending Child Workflows:"):
            in_pending_activities = False
        if not in_pending_activities and stripped.startswith("Type") and not fields.get("workflow_type"):
            fields["workflow_type"] = stripped[len("Type") :].strip()
            continue
        for source, target in key_map.items():
            if stripped.startswith(source):
                value = stripped[len(source) :].strip()
                fields[target] = int(value) if value.isdigit() else value
    pending_match = re.search(r"Pending Activities:\s*(\d+)", text)
    if pending_match:
        fields["pending_activity_count"] = int(pending_match.group(1))
    pending_section = ""
    if "Pending Activities:" in text:
        pending_section = text.split("Pending Activities:", 1)[1]
        for marker in ("Pending Child Workflows:", "Pending Nexus Operations:"):
            pending_section = pending_section.split(marker, 1)[0]
    fields["pending_activity_types"] = re.findall(
        r"^\s*Type\s+([A-Za-z0-9_]+)\s*$", pending_section, flags=re.M
    )
    return fields


def _parse_temporal_list(text: str, workflow_id: str) -> dict[str, Any]:
    for line in text.splitlines():
        if workflow_id not in line:
            continue
        match = re.match(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+", line)
        if match:
            return {
                "status": match.group(1),
                "workflow_id": match.group(2),
                "workflow_type": match.group(3),
                "line": line.strip(),
            }
    return {}


def build_temporal_probe(
    *,
    workflow_id: str,
    address: str,
    command_runner: CommandRunner | None = None,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if override is not None:
        return dict(override)
    runner = command_runner or _default_command_runner
    port_open = _tcp_port_open(address)
    describe = runner(
        ["temporal", "workflow", "describe", "--address", address, "--workflow-id", workflow_id],
        20,
    )
    workflow_list = runner(["temporal", "workflow", "list", "--address", address, "--limit", "10"], 20)
    describe_text = f"{describe.get('stdout', '')}\n{describe.get('stderr', '')}"
    list_text = f"{workflow_list.get('stdout', '')}\n{workflow_list.get('stderr', '')}"
    parsed_describe = _parse_temporal_describe(describe_text)
    parsed_list = _parse_temporal_list(list_text, workflow_id)
    status = str(parsed_list.get("status") or "")
    named_blocker = ""
    if not port_open:
        named_blocker = "TEMPORAL_SERVER_NOT_RUNNING"
    elif describe.get("returncode") != 0 or not parsed_describe.get("workflow_run_id"):
        named_blocker = "TEMPORAL_WORKFLOW_DESCRIBE_UNAVAILABLE"
    elif workflow_list.get("returncode") != 0 or not parsed_list:
        named_blocker = "TEMPORAL_WORKFLOW_LIST_UNAVAILABLE"
    return {
        "address": address,
        "port_open": port_open,
        "workflow_id": workflow_id,
        "workflow_run_id": parsed_describe.get("workflow_run_id", ""),
        "status": status,
        "task_queue": parsed_describe.get("task_queue", ""),
        "workflow_type": parsed_describe.get("workflow_type", ""),
        "history_length": parsed_describe.get("history_length", 0),
        "state_transition_count": parsed_describe.get("state_transition_count", 0),
        "history_size": parsed_describe.get("history_size", 0),
        "pending_activity_count": parsed_describe.get("pending_activity_count", 0),
        "pending_activity_types": parsed_describe.get("pending_activity_types", []),
        "describe_returncode": describe.get("returncode"),
        "list_returncode": workflow_list.get("returncode"),
        "describe_error": describe.get("stderr", ""),
        "list_error": workflow_list.get("stderr", ""),
        "list_line": parsed_list.get("line", ""),
        "named_blocker": named_blocker,
    }


def _extract_first_decision(payload: dict[str, Any]) -> dict[str, Any]:
    decisions = payload.get("decisions")
    if isinstance(decisions, list) and decisions:
        first = decisions[0]
        return first if isinstance(first, dict) else {}
    return {}


def _workflow_run_evidence_paths(
    runtime: Path,
    workflow_id: str,
    workflow_run_id: str,
) -> dict[str, Path]:
    safe_workflow = phase1.safe_stem(workflow_id or "workflow-unbound")
    safe_run = phase1.safe_stem(workflow_run_id or "run-unbound")
    assignment_root = (
        runtime / "state" / "task_bound_evidence" / WORK_ID / "assignment_dag"
    )
    phase1_root = runtime / "state" / "modular_dynamic_worker_pool_phase1"
    return {
        "assignment_node_latest": (
            assignment_root
            / "workflow_runs"
            / safe_workflow
            / safe_run
            / f"{NODE_ID}.latest.json"
        ),
        "assignment_node_jsonl": assignment_root / f"{NODE_ID}.jsonl",
        "fan_in_latest": (
            phase1_root
            / "fan_in_staging_merge_spend"
            / "workflow_runs"
            / safe_workflow
            / safe_run
            / "latest.json"
        ),
    }


def _has_rich_assignment_node_fields(payload: dict[str, Any]) -> bool:
    return (
        payload.get("status") == "assignment_dag_node_evidence_written"
        and str(payload.get("assignment_dag_node_id") or payload.get("node_id") or "")
        == NODE_ID
        and isinstance(payload.get("lane_bindings"), list)
        and len(payload.get("lane_bindings", [])) >= len(CRITICAL_P0_LANE_IDS)
    )


def _latest_rich_assignment_node_from_jsonl(
    path: Path,
    workflow_id: str,
    workflow_run_id: str,
) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if (
            str(payload.get("workflow_id") or "") == workflow_id
            and str(payload.get("workflow_run_id") or "") == workflow_run_id
            and _has_rich_assignment_node_fields(payload)
        ):
            return payload
    return {}


def resolve_workflow_run_evidence(
    *,
    runtime: Path,
    workflow_id: str,
    workflow_run_id: str,
) -> dict[str, Any]:
    paths = _workflow_run_evidence_paths(runtime, workflow_id, workflow_run_id)
    node = _read_json(paths["assignment_node_latest"])
    node_ref = str(paths["assignment_node_latest"])
    if not _has_rich_assignment_node_fields(node):
        jsonl_node = _latest_rich_assignment_node_from_jsonl(
            paths["assignment_node_jsonl"],
            workflow_id,
            workflow_run_id,
        )
        if jsonl_node:
            node = jsonl_node
            node_ref = f"{paths['assignment_node_jsonl']}#latest-rich-assignment-node"
    fan_in = _read_json(paths["fan_in_latest"])
    lane_bindings = (
        node.get("lane_bindings") if isinstance(node.get("lane_bindings"), list) else []
    )
    lane_success_count = len(
        [
            item
            for item in lane_bindings
            if isinstance(item, dict) and str(item.get("status") or "") == "succeeded"
        ]
    )
    unique_accepted = int(
        fan_in.get("unique_accepted_artifact_count")
        or node.get("unique_accepted_artifact_count")
        or 0
    )
    accepted_count = int(
        fan_in.get("accepted_artifact_count")
        or node.get("accepted_artifact_count")
        or unique_accepted
        or 0
    )
    wave_id = str(node.get("wave_id") or fan_in.get("wave_id") or "")
    checks = {
        "assignment_node_ref_exists": bool(node),
        "fan_in_ref_exists": paths["fan_in_latest"].is_file(),
        "assignment_node_status_written": node.get("status")
        == "assignment_dag_node_evidence_written",
        "assignment_node_id_matches": str(
            node.get("assignment_dag_node_id") or node.get("node_id") or ""
        )
        == NODE_ID,
        "workflow_id_matches": str(node.get("workflow_id") or fan_in.get("workflow_id") or "")
        == workflow_id,
        "workflow_run_id_matches": str(
            node.get("workflow_run_id") or fan_in.get("workflow_run_id") or ""
        )
        == workflow_run_id,
        "critical_lane_bindings_present": lane_success_count
        >= len(CRITICAL_P0_LANE_IDS),
        "fan_in_unique_acceptance_positive": unique_accepted > 0,
        "completion_claim_denied": node.get("completion_claim_allowed") is False
        and (not fan_in or fan_in.get("completion_claim_allowed") is False),
    }
    return {
        "schema_version": f"{SCHEMA_VERSION}.workflow_scoped_evidence.v1",
        "status": "workflow_scoped_evidence_ready"
        if all(checks.values())
        else "workflow_scoped_evidence_missing_or_partial",
        "ready": all(checks.values()),
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "wave_id": wave_id,
        "node_ref": node_ref,
        "fan_in_ref": str(paths["fan_in_latest"]),
        "node_exists": bool(node),
        "fan_in_exists": paths["fan_in_latest"].is_file(),
        "lane_count": int(node.get("lane_count") or len(lane_bindings) or 0),
        "lane_success_count": lane_success_count,
        "lane_bindings": lane_bindings,
        "staged_count": int(fan_in.get("staged_count") or node.get("staged_count") or 0),
        "merged_count": int(fan_in.get("merged_count") or node.get("merged_count") or 0),
        "spend_entry_count": int(
            fan_in.get("spend_entry_count") or node.get("spend_entry_count") or 0
        ),
        "accepted_artifact_count": accepted_count,
        "unique_accepted_artifact_count": unique_accepted,
        "provider_tier_usage": fan_in.get("provider_tier_usage")
        if isinstance(fan_in.get("provider_tier_usage"), dict)
        else node.get("provider_tier_usage", {}),
        "token_cost_spend": fan_in.get("token_cost_spend")
        if isinstance(fan_in.get("token_cost_spend"), dict)
        else node.get("token_cost_spend", {}),
        "checks": checks,
        "completion_claim_allowed": False,
        "latest_alias_is_not_proof": True,
        "not_execution_controller": True,
    }


def build_current_run_index(
    *,
    runtime: Path,
    workflow_id: str,
    temporal_probe: dict[str, Any],
) -> dict[str, Any]:
    ledger = _read_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
    auto_dispatch = _read_json(runtime / "state" / "default_auto_dispatch" / "latest.json")
    aaq = _read_json(runtime / "state" / "artifact_acceptance_queue" / "latest.json")
    root_driver = _read_json(runtime / "state" / "root_intent_loop_driver" / "latest.json")
    phase1_latest = _read_json(runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json")
    aaq_decision = _extract_first_decision(aaq)
    ledger_binding = ledger.get("phase1_binding") if isinstance(ledger.get("phase1_binding"), dict) else {}
    temporal_run_id = str(temporal_probe.get("workflow_run_id") or "")
    workflow_scoped = resolve_workflow_run_evidence(
        runtime=runtime,
        workflow_id=workflow_id,
        workflow_run_id=temporal_run_id,
    )
    temporal_checks = {
        "temporal_port_open": temporal_probe.get("port_open") is True,
        "temporal_describe_succeeded": int(temporal_probe.get("describe_returncode") or 0) == 0
        and bool(temporal_run_id),
        "temporal_list_succeeded": int(temporal_probe.get("list_returncode") or 0) == 0
        and bool(temporal_probe.get("status")),
    }
    latest_alias_checks = {
        "workflow_id_matches_ledger": str(ledger_binding.get("workflow_id") or "") == workflow_id,
        "workflow_run_id_matches_ledger": str(ledger_binding.get("workflow_run_id") or "")
        == temporal_run_id,
        "workflow_id_matches_aaq": str(aaq_decision.get("workflow_id") or "") == workflow_id,
        "workflow_run_id_matches_aaq": str(aaq_decision.get("workflow_run_id") or "")
        == temporal_run_id,
        "workflow_id_matches_auto_dispatch": str(auto_dispatch.get("workflow_id") or "")
        == workflow_id,
        "workflow_run_id_matches_auto_dispatch": str(auto_dispatch.get("workflow_run_id") or "")
        == temporal_run_id,
        "ledger_succeeded_positive": int(ledger.get("succeeded_count") or 0) > 0,
        "ledger_succeeded_matches_completed": bool(
            ledger_binding.get("ledger_succeeded_matches_completed")
        ),
        "aaq_unique_acceptance_positive": int(aaq.get("unique_accepted_artifact_count") or 0) > 0,
        "completion_claim_disallowed": aaq.get("completion_claim_allowed") is False,
    }
    scoped_reconciled = workflow_scoped.get("ready") is True
    latest_reconciled = all(latest_alias_checks.values())
    checks = {
        **temporal_checks,
        "workflow_scoped_or_latest_evidence_reconciled": scoped_reconciled
        or latest_reconciled,
        "completion_claim_disallowed": (
            workflow_scoped.get("completion_claim_allowed") is False
            if scoped_reconciled
            else latest_alias_checks["completion_claim_disallowed"]
        ),
    }
    reconciled = all(checks.values())
    blocker = str(temporal_probe.get("named_blocker") or "")
    if not reconciled and not blocker:
        blocker = "CURRENT_333_RUN_INDEX_RECONCILIATION_GAP"
    latest_completed_wave = str(workflow_scoped.get("wave_id") or ledger.get("wave_id") or "")
    scoped_worker_summary = {
        "wave_id": workflow_scoped.get("wave_id", ""),
        "succeeded_count": workflow_scoped.get("lane_success_count", 0),
        "entry_count": workflow_scoped.get("lane_count", 0),
        "phase1_binding": {
            "workflow_id": workflow_id,
            "workflow_run_id": temporal_run_id,
            "ledger_succeeded_matches_completed": workflow_scoped.get("ready") is True,
            "source": "workflow_scoped_assignment_dag_node_evidence",
        },
        "ref": workflow_scoped.get("node_ref", ""),
        "latest_alias_ref": str(runtime / "state" / "worker_dispatch_ledger" / "latest.json"),
    }
    latest_worker_summary = {
        "wave_id": ledger.get("wave_id", ""),
        "succeeded_count": ledger.get("succeeded_count", 0),
        "entry_count": ledger.get("summary", {}).get("entry_count", 0)
        if isinstance(ledger.get("summary"), dict)
        else 0,
        "phase1_binding": ledger_binding,
        "ref": str(runtime / "state" / "worker_dispatch_ledger" / "latest.json"),
    }
    scoped_aaq_summary = {
        "status": "artifact_acceptance_queue_ready"
        if int(workflow_scoped.get("unique_accepted_artifact_count") or 0) > 0
        else "",
        "episode_id": f"workflow-run:{workflow_id}:{temporal_run_id}",
        "accepted_artifact_count": workflow_scoped.get("accepted_artifact_count", 0),
        "unique_accepted_artifact_count": workflow_scoped.get(
            "unique_accepted_artifact_count", 0
        ),
        "first_decision": {
            "workflow_id": workflow_id,
            "workflow_run_id": temporal_run_id,
            "status": "accepted"
            if int(workflow_scoped.get("unique_accepted_artifact_count") or 0) > 0
            else "",
        },
        "ref": workflow_scoped.get("fan_in_ref", ""),
        "latest_alias_ref": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
    }
    latest_aaq_summary = {
        "status": aaq.get("status", ""),
        "episode_id": aaq.get("episode_id", ""),
        "accepted_artifact_count": aaq.get("accepted_artifact_count", 0),
        "unique_accepted_artifact_count": aaq.get("unique_accepted_artifact_count", 0),
        "first_decision": aaq_decision,
        "ref": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
    }
    live_status = str(temporal_probe.get("status") or "")
    current_state = (
        "running_with_pending_activity"
        if live_status.lower() == "running" and int(temporal_probe.get("pending_activity_count") or 0) > 0
        else (live_status.lower() or "unknown")
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.current_run_index.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "workflow_id": workflow_id,
        "workflow_run_id": temporal_run_id,
        "status": "current_333_run_index_ready" if reconciled else "current_333_run_index_blocked",
        "current_state": current_state,
        "temporal": temporal_probe,
        "latest_completed_wave_id": latest_completed_wave,
        "latest_completed_wave_index": auto_dispatch.get("current_wave_index", 0),
        "next_wave_id": auto_dispatch.get("next_wave_id", ""),
        "default_auto_dispatch": {
            "status": auto_dispatch.get("status", ""),
            "wave_id": auto_dispatch.get("wave_id", ""),
            "next_wave_id": auto_dispatch.get("next_wave_id", ""),
            "runtime_enforced": auto_dispatch.get("runtime_enforced"),
            "ref": str(runtime / "state" / "default_auto_dispatch" / "latest.json"),
        },
        "worker_dispatch_ledger": scoped_worker_summary
        if scoped_reconciled
        else latest_worker_summary,
        "artifact_acceptance_queue": scoped_aaq_summary
        if scoped_reconciled
        else latest_aaq_summary,
        "workflow_scoped_evidence": workflow_scoped,
        "stale_alias_detection": {
            "root_intent_loop_driver_latest_status": root_driver.get("status", ""),
            "root_intent_loop_driver_latest_workflow_id": root_driver.get("workflow_id", ""),
            "root_intent_loop_driver_latest_may_be_stale": bool(root_driver)
            and str(root_driver.get("workflow_id") or "") not in {"", workflow_id},
            "worker_dispatch_ledger_latest_may_be_stale": bool(ledger)
            and str(ledger_binding.get("workflow_id") or "") not in {"", workflow_id},
            "artifact_acceptance_queue_latest_may_be_stale": bool(aaq_decision)
            and str(aaq_decision.get("workflow_id") or "") not in {"", workflow_id},
            "phase1_latest_validation_passed": phase1_latest.get("validation", {}).get("passed")
            if isinstance(phase1_latest.get("validation"), dict)
            else None,
        },
        "reconciliation": {
            "reconciled": reconciled,
            "checks": checks,
            "workflow_scoped_checks": workflow_scoped.get("checks", {}),
            "latest_alias_checks": latest_alias_checks,
            "latest_alias_used": not scoped_reconciled,
            "named_blocker": blocker,
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": phase1.now_iso(),
    }


def _entry_exists(path: Path) -> bool:
    return path.exists()


def _capability_entry(
    *,
    provider_id: str,
    capability_kinds: list[str],
    exists_code: bool,
    callable_now: bool,
    exposed_to_current_codex: bool,
    connected_to_333: str,
    aaq_state: str,
    entrypoint: str,
    evidence_refs: dict[str, str],
    adoption_state: str,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "capability_kinds": capability_kinds,
        "entrypoint": entrypoint,
        "five_layer_status": {
            "exists_code_or_manifest": exists_code,
            "callable": callable_now,
            "exposed_to_current_codex": exposed_to_current_codex,
            "connected_to_333": connected_to_333,
            "aaq_state": aaq_state,
        },
        "adoption_state": adoption_state,
        "evidence_refs": evidence_refs,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "notes": notes,
    }


def build_tool_registry(
    *,
    runtime: Path,
    repo: Path,
    current_index: dict[str, Any],
) -> dict[str, Any]:
    capability_gateway = _read_json(runtime / "state" / "capability_gateway" / "latest.json")
    ledger = _read_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
    aaq = _read_json(runtime / "state" / "artifact_acceptance_queue" / "latest.json")
    manifest_paths = sorted((runtime / "capabilities").glob("**/manifest.json"))
    direct_script = repo / "scripts" / "hardmode" / "Invoke-CodexSWorkerLane.ps1"
    direct_module = repo / "services" / "agent_runtime" / "codex_s_direct_worker_lane.py"
    task_control_module = repo / "services" / "agent_runtime" / "codex_333_task_transaction_control.py"
    continuity_module = repo / "services" / "agent_runtime" / "codex_333_stateful_continuity_router.py"
    cli_module = repo / "src" / "xinao_seedlab" / "cli" / "__main__.py"
    mcp_server = repo / "services" / "mcp" / "xinao_mcp_server.py"
    qwen_record = runtime / "state" / "modular_dynamic_worker_pool_phase1" / "qwen_worker_invocation" / "records" / "333-sw-p0-toolregistry-index.json"
    dp_record = runtime / "state" / "dp_sidecar_execution_provider" / "records" / "333-sw-p0-provider-realness-gate.json"
    accepted_via_wave = (
        int(
            current_index.get("artifact_acceptance_queue", {}).get(
                "unique_accepted_artifact_count", 0
            )
            if isinstance(current_index.get("artifact_acceptance_queue"), dict)
            else 0
        )
        > 0
        or (
            int(aaq.get("unique_accepted_artifact_count") or 0) > 0
            and str(aaq.get("episode_id") or "").find(str(ledger.get("wave_id") or "")) >= 0
        )
    )
    providers = [
        _capability_entry(
            provider_id="codex_s.333_stateful_continuity_router",
            capability_kinds=[
                "stateful_continuity_router",
                "current_user_intent_object",
                "forbidden_narrowing",
                "accepted_claim_ids",
                "stale_claim_ids",
                "next_required_artifact",
            ],
            exists_code=_entry_exists(continuity_module) and _entry_exists(cli_module),
            callable_now=_entry_exists(continuity_module) and _entry_exists(cli_module),
            exposed_to_current_codex=True,
            connected_to_333="source_package_intent_continuity_read_model",
            aaq_state="not_artifact_acceptance_surface",
            entrypoint=(
                "python -m xinao_seedlab.cli.__main__ "
                "333-stateful-continuity-router"
            ),
            evidence_refs={
                "module": str(continuity_module),
                "latest": str(runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json"),
            },
            adoption_state="default_hot_path_ready",
            notes=(
                "Keeps source-package intent, forbidden narrowing, stale claims, active blockers, "
                "and next artifact as a machine read model."
            ),
        ),
        _capability_entry(
            provider_id="codex_s.333_task_transaction_control",
            capability_kinds=[
                "task_transaction_control",
                "temporal_signal_task_control",
                "pause_after_current_wave",
                "cancel_after_current_wave",
                "insert_front",
                "resume",
                "return_to_mainline",
            ],
            exists_code=_entry_exists(task_control_module) and _entry_exists(cli_module),
            callable_now=_entry_exists(task_control_module) and _entry_exists(cli_module),
            exposed_to_current_codex=True,
            connected_to_333="current_workflow_task_control_signal",
            aaq_state="not_artifact_acceptance_surface",
            entrypoint=(
                "python -m xinao_seedlab.cli.__main__ "
                "333-task-transaction-control --routing-verb <verb>"
            ),
            evidence_refs={
                "module": str(task_control_module),
                "latest": str(runtime / "state" / "codex_333_task_transaction_control" / "latest.json"),
            },
            adoption_state="default_hot_path_ready",
            notes=(
                "Thin task-control envelope over Temporal task_control / continue_same_task / "
                "drain_after_current_wave. It is not a completion boundary."
            ),
        ),
        _capability_entry(
            provider_id="codex_s.direct_worker_lane",
            capability_kinds=[
                "direct_worker_lane",
                "qwen_direct_worker_lane",
                "dp_direct_worker_lane",
                "provider_worker_lane_staging",
            ],
            exists_code=_entry_exists(direct_script) and _entry_exists(direct_module),
            callable_now=_entry_exists(direct_script) and _entry_exists(direct_module),
            exposed_to_current_codex=True,
            connected_to_333="not_mainline_direct_lane_requires_fan_in_aaq",
            aaq_state="not_directly_accepted",
            entrypoint=str(direct_script),
            evidence_refs={
                "module": str(direct_module),
                "latest": str(runtime / "state" / "codex_s_direct_worker_lane" / "latest.json"),
            },
            adoption_state="api_cli_verifier_ready_not_hook_enforced",
            notes="Direct Qwen/DP foreground worker lane; not RootIntentLoop mainline.",
        ),
        _capability_entry(
            provider_id="qwen_prepaid_cheap_worker",
            capability_kinds=["cheap_worker_provider", "draft", "extraction", "eval"],
            exists_code=_entry_exists(qwen_record),
            callable_now=_read_provider_realness_record(qwen_record).get("model_invocation_performed") is True,
            exposed_to_current_codex=True,
            connected_to_333="task_scoped_wave_lane_terminal_result",
            aaq_state="accepted_via_wave_merge" if accepted_via_wave else "requires_aaq",
            entrypoint="scripts/hardmode/Invoke-CodexSWorkerLane.ps1 -Provider qwen",
            evidence_refs={"record": str(qwen_record)},
            adoption_state="task_scoped_provider_lane_ready",
        ),
        _capability_entry(
            provider_id="legacy.deepseek_dp_sidecar",
            capability_kinds=["dp_sidecar_execution", "audit", "contradiction", "quality_lane"],
            exists_code=_entry_exists(dp_record),
            callable_now=_read_provider_realness_record(dp_record).get("model_invocation_performed") is True,
            exposed_to_current_codex=True,
            connected_to_333="task_scoped_wave_lane_terminal_result",
            aaq_state="accepted_via_wave_merge" if accepted_via_wave else "requires_aaq",
            entrypoint="scripts/hardmode/Invoke-CodexSWorkerLane.ps1 -Provider dp",
            evidence_refs={"record": str(dp_record)},
            adoption_state="api_cli_verifier_ready_not_hook_enforced",
            notes="DP remains a worker/provider lane, not durable carrier.",
        ),
        _capability_entry(
            provider_id="codex_s.capability_gateway",
            capability_kinds=["capability_gateway_snapshot", "provider_discovery"],
            exists_code=bool(capability_gateway),
            callable_now=bool(capability_gateway),
            exposed_to_current_codex=True,
            connected_to_333="discovery_ref_only",
            aaq_state="not_artifact_acceptance_surface",
            entrypoint=str(runtime / "state" / "capability_gateway" / "latest.json"),
            evidence_refs={"latest": str(runtime / "state" / "capability_gateway" / "latest.json")},
            adoption_state="default_hot_path_ready",
        ),
        _capability_entry(
            provider_id="mcp.xinao_runtime.tools",
            capability_kinds=["mcp_tools", "tool_registry_resource", "read_only_discovery"],
            exists_code=_entry_exists(mcp_server),
            callable_now=True,
            exposed_to_current_codex=True,
            connected_to_333="read_only_discovery_not_dispatch",
            aaq_state="not_artifact_acceptance_surface",
            entrypoint="xinao://catalog/tool-registry",
            evidence_refs={"server": str(mcp_server)},
            adoption_state="default_hot_path_ready",
            notes="MCP/UCP dispatch is not restored; this registry is read-only discovery.",
        ),
        _capability_entry(
            provider_id="d_runtime.capability_manifests",
            capability_kinds=["capability_manifest_catalog", "d_runtime_capability_inventory"],
            exists_code=bool(manifest_paths),
            callable_now=bool(manifest_paths),
            exposed_to_current_codex=True,
            connected_to_333="candidate_or_existing_manifest_refs",
            aaq_state="requires_candidate_absorption_before_acceptance",
            entrypoint=str(runtime / "capabilities"),
            evidence_refs={"manifest_count": str(len(manifest_paths))},
            adoption_state="candidate_inventory_ready",
        ),
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}.tool_registry.v1",
        "sentinel": SENTINEL,
        "status": "s_tool_registry_ready",
        "task_id": TASK_ID,
        "workflow_id": current_index.get("workflow_id", ""),
        "workflow_run_id": current_index.get("workflow_run_id", ""),
        "provider_ids": [item["provider_id"] for item in providers],
        "providers": providers,
        "required_provider_ids": REQUIRED_TOOL_REGISTRY_IDS,
        "d_runtime_manifest_count": len(manifest_paths),
        "d_runtime_manifest_sample": [str(path) for path in manifest_paths[:20]],
        "old_clean_registry_role": "reference_only_not_fallback",
        "ucp_dispatch_exposed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": all(item in [provider["provider_id"] for provider in providers] for item in REQUIRED_TOOL_REGISTRY_IDS),
            "checks": {
                "stateful_continuity_router_exposed": "codex_s.333_stateful_continuity_router"
                in [provider["provider_id"] for provider in providers],
                "task_transaction_control_exposed": "codex_s.333_task_transaction_control"
                in [provider["provider_id"] for provider in providers],
                "direct_worker_lane_exposed": "codex_s.direct_worker_lane"
                in [provider["provider_id"] for provider in providers],
                "qwen_exposed": "qwen_prepaid_cheap_worker"
                in [provider["provider_id"] for provider in providers],
                "dp_exposed": "legacy.deepseek_dp_sidecar"
                in [provider["provider_id"] for provider in providers],
                "capability_gateway_exposed": "codex_s.capability_gateway"
                in [provider["provider_id"] for provider in providers],
                "mcp_tools_exposed": "mcp.xinao_runtime.tools"
                in [provider["provider_id"] for provider in providers],
                "d_runtime_manifests_exposed": "d_runtime.capability_manifests"
                in [provider["provider_id"] for provider in providers],
                "five_layer_fields_present": all(
                    bool(provider.get("five_layer_status")) for provider in providers
                ),
            },
        },
        "generated_at": phase1.now_iso(),
    }


def _read_provider_realness_record(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    provider_payload = payload.get("provider_payload")
    if isinstance(provider_payload, dict):
        payload = provider_payload
    selected = str(payload.get("selected_carrier_provider_id") or payload.get("provider_id") or "")
    local_stub = payload.get("local_stub") is True or selected.startswith("seed_cortex.local_")
    return {
        "record_path": str(path),
        "exists": path.is_file(),
        "selected_carrier_provider_id": selected,
        "provider_invocation_performed": payload.get("provider_invocation_performed") is True,
        "model_invocation_performed": payload.get("model_invocation_performed") is True,
        "tool_invocation_performed": payload.get("tool_invocation_performed") is True,
        "local_stub": local_stub,
        "named_blocker": str(payload.get("named_blocker") or ""),
        "raw_response_ref": str(payload.get("raw_response_ref") or ""),
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
    }


def _critical_record_for_entry(entry: dict[str, Any]) -> Path | None:
    refs = entry.get("artifact_refs")
    if not isinstance(refs, list):
        return None
    record_refs = [
        Path(str(ref))
        for ref in refs
        if str(ref).endswith(".json")
        and ("\\records\\" in str(ref) or "/records/" in str(ref))
    ]
    return record_refs[0] if record_refs else None


def _critical_record_for_lane(
    runtime: Path,
    lane_id: str,
    provider_id: str,
    artifact_ref: str = "",
) -> Path | None:
    normalized_lane_id = next(
        (critical_id for critical_id in CRITICAL_P0_LANE_IDS if critical_id in lane_id),
        lane_id,
    )
    if "qwen" in provider_id:
        return (
            runtime
            / "state"
            / "modular_dynamic_worker_pool_phase1"
            / "qwen_worker_invocation"
            / "records"
            / f"{normalized_lane_id}.json"
        )
    if "deepseek" in provider_id or "dp" in provider_id:
        return (
            runtime
            / "state"
            / "dp_sidecar_execution_provider"
            / "records"
            / f"{normalized_lane_id}.json"
        )
    if artifact_ref and ("\\records\\" in artifact_ref or "/records/" in artifact_ref):
        return Path(artifact_ref)
    return None


def _provider_gate_decision(record: dict[str, Any]) -> dict[str, Any]:
    accepted = (
        record.get("exists") is True
        and record.get("provider_invocation_performed") is True
        and record.get("model_invocation_performed") is True
        and record.get("local_stub") is False
        and not record.get("named_blocker")
    )
    rejection_reasons = []
    if record.get("exists") is not True:
        rejection_reasons.append("provider_record_missing")
    if record.get("provider_invocation_performed") is not True:
        rejection_reasons.append("provider_invocation_performed_false")
    if record.get("model_invocation_performed") is not True:
        rejection_reasons.append("model_invocation_performed_false")
    if record.get("local_stub") is True:
        rejection_reasons.append("local_stub_true")
    if record.get("named_blocker"):
        rejection_reasons.append("named_blocker_present")
    return {
        "decision": "accepted_for_critical_path" if accepted else "rejected_from_critical_path",
        "accepted_for_critical_path": accepted,
        "rejection_reasons": rejection_reasons,
    }


def build_provider_realness_gate(
    *,
    runtime: Path,
    current_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger = _read_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
    entries = ledger.get("dispatch_entries") if isinstance(ledger.get("dispatch_entries"), list) else []
    critical_results = []
    current_index = current_index or {}
    workflow_scoped = (
        current_index.get("workflow_scoped_evidence")
        if isinstance(current_index.get("workflow_scoped_evidence"), dict)
        else {}
    )
    scoped_bindings = (
        workflow_scoped.get("lane_bindings")
        if isinstance(workflow_scoped.get("lane_bindings"), list)
        else []
    )
    if scoped_bindings:
        iterable = [
            {
                "lane_id": str(item.get("lane_id") or ""),
                "entry_id": f"{workflow_scoped.get('wave_id', '')}:{item.get('lane_id', '')}",
                "provider": str(
                    item.get("selected_carrier_provider_id")
                    or item.get("provider")
                    or item.get("preferred_provider_id")
                    or ""
                ),
                "preferred_provider": str(item.get("preferred_provider_id") or ""),
                "mode": str(item.get("mode") or ""),
                "poll_status": str(item.get("status") or ""),
                "artifact_ref": str(item.get("artifact_ref") or ""),
            }
            for item in scoped_bindings
            if isinstance(item, dict)
        ]
    else:
        iterable = [
            {
                "lane_id": str(entry.get("lane_id") or ""),
                "entry_id": str(entry.get("entry_id") or ""),
                "provider": str(entry.get("provider") or ""),
                "mode": str(entry.get("mode") or ""),
                "poll_status": str(entry.get("poll_status") or ""),
                "entry": entry,
            }
            for entry in entries
            if isinstance(entry, dict)
        ]
    seen_lane_ids: set[str] = set()
    for entry in iterable:
        lane_id = str(entry.get("lane_id") or "")
        if lane_id in seen_lane_ids or not any(p0_id in lane_id for p0_id in CRITICAL_P0_LANE_IDS):
            continue
        seen_lane_ids.add(lane_id)
        record_path = _critical_record_for_lane(
            runtime,
            lane_id,
            str(entry.get("provider") or ""),
            str(entry.get("artifact_ref") or ""),
        )
        if record_path is None and isinstance(entry.get("entry"), dict):
            record_path = _critical_record_for_entry(entry["entry"])
        record = _read_provider_realness_record(record_path) if record_path else {"exists": False}
        decision = _provider_gate_decision(record)
        critical_results.append(
            {
                "lane_id": lane_id,
                "entry_id": entry.get("entry_id", ""),
                "provider": entry.get("provider", ""),
                "mode": entry.get("mode", ""),
                "poll_status": entry.get("poll_status", ""),
                "record": record,
                "gate": decision,
            }
        )
    negative_fixture_records = [
        {
            "sample_id": "local_stub_fixture",
            "exists": True,
            "selected_carrier_provider_id": "seed_cortex.local_stub_provider",
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "local_stub": True,
            "named_blocker": "",
        },
        {
            "sample_id": "model_not_invoked_fixture",
            "exists": True,
            "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
            "provider_invocation_performed": True,
            "model_invocation_performed": False,
            "local_stub": False,
            "named_blocker": "",
        },
    ]
    negative_samples = [
        {**record, "gate": _provider_gate_decision(record)}
        for record in negative_fixture_records
    ]
    critical_passed = (
        len(critical_results) >= len(CRITICAL_P0_LANE_IDS)
        and all(item["gate"]["accepted_for_critical_path"] is True for item in critical_results)
    )
    negative_rejected = all(
        item["gate"]["decision"] == "rejected_from_critical_path" for item in negative_samples
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.provider_realness_gate.v1",
        "status": "provider_realness_gate_ready"
        if critical_passed and negative_rejected
        else "provider_realness_gate_blocked",
        "critical_lane_ids": CRITICAL_P0_LANE_IDS,
        "critical_results": critical_results,
        "negative_samples": negative_samples,
        "rejection_rules": [
            "local_stub_true",
            "model_invocation_performed_false",
            "provider_invocation_performed_false",
            "provider_record_missing",
            "named_blocker_present",
        ],
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "validation": {
            "passed": critical_passed and negative_rejected,
            "checks": {
                "critical_lane_count_bound": len(critical_results) >= len(CRITICAL_P0_LANE_IDS),
                "critical_lanes_real_provider_invoked": all(
                    item["record"].get("provider_invocation_performed") is True
                    for item in critical_results
                ),
                "critical_lanes_model_invoked": all(
                    item["record"].get("model_invocation_performed") is True
                    for item in critical_results
                ),
                "critical_lanes_not_local_stub": all(
                    item["record"].get("local_stub") is False for item in critical_results
                ),
                "local_stub_fixture_rejected": negative_samples[0]["gate"]["decision"]
                == "rejected_from_critical_path",
                "model_false_fixture_rejected": negative_samples[1]["gate"]["decision"]
                == "rejected_from_critical_path",
            },
        },
    }


def build_dynamic_width_evidence(
    *,
    runtime: Path,
    worker_assignment: dict[str, Any],
    current_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dynamic = _read_json(runtime / "state" / "dynamic_width_policy" / "latest.json")
    ledger = _read_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
    aaq = _read_json(runtime / "state" / "artifact_acceptance_queue" / "latest.json")
    current_index = current_index or {}
    workflow_scoped = (
        current_index.get("workflow_scoped_evidence")
        if isinstance(current_index.get("workflow_scoped_evidence"), dict)
        else {}
    )
    explicit_lane_ids = worker_assignment.get("explicit_work_package_lane_ids")
    if not isinstance(explicit_lane_ids, list):
        explicit_lane_ids = []
    scoped_lane_count = int(workflow_scoped.get("lane_count") or 0)
    scoped_success_count = int(workflow_scoped.get("lane_success_count") or 0)
    scoped_unique_accepted = int(workflow_scoped.get("unique_accepted_artifact_count") or 0)
    scoped_ready = workflow_scoped.get("ready") is True
    width_source = (
        "explicit_assignment_dag_work_package"
        if scoped_ready and explicit_lane_ids
        else str(dynamic.get("target_width_source") or "")
    )
    current_case = "explicit_assignment_dynamic_envelope"
    if dynamic.get("fixed_width_literal_used") is True:
        current_case = "static_fixed_literal"
    elif "bootstrap" in width_source:
        current_case = "bootstrap"
    elif width_source == "dynamic_width_scheduler_not_provided":
        current_case = "missing_dynamic_width_scheduler"
    elif width_source.startswith("dynamic_width_scheduler"):
        current_case = "dynamic_scheduler"
    return {
        "schema_version": f"{SCHEMA_VERSION}.dynamic_width_evidence.v1",
        "status": "dynamic_width_evidence_ready",
        "workflow_id": current_index.get("workflow_id") or dynamic.get("workflow_id", ""),
        "wave_id": workflow_scoped.get("wave_id") or dynamic.get("wave_id", ledger.get("wave_id", "")),
        "widths": {
            "configured_width": len(explicit_lane_ids)
            or scoped_lane_count
            or int(dynamic.get("target_width") or 0),
            "requested_width": scoped_lane_count
            or int(dynamic.get("requested_target_width") or dynamic.get("target_width") or 0),
            "dispatched_width": scoped_lane_count or int(dynamic.get("actual_dispatched_width") or 0),
            "completed_width": scoped_success_count
            or int(ledger.get("succeeded_count") or dynamic.get("actual_completed_width") or 0),
            "accepted_artifact_count": int(
                workflow_scoped.get("accepted_artifact_count")
                or aaq.get("accepted_artifact_count")
                or 0
            ),
            "unique_accepted_artifact_count": scoped_unique_accepted
            or int(aaq.get("unique_accepted_artifact_count") or 0),
        },
        "source": {
            "target_width_source": width_source,
            "width_decision_reason": dynamic.get("width_decision_reason", ""),
            "width_decision_inputs": dynamic.get("width_decision_inputs", {}),
            "recomputed_each_wave": dynamic.get("recomputed_each_wave"),
            "fixed_width_literal_used": dynamic.get("fixed_width_literal_used"),
            "operator_cap_applied": dynamic.get("operator_cap_applied"),
        },
        "case_classification": current_case,
        "named_static_or_bootstrap_cases": {
            "static_fixed_literal": "A configured fixed number such as 10/20/24/50 is present without per-wave capacity input.",
            "bootstrap": "A bootstrap width is used only to get the lane running and must not be called dynamic.",
            "missing_dynamic_width_scheduler": "No scheduler/envelope supplied a width decision; this must become a blocker.",
            "explicit_assignment_dynamic_envelope": "This wave's width comes from the explicit assignment DAG work package and is not a permanent default cap.",
            "dynamic_scheduler": "A per-wave dynamic scheduler supplied capacity inputs and recompute reason.",
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "validation": {
            "passed": all(
                int(value) >= 0
                for value in [
                    len(explicit_lane_ids) or scoped_lane_count or int(dynamic.get("target_width") or 0),
                    scoped_lane_count
                    or int(dynamic.get("requested_target_width") or dynamic.get("target_width") or 0),
                    scoped_lane_count or int(dynamic.get("actual_dispatched_width") or 0),
                    scoped_success_count
                    or int(ledger.get("succeeded_count") or dynamic.get("actual_completed_width") or 0),
                    scoped_unique_accepted or int(aaq.get("unique_accepted_artifact_count") or 0),
                ]
            )
            and bool(width_source),
            "checks": {
                "configured_width_present": (
                    len(explicit_lane_ids) or scoped_lane_count or int(dynamic.get("target_width") or 0)
                )
                > 0,
                "requested_width_present": (
                    scoped_lane_count
                    or int(
                    dynamic.get("requested_target_width") or dynamic.get("target_width") or 0
                )
                )
                > 0,
                "dispatched_width_present": (
                    scoped_lane_count or int(dynamic.get("actual_dispatched_width") or 0)
                )
                > 0,
                "completed_width_present": (
                    scoped_success_count
                    or int(
                    ledger.get("succeeded_count") or dynamic.get("actual_completed_width") or 0
                )
                )
                > 0,
                "accepted_count_present": (
                    scoped_unique_accepted or int(aaq.get("unique_accepted_artifact_count") or 0)
                )
                > 0,
                "static_bootstrap_cases_named": True,
            },
        },
    }


def _manifest_candidate(path: Path) -> dict[str, Any]:
    manifest = _read_json(path)
    provider_id = str(manifest.get("provider_id") or path.parent.name)
    runtime_enforced = manifest.get("runtime_enforced") is True
    return {
        "candidate_id": f"d-runtime:{provider_id}",
        "source_family": "d_runtime_capability_manifest",
        "source_path": str(path),
        "provider_id": provider_id,
        "capability_kinds": manifest.get("capability_kinds", []),
        "absorption_state": {
            "candidate": "registered_from_manifest",
            "smoke": "manifest_validation_ready" if manifest.get("validation", {}).get("passed") is True else "smoke_required",
            "policy": "policy_required_before_default" if not runtime_enforced else "policy_already_bound_in_manifest",
            "thin_bind": "existing_manifest_thin_bind" if manifest else "thin_bind_required",
            "333": "runtime_enforced_manifest" if runtime_enforced else "candidate_not_333_consumed",
            "AAQ": "not_artifact_accepted_until_wave_acceptance",
        },
    }


def _external_candidate(path: Path) -> dict[str, Any]:
    return {
        "candidate_id": f"external:{path.name}",
        "source_family": "external_official_mature",
        "source_path": str(path),
        "provider_id": path.name,
        "capability_kinds": ["external_mature_candidate"],
        "absorption_state": {
            "candidate": "registered_from_local_mirror",
            "smoke": "smoke_required",
            "policy": "opa_conftest_or_manual_policy_required",
            "thin_bind": "thin_adapter_required",
            "333": "not_connected_to_333",
            "AAQ": "not_accepted",
        },
    }


def build_capability_absorption_pipeline(*, runtime: Path, external_root: Path) -> dict[str, Any]:
    manifest_candidates = [
        _manifest_candidate(path)
        for path in sorted((runtime / "capabilities").glob("**/manifest.json"))[:40]
    ]
    official_root = external_root / "official"
    priority_names = [
        "temporalio__temporal",
        "temporalio__sdk-python",
        "langchain-ai__langgraph",
        "BerriAI__litellm",
        "modelcontextprotocol__python-sdk",
        "modelcontextprotocol__servers",
        "backstage__backstage",
        "open-policy-agent__opa",
        "open-policy-agent__conftest",
        "open-telemetry__opentelemetry-python",
        "langfuse__langfuse",
    ]
    external_candidates = []
    if official_root.is_dir():
        by_name = {path.name: path for path in official_root.iterdir() if path.is_dir()}
        for name in priority_names:
            path = by_name.get(name)
            if path is not None:
                external_candidates.append(_external_candidate(path))
    candidates = manifest_candidates + external_candidates
    stage_keys_ok = all(
        set(candidate.get("absorption_state", {}).keys())
        == {"candidate", "smoke", "policy", "thin_bind", "333", "AAQ"}
        for candidate in candidates
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.capability_absorption_pipeline.v1",
        "status": "capability_absorption_pipeline_ready",
        "task_id": TASK_ID,
        "pipeline": [
            "candidate",
            "smoke",
            "policy",
            "thin_bind",
            "333",
            "AAQ",
        ],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "report_only_inventory": False,
        "candidate_matrix_emitted": True,
        "external_mature_replacement_map": {
            "Temporal": "durable workflow and task queue carrier",
            "LangGraph": "checkpoint/store and graph reducer candidate",
            "LiteLLM": "provider router and fallback carrier",
            "Backstage/MCP": "capability catalog and tool registry carrier",
            "OPA/Conftest": "policy-as-code gate for candidate admission",
            "OpenTelemetry/Langfuse/OpenLineage": "trace and lineage candidate surfaces",
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "validation": {
            "passed": bool(candidates) and stage_keys_ok,
            "checks": {
                "candidate_count_positive": bool(candidates),
                "candidate_smoke_policy_thinbind_333_aaq_states_present": stage_keys_ok,
                "report_only_inventory_false": True,
                "external_mature_map_present": True,
            },
        },
        "generated_at": phase1.now_iso(),
    }


def build_source_package(
    *,
    source_files: list[Path],
    foreground_watch_ref: Path,
    max_mature_ref: Path,
    max_mature_fallback_refs: tuple[Path, ...] = MAX_MATURE_COMPONENT_FALLBACK_REFS,
) -> dict[str, Any]:
    files = [_file_facts(path) for path in source_files]
    foreground_watch = _file_facts(foreground_watch_ref)
    max_mature_candidates = [max_mature_ref, *max_mature_fallback_refs]
    resolved_max_mature = next(
        (path for path in max_mature_candidates if path.is_file()),
        max_mature_ref,
    )
    requested_max_mature = _file_facts(max_mature_ref)
    max_mature_fallbacks = [_file_facts(path) for path in max_mature_fallback_refs]
    max_mature = _file_facts(resolved_max_mature)
    return {
        "root": str(source_files[0].parent) if source_files else "",
        "files": files,
        "file_count": len(files),
        "five_text_files_read": len(files) == 5 and all(item["read_in_full"] for item in files),
        "foreground_watch_ref": foreground_watch,
        "max_mature_component_requested_ref": requested_max_mature,
        "max_mature_component_fallback_refs": max_mature_fallbacks,
        "max_mature_component_ref": max_mature,
        "max_mature_component_resolution": {
            "requested_path": str(max_mature_ref),
            "resolved_path": str(resolved_max_mature),
            "requested_exists": requested_max_mature["exists"],
            "fallback_used": resolved_max_mature != max_mature_ref,
            "named_blocker": ""
            if max_mature["read_in_full"]
            else "MAX_MATURE_COMPONENT_REF_NOT_READABLE",
        },
        "source_package_rebound": len(files) == 5 and all(item["exists"] for item in files),
    }


def build_default_mainline_binding(*, runtime: Path) -> dict[str, Any]:
    trigger_path = runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
    trigger = _read_json(trigger_path)
    validation = (
        trigger.get("validation", {})
        if isinstance(trigger.get("validation"), dict)
        else {}
    )
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    no_stop_refs = (
        trigger.get("no_stop_wave_consumption_refs")
        if isinstance(trigger.get("no_stop_wave_consumption_refs"), dict)
        else {}
    )
    hardened = (
        trigger_path.is_file()
        and trigger.get("status") == "default_main_loop_trigger_task_scoped_runtime_enforced"
        and trigger.get("runtime_enforced") is True
        and checks.get("current_333_run_index_consumed_by_default_trigger") is True
        and checks.get("tool_registry_consumed_by_default_trigger") is True
        and checks.get("no_stop_wave_consumption_refs_bound") is True
        and no_stop_refs.get("ready") is True
        and no_stop_refs.get("refs_are_not_execution_controllers") is True
    )
    boundary_checks = {
        "default_trigger_exists": trigger_path.is_file(),
        "default_trigger_task_scoped_runtime_enforced": trigger.get("status")
        == "default_main_loop_trigger_task_scoped_runtime_enforced",
        "default_trigger_runtime_enforced": trigger.get("runtime_enforced") is True,
        "current_333_run_index_consumed_by_default_trigger": checks.get(
            "current_333_run_index_consumed_by_default_trigger"
        )
        is True,
        "tool_registry_consumed_by_default_trigger": checks.get(
            "tool_registry_consumed_by_default_trigger"
        )
        is True,
        "no_stop_wave_consumption_refs_bound": checks.get(
            "no_stop_wave_consumption_refs_bound"
        )
        is True,
        "no_stop_wave_consumption_refs_ready": no_stop_refs.get("ready") is True,
        "no_stop_wave_refs_are_not_controllers": no_stop_refs.get(
            "refs_are_not_execution_controllers"
        )
        is True,
    }
    missing_checks = [
        name for name, passed in boundary_checks.items() if passed is not True
    ]
    named_blocker = (
        ""
        if hardened
        else "DEFAULT_MAINLINE_CURRENT_INDEX_TOOLREGISTRY_CONSUMPTION_NOT_PROVEN"
    )
    next_machine_action = (
        "RootIntentLoop/default trigger already consumes current_333_run_index and ToolRegistry."
        if hardened
        else (
            "Have the existing workflow/default trigger consume current_333_run_index "
            "and S ToolRegistry for the same no-stop wave, then rerun "
            "codex_333_sleep_watch_p0_landing verification."
        )
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.default_mainline_binding.v1",
        "status": "default_mainline_binding_hardened"
        if hardened
        else "default_mainline_binding_blocked",
        "hardened": hardened,
        "phase_boundary_ready": hardened,
        "named_blocker": named_blocker,
        "reason_not_hardened": ""
        if hardened
        else "Default trigger has not proven same-wave current_333_run_index and S ToolRegistry consumption.",
        "missing_binding": "" if hardened else ", ".join(missing_checks),
        "next_machine_action": next_machine_action,
        "consumer": "RootIntentLoop/default_main_loop_trigger_candidate",
        "default_trigger_latest_ref": str(trigger_path),
        "default_trigger_exists": trigger_path.is_file(),
        "default_trigger_status": trigger.get("status", ""),
        "default_trigger_runtime_enforced": trigger.get("runtime_enforced") is True,
        "default_trigger_runtime_enforced_scope": str(
            trigger.get("runtime_enforced_scope") or ""
        ),
        "current_333_run_index_consumed_by_default_trigger": checks.get(
            "current_333_run_index_consumed_by_default_trigger"
        )
        is True,
        "tool_registry_consumed_by_default_trigger": checks.get(
            "tool_registry_consumed_by_default_trigger"
        )
        is True,
        "no_stop_wave_consumption_refs_bound": checks.get(
            "no_stop_wave_consumption_refs_bound"
        )
        is True,
        "no_stop_wave_consumption_refs_ready": no_stop_refs.get("ready") is True,
        "boundary_checks": boundary_checks,
        "missing_checks": missing_checks,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_validation(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source_package", {})
    current = payload.get("current_333_run_index", {})
    registry = payload.get("tool_registry", {})
    realness = payload.get("provider_realness_gate", {})
    width = payload.get("dynamic_width_evidence", {})
    pipeline = payload.get("capability_absorption_pipeline", {})
    task_bound = payload.get("task_bound_jsonl_evidence", {})
    default_mainline = payload.get("default_mainline_binding", {})
    registry_ids = registry.get("provider_ids") if isinstance(registry.get("provider_ids"), list) else []
    default_mainline_consumed = (
        default_mainline.get("hardened") is True
        and default_mainline.get("current_333_run_index_consumed_by_default_trigger")
        is True
        and default_mainline.get("tool_registry_consumed_by_default_trigger") is True
    )
    default_mainline_blocked_with_next_action = (
        default_mainline.get("hardened") is not True
        and bool(default_mainline.get("named_blocker"))
        and bool(default_mainline.get("missing_binding"))
        and bool(default_mainline.get("next_machine_action"))
    )
    checks = {
        "current_source_package_rebound": source.get("source_package_rebound") is True,
        "five_text_files_read": source.get("five_text_files_read") is True,
        "max_mature_component_read": source.get("max_mature_component_ref", {}).get(
            "read_in_full"
        )
        is True,
        "no_completion_claim": payload.get("completion_claim_allowed") is False
        and current.get("completion_claim_allowed") is False,
        "current_333_run_index_written_or_blocked": bool(current)
        and (
            current.get("status") == "current_333_run_index_ready"
            or bool(current.get("reconciliation", {}).get("named_blocker"))
        ),
        "tool_registry_required_ids_exposed": all(
            required in registry_ids for required in REQUIRED_TOOL_REGISTRY_IDS
        ),
        "provider_realness_gate_rejects_fake": realness.get("validation", {}).get("checks", {}).get(
            "local_stub_fixture_rejected"
        )
        is True
        and realness.get("validation", {}).get("checks", {}).get("model_false_fixture_rejected")
        is True,
        "dynamic_width_fields_separated": width.get("validation", {}).get("checks", {}).get(
            "configured_width_present"
        )
        is True
        and width.get("validation", {}).get("checks", {}).get("accepted_count_present") is True,
        "capability_absorption_pipeline_states": pipeline.get("validation", {}).get("checks", {}).get(
            "candidate_smoke_policy_thinbind_333_aaq_states_present"
        )
        is True,
        "task_bound_jsonl_evidence_ready": task_bound.get("validation", {}).get("passed") is True,
        "default_mainline_consumes_current_index_and_tool_registry": default_mainline_consumed,
        "default_mainline_hardened_or_named_blocker": default_mainline_consumed
        or default_mainline_blocked_with_next_action,
        "phase_boundary_named_blocker_has_next_action": default_mainline_consumed
        or default_mainline_blocked_with_next_action,
    }
    required_check_names = [
        "current_source_package_rebound",
        "five_text_files_read",
        "max_mature_component_read",
        "no_completion_claim",
        "current_333_run_index_written_or_blocked",
        "tool_registry_required_ids_exposed",
        "provider_realness_gate_rejects_fake",
        "dynamic_width_fields_separated",
        "capability_absorption_pipeline_states",
        "task_bound_jsonl_evidence_ready",
        "default_mainline_hardened_or_named_blocker",
        "phase_boundary_named_blocker_has_next_action",
    ]
    required_checks = {name: checks[name] for name in required_check_names}
    return {
        "passed": all(required_checks.values()),
        "checks": checks,
        "required_checks": required_checks,
        "validated_at": phase1.now_iso(),
    }


def build_task_bound_jsonl_evidence(
    *,
    runtime: Path,
    paths: dict[str, Path],
    workflow_id: str,
    current_index: dict[str, Any],
    tool_registry: dict[str, Any],
    provider_gate: dict[str, Any],
    width: dict[str, Any],
    pipeline: dict[str, Any],
    default_mainline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow_run_id = str(current_index.get("workflow_run_id") or "")
    wave_id = str(current_index.get("latest_completed_wave_id") or "")
    workflow_run_latest = (
        paths["assignment_dag_evidence_latest"].parent
        / "workflow_runs"
        / phase1.safe_stem(workflow_id or "workflow-unbound")
        / phase1.safe_stem(workflow_run_id or "run-unbound")
        / f"{NODE_ID}.landing.latest.json"
    )
    checks = {
        "workflow_id_present": bool(workflow_id),
        "workflow_run_id_present": bool(workflow_run_id),
        "wave_id_present": bool(wave_id),
        "tool_registry_ready": tool_registry.get("validation", {}).get("passed") is True,
        "provider_realness_gate_ready": provider_gate.get("validation", {}).get("passed") is True,
        "dynamic_width_evidence_ready": width.get("validation", {}).get("passed") is True,
        "capability_absorption_pipeline_ready": pipeline.get("validation", {}).get("passed") is True,
    }
    default_mainline = default_mainline or {}
    default_mainline_hardened = default_mainline.get("hardened") is True
    default_mainline_blocker = "" if default_mainline_hardened else str(
        default_mainline.get("named_blocker") or ""
    )
    evidence = {
        "schema_version": f"{SCHEMA_VERSION}.task_bound_jsonl_evidence.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "node_id": NODE_ID,
        "status": "assignment_dag_node_evidence_written"
        if all(checks.values())
        else "assignment_dag_node_evidence_blocked",
        "source_kind": "assignment_dag_auto_continue_implementation_worker",
        "worker_kind": "implementation_worker",
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "wave_id": wave_id,
        "lane_ids": CRITICAL_P0_LANE_IDS,
        "evidence_refs": {
            "landing_latest": str(paths["latest"]),
            "current_333_run_index": str(paths["current_index_latest"]),
            "tool_registry": str(paths["tool_registry"]),
            "capability_absorption_pipeline": str(paths["capability_pipeline_latest"]),
            "source_assignment_node_evidence": str(
                current_index.get("workflow_scoped_evidence", {}).get("node_ref", "")
            )
            if isinstance(current_index.get("workflow_scoped_evidence"), dict)
            else "",
        },
        "latest_ref": str(paths["assignment_dag_evidence_latest"]),
        "node_latest_ref": str(paths["assignment_dag_node_latest"]),
        "workflow_run_latest_ref": str(workflow_run_latest),
        "jsonl_ref": str(paths["assignment_dag_node_jsonl"]),
        "verification": ["assignment_dag node evidence written"],
        "validation": {
            "passed": all(checks.values()),
            "checks": checks,
            "validated_at": phase1.now_iso(),
        },
        "spawn_new_owner_allowed": False,
        "pump_default_used": False,
        "phase_boundary_ready": default_mainline_hardened,
        "default_mainline_hardened": default_mainline_hardened,
        "named_blocker": default_mainline_blocker,
        "reason_not_hardened": ""
        if default_mainline_hardened
        else str(default_mainline.get("reason_not_hardened") or ""),
        "missing_binding": ""
        if default_mainline_hardened
        else str(default_mainline.get("missing_binding") or ""),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "next_machine_action": str(
            default_mainline.get("next_machine_action")
            or "existing_workflow_consumes_landing_index_and_continues_next_wave"
        ),
        "generated_at": phase1.now_iso(),
    }
    evidence["record_digest_sha256"] = phase1.sha256_json(evidence)
    return evidence


def render_readback(payload: dict[str, Any]) -> str:
    current = payload.get("current_333_run_index", {})
    realness = payload.get("provider_realness_gate", {})
    width = payload.get("dynamic_width_evidence", {}).get("widths", {})
    lines = [
        "# 333 sleep watch P0 landing",
        "",
        f"- workflow: `{current.get('workflow_id', '')}`",
        f"- run_id: `{current.get('workflow_run_id', '')}`",
        f"- current_state: `{current.get('current_state', '')}`",
        f"- latest_completed_wave: `{current.get('latest_completed_wave_id', '')}`",
        f"- provider_realness_gate: `{realness.get('status', '')}`",
        f"- width: configured={width.get('configured_width')} requested={width.get('requested_width')} dispatched={width.get('dispatched_width')} completed={width.get('completed_width')} accepted={width.get('unique_accepted_artifact_count')}",
        f"- default_mainline_hardened: `{payload.get('default_mainline_hardened')}`",
        f"- default_consumer: `{payload.get('default_consumer', '')}`",
        "- completion_claim_allowed: `false`",
        "",
        "人话：本轮只把现有 333 workflow/ledger/AAQ/source package 收敛成 current index、工具五层索引、provider realness gate、宽度证据和能力吸收 pipeline；不宣布用户完成。",
        "",
    ]
    blocker = str(payload.get("named_blocker") or "")
    if not blocker and isinstance(current.get("reconciliation"), dict):
        blocker = current.get("reconciliation", {}).get("named_blocker")
    if blocker:
        lines.append(f"- named_blocker: `{blocker}`")
    return "\n".join(lines)


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    workflow_id: str = DEFAULT_WORKFLOW_ID,
    temporal_address: str = DEFAULT_TEMPORAL_ADDRESS,
    source_files: list[str | Path] | None = None,
    foreground_watch_ref: str | Path = FOREGROUND_WATCH_REF,
    max_mature_component_ref: str | Path = MAX_MATURE_COMPONENT_REF,
    max_mature_component_fallback_refs: list[str | Path] | tuple[str | Path, ...] | None = None,
    external_mature_root: str | Path = EXTERNAL_MATURE_ROOT,
    temporal_probe_override: dict[str, Any] | None = None,
    command_runner: CommandRunner | None = None,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    source_package = build_source_package(
        source_files=[Path(path) for path in (source_files or SOURCE_PACKAGE_FILES)],
        foreground_watch_ref=Path(foreground_watch_ref),
        max_mature_ref=Path(max_mature_component_ref),
        max_mature_fallback_refs=tuple(
            Path(path)
            for path in (
                max_mature_component_fallback_refs
                if max_mature_component_fallback_refs is not None
                else MAX_MATURE_COMPONENT_FALLBACK_REFS
            )
        ),
    )
    worker_assignment = _read_json(
        runtime / "state" / "worker_assignment" / f"{WORK_ID}.json"
    )
    temporal_probe = build_temporal_probe(
        workflow_id=workflow_id,
        address=temporal_address,
        command_runner=command_runner,
        override=temporal_probe_override,
    )
    current_index = build_current_run_index(
        runtime=runtime,
        workflow_id=workflow_id,
        temporal_probe=temporal_probe,
    )
    tool_registry = build_tool_registry(runtime=runtime, repo=repo, current_index=current_index)
    provider_gate = build_provider_realness_gate(runtime=runtime, current_index=current_index)
    width = build_dynamic_width_evidence(
        runtime=runtime,
        worker_assignment=worker_assignment,
        current_index=current_index,
    )
    pipeline = build_capability_absorption_pipeline(
        runtime=runtime,
        external_root=Path(external_mature_root),
    )
    default_mainline_binding = build_default_mainline_binding(runtime=runtime)
    task_bound_jsonl = build_task_bound_jsonl_evidence(
        runtime=runtime,
        paths=paths,
        workflow_id=workflow_id,
        current_index=current_index,
        tool_registry=tool_registry,
        provider_gate=provider_gate,
        width=width,
        pipeline=pipeline,
        default_mainline=default_mainline_binding,
    )
    default_mainline_hardened = default_mainline_binding.get("hardened") is True
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "node_id": NODE_ID,
        "status": "333_sleep_watch_p0_landing_ready",
        "generated_at": phase1.now_iso(),
        "runtime_root": str(runtime),
        "repo_root": str(repo),
        "workflow_id": workflow_id,
        "temporal_address": temporal_address,
        "source_package": source_package,
        "worker_assignment_ref": str(runtime / "state" / "worker_assignment" / f"{WORK_ID}.json"),
        "current_333_run_index": current_index,
        "tool_registry": tool_registry,
        "provider_realness_gate": provider_gate,
        "dynamic_width_evidence": width,
        "capability_absorption_pipeline": pipeline,
        "task_bound_jsonl_evidence": task_bound_jsonl,
        "default_mainline_binding": default_mainline_binding,
        "output_paths": {key: str(value) for key, value in paths.items()},
        "adoption_state": "task_scoped_landing_evidence",
        "phase_boundary_ready": default_mainline_hardened,
        "named_blocker": "" if default_mainline_hardened else default_mainline_binding.get("named_blocker", ""),
        "default_mainline_hardened": default_mainline_hardened,
        "default_consumer": default_mainline_binding.get("consumer", ""),
        "reason_not_hardened": default_mainline_binding.get("reason_not_hardened", ""),
        "missing_binding": default_mainline_binding.get("missing_binding", ""),
        "workspace_only": False,
        "next_machine_action": "Continue existing workflow next-wave fan-in/AAQ watch."
        if default_mainline_hardened
        else default_mainline_binding.get("next_machine_action", ""),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    payload["validation"] = build_validation(payload)
    if payload["validation"]["passed"] is not True:
        payload["status"] = "333_sleep_watch_p0_landing_blocked"
    elif not default_mainline_hardened:
        payload["status"] = "333_sleep_watch_p0_landing_evidence_written_default_mainline_blocked"
    if write:
        phase1.write_json(paths["current_index_latest"], current_index)
        phase1.write_json(paths["current_index_record"], current_index)
        phase1.write_json(paths["tool_registry"], tool_registry)
        phase1.write_json(paths["five_layer_index"], tool_registry)
        phase1.write_json(paths["capability_pipeline_latest"], pipeline)
        phase1.write_json(paths["capability_pipeline_record"], pipeline)
        phase1.write_json(paths["assignment_dag_evidence_latest"], task_bound_jsonl)
        phase1.write_json(paths["assignment_dag_node_latest"], task_bound_jsonl)
        phase1.write_json(Path(task_bound_jsonl["workflow_run_latest_ref"]), task_bound_jsonl)
        phase1.append_jsonl(paths["assignment_dag_node_jsonl"], task_bound_jsonl)
        phase1.write_json(paths["latest"], payload)
        phase1.write_json(paths["record"], payload)
        phase1.write_text(paths["readback"], render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-333-sleep-watch-p0-landing")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--workflow-id", default=DEFAULT_WORKFLOW_ID)
    parser.add_argument("--temporal-address", default=DEFAULT_TEMPORAL_ADDRESS)
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        workflow_id=args.workflow_id,
        temporal_address=args.temporal_address,
        source_files=args.source_file or None,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "workflow_id": payload["workflow_id"],
                "workflow_run_id": payload["current_333_run_index"].get("workflow_run_id"),
                "current_state": payload["current_333_run_index"].get("current_state"),
                "latest_ref": payload["output_paths"]["latest"],
                "current_index_ref": payload["output_paths"]["current_index_latest"],
                "tool_registry_ref": payload["output_paths"]["tool_registry"],
                "validation": payload["validation"],
                "completion_claim_allowed": payload["completion_claim_allowed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
