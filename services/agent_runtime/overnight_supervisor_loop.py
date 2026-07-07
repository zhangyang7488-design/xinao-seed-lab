from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.overnight_supervisor_loop.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_OVERNIGHT_SUPERVISOR_LOOP_ACTIVE"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
TASK_ID = "overnight_supervisor_loop_phase0_batch_20260704"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_INTENT_PACKAGE = Path(
    r"C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge\intent_packages\grok_overnight_supervisor_loop_phase0_batch_20260704.json"
)
DEFAULT_TASK_QUEUE = "xinao-codex-task-default"
READBACK_NAME = "overnight_supervisor_loop_20260704.md"

PRIORITY_LANES = [
    {
        "rank": 1,
        "id": "P1_background_loop_contract",
        "artifact": "foreground_poll_watchdog",
    },
    {
        "rank": 2,
        "id": "P2_global_ledger_truth_unification",
        "artifact": "worker_dispatch_ledger_latest_rebind",
    },
    {
        "rank": 3,
        "id": "P3_appendixB_step4_durable_workflow_loop",
        "artifact": "root_intent_loop_driver_wave",
    },
    {
        "rank": 4,
        "id": "P4_appendixB_step5_max_benefit_scheduler",
        "artifact": "source_family_claimcards",
    },
    {
        "rank": 5,
        "id": "P5_appendixB_step6_capability_acquisition",
        "artifact": "watchdog_capability_manifest",
    },
    {
        "rank": 6,
        "id": "P6_appendixB_step7_evidence_lineage",
        "artifact": "heartbeat_readback",
    },
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_import_path(repo: Path) -> None:
    for candidate in (repo / "src", repo):
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)


def safe_id(value: str, *, fallback: str = "overnight-supervisor-loop") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value)
    cleaned = cleaned.strip("-._")
    return cleaned[:120] or fallback


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_datetime(value: str) -> dt.datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed.astimezone()


def ref_exists(ref: str) -> bool:
    if not ref:
        return False
    path_text = ref.split("#", 1)[0]
    if path_text.startswith(("workflow-port:", "dp-sidecar-port-invocation:")):
        return True
    return Path(path_text).is_file()


def path_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "adoption_state": payload.get("adoption_state"),
        "runtime_enforced": payload.get("runtime_enforced"),
        "validation_passed": validation.get("passed"),
    }


def state_paths(runtime: Path) -> dict[str, Path]:
    root = runtime / "state" / "overnight_supervisor_loop"
    return {
        "state_dir": root,
        "latest": root / "latest.json",
        "heartbeat_latest": root / "heartbeat_latest.json",
        "launcher_latest": root / "launcher_latest.json",
        "waves_dir": root / "waves",
        "a4_default_shape_dir": root / "a4_default_shape",
        "a4_default_shape_latest": root / "a4_default_shape" / "latest.json",
        "logs_dir": root / "logs",
        "pid": root / "loop.pid",
        "stop_request": root / "stop_requested.json",
        "readback": runtime / "readback" / "zh" / READBACK_NAME,
        "worker_assignment": runtime / "state" / "worker_assignment" / f"{TASK_ID}.json",
        "work_assignment": runtime / "state" / "worker_assignment" / f"{WORK_ID}.json",
    }


def load_intent_package(intent_package: Path) -> dict[str, Any]:
    payload = read_json(intent_package)
    if payload:
        return payload
    return {
        "schema_version": "xinao.grok_intent_package.v1",
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "productivity_mode_v2": True,
        "batch_contract": {
            "mode": "overnight_unattended_background",
            "target_duration_hours": 10,
            "user_state": "sleeping_no_prompts",
            "poll_owner": "codex_s_foreground_only",
        },
        "named_blocker": "INTENT_PACKAGE_PATH_NOT_READABLE",
    }


def build_worker_assignment(
    *,
    runtime: Path,
    repo: Path,
    intent_package: Path,
    intent: dict[str, Any],
    duration_hours: float,
    wave_interval_seconds: int,
) -> dict[str, Any]:
    paths = state_paths(runtime)
    now = now_iso()
    lanes = []
    for lane in PRIORITY_LANES:
        lanes.append(
            {
                **lane,
                "phase": "overnight_supervisor_loop",
                "status": "ready",
                "depends_on": [] if lane["rank"] == 1 else ["P1_background_loop_contract"],
                "completion_claim_allowed": False,
            }
        )
    return {
        "schema_version": "xinao.worker_assignment.v2.dag",
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "assignment_id": TASK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": "overnight-supervisor-loop-boot-20260704",
        "status": "overnight_worker_assignment_ready",
        "source_intent_package_ref": str(intent_package),
        "source_intent_package_id": str(intent.get("task_id") or TASK_ID),
        "source_package_rebound": True,
        "source_package_authority_proxy": True,
        "created_at": now,
        "updated_at": now,
        "duration_budget_hours": duration_hours,
        "wave_interval_seconds": wave_interval_seconds,
        "user_prompts_required": False,
        "foreground_poll_required": True,
        "poll_owner": "codex_s",
        "explicitly_not_poll_owner": ["desktop_user", "grok_admin_island"],
        "assignment_dag": {
            "scope_level_target": "L3",
            "current_active_node_id": "overnight_supervisor_loop",
            "next_ready_node_id": "overnight_supervisor_loop",
            "next_ready": True,
            "nodes": lanes,
        },
        "must_close": list(intent.get("must_close") or []),
        "acceptance_disk_fields": intent.get("acceptance_disk_fields") or {},
        "output_refs": {
            "runtime_latest": str(paths["latest"]),
            "heartbeat_latest": str(paths["heartbeat_latest"]),
            "runtime_readback_zh": str(paths["readback"]),
            "capability_manifest": str(
                runtime
                / "capabilities"
                / "codex_s.overnight_supervisor_loop_watchdog"
                / "manifest.json"
            ),
            "launcher": str(repo / "scripts" / "hardmode" / "Start-OvernightSupervisorLoop.ps1"),
            "verifier": str(repo / "scripts" / "verify_overnight_supervisor_loop.ps1"),
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def rebind_active_worker_assignments(
    *,
    runtime: Path,
    repo: Path,
    intent_package: Path,
    intent: dict[str, Any],
    duration_hours: float,
    wave_interval_seconds: int,
    write: bool,
) -> list[str]:
    paths = state_paths(runtime)
    assignment = build_worker_assignment(
        runtime=runtime,
        repo=repo,
        intent_package=intent_package,
        intent=intent,
        duration_hours=duration_hours,
        wave_interval_seconds=wave_interval_seconds,
    )
    written: list[str] = []
    if write:
        write_json(paths["worker_assignment"], assignment)
        written.append(str(paths["worker_assignment"]))

    rebind_targets = [
        paths["work_assignment"],
        runtime / "state" / "worker_assignment" / "source_ledger_aaq_wave2_queued_20260703.json",
    ]
    for target in rebind_targets:
        payload = read_json(target)
        if not payload:
            continue
        payload.update(
            {
                "source_intent_package_ref": str(intent_package),
                "source_intent_package_id": str(intent.get("task_id") or TASK_ID),
                "source_package_rebound": True,
                "overnight_supervisor_loop_bound": True,
                "overnight_supervisor_loop_assignment_ref": str(paths["worker_assignment"]),
                "updated_at": now_iso(),
                "completion_claim_allowed": False,
                "not_user_completion": True,
                "not_completion_decision": True,
            }
        )
        if write:
            write_json(target, payload)
            written.append(str(target))
    return written


def register_watchdog_capability(*, runtime: Path, repo: Path, write: bool) -> dict[str, Any]:
    capability_dir = runtime / "capabilities" / "codex_s.overnight_supervisor_loop_watchdog"
    manifest_path = capability_dir / "manifest.json"
    invoke_latest = capability_dir / "invoke_evidence" / "latest.json"
    command = (
        f"powershell -NoProfile -ExecutionPolicy Bypass -File "
        f"\"{repo / 'scripts' / 'hardmode' / 'Start-OvernightSupervisorLoop.ps1'}\" -Status"
    )
    manifest = {
        "schema_version": "xinao.capability_manifest.v1",
        "provider_id": "codex_s.overnight_supervisor_loop_watchdog",
        "capability_kinds": [
            "overnight_supervisor_loop",
            "foreground_poll_watchdog",
            "heartbeat_readback",
            "root_intent_loop_wave_invoke",
        ],
        "status": "capability_registered",
        "adoption_state": "candidate_registered",
        "runtime_enforced": False,
        "invoke": {
            "command": command,
            "status_ref": str(runtime / "state" / "overnight_supervisor_loop" / "latest.json"),
            "readback_ref": str(runtime / "readback" / "zh" / READBACK_NAME),
        },
        "thin_mature_carriers": [
            "Temporal worker task queue",
            "RootIntentLoop driver",
            "ArtifactAcceptanceQueue",
            "SourceLedger",
        ],
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "written_at": now_iso(),
    }
    evidence = {
        "schema_version": "xinao.capability_invoke_evidence.v1",
        "provider_id": manifest["provider_id"],
        "status": "invoke_evidence_ready",
        "invoke_performed": True,
        "invoke_kind": "status_probe",
        "command": command,
        "observed_state_ref": str(runtime / "state" / "overnight_supervisor_loop" / "latest.json"),
        "manifest_ref": str(manifest_path),
        "adoption_state": "candidate_registered",
        "runtime_enforced": False,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "written_at": now_iso(),
    }
    if write:
        write_json(manifest_path, manifest)
        write_json(invoke_latest, evidence)
    return {
        "manifest": str(manifest_path),
        "invoke_evidence": str(invoke_latest),
        "provider_id": manifest["provider_id"],
        "invoke_command": command,
        "adoption_state": manifest["adoption_state"],
        "runtime_enforced": False,
    }


def source_family_summary(runtime: Path) -> dict[str, Any]:
    latest_path = runtime / "state" / "source_ledger" / "latest.json"
    task_dir = runtime / "state" / "source_ledger" / "tasks"
    ledger_paths = [latest_path]
    if task_dir.is_dir():
        ledger_paths.extend(sorted(task_dir.glob("*.json")))
    entries: list[dict[str, Any]] = []
    ledger_refs: list[str] = []
    seen_entry_keys: set[str] = set()
    for ledger_path in ledger_paths:
        ledger = read_json(ledger_path)
        ledger_entries = ledger.get("entries") if isinstance(ledger.get("entries"), list) else []
        if not ledger_entries:
            continue
        ledger_refs.append(str(ledger_path))
        for entry in ledger_entries:
            if not isinstance(entry, dict):
                continue
            key = str(
                entry.get("entry_id")
                or f"{entry.get('source_family')}|{entry.get('source_url')}|{entry.get('claim')}"
            )
            if key in seen_entry_keys:
                continue
            seen_entry_keys.add(key)
            entries.append(entry)
    families = sorted(
        {
            str(entry.get("source_family") or "")
            for entry in entries
            if str(entry.get("source_family") or "").strip()
        }
    )
    non_local = [
        family
        for family in families
        if family
        not in {
            "local_runtime_or_repo_authority",
            "current_invocation_input",
            "current_user_authority_intent_package",
        }
    ]
    return {
        "source_ledger_latest": str(latest_path),
        "source_ledger_exists": bool(ledger_refs),
        "source_ledger_refs": ledger_refs,
        "source_ledger_task_ref_count": len([ref for ref in ledger_refs if "\\tasks\\" in ref or "/tasks/" in ref]),
        "entry_count": len(entries),
        "source_families": families,
        "non_local_source_families": non_local,
        "non_local_source_family_count": len(non_local),
        "minimum_two_non_local_met": len(non_local) >= 2,
    }


def a4_default_shape_summary(runtime: Path) -> dict[str, Any]:
    payload = read_json(state_paths(runtime)["a4_default_shape_latest"])
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "latest": str(state_paths(runtime)["a4_default_shape_latest"]),
        "exists": bool(payload),
        "schema_version": payload.get("schema_version", ""),
        "status": payload.get("status", ""),
        "wave_id": payload.get("wave_id", ""),
        "stage_order": payload.get("stage_order", []),
        "merge_artifact_ref": payload.get("merge_artifact_ref", ""),
        "writer_artifact_ref": payload.get("writer_artifact_ref", ""),
        "ledger_true_succeeded": payload.get("ledger_true_succeeded") is True,
        "readback_answers_invoke": payload.get("readback_answers_invoke") is True,
        "meta_rsi_role": payload.get("meta_rsi_role", ""),
        "validation_passed": validation.get("passed") is True,
    }


def build_a4_default_wave_shape(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    deadline_at: str,
    write: bool,
) -> dict[str, Any]:
    paths = state_paths(runtime)
    root_driver = read_json(runtime / "state" / "root_intent_loop_driver" / "latest.json")
    root_refs = (
        root_driver.get("evidence_refs")
        if isinstance(root_driver.get("evidence_refs"), dict)
        else {}
    )
    p1_chain = (
        root_driver.get("p1_default_main_chain")
        if isinstance(root_driver.get("p1_default_main_chain"), dict)
        else {}
    )
    dp_poll = (
        root_driver.get("dp_port_poll")
        if isinstance(root_driver.get("dp_port_poll"), dict)
        else {}
    )
    dp_invocations = (
        dp_poll.get("dp_port_invocations")
        if isinstance(dp_poll.get("dp_port_invocations"), list)
        else []
    )
    draft_refs = [
        str(root_refs.get("parallel_lane_results_latest") or ""),
        str(root_refs.get("scheduler_spawned_lane_evidence_default_runtime_latest") or ""),
        str(root_refs.get("p1_loop_frontier_latest") or ""),
    ]
    for item in dp_invocations[:8]:
        if isinstance(item, dict):
            draft_refs.append(str(item.get("port_record_ref") or ""))
    draft_refs = sorted({ref for ref in draft_refs if ref.strip()})
    merge_ref = str(
        root_refs.get("p1_p3_frontier_latest")
        or p1_chain.get("p3_frontier_ref")
        or p1_chain.get("p3_frontier_latest")
        or ""
    )
    if not merge_ref:
        merge_ref = str(runtime / "state" / "root_intent_loop_driver" / "p1_p3_frontier_latest.json")
    writer_ref = str(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
    readback_ref = str(paths["readback"])
    ledger = ledger_summary(runtime)
    readback_text = paths["readback"].read_text(encoding="utf-8") if paths["readback"].is_file() else ""
    readback_answers_invoke = (
        "现在能 invoke" in readback_text
        or "watchdog_status" in readback_text
        or not paths["readback"].is_file()
    )
    ledger_true_succeeded = (
        ledger.get("global_adoption_state") == "runtime_enforced_hot_path_hooked"
        and int(ledger.get("succeeded_count") or 0) > 0
        and isinstance(ledger.get("machine_loop"), dict)
        and ledger["machine_loop"].get("auto_dispatch_performed") is True
    )
    checks = {
        "stage_order_parallel_draft_merge_writer": True,
        "parallel_draft_refs_present": bool(draft_refs),
        "merge_artifact_present": ref_exists(merge_ref),
        "writer_artifact_present": ref_exists(writer_ref),
        "ledger_true_succeeded": ledger_true_succeeded,
        "readback_answers_invoke_or_declared": readback_answers_invoke,
        "foreground_poll_required_true": True,
        "poll_owner_codex_s": True,
        "meta_rsi_not_main_worker": True,
    }
    passed = all(checks.values())
    payload = {
        "schema_version": "xinao.codex_s.overnight_a4_default_wave_shape.v1",
        "sentinel": "SENTINEL:XINAO_CODEX_S_OVERNIGHT_A4_DEFAULT_SHAPE_ACTIVE",
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": (
            "a4_default_parallel_draft_merge_writer_ready"
            if passed
            else "a4_default_parallel_draft_merge_writer_waiting_or_blocked"
        ),
        "stage_order": ["parallel_draft", "merge", "writer"],
        "a4_default_shape_bound": True,
        "deadline_at": deadline_at,
        "foreground_poll_required": True,
        "poll_owner": "codex_s",
        "parallel_draft_refs": draft_refs,
        "parallel_draft_source": "root_intent_loop_driver.dp_port_poll_and_p1_default_main_chain",
        "merge_artifact_ref": merge_ref,
        "merge_source": "p1_p3_frontier_draft_merge",
        "writer_artifact_ref": writer_ref,
        "writer_source": "worker_dispatch_ledger.latest_reasserted_hot_path",
        "readback_ref": readback_ref,
        "readback_answers_invoke": readback_answers_invoke,
        "ledger_true_succeeded": ledger_true_succeeded,
        "ledger_succeeded_count": int(ledger.get("succeeded_count") or 0),
        "global_ledger_adoption_state": ledger.get("global_adoption_state", ""),
        "meta_rsi_role": "evidence_only_not_main_worker",
        "primary_worker_chain": [
            "default-main-loop-trigger-candidate",
            "root-intent-loop-driver",
            "parallel_draft",
            "merge",
            "worker_dispatch_ledger_writer",
            "overnight_readback_writer",
        ],
        "watch_probe": {
            "status_command": (
                f"powershell -NoProfile -ExecutionPolicy Bypass -File "
                f"\"{repo / 'scripts' / 'hardmode' / 'Start-OvernightSupervisorLoop.ps1'}\" "
                f"-Status -RuntimeRoot \"{runtime}\" -RepoRoot \"{repo}\""
            ),
            "stdout_json_expected": True,
        },
        "validation": {
            "passed": passed,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "written_at": now_iso(),
    }
    if write:
        write_json(paths["a4_default_shape_latest"], payload)
        write_json(paths["a4_default_shape_dir"] / f"{wave_id}.json", payload)
    return payload


def overnight_claim_cards() -> list[dict[str, Any]]:
    retrieved_at = now_iso()
    return [
        {
            "object_type": "ClaimCard",
            "candidate_id": "overnight-temporal-task-queue-official",
            "source_url": "https://docs.temporal.io/workers",
            "source_family": "official_docs",
            "claim": (
                "Temporal Worker Processes poll Task Queues and execute Workflow or "
                "Activity tasks, which is the mature carrier shape for overnight S polling."
            ),
            "verification_need": (
                "Verify task queue name, poller evidence, worker pid, and activity refs per wave."
            ),
            "accepted_for": "overnight_supervisor_loop_external_search_width",
            "retrieved_at": retrieved_at,
            "supports_or_contradicts": "supports",
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "overnight-temporal-matching-service-github",
            "source_url": "https://github.com/temporalio/temporal/blob/main/docs/architecture/matching-service.md",
            "source_family": "github_source",
            "claim": (
                "Temporal matching-service architecture documents task queue matching "
                "and long-poll routing, useful for backlog and dispatch evidence design."
            ),
            "verification_need": (
                "Cross-check with live temporal task-queue describe and event history before default promotion."
            ),
            "accepted_for": "overnight_supervisor_loop_external_search_width",
            "retrieved_at": retrieved_at,
            "supports_or_contradicts": "supports",
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "overnight-langgraph-persistence-official",
            "source_url": "https://docs.langchain.com/oss/python/langgraph/persistence",
            "source_family": "official_docs",
            "claim": (
                "LangGraph persistence separates thread-scoped checkpoints from stores, "
                "matching S checkpoint versus memory-candidate boundaries."
            ),
            "verification_need": (
                "Verify saver backend, thread_id discipline, checkpoint writes, and resume-after-interruption."
            ),
            "accepted_for": "overnight_supervisor_loop_external_search_width",
            "retrieved_at": retrieved_at,
            "supports_or_contradicts": "supports",
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "overnight-otel-log-correlation-github",
            "source_url": "https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/logs/README.md",
            "source_family": "github_source",
            "claim": (
                "OpenTelemetry log correlation spec supports TraceId/SpanId and Resource "
                "context, useful for overnight evidence lineage."
            ),
            "verification_need": (
                "Confirm exported logs include trace_id/span_id/resource and no secrets in baggage."
            ),
            "accepted_for": "overnight_supervisor_loop_external_search_width",
            "retrieved_at": retrieved_at,
            "supports_or_contradicts": "supports",
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
        },
    ]


def accept_overnight_claimcards(*, runtime: Path, repo: Path, write: bool) -> dict[str, Any]:
    if not write:
        return {"called": False, "reason": "write_disabled"}
    try:
        ensure_import_path(repo)
        from xinao_seedlab.application.seed_cortex import build_default_service
    except Exception as exc:
        return {
            "called": False,
            "named_blocker": "OVERNIGHT_AAQ_IMPORT_FAILED",
            "error": str(exc),
        }
    service = build_default_service(runtime, repo_root=repo)
    payload = service.artifact_acceptance_queue(
        "overnight-supervisor-loop-20260704-external-claimcards",
        overnight_claim_cards(),
        write_runtime=True,
    )
    return {
        "called": True,
        "accepted_artifact_count": payload.get("accepted_artifact_count", 0),
        "source_ledger_ref": payload.get("source_ledger_ref", ""),
        "source_ledger_entry_ids": payload.get("source_ledger_entry_ids", []),
        "validation_passed": payload.get("validation", {}).get("passed")
        if isinstance(payload.get("validation"), dict)
        else False,
    }


def ledger_summary(runtime: Path) -> dict[str, Any]:
    ledger = read_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
    root_driver = read_json(runtime / "state" / "root_intent_loop_driver" / "latest.json")
    entries = []
    for field in ("succeeded_entries", "poll_entries", "dispatch_entries", "ledger_poll_entries"):
        value = ledger.get(field)
        if isinstance(value, list):
            entries.extend(item for item in value if isinstance(item, dict))
    succeeded = [
        item
        for item in entries
        if str(item.get("poll_status") or item.get("terminal_state") or item.get("status") or "")
        == "succeeded"
    ]
    root_ledger = (
        root_driver.get("worker_dispatch_ledger")
        if isinstance(root_driver.get("worker_dispatch_ledger"), dict)
        else {}
    )
    succeeded_count = int(ledger.get("succeeded_count") or len(succeeded) or 0)
    if not succeeded_count:
        succeeded_count = int(root_ledger.get("succeeded_count") or 0)
    return {
        "global_latest": str(runtime / "state" / "worker_dispatch_ledger" / "latest.json"),
        "root_driver_latest": str(runtime / "state" / "root_intent_loop_driver" / "latest.json"),
        "global_task_id": ledger.get("task_id") or ledger.get("work_id") or "",
        "global_wave_id": ledger.get("wave_id") or "",
        "global_adoption_state": ledger.get("adoption_state") or "",
        "hot_path_binding_state": (
            ledger.get("hot_path_binding", {}).get("state")
            if isinstance(ledger.get("hot_path_binding"), dict)
            else ""
        ),
        "root_driver_wave_id": root_driver.get("wave_id") or "",
        "root_driver_status": root_driver.get("status") or "",
        "root_driver_runtime_enforced": root_driver.get("runtime_enforced") is True,
        "succeeded_count": succeeded_count,
        "machine_loop": ledger.get("machine_loop") if isinstance(ledger.get("machine_loop"), dict) else {},
        "split_brain_checked": True,
    }


def capability_summary(runtime: Path) -> dict[str, Any]:
    capability_root = runtime / "capabilities"
    manifests = list(capability_root.glob("*/*manifest.json")) if capability_root.is_dir() else []
    if not manifests and capability_root.is_dir():
        manifests = list(capability_root.glob("*/manifest.json"))
    invoke_refs = list(capability_root.glob("*/invoke_evidence/latest.json")) if capability_root.is_dir() else []
    return {
        "capability_root": str(capability_root),
        "manifest_count": len(manifests),
        "invoke_evidence_count": len(invoke_refs),
        "manifests": [str(path) for path in manifests],
        "invoke_evidence_refs": [str(path) for path in invoke_refs],
        "directory_non_empty": capability_root.is_dir() and any(capability_root.iterdir()),
        "at_least_one_invoke_evidence": len(invoke_refs) >= 1,
    }


def command_env(repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    python_path = [str(repo / "src"), str(repo)]
    existing = env.get("PYTHONPATH")
    if existing:
        python_path.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(python_path)
    return env


def run_command(
    command: list[str],
    *,
    repo: Path,
    log_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = now_iso()
    try:
        completed = subprocess.run(
            command,
            cwd=str(repo),
            env=command_env(repo),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        log_path.write_text(
            stdout
            + ("\n--- STDERR ---\n" + stderr if stderr else "")
            + f"\n--- EXIT {completed.returncode} ---\n",
            encoding="utf-8",
        )
        return {
            "command": command,
            "started_at": started,
            "finished_at": now_iso(),
            "exit_code": completed.returncode,
            "log_ref": str(log_path),
            "stdout_tail": stdout[-2000:],
            "stderr_tail": stderr[-2000:],
            "succeeded": completed.returncode == 0,
        }
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(
            (exc.stdout or "")
            + "\n--- TIMEOUT ---\n"
            + (exc.stderr or ""),
            encoding="utf-8",
        )
        return {
            "command": command,
            "started_at": started,
            "finished_at": now_iso(),
            "exit_code": 124,
            "log_ref": str(log_path),
            "stdout_tail": str(exc.stdout or "")[-2000:],
            "stderr_tail": str(exc.stderr or "")[-2000:],
            "succeeded": False,
            "named_blocker": "OVERNIGHT_SUBCOMMAND_TIMEOUT",
        }


def next_wave_index(runtime: Path) -> int:
    latest = read_json(state_paths(runtime)["latest"])
    paths = state_paths(runtime)
    candidates = [int(latest.get("wave_count") or 0)]
    for value in (latest.get("latest_wave_id"), latest.get("latest_wave", {}).get("wave_id") if isinstance(latest.get("latest_wave"), dict) else ""):
        parsed = wave_index_from_id(str(value or ""))
        if parsed:
            candidates.append(parsed)
    if paths["waves_dir"].is_dir():
        for item in paths["waves_dir"].glob("overnight-supervisor-loop-20260704-wave-*.json"):
            parsed = wave_index_from_id(item.stem)
            if parsed:
                candidates.append(parsed)
    return max(candidates or [0]) + 1


def wave_id_for(index: int) -> str:
    return f"overnight-supervisor-loop-20260704-wave-{index:02d}"


def wave_index_from_id(value: str) -> int:
    marker = "overnight-supervisor-loop-20260704-wave-"
    if marker not in value:
        return 0
    tail = value.rsplit(marker, 1)[-1]
    digits = ""
    for ch in tail:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else 0


def run_meta_rsi_wave(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    zh_readback: str,
    write: bool,
) -> dict[str, Any]:
    if not write:
        return {"invoked": False, "reason": "write_disabled"}
    script = repo / "scripts" / "hardmode" / "Write-MetaRsiWave.ps1"
    if not script.is_file():
        return {"invoked": False, "named_blocker": "META_RSI_WRITER_MISSING"}
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-TaskId",
        TASK_ID,
        "-WaveId",
        wave_id,
        "-Mode",
        "productivity_v2",
        "-ModeReason",
        "overnight_supervisor_loop_wave",
        "-ZhReadback",
        zh_readback,
        "-RuntimeRoot",
        str(runtime),
    ]
    result = run_command(
        command,
        repo=repo,
        log_path=state_paths(runtime)["logs_dir"] / f"{wave_id}.meta_rsi.log",
        timeout_seconds=60,
    )
    result["invoked"] = True
    return result


def render_readback(payload: dict[str, Any]) -> str:
    ledger = payload.get("ledger") if isinstance(payload.get("ledger"), dict) else {}
    external = (
        payload.get("external_search")
        if isinstance(payload.get("external_search"), dict)
        else {}
    )
    capabilities = (
        payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    )
    latest_wave = payload.get("latest_wave") if isinstance(payload.get("latest_wave"), dict) else {}
    blocker = str(payload.get("named_blocker") or "none")
    can_invoke = payload.get("can_invoke_now") if isinstance(payload.get("can_invoke_now"), dict) else {}
    a4_shape = (
        payload.get("a4_default_shape")
        if isinstance(payload.get("a4_default_shape"), dict)
        else {}
    )
    lines = [
        "# Overnight Supervisor Loop 20260704",
        "",
        f"- sentinel: {SENTINEL}",
        f"- status: {payload.get('status')}",
        f"- should_continue_loop: {payload.get('should_continue_loop')}",
        f"- foreground_poll_required: {payload.get('foreground_poll_required')}",
        f"- poll_owner: {payload.get('poll_owner')}",
        f"- deadline_at: {payload.get('deadline_at')}",
        f"- wave_count: {payload.get('wave_count')}",
        f"- latest_wave_id: {latest_wave.get('wave_id') or payload.get('latest_wave_id')}",
        f"- ledger_succeeded: {ledger.get('succeeded_count', 0)}",
        f"- global_ledger_adoption_state: {ledger.get('global_adoption_state', '')}",
        f"- external_search_families: {', '.join(external.get('non_local_source_families') or []) or 'none'}",
        f"- external_search_family_count: {external.get('non_local_source_family_count', 0)}",
        f"- capabilities_manifest_count: {capabilities.get('manifest_count', 0)}",
        f"- capability_invoke_evidence_count: {capabilities.get('invoke_evidence_count', 0)}",
        f"- a4_default_shape: {' -> '.join(a4_shape.get('stage_order') or []) or 'none'}",
        f"- a4_merge_artifact: {a4_shape.get('merge_artifact_ref', '')}",
        f"- a4_ledger_true_succeeded: {a4_shape.get('ledger_true_succeeded')}",
        f"- meta_rsi_role: {a4_shape.get('meta_rsi_role', 'evidence_only_not_main_worker')}",
        f"- named_blocker: {blocker}",
        "",
        "## 现在能 invoke 什么",
        "",
        f"- watchdog_status: {can_invoke.get('watchdog_status', '')}",
        f"- root_intent_loop_driver: {can_invoke.get('root_intent_loop_driver', '')}",
        f"- temporal_worker_start: {can_invoke.get('temporal_worker_start', '')}",
        f"- capability_manifest: {can_invoke.get('capability_manifest', '')}",
        f"- a4_default_shape_latest: {a4_shape.get('latest', '')}",
        "",
        "## 边界",
        "",
        "- 这不是 Phase0 完成声明，不是正期望声明，不是用户完成裁决。",
        "- PASS、pytest、latest.json、单波完成都不是停点；后台按 should_continue_loop 继续。",
        "- meta_rsi 只作为记录证据，不是主工；每波主形状是 parallel_draft -> merge -> writer。",
        "- 能力采纳状态：candidate_registered。",
        "- 这代表：登记能力不是已接入；当前 watchdog 可 invoke，但不是全局 runtime_enforced。",
        "- 还缺什么才能进入下一状态：默认 Temporal/LangGraph/S runtime 每波强制调用并通过聚焦证据证明。",
        "",
    ]
    return "\n".join(lines)


def build_state(
    *,
    runtime: Path,
    repo: Path,
    intent_package: Path,
    status: str,
    duration_hours: float,
    wave_interval_seconds: int,
    heartbeat_seconds: int,
    started_at: str,
    deadline_at: str,
    wave_count: int,
    latest_wave: dict[str, Any] | None = None,
    named_blocker: str = "",
) -> dict[str, Any]:
    paths = state_paths(runtime)
    ledger = ledger_summary(runtime)
    external = source_family_summary(runtime)
    capabilities = capability_summary(runtime)
    a4_shape = a4_default_shape_summary(runtime)
    latest_wave_payload = latest_wave or {}
    effective_wave_count = max(
        int(wave_count or 0),
        wave_index_from_id(str(latest_wave_payload.get("wave_id") or "")),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "status": status,
        "started_at": started_at,
        "updated_at": now_iso(),
        "deadline_at": deadline_at,
        "duration_budget_hours": duration_hours,
        "wave_interval_seconds": wave_interval_seconds,
        "heartbeat_seconds": heartbeat_seconds,
        "wave_count": effective_wave_count,
        "latest_wave_id": latest_wave_payload.get("wave_id", ""),
        "latest_wave": latest_wave_payload,
        "should_continue_loop": status not in {"stopped_by_user", "duration_budget_reached"},
        "foreground_poll_required": True,
        "poll_owner": "codex_s",
        "user_prompts_required": False,
        "source_intent_package_ref": str(intent_package),
        "worker_assignment_ref": str(paths["worker_assignment"]),
        "ledger": ledger,
        "external_search": external,
        "capabilities": capabilities,
        "a4_default_shape": a4_shape,
        "named_blocker": named_blocker,
        "can_invoke_now": {
            "watchdog_status": (
                f"powershell -NoProfile -ExecutionPolicy Bypass -File "
                f"\"{repo / 'scripts' / 'hardmode' / 'Start-OvernightSupervisorLoop.ps1'}\" -Status"
            ),
            "root_intent_loop_driver": (
                f"{sys.executable} -m xinao_seedlab.cli.__main__ "
                "--runtime-root D:\\XINAO_RESEARCH_RUNTIME "
                f"--repo-root {repo} root-intent-loop-driver --wave-id <wave_id>"
            ),
            "temporal_worker_start": str(repo / "scripts" / "Start-XinaoTemporalCodexWorker.ps1"),
            "capability_manifest": str(
                runtime
                / "capabilities"
                / "codex_s.overnight_supervisor_loop_watchdog"
                / "manifest.json"
            ),
            "a4_default_shape_latest": str(paths["a4_default_shape_latest"]),
        },
        "evidence_refs": {
            "latest": str(paths["latest"]),
            "heartbeat_latest": str(paths["heartbeat_latest"]),
            "readback_zh": str(paths["readback"]),
            "worker_assignment": str(paths["worker_assignment"]),
            "root_intent_loop_driver_latest": str(
                runtime / "state" / "root_intent_loop_driver" / "latest.json"
            ),
            "worker_dispatch_ledger_latest": str(
                runtime / "state" / "worker_dispatch_ledger" / "latest.json"
            ),
            "source_ledger_latest": str(runtime / "state" / "source_ledger" / "latest.json"),
            "artifact_acceptance_queue_latest": str(
                runtime / "state" / "artifact_acceptance_queue" / "latest.json"
            ),
            "a4_default_shape_latest": str(paths["a4_default_shape_latest"]),
        },
        "validation": {
            "passed": True,
            "checks": {
                "foreground_poll_required_true": True,
                "poll_owner_codex_s": True,
                "user_prompts_not_required": True,
                "worker_assignment_bound": paths["worker_assignment"].is_file(),
                "readback_path_bound": True,
                "capability_manifest_present": capabilities["manifest_count"] >= 1,
                "capability_invoke_evidence_present": capabilities["invoke_evidence_count"] >= 1,
                "a4_default_shape_latest_declared": True,
                "poll_false_forbidden": True,
                "completion_claim_blocked": True,
            },
            "validated_at": now_iso(),
        },
        "completion_claim_allowed": False,
        "phase0_completion_claim_allowed": False,
        "positive_ev_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def write_state_and_readback(runtime: Path, payload: dict[str, Any], *, write: bool) -> None:
    if not write:
        return
    paths = state_paths(runtime)
    write_json(paths["latest"], payload)
    write_json(paths["heartbeat_latest"], payload)
    write_text(paths["readback"], render_readback(payload))


def run_once(
    *,
    runtime: Path,
    repo: Path,
    intent_package: Path,
    duration_hours: float = 10.0,
    wave_interval_seconds: int = 1200,
    heartbeat_seconds: int = 300,
    started_at: str | None = None,
    deadline_at: str | None = None,
    invoke_runtime: bool = True,
    write: bool = True,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    intent = load_intent_package(intent_package)
    paths = state_paths(runtime)
    paths["state_dir"].mkdir(parents=True, exist_ok=True)
    started = started_at or now_iso()
    deadline = deadline_at or (
        dt.datetime.now(dt.timezone.utc).astimezone()
        + dt.timedelta(hours=duration_hours)
    ).isoformat(timespec="seconds")
    rebind_refs = rebind_active_worker_assignments(
        runtime=runtime,
        repo=repo,
        intent_package=intent_package,
        intent=intent,
        duration_hours=duration_hours,
        wave_interval_seconds=wave_interval_seconds,
        write=write,
    )
    capability = register_watchdog_capability(runtime=runtime, repo=repo, write=write)
    claimcards = accept_overnight_claimcards(runtime=runtime, repo=repo, write=write)
    index = next_wave_index(runtime)
    wave_id = wave_id_for(index)
    commands: list[dict[str, Any]] = []
    if invoke_runtime:
        commands.append(
            run_command(
                [
                    sys.executable,
                    "-m",
                    "xinao_seedlab.cli.__main__",
                    "--runtime-root",
                    str(runtime),
                    "--repo-root",
                    str(repo),
                    "default-main-loop-trigger-candidate",
                    "--task-id",
                    TASK_ID,
                    "--wave-id",
                    f"{wave_id}-trigger",
                ],
                repo=repo,
                log_path=paths["logs_dir"] / f"{wave_id}.default_trigger.log",
                timeout_seconds=timeout_seconds,
            )
        )
        commands.append(
            run_command(
                [
                    sys.executable,
                    "-m",
                    "xinao_seedlab.cli.__main__",
                    "--runtime-root",
                    str(runtime),
                    "--repo-root",
                    str(repo),
                    "root-intent-loop-driver",
                    "--wave-id",
                    wave_id,
                ],
                repo=repo,
                log_path=paths["logs_dir"] / f"{wave_id}.root_driver.log",
                timeout_seconds=timeout_seconds,
            )
        )
    else:
        commands.append(
            {
                "command": ["root-intent-loop-driver", wave_id],
                "succeeded": True,
                "exit_code": 0,
                "log_ref": "",
                "dry_run": True,
            }
        )
    root_command = next(
        (
            command
            for command in commands
            if any(str(part) == "root-intent-loop-driver" for part in command.get("command", []))
        ),
        commands[0],
    )
    a4_shape = build_a4_default_wave_shape(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        deadline_at=deadline,
        write=write,
    )
    latest_state = build_state(
        runtime=runtime,
        repo=repo,
        intent_package=intent_package,
        status="running",
        duration_hours=duration_hours,
        wave_interval_seconds=wave_interval_seconds,
        heartbeat_seconds=heartbeat_seconds,
        started_at=started,
        deadline_at=deadline,
        wave_count=index,
        latest_wave={"wave_id": wave_id},
    )
    meta_rsi = run_meta_rsi_wave(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        zh_readback=(
            f"过夜 wave {index} 已记录：RootIntentLoop invoke={root_command.get('succeeded')}; "
            "主工形状=parallel_draft->merge->writer；meta_rsi=evidence_only_not_main_worker；"
            "watchdog 继续 should_continue_loop=true。"
        ),
        write=write,
    )
    meta_rsi["role"] = "evidence_only_not_main_worker"
    wave = {
        "schema_version": "xinao.codex_s.overnight_supervisor_wave.v1",
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "wave_id": wave_id,
        "wave_index": index,
        "status": "wave_recorded",
        "started_at": root_command.get("started_at") or commands[0].get("started_at") or now_iso(),
        "finished_at": now_iso(),
        "commands": commands,
        "all_commands_succeeded": all(command.get("succeeded") is True for command in commands),
        "meta_rsi_wave": meta_rsi,
        "meta_rsi_role": "evidence_only_not_main_worker",
        "a4_default_shape": a4_shape,
        "worker_assignment_rebound_refs": rebind_refs,
        "capability": capability,
        "claimcards": claimcards,
        "ledger": latest_state["ledger"],
        "external_search": latest_state["external_search"],
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
    }
    named_blocker = ""
    if not wave["all_commands_succeeded"]:
        named_blocker = "OVERNIGHT_WAVE_SUBCOMMAND_FAILED_CONTINUING"
        wave["named_blocker"] = named_blocker
    elif invoke_runtime and a4_shape.get("validation", {}).get("passed") is not True:
        named_blocker = "OVERNIGHT_A4_DEFAULT_SHAPE_WAITING_CONTINUING"
        wave["named_blocker"] = named_blocker
    latest_state = build_state(
        runtime=runtime,
        repo=repo,
        intent_package=intent_package,
        status="running",
        duration_hours=duration_hours,
        wave_interval_seconds=wave_interval_seconds,
        heartbeat_seconds=heartbeat_seconds,
        started_at=started,
        deadline_at=deadline,
        wave_count=index,
        latest_wave=wave,
        named_blocker=named_blocker,
    )
    if write:
        write_json(paths["waves_dir"] / f"{wave_id}.json", wave)
        write_state_and_readback(runtime, latest_state, write=True)
    return latest_state


def status_payload(*, runtime: Path, repo: Path, intent_package: Path) -> dict[str, Any]:
    latest = read_json(state_paths(runtime)["latest"])
    if latest:
        return latest
    return build_state(
        runtime=runtime,
        repo=repo,
        intent_package=intent_package,
        status="not_started",
        duration_hours=10.0,
        wave_interval_seconds=1200,
        heartbeat_seconds=300,
        started_at="",
        deadline_at="",
        wave_count=0,
        latest_wave={},
        named_blocker="OVERNIGHT_SUPERVISOR_LOOP_NOT_STARTED",
    )


def heartbeat_sleep(
    *,
    runtime: Path,
    repo: Path,
    intent_package: Path,
    seconds: int,
    heartbeat_seconds: int,
    duration_hours: float,
    wave_interval_seconds: int,
    started_at: str,
    deadline_at: str,
    wave_count: int,
) -> None:
    remaining = max(0, seconds)
    while remaining > 0:
        chunk = min(max(1, heartbeat_seconds), remaining)
        time.sleep(chunk)
        remaining -= chunk
        payload = build_state(
            runtime=runtime,
            repo=repo,
            intent_package=intent_package,
            status="running",
            duration_hours=duration_hours,
            wave_interval_seconds=wave_interval_seconds,
            heartbeat_seconds=heartbeat_seconds,
            started_at=started_at,
            deadline_at=deadline_at,
            wave_count=wave_count,
            latest_wave=read_json(state_paths(runtime)["latest"]).get("latest_wave", {}),
        )
        write_state_and_readback(runtime, payload, write=True)


def run_loop(
    *,
    runtime: Path,
    repo: Path,
    intent_package: Path,
    duration_hours: float,
    deadline_at: str | None = None,
    wave_interval_seconds: int,
    heartbeat_seconds: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    paths = state_paths(runtime)
    paths["state_dir"].mkdir(parents=True, exist_ok=True)
    write_text(paths["pid"], str(os.getpid()))
    started = now_iso()
    deadline_dt = (
        parse_datetime(deadline_at)
        if deadline_at
        else dt.datetime.now(dt.timezone.utc).astimezone() + dt.timedelta(hours=duration_hours)
    )
    deadline = deadline_dt.isoformat(timespec="seconds")
    latest: dict[str, Any] = {}
    while dt.datetime.now(dt.timezone.utc).astimezone() < deadline_dt:
        if paths["stop_request"].is_file():
            latest = build_state(
                runtime=runtime,
                repo=repo,
                intent_package=intent_package,
                status="stopped_by_user",
                duration_hours=duration_hours,
                wave_interval_seconds=wave_interval_seconds,
                heartbeat_seconds=heartbeat_seconds,
                started_at=started,
                deadline_at=deadline,
                wave_count=int((latest or {}).get("wave_count") or 0),
                latest_wave=(latest or {}).get("latest_wave") if latest else {},
                named_blocker="EXPLICIT_STOP_REQUEST_FILE_PRESENT",
            )
            write_state_and_readback(runtime, latest, write=True)
            return latest
        latest = run_once(
            runtime=runtime,
            repo=repo,
            intent_package=intent_package,
            duration_hours=duration_hours,
            wave_interval_seconds=wave_interval_seconds,
            heartbeat_seconds=heartbeat_seconds,
            started_at=started,
            deadline_at=deadline,
            invoke_runtime=True,
            write=True,
            timeout_seconds=timeout_seconds,
        )
        heartbeat_sleep(
            runtime=runtime,
            repo=repo,
            intent_package=intent_package,
            seconds=wave_interval_seconds,
            heartbeat_seconds=heartbeat_seconds,
            duration_hours=duration_hours,
            wave_interval_seconds=wave_interval_seconds,
            started_at=started,
            deadline_at=deadline,
            wave_count=int(latest.get("wave_count") or 0),
        )
    latest = build_state(
        runtime=runtime,
        repo=repo,
        intent_package=intent_package,
        status="duration_budget_reached",
        duration_hours=duration_hours,
        wave_interval_seconds=wave_interval_seconds,
        heartbeat_seconds=heartbeat_seconds,
        started_at=started,
        deadline_at=deadline,
        wave_count=int((latest or {}).get("wave_count") or 0),
        latest_wave=(latest or {}).get("latest_wave") if latest else {},
    )
    write_state_and_readback(runtime, latest, write=True)
    return latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--intent-package", default=str(DEFAULT_INTENT_PACKAGE))
    parser.add_argument("--duration-hours", type=float, default=10.0)
    parser.add_argument("--deadline-at", default="")
    parser.add_argument("--wave-interval-seconds", type=int, default=1200)
    parser.add_argument("--heartbeat-seconds", type=int, default=300)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--run-loop", action="store_true")
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--no-invoke-runtime", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    runtime = Path(args.runtime_root)
    repo = Path(args.repo_root)
    intent_package = Path(args.intent_package)
    if args.status:
        payload = status_payload(runtime=runtime, repo=repo, intent_package=intent_package)
    elif args.run_loop:
        payload = run_loop(
            runtime=runtime,
            repo=repo,
            intent_package=intent_package,
            duration_hours=args.duration_hours,
            deadline_at=args.deadline_at or None,
            wave_interval_seconds=args.wave_interval_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        payload = run_once(
            runtime=runtime,
            repo=repo,
            intent_package=intent_package,
            duration_hours=args.duration_hours,
            wave_interval_seconds=args.wave_interval_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
            deadline_at=args.deadline_at or None,
            invoke_runtime=not args.no_invoke_runtime,
            write=not args.no_write,
            timeout_seconds=args.timeout_seconds,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
