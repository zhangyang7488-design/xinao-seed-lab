from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest
from scripts import f4_portable_closure as portable


def _write(path: Path, body: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _canonical(path: Path, value: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(portable._canonical_bytes(value))
    return path


def _add_tar_bytes(archive: tarfile.TarFile, name: str, body: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(body)
    archive.addfile(member, io.BytesIO(body))


def _descriptor(
    body: bytes,
    media_type: str,
    *,
    platform: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "mediaType": media_type,
        "digest": f"sha256:{hashlib.sha256(body).hexdigest()}",
        "size": len(body),
    }
    if platform is not None:
        value["platform"] = platform
    if annotations is not None:
        value["annotations"] = annotations
    return value


def _blob_member(descriptor: dict[str, object]) -> str:
    return f"blobs/sha256/{str(descriptor['digest']).removeprefix('sha256:')}"


def _docker_tar(
    path: Path,
    *,
    extra: tuple[str, bytes] | None = None,
    link: str | None = None,
    nested_index: bool = False,
    nested_depth: int = 0,
    include_attestation: bool = False,
    duplicate_runnable: bool = False,
    descriptor_tamper: str | None = None,
    repo_tags: list[str] | None = None,
    layout_version: str = "1.0.0",
    root_schema_version: int = 2,
    root_media_type: str = "application/vnd.oci.image.index.v1+json",
) -> str:
    image_ref = "example/f4:test"
    config = portable._canonical_bytes({"architecture": "amd64", "os": "linux"})
    config_descriptor = _descriptor(config, "application/vnd.oci.image.config.v1+json")
    layer = b"sealed-layer"
    layer_descriptor = _descriptor(layer, "application/vnd.oci.image.layer.v1.tar")
    runnable = portable._canonical_bytes(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": config_descriptor,
            "layers": [layer_descriptor],
        }
    )
    runnable_descriptor = _descriptor(
        runnable,
        "application/vnd.oci.image.manifest.v1+json",
        platform={"architecture": "amd64", "os": "linux"},
    )
    subject_descriptor = dict(runnable_descriptor)
    blobs: dict[str, bytes] = {
        _blob_member(config_descriptor): config,
        _blob_member(layer_descriptor): layer,
        _blob_member(runnable_descriptor): runnable,
    }
    effective_depth = nested_depth or (1 if nested_index else 0)
    if effective_depth:
        manifests = [runnable_descriptor]
        if duplicate_runnable:
            duplicate = portable._canonical_bytes(
                {
                    "schemaVersion": 2,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": config_descriptor,
                    "layers": [layer_descriptor],
                    "annotations": {"test.example/duplicate": "true"},
                }
            )
            duplicate_descriptor = _descriptor(
                duplicate,
                "application/vnd.oci.image.manifest.v1+json",
                platform={"architecture": "amd64", "os": "linux"},
            )
            manifests.append(duplicate_descriptor)
            blobs[_blob_member(duplicate_descriptor)] = duplicate
        if include_attestation:
            empty_config = b"{}"
            empty_descriptor = _descriptor(empty_config, "application/vnd.oci.empty.v1+json")
            attestation_layer = b"attestation"
            attestation_layer_descriptor = _descriptor(
                attestation_layer, "application/vnd.in-toto+json"
            )
            attestation = portable._canonical_bytes(
                {
                    "schemaVersion": 2,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": empty_descriptor,
                    "layers": [attestation_layer_descriptor],
                    "subject": {
                        key: runnable_descriptor[key] for key in ("mediaType", "digest", "size")
                    },
                }
            )
            attestation_descriptor = _descriptor(
                attestation,
                "application/vnd.oci.image.manifest.v1+json",
                platform={"architecture": "unknown", "os": "unknown"},
                annotations={"vnd.docker.reference.type": "attestation-manifest"},
            )
            manifests.append(attestation_descriptor)
            blobs.update(
                {
                    _blob_member(empty_descriptor): empty_config,
                    _blob_member(attestation_layer_descriptor): attestation_layer,
                    _blob_member(attestation_descriptor): attestation,
                }
            )
        nested = portable._canonical_bytes(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": manifests,
            }
        )
        subject_descriptor = _descriptor(nested, "application/vnd.oci.image.index.v1+json")
        blobs[_blob_member(subject_descriptor)] = nested
        for _ in range(1, effective_depth):
            nested = portable._canonical_bytes(
                {
                    "schemaVersion": 2,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                    "manifests": [subject_descriptor],
                }
            )
            subject_descriptor = _descriptor(nested, "application/vnd.oci.image.index.v1+json")
            blobs[_blob_member(subject_descriptor)] = nested
    image_id = str(subject_descriptor["digest"])
    if descriptor_tamper == "digest":
        subject_descriptor["digest"] = f"sha256:{'0' * 64}"
    elif descriptor_tamper == "uppercase":
        subject_descriptor["digest"] = str(subject_descriptor["digest"]).upper()
    elif descriptor_tamper == "size":
        subject_descriptor["size"] = int(subject_descriptor["size"]) + 1
    index = portable._canonical_bytes(
        {
            "schemaVersion": root_schema_version,
            "mediaType": root_media_type,
            "manifests": [subject_descriptor],
        }
    )
    legacy_manifest = portable._canonical_bytes(
        [
            {
                "Config": _blob_member(config_descriptor),
                "RepoTags": [image_ref] if repo_tags is None else repo_tags,
                "Layers": [_blob_member(layer_descriptor)],
            }
        ]
    )
    with tarfile.open(path, mode="w") as archive:
        _add_tar_bytes(
            archive,
            "oci-layout",
            portable._canonical_bytes({"imageLayoutVersion": layout_version}),
        )
        _add_tar_bytes(archive, "index.json", index)
        _add_tar_bytes(archive, "manifest.json", legacy_manifest)
        for member_name, body in sorted(blobs.items()):
            _add_tar_bytes(archive, member_name, body)
        if extra is not None:
            _add_tar_bytes(archive, extra[0], extra[1])
        if link is not None:
            member = tarfile.TarInfo(link)
            member.type = tarfile.SYMTYPE
            member.linkname = "manifest.json"
            archive.addfile(member)
    return image_id


@pytest.mark.parametrize(
    "value",
    [
        "../escape",
        "/absolute",
        "C:/drive",
        "a\\b",
        "a:b",
        "a/./b",
        "a/../b",
        "CON/file",
        "dir/NUL.json",
        "tail. ",
        "e\u0301.txt",
    ],
)
def test_relative_rejects_nonportable_or_ambiguous_paths(value: str) -> None:
    with pytest.raises(portable.PortableClosureError):
        portable._relative(value, label="candidate")


def test_image_tar_audit_accepts_one_exact_safe_image(tmp_path: Path) -> None:
    archive = tmp_path / "image.tar"
    image_id = _docker_tar(archive)

    result = portable._audit_image_tar(archive, image_id=image_id, image_ref="example/f4:test")

    assert result["archive_layout"]["kind"] == "oci-image-layout-v1"
    assert result["subject_descriptor"]["digest"] == image_id
    assert result["runnable_manifest"]["platform"] == {
        "architecture": "amd64",
        "os": "linux",
    }
    assert result["config"]["architecture"] == "amd64"
    assert result["layer_count"] == 1
    assert result["repo_tags"] == ["example/f4:test"]


@pytest.mark.parametrize(
    ("extra", "link"),
    [
        (("../escape", b"x"), None),
        (("C:/drive", b"x"), None),
        (("CON", b"x"), None),
        (("Manifest.json", b"collision"), None),
        (None, "linked"),
    ],
)
def test_image_tar_audit_rejects_slip_reserved_collision_and_links(
    tmp_path: Path,
    extra: tuple[str, bytes] | None,
    link: str | None,
) -> None:
    archive = tmp_path / "image.tar"
    image_id = _docker_tar(archive, extra=extra, link=link)

    with pytest.raises(portable.PortableClosureError):
        portable._audit_image_tar(archive, image_id=image_id, image_ref="example/f4:test")


def test_image_tar_audit_closes_multilevel_index_and_attestation_graph(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "image.tar"
    image_id = _docker_tar(archive, nested_index=True, include_attestation=True)

    result = portable._audit_image_tar(archive, image_id=image_id, image_ref="example/f4:test")

    assert result["subject_descriptor"]["media_type"] == ("application/vnd.oci.image.index.v1+json")
    assert result["descriptor_count"] == 7
    assert result["reachable_blob_count"] == 7
    assert result["unreferenced_blob_count"] == 0
    assert len(result["descriptor_graph_sha256"]) == 64


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"descriptor_tamper": "digest"}, "subject descriptor"),
        ({"descriptor_tamper": "uppercase"}, "canonical lowercase"),
        ({"descriptor_tamper": "size"}, "descriptor size"),
        ({"repo_tags": []}, "RepoTags"),
        ({"repo_tags": ["foreign/f4:test"]}, "RepoTags"),
        (
            {"nested_index": True, "duplicate_runnable": True},
            "runnable linux/amd64 manifest selection",
        ),
    ],
)
def test_image_tar_audit_rejects_descriptor_tag_and_selection_drift(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
) -> None:
    archive = tmp_path / "image.tar"
    image_id = _docker_tar(archive, **kwargs)

    with pytest.raises(portable.PortableClosureError, match=message):
        portable._audit_image_tar(archive, image_id=image_id, image_ref="example/f4:test")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"layout_version": "1.1.0"}, "layout version"),
        ({"root_schema_version": 1}, "root index"),
        ({"root_media_type": "application/example.invalid"}, "root index"),
    ],
)
def test_image_tar_audit_rejects_layout_and_root_index_drift(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
) -> None:
    archive = tmp_path / "image.tar"
    image_id = _docker_tar(archive, **kwargs)
    with pytest.raises(portable.PortableClosureError, match=message):
        portable._audit_image_tar(archive, image_id=image_id, image_ref="example/f4:test")


def test_image_tar_audit_rejects_unreferenced_valid_blob(tmp_path: Path) -> None:
    archive = tmp_path / "image.tar"
    body = b"unreferenced-but-content-addressed"
    member = f"blobs/sha256/{hashlib.sha256(body).hexdigest()}"
    image_id = _docker_tar(archive, extra=(member, body))
    with pytest.raises(portable.PortableClosureError, match="unreferenced"):
        portable._audit_image_tar(archive, image_id=image_id, image_ref="example/f4:test")


def test_image_tar_audit_rejects_deep_descriptor_chain_with_controlled_error(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "image.tar"
    image_id = _docker_tar(archive, nested_depth=70)
    with pytest.raises(portable.PortableClosureError, match="maximum depth"):
        portable._audit_image_tar(archive, image_id=image_id, image_ref="example/f4:test")


def _minimal_pack(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "pack"
    root.mkdir(parents=True)
    runner = _write(root / portable.RUNNER_NAME, b"# runner\n")
    bundle = _write(root / portable.IMAGE_TAR_RELATIVE, b"sealed image")
    claim_scope = {
        "f4_runtime_replay": "exact semantic replay of the sealed F4 OCI snapshot",
        "foundation_v4": "byte-sealed co-packaged final foundation closure tree",
        "relationship": "co-packaged identities; no runtime-to-foundation derivation claim",
    }
    baseline_core: dict[str, object] = {
        "schema_version": portable.BASELINE_SCHEMA,
        "foundation_v4_relocatable_execution": False,
        "claim_scope": claim_scope,
        "runtime": {
            "image_id": f"sha256:{'1' * 64}",
            "image_tar_audit": {"synthetic": True},
        },
        "canonical_runtime": {
            "semantic_output_file_count": 3,
            "semantic_output_inventory": [
                {
                    "relative_path": path,
                    "sha256": hashlib.sha256(path.encode("utf-8")).hexdigest(),
                    "size_bytes": 1,
                }
                for path in sorted(portable.EXPECTED_SEMANTIC_PATHS)
            ],
            "semantic_output_set_sha256": "2" * 64,
            "raw_assertion_bundle": {
                "relative_path": portable.ASSERTION_BUNDLE_RELATIVE,
                "sha256": hashlib.sha256(
                    portable.ASSERTION_BUNDLE_RELATIVE.encode("utf-8")
                ).hexdigest(),
                "size_bytes": 1,
                "assertion_count": 14,
            },
            "assertion_count": 14,
            "fallback_count": 0,
        },
    }
    baseline: dict[str, object] = {
        **baseline_core,
        "content_sha256": portable._canonical_sha256(baseline_core),
    }
    baseline_path = _canonical(root / portable.BASELINE_RELATIVE, baseline)
    artifacts = portable._inventory(root, excluded={portable.MANIFEST_NAME})
    manifest_core: dict[str, object] = {
        "schema_version": portable.PACK_SCHEMA,
        "runner": portable._file_ref(runner, relative_path=portable.RUNNER_NAME),
        "baseline": portable._file_ref(baseline_path, relative_path=portable.BASELINE_RELATIVE),
        "baseline_content_sha256": baseline["content_sha256"],
        "image_bundle": portable._file_ref(bundle, relative_path=portable.IMAGE_TAR_RELATIVE),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "artifact_set_sha256": portable._canonical_sha256(artifacts),
        "f4_oci_relocatable_execution": True,
        "foundation_v4_relocatable_execution": False,
        "claim_scope": claim_scope,
        "source_admission_anchors": {
            key: hashlib.sha256(key.encode("utf-8")).hexdigest()
            for key in portable.SOURCE_ANCHOR_KEYS
        },
        "foundation_physical_file_count_anchor": 1,
        "pre_execution_runner_anchor_required": True,
    }
    manifest: dict[str, object] = {
        **manifest_core,
        "content_sha256": portable._canonical_sha256(manifest_core),
    }
    manifest_path = _canonical(root / portable.MANIFEST_NAME, manifest)
    return root, {
        "expected_manifest_sha256": portable._file_sha256(manifest_path),
        "expected_runner_sha256": portable._file_sha256(runner),
        "expected_bundle_sha256": portable._file_sha256(bundle),
    }


@pytest.fixture
def isolated_inner_verifiers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(portable, "_audit_image_tar", lambda *_args, **_kwargs: {"synthetic": True})
    monkeypatch.setattr(portable, "_verify_provenance", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(portable, "_verify_snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(portable, "_verify_foundation", lambda *_args, **_kwargs: {})


def test_outer_manifest_requires_three_external_anchors(
    tmp_path: Path,
    isolated_inner_verifiers: None,
) -> None:
    root, anchors = _minimal_pack(tmp_path)

    result = portable.verify_portable_pack(pack_root=root, **anchors)

    assert result["status"] == "VERIFIED"
    assert result["active_retained_absolute_ref_dereference_count"] == 0
    for field in anchors:
        changed = dict(anchors)
        changed[field] = "0" * 64
        with pytest.raises(portable.PortableClosureError):
            portable.verify_portable_pack(pack_root=root, **changed)


def test_outer_manifest_rejects_component_tamper_and_extra_file(
    tmp_path: Path,
    isolated_inner_verifiers: None,
) -> None:
    root, anchors = _minimal_pack(tmp_path)
    baseline = root / portable.BASELINE_RELATIVE
    baseline.write_bytes(baseline.read_bytes() + b"\n")
    with pytest.raises(portable.PortableClosureError, match="inventory"):
        portable.verify_portable_pack(pack_root=root, **anchors)

    root, anchors = _minimal_pack(tmp_path / "second")
    _write(root / "extra.json", b"{}")
    with pytest.raises(portable.PortableClosureError, match="inventory"):
        portable.verify_portable_pack(pack_root=root, **anchors)


def test_self_consistent_manifest_replacement_fails_external_anchor(
    tmp_path: Path,
    isolated_inner_verifiers: None,
) -> None:
    root, anchors = _minimal_pack(tmp_path)
    runner = root / portable.RUNNER_NAME
    runner.write_bytes(b"# replaced runner\n")
    manifest_path = root / portable.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = portable._inventory(root, excluded={portable.MANIFEST_NAME})
    manifest["runner"] = portable._file_ref(runner, relative_path=portable.RUNNER_NAME)
    manifest["artifacts"] = artifacts
    manifest["artifact_count"] = len(artifacts)
    manifest["artifact_set_sha256"] = portable._canonical_sha256(artifacts)
    manifest.pop("content_sha256")
    manifest["content_sha256"] = portable._canonical_sha256(manifest)
    _canonical(manifest_path, manifest)

    with pytest.raises(portable.PortableClosureError, match="external anchor"):
        portable.verify_portable_pack(pack_root=root, **anchors)


def test_retained_windows_absolute_ref_maps_only_to_pack_local_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "pack"
    local = _write(root / "foundation" / "report.json", b"sealed")
    raw = {
        "path": r"Z:\poison\outside\report.json",
        "sha256": portable._file_sha256(local),
        "size_bytes": local.stat().st_size,
    }
    original_open = Path.open
    original_stat = Path.stat

    def guarded_open(self: Path, *args: object, **kwargs: object):
        assert os.path.commonpath([str(self.absolute()), str(root.absolute())]) == str(
            root.absolute()
        )
        return original_open(self, *args, **kwargs)

    def guarded_stat(self: Path, *args: object, **kwargs: object):
        candidate = self.absolute()
        pack = root.absolute()
        assert os.path.commonpath([str(candidate), str(pack)]) == str(pack) or os.path.commonpath(
            [str(candidate), str(pack)]
        ) == str(candidate)
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "stat", guarded_stat)

    mapped = portable._match_recorded_ref(
        root,
        raw,
        "foundation/report.json",
        label="poisoned retained ref",
    )

    assert mapped == local


def _provenance_fixture(
    tmp_path: Path,
    *,
    authority_schema: str,
    execution_schema: str = portable.OCI_EXECUTION_RECEIPT_SCHEMA,
) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "pack"
    image_id = f"sha256:{'1' * 64}"
    data_content = "2" * 64
    semantic_inventory = [
        {
            "relative_path": path,
            "sha256": hashlib.sha256(path.encode("utf-8")).hexdigest(),
            "size_bytes": 1,
        }
        for path in sorted(portable.EXPECTED_SEMANTIC_PATHS)
    ]
    semantic_set = portable._canonical_sha256(semantic_inventory)
    raw_bundle = {
        "relative_path": portable.ASSERTION_BUNDLE_RELATIVE,
        "sha256": next(
            row["sha256"]
            for row in semantic_inventory
            if row["relative_path"] == portable.ASSERTION_BUNDLE_RELATIVE
        ),
        "size_bytes": 1,
        "content_sha256": "4" * 64,
        "request_sha256": "5" * 64,
        "assertion_ids": [f"assertion-{index:02d}" for index in range(14)],
        "assertion_count": 14,
        "assertion_actuals_sha256": "6" * 64,
    }
    frozen_core: dict[str, object] = {
        "schema_version": "xinao.f4_oci_frozen_inputs.v1",
        "image_id": image_id,
        "data_content_sha256": data_content,
    }
    frozen = {**frozen_core, "content_sha256": portable._canonical_sha256(frozen_core)}
    execution_core: dict[str, object] = {
        "schema_version": execution_schema,
        "status": "VERIFIED",
        "run_count": 2,
        "runs": [
            {
                "ordinal": ordinal,
                "semantic_output_file_count": 3,
                "semantic_output_inventory": semantic_inventory,
                "semantic_output_set_sha256": semantic_set,
            }
            for ordinal in (1, 2)
        ],
        "semantic_output_byte_identical": True,
        "semantic_output_set_sha256": semantic_set,
        "assertion_count": 14,
        "fallback_count": 0,
    }
    execution = {
        **execution_core,
        "content_sha256": portable._canonical_sha256(execution_core),
    }
    authority_core: dict[str, object] = {"schema_version": authority_schema}
    authority = {
        **authority_core,
        "content_sha256": portable._canonical_sha256(authority_core),
    }
    frozen_path = _canonical(root / portable.FROZEN_RELATIVE, frozen)
    execution_path = _canonical(root / portable.EXECUTION_RELATIVE, execution)
    authority_path = _canonical(root / portable.AUTHORITY_RELATIVE, authority)
    baseline: dict[str, object] = {
        "runtime": {
            "image_id": image_id,
            "authority_manifest_sha256": portable._file_sha256(authority_path),
            "authority_content_sha256": authority["content_sha256"],
        },
        "snapshot": {"content_sha256": data_content},
        "canonical_runtime": {
            "semantic_output_file_count": 3,
            "semantic_output_inventory": semantic_inventory,
            "semantic_output_set_sha256": semantic_set,
            "raw_assertion_bundle": raw_bundle,
            "assertion_count": 14,
            "fallback_count": 0,
        },
        "provenance": {
            "frozen": portable._file_ref(frozen_path, relative_path=portable.FROZEN_RELATIVE),
            "frozen_content_sha256": frozen["content_sha256"],
            "canonical_execution": portable._file_ref(
                execution_path, relative_path=portable.EXECUTION_RELATIVE
            ),
            "canonical_execution_content_sha256": execution["content_sha256"],
            "authority_manifest": portable._file_ref(
                authority_path, relative_path=portable.AUTHORITY_RELATIVE
            ),
        },
    }
    return root, baseline


def test_provenance_requires_exact_authority_v2(tmp_path: Path) -> None:
    root, baseline = _provenance_fixture(
        tmp_path / "v2", authority_schema="xinao.f4_authority_source_pack.v2"
    )
    assert portable._verify_provenance(root, baseline)["authority_content_sha256"]

    root, baseline = _provenance_fixture(
        tmp_path / "v1", authority_schema="xinao.f4_authority_source_pack.v1"
    )
    with pytest.raises(portable.PortableClosureError, match="provenance"):
        portable._verify_provenance(root, baseline)

    root, baseline = _provenance_fixture(
        tmp_path / "legacy-execution",
        authority_schema="xinao.f4_authority_source_pack.v2",
        execution_schema="xinao.f4_oci_execution_receipt.v1",
    )
    with pytest.raises(portable.PortableClosureError, match="provenance"):
        portable._verify_provenance(root, baseline)


def _semantic_output_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "semantic-output"
    assertion_ids = [f"assertion-{index:02d}" for index in range(14)]
    actuals = {assertion_id: True for assertion_id in assertion_ids}
    bundle_core: dict[str, object] = {
        "schema_version": "xinao.assertion_actual_bundle.v2",
        "protocol_version": "xinao.assertion_bundle_protocol.v2",
        "block_id": "F4_research_factory",
        "checker_id": "f4-test-checker",
        "checker_version": "f4-test-checker.v1",
        "request_sha256": "7" * 64,
        "entrypoint": {
            "module_name": "xinao.foundation.assertion_verifiers.f4_assertion_actuals",
            "source_path": "xinao/foundation/assertion_verifiers/f4_assertion_actuals.py",
            "source_sha256": "8" * 64,
            "checker_id": "f4-test-checker",
            "checker_version": "f4-test-checker.v1",
        },
        "assertion_actuals": actuals,
        "assertion_actual_content_sha256": {
            assertion_id: portable._canonical_sha256({"assertion_id": assertion_id, "actual": True})
            for assertion_id in assertion_ids
        },
    }
    bundle = {
        **bundle_core,
        "content_sha256": portable._canonical_sha256(bundle_core),
    }
    bundle_path = _canonical(root / portable.ASSERTION_BUNDLE_RELATIVE, bundle)
    trace_core: dict[str, object] = {
        "schema_version": "xinao.f4_snapshot_trace_summary.v1",
        "status": "VERIFIED",
        "process_count": 5,
        "fallback_count": 0,
        "total_event_count": 5,
        "process_observations": [],
        "manifest_content_sha256": "9" * 64,
    }
    trace = {
        **trace_core,
        "content_sha256": portable._canonical_sha256(trace_core),
    }
    trace_path = _canonical(root / "snapshot_trace_summary.json", trace)
    stage0_core: dict[str, object] = {
        "schema_version": "xinao.f4_snapshot_stage0_run.v1",
        "status": "VERIFIED",
        "preflight": {"isolation_negative_probes": {"all_rejected": True}},
        "common_assertion_bundle": {
            "path": "/output/f4_assertion_actual_bundle.v2.json",
            "sha256": portable._file_sha256(bundle_path),
            "size_bytes": bundle_path.stat().st_size,
            "content_sha256": bundle["content_sha256"],
            "request_sha256": bundle["request_sha256"],
            "assertion_count": 14,
        },
        "common_authority_projection": {
            "schema_version": "xinao.f4_common_authority_projection.v1",
            "status": "VERIFIED",
        },
        "snapshot_trace_summary_ref": "/output/snapshot_trace_summary.json",
        "snapshot_trace_summary_sha256": portable._file_sha256(trace_path),
        "snapshot_trace_summary_content_sha256": trace["content_sha256"],
        "assertion_count": 14,
        "fallback_count": 0,
    }
    stage0 = {
        **stage0_core,
        "content_sha256": portable._canonical_sha256(stage0_core),
    }
    _canonical(root / "stage0_result.json", stage0)
    return root


def test_semantic_contract_uses_exact_v2_three_file_raw_bundle(tmp_path: Path) -> None:
    root = _semantic_output_fixture(tmp_path)

    contract = portable._semantic_contract(root)

    assert contract["semantic_output_file_count"] == 3
    assert {
        row["relative_path"] for row in contract["semantic_output_inventory"]
    } == portable.EXPECTED_SEMANTIC_PATHS
    assert contract["raw_assertion_bundle"]["assertion_count"] == 14
    assert contract["raw_assertion_bundle"]["request_sha256"] == "7" * 64
    assert "production_check_count" not in contract
    assert "fresh_verifier_count" not in contract


def test_semantic_contract_rejects_legacy_extra_output_and_raw_bundle_drift(
    tmp_path: Path,
) -> None:
    root = _semantic_output_fixture(tmp_path / "extra")
    _write(root / "closure" / "artifact_manifest.json", b"{}")
    with pytest.raises(portable.PortableClosureError, match="three-file"):
        portable._semantic_contract(root)

    root = _semantic_output_fixture(tmp_path / "bundle-drift")
    bundle_path = root / portable.ASSERTION_BUNDLE_RELATIVE
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assertion_id = sorted(bundle["assertion_actual_content_sha256"])[0]
    bundle["assertion_actual_content_sha256"][assertion_id] = "0" * 64
    bundle.pop("content_sha256")
    bundle["content_sha256"] = portable._canonical_sha256(bundle)
    _canonical(bundle_path, bundle)
    with pytest.raises(portable.PortableClosureError, match="raw assertion bundle contract"):
        portable._semantic_contract(root)


def test_build_source_admission_requires_every_external_anchor() -> None:
    observed = {
        key: hashlib.sha256(key.encode("utf-8")).hexdigest() for key in portable.SOURCE_ANCHOR_KEYS
    }
    portable._verify_source_admission_anchors(observed=observed, expected=dict(observed))
    for key in portable.SOURCE_ANCHOR_KEYS:
        changed = dict(observed)
        changed[key] = "0" * 64
        with pytest.raises(portable.PortableClosureError, match=key):
            portable._verify_source_admission_anchors(observed=observed, expected=changed)


def test_manifest_reparse_is_rejected_before_hash(
    tmp_path: Path,
    isolated_inner_verifiers: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, anchors = _minimal_pack(tmp_path)
    manifest = (root / portable.MANIFEST_NAME).absolute()
    original_is_reparse = portable._is_reparse
    original_sha = portable._file_sha256
    hashed: list[Path] = []

    def fake_is_reparse(path: Path) -> bool:
        if path.absolute() == manifest:
            return True
        return original_is_reparse(path)

    def tracked_sha(path: Path) -> str:
        hashed.append(path.absolute())
        return original_sha(path)

    monkeypatch.setattr(portable, "_is_reparse", fake_is_reparse)
    monkeypatch.setattr(portable, "_file_sha256", tracked_sha)
    with pytest.raises(portable.PortableClosureError, match="reparse"):
        portable.verify_portable_pack(pack_root=root, **anchors)
    assert manifest not in hashed


def test_image_immutable_identity_does_not_depend_on_repo_digests() -> None:
    config = {
        "Entrypoint": portable.EXPECTED_ENTRYPOINT,
        "Cmd": portable.EXPECTED_CMD,
        "WorkingDir": "/work",
        "User": "65532:65532",
        "Env": ["PATH=/opt/f4-runtime/.venv/bin"],
        "Labels": {"identity": "sealed"},
    }
    base = {
        "Id": f"sha256:{'1' * 64}",
        "Os": "linux",
        "Architecture": "amd64",
        "Config": config,
    }
    source = {**base, "RepoDigests": ["example@sha256:" + "2" * 64]}
    loaded = {**base, "RepoDigests": []}
    assert portable._image_identity(source) == portable._image_identity(loaded)
    drifted = json.loads(json.dumps(loaded))
    drifted["Config"]["Cmd"] = ["different"]
    with pytest.raises(portable.PortableClosureError):
        portable._image_identity(drifted)


def _daemon_identity() -> dict[str, str]:
    core = {
        "context": "desktop-linux",
        "docker_endpoint": "npipe:////./pipe/dockerDesktopLinuxEngine",
        "daemon_id": "9f370742-b41b-4d0e-a5d3-1e244aca0b9b",
    }
    return {**core, "content_sha256": portable._canonical_sha256(core)}


def test_daemon_fingerprint_requires_all_successful_queries_and_detects_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        ("docker", "context", "show"): "desktop-linux\n",
        (
            "docker",
            "context",
            "inspect",
            "desktop-linux",
            "--format",
            "{{.Endpoints.docker.Host}}",
        ): "npipe:////./pipe/dockerDesktopLinuxEngine\n",
        ("docker", "info", "--format", "{{.ID}}"): ("9f370742-b41b-4d0e-a5d3-1e244aca0b9b\n"),
    }

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, responses[tuple(argv)], "")

    monkeypatch.setattr(portable, "_run", fake_run)
    expected = _daemon_identity()
    assert portable._daemon_fingerprint(cwd=tmp_path) == expected
    portable._require_same_daemon(expected=expected, cwd=tmp_path, operation="test")

    responses[("docker", "info", "--format", "{{.ID}}")] = "different-daemon\n"
    with pytest.raises(portable.PortableClosureError, match="daemon identity drifted"):
        portable._require_same_daemon(expected=expected, cwd=tmp_path, operation="rm")

    def failed_info(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[1] == "info":
            return subprocess.CompletedProcess(argv, 1, "", "daemon unavailable")
        return fake_run(argv)

    monkeypatch.setattr(portable, "_run", failed_info)
    with pytest.raises(portable.PortableClosureError, match="fingerprint query failed"):
        portable._daemon_fingerprint(cwd=tmp_path)


def test_container_query_requires_success_and_full_id_name_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container_id = "1" * 64

    def response(stdout: str, *, returncode: int = 0):
        def fake_run(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([], returncode, stdout, "daemon failure")

        return fake_run

    monkeypatch.setattr(portable, "_run", response(f"{container_id}\texact-owner\n"))
    assert portable._query_container_rows(filter_value="name=exact-owner", cwd=tmp_path) == [
        {"container_id": container_id, "name": "exact-owner"}
    ]
    monkeypatch.setattr(portable, "_run", response("short\texact-owner\n"))
    with pytest.raises(portable.PortableClosureError, match="invalid full ID"):
        portable._query_container_rows(filter_value="name=exact-owner", cwd=tmp_path)
    monkeypatch.setattr(portable, "_run", response("", returncode=1))
    with pytest.raises(portable.PortableClosureError, match="inventory query failed"):
        portable._query_container_rows(filter_value="name=exact-owner", cwd=tmp_path)


def test_exact_name_query_ignores_docker_partial_name_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        portable,
        "_query_container_rows",
        lambda **_kwargs: [
            {"container_id": "1" * 64, "name": "exact-owner-suffix"},
            {"container_id": "2" * 64, "name": "prefix-exact-owner"},
        ],
    )
    assert portable._query_exact_name_rows(name="exact-owner", cwd=tmp_path) == []


@pytest.mark.parametrize("collision", ["name", "owner"])
def test_container_preflight_rejects_exact_name_or_owner_nonce_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    collision: str,
) -> None:
    container_id = "1" * 64

    def fake_query(*, filter_value: str, cwd: Path) -> list[dict[str, str]]:
        assert cwd == tmp_path
        if collision == "name" and filter_value.startswith("name="):
            return [{"container_id": container_id, "name": "exact-owner"}]
        if collision == "owner" and filter_value.startswith("label="):
            return [{"container_id": container_id, "name": "other"}]
        return []

    monkeypatch.setattr(portable, "_query_container_rows", fake_query)
    with pytest.raises(portable.PortableClosureError, match="preflight collision"):
        portable._require_container_preflight_clear(
            name="exact-owner", owner_nonce="a" * 32, cwd=tmp_path
        )


def test_owner_reconcile_rejects_ambiguous_or_foreign_label_without_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = _daemon_identity()
    runtime = {"image_id": f"sha256:{'1' * 64}", "image_identity": {}}
    snapshot = tmp_path / "snapshot"
    output = tmp_path / "output"
    snapshot.mkdir()
    output.mkdir()
    inspected: list[str] = []
    removed: list[str] = []
    monkeypatch.setattr(portable, "_require_same_daemon", lambda **_kwargs: None)
    monkeypatch.setattr(
        portable,
        "_query_owner_rows",
        lambda **_kwargs: [
            {"container_id": "1" * 64, "name": "exact-owner"},
            {"container_id": "2" * 64, "name": "exact-owner"},
        ],
    )
    monkeypatch.setattr(
        portable, "_docker_inspect", lambda *_args, **_kwargs: inspected.append("inspect")
    )
    monkeypatch.setattr(portable, "_run", lambda *_args, **_kwargs: removed.append("rm"))
    with pytest.raises(portable.PortableClosureError, match="ambiguous"):
        portable._reconcile_owned_container(
            name="exact-owner",
            owner_nonce="a" * 32,
            run_id="run-1",
            runtime=runtime,
            snapshot_root=snapshot,
            output_dir=output,
            daemon_fingerprint=daemon,
            cwd=tmp_path,
        )
    assert not inspected and not removed

    foreign, runtime = _container_fixture(
        tmp_path,
        output,
        name="exact-owner",
        owner_nonce="foreign",
        run_id="run-1",
    )
    monkeypatch.setattr(
        portable,
        "_query_owner_rows",
        lambda **_kwargs: [{"container_id": "1" * 64, "name": "exact-owner"}],
    )
    monkeypatch.setattr(portable, "_docker_inspect", lambda *_args, **_kwargs: foreign)
    with pytest.raises(portable.PortableClosureError, match="owner label"):
        portable._reconcile_owned_container(
            name="exact-owner",
            owner_nonce="a" * 32,
            run_id="run-1",
            runtime=runtime,
            snapshot_root=tmp_path / portable.SNAPSHOT_RELATIVE,
            output_dir=output,
            daemon_fingerprint=daemon,
            cwd=tmp_path,
        )
    assert not removed


@pytest.mark.parametrize("drift", ["name", "run", "inspect_id", "image", "mount"])
def test_reconcile_owned_drift_matrix_never_starts_or_removes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    output = tmp_path / "output"
    snapshot = tmp_path / portable.SNAPSHOT_RELATIVE
    output.mkdir()
    snapshot.mkdir()
    container, runtime = _container_fixture(tmp_path, output)
    changed = json.loads(json.dumps(container))
    if drift == "name":
        changed["Name"] = "/foreign-name"
    elif drift == "run":
        changed["Config"]["Labels"][portable.RUN_LABEL] = "foreign-run"
    elif drift == "inspect_id":
        changed["Id"] = "2" * 64
    elif drift == "image":
        changed["Image"] = f"sha256:{'2' * 64}"
    else:
        changed["Mounts"][0]["Source"] = r"Z:\foreign\snapshot"
    mutations: list[list[str]] = []
    monkeypatch.setattr(portable, "_require_same_daemon", lambda **_kwargs: None)
    monkeypatch.setattr(
        portable,
        "_query_owner_rows",
        lambda **_kwargs: [{"container_id": "1" * 64, "name": "exact-owner"}],
    )
    monkeypatch.setattr(portable, "_docker_inspect", lambda *_args, **_kwargs: changed)
    monkeypatch.setattr(
        portable,
        "_run",
        lambda argv, **_kwargs: (
            mutations.append(argv) or subprocess.CompletedProcess(argv, 0, "", "")
        ),
    )
    with pytest.raises(portable.PortableClosureError):
        portable._reconcile_owned_container(
            name="exact-owner",
            owner_nonce="a" * 32,
            run_id="run-1",
            runtime=runtime,
            snapshot_root=snapshot,
            output_dir=output,
            daemon_fingerprint=_daemon_identity(),
            cwd=tmp_path,
        )
    assert mutations == []


def test_owned_cleanup_reinspects_removes_by_full_id_and_proves_all_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container_id = "1" * 64
    daemon = _daemon_identity()
    runtime = {"image_id": f"sha256:{'1' * 64}", "image_identity": {}}
    snapshot = tmp_path / portable.SNAPSHOT_RELATIVE
    output = tmp_path / "output"
    snapshot.mkdir()
    output.mkdir()
    operations: list[str] = []
    monkeypatch.setattr(
        portable,
        "_require_same_daemon",
        lambda **kwargs: operations.append(str(kwargs["operation"])),
    )
    monkeypatch.setattr(
        portable,
        "_inspect_owned_container",
        lambda **_kwargs: {"container_id": container_id, "isolation": {}},
    )

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert argv == ["docker", "rm", "-f", container_id]
        operations.append("rm-by-id")
        return subprocess.CompletedProcess(argv, 0, container_id, "")

    monkeypatch.setattr(portable, "_run", fake_run)
    monkeypatch.setattr(portable, "_query_container_rows", lambda **_kwargs: [])
    proof = portable._remove_owned_container(
        container_id=container_id,
        name="exact-owner",
        owner_nonce="a" * 32,
        run_id="run-1",
        runtime=runtime,
        snapshot_root=snapshot,
        output_dir=output,
        daemon_fingerprint=daemon,
        cwd=tmp_path,
    )
    assert proof == {
        "verified": True,
        "container_id_absent": True,
        "owner_nonce_absent": True,
        "exact_name_absent": True,
    }
    assert operations == [
        "container remove",
        "rm-by-id",
        "container post-remove",
        "container cleanup proof",
    ]

    operations.clear()

    def drift(**kwargs: object) -> None:
        operations.append(str(kwargs["operation"]))
        raise portable.PortableClosureError("daemon identity drifted before rm")

    monkeypatch.setattr(portable, "_require_same_daemon", drift)
    with pytest.raises(portable.PortableClosureError, match="daemon identity drifted"):
        portable._remove_owned_container(
            container_id=container_id,
            name="exact-owner",
            owner_nonce="a" * 32,
            run_id="run-1",
            runtime=runtime,
            snapshot_root=snapshot,
            output_dir=output,
            daemon_fingerprint=daemon,
            cwd=tmp_path,
        )
    assert operations == ["container remove"]


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("rm_nonzero", "removal failed"),
        ("post_query_failure", "post-probe failed"),
        ("residual_id", "exact ID present"),
        ("residual_owner", "owner nonce present"),
        ("foreign_exact_name", "exact name present"),
        ("final_daemon_drift", "daemon identity drifted"),
    ],
)
def test_cleanup_fail_closed_matrix_never_deletes_by_name_or_returns_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    message: str,
) -> None:
    owned_id = "1" * 64
    foreign_id = "2" * 64
    snapshot = tmp_path / portable.SNAPSHOT_RELATIVE
    output = tmp_path / "output"
    snapshot.mkdir()
    output.mkdir()
    rm_calls: list[list[str]] = []
    monkeypatch.setattr(
        portable,
        "_inspect_owned_container",
        lambda **_kwargs: {"container_id": owned_id, "isolation": {}},
    )

    def same_daemon(**kwargs: object) -> None:
        if failure == "final_daemon_drift" and kwargs["operation"] == "container cleanup proof":
            raise portable.PortableClosureError("daemon identity drifted at cleanup proof")

    monkeypatch.setattr(portable, "_require_same_daemon", same_daemon)

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        rm_calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            1 if failure == "rm_nonzero" else 0,
            "",
            "rm failed" if failure == "rm_nonzero" else "",
        )

    monkeypatch.setattr(portable, "_run", fake_run)

    def query(*, filter_value: str, cwd: Path) -> list[dict[str, str]]:
        assert cwd == tmp_path
        if failure == "post_query_failure":
            raise portable.PortableClosureError("post-probe failed")
        if failure == "residual_id" and filter_value.startswith("id="):
            return [{"container_id": owned_id, "name": "exact-owner"}]
        if failure == "residual_owner" and filter_value.startswith("label="):
            return [{"container_id": owned_id, "name": "exact-owner"}]
        if failure == "foreign_exact_name" and filter_value.startswith("name="):
            return [{"container_id": foreign_id, "name": "exact-owner"}]
        return []

    monkeypatch.setattr(portable, "_query_container_rows", query)
    with pytest.raises(portable.PortableClosureError, match=message):
        portable._remove_owned_container(
            container_id=owned_id,
            name="exact-owner",
            owner_nonce="a" * 32,
            run_id="run-1",
            runtime={"image_id": f"sha256:{'1' * 64}", "image_identity": {}},
            snapshot_root=snapshot,
            output_dir=output,
            daemon_fingerprint=_daemon_identity(),
            cwd=tmp_path,
        )
    assert rm_calls == [["docker", "rm", "-f", owned_id]]
    assert all("exact-owner" not in call for call in rm_calls)


@pytest.mark.parametrize(
    ("created", "message"),
    [
        (
            subprocess.CompletedProcess(["docker", "create"], 1, "", "create failed"),
            "create failed",
        ),
        (subprocess.CompletedProcess(["docker", "create"], 0, "", ""), "no exact container ID"),
        (subprocess.TimeoutExpired(["docker", "create"], 30), "create invocation failed"),
    ],
)
def test_create_failure_or_empty_id_reconciles_owned_cleanup_then_raises_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    created: subprocess.CompletedProcess[str] | subprocess.TimeoutExpired,
    message: str,
) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    owned_id = "1" * 64
    daemon = _daemon_identity()
    cleanup: list[str] = []
    monkeypatch.setattr(
        portable,
        "_new_container_identity",
        lambda ordinal: ("exact-owner", "a" * 32, f"run-{ordinal}"),
    )
    monkeypatch.setattr(portable, "_require_container_preflight_clear", lambda **_kwargs: None)
    monkeypatch.setattr(portable, "_require_same_daemon", lambda **_kwargs: None)

    def create_call(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if isinstance(created, BaseException):
            raise created
        return created

    monkeypatch.setattr(portable, "_run", create_call)
    monkeypatch.setattr(
        portable,
        "_reconcile_owned_container",
        lambda **_kwargs: {"container_id": owned_id, "isolation": {}},
    )
    monkeypatch.setattr(
        portable,
        "_remove_owned_container",
        lambda **_kwargs: cleanup.append(str(_kwargs["container_id"])) or {"verified": True},
    )
    with pytest.raises(portable.PortableClosureError, match=message):
        portable._one_runtime(
            ordinal=1,
            pack_root=pack,
            output_root=tmp_path / "output",
            runtime={"image_id": f"sha256:{'1' * 64}"},
            daemon_fingerprint=daemon,
        )
    assert cleanup == [owned_id]


def test_create_candidate_id_mismatch_cleans_only_reconciled_full_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    candidate_id = "2" * 64
    owned_id = "1" * 64
    cleanup: list[str] = []
    calls: list[list[str]] = []
    monkeypatch.setattr(
        portable,
        "_new_container_identity",
        lambda ordinal: ("exact-owner", "a" * 32, f"run-{ordinal}"),
    )
    monkeypatch.setattr(portable, "_require_container_preflight_clear", lambda **_kwargs: None)
    monkeypatch.setattr(portable, "_require_same_daemon", lambda **_kwargs: None)

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, candidate_id, "")

    monkeypatch.setattr(portable, "_run", fake_run)
    monkeypatch.setattr(
        portable,
        "_reconcile_owned_container",
        lambda **_kwargs: {"container_id": owned_id, "isolation": {}},
    )
    monkeypatch.setattr(
        portable,
        "_remove_owned_container",
        lambda **kwargs: (
            cleanup.append(str(kwargs["container_id"]))
            or {
                "verified": True,
                "container_id_absent": True,
                "owner_nonce_absent": True,
                "exact_name_absent": True,
            }
        ),
    )
    with pytest.raises(portable.PortableClosureError, match="differs from the reconciled"):
        portable._one_runtime(
            ordinal=1,
            pack_root=pack,
            output_root=tmp_path / "output",
            runtime={"image_id": f"sha256:{'1' * 64}"},
            daemon_fingerprint=_daemon_identity(),
        )
    assert len(calls) == 1 and calls[0][:2] == ["docker", "create"]
    assert cleanup == [owned_id]


def test_create_timeout_with_no_owned_nonce_never_attempts_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    cleanup: list[str] = []
    monkeypatch.setattr(
        portable,
        "_new_container_identity",
        lambda ordinal: ("exact-owner", "a" * 32, f"run-{ordinal}"),
    )
    monkeypatch.setattr(portable, "_require_container_preflight_clear", lambda **_kwargs: None)
    monkeypatch.setattr(portable, "_require_same_daemon", lambda **_kwargs: None)
    monkeypatch.setattr(
        portable,
        "_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(["docker", "create"], 30)
        ),
    )
    monkeypatch.setattr(portable, "_reconcile_owned_container", lambda **_kwargs: None)
    monkeypatch.setattr(
        portable,
        "_remove_owned_container",
        lambda **kwargs: cleanup.append(str(kwargs["container_id"])),
    )
    with pytest.raises(portable.PortableClosureError, match="create invocation failed"):
        portable._one_runtime(
            ordinal=1,
            pack_root=pack,
            output_root=tmp_path / "output",
            runtime={"image_id": f"sha256:{'1' * 64}"},
            daemon_fingerprint=_daemon_identity(),
        )
    assert cleanup == []


def test_false_cleanup_proof_cannot_publish_runtime_cleanup_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    container_id = "1" * 64
    monkeypatch.setattr(
        portable,
        "_new_container_identity",
        lambda ordinal: ("exact-owner", "a" * 32, f"run-{ordinal}"),
    )
    monkeypatch.setattr(portable, "_require_container_preflight_clear", lambda **_kwargs: None)
    monkeypatch.setattr(portable, "_require_same_daemon", lambda **_kwargs: None)

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[1] == "create":
            return subprocess.CompletedProcess(argv, 0, container_id, "")
        assert argv == ["docker", "start", "-a", container_id]
        return subprocess.CompletedProcess(argv, 0, "runtime", "")

    monkeypatch.setattr(portable, "_run", fake_run)
    monkeypatch.setattr(
        portable,
        "_reconcile_owned_container",
        lambda **_kwargs: {"container_id": container_id, "isolation": {}},
    )
    monkeypatch.setattr(
        portable,
        "_docker_inspect",
        lambda *_args, **_kwargs: {
            "State": {"Status": "exited", "ExitCode": 0, "OOMKilled": False}
        },
    )
    monkeypatch.setattr(portable, "_verify_container", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        portable,
        "_semantic_contract",
        lambda _root: {
            "semantic_output_file_count": 3,
            "semantic_output_inventory": [{"file": "sealed"}],
            "semantic_output_set_sha256": "2" * 64,
            "raw_assertion_bundle": {"assertion_count": 14},
            "assertion_count": 14,
            "fallback_count": 0,
        },
    )
    monkeypatch.setattr(
        portable,
        "_load_object",
        lambda *_args, **_kwargs: {"preflight": {"isolation_negative_probes": []}},
    )
    monkeypatch.setattr(
        portable,
        "_remove_owned_container",
        lambda **_kwargs: {
            "verified": False,
            "container_id_absent": True,
            "owner_nonce_absent": True,
            "exact_name_absent": True,
        },
    )
    with pytest.raises(portable.PortableClosureError, match="cleanup proof.*incomplete"):
        portable._one_runtime(
            ordinal=1,
            pack_root=pack,
            output_root=tmp_path / "output",
            runtime={"image_id": f"sha256:{'1' * 64}"},
            daemon_fingerprint=_daemon_identity(),
        )


def test_image_preload_inventory_fails_closed_and_binds_sealed_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = f"sha256:{'1' * 64}"
    foreign = f"sha256:{'2' * 64}"

    def response(stdout: str, *, returncode: int = 0):
        def fake_run(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([], returncode, stdout, "daemon failure")

        return fake_run

    monkeypatch.setattr(portable, "_run", response("", returncode=1))
    with pytest.raises(portable.PortableClosureError, match="image inventory query failed"):
        portable._prove_preload_image_state(
            image_id=expected,
            sealed_repo_tags=["example/f4:test"],
            require_image_absent=False,
            cwd=tmp_path,
        )

    for malformed in (
        "short\texample/f4\ttest\n",
        f"{expected}\texample/f4\n",
        f"{expected}\texample/f4\ttest\textra\n",
        f"{expected}\t<none>\ttest\n",
    ):
        monkeypatch.setattr(portable, "_run", response(malformed))
        with pytest.raises(portable.PortableClosureError):
            portable._prove_preload_image_state(
                image_id=expected,
                sealed_repo_tags=["example/f4:test"],
                require_image_absent=False,
                cwd=tmp_path,
            )

    monkeypatch.setattr(
        portable,
        "_run",
        response(f"{foreign}\texample/f4\ttest\n"),
    )
    with pytest.raises(portable.PortableClosureError, match="foreign image"):
        portable._prove_preload_image_state(
            image_id=expected,
            sealed_repo_tags=["example/f4:test"],
            require_image_absent=False,
            cwd=tmp_path,
        )

    monkeypatch.setattr(
        portable,
        "_run",
        response(f"{expected}\texample/f4\ttest\n"),
    )
    warm = portable._prove_preload_image_state(
        image_id=expected,
        sealed_repo_tags=["example/f4:test"],
        require_image_absent=False,
        cwd=tmp_path,
    )
    assert warm["expected_image_present"] is True
    assert warm["sealed_repo_tag_bindings"] == [
        {"repo_tag": "example/f4:test", "image_ids": [expected], "status": "expected-image"}
    ]

    monkeypatch.setattr(
        portable,
        "_run",
        response(
            f"{foreign}\tghcr.io/openhands/agent-server\t<none>\n"
            f"sha256:{'3' * 64}\t<none>\t<none>\n"
            f"{expected}\texample/f4\ttest\n"
        ),
    )
    assert portable._daemon_image_inventory(cwd=tmp_path) == [
        {
            "image_id": expected,
            "repository": "example/f4",
            "tag": "test",
            "repo_tag": "example/f4:test",
        },
        {
            "image_id": foreign,
            "repository": "ghcr.io/openhands/agent-server",
            "tag": "<none>",
            "repo_tag": None,
        },
        {
            "image_id": f"sha256:{'3' * 64}",
            "repository": "<none>",
            "tag": "<none>",
            "repo_tag": None,
        },
    ]
    warm_with_named_untagged_image = portable._prove_preload_image_state(
        image_id=expected,
        sealed_repo_tags=["example/f4:test"],
        require_image_absent=False,
        cwd=tmp_path,
    )
    assert warm_with_named_untagged_image["expected_image_present"] is True
    assert warm_with_named_untagged_image["row_count"] == 3

    with pytest.raises(portable.PortableClosureError, match="image-absent daemon"):
        portable._prove_preload_image_state(
            image_id=expected,
            sealed_repo_tags=["example/f4:test"],
            require_image_absent=True,
            cwd=tmp_path,
        )

    monkeypatch.setattr(portable, "_run", response(""))
    absent = portable._prove_preload_image_state(
        image_id=expected,
        sealed_repo_tags=["example/f4:test"],
        require_image_absent=True,
        cwd=tmp_path,
    )
    assert absent["expected_image_present"] is False


def test_receipt_publish_is_atomic_and_never_clobbers_existing_file(tmp_path: Path) -> None:
    source = _write(tmp_path / "receipt.tmp", b"new")
    destination = _write(tmp_path / "receipt.json", b"user-owned")
    with pytest.raises(portable.PortableClosureError, match="concurrently"):
        portable._publish_file_no_clobber(source, destination)
    assert destination.read_bytes() == b"user-owned"
    assert source.read_bytes() == b"new"

    destination.unlink()
    portable._publish_file_no_clobber(source, destination)
    assert destination.read_bytes() == b"new"
    assert not source.exists()


def _container_fixture(
    pack_root: Path,
    output: Path,
    *,
    name: str = "exact-owner",
    owner_nonce: str = "a" * 32,
    run_id: str = "run-1",
) -> tuple[dict[str, object], dict[str, object]]:
    environment = ["PATH=/opt/f4-runtime/.venv/bin"]
    runtime = {
        "image_id": f"sha256:{'1' * 64}",
        "image_identity": {"environment": environment},
    }
    container: dict[str, object] = {
        "Id": "1" * 64,
        "Name": f"/{name}",
        "Image": runtime["image_id"],
        "Config": {
            "Image": runtime["image_id"],
            "Entrypoint": portable.EXPECTED_ENTRYPOINT,
            "Cmd": portable.EXPECTED_CMD,
            "Env": environment,
            "User": "65532:65532",
            "WorkingDir": "/work",
            "Labels": {
                portable.OWNER_LABEL: owner_nonce,
                portable.RUN_LABEL: run_id,
            },
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "NetworkMode": "none",
            "CapDrop": ["ALL"],
            "Privileged": False,
            "Devices": [],
            "Binds": None,
            "PidMode": "",
            "IpcMode": "private",
            "UTSMode": "",
            "UsernsMode": "",
            "CgroupnsMode": "private",
            "SecurityOpt": ["no-new-privileges:true"],
            "PidsLimit": 256,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=268435456"},
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": str((pack_root / portable.SNAPSHOT_RELATIVE).resolve()),
                "Destination": "/capsule",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(output.resolve()),
                "Destination": "/output",
                "RW": True,
            },
        ],
    }
    return container, runtime


def test_container_contract_rejects_privilege_devices_and_environment_drift(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    snapshot = pack_root / portable.SNAPSHOT_RELATIVE
    output = tmp_path / "output"
    snapshot.mkdir(parents=True)
    output.mkdir()
    container, runtime = _container_fixture(pack_root, output)
    portable._verify_container(
        container,
        container_id="1" * 64,
        name="exact-owner",
        owner_nonce="a" * 32,
        run_id="run-1",
        runtime=runtime,
        snapshot_root=snapshot,
        output_dir=output,
    )
    for field, value in (
        ("Privileged", True),
        ("Devices", [{"PathOnHost": "/dev/null"}]),
    ):
        changed = json.loads(json.dumps(container))
        changed["HostConfig"][field] = value
        with pytest.raises(portable.PortableClosureError):
            portable._verify_container(
                changed,
                container_id="1" * 64,
                name="exact-owner",
                owner_nonce="a" * 32,
                run_id="run-1",
                runtime=runtime,
                snapshot_root=snapshot,
                output_dir=output,
            )
    changed = json.loads(json.dumps(container))
    changed["Config"]["Env"] = ["PATH=/tmp"]
    with pytest.raises(portable.PortableClosureError, match="environment"):
        portable._verify_container(
            changed,
            container_id="1" * 64,
            name="exact-owner",
            owner_nonce="a" * 32,
            run_id="run-1",
            runtime=runtime,
            snapshot_root=snapshot,
            output_dir=output,
        )
    for tmpfs_options in (
        "rw,noexec,nosuid,nodev,size=1",
        "rw,noexec,nosuid,nodev,size=2684354560",
        "rw,noexec,nosuid,nodev,size=268435456,extra",
    ):
        changed = json.loads(json.dumps(container))
        changed["HostConfig"]["Tmpfs"]["/tmp"] = tmpfs_options
        with pytest.raises(portable.PortableClosureError, match="tmpfs"):
            portable._verify_container(
                changed,
                container_id="1" * 64,
                name="exact-owner",
                owner_nonce="a" * 32,
                run_id="run-1",
                runtime=runtime,
                snapshot_root=snapshot,
                output_dir=output,
            )


def test_container_mount_source_uses_windows_path_identity(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    snapshot = pack_root / portable.SNAPSHOT_RELATIVE
    output = tmp_path / "output"
    snapshot.mkdir(parents=True)
    output.mkdir()
    container, runtime = _container_fixture(pack_root, output)
    equivalent = json.loads(json.dumps(container))
    for mount in equivalent["Mounts"]:
        mount["Source"] = mount["Source"].upper().replace("\\", "/")
    portable._verify_container(
        equivalent,
        container_id="1" * 64,
        name="exact-owner",
        owner_nonce="a" * 32,
        run_id="run-1",
        runtime=runtime,
        snapshot_root=snapshot,
        output_dir=output,
    )
    different = json.loads(json.dumps(container))
    different["Mounts"][0]["Source"] = r"Z:\definitely-different\snapshot"
    with pytest.raises(portable.PortableClosureError, match="mount"):
        portable._verify_container(
            different,
            container_id="1" * 64,
            name="exact-owner",
            owner_nonce="a" * 32,
            run_id="run-1",
            runtime=runtime,
            snapshot_root=snapshot,
            output_dir=output,
        )
