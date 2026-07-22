from __future__ import annotations

import math
import os
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

SCHEMA_VERSION = "xinao.codex_s.thin_provider_client.v1"
DEFAULT_BASE_URL = os.environ.get("XINAO_PROVIDER_BASE_URL", "http://127.0.0.1:20128/v1")
DEFAULT_API_KEY = os.environ.get(
    "LITELLM_MASTER_KEY",
    os.environ.get("OPENAI_API_KEY", ""),
)


def _openai_client(*, base_url: str, timeout_s: float) -> OpenAI:
    """Bind the official SDK to the selected OpenAI-compatible endpoint.

    Retries stay disabled here because the outer execution receipt owns every
    billable attempt. Local gateways historically allowed an empty key; the SDK
    requires a value, so use a non-secret placeholder only for that local case.
    """

    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be a finite positive number")
    return OpenAI(
        api_key=DEFAULT_API_KEY.strip() or "local-provider-no-key",
        base_url=base_url.rstrip("/") + "/",
        max_retries=0,
        timeout=timeout_s,
    )


def _status_body(exc: APIStatusError, limit: int = 300) -> str:
    try:
        return exc.response.text[:limit]
    except Exception:
        return ""


def resolve_gateway_base_url(
    configured: str | None = None,
    *,
    timeout_s: float = 3.0,
) -> str:
    """Probe candidates: env → params → docker service → host mapped port."""
    in_docker_worker = os.environ.get("XINAO_CODEX_S_REPO_ROOT", "").replace("\\", "/") == "/app"
    seen: set[str] = set()
    candidates: list[str] = []
    host_mapped = "http://127.0.0.1:20128/v1"
    docker_internal = (
        "http://moxing-wangguan:4000/v1",
        "http://litellm:4000/v1",
    )
    host_first = (
        os.environ.get("XINAO_PROVIDER_BASE_URL", "").strip(),
        os.environ.get("XINAO_GATEWAY_BASE_URL", "").strip(),
        (configured or "").strip(),
        host_mapped,
        DEFAULT_BASE_URL,
    )
    docker_first = (
        os.environ.get("XINAO_PROVIDER_BASE_URL", "").strip(),
        os.environ.get("XINAO_GATEWAY_BASE_URL", "").strip(),
        (configured or "").strip(),
        *docker_internal,
        "http://host.docker.internal:20128/v1",
        host_mapped,
        DEFAULT_BASE_URL,
    )
    probe_timeout = 1.0 if not in_docker_worker else timeout_s
    for raw in docker_first if in_docker_worker else host_first:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        candidates.append(raw)
    for url in candidates:
        if probe_gateway(base_url=url, timeout_s=probe_timeout).get("ok") is True:
            return url
    return candidates[-1] if candidates else DEFAULT_BASE_URL


def probe_gateway(*, base_url: str = DEFAULT_BASE_URL, timeout_s: float = 3.0) -> dict[str, Any]:
    try:
        with _openai_client(base_url=base_url, timeout_s=timeout_s) as client:
            response = client.models.with_raw_response.list(timeout=timeout_s)
            return {
                "schema_version": SCHEMA_VERSION,
                "ok": True,
                "base_url": base_url,
                "status_code": response.status_code,
                "body_excerpt": response.text[:500],
            }
    except APIStatusError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "base_url": base_url,
            "status_code": exc.status_code,
            "named_blocker": "PROVIDER_GATEWAY_AUTH_OR_UPSTREAM",
            "error": str(exc),
            "body_excerpt": _status_body(exc),
            "hint": "Set LITELLM_MASTER_KEY or check LiteLLM config",
        }
    except (APIConnectionError, APITimeoutError, TimeoutError, OSError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "base_url": base_url,
            "named_blocker": "PROVIDER_GATEWAY_UNREACHABLE",
            "error": str(exc),
            "hint": "Start LiteLLM/OmniRoute docker on :20128 or set XINAO_PROVIDER_BASE_URL",
        }


def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str = "auto",
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    try:
        with _openai_client(base_url=base_url, timeout_s=timeout_s) as client:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=timeout_s,
            )
            return {
                "ok": True,
                "base_url": base_url,
                "response": completion.model_dump(
                    mode="json",
                    exclude_none=True,
                    exclude_unset=True,
                ),
            }
    except APIStatusError as exc:
        return {
            "ok": False,
            "base_url": base_url,
            "status_code": exc.status_code,
            "named_blocker": "PROVIDER_GATEWAY_AUTH_OR_UPSTREAM",
            "error": str(exc),
        }
    except Exception as exc:
        return {"ok": False, "base_url": base_url, "error": str(exc)}
