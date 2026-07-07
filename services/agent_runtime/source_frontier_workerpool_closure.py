import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_ROOT = REPO_ROOT / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services.agent_runtime import modular_dynamic_worker_pool_phase1 as phase1

DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(r"E:\XINAO_RESEARCH_WORKSPACES\S")

SCHEMA_VERSION = "xinao.codex_s.source_frontier_workerpool_closure.v1"
SENTINEL = "SENTINEL:XINAO_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = "source_frontier_workerpool_global_closure_20260704"
ROUTE_PROFILE = "seed_cortex_phase0"
ROUTING = "continue_same_task"

DpInvoker = Callable[..., dict[str, Any]]
QwenInvoker = Callable[..., dict[str, Any]]


def now_iso() -> str:
    return phase1.now_iso()


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip(".-")
    if len(cleaned) <= 120:
        return cleaned or "wave"
    digest = hashlib.sha256(cleaned.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{cleaned[:103].strip('.-') or 'wave'}-{digest}"


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def digest_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8", errors="replace"
        )
    ).hexdigest()


def wave_evidence_context(
    *,
    wave_id: str,
    parent_wave_id: str,
    workflow_id: str,
    workflow_run_id: str,
    lane_results: list[dict[str, Any]],
    refs: dict[str, str],
    output: dict[str, str],
    evidence_digest: str,
) -> dict[str, Any]:
    source_batch_ids = sorted(
        {
            str(result.get("source_batch_id") or "")
            for result in lane_results
            if isinstance(result, dict) and str(result.get("source_batch_id") or "")
        }
    )
    worker_brief_ids = sorted(
        {
            str(result.get("worker_brief_id") or "")
            for result in lane_results
            if isinstance(result, dict) and str(result.get("worker_brief_id") or "")
        }
    )
    return {
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "source_batch_ids": source_batch_ids,
        "worker_brief_ids": worker_brief_ids,
        "primary_source_batch_id": source_batch_ids[0] if source_batch_ids else "",
        "primary_worker_brief_id": worker_brief_ids[0] if worker_brief_ids else "",
        "source_bound_worker_brief_queue_ref": str(
            refs.get("source_bound_worker_brief_queue") or ""
        ),
        "source_frontier_workerbrief_bridge_wave_ref": str(
            refs.get("source_frontier_workerbrief_bridge_wave") or ""
        ),
        "same_wave_output_refs": {
            "closure_ref": output["wave"],
            "staging_ref": output["staging"],
            "merge_ref": output["merge"],
            "fan_in_ref": output["fan_in"],
            "aaq_ref": output["aaq"],
            "next_frontier_ref": output["next_frontier"],
            "repair_plan_ref": output["repair_plan"],
            "allocation_plan_ref": output["allocation_plan_snapshot"],
            "provider_scheduler_ref": output["provider_scheduler_snapshot"],
            "lane_results_ref": output["lane_results"],
            "executable_worker_brief_queue_ref": output["executable_worker_brief_queue"],
            "worker_dispatch_ledger_wave_ref": output["worker_dispatch_ledger_wave"],
        },
        "evidence_digest_sha256": evidence_digest,
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def short_lane_id(*, wave_id: str, index: int, worker_brief_id: str, mapping_key: str) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "wave_id": wave_id,
                "index": index,
                "worker_brief_id": worker_brief_id,
                "mapping_key": mapping_key,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"sfwc-{index + 1:02d}-{digest}"


def output_paths(
    runtime: Path, *, wave_id: str, workflow_id: str, digest: str = "pending"
) -> dict[str, str]:
    wave_stem = safe_stem(wave_id)
    workflow_stem = safe_stem(workflow_id)
    root = runtime / "state" / "source_frontier_workerpool_closure"
    wave_dir = root / "waves" / wave_stem
    return {
        "latest": str(root / "latest.json"),
        "wave": str(wave_dir / "closure.json"),
        "executable_worker_brief_queue": str(wave_dir / "executable_worker_brief_queue.json"),
        "lane_results": str(wave_dir / "lane_results.json"),
        "allocation_plan_snapshot": str(wave_dir / "allocation_plan_snapshot.json"),
        "provider_scheduler_snapshot": str(wave_dir / "provider_scheduler_snapshot.json"),
        "staging": str(wave_dir / "staging.json"),
        "merge": str(wave_dir / "merge.json"),
        "fan_in": str(wave_dir / "fan_in_acceptance_queue.json"),
        "aaq": str(wave_dir / "artifact_acceptance_queue.json"),
        "next_frontier": str(wave_dir / "next_frontier_machine_actions.json"),
        "repair_plan": str(wave_dir / "repair_plan.json"),
        "independent_eval": str(wave_dir / "independent_eval_payload.json"),
        "worker_dispatch_ledger_wave": str(
            runtime
            / "state"
            / "worker_dispatch_ledger"
            / "waves"
            / wave_stem
            / f"{digest}.source_frontier_workerpool_closure.json"
        ),
        "worker_dispatch_ledger_activity": str(
            runtime
            / "state"
            / "worker_dispatch_ledger"
            / "activity"
            / workflow_stem
            / f"{wave_stem}.source_frontier_workerpool_closure.json"
        ),
        "readback_zh": str(
            runtime / "readback" / "zh" / f"source_frontier_workerpool_closure_{wave_stem}.md"
        ),
        "fan_in_wave_read_model": str(
            runtime
            / "state"
            / "fan_in_acceptance_queue"
            / "waves"
            / f"{wave_stem}.source_frontier_workerpool_closure.json"
        ),
        "next_frontier_wave_read_model": str(
            runtime
            / "state"
            / "next_frontier_machine_actions"
            / "waves"
            / f"{wave_stem}.source_frontier_workerpool_closure.json"
        ),
    }


def build_input_snapshot(
    *,
    snapshot_kind: str,
    source_ref: str,
    output_ref: str,
    evidence_context: dict[str, Any],
) -> dict[str, Any]:
    source_payload = read_json(Path(source_ref)) if source_ref else {}
    return {
        "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.input_snapshot.v1",
        "snapshot_kind": snapshot_kind,
        "wave_id": str(evidence_context.get("wave_id") or ""),
        "parent_wave_id": str(evidence_context.get("parent_wave_id") or ""),
        "workflow_id": str(evidence_context.get("workflow_id") or ""),
        "workflow_run_id": str(evidence_context.get("workflow_run_id") or ""),
        "evidence_digest_sha256": str(evidence_context.get("evidence_digest_sha256") or ""),
        "source_ref": source_ref,
        "snapshot_ref": output_ref,
        "source_digest_sha256": digest_json(source_payload) if source_payload else "",
        "source_payload": source_payload,
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_input_snapshots(
    *,
    refs: dict[str, str],
    output: dict[str, str],
    evidence_context: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        "allocation_plan": build_input_snapshot(
            snapshot_kind="allocation_plan",
            source_ref=str(refs.get("allocation_plan") or ""),
            output_ref=str(output.get("allocation_plan_snapshot") or ""),
            evidence_context=evidence_context,
        ),
        "provider_scheduler": build_input_snapshot(
            snapshot_kind="provider_scheduler",
            source_ref=str(refs.get("provider_scheduler") or ""),
            output_ref=str(output.get("provider_scheduler_snapshot") or ""),
            evidence_context=evidence_context,
        ),
    }


def runtime_refs(runtime: Path, *, parent_wave_id: str) -> dict[str, str]:
    bridge_waves_root = runtime / "state" / "source_frontier_workerbrief_bridge" / "waves"
    bridge_wave_full = bridge_waves_root / f"{parent_wave_id}.json"
    bridge_wave_safe = bridge_waves_root / f"{safe_stem(parent_wave_id)}.json"
    bridge_wave = bridge_wave_full if bridge_wave_full.is_file() else bridge_wave_safe
    return {
        "source_bound_worker_brief_queue": str(bridge_wave),
        "source_bound_worker_brief_queue_latest": str(
            runtime
            / "state"
            / "source_frontier_workerbrief_bridge"
            / "worker_brief_queue_latest.json"
        ),
        "source_frontier_workerbrief_bridge_wave": str(bridge_wave),
        "allocation_plan": str(runtime / "state" / "allocation_plan" / "latest.json"),
        "allocation_worker_brief_queue": str(
            runtime / "state" / "allocation_plan" / "worker_brief_queue_latest.json"
        ),
        "provider_scheduler": str(
            runtime / "state" / phase1.PROVIDER_SCHEDULER_TASK_ID / "latest.json"
        ),
        "provider_scheduler_qwen_policy": str(
            runtime
            / "state"
            / phase1.PROVIDER_SCHEDULER_TASK_ID
            / "qwen_prepaid_policy"
            / "latest.json"
        ),
        "provider_scheduler_qwen_invocation": str(
            runtime
            / "state"
            / phase1.PROVIDER_SCHEDULER_TASK_ID
            / "qwen_invocation"
            / "latest.json"
        ),
    }


def source_bound_queue_from_parent_bridge(
    *,
    bridge_wave: dict[str, Any],
    refs: dict[str, str],
    parent_wave_id: str,
) -> dict[str, Any]:
    bindings = bridge_wave.get("worker_brief_bindings")
    if not isinstance(bindings, list):
        bindings = []
    source_batch_ids = sorted(
        {
            str(binding.get("source_batch_id") or "")
            for binding in bindings
            if isinstance(binding, dict) and str(binding.get("source_batch_id") or "")
        }
    )
    bridge_wave_id = str(bridge_wave.get("wave_id") or "")
    chain_refs = (
        bridge_wave.get("chain_refs") if isinstance(bridge_wave.get("chain_refs"), dict) else {}
    )
    canonical_queue_ref = str(
        bridge_wave.get("canonical_worker_brief_queue_ref")
        or chain_refs.get("worker_brief_queue_ref")
        or ""
    )
    status = (
        "source_bound_worker_brief_queue_ready"
        if bindings
        else "source_bound_worker_brief_queue_blocked"
    )
    return {
        "schema_version": "xinao.codex_s.worker_brief_queue.source_bound.v1",
        "status": status,
        "wave_id": bridge_wave_id,
        "parent_wave_id": parent_wave_id,
        "source_queue_source": "parent_bridge_wave",
        "source_queue_loaded_from_wave_ref": refs.get(
            "source_frontier_workerbrief_bridge_wave", ""
        ),
        "source_queue_latest_fallback_used": False,
        "canonical_worker_brief_queue_ref": canonical_queue_ref,
        "brief_count": len([item for item in bindings if isinstance(item, dict)]),
        "briefs": [item for item in bindings if isinstance(item, dict)],
        "source_item_count": int(bridge_wave.get("source_item_count") or 0),
        "source_batch_ids": source_batch_ids,
        "bridge_validation_passed": bridge_wave.get("validation", {}).get("passed")
        if isinstance(bridge_wave.get("validation"), dict)
        else False,
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def lane_class_from_binding(binding: dict[str, Any]) -> str:
    raw = str(binding.get("lane_class") or binding.get("original_worker_brief_id") or "").lower()
    for lane_class in (
        "cheap_draft",
        "foreground_brain",
        "eval",
        "repo_exec",
        "ci_verify",
        "merge_accept",
        "durable_temporal",
        "search_source",
    ):
        if lane_class in raw:
            return lane_class
    expected = str(binding.get("expected_artifact") or "").lower()
    if "draft" in expected:
        return "cheap_draft"
    if "merge" in expected:
        return "merge_accept"
    return "eval"


def mode_for_binding(binding: dict[str, Any], index: int) -> str:
    lane_class = lane_class_from_binding(binding)
    mapping = {
        "cheap_draft": "draft",
        "foreground_brain": "audit",
        "eval": "eval",
        "repo_exec": "extraction",
        "ci_verify": "citation_verify",
        "merge_accept": "contradiction",
        "durable_temporal": "audit",
        "search_source": "citation_verify",
    }
    mode = mapping.get(lane_class, "eval")
    if index == 0 and mode != "draft":
        return "draft"
    return mode


def render_source_bound_input(
    *,
    binding: dict[str, Any],
    mode: str,
    provider_route: dict[str, Any],
    refs: dict[str, str],
    parent_wave_id: str,
) -> str:
    return "\n".join(
        [
            f"task_id={TASK_ID}",
            f"parent_wave_id={parent_wave_id}",
            f"source_batch_id={binding.get('source_batch_id')}",
            f"frontier_batch_id={binding.get('frontier_batch_id')}",
            f"worker_brief_id={binding.get('worker_brief_id')}",
            f"mapping_key={binding.get('mapping_key')}",
            f"claim_card_id={binding.get('claim_card_id')}",
            f"claim_card_ref={binding.get('claim_card_ref')}",
            f"source_package_ref={json.dumps(binding.get('source_package_ref') or {}, ensure_ascii=False, sort_keys=True)}",
            f"mode={mode}",
            f"objective={binding.get('objective')}",
            f"expected_artifact={binding.get('expected_artifact')}",
            f"provider_scheduler_ref={refs.get('provider_scheduler')}",
            f"provider_route_class={provider_route.get('route_class')}",
            f"preferred_provider_id={provider_route.get('preferred_provider_id')}",
            "fallback_provider_ids="
            + " | ".join(str(item) for item in provider_route.get("fallback_provider_ids", [])),
            f"qwen_prepaid_first_required={provider_route.get('qwen_prepaid_first_required') is True}",
            "must_stage_before_merge=true",
            "direct_final_allowed=false",
            "completion_claim_allowed=false",
            "chain_required=WorkerBrief -> ProviderScheduler -> worker_pool -> staging -> merge -> FanIn -> AAQ -> next_frontier",
        ]
    )


def executable_worker_briefs(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    parent_wave_id: str,
    source_bound_queue: dict[str, Any],
    refs: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    provider_context = phase1.load_provider_route_context(runtime)
    raw_bindings = (
        source_bound_queue.get("briefs")
        if isinstance(source_bound_queue.get("briefs"), list)
        else []
    )
    briefs: list[dict[str, Any]] = []
    mode_counts = {mode: 0 for mode in phase1.MODE_ORDER}
    for index, binding in enumerate(raw_bindings):
        if not isinstance(binding, dict):
            continue
        mode = mode_for_binding(binding, index)
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        provider_route = phase1.provider_route_for_mode(mode, provider_context)
        worker_brief_id = str(
            binding.get("worker_brief_id") or f"source-bound-worker-brief-{index + 1:02d}"
        )
        lane_id = short_lane_id(
            wave_id=wave_id,
            index=index,
            worker_brief_id=worker_brief_id,
            mapping_key=str(binding.get("mapping_key") or ""),
        )
        briefs.append(
            {
                "lane_id": lane_id,
                "lane_number": len(briefs) + 1,
                "mode": mode,
                "objective": str(binding.get("objective") or "Execute source-bound WorkerBrief."),
                "input_text": render_source_bound_input(
                    binding=binding,
                    mode=mode,
                    provider_route=provider_route,
                    refs=refs,
                    parent_wave_id=parent_wave_id,
                ),
                "write_targets": [
                    str(repo),
                    str(runtime / "state" / "source_frontier_workerpool_closure"),
                ],
                "artifact_contract": "source-bound worker result must enter closure staging/fan-in only",
                "provider_route": provider_route,
                "provider_scheduler_context": {
                    "provider_scheduler_task_id": provider_context.get(
                        "provider_scheduler_task_id"
                    ),
                    "provider_scheduler_latest_ref": provider_context.get(
                        "provider_scheduler_latest_ref"
                    ),
                    "qwen_prepaid_policy_ref": provider_context.get("qwen_prepaid_policy_ref"),
                    "qwen_invocation_ref": provider_context.get("qwen_invocation_ref"),
                    "qwen_prepaid_cheap_worker_ready": provider_context.get(
                        "qwen_prepaid_cheap_worker_ready"
                    )
                    is True,
                },
                "source_bound_worker_brief": binding,
                "source_batch_id": str(binding.get("source_batch_id") or ""),
                "worker_brief_id": worker_brief_id,
                "mapping_key": str(binding.get("mapping_key") or ""),
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            }
        )
    if briefs and all(brief["mode"] != "draft" for brief in briefs):
        briefs[0]["mode"] = "draft"
        briefs[0]["provider_route"] = phase1.provider_route_for_mode("draft", provider_context)
        mode_counts["draft"] = 1
    return briefs, mode_counts


def enrich_lane_result(result: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    binding = (
        brief.get("source_bound_worker_brief")
        if isinstance(brief.get("source_bound_worker_brief"), dict)
        else {}
    )
    return {
        **result,
        "worker_brief_id": str(brief.get("worker_brief_id") or ""),
        "source_batch_id": str(brief.get("source_batch_id") or ""),
        "frontier_batch_id": str(
            binding.get("frontier_batch_id") or brief.get("source_batch_id") or ""
        ),
        "claim_card_id": str(binding.get("claim_card_id") or ""),
        "claim_card_ref": str(binding.get("claim_card_ref") or ""),
        "mapping_key": str(brief.get("mapping_key") or ""),
        "allocation_plan_ref": str(binding.get("allocation_plan_ref") or ""),
        "source_bound_worker_brief": binding,
    }


def run_source_bound_lanes(
    *,
    runtime: Path,
    wave_id: str,
    briefs: list[dict[str, Any]],
    dp_invoker: DpInvoker | None,
    qwen_invoker: QwenInvoker | None,
    write: bool,
) -> list[dict[str, Any]]:
    dp = dp_invoker or phase1.default_dp_invoker()
    qwen = qwen_invoker or phase1.default_qwen_invoker()
    results: list[dict[str, Any]] = []
    for brief in briefs:
        result = phase1.run_lane(
            runtime=runtime,
            wave_id=wave_id,
            brief=brief,
            dp_invoker=dp,
            qwen_invoker=qwen,
            write=write,
        )
        results.append(enrich_lane_result(result, brief))
    return results


def is_local_stub_result(result: dict[str, Any]) -> bool:
    return phase1.is_local_stub_result(result)


def is_real_external_worker_result(result: dict[str, Any]) -> bool:
    return phase1.is_real_remote_model_result(result)


def provider_materialization_summary(
    lane_results: list[dict[str, Any]],
    spend_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spend = spend_ledger if isinstance(spend_ledger, dict) else {}
    entries = spend.get("entries") if isinstance(spend.get("entries"), list) else []
    real_results = [result for result in lane_results if is_real_external_worker_result(result)]
    real_drafts = [result for result in real_results if result.get("mode") == "draft"]
    qwen_real = [
        result
        for result in real_results
        if result.get("selected_carrier_provider_id") == phase1.QWEN_CHEAP_WORKER_PROVIDER_ID
    ]
    deepseek_real = [
        result
        for result in real_results
        if result.get("selected_carrier_provider_id")
        in {phase1.DEEPSEEK_DP_PROVIDER_ID, phase1.DEEPSEEK_DP_ROUTE_ID}
    ]
    local_stub_results = [result for result in lane_results if is_local_stub_result(result)]
    tool_diagnostic_results = [
        result for result in lane_results if phase1.is_tool_diagnostic_result(result)
    ]
    real_spend_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and (
            entry.get("qwen_prepaid_invocation") is True
            or entry.get("deepseek_dp_invocation") is True
            or str(entry.get("selected_carrier_provider_id") or "")
            in phase1.REAL_WORKER_PROVIDER_IDS
        )
    ]
    provider_tier_usage = (
        spend.get("provider_tier_usage")
        if isinstance(spend.get("provider_tier_usage"), dict)
        else {}
    )
    qwen_required = [
        result for result in lane_results if result.get("qwen_prepaid_first_required") is True
    ]
    qwen_real_invoked = len(qwen_real) > 0
    deepseek_real_invoked = len(deepseek_real) > 0
    return {
        "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.provider_materialization.v1",
        "real_worker_provider_ids_required": sorted(phase1.REAL_WORKER_PROVIDER_IDS),
        "real_worker_model_invocation_count": len(real_results),
        "qwen_real_model_invocation_count": len(qwen_real),
        "deepseek_dp_real_model_invocation_count": len(deepseek_real),
        "qwen_real_model_invoked": qwen_real_invoked,
        "deepseek_dp_real_model_invoked": deepseek_real_invoked,
        "qwen_and_deepseek_real_model_invoked": qwen_real_invoked and deepseek_real_invoked,
        "external_cheap_draft_count": len(real_drafts),
        "real_provider_invocation_refs": [
            str(result.get("provider_invocation_ref") or "") for result in real_results
        ],
        "real_worker_provider_ids_seen": sorted(
            {str(result.get("selected_carrier_provider_id") or "") for result in real_results}
        ),
        "selected_provider_ids_seen": sorted(
            {
                str(result.get("selected_carrier_provider_id") or "")
                for result in lane_results
                if str(result.get("selected_carrier_provider_id") or "")
            }
        ),
        "local_stub_count": len(local_stub_results),
        "local_stub_draft_count": len(
            [result for result in local_stub_results if result.get("mode") == "draft"]
        ),
        "local_stub_provider_ids_seen": sorted(
            {
                str(result.get("selected_carrier_provider_id") or "")
                for result in local_stub_results
                if str(result.get("selected_carrier_provider_id") or "")
            }
        ),
        "provider_probe_mode_count": len(
            [result for result in lane_results if result.get("mode") == "provider_probe"]
        ),
        "tool_diagnostic_count": len(tool_diagnostic_results),
        "tool_diagnostic_provider_ids_seen": sorted(
            {
                str(result.get("selected_carrier_provider_id") or "")
                for result in tool_diagnostic_results
                if str(result.get("selected_carrier_provider_id") or "")
            }
        ),
        "spend_ledger_real_provider_entry_count": len(real_spend_entries),
        "spend_ledger_provider_usage_entry_count": int(
            spend.get("token_cost_spend", {}).get("provider_usage_entry_count") or 0
        )
        if isinstance(spend.get("token_cost_spend"), dict)
        else 0,
        "provider_tier_usage": provider_tier_usage,
        "qwen_prepaid_first_required_count": len(qwen_required),
        "qwen_prepaid_first_attempted_count": len(
            [
                result
                for result in qwen_required
                if result.get("qwen_prepaid_first_attempted") is True
            ]
        ),
        "qwen_prepaid_first_succeeded_count": len(
            [
                result
                for result in qwen_required
                if result.get("qwen_prepaid_first_succeeded") is True
            ]
        ),
        "qwen_fallback_allowed_count": len(
            [result for result in qwen_required if result.get("fallback_allowed") is True]
        ),
        "qwen_or_deepseek_real_model_invoked": len(real_results) > 0,
        "external_draft_model_invoked": len(real_drafts) > 0,
        "local_stub_only": bool(lane_results)
        and len(real_results) == 0
        and len(local_stub_results) > 0,
        "local_stub_as_completion_attempted": bool(local_stub_results) and len(real_results) == 0,
        "tool_diagnostic_only": bool(lane_results)
        and len(real_results) == 0
        and len(tool_diagnostic_results) > 0,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_source_bound_staging(
    *,
    wave_id: str,
    lane_results: list[dict[str, Any]],
    output: dict[str, str],
    evidence_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = evidence_context or {}
    entries = []
    for result in lane_results:
        staged = result.get("status") == "succeeded" and bool(result.get("artifact_ref"))
        real_external_worker = staged and is_real_external_worker_result(result)
        entries.append(
            {
                "source_batch_id": result.get("source_batch_id", ""),
                "worker_brief_id": result.get("worker_brief_id", ""),
                "lane_id": result.get("lane_id", ""),
                "mode": result.get("mode", ""),
                "artifact_ref": result.get("artifact_ref", ""),
                "provider_invocation_ref": result.get("provider_invocation_ref", ""),
                "selected_carrier_provider_id": result.get("selected_carrier_provider_id", ""),
                "stage_status": "staged_real_external_worker_for_merge_fanin"
                if real_external_worker
                else "staged_local_or_tool_diagnostic_only"
                if staged
                else "blocked_before_staging",
                "staged_for_merge": staged,
                "real_external_worker_invocation": real_external_worker,
                "eligible_for_workerpool_acceptance": real_external_worker,
                "local_stub": is_local_stub_result(result),
                "model_invocation_performed": result.get("model_invocation_performed") is True,
                "completion_claim_allowed": False,
            }
        )
    return {
        **context,
        "schema_version": "xinao.codex_s.source_bound_workerpool_staging.v1",
        "status": "source_bound_staging_ready"
        if any(entry["staged_for_merge"] for entry in entries)
        else "source_bound_staging_blocked",
        "wave_id": wave_id,
        "staging_ref": output["staging"],
        "entry_count": len(entries),
        "staged_count": len([entry for entry in entries if entry["staged_for_merge"]]),
        "real_external_staged_count": len(
            [entry for entry in entries if entry["real_external_worker_invocation"]]
        ),
        "local_or_tool_diagnostic_staged_count": len(
            [
                entry
                for entry in entries
                if entry["staged_for_merge"] and not entry["real_external_worker_invocation"]
            ]
        ),
        "entries": entries,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_merge_record(
    *,
    wave_id: str,
    phase1_merge: dict[str, Any],
    phase1_staging: dict[str, Any],
    closure_staging: dict[str, Any],
    output: dict[str, str],
    evidence_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = evidence_context or {}
    return {
        **context,
        "schema_version": "xinao.codex_s.source_bound_workerpool_merge.v1",
        "status": "source_bound_merge_ready"
        if phase1_merge.get("status") == "merge_consumer_merged"
        else "source_bound_merge_blocked",
        "wave_id": wave_id,
        "merge_ref": output["merge"],
        "phase1_merge_consumer": phase1_merge,
        "phase1_draft_staging": phase1_staging,
        "source_bound_staging_ref": output["staging"],
        "source_bound_staged_count": closure_staging.get("staged_count", 0),
        "merge_artifact": phase1_merge.get("merge_artifact", ""),
        "merged_count": phase1_merge.get("merged_count", 0),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_fan_in(
    *,
    wave_id: str,
    lane_results: list[dict[str, Any]],
    staging: dict[str, Any],
    merge: dict[str, Any],
    output: dict[str, str],
    evidence_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = evidence_context or {}
    accepted_edges = []
    staged_by_worker = {
        str(entry.get("worker_brief_id") or ""): entry
        for entry in staging.get("entries", [])
        if isinstance(entry, dict)
    }
    for index, result in enumerate(lane_results, start=1):
        worker_brief_id = str(result.get("worker_brief_id") or "")
        staged = staged_by_worker.get(worker_brief_id, {})
        real_external_worker = staged.get("eligible_for_workerpool_acceptance") is True
        accepted_edges.append(
            {
                "edge_id": f"source-bound-workerpool-edge-{index:02d}",
                "source_batch_id": result.get("source_batch_id", ""),
                "worker_brief_id": worker_brief_id,
                "lane_id": result.get("lane_id", ""),
                "mode": result.get("mode", ""),
                "producer_lane": result.get("selected_carrier_provider_id", ""),
                "provider_invocation_ref": result.get("provider_invocation_ref", ""),
                "artifact_ref": result.get("artifact_ref", ""),
                "staging_ref": output["staging"],
                "staged_for_merge": staged.get("staged_for_merge") is True,
                "real_external_worker_invocation": real_external_worker,
                "local_stub": staged.get("local_stub") is True,
                "merge_ref": output["merge"],
                "accepted_for": "source_bound_workerpool_closure_aaq_candidate",
                "acceptance_decision": "accepted_for_aaq_candidate"
                if real_external_worker
                else "blocked_before_aaq",
                "direct_fact_promotion_allowed": False,
                "completion_claim_allowed": False,
            }
        )
    accepted = [
        edge
        for edge in accepted_edges
        if edge["acceptance_decision"] == "accepted_for_aaq_candidate"
    ]
    return {
        **context,
        "schema_version": "xinao.codex_s.fan_in_acceptance.v1",
        "status": "fan_in_acceptance_ready_for_source_bound_workerpool"
        if accepted and merge.get("status") == "source_bound_merge_ready"
        else "fan_in_acceptance_repair_required",
        "object_type": "FanInAcceptanceQueue",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "source_kind": "source_bound_worker_brief_queue",
        "fan_in_ref": output["fan_in"],
        "fan_in_is_default_heart": True,
        "not_new_bypass_queue": True,
        "connects_existing_chain": [
            "SourceFrontier",
            "WorkerBrief",
            "ProviderScheduler",
            "worker_pool",
            "staging",
            "merge",
            "ArtifactAcceptanceQueue",
            "next_frontier",
        ],
        "accepted_edges": accepted_edges,
        "accepted_edge_count": len(accepted),
        "next_consumer": "ArtifactAcceptanceQueue",
        "validation": {
            "passed": bool(accepted),
            "checks": {
                "accepted_edges_present": bool(accepted),
                "all_edges_wave_scoped": all(
                    edge.get("staging_ref") == output["staging"] for edge in accepted_edges
                ),
                "direct_fact_promotion_denied": True,
                "completion_claim_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_aaq(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    lane_results: list[dict[str, Any]],
    merge: dict[str, Any],
    fan_in: dict[str, Any],
    output: dict[str, str],
    write: bool,
    evidence_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = evidence_context or {}
    if not write:
        return {
            **context,
            "schema_version": "xinao.seedcortex.artifact_acceptance_queue.v1",
            "status": "artifact_acceptance_queue_skipped_no_write",
            "accepted_artifact_count": 0,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        }
    src = repo / "src"
    for item in (src, repo):
        if str(item) not in sys.path:
            sys.path.insert(0, str(item))
    from xinao_seedlab.adapters.local_fs import to_plain
    from xinao_seedlab.application.seed_cortex import build_default_service

    accepted_edges = [
        edge
        for edge in fan_in.get("accepted_edges", [])
        if isinstance(edge, dict)
        and edge.get("acceptance_decision") == "accepted_for_aaq_candidate"
    ]
    candidates = []
    for index, edge in enumerate(accepted_edges, start=1):
        candidates.append(
            {
                "object_type": "ClaimCard",
                "candidate_id": f"{safe_stem(wave_id)}-source-bound-workerpool-{index:02d}",
                "source_url": str(
                    edge.get("provider_invocation_ref")
                    or edge.get("artifact_ref")
                    or output["fan_in"]
                ),
                "source_family": "source_bound_workerpool_closure",
                "claim": (
                    "Source-bound WorkerBrief drove ProviderScheduler worker-pool execution "
                    f"for source_batch_id={edge.get('source_batch_id')} worker_brief_id={edge.get('worker_brief_id')}."
                ),
                "verification_need": "Verify provider invocation, staging, merge, FanIn, AAQ, and next_frontier refs in the same wave.",
                "accepted_for": "source_bound_workerpool_next_frontier_evidence",
                "artifact_ref": str(merge.get("merge_artifact") or edge.get("artifact_ref") or ""),
                "worker_brief_id": str(edge.get("worker_brief_id") or ""),
                "source_batch_id": str(edge.get("source_batch_id") or ""),
                "fan_in_ref": output["fan_in"],
                "merge_ref": output["merge"],
            }
        )
    service = build_default_service(runtime, repo_root=repo)
    payload = to_plain(
        service.artifact_acceptance_queue(
            f"{TASK_ID}-{safe_stem(wave_id)}",
            candidates,
            write_runtime=True,
        )
    )
    return {
        **payload,
        **context,
        "wave_id": wave_id,
        "aaq_ref": output["aaq"],
        "fan_in_ref": output["fan_in"],
        "merge_ref": output["merge"],
        "source_bound_claim_card_count": len(candidates),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_next_frontier(
    *,
    wave_id: str,
    parent_wave_id: str,
    aaq: dict[str, Any],
    merge: dict[str, Any],
    staging: dict[str, Any],
    output: dict[str, str],
    evidence_context: dict[str, Any] | None = None,
    provider_materialization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = evidence_context or {}
    materialization = provider_materialization if isinstance(provider_materialization, dict) else {}
    accepted = int(aaq.get("accepted_artifact_count") or 0)
    artifact_delta_count = (
        1 if merge.get("merge_artifact") and int(merge.get("merged_count") or 0) > 0 else 0
    )
    synthetic_item_used = any(
        str(batch_id).startswith("bounded-current-source-delta-")
        for batch_id in context.get("source_batch_ids", [])
        if str(batch_id)
    )
    qwen_model_ok = (
        materialization.get("qwen_real_model_invoked") is True
        or int(materialization.get("qwen_real_model_invocation_count") or 0) > 0
        if materialization
        else True
    )
    deepseek_model_ok = (
        materialization.get("deepseek_dp_real_model_invoked") is True
        or int(materialization.get("deepseek_dp_real_model_invocation_count") or 0) > 0
        if materialization
        else True
    )
    real_worker_model_ok = qwen_model_ok and deepseek_model_ok if materialization else True
    external_draft_ok = (
        materialization.get("external_draft_model_invoked") is True if materialization else True
    )
    next_frontier_real_work_count = (
        accepted
        if artifact_delta_count > 0
        and not synthetic_item_used
        and real_worker_model_ok
        and external_draft_ok
        else 0
    )
    next_should_continue = (
        accepted > 0
        and artifact_delta_count > 0
        and not synthetic_item_used
        and real_worker_model_ok
        and external_draft_ok
        and next_frontier_real_work_count > 0
    )
    return {
        **context,
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "next_frontier_machine_actions_ready"
        if next_should_continue
        else "next_frontier_machine_actions_repair_required",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "next_frontier_ref": output["next_frontier"],
        "should_continue_loop": next_should_continue,
        "stop_allowed": False,
        "next_decision": "continue_with_real_frontier"
        if next_should_continue
        else "drain_fan_in_or_replan",
        "while_driver": "event_backlog_frontier_driven"
        if next_should_continue
        else "progress_ledger_gate",
        "source_bound_workerpool_wave_consumed": accepted > 0 and artifact_delta_count > 0,
        "aaq_accepted_artifact_count": accepted,
        "artifact_delta_count": artifact_delta_count,
        "synthetic_item_used": synthetic_item_used,
        "source_bound_staged_count": int(staging.get("staged_count") or 0),
        "real_external_staged_count": int(staging.get("real_external_staged_count") or 0),
        "provider_materialization": materialization,
        "next_frontier_real_work_count": next_frontier_real_work_count,
        "next_frontier_self_loop_count": 0 if next_should_continue else 1,
        "continue_gate": {
            "AAQ_accepted_delta_positive": accepted > 0,
            "artifact_delta_count_positive": artifact_delta_count > 0,
            "synthetic_item_used_false": not synthetic_item_used,
            "qwen_or_deepseek_real_model_invoked": real_worker_model_ok,
            "qwen_real_model_invoked": qwen_model_ok,
            "deepseek_dp_real_model_invoked": deepseek_model_ok,
            "qwen_and_deepseek_real_model_invoked": real_worker_model_ok,
            "external_draft_model_invoked": external_draft_ok,
            "next_frontier_real_work_count_positive": next_frontier_real_work_count > 0,
        },
        "next_frontier": [
            {
                "action_id": f"{safe_stem(wave_id)}-recompute-capacity-after-source-bound-workerpool",
                "action": "recompute_capacity_and_dispatch_next_frontier"
                if next_should_continue
                else "drain_fan_in_or_replan_before_dispatch",
                "parent_wave_id": parent_wave_id,
                "requires": [
                    "source_bound_workerpool_closure",
                    "worker_dispatch_ledger_wave_record",
                    "provider_invocation_refs",
                    "staging_merge_fanin_aaq_refs",
                ],
            }
        ],
        "validation": {
            "passed": accepted > 0 if next_should_continue else True,
            "checks": {
                "aaq_has_accepted_artifacts": accepted > 0,
                "artifact_delta_count_positive": artifact_delta_count > 0,
                "synthetic_item_not_used": not synthetic_item_used,
                "next_continue_requires_real_work": next_should_continue
                == (
                    accepted > 0
                    and artifact_delta_count > 0
                    and not synthetic_item_used
                    and real_worker_model_ok
                    and external_draft_ok
                    and next_frontier_real_work_count > 0
                ),
                "qwen_or_deepseek_real_model_invoked": real_worker_model_ok,
                "qwen_real_model_invoked": qwen_model_ok,
                "deepseek_dp_real_model_invoked": deepseek_model_ok,
                "qwen_and_deepseek_real_model_invoked": real_worker_model_ok,
                "external_draft_model_invoked": external_draft_ok,
                "stop_denied": True,
                "parent_wave_bound": bool(parent_wave_id),
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_acceptance_chains(
    *,
    lane_results: list[dict[str, Any]],
    refs: dict[str, str],
    output: dict[str, str],
    evidence_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = evidence_context or {}
    chains = []
    for result in lane_results:
        binding = (
            result.get("source_bound_worker_brief")
            if isinstance(result.get("source_bound_worker_brief"), dict)
            else {}
        )
        chains.append(
            {
                "wave_id": str(context.get("wave_id") or ""),
                "parent_wave_id": str(context.get("parent_wave_id") or ""),
                "workflow_id": str(context.get("workflow_id") or ""),
                "workflow_run_id": str(context.get("workflow_run_id") or ""),
                "evidence_digest_sha256": str(context.get("evidence_digest_sha256") or ""),
                "source_batch_id": str(result.get("source_batch_id") or ""),
                "worker_brief_id": str(result.get("worker_brief_id") or ""),
                "allocation_plan_ref": str(
                    output.get("allocation_plan_snapshot") or refs.get("allocation_plan") or ""
                ),
                "provider_scheduler_ref": str(
                    output.get("provider_scheduler_snapshot")
                    or refs.get("provider_scheduler")
                    or ""
                ),
                "provider_invocation_ref": str(result.get("provider_invocation_ref") or ""),
                "staging_ref": output["staging"],
                "merge_ref": output["merge"],
                "fan_in_ref": output["fan_in"],
                "aaq_ref": output["aaq"],
                "next_frontier_ref": output["next_frontier"],
                "mapping_key": str(result.get("mapping_key") or binding.get("mapping_key") or ""),
                "lane_id": str(result.get("lane_id") or ""),
                "mode": str(result.get("mode") or ""),
                "status": str(result.get("status") or ""),
                "artifact_ref": str(result.get("artifact_ref") or ""),
            }
        )
    return chains


def build_repair_plan(
    *,
    wave_id: str,
    lane_results: list[dict[str, Any]],
    staging: dict[str, Any],
    merge: dict[str, Any],
    fan_in: dict[str, Any],
    aaq: dict[str, Any],
    output: dict[str, str],
    provider_materialization: dict[str, Any] | None = None,
    evidence_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = evidence_context or {}
    materialization = (
        provider_materialization
        if isinstance(provider_materialization, dict)
        else provider_materialization_summary(lane_results)
    )
    repair_items = []
    for result in lane_results:
        if result.get("status") == "succeeded":
            continue
        blocker = str(
            result.get("named_blocker")
            or result.get("mode_invocation_status")
            or "WORKER_LANE_BLOCKED"
        )
        repair_items.append(
            {
                "source_batch_id": result.get("source_batch_id", ""),
                "worker_brief_id": result.get("worker_brief_id", ""),
                "lane_id": result.get("lane_id", ""),
                "provider_invocation_ref": result.get("provider_invocation_ref", ""),
                "blocker_name": blocker,
                "fixable": blocker
                in {
                    "QWEN_RATE_LIMIT",
                    "QWEN_AUTH_FAILED",
                    "QWEN_NOT_READY",
                    "QWEN_WORKER_POOL_INVOKER_NOT_ROUTED",
                    "QWEN_TRANSIENT_OR_ENDPOINT_FAILED",
                    "TASK_NOT_SUITABLE_FOR_QWEN",
                }
                or "RATE" in blocker.upper()
                or "AUTH" in blocker.upper()
                or "TIMEOUT" in blocker.upper()
                or "ENDPOINT" in blocker.upper()
                or "TRANSIENT" in blocker.upper()
                or "NOT_READY" in blocker.upper(),
                "unblock_action": "repair_provider_route_or_credentials_then_requeue_same_source_bound_workerbrief",
                "report_substitute_allowed": False,
            }
        )
    if materialization.get("qwen_or_deepseek_real_model_invoked") is not True:
        repair_items.append(
            {
                "blocker_name": "REAL_QWEN_OR_DEEPSEEK_MODEL_INVOCATION_MISSING",
                "fixable": True,
                "unblock_action": (
                    "requeue same source-bound WorkerBrief through ProviderScheduler "
                    "with live qwen_prepaid_cheap_worker or DeepSeek/DP model invocation; "
                    "local_draft/local_eval/provider_probe cannot satisfy workerpool closure"
                ),
                "local_stub_count": materialization.get("local_stub_count", 0),
                "report_substitute_allowed": False,
            }
        )
    if (
        materialization.get("qwen_real_model_invoked") is not True
        and int(materialization.get("qwen_real_model_invocation_count") or 0) <= 0
    ):
        repair_items.append(
            {
                "blocker_name": "REAL_QWEN_MODEL_INVOCATION_MISSING",
                "fixable": True,
                "unblock_action": (
                    "route at least one source-bound draft/extraction/eval lane through "
                    "qwen_prepaid_cheap_worker with a real model invocation"
                ),
                "qwen_real_model_invocation_count": materialization.get(
                    "qwen_real_model_invocation_count", 0
                ),
                "report_substitute_allowed": False,
            }
        )
    if (
        materialization.get("deepseek_dp_real_model_invoked") is not True
        and int(materialization.get("deepseek_dp_real_model_invocation_count") or 0) <= 0
    ):
        repair_items.append(
            {
                "blocker_name": "REAL_DEEPSEEK_DP_MODEL_INVOCATION_MISSING",
                "fixable": True,
                "unblock_action": (
                    "route at least one source-bound quality/eval/audit/contradiction lane "
                    "through legacy.deepseek_dp_sidecar with a real DeepSeek model invocation; "
                    "local_eval/provider_probe cannot satisfy DP workerpool closure"
                ),
                "deepseek_dp_real_model_invocation_count": materialization.get(
                    "deepseek_dp_real_model_invocation_count", 0
                ),
                "report_substitute_allowed": False,
            }
        )
    if materialization.get("external_draft_model_invoked") is not True:
        repair_items.append(
            {
                "blocker_name": "REAL_EXTERNAL_DRAFT_NOT_STAGED",
                "fixable": True,
                "unblock_action": (
                    "dispatch at least one draft lane to qwen_prepaid_cheap_worker "
                    "or DeepSeek/DP and stage that real model artifact before FanIn/AAQ"
                ),
                "local_stub_draft_count": materialization.get("local_stub_draft_count", 0),
                "report_substitute_allowed": False,
            }
        )
    if materialization.get("local_stub_as_completion_attempted") is True:
        repair_items.append(
            {
                "blocker_name": "LOCAL_STUB_USED_AS_WORKERPOOL_COMPLETION",
                "fixable": True,
                "unblock_action": "treat local_* output as diagnostic only and requeue real provider lanes",
                "local_stub_provider_ids_seen": materialization.get(
                    "local_stub_provider_ids_seen", []
                ),
                "report_substitute_allowed": False,
            }
        )
    if int(staging.get("staged_count") or 0) <= 0:
        repair_items.append(
            {
                "blocker_name": "SOURCE_BOUND_WORKERPOOL_NO_STAGED_OUTPUT",
                "fixable": True,
                "unblock_action": "requeue_draft_lane_with_provider_fallback",
                "report_substitute_allowed": False,
            }
        )
    if merge.get("status") != "source_bound_merge_ready":
        repair_items.append(
            {
                "blocker_name": "SOURCE_BOUND_WORKERPOOL_MERGE_NOT_READY",
                "fixable": True,
                "unblock_action": "repair_staging_then_retry_merge",
                "report_substitute_allowed": False,
            }
        )
    if (
        fan_in.get("validation", {}).get("passed") is not True
        or int(aaq.get("accepted_artifact_count") or 0) <= 0
    ):
        repair_items.append(
            {
                "blocker_name": "SOURCE_BOUND_WORKERPOOL_FANIN_AAQ_NOT_ACCEPTED",
                "fixable": True,
                "unblock_action": "repair_claimcard_fanin_aaq_and_requeue",
                "report_substitute_allowed": False,
            }
        )
    repair_required = bool(repair_items)
    fixable_count = len([item for item in repair_items if item.get("fixable") is True])
    return {
        **context,
        "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.repair_plan.v1",
        "status": "repair_plan_required" if repair_required else "repair_plan_not_required",
        "wave_id": wave_id,
        "repair_plan_ref": output["repair_plan"],
        "repair_required": repair_required,
        "fixable_repair_count": fixable_count,
        "dispatch_to": "RootIntentLoop / S Default Dynamic Loop",
        "continue_main_loop": repair_required,
        "repair_items": repair_items,
        "named_blocker": ""
        if not repair_required or fixable_count > 0
        else "SOURCE_BOUND_WORKERPOOL_EXTERNAL_CONDITION_BLOCKED",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_independent_eval_payload(
    *,
    wave_id: str,
    provider_materialization: dict[str, Any],
    merge: dict[str, Any],
    staging: dict[str, Any],
    lane_results: list[dict[str, Any]],
    output: dict[str, str],
    evidence_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = evidence_context or {}
    qwen_ok = int(provider_materialization.get("qwen_real_model_invocation_count") or 0) > 0
    deepseek_ok = (
        int(provider_materialization.get("deepseek_dp_real_model_invocation_count") or 0) > 0
    )
    provider_model_ok = qwen_ok or deepseek_ok
    artifact_delta = int(merge.get("merged_count") or 0) > 0 and bool(merge.get("merge_artifact"))
    draft_ok = provider_materialization.get("external_draft_model_invoked") is True
    local_stub_only = provider_materialization.get("local_stub_only") is True
    tool_diagnostic_only = provider_materialization.get("tool_diagnostic_only") is True
    passed = (
        provider_model_ok
        and artifact_delta
        and draft_ok
        and not local_stub_only
        and not tool_diagnostic_only
    )
    return {
        **context,
        "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.independent_eval.v1",
        "status": "independent_eval_passed" if passed else "independent_eval_needs_repair",
        "wave_id": wave_id,
        "independent_eval_ref": output["independent_eval"],
        "passed": passed,
        "provider_model_ok": provider_model_ok,
        "qwen_real_invoked": qwen_ok,
        "deepseek_dp_real_invoked": deepseek_ok,
        "artifact_delta_observed": artifact_delta,
        "external_draft_invoked": draft_ok,
        "local_stub_only": local_stub_only,
        "tool_diagnostic_only": tool_diagnostic_only,
        "lane_result_count": len(lane_results),
        "eval_is_health_signal_only": True,
        "does_not_zero_artifact_delta": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_validation(payload: dict[str, Any]) -> dict[str, Any]:
    chains = (
        payload.get("acceptance_chains")
        if isinstance(payload.get("acceptance_chains"), list)
        else []
    )
    lane_results = (
        payload.get("lane_results") if isinstance(payload.get("lane_results"), list) else []
    )
    wave_id = str(payload.get("wave_id") or "")
    output = payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}
    wave_candidates = [wave_id]
    safe_wave_id = safe_stem(wave_id) if wave_id else ""
    if safe_wave_id:
        wave_candidates.append(safe_wave_id)
    suffix = "-source-frontier-workerpool-closure"
    if wave_id.endswith(suffix):
        wave_candidates.append(wave_id[: -len(suffix)])
    wave_candidates.extend(
        str(value)
        for value in (
            output.get("wave"),
            output.get("staging"),
            output.get("merge"),
            output.get("fan_in"),
            output.get("aaq"),
            output.get("next_frontier"),
        )
        if str(value)
    )
    expected_chain_refs = {
        "allocation_plan_ref": str(output.get("allocation_plan_snapshot") or ""),
        "provider_scheduler_ref": str(output.get("provider_scheduler_snapshot") or ""),
        "staging_ref": str(output.get("staging") or ""),
        "merge_ref": str(output.get("merge") or ""),
        "fan_in_ref": str(output.get("fan_in") or ""),
        "aaq_ref": str(output.get("aaq") or ""),
        "next_frontier_ref": str(output.get("next_frontier") or ""),
    }
    exact_output_refs_available = all(expected_chain_refs.values())
    providers = {
        str(result.get("selected_carrier_provider_id") or "")
        for result in lane_results
        if isinstance(result, dict) and str(result.get("selected_carrier_provider_id") or "")
    }
    route_preferred = {
        str(result.get("provider_route", {}).get("preferred_provider_id") or "")
        for result in lane_results
        if isinstance(result.get("provider_route"), dict)
    }
    provider_materialization = (
        payload.get("provider_materialization")
        if isinstance(payload.get("provider_materialization"), dict)
        else provider_materialization_summary(
            lane_results,
            payload.get("phase1_spend_ledger")
            if isinstance(payload.get("phase1_spend_ledger"), dict)
            else None,
        )
    )
    independent_eval = (
        payload.get("independent_eval_payload")
        if isinstance(payload.get("independent_eval_payload"), dict)
        else {}
    )
    expected_digest = str(payload.get("evidence_digest_sha256") or "")
    expected_workflow_id = str(payload.get("workflow_id") or "")
    expected_wave_id = str(payload.get("wave_id") or "")
    parent_wave_id = str(payload.get("parent_wave_id") or "")
    queue_wave_id = str(payload.get("source_bound_worker_brief_queue_wave_id") or "")
    queue_source_batch_ids = {
        str(item)
        for item in payload.get("source_bound_worker_brief_queue_source_batch_ids", [])
        if str(item)
    }
    payload_source_batch_ids = {
        str(item) for item in payload.get("source_batch_ids", []) if str(item)
    }
    wave_specific_products = [
        payload.get("staging"),
        payload.get("merge"),
        payload.get("fan_in"),
        payload.get("artifact_acceptance_queue"),
        payload.get("next_frontier"),
    ]
    input_snapshots = (
        payload.get("input_snapshots") if isinstance(payload.get("input_snapshots"), dict) else {}
    )
    wave_specific_input_snapshots = [
        input_snapshots.get("allocation_plan"),
        input_snapshots.get("provider_scheduler"),
    ]
    real_qwen_model_invoked = (
        provider_materialization.get("qwen_real_model_invoked") is True
        or int(provider_materialization.get("qwen_real_model_invocation_count") or 0) > 0
    )
    real_deepseek_dp_model_invoked = (
        provider_materialization.get("deepseek_dp_real_model_invoked") is True
        or int(provider_materialization.get("deepseek_dp_real_model_invocation_count") or 0) > 0
    )
    checks = {
        "source_bound_worker_briefs_loaded": int(
            payload.get("source_bound_worker_brief_count") or 0
        )
        > 0,
        "source_bound_queue_parent_wave_bound": bool(parent_wave_id)
        and queue_wave_id == parent_wave_id,
        "source_bound_queue_no_latest_fallback": payload.get(
            "source_bound_worker_brief_queue_latest_fallback_used"
        )
        is False,
        "source_batch_ids_match_parent_bridge_queue": bool(payload_source_batch_ids)
        and payload_source_batch_ids == queue_source_batch_ids,
        "worker_lanes_invoked": len(lane_results)
        == int(payload.get("source_bound_worker_brief_count") or 0),
        "workflow_id_bound": bool(expected_workflow_id),
        "evidence_digest_bound": bool(expected_digest),
        "provider_scheduler_ref_bound": bool(
            payload.get("input_refs", {}).get("provider_scheduler")
        ),
        "wave_specific_input_snapshots_bound": all(
            isinstance(snapshot, dict)
            and str(snapshot.get("wave_id") or "") == expected_wave_id
            and str(snapshot.get("workflow_id") or "") == expected_workflow_id
            and str(snapshot.get("evidence_digest_sha256") or "") == expected_digest
            and bool(snapshot.get("source_ref"))
            and bool(snapshot.get("snapshot_ref"))
            and bool(snapshot.get("source_digest_sha256"))
            and snapshot.get("latest_alias_is_not_proof") is True
            and snapshot.get("completion_claim_allowed") is False
            and snapshot.get("not_execution_controller") is True
            for snapshot in wave_specific_input_snapshots
        ),
        "provider_scheduler_dynamic_route_used": len(route_preferred - {""}) >= 2,
        "not_qwen_only_or_dp_only_route": len(route_preferred - {""}) >= 2,
        "provider_invocation_refs_present": all(
            bool(chain.get("provider_invocation_ref"))
            for chain in chains
            if isinstance(chain, dict)
        ),
        "real_qwen_or_deepseek_model_invoked": provider_materialization.get(
            "qwen_or_deepseek_real_model_invoked"
        )
        is True,
        "real_qwen_model_invoked": real_qwen_model_invoked,
        "real_deepseek_dp_model_invoked": real_deepseek_dp_model_invoked,
        "real_qwen_and_deepseek_model_invoked": real_qwen_model_invoked
        and real_deepseek_dp_model_invoked,
        "real_external_draft_invoked": provider_materialization.get("external_draft_model_invoked")
        is True,
        "local_stub_not_used_as_completion": provider_materialization.get(
            "local_stub_as_completion_attempted"
        )
        is not True,
        "spend_ledger_real_provider_entry": int(
            provider_materialization.get("spend_ledger_real_provider_entry_count") or 0
        )
        > 0,
        "staging_ready": payload.get("staging", {}).get("status") == "source_bound_staging_ready",
        "staging_has_real_external_worker": int(
            payload.get("staging", {}).get("real_external_staged_count") or 0
        )
        > 0,
        "merge_ready": payload.get("merge", {}).get("status") == "source_bound_merge_ready",
        "fan_in_ready": payload.get("fan_in", {}).get("validation", {}).get("passed") is True,
        "aaq_accepted": int(
            payload.get("artifact_acceptance_queue", {}).get("accepted_artifact_count") or 0
        )
        > 0,
        "next_frontier_ready": payload.get("next_frontier", {}).get("validation", {}).get("passed")
        is True,
        "acceptance_chains_complete": all(
            all(
                bool(chain.get(key))
                for key in (
                    "source_batch_id",
                    "worker_brief_id",
                    "allocation_plan_ref",
                    "provider_scheduler_ref",
                    "provider_invocation_ref",
                    "staging_ref",
                    "merge_ref",
                    "fan_in_ref",
                    "aaq_ref",
                    "next_frontier_ref",
                )
            )
            for chain in chains
            if isinstance(chain, dict)
        )
        and bool(chains),
        "same_wave_refs": all(
            (
                str(chain.get(ref_key) or "") == expected_ref
                if exact_output_refs_available
                else any(
                    candidate and candidate in str(chain.get(ref_key) or "")
                    for candidate in wave_candidates
                )
            )
            for chain in chains
            for ref_key, expected_ref in expected_chain_refs.items()
        ),
        "wave_specific_products_bound": all(
            isinstance(product, dict)
            and str(product.get("wave_id") or "") == expected_wave_id
            and str(product.get("workflow_id") or "") == expected_workflow_id
            and str(product.get("evidence_digest_sha256") or "") == expected_digest
            and bool(product.get("source_batch_ids"))
            and bool(product.get("worker_brief_ids"))
            for product in wave_specific_products
        ),
        "repair_plan_present_if_needed": (
            payload.get("repair_plan", {}).get("repair_required") is False
            or bool(payload.get("repair_plan", {}).get("repair_items"))
        ),
        "independent_eval_payload_present": independent_eval.get("schema_version")
        == "xinao.codex_s.source_frontier_workerpool_closure.independent_eval.v1",
        "independent_eval_is_health_signal_only": independent_eval.get("eval_is_health_signal_only")
        is True
        and independent_eval.get("does_not_zero_artifact_delta") is True,
        "latest_alias_not_proof": payload.get("latest_alias_is_not_proof") is True,
        "completion_claim_disallowed": payload.get("completion_claim_allowed") is False,
        "not_execution_controller": payload.get("not_execution_controller") is True,
    }
    passed = all(checks.values())
    if payload.get("repair_plan", {}).get("repair_required") is True:
        passed = False
    return {
        "passed": passed,
        "checks": checks,
        "providers_seen": sorted(providers),
        "preferred_provider_routes_seen": sorted(route_preferred - {""}),
        "provider_materialization": provider_materialization,
        "validated_at": now_iso(),
    }


def render_readback(payload: dict[str, Any]) -> str:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    repair = payload.get("repair_plan") if isinstance(payload.get("repair_plan"), dict) else {}
    lines = [
        "# source frontier workerpool closure readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- wave_id: `{payload.get('wave_id')}`",
        f"- parent_wave_id: `{payload.get('parent_wave_id')}`",
        f"- source_bound_worker_brief_count: {payload.get('source_bound_worker_brief_count')}",
        f"- invoked_lane_count: {len(payload.get('lane_results', [])) if isinstance(payload.get('lane_results'), list) else 0}",
        f"- source_bound_staged_count: {payload.get('staging', {}).get('staged_count') if isinstance(payload.get('staging'), dict) else ''}",
        f"- accepted_artifact_count: {payload.get('artifact_acceptance_queue', {}).get('accepted_artifact_count') if isinstance(payload.get('artifact_acceptance_queue'), dict) else ''}",
        f"- next_frontier_ref: `{payload.get('output_paths', {}).get('next_frontier', '') if isinstance(payload.get('output_paths'), dict) else ''}`",
        f"- allocation_plan_ref: `{payload.get('same_wave_output_refs', {}).get('allocation_plan_ref', '') if isinstance(payload.get('same_wave_output_refs'), dict) else ''}`",
        f"- provider_scheduler_ref: `{payload.get('same_wave_output_refs', {}).get('provider_scheduler_ref', '') if isinstance(payload.get('same_wave_output_refs'), dict) else ''}`",
        f"- worker_dispatch_ledger_wave: `{payload.get('output_paths', {}).get('worker_dispatch_ledger_wave', '') if isinstance(payload.get('output_paths'), dict) else ''}`",
        f"- validation_passed: {validation.get('passed')}",
        f"- repair_required: {repair.get('repair_required')}",
        f"- independent_eval: `{payload.get('independent_eval_payload', {}).get('status', '') if isinstance(payload.get('independent_eval_payload'), dict) else ''}`",
        "",
        "人话：现在可 invoke `python -m services.agent_runtime.source_frontier_workerpool_closure`。",
        "本波 source-bound WorkerBrief 已实际进入 ProviderScheduler/worker pool，并写出 staging、merge、FanIn、AAQ、next_frontier 的同波证据。",
        "还差的只看 repair_plan/named_blocker；没有这些时继续回 RootIntentLoop 重算容量和下一波，不把 readback 当完成。",
        "",
        SENTINEL,
        "",
    ]
    return "\n".join(lines)


def build_ledger_records(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    output = payload["output_paths"]
    ledger = {
        "schema_version": "xinao.codex_s.worker_dispatch_ledger.source_frontier_workerpool_closure_wave.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": payload["wave_id"],
        "parent_wave_id": payload["parent_wave_id"],
        "workflow_id": payload["workflow_id"],
        "status": "source_frontier_workerpool_closure_wave_recorded",
        "generated_at": payload["generated_at"],
        "immutable_wave_evidence": True,
        "latest_alias_is_not_proof": True,
        "closure_wave_ref": output["wave"],
        "acceptance_chains": payload["acceptance_chains"],
        "evidence_digest_sha256": payload["evidence_digest_sha256"],
        "repair_required": payload["repair_plan"]["repair_required"],
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    activity = {
        "schema_version": "xinao.codex_s.worker_dispatch_ledger.activity_source_frontier_workerpool_closure.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": payload["wave_id"],
        "parent_wave_id": payload["parent_wave_id"],
        "workflow_id": payload["workflow_id"],
        "activity": "source_frontier_workerpool_closure",
        "status": "activity_wave_recorded",
        "generated_at": payload["generated_at"],
        "immutable_wave_evidence_ref": output["worker_dispatch_ledger_wave"],
        "closure_wave_ref": output["wave"],
        "evidence_digest_sha256": payload["evidence_digest_sha256"],
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    return ledger, activity


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "source-frontier-workerpool-global-closure-20260704-verify-wave",
    parent_wave_id: str = "source-frontier-workerpool-global-closure-20260704-verify-wave",
    workflow_id: str = "source-frontier-workerpool-global-closure-20260704",
    workflow_run_id: str = "",
    invoked_by_temporal_activity: bool = False,
    dp_invoker: DpInvoker | None = None,
    qwen_invoker: QwenInvoker | None = None,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    refs = runtime_refs(runtime, parent_wave_id=parent_wave_id)
    bridge_wave = read_json(Path(refs["source_frontier_workerbrief_bridge_wave"]))
    bridge_queue = source_bound_queue_from_parent_bridge(
        bridge_wave=bridge_wave,
        refs=refs,
        parent_wave_id=parent_wave_id,
    )
    executable_briefs, mode_counts = executable_worker_briefs(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        parent_wave_id=parent_wave_id,
        source_bound_queue=bridge_queue,
        refs=refs,
    )
    lane_results = run_source_bound_lanes(
        runtime=runtime,
        wave_id=wave_id,
        briefs=executable_briefs,
        dp_invoker=dp_invoker,
        qwen_invoker=qwen_invoker,
        write=write,
    )
    basis = {
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "worker_brief_ids": [brief.get("worker_brief_id") for brief in executable_briefs],
        "lane_result_digests": [digest_json(result) for result in lane_results],
    }
    evidence_digest = digest_json(basis)
    output = output_paths(runtime, wave_id=wave_id, workflow_id=workflow_id, digest=evidence_digest)
    evidence_context = wave_evidence_context(
        wave_id=wave_id,
        parent_wave_id=parent_wave_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        lane_results=lane_results,
        refs=refs,
        output=output,
        evidence_digest=evidence_digest,
    )
    input_snapshots = build_input_snapshots(
        refs=refs,
        output=output,
        evidence_context=evidence_context,
    )
    phase1_staging = phase1.build_draft_staging_queue(
        runtime=runtime,
        wave_id=wave_id,
        lane_results=lane_results,
        write=write,
    )
    source_entry = {
        "source_entry_root": "source_bound_worker_brief_queue",
        "source_entry_read_at": now_iso(),
        "source_entry_digest_sha256": digest_json(bridge_queue),
        "sampled_count": len(executable_briefs),
        "sampled_files": [
            {
                "name": result.get("worker_brief_id"),
                "path": result.get("provider_invocation_ref"),
                "sha256": digest_json(result),
            }
            for result in lane_results[:8]
        ],
    }
    latest_correction = {
        "task_id": TASK_ID,
        "sha256": digest_json({"parent_wave_id": parent_wave_id, "wave_id": wave_id}),
    }
    phase1_merge = phase1.build_merge_consumer(
        runtime=runtime,
        wave_id=wave_id,
        staging_queue=phase1_staging,
        lane_results=lane_results,
        source_entry=source_entry,
        latest_correction=latest_correction,
        write=write,
    )
    phase1_spend = phase1.build_spend_ledger(
        runtime=runtime,
        wave_id=wave_id,
        lane_results=lane_results,
        write=write,
    )
    provider_materialization = provider_materialization_summary(lane_results, phase1_spend)
    staging = build_source_bound_staging(
        wave_id=wave_id,
        lane_results=lane_results,
        output=output,
        evidence_context=evidence_context,
    )
    merge = build_merge_record(
        wave_id=wave_id,
        phase1_merge=phase1_merge,
        phase1_staging=phase1_staging,
        closure_staging=staging,
        output=output,
        evidence_context=evidence_context,
    )
    fan_in = build_fan_in(
        wave_id=wave_id,
        lane_results=lane_results,
        staging=staging,
        merge=merge,
        output=output,
        evidence_context=evidence_context,
    )
    aaq = build_aaq(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        lane_results=lane_results,
        merge=merge,
        fan_in=fan_in,
        output=output,
        write=write,
        evidence_context=evidence_context,
    )
    next_frontier = build_next_frontier(
        wave_id=wave_id,
        parent_wave_id=parent_wave_id,
        aaq=aaq,
        merge=merge,
        staging=staging,
        output=output,
        evidence_context=evidence_context,
        provider_materialization=provider_materialization,
    )
    chains = build_acceptance_chains(
        lane_results=lane_results,
        refs=refs,
        output=output,
        evidence_context=evidence_context,
    )
    repair_plan = build_repair_plan(
        wave_id=wave_id,
        lane_results=lane_results,
        staging=staging,
        merge=merge,
        fan_in=fan_in,
        aaq=aaq,
        output=output,
        evidence_context=evidence_context,
        provider_materialization=provider_materialization,
    )
    independent_eval_payload = build_independent_eval_payload(
        wave_id=wave_id,
        provider_materialization=provider_materialization,
        merge=merge,
        staging=staging,
        lane_results=lane_results,
        output=output,
        evidence_context=evidence_context,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "source_batch_ids": evidence_context["source_batch_ids"],
        "worker_brief_ids": evidence_context["worker_brief_ids"],
        "primary_source_batch_id": evidence_context["primary_source_batch_id"],
        "primary_worker_brief_id": evidence_context["primary_worker_brief_id"],
        "status": "source_frontier_workerpool_closure_ready",
        "generated_at": now_iso(),
        "source_bound_worker_brief_queue_ref": refs["source_bound_worker_brief_queue"],
        "source_bound_worker_brief_queue_loaded_from_wave_ref": bridge_queue.get(
            "source_queue_loaded_from_wave_ref", ""
        ),
        "source_bound_worker_brief_queue_latest_fallback_used": bool(
            bridge_queue.get("source_queue_latest_fallback_used")
        ),
        "source_bound_worker_brief_queue_wave_id": bridge_queue.get("wave_id", ""),
        "source_bound_worker_brief_queue_source_batch_ids": bridge_queue.get(
            "source_batch_ids", []
        ),
        "source_frontier_workerbrief_bridge_wave_ref": refs[
            "source_frontier_workerbrief_bridge_wave"
        ],
        "source_bound_worker_brief_count": len(executable_briefs),
        "mode_counts": mode_counts,
        "executable_worker_briefs": executable_briefs,
        "bridge_wave_validation_passed": bridge_wave.get("validation", {}).get("passed"),
        "lane_results": lane_results,
        "staging": staging,
        "phase1_draft_staging": phase1_staging,
        "merge": merge,
        "phase1_spend_ledger": phase1_spend,
        "provider_materialization": provider_materialization,
        "fan_in": fan_in,
        "artifact_acceptance_queue": aaq,
        "next_frontier": next_frontier,
        "acceptance_chains": chains,
        "repair_plan": repair_plan,
        "independent_eval_payload": independent_eval_payload,
        "input_snapshots": input_snapshots,
        "input_refs": refs,
        "runtime_entrypoint_invocation": {
            "invoked": True,
            "invoked_by": "temporal_codex_task_workflow.source_frontier_workerpool_closure_activity"
            if invoked_by_temporal_activity
            else "services.agent_runtime.source_frontier_workerpool_closure.cli",
            "runtime_enforced": bool(invoked_by_temporal_activity),
            "runtime_enforced_scope": "seed_cortex_temporal_source_frontier_workerpool_closure_activity"
            if invoked_by_temporal_activity
            else "",
            "not_execution_controller": True,
            "not_completion_gate": True,
        },
        "wave_evidence_context": evidence_context,
        "same_wave_output_refs": evidence_context["same_wave_output_refs"],
        "evidence_digest_sha256": evidence_digest,
        "latest_alias_is_not_proof": True,
        "output_paths": output,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
    }
    payload["validation"] = build_validation(payload)
    if repair_plan.get("repair_required") is True:
        payload["status"] = "source_frontier_workerpool_closure_repair_required"
    elif payload["validation"]["passed"]:
        payload["status"] = "source_frontier_workerpool_closure_ready"
    else:
        payload["status"] = "source_frontier_workerpool_closure_blocked"
    ledger, activity = build_ledger_records(payload)
    if write:
        write_json(Path(output["latest"]), payload)
        write_json(Path(output["wave"]), payload)
        write_json(Path(output["allocation_plan_snapshot"]), input_snapshots["allocation_plan"])
        write_json(
            Path(output["provider_scheduler_snapshot"]), input_snapshots["provider_scheduler"]
        )
        write_json(
            Path(output["executable_worker_brief_queue"]),
            {
                **evidence_context,
                "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.executable_worker_brief_queue.v1",
                "status": "executable_worker_brief_queue_ready"
                if executable_briefs
                else "executable_worker_brief_queue_blocked",
                "wave_id": wave_id,
                "parent_wave_id": parent_wave_id,
                "brief_count": len(executable_briefs),
                "briefs": executable_briefs,
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
        )
        write_json(
            Path(output["lane_results"]),
            {
                **evidence_context,
                "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.lane_results.v1",
                "status": "lane_results_ready" if lane_results else "lane_results_blocked",
                "wave_id": wave_id,
                "lane_results": lane_results,
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
        )
        write_json(Path(output["staging"]), staging)
        write_json(Path(output["merge"]), merge)
        write_json(Path(output["fan_in"]), fan_in)
        write_json(Path(output["fan_in_wave_read_model"]), fan_in)
        write_json(Path(output["aaq"]), aaq)
        write_json(Path(output["next_frontier"]), next_frontier)
        write_json(Path(output["next_frontier_wave_read_model"]), next_frontier)
        write_json(Path(output["repair_plan"]), repair_plan)
        write_json(Path(output["independent_eval"]), independent_eval_payload)
        write_json(Path(output["worker_dispatch_ledger_wave"]), ledger)
        write_json(Path(output["worker_dispatch_ledger_activity"]), activity)
        write_text(Path(output["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument(
        "--wave-id", default="source-frontier-workerpool-global-closure-20260704-verify-wave"
    )
    parser.add_argument(
        "--parent-wave-id", default="source-frontier-workerpool-global-closure-20260704-verify-wave"
    )
    parser.add_argument(
        "--workflow-id", default="source-frontier-workerpool-global-closure-20260704"
    )
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--invoked-by-temporal-activity", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        wave_id=args.wave_id,
        parent_wave_id=args.parent_wave_id,
        workflow_id=args.workflow_id,
        workflow_run_id=args.workflow_run_id,
        invoked_by_temporal_activity=args.invoked_by_temporal_activity,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "sentinel": payload["sentinel"],
                "status": payload["status"],
                "wave_id": payload["wave_id"],
                "parent_wave_id": payload["parent_wave_id"],
                "source_bound_worker_brief_count": payload["source_bound_worker_brief_count"],
                "lane_result_count": len(payload["lane_results"]),
                "staged_count": payload["staging"].get("staged_count"),
                "accepted_artifact_count": payload["artifact_acceptance_queue"].get(
                    "accepted_artifact_count"
                ),
                "repair_required": payload["repair_plan"].get("repair_required"),
                "wave_ref": payload["output_paths"]["wave"],
                "worker_dispatch_ledger_wave_ref": payload["output_paths"][
                    "worker_dispatch_ledger_wave"
                ],
                "worker_dispatch_ledger_activity_ref": payload["output_paths"][
                    "worker_dispatch_ledger_activity"
                ],
                "readback_zh_ref": payload["output_paths"]["readback_zh"],
                "validation": payload["validation"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return (
        0
        if payload["validation"]["passed"]
        else 2
        if payload["repair_plan"].get("repair_required")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
