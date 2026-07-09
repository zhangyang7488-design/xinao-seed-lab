"""L4 搜索薄绑 — ripgrep 本地 + SearXNG/DDGS 外部（替 codex_s_light_research_loop 默认热路径）."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from services.agent_runtime.overnight_local_search import local_search
from services.agent_runtime.thin_evidence_writer import append_jsonl, now_iso, write_json
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME, SCHEMA_VERSION, SENTINEL

TASK_ID = "thin_glue_search"
REPLACES_MODULE = "codex_s_light_research_loop"


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_search"
    return {
        "latest": state / "latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_search_latest.md",
    }


def derive_search_query(task_preview: str, *, fallback: str = "thin_glue") -> str:
    text = (task_preview or "").replace("#", " ")
    for token in re.split(r"[^\w.-]+", text):
        cleaned = token.strip("._-")
        if len(cleaned) >= 3:
            return cleaned[:80]
    return fallback


def probe_searxng(
    query: str,
    *,
    base_url: str | None = None,
    max_results: int = 5,
) -> dict[str, Any]:
    base = (base_url or os.environ.get("XINAO_SEARXNG_BASE_URL", "http://127.0.0.1:8080")).rstrip("/")
    try:
        import httpx
    except ImportError:
        return {
            "adapter": "searxng",
            "ok": False,
            "skipped": True,
            "reason": "httpx_missing",
            "hits": [],
            "base_url": base,
        }
    try:
        resp = httpx.get(
            f"{base}/search",
            params={"q": query, "format": "json"},
            timeout=8.0,
        )
    except Exception as exc:
        return {
            "adapter": "searxng",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "hits": [],
            "base_url": base,
        }
    if resp.status_code != 200:
        return {
            "adapter": "searxng",
            "ok": False,
            "skipped": True,
            "reason": f"http_{resp.status_code}",
            "hits": [],
            "base_url": base,
        }
    try:
        payload = resp.json()
    except (ValueError, TypeError) as exc:
        return {
            "adapter": "searxng",
            "ok": False,
            "skipped": True,
            "reason": f"invalid_json:{exc}",
            "hits": [],
            "base_url": base,
        }
    hits: list[dict[str, Any]] = []
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        hits.append(
            {
                "title": str(row.get("title") or ""),
                "url": str(row.get("url") or ""),
                "snippet": str(row.get("content") or row.get("snippet") or "")[:500],
                "source": "searxng",
            }
        )
        if len(hits) >= max_results:
            break
    return {
        "adapter": "searxng",
        "ok": bool(hits),
        "skipped": False,
        "hit_count": len(hits),
        "hits": hits,
        "base_url": base,
    }


def run_local_rg_search(
    repo_root: Path,
    query: str,
    *,
    max_results: int = 8,
) -> dict[str, Any]:
    from services.agent_runtime.thin_glue_rg_utils import default_local_roots, run_rg_scan

    hits = run_rg_scan(repo_root, default_local_roots(repo_root), query, max_results)
    return {
        "adapter": "ripgrep",
        "query": query,
        "hit_count": len(hits),
        "hits": hits,
        "ok": len(hits) > 0,
    }


def searxng_compose_available(*, base_url: str | None = None) -> bool:
    """True when SearXNG sidecar is reachable (compose profile search or explicit URL)."""
    if os.environ.get("XINAO_SEARXNG_COMPOSE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    probe = probe_searxng("ping", base_url=base_url, max_results=1)
    return probe.get("ok") is True and not probe.get("skipped")


def run_external_search(query: str, *, max_results: int = 5) -> dict[str, Any]:
    searx = probe_searxng(query, max_results=max_results)
    if searx.get("ok"):
        return {
            "adapter": "searxng",
            "query": query,
            "hit_count": searx.get("hit_count", 0),
            "hits": searx.get("hits") or [],
            "ok": True,
            "searxng": searx,
            "searxng_compose_available": True,
            "ddgs_gate_hits_required": False,
            "ddgs": {"skipped": True},
        }
    ddgs = local_search(query, max_results=max_results)
    hits = ddgs.get("hits") or []
    hit_count = len(hits)
    # SearXNG not in compose → DDGS fallback with hits>0 gate (honest skip if zero).
    ddgs_ok = hit_count > 0
    return {
        "adapter": "ddgs",
        "query": query,
        "hit_count": hit_count,
        "hits": hits,
        "ok": ddgs_ok,
        "searxng": searx,
        "searxng_compose_available": False,
        "ddgs_gate_hits_required": True,
        "ddgs": ddgs,
        "ddgs_named_blocker": "" if ddgs_ok else "INTEGRATED_BUS_L4_DDGS_ZERO_HITS",
    }


def run_thin_glue_search(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    run_id: str,
    local_query: str | None = None,
    external_query: str | None = None,
    max_results: int = 8,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    local_q = (local_query or "").strip() or derive_search_query("")
    external_q = (external_query or local_q).strip()

    local = run_local_rg_search(repo, local_q, max_results=max_results)
    external = run_external_search(external_q, max_results=min(max_results, 5))

    local_ok = local.get("ok") is True
    external_ok = external.get("ok") is True
    checks = {
        "local_rg_performed": True,
        "local_rg_hits": local_ok,
        "external_search_attempted": True,
        "external_search_hits_or_searx_skipped": external_ok or bool(external.get("searxng", {}).get("skipped")),
        "hand_rolled_light_research_bypassed": True,
    }
    passed = local_ok

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "thin_glue": True,
        "replaces": REPLACES_MODULE,
        "run_id": run_id,
        "local_query": local_q,
        "external_query": external_q,
        "local_search": local,
        "external_search": external,
        "local_hit_count": local.get("hit_count", 0),
        "external_hit_count": external.get("hit_count", 0),
        "validation": {
            "passed": passed,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "named_blockers": [] if passed else ["THIN_GLUE_L4_LOCAL_RG_EMPTY"],
        "timestamp": now_iso(),
    }

    append_jsonl(
        runtime / "evidence" / run_id / "execution.jsonl",
        {
            "layer": "L4",
            "activity": "search",
            "local_hits": local.get("hit_count", 0),
            "external_hits": external.get("hit_count", 0),
            "timestamp": now_iso(),
        },
    )

    if write:
        write_json(paths["latest"], payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "## 一层一句",
            f"- 本地 ripgrep：`{local_q}` → {local.get('hit_count', 0)} 条",
            f"- 外部搜索：{external.get('adapter')} → {external.get('hit_count', 0)} 条",
            f"- 替：`{REPLACES_MODULE}`（正文已归档 _retired）",
            "",
            "## 现在能干什么",
            "thin-glue 默认链已走 L4 搜索薄绑；本地 rg 必绿，外部 SearXNG/DDGS 尽力。",
        ]
        paths["readback"].write_text(
            "\n".join([f"# 薄胶 L4 搜索 {run_id}", "", *lines, ""]),
            encoding="utf-8",
        )
        payload["output_paths"] = {
            "latest": str(paths["latest"]),
            "readback": str(paths["readback"]),
        }

    return payload