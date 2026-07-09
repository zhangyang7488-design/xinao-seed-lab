"""Read D-runtime routing_policy.json — qwen draft + DeepSeek V4 Pro review roles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME

SCHEMA_VERSION = "xinao.routing_policy_reader.v1"
SENTINEL = "SENTINEL:XINAO_ROUTING_POLICY_READER_V1"
DEFAULT_POLICY_PATH = DEFAULT_RUNTIME / "agent_runtime" / "routing_policy.json"

PRO_REVIEW_ROUTE_ROLE = "pro_review_after_draft"
DEFAULT_DRAFT_ROUTE_ROLE = "default_draft_worker_first"
DEFAULT_DRAFT_WORKER = "qwen"
DEFAULT_PRO_REVIEW_MODEL = "deepseek-v4-pro"


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
    routes = policy.get("routes") if isinstance(policy.get("routes"), list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "policy_path": str(policy_path),
        "policy_present": policy_path.is_file(),
        "policy_version": str(policy.get("policy_version") or ""),
        "default_draft_worker": str(policy.get("default_draft_worker") or DEFAULT_DRAFT_WORKER),
        "pro_review_after_draft": str(
            policy.get("pro_review_after_draft") or DEFAULT_PRO_REVIEW_MODEL
        ),
        "routes": routes,
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