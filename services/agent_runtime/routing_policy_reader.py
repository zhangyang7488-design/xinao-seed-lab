"""Read the D-runtime policy while enforcing Grok-only model-worker routing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME

SCHEMA_VERSION = "xinao.routing_policy_reader.v1"
SENTINEL = "SENTINEL:XINAO_ROUTING_POLICY_READER_V1"
DEFAULT_POLICY_PATH = DEFAULT_RUNTIME / "agent_runtime" / "routing_policy.json"

PRO_REVIEW_ROUTE_ROLE = "grok_fanin_validation"
DEFAULT_DRAFT_ROUTE_ROLE = "default_background_worker"
DEFAULT_DRAFT_WORKER = "grok"
DEFAULT_PRO_REVIEW_MODEL = "grok-4.5"
DEFAULT_CLOUD_DRAFT_MODEL = "grok-composer-2.5-fast"
GROK_PROVIDER_ID = "grok_acpx_headless"

TIER_CHEAP_DRAFT = "tier_cheap_draft"
TIER_STRONG_REVIEW = "tier_strong_review"

CLOUD_DRAFT_MODEL_CANDIDATES = (
    "grok-composer-2.5-fast",
    "grok-4.5",
    "grok",
)
LOCAL_MODEL_MARKERS = ("ollama/", "qwen-local", "localhost:11434", ":8b")
PARALLEL_SEMANTIC_BARRIER = "barrier"
PARALLEL_SEMANTIC_ROLLING = "rolling"
VALID_PARALLEL_SEMANTICS = {PARALLEL_SEMANTIC_BARRIER, PARALLEL_SEMANTIC_ROLLING}

DYNAMIC_LOOP_SHAPE_SENTINEL = (
    "SENTINEL:XINAO_EXTERNAL_MATURE_DYNAMIC_LOOP_AND_SMART_ROUTING_SHAPE_V1"
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_routing_policy(*, runtime_root: str | Path = DEFAULT_RUNTIME) -> dict[str, Any]:
    runtime = Path(runtime_root)
    policy_path = runtime / "agent_runtime" / "routing_policy.json"
    policy = _read_json(policy_path)
    raw_routes = policy.get("routes") if isinstance(policy.get("routes"), list) else []
    routes = [
        item
        for item in raw_routes
        if isinstance(item, dict)
        and (
            str(item.get("provider_id") or "") == GROK_PROVIDER_ID
            or str(item.get("target") or "").lower() == "grok"
        )
    ]
    frozen_routes = [item for item in raw_routes if item not in routes]
    return {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "policy_path": str(policy_path),
        "policy_present": policy_path.is_file(),
        "policy_version": str(policy.get("policy_version") or ""),
        "model_worker_policy": "grok_only",
        "allowed_provider_ids": [GROK_PROVIDER_ID],
        "default_draft_worker": DEFAULT_DRAFT_WORKER,
        "default_draft_model": str(
            next(
                (
                    item.get("preferred_model")
                    for item in routes
                    if item.get("route_role") == DEFAULT_DRAFT_ROUTE_ROLE
                    and item.get("preferred_model")
                ),
                DEFAULT_CLOUD_DRAFT_MODEL,
            )
        ),
        "pro_review_after_draft": str(
            policy.get("pro_review_after_draft") or DEFAULT_PRO_REVIEW_MODEL
        ),
        "routes": routes,
        "frozen_non_grok_routes": frozen_routes,
        "route_by_role": {
            str(item.get("route_role") or ""): item
            for item in routes
            if isinstance(item, dict) and item.get("route_role")
        },
        "route_by_target": {
            str(item.get("target") or ""): item
            for item in routes
            if isinstance(item, dict) and item.get("target")
        },
    }


def pro_review_model(*, runtime_root: str | Path = DEFAULT_RUNTIME) -> str:
    ctx = load_routing_policy(runtime_root=runtime_root)
    route = ctx.get("route_by_role", {}).get(PRO_REVIEW_ROUTE_ROLE, {})
    if isinstance(route, dict) and route.get("preferred_model"):
        return str(route["preferred_model"])
    return str(ctx.get("pro_review_after_draft") or DEFAULT_PRO_REVIEW_MODEL)


def draft_worker_target(*, runtime_root: str | Path = DEFAULT_RUNTIME) -> str:
    ctx = load_routing_policy(runtime_root=runtime_root)
    route = ctx.get("route_by_role", {}).get(DEFAULT_DRAFT_ROUTE_ROLE, {})
    if isinstance(route, dict) and route.get("target"):
        return str(route["target"])
    return str(ctx.get("default_draft_worker") or DEFAULT_DRAFT_WORKER)


def is_local_fallback_model(model: str) -> bool:
    """True when model resolves to local ollama — must not be labeled cloud qwen default."""
    lower = str(model or "").strip().lower()
    if not lower:
        return False
    return any(marker in lower for marker in LOCAL_MODEL_MARKERS)


def is_cloud_draft_model(model: str) -> bool:
    lower = str(model or "").strip().lower()
    if not lower or is_local_fallback_model(lower):
        return False
    if lower in {c.lower() for c in CLOUD_DRAFT_MODEL_CANDIDATES}:
        return True
    return lower.startswith("grok")


def resolve_cloud_draft_model(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    candidate: str = "",
) -> str:
    """Static role binding: draft tier resolves to cloud qwen logical name (not ollama)."""
    ctx = load_routing_policy(runtime_root=runtime_root)
    route = ctx.get("route_by_role", {}).get(DEFAULT_DRAFT_ROUTE_ROLE, {})
    candidates: list[str] = []
    if candidate.strip():
        candidates.append(candidate.strip())
    if isinstance(route, dict):
        if route.get("preferred_model"):
            candidates.append(str(route["preferred_model"]))
        tier = route.get("tier") or route.get("model_tier")
        if tier == TIER_CHEAP_DRAFT and route.get("preferred_model"):
            candidates.append(str(route["preferred_model"]))
    policy_model = str(ctx.get("default_draft_model") or "")
    if policy_model:
        candidates.append(policy_model)
    candidates.extend(CLOUD_DRAFT_MODEL_CANDIDATES)
    seen: set[str] = set()
    for raw in candidates:
        model = str(raw or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        if is_cloud_draft_model(model):
            return model
    return DEFAULT_CLOUD_DRAFT_MODEL


def draft_model(*, runtime_root: str | Path = DEFAULT_RUNTIME, candidate: str = "") -> str:
    return resolve_cloud_draft_model(runtime_root=runtime_root, candidate=candidate)


def draft_tier() -> str:
    return TIER_CHEAP_DRAFT


def review_tier() -> str:
    return TIER_STRONG_REVIEW


def resolve_parallel_semantic(params: dict[str, Any] | None = None) -> str:
    """Barrier = scatter-gather join; rolling = as-completed verify + reschedule."""
    raw = str((params or {}).get("parallel_semantic") or PARALLEL_SEMANTIC_BARRIER).strip().lower()
    if raw in VALID_PARALLEL_SEMANTICS:
        return raw
    return PARALLEL_SEMANTIC_BARRIER


def build_tier_used(*, draft: str = "", review: str = "") -> dict[str, str]:
    payload = {
        "draft": draft or draft_tier(),
        "review": review or review_tier(),
    }
    return payload


def build_dynamic_loop_shape_metadata(
    result: dict[str, Any],
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """External mature dynamic-loop shape evidence — minimal weld on bus result."""
    draft = str(result.get("draft_model") or result.get("worker_lane_model") or "")
    review = str(result.get("review_model") or result.get("pro_review_model") or "")
    parallel_semantic = str(result.get("parallel_semantic") or resolve_parallel_semantic(params))
    tier_used = result.get("tier_used")
    if not isinstance(tier_used, dict):
        tier_used = build_tier_used()
    lane_models = result.get("parallel_lane_models")
    if not isinstance(lane_models, list):
        lane_models = []
    return {
        "schema_version": "xinao.external_mature.dynamic_loop_shape.v1",
        "sentinel": DYNAMIC_LOOP_SHAPE_SENTINEL,
        "draft_model": draft,
        "review_model": review,
        "parallel_semantic": parallel_semantic,
        "tier_used": tier_used,
        "parallel_succeeded": int(result.get("parallel_succeeded") or 0),
        "parallel_lane_models": lane_models,
        "draft_cloud_not_ollama": bool(draft) and is_cloud_draft_model(draft),
        "review_strong_tier": tier_used.get("review") == TIER_STRONG_REVIEW,
        "shape_ref": "外部成熟_动态轮回与智能派模_完整形状_20260710.txt",
    }
