from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.thin_provider_client.v1"
DEFAULT_BASE_URL = os.environ.get("XINAO_PROVIDER_BASE_URL", "http://127.0.0.1:20128/v1")
DEFAULT_API_KEY = os.environ.get(
    "LITELLM_MASTER_KEY",
    os.environ.get("OPENAI_API_KEY", ""),
)


def _auth_headers() -> dict[str, str]:
    key = DEFAULT_API_KEY.strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


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
    url = base_url.rstrip("/") + "/models"
    headers = {"Content-Type": "application/json", **_auth_headers()}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {
                "schema_version": SCHEMA_VERSION,
                "ok": True,
                "base_url": base_url,
                "status_code": resp.status,
                "body_excerpt": body[:500],
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "base_url": base_url,
            "status_code": exc.code,
            "named_blocker": "PROVIDER_GATEWAY_AUTH_OR_UPSTREAM",
            "error": str(exc),
            "body_excerpt": body,
            "hint": "Set LITELLM_MASTER_KEY or check LiteLLM config",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
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
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({"model": model, "messages": messages}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", **_auth_headers()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return {"ok": True, "base_url": base_url, "response": body}
    except Exception as exc:
        return {"ok": False, "base_url": base_url, "error": str(exc)}
