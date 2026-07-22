from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from services.agent_runtime import thin_provider_client as provider


class _OpenAIStubHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    chat_status = 200

    def _record(self, body: bytes = b"") -> None:
        self.__class__.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "body": body,
            }
        )

    def _json(self, status: int, payload: object) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        self._record()
        self._json(
            200,
            {
                "object": "list",
                "data": [{"id": "stub-model", "object": "model", "created": 1, "owned_by": "test"}],
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self._record(body)
        if self.__class__.chat_status != 200:
            self._json(self.__class__.chat_status, {"error": {"message": "stub failure"}})
            return
        self._json(
            200,
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": 1,
                "model": "stub-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "SDK_OK",
                            "provider_extra": "kept",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def _openai_stub(*, chat_status: int = 200) -> Iterator[tuple[str, type[_OpenAIStubHandler]]]:
    handler = type("OpenAIStubHandler", (_OpenAIStubHandler,), {})
    handler.requests = []
    handler.chat_status = chat_status
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_probe_gateway_uses_official_sdk_raw_response(monkeypatch) -> None:
    monkeypatch.setattr(provider, "DEFAULT_API_KEY", "sdk-test-key")
    with _openai_stub() as (base_url, handler):
        result = provider.probe_gateway(base_url=base_url, timeout_s=2)

    assert result["ok"] is True
    assert result["status_code"] == 200
    assert "stub-model" in result["body_excerpt"]
    assert [(row["method"], row["path"]) for row in handler.requests] == [("GET", "/v1/models")]
    assert handler.requests[0]["authorization"] == "Bearer sdk-test-key"


def test_chat_completion_preserves_consumer_shape(monkeypatch) -> None:
    monkeypatch.setattr(provider, "DEFAULT_API_KEY", "sdk-test-key")
    with _openai_stub() as (base_url, handler):
        result = provider.chat_completion(
            [{"role": "user", "content": "return SDK_OK"}],
            model="stub-model",
            base_url=base_url,
            timeout_s=2,
        )

    assert result["ok"] is True
    assert result["response"]["choices"][0]["message"]["content"] == "SDK_OK"
    assert result["response"]["choices"][0]["message"]["provider_extra"] == "kept"
    assert "refusal" not in result["response"]["choices"][0]["message"]
    request = handler.requests[0]
    assert (request["method"], request["path"]) == ("POST", "/v1/chat/completions")
    assert json.loads(request["body"])["model"] == "stub-model"


def test_sdk_retry_is_disabled_for_billable_attempt_accounting(monkeypatch) -> None:
    monkeypatch.setattr(provider, "DEFAULT_API_KEY", "sdk-test-key")
    with _openai_stub(chat_status=500) as (base_url, handler):
        result = provider.chat_completion(
            [{"role": "user", "content": "fail once"}],
            model="stub-model",
            base_url=base_url,
            timeout_s=2,
        )

    assert result["ok"] is False
    assert result["status_code"] == 500
    assert result["named_blocker"] == "PROVIDER_GATEWAY_AUTH_OR_UPSTREAM"
    assert len(handler.requests) == 1


def test_timeout_must_be_finite_and_positive() -> None:
    for invalid in (0.0, -1.0, float("inf"), float("nan")):
        try:
            provider._openai_client(base_url="http://127.0.0.1:1/v1", timeout_s=invalid)
        except ValueError as exc:
            assert "finite positive" in str(exc)
        else:
            raise AssertionError(f"invalid timeout was accepted: {invalid!r}")
