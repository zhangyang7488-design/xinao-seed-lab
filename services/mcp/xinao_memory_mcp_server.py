"""Explicit, local-only Mem0 OSS MCP surface for XINAO memory operations.

This server is intentionally separate from ``xinao_mcp_server.py``.  Importing
the module does not initialize Mem0, contact Ollama, or write runtime state;
the backend is created lazily on the first memory operation.  The only
supported transport is stdio.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Any, Iterator, Mapping

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

# The canonical Codex MCP entry invokes this file by absolute path.  In that
# direct-script mode Python puts ``services/mcp`` rather than the repository
# root on sys.path, so the package import below would fail before the MCP
# handshake.  Derive only this file's own fixed project root; normal package
# imports are untouched.
if __package__ in (None, ""):
    _PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

from services.mcp.local_mem0_store import (
    COLLECTION_NAME,
    EMBEDDER_MODEL,
    EMBEDDING_DIMS,
    EVIDENCE_METADATA_FIELDS,
    LIFECYCLE_METADATA_FIELDS,
    LLM_MODEL,
    MEM0_OPERATION_LOCK_TIMEOUT_SECONDS,
    MEMORY_ROOT,
    OLLAMA_BASE_URL,
    RUNTIME_ROOT,
    SUPPORTED_MEMORY_TYPES,
    SUPPORTED_SENSITIVITIES,
    VECTOR_PROVIDER,
    Mem0OperationBusy,
    build_local_mem0_config,
    close_local_mem0_memory,
    local_mem0_operation_lock,
    local_mem0_paths,
)

SCHEMA_VERSION = "xinao.memory.mcp.v1"
SERVER_NAME = "xinao-local-mem0-oss"

MAX_TEXT_CHARS = 8_000
MAX_QUERY_CHARS = 2_000
MAX_IDENTIFIER_CHARS = 160
MAX_PROVENANCE_CHARS = 1_000
MAX_SOURCE_REF_CHARS = 1_000
MAX_METADATA_CHARS = 8_000
MAX_METADATA_DEPTH = 5
MAX_METADATA_ITEMS = 64
MAX_TOP_K = 50
MAX_HISTORY_EVENTS = 50

_RESERVED_METADATA_KEYS = frozenset(
    {
        "agent_id",
        "created_at",
        "data",
        "hash",
        "id",
        "memory",
        "project",
        "provenance",
        "run_id",
        "scope",
        "score",
        "timestamp",
        "updated_at",
        "user_id",
    }
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|password|secret|token)(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.DOTALL,
)
_HISTORY_STRING_LIMITS = {
    "id": MAX_IDENTIFIER_CHARS,
    "memory_id": MAX_IDENTIFIER_CHARS,
    "old_memory": MAX_TEXT_CHARS,
    "new_memory": MAX_TEXT_CHARS,
    "event": 64,
    "created_at": 64,
    "updated_at": 64,
    "actor_id": MAX_IDENTIFIER_CHARS,
    "role": MAX_IDENTIFIER_CHARS,
}


class MemoryInputError(ValueError):
    """A bounded, safe-to-return input validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LocalBoundaryError(RuntimeError):
    """The generated Mem0 configuration escaped the fixed local boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MemoryBusyError(RuntimeError):
    """The shared local memory store is temporarily owned by another process."""

    code = "memory_busy"


mcp = FastMCP(
    SERVER_NAME,
    instructions=(
        "Explicit local-only XINAO memory tools backed by Mem0 OSS. "
        "All records are scoped by user_id, project, and scope. The backend is fixed to "
        "Ollama at 127.0.0.1:11434, qwen3:8b, nomic-embed-text, and the local "
        "D:\\XINAO_RESEARCH_RUNTIME\\state\\mem0 store. No hosted Mem0 client or bulk "
        "delete operation is exposed."
    ),
)

_READ_ONLY_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_RECONCILING_WRITE_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
_CREATE_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
_UPDATE_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
_DELETE_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)

_memory_instance: Any | None = None
_memory_operation_lock = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right))
    )


def _enforce_local_process_settings() -> None:
    # Mem0 OSS telemetry is networked by default. Set this before importing mem0.
    os.environ["MEM0_TELEMETRY"] = "false"
    # Overwrite ambient state so another tool cannot redirect Mem0's local files.
    os.environ["MEM0_DIR"] = str(MEMORY_ROOT)


def _validate_local_config(config: Mapping[str, Any]) -> None:
    llm = config.get("llm")
    embedder = config.get("embedder")
    vector_store = config.get("vector_store")
    if not isinstance(llm, Mapping) or llm.get("provider") != "ollama":
        raise LocalBoundaryError("llm_provider_not_local", "Mem0 LLM provider must be Ollama")
    if not isinstance(embedder, Mapping) or embedder.get("provider") != "ollama":
        raise LocalBoundaryError(
            "embedder_provider_not_local", "Mem0 embedder provider must be Ollama"
        )
    if not isinstance(vector_store, Mapping) or vector_store.get("provider") != VECTOR_PROVIDER:
        raise LocalBoundaryError(
            "vector_provider_not_local", "Mem0 vector provider must be embedded Qdrant"
        )

    llm_config = llm.get("config")
    embedder_config = embedder.get("config")
    vector_config = vector_store.get("config")
    if not isinstance(llm_config, Mapping) or (
        llm_config.get("model") != LLM_MODEL or llm_config.get("ollama_base_url") != OLLAMA_BASE_URL
    ):
        raise LocalBoundaryError(
            "llm_boundary_mismatch", "Mem0 LLM configuration is not fixed-local"
        )
    if not isinstance(embedder_config, Mapping) or (
        embedder_config.get("model") != EMBEDDER_MODEL
        or embedder_config.get("ollama_base_url") != OLLAMA_BASE_URL
    ):
        raise LocalBoundaryError(
            "embedder_boundary_mismatch", "Mem0 embedder configuration is not fixed-local"
        )
    if not isinstance(vector_config, Mapping) or (
        vector_config.get("collection_name") != COLLECTION_NAME
        or vector_config.get("embedding_model_dims") != EMBEDDING_DIMS
        or vector_config.get("on_disk") is not True
        or not _same_path(str(vector_config.get("path", "")), MEMORY_ROOT / "qdrant")
    ):
        raise LocalBoundaryError(
            "vector_path_boundary_mismatch", "Mem0 vector storage is outside the fixed local path"
        )
    if not _same_path(str(config.get("history_db_path", "")), MEMORY_ROOT / "history.db"):
        raise LocalBoundaryError(
            "history_path_boundary_mismatch", "Mem0 history storage is outside the fixed local path"
        )
    if "graph_store" in config:
        raise LocalBoundaryError("graph_store_disabled", "Mem0 graph storage is disabled")


def _build_local_config() -> dict[str, Any]:
    _enforce_local_process_settings()
    config = build_local_mem0_config(runtime_root=RUNTIME_ROOT)
    _validate_local_config(config)
    return config


def _create_memory_instance() -> Any:
    config = _build_local_config()
    try:
        from mem0 import Memory  # type: ignore[import-untyped]
    except ImportError as exc:
        raise LocalBoundaryError(
            "mem0_dependency_missing",
            "Mem0 OSS dependencies are not installed; install the project memory extra",
        ) from exc
    telemetry_module = sys.modules.get("mem0.memory.telemetry")
    if telemetry_module is not None and getattr(telemetry_module, "MEM0_TELEMETRY", False):
        raise LocalBoundaryError(
            "mem0_telemetry_preloaded",
            "Mem0 telemetry was enabled before local memory initialization; refusing startup",
        )
    return Memory.from_config(config)


def _preload_local_backend_dependencies() -> bool:
    """Warm Mem0's native imports before FastMCP starts its event loop.

    FastMCP 1.28 executes synchronous tool functions on the server event-loop
    thread.  On Windows, lazily importing Mem0 from the first tool call also
    imports Qdrant and NumPy native extensions while AnyIO's stdio threads are
    already active.  That cold import can block the protocol loop for tens of
    seconds.  Importing the class here does not open Qdrant, SQLite, or Ollama;
    the per-operation storage lifecycle remains lazy.

    A missing optional dependency is left for ``xinao_memory_status`` to
    report.  An already-loaded telemetry-enabled Mem0 remains a hard boundary
    violation.
    """
    _enforce_local_process_settings()
    try:
        from mem0 import Memory as _Memory  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        return False
    telemetry_module = sys.modules.get("mem0.memory.telemetry")
    if telemetry_module is not None and getattr(telemetry_module, "MEM0_TELEMETRY", False):
        raise LocalBoundaryError(
            "mem0_telemetry_preloaded",
            "Mem0 telemetry was enabled before local memory initialization; refusing startup",
        )
    return True


def _get_memory() -> Any:
    """Return a test override or a fresh instance for one serialized operation."""
    if _memory_instance is not None:
        return _memory_instance
    return _create_memory_instance()


@contextmanager
def _memory_session() -> Iterator[Any]:
    """Open embedded Mem0 only while this process owns the cross-process lock."""
    with _memory_operation_lock:
        if _memory_instance is not None:
            yield _memory_instance
            return
        try:
            with local_mem0_operation_lock(RUNTIME_ROOT):
                memory = _create_memory_instance()
                try:
                    yield memory
                finally:
                    close_local_mem0_memory(memory)
        except Mem0OperationBusy as exc:
            raise MemoryBusyError("Local memory is busy; retry shortly") from exc


def _dependency_available() -> bool:
    try:
        return importlib.util.find_spec("mem0") is not None
    except (ImportError, ValueError):
        return False


def _probe_local_ollama() -> dict[str, Any]:
    """Probe the fixed loopback endpoint directly, without proxy or ambient credentials."""
    connection: HTTPConnection | None = None
    try:
        connection = HTTPConnection("127.0.0.1", 11434, timeout=1.5)
        connection.request("GET", "/api/tags", headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(200_001)
        if response.status != 200:
            return {
                "reachable": True,
                "ready": False,
                "status_code": response.status,
                "error_code": "ollama_http_error",
            }
        if len(body) > 200_000:
            return {
                "reachable": True,
                "ready": False,
                "status_code": response.status,
                "error_code": "ollama_response_too_large",
            }
        payload = json.loads(body.decode("utf-8"))
        models = payload.get("models", []) if isinstance(payload, dict) else []
        names = {
            str(value)
            for item in models
            if isinstance(item, Mapping)
            for value in (item.get("name"), item.get("model"))
            if value
        }

        def model_available(required: str) -> bool:
            aliases = {required}
            if ":" not in required:
                aliases.add(f"{required}:latest")
            return bool(aliases.intersection(names))

        required_models = {
            "llm": {"name": LLM_MODEL, "available": model_available(LLM_MODEL)},
            "embedder": {
                "name": EMBEDDER_MODEL,
                "available": model_available(EMBEDDER_MODEL),
            },
        }
        return {
            "reachable": True,
            "ready": all(item["available"] for item in required_models.values()),
            "status_code": response.status,
            "required_models": required_models,
        }
    except (OSError, HTTPException, json.JSONDecodeError, UnicodeDecodeError):
        return {
            "reachable": False,
            "ready": False,
            "status_code": None,
            "error_code": "ollama_unavailable",
        }
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def _bounded_string(name: str, value: Any, max_chars: int) -> str:
    if not isinstance(value, str):
        raise MemoryInputError("invalid_type", f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise MemoryInputError("empty_value", f"{name} must not be empty")
    if len(normalized) > max_chars:
        raise MemoryInputError("value_too_long", f"{name} exceeds {max_chars} characters")
    return normalized


def _identifier(name: str, value: Any) -> str:
    normalized = _bounded_string(name, value, MAX_IDENTIFIER_CHARS)
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise MemoryInputError("invalid_identifier", f"{name} contains control characters")
    return normalized


def _normalize_boundary(user_id: Any, project: Any, scope: Any) -> dict[str, str]:
    return {
        "user_id": _identifier("user_id", user_id),
        "project": _identifier("project", project),
        "scope": _identifier("scope", scope),
    }


def _validate_metadata_value(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_METADATA_DEPTH:
        raise MemoryInputError("metadata_too_deep", "metadata nesting is too deep")
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        if len(value) > MAX_METADATA_ITEMS:
            raise MemoryInputError("metadata_too_many_items", "metadata list is too large")
        for item in value:
            _validate_metadata_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_METADATA_ITEMS:
            raise MemoryInputError("metadata_too_many_items", "metadata object is too large")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > MAX_IDENTIFIER_CHARS:
                raise MemoryInputError(
                    "invalid_metadata_key", "metadata keys must be bounded strings"
                )
            _validate_metadata_value(item, depth=depth + 1)
        return
    raise MemoryInputError("invalid_metadata_value", "metadata must contain only JSON values")


def _normalize_metadata(metadata: Any) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise MemoryInputError("invalid_metadata", "metadata must be an object")
    reserved = sorted(_RESERVED_METADATA_KEYS.intersection(metadata))
    if reserved:
        raise MemoryInputError(
            "reserved_metadata_key",
            f"metadata contains reserved keys: {', '.join(reserved)}",
        )
    _validate_metadata_value(metadata)
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise MemoryInputError("invalid_metadata", "metadata must be finite JSON") from exc
    if len(encoded) > MAX_METADATA_CHARS:
        raise MemoryInputError(
            "metadata_too_large", f"metadata exceeds {MAX_METADATA_CHARS} serialized characters"
        )
    # Round-trip to detach caller-owned nested containers and guarantee JSON-safe output.
    return json.loads(encoded)


def _normalize_timestamp(value: Any) -> str:
    if value is None:
        return _utc_now()
    raw = _bounded_string("timestamp", value, 64)
    candidate = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise MemoryInputError("invalid_timestamp", "timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise MemoryInputError("invalid_timestamp", "timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_top_k(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_TOP_K:
        raise MemoryInputError("invalid_top_k", f"top_k must be between 1 and {MAX_TOP_K}")
    return value


def _normalize_threshold(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MemoryInputError("invalid_threshold", "min_score must be a number from 0 to 1")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise MemoryInputError("invalid_threshold", "min_score must be a number from 0 to 1")
    return normalized


def _normalize_memory_type(value: Any) -> str:
    normalized = _bounded_string("memory_type", value, 32)
    if normalized not in SUPPORTED_MEMORY_TYPES:
        choices = ", ".join(SUPPORTED_MEMORY_TYPES)
        raise MemoryInputError("invalid_memory_type", f"memory_type must be one of: {choices}")
    return normalized


def _normalize_confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MemoryInputError("invalid_confidence", "confidence must be a number from 0 to 1")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise MemoryInputError("invalid_confidence", "confidence must be a number from 0 to 1")
    return normalized


def _normalize_utc_metadata_timestamp(name: str, value: Any) -> str:
    raw = _bounded_string(name, value, 64)
    candidate = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise MemoryInputError(
            f"invalid_{name}", f"{name} must be a timezone-aware ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise MemoryInputError(
            f"invalid_{name}", f"{name} must be a timezone-aware ISO-8601 timestamp"
        )
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_expires_at(value: Any) -> str:
    return _normalize_utc_metadata_timestamp("expires_at", value)


def _normalize_source_ref(value: Any) -> str:
    return _bounded_string("source_ref", value, MAX_SOURCE_REF_CHARS)


def _normalize_sensitivity(value: Any) -> str:
    normalized = _bounded_string("sensitivity", value, 32)
    if normalized not in SUPPORTED_SENSITIVITIES:
        choices = ", ".join(SUPPORTED_SENSITIVITIES)
        raise MemoryInputError("invalid_sensitivity", f"sensitivity must be one of: {choices}")
    return normalized


def _normalize_include_expired(value: Any) -> bool:
    if not isinstance(value, bool):
        raise MemoryInputError("invalid_include_expired", "include_expired must be a boolean")
    return value


def _normalize_memory_metadata(
    metadata: dict[str, Any],
    *,
    memory_type: Any = None,
    confidence: Any = None,
    expires_at: Any = None,
    supersedes: Any = None,
    source_ref: Any = None,
    valid_from: Any = None,
    last_verified_at: Any = None,
    sensitivity: Any = None,
) -> dict[str, Any]:
    """Validate managed fields supplied explicitly or through legacy metadata."""
    normalized = dict(metadata)
    values = {
        "memory_type": memory_type if memory_type is not None else normalized.get("memory_type"),
        "confidence": confidence if confidence is not None else normalized.get("confidence"),
        "expires_at": expires_at if expires_at is not None else normalized.get("expires_at"),
        "supersedes": supersedes if supersedes is not None else normalized.get("supersedes"),
        "source_ref": source_ref if source_ref is not None else normalized.get("source_ref"),
        "valid_from": valid_from if valid_from is not None else normalized.get("valid_from"),
        "last_verified_at": (
            last_verified_at if last_verified_at is not None else normalized.get("last_verified_at")
        ),
        "sensitivity": (sensitivity if sensitivity is not None else normalized.get("sensitivity")),
    }
    validators = {
        "memory_type": _normalize_memory_type,
        "confidence": _normalize_confidence,
        "expires_at": _normalize_expires_at,
        "supersedes": lambda value: _identifier("supersedes", value),
        "source_ref": _normalize_source_ref,
        "valid_from": lambda value: _normalize_utc_metadata_timestamp("valid_from", value),
        "last_verified_at": lambda value: _normalize_utc_metadata_timestamp(
            "last_verified_at", value
        ),
        "sensitivity": _normalize_sensitivity,
    }
    for key, value in values.items():
        if value is None:
            normalized.pop(key, None)
        else:
            normalized[key] = validators[key](value)
    return normalized


def _domain_metadata(
    boundary: Mapping[str, str],
    *,
    metadata: Any,
    provenance: Any,
    timestamp: Any,
    memory_type: Any = None,
    confidence: Any = None,
    expires_at: Any = None,
    supersedes: Any = None,
    source_ref: Any = None,
    valid_from: Any = None,
    last_verified_at: Any = None,
    sensitivity: Any = None,
) -> dict[str, Any]:
    normalized = _normalize_memory_metadata(
        _normalize_metadata(metadata),
        memory_type=memory_type,
        confidence=confidence,
        expires_at=expires_at,
        supersedes=supersedes,
        source_ref=source_ref,
        valid_from=valid_from,
        last_verified_at=last_verified_at,
        sensitivity=sensitivity,
    )
    normalized.update(
        {
            "user_id": boundary["user_id"],
            "run_id": _domain_run_id(boundary),
            "project": boundary["project"],
            "scope": boundary["scope"],
            "provenance": _bounded_string("provenance", provenance, MAX_PROVENANCE_CHARS),
            "timestamp": _normalize_timestamp(timestamp),
        }
    )
    return normalized


def _domain_run_id(boundary: Mapping[str, str]) -> str:
    """Map the public three-part domain onto Mem0's native query-time run scope."""
    encoded = json.dumps(
        [boundary["user_id"], boundary["project"], boundary["scope"]],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"xinao-memory-{hashlib.sha256(encoded).hexdigest()}"


def _filters(boundary: Mapping[str, str]) -> dict[str, str]:
    return {
        "user_id": boundary["user_id"],
        "run_id": _domain_run_id(boundary),
        "project": boundary["project"],
        "scope": boundary["scope"],
    }


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[TRUNCATED_NESTING]"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth=depth + 1) for item in value[:MAX_TOP_K]]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(), depth=depth + 1)
    return {"type": type(value).__name__, "serializable": False}


def _results(value: Any) -> list[Any]:
    safe = _json_safe(value)
    if isinstance(safe, dict):
        nested = safe.get("results")
        if isinstance(nested, list):
            return nested
        return [safe]
    if isinstance(safe, list):
        return safe
    return [] if safe is None else [safe]


def _record_matches(record: Any, boundary: Mapping[str, str]) -> bool:
    if not isinstance(record, Mapping):
        return False
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    record_user_id = record.get("user_id", metadata.get("user_id"))
    return (
        record_user_id == boundary["user_id"]
        and record.get("run_id", metadata.get("run_id")) == _domain_run_id(boundary)
        and metadata.get("project") == boundary["project"]
        and metadata.get("scope") == boundary["scope"]
    )


def _record_is_expired(record: Any, *, now: datetime | None = None) -> bool:
    """Return true only for a well-formed lifecycle timestamp at or before now."""
    if not isinstance(record, Mapping):
        return False
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    raw = record.get("expires_at", metadata.get("expires_at"))
    if raw is None:
        return False
    try:
        normalized = _normalize_expires_at(raw)
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except MemoryInputError:
        # New writes cannot create malformed values.  Legacy malformed metadata
        # is retained and visible rather than being silently treated as expired.
        return False
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return parsed <= current.astimezone(timezone.utc)


def _record_visible(
    record: Any,
    boundary: Mapping[str, str],
    *,
    include_expired: bool,
) -> bool:
    return _record_matches(record, boundary) and (include_expired or not _record_is_expired(record))


def _bounded_redacted_history_string(value: Any, max_chars: int) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, str):
        return None, False
    redacted = _PRIVATE_KEY_BLOCK.sub("[REDACTED_PRIVATE_KEY]", value)
    redacted = _BEARER_TOKEN.sub("Bearer [REDACTED]", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", redacted)
    if len(redacted) <= max_chars:
        return redacted, False
    marker = "...[TRUNCATED]"
    return redacted[: max_chars - len(marker)] + marker, True


def _sanitize_history_events(raw: Any, memory_id: str) -> tuple[list[dict[str, Any]], bool]:
    """Whitelist, redact, and bound local Mem0 history rows for one exact ID."""
    if isinstance(raw, Mapping):
        nested = raw.get("results")
        candidates = nested if isinstance(nested, (list, tuple)) else []
    elif isinstance(raw, (list, tuple)):
        candidates = raw
    else:
        candidates = []

    truncated = len(candidates) > MAX_HISTORY_EVENTS
    sanitized_events: list[dict[str, Any]] = []
    for event in candidates[:MAX_HISTORY_EVENTS]:
        if not isinstance(event, Mapping) or event.get("memory_id") != memory_id:
            continue
        sanitized: dict[str, Any] = {}
        for key, max_chars in _HISTORY_STRING_LIMITS.items():
            value, value_truncated = _bounded_redacted_history_string(event.get(key), max_chars)
            sanitized[key] = value
            truncated = truncated or value_truncated
        deleted = event.get("is_deleted")
        sanitized["is_deleted"] = (
            bool(deleted) if isinstance(deleted, (bool, int)) and deleted in (0, 1) else None
        )
        sanitized_events.append(sanitized)
    return sanitized_events, truncated


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, (MemoryInputError, LocalBoundaryError, MemoryBusyError)):
        message = str(exc)
    else:
        message = "The local Mem0 backend could not complete the operation"
    message = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", message)
    return message[:600]


def _error_payload(operation: str, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, (MemoryInputError, LocalBoundaryError, MemoryBusyError)):
        code = exc.code
    else:
        code = "local_backend_error"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "operation": operation,
        "local_only": True,
        "timestamp": _utc_now(),
        "error": {
            "code": code,
            "type": type(exc).__name__,
            "message": _safe_error_message(exc),
        },
    }
    if isinstance(exc, MemoryBusyError):
        payload["error"]["retryable"] = True
        payload["error"]["retry_after_seconds"] = 2
    return payload


def _success_payload(
    operation: str,
    *,
    boundary: Mapping[str, str] | None = None,
    **payload: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "operation": operation,
        "local_only": True,
        "timestamp": _utc_now(),
    }
    if boundary is not None:
        result["boundary"] = dict(boundary)
    result.update({key: _json_safe(value) for key, value in payload.items()})
    return result


def _add(
    operation: str,
    *,
    text: Any,
    user_id: Any,
    project: Any,
    scope: Any,
    provenance: Any,
    metadata: Any,
    timestamp: Any,
    memory_type: Any,
    confidence: Any,
    expires_at: Any,
    supersedes: Any,
    source_ref: Any,
    valid_from: Any,
    last_verified_at: Any,
    sensitivity: Any,
    infer: bool,
) -> dict[str, Any]:
    try:
        boundary = _normalize_boundary(user_id, project, scope)
        content = _bounded_string("text", text, MAX_TEXT_CHARS)
        stored_metadata = _domain_metadata(
            boundary,
            metadata=metadata,
            provenance=provenance,
            timestamp=timestamp,
            memory_type=memory_type,
            confidence=confidence,
            expires_at=expires_at,
            supersedes=supersedes,
            source_ref=source_ref,
            valid_from=valid_from,
            last_verified_at=last_verified_at,
            sensitivity=sensitivity,
        )
        with _memory_session() as memory:
            raw = memory.add(
                content,
                user_id=boundary["user_id"],
                run_id=_domain_run_id(boundary),
                metadata=stored_metadata,
                infer=infer,
            )
        items = _results(raw)
        return _success_payload(
            operation,
            boundary=boundary,
            count=len(items),
            results=items,
            infer=infer,
            record_timestamp=stored_metadata["timestamp"],
            provenance=stored_metadata["provenance"],
        )
    except Exception as exc:
        return _error_payload(operation, exc)


@mcp.tool(annotations=_READ_ONLY_TOOL)
def xinao_memory_status() -> dict[str, Any]:
    """Report the fixed local boundary and lazy backend state without initializing Mem0."""
    try:
        _validate_local_config(build_local_mem0_config(runtime_root=RUNTIME_ROOT))
        local_config_ok = True
        local_config_error = None
    except Exception as exc:
        local_config_ok = False
        local_config_error = _error_payload("status", exc)["error"]
    dependency_available = _dependency_available()
    ollama_probe = _probe_local_ollama()
    return _success_payload(
        "status",
        backend="mem0ai_oss",
        initialized=_memory_instance is not None,
        backend_lifecycle="per_operation_interprocess_serialized",
        multiprocess_safe_access=True,
        operation_lock_path=str(local_mem0_paths(RUNTIME_ROOT)["operation_lock"]),
        operation_lock_timeout_sec=MEM0_OPERATION_LOCK_TIMEOUT_SECONDS,
        dependency_available=dependency_available,
        local_config_ok=local_config_ok,
        local_config_error=local_config_error,
        mem0_oss_mode=True,
        hosted_mem0_enabled=False,
        telemetry_enabled=False,
        native_domain_isolation="user_id+deterministic_run_id+project+scope",
        memory_lifecycle={
            "metadata_fields": list(LIFECYCLE_METADATA_FIELDS),
            "supported_memory_types": list(SUPPORTED_MEMORY_TYPES),
            "expired_read_default": "exclude",
            "include_expired_override": True,
            "supersedes_semantics": "advisory_memory_id_reference",
            "automatic_expired_deletion": False,
        },
        memory_evidence={
            "metadata_fields": list(EVIDENCE_METADATA_FIELDS),
            "supported_sensitivities": list(SUPPORTED_SENSITIVITIES),
            "timestamps_normalized_to_utc": True,
        },
        history_read={
            "exposed": True,
            "read_only": True,
            "ownership_gate": "current_record_exact_domain",
            "credential_redaction": True,
            "max_events": MAX_HISTORY_EVENTS,
        },
        transport="stdio",
        ready=bool(local_config_ok and dependency_available and ollama_probe.get("ready")),
        ollama={
            "base_url": OLLAMA_BASE_URL,
            "llm_model": LLM_MODEL,
            "embedder_model": EMBEDDER_MODEL,
            "probe": ollama_probe,
        },
        storage={
            "root": str(MEMORY_ROOT),
            "vector_provider": VECTOR_PROVIDER,
            "vector_path": str(MEMORY_ROOT / "qdrant"),
            "history_path": str(MEMORY_ROOT / "history.db"),
        },
        limits={
            "max_text_chars": MAX_TEXT_CHARS,
            "max_query_chars": MAX_QUERY_CHARS,
            "max_metadata_chars": MAX_METADATA_CHARS,
            "max_top_k": MAX_TOP_K,
            "max_history_events": MAX_HISTORY_EVENTS,
        },
        bulk_delete_exposed=False,
    )


@mcp.tool(annotations=_READ_ONLY_TOOL)
def xinao_memory_search(
    query: str,
    user_id: str,
    project: str,
    scope: str,
    top_k: int = 10,
    min_score: float = 0.1,
    include_expired: bool = False,
) -> dict[str, Any]:
    """Search one exact domain; expired records are hidden unless explicitly requested."""
    try:
        boundary = _normalize_boundary(user_id, project, scope)
        normalized_query = _bounded_string("query", query, MAX_QUERY_CHARS)
        limit = _normalize_top_k(top_k)
        threshold = _normalize_threshold(min_score)
        show_expired = _normalize_include_expired(include_expired)
        with _memory_session() as memory:
            raw = memory.search(
                normalized_query,
                filters=_filters(boundary),
                top_k=limit,
                threshold=threshold,
            )
        items = [
            item
            for item in _results(raw)
            if _record_visible(item, boundary, include_expired=show_expired)
        ]
        return _success_payload(
            "search",
            boundary=boundary,
            count=len(items),
            top_k=limit,
            min_score=threshold,
            include_expired=show_expired,
            results=items,
        )
    except Exception as exc:
        return _error_payload("search", exc)


@mcp.tool(annotations=_READ_ONLY_TOOL)
def xinao_memory_list(
    user_id: str,
    project: str,
    scope: str,
    top_k: int = 20,
    include_expired: bool = False,
) -> dict[str, Any]:
    """List one exact domain; expired records are hidden unless explicitly requested."""
    try:
        boundary = _normalize_boundary(user_id, project, scope)
        limit = _normalize_top_k(top_k)
        show_expired = _normalize_include_expired(include_expired)
        with _memory_session() as memory:
            raw = memory.get_all(filters=_filters(boundary), top_k=limit)
        items = [
            item
            for item in _results(raw)
            if _record_visible(item, boundary, include_expired=show_expired)
        ]
        return _success_payload(
            "list",
            boundary=boundary,
            count=len(items),
            top_k=limit,
            include_expired=show_expired,
            results=items,
        )
    except Exception as exc:
        return _error_payload("list", exc)


@mcp.tool(annotations=_READ_ONLY_TOOL)
def xinao_memory_get(
    memory_id: str,
    user_id: str,
    project: str,
    scope: str,
    include_expired: bool = False,
) -> dict[str, Any]:
    """Get one domain-owned memory; expired records are hidden by default."""
    try:
        boundary = _normalize_boundary(user_id, project, scope)
        normalized_id = _identifier("memory_id", memory_id)
        show_expired = _normalize_include_expired(include_expired)
        with _memory_session() as memory:
            record = _json_safe(memory.get(normalized_id))
        if not _record_visible(record, boundary, include_expired=show_expired):
            return _success_payload(
                "get",
                boundary=boundary,
                memory_id=normalized_id,
                found=False,
                include_expired=show_expired,
                result=None,
            )
        return _success_payload(
            "get",
            boundary=boundary,
            memory_id=normalized_id,
            found=True,
            include_expired=show_expired,
            result=record,
        )
    except Exception as exc:
        return _error_payload("get", exc)


@mcp.tool(annotations=_READ_ONLY_TOOL)
def xinao_memory_history(
    memory_id: str,
    user_id: str,
    project: str,
    scope: str,
) -> dict[str, Any]:
    """Read bounded history only after the current record passes exact domain ownership."""
    try:
        boundary = _normalize_boundary(user_id, project, scope)
        normalized_id = _identifier("memory_id", memory_id)
        with _memory_session() as memory:
            current = _json_safe(memory.get(normalized_id))
            if not _record_matches(current, boundary):
                return _success_payload(
                    "history",
                    boundary=boundary,
                    memory_id=normalized_id,
                    found=False,
                    count=0,
                    truncated=False,
                    results=[],
                )
            raw = memory.history(normalized_id)
        events, truncated = _sanitize_history_events(raw, normalized_id)
        return _success_payload(
            "history",
            boundary=boundary,
            memory_id=normalized_id,
            found=True,
            count=len(events),
            truncated=truncated,
            results=events,
        )
    except Exception as exc:
        return _error_payload("history", exc)


@mcp.tool(annotations=_RECONCILING_WRITE_TOOL)
def xinao_memory_add(
    text: str,
    user_id: str,
    project: str,
    scope: str,
    provenance: str,
    metadata: dict[str, Any] | None = None,
    timestamp: str | None = None,
    memory_type: str | None = None,
    confidence: float | None = None,
    expires_at: str | None = None,
    supersedes: str | None = None,
    source_ref: str | None = None,
    valid_from: str | None = None,
    last_verified_at: str | None = None,
    sensitivity: str | None = None,
) -> dict[str, Any]:
    """Let local qwen3:8b extract and reconcile facts before storing them in one domain."""
    return _add(
        "add",
        text=text,
        user_id=user_id,
        project=project,
        scope=scope,
        provenance=provenance,
        metadata=metadata,
        timestamp=timestamp,
        memory_type=memory_type,
        confidence=confidence,
        expires_at=expires_at,
        supersedes=supersedes,
        source_ref=source_ref,
        valid_from=valid_from,
        last_verified_at=last_verified_at,
        sensitivity=sensitivity,
        infer=True,
    )


@mcp.tool(annotations=_CREATE_TOOL)
def xinao_memory_remember(
    text: str,
    user_id: str,
    project: str,
    scope: str,
    provenance: str,
    metadata: dict[str, Any] | None = None,
    timestamp: str | None = None,
    memory_type: str | None = None,
    confidence: float | None = None,
    expires_at: str | None = None,
    supersedes: str | None = None,
    source_ref: str | None = None,
    valid_from: str | None = None,
    last_verified_at: str | None = None,
    sensitivity: str | None = None,
) -> dict[str, Any]:
    """Store one exact bounded memory without LLM fact extraction (infer=False)."""
    return _add(
        "remember",
        text=text,
        user_id=user_id,
        project=project,
        scope=scope,
        provenance=provenance,
        metadata=metadata,
        timestamp=timestamp,
        memory_type=memory_type,
        confidence=confidence,
        expires_at=expires_at,
        supersedes=supersedes,
        source_ref=source_ref,
        valid_from=valid_from,
        last_verified_at=last_verified_at,
        sensitivity=sensitivity,
        infer=False,
    )


@mcp.tool(annotations=_UPDATE_TOOL)
def xinao_memory_update(
    memory_id: str,
    user_id: str,
    project: str,
    scope: str,
    provenance: str,
    text: str | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: str | None = None,
    memory_type: str | None = None,
    confidence: float | None = None,
    expires_at: str | None = None,
    supersedes: str | None = None,
    source_ref: str | None = None,
    valid_from: str | None = None,
    last_verified_at: str | None = None,
    sensitivity: str | None = None,
) -> dict[str, Any]:
    """Update one memory after an exact domain ownership check; no cross-domain move is allowed."""
    try:
        boundary = _normalize_boundary(user_id, project, scope)
        normalized_id = _identifier("memory_id", memory_id)
        managed_fields = (
            memory_type,
            confidence,
            expires_at,
            supersedes,
            source_ref,
            valid_from,
            last_verified_at,
            sensitivity,
        )
        if text is None and metadata is None and all(value is None for value in managed_fields):
            raise MemoryInputError(
                "empty_update",
                "update requires text, metadata, or a managed field in addition to provenance",
            )
        content = None if text is None else _bounded_string("text", text, MAX_TEXT_CHARS)
        stored_metadata = _domain_metadata(
            boundary,
            metadata=metadata,
            provenance=provenance,
            timestamp=timestamp,
            memory_type=memory_type,
            confidence=confidence,
            expires_at=expires_at,
            supersedes=supersedes,
            source_ref=source_ref,
            valid_from=valid_from,
            last_verified_at=last_verified_at,
            sensitivity=sensitivity,
        )
        if stored_metadata.get("supersedes") == normalized_id:
            raise MemoryInputError("invalid_supersedes", "a memory cannot supersede itself")
        with _memory_session() as memory:
            existing = _json_safe(memory.get(normalized_id))
            if not _record_matches(existing, boundary):
                return _success_payload(
                    "update",
                    boundary=boundary,
                    memory_id=normalized_id,
                    found=False,
                    updated=False,
                    result=None,
                )
            raw = memory.update(normalized_id, data=content, metadata=stored_metadata)
            updated_record = _json_safe(memory.get(normalized_id))
        return _success_payload(
            "update",
            boundary=boundary,
            memory_id=normalized_id,
            found=True,
            updated=True,
            result=raw,
            record=updated_record if _record_matches(updated_record, boundary) else None,
            record_timestamp=stored_metadata["timestamp"],
            provenance=stored_metadata["provenance"],
        )
    except Exception as exc:
        return _error_payload("update", exc)


@mcp.tool(annotations=_DELETE_TOOL)
def xinao_memory_delete(
    memory_id: str,
    user_id: str,
    project: str,
    scope: str,
    provenance: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Delete exactly one memory after an exact domain check; bulk deletion is unavailable."""
    try:
        boundary = _normalize_boundary(user_id, project, scope)
        normalized_id = _identifier("memory_id", memory_id)
        normalized_provenance = _bounded_string("provenance", provenance, MAX_PROVENANCE_CHARS)
        operation_timestamp = _normalize_timestamp(timestamp)
        with _memory_session() as memory:
            existing = _json_safe(memory.get(normalized_id))
            if not _record_matches(existing, boundary):
                return _success_payload(
                    "delete",
                    boundary=boundary,
                    memory_id=normalized_id,
                    found=False,
                    deleted=False,
                    result=None,
                    provenance=normalized_provenance,
                    operation_timestamp=operation_timestamp,
                )
            raw = memory.delete(normalized_id)
        return _success_payload(
            "delete",
            boundary=boundary,
            memory_id=normalized_id,
            found=True,
            deleted=True,
            result=raw,
            provenance=normalized_provenance,
            operation_timestamp=operation_timestamp,
        )
    except Exception as exc:
        return _error_payload("delete", exc)


def main() -> None:
    """Run only when explicitly invoked; no HTTP listener or automatic registration."""
    _preload_local_backend_dependencies()
    mcp.run("stdio")


if __name__ == "__main__":
    main()
