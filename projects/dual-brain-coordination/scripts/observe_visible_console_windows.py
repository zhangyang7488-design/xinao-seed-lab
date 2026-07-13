#!/usr/bin/env python3
"""Bounded Windows visible-console observer for incident attribution."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import time
import uuid
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONSOLE_PROCESS_NAMES = {
    "cmd.exe",
    "conhost.exe",
    "openconsole.exe",
    "powershell.exe",
    "pwsh.exe",
    "python.exe",
    "pythonw.exe",
    "windowsterminal.exe",
    "wt.exe",
}


class ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _process_snapshot() -> dict[int, dict[str, Any]]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if handle == wintypes.HANDLE(-1).value:
        return {}
    rows: dict[int, dict[str, Any]] = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(ProcessEntry32W)
        ok = kernel32.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            rows[int(entry.th32ProcessID)] = {
                "parent_pid": int(entry.th32ParentProcessID),
                "process": str(entry.szExeFile).lower(),
            }
            ok = kernel32.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(handle)
    return rows


def _visible_console_windows() -> list[dict[str, Any]]:
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows.argtypes = [callback_type, ctypes.c_void_p]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    processes = _process_snapshot()
    foreground = int(user32.GetForegroundWindow() or 0)
    rows: list[dict[str, Any]] = []

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = processes.get(int(pid.value), {})
        name = str(process.get("process") or "").lower()
        if name not in CONSOLE_PROCESS_NAMES:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        rows.append(
            {
                "handle": int(hwnd),
                "pid": int(pid.value),
                "parent_pid": int(process.get("parent_pid") or 0),
                "process": name,
                "title": title_buffer.value,
                "foreground_when_seen": int(hwnd) == foreground,
            }
        )
        return True

    user32.EnumWindows(callback, 0)
    return rows


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument("--interval-seconds", type=float, default=0.01)
    args = parser.parse_args()
    started_at = datetime.now(UTC).isoformat()
    baseline = {
        (int(row["handle"]), int(row["pid"])) for row in _visible_console_windows()
    }
    observed: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    deadline = time.monotonic() + max(0.1, args.duration_seconds)
    _write_json_atomic(
        args.output,
        {
            "status": "observing",
            "observer_pid": os.getpid(),
            "started_at": started_at,
            "baseline_count": len(baseline),
            "observed_windows": observed,
        },
    )
    while time.monotonic() < deadline:
        for row in _visible_console_windows():
            key = (int(row["handle"]), int(row["pid"]))
            if key in baseline or key in seen:
                continue
            seen.add(key)
            observed.append({**row, "observed_at": datetime.now(UTC).isoformat()})
            _write_json_atomic(
                args.output,
                {
                    "status": "observing",
                    "observer_pid": os.getpid(),
                    "started_at": started_at,
                    "baseline_count": len(baseline),
                    "observed_windows": observed,
                },
            )
        time.sleep(max(0.005, args.interval_seconds))
    _write_json_atomic(
        args.output,
        {
            "status": "completed",
            "observer_pid": os.getpid(),
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "baseline_count": len(baseline),
            "observed_windows": observed,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
