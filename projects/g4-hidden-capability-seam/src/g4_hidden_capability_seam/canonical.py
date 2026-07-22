"""Identity hashing: canonical-json-v1 + sha256; raw-bytes-sha256-v1 for files."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    """canonical-json-v1: UTF-8, sort_keys, compact separators, ensure_ascii=False."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(obj: Any) -> str:
    return sha256_hex(canonical_json_bytes(obj))


def raw_bytes_sha256_file(path: str | Path) -> tuple[str, int]:
    p = Path(path)
    data = p.read_bytes()
    return sha256_hex(data), len(data)


def write_json(path: str | Path, obj: Any) -> tuple[str, int]:
    """Publish a complete JSON document atomically for concurrent readers.

    The authority store may be SQLite, but its JSON projections are still
    observable objects.  A same-directory temporary plus ``os.replace`` keeps
    readers on either the previous or next complete document.  Windows can
    transiently deny replacement while a reader has the destination open, so
    replacement is retried within a bounded window.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    raw = data.encode("utf-8")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=p.parent,
            prefix=f".{p.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(100):
            try:
                os.replace(temp_path, p)
                temp_path = None
                break
            except PermissionError:
                if attempt == 99:
                    raise
                time.sleep(min(0.002 * (attempt + 1), 0.05))
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return sha256_hex(raw), len(raw)


def read_json(path: str | Path) -> Any:
    p = Path(path)
    last_error: Exception | None = None
    for attempt in range(100):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (FileNotFoundError, PermissionError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 99:
                raise
            time.sleep(min(0.002 * (attempt + 1), 0.05))
    raise RuntimeError(f"unreachable JSON read retry exit: {last_error}")


def identity_from_fields(kind: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Build a versioned semantic identity envelope."""
    payload = {"kind": kind, "fields": fields}
    digest = canonical_json_sha256(payload)
    return {
        "hash_profile": "canonical-json-v1+sha256",
        "kind": kind,
        "identity_sha256": digest,
        "fields": fields,
    }
