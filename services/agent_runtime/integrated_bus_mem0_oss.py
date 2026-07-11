"""Mem0 OSS self-hosted — Ollama + D-disk vector store; E-disk mirror read-only."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, write_json

SCHEMA_VERSION = "xinao.integrated_bus.mem0_oss.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_MEM0_OSS_V1"


def mem0_hot_paths(runtime_root: str | Path = DEFAULT_RUNTIME) -> dict[str, Path]:
    """D 盘热存 — 向量库 / history / 证据（禁止写 E 盘 EXTERNAL_MATURE）。"""
    base = Path(runtime_root) / "state" / "mem0"
    return {
        "base": base,
        "qdrant": base / "qdrant",
        "chroma": base / "chroma",
        "history_db": base / "history.db",
        "evidence": base / "oss_evidence",
    }


def build_mem0_oss_config(params: dict[str, Any], *, runtime_root: Path) -> dict[str, Any]:
    paths = mem0_hot_paths(runtime_root)
    for key in ("qdrant", "chroma", "evidence"):
        paths[key].mkdir(parents=True, exist_ok=True)

    ollama_base = str(params.get("mem0_ollama_base_url") or "http://127.0.0.1:11434")
    llm_model = str(params.get("mem0_llm_model") or "qwen3:8b")
    embedder_model = str(params.get("mem0_embedder_model") or llm_model)
    vector_provider = str(params.get("mem0_vector_provider") or "qdrant")
    collection = str(params.get("mem0_collection_name") or "xinao_integrated_bus")

    if vector_provider == "chroma":
        vector_store = {
            "provider": "chroma",
            "config": {
                "collection_name": collection,
                "path": str(paths["chroma"]),
            },
        }
    else:
        vector_store = {
            "provider": "qdrant",
            "config": {
                "collection_name": collection,
                "path": str(paths["qdrant"]),
                "on_disk": True,
            },
        }

    history_path = str(params.get("mem0_history_path") or paths["history_db"])
    os.environ.setdefault("MEM0_DIR", str(paths["base"]))

    config: dict[str, Any] = {
        "vector_store": vector_store,
        "llm": {
            "provider": "ollama",
            "config": {
                "model": llm_model,
                "ollama_base_url": ollama_base,
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": embedder_model,
                "ollama_base_url": ollama_base,
            },
        },
        "history_db_path": history_path,
    }

    if params.get("mem0_graph_enabled"):
        graph_path = paths["base"] / "graph"
        graph_path.mkdir(parents=True, exist_ok=True)
        config["graph_store"] = {
            "provider": str(params.get("mem0_graph_provider") or "kuzu"),
            "config": {"db": str(graph_path / "mem0_graph.kuzu")},
        }
    return config


def mem0_use_platform_api(params: dict[str, Any]) -> bool:
    if params.get("mem0_oss_mode", True) is False:
        return True
    flag = os.environ.get("XINAO_MEM0_USE_PLATFORM", "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def invoke_mem0_oss_add_search(
    *,
    runtime_root: Path,
    params: dict[str, Any],
    summary_text: str,
    user_id: str,
    replay_ref: str,
    search_query: str | None = None,
) -> dict[str, Any]:
    """OSS add + search smoke; no MEM0 Platform API key."""
    paths = mem0_hot_paths(runtime_root)
    messages = [
        {"role": "user", "content": "XINAO integrated_bus replay promotion"},
        {"role": "assistant", "content": summary_text[:4000]},
    ]
    query = search_query or "integrated_bus promotion replay"

    if mem0_use_platform_api(params):
        api_key = os.environ.get("MEM0_API_KEY", "").strip()
        if not api_key:
            return {
                "mem0_invoke_ok": False,
                "mem0_adapter": "mem0ai_platform_api",
                "error": "MEM0_API_KEY missing",
                "mem0_oss_mode": False,
            }
        try:
            from mem0 import MemoryClient  # type: ignore[import-untyped]

            client = MemoryClient(api_key=api_key)
            client.add(messages, user_id=user_id, metadata={"replay_ref": replay_ref})
            hits = client.search(query, filters={"user_id": user_id})
            return {
                "mem0_invoke_ok": True,
                "mem0_adapter": "mem0ai_platform_api",
                "mem0_store": "cloud",
                "mem0_search_count": len((hits or {}).get("results") or []),
            }
        except Exception as exc:
            return {
                "mem0_invoke_ok": False,
                "mem0_adapter": "mem0ai_platform_api",
                "error": str(exc),
            }

    try:
        from mem0 import Memory  # type: ignore[import-untyped]
    except ImportError as exc:
        return {
            "mem0_invoke_ok": False,
            "mem0_adapter": "mem0ai_oss_import_missing",
            "error": str(exc),
            "hint": "uv pip install mem0ai qdrant-client",
        }

    providers_to_try = [str(params.get("mem0_vector_provider") or "qdrant")]
    if providers_to_try[0] == "qdrant":
        providers_to_try.append("chroma")

    last_error = ""
    for provider in providers_to_try:
        attempt_params = dict(params)
        attempt_params["mem0_vector_provider"] = provider
        attempt_config = build_mem0_oss_config(attempt_params, runtime_root=runtime_root)
        try:
            memory = Memory.from_config(attempt_config)
            add_result = memory.add(messages, user_id=user_id, metadata={"replay_ref": replay_ref})
            search_result = memory.search(query, filters={"user_id": user_id})
            results: list[Any] = []
            if isinstance(search_result, dict):
                results = list(search_result.get("results") or [])
            elif isinstance(search_result, list):
                results = search_result

            evidence = {
                "schema_version": SCHEMA_VERSION,
                "sentinel": SENTINEL,
                "mem0_oss_mode": True,
                "mem0_platform_key_required": False,
                "cold_mirror": str(params.get("mem0_mirror") or ""),
                "hot_paths": {k: str(v) for k, v in paths.items()},
                "config_summary": {
                    "llm": attempt_config["llm"]["config"]["model"],
                    "embedder": attempt_config["embedder"]["config"]["model"],
                    "vector_provider": attempt_config["vector_store"]["provider"],
                    "vector_path": attempt_config["vector_store"]["config"].get("path"),
                    "history_db_path": attempt_config.get("history_db_path"),
                    "graph_enabled": "graph_store" in attempt_config,
                },
                "add_result_type": type(add_result).__name__,
                "search_query": query,
                "search_hit_count": len(results),
                "user_id": user_id,
                "replay_ref": replay_ref,
            }
            write_json(paths["evidence"] / "latest.json", evidence)

            return {
                "mem0_invoke_ok": True,
                "mem0_adapter": "mem0ai_oss_self_hosted",
                "mem0_oss_mode": True,
                "mem0_platform_key_required": False,
                "mem0_store": str(paths["base"]),
                "mem0_vector_path": attempt_config["vector_store"]["config"].get("path"),
                "mem0_vector_provider": provider,
                "mem0_history_path": attempt_config.get("history_db_path"),
                "mem0_search_count": len(results),
                "mem0_evidence_ref": str(paths["evidence"] / "latest.json"),
            }
        except Exception as exc:
            last_error = str(exc)
            continue

    return {
        "mem0_invoke_ok": False,
        "mem0_adapter": "mem0ai_oss_self_hosted",
        "mem0_oss_mode": True,
        "error": last_error,
        "hot_paths": {k: str(v) for k, v in paths.items()},
    }
