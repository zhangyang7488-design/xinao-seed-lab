"""RTK, Caveman, and deterministic fallback readback compression."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_MAX_CHARS = 2400


def _ratio(before: int, after: int) -> float:
    if before <= 0:
        return 0.0
    return round(max(0.0, 1.0 - (after / before)), 4)


def _repo_root() -> Path:
    env = os.environ.get("XINAO_CODEX_S_REPO_ROOT", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def _caveman_compress_stdin_script() -> Path:
    return _repo_root() / "scripts" / "l8" / "caveman_compress_stdin.py"


def _caveman_compress_commands() -> list[list[str]]:
    commands: list[list[str]] = []
    for cmd in ("caveman-compress", "caveman"):
        exe = shutil.which(cmd)
        if exe:
            commands.append([exe])
    script = _caveman_compress_stdin_script()
    if script.is_file():
        commands.append([sys.executable, str(script)])
    return commands


def _probe_l8_cli_tools() -> dict[str, str]:
    """Probe optional compressors without mutating the host or installing tools."""

    return {
        "rtk_named_blocker": "" if shutil.which("rtk") else "RTK_CLI_MISSING",
        "caveman_named_blocker": "" if _caveman_compress_commands() else "CAVEMAN_CLI_MISSING",
    }


def compress_readback_fallback(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        key = re.sub(r"\s+", " ", line.strip().lower())
        if key in seen and line.startswith("- "):
            continue
        seen.add(key)
        lines.append(line)
    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[: max_chars - 20] + "\n…[thin_glue_l8_truncated]"
    before = len(text)
    after = len(body)
    return {
        "adapter": "deterministic_dedupe_truncate",
        "ok": True,
        "text": body,
        "before_chars": before,
        "after_chars": after,
        "compression_ratio": _ratio(before, after),
    }


def try_rtk_compress(text: str) -> dict[str, Any] | None:
    rtk = shutil.which("rtk")
    if not rtk:
        return None
    # `rtk log` accepts stdin today; `compress --stdin` is forward-compatible if added upstream.
    for args in (["log"], ["compress", "--stdin"]):
        try:
            proc = subprocess.run(
                [rtk, *args],
                input=text,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0 or not (proc.stdout or "").strip():
            continue
        out = proc.stdout
        return {
            "adapter": "rtk",
            "ok": True,
            "text": out,
            "before_chars": len(text),
            "after_chars": len(out),
            "compression_ratio": _ratio(len(text), len(out)),
        }
    return None


def try_caveman_compress(text: str) -> dict[str, Any] | None:
    for argv in _caveman_compress_commands():
        try:
            proc = subprocess.run(
                argv,
                input=text,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0 or not (proc.stdout or "").strip():
            continue
        out = proc.stdout
        return {
            "adapter": "caveman",
            "ok": True,
            "text": out,
            "before_chars": len(text),
            "after_chars": len(out),
            "compression_ratio": _ratio(len(text), len(out)),
        }
    return None


def compress_readback_text(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    blockers = _probe_l8_cli_tools()
    for fn in (try_rtk_compress, try_caveman_compress):
        result = fn(text)
        if result and result.get("ok"):
            result.update(blockers)
            return result
    fallback = compress_readback_fallback(text, max_chars=max_chars)
    fallback.update(blockers)
    return fallback
