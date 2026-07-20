from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import build_f4_snapshot_oci as oci
from scripts import refresh_f4_oci_build_inputs as subject


def _write_manifest(path: Path, *, schema_version: str, marker: str) -> Path:
    core = {"schema_version": schema_version, "marker": marker}
    value = {**core, "content_sha256": oci._canonical_sha256(core)}
    path.write_bytes(oci._canonical_bytes(value))
    return path


def _source_files(tmp_path: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for index, field in enumerate(oci._source_files()):
        path = tmp_path / "sources" / f"{field}.{index}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"sealed-{field}".encode())
        paths[field] = path
    return paths


def test_refresh_derives_every_build_identity_and_is_byte_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _write_manifest(
        tmp_path / "authority.json",
        schema_version=subject.AUTHORITY_SCHEMA,
        marker="authority",
    )
    data = _write_manifest(
        tmp_path / "snapshot_manifest.json",
        schema_version=subject.DATA_SCHEMA,
        marker="data",
    )
    source_files = _source_files(tmp_path)
    monkeypatch.setattr(oci, "_source_files", lambda: dict(source_files))
    output = tmp_path / "build_inputs.v1.json"

    first = subject.refresh_build_inputs(
        authority_manifest=authority,
        data_manifest=data,
        output_path=output,
    )
    first_bytes = output.read_bytes()
    second = subject.refresh_build_inputs(
        authority_manifest=authority,
        data_manifest=data,
        output_path=output,
    )

    assert first == second
    assert output.read_bytes() == first_bytes == oci._canonical_bytes(first)
    assert first["schema_version"] == subject.SCHEMA_VERSION
    assert first["image_ref"] == (
        "xinao/f4-verifier:"
        f"{first['authority_content_sha256'][:8]}-{first['data_content_sha256'][:8]}"
    )
    assert first["authority_manifest_sha256"] == oci._file_sha256(authority)
    assert first["data_manifest_sha256"] == oci._file_sha256(data)
    assert all(first[field] == oci._file_sha256(path) for field, path in source_files.items())
    core = dict(first)
    assert core.pop("content_sha256") == oci._canonical_sha256(core)
    monkeypatch.setattr(oci, "BUILD_INPUTS", output)
    assert oci._verify_build_inputs() == first


def test_refresh_rejects_manifest_content_drift_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _write_manifest(
        tmp_path / "authority.json",
        schema_version=subject.AUTHORITY_SCHEMA,
        marker="authority",
    )
    data = _write_manifest(
        tmp_path / "snapshot_manifest.json",
        schema_version=subject.DATA_SCHEMA,
        marker="data",
    )
    source_files = _source_files(tmp_path)
    monkeypatch.setattr(oci, "_source_files", lambda: dict(source_files))
    tampered = json.loads(data.read_text(encoding="utf-8"))
    tampered["marker"] = "tampered-without-reseal"
    data.write_text(json.dumps(tampered), encoding="utf-8")
    output = tmp_path / "build_inputs.v1.json"

    with pytest.raises(oci.OciBuildError, match="content identity drifted"):
        subject.refresh_build_inputs(
            authority_manifest=authority,
            data_manifest=data,
            output_path=output,
        )

    assert not output.exists()


def test_refresh_cli_metadata_never_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "refresh_build_inputs",
        lambda **kwargs: pytest.fail(f"metadata argument wrote build inputs: {kwargs}"),
    )

    with pytest.raises(SystemExit) as raised:
        subject.main(["--help"])

    assert raised.value.code == 0
