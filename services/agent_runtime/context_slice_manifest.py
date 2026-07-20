from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from services.agent_runtime.execution_contract import artifact_json_bytes, canonical_json_bytes

CONTEXT_SLICE_SPEC_VERSION = "xinao.context_slice_spec.v1"
CONTEXT_SLICE_MANIFEST_VERSION = "xinao.context_slice_manifest.v1"
CONTEXT_SLICE_IDENTITY_VERSION = "xinao.context_slice_identity.v1"
DEFAULT_MAX_CONTENT_BYTES = 65_536


class ContextSliceManifestError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContextSliceManifestError(f"{field} must be an object")
    return dict(value)


def _require_relative_path(value: object, field: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = Path(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ContextSliceManifestError(f"{field} must be a bounded relative path")
    return path.as_posix()


def _require_int(value: object, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise ContextSliceManifestError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContextSliceManifestError(f"{field} must be an integer") from exc
    if parsed < minimum:
        raise ContextSliceManifestError(f"{field} must be >= {minimum}")
    return parsed


def _source_path(root: Path, logical_path: str) -> Path:
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(logical_path)).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ContextSliceManifestError(f"source escapes root: {logical_path}")
    if not resolved.is_file():
        raise ContextSliceManifestError(f"source is not a file: {logical_path}")
    return resolved


def _decode_source(raw: bytes, logical_path: str) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ContextSliceManifestError(f"source is not UTF-8: {logical_path}") from exc


def _python_symbol_range(text: str, name: str, logical_path: str) -> tuple[int, int]:
    try:
        tree = ast.parse(text, filename=logical_path)
    except SyntaxError as exc:
        raise ContextSliceManifestError(f"source is not valid Python: {logical_path}") from exc
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == name
    ]
    if len(matches) != 1:
        raise ContextSliceManifestError(
            f"python_symbol must match exactly once: path={logical_path}, name={name}"
        )
    node = matches[0]
    start = min(
        [node.lineno, *(decorator.lineno for decorator in getattr(node, "decorator_list", []))]
    )
    end = int(node.end_lineno or node.lineno)
    return start, end


def _slice_bytes(raw: bytes, start: int, end: int, logical_path: str) -> bytes:
    lines = raw.splitlines(keepends=True)
    if end > len(lines):
        raise ContextSliceManifestError(
            f"line range exceeds source: path={logical_path}, end={end}, lines={len(lines)}"
        )
    return b"".join(lines[start - 1 : end])


def _selector_range(
    selector: Mapping[str, object],
    *,
    text: str,
    logical_path: str,
) -> tuple[dict[str, object], int, int]:
    kind = str(selector.get("kind") or "").strip()
    if kind == "python_symbol":
        name = str(selector.get("name") or "").strip()
        if not name:
            raise ContextSliceManifestError("python_symbol.name is required")
        start, end = _python_symbol_range(text, name, logical_path)
        identity: dict[str, object] = {"kind": kind, "name": name}
        return identity, start, end
    if kind == "line_range":
        start = _require_int(selector.get("start"), "line_range.start")
        end = _require_int(selector.get("end"), "line_range.end")
        if end < start:
            raise ContextSliceManifestError("line_range.end must be >= line_range.start")
        return {"kind": kind, "start": start, "end": end}, start, end
    raise ContextSliceManifestError(f"unsupported selector kind: {kind or 'missing'}")


def _context_identity(sources: Sequence[Mapping[str, object]]) -> dict[str, object]:
    identity_sources: list[dict[str, object]] = []
    for source in sources:
        slices: list[dict[str, object]] = []
        for raw_slice in source["slices"]:  # type: ignore[index]
            row = dict(raw_slice)
            row.pop("content", None)
            slices.append(row)
        identity_sources.append(
            {
                "path": source["path"],
                "source_sha256": source["source_sha256"],
                "source_bytes": source["source_bytes"],
                "slices": slices,
            }
        )
    return {"schema_version": CONTEXT_SLICE_IDENTITY_VERSION, "sources": identity_sources}


def validate_context_slice_manifest(raw: Mapping[str, object]) -> dict[str, Any]:
    manifest = _require_mapping(raw, "context_slice_manifest")
    if manifest.get("schema_version") != CONTEXT_SLICE_MANIFEST_VERSION:
        raise ContextSliceManifestError("unsupported context slice manifest schema_version")
    sources_raw = manifest.get("sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise ContextSliceManifestError("sources must be a non-empty array")

    normalized_sources: list[dict[str, object]] = []
    total_content_bytes = 0
    previous_path = ""
    for source_index, raw_source in enumerate(sources_raw):
        source = _require_mapping(raw_source, f"sources[{source_index}]")
        logical_path = _require_relative_path(source.get("path"), f"sources[{source_index}].path")
        if logical_path <= previous_path:
            raise ContextSliceManifestError("sources must be unique and sorted by path")
        previous_path = logical_path
        source_sha256 = str(source.get("source_sha256") or "")
        if len(source_sha256) != 64:
            raise ContextSliceManifestError("source_sha256 must be a sha256")
        source_bytes = _require_int(source.get("source_bytes"), "source_bytes", minimum=0)
        slices_raw = source.get("slices")
        if not isinstance(slices_raw, list) or not slices_raw:
            raise ContextSliceManifestError("source slices must be a non-empty array")
        slices: list[dict[str, object]] = []
        previous_end = 0
        for slice_index, raw_slice in enumerate(slices_raw):
            row = _require_mapping(raw_slice, f"slices[{slice_index}]")
            line_start = _require_int(row.get("line_start"), "line_start")
            line_end = _require_int(row.get("line_end"), "line_end")
            if line_end < line_start or line_start <= previous_end:
                raise ContextSliceManifestError("slice ranges must be sorted and non-overlapping")
            previous_end = line_end
            content = str(row.get("content") or "")
            content_bytes = content.encode("utf-8")
            if _sha256_bytes(content_bytes) != str(row.get("content_sha256") or ""):
                raise ContextSliceManifestError("slice content_sha256 mismatch")
            if len(content_bytes) != _require_int(
                row.get("content_bytes"), "content_bytes", minimum=0
            ):
                raise ContextSliceManifestError("slice content_bytes mismatch")
            total_content_bytes += len(content_bytes)
            slices.append(dict(row))
        normalized_sources.append(
            {
                "path": logical_path,
                "source_sha256": source_sha256,
                "source_bytes": source_bytes,
                "slices": slices,
            }
        )

    source_identity = [
        {"path": row["path"], "sha256": row["source_sha256"], "bytes": row["source_bytes"]}
        for row in normalized_sources
    ]
    source_manifest_sha256 = _sha256_bytes(canonical_json_bytes(source_identity))
    context_sha256 = _sha256_bytes(canonical_json_bytes(_context_identity(normalized_sources)))
    if source_manifest_sha256 != str(manifest.get("source_manifest_sha256") or ""):
        raise ContextSliceManifestError("source_manifest_sha256 mismatch")
    if context_sha256 != str(manifest.get("context_sha256") or ""):
        raise ContextSliceManifestError("context_sha256 mismatch")
    if total_content_bytes != _require_int(
        manifest.get("total_content_bytes"), "total_content_bytes", minimum=0
    ):
        raise ContextSliceManifestError("total_content_bytes mismatch")

    return {
        "schema_version": CONTEXT_SLICE_MANIFEST_VERSION,
        "authority": False,
        "completion_claim_allowed": False,
        "spec_sha256": str(manifest.get("spec_sha256") or ""),
        "source_manifest_sha256": source_manifest_sha256,
        "context_sha256": context_sha256,
        "total_content_bytes": total_content_bytes,
        "sources": normalized_sources,
        "false_green_deny": str(manifest.get("false_green_deny") or ""),
    }


def build_context_slice_manifest(
    *,
    root: Path,
    spec_path: Path,
    max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES,
) -> dict[str, Any]:
    spec_raw = Path(spec_path).read_bytes()
    try:
        spec = _require_mapping(json.loads(spec_raw.decode("utf-8")), "context_slice_spec")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextSliceManifestError("context slice spec must be UTF-8 JSON") from exc
    if spec.get("schema_version") != CONTEXT_SLICE_SPEC_VERSION:
        raise ContextSliceManifestError("unsupported context slice spec schema_version")
    entries = spec.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ContextSliceManifestError("entries must be a non-empty array")

    sources: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for entry_index, raw_entry in enumerate(entries):
        entry = _require_mapping(raw_entry, f"entries[{entry_index}]")
        logical_path = _require_relative_path(entry.get("path"), f"entries[{entry_index}].path")
        if logical_path in seen_paths:
            raise ContextSliceManifestError(f"duplicate source path: {logical_path}")
        seen_paths.add(logical_path)
        source_path = _source_path(Path(root), logical_path)
        raw_source = source_path.read_bytes()
        text = _decode_source(raw_source, logical_path)
        selectors = entry.get("selectors")
        if not isinstance(selectors, list) or not selectors:
            raise ContextSliceManifestError(f"selectors required: {logical_path}")
        slices: list[dict[str, object]] = []
        for raw_selector in selectors:
            selector = _require_mapping(raw_selector, f"selector[{logical_path}]")
            identity, start, end = _selector_range(
                selector,
                text=text,
                logical_path=logical_path,
            )
            content_bytes = _slice_bytes(raw_source, start, end, logical_path)
            try:
                content = content_bytes.decode("utf-8-sig" if start == 1 else "utf-8")
            except UnicodeDecodeError as exc:
                raise ContextSliceManifestError(
                    f"selected content is not UTF-8: {logical_path}:{start}-{end}"
                ) from exc
            slices.append(
                {
                    **identity,
                    "line_start": start,
                    "line_end": end,
                    "content_bytes": len(content.encode("utf-8")),
                    "content_sha256": _sha256_bytes(content.encode("utf-8")),
                    "content": content,
                }
            )
        slices.sort(key=lambda row: (int(row["line_start"]), int(row["line_end"])))
        for left, right in zip(slices, slices[1:], strict=False):
            if int(right["line_start"]) <= int(left["line_end"]):
                raise ContextSliceManifestError(f"overlapping selectors: {logical_path}")
        sources.append(
            {
                "path": logical_path,
                "source_sha256": _sha256_bytes(raw_source),
                "source_bytes": len(raw_source),
                "slices": slices,
            }
        )
    sources.sort(key=lambda row: str(row["path"]))
    total_content_bytes = sum(
        int(slice_row["content_bytes"])
        for source in sources
        for slice_row in source["slices"]  # type: ignore[index]
    )
    if total_content_bytes > max_content_bytes:
        raise ContextSliceManifestError(
            f"context slice exceeds max_content_bytes: {total_content_bytes}>{max_content_bytes}"
        )
    source_identity = [
        {"path": row["path"], "sha256": row["source_sha256"], "bytes": row["source_bytes"]}
        for row in sources
    ]
    manifest: dict[str, Any] = {
        "schema_version": CONTEXT_SLICE_MANIFEST_VERSION,
        "authority": False,
        "completion_claim_allowed": False,
        "spec_sha256": _sha256_bytes(spec_raw),
        "source_manifest_sha256": _sha256_bytes(canonical_json_bytes(source_identity)),
        "context_sha256": _sha256_bytes(canonical_json_bytes(_context_identity(sources))),
        "total_content_bytes": total_content_bytes,
        "sources": sources,
        "false_green_deny": (
            "A compact context slice is input/evidence only; it cannot grant authority, "
            "prove omitted context irrelevant, lower the model/reasoning/evidence bar, or "
            "replace task-specific verification."
        ),
    }
    return validate_context_slice_manifest(manifest)


def write_context_slice_manifest(path: Path, manifest: Mapping[str, object]) -> str:
    validated = validate_context_slice_manifest(manifest)
    payload = artifact_json_bytes(validated)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def load_context_slice_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextSliceManifestError(f"invalid context slice manifest: {path}") from exc
    return validate_context_slice_manifest(_require_mapping(raw, "context_slice_manifest"))
