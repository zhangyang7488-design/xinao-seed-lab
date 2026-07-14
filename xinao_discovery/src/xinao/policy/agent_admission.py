"""Fail-closed agent admission checks for the P9 negative behavior suite."""

from __future__ import annotations

from typing import Any

_BYPASS_FLAGS = {"skip_verifier", "skip_schema", "bypass_authority", "promote_without_evidence"}


def evaluate_agent_admission(request: dict[str, Any]) -> dict[str, Any]:
    role = str(request.get("role") or "").strip()
    model = str(request.get("model") or "").strip().lower()
    provider = str(request.get("provider") or "").strip()
    sources = [str(value).strip() for value in request.get("source_refs", []) if str(value).strip()]
    flags = dict(request.get("flags") or {})
    authorization = dict(request.get("authorization") or {})
    reasons: list[str] = []
    if role != "grok_worker":
        reasons.append("worker_role_forbidden")
    elif model != "grok-4.5" or provider != "grok_acpx_headless":
        reasons.append("model_identity_mismatch")
    if request.get("write") is True:
        reasons.append("worker_write_forbidden")
    if not sources:
        reasons.append("source_refs_required")
    if any(flags.get(name) is True for name in _BYPASS_FLAGS):
        reasons.append("bypass_flag_forbidden")
    if str(authorization.get("mode") or "").lower() in {"auto_all", "authorize_all"}:
        reasons.append("automatic_blanket_authorization_forbidden")
    return {
        "schema_version": "xinao.agent_admission.v1",
        "admitted": not reasons,
        "reasons": reasons,
        "role": role,
        "model": model,
        "provider": provider,
        "write": request.get("write") is True,
        "source_count": len(sources),
    }
