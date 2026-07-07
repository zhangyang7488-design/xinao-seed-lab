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


SCHEMA_VERSION = "xinao.codex_s.source_family_smoked_candidate_thin_bind.v1"
SENTINEL = "SENTINEL:XINAO_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
PARENT_TASK_ID = WORK_ID
TASK_ID = "wave7_source_family_smoked_candidate_thin_bind_20260704"
ROUTING = "continue_same_task"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
IMPLEMENT_ACTION = "implement_thin_bind_adapter_for_smoked_candidates"
NEXT_ACTION = "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway"

SRC_ROOT = DEFAULT_REPO / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xinao_seedlab.adapters.source_candidate import SourceCandidateAdapter
from services.agent_runtime.source_family_adapter_smoke import (
    first_next_action,
    json_ref,
    path_digest,
    read_json,
    safe_id,
    write_json,
    write_text,
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def output_paths(repo: Path, runtime: Path, wave_id: str) -> dict[str, str]:
    root = runtime / "state" / "source_family_smoked_candidate_thin_bind"
    return {
        "runtime_latest": str(root / "latest.json"),
        "wave_latest": str(root / "waves" / f"{wave_id}.json"),
        "bindings_latest": str(root / "bindings" / "latest.json"),
        "bindings_wave": str(root / "bindings" / f"{wave_id}.json"),
        "binding_dir": str(root / "bindings" / wave_id),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_source_family_smoked_candidate_thin_bind.v1.json"),
        "adapter_smoke_latest": str(runtime / "state" / "source_family_adapter_smoke" / "latest.json"),
        "adapter_smoke_candidate_results_latest": str(runtime / "state" / "source_family_adapter_smoke" / "candidate_results" / "latest.json"),
        "previous_next_frontier_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "next_frontier_machine_actions_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "artifact_acceptance_queue_latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "source_ledger_latest": str(runtime / "state" / "source_ledger" / "latest.json"),
        "manifest": str(runtime / "capabilities" / "codex_s.source_family_smoked_candidate_thin_bind" / "manifest.json"),
        "readback_zh": str(runtime / "readback" / "zh" / "source_family_smoked_candidate_thin_bind_20260704.md"),
    }


def build_manifest(paths: dict[str, str], validation_passed: bool) -> dict[str, Any]:
    return {
        "schema_version": "xinao.capability_manifest.v1",
        "capability_id": "codex_s.source_family_smoked_candidate_thin_bind",
        "status": "ready" if validation_passed else "blocked",
        "invoke": {
            "cli": "python -m xinao_seedlab.cli.__main__ source-family-smoked-candidate-thin-bind --wave-id <wave>",
            "input_action": IMPLEMENT_ACTION,
        },
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "consumes": [
            paths["adapter_smoke_latest"],
            paths["adapter_smoke_candidate_results_latest"],
            paths["previous_next_frontier_latest"],
        ],
        "writes": [
            paths["runtime_latest"],
            paths["bindings_latest"],
            paths["next_frontier_machine_actions_latest"],
        ],
        "not_completion_boundary": True,
        "secret_values_recorded": False,
    }


def build_next_frontier(
    *,
    wave_id: str,
    parent_wave_id: str,
    paths: dict[str, str],
    validation_passed: bool,
) -> dict[str, Any]:
    if validation_passed:
        next_items = [
            {
                "action_id": "next-wave-evaluate-smoked-adapter-bindings",
                "action": NEXT_ACTION,
                "why": "Thin bindings exist for smoked source-family candidates; evaluate value before any default capability promotion.",
                "requires": [
                    paths["bindings_latest"],
                    "adapter value evaluation",
                    "AAQ",
                    "SourceLedger",
                ],
            },
            {
                "action_id": "next-wave-default-temporal-chain-poll",
                "action": "keep_default_temporal_chain_polling",
                "why": "Thin binding is not completion; foreground/background polling continues.",
                "requires": ["Temporal task queue poller", "worker dispatch ledger"],
            },
        ]
    else:
        next_items = [
            {
                "action_id": "repair-smoked-candidate-thin-bind",
                "action": "repair_smoked_candidate_thin_bind_inputs",
                "why": "Thin binding cannot proceed until adapter-smoke results are validation-positive.",
                "requires": [paths["adapter_smoke_candidate_results_latest"]],
            }
        ]
    return {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "smoked_candidate_thin_bind_next_frontier_ready" if validation_passed else "smoked_candidate_thin_bind_repair_required",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "should_continue_loop": True,
        "stop_allowed": False,
        "stop_allowed_reason": "thin_bindings_need_value_eval_before_default_capability_promotion",
        "thin_bind": {
            "consumed_action": IMPLEMENT_ACTION,
            "bindings_ref": paths["bindings_latest"],
        },
        "next_frontier": next_items,
        "output_paths": {"runtime_latest": paths["next_frontier_machine_actions_latest"]},
        "validation": {
            "passed": validation_passed,
            "checks": {
                "thin_bind_action_consumed": validation_passed,
                "bindings_ref_written": bool(paths["bindings_latest"]),
                "stop_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def render_readback(payload: dict[str, Any]) -> str:
    lines = [
        "# Source-family smoked candidate thin-bind readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- wave_id: `{payload.get('wave_id')}`",
        f"- parent_wave_id: `{payload.get('parent_wave_id')}`",
        f"- consumed action: `{payload.get('consumed_next_frontier_action')}`",
        f"- bindings ready: {payload.get('ready_binding_count')} / {payload.get('binding_count')}",
        f"- bindings: `{payload.get('output_paths', {}).get('bindings_latest')}`",
        f"- next_frontier: `{payload.get('output_paths', {}).get('next_frontier_machine_actions_latest')}`",
        "",
        "验收三句：",
        "1. 本动作消费的是 adapter-smoke 后的 `implement_thin_bind_adapter_for_smoked_candidates`。",
        "2. thin bind 只把 smoke-positive candidates 绑定到 repo-native SourceCandidateAdapter，不直接提升默认能力。",
        "3. 下一步仍要做 adapter value eval / AAQ / SourceLedger，不允许停成完成。",
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
    wave_id: str = "wave-block7-source-family-smoked-candidate-thin-bind",
    write: bool = True,
) -> dict[str, Any]:
    del anchor_package_root
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(repo, runtime, wave_id)
    adapter_smoke = read_json(Path(paths["adapter_smoke_latest"]))
    candidate_results_payload = read_json(Path(paths["adapter_smoke_candidate_results_latest"]))
    previous_next_frontier = read_json(Path(paths["previous_next_frontier_latest"]))
    aaq = read_json(Path(paths["artifact_acceptance_queue_latest"]))
    source_ledger = read_json(Path(paths["source_ledger_latest"]))
    results = (
        candidate_results_payload.get("results")
        if isinstance(candidate_results_payload.get("results"), list)
        else []
    )
    bindings = [
        SourceCandidateAdapter.bind_smoked_candidate(result if isinstance(result, dict) else {})
        for result in results
    ]
    ready_binding_count = sum(1 for item in bindings if item.get("validation", {}).get("passed") is True)
    previous_action = first_next_action(previous_next_frontier)
    already_consumed = previous_action == NEXT_ACTION and previous_next_frontier.get("stop_allowed") is False
    consumed_action = IMPLEMENT_ACTION if already_consumed else previous_action
    parent_wave_id = str(
        previous_next_frontier.get("parent_wave_id")
        if already_consumed
        else previous_next_frontier.get("wave_id")
        or adapter_smoke.get("wave_id")
        or candidate_results_payload.get("wave_id")
        or ""
    )
    checks = {
        "adapter_smoke_validation_passed": adapter_smoke.get("validation", {}).get("passed") is True
        if isinstance(adapter_smoke.get("validation"), dict)
        else False,
        "candidate_results_validation_passed": candidate_results_payload.get("validation", {}).get("passed") is True
        if isinstance(candidate_results_payload.get("validation"), dict)
        else False,
        "candidate_results_nonempty": len(results) > 0,
        "previous_next_action_implement_or_idempotent": previous_action == IMPLEMENT_ACTION or already_consumed,
        "all_bindings_ready": bool(bindings) and ready_binding_count == len(bindings),
        "no_binding_promotes_default_capability": all(
            item.get("binding", {}).get("promotion_allowed") is False
            for item in bindings
            if isinstance(item.get("binding"), dict)
        ),
        "aaq_and_source_ledger_present": bool(aaq) and bool(source_ledger),
        "completion_claim_denied": True,
    }
    validation_passed = all(checks.values())
    bindings_payload = {
        "schema_version": f"{SCHEMA_VERSION}.bindings.v1",
        "status": "smoked_candidate_thin_bindings_ready" if validation_passed else "smoked_candidate_thin_bindings_blocked",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "binding_count": len(bindings),
        "ready_binding_count": ready_binding_count,
        "bindings": bindings,
        "validation": {"passed": validation_passed, "checks": checks},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    repair_plan = {
        "schema_version": "xinao.codex_s.source_family_smoked_candidate_thin_bind_repair_plan.v1",
        "status": "repair_not_required" if validation_passed else "repair_required",
        "named_blocker": "" if validation_passed else "SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND_INPUT_NOT_READY",
        "missing_checks": [name for name, passed in checks.items() if not passed],
        "return_to_main_route": True,
        "not_user_completion": True,
        "not_execution_controller": True,
    }
    manifest = build_manifest(paths, validation_passed)
    next_frontier = build_next_frontier(
        wave_id=wave_id,
        parent_wave_id=parent_wave_id,
        paths=paths,
        validation_passed=validation_passed,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "status": "source_family_smoked_candidate_thin_bind_ready" if validation_passed else "source_family_smoked_candidate_thin_bind_blocked",
        "generated_at": now_iso(),
        "consumed_next_frontier_action": consumed_action,
        "binding_count": len(bindings),
        "ready_binding_count": ready_binding_count,
        "input_refs": {
            "adapter_smoke_latest": json_ref(Path(paths["adapter_smoke_latest"])),
            "adapter_smoke_candidate_results_latest": json_ref(Path(paths["adapter_smoke_candidate_results_latest"])),
            "previous_next_frontier_latest": json_ref(Path(paths["previous_next_frontier_latest"])),
            "artifact_acceptance_queue_latest": json_ref(Path(paths["artifact_acceptance_queue_latest"])),
            "source_ledger_latest": json_ref(Path(paths["source_ledger_latest"])),
        },
        "bindings": bindings_payload,
        "capability_manifest": manifest,
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
        binding_dir = Path(paths["binding_dir"])
        for index, item in enumerate(bindings, start=1):
            binding_id = item.get("binding", {}).get("binding_id") if isinstance(item.get("binding"), dict) else f"binding-{index:02d}"
            write_json(binding_dir / f"{index:02d}-{safe_id(binding_id)}.json", item)
        write_json(Path(paths["bindings_latest"]), bindings_payload)
        write_json(Path(paths["bindings_wave"]), bindings_payload)
        write_json(Path(paths["manifest"]), manifest)
        next_frontier_supervisor.promote_candidate_next_frontier(
            runtime_root=runtime,
            candidate=next_frontier,
            source_kind="source_family_smoked_candidate_thin_bind",
            source_ref=paths["runtime_latest"],
        )
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["wave_latest"]), payload)
        write_text(Path(paths["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Thin-bind source-family smoked adapter candidates.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="wave-block7-source-family-smoked-candidate-thin-bind")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        wave_id=args.wave_id,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
