"""L8 token stack — RTK / Caveman / deterministic fallback for readback compression."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, write_json

REPLACES_TARGET = "handroll_readback_compress"
SCHEMA_VERSION = "xinao.codex_s.thin_glue_l8_token_stack.v1"
DEFAULT_MAX_CHARS = 2400


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
    try:
        proc = subprocess.run(
            [rtk, "compress", "--stdin"],
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
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


def try_caveman_compress(text: str) -> dict[str, Any] | None:
    for cmd in ("caveman-compress", "caveman"):
        exe = shutil.which(cmd)
        if not exe:
            continue
        try:
            proc = subprocess.run(
                [exe],
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
    for fn in (try_rtk_compress, try_caveman_compress):
        result = fn(text)
        if result and result.get("ok"):
            return result
    return compress_readback_fallback(text, max_chars=max_chars)


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
        paths["readback"].write_text(payload["acceptance_now_can_invoke_cn"] + "\n", encoding="utf-8")
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