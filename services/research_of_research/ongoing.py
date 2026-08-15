"""Thin durable consumer for explicitly appointed ongoing RoR cognition contacts.

The Stage-0 :mod:`continuation` adapter remains observation-only.  This module
requires a separate, exact-byte-bound human contract before it may create one
fresh, candidate-only clean-room contact.  It never resumes a session, touches
root-main, adopts a candidate, or exposes a shared-effect gateway.

``reconcile_ongoing`` is deliberately a short state-machine tick.  It launches
the PowerShell/Codex carrier detached, records the exact child and lease, closes
stdin, and returns.  A later tick seals output only after a definite terminal
trajectory record.  Thus a long Sol contact cannot occupy the Stage-0 watchdog.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from services.research_of_research.cell import DEFAULT_QUOTA_ROOT, AccountQuota
from services.research_of_research.windows_job import (
    JobSnapshot,
    JobState,
    WindowsJobError,
    query_named_job,
    spawn_windows_job_process,
    terminate_named_job,
)
from services.xinao_perpetual_world_compute.controller import (
    WORLD_TURN_QUOTA_LEASE_SCHEMA,
    ProcessLiveness,
    _release_byte_lock,
    _try_acquire_byte_lock,
    atomic_write_bytes,
    atomic_write_json,
    build_codex_arguments,
    build_codex_command,
    build_trajectory_index,
    canonical_json_bytes,
    clone_isolated_repo,
    create_world_isolated_launcher,
    sha256_file,
    terminate_process_tree,
    validate_source_repo,
)
from services.xinao_perpetual_world_compute.controller import (
    now_iso as _controller_now_iso,
)
from services.xinao_perpetual_world_compute.controller import (
    process_liveness as _controller_process_liveness,
)

DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\research_of_research")
ONGOING_DIRECTORY = "ongoing"

LEGACY_CONTRACT_INPUT_SCHEMA = "xinao.research-of-research.ongoing-contract.v1"
CONTRACT_INPUT_SCHEMA = "xinao.research-of-research.ongoing-contract.v2"
OBSERVATION_ELIGIBILITY_SCHEMA = "xinao.research-of-research.observation-eligibility-predicate.v1"
CONTRACT_REVISION_SCHEMA = "xinao.research-of-research.ongoing-contract-revision.v1"
CONTRACT_POINTER_SCHEMA = "xinao.research-of-research.ongoing-contract-pointer.v1"
CONTRACT_STOP_SCHEMA = "xinao.research-of-research.ongoing-contract-stop.v1"
FACT_SCHEMA = "xinao.research-of-research.ongoing-fact.v1"
OPPORTUNITY_SCHEMA = "xinao.research-of-research.ongoing-opportunity.v1"
OPPORTUNITY_STATUS_SCHEMA = "xinao.research-of-research.ongoing-opportunity-status.v1"
ATTEMPT_SCHEMA = "xinao.research-of-research.ongoing-attempt.v1"
ATTEMPT_STATUS_SCHEMA = "xinao.research-of-research.ongoing-attempt-status.v1"
CANDIDATE_SCHEMA = "xinao.research-of-research.ongoing-candidate.v2"
LEGACY_CANDIDATE_SCHEMA = "xinao.research-of-research.ongoing-candidate.v1"
PROJECTION_SCHEMA = "xinao.research-of-research.ongoing-projection.v1"
BUNDLE_MANIFEST_SCHEMA = "xinao.research-of-research.reentry-evidence-bundle.v2"
RUNNER_REQUEST_SCHEMA = "xinao.research-of-research.ongoing-runner-request.v1"
RUNNER_LAUNCH_INTENT_SCHEMA = "xinao.research-of-research.ongoing-runner-launch-intent.v1"
RUNNER_SPAWN_SCHEMA = "xinao.research-of-research.ongoing-runner-spawn.v1"
RUNNER_STARTED_SCHEMA = "xinao.research-of-research.ongoing-runner-started.v1"
RUNNER_TERMINAL_SCHEMA = "xinao.research-of-research.ongoing-runner-terminal.v1"
JOB_IDENTITY_SCHEMA = "xinao.research-of-research.ongoing-windows-job-identity.v1"

PROTOCOL_STAGE = "ONGOING_ROR_CANDIDATE_CONTACTS_ONLY"
BUNDLE_RELATIVE_ROOT = Path("S_REENTRY_EVIDENCE") / "ROR_FRAME"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GROUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_BOUNDARIES = {
    "authority": False,
    "shared_effect_authorized": False,
    "completion_claim_allowed": False,
}

_CONTRACT_REQUIRED_KEYS = {
    "schema",
    "human_appointment",
    "parent_statement",
    "survives",
    "dies",
    "unknowns",
    "pending_futures",
    "source_groups",
    "wake_switches",
    "clean_room",
    "account_order",
    "physical_quota_limit",
    "model",
    "model_reasoning_effort",
    "timeout_seconds",
    "minimum_continuation_delay_seconds",
}
_CONTRACT_OPTIONAL_KEYS = {"continuation_observation_eligibility"}
_CONTRACT_V2_KEYS = {
    "schema",
    "human_appointment",
    "evidence_frame",
    "wake_policy",
    "carrier",
}
_EVIDENCE_FRAME_KEYS = {
    "source_groups",
    "coverage_claim",
    "snapshot_atomicity",
    "instruction_authority",
    "cognition_authority",
}
_WAKE_POLICY_KEYS = {
    "activation",
    "continuation_observations",
    "inventory_changes",
    "minimum_repeat_delay_seconds",
    "continuation_observation_eligibility",
}
_CARRIER_KEYS = {
    "clean_room",
    "account_order",
    "physical_quota_limit",
    "model",
    "model_reasoning_effort",
    "timeout_seconds",
}
_WAKE_KEYS = {
    "activation",
    "continuation_observations",
    "inventory_changes",
    "candidate_continue",
}
_CLEAN_ROOM_KEYS = {"source_repo", "launcher_path", "powershell_path", "workspace_root"}
_SOURCE_GROUP_REQUIRED_KEYS = {"name", "root", "glob_patterns", "exact_files"}
_SOURCE_GROUP_OPTIONAL_KEYS = {"wake_authoritative"}
_APPOINTMENT_KEYS = {"source_path", "source_sha256", "quoted_words"}
_OBSERVATION_ELIGIBILITY_KEYS = {
    "schema",
    "field",
    "operator",
    "values",
    "missing_is_eligible",
}
_RESERVED_LEASE_KEYS = {
    "schema",
    "lease_id",
    "counted",
    "status",
    "account_slot",
    "slot",
    "limit",
    "run_id",
    "lineage_id",
    "workspace",
    "controller_pid",
    "child_pid",
    "reserved_at",
    "bound_at",
    "released_at",
    "experiment_candidate_only",
    "path",
}
_DEFAULT_OBSERVATION_ELIGIBILITY = {
    "schema": OBSERVATION_ELIGIBILITY_SCHEMA,
    "field": "reported_status",
    "operator": "NOT_IN",
    "values": ["INVALID_EXPERIMENT"],
    "missing_is_eligible": False,
}

# The live temporary account-cap holders publish their policy under the same
# account admission lock that protects world-turn leases.  Their fsynced policy
# scan can occupy that lock for seconds while leaving only a short gap between
# cycles.  A single nonblocking probe therefore does not distinguish a full
# account from transient lock contention.  Keep the Scheduled Task tick short,
# but preserve that distinction and wait through a bounded lock-turnover window.
_CAPACITY_ADMISSION_LOCK_TIMEOUT_SECONDS = 10.0
_CAPACITY_ADMISSION_RETRY_DELAY_SECONDS = 0.01
_WORKSPACE_INVENTORY_RETRY_DELAY_SECONDS = 0.05
_MAX_PRE_MODEL_CARRIER_FAILURES = 6
_MAX_MODEL_FAILURES = 2

_OPPORTUNITY_STATUSES = {
    "DUE",
    "WAITING_FOR_COMPUTE",
    "NOT_BEFORE",
    "RUNNING",
    "COMPLETED",
    "RETRYABLE",
    "ORPHAN_OWN_ATTEMPT",
    "STOPPED",
}
_ATTEMPT_STATUSES = {
    "CLAIMING_COMPUTE",
    "WAITING_FOR_COMPUTE",
    "PREPARING",
    "LAUNCHING",
    "RUNNER_STARTING",
    "CHILD_SPAWNED",
    "RUNNING",
    "SEALED",
    "INVALID_OUTPUT",
    "RETRYABLE",
    "FAILED_UNKNOWN",
    "TERMINAL_FAILED",
    "STOP_REQUESTED",
    "STOPPED",
}

_RUNNER_RELEASE_FILES = (
    "services/__init__.py",
    "services/research_of_research/__init__.py",
    "services/research_of_research/continuation.py",
    "services/research_of_research/ongoing.py",
    "services/research_of_research/windows_job.py",
    "services/research_of_research/cell.py",
    "services/xinao_perpetual_world_compute/__init__.py",
    "services/xinao_perpetual_world_compute/controller.py",
)


class OngoingError(RuntimeError):
    """A contract, identity, or fail-closed runtime invariant failed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(reason_code: str, message: str) -> None:
    raise OngoingError(reason_code, message)


def _now_iso() -> str:
    return _controller_now_iso()


def _process_liveness(pid: int | None) -> str:
    value = _controller_process_liveness(pid)
    return value.value if isinstance(value, ProcessLiveness) else str(value)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stable_id(value: object) -> str:
    return _sha256(canonical_json_bytes(value))


def _job_identity(attempt_id: str) -> dict[str, Any]:
    """Return the deterministic kernel owner identity for one production attempt."""

    attempt_id = _require_content_id(
        attempt_id, code="JOB_IDENTITY_INVALID", field="Job attempt id"
    )
    unsigned = {
        "schema": JOB_IDENTITY_SCHEMA,
        "attempt_id": attempt_id,
        "job_name": f"Global\\XINAO-S-RoR-Ongoing-v1-{attempt_id}",
        "assignment": "PROC_THREAD_ATTRIBUTE_JOB_LIST",
        "name_anchor": "CARRIER_INHERITED_SYNCHRONIZE_HANDLE",
        "carrier_role": "CLEANROOM_POWERSHELL_ROOT",
        "kill_on_job_close": False,
    }
    return {**unsigned, "job_identity_id": _stable_id(unsigned)}


def _validate_job_identity(value: object, *, attempt_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("JOB_IDENTITY_INVALID", "Job identity must be an object")
    expected = _job_identity(attempt_id)
    _require_exact_keys(value, set(expected), code="JOB_IDENTITY_KEYS_INVALID")
    if dict(value) != expected:
        _fail("JOB_IDENTITY_INVALID", "Job identity differs from deterministic owner")
    return expected


def _job_snapshot(attempt_id: str) -> JobSnapshot:
    identity = _job_identity(attempt_id)
    try:
        return query_named_job(str(identity["job_name"]))
    except WindowsJobError as exc:
        return JobSnapshot(
            job_name=str(identity["job_name"]),
            state=JobState.UNKNOWN,
            winerror=exc.winerror,
            error_message=f"{exc.reason_code}:{exc}",
        )


def _terminate_job(attempt_id: str) -> JobSnapshot:
    identity = _job_identity(attempt_id)
    try:
        return terminate_named_job(str(identity["job_name"]))
    except WindowsJobError as exc:
        return JobSnapshot(
            job_name=str(identity["job_name"]),
            state=JobState.UNKNOWN,
            winerror=exc.winerror,
            error_message=f"{exc.reason_code}:{exc}",
        )


def _require_content_id(value: object, *, code: str, field: str) -> str:
    if not isinstance(value, str) or not _HEX_SHA256.fullmatch(value):
        _fail(code, f"{field} must be a lowercase SHA256 content id")
    return value


def _ongoing_root(runtime_root: Path) -> Path:
    return runtime_root.resolve(strict=False) / ONGOING_DIRECTORY


def _read_json_object(path: Path, *, reason_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OngoingError(reason_code, f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        _fail(reason_code, f"JSON object required: {path}")
    return value


def _write_once_bytes(path: Path, raw: bytes, *, conflict_code: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise OngoingError(conflict_code, f"cannot read immutable record: {path}") from exc
        if existing != raw:
            _fail(conflict_code, f"immutable record collision: {path}")
        return _sha256(existing)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{_sha256(raw)[:12]}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                _fail(conflict_code, f"immutable record collision: {path}")
        except OSError:
            # Hard links are not available on every Windows volume.  The single
            # component byte lock still serializes writers; replace only when
            # the destination remains absent.
            if path.exists():
                if path.read_bytes() != raw:
                    _fail(conflict_code, f"immutable record collision: {path}")
            else:
                os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256(raw)


def _write_once_json(path: Path, value: object, *, conflict_code: str) -> str:
    return _write_once_bytes(path, canonical_json_bytes(value), conflict_code=conflict_code)


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], *, code: str) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        _fail(code, f"keys invalid; missing={missing!r} extra={extra!r}")


def _require_string(value: object, *, code: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(code, f"{field} must be a non-empty string")
    return value


def _require_string_list(value: object, *, code: str, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        _fail(code, f"{field} must be a list of non-empty strings")
    return list(value)


def _validate_observation_eligibility(value: object | None) -> dict[str, Any]:
    """Normalize the replaceable, contract-owned observation eligibility rule."""

    if value is None:
        value = _DEFAULT_OBSERVATION_ELIGIBILITY
    if not isinstance(value, Mapping):
        _fail(
            "OBSERVATION_ELIGIBILITY_INVALID",
            "continuation_observation_eligibility must be an object",
        )
    _require_exact_keys(
        value,
        _OBSERVATION_ELIGIBILITY_KEYS,
        code="OBSERVATION_ELIGIBILITY_KEYS_INVALID",
    )
    values = _require_string_list(
        value.get("values"),
        code="OBSERVATION_ELIGIBILITY_VALUES_INVALID",
        field="continuation_observation_eligibility.values",
    )
    if len(values) != len(set(values)):
        _fail(
            "OBSERVATION_ELIGIBILITY_VALUES_INVALID",
            "continuation observation eligibility values must be unique",
        )
    if (
        value.get("schema") != OBSERVATION_ELIGIBILITY_SCHEMA
        or value.get("field") != "reported_status"
        or value.get("operator") not in {"IN", "NOT_IN"}
        or type(value.get("missing_is_eligible")) is not bool
    ):
        _fail(
            "OBSERVATION_ELIGIBILITY_INVALID",
            "unsupported continuation observation eligibility predicate",
        )
    return {
        "schema": OBSERVATION_ELIGIBILITY_SCHEMA,
        "field": "reported_status",
        "operator": str(value["operator"]),
        "values": values,
        "missing_is_eligible": bool(value["missing_is_eligible"]),
    }


def _evaluate_observation_eligibility(
    predicate: Mapping[str, Any], reported_status: object
) -> dict[str, Any]:
    normalized = _validate_observation_eligibility(predicate)
    observed_value = reported_status if isinstance(reported_status, str) else None
    if observed_value is None:
        eligible = bool(normalized["missing_is_eligible"])
    else:
        contained = observed_value in normalized["values"]
        eligible = contained if normalized["operator"] == "IN" else not contained
    return {
        "predicate": normalized,
        "observed_value": observed_value,
        "eligible": eligible,
    }


def _observation_fact_eligibility(
    contract: Mapping[str, Any], fact: Mapping[str, Any]
) -> dict[str, Any]:
    eligibility = _evaluate_observation_eligibility(
        _contract_observation_eligibility(contract),
        fact.get("reported_status"),
    )
    recorded = fact.get("cognition_eligibility")
    if recorded is not None and recorded != eligibility:
        _fail(
            "OBSERVATION_ELIGIBILITY_DRIFT",
            "durable observation eligibility disagrees with its contract",
        )
    return eligibility


def _absolute_path(value: object, *, code: str, field: str, must_exist: bool = False) -> Path:
    text = _require_string(value, code=code, field=field)
    supplied = Path(text)
    if not supplied.is_absolute():
        _fail(code, f"{field} must be absolute: {text}")
    try:
        return supplied.resolve(strict=must_exist)
    except OSError as exc:
        raise OngoingError(code, f"{field} cannot be resolved: {text}") from exc


def _is_reparse(path: Path) -> bool:
    try:
        stat = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _require_regular_unlinked(path: Path, *, code: str, field: str) -> None:
    if not path.is_file() or _is_reparse(path):
        _fail(code, f"{field} must be an existing regular non-reparse file: {path}")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _paths_overlap(left: Path, right: Path) -> bool:
    return _is_within(left, right) or _is_within(right, left)


def _stable_read(path: Path, *, expected_sha256: str | None = None) -> bytes:
    _require_regular_unlinked(path, code="SOURCE_NOT_REGULAR", field="source")
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise OngoingError("SOURCE_READ_FAILED", f"cannot read source: {path}") from exc
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        _fail("SOURCE_DRIFT_DURING_READ", f"source changed during read: {path}")
    observed = _sha256(raw)
    if expected_sha256 is not None and observed != expected_sha256.casefold():
        _fail("SOURCE_HASH_MISMATCH", f"source hash changed: {path}")
    return raw


def _validate_contract_v1(value: Mapping[str, Any], *, runtime_root: Path) -> dict[str, Any]:
    observed_contract_keys = set(value)
    if not (
        _CONTRACT_REQUIRED_KEYS <= observed_contract_keys
        and observed_contract_keys <= _CONTRACT_REQUIRED_KEYS | _CONTRACT_OPTIONAL_KEYS
    ):
        missing = sorted(_CONTRACT_REQUIRED_KEYS - observed_contract_keys)
        extra = sorted(observed_contract_keys - _CONTRACT_REQUIRED_KEYS - _CONTRACT_OPTIONAL_KEYS)
        _fail("CONTRACT_KEYS_INVALID", f"keys invalid; missing={missing!r} extra={extra!r}")
    if value.get("schema") != LEGACY_CONTRACT_INPUT_SCHEMA:
        _fail("CONTRACT_SCHEMA_INVALID", "unsupported ongoing contract schema")

    appointment_value = value.get("human_appointment")
    if not isinstance(appointment_value, Mapping):
        _fail("HUMAN_APPOINTMENT_INVALID", "human_appointment must be an object")
    _require_exact_keys(appointment_value, _APPOINTMENT_KEYS, code="HUMAN_APPOINTMENT_KEYS_INVALID")
    appointment_path = _absolute_path(
        appointment_value.get("source_path"),
        code="HUMAN_APPOINTMENT_PATH_INVALID",
        field="human_appointment.source_path",
        must_exist=True,
    )
    _require_regular_unlinked(
        appointment_path, code="HUMAN_APPOINTMENT_PATH_INVALID", field="human appointment"
    )
    appointment_sha = str(appointment_value.get("source_sha256", "")).casefold()
    if not _HEX_SHA256.fullmatch(appointment_sha):
        _fail("HUMAN_APPOINTMENT_SHA256_INVALID", "human appointment SHA256 is invalid")
    appointment_raw = _stable_read(appointment_path, expected_sha256=appointment_sha)
    quoted_words = _require_string(
        appointment_value.get("quoted_words"),
        code="HUMAN_APPOINTMENT_WORDS_INVALID",
        field="human_appointment.quoted_words",
    )
    try:
        appointment_text = appointment_raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise OngoingError(
            "HUMAN_APPOINTMENT_UTF8_INVALID", "human appointment must be UTF-8 text"
        ) from exc
    if quoted_words not in appointment_text:
        _fail(
            "HUMAN_APPOINTMENT_QUOTE_MISMATCH",
            "quoted_words is not an exact substring of the bound appointment",
        )

    parent_statement = _require_string(
        value.get("parent_statement"), code="PARENT_STATEMENT_INVALID", field="parent_statement"
    )
    parent_delta = {
        key: _require_string_list(value.get(key), code="PARENT_ARRAY_INVALID", field=key)
        for key in ("survives", "dies", "unknowns", "pending_futures")
    }

    wake_value = value.get("wake_switches")
    if not isinstance(wake_value, Mapping):
        _fail("WAKE_SWITCHES_INVALID", "wake_switches must be an object")
    _require_exact_keys(wake_value, _WAKE_KEYS, code="WAKE_SWITCH_KEYS_INVALID")
    if any(type(wake_value[key]) is not bool for key in _WAKE_KEYS):
        _fail("WAKE_SWITCH_VALUE_INVALID", "wake switches must be booleans")
    if wake_value["activation"] is not True:
        _fail("ACTIVATION_WAKE_REQUIRED", "initial activation must create one opportunity")
    observation_eligibility = _validate_observation_eligibility(
        value.get("continuation_observation_eligibility")
    )

    clean_value = value.get("clean_room")
    if not isinstance(clean_value, Mapping):
        _fail("CLEAN_ROOM_INVALID", "clean_room must be an object")
    _require_exact_keys(clean_value, _CLEAN_ROOM_KEYS, code="CLEAN_ROOM_KEYS_INVALID")
    clean_room = {
        key: str(
            _absolute_path(
                clean_value.get(key),
                code="CLEAN_ROOM_PATH_INVALID",
                field=f"clean_room.{key}",
                must_exist=key != "workspace_root",
            )
        )
        for key in sorted(_CLEAN_ROOM_KEYS)
    }
    source_repo = Path(clean_room["source_repo"])
    launcher = Path(clean_room["launcher_path"])
    powershell = Path(clean_room["powershell_path"])
    if not source_repo.is_dir() or _is_reparse(source_repo):
        _fail("CLEAN_ROOM_REPO_INVALID", f"clean-room source repo invalid: {source_repo}")
    _require_regular_unlinked(launcher, code="CLEAN_ROOM_LAUNCHER_INVALID", field="launcher")
    _require_regular_unlinked(powershell, code="CLEAN_ROOM_POWERSHELL_INVALID", field="PowerShell")

    workspace_root = Path(clean_room["workspace_root"])
    ongoing_root = _ongoing_root(runtime_root)
    protected_roots = [ongoing_root, workspace_root, DEFAULT_QUOTA_ROOT.resolve(strict=False)]
    if any(_paths_overlap(workspace_root, root) for root in (ongoing_root, DEFAULT_QUOTA_ROOT)):
        _fail("CLEAN_ROOM_WORKSPACE_OVERLAP", "clean-room workspace overlaps runtime/quota state")

    groups_value = value.get("source_groups")
    if not isinstance(groups_value, list) or not groups_value:
        _fail("SOURCE_GROUPS_INVALID", "source_groups must be a non-empty list")
    groups: list[dict[str, Any]] = []
    group_names: set[str] = set()
    for index, raw_group in enumerate(groups_value):
        if not isinstance(raw_group, Mapping):
            _fail("SOURCE_GROUP_INVALID", f"source group {index} must be an object")
        observed_group_keys = set(raw_group)
        if not (
            _SOURCE_GROUP_REQUIRED_KEYS <= observed_group_keys
            and observed_group_keys <= _SOURCE_GROUP_REQUIRED_KEYS | _SOURCE_GROUP_OPTIONAL_KEYS
        ):
            missing = sorted(_SOURCE_GROUP_REQUIRED_KEYS - observed_group_keys)
            extra = sorted(
                observed_group_keys - _SOURCE_GROUP_REQUIRED_KEYS - _SOURCE_GROUP_OPTIONAL_KEYS
            )
            _fail(
                "SOURCE_GROUP_KEYS_INVALID",
                f"source group keys invalid; missing={missing!r} extra={extra!r}",
            )
        name = _require_string(
            raw_group.get("name"), code="SOURCE_GROUP_NAME_INVALID", field="source_group.name"
        )
        if not _GROUP_NAME.fullmatch(name) or name.casefold() in group_names:
            _fail("SOURCE_GROUP_NAME_INVALID", f"invalid or duplicate source group name: {name}")
        group_names.add(name.casefold())
        root = _absolute_path(
            raw_group.get("root"),
            code="SOURCE_GROUP_ROOT_INVALID",
            field=f"source_groups[{index}].root",
            must_exist=True,
        )
        if not root.is_dir() or _is_reparse(root):
            _fail("SOURCE_GROUP_ROOT_INVALID", f"source group root invalid: {root}")
        if any(_paths_overlap(root, protected) for protected in protected_roots):
            _fail("SOURCE_GROUP_OUTPUT_OVERLAP", f"source group watches an output surface: {root}")
        globs = _require_string_list(
            raw_group.get("glob_patterns"),
            code="SOURCE_GROUP_GLOBS_INVALID",
            field=f"source_groups[{index}].glob_patterns",
        )
        exact_files = _require_string_list(
            raw_group.get("exact_files"),
            code="SOURCE_GROUP_FILES_INVALID",
            field=f"source_groups[{index}].exact_files",
        )
        if not globs and not exact_files:
            _fail("SOURCE_GROUP_EMPTY", f"source group has no selectors: {name}")
        wake_authoritative = raw_group.get("wake_authoritative", True)
        if type(wake_authoritative) is not bool:
            _fail(
                "SOURCE_GROUP_WAKE_AUTHORITY_INVALID",
                f"source group wake_authoritative must be boolean: {name}",
            )
        for pattern in globs:
            candidate = Path(pattern)
            if candidate.is_absolute() or ".." in candidate.parts:
                _fail("SOURCE_GROUP_GLOB_INVALID", f"unsafe glob pattern: {pattern}")
        normalized_files: list[str] = []
        for file_value in exact_files:
            supplied = Path(file_value)
            selected = supplied if supplied.is_absolute() else root / supplied
            resolved = selected.resolve(strict=False)
            if not _is_within(resolved, root):
                _fail(
                    "SOURCE_GROUP_FILE_OUTSIDE_ROOT",
                    f"exact file escapes source root: {file_value}",
                )
            normalized_files.append(str(resolved))
        normalized_group = {
            "name": name,
            "root": str(root),
            "glob_patterns": globs,
            "exact_files": normalized_files,
        }
        if "wake_authoritative" in raw_group:
            normalized_group["wake_authoritative"] = wake_authoritative
        groups.append(normalized_group)
    shared_s_root = Path(__file__).resolve().parents[2]
    disallowed_workspace_overlaps = [source_repo, ongoing_root, DEFAULT_QUOTA_ROOT, shared_s_root]
    disallowed_workspace_overlaps.extend(Path(str(group["root"])) for group in groups)
    if any(
        _paths_overlap(workspace_root, protected) for protected in disallowed_workspace_overlaps
    ):
        _fail(
            "CLEAN_ROOM_WORKSPACE_OUTPUT_OVERLAP",
            "clean-room output workspace overlaps a source/shared/runtime surface",
        )

    account_order = value.get("account_order")
    if (
        not isinstance(account_order, list)
        or not account_order
        or any(slot not in {"A", "C"} for slot in account_order)
        or len(set(account_order)) != len(account_order)
    ):
        _fail("ACCOUNT_ORDER_INVALID", "account_order must be a unique non-empty subset of A/C")
    if value.get("physical_quota_limit") != 4:
        _fail("PHYSICAL_QUOTA_LIMIT_INVALID", "physical_quota_limit must equal 4")
    model = _require_string(value.get("model"), code="MODEL_INVALID", field="model")
    effort = _require_string(
        value.get("model_reasoning_effort"),
        code="MODEL_EFFORT_INVALID",
        field="model_reasoning_effort",
    )
    timeout = value.get("timeout_seconds")
    delay = value.get("minimum_continuation_delay_seconds")
    if type(timeout) is not int or timeout < 1:
        _fail("TIMEOUT_INVALID", "timeout_seconds must be a positive integer")
    if type(delay) is not int or delay < 0:
        _fail("CONTINUATION_DELAY_INVALID", "minimum continuation delay must be non-negative")

    normalized_contract = {
        "schema": LEGACY_CONTRACT_INPUT_SCHEMA,
        "human_appointment": {
            "source_path": str(appointment_path),
            "source_sha256": appointment_sha,
            "quoted_words": quoted_words,
        },
        "parent_statement": parent_statement,
        **parent_delta,
        "source_groups": groups,
        "wake_switches": {key: bool(wake_value[key]) for key in sorted(_WAKE_KEYS)},
        "clean_room": clean_room,
        "account_order": list(account_order),
        "physical_quota_limit": 4,
        "model": model,
        "model_reasoning_effort": effort,
        "timeout_seconds": timeout,
        "minimum_continuation_delay_seconds": delay,
    }
    if "continuation_observation_eligibility" in value:
        normalized_contract["continuation_observation_eligibility"] = observation_eligibility
    return normalized_contract


def _validate_contract(value: Mapping[str, Any], *, runtime_root: Path) -> dict[str, Any]:
    """Validate a separated v2 carrier contract while retaining v1 read compatibility.

    V2 deliberately does not contain a compiled parent statement or a model-authored
    continuation channel.  It binds four different mechanical objects without
    pretending they have the same authority: the exact human appointment, a
    contract-selected evidence frame, deterministic wake policy, and carrier
    configuration.
    """

    if value.get("schema") == LEGACY_CONTRACT_INPUT_SCHEMA:
        return _validate_contract_v1(value, runtime_root=runtime_root)
    if value.get("schema") != CONTRACT_INPUT_SCHEMA:
        _fail("CONTRACT_SCHEMA_INVALID", "unsupported ongoing contract schema")
    _require_exact_keys(value, _CONTRACT_V2_KEYS, code="CONTRACT_KEYS_INVALID")

    evidence = value.get("evidence_frame")
    if not isinstance(evidence, Mapping):
        _fail("EVIDENCE_FRAME_INVALID", "evidence_frame must be an object")
    _require_exact_keys(evidence, _EVIDENCE_FRAME_KEYS, code="EVIDENCE_FRAME_KEYS_INVALID")
    if evidence.get("coverage_claim") != "CONTRACT_SELECTED_PARTIAL":
        _fail("EVIDENCE_FRAME_COVERAGE_INVALID", "evidence frame must claim partial coverage")
    if evidence.get("snapshot_atomicity") != "PER_FILE_STABLE_NO_GLOBAL_ATOMICITY":
        _fail(
            "EVIDENCE_FRAME_ATOMICITY_INVALID",
            "evidence frame must disclose per-file rather than global atomicity",
        )
    if evidence.get("instruction_authority") is not False:
        _fail("EVIDENCE_FRAME_AUTHORITY_INVALID", "evidence is not an instruction source")
    if evidence.get("cognition_authority") is not False:
        _fail("EVIDENCE_FRAME_AUTHORITY_INVALID", "evidence does not own cognition")

    wake = value.get("wake_policy")
    if not isinstance(wake, Mapping):
        _fail("WAKE_POLICY_INVALID", "wake_policy must be an object")
    _require_exact_keys(wake, _WAKE_POLICY_KEYS, code="WAKE_POLICY_KEYS_INVALID")
    for field in ("activation", "continuation_observations", "inventory_changes"):
        if type(wake.get(field)) is not bool:
            _fail("WAKE_POLICY_VALUE_INVALID", f"wake_policy.{field} must be boolean")
    if wake.get("activation") is not True:
        _fail("ACTIVATION_WAKE_REQUIRED", "initial activation must create one opportunity")
    delay = wake.get("minimum_repeat_delay_seconds")
    if type(delay) is not int or delay < 0:
        _fail(
            "CONTINUATION_DELAY_INVALID",
            "wake_policy.minimum_repeat_delay_seconds must be non-negative",
        )

    carrier = value.get("carrier")
    if not isinstance(carrier, Mapping):
        _fail("CARRIER_INVALID", "carrier must be an object")
    _require_exact_keys(carrier, _CARRIER_KEYS, code="CARRIER_KEYS_INVALID")

    # Reuse the mature path/source/quota validation without preserving the v1
    # epistemic fields in the durable v2 representation.
    legacy_input = {
        "schema": LEGACY_CONTRACT_INPUT_SCHEMA,
        "human_appointment": value.get("human_appointment"),
        "parent_statement": "LEGACY_VALIDATION_ADAPTER_NOT_A_REENTRY_INSTRUCTION",
        "survives": [],
        "dies": [],
        "unknowns": [],
        "pending_futures": [],
        "source_groups": evidence.get("source_groups"),
        "wake_switches": {
            "activation": wake.get("activation"),
            "continuation_observations": wake.get("continuation_observations"),
            "inventory_changes": wake.get("inventory_changes"),
            "candidate_continue": False,
        },
        "continuation_observation_eligibility": wake.get("continuation_observation_eligibility"),
        "clean_room": carrier.get("clean_room"),
        "account_order": carrier.get("account_order"),
        "physical_quota_limit": carrier.get("physical_quota_limit"),
        "model": carrier.get("model"),
        "model_reasoning_effort": carrier.get("model_reasoning_effort"),
        "timeout_seconds": carrier.get("timeout_seconds"),
        "minimum_continuation_delay_seconds": delay,
    }
    normalized = _validate_contract_v1(legacy_input, runtime_root=runtime_root)
    return {
        "schema": CONTRACT_INPUT_SCHEMA,
        "human_appointment": normalized["human_appointment"],
        "evidence_frame": {
            "source_groups": normalized["source_groups"],
            "coverage_claim": "CONTRACT_SELECTED_PARTIAL",
            "snapshot_atomicity": "PER_FILE_STABLE_NO_GLOBAL_ATOMICITY",
            "instruction_authority": False,
            "cognition_authority": False,
        },
        "wake_policy": {
            "activation": bool(wake["activation"]),
            "continuation_observations": bool(wake["continuation_observations"]),
            "inventory_changes": bool(wake["inventory_changes"]),
            "minimum_repeat_delay_seconds": int(delay),
            "continuation_observation_eligibility": normalized[
                "continuation_observation_eligibility"
            ],
        },
        "carrier": {
            "clean_room": normalized["clean_room"],
            "account_order": normalized["account_order"],
            "physical_quota_limit": normalized["physical_quota_limit"],
            "model": normalized["model"],
            "model_reasoning_effort": normalized["model_reasoning_effort"],
            "timeout_seconds": normalized["timeout_seconds"],
        },
    }


def _contract_appointment(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    value = contract.get("human_appointment")
    if not isinstance(value, Mapping):
        _fail("HUMAN_APPOINTMENT_INVALID", "contract has no human appointment")
    return value


def _contract_source_groups(contract: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    if contract.get("schema") == CONTRACT_INPUT_SCHEMA:
        frame = contract.get("evidence_frame")
        groups = frame.get("source_groups") if isinstance(frame, Mapping) else None
    else:
        groups = contract.get("source_groups")
    if not isinstance(groups, list):
        _fail("SOURCE_GROUPS_INVALID", "contract has no evidence source groups")
    return groups


def _contract_wake_policy(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    if contract.get("schema") == CONTRACT_INPUT_SCHEMA:
        value = contract.get("wake_policy")
    else:
        value = contract.get("wake_switches")
    if not isinstance(value, Mapping):
        _fail("WAKE_POLICY_INVALID", "contract has no wake policy")
    return value


def _contract_observation_eligibility(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    policy = _contract_wake_policy(contract)
    return policy.get(
        "continuation_observation_eligibility",
        contract.get("continuation_observation_eligibility", _DEFAULT_OBSERVATION_ELIGIBILITY),
    )


def _contract_carrier(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    value = contract.get("carrier")
    return value if isinstance(value, Mapping) else contract


def _contract_clean_room(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    carrier = _contract_carrier(contract)
    value = carrier.get("clean_room")
    if not isinstance(value, Mapping):
        _fail("CLEAN_ROOM_INVALID", "contract carrier has no clean_room")
    return value


def _contract_account_order(contract: Mapping[str, Any]) -> list[str]:
    value = _contract_carrier(contract).get("account_order")
    if not isinstance(value, list):
        _fail("ACCOUNT_ORDER_INVALID", "contract carrier has no account order")
    return [str(item) for item in value]


def _contract_carrier_value(contract: Mapping[str, Any], field: str) -> Any:
    return _contract_carrier(contract).get(field)


def _contract_repeat_delay(contract: Mapping[str, Any]) -> int:
    policy = _contract_wake_policy(contract)
    value = policy.get(
        "minimum_repeat_delay_seconds",
        contract.get("minimum_continuation_delay_seconds"),
    )
    if type(value) is not int or value < 0:
        _fail("CONTINUATION_DELAY_INVALID", "contract repeat delay is invalid")
    return value


def _wake_authoritative_group_names(contract: Mapping[str, Any]) -> set[str]:
    """Return the contract-selected wake surface; old v1 groups retain old behavior."""

    return {
        str(group["name"])
        for group in _contract_source_groups(contract)
        if group.get("wake_authoritative", True) is True
    }


def _wake_inventory_id(contract: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> str:
    wake_groups = _wake_authoritative_group_names(contract)
    wake_entries = [dict(entry) for entry in entries if str(entry.get("group")) in wake_groups]
    return _stable_id(wake_entries)


def _inventory_wake_id(contract: Mapping[str, Any], inventory: Mapping[str, Any]) -> str:
    supplied = inventory.get("wake_inventory_id")
    if supplied is not None:
        return _require_content_id(
            supplied, code="WAKE_INVENTORY_INVALID", field="wake inventory id"
        )
    entries = inventory.get("entries")
    if not isinstance(entries, list) or any(not isinstance(entry, Mapping) for entry in entries):
        _fail("WAKE_INVENTORY_INVALID", "inventory entries cannot form a wake identity")
    return _wake_inventory_id(contract, entries)


def _fact_wake_inventory_id(contract: Mapping[str, Any], fact: Mapping[str, Any]) -> str:
    supplied = fact.get("wake_inventory_id")
    entries = fact.get("inventory")
    if not isinstance(entries, list) or any(not isinstance(entry, Mapping) for entry in entries):
        _fail("WAKE_INVENTORY_FACT_INVALID", "inventory fact has no valid inventory entries")
    recomputed = _wake_inventory_id(contract, entries)
    if supplied is None:
        return recomputed
    observed = _require_content_id(
        supplied, code="WAKE_INVENTORY_FACT_INVALID", field="fact wake inventory id"
    )
    if observed != recomputed:
        _fail("WAKE_INVENTORY_FACT_INVALID", "inventory fact wake identity is inconsistent")
    return observed


def _inventory_sources(contract: Mapping[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for group in _contract_source_groups(contract):
        name = str(group["name"])
        root = Path(str(group["root"]))
        selected: dict[str, Path] = {}
        for pattern in group["glob_patterns"]:
            try:
                matches = root.glob(str(pattern))
                for path in matches:
                    try:
                        lexical_relative = path.relative_to(root)
                    except ValueError:
                        _fail("SOURCE_GLOB_ESCAPE", f"glob match escaped source root: {path}")
                    cursor = root
                    for part in lexical_relative.parts:
                        cursor = cursor / part
                        if cursor.exists() and _is_reparse(cursor):
                            _fail(
                                "SOURCE_REPARSE_REJECTED",
                                f"source selector traversed reparse path: {cursor}",
                            )
                    resolved = path.resolve(strict=False)
                    if not _is_within(resolved, root):
                        _fail(
                            "SOURCE_GLOB_ESCAPE", f"glob match resolved outside source root: {path}"
                        )
                    if path.is_file() and not _is_reparse(path):
                        selected[str(resolved).casefold()] = resolved
                    elif path.exists() and _is_reparse(path):
                        _fail(
                            "SOURCE_REPARSE_REJECTED",
                            f"source selector traversed reparse path: {path}",
                        )
            except (OSError, ValueError) as exc:
                raise OngoingError(
                    "SOURCE_GLOB_FAILED", f"cannot evaluate source glob: {root}:{pattern}"
                ) from exc
        for text in group["exact_files"]:
            path = Path(str(text)).resolve(strict=False)
            selected[str(path).casefold()] = path
        for folded, path in sorted(selected.items(), key=lambda item: item[0]):
            if folded in seen_paths:
                _fail("SOURCE_PATH_DUPLICATE", f"source path selected more than once: {path}")
            seen_paths.add(folded)
            relative = path.relative_to(root).as_posix()
            export_path = f"{name}/{relative}"
            if not path.exists():
                entries.append(
                    {
                        "group": name,
                        "source_path": str(path),
                        "export_path": export_path,
                        "state": "MISSING",
                        "size": None,
                        "sha256": None,
                    }
                )
                continue
            raw = _stable_read(path)
            entries.append(
                {
                    "group": name,
                    "source_path": str(path),
                    "export_path": export_path,
                    "state": "PRESENT",
                    "size": len(raw),
                    "sha256": _sha256(raw),
                }
            )
    entries.sort(key=lambda row: (str(row["source_path"]).casefold(), str(row["group"]).casefold()))
    return {
        "inventory_id": _stable_id(entries),
        "wake_inventory_id": _wake_inventory_id(contract, entries),
        "entries": entries,
    }


def _load_revision(root: Path, revision_id: str) -> dict[str, Any]:
    _require_content_id(
        revision_id, code="CONTRACT_REVISION_ID_INVALID", field="contract revision id"
    )
    path = root / "contracts" / "revisions" / f"{revision_id}.json"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OngoingError(
            "CONTRACT_REVISION_MISSING", f"contract revision missing: {path}"
        ) from exc
    if _sha256(raw) != revision_id:
        _fail("CONTRACT_REVISION_HASH_MISMATCH", f"contract revision hash mismatch: {path}")
    revision = _read_json_object(path, reason_code="CONTRACT_REVISION_JSON_INVALID")
    if (
        revision.get("schema") != CONTRACT_REVISION_SCHEMA
        or revision.get("protocol_stage") != PROTOCOL_STAGE
    ):
        _fail("CONTRACT_REVISION_SCHEMA_INVALID", f"contract revision invalid: {path}")
    if any(revision.get(key) is not value for key, value in _BOUNDARIES.items()):
        _fail("CONTRACT_REVISION_AUTHORITY_INVALID", f"contract revision authority invalid: {path}")
    return {**revision, "revision_id": revision_id}


def _stop_path(root: Path, revision_id: str) -> Path:
    _require_content_id(revision_id, code="CONTRACT_REVISION_ID_INVALID", field="revision id")
    return root / "contracts" / "stops" / f"{revision_id}.json"


def _read_stop(root: Path, revision_id: str) -> dict[str, Any] | None:
    path = _stop_path(root, revision_id)
    if not path.is_file():
        return None
    value = _read_json_object(path, reason_code="CONTRACT_STOP_INVALID")
    _require_exact_keys(
        value,
        {"schema", "revision_id", "stopped_at", "protocol_stage", *_BOUNDARIES},
        code="CONTRACT_STOP_KEYS_INVALID",
    )
    if (
        value.get("schema") != CONTRACT_STOP_SCHEMA
        or value.get("revision_id") != revision_id
        or value.get("protocol_stage") != PROTOCOL_STAGE
        or any(value.get(key) is not expected for key, expected in _BOUNDARIES.items())
    ):
        _fail("CONTRACT_STOP_INVALID", f"invalid immutable stop seal: {path}")
    _parse_iso(str(value.get("stopped_at")))
    return value


def _contract_is_stopped(root: Path, current: Mapping[str, Any]) -> bool:
    return (
        current.get("status") == "STOPPED"
        or _read_stop(root, str(current["revision_id"])) is not None
    )


def _load_current(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = root / "contracts" / "current.json"
    if not path.is_file():
        _fail("CONTRACT_NOT_BOUND", f"no ongoing contract is bound: {path}")
    current = _read_json_object(path, reason_code="CONTRACT_POINTER_INVALID")
    required = {
        "schema",
        "revision_id",
        "status",
        "published_at",
        "protocol_stage",
        *_BOUNDARIES,
    }
    if current.get("status") == "STOPPED":
        required.add("stopped_at")
    _require_exact_keys(current, required, code="CONTRACT_POINTER_KEYS_INVALID")
    if (
        current.get("schema") != CONTRACT_POINTER_SCHEMA
        or current.get("protocol_stage") != PROTOCOL_STAGE
    ):
        _fail("CONTRACT_POINTER_SCHEMA_INVALID", f"current contract pointer invalid: {path}")
    if current.get("status") not in {"LIVE", "STOPPED"}:
        _fail("CONTRACT_POINTER_STATUS_INVALID", f"current contract status invalid: {path}")
    if any(current.get(key) is not value for key, value in _BOUNDARIES.items()):
        _fail("CONTRACT_POINTER_AUTHORITY_INVALID", f"current pointer authority invalid: {path}")
    revision_id = current.get("revision_id")
    if not isinstance(revision_id, str):
        _fail("CONTRACT_POINTER_REVISION_INVALID", "current pointer has no revision id")
    revision = _load_revision(root, revision_id)
    stop = _read_stop(root, revision_id)
    # The immutable seal is written before the mutable pointer.  LIVE + seal is
    # therefore a recoverable STOPPING crash state, never permission to launch.
    if current["status"] == "STOPPED" and stop is None:
        _fail("CONTRACT_STOP_SEAL_MISSING", "stopped pointer has no immutable stop seal")
    if current["status"] == "STOPPED" and current.get("stopped_at") != stop.get("stopped_at"):
        _fail("CONTRACT_STOP_TIME_MISMATCH", "stopped pointer disagrees with immutable stop seal")
    return current, revision


def _acquire_lock(root: Path) -> Any | None:
    return _try_acquire_byte_lock(root / ".ongoing.lock")


def _fact_path(root: Path, fact_id: str) -> Path:
    _require_content_id(fact_id, code="FACT_ID_INVALID", field="fact id")
    return root / "facts" / f"{fact_id}.json"


def _write_fact(root: Path, fact: Mapping[str, Any]) -> tuple[str, bool]:
    fact_id = str(fact["fact_id"])
    path = _fact_path(root, fact_id)
    created = not path.exists()
    _write_once_json(path, dict(fact), conflict_code="FACT_CONFLICT")
    return fact_id, created


def _read_source_fact(root: Path, fact_id: str) -> dict[str, Any]:
    path = _fact_path(root, fact_id)
    value = _read_json_object(path, reason_code="FACT_INVALID")
    if (
        value.get("schema") != FACT_SCHEMA
        or value.get("fact_id") != fact_id
        or value.get("protocol_stage") != PROTOCOL_STAGE
        or any(value.get(key) is not expected for key, expected in _BOUNDARIES.items())
    ):
        _fail("FACT_INVALID", f"source fact boundary invalid: {path}")
    fact_type = value.get("fact_type")
    if fact_type in {"ACTIVATION", "INVENTORY_CHANGE"}:
        identity = {
            "contract_revision_id": value.get("contract_revision_id"),
            "fact_type": fact_type,
            "inventory_id": value.get("inventory_id"),
        }
    elif fact_type == "CONTINUATION_OBSERVATION":
        identity = {
            "contract_revision_id": value.get("contract_revision_id"),
            "fact_type": fact_type,
            "observation_id": value.get("observation_id"),
            "source_sha256": value.get("source_sha256"),
        }
    else:
        _fail("FACT_TYPE_NOT_CONTACT_SOURCE", f"fact cannot source a cognition contact: {path}")
    if _stable_id(identity) != fact_id:
        _fail("FACT_IDENTITY_INVALID", f"source fact identity mismatch: {path}")
    return value


def _opportunity_paths(root: Path, opportunity_id: str) -> tuple[Path, Path]:
    _require_content_id(opportunity_id, code="OPPORTUNITY_ID_INVALID", field="opportunity id")
    directory = root / "opportunities" / opportunity_id
    return directory / "request.json", directory / "status.json"


def _write_opportunity(
    root: Path,
    *,
    revision_id: str,
    fact: Mapping[str, Any],
    trigger_type: str,
    not_before: str,
    workspace_root: str,
    predecessor_candidate_id: str | None = None,
) -> tuple[str, bool]:
    identity = {
        "contract_revision_id": revision_id,
        "source_fact_id": fact["fact_id"],
        "trigger_type": trigger_type,
    }
    opportunity_id = _stable_id(identity)
    request = {
        "schema": OPPORTUNITY_SCHEMA,
        "opportunity_id": opportunity_id,
        **identity,
        "external_epoch_id": str(fact["fact_id"]),
        "predecessor_candidate_id": predecessor_candidate_id,
        "not_before": not_before,
        "workspace_root": workspace_root,
        "created_at": str(fact["observed_at"]),
        "candidate_only": True,
        "root_main_used": False,
        "root_main_state": "NO_ROOT_MAIN_PATH_TOUCHED",
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }
    request_path, status_path = _opportunity_paths(root, opportunity_id)
    if request_path.exists():
        existing = _read_opportunity_request(request_path)
        fixed = {
            "opportunity_id": opportunity_id,
            "contract_revision_id": revision_id,
            "source_fact_id": fact["fact_id"],
            "trigger_type": trigger_type,
            "external_epoch_id": str(fact["fact_id"]),
            "workspace_root": workspace_root,
            "created_at": str(fact["observed_at"]),
        }
        if any(existing.get(key) != expected for key, expected in fixed.items()):
            _fail(
                "OPPORTUNITY_REPLAY_IDENTITY_DRIFT",
                f"existing opportunity no longer binds its creation-time source: {request_path}",
            )
        if not status_path.exists():
            _write_opportunity_status(
                status_path,
                opportunity_id=opportunity_id,
                status="DUE",
                attempt_id=None,
                reason_code=None,
            )
        return opportunity_id, False
    _write_once_json(request_path, request, conflict_code="OPPORTUNITY_CONFLICT")
    if not status_path.exists():
        _write_opportunity_status(
            status_path,
            opportunity_id=opportunity_id,
            status="DUE",
            attempt_id=None,
            reason_code=None,
        )
    return opportunity_id, True


def _write_opportunity_status(
    path: Path,
    *,
    opportunity_id: str,
    status: str,
    attempt_id: str | None,
    reason_code: str | None,
) -> None:
    if status not in _OPPORTUNITY_STATUSES:
        _fail("OPPORTUNITY_STATUS_INVALID", f"invalid opportunity status: {status}")
    atomic_write_json(
        path,
        {
            "schema": OPPORTUNITY_STATUS_SCHEMA,
            "opportunity_id": opportunity_id,
            "status": status,
            "attempt_id": attempt_id,
            "reason_code": reason_code,
            "updated_at": _now_iso(),
            "protocol_stage": PROTOCOL_STAGE,
            **_BOUNDARIES,
        },
    )


def _read_opportunity_status(path: Path, opportunity_id: str) -> dict[str, Any]:
    value = _read_json_object(path, reason_code="OPPORTUNITY_STATUS_INVALID")
    expected = {
        "schema",
        "opportunity_id",
        "status",
        "attempt_id",
        "reason_code",
        "updated_at",
        "protocol_stage",
        *_BOUNDARIES,
    }
    _require_exact_keys(value, expected, code="OPPORTUNITY_STATUS_KEYS_INVALID")
    if (
        value.get("schema") != OPPORTUNITY_STATUS_SCHEMA
        or value.get("opportunity_id") != opportunity_id
        or value.get("status") not in _OPPORTUNITY_STATUSES
        or value.get("protocol_stage") != PROTOCOL_STAGE
        or any(value.get(key) is not expected_value for key, expected_value in _BOUNDARIES.items())
    ):
        _fail("OPPORTUNITY_STATUS_INVALID", f"opportunity status invalid: {path}")
    return value


def _parse_iso(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise OngoingError("TIMESTAMP_INVALID", f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _iso_after(value: str, seconds: int) -> str:
    return (_parse_iso(value) + dt.timedelta(seconds=seconds)).isoformat()


def _is_due(value: str) -> bool:
    return _parse_iso(_now_iso()) >= _parse_iso(value)


def _candidate_evidence_bundle(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    field = (
        "frozen_evidence_bundle" if candidate.get("schema") == CANDIDATE_SCHEMA else "exact_bundle"
    )
    value = candidate.get(field)
    if not isinstance(value, Mapping):
        _fail("CANDIDATE_BUNDLE_INVALID", f"candidate has no evidence bundle: {field}")
    return value


def _candidate_history(root: Path, revision_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "candidates").glob("*.json")):
        value = _read_json_object(path, reason_code="CANDIDATE_INVALID")
        candidate_id = _require_content_id(
            path.stem.casefold(), code="CANDIDATE_ID_INVALID", field="candidate id"
        )
        seal = value.get("candidate_seal_sha256")
        unsigned = dict(value)
        unsigned.pop("candidate_seal_sha256", None)
        evidence_bundle = _candidate_evidence_bundle(value)
        bundle_manifest_id = _require_content_id(
            evidence_bundle.get("manifest_id"),
            code="CANDIDATE_BUNDLE_INVALID",
            field="candidate bundle manifest id",
        )
        wake_inventory_id = _require_content_id(
            evidence_bundle.get("wake_inventory_id"),
            code="CANDIDATE_BUNDLE_INVALID",
            field="candidate wake inventory id",
        )
        attempt_id = _require_content_id(
            value.get("attempt_id"), code="CANDIDATE_SCHEMA_INVALID", field="attempt id"
        )
        attempt_paths = _attempt_paths(root, attempt_id)
        attempt_request = _read_json_object(
            attempt_paths["request"], reason_code="ATTEMPT_REQUEST_INVALID"
        )
        attempt_environment = _read_json_object(
            attempt_paths["environment"], reason_code="ATTEMPT_ENVIRONMENT_INVALID"
        )
        if (
            value.get("contract_revision_id") != attempt_request.get("contract_revision_id")
            or value.get("opportunity_id") != attempt_request.get("opportunity_id")
            or value.get("source_fact_id") != attempt_request.get("source_fact_id")
            or value.get("external_epoch_id") != attempt_request.get("external_epoch_id")
            or attempt_environment.get("bundle") != evidence_bundle
        ):
            _fail(
                "CANDIDATE_PROVENANCE_INVALID",
                f"candidate provenance differs from its durable attempt: {path}",
            )
        expected_identity = {
            "contract_revision_id": value.get("contract_revision_id"),
            "opportunity_id": value.get("opportunity_id"),
            "source_fact_id": value.get("source_fact_id"),
            "external_epoch_id": value.get("external_epoch_id"),
            "attempt_id": attempt_id,
            "last_message_sha256": value.get("last_message_sha256"),
            "output_sha256": _stable_id(value.get("candidate_output")),
            "wake_inventory_id": wake_inventory_id,
        }
        candidate_schema = value.get("schema")
        if candidate_schema == CANDIDATE_SCHEMA:
            expected_identity["evidence_manifest_id"] = bundle_manifest_id
            payload = value.get("candidate_payload")
            payload_sha256 = value.get("candidate_payload_sha256")
            if (
                not isinstance(payload, str)
                or not payload.strip()
                or payload_sha256 != _sha256(payload.encode("utf-8"))
            ):
                _fail("CANDIDATE_PAYLOAD_INVALID", f"candidate payload invalid: {path}")
            expected_identity["payload_sha256"] = payload_sha256
        else:
            expected_identity["exact_bundle_manifest_id"] = bundle_manifest_id
        if (
            candidate_schema not in {CANDIDATE_SCHEMA, LEGACY_CANDIDATE_SCHEMA}
            or value.get("candidate_id") != candidate_id
            or _stable_id(expected_identity) != candidate_id
            or not isinstance(seal, str)
            or seal != _sha256(canonical_json_bytes(unsigned))
            or value.get("candidate_only") is not True
            or value.get("root_main_used") is not False
            or value.get("effect_gateway_called") is not False
            or value.get("continuation_authorized") is not False
            or any(value.get(key) is not expected for key, expected in _BOUNDARIES.items())
        ):
            _fail("CANDIDATE_SCHEMA_INVALID", f"candidate schema invalid: {path}")
        if value.get("contract_revision_id") == revision_id:
            rows.append(value)

    def chronology_ordinal(row: Mapping[str, Any]) -> int:
        bundle = _candidate_evidence_bundle(row)
        history = bundle.get("candidate_history")
        ordinal = history.get("candidate_count") if isinstance(history, Mapping) else None
        if type(ordinal) is not int or ordinal < 0:
            _fail(
                "CANDIDATE_CHRONOLOGY_INVALID",
                f"candidate has no durable chronology ordinal: {row.get('candidate_id')}",
            )
        return ordinal

    ordered = sorted(
        rows,
        key=lambda row: (
            chronology_ordinal(row),
            str(row.get("completed_at", "")),
            str(row.get("candidate_id", "")),
        ),
    )
    observed_ordinals = [chronology_ordinal(row) for row in ordered]
    if observed_ordinals != list(range(len(ordered))):
        _fail(
            "CANDIDATE_CHRONOLOGY_INVALID",
            "candidate chronology ordinals are missing, duplicated, or non-contiguous",
        )
    return ordered


def _latest_candidate(root: Path, revision_id: str) -> dict[str, Any] | None:
    rows = _candidate_history(root, revision_id)
    return rows[-1] if rows else None


def _validate_candidate_history_bundle(bundle_root: Path, root: Path, revision_id: str) -> None:
    """Cross-bind the history index, durable chronology, and copied exact bytes."""

    index_path = bundle_root / "HISTORY" / "CANDIDATE_INDEX.json"
    index_raw = _stable_read(index_path)
    try:
        index = json.loads(index_raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OngoingError(
            "EXACT_BUNDLE_HISTORY_INDEX_INVALID", "candidate history index is invalid JSON"
        ) from exc
    if not isinstance(index, dict):
        _fail("EXACT_BUNDLE_HISTORY_INDEX_INVALID", "candidate history index must be an object")
    expected_keys = {
        "schema",
        "contract_revision_id",
        "candidates",
        "latest_candidate_id",
        "history_id",
        *_BOUNDARIES,
    }
    _require_exact_keys(index, expected_keys, code="EXACT_BUNDLE_HISTORY_INDEX_KEYS_INVALID")
    unsigned = dict(index)
    history_id = unsigned.pop("history_id", None)
    if (
        index.get("schema") != "xinao.research-of-research.ongoing-candidate-history.v1"
        or index.get("contract_revision_id") != revision_id
        or history_id != _stable_id(unsigned)
        or any(index.get(key) is not expected for key, expected in _BOUNDARIES.items())
    ):
        _fail(
            "EXACT_BUNDLE_HISTORY_INDEX_INVALID",
            "candidate history index identity or boundary is invalid",
        )

    expected_rows: list[dict[str, Any]] = []
    for chronology_ordinal, candidate in enumerate(_candidate_history(root, revision_id)):
        candidate_id = str(candidate["candidate_id"])
        durable_path = root / "candidates" / f"{candidate_id}.json"
        copied_path = bundle_root / "HISTORY" / "candidates" / f"{candidate_id}.json"
        durable_raw = _stable_read(durable_path)
        copied_raw = _stable_read(copied_path, expected_sha256=_sha256(durable_raw))
        if copied_raw != durable_raw:
            _fail(
                "EXACT_BUNDLE_HISTORY_BYTES_MISMATCH",
                f"copied candidate differs from durable chronology: {candidate_id}",
            )
        expected_rows.append(
            {
                "candidate_id": candidate_id,
                "chronology_ordinal": chronology_ordinal,
                "completed_at": candidate["completed_at"],
                "opportunity_id": candidate["opportunity_id"],
                "attempt_id": candidate["attempt_id"],
                "file_sha256": _sha256(durable_raw),
                "candidate_seal_sha256": candidate["candidate_seal_sha256"],
            }
        )
    expected_latest = expected_rows[-1]["candidate_id"] if expected_rows else None
    if (
        index.get("candidates") != expected_rows
        or index.get("latest_candidate_id") != expected_latest
    ):
        _fail(
            "EXACT_BUNDLE_HISTORY_CHRONOLOGY_MISMATCH",
            "candidate history index does not equal the durable chronology",
        )


def _activation_fact(revision_id: str, inventory_id: str, *, observed_at: str) -> dict[str, Any]:
    identity = {
        "contract_revision_id": revision_id,
        "fact_type": "ACTIVATION",
        "inventory_id": inventory_id,
    }
    return {
        "schema": FACT_SCHEMA,
        "fact_id": _stable_id(identity),
        **identity,
        "observed_at": observed_at,
        "external_reality": False,
        "human_appointed_activation": True,
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }


def _inventory_fact(
    revision_id: str, inventory: Mapping[str, Any], *, observed_at: str
) -> dict[str, Any]:
    identity = {
        "contract_revision_id": revision_id,
        "fact_type": "INVENTORY_CHANGE",
        "inventory_id": inventory["inventory_id"],
    }
    return {
        "schema": FACT_SCHEMA,
        "fact_id": _stable_id(identity),
        **identity,
        "wake_inventory_id": inventory["wake_inventory_id"],
        "inventory": list(inventory["entries"]),
        "observed_at": observed_at,
        "external_reality": True,
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }


def _observation_facts(
    runtime_root: Path, revision_id: str, contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    observations_root = runtime_root / "continuation" / "observations"
    for path in sorted(
        observations_root.glob("*/observation.json"), key=lambda item: item.as_posix().casefold()
    ):
        try:
            raw = _stable_read(path)
            value = json.loads(raw.decode("utf-8-sig"))
        except OngoingError:
            raise
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OngoingError(
                "CONTINUATION_OBSERVATION_INVALID", f"invalid Stage0 observation: {path}"
            ) from exc
        if not isinstance(value, dict):
            _fail(
                "CONTINUATION_OBSERVATION_INVALID", f"Stage0 observation is not an object: {path}"
            )
        observation_id = path.parent.name
        required_false = (
            "authority",
            "instruction_source",
            "continuation_authorized",
            "dispatch_allowed",
            "reentry_request_derived",
            "main_launch_authorized",
            "capacity_claim_authorized",
            "shared_effect_authorized",
            "completion_claim_allowed",
        )
        if (
            value.get("schema") != "xinao.research-of-research.continuation-observation.v0"
            or value.get("observation_id") != observation_id
            or any(value.get(key) is not False for key in required_false)
        ):
            _fail("CONTINUATION_OBSERVATION_AUTHORITY_INVALID", f"invalid Stage0 boundary: {path}")
        raw_sha = _sha256(raw)
        identity = {
            "contract_revision_id": revision_id,
            "fact_type": "CONTINUATION_OBSERVATION",
            "observation_id": observation_id,
            "source_sha256": raw_sha,
        }
        source = value.get("source") if isinstance(value.get("source"), Mapping) else {}
        eligibility = _evaluate_observation_eligibility(
            _contract_observation_eligibility(contract),
            source.get("reported_status"),
        )
        relative_receipt = source.get("relative_path")
        receipt_source_path = None
        if isinstance(relative_receipt, str):
            candidate = (runtime_root / relative_receipt).resolve(strict=False)
            if _is_within(candidate, runtime_root):
                receipt_source_path = str(candidate)
        fact_id = _stable_id(identity)
        existing_path = _fact_path(_ongoing_root(runtime_root), fact_id)
        if existing_path.is_file():
            existing = _read_source_fact(_ongoing_root(runtime_root), fact_id)
            expected_existing = {
                "source_path": str(path.resolve(strict=False)),
                "receipt_source_path": receipt_source_path,
                "reported_status": source.get("reported_status"),
                "source_sha256": raw_sha,
                "observation_id": observation_id,
                "contract_revision_id": revision_id,
            }
            if any(existing.get(key) != expected for key, expected in expected_existing.items()):
                _fail(
                    "CONTINUATION_OBSERVATION_FACT_DRIFT",
                    f"durable fact disagrees with its exact Stage0 observation: {existing_path}",
                )
            _observation_fact_eligibility(contract, existing)
            facts.append(existing)
            continue
        facts.append(
            {
                "schema": FACT_SCHEMA,
                "fact_id": fact_id,
                **identity,
                "source_path": str(path.resolve(strict=False)),
                "receipt_source_path": receipt_source_path,
                "reported_status": source.get("reported_status"),
                "cognition_eligibility": eligibility,
                "observed_at": _now_iso(),
                "external_reality": True,
                "source_non_authoritative": True,
                "protocol_stage": PROTOCOL_STAGE,
                **_BOUNDARIES,
            }
        )
    return facts


def _contract_drift_fact(
    revision: Mapping[str, Any], *, drift_sources: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    identity = {
        "contract_revision_id": revision["revision_id"],
        "fact_type": "CONTRACT_DRIFT",
        "drift_sources": list(drift_sources),
    }
    return {
        "schema": FACT_SCHEMA,
        "fact_id": _stable_id(identity),
        **identity,
        "observed_at": _now_iso(),
        "requires_new_explicit_contract": True,
        "external_reality": True,
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }


def _revalidate_contract_sources(revision: Mapping[str, Any]) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []
    bindings = [
        (
            "CONTRACT_SOURCE",
            Path(str(revision["contract_source_path"])),
            str(revision["contract_source_sha256"]),
        ),
        (
            "HUMAN_APPOINTMENT",
            Path(str(_contract_appointment(revision["contract"])["source_path"])),
            str(_contract_appointment(revision["contract"])["source_sha256"]),
        ),
    ]
    for source_type, path, expected in bindings:
        try:
            raw = _stable_read(path)
            observed: str | None = _sha256(raw)
        except OngoingError:
            observed = None
        if observed != expected:
            drift.append(
                {
                    "source_type": source_type,
                    "source_path": str(path.resolve(strict=False)),
                    "expected_sha256": expected,
                    "observed_sha256": observed,
                }
            )
    return drift


def _projection(
    root: Path,
    *,
    current: Mapping[str, Any],
    revision: Mapping[str, Any],
    inventory_id: str | None,
    new_opportunity_ids: Sequence[str],
) -> dict[str, Any]:
    facts = list((root / "facts").glob("*.json"))
    opportunities = list((root / "opportunities").glob("*/request.json"))
    attempts = list((root / "attempts").glob("*/request.json"))
    candidates = list((root / "candidates").glob("*.json"))
    statuses: dict[str, int] = {}
    for path in (root / "opportunities").glob("*/status.json"):
        value = _read_opportunity_status(path, path.parent.name)
        status = str(value["status"])
        statuses[status] = statuses.get(status, 0) + 1
    projection = {
        "schema": PROJECTION_SCHEMA,
        "contract_revision_id": current["revision_id"],
        "contract_status": "STOPPED" if _contract_is_stopped(root, current) else current["status"],
        "activation_inventory_id": revision["activation_inventory_id"],
        "current_inventory_id": inventory_id,
        "fact_count": len(facts),
        "opportunity_count": len(opportunities),
        "attempt_count": len(attempts),
        "candidate_count": len(candidates),
        "opportunity_status_counts": statuses,
        "new_opportunity_ids": sorted(new_opportunity_ids),
        "updated_at": _now_iso(),
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }
    atomic_write_json(root / "projection" / "current.json", projection)
    return projection


def initialize_ongoing_contract(runtime_root: Path, contract_path: Path) -> dict[str, Any]:
    """Bind exact human contract bytes and freeze the activation inventory."""

    runtime_root = runtime_root.resolve(strict=False)
    root = _ongoing_root(runtime_root)
    contract_path = contract_path.resolve(strict=True)
    raw = _stable_read(contract_path)
    contract_source_sha = _sha256(raw)
    try:
        supplied = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OngoingError(
            "CONTRACT_JSON_INVALID", f"invalid ongoing contract JSON: {contract_path}"
        ) from exc
    if not isinstance(supplied, dict):
        _fail("CONTRACT_JSON_OBJECT_REQUIRED", "ongoing contract must be a JSON object")
    contract = _validate_contract(supplied, runtime_root=runtime_root)

    guard = _acquire_lock(root)
    if guard is None:
        return {"outcome": "LOCK_BUSY", "created": False, **_BOUNDARIES}
    try:
        current_path = root / "contracts" / "current.json"
        prior_current: dict[str, Any] | None = None
        if current_path.is_file():
            prior_current, prior_revision = _load_current(root)
            prior_stop = _read_stop(root, str(prior_current["revision_id"]))
            if prior_stop is not None and prior_current["status"] == "LIVE":
                prior_current = {
                    **prior_current,
                    "status": "STOPPED",
                    "stopped_at": prior_stop["stopped_at"],
                }
                atomic_write_json(current_path, prior_current)
            if prior_current["status"] == "LIVE":
                if prior_revision.get("contract_source_sha256") == contract_source_sha:
                    return {
                        "outcome": "BOUND",
                        "created": False,
                        "revision_id": prior_current["revision_id"],
                        "activation_inventory_id": prior_revision["activation_inventory_id"],
                        **_BOUNDARIES,
                    }
                _fail(
                    "CONTRACT_ALREADY_BOUND", "a different LIVE ongoing contract is already bound"
                )
            if prior_revision.get("contract_source_sha256") == contract_source_sha:
                _fail(
                    "CONTRACT_REVISION_STOPPED",
                    "a stopped revision cannot be republished; bind a new explicit contract",
                )

        source_copy = root / "contracts" / "sources" / f"{contract_source_sha}.json"
        _write_once_bytes(source_copy, raw, conflict_code="CONTRACT_SOURCE_CONFLICT")

        unpublished = []
        for path in sorted((root / "contracts" / "revisions").glob("*.json")):
            value = _load_revision(root, path.stem.casefold())
            stop_path = root / "contracts" / "stops" / f"{path.stem.casefold()}.json"
            if (
                value.get("contract_source_sha256") == contract_source_sha
                and not stop_path.exists()
            ):
                unpublished.append(value)
        if len(unpublished) > 1:
            _fail("CONTRACT_UNPUBLISHED_AMBIGUOUS", "multiple revisions bind the same source bytes")
        if unpublished:
            revision = unpublished[0]
            revision_id = str(revision["revision_id"])
        else:
            inventory = _inventory_sources(contract)
            revision = {
                "schema": CONTRACT_REVISION_SCHEMA,
                "contract_source_path": str(contract_path),
                "contract_source_sha256": contract_source_sha,
                "contract": contract,
                "activation_inventory_id": inventory["inventory_id"],
                "activation_wake_inventory_id": inventory["wake_inventory_id"],
                "activation_inventory": inventory["entries"],
                "activation_observed_at": _now_iso(),
                "protocol_stage": PROTOCOL_STAGE,
                "candidate_only": True,
                "root_main_used": False,
                "root_main_state": "NO_ROOT_MAIN_PATH_TOUCHED",
                **_BOUNDARIES,
            }
            revision_raw = canonical_json_bytes(revision)
            revision_id = _sha256(revision_raw)
            _write_once_bytes(
                root / "contracts" / "revisions" / f"{revision_id}.json",
                revision_raw,
                conflict_code="CONTRACT_REVISION_CONFLICT",
            )
            revision = {**revision, "revision_id": revision_id}

        activation_time = str(revision["activation_observed_at"])
        activation = _activation_fact(
            revision_id, str(revision["activation_inventory_id"]), observed_at=activation_time
        )
        _write_fact(root, activation)
        opportunity_id, _ = _write_opportunity(
            root,
            revision_id=revision_id,
            fact=activation,
            trigger_type="ACTIVATION",
            not_before=activation_time,
            workspace_root=str(_contract_clean_room(contract)["workspace_root"]),
        )
        current = {
            "schema": CONTRACT_POINTER_SCHEMA,
            "revision_id": revision_id,
            "status": "LIVE",
            "published_at": activation_time,
            "protocol_stage": PROTOCOL_STAGE,
            **_BOUNDARIES,
        }
        atomic_write_json(current_path, current)
        _projection(
            root,
            current=current,
            revision={**revision, "revision_id": revision_id},
            inventory_id=str(revision["activation_inventory_id"]),
            new_opportunity_ids=[opportunity_id],
        )
        return {
            "outcome": "BOUND",
            "created": True,
            "revision_id": revision_id,
            "activation_inventory_id": revision["activation_inventory_id"],
            "activation_opportunity_id": opportunity_id,
            **_BOUNDARIES,
        }
    finally:
        _release_byte_lock(guard)


def _attempt_paths(root: Path, attempt_id: str) -> dict[str, Path]:
    _require_content_id(attempt_id, code="ATTEMPT_ID_INVALID", field="attempt id")
    directory = root / "attempts" / attempt_id
    return {
        "directory": directory,
        "request": directory / "request.json",
        "status": directory / "status.json",
        "prompt": directory / "prompt.txt",
        "stdout": directory / "trajectory.jsonl",
        "stderr": directory / "stderr.txt",
        "last_message": directory / "last_message.json",
        "trajectory_index": directory / "trajectory_index.jsonl",
        "arguments": directory / "codex_args.json",
        "output_schema": directory / "output_schema.json",
        "command": directory / "command.json",
        "launcher": directory / "isolated-launcher.ps1",
        "environment": directory / "environment.json",
        "lease_identity": directory / "lease_identity.json",
        "runner_request": directory / "runner_request.json",
        "runner_launch_intent": directory / "runner_launch_intent.json",
        "runner_spawn": directory / "runner_spawn.json",
        "runner_started": directory / "runner_started.json",
        "runner_terminal": directory / "runner_terminal.json",
        "runner_stdout": directory / "runner_stdout.txt",
        "runner_stderr": directory / "runner_stderr.txt",
    }


def _attempt_status_value(
    *,
    attempt_id: str,
    opportunity_id: str,
    status: str,
    child_pid: int | None = None,
    runner_pid: int | None = None,
    account_slot: str | None = None,
    lease: Mapping[str, Any] | None = None,
    reason_code: str | None = None,
    exit_code: int | None = None,
    session_id: str | None = None,
    candidate_id: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> dict[str, Any]:
    if status not in _ATTEMPT_STATUSES:
        _fail("ATTEMPT_STATUS_INVALID", f"invalid attempt status: {status}")
    return {
        "schema": ATTEMPT_STATUS_SCHEMA,
        "attempt_id": attempt_id,
        "opportunity_id": opportunity_id,
        "status": status,
        "child_pid": child_pid,
        "runner_pid": runner_pid,
        "account_slot": account_slot,
        "lease": dict(lease) if lease is not None else None,
        "reason_code": reason_code,
        "exit_code": exit_code,
        "session_id": session_id,
        "candidate_id": candidate_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "updated_at": _now_iso(),
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }


def _write_attempt_status(path: Path, **kwargs: Any) -> dict[str, Any]:
    value = _attempt_status_value(**kwargs)
    atomic_write_json(path, value)
    return value


def _read_attempt_status(path: Path) -> dict[str, Any]:
    value = _read_json_object(path, reason_code="ATTEMPT_STATUS_INVALID")
    expected = {
        "schema",
        "attempt_id",
        "opportunity_id",
        "status",
        "child_pid",
        "runner_pid",
        "account_slot",
        "lease",
        "reason_code",
        "exit_code",
        "session_id",
        "candidate_id",
        "started_at",
        "ended_at",
        "updated_at",
        "protocol_stage",
        *_BOUNDARIES,
    }
    _require_exact_keys(value, expected, code="ATTEMPT_STATUS_KEYS_INVALID")
    if (
        value.get("schema") != ATTEMPT_STATUS_SCHEMA
        or value.get("status") not in _ATTEMPT_STATUSES
        or value.get("protocol_stage") != PROTOCOL_STAGE
        or path.parent.name != value.get("attempt_id")
        or any(value.get(key) is not expected_value for key, expected_value in _BOUNDARIES.items())
    ):
        _fail("ATTEMPT_STATUS_INVALID", f"attempt status invalid: {path}")
    return value


def _next_attempt(
    root: Path, opportunity: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Path]]:
    opportunity_id = str(opportunity["opportunity_id"])
    prior: list[tuple[int, dict[str, Any], dict[str, Path]]] = []
    for path in (root / "attempts").glob("*/request.json"):
        value = _read_json_object(path, reason_code="ATTEMPT_REQUEST_INVALID")
        if value.get("opportunity_id") == opportunity_id:
            _validate_attempt_request(value, root=root, opportunity=opportunity)
            ordinal = int(value["ordinal"])
            prior.append((ordinal, value, _attempt_paths(root, str(value["attempt_id"]))))
    prior.sort(key=lambda item: item[0])
    if [item[0] for item in prior] != list(range(1, len(prior) + 1)):
        _fail(
            "ATTEMPT_ORDINALS_INVALID",
            f"attempt ordinals are missing or duplicated for opportunity {opportunity_id}",
        )
    if prior:
        _, latest_request, latest_paths = prior[-1]
        if not latest_paths["status"].exists():
            observed_files = {
                path.name for path in latest_paths["directory"].iterdir() if path.is_file()
            }
            if observed_files != {latest_paths["request"].name}:
                _fail(
                    "ATTEMPT_REQUEST_ONLY_STATE_INVALID",
                    "attempt request without status has additional durable artifacts",
                )
            # The request is published before CLAIMING_COMPUTE.  Reusing this
            # exact immutable request repairs that crash boundary without
            # consuming retry budget or manufacturing a new attempt identity.
            return latest_request, latest_paths
    ordinal = len(prior) + 1
    attempt_id = _stable_id({"opportunity_id": opportunity_id, "ordinal": ordinal})
    paths = _attempt_paths(root, attempt_id)
    workspace = Path(str(opportunity["workspace_root"])) / f"ror-{attempt_id}"
    request = {
        "schema": ATTEMPT_SCHEMA,
        "attempt_id": attempt_id,
        "opportunity_id": opportunity_id,
        "contract_revision_id": opportunity["contract_revision_id"],
        "source_fact_id": opportunity["source_fact_id"],
        "external_epoch_id": opportunity["external_epoch_id"],
        "ordinal": ordinal,
        "workspace": str(workspace.resolve(strict=False)),
        "attempt_directory": str(paths["directory"].resolve(strict=False)),
        "trajectory_path": str(paths["stdout"].resolve(strict=False)),
        "stderr_path": str(paths["stderr"].resolve(strict=False)),
        "last_message_path": str(paths["last_message"].resolve(strict=False)),
        "created_at": _now_iso(),
        "fresh_session_only": True,
        "resume_session_id": None,
        "root_main_used": False,
        "root_main_state": "NO_ROOT_MAIN_PATH_TOUCHED",
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }
    _write_once_json(paths["request"], request, conflict_code="ATTEMPT_REQUEST_CONFLICT")
    return request, paths


def _claim_capacity(
    contract: Mapping[str, Any], *, attempt_id: str, opportunity_id: str, workspace: Path
) -> dict[str, Any]:
    errors: list[str] = []
    quotas = {
        str(account_slot): AccountQuota(
            account_slot=str(account_slot),
            quota_root=DEFAULT_QUOTA_ROOT,
            limit=4,
            run_id=attempt_id,
            reclaim_bound_leases=False,
        )
        for account_slot in _contract_account_order(contract)
    }
    pending_accounts = set(quotas)
    capacity_busy_accounts: set[str] = set()
    deadline = time.monotonic() + _CAPACITY_ADMISSION_LOCK_TIMEOUT_SECONDS
    while pending_accounts:
        lock_busy_accounts: set[str] = set()
        for account_slot, quota in quotas.items():
            if account_slot not in pending_accounts:
                continue
            try:
                result = quota.try_claim_outcome(lineage_id=opportunity_id, workspace=workspace)
            except Exception as exc:
                errors.append(f"{account_slot}:{type(exc).__name__}:{exc}")
                pending_accounts.remove(account_slot)
                continue
            outcome = str(result.get("outcome"))
            if outcome == "CLAIMED":
                return {"outcome": "CLAIMED", "quota": quota, "lease": result["lease"]}
            if outcome == "CAPACITY_BUSY":
                capacity_busy_accounts.add(account_slot)
                pending_accounts.remove(account_slot)
                continue
            if outcome == "LOCK_BUSY":
                lock_busy_accounts.add(account_slot)
                continue
            errors.append(f"{account_slot}:QUOTA_CLAIM_OUTCOME_INVALID:{outcome}")
            pending_accounts.remove(account_slot)
        if not lock_busy_accounts:
            break
        if time.monotonic() >= deadline:
            errors.extend(
                f"{account_slot}:QUOTA_ADMISSION_LOCK_TIMEOUT"
                for account_slot in sorted(lock_busy_accounts)
            )
            break
        time.sleep(_CAPACITY_ADMISSION_RETRY_DELAY_SECONDS)
    if errors:
        return {"outcome": "UNKNOWN", "reason_code": "COMPUTE_UNKNOWN", "detail": errors}
    if capacity_busy_accounts == set(quotas):
        return {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"}
    return {
        "outcome": "UNKNOWN",
        "reason_code": "COMPUTE_UNKNOWN",
        "detail": ["QUOTA_ADMISSION_STATE_INCOMPLETE"],
    }


def _release_capacity(quota: Any, lease: Mapping[str, Any]) -> str:
    return str(quota.release(lease))


def _copy_trigger_evidence(
    *,
    runtime_root: Path,
    root: Path,
    bundle_root: Path,
    fact: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Freeze the exact fact and, for Stage0, its observation and receipt bytes."""

    entries: list[dict[str, Any]] = []

    def copy_one(source: Path, export_path: str, expected_sha256: str | None = None) -> bytes:
        raw = _stable_read(source, expected_sha256=expected_sha256)
        destination = (bundle_root / export_path).resolve(strict=False)
        if not _is_within(destination, bundle_root):
            _fail("TRIGGER_EXPORT_ESCAPE", f"trigger export escaped bundle: {export_path}")
        atomic_write_bytes(destination, raw)
        entries.append(
            {
                "group": "trigger",
                "source_path": str(source.resolve(strict=False)),
                "export_path": export_path,
                "state": "PRESENT",
                "size": len(raw),
                "sha256": _sha256(raw),
            }
        )
        return raw

    fact_id = str(fact["fact_id"])
    fact_path = _fact_path(root, fact_id)
    fact_raw = copy_one(fact_path, "TRIGGER/ongoing_fact.json")
    if json.loads(fact_raw.decode("utf-8-sig")) != dict(fact):
        _fail("TRIGGER_FACT_BYTES_MISMATCH", "trigger fact bytes differ from validated fact")

    if fact.get("fact_type") != "CONTINUATION_OBSERVATION":
        return entries

    observation_id = _require_content_id(
        fact.get("observation_id"),
        code="TRIGGER_OBSERVATION_ID_INVALID",
        field="trigger observation id",
    )
    expected_observation_path = (
        runtime_root / "continuation" / "observations" / observation_id / "observation.json"
    ).resolve(strict=False)
    supplied_observation_path = Path(str(fact.get("source_path"))).resolve(strict=False)
    if supplied_observation_path != expected_observation_path:
        _fail("TRIGGER_OBSERVATION_PATH_INVALID", "Stage0 observation path is not canonical")
    observation_raw = copy_one(
        expected_observation_path,
        "TRIGGER/continuation_observation.json",
        str(fact.get("source_sha256")),
    )
    try:
        observation = json.loads(observation_raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OngoingError("TRIGGER_OBSERVATION_INVALID", "Stage0 observation is invalid") from exc
    if not isinstance(observation, dict) or observation.get("observation_id") != observation_id:
        _fail("TRIGGER_OBSERVATION_INVALID", "Stage0 observation identity mismatch")
    source = observation.get("source")
    if not isinstance(source, Mapping):
        _fail("TRIGGER_OBSERVATION_SOURCE_INVALID", "Stage0 observation has no source record")
    if source.get("reported_status") != fact.get("reported_status"):
        _fail(
            "TRIGGER_OBSERVATION_STATUS_MISMATCH",
            "Stage0 observation and durable fact disagree on reported status",
        )
    relative_path = source.get("relative_path")
    receipt_sha = str(source.get("receipt_file_sha256", "")).casefold()
    if not isinstance(relative_path, str) or not _HEX_SHA256.fullmatch(receipt_sha):
        _fail("TRIGGER_RECEIPT_BINDING_INVALID", "Stage0 observation has no exact receipt binding")
    receipt_path = (runtime_root / relative_path).resolve(strict=False)
    if not _is_within(receipt_path, runtime_root):
        _fail("TRIGGER_RECEIPT_PATH_ESCAPE", "Stage0 receipt escaped runtime root")
    if str(fact.get("receipt_source_path")) != str(receipt_path):
        _fail("TRIGGER_RECEIPT_PATH_INVALID", "fact and observation disagree on receipt path")
    copy_one(receipt_path, "TRIGGER/run_receipt.json", receipt_sha)
    return entries


def _freeze_reentry_evidence(
    contract: Mapping[str, Any],
    revision: Mapping[str, Any],
    inventory: Mapping[str, Any],
    workspace: Path,
    *,
    source_identity: Mapping[str, Any],
    runtime_root: Path | None = None,
    root: Path | None = None,
    trigger_fact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    wake_inventory_id = _inventory_wake_id(contract, inventory)
    bundle_root = workspace / BUNDLE_RELATIVE_ROOT
    if bundle_root.exists():
        _fail(
            "EXACT_BUNDLE_ALREADY_EXISTS",
            f"frozen re-entry evidence bundle already exists: {bundle_root}",
        )
    bundle_root.mkdir(parents=True, exist_ok=False)
    manifest_entries: list[dict[str, Any]] = []
    export_paths: set[str] = set()
    for entry in inventory["entries"]:
        export_path = str(entry["export_path"])
        if export_path.casefold() in export_paths:
            _fail("EXACT_BUNDLE_EXPORT_COLLISION", f"duplicate export path: {export_path}")
        export_paths.add(export_path.casefold())
        manifest_entry = {
            "group": entry["group"],
            "source_path": entry["source_path"],
            "export_path": export_path,
            "state": entry["state"],
            "size": entry["size"],
            "sha256": entry["sha256"],
        }
        if entry["state"] == "PRESENT":
            source = Path(str(entry["source_path"]))
            raw = _stable_read(source, expected_sha256=str(entry["sha256"]))
            if len(raw) != int(entry["size"]):
                _fail("SOURCE_SIZE_DRIFT_DURING_FREEZE", f"source size changed: {source}")
            destination = (bundle_root / export_path).resolve(strict=False)
            if not _is_within(destination, bundle_root):
                _fail("EXACT_BUNDLE_EXPORT_ESCAPE", f"export path escaped bundle: {export_path}")
            atomic_write_bytes(destination, raw)
        manifest_entries.append(manifest_entry)
    history_rows: list[dict[str, Any]] = []
    durable_history = (
        _candidate_history(root, str(revision["revision_id"])) if root is not None else []
    )
    for chronology_ordinal, candidate in enumerate(durable_history):
        candidate_id = str(candidate["candidate_id"])
        source = root / "candidates" / f"{candidate_id}.json"
        raw = _stable_read(source)
        export_path = f"HISTORY/candidates/{candidate_id}.json"
        destination = (bundle_root / export_path).resolve(strict=False)
        atomic_write_bytes(destination, raw)
        manifest_entries.append(
            {
                "group": "candidate_history",
                "source_path": str(source.resolve(strict=False)),
                "export_path": export_path,
                "state": "PRESENT",
                "size": len(raw),
                "sha256": _sha256(raw),
            }
        )
        export_paths.add(export_path.casefold())
        history_rows.append(
            {
                "candidate_id": candidate_id,
                "chronology_ordinal": chronology_ordinal,
                "completed_at": candidate["completed_at"],
                "opportunity_id": candidate["opportunity_id"],
                "attempt_id": candidate["attempt_id"],
                "file_sha256": _sha256(raw),
                "candidate_seal_sha256": candidate["candidate_seal_sha256"],
            }
        )
    history_unsigned = {
        "schema": "xinao.research-of-research.ongoing-candidate-history.v1",
        "contract_revision_id": revision["revision_id"],
        "candidates": history_rows,
        "latest_candidate_id": history_rows[-1]["candidate_id"] if history_rows else None,
        "authority": False,
        "shared_effect_authorized": False,
        "completion_claim_allowed": False,
    }
    history_index = {**history_unsigned, "history_id": _stable_id(history_unsigned)}
    history_index_path = bundle_root / "HISTORY" / "CANDIDATE_INDEX.json"
    atomic_write_json(history_index_path, history_index)
    history_index_raw = _stable_read(history_index_path)
    manifest_entries.append(
        {
            "group": "candidate_history",
            "source_path": str(history_index_path.resolve(strict=False)),
            "export_path": "HISTORY/CANDIDATE_INDEX.json",
            "state": "PRESENT",
            "size": len(history_index_raw),
            "sha256": _sha256(history_index_raw),
        }
    )
    export_paths.add("history/candidate_index.json")
    trigger_entries: list[dict[str, Any]] = []
    if runtime_root is not None and root is not None and trigger_fact is not None:
        trigger_entries = _copy_trigger_evidence(
            runtime_root=runtime_root,
            root=root,
            bundle_root=bundle_root,
            fact=trigger_fact,
        )
    for entry in trigger_entries:
        if str(entry["export_path"]).casefold() in export_paths:
            _fail("EXACT_BUNDLE_EXPORT_COLLISION", f"duplicate export path: {entry['export_path']}")
        export_paths.add(str(entry["export_path"]).casefold())
        manifest_entries.append(entry)
    unsigned = {
        "schema": BUNDLE_MANIFEST_SCHEMA,
        "inventory_id": inventory["inventory_id"],
        "wake_inventory_id": wake_inventory_id,
        "trigger_fact_id": trigger_fact["fact_id"] if trigger_fact is not None else None,
        "trigger_fact_type": trigger_fact["fact_type"] if trigger_fact is not None else None,
        "entries": manifest_entries,
        "git_identity": dict(source_identity),
        "bound_reentry_contract": {
            "contract_revision_id": revision["revision_id"],
            "contract_source_path": revision["contract_source_path"],
            "contract_source_sha256": revision["contract_source_sha256"],
            "contract": contract,
        },
        "evidence_scope": "CONTRACT_SELECTED_REENTRY_EVIDENCE",
        "coverage_claim": "PARTIAL",
        "snapshot_atomicity": "PER_FILE_STABLE_NO_GLOBAL_ATOMICITY",
        "instruction_authority": False,
        "cognition_authority": False,
        "source_repository_is_cognition_body": True,
        "evidence_frame_replaces_repository_world": False,
        "candidate_only": True,
        "root_main_used": False,
        "root_main_state": "NO_ROOT_MAIN_PATH_TOUCHED",
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }
    manifest_id = _stable_id(unsigned)
    manifest = {**unsigned, "manifest_id": manifest_id}
    manifest_path = bundle_root / "MANIFEST.json"
    atomic_write_json(manifest_path, manifest)
    return {
        "manifest_id": manifest_id,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path).casefold(),
        "inventory_id": inventory["inventory_id"],
        "wake_inventory_id": wake_inventory_id,
        "entries": manifest_entries,
        "bundle_root": str(bundle_root),
        "candidate_history": {
            "history_id": history_index["history_id"],
            "index_path": str(history_index_path),
            "index_sha256": _sha256(history_index_raw),
            "candidate_count": len(history_rows),
        },
    }


def _prepare_attempt_environment(
    runtime_root: Path,
    root: Path,
    contract: Mapping[str, Any],
    revision: Mapping[str, Any],
    inventory: Mapping[str, Any],
    trigger_fact: Mapping[str, Any],
    attempt: Mapping[str, Any],
    paths: Mapping[str, Path],
) -> dict[str, Any]:
    clean_room = _contract_clean_room(contract)
    source_repo = Path(str(clean_room["source_repo"]))
    source_identity = validate_source_repo(source_repo)
    workspace = Path(str(attempt["workspace"]))
    clone_identity = clone_isolated_repo(source_repo, workspace, str(source_identity["head"]))
    after = validate_source_repo(source_repo)
    if after != source_identity:
        _fail("SOURCE_REPO_DRIFT_DURING_CLONE", "clean-room source repository changed during clone")
    source_launcher_path = Path(str(clean_room["launcher_path"]))
    source_launcher_raw = _stable_read(source_launcher_path)
    launcher_identity = create_world_isolated_launcher(
        source_launcher_path,
        paths["launcher"],
        network_access=False,
    )
    launcher_identity = {
        **dict(launcher_identity),
        "source_path": str(source_launcher_path.resolve(strict=True)),
        "source_sha256": _sha256(source_launcher_raw),
    }
    launcher_identity = _harden_attempt_launcher(paths["launcher"], launcher_identity)
    workspace_git_config = _artifact_ref(workspace / ".git" / "config")
    bundle = _freeze_reentry_evidence(
        contract,
        revision,
        inventory,
        workspace,
        runtime_root=runtime_root,
        root=root,
        trigger_fact=trigger_fact,
        source_identity=source_identity,
    )
    environment = {
        "workspace": str(workspace),
        "source_identity": source_identity,
        "clone_identity": clone_identity,
        "launcher_identity": launcher_identity,
        "workspace_git_config": workspace_git_config,
        "bundle": bundle,
    }
    manifest = _read_json_object(
        Path(str(bundle["manifest_path"])), reason_code="EXACT_BUNDLE_MANIFEST_INVALID"
    )
    _validate_prepared_clone(workspace, environment, manifest)
    return environment


def _harden_attempt_launcher(path: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    """Remove ambient Git credential/write escape from only this frozen launcher."""

    raw = path.read_bytes()
    seam = (
        b"& $codexExe --cd $launchWorkdir --sandbox workspace-write "
        b"-c 'approval_policy=\"never\"' "
        b"-c 'sandbox_workspace_write.network_access=false' "
        b"@slotSpecificCodexArgs @CodexArgs"
    )
    if raw.count(seam) != 1:
        _fail("ATTEMPT_LAUNCHER_HARDENING_SEAM_MISMATCH", f"launcher seam invalid: {path}")
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    diagnostic_block = newline.join(
        (
            b'Write-Host "CODEX $AccountSlot | one shared clean-room runtime | credential $AccountSlot" -ForegroundColor Cyan',
            b'Write-Host "SHARED_RUNTIME=$canonicalCodexHome"',
            b'Write-Host "CODEX_HOME=$codexHome"',
            b'Write-Host "WORKDIR=$launchWorkdir"',
            b'Write-Host "MODEL=gpt-5.6-sol"',
            b"Write-Host \"AUTH=$(if ($hasAuth) { 'present (clean-room carrier)' } else { 'missing - login required' })\"",
            b'Write-Host ""',
        )
    )
    diagnostic_count = raw.count(diagnostic_block)
    if diagnostic_count > 1:
        _fail("ATTEMPT_LAUNCHER_DIAGNOSTIC_SEAM_MISMATCH", f"launcher diagnostics invalid: {path}")
    without_diagnostics = raw.replace(diagnostic_block, b"", 1) if diagnostic_count == 1 else raw
    block = newline.join(
        (
            b'$env:GIT_CONFIG_NOSYSTEM = "1"',
            b'$env:GIT_TERMINAL_PROMPT = "0"',
            b'$env:GCM_INTERACTIVE = "Never"',
            b'$env:GIT_ASKPASS = ""',
            b'$env:SSH_ASKPASS = ""',
            b'$env:GIT_CONFIG_COUNT = "1"',
            b'$env:GIT_CONFIG_KEY_0 = "credential.helper"',
            b'$env:GIT_CONFIG_VALUE_0 = ""',
            b"& $codexExe --cd $launchWorkdir --sandbox workspace-write "
            b"-c 'approval_policy=\"never\"' "
            b"-c 'sandbox_workspace_write.network_access=false' "
            b"@slotSpecificCodexArgs @CodexArgs",
        )
    )
    hardened = without_diagnostics.replace(seam, block, 1)
    digest = atomic_write_bytes(path, hardened)
    return {
        **dict(identity),
        "sha256": digest,
        "network_access": False,
        "git_system_config_disabled": True,
        "git_credential_helper_disabled": True,
        "git_terminal_prompt_disabled": True,
        "credential_isolation_scope": "ATTEMPT_PROCESS_ENVIRONMENT_NOT_OS_IDENTITY",
        "network_boundary": "MODEL_NETWORK_DISABLED_EXTERNAL_RESEARCH_MUST_BE_FROZEN_EVIDENCE",
        "stdout_diagnostics_suppressed": diagnostic_count == 1,
    }


def _output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "payload",
            "authority",
            "shared_effect_authorized",
            "completion_claim_allowed",
        ],
        "properties": {
            "payload": {"type": "string"},
            "authority": {"type": "boolean", "const": False},
            "shared_effect_authorized": {"type": "boolean", "const": False},
            "completion_claim_allowed": {"type": "boolean", "const": False},
        },
    }


def _build_prompt(
    contract: Mapping[str, Any],
    revision: Mapping[str, Any],
    opportunity: Mapping[str, Any],
    trigger_fact: Mapping[str, Any],
    bundle: Mapping[str, Any],
    prior_candidate: Mapping[str, Any] | None,
) -> str:
    appointment = _contract_appointment(contract)
    appointment_quote = json.dumps(str(appointment["quoted_words"]), ensure_ascii=False)
    prior_id = str(prior_candidate["candidate_id"]) if prior_candidate is not None else "NONE"
    trigger_path = Path(str(bundle["bundle_root"])) / "TRIGGER" / "ongoing_fact.json"
    return f"""You are one fresh Sol cognition contact for an explicitly appointed, candidate-only research-of-research re-entry opportunity.

The current working directory is an isolated clone of the clean-room repository at the exact source
HEAD recorded in the manifest. That repository is the cognition/reality body for this contact. Follow
its own AGENTS and entry semantics. S has selected no research question, representation, hypothesis,
method, or scientific output vocabulary for you.

Mechanical identities:
- contract revision: {revision["revision_id"]}
- exact human appointment quote: {appointment_quote}
- human appointment source sha256: {appointment["source_sha256"]}
- opportunity: {opportunity["opportunity_id"]}
- trigger: {opportunity["trigger_type"]} observed at {trigger_fact["observed_at"]}
- trigger fact id: {trigger_fact["fact_id"]}
- frozen evidence manifest: {bundle["manifest_path"]}
- manifest id: {bundle["manifest_id"]}
- trigger fact bytes: {trigger_path}
- candidate-history index: {bundle["candidate_history"]["index_path"]}
- prior candidate id: {prior_id}

The evidence frame is contract-selected re-entry evidence. Its PRESENT entries are exact per-file
bytes at freeze time, but its coverage is partial and it is not a globally atomic snapshot, the whole
current reality, an instruction source, or a substitute for the repository world. Decide for yourself
what is relevant, what else in the repository must be read, and how to use your available tools.

Direct model network access is mechanically disabled. Work only inside this isolated workspace. Do
not touch shared production, real money, credentials, root-main, existing sessions/world state, or an
effect gateway. This contact cannot authorize another contact or wake itself; later compute requires a
separate mechanical external fact or explicit appointment.

Return exactly one JSON object matching the supplied transport schema. Put your candidate in the
payload string in whatever representation you judge useful. The carrier treats payload as opaque
content and will not parse it for research meaning. authority, shared_effect_authorized, and
completion_claim_allowed must all be false.
"""


def _validate_final_output(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("FINAL_OUTPUT_OBJECT_REQUIRED", "final output must be a JSON object")
    required = set(_output_schema()["required"])
    _require_exact_keys(value, required, code="FINAL_OUTPUT_KEYS_INVALID")
    _require_string(value.get("payload"), code="FINAL_PAYLOAD_INVALID", field="payload")
    if any(value.get(key) is not False for key in _BOUNDARIES):
        _fail("FINAL_AUTHORITY_INVALID", "candidate authority boundary must remain false")
    return dict(value)


def _read_opportunity_request(path: Path) -> dict[str, Any]:
    value = _read_json_object(path, reason_code="OPPORTUNITY_REQUEST_INVALID")
    expected = {
        "schema",
        "opportunity_id",
        "contract_revision_id",
        "source_fact_id",
        "trigger_type",
        "external_epoch_id",
        "predecessor_candidate_id",
        "not_before",
        "workspace_root",
        "created_at",
        "candidate_only",
        "root_main_used",
        "root_main_state",
        "protocol_stage",
        *_BOUNDARIES,
    }
    _require_exact_keys(value, expected, code="OPPORTUNITY_REQUEST_KEYS_INVALID")
    identity = {
        "contract_revision_id": value.get("contract_revision_id"),
        "source_fact_id": value.get("source_fact_id"),
        "trigger_type": value.get("trigger_type"),
    }
    expected_id = _stable_id(identity)
    if (
        value.get("schema") != OPPORTUNITY_SCHEMA
        or value.get("opportunity_id") != path.parent.name
        or value.get("opportunity_id") != expected_id
        or value.get("external_epoch_id") != value.get("source_fact_id")
        or value.get("protocol_stage") != PROTOCOL_STAGE
        or value.get("candidate_only") is not True
        or value.get("root_main_used") is not False
        or value.get("root_main_state") != "NO_ROOT_MAIN_PATH_TOUCHED"
        or any(value.get(key) is not expected_value for key, expected_value in _BOUNDARIES.items())
    ):
        _fail("OPPORTUNITY_REQUEST_INVALID", f"opportunity request invalid: {path}")
    _require_content_id(
        value.get("contract_revision_id"),
        code="OPPORTUNITY_REQUEST_INVALID",
        field="opportunity contract revision id",
    )
    _require_content_id(
        value.get("source_fact_id"),
        code="OPPORTUNITY_REQUEST_INVALID",
        field="opportunity source fact id",
    )
    workspace_root = _absolute_path(
        value.get("workspace_root"),
        code="OPPORTUNITY_WORKSPACE_ROOT_INVALID",
        field="opportunity workspace_root",
    )
    if _is_reparse(workspace_root):
        _fail("OPPORTUNITY_WORKSPACE_ROOT_INVALID", "opportunity workspace root is reparse")
    return value


def _lease_identity(root: Path, attempt_id: str) -> dict[str, Any]:
    path = _attempt_paths(root, attempt_id)["lease_identity"]
    value = _read_json_object(path, reason_code="LEASE_IDENTITY_INVALID")
    required = {
        "schema",
        "attempt_id",
        "opportunity_id",
        "job_identity",
        "account_slot",
        "slot",
        "limit",
        "lease_id",
        "lease_path",
        "reserved_lease",
        "created_at",
        "protocol_stage",
        *_BOUNDARIES,
    }
    _require_exact_keys(value, required, code="LEASE_IDENTITY_KEYS_INVALID")
    account = value.get("account_slot")
    slot = value.get("slot")
    if account not in {"A", "C"} or type(slot) is not int or not 1 <= slot <= 4:
        _fail("LEASE_IDENTITY_INVALID", f"lease account/slot invalid: {path}")
    opportunity_id = _require_content_id(
        value.get("opportunity_id"),
        code="LEASE_IDENTITY_INVALID",
        field="lease opportunity id",
    )
    lease_id = _require_string(
        value.get("lease_id"), code="LEASE_IDENTITY_INVALID", field="lease id"
    )
    expected_path = (
        DEFAULT_QUOTA_ROOT.resolve(strict=False) / str(account) / f"world-turn-{slot:02d}.json"
    )
    if Path(str(value.get("lease_path"))).resolve(strict=False) != expected_path:
        _fail("LEASE_PATH_INVALID", f"lease path is not the exact quota slot: {path}")
    if (
        value.get("schema") != "xinao.research-of-research.ongoing-lease-identity.v1"
        or value.get("attempt_id") != attempt_id
        or value.get("limit") != 4
        or value.get("protocol_stage") != PROTOCOL_STAGE
    ):
        _fail("LEASE_IDENTITY_INVALID", f"lease attempt identity invalid: {path}")
    if any(value.get(key) is not expected_value for key, expected_value in _BOUNDARIES.items()):
        _fail("LEASE_IDENTITY_AUTHORITY_INVALID", f"lease identity authority invalid: {path}")
    _validate_job_identity(value.get("job_identity"), attempt_id=attempt_id)
    _parse_iso(str(value.get("created_at")))

    reserved = value.get("reserved_lease")
    if not isinstance(reserved, Mapping):
        _fail("LEASE_RESERVED_IDENTITY_INVALID", f"reserved_lease must be an object: {path}")
    _require_exact_keys(reserved, _RESERVED_LEASE_KEYS, code="LEASE_RESERVED_KEYS_INVALID")
    reserved_path = Path(str(reserved.get("path"))).resolve(strict=False)
    controller_pid = reserved.get("controller_pid")
    attempt_request = _read_json_object(
        _attempt_paths(root, attempt_id)["request"], reason_code="ATTEMPT_REQUEST_INVALID"
    )
    if (
        attempt_request.get("schema") != ATTEMPT_SCHEMA
        or attempt_request.get("attempt_id") != attempt_id
        or attempt_request.get("opportunity_id") != opportunity_id
    ):
        _fail(
            "LEASE_RESERVED_IDENTITY_INVALID",
            f"lease identity disagrees with its attempt request: {path}",
        )
    expected_workspace = _absolute_path(
        attempt_request.get("workspace"),
        code="LEASE_RESERVED_IDENTITY_INVALID",
        field="attempt workspace",
    )
    reserved_workspace = Path(str(reserved.get("workspace"))).resolve(strict=False)
    if (
        reserved.get("schema") != WORLD_TURN_QUOTA_LEASE_SCHEMA
        or reserved.get("lease_id") != lease_id
        or reserved.get("counted") is not True
        or reserved.get("status") != "RESERVED"
        or reserved.get("account_slot") != account
        or reserved.get("slot") != slot
        or reserved.get("limit") != 4
        or reserved.get("run_id") != attempt_id
        or reserved.get("lineage_id") != opportunity_id
        or reserved_workspace != expected_workspace
        or reserved_path != expected_path
        or type(controller_pid) is not int
        or int(controller_pid) <= 0
        or reserved.get("child_pid") is not None
        or reserved.get("bound_at") is not None
        or reserved.get("released_at") is not None
        or reserved.get("experiment_candidate_only") is not True
    ):
        _fail(
            "LEASE_RESERVED_IDENTITY_INVALID",
            f"reserved_lease does not prove the exact immutable reservation: {path}",
        )
    _parse_iso(str(reserved.get("reserved_at")))
    return value


def _lease_identity_value(
    root: Path,
    *,
    attempt_id: str,
    opportunity_id: str,
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the immutable identity from a durably observed RESERVED record."""

    account = str(lease.get("account_slot"))
    slot = lease.get("slot")
    if account not in {"A", "C"} or type(slot) is not int or not 1 <= slot <= 4:
        _fail("LEASE_RESERVED_IDENTITY_INVALID", "claimed lease account/slot is invalid")
    lease_path = Path(
        str(
            lease.get(
                "path",
                DEFAULT_QUOTA_ROOT.resolve(strict=False) / account / f"world-turn-{slot:02d}.json",
            )
        )
    ).resolve(strict=False)
    reserved = {**dict(lease), "path": str(lease_path)}
    return {
        "schema": "xinao.research-of-research.ongoing-lease-identity.v1",
        "attempt_id": attempt_id,
        "opportunity_id": opportunity_id,
        "job_identity": _job_identity(attempt_id),
        "account_slot": account,
        "slot": slot,
        "limit": 4,
        "lease_id": reserved.get("lease_id"),
        "lease_path": str(lease_path),
        "reserved_lease": reserved,
        # The quota record is the first durable claim fact.  Reusing its
        # timestamp makes recovery after the claim->identity crash window
        # byte-stable instead of inventing a second observation time.
        "created_at": str(reserved.get("reserved_at")),
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }


def _scan_exact_attempt_lease(
    root: Path, attempt_id: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Discover a claim committed before ``lease_identity.json`` existed.

    The attempt request and CLAIMING projection are the durable pre-claim
    intent.  Every A/C slot is read while holding its normal admission lock;
    malformed, unreadable, or duplicate state is UNKNOWN and authorizes no
    mutation.  Only one exact run/lineage/workspace identity can be adopted.
    """

    request = _read_json_object(
        _attempt_paths(root, attempt_id)["request"], reason_code="ATTEMPT_REQUEST_INVALID"
    )
    opportunity_id = _require_content_id(
        request.get("opportunity_id"),
        code="ATTEMPT_REQUEST_INVALID",
        field="attempt opportunity id",
    )
    workspace = _absolute_path(
        request.get("workspace"),
        code="ATTEMPT_REQUEST_INVALID",
        field="attempt workspace",
    )
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    persisted_keys = _RESERVED_LEASE_KEYS - {"path"}
    for account in ("A", "C"):
        quota = AccountQuota(
            account_slot=account,
            quota_root=DEFAULT_QUOTA_ROOT,
            limit=4,
            run_id=attempt_id,
            reclaim_bound_leases=False,
        )
        # A cap keeper uses this same admission mutex.  A single failed probe
        # cannot distinguish a busy guard from an absent claim, and returning
        # a false absence would let the normal launch path reserve a second
        # counted slot for this attempt.  Inspect every account under its
        # normal guard, with a bounded wait per account; timeout preserves the
        # durable CLAIMING_COMPUTE intent for a later recovery tick.
        deadline = time.monotonic() + _CAPACITY_ADMISSION_LOCK_TIMEOUT_SECONDS
        while True:
            guard = _try_acquire_byte_lock(quota.guard_path)
            if guard is not None:
                break
            if time.monotonic() >= deadline:
                _fail(
                    "QUOTA_SCAN_LOCK_TIMEOUT",
                    f"quota scan lock timeout for account {account}",
                )
            time.sleep(_CAPACITY_ADMISSION_RETRY_DELAY_SECONDS)
        try:
            for slot, path in enumerate(quota.records, 1):
                if not path.is_file():
                    continue
                record = _read_json_object(path, reason_code="QUOTA_SCAN_RECORD_INVALID")
                if (
                    record.get("schema") != WORLD_TURN_QUOTA_LEASE_SCHEMA
                    or record.get("account_slot") != account
                    or record.get("slot") != slot
                    or record.get("status") not in {"RESERVED", "BOUND", "RELEASED"}
                ):
                    _fail("QUOTA_SCAN_RECORD_INVALID", f"quota record identity drift: {path}")
                if record.get("run_id") != attempt_id:
                    continue
                _require_exact_keys(
                    record, persisted_keys, code="QUOTA_SCAN_OWNED_RECORD_KEYS_INVALID"
                )
                observed_workspace = Path(str(record.get("workspace"))).resolve(strict=False)
                if (
                    record.get("lineage_id") != opportunity_id
                    or observed_workspace != workspace
                    or record.get("counted") is not True
                    or record.get("limit") != 4
                    or record.get("experiment_candidate_only") is not True
                ):
                    _fail(
                        "QUOTA_SCAN_OWNERSHIP_DRIFT",
                        f"quota record shares attempt id but not exact intent: {path}",
                    )
                lease = {**record, "path": str(path.resolve(strict=False))}
                identity = _lease_identity_value(
                    root,
                    attempt_id=attempt_id,
                    opportunity_id=opportunity_id,
                    lease=lease,
                )
                matches.append((identity, lease))
        finally:
            _release_byte_lock(guard)
    if len(matches) > 1:
        _fail("QUOTA_SCAN_DUPLICATE_OWNERSHIP", "multiple slots claim the exact attempt identity")
    return matches[0] if matches else None


def _owned_lease_record(root: Path, attempt_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = _lease_identity(root, attempt_id)
    path = Path(str(identity["lease_path"]))
    record = _read_json_object(path, reason_code="LEASE_RECORD_INVALID")
    if (
        record.get("schema") != WORLD_TURN_QUOTA_LEASE_SCHEMA
        or record.get("lease_id") != identity["lease_id"]
        or record.get("run_id") != attempt_id
        or record.get("lineage_id") != identity["opportunity_id"]
        or record.get("account_slot") != identity["account_slot"]
        or record.get("slot") != identity["slot"]
        or record.get("limit") != 4
        or record.get("counted") is not True
    ):
        _fail("LEASE_OWNERSHIP_DRIFT", f"quota lease no longer proves exact ownership: {path}")
    return identity, {**record, "path": str(path)}


def _quota_from_identity(identity: Mapping[str, Any]) -> AccountQuota:
    return AccountQuota(
        account_slot=str(identity["account_slot"]),
        quota_root=DEFAULT_QUOTA_ROOT,
        limit=4,
        run_id=str(identity["attempt_id"]),
        reclaim_bound_leases=False,
    )


def _artifact_ref(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    _require_regular_unlinked(path, code="CONTROL_ARTIFACT_INVALID", field="control artifact")
    before = path.stat()
    digest = sha256_file(path).casefold()
    after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        _fail("CONTROL_ARTIFACT_DRIFT", f"control artifact changed while hashing: {path}")
    return {"path": str(path), "size": after.st_size, "sha256": digest}


def _verify_artifact_ref(value: object, *, expected_path: Path | None, code: str) -> bytes:
    if not isinstance(value, Mapping):
        _fail(code, "artifact reference must be an object")
    _require_exact_keys(value, {"path", "size", "sha256"}, code=code)
    path = _absolute_path(value.get("path"), code=code, field="artifact path", must_exist=True)
    if expected_path is not None and path != expected_path.resolve(strict=True):
        _fail(code, f"artifact path is not the exact prepared path: {path}")
    if type(value.get("size")) is not int or int(value["size"]) < 0:
        _fail(code, "artifact size is invalid")
    digest = str(value.get("sha256", "")).casefold()
    if not _HEX_SHA256.fullmatch(digest):
        _fail(code, "artifact SHA256 is invalid")
    raw = _stable_read(path, expected_sha256=digest)
    if len(raw) != int(value["size"]):
        _fail(code, f"artifact size drifted: {path}")
    return raw


def _runner_release_identity() -> dict[str, Any]:
    app_root = Path(__file__).resolve().parents[2]
    files = {
        relative: _artifact_ref(app_root / Path(relative)) for relative in _RUNNER_RELEASE_FILES
    }
    interpreter = _artifact_ref(Path(sys.executable))
    unsigned = {
        "app_root": str(app_root),
        "interpreter": interpreter,
        "files": files,
    }
    return {**unsigned, "release_id": _stable_id(unsigned)}


def _validate_runner_release(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("RUNNER_RELEASE_INVALID", "runner release must be an object")
    _require_exact_keys(
        value, {"app_root", "interpreter", "files", "release_id"}, code="RUNNER_RELEASE_INVALID"
    )
    app_root = _absolute_path(
        value.get("app_root"),
        code="RUNNER_RELEASE_INVALID",
        field="runner app_root",
        must_exist=True,
    )
    files = value.get("files")
    if not isinstance(files, Mapping) or set(files) != set(_RUNNER_RELEASE_FILES):
        _fail("RUNNER_RELEASE_INVALID", "runner release file set is not exact")
    for relative in _RUNNER_RELEASE_FILES:
        _verify_artifact_ref(
            files[relative],
            expected_path=app_root / Path(relative),
            code="RUNNER_RELEASE_FILE_DRIFT",
        )
    interpreter = _verify_artifact_ref(
        value.get("interpreter"),
        expected_path=Path(sys.executable),
        code="RUNNER_INTERPRETER_DRIFT",
    )
    del interpreter
    unsigned = {key: value[key] for key in ("app_root", "interpreter", "files")}
    if value.get("release_id") != _stable_id(unsigned):
        _fail("RUNNER_RELEASE_ID_INVALID", "runner release identity mismatch")
    return dict(value)


def _git_workspace_output(workspace: Path, arguments: Sequence[str]) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
        }
    )
    result = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=env,
        check=False,
    )
    if result.returncode != 0:
        _fail(
            "WORKSPACE_GIT_PROBE_FAILED",
            f"git {' '.join(arguments)} failed: {result.stderr.strip()}",
        )
    return result.stdout


def _git_workspace_bytes(workspace: Path, arguments: Sequence[str]) -> bytes:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
        }
    )
    result = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        capture_output=True,
        shell=False,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=env,
        check=False,
    )
    if result.returncode != 0:
        _fail("WORKSPACE_GIT_PROBE_FAILED", f"git {' '.join(arguments)} failed")
    return result.stdout


def _validate_prepared_clone(
    workspace: Path, environment: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    expected_source = environment.get("source_identity")
    expected_clone = environment.get("clone_identity")
    if not isinstance(expected_source, Mapping) or not isinstance(expected_clone, Mapping):
        _fail("WORKSPACE_CLONE_IDENTITY_INVALID", "prepared clone identities are missing")
    top = Path(_git_workspace_output(workspace, ["rev-parse", "--show-toplevel"]).strip()).resolve(
        strict=True
    )
    head = _git_workspace_output(workspace, ["rev-parse", "HEAD"]).strip().casefold()
    remotes = [line for line in _git_workspace_output(workspace, ["remote"]).splitlines() if line]
    if (
        top != workspace.resolve(strict=True)
        or head != str(expected_source.get("head", "")).casefold()
        or head != str(expected_clone.get("head", "")).casefold()
        or remotes
    ):
        _fail("WORKSPACE_CLONE_IDENTITY_DRIFT", "prepared clone HEAD/root/remotes drifted")
    _verify_artifact_ref(
        environment.get("workspace_git_config"),
        expected_path=workspace / ".git" / "config",
        code="WORKSPACE_GIT_CONFIG_DRIFT",
    )
    tracked_status = ""
    for scan_ordinal in range(2):
        tracked_status = _git_workspace_output(
            workspace, ["status", "--porcelain=v1", "--untracked-files=no"]
        )
        if not tracked_status.strip():
            break
        if scan_ordinal == 0:
            time.sleep(_WORKSPACE_INVENTORY_RETRY_DELAY_SECONDS)
    else:
        _fail(
            "WORKSPACE_CLONE_TRACKED_STATUS_DRIFT",
            f"prepared clone has tracked/staged changes: {tracked_status!r}",
        )
    # Include ignored files as well.  An injected ignored file is still part of
    # the model-visible workspace and therefore cannot be outside the exact set.
    bundle_prefix = BUNDLE_RELATIVE_ROOT.as_posix()
    expected_untracked = {
        f"{bundle_prefix}/{entry['export_path']}"
        for entry in manifest["entries"]
        if entry.get("state") == "PRESENT"
    }
    expected_untracked.add(f"{bundle_prefix}/MANIFEST.json")
    untracked_paths: set[str] = set()
    for scan_ordinal in range(2):
        untracked_raw = _git_workspace_bytes(workspace, ["ls-files", "--others", "-z"])
        try:
            untracked_paths = {
                raw.decode("utf-8").replace("\\", "/") for raw in untracked_raw.split(b"\0") if raw
            }
        except UnicodeError as exc:
            raise OngoingError(
                "WORKSPACE_GIT_PATH_ENCODING_INVALID", "git path is not UTF-8"
            ) from exc
        if untracked_paths == expected_untracked:
            break
        if scan_ordinal == 0:
            time.sleep(_WORKSPACE_INVENTORY_RETRY_DELAY_SECONDS)
    else:
        _fail(
            "WORKSPACE_CLONE_UNTRACKED_SET_DRIFT",
            "prepared clone tracked/untracked set drifted: "
            f"actual_only={sorted(untracked_paths - expected_untracked)!r} "
            f"expected_only={sorted(expected_untracked - untracked_paths)!r}",
        )


def _trajectory_summary(stdout_path: Path) -> dict[str, Any]:
    thread_ids: list[str] = []
    terminals: list[str] = []
    event_count = 0
    malformed_count = 0
    last_event_type: str | None = None
    ends_with_newline = False
    if stdout_path.is_file():
        raw_stream = stdout_path.read_bytes()
        ends_with_newline = not raw_stream or raw_stream.endswith(b"\n")
        for raw_line in raw_stream.splitlines():
            if not raw_line.strip():
                continue
            event_count += 1
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                malformed_count += 1
                continue
            if not isinstance(event, dict):
                malformed_count += 1
                continue
            event_type = event.get("type")
            if not isinstance(event_type, str) or not event_type:
                malformed_count += 1
                continue
            last_event_type = event_type
            if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
                thread_ids.append(str(event["thread_id"]))
            if event_type in {"turn.completed", "turn.failed", "turn.cancelled"}:
                terminals.append(str(event_type))
    complete_success = (
        event_count > 0
        and malformed_count == 0
        and ends_with_newline
        and len(thread_ids) == 1
        and len(terminals) == 1
        and terminals[0] == "turn.completed"
        and last_event_type == "turn.completed"
    )
    return {
        "event_count": event_count,
        "thread_ids": thread_ids,
        "session_id": thread_ids[-1] if thread_ids else None,
        "terminal_events": terminals,
        "malformed_event_count": malformed_count,
        "ends_with_newline": ends_with_newline,
        "last_event_type": last_event_type,
        "complete_success": complete_success,
    }


def _build_runner_request(
    root: Path,
    *,
    revision: Mapping[str, Any],
    inventory: Mapping[str, Any],
    opportunity: Mapping[str, Any],
    attempt: Mapping[str, Any],
    trigger_fact: Mapping[str, Any],
    environment: Mapping[str, Any],
    prior_candidate: Mapping[str, Any] | None,
    paths: Mapping[str, Path],
) -> dict[str, Any]:
    revision_id = str(revision["revision_id"])
    artifact_refs = {
        "attempt_request": _artifact_ref(paths["request"]),
        "opportunity_request": _artifact_ref(
            _opportunity_paths(root, str(opportunity["opportunity_id"]))[0]
        ),
        "source_fact": _artifact_ref(_fact_path(root, str(trigger_fact["fact_id"]))),
        "contract_revision": _artifact_ref(
            root / "contracts" / "revisions" / f"{revision_id}.json"
        ),
        "environment": _artifact_ref(paths["environment"]),
        "bundle_manifest": _artifact_ref(Path(str(environment["bundle"]["manifest_path"]))),
        "prompt": _artifact_ref(paths["prompt"]),
        "output_schema": _artifact_ref(paths["output_schema"]),
        "arguments": _artifact_ref(paths["arguments"]),
        "command": _artifact_ref(paths["command"]),
        "launcher": _artifact_ref(paths["launcher"]),
        "lease_identity": _artifact_ref(paths["lease_identity"]),
    }
    prior_ref = None
    prior_candidate_id = None
    if prior_candidate is not None:
        prior_candidate_id = str(prior_candidate["candidate_id"])
        prior_ref = _artifact_ref(root / "candidates" / f"{prior_candidate_id}.json")
    unsigned = {
        "schema": RUNNER_REQUEST_SCHEMA,
        "attempt_id": attempt["attempt_id"],
        "job_identity_id": _validate_job_identity(
            _lease_identity(root, str(attempt["attempt_id"])).get("job_identity"),
            attempt_id=str(attempt["attempt_id"]),
        )["job_identity_id"],
        "opportunity_id": opportunity["opportunity_id"],
        "contract_revision_id": revision_id,
        "source_fact_id": trigger_fact["fact_id"],
        "inventory_id": inventory["inventory_id"],
        "prior_candidate_id": prior_candidate_id,
        "prior_candidate_ref": prior_ref,
        "workspace": str(environment["workspace"]),
        "timeout_seconds": int(_contract_carrier_value(revision["contract"], "timeout_seconds")),
        "artifact_refs": artifact_refs,
        "runner_release": _runner_release_identity(),
        "created_at": _now_iso(),
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }
    return {**unsigned, "runner_request_id": _stable_id(unsigned)}


def _runner_request(
    root: Path, attempt_id: str, *, expected_sha256: str | None = None
) -> dict[str, Any]:
    path = _attempt_paths(root, attempt_id)["runner_request"]
    raw = _stable_read(path, expected_sha256=expected_sha256)
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OngoingError("RUNNER_REQUEST_INVALID", f"runner request invalid: {path}") from exc
    if not isinstance(value, dict):
        _fail("RUNNER_REQUEST_INVALID", f"runner request is not an object: {path}")
    expected_keys = {
        "schema",
        "runner_request_id",
        "attempt_id",
        "job_identity_id",
        "opportunity_id",
        "contract_revision_id",
        "source_fact_id",
        "inventory_id",
        "prior_candidate_id",
        "prior_candidate_ref",
        "workspace",
        "timeout_seconds",
        "artifact_refs",
        "runner_release",
        "created_at",
        "protocol_stage",
        *_BOUNDARIES,
    }
    _require_exact_keys(value, expected_keys, code="RUNNER_REQUEST_KEYS_INVALID")
    unsigned = dict(value)
    request_id = unsigned.pop("runner_request_id", None)
    refs = value.get("artifact_refs")
    expected_ref_keys = {
        "attempt_request",
        "opportunity_request",
        "source_fact",
        "contract_revision",
        "environment",
        "bundle_manifest",
        "prompt",
        "output_schema",
        "arguments",
        "command",
        "launcher",
        "lease_identity",
    }
    if (
        value.get("schema") != RUNNER_REQUEST_SCHEMA
        or value.get("attempt_id") != attempt_id
        or request_id != _stable_id(unsigned)
        or value.get("protocol_stage") != PROTOCOL_STAGE
        or not isinstance(refs, Mapping)
        or set(refs) != expected_ref_keys
        or type(value.get("timeout_seconds")) is not int
        or int(value["timeout_seconds"]) <= 0
        or any(value.get(key) is not expected for key, expected in _BOUNDARIES.items())
    ):
        _fail("RUNNER_REQUEST_INVALID", f"runner request invalid: {path}")
    identity = _lease_identity(root, attempt_id)
    job_identity = _validate_job_identity(identity.get("job_identity"), attempt_id=attempt_id)
    if value.get("job_identity_id") != job_identity["job_identity_id"]:
        _fail("RUNNER_REQUEST_INVALID", "runner request binds a different Job owner")
    _validate_runner_release(value.get("runner_release"))
    return value


def _json_from_bound_bytes(raw: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OngoingError(code, "bound control JSON is invalid") from exc
    if not isinstance(value, dict):
        _fail(code, "bound control JSON must be an object")
    return value


def _validate_attempt_request(
    attempt: Mapping[str, Any], *, root: Path, opportunity: Mapping[str, Any]
) -> None:
    attempt_id = _require_content_id(
        attempt.get("attempt_id"), code="ATTEMPT_REQUEST_INVALID", field="attempt id"
    )
    expected_keys = {
        "schema",
        "attempt_id",
        "opportunity_id",
        "contract_revision_id",
        "source_fact_id",
        "external_epoch_id",
        "ordinal",
        "workspace",
        "attempt_directory",
        "trajectory_path",
        "stderr_path",
        "last_message_path",
        "created_at",
        "fresh_session_only",
        "resume_session_id",
        "root_main_used",
        "root_main_state",
        "protocol_stage",
        *_BOUNDARIES,
    }
    _require_exact_keys(attempt, expected_keys, code="ATTEMPT_REQUEST_KEYS_INVALID")
    ordinal = attempt.get("ordinal")
    paths = _attempt_paths(root, attempt_id)
    workspace = (Path(str(opportunity["workspace_root"])) / f"ror-{attempt_id}").resolve(
        strict=False
    )
    if (
        attempt.get("schema") != ATTEMPT_SCHEMA
        or type(ordinal) is not int
        or int(ordinal) < 1
        or _stable_id({"opportunity_id": opportunity["opportunity_id"], "ordinal": ordinal})
        != attempt_id
        or attempt.get("opportunity_id") != opportunity.get("opportunity_id")
        or attempt.get("contract_revision_id") != opportunity.get("contract_revision_id")
        or attempt.get("source_fact_id") != opportunity.get("source_fact_id")
        or attempt.get("external_epoch_id") != opportunity.get("external_epoch_id")
        or Path(str(attempt.get("workspace"))).resolve(strict=False) != workspace
        or Path(str(attempt.get("attempt_directory"))).resolve(strict=False)
        != paths["directory"].resolve(strict=False)
        or Path(str(attempt.get("trajectory_path"))).resolve(strict=False)
        != paths["stdout"].resolve(strict=False)
        or Path(str(attempt.get("stderr_path"))).resolve(strict=False)
        != paths["stderr"].resolve(strict=False)
        or Path(str(attempt.get("last_message_path"))).resolve(strict=False)
        != paths["last_message"].resolve(strict=False)
        or attempt.get("fresh_session_only") is not True
        or attempt.get("resume_session_id") is not None
        or attempt.get("root_main_used") is not False
        or attempt.get("root_main_state") != "NO_ROOT_MAIN_PATH_TOUCHED"
        or attempt.get("protocol_stage") != PROTOCOL_STAGE
        or any(attempt.get(key) is not expected for key, expected in _BOUNDARIES.items())
    ):
        _fail("ATTEMPT_REQUEST_INVALID", "attempt request identity or path binding invalid")


def _validate_reentry_evidence_bundle(
    manifest: Mapping[str, Any],
    *,
    workspace: Path,
    request: Mapping[str, Any],
    inventory: Mapping[str, Any],
    trigger_fact: Mapping[str, Any],
    root: Path,
    revision_id: str,
) -> None:
    unsigned = dict(manifest)
    manifest_id = unsigned.pop("manifest_id", None)
    reentry_contract = manifest.get("bound_reentry_contract")
    bound_contract = (
        reentry_contract.get("contract") if isinstance(reentry_contract, Mapping) else None
    )
    if not isinstance(bound_contract, Mapping):
        _fail("EXACT_BUNDLE_MANIFEST_INVALID", "bundle has no bound re-entry contract")
    revision = _load_revision(root, revision_id)
    expected_reentry_contract = {
        "contract_revision_id": revision_id,
        "contract_source_path": revision["contract_source_path"],
        "contract_source_sha256": revision["contract_source_sha256"],
        "contract": revision["contract"],
    }
    if reentry_contract != expected_reentry_contract:
        _fail(
            "EXACT_BUNDLE_PARENT_CONTRACT_INVALID",
            "bundle re-entry contract does not equal its immutable revision",
        )
    expected_wake_inventory_id = _inventory_wake_id(bound_contract, inventory)
    if (
        manifest.get("schema") != BUNDLE_MANIFEST_SCHEMA
        or manifest_id != _stable_id(unsigned)
        or manifest.get("inventory_id") != request.get("inventory_id")
        or manifest.get("wake_inventory_id") != expected_wake_inventory_id
        or manifest.get("trigger_fact_id") != request.get("source_fact_id")
        or manifest.get("evidence_scope") != "CONTRACT_SELECTED_REENTRY_EVIDENCE"
        or manifest.get("coverage_claim") != "PARTIAL"
        or manifest.get("snapshot_atomicity") != "PER_FILE_STABLE_NO_GLOBAL_ATOMICITY"
        or manifest.get("instruction_authority") is not False
        or manifest.get("cognition_authority") is not False
        or manifest.get("source_repository_is_cognition_body") is not True
        or manifest.get("evidence_frame_replaces_repository_world") is not False
        or manifest.get("candidate_only") is not True
        or manifest.get("root_main_used") is not False
        or any(manifest.get(key) is not expected for key, expected in _BOUNDARIES.items())
    ):
        _fail("EXACT_BUNDLE_MANIFEST_INVALID", "frozen evidence manifest is invalid")
    bundle_root = workspace / BUNDLE_RELATIVE_ROOT
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        _fail("EXACT_BUNDLE_MANIFEST_INVALID", "bundle entries must be a list")
    export_paths: set[str] = set()
    inventory_entries: list[dict[str, Any]] = []
    trigger_exports: set[str] = set()
    history_exports: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            _fail("EXACT_BUNDLE_MANIFEST_INVALID", "bundle entry must be an object")
        export_path = str(entry.get("export_path", ""))
        folded = export_path.casefold()
        destination = (bundle_root / export_path).resolve(strict=False)
        if not export_path or folded in export_paths or not _is_within(destination, bundle_root):
            _fail("EXACT_BUNDLE_MANIFEST_INVALID", "bundle export path invalid")
        export_paths.add(folded)
        normalized = {
            "group": entry.get("group"),
            "source_path": entry.get("source_path"),
            "export_path": export_path,
            "state": entry.get("state"),
            "size": entry.get("size"),
            "sha256": entry.get("sha256"),
        }
        if export_path.startswith("TRIGGER/"):
            trigger_exports.add(export_path)
        elif export_path.startswith("HISTORY/"):
            history_exports.add(export_path)
        else:
            inventory_entries.append(normalized)
        if entry.get("state") == "PRESENT":
            raw = _stable_read(destination, expected_sha256=str(entry.get("sha256", "")))
            if type(entry.get("size")) is not int or len(raw) != int(entry["size"]):
                _fail("EXACT_BUNDLE_ENTRY_DRIFT", f"bundle entry size drifted: {destination}")
        elif entry.get("state") != "MISSING":
            _fail("EXACT_BUNDLE_MANIFEST_INVALID", "bundle entry state invalid")
    expected_inventory = sorted(
        (dict(entry) for entry in inventory["entries"]),
        key=lambda row: (str(row["source_path"]).casefold(), str(row["group"]).casefold()),
    )
    observed_inventory = sorted(
        inventory_entries,
        key=lambda row: (str(row["source_path"]).casefold(), str(row["group"]).casefold()),
    )
    if observed_inventory != expected_inventory or _stable_id(expected_inventory) != request.get(
        "inventory_id"
    ):
        _fail("EXACT_BUNDLE_INVENTORY_OMISSION", "bundle entries do not equal recomputed inventory")
    expected_trigger_exports = {"TRIGGER/ongoing_fact.json"}
    if trigger_fact.get("fact_type") == "CONTINUATION_OBSERVATION":
        expected_trigger_exports.update(
            {"TRIGGER/continuation_observation.json", "TRIGGER/run_receipt.json"}
        )
    if trigger_exports != expected_trigger_exports:
        _fail("EXACT_BUNDLE_TRIGGER_OMISSION", "bundle trigger evidence set is incomplete")
    expected_history_exports = {"HISTORY/CANDIDATE_INDEX.json"}
    expected_history_exports.update(
        f"HISTORY/candidates/{candidate['candidate_id']}.json"
        for candidate in _candidate_history(root, revision_id)
    )
    if history_exports != expected_history_exports:
        _fail("EXACT_BUNDLE_HISTORY_OMISSION", "bundle candidate chronology is incomplete")
    _validate_candidate_history_bundle(bundle_root, root, revision_id)


def _validate_runner_preflight(
    runtime_root: Path,
    root: Path,
    attempt_id: str,
    *,
    expected_request_sha256: str | None = None,
    verify_live_lease: bool = True,
) -> dict[str, Any]:
    request = _runner_request(root, attempt_id, expected_sha256=expected_request_sha256)
    current, revision = _load_current(root)
    if (
        _contract_is_stopped(root, current)
        or current.get("status") != "LIVE"
        or current.get("revision_id") != request.get("contract_revision_id")
    ):
        _fail("CONTRACT_STOPPED_BEFORE_LAUNCH", "runner no longer has the exact LIVE contract")
    drift = _revalidate_contract_sources(revision)
    if drift:
        _fail("CONTRACT_REBIND_REQUIRED", "contract source drifted before model launch")
    inventory = _inventory_sources(revision["contract"])
    if inventory.get("inventory_id") != request.get("inventory_id"):
        _fail(
            "INVENTORY_DRIFT_BEFORE_LAUNCH",
            "contract-selected evidence inventory changed before model launch",
        )

    paths = _attempt_paths(root, attempt_id)
    active_status = _read_attempt_status(paths["status"])
    if active_status.get("attempt_id") != attempt_id or active_status.get("status") not in {
        "LAUNCHING",
        "RUNNER_STARTING",
    }:
        _fail(
            "RUNNER_ATTEMPT_NOT_ACTIVE",
            "runner may create a process only for the still-active exact attempt",
        )
    refs = request["artifact_refs"]
    opportunity_id = str(request["opportunity_id"])
    opportunity_path = _opportunity_paths(root, opportunity_id)[0]
    fact_path = _fact_path(root, str(request["source_fact_id"]))
    revision_path = root / "contracts" / "revisions" / f"{revision['revision_id']}.json"
    expected_paths = {
        "attempt_request": paths["request"],
        "opportunity_request": opportunity_path,
        "source_fact": fact_path,
        "contract_revision": revision_path,
        "environment": paths["environment"],
        "prompt": paths["prompt"],
        "output_schema": paths["output_schema"],
        "arguments": paths["arguments"],
        "command": paths["command"],
        "launcher": paths["launcher"],
        "lease_identity": paths["lease_identity"],
    }
    bound: dict[str, bytes] = {
        name: _verify_artifact_ref(refs[name], expected_path=path, code="RUNNER_ARTIFACT_DRIFT")
        for name, path in expected_paths.items()
    }
    attempt = _json_from_bound_bytes(bound["attempt_request"], code="ATTEMPT_REQUEST_INVALID")
    opportunity = _read_opportunity_request(opportunity_path)
    _validate_attempt_request(attempt, root=root, opportunity=opportunity)
    fact = _read_source_fact(root, str(request["source_fact_id"]))
    if (
        fact.get("fact_type") == "CONTINUATION_OBSERVATION"
        and _observation_fact_eligibility(revision["contract"], fact).get("eligible") is not True
    ):
        _fail(
            "RUNNER_TRIGGER_INELIGIBLE",
            "contract predicate does not authorize cognition for this durable observation",
        )
    if (
        request.get("opportunity_id") != opportunity.get("opportunity_id")
        or request.get("contract_revision_id") != opportunity.get("contract_revision_id")
        or request.get("source_fact_id") != opportunity.get("source_fact_id")
        or fact.get("contract_revision_id") != revision.get("revision_id")
        or Path(str(opportunity.get("workspace_root"))).resolve(strict=False)
        != Path(str(_contract_clean_room(revision["contract"])["workspace_root"])).resolve(
            strict=False
        )
    ):
        _fail("RUNNER_SOURCE_BINDING_INVALID", "runner source identities are inconsistent")

    environment = _json_from_bound_bytes(bound["environment"], code="ATTEMPT_ENVIRONMENT_INVALID")
    workspace = Path(str(environment.get("workspace"))).resolve(strict=False)
    if workspace != Path(str(attempt["workspace"])).resolve(strict=False):
        _fail("RUNNER_WORKSPACE_MISMATCH", "runner workspace differs from exact attempt")
    manifest_path = Path(str(environment.get("bundle", {}).get("manifest_path")))
    manifest_raw = _verify_artifact_ref(
        refs["bundle_manifest"],
        expected_path=manifest_path,
        code="EXACT_BUNDLE_MANIFEST_DRIFT",
    )
    manifest = _json_from_bound_bytes(manifest_raw, code="EXACT_BUNDLE_MANIFEST_INVALID")
    _validate_reentry_evidence_bundle(
        manifest,
        workspace=workspace,
        request=request,
        inventory=inventory,
        trigger_fact=fact,
        root=root,
        revision_id=str(revision["revision_id"]),
    )
    observed_source_identity = validate_source_repo(
        Path(str(_contract_clean_room(revision["contract"])["source_repo"]))
    )
    if observed_source_identity != environment.get("source_identity"):
        _fail("SOURCE_REPO_DRIFT_BEFORE_LAUNCH", "clean-room source repo changed after freeze")
    launcher_identity = environment.get("launcher_identity")
    if not isinstance(launcher_identity, Mapping):
        _fail("ATTEMPT_LAUNCHER_IDENTITY_INVALID", "launcher identity is missing")
    _stable_read(
        Path(str(_contract_clean_room(revision["contract"])["launcher_path"])),
        expected_sha256=str(launcher_identity.get("source_sha256", "")),
    )
    _validate_prepared_clone(workspace, environment, manifest)

    prior_candidate = None
    prior_id = request.get("prior_candidate_id")
    if prior_id is None:
        if request.get("prior_candidate_ref") is not None:
            _fail("RUNNER_PRIOR_CANDIDATE_INVALID", "prior candidate ref exists without identity")
    else:
        prior_id = _require_content_id(
            prior_id, code="RUNNER_PRIOR_CANDIDATE_INVALID", field="prior candidate id"
        )
        prior_raw = _verify_artifact_ref(
            request.get("prior_candidate_ref"),
            expected_path=root / "candidates" / f"{prior_id}.json",
            code="RUNNER_PRIOR_CANDIDATE_DRIFT",
        )
        prior_candidate = _json_from_bound_bytes(prior_raw, code="RUNNER_PRIOR_CANDIDATE_INVALID")
        if prior_candidate.get("candidate_id") != prior_id:
            _fail("RUNNER_PRIOR_CANDIDATE_INVALID", "prior candidate identity mismatch")

    schema_value = json.loads(bound["output_schema"].decode("utf-8-sig"))
    if schema_value != _output_schema():
        _fail("RUNNER_OUTPUT_SCHEMA_DRIFT", "output schema differs from current exact builder")
    arguments = json.loads(bound["arguments"].decode("utf-8-sig"))
    identity = _lease_identity(root, attempt_id)
    if verify_live_lease:
        live_identity, live_lease = _owned_lease_record(root, attempt_id)
        _validate_job_identity(live_identity.get("job_identity"), attempt_id=attempt_id)
        if live_lease.get("status") != "RESERVED":
            _fail(
                "RUNNER_LEASE_NOT_RESERVED",
                "production Job process may start only while exact quota remains RESERVED",
            )
    config = {
        "model": _contract_carrier_value(revision["contract"], "model"),
        "model_reasoning_effort": _contract_carrier_value(
            revision["contract"], "model_reasoning_effort"
        ),
        "powershell_path": _contract_clean_room(revision["contract"])["powershell_path"],
        "launcher_path": str(paths["launcher"]),
        "account_slot": str(identity["account_slot"]),
    }
    expected_arguments = build_codex_arguments(
        config, last_message_path=paths["last_message"], session_id=None
    )
    expected_arguments[-1:-1] = ["--output-schema", str(paths["output_schema"])]
    if arguments != expected_arguments:
        _fail("RUNNER_ARGUMENTS_DRIFT", "Codex arguments differ from exact fresh-session builder")
    expected_command = build_codex_command(
        config, workspace=workspace, arguments_path=paths["arguments"]
    )
    command_record = _json_from_bound_bytes(bound["command"], code="RUNNER_COMMAND_INVALID")
    command_unsigned = {
        "schema": "xinao.research-of-research.ongoing-command.v1",
        "argv": expected_command,
        "codex_argv": expected_arguments,
        "fresh_session_only": True,
        "resume_session_id": None,
        "root_main_used": False,
        "root_main_state": "NO_ROOT_MAIN_PATH_TOUCHED",
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }
    if command_record != command_unsigned:
        _fail("RUNNER_COMMAND_DRIFT", "command record differs from exact low-level builder")
    expected_prompt = _build_prompt(
        revision["contract"], revision, opportunity, fact, environment["bundle"], prior_candidate
    ).encode("utf-8")
    if bound["prompt"] != expected_prompt:
        _fail("RUNNER_PROMPT_DRIFT", "prompt differs from exact trigger/current-reality builder")
    if str(request.get("workspace")) != str(environment["workspace"]):
        _fail("RUNNER_WORKSPACE_MISMATCH", "runner request workspace drifted")
    return {
        "request": request,
        "revision": revision,
        "inventory": inventory,
        "opportunity": opportunity,
        "fact": fact,
        "attempt": attempt,
        "environment": environment,
        "workspace": workspace,
        "command": expected_command,
        "prompt": expected_prompt,
        "lease_identity": identity,
    }


def _runner_launch_intent_value(
    *, attempt_id: str, request: Mapping[str, Any], request_sha256: str, launch_nonce: str
) -> dict[str, Any]:
    job_identity = _job_identity(attempt_id)
    if request.get("job_identity_id") != job_identity["job_identity_id"]:
        _fail("RUNNER_LAUNCH_INTENT_INVALID", "request binds a different Job owner")
    return {
        "schema": RUNNER_LAUNCH_INTENT_SCHEMA,
        "attempt_id": attempt_id,
        "runner_request_id": request["runner_request_id"],
        "runner_request_sha256": request_sha256,
        "runner_release_id": request["runner_release"]["release_id"],
        "launch_nonce": launch_nonce,
        "job_identity": job_identity,
        "requested_at": str(request["created_at"]),
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }


def _read_runner_launch_intent(root: Path, attempt_id: str) -> dict[str, Any]:
    path = _attempt_paths(root, attempt_id)["runner_launch_intent"]
    value = _read_json_object(path, reason_code="RUNNER_LAUNCH_INTENT_INVALID")
    _require_exact_keys(
        value,
        {
            "schema",
            "attempt_id",
            "runner_request_id",
            "runner_request_sha256",
            "runner_release_id",
            "launch_nonce",
            "job_identity",
            "requested_at",
            "protocol_stage",
            *_BOUNDARIES,
        },
        code="RUNNER_LAUNCH_INTENT_KEYS_INVALID",
    )
    if (
        value.get("schema") != RUNNER_LAUNCH_INTENT_SCHEMA
        or value.get("attempt_id") != attempt_id
        or not isinstance(value.get("launch_nonce"), str)
        or not _HEX_SHA256.fullmatch(str(value.get("runner_request_sha256", "")))
        or value.get("protocol_stage") != PROTOCOL_STAGE
        or any(value.get(key) is not expected for key, expected in _BOUNDARIES.items())
    ):
        _fail("RUNNER_LAUNCH_INTENT_INVALID", f"runner launch intent invalid: {path}")
    job_identity = _validate_job_identity(value.get("job_identity"), attempt_id=attempt_id)
    request = _runner_request(root, attempt_id, expected_sha256=str(value["runner_request_sha256"]))
    if (
        value.get("runner_request_id") != request.get("runner_request_id")
        or value.get("runner_release_id") != request["runner_release"]["release_id"]
        or request.get("job_identity_id") != job_identity["job_identity_id"]
    ):
        _fail("RUNNER_LAUNCH_INTENT_INVALID", "launch intent does not bind exact runner request")
    return value


def _runner_spawn_value(
    *,
    attempt_id: str,
    runner_pid: int,
    inline_test_runner: bool,
    intent: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": RUNNER_SPAWN_SCHEMA,
        "attempt_id": attempt_id,
        "runner_request_id": intent["runner_request_id"],
        "runner_request_sha256": intent["runner_request_sha256"],
        "launch_nonce": intent["launch_nonce"],
        "job_identity_id": intent["job_identity"]["job_identity_id"],
        "runner_pid": runner_pid,
        "inline_test_runner": inline_test_runner,
        "spawned_at": intent["requested_at"],
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }


def _read_runner_spawn(root: Path, attempt_id: str) -> dict[str, Any]:
    path = _attempt_paths(root, attempt_id)["runner_spawn"]
    value = _read_json_object(path, reason_code="RUNNER_SPAWN_INVALID")
    expected = {
        "schema",
        "attempt_id",
        "runner_request_id",
        "runner_request_sha256",
        "launch_nonce",
        "job_identity_id",
        "runner_pid",
        "inline_test_runner",
        "spawned_at",
        "protocol_stage",
        *_BOUNDARIES,
    }
    _require_exact_keys(value, expected, code="RUNNER_SPAWN_KEYS_INVALID")
    intent = _read_runner_launch_intent(root, attempt_id)
    expected_value = _runner_spawn_value(
        attempt_id=attempt_id,
        runner_pid=int(value.get("runner_pid", 0)),
        inline_test_runner=bool(value.get("inline_test_runner")),
        intent=intent,
    )
    if (
        type(value.get("runner_pid")) is not int
        or int(value["runner_pid"]) <= 0
        or value != expected_value
    ):
        _fail("RUNNER_SPAWN_INVALID", f"runner spawn receipt invalid: {path}")
    return value


def _read_runner_started(root: Path, attempt_id: str) -> dict[str, Any]:
    path = _attempt_paths(root, attempt_id)["runner_started"]
    value = _read_json_object(path, reason_code="RUNNER_STARTED_INVALID")
    expected = {
        "schema",
        "started_seal_sha256",
        "attempt_id",
        "runner_request_id",
        "runner_request_sha256",
        "launch_nonce",
        "job_identity_id",
        "job_name",
        "runner_pid",
        "child_pid",
        "started_at",
        "command_sha256",
        "protocol_stage",
        *_BOUNDARIES,
    }
    _require_exact_keys(value, expected, code="RUNNER_STARTED_KEYS_INVALID")
    unsigned = dict(value)
    seal = unsigned.pop("started_seal_sha256", None)
    spawn = _read_runner_spawn(root, attempt_id)
    intent = _read_runner_launch_intent(root, attempt_id)
    job_identity = _validate_job_identity(intent.get("job_identity"), attempt_id=attempt_id)
    if (
        value.get("schema") != RUNNER_STARTED_SCHEMA
        or value.get("attempt_id") != attempt_id
        or value.get("runner_request_id") != spawn.get("runner_request_id")
        or value.get("runner_request_sha256") != spawn.get("runner_request_sha256")
        or value.get("launch_nonce") != spawn.get("launch_nonce")
        or value.get("job_identity_id") != job_identity["job_identity_id"]
        or value.get("job_name") != job_identity["job_name"]
        or value.get("runner_pid") != spawn.get("runner_pid")
        or type(value.get("child_pid")) is not int
        or int(value["child_pid"]) <= 0
        or seal != _sha256(canonical_json_bytes(unsigned))
        or value.get("protocol_stage") != PROTOCOL_STAGE
        or any(value.get(key) is not expected for key, expected in _BOUNDARIES.items())
    ):
        _fail("RUNNER_STARTED_INVALID", f"runner started receipt invalid: {path}")
    _runner_request(root, attempt_id, expected_sha256=str(value["runner_request_sha256"]))
    command_record = _read_json_object(
        _attempt_paths(root, attempt_id)["command"], reason_code="RUNNER_COMMAND_INVALID"
    )
    if value.get("command_sha256") != _stable_id(command_record.get("argv")):
        _fail("RUNNER_STARTED_COMMAND_MISMATCH", "started receipt binds a different command")
    return value


def _write_runner_terminal(
    root: Path,
    attempt_id: str,
    *,
    runner_pid: int,
    child_pid: int | None,
    exit_code: int | None,
    timed_out: bool,
    started_at: str,
    ended_at: str,
    release_status: str,
    error_code: str | None,
    runner_request_id: str,
    runner_request_sha256: str,
    child_definitely_dead: bool,
    stop_requested: bool,
    job_terminal_state: str,
) -> dict[str, Any]:
    paths = _attempt_paths(root, attempt_id)
    summary = _trajectory_summary(paths["stdout"])
    unsigned = {
        "schema": RUNNER_TERMINAL_SCHEMA,
        "attempt_id": attempt_id,
        "runner_request_id": runner_request_id,
        "runner_request_sha256": runner_request_sha256,
        "job_identity_id": _job_identity(attempt_id)["job_identity_id"],
        "job_name": _job_identity(attempt_id)["job_name"],
        "job_terminal_state": job_terminal_state,
        "runner_pid": runner_pid,
        "child_pid": child_pid,
        "child_definitely_dead": child_definitely_dead,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stop_requested": stop_requested,
        "started_at": started_at,
        "ended_at": ended_at,
        "release_status": release_status,
        "error_code": error_code,
        "session_id": summary["session_id"],
        "terminal_events": summary["terminal_events"],
        "trajectory_event_count": summary["event_count"],
        "trajectory_malformed_event_count": summary["malformed_event_count"],
        "trajectory_ends_with_newline": summary["ends_with_newline"],
        "trajectory_last_event_type": summary["last_event_type"],
        "trajectory_complete_success": summary["complete_success"],
        "trajectory_sha256": sha256_file(paths["stdout"]).casefold()
        if paths["stdout"].is_file()
        else None,
        "stderr_sha256": sha256_file(paths["stderr"]).casefold()
        if paths["stderr"].is_file()
        else None,
        "last_message_sha256": (
            sha256_file(paths["last_message"]).casefold()
            if paths["last_message"].is_file()
            else None
        ),
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }
    value = {**unsigned, "terminal_seal_sha256": _sha256(canonical_json_bytes(unsigned))}
    _write_once_json(paths["runner_terminal"], value, conflict_code="RUNNER_TERMINAL_CONFLICT")
    return value


def _read_runner_terminal(root: Path, attempt_id: str) -> dict[str, Any]:
    path = _attempt_paths(root, attempt_id)["runner_terminal"]
    value = _read_json_object(path, reason_code="RUNNER_TERMINAL_INVALID")
    expected = {
        "schema",
        "terminal_seal_sha256",
        "attempt_id",
        "runner_request_id",
        "runner_request_sha256",
        "job_identity_id",
        "job_name",
        "job_terminal_state",
        "runner_pid",
        "child_pid",
        "child_definitely_dead",
        "exit_code",
        "timed_out",
        "stop_requested",
        "started_at",
        "ended_at",
        "release_status",
        "error_code",
        "session_id",
        "terminal_events",
        "trajectory_event_count",
        "trajectory_malformed_event_count",
        "trajectory_ends_with_newline",
        "trajectory_last_event_type",
        "trajectory_complete_success",
        "trajectory_sha256",
        "stderr_sha256",
        "last_message_sha256",
        "protocol_stage",
        *_BOUNDARIES,
    }
    _require_exact_keys(value, expected, code="RUNNER_TERMINAL_KEYS_INVALID")
    unsigned = dict(value)
    seal = unsigned.pop("terminal_seal_sha256", None)
    if (
        value.get("schema") != RUNNER_TERMINAL_SCHEMA
        or value.get("attempt_id") != attempt_id
        or seal != _sha256(canonical_json_bytes(unsigned))
        or value.get("protocol_stage") != PROTOCOL_STAGE
        or type(value.get("child_definitely_dead")) is not bool
        or type(value.get("stop_requested")) is not bool
        or any(value.get(key) is not expected for key, expected in _BOUNDARIES.items())
    ):
        _fail("RUNNER_TERMINAL_INVALID", f"runner terminal receipt invalid: {path}")
    spawn = _read_runner_spawn(root, attempt_id)
    intent = _read_runner_launch_intent(root, attempt_id)
    job_identity = _validate_job_identity(intent.get("job_identity"), attempt_id=attempt_id)
    expected_terminal_states = (
        {"INLINE_TEST_TERMINAL"}
        if spawn.get("inline_test_runner") is True
        else {JobState.PRESENT_EMPTY.value, JobState.ABSENT.value}
    )
    if (
        value.get("job_identity_id") != job_identity["job_identity_id"]
        or value.get("job_name") != job_identity["job_name"]
        or value.get("job_terminal_state") not in expected_terminal_states
        or value.get("child_definitely_dead") is not True
    ):
        _fail("RUNNER_TERMINAL_JOB_INVALID", "terminal does not prove the exact Job is empty")
    if spawn.get("inline_test_runner") is not True:
        live_job = _job_snapshot(attempt_id)
        if live_job.state not in {JobState.PRESENT_EMPTY, JobState.ABSENT}:
            _fail(
                "RUNNER_TERMINAL_JOB_LIVE",
                "candidate terminal cannot seal while the exact Job is nonempty or unknown",
            )
    request = _runner_request(
        root, attempt_id, expected_sha256=str(value.get("runner_request_sha256"))
    )
    if request.get("runner_request_id") != value.get("runner_request_id"):
        _fail("RUNNER_TERMINAL_REQUEST_MISMATCH", "terminal binds a different runner request")
    if value.get("child_pid") is not None:
        started = _read_runner_started(root, attempt_id)
        if value.get("child_pid") != started.get("child_pid") or value.get(
            "runner_pid"
        ) != started.get("runner_pid"):
            _fail("RUNNER_TERMINAL_STARTED_MISMATCH", "terminal binds a different child")
    for ref in request["artifact_refs"].values():
        _verify_artifact_ref(ref, expected_path=None, code="RUNNER_TERMINAL_CONTROL_DRIFT")
    if request.get("prior_candidate_ref") is not None:
        _verify_artifact_ref(
            request["prior_candidate_ref"],
            expected_path=None,
            code="RUNNER_TERMINAL_CONTROL_DRIFT",
        )
    paths = _attempt_paths(root, attempt_id)
    observed_trajectory = (
        sha256_file(paths["stdout"]).casefold() if paths["stdout"].is_file() else None
    )
    observed_stderr = sha256_file(paths["stderr"]).casefold() if paths["stderr"].is_file() else None
    observed_last = (
        sha256_file(paths["last_message"]).casefold() if paths["last_message"].is_file() else None
    )
    if (
        observed_trajectory != value.get("trajectory_sha256")
        or observed_stderr != value.get("stderr_sha256")
        or observed_last != value.get("last_message_sha256")
    ):
        _fail("RUNNER_TERMINAL_ARTIFACT_DRIFT", "terminal-bound output artifacts changed")
    summary = _trajectory_summary(paths["stdout"])
    if (
        summary["event_count"] != value.get("trajectory_event_count")
        or summary["malformed_event_count"] != value.get("trajectory_malformed_event_count")
        or summary["ends_with_newline"] != value.get("trajectory_ends_with_newline")
        or summary["last_event_type"] != value.get("trajectory_last_event_type")
        or summary["complete_success"] != value.get("trajectory_complete_success")
        or summary["session_id"] != value.get("session_id")
        or summary["terminal_events"] != value.get("terminal_events")
    ):
        _fail("RUNNER_TERMINAL_TRAJECTORY_DRIFT", "terminal trajectory summary changed")
    return value


def _failed_attempt_retry_policy(root: Path, current_status: Mapping[str, Any]) -> tuple[bool, str]:
    """Keep carrier recovery failures out of the bounded model-contact budget."""

    opportunity_id = str(current_status["opportunity_id"])
    model_failures = 0
    carrier_failures = 0
    current_started_model = False
    for path in sorted((root / "attempts").glob("*/status.json")):
        status = _read_attempt_status(path)
        if status.get("opportunity_id") != opportunity_id or status.get("status") not in {
            "RETRYABLE",
            "TERMINAL_FAILED",
        }:
            continue
        attempt_id = str(status["attempt_id"])
        started_model = (
            type(status.get("child_pid")) is int
            or isinstance(status.get("session_id"), str)
            or _attempt_paths(root, attempt_id)["runner_started"].is_file()
        )
        if attempt_id == current_status.get("attempt_id"):
            current_started_model = started_model
        if started_model:
            model_failures += 1
        else:
            carrier_failures += 1

    if current_started_model:
        return model_failures < _MAX_MODEL_FAILURES, "BOUNDED_MODEL_RETRY_EXHAUSTED"
    return (
        carrier_failures < _MAX_PRE_MODEL_CARRIER_FAILURES,
        "BOUNDED_CARRIER_RETRY_EXHAUSTED",
    )


def _seal_terminal(root: Path, attempt_id: str) -> dict[str, Any]:
    paths = _attempt_paths(root, attempt_id)
    attempt = _read_json_object(paths["request"], reason_code="ATTEMPT_REQUEST_INVALID")
    terminal = _read_runner_terminal(root, attempt_id)
    current, revision = _load_current(root)
    opportunity_id = str(attempt["opportunity_id"])
    request_path, opportunity_status_path = _opportunity_paths(root, opportunity_id)
    opportunity = _read_opportunity_request(request_path)
    status = _read_attempt_status(paths["status"])
    if status["status"] in {"SEALED", "INVALID_OUTPUT", "TERMINAL_FAILED", "STOPPED"}:
        _repair_attempt_opportunity_projections(root)
        return {
            "outcome": "RECONCILED",
            "attempt_id": attempt_id,
            "candidate_id": status.get("candidate_id"),
            "new_opportunity_ids": [],
            "launched_attempt_ids": [],
            **_BOUNDARIES,
        }

    if (
        terminal.get("child_definitely_dead") is not True
        or terminal.get("release_status") != "RELEASED"
    ):
        reason = (
            "CHILD_DEATH_NOT_CONFIRMED"
            if terminal.get("child_definitely_dead") is not True
            else f"QUOTA_{terminal.get('release_status')}"
        )
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="FAILED_UNKNOWN",
            child_pid=terminal.get("child_pid"),
            runner_pid=terminal.get("runner_pid"),
            account_slot=status.get("account_slot"),
            lease=status.get("lease"),
            reason_code=reason,
            exit_code=terminal.get("exit_code"),
            session_id=terminal.get("session_id"),
            started_at=terminal.get("started_at"),
            ended_at=terminal.get("ended_at"),
        )
        _write_opportunity_status(
            opportunity_status_path,
            opportunity_id=opportunity_id,
            status="ORPHAN_OWN_ATTEMPT",
            attempt_id=attempt_id,
            reason_code=reason,
        )
        return {
            "outcome": "FAILED_UNKNOWN",
            "reason_code": reason,
            "attempt_id": attempt_id,
            "candidate_id": None,
            "new_opportunity_ids": [],
            "launched_attempt_ids": [],
            **_BOUNDARIES,
        }

    if terminal.get("stop_requested") is True or _contract_is_stopped(root, current):
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="STOPPED",
            child_pid=terminal.get("child_pid"),
            runner_pid=terminal.get("runner_pid"),
            account_slot=status.get("account_slot"),
            lease=status.get("lease"),
            reason_code="CONTRACT_STOPPED",
            exit_code=terminal.get("exit_code"),
            session_id=terminal.get("session_id"),
            started_at=terminal.get("started_at"),
            ended_at=terminal.get("ended_at"),
        )
        _write_opportunity_status(
            opportunity_status_path,
            opportunity_id=opportunity_id,
            status="STOPPED",
            attempt_id=attempt_id,
            reason_code="CONTRACT_STOPPED",
        )
        return {
            "outcome": "STOPPED",
            "attempt_id": attempt_id,
            "candidate_id": None,
            "new_opportunity_ids": [],
            "launched_attempt_ids": [],
            **_BOUNDARIES,
        }

    terminal_failed = (
        bool(terminal.get("timed_out"))
        or terminal.get("exit_code") != 0
        or terminal.get("trajectory_complete_success") is not True
        or terminal.get("error_code") is not None
    )
    if terminal_failed:
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="TERMINAL_FAILED",
            child_pid=terminal.get("child_pid"),
            runner_pid=terminal.get("runner_pid"),
            account_slot=status.get("account_slot"),
            lease=status.get("lease"),
            reason_code=str(terminal.get("error_code") or "MODEL_TERMINAL_FAILED"),
            exit_code=terminal.get("exit_code"),
            session_id=terminal.get("session_id"),
            started_at=terminal.get("started_at"),
            ended_at=terminal.get("ended_at"),
        )
        failed_status = _read_attempt_status(paths["status"])
        retry_allowed, exhausted_reason = _failed_attempt_retry_policy(root, failed_status)
        _write_opportunity_status(
            opportunity_status_path,
            opportunity_id=opportunity_id,
            status="RETRYABLE" if retry_allowed else "COMPLETED",
            attempt_id=attempt_id,
            reason_code=(
                str(terminal.get("error_code") or "MODEL_TERMINAL_FAILED")
                if retry_allowed
                else exhausted_reason
            ),
        )
        return {
            "outcome": "RETRYABLE" if retry_allowed else "RECONCILED",
            "attempt_id": attempt_id,
            "new_opportunity_ids": [],
            "launched_attempt_ids": [],
            **_BOUNDARIES,
        }

    try:
        raw_last = paths["last_message"].read_bytes()
        parsed = json.loads(raw_last.decode("utf-8-sig"))
        output = _validate_final_output(parsed)
        if not terminal.get("session_id"):
            _fail("SESSION_ID_MISSING", "fresh contact emitted no thread.started identity")
    except (OSError, UnicodeError, json.JSONDecodeError, OngoingError) as exc:
        reason = exc.reason_code if isinstance(exc, OngoingError) else "FINAL_OUTPUT_INVALID"
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="INVALID_OUTPUT",
            child_pid=terminal.get("child_pid"),
            runner_pid=terminal.get("runner_pid"),
            account_slot=status.get("account_slot"),
            lease=status.get("lease"),
            reason_code=reason,
            exit_code=terminal.get("exit_code"),
            session_id=terminal.get("session_id"),
            started_at=terminal.get("started_at"),
            ended_at=terminal.get("ended_at"),
        )
        _write_opportunity_status(
            opportunity_status_path,
            opportunity_id=opportunity_id,
            status="COMPLETED",
            attempt_id=attempt_id,
            reason_code=reason,
        )
        return {
            "outcome": "RECONCILED",
            "attempt_id": attempt_id,
            "candidate_id": None,
            "new_opportunity_ids": [],
            "launched_attempt_ids": [],
            **_BOUNDARIES,
        }

    environment = _read_json_object(paths["environment"], reason_code="ATTEMPT_ENVIRONMENT_INVALID")
    frozen_bundle = environment.get("bundle")
    if not isinstance(frozen_bundle, Mapping):
        _fail("ATTEMPT_ENVIRONMENT_INVALID", "attempt environment has no frozen evidence bundle")
    bundle_manifest_id = _require_content_id(
        frozen_bundle.get("manifest_id"),
        code="ATTEMPT_ENVIRONMENT_INVALID",
        field="attempt bundle manifest id",
    )
    wake_inventory_id = _require_content_id(
        frozen_bundle.get("wake_inventory_id"),
        code="ATTEMPT_ENVIRONMENT_INVALID",
        field="attempt wake inventory id",
    )
    payload_sha256 = _sha256(str(output["payload"]).encode("utf-8"))
    candidate_identity = {
        "contract_revision_id": current["revision_id"],
        "opportunity_id": opportunity_id,
        "source_fact_id": opportunity["source_fact_id"],
        "external_epoch_id": opportunity["external_epoch_id"],
        "attempt_id": attempt_id,
        "last_message_sha256": terminal["last_message_sha256"],
        "output_sha256": _stable_id(output),
        "payload_sha256": payload_sha256,
        "evidence_manifest_id": bundle_manifest_id,
        "wake_inventory_id": wake_inventory_id,
    }
    candidate_id = _stable_id(candidate_identity)
    trajectory_index = build_trajectory_index(paths["stdout"], paths["trajectory_index"])
    candidate_unsigned = {
        "schema": CANDIDATE_SCHEMA,
        "candidate_id": candidate_id,
        "contract_revision_id": current["revision_id"],
        "opportunity_id": opportunity_id,
        "source_fact_id": opportunity["source_fact_id"],
        "external_epoch_id": opportunity["external_epoch_id"],
        "attempt_id": attempt_id,
        "carrier_result": "OPAQUE_CANDIDATE_PAYLOAD_SEALED",
        "continuation_authorized": False,
        "candidate_output": output,
        "candidate_payload": output["payload"],
        "candidate_payload_sha256": payload_sha256,
        "completed_at": terminal["ended_at"],
        "account_slot": status.get("account_slot"),
        "lease_identity": _read_json_object(
            paths["lease_identity"], reason_code="LEASE_IDENTITY_INVALID"
        ),
        "quota_release_status": terminal.get("release_status"),
        "session_id": terminal["session_id"],
        "source_repo_identity": environment["source_identity"],
        "workspace": environment["workspace"],
        "workspace_clone_identity": environment["clone_identity"],
        "launcher_identity": environment["launcher_identity"],
        "frozen_evidence_bundle": dict(frozen_bundle),
        "prompt_path": str(paths["prompt"]),
        "prompt_sha256": sha256_file(paths["prompt"]).casefold(),
        "output_schema_path": str(paths["output_schema"]),
        "output_schema_sha256": sha256_file(paths["output_schema"]).casefold(),
        "codex_args_path": str(paths["arguments"]),
        "codex_args_sha256": sha256_file(paths["arguments"]).casefold(),
        "trajectory": trajectory_index,
        "stderr_path": str(paths["stderr"]),
        "stderr_sha256": terminal["stderr_sha256"],
        "last_message_path": str(paths["last_message"]),
        "last_message_sha256": terminal["last_message_sha256"],
        "root_main_used": False,
        "root_main_state": "NO_ROOT_MAIN_PATH_TOUCHED",
        "effect_gateway_called": False,
        "fresh_session_only": True,
        "resume_session_id": None,
        "candidate_only": True,
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }
    candidate = {
        **candidate_unsigned,
        "candidate_seal_sha256": _sha256(canonical_json_bytes(candidate_unsigned)),
    }
    _write_once_json(
        root / "candidates" / f"{candidate_id}.json",
        candidate,
        conflict_code="CANDIDATE_CONFLICT",
    )
    _write_attempt_status(
        paths["status"],
        attempt_id=attempt_id,
        opportunity_id=opportunity_id,
        status="SEALED",
        child_pid=terminal.get("child_pid"),
        runner_pid=terminal.get("runner_pid"),
        account_slot=status.get("account_slot"),
        lease=status.get("lease"),
        reason_code=(
            None if terminal.get("release_status") == "RELEASED" else "QUOTA_RELEASE_NOT_CONFIRMED"
        ),
        exit_code=terminal.get("exit_code"),
        session_id=terminal.get("session_id"),
        candidate_id=candidate_id,
        started_at=terminal.get("started_at"),
        ended_at=terminal.get("ended_at"),
    )
    _write_opportunity_status(
        opportunity_status_path,
        opportunity_id=opportunity_id,
        status="COMPLETED",
        attempt_id=attempt_id,
        reason_code=None,
    )
    return {
        "outcome": "RECONCILED",
        "attempt_id": attempt_id,
        "candidate_id": candidate_id,
        "carrier_result": "OPAQUE_CANDIDATE_PAYLOAD_SEALED",
        "new_opportunity_ids": [],
        "launched_attempt_ids": [],
        **_BOUNDARIES,
    }


def _terminate_attempt_process(process: Any, *, inline: bool) -> None:
    """Terminate only the exactly owned attempt carrier.

    Production uses kernel Job authority.  The legacy PID-tree helper remains
    only for injected in-process test doubles which do not create a Job.
    """

    if not inline and hasattr(process, "terminate_tree"):
        process.terminate_tree(exit_code=1)
        return
    terminate_process_tree(process)


def _try_terminate_attempt_process(process: Any, *, inline: bool) -> str | None:
    try:
        _terminate_attempt_process(process, inline=inline)
    except BaseException as exc:
        reason = getattr(exc, "reason_code", type(exc).__name__.upper())
        return f"TERMINATE_{reason}"
    return None


def _run_attempt_runner(
    runtime_root: Path,
    attempt_id: str,
    *,
    popen_factory: Callable[..., Any] | None = None,
    quota_override: Any | None = None,
    lease_override: Mapping[str, Any] | None = None,
    expected_request_sha256: str | None = None,
    launch_nonce: str | None = None,
) -> dict[str, Any]:
    """Dedicated carrier: own model wait/timeout/terminal/release/seal."""

    runtime_root = runtime_root.resolve(strict=False)
    root = _ongoing_root(runtime_root)
    paths = _attempt_paths(root, attempt_id)
    intent = _read_runner_launch_intent(root, attempt_id)
    if expected_request_sha256 is None:
        expected_request_sha256 = str(intent["runner_request_sha256"])
    if launch_nonce is None:
        launch_nonce = str(intent["launch_nonce"])
    if expected_request_sha256 != intent.get("runner_request_sha256") or launch_nonce != intent.get(
        "launch_nonce"
    ):
        _fail("RUNNER_INVOCATION_IDENTITY_INVALID", "runner invocation does not bind launch intent")
    request = _runner_request(root, attempt_id, expected_sha256=expected_request_sha256)
    if not paths["runner_spawn"].is_file() and popen_factory is None:
        _write_once_json(
            paths["runner_spawn"],
            _runner_spawn_value(
                attempt_id=attempt_id,
                runner_pid=os.getpid(),
                inline_test_runner=False,
                intent=intent,
            ),
            conflict_code="RUNNER_SPAWN_CONFLICT",
        )
    spawn = _read_runner_spawn(root, attempt_id)
    inline = bool(spawn.get("inline_test_runner"))
    if not inline and spawn.get("runner_pid") != os.getpid():
        _fail("RUNNER_PID_MISMATCH", "runner spawn identity does not match this process")

    identity = _lease_identity(root, attempt_id)
    job_identity = _validate_job_identity(identity.get("job_identity"), attempt_id=attempt_id)
    quota = quota_override if quota_override is not None else _quota_from_identity(identity)
    lease = dict(lease_override) if lease_override is not None else dict(identity["reserved_lease"])
    started_at = _now_iso()
    process: Any | None = None
    bound_lease: Mapping[str, Any] = lease
    started_receipt_written = False
    timed_out = False
    stop_requested = False
    error_code: str | None = None
    exit_code: int | None = None
    prepared: dict[str, Any] | None = None
    prompt_file: Any | None = None
    cancelled_before_process = False
    paths["stdout"].parent.mkdir(parents=True, exist_ok=True)
    stdout = paths["stdout"].open("ab", buffering=0)
    stderr = paths["stderr"].open("ab", buffering=0)
    model_env = os.environ.copy()
    model_env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "",
        }
    )
    launch_guard = None
    try:
        if not inline:
            deadline = time.monotonic() + 60.0
            while launch_guard is None and time.monotonic() < deadline:
                launch_guard = _acquire_lock(root)
                if launch_guard is None:
                    time.sleep(0.05)
            if launch_guard is None:
                _fail("RUNNER_LAUNCH_LOCK_TIMEOUT", "runner could not acquire launch lock")
        prepared = _validate_runner_preflight(
            runtime_root,
            root,
            attempt_id,
            expected_request_sha256=expected_request_sha256,
            verify_live_lease=(quota_override is None),
        )
        command = list(prepared["command"])
        prompt = bytes(prepared["prompt"])
        try:
            if inline:
                if popen_factory is None:
                    _fail("INLINE_RUNNER_FACTORY_MISSING", "inline runner requires a factory")
                process = popen_factory(
                    command,
                    cwd=prepared["workspace"],
                    stdin=subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env=model_env,
                )
            else:
                # A synchronous write to a child pipe can block before the
                # timeout/Stop loop starts when the prompt exceeds the pipe
                # buffer or the carrier has not begun reading.  The prompt is
                # already an exact sealed artifact; inherit that read-only
                # file handle directly so process creation never depends on a
                # producer-side pipe write.
                prompt_file = paths["prompt"].open("rb", buffering=0)
                if prompt_file.read() != prompt:
                    _fail("MODEL_PROMPT_DRIFT", "prompt file changed after runner preflight")
                prompt_file.seek(0)
                try:
                    process = spawn_windows_job_process(
                        command,
                        job_name=str(job_identity["job_name"]),
                        cwd=prepared["workspace"],
                        stdin=prompt_file,
                        stdout=stdout,
                        stderr=stderr,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        env=model_env,
                    )
                finally:
                    prompt_file.close()
                    prompt_file = None
            started_unsigned = {
                "schema": RUNNER_STARTED_SCHEMA,
                "attempt_id": attempt_id,
                "runner_request_id": request["runner_request_id"],
                "runner_request_sha256": expected_request_sha256,
                "launch_nonce": launch_nonce,
                "job_identity_id": job_identity["job_identity_id"],
                "job_name": job_identity["job_name"],
                "runner_pid": os.getpid(),
                "child_pid": int(process.pid),
                "started_at": started_at,
                "command_sha256": _stable_id(command),
                "protocol_stage": PROTOCOL_STAGE,
                **_BOUNDARIES,
            }
            started_receipt = {
                **started_unsigned,
                "started_seal_sha256": _sha256(canonical_json_bytes(started_unsigned)),
            }
            _write_once_json(
                paths["runner_started"], started_receipt, conflict_code="RUNNER_STARTED_CONFLICT"
            )
            started_receipt_written = True
            # The named Job, not the root PowerShell PID, owns production
            # liveness.  Keep the counted lease RESERVED so every shared
            # reclaimer fails closed while any Job member may still exist.
            if inline:
                bound_lease = quota.bind(lease, child_pid=int(process.pid))
            _write_attempt_status(
                paths["status"],
                attempt_id=attempt_id,
                opportunity_id=str(request["opportunity_id"]),
                status="RUNNING",
                child_pid=int(process.pid),
                runner_pid=os.getpid(),
                account_slot=str(identity["account_slot"]),
                lease=bound_lease,
                started_at=started_at,
            )
        except BaseException:
            raise
        finally:
            if launch_guard is not None:
                _release_byte_lock(launch_guard)
                launch_guard = None

        if inline:
            try:
                process.communicate(input=prompt, timeout=float(request["timeout_seconds"]))
            except subprocess.TimeoutExpired:
                timed_out = True
                error_code = "MODEL_TIMEOUT"
                termination_error = _try_terminate_attempt_process(process, inline=inline)
                error_code = termination_error or error_code
                try:
                    process.wait(timeout=30)
                except Exception:
                    pass
        else:
            timeout_deadline = time.monotonic() + float(request["timeout_seconds"])
            while process.poll() is None:
                try:
                    current, _ = _load_current(root)
                    stop_requested = _contract_is_stopped(root, current)
                except OngoingError:
                    stop_requested = True
                    error_code = "CONTRACT_STATE_UNKNOWN"
                if stop_requested:
                    error_code = error_code or "CONTRACT_STOPPED"
                    termination_error = _try_terminate_attempt_process(process, inline=inline)
                    error_code = termination_error or error_code
                    try:
                        process.wait(timeout=30)
                    except Exception:
                        pass
                    break
                if time.monotonic() >= timeout_deadline:
                    timed_out = True
                    error_code = "MODEL_TIMEOUT"
                    termination_error = _try_terminate_attempt_process(process, inline=inline)
                    error_code = termination_error or error_code
                    try:
                        process.wait(timeout=30)
                    except Exception:
                        pass
                    break
                time.sleep(1.0)
        exit_code = process.poll()
    except BaseException as exc:
        reason = exc.reason_code if isinstance(exc, OngoingError) else type(exc).__name__.upper()
        error_code = error_code or f"RUNNER_{reason}"
        if process is None and isinstance(exc, OngoingError):
            diagnostic = {
                "carrier_error": reason,
                "message": str(exc),
                "model_process_started": False,
            }
            stderr.write((json.dumps(diagnostic, ensure_ascii=False) + "\n").encode("utf-8"))
            stderr.flush()
        cancelled_before_process = process is None and reason in {
            "RUNNER_ATTEMPT_NOT_ACTIVE",
            "RUNNER_LEASE_NOT_RESERVED",
        }
        if process is not None and process.poll() is None:
            termination_error = _try_terminate_attempt_process(process, inline=inline)
            error_code = termination_error or error_code
            try:
                process.wait(timeout=30)
            except Exception:
                pass
        exit_code = process.poll() if process is not None else None
    finally:
        if launch_guard is not None:
            _release_byte_lock(launch_guard)
        if prompt_file is not None and not prompt_file.closed:
            prompt_file.close()
        stdout.close()
        stderr.close()

    if cancelled_before_process:
        return {
            "outcome": "CANCELLED_BEFORE_PROCESS",
            "reason_code": error_code,
            "attempt_id": attempt_id,
            **_BOUNDARIES,
        }

    ended_at = _now_iso()
    if inline:
        job_terminal_state = "INLINE_TEST_TERMINAL"
        child_definitely_dead = process is None or process.poll() is not None
    else:
        snapshot = process.job_snapshot() if process is not None else _job_snapshot(attempt_id)
        job_terminal_state = snapshot.state.value
        child_definitely_dead = snapshot.state in {JobState.PRESENT_EMPTY, JobState.ABSENT}
    if not child_definitely_dead:
        guard = None if inline else _acquire_lock(root)
        try:
            _write_attempt_status(
                paths["status"],
                attempt_id=attempt_id,
                opportunity_id=str(request["opportunity_id"]),
                status="FAILED_UNKNOWN",
                child_pid=int(process.pid) if process is not None else None,
                runner_pid=os.getpid(),
                account_slot=str(identity["account_slot"]),
                lease=bound_lease,
                reason_code="CHILD_DEATH_NOT_CONFIRMED",
                started_at=started_at,
            )
            _, opportunity_status_path = _opportunity_paths(root, str(request["opportunity_id"]))
            _write_opportunity_status(
                opportunity_status_path,
                opportunity_id=str(request["opportunity_id"]),
                status="ORPHAN_OWN_ATTEMPT",
                attempt_id=attempt_id,
                reason_code="CHILD_DEATH_NOT_CONFIRMED",
            )
        finally:
            if guard is not None:
                _release_byte_lock(guard)
        if process is not None and not inline and hasattr(process, "close"):
            process.close()
        return {
            "outcome": "FAILED_UNKNOWN",
            "reason_code": "CHILD_DEATH_NOT_CONFIRMED",
            "attempt_id": attempt_id,
            **_BOUNDARIES,
        }

    try:
        release_status = _release_capacity(quota, bound_lease)
    except Exception as exc:
        release_status = f"RELEASE_ERROR_{type(exc).__name__.upper()}"
    if release_status != "RELEASED":
        # An immutable terminal carrying a transient release failure would
        # strand the RESERVED slot forever because every later tick would
        # replay the terminal instead of retrying exact release.  Keep output
        # non-candidate and leave the attempt recoverable from Job EMPTY/ABSENT.
        guard = None if inline else _acquire_lock(root)
        try:
            if inline or guard is not None:
                _write_attempt_status(
                    paths["status"],
                    attempt_id=attempt_id,
                    opportunity_id=str(request["opportunity_id"]),
                    status="FAILED_UNKNOWN",
                    child_pid=(
                        int(process.pid)
                        if process is not None and started_receipt_written
                        else None
                    ),
                    runner_pid=os.getpid(),
                    account_slot=str(identity["account_slot"]),
                    lease=bound_lease,
                    reason_code=f"QUOTA_{release_status}",
                    exit_code=exit_code,
                    session_id=None,
                    started_at=started_at,
                    ended_at=ended_at,
                )
                _, opportunity_status_path = _opportunity_paths(
                    root, str(request["opportunity_id"])
                )
                _write_opportunity_status(
                    opportunity_status_path,
                    opportunity_id=str(request["opportunity_id"]),
                    status="ORPHAN_OWN_ATTEMPT",
                    attempt_id=attempt_id,
                    reason_code=f"QUOTA_{release_status}",
                )
        finally:
            if guard is not None:
                _release_byte_lock(guard)
        if process is not None and not inline and hasattr(process, "close"):
            process.close()
        return {
            "outcome": "FAILED_UNKNOWN",
            "reason_code": f"QUOTA_{release_status}",
            "attempt_id": attempt_id,
            **_BOUNDARIES,
        }
    _write_runner_terminal(
        root,
        attempt_id,
        runner_pid=os.getpid(),
        child_pid=(int(process.pid) if process is not None and started_receipt_written else None),
        exit_code=exit_code,
        timed_out=timed_out,
        started_at=started_at,
        ended_at=ended_at,
        release_status=release_status,
        error_code=error_code,
        runner_request_id=str(request["runner_request_id"]),
        runner_request_sha256=expected_request_sha256,
        child_definitely_dead=True,
        stop_requested=stop_requested,
        job_terminal_state=job_terminal_state,
    )
    if process is not None and not inline and hasattr(process, "close"):
        process.close()
    if inline:
        return {"outcome": "TERMINAL_PENDING_SEAL", "attempt_id": attempt_id, **_BOUNDARIES}
    guard = _acquire_lock(root)
    if guard is None:
        return {"outcome": "TERMINAL_PENDING_SEAL", "attempt_id": attempt_id, **_BOUNDARIES}
    try:
        return _seal_terminal(root, attempt_id)
    finally:
        _release_byte_lock(guard)


def _materialize_external_opportunities(
    runtime_root: Path,
    root: Path,
    revision: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> list[str]:
    revision_id = str(revision["revision_id"])
    contract = revision["contract"]
    new_ids: list[str] = []
    latest = _latest_candidate(root, revision_id)

    def scheduled_after_contract_floor(fact: Mapping[str, Any]) -> str:
        observed = _parse_iso(str(fact["observed_at"]))
        if latest is None:
            return observed.isoformat()
        floor = _parse_iso(
            _iso_after(
                str(latest["completed_at"]),
                _contract_repeat_delay(contract),
            )
        )
        return max(observed, floor).isoformat()

    observation_wake_created = False
    if _contract_wake_policy(contract)["continuation_observations"]:
        for fact in _observation_facts(runtime_root, revision_id, contract):
            _write_fact(root, fact)
            eligibility = _observation_fact_eligibility(contract, fact)
            if eligibility["eligible"] is not True:
                # The source fact remains durable evidence.  A replaceable
                # contract predicate, not the detector, decides whether this
                # contract revision may derive a cognition opportunity.
                continue
            opportunity_id, opportunity_created = _write_opportunity(
                root,
                revision_id=revision_id,
                fact=fact,
                trigger_type="CONTINUATION_OBSERVATION",
                not_before=scheduled_after_contract_floor(fact),
                workspace_root=str(_contract_clean_room(contract)["workspace_root"]),
                predecessor_candidate_id=(str(latest["candidate_id"]) if latest else None),
            )
            if opportunity_created:
                observation_wake_created = True
                new_ids.append(opportunity_id)

    pending_contact_exists = observation_wake_created or any(
        _read_opportunity_status(path, path.parent.name)["status"]
        in {"DUE", "WAITING_FOR_COMPUTE", "NOT_BEFORE", "RETRYABLE", "RUNNING"}
        for path in (root / "opportunities").glob("*/status.json")
    )

    activation_wake_recomputed = _wake_inventory_id(contract, revision["activation_inventory"])
    activation_wake_supplied = revision.get("activation_wake_inventory_id")
    if activation_wake_supplied is None:
        activation_wake_inventory_id = activation_wake_recomputed
    else:
        activation_wake_inventory_id = _require_content_id(
            activation_wake_supplied,
            code="ACTIVATION_WAKE_INVENTORY_INVALID",
            field="activation wake inventory id",
        )
        if activation_wake_inventory_id != activation_wake_recomputed:
            _fail(
                "ACTIVATION_WAKE_INVENTORY_INVALID",
                "activation wake inventory identity is inconsistent",
            )
    inventory_facts = [
        value
        for path in (root / "facts").glob("*.json")
        for value in [_read_json_object(path, reason_code="FACT_INVALID")]
        if value.get("fact_type") == "INVENTORY_CHANGE"
        and value.get("contract_revision_id") == revision_id
    ]
    current_wake_inventory_id = str(inventory["wake_inventory_id"])
    matching_wake_facts = [
        fact
        for fact in inventory_facts
        if _fact_wake_inventory_id(contract, fact) == current_wake_inventory_id
    ]
    candidate_covered_wake_inventory_ids = {
        str(bundle["wake_inventory_id"])
        for candidate in _candidate_history(root, revision_id)
        for bundle in [_candidate_evidence_bundle(candidate)]
        if bundle.get("wake_inventory_id") is not None
    }
    if (
        _contract_wake_policy(contract)["inventory_changes"]
        and current_wake_inventory_id != activation_wake_inventory_id
    ):
        if matching_wake_facts:
            # One wake epoch may have a richer freeze-only current inventory on
            # replay.  Its first immutable fact remains the trigger identity.
            fact = min(
                matching_wake_facts,
                key=lambda value: (str(value.get("observed_at", "")), str(value["fact_id"])),
            )
        else:
            fact = _inventory_fact(revision_id, inventory, observed_at=_now_iso())
            _write_fact(root, fact)
        # A newly visible receipt also changes any inventory that watches the
        # runtime.  One fresh contact already freezes the whole current
        # inventory, so do not manufacture a second contact for the same tick.
        if (
            not pending_contact_exists
            and current_wake_inventory_id not in candidate_covered_wake_inventory_ids
        ):
            opportunity_id, opportunity_created = _write_opportunity(
                root,
                revision_id=revision_id,
                fact=fact,
                trigger_type="INVENTORY_CHANGE",
                not_before=scheduled_after_contract_floor(fact),
                workspace_root=str(_contract_clean_room(contract)["workspace_root"]),
                predecessor_candidate_id=(str(latest["candidate_id"]) if latest else None),
            )
            if opportunity_created:
                new_ids.append(opportunity_id)
    return sorted(set(new_ids))


def _running_attempt(root: Path) -> tuple[dict[str, Any], dict[str, Path]] | None:
    for path in sorted((root / "attempts").glob("*/status.json")):
        status = _read_attempt_status(path)
        if status["status"] in {
            "CLAIMING_COMPUTE",
            "PREPARING",
            "LAUNCHING",
            "RUNNER_STARTING",
            "CHILD_SPAWNED",
            "RUNNING",
            "FAILED_UNKNOWN",
            "STOP_REQUESTED",
        }:
            return status, _attempt_paths(root, str(status["attempt_id"]))
    return None


def _runner_bootstrap_source() -> str:
    return """import hashlib,json,pathlib,runpy,sys
release=json.loads(sys.argv.pop(1))
def verify(ref):
    path=pathlib.Path(ref['path']).resolve(strict=True)
    raw=path.read_bytes()
    if len(raw)!=ref['size'] or hashlib.sha256(raw).hexdigest().lower()!=ref['sha256']:
        raise SystemExit('RUNNER_RELEASE_DRIFT:'+str(path))
    return path
verify(release['interpreter'])
root=pathlib.Path(release['app_root']).resolve(strict=True)
for relative,ref in release['files'].items():
    if verify(ref)!=(root/pathlib.Path(relative)).resolve(strict=True):
        raise SystemExit('RUNNER_RELEASE_PATH_MISMATCH:'+relative)
unsigned={key:release[key] for key in ('app_root','interpreter','files')}
canonical=json.dumps(unsigned,ensure_ascii=False,indent=2,sort_keys=True).encode('utf-8')+b'\\n'
if hashlib.sha256(canonical).hexdigest()!=release['release_id']:
    raise SystemExit('RUNNER_RELEASE_ID_INVALID')
sys.path.insert(0,str(root))
runpy.run_module('services.research_of_research.ongoing',run_name='__main__',alter_sys=True)
"""


def _spawn_detached_runner(
    runtime_root: Path,
    attempt_id: str,
    paths: Mapping[str, Path],
    *,
    request: Mapping[str, Any],
    request_sha256: str,
    launch_nonce: str,
) -> Any:
    release = request["runner_release"]
    release_json = json.dumps(release, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    bootstrap = _runner_bootstrap_source()
    command = [
        str(release["interpreter"]["path"]),
        "-I",
        "-S",
        "-B",
        "-c",
        bootstrap,
        release_json,
        "_run-attempt",
        "--runtime-root",
        str(runtime_root),
        "--attempt-id",
        attempt_id,
        "--runner-request-sha256",
        request_sha256,
        "--launch-nonce",
        launch_nonce,
    ]
    flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
    )
    paths["runner_stdout"].parent.mkdir(parents=True, exist_ok=True)
    stdout = paths["runner_stdout"].open("ab", buffering=0)
    stderr = paths["runner_stderr"].open("ab", buffering=0)
    try:
        runner_env = os.environ.copy()
        runner_env.pop("PYTHONPATH", None)
        runner_env.pop("PYTHONHOME", None)
        runner_env["PYTHONNOUSERSITE"] = "1"
        return subprocess.Popen(
            command,
            cwd=Path(str(release["app_root"])),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            creationflags=flags,
            start_new_session=(os.name != "nt"),
            env=runner_env,
        )
    finally:
        stdout.close()
        stderr.close()


def _recovery_outcome(
    *,
    outcome: str,
    attempt_id: str,
    reason_code: str | None = None,
    runner_pid: int | None = None,
    child_pid: int | None = None,
) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "attempt_id": attempt_id,
        "reason_code": reason_code,
        "runner_pid": runner_pid,
        "child_pid": child_pid,
        "new_opportunity_ids": [],
        "launched_attempt_ids": [],
        **_BOUNDARIES,
    }


def _write_recovered_attempt(
    root: Path,
    paths: Mapping[str, Path],
    *,
    attempt_status: Mapping[str, Any],
    status: str,
    opportunity_status: str,
    reason_code: str | None,
    runner_pid: int | None = None,
    child_pid: int | None = None,
    account_slot: str | None = None,
    lease: Mapping[str, Any] | None = None,
) -> None:
    attempt_id = str(attempt_status["attempt_id"])
    opportunity_id = str(attempt_status["opportunity_id"])
    _write_attempt_status(
        paths["status"],
        attempt_id=attempt_id,
        opportunity_id=opportunity_id,
        status=status,
        child_pid=child_pid,
        runner_pid=runner_pid,
        account_slot=account_slot,
        lease=lease,
        reason_code=reason_code,
        started_at=attempt_status.get("started_at"),
        ended_at=_now_iso() if status in {"RETRYABLE", "TERMINAL_FAILED", "STOPPED"} else None,
    )
    _, opportunity_status_path = _opportunity_paths(root, opportunity_id)
    _write_opportunity_status(
        opportunity_status_path,
        opportunity_id=opportunity_id,
        status=opportunity_status,
        attempt_id=attempt_id,
        reason_code=reason_code,
    )


def _expected_opportunity_projection(
    root: Path, attempt_status: Mapping[str, Any]
) -> tuple[str, str | None] | None:
    """Derive the durable opportunity projection from an attempt fact.

    Attempt and opportunity status are separate atomic files.  This mapping is
    the restart repair for a crash between those two writes; it creates no new
    scientific or dispatch authority.
    """

    status = str(attempt_status["status"])
    reason = attempt_status.get("reason_code")
    if status == "WAITING_FOR_COMPUTE":
        return "WAITING_FOR_COMPUTE", str(reason) if reason is not None else None
    if status == "RETRYABLE":
        return "RETRYABLE", str(reason) if reason is not None else None
    if status == "SEALED":
        return "COMPLETED", None
    if status == "INVALID_OUTPUT":
        return "COMPLETED", str(reason) if reason is not None else "FINAL_OUTPUT_INVALID"
    if status == "TERMINAL_FAILED":
        retry_allowed, exhausted_reason = _failed_attempt_retry_policy(root, attempt_status)
        if retry_allowed:
            return "RETRYABLE", str(reason) if reason is not None else "MODEL_TERMINAL_FAILED"
        return "COMPLETED", exhausted_reason
    if status == "STOPPED":
        return "STOPPED", str(reason) if reason is not None else "CONTRACT_STOPPED"
    if status in {"FAILED_UNKNOWN", "STOP_REQUESTED"}:
        return "ORPHAN_OWN_ATTEMPT", str(reason) if reason is not None else status
    return None


def _repair_attempt_opportunity_projections(root: Path) -> list[str]:
    repaired: list[str] = []
    latest_by_opportunity: dict[str, tuple[int, dict[str, Any]]] = {}
    seen_ordinals: dict[str, set[int]] = {}
    for path in sorted((root / "attempts").glob("*/status.json")):
        attempt_status = _read_attempt_status(path)
        attempt_id = str(attempt_status["attempt_id"])
        request = _read_json_object(
            _attempt_paths(root, attempt_id)["request"], reason_code="ATTEMPT_REQUEST_INVALID"
        )
        opportunity_id = str(attempt_status["opportunity_id"])
        ordinal = request.get("ordinal")
        if (
            type(ordinal) is not int
            or ordinal < 1
            or request.get("opportunity_id") != opportunity_id
            or request.get("attempt_id") != attempt_id
            or attempt_id != _stable_id({"opportunity_id": opportunity_id, "ordinal": ordinal})
        ):
            _fail("ATTEMPT_REPAIR_IDENTITY_INVALID", f"attempt repair identity invalid: {path}")
        opportunity_ordinals = seen_ordinals.setdefault(opportunity_id, set())
        if ordinal in opportunity_ordinals:
            _fail(
                "ATTEMPT_REPAIR_ORDINAL_DUPLICATE",
                f"duplicate attempt ordinal for opportunity {opportunity_id}",
            )
        opportunity_ordinals.add(ordinal)
        prior = latest_by_opportunity.get(opportunity_id)
        if prior is None or ordinal > prior[0]:
            latest_by_opportunity[opportunity_id] = (ordinal, attempt_status)

    for opportunity_id, (_, attempt_status) in sorted(latest_by_opportunity.items()):
        attempt_id = str(attempt_status["attempt_id"])
        attempt_request = _read_json_object(
            _attempt_paths(root, attempt_id)["request"],
            reason_code="ATTEMPT_REQUEST_INVALID",
        )
        attempt_revision_id = _require_content_id(
            attempt_request.get("contract_revision_id"),
            code="ATTEMPT_REQUEST_INVALID",
            field="attempt contract revision id",
        )
        expected = (
            ("STOPPED", "CONTRACT_STOPPED")
            if _read_stop(root, attempt_revision_id) is not None
            else _expected_opportunity_projection(root, attempt_status)
        )
        if expected is None:
            continue
        _, opportunity_status_path = _opportunity_paths(root, opportunity_id)
        observed = _read_opportunity_status(opportunity_status_path, opportunity_id)
        expected_status, expected_reason = expected
        if (
            observed.get("status") == expected_status
            and observed.get("attempt_id") == attempt_id
            and observed.get("reason_code") == expected_reason
        ):
            continue
        _write_opportunity_status(
            opportunity_status_path,
            opportunity_id=opportunity_id,
            status=expected_status,
            attempt_id=attempt_id,
            reason_code=expected_reason,
        )
        repaired.append(attempt_id)
    return repaired


def _release_recovered_lease(
    root: Path,
    paths: Mapping[str, Path],
    *,
    attempt_status: Mapping[str, Any],
    stopped: bool,
    reason_code: str,
) -> dict[str, Any]:
    attempt_id = str(attempt_status["attempt_id"])
    identity, lease = _owned_lease_record(root, attempt_id)
    release_status = _release_capacity(_quota_from_identity(identity), lease)
    if release_status != "RELEASED":
        failure = f"{reason_code}:{release_status}"
        _write_recovered_attempt(
            root,
            paths,
            attempt_status=attempt_status,
            status="FAILED_UNKNOWN",
            opportunity_status="ORPHAN_OWN_ATTEMPT",
            reason_code=failure,
            runner_pid=(
                int(attempt_status["runner_pid"])
                if type(attempt_status.get("runner_pid")) is int
                else None
            ),
            child_pid=(
                int(attempt_status["child_pid"])
                if type(attempt_status.get("child_pid")) is int
                else None
            ),
            account_slot=str(identity["account_slot"]),
            lease=lease,
        )
        return _recovery_outcome(
            outcome="FAILED_UNKNOWN",
            attempt_id=attempt_id,
            reason_code=failure,
        )
    if stopped:
        attempt_projection = "STOPPED"
        opportunity_projection = "STOPPED"
        outcome = "STOPPED"
        final_reason = "CONTRACT_STOPPED_BEFORE_MODEL_START"
    else:
        attempt_projection = "RETRYABLE"
        opportunity_projection = "RETRYABLE"
        outcome = "RETRYABLE"
        final_reason = reason_code
    _write_recovered_attempt(
        root,
        paths,
        attempt_status=attempt_status,
        status=attempt_projection,
        opportunity_status=opportunity_projection,
        reason_code=final_reason,
        account_slot=str(identity["account_slot"]),
        lease=lease,
    )
    return _recovery_outcome(
        outcome=outcome,
        attempt_id=attempt_id,
        reason_code=final_reason,
    )


def _job_timeout_due(root: Path, attempt_id: str) -> bool:
    request = _runner_request(root, attempt_id)
    deadline = _parse_iso(str(request["created_at"])) + dt.timedelta(
        seconds=int(request["timeout_seconds"]) + 60
    )
    return _parse_iso(_now_iso()) >= deadline


def _job_recovery_hold(
    root: Path,
    paths: Mapping[str, Path],
    *,
    attempt_status: Mapping[str, Any],
    lease: Mapping[str, Any],
    account_slot: str,
    runner_pid: int | None,
    child_pid: int | None,
    stopped: bool,
    reason_code: str,
    outcome: str,
    attempt_projection: str = "FAILED_UNKNOWN",
) -> dict[str, Any]:
    _write_recovered_attempt(
        root,
        paths,
        attempt_status=attempt_status,
        status="STOP_REQUESTED" if stopped else attempt_projection,
        opportunity_status="ORPHAN_OWN_ATTEMPT" if stopped else "RUNNING",
        reason_code=reason_code,
        runner_pid=runner_pid,
        child_pid=child_pid,
        account_slot=account_slot,
        lease=lease,
    )
    return _recovery_outcome(
        outcome="STOP_PENDING" if stopped else outcome,
        attempt_id=str(attempt_status["attempt_id"]),
        reason_code=reason_code,
        runner_pid=runner_pid,
        child_pid=child_pid,
    )


def _recover_running_attempt(
    root: Path,
    attempt_status: Mapping[str, Any],
    paths: Mapping[str, Path],
    *,
    stopped: bool,
) -> dict[str, Any]:
    """Rebuild mutable projections from receipts and deterministic Job ownership."""

    attempt_id = str(attempt_status["attempt_id"])
    has_identity = paths["lease_identity"].is_file()
    has_intent = paths["runner_launch_intent"].is_file()
    has_spawn = paths["runner_spawn"].is_file()
    has_started = paths["runner_started"].is_file()

    if not has_identity:
        if has_intent or has_spawn or has_started:
            return _recovery_outcome(
                outcome="FAILED_UNKNOWN",
                attempt_id=attempt_id,
                reason_code="LEASE_IDENTITY_MISSING_AFTER_RUNNER_AUTHORIZATION",
            )
        try:
            discovered = _scan_exact_attempt_lease(root, attempt_id)
        except OngoingError as exc:
            if exc.reason_code == "QUOTA_SCAN_LOCK_TIMEOUT":
                # Do not project WAITING_FOR_COMPUTE here.  A counted RESERVED
                # lease may already exist but remain undiscovered, so the
                # CLAIMING_COMPUTE attempt must stay the sole idempotency
                # barrier until a later tick can inspect both account roots.
                return _recovery_outcome(
                    outcome="LOCK_BUSY",
                    attempt_id=attempt_id,
                    reason_code=exc.reason_code,
                )
            return _recovery_outcome(
                outcome="FAILED_UNKNOWN",
                attempt_id=attempt_id,
                reason_code=exc.reason_code,
            )
        if discovered is None or discovered[1].get("status") == "RELEASED":
            # Nothing crossed the durable quota boundary.  Keep the same
            # attempt as a waiting request so the normal launch path reuses
            # its identity instead of spending a bounded model retry on a
            # reconciler crash that never launched cognition.
            projection = "STOPPED" if stopped else "WAITING_FOR_COMPUTE"
            _write_recovered_attempt(
                root,
                paths,
                attempt_status=attempt_status,
                status=projection,
                opportunity_status=projection,
                reason_code=(
                    "CONTRACT_STOPPED_WITHOUT_CAPACITY" if stopped else "PRE_CLAIM_CRASH_RECOVERED"
                ),
            )
            return _recovery_outcome(
                outcome=projection,
                attempt_id=attempt_id,
                reason_code=(
                    "CONTRACT_STOPPED_WITHOUT_CAPACITY" if stopped else "PRE_CLAIM_CRASH_RECOVERED"
                ),
            )
        identity, lease = discovered
        if lease.get("status") != "RESERVED":
            return _recovery_outcome(
                outcome="FAILED_UNKNOWN",
                attempt_id=attempt_id,
                reason_code="PRE_IDENTITY_LEASE_STATUS_UNKNOWN",
            )
        _write_once_json(paths["lease_identity"], identity, conflict_code="LEASE_IDENTITY_CONFLICT")
        has_identity = True

    # No carrier was authorized yet.  A durable exact RESERVED lease belongs
    # only to this attempt and can be released without probing any PID.
    if not has_intent:
        identity, lease = _owned_lease_record(root, attempt_id)
        if lease.get("status") not in {"RESERVED", "RELEASED"}:
            return _recovery_outcome(
                outcome="FAILED_UNKNOWN",
                attempt_id=attempt_id,
                reason_code="PRE_RUNNER_LEASE_STATUS_UNKNOWN",
            )
        return _release_recovered_lease(
            root,
            paths,
            attempt_status=attempt_status,
            stopped=stopped,
            reason_code="PRE_RUNNER_CRASH_RECOVERED",
        )

    # The production runner cannot create the model without this same lock and
    # an exact RESERVED preflight.  Therefore EMPTY/ABSENT is a safe barrier:
    # release first, mark this attempt inactive, and any late runner cancels
    # before CreateProcess.  NONEMPTY/UNKNOWN always keeps capacity.
    if not has_spawn:
        identity, lease = _owned_lease_record(root, attempt_id)
        account_slot = str(identity["account_slot"])
        snapshot = _job_snapshot(attempt_id)
        if snapshot.state == JobState.UNKNOWN:
            return _job_recovery_hold(
                root,
                paths,
                attempt_status=attempt_status,
                lease=lease,
                account_slot=account_slot,
                runner_pid=None,
                child_pid=None,
                stopped=stopped,
                reason_code="RUNNER_SPAWN_GAP_JOB_UNKNOWN",
                outcome="RUNNING_UNKNOWN",
            )
        if snapshot.state == JobState.PRESENT_NONEMPTY:
            if lease.get("status") != "RESERVED":
                return _job_recovery_hold(
                    root,
                    paths,
                    attempt_status=attempt_status,
                    lease=lease,
                    account_slot=account_slot,
                    runner_pid=None,
                    child_pid=None,
                    stopped=stopped,
                    reason_code="JOB_NONEMPTY_WITHOUT_RESERVED_CAPACITY",
                    outcome="FAILED_UNKNOWN",
                )
            if stopped or _job_timeout_due(root, attempt_id):
                before = _terminate_job(attempt_id)
                if before.state == JobState.UNKNOWN:
                    return _job_recovery_hold(
                        root,
                        paths,
                        attempt_status=attempt_status,
                        lease=lease,
                        account_slot=account_slot,
                        runner_pid=None,
                        child_pid=None,
                        stopped=stopped,
                        reason_code="JOB_TERMINATION_UNKNOWN",
                        outcome="FAILED_UNKNOWN",
                    )
                after = _job_snapshot(attempt_id)
                if after.state not in {JobState.PRESENT_EMPTY, JobState.ABSENT}:
                    return _job_recovery_hold(
                        root,
                        paths,
                        attempt_status=attempt_status,
                        lease=lease,
                        account_slot=account_slot,
                        runner_pid=None,
                        child_pid=None,
                        stopped=stopped,
                        reason_code="JOB_TERMINATION_PENDING",
                        outcome="RUNNING",
                        attempt_projection="CHILD_SPAWNED",
                    )
            else:
                return _job_recovery_hold(
                    root,
                    paths,
                    attempt_status=attempt_status,
                    lease=lease,
                    account_slot=account_slot,
                    runner_pid=None,
                    child_pid=None,
                    stopped=False,
                    reason_code="JOB_OWNS_CHILD_BEFORE_RUNNER_RECEIPT",
                    outcome="RUNNING",
                    attempt_projection="CHILD_SPAWNED",
                )
        if lease.get("status") not in {"RESERVED", "RELEASED"}:
            return _job_recovery_hold(
                root,
                paths,
                attempt_status=attempt_status,
                lease=lease,
                account_slot=account_slot,
                runner_pid=None,
                child_pid=None,
                stopped=stopped,
                reason_code="JOB_TERMINAL_LEASE_STATUS_DRIFT",
                outcome="FAILED_UNKNOWN",
            )
        return _release_recovered_lease(
            root,
            paths,
            attempt_status=attempt_status,
            stopped=stopped,
            reason_code="RUNNER_SPAWN_GAP_JOB_TERMINAL",
        )

    spawn = _read_runner_spawn(root, attempt_id)
    if spawn.get("inline_test_runner") is not True:
        runner_pid = int(spawn["runner_pid"])
        runner_liveness = _process_liveness(runner_pid)
        identity, lease = _owned_lease_record(root, attempt_id)
        account_slot = str(identity["account_slot"])
        _validate_job_identity(identity.get("job_identity"), attempt_id=attempt_id)
        started = _read_runner_started(root, attempt_id) if has_started else None
        child_pid = int(started["child_pid"]) if started is not None else None
        snapshot = _job_snapshot(attempt_id)

        if snapshot.state == JobState.UNKNOWN:
            return _job_recovery_hold(
                root,
                paths,
                attempt_status=attempt_status,
                lease=lease,
                account_slot=account_slot,
                runner_pid=runner_pid,
                child_pid=child_pid,
                stopped=stopped,
                reason_code="JOB_LIVENESS_UNKNOWN",
                outcome="RUNNING_UNKNOWN",
            )

        if snapshot.state == JobState.PRESENT_NONEMPTY:
            if lease.get("status") != "RESERVED":
                return _job_recovery_hold(
                    root,
                    paths,
                    attempt_status=attempt_status,
                    lease=lease,
                    account_slot=account_slot,
                    runner_pid=runner_pid,
                    child_pid=child_pid,
                    stopped=stopped,
                    reason_code="JOB_NONEMPTY_WITHOUT_RESERVED_CAPACITY",
                    outcome="FAILED_UNKNOWN",
                )
            if stopped or _job_timeout_due(root, attempt_id):
                before = _terminate_job(attempt_id)
                if before.state == JobState.UNKNOWN:
                    return _job_recovery_hold(
                        root,
                        paths,
                        attempt_status=attempt_status,
                        lease=lease,
                        account_slot=account_slot,
                        runner_pid=runner_pid,
                        child_pid=child_pid,
                        stopped=stopped,
                        reason_code="JOB_TERMINATION_UNKNOWN",
                        outcome="FAILED_UNKNOWN",
                    )
                after = _job_snapshot(attempt_id)
                if after.state not in {JobState.PRESENT_EMPTY, JobState.ABSENT}:
                    return _job_recovery_hold(
                        root,
                        paths,
                        attempt_status=attempt_status,
                        lease=lease,
                        account_slot=account_slot,
                        runner_pid=runner_pid,
                        child_pid=child_pid,
                        stopped=stopped,
                        reason_code="JOB_TERMINATION_PENDING",
                        outcome="RUNNING",
                        attempt_projection="CHILD_SPAWNED",
                    )
                snapshot = after
            else:
                _write_recovered_attempt(
                    root,
                    paths,
                    attempt_status=attempt_status,
                    status="RUNNING" if started is not None else "CHILD_SPAWNED",
                    opportunity_status="RUNNING",
                    reason_code="KERNEL_JOB_OWNS_PROCESS_TREE",
                    runner_pid=runner_pid,
                    child_pid=child_pid,
                    account_slot=account_slot,
                    lease=lease,
                )
                return _recovery_outcome(
                    outcome="RUNNING",
                    attempt_id=attempt_id,
                    reason_code="KERNEL_JOB_OWNS_PROCESS_TREE",
                    runner_pid=runner_pid,
                    child_pid=child_pid,
                )

        # Job EMPTY while a runner is alive is normal finalization.  Let the
        # exact owner write terminal evidence; ABSENT is also safe to cancel a
        # pre-launch waiter because active-status and RESERVED checks are under
        # this same lock.
        if (
            snapshot.state == JobState.PRESENT_EMPTY
            and runner_liveness in {"ALIVE", "UNKNOWN"}
            and not stopped
        ):
            return _job_recovery_hold(
                root,
                paths,
                attempt_status=attempt_status,
                lease=lease,
                account_slot=account_slot,
                runner_pid=runner_pid,
                child_pid=child_pid,
                stopped=False,
                reason_code=f"JOB_EMPTY_RUNNER_{runner_liveness}_FINALIZING",
                outcome="RUNNING" if runner_liveness == "ALIVE" else "RUNNING_UNKNOWN",
                attempt_projection="RUNNING",
            )
        if lease.get("status") not in {"RESERVED", "RELEASED"}:
            return _job_recovery_hold(
                root,
                paths,
                attempt_status=attempt_status,
                lease=lease,
                account_slot=account_slot,
                runner_pid=runner_pid,
                child_pid=child_pid,
                stopped=stopped,
                reason_code="JOB_TERMINAL_LEASE_STATUS_DRIFT",
                outcome="FAILED_UNKNOWN",
            )
        return _release_recovered_lease(
            root,
            paths,
            attempt_status=attempt_status,
            stopped=stopped,
            reason_code="KERNEL_JOB_TERMINAL_RECOVERED",
        )

    # Inline injected tests retain their Popen/PID projection.  They never
    # represent the installed production ownership mechanism.
    runner_pid = int(spawn["runner_pid"])
    runner_liveness = _process_liveness(runner_pid)
    identity = _lease_identity(root, attempt_id)
    lease = dict(identity["reserved_lease"])
    account_slot = str(identity["account_slot"])

    started: dict[str, Any] | None = None
    child_pid: int | None = None
    if has_started:
        started = _read_runner_started(root, attempt_id)
        child_pid = int(started["child_pid"])
        if not stopped or runner_liveness == "DEAD":
            identity, lease = _owned_lease_record(root, attempt_id)
        if lease.get("status") == "BOUND" and lease.get("child_pid") != child_pid and not stopped:
            _write_recovered_attempt(
                root,
                paths,
                attempt_status=attempt_status,
                status="FAILED_UNKNOWN",
                opportunity_status="ORPHAN_OWN_ATTEMPT",
                reason_code="RUNNER_STARTED_LEASE_CHILD_MISMATCH",
                runner_pid=runner_pid,
                child_pid=child_pid,
                account_slot=account_slot,
                lease=lease,
            )
            return _recovery_outcome(
                outcome="FAILED_UNKNOWN",
                attempt_id=attempt_id,
                reason_code="RUNNER_STARTED_LEASE_CHILD_MISMATCH",
                runner_pid=runner_pid,
                child_pid=child_pid,
            )

    if runner_liveness == "DEAD" and started is None:
        # Read the live exact lease only when an effect (release) might later be
        # considered.  A live runner-spawn adoption is projection repair and
        # must not depend on a temporarily unavailable mutable quota readback.
        identity, lease = _owned_lease_record(root, attempt_id)

    if runner_liveness in {"ALIVE", "UNKNOWN"}:
        if stopped:
            if runner_liveness == "ALIVE":
                _write_recovered_attempt(
                    root,
                    paths,
                    attempt_status=attempt_status,
                    status="STOP_REQUESTED",
                    opportunity_status="ORPHAN_OWN_ATTEMPT",
                    reason_code="CONTRACT_STOPPED_RUNNER_OWNS_TERMINATION",
                    runner_pid=runner_pid,
                    child_pid=child_pid,
                    account_slot=account_slot,
                    lease=lease,
                )
            return _recovery_outcome(
                outcome="STOP_PENDING",
                attempt_id=attempt_id,
                reason_code=f"RUNNER_{runner_liveness}",
                runner_pid=runner_pid,
                child_pid=child_pid,
            )
        if runner_liveness == "ALIVE":
            projection = (
                "RUNNING"
                if started is not None and lease.get("status") == "BOUND"
                else "RUNNER_STARTING"
            )
            _write_recovered_attempt(
                root,
                paths,
                attempt_status=attempt_status,
                status=projection,
                opportunity_status="RUNNING",
                reason_code=None,
                runner_pid=runner_pid,
                child_pid=child_pid if projection == "RUNNING" else None,
                account_slot=account_slot,
                lease=lease,
            )
        return _recovery_outcome(
            outcome="RUNNING" if runner_liveness == "ALIVE" else "RUNNING_UNKNOWN",
            attempt_id=attempt_id,
            runner_pid=runner_pid,
            child_pid=child_pid,
        )

    # A dead runner without a started receipt may still have crossed model
    # Popen.  No JSON or raw PID can prove the child absent, so retain capacity.
    if started is None:
        _write_recovered_attempt(
            root,
            paths,
            attempt_status=attempt_status,
            status="FAILED_UNKNOWN",
            opportunity_status="ORPHAN_OWN_ATTEMPT",
            reason_code="RUNNER_DIED_BEFORE_STARTED_RECEIPT",
            runner_pid=runner_pid,
            account_slot=account_slot,
            lease=lease,
        )
        return _recovery_outcome(
            outcome="STOP_PENDING" if stopped else "FAILED_UNKNOWN",
            attempt_id=attempt_id,
            reason_code="RUNNER_DIED_BEFORE_STARTED_RECEIPT",
            runner_pid=runner_pid,
        )

    child_liveness = _process_liveness(child_pid)
    if child_liveness in {"ALIVE", "UNKNOWN"}:
        # The model may still be producing evidence after its waiter died.
        # Keep polling this exact receipt; never taskkill or start a duplicate.
        _write_recovered_attempt(
            root,
            paths,
            attempt_status=attempt_status,
            status="STOP_REQUESTED" if stopped else "CHILD_SPAWNED",
            opportunity_status="RUNNING" if not stopped else "ORPHAN_OWN_ATTEMPT",
            reason_code=(
                "CONTRACT_STOPPED_CHILD_STILL_OWNED"
                if stopped
                else f"RUNNER_DIED_CHILD_{child_liveness}"
            ),
            runner_pid=runner_pid,
            child_pid=child_pid,
            account_slot=account_slot,
            lease=lease,
        )
        return _recovery_outcome(
            outcome="STOP_PENDING"
            if stopped
            else ("RUNNING" if child_liveness == "ALIVE" else "RUNNING_UNKNOWN"),
            attempt_id=attempt_id,
            reason_code=f"RUNNER_DIED_CHILD_{child_liveness}",
            runner_pid=runner_pid,
            child_pid=child_pid,
        )

    # Both recorded owners are definitely dead.  The exact lease release is
    # the only effect; partial model output is never promoted to a candidate.
    return _release_recovered_lease(
        root,
        paths,
        attempt_status=attempt_status,
        stopped=stopped,
        reason_code="RUNNER_DIED_CHILD_DEAD_RECOVERED",
    )


def _launch_due_opportunity(
    runtime_root: Path,
    root: Path,
    revision: Mapping[str, Any],
    inventory: Mapping[str, Any],
    opportunity: Mapping[str, Any],
    *,
    popen_factory: Callable[..., Any] | None,
) -> dict[str, Any]:
    opportunity_id = str(opportunity["opportunity_id"])
    if opportunity.get("contract_revision_id") != revision.get("revision_id"):
        _fail(
            "OPPORTUNITY_REVISION_MISMATCH", "opportunity does not bind current contract revision"
        )
    expected_workspace_root = Path(
        str(_contract_clean_room(revision["contract"])["workspace_root"])
    ).resolve(strict=False)
    if (
        Path(str(opportunity.get("workspace_root"))).resolve(strict=False)
        != expected_workspace_root
    ):
        _fail("OPPORTUNITY_WORKSPACE_ROOT_MISMATCH", "opportunity workspace root drifted")
    trigger_fact = _read_source_fact(root, str(opportunity["source_fact_id"]))
    if trigger_fact.get("contract_revision_id") != revision.get("revision_id"):
        _fail("TRIGGER_FACT_REVISION_MISMATCH", "trigger fact does not bind current revision")
    _, opportunity_status_path = _opportunity_paths(root, opportunity_id)
    prior_status = _read_opportunity_status(opportunity_status_path, opportunity_id)
    if prior_status["status"] == "WAITING_FOR_COMPUTE" and prior_status.get("attempt_id"):
        attempt_id = str(prior_status["attempt_id"])
        paths = _attempt_paths(root, attempt_id)
        attempt = _read_json_object(paths["request"], reason_code="ATTEMPT_REQUEST_INVALID")
    else:
        attempt, paths = _next_attempt(root, opportunity)
        attempt_id = str(attempt["attempt_id"])
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="CLAIMING_COMPUTE",
        )
    workspace = Path(str(attempt["workspace"]))
    capacity = _claim_capacity(
        revision["contract"],
        attempt_id=attempt_id,
        opportunity_id=opportunity_id,
        workspace=workspace,
    )
    if capacity.get("outcome") != "CLAIMED":
        reason = str(capacity.get("reason_code", "COMPUTE_UNKNOWN"))
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="WAITING_FOR_COMPUTE",
            reason_code=reason,
        )
        _write_opportunity_status(
            opportunity_status_path,
            opportunity_id=opportunity_id,
            status="WAITING_FOR_COMPUTE",
            attempt_id=attempt_id,
            reason_code=reason,
        )
        return {
            "outcome": "WAITING_FOR_COMPUTE",
            "reason_code": reason,
            "attempt_id": attempt_id,
            "new_opportunity_ids": [],
            "launched_attempt_ids": [],
            **_BOUNDARIES,
        }
    quota = capacity["quota"]
    lease = dict(capacity["lease"])
    account = str(lease.get("account_slot"))
    slot = int(lease.get("slot", 1))
    lease_path = Path(
        str(
            lease.get(
                "path",
                DEFAULT_QUOTA_ROOT.resolve(strict=False) / account / f"world-turn-{slot:02d}.json",
            )
        )
    ).resolve(strict=False)
    lease["path"] = str(lease_path)
    lease_identity = _lease_identity_value(
        root,
        attempt_id=attempt_id,
        opportunity_id=opportunity_id,
        lease=lease,
    )
    _write_once_json(
        paths["lease_identity"], lease_identity, conflict_code="LEASE_IDENTITY_CONFLICT"
    )
    _write_attempt_status(
        paths["status"],
        attempt_id=attempt_id,
        opportunity_id=opportunity_id,
        status="PREPARING",
        account_slot=account,
        lease=lease,
    )
    try:
        environment = _prepare_attempt_environment(
            runtime_root,
            root,
            revision["contract"],
            revision,
            inventory,
            trigger_fact,
            attempt,
            paths,
        )
        _write_once_json(
            paths["environment"], environment, conflict_code="ATTEMPT_ENVIRONMENT_CONFLICT"
        )
        schema = _output_schema()
        _write_once_json(paths["output_schema"], schema, conflict_code="OUTPUT_SCHEMA_CONFLICT")
        prior_candidate = _latest_candidate(root, str(revision["revision_id"]))
        prompt = _build_prompt(
            revision["contract"],
            revision,
            opportunity,
            trigger_fact,
            environment["bundle"],
            prior_candidate,
        )
        _write_once_bytes(paths["prompt"], prompt.encode("utf-8"), conflict_code="PROMPT_CONFLICT")
        config = {
            "model": _contract_carrier_value(revision["contract"], "model"),
            "model_reasoning_effort": _contract_carrier_value(
                revision["contract"], "model_reasoning_effort"
            ),
            "powershell_path": _contract_clean_room(revision["contract"])["powershell_path"],
            "launcher_path": str(paths["launcher"]),
            "account_slot": account,
        }
        arguments = build_codex_arguments(
            config, last_message_path=paths["last_message"], session_id=None
        )
        arguments[-1:-1] = ["--output-schema", str(paths["output_schema"])]
        _write_once_json(paths["arguments"], arguments, conflict_code="CODEX_ARGUMENTS_CONFLICT")
        command = build_codex_command(
            config, workspace=Path(str(environment["workspace"])), arguments_path=paths["arguments"]
        )
        _write_once_json(
            paths["command"],
            {
                "schema": "xinao.research-of-research.ongoing-command.v1",
                "argv": command,
                "codex_argv": arguments,
                "fresh_session_only": True,
                "resume_session_id": None,
                "root_main_used": False,
                "root_main_state": "NO_ROOT_MAIN_PATH_TOUCHED",
                "protocol_stage": PROTOCOL_STAGE,
                **_BOUNDARIES,
            },
            conflict_code="COMMAND_CONFLICT",
        )
        runner_request = _build_runner_request(
            root,
            revision=revision,
            inventory=inventory,
            opportunity=opportunity,
            attempt=attempt,
            trigger_fact=trigger_fact,
            environment=environment,
            prior_candidate=prior_candidate,
            paths=paths,
        )
        _write_once_json(
            paths["runner_request"], runner_request, conflict_code="RUNNER_REQUEST_CONFLICT"
        )
        runner_request_sha256 = sha256_file(paths["runner_request"]).casefold()
        launch_nonce = _stable_id(
            {
                "attempt_id": attempt_id,
                "runner_request_id": runner_request["runner_request_id"],
                "runner_request_sha256": runner_request_sha256,
            }
        )
        launch_intent = _runner_launch_intent_value(
            attempt_id=attempt_id,
            request=runner_request,
            request_sha256=runner_request_sha256,
            launch_nonce=launch_nonce,
        )
        _write_once_json(
            paths["runner_launch_intent"],
            launch_intent,
            conflict_code="RUNNER_LAUNCH_INTENT_CONFLICT",
        )
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="LAUNCHING",
            account_slot=account,
            lease=lease,
        )
    except BaseException as exc:
        release = _release_capacity(quota, lease)
        reason = exc.reason_code if isinstance(exc, OngoingError) else type(exc).__name__.upper()
        try:
            atomic_write_bytes(
                paths["stderr"],
                canonical_json_bytes(
                    {
                        "carrier_error": reason,
                        "message": str(exc),
                        "model_process_started": False,
                        "phase": "PREPARE",
                    }
                ),
            )
        except OSError:
            pass
        released = release == "RELEASED"
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="RETRYABLE" if released else "FAILED_UNKNOWN",
            account_slot=account,
            lease=lease,
            reason_code=f"PREPARE_{reason}:{release}",
        )
        _write_opportunity_status(
            opportunity_status_path,
            opportunity_id=opportunity_id,
            status="RETRYABLE" if released else "ORPHAN_OWN_ATTEMPT",
            attempt_id=attempt_id,
            reason_code=f"PREPARE_{reason}",
        )
        return {
            "outcome": "RETRYABLE" if released else "FAILED_UNKNOWN",
            "reason_code": f"PREPARE_{reason}",
            "attempt_id": attempt_id,
            "new_opportunity_ids": [],
            "launched_attempt_ids": [],
            **_BOUNDARIES,
        }

    if popen_factory is not None:
        _write_once_json(
            paths["runner_spawn"],
            _runner_spawn_value(
                attempt_id=attempt_id,
                runner_pid=os.getpid(),
                inline_test_runner=True,
                intent=launch_intent,
            ),
            conflict_code="RUNNER_SPAWN_CONFLICT",
        )
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="RUNNER_STARTING",
            runner_pid=os.getpid(),
            account_slot=account,
            lease=lease,
        )
        result = _run_attempt_runner(
            runtime_root,
            attempt_id,
            popen_factory=popen_factory,
            quota_override=quota,
            lease_override=lease,
            expected_request_sha256=runner_request_sha256,
            launch_nonce=launch_nonce,
        )
        if paths["runner_terminal"].is_file():
            result = _seal_terminal(root, attempt_id)
        return {**result, "launched_attempt_ids": [attempt_id]}

    try:
        runner = _spawn_detached_runner(
            runtime_root,
            attempt_id,
            paths,
            request=runner_request,
            request_sha256=runner_request_sha256,
            launch_nonce=launch_nonce,
        )
    except BaseException as exc:
        release = _release_capacity(quota, lease)
        reason = exc.reason_code if isinstance(exc, OngoingError) else type(exc).__name__.upper()
        released = release == "RELEASED"
        _write_attempt_status(
            paths["status"],
            attempt_id=attempt_id,
            opportunity_id=opportunity_id,
            status="RETRYABLE" if released else "FAILED_UNKNOWN",
            account_slot=account,
            lease=lease,
            reason_code=f"RUNNER_SPAWN_{reason}:{release}",
        )
        _write_opportunity_status(
            opportunity_status_path,
            opportunity_id=opportunity_id,
            status="RETRYABLE" if released else "ORPHAN_OWN_ATTEMPT",
            attempt_id=attempt_id,
            reason_code=f"RUNNER_SPAWN_{reason}",
        )
        return {
            "outcome": "RETRYABLE" if released else "FAILED_UNKNOWN",
            "reason_code": f"RUNNER_SPAWN_{reason}",
            "attempt_id": attempt_id,
            "new_opportunity_ids": [],
            "launched_attempt_ids": [],
            **_BOUNDARIES,
        }
    _write_once_json(
        paths["runner_spawn"],
        _runner_spawn_value(
            attempt_id=attempt_id,
            runner_pid=int(runner.pid),
            inline_test_runner=False,
            intent=launch_intent,
        ),
        conflict_code="RUNNER_SPAWN_CONFLICT",
    )
    _write_attempt_status(
        paths["status"],
        attempt_id=attempt_id,
        opportunity_id=opportunity_id,
        status="RUNNER_STARTING",
        runner_pid=int(runner.pid),
        account_slot=account,
        lease=lease,
    )
    _write_opportunity_status(
        opportunity_status_path,
        opportunity_id=opportunity_id,
        status="RUNNING",
        attempt_id=attempt_id,
        reason_code=None,
    )
    return {
        "outcome": "RUNNING",
        "attempt_id": attempt_id,
        "runner_pid": int(runner.pid),
        "new_opportunity_ids": [],
        "launched_attempt_ids": [attempt_id],
        **_BOUNDARIES,
    }


def reconcile_ongoing(
    runtime_root: Path = DEFAULT_RUNTIME_ROOT, *, popen_factory: Callable[..., Any] | None = None
) -> dict[str, Any]:
    """Perform one short durable reconciliation and at most one fresh contact."""

    runtime_root = runtime_root.resolve(strict=False)
    root = _ongoing_root(runtime_root)
    guard = _acquire_lock(root)
    if guard is None:
        return {
            "outcome": "LOCK_BUSY",
            "new_opportunity_ids": [],
            "launched_attempt_ids": [],
            **_BOUNDARIES,
        }
    try:
        current, revision = _load_current(root)
        _repair_attempt_opportunity_projections(root)
        if _contract_is_stopped(root, current):
            stopped_running = _running_attempt(root)
            if stopped_running is not None and stopped_running[1]["runner_terminal"].is_file():
                return _seal_terminal(root, str(stopped_running[0]["attempt_id"]))
            if stopped_running is not None:
                return _recover_running_attempt(
                    root,
                    stopped_running[0],
                    stopped_running[1],
                    stopped=True,
                )
            return {
                "outcome": "STOPPED",
                "revision_id": current["revision_id"],
                "new_opportunity_ids": [],
                "launched_attempt_ids": [],
                **_BOUNDARIES,
            }
        drift = _revalidate_contract_sources(revision)
        if drift:
            identity = {
                "contract_revision_id": revision["revision_id"],
                "fact_type": "CONTRACT_DRIFT",
                "drift_sources": list(drift),
            }
            fact_path = _fact_path(root, _stable_id(identity))
            if fact_path.is_file():
                fact = _read_json_object(fact_path, reason_code="FACT_INVALID")
            else:
                fact = _contract_drift_fact(revision, drift_sources=drift)
                _write_fact(root, fact)
            _projection(
                root,
                current=current,
                revision=revision,
                inventory_id=None,
                new_opportunity_ids=[],
            )
            return {
                "outcome": "CONTRACT_REBIND_REQUIRED",
                "fact_id": fact["fact_id"],
                "new_opportunity_ids": [],
                "launched_attempt_ids": [],
                **_BOUNDARIES,
            }

        running = _running_attempt(root)
        if running is not None:
            attempt_status, paths = running
            attempt_id = str(attempt_status["attempt_id"])
            if paths["runner_terminal"].is_file():
                result = _seal_terminal(root, attempt_id)
                inventory = _inventory_sources(revision["contract"])
                _projection(
                    root,
                    current=current,
                    revision=revision,
                    inventory_id=str(inventory["inventory_id"]),
                    new_opportunity_ids=[],
                )
                return result
            return _recover_running_attempt(root, attempt_status, paths, stopped=False)

        inventory = _inventory_sources(revision["contract"])
        new_ids = _materialize_external_opportunities(runtime_root, root, revision, inventory)
        due: list[tuple[str, dict[str, Any]]] = []
        future: list[tuple[str, dict[str, Any]]] = []
        for request_path in sorted((root / "opportunities").glob("*/request.json")):
            request = _read_opportunity_request(request_path)
            if request.get("contract_revision_id") != revision.get("revision_id"):
                continue
            _, status_path = _opportunity_paths(root, str(request["opportunity_id"]))
            status = _read_opportunity_status(status_path, str(request["opportunity_id"]))
            if status["status"] not in {
                "DUE",
                "NOT_BEFORE",
                "WAITING_FOR_COMPUTE",
                "RETRYABLE",
            }:
                continue
            row = (str(request["created_at"]), request)
            (due if _is_due(str(request["not_before"])) else future).append(row)
        if not due:
            for _, request in future:
                _, status_path = _opportunity_paths(root, str(request["opportunity_id"]))
                prior = _read_opportunity_status(status_path, str(request["opportunity_id"]))
                _write_opportunity_status(
                    status_path,
                    opportunity_id=str(request["opportunity_id"]),
                    status="NOT_BEFORE",
                    attempt_id=prior.get("attempt_id"),
                    reason_code="CONTRACT_MINIMUM_DELAY",
                )
            projection = _projection(
                root,
                current=current,
                revision=revision,
                inventory_id=str(inventory["inventory_id"]),
                new_opportunity_ids=new_ids,
            )
            return {
                "outcome": "WAIT",
                "new_opportunity_ids": new_ids,
                "launched_attempt_ids": [],
                "opportunity_count": projection["opportunity_count"],
                **_BOUNDARIES,
            }
        _, selected = min(due, key=lambda row: (row[0], str(row[1]["opportunity_id"])))
        result = _launch_due_opportunity(
            runtime_root,
            root,
            revision,
            inventory,
            selected,
            popen_factory=popen_factory,
        )
        projection = _projection(
            root,
            current=current,
            revision=revision,
            inventory_id=str(inventory["inventory_id"]),
            new_opportunity_ids=new_ids,
        )
        return {
            **result,
            "new_opportunity_ids": new_ids,
            "opportunity_count": projection["opportunity_count"],
        }
    finally:
        _release_byte_lock(guard)


def ongoing_status(runtime_root: Path = DEFAULT_RUNTIME_ROOT) -> dict[str, Any]:
    """Read and validate the current ongoing contract and durable object counts."""

    runtime_root = runtime_root.resolve(strict=False)
    root = _ongoing_root(runtime_root)
    current, revision = _load_current(root)
    statuses: dict[str, int] = {}
    for path in (root / "opportunities").glob("*/status.json"):
        value = _read_opportunity_status(path, path.parent.name)
        key = str(value["status"])
        statuses[key] = statuses.get(key, 0) + 1
    running = _running_attempt(root)
    return {
        "outcome": "READABLE",
        "runtime_root": str(runtime_root),
        "revision_id": current["revision_id"],
        "contract_status": "STOPPED" if _contract_is_stopped(root, current) else current["status"],
        "activation_inventory_id": revision["activation_inventory_id"],
        "fact_count": len(list((root / "facts").glob("*.json"))),
        "opportunity_count": len(list((root / "opportunities").glob("*/request.json"))),
        "attempt_count": len(list((root / "attempts").glob("*/request.json"))),
        "candidate_count": len(list((root / "candidates").glob("*.json"))),
        "opportunity_status_counts": statuses,
        "active_attempt_id": running[0]["attempt_id"] if running else None,
        "protocol_stage": PROTOCOL_STAGE,
        **_BOUNDARIES,
    }


def _terminate_pid(pid: int) -> str:
    if os.name == "nt":
        result = subprocess.run(
            [r"C:\Windows\System32\taskkill.exe", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=60,
            check=False,
        )
        return "TERMINATED" if result.returncode == 0 else f"TASKKILL_{result.returncode}"
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        return "ALREADY_DEAD"
    return "TERMINATED"


def stop_ongoing_contract(runtime_root: Path, *, expected_revision_id: str) -> dict[str, Any]:
    """CAS-stop one revision, preserving every fact, attempt, and candidate."""

    runtime_root = runtime_root.resolve(strict=False)
    root = _ongoing_root(runtime_root)
    _require_content_id(
        expected_revision_id,
        code="CONTRACT_EXPECTED_REVISION_INVALID",
        field="expected revision id",
    )
    guard = _acquire_lock(root)
    if guard is None:
        return {"outcome": "LOCK_BUSY", **_BOUNDARIES}
    try:
        current, revision = _load_current(root)
        if current["revision_id"] != expected_revision_id:
            _fail("CONTRACT_EXPECTED_REVISION_MISMATCH", "current ongoing revision changed")
        already_stopped = _contract_is_stopped(root, current)
        stop = _read_stop(root, expected_revision_id)
        if stop is None:
            stop = {
                "schema": CONTRACT_STOP_SCHEMA,
                "revision_id": expected_revision_id,
                "stopped_at": _now_iso(),
                "protocol_stage": PROTOCOL_STAGE,
                **_BOUNDARIES,
            }
            _write_once_json(
                _stop_path(root, expected_revision_id),
                stop,
                conflict_code="CONTRACT_STOP_CONFLICT",
            )
        stopped = {
            **current,
            "status": "STOPPED",
            "stopped_at": stop["stopped_at"],
        }
        atomic_write_json(root / "contracts" / "current.json", stopped)
        process_readback: list[dict[str, Any]] = []
        stop_pending = False
        running = _running_attempt(root)
        if running is not None:
            attempt_status, paths = running
            runner_pid = attempt_status.get("runner_pid")
            child_pid = attempt_status.get("child_pid")
            if paths["runner_started"].is_file():
                try:
                    started = _read_runner_started(root, str(attempt_status["attempt_id"]))
                    runner_pid = (
                        runner_pid if isinstance(runner_pid, int) else started["runner_pid"]
                    )
                    child_pid = child_pid if isinstance(child_pid, int) else started["child_pid"]
                except OngoingError as exc:
                    process_readback.append(
                        {
                            "role": "STARTED_RECEIPT",
                            "pid": None,
                            "liveness": "UNKNOWN",
                            "reason": exc.reason_code,
                        }
                    )
                    stop_pending = True
            for role, pid in (("RUNNER", runner_pid), ("MODEL_CHILD", child_pid)):
                liveness = _process_liveness(pid) if type(pid) is int else "NO_RECEIPT"
                process_readback.append({"role": role, "pid": pid, "liveness": liveness})
                if type(pid) is not int or liveness in {"ALIVE", "UNKNOWN"}:
                    stop_pending = True
            _write_attempt_status(
                paths["status"],
                attempt_id=str(attempt_status["attempt_id"]),
                opportunity_id=str(attempt_status["opportunity_id"]),
                status="STOP_REQUESTED",
                child_pid=child_pid if isinstance(child_pid, int) else None,
                runner_pid=runner_pid if isinstance(runner_pid, int) else None,
                account_slot=attempt_status.get("account_slot"),
                lease=attempt_status.get("lease"),
                reason_code="CONTRACT_STOPPED",
                started_at=attempt_status.get("started_at"),
            )
            if paths["runner_terminal"].is_file():
                try:
                    terminal = _read_runner_terminal(root, str(attempt_status["attempt_id"]))
                    if (
                        terminal.get("child_definitely_dead") is True
                        and terminal.get("release_status") == "RELEASED"
                    ):
                        stop_pending = False
                except OngoingError as exc:
                    process_readback.append(
                        {
                            "role": "TERMINAL_RECEIPT",
                            "pid": None,
                            "liveness": "UNKNOWN",
                            "reason": exc.reason_code,
                        }
                    )
                    stop_pending = True
            else:
                recovery = _recover_running_attempt(
                    root,
                    _read_attempt_status(paths["status"]),
                    paths,
                    stopped=True,
                )
                stop_pending = recovery["outcome"] != "STOPPED"
        for attempt_status_path in (root / "attempts").glob("*/status.json"):
            waiting = _read_attempt_status(attempt_status_path)
            if waiting["status"] != "WAITING_FOR_COMPUTE":
                continue
            waiting_request = _read_json_object(
                _attempt_paths(root, str(waiting["attempt_id"]))["request"],
                reason_code="ATTEMPT_REQUEST_INVALID",
            )
            if waiting_request.get("contract_revision_id") != expected_revision_id:
                continue
            if any(
                waiting.get(field) is not None
                for field in ("child_pid", "runner_pid", "account_slot", "lease")
            ):
                _fail(
                    "STOP_WAITING_ATTEMPT_OWNS_RESOURCES",
                    "WAITING_FOR_COMPUTE attempt unexpectedly owns process or quota state",
                )
            _write_attempt_status(
                attempt_status_path,
                attempt_id=str(waiting["attempt_id"]),
                opportunity_id=str(waiting["opportunity_id"]),
                status="STOPPED",
                reason_code="CONTRACT_STOPPED_BEFORE_CAPACITY",
            )
        for path in (root / "opportunities").glob("*/status.json"):
            value = _read_opportunity_status(path, path.parent.name)
            if value["status"] not in {"COMPLETED", "ORPHAN_OWN_ATTEMPT"}:
                _write_opportunity_status(
                    path,
                    opportunity_id=path.parent.name,
                    status="STOPPED",
                    attempt_id=value.get("attempt_id"),
                    reason_code="CONTRACT_STOPPED",
                )
        _projection(
            root,
            current=stopped,
            revision=revision,
            inventory_id=None,
            new_opportunity_ids=[],
        )
        return {
            "outcome": "STOP_PENDING"
            if stop_pending
            else ("ALREADY_STOPPED" if already_stopped else "STOPPED"),
            "revision_id": expected_revision_id,
            "process_readback": process_readback,
            "runner_owned_termination": True,
            "pid_only_taskkill_used": False,
            **_BOUNDARIES,
        }
    finally:
        _release_byte_lock(guard)


def _main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Internal ongoing RoR runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    runner = subparsers.add_parser("_run-attempt")
    runner.add_argument("--runtime-root", type=Path, required=True)
    runner.add_argument("--attempt-id", required=True)
    runner.add_argument("--runner-request-sha256", required=True)
    runner.add_argument("--launch-nonce", required=True)
    args = parser.parse_args(argv)
    if args.command == "_run-attempt":
        _require_content_id(args.attempt_id, code="ATTEMPT_ID_INVALID", field="attempt id")
        _require_content_id(
            args.runner_request_sha256,
            code="RUNNER_REQUEST_SHA256_INVALID",
            field="runner request SHA256",
        )
        result = _run_attempt_runner(
            args.runtime_root,
            args.attempt_id,
            expected_request_sha256=args.runner_request_sha256,
            launch_nonce=args.launch_nonce,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("outcome") in {"RECONCILED", "TERMINAL_PENDING_SEAL"} else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
