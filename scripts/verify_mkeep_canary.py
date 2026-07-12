#!/usr/bin/env python3
"""One bounded real T10 canary; no scheduler, daemon, recovery, or TUI attachment."""

from __future__ import annotations

import argparse
import base64
import contextlib
import ctypes
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Child helpers must use the exact invoking environment: the base interpreter
# lacks the pinned project dependencies and would not exercise the shipped module.
PYTHON_EXE = sys.executable
WINDOWLESS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _windows_identity(pid: int) -> dict[str, Any]:
    if os.name != "nt":
        return {
            "pid": pid,
            "process_created_at": "non-windows",
            "executable_path": sys.executable,
            "logon_session": 0,
        }
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_bool
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
    kernel32.ProcessIdToSessionId.argtypes = [ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.ProcessIdToSessionId.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed")
    try:
        creation = ctypes.c_ulonglong()
        exit_time = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise OSError(ctypes.get_last_error(), "GetProcessTimes failed")
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), "QueryFullProcessImageNameW failed")
        session = ctypes.c_ulong()
        if not kernel32.ProcessIdToSessionId(pid, ctypes.byref(session)):
            raise OSError(ctypes.get_last_error(), "ProcessIdToSessionId failed")
        return {
            "pid": pid,
            "process_created_at": str(creation.value),
            "executable_path": str(Path(buffer.value).resolve()),
            "logon_session": int(session.value),
        }
    finally:
        kernel32.CloseHandle(handle)


def _cim_command_identity(pid: int, marker: str, observed_pids: set[int] | None = None) -> dict[str, Any]:
    """Read parent/command-marker identity once through the native CIM surface."""
    if os.name != "nt":
        return {
            "ok": True,
            "pid": pid,
            "parent_pid": os.getpid(),
            "marker_ok": True,
            "probe_exited": True,
            "probe_no_window": True,
        }
    escaped = marker.replace("'", "''")
    code = (
        f'$p=Get-CimInstance Win32_Process -Filter "ProcessId={pid}";'
        f"$marker='{escaped}';"
        "if($null -eq $p){exit 4};"
        "[pscustomobject]@{pid=[int]$p.ProcessId;parent_pid=[int]$p.ParentProcessId;"
        "marker_ok=[bool]($p.CommandLine -like ('*'+$marker+'*'))}"
        "|ConvertTo-Json -Compress"
    )
    probe = subprocess.Popen(
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=WINDOWLESS,
    )
    if observed_pids is not None:
        observed_pids.add(probe.pid)
    try:
        stdout, stderr = probe.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        probe.kill()
        stdout, stderr = probe.communicate(timeout=10)
        return {
            "ok": False,
            "pid": pid,
            "probe_pid": probe.pid,
            "probe_exited": probe.poll() is not None,
            "probe_no_window": WINDOWLESS != 0,
            "timed_out": True,
        }
    if probe.returncode != 0:
        return {
            "ok": False,
            "pid": pid,
            "probe_pid": probe.pid,
            "probe_exited": True,
            "probe_no_window": WINDOWLESS != 0,
            "exit_code": probe.returncode,
            "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        }
    value = json.loads(stdout)
    return {
        "ok": True,
        "pid": int(value["pid"]),
        "probe_pid": probe.pid,
        "parent_pid": int(value["parent_pid"]),
        "marker_ok": value["marker_ok"] is True,
        "probe_exited": True,
        "probe_no_window": WINDOWLESS != 0,
    }


def _window_snapshot(pids: set[int]) -> dict[str, Any]:
    if os.name != "nt":
        return {
            "visible_window_count": 0,
            "visible_window_pids": [],
            "foreground_pid": None,
        }
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows.argtypes = [callback_type, ctypes.c_void_p]
    user32.EnumWindows.restype = ctypes.c_bool
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.GetWindowThreadProcessId.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.GetForegroundWindow.restype = ctypes.c_void_p

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in pids:
                found.append(int(pid.value))
        return True

    user32.EnumWindows(callback, 0)
    foreground = user32.GetForegroundWindow()
    foreground_pid = ctypes.c_ulong()
    if foreground:
        user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
    return {
        "visible_window_count": len(found),
        "visible_window_pids": sorted(set(found)),
        "foreground_pid": int(foreground_pid.value) if foreground else None,
    }


def _fixture(marker: str) -> int:
    print(json.dumps({"ready": True, "marker": marker, "pid": os.getpid()}), flush=True)
    for line in sys.stdin:
        value = json.loads(line)
        if value.get("command") == "exit":
            print(json.dumps({"exiting": True, "marker": marker}), flush=True)
            return 0
        print(
            json.dumps(
                {
                    "marker": marker,
                    "snapshot": value.get("snapshot") or {},
                    "pid": os.getpid(),
                }
            ),
            flush=True,
        )
    return 0


def _spawn(args: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [PYTHON_EXE, str(Path(__file__).resolve()), *args],
        cwd=REPO,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=WINDOWLESS,
    )


def _readline_timeout(stream: Any, timeout: float, label: str) -> str:
    result: queue.Queue[object] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            result.put(stream.readline())
        except BaseException as exc:  # pragma: no cover - defensive pipe failure
            result.put(exc)

    thread = threading.Thread(target=read, name=f"mkeep-read-{label}", daemon=True)
    thread.start()
    try:
        value = result.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError(f"timed out reading {label}") from exc
    if isinstance(value, BaseException):
        raise value
    if not isinstance(value, str) or not value:
        raise EOFError(f"unexpected EOF reading {label}")
    return value


def _terminate(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class _WindowMonitor:
    """Continuously observe attributable child windows and foreground ownership."""

    def __init__(self, pids: set[int]) -> None:
        self.pids = pids
        self.samples = 0
        self.max_visible = 0
        self.visible_pids: set[int] = set()
        self.foreground_owned = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mkeep-window-monitor", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            current = set(self.pids)
            snapshot = _window_snapshot(current)
            self.samples += 1
            self.max_visible = max(self.max_visible, int(snapshot["visible_window_count"]))
            self.visible_pids.update(int(pid) for pid in snapshot["visible_window_pids"])
            if snapshot.get("foreground_pid") in current:
                self.foreground_owned = True
            self._stop.wait(0.01)


def _exchange(process: subprocess.Popen[str], snapshot: dict[str, Any]) -> dict[str, Any]:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps({"snapshot": snapshot}) + "\n")
    process.stdin.flush()
    response = json.loads(_readline_timeout(process.stdout, 10, "fixture response"))
    if not isinstance(response, dict):
        raise TypeError("fixture response must be an object")
    return response


def build_evidence(duration_seconds: float, run_id: str) -> dict[str, object]:
    from xinao_coordination.m_keep import (
        OBSERVATION_STATES,
        m_keep_policy,
        observe_snapshot,
    )

    marker = f"mkeep-canary-{run_id}"
    source_paths = {
        "m_keep": REPO / "src" / "xinao_coordination" / "m_keep.py",
        "module_config": REPO / "src" / "xinao_coordination" / "module_config.py",
        "config": REPO / "configs" / "modules" / "m_keep.toml",
        "verifier": Path(__file__).resolve(),
    }
    source_hashes_start = {name: _sha256(path) for name, path in source_paths.items()}
    process = _spawn(["--fixture", "--marker", marker])
    observed_pids = {os.getpid(), process.pid}
    monitor = _WindowMonitor(observed_pids)
    monitor.start()
    started = time.monotonic()
    crash: subprocess.Popen[str] | None = None
    crash_result: dict[str, Any] = {}
    crash_stdout = ""
    crash_preserved_identity = False
    process_exited = False
    monitor_stopped = False
    samples: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    try:
        assert process.stdout is not None
        ready = json.loads(_readline_timeout(process.stdout, 10, "fixture readiness"))
        if ready.get("marker") != marker or ready.get("ready") is not True:
            raise RuntimeError("fixture did not establish the exact marker")
        fixture_pid = int(ready["pid"])
        observed_pids.add(fixture_pid)
        native = _windows_identity(fixture_pid)
        launcher_identity = _cim_command_identity(process.pid, marker, observed_pids)
        command_identity = _cim_command_identity(fixture_pid, marker, observed_pids)
        binding = {
            "session_id": marker,
            "generation": 1,
            "pid": fixture_pid,
            "process_created_at": native["process_created_at"],
            "executable_path": native["executable_path"],
            "command_line_marker": marker,
            "logon_session": native["logon_session"],
            "parent_pid": command_identity.get("parent_pid"),
        }
        native_identity_exact = bool(
            command_identity.get("ok") is True
            and command_identity.get("pid") == fixture_pid
            and command_identity.get("parent_pid") == process.pid
            and command_identity.get("marker_ok") is True
            and command_identity.get("probe_exited") is True
            and command_identity.get("probe_no_window") is True
            and launcher_identity.get("ok") is True
            and launcher_identity.get("pid") == process.pid
            and launcher_identity.get("parent_pid") == os.getpid()
            and launcher_identity.get("marker_ok") is True
            and Path(str(native.get("executable_path") or "")).resolve()
            == Path(str(getattr(sys, "_base_executable", sys.executable))).resolve()
        )
        cases = [
            ("LIVENESS", {"managed_session": True, "alive": True}),
            ("READINESS", {"managed_session": True, "ready": True, "active_turn": True}),
            ("PROGRESS", {"managed_session": True, "progress": True}),
            ("WAITING_INPUT", {"managed_session": True, "waiting_input": True}),
            ("READY_IDLE", {"managed_session": True, "ready": True}),
            ("CAPACITY_ERROR", {"managed_session": True, "capacity_error": True}),
        ]
        interval = duration_seconds / max(1, len(cases) - 1)
        foreground_start = _window_snapshot({fixture_pid, process.pid, os.getpid()}).get("foreground_pid")
        for index, (expected, snapshot) in enumerate(cases):
            target = started + (interval * index)
            remaining = target - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            fixture = _exchange(process, snapshot)
            native_now = _windows_identity(fixture_pid)
            observed = observe_snapshot(
                fixture["snapshot"],
                binding=binding,
                expected_binding=binding,
            )
            window = _window_snapshot({fixture_pid, process.pid, os.getpid()})
            windows.append(window)
            samples.append(
                {
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "expected": expected,
                    "fixture": fixture,
                    "observed": observed,
                    "native_identity_unchanged": native_now == native,
                    "window": window,
                }
            )
            if index == 1:
                fault_payload = {
                    "snapshot": {"managed_session": True, "progress": True},
                    "binding": binding,
                    "expected_binding": binding,
                }
                encoded = base64.urlsafe_b64encode(
                    json.dumps(fault_payload, separators=(",", ":")).encode("utf-8")
                ).decode("ascii")
                crash = _spawn(["--observer-crash", "--marker", marker, "--payload", encoded])
                observed_pids.add(crash.pid)
                try:
                    crash_stdout, _ = crash.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    crash.kill()
                    crash_stdout, _ = crash.communicate(timeout=5)
                with contextlib.suppress(json.JSONDecodeError):
                    parsed = json.loads(crash_stdout)
                    if isinstance(parsed, dict):
                        crash_result = parsed
                crash_preserved_identity = _windows_identity(fixture_pid) == native

        incomplete = observe_snapshot(
            {"managed_session": True, "ready": True},
            binding={"session_id": marker},
            expected_binding=binding,
        )
        old_owner = observe_snapshot(
            {"managed_session": True, "ready": True},
            binding={**binding, "generation": 0},
            expected_binding=binding,
        )
        stopped = observe_snapshot(
            {"managed_session": True, "ready": True},
            binding=binding,
            expected_binding=binding,
            stop_active=True,
        )
        paused = observe_snapshot(
            {"managed_session": True, "ready": True},
            binding=binding,
            expected_binding=binding,
            pause_active=True,
        )
        restart_cap = observe_snapshot(
            {"managed_session": True, "capacity_error": True, "restart_count": 3},
            binding=binding,
            expected_binding=binding,
        )
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"command": "exit"}) + "\n")
        process.stdin.flush()
        exit_ack = json.loads(_readline_timeout(process.stdout, 10, "fixture exit acknowledgement"))
        process.wait(timeout=10)
        fixture_child_exited = False
        try:
            _windows_identity(fixture_pid)
        except OSError:
            fixture_child_exited = True
        process_exited = process.returncode == 0 and exit_ack.get("exiting") is True and fixture_child_exited
        foreground_end = _window_snapshot({fixture_pid, process.pid, os.getpid()}).get("foreground_pid")
        elapsed = time.monotonic() - started
        monitor.stop()
        monitor_stopped = True
        policy = m_keep_policy()
        source_hashes_end = {name: _sha256(path) for name, path in source_paths.items()}
        module_source = source_paths["m_keep"].read_text(encoding="utf-8").lower()
        forbidden_module_primitives = (
            "import subprocess",
            "popen(",
            "createprocess",
            "sendkeys",
            "register-scheduledtask",
            "start-process",
        )
        crash_observation = (
            crash_result.get("observation") if isinstance(crash_result.get("observation"), dict) else {}
        )
        checks = {
            "capability_installed": policy["capability_installed"] is True,
            "default_disabled": policy["enabled"] is False,
            "observe_only": policy["observe_only"] is True,
            "no_timer_or_daemon": policy["timer"] is False and policy["daemon"] is False,
            "real_observation_window": elapsed >= 60.0 and duration_seconds >= 60.0,
            "all_states_observed": {item["observed"]["observation"] for item in samples}
            == OBSERVATION_STATES,
            "native_identity_verified": native_identity_exact
            and all(
                item["observed"]["identity_verified"] is True and item["native_identity_unchanged"] is True
                for item in samples
            ),
            "ambiguous_identity_needs_user": incomplete["identity_verified"] is False
            and incomplete["next_action"] == "NEEDS_USER",
            "old_owner_fenced": old_owner["identity_verified"] is False
            and old_owner["identity_mismatches"] == ["generation"],
            "stop_pause_never_recovers": stopped["stop_active"] is True
            and paused["pause_active"] is True
            and stopped["recovery_attempted"] is False
            and paused["recovery_attempted"] is False,
            "observer_crash_did_not_restart_or_kill_fixture": crash is not None
            and crash.returncode == 73
            and crash_result.get("marker") == marker
            and crash_observation.get("observation") == "PROGRESS"
            and crash_observation.get("identity_verified") is True
            and crash_preserved_identity
            and all(item["fixture"]["pid"] == fixture_pid for item in samples),
            "restart_cap_needs_user": restart_cap["next_action"] == "NEEDS_USER"
            and restart_cap["restart_count"] == 3
            and restart_cap["restart_cap"] == 0
            and restart_cap["restart_cap_reached"] is True
            and restart_cap["recovery_attempted"] is False,
            "continuous_window_monitor_ran": monitor.samples >= 100,
            "zero_visible_windows": monitor.max_visible == 0,
            "foreground_never_owned_by_canary": monitor.foreground_owned is False,
            "fixture_and_observer_exited": process_exited and crash is not None and crash.poll() == 73,
            "no_session_side_effects": all(
                not any(item["observed"]["side_effects"].values()) for item in samples
            ),
            "not_attached_to_tui": policy["tui_attached"] is False,
            "module_has_no_process_or_persistence_primitives": all(
                token not in module_source for token in forbidden_module_primitives
            ),
            "sources_stable_during_run": source_hashes_start == source_hashes_end,
        }
        return {
            "schema_version": "xinao.m_keep.canary.v2",
            "run_id": run_id,
            "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ok": all(checks.values()),
            "completion_claim_allowed": all(checks.values()),
            "policy": policy,
            "checks": checks,
            "managed_session_canary": {
                "observation_seconds": round(elapsed, 3),
                "single_process_sampling_observer": True,
                "managed_session_process_count": 1,
                "fault_injection_observer_process_count": 1,
                "native_session_identity_verified": checks["native_identity_verified"],
                "stop_pause_cases_passed": checks["stop_pause_never_recovers"],
                "observer_crash_case_passed": checks["observer_crash_did_not_restart_or_kill_fixture"],
                "old_owner_case_passed": checks["old_owner_fenced"],
                "restart_cap_case_passed": checks["restart_cap_needs_user"],
                "visible_window_count": monitor.max_visible,
                "continuous_window_samples": monitor.samples,
                "visible_window_pids": sorted(monitor.visible_pids),
                "foreground_unchanged": foreground_start == foreground_end,
                "foreground_never_owned_by_canary": monitor.foreground_owned is False,
                "processes_exited": checks["fixture_and_observer_exited"],
                "binding": binding,
                "native_identity": native,
                "launcher_identity": launcher_identity,
                "command_identity": command_identity,
                "observer_crash": {
                    "pid": crash.pid if crash is not None else None,
                    "exit_code": crash.returncode if crash is not None else None,
                    "result": crash_result,
                    "stdout_tail": crash_stdout[-1000:],
                    "stdout_sha256": hashlib.sha256(crash_stdout.encode("utf-8")).hexdigest(),
                    "fixture_identity_preserved": crash_preserved_identity,
                },
            },
            "samples": samples,
            "negative_cases": {
                "incomplete_binding": incomplete,
                "old_owner": old_owner,
                "stop": stopped,
                "pause": paused,
                "restart_cap": restart_cap,
            },
            "negative_effects": {
                "continuous_visible_window_count": monitor.max_visible,
                "continuous_foreground_owned": monitor.foreground_owned,
                "child_processes_exited": checks["fixture_and_observer_exited"],
                "module_forbidden_primitives_absent": checks[
                    "module_has_no_process_or_persistence_primitives"
                ],
            },
            "source_hashes_start": source_hashes_start,
            "source_hashes_end": source_hashes_end,
        }
    finally:
        if not monitor_stopped:
            monitor.stop()
        _terminate(process)
        _terminate(crash)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\S6_mkeep_canary_latest.json",
    )
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--observer-crash", action="store_true")
    parser.add_argument("--marker", default="")
    parser.add_argument("--payload", default="")
    args = parser.parse_args()
    if args.fixture:
        return _fixture(args.marker)
    if args.observer_crash:
        from xinao_coordination.m_keep import observe_snapshot

        decoded = base64.urlsafe_b64decode(args.payload.encode("ascii"))
        value = json.loads(decoded)
        observation = observe_snapshot(
            value["snapshot"],
            binding=value["binding"],
            expected_binding=value["expected_binding"],
        )
        print(
            json.dumps({"observer_crash": True, "marker": args.marker, "observation": observation}),
            flush=True,
        )
        # Stay observable long enough for the external 10 ms window monitor,
        # then emulate an abrupt observer failure without cleanup/restart hooks.
        time.sleep(0.2)
        os._exit(73)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex

    def write(value: dict[str, object]) -> None:
        temporary = output.with_name(f".{output.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, output)

    # Invalidate any older PASS before work begins.  A crash or forced stop now
    # leaves an honest non-green latest record instead of silently reusing stale evidence.
    write(
        {
            "schema_version": "xinao.m_keep.canary.v2",
            "run_id": run_id,
            "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "RUNNING",
            "ok": False,
            "completion_claim_allowed": False,
        }
    )
    try:
        payload = build_evidence(args.duration_seconds, run_id)
    except BaseException as exc:  # preserve a bounded failure record after cleanup
        payload = {
            "schema_version": "xinao.m_keep.canary.v2",
            "run_id": run_id,
            "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "FAILED",
            "ok": False,
            "completion_claim_allowed": False,
            "error_type": type(exc).__name__,
        }
    write(payload)
    print(json.dumps({"ok": payload["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
