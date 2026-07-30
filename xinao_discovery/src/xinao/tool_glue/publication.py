"""Durable single-document publication for the tool-glue constitution.

The authority document is changed by one cooperative publisher at a time.  A
durable marker and journal make every pre-verification state recoverable without
turning this module into a resident control plane.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import portalocker

DEFAULT_AUTHORITY_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\工具胶水宪法\软件工具胶水宪法_当前有效.txt"
)
DEFAULT_STATE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\tool_glue_constitution_publication")
DEFAULT_GUARD_ROOT = DEFAULT_STATE_ROOT / "guards"
# Repo one-home for projection refresh; still binds Situation Island map/catalog defaults.
DEFAULT_UPDATER_PATH = (
    Path(__file__).resolve().parents[4] / "scripts" / "Update-CodexContextCatalog.ps1"
)
DEFAULT_VERIFIER_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\scripts"
    r"\Test-CodexSituationIsland.ps1"
)

JOURNAL_SCHEMA = "xinao.tool_glue_constitution_transaction.v1"
MARKER_SCHEMA = "xinao.tool_glue_constitution_marker.v1"
RESULT_SCHEMA = "xinao.tool_glue_constitution_publication_result.v1"
EXPECTED_DOCUMENT_VERSION = "v3.4"
_VERSION_PREFIX = "\u7248\u672c\uff1a"
_REFRESH_RECEIPT_SCHEMA = "xinao.mainline_projection_refresh.v1"
_SELFTEST_RECEIPT_SCHEMA = "xinao.codex_situation_island_context_architecture_verification.v4"
_CONSUMER_RECEIPT_SCHEMA = "xinao.tool_glue_constitution_consumer_readback.v1"
_SELFTEST_READY_SENTINEL = "SENTINEL:XINAO_CODEX_SITUATION_ISLAND_CONTEXT_ARCHITECTURE_READY_V4"
_MATURATION_INVARIANT_SENTINEL = "XINAO_NECESSARY_CHAIN_MATURATION_INVARIANT"

PREPARED = "PREPARED"
APPLYING = "APPLYING"
AUTHORITY_APPLIED = "AUTHORITY_APPLIED"
VERIFIED = "VERIFIED"
ROLLING_BACK = "ROLLING_BACK"
ROLLED_BACK_VERIFIED = "ROLLED_BACK_VERIFIED"

_KNOWN_STATES = {
    PREPARED,
    APPLYING,
    AUTHORITY_APPLIED,
    VERIFIED,
    ROLLING_BACK,
    ROLLED_BACK_VERIFIED,
}
_BINDING_FIELDS = ("pwsh", "updater", "verifier", "python", "consumer")

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class PublicationError(RuntimeError):
    """A fail-closed publication error with a machine-readable receipt."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        receipt: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.receipt = {
            "schema_version": RESULT_SCHEMA,
            "status": "FAILED",
            "error_code": code,
            "error": message,
            **(receipt or {}),
            "completion_claim_allowed": False,
        }


@dataclass(frozen=True)
class PublicationBindings:
    """Executable and script identities used for post-publication verification."""

    pwsh_path: Path
    updater_path: Path
    verifier_path: Path
    python_path: Path
    consumer_path: Path

    def resolved(self) -> PublicationBindings:
        return PublicationBindings(
            pwsh_path=self.pwsh_path.resolve(),
            updater_path=self.updater_path.resolve(),
            verifier_path=self.verifier_path.resolve(),
            python_path=self.python_path.resolve(),
            consumer_path=self.consumer_path.resolve(),
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def discover_pwsh() -> Path:
    """Return the current PowerShell 7 executable without relying on shell aliases."""

    discovered = shutil.which("pwsh")
    if discovered:
        return Path(discovered).resolve()

    pinned_root = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\powershell")
    pinned = sorted(pinned_root.glob("*/pwsh.exe"), reverse=True)
    if pinned:
        return pinned[0].resolve()

    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        candidate = Path(program_files) / "PowerShell" / "7" / "pwsh.exe"
        if candidate.is_file():
            return candidate.resolve()
    raise PublicationError("PWSH_NOT_FOUND", "PowerShell 7 executable was not found")


def discover_python() -> Path:
    """Return the base interpreter, never a disposable worktree virtualenv shim."""

    executable = Path(getattr(sys, "_base_executable", None) or sys.executable).resolve()
    if not executable.is_file():
        raise PublicationError(
            "PYTHON_NOT_FOUND", f"base Python executable is missing: {executable}"
        )
    return executable


def default_publication_bindings() -> PublicationBindings:
    """Discover production bindings while keeping every path injectable in tests."""

    return PublicationBindings(
        pwsh_path=discover_pwsh(),
        updater_path=DEFAULT_UPDATER_PATH,
        verifier_path=DEFAULT_VERIFIER_PATH,
        python_path=discover_python(),
        consumer_path=_repo_root() / "scripts" / "verify_tool_glue_consumer.py",
    ).resolved()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _document_version(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PublicationError("DOCUMENT_ENCODING_INVALID", "constitution must be UTF-8") from exc
    version_lines = [line.strip() for line in text.splitlines() if line.startswith(_VERSION_PREFIX)]
    if len(version_lines) != 1:
        raise PublicationError(
            "DOCUMENT_VERSION_INVALID",
            "constitution must contain exactly one version line",
        )
    version = version_lines[0].removeprefix(_VERSION_PREFIX).strip()
    if not version:
        raise PublicationError("DOCUMENT_VERSION_INVALID", "constitution version is empty")
    return version


def _normalized_sha256(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise PublicationError("INVALID_SHA256", f"{field} must be a SHA256 hex digest")
    return normalized


def _path_binding_sha256(path: Path) -> str:
    normalized = os.path.normcase(str(path.resolve()))
    return sha256_bytes(normalized.encode("utf-8"))


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PublicationError("INVALID_JSON", f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise PublicationError("INVALID_JSON", f"JSON root must be an object: {path}")
    return value


def _get_windows_file_attributes(path: Path) -> int:
    """Read the complete Windows attribute mask for one existing file."""

    attributes = getattr(path.stat(), "st_file_attributes", None)
    if attributes is None:
        raise PublicationError(
            "WINDOWS_ATTRIBUTES_UNAVAILABLE",
            f"Windows file attributes are unavailable: {path}",
        )
    return int(attributes)


def _set_windows_file_attributes(path: Path, attributes: int) -> None:
    """Restore a journaled Windows attribute mask without collapsing it to chmod."""

    if os.name != "nt":
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_attributes = kernel32.SetFileAttributesW
    set_attributes.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    set_attributes.restype = ctypes.c_int
    if not set_attributes(str(path.resolve()), attributes):
        raise ctypes.WinError(ctypes.get_last_error())


def _capture_file_metadata(path: Path) -> dict[str, int | None]:
    """Capture every replace-sensitive authority attribute before mutation."""

    current = path.stat()
    return {
        "mode": stat.S_IMODE(current.st_mode),
        "windows_file_attributes": (
            _get_windows_file_attributes(path) if os.name == "nt" else None
        ),
    }


def _validated_file_metadata(value: object) -> dict[str, int | None]:
    if not isinstance(value, dict):
        raise PublicationError("AUTHORITY_METADATA_INVALID", "authority metadata is invalid")
    mode = value.get("mode")
    windows_attributes = value.get("windows_file_attributes")
    if not isinstance(mode, int) or mode < 0 or mode > 0o7777:
        raise PublicationError("AUTHORITY_METADATA_INVALID", "authority mode is invalid")
    if windows_attributes is not None and (
        not isinstance(windows_attributes, int)
        or windows_attributes < 0
        or windows_attributes > 0xFFFFFFFF
    ):
        raise PublicationError(
            "AUTHORITY_METADATA_INVALID", "authority Windows attributes are invalid"
        )
    if os.name == "nt" and windows_attributes is None:
        raise PublicationError(
            "AUTHORITY_METADATA_INVALID", "authority Windows attributes are missing"
        )
    return {"mode": mode, "windows_file_attributes": windows_attributes}


def _apply_file_metadata(path: Path, metadata: object) -> None:
    validated = _validated_file_metadata(metadata)
    mode = validated["mode"]
    if not isinstance(mode, int):
        raise PublicationError("AUTHORITY_METADATA_INVALID", "authority mode is invalid")
    path.chmod(mode)
    windows_attributes = validated["windows_file_attributes"]
    if windows_attributes is not None:
        _set_windows_file_attributes(path, windows_attributes)


def _make_file_writable(path: Path) -> None:
    if os.name == "nt":
        attributes = _get_windows_file_attributes(path)
        if attributes & stat.FILE_ATTRIBUTE_READONLY:
            _set_windows_file_attributes(path, attributes & ~stat.FILE_ATTRIBUTE_READONLY)
        return
    current_mode = stat.S_IMODE(path.stat().st_mode)
    if not current_mode & stat.S_IWRITE:
        path.chmod(current_mode | stat.S_IWRITE)


def _assert_file_metadata(path: Path, expected: object) -> None:
    validated = _validated_file_metadata(expected)
    if _capture_file_metadata(path) != validated:
        raise PublicationError(
            "AUTHORITY_METADATA_DRIFT", "authority file metadata no longer matches the journal"
        )


def _atomic_replace_bytes(
    path: Path,
    raw: bytes,
    *,
    metadata: object | None = None,
) -> None:
    """Flush a same-directory temporary and atomically replace ``path``."""

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    prior_metadata = _capture_file_metadata(path) if path.exists() else None
    desired_metadata = (
        _validated_file_metadata(metadata) if metadata is not None else prior_metadata
    )
    target_was_made_writable = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if prior_metadata is not None:
            _make_file_writable(path)
            target_was_made_writable = True
        os.replace(temporary, path)
        if desired_metadata is not None:
            _apply_file_metadata(path, desired_metadata)
    except Exception:
        if target_was_made_writable and path.exists() and prior_metadata is not None:
            with suppress(Exception):
                _apply_file_metadata(path, prior_metadata)
        raise
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_replace_bytes(path, raw)


def _archive_path(state_root: Path, kind: str, digest: str) -> Path:
    return state_root / "archive" / kind / "sha256" / digest[:2] / f"{digest}.blob"


def _seal_archive_bytes(state_root: Path, kind: str, raw: bytes, digest: str) -> Path:
    """Create an immutable-by-identity CAS entry without replacing prior content."""

    if sha256_bytes(raw) != digest:
        raise PublicationError("ARCHIVE_INPUT_HASH_MISMATCH", f"{kind} archive input drifted")
    destination = _archive_path(state_root, kind, digest).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != digest:
            raise PublicationError("ARCHIVE_BINDING_DRIFT", f"existing {kind} archive is corrupt")
        return destination

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{digest}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        with suppress(FileExistsError):
            os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    if not destination.is_file() or sha256_file(destination) != digest:
        raise PublicationError("ARCHIVE_SEAL_FAILED", f"sealed {kind} archive failed readback")
    return destination


def _binding_snapshot(bindings: PublicationBindings) -> dict[str, dict[str, str]]:
    bindings = bindings.resolved()
    paths = {
        "pwsh": bindings.pwsh_path,
        "updater": bindings.updater_path,
        "verifier": bindings.verifier_path,
        "python": bindings.python_path,
        "consumer": bindings.consumer_path,
    }
    snapshot: dict[str, dict[str, str]] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise PublicationError("BINDING_MISSING", f"{name} binding is missing: {path}")
        snapshot[name] = {"path": str(path), "sha256": sha256_file(path)}
    return snapshot


def _validate_binding_snapshot(
    expected: object,
    bindings: PublicationBindings,
) -> PublicationBindings:
    if not isinstance(expected, dict):
        raise PublicationError("BINDING_INVALID", "journal postflight bindings are invalid")
    consumer = expected.get("consumer")
    if not isinstance(consumer, dict) or not isinstance(consumer.get("path"), str):
        raise PublicationError("BINDING_INVALID", "journal consumer binding is invalid")
    effective = PublicationBindings(
        pwsh_path=bindings.pwsh_path,
        updater_path=bindings.updater_path,
        verifier_path=bindings.verifier_path,
        python_path=bindings.python_path,
        consumer_path=Path(consumer["path"]),
    ).resolved()
    observed = _binding_snapshot(effective)
    for field in _BINDING_FIELDS:
        if expected.get(field) != observed[field]:
            raise PublicationError(
                "BINDING_DRIFT",
                f"postflight binding drifted: {field}",
            )
    return effective


def _default_command_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def _consumer_command(
    bindings: PublicationBindings,
    authority_path: Path,
    expected_sha256: str,
    expected_version: str,
    *,
    legacy_preimage_readback: bool,
) -> list[str]:
    consumer_command = [
        str(bindings.python_path),
        str(bindings.consumer_path),
        "--authority-path",
        str(authority_path),
        "--expected-sha256",
        expected_sha256,
        "--expected-version",
        expected_version,
    ]
    if legacy_preimage_readback:
        consumer_command.append("--legacy-preimage-readback")
    return consumer_command


def _postflight_commands(
    bindings: PublicationBindings,
    authority_path: Path,
    expected_sha256: str,
    expected_version: str,
    *,
    legacy_preimage_readback: bool,
) -> list[tuple[str, list[str]]]:
    powershell_prefix = [
        str(bindings.pwsh_path),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
    ]
    return [
        (
            "projection_refresh",
            [
                *powershell_prefix,
                str(bindings.updater_path),
                "-ExpectedSoftwareFoundationSha256",
                expected_sha256,
                "-ExpectedSoftwareFoundationVersion",
                expected_version,
            ],
        ),
        ("projection_selftest", [*powershell_prefix, str(bindings.verifier_path)]),
        (
            "fresh_subprocess_consumer",
            _consumer_command(
                bindings,
                authority_path,
                expected_sha256,
                expected_version,
                legacy_preimage_readback=legacy_preimage_readback,
            ),
        ),
    ]


def _parse_receipt_stdout(name: str, stdout: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout)
    except Exception as exc:
        raise PublicationError(
            "POSTFLIGHT_RECEIPT_INVALID",
            f"postflight step did not emit one JSON object: {name}",
        ) from exc
    if not isinstance(value, dict):
        raise PublicationError(
            "POSTFLIGHT_RECEIPT_INVALID",
            f"postflight step JSON root is not an object: {name}",
        )
    return value


def _validate_receipt_payload(
    *,
    name: str,
    receipt: object,
    authority_path: Path,
    expected_sha256: str,
    expected_version: str,
    legacy_preimage_readback: bool,
) -> None:
    if not isinstance(receipt, dict):
        raise PublicationError(
            "POSTFLIGHT_RECEIPT_INVALID", f"postflight receipt is not an object: {name}"
        )
    if name == "projection_refresh":
        bindings = receipt.get("projection_bindings")
        # Catalog/selector one-home must bind both version and sha from the live authority.
        valid = (
            receipt.get("schema_version") == _REFRESH_RECEIPT_SCHEMA
            and receipt.get("authority_text_mutated") is False
            and isinstance(bindings, dict)
            and str(bindings.get("software_foundation_sha256", "")).lower() == expected_sha256
            and bindings.get("software_foundation_version") == expected_version
            and isinstance(bindings.get("software_foundation_path"), str)
            and bool(str(bindings.get("software_foundation_path")).strip())
        )
    elif name == "projection_selftest":
        valid = (
            receipt.get("schema_version") == _SELFTEST_RECEIPT_SCHEMA
            and receipt.get("ready") is True
            and receipt.get("failed") == []
            and receipt.get("sentinel") == _SELFTEST_READY_SENTINEL
        )
    elif name in {
        "fresh_subprocess_candidate_preflight",
        "fresh_subprocess_consumer",
    }:
        invariant_required = not legacy_preimage_readback
        anchors = receipt.get("semantic_anchors")
        valid = (
            receipt.get("schema_version") == _CONSUMER_RECEIPT_SCHEMA
            and receipt.get("status") == VERIFIED
            and isinstance(receipt.get("authority_path"), str)
            and Path(str(receipt["authority_path"])).resolve() == authority_path.resolve()
            and receipt.get("authority_sha256") == expected_sha256
            and isinstance(receipt.get("authority_size_bytes"), int)
            and int(receipt["authority_size_bytes"]) > 0
            and receipt.get("constitution_version") == expected_version
            and receipt.get("maturation_invariant_verified") is invariant_required
            and isinstance(anchors, list)
            and (_MATURATION_INVARIANT_SENTINEL in anchors if invariant_required else anchors == [])
            and receipt.get("completion_claim_allowed") is False
        )
    else:
        valid = False
    if not valid:
        raise PublicationError(
            "POSTFLIGHT_RECEIPT_INVALID",
            f"postflight receipt fields do not bind the expected result: {name}",
        )


def _run_receipted_command(
    *,
    name: str,
    command: list[str],
    authority_path: Path,
    expected_sha256: str,
    expected_version: str,
    legacy_preimage_readback: bool,
    command_runner: CommandRunner,
    failure_code: str,
) -> dict[str, Any]:
    try:
        completed = command_runner(command)
    except Exception as exc:
        raise PublicationError(
            f"{failure_code}_EXECUTION_FAILED",
            f"receipted command raised before completion: {name}",
            receipt={"failed_step": name},
        ) from exc
    outcome: dict[str, Any] = {
        "name": name,
        "returncode": int(completed.returncode),
    }
    if completed.returncode != 0:
        with suppress(PublicationError):
            outcome["receipt"] = _parse_receipt_stdout(name, completed.stdout or "")
        outcome["stdout_tail"] = (completed.stdout or "")[-4000:]
        outcome["stderr_tail"] = (completed.stderr or "")[-4000:]
        raise PublicationError(
            failure_code,
            f"receipted command returned nonzero: {name}",
            receipt={"failed_step": name, "postflight": [outcome]},
        )
    try:
        receipt = _parse_receipt_stdout(name, completed.stdout or "")
        _validate_receipt_payload(
            name=name,
            receipt=receipt,
            authority_path=authority_path,
            expected_sha256=expected_sha256,
            expected_version=expected_version,
            legacy_preimage_readback=legacy_preimage_readback,
        )
    except PublicationError as exc:
        code = (
            "CANDIDATE_PREFLIGHT_RECEIPT_INVALID"
            if failure_code == "CANDIDATE_PREFLIGHT_FAILED"
            else exc.code
        )
        raise PublicationError(
            code,
            str(exc),
            receipt={"failed_step": name, "postflight": [outcome]},
        ) from exc
    outcome["receipt"] = receipt
    return outcome


def _run_candidate_preflight(
    *,
    bindings: PublicationBindings,
    candidate_path: Path,
    expected_sha256: str,
    expected_version: str,
    command_runner: CommandRunner,
) -> list[dict[str, Any]]:
    name = "fresh_subprocess_candidate_preflight"
    command = _consumer_command(
        bindings,
        candidate_path,
        expected_sha256,
        expected_version,
        legacy_preimage_readback=False,
    )
    outcome = _run_receipted_command(
        name=name,
        command=command,
        authority_path=candidate_path,
        expected_sha256=expected_sha256,
        expected_version=expected_version,
        legacy_preimage_readback=False,
        command_runner=command_runner,
        failure_code="CANDIDATE_PREFLIGHT_FAILED",
    )
    if sha256_file(candidate_path) != expected_sha256:
        raise PublicationError(
            "CANDIDATE_PREFLIGHT_HASH_DRIFT",
            "candidate archive drifted during semantic preflight",
        )
    return [outcome]


def _run_postflight(
    *,
    journal: dict[str, Any],
    bindings: PublicationBindings,
    authority_path: Path,
    expected_sha256: str,
    command_runner: CommandRunner,
) -> tuple[list[dict[str, Any]], str]:
    bindings = _validate_binding_snapshot(journal.get("postflight_bindings"), bindings)
    publishing_candidate = expected_sha256 == journal.get("expected_new_sha256")
    expected_version = str(
        journal.get("new_document_version")
        if publishing_candidate
        else journal.get("old_document_version")
    )
    legacy_preimage_readback = (
        not publishing_candidate and expected_version != EXPECTED_DOCUMENT_VERSION
    )
    outcomes: list[dict[str, Any]] = []
    commands = _postflight_commands(
        bindings,
        authority_path,
        expected_sha256,
        expected_version,
        legacy_preimage_readback=legacy_preimage_readback,
    )
    for name, command in commands:
        _assert_current_hash(authority_path, expected_sha256, "FINAL_AUTHORITY_HASH_MISMATCH")
        outcome = _run_receipted_command(
            name=name,
            command=command,
            authority_path=authority_path,
            expected_sha256=expected_sha256,
            expected_version=expected_version,
            legacy_preimage_readback=legacy_preimage_readback,
            command_runner=command_runner,
            failure_code="POSTFLIGHT_FAILED",
        )
        outcomes.append(outcome)
        if sha256_file(authority_path) != expected_sha256:
            raise PublicationError(
                "FINAL_AUTHORITY_HASH_MISMATCH",
                f"authority hash drifted during postflight step: {name}",
                receipt={"failed_step": name, "postflight": outcomes},
            )
    final_digest = sha256_file(authority_path)
    if final_digest != expected_sha256:
        raise PublicationError(
            "FINAL_AUTHORITY_HASH_MISMATCH",
            "final physical authority hash does not match the transaction",
            receipt={"observed_authority_sha256": final_digest, "postflight": outcomes},
        )
    return outcomes, final_digest


def _postflight_record_is_verified(
    value: object,
    *,
    authority_path: Path,
    expected_sha256: str,
    expected_version: str,
    legacy_preimage_readback: bool,
) -> bool:
    if not isinstance(value, list) or len(value) != 3:
        return False
    expected_names = [
        "projection_refresh",
        "projection_selftest",
        "fresh_subprocess_consumer",
    ]
    try:
        for item, expected_name in zip(value, expected_names, strict=True):
            if (
                not isinstance(item, dict)
                or item.get("name") != expected_name
                or item.get("returncode") != 0
            ):
                return False
            _validate_receipt_payload(
                name=expected_name,
                receipt=item.get("receipt"),
                authority_path=authority_path,
                expected_sha256=expected_sha256,
                expected_version=expected_version,
                legacy_preimage_readback=legacy_preimage_readback,
            )
    except PublicationError:
        return False
    return True


def _candidate_preflight_record_is_verified(
    value: object,
    *,
    candidate_path: Path,
    expected_sha256: str,
    expected_version: str,
) -> bool:
    if not isinstance(value, list) or len(value) != 1:
        return False
    item = value[0]
    if (
        not isinstance(item, dict)
        or item.get("name") != "fresh_subprocess_candidate_preflight"
        or item.get("returncode") != 0
    ):
        return False
    try:
        _validate_receipt_payload(
            name="fresh_subprocess_candidate_preflight",
            receipt=item.get("receipt"),
            authority_path=candidate_path,
            expected_sha256=expected_sha256,
            expected_version=expected_version,
            legacy_preimage_readback=False,
        )
    except PublicationError:
        return False
    return True


def _marker_path(state_root: Path) -> Path:
    return state_root / "active_transaction.marker.json"


def _guard_path(authority_path: Path) -> Path:
    """Return the canonical guard for one normalized authority identity."""

    return DEFAULT_GUARD_ROOT / f"{_path_binding_sha256(authority_path)}.lock"


@contextmanager
def _publication_lease(authority_path: Path) -> Iterator[None]:
    guard_path = _guard_path(authority_path).resolve()
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    lease = portalocker.Lock(
        str(guard_path),
        mode="a+b",
        timeout=0,
        flags=portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
    )
    try:
        lease.acquire()
    except portalocker.exceptions.AlreadyLocked as exc:
        raise PublicationError(
            "LEASE_HELD", "another tool-glue publication holds the lease"
        ) from exc
    try:
        yield
    finally:
        lease.release()


def _transaction_id(value: str | None) -> str:
    transaction_id = value or uuid.uuid4().hex
    if (
        not transaction_id
        or transaction_id in {".", ".."}
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in transaction_id
        )
    ):
        raise PublicationError(
            "INVALID_TRANSACTION_ID", "transaction_id contains unsafe characters"
        )
    return transaction_id


def _journal_path(state_root: Path, transaction_id: str) -> Path:
    return state_root / "transactions" / transaction_id / "transaction.v1.json"


def _marker_payload(
    authority_path: Path,
    journal_path: Path,
    journal: dict[str, Any],
) -> dict[str, Any]:
    snapshot_bytes = (
        json.dumps(journal, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return {
        "schema_version": MARKER_SCHEMA,
        "authority_path": str(authority_path.resolve()),
        "authority_binding_sha256": _path_binding_sha256(authority_path),
        "journal_path": str(journal_path.resolve()),
        "journal_snapshot": journal,
        "journal_snapshot_sha256": sha256_bytes(snapshot_bytes),
        "completion_claim_allowed": False,
    }


def _persist_journal_and_marker(
    *,
    journal: dict[str, Any],
    journal_path: Path,
    marker_path: Path,
    authority_path: Path,
) -> None:
    _write_json_atomic(journal_path, journal)
    _write_json_atomic(marker_path, _marker_payload(authority_path, journal_path, journal))


def _journal_receipt(
    journal: dict[str, Any],
    journal_path: Path,
    authority_path: Path,
) -> dict[str, Any]:
    observed_digest = sha256_file(authority_path) if authority_path.is_file() else ""
    status = str(journal["status"])
    terminal_expected = (
        str(journal["expected_new_sha256"])
        if status == VERIFIED
        else str(journal["expected_old_sha256"])
        if status == ROLLED_BACK_VERIFIED
        else None
    )
    if terminal_expected is not None and observed_digest != terminal_expected:
        raise PublicationError(
            "FINAL_AUTHORITY_HASH_MISMATCH",
            "terminal receipt cannot bind a drifted physical authority",
            receipt={"observed_authority_sha256": observed_digest},
        )
    return {
        "schema_version": RESULT_SCHEMA,
        "status": status,
        "transaction_id": str(journal["transaction_id"]),
        "authority_path": str(journal["authority_path"]),
        "authority_sha256": observed_digest if terminal_expected is not None else None,
        "authority_metadata": _capture_file_metadata(authority_path),
        "expected_old_sha256": str(journal["expected_old_sha256"]),
        "expected_new_sha256": str(journal["expected_new_sha256"]),
        "candidate_archive_path": str(journal["candidate_archive_path"]),
        "preimage_archive_path": str(journal["preimage_archive_path"]),
        "transaction_journal": str(journal_path),
        "candidate_preflight": journal.get("candidate_preflight"),
        "postflight": journal.get("postflight"),
        "postflight_final_authority_sha256": journal.get("postflight_final_authority_sha256"),
        "rollback_postflight": journal.get("rollback_postflight"),
        "rollback_postflight_final_authority_sha256": journal.get(
            "rollback_postflight_final_authority_sha256"
        ),
        "completion_claim_allowed": False,
    }


def _validate_archive_binding(
    state_root: Path,
    kind: str,
    path_value: object,
    digest: str,
) -> Path:
    path = Path(str(path_value)).resolve()
    expected_path = _archive_path(state_root, kind, digest).resolve()
    if path != expected_path:
        raise PublicationError("ARCHIVE_BINDING_DRIFT", f"{kind} archive path drifted")
    if not path.is_file() or sha256_file(path) != digest:
        raise PublicationError("ARCHIVE_BINDING_DRIFT", f"{kind} archive content drifted")
    return path


def _validate_journal(
    journal: dict[str, Any],
    *,
    journal_path: Path,
    authority_path: Path,
    state_root: Path,
) -> tuple[Path, Path]:
    if journal.get("schema_version") != JOURNAL_SCHEMA:
        raise PublicationError("JOURNAL_SCHEMA_INVALID", "transaction journal schema is invalid")
    status = str(journal.get("status"))
    if status not in _KNOWN_STATES:
        raise PublicationError("JOURNAL_STATE_INVALID", f"unsupported transaction state: {status}")
    bound_authority = Path(str(journal.get("authority_path", ""))).resolve()
    if bound_authority != authority_path.resolve():
        raise PublicationError("AUTHORITY_BINDING_DRIFT", "journal authority path does not match")
    if journal.get("authority_binding_sha256") != _path_binding_sha256(authority_path):
        raise PublicationError("AUTHORITY_BINDING_DRIFT", "journal authority identity drifted")

    transaction_id = _transaction_id(str(journal.get("transaction_id", "")))
    if journal_path.resolve() != _journal_path(state_root, transaction_id).resolve():
        raise PublicationError("JOURNAL_BINDING_DRIFT", "journal path does not match transaction")
    old_digest = _normalized_sha256(str(journal.get("expected_old_sha256", "")), "expected_old")
    new_digest = _normalized_sha256(str(journal.get("expected_new_sha256", "")), "expected_new")
    if old_digest == new_digest:
        raise PublicationError("IDENTICAL_HASHES", "old and new publication hashes must differ")
    preimage = _validate_archive_binding(
        state_root, "preimages", journal.get("preimage_archive_path"), old_digest
    )
    candidate = _validate_archive_binding(
        state_root, "candidates", journal.get("candidate_archive_path"), new_digest
    )
    old_version = str(journal.get("old_document_version", ""))
    new_version = str(journal.get("new_document_version", ""))
    if not old_version or new_version != EXPECTED_DOCUMENT_VERSION:
        raise PublicationError(
            "DOCUMENT_VERSION_INVALID",
            "journal document versions do not bind the v3.4 publication",
        )
    if _document_version(preimage.read_bytes()) != old_version:
        raise PublicationError("DOCUMENT_VERSION_DRIFT", "preimage document version drifted")
    if _document_version(candidate.read_bytes()) != new_version:
        raise PublicationError("DOCUMENT_VERSION_DRIFT", "candidate document version drifted")
    _validated_file_metadata(journal.get("authority_metadata"))
    if not _candidate_preflight_record_is_verified(
        journal.get("candidate_preflight"),
        candidate_path=candidate,
        expected_sha256=new_digest,
        expected_version=new_version,
    ):
        raise PublicationError(
            "CANDIDATE_PREFLIGHT_EVIDENCE_INVALID",
            "journal lacks a structured candidate semantic preflight receipt",
        )

    binding_record = journal.get("postflight_bindings")
    if not isinstance(binding_record, dict) or not isinstance(binding_record.get("consumer"), dict):
        raise PublicationError("BINDING_INVALID", "journal consumer binding is invalid")
    consumer_record = binding_record["consumer"]
    consumer_digest = _normalized_sha256(str(consumer_record.get("sha256", "")), "consumer_sha256")
    _validate_archive_binding(
        state_root,
        "consumers",
        consumer_record.get("path"),
        consumer_digest,
    )
    if journal.get("completion_claim_allowed") is not False:
        raise PublicationError(
            "JOURNAL_CLAIM_INVALID", "journal completion claim must remain false"
        )
    if status == VERIFIED:
        verified = _postflight_record_is_verified(
            journal.get("postflight"),
            authority_path=authority_path,
            expected_sha256=new_digest,
            expected_version=new_version,
            legacy_preimage_readback=False,
        )
        if not verified or journal.get("postflight_final_authority_sha256") != new_digest:
            raise PublicationError(
                "POSTFLIGHT_EVIDENCE_INVALID",
                "VERIFIED journal lacks complete structured postflight evidence",
            )
    if status == ROLLED_BACK_VERIFIED:
        legacy_preimage_readback = old_version != EXPECTED_DOCUMENT_VERSION
        verified = _postflight_record_is_verified(
            journal.get("rollback_postflight"),
            authority_path=authority_path,
            expected_sha256=old_digest,
            expected_version=old_version,
            legacy_preimage_readback=legacy_preimage_readback,
        )
        if not verified or journal.get("rollback_postflight_final_authority_sha256") != old_digest:
            raise PublicationError(
                "POSTFLIGHT_EVIDENCE_INVALID",
                "ROLLED_BACK_VERIFIED journal lacks structured rollback evidence",
            )
    return preimage, candidate


def _load_active_journal(
    *,
    authority_path: Path,
    state_root: Path,
) -> tuple[dict[str, Any], Path, Path, Path]:
    marker_path = _marker_path(state_root).resolve()
    marker = _read_object(marker_path)
    if marker.get("schema_version") != MARKER_SCHEMA:
        raise PublicationError("MARKER_SCHEMA_INVALID", "active marker schema is invalid")
    if marker.get("completion_claim_allowed") is not False:
        raise PublicationError("MARKER_CLAIM_INVALID", "active marker completion claim is invalid")
    if Path(str(marker.get("authority_path", ""))).resolve() != authority_path.resolve():
        raise PublicationError("AUTHORITY_BINDING_DRIFT", "marker authority path does not match")
    if marker.get("authority_binding_sha256") != _path_binding_sha256(authority_path):
        raise PublicationError("AUTHORITY_BINDING_DRIFT", "marker authority identity drifted")
    journal_path = Path(str(marker.get("journal_path", ""))).resolve()
    transactions_root = (state_root / "transactions").resolve()
    if not journal_path.is_relative_to(transactions_root):
        raise PublicationError("JOURNAL_BINDING_DRIFT", "marker journal path is invalid")
    snapshot = marker.get("journal_snapshot")
    if not isinstance(snapshot, dict):
        raise PublicationError("MARKER_SNAPSHOT_INVALID", "marker journal snapshot is missing")
    snapshot_bytes = (
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if marker.get("journal_snapshot_sha256") != sha256_bytes(snapshot_bytes):
        raise PublicationError("MARKER_SNAPSHOT_INVALID", "marker journal snapshot drifted")
    if not journal_path.is_file():
        _validate_journal(
            snapshot,
            journal_path=journal_path,
            authority_path=authority_path,
            state_root=state_root,
        )
        _write_json_atomic(journal_path, snapshot)
    journal = _read_object(journal_path)
    preimage, candidate = _validate_journal(
        journal,
        journal_path=journal_path,
        authority_path=authority_path,
        state_root=state_root,
    )
    return journal, journal_path, preimage, candidate


def _discover_orphan_journal(
    *,
    authority_path: Path,
    state_root: Path,
) -> Path | None:
    transactions_root = (state_root / "transactions").resolve()
    if not transactions_root.is_dir():
        return None
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for journal_path in sorted(transactions_root.glob("*/transaction.v1.json")):
        journal = _read_object(journal_path)
        if Path(str(journal.get("authority_path", ""))).resolve() != authority_path.resolve():
            continue
        if journal.get("authority_binding_sha256") != _path_binding_sha256(authority_path):
            raise PublicationError(
                "AUTHORITY_BINDING_DRIFT", "orphan journal authority identity drifted"
            )
        if str(journal.get("status")) not in {
            PREPARED,
            APPLYING,
            AUTHORITY_APPLIED,
            ROLLING_BACK,
        }:
            continue
        _validate_journal(
            journal,
            journal_path=journal_path,
            authority_path=authority_path,
            state_root=state_root,
        )
        candidates.append((journal_path.resolve(), journal))
    if len(candidates) > 1:
        raise PublicationError(
            "ORPHAN_JOURNAL_AMBIGUOUS",
            "multiple active journals bind the same authority without a marker",
        )
    if not candidates:
        return None
    journal_path, journal = candidates[0]
    marker_path = _marker_path(state_root).resolve()
    _write_json_atomic(marker_path, _marker_payload(authority_path, journal_path, journal))
    return marker_path


def _remove_marker(marker_path: Path) -> None:
    try:
        marker_path.unlink(missing_ok=True)
    except OSError as exc:
        raise PublicationError(
            "MARKER_CLEANUP_FAILED",
            f"could not remove terminal transaction marker: {marker_path}",
        ) from exc


def _assert_current_hash(authority_path: Path, expected: str, code: str) -> None:
    if not authority_path.is_file() or sha256_file(authority_path) != expected:
        raise PublicationError(code, f"authority target does not match required hash: {expected}")


def _rollback_locked(
    *,
    journal: dict[str, Any],
    journal_path: Path,
    preimage_path: Path,
    authority_path: Path,
    marker_path: Path,
    bindings: PublicationBindings,
    command_runner: CommandRunner,
    require_current_new: bool,
) -> dict[str, Any]:
    old_digest = str(journal["expected_old_sha256"])
    new_digest = str(journal["expected_new_sha256"])
    current_digest = sha256_file(authority_path) if authority_path.is_file() else ""
    if require_current_new and current_digest != new_digest:
        raise PublicationError(
            "ROLLBACK_TARGET_NOT_NEW",
            "explicit rollback is allowed only while the authority equals the published hash",
            receipt={"observed_authority_sha256": current_digest},
        )
    if current_digest not in {old_digest, new_digest}:
        raise PublicationError(
            "AUTHORITY_TARGET_DRIFT",
            "authority target matches neither transaction preimage nor candidate",
            receipt={"observed_authority_sha256": current_digest},
        )

    journal["status"] = ROLLING_BACK
    journal["completion_claim_allowed"] = False
    _persist_journal_and_marker(
        journal=journal,
        journal_path=journal_path,
        marker_path=marker_path,
        authority_path=authority_path,
    )
    authority_metadata = _validated_file_metadata(journal.get("authority_metadata"))
    if current_digest == new_digest:
        _atomic_replace_bytes(
            authority_path,
            preimage_path.read_bytes(),
            metadata=authority_metadata,
        )
    _assert_current_hash(authority_path, old_digest, "ROLLBACK_WRITE_FAILED")
    _apply_file_metadata(authority_path, authority_metadata)
    _assert_file_metadata(authority_path, authority_metadata)
    effective_bindings = _validate_binding_snapshot(journal.get("postflight_bindings"), bindings)
    rollback_postflight, final_digest = _run_postflight(
        journal=journal,
        bindings=effective_bindings,
        authority_path=authority_path,
        expected_sha256=old_digest,
        command_runner=command_runner,
    )
    journal["rollback_postflight"] = rollback_postflight
    journal["rollback_postflight_final_authority_sha256"] = final_digest
    journal["status"] = ROLLED_BACK_VERIFIED
    _persist_journal_and_marker(
        journal=journal,
        journal_path=journal_path,
        marker_path=marker_path,
        authority_path=authority_path,
    )
    receipt = _journal_receipt(journal, journal_path, authority_path)
    _remove_marker(marker_path)
    return receipt


def _recover_locked(
    *,
    authority_path: Path,
    state_root: Path,
    bindings: PublicationBindings,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    marker_path = _marker_path(state_root).resolve()
    if not marker_path.is_file():
        discovered = _discover_orphan_journal(
            authority_path=authority_path,
            state_root=state_root,
        )
        if discovered is None:
            return {
                "schema_version": RESULT_SCHEMA,
                "status": "NO_INTERRUPTED_TRANSACTION",
                "authority_path": str(authority_path),
                "completion_claim_allowed": False,
            }

    journal, journal_path, preimage, _candidate = _load_active_journal(
        authority_path=authority_path,
        state_root=state_root,
    )
    status = str(journal["status"])
    old_digest = str(journal["expected_old_sha256"])
    new_digest = str(journal["expected_new_sha256"])
    current_digest = sha256_file(authority_path) if authority_path.is_file() else ""

    if status in {PREPARED, APPLYING, ROLLING_BACK}:
        return _rollback_locked(
            journal=journal,
            journal_path=journal_path,
            preimage_path=preimage,
            authority_path=authority_path,
            marker_path=marker_path,
            bindings=bindings,
            command_runner=command_runner,
            require_current_new=False,
        )
    if status == AUTHORITY_APPLIED:
        if current_digest != new_digest:
            raise PublicationError(
                "AUTHORITY_TARGET_DRIFT",
                "AUTHORITY_APPLIED recovery requires the exact candidate postimage",
                receipt={"observed_authority_sha256": current_digest},
            )
        _assert_file_metadata(authority_path, journal.get("authority_metadata"))
        effective_bindings = _validate_binding_snapshot(
            journal.get("postflight_bindings"), bindings
        )
        postflight, final_digest = _run_postflight(
            journal=journal,
            bindings=effective_bindings,
            authority_path=authority_path,
            expected_sha256=new_digest,
            command_runner=command_runner,
        )
        journal["postflight"] = postflight
        journal["postflight_final_authority_sha256"] = final_digest
        journal["status"] = VERIFIED
        _persist_journal_and_marker(
            journal=journal,
            journal_path=journal_path,
            marker_path=marker_path,
            authority_path=authority_path,
        )
        receipt = _journal_receipt(journal, journal_path, authority_path)
        _remove_marker(marker_path)
        return receipt
    if status == VERIFIED:
        if current_digest != new_digest:
            raise PublicationError("AUTHORITY_TARGET_DRIFT", "VERIFIED target hash drifted")
        _assert_file_metadata(authority_path, journal.get("authority_metadata"))
        receipt = _journal_receipt(journal, journal_path, authority_path)
        _remove_marker(marker_path)
        return receipt
    if status == ROLLED_BACK_VERIFIED:
        if current_digest != old_digest:
            raise PublicationError("AUTHORITY_TARGET_DRIFT", "rolled-back target hash drifted")
        _assert_file_metadata(authority_path, journal.get("authority_metadata"))
        receipt = _journal_receipt(journal, journal_path, authority_path)
        _remove_marker(marker_path)
        return receipt
    raise PublicationError("JOURNAL_STATE_INVALID", f"cannot recover transaction state: {status}")


def recover_tool_glue_constitution(
    *,
    authority_path: Path = DEFAULT_AUTHORITY_PATH,
    state_root: Path = DEFAULT_STATE_ROOT,
    bindings: PublicationBindings | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Recover one durable transaction according to its persisted state."""

    authority_path = authority_path.resolve()
    state_root = state_root.resolve()
    bindings = (bindings or default_publication_bindings()).resolved()
    runner = command_runner or _default_command_runner
    with _publication_lease(authority_path):
        return _recover_locked(
            authority_path=authority_path,
            state_root=state_root,
            bindings=bindings,
            command_runner=runner,
        )


def publish_tool_glue_constitution(
    *,
    candidate_path: Path,
    expected_old_sha256: str,
    expected_new_sha256: str,
    authority_path: Path = DEFAULT_AUTHORITY_PATH,
    state_root: Path = DEFAULT_STATE_ROOT,
    bindings: PublicationBindings | None = None,
    command_runner: CommandRunner | None = None,
    transaction_id: str | None = None,
) -> dict[str, Any]:
    """CAS-publish one candidate and verify every real consumer before success."""

    authority_path = authority_path.resolve()
    candidate_path = candidate_path.resolve()
    state_root = state_root.resolve()
    bindings = (bindings or default_publication_bindings()).resolved()
    runner = command_runner or _default_command_runner
    old_digest = _normalized_sha256(expected_old_sha256, "expected_old_sha256")
    new_digest = _normalized_sha256(expected_new_sha256, "expected_new_sha256")
    if old_digest == new_digest:
        raise PublicationError("IDENTICAL_HASHES", "old and new publication hashes must differ")
    if authority_path == candidate_path:
        raise PublicationError(
            "CANDIDATE_IS_AUTHORITY", "candidate must not be the live authority path"
        )
    if not authority_path.is_file():
        raise PublicationError(
            "AUTHORITY_MISSING", f"authority document is missing: {authority_path}"
        )
    if not candidate_path.is_file():
        raise PublicationError(
            "CANDIDATE_MISSING", f"candidate document is missing: {candidate_path}"
        )
    _assert_current_hash(authority_path, old_digest, "EXPECTED_OLD_MISMATCH")
    _assert_current_hash(candidate_path, new_digest, "EXPECTED_NEW_MISMATCH")

    with _publication_lease(authority_path):
        marker_path = _marker_path(state_root).resolve()
        recovered = _recover_locked(
            authority_path=authority_path,
            state_root=state_root,
            bindings=bindings,
            command_runner=runner,
        )
        if recovered["status"] != "NO_INTERRUPTED_TRANSACTION":
            raise PublicationError(
                "RECOVERED_TRANSACTION_RETRY_REQUIRED",
                "an interrupted transaction was recovered; retry with fresh expected hashes",
                receipt={"recovery": recovered},
            )

        # Both preconditions are repeated after acquiring the exclusive lease.
        _assert_current_hash(authority_path, old_digest, "EXPECTED_OLD_MISMATCH_AFTER_LOCK")
        _assert_current_hash(candidate_path, new_digest, "EXPECTED_NEW_MISMATCH_AFTER_LOCK")
        candidate_bytes = candidate_path.read_bytes()
        if sha256_bytes(candidate_bytes) != new_digest:
            raise PublicationError(
                "EXPECTED_NEW_MISMATCH_AFTER_LOCK",
                "candidate changed while sealing the post-lock snapshot",
            )
        preimage_bytes = authority_path.read_bytes()
        if sha256_bytes(preimage_bytes) != old_digest:
            raise PublicationError(
                "EXPECTED_OLD_MISMATCH_AFTER_LOCK",
                "authority changed while sealing the post-lock preimage",
            )
        authority_metadata = _capture_file_metadata(authority_path)
        old_document_version = _document_version(preimage_bytes)
        new_document_version = _document_version(candidate_bytes)
        if new_document_version != EXPECTED_DOCUMENT_VERSION:
            raise PublicationError(
                "DOCUMENT_VERSION_INVALID",
                f"candidate must declare {EXPECTED_DOCUMENT_VERSION}",
            )
        candidate_archive = _seal_archive_bytes(
            state_root, "candidates", candidate_bytes, new_digest
        )
        preimage_archive = _seal_archive_bytes(state_root, "preimages", preimage_bytes, old_digest)
        if not bindings.consumer_path.is_file():
            raise PublicationError(
                "BINDING_MISSING",
                f"consumer binding is missing: {bindings.consumer_path}",
            )
        consumer_bytes = bindings.consumer_path.read_bytes()
        consumer_digest = sha256_bytes(consumer_bytes)
        durable_consumer = _seal_archive_bytes(
            state_root,
            "consumers",
            consumer_bytes,
            consumer_digest,
        )
        effective_bindings = PublicationBindings(
            pwsh_path=bindings.pwsh_path,
            updater_path=bindings.updater_path,
            verifier_path=bindings.verifier_path,
            python_path=bindings.python_path,
            consumer_path=durable_consumer,
        ).resolved()
        bindings_snapshot = _binding_snapshot(effective_bindings)
        candidate_preflight = _run_candidate_preflight(
            bindings=effective_bindings,
            candidate_path=candidate_archive,
            expected_sha256=new_digest,
            expected_version=new_document_version,
            command_runner=runner,
        )
        txid = _transaction_id(transaction_id)
        journal_path = _journal_path(state_root, txid).resolve()
        if journal_path.exists():
            raise PublicationError("TRANSACTION_EXISTS", f"transaction already exists: {txid}")
        journal: dict[str, Any] = {
            "schema_version": JOURNAL_SCHEMA,
            "transaction_id": txid,
            "status": PREPARED,
            "authority_path": str(authority_path),
            "authority_binding_sha256": _path_binding_sha256(authority_path),
            "expected_old_sha256": old_digest,
            "expected_new_sha256": new_digest,
            "old_document_version": old_document_version,
            "new_document_version": new_document_version,
            "candidate_source_path": str(candidate_path),
            "candidate_archive_path": str(candidate_archive),
            "preimage_archive_path": str(preimage_archive),
            "postflight_bindings": bindings_snapshot,
            "authority_metadata": authority_metadata,
            "candidate_preflight": candidate_preflight,
            "completion_claim_allowed": False,
        }

        try:
            _persist_journal_and_marker(
                journal=journal,
                journal_path=journal_path,
                marker_path=marker_path,
                authority_path=authority_path,
            )
            journal["status"] = APPLYING
            _persist_journal_and_marker(
                journal=journal,
                journal_path=journal_path,
                marker_path=marker_path,
                authority_path=authority_path,
            )
            _assert_current_hash(authority_path, old_digest, "EXPECTED_OLD_MISMATCH_BEFORE_REPLACE")
            if sha256_file(candidate_archive) != new_digest:
                raise PublicationError("ARCHIVE_BINDING_DRIFT", "candidate archive drifted")
            _atomic_replace_bytes(
                authority_path,
                candidate_archive.read_bytes(),
                metadata=authority_metadata,
            )
            _assert_current_hash(authority_path, new_digest, "AUTHORITY_REPLACE_FAILED")
            _assert_file_metadata(authority_path, authority_metadata)
            journal["status"] = AUTHORITY_APPLIED
            _persist_journal_and_marker(
                journal=journal,
                journal_path=journal_path,
                marker_path=marker_path,
                authority_path=authority_path,
            )
            postflight, final_digest = _run_postflight(
                journal=journal,
                bindings=effective_bindings,
                authority_path=authority_path,
                expected_sha256=new_digest,
                command_runner=runner,
            )
            journal["postflight"] = postflight
            journal["postflight_final_authority_sha256"] = final_digest
            journal["status"] = VERIFIED
            _persist_journal_and_marker(
                journal=journal,
                journal_path=journal_path,
                marker_path=marker_path,
                authority_path=authority_path,
            )
            receipt = _journal_receipt(journal, journal_path, authority_path)
            _remove_marker(marker_path)
            return receipt
        except Exception as primary:
            failure = (
                primary
                if isinstance(primary, PublicationError)
                else PublicationError("PUBLICATION_FAILED", str(primary))
            )
            if marker_path.is_file() or journal_path.is_file():
                try:
                    recovery = _recover_locked(
                        authority_path=authority_path,
                        state_root=state_root,
                        bindings=effective_bindings,
                        command_runner=runner,
                    )
                except Exception as recovery_error:
                    raise PublicationError(
                        failure.code,
                        str(failure),
                        receipt={
                            **failure.receipt,
                            "recovery_status": "FAILED",
                            "recovery_error": str(recovery_error),
                            "transaction_journal": str(journal_path),
                            "completion_claim_allowed": False,
                        },
                    ) from primary
                if recovery["status"] == VERIFIED:
                    return {
                        **recovery,
                        "recovered_from_error_code": failure.code,
                    }
                raise PublicationError(
                    failure.code,
                    str(failure),
                    receipt={
                        **failure.receipt,
                        "recovery": recovery,
                        "transaction_journal": str(journal_path),
                        "completion_claim_allowed": False,
                    },
                ) from primary
            raise failure from primary


def rollback_tool_glue_constitution(
    *,
    journal_path: Path,
    authority_path: Path = DEFAULT_AUTHORITY_PATH,
    state_root: Path = DEFAULT_STATE_ROOT,
    bindings: PublicationBindings | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Explicitly roll back a verified publication only from its exact postimage."""

    authority_path = authority_path.resolve()
    state_root = state_root.resolve()
    journal_path = journal_path.resolve()
    bindings = (bindings or default_publication_bindings()).resolved()
    runner = command_runner or _default_command_runner
    with _publication_lease(authority_path):
        marker_path = _marker_path(state_root).resolve()
        if marker_path.exists():
            raise PublicationError(
                "ACTIVE_TRANSACTION_EXISTS",
                "recover the active transaction before requesting explicit rollback",
            )
        journal = _read_object(journal_path)
        preimage, _candidate = _validate_journal(
            journal,
            journal_path=journal_path,
            authority_path=authority_path,
            state_root=state_root,
        )
        if journal.get("status") != VERIFIED:
            raise PublicationError(
                "ROLLBACK_STATE_INVALID",
                "explicit rollback requires a VERIFIED transaction journal",
            )
        _assert_current_hash(
            authority_path,
            str(journal["expected_new_sha256"]),
            "ROLLBACK_TARGET_NOT_NEW",
        )
        _write_json_atomic(
            marker_path,
            _marker_payload(authority_path, journal_path, journal),
        )
        return _rollback_locked(
            journal=journal,
            journal_path=journal_path,
            preimage_path=preimage,
            authority_path=authority_path,
            marker_path=marker_path,
            bindings=bindings,
            command_runner=runner,
            require_current_new=True,
        )


__all__ = [
    "APPLYING",
    "AUTHORITY_APPLIED",
    "DEFAULT_AUTHORITY_PATH",
    "DEFAULT_GUARD_ROOT",
    "DEFAULT_STATE_ROOT",
    "DEFAULT_UPDATER_PATH",
    "DEFAULT_VERIFIER_PATH",
    "JOURNAL_SCHEMA",
    "MARKER_SCHEMA",
    "PREPARED",
    "ROLLED_BACK_VERIFIED",
    "ROLLING_BACK",
    "VERIFIED",
    "PublicationBindings",
    "PublicationError",
    "default_publication_bindings",
    "discover_pwsh",
    "discover_python",
    "publish_tool_glue_constitution",
    "recover_tool_glue_constitution",
    "rollback_tool_glue_constitution",
    "sha256_bytes",
    "sha256_file",
]
