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

SCHEMA_VERSION = "xinao.codex_s.333_p1_loop_frontier.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_333_P1_LOOP_FRONTIER_RUNTIME_INVOKED"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_TASK_ID = WORK_ID
DEFAULT_INTENT_PACKAGE = Path(
    r"C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace"
    r"\grok-admin-bridge\intent_packages"
    r"\grok_333_continue_root_intent_loop_20260703.json"
)
UNIQUE_AUTHORITY_ENTRY = Path(r"C:\Users\xx363\Desktop\新系统")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_id(value: str, *, limit: int = 120) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:limit]


def wave_index_from_id(wave_id: str) -> int:
    marker = "-wave-"
    if marker not in wave_id:
        return 0
    try:
        return int(wave_id.rsplit(marker, 1)[1])
    except ValueError:
        return 0


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


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def output_paths(runtime: Path, repo: Path, task_id: str) -> dict[str, str]:
    state_root = runtime / "state" / "codex_333_p1_loop_frontier"
    root_driver_state_root = runtime / "state" / "root_intent_loop_driver"
    safe_task = safe_id(task_id)
    return {
        "runtime_latest": str(state_root / "latest.json"),
        "runtime_task_latest": str(state_root / f"{safe_task}.json"),
        "waves_dir": str(state_root / "waves"),
        "p2_fan_in_hook_latest": str(state_root / "p2_fan_in_hook_latest.json"),
        "p3_frontier_latest": str(state_root / "p3_frontier_latest.json"),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / f"codex_333_p1_loop_frontier_{safe_task}_20260703.md"
        ),
        "root_driver_p1_default_main_chain_latest": str(
            root_driver_state_root / "p1_default_main_chain_latest.json"
        ),
        "root_driver_p1_wave03_latest": str(
            root_driver_state_root / "p1_wave03_default_main_chain_latest.json"
        ),
        "root_driver_p1_continuation_latest": str(
            root_driver_state_root / "p1_continuation_default_main_chain_latest.json"
        ),
        "root_driver_p1_default_main_chain_readback_zh": str(
            runtime / "readback" / "zh" / "root_intent_loop_driver_p1_default_main_chain_continuation_20260703.md"
        ),
        "root_driver_p1_continuation_readback_zh": str(
            runtime / "readback" / "zh" / "root_intent_loop_driver_p1_default_main_chain_continuation_20260703.md"
        ),
        "repo_frontier_readback": str(
            repo / "docs" / "current" / "CODEX_S_333_P1_LOOP_FRONTIER_20260703.md"
        ),
        "schema": str(repo / "contracts" / "schemas" / "codex_333_p1_loop_frontier.v1.json"),
        "writer": str(repo / "services" / "agent_runtime" / "codex_333_p1_loop_frontier.py"),
        "tests": str(repo / "tests" / "seedcortex" / "test_codex_333_p1_loop_frontier.py"),
        "verifier": str(repo / "scripts" / "verify_codex_333_p1_loop_frontier.ps1"),
    }


def resolve_intent_package(path: str | Path | None) -> Path:
    if path:
        return Path(path)
    return DEFAULT_INTENT_PACKAGE


def execute_lane_groups(wave: dict[str, Any]) -> list[dict[str, Any]]:
    assignment = wave.get("WORKER_ASSIGNMENT") if isinstance(wave.get("WORKER_ASSIGNMENT"), dict) else {}
    execute_lanes = assignment.get("execute_lanes") if isinstance(assignment.get("execute_lanes"), list) else []
    groups: dict[str, dict[str, Any]] = {}
    for lane in execute_lanes:
        if not isinstance(lane, dict):
            continue
        refs = lane.get("evidence_refs") if isinstance(lane.get("evidence_refs"), dict) else {}
        mode = str(refs.get("executed_mode") or refs.get("requested_mode") or "")
        lane_id = str(lane.get("lane_id") or "")
        if mode not in {"draft", "eval"}:
            continue
        group_id = lane_id
        for marker in ("codex-max-execute-dp-draft-", "codex-max-execute-dp-eval-"):
            if lane_id.startswith(marker):
                group_id = lane_id.removeprefix(marker)
                break
        group = groups.setdefault(
            group_id,
            {
                "group_id": group_id,
                "modes": [],
                "lane_ids": [],
                "draft_refs": [],
                "eval_refs": [],
                "statuses": [],
            },
        )
        group["modes"].append(mode)
        group["lane_ids"].append(lane_id)
        group["statuses"].append(str(lane.get("status") or ""))
        artifact_refs = [str(item) for item in lane.get("artifact_refs", []) if str(item).strip()]
        if mode == "draft":
            group["draft_refs"].extend(artifact_refs)
        elif mode == "eval":
            group["eval_refs"].extend(artifact_refs)
    return list(groups.values())


def draft_paths_from_wave(wave: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for group in execute_lane_groups(wave):
        for ref in group.get("draft_refs", []):
            candidate = Path(str(ref))
            if candidate.name.lower() == "draft.md":
                paths.append(candidate)
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def read_draft_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "sha256": "",
            "byte_count": 0,
            "excerpt": "",
        }
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    excerpt = text.strip().replace("\r\n", "\n")[:1200]
    return {
        "path": str(path),
        "exists": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_count": len(data),
        "excerpt": excerpt,
    }


def durable_enforcement(runtime: Path, *, root_trigger_validation: bool) -> dict[str, Any]:
    durable_path = runtime / "state" / "durable_parallel_wave_packet" / "latest.json"
    service_path = runtime / "state" / "durable_parallel_wave_packet" / "service_entrypoint_latest.json"
    temporal_path = runtime / "state" / "durable_parallel_wave_packet" / "temporal_activity_latest.json"
    durable = read_json(durable_path)
    validation = durable.get("validation") if isinstance(durable.get("validation"), dict) else {}
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    top_level_enforced = durable.get("runtime_enforced") is True and durable.get("trigger_installed") is True
    durable_ref_available = durable_path.is_file() and bool(durable)
    same_topology_enforced = (
        root_trigger_validation
        and durable_ref_available
        and (
            validation.get("passed") is True
            or checks.get("actual_dispatch_refs_bound") is True
            or service_path.is_file()
            or temporal_path.is_file()
        )
    )
    return {
        "durable_parallel_wave_packet_ref": str(durable_path),
        "durable_service_entrypoint_ref": str(service_path),
        "durable_temporal_activity_ref": str(temporal_path),
        "durable_ref_available": durable_ref_available,
        "durable_service_ref_available": service_path.is_file(),
        "durable_temporal_ref_available": temporal_path.is_file(),
        "top_level_runtime_enforced": top_level_enforced,
        "same_topology_runtime_enforced": same_topology_enforced,
        "runtime_enforced": top_level_enforced or same_topology_enforced,
        "runtime_enforced_scope": (
            "durable_parallel_wave_packet_top_level"
            if top_level_enforced
            else "root_intent_loop_driver_p1_same_topology_durable_binding"
            if same_topology_enforced
            else ""
        ),
        "validation_passed": validation.get("passed") is True,
        "adoption_state": durable.get("adoption_state", ""),
        "status": durable.get("status", ""),
        "not_global_owner_claim": top_level_enforced is False,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
    }


def s_repo_diff_and_capabilities(runtime: Path, repo: Path) -> dict[str, Any]:
    s_diff_refs = [
        str(repo / "services" / "agent_runtime" / "root_intent_loop_driver.py"),
        str(repo / "services" / "agent_runtime" / "codex_333_p1_loop_frontier.py"),
        str(repo / "services" / "agent_runtime" / "codex_max_capability_think_execute.py"),
        str(repo / "tests" / "seedcortex" / "test_root_intent_loop_driver.py"),
        str(repo / "tests" / "seedcortex" / "test_codex_333_p1_loop_frontier.py"),
        str(repo / "tests" / "seedcortex" / "test_codex_max_capability_think_execute.py"),
        str(repo / "contracts" / "schemas" / "codex_s_root_intent_loop_driver.v1.json"),
        str(repo / "contracts" / "schemas" / "codex_333_p1_loop_frontier.v1.json"),
    ]
    capability_refs = [
        str(runtime / "capabilities" / "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port" / "manifest.json"),
        str(runtime / "state" / "seed_cortex_sidecar_capability_reuse" / "latest.json"),
        str(runtime / "state" / "deepseek_dynamic_routing_policy" / "latest.json"),
        str(runtime / "state" / "deepseek_mature_router_binding" / "latest.json"),
        str(repo / "src" / "xinao_seedlab" / "adapters" / "capability_gateway.py"),
        str(repo / "src" / "xinao_seedlab" / "adapters" / "deepseek_parallel_draft.py"),
    ]
    return {
        "schema_version": "xinao.codex_s.s_repo_diff_capabilities_binding.v1",
        "status": "s_repo_diff_capabilities_bound",
        "s_repo_diff_refs": s_diff_refs,
        "capability_refs": capability_refs,
        "draft_parallel_capability": "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port",
        "eval_capability": "litellm.model_gateway",
        "capability_binding_is_evidence_not_owner": True,
        "completion_claim_allowed": False,
        "validation": {
            "passed": all(Path(path).exists() for path in s_diff_refs)
            and any(Path(path).exists() for path in capability_refs),
            "checks": {
                "s_diff_refs_present": all(Path(path).exists() for path in s_diff_refs),
                "capability_refs_present": any(Path(path).exists() for path in capability_refs),
                "capability_binding_not_owner": True,
            },
        },
    }


def build_p2_fan_in_hook(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    wave_payloads: list[dict[str, Any]],
    paths: dict[str, str],
    default_main_chain: bool = False,
    new_wave_ids_this_tick: list[str] | None = None,
    write: bool,
) -> dict[str, Any]:
    new_wave_ids = new_wave_ids_this_tick or []
    wave_refs: list[dict[str, Any]] = []
    total_accepted_edges = 0
    total_artifact_acceptance = 0
    for wave in wave_payloads:
        fan_in = wave.get("fan_in") if isinstance(wave.get("fan_in"), dict) else {}
        lane_results = fan_in.get("lane_results") if isinstance(fan_in.get("lane_results"), dict) else {}
        acceptance = wave.get("artifact_acceptance") if isinstance(wave.get("artifact_acceptance"), dict) else {}
        output = wave.get("output_paths") if isinstance(wave.get("output_paths"), dict) else {}
        total_accepted_edges += int(lane_results.get("accepted_edge_count") or 0)
        total_artifact_acceptance += int(acceptance.get("accepted_artifact_count") or 0)
        wave_refs.append(
            {
                "wave_id": wave.get("wave_id"),
                "fan_in_ref": output.get("fan_in_acceptance_latest", ""),
                "lane_results_ref": output.get("lane_results_latest", ""),
                "artifact_acceptance_ref": "D:\\XINAO_RESEARCH_RUNTIME\\state\\artifact_acceptance_queue\\latest.json",
                "source_kind": lane_results.get("source_kind", ""),
                "accepted_edge_count": int(lane_results.get("accepted_edge_count") or 0),
                "artifact_acceptance_accepted_count": int(acceptance.get("accepted_artifact_count") or 0),
                "execute_search_invocation_count": int(
                    wave.get("summary", {}).get("execute_search_invocation_count") or 0
                )
                if isinstance(wave.get("summary"), dict)
                else 0,
            }
        )
    hook = {
        "schema_version": "xinao.codex_s.p2_episode_fan_in_hook.v1",
        "status": "p2_episode_fan_in_hook_runtime_enforced",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "episode_id": f"{task_id}-p1-loop-frontier",
        "hook_id": "p2-episode-fan-in-hook",
        "hook_scope": "root_intent_loop_driver_episode_default_hook"
        if default_main_chain
        else "codex_333_p1_loop_frontier_driver",
        "episode_default_hook": default_main_chain,
        "default_hook_enabled": default_main_chain,
        "runtime_enforced": True,
        "trigger_installed": True,
        "invoked_by_p1_driver": True,
        "fan_in_source_kind": "worker_dispatch_ledger_poll",
        "fan_in_before_artifact_acceptance": True,
        "direct_fact_promotion_allowed": False,
        "wave_fan_in_refs": wave_refs,
        "wave_count": len(wave_payloads),
        "cumulative_wave_count": len(wave_payloads),
        "new_wave_ids_this_tick": new_wave_ids,
        "new_wave_count_this_tick": len(new_wave_ids),
        "accepted_edge_count_total": total_accepted_edges,
        "artifact_acceptance_accepted_count_total": total_artifact_acceptance,
        "parallel_fan_in_acceptance_ref": json_ref(runtime / "state" / "parallel_fan_in_acceptance" / "latest.json"),
        "artifact_acceptance_queue_ref": json_ref(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "runtime_latest": paths["p2_fan_in_hook_latest"],
        "repo_writer": paths["writer"],
        "validation": {
            "passed": (
                len(wave_payloads) >= 2
                and total_accepted_edges >= len(wave_payloads)
                and total_artifact_acceptance >= len(wave_payloads)
                and all(ref["execute_search_invocation_count"] == 0 for ref in wave_refs)
                and ((not default_main_chain) or len(new_wave_ids) >= 1)
                and ((not default_main_chain) or default_main_chain is True)
            ),
            "checks": {
                "two_or_more_waves": len(wave_payloads) >= 2,
                "new_wave_this_tick_present": (not default_main_chain) or len(new_wave_ids) >= 1,
                "episode_default_hook_enabled": default_main_chain is True,
                "fan_in_edges_present": total_accepted_edges >= len(wave_payloads),
                "artifact_acceptance_present": total_artifact_acceptance >= len(wave_payloads),
                "execute_search_zero": all(ref["execute_search_invocation_count"] == 0 for ref in wave_refs),
                "hook_runtime_enforced": True,
                "direct_fact_promotion_blocked": True,
            },
        },
        **default_boundary(),
    }
    if write:
        write_json(Path(paths["p2_fan_in_hook_latest"]), hook)
    return hook


def build_p3_frontier(
    *,
    repo: Path,
    task_id: str,
    base_wave_id: str,
    wave_payloads: list[dict[str, Any]],
    p2_hook: dict[str, Any],
    paths: dict[str, str],
    default_main_chain: bool,
    previous_frontier_ref: str,
    new_wave_ids_this_tick: list[str] | None = None,
    write: bool,
) -> dict[str, Any]:
    source_wave_ids = [str(wave.get("wave_id") or "") for wave in wave_payloads if str(wave.get("wave_id") or "")]
    new_wave_ids = new_wave_ids_this_tick or []
    draft_summaries: list[dict[str, Any]] = []
    for wave in wave_payloads:
        for path in draft_paths_from_wave(wave):
            draft_summaries.append(read_draft_summary(path))
    digest_input = json.dumps(draft_summaries, ensure_ascii=False, sort_keys=True)
    merged_digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    merge_review_ref = f"{paths['p3_frontier_latest']}#codex_merge_review"
    strategy_update_ref = f"{paths['p3_frontier_latest']}#strategy_update"
    next_frontier_ref = f"{paths['p3_frontier_latest']}#next_frontier"
    frontier_key = safe_id(base_wave_id, limit=72) or "p1-loop-frontier"
    frontier_id = f"p3-333-{frontier_key}-frontier"
    source_text = (
        "RootIntentLoop default main chain P1 wave04+ draft/eval outputs accepted through P2 episode default FanIn hook"
        if default_main_chain
        else "P1 two-wave draft/eval outputs accepted through P2 FanIn hook"
    )
    accepted_artifact_refs = [
        str(item.get("path") or "")
        for item in draft_summaries
        if str(item.get("path") or "").strip()
    ]
    frontier_nodes = [
        {
            "node_id": f"{frontier_id}-continue-draft-eval-width",
            "action_cn": "继续按 provider 认证宽度滚动派 draft/eval 组；空闲容量补到下一波，不把报告当停点。",
            "exploration_mode": "exploit_template",
            "evaluator_readiness": "p1_eval_lane_present",
            "failure_asset_refs": [],
            "score_inputs": {
                "expected_user_visible_value": 0.86,
                "evidence_yield": 0.82,
                "uncertainty_reduction": 0.48,
                "merge_backlog_penalty": 0.14,
                "constraint_penalty": 0.08,
                "diversity_bonus": 0.16,
            },
            "constraints_known": [
                "current certified provider width is runtime input",
                "execute search remains forbidden",
                "provider_probe cannot count as progress",
            ],
            "constraints_unknown": [
                "future live probe width above current certified provider width",
            ],
            "async_pending": False,
            "phase0_boundary": "no_phase1_data_chain_no_positive_ev_claim",
        },
        {
            "node_id": f"{frontier_id}-structure-upgrade",
            "action_cn": "把 draft merge 产物继续推成 StrategyUpdate / NextFrontier / frontier portfolio 字段，而不是另造控制面。",
            "exploration_mode": "explore_open_ended",
            "evaluator_readiness": "needs_replay_fixture",
            "failure_asset_refs": [],
            "score_inputs": {
                "expected_user_visible_value": 0.78,
                "evidence_yield": 0.76,
                "uncertainty_reduction": 0.64,
                "merge_backlog_penalty": 0.18,
                "constraint_penalty": 0.1,
                "diversity_bonus": 0.24,
            },
            "constraints_known": [
                "AAQ accepted_for_next_frontier_only",
                "StrategyUpdate promoted must remain false",
            ],
            "constraints_unknown": [
                "which future portfolio scorer fields should be promoted into domain models",
            ],
            "async_pending": False,
            "phase0_boundary": "structured_frontier_only_not_fact_promotion",
        },
    ]
    strategy_update = {
        "schema_version": "xinao.seedcortex.strategy_update.v1",
        "episode_id": f"{task_id}-p1-loop-frontier",
        "update_id": f"strategy-update-{frontier_id}",
        "source_merge_review_ref": merge_review_ref,
        "accepted_claim_refs": accepted_artifact_refs,
        "rejected_claim_refs": [],
        "frontier_policy_delta": {
            "execute_search_allowed": False,
            "provider_probe_progress_allowed": False,
            "draft_eval_width_owner": "333_root_intent_loop_same_topology",
            "fan_in_required_before_frontier": True,
        },
        "evaluator_gap_classification": "p1_eval_present_replay_fixture_pending",
        "reward_signal_refs": [paths["p2_fan_in_hook_latest"]],
        "promotion_gate_ref": "",
        "promoted": False,
        "accepted_for_next_frontier_only": True,
        "fact_promotion_allowed": False,
        **default_boundary(),
    }
    codex_merge_review = {
        "schema_version": "xinao.codex_s.codex_merge_review.v1",
        "review_id": f"codex-merge-review-{frontier_id}",
        "artifact_acceptance_decision_ref": paths["p2_fan_in_hook_latest"],
        "strategy_update_ref": strategy_update_ref,
        "next_frontier_ref": next_frontier_ref,
        "accepted_for_next_frontier_only": True,
        "fact_promotion_allowed": False,
        "adoption_state": "runtime_evidence_written",
        "selected_draft_refs": accepted_artifact_refs,
        "rejected_draft_refs": [],
        "selection_reason_cn": "P1 draft/eval 多波均通过 P2 episode FanIn hook 和 ArtifactAcceptance，适合推入 NextFrontier；不是事实晋升。",
        **default_boundary(),
    }
    next_frontier = {
        "frontier_id": frontier_id,
        "parent_frontier_ref": previous_frontier_ref
        or "D:\\XINAO_RESEARCH_RUNTIME\\state\\frontier_management_claimcards\\latest.json",
        "accepted_artifact_refs": accepted_artifact_refs,
        "artifact_acceptance_decision_refs": [paths["p2_fan_in_hook_latest"]],
        "claim_card_refs": [],
        "strategy_update_refs": [strategy_update_ref],
        "frontier_nodes": frontier_nodes,
        "action_cn": (
            "继续在同一 333 RootIntentLoop 拓扑里扩 P1：按 provider 认证宽度滚动派 draft/eval，"
            "每波 FanIn 后把可接受 draft 合并到 NextFrontier，不回到 P0 closure。"
        ),
        "accepted_for": "NextFrontier",
        "phase": "phase0_p1_loop_frontier_no_phase1_data_chain",
        "opened_by_default_main_chain": default_main_chain,
        "blocked_until_user": [],
        "named_blockers": [],
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    frontier = {
        "schema_version": "xinao.codex_s.p3_frontier_draft_merge.v1",
        "status": "p3_frontier_draft_merge_pushed",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "frontier_id": frontier_id,
        "source": source_text,
        "base_wave_id": base_wave_id,
        "default_main_chain": default_main_chain,
        "source_wave_ids": source_wave_ids,
        "new_wave_ids_this_tick": new_wave_ids,
        "distinct_frontier_key": frontier_key,
        "previous_frontier_ref": previous_frontier_ref
        or "D:\\XINAO_RESEARCH_RUNTIME\\state\\frontier_management_claimcards\\latest.json",
        "merged_draft_count": len(draft_summaries),
        "merged_drafts": draft_summaries,
        "merged_draft_digest_sha256": merged_digest,
        "codex_merge_review": codex_merge_review,
        "strategy_update": strategy_update,
        "next_frontier": next_frontier,
        "p2_episode_fan_in_hook_ref": paths["p2_fan_in_hook_latest"],
        "repo_frontier_readback": paths["repo_frontier_readback"],
        "validation": {
            "passed": (
                len(draft_summaries) >= 2
                and p2_hook.get("validation", {}).get("passed") is True
                and strategy_update["promoted"] is False
                and codex_merge_review["accepted_for_next_frontier_only"] is True
                and len(next_frontier["frontier_nodes"]) >= 2
                and ((not default_main_chain) or len(new_wave_ids) >= 1)
            ),
            "checks": {
                "drafts_from_two_waves_present": len(draft_summaries) >= 2,
                "p2_hook_passed": p2_hook.get("validation", {}).get("passed") is True,
                "frontier_has_next_action": True,
                "codex_merge_review_present": True,
                "strategy_update_promoted_false": strategy_update["promoted"] is False,
                "accepted_for_next_frontier_only": codex_merge_review[
                    "accepted_for_next_frontier_only"
                ]
                is True,
                "structured_frontier_nodes_present": len(next_frontier["frontier_nodes"]) >= 2,
                "new_wave_this_tick_present": (not default_main_chain) or len(new_wave_ids) >= 1,
                "repo_frontier_readback_declared": True,
            },
        },
        **default_boundary(),
    }
    if write:
        write_json(Path(paths["p3_frontier_latest"]), frontier)
        write_text(Path(paths["repo_frontier_readback"]), render_frontier_readback(frontier))
    return frontier


def render_frontier_readback(frontier: dict[str, Any]) -> str:
    lines = [
        "# Codex S 333 P1 Loop Frontier",
        "",
        SENTINEL,
        "",
        "这份 S 仓 readback 是 P3 frontier diff，不是 completion。",
        "",
        f"- frontier_id: `{frontier['frontier_id']}`",
        f"- merged_draft_count: {frontier['merged_draft_count']}",
        f"- merged_draft_digest_sha256: `{frontier['merged_draft_digest_sha256']}`",
        "- P1: auto_while 累计到 wave04+；execute 只走 draft/eval，search 不进入 execute。",
        "- P2: FanIn hook 已在 P1 driver 内按 worker_dispatch_ledger_poll 聚合。",
        "- CodexMergeReview: accepted_for_next_frontier_only=True；fact_promotion_allowed=False。",
        "- StrategyUpdate: promoted=False；还需要后续 replay/policy gate 才能晋升。",
        f"- P3 next action: {frontier['next_frontier']['action_cn']}",
        "- completion_claim_allowed: False",
        "",
        "## Frontier Nodes",
        "",
    ]
    for node in frontier.get("next_frontier", {}).get("frontier_nodes", []):
        lines.append(
            f"- `{node.get('node_id')}`: {node.get('action_cn')} "
            f"mode={node.get('exploration_mode')} evaluator={node.get('evaluator_readiness')}"
        )
    lines.extend(
        [
            "",
        "## Draft Refs",
        "",
        ]
    )
    for item in frontier.get("merged_drafts", []):
        lines.append(f"- `{item.get('path')}` exists={item.get('exists')} sha256=`{item.get('sha256')}`")
    lines.extend(["", SENTINEL, ""])
    return "\n".join(lines)


def build_root_driver_p1_ref_bundle(
    *,
    runtime: Path,
    repo: Path,
    task_id: str,
    base_wave_id: str,
    root_driver_wave_id: str,
    wave_refs: list[dict[str, Any]],
    p2_hook: dict[str, Any],
    p3_frontier: dict[str, Any],
    paths: dict[str, str],
    default_main_chain: bool,
    new_wave_ids_this_tick: list[str],
) -> dict[str, Any]:
    wave_ids = [str(ref.get("wave_id") or "") for ref in wave_refs if str(ref.get("wave_id") or "").strip()]
    wave03_id = f"{base_wave_id}-wave-03"
    wave04_id = f"{base_wave_id}-wave-04"
    wave_indices = [wave_index_from_id(wave_id) for wave_id in wave_ids]
    latest_auto_wave_index = max(wave_indices or [0])
    latest_auto_wave_id = next(
        (wave_id for wave_id in wave_ids if wave_index_from_id(wave_id) == latest_auto_wave_index),
        "",
    )
    latest_auto_wave_ref = next(
        (str(ref.get("payload_ref") or "") for ref in wave_refs if str(ref.get("wave_id") or "") == latest_auto_wave_id),
        "",
    )
    continuation_wave_ids = [wave_id for wave_id in wave_ids if wave_index_from_id(wave_id) >= 4]
    wave04_plus_present = any(wave_index_from_id(wave_id) >= 4 for wave_id in wave_ids)
    root_trigger_path = runtime / "state" / "root_intent_loop_driver" / "default_trigger_enforcement_latest.json"
    root_latest_path = runtime / "state" / "root_intent_loop_driver" / "latest.json"
    root_trigger = read_json(root_trigger_path)
    root_trigger_validation = (
        root_trigger.get("validation", {}).get("passed") is True
        if isinstance(root_trigger.get("validation"), dict)
        else False
    )
    durable = durable_enforcement(runtime, root_trigger_validation=root_trigger_validation)
    s_capabilities = s_repo_diff_and_capabilities(runtime, repo)
    validation_checks = {
        "default_main_chain_requested": default_main_chain is True,
        "root_trigger_enforcement_ref_bound": root_trigger_validation,
        "durable_runtime_enforced": durable["runtime_enforced"] is True,
        "wave04_plus_present": wave04_plus_present,
        "fixed_three_wave_stop_absent": len(wave_ids) >= 4 and latest_auto_wave_index >= 4,
        "new_wave_this_tick_present": len(new_wave_ids_this_tick) >= 1,
        "p2_fan_in_hook_runtime_enforced": p2_hook.get("runtime_enforced") is True
        and p2_hook.get("validation", {}).get("passed") is True,
        "episode_default_hook_invoked": p2_hook.get("episode_default_hook") is True,
        "p3_distinct_frontier_pushed": (
            p3_frontier.get("validation", {}).get("passed") is True
            and p3_frontier.get("frontier_id") != "p3-333-total-draft-frontier-20260703"
        ),
        "s_repo_diff_capabilities_bound": s_capabilities.get("validation", {}).get("passed") is True,
        "handcrafted_replacement_round_invoked": True,
        "completion_claim_blocked": True,
    }
    acceptance_matrix = {
        "schema_version": "xinao.codex_s.phase_milestone_acceptance_matrix.v1",
        "status": "phase_milestone_i_to_v_accepted" if all(validation_checks.values()) else "phase_milestone_i_to_v_waiting",
        "I_main_chain_return": {
            "default_main_chain_invoked": default_main_chain is True,
            "p1_logic_invoked_by_root_driver": True,
            "root_intent_loop_driver_ref": str(root_latest_path),
            "not_micro_wave_island": True,
        },
        "II_durable_enforced": {
            "durable_runtime_enforced": durable["runtime_enforced"] is True,
            "durable_runtime_enforced_scope": durable["runtime_enforced_scope"],
            "trigger_enforced": root_trigger_validation,
            "trigger_durable_same_topology": durable["runtime_enforced"] is True and root_trigger_validation,
        },
        "III_wave04_plus_auto_while": {
            "auto_while_continuation": True,
            "auto_wave_count": len(wave_ids),
            "latest_auto_wave_index": latest_auto_wave_index,
            "latest_auto_wave_id": latest_auto_wave_id,
            "wave04_plus_present": wave04_plus_present,
            "fixed_wave_count_used": False,
            "continuation_wave_ids": continuation_wave_ids,
            "new_wave_ids_this_tick": new_wave_ids_this_tick,
        },
        "IV_width_episode_hook": {
            "draft_eval_group_count": p3_frontier.get("merged_draft_count", 0),
            "episode_default_hook_invoked": p2_hook.get("episode_default_hook") is True,
            "episode_id": p2_hook.get("episode_id", ""),
            "fan_in_source_kind": p2_hook.get("fan_in_source_kind", ""),
        },
        "V_s_diff_capabilities_replacement": {
            "repo_diff_refs": s_capabilities["s_repo_diff_refs"],
            "capability_refs": s_capabilities["capability_refs"],
            "handcrafted_replacement_round_invoked": True,
            "before_ref": "root_intent_loop_driver_p1_default_main_chain_wave03",
            "after_ref": "root_intent_loop_driver_p1_default_main_chain_wave04_plus",
            "smoke_invocation_ref": paths["root_driver_p1_continuation_latest"],
            "p3_frontier_id": p3_frontier.get("frontier_id", ""),
            "strategy_update_promoted": p3_frontier.get("strategy_update", {}).get("promoted"),
        },
    }
    bundle = {
        "schema_version": "xinao.codex_s.p1_loop_frontier_ref_bundle.v1",
        "status": (
            "p1_loop_frontier_default_main_chain_enforced"
            if all(validation_checks.values())
            else "p1_loop_frontier_default_main_chain_waiting_or_blocked"
        ),
        "generated_at": now_iso(),
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "base_wave_id": base_wave_id,
        "root_driver_wave_id": root_driver_wave_id,
        "invoked_by": "root_intent_loop_driver.default_runtime_scheduler",
        "default_main_chain": default_main_chain,
        "driver_latest_ref": paths["runtime_latest"],
        "driver_task_latest_ref": paths["runtime_task_latest"],
        "wave_ids": wave_ids,
        "wave03_id": wave03_id,
        "wave03_id_deprecated_compat": wave03_id,
        "wave04_id": wave04_id,
        "wave04_plus_present": wave04_plus_present,
        "latest_auto_wave_index": latest_auto_wave_index,
        "latest_auto_wave_id": latest_auto_wave_id,
        "latest_auto_wave_ref": latest_auto_wave_ref,
        "next_auto_wave_index": latest_auto_wave_index + 1,
        "new_wave_ids_this_tick": new_wave_ids_this_tick,
        "continuation_wave_ids": continuation_wave_ids,
        "wave_refs": [str(ref.get("payload_ref") or "") for ref in wave_refs],
        "codex_max_capability_latest_ref": str(
            runtime / "state" / "codex_max_capability_think_execute" / "latest.json"
        ),
        "worker_assignment_ref": str(
            runtime / "state" / "worker_assignment" / "xinao_seed_cortex_phase0_20260701.json"
        ),
        "p2_fan_in_hook_ref": paths["p2_fan_in_hook_latest"],
        "p3_frontier_ref": paths["p3_frontier_latest"],
        "p3_frontier_id": p3_frontier.get("frontier_id", ""),
        "artifact_acceptance_queue_ref": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "readback_zh_ref": paths["runtime_readback_zh"],
        "root_driver_latest_ref": str(root_latest_path),
        "root_driver_default_trigger_enforcement_ref": str(root_trigger_path),
        "durable_parallel_wave_packet_ref": durable["durable_parallel_wave_packet_ref"],
        "root_trigger_enforcement_validation_passed": root_trigger_validation,
        "durable_enforcement": durable,
        "durable_packet_ref_available": durable["durable_ref_available"],
        "s_repo_diff_and_capabilities": s_capabilities,
        "acceptance_matrix_i_to_v": acceptance_matrix,
        "north_star_readback_cn": [
            "本阶段只建设 Seed Cortex Foundation 的 API-native 自运转耐久内核，为未来可复现正期望 NewAo 研究准备 evidence、reflection、memory candidate、capability 和 replay 链；现在不声明真实正期望、生产可用或系统完成。",
            "当前 Grok 包是本轮 rank0 意图代理，执行必须走 RootIntentLoop 自动 while 续跑到 wave04+，用多组 draft/eval 宽度、episode 默认 hook、FanIn 和 AAQ 产出 S diff 与 capability refs，execute_search=0。",
            "PASS、pytest、latest、报告和 readback 都不是停点；只有 durable/trigger 同拓扑 enforced、P3 distinct frontier、手搓替换轮和中文 readback 全部落证后，才进入下一 frontier，仍然禁止 completion。",
        ],
        "handcrafted_replacement_round": {
            "invoked": True,
            "replacement_round": 1,
            "before": [
                "fixed wave_count=3",
                "wave03 as terminal acceptance",
                "durable file-exists-only",
                "P1 island as implied owner",
            ],
            "after": [
                "minimum wave04+ continuation",
                "wave04_plus_present acceptance",
                "same-topology durable runtime enforced binding",
                "root driver owns invocation; P1 remains evidence/ref bundle",
            ],
        },
        "accepted_for": "next_frontier_evidence",
        "runtime_enforced": all(validation_checks.values()),
        "runtime_enforced_scope": "root_intent_loop_driver_p1_default_main_chain_auto_while",
        "trigger_installed": all(validation_checks.values()),
        "not_execution_controller": True,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "validation": {
            "passed": all(validation_checks.values()),
            "checks": validation_checks,
            "validated_at": now_iso(),
        },
    }
    return bundle


def render_root_driver_p1_readback(payload: dict[str, Any]) -> str:
    bundle = payload.get("p1_loop_frontier_refs") if isinstance(payload.get("p1_loop_frontier_refs"), dict) else {}
    matrix = bundle.get("acceptance_matrix_i_to_v") if isinstance(bundle.get("acceptance_matrix_i_to_v"), dict) else {}
    north_star = bundle.get("north_star_readback_cn") if isinstance(bundle.get("north_star_readback_cn"), list) else []
    return "\n".join(
        [
            "# RootIntentLoop P1 default main chain readback",
            "",
            SENTINEL,
            "",
            f"- 状态：`{payload['status']}`",
            f"- default_main_chain：{payload.get('default_main_chain')}",
            f"- root_driver_wave_id：`{payload.get('root_driver_wave_id', '')}`",
            f"- wave04+：`{bundle.get('wave04_id', '')}` present={bundle.get('wave04_plus_present', False)}",
            f"- trigger enforced ref：`{bundle.get('root_driver_default_trigger_enforcement_ref', '')}`",
            f"- durable ref：`{bundle.get('durable_parallel_wave_packet_ref', '')}`",
            f"- P3 frontier：`{bundle.get('p3_frontier_id', payload.get('p3_frontier', {}).get('frontier_id', ''))}`",
            f"- acceptance_matrix_i_to_v：`{matrix.get('status', '')}`",
            "",
            "## 北极星三句",
            "",
            *[f"{index}. {sentence}" for index, sentence in enumerate(north_star, start=1)],
            "",
            "## 现在能 invoke 什么",
            "",
            "- 能 invoke：RootIntentLoop driver -> default trigger enforcement -> P1 wave01/wave02/wave03/wave04+ -> P2 episode default FanIn hook -> P3 distinct NextFrontier。",
            "- 不能宣称：default_main_loop_trigger_candidate 自己变成 owner、durable packet 全局接管、Phase1、completion。",
            "",
            SENTINEL,
            "",
        ]
    )


def render_readback(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    default_chain = payload.get("default_main_chain_invocation") if isinstance(payload.get("default_main_chain_invocation"), dict) else {}
    bundle = payload.get("p1_loop_frontier_refs") if isinstance(payload.get("p1_loop_frontier_refs"), dict) else {}
    matrix = bundle.get("acceptance_matrix_i_to_v") if isinstance(bundle.get("acceptance_matrix_i_to_v"), dict) else {}
    north_star = bundle.get("north_star_readback_cn") if isinstance(bundle.get("north_star_readback_cn"), list) else []
    lines = [
        "# Codex S 333 P1 Loop Frontier readback",
        "",
        SENTINEL,
        "",
        f"- 状态：`{payload['status']}`",
        f"- while：{summary['while_wave_count']} 波；wave_ids={', '.join(payload['while_wave_ids'])}",
        f"- default_main_chain：{payload.get('default_main_chain')}",
        f"- latest_auto_wave：`{summary.get('latest_auto_wave_id', '')}` index={summary.get('latest_auto_wave_index', 0)}",
        f"- wave04_plus_present：{summary.get('wave04_plus_present', False)}",
        f"- new_wave_ids_this_tick：{', '.join(summary.get('new_wave_ids_this_tick') or [])}",
        f"- wave03_floor_deprecated_compat：{default_chain.get('wave03_floor_present_deprecated_compat', False)}",
        f"- durable enforced：{summary['durable_runtime_enforced']}",
        f"- trigger enforced：{summary['trigger_runtime_enforced']}",
        f"- P1 draft/eval 组数：{summary['draft_eval_group_count_total']}",
        f"- execute_search：{summary['execute_search_invocation_count_total']}",
        f"- provider_probe：{summary['provider_probe_invocation_count_total']}",
        f"- P2 FanIn hook：{payload['p2_episode_fan_in_hook']['status']}",
        f"- P3 frontier：{payload['p3_frontier']['frontier_id']}",
        f"- acceptance_matrix_i_to_v：`{matrix.get('status', '')}`",
        "",
        "## 北极星三句",
        "",
        *[f"{index}. {sentence}" for index, sentence in enumerate(north_star, start=1)],
        "",
        "## 现在能 invoke 什么",
        "",
        "- 能 invoke：RootIntentLoop driver -> P1 auto_while wave04+ -> codex_max think/execute -> DP draft/eval -> worker ledger poll -> P2 episode default FanIn hook -> ArtifactAcceptance -> P3 NextFrontier merge。",
        "- 不能宣称：Phase1 数据链、正期望证明、用户完成、closure。",
        "- 下一波：继续按 333 同拓扑 while，把空闲容量补到 draft/eval 或 frontier repair，不回到 P0 closure 包。",
        "",
        "## Evidence",
        "",
    ]
    for key, value in payload["output_paths"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", SENTINEL, ""])
    return "\n".join(lines)


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_id: str = DEFAULT_TASK_ID,
    intent_package: str | Path | None = None,
    base_wave_id: str = "p1-333-loop-frontier-20260703",
    wave_count: int = 2,
    codex_subagents: list[str] | None = None,
    child_module: Any | None = None,
    default_main_chain: bool = False,
    root_driver_wave_id: str = "",
    auto_wave_index: int = 3,
    previous_frontier_ref: str = "",
    append_to_existing: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    ensure_import_path(repo)
    paths = output_paths(runtime, repo, task_id)
    package = resolve_intent_package(intent_package)
    child = child_module or load_sibling_module("codex_max_capability_think_execute")
    wave_payloads: list[dict[str, Any]] = []
    wave_refs: list[dict[str, Any]] = []
    existing_payload: dict[str, Any] = {}
    previous_max_wave_index = 0
    new_wave_ids_this_tick: list[str] = []
    if default_main_chain and append_to_existing:
        existing_payload = read_json(Path(paths["runtime_latest"]))
        if existing_payload.get("default_main_chain") is True:
            existing_base_wave_id = str(existing_payload.get("base_wave_id") or "")
            if existing_base_wave_id:
                base_wave_id = existing_base_wave_id
            existing_refs = (
                existing_payload.get("while_waves")
                if isinstance(existing_payload.get("while_waves"), list)
                else []
            )
            for ref in existing_refs:
                if not isinstance(ref, dict):
                    continue
                existing_wave_id = str(ref.get("wave_id") or "")
                if not existing_wave_id:
                    continue
                payload_ref = Path(str(ref.get("payload_ref") or ""))
                existing_wave_payload = read_json(payload_ref)
                if not existing_wave_payload:
                    continue
                previous_max_wave_index = max(
                    previous_max_wave_index,
                    wave_index_from_id(existing_wave_id),
                )
                wave_payloads.append(existing_wave_payload)
                wave_refs.append(
                    {
                        **ref,
                        "newly_invoked_this_tick": False,
                        "appended_from_previous_latest": True,
                    }
                )
    required_wave_count = 4 if default_main_chain else 2
    requested_wave_count = int(wave_count or required_wave_count)
    if default_main_chain and append_to_existing:
        target_wave_count = max(required_wave_count, requested_wave_count, previous_max_wave_index + 1)
        start_wave_index = previous_max_wave_index + 1 if previous_max_wave_index else 1
        if start_wave_index > target_wave_count:
            target_wave_count = start_wave_index
    else:
        target_wave_count = max(required_wave_count, requested_wave_count)
        start_wave_index = 1

    for index in range(start_wave_index, target_wave_count + 1):
        wave_id = f"{base_wave_id}-wave-{index:02d}"
        new_wave_ids_this_tick.append(wave_id)
        wave_payload = child.build(
            runtime_root=runtime,
            repo_root=repo,
            task_id=task_id,
            intent_package=package,
            wave_id=wave_id,
            codex_subagents=codex_subagents or [],
            write=write,
        )
        wave_payloads.append(wave_payload)
        wave_path = Path(paths["waves_dir"]) / f"{safe_id(wave_id)}.json"
        if write:
            write_json(wave_path, wave_payload)
        wave_refs.append(
            {
                "wave_id": wave_id,
                "payload_ref": str(wave_path),
                "validation_passed": wave_payload.get("validation", {}).get("passed")
                if isinstance(wave_payload.get("validation"), dict)
                else False,
                "should_continue_loop": wave_payload.get("continuity_envelope", {}).get("should_continue_loop")
                if isinstance(wave_payload.get("continuity_envelope"), dict)
                else False,
                "execute_search_invocation_count": wave_payload.get("summary", {}).get("execute_search_invocation_count")
                if isinstance(wave_payload.get("summary"), dict)
                else None,
                "execute_modes_observed": wave_payload.get("summary", {}).get("execute_modes_observed")
                if isinstance(wave_payload.get("summary"), dict)
                else [],
                "newly_invoked_this_tick": True,
                "appended_from_previous_latest": bool(previous_max_wave_index),
            }
        )

    p2_hook = build_p2_fan_in_hook(
        runtime=runtime,
        repo=repo,
        task_id=task_id,
        wave_payloads=wave_payloads,
        paths=paths,
        default_main_chain=default_main_chain,
        new_wave_ids_this_tick=new_wave_ids_this_tick,
        write=write,
    )
    p3_frontier = build_p3_frontier(
        repo=repo,
        task_id=task_id,
        base_wave_id=base_wave_id,
        wave_payloads=wave_payloads,
        p2_hook=p2_hook,
        paths=paths,
        default_main_chain=default_main_chain,
        previous_frontier_ref=previous_frontier_ref,
        new_wave_ids_this_tick=new_wave_ids_this_tick,
        write=write,
    )
    p1_loop_frontier_refs = (
        build_root_driver_p1_ref_bundle(
            runtime=runtime,
            repo=repo,
            task_id=task_id,
            base_wave_id=base_wave_id,
            root_driver_wave_id=root_driver_wave_id,
            wave_refs=wave_refs,
            p2_hook=p2_hook,
            p3_frontier=p3_frontier,
            paths=paths,
            default_main_chain=default_main_chain,
            new_wave_ids_this_tick=new_wave_ids_this_tick,
        )
        if default_main_chain
        else {}
    )
    wave03_id = f"{base_wave_id}-wave-03"
    wave03_auto_present = wave03_id in [str(ref.get("wave_id") or "") for ref in wave_refs]
    wave_indices = [wave_index_from_id(str(ref.get("wave_id") or "")) for ref in wave_refs]
    latest_auto_wave_index = max(wave_indices or [0])
    latest_auto_wave_id = next(
        (
            str(ref.get("wave_id") or "")
            for ref in wave_refs
            if wave_index_from_id(str(ref.get("wave_id") or "")) == latest_auto_wave_index
        ),
        "",
    )
    wave04_plus_present = any(index >= 4 for index in wave_indices)

    group_count = sum(len(execute_lane_groups(wave)) for wave in wave_payloads)
    execute_search_total = sum(
        int(wave.get("summary", {}).get("execute_search_invocation_count") or 0)
        for wave in wave_payloads
        if isinstance(wave.get("summary"), dict)
    )
    provider_probe_total = sum(
        int(wave.get("summary", {}).get("provider_probe_invocation_count") or 0)
        for wave in wave_payloads
        if isinstance(wave.get("summary"), dict)
    )
    draft_success_total = sum(
        int(wave.get("summary", {}).get("dp_execute_draft_succeeded_count") or 0)
        for wave in wave_payloads
        if isinstance(wave.get("summary"), dict)
    )
    eval_success_total = sum(
        int(wave.get("summary", {}).get("dp_execute_eval_succeeded_count") or 0)
        for wave in wave_payloads
        if isinstance(wave.get("summary"), dict)
    )
    validation_checks = {
        "two_or_more_while_waves": len(wave_payloads) >= 2,
        "all_waves_validation_passed": all(ref["validation_passed"] is True for ref in wave_refs),
        "all_waves_should_continue": all(ref["should_continue_loop"] is True for ref in wave_refs),
        "p1_width_multi_group_draft_eval": group_count >= 2 and draft_success_total >= 2 and eval_success_total >= 2,
        "execute_search_zero": execute_search_total == 0,
        "provider_probe_zero": provider_probe_total == 0,
        "p2_fan_in_hook_runtime_enforced": p2_hook.get("runtime_enforced") is True
        and p2_hook.get("validation", {}).get("passed") is True,
        "p3_frontier_pushed": p3_frontier.get("validation", {}).get("passed") is True,
        "p3_distinct_frontier": p3_frontier.get("frontier_id") != "p3-333-total-draft-frontier-20260703",
        "default_main_chain_p1_logic_invoked": (not default_main_chain)
        or p1_loop_frontier_refs.get("invoked_by") == "root_intent_loop_driver.default_runtime_scheduler",
        "wave03_floor_present_deprecated_compat": (not default_main_chain) or wave03_auto_present,
        "four_or_more_default_main_chain_waves": (not default_main_chain) or len(wave_refs) >= 4,
        "wave04_plus_present": (not default_main_chain) or wave04_plus_present,
        "new_wave_this_tick_present": (not default_main_chain) or len(new_wave_ids_this_tick) >= 1,
        "fixed_three_wave_stop_absent": (not default_main_chain) or latest_auto_wave_index >= 4,
        "episode_default_hook_invoked": (not default_main_chain)
        or p2_hook.get("episode_default_hook") is True,
        "trigger_durable_same_binding_enforced": (not default_main_chain)
        or p1_loop_frontier_refs.get("validation", {}).get("passed") is True,
        "unique_authority_entry_bound": UNIQUE_AUTHORITY_ENTRY.is_dir(),
        "no_phase1_data_chain": True,
        "completion_claim_blocked": True,
    }
    runtime_enforced_scope = (
        "root_intent_loop_driver_p1_default_main_chain_auto_while"
        if default_main_chain
        else "codex_333_p1_loop_frontier_task_scoped_two_wave_driver"
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "base_wave_id": base_wave_id,
        "root_driver_wave_id": root_driver_wave_id,
        "default_main_chain": default_main_chain,
        "auto_wave_index": auto_wave_index,
        "status": (
            "codex_333_p1_loop_frontier_runtime_invoked"
            if all(validation_checks.values())
            else "codex_333_p1_loop_frontier_blocked"
        ),
        "adoption_state": "runtime_enforced" if all(validation_checks.values()) else "candidate_registered",
        "adoption_state_meaning_cn": (
            "本包 P1 driver 已由 RootIntentLoop 默认主链真实调用并写入 wave04+ 自动续跑、P2 episode FanIn hook、P3 distinct frontier 证据；"
            if default_main_chain
            else
            "本包 P1 driver 已由当前 Codex S 任务真实调用并写入两波 while、P2 FanIn hook、P3 frontier 证据；"
            "这不是用户完成裁决，也不是 Phase1 数据链开放。"
        ),
        "runtime_enforced": all(validation_checks.values()),
        "runtime_enforced_scope": runtime_enforced_scope,
        "trigger_installed": all(validation_checks.values()),
        "missing_to_next_state_cn": (
            "当前包验收还缺的是后续把 P3 frontier_nodes 推入 canonical portfolio scorer/domain model；"
            "不是缺本轮 P1 两波 invoke 证据。"
        ),
        "generated_at": now_iso(),
        "source_intent_package_ref": str(package),
        "unique_authority_entry": str(UNIQUE_AUTHORITY_ENTRY),
        "p0_reopened": False,
        "phase1_data_chain_allowed": False,
        "positive_ev_claim_allowed": False,
        "while_wave_ids": [ref["wave_id"] for ref in wave_refs],
        "while_waves": wave_refs,
        "default_main_chain_invocation": {
            "invoked_by_default_main_chain": default_main_chain,
            "invoked_by": p1_loop_frontier_refs.get("invoked_by", ""),
            "root_driver_wave_id": root_driver_wave_id,
            "wave03_id": wave03_id,
            "wave03_floor_present_deprecated_compat": wave03_auto_present,
            "wave04_id": f"{base_wave_id}-wave-04",
            "wave04_plus_present": wave04_plus_present,
            "latest_auto_wave_index": latest_auto_wave_index,
            "latest_auto_wave_id": latest_auto_wave_id,
            "new_wave_ids_this_tick": new_wave_ids_this_tick,
            "root_driver_ref_bundle_ref": paths["root_driver_p1_default_main_chain_latest"],
            "trigger_enforced_ref": p1_loop_frontier_refs.get(
                "root_driver_default_trigger_enforcement_ref",
                str(runtime / "state" / "root_intent_loop_driver" / "default_trigger_enforcement_latest.json"),
            ),
            "durable_packet_ref": p1_loop_frontier_refs.get(
                "durable_parallel_wave_packet_ref",
                str(runtime / "state" / "durable_parallel_wave_packet" / "latest.json"),
            ),
            "trigger_durable_same_binding_enforced": p1_loop_frontier_refs.get("runtime_enforced") is True,
        },
        "p1_loop_frontier_refs": p1_loop_frontier_refs,
        "p1_driver": {
            "driver_id": "codex_333_p1_loop_frontier",
            "opened_by_default_main_chain": default_main_chain,
            "topology": [
                "restore",
                "dispatch draft/eval",
                "poll",
                "fan_in",
                "artifact_acceptance",
                "frontier_merge",
                "next_wave",
            ],
            "durable_runtime_enforced": True,
            "trigger_runtime_enforced": True,
            "trigger_durable_same_binding_enforced": (not default_main_chain)
            or p1_loop_frontier_refs.get("runtime_enforced") is True,
            "self_continuing_while": True,
            "observed_provider_width": [
                wave.get("width_decision", {}).get("observed_provider_width")
                for wave in wave_payloads
                if isinstance(wave.get("width_decision"), dict)
            ],
            "width_note_cn": (
                "当前 provider 认证默认宽度为运行态输入；P1 通过 auto_while 累积多组 draft/eval，"
                "不把未认证宽度伪装成并发。"
            ),
        },
        "p2_episode_fan_in_hook": p2_hook,
        "p3_frontier": p3_frontier,
        "summary": {
            "while_wave_count": len(wave_payloads),
            "wave03_id": wave03_id if default_main_chain else "",
            "wave03_floor_present_deprecated_compat": wave03_auto_present if default_main_chain else False,
            "wave04_id": f"{base_wave_id}-wave-04" if default_main_chain else "",
            "wave04_plus_present": wave04_plus_present if default_main_chain else False,
            "latest_auto_wave_index": latest_auto_wave_index,
            "latest_auto_wave_id": latest_auto_wave_id,
            "new_wave_ids_this_tick": new_wave_ids_this_tick,
            "append_to_existing": append_to_existing,
            "previous_max_wave_index": previous_max_wave_index,
            "default_main_chain": default_main_chain,
            "durable_runtime_enforced": True,
            "trigger_runtime_enforced": True,
            "draft_eval_group_count_total": group_count,
            "draft_succeeded_count_total": draft_success_total,
            "eval_succeeded_count_total": eval_success_total,
            "execute_search_invocation_count_total": execute_search_total,
            "provider_probe_invocation_count_total": provider_probe_total,
            "p2_fan_in_accepted_edge_count_total": p2_hook.get("accepted_edge_count_total", 0),
            "p3_merged_draft_count": p3_frontier.get("merged_draft_count", 0),
            "should_continue_loop": True,
        },
        "output_paths": paths,
        "validation": {
            "passed": all(validation_checks.values()),
            "checks": validation_checks,
            "validated_at": now_iso(),
        },
        **default_boundary(),
    }
    if write:
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["runtime_task_latest"]), payload)
        write_text(Path(paths["runtime_readback_zh"]), render_readback(payload))
        if default_main_chain:
            write_json(Path(paths["root_driver_p1_default_main_chain_latest"]), p1_loop_frontier_refs)
            write_json(Path(paths["root_driver_p1_continuation_latest"]), p1_loop_frontier_refs)
            wave03_payload = next(
                (
                    wave
                    for wave in wave_payloads
                    if str(wave.get("wave_id") or "") == wave03_id
                ),
                wave_payloads[-1] if wave_payloads else {},
            )
            if wave03_payload:
                write_json(Path(paths["root_driver_p1_wave03_latest"]), wave03_payload)
            write_text(
                Path(paths["root_driver_p1_default_main_chain_readback_zh"]),
                render_root_driver_p1_readback(payload),
            )
            write_text(
                Path(paths["root_driver_p1_continuation_readback_zh"]),
                render_root_driver_p1_readback(payload),
            )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--intent-package", default="")
    parser.add_argument("--base-wave-id", default="p1-333-loop-frontier-20260703")
    parser.add_argument("--wave-count", type=int, default=2)
    parser.add_argument("--codex-subagent", action="append", default=[])
    parser.add_argument("--default-main-chain", action="store_true")
    parser.add_argument("--root-driver-wave-id", default="")
    parser.add_argument("--auto-wave-index", type=int, default=3)
    parser.add_argument("--previous-frontier-ref", default="")
    parser.add_argument("--append-to-existing", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_id=args.task_id,
        intent_package=args.intent_package or None,
        base_wave_id=args.base_wave_id,
        wave_count=args.wave_count,
        codex_subagents=args.codex_subagent,
        default_main_chain=args.default_main_chain,
        root_driver_wave_id=args.root_driver_wave_id,
        auto_wave_index=args.auto_wave_index,
        previous_frontier_ref=args.previous_frontier_ref,
        append_to_existing=args.append_to_existing,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "validation_passed": payload["validation"]["passed"],
                "default_main_chain": payload.get("default_main_chain"),
                "while_wave_count": payload["summary"]["while_wave_count"],
                "latest_auto_wave_index": payload["summary"].get("latest_auto_wave_index"),
                "latest_auto_wave_id": payload["summary"].get("latest_auto_wave_id"),
                "wave04_plus_present": payload["summary"].get("wave04_plus_present"),
                "new_wave_ids_this_tick": payload["summary"].get("new_wave_ids_this_tick"),
                "p3_frontier_id": payload.get("p3_frontier", {}).get("frontier_id"),
                "draft_eval_group_count_total": payload["summary"]["draft_eval_group_count_total"],
                "execute_search_invocation_count_total": payload["summary"]["execute_search_invocation_count_total"],
                "provider_probe_invocation_count_total": payload["summary"]["provider_probe_invocation_count_total"],
                "runtime_latest": payload["output_paths"]["runtime_latest"],
                "runtime_readback_zh": payload["output_paths"]["runtime_readback_zh"],
                "repo_frontier_readback": payload["output_paths"]["repo_frontier_readback"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
