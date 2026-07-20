#!/usr/bin/env python3
"""Build, inspect, and atomically freeze the fixed F4 verifier image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKER_CONTEXT = REPO_ROOT / "docker" / "f4-verifier"
DOCKERFILE = DOCKER_CONTEXT / "Dockerfile"
BUILD_INPUTS = DOCKER_CONTEXT / "build_inputs.v1.json"
FROZEN_INPUTS = DOCKER_CONTEXT / "frozen_inputs.v1.json"
EVIDENCE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence")
PYTHON_BASE_IMAGE = (
    "python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf"
)
UV_BASE_IMAGE = (
    "ghcr.io/astral-sh/uv@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa"
)


class OciBuildError(RuntimeError):
    """Raised when frozen inputs or the built image identity drift."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise OciBuildError(message)


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


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    _require(path.is_file(), f"{label} is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{label} is not an object: {path}")
    return value


def _content_addressed(value: dict[str, Any], *, label: str) -> str:
    core = dict(value)
    content_hash = str(core.pop("content_sha256", ""))
    _require(
        len(content_hash) == 64 and _canonical_sha256(core) == content_hash,
        f"{label} content identity drifted",
    )
    return content_hash


def _source_files() -> dict[str, Path]:
    return {
        "dockerfile_sha256": DOCKERFILE,
        "contract_writer_sha256": DOCKER_CONTEXT / "write_execution_contract.py",
        "verifier_lock_sha256": DOCKER_CONTEXT / "uv.lock",
        "root_lock_sha256": REPO_ROOT / "uv.lock",
        "xinao_lock_sha256": REPO_ROOT / "xinao_discovery" / "uv.lock",
        "dual_brain_lock_sha256": (REPO_ROOT / "projects" / "dual-brain-coordination" / "uv.lock"),
        "runner_sha256": REPO_ROOT / "scripts" / "run_f4_snapshot_oci.py",
        "builder_sha256": Path(__file__).resolve(),
    }


def _verify_build_inputs() -> dict[str, Any]:
    config = _load_object(BUILD_INPUTS, label="pre-build frozen inputs")
    _require(
        config.get("schema_version") == "xinao.f4_oci_build_inputs.v1",
        "pre-build input schema drifted",
    )
    _content_addressed(config, label="pre-build frozen inputs")
    _require(
        all(config.get(field) == _file_sha256(path) for field, path in _source_files().items()),
        "pre-build source identity drifted",
    )
    authority_manifest = Path(str(config["authority_manifest_path"])).resolve()
    data_manifest = Path(str(config["data_manifest_path"])).resolve()
    authority = _load_object(authority_manifest, label="authority manifest")
    data = _load_object(data_manifest, label="data manifest")
    _require(
        config.get("authority_manifest_sha256") == _file_sha256(authority_manifest)
        and config.get("authority_content_sha256") == authority.get("content_sha256"),
        "pre-build authority identity drifted",
    )
    _require(
        config.get("data_manifest_sha256") == _file_sha256(data_manifest)
        and config.get("data_content_sha256") == data.get("content_sha256"),
        "pre-build data identity drifted",
    )
    _require(
        config.get("python_base_image") == PYTHON_BASE_IMAGE
        and config.get("uv_base_image") == UV_BASE_IMAGE,
        "pre-build image base identity drifted",
    )
    return config


def _run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
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
        f"{completed.stdout[-3000:]}\n{completed.stderr[-3000:]}",
    )
    return completed


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    _require(not temporary.exists(), f"atomic staging path exists: {temporary}")
    temporary.write_bytes(_canonical_bytes(value))
    os.replace(temporary, path)


def _write_immutable(path: Path, value: dict[str, Any]) -> None:
    rendered = _canonical_bytes(value)
    if path.exists():
        _require(path.read_bytes() == rendered, f"immutable evidence identity conflict: {path}")
        return
    path.write_bytes(rendered)


def _fresh_runner_verify() -> dict[str, Any]:
    bootstrap = (
        "import json,sys;"
        f"sys.path.insert(0,{str(REPO_ROOT)!r});"
        "from scripts.run_f4_snapshot_oci import _verify_frozen_inputs,_verify_image;"
        "value=_verify_frozen_inputs();"
        "image=_verify_image(value);"
        "print(json.dumps({'content_sha256':value['content_sha256'],"
        "'image_id':value['image_id'],'repo_digests':sorted(image.get('RepoDigests') or [])},"
        "sort_keys=True))"
    )
    completed = _run([sys.executable, "-I", "-c", bootstrap], timeout=120)
    value = json.loads(completed.stdout.splitlines()[-1])
    _require(isinstance(value, dict), "fresh runner verification returned no object")
    return value


def _build_argv(config: dict[str, Any], authority_root: Path) -> list[str]:
    build_args = {
        "AUTHORITY_MANIFEST_SHA256": config["authority_manifest_sha256"],
        "AUTHORITY_CONTENT_SHA256": config["authority_content_sha256"],
        "DATA_MANIFEST_SHA256": config["data_manifest_sha256"],
        "DATA_CONTENT_SHA256": config["data_content_sha256"],
        "DOCKERFILE_SHA256": config["dockerfile_sha256"],
        "CONTRACT_WRITER_SHA256": config["contract_writer_sha256"],
        "VERIFIER_LOCK_SHA256": config["verifier_lock_sha256"],
    }
    argv = [
        "docker",
        "buildx",
        "build",
        "--load",
        "--file",
        str(DOCKERFILE),
        "--tag",
        str(config["image_ref"]),
        "--build-context",
        f"authority={authority_root}",
    ]
    for key, value in build_args.items():
        argv.extend(("--build-arg", f"{key}={value}"))
    argv.append(str(DOCKER_CONTEXT))
    return argv


def _write_postbuild_verification(
    *,
    config: dict[str, Any],
    final: dict[str, Any],
    receipt: dict[str, Any],
    receipt_path: Path,
    image_id: str,
    repo_digests: list[str],
) -> tuple[Path, dict[str, Any]]:
    fresh = _fresh_runner_verify()
    _require(
        fresh
        == {
            "content_sha256": final["content_sha256"],
            "image_id": image_id,
            "repo_digests": repo_digests,
        },
        "fresh runner did not accept final frozen identities",
    )
    verification_core = {
        "schema_version": "xinao.f4_oci_image_build_fresh_verification.v1",
        "status": "POSTBUILD_VERIFIED",
        "final_frozen_inputs_ref": str(FROZEN_INPUTS.resolve()),
        "final_frozen_inputs_sha256": _file_sha256(FROZEN_INPUTS),
        "final_frozen_inputs_content_sha256": final["content_sha256"],
        "build_receipt_ref": str(receipt_path),
        "build_receipt_sha256": _file_sha256(receipt_path),
        "build_receipt_content_sha256": receipt["content_sha256"],
        "image_ref": config["image_ref"],
        "image_id": image_id,
        "repo_digests": repo_digests,
        "fresh_process_frozen_and_image_verification": fresh,
    }
    verification = {
        **verification_core,
        "content_sha256": _canonical_sha256(verification_core),
    }
    verification_path = receipt_path.parent / "image_build_fresh_verification.json"
    _write_immutable(verification_path, verification)
    return verification_path, verification


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build, inspect, and atomically freeze the fixed F4 verifier image."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv)
    try:
        config = _verify_build_inputs()
        authority_root = Path(str(config["authority_manifest_path"])).resolve().parent
        argv = _build_argv(config, authority_root)
        _run(argv, timeout=3600)
        rows = json.loads(
            _run(["docker", "image", "inspect", str(config["image_ref"])], timeout=120).stdout
        )
        _require(isinstance(rows, list) and len(rows) == 1, "built image inspect drifted")
        image = rows[0]
        _require(isinstance(image, dict), "built image inspect returned no object")
        image_id = str(image.get("Id") or "")
        _require(image_id.startswith("sha256:") and len(image_id) == 71, "image ID is invalid")
        repo_digests = sorted(str(item) for item in image.get("RepoDigests") or [])
        receipt_path = (
            EVIDENCE_ROOT
            / (
                f"xinao-f4-oci-image-build-{image_id.removeprefix('sha256:')[:16]}-"
                f"{config['content_sha256'][:12]}"
            )
            / "image_build_receipt.json"
        )
        final_core = {
            **{key: value for key, value in config.items() if key != "content_sha256"},
            "schema_version": "xinao.f4_oci_frozen_inputs.v1",
            "prebuild_inputs_ref": str(BUILD_INPUTS.resolve()),
            "prebuild_inputs_sha256": _file_sha256(BUILD_INPUTS),
            "prebuild_inputs_content_sha256": config["content_sha256"],
            "image_id": image_id,
            "repo_digests": repo_digests,
            "build_receipt_path": str(receipt_path),
        }
        final = {**final_core, "content_sha256": _canonical_sha256(final_core)}
        _atomic_write(FROZEN_INPUTS, final)

        receipt_core = {
            "schema_version": "xinao.f4_oci_image_build_receipt.v1",
            "status": "BUILT",
            "prebuild_inputs_ref": str(BUILD_INPUTS.resolve()),
            "prebuild_inputs_sha256": _file_sha256(BUILD_INPUTS),
            "prebuild_inputs_content_sha256": config["content_sha256"],
            "final_frozen_inputs_ref": str(FROZEN_INPUTS.resolve()),
            "final_frozen_inputs_sha256": _file_sha256(FROZEN_INPUTS),
            "final_frozen_inputs_content_sha256": final["content_sha256"],
            "image_ref": config["image_ref"],
            "image_id": image_id,
            "repo_digests": repo_digests,
            "authority_manifest_sha256": config["authority_manifest_sha256"],
            "authority_content_sha256": config["authority_content_sha256"],
            "data_manifest_sha256": config["data_manifest_sha256"],
            "data_content_sha256": config["data_content_sha256"],
            "dockerfile_sha256": config["dockerfile_sha256"],
            "contract_writer_sha256": config["contract_writer_sha256"],
            "verifier_lock_sha256": config["verifier_lock_sha256"],
            "builder_sha256": config["builder_sha256"],
            "runner_sha256": config["runner_sha256"],
            "authority_named_build_context": str(authority_root),
            "base_images_overridden": False,
            "build_argv": argv,
        }
        receipt = {**receipt_core, "content_sha256": _canonical_sha256(receipt_core)}
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        _write_immutable(receipt_path, receipt)
        verification_path, verification = _write_postbuild_verification(
            config=config,
            final=final,
            receipt=receipt,
            receipt_path=receipt_path,
            image_id=image_id,
            repo_digests=repo_digests,
        )
        print(
            json.dumps(
                {
                    "status": "BUILT_AND_FROZEN",
                    "image_ref": config["image_ref"],
                    "image_id": image_id,
                    "repo_digests": repo_digests,
                    "frozen_inputs_ref": str(FROZEN_INPUTS),
                    "frozen_inputs_content_sha256": final["content_sha256"],
                    "build_receipt_ref": str(receipt_path),
                    "build_receipt_content_sha256": receipt["content_sha256"],
                    "fresh_verification_ref": str(verification_path),
                    "fresh_verification_content_sha256": verification["content_sha256"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (OciBuildError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
