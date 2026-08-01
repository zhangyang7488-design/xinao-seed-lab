"""Focused regression for the real ResearchEpisode cross-container IPC bridge."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESEARCHER = ROOT / "docker" / "xinao-researcher"
HOST_PATH = ROOT / "skills" / "xinao" / "scripts" / "dual_container_host.py"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def specs() -> Any:
    return _load("xinao_ipc_runtime_specs_test", RESEARCHER / "docker_create_specs.py")


@pytest.fixture(scope="module")
def tool() -> Any:
    _load("ipc_contract", RESEARCHER / "ipc_contract.py")
    return _load("xinao_ipc_runtime_tool_test", RESEARCHER / "tool_executor.py")


@pytest.fixture(scope="module")
def host() -> Any:
    return _load("xinao_ipc_runtime_host_test", HOST_PATH)


def test_peer_gated_socket_mode_requires_a_nonempty_uid_pin(
    tool: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XINAO_IPC_PEER_REQUIRE", "1")
    monkeypatch.delenv("XINAO_IPC_PEER_UIDS", raising=False)
    with pytest.raises(tool.ToolExecutorError) as exc:
        tool.unix_socket_access_mode()
    assert exc.value.reason_code == "IPC_PEER_CONFIG_REQUIRED"

    monkeypatch.setenv("XINAO_IPC_PEER_UIDS", "0")
    assert tool.unix_socket_access_mode() == 0o666

    for invalid in ("65534", "0,65534"):
        monkeypatch.setenv("XINAO_IPC_PEER_UIDS", invalid)
        with pytest.raises(tool.ToolExecutorError) as invalid_config:
            tool.unix_socket_access_mode()
        assert invalid_config.value.reason_code == "IPC_PEER_UID_CONFIG"

    monkeypatch.delenv("XINAO_IPC_PEER_UIDS", raising=False)
    monkeypatch.delenv("XINAO_IPC_PEER_REQUIRE", raising=False)
    assert tool.unix_socket_access_mode() == 0o600


def test_peer_gate_refuses_platform_without_linux_peer_credentials(
    tool: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XINAO_IPC_PEER_REQUIRE", "1")
    monkeypatch.setenv("XINAO_IPC_PEER_UIDS", "0")
    monkeypatch.delattr(tool.socket, "SO_PEERCRED", raising=False)

    class FakeConnection:
        def getsockopt(self, *_args: Any) -> bytes:
            raise AssertionError("numeric SO_PEERCRED fallback must not be attempted")

    with pytest.raises(tool.ToolExecutorError) as unavailable:
        tool.assert_unix_peer_allowed(FakeConnection())
    assert unavailable.value.reason_code == "IPC_PEER_CRED_UNAVAILABLE"


def test_canonical_specs_pin_transport_root_and_tool_peer_uid(specs: Any) -> None:
    transport = specs.transport_container_spec(
        image="transport",
        name="transport-ipc",
        auth_host_path="/host/auth.json",
        input_host_path="/host/input",
        output_host_path="/host/output",
        ipc_host_dir="/host/ipc",
    )
    tool = specs.tool_executor_container_spec(
        image="tool",
        name="tool-ipc",
        episode_lab_host_path="/host/lab",
        ipc_host_dir="/host/ipc",
    )
    assert transport["user"] == "0:0"
    assert tool["env"]["XINAO_IPC_PEER_REQUIRE"] == "1"
    assert tool["env"]["XINAO_IPC_PEER_UIDS"] == "0"


def test_ipc_mount_rewrite_matches_exact_target_and_keeps_copy_up(host: Any) -> None:
    original = [
        "docker",
        "create",
        "--mount",
        "type=bind,src=D:/episode/ipc,dst=/ipc",
        "--mount",
        "type=bind,src=D:/episode/ipc-other,dst=/ipc-other",
        "image",
    ]
    rewritten = host._replace_ipc_bind_with_volume(original, "xinao-ipc-volume")
    assert "type=volume,src=xinao-ipc-volume,dst=/ipc" in rewritten
    assert "volume-nocopy" not in " ".join(rewritten)
    assert "type=bind,src=D:/episode/ipc-other,dst=/ipc-other" in rewritten

    with pytest.raises(host.DualHostError) as exc:
        host._replace_ipc_bind_with_volume(
            ["docker", "create", "--mount", "type=bind,src=D:/x,dst=/ipc-extra", "image"],
            "xinao-ipc-volume",
        )
    assert exc.value.reason_code == "DUAL_HOST_IPC_MOUNT_REWRITE_FAILED"


def test_volume_inspect_requires_same_exact_name_and_source(host: Any) -> None:
    volume = "xinao-ipc-volume"
    source = f"/var/lib/docker/volumes/{volume}/_data"

    def doc(source_value: str, *, name: str = volume, kind: str = "volume") -> dict[str, Any]:
        return {
            "Mounts": [
                {
                    "Type": kind,
                    "Name": name,
                    "Source": source_value,
                    "Destination": "/ipc",
                    "RW": True,
                }
            ]
        }

    observed = host._require_exact_ipc_volume_mounts(
        tool_inspect=doc(source),
        transport_inspect=doc(source),
        expected_volume=volume,
    )
    assert observed == source

    with pytest.raises(host.DualHostError) as mismatch:
        host._require_exact_ipc_volume_mounts(
            tool_inspect=doc(source),
            transport_inspect=doc(source + "-foreign"),
            expected_volume=volume,
        )
    assert mismatch.value.reason_code == "DUAL_HOST_IPC_VOLUME_MISMATCH"

    with pytest.raises(host.DualHostError) as bind:
        host._require_exact_ipc_volume_mounts(
            tool_inspect=doc("D:/episode/ipc", name="", kind="bind"),
            transport_inspect=doc(source),
            expected_volume=volume,
        )
    assert bind.value.reason_code == "DUAL_HOST_IPC_VOLUME_MISMATCH"


def test_tool_socket_start_canary_accepts_only_expected_owner_mode(
    host: Any, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        args = list(argv)
        calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            '{"gid":65532,"is_socket":true,"mode":438,"uid":65532}\n',
            "",
        )

    cfg = host.DualHostConfig(
        transport_image="transport",
        tool_image="tool",
        auth_host_path=tmp_path / "auth.json",
        episode_root=tmp_path / "episode",
        runner=runner,
    )
    guardian = host.DualContainerHost(cfg)
    evidence = guardian._wait_for_tool_socket_ready("tool-container", timeout_seconds=0.1)
    assert evidence == {"gid": 65532, "is_socket": True, "mode": 0o666, "uid": 65532}
    assert calls and calls[0][:3] == ["docker", "exec", "tool-container"]
    assert "/ipc/tool.sock" in " ".join(calls[0])
    assert "os.lstat" in " ".join(calls[0])


def test_start_pair_waits_for_tool_socket_before_transport(
    host: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    guardian = host.DualContainerHost(
        host.DualHostConfig(
            transport_image="transport",
            tool_image="tool",
            auth_host_path=auth,
            episode_root=tmp_path / "episode",
            synthetic=True,
        )
    )
    guardian.create_pair(episode_id="ep_start_order", session_id="xrsess_start_order")
    guardian.config.synthetic = False
    events: list[str] = []

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        args = list(argv)
        if args[:2] == ["docker", "start"]:
            role = "tool" if "synthetic-tool" in args[-1] else "transport"
            events.append(f"start:{role}")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(guardian, "runner", runner)
    monkeypatch.setattr(
        guardian,
        "validate_before_start",
        lambda: {"status": "PRESTART_VALIDATED"},
    )

    def socket_ready(_container_id: str) -> dict[str, Any]:
        events.append("socket:ready")
        return {"uid": 65532, "gid": 65532, "mode": 0o666, "is_socket": True}

    monkeypatch.setattr(guardian, "_wait_for_tool_socket_ready", socket_ready)
    result = guardian.start_pair()
    assert result["status"] == "PAIR_STARTED"
    assert events == ["start:tool", "socket:ready", "start:transport"]


def test_require_live_pair_ready_rechecks_volume_and_socket(
    host: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    volume = "xinao-ipc-ep-live"
    source = f"/var/lib/docker/volumes/{volume}/_data"
    common = {
        "episode_id": "ep-live",
        "session_id": "xrsess-live",
        "tool_container_id": "tool-live",
        "transport_container_id": "transport-live",
        "tool_image_id": "sha256:tool",
        "transport_image_id": "sha256:transport",
        "ipc_mount_type": "volume",
        "ipc_volume": volume,
        "ipc_volume_source": source,
        "ipc_peer_uids": "0",
    }
    receipt = {**common, "schema_version": host.PAIR_RECEIPT_SCHEMA}
    receipt_hash = hashlib.sha256(host._canonical_bytes(receipt)).hexdigest()
    receipt["pair_receipt_sha256"] = receipt_hash
    lease = {
        **common,
        "schema_version": host.PAIR_LEASE_SCHEMA,
        "phase": "running",
        "pair_receipt_sha256": receipt_hash,
    }
    inventory = {
        "schema_version": host.SESSION_INVENTORY_SCHEMA,
        "episode_id": "ep-live",
        "host_session_id": "xrsess-live",
        "grok_session_id": "",
    }
    guardian = host.DualContainerHost(
        host.DualHostConfig(
            transport_image="transport",
            tool_image="tool",
            auth_host_path=tmp_path / "auth.json",
            episode_root=tmp_path / "episode",
        )
    )
    monkeypatch.setattr(guardian, "load_lease", lambda: dict(lease))
    monkeypatch.setattr(guardian, "load_pair_receipt", lambda: dict(receipt))
    monkeypatch.setattr(guardian, "load_session_inventory", lambda: dict(inventory))

    ipc_mount = {
        "Destination": "/ipc",
        "Source": source,
        "Name": volume,
        "Type": "volume",
        "RW": True,
    }
    tool_doc = {
        "Image": "sha256:tool",
        "Config": {"User": "65532:65532"},
        "HostConfig": {"NetworkMode": "none"},
        "State": {"Running": True},
        "Mounts": [ipc_mount],
    }
    transport_doc = {
        "Image": "sha256:transport",
        "Config": {"User": "0:0"},
        "HostConfig": {"NetworkMode": host.DEFAULT_TRANSPORT_NETWORK},
        "NetworkSettings": {"Networks": {host.DEFAULT_TRANSPORT_NETWORK: {}}},
        "State": {"Running": True},
        "Mounts": [
            {
                "Destination": "/grok-home/auth.json",
                "Source": "/host/auth.json",
                "Type": "bind",
                "RW": False,
            },
            ipc_mount,
        ],
    }
    monkeypatch.setattr(
        guardian,
        "_docker_inspect",
        lambda container_id: tool_doc if container_id == "tool-live" else transport_doc,
    )
    socket_observation = {
        "uid": 65532,
        "gid": 65532,
        "mode": 0o666,
        "is_socket": True,
    }
    calls: list[str] = []

    def socket_ready(container_id: str) -> dict[str, Any]:
        calls.append(container_id)
        return dict(socket_observation)

    monkeypatch.setattr(guardian, "_wait_for_tool_socket_ready", socket_ready)
    ready = guardian.require_live_pair_ready(
        expected_episode_id="ep-live",
        expected_host_session_id="xrsess-live",
    )
    assert ready["status"] == "LIVE_PAIR_READY"
    assert ready["tool_socket_ready"] == socket_observation
    assert calls == ["tool-live"]

    tool_doc["State"] = {}
    with pytest.raises(host.DualHostError) as missing_running:
        guardian.require_live_pair_ready(
            expected_episode_id="ep-live",
            expected_host_session_id="xrsess-live",
        )
    assert missing_running.value.reason_code == "DUAL_HOST_CONTAINER_STOPPED"


def test_synthetic_pair_carries_same_peer_identity_in_receipt(host: Any, tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    guardian = host.DualContainerHost(
        host.DualHostConfig(
            transport_image="transport",
            tool_image="tool",
            auth_host_path=auth,
            episode_root=tmp_path / "episode",
            synthetic=True,
        )
    )
    created = guardian.create_pair(episode_id="ep_ipc_pin", session_id="xrsess_ipc_pin")
    assert "XINAO_IPC_PEER_UIDS=0" in created["tool_create_argv"]
    assert created["pair_receipt"]["ipc_peer_uids"] == "0"
    assert created["lease"]["ipc_peer_uids"] == "0"
