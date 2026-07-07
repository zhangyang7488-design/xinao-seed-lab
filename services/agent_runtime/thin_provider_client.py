from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.thin_provider_client.v1"
DEFAULT_BASE_URL = os.environ.get("XINAO_PROVIDER_BASE_URL", "http://127.0.0.1:20128/v1")


def probe_gateway(*, base_url: str = DEFAULT_BASE_URL, timeout_s: float = 3.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {
                "schema_version": SCHEMA_VERSION,
                "ok": True,
                "base_url": base_url,
                "status_code": resp.status,
                "body_excerpt": body[:500],
            }
    except urllib.error.URLError as exc:
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
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return {"ok": True, "base_url": base_url, "response": body}
    except Exception as exc:
        return {"ok": False, "base_url": base_url, "error": str(exc)}