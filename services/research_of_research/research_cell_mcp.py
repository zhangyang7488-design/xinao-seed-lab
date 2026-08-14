"""Sealed stdio MCP tools for one isolated research-cell workspace.

The server deliberately exposes only one of two tiny capability sets:

* an opaque archive query surface backed by ``archive_query.py``; or
* a mutually-exclusive ``commit_choice`` writer for preregistered paths.

It is stdlib-only so the reviewed bytes can be copied into a frozen workspace.
All paths come from the sealed local config, never from model tool arguments.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

sys.dont_write_bytecode = True

CONFIG_SCHEMA = "xinao.research-of-research.cell-mcp-config.v1"
SERVER_NAME = "research-cell"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
_ARCHIVE_TOOL_NAMES = (
    "archive_list",
    "archive_metadata",
    "archive_find",
    "archive_open",
)


class CellToolError(RuntimeError):
    """One sealed tool contract or invocation was rejected."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(code: str, message: str) -> None:
    raise CellToolError(code, message)


def _canonical_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_relative(value: object, *, field: str) -> PurePosixPath:
    if not isinstance(value, str):
        _fail("CONFIG_INVALID", f"{field} must be a relative path")
    normalized = value.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or ":" in relative.parts[0]
    ):
        _fail("CONFIG_INVALID", f"{field} must be a safe relative path")
    return relative


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _workspace_path(
    root: Path,
    relative_value: object,
    *,
    field: str,
    must_exist: bool,
) -> Path:
    relative = _safe_relative(relative_value, field=field)
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts[:-1] if not must_exist else relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            _fail("PATH_INVALID", f"{field} traverses a link")
    if must_exist:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise CellToolError("PATH_MISSING", f"{field} is missing") from exc
        if not resolved.is_file() or not _within(resolved, root):
            _fail("PATH_INVALID", f"{field} is not a contained regular file")
        return resolved
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError as exc:
        raise CellToolError("PATH_INVALID", f"{field} parent is missing") from exc
    if not parent.is_dir() or not _within(parent, root):
        _fail("PATH_INVALID", f"{field} parent escapes the workspace")
    return parent / candidate.name


def _read_config(path: Path, root: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CellToolError("CONFIG_INVALID", "sealed tool config is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema") != CONFIG_SCHEMA:
        _fail("CONFIG_INVALID", "sealed tool config schema is invalid")
    mode = value.get("mode")
    if mode == "archive-query":
        if set(value) != {"schema", "mode", "archive"}:
            _fail("CONFIG_INVALID", "archive tool config contains unknown fields")
        archive = value.get("archive")
        required = {"catalog_path", "config_path", "ledger_path"}
        if not isinstance(archive, dict) or set(archive) != required:
            _fail("CONFIG_INVALID", "archive tool paths are incomplete")
        for field in required:
            _safe_relative(archive[field], field=field)
    elif mode == "commit-choice":
        if not set(value).issubset({"schema", "mode", "choices", "max_content_bytes"}):
            _fail("CONFIG_INVALID", "commit tool config contains unknown fields")
        choices = value.get("choices")
        if not isinstance(choices, dict) or len(choices) < 2:
            _fail("CONFIG_INVALID", "commit tool requires at least two choices")
        if any(
            not isinstance(choice, str)
            or not choice
            or not choice.replace("-", "_").isidentifier()
            for choice in choices
        ):
            _fail("CONFIG_INVALID", "commit choice ids are invalid")
        targets = []
        for choice, relative in choices.items():
            target = _workspace_path(
                root,
                relative,
                field=f"choices.{choice}",
                must_exist=False,
            )
            targets.append(target)
        if len(set(targets)) != len(targets):
            _fail("CONFIG_INVALID", "commit choices must bind distinct paths")
        limit = value.get("max_content_bytes", 65536)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1_048_576:
            _fail("CONFIG_INVALID", "max_content_bytes is invalid")
    else:
        _fail("CONFIG_INVALID", "sealed tool mode is invalid")
    return value


def _load_archive_module(root: Path) -> ModuleType:
    path = _workspace_path(root, "archive_query.py", field="archive_query.py", must_exist=True)
    spec = importlib.util.spec_from_file_location("research_cell_archive_query", path)
    if spec is None or spec.loader is None:
        _fail("ARCHIVE_TOOL_INVALID", "archive query implementation could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive_paths(config: Mapping[str, Any], root: Path) -> dict[str, Path]:
    archive = config["archive"]
    assert isinstance(archive, Mapping)
    return {
        "catalog_path": _workspace_path(
            root, archive["catalog_path"], field="catalog_path", must_exist=True
        ),
        "config_path": _workspace_path(
            root, archive["config_path"], field="config_path", must_exist=True
        ),
        "ledger_path": _workspace_path(
            root, archive["ledger_path"], field="ledger_path", must_exist=True
        ),
    }


def _string_array(value: object, *, field: str, allow_empty: bool) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        _fail("TOOL_ARGUMENT_INVALID", f"{field} must be a unique string array")
    return list(value)


def _optional_string(arguments: Mapping[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        _fail("TOOL_ARGUMENT_INVALID", f"{key} must be a non-empty string")
    return value


def _call_archive(
    name: str,
    arguments: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    root: Path,
) -> dict[str, Any]:
    module = _load_archive_module(root)
    common = _archive_paths(config, root)
    try:
        if name == "archive_list":
            if not set(arguments).issubset({"kind"}):
                _fail("TOOL_ARGUMENT_INVALID", "archive_list received unknown arguments")
            return module.list_records(kind=_optional_string(arguments, "kind"), **common)
        if name == "archive_metadata":
            if not set(arguments).issubset({"record_ids"}):
                _fail("TOOL_ARGUMENT_INVALID", "archive_metadata received unknown arguments")
            record_ids = _string_array(
                arguments.get("record_ids", []), field="record_ids", allow_empty=True
            )
            return module.record_metadata(record_ids=record_ids, **common)
        if name == "archive_find":
            if not set(arguments).issubset({"fixed_string", "kind"}):
                _fail("TOOL_ARGUMENT_INVALID", "archive_find received unknown arguments")
            fixed_string = arguments.get("fixed_string")
            if not isinstance(fixed_string, str) or not fixed_string:
                _fail("TOOL_ARGUMENT_INVALID", "fixed_string must be non-empty")
            return module.find_fixed_string(
                fixed_string=fixed_string,
                kind=_optional_string(arguments, "kind"),
                **common,
            )
        if name == "archive_open":
            if set(arguments) != {"record_ids"}:
                _fail("TOOL_ARGUMENT_INVALID", "archive_open requires only record_ids")
            record_ids = _string_array(
                arguments.get("record_ids"), field="record_ids", allow_empty=False
            )
            return module.open_records(record_ids=record_ids, **common)
    except CellToolError:
        raise
    except Exception as exc:
        reason_code = getattr(exc, "reason_code", "ARCHIVE_QUERY_REJECTED")
        raise CellToolError(str(reason_code), "archive query rejected") from exc
    _fail("TOOL_NOT_FOUND", "archive tool is not enabled")


def _call_commit(
    arguments: Mapping[str, Any], *, config: Mapping[str, Any], root: Path
) -> dict[str, Any]:
    if set(arguments) != {"choice", "content"}:
        _fail("TOOL_ARGUMENT_INVALID", "commit_choice requires choice and content")
    choice = arguments.get("choice")
    content = arguments.get("content")
    choices = config["choices"]
    assert isinstance(choices, Mapping)
    if not isinstance(choice, str) or choice not in choices:
        _fail("CHOICE_INVALID", "choice is not preregistered")
    if not isinstance(content, str) or not content.strip():
        _fail("CONTENT_INVALID", "content must be non-empty UTF-8 text")
    raw = content.encode("utf-8")
    limit = int(config.get("max_content_bytes", 65536))
    if len(raw) > limit:
        _fail("CONTENT_TOO_LARGE", "content exceeds the frozen byte ceiling")
    targets = {
        candidate: _workspace_path(
            root,
            relative,
            field=f"choices.{candidate}",
            must_exist=False,
        )
        for candidate, relative in choices.items()
    }
    if any(target.exists() for target in targets.values()):
        _fail("CHOICE_ALREADY_COMMITTED", "one preregistered choice already exists")
    target = targets[choice]
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CellToolError("CHOICE_ALREADY_COMMITTED", "choice already exists") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if any(candidate != choice and path.exists() for candidate, path in targets.items()):
        target.unlink(missing_ok=True)
        _fail("CHOICE_CONFLICT", "mutually exclusive choice paths raced")
    return {
        "schema": "xinao.research-of-research.commit-choice-result.v1",
        "authority": False,
        "choice": choice,
        "relative_path": str(choices[choice]).replace("\\", "/"),
        "bytes": len(raw),
        "sha256": _sha(raw),
    }


def _tool_definitions(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    if config["mode"] == "archive-query":
        return [
            {
                "name": "archive_list",
                "description": "List opaque archive records without opening their content.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"kind": {"type": "string", "minLength": 1}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "archive_metadata",
                "description": "Read public metadata for selected opaque record ids.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "record_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "uniqueItems": True,
                        }
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "archive_find",
                "description": "Exact fixed-string search over the sealed opaque archive.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "fixed_string": {"type": "string", "minLength": 1},
                        "kind": {"type": "string", "minLength": 1},
                    },
                    "required": ["fixed_string"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "archive_open",
                "description": "Open content for opaque ids under the frozen distinct-id ceiling.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "record_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                            "uniqueItems": True,
                        }
                    },
                    "required": ["record_ids"],
                    "additionalProperties": False,
                },
            },
        ]
    choices = config["choices"]
    assert isinstance(choices, Mapping)
    return [
        {
            "name": "commit_choice",
            "description": "Commit exactly one preregistered mutually-exclusive output choice.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "enum": sorted(choices)},
                    "content": {"type": "string", "minLength": 1},
                },
                "required": ["choice", "content"],
                "additionalProperties": False,
            },
        }
    ]


def _tool_result(value: Mapping[str, Any], *, is_error: bool) -> dict[str, Any]:
    text = _canonical_text(value)
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }
    if not is_error:
        result["structuredContent"] = dict(value)
    return result


def _handle_request(
    request: Mapping[str, Any], *, config: Mapping[str, Any], root: Path
) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if "id" not in request:
        return None
    if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32600, "message": "Invalid Request"},
        }
    params = request.get("params", {})
    params = params if isinstance(params, Mapping) else {}
    if method == "initialize":
        requested_version = params.get("protocolVersion")
        protocol_version = (
            requested_version if isinstance(requested_version, str) else DEFAULT_PROTOCOL_VERSION
        )
        result = {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _tool_definitions(config)}
    elif method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, Mapping):
            result = _tool_result(
                {"error": {"code": "TOOL_ARGUMENT_INVALID", "message": "invalid call"}},
                is_error=True,
            )
        else:
            try:
                if config["mode"] == "archive-query":
                    if name not in _ARCHIVE_TOOL_NAMES:
                        _fail("TOOL_NOT_FOUND", "tool is not enabled")
                    value = _call_archive(name, arguments, config=config, root=root)
                elif name == "commit_choice":
                    value = _call_commit(arguments, config=config, root=root)
                else:
                    _fail("TOOL_NOT_FOUND", "tool is not enabled")
                result = _tool_result(value, is_error=False)
            except CellToolError as exc:
                result = _tool_result(
                    {"error": {"code": exc.reason_code, "message": str(exc)}},
                    is_error=True,
                )
            except Exception:
                result = _tool_result(
                    {
                        "error": {
                            "code": "CELL_TOOL_INTERNAL_ERROR",
                            "message": "sealed tool failed internally",
                        }
                    },
                    is_error=True,
                )
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(config_path: Path) -> int:
    root = Path.cwd().resolve(strict=True)
    config_file = _workspace_path(root, str(config_path), field="config", must_exist=True)
    config = _read_config(config_file, root)
    for raw_line in sys.stdin.buffer:
        if not raw_line.strip():
            continue
        try:
            request = json.loads(raw_line.decode("utf-8"))
            if not isinstance(request, Mapping):
                raise ValueError("request is not an object")
            response = _handle_request(request, config=config, root=root)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        if response is not None:
            sys.stdout.buffer.write((_canonical_text(response) + "\n").encode("utf-8"))
            sys.stdout.buffer.flush()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="research-cell-tools.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return serve(Path(args.config))
    except CellToolError as exc:
        sys.stderr.write(_canonical_text({"error": {"code": exc.reason_code}}) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
