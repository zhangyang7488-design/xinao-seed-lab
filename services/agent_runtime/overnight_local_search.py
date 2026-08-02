from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = "xinao.overnight.local_search.v1"


def _github_hint(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "github.com" or host.endswith(".github.com")


def search_ddgs(query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
    from ddgs import DDGS

    hits: list[dict[str, Any]] = []
    for row in DDGS().text(query, max_results=max_results):
        if not isinstance(row, dict):
            continue
        url = str(row.get("href") or row.get("url") or "")
        hits.append(
            {
                "title": str(row.get("title") or ""),
                "url": url,
                "snippet": str(row.get("body") or row.get("snippet") or "")[:500],
                "source": "ddgs",
                "is_github": _github_hint(url),
            }
        )
    return hits


def probe_ddgs(query: str, *, max_results: int = 5) -> dict[str, Any]:
    try:
        hits = search_ddgs(query, max_results=max_results)
        return {
            "adapter": "ddgs",
            "query": query,
            "ok": len(hits) > 0,
            "skipped": False,
            "hit_count": len(hits),
            "hits": hits,
        }
    except Exception as exc:
        return {
            "adapter": "ddgs",
            "query": query,
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "hit_count": 0,
            "hits": [],
        }


def probe_exa(query: str, *, max_results: int = 5) -> dict[str, Any]:
    api_key = os.environ.get("EXA_API_KEY", "").strip()
    if not api_key:
        return {
            "adapter": "exa",
            "query": query,
            "ok": False,
            "skipped": True,
            "reason": "exa_api_key_missing",
            "hit_count": 0,
            "hits": [],
        }
    try:
        hits = search_exa(query, max_results=max_results)
        return {
            "adapter": "exa",
            "query": query,
            "ok": len(hits) > 0,
            "skipped": False,
            "hit_count": len(hits),
            "hits": hits,
        }
    except Exception as exc:
        return {
            "adapter": "exa",
            "query": query,
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "hit_count": 0,
            "hits": [],
        }


def search_exa(query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
    api_key = os.environ.get("EXA_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        import httpx
    except ImportError:
        return []
    resp = httpx.post(
        "https://api.exa.ai/search",
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json={"query": query, "numResults": max_results, "type": "auto"},
        timeout=30.0,
    )
    if resp.status_code != 200:
        return []
    payload = resp.json()
    hits: list[dict[str, Any]] = []
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        hits.append(
            {
                "title": str(row.get("title") or ""),
                "url": url,
                "snippet": str(row.get("text") or row.get("snippet") or "")[:500],
                "source": "exa",
                "is_github": _github_hint(url),
            }
        )
    return hits


def local_search(query: str, *, max_results: int = 5) -> dict[str, Any]:
    ddgs_hits = search_ddgs(query, max_results=max_results)
    exa_hits = search_exa(query, max_results=max_results) if not ddgs_hits else []
    merged = ddgs_hits + [h for h in exa_hits if h["url"] not in {x["url"] for x in ddgs_hits}]
    github_first = sorted(merged, key=lambda h: (not h.get("is_github"), h.get("url", "")))
    return {
        "schema_version": SCHEMA_VERSION,
        "query": query,
        "hit_count": len(github_first),
        "github_hit_count": sum(1 for h in github_first if h.get("is_github")),
        "sources_used": [
            s for s in ("ddgs", "exa") if (ddgs_hits and s == "ddgs") or (exa_hits and s == "exa")
        ],
        "hits": github_first[:max_results],
    }

