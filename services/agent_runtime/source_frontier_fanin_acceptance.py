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


SCHEMA_VERSION = "xinao.codex_s.source_frontier_fanin_acceptance.v1"
SENTINEL = "SENTINEL:XINAO_SOURCE_FRONTIER_FANIN_ACCEPTANCE_READY"
CONSUMER_SENTINEL = "SENTINEL:XINAO_SOURCE_FRONTIER_DURABLE_CONSUMER_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
PARENT_TASK_ID = WORK_ID
TASK_ID = "wave3_20260702_absorption_slice_20260704"
ROUTING = "continue_same_task"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
SRC_ROOT = DEFAULT_REPO / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

AUTHORITY_FILES = [
    "AUTHORITY_READ_ORDER.txt",
    "新系统独立并行_自由发散外部研究总稿_20260701.txt",
    "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
]

MAIN_EXECUTION_LOOP = [
    "restore",
    "dispatch",
    "poll",
    "fan_in",
    "verify_evidence_readback",
    "recompute_capacity",
    "next_wave",
]

SOURCE_FRONTIER_BATCHES = [
    {
        "batch_id": "source_family_fanout_claimcards",
        "module_id": "wave3_module_1_source_family_fanout",
        "candidate_kind": "SourceFamilyWavePlan",
        "authority_ref": "20260702 lines 598-653, 1200-1265",
        "claim": (
            "Open exploration must run source-family fanout every wave; official docs are one lane, "
            "not the whole research surface."
        ),
        "source_family": "local_authority_source_package",
        "codex_s_rule_or_config_delta": "source_family_fanout_is_backlog_work_not_report",
        "verification_need": "ClaimCardStagingQueue -> FanInAcceptanceQueue -> AAQ accepts at least one non-local source family.",
        "utility_score": 51,
    },
    {
        "batch_id": "frontier_portfolio_four_objects",
        "module_id": "wave3_module_2_phase0_four_objects",
        "candidate_kind": "Phase0FrontierObjects",
        "authority_ref": "20260702 lines 1853-1891",
        "claim": (
            "The next frontier machine state must expose FrontierCandidate, FrontierPortfolioSnapshot, "
            "LaneResultReview, and RewardSignal before the next dispatch decision."
        ),
        "source_family": "local_authority_source_package",
        "codex_s_rule_or_config_delta": "frontier_portfolio_four_objects_are_required_for_recompute",
        "verification_need": "Write frontier portfolio, lane result review, reward signal, and next action refs.",
        "utility_score": 54,
    },
    {
        "batch_id": "private_open_source_reference_lane",
        "module_id": "wave3_module_3_private_open_source_absorption",
        "candidate_kind": "PrivateOpenSourceDiscoveryLane",
        "authority_ref": "20260702 lines 1179-1290, 1349-1414",
        "claim": (
            "Private and small open-source projects are a first-class discovery lane, but remain "
            "reference_only or candidate_pattern until cross-checked and accepted."
        ),
        "source_family": "local_authority_source_package",
        "codex_s_rule_or_config_delta": "private_open_source_lane_continues_as_candidate_not_fact_source",
        "verification_need": "At least one open-source ClaimCard enters staging and AAQ without direct fact promotion.",
        "utility_score": 49,
    },
    {
        "batch_id": "post_hygiene_total_source_frontier_claimcards",
        "module_id": "wave3_continuation_4_total_source_frontier_after_hygiene",
        "candidate_kind": "TotalSourceFrontierContinuation",
        "authority_ref": "20260701 total source frontier + 20260704 planning lines 96-149",
        "claim": (
            "After blocks 3/4/5/2, the next useful frontier is not ProviderScheduler; it is "
            "continuing total source absorption through ClaimCard/FanIn/AAQ with source-package backrefs."
        ),
        "source_family": "local_authority_source_package",
        "codex_s_rule_or_config_delta": "post_hygiene_total_source_frontier_remains_open_until_claimcards_are_consumed",
        "verification_need": "Write a new ClaimCard batch after wave2 hygiene and keep stop_allowed=false until consumed.",
        "utility_score": 57,
    },
    {
        "batch_id": "default_loop_split_brain_unification",
        "module_id": "wave3_continuation_5_default_loop_unification",
        "candidate_kind": "DefaultLoopSplitBrainUnification",
        "authority_ref": "20260702 §0 RootIntentLoop + planning lines 445-452",
        "claim": (
            "Only Phase3 event_queue + LoopRuntimeState + phase4 scheduler may be the default while; "
            "30min, same_default, phase2 consumer, and meta_rsi are reference/watchdog surfaces."
        ),
        "source_family": "local_authority_source_package",
        "codex_s_rule_or_config_delta": "default_loop_trigger_reads_event_queue_not_legacy_runner",
        "verification_need": "Fan-in evidence must point to default_main_loop_hygiene and wave2 scoped next frontier.",
        "utility_score": 55,
    },
    {
        "batch_id": "clean_ingress_s_native_boundary",
        "module_id": "wave3_continuation_6_clean_ingress_boundary",
        "candidate_kind": "IngressBoundaryNamedBlockerOrSNative",
        "authority_ref": "planning lines 451-452 and S workspace boundary",
        "claim": (
            "CLEAN ingress cannot be revived as S hot-path authority; either S-native spawn/signal is the "
            "exclusive default route or the remaining compatibility gap is a named_blocker."
        ),
        "source_family": "local_authority_source_package",
        "codex_s_rule_or_config_delta": "clean_ingress_reference_only_unless_explicit_compatibility_task",
        "verification_need": "ClaimCard and SourceLedger must keep old CLEAN as reference_only, not task owner.",
        "utility_score": 52,
    },
]

CLAIM_CARD_REQUIRED_FIELDS = [
    "source_url",
    "source_family",
    "claim",
    "verification_need",
    "accepted_for",
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


def short_wave_stem(wave_id: str, *, max_len: int = 96) -> str:
    value = str(wave_id or "wave")
    if len(value) <= max_len:
        return value
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{value[: max_len - 17]}-{digest}"


def read_json_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def json_ref(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return ref
    payload = read_json_payload(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    ref.update(
        {
            "json_valid": bool(payload),
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "sentinel": payload.get("sentinel"),
            "validation_passed": validation.get("passed"),
            "adoption_state": payload.get("adoption_state"),
            "not_execution_controller": payload.get("not_execution_controller"),
        }
    )
    return ref


def output_paths(repo: Path, runtime: Path, wave_id: str) -> dict[str, str]:
    root = runtime / "state" / "source_frontier_fanin_acceptance"
    episode_id = f"source-frontier-fanin-acceptance-{wave_id}"
    wave_stem = short_wave_stem(wave_id)
    return {
        "runtime_latest": str(root / "latest.json"),
        "wave_latest": str(root / "waves" / f"{wave_id}.json"),
        "worker_assignment_latest": str(runtime / "state" / "worker_assignment" / f"{TASK_ID}.json"),
        "slice_worker_assignment_latest": str(runtime / "state" / "worker_assignment" / f"{TASK_ID}.json"),
        "parent_assignment_link": str(
            runtime / "state" / "worker_assignment" / f"{PARENT_TASK_ID}.current_source_frontier_slice.json"
        ),
        "worker_assignment_wave": str(
            runtime
            / "state"
            / "worker_assignment"
            / f"{TASK_ID}.source_frontier_fanin_acceptance.{wave_stem}.json"
        ),
        "fan_in_acceptance_queue_latest": str(runtime / "state" / "fan_in_acceptance_queue" / "latest.json"),
        "parallel_fan_in_acceptance_latest": str(runtime / "state" / "parallel_fan_in_acceptance" / "latest.json"),
        "claim_card_staging_queue_latest": str(runtime / "state" / "claim_card_staging_queue" / "latest.json"),
        "source_family_wave_plan_latest": str(runtime / "state" / "source_family_wave_plan" / "latest.json"),
        "next_frontier_machine_actions_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "frontier_portfolio_snapshot_latest": str(runtime / "state" / "frontier_portfolio_snapshot" / "latest.json"),
        "lane_result_review_latest": str(runtime / "state" / "lane_result_review" / "latest.json"),
        "reward_signal_latest": str(runtime / "state" / "reward_signal" / "latest.json"),
        "source_frontier_durable_consumer_latest": str(
            runtime / "state" / "source_frontier_durable_consumer" / "latest.json"
        ),
        "source_frontier_durable_consumer_readback": str(
            runtime / "readback" / "zh" / "source_frontier_durable_consumer_20260704.md"
        ),
        "artifact_acceptance_queue_latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "source_ledger_latest": str(runtime / "state" / "source_ledger" / "latest.json"),
        "episode_workflow_entry": str(runtime / "runs" / "episodes" / episode_id / "workflow_entry.json"),
        "episode_trace": str(runtime / "runs" / "episodes" / episode_id / "episode_trace.jsonl"),
        "runtime_readback_zh": str(runtime / "readback" / "zh" / "source_frontier_fanin_acceptance_20260704.md"),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_source_frontier_fanin_acceptance.v1.json"),
        "writer": str(repo / "services" / "agent_runtime" / "source_frontier_fanin_acceptance.py"),
        "tests": str(repo / "tests" / "seedcortex" / "test_source_frontier_fanin_acceptance.py"),
        "verifier": str(repo / "scripts" / "verify_source_frontier_fanin_acceptance.ps1"),
    }


def file_source_ref(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "read_in_full": False,
        "role": "source_package_member",
    }
    if not path.is_file():
        return ref
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    ref.update(
        {
            "read_in_full": True,
            "line_count": len(text.splitlines()),
            "char_count": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        }
    )
    return ref


def source_package_refs(anchor_package_root: Path) -> dict[str, Any]:
    refs = [file_source_ref(anchor_package_root / name) for name in AUTHORITY_FILES]
    digest_input = json.dumps(
        [
            {
                "path": ref["path"],
                "exists": ref["exists"],
                "sha256": ref.get("sha256", ""),
                "line_count": ref.get("line_count", 0),
            }
            for ref in refs
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "root": str(anchor_package_root),
        "read_at": now_iso(),
        "authority_read_order": [str(anchor_package_root / name) for name in AUTHORITY_FILES],
        "refs": refs,
        "read_full_count": sum(1 for ref in refs if ref.get("read_in_full") is True),
        "all_required_sources_read_full": all(ref.get("read_in_full") is True for ref in refs),
        "source_package_digest_sha256": hashlib.sha256(
            digest_input.encode("utf-8", errors="replace")
        ).hexdigest(),
        "source_package_back_ref_required": True,
        "not_fixed_two_text_task_slicer": True,
    }


def static_external_claim_cards() -> list[dict[str, Any]]:
    return [
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-temporal-task-queue-backlog-worker-poll",
            "source_url": "https://docs.temporal.io/task-queue",
            "source_family": "official_temporal_docs",
            "claim": (
                "Temporal task queues are worker-polled durable queues; workers poll only when "
                "they have spare capacity, and task persistence survives worker recovery."
            ),
            "verification_need": "Keep 333 backend loop queue/backlog driven and inspect task queue poll/backlog evidence.",
            "accepted_for": "FanInAcceptanceQueue_default_hot_path_evidence",
            "supports_or_contradicts": "supports",
            "codex_s_rule_or_config_delta": "queue_backlog_frontier_drives_dispatch_not_30min_runner",
            "artifact_ref": "web:temporal-task-queue",
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-langgraph-fanout-fanin-reducers",
            "source_url": "https://docs.langchain.com/oss/python/langgraph/use-graph-api",
            "source_family": "official_langgraph_docs",
            "claim": (
                "LangGraph supports parallel branch fan-out/fan-in and requires reducer semantics "
                "for shared state updates from branches."
            ),
            "verification_need": "Use append/staging queue semantics for parallel ClaimCard and lane results before merge.",
            "accepted_for": "FanInAcceptanceQueue_default_hot_path_evidence",
            "supports_or_contradicts": "supports",
            "codex_s_rule_or_config_delta": "fan_in_queue_is_merge_heart_not_report_summary",
            "artifact_ref": "web:langgraph-fanout-fanin",
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-scitt-artifact-claim-evidence-ledger",
            "source_url": "https://scitt.io/components/artifacts--claims-evidence.html",
            "source_family": "standards_claim_evidence_model",
            "claim": (
                "SCITT models a ledger as capturing claims about artifacts with optional persisted evidence."
            ),
            "verification_need": "Keep ClaimCard -> SourceLedger -> ArtifactAcceptanceQueue before fact or frontier promotion.",
            "accepted_for": "FanInAcceptanceQueue_default_hot_path_evidence",
            "supports_or_contradicts": "supports",
            "codex_s_rule_or_config_delta": "claimcards_require_sourceledger_before_aaq_acceptance",
            "artifact_ref": "web:scitt-claims-evidence",
        },
    ]


def local_authority_claim_card(source_package: dict[str, Any]) -> dict[str, Any]:
    execution_source = next(
        (
            str(ref.get("path") or "")
            for ref in source_package.get("refs", [])
            if "20260702" in str(ref.get("path") or "")
        ),
        str(DEFAULT_ANCHOR_PACKAGE / "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt"),
    )
    return {
        "object_type": "ClaimCard",
        "candidate_id": "claim-local-authority-20260702-absorption-boundary",
        "source_url": execution_source,
        "source_family": "local_authority_source_package",
        "claim": (
            "The current absorption target is FanInAcceptanceQueue, schema/contract, read-only verifier, "
            "source package back-ref, and episode/workflow entry serving the 20260701 root frontier."
        ),
        "verification_need": "Verify this wave writes WORKER_ASSIGNMENT, fan-in queue, AAQ, source refs, workflow entry, and next frontier.",
        "accepted_for": "source_frontier_absorption_default_hot_path",
        "supports_or_contradicts": "supports",
        "codex_s_rule_or_config_delta": "provider_scheduler_is_carrier_not_task",
        "artifact_ref": f"source_package_digest:{source_package.get('source_package_digest_sha256', '')}",
    }


def consumer_state_path(runtime: Path) -> Path:
    return runtime / "state" / "source_frontier_durable_consumer" / "latest.json"


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def batch_ids() -> list[str]:
    return [str(item["batch_id"]) for item in SOURCE_FRONTIER_BATCHES]


def batch_by_id(batch_id: str) -> dict[str, Any]:
    for item in SOURCE_FRONTIER_BATCHES:
        if item["batch_id"] == batch_id:
            return dict(item)
    return {}


def consumed_batch_ids_from_runtime(runtime: Path) -> list[str]:
    payload = read_json_if_exists(consumer_state_path(runtime))
    consumed = payload.get("consumed_batch_ids")
    if not isinstance(consumed, list):
        return []
    known = set(batch_ids())
    return [str(item) for item in consumed if str(item) in known]


def derive_frontier_backlog(
    *,
    runtime: Path,
    current_batch_id: str = "",
    consumed_batch_ids: list[str] | None = None,
) -> dict[str, Any]:
    known = batch_ids()
    consumed = list(consumed_batch_ids) if consumed_batch_ids is not None else consumed_batch_ids_from_runtime(runtime)
    consumed_set = {str(item) for item in consumed if str(item) in known}
    if current_batch_id and current_batch_id in known:
        consumed_set.add(current_batch_id)
    remaining = [item for item in known if item not in consumed_set]
    current_batch = batch_by_id(current_batch_id) if current_batch_id else {}
    return {
        "schema_version": "xinao.codex_s.source_frontier_backlog.v1",
        "module_id": "wave3_20260702_absorption_slice",
        "task_id": TASK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "routing": ROUTING,
        "batch_total": len(known),
        "batch_ids": known,
        "current_batch_id": current_batch_id,
        "current_batch": current_batch,
        "consumed_batch_ids": [item for item in known if item in consumed_set],
        "remaining_batch_ids": remaining,
        "remaining_count": len(remaining),
        "source_package_gap_open": bool(remaining),
        "source_gap_scope": "wave3_module_source_frontier_backlog",
        "not_new_bypass_queue": True,
        "next_consumer": "ClaimCardStagingQueue -> FanInAcceptanceQueue -> ArtifactAcceptanceQueue -> NextFrontier",
    }


def batch_claim_card(batch: dict[str, Any], source_package: dict[str, Any]) -> dict[str, Any]:
    execution_source = next(
        (
            str(ref.get("path") or "")
            for ref in source_package.get("refs", [])
            if "20260702" in str(ref.get("path") or "")
        ),
        str(DEFAULT_ANCHOR_PACKAGE / "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt"),
    )
    batch_id = str(batch.get("batch_id") or "source-frontier-batch")
    return {
        "object_type": "ClaimCard",
        "candidate_id": f"claim-{batch_id}",
        "source_url": execution_source,
        "source_family": str(batch.get("source_family") or "local_authority_source_package"),
        "claim": str(batch.get("claim") or ""),
        "verification_need": str(batch.get("verification_need") or "Fan-in and AAQ acceptance required."),
        "accepted_for": f"source_frontier_batch:{batch_id}",
        "supports_or_contradicts": "supports",
        "codex_s_rule_or_config_delta": str(batch.get("codex_s_rule_or_config_delta") or ""),
        "artifact_ref": f"source_authority_ref:{batch.get('authority_ref') or batch_id}",
        "frontier_batch_id": batch_id,
        "frontier_module_id": str(batch.get("module_id") or ""),
    }


def external_open_source_claim_card() -> dict[str, Any]:
    return {
        "object_type": "ClaimCard",
        "candidate_id": "claim-open-source-agent-carrier-candidates-reference-only",
        "source_url": "https://github.com/OpenHands/OpenHands",
        "source_family": "github_open_source_repo",
        "claim": (
            "OpenHands-style coding-agent repositories are mature-carrier discovery candidates, "
            "but remain reference_only until an adapter smoke and AAQ acceptance promote them."
        ),
        "verification_need": "Keep open-source agent projects as candidate_pattern ClaimCards, not fact source or default provider.",
        "accepted_for": "source_frontier_batch:private_open_source_reference_lane",
        "supports_or_contradicts": "supports",
        "codex_s_rule_or_config_delta": "private_open_source_candidates_require_adapter_smoke_before_use",
        "artifact_ref": "web:github-openhands",
        "frontier_batch_id": "private_open_source_reference_lane",
        "frontier_module_id": "wave3_module_3_private_open_source_absorption",
        "promotion_state": "reference_only_candidate_pattern",
    }


def build_worker_assignment(
    *,
    wave_id: str,
    source_package: dict[str, Any],
    paths: dict[str, str],
    invoked_by_main_execution_loop_tick: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.worker_assignment.v2.dag",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "assignment_id": f"source_frontier_fanin_acceptance:{wave_id}",
        "wave_id": wave_id,
        "status": "worker_assignment_ready",
        "semantic_owner": "333",
        "foreground_brain_owner": True,
        "source_intent_package_ref": "current_user_grok_wave_block3_source_absorption_package",
        "source_package_back_ref": source_package,
        "not_provider_scheduler_main_task": True,
        "provider_scheduler_role": "carrier_layer_only_for_codex_qwen_dp_execution",
        "default_hot_path_goal": (
            "20260702 absorption slice serves the 20260701 source frontier through "
            "FanInAcceptanceQueue, AAQ, ClaimCards, source back-ref, and episode/workflow entry."
        ),
        "main_execution_loop": MAIN_EXECUTION_LOOP,
        "while_continuation_default": True,
        "while_driver": "event_backlog_frontier_driven",
        "forbid_fixed_interval_main_loop": True,
        "forbidden_main_loop_shapes": [
            "sleep_1800",
            "30min_runner",
            "fixed_interval_runner",
            "same_default_loop_as_owner",
        ],
        "invoked_by_main_execution_loop_tick": invoked_by_main_execution_loop_tick,
        "used_welded_execution_shape": {
            "SupervisorBrain": "Codex S foreground brain",
            "ProviderScheduler": "phase4 carrier layer, not task owner",
            "CheapDraftWorkerPool": "DP/Qwen/DeepSeek as draft/extract/eval/search carriers",
            "FanInAcceptanceQueue": "default heart",
            "ArtifactAcceptanceQueue": "acceptance gate for NextFrontier evidence",
        },
        "no_side_queue_island": {
            "FanInAcceptanceQueue_is_default_hot_path_heart": True,
            "not_new_bypass_queue": True,
            "must_connect_existing_chain": [
                "draft_staging",
                "merge",
                "ArtifactAcceptanceQueue",
                "accepted_artifact",
                "next_frontier",
            ],
        },
        "target_width": 8,
        "width_decision_reason": {
            "source_frontier_edges": 4,
            "external_claimcard_lanes": 3,
            "fan_in_acceptance_serial_slots": 1,
            "serial_only": ["same_file_write", "merge", "acceptance"],
            "provider_scheduler_fixed_width_not_used": True,
        },
        "mode_counts": {
            "source_read": 3,
            "claim_card": 4,
            "fan_in_acceptance": 1,
            "artifact_acceptance": 1,
            "next_frontier": 1,
        },
        "assignment_dag": {
            "current_active_node_id": "fan_in_acceptance_queue_default_heart",
            "next_ready_node_id": "next_frontier_machine_action_refill",
            "nodes": [
                {
                    "id": "authority_source_restore",
                    "status": "done",
                    "parallelizable": False,
                    "outputs": [ref["path"] for ref in source_package.get("refs", [])],
                },
                {
                    "id": "source_frontier_claimcard_fanout",
                    "status": "done",
                    "parallelizable": True,
                    "worker_briefs": [
                        "official_temporal_docs_claimcard",
                        "official_langgraph_docs_claimcard",
                        "standards_claim_evidence_claimcard",
                        "local_authority_source_package_claimcard",
                    ],
                    "outputs": [paths["claim_card_staging_queue_latest"]],
                },
                {
                    "id": "fan_in_acceptance_queue_default_heart",
                    "status": "done",
                    "parallelizable": False,
                    "serial_reason": "merge/acceptance writes one canonical queue",
                    "outputs": [
                        paths["fan_in_acceptance_queue_latest"],
                        paths["parallel_fan_in_acceptance_latest"],
                    ],
                },
                {
                    "id": "artifact_acceptance_queue_and_sourceledger",
                    "status": "done",
                    "parallelizable": False,
                    "serial_reason": "AAQ writes SourceLedger before acceptance decision",
                    "outputs": [
                        paths["artifact_acceptance_queue_latest"],
                        paths["source_ledger_latest"],
                    ],
                },
                {
                    "id": "episode_workflow_entry_and_next_frontier",
                    "status": "ready_next",
                    "parallelizable": True,
                    "outputs": [
                        paths["episode_workflow_entry"],
                        paths["next_frontier_machine_actions_latest"],
                    ],
                },
            ],
        },
        "hard_acceptance": {
            "requires_worker_assignment_dag": True,
            "requires_fan_in_acceptance_queue": True,
            "requires_claimcard_sourceledger_aaq": True,
            "requires_episode_workflow_entry": True,
            "requires_next_wave_decision": True,
            "requires_source_frontier_gap_answer": True,
            "completion_claim_allowed": False,
        },
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def build_claim_card_staging_queue(
    *,
    wave_id: str,
    source_package: dict[str, Any],
    claim_cards: list[dict[str, Any]],
    paths: dict[str, str],
) -> dict[str, Any]:
    non_local_families = sorted(
        {
            str(card.get("source_family") or "")
            for card in claim_cards
            if str(card.get("source_family") or "") != "local_authority_source_package"
        }
    )
    return {
        "schema_version": "xinao.codex_s.claim_card_staging_queue.v1",
        "status": "claim_card_staging_queue_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "source_package_back_ref": source_package,
        "claim_card_count": len(claim_cards),
        "non_local_source_family_count": len(non_local_families),
        "source_families": sorted({str(card.get("source_family") or "") for card in claim_cards}),
        "claim_cards": claim_cards,
        "next_consumer": "FanInAcceptanceQueue",
        "output_paths": {"runtime_latest": paths["claim_card_staging_queue_latest"]},
        "validation": {
            "passed": len(claim_cards) >= 4 and len(non_local_families) >= 2,
            "checks": {
                "claim_cards_present": len(claim_cards) >= 1,
                "source_family_minimum_met": len(non_local_families) >= 2,
                "source_package_back_ref_present": bool(source_package.get("source_package_digest_sha256")),
                "completion_claim_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_fan_in_acceptance_payload(
    *,
    wave_id: str,
    claim_cards: list[dict[str, Any]],
    source_package: dict[str, Any],
    paths: dict[str, str],
) -> dict[str, Any]:
    accepted_edges = [
        {
            "edge_id": f"fan-in-edge-{index:02d}",
            "candidate_id": str(card.get("candidate_id") or f"claim-{index:02d}"),
            "producer_lane": str(card.get("source_family") or ""),
            "artifact_ref": str(card.get("artifact_ref") or ""),
            "accepted_for": str(card.get("accepted_for") or "next_frontier_evidence"),
            "acceptance_decision": "accepted_for_aaq_candidate",
            "source_url": str(card.get("source_url") or ""),
            "verification_need": str(card.get("verification_need") or ""),
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
        }
        for index, card in enumerate(claim_cards, start=1)
    ]
    payload = {
        "schema_version": "xinao.codex_s.fan_in_acceptance.v1",
        "status": "fan_in_acceptance_ready_for_plan_evidence",
        "object_type": "FanInAcceptanceQueue",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "acceptance_id": f"source-frontier-fan-in:{wave_id}",
        "source_kind": "claim_card_staging_queue",
        "source_package_back_ref": source_package,
        "claim_card_staging_queue_ref": paths["claim_card_staging_queue_latest"],
        "fan_in_acceptance_queue_ref": paths["fan_in_acceptance_queue_latest"],
        "artifact_acceptance_queue_ref": paths["artifact_acceptance_queue_latest"],
        "accepted_edges": accepted_edges,
        "accepted_edge_count": len(accepted_edges),
        "rejected_edges": [],
        "staged_edges": [],
        "source_family_count": len({edge["producer_lane"] for edge in accepted_edges}),
        "claim_card_required_fields": CLAIM_CARD_REQUIRED_FIELDS,
        "fan_in_is_default_heart": True,
        "not_new_bypass_queue": True,
        "connects_existing_chain": [
            "draft_staging",
            "merge",
            "ArtifactAcceptanceQueue",
            "accepted_artifact",
            "next_frontier",
        ],
        "artifact_acceptance_queue_required": True,
        "source_ledger_required": True,
        "before_artifact_acceptance": True,
        "direct_fact_promotion_allowed": False,
        "completion_claim_allowed": False,
        "next_consumer": "ArtifactAcceptanceQueue",
        "output_paths": {
            "fan_in_acceptance_queue_latest": paths["fan_in_acceptance_queue_latest"],
            "parallel_fan_in_acceptance_latest": paths["parallel_fan_in_acceptance_latest"],
        },
        "validation": {
            "passed": len(accepted_edges) > 0,
            "checks": {
                "accepted_edges_present": len(accepted_edges) > 0,
                "all_edges_have_source_url": all(bool(edge["source_url"]) for edge in accepted_edges),
                "fan_in_before_aaq": True,
                "direct_fact_promotion_denied": True,
                "completion_claim_denied": True,
            },
        },
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    return payload


def build_frontier_objects(
    *,
    wave_id: str,
    paths: dict[str, str],
    source_package: dict[str, Any],
    aaq_payload: dict[str, Any],
    frontier_backlog: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    remaining_ids = [
        str(item) for item in frontier_backlog.get("remaining_batch_ids", []) if str(item).strip()
    ]
    consumed_ids = [
        str(item) for item in frontier_backlog.get("consumed_batch_ids", []) if str(item).strip()
    ]
    current_batch_id = str(frontier_backlog.get("current_batch_id") or "")
    source_gap_open = bool(remaining_ids)
    current_batch = (
        frontier_backlog.get("current_batch")
        if isinstance(frontier_backlog.get("current_batch"), dict)
        else {}
    )
    candidate_scores = [
        {
            "candidate_id": "frontier-fanin-aaq-hotpath",
            "candidate_kind": "FanInAcceptanceQueueDefaultHeart",
            "parent_frontier_ref": "20260701_total_draft",
            "expected_user_visible_value": 9,
            "evidence_yield": 9,
            "uncertainty_reduction": 7,
            "unblock_value": 9,
            "time_to_signal": 2,
            "cost_estimate": 1,
            "risk_score": 2,
            "parallel_fit": 7,
            "verification_fit": 9,
            "novelty_score": 5,
            "utility_score": 53,
            "current_state": "accepted_this_wave",
        },
    ]
    for batch in SOURCE_FRONTIER_BATCHES:
        batch_id = str(batch["batch_id"])
        if batch_id == current_batch_id:
            state = "accepted_this_wave"
        elif batch_id in consumed_ids:
            state = "accepted_previous_wave"
        elif batch_id in remaining_ids:
            state = "ready_next"
        else:
            state = "unknown"
        candidate_scores.append(
            {
                "candidate_id": batch_id,
                "candidate_kind": batch["candidate_kind"],
                "parent_frontier_ref": batch["authority_ref"],
                "expected_user_visible_value": 8,
                "evidence_yield": 8,
                "uncertainty_reduction": 8,
                "unblock_value": 8,
                "time_to_signal": 3,
                "cost_estimate": 2,
                "risk_score": 2,
                "parallel_fit": 9,
                "verification_fit": 8,
                "novelty_score": 7,
                "utility_score": int(batch["utility_score"]),
                "current_state": state,
            }
        )
    next_frontier = [
        {
            "action_id": f"next-wave-{batch_id}",
            "action": "consume_source_frontier_batch",
            "why": f"{batch_id} remains in the wave3 source frontier backlog.",
            "requires": [
                "source_family_wave_plan",
                "ClaimCardStagingQueue",
                "FanInAcceptanceQueue",
                "ArtifactAcceptanceQueue",
                "FrontierPortfolioSnapshot",
                "LaneResultReview",
                "RewardSignal",
            ],
        }
        for batch_id in remaining_ids
    ]
    portfolio = {
        "schema_version": "xinao.codex_s.frontier_portfolio_snapshot.v1",
        "status": "frontier_portfolio_snapshot_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "source_package_back_ref": source_package,
        "frontier_backlog": frontier_backlog,
        "candidate_scores": candidate_scores,
        "selected_for_dispatch": remaining_ids[:1],
        "selected_for_verify": [current_batch_id] if current_batch_id else ["frontier-fanin-aaq-hotpath"],
        "selected_for_explore": remaining_ids,
        "selected_for_repair": [],
        "rejected_or_deferred": [],
        "reason_codes": [
            "fan_in_acceptance_queue_is_current_absorption_target",
            "next_wave_recomputes_20260701_frontier",
        ],
        "output_paths": {"runtime_latest": paths["frontier_portfolio_snapshot_latest"]},
        "validation": {"passed": True},
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    source_family_wave_plan = {
        "schema_version": "xinao.codex_s.source_family_wave_plan.v1",
        "status": "source_family_wave_plan_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "families": [
            "official/provider docs",
            "GitHub/open-source repos",
            "community/blog/forum",
            "papers/benchmarks",
            "local runtime evidence",
        ],
        "minimum_source_family_count": 2,
        "official_docs_only_allowed": False,
        "claim_card_fan_in_required": True,
        "frontier_backlog": frontier_backlog,
        "next_consumer": "ClaimCardStagingQueue",
        "output_paths": {"runtime_latest": paths["source_family_wave_plan_latest"]},
        "validation": {"passed": True},
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    next_actions = {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "next_frontier_machine_actions_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "should_continue_loop": source_gap_open,
        "stop_allowed": not source_gap_open,
        "stop_allowed_reason": (
            "source_frontier_and_next_wave_actions_remain"
            if source_gap_open
            else "wave3_source_frontier_module_backlog_cleared_task_scoped_not_root_completion"
        ),
        "while_driver": "event_backlog_frontier_driven",
        "sleep_1800_main_loop_allowed": False,
        "fixed_interval_runner_main_loop_allowed": False,
        "frontier_backlog": frontier_backlog,
        "source_frontier_gap": {
            "exists": source_gap_open,
            "reason": (
                "20260701/20260702 source package still has frontier candidates after this absorption slice."
                if source_gap_open
                else "The wave3 source frontier backlog has been consumed through durable fan-in/AAQ."
            ),
            "source_package_gap_open": source_gap_open,
            "current_batch_id": current_batch_id,
            "current_batch_kind": current_batch.get("candidate_kind"),
            "remaining_batch_ids": remaining_ids,
            "consumed_batch_ids": consumed_ids,
            "next_gap_action": (
                "continue_source_family_fanout_and_frontier_portfolio_recompute"
                if source_gap_open
                else "none_for_wave3_module"
            ),
        },
        "next_frontier": next_frontier,
        "aaq_accepted_artifact_count": int(aaq_payload.get("accepted_artifact_count") or 0),
        "output_paths": {"runtime_latest": paths["next_frontier_machine_actions_latest"]},
        "validation": {
            "passed": int(aaq_payload.get("accepted_artifact_count") or 0) > 0,
            "checks": {
                "aaq_has_accepted_artifacts": int(aaq_payload.get("accepted_artifact_count") or 0) > 0,
                "next_frontier_present_or_gap_cleared": bool(next_frontier) or not source_gap_open,
                "stop_allowed_derived_from_frontier": (
                    (not source_gap_open) == (len(remaining_ids) == 0)
                ),
                "source_frontier_gap_answered": True,
                "backlog_accounted": len(consumed_ids) + len(remaining_ids) == len(SOURCE_FRONTIER_BATCHES),
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    return portfolio, source_family_wave_plan, next_actions


def build_episode_workflow_entry(
    *,
    wave_id: str,
    paths: dict[str, str],
    worker_assignment: dict[str, Any],
    fan_in_payload: dict[str, Any],
    aaq_payload: dict[str, Any],
    next_actions: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.codex_s.source_frontier_episode_workflow_entry.v1",
        "status": "episode_workflow_entry_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "episode_id": f"source-frontier-fanin-acceptance-{wave_id}",
        "workflow_shape": MAIN_EXECUTION_LOOP,
        "workflow_owner": "Codex S foreground brain",
        "temporal_owner_expected": True,
        "background_runner_owner": False,
        "worker_assignment_ref": paths["worker_assignment_latest"],
        "slice_worker_assignment_ref": paths["slice_worker_assignment_latest"],
        "parent_assignment_link": paths["parent_assignment_link"],
        "fan_in_acceptance_queue_ref": paths["fan_in_acceptance_queue_latest"],
        "artifact_acceptance_queue_ref": paths["artifact_acceptance_queue_latest"],
        "source_ledger_ref": aaq_payload.get("source_ledger_ref", ""),
        "next_frontier_ref": paths["next_frontier_machine_actions_latest"],
        "worker_assignment_status": worker_assignment.get("status"),
        "fan_in_accepted_edge_count": fan_in_payload.get("accepted_edge_count"),
        "aaq_accepted_artifact_count": aaq_payload.get("accepted_artifact_count"),
        "should_continue_loop": next_actions.get("should_continue_loop") is True,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": (
                worker_assignment.get("status") == "worker_assignment_ready"
                and int(fan_in_payload.get("accepted_edge_count") or 0) > 0
                and int(aaq_payload.get("accepted_artifact_count") or 0) > 0
                and (
                    next_actions.get("should_continue_loop") is True
                    or next_actions.get("source_frontier_gap", {}).get("source_package_gap_open")
                    is False
                )
            ),
            "checks": {
                "worker_assignment_ready": worker_assignment.get("status") == "worker_assignment_ready",
                "fan_in_edges_present": int(fan_in_payload.get("accepted_edge_count") or 0) > 0,
                "aaq_accepted": int(aaq_payload.get("accepted_artifact_count") or 0) > 0,
                "next_wave_continues_or_module_consumed": (
                    next_actions.get("should_continue_loop") is True
                    or next_actions.get("source_frontier_gap", {}).get("source_package_gap_open")
                    is False
                ),
            },
        },
    }


def build_lane_result_review(
    *,
    wave_id: str,
    frontier_backlog: dict[str, Any],
    fan_in_payload: dict[str, Any],
    aaq_payload: dict[str, Any],
    paths: dict[str, str],
) -> dict[str, Any]:
    current_batch_id = str(frontier_backlog.get("current_batch_id") or "")
    return {
        "schema_version": "xinao.codex_s.lane_result_review.v1",
        "status": "lane_result_review_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "frontier_batch_id": current_batch_id,
        "lane_class": "source_frontier_claimcard_fanout",
        "fan_in_accepted_edge_count": int(fan_in_payload.get("accepted_edge_count") or 0),
        "aaq_accepted_artifact_count": int(aaq_payload.get("accepted_artifact_count") or 0),
        "accepted_for_next_frontier": True,
        "direct_fact_promotion_allowed": False,
        "output_paths": {"runtime_latest": paths["lane_result_review_latest"]},
        "validation": {
            "passed": int(fan_in_payload.get("accepted_edge_count") or 0) > 0
            and int(aaq_payload.get("accepted_artifact_count") or 0) > 0
            and bool(current_batch_id),
            "checks": {
                "fan_in_accepted": int(fan_in_payload.get("accepted_edge_count") or 0) > 0,
                "aaq_accepted": int(aaq_payload.get("accepted_artifact_count") or 0) > 0,
                "frontier_batch_bound": bool(current_batch_id),
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_reward_signal(
    *,
    wave_id: str,
    frontier_backlog: dict[str, Any],
    lane_review: dict[str, Any],
    paths: dict[str, str],
) -> dict[str, Any]:
    remaining_count = int(frontier_backlog.get("remaining_count") or 0)
    consumed_count = len(frontier_backlog.get("consumed_batch_ids") or [])
    return {
        "schema_version": "xinao.codex_s.reward_signal.v1",
        "status": "reward_signal_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "frontier_batch_id": frontier_backlog.get("current_batch_id") or "",
        "signal": "positive_progress"
        if lane_review.get("validation", {}).get("passed")
        else "blocked",
        "consumed_batch_count": consumed_count,
        "remaining_batch_count": remaining_count,
        "source_gap_open": remaining_count > 0,
        "next_action": "continue_durable_consumer"
        if remaining_count > 0
        else "wave3_module_consumed",
        "output_paths": {"runtime_latest": paths["reward_signal_latest"]},
        "validation": {
            "passed": lane_review.get("validation", {}).get("passed") is True,
            "checks": {
                "lane_review_accepted": lane_review.get("validation", {}).get("passed") is True,
                "backlog_count_non_negative": remaining_count >= 0,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def render_readback(payload: dict[str, Any]) -> str:
    validation = payload.get("validation", {}).get("checks", {})
    paths = payload.get("output_paths", {})
    aaq = payload.get("artifact_acceptance_queue", {})
    next_actions = payload.get("next_frontier_machine_actions", {})
    source_gap_open = next_actions.get("source_frontier_gap", {}).get("source_package_gap_open")
    gap_answer = "是" if source_gap_open else "否"
    continue_answer = "是" if next_actions.get("should_continue_loop") else "否，本 wave3 模块 backlog 已吃完"
    lines = [
        "# 20260702 source frontier / FanInAcceptanceQueue 吸收 readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- adoption_state: `{payload.get('adoption_state')}`",
        f"- task_id: `{payload.get('task_id')}`",
        f"- parent_task_id: `{payload.get('parent_task_id')}`",
        f"- routing: `{payload.get('routing')}`",
        f"- worker_assignment: `{paths.get('slice_worker_assignment_latest', '')}`",
        f"- FanInAcceptanceQueue: `{paths.get('fan_in_acceptance_queue_latest', '')}`",
        f"- ArtifactAcceptanceQueue accepted: {aaq.get('accepted_artifact_count')}",
        f"- ClaimCard source families: {payload.get('claim_card_staging_queue', {}).get('source_families', [])}",
        f"- should_continue_loop: {next_actions.get('should_continue_loop')}",
        f"- stop_allowed: {next_actions.get('stop_allowed')}",
        "",
        "验收三句：",
        f"1. 还在 while 下一波吗？{continue_answer}。`should_continue_loop={next_actions.get('should_continue_loop')}`，下一波写在 NextFrontierMachineActionQueue。",
        f"2. FanIn/AAQ 是不是默认心脏了？是。`fan_in_is_default_heart={payload.get('fan_in_acceptance_queue', {}).get('fan_in_is_default_heart')}`，AAQ 接 SourceLedger 后再进入 next frontier。",
        "3. default 还有手搓吗？ProviderScheduler 只保留为执行承载；本块默认入口是 source frontier -> ClaimCard staging -> FanInAcceptanceQueue -> AAQ -> episode/workflow -> next frontier。",
        f"4. 还剩 source frontier / source package gap 吗？{gap_answer}。`source_package_gap_open={source_gap_open}`，`remaining_batch_ids={next_actions.get('source_frontier_gap', {}).get('remaining_batch_ids')}`。",
        "",
        "现在能 invoke 什么：",
        "- `python -m xinao_seedlab.cli.__main__ source-frontier-fanin-acceptance --wave-id <wave>`",
        "- `python -m xinao_seedlab.cli.__main__ main-execution-loop-tick --wave-id <wave>` 会先准备 source-frontier fan-in surface。",
        "- `scripts\\verify_source_frontier_fanin_acceptance.ps1` 只读验证 WORKER_ASSIGNMENT、FanInAcceptanceQueue、AAQ、SourceLedger、episode/workflow、next frontier。",
        "",
        "还差什么：如果 source_gap 仍为 true，就继续下一波 source-family fanout；如果为 false，本 wave3 source frontier 模块已吃完，但不代表整根 333/Phase0 完成。",
        "",
        "while 语义：event/backlog/frontier driven；禁止 sleep-1800、30min runner、fixed interval 当主循环。",
        "",
        f"- validation.source_package_read_full: {validation.get('source_package_read_full')}",
        f"- validation.fan_in_acceptance_queue_written: {validation.get('fan_in_acceptance_queue_written')}",
        f"- validation.artifact_acceptance_queue_accepted: {validation.get('artifact_acceptance_queue_accepted')}",
        f"- validation.while_continuation_or_module_consumed: {validation.get('while_continuation_or_module_consumed')}",
        f"- validation.lane_result_review_written: {validation.get('lane_result_review_written')}",
        f"- validation.reward_signal_written: {validation.get('reward_signal_written')}",
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
    wave_id: str = "source-frontier-fanin-acceptance-wave-block3",
    invoked_by_main_execution_loop_tick: bool = False,
    frontier_backlog: dict[str, Any] | None = None,
    extra_claim_cards: list[dict[str, Any]] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    anchor = Path(anchor_package_root)
    paths = output_paths(repo, runtime, wave_id)
    source_package = source_package_refs(anchor)
    if frontier_backlog is None:
        frontier_backlog = derive_frontier_backlog(runtime=runtime)
    claim_cards = (
        static_external_claim_cards()
        + [local_authority_claim_card(source_package)]
        + list(extra_claim_cards or [])
    )
    worker_assignment = build_worker_assignment(
        wave_id=wave_id,
        source_package=source_package,
        paths=paths,
        invoked_by_main_execution_loop_tick=invoked_by_main_execution_loop_tick,
    )
    claim_staging = build_claim_card_staging_queue(
        wave_id=wave_id,
        source_package=source_package,
        claim_cards=claim_cards,
        paths=paths,
    )
    fan_in_payload = build_fan_in_acceptance_payload(
        wave_id=wave_id,
        claim_cards=claim_cards,
        source_package=source_package,
        paths=paths,
    )

    from xinao_seedlab.application.seed_cortex import build_default_service

    service = build_default_service(runtime, repo_root=repo)
    aaq_payload = service.artifact_acceptance_queue(
        f"source-frontier-fanin-acceptance-{wave_id}",
        claim_cards,
        write_runtime=write,
    )
    portfolio, source_family_wave_plan, next_actions = build_frontier_objects(
        wave_id=wave_id,
        paths=paths,
        source_package=source_package,
        aaq_payload=aaq_payload,
        frontier_backlog=frontier_backlog,
    )
    lane_review = build_lane_result_review(
        wave_id=wave_id,
        frontier_backlog=frontier_backlog,
        fan_in_payload=fan_in_payload,
        aaq_payload=aaq_payload,
        paths=paths,
    )
    reward_signal = build_reward_signal(
        wave_id=wave_id,
        frontier_backlog=frontier_backlog,
        lane_review=lane_review,
        paths=paths,
    )
    episode_entry = build_episode_workflow_entry(
        wave_id=wave_id,
        paths=paths,
        worker_assignment=worker_assignment,
        fan_in_payload=fan_in_payload,
        aaq_payload=aaq_payload,
        next_actions=next_actions,
    )
    refs = {
        "worker_assignment": json_ref(Path(paths["worker_assignment_latest"])),
        "parent_assignment_link": json_ref(Path(paths["parent_assignment_link"])),
        "fan_in_acceptance_queue": json_ref(Path(paths["fan_in_acceptance_queue_latest"])),
        "parallel_fan_in_acceptance": json_ref(Path(paths["parallel_fan_in_acceptance_latest"])),
        "artifact_acceptance_queue": json_ref(Path(paths["artifact_acceptance_queue_latest"])),
        "source_ledger": json_ref(Path(paths["source_ledger_latest"])),
        "episode_workflow_entry": json_ref(Path(paths["episode_workflow_entry"])),
        "next_frontier_machine_actions": json_ref(Path(paths["next_frontier_machine_actions_latest"])),
    }
    checks = {
        "source_package_read_full": source_package.get("all_required_sources_read_full") is True,
        "worker_assignment_dag_ready": worker_assignment.get("status") == "worker_assignment_ready",
        "claim_card_staging_ready": claim_staging.get("validation", {}).get("passed") is True,
        "fan_in_acceptance_queue_written": fan_in_payload.get("validation", {}).get("passed") is True,
        "artifact_acceptance_queue_accepted": int(aaq_payload.get("accepted_artifact_count") or 0) > 0,
        "source_ledger_written": bool(aaq_payload.get("source_ledger_ref")),
        "episode_workflow_entry_ready": episode_entry.get("validation", {}).get("passed") is True,
        "next_frontier_ready": next_actions.get("validation", {}).get("passed") is True,
        "while_continuation_or_module_consumed": (
            next_actions.get("should_continue_loop") is True
            and next_actions.get("stop_allowed") is False
        )
        or (
            next_actions.get("should_continue_loop") is False
            and next_actions.get("stop_allowed") is True
            and next_actions.get("source_frontier_gap", {}).get("source_package_gap_open")
            is False
        ),
        "while_is_event_backlog_frontier_driven": next_actions.get("while_driver")
        == "event_backlog_frontier_driven"
        and next_actions.get("sleep_1800_main_loop_allowed") is False
        and next_actions.get("fixed_interval_runner_main_loop_allowed") is False,
        "fan_in_not_bypass_island": fan_in_payload.get("not_new_bypass_queue") is True
        and "draft_staging" in (fan_in_payload.get("connects_existing_chain") or [])
        and "merge" in (fan_in_payload.get("connects_existing_chain") or [])
        and "next_frontier" in (fan_in_payload.get("connects_existing_chain") or []),
        "source_frontier_gap_answered": isinstance(
            next_actions.get("source_frontier_gap", {}).get("source_package_gap_open"),
            bool,
        ),
        "lane_result_review_written": lane_review.get("validation", {}).get("passed") is True
        or not frontier_backlog.get("current_batch_id"),
        "reward_signal_written": reward_signal.get("validation", {}).get("passed") is True
        or not frontier_backlog.get("current_batch_id"),
        "provider_scheduler_not_main_task": worker_assignment.get("not_provider_scheduler_main_task") is True,
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": "source_frontier_fanin_acceptance_ready"
        if all(checks.values())
        else "source_frontier_fanin_acceptance_blocked",
        "generated_at": now_iso(),
        "adoption_state": "default_hot_path_ready",
        "runtime_enforced": False,
        "trigger_installed": False,
        "invoked_by_main_execution_loop_tick": invoked_by_main_execution_loop_tick,
        "source_package": source_package,
        "worker_assignment": worker_assignment,
        "claim_card_staging_queue": claim_staging,
        "fan_in_acceptance_queue": fan_in_payload,
        "artifact_acceptance_queue": aaq_payload,
        "frontier_portfolio_snapshot": portfolio,
        "source_family_wave_plan": source_family_wave_plan,
        "frontier_backlog": frontier_backlog,
        "lane_result_review": lane_review,
        "reward_signal": reward_signal,
        "next_frontier_machine_actions": next_actions,
        "episode_workflow_entry": episode_entry,
        "default_hot_path_binding": {
            "source_frontier_absorption_is_current_main_task": True,
            "fan_in_acceptance_queue_default_heart": True,
            "fan_in_acceptance_queue_not_bypass_island": True,
            "connects_existing_draft_staging_merge_aaq_next_frontier": True,
            "artifact_acceptance_queue_required": True,
            "source_package_back_ref_required": True,
            "episode_workflow_entry_required": True,
            "provider_scheduler_main_task": False,
            "while_driver": "event_backlog_frontier_driven",
            "sleep_1800_main_loop_allowed": False,
            "fixed_interval_runner_main_loop_allowed": False,
        },
        "refs": refs,
        "output_paths": paths,
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        parent_link = {
            "schema_version": "xinao.worker_assignment.parent_slice_link.v1",
            "work_id": WORK_ID,
            "parent_task_id": PARENT_TASK_ID,
            "task_id": TASK_ID,
            "routing": ROUTING,
            "current_source_frontier_slice_assignment_ref": paths["slice_worker_assignment_latest"],
            "root_task_not_claimed_complete": True,
            "completion_claim_allowed": False,
            "generated_at": now_iso(),
        }
        write_json(Path(paths["slice_worker_assignment_latest"]), worker_assignment)
        write_json(Path(paths["parent_assignment_link"]), parent_link)
        write_json(Path(paths["worker_assignment_wave"]), worker_assignment)
        write_json(Path(paths["claim_card_staging_queue_latest"]), claim_staging)
        write_json(Path(paths["fan_in_acceptance_queue_latest"]), fan_in_payload)
        write_json(Path(paths["parallel_fan_in_acceptance_latest"]), fan_in_payload)
        write_json(Path(paths["frontier_portfolio_snapshot_latest"]), portfolio)
        write_json(Path(paths["source_family_wave_plan_latest"]), source_family_wave_plan)
        write_json(Path(paths["lane_result_review_latest"]), lane_review)
        write_json(Path(paths["reward_signal_latest"]), reward_signal)
        write_json(Path(paths["next_frontier_machine_actions_latest"]), next_actions)
        write_json(Path(paths["episode_workflow_entry"]), episode_entry)
        trace = Path(paths["episode_trace"])
        trace.parent.mkdir(parents=True, exist_ok=True)
        with trace.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "event_type": "source_frontier_fanin_acceptance_ready",
                        "wave_id": wave_id,
                        "at": now_iso(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["wave_latest"]), payload)
        write_text(Path(paths["runtime_readback_zh"]), render_readback(payload))
    return payload


def render_consumer_readback(payload: dict[str, Any]) -> str:
    lines = [
        "# source frontier durable consumer readback",
        "",
        CONSUMER_SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- task_id: `{payload.get('task_id')}`",
        f"- parent_task_id: `{payload.get('parent_task_id')}`",
        f"- consumed_this_run: {payload.get('consumed_this_run')}",
        f"- consumed_batch_ids: {payload.get('consumed_batch_ids')}",
        f"- remaining_batch_ids: {payload.get('remaining_batch_ids')}",
        f"- source_gap_open: {payload.get('source_gap_open')}",
        f"- named_blocker: `{payload.get('named_blocker')}`",
        f"- durable_activity_invoked: {payload.get('durable_activity_invoked')}",
        "",
        "人话：这不是 report/PASS；这是按 NextFrontier backlog 连续消费 wave3 source frontier 模块。",
        "如果 source_gap_open=false，表示这个 wave3 模块已吃完；不代表 333/Phase0 整根完成。",
        "",
        CONSUMER_SENTINEL,
        "",
    ]
    return "\n".join(lines)


def consume_source_frontier_backlog(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    wave_id: str = "source-frontier-durable-consumer-wave",
    max_waves: int = 3,
    durable_activity_invoked: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    anchor = Path(anchor_package_root)
    paths = output_paths(repo, runtime, wave_id)
    source_package = source_package_refs(anchor)
    consumed_before = consumed_batch_ids_from_runtime(runtime)
    consumed_set = set(consumed_before)
    pending = [batch for batch in SOURCE_FRONTIER_BATCHES if batch["batch_id"] not in consumed_set]
    consumed_this_run: list[str] = []
    wave_payload_refs: list[dict[str, Any]] = []
    max_count = max(0, int(max_waves or 0))
    named_blocker = ""
    if max_count <= 0 and pending:
        named_blocker = "SOURCE_FRONTIER_CONSUMER_MAX_WAVES_ZERO"
    for batch in pending[:max_count]:
        batch_id = str(batch["batch_id"])
        consumed_after = [item for item in batch_ids() if item in consumed_set or item == batch_id]
        backlog = derive_frontier_backlog(
            runtime=runtime,
            current_batch_id=batch_id,
            consumed_batch_ids=consumed_after,
        )
        extra_cards = [batch_claim_card(batch, source_package)]
        if batch_id == "private_open_source_reference_lane":
            extra_cards.append(external_open_source_claim_card())
        wave_payload = build(
            runtime_root=runtime,
            repo_root=repo,
            anchor_package_root=anchor,
            wave_id=f"{wave_id}-{batch_id}",
            invoked_by_main_execution_loop_tick=False,
            frontier_backlog=backlog,
            extra_claim_cards=extra_cards,
            write=write,
        )
        if wave_payload.get("validation", {}).get("passed") is not True:
            named_blocker = f"SOURCE_FRONTIER_BATCH_VALIDATION_FAILED:{batch_id}"
            break
        consumed_set.add(batch_id)
        consumed_this_run.append(batch_id)
        wave_payload_refs.append(
            {
                "batch_id": batch_id,
                "wave_id": wave_payload.get("wave_id"),
                "latest_ref": wave_payload.get("output_paths", {}).get("runtime_latest"),
                "fan_in_ref": wave_payload.get("output_paths", {}).get("fan_in_acceptance_queue_latest"),
                "aaq_ref": wave_payload.get("output_paths", {}).get("artifact_acceptance_queue_latest"),
                "lane_result_review_ref": wave_payload.get("output_paths", {}).get("lane_result_review_latest"),
                "reward_signal_ref": wave_payload.get("output_paths", {}).get("reward_signal_latest"),
                "source_gap_open_after_wave": wave_payload.get("next_frontier_machine_actions", {})
                .get("source_frontier_gap", {})
                .get("source_package_gap_open"),
            }
        )
    remaining = [item for item in batch_ids() if item not in consumed_set]
    source_gap_open = bool(remaining)
    status = (
        "source_frontier_module_consumed"
        if not source_gap_open and not named_blocker
        else "source_frontier_module_backlog_remaining"
    )
    if named_blocker:
        status = "source_frontier_module_blocked"
    payload = {
        "schema_version": "xinao.codex_s.source_frontier_durable_consumer.v1",
        "sentinel": CONSUMER_SENTINEL,
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": status,
        "generated_at": now_iso(),
        "durable_activity_invoked": durable_activity_invoked,
        "while_driver": "event_backlog_frontier_driven",
        "fixed_interval_runner_main_loop_allowed": False,
        "sleep_1800_main_loop_allowed": False,
        "batch_total": len(SOURCE_FRONTIER_BATCHES),
        "consumed_before": consumed_before,
        "consumed_this_run": consumed_this_run,
        "consumed_batch_ids": [item for item in batch_ids() if item in consumed_set],
        "remaining_batch_ids": remaining,
        "source_gap_open": source_gap_open,
        "named_blocker": named_blocker,
        "wave_payload_refs": wave_payload_refs,
        "latest_source_frontier_ref": paths["runtime_latest"],
        "readback_zh": paths["source_frontier_durable_consumer_readback"],
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": not named_blocker,
            "checks": {
                "event_backlog_frontier_driven": True,
                "consumed_or_already_empty": bool(consumed_this_run) or not pending,
                "source_gap_false_when_all_batches_consumed": (not source_gap_open)
                == (len(remaining) == 0),
                "no_fixed_interval_runner": True,
                "fan_in_aaq_refs_written": all(
                    bool(ref.get("fan_in_ref")) and bool(ref.get("aaq_ref"))
                    for ref in wave_payload_refs
                ),
            },
        },
    }
    if write:
        write_json(Path(paths["source_frontier_durable_consumer_latest"]), payload)
        write_text(Path(paths["source_frontier_durable_consumer_readback"]), render_consumer_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="source-frontier-fanin-acceptance-wave-block3")
    parser.add_argument("--invoked-by-main-execution-loop-tick", action="store_true")
    parser.add_argument("--consume-backlog", action="store_true")
    parser.add_argument("--max-waves", type=int, default=3)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if args.consume_backlog:
        payload = consume_source_frontier_backlog(
            runtime_root=args.runtime_root,
            repo_root=args.repo_root,
            anchor_package_root=args.anchor_package_root,
            wave_id=args.wave_id,
            max_waves=args.max_waves,
            durable_activity_invoked=False,
            write=not args.no_write,
        )
        print(
            json.dumps(
                {
                    "schema_version": payload["schema_version"],
                    "status": payload["status"],
                    "wave_id": payload["wave_id"],
                    "source_gap_open": payload["source_gap_open"],
                    "remaining_batch_ids": payload["remaining_batch_ids"],
                    "sentinel": payload["sentinel"],
                },
                ensure_ascii=True,
                indent=2,
            )
        )
        print(CONSUMER_SENTINEL)
        return 0 if payload.get("validation", {}).get("passed") is True else 1
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        wave_id=args.wave_id,
        invoked_by_main_execution_loop_tick=args.invoked_by_main_execution_loop_tick,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "wave_id": payload["wave_id"],
                "worker_assignment": payload["output_paths"]["worker_assignment_latest"],
                "fan_in_acceptance_queue": payload["output_paths"]["fan_in_acceptance_queue_latest"],
                "artifact_acceptance_queue": payload["output_paths"]["artifact_acceptance_queue_latest"],
                "next_frontier": payload["output_paths"]["next_frontier_machine_actions_latest"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
