"""LiteLLM + Langfuse callback — hot-path trace (BerriAI sample seam, params only)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_provider_client import DEFAULT_BASE_URL, chat_completion, probe_gateway

SCHEMA_VERSION = "xinao.integrated_bus.litellm_langfuse.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_LITELLM_LANGFUSE"


def _langfuse_keys_present() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") or os.environ.get("LANGFUSE_SECRET_KEY"))


def configure_litellm_langfuse_callbacks(*, force: bool = True) -> dict[str, Any]:
    """Wire litellm.success_callback=['langfuse'] once per Activity (global litellm)."""
    configured: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "success_callback": ["langfuse"],
        "langfuse_keys_present": _langfuse_keys_present(),
        "tracing_enabled": os.environ.get("LITELLM_TRACING_ENABLED", "1").strip().lower() not in {"0", "false", "no"},
    }
    if not configured["tracing_enabled"]:
        configured["skipped"] = True
        configured["reason"] = "LITELLM_TRACING_DISABLED"
        return configured

    try:
        import litellm

        litellm.success_callback = ["langfuse"]
        if os.environ.get("LANGFUSE_PUBLIC_KEY"):
            litellm.langfuse_public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
        if os.environ.get("LANGFUSE_SECRET_KEY"):
            litellm.langfuse_secret_key = os.environ["LANGFUSE_SECRET_KEY"]
        if os.environ.get("LANGFUSE_HOST"):
            litellm.langfuse_host = os.environ["LANGFUSE_HOST"]
        configured["litellm_module"] = True
        configured["callback_wired"] = True
    except Exception as exc:
        configured["callback_wired"] = False
        configured["litellm_error"] = str(exc)

    if force and configured.get("callback_wired"):
        os.environ.setdefault("LITELLM_SUCCESS_CALLBACK", "langfuse")
    return configured


def run_gateway_trace_smoke(
    *,
    prompt: str = "reply with exactly: integrated_bus_trace_ok",
    model: str = "auto",
    base_url: str | None = None,
) -> dict[str, Any]:
    """Probe gateway + one completion so Langfuse callback fires on hot path."""
    callback_cfg = configure_litellm_langfuse_callbacks()
    url = base_url or DEFAULT_BASE_URL
    probe = probe_gateway(base_url=url)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "layer": "L8/L5",
        "adapter": "litellm+langfuse_callback",
        "callback_config": callback_cfg,
        "gateway_probe": probe,
        "completion_ok": False,
        "named_blocker": "",
    }

    if not probe.get("ok"):
        result["named_blocker"] = str(probe.get("named_blocker") or "PROVIDER_GATEWAY_UNREACHABLE")
        result["skipped_completion"] = True
        return result

    # Prefer litellm.completion (callback path); fallback OpenAI-compat HTTP.
    try:
        import litellm

        configure_litellm_langfuse_callbacks()
        api_base = url.rstrip("/").removesuffix("/v1") if "/v1" in url else url
        resp = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            api_base=api_base,
            timeout=45,
        )
        text = ""
        try:
            text = resp.choices[0].message.content or ""
        except Exception:
            text = str(resp)[:200]
        result["completion_ok"] = bool(text.strip())
        result["completion_via"] = "litellm.completion"
        result["completion_excerpt"] = text[:120]
    except Exception as litellm_exc:
        http = chat_completion([{"role": "user", "content": prompt}], model=model, base_url=url)
        result["completion_via"] = "thin_provider_client_fallback"
        result["litellm_completion_error"] = str(litellm_exc)
        if http.get("ok"):
            try:
                text = http["response"]["choices"][0]["message"]["content"]
            except Exception:
                text = ""
            result["completion_ok"] = bool(str(text).strip())
            result["completion_excerpt"] = str(text)[:120]
        else:
            result["named_blocker"] = "LITELLM_COMPLETION_FAILED"
            result["http_error"] = http.get("error")

    if callback_cfg.get("callback_wired") and not _langfuse_keys_present():
        result["langfuse_trace_note"] = "callback_wired_keys_missing_trace_may_be_noop"
    return result