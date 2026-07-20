from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from scripts import run_f4_snapshot_stage0 as subject


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_addressed(core: dict[str, object]) -> dict[str, object]:
    return {**core, "content_sha256": subject._canonical_sha256(core)}


def test_image_contract_verifies_image_owned_dockerfile_writer_and_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    writer = tmp_path / "write_execution_contract.py"
    lock = tmp_path / "uv.lock"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    writer.write_text("# writer\n", encoding="utf-8")
    lock.write_text("version = 1\n", encoding="utf-8")
    core = {
        "schema_version": subject.CONTRACT_SCHEMA,
        "authority_manifest_sha256": "1" * 64,
        "authority_content_sha256": "2" * 64,
        "data_manifest_sha256": "3" * 64,
        "data_content_sha256": "4" * 64,
        "dockerfile_sha256": _sha(dockerfile),
        "contract_writer_sha256": _sha(writer),
        "verifier_lock_sha256": _sha(lock),
        "python_base_image": subject.PYTHON_BASE_IMAGE,
        "uv_base_image": subject.UV_BASE_IMAGE,
        "authority_retained_identity": subject.AUTHORITY_RETAINED_IDENTITY,
    }
    contract = {**core, "content_sha256": subject._canonical_sha256(core)}
    contract_path = tmp_path / "execution_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    monkeypatch.setattr(subject, "IMAGE_CONTRACT", contract_path)
    monkeypatch.setattr(subject, "IMAGE_DOCKERFILE", dockerfile)
    monkeypatch.setattr(subject, "IMAGE_CONTRACT_WRITER", writer)
    monkeypatch.setattr(subject, "VERIFIER_LOCK", lock)

    assert subject._verify_image_contract() == contract

    drifted = dict(contract)
    drifted["python_base_image"] = "python@example"
    drifted_core = dict(drifted)
    drifted_core.pop("content_sha256")
    drifted["content_sha256"] = subject._canonical_sha256(drifted_core)
    contract_path.write_text(json.dumps(drifted), encoding="utf-8")
    with pytest.raises(subject.Stage0Error, match="base identity drifted"):
        subject._verify_image_contract()

    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    writer.write_text("# drift\n", encoding="utf-8")
    with pytest.raises(subject.Stage0Error, match="contract writer identity drifted"):
        subject._verify_image_contract()


def test_stage0_rejects_host_xinao_runtime_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("XINAO_F4_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XINAO_F4_SNAPSHOT_MANIFEST", "/host/override")

    with pytest.raises(subject.Stage0Error, match="environment override rejected"):
        subject._reject_host_runtime_overrides()


def test_exact_inventory_rejects_extra_file(tmp_path: Path) -> None:
    root = tmp_path / "capsule"
    root.mkdir()
    manifest = root / "snapshot_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    payload = root / "payload.json"
    payload.write_text("{}", encoding="utf-8")
    rows = [
        {
            "relative_path": "payload.json",
            "sha256": _sha(payload),
            "size_bytes": payload.stat().st_size,
        }
    ]
    (root / "undeclared.json").write_text("{}", encoding="utf-8")

    with pytest.raises(subject.Stage0Error, match="inventory is not exact"):
        subject._exact_inventory(
            root=root,
            manifest_path=manifest,
            rows=rows,
            label="test capsule",
        )


def test_runtime_dependency_smoke_uses_lexical_venv_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = Path(os.path.abspath(sys.executable))
    monkeypatch.setattr(subject, "RUNTIME_VENV_ROOT", Path(sys.prefix))
    monkeypatch.setattr(subject, "RUNTIME_VENV_BIN", launcher.parent)

    result = subject._dependency_import_smoke({"external_module_roots": ["__future__", "json"]})

    assert result["status"] == "VERIFIED"
    assert result["python_executable"] == str(launcher)
    assert result["external_module_count"] == 2
    assert result["failure_count"] == 0


def test_preflight_hashes_build_smoke_before_installing_read_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xinao.foundation import f4_authority_source_pack, f4_evidence_snapshot

    authority = {"authority": "verified"}
    data = {"data": "verified"}
    smoke = {"status": "VERIFIED", "content_sha256": "1" * 64}
    contract = {
        "content_sha256": "2" * 64,
        "authority_manifest_sha256": "3" * 64,
        "authority_content_sha256": "4" * 64,
        "data_manifest_sha256": "5" * 64,
        "data_content_sha256": "6" * 64,
    }
    hook_installed = False
    smoke_path = tmp_path / "dependency_import_smoke.json"
    smoke_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(subject, "IMAGE_DEPENDENCY_SMOKE", smoke_path)
    monkeypatch.setattr(subject, "TRACE_ROOT", tmp_path / "traces")
    monkeypatch.setattr(subject, "_reject_host_runtime_overrides", lambda: None)
    monkeypatch.setattr(subject, "_verify_image_contract", lambda: contract)
    monkeypatch.setattr(subject, "_verify_authority", lambda value: authority)
    monkeypatch.setattr(subject, "_verify_data_capsule", lambda value: data)
    monkeypatch.setattr(subject, "_filter_and_bind_imports", lambda: [])
    monkeypatch.setattr(subject, "_isolation_negative_probes", lambda: {})
    monkeypatch.setattr(subject, "_dependency_import_smoke", lambda value: smoke)
    monkeypatch.setattr(subject, "_load_json_object", lambda path, label: smoke)
    monkeypatch.setattr(
        f4_authority_source_pack,
        "verify_authority_source_pack",
        lambda path: authority,
    )
    monkeypatch.setattr(
        f4_evidence_snapshot,
        "verify_snapshot_manifest",
        lambda path: data,
    )

    def install_boundary() -> None:
        nonlocal hook_installed
        hook_installed = True

    def hash_file(path: Path) -> str:
        if path == smoke_path and hook_installed:
            pytest.fail("build smoke was read after the boundary was installed")
        return "7" * 64

    monkeypatch.setattr(subject, "_install_read_boundary", install_boundary)
    monkeypatch.setattr(subject, "_file_sha256", hash_file)

    result, observed_data = subject.preflight()

    assert hook_installed is True
    assert observed_data == data
    assert result["build_dependency_import_smoke_sha256"] == "7" * 64


def test_common_authority_projection_binds_request_and_semantic_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f4_source = "xinao_discovery/src/xinao/foundation/assertion_verifiers/f4_assertion_actuals.py"
    carrier_source = subject.CARRIER_SOURCE
    common_core = {
        "schema_version": "xinao.compiler_code_manifest.v3",
        "entries": [
            {
                "relative_path": f4_source,
                "sha256": "1" * 64,
                "size": 17,
            },
            {
                "relative_path": "xinao_discovery/src/xinao/canonical.py",
                "sha256": "2" * 64,
                "size": 23,
            },
        ],
        "registry": {
            "F4_research_factory": {
                "source_sha256": "1" * 64,
            }
        },
    }
    common = _content_addressed(common_core)
    common_path = tmp_path / "authority_manifest.json"
    common_path.write_bytes(subject._canonical_bytes(common))
    monkeypatch.setattr(subject, "COMMON_AUTHORITY_MANIFEST", common_path)
    image_authority = {
        "python_sources": [
            {
                "relative_path": f4_source,
                "sha256": "1" * 64,
                "size_bytes": 17,
            },
            {
                "relative_path": "xinao_discovery/src/xinao/canonical.py",
                "sha256": "2" * 64,
                "size_bytes": 23,
            },
            {
                "relative_path": carrier_source,
                "sha256": "3" * 64,
                "size_bytes": 31,
            },
        ]
    }
    request = {"compiler_code_sha256": _sha(common_path)}

    projection = subject._common_authority_projection(
        request=request,
        image_authority=image_authority,
    )

    assert projection["status"] == "VERIFIED"
    assert projection["semantic_source_count"] == 2
    assert projection["carrier_source_count"] == 1
    assert projection["f4_actuals_source_sha256"] == "1" * 64
    assert projection["common_authority_manifest_sha256"] == _sha(common_path)

    image_authority["python_sources"][1]["sha256"] = "4" * 64
    with pytest.raises(subject.Stage0Error, match="differs from common authority"):
        subject._common_authority_projection(
            request=request,
            image_authority=image_authority,
        )


def test_common_assertion_bundle_is_exact_fourteen_true_actuals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xinao.foundation import assertion_bundle_runner

    assertion_ids = [f"assertion-{index:02d}" for index in range(14)]
    request = {"assertion_ids": assertion_ids}
    bundle_core = {
        "schema_version": "xinao.assertion_actual_bundle.v2",
        "block_id": "F4_research_factory",
        "request_sha256": "5" * 64,
        "assertion_actuals": {key: True for key in assertion_ids},
    }
    bundle = _content_addressed(bundle_core)
    raw = subject._canonical_bytes(bundle)
    monkeypatch.setattr(subject, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(
        assertion_bundle_runner,
        "build_bundle_bytes_v2",
        lambda **kwargs: raw,
    )

    result = subject._build_common_assertion_bundle(request)

    output = tmp_path / subject.COMMON_BUNDLE_NAME
    assert output.read_bytes() == raw
    assert result["assertion_count"] == 14
    assert result["sha256"] == _sha(output)
    assert result["content_sha256"] == bundle["content_sha256"]

    bundle_core["assertion_actuals"][assertion_ids[0]] = False
    rejected = _content_addressed(bundle_core)
    monkeypatch.setattr(
        assertion_bundle_runner,
        "build_bundle_bytes_v2",
        lambda **kwargs: subject._canonical_bytes(rejected),
    )
    with pytest.raises(subject.Stage0Error, match="exact 14 verified actuals"):
        subject._build_common_assertion_bundle(request)
