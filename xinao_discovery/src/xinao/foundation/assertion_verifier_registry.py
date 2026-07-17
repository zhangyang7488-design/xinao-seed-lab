"""Fixed authority registry and code seal for foundation assertion verifiers."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
import stat
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256

CANONICAL_PROJECTION_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\mainline_domain_research_current"
    r"\blueprint.current_domain_research.json"
)
CURRENT_HUMAN_SPEC_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\01_主线入口"
    r"\新澳完整研究施工与旁路双环进化_当前有效.txt"
)
CURRENT_FORMAL_CONTRACT_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\02正式合同"
    r"\新澳整体基础执行与自主研究准入合同_当前有效.txt"
)
FOUNDATION_BLOCK_IDS = (
    "F1_settlement_world",
    "F2_issuer_settlement_cost_space",
    "F3_research_weight",
    "F4_research_factory",
)

_FOUNDATION_DIR = Path(__file__).resolve().parent
_XINAO_SRC = _FOUNDATION_DIR.parents[1]
_PROJECT_ROOT = _FOUNDATION_DIR.parents[2]
_REPO_ROOT = _FOUNDATION_DIR.parents[3]
_CANONICAL_PYTHON = _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
_F4_DUAL_BRAIN_PYTHON = (
    _REPO_ROOT / "projects" / "dual-brain-coordination" / ".venv" / "Scripts" / "python.exe"
)

AUTHORITY_SEAL_POLICY_ID = "xinao.foundation_authority_seal.v1"
AUTHORITY_MANIFEST_SCHEMA_VERSION = "xinao.compiler_code_manifest.v3"
RUNTIME_BUILDINFO_SCHEMA_VERSION = "xinao.foundation_runtime_buildinfo.v1"
AUTHORITY_MANIFEST_FILENAME = "authority_manifest.json"
RUNTIME_BUILDINFO_FILENAME = "runtime_buildinfo.json"
AUTHORITY_SOURCES_DIRNAME = "sources"

_RUNTIME_ROOTS = MappingProxyType(
    {
        "xinao_assertion_runtime": (
            "hypothesis",
            "pydantic",
            "rfc8785",
            "uuid6",
        ),
        "f4_dual_brain_runtime": (
            "temporalio",
            "pydantic",
            "rfc8785",
            "uuid6",
            "apsw",
            "jsonschema",
            "opentelemetry-api",
        ),
    }
)

_F4_AUTHORITY_SCRIPTS = (
    "verify_f4_live_canary_pack.py",
    "verify_f4_negative_companion_pack.py",
    "verify_f4_portfolio_source_canary_pack.py",
    "run_foundation_v2_f4_negative_companion.py",
)

_RUNTIME_PROBE = r"""
import hashlib
import importlib.metadata as metadata
import json
import pathlib
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def distribution_record(name):
    dist = metadata.distribution(name)
    prefix = pathlib.Path(sys.prefix).resolve()
    entries = []
    for item in sorted(dist.files or (), key=lambda value: str(value).replace("\\", "/")):
        path = pathlib.Path(dist.locate_file(item)).resolve()
        try:
            relative = path.relative_to(prefix).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"distribution file escapes runtime prefix: {name}: {path}") from exc
        if path.is_file():
            raw = path.read_bytes()
            entries.append(
                {
                    "relative_path": relative,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size": len(raw),
                }
            )
    requirements = []
    for raw_requirement in dist.requires or ():
        requirement = Requirement(raw_requirement)
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
            continue
        requirements.append(canonicalize_name(requirement.name))
    requirements = sorted(set(requirements))
    record = {
        "name": canonicalize_name(dist.metadata["Name"]),
        "version": dist.version,
        "requirements": requirements,
        "file_count": len(entries),
        "file_tree_sha256": digest(entries),
    }
    return record, requirements


roots = tuple(canonicalize_name(value) for value in json.loads(sys.argv[1]))
pending = list(roots)
records = {}
while pending:
    name = pending.pop(0)
    if name in records:
        continue
    record, requirements = distribution_record(name)
    records[name] = record
    pending.extend(item for item in requirements if item not in records)

resolver, _ = distribution_record("packaging")
payload = {
    "roots": list(roots),
    "resolver_distribution": resolver,
    "distributions": [records[name] for name in sorted(records)],
}
payload["projection_sha256"] = digest(payload)
print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
"""


class CanonicalVerifierError(ValueError):
    """Raised when a verifier or its authority seal is not canonical."""


@dataclass(frozen=True)
class CanonicalVerifier:
    block_id: str
    module_name: str
    relative_source: str
    checker_version: str

    @property
    def source_path(self) -> Path:
        path = (_XINAO_SRC / self.relative_source).resolve()
        canonical_root = _XINAO_SRC.resolve()
        if not path.is_relative_to(canonical_root) or not path.is_file():
            raise CanonicalVerifierError(
                f"canonical verifier path is unavailable for {self.block_id}: {path}"
            )
        return path

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.source_path.read_bytes()).hexdigest()

    @property
    def checker_id(self) -> str:
        return f"xinao.canonical.{self.block_id}.{self.source_sha256}"


_REGISTRY = MappingProxyType(
    {
        "F1_settlement_world": CanonicalVerifier(
            block_id="F1_settlement_world",
            module_name="xinao.foundation.assertion_verifiers.f1_assertion_actuals",
            relative_source="xinao/foundation/assertion_verifiers/f1_assertion_actuals.py",
            checker_version="xinao.foundation.assertion_actuals.f1.v1",
        ),
        "F2_issuer_settlement_cost_space": CanonicalVerifier(
            block_id="F2_issuer_settlement_cost_space",
            module_name="xinao.foundation.assertion_verifiers.f2_assertion_actuals",
            relative_source="xinao/foundation/assertion_verifiers/f2_assertion_actuals.py",
            checker_version="xinao.foundation.assertion_actuals.f2.v1",
        ),
        "F3_research_weight": CanonicalVerifier(
            block_id="F3_research_weight",
            module_name="xinao.foundation.assertion_verifiers.f3_assertion_actuals",
            relative_source="xinao/foundation/assertion_verifiers/f3_assertion_actuals.py",
            checker_version="xinao.foundation.assertion_actuals.f3.v1",
        ),
        "F4_research_factory": CanonicalVerifier(
            block_id="F4_research_factory",
            module_name="xinao.foundation.assertion_verifiers.f4_assertion_actuals",
            relative_source="xinao/foundation/assertion_verifiers/f4_assertion_actuals.py",
            checker_version="xinao.foundation.assertion_actuals.f4.v1",
        ),
    }
)


def canonical_registry() -> Mapping[str, CanonicalVerifier]:
    if tuple(_REGISTRY) != FOUNDATION_BLOCK_IDS:
        raise CanonicalVerifierError("canonical verifier registry must be exact ordered F1-F4")
    return _REGISTRY


def canonical_verifier(block_id: str) -> CanonicalVerifier:
    try:
        return canonical_registry()[block_id]
    except KeyError as exc:
        raise CanonicalVerifierError(f"unknown foundation block: {block_id}") from exc


def canonical_python_executable() -> Path:
    path = _CANONICAL_PYTHON.resolve()
    if not path.is_file():
        raise CanonicalVerifierError(f"canonical Python is unavailable: {path}")
    return path


def canonical_projection_path(path: Path | None = None) -> Path:
    """Return the sole current machine projection without granting it authority."""

    canonical = CANONICAL_PROJECTION_PATH.resolve()
    candidate = (path or canonical).resolve()
    if not canonical.is_file() or candidate != canonical:
        raise CanonicalVerifierError(
            "foundation authority binding requires the current non-authoritative "
            f"machine projection: {canonical}"
        )
    return canonical


def _validate_source_shape(entry: CanonicalVerifier) -> None:
    raw = entry.source_path.read_bytes()
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=str(entry.source_path))
    except (UnicodeError, SyntaxError) as exc:
        raise CanonicalVerifierError(
            f"canonical verifier is not valid UTF-8 Python: {entry.block_id}"
        ) from exc
    functions = [
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if functions != ["build_assertion_actuals_v1"]:
        raise CanonicalVerifierError(
            f"canonical verifier must expose one top-level callable: {entry.block_id}"
        )


def load_canonical_actuals_callable(
    block_id: str,
) -> tuple[CanonicalVerifier, Callable[[Mapping[str, Any]], Mapping[str, Any]]]:
    entry = canonical_verifier(block_id)
    _validate_source_shape(entry)
    module = importlib.import_module(entry.module_name)
    module_path = Path(str(module.__file__)).resolve()
    if module_path != entry.source_path:
        raise CanonicalVerifierError(
            f"canonical verifier module path replacement detected: {block_id}"
        )
    public_callables = sorted(
        name for name, value in vars(module).items() if not name.startswith("_") and callable(value)
    )
    if public_callables != ["build_assertion_actuals_v1"]:
        raise CanonicalVerifierError(f"canonical verifier public surface is invalid: {block_id}")
    return entry, module.build_assertion_actuals_v1


def _authority_code_paths() -> list[tuple[str, Path]]:
    """Return the narrow F1-F4 producer/verifier source closure."""

    candidates: list[Path] = [_XINAO_SRC / "xinao" / "__init__.py"]
    for root in (
        _XINAO_SRC / "xinao" / "canonical",
        _XINAO_SRC / "xinao" / "foundation",
        _XINAO_SRC / "xinao" / "contracts",
        _XINAO_SRC / "xinao" / "lineage",
        _REPO_ROOT / "projects" / "dual-brain-coordination" / "src",
    ):
        if not root.is_dir():
            raise CanonicalVerifierError(f"foundation authority root is missing: {root}")
        candidates.extend(sorted(root.rglob("*.py")))
    candidates.extend(
        [
            _REPO_ROOT / "services" / "__init__.py",
            _REPO_ROOT / "services" / "agent_runtime" / "__init__.py",
            _REPO_ROOT / "services" / "agent_runtime" / "foundation_continuous_workflow.py",
            _REPO_ROOT / "services" / "agent_runtime" / "foundation_continuous_workflow_v2.py",
            *(_REPO_ROOT / "scripts" / name for name in _F4_AUTHORITY_SCRIPTS),
        ]
    )
    paths: list[tuple[str, Path]] = []
    seen: set[str] = set()
    seen_casefold: set[str] = set()
    for candidate in sorted(set(candidates), key=lambda value: str(value).casefold()):
        path = candidate.resolve()
        if not path.is_file() or not path.is_relative_to(_REPO_ROOT.resolve()):
            raise CanonicalVerifierError(f"foundation authority source is missing: {path}")
        relative = path.relative_to(_REPO_ROOT).as_posix()
        folded = relative.casefold()
        if relative in seen or folded in seen_casefold:
            raise CanonicalVerifierError(f"foundation authority path identity collides: {relative}")
        seen.add(relative)
        seen_casefold.add(folded)
        paths.append((f"source:{relative}", path))
    return paths


def _python_runtime_identity(python: Path, *, label: str) -> dict[str, Any]:
    python = python.resolve()
    if not python.is_file():
        raise CanonicalVerifierError(f"{label} Python is unavailable: {python}")
    raw = python.read_bytes()
    completed = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            (
                "import json,platform,sys;"
                "print(json.dumps({'implementation':platform.python_implementation(),"
                "'version':platform.python_version(),"
                "'cache_tag':sys.implementation.cache_tag},sort_keys=True))"
            ),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        timeout=30,
    )
    if completed.returncode != 0:
        raise CanonicalVerifierError(
            f"{label} Python identity probe failed: {completed.stderr.strip()}"
        )
    try:
        identity = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CanonicalVerifierError(f"{label} Python identity is invalid") from exc
    return {
        "executable_path": str(python),
        "executable_sha256": hashlib.sha256(raw).hexdigest(),
        "executable_size": len(raw),
        **identity,
    }


def _runtime_distribution_projection(
    python: Path, *, label: str, roots: tuple[str, ...]
) -> dict[str, Any]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    completed = subprocess.run(
        [
            str(python.resolve()),
            "-I",
            "-c",
            _RUNTIME_PROBE,
            json.dumps(list(roots), ensure_ascii=False),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=environment,
        timeout=120,
    )
    if completed.returncode != 0:
        raise CanonicalVerifierError(
            f"{label} dependency projection failed: {completed.stderr.strip()}"
        )
    try:
        projection = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CanonicalVerifierError(f"{label} dependency projection is invalid") from exc
    if not isinstance(projection, dict):
        raise CanonicalVerifierError(f"{label} dependency projection is not an object")
    recorded_hash = projection.get("projection_sha256")
    core = dict(projection)
    core.pop("projection_sha256", None)
    if (
        projection.get("roots") != list(roots)
        or not isinstance(recorded_hash, str)
        or canonical_sha256(core) != recorded_hash
        or not isinstance(projection.get("distributions"), list)
        or not projection["distributions"]
    ):
        raise CanonicalVerifierError(f"{label} dependency projection is inconsistent")
    return projection


def build_foundation_runtime_buildinfo() -> dict[str, Any]:
    runtimes = {
        "xinao_assertion_runtime": {
            "interpreter": _python_runtime_identity(
                canonical_python_executable(), label="canonical assertion runner"
            ),
            "distribution_projection": _runtime_distribution_projection(
                canonical_python_executable(),
                label="canonical assertion runner",
                roots=_RUNTIME_ROOTS["xinao_assertion_runtime"],
            ),
        },
        "f4_dual_brain_runtime": {
            "interpreter": _python_runtime_identity(
                _F4_DUAL_BRAIN_PYTHON, label="F4 dual-brain verifier"
            ),
            "distribution_projection": _runtime_distribution_projection(
                _F4_DUAL_BRAIN_PYTHON,
                label="F4 dual-brain verifier",
                roots=_RUNTIME_ROOTS["f4_dual_brain_runtime"],
            ),
        },
    }
    core = {
        "schema_version": RUNTIME_BUILDINFO_SCHEMA_VERSION,
        "runtimes": runtimes,
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def build_canonical_code_manifest() -> dict[str, Any]:
    for block_id in FOUNDATION_BLOCK_IDS:
        load_canonical_actuals_callable(block_id)
    entries = []
    for role, path in _authority_code_paths():
        raw = path.read_bytes()
        entries.append(
            {
                "role": role,
                "relative_path": path.relative_to(_REPO_ROOT).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
        )
    registry_projection = {
        block_id: {
            "module_name": entry.module_name,
            "relative_source": entry.relative_source,
            "source_sha256": entry.source_sha256,
            "checker_id": entry.checker_id,
            "checker_version": entry.checker_version,
        }
        for block_id, entry in canonical_registry().items()
    }
    runtime_buildinfo = build_foundation_runtime_buildinfo()
    runtime_bytes = canonical_dumps(runtime_buildinfo)
    runtime_ref = {
        "relative_path": RUNTIME_BUILDINFO_FILENAME,
        "sha256": hashlib.sha256(runtime_bytes).hexdigest(),
        "size": len(runtime_bytes),
    }
    source_tree_sha256 = canonical_sha256(entries)
    core = {
        "schema_version": AUTHORITY_MANIFEST_SCHEMA_VERSION,
        "policy_id": AUTHORITY_SEAL_POLICY_ID,
        "registry": registry_projection,
        "entries": entries,
        "source_tree_sha256": source_tree_sha256,
        "runtime_buildinfo_ref": runtime_ref,
        "authority_tree_sha256": canonical_sha256(
            {
                "policy_id": AUTHORITY_SEAL_POLICY_ID,
                "source_tree_sha256": source_tree_sha256,
                "runtime_buildinfo_ref": runtime_ref,
            }
        ),
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def canonical_code_manifest_bytes() -> bytes:
    return canonical_dumps(build_canonical_code_manifest())


def validate_canonical_code_manifest(path: Path) -> dict[str, Any]:
    path = path.resolve()
    raw = path.read_bytes()
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CanonicalVerifierError("canonical code manifest is not JSON") from exc
    expected = build_canonical_code_manifest()
    if canonical_dumps(loaded) != raw or canonical_dumps(loaded) != canonical_dumps(expected):
        raise CanonicalVerifierError("canonical code manifest does not match current sealed code")
    return loaded


def _relative_snapshot_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CanonicalVerifierError("authority snapshot path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} or ":" in part for part in path.parts)
        or path.as_posix() != value
    ):
        raise CanonicalVerifierError(f"authority snapshot path escapes its root: {value}")
    return path


def _is_reparse(path: Path) -> bool:
    value = os.lstat(path)
    attributes = int(getattr(value, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


def _assert_snapshot_has_no_reparse(root: Path) -> None:
    if _is_reparse(root):
        raise CanonicalVerifierError(f"authority snapshot root is a reparse point: {root}")
    for path in root.rglob("*"):
        if _is_reparse(path):
            raise CanonicalVerifierError(f"authority snapshot contains a reparse point: {path}")


def _validate_manifest_shape(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CanonicalVerifierError("authority manifest must be an object")
    expected_keys = {
        "schema_version",
        "policy_id",
        "registry",
        "entries",
        "source_tree_sha256",
        "runtime_buildinfo_ref",
        "authority_tree_sha256",
        "content_sha256",
    }
    if set(value) != expected_keys:
        raise CanonicalVerifierError("authority manifest keys are not exact")
    if (
        value.get("schema_version") != AUTHORITY_MANIFEST_SCHEMA_VERSION
        or value.get("policy_id") != AUTHORITY_SEAL_POLICY_ID
    ):
        raise CanonicalVerifierError("authority manifest policy is unknown")
    core = dict(value)
    recorded_content_hash = core.pop("content_sha256", None)
    if canonical_sha256(core) != recorded_content_hash:
        raise CanonicalVerifierError("authority manifest content hash drifted")
    entries = value.get("entries")
    if not isinstance(entries, list) or not entries:
        raise CanonicalVerifierError("authority manifest source inventory is empty")
    roles: set[str] = set()
    paths: set[str] = set()
    folded_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "role",
            "relative_path",
            "sha256",
            "size",
        }:
            raise CanonicalVerifierError("authority manifest source entry is invalid")
        role = entry.get("role")
        relative = _relative_snapshot_path(entry.get("relative_path"))
        digest = entry.get("sha256")
        size = entry.get("size")
        if (
            not isinstance(role, str)
            or not role
            or role in roles
            or relative.as_posix() in paths
            or relative.as_posix().casefold() in folded_paths
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(size, int)
            or size <= 0
        ):
            raise CanonicalVerifierError("authority manifest source identity is invalid")
        roles.add(role)
        paths.add(relative.as_posix())
        folded_paths.add(relative.as_posix().casefold())
    if entries != sorted(entries, key=lambda item: str(item["relative_path"]).casefold()):
        raise CanonicalVerifierError("authority manifest source inventory is not ordered")
    if canonical_sha256(entries) != value.get("source_tree_sha256"):
        raise CanonicalVerifierError("authority source tree hash drifted")
    runtime_ref = value.get("runtime_buildinfo_ref")
    if (
        not isinstance(runtime_ref, dict)
        or set(runtime_ref) != {"relative_path", "sha256", "size"}
        or runtime_ref.get("relative_path") != RUNTIME_BUILDINFO_FILENAME
        or not isinstance(runtime_ref.get("sha256"), str)
        or len(runtime_ref["sha256"]) != 64
        or not isinstance(runtime_ref.get("size"), int)
        or runtime_ref["size"] <= 0
    ):
        raise CanonicalVerifierError("authority runtime buildinfo reference is invalid")
    expected_authority_hash = canonical_sha256(
        {
            "policy_id": AUTHORITY_SEAL_POLICY_ID,
            "source_tree_sha256": value["source_tree_sha256"],
            "runtime_buildinfo_ref": runtime_ref,
        }
    )
    if value.get("authority_tree_sha256") != expected_authority_hash:
        raise CanonicalVerifierError("authority tree hash drifted")
    return value


def materialize_authority_snapshot(root: Path) -> dict[str, Any]:
    root = Path(os.path.abspath(root))
    if root.exists():
        raise CanonicalVerifierError(f"authority snapshot root already exists: {root}")
    root.mkdir(parents=True, exist_ok=False)
    sources_root = root / AUTHORITY_SOURCES_DIRNAME
    sources_root.mkdir()
    manifest = build_canonical_code_manifest()
    runtime = build_foundation_runtime_buildinfo()
    runtime_bytes = canonical_dumps(runtime)
    if hashlib.sha256(runtime_bytes).hexdigest() != manifest["runtime_buildinfo_ref"]["sha256"]:
        raise CanonicalVerifierError("authority runtime changed during snapshot creation")
    for entry in manifest["entries"]:
        relative = _relative_snapshot_path(entry["relative_path"])
        source = (_REPO_ROOT / Path(*relative.parts)).resolve()
        raw = source.read_bytes()
        if len(raw) != entry["size"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise CanonicalVerifierError(
                f"authority source changed during snapshot creation: {relative}"
            )
        destination = sources_root.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    runtime_path = root / RUNTIME_BUILDINFO_FILENAME
    runtime_path.write_bytes(runtime_bytes)
    manifest_path = root / AUTHORITY_MANIFEST_FILENAME
    manifest_path.write_bytes(canonical_dumps(manifest))
    validated = validate_authority_snapshot(manifest_path, require_live_match=True)
    return {
        "root": root,
        "manifest_path": manifest_path,
        "runtime_buildinfo_path": runtime_path,
        "manifest": validated,
    }


def validate_authority_snapshot(manifest_path: Path, *, require_live_match: bool) -> dict[str, Any]:
    manifest_path = Path(os.path.abspath(manifest_path))
    root = manifest_path.parent
    if manifest_path.name != AUTHORITY_MANIFEST_FILENAME or not root.is_dir():
        raise CanonicalVerifierError("authority snapshot manifest location is invalid")
    _assert_snapshot_has_no_reparse(root)
    raw = manifest_path.read_bytes()
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CanonicalVerifierError("authority snapshot manifest is not JSON") from exc
    if canonical_dumps(loaded) != raw:
        raise CanonicalVerifierError("authority snapshot manifest is not canonical JSON")
    manifest = _validate_manifest_shape(loaded)
    expected_files = {
        AUTHORITY_MANIFEST_FILENAME,
        RUNTIME_BUILDINFO_FILENAME,
        *(f"{AUTHORITY_SOURCES_DIRNAME}/{entry['relative_path']}" for entry in manifest["entries"]),
    }
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual_files != expected_files or len(actual_files) != len(
        {item.casefold() for item in actual_files}
    ):
        raise CanonicalVerifierError("authority snapshot file inventory is not exact")
    expected_directories = {AUTHORITY_SOURCES_DIRNAME}
    for item in expected_files:
        parent = PurePosixPath(item).parent
        while parent != PurePosixPath("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    actual_directories = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()
    }
    if actual_directories != expected_directories or len(actual_directories) != len(
        {item.casefold() for item in actual_directories}
    ):
        raise CanonicalVerifierError("authority snapshot directory inventory is not exact")
    for entry in manifest["entries"]:
        relative = _relative_snapshot_path(entry["relative_path"])
        path = root / AUTHORITY_SOURCES_DIRNAME / Path(*relative.parts)
        content = path.read_bytes()
        if len(content) != entry["size"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise CanonicalVerifierError(
                f"authority snapshot source hash drifted: {relative.as_posix()}"
            )
    runtime_path = root / RUNTIME_BUILDINFO_FILENAME
    runtime_raw = runtime_path.read_bytes()
    runtime_ref = manifest["runtime_buildinfo_ref"]
    if (
        len(runtime_raw) != runtime_ref["size"]
        or hashlib.sha256(runtime_raw).hexdigest() != runtime_ref["sha256"]
    ):
        raise CanonicalVerifierError("authority snapshot runtime buildinfo drifted")
    try:
        runtime = json.loads(runtime_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CanonicalVerifierError("authority runtime buildinfo is not JSON") from exc
    if canonical_dumps(runtime) != runtime_raw or not isinstance(runtime, dict):
        raise CanonicalVerifierError("authority runtime buildinfo is not canonical")
    runtime_core = dict(runtime)
    runtime_hash = runtime_core.pop("content_sha256", None)
    if (
        runtime.get("schema_version") != RUNTIME_BUILDINFO_SCHEMA_VERSION
        or canonical_sha256(runtime_core) != runtime_hash
    ):
        raise CanonicalVerifierError("authority runtime buildinfo content drifted")
    if require_live_match:
        current = build_canonical_code_manifest()
        if canonical_dumps(manifest) != canonical_dumps(current):
            raise CanonicalVerifierError(
                "authority snapshot does not match current production authority"
            )
    return manifest


__all__ = [
    "AUTHORITY_MANIFEST_FILENAME",
    "AUTHORITY_MANIFEST_SCHEMA_VERSION",
    "AUTHORITY_SEAL_POLICY_ID",
    "CANONICAL_PROJECTION_PATH",
    "CURRENT_FORMAL_CONTRACT_PATH",
    "CURRENT_HUMAN_SPEC_PATH",
    "FOUNDATION_BLOCK_IDS",
    "RUNTIME_BUILDINFO_FILENAME",
    "RUNTIME_BUILDINFO_SCHEMA_VERSION",
    "CanonicalVerifier",
    "CanonicalVerifierError",
    "build_canonical_code_manifest",
    "build_foundation_runtime_buildinfo",
    "canonical_code_manifest_bytes",
    "canonical_projection_path",
    "canonical_python_executable",
    "canonical_registry",
    "canonical_verifier",
    "load_canonical_actuals_callable",
    "materialize_authority_snapshot",
    "validate_authority_snapshot",
    "validate_canonical_code_manifest",
]
