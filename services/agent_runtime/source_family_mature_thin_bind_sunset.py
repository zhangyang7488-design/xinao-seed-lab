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

from services.agent_runtime import next_frontier_continuation_supervisor as next_frontier_supervisor


SCHEMA_VERSION = "xinao.codex_s.source_family_mature_thin_bind_sunset.v1"
SENTINEL = "SENTINEL:XINAO_SOURCE_FAMILY_MATURE_THIN_BIND_SUNSET_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
PARENT_TASK_ID = WORK_ID
TASK_ID = "wave5_source_family_mature_thin_bind_sunset_20260704"
ROUTING = "continue_same_task"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
SOURCE_FAMILY_TASK_ID = "wave4_20260701_frontier_source_family_20260704"
PHASE5_ACTION = "enter_phase5_mature_thin_bind_sunset"
SRC_ROOT = DEFAULT_REPO / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


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


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def path_digest(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "json_valid": bool(payload) or not path.is_file(),
        "sha256": path_digest(path),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "wave_id": payload.get("wave_id"),
        "task_id": payload.get("task_id"),
        "validation_passed": validation.get("passed"),
        "not_execution_controller": payload.get("not_execution_controller"),
    }


def output_paths(repo: Path, runtime: Path, wave_id: str) -> dict[str, str]:
    root = runtime / "state" / "source_family_mature_thin_bind_sunset"
    return {
        "runtime_latest": str(root / "latest.json"),
        "wave_latest": str(root / "waves" / f"{wave_id}.json"),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_source_family_mature_thin_bind_sunset.v1.json"),
        "source_family_latest": str(runtime / "state" / "source_family_wave_scheduler" / "latest.json"),
        "source_family_temporal_activity_latest": str(
            runtime / "state" / "source_family_wave_scheduler" / "temporal_activity_latest.json"
        ),
        "total_source_frontier_coverage_latest": str(
            runtime / "state" / "source_family_wave_scheduler" / "total_source_frontier_coverage" / "latest.json"
        ),
        "source_topic_claimcards_latest": str(
            runtime / "state" / "source_family_wave_scheduler" / "source_topic_claimcards" / "latest.json"
        ),
        "mature_carrier_replacement_bindings_latest": str(
            runtime / "state" / "mature_carrier_replacement_bindings" / "latest.json"
        ),
        "mature_carrier_thin_bind_manifest": str(
            runtime / "capabilities" / "codex_s.source_family_mature_carrier_thin_bind" / "manifest.json"
        ),
        "phase5_sunset_manifest": str(
            runtime / "capabilities" / "codex_s.source_family_mature_thin_bind_sunset" / "manifest.json"
        ),
        "artifact_acceptance_queue_latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "source_ledger_latest": str(runtime / "state" / "source_ledger" / "latest.json"),
        "previous_next_frontier_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "next_frontier_machine_actions_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "sunset_edges_latest": str(root / "sunset_edges" / "latest.json"),
        "sunset_edges_wave": str(root / "sunset_edges" / f"{wave_id}.json"),
        "candidate_adapter_smoke_queue_latest": str(root / "candidate_adapter_smoke_queue" / "latest.json"),
        "candidate_adapter_smoke_queue_wave": str(root / "candidate_adapter_smoke_queue" / f"{wave_id}.json"),
        "readback_zh": str(runtime / "readback" / "zh" / "wave_block5_mature_thin_bind_sunset_20260704.md"),
    }


def first_next_action(payload: dict[str, Any]) -> str:
    actions = payload.get("next_frontier")
    if isinstance(actions, list) and actions:
        first = actions[0]
        if isinstance(first, dict):
            return str(first.get("action") or "")
    return ""


def phase5_action_already_consumed(payload: dict[str, Any]) -> bool:
    phase5 = payload.get("phase5_sunset") if isinstance(payload.get("phase5_sunset"), dict) else {}
    return (
        first_next_action(payload) == "smoke_mature_carrier_adapter_candidates"
        and phase5.get("consumed_action") == PHASE5_ACTION
        and payload.get("stop_allowed") is False
    )


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_sunset_edges(bindings: dict[str, Any], paths: dict[str, str]) -> dict[str, Any]:
    landed = bindings.get("landed_bindings") if isinstance(bindings.get("landed_bindings"), list) else []
    edges: list[dict[str, Any]] = []
    for index, item in enumerate(landed, start=1):
        if not isinstance(item, dict):
            continue
        edges.append(
            {
                "edge_id": f"phase5-sunset-edge-{index:02d}-{item.get('binding_id')}",
                "binding_id": item.get("binding_id"),
                "handrolled_surface": item.get("handrolled_surface"),
                "mature_carrier": item.get("mature_carrier"),
                "thin_bind_adapter": item.get("thin_bind_adapter"),
                "source_claim_card_id": item.get("source_claim_card_id"),
                "source_url": item.get("source_url"),
                "invoke": item.get("invoke", {}),
                "sunset_scope": item.get("sunset_scope", []),
                "status": "sunset_edge_ready" if item.get("thin_bind_landed") is True else "sunset_edge_blocked",
                "thin_bind_landed": item.get("thin_bind_landed") is True,
                "policy_only": item.get("policy_only") is True,
                "evidence_ref": paths["mature_carrier_replacement_bindings_latest"],
            }
        )
    checks = {
        "landed_edges_present": len(edges) >= 2,
        "all_edges_landed": all(edge["thin_bind_landed"] for edge in edges),
        "no_policy_only_edges": all(edge["policy_only"] is False for edge in edges),
        "all_edges_have_invokes": all(bool(edge.get("invoke")) for edge in edges),
    }
    return {
        "schema_version": "xinao.codex_s.source_family_mature_thin_bind_sunset_edges.v1",
        "status": "sunset_edges_ready" if all(checks.values()) else "sunset_edges_blocked",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "edge_count": len(edges),
        "edges": edges,
        "output_paths": {
            "runtime_latest": paths["sunset_edges_latest"],
            "wave": paths["sunset_edges_wave"],
        },
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_candidate_smoke_queue(bindings: dict[str, Any], paths: dict[str, str]) -> dict[str, Any]:
    candidates = bindings.get("candidate_replacement_queue")
    raw_candidates = candidates if isinstance(candidates, list) else []
    queued: list[dict[str, Any]] = []
    for index, item in enumerate(raw_candidates, start=1):
        if not isinstance(item, dict):
            continue
        queued.append(
            {
                "queue_id": f"phase5-adapter-smoke-{index:02d}-{item.get('binding_id')}",
                "binding_id": item.get("binding_id"),
                "mature_carrier": item.get("mature_carrier"),
                "handrolled_surface": item.get("handrolled_surface"),
                "source_claim_card_id": item.get("source_claim_card_id"),
                "source_url": item.get("source_url"),
                "promotion_gate": item.get("promotion_gate") or "adapter_smoke_before_default_capability",
                "status": "adapter_smoke_required_before_promotion",
                "thin_bind_landed": False,
            }
        )
    checks = {
        "candidate_queue_present": len(queued) >= 1,
        "all_candidates_have_promotion_gate": all(bool(item.get("promotion_gate")) for item in queued),
        "no_candidate_promoted_without_smoke": all(item.get("thin_bind_landed") is False for item in queued),
    }
    return {
        "schema_version": "xinao.codex_s.source_family_phase5_candidate_adapter_smoke_queue.v1",
        "status": "candidate_adapter_smoke_queue_ready" if all(checks.values()) else "candidate_adapter_smoke_queue_empty",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "candidate_count": len(queued),
        "candidates": queued,
        "output_paths": {
            "runtime_latest": paths["candidate_adapter_smoke_queue_latest"],
            "wave": paths["candidate_adapter_smoke_queue_wave"],
        },
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_phase5_manifest(paths: dict[str, str], validation_passed: bool) -> dict[str, Any]:
    return {
        "schema_version": "xinao.capability_manifest.v1",
        "capability_id": "codex_s.source_family_mature_thin_bind_sunset",
        "status": "ready" if validation_passed else "blocked",
        "invoke": {
            "cli": "python -m xinao_seedlab.cli.__main__ source-family-mature-thin-bind-sunset --wave-id <wave>",
            "verifier": "scripts/verify_source_family_mature_thin_bind_sunset.ps1",
            "input_action": PHASE5_ACTION,
        },
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "consumes": [
            paths["source_family_latest"],
            paths["total_source_frontier_coverage_latest"],
            paths["mature_carrier_replacement_bindings_latest"],
            paths["mature_carrier_thin_bind_manifest"],
        ],
        "writes": [
            paths["runtime_latest"],
            paths["sunset_edges_latest"],
            paths["candidate_adapter_smoke_queue_latest"],
            paths["next_frontier_machine_actions_latest"],
        ],
        "not_completion_boundary": True,
        "secret_values_recorded": False,
    }


def build_next_frontier(
    *,
    wave_id: str,
    paths: dict[str, str],
    validation_passed: bool,
    candidate_queue: dict[str, Any],
    parent_wave_id: str,
) -> dict[str, Any]:
    candidates = candidate_queue.get("candidates") if isinstance(candidate_queue.get("candidates"), list) else []
    if validation_passed:
        next_items = [
            {
                "action_id": "next-wave-phase5-adapter-smoke-candidates",
                "action": "smoke_mature_carrier_adapter_candidates",
                "why": "Phase5 consumed the zero-gap source-family frontier and queued mature-carrier candidates behind adapter smoke gates.",
                "requires": [
                    paths["candidate_adapter_smoke_queue_latest"],
                    "adapter_smoke_before_default_capability",
                    "SourceLedger",
                    "AAQ",
                ],
            },
            {
                "action_id": "next-wave-default-temporal-chain-poll",
                "action": "keep_default_temporal_chain_polling",
                "why": "Foreground and background lanes must continue polling; phase5 sunset evidence is not a completion boundary.",
                "requires": ["Temporal task queue poller", "worker dispatch ledger", "next_frontier_machine_actions"],
            },
        ]
    else:
        next_items = [
            {
                "action_id": "repair-phase5-mature-thin-bind-sunset-inputs",
                "action": "repair_phase5_mature_thin_bind_sunset_inputs",
                "why": "Phase5 sunset cannot consume the frontier until all input evidence is wave-bound and validation-positive.",
                "requires": [
                    paths["source_family_latest"],
                    paths["total_source_frontier_coverage_latest"],
                    paths["mature_carrier_replacement_bindings_latest"],
                    paths["mature_carrier_thin_bind_manifest"],
                ],
            }
        ]
    return {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "phase5_next_frontier_ready" if validation_passed else "phase5_next_frontier_repair_required",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "should_continue_loop": True,
        "stop_allowed": False,
        "stop_allowed_reason": "phase5_mature_thin_bind_sunset_consumed_but_candidate_smoke_and_default_polling_continue",
        "source_frontier_gap": {
            "exists": True,
            "source_package_gap_open": False,
            "gap_scope": "20260701_total_source_frontier",
            "topic_family_count": 0,
            "covered_topic_family_count": 0,
            "remaining_topic_family_count": 0,
            "coverage_ref": paths["total_source_frontier_coverage_latest"],
            "next_gap_action": "source_family_gap_closed_phase5_consumed",
        },
        "phase5_sunset": {
            "consumed_action": PHASE5_ACTION,
            "sunset_edges_ref": paths["sunset_edges_latest"],
            "candidate_adapter_smoke_queue_ref": paths["candidate_adapter_smoke_queue_latest"],
            "candidate_count": len(candidates),
        },
        "next_frontier": next_items,
        "output_paths": {"runtime_latest": paths["next_frontier_machine_actions_latest"]},
        "validation": {
            "passed": validation_passed,
            "checks": {
                "phase5_action_consumed": validation_passed,
                "candidate_queue_ref_written": bool(paths["candidate_adapter_smoke_queue_latest"]),
                "stop_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def render_readback(payload: dict[str, Any]) -> str:
    paths = payload.get("output_paths", {})
    checks = payload.get("validation", {}).get("checks", {})
    sunset = payload.get("sunset_edges", {})
    queue = payload.get("candidate_adapter_smoke_queue", {})
    lines = [
        "# Wave-block5 source-family mature thin-bind sunset readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- wave_id: `{payload.get('wave_id')}`",
        f"- parent_wave_id: `{payload.get('parent_wave_id')}`",
        f"- consumed next action: `{payload.get('consumed_next_frontier_action')}`",
        f"- sunset edges landed: {sunset.get('edge_count')}",
        f"- adapter smoke candidates queued: {queue.get('candidate_count')}",
        f"- source frontier remaining: {payload.get('source_frontier_remaining_topic_family_count')}",
        f"- phase5 capability invoke: `{paths.get('phase5_sunset_manifest')}`",
        f"- sunset edges: `{paths.get('sunset_edges_latest')}`",
        f"- candidate smoke queue: `{paths.get('candidate_adapter_smoke_queue_latest')}`",
        f"- next_frontier: `{paths.get('next_frontier_machine_actions_latest')}`",
        "",
        "验收三句：",
        "1. 本动作消费的是 source-family scheduler 写出的 `enter_phase5_mature_thin_bind_sunset`，不是 bridge ready 或 PASS 报告。",
        "2. source frontier remaining 必须为 0，thin-bind manifest/bindings 必须 ready，才允许写 phase5 sunset evidence。",
        "3. 现在能 invoke `python -m xinao_seedlab.cli.__main__ source-family-mature-thin-bind-sunset --wave-id <wave>`；后续继续做 adapter smoke 和默认 Temporal 轮询，不允许停成完成。",
        "",
        f"- validation checks: `{checks}`",
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
    wave_id: str = "wave-block5-source-family-mature-thin-bind-sunset",
    invoked_by_temporal_activity: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    del anchor_package_root
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(repo, runtime, wave_id)

    source_family = read_json(Path(paths["source_family_latest"]))
    source_family_temporal = read_json(Path(paths["source_family_temporal_activity_latest"]))
    coverage = read_json(Path(paths["total_source_frontier_coverage_latest"]))
    topic_cards = read_json(Path(paths["source_topic_claimcards_latest"]))
    bindings = read_json(Path(paths["mature_carrier_replacement_bindings_latest"]))
    thin_manifest = read_json(Path(paths["mature_carrier_thin_bind_manifest"]))
    aaq = read_json(Path(paths["artifact_acceptance_queue_latest"]))
    source_ledger = read_json(Path(paths["source_ledger_latest"]))
    previous_next_frontier = read_json(Path(paths["previous_next_frontier_latest"]))

    previous_next_action = first_next_action(previous_next_frontier)
    already_consumed = phase5_action_already_consumed(previous_next_frontier)
    can_consume_phase5 = previous_next_action == PHASE5_ACTION or already_consumed
    consumed_action = PHASE5_ACTION if can_consume_phase5 else ""
    foreign_next_action = "" if can_consume_phase5 else previous_next_action
    parent_wave_id = str(
        previous_next_frontier.get("parent_wave_id")
        if already_consumed
        else previous_next_frontier.get("wave_id")
        or source_family.get("wave_id")
        or source_family_temporal.get("wave_id")
        or bindings.get("wave_id")
        or ""
    )
    remaining = int_value(coverage.get("remaining_topic_family_count"))
    source_gap_open = coverage.get("source_gap_open")
    if source_gap_open is None:
        source_gap_open = coverage.get("source_package_gap_open")

    sunset_edges = build_sunset_edges(bindings, paths)
    candidate_queue = build_candidate_smoke_queue(bindings, paths)

    thin_invoke = thin_manifest.get("invoke") if isinstance(thin_manifest.get("invoke"), dict) else {}
    checks = {
        "parent_next_action_phase5": can_consume_phase5,
        "phase5_sunset_idempotent_recheck": can_consume_phase5 and consumed_action == PHASE5_ACTION,
        "foreign_next_action_not_consumed": foreign_next_action == "",
        "source_frontier_zero_remaining": remaining == 0 and source_gap_open is False,
        "coverage_validation_passed": coverage.get("validation", {}).get("passed") is True
        if isinstance(coverage.get("validation"), dict)
        else False,
        "source_family_validation_passed": source_family.get("validation", {}).get("passed") is True
        if isinstance(source_family.get("validation"), dict)
        else False,
        "bindings_ready": bindings.get("validation", {}).get("passed") is True
        and bindings.get("thin_bind_landed") is True
        and int_value(bindings.get("thin_bind_landed_count")) >= 2
        and bindings.get("policy_only") is False
        if isinstance(bindings.get("validation"), dict)
        else False,
        "thin_bind_manifest_ready": thin_manifest.get("capability_id")
        == "codex_s.source_family_mature_carrier_thin_bind"
        and thin_manifest.get("status") == "ready",
        "thin_bind_manifest_invokable": bool(thin_invoke.get("cli"))
        and bool(thin_invoke.get("temporal_activity")),
        "sunset_edges_ready": sunset_edges.get("validation", {}).get("passed") is True,
        "candidate_smoke_queue_ready": candidate_queue.get("validation", {}).get("passed") is True,
        "aaq_and_source_ledger_present": int_value(aaq.get("accepted_artifact_count")) > 0
        and bool(source_ledger),
        "topic_claimcards_present": int_value(topic_cards.get("claim_card_count")) > 0,
        "completion_claim_denied": True,
    }
    validation_passed = can_consume_phase5 and all(checks.values())
    repair_plan = {
        "schema_version": "xinao.codex_s.phase5_mature_thin_bind_repair_plan.v1",
        "status": "repair_not_required" if validation_passed else "repair_required",
        "named_blocker": "" if validation_passed else "PHASE5_MATURE_THIN_BIND_SUNSET_INPUT_NOT_READY",
        "missing_checks": [name for name, passed in checks.items() if not passed],
        "return_to_main_route": True,
        "suggested_recheck_command": (
            "python -m xinao_seedlab.cli.__main__ source-family-mature-thin-bind-sunset "
            "--wave-id <wave>"
        ),
        "not_user_completion": True,
        "not_execution_controller": True,
    }
    phase5_manifest = build_phase5_manifest(paths, validation_passed)
    next_frontier = build_next_frontier(
        wave_id=wave_id,
        paths=paths,
        validation_passed=validation_passed,
        candidate_queue=candidate_queue,
        parent_wave_id=parent_wave_id,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "source_family_task_id": SOURCE_FAMILY_TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "status": "source_family_mature_thin_bind_sunset_ready"
        if validation_passed
        else "source_family_mature_thin_bind_sunset_blocked",
        "generated_at": now_iso(),
        "adoption_state": "phase5_source_family_mature_thin_bind_sunset_consumed"
        if validation_passed
        else "phase5_source_family_mature_thin_bind_sunset_repair_required",
        "invoked_by_temporal_activity": invoked_by_temporal_activity,
        "consumed_next_frontier_action": consumed_action,
        "foreign_next_frontier_action_deferred": foreign_next_action,
        "next_frontier_write_skipped": not can_consume_phase5,
        "source_frontier_remaining_topic_family_count": remaining,
        "source_frontier_gap_open": source_gap_open,
        "input_refs": {
            "source_family_latest": json_ref(Path(paths["source_family_latest"])),
            "source_family_temporal_activity_latest": json_ref(
                Path(paths["source_family_temporal_activity_latest"])
            ),
            "total_source_frontier_coverage_latest": json_ref(
                Path(paths["total_source_frontier_coverage_latest"])
            ),
            "source_topic_claimcards_latest": json_ref(Path(paths["source_topic_claimcards_latest"])),
            "mature_carrier_replacement_bindings_latest": json_ref(
                Path(paths["mature_carrier_replacement_bindings_latest"])
            ),
            "mature_carrier_thin_bind_manifest": json_ref(Path(paths["mature_carrier_thin_bind_manifest"])),
            "artifact_acceptance_queue_latest": json_ref(Path(paths["artifact_acceptance_queue_latest"])),
            "source_ledger_latest": json_ref(Path(paths["source_ledger_latest"])),
            "previous_next_frontier_latest": json_ref(Path(paths["previous_next_frontier_latest"])),
        },
        "sunset_edges": sunset_edges,
        "candidate_adapter_smoke_queue": candidate_queue,
        "phase5_sunset_manifest": phase5_manifest,
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
        if can_consume_phase5:
            write_json(Path(paths["sunset_edges_latest"]), sunset_edges)
            write_json(Path(paths["sunset_edges_wave"]), sunset_edges)
            write_json(Path(paths["candidate_adapter_smoke_queue_latest"]), candidate_queue)
            write_json(Path(paths["candidate_adapter_smoke_queue_wave"]), candidate_queue)
            write_json(Path(paths["phase5_sunset_manifest"]), phase5_manifest)
            next_frontier_supervisor.promote_candidate_next_frontier(
                runtime_root=runtime,
                candidate=next_frontier,
                source_kind="source_family_mature_thin_bind_sunset",
                source_ref=paths["runtime_latest"],
            )
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["wave_latest"]), payload)
        write_text(Path(paths["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume source-family phase5 mature thin-bind sunset action.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="wave-block5-source-family-mature-thin-bind-sunset")
    parser.add_argument("--invoked-by-temporal-activity", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        wave_id=args.wave_id,
        invoked_by_temporal_activity=args.invoked_by_temporal_activity,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
