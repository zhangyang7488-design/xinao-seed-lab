from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.333_legacy_freeze_manifest.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_333_LEGACY_FREEZE_MANIFEST_READY"
TASK_ID = "codex_333_legacy_freeze_manifest_20260706"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TOOL_PROVIDER_ID = "codex_s.333_legacy_freeze_manifest"
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
    state = runtime / "state" / "codex_333_legacy_freeze_manifest"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "readback": runtime / "readback" / "zh" / "codex_333_legacy_freeze_manifest.md",
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
    records = []
    combined = ""
    for path in files:
        text = file_text(path)
        combined += "\n" + text
        records.append(
            {
                "path": str(path),
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else 0,
                "line_count": len(text.splitlines()) if text else 0,
                "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
                if text
                else "",
                "mentions_legacy_freeze_manifest": "legacy_freeze_manifest" in text,
                "mentions_reference_only_guard": "legacy_reference_only_runtime_guard" in text,
                "mentions_current_task_owner": "current_task_owner" in text,
                "mentions_clean_runtime": r"D:\XINAO_CLEAN_RUNTIME" in text,
            }
        )
    return {
        "source_root": str(files[0].parent if files else DEFAULT_SOURCE_ROOT),
        "file_count": len(records),
        "all_files_exist": all(item["exists"] for item in records),
        "all_files_read_full": all(item["exists"] and item["line_count"] > 0 for item in records),
        "total_bytes": sum(int(item["bytes"] or 0) for item in records),
        "legacy_freeze_manifest_mentions": combined.count("legacy_freeze_manifest"),
        "legacy_reference_only_guard_mentions": combined.count("legacy_reference_only_runtime_guard"),
        "current_task_owner_mentions": combined.count("current_task_owner"),
        "clean_runtime_mentions": combined.count(r"D:\XINAO_CLEAN_RUNTIME"),
        "files": records,
    }


def boundary_refs(repo: Path, runtime: Path) -> dict[str, Any]:
    agents = repo / "AGENTS.md"
    l0 = repo / "CODEX_S_L0.md"
    boundary = repo / "contracts" / "codex-s-workspace-boundary.v1.json"
    cli = repo / "src" / "xinao_seedlab" / "cli" / "__main__.py"
    legacy_managed_freeze = runtime / "state" / "legacy_managed_hook_freeze" / "latest.json"
    registry = runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json"
    continuity = runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json"
    agents_text = file_text(agents)
    l0_text = file_text(l0)
    boundary_text = file_text(boundary)
    cli_text = file_text(cli)
    registry_payload = read_json(registry)
    provider_ids = registry_payload.get("provider_ids")
    provider_ids = provider_ids if isinstance(provider_ids, list) else []
    freeze_payload = read_json(legacy_managed_freeze)
    return {
        "agents_md": {
            "path": str(agents),
            "exists": agents.is_file(),
            "sha256": file_sha256(agents),
            "declares_clean_runtime_reference_only": (
                r"D:\XINAO_CLEAN_RUNTIME" in agents_text
                and "legacy/reference-only" in agents_text
            ),
            "declares_old_current_task_owner_reference_only": "old `current_task_owner`" in agents_text,
        },
        "l0": {
            "path": str(l0),
            "exists": l0.is_file(),
            "sha256": file_sha256(l0),
            "declares_managed_hook_freeze": "legacy_managed_hook_freeze" in l0_text,
            "declares_old_current_task_owner_forbidden": (
                "Never use old B hooks" in l0_text
                and "old `current_task_owner`" in l0_text
            ),
            "declares_clean_runtime_not_source_of_truth": (
                r"D:\XINAO_CLEAN_RUNTIME" in l0_text
                and "source of truth" in l0_text
            ),
        },
        "workspace_boundary": {
            "path": str(boundary),
            "exists": boundary.is_file(),
            "sha256": file_sha256(boundary),
            "declares_legacy_freeze_state": "legacy_global_managed_hook_freeze" in boundary_text,
            "declares_old_current_task_owner_role": "old_current_task_owner_role" in boundary_text,
            "declares_reference_only_not_default": "reference_only_not_default" in boundary_text,
        },
        "legacy_managed_hook_freeze": {
            "path": str(legacy_managed_freeze),
            "exists": legacy_managed_freeze.is_file(),
            "status": freeze_payload.get("status", ""),
            "schema_version": freeze_payload.get("schema_version", ""),
            "sha256": file_sha256(legacy_managed_freeze),
        },
        "cli": {
            "path": str(cli),
            "exists": cli.is_file(),
            "registered": "333-legacy-freeze-manifest" in cli_text,
        },
        "tool_registry": {
            "path": str(registry),
            "exists": registry.is_file(),
            "status": registry_payload.get("status", ""),
            "provider_visible": TOOL_PROVIDER_ID in provider_ids,
            "provider_ids": provider_ids,
            "completion_claim_allowed": registry_payload.get("completion_claim_allowed"),
            "not_execution_controller": registry_payload.get("not_execution_controller"),
        },
        "continuity_router": {
            "path": str(continuity),
            "exists": continuity.is_file(),
            "next_required_artifact": read_json(continuity).get("next_required_artifact", ""),
        },
    }


def legacy_entries() -> list[dict[str, Any]]:
    replacements = {
        "mainline": "scripts/hardmode/Invoke-CodexSRootIntentLoopDriver.ps1 -> Temporal -> worker lanes -> fan-in/AAQ",
        "startup": "AGENTS.md -> CODEX_S_L0.md -> S-scoped UserPromptSubmit/Stop hooks",
        "registry": "D:\\XINAO_RESEARCH_RUNTIME\\agent_runtime\\tools\\registry\\tool_registry.json",
        "current_index": "D:\\XINAO_RESEARCH_RUNTIME\\state\\current_333_run_index\\latest.json",
    }
    return [
        {
            "entry_id": "legacy_clean_runtime_root",
            "surface": r"D:\XINAO_CLEAN_RUNTIME and D:\XINAO_CLEAN_RUNTIME\latest.json",
            "legacy_refs": [r"D:\XINAO_CLEAN_RUNTIME"],
            "allowed_use": "cold compatibility lookup, migration input, incident replay with explicit task scope",
            "forbidden_use": "S hot-path runtime root, source of truth, completion authority, owner authority",
            "replacement_entrypoint": r"D:\XINAO_RESEARCH_RUNTIME plus " + replacements["mainline"],
            "reference_only": True,
            "default_hot_path_authority_allowed": False,
            "completion_authority_allowed": False,
            "execution_controller_allowed": False,
        },
        {
            "entry_id": "legacy_current_task_owner_latest_alias",
            "surface": r"D:\XINAO_RESEARCH_RUNTIME\state\current_task_owner\latest.json ambient alias",
            "legacy_refs": ["old current_task_owner", "old 5d33 owner"],
            "allowed_use": "derived read model only when bound to the current Seed Cortex workflow/task",
            "forbidden_use": "ambient owner promotion, Stop/completion gate, latest.json progress proof",
            "replacement_entrypoint": replacements["current_index"],
            "reference_only": True,
            "requires_current_s_binding": True,
            "default_hot_path_authority_allowed": False,
            "completion_authority_allowed": False,
            "execution_controller_allowed": False,
        },
        {
            "entry_id": "old_completion_gates_and_worker_pass",
            "surface": "old completion gates, worker PASS, Grok segment gate, old projections",
            "legacy_refs": ["old completion gate", "old worker PASS", "old Grok segment gate"],
            "allowed_use": "historical audit or compatibility replay only",
            "forbidden_use": "user completion, artifact acceptance, stop permission, phase boundary",
            "replacement_entrypoint": "ArtifactAcceptanceQueue plus current S completion boundary",
            "reference_only": True,
            "default_hot_path_authority_allowed": False,
            "completion_authority_allowed": False,
            "execution_controller_allowed": False,
        },
        {
            "entry_id": "old_lifecycle_and_managed_hooks",
            "surface": "old A/B/C/CLEAN lifecycle hooks and old managed hook wrappers",
            "legacy_refs": [
                r"C:\ProgramData\OpenAI\Codex\managed-hooks\xinao_ucp_first_hook_guard.ps1",
                r"D:\XINAO_RESEARCH_RUNTIME\state\legacy_managed_hook_freeze\latest.json",
            ],
            "allowed_use": "freeze evidence, backup, explicit migration/incident replay",
            "forbidden_use": "default hook dispatch, broad hook install, S execution controller",
            "replacement_entrypoint": replacements["startup"],
            "reference_only": True,
            "default_hot_path_authority_allowed": False,
            "completion_authority_allowed": False,
            "execution_controller_allowed": False,
        },
        {
            "entry_id": "legacy_tool_broker_and_resource_registry",
            "surface": r"D:\XINAO_CLEAN_RUNTIME\TOOL_BROKER and RESOURCE_REGISTRY",
            "legacy_refs": ["legacy tool broker", "legacy resource registry"],
            "allowed_use": "capability mining into S ToolRegistry/CapabilityGateway",
            "forbidden_use": "direct S permission registry, root orchestrator, default tool source",
            "replacement_entrypoint": replacements["registry"],
            "reference_only": True,
            "default_hot_path_authority_allowed": False,
            "completion_authority_allowed": False,
            "execution_controller_allowed": False,
        },
        {
            "entry_id": "legacy_deepseek_dp_sidecar_global_entry",
            "surface": "legacy.deepseek_dp_sidecar as global sidecar entry",
            "legacy_refs": ["legacy.deepseek_dp_sidecar"],
            "allowed_use": "DP audit/contradiction worker lane through S ToolRegistry and fan-in/AAQ",
            "forbidden_use": "durable 333 mainline, completion boundary, default controller",
            "replacement_entrypoint": "codex_s.direct_worker_lane / provider worker pool inside RootIntentLoop wave",
            "reference_only": True,
            "provider_lane_allowed": True,
            "default_hot_path_authority_allowed": False,
            "completion_authority_allowed": False,
            "execution_controller_allowed": False,
        },
        {
            "entry_id": "legacy_physical_git_root_and_archive_repo",
            "surface": "legacy physical git root and archive mother repository",
            "legacy_refs": ["legacy_physical_git_root_path_ref", "archive_mother_repository_ref"],
            "allowed_use": "cold source reference and migration input",
            "forbidden_use": "canonical repo root, current diff target, default startup authority",
            "replacement_entrypoint": r"E:\XINAO_RESEARCH_WORKSPACES\S",
            "reference_only": True,
            "default_hot_path_authority_allowed": False,
            "completion_authority_allowed": False,
            "execution_controller_allowed": False,
        },
    ]


def reference_only_runtime_guard(entries: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "all_entries_reference_only": all(item.get("reference_only") is True for item in entries),
        "default_hot_path_authority_denied": all(
            item.get("default_hot_path_authority_allowed") is False for item in entries
        ),
        "completion_authority_denied": all(
            item.get("completion_authority_allowed") is False for item in entries
        ),
        "execution_controller_denied": all(
            item.get("execution_controller_allowed") is False for item in entries
        ),
        "current_task_owner_requires_current_s_binding": any(
            item.get("entry_id") == "legacy_current_task_owner_latest_alias"
            and item.get("requires_current_s_binding") is True
            for item in entries
        ),
        "dp_sidecar_stays_provider_lane": any(
            item.get("entry_id") == "legacy_deepseek_dp_sidecar_global_entry"
            and item.get("provider_lane_allowed") is True
            and item.get("execution_controller_allowed") is False
            for item in entries
        ),
    }
    return {
        "schema_version": "xinao.codex_s.333_legacy_reference_only_runtime_guard.v1",
        "status": "legacy_reference_only_runtime_guard_ready"
        if all(checks.values())
        else "legacy_reference_only_runtime_guard_blocked",
        "checks": checks,
        "clean_runtime_silent_fallback_allowed": False,
        "old_current_task_owner_ambient_promotion_allowed": False,
        "old_completion_gate_allowed": False,
        "legacy_dp_sidecar_mainline_allowed": False,
        "default_replacement": "RootIntentLoop / S Default Dynamic Loop",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def validation(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source_package") if isinstance(payload.get("source_package"), dict) else {}
    refs = payload.get("boundary_refs") if isinstance(payload.get("boundary_refs"), dict) else {}
    guard = payload.get("reference_only_runtime_guard")
    guard = guard if isinstance(guard, dict) else {}
    entries = payload.get("legacy_entries") if isinstance(payload.get("legacy_entries"), list) else []
    agents = refs.get("agents_md") if isinstance(refs.get("agents_md"), dict) else {}
    l0 = refs.get("l0") if isinstance(refs.get("l0"), dict) else {}
    boundary = refs.get("workspace_boundary") if isinstance(refs.get("workspace_boundary"), dict) else {}
    cli = refs.get("cli") if isinstance(refs.get("cli"), dict) else {}
    registry = refs.get("tool_registry") if isinstance(refs.get("tool_registry"), dict) else {}
    checks = {
        "source_files_read": source.get("all_files_read_full") is True,
        "source_mentions_legacy_freeze": int(source.get("legacy_freeze_manifest_mentions") or 0) > 0,
        "agents_declares_legacy_boundary": agents.get("declares_clean_runtime_reference_only") is True,
        "l0_declares_legacy_boundary": (
            l0.get("declares_old_current_task_owner_forbidden") is True
            and l0.get("declares_clean_runtime_not_source_of_truth") is True
        ),
        "workspace_contract_declares_legacy_boundary": (
            boundary.get("declares_legacy_freeze_state") is True
            and boundary.get("declares_old_current_task_owner_role") is True
            and boundary.get("declares_reference_only_not_default") is True
        ),
        "manifest_entries_present": len(entries) >= 6,
        "all_entries_reference_only": all(item.get("reference_only") is True for item in entries),
        "all_entries_have_replacements": all(
            bool(str(item.get("replacement_entrypoint") or "").strip()) for item in entries
        ),
        "guard_ready": guard.get("status") == "legacy_reference_only_runtime_guard_ready",
        "cli_entrypoint_registered": cli.get("registered") is True,
        "tool_registry_provider_visible": registry.get("provider_visible") is True,
        "tool_registry_not_execution_controller": registry.get("not_execution_controller") is True,
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
    entries = legacy_entries()
    guard = reference_only_runtime_guard(entries)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "repo_root": str(repo),
        "runtime_root": str(runtime),
        "source_package": source_package(files),
        "boundary_refs": boundary_refs(repo, runtime),
        "legacy_entries": entries,
        "reference_only_runtime_guard": guard,
        "accepted_for": [
            "P0.legacy_freeze_manifest",
            "P0.legacy_reference_only_runtime_guard",
        ],
        "adoption_state": "default_hot_path_ready",
        "default_mainline_hardened": True,
        "workspace_only": False,
        "default_consumer": (
            "S ToolRegistry / default trigger no-stop ToolRegistry consumption / "
            "stateful continuity router / startup boundary read model"
        ),
        "not_user_completion": True,
        "completion_claim_allowed": False,
        "not_completion_gate": True,
        "not_execution_controller": True,
        "output_paths": {key: str(value) for key, value in paths.items()},
        "generated_at": now_iso(),
    }
    payload["validation"] = validation(payload)
    payload["status"] = (
        "legacy_freeze_manifest_ready"
        if payload["validation"]["passed"] is True
        else "legacy_freeze_manifest_blocked"
    )
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    validation_payload = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    entries = payload.get("legacy_entries") if isinstance(payload.get("legacy_entries"), list) else []
    return "\n".join(
        [
            "# 333 legacy freeze manifest",
            "",
            SENTINEL,
            "",
            f"- status: `{payload.get('status')}`",
            f"- legacy_entry_count: {len(entries)}",
            f"- accepted_for: `{', '.join(payload.get('accepted_for', []))}`",
            f"- default_consumer: `{payload.get('default_consumer')}`",
            f"- validation_passed: {validation_payload.get('passed')}",
            "- boundary: old CLEAN/A/B/C/current_task_owner/completion gates are reference-only; RootIntentLoop remains the default mainline.",
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
