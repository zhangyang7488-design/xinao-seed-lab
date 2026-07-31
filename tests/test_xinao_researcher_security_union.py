"""Security union: MCP convergence × red-team repairs.

Executable proofs for the integrator interface. Does not claim live Docker,
live model role fitness, Owner adoption, or parent completion.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "docker" / "xinao-researcher"
SEALED_CANARY_SHA256 = "c9c1a132ac00ebde9b198db6eb12a1be456cbcfb8c66d892856997595e40c47e"
# Unix-domain IPC + SO_PEERCRED are the production Linux/container transport.
# Windows interpreters lack socket.AF_UNIX; do not mock peer credentials green.
_HAS_AF_UNIX = hasattr(socket, "AF_UNIX")
_SKIP_NO_AF_UNIX = pytest.mark.skipif(
    not _HAS_AF_UNIX,
    reason="Unix-domain socket transport required (socket.AF_UNIX absent)",
)


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ipc() -> Any:
    return _load("xinao_ipc_contract_union", PKG / "ipc_contract.py")


@pytest.fixture(scope="module")
def tool_mod() -> Any:
    _load("ipc_contract", PKG / "ipc_contract.py")
    return _load("xinao_tool_executor_union", PKG / "tool_executor.py")


@pytest.fixture(scope="module")
def broker_mod() -> Any:
    _load("ipc_contract", PKG / "ipc_contract.py")
    return _load("xinao_transport_broker_union", PKG / "transport_broker.py")


@pytest.fixture(scope="module")
def specs() -> Any:
    return _load("xinao_docker_create_specs_union", PKG / "docker_create_specs.py")


@pytest.fixture(scope="module")
def mcp_mod() -> Any:
    _load("ipc_contract", PKG / "ipc_contract.py")
    _load("transport_broker", PKG / "transport_broker.py")
    return _load("xinao_mcp_episode_lab_server_union", PKG / "mcp_episode_lab_server.py")


@pytest.fixture(scope="module")
def bind_mod() -> Any:
    _load("ipc_contract", PKG / "ipc_contract.py")
    return _load("xinao_episode_mcp_binding_union", PKG / "episode_mcp_binding.py")


def test_union_canary_entrypoint_exact() -> None:
    digest = hashlib.sha256((PKG / "entrypoint.py").read_bytes()).hexdigest()
    assert digest == SEALED_CANARY_SHA256


def test_union_mcp_scrubs_and_strips_builtins(mcp_mod: Any, bind_mod: Any, tmp_path: Path) -> None:
    os.environ["GROK_API_KEY"] = "union-secret"
    os.environ["XAI_API_KEY"] = "union-xai"
    os.environ["DOCKER_HOST"] = "unix:///var/run/docker.sock"
    try:
        removed = mcp_mod.scrub_inherited_transport_env()
        assert "GROK_API_KEY" in removed
        assert "XAI_API_KEY" in removed
        assert "DOCKER_HOST" in removed
        assert "GROK_API_KEY" not in os.environ
    finally:
        for key in ("GROK_API_KEY", "XAI_API_KEY", "DOCKER_HOST"):
            os.environ.pop(key, None)
    receipt = bind_mod.materialize_attempt_local_binding(
        root=tmp_path / "bind",
        episode_id="ep-union-bind",
        socket_path="/ipc/tool.sock",
        server_path=str(PKG / "mcp_episode_lab_server.py"),
        pythonpath=str(PKG),
    )
    assert receipt["tools_allowlist"] == ["search_tool", "use_tool"]
    assert "run_terminal_cmd" in receipt["stripped_builtins"]
    assert "web_search" in receipt["stripped_builtins"]
    assert "read_file" in receipt["stripped_builtins"]
    assert receipt["completion_claim_allowed"] is False


@_SKIP_NO_AF_UNIX
def test_union_durable_replay_survives_restart(
    tmp_path: Path, tool_mod: Any, broker_mod: Any, ipc: Any
) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    sock = tmp_path / "ipc" / "tool.sock"
    sock.parent.mkdir()
    state = tmp_path / "ipc" / ".xinao-replay"

    def _serve() -> None:
        tool_mod.serve_unix(
            socket_path=sock,
            lab_root=lab,
            oneshot=False,
            replay_state_dir=state,
        )

    t1 = threading.Thread(target=_serve, daemon=True)
    t1.start()
    for _ in range(100):
        if sock.exists():
            break
        time.sleep(0.02)
    assert sock.exists()
    broker = broker_mod.UnixSocketBroker(sock)
    req = ipc.build_request(op="ping", episode_id="ep-durable", request_id="fixed-across-restart")
    assert broker.call(req)["status"] == "ok"
    # Simulate tool-executor restart: new process/thread, same durable state dir.
    # Stop by unlinking is hard; spawn second server on new sock sharing state.
    sock2 = tmp_path / "ipc" / "tool2.sock"

    def _serve2() -> None:
        tool_mod.serve_unix(
            socket_path=sock2,
            lab_root=lab,
            oneshot=False,
            replay_state_dir=state,
        )

    threading.Thread(target=_serve2, daemon=True).start()
    for _ in range(100):
        if sock2.exists():
            break
        time.sleep(0.02)
    assert sock2.exists()
    broker2 = broker_mod.UnixSocketBroker(sock2)
    replay = None
    last_err: Exception | None = None
    for _ in range(50):
        try:
            replay = broker2.call(req)
            break
        except Exception as exc:  # connect race before listen
            last_err = exc
            time.sleep(0.02)
    if replay is None:
        raise last_err if last_err is not None else AssertionError("sock2 never ready")
    assert replay["status"] == "denied"
    assert replay["reason_code"] == "REQUEST_REPLAY"
    assert replay["owner_adopted"] is False
    # Marker must live under IPC state, not lab.
    markers = list(state.rglob("*.seen"))
    assert markers
    assert not list(lab.rglob("*.seen"))


def test_union_peer_require_fail_closed(
    tool_mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XINAO_IPC_PEER_UIDS", raising=False)
    monkeypatch.setenv("XINAO_IPC_PEER_REQUIRE", "1")
    assert tool_mod.peer_require_enabled() is True
    assert tool_mod._peer_uids_allowed() == set()

    # Portable: empty allowlist must deny before SO_PEERCRED (no AF_UNIX needed).
    class _Fake:
        def getsockopt(self, *a, **k):  # pragma: no cover
            raise AssertionError("should not reach SO_PEERCRED when allowlist empty")

    with pytest.raises(tool_mod.ToolExecutorError) as exc:
        tool_mod.assert_unix_peer_allowed(_Fake())  # type: ignore[arg-type]
    assert exc.value.reason_code == "IPC_PEER_CONFIG_REQUIRED"

    # Real SO_PEERCRED peer-uid denial requires Unix-domain sockets (Linux/container).
    # Do not replace this leg with a mock that would falsely pass on Windows.
    if not _HAS_AF_UNIX:
        pytest.skip("Unix-domain socket + SO_PEERCRED peer-uid leg requires socket.AF_UNIX")

    monkeypatch.setenv("XINAO_IPC_PEER_UIDS", "0")
    # Wrong uid denied when SO_PEERCRED available via real unix pair.
    lab = tmp_path / "lab"
    lab.mkdir()
    sock = tmp_path / "peer.sock"
    # Only accept and peer-check; use real socket.
    ready = threading.Event()
    result: dict[str, Any] = {}

    def _server() -> None:
        if sock.exists():
            sock.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock))
        srv.listen(1)
        ready.set()
        conn, _ = srv.accept()
        try:
            tool_mod.assert_unix_peer_allowed(conn)
            result["ok"] = True
        except tool_mod.ToolExecutorError as e:
            result["reason"] = e.reason_code
        finally:
            conn.close()
            srv.close()

    threading.Thread(target=_server, daemon=True).start()
    assert ready.wait(2)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(sock))
    client.close()
    for _ in range(50):
        if result:
            break
        time.sleep(0.02)
    # Current worker uid is 65532; allowlist is 0 → denied.
    if result.get("ok"):
        # If somehow running as uid 0, still prove require path exists.
        assert os.getuid() == 0
    else:
        assert result.get("reason") == "IPC_PEER_UID_DENIED"


def test_union_shell_bwrap_no_path_walk(
    tool_mod: Any, ipc: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if tool_mod.resolve_bwrap_bin() is None:
        pytest.skip("bwrap unavailable")
    monkeypatch.setenv("XINAO_TOOL_EXEC_BWRAP", "require")
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "work").mkdir()
    code = (
        "import pathlib\n"
        "p=pathlib.Path('.').resolve()\n"
        "for _ in range(12):\n"
        "    p=p.parent\n"
        "    cand=p/'etc'/'passwd'\n"
        "    if cand.exists():\n"
        "        print('LEAK'); break\n"
        "else:\n"
        "    print('NOLEAK')\n"
    )
    resp = tool_mod.execute_op(
        ipc.build_request(
            op="shell_exec",
            episode_id="ep-bwrap",
            request_id="bw-1",
            args={"argv": [sys.executable, "-c", code], "cwd_relative": "work"},
            timeout_ms=8000,
        ),
        lab_root=lab,
    )
    assert resp["status"] == "ok", resp
    stdout = (resp.get("stdout") or "").strip()
    assert "NOLEAK" in stdout
    assert not stdout.startswith("LEAK")
    assert "LEAK " not in stdout
    # Shell interpreters still denied at argv layer.
    sh = tool_mod.execute_op(
        ipc.build_request(
            op="shell_exec",
            episode_id="ep-bwrap",
            request_id="bw-sh",
            args={"argv": ["/bin/sh", "-c", "id"], "cwd_relative": "work"},
        ),
        lab_root=lab,
    )
    assert sh["status"] == "denied"
    assert sh["reason_code"] == "ARGV_DENIED"


def test_union_create_spec_and_inspect_agree(specs: Any) -> None:
    tool = specs.tool_executor_container_spec(
        image="tool:union",
        name="tool-u",
        episode_lab_host_path="/host/lab",
        ipc_host_dir="/host/ipc",
        ipc_peer_uids="1000",
        bwrap_mode="require",
    )
    specs.assert_tool_spec_fail_closed(tool)
    good_inspect = {
        "Image": "sha256:abc",
        "Config": {
            "User": "65532:65532",
            "Entrypoint": [
                "python",
                "-I",
                "/opt/xinao-tool-executor/tool_executor.py",
            ],
            "Env": [
                "HOME=/tmp",
                "XINAO_TOOL_EXEC_BWRAP=require",
                "XINAO_IPC_PEER_REQUIRE=1",
                "XINAO_IPC_PEER_UIDS=1000",
                "XINAO_REPLAY_STATE_DIR=/ipc/.xinao-replay",
            ],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "Mounts": [
            {"Destination": "/episode-lab", "Source": "/host/lab"},
            {"Destination": "/ipc", "Source": "/host/ipc"},
        ],
    }
    assert specs.validate_tool_container_inspect(good_inspect) == []
    assert specs.create_spec_matches_inspect(tool, good_inspect) == []

    # Drift: inspect missing bwrap must fail live validator and disagree if create is clean.
    bad_inspect = json.loads(json.dumps(good_inspect))
    bad_inspect["Config"]["Env"] = ["HOME=/tmp", "XINAO_IPC_PEER_REQUIRE=1"]
    live_v = specs.validate_tool_container_inspect(bad_inspect)
    assert any("bwrap" in v for v in live_v)
    disagree = specs.create_spec_matches_inspect(tool, bad_inspect)
    assert disagree

    bundle = specs.dual_container_bundle(
        transport_image="t",
        tool_image="tool",
        auth_host_path="/a",
        input_host_path="/i",
        output_host_path="/o",
        episode_lab_host_path="/lab",
        ipc_host_dir="/ipc",
        ipc_peer_uids="1000",
    )
    assert bundle["fail_closed_before_provider"] is True
    assert bundle["tool_spec_violations"] == []
    mi = bundle["minimal_integrator_interface"]
    assert "assert_tool_spec_fail_closed" in mi["validators"].values()
    assert mi["transport_mcp"]["tools_allowlist"] == ["search_tool", "use_tool"]
    assert "XINAO_IPC_PEER_REQUIRE=1" in mi["tool_env_required"][1] or any(
        "PEER_REQUIRE" in x for x in mi["tool_env_required"]
    )


def test_union_dockerfile_installs_bwrap() -> None:
    text = (PKG / "Dockerfile.tool-executor").read_text(encoding="utf-8")
    assert "bubblewrap" in text
    assert "XINAO_TOOL_EXEC_BWRAP" in text
    assert "USER 65532:65532" in text
    assert "entrypoint.py" not in text
