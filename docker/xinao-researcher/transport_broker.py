"""Transport-side Unix socket broker for dual-container IPC.

Runs in the authful transport container and forwards schema-validated requests
to the no-auth tool sidecar. Does not open host Docker sockets or write ledgers.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Mapping

from ipc_contract import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    IpcContractError,
    canonical_bytes,
    decode_frame,
    encode_frame,
    parse_json_object,
)


class BrokerError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(detail or reason_code)
        self.reason_code = reason_code
        self.detail = str(detail)[:2000]


class UnixSocketBroker:
    """Length-prefixed JSON request/response over a Unix domain socket."""

    def __init__(self, socket_path: Path | str, *, connect_timeout_s: float = 5.0) -> None:
        self.socket_path = Path(socket_path)
        self.connect_timeout_s = float(connect_timeout_s)

    def call(self, request: Mapping[str, Any], *, timeout_s: float | None = None) -> dict[str, Any]:
        timeout = self.connect_timeout_s if timeout_s is None else float(timeout_s)
        if not isinstance(request, Mapping):
            raise BrokerError("REQUEST_INVALID", "mapping required")
        try:
            frame = encode_frame(dict(request))
        except (TypeError, ValueError, IpcContractError) as exc:
            raise BrokerError("REQUEST_ENCODE_FAILED", str(exc)) from exc
        if len(frame) - 8 > MAX_REQUEST_BYTES:
            raise BrokerError("REQUEST_TOO_LARGE", str(len(frame) - 8))
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except OSError as exc:
            raise BrokerError("SOCKET_CREATE_FAILED", str(exc)) from exc
        try:
            sock.settimeout(timeout)
            try:
                sock.connect(str(self.socket_path))
            except OSError as exc:
                raise BrokerError("SIDECAR_CONNECT_FAILED", str(exc)) from exc
            try:
                sock.sendall(frame)
            except OSError as exc:
                raise BrokerError("SIDECAR_SEND_FAILED", str(exc)) from exc
            buffer = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                except OSError as exc:
                    raise BrokerError("SIDECAR_RECV_FAILED", str(exc)) from exc
                if not chunk:
                    if not buffer:
                        raise BrokerError("SIDECAR_CLOSED", "empty response")
                    break
                buffer += chunk
                if len(buffer) > MAX_RESPONSE_BYTES + 8:
                    raise BrokerError("RESPONSE_TOO_LARGE", str(len(buffer)))
                try:
                    message, remaining = decode_frame(buffer, maximum=MAX_RESPONSE_BYTES)
                except IpcContractError as exc:
                    if exc.reason_code == "FRAME_INCOMPLETE":
                        continue
                    raise BrokerError(exc.reason_code, exc.detail) from exc
                if remaining:
                    # One response per call; ignore trailing bytes.
                    pass
                if not isinstance(message, dict):
                    raise BrokerError("RESPONSE_INVALID", "object required")
                # Bind response request_id when present.
                expected_id = request.get("request_id")
                observed_id = message.get("request_id")
                if expected_id is not None and observed_id not in {None, expected_id}:
                    raise BrokerError(
                        "RESPONSE_REQUEST_ID_MISMATCH",
                        f"expected={expected_id} observed={observed_id}",
                    )
                return message
            # Fallback parse of entire buffer if loop exited without frame.
            try:
                message, _ = decode_frame(buffer, maximum=MAX_RESPONSE_BYTES)
            except IpcContractError as exc:
                raise BrokerError(exc.reason_code, exc.detail) from exc
            return message
        finally:
            try:
                sock.close()
            except OSError:
                pass


def call_stdio_once(request: Mapping[str, Any]) -> dict[str, Any]:
    """Utility for tests: round-trip via encode/decode without a live socket."""
    frame = encode_frame(dict(request))
    message, _ = decode_frame(frame, maximum=MAX_REQUEST_BYTES)
    return parse_json_object(canonical_bytes(message))
