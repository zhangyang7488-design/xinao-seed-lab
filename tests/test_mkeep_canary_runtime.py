from __future__ import annotations

import base64
import json
import uuid

from scripts.verify_mkeep_canary import _cim_command_identity, _spawn, _windows_identity


def test_disposable_fixture_uses_one_real_process_identity() -> None:
    marker = f"mkeep-test-{uuid.uuid4().hex}"
    process = _spawn(["--fixture", "--marker", marker])
    try:
        assert process.stdout is not None
        assert process.stdin is not None
        ready = json.loads(process.stdout.readline())
        assert ready["marker"] == marker
        fixture_pid = int(ready["pid"])
        assert fixture_pid > 0
        assert _windows_identity(fixture_pid)["pid"] == fixture_pid
        command_identity = _cim_command_identity(
            fixture_pid, marker, {process.pid, fixture_pid}
        )
        assert command_identity["marker_ok"] is True
        assert command_identity["parent_pid"] == process.pid
        process.stdin.write(json.dumps({"command": "exit"}) + "\n")
        process.stdin.flush()
        process.stdout.readline()
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def test_observer_crash_probe_exits_without_touching_a_fixture() -> None:
    marker = f"mkeep-test-{uuid.uuid4().hex}"
    binding = {
        "session_id": marker,
        "generation": 1,
        "pid": 1,
        "process_created_at": "created",
        "executable_path": "python.exe",
        "command_line_marker": marker,
        "logon_session": 1,
        "parent_pid": 2,
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "snapshot": {"managed_session": True, "ready": True},
                "binding": binding,
                "expected_binding": binding,
            }
        ).encode("utf-8")
    ).decode("ascii")
    process = _spawn(
        ["--observer-crash", "--marker", marker, "--payload", payload]
    )
    assert process.wait(timeout=10) == 73
