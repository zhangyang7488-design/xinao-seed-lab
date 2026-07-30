from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Sequence

DEFAULT_STATE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill")
MAX_CONTROL_BYTES = 512 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_BUNDLE_FILE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_TOTAL_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_FILES = 4096
MAX_BUNDLE_ENTRIES = 65536
RUNTIME_HANDOFF_TIMEOUT_SECONDS = 30.0
RUNTIME_REAP_TIMEOUT_SECONDS = 5.0
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 100000
RELEASE_RUNTIME_RELATIVE_PATH = Path("skill-bundle") / "scripts" / "xinao_runtime.py"
# Bound to the co-located bootstrap-migration companion. Tampering fails before execution.
# Update this whenever the candidate xinao_runtime.py bytes change.
EXPECTED_COMPANION_RUNTIME_SHA256 = (
    "f83c77d6d1262aa5082010daea3c47e5af70ab6039828c174b58b7f000921442"
)
RELEASE_ID_PATTERN = re.compile(r"^researcher-[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{16}$")
TXN_ID_PATTERN = re.compile(r"^xra_[0-9]{8}T[0-9]{6}_[0-9a-f]{16}$")
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HEX_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ACTIVE_REF_KEYS = {
    "release_id",
    "release_manifest_path",
    "release_manifest_sha256",
    "skill_bundle_manifest_sha256",
    "skill_bundle_tree_sha256",
    "capability_version",
    "package_version",
    "required_bootstrap_protocol",
    "activation_txn_id",
}
JOURNAL_KEYS = {
    "schema_version",
    "revision",
    "txn_id",
    "operation",
    "state",
    "from",
    "requested_to",
    "to",
    "expected_generation",
    "prepared_at",
    "updated_at",
    "switched_pointer_sha256",
    "canary",
    "failure_reason",
    "terminal_pointer_sha256",
}
MIGRATE_FROM_KEYS = {
    "legacy_pointer_sha256",
    "legacy_pointer",
    "previous_verified",
    "legacy_restore_path",
    "legacy_restore_manifest_sha256",
    "legacy_restore_tree_sha256",
}
LEGACY_POINTER_KEYS = {
    "schema_version",
    "release_id",
    "release_manifest_path",
    "release_manifest_sha256",
    "promoted_at",
    "previous_pointer_sha256",
    "previous_release_id",
    "previous_release_manifest_path",
    "previous_release_manifest_sha256",
}
PENDING_ACTIVATION_STATES = {
    "PREPARED",
    "POINTER_SWITCHED",
    "CANARY_STARTED",
    "ROLLBACK_POINTER_SWITCHED",
    "ROLLBACK_CANARY_STARTED",
}
TERMINAL_ACTIVATION_STATES = {"VERIFIED", "ROLLED_BACK"}
FORBIDDEN_RUNTIME_TOKENS = (
    "grok_worker_pool",
    "codex_task_runs",
    "selection_receipt",
    "common_contract",
    "integrated_bus",
)
RELEASE_KEYS = {
    "schema_version",
    "release_id",
    "package_version",
    "capability_id",
    "capability_version",
    "charter_version",
    "runtime_version",
    "release_identity_sha256",
    "source_identity",
    "skill_bundle_path",
    "skill_bundle_manifest_path",
    "skill_bundle_manifest_sha256",
    "skill_bundle_tree_sha256",
    "image_tag_observational",
    "image_id",
    "image_entrypoint",
    "image_labels",
    "skill_hashes",
    "required_bootstrap_protocol",
    "generic_worker_route_allowed",
    "state_namespace",
    "run_namespace",
}
SKILL_HASH_PATHS = {
    "skill_md_sha256": "SKILL.md",
    "skill_invoker_sha256": "scripts/xinao.py",
    "capability_registry_sha256": "references/capabilities.v1.json",
    "charter_sha256": "references/researcher-charter.v1.json",
    "output_schema_sha256": "references/researcher-output.v2.schema.json",
    "material_bundle_schema_sha256": "references/material-bundle.v1.schema.json",
    "runtime_lock_sha256": "references/researcher-runtime-lock.v1.json",
    "meta_sha256": "references/meta.md",
}
IMAGE_LABEL_KEYS = {
    "io.xinao.researcher.chain",
    "io.xinao.researcher.generic-worker-route",
    "io.xinao.researcher.grok-donor-image-id",
    "io.xinao.researcher.grok-donor-binary.sha256",
    "io.xinao.researcher.charter.sha256",
    "io.xinao.researcher.output-schema.sha256",
    "io.xinao.researcher.material-bundle-schema.sha256",
    "io.xinao.researcher.runtime-lock.sha256",
    "io.xinao.researcher.skill-invoker.sha256",
    "io.xinao.researcher.dockerfile.sha256",
    "io.xinao.researcher.entrypoint.sha256",
    "io.xinao.researcher.source-identity.sha256",
    "io.xinao.researcher.requested-model",
}


class BootstrapError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = str(detail)[:2000]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _strict_int(value: str) -> int:
    if len(value.lstrip("-")) > 128:
        raise ValueError("JSON integer exceeds 128 digits")
    return int(value)


def _strict_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON float forbidden")
    return parsed


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key forbidden: {key}")
        result[key] = value
    return result


def _validate_shape(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > MAX_JSON_DEPTH:
            raise ValueError(f"JSON depth exceeds {MAX_JSON_DEPTH}")
        if nodes > MAX_JSON_NODES:
            raise ValueError(f"JSON nodes exceed {MAX_JSON_NODES}")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _is_reparse_stat(value: os.stat_result) -> bool:
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


def _regular_control_bytes(path: Path, *, maximum: int = MAX_CONTROL_BYTES) -> bytes:
    try:
        if not os.path.lexists(path):
            raise BootstrapError("BOOTSTRAP_CONTROL_MISSING", str(path))
        before = os.lstat(path)
        if _is_reparse_stat(before) or not stat.S_ISREG(before.st_mode):
            raise BootstrapError("BOOTSTRAP_CONTROL_FILE_INVALID", str(path))
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened_before.st_mode):
                raise BootstrapError("BOOTSTRAP_CONTROL_FILE_INVALID", str(path))
            payload = stream.read(maximum + 1)
            opened_after = os.fstat(stream.fileno())
        after = os.lstat(path)
        if _is_reparse_stat(after) or not stat.S_ISREG(after.st_mode):
            raise BootstrapError("BOOTSTRAP_CONTROL_FILE_INVALID", str(path))
        identities = {
            (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
            for item in (before, opened_before, opened_after, after)
        }
        if len(identities) != 1 or len(payload) != after.st_size:
            raise BootstrapError("BOOTSTRAP_CONTROL_CHANGED", str(path))
        if len(payload) > maximum:
            raise BootstrapError("BOOTSTRAP_CONTROL_TOO_LARGE", str(path))
        return payload
    except BootstrapError:
        raise
    except OSError as exc:
        raise BootstrapError("BOOTSTRAP_CONTROL_INVALID", f"{path}: {exc}") from exc


def _load_json_with_identity(
    path: Path, *, maximum: int = MAX_CONTROL_BYTES
) -> tuple[dict[str, Any], str]:
    payload = _regular_control_bytes(path, maximum=maximum)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number forbidden: {token}")
            ),
            parse_int=_strict_int,
            parse_float=_strict_float,
            object_pairs_hook=_strict_object,
        )
        _validate_shape(value)
    except BootstrapError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise BootstrapError("BOOTSTRAP_CONTROL_INVALID", f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BootstrapError("BOOTSTRAP_CONTROL_INVALID", f"object required: {path}")
    return value, _sha256_bytes(payload)


def _load_json(path: Path) -> dict[str, Any]:
    return _load_json_with_identity(path)[0]


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _require_plain_directory(path: Path, reason_code: str) -> None:
    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise BootstrapError(reason_code, f"{path}: {exc}") from exc
    if _is_reparse_stat(observed) or not stat.S_ISDIR(observed.st_mode):
        raise BootstrapError(reason_code, str(path))


def _validate_active_ref_shape(
    value: object,
    *,
    state_root: Path,
    reason_code: str = "RELEASE_REF_INVALID",
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != ACTIVE_REF_KEYS:
        raise BootstrapError(reason_code, str(value)[:2000])
    release_id = value.get("release_id")
    txn_id = value.get("activation_txn_id")
    if not isinstance(release_id, str) or RELEASE_ID_PATTERN.fullmatch(release_id) is None:
        raise BootstrapError("RELEASE_IDENTITY_INVALID", str(release_id))
    if not isinstance(txn_id, str) or TXN_ID_PATTERN.fullmatch(txn_id) is None:
        raise BootstrapError("ACTIVATION_TRANSACTION_ID_INVALID", str(txn_id))
    manifest_value = value.get("release_manifest_path")
    if not isinstance(manifest_value, str):
        raise BootstrapError("RELEASE_MANIFEST_PATH_INVALID", str(manifest_value))
    manifest_path = Path(manifest_value)
    expected_manifest_path = (
        state_root / "researcher_container" / "releases" / release_id / "release.json"
    )
    if _normalized_path(manifest_path) != _normalized_path(expected_manifest_path):
        raise BootstrapError("RELEASE_MANIFEST_PATH_INVALID", str(manifest_path))
    for key in (
        "release_manifest_sha256",
        "skill_bundle_manifest_sha256",
        "skill_bundle_tree_sha256",
    ):
        observed = value.get(key)
        if not isinstance(observed, str) or HEX_SHA256_PATTERN.fullmatch(observed) is None:
            raise BootstrapError("RELEASE_REF_INVALID", key)
    for key in ("capability_version", "package_version"):
        observed = value.get(key)
        if not isinstance(observed, str) or SEMVER_PATTERN.fullmatch(observed) is None:
            raise BootstrapError("RELEASE_REF_INVALID", key)
    if value.get("required_bootstrap_protocol") != 2:
        raise BootstrapError("BOOTSTRAP_PROTOCOL_UNSUPPORTED", release_id)
    return value


def _validate_journal_shape(
    journal: dict[str, Any],
    *,
    journal_path: Path,
    state_root: Path,
) -> None:
    if (
        set(journal) != JOURNAL_KEYS
        or journal.get("schema_version") != "xinao.researcher_activation_journal.v1"
    ):
        raise BootstrapError("ACTIVATION_JOURNAL_SCHEMA_INVALID", str(journal_path))
    txn_id = journal.get("txn_id")
    if not isinstance(txn_id, str) or TXN_ID_PATTERN.fullmatch(txn_id) is None:
        raise BootstrapError("ACTIVATION_TRANSACTION_ID_INVALID", str(txn_id))
    expected_path = (
        state_root / "researcher_container" / "transactions" / txn_id / "activation.v1.json"
    )
    if _normalized_path(journal_path) != _normalized_path(expected_path):
        raise BootstrapError("ACTIVATION_TRANSACTION_BINDING_MISMATCH", str(journal_path))
    revision = journal.get("revision")
    if type(revision) is not int or revision < 1:
        raise BootstrapError("ACTIVATION_JOURNAL_REVISION_INVALID", str(revision))
    if journal.get("operation") not in {"ACTIVATE", "ROLLBACK", "MIGRATE"}:
        raise BootstrapError("ACTIVATION_OPERATION_INVALID", str(journal.get("operation")))
    valid_states = PENDING_ACTIVATION_STATES | TERMINAL_ACTIVATION_STATES | {"RECOVERY_CONFLICT"}
    if journal.get("state") not in valid_states:
        raise BootstrapError("ACTIVATION_STATE_INVALID", str(journal.get("state")))
    generation = journal.get("expected_generation")
    if type(generation) is not int or generation < 1:
        raise BootstrapError("ACTIVATION_GENERATION_INVALID", str(generation))
    for key in ("prepared_at", "updated_at"):
        observed = journal.get(key)
        if not isinstance(observed, str) or not observed or len(observed) > 128:
            raise BootstrapError("ACTIVATION_JOURNAL_SCHEMA_INVALID", key)
    requested_to = _validate_active_ref_shape(journal.get("requested_to"), state_root=state_root)
    target = _validate_active_ref_shape(journal.get("to"), state_root=state_root)
    if requested_to.get("activation_txn_id") != txn_id or target.get("activation_txn_id") != txn_id:
        raise BootstrapError("ACTIVATION_TRANSACTION_BINDING_MISMATCH", txn_id)
    from_value = journal.get("from")
    if journal.get("operation") == "MIGRATE":
        # Terminal MIGRATE journals remain the active activation witness after protocol
        # transition; ordinary fence formation must accept their legacy restore from-shape.
        if not isinstance(from_value, dict) or set(from_value) != MIGRATE_FROM_KEYS:
            raise BootstrapError("ACTIVATION_SOURCE_INVALID", txn_id)
        legacy_pointer_sha256 = from_value.get("legacy_pointer_sha256")
        if (
            not isinstance(legacy_pointer_sha256, str)
            or HEX_SHA256_PATTERN.fullmatch(legacy_pointer_sha256) is None
        ):
            raise BootstrapError("ACTIVATION_SOURCE_INVALID", "legacy_pointer_sha256")
        legacy_pointer = from_value.get("legacy_pointer")
        if not isinstance(legacy_pointer, dict) or set(legacy_pointer) != LEGACY_POINTER_KEYS:
            raise BootstrapError("ACTIVATION_SOURCE_INVALID", "legacy_pointer")
        if legacy_pointer.get("schema_version") != "xinao.researcher_current_pointer.v1":
            raise BootstrapError("ACTIVATION_SOURCE_INVALID", "legacy_pointer.schema_version")
        if from_value.get("previous_verified") is not None:
            _validate_active_ref_shape(from_value.get("previous_verified"), state_root=state_root)
        for key in (
            "legacy_restore_path",
            "legacy_restore_manifest_sha256",
            "legacy_restore_tree_sha256",
        ):
            observed = from_value.get(key)
            if not isinstance(observed, str) or not observed:
                raise BootstrapError("ACTIVATION_SOURCE_INVALID", key)
        if (
            HEX_SHA256_PATTERN.fullmatch(str(from_value.get("legacy_restore_manifest_sha256", "")))
            is None
            or HEX_SHA256_PATTERN.fullmatch(str(from_value.get("legacy_restore_tree_sha256", "")))
            is None
        ):
            raise BootstrapError("ACTIVATION_SOURCE_INVALID", "legacy_restore_hash")
        restore_path = Path(str(from_value.get("legacy_restore_path", "")))
        if not restore_path.is_absolute():
            raise BootstrapError("ACTIVATION_SOURCE_INVALID", "legacy_restore_path")
    elif from_value is not None:
        if not isinstance(from_value, dict) or set(from_value) != {
            "generation",
            "pointer_sha256",
            "active",
            "previous_verified",
        }:
            raise BootstrapError("ACTIVATION_SOURCE_INVALID", txn_id)
        source_generation = from_value.get("generation")
        if type(source_generation) is not int or source_generation < 1:
            raise BootstrapError("ACTIVATION_SOURCE_INVALID", "generation")
        source_pointer_sha256 = from_value.get("pointer_sha256")
        if (
            not isinstance(source_pointer_sha256, str)
            or HEX_SHA256_PATTERN.fullmatch(source_pointer_sha256) is None
        ):
            raise BootstrapError("ACTIVATION_SOURCE_INVALID", "pointer_sha256")
        _validate_active_ref_shape(from_value.get("active"), state_root=state_root)
        if from_value.get("previous_verified") is not None:
            _validate_active_ref_shape(from_value.get("previous_verified"), state_root=state_root)
    for key in ("switched_pointer_sha256", "terminal_pointer_sha256"):
        observed = journal.get(key)
        if observed is not None and (
            not isinstance(observed, str) or HEX_SHA256_PATTERN.fullmatch(observed) is None
        ):
            raise BootstrapError("ACTIVATION_JOURNAL_SCHEMA_INVALID", key)
    if journal.get("canary") is not None and not isinstance(journal.get("canary"), dict):
        raise BootstrapError("ACTIVATION_JOURNAL_SCHEMA_INVALID", "canary")
    if journal.get("failure_reason") is not None and not isinstance(
        journal.get("failure_reason"), dict
    ):
        raise BootstrapError("ACTIVATION_JOURNAL_SCHEMA_INVALID", "failure_reason")


def _release_identity_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    source_identity = manifest.get("source_identity") or {}
    return {
        "package_version": manifest.get("package_version"),
        "capability_id": manifest.get("capability_id"),
        "capability_version": manifest.get("capability_version"),
        "charter_version": manifest.get("charter_version"),
        "runtime_version": manifest.get("runtime_version"),
        "grok_donor_image_id": source_identity.get("grok_donor_image_id"),
        "grok_donor_binary_sha256": source_identity.get("grok_donor_binary_sha256"),
        "skill_bundle_tree_sha256": manifest.get("skill_bundle_tree_sha256"),
        "image_id": manifest.get("image_id"),
        "image_entrypoint": manifest.get("image_entrypoint"),
        "image_labels": manifest.get("image_labels"),
        "required_bootstrap_protocol": manifest.get("required_bootstrap_protocol"),
        "generic_worker_route_allowed": manifest.get("generic_worker_route_allowed"),
        "state_namespace": manifest.get("state_namespace"),
        "run_namespace": manifest.get("run_namespace"),
    }


def _validate_release_manifest_shape(
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
    state_root: Path,
) -> None:
    if (
        set(manifest) != RELEASE_KEYS
        or manifest.get("schema_version") != "xinao.researcher_release.v2"
    ):
        raise BootstrapError("RELEASE_SCHEMA_INVALID", str(manifest_path))
    package_version = manifest.get("package_version")
    capability_version = manifest.get("capability_version")
    charter_version = manifest.get("charter_version")
    runtime_version = manifest.get("runtime_version")
    if not isinstance(package_version, str) or SEMVER_PATTERN.fullmatch(package_version) is None:
        raise BootstrapError("SKILL_VERSION_INVALID", str(package_version))
    if (
        not isinstance(capability_version, str)
        or SEMVER_PATTERN.fullmatch(capability_version) is None
        or capability_version != charter_version
        or capability_version != runtime_version
    ):
        raise BootstrapError(
            "RESEARCHER_VERSION_IDENTITY_MISMATCH",
            f"capability={capability_version} charter={charter_version} runtime={runtime_version}",
        )
    if manifest.get("capability_id") != "researcher-container":
        raise BootstrapError(
            "RELEASE_CAPABILITY_IDENTITY_INVALID", str(manifest.get("capability_id"))
        )
    source_identity = manifest.get("source_identity")
    if not isinstance(source_identity, dict) or set(source_identity) != {
        "source_commit",
        "source_tree",
        "source_dirty",
        "grok_donor_image_id",
        "grok_donor_binary_sha256",
    }:
        raise BootstrapError("RELEASE_SOURCE_IDENTITY_INVALID", str(manifest_path))
    if source_identity.get("source_dirty") is not False:
        raise BootstrapError("DIRTY_RELEASE_ACTIVATION_FORBIDDEN", str(manifest_path))
    for key in ("source_commit", "source_tree"):
        observed = source_identity.get(key)
        if not isinstance(observed, str) or re.fullmatch(r"[0-9a-f]{40,64}", observed) is None:
            raise BootstrapError("RELEASE_SOURCE_IDENTITY_INVALID", key)
    donor_id = source_identity.get("grok_donor_image_id")
    if not isinstance(donor_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", donor_id) is None:
        raise BootstrapError("RELEASE_DONOR_IDENTITY_MISSING", str(donor_id))
    donor_binary_sha256 = source_identity.get("grok_donor_binary_sha256")
    if (
        not isinstance(donor_binary_sha256, str)
        or HEX_SHA256_PATTERN.fullmatch(donor_binary_sha256) is None
    ):
        raise BootstrapError(
            "RELEASE_DONOR_BINARY_IDENTITY_MISSING", str(donor_binary_sha256)
        )
    if (
        manifest.get("required_bootstrap_protocol") != 2
        or manifest.get("generic_worker_route_allowed") is not False
    ):
        raise BootstrapError("RELEASE_CHAIN_CLASS_INVALID", str(manifest_path))
    if (
        manifest.get("state_namespace") != "xinao_skill/researcher_container"
        or manifest.get("run_namespace") != "xinao_researcher"
    ):
        raise BootstrapError("CROSS_CHAIN_NAMESPACE_FORBIDDEN", str(manifest_path))
    for value in (manifest.get("state_namespace"), manifest.get("run_namespace")):
        normalized = str(value).lower().replace("-", "_")
        if any(token in normalized for token in FORBIDDEN_RUNTIME_TOKENS):
            raise BootstrapError("CROSS_CHAIN_NAMESPACE_FORBIDDEN", str(value))
    image_id = manifest.get("image_id")
    if not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise BootstrapError("RELEASE_IMAGE_IDENTITY_INVALID", str(image_id))
    if manifest.get("image_entrypoint") != [
        "python",
        "-I",
        "/opt/xinao-researcher/entrypoint.py",
    ]:
        raise BootstrapError("RELEASE_IMAGE_IDENTITY_INVALID", "image_entrypoint")
    image_tag = manifest.get("image_tag_observational")
    if not isinstance(image_tag, str) or not image_tag or len(image_tag) > 256:
        raise BootstrapError("RELEASE_IMAGE_IDENTITY_INVALID", "image_tag_observational")
    labels = manifest.get("image_labels")
    if not isinstance(labels, dict) or set(labels) != IMAGE_LABEL_KEYS:
        raise BootstrapError("RELEASE_IMAGE_IDENTITY_INVALID", "image_labels")
    hashes = manifest.get("skill_hashes")
    if not isinstance(hashes, dict) or set(hashes) != set(SKILL_HASH_PATHS):
        raise BootstrapError("RELEASE_SKILL_HASHES_MISMATCH", str(manifest_path))
    for key, value in hashes.items():
        if not isinstance(value, str) or HEX_SHA256_PATTERN.fullmatch(value) is None:
            raise BootstrapError("RELEASE_SKILL_HASHES_MISMATCH", key)
    source_identity_sha256 = _sha256_bytes(_canonical_bytes(source_identity))
    expected_labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": donor_id,
        "io.xinao.researcher.grok-donor-binary.sha256": donor_binary_sha256,
        "io.xinao.researcher.charter.sha256": hashes["charter_sha256"],
        "io.xinao.researcher.output-schema.sha256": hashes["output_schema_sha256"],
        "io.xinao.researcher.material-bundle-schema.sha256": hashes[
            "material_bundle_schema_sha256"
        ],
        "io.xinao.researcher.runtime-lock.sha256": hashes["runtime_lock_sha256"],
        "io.xinao.researcher.skill-invoker.sha256": hashes["skill_invoker_sha256"],
        "io.xinao.researcher.dockerfile.sha256": labels.get(
            "io.xinao.researcher.dockerfile.sha256"
        ),
        "io.xinao.researcher.entrypoint.sha256": labels.get(
            "io.xinao.researcher.entrypoint.sha256"
        ),
        "io.xinao.researcher.source-identity.sha256": source_identity_sha256,
        "io.xinao.researcher.requested-model": "grok-4.5",
    }
    if labels != expected_labels:
        raise BootstrapError("RELEASE_IMAGE_IDENTITY_INVALID", "image_labels")
    for key in (
        "io.xinao.researcher.dockerfile.sha256",
        "io.xinao.researcher.entrypoint.sha256",
    ):
        if HEX_SHA256_PATTERN.fullmatch(str(labels.get(key, ""))) is None:
            raise BootstrapError("RELEASE_IMAGE_IDENTITY_INVALID", key)
    for key in (
        "skill_bundle_manifest_sha256",
        "skill_bundle_tree_sha256",
        "release_identity_sha256",
    ):
        observed = manifest.get(key)
        if not isinstance(observed, str) or HEX_SHA256_PATTERN.fullmatch(observed) is None:
            raise BootstrapError("RELEASE_IDENTITY_MISMATCH", key)
    identity_sha256 = _sha256_bytes(_canonical_bytes(_release_identity_payload(manifest)))
    if manifest.get("release_identity_sha256") != identity_sha256:
        raise BootstrapError("RELEASE_IDENTITY_MISMATCH", str(manifest_path))
    expected_release_id = f"researcher-{capability_version}-{identity_sha256[:16]}"
    if manifest.get("release_id") != expected_release_id:
        raise BootstrapError("RELEASE_IDENTITY_INVALID", str(manifest.get("release_id")))
    expected_manifest_path = (
        state_root / "researcher_container" / "releases" / expected_release_id / "release.json"
    )
    if _normalized_path(manifest_path) != _normalized_path(expected_manifest_path):
        raise BootstrapError("RELEASE_MANIFEST_PATH_INVALID", str(manifest_path))


def _validate_release_skill_hashes(manifest: dict[str, Any], bundle_root: Path) -> None:
    expected = manifest["skill_hashes"]
    observed: dict[str, str] = {}
    for key, relative in SKILL_HASH_PATHS.items():
        payload = _regular_control_bytes(
            bundle_root / Path(relative), maximum=MAX_BUNDLE_FILE_BYTES
        )
        observed[key] = _sha256_bytes(payload)
    if observed != expected:
        raise BootstrapError("RELEASE_SKILL_HASHES_MISMATCH", str(bundle_root))


@contextmanager
def _activation_lock(state_root: Path):
    _require_plain_directory(state_root, "STATE_ROOT_INVALID")
    _require_plain_directory(state_root / "researcher_container", "STATE_ROOT_INVALID")
    lock_path = state_root / "researcher_container" / ".activation.lock"
    try:
        before = os.lstat(lock_path)
    except OSError as exc:
        raise BootstrapError("ACTIVATION_LOCK_MISSING", f"{lock_path}: {exc}") from exc
    if (
        _is_reparse_stat(before)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size < 1
    ):
        raise BootstrapError("ACTIVATION_LOCK_INVALID", str(lock_path))
    try:
        stream = lock_path.open("r+b", buffering=0)
    except OSError as exc:
        raise BootstrapError("ACTIVATION_LOCK_OPEN_FAILED", f"{lock_path}: {exc}") from exc
    locked = False
    deadline = time.monotonic() + 30.0
    try:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise BootstrapError("ACTIVATION_LOCK_CHANGED", str(lock_path))
        while not locked:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise BootstrapError("ACTIVATION_LOCK_TIMEOUT", f"{lock_path}: {exc}") from exc
                time.sleep(0.05)
        after = os.lstat(lock_path)
        if _is_reparse_stat(after) or (after.st_dev, after.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise BootstrapError("ACTIVATION_LOCK_CHANGED", str(lock_path))
        yield
    finally:
        if locked:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        stream.close()


def _pending_activation_journals(state_root: Path) -> list[dict[str, Any]]:
    transactions_root = state_root / "researcher_container" / "transactions"
    if not os.path.lexists(transactions_root):
        return []
    _require_plain_directory(transactions_root, "TRANSACTION_ROOT_INVALID")
    pending: list[dict[str, Any]] = []
    entries: list[os.DirEntry[str]] = []
    try:
        with os.scandir(transactions_root) as iterator:
            for entry in iterator:
                entries.append(entry)
                if len(entries) > 10000:
                    raise BootstrapError("TRANSACTION_SET_TOO_LARGE", str(transactions_root))
    except BootstrapError:
        raise
    except OSError as exc:
        raise BootstrapError("TRANSACTION_ROOT_INVALID", f"{transactions_root}: {exc}") from exc
    entries.sort(key=lambda item: item.name)
    for entry in entries:
        try:
            entry_stat = os.lstat(entry.path)
        except OSError as exc:
            raise BootstrapError("TRANSACTION_ENTRY_INVALID", f"{entry.path}: {exc}") from exc
        if _is_reparse_stat(entry_stat):
            raise BootstrapError("TRANSACTION_REPARSE_FORBIDDEN", entry.path)
        if not stat.S_ISDIR(entry_stat.st_mode):
            raise BootstrapError("TRANSACTION_ENTRY_INVALID", entry.path)
        journal_path = Path(entry.path) / "activation.v1.json"
        if not os.path.lexists(journal_path):
            continue
        if TXN_ID_PATTERN.fullmatch(entry.name) is None:
            raise BootstrapError("ACTIVATION_TRANSACTION_ID_INVALID", entry.name)
        journal = _load_json(journal_path)
        _validate_journal_shape(
            journal,
            journal_path=journal_path,
            state_root=state_root,
        )
        if journal.get("state") == "RECOVERY_CONFLICT":
            raise BootstrapError("RECOVERY_CONFLICT", str(journal.get("txn_id", "")))
        if journal.get("state") not in TERMINAL_ACTIVATION_STATES:
            pending.append(journal)
    return pending


def _validate_bundle(
    *,
    release_root: Path,
    manifest: dict[str, Any],
    active: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    expected_bundle_root = release_root / "skill-bundle"
    expected_manifest_path = release_root / "skill-bundle.manifest.json"
    bundle_root = Path(str(manifest.get("skill_bundle_path", "")))
    bundle_manifest_path = Path(str(manifest.get("skill_bundle_manifest_path", "")))
    if _normalized_path(bundle_root) != _normalized_path(expected_bundle_root):
        raise BootstrapError("SKILL_BUNDLE_PATH_INVALID", str(bundle_root))
    if _normalized_path(bundle_manifest_path) != _normalized_path(expected_manifest_path):
        raise BootstrapError("SKILL_BUNDLE_MANIFEST_PATH_INVALID", str(bundle_manifest_path))
    _require_plain_directory(release_root.parent, "RELEASE_ROOT_INVALID")
    _require_plain_directory(release_root, "RELEASE_ROOT_INVALID")
    bundle_manifest, bundle_manifest_sha256 = _load_json_with_identity(
        bundle_manifest_path, maximum=MAX_MANIFEST_BYTES
    )
    expected_manifest_sha256 = manifest.get("skill_bundle_manifest_sha256")
    if (
        bundle_manifest_sha256 != expected_manifest_sha256
        or active.get("skill_bundle_manifest_sha256") != expected_manifest_sha256
    ):
        raise BootstrapError("SKILL_BUNDLE_MANIFEST_IDENTITY_MISMATCH", str(bundle_manifest_path))
    if bundle_manifest.get("schema_version") != "xinao.skill_bundle_manifest.v1":
        raise BootstrapError("SKILL_BUNDLE_MANIFEST_SCHEMA_INVALID", str(bundle_manifest_path))
    if set(bundle_manifest) != {
        "schema_version",
        "skill_id",
        "package_version",
        "files",
        "tree_sha256",
    }:
        raise BootstrapError("SKILL_BUNDLE_MANIFEST_SHAPE_INVALID", str(bundle_manifest_path))
    if bundle_manifest.get("skill_id") != "xinao":
        raise BootstrapError("SKILL_BUNDLE_IDENTITY_INVALID", str(bundle_manifest_path))
    if bundle_manifest.get("package_version") != manifest.get("package_version"):
        raise BootstrapError("SKILL_BUNDLE_VERSION_MISMATCH", str(bundle_manifest_path))
    files = bundle_manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_BUNDLE_FILES:
        raise BootstrapError("SKILL_BUNDLE_INVENTORY_INVALID", str(bundle_manifest_path))
    expected_rows: dict[str, dict[str, Any]] = {}
    ordered_paths: list[str] = []
    for row in files:
        if not isinstance(row, dict) or set(row) != {
            "relative_path",
            "type",
            "size",
            "sha256",
        }:
            raise BootstrapError("SKILL_BUNDLE_INVENTORY_INVALID", str(row)[:500])
        relative = row.get("relative_path")
        size = row.get("size")
        digest = row.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or row.get("type") != "file"
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or relative in expected_rows
        ):
            raise BootstrapError("SKILL_BUNDLE_INVENTORY_INVALID", str(row)[:500])
        ordered_paths.append(relative)
        expected_rows[relative] = row
    if ordered_paths != sorted(ordered_paths):
        raise BootstrapError("SKILL_BUNDLE_INVENTORY_ORDER_INVALID", str(bundle_manifest_path))
    normalized_paths = [os.path.normcase(value) for value in ordered_paths]
    if len(normalized_paths) != len(set(normalized_paths)):
        raise BootstrapError("SKILL_BUNDLE_PATH_COLLISION", str(bundle_manifest_path))
    try:
        root_stat = os.lstat(bundle_root)
    except OSError as exc:
        raise BootstrapError("SKILL_BUNDLE_ROOT_INVALID", f"{bundle_root}: {exc}") from exc
    if _is_reparse_stat(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise BootstrapError("SKILL_BUNDLE_ROOT_INVALID", str(bundle_root))
    observed: dict[str, tuple[int, str]] = {}
    expected_directories: set[str] = set()
    for relative in expected_rows:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    observed_directories: set[str] = set()
    total_bytes = 0
    stack: list[tuple[Path, str]] = [(bundle_root, "")]
    nodes = 0
    while stack:
        directory, prefix = stack.pop()
        entries: list[os.DirEntry[str]] = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    entries.append(entry)
                    if nodes + len(entries) > MAX_BUNDLE_ENTRIES:
                        raise BootstrapError("SKILL_BUNDLE_TOO_MANY_ENTRIES", str(bundle_root))
            entries.sort(key=lambda item: item.name)
        except BootstrapError:
            raise
        except OSError as exc:
            raise BootstrapError("SKILL_BUNDLE_READ_FAILED", f"{directory}: {exc}") from exc
        for entry in entries:
            nodes += 1
            if nodes > MAX_BUNDLE_ENTRIES:
                raise BootstrapError("SKILL_BUNDLE_TOO_MANY_ENTRIES", str(bundle_root))
            try:
                entry_stat = os.lstat(entry.path)
            except OSError as exc:
                raise BootstrapError("SKILL_BUNDLE_READ_FAILED", f"{entry.path}: {exc}") from exc
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            relative = relative.replace("\\", "/")
            if _is_reparse_stat(entry_stat):
                raise BootstrapError("SKILL_BUNDLE_REPARSE_FORBIDDEN", relative)
            if stat.S_ISDIR(entry_stat.st_mode):
                observed_directories.add(relative)
                stack.append((Path(entry.path), relative))
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise BootstrapError("SKILL_BUNDLE_ENTRY_INVALID", relative)
            if entry_stat.st_nlink != 1:
                raise BootstrapError("SKILL_BUNDLE_HARDLINK_FORBIDDEN", relative)
            payload = _regular_control_bytes(Path(entry.path), maximum=MAX_BUNDLE_FILE_BYTES)
            total_bytes += len(payload)
            if total_bytes > MAX_BUNDLE_TOTAL_BYTES:
                raise BootstrapError("SKILL_BUNDLE_TOO_LARGE", str(bundle_root))
            observed[relative] = (len(payload), _sha256_bytes(payload))
    if set(observed) != set(expected_rows) or observed_directories != expected_directories:
        raise BootstrapError("SKILL_BUNDLE_FILE_SET_MISMATCH", str(bundle_root))
    for relative, (size, digest) in observed.items():
        row = expected_rows[relative]
        if row["size"] != size or row["sha256"] != digest:
            raise BootstrapError("SKILL_BUNDLE_FILE_IDENTITY_MISMATCH", relative)
    tree_sha256 = _sha256_bytes(_canonical_bytes(files))
    if (
        tree_sha256 != bundle_manifest.get("tree_sha256")
        or tree_sha256 != manifest.get("skill_bundle_tree_sha256")
        or tree_sha256 != active.get("skill_bundle_tree_sha256")
    ):
        raise BootstrapError("SKILL_BUNDLE_TREE_IDENTITY_MISMATCH", str(bundle_root))
    return bundle_root, bundle_manifest


def _runtime_entry_locked(
    argv: Sequence[str], state_root: Path
) -> tuple[Path, bytes, dict[str, Any]]:
    pointer_path = state_root / "researcher_container" / "current.json"
    pointer, pointer_sha256 = _load_json_with_identity(pointer_path)
    if pointer.get("schema_version") != "xinao.researcher_current_pointer.v2":
        raise BootstrapError("BOOTSTRAP_MIGRATION_REQUIRED", str(pointer_path))
    if set(pointer) != {
        "schema_version",
        "generation",
        "active",
        "previous_verified",
        "switched_at",
    }:
        raise BootstrapError("CURRENT_POINTER_SCHEMA_INVALID", str(pointer_path))
    generation = pointer.get("generation")
    if type(generation) is not int or generation < 1:
        raise BootstrapError("CURRENT_POINTER_GENERATION_INVALID", str(generation))
    switched_at = pointer.get("switched_at")
    if not isinstance(switched_at, str) or not switched_at or len(switched_at) > 128:
        raise BootstrapError("CURRENT_POINTER_SCHEMA_INVALID", "switched_at")
    active = _validate_active_ref_shape(
        pointer.get("active"),
        state_root=state_root,
        reason_code="CURRENT_POINTER_ACTIVE_INVALID",
    )
    if pointer.get("previous_verified") is not None:
        _validate_active_ref_shape(pointer.get("previous_verified"), state_root=state_root)
    txn_id = active["activation_txn_id"]
    journal_path = (
        state_root / "researcher_container" / "transactions" / txn_id / "activation.v1.json"
    )
    journal = _load_json(journal_path)
    _validate_journal_shape(journal, journal_path=journal_path, state_root=state_root)
    if journal.get("txn_id") != txn_id:
        raise BootstrapError("ACTIVATION_TRANSACTION_BINDING_MISMATCH", txn_id)
    if journal.get("expected_generation") != generation:
        raise BootstrapError("ACTIVATION_GENERATION_BINDING_MISMATCH", txn_id)
    if journal.get("to") != active:
        raise BootstrapError("ACTIVATION_TARGET_BINDING_MISMATCH", txn_id)
    command = argv[0] if argv else ""
    if journal.get("state") not in TERMINAL_ACTIVATION_STATES and command != "recover":
        raise BootstrapError("RECOVERY_REQUIRED", f"activation={txn_id}")
    if journal.get("state") in TERMINAL_ACTIVATION_STATES:
        if journal.get("terminal_pointer_sha256") != pointer_sha256:
            raise BootstrapError("ACTIVATION_POINTER_BINDING_MISMATCH", txn_id)
    pending = _pending_activation_journals(state_root)
    if len(pending) > 1:
        raise BootstrapError("RECOVERY_CONFLICT", "multiple pending activation journals")
    if pending and command != "recover":
        raise BootstrapError("RECOVERY_REQUIRED", str(pending[0].get("txn_id", "")))
    runtime_ref = active
    if pending and command == "recover":
        recovery_from = pending[0].get("from")
        if not isinstance(recovery_from, dict) or not isinstance(recovery_from.get("active"), dict):
            raise BootstrapError("RECOVERY_SOURCE_INVALID", str(pending[0].get("txn_id", "")))
        runtime_ref = recovery_from["active"]
    selected_release_id = runtime_ref.get("release_id")
    if (
        not isinstance(selected_release_id, str)
        or RELEASE_ID_PATTERN.fullmatch(selected_release_id) is None
    ):
        raise BootstrapError("RELEASE_IDENTITY_INVALID", str(selected_release_id))
    manifest_path = Path(str(runtime_ref.get("release_manifest_path", "")))
    expected_manifest_path = (
        state_root / "researcher_container" / "releases" / selected_release_id / "release.json"
    )
    if os.path.normcase(os.path.abspath(manifest_path)) != os.path.normcase(
        os.path.abspath(expected_manifest_path)
    ):
        raise BootstrapError("RELEASE_MANIFEST_PATH_INVALID", str(manifest_path))
    manifest, manifest_sha256 = _load_json_with_identity(manifest_path)
    if manifest_sha256 != runtime_ref.get("release_manifest_sha256"):
        raise BootstrapError("RELEASE_MANIFEST_IDENTITY_MISMATCH", str(manifest_path))
    _validate_release_manifest_shape(
        manifest,
        manifest_path=manifest_path,
        state_root=state_root,
    )
    expected_ref = {
        "release_id": manifest["release_id"],
        "release_manifest_path": str(manifest_path),
        "release_manifest_sha256": manifest_sha256,
        "skill_bundle_manifest_sha256": manifest["skill_bundle_manifest_sha256"],
        "skill_bundle_tree_sha256": manifest["skill_bundle_tree_sha256"],
        "capability_version": manifest["capability_version"],
        "package_version": manifest["package_version"],
        "required_bootstrap_protocol": manifest["required_bootstrap_protocol"],
        "activation_txn_id": runtime_ref["activation_txn_id"],
    }
    if runtime_ref != expected_ref:
        raise BootstrapError("RELEASE_POINTER_IDENTITY_MISMATCH", selected_release_id)
    bundle_root, bundle_manifest = _validate_bundle(
        release_root=manifest_path.parent,
        manifest=manifest,
        active=runtime_ref,
    )
    _validate_release_skill_hashes(manifest, bundle_root)
    files = bundle_manifest["files"]
    runtime_relative = RELEASE_RUNTIME_RELATIVE_PATH.relative_to("skill-bundle").as_posix()
    runtime_rows = [
        row
        for row in files
        if isinstance(row, dict) and row.get("relative_path") == runtime_relative
    ]
    if len(runtime_rows) != 1:
        raise BootstrapError("SKILL_RUNTIME_ENTRY_MISSING", runtime_relative)
    runtime_path = bundle_root / runtime_relative
    runtime_payload = _regular_control_bytes(runtime_path, maximum=MAX_BUNDLE_FILE_BYTES)
    if _sha256_bytes(runtime_payload) != runtime_rows[0].get("sha256"):
        raise BootstrapError("SKILL_RUNTIME_ENTRY_IDENTITY_MISMATCH", str(runtime_path))
    try:
        runtime_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BootstrapError("SKILL_RUNTIME_ENTRY_INVALID", str(runtime_path)) from exc
    fence = {
        "schema_version": "xinao.bootstrap_fence.v1",
        "state_root": str(state_root),
        "pointer_sha256": pointer_sha256,
        "pointer_generation": generation,
        "active_txn_id": txn_id,
        "pending_txn_id": pending[0]["txn_id"] if pending else None,
        "selected_release_id": selected_release_id,
        "selected_release_manifest_sha256": manifest_sha256,
        "selected_skill_bundle_tree_sha256": manifest["skill_bundle_tree_sha256"],
        "selected_runtime_sha256": _sha256_bytes(runtime_payload),
    }
    return runtime_path, runtime_payload, fence


def _runtime_wrapper(runtime_path: Path, runtime_payload: bytes) -> bytes:
    encoded = base64.b64encode(runtime_payload).decode("ascii")
    source_name = ascii(str(runtime_path))
    return (
        "import base64\n"
        f"_source = base64.b64decode({encoded!r}, validate=True)\n"
        f"_name = {source_name}\n"
        "_scope = {\n"
        "    '__name__': '__main__',\n"
        "    '__file__': _name,\n"
        "    '__package__': None,\n"
        "    '__cached__': None,\n"
        "}\n"
        "exec(compile(_source, _name, 'exec'), _scope, _scope)\n"
    ).encode("ascii")


def _reap_failed_runtime_child(process: subprocess.Popen[bytes]) -> str:
    cleanup_errors: list[str] = []
    if process.poll() is None:
        try:
            process.terminate()
        except OSError as exc:
            cleanup_errors.append(f"terminate:{exc}")
    try:
        process.wait(timeout=RUNTIME_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError as exc:
            cleanup_errors.append(f"kill:{exc}")
        try:
            process.wait(timeout=RUNTIME_REAP_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            cleanup_errors.append(f"wait:{exc}")
    except OSError as exc:
        cleanup_errors.append(f"wait:{exc}")
    return "; ".join(cleanup_errors)


def _handoff_runtime_wrapper(process: subprocess.Popen[bytes], wrapper: bytes) -> None:
    stream = process.stdin
    if stream is None:
        cleanup = _reap_failed_runtime_child(process)
        raise BootstrapError(
            "SKILL_RUNTIME_HANDOFF_FAILED",
            "runtime stdin pipe unavailable" + (f"; cleanup={cleanup}" if cleanup else ""),
        )
    outcome: dict[str, object] = {}

    def write_and_close() -> None:
        try:
            written = stream.write(wrapper)
            if written != len(wrapper):
                raise OSError(f"short runtime handoff: {written}/{len(wrapper)}")
            stream.flush()
        except Exception as exc:
            outcome["error"] = exc
        finally:
            try:
                stream.close()
            except Exception as exc:
                outcome.setdefault("error", exc)

    writer = threading.Thread(
        target=write_and_close,
        name="xinao-runtime-handoff",
        daemon=True,
    )
    try:
        writer.start()
    except RuntimeError as exc:
        cleanup = _reap_failed_runtime_child(process)
        raise BootstrapError(
            "SKILL_RUNTIME_HANDOFF_FAILED",
            str(exc) + (f"; cleanup={cleanup}" if cleanup else ""),
        ) from exc
    writer.join(timeout=RUNTIME_HANDOFF_TIMEOUT_SECONDS)
    if writer.is_alive() or "error" in outcome:
        cleanup = _reap_failed_runtime_child(process)
        writer.join(timeout=RUNTIME_REAP_TIMEOUT_SECONDS)
        detail = (
            "runtime stdin handoff timed out"
            if writer.is_alive()
            else str(outcome.get("error", "runtime stdin handoff failed"))
        )
        if writer.is_alive():
            detail += "; writer did not stop after child reap"
        if cleanup:
            detail += f"; cleanup={cleanup}"
        process.stdin = None
        raise BootstrapError("SKILL_RUNTIME_HANDOFF_FAILED", detail)
    process.stdin = None


def _companion_runtime_path() -> Path:
    return Path(__file__).resolve().with_name("xinao_runtime.py")


def _run_companion_runtime(argv: Sequence[str]) -> int:
    """Execute the co-located runtime for protocol migration without a v2 fence.

    Ordinary inspect/research never take this path: they always require a verified
    protocol-2 pointer, terminal journal, and inventory-bound release runtime.
    """

    if argv and argv[0] not in {"bootstrap-migrate", "recover"}:
        raise BootstrapError("INVOCATION_ARGUMENTS_INVALID", argv[0])
    if argv and argv[0] == "bootstrap-migrate" and len(argv) != 1:
        raise BootstrapError(
            "INVOCATION_ARGUMENTS_INVALID",
            "bootstrap-migrate absorbs all technical fields; pass no release, hash, path, or generation",
        )
    runtime_path = _companion_runtime_path()
    if not runtime_path.is_file():
        raise BootstrapError("BOOTSTRAP_MIGRATION_RUNTIME_ABSENT", str(runtime_path))
    runtime_payload = _regular_control_bytes(runtime_path, maximum=MAX_BUNDLE_FILE_BYTES)
    observed_runtime_sha256 = hashlib.sha256(runtime_payload).hexdigest()
    if (
        not isinstance(EXPECTED_COMPANION_RUNTIME_SHA256, str)
        or len(EXPECTED_COMPANION_RUNTIME_SHA256) != 64
        or any(ch not in "0123456789abcdef" for ch in EXPECTED_COMPANION_RUNTIME_SHA256)
    ):
        raise BootstrapError(
            "COMPANION_RUNTIME_SEAL_INVALID",
            "EXPECTED_COMPANION_RUNTIME_SHA256 is not a sealed sha256 hex digest",
        )
    if observed_runtime_sha256 != EXPECTED_COMPANION_RUNTIME_SHA256:
        raise BootstrapError(
            "COMPANION_RUNTIME_IDENTITY_MISMATCH",
            (
                f"path={runtime_path} expected={EXPECTED_COMPANION_RUNTIME_SHA256} "
                f"observed={observed_runtime_sha256}"
            ),
        )
    try:
        runtime_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BootstrapError("SKILL_RUNTIME_ENTRY_INVALID", str(runtime_path)) from exc
    process: subprocess.Popen[bytes] | None = None
    try:
        wrapper = _runtime_wrapper(runtime_path, runtime_payload)
        child_environment = os.environ.copy()
        child_environment.pop("XINAO_BOOTSTRAP_FENCE_V1", None)
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-", *argv],
                stdin=subprocess.PIPE,
                env=child_environment,
            )
        except OSError as exc:
            raise BootstrapError("SKILL_RUNTIME_START_FAILED", str(exc)) from exc
        _handoff_runtime_wrapper(process, wrapper)
        return process.wait()
    except BaseException:
        if process is not None:
            _reap_failed_runtime_child(process)
            stream = process.stdin
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
                process.stdin = None
        raise


def _pointer_requires_migration_entry(state_root: Path, command: str) -> bool:
    if command not in {"bootstrap-migrate", "recover"}:
        return False
    pointer_path = state_root / "researcher_container" / "current.json"
    if command == "bootstrap-migrate":
        return True
    if not pointer_path.is_file():
        return False
    try:
        pointer, _sha = _load_json_with_identity(pointer_path)
    except BootstrapError:
        return False
    if pointer.get("schema_version") == "xinao.researcher_current_pointer.v1":
        return True
    if pointer.get("schema_version") != "xinao.researcher_current_pointer.v2":
        return False
    # Mid-migration recover: pending MIGRATE journal while ordinary fence cannot form.
    transaction_root = state_root / "researcher_container" / "transactions"
    if not transaction_root.is_dir():
        return False
    try:
        for entry in sorted(transaction_root.iterdir()):
            journal_path = entry / "activation.v1.json"
            if not journal_path.is_file():
                continue
            journal = _load_json(journal_path)
            if (
                isinstance(journal, dict)
                and journal.get("operation") == "MIGRATE"
                and journal.get("state") not in TERMINAL_ACTIVATION_STATES
            ):
                return True
    except BootstrapError:
        return False
    return False


def _run_runtime(argv: Sequence[str]) -> int:
    state_root = Path(os.environ.get("XINAO_SKILL_STATE_ROOT", str(DEFAULT_STATE_ROOT)))
    if not state_root.is_absolute():
        raise BootstrapError("STATE_ROOT_INVALID", str(state_root))
    command = argv[0] if argv else ""
    if _pointer_requires_migration_entry(state_root, command):
        return _run_companion_runtime(argv)
    process: subprocess.Popen[bytes] | None = None
    try:
        with _activation_lock(state_root):
            runtime_path, runtime_payload, fence = _runtime_entry_locked(argv, state_root)
            wrapper = _runtime_wrapper(runtime_path, runtime_payload)
            child_environment = os.environ.copy()
            child_environment["XINAO_BOOTSTRAP_FENCE_V1"] = json.dumps(
                fence,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            try:
                process = subprocess.Popen(
                    [sys.executable, "-I", "-", *argv],
                    stdin=subprocess.PIPE,
                    env=child_environment,
                )
            except OSError as exc:
                raise BootstrapError("SKILL_RUNTIME_START_FAILED", str(exc)) from exc
            _handoff_runtime_wrapper(process, wrapper)
        return process.wait()
    except BaseException:
        if process is not None:
            _reap_failed_runtime_child(process)
            stream = process.stdin
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
                process.stdin = None
        raise


def _error(error: BootstrapError) -> None:
    print(
        json.dumps(
            {
                "schema_version": "xinao.bootstrap_error.v1",
                "status": "PREFLIGHT_FAILED",
                "reason_codes": [error.reason_code],
                "detail": error.detail,
                "user_operations_required": [],
                "science_restored": False,
                "parent_complete": False,
                "completion_claim_allowed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        return _run_runtime(arguments)
    except BootstrapError as exc:
        _error(exc)
        return 2
    except OSError as exc:
        _error(BootstrapError("SKILL_RUNTIME_START_FAILED", str(exc)))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
