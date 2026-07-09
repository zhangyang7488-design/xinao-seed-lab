from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = "xinao.overnight.local_search.v1"


def _github_hint(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "github.com" in host


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
        "sources_used": [s for s in ("ddgs", "exa") if (ddgs_hits and s == "ddgs") or (exa_hits and s == "exa")],
        "hits": github_first[:max_results],
    }


def load_glue_authority(glue_dir: Path) -> str:
    parts: list[str] = []
    for name in (
        "00_先发这个_阅读顺序.txt",
        "XINAO_外部薄胶开焊总图_20260708.txt",
        "XINAO_Phase0_第一刀施工包_20260708.txt",
    ):
        path = glue_dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"### {name}\n{text[:6000]}")
    return "\n\n".join(parts)


def build_item_context(
    item: dict[str, Any],
    *,
    glue_dir: Path,
    runtime_root: Path,
    wave_id: str,
) -> Path:
    queries = item.get("github_queries") or []
    search_blocks: list[dict[str, Any]] = []
    for q in queries[:2]:
        search_blocks.append(local_search(str(q), max_results=5))

    out_dir = runtime_root / "overnight" / wave_id / "local_search"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{item['id']}_context.json"
    payload = {
        "schema_version": "xinao.overnight.item_context.v1",
        "item_id": item["id"],
        "layer": item.get("layer"),
        "sunset_target": item.get("sunset_target"),
        "replace_with": item.get("replace_with"),
        "glue_authority_dir": str(glue_dir),
        "glue_authority_excerpt": load_glue_authority(glue_dir),
        "local_search": search_blocks,
        "routing_note": "local_search_first_then_qwen_draft; dp_sparing",
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items-file", required=True)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--glue-dir", default=r"C:\Users\xx363\Desktop\仓库胶水")
    parser.add_argument("--runtime-root", default=r"D:\XINAO_RESEARCH_RUNTIME")
    parser.add_argument("--wave-id", default="overnight-glue-20260708")
    args = parser.parse_args(argv)

    items = json.loads(Path(args.items_file).read_text(encoding="utf-8"))["items"]
    item = next((x for x in items if x["id"] == args.item_id), None)
    if not item:
        print(json.dumps({"error": "item_not_found", "item_id": args.item_id}))
        return 2
    out_path = build_item_context(
        item,
        glue_dir=Path(args.glue_dir),
        runtime_root=Path(args.runtime_root),
        wave_id=args.wave_id,
    )
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())