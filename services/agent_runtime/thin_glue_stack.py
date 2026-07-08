"""L0–L9 thin glue adapters — external mature OSS + minimal seams."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.thin_glue_stack.v1"
SENTINEL = "SENTINEL:XINAO_THIN_GLUE_STACK_READY"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_MATERIALS = DEFAULT_REPO / "materials"


def thin_glue_enabled(flag: str, *, default: str = "1") -> bool:
    return os.environ.get(flag, default).strip().lower() not in {"0", "false", "no", "off"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def l0_intake_markdown(path: Path, *, max_chars: int = 4000) -> dict[str, Any]:
    adapter = "markitdown"
    try:
        from markitdown import MarkItDown

        result = MarkItDown().convert(str(path))
        text = (result.text_content or "")[:max_chars]
    except Exception:
        adapter = "plain_text_fallback"
        text = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    return {
        "layer": "L0",
        "adapter": adapter,
        "source": str(path),
        "content_md": text,
        "char_count": len(text),
        "timestamp": now_iso(),
    }


def l0_scan_materials(
    materials_root: Path,
    *,
    patterns: tuple[str, ...] = ("*.md", "*.txt"),
    max_files: int = 12,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not materials_root.is_dir():
        return entries
    seen: set[str] = set()
    for pattern in patterns:
        for path in sorted(materials_root.rglob(pattern)):
            key = str(path.resolve())
            if key in seen or path.name.startswith("."):
                continue
            seen.add(key)
            try:
                entries.append(l0_intake_markdown(path))
            except Exception as exc:
                entries.append(
                    {
                        "layer": "L0",
                        "adapter": "markitdown",
                        "source": str(path),
                        "error": str(exc),
                        "timestamp": now_iso(),
                    }
                )
            if len(entries) >= max_files:
                return entries
    return entries


def l3_run_sandbox(
    code: str,
    *,
    prefer_docker: bool = True,
    prefer_e2b: bool = False,
) -> dict[str, Any]:
    from services.agent_runtime.thin_bootstrap_sandbox import run_cheapest_sandbox

    result = run_cheapest_sandbox(code, prefer_docker=prefer_docker, prefer_e2b=prefer_e2b)
    return {
        "layer": "L3",
        "adapter": result.backend,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "ok": result.exit_code == 0,
    }


def l8_write_zh_readback(
    runtime_root: Path,
    *,
    run_id: str,
    title: str,
    lines: list[str],
) -> Path:
    zh_path = runtime_root / "readback" / "zh" / f"{run_id}.md"
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join([f"# {title}", "", *lines, ""])
    zh_path.write_text(body, encoding="utf-8")
    if thin_glue_enabled("XINAO_THIN_GLUE_TOKEN_STACK", default="1"):
        from services.agent_runtime.thin_glue_l8_token_stack import compress_zh_readback_file

        compress_zh_readback_file(zh_path, runtime_root=runtime_root, write=True)
    return zh_path


def l9_probe_provider(*, base_url: str | None = None) -> dict[str, Any]:
    from services.agent_runtime.thin_provider_client import DEFAULT_BASE_URL, probe_gateway

    probe = probe_gateway(base_url=base_url or DEFAULT_BASE_URL)
    probe["layer"] = "L9"
    probe["adapter"] = "litellm_or_omniroute_openai_compat"
    return probe


def l9_chat_smoke(
    *,
    base_url: str | None = None,
    model: str = "auto",
    prompt: str = "reply with exactly: glue_ok",
) -> dict[str, Any]:
    from services.agent_runtime.thin_provider_client import DEFAULT_BASE_URL, chat_completion

    result = chat_completion(
        [{"role": "user", "content": prompt}],
        model=model,
        base_url=base_url or DEFAULT_BASE_URL,
        timeout_s=30.0,
    )
    result["layer"] = "L9"
    result["adapter"] = "litellm_or_omniroute_openai_compat"
    return result