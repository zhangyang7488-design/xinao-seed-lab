from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime import completion_claim_payload_builder

SCHEMA_VERSION = "xinao.codex_s.pre_pass_audit_loop.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_PRE_PASS_AUDIT_LOOP_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = "pre_pass_audit_loop_20260704"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_DESKTOP_SPEC = Path(r"C:\Users\xx363\Desktop\新建 文本文档 (2).txt")

AUDIT_LANE_IDS = [
    "hotpath_lane",
    "runtime_lane",
    "provider_lane",
    "mature_capability_lane",
    "source_gap_lane",
    "fanin_lane",
    "completion_boundary_lane",
    "closure_bundle_lane",
    "readback_lane",
    "history_lane",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str, *, limit: int = 96) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value).strip("._")
    cleaned = cleaned or "default"
    if len(cleaned) <= limit:
        return cleaned
    digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{cleaned[: limit - 13]}-{digest}"


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


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "schema_version": payload.get("schema_version", ""),
        "status": payload.get("status", ""),
        "validation_passed": validation.get("passed"),
        "not_execution_controller": payload.get("not_execution_controller"),
        "completion_claim_allowed": payload.get("completion_claim_allowed"),
    }


def output_paths(runtime_root: Path, *, task_id: str, wave_id: str) -> dict[str, str]:
    state_dir = runtime_root / "state" / "pre_pass_audit_loop"
    task_dir = state_dir / "tasks" / safe_stem(task_id)
    return {
        "latest": str(state_dir / "latest.json"),
        "task_wave": str(task_dir / f"{safe_stem(wave_id)}.json"),
        "candidate_snapshot_latest": str(state_dir / "candidate_snapshot_latest.json"),
        "audit_lane_registry_latest": str(state_dir / "audit_lane_registry_latest.json"),
        "audit_fan_in_latest": str(state_dir / "audit_fan_in_latest.json"),
        "repair_plan_latest": str(state_dir / "repair_plan_latest.json"),
        "reaudit_latest": str(state_dir / "reaudit_latest.json"),
        "readback_zh": str(
            runtime_root / "readback" / "zh" / f"pre_pass_audit_loop_{safe_stem(wave_id)}.md"
        ),
    }


def git_head(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def git_dirty(repo_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except Exception:
        return False
    return bool(result.stdout.strip()) if result.returncode == 0 else False


def load_candidate_json(candidate_json: str | Path | None) -> dict[str, Any]:
    if not candidate_json:
        return {}
    path = Path(candidate_json)
    if path.is_file():
        return read_json(path)
    try:
        payload = json.loads(str(candidate_json))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def list_existing_refs(paths: list[Path]) -> list[str]:
    return [str(path) for path in paths if path.is_file()]


def build_candidate_snapshot(
    *,
    runtime_root: Path,
    repo_root: Path,
    task_id: str,
    wave_id: str,
    candidate_json: str | Path | None = None,
    extra_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = runtime_root / "state"
    loaded = load_candidate_json(candidate_json)
    artifact_refs = list(loaded.get("artifact_refs") or [])
    workflow_refs = list(loaded.get("workflow_refs") or [])
    worker_refs = list(loaded.get("worker_ledger_refs") or [])
    source_refs = list(loaded.get("source_frontier_refs") or [])
    provider_refs = list(loaded.get("provider_invocation_refs") or [])
    fan_in_refs = list(loaded.get("fan_in_refs") or [])
    readback_refs = list(loaded.get("readback_refs") or [])

    artifact_refs.extend(
        list_existing_refs(
            [
                state / "modular_dynamic_worker_pool_phase1" / "merge_consumer" / "latest.json",
                state / "artifact_acceptance_queue" / "latest.json",
            ]
        )
    )
    workflow_refs.extend(
        list_existing_refs(
            [
                state
                / "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
                / "latest.json",
                state / "temporal_codex_task_workflow" / "latest.json",
                state / "loop_runtime_state" / "latest.json",
            ]
        )
    )
    worker_refs.extend(
        list_existing_refs(
            [
                state / "worker_dispatch_ledger" / "latest.json",
                state / "worker_dispatch_ledger" / "temporal_activity_latest.json",
                state
                / "worker_dispatch_ledger"
                / "temporal_activity_no_window_dp_worker_pool_phase3_20260704.latest.json",
            ]
        )
    )
    source_refs.extend(
        list_existing_refs(
            [
                state / "source_frontier_durable_consumer" / "latest.json",
                state / "source_family_wave_scheduler" / "latest.json",
                state / "source_ledger" / "latest.json",
            ]
        )
    )
    provider_refs.extend(
        list_existing_refs(
            [
                state / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
                state
                / "modular_dynamic_worker_pool_phase1"
                / "qwen_worker_invocation"
                / "latest.json",
                state / "model_gateway_route" / "latest.json",
            ]
        )
    )
    mature_refs = list_existing_refs(
        [
            state / "mature_capability_first" / "latest.json",
            state / "mature_capability_first" / "fitness_latest.json",
        ]
    )
    fan_in_refs.extend(
        list_existing_refs(
            [
                state
                / "modular_dynamic_worker_pool_phase1"
                / "draft_staging_queue"
                / "latest.json",
                state / "modular_dynamic_worker_pool_phase1" / "merge_consumer" / "latest.json",
                state / "source_frontier_durable_consumer" / "fan_in_acceptance_queue_latest.json",
            ]
        )
    )
    readback_refs.extend(
        list_existing_refs(
            [
                runtime_root
                / "readback"
                / "zh"
                / "temporal_activity_no_window_dp_worker_pool_phase3_20260704.md",
                runtime_root / "readback" / "zh" / "codex_s_main_execution_loop_tick_20260702.md",
            ]
        )
    )

    refs = extra_refs if isinstance(extra_refs, dict) else {}
    for key, target in (
        ("artifact_refs", artifact_refs),
        ("workflow_refs", workflow_refs),
        ("worker_ledger_refs", worker_refs),
        ("source_frontier_refs", source_refs),
        ("provider_invocation_refs", provider_refs),
        ("mature_capability_first_refs", mature_refs),
        ("fan_in_refs", fan_in_refs),
        ("readback_refs", readback_refs),
    ):
        values = refs.get(key)
        if isinstance(values, list):
            target.extend(str(item) for item in values if str(item).strip())

    def unique(values: list[Any]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result

    return {
        "schema_version": "xinao.codex_s.pre_pass_candidate_snapshot.v1",
        "task_id": task_id,
        "wave_id": wave_id,
        "candidate_kind": str(loaded.get("candidate_kind") or "before_final_or_pass"),
        "user_prompt": str(loaded.get("user_prompt") or loaded.get("last_user_message") or ""),
        "assistant_text": str(
            loaded.get("assistant_text")
            or loaded.get("last_assistant_message")
            or loaded.get("completion_text")
            or loaded.get("report_text")
            or ""
        ),
        "closure_evidence_bundle": loaded.get("closure_evidence_bundle")
        if isinstance(loaded.get("closure_evidence_bundle"), dict)
        else {},
        "artifact_refs": unique(artifact_refs),
        "git_head_sha": str(loaded.get("git_head_sha") or git_head(repo_root)),
        "workflow_refs": unique(workflow_refs),
        "worker_ledger_refs": unique(worker_refs),
        "source_frontier_refs": unique(source_refs),
        "provider_invocation_refs": unique(provider_refs),
        "mature_capability_first_refs": unique(mature_refs),
        "fan_in_refs": unique(fan_in_refs),
        "readback_refs": unique(readback_refs),
        "created_at": now_iso(),
        "completion_claim_allowed": bool(loaded.get("completion_claim_allowed", False)),
        "not_user_completion": True,
    }


def lane_result(
    lane_id: str,
    *,
    status: str,
    severity: str,
    evidence_refs: list[str] | None = None,
    actionable_change: str = "",
    affected_artifacts: list[str] | None = None,
    recheck_command: str = "",
    blocker_name: str | None = None,
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "status": status,
        "severity": severity,
        "evidence_refs": list(evidence_refs or []),
        "actionable_change": actionable_change,
        "affected_artifacts": list(affected_artifacts or []),
        "recheck_command": recheck_command,
        "blocker_name": blocker_name,
    }


def count_items(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def audit_lanes(
    *,
    runtime_root: Path,
    repo_root: Path,
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    state = runtime_root / "state"
    main_tick = read_json(state / "codex_s_main_execution_loop_tick" / "latest.json")
    loop_state = read_json(state / "loop_runtime_state" / "latest.json")
    provider = read_json(state / "codex_native_provider_scheduler_phase4_20260704" / "latest.json")
    worker_pool = read_json(state / "modular_dynamic_worker_pool_phase1" / "latest.json")
    source_frontier = read_json(state / "source_frontier_durable_consumer" / "latest.json")
    source_family = read_json(state / "source_family_wave_scheduler" / "latest.json")
    staging = read_json(
        state / "modular_dynamic_worker_pool_phase1" / "draft_staging_queue" / "latest.json"
    )
    merge = read_json(
        state / "modular_dynamic_worker_pool_phase1" / "merge_consumer" / "latest.json"
    )

    lanes: list[dict[str, Any]] = []
    main_tick_ok = (
        main_tick.get("validation", {}).get("passed") is True
        and main_tick.get("not_execution_controller") is True
    )
    lanes.append(
        lane_result(
            "hotpath_lane",
            status="PASS" if main_tick_ok else "FIXABLE",
            severity="high" if not main_tick_ok else "low",
            evidence_refs=list(snapshot.get("workflow_refs") or []),
            actionable_change=""
            if main_tick_ok
            else "Invoke codex_s_main_execution_loop_tick and attach pre_pass refs to runtime/fan-in/evidence refs.",
            affected_artifacts=["services/agent_runtime/codex_s_main_execution_loop_tick.py"],
            recheck_command="python -m xinao_seedlab.cli.__main__ main-execution-loop-tick",
            blocker_name=None if main_tick_ok else "PRE_PASS_HOTPATH_NOT_BOUND",
        )
    )

    stop = loop_state.get("stop") if isinstance(loop_state.get("stop"), dict) else {}
    stop_allowed = stop.get("stop_allowed")
    runtime_ok = bool(loop_state) and stop.get("derived") is True
    runtime_fixable = runtime_ok and stop_allowed is False
    lanes.append(
        lane_result(
            "runtime_lane",
            status="FIXABLE" if (runtime_fixable or not runtime_ok) else "PASS",
            severity="high" if (runtime_fixable or not runtime_ok) else "low",
            evidence_refs=list(snapshot.get("workflow_refs") or []),
            actionable_change=(
                "LoopRuntimeState says stop_allowed=false; dispatch/fan-in/merge next frontier before final wording."
                if runtime_fixable
                else (
                    ""
                    if runtime_ok
                    else "Write LoopRuntimeState before any Pre-PASS final decision."
                )
            ),
            affected_artifacts=[str(state / "loop_runtime_state" / "latest.json")],
            recheck_command="powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_temporal_activity_no_window_dp_worker_pool_phase3.ps1",
            blocker_name=None if runtime_ok else "PRE_PASS_LOOP_RUNTIME_STATE_MISSING",
        )
    )

    qwen_scope_ok = worker_pool.get("qwen_first_applies_only_to") == "cheap_worker_lane"
    external_cheap = int(worker_pool.get("external_cheap_draft_count") or 0)
    qwen_draft = int(worker_pool.get("qwen_prepaid_draft_count") or 0)
    provider_ok = provider.get("validation", {}).get("passed") is True or (
        qwen_scope_ok and external_cheap > 0 and qwen_draft > 0
    )
    lanes.append(
        lane_result(
            "provider_lane",
            status="PASS" if provider_ok else "FIXABLE",
            severity="medium" if not provider_ok else "low",
            evidence_refs=list(snapshot.get("provider_invocation_refs") or []),
            actionable_change=""
            if provider_ok
            else "Refresh ProviderScheduler/Qwen cheap-lane evidence; Qwen-first must stay scoped to cheap_worker_lane.",
            affected_artifacts=["services/agent_runtime/codex_native_provider_scheduler_phase4.py"],
            recheck_command="python -m xinao_seedlab.cli.__main__ codex-native-provider-scheduler-phase4",
            blocker_name=None if provider_ok else "PRE_PASS_PROVIDER_ROUTE_NOT_EVIDENCED",
        )
    )

    mature_path = state / "mature_capability_first" / "latest.json"
    mature = read_json(mature_path) if mature_path.is_file() else {}
    mature_validation = (
        mature.get("validation") if isinstance(mature.get("validation"), dict) else {}
    )
    mature_ok = (
        mature.get("schema_version") == "xinao.codex_s.mature_capability_first.v1"
        and mature_validation.get("passed") is True
        and mature.get("not_execution_controller") is True
    )
    lanes.append(
        lane_result(
            "mature_capability_lane",
            status="PASS" if mature_ok else "FIXABLE",
            severity="high" if not mature_ok else "low",
            evidence_refs=list(snapshot.get("mature_capability_first_refs") or []),
            actionable_change=(
                ""
                if mature_ok
                else "Run MatureCapabilityFirst before final/PASS-shaped wording; generic mechanisms need mature candidates or ADR exception."
            ),
            affected_artifacts=["services/agent_runtime/mature_capability_first.py"],
            recheck_command="python -m services.agent_runtime.mature_capability_first --task-id <task_id> --wave-id <wave_id>",
            blocker_name=None if mature_ok else "PRE_PASS_MATURE_CAPABILITY_FIRST_MISSING",
        )
    )

    source_gaps = (
        loop_state.get("source_gaps") if isinstance(loop_state.get("source_gaps"), list) else []
    )
    source_gap_open = bool(source_gaps) or source_frontier.get("source_gap_open") is True
    source_known = bool(source_frontier or source_family or snapshot.get("source_frontier_refs"))
    lanes.append(
        lane_result(
            "source_gap_lane",
            status="FIXABLE" if source_gap_open else ("PASS" if source_known else "FIXABLE"),
            severity="medium" if (source_gap_open or not source_known) else "low",
            evidence_refs=list(snapshot.get("source_frontier_refs") or []),
            actionable_change=""
            if source_known and not source_gap_open
            else "Dispatch source/source-family lane or record evidence-backed source gap blocker.",
            affected_artifacts=[str(state / "source_frontier_durable_consumer" / "latest.json")],
            recheck_command="python -m xinao_seedlab.cli.__main__ source-family-wave-scheduler",
            blocker_name=None
            if source_known and not source_gap_open
            else "PRE_PASS_SOURCE_GAP_OPEN",
        )
    )

    staged_count = int(staging.get("staged_count") or worker_pool.get("staged_count") or 0)
    merged_count = int(merge.get("merged_count") or worker_pool.get("merged_count") or 0)
    fanin_ok = staged_count > 0 and merged_count > 0
    lanes.append(
        lane_result(
            "fanin_lane",
            status="PASS" if fanin_ok else "FIXABLE",
            severity="high" if not fanin_ok else "low",
            evidence_refs=list(snapshot.get("fan_in_refs") or []),
            actionable_change=""
            if fanin_ok
            else "Stage worker drafts and run MergeConsumer before Pre-PASS can pass.",
            affected_artifacts=[
                str(state / "modular_dynamic_worker_pool_phase1" / "merge_consumer" / "latest.json")
            ],
            recheck_command="python -m xinao_seedlab.cli.__main__ modular-dynamic-worker-pool-phase1",
            blocker_name=None if fanin_ok else "PRE_PASS_FANIN_MERGE_MISSING",
        )
    )

    completion_overclaim = snapshot.get("completion_claim_allowed") is True
    lanes.append(
        lane_result(
            "completion_boundary_lane",
            status="HARD_RISK" if completion_overclaim else "PASS",
            severity="critical" if completion_overclaim else "low",
            evidence_refs=list(snapshot.get("artifact_refs") or []),
            actionable_change=""
            if not completion_overclaim
            else "Remove completion permission; Pre-PASS is not completion gate and cannot overrule S completion boundary.",
            affected_artifacts=[],
            recheck_command="python -m xinao_seedlab.cli.__main__ pre-pass-audit-loop --task-id <task_id> --wave-id <wave_id>",
            blocker_name="PRE_PASS_COMPLETION_BOUNDARY_OVERCLAIM" if completion_overclaim else None,
        )
    )

    closure_bundle = (
        snapshot.get("closure_evidence_bundle")
        if isinstance(snapshot.get("closure_evidence_bundle"), dict)
        else {}
    )
    computed_closure = completion_claim_payload_builder.closure_evidence_bundle_status(
        str(snapshot.get("assistant_text") or ""),
        user_text=str(snapshot.get("user_prompt") or ""),
    )
    closure_status = (
        closure_bundle if closure_bundle.get("closure_intent") is True else computed_closure
    )
    closure_ok = not closure_status.get("closure_intent") or closure_status.get("complete") is True
    missing_closure = list(closure_status.get("missing_fields") or [])
    lanes.append(
        lane_result(
            "closure_bundle_lane",
            status="PASS" if closure_ok else "FIXABLE",
            severity="high" if not closure_ok else "low",
            evidence_refs=list(snapshot.get("artifact_refs") or [])
            + list(snapshot.get("readback_refs") or []),
            actionable_change=(
                ""
                if closure_ok
                else "Replace closure-shaped final text with a full closure evidence bundle: default mainline binding, runtime worker load, verification, evidence/readback, git clean status, commit hash, push target, 333/mainline state, and remaining/named-blocker state."
            ),
            affected_artifacts=[
                "services/agent_runtime/completion_claim_payload_builder.py",
                "scripts/hardmode/Invoke-CodexSStopHook.ps1",
            ],
            recheck_command="python -m pytest -q tests/test_completion_claim_payload_builder.py tests/seedcortex/test_pre_pass_audit_loop.py",
            blocker_name=None if closure_ok else "PRE_PASS_CLOSURE_EVIDENCE_BUNDLE_MISSING",
        )
    )

    readbacks = [Path(ref) for ref in snapshot.get("readback_refs", [])]
    readback_ok = any(path.is_file() for path in readbacks)
    lanes.append(
        lane_result(
            "readback_lane",
            status="PASS" if readback_ok else "FIXABLE",
            severity="medium" if not readback_ok else "low",
            evidence_refs=[str(path) for path in readbacks if path.is_file()],
            actionable_change=""
            if readback_ok
            else "Write Chinese readback explaining backend work, backlog, merge, source gap, stop_allowed and next machine action.",
            affected_artifacts=[str(runtime_root / "readback" / "zh")],
            recheck_command="powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_pre_pass_audit_loop.ps1",
            blocker_name=None if readback_ok else "PRE_PASS_READBACK_MISSING",
        )
    )

    dirty = git_dirty(repo_root)
    lanes.append(
        lane_result(
            "history_lane",
            status="FIXABLE" if dirty else "PASS",
            severity="medium" if dirty else "low",
            evidence_refs=[],
            actionable_change=""
            if not dirty
            else "Working tree has uncommitted implementation; finish verification and commit before claiming durable route is landed.",
            affected_artifacts=[str(repo_root)],
            recheck_command="git status --short --branch",
            blocker_name=None if not dirty else "PRE_PASS_WORKTREE_DIRTY",
        )
    )
    return lanes


def build_fan_in_decision(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    hard = [lane for lane in lanes if lane.get("status") == "HARD_RISK"]
    user = [lane for lane in lanes if lane.get("status") == "USER_DECISION"]
    blockers = [lane for lane in lanes if lane.get("status") == "NAMED_BLOCKER"]
    fixable = [lane for lane in lanes if lane.get("status") == "FIXABLE"]
    if hard:
        decision = "hard_risk_stop_for_user"
    elif user:
        decision = "user_decision_required"
    elif blockers:
        decision = "named_blocker_recorded"
    elif fixable:
        decision = "repair_required"
    else:
        decision = "all_pass_final_allowed"
    return {
        "decision": decision,
        "final_allowed": decision == "all_pass_final_allowed",
        "fixable_count": len(fixable),
        "named_blocker_count": len(blockers),
        "hard_risk_count": len(hard),
        "user_decision_count": len(user),
        "lane_status_counts": {
            status: sum(1 for lane in lanes if lane.get("status") == status)
            for status in ["PASS", "FIXABLE", "USER_DECISION", "NAMED_BLOCKER", "HARD_RISK"]
        },
    }


def build_repair_plan(
    *,
    task_id: str,
    wave_id: str,
    round_index: int,
    lanes: list[dict[str, Any]],
) -> dict[str, Any]:
    fixable = [lane for lane in lanes if lane.get("status") == "FIXABLE"]
    target_files = sorted(
        {
            artifact
            for lane in fixable
            for artifact in lane.get("affected_artifacts", [])
            if isinstance(artifact, str) and artifact
        }
    )
    return {
        "schema_version": "xinao.codex_s.pre_pass_repair_plan.v1",
        "repair_id": f"pre-pass-repair-{safe_stem(wave_id)}-round-{round_index}",
        "task_id": task_id,
        "wave_id": wave_id,
        "source_audit_round": round_index,
        "fixable_findings": fixable,
        "target_files": target_files,
        "target_runtime_paths": target_files,
        "execution_lanes": [
            {
                "lane_id": f"repair_{lane['lane_id']}",
                "mode": "repair",
                "objective": lane.get("actionable_change", ""),
                "recheck_command": lane.get("recheck_command", ""),
            }
            for lane in fixable
        ],
        "expected_evidence": [
            "updated CandidateSnapshot",
            "audit_fan_in_latest",
            "repair lane result or named_blocker",
            "Chinese readback",
        ],
        "re_audit_scope": [lane.get("lane_id") for lane in fixable],
        "dispatch_to": "root_intent_loop_driver",
        "temporal_consumable": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def render_readback(payload: dict[str, Any]) -> str:
    decision = payload.get("audit_fan_in", {}).get("decision", "")
    lines = [
        "# Pre-PASS Audit Loop 回读",
        "",
        SENTINEL,
        "",
        f"- task_id: `{payload.get('task_id')}`",
        f"- wave_id: `{payload.get('wave_id')}`",
        f"- status: `{payload.get('status')}`",
        f"- fan_in_decision: `{decision}`",
        f"- final_allowed: {payload.get('audit_fan_in', {}).get('final_allowed')}",
        f"- fixable_count: {payload.get('audit_fan_in', {}).get('fixable_count')}",
        f"- named_blocker: `{payload.get('named_blocker')}`",
        f"- repair_plan_ref: `{payload.get('repair_plan_ref')}`",
        "- 这不是 completion gate，不是旧段审，不是执行 owner；FIXABLE 只生成 RepairPlan，交 RootIntentLoop/Temporal 继续消费。",
        "- 审计 lane: hotpath/runtime/provider/mature_capability/source_gap/fanin/completion_boundary/closure_bundle/readback/history。",
        "- next_machine_action: repair_required 时 dispatch_repair_plan；all_pass 时只允许当前 S completion boundary 继续判断。",
        "",
        "## Evidence",
    ]
    for key, value in payload.get("output_paths", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", SENTINEL, ""])
    return "\n".join(lines)


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_id: str = TASK_ID,
    wave_id: str = "pre-pass-audit-loop-wave-001",
    candidate_json: str | Path | None = None,
    candidate_snapshot: dict[str, Any] | None = None,
    extra_refs: dict[str, Any] | None = None,
    invoked_by_main_execution_loop_tick: bool = False,
    invoked_by_temporal_activity: bool = False,
    max_audit_rounds: int = 3,
    max_repair_attempts_per_finding: int = 2,
    write: bool = True,
) -> dict[str, Any]:
    try:
        from services.agent_runtime.thin_glue_l6_self_heal import (
            run_thin_glue_self_heal_as_pre_pass_delegate,
            thin_glue_self_heal_enabled,
        )

        if thin_glue_self_heal_enabled():
            return run_thin_glue_self_heal_as_pre_pass_delegate(
                runtime_root=runtime_root,
                repo_root=repo_root,
                task_id=task_id,
                wave_id=wave_id,
                invoked_by_temporal_activity=invoked_by_temporal_activity,
                write=write,
            )
    except Exception:
        pass
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime, task_id=task_id, wave_id=wave_id)
    snapshot = (
        dict(candidate_snapshot)
        if isinstance(candidate_snapshot, dict) and candidate_snapshot
        else build_candidate_snapshot(
            runtime_root=runtime,
            repo_root=repo,
            task_id=task_id,
            wave_id=wave_id,
            candidate_json=candidate_json,
            extra_refs=extra_refs,
        )
    )
    lanes = audit_lanes(runtime_root=runtime, repo_root=repo, snapshot=snapshot)
    fan_in = build_fan_in_decision(lanes)
    repair_plan = build_repair_plan(
        task_id=task_id,
        wave_id=wave_id,
        round_index=1,
        lanes=lanes,
    )
    repair_plan_ref = paths["repair_plan_latest"] if repair_plan.get("fixable_findings") else ""
    previous = read_json(Path(paths["latest"]))
    previous_fan_in = (
        previous.get("audit_fan_in") if isinstance(previous.get("audit_fan_in"), dict) else {}
    )
    repeated_fixable_without_artifact_delta = (
        previous_fan_in.get("decision") == "repair_required"
        and fan_in.get("decision") == "repair_required"
        and int(previous_fan_in.get("fixable_count") or 0) == int(fan_in.get("fixable_count") or 0)
        and not snapshot.get("artifact_delta_refs")
    )
    anti_audit_marathon = {
        "enabled": True,
        "triggered": repeated_fixable_without_artifact_delta,
        "previous_latest_ref": paths["latest"],
        "named_blocker": "REPEATED_FIXABLE_WITHOUT_ARTIFACT_DELTA"
        if repeated_fixable_without_artifact_delta
        else "",
        "strategy_mutation_ref": "",
    }
    progress_bundle: dict[str, Any] = {}
    if repeated_fixable_without_artifact_delta:
        from services.agent_runtime import progress_self_evolution

        progress_bundle = progress_self_evolution.record_progress_bundle(
            runtime_root=runtime,
            wave_id=wave_id,
            source_digest=hashlib.sha256(
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            source_theme_id="pre_pass_audit_loop.repeated_fixable",
            input_count=len(lanes),
            mapped_count=len(lanes),
            artifact_delta_count=0,
            named_blocker_delta=1,
            readback_delta=1,
            synthetic_item_used=False,
            source_frontier_empty=False,
            feedback_source_refs=[
                paths["audit_fan_in_latest"],
                paths["repair_plan_latest"],
                paths["candidate_snapshot_latest"],
            ],
            no_progress_reason="repeated_fixable_without_artifact_delta",
            write=write,
        )
        anti_audit_marathon["strategy_mutation_ref"] = progress_bundle.get("output_paths", {}).get(
            "strategy_latest", ""
        )
    named_blockers = sorted(
        {
            str(lane.get("blocker_name"))
            for lane in lanes
            if lane.get("blocker_name") and lane.get("status") in {"NAMED_BLOCKER", "HARD_RISK"}
        }
    )
    if repeated_fixable_without_artifact_delta:
        named_blockers.append("REPEATED_FIXABLE_WITHOUT_ARTIFACT_DELTA")
    checks = {
        "candidate_snapshot_present": bool(snapshot.get("candidate_kind")),
        "audit_lanes_complete": [lane.get("lane_id") for lane in lanes] == AUDIT_LANE_IDS,
        "structured_lane_outputs": all(
            lane.get("status") in {"PASS", "FIXABLE", "USER_DECISION", "NAMED_BLOCKER", "HARD_RISK"}
            and isinstance(lane.get("evidence_refs"), list)
            and "actionable_change" in lane
            for lane in lanes
        ),
        "fixable_generates_repair_plan": fan_in["fixable_count"] == 0
        or bool(repair_plan.get("execution_lanes")),
        "repair_plan_dispatches_to_root_intent_loop": repair_plan.get("dispatch_to")
        == "root_intent_loop_driver",
        "not_completion_gate": True,
        "not_execution_controller": True,
        "old_clean_not_used": True,
        "completion_claim_blocked": True,
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": task_id,
        "wave_id": wave_id,
        "status": "pre_pass_audit_loop_ready"
        if all(checks.values())
        else "pre_pass_audit_loop_blocked",
        "generated_at": now_iso(),
        "desktop_spec_ref": str(DEFAULT_DESKTOP_SPEC),
        "candidate_snapshot": snapshot,
        "audit_lane_registry": {
            "schema_version": "xinao.codex_s.pre_pass_audit_lane_registry.v1",
            "lane_count": len(lanes),
            "lanes": lanes,
        },
        "audit_fan_in": fan_in,
        "repair_plan": repair_plan,
        "repair_plan_ref": repair_plan_ref,
        "anti_audit_marathon_gate": anti_audit_marathon,
        "progress_self_evolution": progress_bundle,
        "reaudit": {
            "schema_version": "xinao.codex_s.pre_pass_reaudit.v1",
            "max_audit_rounds": max_audit_rounds,
            "max_repair_attempts_per_finding": max_repair_attempts_per_finding,
            "stale_snapshot_reject": True,
            "no_new_actionable_issue_stop": True,
            "terminal_blocker_required": True,
            "next_round_required": fan_in.get("decision") == "repair_required"
            and not repeated_fixable_without_artifact_delta,
        },
        "pre_pass_payload": {
            "all_pass": fan_in.get("decision") == "all_pass_final_allowed",
            "repair_required": fan_in.get("decision") == "repair_required"
            and not repeated_fixable_without_artifact_delta,
            "named_blocker": ",".join(named_blockers),
            "continue_main_loop": fan_in.get("decision") == "repair_required"
            and not repeated_fixable_without_artifact_delta,
            "decision": "named_blocker"
            if repeated_fixable_without_artifact_delta
            else "dispatch_repair_plan"
            if fan_in.get("decision") == "repair_required"
            else fan_in.get("decision"),
        },
        "named_blocker": ",".join(named_blockers),
        "invoked_by_main_execution_loop_tick": invoked_by_main_execution_loop_tick,
        "invoked_by_temporal_activity": invoked_by_temporal_activity,
        "runtime_enforced": invoked_by_temporal_activity,
        "runtime_enforced_scope": "seed_cortex_temporal_pre_pass_audit_loop_activity"
        if invoked_by_temporal_activity
        else "",
        "completion_claim_allowed": False,
        "final_allowed": fan_in.get("final_allowed") is True,
        "not_old_segment_audit": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "output_paths": paths,
        "validation": {"passed": all(checks.values()), "checks": checks},
    }
    if write:
        write_json(Path(paths["latest"]), payload)
        write_json(Path(paths["task_wave"]), payload)
        write_json(Path(paths["candidate_snapshot_latest"]), snapshot)
        write_json(Path(paths["audit_lane_registry_latest"]), payload["audit_lane_registry"])
        write_json(Path(paths["audit_fan_in_latest"]), fan_in)
        write_json(Path(paths["reaudit_latest"]), payload["reaudit"])
        if repair_plan_ref:
            write_json(Path(repair_plan_ref), repair_plan)
        write_text(Path(paths["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-id", default=TASK_ID)
    parser.add_argument("--wave-id", default="pre-pass-audit-loop-wave-001")
    parser.add_argument("--candidate-json", default="")
    parser.add_argument("--invoked-by-main-execution-loop-tick", action="store_true")
    parser.add_argument("--invoked-by-temporal-activity", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_id=args.task_id,
        wave_id=args.wave_id,
        candidate_json=args.candidate_json or None,
        invoked_by_main_execution_loop_tick=args.invoked_by_main_execution_loop_tick,
        invoked_by_temporal_activity=args.invoked_by_temporal_activity,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "fan_in_decision": payload["audit_fan_in"]["decision"],
                "repair_plan_ref": payload["repair_plan_ref"],
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
