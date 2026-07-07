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

from services.agent_runtime import task_package_resolver


SCHEMA_VERSION = "xinao.codex_s.current_task_source_intake.v1"
SENTINEL = "SENTINEL:XINAO_CURRENT_TASK_SOURCE_INTAKE_READY"
TASK_ID = "p0_006_current_three_text_source_intake"
SOURCE_PACKAGE_ID = "current_p0_three_text_20260707"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_PACKAGE_ROOT = Path(
    os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统")
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str, *, limit: int = 120) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in str(value)).strip("-._")
    if not cleaned:
        cleaned = "current-task-source"
    if len(cleaned) <= limit:
        return cleaned
    digest = hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{cleaned[: limit - 13]}-{digest}"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "current_task_source_intake"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "worker_brief_queue": state / "worker_brief_queue_latest.json",
        "canonical_worker_brief_queue": runtime / "state" / "worker_brief_queue" / "latest.json",
        "compat_worker_brief_queue": runtime / "state" / "worker_brief" / "latest.json",
        "source_ledger": runtime / "state" / "source_ledger" / "latest.json",
        "readback": runtime / "readback" / "zh" / "current_task_source_intake_20260707.md",
        "capability_manifest": runtime
        / "capabilities"
        / "codex_s.current_task_source_intake"
        / "manifest.json",
    }


def current_workflow(runtime: Path) -> dict[str, str]:
    payload = read_json(runtime / "state" / "current_333_run_index" / "latest.json")
    return {
        "workflow_id": str(payload.get("workflow_id") or ""),
        "workflow_run_id": str(payload.get("workflow_run_id") or ""),
        "status": str(payload.get("status") or ""),
    }


def source_refs_from_current_package(runtime: Path, task_package_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    package = task_package_resolver.resolve_task_package(
        task_package_root,
        include_manifest_ref=True,
        runtime_root=runtime,
    )
    refs = [
        ref
        for ref in task_package_resolver.source_refs_from_package(package)
        if isinstance(ref, dict) and ref.get("read_full") is True and ref.get("role") != "task_package_manifest"
    ]
    return package, refs


def build_source_entries(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, ref in enumerate(refs, start=1):
        path = str(ref.get("path") or "")
        role = str(ref.get("role") or "current_task_resource")
        digest_basis = {
            "source_package_id": SOURCE_PACKAGE_ID,
            "path": path,
            "role": role,
            "sha256": str(ref.get("sha256") or ""),
        }
        digest = hashlib.sha256(
            json.dumps(digest_basis, ensure_ascii=False, sort_keys=True).encode(
                "utf-8", errors="replace"
            )
        ).hexdigest()[:16]
        entries.append(
            {
                "entry_id": f"source-ledger:{safe_stem(SOURCE_PACKAGE_ID)}:{index:02d}:{digest}",
                "candidate_id": f"{SOURCE_PACKAGE_ID}:{index:02d}:{safe_stem(Path(path).name)}",
                "object_type": "SourceLedgerEntry",
                "source_package_id": SOURCE_PACKAGE_ID,
                "source_url": path,
                "source_family": "current_task_three_text_package",
                "source_role": role,
                "source_name": str(ref.get("name") or Path(path).name),
                "claim": f"Current task package resource {Path(path).name} was read in full for P0 delivery execution.",
                "verification_need": "Verify sha256/read_full and consume this entry when building WorkerBrief queue.",
                "accepted_for": "current_task_source_intake",
                "claim_card_ref": path,
                "sha256": str(ref.get("sha256") or ""),
                "size_bytes": int(ref.get("size_bytes") or 0),
                "line_count": int(ref.get("line_count") or 0),
                "read_full": ref.get("read_full") is True,
                "raw_secret_values_recorded": False,
                "direct_fact_promotion_allowed": False,
                "completion_claim_allowed": False,
                "not_source_of_truth": True,
                "not_user_completion": True,
                "not_completion_decision": True,
                "not_execution_controller": True,
            }
        )
    return entries


def provider_candidates_for_role(role: str) -> list[str]:
    if role == "p0_execution_entrypoint":
        return ["qwen_prepaid_cheap_worker", "deepseek_v4_pro", "codex_exec"]
    if role == "p1_gate_context":
        return ["qwen_prepaid_cheap_worker", "deepseek_dp", "codex_exec"]
    return ["qwen_prepaid_cheap_worker", "deepseek_dp", "codex_exec"]


def build_worker_brief_queue(*, source_entries: list[dict[str, Any]], workflow: dict[str, str]) -> dict[str, Any]:
    briefs: list[dict[str, Any]] = []
    for index, entry in enumerate(source_entries, start=1):
        role = str(entry.get("source_role") or "current_task_resource")
        source_name = str(entry.get("source_name") or f"source-{index:02d}")
        lane_class = "repo_exec" if role == "p0_execution_entrypoint" else "extraction"
        brief_id = f"{TASK_ID}:brief:{index:02d}:{safe_stem(role)}"
        briefs.append(
            {
                "brief_id": brief_id,
                "worker_brief_id": brief_id,
                "task_id": TASK_ID,
                "source_package_id": SOURCE_PACKAGE_ID,
                "workflow_id": workflow.get("workflow_id") or "",
                "workflow_run_id": workflow.get("workflow_run_id") or "",
                "lane_id": f"{TASK_ID}:{safe_stem(role)}:{index:02d}",
                "lane_class": lane_class,
                "objective": (
                    f"Consume current task source {source_name} and produce dispatchable delivery work; "
                    "do not open next_frontier by default."
                ),
                "provider_candidates": provider_candidates_for_role(role),
                "provider_route_key": "engineering_patch_or_test"
                if role == "p0_execution_entrypoint"
                else "draft_extraction_classify_eval",
                "queue": "xinao-codex-task-default",
                "expected_artifact": "source_bound_delivery_candidate",
                "source_ledger_entry_id": str(entry.get("entry_id") or ""),
                "source_ref": str(entry.get("source_url") or ""),
                "source_sha256": str(entry.get("sha256") or ""),
                "source_role": role,
                "worker_output_must_enter_staging": True,
                "fan_in_target": "artifact_acceptance_queue",
                "accepted_for": "current_task_workerbrief",
                "next_frontier_default_outlet": False,
                "direct_final_allowed": False,
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            }
        )
    return {
        "schema_version": "xinao.codex_s.worker_brief_queue.v1",
        "status": "worker_brief_queue_ready" if briefs else "worker_brief_queue_blocked",
        "queue_id": SOURCE_PACKAGE_ID,
        "task_id": TASK_ID,
        "source_package_id": SOURCE_PACKAGE_ID,
        "workflow_id": workflow.get("workflow_id") or "",
        "workflow_run_id": workflow.get("workflow_run_id") or "",
        "brief_count": len(briefs),
        "source_entry_count": len(source_entries),
        "briefs": briefs,
        "source_ledger_entry_ids": [str(entry.get("entry_id") or "") for entry in source_entries],
        "dispatch_ready": bool(briefs),
        "default_mainline_binding": "SourceLedger -> WorkerBriefQueue -> ProviderScheduler",
        "next_frontier_default_outlet": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def build_capability_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.capability_manifest.v1",
        "provider_id": "codex_s.current_task_source_intake",
        "status": "registered",
        "capability_kinds": [
            "current_task_source_intake",
            "source_ledger_writer",
            "worker_brief_queue_writer",
        ],
        "task_id": TASK_ID,
        "runtime_latest": payload.get("output_paths", {}).get("latest", ""),
        "source_ledger_latest": payload.get("output_paths", {}).get("source_ledger", ""),
        "worker_brief_queue_latest": payload.get("output_paths", {}).get("canonical_worker_brief_queue", ""),
        "schema_ref": "contracts/schemas/codex_s_current_task_source_intake.v1.json",
        "verifier": "scripts/verify_current_task_source_intake.ps1",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def _load_default_service(runtime: Path, repo: Path):
    for item in (repo / "src", repo):
        text = str(item)
        if text not in sys.path:
            sys.path.insert(0, text)
    from xinao_seedlab.application.seed_cortex import build_default_service

    return build_default_service(runtime, repo_root=repo)


def build_current_task_source_intake(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_package_root: str | Path = DEFAULT_TASK_PACKAGE_ROOT,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    task_root = Path(task_package_root)
    paths = output_paths(runtime)
    package, refs = source_refs_from_current_package(runtime, task_root)
    source_entries = build_source_entries(refs)
    workflow = current_workflow(runtime)
    contract = read_json(runtime / "state" / "task_contract_router" / "latest.json")
    source_ledger = (
        _load_default_service(runtime, repo).global_source_ledger(
            task_id=TASK_ID,
            episode_id=f"{TASK_ID}-20260707",
            source_entries=source_entries,
            write_runtime=write,
        )
        if write
        else {
            "schema_version": "xinao.seedcortex.source_ledger.v1",
            "status": "source_ledger_ready" if source_entries else "source_ledger_empty",
            "entry_count": len(source_entries),
            "entries": source_entries,
            "validation": {"passed": bool(source_entries)},
            "output_paths": {"runtime_latest": str(paths["source_ledger"])},
        }
    )
    worker_brief_queue = build_worker_brief_queue(source_entries=source_entries, workflow=workflow)
    accepted_tasks = task_package_resolver.runtime_accepted_task_decisions(runtime)
    selected_or_accepted = (
        package.get("next_mature_bind_task_id") == TASK_ID or TASK_ID in accepted_tasks
    )
    current_contract_ready = (
        contract.get("status") == "execution_contract_ready"
        and contract.get("contract_id") == TASK_ID
        and bool(contract.get("workflow_run_id"))
        and contract.get("validation", {}).get("passed") is True
    )
    contract_ready = current_contract_ready or TASK_ID in accepted_tasks
    checks = {
        "current_package_selected_or_accepted": selected_or_accepted,
        "contract_ready": contract_ready,
        "all_package_refs_read_full": len(refs) >= 3 and all(ref.get("read_full") is True for ref in refs),
        "source_entries_written": int(source_ledger.get("entry_count") or 0) == len(source_entries) >= 3,
        "source_ledger_has_current_package": SOURCE_PACKAGE_ID
        in json.dumps(source_ledger, ensure_ascii=False),
        "worker_brief_queue_ready": worker_brief_queue.get("status") == "worker_brief_queue_ready",
        "brief_count_matches_source_entries": int(worker_brief_queue.get("brief_count") or 0)
        == len(source_entries),
        "briefs_bind_source_entries": all(
            brief.get("source_ledger_entry_id")
            for brief in worker_brief_queue.get("briefs", [])
            if isinstance(brief, dict)
        ),
        "workflow_bound": bool(workflow.get("workflow_id") and workflow.get("workflow_run_id")),
        "frontier_not_default_exit": worker_brief_queue.get("next_frontier_default_outlet") is False,
        "completion_claim_blocked": True,
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "current_task_source_intake_ready"
        if all(checks.values())
        else "current_task_source_intake_blocked",
        "source_package_id": SOURCE_PACKAGE_ID,
        "repo_root": str(repo),
        "runtime_root": str(runtime),
        "task_package_root": str(task_root),
        "task_package": {
            "mode": package.get("mode"),
            "next_mature_bind_task_id": str(package.get("next_mature_bind_task_id") or ""),
            "runtime_accepted_task_ids": package.get("runtime_accepted_task_ids") or [],
            "source_package_digest_sha256": package.get("source_package_digest_sha256"),
            "read_full_count": package.get("read_full_count"),
        },
        "task_contract_router": {
            "contract_id": str(contract.get("contract_id") or ""),
            "status": str(contract.get("status") or ""),
            "workflow_id": str(contract.get("workflow_id") or ""),
            "workflow_run_id": str(contract.get("workflow_run_id") or ""),
            "validation_passed": contract.get("validation", {}).get("passed") is True,
        },
        "current_workflow": workflow,
        "source_refs": refs,
        "source_entries": source_entries,
        "source_entry_count": len(source_entries),
        "source_ledger": source_ledger,
        "worker_brief_queue": worker_brief_queue,
        "acceptance": {
            "artifact_kind": "current_task_source_intake",
            "accepted_for": "accepted_for_delivery",
            "artifact_acceptance_decision": "accepted_for_delivery",
            "success_field": "current_task_source_intake_ready",
        },
        "next_machine_actions": [
            {
                "order": 1,
                "task_id": "p0_007_default_main_loop_trigger_bind",
                "action": "bind current WorkerBrief queue into the live r9 every-wave Temporal main loop",
                "blocker_if_failed": "DEFAULT_MAIN_LOOP_TRIGGER_NOT_EVERY_WAVE_ENFORCED",
            },
            {
                "order": 2,
                "task_id": "p0_008_worker_dispatch_real_receipt",
                "action": "consume WorkerBrief queue and write worker_dispatch_ledger succeeded only from provider receipts",
                "blocker_if_failed": "WORKER_DISPATCH_LEDGER_HAS_NO_REAL_PROVIDER_RECEIPT",
            },
        ],
        "output_paths": {
            "latest": str(paths["latest"]),
            "record": str(paths["record"]),
            "source_ledger": str(paths["source_ledger"]),
            "worker_brief_queue": str(paths["worker_brief_queue"]),
            "canonical_worker_brief_queue": str(paths["canonical_worker_brief_queue"]),
            "compat_worker_brief_queue": str(paths["compat_worker_brief_queue"]),
            "readback": str(paths["readback"]),
            "capability_manifest": str(paths["capability_manifest"]),
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    payload["validation"] = {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()}
    manifest = build_capability_manifest(payload)
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_json(paths["worker_brief_queue"], worker_brief_queue)
        write_json(paths["canonical_worker_brief_queue"], worker_brief_queue)
        write_json(paths["compat_worker_brief_queue"], worker_brief_queue)
        write_text(paths["readback"], render_readback(payload))
        write_json(paths["capability_manifest"], manifest)
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    lines = [
        "# Current Task Source Intake",
        "",
        SENTINEL,
        "",
        "## 结论",
        "",
        f"- status: `{payload.get('status')}`",
        f"- source_package_id: `{payload.get('source_package_id')}`",
        f"- source_entry_count: `{payload.get('source_entry_count')}`",
        f"- worker_brief_count: `{payload.get('worker_brief_queue', {}).get('brief_count')}`",
        f"- contract_id: `{payload.get('task_contract_router', {}).get('contract_id')}`",
        f"- workflow_run_id: `{payload.get('current_workflow', {}).get('workflow_run_id')}`",
        "",
        "## 现在能 invoke 什么",
        "",
        "- 当前三文本已经是 SourceLedger entry，不再只是 continuity_router 读过。",
        "- `worker_brief_queue/latest.json` 已生成，下一步可以被 ProviderScheduler/Temporal worker 消费。",
        "- 这一步仍不是 P0 完成，worker 真实回执要等 p0_008。",
        "",
        "## 下一机器动作",
        "",
    ]
    for item in payload.get("next_machine_actions", []):
        lines.append(f"- {item.get('order')}. `{item.get('task_id')}`: {item.get('action')}")
    lines.extend(
        [
            "",
            "## 输出",
            "",
            f"- source_ledger: `{payload.get('output_paths', {}).get('source_ledger')}`",
            f"- worker_brief_queue: `{payload.get('output_paths', {}).get('canonical_worker_brief_queue')}`",
            f"- latest: `{payload.get('output_paths', {}).get('latest')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="current-task-source-intake")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-package-root", default=str(DEFAULT_TASK_PACKAGE_ROOT))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build_current_task_source_intake(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_package_root=args.task_package_root,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "source_entry_count": payload["source_entry_count"],
                "worker_brief_count": payload["worker_brief_queue"]["brief_count"],
                "validation": payload["validation"],
                "latest": payload["output_paths"]["latest"],
                "source_ledger": payload["output_paths"]["source_ledger"],
                "worker_brief_queue": payload["output_paths"]["canonical_worker_brief_queue"],
                "readback": payload["output_paths"]["readback"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
