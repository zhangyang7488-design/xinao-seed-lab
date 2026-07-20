#!/usr/bin/env python3
"""Image-owned stdlib-first bootstrap for isolated F4 capsule replay."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

DATA_ROOT = Path("/capsule")
DATA_MANIFEST = DATA_ROOT / "snapshot_manifest.json"
COMMON_F4_REQUEST = DATA_ROOT / "files" / "closure_f4_request"
COMMON_AUTHORITY_MANIFEST = DATA_ROOT / "files" / "closure_authority_manifest"
OUTPUT_ROOT = Path("/output")
AUTHORITY_ROOT = Path("/opt/xinao-authority")
AUTHORITY_MANIFEST = AUTHORITY_ROOT / "authority_source_manifest.json"
IMAGE_CONTRACT = Path("/opt/f4-metadata/execution_contract.json")
IMAGE_DOCKERFILE = Path("/opt/f4-metadata/Dockerfile")
IMAGE_CONTRACT_WRITER = Path("/opt/f4-metadata/write_execution_contract.py")
IMAGE_DEPENDENCY_SMOKE = Path("/opt/f4-metadata/dependency_import_smoke.json")
VERIFIER_LOCK = Path("/opt/f4-runtime/uv.lock")
TRACE_ROOT = Path("/tmp/xinao-f4-traces")
RUNTIME_VENV_ROOT = Path("/opt/f4-runtime/.venv")
RUNTIME_VENV_BIN = RUNTIME_VENV_ROOT / "bin"
AUTHORITY_RETAINED_IDENTITY = r"E:\XINAO_RESEARCH_WORKSPACES\nianhua-new-route-active"
PYTHON_BASE_IMAGE = (
    "python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf"
)
UV_BASE_IMAGE = (
    "ghcr.io/astral-sh/uv@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa"
)

DATA_MANIFEST_NAME = "snapshot_manifest.json"
AUTHORITY_MANIFEST_NAME = "authority_source_manifest.json"
CONTRACT_SCHEMA = "xinao.f4_oci_image_execution_contract.v1"
PREFLIGHT_SCHEMA = "xinao.f4_snapshot_stage0_preflight.v3"
DEPENDENCY_SMOKE_SCHEMA = "xinao.f4_dependency_import_smoke.v1"
TRACE_SCHEMA = "xinao.f4_snapshot_trace_summary.v1"
RUN_SCHEMA = "xinao.f4_snapshot_stage0_run.v1"
AUTHORITY_PROJECTION_SCHEMA = "xinao.f4_common_authority_projection.v1"
COMMON_BUNDLE_NAME = "f4_assertion_actual_bundle.v2.json"
CARRIER_SOURCE = "scripts/run_f4_snapshot_stage0.py"
LOCAL_MODULE_PREFIXES = ("services", "xinao", "xinao_coordination")
FIXED_RUNTIME_ENV = {
    "XINAO_F4_SNAPSHOT_MANIFEST": str(DATA_MANIFEST),
    "XINAO_F4_SNAPSHOT_OUTPUT_ROOT": str(OUTPUT_ROOT),
    "XINAO_F4_SNAPSHOT_TRACE_DIR": str(TRACE_ROOT),
    "XINAO_F4_AUTHORITY_ROOT": str(AUTHORITY_ROOT),
    "XINAO_F4_AUTHORITY_IDENTITY": AUTHORITY_RETAINED_IDENTITY,
}


class Stage0Error(RuntimeError):
    """Raised before local project code is admitted into the process."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise Stage0Error(message)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = int(getattr(info, "st_file_attributes", 0))
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    _require(path.is_file(), f"{label} is missing: {path}")
    _require(not _is_reparse(path), f"{label} is a reparse point: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Stage0Error(f"{label} is not valid JSON") from exc
    _require(isinstance(value, dict), f"{label} is not a JSON object")
    return value


def _verify_content_identity(value: dict[str, Any], *, label: str) -> str:
    core = dict(value)
    content_hash = str(core.pop("content_sha256", ""))
    _require(
        len(content_hash) == 64 and content_hash == _canonical_sha256(core),
        f"{label} content identity drifted",
    )
    return content_hash


def _exact_inventory(
    *,
    root: Path,
    manifest_path: Path,
    rows: object,
    label: str,
) -> list[dict[str, Any]]:
    _require(root.is_dir() and not _is_reparse(root), f"{label} root is not a plain directory")
    _require(isinstance(rows, list) and rows, f"{label} inventory is empty")
    expected: dict[str, dict[str, Any]] = {}
    for raw in rows:
        _require(isinstance(raw, dict), f"{label} inventory row is invalid")
        relative = str(raw.get("relative_path") or "")
        _require(
            relative
            and "\\" not in relative
            and not relative.startswith("/")
            and all(part not in {"", ".", ".."} for part in relative.split("/")),
            f"{label} inventory path is unsafe: {relative}",
        )
        _require(relative not in expected, f"{label} inventory path is duplicated: {relative}")
        expected[relative] = dict(raw)

    actual: set[str] = set()
    for directory, names, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        _require(not _is_reparse(directory_path), f"{label} directory is a reparse point")
        for name in names:
            _require(
                not _is_reparse(directory_path / name),
                f"{label} child directory is a reparse point: {directory_path / name}",
            )
        for name in files:
            path = directory_path / name
            _require(not _is_reparse(path), f"{label} file is a reparse point: {path}")
            if path.resolve() != manifest_path.resolve():
                actual.add(path.relative_to(root).as_posix())
    _require(actual == set(expected), f"{label} inventory is not exact")
    ordered: list[dict[str, Any]] = []
    for relative in sorted(expected):
        path = root / Path(*relative.split("/"))
        raw = expected[relative]
        _require(path.is_file(), f"{label} inventory file is missing: {relative}")
        observed = {
            "relative_path": relative,
            "sha256": _file_sha256(path),
            "size_bytes": path.stat().st_size,
        }
        _require(raw == observed, f"{label} inventory seal drifted: {relative}")
        ordered.append(observed)
    return ordered


def _verify_image_contract() -> dict[str, Any]:
    contract = _load_json_object(IMAGE_CONTRACT, label="image execution contract")
    _require(contract.get("schema_version") == CONTRACT_SCHEMA, "image contract schema drifted")
    _verify_content_identity(contract, label="image execution contract")
    expected_keys = {
        "schema_version",
        "authority_manifest_sha256",
        "authority_content_sha256",
        "data_manifest_sha256",
        "data_content_sha256",
        "dockerfile_sha256",
        "contract_writer_sha256",
        "verifier_lock_sha256",
        "python_base_image",
        "uv_base_image",
        "authority_retained_identity",
        "content_sha256",
    }
    _require(set(contract) == expected_keys, "image contract key set drifted")
    _require(
        contract.get("authority_retained_identity") == AUTHORITY_RETAINED_IDENTITY,
        "authority retained identity drifted",
    )
    _require(
        contract.get("python_base_image") == PYTHON_BASE_IMAGE
        and contract.get("uv_base_image") == UV_BASE_IMAGE,
        "image base identity drifted",
    )
    _require(
        contract.get("verifier_lock_sha256") == _file_sha256(VERIFIER_LOCK),
        "installed verifier lock identity drifted",
    )
    _require(
        contract.get("dockerfile_sha256") == _file_sha256(IMAGE_DOCKERFILE),
        "image-owned Dockerfile identity drifted",
    )
    _require(
        contract.get("contract_writer_sha256") == _file_sha256(IMAGE_CONTRACT_WRITER),
        "image-owned contract writer identity drifted",
    )
    return contract


def _verify_data_capsule(contract: dict[str, Any]) -> dict[str, Any]:
    manifest = _load_json_object(DATA_MANIFEST, label="data snapshot manifest")
    _require(DATA_MANIFEST.name == DATA_MANIFEST_NAME, "data manifest name drifted")
    content_hash = _verify_content_identity(manifest, label="data snapshot manifest")
    _require(
        _file_sha256(DATA_MANIFEST) == contract["data_manifest_sha256"]
        and content_hash == contract["data_content_sha256"],
        "mounted data capsule is not the image-bound identity",
    )
    inventory = _exact_inventory(
        root=DATA_ROOT,
        manifest_path=DATA_MANIFEST,
        rows=manifest.get("inventory"),
        label="data capsule",
    )
    _require(
        manifest.get("inventory_count") == len(inventory),
        "data capsule inventory count drifted",
    )
    return manifest


def _verify_authority(contract: dict[str, Any]) -> dict[str, Any]:
    manifest = _load_json_object(AUTHORITY_MANIFEST, label="authority manifest")
    _require(AUTHORITY_MANIFEST.name == AUTHORITY_MANIFEST_NAME, "authority manifest name drifted")
    content_hash = _verify_content_identity(manifest, label="authority manifest")
    _require(
        _file_sha256(AUTHORITY_MANIFEST) == contract["authority_manifest_sha256"]
        and content_hash == contract["authority_content_sha256"],
        "image authority is not the execution-contract identity",
    )
    artifacts = _exact_inventory(
        root=AUTHORITY_ROOT,
        manifest_path=AUTHORITY_MANIFEST,
        rows=manifest.get("artifacts"),
        label="authority source pack",
    )
    _require(
        manifest.get("artifact_count") == len(artifacts),
        "authority artifact count drifted",
    )
    self_path = Path(__file__).resolve()
    _require(_inside(self_path, AUTHORITY_ROOT), "stage0 did not execute from image authority")
    self_relative = self_path.relative_to(AUTHORITY_ROOT).as_posix()
    by_path = {str(item["relative_path"]): item for item in artifacts}
    _require(self_relative in by_path, "stage0 is absent from authority inventory")
    _require(
        by_path[self_relative]["sha256"] == _file_sha256(self_path),
        "stage0 authority seal drifted",
    )
    return manifest


def _reject_host_runtime_overrides() -> None:
    inherited = sorted(key for key in os.environ if key.upper().startswith("XINAO_F4_"))
    _require(not inherited, f"host XINAO_F4 environment override rejected: {inherited}")
    os.environ.update(FIXED_RUNTIME_ENV)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTHONUTF8"] = "1"


def _runtime_python_launcher() -> Path:
    launcher = Path(os.path.abspath(sys.executable))
    _require(
        launcher.parent == RUNTIME_VENV_BIN, f"runtime Python launcher escaped venv: {launcher}"
    )
    _require(launcher.is_file(), f"runtime Python launcher is missing: {launcher}")
    return launcher


def _dependency_import_smoke(authority: dict[str, Any]) -> dict[str, Any]:
    raw_roots = authority.get("external_module_roots")
    _require(
        isinstance(raw_roots, list)
        and raw_roots == sorted(set(raw_roots))
        and all(isinstance(item, str) and item for item in raw_roots),
        "authority external module inventory drifted",
    )
    roots = list(raw_roots)
    third_party_roots = sorted(set(roots) - set(sys.stdlib_module_names))
    launcher = _runtime_python_launcher()
    bootstrap = "\n".join(
        (
            "import importlib, json, sys",
            "roots = json.loads(sys.argv[1])",
            "failures = {}",
            "for name in roots:",
            "    try:",
            "        importlib.import_module(name)",
            "    except Exception as exc:",
            "        failures[name] = f'{type(exc).__name__}: {exc}'",
            "result = {",
            "    'python_executable': sys.executable,",
            "    'python_prefix': sys.prefix,",
            "    'site_package_paths': sorted(path for path in sys.path if 'site-packages' in path),",
            "    'imported_module_roots': roots,",
            "    'failures': failures,",
            "}",
            "print(json.dumps(result, sort_keys=True, separators=(',', ':')))",
            "raise SystemExit(bool(failures))",
        )
    )
    allowed_environment = {
        "HOME",
        "LANG",
        "PATH",
        "TEMP",
        "TMP",
        "TZ",
    }
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in allowed_environment
    }
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})
    completed = subprocess.run(
        [str(launcher), "-I", "-c", bootstrap, json.dumps(roots)],
        cwd=str(RUNTIME_VENV_ROOT.parent),
        env=environment,
        capture_output=True,
        text=True,
        shell=False,
        timeout=120,
        check=False,
    )
    _require(
        completed.returncode == 0,
        "runtime dependency import smoke failed: "
        + completed.stdout[-3000:]
        + completed.stderr[-3000:],
    )
    try:
        observed = json.loads(completed.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise Stage0Error("runtime dependency import smoke emitted no result") from exc
    expected_site_root = os.path.normcase(str(RUNTIME_VENV_ROOT / "lib"))
    site_paths = observed.get("site_package_paths")
    _require(
        observed.get("python_executable") == str(launcher)
        and observed.get("python_prefix") == str(RUNTIME_VENV_ROOT)
        and observed.get("imported_module_roots") == roots
        and observed.get("failures") == {}
        and isinstance(site_paths, list)
        and any(os.path.normcase(str(path)).startswith(expected_site_root) for path in site_paths),
        "runtime dependency import smoke escaped the fixed venv",
    )
    core = {
        "schema_version": DEPENDENCY_SMOKE_SCHEMA,
        "status": "VERIFIED",
        "python_executable": str(launcher),
        "python_prefix": str(RUNTIME_VENV_ROOT),
        "external_module_count": len(roots),
        "external_module_roots": roots,
        "third_party_module_count": len(third_party_roots),
        "third_party_module_roots": third_party_roots,
        "failure_count": 0,
    }
    return {**core, "content_sha256": _canonical_sha256(core)}


def _filter_and_bind_imports() -> list[str]:
    runtime_roots = (Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve())
    retained: list[str] = []
    for raw in sys.path:
        if not raw:
            continue
        try:
            resolved = Path(raw).resolve()
        except OSError:
            continue
        if any(_inside(resolved, root) for root in runtime_roots):
            retained.append(str(resolved))
    local_roots = (
        AUTHORITY_ROOT,
        AUTHORITY_ROOT / "xinao_discovery" / "src",
        AUTHORITY_ROOT / "projects" / "dual-brain-coordination" / "src",
    )
    for root in reversed(local_roots):
        _require(root.is_dir(), f"authority module root is missing: {root}")
        retained.insert(0, str(root))
    sys.path[:] = list(dict.fromkeys(retained))
    for name in tuple(sys.modules):
        if name in LOCAL_MODULE_PREFIXES or name.startswith(
            tuple(prefix + "." for prefix in LOCAL_MODULE_PREFIXES)
        ):
            del sys.modules[name]
    return [str(root.resolve()) for root in local_roots]


def _install_read_boundary() -> None:
    allowed_roots = (
        AUTHORITY_ROOT.resolve(),
        DATA_ROOT.resolve(),
        OUTPUT_ROOT.resolve(),
        TRACE_ROOT.parent.resolve(),
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
    )

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        try:
            path = Path(args[0]).resolve()
        except (OSError, TypeError, ValueError):
            return
        if any(_inside(path, root) for root in allowed_roots):
            return
        raise Stage0Error(f"image read boundary rejected path: {path}")

    sys.addaudithook(audit)


def _isolation_negative_probes() -> dict[str, Any]:
    write_rejections: list[dict[str, Any]] = []
    for label, path in (
        ("image_authority", AUTHORITY_ROOT / ".stage0-write-negative"),
        ("data_capsule", DATA_ROOT / ".stage0-write-negative"),
    ):
        try:
            path.write_bytes(b"rejected")
        except OSError as exc:
            write_rejections.append(
                {
                    "label": label,
                    "path": str(path),
                    "status": "REJECTED",
                    "exception_type": type(exc).__name__,
                    "errno": exc.errno,
                }
            )
        else:
            path.unlink(missing_ok=True)
            raise Stage0Error(f"isolation write unexpectedly succeeded: {path}")

    host_path_rejections: list[dict[str, Any]] = []
    for label, path in (
        (
            "host_e",
            Path(
                "/run/desktop/mnt/host/e/XINAO_RESEARCH_WORKSPACES/"
                "nianhua-new-route-active/AGENTS.md"
            ),
        ),
        (
            "host_d",
            Path(
                "/run/desktop/mnt/host/d/XINAO_RESEARCH_RUNTIME/state/"
                "Codex_Situation_Island/state/session_checkpoint.json"
            ),
        ),
        (
            "host_mnt_e",
            Path("/host_mnt/e/XINAO_RESEARCH_WORKSPACES/nianhua-new-route-active/AGENTS.md"),
        ),
        (
            "host_mnt_d",
            Path(
                "/host_mnt/d/XINAO_RESEARCH_RUNTIME/state/"
                "Codex_Situation_Island/state/session_checkpoint.json"
            ),
        ),
    ):
        try:
            path.read_bytes()
        except OSError as exc:
            host_path_rejections.append(
                {
                    "label": label,
                    "path": str(path),
                    "status": "REJECTED",
                    "exception_type": type(exc).__name__,
                    "errno": exc.errno,
                }
            )
        else:
            raise Stage0Error(f"undeclared host path was readable: {path}")

    output_probe = OUTPUT_ROOT / ".stage0-output-probe"
    output_probe.write_bytes(b"output-write-probe")
    _require(output_probe.read_bytes() == b"output-write-probe", "output probe readback failed")
    output_probe.unlink()
    return {
        "image_authority_write_rejected": True,
        "data_capsule_write_rejected": True,
        "host_path_read_rejected_count": len(host_path_rejections),
        "output_write_verified": True,
        "write_rejections": write_rejections,
        "host_path_rejections": host_path_rejections,
    }


def _local_module_origins() -> dict[str, str]:
    origins: dict[str, str] = {}
    for name, module in sorted(sys.modules.items()):
        if not (
            name in LOCAL_MODULE_PREFIXES
            or name.startswith(tuple(prefix + "." for prefix in LOCAL_MODULE_PREFIXES))
        ):
            continue
        raw = getattr(module, "__file__", None)
        if not raw:
            continue
        origin = Path(str(raw)).resolve()
        _require(_inside(origin, AUTHORITY_ROOT), f"local module escaped authority: {name}")
        origins[name] = str(origin)
    _require("xinao" in origins and "services" in origins, "required local modules are absent")
    return origins


def preflight() -> tuple[dict[str, Any], dict[str, Any]]:
    _reject_host_runtime_overrides()
    contract = _verify_image_contract()
    authority = _verify_authority(contract)
    data = _verify_data_capsule(contract)
    module_roots = _filter_and_bind_imports()
    TRACE_ROOT.mkdir(parents=True, exist_ok=True)
    isolation_negative_probes = _isolation_negative_probes()
    dependency_import_smoke = _dependency_import_smoke(authority)
    build_dependency_import_smoke = _load_json_object(
        IMAGE_DEPENDENCY_SMOKE,
        label="build dependency import smoke",
    )
    _require(
        build_dependency_import_smoke == dependency_import_smoke,
        "runtime dependency import smoke drifted from image build",
    )
    build_dependency_import_smoke_sha256 = _file_sha256(IMAGE_DEPENDENCY_SMOKE)
    _install_read_boundary()

    from xinao.foundation.f4_authority_source_pack import verify_authority_source_pack
    from xinao.foundation.f4_evidence_snapshot import verify_snapshot_manifest

    verified_authority = verify_authority_source_pack(AUTHORITY_MANIFEST)
    verified_data = verify_snapshot_manifest(DATA_MANIFEST)
    _require(verified_authority == authority, "authority package verification drifted")
    _require(verified_data == data, "data package verification drifted")
    for name in LOCAL_MODULE_PREFIXES:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue
    core = {
        "schema_version": PREFLIGHT_SCHEMA,
        "status": "VERIFIED",
        "image_contract_content_sha256": contract["content_sha256"],
        "authority_manifest_sha256": contract["authority_manifest_sha256"],
        "authority_content_sha256": contract["authority_content_sha256"],
        "data_manifest_sha256": contract["data_manifest_sha256"],
        "data_content_sha256": contract["data_content_sha256"],
        "stage0_sha256": _file_sha256(Path(__file__).resolve()),
        "module_roots": module_roots,
        "fixed_runtime_env": dict(FIXED_RUNTIME_ENV),
        "dependency_import_smoke": dependency_import_smoke,
        "build_dependency_import_smoke_sha256": build_dependency_import_smoke_sha256,
        "isolation_negative_probes": isolation_negative_probes,
        "host_runtime_override_count": 0,
        "fallback_count": 0,
    }
    return {**core, "content_sha256": _canonical_sha256(core)}, data


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))
    return path


def _common_authority_projection(
    *,
    request: dict[str, Any],
    image_authority: dict[str, Any],
) -> dict[str, Any]:
    common = _load_json_object(
        COMMON_AUTHORITY_MANIFEST,
        label="common closure authority manifest",
    )
    _require(
        _file_sha256(COMMON_AUTHORITY_MANIFEST) == request.get("compiler_code_sha256"),
        "F4 request does not bind the common authority manifest bytes",
    )
    common_content = _verify_content_identity(
        common,
        label="common closure authority manifest",
    )
    _require(
        common.get("schema_version") == "xinao.compiler_code_manifest.v3",
        "common closure authority schema drifted",
    )
    raw_entries = common.get("entries")
    raw_sources = image_authority.get("python_sources")
    _require(isinstance(raw_entries, list), "common authority entries are absent")
    _require(isinstance(raw_sources, list), "image authority Python sources are absent")
    common_entries = {
        str(row.get("relative_path")): dict(row)
        for row in raw_entries
        if isinstance(row, dict) and str(row.get("relative_path") or "").endswith(".py")
    }
    _require(
        len(common_entries)
        == len(
            [
                row
                for row in raw_entries
                if isinstance(row, dict) and str(row.get("relative_path") or "").endswith(".py")
            ]
        ),
        "common authority Python source paths are duplicated",
    )
    semantic_sources: list[dict[str, Any]] = []
    carrier_sources: list[dict[str, Any]] = []
    for raw in raw_sources:
        _require(isinstance(raw, dict), "image authority source row is invalid")
        row = dict(raw)
        relative = str(row.get("relative_path") or "")
        projection = {
            "relative_path": relative,
            "sha256": row.get("sha256"),
            "size_bytes": row.get("size_bytes"),
        }
        if relative == CARRIER_SOURCE:
            carrier_sources.append(projection)
            continue
        common_row = common_entries.get(relative)
        _require(
            common_row is not None,
            f"image semantic source is absent from common authority: {relative}",
        )
        _require(
            common_row.get("sha256") == projection["sha256"]
            and common_row.get("size") == projection["size_bytes"],
            f"image semantic source differs from common authority: {relative}",
        )
        semantic_sources.append(projection)
    _require(
        len(carrier_sources) == 1,
        "image authority must contain exactly one image-owned carrier source",
    )
    f4_source = "xinao_discovery/src/xinao/foundation/assertion_verifiers/f4_assertion_actuals.py"
    _require(
        any(row["relative_path"] == f4_source for row in semantic_sources),
        "image authority does not contain the canonical F4 assertion actuals",
    )
    registry = common.get("registry")
    _require(isinstance(registry, dict), "common authority registry is absent")
    f4_registry = registry.get("F4_research_factory")
    _require(
        isinstance(f4_registry, dict)
        and f4_registry.get("source_sha256") == common_entries[f4_source].get("sha256"),
        "common F4 registry source binding drifted",
    )
    semantic_sources.sort(key=lambda item: str(item["relative_path"]))
    core = {
        "schema_version": AUTHORITY_PROJECTION_SCHEMA,
        "status": "VERIFIED",
        "common_authority_manifest_sha256": _file_sha256(COMMON_AUTHORITY_MANIFEST),
        "common_authority_content_sha256": common_content,
        "semantic_source_count": len(semantic_sources),
        "semantic_sources_sha256": _canonical_sha256(semantic_sources),
        "carrier_source_count": 1,
        "carrier_source": carrier_sources[0],
        "f4_actuals_source_sha256": common_entries[f4_source]["sha256"],
    }
    return {**core, "content_sha256": _canonical_sha256(core)}


def _build_common_assertion_bundle(request: dict[str, Any]) -> dict[str, Any]:
    from xinao.foundation.assertion_bundle_runner import build_bundle_bytes_v2

    raw = build_bundle_bytes_v2(request=request, block_id="F4_research_factory")
    try:
        bundle = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Stage0Error("F4 assertion bundle is not canonical JSON") from exc
    _require(isinstance(bundle, dict), "F4 assertion bundle is not an object")
    _require(_canonical_bytes(bundle) == raw, "F4 assertion bundle bytes are not canonical")
    bundle_content = _verify_content_identity(bundle, label="F4 assertion bundle")
    actuals = bundle.get("assertion_actuals")
    assertion_ids = request.get("assertion_ids")
    _require(
        bundle.get("schema_version") == "xinao.assertion_actual_bundle.v2"
        and bundle.get("block_id") == "F4_research_factory"
        and isinstance(assertion_ids, list)
        and len(assertion_ids) == 14
        and isinstance(actuals, dict)
        and sorted(actuals) == assertion_ids
        and all(value is True for value in actuals.values()),
        "F4 assertion bundle does not contain the exact 14 verified actuals",
    )
    path = OUTPUT_ROOT / COMMON_BUNDLE_NAME
    path.write_bytes(raw)
    return {
        "path": str(path),
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
        "content_sha256": bundle_content,
        "request_sha256": bundle.get("request_sha256"),
        "assertion_count": len(actuals),
    }


def _trace_summary(expected_content_hash: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(TRACE_ROOT.glob("snapshot-trace-*.json")):
        value = _load_json_object(path, label="snapshot trace")
        row = {
            "event_count": int(value.get("event_count", -1)),
            "fallback_count": int(value.get("fallback_count", -1)),
            "manifest_content_sha256": str(value.get("manifest_content_sha256") or ""),
        }
        _require(row["event_count"] >= 0, "snapshot trace event count is invalid")
        _require(row["fallback_count"] == 0, "snapshot fallback was observed")
        _require(
            row["manifest_content_sha256"] == expected_content_hash,
            "snapshot trace identifies another capsule",
        )
        rows.append(row)
    rows.sort(key=lambda item: (item["event_count"], item["manifest_content_sha256"]))
    _require(len(rows) >= 5, "snapshot trace does not cover parent, checker, and three verifiers")
    core = {
        "schema_version": TRACE_SCHEMA,
        "status": "VERIFIED",
        "process_count": len(rows),
        "fallback_count": 0,
        "total_event_count": sum(int(row["event_count"]) for row in rows),
        "process_observations": rows,
        "manifest_content_sha256": expected_content_hash,
    }
    return {**core, "content_sha256": _canonical_sha256(core)}


def run() -> dict[str, Any]:
    preflight_result, data = preflight()
    _require(OUTPUT_ROOT.is_dir(), "fixed output mount is missing")
    from xinao.foundation.f4_snapshot_runtime import snapshot_runtime

    request = _load_json_object(COMMON_F4_REQUEST, label="common F4 assertion request")
    image_authority = _load_json_object(AUTHORITY_MANIFEST, label="image authority manifest")
    authority_projection = _common_authority_projection(
        request=request,
        image_authority=image_authority,
    )
    bundle = _build_common_assertion_bundle(request)
    runtime = snapshot_runtime()
    _require(runtime is not None, "snapshot runtime was not activated")
    runtime.write_trace()
    trace = _trace_summary(str(data["content_sha256"]))
    trace_path = _write_json(OUTPUT_ROOT / "snapshot_trace_summary.json", trace)
    origins = _local_module_origins()
    core = {
        "schema_version": RUN_SCHEMA,
        "status": "VERIFIED",
        "preflight": preflight_result,
        "common_assertion_bundle": bundle,
        "common_authority_projection": authority_projection,
        "snapshot_trace_summary_ref": str(trace_path),
        "snapshot_trace_summary_sha256": _file_sha256(trace_path),
        "snapshot_trace_summary_content_sha256": trace["content_sha256"],
        "local_module_count": len(origins),
        "local_module_origins": origins,
        "assertion_count": bundle["assertion_count"],
        "fallback_count": 0,
    }
    result = {**core, "content_sha256": _canonical_sha256(core)}
    result_path = _write_json(OUTPUT_ROOT / "stage0_result.json", result)
    return {
        **result,
        "stage0_result_ref": str(result_path),
        "stage0_result_sha256": _file_sha256(result_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dependency-smoke", "preflight", "run"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "dependency-smoke":
            authority = _load_json_object(AUTHORITY_MANIFEST, label="authority manifest")
            result = _dependency_import_smoke(authority)
        elif args.command == "preflight":
            result, _ = preflight()
        else:
            result = run()
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
