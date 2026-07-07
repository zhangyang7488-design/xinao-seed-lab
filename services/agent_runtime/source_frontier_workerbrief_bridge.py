import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(r"E:\XINAO_RESEARCH_WORKSPACES\S")

SCHEMA_VERSION = "xinao.codex_s.source_frontier_workerbrief_bridge.v1"
SENTINEL = "SENTINEL:XINAO_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = "source_frontier_workerpool_global_closure_20260704"
ROUTE_PROFILE = "seed_cortex_phase0"
ROUTING = "continue_same_task"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return stem.strip(".-") or "wave"


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
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def digest_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "schema_version": str(payload.get("schema_version") or ""),
        "status": str(payload.get("status") or ""),
        "validation_passed": validation.get("passed"),
        "completion_claim_allowed": payload.get("completion_claim_allowed"),
        "not_execution_controller": payload.get("not_execution_controller"),
    }


def output_paths(
    runtime: Path, *, wave_id: str, workflow_id: str, evidence_digest: str = ""
) -> dict[str, str]:
    state = runtime / "state" / "source_frontier_workerbrief_bridge"
    wave_stem = safe_stem(wave_id)
    workflow_stem = safe_stem(workflow_id)
    ledger_wave_dir = runtime / "state" / "worker_dispatch_ledger" / "waves" / wave_stem
    ledger_digest = evidence_digest or "pending-digest"
    return {
        "latest": str(state / "latest.json"),
        "temporal_activity_latest": str(state / "temporal_activity_latest.json"),
        "wave": str(state / "waves" / f"{wave_stem}.json"),
        "worker_brief_queue_latest": str(state / "worker_brief_queue_latest.json"),
        "mapping_latest": str(state / "mapping_latest.json"),
        "worker_dispatch_ledger_wave": str(ledger_wave_dir / f"{ledger_digest}.json"),
        "worker_dispatch_ledger_activity": str(
            runtime
            / "state"
            / "worker_dispatch_ledger"
            / "activity"
            / workflow_stem
            / f"{wave_stem}.json"
        ),
        "readback_zh": str(
            runtime / "readback" / "zh" / f"source_frontier_workerbrief_bridge_{wave_stem}.md"
        ),
    }


def runtime_ref_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state"
    return {
        "source_frontier_durable_consumer": state
        / "source_frontier_durable_consumer"
        / "latest.json",
        "source_frontier_fanin_acceptance": state
        / "source_frontier_fanin_acceptance"
        / "latest.json",
        "claim_card_staging_queue": state / "claim_card_staging_queue" / "latest.json",
        "fan_in_acceptance_queue": state / "fan_in_acceptance_queue" / "latest.json",
        "artifact_acceptance_queue": state / "artifact_acceptance_queue" / "latest.json",
        "source_ledger": state / "source_ledger" / "latest.json",
        "next_frontier_machine_actions": state / "next_frontier_machine_actions" / "latest.json",
        "loop_runtime_state": state / "loop_runtime_state" / "latest.json",
        "allocation_plan": state / "allocation_plan" / "latest.json",
        "allocation_worker_brief_queue": state
        / "allocation_plan"
        / "worker_brief_queue_latest.json",
        "worker_brief_queue": state / "worker_brief" / "latest.json",
        "modular_worker_pool": state / "modular_dynamic_worker_pool_phase1" / "latest.json",
        "modular_worker_pool_default_route": (
            state / "modular_dynamic_worker_pool_phase1" / "default_route_binding" / "latest.json"
        ),
        "modular_worker_pool_draft_staging": (
            state / "modular_dynamic_worker_pool_phase1" / "draft_staging_queue" / "latest.json"
        ),
        "modular_worker_pool_merge_consumer": (
            state / "modular_dynamic_worker_pool_phase1" / "merge_consumer" / "latest.json"
        ),
        "modular_worker_pool_spend_ledger": (
            state / "modular_dynamic_worker_pool_phase1" / "spend_ledger" / "latest.json"
        ),
        "provider_scheduler": state
        / "codex_native_provider_scheduler_phase4_20260704"
        / "latest.json",
        "scheduler_invocation_packet": state / "scheduler_invocation_packet" / "latest.json",
    }


def compact_ref(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "status": str(payload.get("status") or ""),
        "schema_version": str(payload.get("schema_version") or ""),
        "validation_passed": validation.get("passed"),
    }


def load_runtime_surfaces(runtime: Path) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    paths = runtime_ref_paths(runtime)
    return paths, {name: read_json(path) for name, path in paths.items()}


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    if value in (None, "", 0):
        return []
    return [value]


def source_package_ref(
    payloads: dict[str, dict[str, Any]], paths: dict[str, Path]
) -> dict[str, Any]:
    fanin = payloads.get("source_frontier_fanin_acceptance", {})
    package = fanin.get("source_package") if isinstance(fanin.get("source_package"), dict) else {}
    if package:
        return {
            "source_package_digest_sha256": str(package.get("source_package_digest_sha256") or ""),
            "root": str(package.get("root") or ""),
            "read_full_count": package.get("read_full_count"),
            "source_ref": str(paths["source_frontier_fanin_acceptance"]),
        }
    claim_queue = payloads.get("claim_card_staging_queue", {})
    return {
        "source_package_digest_sha256": digest_json(
            {
                "claim_card_staging_queue": claim_queue.get("claim_card_count"),
                "source_frontier_durable_consumer": payloads.get(
                    "source_frontier_durable_consumer", {}
                ).get("status"),
                "loop_runtime_state": payloads.get("loop_runtime_state", {}).get("status"),
            }
        ),
        "root": "",
        "read_full_count": 0,
        "source_ref": str(paths["claim_card_staging_queue"]),
    }


def claim_cards(payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    queue = payloads.get("claim_card_staging_queue", {})
    cards = queue.get("claim_cards")
    if isinstance(cards, list) and cards:
        return [card for card in cards if isinstance(card, dict)]
    fanin = payloads.get("source_frontier_fanin_acceptance", {})
    staging = (
        fanin.get("claim_card_staging_queue")
        if isinstance(fanin.get("claim_card_staging_queue"), dict)
        else {}
    )
    cards = staging.get("claim_cards")
    if isinstance(cards, list):
        return [card for card in cards if isinstance(card, dict)]
    return []


def claim_ref_for_index(cards: list[dict[str, Any]], index: int) -> dict[str, Any]:
    if not cards:
        return {
            "claim_card_id": "bounded-current-source-delta-claim",
            "claim_card_ref": "runtime:bounded-current-source-delta",
            "source_family": "local_runtime_delta",
            "accepted_for": "source_frontier_workerbrief_bridge",
        }
    card = cards[index % len(cards)]
    return {
        "claim_card_id": str(
            card.get("candidate_id") or card.get("claim_card_id") or f"claim-card-{index + 1}"
        ),
        "claim_card_ref": str(card.get("artifact_ref") or card.get("source_url") or ""),
        "source_family": str(card.get("source_family") or card.get("source_type") or ""),
        "accepted_for": str(card.get("accepted_for") or ""),
    }


def claim_card_source_batch_items(
    *,
    cards: list[dict[str, Any]],
    package_ref: dict[str, Any],
    claim_queue: dict[str, Any],
    paths: dict[str, Path],
) -> list[dict[str, Any]]:
    source_families = [
        str(item) for item in as_list(claim_queue.get("source_families")) if str(item).strip()
    ]
    non_local_count = int(claim_queue.get("non_local_source_family_count") or 0)
    if len(cards) < 2 and len(source_families) < 2 and non_local_count < 2:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        family = str(
            card.get("source_family") or card.get("source_type") or "claim_card_source"
        ).strip()
        if not family:
            family = "claim_card_source"
        grouped.setdefault(family, []).append(card)
    source_items: list[dict[str, Any]] = []
    for family in sorted(grouped):
        family_cards = grouped[family]
        if not family_cards:
            continue
        representative = family_cards[0]
        ids = [
            str(
                card.get("candidate_id")
                or card.get("claim_card_id")
                or card.get("source_url")
                or ""
            )
            for card in family_cards
            if str(
                card.get("candidate_id")
                or card.get("claim_card_id")
                or card.get("source_url")
                or ""
            )
        ]
        digest = digest_json(
            {
                "source_family": family,
                "claim_card_ids": ids,
                "claim_queue_wave_id": claim_queue.get("wave_id"),
            }
        )[:16]
        batch_id = f"claimcard-source-batch-{safe_stem(family)}-{digest}"
        representative_id = str(
            representative.get("candidate_id")
            or representative.get("claim_card_id")
            or (ids[0] if ids else "")
            or batch_id
        )
        source_items.append(
            {
                "source_batch_id": batch_id,
                "frontier_batch_id": batch_id,
                "source_batch_ref": str(paths["claim_card_staging_queue"]),
                "fan_in_ref": str(paths["fan_in_acceptance_queue"]),
                "aaq_ref": str(paths["artifact_acceptance_queue"]),
                "source_package_ref": package_ref,
                "claim_card_id": representative_id,
                "claim_card_ref": str(
                    representative.get("artifact_ref")
                    or representative.get("source_url")
                    or paths["claim_card_staging_queue"]
                ),
                "source_family": family,
                "source_origin": "claim_card_staging_queue.source_family_batch",
                "claim_card_ids": ids,
                "source_card_count": len(family_cards),
                "bounded_current_source_frontier_item": False,
            }
        )
    return source_items


def build_source_items(
    *, runtime: Path, paths: dict[str, Path], payloads: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_frontier = payloads.get("source_frontier_durable_consumer", {})
    wave_refs = source_frontier.get("wave_payload_refs")
    cards = claim_cards(payloads)
    package_ref = source_package_ref(payloads, paths)
    source_items: list[dict[str, Any]] = []
    if isinstance(wave_refs, list):
        for index, ref in enumerate(wave_refs):
            if not isinstance(ref, dict):
                continue
            batch_id = str(ref.get("batch_id") or ref.get("wave_id") or "").strip()
            if not batch_id:
                continue
            claim = claim_ref_for_index(cards, index)
            source_items.append(
                {
                    "source_batch_id": batch_id,
                    "frontier_batch_id": batch_id,
                    "source_batch_ref": str(ref.get("latest_ref") or ""),
                    "fan_in_ref": str(ref.get("fan_in_ref") or paths["fan_in_acceptance_queue"]),
                    "aaq_ref": str(ref.get("aaq_ref") or paths["artifact_acceptance_queue"]),
                    "source_package_ref": package_ref,
                    "claim_card_id": claim["claim_card_id"],
                    "claim_card_ref": claim["claim_card_ref"],
                    "source_family": claim["source_family"],
                    "source_origin": "source_frontier_durable_consumer.wave_payload_refs",
                    "bounded_current_source_frontier_item": False,
                }
            )
    remaining = [
        str(item)
        for item in as_list(source_frontier.get("remaining_batch_ids"))
        if str(item).strip()
    ]
    if not source_items and remaining:
        for index, batch_id in enumerate(remaining):
            claim = claim_ref_for_index(cards, index)
            source_items.append(
                {
                    "source_batch_id": batch_id,
                    "frontier_batch_id": batch_id,
                    "source_batch_ref": str(paths["source_frontier_durable_consumer"]),
                    "fan_in_ref": str(paths["fan_in_acceptance_queue"]),
                    "aaq_ref": str(paths["artifact_acceptance_queue"]),
                    "source_package_ref": package_ref,
                    "claim_card_id": claim["claim_card_id"],
                    "claim_card_ref": claim["claim_card_ref"],
                    "source_family": claim["source_family"],
                    "source_origin": "source_frontier_durable_consumer.remaining_batch_ids",
                    "bounded_current_source_frontier_item": False,
                }
            )
    if source_items:
        return source_items, {"generated_bounded_item": False, "source_frontier_empty": False}

    claim_queue = payloads.get("claim_card_staging_queue", {})
    claim_batch_items = claim_card_source_batch_items(
        cards=cards,
        package_ref=package_ref,
        claim_queue=claim_queue,
        paths=paths,
    )
    if claim_batch_items:
        return claim_batch_items, {
            "generated_bounded_item": False,
            "source_frontier_empty": False,
            "source_origin": "claim_card_staging_queue.source_family_batch",
            "claim_card_batch_backed": True,
            "claim_card_count": len(cards),
            "source_family_count": len(
                {
                    str(item.get("source_family") or "")
                    for item in cards
                    if isinstance(item, dict) and str(item.get("source_family") or "")
                }
            ),
        }

    loop = payloads.get("loop_runtime_state", {})
    next_actions = payloads.get("next_frontier_machine_actions", {})
    next_frontier = as_list(loop.get("next_frontier")) or as_list(next_actions.get("next_frontier"))
    claim = claim_ref_for_index(cards, 0)
    package_ref = source_package_ref(payloads, paths)
    basis = {
        "source_frontier_status": source_frontier.get("status"),
        "consumed_batch_ids": source_frontier.get("consumed_batch_ids"),
        "remaining_batch_ids": source_frontier.get("remaining_batch_ids"),
        "loop_next_frontier": next_frontier[:3],
        "next_frontier_actions_status": next_actions.get("status"),
        "claim_card_id": claim["claim_card_id"],
        "source_package_digest_sha256": package_ref.get("source_package_digest_sha256"),
    }
    return [], {
        "status": "empty_frontier_noop",
        "generated_bounded_item": False,
        "source_frontier_empty": True,
        "worker_brief_binding_count": 0,
        "source_digest_sha256": str(
            package_ref.get("source_package_digest_sha256") or digest_json(basis)
        ),
        "noop_reason": (
            "source frontier has no current wave payload refs or remaining batches; "
            "bridge must not synthesize bounded-current-source-delta"
        ),
        "progress_ledger_decision": "empty_frontier_noop",
        "bounded_item_basis": basis,
    }


def canonical_worker_brief_queue(
    payloads: dict[str, dict[str, Any]], paths: dict[str, Path]
) -> tuple[dict[str, Any], str, str]:
    allocation_queue = payloads.get("allocation_worker_brief_queue", {})
    if isinstance(allocation_queue.get("briefs"), list) and allocation_queue.get("briefs"):
        return (
            allocation_queue,
            str(paths["allocation_worker_brief_queue"]),
            "allocation_plan.worker_brief_queue",
        )
    worker_queue = payloads.get("worker_brief_queue", {})
    if isinstance(worker_queue.get("briefs"), list) and worker_queue.get("briefs"):
        return (
            worker_queue,
            str(paths["worker_brief_queue"]),
            "modular_dynamic_worker_pool_phase1.worker_brief_queue",
        )
    return (
        {
            "schema_version": "xinao.codex_s.worker_brief_queue.v1",
            "status": "worker_brief_queue_ready",
            "brief_count": 3,
            "briefs": [
                {
                    "brief_id": "synthetic-source-bridge:brief:cheap_draft",
                    "lane_class": "cheap_draft",
                    "objective": "Draft a bounded source-frontier response through the cheap worker lane.",
                    "expected_artifact": "draft_ref",
                    "provider_candidates": [
                        "qwen_prepaid_cheap_worker",
                        "deepseek_dp",
                        "codex_exec",
                    ],
                    "worker_output_must_enter_staging": True,
                    "completion_claim_allowed": False,
                },
                {
                    "brief_id": "synthetic-source-bridge:brief:eval",
                    "lane_class": "eval",
                    "objective": "Evaluate source ClaimCard mapping before fan-in acceptance.",
                    "expected_artifact": "eval_ref",
                    "provider_candidates": ["codex_exec"],
                    "worker_output_must_enter_staging": True,
                    "completion_claim_allowed": False,
                },
                {
                    "brief_id": "synthetic-source-bridge:brief:merge_accept",
                    "lane_class": "merge_accept",
                    "objective": "Merge accepted worker output into AAQ and next frontier.",
                    "expected_artifact": "merge_ref",
                    "provider_candidates": ["codex_exec"],
                    "worker_output_must_enter_staging": True,
                    "completion_claim_allowed": False,
                },
            ],
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
        "",
        "bridge_fallback_minimal_worker_brief_queue",
    )


def provider_policy_for_brief(
    brief: dict[str, Any], payloads: dict[str, dict[str, Any]], paths: dict[str, Path]
) -> dict[str, Any]:
    route = brief.get("provider_route") if isinstance(brief.get("provider_route"), dict) else {}
    candidates = brief.get("provider_candidates")
    if not isinstance(candidates, list):
        candidates = []
    default_route = payloads.get("modular_worker_pool_default_route", {})
    provider_scheduler = payloads.get("provider_scheduler", {})
    return {
        "provider_scheduler_ref": str(paths["provider_scheduler"]),
        "worker_pool_default_route_ref": str(paths["modular_worker_pool_default_route"]),
        "preferred_provider_id": str(
            route.get("preferred_provider_id") or (candidates[0] if candidates else "")
        ),
        "provider_candidates": [str(item) for item in candidates],
        "qwen_prepaid_cheap_worker_default_first": bool(
            default_route.get("qwen_prepaid_cheap_worker_default_first") is True
            or provider_scheduler.get("qwen_prepaid_cheap_worker_default_first") is True
            or route.get("qwen_prepaid_first_required") is True
        ),
        "fallback_provider_ids": route.get("fallback_provider_ids")
        if isinstance(route.get("fallback_provider_ids"), list)
        else [],
        "provider_probe_used_as_progress": False,
        "search_is_main_task": False,
    }


def brief_id(brief: dict[str, Any], index: int) -> str:
    for key in ("brief_id", "worker_brief_id", "lane_id"):
        value = str(brief.get(key) or "").strip()
        if value:
            return value
    return f"worker-brief-{index + 1:02d}"


def build_worker_brief_bindings(
    *,
    wave_id: str,
    payloads: dict[str, dict[str, Any]],
    paths: dict[str, Path],
    source_items: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    queue, queue_ref, queue_source = canonical_worker_brief_queue(payloads, paths)
    raw_briefs = queue.get("briefs") if isinstance(queue.get("briefs"), list) else []
    worker_bindings: list[dict[str, Any]] = []
    for source_index, source_item in enumerate(source_items):
        for brief_index, brief_value in enumerate(raw_briefs):
            if not isinstance(brief_value, dict):
                continue
            original_brief_id = brief_id(brief_value, brief_index)
            worker_brief_id = f"{wave_id}:source-bound:{source_index + 1:02d}:{brief_index + 1:02d}"
            mapping_key = digest_json(
                {
                    "wave_id": wave_id,
                    "source_batch_id": source_item["source_batch_id"],
                    "original_worker_brief_id": original_brief_id,
                    "claim_card_id": source_item["claim_card_id"],
                }
            )[:24]
            fan_in_target = {
                "fan_in_ref": source_item["fan_in_ref"],
                "draft_staging_ref": str(paths["modular_worker_pool_draft_staging"]),
                "merge_consumer_ref": str(paths["modular_worker_pool_merge_consumer"]),
                "worker_output_must_enter_staging": True,
            }
            aaq_target = {
                "artifact_acceptance_queue_ref": source_item["aaq_ref"],
                "source_ledger_ref": str(paths["source_ledger"]),
                "claim_card_requires_source_ledger": True,
            }
            next_frontier_policy = {
                "next_frontier_ref": str(paths["next_frontier_machine_actions"]),
                "promotion_requires_fan_in_and_aaq": True,
                "direct_final_allowed": False,
                "completion_claim_allowed": False,
            }
            worker_bindings.append(
                {
                    "worker_brief_id": worker_brief_id,
                    "original_worker_brief_id": original_brief_id,
                    "source_batch_id": source_item["source_batch_id"],
                    "frontier_batch_id": source_item["frontier_batch_id"],
                    "claim_card_id": source_item["claim_card_id"],
                    "claim_card_ref": source_item["claim_card_ref"],
                    "source_package_ref": source_item["source_package_ref"],
                    "mapping_key": mapping_key,
                    "objective": str(
                        brief_value.get("objective")
                        or "Execute source-frontier mapped worker brief."
                    ),
                    "expected_artifact": str(brief_value.get("expected_artifact") or "staging_ref"),
                    "provider_policy": provider_policy_for_brief(brief_value, payloads, paths),
                    "fan_in_target": fan_in_target,
                    "aaq_target": aaq_target,
                    "next_frontier_policy": next_frontier_policy,
                    "source_origin": source_item.get("source_origin", ""),
                    "bounded_current_source_frontier_item": source_item.get(
                        "bounded_current_source_frontier_item"
                    )
                    is True,
                    "worker_output_must_enter_staging": True,
                    "direct_final_allowed": False,
                    "completion_claim_allowed": False,
                    "not_execution_controller": True,
                }
            )
    source_bound_queue = {
        "schema_version": "xinao.codex_s.worker_brief_queue.source_bound.v1",
        "status": "source_bound_worker_brief_queue_ready"
        if worker_bindings
        else "source_bound_worker_brief_queue_blocked",
        "wave_id": wave_id,
        "canonical_worker_brief_queue_ref": queue_ref,
        "canonical_worker_brief_queue_source": queue_source,
        "source_item_count": len(source_items),
        "source_batch_ids": sorted(
            {
                str(item.get("source_batch_id") or "")
                for item in source_items
                if isinstance(item, dict) and str(item.get("source_batch_id") or "")
            }
        ),
        "brief_count": len(worker_bindings),
        "briefs": worker_bindings,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    queue_summary = {
        "canonical_worker_brief_queue_ref": queue_ref,
        "canonical_worker_brief_queue_source": queue_source,
        "canonical_worker_brief_count": int(queue.get("brief_count") or len(raw_briefs)),
        "source_bound_worker_brief_count": len(worker_bindings),
    }
    return source_bound_queue, worker_bindings, queue_summary


def build_chain_refs(paths: dict[str, Path], payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_frontier_ref": str(paths["source_frontier_durable_consumer"]),
        "claim_card_staging_ref": str(paths["claim_card_staging_queue"]),
        "fan_in_ref": str(paths["fan_in_acceptance_queue"]),
        "aaq_ref": str(paths["artifact_acceptance_queue"]),
        "allocation_plan_ref": str(paths["allocation_plan"]),
        "allocation_worker_brief_queue_ref": str(paths["allocation_worker_brief_queue"]),
        "provider_scheduler_ref": str(paths["provider_scheduler"]),
        "worker_pool_ref": str(paths["modular_worker_pool"]),
        "worker_pool_worker_brief_queue_ref": str(paths["worker_brief_queue"]),
        "draft_staging_ref": str(paths["modular_worker_pool_draft_staging"]),
        "merge_consumer_ref": str(paths["modular_worker_pool_merge_consumer"]),
        "spend_ledger_ref": str(paths["modular_worker_pool_spend_ledger"]),
        "next_frontier_ref": str(paths["next_frontier_machine_actions"]),
        "worker_pool_status": str(payloads.get("modular_worker_pool", {}).get("status") or ""),
        "worker_pool_runtime_enforced": payloads.get("modular_worker_pool", {}).get(
            "runtime_enforced"
        ),
        "worker_pool_adoption_state": str(
            payloads.get("modular_worker_pool", {}).get("adoption_state") or ""
        ),
    }


def required_mapping_fields_present(mapping: dict[str, Any]) -> bool:
    required = [
        "worker_brief_id",
        "source_batch_id",
        "frontier_batch_id",
        "claim_card_id",
        "claim_card_ref",
        "source_package_ref",
        "mapping_key",
        "objective",
        "expected_artifact",
        "provider_policy",
        "fan_in_target",
        "aaq_target",
        "next_frontier_policy",
    ]
    return all(key in mapping and mapping.get(key) not in (None, "") for key in required)


def build_validation(payload: dict[str, Any]) -> dict[str, Any]:
    mappings = (
        payload.get("worker_brief_bindings")
        if isinstance(payload.get("worker_brief_bindings"), list)
        else []
    )
    source_items = (
        payload.get("source_frontier_items")
        if isinstance(payload.get("source_frontier_items"), list)
        else []
    )
    chain = payload.get("chain_refs") if isinstance(payload.get("chain_refs"), dict) else {}
    output = payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}
    source_delta = (
        payload.get("source_frontier_delta")
        if isinstance(payload.get("source_frontier_delta"), dict)
        else {}
    )
    empty_frontier_noop = source_delta.get("status") == "empty_frontier_noop"
    checks = {
        "source_frontier_to_workerbrief_binding": payload.get(
            "source_frontier_to_workerbrief_binding"
        )
        is True,
        "not_new_control_plane": payload.get("not_new_control_plane") is True,
        "source_items_present": len(source_items) >= 1 or empty_frontier_noop,
        "worker_brief_bindings_present": len(mappings) >= 1 or empty_frontier_noop,
        "required_mapping_fields_present": all(
            required_mapping_fields_present(mapping)
            for mapping in mappings
            if isinstance(mapping, dict)
        ),
        "provider_policy_bound": all(
            isinstance(mapping.get("provider_policy"), dict)
            and bool(mapping["provider_policy"].get("provider_scheduler_ref"))
            for mapping in mappings
            if isinstance(mapping, dict)
        ),
        "fan_in_aaq_next_frontier_bound": bool(chain.get("fan_in_ref"))
        and bool(chain.get("aaq_ref"))
        and bool(chain.get("next_frontier_ref")),
        "canonical_worker_brief_queue_bound": bool(
            payload.get("worker_brief_queue_summary", {}).get("canonical_worker_brief_queue_ref")
        ),
        "worker_pool_evidence_bound": bool(chain.get("worker_pool_ref")),
        "immutable_wave_ledger_ref_declared": bool(output.get("worker_dispatch_ledger_wave")),
        "activity_ledger_ref_declared": bool(output.get("worker_dispatch_ledger_activity")),
        "empty_frontier_does_not_generate_bounded_item": (
            source_delta.get("source_frontier_empty") is not True
            or source_delta.get("generated_bounded_item") is False
        ),
        "latest_alias_not_proof": payload.get("latest_alias_is_not_proof") is True,
        "completion_claim_disallowed": payload.get("completion_claim_allowed") is False,
        "not_execution_controller": payload.get("not_execution_controller") is True,
    }
    return {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()}


def render_readback(payload: dict[str, Any]) -> str:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    bridge = (
        payload.get("worker_brief_queue_summary")
        if isinstance(payload.get("worker_brief_queue_summary"), dict)
        else {}
    )
    output = payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}
    return "\n".join(
        [
            "# source frontier -> WorkerBrief bridge readback",
            "",
            SENTINEL,
            "",
            f"- status: `{payload.get('status')}`",
            f"- wave_id: `{payload.get('wave_id')}`",
            f"- workflow_id: `{payload.get('workflow_id')}`",
            f"- source_item_count: {payload.get('source_item_count')}",
            f"- source_bound_worker_brief_count: {bridge.get('source_bound_worker_brief_count')}",
            f"- generated_bounded_item: {payload.get('source_frontier_delta', {}).get('generated_bounded_item')}",
            f"- canonical_worker_brief_queue_ref: `{bridge.get('canonical_worker_brief_queue_ref')}`",
            f"- worker_dispatch_ledger_wave: `{output.get('worker_dispatch_ledger_wave')}`",
            f"- worker_dispatch_ledger_activity: `{output.get('worker_dispatch_ledger_activity')}`",
            f"- validation_passed: {validation.get('passed')}",
            "",
            "人话：这一步只做薄绑定，把 source frontier/ClaimCard/source refs 映射进 WorkerBrief 输入；",
            "它不是新的调度器，也不是完成门。worker 输出仍然必须进 staging、FanIn、AAQ、next_frontier。",
            "latest 只是方便入口；本次证明看 wave/activity ledger 里的不可变证据。",
            "",
            SENTINEL,
            "",
        ]
    )


def build_ledger_records(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    output = payload["output_paths"]
    basis = {
        "schema_version": payload["schema_version"],
        "wave_id": payload["wave_id"],
        "workflow_id": payload["workflow_id"],
        "source_frontier_items": payload["source_frontier_items"],
        "worker_brief_bindings": payload["worker_brief_bindings"],
        "chain_refs": payload["chain_refs"],
        "worker_pool_existing_real_wave_evidence_reused": payload[
            "worker_pool_existing_real_wave_evidence_reused"
        ],
    }
    digest = payload["evidence_digest_sha256"]
    ledger_record = {
        "schema_version": "xinao.codex_s.worker_dispatch_ledger.source_frontier_workerbrief_wave.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": payload["wave_id"],
        "workflow_id": payload["workflow_id"],
        "status": "source_frontier_workerbrief_bridge_wave_recorded",
        "generated_at": payload["generated_at"],
        "immutable_wave_evidence": True,
        "latest_alias_is_not_proof": True,
        "source_frontier_workerbrief_bridge_ref": output["wave"],
        "source_bound_worker_brief_queue_ref": output["worker_brief_queue_latest"],
        "evidence_digest_sha256": digest,
        "digest_basis": basis,
        "source_item_count": payload["source_item_count"],
        "worker_brief_binding_count": payload["worker_brief_binding_count"],
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    activity_record = {
        "schema_version": "xinao.codex_s.worker_dispatch_ledger.activity_source_frontier_workerbrief_bridge.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "workflow_id": payload["workflow_id"],
        "wave_id": payload["wave_id"],
        "activity": "source_frontier_workerbrief_bridge",
        "status": "activity_wave_recorded",
        "generated_at": payload["generated_at"],
        "immutable_wave_evidence_ref": output["worker_dispatch_ledger_wave"],
        "source_frontier_workerbrief_bridge_ref": output["wave"],
        "evidence_digest_sha256": digest,
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    return ledger_record, activity_record


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "source-frontier-workerpool-global-closure-20260704-wave-01",
    workflow_id: str = "source-frontier-workerpool-global-closure-20260704",
    invoked_by_temporal_activity: bool = False,
    activity_context: dict[str, Any] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths, payloads = load_runtime_surfaces(runtime)
    source_items, source_delta = build_source_items(runtime=runtime, paths=paths, payloads=payloads)
    source_bound_queue, mappings, queue_summary = build_worker_brief_bindings(
        wave_id=wave_id,
        payloads=payloads,
        paths=paths,
        source_items=source_items,
    )
    chain_refs = build_chain_refs(paths, payloads)
    evidence_basis = {
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "source_frontier_items": source_items,
        "worker_brief_bindings": mappings,
        "chain_refs": chain_refs,
    }
    evidence_digest = digest_json(evidence_basis)
    output = output_paths(
        runtime, wave_id=wave_id, workflow_id=workflow_id, evidence_digest=evidence_digest
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "status": "source_frontier_workerbrief_bridge_ready",
        "generated_at": now_iso(),
        "repo_root": str(repo),
        "source_frontier_to_workerbrief_binding": True,
        "thin_binding_only": True,
        "not_new_control_plane": True,
        "not_scheduler": True,
        "allocation_plan_is_canonical_lane_envelope": True,
        "source_frontier_items": source_items,
        "source_item_count": len(source_items),
        "source_frontier_delta": source_delta,
        "worker_brief_queue_summary": queue_summary,
        "source_bound_worker_brief_queue": source_bound_queue,
        "worker_brief_bindings": mappings,
        "worker_brief_binding_count": len(mappings),
        "chain_refs": chain_refs,
        "input_refs": {
            name: compact_ref(path, payloads.get(name, {})) for name, path in paths.items()
        },
        "runtime_entrypoint_invocation": {
            "invoked": True,
            "invoked_by": "temporal_codex_task_workflow.source_frontier_workerbrief_bridge_activity"
            if invoked_by_temporal_activity
            else "services.agent_runtime.source_frontier_workerbrief_bridge.cli",
            "runtime_enforced": bool(invoked_by_temporal_activity),
            "runtime_enforced_scope": "seed_cortex_temporal_source_frontier_workerbrief_bridge_activity"
            if invoked_by_temporal_activity
            else "",
            "not_execution_controller": True,
            "not_completion_gate": True,
        },
        "activity_context": activity_context or {},
        "worker_pool_existing_real_wave_evidence_reused": True,
        "worker_pool_reinvoke_performed_by_bridge": False,
        "bridge_wave_invocation_performed": True,
        "immutable_wave_evidence": True,
        "latest_alias_is_not_proof": True,
        "evidence_digest_sha256": evidence_digest,
        "output_paths": output,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
    }
    if source_delta.get("status") == "empty_frontier_noop":
        from services.agent_runtime import progress_self_evolution

        progress_bundle = progress_self_evolution.record_progress_bundle(
            runtime_root=runtime,
            wave_id=wave_id,
            source_digest=str(source_delta.get("source_digest_sha256") or evidence_digest),
            source_theme_id="source_frontier_workerbrief_bridge.empty_frontier_noop",
            input_count=0,
            mapped_count=0,
            artifact_delta_count=0,
            aaq_accepted_delta=0,
            default_invoke_delta=0,
            named_blocker_delta=0,
            claimcard_delta=0,
            readback_delta=1,
            synthetic_item_used=False,
            source_frontier_empty=True,
            next_frontier_real_work_count=0,
            next_frontier_self_loop_count=len(
                as_list(payloads.get("loop_runtime_state", {}).get("next_frontier"))
                or as_list(payloads.get("next_frontier_machine_actions", {}).get("next_frontier"))
            ),
            feedback_source_refs=[
                str(paths["source_frontier_durable_consumer"]),
                str(paths["source_frontier_fanin_acceptance"]),
                str(paths["claim_card_staging_queue"]),
            ],
            no_progress_reason="empty_frontier_noop_no_source_batches",
            write=write,
        )
        payload["progress_self_evolution"] = progress_bundle
        payload["strategy_mutation_ref"] = progress_bundle.get("output_paths", {}).get(
            "strategy_latest", ""
        )
    payload["validation"] = build_validation(payload)
    payload["status"] = (
        "source_frontier_workerbrief_bridge_ready"
        if payload["validation"]["passed"]
        else "source_frontier_workerbrief_bridge_blocked"
    )
    if write:
        existing_wave = read_json(Path(output["wave"]))
        existing_digest = str(existing_wave.get("evidence_digest_sha256") or "")
        if (
            existing_wave.get("schema_version") == SCHEMA_VERSION
            and existing_wave.get("wave_id") == wave_id
            and existing_digest
            and existing_digest != evidence_digest
        ):
            conflict_path = (
                runtime
                / "state"
                / "source_frontier_workerbrief_bridge"
                / "immutable_wave_conflicts"
                / safe_stem(wave_id)
                / f"{evidence_digest}.json"
            )
            write_json(
                conflict_path,
                {
                    "schema_version": "xinao.codex_s.source_frontier_workerbrief_bridge.immutable_conflict.v1",
                    "sentinel": SENTINEL,
                    "work_id": WORK_ID,
                    "task_id": TASK_ID,
                    "status": "immutable_wave_conflict_requeue_required",
                    "wave_id": wave_id,
                    "workflow_id": workflow_id,
                    "existing_wave_ref": output["wave"],
                    "existing_evidence_digest_sha256": existing_digest,
                    "attempted_evidence_digest_sha256": evidence_digest,
                    "attempted_source_batch_ids": sorted(
                        {
                            str(item.get("source_batch_id") or "")
                            for item in mappings
                            if isinstance(item, dict) and str(item.get("source_batch_id") or "")
                        }
                    ),
                    "repair_plan": {
                        "repair_required": True,
                        "fixable": True,
                        "dispatch_to": "RootIntentLoop / S Default Dynamic Loop",
                        "unblock_action": "requeue_source_frontier_workerbrief_bridge_with_new_continuation_wave_id",
                        "report_substitute_allowed": False,
                    },
                    "latest_alias_is_not_proof": True,
                    "completion_claim_allowed": False,
                    "not_execution_controller": True,
                    "generated_at": now_iso(),
                },
            )
            return {
                **existing_wave,
                "immutable_wave_reused_on_digest_conflict": True,
                "immutable_conflict_ref": str(conflict_path),
                "attempted_evidence_digest_sha256": evidence_digest,
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            }
    ledger_record, activity_record = build_ledger_records(payload)
    if write:
        write_json(Path(output["latest"]), payload)
        write_json(Path(output["wave"]), payload)
        write_json(Path(output["worker_brief_queue_latest"]), source_bound_queue)
        write_json(
            Path(output["mapping_latest"]),
            {
                "schema_version": "xinao.codex_s.source_frontier_workerbrief_bridge.mapping.v1",
                "status": "source_frontier_workerbrief_mapping_ready",
                "wave_id": wave_id,
                "workflow_id": workflow_id,
                "worker_brief_bindings": mappings,
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
        )
        write_json(Path(output["worker_dispatch_ledger_wave"]), ledger_record)
        write_json(Path(output["worker_dispatch_ledger_activity"]), activity_record)
        if invoked_by_temporal_activity:
            write_json(Path(output["temporal_activity_latest"]), payload)
        write_text(Path(output["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument(
        "--wave-id", default="source-frontier-workerpool-global-closure-20260704-wave-01"
    )
    parser.add_argument(
        "--workflow-id", default="source-frontier-workerpool-global-closure-20260704"
    )
    parser.add_argument("--invoked-by-temporal-activity", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        wave_id=args.wave_id,
        workflow_id=args.workflow_id,
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
                "workflow_id": payload["workflow_id"],
                "source_item_count": payload["source_item_count"],
                "worker_brief_binding_count": payload["worker_brief_binding_count"],
                "latest_ref": payload["output_paths"]["latest"],
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
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
