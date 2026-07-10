"""Fixed local Mem0 storage primitives shared by the memory MCP server."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import portalocker

RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
MEMORY_ROOT = RUNTIME_ROOT / "state" / "mem0"

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
LLM_MODEL = "qwen3:8b"
EMBEDDER_MODEL = "nomic-embed-text"
EMBEDDING_DIMS = 768
VECTOR_PROVIDER = "qdrant"
COLLECTION_NAME = "xinao_codex_memory_v2"

# Portable lifecycle labels stored as ordinary metadata.  They deliberately do
# not activate Mem0's provider-specific temporal or procedural-memory features.
SUPPORTED_MEMORY_TYPES = ("semantic", "episodic", "procedural")
LIFECYCLE_METADATA_FIELDS = ("memory_type", "confidence", "expires_at", "supersedes")
SUPPORTED_SENSITIVITIES = ("public", "internal", "sensitive")
EVIDENCE_METADATA_FIELDS = ("source_ref", "valid_from", "last_verified_at", "sensitivity")

MEM0_OPERATION_LOCK_NAME = ".xinao-memory-operation.lock"
MEM0_OPERATION_LOCK_TIMEOUT_SECONDS = 10.0


class Mem0OperationBusy(RuntimeError):
    """Another local process owns the embedded Mem0 storage temporarily."""


def local_mem0_paths(runtime_root: str | Path = RUNTIME_ROOT) -> dict[str, Path]:
    """Return the fixed D-drive paths used by the embedded memory store."""
    base = Path(runtime_root) / "state" / "mem0"
    return {
        "base": base,
        "qdrant": base / "qdrant",
        "history_db": base / "history.db",
        "operation_lock": base / MEM0_OPERATION_LOCK_NAME,
    }


@contextmanager
def local_mem0_operation_lock(
    runtime_root: str | Path = RUNTIME_ROOT,
    *,
    timeout_seconds: float = MEM0_OPERATION_LOCK_TIMEOUT_SECONDS,
) -> Iterator[Path]:
    """Serialize processes that open the embedded Qdrant and history database."""
    paths = local_mem0_paths(runtime_root)
    paths["base"].mkdir(parents=True, exist_ok=True)
    lock_path = paths["operation_lock"]
    try:
        with portalocker.Lock(
            str(lock_path),
            mode="a",
            timeout=timeout_seconds,
            check_interval=0.1,
        ):
            yield lock_path
    except portalocker.exceptions.LockException as exc:
        raise Mem0OperationBusy("Local memory is busy; retry shortly") from exc


def close_local_mem0_memory(memory: Any) -> None:
    """Close QdrantLocal first and Mem0's SQLite history connection second."""
    vector_store = getattr(memory, "vector_store", None)
    client = getattr(vector_store, "client", None)
    client_close = getattr(client, "close", None)
    memory_close = getattr(memory, "close", None)
    try:
        if callable(client_close):
            client_close()
    finally:
        if callable(memory_close):
            memory_close()


def build_local_mem0_config(*, runtime_root: str | Path = RUNTIME_ROOT) -> dict[str, Any]:
    """Build the single supported Ollama + embedded Qdrant configuration."""
    paths = local_mem0_paths(runtime_root)
    return {
        "vector_store": {
            "provider": VECTOR_PROVIDER,
            "config": {
                "collection_name": COLLECTION_NAME,
                "path": str(paths["qdrant"]),
                "on_disk": True,
                "embedding_model_dims": EMBEDDING_DIMS,
            },
        },
        "llm": {
            "provider": "ollama",
            "config": {
                "model": LLM_MODEL,
                "ollama_base_url": OLLAMA_BASE_URL,
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": EMBEDDER_MODEL,
                "ollama_base_url": OLLAMA_BASE_URL,
            },
        },
        "history_db_path": str(paths["history_db"]),
    }
