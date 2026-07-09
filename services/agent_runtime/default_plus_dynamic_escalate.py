"""Default + dynamic escalate policy — T0 default + T1 secondary (authority contract)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.agent_runtime.routing_policy_reader import (
    DEFAULT_DRAFT_ROUTE_ROLE,
    PRO_REVIEW_ROUTE_ROLE,
    draft_worker_target,
    load_routing_policy,
    pro_review_model,
)
from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME

SCHEMA_VERSION = "xinao.default_plus_dynamic_escalate_policy.v1"
SENTINEL = "SENTINEL:DEFAULT_PLUS_DYNAMIC_ESCALATE_POLICY_V1"
POLICY_CONTRACT = "grok_default_plus_dynamic_escalate_policy.v1.json"

T0_DRAFT_ADAPTER = "cloud_qwen_via_litellm"
T1_PRO_REVIEW_ADAPTER = "deepseek_v4_pro_or_strong_review"
SEARCH_TIER_CHAIN = ("T0_searxng", "T0_ddgs_fallback", "T1_exa_dynamic")

_BANNED_DEFAULT_QWEN_MARKERS = (
    "qwen-local",
    "ollama/",
    "ollama:",
    ":11434",
    "qwen3:8b",
)
_CLOUD_QWEN_DEFAULT = "qwen3.6-flash"
_EXA_AGGRESSIVE_MODES = frozenset({"aggressive", "auto", "on", "1", "true", "yes"})
_HARD_DIFFICULTY = frozenset({"hard", "deep", "high", "architecture", "acceptance"})


def is_banned_default_qwen_model(model: str) -> bool:
    """Ban local ollama / qwen-local posing as cloud 千问 default."""
    text = str(model or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _BANNED_DEFAULT_QWEN_MARKERS)


def sanitize_default_draft_model(
    model: str,
    *,
    fallback: str = _CLOUD_QWEN_DEFAULT,
) -> str:
    cleaned = str(model or "").strip()
    if not cleaned or is_banned_default_qwen_model(cleaned):
        return fallback
    return cleaned


def load_escalate_policy_context(*, runtime_root: str | Path = DEFAULT_RUNTIME) -> dict[str, Any]:
    routing = load_routing_policy(runtime_root=runtime_root)
    draft_binding = resolve_draft_role_binding(runtime_root=runtime_root)
    review_binding = resolve_pro_review_role_binding(runtime_root=runtime_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "policy_contract": POLICY_CONTRACT,
        "routing_policy_ref": routing.get("policy_path"),
        "routing_policy_present": routing.get("policy_present") is True,
        "T0_draft": draft_binding,
        "T1_pro_review": review_binding,
        "search_tier_chain": list(SEARCH_TIER_CHAIN),
        "ollama_default_qwen_banned": True,
    }


def resolve_draft_role_binding(*, runtime_root: str | Path = DEFAULT_RUNTIME) -> dict[str, Any]:
    """Static T0 cloud qwen draft role — routing_policy default_draft_worker_first."""
    routing = load_routing_policy(runtime_root=runtime_root)
    route = routing.get("route_by_role", {}).get(DEFAULT_DRAFT_ROUTE_ROLE, {})
    preferred = ""
    if isinstance(route, dict):
        preferred = str(route.get("preferred_model") or "")
    model = sanitize_default_draft_model(preferred or _CLOUD_QWEN_DEFAULT)
    return {
        "tier": "T0_DEFAULT",
        "route_role": DEFAULT_DRAFT_ROUTE_ROLE,
        "target": draft_worker_target(runtime_root=runtime_root),
        "preferred_model": model,
        "adapter": T0_DRAFT_ADAPTER,
        "provider": "qwen",
        "via": "litellm",
        "ollama_default_banned": True,
    }


def resolve_pro_review_role_binding(*, runtime_root: str | Path = DEFAULT_RUNTIME) -> dict[str, Any]:
    """Static T1 Pro review role — routing_policy pro_review_after_draft."""
    routing = load_routing_policy(runtime_root=runtime_root)
    route = routing.get("route_by_role", {}).get(PRO_REVIEW_ROUTE_ROLE, {})
    model = pro_review_model(runtime_root=runtime_root)
    target = "deepseek"
    if isinstance(route, dict) and route.get("target"):
        target = str(route["target"])
    return {
        "tier": "T1_SECONDARY",
        "route_role": PRO_REVIEW_ROUTE_ROLE,
        "target": target,
        "preferred_model": model,
        "adapter": T1_PRO_REVIEW_ADAPTER,
        "via": "litellm",
    }


def should_escalate_model(*, context: dict[str, Any] | None = None) -> bool:
    """Dynamic model escalation — difficulty / failure / heal / low draft quality."""
    ctx = context or {}
    difficulty = str(ctx.get("difficulty") or ctx.get("task_difficulty") or "").strip().lower()
    if difficulty in _HARD_DIFFICULTY:
        return True
    if int(ctx.get("failure_count") or ctx.get("failures") or 0) > 0:
        return True
    if ctx.get("heal_repair_required") is True:
        return True
    if ctx.get("draft_quality_low") is True:
        return True
    task_type = str(ctx.get("task_type") or "").strip().lower()
    if task_type in _HARD_DIFFICULTY:
        return True
    return False


def should_escalate_search(
    query: str,
    *,
    searx_result: dict[str, Any],
    ddgs_hits: list[dict[str, Any]] | int,
    context: dict[str, Any] | None = None,
) -> bool:
    """T1 Exa dynamic — SearXNG→DDGS→Exa cascade when T0 insufficient."""
    del query
    if not os.environ.get("EXA_API_KEY", "").strip():
        return False
    ctx = context or {}
    mode = os.environ.get("XINAO_EXA_SEARCH_MODE", "").strip().lower()
    if mode in _EXA_AGGRESSIVE_MODES:
        return True
    if ctx.get("heal_repair_required") is True or ctx.get("low_github_hits") is True:
        return True
    difficulty = str(ctx.get("difficulty") or ctx.get("search_difficulty") or "").strip().lower()
    if difficulty in _HARD_DIFFICULTY:
        return True
    if int(ctx.get("failure_count") or 0) > 0:
        return True
    searx_failed = searx_result.get("ok") is not True
    if not searx_failed:
        return False
    ddgs_count = ddgs_hits if isinstance(ddgs_hits, int) else len(ddgs_hits)
    return ddgs_count < 2


def resolve_search_tier_evidence(external: dict[str, Any]) -> dict[str, Any]:
    adapter = str(external.get("adapter") or "")
    tier = "T0_DEFAULT"
    if adapter == "exa" or external.get("exa_dynamic") is True:
        tier = "T1_SECONDARY"
    elif adapter == "ddgs":
        tier = "T0_ddgs_fallback"
    return {
        "search_tier_used": tier,
        "search_adapter_primary": adapter,
        "search_tier_chain": list(external.get("search_tier_chain") or SEARCH_TIER_CHAIN),
        "search_sources_tried": list(external.get("sources_tried") or []),
        "exa_dynamic": external.get("exa_dynamic") is True,
        "searxng_ok": (external.get("searxng") or {}).get("ok") is True,
        "ddgs_ok": (external.get("ddgs") or {}).get("ok") is True,
        "exa_ok": (external.get("exa") or {}).get("ok") is True,
    }


def enrich_bus_escalate_evidence(
    result: dict[str, Any],
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
) -> dict[str, Any]:
    """Attach model/role/search tier evidence for integrated_bus_runner checks."""
    merged = dict(result)
    policy_ctx = load_escalate_policy_context(runtime_root=runtime_root)
    draft = policy_ctx["T0_draft"]
    review = policy_ctx["T1_pro_review"]

    merged.setdefault("escalate_policy_sentinel", SENTINEL)
    merged.setdefault("escalate_policy_contract", POLICY_CONTRACT)
    merged.setdefault("routing_policy_ref", policy_ctx.get("routing_policy_ref"))
    merged.setdefault("ollama_default_qwen_banned", True)

    if not merged.get("worker_lane_route_role"):
        merged["worker_lane_route_role"] = str(draft.get("route_role") or DEFAULT_DRAFT_ROUTE_ROLE)
    if not merged.get("worker_lane_tier"):
        merged["worker_lane_tier"] = str(draft.get("tier") or "T0_DEFAULT")
    if not merged.get("worker_lane_adapter"):
        merged["worker_lane_adapter"] = str(draft.get("adapter") or T0_DRAFT_ADAPTER)
    worker_model = str(merged.get("worker_lane_model") or draft.get("preferred_model") or "")
    merged["worker_lane_model"] = sanitize_default_draft_model(worker_model)

    if not merged.get("pro_review_route_role"):
        merged["pro_review_route_role"] = str(review.get("route_role") or PRO_REVIEW_ROUTE_ROLE)
    if not merged.get("pro_review_tier"):
        merged["pro_review_tier"] = str(review.get("tier") or "T1_SECONDARY")
    if not merged.get("pro_review_adapter"):
        merged["pro_review_adapter"] = str(review.get("adapter") or T1_PRO_REVIEW_ADAPTER)
    if not merged.get("pro_review_model"):
        merged["pro_review_model"] = str(review.get("preferred_model") or "")

    search_ext = merged.get("search_external") if isinstance(merged.get("search_external"), dict) else {}
    tier_ev = resolve_search_tier_evidence(search_ext)
    for key, val in tier_ev.items():
        merged.setdefault(key, val)

    merged["model_escalate_policy_wired"] = True
    merged["search_escalate_policy_wired"] = bool(tier_ev.get("search_tier_chain"))
    merged["default_plus_dynamic_escalate"] = {
        "T0_draft": draft,
        "T1_pro_review": review,
        "search": tier_ev,
        "policy_contract": POLICY_CONTRACT,
    }
    return merged