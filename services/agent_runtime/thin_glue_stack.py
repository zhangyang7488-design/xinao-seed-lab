"""L0–L9 thin glue adapters — external mature OSS + minimal seams."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.carrier_identity import resolve_code_carrier_root

SCHEMA_VERSION = "xinao.codex_s.thin_glue_stack.v1"
SENTINEL = "SENTINEL:XINAO_THIN_GLUE_STACK_READY"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = resolve_code_carrier_root(anchor=__file__)
DEFAULT_MATERIALS = DEFAULT_REPO / "materials"
# Container mount for D:\XINAO_RESEARCH_RUNTIME (houtai-gongren). Never default to host Desktop.
DEFAULT_EVIDENCE_MOUNT = Path("/evidence")
DEFAULT_INTAKE_FALLBACK_TEXT = (
    "# integrated_bus intake fallback\n\n"
    "marker: integrated_bus_intake_path_fix\n"
    "intent_cn: 默认 intake 使用 /evidence 或 materials，禁止依赖主机 Desktop\\*.lnk\n"
    "acceptance: readable\n"
)


def thin_glue_enabled(flag: str, *, default: str = "1") -> bool:
    return os.environ.get(flag, default).strip().lower() not in {"0", "false", "no", "off"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def is_host_desktop_path(raw: str | Path | None) -> bool:
    """True for Windows host Desktop paths (not visible inside Linux workers)."""
    if raw is None:
        return False
    ms = str(raw).replace("\\", "/")
    lower = ms.lower()
    if "/desktop/" not in lower and not lower.endswith("/desktop"):
        return False
    return (
        ":/users/" in lower
        or lower.startswith("/users/")
        or lower.startswith("c:/users/")
        or "\\users\\" in str(raw).lower()
    )


def default_intake_candidates(
    *,
    repo_root: Path | None = None,
    runtime_root: Path | None = None,
) -> list[Path]:
    """Container/evidence-first intake paths. Desktop is never a default."""
    repo = Path(repo_root) if repo_root else DEFAULT_REPO
    runtime = Path(runtime_root) if runtime_root else DEFAULT_RUNTIME
    evidence = DEFAULT_EVIDENCE_MOUNT if DEFAULT_EVIDENCE_MOUNT.is_dir() else runtime
    app = Path("/app") if Path("/app").is_dir() else repo
    return [
        evidence / "state" / "watchdog" / "integrated_bus" / "inbox" / "default_intake.md",
        evidence / "state" / "integrated_bus_intake" / "default_input.md",
        evidence / "tmp" / "probe_intake_text.txt",
        runtime / "state" / "watchdog" / "integrated_bus" / "inbox" / "default_intake.md",
        runtime / "state" / "integrated_bus_intake" / "default_input.md",
        runtime / "tmp" / "probe_intake_text.txt",
        app / "materials" / "phase0_test_input.md",
        app / "materials" / "thin_bootstrap_input.md",
        repo / "materials" / "phase0_test_input.md",
        repo / "materials" / "thin_bootstrap_input.md",
        DEFAULT_MATERIALS / "phase0_test_input.md",
    ]


def resolve_intake_source(
    raw: str | Path | None,
    *,
    repo_root: Path | None = None,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    """
    Resolve intake path without raising.
    Prefer evidence/materials; host Desktop *.lnk is optional only when it exists on host.
    """
    requested = str(raw or "").strip()
    blocker = ""
    path: Path | None = Path(requested) if requested else None

    if path is not None and path.is_file():
        # Host-visible Desktop is optional when present; never required.
        return {
            "path": path,
            "requested": requested,
            "named_blocker": "",
            "used_fallback_text": False,
        }

    if path is not None and is_host_desktop_path(path):
        blocker = "host_desktop_path_unmounted_in_container"
    elif requested:
        blocker = "intake_path_missing"

    for candidate in default_intake_candidates(repo_root=repo_root, runtime_root=runtime_root):
        if candidate.is_file():
            return {
                "path": candidate,
                "requested": requested,
                "named_blocker": blocker or "intake_path_substituted_evidence_or_materials",
                "used_fallback_text": False,
            }

    return {
        "path": None,
        "requested": requested,
        "named_blocker": blocker or "intake_path_missing_all_candidates",
        "used_fallback_text": True,
    }


def l0_intake_markdown(path: Path, *, max_chars: int = 4000) -> dict[str, Any]:
    """
    L0 intake. Never raises FileNotFoundError on host Desktop paths —
    substitutes evidence/materials or synthetic fallback so Temporal does not infinite-retry.
    """
    resolved = resolve_intake_source(path)
    source_path = resolved.get("path")
    named_blocker = str(resolved.get("named_blocker") or "")
    adapter = "markitdown"
    text = ""

    if source_path is not None and Path(source_path).is_file():
        try:
            from markitdown import MarkItDown

            result = MarkItDown().convert(str(source_path))
            text = (result.text_content or "")[:max_chars]
        except Exception:
            adapter = "plain_text_fallback"
            try:
                text = Path(source_path).read_text(encoding="utf-8", errors="replace")[:max_chars]
            except OSError as exc:
                adapter = "synthetic_fallback"
                named_blocker = named_blocker or f"intake_read_failed:{exc}"
                text = DEFAULT_INTAKE_FALLBACK_TEXT[:max_chars]
    else:
        adapter = "synthetic_fallback"
        text = DEFAULT_INTAKE_FALLBACK_TEXT[:max_chars]
        if not named_blocker:
            named_blocker = "intake_path_missing_all_candidates"

    return {
        "layer": "L0",
        "adapter": adapter,
        "source": str(source_path or path),
        "requested_source": str(resolved.get("requested") or path),
        "content_md": text,
        "char_count": len(text),
        "named_blocker": named_blocker,
        "used_fallback_text": bool(resolved.get("used_fallback_text"))
        or adapter == "synthetic_fallback",
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
    docker_image: str = "python:3.12-slim",
) -> dict[str, Any]:
    from services.agent_runtime.thin_bootstrap_sandbox import run_cheapest_sandbox

    result = run_cheapest_sandbox(
        code,
        prefer_docker=prefer_docker,
        prefer_e2b=prefer_e2b,
        docker_image=docker_image,
    )
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
