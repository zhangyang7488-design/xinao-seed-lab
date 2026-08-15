from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from base64 import b64encode
from pathlib import Path

import pytest
import services.research_of_research.windows_job as windows_job
from services.research_of_research.windows_job import (
    JobState,
    WindowsJobError,
    query_named_job,
    spawn_windows_job_process,
    terminate_named_job,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object tests")


def _job_name() -> str:
    return f"Global\\XINAO-S-RoR-Test-{uuid.uuid4().hex}"


def _wait_for(
    predicate: object,
    *,
    timeout: float = 10.0,
) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()  # type: ignore[operator]
        if result:
            return result
        time.sleep(0.03)
    raise AssertionError("condition did not become true before timeout")


def _cleanup_job(job_name: str) -> None:
    terminate_named_job(job_name, exit_code=91)
    _wait_for(lambda: query_named_job(job_name).state == JobState.ABSENT, timeout=10.0)


def test_exact_stdio_job_state_and_existing_name_fail_closed(tmp_path: Path) -> None:
    job_name = _job_name()
    process = spawn_windows_job_process(
        [
            sys.executable,
            "-c",
            (
                "import sys,time; "
                "data=sys.stdin.buffer.read(); "
                "sys.stdout.buffer.write(b'out:'+data); sys.stdout.buffer.flush(); "
                "sys.stderr.buffer.write(b'err:'+data); sys.stderr.buffer.flush(); "
                "time.sleep(.15)"
            ),
        ],
        job_name=job_name,
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ,
    )
    try:
        snapshot = query_named_job(job_name)
        assert snapshot.state == JobState.PRESENT_NONEMPTY
        assert process.pid in snapshot.process_ids
        assert process.poll() is None

        with pytest.raises(WindowsJobError) as caught:
            spawn_windows_job_process(
                [sys.executable, "-c", "raise SystemExit(99)"],
                job_name=job_name,
                cwd=tmp_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ,
            )
        assert caught.value.reason_code == "JOB_ALREADY_EXISTS"
        assert process.poll() is None

        assert process.stdin is not None
        process.stdin.write(b"hello")
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert process.stdout is not None
        assert process.stderr is not None
        assert process.stdout.read() == b"out:hello"
        assert process.stderr.read() == b"err:hello"
        assert process.job_snapshot().state == JobState.PRESENT_EMPTY
        assert query_named_job(job_name).state == JobState.PRESENT_EMPTY
    finally:
        if process.poll() is None:
            process.terminate_tree(exit_code=91)
            process.wait(timeout=10)
        process.close()
    _wait_for(lambda: query_named_job(job_name).state == JobState.ABSENT)


def test_poll_waits_for_job_descendant_after_root_exits(tmp_path: Path) -> None:
    job_name = _job_name()
    descendant_code = "import time; time.sleep(1.0)"
    root_code = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{descendant_code!r}]); "
        "raise SystemExit(23)"
    )
    process = spawn_windows_job_process(
        [sys.executable, "-c", root_code],
        job_name=job_name,
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ,
    )
    try:
        assert process.stdin is not None
        process.stdin.close()
        descendant_snapshot = _wait_for(
            lambda: (
                snapshot
                if (
                    (snapshot := process.job_snapshot()).state == JobState.PRESENT_NONEMPTY
                    and process.pid not in snapshot.process_ids
                )
                else None
            )
        )
        assert descendant_snapshot.process_ids
        assert process.poll() is None
        assert process.wait(timeout=10) == 23
        assert process.job_snapshot().state == JobState.PRESENT_EMPTY
    finally:
        if process.poll() is None:
            process.terminate_tree(exit_code=91)
            process.wait(timeout=10)
        process.close()
    _wait_for(lambda: query_named_job(job_name).state == JobState.ABSENT)


def test_explicit_output_file_handles_match_production_shape(tmp_path: Path) -> None:
    job_name = _job_name()
    stdout_path = tmp_path / "stdout.bin"
    stderr_path = tmp_path / "stderr.bin"
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        process = spawn_windows_job_process(
            [
                sys.executable,
                "-c",
                (
                    "import sys; data=sys.stdin.buffer.read(); "
                    "sys.stdout.buffer.write(b'file-out:'+data); "
                    "sys.stderr.buffer.write(b'file-err:'+data)"
                ),
            ],
            job_name=job_name,
            cwd=tmp_path,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            env=os.environ,
        )
        try:
            assert process.stdout is None
            assert process.stderr is None
            assert process.stdin is not None
            process.stdin.write(b"payload")
            process.stdin.close()
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.terminate_tree(exit_code=91)
                process.wait(timeout=10)
            process.close()
    assert stdout_path.read_bytes() == b"file-out:payload"
    assert stderr_path.read_bytes() == b"file-err:payload"
    _wait_for(lambda: query_named_job(job_name).state == JobState.ABSENT)


def test_exit_code_259_is_terminal_when_process_handle_is_signaled(tmp_path: Path) -> None:
    """259 is also STILL_ACTIVE, so GetExitCodeProcess alone is ambiguous."""

    job_name = _job_name()
    process = spawn_windows_job_process(
        [sys.executable, "-c", "import os; os._exit(259)"],
        job_name=job_name,
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ,
    )
    try:
        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=10) == 259
        assert process.poll() == 259
    finally:
        if process.poll() is None:
            process.terminate_tree(exit_code=91)
            process.wait(timeout=10)
        process.close()
    _wait_for(lambda: query_named_job(job_name).state == JobState.ABSENT)


def test_terminate_tree_uses_job_and_ends_all_members(tmp_path: Path) -> None:
    job_name = _job_name()
    root_code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "time.sleep(30)"
    )
    process = spawn_windows_job_process(
        [sys.executable, "-c", root_code],
        job_name=job_name,
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ,
    )
    try:
        assert process.stdin is not None
        process.stdin.close()
        populated = _wait_for(
            lambda: snapshot if len((snapshot := process.job_snapshot()).process_ids) >= 2 else None
        )
        assert process.pid in populated.process_ids
        process.terminate_tree(exit_code=77)
        assert process.wait(timeout=10) == 77
        assert process.job_snapshot().state == JobState.PRESENT_EMPTY
    finally:
        if process.poll() is None:
            process.terminate_tree(exit_code=91)
            process.wait(timeout=10)
        process.close()
    _wait_for(lambda: query_named_job(job_name).state == JobState.ABSENT)


def test_inherited_keepalive_preserves_name_after_spawner_death(tmp_path: Path) -> None:
    """This fails if the apparently-unused inherited Job handle is removed."""

    job_name = _job_name()
    helper = (
        "import os,subprocess,sys; "
        "from services.research_of_research.windows_job import spawn_windows_job_process; "
        "p=spawn_windows_job_process("
        "[sys.executable,'-c','import time; time.sleep(30)'],"
        f"job_name={job_name!r},cwd={str(tmp_path)!r},"
        "stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=os.environ); "
        "p.stdin.close(); "
        "print(p.pid,flush=True); "
        "os._exit(0)"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", helper],
            cwd=Path.cwd(),
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env=os.environ,
        )
        child_pid = int(completed.stdout.strip())
        snapshot = query_named_job(job_name)
        assert snapshot.state == JobState.PRESENT_NONEMPTY
        assert child_pid in snapshot.process_ids
        before = terminate_named_job(job_name, exit_code=79)
        assert before.state == JobState.PRESENT_NONEMPTY
    finally:
        _cleanup_job(job_name)


def test_powershell_carrier_keeps_anchor_and_child_in_same_job(tmp_path: Path) -> None:
    """Exercise the production carrier shape, not only a Python root process."""

    powershell = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        pytest.skip("Windows PowerShell carrier is not installed")

    job_name = _job_name()
    command = f"& '{sys.executable}' -c 'import time; time.sleep(30)'"
    encoded = b64encode(command.encode("utf-16-le")).decode("ascii")
    helper = (
        "import os,subprocess,sys; "
        "from services.research_of_research.windows_job import spawn_windows_job_process; "
        "p=spawn_windows_job_process("
        f"[{str(powershell)!r},'-NoLogo','-NoProfile','-NonInteractive',"
        f"'-EncodedCommand',{encoded!r}],"
        f"job_name={job_name!r},cwd={str(tmp_path)!r},"
        "stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=os.environ); "
        "p.stdin.close(); "
        "print(p.pid,flush=True); "
        "os._exit(0)"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", helper],
            cwd=Path.cwd(),
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env=os.environ,
        )
        carrier_pid = int(completed.stdout.strip())
        snapshot = _wait_for(
            lambda: (
                current if len((current := query_named_job(job_name)).process_ids) >= 2 else None
            )
        )
        assert snapshot.state == JobState.PRESENT_NONEMPTY
        assert carrier_pid in snapshot.process_ids
        assert any(pid != carrier_pid for pid in snapshot.process_ids)
    finally:
        _cleanup_job(job_name)


def test_open_access_failure_is_unknown_not_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DeniedDll:
        @staticmethod
        def OpenJobObjectW(_access: int, _inherit: bool, _name: str) -> int:
            import ctypes

            ctypes.set_last_error(5)
            return 0

    class _DeniedKernel:
        dll = _DeniedDll()

    monkeypatch.setattr(windows_job, "_kernel32", lambda: _DeniedKernel())
    snapshot = query_named_job(_job_name())
    assert snapshot.state == JobState.UNKNOWN
    assert snapshot.winerror == 5
    assert snapshot.process_ids == ()


def test_named_job_absence_and_validation_are_typed(tmp_path: Path) -> None:
    job_name = _job_name()
    absent = query_named_job(job_name)
    assert absent.state == JobState.ABSENT
    assert absent.process_ids == ()

    with pytest.raises(WindowsJobError) as caught:
        query_named_job("Local\\not-admitted")
    assert caught.value.reason_code == "JOB_NAME_INVALID"

    with pytest.raises(WindowsJobError) as caught:
        spawn_windows_job_process(
            ["python", "-c", "pass"],
            job_name=job_name,
            cwd=tmp_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ,
        )
    assert caught.value.reason_code == "EXECUTABLE_INVALID"


def test_job_snapshots_are_json_serializable_without_pid_authority(tmp_path: Path) -> None:
    job_name = _job_name()
    snapshot = query_named_job(job_name)
    encoded = json.dumps(
        {
            "job_name": snapshot.job_name,
            "state": snapshot.state.value,
            "process_ids": list(snapshot.process_ids),
            "winerror": snapshot.winerror,
        },
        sort_keys=True,
    )
    assert '"state": "ABSENT"' in encoded
