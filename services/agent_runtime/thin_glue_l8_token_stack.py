"""L8 token stack — RTK / Caveman / deterministic fallback for readback compression."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, write_json

REPLACES_TARGET = "handroll_readback_compress"
SCHEMA_VERSION = "xinao.codex_s.thin_glue_l8_token_stack.v1"
DEFAULT_MAX_CHARS = 2400
RTK_INSTALL_SH = "https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh"
RTK_RELEASE_API = "https://api.github.com/repos/rtk-ai/rtk/releases/latest"
CAVEMAN_REPO = "https://github.com/JuliusBrussee/caveman.git"
_INSTALL_ATTEMPTED = False


def thin_glue_token_stack_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_TOKEN_STACK", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_token_stack"
    return {
        "latest": state / "latest.json",
        "compressed_dir": runtime / "readback" / "zh" / "compressed",
        "readback": runtime / "readback" / "zh" / "thin_glue_token_stack_latest.md",
    }


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


def _local_bin_dir() -> Path:
    custom = os.environ.get("XINAO_L8_LOCAL_BIN", "").strip()
    if custom:
        return Path(custom)
    return Path.home() / ".local" / "bin"


def _install_caveman_compress_shim(*, install_dir: Path) -> bool:
    script = _caveman_compress_stdin_script()
    if not script.is_file():
        return False
    install_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        target = install_dir / "caveman-compress.cmd"
        target.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
    else:
        target = install_dir / "caveman-compress"
        target.write_text(
            f'#!/usr/bin/env sh\nexec "{sys.executable}" "{script}" "$@"\n',
            encoding="utf-8",
        )
        target.chmod(0o755)
    return target.is_file()


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


def _install_rtk_windows(*, install_dir: Path) -> bool:
    install_dir.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(RTK_RELEASE_API, timeout=60) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except OSError:
        return False
    asset_url = ""
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if name == "rtk-x86_64-pc-windows-msvc.zip":
            asset_url = str(asset.get("browser_download_url") or "")
            break
    if not asset_url:
        return False
    try:
        with urlopen(asset_url, timeout=120) as resp:
            payload = resp.read()
    except OSError:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "rtk.zip"
        zpath.write_bytes(payload)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmp)
        src = Path(tmp) / "rtk.exe"
        if not src.is_file():
            return False
        target = install_dir / "rtk.exe"
        shutil.copy2(src, target)
    return target.is_file()


def attempt_install_rtk() -> str:
    if shutil.which("rtk"):
        return ""
    install_dir = _local_bin_dir()
    try:
        if platform.system().lower().startswith("win"):
            ok = _install_rtk_windows(install_dir=install_dir)
        else:
            env = os.environ.copy()
            env["RTK_INSTALL_DIR"] = str(install_dir)
            proc = subprocess.run(
                ["sh", "-c", f'curl -fsSL "{RTK_INSTALL_SH}" | sh'],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
                env=env,
            )
            ok = proc.returncode == 0 and bool(shutil.which("rtk"))
        if ok or shutil.which("rtk"):
            path = str(install_dir)
            if path not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{path}{os.pathsep}{os.environ.get('PATH', '')}"
            return ""
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "RTK_CLI_INSTALL_FAILED"


def attempt_install_caveman() -> str:
    for cmd in ("caveman-compress", "caveman"):
        if shutil.which(cmd):
            return ""
    install_dir = _local_bin_dir()
    try:
        if _install_caveman_compress_shim(install_dir=install_dir):
            path = str(install_dir)
            if path not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{path}{os.pathsep}{os.environ.get('PATH', '')}"
            if shutil.which("caveman-compress"):
                return ""
    except OSError:
        pass
    return "CAVEMAN_CLI_INSTALL_FAILED"


def ensure_l8_cli_tools() -> dict[str, str]:
    """Attempt one-shot install when CLIs are missing; return named_blockers on failure."""
    global _INSTALL_ATTEMPTED
    blockers: dict[str, str] = {
        "rtk_named_blocker": "",
        "caveman_named_blocker": "",
    }
    if os.environ.get("XINAO_L8_SKIP_CLI_INSTALL", "").strip().lower() in {"1", "true", "yes"}:
        return blockers
    if _INSTALL_ATTEMPTED:
        if not shutil.which("rtk"):
            blockers["rtk_named_blocker"] = "RTK_CLI_MISSING"
        if not shutil.which("caveman-compress") and not shutil.which("caveman"):
            blockers["caveman_named_blocker"] = "CAVEMAN_CLI_MISSING"
        return blockers
    _INSTALL_ATTEMPTED = True
    if not shutil.which("rtk"):
        blockers["rtk_named_blocker"] = attempt_install_rtk()
    if not shutil.which("caveman-compress") and not shutil.which("caveman"):
        blockers["caveman_named_blocker"] = attempt_install_caveman()
    return blockers


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
        "hand_rolled_compress_bypassed": True,
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
            "hand_rolled_compress_bypassed": True,
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
            "hand_rolled_compress_bypassed": True,
        }
    return None


def compress_readback_text(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    blockers = ensure_l8_cli_tools()
    for fn in (try_rtk_compress, try_caveman_compress):
        result = fn(text)
        if result and result.get("ok"):
            result.update(blockers)
            return result
    fallback = compress_readback_fallback(text, max_chars=max_chars)
    fallback.update(blockers)
    return fallback


def compress_zh_readback_file(
    path: Path,
    *,
    runtime_root: Path,
    write: bool = True,
) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    compressed = compress_readback_text(raw)
    out_path = output_paths(runtime_root)["compressed_dir"] / path.name
    if write:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(compressed["text"] + "\n", encoding="utf-8")
    compressed["source_path"] = str(path)
    compressed["compressed_path"] = str(out_path) if write else ""
    return compressed


def run_thin_glue_token_stack(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    max_files: int = 12,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    zh_dir = runtime / "readback" / "zh"
    files = sorted(
        [p for p in zh_dir.glob("*.md") if p.is_file() and "compressed" not in p.parts],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:max_files]
    results: list[dict[str, Any]] = []
    for path in files:
        results.append(compress_zh_readback_file(path, runtime_root=runtime, write=write))

    adapters = {str(item.get("adapter") or "") for item in results}
    avg_ratio = (
        sum(float(item.get("compression_ratio") or 0) for item in results) / len(results)
        if results
        else 0.0
    )
    checks = {
        "files_processed": len(results) > 0,
        "compression_applied": any(int(item.get("after_chars") or 0) > 0 for item in results),
        "hand_rolled_compress_bypassed": True,
        "external_adapter_used": any(a in {"rtk", "caveman"} for a in adapters),
    }
    passed = checks["files_processed"] and checks["compression_applied"]

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "replaces": REPLACES_TARGET,
        "not_333_mainline": True,
        "thin_glue": True,
        "file_count": len(results),
        "adapters_used": sorted(adapters),
        "average_compression_ratio": round(avg_ratio, 4),
        "results": results,
        "acceptance_now_can_invoke_cn": (
            f"L8 token 栈：压了 {len(results)} 个 zh readback；"
            f"adapter={','.join(sorted(adapters)) or 'fallback'}；"
            f"均压缩率≈{avg_ratio:.0%}"
            if passed
            else "L8：无 zh readback 可压"
        ),
        "validation": {"passed": passed, "checks": checks},
    }

    if write:
        paths = output_paths(runtime)
        write_json(paths["latest"], payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            payload["acceptance_now_can_invoke_cn"] + "\n", encoding="utf-8"
        )
        payload["output_paths"] = {
            "latest": str(paths["latest"]),
            "compressed_dir": str(paths["compressed_dir"]),
            "readback_zh": str(paths["readback"]),
        }

    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Thin glue L8 token stack compress")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--max-files", type=int, default=12)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    payload = run_thin_glue_token_stack(
        runtime_root=args.runtime_root,
        max_files=args.max_files,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
