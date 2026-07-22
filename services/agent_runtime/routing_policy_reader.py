"""Read the D-runtime worker policy without hard-coding a provider default.

The policy carries a replaceable stable preference and candidate admission.
Current task, health and capacity facts still determine the exact route.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from services.agent_runtime.quota_capacity_adapter import capacity_by_provider_from_quota
from services.agent_runtime.supervisor_worker_selector import select_supervisor_worker
from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME

SCHEMA_VERSION = "xinao.routing_policy_reader.v1"
SENTINEL = "SENTINEL:XINAO_ROUTING_POLICY_READER_V1"
DEFAULT_POLICY_PATH = DEFAULT_RUNTIME / "agent_runtime" / "routing_policy.json"

PRO_REVIEW_ROUTE_ROLE = "grok_fanin_validation"
DEFAULT_DRAFT_ROUTE_ROLE = "default_background_worker"
DEFAULT_DRAFT_WORKER = "caller_resolved"
DEFAULT_PRO_REVIEW_MODEL = ""
DEFAULT_CLOUD_DRAFT_MODEL = ""
GROK_PROVIDER_ID = "grok_acpx_headless"
CODEX_SUBAGENT_PROVIDER_ID = "codex_subagent"
DEFAULT_MODEL_WORKER_POLICY = "positive_benefit_dynamic"
DEFAULT_ALLOWED_PROVIDER_IDS = (GROK_PROVIDER_ID, CODEX_SUBAGENT_PROVIDER_ID)

TIER_CHEAP_DRAFT = "tier_cheap_draft"
TIER_STRONG_REVIEW = "tier_strong_review"

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
    all_routes = [
        dict(item)
        for item in raw_routes
        if isinstance(item, dict)
        and (str(item.get("provider_id") or "").strip() or str(item.get("target") or "").strip())
    ]
    configured_allowed = policy.get("allowed_provider_ids")
    if isinstance(configured_allowed, list):
        allowed_provider_ids = list(
            dict.fromkeys(str(value).strip() for value in configured_allowed if str(value).strip())
        )
    else:
        allowed_provider_ids = list(
            dict.fromkeys(
                str(item.get("provider_id") or "").strip()
                for item in all_routes
                if str(item.get("provider_id") or "").strip()
            )
        )
    frozen_values = policy.get("frozen_workers")
    frozen_workers = {
        str(value).strip()
        for value in (frozen_values if isinstance(frozen_values, list) else [])
        if str(value).strip()
    }

    def is_active(item: dict[str, Any]) -> bool:
        provider_id = str(item.get("provider_id") or "").strip()
        identities = {
            provider_id,
            str(item.get("target") or "").strip(),
            str(item.get("worker_id") or "").strip(),
        }
        return bool(provider_id in allowed_provider_ids and not (identities & frozen_workers))

    routes = [item for item in all_routes if is_active(item)]
    inactive_routes = [item for item in all_routes if not is_active(item)]
    return {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "policy_path": str(policy_path),
        "policy_present": policy_path.is_file(),
        "policy_version": str(policy.get("policy_version") or ""),
        "model_worker_policy": str(
            policy.get("model_worker_policy") or DEFAULT_MODEL_WORKER_POLICY
        ),
        "default_strategy": str(policy.get("default_strategy") or ""),
        "stable_preferred_provider_id": str(
            policy.get("stable_preferred_provider_id")
            or policy.get("preferred_provider_when_benefit_close")
            or ""
        ),
        "provider_preference_scope": str(policy.get("provider_preference_scope") or ""),
        "worker_output_authority": str(policy.get("worker_output_authority") or ""),
        "quota_policy": str(policy.get("quota_policy") or ""),
        "codex_inner_optimization_policy": dict(
            policy.get("codex_inner_optimization_policy")
            if isinstance(policy.get("codex_inner_optimization_policy"), Mapping)
            else {}
        ),
        "quota_capacity_bindings": dict(
            policy.get("quota_capacity_bindings")
            if isinstance(policy.get("quota_capacity_bindings"), Mapping)
            else {}
        ),
        "allowed_provider_ids": allowed_provider_ids,
        "frozen_workers": sorted(frozen_workers),
        "default_draft_worker": str(policy.get("default_draft_worker") or DEFAULT_DRAFT_WORKER),
        "default_draft_model": str(
            next(
                (
                    item.get("preferred_model")
                    for item in routes
                    if item.get("route_role") == DEFAULT_DRAFT_ROUTE_ROLE
                    and item.get("preferred_model")
                ),
                "",
            )
        ),
        "pro_review_after_draft": str(
            policy.get("pro_review_after_draft") or DEFAULT_PRO_REVIEW_MODEL
        ),
        "routes": routes,
        "all_routes": all_routes,
        "inactive_routes": inactive_routes,
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


def _policy_candidate_identities(ctx: Mapping[str, Any]) -> set[tuple[str, str, str, str]]:
    identities: set[tuple[str, str, str, str]] = set()
    for route in ctx.get("routes", []):
        if not isinstance(route, Mapping):
            continue
        identity = (
            str(route.get("provider_id") or "").strip(),
            str(route.get("profile_ref") or "").strip(),
            str(route.get("model_id") or route.get("preferred_model") or "").strip(),
            str(route.get("transport_id") or "").strip(),
        )
        if all(identity):
            identities.add(identity)
    return identities


def resolve_supervisor_worker_decision(
    request: Mapping[str, Any],
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
) -> dict[str, Any]:
    """Bind one caller-observed decision to exact active policy candidates.

    The caller owns health, benefit and context facts.  The D-runtime policy
    owns candidate admission.  This bridge performs no probes and invents no
    provider, profile, model or transport fallback.
    """

    if not isinstance(request, Mapping):
        raise TypeError("supervisor routing request must be an object")
    ctx = load_routing_policy(runtime_root=runtime_root)
    if ctx.get("policy_present") is not True:
        raise ValueError("supervisor routing policy is required")
    policy_path = Path(str(ctx["policy_path"]))
    policy_raw = policy_path.read_bytes()
    policy_identities = _policy_candidate_identities(ctx)
    raw_candidates = request.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("supervisor routing requires non-empty exact candidates")
    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_candidates):
        if not isinstance(raw, Mapping):
            raise TypeError(f"supervisor routing candidate {index} must be an object")
        candidate = dict(raw)
        identity = candidate.get("identity")
        identity_value = identity if isinstance(identity, Mapping) else candidate
        exact = (
            str(identity_value.get("provider_id") or "").strip(),
            str(identity_value.get("profile_ref") or "").strip(),
            str(identity_value.get("model_id") or "").strip(),
            str(identity_value.get("transport_id") or "").strip(),
        )
        declared_active = exact in policy_identities
        if candidate.get("declared_active") is not declared_active:
            raise ValueError(
                "caller declared_active disagrees with exact routing policy admission: "
                f"candidate={exact}, policy_active={declared_active}"
            )
        candidates.append(candidate)
    explicit_capacity = request.get("capacity_by_provider")
    quota_result = request.get("quota_result")
    if explicit_capacity is not None and quota_result is not None:
        raise ValueError("provide capacity_by_provider or quota_result, not both")
    capacity_by_provider = explicit_capacity
    if quota_result is not None:
        if not isinstance(quota_result, Mapping):
            raise TypeError("quota_result must be an object")
        capacity_by_provider = capacity_by_provider_from_quota(
            quota_result,
            ctx.get("quota_capacity_bindings", {}),
        )

    work_class = str(request.get("work_class") or "").strip()
    high_value_audit = work_class == "high_value_audit"
    audit_role = str(request.get("audit_role") or "").strip().lower()
    if high_value_audit and audit_role not in {"cognitive_review", "independent_validation"}:
        raise ValueError(
            "high_value_audit requires audit_role=cognitive_review or independent_validation"
        )
    direct_tool_required = high_value_audit and audit_role == "independent_validation"
    evidence_access_required = (
        True
        if high_value_audit
        else request.get("evidence_access_required", False)
    )
    direct_tool_access_required = (
        True
        if direct_tool_required
        else request.get("direct_tool_access_required", False)
    )
    decision = select_supervisor_worker(
        candidates,
        task_separable=request.get("task_separable"),
        supervisor_choice=request.get("supervisor_choice"),
        context_inheritance_required=request.get("context_inheritance_required", False),
        evidence_access_required=evidence_access_required,
        direct_tool_access_required=direct_tool_access_required,
        stable_preferred_provider_id=str(
            request.get("stable_preferred_provider_id")
            or ctx.get("stable_preferred_provider_id")
            or ""
        ),
        capacity_by_provider=capacity_by_provider,
    )
    receipt = {
        **decision,
        "schema_version": "xinao.supervisor_worker_decision_receipt.v1",
        "policy_ref": str(policy_path),
        "policy_sha256": hashlib.sha256(policy_raw).hexdigest(),
        "policy_version": str(ctx.get("policy_version") or ""),
        "work_class": work_class,
        "audit_role": audit_role,
        "evidence_access_required": evidence_access_required,
        "direct_tool_access_required": direct_tool_access_required,
        "provider_preference_scope": str(ctx.get("provider_preference_scope") or ""),
        "worker_output_authority": str(ctx.get("worker_output_authority") or ""),
        "quota_policy": str(ctx.get("quota_policy") or ""),
        "codex_inner_optimization_policy": dict(
            ctx.get("codex_inner_optimization_policy")
            if isinstance(ctx.get("codex_inner_optimization_policy"), Mapping)
            else {}
        ),
    }
    receipt["decision_sha256"] = hashlib.sha256(
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return receipt


def pro_review_model(*, runtime_root: str | Path = DEFAULT_RUNTIME) -> str:
    ctx = load_routing_policy(runtime_root=runtime_root)
    route = ctx.get("route_by_role", {}).get(PRO_REVIEW_ROUTE_ROLE, {})
    if isinstance(route, dict) and route.get("preferred_model"):
        return str(route["preferred_model"])
    model = str(ctx.get("pro_review_after_draft") or DEFAULT_PRO_REVIEW_MODEL)
    if not model:
        raise ValueError("pro review model is not explicitly configured")
    return model


def draft_worker_target(*, runtime_root: str | Path = DEFAULT_RUNTIME) -> str:
    ctx = load_routing_policy(runtime_root=runtime_root)
    route = ctx.get("route_by_role", {}).get(DEFAULT_DRAFT_ROUTE_ROLE, {})
    if isinstance(route, dict) and route.get("target"):
        return str(route["target"])
    configured = str(ctx.get("default_draft_worker") or DEFAULT_DRAFT_WORKER)
    if any(
        configured
        in {
            str(item.get("target") or ""),
            str(item.get("provider_id") or ""),
            str(item.get("worker_id") or ""),
        }
        for item in ctx.get("routes", [])
        if isinstance(item, dict)
    ):
        return configured
    return DEFAULT_DRAFT_WORKER


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
    return lower.startswith("grok")


def resolve_cloud_draft_model(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    candidate: str = "",
) -> str:
    """Resolve a model only after the Grok provider route is currently active."""
    ctx = load_routing_policy(runtime_root=runtime_root)
    if ctx.get("policy_present") is not True:
        raise ValueError("Grok model route policy is not present")
    active_grok_models = {
        str(item.get("model_id") or item.get("preferred_model") or "").strip()
        for item in ctx.get("routes", [])
        if isinstance(item, dict)
        and str(item.get("provider_id") or "") == GROK_PROVIDER_ID
        and str(item.get("model_id") or item.get("preferred_model") or "").strip()
    }
    if not active_grok_models:
        raise ValueError("Grok model route is not active in the current worker policy")
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
    seen: set[str] = set()
    for raw in candidates:
        model = str(raw or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        if is_cloud_draft_model(model) and model in active_grok_models:
            return model
    raise ValueError("no explicitly selected active Grok model")


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
