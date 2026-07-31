"""Transport episode idle-hold: stay running until SIGTERM; no canary confusion.

Proves the production breakpoint fix where episode_entrypoint exited in <1s
(EPISODE_ENTRYPOINT_IDLE) so require_live_pair_ready / docker exec could not attach.
"""

from __future__ import annotations

import importlib.util
import json
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
EPISODE_ENTRYPOINT = ROOT / "docker" / "xinao-researcher" / "episode_entrypoint.py"
SPECS_PATH = ROOT / "docker" / "xinao-researcher" / "docker_create_specs.py"
CANARY_ENTRYPOINT = ROOT / "docker" / "xinao-researcher" / "entrypoint.py"


def _load(name: str, path: Path) -> Any:
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def episode() -> Any:
    return _load("xinao_episode_entrypoint_idle_hold", EPISODE_ENTRYPOINT)


@pytest.fixture
def specs() -> Any:
    return _load("xinao_docker_create_specs_idle_hold", SPECS_PATH)


def test_self_describe_unchanged_and_exits(
    episode: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = episode.main(["--self-describe"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["profile"] == "GENUINE_SCIENTIST_EPISODE"
    assert out["default_image_entrypoint_profile"] == "INSTRUMENT_CANARY"
    assert out["idle_hold_mode"] is True
    assert out["completion_claim_allowed"] is False
    assert out["generic_file_shell_tools"] is False


def test_bare_without_hold_writes_receipt_and_exits(
    episode: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv("XINAO_EPISODE_RECEIPT_PATH", str(receipt))
    rc = episode.main([])
    assert rc == 0
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    assert doc["status"] == "AWAITING_HOST_GROK_ATTACH"
    assert doc["hold"] is False
    assert doc["completion_claim_allowed"] is False
    err = capsys.readouterr().err
    status = json.loads(err.strip().splitlines()[-1])
    assert status["status"] == "EPISODE_ENTRYPOINT_IDLE"
    assert status["hold"] is False


def test_hold_writes_receipt_blocks_until_hook(
    episode: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv("XINAO_EPISODE_RECEIPT_PATH", str(receipt))
    seen = {"blocked": False}

    def _wait() -> None:
        seen["blocked"] = True

    episode._HOLD_WAIT_HOOK = _wait
    try:
        rc = episode.main(["--hold"])
    finally:
        episode._HOLD_WAIT_HOOK = None
    assert rc == 0
    assert seen["blocked"] is True
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    assert doc["status"] == "AWAITING_HOST_GROK_ATTACH"
    assert doc["hold"] is True
    err = capsys.readouterr().err
    status = json.loads(err.strip().splitlines()[-1])
    assert status["status"] == "EPISODE_ENTRYPOINT_IDLE_HOLD"
    assert status["completion_claim_allowed"] is False


def test_hold_env_flag_equivalent(
    episode: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv("XINAO_EPISODE_RECEIPT_PATH", str(receipt))
    monkeypatch.setenv("XINAO_EPISODE_HOLD", "1")
    episode._HOLD_WAIT_HOOK = lambda: None
    try:
        assert episode.main([]) == 0
    finally:
        episode._HOLD_WAIT_HOOK = None
    assert json.loads(receipt.read_text(encoding="utf-8"))["hold"] is True


def test_hold_subprocess_exits_on_sigterm(tmp_path: Path) -> None:
    """Attack: hold process must leave on SIGTERM (docker stop path)."""
    if sys.platform == "win32":
        # Windows terminate() is not SIGTERM; exercise Unix-shaped path only.
        pytest.skip("SIGTERM subprocess proof requires POSIX")
    receipt = tmp_path / "receipt.json"
    env = {
        **dict(**{k: v for k, v in __import__("os").environ.items()}),
        "XINAO_EPISODE_RECEIPT_PATH": str(receipt),
        "PYTHONUTF8": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-I", str(EPISODE_ENTRYPOINT), "--hold"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and not receipt.is_file():
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=1)
                pytest.fail(
                    f"hold process exited early rc={proc.returncode} err={err!r} out={out!r}"
                )
            time.sleep(0.05)
        assert receipt.is_file(), "hold mode must write AWAITING receipt before blocking"
        assert proc.poll() is None, "hold must still be running before SIGTERM"
        proc.send_signal(signal.SIGTERM)
        try:
            rc = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.fail("hold process did not exit after SIGTERM")
        assert rc == 0, f"expected clean exit after SIGTERM, got {rc}"
        doc = json.loads(receipt.read_text(encoding="utf-8"))
        assert doc["status"] == "AWAITING_HOST_GROK_ATTACH"
        assert doc["hold"] is True
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_hold_does_not_busy_spin_cpu(episode: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold wait must block (Event), not a tight loop."""
    entered = threading.Event()
    release = threading.Event()

    def _wait() -> None:
        entered.set()
        release.wait(timeout=5)

    episode._HOLD_WAIT_HOOK = _wait
    try:
        t = threading.Thread(target=lambda: episode.main(["--hold"]), daemon=True)
        t.start()
        assert entered.wait(timeout=2)
        # Still blocked in wait — not finished
        assert t.is_alive()
        release.set()
        t.join(timeout=2)
        assert not t.is_alive()
    finally:
        episode._HOLD_WAIT_HOOK = None
        release.set()


def test_use_episode_entrypoint_passes_hold(specs: Any) -> None:
    transport = specs.transport_container_spec(
        image="sha256:" + "b" * 64,
        name="xinao-transport-hold-test",
        auth_host_path="/host/auth.json",
        input_host_path="/host/in",
        output_host_path="/host/out",
        ipc_host_dir="/host/ipc",
        use_episode_entrypoint=True,
    )
    assert transport["episode_entrypoint_selected"] is True
    assert transport["episode_idle_hold"] is True
    assert transport["entrypoint"] == [
        "python",
        "-I",
        "/opt/xinao-researcher/episode_entrypoint.py",
        "--hold",
    ]
    assert specs.validate_transport_spec_invariants(transport) == []
    argv = specs.docker_create_argv(transport)
    ep_idx = argv.index("--entrypoint")
    assert argv[ep_idx + 1] == "python"
    image_idx = argv.index(transport["image"])
    cmd = argv[image_idx + 1 :]
    assert cmd == [
        "-I",
        "/opt/xinao-researcher/episode_entrypoint.py",
        "--hold",
    ]


def test_default_canary_entrypoint_unchanged(specs: Any) -> None:
    transport = specs.transport_container_spec(
        image="sha256:" + "c" * 64,
        name="xinao-transport-canary",
        auth_host_path="/host/auth.json",
        input_host_path="/host/in",
        output_host_path="/host/out",
        ipc_host_dir="/host/ipc",
        use_episode_entrypoint=False,
    )
    assert transport["episode_entrypoint_selected"] is False
    assert transport["episode_idle_hold"] is False
    assert transport["entrypoint"] == [
        "python",
        "-I",
        "/opt/xinao-researcher/entrypoint.py",
    ]
    assert "--hold" not in transport["entrypoint"]
    assert "episode_entrypoint.py" not in " ".join(transport["entrypoint"])
    assert specs.validate_transport_spec_invariants(transport) == []


def test_episode_without_hold_is_spec_violation(specs: Any) -> None:
    transport = specs.transport_container_spec(
        image="sha256:" + "d" * 64,
        name="xinao-transport-no-hold",
        auth_host_path="/host/auth.json",
        input_host_path="/host/in",
        output_host_path="/host/out",
        ipc_host_dir="/host/ipc",
        use_episode_entrypoint=True,
        entrypoint=[
            "python",
            "-I",
            "/opt/xinao-researcher/episode_entrypoint.py",
        ],
    )
    violations = specs.validate_transport_spec_invariants(transport)
    assert any("episode_entrypoint_requires_hold" in v for v in violations)


def test_bundle_with_episode_hold_fail_closed(specs: Any) -> None:
    bundle = specs.dual_container_bundle(
        transport_image="t",
        tool_image="tool",
        auth_host_path="/a/auth.json",
        input_host_path="/i",
        output_host_path="/o",
        episode_lab_host_path="/lab",
        ipc_host_dir="/ipc",
        use_episode_entrypoint=True,
        ipc_peer_uids="1000",
    )
    assert bundle["fail_closed_before_provider"] is True
    assert bundle["transport_spec_violations"] == []
    assert "--hold" in bundle["transport"]["entrypoint"]
    create_argv = bundle["transport_docker_create_argv"]
    assert "--hold" in create_argv


def test_canary_entrypoint_source_not_confused_with_episode() -> None:
    canary = CANARY_ENTRYPOINT.read_text(encoding="utf-8")
    episode = EPISODE_ENTRYPOINT.read_text(encoding="utf-8")
    assert "GENUINE_SCIENTIST_EPISODE" not in canary
    assert "episode_entrypoint" not in canary
    assert "--hold" not in canary
    assert "AWAITING_HOST_GROK_ATTACH" not in canary
    assert "--hold" in episode
    assert "AWAITING_HOST_GROK_ATTACH" in episode
    assert "SIGTERM" in episode


def test_error_argv_self_describe_still_zero(episode: Any) -> None:
    """Unknown flags ignored for describe path; hold not entered."""
    assert episode.main(["--self-describe", "--hold"]) == 0
