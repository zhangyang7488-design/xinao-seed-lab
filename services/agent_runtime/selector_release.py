"""Build and atomically promote an immutable supervisor-selector release.

Runtime launchers consume one hash-bound ``current.json`` pointer.  Task CWDs,
worktree scans, and dated repository paths are intentionally not resolver
inputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

RELEASE_SCHEMA = "xinao.selector_release.v2"
LEGACY_V1_RELEASE_SCHEMA = "xinao.selector_release.v1"
POINTER_SCHEMA = "xinao.selector_release_pointer.v1"
SOURCE_CAPTURE_SCHEMA = "xinao.selector_release_source_capture.v1"
EXECUTION_BINDING_SCHEMA = "xinao.selector_release_execution_binding.v1"
LEGACY_V1_MIGRATION_SCHEMA = "xinao.selector_release_legacy_v1_migration.v1"
CURRENT_STATE_ABSENT = "ABSENT"
CURRENT_STATE_PRESENT = "PRESENT"
CURRENT_STATE_LEGACY_V1_PRESENT = "LEGACY_V1_PRESENT"
REQUIRED_DISTRIBUTIONS = (
    "attrs",
    "jsonschema",
    "jsonschema-specifications",
    "portalocker",
    "referencing",
    "rpds-py",
    "typing-extensions",
    *(("pywin32",) if os.name == "nt" else ()),
)

RELEASE_FILES = (
    "services/__init__.py",
    "services/agent_runtime/__init__.py",
    "services/agent_runtime/routing_policy_reader.py",
    "services/agent_runtime/supervisor_worker_selector.py",
    "services/agent_runtime/provider_routing_preference.py",
    "services/agent_runtime/quota_capacity_adapter.py",
    "services/agent_runtime/carrier_identity.py",
    "services/agent_runtime/thin_glue_stack.py",
    "services/agent_runtime/direct_worker_pool_common_adapter.py",
    "services/agent_runtime/execution_contract.py",
    "services/agent_runtime/work_unit_lifecycle.py",
    "services/agent_runtime/action_resume_receipt.py",
    "services/agent_runtime/grok_execution_contract_adapter.py",
    "services/agent_runtime/context_slice_manifest.py",
    "services/agent_runtime/audit_adjudication.py",
    "services/agent_runtime/dispatch_economics.py",
    "services/agent_runtime/quota_dispatch_epoch.py",
    "services/agent_runtime/schemas/audit_adjudication.v1.schema.json",
    "services/agent_runtime/schemas/audit_assessment.v1.schema.json",
    "services/agent_runtime/schemas/audit_candidate_findings.v1.schema.json",
    "services/agent_runtime/schemas/execution_attempt_receipt.v1.schema.json",
    "services/agent_runtime/schemas/execution_logical_contract.v1.schema.json",
    "scripts/prepare_direct_worker_pool_common_contract.py",
    "scripts/validate_worker_package_batch.py",
    "scripts/quota_dispatch_epoch.py",
    "scripts/record_dispatch_outcome.py",
    "scripts/record_audit_adjudication.py",
    "scripts/project_dispatch_outcomes.py",
    "scripts/build_worker_package_batch.py",
)
SOURCE_CAPTURE_FILES = (*RELEASE_FILES, "uv.lock")
LEGACY_V1_POINTER_FIELDS = frozenset(
    {
        "schema_version",
        "release_id",
        "release_root",
        "release_manifest_ref",
        "release_manifest_sha256",
    }
)
LEGACY_V1_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "release_id",
        "release_root",
        "source_root",
        "source_git_head",
        "source_capture",
        "files",
        "selector_source_sha256",
        "python_executable",
        "probe",
        "authority",
        "completion_claim_allowed",
        "release_content_sha256",
    }
)


class SelectorReleaseError(ValueError):
    """Raised when a selector release or pointer fails identity validation."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SelectorReleaseError(f"{label} must be non-empty")
    return text


def _sha(value: object, label: str) -> str:
    text = _text(value, label).lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise SelectorReleaseError(f"{label} must be sha256")
    return text


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _atomic_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _json_bytes(payload)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return _sha_bytes(raw)


class _SelectorReleaseLock:
    """Serialize only the shared selector pointer commit boundary."""

    def __init__(self, directory: Path, timeout_sec: float = 30.0) -> None:
        self.path = directory / ".promotion.lock"
        self.timeout_sec = timeout_sec
        self._lock: object | None = None

    def __enter__(self) -> "_SelectorReleaseLock":
        # Pointer validation is intentionally standard-library-only so an
        # installed consumer can run the immutable validator carrier with
        # ``python -I -S -B``.  Promotion alone needs the third-party lock.
        try:
            import portalocker
        except ImportError as exc:
            raise SelectorReleaseError("selector release promotion requires portalocker") from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = portalocker.Lock(
            str(self.path),
            mode="a+",
            timeout=self.timeout_sec,
            check_interval=0.05,
            flags=portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
        )
        try:
            stream = lock.acquire()
        except portalocker.exceptions.LockException as exc:
            raise SelectorReleaseError(
                f"selector release promotion lock timeout: {self.path}"
            ) from exc
        try:
            stream.seek(0)
            stream.truncate()
            stream.write(f"pid={os.getpid()}\n")
            stream.flush()
            os.fsync(stream.fileno())
        except Exception:
            lock.release()
            raise
        self._lock = lock
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        lock = self._lock
        self._lock = None
        if lock is not None:
            release = getattr(lock, "release", None)
            if callable(release):
                release()


def _decode_object(raw: bytes, *, path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SelectorReleaseError(f"{label} invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SelectorReleaseError(f"{label} must be an object: {path}")
    return value


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise SelectorReleaseError(f"{label} missing: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SelectorReleaseError(f"{label} unreadable: {path}: {exc}") from exc
    return _decode_object(raw, path=path, label=label)


def _lexical_absolute(path: Path) -> Path:
    """Return an absolute path without following a symlink or junction."""

    return Path(os.path.abspath(os.fspath(path)))


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(_lexical_absolute(path))))


def _assert_no_reparse_existing_path(path: Path, *, label: str) -> Path:
    """Reject every pre-existing symlink/reparse component before legacy reads."""

    absolute = _lexical_absolute(path)
    anchor = Path(absolute.anchor)
    current = anchor
    final_stat: os.stat_result | None = None
    for component in absolute.parts[1:]:
        current /= component
        try:
            final_stat = current.lstat()
        except OSError as exc:
            raise SelectorReleaseError(f"{label} missing or unreadable: {current}: {exc}") from exc
        attributes = int(getattr(final_stat, "st_file_attributes", 0))
        reparse_attribute = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        if stat.S_ISLNK(final_stat.st_mode) or attributes & reparse_attribute:
            raise SelectorReleaseError(f"{label} reparse component rejected: {current}")
    if final_stat is None:
        raise SelectorReleaseError(f"{label} must not be a volume root: {absolute}")
    return absolute


def _declared_legacy_path(value: object, label: str) -> Path:
    text = _text(value, label)
    raw = Path(text)
    if not raw.is_absolute():
        raise SelectorReleaseError(f"{label} must be absolute")
    segments = text.replace("\\", "/").split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise SelectorReleaseError(f"{label} must not contain dot path segments")
    return _lexical_absolute(raw)


def _legacy_release_identifier(value: object) -> str:
    identifier = _text(value, "pointer.release_id")
    if (
        any(char in identifier for char in '\\/:*?"<>|')
        or identifier in {".", ".."}
        or Path(identifier).name != identifier
    ):
        raise SelectorReleaseError("legacy v1 release_id is not a safe path segment")
    return identifier


def _legacy_runtime_paths(runtime_root: Path) -> tuple[Path, Path]:
    state = _lexical_absolute(runtime_root) / "state" / "grok_supervisor_selector"
    return state / "releases", state / "current.json"


def _read_stable_bytes(path: Path, *, label: str) -> bytes:
    try:
        before = path.read_bytes()
        after = path.read_bytes()
    except OSError as exc:
        raise SelectorReleaseError(f"{label} unreadable: {path}: {exc}") from exc
    if before != after:
        raise SelectorReleaseError(f"{label} changed during observation: {path}")
    return before


def _legacy_v1_static_file_bindings(
    manifest: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise SelectorReleaseError("legacy v1 release file list missing")
    observed: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict) or set(raw) != {"path", "sha256", "size_bytes"}:
            raise SelectorReleaseError(f"legacy v1 release file entry invalid: {index}")
        relative_text = _text(raw.get("path"), f"legacy files[{index}].path")
        relative = Path(relative_text)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != relative_text
            or relative_text in observed
        ):
            raise SelectorReleaseError(f"legacy v1 release file path invalid: {relative_text}")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise SelectorReleaseError(f"legacy files[{index}].size_bytes must be >= 0")
        observed[relative_text] = {
            "sha256": _sha(raw.get("sha256"), f"legacy files[{index}].sha256"),
            "size_bytes": size,
        }
    if tuple(observed) != RELEASE_FILES:
        raise SelectorReleaseError("legacy v1 release file closure mismatch")
    return observed


def _legacy_v1_pointer_identity(runtime_root: Path) -> dict[str, str]:
    """Statically bind the exact legacy pointer+manifest without executing legacy code."""

    runtime = _lexical_absolute(runtime_root)
    releases, pointer_path = _legacy_runtime_paths(runtime)
    _assert_no_reparse_existing_path(pointer_path, label="legacy v1 current pointer")
    pointer_raw = _read_stable_bytes(pointer_path, label="legacy v1 current pointer")
    pointer = _decode_object(
        pointer_raw,
        path=pointer_path,
        label="legacy v1 current pointer",
    )
    if set(pointer) != LEGACY_V1_POINTER_FIELDS:
        raise SelectorReleaseError("legacy v1 current pointer field set mismatch")
    if pointer.get("schema_version") != POINTER_SCHEMA:
        raise SelectorReleaseError("legacy v1 current pointer schema mismatch")
    release_id = _legacy_release_identifier(pointer.get("release_id"))
    expected_release_root = releases / release_id
    release_root = _declared_legacy_path(pointer.get("release_root"), "pointer.release_root")
    if release_root.name != release_id or _path_key(release_root) != _path_key(
        expected_release_root
    ):
        raise SelectorReleaseError("legacy v1 release root is not the exact runtime release")
    manifest_path = _declared_legacy_path(
        pointer.get("release_manifest_ref"), "pointer.release_manifest_ref"
    )
    expected_manifest_path = expected_release_root / "release_manifest.json"
    if _path_key(manifest_path) != _path_key(expected_manifest_path):
        raise SelectorReleaseError("legacy v1 manifest is not the exact runtime release manifest")
    _assert_no_reparse_existing_path(manifest_path, label="legacy v1 release manifest")
    manifest_raw = _read_stable_bytes(manifest_path, label="legacy v1 release manifest")
    expected_manifest_sha = _sha(
        pointer.get("release_manifest_sha256"), "pointer.release_manifest_sha256"
    )
    if _sha_bytes(manifest_raw) != expected_manifest_sha:
        raise SelectorReleaseError("legacy v1 release manifest hash mismatch")
    manifest = _decode_object(
        manifest_raw,
        path=manifest_path,
        label="legacy v1 release manifest",
    )
    if set(manifest) != LEGACY_V1_MANIFEST_FIELDS:
        raise SelectorReleaseError("legacy v1 release manifest field set mismatch")
    if manifest.get("schema_version") != LEGACY_V1_RELEASE_SCHEMA:
        raise SelectorReleaseError("current release is not the expected legacy v1 schema")
    if manifest.get("release_id") != release_id:
        raise SelectorReleaseError("legacy v1 release id mismatch")
    declared_manifest_root = _declared_legacy_path(
        manifest.get("release_root"), "manifest.release_root"
    )
    if _path_key(declared_manifest_root) != _path_key(expected_release_root):
        raise SelectorReleaseError("legacy v1 manifest release root mismatch")
    content = dict(manifest)
    expected_content_sha = _sha(
        content.pop("release_content_sha256", None), "release_content_sha256"
    )
    if _sha_bytes(_canonical_bytes(content)) != expected_content_sha:
        raise SelectorReleaseError("legacy v1 release content hash mismatch")
    observed_files = _legacy_v1_static_file_bindings(manifest)
    if manifest.get("source_capture") is None:
        raise SelectorReleaseError("legacy v1 source capture missing")
    _validate_source_capture(manifest, observed_files)
    selector_sha = _sha(manifest.get("selector_source_sha256"), "legacy selector_source_sha256")
    selector_relative = "services/agent_runtime/routing_policy_reader.py"
    if observed_files[selector_relative]["sha256"] != selector_sha:
        raise SelectorReleaseError("legacy v1 selector source declaration mismatch")
    python_executable = _text(manifest.get("python_executable"), "legacy python_executable")
    probe = manifest.get("probe")
    if not isinstance(probe, dict):
        raise SelectorReleaseError("legacy v1 probe declaration missing")
    if probe.get("python_executable") != python_executable:
        raise SelectorReleaseError("legacy v1 probe interpreter declaration mismatch")
    if probe.get("selector_source_sha256") != selector_sha:
        raise SelectorReleaseError("legacy v1 probe selector declaration mismatch")
    if (
        manifest.get("authority") is not False
        or manifest.get("completion_claim_allowed") is not False
    ):
        raise SelectorReleaseError("legacy v1 authority declaration mismatch")
    if _read_stable_bytes(manifest_path, label="legacy v1 release manifest") != manifest_raw:
        raise SelectorReleaseError("legacy v1 release manifest changed during observation")
    if _read_stable_bytes(pointer_path, label="legacy v1 current pointer") != pointer_raw:
        raise SelectorReleaseError("legacy v1 current pointer changed during observation")
    return {
        "state": CURRENT_STATE_LEGACY_V1_PRESENT,
        "release_id": release_id,
        "pointer_sha256": _sha_bytes(pointer_raw),
        "release_manifest_sha256": expected_manifest_sha,
    }


def selector_release_legacy_v1_migration_identity(runtime_root: Path) -> dict[str, str]:
    """Return a one-shot CAS identity only for the exact current legacy v1 release."""

    return _legacy_v1_pointer_identity(runtime_root)


def _capture_selected_sources(source_root: Path) -> dict[str, dict[str, object]]:
    """Read the exact selected closure once; callers must verify it again later."""

    captured: dict[str, dict[str, object]] = {}
    for relative_text in SOURCE_CAPTURE_FILES:
        relative = Path(relative_text)
        origin = source_root / relative
        try:
            resolved = origin.resolve(strict=True)
        except OSError as exc:
            raise SelectorReleaseError(f"selector release source missing: {relative_text}") from exc
        if not origin.is_file() or not _under(resolved, source_root):
            raise SelectorReleaseError(f"selector release source missing: {relative_text}")
        try:
            raw = origin.read_bytes()
        except OSError as exc:
            raise SelectorReleaseError(
                f"selector release source unreadable: {relative_text}: {exc}"
            ) from exc
        captured[relative.as_posix()] = {
            "path": relative.as_posix(),
            "sha256": _sha_bytes(raw),
            "size_bytes": len(raw),
            "raw": raw,
        }
    return captured


def _source_capture_manifest(
    captured: Mapping[str, Mapping[str, object]], *, source_git_head: str | None
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": SOURCE_CAPTURE_SCHEMA,
        "method": "selected_source_double_read",
        "source_git_head": source_git_head,
        "files": [
            {
                "path": relative_text,
                "sha256": captured[relative_text]["sha256"],
                "size_bytes": captured[relative_text]["size_bytes"],
            }
            for relative_text in SOURCE_CAPTURE_FILES
        ],
    }
    return {**body, "source_capture_sha256": _sha_bytes(_canonical_bytes(body))}


def _same_source_capture(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
) -> bool:
    if before.keys() != after.keys():
        return False
    return all(
        before[path].get("raw") == after[path].get("raw")
        and before[path].get("size_bytes") == after[path].get("size_bytes")
        for path in before
    )


def _validate_source_capture(
    manifest: Mapping[str, object],
    release_files: Mapping[str, Mapping[str, object]],
) -> None:
    raw_capture = manifest.get("source_capture")
    if raw_capture is None:
        # Legacy v1 releases predate coherent producer capture.  New builds
        # always carry the stronger contract, while old live pointers remain readable.
        return
    if not isinstance(raw_capture, dict):
        raise SelectorReleaseError("selector release source capture must be an object")
    capture = dict(raw_capture)
    expected_capture_sha = _sha(
        capture.pop("source_capture_sha256", None), "source_capture.source_capture_sha256"
    )
    if _sha_bytes(_canonical_bytes(capture)) != expected_capture_sha:
        raise SelectorReleaseError("selector release source capture hash mismatch")
    if capture.get("schema_version") != SOURCE_CAPTURE_SCHEMA:
        raise SelectorReleaseError("selector release source capture schema mismatch")
    if capture.get("method") != "selected_source_double_read":
        raise SelectorReleaseError("selector release source capture method mismatch")
    if capture.get("source_git_head") != manifest.get("source_git_head"):
        raise SelectorReleaseError("selector release source git head mismatch")
    rows = capture.get("files")
    if not isinstance(rows, list):
        raise SelectorReleaseError("selector release source capture files missing")
    observed: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise SelectorReleaseError(f"source capture file entry invalid: {index}")
        relative_text = _text(raw.get("path"), f"source_capture.files[{index}].path")
        if relative_text in observed:
            raise SelectorReleaseError(f"duplicate source capture file: {relative_text}")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise SelectorReleaseError(f"source_capture.files[{index}].size_bytes must be >= 0")
        observed[relative_text] = {
            "sha256": _sha(raw.get("sha256"), f"source_capture.files[{index}].sha256"),
            "size_bytes": size,
        }
    if tuple(observed) != SOURCE_CAPTURE_FILES:
        raise SelectorReleaseError("selector release source capture closure mismatch")
    for relative_text in RELEASE_FILES:
        if observed[relative_text] != release_files[relative_text]:
            raise SelectorReleaseError(
                f"selector release source capture differs from release file: {relative_text}"
            )


def _runtime_paths(runtime_root: Path) -> tuple[Path, Path]:
    state = runtime_root.resolve(strict=False) / "state" / "grok_supervisor_selector"
    return state / "releases", state / "current.json"


def _python_in_venv(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _absolute_executable(path: Path) -> Path:
    """Normalize an executable path without dereferencing a venv symlink."""

    executable = Path(os.path.abspath(os.fspath(path)))
    if not executable.is_file():
        raise SelectorReleaseError(f"selector release python missing: {executable}")
    return executable


def _locked_requirement_specs_from_bytes(raw: bytes, *, lock_path: Path) -> tuple[str, ...]:
    try:
        lock = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise SelectorReleaseError(f"selector release lock invalid: {lock_path}: {exc}") from exc
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise SelectorReleaseError(f"selector release lock has no package list: {lock_path}")
    versions: dict[str, set[str]] = {name: set() for name in REQUIRED_DISTRIBUTIONS}
    for raw in packages:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip().lower()
        version = str(raw.get("version") or "").strip()
        if name in versions and version:
            versions[name].add(version)
    invalid = {name: sorted(found) for name, found in versions.items() if len(found) != 1}
    if invalid:
        raise SelectorReleaseError(
            "selector release dependencies are not uniquely pinned in uv.lock: "
            + json.dumps(invalid, ensure_ascii=False, sort_keys=True)
        )
    return tuple(f"{name}=={next(iter(versions[name]))}" for name in REQUIRED_DISTRIBUTIONS)


def _locked_requirement_specs(source_root: Path) -> tuple[str, ...]:
    """Resolve the release dependency subset to exact versions from ``uv.lock``."""

    lock_path = source_root / "uv.lock"
    try:
        raw = lock_path.read_bytes()
    except OSError as exc:
        raise SelectorReleaseError(f"selector release lock invalid: {lock_path}: {exc}") from exc
    return _locked_requirement_specs_from_bytes(raw, lock_path=lock_path)


def _bootstrap_release_dependencies(
    *,
    source_root: Path,
    python_executable: Path,
    requirements: tuple[str, ...],
) -> tuple[str, ...]:
    """Install only the exact locked release closure into its isolated venv."""

    uv_executable = shutil.which("uv")
    if not uv_executable:
        raise SelectorReleaseError("selector release bootstrap requires the uv executable")
    completed = subprocess.run(
        [
            uv_executable,
            "--no-config",
            "pip",
            "install",
            "--python",
            str(_absolute_executable(python_executable)),
            "--no-deps",
            *requirements,
        ],
        cwd=source_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SelectorReleaseError(
            "selector release locked dependency bootstrap failed: "
            f"exit={completed.returncode}; stdout={completed.stdout.strip()}; "
            f"stderr={completed.stderr.strip()}"
        )
    return requirements


def _probe_release(release_root: Path, python_executable: Path) -> dict[str, object]:
    python_executable = _absolute_executable(python_executable)
    selector = release_root / "services" / "agent_runtime" / "routing_policy_reader.py"
    code = (
        "import hashlib,importlib,importlib.metadata,json,pathlib,sys;"
        "r=pathlib.Path(sys.argv[1]).resolve(strict=True);"
        "sys.path.insert(0,str(r));"
        "m=importlib.import_module('services.agent_runtime.routing_policy_reader');"
        "a=importlib.import_module('services.agent_runtime.action_resume_receipt');"
        "d=importlib.import_module('services.agent_runtime.dispatch_economics');"
        "importlib.import_module('jsonschema');"
        "p=pathlib.Path(m.__file__).resolve(strict=True);"
        "ap=pathlib.Path(a.__file__).resolve(strict=True);"
        "required=getattr(m,'resolve_supervisor_worker_decision',None);"
        "claim=getattr(d,'claim_dispatch_route',None);"
        "checkpoint_preparer=getattr(a,'prepare_task_local_checkpoint',None);"
        "package_task_run_preparer=getattr(d,'prepare_worker_package_task_run',None);"
        "deps={n:importlib.metadata.version(n) for n in sys.argv[2:]};"
        "print(json.dumps({'module':str(p),'callable':callable(required),"
        "'action_resume_module':str(ap),'claim_callable':callable(claim),"
        "'checkpoint_preparer_callable':callable(checkpoint_preparer),"
        "'package_task_run_preparer_callable':callable(package_task_run_preparer),"
        "'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'dependencies':deps}));"
        "raise SystemExit(0 if callable(required) and callable(claim) and "
        "callable(checkpoint_preparer) and callable(package_task_run_preparer) and p=="
        "r/'services'/'agent_runtime'/'routing_policy_reader.py' and ap=="
        "r/'services'/'agent_runtime'/'action_resume_receipt.py' else 21)"
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            str(python_executable),
            "-I",
            "-B",
            "-c",
            code,
            str(release_root),
            *REQUIRED_DISTRIBUTIONS,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        payload = {}
    if (
        completed.returncode != 0
        or payload.get("callable") is not True
        or payload.get("claim_callable") is not True
        or payload.get("checkpoint_preparer_callable") is not True
        or payload.get("package_task_run_preparer_callable") is not True
        or payload.get("module") != str(selector.resolve(strict=True))
        or payload.get("action_resume_module")
        != str(
            (release_root / "services" / "agent_runtime" / "action_resume_receipt.py").resolve(
                strict=True
            )
        )
        or payload.get("sha256") != _sha_file(selector)
    ):
        raise SelectorReleaseError(
            "selector release import probe failed: "
            f"exit={completed.returncode}; stdout={completed.stdout.strip()}; "
            f"stderr={completed.stderr.strip()}"
        )
    preparer = release_root / "scripts" / "prepare_direct_worker_pool_common_contract.py"
    preparer_help = subprocess.run(
        [str(python_executable), "-I", "-B", str(preparer), "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    if preparer_help.returncode != 0 or "usage:" not in preparer_help.stdout.lower():
        raise SelectorReleaseError(
            "selector release contract preparer probe failed: "
            f"exit={preparer_help.returncode}; stdout={preparer_help.stdout.strip()}; "
            f"stderr={preparer_help.stderr.strip()}"
        )
    return {
        # On POSIX a venv interpreter is normally a symlink.  Recording its
        # realpath would silently drop the venv's site-packages at replay.
        "python_executable": str(python_executable),
        "python_isolated": True,
        "dont_write_bytecode": True,
        "selector_source": str(selector.resolve(strict=True)),
        "selector_source_sha256": payload["sha256"],
        "action_resume_module": payload["action_resume_module"],
        "dispatch_route_claim_callable": True,
        "task_local_checkpoint_preparer_callable": True,
        "package_task_run_preparer_callable": True,
        "contract_preparer": str(preparer.resolve(strict=True)),
        "contract_preparer_help": True,
        "dependency_distributions": payload["dependencies"],
    }


def _pointer_statically_references_release(
    pointer_path: Path,
    *,
    release_id: str,
    release_root: Path,
    manifest_path: Path,
) -> bool:
    """Avoid deleting a new release after its pointer commit already happened."""

    try:
        raw = pointer_path.read_bytes()
        pointer = _decode_object(raw, path=pointer_path, label="selector release pointer")
        manifest_raw = manifest_path.read_bytes()
    except (OSError, SelectorReleaseError):
        return False
    return (
        pointer.get("schema_version") == POINTER_SCHEMA
        and pointer.get("release_id") == release_id
        and _path_key(Path(str(pointer.get("release_root") or ""))) == _path_key(release_root)
        and _path_key(Path(str(pointer.get("release_manifest_ref") or "")))
        == _path_key(manifest_path)
        and pointer.get("release_manifest_sha256") == _sha_bytes(manifest_raw)
    )


def build_selector_release(
    *,
    source_root: Path,
    runtime_root: Path,
    release_id: str,
    python_executable: Path,
    create_venv: bool = True,
    promote: bool = False,
    expected_current: Mapping[str, object] | None = None,
    migrate_current_v1: bool = False,
) -> dict[str, object]:
    """Build one release from a stable double-read of the selected source closure."""

    source = Path(source_root).resolve(strict=True)
    runtime = (
        _lexical_absolute(Path(runtime_root))
        if migrate_current_v1
        else Path(runtime_root).resolve(strict=False)
    )
    identifier = _text(release_id, "release_id")
    if any(char in identifier for char in '\\/:*?"<>|') or identifier in {".", ".."}:
        raise SelectorReleaseError("release_id is not a safe path segment")
    executable = _absolute_executable(Path(python_executable))
    release_parent, pointer_path = (
        _legacy_runtime_paths(runtime) if migrate_current_v1 else _runtime_paths(runtime)
    )
    if expected_current is not None and not promote:
        raise SelectorReleaseError("expected_current is only valid when promote=True")
    if migrate_current_v1 and not promote:
        raise SelectorReleaseError("migrate_current_v1 is only valid when promote=True")
    if migrate_current_v1 and expected_current is not None:
        raise SelectorReleaseError("migrate_current_v1 observes its own exact legacy expectation")
    promotion_expectation: dict[str, str] | None = None
    if expected_current is not None:
        promotion_expectation = _normalize_current_identity(expected_current)
    elif promote:
        promotion_expectation = (
            selector_release_legacy_v1_migration_identity(runtime)
            if migrate_current_v1
            else selector_release_current_identity(runtime)
        )
    source_git_head = _git_head(source)
    captured_sources = _capture_selected_sources(source)
    requirements = _locked_requirement_specs_from_bytes(
        captured_sources["uv.lock"]["raw"],
        lock_path=source / "uv.lock",
    )
    release_root = release_parent / identifier
    if release_root.exists():
        raise SelectorReleaseError(f"selector release already exists: {release_root}")
    release_root.mkdir(parents=True, exist_ok=False)
    try:
        files: list[dict[str, object]] = []
        for relative_text in RELEASE_FILES:
            relative = Path(relative_text)
            target = release_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            selected = captured_sources[relative.as_posix()]
            raw = selected["raw"]
            if not isinstance(raw, bytes):
                raise SelectorReleaseError(
                    f"selector release source capture invalid: {relative_text}"
                )
            target.write_bytes(raw)
            files.append(
                {
                    "path": relative.as_posix(),
                    "sha256": _sha_file(target),
                    "size_bytes": target.stat().st_size,
                }
            )
        selected_python = executable
        if create_venv:
            completed = subprocess.run(
                [
                    str(executable),
                    "-m",
                    "venv",
                    str(release_root / ".venv"),
                    "--without-pip",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode != 0:
                raise SelectorReleaseError(
                    "selector release venv creation failed: "
                    f"exit={completed.returncode}; stderr={completed.stderr.strip()}"
                )
            selected_python = _python_in_venv(release_root)
            _bootstrap_release_dependencies(
                source_root=source,
                python_executable=selected_python,
                requirements=requirements,
            )
        probe = _probe_release(release_root, selected_python)
        observed_sources = _capture_selected_sources(source)
        if not _same_source_capture(captured_sources, observed_sources):
            raise SelectorReleaseError(
                "selector release selected source changed during coherent capture"
            )
        observed_git_head = _git_head(source)
        if observed_git_head != source_git_head:
            raise SelectorReleaseError(
                "selector release source git HEAD changed during coherent capture"
            )
        source_capture = _source_capture_manifest(
            captured_sources,
            source_git_head=source_git_head,
        )
        selected_python_path = Path(str(probe["python_executable"]))
        try:
            selected_python_raw = selected_python_path.read_bytes()
        except OSError as exc:
            raise SelectorReleaseError(
                f"selector release python unreadable: {selected_python_path}: {exc}"
            ) from exc
        manifest: dict[str, object] = {
            "schema_version": RELEASE_SCHEMA,
            "release_id": identifier,
            "release_root": str(release_root.resolve(strict=True)),
            "source_root": str(source),
            "source_git_head": source_git_head,
            "source_capture": source_capture,
            "files": files,
            "selector_source_sha256": probe["selector_source_sha256"],
            "python_executable": probe["python_executable"],
            "python_sha256": _sha_bytes(selected_python_raw),
            "python_size_bytes": len(selected_python_raw),
            "probe": probe,
            "authority": False,
            "completion_claim_allowed": False,
        }
        manifest["release_content_sha256"] = _sha_bytes(_canonical_bytes(manifest))
        manifest_path = release_root / "release_manifest.json"
        manifest_sha = _atomic_json(manifest_path, manifest)
        result: dict[str, object] = {
            "status": "release_built",
            "release_id": identifier,
            "release_root": str(release_root.resolve(strict=True)),
            "release_manifest_ref": str(manifest_path.resolve(strict=True)),
            "release_manifest_sha256": manifest_sha,
            "selector_source_sha256": probe["selector_source_sha256"],
            "python_executable": probe["python_executable"],
            "source_capture_sha256": source_capture["source_capture_sha256"],
        }
        if promote:
            if promotion_expectation is None:
                raise SelectorReleaseError("selector release promotion expectation missing")
            result.update(
                promote_selector_release(
                    runtime,
                    release_id=identifier,
                    expected_current=promotion_expectation,
                    migrate_current_v1=migrate_current_v1,
                )
            )
            result["status"] = (
                "release_built_and_migrated_from_legacy_v1"
                if migrate_current_v1
                else "release_built_and_promoted"
            )
        return result
    except Exception:
        committed = migrate_current_v1 and _pointer_statically_references_release(
            pointer_path,
            release_id=identifier,
            release_root=release_root,
            manifest_path=release_root / "release_manifest.json",
        )
        if not committed:
            shutil.rmtree(release_root, ignore_errors=True)
        raise


def _git_head(source: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and len(value) == 40 else None


def validate_selector_release_pointer(pointer_path: Path) -> dict[str, Any]:
    """Validate pointer, same-read manifest bytes, and the static release closure.

    Runtime consumers receive an exact execution binding and perform the final
    no-reparse, same-handle validation while holding those handles through
    process exit.  Loading a current release must never import its code across
    a validate-then-reopen seam.
    """

    pointer_file = Path(pointer_path).resolve(strict=False)
    pointer = _read_object(pointer_file, "selector release pointer")
    if pointer.get("schema_version") != POINTER_SCHEMA:
        raise SelectorReleaseError("selector release pointer schema mismatch")
    release_id = _text(pointer.get("release_id"), "pointer.release_id")
    release_root = Path(_text(pointer.get("release_root"), "pointer.release_root")).resolve(
        strict=False
    )
    manifest_path = Path(
        _text(pointer.get("release_manifest_ref"), "pointer.release_manifest_ref")
    ).resolve(strict=False)
    expected_manifest_sha = _sha(
        pointer.get("release_manifest_sha256"), "pointer.release_manifest_sha256"
    )
    if not manifest_path.is_file():
        raise SelectorReleaseError(f"release manifest missing: {manifest_path}")
    try:
        manifest_raw = manifest_path.read_bytes()
    except OSError as exc:
        raise SelectorReleaseError(f"release manifest unreadable: {manifest_path}: {exc}") from exc
    observed_manifest_sha = _sha_bytes(manifest_raw)
    if observed_manifest_sha != expected_manifest_sha:
        raise SelectorReleaseError(
            "release manifest hash mismatch: "
            f"expected={expected_manifest_sha}; observed={observed_manifest_sha}"
        )
    manifest = _decode_object(
        manifest_raw,
        path=manifest_path,
        label="selector release manifest",
    )
    if manifest.get("schema_version") != RELEASE_SCHEMA:
        raise SelectorReleaseError("selector release manifest schema mismatch")
    if manifest.get("release_id") != release_id:
        raise SelectorReleaseError("selector release id mismatch")
    if Path(str(manifest.get("release_root") or "")).resolve(strict=False) != release_root:
        raise SelectorReleaseError("selector release root mismatch")
    if manifest_path.parent.resolve(strict=False) != release_root:
        raise SelectorReleaseError("release manifest is not inside exact release root")
    content = dict(manifest)
    expected_content_sha = _sha(
        content.pop("release_content_sha256", None), "release_content_sha256"
    )
    if _sha_bytes(_canonical_bytes(content)) != expected_content_sha:
        raise SelectorReleaseError("selector release content hash mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise SelectorReleaseError("selector release file list missing")
    observed_paths: set[str] = set()
    observed_files: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(files):
        if not isinstance(raw, dict):
            raise SelectorReleaseError(f"release file entry invalid: {index}")
        relative_text = _text(raw.get("path"), f"files[{index}].path")
        if relative_text in observed_paths:
            raise SelectorReleaseError(f"duplicate release file: {relative_text}")
        observed_paths.add(relative_text)
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise SelectorReleaseError(f"unsafe release file path: {relative_text}")
        target = (release_root / relative).resolve(strict=False)
        if not target.is_file() or not _under(target.resolve(strict=True), release_root):
            raise SelectorReleaseError(f"release file missing: {target}")
        expected = _sha(raw.get("sha256"), f"files[{index}].sha256")
        try:
            target_raw = target.read_bytes()
        except OSError as exc:
            raise SelectorReleaseError(f"release file unreadable: {target}: {exc}") from exc
        actual = _sha_bytes(target_raw)
        if actual != expected:
            raise SelectorReleaseError(
                f"release file hash mismatch: {relative_text}; "
                f"expected={expected}; observed={actual}"
            )
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise SelectorReleaseError(f"files[{index}].size_bytes must be >= 0")
        if len(target_raw) != size:
            raise SelectorReleaseError(f"release file size mismatch: {relative_text}")
        observed_files[relative_text] = {"sha256": expected, "size_bytes": size}
    if observed_paths != set(RELEASE_FILES):
        raise SelectorReleaseError("selector release file closure mismatch")
    _validate_source_capture(manifest, observed_files)
    selector_sha = _sha(manifest.get("selector_source_sha256"), "selector_source_sha256")
    selector = release_root / "services" / "agent_runtime" / "routing_policy_reader.py"
    if _sha_file(selector) != selector_sha:
        raise SelectorReleaseError("selector source hash mismatch")
    python_executable = _absolute_executable(
        Path(_text(manifest.get("python_executable"), "python_executable"))
    )
    declared_probe = manifest.get("probe")
    if not isinstance(declared_probe, dict):
        raise SelectorReleaseError("selector release probe missing")
    if declared_probe.get("python_executable") != str(python_executable):
        raise SelectorReleaseError("selector release probe interpreter mismatch")
    if declared_probe.get("selector_source_sha256") != selector_sha:
        raise SelectorReleaseError("selector release probe selector mismatch")
    expected_python_sha = _sha(manifest.get("python_sha256"), "python_sha256")
    python_size = manifest.get("python_size_bytes")
    if isinstance(python_size, bool) or not isinstance(python_size, int) or python_size < 0:
        raise SelectorReleaseError("python_size_bytes must be >= 0")
    try:
        python_raw = python_executable.read_bytes()
    except OSError as exc:
        raise SelectorReleaseError(
            f"selector release python unreadable: {python_executable}: {exc}"
        ) from exc
    if _sha_bytes(python_raw) != expected_python_sha or len(python_raw) != python_size:
        raise SelectorReleaseError("selector release interpreter bytes drifted")
    execution_binding = {
        "schema_version": EXECUTION_BINDING_SCHEMA,
        "release_root": str(release_root),
        "python": {
            "path": str(python_executable),
            "sha256": expected_python_sha,
            "size_bytes": python_size,
        },
        "files": [
            {
                "path": relative_text,
                "sha256": observed_files[relative_text]["sha256"],
                "size_bytes": observed_files[relative_text]["size_bytes"],
            }
            for relative_text in RELEASE_FILES
        ],
    }
    if _sha_file(manifest_path) != expected_manifest_sha:
        raise SelectorReleaseError("release manifest changed during validation")
    return {
        **pointer,
        "pointer_path": str(pointer_file),
        "release_id": release_id,
        "release_root": str(release_root),
        "release_manifest_ref": str(manifest_path),
        "release_manifest_sha256": expected_manifest_sha,
        "selector_source_sha256": selector_sha,
        "python_executable": str(python_executable),
        "release_manifest": manifest,
        "execution_binding": execution_binding,
    }


def _normalize_current_identity(
    value: Mapping[str, object],
    *,
    allow_legacy_v1: bool = False,
) -> dict[str, str]:
    state = _text(value.get("state"), "expected_current.state").upper()
    if state == CURRENT_STATE_ABSENT:
        if set(value) != {"state"}:
            raise SelectorReleaseError("ABSENT expected_current may only contain state")
        return {"state": CURRENT_STATE_ABSENT}
    if state == CURRENT_STATE_LEGACY_V1_PRESENT:
        if not allow_legacy_v1:
            raise SelectorReleaseError(
                "LEGACY_V1_PRESENT expected_current is forbidden for normal promotion"
            )
        if set(value) != {
            "state",
            "release_id",
            "pointer_sha256",
            "release_manifest_sha256",
        }:
            raise SelectorReleaseError(
                "LEGACY_V1_PRESENT expected_current requires exact release_id, "
                "pointer_sha256, and release_manifest_sha256"
            )
        return {
            "state": CURRENT_STATE_LEGACY_V1_PRESENT,
            "release_id": _text(value.get("release_id"), "expected_current.release_id"),
            "pointer_sha256": _sha(value.get("pointer_sha256"), "expected_current.pointer_sha256"),
            "release_manifest_sha256": _sha(
                value.get("release_manifest_sha256"),
                "expected_current.release_manifest_sha256",
            ),
        }
    if state != CURRENT_STATE_PRESENT:
        raise SelectorReleaseError(
            "expected_current.state must be ABSENT, PRESENT, or explicit LEGACY_V1_PRESENT"
        )
    if set(value) != {"state", "release_id", "pointer_sha256"}:
        raise SelectorReleaseError(
            "PRESENT expected_current requires exact release_id and pointer_sha256"
        )
    return {
        "state": CURRENT_STATE_PRESENT,
        "release_id": _text(value.get("release_id"), "expected_current.release_id"),
        "pointer_sha256": _sha(value.get("pointer_sha256"), "expected_current.pointer_sha256"),
    }


def _current_pointer_identity(pointer_path: Path) -> dict[str, str]:
    try:
        before = pointer_path.read_bytes()
    except FileNotFoundError:
        return {"state": CURRENT_STATE_ABSENT}
    except OSError as exc:
        raise SelectorReleaseError(
            f"selector release pointer unreadable: {pointer_path}: {exc}"
        ) from exc
    try:
        before_pointer = json.loads(before.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SelectorReleaseError(
            f"selector release pointer invalid JSON: {pointer_path}: {exc}"
        ) from exc
    if not isinstance(before_pointer, dict):
        raise SelectorReleaseError(f"selector release pointer must be an object: {pointer_path}")
    validated = validate_selector_release_pointer(pointer_path)
    try:
        after = pointer_path.read_bytes()
    except OSError as exc:
        raise SelectorReleaseError(
            f"selector release pointer changed during observation: {pointer_path}: {exc}"
        ) from exc
    if before != after:
        raise SelectorReleaseError(
            f"selector release pointer changed during observation: {pointer_path}"
        )
    before_semantics = {
        "schema_version": before_pointer.get("schema_version"),
        "release_id": _text(before_pointer.get("release_id"), "pointer.release_id"),
        "release_root": str(
            Path(_text(before_pointer.get("release_root"), "pointer.release_root")).resolve(
                strict=False
            )
        ),
        "release_manifest_ref": str(
            Path(
                _text(
                    before_pointer.get("release_manifest_ref"),
                    "pointer.release_manifest_ref",
                )
            ).resolve(strict=False)
        ),
        "release_manifest_sha256": _sha(
            before_pointer.get("release_manifest_sha256"),
            "pointer.release_manifest_sha256",
        ),
    }
    validated_semantics = {field: validated.get(field) for field in before_semantics}
    if before_semantics != validated_semantics:
        raise SelectorReleaseError(
            f"selector release pointer changed during observation: {pointer_path}"
        )
    return {
        "state": CURRENT_STATE_PRESENT,
        "release_id": str(validated["release_id"]),
        "pointer_sha256": _sha_bytes(before),
    }


def selector_release_current_identity(runtime_root: Path) -> dict[str, str]:
    """Return the exact current pointer identity, including an explicit ABSENT state."""

    _, pointer_path = _runtime_paths(Path(runtime_root).resolve(strict=False))
    return _current_pointer_identity(pointer_path)


def _write_pointer_candidate(pointer_path: Path, payload: object) -> tuple[Path, str]:
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    raw = _json_bytes(payload)
    descriptor, temporary = tempfile.mkstemp(
        prefix=pointer_path.name + ".candidate.",
        suffix=".tmp",
        dir=pointer_path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path, _sha_bytes(raw)


def _replace_pointer_candidate(
    temporary_pointer: Path,
    pointer_path: Path,
    *,
    timeout_sec: float = 2.0,
) -> None:
    """Retry only the transient Windows sharing denial at the atomic replace syscall."""

    deadline = time.monotonic() + timeout_sec
    while True:
        try:
            os.replace(temporary_pointer, pointer_path)
            return
        except PermissionError as exc:
            if os.name != "nt" or time.monotonic() >= deadline:
                raise SelectorReleaseError(
                    f"selector release pointer replace failed: {pointer_path}: {exc}"
                ) from exc
            time.sleep(0.01)


def promote_selector_release(
    runtime_root: Path,
    *,
    release_id: str,
    expected_current: Mapping[str, object],
    migrate_current_v1: bool = False,
) -> dict[str, object]:
    """CAS-promote one validated release against the caller-observed pointer identity."""

    runtime = (
        _lexical_absolute(Path(runtime_root))
        if migrate_current_v1
        else Path(runtime_root).resolve(strict=False)
    )
    identifier = _text(release_id, "release_id")
    if any(char in identifier for char in '\\/:*?"<>|') or identifier in {".", ".."}:
        raise SelectorReleaseError("release_id is not a safe path segment")
    expectation = _normalize_current_identity(
        expected_current,
        allow_legacy_v1=migrate_current_v1,
    )
    if migrate_current_v1 and expectation["state"] != CURRENT_STATE_LEGACY_V1_PRESENT:
        raise SelectorReleaseError(
            "migrate_current_v1 requires an exact LEGACY_V1_PRESENT expectation"
        )
    releases, pointer_path = (
        _legacy_runtime_paths(runtime) if migrate_current_v1 else _runtime_paths(runtime)
    )
    release_root = releases / identifier
    manifest_path = release_root / "release_manifest.json"
    if not manifest_path.is_file():
        raise SelectorReleaseError(f"release manifest missing: {manifest_path}")

    with _SelectorReleaseLock(pointer_path.parent):
        pointer = {
            "schema_version": POINTER_SCHEMA,
            "release_id": identifier,
            "release_root": str(release_root.resolve(strict=True)),
            "release_manifest_ref": str(manifest_path.resolve(strict=True)),
            "release_manifest_sha256": _sha_file(manifest_path),
        }
        temporary_pointer, desired_pointer_sha = _write_pointer_candidate(pointer_path, pointer)
        try:
            validated_candidate = validate_selector_release_pointer(temporary_pointer)
            desired_identity = {
                "state": CURRENT_STATE_PRESENT,
                "release_id": identifier,
                "pointer_sha256": desired_pointer_sha,
            }
            if migrate_current_v1:
                try:
                    observed = _legacy_v1_pointer_identity(runtime)
                except SelectorReleaseError as exc:
                    raise SelectorReleaseError(
                        f"selector release current pointer changed from expected legacy v1: {exc}"
                    ) from exc
            else:
                observed = _current_pointer_identity(pointer_path)
            if observed == desired_identity:
                status = "release_already_current"
            else:
                if observed != expectation:
                    raise SelectorReleaseError(
                        "selector release current pointer changed: "
                        f"expected={json.dumps(expectation, sort_keys=True)}; "
                        f"observed={json.dumps(observed, sort_keys=True)}"
                    )
                _replace_pointer_candidate(temporary_pointer, pointer_path)
                status = (
                    "release_migrated_from_legacy_v1" if migrate_current_v1 else "release_promoted"
                )
        finally:
            temporary_pointer.unlink(missing_ok=True)

        validated = validate_selector_release_pointer(pointer_path)
        observed_pointer_sha = _sha_file(pointer_path)
        if validated["release_id"] != identifier or observed_pointer_sha != desired_pointer_sha:
            raise SelectorReleaseError("selector release pointer commit readback mismatch")
        if validated_candidate["release_manifest_sha256"] != validated["release_manifest_sha256"]:
            raise SelectorReleaseError("selector release candidate readback mismatch")
        result: dict[str, object] = {
            "status": status,
            "release_id": identifier,
            "pointer_path": str(pointer_path.resolve(strict=True)),
            "pointer_sha256": observed_pointer_sha,
            "release_root": validated["release_root"],
            "selector_source_sha256": validated["selector_source_sha256"],
            "python_executable": validated["python_executable"],
        }
        if migrate_current_v1:
            result["completion_claim_allowed"] = False
            result["migration"] = {
                "schema_version": LEGACY_V1_MIGRATION_SCHEMA,
                "from": expectation,
                "to": {
                    "state": CURRENT_STATE_PRESENT,
                    "release_id": identifier,
                    "pointer_sha256": observed_pointer_sha,
                    "release_manifest_sha256": validated["release_manifest_sha256"],
                },
                "completion_claim_allowed": False,
            }
        return result


def load_current_selector_release(runtime_root: Path) -> dict[str, Any]:
    """Load the single stable selector release; never search a task worktree."""

    _, pointer = _runtime_paths(Path(runtime_root))
    return validate_selector_release_pointer(pointer)
