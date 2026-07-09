"""LiteLLM + Langfuse callback — hot-path trace (BerriAI sample seam, params only)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_provider_client import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    chat_completion,
    probe_gateway,
    resolve_gateway_base_url,
)

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

    if not configured["langfuse_keys_present"]:
        configured["skipped"] = True
        configured["reason"] = "LANGFUSE_KEYS_MISSING"
        configured["callback_wired"] = False
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


def _litellm_api_base(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        return url.removesuffix("/v1")
    return url


def run_gateway_trace_smoke(
    *,
    prompt: str = "reply with exactly: integrated_bus_trace_ok",
    model: str = "auto",
    base_url: str | None = None,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    """Probe gateway + one completion so Langfuse callback fires on hot path."""
    callback_cfg = configure_litellm_langfuse_callbacks()
    url = resolve_gateway_base_url(base_url)
    probe = probe_gateway(base_url=url)
    api_key = os.environ.get("LITELLM_MASTER_KEY", DEFAULT_API_KEY)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "layer": "L8/L5",
        "adapter": "litellm+langfuse_callback",
        "callback_config": callback_cfg,
        "gateway_probe": probe,
        "gateway_base_url": url,
        "completion_ok": False,
        "named_blocker": "",
    }

    if not probe.get("ok"):
        result["named_blocker"] = str(probe.get("named_blocker") or "PROVIDER_GATEWAY_UNREACHABLE")
        result["skipped_completion"] = True
        _write_litellm_evidence(runtime_root, result)
        return result

    # Prefer litellm.completion (callback path); fallback OpenAI-compat HTTP.
    try:
        import litellm

        configure_litellm_langfuse_callbacks()
        litellm.drop_params = True
        api_base = _litellm_api_base(url)
        resp = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            api_base=api_base,
            api_key=api_key,
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
        result["invoke_ok"] = True
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

    _write_litellm_evidence(runtime_root, result)
    return result


def _write_litellm_evidence(runtime_root: Path | None, record: dict[str, Any]) -> str:
    if runtime_root is None:
        return ""
    from services.agent_runtime.integrated_bus_bus_nodes import resolve_runtime_root
    from services.agent_runtime.thin_glue_stack import write_json

    rt = resolve_runtime_root(runtime_root)
    out_dir = rt / "state" / "litellm"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "latest.json"
    payload = {
        "schema_version": "xinao.integrated_bus.litellm_invoke.v1",
        "invoke_ok": record.get("completion_via") == "litellm.completion" and record.get("completion_ok") is True,
        "adapter": str(record.get("completion_via") or record.get("adapter") or "litellm_invoke_failed"),
        "gateway_base_url": record.get("gateway_base_url"),
        "completion_excerpt": record.get("completion_excerpt"),
        "named_blocker": record.get("named_blocker"),
        "litellm_completion_error": record.get("litellm_completion_error"),
        "callback_wired": (record.get("callback_config") or {}).get("callback_wired"),
    }
    write_json(path, payload)
    record["litellm_evidence_ref"] = str(path)
    return str(path)