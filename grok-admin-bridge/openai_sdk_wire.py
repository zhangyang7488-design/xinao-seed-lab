"""Official OpenAI SDK wire adapter for the PowerShell relay worker.

The JSON request arrives on stdin so API keys never appear in process arguments.
Only protocol transport lives here; identity, quota, receipts, hashes, and
acceptance remain owned by the PowerShell worker.
"""

from __future__ import annotations

import json
import math
import sys
from importlib.metadata import version
from typing import Any

from openai import APIStatusError, OpenAI


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def _invoke(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = _required_text(payload, "api_key")
    base_url = _required_text(payload, "base_url").rstrip("/") + "/"
    api_style = _required_text(payload, "api_style")
    model = _required_text(payload, "model")
    prompt = _required_text(payload, "prompt")
    max_tokens = int(payload.get("max_tokens") or 0)
    timeout_seconds = float(payload.get("timeout_seconds") or 0)
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if api_style not in {"chat_completions", "responses"}:
        raise ValueError(f"unsupported api_style: {api_style}")

    sdk_version = version("openai")
    try:
        with OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            timeout=timeout_seconds,
        ) as client:
            if api_style == "chat_completions":
                response = client.chat.completions.with_raw_response.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    timeout=timeout_seconds,
                )
            else:
                response = client.responses.with_raw_response.create(
                    model=model,
                    input=prompt,
                    max_output_tokens=max_tokens,
                    timeout=timeout_seconds,
                )
        return {
            "ok": True,
            "status_code": int(response.status_code),
            "raw_response": response.text,
            "request_id": str(response.headers.get("x-request-id") or ""),
            "sdk": "openai-python",
            "sdk_version": sdk_version,
            "max_retries": 0,
        }
    except APIStatusError as exc:
        return {
            "ok": False,
            "status_code": int(exc.status_code),
            "error_type": type(exc).__name__,
            "error": f"provider returned HTTP {exc.status_code}",
            "sdk": "openai-python",
            "sdk_version": sdk_version,
            "max_retries": 0,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": 0,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "sdk": "openai-python",
            "sdk_version": sdk_version,
            "max_retries": 0,
        }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("stdin JSON must be an object")
        result = _invoke(payload)
    except Exception as exc:
        result = {
            "ok": False,
            "status_code": 0,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "sdk": "openai-python",
            "sdk_version": version("openai"),
            "max_retries": 0,
        }
    # The host PowerShell can launch redirected Python with a narrow Windows
    # code page (for example GBK). An ASCII JSON envelope keeps arbitrary model
    # text lossless via escapes and prevents a post-request encoding crash.
    sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
