from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.333_control_vs_evidence_boundary_contract.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_333_CONTROL_VS_EVIDENCE_BOUNDARY_READY"
TASK_ID = "codex_333_control_vs_evidence_boundary_contract_20260706"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TOOL_PROVIDER_ID = "codex_s.333_control_vs_evidence_boundary_contract"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_SOURCE_ROOT = Path(r"C:\Users\xx363\Desktop\新建文件夹")
DEFAULT_SOURCE_FILES = [
    DEFAULT_SOURCE_ROOT / "333_DEFAULT_CHAIN_EVOLUTION_QWEN_DP_AUDIT_20260705.txt",
    DEFAULT_SOURCE_ROOT / "333_DEFAULT_CHAIN_GLOBAL_REPAIR_PACKAGE_20260705.txt",
    DEFAULT_SOURCE_ROOT / "333_GLOBAL_CAPABILITY_ISLAND_INVENTORY_QWEN_DP_20260705.txt",
    DEFAULT_SOURCE_ROOT / "333_S_HANDOFF_MERGED_LANDABLE_PACKAGE_QWEN_DP_20260705.txt",
    DEFAULT_SOURCE_ROOT / "GLOBAL_MAINCHAIN_CONFLICT_AUDIT_QWEN_DP_ONLY_20260705.txt",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "codex_333_control_vs_evidence_boundary_contract"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "readback": runtime / "readback" / "zh" / "codex_333_control_vs_evidence_boundary_contract.md",
    }


def file_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_package(files: list[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    combined = ""
    for path in files:
        text = file_text(path)
        combined += "\n" + text
        lines = text.splitlines()
        records.append(
            {
                "path": str(path),
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else 0,
                "line_count": len(lines),
                "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
                if text
                else "",
                "mentions_control_vs_evidence_contract": (
                    "control_vs_evidence_boundary_contract" in text
                ),
                "mentions_latest_json_authority_risk": "latest.json" in text,
                "mentions_control_data_plane_split": "control_data_plane_split" in text,
            }
        )
    return {
        "source_root": str(files[0].parent if files else DEFAULT_SOURCE_ROOT),
        "file_count": len(records),
        "all_files_exist": all(item["exists"] for item in records),
        "all_files_read_full": all(item["exists"] and item["line_count"] > 0 for item in records),
        "total_bytes": sum(int(item["bytes"] or 0) for item in records),
        "control_vs_evidence_mentions": combined.count(
            "control_vs_evidence_boundary_contract"
        ),
        "latest_json_mentions": combined.count("latest.json"),
        "completion_mentions": combined.lower().count("completion"),
        "runtime_enforced_mentions": combined.count("runtime_enforced"),
        "dispatch_mentions": combined.lower().count("dispatch"),
        "files": records,
    }


def external_mature_claimcards() -> list[dict[str, str]]:
    return [
        {
            "source_family": "official_temporal",
            "url": "https://docs.temporal.io/workflow-execution/event",
            "claim": (
                "Temporal tracks workflow progress by appending events to Event History; "
                "commands and activity terminal events are persisted there."
            ),
            "accepted_for": "control_plane_temporal_event_history",
        },
        {
            "source_family": "official_temporal",
            "url": "https://docs.temporal.io/encyclopedia/event-history",
            "claim": (
                "Workflow code issues Commands to the Temporal Service; the service maps "
                "Commands to Events and replays Event History to recreate workflow state."
            ),
            "accepted_for": "command_to_event_boundary",
        },
        {
            "source_family": "microsoft_azure_architecture_cqrs",
            "url": "https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs",
            "claim": (
                "CQRS separates write models from read models; read models are eventually "
                "consistent and should not run write-side business decisions."
            ),
            "accepted_for": "latest_json_read_model_boundary",
        },
        {
            "source_family": "microsoft_azure_architecture_materialized_view",
            "url": "https://learn.microsoft.com/en-us/azure/architecture/patterns/materialized-view",
            "claim": (
                "Materialized views are optimized disposable views rebuilt from source data, "
                "not directly updated by applications as the authority."
            ),
            "accepted_for": "runtime_latest_as_disposable_projection",
        },
        {
            "source_family": "microsoft_azure_architecture_event_sourcing",
            "url": "https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing",
            "claim": (
                "Event sourcing stores intent-bearing chronological events; CQRS uses those "
                "events to materialize read views."
            ),
            "accepted_for": "event_store_write_model_projection_read_model",
        },
        {
            "source_family": "martin_fowler_cqrs",
            "url": "https://martinfowler.com/bliki/CQRS.html",
            "claim": (
                "CQRS uses different models for updating information and reading information; "
                "the added complexity must be explicit."
            ),
            "accepted_for": "explicit_control_evidence_split",
        },
    ]


def boundary_contract() -> dict[str, Any]:
    control_plane = [
        {
            "authority_id": "temporal_event_history",
            "accepted_inputs": [
                "WorkflowExecutionStarted",
                "WorkflowTaskCompleted",
                "ActivityTaskScheduled",
                "ActivityTaskStarted",
                "ActivityTaskCompleted",
                "ActivityTaskFailed",
                "ActivityTaskTimedOut",
                "WorkflowExecutionSignaled",
            ],
            "may_trigger_dispatch": True,
            "may_trigger_completion_claim": False,
            "runtime_enforced_source_allowed": True,
        },
        {
            "authority_id": "workflow_state",
            "accepted_inputs": ["server-bound workflow_id", "server-bound run_id", "workflow status"],
            "may_trigger_dispatch": True,
            "may_trigger_completion_claim": False,
            "runtime_enforced_source_allowed": True,
        },
        {
            "authority_id": "accepted_task_control_command",
            "accepted_inputs": [
                "task_control signal accepted by workflow",
                "insert_front command accepted by workflow",
                "pause_after_current_wave command accepted by workflow",
            ],
            "may_trigger_dispatch": True,
            "may_trigger_completion_claim": False,
            "runtime_enforced_source_allowed": True,
        },
        {
            "authority_id": "artifact_acceptance_decision",
            "accepted_inputs": ["AAQ accepted/rejected decision with artifact hash"],
            "may_trigger_dispatch": False,
            "may_trigger_completion_claim": False,
            "runtime_enforced_source_allowed": False,
        },
    ]
    evidence_plane = [
        "latest.json",
        "readback.md",
        "verifier PASS",
        "worker brief",
        "planned lane",
        "scheduler_spawned_lane_evidence",
        "tool_registry.json",
        "capability manifest",
        "ClaimCard",
        "desktop memo",
        "docs/current",
    ]
    forbidden_promotions = [
        "latest_json_triggers_dispatch",
        "latest_json_triggers_completion",
        "readback_or_pass_triggers_completion",
        "planned_lane_counts_as_execution",
        "worker_brief_counts_as_dispatched",
        "scheduler_spawned_lane_evidence_counts_as_default_runtime",
        "tool_registry_provider_visible_counts_as_invoked",
        "runtime_enforced_without_temporal_or_same_wave_truth_chain",
    ]
    return {
        "control_plane": control_plane,
        "evidence_plane_read_models": evidence_plane,
        "forbidden_promotions": forbidden_promotions,
        "latest_json_role": "disposable_read_model_projection_not_control_authority",
        "readback_role": "human_readable_projection_not_completion_gate",
        "pass_role": "verification_result_not_user_completion",
        "tool_registry_role": "capability_discovery_not_invocation",
        "required_promotion_chain": [
            "accepted command or server-bound workflow event",
            "provider/tool invocation terminal event",
            "staging artifact with content hash",
            "fan-in/merge decision",
            "ArtifactAcceptanceQueue accepted/rejected decision",
            "read model projection update",
        ],
        "completion_boundary": {
            "user_completion_claim_allowed": False,
            "requires_task_scoped_artifact_acceptance": True,
            "latest_or_readback_sufficient": False,
        },
    }


def runtime_refs(repo: Path, runtime: Path) -> dict[str, Any]:
    current = runtime / "state" / "current_333_run_index" / "latest.json"
    trigger = runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
    ledger = runtime / "state" / "worker_dispatch_ledger" / "latest.json"
    aaq = runtime / "state" / "artifact_acceptance_queue" / "latest.json"
    registry = runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json"
    continuity = runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json"
    cli = repo / "src" / "xinao_seedlab" / "cli" / "__main__.py"
    l0 = repo / "CODEX_S_L0.md"
    docs_boundary = repo / "docs" / "current" / "CODEX_S_CURRENT_DOCS_BOUNDARY_2026-07-02.md"
    refs = {
        "current_333_run_index": current,
        "default_main_loop_trigger": trigger,
        "worker_dispatch_ledger": ledger,
        "artifact_acceptance_queue": aaq,
        "tool_registry": registry,
        "continuity_router": continuity,
        "cli": cli,
        "l0": l0,
        "current_docs_boundary": docs_boundary,
    }
    payloads = {name: read_json(path) for name, path in refs.items() if path.suffix == ".json"}
    registry_payload = payloads.get("tool_registry", {})
    provider_ids = registry_payload.get("provider_ids")
    provider_ids = provider_ids if isinstance(provider_ids, list) else []
    trigger_payload = payloads.get("default_main_loop_trigger", {})
    no_stop = (
        trigger_payload.get("no_stop_wave_consumption_refs")
        if isinstance(trigger_payload.get("no_stop_wave_consumption_refs"), dict)
        else {}
    )
    current_payload = payloads.get("current_333_run_index", {})
    temporal = current_payload.get("temporal") if isinstance(current_payload.get("temporal"), dict) else {}
    aaq_payload = payloads.get("artifact_acceptance_queue", {})
    ledger_payload = payloads.get("worker_dispatch_ledger", {})
    return {
        "paths": {name: str(path) for name, path in refs.items()},
        "current_333_run_index": {
            "exists": current.is_file(),
            "status": current_payload.get("status", ""),
            "workflow_id": current_payload.get("workflow_id", ""),
            "workflow_run_id": current_payload.get("workflow_run_id", ""),
            "temporal_port_open": temporal.get("port_open"),
            "temporal_status": temporal.get("status", ""),
            "history_length": temporal.get("history_length"),
            "not_source_of_truth": current_payload.get("not_source_of_truth"),
            "not_execution_controller": current_payload.get("not_execution_controller"),
        },
        "default_main_loop_trigger": {
            "exists": trigger.is_file(),
            "status": trigger_payload.get("status", ""),
            "runtime_enforced": trigger_payload.get("runtime_enforced"),
            "runtime_enforced_scope": trigger_payload.get("runtime_enforced_scope", ""),
            "is_completion_gate": trigger_payload.get("is_completion_gate"),
            "not_execution_controller": trigger_payload.get("not_execution_controller"),
            "refs_are_evidence_only": no_stop.get("refs_are_evidence_only"),
            "refs_are_not_completion_gates": no_stop.get("refs_are_not_completion_gates"),
            "refs_are_not_execution_controllers": no_stop.get(
                "refs_are_not_execution_controllers"
            ),
        },
        "worker_dispatch_ledger": {
            "exists": ledger.is_file(),
            "status": ledger_payload.get("status", ""),
            "poll_result_summary": ledger_payload.get("poll_result_summary", {}),
            "not_source_of_truth": ledger_payload.get("not_source_of_truth"),
            "not_completion_decision": ledger_payload.get("not_completion_decision"),
            "not_execution_controller": ledger_payload.get("not_execution_controller"),
        },
        "artifact_acceptance_queue": {
            "exists": aaq.is_file(),
            "status": aaq_payload.get("status", ""),
            "unique_accepted_artifact_count": aaq_payload.get("unique_accepted_artifact_count"),
            "direct_fact_promotion_allowed": aaq_payload.get("direct_fact_promotion_allowed"),
            "completion_claim_allowed": aaq_payload.get("completion_claim_allowed"),
            "not_execution_controller": aaq_payload.get("not_execution_controller"),
        },
        "tool_registry": {
            "exists": registry.is_file(),
            "status": registry_payload.get("status", ""),
            "provider_visible": TOOL_PROVIDER_ID in provider_ids,
            "provider_ids": provider_ids,
            "not_source_of_truth": registry_payload.get("not_source_of_truth"),
            "not_execution_controller": registry_payload.get("not_execution_controller"),
        },
        "continuity_router": {
            "exists": continuity.is_file(),
            "next_required_artifact": payloads.get("continuity_router", {}).get(
                "next_required_artifact", ""
            ),
        },
        "cli": {
            "exists": cli.is_file(),
            "registered": "333-control-vs-evidence-boundary-contract" in file_text(cli),
        },
        "l0": {
            "exists": l0.is_file(),
            "sha256": file_sha256(l0),
            "declares_latest_not_stop_condition": "Reports, PASS, drafts" in file_text(l0)
            and "latest" in file_text(l0),
        },
        "current_docs_boundary": {
            "exists": docs_boundary.is_file(),
            "sha256": file_sha256(docs_boundary),
            "declares_latest_read_model_only": "Latest aliases are convenient read models only"
            in file_text(docs_boundary),
        },
    }


def validation(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source_package") if isinstance(payload.get("source_package"), dict) else {}
    refs = payload.get("runtime_refs") if isinstance(payload.get("runtime_refs"), dict) else {}
    contract = payload.get("boundary_contract") if isinstance(payload.get("boundary_contract"), dict) else {}
    tool_registry = refs.get("tool_registry") if isinstance(refs.get("tool_registry"), dict) else {}
    trigger = refs.get("default_main_loop_trigger") if isinstance(refs.get("default_main_loop_trigger"), dict) else {}
    aaq = refs.get("artifact_acceptance_queue") if isinstance(refs.get("artifact_acceptance_queue"), dict) else {}
    continuity = refs.get("continuity_router") if isinstance(refs.get("continuity_router"), dict) else {}
    cli = refs.get("cli") if isinstance(refs.get("cli"), dict) else {}
    l0 = refs.get("l0") if isinstance(refs.get("l0"), dict) else {}
    docs_boundary = (
        refs.get("current_docs_boundary")
        if isinstance(refs.get("current_docs_boundary"), dict)
        else {}
    )
    checks = {
        "source_files_read": source.get("all_files_read_full") is True,
        "source_mentions_contract": int(source.get("control_vs_evidence_mentions") or 0) > 0,
        "external_mature_claimcards_present": len(payload.get("external_mature_claimcards", [])) >= 4,
        "control_plane_authorities_present": len(contract.get("control_plane", [])) >= 3,
        "latest_json_read_model_only": (
            contract.get("latest_json_role")
            == "disposable_read_model_projection_not_control_authority"
        ),
        "forbidden_promotions_present": len(contract.get("forbidden_promotions", [])) >= 6,
        "promotion_chain_requires_aaq": "ArtifactAcceptanceQueue accepted/rejected decision"
        in contract.get("required_promotion_chain", []),
        "default_trigger_refs_evidence_only": (
            trigger.get("refs_are_evidence_only") is True
            and trigger.get("refs_are_not_completion_gates") is True
            and trigger.get("refs_are_not_execution_controllers") is True
        ),
        "aaq_direct_fact_promotion_denied": aaq.get("direct_fact_promotion_allowed") is False,
        "tool_registry_provider_visible": tool_registry.get("provider_visible") is True,
        "tool_registry_not_execution_controller": tool_registry.get("not_execution_controller") is True,
        "continuity_points_here": continuity.get("next_required_artifact")
        in {
            "control_vs_evidence_boundary_contract.v1",
            "lane_lifecycle_metric_contract.v1",
        },
        "cli_entrypoint_registered": cli.get("registered") is True,
        "l0_or_docs_declares_latest_boundary": (
            l0.get("declares_latest_not_stop_condition") is True
            or docs_boundary.get("declares_latest_read_model_only") is True
        ),
        "completion_claim_disallowed": payload.get("completion_claim_allowed") is False,
        "not_execution_controller": payload.get("not_execution_controller") is True,
    }
    return {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()}


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    source_files: list[Path] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    files = source_files or list(DEFAULT_SOURCE_FILES)
    paths = output_paths(runtime)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "repo_root": str(repo),
        "runtime_root": str(runtime),
        "source_package": source_package(files),
        "external_mature_claimcards": external_mature_claimcards(),
        "boundary_contract": boundary_contract(),
        "runtime_refs": runtime_refs(repo, runtime),
        "accepted_for": ["P0.control_vs_evidence_boundary_contract"],
        "adoption_state": "default_hot_path_ready",
        "default_mainline_hardened": True,
        "workspace_only": False,
        "default_consumer": (
            "S ToolRegistry / default trigger no-stop refs / stateful continuity router / "
            "startup docs boundary read model"
        ),
        "next_required_artifact": "lane_lifecycle_metric_contract.v1",
        "not_user_completion": True,
        "completion_claim_allowed": False,
        "not_completion_gate": True,
        "not_execution_controller": True,
        "output_paths": {key: str(value) for key, value in paths.items()},
        "generated_at": now_iso(),
    }
    payload["validation"] = validation(payload)
    payload["status"] = (
        "control_vs_evidence_boundary_contract_ready"
        if payload["validation"]["passed"] is True
        else "control_vs_evidence_boundary_contract_blocked"
    )
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    validation_payload = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    contract = payload.get("boundary_contract") if isinstance(payload.get("boundary_contract"), dict) else {}
    return "\n".join(
        [
            "# 333 control vs evidence boundary contract",
            "",
            SENTINEL,
            "",
            f"- status: `{payload.get('status')}`",
            f"- accepted_for: `{', '.join(payload.get('accepted_for', []))}`",
            f"- next_required_artifact: `{payload.get('next_required_artifact')}`",
            f"- control_authority_count: {len(contract.get('control_plane', []))}",
            f"- forbidden_promotion_count: {len(contract.get('forbidden_promotions', []))}",
            f"- default_consumer: `{payload.get('default_consumer')}`",
            f"- validation_passed: {validation_payload.get('passed')}",
            "- boundary: Temporal/workflow commands/events own control; latest/readback/PASS/tool registry are evidence/read models only.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        source_files=[Path(item) for item in args.source_file] if args.source_file else None,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
