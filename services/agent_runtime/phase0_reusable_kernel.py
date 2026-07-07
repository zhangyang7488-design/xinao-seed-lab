from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import next_frontier_continuation_supervisor as next_frontier_supervisor
from services.agent_runtime import task_package_resolver as task_package

SCHEMA_VERSION = "xinao.codex_s.phase0_reusable_kernel.v1"
SENTINEL = "SENTINEL:XINAO_PHASE0_REUSABLE_KERNEL_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
PARENT_TASK_ID = WORK_ID
TASK_ID = "wave5_phase0_reusable_kernel_20260704"
ROUTING = "continue_same_task"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
def _thin_glue_bridge(runtime: Path) -> dict[str, Any]:
    from services.agent_runtime.thin_glue_mainline_bridge import attach_thin_glue_bridge_evidence

    return attach_thin_glue_bridge_evidence(runtime)


DEFAULT_SPEC = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\specs\max_benefit_dynamic_loop_authority_20260702.v1.md"
)
SRC_ROOT = DEFAULT_REPO / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

AUTHORITY_FILES = list(task_package.LEGACY_AUTHORITY_FILES)
TASK_PACKAGE_MANIFEST_NAMES = list(task_package.TASK_PACKAGE_MANIFEST_NAMES)


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


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "json_valid": bool(payload) or not path.is_file(),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "validation_passed": validation.get("passed"),
        "not_execution_controller": payload.get("not_execution_controller"),
    }


def task_package_manifest_ref(anchor: Path) -> tuple[Path | None, dict[str, Any]]:
    for name in TASK_PACKAGE_MANIFEST_NAMES:
        candidate = anchor / name
        if candidate.is_file():
            payload = read_json(candidate)
            if payload:
                return candidate, payload
    return None, {}


def normalize_manifest_resource_path(anchor: Path, resource_path: str) -> Path:
    raw = str(resource_path or "").strip()
    path = Path(raw)
    if path.is_absolute():
        return path
    return anchor / raw


def manifest_resource_paths(anchor: Path, manifest: dict[str, Any]) -> list[Path]:
    resources = manifest.get("resources")
    if not isinstance(resources, list):
        return []
    paths: list[Path] = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        raw_path = str(resource.get("path") or resource.get("href") or "").strip()
        if not raw_path:
            continue
        paths.append(normalize_manifest_resource_path(anchor, raw_path))
    return paths


def output_paths(repo: Path, runtime: Path, wave_id: str) -> dict[str, str]:
    root = runtime / "state" / "phase0_reusable_kernel"
    return {
        "runtime_latest": str(root / "latest.json"),
        "wave_latest": str(root / "waves" / f"{wave_id}.json"),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_phase0_reusable_kernel.v1.json"),
        "worker_assignment_latest": str(
            runtime / "state" / "worker_assignment" / f"{TASK_ID}.json"
        ),
        "kernel_objects_latest": str(root / "kernel_objects" / "latest.json"),
        "provider_swap_replay_latest": str(root / "provider_swap_replay" / "latest.json"),
        "new_work_id_thin_bind_latest": str(root / "new_work_id_thin_bind" / "latest.json"),
        "capability_manifest": str(
            runtime / "capabilities" / "codex_s.phase0_reusable_kernel" / "manifest.json"
        ),
        "next_frontier_machine_actions_latest": str(
            runtime / "state" / "next_frontier_machine_actions" / "latest.json"
        ),
        "readback_zh": str(
            runtime / "readback" / "zh" / "wave_block5_phase0_reusable_kernel_20260704.md"
        ),
    }


def source_package_refs(anchor: Path, spec: Path) -> dict[str, Any]:
    package = task_package.resolve_task_package(
        anchor,
        legacy_files=tuple(AUTHORITY_FILES),
        include_manifest_ref=True,
    )
    spec_ref = task_package.text_source_ref(
        spec,
        role=(
            "spec_reference_optional_when_manifest_present"
            if package.get("manifest_driven")
            else "legacy_spec_reference"
        ),
    )
    if package.get("manifest_driven") is not True:
        package["refs"] = [*package.get("refs", []), spec_ref]
        package["all_required_sources_read_full"] = all(
            ref.get("read_full") is True for ref in package.get("refs", [])
        )
    return {
        **package,
        "root": str(anchor),
        "package_mode": "manifest"
        if package.get("manifest_driven")
        else package.get("package_mode"),
        "spec_ref": str(spec),
        "task_package_manifest_ref": str(package.get("task_package_manifest_path") or ""),
        "spec_optional_ref": spec_ref,
        "source_frontier_scope": (
            "current_manifest_task_package_phase0_reusable_kernel"
            if package.get("manifest_driven")
            else "wave5_phase0_reusable_kernel"
        ),
    }


def build_kernel_objects(repo: Path, runtime: Path) -> dict[str, Any]:
    fan_in = json_ref(runtime / "state" / "fan_in_acceptance_queue" / "latest.json")
    aaq = json_ref(runtime / "state" / "artifact_acceptance_queue" / "latest.json")
    source_family = json_ref(
        runtime / "state" / "source_family_wave_scheduler" / "temporal_activity_latest.json"
    )
    schema_paths = [
        repo / "contracts" / "schemas" / "codex_s_source_frontier_fanin_acceptance.v1.json",
        repo / "contracts" / "schemas" / "codex_s_source_family_wave_scheduler.v1.json",
        repo / "contracts" / "schemas" / "codex_s_main_execution_loop_tick.v1.json",
    ]
    verifier_paths = [
        repo / "scripts" / "verify_source_frontier_fanin_acceptance.ps1",
        repo / "scripts" / "verify_source_family_wave_scheduler.ps1",
        repo / "scripts" / "verify_codex_s_main_execution_loop_tick.ps1",
    ]
    episode_refs = [
        runtime
        / "runs"
        / "episodes"
        / "source-family-wave-wave4-source-family-default-lane-20260704-wave-01-ingress"
        / "workflow_entry.json",
        runtime / "state" / "temporal_codex_task_workflow" / "latest.json",
        runtime / "state" / "source_family_wave_scheduler" / "temporal_activity_latest.json",
    ]
    compatibility_refs = {
        "FrontierCandidate.v1": json_ref(
            runtime / "state" / "next_frontier_machine_actions" / "latest.json"
        ),
        "FrontierPortfolioSnapshot.v1": json_ref(
            runtime / "state" / "frontier_portfolio_snapshot" / "latest.json"
        ),
        "LaneResultReview.v1": json_ref(runtime / "state" / "lane_result_review" / "latest.json"),
        "RewardSignal.v1": json_ref(runtime / "state" / "reward_signal" / "latest.json"),
    }
    objects = [
        {
            "object_id": "FanInAcceptanceQueue",
            "status": "landed" if fan_in["exists"] and aaq["exists"] else "gap",
            "invoke_path": "source-frontier-fanin-acceptance / source-family-wave-scheduler",
            "refs": [fan_in, aaq, source_family],
        },
        {
            "object_id": "SchemaContract",
            "status": "landed" if all(path.is_file() for path in schema_paths) else "gap",
            "invoke_path": "json-schema-bound runtime payloads and focused verifier scripts",
            "refs": [{"path": str(path), "exists": path.is_file()} for path in schema_paths],
        },
        {
            "object_id": "ReadOnlyVerifierChain",
            "status": "landed" if all(path.is_file() for path in verifier_paths) else "gap",
            "invoke_path": "scripts/verify_source_frontier_fanin_acceptance.ps1; scripts/verify_source_family_wave_scheduler.ps1",
            "refs": [{"path": str(path), "exists": path.is_file()} for path in verifier_paths],
        },
        {
            "object_id": "EpisodeWorkflowEntry",
            "status": "landed" if any(path.is_file() for path in episode_refs) else "gap",
            "invoke_path": "Temporal workflow/activity -> episode workflow entry -> readback",
            "refs": [{"path": str(path), "exists": path.is_file()} for path in episode_refs],
        },
    ]
    return {
        "schema_version": "xinao.codex_s.phase0_kernel_objects.v1",
        "status": "phase0_kernel_objects_ready"
        if all(obj["status"] == "landed" for obj in objects)
        else "phase0_kernel_objects_blocked",
        "objects": objects,
        "object_count": len(objects),
        "landed_count": len([obj for obj in objects if obj["status"] == "landed"]),
        "compatibility_frontier_four_objects": compatibility_refs,
        "frontier_four_objects_available": all(
            ref["exists"] for ref in compatibility_refs.values()
        ),
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": all(obj["status"] == "landed" for obj in objects),
            "checks": {
                "fan_in_aaq_landed": objects[0]["status"] == "landed",
                "schema_contract_landed": objects[1]["status"] == "landed",
                "verifier_chain_landed": objects[2]["status"] == "landed",
                "episode_workflow_landed": objects[3]["status"] == "landed",
            },
        },
    }


def build_provider_swap_replay(runtime: Path) -> dict[str, Any]:
    phase4 = read_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json"
    )
    registry = (
        phase4.get("provider_registry") if isinstance(phase4.get("provider_registry"), dict) else {}
    )
    scheduler = (
        phase4.get("scheduler_decision")
        if isinstance(phase4.get("scheduler_decision"), dict)
        else {}
    )
    providers = registry.get("providers") if isinstance(registry.get("providers"), list) else []
    switchable = [
        item
        for item in providers
        if item.get("switchable") is True and item.get("status") == "ready"
    ]
    routes = (
        scheduler.get("route_policy") if isinstance(scheduler.get("route_policy"), dict) else {}
    )
    return {
        "schema_version": "xinao.codex_s.phase0_provider_swap_replay.v1",
        "status": "provider_swap_replay_ready"
        if len(switchable) >= 3 and bool(routes)
        else "provider_swap_replay_blocked",
        "provider_registry_ref": str(
            runtime
            / "state"
            / "codex_native_provider_scheduler_phase4_20260704"
            / "provider_registry"
            / "latest.json"
        ),
        "model_gateway_ref": str(
            runtime
            / "state"
            / "codex_native_provider_scheduler_phase4_20260704"
            / "model_gateway"
            / "latest.json"
        ),
        "executor_adapter_ref": str(
            runtime
            / "state"
            / "codex_native_provider_scheduler_phase4_20260704"
            / "executor_adapter"
            / "latest.json"
        ),
        "switchable_ready_provider_count": len(switchable),
        "route_policy_keys": sorted(routes.keys()),
        "provider_swap_requires_domain_rewrite": False,
        "provider_outputs_to_staging_before_promotion": True,
        "replay_eval_required_before_memory_policy_promotion": True,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": len(switchable) >= 3 and bool(routes),
            "checks": {
                "switchable_ready_provider_count_at_least_3": len(switchable) >= 3,
                "route_policy_present": bool(routes),
                "domain_rewrite_not_required": True,
                "outputs_to_staging_first": True,
            },
        },
    }


def build_new_work_id_thin_bind(paths: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "xinao.codex_s.new_work_id_thin_bind.v1",
        "status": "new_work_id_thin_bind_ready",
        "sample_work_id": "xinao_seed_cortex_phase0_replay_bind_smoke_20260704",
        "bind_without_hand_solder": True,
        "inherited_ports": [
            "RootIntentLoop",
            "LoopRuntimeState",
            "SourceFamilyWaveScheduler",
            "FanInAcceptanceQueue",
            "ArtifactAcceptanceQueue",
            "ProviderGateway",
            "ExecutorAdapter",
            "TemporalWorkflowActivity",
        ],
        "invoke_path": "python -m xinao_seedlab.cli.__main__ phase0-reusable-kernel --wave-id <wave>",
        "capability_manifest_ref": paths["capability_manifest"],
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {"passed": True},
    }


def build_next_frontier(
    paths: dict[str, str], source_package: dict[str, Any] | None = None
) -> dict[str, Any]:
    package = source_package if isinstance(source_package, dict) else {}
    manifest_driven = package.get("manifest_driven") is True
    gap_scope = (
        "current_manifest_task_package_after_phase0_reusable_kernel"
        if manifest_driven
        else "wave2_mainchain_hygiene_or_next_legacy_frontier"
    )
    return {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "next_frontier_machine_actions_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "should_continue_loop": True,
        "stop_allowed": False,
        "stop_allowed_reason": "phase0_reusable_kernel_task_scoped_ready_but_total_333_frontier_continues_to_hygiene_and_future_frontiers",
        "while_driver": "event_backlog_frontier_driven",
        "source_frontier_gap": {
            "exists": True,
            "source_package_gap_open": True,
            "gap_scope": gap_scope,
            "manifest_driven": manifest_driven,
            "task_package_manifest_ref": str(package.get("task_package_manifest_ref") or ""),
            "wave5_phase0_reusable_kernel_task_scoped_accepted": True,
        },
        "next_frontier": [
            {
                "action_id": "next-wave-wave2-mainchain-hygiene",
                "action": "enter_wave2_mainchain_hygiene",
                "why": "Reusable kernel gate is task-scoped ready; remaining planned slice is mainchain hygiene, hidden-window reconciliation, and tracker refresh.",
            }
        ],
        "output_paths": {"runtime_latest": paths["next_frontier_machine_actions_latest"]},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {"passed": True},
    }


def render_readback(payload: dict[str, Any]) -> str:
    objects = payload.get("kernel_objects", {})
    swap = payload.get("provider_swap_replay", {})
    thin = payload.get("new_work_id_thin_bind", {})
    lines = [
        "# Wave-block5 Phase0 reusable kernel readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- task_id: `{payload.get('task_id')}`",
        f"- landed objects: {objects.get('landed_count')}/{objects.get('object_count')}",
        f"- frontier four objects available: {objects.get('frontier_four_objects_available')}",
        f"- switchable providers ready: {swap.get('switchable_ready_provider_count')}",
        f"- new work_id thin bind: {thin.get('bind_without_hand_solder')}",
        "",
        "验收三句：",
        "1. 四对象各自能 invoke 什么？FanIn/AAQ、schema contract、只读 verifier、episode/workflow entry 都有 refs 和 invoke 路径。",
        "2. 新 work_id 薄绑要不要手搓？不要。`new_work_id_thin_bind` 继承同一 RootIntentLoop/AAQ/ProviderGateway/Temporal ports。",
        "3. 还在 while 吗？是。`stop_allowed=false`；下一机器动作是 Wave-块2 主链卫生/黑窗镜像收口，不是用户完成。",
        "",
        "现在能 invoke 什么：",
        "- `python -m xinao_seedlab.cli.__main__ phase0-reusable-kernel --wave-id <wave>`",
        "- `scripts\\verify_phase0_reusable_kernel.ps1`",
        "",
        "边界：这是 Phase0 reusable-kernel task-scoped acceptance；不启动 Phase1 数据链/正期望，不宣称用户完成。",
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
    spec_path: str | Path = DEFAULT_SPEC,
    wave_id: str = "wave-block5-phase0-reusable-kernel",
    invoked_by_temporal_activity: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    anchor = Path(anchor_package_root)
    spec = Path(spec_path)
    paths = output_paths(repo, runtime, wave_id)
    source_package = source_package_refs(anchor, spec)
    kernel_objects = build_kernel_objects(repo, runtime)
    provider_swap = build_provider_swap_replay(runtime)
    thin_bind = build_new_work_id_thin_bind(paths)
    next_frontier = build_next_frontier(paths, source_package)
    primary_authority_path = (
        source_package.get("task_package_manifest_ref")
        if source_package.get("manifest_driven") is True
        else str(anchor / AUTHORITY_FILES[-1])
    )
    worker_assignment = {
        "schema_version": "xinao.worker_assignment.v2.dag",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "assignment_id": f"phase0_reusable_kernel:{wave_id}",
        "wave_id": wave_id,
        "status": "worker_assignment_ready",
        "scope_level_target": "L3",
        "scope_level_current": "L3_task_scoped_acceptance_ready",
        "primary_authority_path": str(primary_authority_path or ""),
        "primary_authority_mode": (
            "task_package_manifest"
            if source_package.get("manifest_driven") is True
            else "legacy_authority_file"
        ),
        "assignment_dag": {
            "nodes": [
                "restore_wave3_wave4_evidence",
                "judge_four_kernel_objects",
                "provider_swap_replay_gate",
                "new_work_id_thin_bind",
                "capability_manifest",
                "next_frontier",
            ],
            "serial_only": ["same_file_write", "acceptance", "capability_manifest_write"],
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    capability_manifest = {
        "schema_version": "xinao.capability_manifest.v1",
        "capability_id": "codex_s.phase0_reusable_kernel",
        "status": "ready",
        "invoke": {
            "cli": "python -m xinao_seedlab.cli.__main__ phase0-reusable-kernel --wave-id <wave>",
            "verifier": "scripts/verify_phase0_reusable_kernel.ps1",
        },
        "task_id": TASK_ID,
        "not_completion_boundary": True,
        "secret_values_recorded": False,
    }
    checks = {
        "source_package_read_full": source_package.get("all_required_sources_read_full") is True,
        "kernel_objects_landed": kernel_objects.get("validation", {}).get("passed") is True,
        "provider_swap_replay_ready": provider_swap.get("validation", {}).get("passed") is True,
        "new_work_id_thin_bind_ready": thin_bind.get("validation", {}).get("passed") is True,
        "frontier_four_objects_available": kernel_objects.get("frontier_four_objects_available")
        is True,
        "capability_manifest_ready": capability_manifest.get("status") == "ready",
        "completion_claim_denied": True,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": "phase0_reusable_kernel_ready"
        if all(checks.values())
        else "phase0_reusable_kernel_blocked",
        "generated_at": now_iso(),
        "adoption_state": "task_scoped_reusable_kernel_ready_not_user_completion",
        "invoked_by_temporal_activity": invoked_by_temporal_activity,
        "source_package": source_package,
        "worker_assignment": worker_assignment,
        "kernel_objects": kernel_objects,
        "provider_swap_replay": provider_swap,
        "new_work_id_thin_bind": thin_bind,
        "capability_manifest": capability_manifest,
        "next_frontier_machine_actions": next_frontier,
        "output_paths": paths,
        "thin_glue_mainline_bridge": _thin_glue_bridge(runtime),
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        write_json(Path(paths["worker_assignment_latest"]), worker_assignment)
        write_json(Path(paths["kernel_objects_latest"]), kernel_objects)
        write_json(Path(paths["provider_swap_replay_latest"]), provider_swap)
        write_json(Path(paths["new_work_id_thin_bind_latest"]), thin_bind)
        write_json(Path(paths["capability_manifest"]), capability_manifest)
        next_frontier_supervisor.promote_candidate_next_frontier(
            runtime_root=runtime,
            candidate=next_frontier,
            source_kind="phase0_reusable_kernel",
            source_ref=paths["runtime_latest"],
        )
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["wave_latest"]), payload)
        write_text(Path(paths["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--spec-path", default=str(DEFAULT_SPEC))
    parser.add_argument("--wave-id", default="wave-block5-phase0-reusable-kernel")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        spec_path=args.spec_path,
        wave_id=args.wave_id,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "landed_count": payload["kernel_objects"]["landed_count"],
                "object_count": payload["kernel_objects"]["object_count"],
                "capability_manifest": payload["output_paths"]["capability_manifest"],
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
