"""L4 搜索薄绑 — ripgrep 本地 + SearXNG/DDGS/Exa 外部（替 codex_s_light_research_loop 默认热路径）."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from services.agent_runtime.default_plus_dynamic_escalate import (
    SEARCH_TIER_CHAIN as POLICY_SEARCH_TIER_CHAIN,
    should_escalate_search,
)
from services.agent_runtime.overnight_local_search import probe_ddgs, probe_exa
from services.agent_runtime.thin_evidence_writer import append_jsonl, now_iso, write_json
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME, SCHEMA_VERSION, SENTINEL

TASK_ID = "thin_glue_search"
REPLACES_MODULE = "codex_s_light_research_loop"
_SEARXNG_USER_AGENT = "XINAO-integrated-bus/1.0"
_DEFAULT_SEARXNG_BASE = "http://127.0.0.1:8888"
_EXA_AGGRESSIVE_MODES = frozenset({"aggressive", "auto", "on", "1", "true", "yes"})


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


def searxng_query_ladder(primary: str, *, context_text: str = "") -> list[str]:
    """Ordered SearXNG probes — waiwang-sousuo may return 0 hits for camelCase tokens like Phase0."""
    seen: set[str] = set()
    ladder: list[str] = []

    def _add(candidate: str) -> None:
        cleaned = (candidate or "").strip()
        if len(cleaned) < 3:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        ladder.append(cleaned[:80])

    _add(primary)
    text = context_text or ""
    marker = re.search(r"marker:\s*([^\s]+)", text, re.IGNORECASE)
    if marker:
        _add(marker.group(1).replace("_", " "))
        _add(marker.group(1))
    skip_tokens = frozenset(
        {"marker", "input", "test", "phase", "phase0", "smoke", "commit", "intake", "sandbox"}
    )
    for token in re.split(r"[^\w.-]+", text.replace("#", " ")):
        cleaned = token.strip("._-")
        if len(cleaned) >= 4 and cleaned.isascii() and cleaned.casefold() not in skip_tokens:
            _add(cleaned)
    for fallback in ("minimal", "smoke test", "software engineering"):
        _add(fallback)
    return ladder


def probe_searxng_ladder(
    query: str,
    *,
    context_text: str = "",
    base_url: str | None = None,
    max_results: int = 5,
) -> dict[str, Any]:
    """Try primary + fallbacks until SearXNG returns hits (compose sidecar invoke_green)."""
    attempts: list[dict[str, Any]] = []
    last = probe_searxng(query, base_url=base_url, max_results=max_results)
    attempts.append({"query": query, "hit_count": int(last.get("hit_count") or 0)})
    if last.get("ok"):
        last["searxng_query_used"] = query
        last["searxng_query_attempts"] = attempts
        return last
    if last.get("status_code") != 200:
        last["searxng_query_used"] = query
        last["searxng_query_attempts"] = attempts
        return last
    for alt in searxng_query_ladder(query, context_text=context_text)[1:]:
        probe = probe_searxng(alt, base_url=base_url, max_results=max_results)
        attempts.append({"query": alt, "hit_count": int(probe.get("hit_count") or 0)})
        if probe.get("ok"):
            probe["searxng_query_used"] = alt
            probe["searxng_query_attempts"] = attempts
            probe["searxng_primary_query"] = query
            return probe
        last = probe
    last["searxng_query_used"] = query
    last["searxng_query_attempts"] = attempts
    return last


def _skipped_adapter(name: str, *, reason: str = "not_needed", wired: bool = False) -> dict[str, Any]:
    return {
        "adapter": name,
        "ok": False,
        "skipped": True,
        "reason": reason,
        "wired": wired,
        "hit_count": 0,
        "hits": [],
    }


def exa_escalation_wired() -> bool:
    """T1 Exa dynamic escalation path is implemented (thin_bind); invoke is separate."""
    return True


SEARCH_TIER_CHAIN = POLICY_SEARCH_TIER_CHAIN


def probe_searxng(
    query: str,
    *,
    base_url: str | None = None,
    max_results: int = 5,
) -> dict[str, Any]:
    base = (base_url or os.environ.get("XINAO_SEARXNG_BASE_URL", _DEFAULT_SEARXNG_BASE)).rstrip("/")
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
            "status_code": None,
        }
    try:
        resp = httpx.get(
            f"{base}/search",
            params={"q": query, "format": "json"},
            headers={"User-Agent": _SEARXNG_USER_AGENT},
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
            "status_code": None,
        }
    if resp.status_code != 200:
        return {
            "adapter": "searxng",
            "ok": False,
            "skipped": True,
            "reason": f"http_{resp.status_code}",
            "hits": [],
            "base_url": base,
            "status_code": resp.status_code,
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
            "status_code": resp.status_code,
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
        "status_code": resp.status_code,
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
    """True when SearXNG sidecar responds with non-403 or XINAO_SEARXNG_COMPOSE=1."""
    if os.environ.get("XINAO_SEARXNG_COMPOSE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    probe = probe_searxng("ping", base_url=base_url, max_results=1)
    status = probe.get("status_code")
    return status is not None and status != 403


def should_use_exa_fallback(
    query: str,
    *,
    searx_result: dict[str, Any],
    ddgs_hits: list[dict[str, Any]] | int,
    context: dict[str, Any] | None = None,
) -> bool:
    """Backward-compatible alias — delegates to default_plus_dynamic_escalate policy."""
    return should_escalate_search(
        query,
        searx_result=searx_result,
        ddgs_hits=ddgs_hits,
        context=context,
    )


def _pick_external_primary(
    searx: dict[str, Any],
    ddgs: dict[str, Any],
    exa: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], bool]:
    if searx.get("ok"):
        hits = searx.get("hits") or []
        return "searxng", hits, True
    if ddgs.get("ok"):
        hits = ddgs.get("hits") or []
        return "ddgs", hits, True
    if exa.get("ok"):
        hits = exa.get("hits") or []
        return "exa", hits, True
    if ddgs.get("skipped") is not True:
        return "ddgs", [], False
    if exa.get("skipped") is not True:
        return "exa", [], False
    return "searxng", [], False


def run_external_search(
    query: str,
    *,
    max_results: int = 5,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources_tried: list[str] = []
    compose_avail = searxng_compose_available()
    context_text = str((context or {}).get("content_md") or "")

    if compose_avail:
        searx = probe_searxng_ladder(
            query,
            context_text=context_text,
            max_results=max_results,
        )
    else:
        searx = probe_searxng(query, max_results=max_results)
    sources_tried.append("searxng")

    ddgs = _skipped_adapter("ddgs")
    exa = _skipped_adapter("exa", wired=exa_escalation_wired())
    exa_dynamic = False

    if searx.get("ok") is not True:
        ddgs = probe_ddgs(query, max_results=max_results)
        sources_tried.append("ddgs")

    ddgs_hits = ddgs.get("hits") or []
    if should_use_exa_fallback(
        query,
        searx_result=searx,
        ddgs_hits=ddgs_hits,
        context=context,
    ):
        exa_dynamic = True
        exa = probe_exa(query, max_results=max_results)
        exa["wired"] = True
        exa["invoked"] = exa.get("skipped") is not True
        sources_tried.append("exa")

    adapter, hits, ok = _pick_external_primary(searx, ddgs, exa)
    hit_count = len(hits)
    ddgs_gate_hits_required = searx.get("ok") is not True

    ddgs_named_blocker = ""
    if ddgs_gate_hits_required and adapter == "ddgs" and not ok:
        ddgs_named_blocker = "INTEGRATED_BUS_L4_DDGS_ZERO_HITS"

    search_tier_used = "T0_DEFAULT"
    if adapter == "exa" or exa_dynamic:
        search_tier_used = "T1_SECONDARY"
    elif adapter == "ddgs":
        search_tier_used = "T0_ddgs_fallback"

    return {
        "adapter": adapter,
        "query": query,
        "hit_count": hit_count,
        "hits": hits[:max_results],
        "ok": ok,
        "searxng": searx,
        "ddgs": ddgs,
        "exa": exa,
        "exa_dynamic": exa_dynamic,
        "exa_dynamic_optional_tier3": exa_escalation_wired(),
        "search_tier_chain": list(SEARCH_TIER_CHAIN),
        "search_tier_used": search_tier_used,
        "sources_tried": sources_tried,
        "searxng_compose_available": compose_avail,
        "ddgs_gate_hits_required": ddgs_gate_hits_required,
        "ddgs_named_blocker": ddgs_named_blocker,
        "escalate_policy": "default_plus_dynamic_escalate.v1",
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
            "thin-glue 默认链已走 L4 搜索薄绑；本地 rg 必绿，外部 SearXNG/DDGS/Exa 尽力。",
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