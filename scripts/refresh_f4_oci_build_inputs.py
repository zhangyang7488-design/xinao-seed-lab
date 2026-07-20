#!/usr/bin/env python3
"""Refresh the exact content-addressed inputs consumed by the F4 OCI builder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

if __package__:
    from scripts import build_f4_snapshot_oci as oci
else:
    import build_f4_snapshot_oci as oci


SCHEMA_VERSION = "xinao.f4_oci_build_inputs.v1"
AUTHORITY_SCHEMA = "xinao.f4_authority_source_pack.v2"
DATA_SCHEMA = "xinao.evidence_snapshot.v1"
DEFAULT_IMAGE_REPOSITORY = "xinao/f4-verifier"


def _manifest_identity(
    path: Path,
    *,
    label: str,
    schema_version: str,
) -> tuple[dict[str, Any], str, str]:
    value = oci._load_object(path, label=label)
    oci._require(
        value.get("schema_version") == schema_version,
        f"{label} schema drifted",
    )
    content_sha256 = oci._content_addressed(value, label=label)
    return value, oci._file_sha256(path), content_sha256


def refresh_build_inputs(
    *,
    authority_manifest: Path,
    data_manifest: Path,
    output_path: Path = oci.BUILD_INPUTS,
    image_repository: str = DEFAULT_IMAGE_REPOSITORY,
) -> dict[str, Any]:
    """Write one deterministic pre-build identity file from live sealed inputs."""

    authority_path = authority_manifest.resolve()
    data_path = data_manifest.resolve()
    output = output_path.resolve()
    repository = image_repository.strip()
    oci._require(repository and ":" not in repository, "image repository is invalid")

    _, authority_file_sha256, authority_content_sha256 = _manifest_identity(
        authority_path,
        label="authority manifest",
        schema_version=AUTHORITY_SCHEMA,
    )
    _, data_file_sha256, data_content_sha256 = _manifest_identity(
        data_path,
        label="data manifest",
        schema_version=DATA_SCHEMA,
    )
    source_files = oci._source_files()
    protected = {authority_path, data_path, *(path.resolve() for path in source_files.values())}
    oci._require(output not in protected, "build-input output overlaps one of its inputs")

    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "image_ref": (f"{repository}:{authority_content_sha256[:8]}-{data_content_sha256[:8]}"),
        "authority_manifest_path": str(authority_path),
        "authority_manifest_sha256": authority_file_sha256,
        "authority_content_sha256": authority_content_sha256,
        "data_manifest_path": str(data_path),
        "data_manifest_sha256": data_file_sha256,
        "data_content_sha256": data_content_sha256,
        **{field: oci._file_sha256(path) for field, path in source_files.items()},
        "python_base_image": oci.PYTHON_BASE_IMAGE,
        "uv_base_image": oci.UV_BASE_IMAGE,
    }
    result = {**core, "content_sha256": oci._canonical_sha256(core)}

    # Refuse to publish a mixed observation if an input changed during generation.
    _, authority_file_after, authority_content_after = _manifest_identity(
        authority_path,
        label="authority manifest",
        schema_version=AUTHORITY_SCHEMA,
    )
    _, data_file_after, data_content_after = _manifest_identity(
        data_path,
        label="data manifest",
        schema_version=DATA_SCHEMA,
    )
    source_hashes_after = {field: oci._file_sha256(path) for field, path in source_files.items()}
    oci._require(
        authority_file_after == authority_file_sha256
        and authority_content_after == authority_content_sha256
        and data_file_after == data_file_sha256
        and data_content_after == data_content_sha256
        and all(result[field] == value for field, value in source_hashes_after.items()),
        "F4 OCI build inputs drifted during refresh",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    oci._atomic_write(output, result)
    observed = oci._load_object(output, label="refreshed build inputs")
    oci._require(observed == result, "refreshed build inputs changed after publish")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-manifest", type=Path, required=True)
    parser.add_argument("--data-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=oci.BUILD_INPUTS)
    parser.add_argument("--image-repository", default=DEFAULT_IMAGE_REPOSITORY)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        value = refresh_build_inputs(
            authority_manifest=args.authority_manifest,
            data_manifest=args.data_manifest,
            output_path=args.output,
            image_repository=args.image_repository,
        )
    except (OSError, ValueError, oci.OciBuildError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "REFRESHED",
                "output_path": str(args.output.resolve()),
                "image_ref": value["image_ref"],
                "content_sha256": value["content_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
