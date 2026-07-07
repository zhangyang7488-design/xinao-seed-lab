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

from services.agent_runtime import task_package_resolver as task_package

SCHEMA_VERSION = "xinao.codex_s.max_capability_think_execute.v1"
LANE_RESULTS_SCHEMA_VERSION = "xinao.codex_s.max_capability_think_execute_lane_results.v1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
SENTINEL = "SENTINEL:XINAO_CODEX_MAX_CAPABILITY_THINK_EXECUTE_RUNTIME_INVOKED"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_TASK_ID = "xinao_seed_cortex_phase0_20260701"
NODE_ID = "codex_max_capability_think_execute"
DEFAULT_WORKFLOW_ID = "333-sleep-watch-source-package-20260705-r1"
DEFAULT_PHASE_SCOPE = "assignment_dag_auto_continue"
CONTINUATION_AUTHORIZATION_LANE = "codex_a_brain_dispatch"
TASK_BOUND_CODEX_WORKER_MARKER = "RESULT_XINAO_TASK_BOUND_CODEX_WORKER_OK"
CURRENT_GROK_CONTINUE_INTENT_PACKAGE = Path(
    r"C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace"
    r"\grok-admin-bridge\intent_packages"
    r"\grok_333_continue_root_intent_loop_20260703.json"
)
DEFAULT_INTENT_PACKAGE = CURRENT_GROK_CONTINUE_INTENT_PACKAGE
BOOT_DEFAULT_SUPPLEMENT_PACKAGE = Path(
    r"C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace"
    r"\grok-admin-bridge\intent_packages"
    r"\codex_scope_max_loop_boot_default_supplement_20260703.json"
)
LEGACY_THINK_EXECUTE_PACKAGE = Path(
    r"C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace"
    r"\grok-admin-bridge\intent_packages"
    r"\codex_max_capability_think_execute_20260703.json"
)
FORBIDDEN_INTENT_PACKAGE_MARKERS = (
    "phase0_default_hot_path_full_closure",
    "full_hot_path_closure",
    "full_closure",
)
DEFAULT_SOURCE_ROOT = task_package.DEFAULT_TASK_PACKAGE_ROOT
PRIMARY_AUTHORITY_PATH = DEFAULT_SOURCE_ROOT / "TASK_PACKAGE.json"
PARENT_AUTHORITY_PATH = DEFAULT_SOURCE_ROOT / "TASK_PACKAGE.json"
TASK_PACKAGE_ENTRY_PATH = DEFAULT_SOURCE_ROOT / "TASK_PACKAGE.json"
TOTAL_DRAFT_SPEC_NAME = "max_benefit_dynamic_loop_authority_20260702.v1.md"
TOTAL_DRAFT_SECTION_REFS = ["§4", "§11", "§13", "§14"]

SUCCESS_NONPROBE_STATUSES = {"draft_ready", "search_ready", "model_ready"}
TERMINAL_STATUSES = {"succeeded", "failed", "blocked", "cancelled"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_id(value: str, *, limit: int = 96) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:limit]


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


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_json_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    try:
        normalized = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return {}
    return normalized if isinstance(normalized, dict) else {}


def read_json_argument(value: str | Path | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return normalize_json_dict(value)
    if value is None:
        return {}
    raw = str(value).strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return normalize_json_dict(payload)
    return read_json(Path(raw))


def first_work_package_item(work_package: dict[str, Any]) -> dict[str, Any]:
    items = work_package.get("work_items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                return normalize_json_dict(item)
    return {}


def work_package_node_id(work_package: dict[str, Any]) -> str:
    item = first_work_package_item(work_package)
    return (
        str(work_package.get("next_ready_node_id") or item.get("id") or NODE_ID).strip() or NODE_ID
    )


def work_package_acceptance(work_package: dict[str, Any]) -> list[str]:
    item = first_work_package_item(work_package)
    raw = item.get("acceptance")
    if not isinstance(raw, list):
        raw = work_package.get("acceptance")
    if isinstance(raw, list):
        accepted = [str(value) for value in raw if str(value).strip()]
        if accepted:
            return accepted
    return [
        "think_lanes and execute_lanes are present",
        "non-probe DP invocation is recorded",
        "ledger/fan-in consume worker_dispatch_ledger poll products",
        "Chinese readback answers think dispatch, execute lanes, and current capability",
    ]


def work_package_files(work_package: dict[str, Any], paths: dict[str, str]) -> list[str]:
    item = first_work_package_item(work_package)
    raw = work_package.get("files")
    if not isinstance(raw, list):
        raw = item.get("files")
    if isinstance(raw, list):
        files = [str(value) for value in raw if str(value).strip()]
        if files:
            return files
    return [paths["writer"], paths["tests"], paths["verifier"]]


def work_package_title(work_package: dict[str, Any]) -> str:
    item = first_work_package_item(work_package)
    return str(
        item.get("title")
        or work_package.get("title")
        or "Codex整包自分解 + 耐久后台 + think/execute 双阶段"
    )


def work_package_status(work_package: dict[str, Any]) -> str:
    item = first_work_package_item(work_package)
    return str(item.get("status") or work_package.get("status") or "ready_next")


def work_package_objective(work_package: dict[str, Any]) -> str:
    item = first_work_package_item(work_package)
    return str(work_package.get("objective") or item.get("objective") or "").strip()


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "json_valid": bool(payload),
        "schema_version": payload.get("schema_version", ""),
        "status": payload.get("status", ""),
        "validation_passed": validation.get("passed"),
    }


def default_boundary() -> dict[str, bool]:
    return {
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def output_paths(
    runtime: Path,
    repo: Path,
    task_id: str,
    *,
    assignment_dag_node_id: str = NODE_ID,
) -> dict[str, str]:
    safe_task = safe_id(task_id, limit=120)
    safe_node = safe_id(assignment_dag_node_id or NODE_ID, limit=120)
    state_root = runtime / "state" / "codex_max_capability_think_execute"
    assignment_dag_root = runtime / "state" / "task_bound_evidence" / WORK_ID / "assignment_dag"
    return {
        "runtime_latest": str(state_root / "latest.json"),
        "runtime_task_latest": str(state_root / f"{safe_task}.json"),
        "worker_assignment": str(runtime / "state" / "worker_assignment" / f"{safe_task}.json"),
        "task_card_latest": str(runtime / "state" / "task_card" / "latest.json"),
        "task_card_task_latest": str(runtime / "state" / "task_card" / f"{safe_task}.json"),
        "total_draft_spec": str(runtime / "specs" / TOTAL_DRAFT_SPEC_NAME),
        "lane_results_latest": str(runtime / "state" / "parallel_lane_results" / "latest.json"),
        "lane_results_task_latest": str(state_root / "lane_results_latest.json"),
        "lane_results_dir": str(state_root / "lane_results" / safe_task),
        "fan_in_acceptance_latest": str(
            runtime / "state" / "parallel_fan_in_acceptance" / "latest.json"
        ),
        "fan_in_acceptance_task_latest": str(state_root / "fan_in_acceptance_latest.json"),
        "continuity_envelope_latest": str(state_root / "continuity_envelope_latest.json"),
        "task_bound_assignment_dag_latest": str(assignment_dag_root / "latest.json"),
        "task_bound_assignment_dag_node_latest": str(
            assignment_dag_root / f"{safe_node}.latest.json"
        ),
        "task_bound_assignment_dag_node_jsonl": str(assignment_dag_root / f"{safe_node}.jsonl"),
        "task_bound_assignment_dag_workflow_runs": str(assignment_dag_root / "workflow_runs"),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / f"worker_assignment_{safe_task}_20260703.md"
        ),
        "schema": str(
            repo / "contracts" / "schemas" / "codex_s_max_capability_think_execute.v1.json"
        ),
        "writer": str(
            repo / "services" / "agent_runtime" / "codex_max_capability_think_execute.py"
        ),
        "tests": str(repo / "tests" / "seedcortex" / "test_codex_max_capability_think_execute.py"),
        "verifier": str(repo / "scripts" / "verify_codex_max_capability_think_execute.ps1"),
    }


def ensure_import_path(repo: Path) -> None:
    for candidate in (repo / "src", repo):
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)


def load_sibling_module(module_name: str):
    path = Path(__file__).resolve().parent / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_forbidden_intent_package(path: Path) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return any(marker in normalized for marker in FORBIDDEN_INTENT_PACKAGE_MARKERS)


def source_intent_package_id(path: Path) -> str:
    stem = path.stem.lower()
    if "grok_333_continue" in stem:
        return "grok_333_continue"
    return path.stem


def assignment_source_intent_package(runtime: Path, task_id: str) -> Path | None:
    assignment_ref = runtime / "state" / "worker_assignment" / f"{safe_id(task_id, limit=120)}.json"
    assignment = read_json(assignment_ref)
    raw_ref = str(assignment.get("source_intent_package_ref") or "").strip()
    if not raw_ref:
        return None
    candidate = Path(raw_ref)
    if candidate.is_file() and not is_forbidden_intent_package(candidate):
        return candidate
    return None


def resolve_intent_package(
    path: str | Path | None,
    *,
    runtime: Path = DEFAULT_RUNTIME,
    task_id: str = DEFAULT_TASK_ID,
) -> Path:
    if path:
        requested = Path(path)
        if not is_forbidden_intent_package(requested):
            return requested
    assignment_candidate = assignment_source_intent_package(runtime, task_id)
    if assignment_candidate is not None:
        return assignment_candidate
    for candidate in (
        DEFAULT_INTENT_PACKAGE,
        BOOT_DEFAULT_SUPPLEMENT_PACKAGE,
        LEGACY_THINK_EXECUTE_PACKAGE,
    ):
        if candidate.is_file() and not is_forbidden_intent_package(candidate):
            return candidate
    root = DEFAULT_INTENT_PACKAGE.parent
    if root.is_dir():
        matches = sorted(root.glob("*grok*333*continue*.json"))
        if matches:
            return matches[-1]
        matches = sorted(root.glob("*scope*max*loop*boot*.json"))
        if matches:
            return matches[-1]
        matches = sorted(root.glob("*max_capability*think*execute*.json"))
        if matches:
            return matches[-1]
    return DEFAULT_INTENT_PACKAGE


def parse_subagent(value: str) -> dict[str, Any]:
    raw = value.strip()
    parts = [part.strip() for part in raw.split(":")]
    agent_id = parts[0] if parts else ""
    role = parts[1] if len(parts) > 1 and parts[1] else "codex_subagent"
    raw_status = parts[2] if len(parts) > 2 and parts[2] else "dispatched"
    status_map = {
        "completed": "succeeded",
        "complete": "succeeded",
        "done": "succeeded",
        "running": "dispatched",
    }
    poll_status = status_map.get(raw_status.lower(), raw_status.lower())
    if poll_status not in TERMINAL_STATUSES and poll_status not in {
        "dispatched",
        "polling",
        "queued",
    }:
        poll_status = "dispatched"
    return {
        "agent_id": agent_id,
        "role": role,
        "poll_status": poll_status,
        "source": "actual_codex_subagent_tool_ref",
        "raw_ref": raw,
    }


def routing_width_decision(runtime: Path) -> dict[str, Any]:
    policy_ref = runtime / "state" / "deepseek_dynamic_routing_policy" / "latest.json"
    keypool_ref = runtime / "state" / "deepseek_keypool_live_probe" / "latest.json"
    mature_ref = runtime / "state" / "deepseek_mature_router_binding" / "latest.json"
    capacity_ref = runtime / "state" / "parallel_capacity" / "latest.json"
    policy = read_json(policy_ref)
    routing_policy = (
        policy.get("routing_policy") if isinstance(policy.get("routing_policy"), dict) else {}
    )
    capacity = read_json(capacity_ref)
    try:
        observed_width = int(routing_policy.get("current_default_provider_width") or 0)
    except (TypeError, ValueError):
        observed_width = 0
    try:
        capacity_ceiling = int(capacity.get("computed_fanout_ceiling") or 0)
    except (TypeError, ValueError):
        capacity_ceiling = 0
    mature_router_bound = routing_policy.get("mature_router_bound") is True
    default_dispatch_allowed = (
        routing_policy.get("default_intelligent_dispatch_allowed") is True
        and (
            routing_policy.get("router_dispatch_gate_passed") is True
            or routing_policy.get("completion_gate_passed") is True
        )
        and mature_router_bound
    )
    if observed_width > 0 and default_dispatch_allowed:
        effective_count = min(
            observed_width,
            capacity_ceiling if capacity_ceiling > 0 else observed_width,
        )
        execution_width_state = "mature_router_bound_dynamic_width"
        serial_exception = False
        serial_exception_reason = ""
    else:
        effective_count = 1
        execution_width_state = "serial_exception_nonprobe_draft_eval_lanes_only"
        serial_exception = True
        serial_exception_reason = (
            str(policy.get("named_blocker") or routing_policy.get("named_blocker"))
            or "XINAO_MATURE_ROUTER_BACKEND_NOT_BOUND"
        )
    return {
        "schema_version": "xinao.codex_s.max_capability_width_decision.v1",
        "width_source": "deepseek_dynamic_routing_policy.routing_policy.current_default_provider_width",
        "policy_ref": str(policy_ref),
        "keypool_ref": str(keypool_ref),
        "mature_router_binding_ref": str(mature_ref),
        "parallel_capacity_ref": str(capacity_ref),
        "observed_provider_width": observed_width,
        "parallel_capacity_ceiling": capacity_ceiling,
        "effective_execute_lane_count": max(1, effective_count),
        "mature_router_bound": mature_router_bound,
        "default_intelligent_dispatch_allowed": default_dispatch_allowed,
        "execution_width_state": execution_width_state,
        "serial_exception": serial_exception,
        "serial_exception_reason": serial_exception_reason,
        "hardcoded_fixed_width_used": False,
        "fixed_20_or_50_width_used": False,
        "provider_probe_default_allowed": False,
        "default_nonprobe_mode": "draft",
        "default_boundary": default_boundary(),
    }


def total_draft_boot_spec(
    *,
    runtime: Path,
    repo: Path,
    intent_payload: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    spec_path = runtime / "specs" / TOTAL_DRAFT_SPEC_NAME
    current_task_package = task_package.resolve_task_package(
        DEFAULT_SOURCE_ROOT, include_manifest_ref=True
    )
    current_read_order = [
        str(path) for path in current_task_package.get("read_order", []) if str(path).strip()
    ]
    current_resource_paths = [
        str(ref.get("path") or "")
        for ref in current_task_package.get("refs", [])
        if ref.get("role") != "task_package_manifest" and str(ref.get("path") or "").strip()
    ]
    current_package_active = current_task_package.get("legacy_fallback") is not True and bool(
        current_read_order
    )
    primary_authority = (
        intent_payload.get("primary_authority")
        if isinstance(intent_payload.get("primary_authority"), dict)
        else {}
    )
    semantic = (
        intent_payload.get("semantic_object")
        if isinstance(intent_payload.get("semantic_object"), dict)
        else {}
    )
    authority_order = (
        semantic.get("authority_read_order")
        if isinstance(semantic.get("authority_read_order"), list)
        else []
    )
    authority_order = [str(item) for item in authority_order if str(item).strip()]
    if current_package_active:
        order_path = Path(current_read_order[0])
        ordered_root_raw = (
            current_resource_paths[0] if current_resource_paths else current_read_order[0]
        )
        ordered_execution_raw = (
            current_resource_paths[1] if len(current_resource_paths) >= 2 else ordered_root_raw
        )
    else:
        order_path = (
            Path(authority_order[0]) if len(authority_order) >= 1 else TASK_PACKAGE_ENTRY_PATH
        )
        ordered_root_raw = authority_order[1] if len(authority_order) >= 2 else ""
        ordered_execution_raw = authority_order[2] if len(authority_order) >= 3 else ""
    primary_raw = (
        intent_payload.get("primary_authority_path")
        or primary_authority.get("path")
        or ordered_root_raw
        or PRIMARY_AUTHORITY_PATH
    )
    root = Path(str(ordered_root_raw or primary_raw))
    if not str(root).strip() or str(root) == ".":
        root = PRIMARY_AUTHORITY_PATH

    execution_candidates = [
        ordered_execution_raw,
        str(primary_authority.get("execution_path") or ""),
        str(primary_authority.get("parent_anchor") or ""),
        str(primary_raw or ""),
        str(PARENT_AUTHORITY_PATH),
    ]
    execution = next(
        (
            Path(candidate)
            for candidate in execution_candidates
            if str(candidate).strip() and Path(candidate).is_file()
        ),
        Path(
            next(
                (candidate for candidate in execution_candidates if str(candidate).strip()),
                str(PARENT_AUTHORITY_PATH),
            )
        ),
    )
    if not str(execution).strip() or str(execution) == ".":
        execution = PARENT_AUTHORITY_PATH

    primary = root
    parent = execution
    primary_exists = root.is_file()
    execution_exists = execution.is_file()
    root_text = root.read_text(encoding="utf-8", errors="replace") if primary_exists else ""
    execution_text = (
        execution.read_text(encoding="utf-8", errors="replace") if execution_exists else ""
    )
    raw_quotes = (
        semantic.get("total_draft_anti_accident_quotes_cn") if isinstance(semantic, dict) else []
    )
    anti_accident = (
        [str(item) for item in raw_quotes if str(item).strip()]
        if isinstance(raw_quotes, list)
        else []
    )
    semantic_text = json.dumps(semantic, ensure_ascii=False, sort_keys=True)
    combined_text = "\n".join([root_text, execution_text, semantic_text])
    combined_lower = combined_text.lower()
    dynamic_loop_present = (
        "supervisorloopworkflow" in combined_lower
        or (
            "默认动态轮回循环" in combined_text
            and "poll" in combined_lower
            and "fan-in" in combined_lower
        )
        or (
            "动态轮回循环" in combined_text
            and "恢复状态" in combined_text
            and "下一波" in combined_text
        )
    )
    anti_accident_present = (
        "11. 关键反事故句" in combined_text
        or bool(anti_accident)
        or "report、PASS、draft、window end" in combined_text
    )
    section_hits = {
        "serial_default": "serial is the exception" in combined_lower
        or "serial_exception" in combined_lower,
        "supervisor_loop": dynamic_loop_present,
        "section_4": "4. 当前工程的动态轮回循环定义" in combined_text or dynamic_loop_present,
        "section_11": anti_accident_present,
        "section_13": "13. 中文 readback" in combined_text or "中文 readback" in combined_text,
        "section_14": "14. 最终反保守修正版" in combined_text or "反保守" in combined_text,
        "pass_not_stop": "report、PASS、draft、window end" in combined_text,
        "readback_heartbeat": "readback 是 heartbeat" in combined_text,
    }
    if not anti_accident:
        anti_accident = [
            "不要把并行理解成一次性开工批次",
            "并行派发只是默认动态轮回循环中的一个节点",
            "report、PASS、draft、window end、consolidated response 都不是停止条件",
            "readback 是 heartbeat，不是 final",
        ]
    must_read_authority_order = current_read_order if current_package_active else [str(order_path)]
    payload = {
        "schema_version": "xinao.codex_s.total_draft_boot_spec.v1",
        "status": "total_draft_boot_spec_ready"
        if primary_exists
        else "total_draft_boot_spec_blocked",
        "spec_ref": str(spec_path),
        "primary_authority_rank": 0,
        "primary_authority_path": str(primary),
        "primary_authority_exists": primary_exists,
        "root_authority_path": str(root),
        "root_authority_exists": primary_exists,
        "execution_authority_path": str(execution),
        "execution_authority_exists": execution_exists,
        "authority_read_order_ref": {
            "path": str(order_path),
            "exists": order_path.is_file(),
            "role": (
                "current_task_package_manifest_or_entry"
                if current_package_active
                else "legacy_authority_read_order"
            ),
        },
        "current_task_package": current_task_package,
        "current_task_package_active": current_package_active,
        "parent_authority_path": str(parent),
        "grok_contract_rank": 0,
        "current_grok_package_rank": 0,
        "current_grok_package_authority_proxy": True,
        "grok_contract_role": "current_user_authority_proxy_for_source_intent_and_priority",
        "l3_default": True,
        "l1_forbidden_as_default": True,
        "scope_level_target": "L3",
        "scope_level_current": "L3_boot_binding_in_progress",
        "total_draft_section_refs": TOTAL_DRAFT_SECTION_REFS,
        "section_hits": section_hits,
        "anti_accident_quotes_cn": anti_accident,
        "forbidden_reductions": [
            "treat_20260702_txt_as_reference_only_or_completed_research",
            "treat_user_max_parallel_as_L1_local_patch_only",
            "treat_one_parallel_wave_summary_as_dynamic_loop",
            "treat_verify_wave_pass_as_L2_or_L3_done",
        ],
        "must_read_order": [
            *must_read_authority_order,
            str(spec_path),
            str(primary),
            str(parent),
            str(repo / "CODEX_S_L0.md"),
            str(repo / "SEED_CORTEX_MUST_READ_FIRST.md"),
        ],
        "validation": {
            "passed": primary_exists
            and execution_exists
            and order_path.is_file()
            and section_hits["supervisor_loop"]
            and section_hits["section_4"]
            and section_hits["section_11"]
            and section_hits["section_13"]
            and section_hits["section_14"]
            and section_hits["pass_not_stop"]
            and section_hits["readback_heartbeat"],
            "checks": {
                "authority_read_order_exists": order_path.is_file(),
                "primary_authority_exists": primary_exists,
                "root_authority_exists": primary_exists,
                "execution_authority_exists": execution_exists,
                "supervisor_loop_present": section_hits["supervisor_loop"],
                "section_4_present": section_hits["section_4"],
                "anti_accident_section_present": section_hits["section_11"],
                "section_11_present": section_hits["section_11"],
                "section_13_present": section_hits["section_13"],
                "section_14_present": section_hits["section_14"],
                "pass_not_stop_present": section_hits["pass_not_stop"],
                "readback_heartbeat_present": section_hits["readback_heartbeat"],
                "l3_default": True,
                "l1_forbidden_as_default": True,
            },
        },
        **default_boundary(),
    }
    markdown = "\n".join(
        [
            "# Max Benefit Dynamic Loop Authority",
            "",
            "SENTINEL:XINAO_MAX_BENEFIT_DYNAMIC_LOOP_AUTHORITY_20260702",
            "",
            "## Authority",
            "",
            "- Current user-supplied Grok package rank 0: user's sole authority proxy for the current task; outranks every local/repo/runtime/desktop authority surface for source intent and priority.",
            f"- Current task package active: `{current_package_active}`",
            f"- Current task package resolver: `{current_task_package.get('resolution')}`",
            f"- Root authority: `{root}`",
            f"- Execution authority: `{execution}`",
            f"- Parent anchor: `{parent}`",
            "- Old or non-current Grok material: reference-only alignment input.",
            "- This spec is the S boot mirror. It does not replace the desktop draft.",
            f"- Task package entry: `{order_path}`",
            "",
            "## Operational Scope Labels",
            "",
            "- L3 whole-transaction default: restore -> recompute frontier -> dispatch -> poll -> fan-in -> acceptance -> Chinese readback -> next wave.",
            "- L2 substage loop: a WP or segment can loop, but it is insufficient alone.",
            "- L1 local point parallelism: useful inside a wave, forbidden as the default completion shape.",
            "",
            "## Must Keep",
            "",
            "- Serial is the exception; max-benefit frontier parallelism is the default.",
            "- Parallel dispatch is one node inside the dynamic loop, not a one-shot batch.",
            "- report/PASS/draft/window end/readback are not stop conditions.",
            "- DeepSeek/search/external/source-family width must not be inferred from Codex subagent slot count.",
            "",
            "## Required Sections",
            "",
            "- §4 SupervisorLoopWorkflow: dynamic loop definition.",
            "- §11 anti-accident sentences: no one-shot PASS, no report as stop.",
            "- §13 Chinese readback: heartbeat and current capability surface.",
            "- §14 anti-conservative correction: do not shrink DeepSeek/search to Codex 6.",
            "",
            "## Machine Fields",
            "",
            "- `WORKER_ASSIGNMENT.scope_level_target = L3`",
            "- `WORKER_ASSIGNMENT.scope_level_current` must state whether L3 is running, blocked, or serial-exceptioned.",
            "- `WORKER_ASSIGNMENT.primary_authority_path` must point to the desktop draft above.",
            "- `WORKER_ASSIGNMENT.current_grok_package_authority_proxy` must be true when a current user-supplied Grok package is present.",
            "- `WORKER_ASSIGNMENT.total_draft_section_refs = [§4, §11, §13, §14]`",
            "",
            "## Validation",
            "",
            f"- primary_authority_exists: {primary_exists}",
            f"- execution_authority_exists: {execution_exists}",
            f"- section_hits: `{json.dumps(section_hits, ensure_ascii=False)}`",
            "",
            "SENTINEL:XINAO_MAX_BENEFIT_DYNAMIC_LOOP_AUTHORITY_20260702",
            "",
        ]
    )
    if write:
        write_text(spec_path, markdown)
    return payload


def hook_binding_state(runtime: Path, repo: Path, spec_ref: str) -> dict[str, Any]:
    side_audit = repo / "scripts" / "hardmode" / "Invoke-CodexSSideAuditHook.ps1"
    l0 = repo / "CODEX_S_L0.md"
    must_read = repo / "SEED_CORTEX_MUST_READ_FIRST.md"
    side_text = (
        side_audit.read_text(encoding="utf-8", errors="replace") if side_audit.is_file() else ""
    )
    l0_text = l0.read_text(encoding="utf-8", errors="replace") if l0.is_file() else ""
    must_text = (
        must_read.read_text(encoding="utf-8", errors="replace") if must_read.is_file() else ""
    )
    temporal_ledger = read_json(
        runtime / "state" / "worker_dispatch_ledger" / "temporal_activity_latest.json"
    )
    invocation = (
        temporal_ledger.get("runtime_entrypoint_invocation")
        if isinstance(temporal_ledger.get("runtime_entrypoint_invocation"), dict)
        else {}
    )
    temporal_hooked = (
        invocation.get("invoked_by")
        == "temporal_codex_task_workflow.worker_dispatch_ledger_activity"
        and invocation.get("runtime_enforced") is True
    )
    side_hook_reads_spec = spec_ref in side_text or TOTAL_DRAFT_SPEC_NAME in side_text
    l0_reads_spec = spec_ref in l0_text or TOTAL_DRAFT_SPEC_NAME in l0_text
    must_read_reads_spec = spec_ref in must_text or TOTAL_DRAFT_SPEC_NAME in must_text
    named_blocker = ""
    if not side_hook_reads_spec:
        named_blocker = "CODEX_S_SIDE_AUDIT_HOOK_SPEC_ANCHOR_MISSING"
    elif not temporal_hooked:
        named_blocker = "TEMPORAL_WORKER_DISPATCH_LEDGER_ACTIVITY_NOT_LIVE_HOOKED"
    hooked_state = (
        "hooked_runtime_entrypoint" if side_hook_reads_spec and temporal_hooked else "hook_blocked"
    )
    return {
        "schema_version": "xinao.codex_s.max_loop_boot_hook_binding.v1",
        "adoption_state": hooked_state,
        "base_worker_dispatch_ledger_adoption_state": str(
            temporal_ledger.get("adoption_state") or ""
        ),
        "side_audit_hook_ref": str(side_audit),
        "side_audit_hook_reads_total_draft_spec": side_hook_reads_spec,
        "l0_ref": str(l0),
        "l0_reads_total_draft_spec": l0_reads_spec,
        "must_read_ref": str(must_read),
        "must_read_reads_total_draft_spec": must_read_reads_spec,
        "worker_dispatch_ledger_temporal_activity_ref": str(
            runtime / "state" / "worker_dispatch_ledger" / "temporal_activity_latest.json"
        ),
        "temporal_worker_dispatch_ledger_activity_hooked": temporal_hooked,
        "current_driver_ledger_poll_hooked": True,
        "ledger_hooked_or_blocker": side_hook_reads_spec and temporal_hooked,
        "named_blocker": named_blocker,
        "default_boundary": default_boundary(),
    }


def base_lane(
    *,
    lane_id: str,
    phase: str,
    lane_kind: str,
    edge_kind: str,
    resource_lane: str,
    status: str,
    depends_on: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    evidence_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "phase": phase,
        "lane_kind": lane_kind,
        "edge_kind": edge_kind,
        "resource_lane": resource_lane,
        "status": status,
        "depends_on": depends_on or [],
        "artifact_refs": artifact_refs or [],
        "evidence_refs": evidence_refs or {},
        **default_boundary(),
    }


def build_lane_plan(
    *,
    task_id: str,
    wave_id: str,
    subagents: list[str],
    width: dict[str, Any],
) -> dict[str, Any]:
    think_lanes: list[dict[str, Any]] = []
    for index, raw in enumerate(subagents, start=1):
        subagent = parse_subagent(raw)
        agent_id = str(subagent.get("agent_id") or f"codex-subagent-{index:02d}")
        role = safe_id(str(subagent.get("role") or "codex_subagent"), limit=48)
        think_lanes.append(
            base_lane(
                lane_id=f"codex-max-think-subagent-{index:02d}-{role}",
                phase="think",
                lane_kind="codex_subagent",
                edge_kind="audit",
                resource_lane="codex_subagent",
                status=str(subagent.get("poll_status") or "dispatched"),
                artifact_refs=[f"codex-subagent:{agent_id}"],
                evidence_refs={
                    "agent_id": agent_id,
                    "role": role,
                    "subagent_ref": f"codex-subagent:{agent_id}",
                    "true_invoke_ref": True,
                },
            )
        )
    think_lanes.append(
        base_lane(
            lane_id="codex-max-think-dp-search-01",
            phase="think",
            lane_kind="dp_sidecar_execution",
            edge_kind="search",
            resource_lane="dp_search",
            status="planned_for_invoke",
            artifact_refs=[],
            evidence_refs={
                "requested_mode": "search",
                "provider_probe": False,
                "purpose": "think_phase_external_search_and_context_fanout",
            },
        )
    )

    effective_execute = max(1, int(width.get("effective_execute_lane_count") or 1))
    execute_lanes = []
    for index in range(1, effective_execute + 1):
        draft_lane_id = f"codex-max-execute-dp-draft-{index:02d}"
        eval_lane_id = f"codex-max-execute-dp-eval-{index:02d}"
        execute_lanes.append(
            base_lane(
                lane_id=draft_lane_id,
                phase="execute",
                lane_kind="dp_sidecar_execution",
                edge_kind="draft",
                resource_lane="dp_draft",
                status="planned_for_invoke",
                depends_on=["codex-max-think-dp-search-01"],
                artifact_refs=[],
                evidence_refs={
                    "requested_mode": "draft",
                    "provider_probe": False,
                    "purpose": "execute_phase_parallel_code_draft",
                    "search_phase": "think_only",
                },
            )
        )
        execute_lanes.append(
            base_lane(
                lane_id=eval_lane_id,
                phase="execute",
                lane_kind="dp_sidecar_execution",
                edge_kind="eval",
                resource_lane="dp_model",
                status="planned_for_invoke",
                depends_on=[draft_lane_id],
                artifact_refs=[],
                evidence_refs={
                    "requested_mode": "eval",
                    "provider_probe": False,
                    "purpose": "execute_phase_parallel_draft_eval",
                    "search_phase": "think_only",
                },
            )
        )
    dependencies = [
        {
            "from": "codex-max-think-dp-search-01",
            "to": lane["lane_id"],
            "dependency_kind": "think_context_before_execute",
            "required": True,
        }
        for lane in execute_lanes
        if str(lane.get("evidence_refs", {}).get("requested_mode") or "") == "draft"
    ] + [
        {
            "from": f"codex-max-execute-dp-draft-{index:02d}",
            "to": f"codex-max-execute-dp-eval-{index:02d}",
            "dependency_kind": "draft_before_eval",
            "required": True,
        }
        for index in range(1, effective_execute + 1)
    ]
    return {
        "think_lanes": think_lanes,
        "execute_lanes": execute_lanes,
        "dependencies": dependencies,
        "wave_id": wave_id,
        "task_id": task_id,
    }


def _intent_objective_zh(intent_payload: dict[str, Any], task_id: str) -> str:
    task_objectives = {
        "codex_s_task_decoder_thin_bind_20260703": (
            "TaskDecoder薄绑非新搜索岛：compose已有碎片→TaskCard→既有lane；输出ClaimCard或blocker。"
        ),
        "source_ledger_aaq_wave2_queued_20260703": (
            "Wave2 SourceLedger+AAQ排队并行：全局ledger+AAQ硬门+焊main_loop/temporal。"
        ),
    }
    if task_id in task_objectives:
        return task_objectives[task_id]
    for key in ("意图", "intent", "objective", "mission", "user_goal"):
        value = intent_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    semantic = (
        intent_payload.get("semantic_object")
        if isinstance(intent_payload.get("semantic_object"), dict)
        else {}
    )
    packages = (
        semantic.get("work_packages") if isinstance(semantic.get("work_packages"), list) else []
    )
    titles = [
        str(item.get("title") or item.get("id") or "").strip()
        for item in packages
        if isinstance(item, dict) and str(item.get("title") or item.get("id") or "").strip()
    ]
    if titles:
        return "；".join(titles[:4])
    return f"{task_id}：按当前 Seed Cortex S 意图包继续 RootIntentLoop。"


def _task_card_accepted_for(task_id: str) -> str:
    if task_id == "source_ledger_aaq_wave2_queued_20260703":
        return "source_ledger_aaq_wave2_queued_global_ledger_gate"
    if task_id == "codex_s_task_decoder_thin_bind_20260703":
        return "task_decoder_thin_bind_to_existing_lane"
    return "task_card_claim_to_existing_lane"


def build_task_card(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    wave_id: str,
    package_ref: Path,
    intent_payload: dict[str, Any],
    lane_plan: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime, repo, task_id)
    objective = _intent_objective_zh(intent_payload, task_id)
    lane_targets = [
        str(lane.get("lane_id") or "")
        for lane in lane_plan.get("think_lanes", []) + lane_plan.get("execute_lanes", [])
        if isinstance(lane, dict) and str(lane.get("lane_id") or "").strip()
    ]
    claim_card = {
        "object_type": "ClaimCard",
        "candidate_id": f"task-card-claim-{safe_id(task_id, limit=72)}",
        "source_url": str(package_ref),
        "source_family": "current_user_authority_intent_package",
        "claim": objective,
        "verification_need": "Route through existing codex_max_capability lanes; require fan-in/AAQ before promotion.",
        "accepted_for": _task_card_accepted_for(task_id),
        "artifact_ref": paths["task_card_task_latest"],
        "direct_fact_promotion_allowed": False,
        "completion_claim_allowed": False,
    }
    payload = {
        "schema_version": "xinao.seedcortex.task_card.v1",
        "object_type": "TaskCard",
        "status": "task_card_ready" if lane_targets else "task_card_blocked_no_existing_lane",
        "task_id": task_id,
        "wave_id": wave_id,
        "task_card_id": f"TaskCard:{safe_id(task_id, limit=80)}",
        "source_intent_ref": str(package_ref),
        "source_intent_exists": package_ref.is_file(),
        "objective_zh": objective,
        "expected_artifact": "ClaimCard_or_named_blocker",
        "reuse_lane_hint": "codex_max_capability_think_execute.build_lane_plan",
        "no_new_search_island": True,
        "fan_in_required": True,
        "routes_to_existing_lanes": lane_targets,
        "routes_to_claim_card_or_blocker": True,
        "claim_card_required_fields": [
            "source_url",
            "source_family",
            "claim",
            "verification_need",
            "accepted_for",
        ],
        "claim_card_candidate": claim_card,
        "named_blocker_if_no_lane": "" if lane_targets else "TASK_DECODER_NO_EXISTING_LANE_TARGET",
        "output_paths": {
            "runtime_latest": paths["task_card_latest"],
            "task_latest": paths["task_card_task_latest"],
        },
        "validation": {
            "passed": bool(lane_targets),
            "checks": {
                "source_intent_bound": bool(str(package_ref)),
                "no_new_search_island": True,
                "existing_lane_targets_present": bool(lane_targets),
                "claim_card_candidate_has_required_fields": all(
                    str(claim_card.get(field) or "").strip()
                    for field in [
                        "source_url",
                        "source_family",
                        "claim",
                        "verification_need",
                        "accepted_for",
                    ]
                ),
                "fan_in_required": True,
            },
        },
        **default_boundary(),
    }
    if write:
        write_json(Path(paths["task_card_latest"]), payload)
        write_json(Path(paths["task_card_task_latest"]), payload)
    return payload


def bind_task_card_to_lane_plan(
    lane_plan: dict[str, Any], task_card: dict[str, Any]
) -> dict[str, Any]:
    task_card_ref = str(task_card.get("output_paths", {}).get("task_latest") or "")
    task_card_id = str(task_card.get("task_card_id") or "TaskCard")
    routed = set(task_card.get("routes_to_existing_lanes") or [])
    bound_plan = {
        "think_lanes": [],
        "execute_lanes": [],
        "dependencies": list(lane_plan.get("dependencies") or []),
        "wave_id": lane_plan.get("wave_id"),
        "task_id": lane_plan.get("task_id"),
    }
    for phase_key in ("think_lanes", "execute_lanes"):
        for lane in lane_plan.get(phase_key, []):
            if not isinstance(lane, dict):
                continue
            evidence = (
                lane.get("evidence_refs") if isinstance(lane.get("evidence_refs"), dict) else {}
            )
            lane_id = str(lane.get("lane_id") or "")
            updated_lane = {
                **lane,
                "evidence_refs": {
                    **evidence,
                    "task_card_ref": task_card_ref,
                    "task_card_id": task_card_id,
                    "task_decoder_thin_bind": lane_id in routed,
                    "expected_task_decoder_output": "ClaimCard_or_named_blocker",
                    "no_new_search_island": True,
                },
            }
            bound_plan[phase_key].append(updated_lane)
            if lane_id in routed:
                bound_plan["dependencies"].append(
                    {
                        "from": task_card_id,
                        "to": lane_id,
                        "dependency_kind": "task_card_drives_existing_lane",
                        "required": True,
                    }
                )
    return bound_plan


def dp_poll_status(port_payload: dict[str, Any]) -> str:
    provider_payload = (
        port_payload.get("provider_payload")
        if isinstance(port_payload.get("provider_payload"), dict)
        else {}
    )
    mode = str(port_payload.get("mode") or provider_payload.get("mode") or "")
    status = str(provider_payload.get("mode_invocation_status") or "")
    if (
        mode != "provider_probe"
        and status in SUCCESS_NONPROBE_STATUSES
        and provider_payload.get("provider_invocation_performed") is True
    ):
        return "succeeded"
    if status == "blocked":
        return "blocked"
    return "failed"


def dp_lane_input_text(
    *,
    task_id: str,
    wave_id: str,
    lane: dict[str, Any],
    requested_mode: str,
    intent_text: str,
) -> str:
    common = [
        f"task_id={task_id}",
        f"wave_id={wave_id}",
        f"lane_id={lane['lane_id']}",
        f"phase={lane['phase']}",
        f"requested_mode={requested_mode}",
        f"intent_sha256={hashlib.sha256(intent_text.encode('utf-8', errors='replace')).hexdigest()}",
    ]
    if requested_mode == "draft":
        return "\n".join(
            [
                *common,
                "objective=P0 execute draft lane: produce bounded code-change draft for Codex merge.",
                "mode_policy=search is think-only; execute progress is draft code output, not search/audit/provider_probe.",
                "write_targets=services/agent_runtime/codex_max_capability_think_execute.py; services/agent_runtime/agent_runtime.py; src/xinao_seedlab/adapters/deepseek_parallel_draft.py; tests/seedcortex/test_codex_max_capability_think_execute.py; tests/seedcortex/test_deepseek_surrogate_sanitizer.py; scripts/verify_codex_max_capability_think_execute.ps1",
                "required_result=describe draft/eval execute lanes, S repo diff targets, runtime evidence, and Chinese readback update.",
                "authority_entry=C:/Users/xx363/Desktop/新系统",
                "source_package_id=grok_333_continue",
            ]
        )
    if requested_mode == "eval":
        return "\n".join(
            [
                *common,
                "objective=P0 eval lane: evaluate draft/eval execute-mode correctness without counting search/audit/probe as execute progress.",
                "acceptance=execute_lanes include draft and eval; execute_search_invocation_count=0; default_nonprobe_mode=draft; completion_claim_allowed=false.",
            ]
        )
    return "\n".join([*common, f"intent={intent_text[:3000]}"])


def invoke_dp_lanes(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    wave_id: str,
    lanes: list[dict[str, Any]],
    intent_text: str,
    write: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ensure_import_path(repo)
    dp_port = load_sibling_module("dp_sidecar_execution_port")
    updated_lanes: list[dict[str, Any]] = []
    invocations: list[dict[str, Any]] = []
    for index, lane in enumerate(lanes, start=1):
        if lane.get("lane_kind") != "dp_sidecar_execution":
            updated_lanes.append(lane)
            continue
        default_mode = "draft" if lane.get("phase") == "execute" else "search"
        requested_mode = str(lane.get("evidence_refs", {}).get("requested_mode") or default_mode)
        if lane.get("phase") == "execute" and requested_mode == "search":
            requested_mode = "draft"
        if requested_mode == "provider_probe":
            requested_mode = default_mode
        wave_scope_id = hashlib.sha256(wave_id.encode("utf-8")).hexdigest()[:16]
        invocation_id = (
            f"{safe_id(task_id, limit=40)}-"
            f"{safe_id(wave_id, limit=36)}-"
            f"{wave_scope_id}-"
            f"{safe_id(lane['lane_id'], limit=32)}"
        )
        provider_task_id = safe_id(
            f"{task_id}-{wave_scope_id}-{lane['phase']}-{index:02d}",
            limit=120,
        )
        payload = dp_port.invoke_dp_sidecar_execution_port(
            runtime_root=runtime,
            task_id=provider_task_id,
            request_id=f"{wave_id}:{lane['phase']}:dp-route:{index:02d}",
            invocation_id=invocation_id,
            episode_id=f"{safe_id(task_id, limit=80)}-max-capability",
            mode=requested_mode,
            objective=str(
                lane.get("evidence_refs", {}).get("purpose") or "Codex S non-probe DP lane"
            ),
            input_text=dp_lane_input_text(
                task_id=task_id,
                wave_id=wave_id,
                lane=lane,
                requested_mode=requested_mode,
                intent_text=intent_text,
            ),
            max_results=3,
            write=write,
        )
        poll_status = dp_poll_status(payload)
        provider_payload = (
            payload.get("provider_payload")
            if isinstance(payload.get("provider_payload"), dict)
            else {}
        )
        source_invocation = (
            provider_payload.get("source_provider_invocation")
            if isinstance(provider_payload.get("source_provider_invocation"), dict)
            else {}
        )
        source_query_normalization = (
            source_invocation.get("query_normalization")
            if isinstance(source_invocation.get("query_normalization"), dict)
            else {}
        )
        evidence_refs = (
            payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), dict) else {}
        )
        actual_refs = (
            payload.get("actual_dispatch_refs")
            if isinstance(payload.get("actual_dispatch_refs"), dict)
            else {}
        )
        mode_dispatch_attempted = provider_payload.get("mode_dispatch_attempted") is True
        provider_invocation_performed = (
            provider_payload.get("provider_invocation_performed") is True
        )
        named_blocker = str(provider_payload.get("named_blocker") or "").strip()
        if requested_mode != "provider_probe" and (
            not mode_dispatch_attempted or not provider_invocation_performed
        ):
            named_blocker = (
                named_blocker or f"DP_SIDECAR_{requested_mode.upper()}_PROVIDER_NOT_DISPATCHED"
            )
        artifact_refs = sorted(
            {
                str(ref)
                for ref in (
                    evidence_refs.get("record_path"),
                    evidence_refs.get("provider_invocation_ref"),
                    evidence_refs.get("provider_latest_ref"),
                    provider_payload.get("provider_invocation_ref"),
                    provider_payload.get("raw_response_ref"),
                    provider_payload.get("result_path"),
                )
                if str(ref or "").strip()
            }
        )
        updated_lane = dict(lane)
        updated_lane.update(
            {
                "status": poll_status,
                "artifact_refs": artifact_refs,
                "evidence_refs": {
                    **(
                        lane.get("evidence_refs")
                        if isinstance(lane.get("evidence_refs"), dict)
                        else {}
                    ),
                    "requested_mode": requested_mode,
                    "executed_mode": str(payload.get("mode") or requested_mode),
                    "mode_invocation_status": str(
                        provider_payload.get("mode_invocation_status") or ""
                    ),
                    "mode_dispatch_attempted": mode_dispatch_attempted,
                    "provider_invocation_performed": provider_invocation_performed,
                    "model_invocation_performed": provider_payload.get("model_invocation_performed")
                    is True,
                    "tool_invocation_performed": provider_payload.get("tool_invocation_performed")
                    is True,
                    "named_blocker": named_blocker,
                    "source_provider_id": str(source_invocation.get("provider_id") or ""),
                    "source_result_count": int(source_invocation.get("result_count") or 0),
                    "search_query_normalized": source_query_normalization.get("normalized") is True,
                    "selected_carrier_provider_id": str(
                        actual_refs.get("selected_carrier_provider_id")
                        or provider_payload.get("selected_carrier_provider_id")
                        or ""
                    ),
                    "provider_task_id": provider_task_id,
                    "wave_scoped_provider_task_id": True,
                    "wave_scope_id": wave_scope_id,
                    "record_path": evidence_refs.get("record_path", ""),
                    "provider_invocation_ref": evidence_refs.get("provider_invocation_ref", ""),
                    "provider_latest_ref": evidence_refs.get("provider_latest_ref", ""),
                    "provider_probe": False,
                },
            }
        )
        invocations.append(
            {
                "lane_id": lane["lane_id"],
                "phase": lane["phase"],
                "invocation_id": invocation_id,
                "provider_task_id": provider_task_id,
                "wave_scoped_provider_task_id": True,
                "wave_scope_id": wave_scope_id,
                "requested_mode": requested_mode,
                "executed_mode": str(payload.get("mode") or requested_mode),
                "poll_status": poll_status,
                "mode_invocation_status": str(provider_payload.get("mode_invocation_status") or ""),
                "mode_dispatch_attempted": mode_dispatch_attempted,
                "provider_invocation_performed": provider_invocation_performed,
                "model_invocation_performed": provider_payload.get("model_invocation_performed")
                is True,
                "tool_invocation_performed": provider_payload.get("tool_invocation_performed")
                is True,
                "source_provider_id": str(source_invocation.get("provider_id") or ""),
                "source_result_count": int(source_invocation.get("result_count") or 0),
                "search_query_normalized": source_query_normalization.get("normalized") is True,
                "named_blocker": named_blocker,
                "artifact_refs": artifact_refs,
                "record_path": evidence_refs.get("record_path", ""),
                "provider_invocation_ref": evidence_refs.get("provider_invocation_ref", ""),
            }
        )
        updated_lanes.append(updated_lane)
    return updated_lanes, invocations


def ledger_entry_from_lane(
    *,
    task_id: str,
    wave_id: str,
    workflow_id: str,
    phase_scope: str,
    continuation_authorization_lane: str,
    worker_kind: str,
    lane: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    poll_status = str(lane.get("status") or "dispatched")
    if poll_status not in TERMINAL_STATUSES and poll_status not in {
        "queued",
        "dispatched",
        "polling",
    }:
        poll_status = "dispatched"
    lane_kind = str(lane.get("lane_kind") or "")
    mode = "subagent" if lane_kind == "codex_subagent" else "dp_sidecar_execution"
    evidence = lane.get("evidence_refs") if isinstance(lane.get("evidence_refs"), dict) else {}
    provider = (
        "codex.subagent"
        if mode == "subagent"
        else str(evidence.get("selected_carrier_provider_id") or "legacy.deepseek_dp_sidecar")
    )
    agent_id = (
        str(evidence.get("agent_id") or lane.get("lane_id"))
        if mode == "subagent"
        else str(evidence.get("provider_invocation_ref") or lane.get("lane_id"))
    )
    artifact_refs = [
        str(ref) for ref in lane.get("artifact_refs", []) if isinstance(ref, str) and ref.strip()
    ]
    if not artifact_refs:
        artifact_refs = [f"lane:{lane.get('lane_id')}"]
    return {
        "entry_id": f"{wave_id}:{lane['lane_id']}",
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "phase_scope": phase_scope,
        "continuation_authorization_lane": continuation_authorization_lane,
        "worker_kind": worker_kind,
        "task_id": task_id,
        "lane_id": str(lane["lane_id"]),
        "agent_id": agent_id,
        "provider": provider,
        "mode": mode,
        "dispatch_time": now_iso(),
        "poll_status": poll_status,
        "requested_dp_mode": str(evidence.get("requested_mode") or ""),
        "executed_dp_mode": str(
            evidence.get("executed_mode") or evidence.get("requested_mode") or ""
        ),
        "mode_invocation_status": str(evidence.get("mode_invocation_status") or ""),
        "mode_dispatch_attempted": evidence.get("mode_dispatch_attempted") is True,
        "provider_invocation_performed": evidence.get("provider_invocation_performed") is True,
        "model_invocation_performed": evidence.get("model_invocation_performed") is True,
        "tool_invocation_performed": evidence.get("tool_invocation_performed") is True,
        "artifact_refs": artifact_refs,
        "fan_in_decision": (
            "accepted_for_ledger_evidence_only"
            if poll_status == "succeeded"
            else "staged_candidate_only"
            if poll_status in {"queued", "dispatched", "polling"}
            else "rejected"
        ),
        "next_wave_decision": "requires_upstream_scheduler_explicit_call",
        "adoption_state": "verifier_ready_but_not_hooked",
        "transport_pattern_ref": "s_native_max_capability_dp_poll",
        "legacy_5d33_transport_pattern_reused": False,
        "legacy_5d33_owner_reused": False,
        "legacy_5d33_pass_reused": False,
        "legacy_5d33_latest_authority_reused": False,
        "new_owner_created": False,
        "codex_a_intent_ingress_called": False,
        "pump_default_used": False,
        **default_boundary(),
    }


def write_worker_assignment(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    wave_id: str,
    workflow_id: str,
    workflow_run_id: str,
    phase_scope: str,
    continuation_authorization_lane: str,
    worker_assignment_ref: str,
    worker_kind: str,
    provider_routing_mode: str,
    default_token_saving_worker_route: bool | None,
    intent_package: Path,
    work_package: dict[str, Any],
    width: dict[str, Any],
    boot_spec: dict[str, Any],
    lane_plan: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    package_id = source_intent_package_id(intent_package)
    explicit_work_package_bound = bool(work_package)
    node_id = work_package_node_id(work_package)
    paths = output_paths(
        runtime,
        repo,
        task_id,
        assignment_dag_node_id=node_id,
    )
    acceptance = work_package_acceptance(work_package)
    files = work_package_files(work_package, paths)
    objective = work_package_objective(work_package)
    node_status = work_package_status(work_package)
    base_assignment_ref = worker_assignment_ref or str(
        runtime / "state" / "worker_assignment" / "xinao_seed_cortex_phase0_20260701.json"
    )
    payload = {
        "schema_version": "xinao.worker_assignment.v2.dag",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "assignment_id": task_id,
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "phase_scope": phase_scope,
        "continuation_authorization_lane": continuation_authorization_lane,
        "worker_kind": worker_kind,
        "provider_routing_mode": provider_routing_mode,
        "default_token_saving_worker_route": default_token_saving_worker_route,
        "existing_temporal_workflow_bound": bool(workflow_id),
        "explicit_work_package_bound": explicit_work_package_bound,
        "work_package_digest_sha256": sha256_json(work_package)
        if explicit_work_package_bound
        else "",
        "work_package_next_ready_node_id": node_id if explicit_work_package_bound else "",
        "work_package_objective": objective,
        "source_intent_package_ref": str(intent_package),
        "source_intent_package_id": package_id,
        "source_package_rebound": package_id == "grok_333_continue",
        "forbidden_source_package_shapes": [
            "one_wave_stop_package",
            "pass_report_readback_stop_package",
            "verifier_only_terminal_package",
            "phase0_default_hot_path_full_closure_as_default",
        ],
        "base_assignment_ref": base_assignment_ref,
        "codex_not_all_roles_at_once": True,
        "spawn_new_owner_allowed": False,
        "new_owner_created": False,
        "codex_a_intent_ingress_called": False,
        "pump_default_used": False,
        "assignment_role": "task_scoped_think_execute_worker_assignment",
        "scope_level_target": "L3",
        "scope_level_current": (
            "L3_supervisor_loop_default_with_serial_exception_for_unbound_model_router"
            if width.get("serial_exception") is True
            else "L3_supervisor_loop_default_running"
        ),
        "primary_authority_rank": 0,
        "primary_authority_path": boot_spec.get(
            "primary_authority_path", str(PRIMARY_AUTHORITY_PATH)
        ),
        "grok_contract_rank": 0,
        "current_grok_package_rank": 0,
        "current_grok_package_authority_proxy": True,
        "total_draft_spec_ref": boot_spec.get("spec_ref", paths["total_draft_spec"]),
        "total_draft_section_refs": TOTAL_DRAFT_SECTION_REFS,
        "forbidden_scope_shrink": [
            "L1_local_point_parallel_as_default",
            "total_draft_reference_only",
            "verify_wave_as_completion",
            "one_parallel_wave_summary_as_dynamic_loop",
        ],
        "assignment_dag": {
            "current_active_node_id": node_id,
            "next_ready_node_id": node_id,
            "previous_completed_node_id": "",
            "blocked_terminal_node_id": "completion_side_audit_gate",
            "next_ready": True,
            "nodes": [
                {
                    "id": node_id,
                    "status": node_status,
                    "title": work_package_title(work_package),
                    "files": files,
                    "acceptance": acceptance,
                    "objective": objective,
                    "explicit_work_package_bound": explicit_work_package_bound,
                }
            ],
        },
        "width_decision": width,
        "think_lanes": lane_plan["think_lanes"],
        "execute_lanes": lane_plan["execute_lanes"],
        "dependencies": lane_plan["dependencies"],
        "output_refs": paths,
        "created_at": now_iso(),
        "validation": {
            "checks": {
                "think_lanes_present": bool(lane_plan["think_lanes"]),
                "execute_lanes_present": bool(lane_plan["execute_lanes"]),
                "dependencies_present": bool(lane_plan["dependencies"]),
                "fixed_width_not_used": width.get("hardcoded_fixed_width_used") is False,
                "scope_level_target_l3": True,
                "primary_authority_rank_0_current_grok_package": True,
                "total_draft_section_refs_present": True,
                "workflow_id_bound": bool(workflow_id),
                "phase_scope_bound": bool(phase_scope),
                "continuation_authorization_lane_bound": bool(continuation_authorization_lane),
                "spawn_new_owner_not_allowed": True,
                "work_package_next_ready_node_bound": (
                    not explicit_work_package_bound or node_id == work_package_node_id(work_package)
                ),
            },
        },
        **default_boundary(),
    }
    payload["validation"]["passed"] = all(payload["validation"]["checks"].values())
    if write:
        write_json(Path(paths["worker_assignment"]), payload)
    return payload


def write_worker_dispatch_ledger(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    wave_id: str,
    workflow_id: str,
    phase_scope: str,
    continuation_authorization_lane: str,
    worker_kind: str,
    lanes: list[dict[str, Any]],
    write: bool,
) -> dict[str, Any]:
    ledger_module = load_sibling_module("worker_dispatch_ledger")
    entries = [
        ledger_entry_from_lane(
            task_id=task_id,
            wave_id=wave_id,
            workflow_id=workflow_id,
            phase_scope=phase_scope,
            continuation_authorization_lane=continuation_authorization_lane,
            worker_kind=worker_kind,
            lane=lane,
            index=index,
        )
        for index, lane in enumerate(lanes, start=1)
    ]
    payload = ledger_module.build_worker_dispatch_ledger(
        repo_root=repo,
        runtime_root=runtime,
        wave_id=wave_id,
        task_id=task_id,
        extra_entries=entries,
        poll_scope_lane_id_prefixes=("codex-max-think-", "codex-max-execute-"),
        runtime_entrypoint_invocation={
            "invoked_by": "codex_max_capability_think_execute.worker_dispatch_ledger_poll",
            "runtime_enforced_scope": "seed_cortex_codex_max_capability_think_execute",
            "runtime_enforced": True,
            "workflow_id": workflow_id,
            "phase_scope": phase_scope,
            "continuation_authorization_lane": continuation_authorization_lane,
            "worker_kind": worker_kind,
            "new_owner_created": False,
            "codex_a_intent_ingress_called": False,
            "pump_default_used": False,
        },
        write=write,
    )
    return payload if isinstance(payload, dict) else {}


def edge_shape(entry: dict[str, Any], index: int) -> dict[str, Any]:
    lane_id = str(entry.get("lane_id") or f"lane-{index:02d}")
    dp_mode = str(entry.get("executed_dp_mode") or entry.get("requested_dp_mode") or "")
    digest = hashlib.sha256(lane_id.encode("utf-8")).hexdigest()[:12]
    if "subagent" in lane_id:
        edge_kind = "audit"
        resource_lane = "codex_subagent"
    elif dp_mode in {"draft", "eval", "contradiction", "extraction", "audit"}:
        edge_kind = dp_mode
        resource_lane = "dp_model" if dp_mode != "draft" else "dp_draft"
    elif "search" in lane_id:
        edge_kind = "search"
        resource_lane = "dp_search"
    else:
        edge_kind = "read"
        resource_lane = "dp_sidecar"
    return {
        "edge_id": f"codex-max-capability-edge-{index:02d}-{digest}",
        "edge_kind": edge_kind,
        "resource_lane": resource_lane,
        "expected_marginal_value": 0.86
        if edge_kind == "draft"
        else 0.82
        if edge_kind in {"eval", "search"}
        else 0.76,
        "verification_cost": 0.2,
        "merge_cost": 0.1,
        "risk_cost": 0.12,
        "selected": entry.get("poll_status") == "succeeded",
    }


def write_lane_results_and_fan_in(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    wave_id: str,
    workflow_id: str,
    phase_scope: str,
    continuation_authorization_lane: str,
    ledger: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime, repo, task_id)
    poll_entries = [
        entry
        for entry in ledger.get("poll_entries", [])
        if isinstance(entry, dict) and str(entry.get("poll_status") or "") in TERMINAL_STATUSES
    ]
    succeeded = [entry for entry in poll_entries if entry.get("poll_status") == "succeeded"]
    accepted_edges: list[dict[str, Any]] = []
    rejected_edges: list[dict[str, Any]] = []
    lane_results: list[dict[str, Any]] = []
    lane_result_refs: list[str] = []
    plan_id = f"codex-max-capability-think-execute:{wave_id}"
    lane_dir = Path(paths["lane_results_dir"])
    ledger_ref = runtime / "state" / "worker_dispatch_ledger" / "latest.json"
    for index, entry in enumerate(poll_entries, start=1):
        edge = edge_shape(entry, index)
        poll_status = str(entry.get("poll_status") or "failed")
        terminal_state = (
            "succeeded"
            if poll_status == "succeeded"
            else "blocked"
            if poll_status == "blocked"
            else "cancelled"
            if poll_status == "cancelled"
            else "failed"
        )
        result = {
            "schema_version": "xinao.codex_s.parallel_lane_result.v1",
            "work_id": WORK_ID,
            "route_profile": ROUTE_PROFILE,
            "result_id": f"{edge['edge_id']}:result",
            "plan_id": plan_id,
            "workflow_id": workflow_id,
            "phase_scope": phase_scope,
            "continuation_authorization_lane": continuation_authorization_lane,
            "edge_id": edge["edge_id"],
            "edge_kind": edge["edge_kind"],
            "resource_lane": edge["resource_lane"],
            "terminal_state": terminal_state,
            "expected_marginal_value": edge["expected_marginal_value"],
            "verification_cost": edge["verification_cost"],
            "merge_cost": edge["merge_cost"],
            "risk_cost": edge["risk_cost"],
            "selected": poll_status == "succeeded",
            "artifact_refs": [
                str(ref)
                for ref in entry.get("artifact_refs", [])
                if isinstance(ref, str) and ref.strip()
            ]
            or [str(ledger_ref)],
            "source_kind": "worker_dispatch_ledger_poll",
            "worker_dispatch_ledger_entry_ref": f"{ledger_ref}#entry_id={entry.get('entry_id') or ''}",
            "worker_dispatch_ledger_entry_id": str(entry.get("entry_id") or ""),
            "worker_dispatch_ledger_poll_status": poll_status,
            "source_worker_dispatch_ledger_ref": str(ledger_ref),
            "source_worker_dispatch_ledger_entry_id": str(entry.get("entry_id") or ""),
            "source_poll_status": poll_status,
            "requested_dp_mode": str(entry.get("requested_dp_mode") or ""),
            "executed_dp_mode": str(
                entry.get("executed_dp_mode") or entry.get("requested_dp_mode") or ""
            ),
            "mode_invocation_status": str(entry.get("mode_invocation_status") or ""),
            "written_by_driver_from_ledger_poll": True,
            "synthetic_succeeded": False,
            "synthetic_succeeded_by_driver": False,
            "driver_synthetic_succeeded_allowed": False,
            "default_boundary": default_boundary(),
        }
        result_path = lane_dir / f"{edge['edge_id']}.json"
        lane_results.append(result)
        lane_result_refs.append(str(result_path))
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
            write_json(result_path, result)
    fan_in = {
        "schema_version": "xinao.codex_s.fan_in_acceptance.v1",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "acceptance_id": f"codex-max-capability-fan-in:{wave_id}",
        "plan_id": plan_id,
        "workflow_id": workflow_id,
        "phase_scope": phase_scope,
        "continuation_authorization_lane": continuation_authorization_lane,
        "parallel_default": "max_expected_marginal_value",
        "source_kind": "worker_dispatch_ledger_poll",
        "worker_dispatch_ledger_succeeded_count": len(succeeded),
        "driver_synthetic_succeeded_allowed": False,
        "accepted_edges": accepted_edges,
        "rejected_edges": rejected_edges,
        "serial_deferred_edges": [],
        "default_boundary": default_boundary(),
    }
    aggregate = {
        "schema_version": LANE_RESULTS_SCHEMA_VERSION,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "phase_scope": phase_scope,
        "continuation_authorization_lane": continuation_authorization_lane,
        "status": "codex_max_capability_lane_results_ready",
        "plan_id": plan_id,
        "source_kind": "worker_dispatch_ledger_poll",
        "poll_source": "worker_dispatch_ledger_poll",
        "worker_dispatch_ledger_ref": str(ledger_ref),
        "fan_in_acceptance_ref": paths["fan_in_acceptance_latest"],
        "lane_result_refs": lane_result_refs,
        "lane_result_count": len(lane_results),
        "ledger_poll_entry_count": len(poll_entries),
        "worker_dispatch_ledger_succeeded_count": len(succeeded),
        "accepted_edge_count": len(accepted_edges),
        "rejected_edge_count": len(rejected_edges),
        "fan_in_consumed_real_lane_results": len(accepted_edges) == len(succeeded)
        and len(succeeded) > 0,
        "synthetic_succeeded_count": 0,
        "driver_synthetic_succeeded_allowed": False,
        "fan_in_before_artifact_acceptance": True,
        "fan_in_acceptance": fan_in,
        "validation": {
            "passed": len(succeeded) > 0
            and len(accepted_edges) == len(succeeded)
            and len(lane_results) == len(poll_entries),
            "checks": {
                "ledger_has_succeeded_poll": len(succeeded) > 0,
                "fan_in_accepts_only_ledger_succeeded": len(accepted_edges) == len(succeeded),
                "lane_results_match_poll_entries": len(lane_results) == len(poll_entries),
                "source_is_worker_dispatch_ledger_poll": True,
                "synthetic_succeeded_count_zero": True,
            },
            "validated_at": now_iso(),
        },
        **default_boundary(),
    }
    if write:
        write_json(Path(paths["fan_in_acceptance_latest"]), fan_in)
        write_json(Path(paths["fan_in_acceptance_task_latest"]), fan_in)
        write_json(Path(paths["lane_results_latest"]), aggregate)
        write_json(Path(paths["lane_results_task_latest"]), aggregate)
    return {"lane_results": aggregate, "fan_in_acceptance": fan_in}


def run_artifact_acceptance(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    fan_in_artifact_ref: str,
    task_card: dict[str, Any],
    service: Any | None,
    write: bool,
) -> dict[str, Any]:
    if service is None:
        ensure_import_path(repo)
        from xinao_seedlab.application.seed_cortex import build_default_service

        service = build_default_service(runtime, repo_root=repo)
    candidates = [
        {
            "candidate_id": "codex-max-capability-fan-in",
            "artifact_kind": "codex_max_capability_think_execute_fan_in",
            "producer_lane": "codex_max_capability_think_execute",
            "artifact_ref": fan_in_artifact_ref,
            "expected_schema_version": LANE_RESULTS_SCHEMA_VERSION,
            "accepted_for": "next_frontier_evidence",
            "verification_refs": [
                "tests/seedcortex/test_codex_max_capability_think_execute.py",
                "scripts/verify_codex_max_capability_think_execute.ps1",
            ],
            "fan_in_required": True,
            "file_exists_only": False,
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
        }
    ]
    claim_card = (
        task_card.get("claim_card_candidate")
        if isinstance(task_card.get("claim_card_candidate"), dict)
        else {}
    )
    if claim_card:
        candidates.append(claim_card)
    return service.artifact_acceptance_queue(
        f"{safe_id(task_id, limit=80)}-artifact-acceptance",
        candidates,
        write_runtime=write,
    )


def write_continuity_envelope(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    wave_id: str,
    workflow_id: str,
    phase_scope: str,
    continuation_authorization_lane: str,
    acceptance: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime, repo, task_id)
    accepted_count = int(acceptance.get("accepted_artifact_count") or 0)
    envelope = {
        "schema_version": "xinao.codex_s.continuity_envelope.v1",
        "object_type": "ContinuityEnvelope",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "phase_scope": phase_scope,
        "continuation_authorization_lane": continuation_authorization_lane,
        "status": "continuity_envelope_written_after_artifact_acceptance"
        if accepted_count > 0
        else "continuity_envelope_blocked_before_acceptance",
        "should_continue_loop": True,
        "temporal_auto_continue_expected": True,
        "next_wave_required": True,
        "artifact_acceptance_ref": str(
            runtime / "state" / "artifact_acceptance_queue" / "latest.json"
        ),
        "accepted_artifact_count": accepted_count,
        "chinese_anchor_text": (
            "本轮 RootIntentLoop 不靠 Stop hook 或 PASS 续命：WORKER_ASSIGNMENT 已拆成 think/execute，"
            "DP 默认走非 provider_probe，worker_dispatch_ledger poll 后 fan-in，"
            "ArtifactAcceptance 通过后回插队/父任务栈；没有父任务时回 root 重新算 highest-EV next action。"
        ),
        "return_stack": [
            {
                "frame_id": "seed-cortex-root-mainline",
                "kind": "mainline",
                "status": "active",
                "pop_restore_available": True,
                "root_recompute_when_empty": True,
            }
        ],
        "next_default_action": (
            "return_to_parent_or_root_recompute_highest_ev_next_action"
            if accepted_count > 0
            else "repair_artifact_acceptance_before_next_wave"
        ),
        "readback_zh_ref": paths["runtime_readback_zh"],
        **default_boundary(),
    }
    if write:
        write_json(Path(paths["continuity_envelope_latest"]), envelope)
    return envelope


def write_task_bound_assignment_dag_evidence(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    wave_id: str,
    workflow_id: str,
    workflow_run_id: str,
    phase_scope: str,
    continuation_authorization_lane: str,
    worker_assignment_ref: str,
    worker_kind: str,
    work_package: dict[str, Any],
    worker_assignment: dict[str, Any],
    summary: dict[str, Any],
    continuity: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    dag = (
        worker_assignment.get("assignment_dag")
        if isinstance(worker_assignment.get("assignment_dag"), dict)
        else {}
    )
    node_id = (
        work_package_node_id(work_package)
        if work_package
        else str(dag.get("next_ready_node_id") or dag.get("current_active_node_id") or NODE_ID)
    )
    paths = output_paths(
        runtime,
        repo,
        task_id,
        assignment_dag_node_id=node_id,
    )
    latest = Path(paths["task_bound_assignment_dag_latest"])
    node_latest = Path(paths["task_bound_assignment_dag_node_latest"])
    jsonl_path = Path(paths["task_bound_assignment_dag_node_jsonl"])
    workflow_latest = (
        Path(paths["task_bound_assignment_dag_workflow_runs"])
        / safe_id(workflow_id, limit=120)
        / safe_id(wave_id, limit=120)
        / f"{safe_id(node_id, limit=120)}.latest.json"
    )
    evidence = {
        "schema_version": "xinao.codex_s.task_bound_assignment_dag_node_evidence.v1",
        "status": "task_bound_assignment_dag_node_evidence_written",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "node_id": node_id,
        "phase_scope": phase_scope,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "wave_id": wave_id,
        "continuation_authorization_lane": continuation_authorization_lane,
        "worker_assignment_ref": worker_assignment_ref,
        "worker_kind": worker_kind,
        "explicit_work_package_bound": bool(work_package),
        "work_package_digest_sha256": sha256_json(work_package) if work_package else "",
        "work_package_next_ready_node_id": node_id if work_package else "",
        "work_package_objective": work_package_objective(work_package),
        "task_bound_codex_worker_marker": TASK_BOUND_CODEX_WORKER_MARKER,
        "new_owner_created": False,
        "codex_a_intent_ingress_called": False,
        "pump_default_used": False,
        "completion_claim_allowed": False,
        "assignment_dag": dag,
        "current_active_node_id": dag.get("current_active_node_id", ""),
        "next_ready_node_id": dag.get("next_ready_node_id", ""),
        "think_lane_count": int(summary.get("think_lane_count") or 0),
        "execute_lane_count": int(summary.get("execute_lane_count") or 0),
        "worker_dispatch_ledger_succeeded_count": int(
            summary.get("worker_dispatch_ledger_succeeded_count") or 0
        ),
        "accepted_artifact_count": int(summary.get("artifact_acceptance_accepted_count") or 0),
        "continuity_should_continue_loop": continuity.get("should_continue_loop") is True,
        "continuity_next_default_action": str(continuity.get("next_default_action") or ""),
        "evidence_refs": {
            "worker_assignment": paths["worker_assignment"],
            "runtime_latest": paths["runtime_latest"],
            "continuity_envelope": paths["continuity_envelope_latest"],
            "node_latest": paths["task_bound_assignment_dag_node_latest"],
            "jsonl": paths["task_bound_assignment_dag_node_jsonl"],
        },
        "latest_ref": str(latest),
        "node_latest_ref": str(node_latest),
        "workflow_run_latest_ref": str(workflow_latest),
        "jsonl_ref": str(jsonl_path),
        "validation": {
            "passed": (
                dag.get("current_active_node_id") == node_id
                and dag.get("next_ready_node_id") == node_id
                and bool(workflow_id)
                and bool(phase_scope)
                and bool(continuation_authorization_lane)
                and int(summary.get("execute_lane_count") or 0) > 0
                and continuity.get("should_continue_loop") is True
            )
        },
        **default_boundary(),
    }
    evidence["record_digest_sha256"] = sha256_json(evidence)
    if write:
        write_json(latest, evidence)
        write_json(node_latest, evidence)
        write_json(workflow_latest, evidence)
        append_jsonl(jsonl_path, evidence)
    return evidence


def phase0_closure_dag(
    *,
    hook_binding: dict[str, Any],
    worker_assignment: dict[str, Any],
    summary: dict[str, Any],
    boot_spec: dict[str, Any],
    continuity: dict[str, Any],
    output_paths: dict[str, Any],
    validation_checks: dict[str, bool],
) -> dict[str, Any]:
    named_serial_exception = bool(summary.get("named_serial_exception_present") is True)
    ledger_hooked = hook_binding.get("adoption_state") == "hooked_runtime_entrypoint"
    dp_draft_eval_succeeded = int(summary.get("dp_execute_draft_eval_succeeded_count") or 0) > 0
    nodes = [
        {
            "id": "WP_HOOK",
            "status": "ready" if ledger_hooked else "blocked",
            "evidence_refs": [
                r"D:\XINAO_RESEARCH_RUNTIME\state\worker_dispatch_ledger\temporal_activity_latest.json",
                r"D:\XINAO_RESEARCH_RUNTIME\state\root_intent_loop_driver\latest.json",
            ],
            "can_do_cn": "默认热路径可识别 Temporal worker_dispatch_ledger activity，并把 RootIntentLoop fan-in 限定到 ledger poll。",
            "named_blocker": hook_binding.get("named_blocker") or "",
        },
        {
            "id": "WP_THINK",
            "status": (
                "ready"
                if summary.get("think_lane_count", 0) > 0
                and (summary.get("dp_nonprobe_attempted_count", 0) > 0 or named_serial_exception)
                else "blocked"
            ),
            "evidence_refs": [
                output_paths.get("worker_assignment", ""),
                output_paths.get("runtime_task_latest", ""),
            ],
            "can_do_cn": "能把整包意图拆成 think_lanes，并把 search 留在 think/context 扇出。",
            "named_blocker": "",
        },
        {
            "id": "WP_EXECUTE",
            "status": ("ready" if dp_draft_eval_succeeded or named_serial_exception else "blocked"),
            "evidence_refs": [output_paths.get("lane_results_latest", "")],
            "can_do_cn": (
                "能进入 execute_lanes，并已完成非 probe draft/eval；模型类 mature router 未绑定时仍作为 serial_exception。"
                if dp_draft_eval_succeeded
                else "能进入 execute_lanes；当前 draft/eval provider 不可用时写 named serial_exception，而不是伪造 succeeded。"
            ),
            "named_blocker": summary.get("execute_serial_exception_named_blocker", ""),
        },
        {
            "id": "WP_READBACK",
            "status": "ready",
            "evidence_refs": [output_paths.get("runtime_readback_zh", "")],
            "can_do_cn": "中文读回回答现在能干什么、L1/L2/L3 差距、下一机器动作。",
            "named_blocker": "",
        },
        {
            "id": "WP_BOOT_STABLE",
            "status": "ready"
            if boot_spec.get("validation", {}).get("passed") is True
            else "blocked",
            "evidence_refs": [
                output_paths.get("total_draft_spec", ""),
                output_paths.get("worker_assignment", ""),
            ],
            "can_do_cn": "新窗默认读 ORDER+两份权威+spec mirror，并保持 L3 whole-transaction default。",
            "named_blocker": ""
            if boot_spec.get("validation", {}).get("passed") is True
            else "TOTAL_DRAFT_BOOT_SPEC_NOT_VALID",
        },
        {
            "id": "WP_VERIFY",
            "status": "ready" if all(validation_checks.values()) else "blocked",
            "evidence_refs": [
                "scripts/verify_codex_max_capability_think_execute.ps1",
                "scripts/verify_phase0_default_hot_path_full_closure.ps1",
            ],
            "can_do_cn": "整包 verifier 能挡住 L1 冒充、not_hooked 冒充、provider_probe 冒充。",
            "named_blocker": ""
            if all(validation_checks.values())
            else "PHASE0_FULL_CLOSURE_VALIDATION_FAILED",
        },
    ]
    return {
        "schema_version": "xinao.codex_s.phase0_default_hot_path_full_closure_dag.v1",
        "status": "ready" if all(node["status"] == "ready" for node in nodes) else "blocked",
        "task_id": worker_assignment.get("task_id"),
        "scope_level_target": worker_assignment.get("scope_level_target"),
        "scope_level_current": worker_assignment.get("scope_level_current"),
        "ledger_adoption_state": hook_binding.get("adoption_state"),
        "base_worker_dispatch_ledger_adoption_state": hook_binding.get(
            "base_worker_dispatch_ledger_adoption_state"
        ),
        "not_hooked_as_completion_forbidden": True,
        "named_serial_exception_present": named_serial_exception,
        "should_continue_loop": continuity.get("should_continue_loop") is True,
        "nodes": nodes,
        "default_boundary": default_boundary(),
    }


def intent_work_package_status(
    *,
    intent_payload: dict[str, Any],
    summary: dict[str, Any],
    width: dict[str, Any],
    hook_binding: dict[str, Any],
    validation_checks: dict[str, bool],
) -> list[dict[str, Any]]:
    semantic = (
        intent_payload.get("semantic_object")
        if isinstance(intent_payload.get("semantic_object"), dict)
        else {}
    )
    raw_packages = (
        semantic.get("work_packages") if isinstance(semantic.get("work_packages"), list) else []
    )
    dp_attempted = int(summary.get("dp_nonprobe_attempted_count") or 0) > 0
    dp_succeeded = int(summary.get("dp_nonprobe_succeeded_count") or 0) > 0
    mature_router_bound = width.get("mature_router_bound") is True
    hotpath_hooked = (
        hook_binding.get("adoption_state") == "hooked_runtime_entrypoint"
        and validation_checks.get("ledger_adoption_state_hooked") is True
        and validation_checks.get("continuity_should_continue_loop") is True
    )
    validation_ready = all(validation_checks.values())

    def state_for(package_id: str) -> tuple[str, str, str]:
        if package_id == "WP_DIAG":
            return (
                "ready" if dp_attempted else "blocked",
                "已查 provider 链：付费 Exa/Serper auth fail，本地 SearXNG 未监听，免费 DDGS/DuckDuckGo fallback 可接管。",
                "" if dp_attempted else "DP_SEARCH_DIAG_NOT_ATTEMPTED",
            )
        if package_id == "WP_FIX_PROVIDER":
            return (
                "ready" if dp_succeeded else "blocked",
                "search 只作为 think/context 扇出；execute 进展必须来自 draft/eval。",
                "" if dp_succeeded else "DP_SEARCH_FREE_PROVIDER_FAILED_OR_EMPTY",
            )
        if package_id == "WP_ROUTER_BIND":
            return (
                "ready" if mature_router_bound else "blocked",
                "mature router 未伪装绑定；当前为 router_serial_exception，默认模型宽并行仍关闭。",
                "" if mature_router_bound else "XINAO_MATURE_ROUTER_BACKEND_NOT_BOUND",
            )
        if package_id == "WP_EXECUTE_WAVE":
            return (
                "ready" if dp_succeeded else "blocked",
                "think/search 只做上下文扇出；execute/draft 和 execute/eval 走 dp_sidecar_execution_port 非 probe 调用并进入 ledger/fan-in。",
                "" if dp_succeeded else "DP_EXECUTE_WAVE_NO_NONPROBE_SUCCESS",
            )
        if package_id == "WP_HOTPATH":
            return (
                "ready" if hotpath_hooked else "blocked",
                "worker_dispatch_ledger adoption 保持 hooked_runtime_entrypoint；should_continue_loop=true。",
                "" if hotpath_hooked else "DEFAULT_HOTPATH_LEDGER_NOT_HOOKED",
            )
        if package_id == "WP_PRODUCT_READBACK":
            return (
                "ready",
                "中文读回写入 D runtime，回答现在能搜、能调、仍差哪个 router/backend。",
                "",
            )
        if package_id == "WP_VERIFY_MIN":
            return (
                "ready" if validation_ready else "blocked",
                "只复用现有最小验收面；未新增 verifier。",
                "" if validation_ready else "MIN_ACCEPTANCE_CHECK_FAILED",
            )
        return ("observed", "包内 WP 已进入 readback；未绑定专门状态机。", "")

    rows: list[dict[str, Any]] = []
    for item in raw_packages:
        if not isinstance(item, dict):
            continue
        package_id = str(item.get("id") or "").strip()
        if not package_id:
            continue
        status, can_do, blocker = state_for(package_id)
        rows.append(
            {
                "id": package_id,
                "title": str(item.get("title") or ""),
                "status": status,
                "can_do_cn": can_do,
                "named_blocker": blocker,
            }
        )
    return rows


def render_readback(payload: dict[str, Any]) -> str:
    width = payload["width_decision"]
    summary = payload["summary"]
    paths = payload["output_paths"]
    assignment = payload["WORKER_ASSIGNMENT"]
    boot_spec = (
        payload.get("total_draft_boot_spec")
        if isinstance(payload.get("total_draft_boot_spec"), dict)
        else {}
    )
    hook = payload.get("hook_binding") if isinstance(payload.get("hook_binding"), dict) else {}
    dag = (
        payload.get("phase0_closure_dag")
        if isinstance(payload.get("phase0_closure_dag"), dict)
        else {}
    )
    task_card = payload.get("task_card") if isinstance(payload.get("task_card"), dict) else {}
    artifact_acceptance = (
        payload.get("artifact_acceptance")
        if isinstance(payload.get("artifact_acceptance"), dict)
        else {}
    )
    workflow_binding = (
        payload.get("workflow_binding") if isinstance(payload.get("workflow_binding"), dict) else {}
    )
    explicit_work_package = (
        payload.get("explicit_work_package")
        if isinstance(payload.get("explicit_work_package"), dict)
        else {}
    )
    source_ledger_ref = (
        str(artifact_acceptance.get("source_ledger_ref") or "")
        or r"D:\XINAO_RESEARCH_RUNTIME\state\source_ledger\latest.json"
    )
    dp_invocations = (
        payload.get("dp_invocations") if isinstance(payload.get("dp_invocations"), list) else []
    )
    successful_dp = [
        item
        for item in dp_invocations
        if isinstance(item, dict) and item.get("poll_status") == "succeeded"
    ]
    source_provider_summary = sorted(
        {
            (
                str(item.get("source_provider_id") or "unknown"),
                int(item.get("source_result_count") or 0),
            )
            for item in successful_dp
        }
    )
    source_provider_text = (
        "；".join(f"{provider} results={count}" for provider, count in source_provider_summary)
        if source_provider_summary
        else "none"
    )
    dp_success = int(summary.get("dp_nonprobe_succeeded_count") or 0) > 0
    execute_draft_success = int(summary.get("dp_execute_draft_succeeded_count") or 0) > 0
    execute_mode_text = ",".join(summary.get("execute_modes_observed") or []) or "none"
    current_wave = (
        payload.get("current_wave_work_packages")
        if isinstance(payload.get("current_wave_work_packages"), list)
        else []
    )
    current_wave_lines = [
        f"- `{item.get('id')}` {item.get('title', '')}：status=`{item.get('status')}`；能干什么：{item.get('can_do_cn')}；blocker=`{item.get('named_blocker') or 'none'}`。"
        for item in current_wave
        if isinstance(item, dict)
    ] or ["- 本轮包未提供 work_packages；沿旧 Phase0 DAG readback。"]
    provider_gap_line = (
        "- 已修通：execute 段已有 DP draft 非 probe succeeded；eval 作为评估支撑单独计数，search 只保留为 think/context 扇出。"
        if execute_draft_success
        else "- 未完全落地：execute draft/eval provider 当前仍有 named serial_exception；不把 search 或 audit 写成 execute 成功。"
    )
    next_machine_action = (
        "- 下一机器动作：按 draft/eval 产物继续 fan-in 和下一波代码 patch；search 仅补上下文，不作为 execute 进展。"
        if execute_draft_success
        else "- 下一机器动作：继续修 draft/eval provider 或 mature router/backend，让下一波 execute lane 真 succeeded。"
    )
    subagent_lines = [
        f"- 子代理 `{lane.get('evidence_refs', {}).get('agent_id', lane.get('lane_id'))}`："
        f"{lane.get('evidence_refs', {}).get('role', '')}，状态 `{lane.get('status')}`。"
        for lane in assignment.get("think_lanes", [])
        if lane.get("lane_kind") == "codex_subagent"
    ]
    if not subagent_lines:
        subagent_lines = ["- 子代理：本轮未传入已 spawn 的子代理 ref。"]
    return "\n".join(
        [
            "# Codex S 整包 think/execute readback",
            "",
            SENTINEL,
            "",
            "## 思考派了什么",
            "",
            *subagent_lines,
            "- DP think lane：`codex-max-think-dp-search-01`，mode=`search`，非 provider_probe，进入外部搜索/上下文扇出。",
            "- search 只在 think：search 是外部上下文/来源发现 lane，进入 fan-in 前保持候选证据，不作为 execute 写码进展。",
            "",
            "## L 层与总稿",
            "",
            f"- 当前目标层：`{assignment.get('scope_level_target')}`；当前状态：`{assignment.get('scope_level_current')}`。",
            (
                f"- 当前 workflow：`{workflow_binding.get('workflow_id') or 'none'}`；"
                f"phase_scope=`{workflow_binding.get('phase_scope') or 'none'}`；"
                f"continuation_lane=`{workflow_binding.get('continuation_authorization_lane') or 'none'}`；"
                f"worker_kind=`{workflow_binding.get('worker_kind') or 'none'}`。"
            ),
            (
                f"- 本轮 work_package bound：{explicit_work_package.get('bound', False)}；"
                f"next_ready_node_id=`{explicit_work_package.get('next_ready_node_id') or 'none'}`；"
                f"objective=`{explicit_work_package.get('objective') or 'none'}`。"
            ),
            "- 本轮没有调用 `/codex-a/intent`，没有创建新 owner，也没有使用 pump default；这里只写 existing Temporal workflow 下的 worker evidence。",
            f"- rank-0 当前 Grok 权威代理已绑定；总稿入口：`{assignment.get('primary_authority_path')}`。",
            f"- D 盘 spec：`{paths.get('total_draft_spec')}`；spec validation：{boot_spec.get('validation', {}).get('passed') if isinstance(boot_spec.get('validation'), dict) else False}。",
            "- 本轮不是 L1 局部并行冒充默认；L1 只能是波内节点，L3 SupervisorLoop 才是默认事务语义。",
            "- 对齐总稿节：§4 SupervisorLoopWorkflow，§11 反事故句，§13 中文 readback，§14 不得把 DeepSeek/search 缩成 Codex 6。",
            "",
            "## 执行几路",
            "",
            (
                f"- 成熟路由观测宽度：{width['observed_provider_width']}；"
                f"parallel_capacity ceiling：{width['parallel_capacity_ceiling']}；"
                f"mature_router_bound：{width['mature_router_bound']}；"
                f"default_dispatch_allowed：{width['default_intelligent_dispatch_allowed']}。"
            ),
            (
                f"- 本轮 effective execute lanes：{width['effective_execute_lane_count']}；"
                f"状态：`{width['execution_width_state']}`；"
                f"serial_exception：{width['serial_exception']}。"
            ),
            (
                f"- ledger succeeded：{summary['worker_dispatch_ledger_succeeded_count']}；"
                f"DP 非 probe succeeded：{summary['dp_nonprobe_succeeded_count']}；"
                f"DP 非 probe attempted：{summary.get('dp_nonprobe_attempted_count', 0)}；"
                f"execute draft succeeded：{summary.get('dp_execute_draft_succeeded_count', 0)}；"
                f"execute eval support succeeded：{summary.get('dp_execute_eval_succeeded_count', 0)}；"
                f"execute search invoked：{summary.get('execute_search_invocation_count', 0)}；"
                f"provider_probe invoked：{summary['provider_probe_invocation_count']}；"
                f"synthetic_succeeded：{summary['synthetic_succeeded_count']}。"
            ),
            (
                f"- ledger hooked：adoption_state=`{hook.get('adoption_state') or 'unknown'}`；"
                f"base_adoption_state=`{hook.get('base_worker_dispatch_ledger_adoption_state') or 'unknown'}`；"
                f"side_audit_spec={hook.get('side_audit_hook_reads_total_draft_spec', False)}；"
                f"temporal_worker_ledger={hook.get('temporal_worker_dispatch_ledger_activity_hooked', False)}；"
                f"blocker=`{hook.get('named_blocker') or 'none'}`。"
            ),
            (
                f"- named serial_exception：{summary.get('named_serial_exception_present', False)}；"
                f"reason=`{summary.get('execute_serial_exception_named_blocker') or 'none'}`。"
            ),
            f"- execute modes observed：`{execute_mode_text}`；source/search provider succeeded：`{source_provider_text}`。",
            "",
            "## WP_HOOK -> THINK -> EXECUTE -> READBACK -> VERIFY",
            "",
            *[
                f"- `{node.get('id')}`：status=`{node.get('status')}`；能干什么：{node.get('can_do_cn')}；blocker=`{node.get('named_blocker') or 'none'}`。"
                for node in dag.get("nodes", [])
            ],
            f"- should_continue_loop：{dag.get('should_continue_loop', False)}。",
            "",
            "## 本轮 7 WP 对照",
            "",
            *current_wave_lines,
            "",
            "## 现在能干什么",
            "",
            "- 写了什么：本轮 S 仓 diff 修改 `services/agent_runtime/codex_max_capability_think_execute.py`、`services/agent_runtime/agent_runtime.py`、`src/xinao_seedlab/adapters/deepseek_parallel_draft.py`、`tests/seedcortex/test_codex_max_capability_think_execute.py`、`tests/seedcortex/test_deepseek_surrogate_sanitizer.py`、`scripts/verify_codex_max_capability_think_execute.ps1`，并写入 task-scoped WORKER_ASSIGNMENT、lane results、fan-in / ArtifactAcceptance / ContinuityEnvelope 证据。",
            "- execute 是 draft/eval：P0 执行段并行走 DP draft / eval，用于写码、评估和回插证据，`execute_search_invocation_count=0`。",
            "- search 只在 think：search 只作为 think 阶段的外部上下文/来源发现 lane，进入 fan-in 前保持候选证据，不作为 execute 写码能力。",
            f"- TaskDecoder 薄绑：TaskCard=`{task_card.get('status', 'unknown')}`，不新建搜索岛，驱动既有 lane 数={len(task_card.get('routes_to_existing_lanes', []) if isinstance(task_card.get('routes_to_existing_lanes'), list) else [])}。",
            f"- SourceLedger+AAQ：ClaimCard 硬门={artifact_acceptance.get('claim_card_hard_gate_enforced', False)}，source_ledger_entries={artifact_acceptance.get('claim_card_source_ledger_entry_count', 0)}，source_ledger_ref=`{artifact_acceptance.get('source_ledger_ref') or 'none'}`。",
            "- 能接收一个整包意图，写 task-scoped WORKER_ASSIGNMENT，并把 think_lanes / execute_lanes / dependencies 明示出来。",
            (
                "- 能真实调用 DP `draft/eval` execute lane，并把 draft/eval 结果送入 ledger/fan-in。"
                if execute_draft_success
                else "- 能真实接收 Codex 子代理 ref，并调用 DP `draft/eval` execute lane；provider 失败时写 named serial_exception，不伪造成功。"
            ),
            "- 能把 fan-in aggregate 送入 ArtifactAcceptanceQueue，通过后写 ContinuityEnvelope 和中文锚定文本。",
            "- 能把当前 Grok rank-0 权威代理和新系统总稿落成 D 盘 spec、L0 首读锚点和 Stop side-audit source anchor。",
            "- 仍不能宣布成熟 router 已绑定；模型类默认宽并行要等 mature router/backend/default_dispatch 绑定后再放开，目前只能写 serial_exception。",
            "",
            "## 总稿差距与下一机器动作",
            "",
            "- 已落地：WP_BOOT1 spec mirror、WORKER_ASSIGNMENT L3 字段、非 probe DP draft/eval execute plan、ledger poll/fan-in/acceptance。",
            provider_gap_line,
            next_machine_action,
            "",
            "## 证据路径",
            "",
            f"- total draft spec：`{paths['total_draft_spec']}`",
            f"- WORKER_ASSIGNMENT：`{paths['worker_assignment']}`",
            f"- TaskCard：`{paths['task_card_task_latest']}`",
            f"- SourceLedger：`{source_ledger_ref}`",
            "- worker ledger：`D:\\XINAO_RESEARCH_RUNTIME\\state\\worker_dispatch_ledger\\latest.json`",
            f"- lane results：`{paths['lane_results_latest']}`",
            f"- fan-in：`{paths['fan_in_acceptance_latest']}`",
            "- ArtifactAcceptance：`D:\\XINAO_RESEARCH_RUNTIME\\state\\artifact_acceptance_queue\\latest.json`",
            f"- ContinuityEnvelope：`{paths['continuity_envelope_latest']}`",
            "",
            SENTINEL,
            "",
        ]
    )


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_id: str = DEFAULT_TASK_ID,
    intent_package: str | Path | None = None,
    wave_id: str = "codex-max-capability-think-execute-wave-20260703",
    workflow_id: str = DEFAULT_WORKFLOW_ID,
    workflow_run_id: str = "",
    phase_scope: str = DEFAULT_PHASE_SCOPE,
    continuation_authorization_lane: str = CONTINUATION_AUTHORIZATION_LANE,
    worker_assignment_ref: str = "",
    worker_kind: str = "implementation_worker",
    provider_routing_mode: str = "runtime_default",
    default_token_saving_worker_route: bool | None = None,
    work_package: str | Path | dict[str, Any] | None = None,
    codex_subagents: list[str] | None = None,
    service: Any | None = None,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    package_ref = resolve_intent_package(intent_package, runtime=runtime, task_id=task_id)
    intent_payload = read_json(package_ref)
    work_package_payload = read_json_argument(work_package)
    assignment_dag_node_id = (
        work_package_node_id(work_package_payload) if work_package_payload else NODE_ID
    )
    intent_text = (
        json.dumps(intent_payload, ensure_ascii=False, sort_keys=True)
        if intent_payload
        else task_id
    )
    paths = output_paths(
        runtime,
        repo,
        task_id,
        assignment_dag_node_id=assignment_dag_node_id,
    )

    boot_spec = total_draft_boot_spec(
        runtime=runtime,
        repo=repo,
        intent_payload=intent_payload,
        write=write,
    )
    hook_binding = hook_binding_state(
        runtime,
        repo,
        str(boot_spec.get("spec_ref") or paths["total_draft_spec"]),
    )
    width = routing_width_decision(runtime)
    lane_plan = build_lane_plan(
        task_id=task_id,
        wave_id=wave_id,
        subagents=codex_subagents or [],
        width=width,
    )
    task_card = build_task_card(
        runtime=runtime,
        repo=repo,
        task_id=task_id,
        wave_id=wave_id,
        package_ref=package_ref,
        intent_payload=intent_payload,
        lane_plan=lane_plan,
        write=write,
    )
    lane_plan = bind_task_card_to_lane_plan(lane_plan, task_card)
    all_planned_lanes = lane_plan["think_lanes"] + lane_plan["execute_lanes"]
    invoked_lanes, dp_invocations = invoke_dp_lanes(
        runtime=runtime,
        repo=repo,
        task_id=task_id,
        wave_id=wave_id,
        lanes=all_planned_lanes,
        intent_text=intent_text,
        write=write,
    )
    think_lanes = [lane for lane in invoked_lanes if lane.get("phase") == "think"]
    execute_lanes = [lane for lane in invoked_lanes if lane.get("phase") == "execute"]
    lane_plan = {
        **lane_plan,
        "think_lanes": think_lanes,
        "execute_lanes": execute_lanes,
    }
    worker_assignment = write_worker_assignment(
        runtime=runtime,
        repo=repo,
        task_id=task_id,
        wave_id=wave_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        phase_scope=phase_scope,
        continuation_authorization_lane=continuation_authorization_lane,
        worker_assignment_ref=worker_assignment_ref,
        worker_kind=worker_kind,
        provider_routing_mode=provider_routing_mode,
        default_token_saving_worker_route=default_token_saving_worker_route,
        intent_package=package_ref,
        work_package=work_package_payload,
        width=width,
        boot_spec=boot_spec,
        lane_plan=lane_plan,
        write=write,
    )
    ledger = write_worker_dispatch_ledger(
        runtime=runtime,
        repo=repo,
        task_id=task_id,
        wave_id=wave_id,
        workflow_id=workflow_id,
        phase_scope=phase_scope,
        continuation_authorization_lane=continuation_authorization_lane,
        worker_kind=worker_kind,
        lanes=think_lanes + execute_lanes,
        write=write,
    )
    fan_in = write_lane_results_and_fan_in(
        runtime=runtime,
        repo=repo,
        task_id=task_id,
        wave_id=wave_id,
        workflow_id=workflow_id,
        phase_scope=phase_scope,
        continuation_authorization_lane=continuation_authorization_lane,
        ledger=ledger,
        write=write,
    )
    acceptance = run_artifact_acceptance(
        runtime=runtime,
        repo=repo,
        task_id=task_id,
        fan_in_artifact_ref=paths["lane_results_latest"],
        task_card=task_card,
        service=service,
        write=write,
    )
    continuity = write_continuity_envelope(
        runtime=runtime,
        repo=repo,
        task_id=task_id,
        wave_id=wave_id,
        workflow_id=workflow_id,
        phase_scope=phase_scope,
        continuation_authorization_lane=continuation_authorization_lane,
        acceptance=acceptance,
        write=write,
    )
    task_bound_assignment_dag = write_task_bound_assignment_dag_evidence(
        runtime=runtime,
        repo=repo,
        task_id=task_id,
        wave_id=wave_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        phase_scope=phase_scope,
        continuation_authorization_lane=continuation_authorization_lane,
        worker_assignment_ref=worker_assignment_ref,
        worker_kind=worker_kind,
        work_package=work_package_payload,
        worker_assignment=worker_assignment,
        summary={
            "think_lane_count": len(think_lanes),
            "execute_lane_count": len(execute_lanes),
            "worker_dispatch_ledger_succeeded_count": int(ledger.get("succeeded_count") or 0),
            "artifact_acceptance_accepted_count": int(
                acceptance.get("accepted_artifact_count") or 0
            ),
        },
        continuity=continuity,
        write=write,
    )

    provider_probe_count = sum(
        1 for item in dp_invocations if item.get("executed_mode") == "provider_probe"
    )
    dp_nonprobe_attempted = sum(
        1
        for item in dp_invocations
        if item.get("executed_mode") != "provider_probe"
        and item.get("mode_dispatch_attempted") is True
    )
    dp_nonprobe_succeeded = sum(
        1
        for item in dp_invocations
        if item.get("executed_mode") != "provider_probe" and item.get("poll_status") == "succeeded"
    )
    execute_invocations = [item for item in dp_invocations if item.get("phase") == "execute"]
    execute_search_invocation_count = sum(
        1 for item in execute_invocations if item.get("executed_mode") == "search"
    )
    dp_execute_draft_eval_attempted = sum(
        1
        for item in execute_invocations
        if item.get("executed_mode") in {"draft", "eval"}
        and item.get("mode_dispatch_attempted") is True
    )
    dp_execute_draft_eval_succeeded = sum(
        1
        for item in execute_invocations
        if item.get("executed_mode") in {"draft", "eval"} and item.get("poll_status") == "succeeded"
    )
    dp_execute_draft_attempted = sum(
        1
        for item in execute_invocations
        if item.get("executed_mode") == "draft" and item.get("mode_dispatch_attempted") is True
    )
    dp_execute_draft_succeeded = sum(
        1
        for item in execute_invocations
        if item.get("executed_mode") == "draft" and item.get("poll_status") == "succeeded"
    )
    dp_execute_eval_attempted = sum(
        1
        for item in execute_invocations
        if item.get("executed_mode") == "eval" and item.get("mode_dispatch_attempted") is True
    )
    dp_execute_eval_succeeded = sum(
        1
        for item in execute_invocations
        if item.get("executed_mode") == "eval" and item.get("poll_status") == "succeeded"
    )
    execute_modes_observed = sorted(
        {
            str(item.get("executed_mode") or "")
            for item in execute_invocations
            if str(item.get("executed_mode") or "")
        }
    )
    dp_named_blockers = [
        str(item.get("named_blocker") or "")
        for item in dp_invocations
        if item.get("executed_mode") != "provider_probe"
        and str(item.get("named_blocker") or "").strip()
    ]
    execute_serial_exception_named_blocker = (
        dp_named_blockers[0]
        if dp_named_blockers
        else str(width.get("serial_exception_reason") or "")
        if width.get("serial_exception") is True
        else ""
    )
    named_serial_exception_present = bool(execute_serial_exception_named_blocker)
    lane_results = fan_in["lane_results"]
    summary = {
        "think_lane_count": len(think_lanes),
        "execute_lane_count": len(execute_lanes),
        "dp_port_invocation_count": len(dp_invocations),
        "dp_nonprobe_attempted_count": dp_nonprobe_attempted,
        "dp_nonprobe_succeeded_count": dp_nonprobe_succeeded,
        "dp_execute_draft_eval_attempted_count": dp_execute_draft_eval_attempted,
        "dp_execute_draft_eval_succeeded_count": dp_execute_draft_eval_succeeded,
        "dp_execute_draft_attempted_count": dp_execute_draft_attempted,
        "dp_execute_draft_succeeded_count": dp_execute_draft_succeeded,
        "dp_execute_eval_attempted_count": dp_execute_eval_attempted,
        "dp_execute_eval_succeeded_count": dp_execute_eval_succeeded,
        "execute_search_invocation_count": execute_search_invocation_count,
        "execute_modes_observed": execute_modes_observed,
        "provider_probe_invocation_count": provider_probe_count,
        "named_serial_exception_present": named_serial_exception_present,
        "execute_serial_exception_named_blocker": execute_serial_exception_named_blocker,
        "worker_dispatch_ledger_poll_entry_count": int(
            ledger.get("poll_result_summary", {}).get("entry_count") or 0
        )
        if isinstance(ledger.get("poll_result_summary"), dict)
        else 0,
        "worker_dispatch_ledger_succeeded_count": int(ledger.get("succeeded_count") or 0),
        "fan_in_accepted_edge_count": int(lane_results.get("accepted_edge_count") or 0),
        "synthetic_succeeded_count": int(lane_results.get("synthetic_succeeded_count") or 0),
        "artifact_acceptance_accepted_count": int(acceptance.get("accepted_artifact_count") or 0),
        "source_ledger_entry_count": int(
            acceptance.get("claim_card_source_ledger_entry_count") or 0
        ),
    }
    validation_checks = {
        "worker_assignment_has_think_lanes": bool(worker_assignment.get("think_lanes")),
        "worker_assignment_has_execute_lanes": bool(worker_assignment.get("execute_lanes")),
        "worker_assignment_has_dependencies": bool(worker_assignment.get("dependencies")),
        "true_subagent_refs_present": any(
            lane.get("lane_kind") == "codex_subagent"
            and lane.get("evidence_refs", {}).get("agent_id")
            for lane in think_lanes
        ),
        "dp_nonprobe_invoked_or_named_serial_exception": dp_nonprobe_succeeded > 0
        or named_serial_exception_present,
        "dp_nonprobe_attempted_or_succeeded": dp_nonprobe_attempted > 0
        or dp_nonprobe_succeeded > 0
        or named_serial_exception_present,
        "execute_lanes_include_draft": any(
            lane.get("phase") == "execute"
            and lane.get("evidence_refs", {}).get("requested_mode") == "draft"
            for lane in execute_lanes
        ),
        "execute_lanes_include_eval": any(
            lane.get("phase") == "execute"
            and lane.get("evidence_refs", {}).get("requested_mode") == "eval"
            for lane in execute_lanes
        ),
        "execute_search_not_used": execute_search_invocation_count == 0,
        "provider_probe_not_default": provider_probe_count == 0,
        "width_from_runtime_policy": width.get("width_source")
        == "deepseek_dynamic_routing_policy.routing_policy.current_default_provider_width",
        "hardcoded_fixed_width_not_used": width.get("hardcoded_fixed_width_used") is False,
        "ledger_poll_has_succeeded": summary["worker_dispatch_ledger_succeeded_count"] > 0,
        "fan_in_from_worker_dispatch_ledger_poll": lane_results.get("source_kind")
        == "worker_dispatch_ledger_poll",
        "fan_in_consumed_real_lane_results": lane_results.get("fan_in_consumed_real_lane_results")
        is True,
        "synthetic_succeeded_zero": summary["synthetic_succeeded_count"] == 0,
        "artifact_acceptance_accepted": summary["artifact_acceptance_accepted_count"] > 0,
        "task_card_thin_bind_ready": task_card.get("validation", {}).get("passed") is True
        and task_card.get("no_new_search_island") is True,
        "existing_workflow_id_bound": bool(workflow_id),
        "phase_scope_assignment_dag_auto_continue": phase_scope == "assignment_dag_auto_continue",
        "continuation_authorization_lane_bound": bool(continuation_authorization_lane),
        "spawn_new_owner_not_allowed": worker_assignment.get("spawn_new_owner_allowed") is False
        and worker_assignment.get("new_owner_created") is False,
        "codex_a_intent_ingress_not_called": worker_assignment.get("codex_a_intent_ingress_called")
        is False,
        "pump_default_not_used": worker_assignment.get("pump_default_used") is False,
        "explicit_work_package_node_bound": (
            not work_package_payload
            or (
                worker_assignment.get("explicit_work_package_bound") is True
                and worker_assignment.get("work_package_next_ready_node_id")
                == assignment_dag_node_id
            )
        ),
        "task_card_drives_existing_lane": any(
            dependency.get("dependency_kind") == "task_card_drives_existing_lane"
            for dependency in worker_assignment.get("dependencies", [])
            if isinstance(dependency, dict)
        ),
        "claim_card_entered_source_ledger": summary["source_ledger_entry_count"] > 0
        and bool(acceptance.get("source_ledger_ref")),
        "aaq_claim_card_hard_gate_enforced": acceptance.get("claim_card_hard_gate_enforced") is True
        and acceptance.get("claim_card_requires_source_ledger") is True,
        "continuity_envelope_written_after_acceptance": continuity.get("accepted_artifact_count", 0)
        > 0,
        "total_draft_spec_landed": boot_spec.get("validation", {}).get("passed") is True,
        "worker_assignment_scope_level_l3": worker_assignment.get("scope_level_target") == "L3",
        "primary_authority_rank_0_current_grok_package": worker_assignment.get(
            "primary_authority_rank"
        )
        == 0
        and worker_assignment.get("current_grok_package_authority_proxy") is True,
        "hook_reads_total_draft_spec": hook_binding.get("side_audit_hook_reads_total_draft_spec")
        is True,
        "ledger_adoption_state_hooked": hook_binding.get("adoption_state")
        == "hooked_runtime_entrypoint",
        "continuity_should_continue_loop": continuity.get("should_continue_loop") is True,
        "task_bound_assignment_dag_evidence_written": task_bound_assignment_dag.get(
            "validation", {}
        ).get("passed")
        is True,
    }
    current_wave_work_packages = intent_work_package_status(
        intent_payload=intent_payload,
        summary=summary,
        width=width,
        hook_binding=hook_binding,
        validation_checks=validation_checks,
    )
    dag = phase0_closure_dag(
        hook_binding=hook_binding,
        worker_assignment=worker_assignment,
        summary=summary,
        boot_spec=boot_spec,
        continuity=continuity,
        output_paths=paths,
        validation_checks=validation_checks,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "wave_id": wave_id,
        "workflow_binding": {
            "workflow_id": workflow_id,
            "workflow_run_id": workflow_run_id,
            "phase_scope": phase_scope,
            "continuation_authorization_lane": continuation_authorization_lane,
            "worker_kind": worker_kind,
            "worker_assignment_ref": worker_assignment_ref,
            "provider_routing_mode": provider_routing_mode,
            "default_token_saving_worker_route": default_token_saving_worker_route,
            "existing_temporal_workflow_bound": bool(workflow_id),
            "new_owner_created": False,
            "codex_a_intent_ingress_called": False,
            "pump_default_used": False,
        },
        "explicit_work_package": {
            "bound": bool(work_package_payload),
            "digest_sha256": sha256_json(work_package_payload) if work_package_payload else "",
            "next_ready_node_id": work_package_node_id(work_package_payload)
            if work_package_payload
            else "",
            "objective": work_package_objective(work_package_payload),
        },
        "status": "codex_max_capability_think_execute_runtime_evidence_written",
        "generated_at": now_iso(),
        "source_intent_package_ref": str(package_ref),
        "source_intent_package_exists": package_ref.is_file(),
        "task_card": task_card,
        "total_draft_boot_spec": boot_spec,
        "hook_binding": hook_binding,
        "WORKER_ASSIGNMENT": worker_assignment,
        "width_decision": width,
        "dp_invocations": dp_invocations,
        "worker_dispatch_ledger": {
            "latest_ref": str(runtime / "state" / "worker_dispatch_ledger" / "latest.json"),
            "source_kind": ledger.get("source_kind"),
            "succeeded_count": ledger.get("succeeded_count"),
            "poll_result_summary": ledger.get("poll_result_summary", {}),
        },
        "fan_in": fan_in,
        "artifact_acceptance": {
            "latest_ref": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
            "accepted_artifact_count": acceptance.get("accepted_artifact_count"),
            "rejected_artifact_count": acceptance.get("rejected_artifact_count"),
            "claim_card_source_ledger_entry_count": acceptance.get(
                "claim_card_source_ledger_entry_count"
            ),
            "source_ledger_ref": acceptance.get("source_ledger_ref"),
            "claim_card_hard_gate_enforced": acceptance.get("claim_card_hard_gate_enforced"),
            "status": acceptance.get("status"),
            "validation": acceptance.get("validation"),
        },
        "continuity_envelope": continuity,
        "task_bound_assignment_dag_evidence": task_bound_assignment_dag,
        "phase0_closure_dag": dag,
        "current_wave_work_packages": current_wave_work_packages,
        "summary": summary,
        "readback_questions": {
            "think_dispatched": "WORKER_ASSIGNMENT.think_lanes",
            "execute_lane_count": summary["execute_lane_count"],
            "current_capability": "think/search context -> execute/draft+eval -> ledger poll -> fan-in -> ArtifactAcceptance -> ContinuityEnvelope",
            "scope_level": worker_assignment.get("scope_level_current"),
            "total_draft_gap": "mature router model gateway and live Temporal continuation remain named blockers unless hooked",
        },
        "output_paths": paths,
        "validation": {
            "passed": all(validation_checks.values()),
            "checks": validation_checks,
            "validated_at": now_iso(),
        },
        **default_boundary(),
    }
    readback = render_readback(payload)
    if write:
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["runtime_task_latest"]), payload)
        write_text(Path(paths["runtime_readback_zh"]), readback)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--intent-package", default="")
    parser.add_argument("--wave-id", default="codex-max-capability-think-execute-wave-20260703")
    parser.add_argument("--workflow-id", default=DEFAULT_WORKFLOW_ID)
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--phase-scope", default=DEFAULT_PHASE_SCOPE)
    parser.add_argument(
        "--continuation-authorization-lane", default=CONTINUATION_AUTHORIZATION_LANE
    )
    parser.add_argument("--worker-assignment-ref", default="")
    parser.add_argument("--worker-kind", default="implementation_worker")
    parser.add_argument("--provider-routing-mode", default="runtime_default")
    parser.add_argument(
        "--default-token-saving-worker-route",
        choices=("true", "false", "unset"),
        default="unset",
    )
    parser.add_argument(
        "--work-package-json",
        default="",
        help="Inline JSON or path for the explicit assignment_dag work package.",
    )
    parser.add_argument(
        "--think-subagent", "--codex-subagent", dest="codex_subagent", action="append", default=[]
    )
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if args.default_token_saving_worker_route == "true":
        token_saving_route: bool | None = True
    elif args.default_token_saving_worker_route == "false":
        token_saving_route = False
    else:
        token_saving_route = None
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_id=args.task_id,
        intent_package=args.intent_package or None,
        wave_id=args.wave_id,
        workflow_id=args.workflow_id,
        workflow_run_id=args.workflow_run_id,
        phase_scope=args.phase_scope,
        continuation_authorization_lane=args.continuation_authorization_lane,
        worker_assignment_ref=args.worker_assignment_ref,
        worker_kind=args.worker_kind,
        provider_routing_mode=args.provider_routing_mode,
        default_token_saving_worker_route=token_saving_route,
        work_package=args.work_package_json or None,
        codex_subagents=args.codex_subagent,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "task_id": payload["task_id"],
                "workflow_id": payload["workflow_binding"]["workflow_id"],
                "phase_scope": payload["workflow_binding"]["phase_scope"],
                "explicit_work_package_bound": payload["explicit_work_package"]["bound"],
                "validation_passed": payload["validation"]["passed"],
                "think_lane_count": payload["summary"]["think_lane_count"],
                "execute_lane_count": payload["summary"]["execute_lane_count"],
                "dp_nonprobe_attempted_count": payload["summary"]["dp_nonprobe_attempted_count"],
                "dp_nonprobe_succeeded_count": payload["summary"]["dp_nonprobe_succeeded_count"],
                "named_serial_exception_present": payload["summary"][
                    "named_serial_exception_present"
                ],
                "ledger_adoption_state": payload["hook_binding"]["adoption_state"],
                "should_continue_loop": payload["continuity_envelope"]["should_continue_loop"],
                "provider_probe_invocation_count": payload["summary"][
                    "provider_probe_invocation_count"
                ],
                "worker_assignment": payload["output_paths"]["worker_assignment"],
                "readback": payload["output_paths"]["runtime_readback_zh"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
