#!/usr/bin/env python3
"""Run the fixed F4 verifier image twice and emit an inspect-bound OCI receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN_INPUTS = REPO_ROOT / "docker" / "f4-verifier" / "frozen_inputs.v1.json"
ALLOWED_OUTPUT_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence")
RECEIPT_SCHEMA = "xinao.f4_oci_execution_receipt.v2"
EXPECTED_ENTRYPOINT = [
    "/opt/f4-runtime/.venv/bin/python",
    "-I",
    "/opt/xinao-authority/scripts/run_f4_snapshot_stage0.py",
]
EXPECTED_CMD = ["run"]
PYTHON_BASE_IMAGE = (
    "python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf"
)
UV_BASE_IMAGE = (
    "ghcr.io/astral-sh/uv@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa"
)
EXPECTED_TOP_LEVEL_FILES = {
    "f4_assertion_actual_bundle.v2.json",
    "snapshot_trace_summary.json",
    "stage0_result.json",
}
HOST_SENTINEL_PATHS = {
    "host_e": REPO_ROOT / "AGENTS.md",
    "host_d": Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\state\session_checkpoint.json"
    ),
}


class OciRunnerError(RuntimeError):
    """Raised when the fixed OCI execution contract is not observed."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise OciRunnerError(message)


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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = int(getattr(info, "st_file_attributes", 0))
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _overlaps(left: Path, right: Path) -> bool:
    return _inside(left, right) or _inside(right, left)


def _validate_output_parent(
    path: Path,
    config: dict[str, Any],
    *,
    data_root: Path | None = None,
) -> Path:
    resolved = path.resolve()
    _require(not resolved.exists(), f"output parent already exists: {resolved}")
    _require(
        _inside(resolved, ALLOWED_OUTPUT_ROOT) and resolved != ALLOWED_OUTPUT_ROOT.resolve(),
        f"output parent is outside the fixed D evidence root: {resolved}",
    )
    current = resolved.parent
    while True:
        if current.exists():
            _require(not _is_reparse(current), f"output parent contains a reparse point: {current}")
        parent = current.parent
        if parent == current:
            break
        current = parent
    build_receipt_raw = str(config.get("build_receipt_path") or "")
    _require(build_receipt_raw, "frozen build receipt path is absent")
    protected_data_root = (
        data_root.resolve()
        if data_root is not None
        else Path(str(config["data_manifest_path"])).resolve().parent
    )
    protected = (
        REPO_ROOT.resolve(),
        FROZEN_INPUTS.resolve(),
        Path(str(config["authority_manifest_path"])).resolve().parent,
        Path(str(config["data_manifest_path"])).resolve().parent,
        protected_data_root,
        Path(build_receipt_raw).resolve().parent,
    )
    _require(
        not any(_overlaps(resolved, item) for item in protected),
        "output parent overlaps repository, frozen input, authority, or data capsule",
    )
    return resolved


def _admit_execution_data_root(
    config: dict[str, Any],
    data_root: Path | None,
) -> Path:
    root = (
        data_root.resolve()
        if data_root is not None
        else Path(str(config["data_manifest_path"])).resolve().parent
    )
    _require(root.is_dir() and not _is_reparse(root), "execution data root is invalid")
    manifest_path = root / "snapshot_manifest.json"
    manifest = _load_object(manifest_path, label="execution data manifest")
    content_hash = _content_addressed(manifest, label="execution data manifest")
    _require(
        _file_sha256(manifest_path) == config["data_manifest_sha256"]
        and content_hash == config["data_content_sha256"],
        "execution data root differs from the frozen content identity",
    )
    return root


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    _require(path.is_file(), f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OciRunnerError(f"{label} is invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"{label} is not a JSON object")
    return value


def _content_addressed(value: dict[str, Any], *, label: str) -> str:
    core = dict(value)
    content_hash = str(core.pop("content_sha256", ""))
    _require(
        len(content_hash) == 64 and content_hash == _canonical_sha256(core),
        f"{label} content identity drifted",
    )
    return content_hash


def _run(argv: list[str], *, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        shell=False,
        timeout=timeout,
        check=False,
    )
    _require(
        completed.returncode == 0,
        f"command failed ({completed.returncode}): {argv!r}\n"
        f"{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}",
    )
    return completed


def _docker_inspect(kind: str, identity: str) -> dict[str, Any]:
    value = json.loads(_run(["docker", kind, "inspect", identity]).stdout)
    _require(isinstance(value, list) and len(value) == 1, f"docker {kind} inspect drifted")
    _require(isinstance(value[0], dict), f"docker {kind} inspect returned no object")
    return value[0]


def _verify_frozen_inputs() -> dict[str, Any]:
    config = _load_object(FROZEN_INPUTS, label="frozen OCI inputs")
    _require(
        config.get("schema_version") == "xinao.f4_oci_frozen_inputs.v1",
        "frozen input schema drifted",
    )
    _content_addressed(config, label="frozen OCI inputs")
    source_files = {
        "dockerfile_sha256": REPO_ROOT / "docker" / "f4-verifier" / "Dockerfile",
        "contract_writer_sha256": (
            REPO_ROOT / "docker" / "f4-verifier" / "write_execution_contract.py"
        ),
        "verifier_lock_sha256": REPO_ROOT / "docker" / "f4-verifier" / "uv.lock",
        "root_lock_sha256": REPO_ROOT / "uv.lock",
        "xinao_lock_sha256": REPO_ROOT / "xinao_discovery" / "uv.lock",
        "dual_brain_lock_sha256": (REPO_ROOT / "projects" / "dual-brain-coordination" / "uv.lock"),
        "runner_sha256": Path(__file__).resolve(),
        "builder_sha256": REPO_ROOT / "scripts" / "build_f4_snapshot_oci.py",
    }
    for field, path in source_files.items():
        _require(config.get(field) == _file_sha256(path), f"frozen source drifted: {field}")
    for prefix in ("authority", "data"):
        manifest = Path(str(config.get(f"{prefix}_manifest_path") or "")).resolve()
        value = _load_object(manifest, label=f"{prefix} manifest")
        _require(
            config.get(f"{prefix}_manifest_sha256") == _file_sha256(manifest)
            and config.get(f"{prefix}_content_sha256") == value.get("content_sha256"),
            f"frozen {prefix} identity drifted",
        )
    image_id = str(config.get("image_id") or "")
    _require(image_id.startswith("sha256:") and len(image_id) == 71, "fixed image ID is absent")
    _require(
        config.get("python_base_image") == PYTHON_BASE_IMAGE
        and config.get("uv_base_image") == UV_BASE_IMAGE,
        "fixed image base identity drifted",
    )
    build_receipt_path = Path(str(config.get("build_receipt_path") or "")).resolve()
    build_receipt = _load_object(build_receipt_path, label="image build receipt")
    _content_addressed(build_receipt, label="image build receipt")
    _require(
        build_receipt.get("schema_version") == "xinao.f4_oci_image_build_receipt.v1"
        and build_receipt.get("status") == "BUILT"
        and build_receipt.get("final_frozen_inputs_content_sha256") == config["content_sha256"]
        and build_receipt.get("image_id") == image_id
        and build_receipt.get("builder_sha256") == config["builder_sha256"]
        and build_receipt.get("runner_sha256") == config["runner_sha256"],
        "image build receipt drifted",
    )
    return config


def _verify_image(config: dict[str, Any]) -> dict[str, Any]:
    image = _docker_inspect("image", str(config["image_ref"]))
    _require(image.get("Id") == config["image_id"], "image tag no longer identifies frozen image")
    _require(
        sorted(str(item) for item in image.get("RepoDigests") or [])
        == sorted(str(item) for item in config.get("repo_digests") or []),
        "image repo digest set drifted",
    )
    image_config = image.get("Config")
    _require(isinstance(image_config, dict), "image Config is absent")
    _require(image_config.get("Entrypoint") == EXPECTED_ENTRYPOINT, "image entrypoint drifted")
    _require(image_config.get("Cmd") == EXPECTED_CMD, "image fixed run command drifted")
    _require(image_config.get("WorkingDir") == "/work", "image working directory drifted")
    _require(image_config.get("User") == "65532:65532", "image runtime user drifted")
    environment = image_config.get("Env")
    _require(isinstance(environment, list), "image environment is absent")
    _require(
        not any(str(item).upper().startswith("XINAO_F4_") for item in environment),
        "image contains an overridable XINAO_F4 runtime environment",
    )
    labels = image_config.get("Labels")
    _require(isinstance(labels, dict), "image labels are absent")
    expected_labels = {
        "io.xinao.f4.authority.manifest.sha256": config["authority_manifest_sha256"],
        "io.xinao.f4.authority.content.sha256": config["authority_content_sha256"],
        "io.xinao.f4.data.manifest.sha256": config["data_manifest_sha256"],
        "io.xinao.f4.data.content.sha256": config["data_content_sha256"],
        "io.xinao.f4.dockerfile.sha256": config["dockerfile_sha256"],
        "io.xinao.f4.contract-writer.sha256": config["contract_writer_sha256"],
        "io.xinao.f4.verifier-lock.sha256": config["verifier_lock_sha256"],
    }
    _require(
        all(labels.get(key) == value for key, value in expected_labels.items()),
        "image identity labels drifted",
    )
    return image


def _verify_postbuild(config: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    build_receipt_path = Path(str(config["build_receipt_path"])).resolve()
    path = build_receipt_path.parent / "image_build_fresh_verification.json"
    value = _load_object(path, label="post-build fresh verification")
    _content_addressed(value, label="post-build fresh verification")
    build_receipt = _load_object(build_receipt_path, label="image build receipt")
    _require(
        value.get("schema_version") == "xinao.f4_oci_image_build_fresh_verification.v1"
        and value.get("status") == "POSTBUILD_VERIFIED"
        and value.get("final_frozen_inputs_content_sha256") == config["content_sha256"]
        and value.get("build_receipt_sha256") == _file_sha256(build_receipt_path)
        and value.get("build_receipt_content_sha256") == build_receipt["content_sha256"]
        and value.get("image_id") == config["image_id"],
        "post-build fresh verification drifted",
    )
    return path, value


def _mount_rows(container: dict[str, Any]) -> list[dict[str, Any]]:
    mounts = container.get("Mounts")
    _require(isinstance(mounts, list), "container mounts are absent")
    rows = [
        {
            "type": str(item.get("Type") or ""),
            "source": str(item.get("Source") or ""),
            "destination": str(item.get("Destination") or ""),
            "rw": bool(item.get("RW")),
        }
        for item in mounts
        if isinstance(item, dict)
    ]
    rows.sort(key=lambda item: item["destination"])
    return rows


def _verify_created_container(
    container: dict[str, Any],
    *,
    config: dict[str, Any],
    output_dir: Path,
    data_root: Path | None = None,
) -> dict[str, Any]:
    host = container.get("HostConfig")
    runtime = container.get("Config")
    _require(isinstance(host, dict) and isinstance(runtime, dict), "container config is absent")
    _require(container.get("Image") == config["image_id"], "container image ID drifted")
    _require(runtime.get("Entrypoint") == EXPECTED_ENTRYPOINT, "container entrypoint drifted")
    _require(runtime.get("Cmd") == EXPECTED_CMD, "container command drifted")
    _require(host.get("ReadonlyRootfs") is True, "container root filesystem is writable")
    _require(host.get("NetworkMode") == "none", "container network is not disabled")
    _require(host.get("CapDrop") == ["ALL"], "container capabilities were not dropped")
    security = host.get("SecurityOpt")
    _require(
        isinstance(security, list)
        and any(str(item).startswith("no-new-privileges") for item in security),
        "container no-new-privileges is absent",
    )
    _require(runtime.get("User") == "65532:65532", "container runtime user drifted")
    _require(runtime.get("WorkingDir") == "/work", "container working directory drifted")
    _require(host.get("PidsLimit") == 256, "container PID limit drifted")
    tmpfs = host.get("Tmpfs")
    _require(isinstance(tmpfs, dict) and set(tmpfs) == {"/tmp"}, "fresh /tmp tmpfs is absent")
    _require(
        all(token in str(tmpfs["/tmp"]) for token in ("rw", "noexec", "nosuid", "nodev")),
        "fresh /tmp tmpfs options drifted",
    )
    execution_data_root = (
        data_root.resolve()
        if data_root is not None
        else Path(str(config["data_manifest_path"])).resolve().parent
    )
    mounts = _mount_rows(container)
    _require(
        mounts
        == [
            {
                "type": "bind",
                "source": str(execution_data_root),
                "destination": "/capsule",
                "rw": False,
            },
            {
                "type": "bind",
                "source": str(output_dir.resolve()),
                "destination": "/output",
                "rw": True,
            },
        ],
        "container mount inventory drifted",
    )
    environment = runtime.get("Env")
    _require(
        isinstance(environment, list)
        and not any(str(item).upper().startswith("XINAO_F4_") for item in environment),
        "container received an XINAO_F4 environment override",
    )
    return {
        "readonly_rootfs": True,
        "network_mode": "none",
        "cap_drop": ["ALL"],
        "security_opt": sorted(str(item) for item in security),
        "tmpfs": {"/tmp": str(tmpfs["/tmp"])},
        "mounts": mounts,
        "entrypoint": list(EXPECTED_ENTRYPOINT),
        "cmd": list(EXPECTED_CMD),
        "user": "65532:65532",
        "working_dir": "/work",
        "pids_limit": 256,
        "xinao_f4_environment_count": 0,
    }


def _output_inventory(root: Path) -> list[dict[str, Any]]:
    rows = [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": _file_sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(
            (candidate for candidate in root.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(root).as_posix(),
        )
    ]
    paths = {str(item["relative_path"]) for item in rows}
    _require(EXPECTED_TOP_LEVEL_FILES <= paths, "stage0 output files are incomplete")
    _require(
        paths == EXPECTED_TOP_LEVEL_FILES and len(rows) == 3,
        "semantic output file inventory is not exactly the sealed three-file set",
    )
    stage0 = _load_object(root / "stage0_result.json", label="stage0 result")
    _content_addressed(stage0, label="stage0 result")
    _require(
        stage0.get("status") == "VERIFIED"
        and stage0.get("assertion_count") == 14
        and stage0.get("fallback_count") == 0,
        "stage0 semantic result drifted",
    )
    bundle_path = root / "f4_assertion_actual_bundle.v2.json"
    bundle = _load_object(bundle_path, label="F4 assertion bundle")
    _content_addressed(bundle, label="F4 assertion bundle")
    actuals = bundle.get("assertion_actuals")
    bundle_ref = stage0.get("common_assertion_bundle")
    _require(
        bundle.get("schema_version") == "xinao.assertion_actual_bundle.v2"
        and bundle.get("block_id") == "F4_research_factory"
        and isinstance(actuals, dict)
        and len(actuals) == 14
        and all(value is True for value in actuals.values())
        and isinstance(bundle_ref, dict)
        and bundle_ref.get("sha256") == _file_sha256(bundle_path)
        and bundle_ref.get("size_bytes") == bundle_path.stat().st_size
        and bundle_ref.get("content_sha256") == bundle["content_sha256"],
        "stage0 F4 assertion bundle binding drifted",
    )
    authority_projection = stage0.get("common_authority_projection")
    _require(
        isinstance(authority_projection, dict)
        and authority_projection.get("schema_version") == "xinao.f4_common_authority_projection.v1"
        and authority_projection.get("status") == "VERIFIED",
        "stage0 common authority projection is absent",
    )
    trace = _load_object(root / "snapshot_trace_summary.json", label="snapshot trace summary")
    _content_addressed(trace, label="snapshot trace summary")
    _require(
        trace.get("status") == "VERIFIED"
        and trace.get("fallback_count") == 0
        and int(trace.get("process_count", 0)) >= 5,
        "snapshot trace summary drifted",
    )
    return rows


def _host_sentinel_bindings() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, path in HOST_SENTINEL_PATHS.items():
        _require(path.is_file(), f"existing host sentinel is missing: {path}")
        rows.append(
            {
                "label": label,
                "path": str(path.resolve()),
                "sha256": _file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return rows


def _one_run(
    *,
    ordinal: int,
    config: dict[str, Any],
    output_parent: Path,
    data_root: Path,
) -> dict[str, Any]:
    output_dir = output_parent / f"run-{ordinal}"
    _require(not output_dir.exists(), f"run output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    name = f"xinao-f4-oci-{uuid.uuid4().hex[:16]}"
    capsule = data_root
    argv = [
        "docker",
        "create",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "--mount",
        f"type=bind,src={capsule},dst=/capsule,readonly",
        "--mount",
        f"type=bind,src={output_dir.resolve()},dst=/output",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=268435456",
        str(config["image_id"]),
    ]
    container_id = _run(argv).stdout.strip()
    _require(container_id, "docker create returned no container ID")
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    stdout = ""
    stderr = ""
    try:
        before = _docker_inspect("container", container_id)
        isolation = _verify_created_container(
            before,
            config=config,
            output_dir=output_dir,
            data_root=data_root,
        )
        started = _run(["docker", "start", "-a", container_id])
        stdout = started.stdout
        stderr = started.stderr
        after = _docker_inspect("container", container_id)
        state = after.get("State")
        _require(isinstance(state, dict), "container exit state is absent")
        _require(
            state.get("Status") == "exited"
            and state.get("ExitCode") == 0
            and state.get("OOMKilled") is False,
            f"container did not exit cleanly: {state}",
        )
        inventory = _output_inventory(output_dir)
        stage0_result = _load_object(output_dir / "stage0_result.json", label="stage0 result")
        return {
            "ordinal": ordinal,
            "container_id": container_id,
            "output_ref": str(output_dir.resolve()),
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
            "exit_code": 0,
            "isolation": isolation,
            "semantic_output_file_count": len(inventory),
            "semantic_output_inventory": inventory,
            "semantic_output_set_sha256": _canonical_sha256(inventory),
            "runtime_negative_probes": stage0_result["preflight"]["isolation_negative_probes"],
        }
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_id],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            shell=False,
            timeout=120,
            check=False,
        )


def run_fixed(*, output_parent: Path, data_root: Path | None = None) -> Path:
    config = _verify_frozen_inputs()
    postbuild_path, postbuild = _verify_postbuild(config)
    execution_data_root = _admit_execution_data_root(config, data_root)
    output_parent = _validate_output_parent(
        output_parent,
        config,
        data_root=execution_data_root,
    )
    image = _verify_image(config)
    output_parent.mkdir(parents=True)
    sentinels = _host_sentinel_bindings()
    first = _one_run(
        ordinal=1,
        config=config,
        output_parent=output_parent,
        data_root=execution_data_root,
    )
    second = _one_run(
        ordinal=2,
        config=config,
        output_parent=output_parent,
        data_root=execution_data_root,
    )
    _require(
        first["semantic_output_inventory"] == second["semantic_output_inventory"],
        "isolated semantic outputs are not byte-identical",
    )
    core = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "VERIFIED",
        "captured_at": datetime.now(UTC).isoformat(),
        "frozen_inputs_content_sha256": config["content_sha256"],
        "runner_sha256": config["runner_sha256"],
        "builder_sha256": config["builder_sha256"],
        "image_build_receipt": {
            "path": config["build_receipt_path"],
            "sha256": _file_sha256(Path(config["build_receipt_path"])),
            "content_sha256": _load_object(
                Path(config["build_receipt_path"]), label="image build receipt"
            )["content_sha256"],
        },
        "postbuild_fresh_verification": {
            "path": str(postbuild_path),
            "sha256": _file_sha256(postbuild_path),
            "content_sha256": postbuild["content_sha256"],
        },
        "host_sentinels": sentinels,
        "image": {
            "ref": config["image_ref"],
            "id": config["image_id"],
            "repo_digests": sorted(str(item) for item in image.get("RepoDigests") or []),
        },
        "authority_manifest_sha256": config["authority_manifest_sha256"],
        "authority_content_sha256": config["authority_content_sha256"],
        "data_manifest_sha256": config["data_manifest_sha256"],
        "data_content_sha256": config["data_content_sha256"],
        "source_lock_lineage": {
            "root_lock_sha256": config["root_lock_sha256"],
            "xinao_lock_sha256": config["xinao_lock_sha256"],
            "dual_brain_lock_sha256": config["dual_brain_lock_sha256"],
            "verifier_lock_sha256": config["verifier_lock_sha256"],
        },
        "run_count": 2,
        "runs": [first, second],
        "semantic_output_byte_identical": True,
        "semantic_output_set_sha256": first["semantic_output_set_sha256"],
        "assertion_count": 14,
        "fallback_count": 0,
        "network_mode": "none",
        "readonly_rootfs": True,
        "data_mount_readonly": True,
        "authority_mount_count": 0,
        "host_xinao_f4_environment_forward_count": 0,
    }
    receipt = {**core, "content_sha256": _canonical_sha256(core)}
    path = output_parent / "execution_capsule_receipt.json"
    path.write_bytes(_canonical_bytes(receipt))
    return path


def verify_execution_receipt(path: Path) -> dict[str, Any]:
    """Revalidate one OCI receipt and both sealed output trees from bytes."""

    receipt_path = path.resolve()
    receipt = _load_object(receipt_path, label="execution receipt")
    _content_addressed(receipt, label="execution receipt")
    runs = receipt.get("runs")
    _require(
        receipt.get("schema_version") == RECEIPT_SCHEMA
        and receipt.get("status") == "VERIFIED"
        and receipt.get("run_count") == 2
        and isinstance(runs, list)
        and len(runs) == 2
        and receipt.get("semantic_output_byte_identical") is True
        and receipt.get("assertion_count") == 14
        and receipt.get("fallback_count") == 0
        and receipt.get("network_mode") == "none"
        and receipt.get("readonly_rootfs") is True
        and receipt.get("data_mount_readonly") is True
        and receipt.get("authority_mount_count") == 0
        and receipt.get("host_xinao_f4_environment_forward_count") == 0,
        "execution receipt terminal contract drifted",
    )
    observed: list[list[dict[str, Any]]] = []
    for ordinal, raw in enumerate(runs, start=1):
        _require(isinstance(raw, dict), "execution receipt run row is invalid")
        run = dict(raw)
        isolation = run.get("isolation")
        _require(
            run.get("ordinal") == ordinal
            and run.get("exit_code") == 0
            and isinstance(isolation, dict)
            and isolation.get("readonly_rootfs") is True
            and isolation.get("network_mode") == "none"
            and isolation.get("cap_drop") == ["ALL"]
            and "no-new-privileges" in " ".join(isolation.get("security_opt") or [])
            and isolation.get("xinao_f4_environment_count") == 0,
            "execution receipt isolation proof drifted",
        )
        output_root = Path(str(run.get("output_ref") or "")).resolve()
        inventory = _output_inventory(output_root)
        _require(
            inventory == run.get("semantic_output_inventory")
            and len(inventory) == run.get("semantic_output_file_count")
            and _canonical_sha256(inventory) == run.get("semantic_output_set_sha256"),
            "execution receipt output inventory drifted",
        )
        observed.append(inventory)
    _require(
        observed[0] == observed[1]
        and receipt.get("semantic_output_set_sha256") == _canonical_sha256(observed[0]),
        "execution receipt outputs are not byte-identical",
    )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-parent", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        path = run_fixed(output_parent=args.output_parent)
    except (OciRunnerError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False))
        return 1
    receipt = _load_object(path, label="execution receipt")
    print(
        json.dumps(
            {
                "status": "VERIFIED",
                "execution_receipt_ref": str(path),
                "content_sha256": receipt["content_sha256"],
                "image_id": receipt["image"]["id"],
                "semantic_output_set_sha256": receipt["semantic_output_set_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
