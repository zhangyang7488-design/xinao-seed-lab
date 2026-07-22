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
import subprocess
import tempfile
from pathlib import Path
from typing import Any

RELEASE_SCHEMA = "xinao.selector_release.v1"
POINTER_SCHEMA = "xinao.selector_release_pointer.v1"
REQUIRED_DISTRIBUTIONS = (
    "attrs",
    "jsonschema",
    "jsonschema-specifications",
    "referencing",
    "rpds-py",
)

RELEASE_FILES = (
    "services/__init__.py",
    "services/agent_runtime/__init__.py",
    "services/agent_runtime/routing_policy_reader.py",
    "services/agent_runtime/supervisor_worker_selector.py",
    "services/agent_runtime/provider_routing_preference.py",
    "services/agent_runtime/quota_capacity_adapter.py",
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


def _atomic_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
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


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise SelectorReleaseError(f"{label} missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SelectorReleaseError(f"{label} invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SelectorReleaseError(f"{label} must be an object: {path}")
    return value


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
        "deps={n:importlib.metadata.version(n) for n in sys.argv[2:]};"
        "print(json.dumps({'module':str(p),'callable':callable(required),"
        "'action_resume_module':str(ap),'claim_callable':callable(claim),"
        "'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'dependencies':deps}));"
        "raise SystemExit(0 if callable(required) and callable(claim) and p=="
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
        "dependency_distributions": payload["dependencies"],
    }


def build_selector_release(
    *,
    source_root: Path,
    runtime_root: Path,
    release_id: str,
    python_executable: Path,
    create_venv: bool = True,
    promote: bool = False,
) -> dict[str, object]:
    """Copy the pinned selector closure into a new immutable release directory."""

    source = Path(source_root).resolve(strict=True)
    runtime = Path(runtime_root).resolve(strict=False)
    identifier = _text(release_id, "release_id")
    if any(char in identifier for char in '\\/:*?"<>|') or identifier in {".", ".."}:
        raise SelectorReleaseError("release_id is not a safe path segment")
    executable = _absolute_executable(Path(python_executable))
    release_parent, _ = _runtime_paths(runtime)
    release_root = release_parent / identifier
    if release_root.exists():
        raise SelectorReleaseError(f"selector release already exists: {release_root}")
    release_root.mkdir(parents=True, exist_ok=False)
    try:
        files: list[dict[str, object]] = []
        for relative_text in RELEASE_FILES:
            relative = Path(relative_text)
            origin = (source / relative).resolve(strict=False)
            if not origin.is_file() or not _under(origin.resolve(strict=True), source):
                raise SelectorReleaseError(f"selector release source missing: {relative_text}")
            target = release_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
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
                    "--system-site-packages",
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
        probe = _probe_release(release_root, selected_python)
        manifest: dict[str, object] = {
            "schema_version": RELEASE_SCHEMA,
            "release_id": identifier,
            "release_root": str(release_root.resolve(strict=True)),
            "source_root": str(source),
            "source_git_head": _git_head(source),
            "files": files,
            "selector_source_sha256": probe["selector_source_sha256"],
            "python_executable": probe["python_executable"],
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
        }
        if promote:
            result.update(promote_selector_release(runtime, release_id=identifier))
            result["status"] = "release_built_and_promoted"
        return result
    except Exception:
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
    """Validate pointer, manifest, every release byte, and interpreter identity."""

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
    observed_manifest_sha = _sha_file(manifest_path)
    if observed_manifest_sha != expected_manifest_sha:
        raise SelectorReleaseError(
            "release manifest hash mismatch: "
            f"expected={expected_manifest_sha}; observed={observed_manifest_sha}"
        )
    manifest = _read_object(manifest_path, "selector release manifest")
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
        actual = _sha_file(target)
        if actual != expected:
            raise SelectorReleaseError(
                f"release file hash mismatch: {relative_text}; "
                f"expected={expected}; observed={actual}"
            )
    if observed_paths != set(RELEASE_FILES):
        raise SelectorReleaseError("selector release file closure mismatch")
    selector_sha = _sha(manifest.get("selector_source_sha256"), "selector_source_sha256")
    selector = release_root / "services" / "agent_runtime" / "routing_policy_reader.py"
    if _sha_file(selector) != selector_sha:
        raise SelectorReleaseError("selector source hash mismatch")
    python_executable = _absolute_executable(
        Path(_text(manifest.get("python_executable"), "python_executable"))
    )
    observed_probe = _probe_release(release_root, python_executable)
    declared_probe = manifest.get("probe")
    if not isinstance(declared_probe, dict):
        raise SelectorReleaseError("selector release probe missing")
    if observed_probe != declared_probe:
        raise SelectorReleaseError("selector release interpreter or dependency closure drifted")
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
    }


def promote_selector_release(runtime_root: Path, *, release_id: str) -> dict[str, object]:
    """Atomically move the single current pointer after full release validation."""

    runtime = Path(runtime_root).resolve(strict=False)
    identifier = _text(release_id, "release_id")
    releases, pointer_path = _runtime_paths(runtime)
    release_root = releases / identifier
    manifest_path = release_root / "release_manifest.json"
    if not manifest_path.is_file():
        raise SelectorReleaseError(f"release manifest missing: {manifest_path}")
    pointer = {
        "schema_version": POINTER_SCHEMA,
        "release_id": identifier,
        "release_root": str(release_root.resolve(strict=True)),
        "release_manifest_ref": str(manifest_path.resolve(strict=True)),
        "release_manifest_sha256": _sha_file(manifest_path),
    }
    temporary_pointer = pointer_path.with_name(pointer_path.name + ".candidate")
    if temporary_pointer.exists():
        temporary_pointer.unlink()
    try:
        _atomic_json(temporary_pointer, pointer)
        validate_selector_release_pointer(temporary_pointer)
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary_pointer, pointer_path)
    finally:
        temporary_pointer.unlink(missing_ok=True)
    validated = validate_selector_release_pointer(pointer_path)
    return {
        "status": "release_promoted",
        "release_id": identifier,
        "pointer_path": str(pointer_path.resolve(strict=True)),
        "pointer_sha256": _sha_file(pointer_path),
        "release_root": validated["release_root"],
        "selector_source_sha256": validated["selector_source_sha256"],
        "python_executable": validated["python_executable"],
    }


def load_current_selector_release(runtime_root: Path) -> dict[str, Any]:
    """Load the single stable selector release; never search a task worktree."""

    _, pointer = _runtime_paths(Path(runtime_root))
    return validate_selector_release_pointer(pointer)
