"""Fail-closed, per-attempt runtime bindings for migrated XINAO reality.

This module creates and validates immutable records only.  It never modifies a
launcher, materializes a live view, starts a child, or writes a runtime file.
The controller remains responsible for writing canonical bytes into the exact
attempt directory and the frozen launcher remains responsible for applying the
sealed environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

WORLD_RUNTIME_BINDING_SCHEMA = "xinao.cleanroom.world-runtime-binding.v1"
WORLD_RUNTIME_APPLIED_RECEIPT_SCHEMA = "xinao.cleanroom.world-runtime-binding-applied.v1"

_ENVIRONMENT_NAMES = frozenset(
    {"PYTHONPATH", "XINAO_WORLD_WORKSPACE", "XINAO_LIVE_REALITY_ROOT"}
)
_ROLES = frozenset({"independent_world", "late_fusion_root"})
_ACCOUNT_SLOTS = frozenset({"A", "C"})
_LEGACY_LIVE_RELATIVE = Path("xinao") / "reality" / "live"
_MIGRATION_SCHEMA = "xinao.reality-live-copy-first-migration.v1"
_EFFECTIVE_CODE_SCHEMA = "xinao.lineage-effective-code.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_HEAD_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_NONCE_RE = re.compile(r"^[0-9a-f]{32,64}$")


class WorldRuntimeBindingError(ValueError):
    """A binding, external identity, or applied receipt failed closed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(reason_code: str, message: str) -> None:
    raise WorldRuntimeBindingError(reason_code, message)


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("INPUT_INVALID", f"{field} must be an object")
    return dict(value)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        _fail("EVIDENCE_MISSING", f"{field} is missing fields: {', '.join(missing)}")
    if extra:
        _fail("INPUT_INVALID", f"{field} has unsupported fields: {', '.join(extra)}")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail("INPUT_INVALID", f"{field} must be a non-empty exact string")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        _fail("INPUT_INVALID", f"{field} must be a lowercase SHA-256")
    return value


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail("INPUT_INVALID", f"{field} must be an integer >= 1")
    return value


def _false(value: object, field: str) -> bool:
    if value is not False:
        _fail("BOUNDARY_VIOLATION", f"{field} must be false")
    return False


def _zero(value: object, field: str) -> int:
    if isinstance(value, bool) or value != 0:
        _fail("CROSS_LINEAGE_FALLBACK_FORBIDDEN", f"{field} must be zero")
    return 0


def _is_reparse(path: Path) -> bool:
    metadata = path.lstat()
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return path.is_symlink() or bool(reparse_flag and attributes & reparse_flag)


def _path(value: object, field: str, *, kind: str) -> Path:
    text = _text(value, field)
    raw = Path(text)
    if not raw.is_absolute():
        _fail("PATH_INVALID", f"{field} must be absolute")
    resolved = raw.resolve(strict=False)
    if str(resolved) != text:
        _fail("PATH_NONCANONICAL", f"{field} must be an exact resolved path")
    if not resolved.exists():
        _fail("PATH_MISSING", f"{field} is missing: {resolved}")
    if _is_reparse(resolved):
        _fail("PATH_REPARSE_FORBIDDEN", f"{field} is a reparse point")
    if kind == "file" and not resolved.is_file():
        _fail("PATH_KIND_MISMATCH", f"{field} must be a regular file")
    if kind == "directory" and not resolved.is_dir():
        _fail("PATH_KIND_MISMATCH", f"{field} must be a directory")
    return resolved


def _path_identity(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _same_path(left: Path, right: Path) -> bool:
    return _path_identity(left) == _path_identity(right)


def _is_within(path: Path, root: Path) -> bool:
    value = _path_identity(path)
    parent = _path_identity(root)
    return value == parent or value.startswith(parent + os.sep)


def _strictly_within(path: Path, root: Path) -> bool:
    return _is_within(path, root) and not _same_path(path, root)


def _verify_file(path_value: object, sha_value: object, field: str) -> tuple[Path, str]:
    path = _path(path_value, f"{field}_path", kind="file")
    expected = _sha256(sha_value, f"{field}_sha256")
    observed = sha256_file(path)
    if observed != expected:
        _fail(
            "EXTERNAL_IDENTITY_DRIFT",
            f"{field} bytes drifted: expected={expected}; observed={observed}",
        )
    return path, expected


def _json_file(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldRuntimeBindingError("MANIFEST_INVALID", f"{field} is not JSON") from exc
    return _mapping(value, field)


def _verify_exact_effective_tree(
    root: Path, manifest: Mapping[str, object]
) -> str:
    """Bind the declared effective-code manifest to the exact runnable bytes."""

    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list) or any(
        not isinstance(entry, Mapping) for entry in raw_entries
    ):
        _fail("EFFECTIVE_CODE_TREE_INVALID", "effective code entries must be objects")
    expected: dict[str, dict[str, object]] = {}
    for index, raw_entry in enumerate(raw_entries):
        entry = dict(raw_entry)
        _exact_keys(
            entry,
            frozenset({"relative_path", "classification", "bytes", "sha256"}),
            f"entries[{index}]",
        )
        relative = _text(entry.get("relative_path"), f"entries[{index}].relative_path")
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or relative_path.as_posix() != relative
            or any(part in {"", ".", ".."} for part in relative_path.parts)
        ):
            _fail("EFFECTIVE_CODE_TREE_INVALID", "effective code path is unsafe")
        folded = relative.casefold()
        if folded in expected:
            _fail(
                "EFFECTIVE_CODE_TREE_COLLISION",
                "effective code manifest has a case-insensitive path collision",
            )
        size = entry.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            _fail("EFFECTIVE_CODE_TREE_INVALID", "effective code bytes must be >= 0")
        expected[folded] = {
            "relative_path": relative,
            "classification": _text(
                entry.get("classification"), f"entries[{index}].classification"
            ),
            "bytes": size,
            "sha256": _sha256(entry.get("sha256"), f"entries[{index}].sha256"),
        }
    observed: dict[str, Path] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if _is_reparse(path):
            _fail("EFFECTIVE_CODE_TREE_REPARSE", "effective code contains a reparse point")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        folded = relative.casefold()
        if folded in observed:
            _fail(
                "EFFECTIVE_CODE_TREE_COLLISION",
                "effective code has a case-insensitive path collision",
            )
        observed[folded] = path
    if set(observed) != set(expected):
        _fail(
            "EFFECTIVE_CODE_TREE_SET_MISMATCH",
            "effective code exact file set differs from its manifest",
        )
    records: list[dict[str, object]] = []
    for folded, record in expected.items():
        relative = str(record["relative_path"])
        expected_size = int(record["bytes"])
        expected_sha = str(record["sha256"])
        path = observed[folded]
        size = path.stat().st_size
        observed_sha = sha256_file(path)
        if size != expected_size or observed_sha != expected_sha:
            _fail(
                "EFFECTIVE_CODE_TREE_BYTES_MISMATCH",
                f"effective code bytes drifted: {relative}",
            )
        records.append(dict(record))
    canonical_records = sorted(records, key=lambda item: str(item["relative_path"]).casefold())
    digest = hashlib.sha256()
    for record in canonical_records:
        digest.update(canonical_json_bytes(record))
    tree_sha = digest.hexdigest()
    declared = _sha256(manifest.get("payload_tree_sha256"), "payload_tree_sha256")
    if tree_sha != declared:
        _fail(
            "EFFECTIVE_CODE_TREE_HASH_MISMATCH",
            "effective code tree does not match the declared payload identity",
        )
    return tree_sha


def _seal(record: Mapping[str, object], hash_field: str) -> dict[str, Any]:
    sealed = dict(record)
    sealed[hash_field] = sha256_bytes(canonical_json_bytes(sealed))
    return sealed


def _verify_self_hash(record: Mapping[str, object], hash_field: str) -> str:
    observed = _sha256(record.get(hash_field), hash_field)
    unsigned = dict(record)
    unsigned.pop(hash_field, None)
    expected = sha256_bytes(canonical_json_bytes(unsigned))
    if observed != expected:
        _fail("RECORD_HASH_MISMATCH", f"{hash_field} does not seal the canonical record")
    return observed


def expected_attempt_directory(
    *, run_dir: Path, lineage_id: str, turn_number: int, attempt_number: int
) -> Path:
    return (
        Path(run_dir)
        / "lineages"
        / lineage_id
        / "turns"
        / f"turn-{turn_number:06d}"
        / f"attempt-{attempt_number:02d}"
    ).resolve(strict=False)


def expected_runtime_binding_path(
    *, run_dir: Path, lineage_id: str, turn_number: int, attempt_number: int
) -> Path:
    return expected_attempt_directory(
        run_dir=run_dir,
        lineage_id=lineage_id,
        turn_number=turn_number,
        attempt_number=attempt_number,
    ) / "runtime_binding.json"


def expected_applied_receipt_path(
    *, run_dir: Path, lineage_id: str, turn_number: int, attempt_number: int
) -> Path:
    return expected_attempt_directory(
        run_dir=run_dir,
        lineage_id=lineage_id,
        turn_number=turn_number,
        attempt_number=attempt_number,
    ) / "binding-applied.json"


def expected_codex_args_path(
    *, run_dir: Path, lineage_id: str, turn_number: int, attempt_number: int
) -> Path:
    return expected_attempt_directory(
        run_dir=run_dir,
        lineage_id=lineage_id,
        turn_number=turn_number,
        attempt_number=attempt_number,
    ) / "codex_args.json"


def _validate_codex_args(path: Path) -> list[str]:
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldRuntimeBindingError("CODEX_ARGS_INVALID", "codex args are not JSON") from exc
    if (
        not isinstance(parsed, list)
        or not parsed
        or any(not isinstance(item, str) or not item for item in parsed)
    ):
        _fail("CODEX_ARGS_INVALID", "codex args must be a non-empty string array")
    if canonical_json_bytes(parsed) != raw:
        _fail("CODEX_ARGS_NONCANONICAL", "codex args file must use canonical JSON bytes")
    forbidden_exact = {"--sandbox", "-s", "--add-dir", "--cd"}
    forbidden_fragments = (
        "dangerously-bypass-approvals-and-sandbox",
        "approval_policy",
        "sandbox_mode",
        "additional_writable_roots",
        "writable_roots",
        "sandbox_workspace_write",
    )
    for argument in parsed:
        lowered = argument.casefold()
        if lowered in forbidden_exact or lowered.startswith("--add-dir=") or any(
            fragment in lowered for fragment in forbidden_fragments
        ):
            _fail(
                "CODEX_ARGS_BOUNDARY_OVERRIDE",
                "codex args may not override sandbox, approval, or writable roots",
            )
    return parsed


_BINDING_KEYS = frozenset(
    {
        "schema",
        "authority",
        "completion_claim_allowed",
        "run_id",
        "run_dir",
        "account_slot",
        "lineage_id",
        "role",
        "workspace",
        "source_head",
        "turn_number",
        "attempt_number",
        "invocation_nonce",
        "binding_path",
        "applied_receipt_path",
        "codex_args_path",
        "codex_args_sha256",
        "frozen_launcher_path",
        "frozen_launcher_sha256",
        "controller_release_path",
        "controller_release_sha256",
        "controller_python",
        "controller_python_sha256",
        "runtime_binding_release_path",
        "runtime_binding_release_sha256",
        "migration_manifest_path",
        "migration_manifest_sha256",
        "migration_id",
        "base_manifest_path",
        "base_manifest_sha256",
        "effective_code_root",
        "effective_python_path",
        "effective_code_manifest_path",
        "effective_code_manifest_sha256",
        "effective_code_tree_sha256",
        "effective_code_owner_run_id",
        "effective_code_owner_lineage_id",
        "private_live_root",
        "live_seed_receipt_path",
        "live_seed_receipt_sha256",
        "python_path_order",
        "environment",
        "legacy_live_runtime_dependency",
        "cross_lineage_overlay_count",
        "binding_sha256",
    }
)


def build_world_runtime_binding(
    *,
    run_id: str,
    run_dir: Path,
    account_slot: str,
    lineage_id: str,
    role: str,
    workspace: Path,
    source_head: str,
    turn_number: int,
    attempt_number: int,
    invocation_nonce: str,
    codex_args_path: Path,
    codex_args_sha256: str,
    frozen_launcher_path: Path,
    frozen_launcher_sha256: str,
    controller_release_path: Path,
    controller_release_sha256: str,
    controller_python: Path,
    controller_python_sha256: str,
    runtime_binding_release_path: Path,
    runtime_binding_release_sha256: str,
    migration_manifest_path: Path,
    migration_manifest_sha256: str,
    migration_id: str,
    base_manifest_path: Path,
    base_manifest_sha256: str,
    effective_code_root: Path,
    effective_python_path: Path,
    effective_code_manifest_path: Path,
    effective_code_manifest_sha256: str,
    effective_code_tree_sha256: str,
    effective_code_owner_run_id: str,
    effective_code_owner_lineage_id: str,
    private_live_root: Path,
    live_seed_receipt_path: Path,
    live_seed_receipt_sha256: str,
) -> dict[str, Any]:
    """Build the exact binding for one child invocation."""

    run_root = Path(run_dir).resolve(strict=False)
    workspace_root = Path(workspace).resolve(strict=False)
    code_root = Path(effective_code_root).resolve(strict=False)
    python_path = Path(effective_python_path).resolve(strict=False)
    live_root = Path(private_live_root).resolve(strict=False)
    binding_path = expected_runtime_binding_path(
        run_dir=run_root,
        lineage_id=lineage_id,
        turn_number=turn_number,
        attempt_number=attempt_number,
    )
    receipt_path = expected_applied_receipt_path(
        run_dir=run_root,
        lineage_id=lineage_id,
        turn_number=turn_number,
        attempt_number=attempt_number,
    )
    core: dict[str, object] = {
        "schema": WORLD_RUNTIME_BINDING_SCHEMA,
        "authority": False,
        "completion_claim_allowed": False,
        "run_id": run_id,
        "run_dir": str(run_root),
        "account_slot": account_slot,
        "lineage_id": lineage_id,
        "role": role,
        "workspace": str(workspace_root),
        "source_head": source_head,
        "turn_number": turn_number,
        "attempt_number": attempt_number,
        "invocation_nonce": invocation_nonce,
        "binding_path": str(binding_path),
        "applied_receipt_path": str(receipt_path),
        "codex_args_path": str(Path(codex_args_path).resolve(strict=False)),
        "codex_args_sha256": codex_args_sha256,
        "frozen_launcher_path": str(Path(frozen_launcher_path).resolve(strict=False)),
        "frozen_launcher_sha256": frozen_launcher_sha256,
        "controller_release_path": str(Path(controller_release_path).resolve(strict=False)),
        "controller_release_sha256": controller_release_sha256,
        "controller_python": str(Path(controller_python).resolve(strict=False)),
        "controller_python_sha256": controller_python_sha256,
        "runtime_binding_release_path": str(
            Path(runtime_binding_release_path).resolve(strict=False)
        ),
        "runtime_binding_release_sha256": runtime_binding_release_sha256,
        "migration_manifest_path": str(Path(migration_manifest_path).resolve(strict=False)),
        "migration_manifest_sha256": migration_manifest_sha256,
        "migration_id": migration_id,
        "base_manifest_path": str(Path(base_manifest_path).resolve(strict=False)),
        "base_manifest_sha256": base_manifest_sha256,
        "effective_code_root": str(code_root),
        "effective_python_path": str(python_path),
        "effective_code_manifest_path": str(
            Path(effective_code_manifest_path).resolve(strict=False)
        ),
        "effective_code_manifest_sha256": effective_code_manifest_sha256,
        "effective_code_tree_sha256": effective_code_tree_sha256,
        "effective_code_owner_run_id": effective_code_owner_run_id,
        "effective_code_owner_lineage_id": effective_code_owner_lineage_id,
        "private_live_root": str(live_root),
        "live_seed_receipt_path": str(Path(live_seed_receipt_path).resolve(strict=False)),
        "live_seed_receipt_sha256": live_seed_receipt_sha256,
        "python_path_order": [str(python_path)],
        "environment": {
            "PYTHONPATH": str(python_path),
            "XINAO_WORLD_WORKSPACE": str(workspace_root),
            "XINAO_LIVE_REALITY_ROOT": str(live_root),
        },
        "legacy_live_runtime_dependency": False,
        "cross_lineage_overlay_count": 0,
    }
    return validate_world_runtime_binding(_seal(core, "binding_sha256"))


def validate_world_runtime_binding(value: Mapping[str, object]) -> dict[str, Any]:
    """Validate exact invocation identity, paths, external bytes, and environment."""

    raw = _mapping(value, "binding")
    _exact_keys(raw, _BINDING_KEYS, "binding")
    if raw["schema"] != WORLD_RUNTIME_BINDING_SCHEMA:
        _fail("SCHEMA_MISMATCH", "binding schema is unsupported")
    _false(raw["authority"], "authority")
    _false(raw["completion_claim_allowed"], "completion_claim_allowed")
    _verify_self_hash(raw, "binding_sha256")

    run_id = _text(raw["run_id"], "run_id")
    lineage_id = _text(raw["lineage_id"], "lineage_id")
    role = _text(raw["role"], "role")
    if role not in _ROLES:
        _fail("ROLE_INVALID", f"unsupported role: {role}")
    if (lineage_id == "root-main") != (role == "late_fusion_root"):
        _fail("ROLE_IDENTITY_MISMATCH", "root-main must be the only late_fusion_root")
    account_slot = _text(raw["account_slot"], "account_slot")
    if account_slot not in _ACCOUNT_SLOTS:
        _fail("ACCOUNT_SLOT_INVALID", "account_slot must be A or C")
    source_head = _text(raw["source_head"], "source_head")
    if not _SOURCE_HEAD_RE.fullmatch(source_head):
        _fail("SOURCE_HEAD_INVALID", "source_head must be a lowercase Git object id")
    turn_number = _positive_integer(raw["turn_number"], "turn_number")
    attempt_number = _positive_integer(raw["attempt_number"], "attempt_number")
    invocation_nonce = _text(raw["invocation_nonce"], "invocation_nonce")
    if not _NONCE_RE.fullmatch(invocation_nonce):
        _fail("INVOCATION_NONCE_INVALID", "invocation_nonce has unsupported syntax")

    run_dir = _path(raw["run_dir"], "run_dir", kind="directory")
    if run_dir.name != run_id:
        _fail("RUN_PATH_IDENTITY_MISMATCH", "run_dir leaf must equal run_id")
    workspace = _path(raw["workspace"], "workspace", kind="directory")
    if workspace.name != lineage_id:
        _fail("CROSS_LINEAGE_WORKSPACE", "workspace leaf must equal lineage_id")
    if _is_within(workspace, run_dir) or _is_within(run_dir, workspace):
        _fail("WRITE_DOMAIN_OVERLAP", "run control and lineage workspace must be disjoint")

    expected_binding = expected_runtime_binding_path(
        run_dir=run_dir,
        lineage_id=lineage_id,
        turn_number=turn_number,
        attempt_number=attempt_number,
    )
    binding_path = Path(_text(raw["binding_path"], "binding_path")).resolve(strict=False)
    if not _same_path(binding_path, expected_binding):
        _fail("BINDING_PATH_MISMATCH", "binding_path is not the exact attempt-local path")
    expected_applied = expected_applied_receipt_path(
        run_dir=run_dir,
        lineage_id=lineage_id,
        turn_number=turn_number,
        attempt_number=attempt_number,
    )
    applied_path = Path(_text(raw["applied_receipt_path"], "applied_receipt_path")).resolve(
        strict=False
    )
    if not _same_path(applied_path, expected_applied):
        _fail("APPLIED_RECEIPT_PATH_MISMATCH", "applied receipt must be binding-path sibling")
    expected_codex_args = expected_codex_args_path(
        run_dir=run_dir,
        lineage_id=lineage_id,
        turn_number=turn_number,
        attempt_number=attempt_number,
    )
    codex_args, codex_args_sha = _verify_file(
        raw["codex_args_path"], raw["codex_args_sha256"], "codex_args"
    )
    if not _same_path(codex_args, expected_codex_args):
        _fail("CODEX_ARGS_PATH_MISMATCH", "codex args must be the exact attempt sibling")
    _validate_codex_args(codex_args)

    launcher, launcher_sha = _verify_file(
        raw["frozen_launcher_path"], raw["frozen_launcher_sha256"], "frozen_launcher"
    )
    controller_release, controller_sha = _verify_file(
        raw["controller_release_path"],
        raw["controller_release_sha256"],
        "controller_release",
    )
    if not _strictly_within(launcher, run_dir) or not _strictly_within(
        controller_release, run_dir
    ):
        _fail("CONTROL_BODY_OUTSIDE_RUN", "frozen launcher and release must be inside run_dir")
    controller_python, controller_python_sha = _verify_file(
        raw["controller_python"],
        raw["controller_python_sha256"],
        "controller_python",
    )
    runtime_binding_release, runtime_binding_release_sha = _verify_file(
        raw["runtime_binding_release_path"],
        raw["runtime_binding_release_sha256"],
        "runtime_binding_release",
    )
    if not _strictly_within(runtime_binding_release, run_dir):
        _fail(
            "CONTROL_BODY_OUTSIDE_RUN",
            "runtime binding validator must be inside run_dir",
        )

    migration_manifest, migration_sha = _verify_file(
        raw["migration_manifest_path"],
        raw["migration_manifest_sha256"],
        "migration_manifest",
    )
    migration_id = _text(raw["migration_id"], "migration_id")
    migration_payload = _json_file(migration_manifest, "migration manifest")
    if migration_payload.get("schema") != _MIGRATION_SCHEMA:
        _fail("MIGRATION_MANIFEST_MISMATCH", "migration manifest schema is unsupported")
    if migration_payload.get("migration_id") != migration_id:
        _fail("MIGRATION_MANIFEST_MISMATCH", "migration_id is not sealed by its manifest")
    if migration_payload.get("source_deletion_permitted") is not False:
        _fail("MIGRATION_MANIFEST_MISMATCH", "migration manifest lost no-delete provenance")
    if migration_payload.get("live_reality_root_runtime_bindable") is not False:
        _fail("SHARED_LIVE_ROOT_BINDING_FORBIDDEN", "shared live root became runtime-bindable")
    world_compute_root = _path(
        migration_payload.get("world_compute_root"),
        "migration world_compute_root",
        kind="directory",
    )
    if _is_within(migration_manifest, workspace):
        _fail("MANIFEST_IN_WRITABLE_SCOPE", "migration manifest entered lineage workspace")
    base_manifest, base_manifest_sha = _verify_file(
        raw["base_manifest_path"], raw["base_manifest_sha256"], "base_manifest"
    )
    if _is_within(base_manifest, workspace):
        _fail("MANIFEST_IN_WRITABLE_SCOPE", "base manifest entered lineage workspace")
    base_bundle = _mapping(migration_payload.get("base_bundle"), "migration base_bundle")
    if (
        base_bundle.get("manifest_path") != str(base_manifest)
        or base_bundle.get("manifest_sha256") != base_manifest_sha
        or base_bundle.get("runtime_bindable") is not False
    ):
        _fail("BASE_MANIFEST_MISMATCH", "base manifest provenance changed or became runnable")

    code_root = _path(raw["effective_code_root"], "effective_code_root", kind="directory")
    if _is_within(code_root, workspace):
        _fail("WRITABLE_CODE_ROOT_FORBIDDEN", "effective code root entered lineage workspace")
    if _is_within(code_root, workspace / _LEGACY_LIVE_RELATIVE):
        _fail("LEGACY_LIVE_RUNTIME_DEPENDENCY", "effective code root reused legacy live path")
    effective_python = _path(
        raw["effective_python_path"], "effective_python_path", kind="directory"
    )
    if not _same_path(effective_python, code_root / "code"):
        _fail("EFFECTIVE_PYTHON_PATH_MISMATCH", "effective Python path must be code_root/code")
    effective_manifest, effective_manifest_sha = _verify_file(
        raw["effective_code_manifest_path"],
        raw["effective_code_manifest_sha256"],
        "effective_code_manifest",
    )
    if _is_within(effective_manifest, workspace):
        _fail("MANIFEST_IN_WRITABLE_SCOPE", "effective code manifest entered workspace")
    effective_tree_sha = _sha256(raw["effective_code_tree_sha256"], "effective_code_tree_sha256")
    effective_owner_run_id = _text(
        raw["effective_code_owner_run_id"], "effective_code_owner_run_id"
    )
    effective_owner_lineage_id = _text(
        raw["effective_code_owner_lineage_id"], "effective_code_owner_lineage_id"
    )
    if effective_owner_run_id != run_id or effective_owner_lineage_id != lineage_id:
        reason = (
            "ROOT_MAIN_BRANCH_OVERLAY_FORBIDDEN"
            if lineage_id == "root-main"
            else "CROSS_LINEAGE_EFFECTIVE_CODE"
        )
        _fail(reason, "effective code ownership differs from the exact invocation lineage")
    effective_payload = _json_file(effective_manifest, "effective code manifest")
    if (
        effective_payload.get("schema") != _EFFECTIVE_CODE_SCHEMA
        or effective_payload.get("payload_tree_sha256") != effective_tree_sha
        or effective_payload.get("base_fallback_permitted") is not False
    ):
        _fail(
            "EFFECTIVE_CODE_MANIFEST_MISMATCH",
            "effective code manifest does not seal its deletion-preserving tree",
        )
    if _verify_exact_effective_tree(code_root, effective_payload) != effective_tree_sha:
        _fail(
            "EFFECTIVE_CODE_TREE_HASH_MISMATCH",
            "effective code tree differs from the binding identity",
        )

    private_live = _path(raw["private_live_root"], "private_live_root", kind="directory")
    if not _strictly_within(private_live, workspace):
        _fail("PRIVATE_LIVE_ROOT_OUTSIDE_WORKSPACE", "private live root escaped workspace")
    if _is_within(private_live, workspace / _LEGACY_LIVE_RELATIVE):
        _fail("LEGACY_LIVE_RUNTIME_DEPENDENCY", "private live root reused xinao/reality/live")
    if any(part.casefold().startswith("pre203_") for part in private_live.parts):
        _fail(
            "CONCRETE_STORE_ROOT_FORBIDDEN",
            "private_live_root must be the parent of pre203_* stores",
        )
    live_seed, live_seed_sha = _verify_file(
        raw["live_seed_receipt_path"],
        raw["live_seed_receipt_sha256"],
        "live_seed_receipt",
    )
    if _is_within(live_seed, workspace):
        _fail("LIVE_SEED_RECEIPT_WRITABLE", "lineage child must not write seed receipt")
    if not _strictly_within(live_seed, world_compute_root):
        _fail(
            "LIVE_SEED_RECEIPT_OUTSIDE_COMPUTE_ROOT",
            "live seed receipt must be inside the manifest-bound world_compute_root",
        )

    overlays = migration_payload.get("workspace_overlays")
    if not isinstance(overlays, list) or any(not isinstance(item, Mapping) for item in overlays):
        _fail("MIGRATION_MANIFEST_MISMATCH", "workspace_overlays must be an object array")
    matching_views = [
        dict(item)
        for item in overlays
        if isinstance(item.get("workspace_root"), str)
        and _same_path(Path(str(item["workspace_root"])), workspace)
    ]
    if len(matching_views) != 1:
        reason = (
            "ROOT_MAIN_BRANCH_OVERLAY_FORBIDDEN"
            if lineage_id == "root-main"
            else "CROSS_LINEAGE_EFFECTIVE_CODE"
        )
        _fail(reason, "migration must contain exactly one view for the exact workspace")
    view = matching_views[0]
    private_contract = _mapping(
        view.get("private_live_materialization"), "migration private_live_materialization"
    )
    runtime_environment = _mapping(
        view.get("runtime_environment"), "migration runtime_environment"
    )
    expected_view_fields = {
        "workspace_key": effective_owner_lineage_id,
        "runtime_view": "lineage_effective_view_only",
        "python_path_order": [str(effective_python)],
        "effective_python_path": str(effective_python),
        "effective_code_root": str(code_root),
        "effective_code_payload_tree_sha256": effective_tree_sha,
        "effective_code_manifest_path": str(effective_manifest),
        "effective_code_manifest_sha256": effective_manifest_sha,
        "private_effective_live_root": str(private_live),
    }
    if any(view.get(key) != expected for key, expected in expected_view_fields.items()):
        _fail("CROSS_LINEAGE_EFFECTIVE_CODE", "binding differs from its exact migration view")
    if (
        private_contract.get("root") != str(private_live)
        or private_contract.get("receipt_path") != str(live_seed)
        or private_contract.get("receipt_sha256") != live_seed_sha
    ):
        _fail("LIVE_SEED_RECEIPT_MISMATCH", "private live seed receipt is not manifest-bound")
    if (
        runtime_environment.get("PYTHONPATH") != str(effective_python)
        or runtime_environment.get("XINAO_LIVE_REALITY_ROOT") != str(private_live)
        or runtime_environment.get("XINAO_WORLD_WORKSPACE") != str(workspace)
    ):
        _fail("ENVIRONMENT_MISMATCH", "migration runtime environment differs from binding")

    paths = raw["python_path_order"]
    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
        _fail("INPUT_INVALID", "python_path_order must be an ordered path array")
    normalized_paths = [
        str(_path(item, f"python_path_order[{index}]", kind="directory"))
        for index, item in enumerate(paths)
    ]
    expected_paths = [str(effective_python)]
    if normalized_paths != expected_paths:
        _fail(
            "PYTHON_PATH_ORDER_MISMATCH",
            "python_path_order must contain only the deletion-preserving effective code root",
        )

    environment = _mapping(raw["environment"], "environment")
    _exact_keys(environment, _ENVIRONMENT_NAMES, "environment")
    expected_environment = {
        "PYTHONPATH": str(effective_python),
        "XINAO_WORLD_WORKSPACE": str(workspace),
        "XINAO_LIVE_REALITY_ROOT": str(private_live),
    }
    if environment != expected_environment:
        _fail("ENVIRONMENT_MISMATCH", "environment is not the exact sealed path projection")
    _false(raw["legacy_live_runtime_dependency"], "legacy_live_runtime_dependency")
    _zero(raw["cross_lineage_overlay_count"], "cross_lineage_overlay_count")

    normalized: dict[str, Any] = {
        "schema": WORLD_RUNTIME_BINDING_SCHEMA,
        "authority": False,
        "completion_claim_allowed": False,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "account_slot": account_slot,
        "lineage_id": lineage_id,
        "role": role,
        "workspace": str(workspace),
        "source_head": source_head,
        "turn_number": turn_number,
        "attempt_number": attempt_number,
        "invocation_nonce": invocation_nonce,
        "binding_path": str(expected_binding),
        "applied_receipt_path": str(expected_applied),
        "codex_args_path": str(codex_args),
        "codex_args_sha256": codex_args_sha,
        "frozen_launcher_path": str(launcher),
        "frozen_launcher_sha256": launcher_sha,
        "controller_release_path": str(controller_release),
        "controller_release_sha256": controller_sha,
        "controller_python": str(controller_python),
        "controller_python_sha256": controller_python_sha,
        "runtime_binding_release_path": str(runtime_binding_release),
        "runtime_binding_release_sha256": runtime_binding_release_sha,
        "migration_manifest_path": str(migration_manifest),
        "migration_manifest_sha256": migration_sha,
        "migration_id": migration_id,
        "base_manifest_path": str(base_manifest),
        "base_manifest_sha256": base_manifest_sha,
        "effective_code_root": str(code_root),
        "effective_python_path": str(effective_python),
        "effective_code_manifest_path": str(effective_manifest),
        "effective_code_manifest_sha256": effective_manifest_sha,
        "effective_code_tree_sha256": effective_tree_sha,
        "effective_code_owner_run_id": effective_owner_run_id,
        "effective_code_owner_lineage_id": effective_owner_lineage_id,
        "private_live_root": str(private_live),
        "live_seed_receipt_path": str(live_seed),
        "live_seed_receipt_sha256": live_seed_sha,
        "python_path_order": expected_paths,
        "environment": expected_environment,
        "legacy_live_runtime_dependency": False,
        "cross_lineage_overlay_count": 0,
        "binding_sha256": raw["binding_sha256"],
    }
    if normalized != raw:
        _fail("BINDING_NONCANONICAL", "binding values are not in canonical normalized form")
    return normalized


def world_runtime_binding_bytes(value: Mapping[str, object]) -> bytes:
    return canonical_json_bytes(validate_world_runtime_binding(value))


def world_runtime_binding_file_sha256(value: Mapping[str, object]) -> str:
    return sha256_bytes(world_runtime_binding_bytes(value))


def validate_world_runtime_binding_bytes(
    raw: bytes, *, expected_file_sha256: str | None = None
) -> dict[str, Any]:
    observed = sha256_bytes(raw)
    if expected_file_sha256 is not None and observed != _sha256(
        expected_file_sha256, "expected_file_sha256"
    ):
        _fail("BINDING_FILE_HASH_MISMATCH", "runtime binding file bytes drifted")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldRuntimeBindingError("BINDING_FILE_INVALID", "binding bytes are not JSON") from exc
    binding = validate_world_runtime_binding(_mapping(parsed, "binding file"))
    if canonical_json_bytes(binding) != raw:
        _fail("BINDING_FILE_NONCANONICAL", "binding file is not canonical JSON")
    return binding


def environment_projection(value: Mapping[str, object]) -> dict[str, str]:
    return dict(validate_world_runtime_binding(value)["environment"])


_APPLIED_KEYS = frozenset(
    {
        "schema",
        "binding_schema",
        "run_id",
        "lineage_id",
        "role",
        "turn_number",
        "attempt_number",
        "invocation_nonce",
        "binding_path",
        "binding_sha256",
        "binding_file_sha256",
        "applied_receipt_path",
        "codex_args_path",
        "codex_args_sha256",
        "frozen_launcher_path",
        "frozen_launcher_sha256",
        "controller_release_path",
        "controller_release_sha256",
        "launcher_pid",
        "environment",
        "environment_sha256",
        "applied",
        "receipt_sha256",
    }
)


def build_world_runtime_binding_applied_receipt(
    *,
    binding: Mapping[str, object],
    binding_file_sha256: str,
    observed_environment: Mapping[str, object],
    launcher_pid: int,
) -> dict[str, Any]:
    """Seal an exact launcher observation for one invocation."""

    normalized = validate_world_runtime_binding(binding)
    binding_path = Path(normalized["binding_path"])
    if not binding_path.is_file():
        _fail("BINDING_FILE_MISSING", "attempt-local runtime binding file is missing")
    expected_binding_file_sha = _sha256(binding_file_sha256, "binding_file_sha256")
    binding_raw = binding_path.read_bytes()
    if sha256_bytes(binding_raw) != expected_binding_file_sha:
        _fail("BINDING_FILE_HASH_MISMATCH", "runtime binding changed before application")
    if validate_world_runtime_binding_bytes(
        binding_raw, expected_file_sha256=expected_binding_file_sha
    ) != normalized:
        _fail("BINDING_FILE_IDENTITY_MISMATCH", "runtime binding file changed identity")
    observed = _mapping(observed_environment, "observed_environment")
    _exact_keys(observed, _ENVIRONMENT_NAMES, "observed_environment")
    expected_environment = dict(normalized["environment"])
    if observed != expected_environment:
        _fail("ENVIRONMENT_MISMATCH", "launcher did not apply the sealed environment")
    pid = _positive_integer(launcher_pid, "launcher_pid")
    core: dict[str, object] = {
        "schema": WORLD_RUNTIME_APPLIED_RECEIPT_SCHEMA,
        "binding_schema": WORLD_RUNTIME_BINDING_SCHEMA,
        "run_id": normalized["run_id"],
        "lineage_id": normalized["lineage_id"],
        "role": normalized["role"],
        "turn_number": normalized["turn_number"],
        "attempt_number": normalized["attempt_number"],
        "invocation_nonce": normalized["invocation_nonce"],
        "binding_path": normalized["binding_path"],
        "binding_sha256": normalized["binding_sha256"],
        "binding_file_sha256": expected_binding_file_sha,
        "applied_receipt_path": normalized["applied_receipt_path"],
        "codex_args_path": normalized["codex_args_path"],
        "codex_args_sha256": normalized["codex_args_sha256"],
        "frozen_launcher_path": normalized["frozen_launcher_path"],
        "frozen_launcher_sha256": normalized["frozen_launcher_sha256"],
        "controller_release_path": normalized["controller_release_path"],
        "controller_release_sha256": normalized["controller_release_sha256"],
        "launcher_pid": pid,
        "environment": expected_environment,
        "environment_sha256": sha256_bytes(canonical_json_bytes(expected_environment)),
        "applied": True,
    }
    return validate_world_runtime_binding_applied_receipt(
        _seal(core, "receipt_sha256"),
        binding=normalized,
        binding_file_sha256=expected_binding_file_sha,
    )


def validate_world_runtime_binding_applied_receipt(
    value: Mapping[str, object] | None,
    *,
    binding: Mapping[str, object],
    binding_file_sha256: str,
) -> dict[str, Any]:
    if value is None:
        _fail("APPLIED_RECEIPT_MISSING", "binding-applied.json is required")
    normalized = validate_world_runtime_binding(binding)
    raw = _mapping(value, "applied receipt")
    _exact_keys(raw, _APPLIED_KEYS, "applied receipt")
    if raw["schema"] != WORLD_RUNTIME_APPLIED_RECEIPT_SCHEMA:
        _fail("SCHEMA_MISMATCH", "applied receipt schema is unsupported")
    if raw["binding_schema"] != WORLD_RUNTIME_BINDING_SCHEMA:
        _fail("SCHEMA_MISMATCH", "applied receipt binding schema is unsupported")
    _verify_self_hash(raw, "receipt_sha256")
    binding_path = Path(normalized["binding_path"])
    if not binding_path.is_file():
        _fail("BINDING_FILE_MISSING", "attempt-local runtime binding file is missing")
    expected_file_sha = _sha256(binding_file_sha256, "binding_file_sha256")
    binding_raw = binding_path.read_bytes()
    if sha256_bytes(binding_raw) != expected_file_sha:
        _fail("BINDING_FILE_HASH_MISMATCH", "runtime binding drifted after application")
    if validate_world_runtime_binding_bytes(
        binding_raw, expected_file_sha256=expected_file_sha
    ) != normalized:
        _fail("BINDING_FILE_IDENTITY_MISMATCH", "runtime binding no longer matches receipt")
    expected_environment = dict(normalized["environment"])
    expected = {
        "schema": WORLD_RUNTIME_APPLIED_RECEIPT_SCHEMA,
        "binding_schema": WORLD_RUNTIME_BINDING_SCHEMA,
        "run_id": normalized["run_id"],
        "lineage_id": normalized["lineage_id"],
        "role": normalized["role"],
        "turn_number": normalized["turn_number"],
        "attempt_number": normalized["attempt_number"],
        "invocation_nonce": normalized["invocation_nonce"],
        "binding_path": normalized["binding_path"],
        "binding_sha256": normalized["binding_sha256"],
        "binding_file_sha256": expected_file_sha,
        "applied_receipt_path": normalized["applied_receipt_path"],
        "codex_args_path": normalized["codex_args_path"],
        "codex_args_sha256": normalized["codex_args_sha256"],
        "frozen_launcher_path": normalized["frozen_launcher_path"],
        "frozen_launcher_sha256": normalized["frozen_launcher_sha256"],
        "controller_release_path": normalized["controller_release_path"],
        "controller_release_sha256": normalized["controller_release_sha256"],
        "launcher_pid": _positive_integer(raw["launcher_pid"], "launcher_pid"),
        "environment": expected_environment,
        "environment_sha256": sha256_bytes(canonical_json_bytes(expected_environment)),
        "applied": True,
        "receipt_sha256": raw["receipt_sha256"],
    }
    if raw != expected:
        _fail("APPLIED_RECEIPT_MISMATCH", "applied receipt drifted from exact invocation")
    return expected


def world_runtime_applied_receipt_bytes(
    value: Mapping[str, object],
    *,
    binding: Mapping[str, object],
    binding_file_sha256: str,
) -> bytes:
    return canonical_json_bytes(
        validate_world_runtime_binding_applied_receipt(
            value,
            binding=binding,
            binding_file_sha256=binding_file_sha256,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate one frozen world runtime binding")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-binding")
    verify.add_argument("--binding", type=Path, required=True)
    verify.add_argument("--expected-file-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        validate_world_runtime_binding_bytes(
            args.binding.read_bytes(),
            expected_file_sha256=args.expected_file_sha256,
        )
        return 0
    except (OSError, WorldRuntimeBindingError):
        return 2


__all__ = [
    "WORLD_RUNTIME_APPLIED_RECEIPT_SCHEMA",
    "WORLD_RUNTIME_BINDING_SCHEMA",
    "WorldRuntimeBindingError",
    "build_world_runtime_binding",
    "build_world_runtime_binding_applied_receipt",
    "canonical_json_bytes",
    "environment_projection",
    "expected_applied_receipt_path",
    "expected_attempt_directory",
    "expected_codex_args_path",
    "expected_runtime_binding_path",
    "sha256_bytes",
    "sha256_file",
    "validate_world_runtime_binding",
    "validate_world_runtime_binding_applied_receipt",
    "validate_world_runtime_binding_bytes",
    "world_runtime_applied_receipt_bytes",
    "world_runtime_binding_bytes",
    "world_runtime_binding_file_sha256",
]


if __name__ == "__main__":
    raise SystemExit(main())
