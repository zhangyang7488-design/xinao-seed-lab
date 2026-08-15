"""Freeze, run, and verify bounded research-of-research contacts.

This module implements effect and evidence physics, not an ontology of research.
The v2 format is one optional compiled-contact dialect: it may carry one or more
isolated consumers and optional hypotheses or factors, but none of those objects
is required to describe cognition itself.  The runner retains raw trajectories;
it never qualifies evidence, adopts a representation, or decides what the hidden
research operator is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.research_of_research.continuation import request_continuation_reconcile
from services.xinao_perpetual_world_compute.controller import (
    WORLD_TURN_QUOTA_LEASE_SCHEMA,
    ProcessLiveness,
    _release_byte_lock,
    _try_acquire_byte_lock,
    atomic_write_bytes,
    atomic_write_json,
    build_trajectory_index,
    create_world_isolated_launcher,
    is_process_alive,
    now_iso,
    process_liveness,
    read_json_object,
    sha256_file,
)

LEGACY_CELL_SPEC_SCHEMA = "xinao.research-of-research.cell-spec.v1"
CELL_SPEC_SCHEMA = "xinao.research-of-research.cell-spec.v2"
CELL_SCHEMA = "xinao.research-of-research.cell.v2"
RUN_SCHEMA = "xinao.research-of-research.run.v2"
VERIFY_SCHEMA = "xinao.research-of-research.verification.v1"
CONTRAST_SCHEMA = "xinao.research-of-research.mechanical-contrast.v2"
RAW_ARCHIVE_SCHEMA = "xinao.research-of-research.raw-archive-manifest.v1"
RECONSTRUCTION_SCHEMA = "xinao.research-of-research.episode-reconstruction.v1"
CONTRAST_VIEW_SCHEMA = "xinao.research-of-research.contrast-view.v1"
REPLAY_TWIN_SCHEMA = "xinao.research-of-research.replay-twin.v1"
RAW_TRAJECTORY_LEDGER_SCHEMA = "xinao.research-of-research.raw-trajectory-ledger.v1"

DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\research_of_research")
DEFAULT_QUOTA_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_world_turn_quota")
DEFAULT_LAUNCHER = Path(r"E:\CODEX_CLEANROOM\Open-Codex-Cleanroom.ps1")
DEFAULT_POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
DEFAULT_WORKSPACE_ROOT = Path(r"E:\CODEX_CLEANROOM\research-lineages\research-of-research")
TEMPORARY_ACCOUNT_RESEARCH_CAP = 2

_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
_MCP_SERVER_ID = re.compile(r"^[a-z][a-z0-9_-]{2,31}$")
_LOCAL_MCP_TOOLS = {
    "archive_list",
    "archive_metadata",
    "archive_find",
    "archive_open",
    "commit_choice",
}
_FIDELITIES = {
    "EXACT_REPLAYABLE",
    "HIGH_FIDELITY",
    "PARTIAL",
    "OBSERVATIONAL_ONLY",
    "UNRECOVERABLE",
}
_SOURCE_VISIBILITIES = {
    "model_visible",
    "evidence_only",
    "withheld",
    "future_settlement",
}
_PROTECTED_ROOTS = (
    Path(r"E:\XINAO_RESEARCH_WORKSPACES\S"),
    Path(r"E:\CODEX_CLEANROOM"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_world_compute"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_a"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_c"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\account_research_caps"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_world_turn_quota"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_logical_root"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\xinao\live-reality"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\xinao\world-compute"),
    Path(r"C:\Users\xx363\Desktop\历史备用 不动"),
)


class ResearchCellError(RuntimeError):
    """A cell identity, isolation, quota, or evidence invariant failed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(code: str, message: str) -> None:
    raise ResearchCellError(code, message)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _nested(left: Path, right: Path) -> bool:
    left = _resolve(left)
    right = _resolve(right)
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def validate_runtime_root(
    root: Path, *, protected_roots: Sequence[Path] = _PROTECTED_ROOTS
) -> Path:
    resolved = _resolve(root)
    for protected in protected_roots:
        if _nested(resolved, protected):
            _fail("RUN_ROOT_OVERLAPS_PRODUCTION", f"run root overlaps protected root: {protected}")
    state_root = _resolve(Path(r"D:\XINAO_RESEARCH_RUNTIME\state"))
    try:
        state_relative = resolved.relative_to(state_root)
    except ValueError:
        state_relative = None
    if state_relative and state_relative.parts[0].casefold().startswith("xinao_perpetual_"):
        _fail(
            "RUN_ROOT_OVERLAPS_PRODUCTION",
            f"run root overlaps a perpetual production runtime: {resolved}",
        )
    return resolved


def _validate_workspace_root(root: Path) -> Path:
    resolved = _resolve(root)
    allowed = _resolve(Path(r"E:\CODEX_CLEANROOM\research-lineages"))
    try:
        relative = resolved.relative_to(allowed)
    except ValueError as exc:
        raise ResearchCellError(
            "WORKSPACE_ROOT_OUTSIDE_CLEANROOM",
            f"workspace root is outside the clean-room launcher boundary: {resolved}",
        ) from exc
    if not relative.parts or relative.parts[0].casefold() != "research-of-research":
        _fail(
            "WORKSPACE_ROOT_OVERLAPS_PRODUCTION",
            "research cells require the dedicated research-of-research clean-room subtree",
        )
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchCellError("JSON_INVALID", f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        _fail("JSON_INVALID", f"JSON root must be an object: {path}")
    return value


def _file_identity(path: Path) -> dict[str, Any]:
    path = _resolve(path)
    if path.is_symlink() or not path.is_file():
        _fail("SOURCE_INVALID", f"source is not a regular non-link file: {path}")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        _fail("SOURCE_CHANGED", f"source changed while being read: {path}")
    return {
        "path": str(path),
        "bytes": len(raw),
        "sha256": _sha(raw),
        "mtime_ns": before.st_mtime_ns,
    }


def _material_bytes(descriptor: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    kind = descriptor.get("kind")
    if kind == "literal":
        text = descriptor.get("text")
        if not isinstance(text, str) or not text:
            _fail("MATERIAL_INVALID", "literal material must contain non-empty text")
        raw = text.encode("utf-8")
        return raw, {"kind": "literal", "bytes": len(raw), "sha256": _sha(raw)}
    if kind not in {"file", "line_slice"}:
        _fail("MATERIAL_INVALID", f"unsupported material kind: {kind}")
    path = _resolve(str(descriptor.get("path", "")))
    identity = _file_identity(path)
    source_raw = path.read_bytes()
    confirmed = _file_identity(path)
    if confirmed["sha256"] != identity["sha256"] or _sha(source_raw) != identity["sha256"]:
        _fail("SOURCE_CHANGED", f"source changed between identity and archive read: {path}")
    if kind == "file":
        return source_raw, {"kind": "file", "source": identity, **identity}
    try:
        text = source_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchCellError(
            "MATERIAL_NOT_UTF8", f"line slice source is not UTF-8: {path}"
        ) from exc
    start = descriptor.get("start_line")
    end = descriptor.get("end_line")
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        _fail("MATERIAL_INVALID", "line slice requires a positive inclusive line range")
    lines = text.splitlines(keepends=True)
    if end > len(lines):
        _fail("MATERIAL_RANGE_INVALID", f"line range {start}-{end} exceeds {len(lines)}")
    raw = "".join(lines[start - 1 : end]).encode("utf-8")
    return raw, {
        "kind": "line_slice",
        "source": identity,
        "start_line": start,
        "end_line": end,
        "bytes": len(raw),
        "sha256": _sha(raw),
    }


def _safe_relative(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        _fail("WORKSPACE_FILE_INVALID", f"workspace path escapes its seed: {value}")
    return candidate


def _tree_manifest(root: Path) -> dict[str, Any]:
    root = _resolve(root)
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        _fail("TREE_INVALID", f"tree root does not exist: {root}")
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            _fail("TREE_INVALID", f"tree contains a link: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            _fail("TREE_INVALID", f"tree contains a non-file: {path}")
        raw = path.read_bytes()
        rows.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "bytes": len(raw),
                "sha256": _sha(raw),
            }
        )
    digest = _sha(_canonical_bytes(rows))
    return {"root": str(root), "files": rows, "tree_sha256": digest}


def _tree_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, list[str]]:
    before_rows = {row["relative_path"]: row["sha256"] for row in before.get("files", [])}
    after_rows = {row["relative_path"]: row["sha256"] for row in after.get("files", [])}
    return {
        "added": sorted(after_rows.keys() - before_rows.keys()),
        "removed": sorted(before_rows.keys() - after_rows.keys()),
        "modified": sorted(
            path
            for path in before_rows.keys() & after_rows.keys()
            if before_rows[path] != after_rows[path]
        ),
    }


def _classify_action_cone(
    delta: Mapping[str, Sequence[str]], observables: Mapping[str, Any]
) -> dict[str, Any]:
    changed = (
        set(delta.get("added", [])) | set(delta.get("removed", [])) | set(delta.get("modified", []))
    )
    old_declared = set(observables.get("old_action_cone_paths", []))
    new_declared = set(observables.get("new_action_cone_paths", []))
    old_hits = sorted(changed & old_declared)
    new_hits = sorted(changed & new_declared)
    if new_hits and not old_hits:
        classification = "SWITCHED"
    elif old_hits and not new_hits:
        classification = "PERSISTED"
    elif old_hits and new_hits:
        classification = "MIXED"
    else:
        classification = "NONE"
    return {
        "classification": classification,
        "old_action_cone_hits": old_hits,
        "new_action_cone_hits": new_hits,
        "diagnostic_only": True,
    }


def _write_once(path: Path, raw: bytes, *, conflict_code: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / ".write-once.lock"
    deadline = time.monotonic() + 30.0
    guard = None
    while guard is None and time.monotonic() < deadline:
        guard = _try_acquire_byte_lock(lock_path)
        if guard is None:
            time.sleep(0.01)
    if guard is None:
        _fail("WRITE_ONCE_LOCK_TIMEOUT", f"could not lock immutable store: {path.parent}")
    try:
        if path.exists():
            if path.is_file() and path.read_bytes() == raw:
                return "ACCEPTED_IDENTICAL_REUSE"
            _fail(conflict_code, f"immutable bytes already exist and differ: {path}")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.is_file() and path.read_bytes() == raw:
                return "ACCEPTED_IDENTICAL_REUSE"
            _fail(conflict_code, f"immutable bytes raced with different content: {path}")
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return "CREATED"
    finally:
        _release_byte_lock(guard)


def _snapshot_tree(source: Path, destination: Path) -> dict[str, Any]:
    """Copy one completed workspace into its immutable run evidence directory."""

    expected = _tree_manifest(source)
    if destination.exists():
        _fail("WORKSPACE_SNAPSHOT_CONFLICT", f"snapshot target already exists: {destination}")
    shutil.copytree(source, destination)
    observed = _tree_manifest(destination)
    if observed["tree_sha256"] != expected["tree_sha256"]:
        _fail("WORKSPACE_SNAPSHOT_DRIFT", f"workspace changed while snapshotting: {source}")
    return observed


def _validate_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    schema = spec.get("schema")
    if schema not in {LEGACY_CELL_SPEC_SCHEMA, CELL_SPEC_SCHEMA}:
        _fail("SPEC_SCHEMA_INVALID", "unsupported research cell spec schema")
    is_v2 = schema == CELL_SPEC_SCHEMA
    cell_id = spec.get("cell_id")
    if not isinstance(cell_id, str) or _SLUG.fullmatch(cell_id) is None:
        _fail("CELL_ID_INVALID", "cell_id must be a stable lowercase slug")
    episode = spec.get("episode")
    intervention = spec.get("intervention")
    harness = spec.get("harness")
    hypotheses = spec.get("hypotheses")
    if not isinstance(episode, dict) or not isinstance(intervention, dict):
        _fail("SPEC_INVALID", "episode and intervention must be objects")
    if not isinstance(harness, dict):
        _fail("SPEC_INVALID", "harness must be an object")
    fidelity = episode.get("replay_fidelity")
    if fidelity not in _FIDELITIES:
        _fail("FIDELITY_INVALID", f"unsupported replay fidelity: {fidelity}")
    gaps = episode.get("known_gaps")
    if not isinstance(gaps, list) or any(not isinstance(item, str) for item in gaps):
        _fail("SPEC_INVALID", "known_gaps must be a list of strings")
    if fidelity in {"EXACT_REPLAYABLE", "HIGH_FIDELITY"} and gaps:
        _fail("FIDELITY_OVERCLAIM", "high replay fidelity cannot retain known gaps")
    sources = episode.get("sources")
    if not isinstance(sources, list) or not sources:
        _fail("SOURCE_INVALID", "episode sources must be a non-empty list")
    source_ids: list[str] = []
    source_by_id: dict[str, Mapping[str, Any]] = {}
    chronology_indexes: list[int] = []
    cutoff_index = episode.get("cutoff_index")
    if is_v2 and (not isinstance(cutoff_index, int) or cutoff_index < 0):
        _fail("CUTOFF_INVALID", "v2 cells require a non-negative cutoff_index")
    for row in sources:
        if not isinstance(row, dict):
            _fail("SOURCE_INVALID", "each episode source must be an object")
        source_id = row.get("id")
        if not isinstance(source_id, str) or _SLUG.fullmatch(source_id) is None:
            _fail("SOURCE_INVALID", "each source requires a stable lowercase slug")
        if source_id in source_by_id:
            _fail("SOURCE_INVALID", "source ids must be unique")
        source_ids.append(source_id)
        source_by_id[source_id] = row
        if is_v2:
            chronology_index = row.get("chronology_index")
            if not isinstance(chronology_index, int) or chronology_index < 0:
                _fail("SOURCE_CHRONOLOGY_INVALID", f"source lacks chronology_index: {source_id}")
            chronology_indexes.append(chronology_index)
            visibility = row.get("visibility")
            if visibility not in _SOURCE_VISIBILITIES:
                _fail("SOURCE_VISIBILITY_INVALID", f"invalid visibility for {source_id}")
            if visibility == "model_visible" and chronology_index > cutoff_index:
                _fail("FUTURE_SOURCE_VISIBLE", f"source is after the declared cutoff: {source_id}")
    if is_v2 and len(set(chronology_indexes)) != len(chronology_indexes):
        _fail("SOURCE_CHRONOLOGY_INVALID", "chronology indexes must be unique")
    if is_v2:
        for source_id, row in source_by_id.items():
            derived_from = row.get("derived_from", [])
            if not isinstance(derived_from, list) or any(
                not isinstance(item, str) or item not in source_by_id for item in derived_from
            ):
                _fail("SOURCE_PROVENANCE_INVALID", f"invalid derived_from for {source_id}")
            if row.get("provenance_kind") == "derived" and not derived_from:
                _fail("SOURCE_PROVENANCE_INVALID", f"derived source lacks provenance: {source_id}")
    variants = intervention.get("variants")
    minimum_variants = 1 if is_v2 else 2
    if not isinstance(variants, list) or len(variants) < minimum_variants:
        _fail(
            "SPEC_INVALID",
            f"at least {minimum_variants} execution variant(s) are required",
        )
    variant_ids = [row.get("id") if isinstance(row, dict) else None for row in variants]
    if any(not isinstance(item, str) or _SLUG.fullmatch(item) is None for item in variant_ids):
        _fail("VARIANT_ID_INVALID", "each variant must have a stable lowercase slug")
    if len(set(variant_ids)) != len(variant_ids):
        _fail("VARIANT_ID_INVALID", "variant ids must be unique")
    held = intervention.get("held_constants", [])
    if not isinstance(held, list) or any(not isinstance(item, str) for item in held):
        _fail("INTERVENTION_INVALID", "held_constants must be a list of strings")
    if not is_v2 and len(held) < 3:
        _fail("INTERVENTION_INVALID", "legacy cells require at least three held constants")
    if is_v2:
        variables = intervention.get("intervention_variables", [])
        confounders = intervention.get("known_confounders", [])
        if not isinstance(variables, list) or any(
            not isinstance(item, str) or not item for item in variables
        ):
            _fail("INTERVENTION_INVALID", "intervention_variables must be a list of strings")
        if len(set(variables)) != len(variables):
            _fail("INTERVENTION_INVALID", "intervention_variables must be unique")
        if not isinstance(confounders, list) or any(
            not isinstance(item, str) for item in confounders
        ):
            _fail("INTERVENTION_INVALID", "known_confounders must be a list of strings")
        common_view = intervention.get("common_view")
        if not isinstance(common_view, list) or any(
            not isinstance(item, str) or item not in source_by_id for item in common_view
        ):
            _fail("CONTRAST_VIEW_INVALID", "common_view must reference archived sources")
        _material_bytes(intervention.get("terminal_contract", {}))
        for row in variants:
            view = row.get("view")
            if not isinstance(view, list) or any(
                not isinstance(item, str) or item not in source_by_id for item in view
            ):
                _fail("CONTRAST_VIEW_INVALID", f"variant view is invalid: {row.get('id')}")
            factors = row.get("factor_assignments", {})
            if not isinstance(factors, dict):
                _fail("INTERVENTION_INVALID", f"variant factors must be an object: {row.get('id')}")
            if variables and set(factors) != set(variables):
                _fail(
                    "INTERVENTION_INVALID",
                    f"variant factor assignment is incomplete: {row.get('id')}",
                )
            for source_id in [*common_view, *view]:
                source = source_by_id[source_id]
                if source.get("visibility") != "model_visible":
                    _fail("CONTRAST_VIEW_LEAK", f"view references non-visible source: {source_id}")
            overlay = row.get("workspace_files", {})
            source_overlay = row.get("workspace_source_files", {})
            removes = row.get("workspace_remove", [])
            if not isinstance(overlay, dict) or any(
                not isinstance(value, str) for value in overlay.values()
            ):
                _fail("HARNESS_INVALID", "variant workspace_files must contain text")
            if not isinstance(source_overlay, dict) or any(
                not isinstance(value, str) or value not in source_by_id
                for value in source_overlay.values()
            ):
                _fail("HARNESS_INVALID", "variant workspace_source_files must reference sources")
            if not isinstance(removes, list) or any(
                not isinstance(value, str) for value in removes
            ):
                _fail("HARNESS_INVALID", "workspace_remove must be a list of paths")
            for relative in [*overlay, *source_overlay, *removes]:
                _safe_relative(str(relative))
            for source_id in source_overlay.values():
                source = source_by_id[source_id]
                if source.get("visibility") != "model_visible":
                    _fail(
                        "CONTRAST_VIEW_LEAK",
                        f"workspace references non-visible source: {source_id}",
                    )
    else:
        only_changed = intervention.get("only_changed")
        if not isinstance(only_changed, str) or not only_changed:
            _fail("INTERVENTION_INVALID", "legacy cells require one changed variable")
    if hypotheses is None and is_v2:
        hypotheses = []
    if not isinstance(hypotheses, list) or (not is_v2 and len(hypotheses) < 2):
        _fail(
            "HYPOTHESES_INVALID",
            "legacy cells require at least two competing predictions",
        )
    prediction_ids = []
    for row in hypotheses:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            _fail("HYPOTHESES_INVALID", "each hypothesis requires an id")
        if not isinstance(row.get("prediction"), str) or not row["prediction"].strip():
            _fail("HYPOTHESES_INVALID", "each hypothesis requires a prediction")
        prediction_ids.append(row["id"])
    if len(set(prediction_ids)) != len(prediction_ids):
        _fail("HYPOTHESES_INVALID", "hypothesis ids must be unique")
    forbidden = spec.get("forbidden_future_sentinels", [])
    if not isinstance(forbidden, list) or any(
        not isinstance(item, str) or not item for item in forbidden
    ):
        _fail("SPEC_INVALID", "future sentinels must be non-empty strings")
    workspace_files = harness.get("workspace_files")
    if not isinstance(workspace_files, dict) or not workspace_files:
        _fail("HARNESS_INVALID", "harness workspace_files must be a non-empty object")
    for relative, content in workspace_files.items():
        _safe_relative(str(relative))
        if not isinstance(content, str):
            _fail("HARNESS_INVALID", "workspace file content must be text")
    local_mcp = harness.get("local_mcp")
    if local_mcp is not None:
        if not is_v2 or not isinstance(local_mcp, dict):
            _fail("LOCAL_MCP_INVALID", "local_mcp is supported only by v2 cells")
        required_mcp_keys = {"server_id", "script_path", "config_path", "enabled_tools"}
        optional_mcp_keys = {"startup_timeout_sec", "tool_timeout_sec"}
        if not required_mcp_keys.issubset(local_mcp) or not set(local_mcp).issubset(
            required_mcp_keys | optional_mcp_keys
        ):
            _fail("LOCAL_MCP_INVALID", "local_mcp fields are incomplete or unknown")
        server_id = local_mcp.get("server_id")
        if not isinstance(server_id, str) or _MCP_SERVER_ID.fullmatch(server_id) is None:
            _fail("LOCAL_MCP_INVALID", "local MCP server_id is invalid")
        script_relative = str(local_mcp.get("script_path"))
        config_relative = str(local_mcp.get("config_path"))
        _safe_relative(script_relative)
        _safe_relative(config_relative)
        if script_relative == config_relative:
            _fail("LOCAL_MCP_INVALID", "local MCP script and config must differ")
        if script_relative not in workspace_files or config_relative not in workspace_files:
            _fail("LOCAL_MCP_INVALID", "local MCP script and config must be common frozen files")
        enabled_tools = local_mcp.get("enabled_tools")
        if (
            not isinstance(enabled_tools, list)
            or not enabled_tools
            or any(
                not isinstance(item, str) or item not in _LOCAL_MCP_TOOLS for item in enabled_tools
            )
            or len(set(enabled_tools)) != len(enabled_tools)
        ):
            _fail("LOCAL_MCP_INVALID", "local MCP enabled_tools are invalid")
        for timeout_key, default in (("startup_timeout_sec", 20.0), ("tool_timeout_sec", 120.0)):
            timeout = local_mcp.get(timeout_key, default)
            if (
                not isinstance(timeout, (int, float))
                or isinstance(timeout, bool)
                or timeout <= 0
                or timeout > 1800
            ):
                _fail("LOCAL_MCP_INVALID", f"{timeout_key} is invalid")
        protected_mcp_paths = {script_relative, config_relative}
        for row in variants:
            touched = (
                set(row.get("workspace_files", {}))
                | set(row.get("workspace_source_files", {}))
                | set(row.get("workspace_remove", []))
            )
            if touched & protected_mcp_paths:
                _fail("LOCAL_MCP_INVALID", "variants cannot alter the frozen local MCP carrier")
    workspace_source_files = harness.get("workspace_source_files", {})
    if not isinstance(workspace_source_files, dict) or any(
        not isinstance(source_id, str) or source_id not in source_by_id
        for source_id in workspace_source_files.values()
    ):
        _fail("HARNESS_INVALID", "workspace_source_files must reference archived sources")
    for relative in workspace_source_files:
        _safe_relative(str(relative))
    if is_v2:
        for source_id in workspace_source_files.values():
            if source_by_id[source_id].get("visibility") != "model_visible":
                _fail("CONTRAST_VIEW_LEAK", f"workspace references non-visible source: {source_id}")
    account_slot = harness.get("account_slot")
    if account_slot not in {"A", "C"}:
        _fail("HARNESS_INVALID", "account_slot must be A or C")
    declared_cap = harness.get(
        "max_account_research_turns",
        2 if is_v2 else harness.get("world_turn_concurrency_limit", 4),
    )
    if not isinstance(declared_cap, int) or declared_cap < 1 or declared_cap > 4:
        _fail("HARNESS_INVALID", "max_account_research_turns must be between 1 and 4")
    if is_v2 and declared_cap != 2:
        _fail(
            "ACCOUNT_RESEARCH_CAP_INVALID",
            "current v2 contacts require the temporary per-account Sol research cap of 2",
        )
    physical_slots = harness.get(
        "physical_world_turn_slots",
        4 if is_v2 else harness.get("world_turn_concurrency_limit", 4),
    )
    if (
        not isinstance(physical_slots, int)
        or physical_slots < 1
        or physical_slots > 16
        or declared_cap > physical_slots
    ):
        _fail("HARNESS_INVALID", "physical_world_turn_slots is incompatible with the cap")
    if is_v2 and harness.get("root_main_compute_allowed", False) is not False:
        _fail("ROOT_MAIN_COMPUTE_FORBIDDEN", "v2 replay cells keep root-main parked")
    if is_v2 and not isinstance(harness.get("account_research_cap_policy"), str):
        _fail("CAP_POLICY_REQUIRED", "v2 cells bind the live account research cap policy")
    if harness.get("web_search", "disabled") not in {"disabled", "cached", "live"}:
        _fail("HARNESS_INVALID", "web_search must be disabled, cached, or live")
    guards = spec.get("production_guards", [])
    if not isinstance(guards, list) or any(
        not isinstance(item, str) or not item for item in guards
    ):
        _fail("PRODUCTION_GUARD_INVALID", "production_guards must be a list of paths")
    if is_v2 and not guards:
        _fail("PRODUCTION_GUARD_REQUIRED", "v2 contacts require a live production guard")
    forbidden_types = harness.get("forbidden_item_types", [])
    if not isinstance(forbidden_types, list) or any(
        not isinstance(item, str) or not item for item in forbidden_types
    ):
        _fail("HARNESS_INVALID", "forbidden_item_types must be a list of strings")
    return dict(spec)


def _source_blob_path(runtime_root: Path, digest: str) -> Path:
    return runtime_root / "raw_archive" / "blobs" / "sha256" / digest[:2] / f"{digest}.bin"


def _compile_contrast_view(
    *,
    source_refs: Sequence[str],
    sources: Mapping[str, Mapping[str, Any]],
    terminal_contract: bytes,
) -> tuple[bytes, list[dict[str, Any]]]:
    chunks: list[bytes] = []
    selected: list[dict[str, Any]] = []
    for source_id in source_refs:
        source = sources[source_id]
        raw = _resolve(str(source["sealed_copy_path"])).read_bytes()
        header = (
            f"--- ARCHIVED SOURCE {source_id} sha256={source['archive_sha256']} ---\n"
        ).encode("utf-8")
        chunks.extend((header, raw, b"\n"))
        selected.append(
            {
                "source_id": source_id,
                "chronology_index": source.get("chronology_index"),
                "role": source.get("role"),
                "provenance_kind": source.get("provenance_kind"),
                "archive_sha256": source["archive_sha256"],
            }
        )
    chunks.extend((b"\n--- TERMINAL CONTRACT ---\n", terminal_contract))
    if not terminal_contract.endswith(b"\n"):
        chunks.append(b"\n")
    return b"".join(chunks), selected


def _populate_workspace(
    *,
    root: Path,
    text_files: Mapping[str, str],
    source_files: Mapping[str, str],
    sources: Mapping[str, Mapping[str, Any]],
) -> None:
    for relative, content in text_files.items():
        atomic_write_bytes(root / _safe_relative(relative), content.encode("utf-8"))
    for relative, source_id in source_files.items():
        raw = _resolve(str(sources[source_id]["sealed_copy_path"])).read_bytes()
        atomic_write_bytes(root / _safe_relative(relative), raw)


def freeze_cell(spec_path: Path, runtime_root: Path = DEFAULT_RUNTIME_ROOT) -> dict[str, Any]:
    """Freeze a preregistered cell without launching a cognition consumer."""

    spec_path = _resolve(spec_path)
    spec = _validate_spec(_read_json(spec_path))
    root = validate_runtime_root(runtime_root)
    cell_dir = root / "cells" / spec["cell_id"]
    spec_raw = _canonical_bytes(spec)
    spec_sha = _sha(spec_raw)
    existing = cell_dir / "cell.json"
    if existing.is_file():
        cell = _read_json(existing)
        if cell.get("spec_sha256") != spec_sha:
            _fail("CELL_CONFLICT", f"cell id already binds different preregistration: {cell_dir}")
        verification = verify_cell(cell_dir)
        if not verification["ok"]:
            _fail("CELL_DRIFT", f"existing cell failed verification: {cell_dir}")
        return {
            "disposition": "ACCEPTED_IDENTICAL_REUSE",
            "cell_directory": str(cell_dir),
            "cell_sha256": cell["cell_sha256"],
        }
    if cell_dir.exists():
        _fail("CELL_CONFLICT", f"unsealed cell directory already exists: {cell_dir}")
    is_v2 = spec["schema"] == CELL_SPEC_SCHEMA
    sealed = cell_dir / "sealed"
    sources_dir = sealed / "sources"
    variants_dir = sealed / "variants"
    views_dir = sealed / "contrast_views"
    workspace_dir = sealed / "workspace_seed"
    workspace_variants_dir = sealed / "workspace_variants"
    for directory in (
        sources_dir,
        variants_dir,
        views_dir,
        workspace_dir,
        workspace_variants_dir,
    ):
        directory.mkdir(parents=True, exist_ok=False)
    try:
        source_rows: list[dict[str, Any]] = []
        for index, row in enumerate(spec["episode"].get("sources", []), 1):
            raw, identity = _material_bytes(row.get("material", {}))
            target = sources_dir / f"{index:02d}-{row['id']}.bin"
            atomic_write_bytes(target, raw)
            digest = _sha(raw)
            canonical = _source_blob_path(root, digest)
            archive_disposition = _write_once(
                canonical,
                raw,
                conflict_code="RAW_ARCHIVE_COLLISION",
            )
            source_rows.append(
                {
                    "id": row["id"],
                    "role": row.get("role", "evidence"),
                    "visibility": row.get("visibility", "evidence_only"),
                    "known_at": row.get("known_at"),
                    "chronology_index": row.get("chronology_index"),
                    "provenance_kind": row.get("provenance_kind", "raw"),
                    "derived_from": row.get("derived_from", []),
                    "archive_path": str(canonical),
                    "canonical_archive_path": str(canonical),
                    "sealed_copy_path": str(target),
                    "archive_disposition": archive_disposition,
                    "archive_sha256": digest,
                    "archive_bytes": len(raw),
                    "material_identity": identity,
                }
            )
        sources_by_id = {row["id"]: row for row in source_rows}
        raw_archive_manifest = {
            "schema": RAW_ARCHIVE_SCHEMA,
            "authority": False,
            "cell_id": spec["cell_id"],
            "content_addressed": True,
            "append_only": True,
            "sources": [
                {
                    key: row.get(key)
                    for key in (
                        "id",
                        "role",
                        "visibility",
                        "known_at",
                        "chronology_index",
                        "provenance_kind",
                        "derived_from",
                        "canonical_archive_path",
                        "sealed_copy_path",
                        "archive_sha256",
                        "archive_bytes",
                    )
                }
                for row in source_rows
            ],
        }
        raw_archive_path = sealed / "raw_archive_manifest.json"
        atomic_write_json(raw_archive_path, raw_archive_manifest)
        reconstruction = {
            "schema": RECONSTRUCTION_SCHEMA,
            "authority": False,
            "operator_interpretation": None,
            "cell_id": spec["cell_id"],
            "cutoff_index": spec["episode"].get("cutoff_index"),
            "cutoff_label": spec["episode"].get("cutoff"),
            "replay_fidelity": spec["episode"]["replay_fidelity"],
            "known_gaps": spec["episode"]["known_gaps"],
            "source_sequence": [
                {
                    "source_id": row["id"],
                    "chronology_index": row.get("chronology_index"),
                    "known_at": row.get("known_at"),
                    "visibility": row["visibility"],
                    "archive_sha256": row["archive_sha256"],
                }
                for row in sorted(
                    source_rows,
                    key=lambda item: (
                        item.get("chronology_index") is None,
                        item.get("chronology_index") or 0,
                        item["id"],
                    ),
                )
            ],
        }
        reconstruction_path = sealed / "episode_reconstruction.json"
        atomic_write_json(reconstruction_path, reconstruction)

        _populate_workspace(
            root=workspace_dir,
            text_files=spec["harness"]["workspace_files"],
            source_files=spec["harness"].get("workspace_source_files", {}),
            sources=sources_by_id,
        )
        workspace_manifest = _tree_manifest(workspace_dir)
        local_mcp_descriptor: dict[str, Any] | None = None
        local_mcp = spec["harness"].get("local_mcp")
        if local_mcp is not None:
            script_relative = str(local_mcp["script_path"])
            config_relative = str(local_mcp["config_path"])
            script_path = workspace_dir / _safe_relative(script_relative)
            config_path = workspace_dir / _safe_relative(config_relative)
            local_mcp_descriptor = {
                "server_id": local_mcp["server_id"],
                "transport": "stdio",
                "command": "python",
                "script_path": script_relative,
                "script_sha256": sha256_file(script_path).casefold(),
                "config_path": config_relative,
                "config_sha256": sha256_file(config_path).casefold(),
                "enabled_tools": list(local_mcp["enabled_tools"]),
                "startup_timeout_sec": float(local_mcp.get("startup_timeout_sec", 20.0)),
                "tool_timeout_sec": float(local_mcp.get("tool_timeout_sec", 120.0)),
                "required": True,
                "default_tools_approval_mode": "approve",
            }
        variant_rows: list[dict[str, Any]] = []
        visible_blobs: list[bytes] = [
            path.read_bytes() for path in workspace_dir.rglob("*") if path.is_file()
        ]
        common_identity: dict[str, Any] | None = None
        common_path: Path | None = None
        common_raw = b""
        if is_v2:
            terminal_raw, terminal_identity = _material_bytes(
                spec["intervention"]["terminal_contract"]
            )
            terminal_path = sealed / "terminal_contract.bin"
            atomic_write_bytes(terminal_path, terminal_raw)
        else:
            common_raw, common_identity = _material_bytes(spec["intervention"]["common"])
            common_path = sealed / "common_prompt.bin"
            atomic_write_bytes(common_path, common_raw)
            terminal_raw = str(spec["intervention"].get("shared_instruction", "")).encode("utf-8")
            terminal_identity = {
                "kind": "legacy_shared_instruction",
                "bytes": len(terminal_raw),
                "sha256": _sha(terminal_raw),
            }
        terminal_sha = _sha(terminal_raw)
        view_manifest_rows: list[dict[str, Any]] = []
        for row in spec["intervention"]["variants"]:
            variant_id = row["id"]
            variant_workspace = workspace_variants_dir / variant_id
            shutil.copytree(workspace_dir, variant_workspace)
            for relative in row.get("workspace_remove", []):
                target = variant_workspace / _safe_relative(relative)
                if target.is_dir():
                    _fail(
                        "WORKSPACE_FILE_INVALID",
                        f"workspace_remove targets a directory: {relative}",
                    )
                target.unlink(missing_ok=True)
            _populate_workspace(
                root=variant_workspace,
                text_files=row.get("workspace_files", {}),
                source_files=row.get("workspace_source_files", {}),
                sources=sources_by_id,
            )
            variant_workspace_manifest = _tree_manifest(variant_workspace)
            if is_v2:
                source_refs = [
                    *spec["intervention"].get("common_view", []),
                    *row.get("view", []),
                ]
                prompt_raw, selected_sources = _compile_contrast_view(
                    source_refs=source_refs,
                    sources=sources_by_id,
                    terminal_contract=terminal_raw,
                )
                condition_path = None
                condition_sha = None
                condition_bytes = None
                identity = None
            else:
                condition_raw, identity = _material_bytes(row["condition"])
                condition_path = variants_dir / f"{variant_id}.bin"
                atomic_write_bytes(condition_path, condition_raw)
                prompt_raw = (
                    common_raw
                    + b"\n\n--- INTERVENTION CONDITION ---\n"
                    + condition_raw
                    + (b"\n\n--- SHARED REQUEST ---\n" + terminal_raw if terminal_raw else b"")
                )
                selected_sources = []
                condition_sha = _sha(condition_raw)
                condition_bytes = len(condition_raw)
            prompt_path = views_dir / f"{variant_id}.prompt.bin"
            atomic_write_bytes(prompt_path, prompt_raw)
            view_manifest = {
                "schema": CONTRAST_VIEW_SCHEMA,
                "authority": False,
                "cell_id": spec["cell_id"],
                "variant_id": variant_id,
                "cutoff_index": spec["episode"].get("cutoff_index"),
                "selected_sources": selected_sources,
                "factor_assignments": row.get("factor_assignments", {}),
                "known_confounders": spec["intervention"].get("known_confounders", []),
                "terminal_contract_sha256": terminal_sha,
                "compiled_prompt_path": str(prompt_path),
                "compiled_prompt_sha256": _sha(prompt_raw),
                "compiled_prompt_bytes": len(prompt_raw),
                "workspace_tree_sha256": variant_workspace_manifest["tree_sha256"],
            }
            view_manifest_path = views_dir / f"{variant_id}.view.json"
            atomic_write_json(view_manifest_path, view_manifest)
            visible_blobs.append(prompt_raw)
            visible_blobs.extend(
                path.read_bytes() for path in variant_workspace.rglob("*") if path.is_file()
            )
            variant_rows.append(
                {
                    "id": variant_id,
                    "provenance_kind": row.get("provenance_kind", "unknown"),
                    "factor_assignments": row.get("factor_assignments", {}),
                    "condition_path": str(condition_path) if condition_path else None,
                    "condition_sha256": condition_sha,
                    "condition_bytes": condition_bytes,
                    "material_identity": identity,
                    "compiled_prompt_path": str(prompt_path),
                    "compiled_prompt_sha256": _sha(prompt_raw),
                    "compiled_prompt_bytes": len(prompt_raw),
                    "contrast_view_path": str(view_manifest_path),
                    "contrast_view_sha256": sha256_file(view_manifest_path).casefold(),
                    "workspace_seed": variant_workspace_manifest,
                }
            )
            view_manifest_rows.append(
                {
                    "variant_id": variant_id,
                    "path": str(view_manifest_path),
                    "sha256": sha256_file(view_manifest_path).casefold(),
                    "compiled_prompt_sha256": _sha(prompt_raw),
                }
            )
        if not is_v2 and len({row["condition_sha256"] for row in variant_rows}) != len(
            variant_rows
        ):
            _fail("INTERVENTION_INVALID", "variant condition bytes must differ")

        for sentinel in spec.get("forbidden_future_sentinels", []):
            needle = sentinel.encode("utf-8")
            if any(needle in blob for blob in visible_blobs):
                _fail("INVALID_EXPERIMENT", "a preregistered future sentinel is model-visible")

        launcher_path = sealed / "Open-Codex-Research-Cell.ps1"
        launcher_receipt = create_world_isolated_launcher(
            _resolve(spec["harness"].get("launcher", DEFAULT_LAUNCHER)),
            launcher_path,
            network_access=True,
        )
        replay_twin = {
            "schema": REPLAY_TWIN_SCHEMA,
            "authority": False,
            "completion_claim_allowed": False,
            "cell_id": spec["cell_id"],
            "account_slot": spec["harness"]["account_slot"],
            "model": spec["harness"].get("model", "gpt-5.6-sol"),
            "model_reasoning_effort": spec["harness"].get("model_reasoning_effort", "max"),
            "max_account_research_turns": spec["harness"].get("max_account_research_turns", 2),
            "physical_world_turn_slots": spec["harness"].get("physical_world_turn_slots", 4),
            "root_main_used": False,
            "root_main_compute_allowed": False,
            "local_mcp": (
                {
                    key: local_mcp_descriptor[key]
                    for key in (
                        "server_id",
                        "transport",
                        "script_sha256",
                        "config_sha256",
                        "enabled_tools",
                        "required",
                    )
                }
                if local_mcp_descriptor is not None
                else None
            ),
            "launcher_sha256": launcher_receipt["sha256"],
            "reconstruction_sha256": sha256_file(reconstruction_path).casefold(),
            "variants": [
                {
                    "variant_id": row["id"],
                    "compiled_prompt_sha256": row["compiled_prompt_sha256"],
                    "workspace_tree_sha256": row["workspace_seed"]["tree_sha256"],
                }
                for row in variant_rows
            ],
        }
        replay_twin_path = sealed / "replay_twin.json"
        atomic_write_json(replay_twin_path, replay_twin)
        source_map = {
            "schema": (
                "xinao.research-of-research.source-map.v2"
                if is_v2
                else "xinao.research-of-research.source-map.v1"
            ),
            "cell_id": spec["cell_id"],
            "episode": spec["episode"],
            "sources": source_rows,
            "raw_archive_manifest": {
                "path": str(raw_archive_path),
                "sha256": sha256_file(raw_archive_path).casefold(),
            },
            "episode_reconstruction": {
                "path": str(reconstruction_path),
                "sha256": sha256_file(reconstruction_path).casefold(),
            },
            "common": (
                {
                    "path": str(common_path),
                    "sha256": _sha(common_raw),
                    "bytes": len(common_raw),
                    "material_identity": common_identity,
                }
                if common_path is not None
                else None
            ),
            "terminal_contract": {
                "path": str(terminal_path) if is_v2 else None,
                "sha256": terminal_sha,
                "bytes": len(terminal_raw),
                "material_identity": terminal_identity,
            },
            "variants": variant_rows,
            "contrast_views": view_manifest_rows,
            "workspace_seed": workspace_manifest,
            "local_mcp": local_mcp_descriptor,
            "launcher": launcher_receipt,
            "replay_twin": {
                "path": str(replay_twin_path),
                "sha256": sha256_file(replay_twin_path).casefold(),
            },
        }
        source_map_path = cell_dir / "source_map.json"
        atomic_write_json(source_map_path, source_map)
        spec_snapshot = cell_dir / "preregistration.json"
        atomic_write_bytes(spec_snapshot, spec_raw)
        unsigned_cell = {
            "schema": CELL_SCHEMA,
            "authority": False,
            "completion_claim_allowed": False,
            "cell_id": spec["cell_id"],
            "created_at": now_iso(),
            "spec_path": str(spec_snapshot),
            "spec_sha256": spec_sha,
            "source_map_path": str(source_map_path),
            "source_map_sha256": sha256_file(source_map_path).casefold(),
            "replay_fidelity": spec["episode"]["replay_fidelity"],
            "known_gaps": spec["episode"]["known_gaps"],
            "preregistered_hypotheses": spec.get("hypotheses", []),
            "only_changed": spec["intervention"].get("only_changed"),
            "intervention_variables": spec["intervention"].get(
                "intervention_variables",
                (
                    [spec["intervention"]["only_changed"]]
                    if spec["intervention"].get("only_changed")
                    else []
                ),
            ),
            "known_confounders": spec["intervention"].get("known_confounders", []),
            "raw_archive_manifest_path": str(raw_archive_path),
            "episode_reconstruction_path": str(reconstruction_path),
            "replay_twin_path": str(replay_twin_path),
            "runs_root": str(cell_dir / "runs"),
        }
        cell = {**unsigned_cell, "cell_sha256": _sha(_canonical_bytes(unsigned_cell))}
        atomic_write_json(existing, cell)
        verification = verify_cell(cell_dir)
        if not verification["ok"]:
            _fail("FREEZE_VERIFICATION_FAILED", json.dumps(verification, ensure_ascii=False))
        return {
            "disposition": "CREATED",
            "cell_directory": str(cell_dir),
            "cell_sha256": cell["cell_sha256"],
            "verification": verification,
        }
    except BaseException:
        # Keep partial bytes for forensic recovery; never silently overwrite them.
        raise


class AccountQuota:
    """Shared A/C world-turn admission compatible with the production lease schema."""

    def __init__(
        self,
        *,
        account_slot: str,
        quota_root: Path,
        limit: int,
        run_id: str,
        reclaim_bound_leases: bool = True,
    ) -> None:
        if account_slot not in {"A", "C"} or limit < 1:
            _fail("QUOTA_CONFIG_INVALID", "invalid account slot or concurrency limit")
        self.account_slot = account_slot
        self.account_root = _resolve(quota_root) / account_slot
        self.limit = limit
        self.run_id = run_id
        self.reclaim_bound_leases = reclaim_bound_leases
        self.guard_path = self.account_root / "admission.lock"
        self.records = [
            self.account_root / f"world-turn-{index:02d}.json" for index in range(1, limit + 1)
        ]

    @staticmethod
    def _archive(path: Path, record: Mapping[str, Any]) -> None:
        lease_id = str(record.get("lease_id", "")).strip()
        if not lease_id:
            _fail("QUOTA_RECORD_INVALID", f"quota record lacks lease identity: {path}")
        history = path.parent / "history" / f"{lease_id}.json"
        raw = path.read_bytes()
        if history.exists() and history.read_bytes() != raw:
            _fail("QUOTA_HISTORY_COLLISION", f"quota history collision: {history}")
        if not history.exists():
            atomic_write_bytes(history, raw)

    def try_claim_outcome(self, *, lineage_id: str, workspace: Path) -> dict[str, Any]:
        """Try once while preserving lock contention versus real capacity pressure."""

        guard = _try_acquire_byte_lock(self.guard_path)
        if guard is None:
            return {"outcome": "LOCK_BUSY"}
        try:
            for slot, path in enumerate(self.records, 1):
                if path.is_file():
                    prior = read_json_object(path)
                    if (
                        prior.get("schema") != WORLD_TURN_QUOTA_LEASE_SCHEMA
                        or prior.get("account_slot") != self.account_slot
                        or int(prior.get("slot", -1)) != slot
                    ):
                        _fail("QUOTA_RECORD_INVALID", f"quota record identity drift: {path}")
                    status = str(prior.get("status", ""))
                    if prior.get("operator_throttle") is True and status in {"RESERVED", "BOUND"}:
                        # A throttle is an account policy reservation, not a dead
                        # child lease that an experiment may recycle.  Its owner
                        # must explicitly release it.
                        continue
                    if status == "RESERVED":
                        continue
                    if status == "BOUND":
                        if not self.reclaim_bound_leases:
                            continue
                        child_pid = prior.get("child_pid")
                        controller_pid = prior.get("controller_pid")
                        child_liveness = (
                            process_liveness(child_pid)
                            if isinstance(child_pid, int)
                            and not isinstance(child_pid, bool)
                            and child_pid > 0
                            else ProcessLiveness.UNKNOWN
                        )
                        if child_liveness != ProcessLiveness.DEAD:
                            continue
                        controller_liveness = (
                            process_liveness(controller_pid)
                            if isinstance(controller_pid, int)
                            and not isinstance(controller_pid, bool)
                            and controller_pid > 0
                            else ProcessLiveness.UNKNOWN
                        )
                        if controller_liveness != ProcessLiveness.DEAD:
                            continue
                    elif status != "RELEASED":
                        _fail("QUOTA_RECORD_INVALID", f"quota status drift: {path}:{status}")
                    self._archive(path, prior)
                lease = {
                    "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                    "lease_id": f"quota-ror-{uuid.uuid4().hex}",
                    "counted": True,
                    "status": "RESERVED",
                    "account_slot": self.account_slot,
                    "slot": slot,
                    "limit": self.limit,
                    "run_id": self.run_id,
                    "lineage_id": lineage_id,
                    "workspace": str(_resolve(workspace)),
                    "controller_pid": os.getpid(),
                    "child_pid": None,
                    "reserved_at": now_iso(),
                    "bound_at": None,
                    "released_at": None,
                    "experiment_candidate_only": True,
                }
                atomic_write_json(path, lease)
                return {"outcome": "CLAIMED", "lease": {**lease, "path": str(path)}}
            return {"outcome": "CAPACITY_BUSY"}
        finally:
            _release_byte_lock(guard)

    def try_claim(self, *, lineage_id: str, workspace: Path) -> dict[str, Any] | None:
        """Compatibility surface for callers that already retry either busy outcome."""

        result = self.try_claim_outcome(lineage_id=lineage_id, workspace=workspace)
        return dict(result["lease"]) if result["outcome"] == "CLAIMED" else None

    def claim(self, *, lineage_id: str, workspace: Path, timeout_seconds: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            lease = self.try_claim(lineage_id=lineage_id, workspace=workspace)
            if lease is not None:
                return lease
            time.sleep(0.05)
        _fail("QUOTA_TIMEOUT", f"no {self.account_slot} world-turn quota became available")

    def bind(self, lease: Mapping[str, Any], *, child_pid: int) -> dict[str, Any]:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            guard = _try_acquire_byte_lock(self.guard_path)
            if guard is None:
                time.sleep(0.05)
                continue
            try:
                path = _resolve(str(lease["path"]))
                current = read_json_object(path)
                if (
                    current.get("lease_id") != lease["lease_id"]
                    or current.get("status") != "RESERVED"
                ):
                    _fail("QUOTA_RESERVATION_DRIFT", f"quota reservation drift: {path}")
                # The process that performs the bind owns the child and the
                # release window.  A short admission tick may already have
                # exited, so retaining its PID would let another controller
                # recycle this BOUND record after the child exits but before
                # the real owner seals and releases it.
                current.update(
                    {
                        "status": "BOUND",
                        "controller_pid": os.getpid(),
                        "child_pid": child_pid,
                        "bound_at": now_iso(),
                    }
                )
                atomic_write_json(path, current)
                return {**current, "path": str(path)}
            finally:
                _release_byte_lock(guard)
        _fail("QUOTA_BIND_TIMEOUT", "could not bind child to quota reservation")

    def release(self, lease: Mapping[str, Any]) -> str:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            guard = _try_acquire_byte_lock(self.guard_path)
            if guard is None:
                time.sleep(0.05)
                continue
            try:
                try:
                    slot = lease["slot"]
                    if type(slot) is not int or not 1 <= slot <= self.limit:
                        return "OWNERSHIP_DRIFT"
                    path = _resolve(str(lease["path"]))
                except (KeyError, TypeError, ValueError):
                    return "OWNERSHIP_DRIFT"
                expected_path = self.records[slot - 1]
                if path != expected_path:
                    return "OWNERSHIP_DRIFT"
                current = read_json_object(path)
                immutable_identity = (
                    "schema",
                    "lease_id",
                    "counted",
                    "account_slot",
                    "slot",
                    "limit",
                    "run_id",
                    "lineage_id",
                    "workspace",
                )
                if (
                    lease.get("schema") != WORLD_TURN_QUOTA_LEASE_SCHEMA
                    or lease.get("counted") is not True
                    or lease.get("account_slot") != self.account_slot
                    or lease.get("limit") != self.limit
                    or lease.get("run_id") != self.run_id
                    or any(current.get(key) != lease.get(key) for key in immutable_identity)
                ):
                    return "OWNERSHIP_DRIFT"
                status = current.get("status")
                if status not in {"RESERVED", "BOUND", "RELEASED"}:
                    return "OWNERSHIP_DRIFT"
                if status == "RELEASED":
                    return "RELEASED"
                child_pid = current.get("child_pid")
                if status == "BOUND":
                    child_liveness = (
                        process_liveness(child_pid)
                        if isinstance(child_pid, int)
                        and not isinstance(child_pid, bool)
                        and child_pid > 0
                        else ProcessLiveness.UNKNOWN
                    )
                    if child_liveness == ProcessLiveness.ALIVE:
                        return "CHILD_STILL_ALIVE"
                    if child_liveness != ProcessLiveness.DEAD:
                        return "CHILD_LIVENESS_UNKNOWN"
                current.update({"status": "RELEASED", "released_at": now_iso()})
                atomic_write_json(path, current)
                return "RELEASED"
            finally:
                _release_byte_lock(guard)
        return "RELEASE_TIMEOUT"


def _observe_guard(path: Path) -> dict[str, Any]:
    last_error: ResearchCellError | None = None
    for _attempt in range(10):
        try:
            identity = _file_identity(path)
            value = _read_json(path)
            if _file_identity(path)["sha256"] == identity["sha256"]:
                break
        except ResearchCellError as exc:
            last_error = exc
        time.sleep(0.01)
    else:
        raise ResearchCellError(
            "PRODUCTION_GUARD_UNSTABLE",
            f"could not take a stable read-only guard observation: {path}: {last_error}",
        )
    observed_pid = value.get("controller_pid")
    observed_pid_field = "controller_pid"
    if not isinstance(observed_pid, int):
        observed_pid = value.get("pid")
        observed_pid_field = "pid"
    return {
        **identity,
        "run_id": value.get("run_id"),
        "account_slot": value.get("account_slot"),
        "status": value.get("status"),
        "stop_requested": value.get("stop_requested"),
        "controller_pid": observed_pid,
        "controller_pid_field": observed_pid_field,
        "controller_alive": (
            is_process_alive(observed_pid) if isinstance(observed_pid, int) else None
        ),
    }


def _check_guard_transition(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for field in ("run_id", "account_slot"):
        if before.get(field) is not None and after.get(field) != before.get(field):
            failures.append(f"{field}_changed")
    if before.get("stop_requested") is False and after.get("stop_requested") is True:
        failures.append("stop_was_requested")
    if before.get("controller_alive") is True and after.get("controller_alive") is False:
        failures.append("controller_died")
    return failures


def _require_live_production_guards(observations: Sequence[Mapping[str, Any]]) -> None:
    for observation in observations:
        failures: list[str] = []
        if observation.get("status") != "RUNNING":
            failures.append("status_not_running")
        if observation.get("stop_requested") is not False:
            failures.append("stop_not_false")
        if observation.get("controller_alive") is not True:
            failures.append("controller_not_alive")
        if failures:
            _fail(
                "PRODUCTION_GUARD_NOT_LIVE",
                f"production guard is not live: {observation.get('path')}:{','.join(failures)}",
            )


def _observe_cap_policy(
    path: Path,
    *,
    account_slot: str,
    declared_cap: int,
    physical_slots: int,
) -> dict[str, Any]:
    last_error: ResearchCellError | None = None
    for _attempt in range(50):
        try:
            identity = _file_identity(path)
            value = _read_json(path)
            if _file_identity(path)["sha256"] == identity["sha256"]:
                break
        except ResearchCellError as exc:
            last_error = exc
        time.sleep(0.005)
    else:
        raise ResearchCellError(
            "CAP_POLICY_UNSTABLE",
            f"could not take a stable cap-policy read: {path}: {last_error}",
        )
    failures: list[str] = []
    expected_throttles = physical_slots - declared_cap
    if value.get("account_slot") != account_slot:
        failures.append("account_slot")
    if value.get("simultaneous_independent_world_turn_cap") != declared_cap:
        failures.append("declared_cap")
    if value.get("physical_slots") != physical_slots:
        failures.append("physical_slots")
    if value.get("required_throttle_count") != expected_throttles:
        failures.append("required_throttle_count")
    throttle_slots = value.get("active_throttle_slots")
    if (
        not isinstance(throttle_slots, list)
        or len(throttle_slots) != expected_throttles
        or any(
            not isinstance(slot, int) or isinstance(slot, bool) or slot < 1 or slot > physical_slots
            for slot in throttle_slots
        )
        or len(set(throttle_slots)) != len(throttle_slots)
    ):
        failures.append("active_throttle_slots")
    if value.get("late_fusion_root_counted") is not False:
        failures.append("late_fusion_root_counted")
    if value.get("late_fusion_root_compute_allowed") is not False:
        failures.append("late_fusion_root_compute_allowed")
    holder_pid = value.get("pid")
    holder_alive = isinstance(holder_pid, int) and is_process_alive(holder_pid)
    if not holder_alive:
        failures.append("holder_not_alive")
    if failures:
        _fail("CAP_POLICY_INVALID", f"cap policy contract failed: {','.join(failures)}")
    return {
        **identity,
        "schema": value.get("schema"),
        "status": value.get("status"),
        "account_slot": value.get("account_slot"),
        "physical_slots": value.get("physical_slots"),
        "simultaneous_independent_world_turn_cap": value.get(
            "simultaneous_independent_world_turn_cap"
        ),
        "required_throttle_count": value.get("required_throttle_count"),
        "active_throttle_slots": throttle_slots,
        "holder_pid": holder_pid,
        "holder_alive": holder_alive,
        "late_fusion_root_counted": False,
        "late_fusion_root_compute_allowed": False,
    }


def _observe_cap_throttles(
    quota: "AccountQuota", cap_policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for slot in cap_policy.get("active_throttle_slots", []):
        path = quota.records[int(slot) - 1]
        last_error: ResearchCellError | None = None
        for _attempt in range(10):
            try:
                identity = _file_identity(path)
                value = _read_json(path)
                if _file_identity(path)["sha256"] == identity["sha256"]:
                    break
            except ResearchCellError as exc:
                last_error = exc
            time.sleep(0.01)
        else:
            raise ResearchCellError(
                "CAP_THROTTLE_UNSTABLE",
                f"could not take a stable throttle observation: {path}: {last_error}",
            )
        pid_candidates = [value.get("child_pid"), value.get("controller_pid")]
        throttle_alive = any(
            isinstance(pid, int) and not isinstance(pid, bool) and is_process_alive(pid)
            for pid in pid_candidates
        )
        failures: list[str] = []
        if value.get("schema") != WORLD_TURN_QUOTA_LEASE_SCHEMA:
            failures.append("schema")
        if value.get("account_slot") != quota.account_slot:
            failures.append("account_slot")
        if value.get("slot") != slot:
            failures.append("slot")
        if value.get("status") != "BOUND":
            failures.append("status")
        if value.get("operator_throttle") is not True:
            failures.append("operator_throttle")
        if not throttle_alive:
            failures.append("throttle_not_alive")
        if failures:
            _fail(
                "CAP_THROTTLE_INVALID",
                f"cap throttle contract failed for slot {slot}: {','.join(failures)}",
            )
        observations.append(
            {
                **identity,
                "slot": slot,
                "lease_id": value.get("lease_id"),
                "status": value.get("status"),
                "operator_throttle": True,
                "child_pid": value.get("child_pid"),
                "controller_pid": value.get("controller_pid"),
                "throttle_alive": throttle_alive,
            }
        )
    return observations


def _codex_arguments(
    *,
    model: str,
    effort: str,
    web_search: str,
    last_message_path: Path,
    local_mcp: Mapping[str, Any] | None = None,
    workspace: Path | None = None,
) -> list[str]:
    arguments = [
        "exec",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ephemeral",
        "--strict-config",
        "--json",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-c",
        f'web_search="{web_search}"',
        "-c",
        "features.multi_agent=false",
        "-c",
        "features.multi_agent_v2=false",
        "-c",
        "features.memories=false",
    ]
    if local_mcp is not None:
        if workspace is None:
            _fail("LOCAL_MCP_INVALID", "local MCP requires the isolated workspace")
        server_id = str(local_mcp["server_id"])
        prefix = f"mcp_servers.{server_id}"
        server_args = [
            str(local_mcp["script_path"]),
            "--config",
            str(local_mcp["config_path"]),
        ]
        settings: list[tuple[str, object]] = [
            ("command", str(local_mcp["command"])),
            ("args", server_args),
            ("cwd", str(workspace)),
            ("startup_timeout_sec", float(local_mcp["startup_timeout_sec"])),
            ("tool_timeout_sec", float(local_mcp["tool_timeout_sec"])),
            ("default_tools_approval_mode", "approve"),
            ("enabled_tools", list(local_mcp["enabled_tools"])),
            ("required", True),
            ("enabled", True),
        ]
        for key, value in settings:
            arguments.extend(["-c", f"{prefix}.{key}={_toml_cli_literal(value)}"])
    arguments.extend(["-o", str(last_message_path), "-"])
    return arguments


def _toml_cli_literal(value: object) -> str:
    """Render the tiny config value subset without Windows eating TOML quotes.

    The clean-room launcher passes a PowerShell string array to a native exe.
    Double quotes inside one array element are consumed by that boundary;
    TOML literal strings use single quotes and therefore survive unchanged.
    """

    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "[" + ",".join(_toml_cli_literal(item) for item in value) + "]"
    _fail("LOCAL_MCP_INVALID", "unsupported local MCP config value")


def _mechanical_contrast(run_dir: Path, jobs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for job in jobs:
        index_path = _resolve(str(job["trajectory_index"]["path"]))
        event_types: Counter[str] = Counter()
        item_types: Counter[str] = Counter()
        sequence: list[str] = []
        with index_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                event = json.loads(line)
                event_type = str(event.get("event_type"))
                item_type = str(event.get("item_type"))
                event_types[event_type] += 1
                if item_type != "None":
                    item_types[item_type] += 1
                    if len(sequence) < 32:
                        sequence.append(item_type)
        last_path = _resolve(str(job["last_message_path"]))
        last_raw = last_path.read_bytes() if last_path.is_file() else b""
        rows.append(
            {
                "variant_id": job["variant_id"],
                "replicate": job["replicate"],
                "event_types": dict(sorted(event_types.items())),
                "item_types": dict(sorted(item_types.items())),
                "first_item_type_sequence": sequence,
                "last_message_sha256": _sha(last_raw),
                "last_message_bytes": len(last_raw),
                "workspace_tree_sha256": job["workspace_after"]["tree_sha256"],
                "workspace_delta": job.get("workspace_delta", {}),
                "action_cone": job.get("action_cone", {}),
            }
        )
    contrast = {
        "schema": CONTRAST_SCHEMA,
        "authority": False,
        "scientific_verdict": None,
        "diagnostic_only": True,
        "not_contrast_view": True,
        "ledger_role": "post_run_mechanical_descriptor",
        "note": "Mechanical descriptors only; they are neither a Contrast View nor qualified evidence.",
        "rows": rows,
    }
    path = run_dir / "mechanical_contrast.json"
    atomic_write_json(path, contrast)
    return {**contrast, "path": str(path), "sha256": sha256_file(path).casefold()}


def _observed_item_types(index_path: Path) -> set[str]:
    observed: set[str] = set()
    with index_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            item_type = row.get("item_type")
            if isinstance(item_type, str) and item_type:
                observed.add(item_type)
    return observed


def _write_raw_trajectory_ledger(
    *,
    run_dir: Path,
    cell: Mapping[str, Any],
    run_id: str,
    status: str,
    jobs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ledger_dir = run_dir / "ledgers"
    raw_ledger = {
        "schema": RAW_TRAJECTORY_LEDGER_SCHEMA,
        "authority": False,
        "completion_claim_allowed": False,
        "cell_id": cell["cell_id"],
        "cell_sha256": cell["cell_sha256"],
        "run_id": run_id,
        "run_status": status,
        "append_only": True,
        "trajectories": [
            {
                "lineage_id": row["lineage_id"],
                "variant_id": row["variant_id"],
                "replicate": row["replicate"],
                "prompt_sha256": row["prompt_sha256"],
                "trajectory_raw_path": row["trajectory_index"]["raw_path"],
                "trajectory_raw_sha256": row["trajectory_index"]["raw_sha256"],
                "trajectory_index_path": row["trajectory_index"]["path"],
                "trajectory_index_sha256": row["trajectory_index"]["sha256"],
                "workspace_before_tree_sha256": row["workspace_before"]["tree_sha256"],
                "workspace_after_tree_sha256": row["workspace_after"]["tree_sha256"],
                "workspace_delta": row.get("workspace_delta", {}),
                "exit_code": row["exit_code"],
            }
            for row in jobs
        ],
    }
    raw_path = ledger_dir / "raw_trajectory_manifest.json"
    atomic_write_json(raw_path, raw_ledger)
    return {
        "raw_trajectory": {
            "path": str(raw_path),
            "sha256": sha256_file(raw_path).casefold(),
        }
    }


def run_cell(
    cell_dir: Path,
    *,
    replicates: int = 1,
    max_parallel: int = 2,
    quota_wait_seconds: float = 300.0,
    variant_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run fresh isolated variants; retain raw evidence and make no scientific verdict."""

    if replicates < 1 or max_parallel < 1:
        _fail("RUN_ARGUMENT_INVALID", "replicates and max_parallel must be positive")
    cell_dir = _resolve(cell_dir)
    # A damaged historical run is evidence damage, not a mutation of the
    # frozen cell inputs.  Keep it visible to normal verification while still
    # allowing a fresh isolated retry when the preregistration itself is sound.
    frozen = verify_cell(cell_dir, include_runs=False)
    if not frozen["ok"]:
        _fail("CELL_DRIFT", json.dumps(frozen, ensure_ascii=False))
    cell = _read_json(cell_dir / "cell.json")
    spec = _read_json(cell_dir / "preregistration.json")
    source_map = _read_json(cell_dir / "source_map.json")
    harness = spec["harness"]
    is_v2 = spec.get("schema") == CELL_SPEC_SCHEMA
    available_variant_ids = [str(row["id"]) for row in source_map["variants"]]
    if variant_ids is None:
        selected_variant_ids = available_variant_ids
    else:
        selected_variant_ids = list(variant_ids)
        if not selected_variant_ids or len(set(selected_variant_ids)) != len(selected_variant_ids):
            _fail("RUN_VARIANT_INVALID", "variant_ids must be a non-empty unique selection")
        unknown = sorted(set(selected_variant_ids) - set(available_variant_ids))
        if unknown:
            _fail("RUN_VARIANT_INVALID", f"unknown preregistered variants: {unknown}")
    declared_cap = int(
        harness.get(
            "max_account_research_turns",
            2 if is_v2 else harness.get("world_turn_concurrency_limit", 4),
        )
    )
    effective_cap = min(declared_cap, TEMPORARY_ACCOUNT_RESEARCH_CAP)
    physical_slots = int(harness.get("physical_world_turn_slots", 4))
    if max_parallel > effective_cap:
        _fail(
            "ACCOUNT_RESEARCH_CAP_EXCEEDED",
            f"max_parallel={max_parallel} exceeds current account cap={effective_cap}",
        )
    run_id = datetime.now(timezone.utc).strftime("ror-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    guard_paths = [_resolve(item) for item in spec.get("production_guards", [])]
    guards_before = [_observe_guard(path) for path in guard_paths]
    if is_v2:
        _require_live_production_guards(guards_before)
    cap_policy_before = (
        _observe_cap_policy(
            _resolve(harness["account_research_cap_policy"]),
            account_slot=harness["account_slot"],
            declared_cap=effective_cap,
            physical_slots=physical_slots,
        )
        if is_v2
        else None
    )
    quota = AccountQuota(
        account_slot=harness["account_slot"],
        quota_root=_resolve(harness.get("world_turn_quota_root", DEFAULT_QUOTA_ROOT)),
        limit=physical_slots,
        run_id=run_id,
    )
    cap_throttles_before = (
        _observe_cap_throttles(quota, cap_policy_before) if cap_policy_before is not None else None
    )
    # Reject an invalid live boundary before creating a run identity.  A
    # preflight refusal launches no cognition consumer and is not a run.
    run_dir = cell_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    state_path = run_dir / "run_state.json"
    atomic_write_json(
        state_path,
        {"schema": RUN_SCHEMA, "run_id": run_id, "status": "PREPARING", "started_at": now_iso()},
    )
    common = (
        _resolve(source_map["common"]["path"]).read_text(encoding="utf-8")
        if source_map.get("common")
        else ""
    )
    shared_instruction = str(spec["intervention"].get("shared_instruction", ""))
    variants = {row["id"]: row for row in source_map["variants"]}
    jobs: list[dict[str, Any]] = []
    for replicate in range(1, replicates + 1):
        for variant_id in selected_variant_ids:
            jobs.append({"variant_id": variant_id, "replicate": replicate, **variants[variant_id]})
    launcher = _resolve(source_map["launcher"]["path"])
    powershell = _resolve(harness.get("powershell_path", DEFAULT_POWERSHELL))
    model = str(harness.get("model", "gpt-5.6-sol"))
    effort = str(harness.get("model_reasoning_effort", "max"))
    web_search = str(harness.get("web_search", "disabled"))
    timeout_seconds = float(harness.get("turn_timeout_seconds", 1800))
    runner_source_sha256 = sha256_file(Path(__file__)).casefold()
    workspace_root = _validate_workspace_root(
        _resolve(harness.get("workspace_root", DEFAULT_WORKSPACE_ROOT))
    )
    completed: list[dict[str, Any]] = []
    stop_requested = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    prior_handlers: dict[int, Any] = {}
    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is not None:
            prior_handlers[signal_value] = signal.signal(signal_value, request_stop)
    try:
        atomic_write_json(
            state_path,
            {"schema": RUN_SCHEMA, "run_id": run_id, "status": "RUNNING", "started_at": now_iso()},
        )
        for offset in range(0, len(jobs), max_parallel):
            batch = jobs[offset : offset + max_parallel]
            active: list[dict[str, Any]] = []
            try:
                # Reserve the whole batch before starting any child.  This prevents a
                # finished first child from self-blocking behind a second quota claim.
                for job in batch:
                    if stop_requested:
                        _fail("RUN_STOPPED", "stop requested during research cell run")
                    lineage_id = f"{job['variant_id']}-r{job['replicate']:02d}"
                    workspace = workspace_root / cell["cell_id"] / run_id / lineage_id
                    workspace_seed = job.get("workspace_seed", source_map["workspace_seed"])
                    shutil.copytree(_resolve(workspace_seed["root"]), workspace)
                    workspace_before = _tree_manifest(workspace)
                    if workspace_before["tree_sha256"] != workspace_seed["tree_sha256"]:
                        _fail(
                            "REPLAY_TWIN_SEED_DRIFT",
                            f"copied workspace seed drift: {job['variant_id']}",
                        )
                    job_dir = run_dir / "arms" / lineage_id
                    job_dir.mkdir(parents=True, exist_ok=False)
                    if job.get("compiled_prompt_path"):
                        prompt_raw = _resolve(job["compiled_prompt_path"]).read_bytes()
                        if _sha(prompt_raw) != job.get("compiled_prompt_sha256"):
                            _fail(
                                "CONTRAST_VIEW_DRIFT", f"compiled view drift: {job['variant_id']}"
                            )
                    else:
                        condition = _resolve(job["condition_path"]).read_text(encoding="utf-8")
                        prompt = common + "\n\n--- INTERVENTION CONDITION ---\n" + condition
                        if shared_instruction:
                            prompt += "\n\n--- SHARED REQUEST ---\n" + shared_instruction
                        prompt_raw = prompt.encode("utf-8")
                    prompt_path = job_dir / "prompt_snapshot.md"
                    atomic_write_bytes(prompt_path, prompt_raw)
                    last_path = job_dir / "last_message.txt"
                    args_path = job_dir / "codex_args.json"
                    local_mcp = source_map.get("local_mcp")
                    if local_mcp is not None:
                        for path_key, sha_key in (
                            ("script_path", "script_sha256"),
                            ("config_path", "config_sha256"),
                        ):
                            carrier = workspace / _safe_relative(str(local_mcp[path_key]))
                            if (
                                not carrier.is_file()
                                or sha256_file(carrier).casefold() != local_mcp[sha_key]
                            ):
                                _fail(
                                    "LOCAL_MCP_DRIFT",
                                    f"local MCP carrier drift: {job['variant_id']}:{path_key}",
                                )
                    arguments = _codex_arguments(
                        model=model,
                        effort=effort,
                        web_search=web_search,
                        last_message_path=last_path,
                        local_mcp=local_mcp,
                        workspace=workspace,
                    )
                    atomic_write_bytes(
                        args_path, json.dumps(arguments, ensure_ascii=False).encode("utf-8")
                    )
                    if is_v2:
                        live_cap_policy = _observe_cap_policy(
                            _resolve(harness["account_research_cap_policy"]),
                            account_slot=harness["account_slot"],
                            declared_cap=effective_cap,
                            physical_slots=physical_slots,
                        )
                        _observe_cap_throttles(quota, live_cap_policy)
                    lease = quota.claim(
                        lineage_id=lineage_id,
                        workspace=workspace,
                        timeout_seconds=quota_wait_seconds,
                    )
                    stdout_path = job_dir / "trajectory.jsonl"
                    stderr_path = job_dir / "stderr.txt"
                    command = [
                        str(powershell),
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(launcher),
                        "-AccountSlot",
                        harness["account_slot"],
                        "-WorkDir",
                        str(workspace),
                        "-CodexArgsFile",
                        str(args_path),
                    ]
                    active.append(
                        {
                            **job,
                            "lineage_id": lineage_id,
                            "workspace": workspace,
                            "workspace_before": workspace_before,
                            "job_dir": job_dir,
                            "prompt_path": prompt_path,
                            "prompt_raw": prompt_raw,
                            "last_path": last_path,
                            "args_path": args_path,
                            "stdout_path": stdout_path,
                            "stderr_path": stderr_path,
                            "stdout_stream": None,
                            "stderr_stream": None,
                            "child": None,
                            "lease": lease,
                            "command": command,
                            "launched_at": None,
                        }
                    )
                for row in active:
                    stdout_stream = row["stdout_path"].open("wb")
                    stderr_stream = row["stderr_path"].open("wb")
                    row["stdout_stream"] = stdout_stream
                    row["stderr_stream"] = stderr_stream
                    child = subprocess.Popen(
                        row["command"],
                        cwd=row["workspace"],
                        stdin=subprocess.PIPE,
                        stdout=stdout_stream,
                        stderr=stderr_stream,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    row["child"] = child
                    row["launched_at"] = now_iso()
                    bound = quota.bind(row["lease"], child_pid=child.pid)
                    row["lease"] = bound
                    if child.stdin is None:
                        _fail("PROMPT_TRANSPORT_INVALID", "Codex stdin pipe was not created")
                    try:
                        child.stdin.write(row["prompt_raw"])
                        child.stdin.close()
                    except BrokenPipeError:
                        child.stdin.close()
                deadline = time.monotonic() + timeout_seconds
                while any(row["child"].poll() is None for row in active):
                    if stop_requested or time.monotonic() >= deadline:
                        for row in active:
                            if row["child"].poll() is None:
                                row["child"].terminate()
                        break
                    time.sleep(0.25)
                for row in active:
                    child = row["child"]
                    try:
                        exit_code = child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        exit_code = child.wait(timeout=30)
                    row["stdout_stream"].close()
                    row["stderr_stream"].close()
                    release_status = quota.release(row["lease"])
                    index = build_trajectory_index(
                        row["stdout_path"], row["job_dir"] / "trajectory_index.jsonl"
                    )
                    forbidden_types = set(harness.get("forbidden_item_types", []))
                    forbidden_observed = sorted(
                        forbidden_types & _observed_item_types(_resolve(index["path"]))
                    )
                    workspace_after = _tree_manifest(row["workspace"])
                    workspace_after_snapshot = _snapshot_tree(
                        row["workspace"], row["job_dir"] / "workspace_after"
                    )
                    workspace_delta = _tree_delta(row["workspace_before"], workspace_after)
                    observables = spec.get("observables", {})
                    action_cone = (
                        _classify_action_cone(workspace_delta, observables)
                        if isinstance(observables, Mapping)
                        and (
                            observables.get("old_action_cone_paths")
                            or observables.get("new_action_cone_paths")
                        )
                        else None
                    )
                    completed_row = {
                        "variant_id": row["variant_id"],
                        "replicate": row["replicate"],
                        "lineage_id": row["lineage_id"],
                        "pid": child.pid,
                        "exit_code": exit_code,
                        "launched_at": row["launched_at"],
                        "finished_at": now_iso(),
                        "workspace": str(row["workspace"]),
                        "workspace_seed_tree_sha256": row.get("workspace_seed", {}).get(
                            "tree_sha256",
                            source_map["workspace_seed"]["tree_sha256"],
                        ),
                        "workspace_before": row["workspace_before"],
                        "workspace_after": workspace_after,
                        "workspace_after_snapshot": workspace_after_snapshot,
                        "workspace_delta": workspace_delta,
                        "prompt_path": str(row["prompt_path"]),
                        "prompt_sha256": sha256_file(row["prompt_path"]).casefold(),
                        "compiled_prompt_expected_sha256": row.get("compiled_prompt_sha256"),
                        "contrast_view_path": row.get("contrast_view_path"),
                        "contrast_view_sha256": row.get("contrast_view_sha256"),
                        "prompt_transport": "stdin_utf8",
                        "arguments_path": str(row["args_path"]),
                        "arguments_sha256": sha256_file(row["args_path"]).casefold(),
                        "local_mcp": (
                            {
                                key: source_map["local_mcp"][key]
                                for key in (
                                    "server_id",
                                    "transport",
                                    "script_sha256",
                                    "config_sha256",
                                    "enabled_tools",
                                    "required",
                                )
                            }
                            if source_map.get("local_mcp") is not None
                            else None
                        ),
                        "trajectory_index": index,
                        "forbidden_item_types_observed": forbidden_observed,
                        "stderr_path": str(row["stderr_path"]),
                        "stderr_sha256": sha256_file(row["stderr_path"]).casefold(),
                        "last_message_path": str(row["last_path"]),
                        "last_message_sha256": (
                            sha256_file(row["last_path"]).casefold()
                            if row["last_path"].is_file()
                            else None
                        ),
                        "quota_lease_id": row["lease"]["lease_id"],
                        "quota_slot": row["lease"]["slot"],
                        "quota_release_status": release_status,
                    }
                    if action_cone is not None:
                        completed_row["action_cone"] = action_cone
                    completed.append(completed_row)
            finally:
                for row in active:
                    child = row.get("child")
                    if child is not None and child.poll() is None:
                        child.kill()
                        child.wait(timeout=30)
                    if row.get("stdout_stream") is not None and not row["stdout_stream"].closed:
                        row["stdout_stream"].close()
                    if row.get("stderr_stream") is not None and not row["stderr_stream"].closed:
                        row["stderr_stream"].close()
                    quota.release(row["lease"])

        guards_after = [_observe_guard(path) for path in guard_paths]
        cap_policy_after = (
            _observe_cap_policy(
                _resolve(harness["account_research_cap_policy"]),
                account_slot=harness["account_slot"],
                declared_cap=effective_cap,
                physical_slots=physical_slots,
            )
            if is_v2
            else None
        )
        cap_throttles_after = (
            _observe_cap_throttles(quota, cap_policy_after)
            if cap_policy_after is not None
            else None
        )
        guard_failures = [
            {"path": before["path"], "failures": _check_guard_transition(before, after)}
            for before, after in zip(guards_before, guards_after, strict=True)
            if _check_guard_transition(before, after)
        ]
        cap_policy_failures: list[str] = []
        if cap_policy_before and cap_policy_after:
            for field in (
                "account_slot",
                "physical_slots",
                "simultaneous_independent_world_turn_cap",
                "required_throttle_count",
                "holder_pid",
                "late_fusion_root_counted",
                "late_fusion_root_compute_allowed",
            ):
                if cap_policy_after.get(field) != cap_policy_before.get(field):
                    cap_policy_failures.append(f"{field}_changed")
        if cap_throttles_before is not None and cap_throttles_after is not None:
            before_throttles = [(row["slot"], row["lease_id"]) for row in cap_throttles_before]
            after_throttles = [(row["slot"], row["lease_id"]) for row in cap_throttles_after]
            if after_throttles != before_throttles:
                cap_policy_failures.append("active_throttle_identity_changed")
        contrast = _mechanical_contrast(run_dir, completed)
        all_ok = bool(completed) and all(
            row["exit_code"] == 0
            and row["quota_release_status"] == "RELEASED"
            and row["trajectory_index"]["event_count"] > 0
            and not row["forbidden_item_types_observed"]
            for row in completed
        )
        status = (
            "SEALED"
            if all_ok and not guard_failures and not cap_policy_failures
            else "INVALID_EXPERIMENT"
        )
        ledgers = _write_raw_trajectory_ledger(
            run_dir=run_dir,
            cell=cell,
            run_id=run_id,
            status=status,
            jobs=completed,
        )
        receipt = {
            "schema": RUN_SCHEMA,
            "authority": False,
            "completion_claim_allowed": False,
            "scientific_verdict": None,
            "run_id": run_id,
            "cell_id": cell["cell_id"],
            "cell_sha256": cell["cell_sha256"],
            "status": status,
            "started_at": _read_json(state_path)["started_at"],
            "finished_at": now_iso(),
            "account_slot": harness["account_slot"],
            "max_account_research_turns": effective_cap,
            "physical_world_turn_slots": physical_slots,
            "root_main_used": False,
            "root_main_state": "NO_ROOT_MAIN_JOB_CREATED",
            "root_main_compute_allowed": False,
            "model": model,
            "model_reasoning_effort": effort,
            "web_search": web_search,
            "runner_source_sha256": runner_source_sha256,
            "prompt_transport": "stdin_utf8",
            "local_mcp": source_map.get("local_mcp"),
            "replicates": replicates,
            "selected_variant_ids": selected_variant_ids,
            "held_constants": spec["intervention"].get("held_constants", []),
            "only_changed": spec["intervention"].get("only_changed"),
            "intervention_variables": spec["intervention"].get(
                "intervention_variables",
                (
                    [spec["intervention"]["only_changed"]]
                    if spec["intervention"].get("only_changed")
                    else []
                ),
            ),
            "known_confounders": spec["intervention"].get("known_confounders", []),
            "jobs": completed,
            "production_guards_before": guards_before,
            "production_guards_after": guards_after,
            "production_guard_failures": guard_failures,
            "account_research_cap_policy_before": cap_policy_before,
            "account_research_cap_policy_after": cap_policy_after,
            "account_research_cap_throttles_before": cap_throttles_before,
            "account_research_cap_throttles_after": cap_throttles_after,
            "account_research_cap_policy_failures": cap_policy_failures,
            "mechanical_contrast_path": contrast["path"],
            "mechanical_contrast_sha256": contrast["sha256"],
            "ledgers": ledgers,
        }
        receipt["receipt_sha256"] = _sha(_canonical_bytes(receipt))
        receipt_path = run_dir / "run_receipt.json"
        atomic_write_json(receipt_path, receipt)
        # Optional low-latency bell only.  A sibling one-shot Scheduled Task
        # rescans durable receipts, so task absence/failure cannot fail the run
        # or create a commit-notify dual-write requirement.
        request_continuation_reconcile(
            receipt_path=receipt_path,
            runtime_root=cell_dir.parent.parent,
        )
        atomic_write_json(
            state_path,
            {"schema": RUN_SCHEMA, "run_id": run_id, "status": status, "finished_at": now_iso()},
        )
        return {**receipt, "run_directory": str(run_dir), "receipt_path": str(receipt_path)}
    except BaseException as exc:
        atomic_write_json(
            state_path,
            {
                "schema": RUN_SCHEMA,
                "run_id": run_id,
                "status": "FAILED",
                "failed_at": now_iso(),
                "error_type": type(exc).__name__,
                "reason_code": getattr(exc, "reason_code", None),
            },
        )
        raise
    finally:
        for signal_value, handler in prior_handlers.items():
            signal.signal(signal_value, handler)


def verify_cell(cell_dir: Path, *, include_runs: bool = True) -> dict[str, Any]:
    """Re-hash the preregistration, sealed inputs, and every completed run."""

    cell_dir = _resolve(cell_dir)
    failures: list[str] = []
    try:
        cell = _read_json(cell_dir / "cell.json")
        spec_path = _resolve(cell["spec_path"])
        source_map_path = _resolve(cell["source_map_path"])
        spec_raw = spec_path.read_bytes()
        if _sha(spec_raw) != cell.get("spec_sha256"):
            failures.append("PREDICTION_MUTATED")
        if sha256_file(source_map_path).casefold() != cell.get("source_map_sha256"):
            failures.append("SOURCE_MAP_MUTATED")
        unsigned = dict(cell)
        observed_seal = unsigned.pop("cell_sha256", None)
        if _sha(_canonical_bytes(unsigned)) != observed_seal:
            failures.append("CELL_SEAL_INVALID")
        source_map = _read_json(source_map_path)
        for source in source_map.get("sources", []):
            path = _resolve(source["archive_path"])
            if not path.is_file() or sha256_file(path).casefold() != source["archive_sha256"]:
                failures.append(f"SOURCE_ARCHIVE_DRIFT:{source.get('id')}")
            sealed_copy = source.get("sealed_copy_path")
            if sealed_copy and (
                not _resolve(sealed_copy).is_file()
                or sha256_file(_resolve(sealed_copy)).casefold() != source["archive_sha256"]
            ):
                failures.append(f"SOURCE_SEALED_COPY_DRIFT:{source.get('id')}")
        for key, failure in (
            ("raw_archive_manifest", "RAW_ARCHIVE_MANIFEST_DRIFT"),
            ("episode_reconstruction", "EPISODE_RECONSTRUCTION_DRIFT"),
            ("replay_twin", "REPLAY_TWIN_DRIFT"),
        ):
            descriptor = source_map.get(key)
            if descriptor and (
                not _resolve(descriptor["path"]).is_file()
                or sha256_file(_resolve(descriptor["path"])).casefold() != descriptor["sha256"]
            ):
                failures.append(failure)
        common = source_map.get("common")
        if common and sha256_file(_resolve(common["path"])).casefold() != common["sha256"]:
            failures.append("COMMON_PROMPT_DRIFT")
        terminal = source_map.get("terminal_contract")
        if (
            terminal
            and terminal.get("path")
            and (sha256_file(_resolve(terminal["path"])).casefold() != terminal["sha256"])
        ):
            failures.append("TERMINAL_CONTRACT_DRIFT")
        for variant in source_map["variants"]:
            condition_path = variant.get("condition_path")
            if condition_path and (
                sha256_file(_resolve(condition_path)).casefold() != variant["condition_sha256"]
            ):
                failures.append(f"CONDITION_DRIFT:{variant['id']}")
            compiled_path = variant.get("compiled_prompt_path")
            if compiled_path and (
                sha256_file(_resolve(compiled_path)).casefold() != variant["compiled_prompt_sha256"]
            ):
                failures.append(f"COMPILED_VIEW_DRIFT:{variant['id']}")
            view_path = variant.get("contrast_view_path")
            if view_path and (
                sha256_file(_resolve(view_path)).casefold() != variant["contrast_view_sha256"]
            ):
                failures.append(f"CONTRAST_VIEW_MANIFEST_DRIFT:{variant['id']}")
            variant_workspace = variant.get("workspace_seed")
            if variant_workspace and (
                _tree_manifest(_resolve(variant_workspace["root"]))["tree_sha256"]
                != variant_workspace["tree_sha256"]
            ):
                failures.append(f"VARIANT_WORKSPACE_SEED_DRIFT:{variant['id']}")
        if (
            _tree_manifest(_resolve(source_map["workspace_seed"]["root"]))["tree_sha256"]
            != source_map["workspace_seed"]["tree_sha256"]
        ):
            failures.append("WORKSPACE_SEED_DRIFT")
        local_mcp = source_map.get("local_mcp")
        if isinstance(local_mcp, Mapping):
            workspace_seed_root = _resolve(source_map["workspace_seed"]["root"])
            for path_key, sha_key in (
                ("script_path", "script_sha256"),
                ("config_path", "config_sha256"),
            ):
                carrier = workspace_seed_root / _safe_relative(str(local_mcp[path_key]))
                if not carrier.is_file() or sha256_file(carrier).casefold() != local_mcp[sha_key]:
                    failures.append(f"LOCAL_MCP_CARRIER_DRIFT:{path_key}")
        launcher = source_map["launcher"]
        if sha256_file(_resolve(launcher["path"])).casefold() != str(launcher["sha256"]).casefold():
            failures.append("LAUNCHER_DRIFT")
        run_rows: list[dict[str, Any]] = []
        runs_root = cell_dir / "runs"
        if include_runs and runs_root.is_dir():
            for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
                receipt_path = run_dir / "run_receipt.json"
                if not receipt_path.is_file():
                    run_rows.append({"run_id": run_dir.name, "status": "INCOMPLETE"})
                    failures.append(f"RUN_INCOMPLETE:{run_dir.name}")
                    continue
                receipt = _read_json(receipt_path)
                run_failures: list[str] = []
                if receipt.get("cell_sha256") != cell.get("cell_sha256"):
                    run_failures.append("RUN_CELL_IDENTITY_DRIFT")
                if receipt.get("receipt_sha256"):
                    unsigned_receipt = dict(receipt)
                    observed_receipt_seal = unsigned_receipt.pop("receipt_sha256")
                    if _sha(_canonical_bytes(unsigned_receipt)) != observed_receipt_seal:
                        run_failures.append("RUN_RECEIPT_SEAL_INVALID")
                contrast_path = _resolve(receipt["mechanical_contrast_path"])
                if sha256_file(contrast_path).casefold() != receipt["mechanical_contrast_sha256"]:
                    run_failures.append("CONTRAST_DRIFT")
                for ledger_name, descriptor in receipt.get("ledgers", {}).items():
                    ledger_path = _resolve(descriptor["path"])
                    if (
                        not ledger_path.is_file()
                        or sha256_file(ledger_path).casefold() != descriptor["sha256"]
                    ):
                        run_failures.append(f"LEDGER_DRIFT:{ledger_name}")
                for job in receipt.get("jobs", []):
                    if job.get("local_mcp") != (
                        {
                            key: source_map["local_mcp"][key]
                            for key in (
                                "server_id",
                                "transport",
                                "script_sha256",
                                "config_sha256",
                                "enabled_tools",
                                "required",
                            )
                        }
                        if source_map.get("local_mcp") is not None
                        else None
                    ):
                        run_failures.append(f"LOCAL_MCP_BINDING_DRIFT:{job['lineage_id']}")
                    raw_path = _resolve(job["trajectory_index"]["raw_path"])
                    index_path = _resolve(job["trajectory_index"]["path"])
                    if (
                        sha256_file(raw_path).casefold()
                        != str(job["trajectory_index"]["raw_sha256"]).casefold()
                    ):
                        run_failures.append(f"TRAJECTORY_DRIFT:{job['lineage_id']}")
                    if (
                        sha256_file(index_path).casefold()
                        != str(job["trajectory_index"]["sha256"]).casefold()
                    ):
                        run_failures.append(f"TRAJECTORY_INDEX_DRIFT:{job['lineage_id']}")
                    if job.get("last_message_sha256"):
                        if (
                            sha256_file(_resolve(job["last_message_path"])).casefold()
                            != job["last_message_sha256"]
                        ):
                            run_failures.append(f"LAST_MESSAGE_DRIFT:{job['lineage_id']}")
                    for field, reason in (
                        ("prompt", "PROMPT_SNAPSHOT_DRIFT"),
                        ("arguments", "ARGUMENTS_DRIFT"),
                        ("stderr", "STDERR_DRIFT"),
                    ):
                        path_key = f"{field}_path"
                        sha_key = f"{field}_sha256"
                        if job.get(path_key) and (
                            sha256_file(_resolve(job[path_key])).casefold() != job.get(sha_key)
                        ):
                            run_failures.append(f"{reason}:{job['lineage_id']}")
                    for manifest_name in ("workspace_before", "workspace_after"):
                        manifest = job.get(manifest_name, {})
                        if _sha(_canonical_bytes(manifest.get("files", []))) != manifest.get(
                            "tree_sha256"
                        ):
                            run_failures.append(
                                f"WORKSPACE_MANIFEST_INVALID:{job['lineage_id']}:{manifest_name}"
                            )
                    snapshot = job.get("workspace_after_snapshot")
                    if isinstance(snapshot, Mapping):
                        snapshot_root = _resolve(str(snapshot.get("root", "")))
                        try:
                            snapshot_root.relative_to(run_dir)
                        except ValueError:
                            run_failures.append(
                                f"WORKSPACE_AFTER_SNAPSHOT_OUTSIDE_RUN:{job['lineage_id']}"
                            )
                        if not snapshot_root.is_dir():
                            run_failures.append(
                                f"WORKSPACE_AFTER_SNAPSHOT_MISSING:{job['lineage_id']}"
                            )
                        else:
                            live_snapshot = _tree_manifest(snapshot_root)
                            expected_after = job.get("workspace_after", {}).get("tree_sha256")
                            if (
                                live_snapshot["tree_sha256"] != snapshot.get("tree_sha256")
                                or snapshot.get("tree_sha256") != expected_after
                            ):
                                run_failures.append(
                                    f"WORKSPACE_AFTER_SNAPSHOT_DRIFT:{job['lineage_id']}"
                                )
                    else:
                        # Legacy receipts predate archived workspace snapshots.
                        workspace_path = job.get("workspace")
                        if (
                            not isinstance(workspace_path, str)
                            or not _resolve(workspace_path).is_dir()
                        ):
                            run_failures.append(f"WORKSPACE_AFTER_MISSING:{job['lineage_id']}")
                        else:
                            live_workspace = _tree_manifest(_resolve(workspace_path))
                            if live_workspace["tree_sha256"] != job.get("workspace_after", {}).get(
                                "tree_sha256"
                            ):
                                run_failures.append(f"WORKSPACE_AFTER_DRIFT:{job['lineage_id']}")
                    expected_prompt = job.get("compiled_prompt_expected_sha256")
                    if expected_prompt and expected_prompt != job.get("prompt_sha256"):
                        run_failures.append(f"COMPILED_VIEW_NOT_CONSUMED:{job['lineage_id']}")
                    expected_seed = job.get("workspace_seed_tree_sha256")
                    if expected_seed and expected_seed != job.get("workspace_before", {}).get(
                        "tree_sha256"
                    ):
                        run_failures.append(f"REPLAY_TWIN_SEED_NOT_CONSUMED:{job['lineage_id']}")
                if receipt.get("schema") == RUN_SCHEMA:
                    selected = receipt.get("selected_variant_ids")
                    if selected is None:
                        selected = [row.get("id") for row in source_map.get("variants", [])]
                    available = {row.get("id") for row in source_map.get("variants", [])}
                    if (
                        not isinstance(selected, list)
                        or not selected
                        or len(set(selected)) != len(selected)
                        or any(item not in available for item in selected)
                    ):
                        run_failures.append("RUN_VARIANT_SET_INVALID")
                        selected = []
                    replicate_count = int(receipt.get("replicates", 0))
                    expected_pairs = {
                        (variant_id, replicate)
                        for variant_id in selected
                        for replicate in range(1, replicate_count + 1)
                    }
                    observed_pairs = [
                        (row.get("variant_id"), row.get("replicate"))
                        for row in receipt.get("jobs", [])
                    ]
                    if (
                        len(observed_pairs) != len(expected_pairs)
                        or set(observed_pairs) != expected_pairs
                    ):
                        run_failures.append("RUN_JOB_SET_INCOMPLETE")
                    if (
                        receipt.get("root_main_used") is not False
                        or receipt.get("root_main_compute_allowed") is not False
                    ):
                        run_failures.append("ROOT_MAIN_BOUNDARY_INVALID")
                    if receipt.get("status") == "SEALED" and (
                        receipt.get("production_guard_failures")
                        or receipt.get("account_research_cap_policy_failures")
                        or any(
                            row.get("exit_code") != 0
                            or row.get("quota_release_status") != "RELEASED"
                            for row in receipt.get("jobs", [])
                        )
                    ):
                        run_failures.append("SEALED_STATUS_INVARIANT_INVALID")
                run_rows.append(
                    {
                        "run_id": receipt.get("run_id"),
                        "status": receipt.get("status"),
                        "failures": run_failures,
                    }
                )
                failures.extend(run_failures)
        return {
            "schema": VERIFY_SCHEMA,
            "cell_directory": str(cell_dir),
            "cell_id": cell.get("cell_id"),
            "ok": not failures,
            "failures": failures,
            "runs": run_rows,
            "verified_at": now_iso(),
            "authority": False,
            "completion_claim_allowed": False,
        }
    except (KeyError, OSError, ResearchCellError, json.JSONDecodeError) as exc:
        return {
            "schema": VERIFY_SCHEMA,
            "cell_directory": str(cell_dir),
            "ok": False,
            "failures": [f"VERIFY_EXCEPTION:{type(exc).__name__}:{exc}"],
            "runs": [],
            "verified_at": now_iso(),
            "authority": False,
            "completion_claim_allowed": False,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze, run, or verify one bounded research-of-research contact"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--spec", type=Path, required=True)
    freeze.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    run = subparsers.add_parser("run")
    run.add_argument("--cell-dir", type=Path, required=True)
    run.add_argument("--replicates", type=int, default=1)
    run.add_argument("--max-parallel", type=int, default=2)
    run.add_argument("--quota-wait-seconds", type=float, default=300.0)
    run.add_argument("--variant", dest="variant_ids", action="append")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--cell-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "freeze":
            result = freeze_cell(args.spec, args.runtime_root)
        elif args.command == "run":
            result = run_cell(
                args.cell_dir,
                replicates=args.replicates,
                max_parallel=args.max_parallel,
                quota_wait_seconds=args.quota_wait_seconds,
                variant_ids=args.variant_ids,
            )
        else:
            result = verify_cell(args.cell_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", result.get("status") != "INVALID_EXPERIMENT") else 2
    except ResearchCellError as exc:
        print(json.dumps({"ok": False, "reason_code": exc.reason_code, "error": str(exc)}))
        return 2


__all__ = [
    "CELL_SPEC_SCHEMA",
    "LEGACY_CELL_SPEC_SCHEMA",
    "AccountQuota",
    "ResearchCellError",
    "build_parser",
    "freeze_cell",
    "main",
    "run_cell",
    "validate_runtime_root",
    "verify_cell",
]
