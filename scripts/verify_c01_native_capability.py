#!/usr/bin/env python3
"""Fresh, non-interactive capability smoke for the two native TUI entries."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DESKTOP = Path(r"C:\Users\xx363\Desktop")
GROK_EXE = Path(r"C:\Users\xx363\.grok\bin\grok.exe")
CODEX_PS1 = Path(r"C:\Users\xx363\AppData\Roaming\npm\codex.ps1")
TERMINAL_SETTINGS = Path(
    os.environ.get("LOCALAPPDATA", r"C:\Users\xx363\AppData\Local")
) / "Packages" / "Microsoft.WindowsTerminal_8wekyb3d8bbwe" / "LocalState" / "settings.json"
DEFAULT_OUT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\C01_native_capability_latest.json")
WINDOWLESS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _foreground() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow()) if os.name == "nt" else 0


def _process_tree(root_pid: int) -> set[int]:
    if os.name != "nt":
        return {root_pid}
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return {root_pid}

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    parents: dict[int, set[int]] = {}
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(ProcessEntry)
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents.setdefault(int(entry.th32ParentProcessID), set()).add(
                int(entry.th32ProcessID)
            )
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    tree = {root_pid}
    frontier = [root_pid]
    while frontier:
        children = parents.get(frontier.pop(), set()) - tree
        tree.update(children)
        frontier.extend(children)
    return tree


def _visible_windows(pids: set[int]) -> set[int]:
    if os.name != "nt":
        return set()
    user32 = ctypes.windll.user32
    handles: set[int] = set()
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) in pids and user32.IsWindowVisible(hwnd):
            handles.add(int(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return handles


def _pid_running(pid: int) -> bool:
    if os.name != "nt":
        return False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    exit_code = ctypes.c_ulong()
    try:
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and int(
            exit_code.value
        ) == 259
    finally:
        kernel32.CloseHandle(handle)


def _matching_processes() -> list[dict[str, Any]]:
    code = (
        "$items=Get-CimInstance Win32_Process | Where-Object {"
        "$_.Name -in @('grok.exe','codex.exe') -or "
        "($_.Name -eq 'node.exe' -and $_.ExecutablePath -match 'codex')};"
        "$items | Select-Object ProcessId,CreationDate,ExecutablePath | ConvertTo-Json -Compress"
    )
    proc = subprocess.run(
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        creationflags=WINDOWLESS,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    value = json.loads(proc.stdout)
    rows = value if isinstance(value, list) else [value]
    return sorted(
        [
            {
                "pid": int(row.get("ProcessId") or 0),
                "created": str(row.get("CreationDate") or ""),
                "exe": str(row.get("ExecutablePath") or ""),
            }
            for row in rows
            if isinstance(row, dict)
        ],
        key=lambda row: (row["pid"], row["created"]),
    )


def _shortcut(path: Path) -> dict[str, Any]:
    escaped = str(path).replace("'", "''")
    code = (
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut('{escaped}');"
        "[pscustomobject]@{target=$s.TargetPath;arguments=$s.Arguments;"
        "workdir=$s.WorkingDirectory;window_style=$s.WindowStyle}|ConvertTo-Json -Compress"
    )
    proc = subprocess.run(
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        creationflags=WINDOWLESS,
    )
    value = json.loads(proc.stdout) if proc.returncode == 0 else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "sha256": _sha256(path) if path.is_file() else None,
        "target": str(value.get("target") or ""),
        "arguments": str(value.get("arguments") or ""),
        "workdir": str(value.get("workdir") or ""),
        "window_style": value.get("window_style"),
    }


def _run_probe(
    label: str,
    command: list[str],
    *,
    include_stdout: bool = False,
    timeout: float = 60,
) -> dict[str, Any]:
    process = subprocess.Popen(
        command,
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        creationflags=WINDOWLESS,
    )
    observed_new_windows: set[int] = set()
    observed_tree = {process.pid}
    took_foreground = False
    stop_observer = threading.Event()

    def observe() -> None:
        nonlocal took_foreground
        while not stop_observer.is_set():
            observed_tree.update(_process_tree(process.pid))
            windows = _visible_windows(observed_tree)
            observed_new_windows.update(windows)
            if _foreground() in windows:
                took_foreground = True
            time.sleep(0.02)

    observer = threading.Thread(target=observe, name=f"c01-observer-{label}", daemon=True)
    observer.start()
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        process.kill()
        timed_out = True
        stdout, stderr = process.communicate(timeout=10)
    finally:
        stop_observer.set()
        observer.join(timeout=2)
    time.sleep(0.05)
    resident_after = {pid for pid in observed_tree if _pid_running(pid)}
    result = {
        "label": label,
        "pid": process.pid,
        "command_executable": command[0],
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "stdout_size": len(stdout),
        "stdout_sha256": _sha256_bytes(stdout),
        "stderr_size": len(stderr),
        "stderr_sha256": _sha256_bytes(stderr),
        "visible_window_count": len(observed_new_windows),
        "foreground_unchanged": not took_foreground,
        "root_process_exited": process.poll() is not None,
        "observed_process_count": len(observed_tree),
        "process_tree_resident_count": len(resident_after),
        "create_no_window": bool(WINDOWLESS) if os.name == "nt" else True,
    }
    if include_stdout:
        result["stdout_text"] = stdout.decode("utf-8", errors="replace")
        result["stderr_text"] = stderr.decode("utf-8", errors="replace")
    return result


def _terminal_profiles() -> dict[str, Any]:
    data = json.loads(TERMINAL_SETTINGS.read_text(encoding="utf-8"))
    profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
    profile_list = profiles.get("list") if isinstance(profiles.get("list"), list) else []
    wanted = {"XINAO Grok 4.5", "XINAO Codex S Hardmode"}
    found = {
        str(item.get("name")): {
            "guid": item.get("guid"),
            "commandline": item.get("commandline") or item.get("commandLine"),
            "starting_directory": item.get("startingDirectory"),
        }
        for item in profile_list
        if isinstance(item, dict) and str(item.get("name")) in wanted
    }
    return {
        "settings_path": str(TERMINAL_SETTINGS),
        "settings_sha256": _sha256(TERMINAL_SETTINGS),
        "profiles": found,
    }


def build_evidence() -> dict[str, Any]:
    process_before = _matching_processes()
    shortcuts = {
        "grok": _shortcut(DESKTOP / "Grok 4.5.lnk"),
        "codex": _shortcut(DESKTOP / "OPEN CODEX S HARDMODE.lnk"),
    }
    terminal = _terminal_profiles()
    probes = [
        _run_probe("grok_version", [str(GROK_EXE), "--version"]),
        _run_probe("grok_help", [str(GROK_EXE), "--help"]),
        _run_probe("grok_sessions_read", [str(GROK_EXE), "sessions", "list", "-n", "1"]),
        _run_probe(
            "codex_version",
            [
                "pwsh.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(CODEX_PS1),
                "--version",
            ],
        ),
        _run_probe(
            "codex_help",
            [
                "pwsh.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(CODEX_PS1),
                "--help",
            ],
        ),
        _run_probe(
            "codex_mcp_list",
            [
                "pwsh.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(CODEX_PS1),
                "mcp",
                "list",
            ],
        ),
    ]
    process_after = _matching_processes()
    profile_map = terminal["profiles"]
    checks = {
        "shortcuts_exist": all(item["exists"] for item in shortcuts.values()),
        "shortcuts_target_windows_terminal": all(
            Path(item["target"]).name.casefold() == "wt.exe" for item in shortcuts.values()
        ),
        "shortcut_profiles_distinct": shortcuts["grok"]["arguments"]
        != shortcuts["codex"]["arguments"],
        "shortcut_workdirs_exist": all(
            Path(item["workdir"]).is_dir() for item in shortcuts.values()
        ),
        "terminal_profiles_present": set(profile_map)
        == {"XINAO Grok 4.5", "XINAO Codex S Hardmode"},
        "terminal_profiles_distinct": len(
            {str(item.get("guid") or "") for item in profile_map.values()}
        )
        == 2,
        "native_binaries_present": GROK_EXE.is_file() and CODEX_PS1.is_file(),
        "all_fresh_probes_exit_zero": all(probe["exit_code"] == 0 for probe in probes),
        "all_fresh_probes_nonempty": all(probe["stdout_size"] > 0 for probe in probes),
        "no_probe_timed_out": not any(probe["timed_out"] for probe in probes),
        "no_visible_windows": not any(probe["visible_window_count"] for probe in probes),
        "foreground_unchanged": all(probe["foreground_unchanged"] for probe in probes),
        "all_probe_roots_exited": all(probe["root_process_exited"] for probe in probes),
        # Global Grok worker activity may legitimately change concurrently; the
        # attributable negative check is that every probe root exited and no
        # visible window/focus effect occurred.  Keep the global snapshots as
        # non-gating evidence instead of misattributing another ready-frontier lane.
        "probe_processes_exited_without_window": all(
            probe["root_process_exited"]
            and probe["process_tree_resident_count"] == 0
            and probe["visible_window_count"] == 0
            for probe in probes
        ),
    }
    script = Path(__file__).resolve()
    return {
        "schema_version": "xinao.c01.native_capability.v1",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": f"c01-{uuid.uuid4().hex}",
        "ok": all(checks.values()),
        "completion_claim_allowed": all(checks.values()),
        "checks": checks,
        "shortcuts": shortcuts,
        "terminal": terminal,
        "probes": probes,
        "process_baseline": {"before": process_before, "after": process_after},
        "source_hashes": {str(script.relative_to(REPO)).replace("/", "\\"): _sha256(script)},
        "non_claims": {
            "interactive_prompt_submitted": False,
            "desktop_tui_opened": False,
            "session_adopted_or_resumed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    output = Path(args.output)
    payload = build_evidence()
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = output.with_name(f".{output.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(raw, encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps({"ok": payload["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
