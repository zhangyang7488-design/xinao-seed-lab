from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import build_f4_oci_data_capsule as subject
from xinao.foundation.f4_evidence_snapshot import canonical_sha256
from xinao.foundation.foundation_v4_relocation_capsule_builder import (
    F4_ARTIFACT_NAMES,
    F4_ASSERTION_IDS,
    F4_INPUT_NAMES,
)


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _closure_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "closure"
    input_root = root / "source_materials" / "inputs"
    artifact_root = root / "source_materials" / "artifacts" / "F4_research_factory"
    authority = _write_json(
        root / "authority_snapshot" / "authority_manifest.json",
        {"authority": "sealed"},
    )
    input_root.mkdir(parents=True)
    artifact_root.mkdir(parents=True)

    input_evidence: dict[str, dict[str, object]] = {}
    input_hashes: dict[str, str] = {}
    for index, name in enumerate(F4_INPUT_NAMES):
        if name == "compiler_code_sha256":
            path = authority
        else:
            path = input_root / f"{name}.{index}.bin"
            path.write_bytes(f"sealed-{name}".encode())
        sha256 = _file_sha256(path)
        input_hashes[name] = sha256
        input_evidence[name] = {
            "input_hash_key": name,
            "path": str(path.resolve()),
            "sha256": sha256,
            "size_bytes": path.stat().st_size,
        }

    artifacts: dict[str, dict[str, object]] = {}
    for index, name in enumerate(F4_ARTIFACT_NAMES):
        payload = {"object_type": name, "ordinal": index}
        path = _write_json(artifact_root / f"{name}.{index}.json", payload)
        staged = {
            "artifact_type": name,
            "code_hash": input_hashes["compiler_code_sha256"],
            "config_hash": input_hashes["compiler_config_sha256"],
            "input_hashes": dict(input_hashes),
            "payload": payload,
            "payload_sha256": canonical_sha256(payload),
            "source_ref": {
                "artifact_type": name,
                "path": str(path.resolve()),
                "sha256": _file_sha256(path),
                "size_bytes": path.stat().st_size,
            },
            "version": f"{name}@fixture",
        }
        artifacts[name] = {
            "staged_envelope": staged,
            "staged_envelope_content_sha256": canonical_sha256(staged),
        }

    request = {
        "artifacts": artifacts,
        "assertion_ids": list(F4_ASSERTION_IDS),
        "block_id": "F4_research_factory",
        "compiler_code_sha256": input_hashes["compiler_code_sha256"],
        "compiler_config_sha256": input_hashes["compiler_config_sha256"],
        "input_evidence": input_evidence,
        "input_hashes": input_hashes,
        "protocol_version": "xinao.assertion_bundle_protocol.v2",
        "schema_version": "xinao.assertion_request.v2",
    }
    _write_json(root / "assertion_requests" / "F4_research_factory.json", request)
    return root


def _admitted_fixture(root: Path) -> SimpleNamespace:
    input_root = root / "source_materials" / "inputs"
    artifact_root = root / "source_materials" / "artifacts" / "F4_research_factory"
    bindings = [
        SimpleNamespace(kind="input", name=path.stem, source_path=path)
        for path in input_root.iterdir()
    ]
    bindings.extend(
        SimpleNamespace(kind="artifact", name=path.stem, source_path=path)
        for path in artifact_root.iterdir()
    )
    bindings.append(
        SimpleNamespace(
            kind="input",
            name="compiler_code_sha256",
            source_path=root / "authority_snapshot" / "authority_manifest.json",
        )
    )
    return SimpleNamespace(
        root=root.resolve(),
        request_path=(root / "assertion_requests" / "F4_research_factory.json").resolve(),
        authority=SimpleNamespace(
            manifest_path=(root / "authority_snapshot" / "authority_manifest.json").resolve()
        ),
        bindings=tuple(bindings),
    )


def test_dynamic_lineage_inputs_replace_all_previous_hardcoded_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = tmp_path / "current"
    support = tmp_path / "support"
    verification = tmp_path / "live-verification.json"
    closure = _closure_fixture(tmp_path)
    monkeypatch.setattr(subject, "admit_f4_closure", lambda root: _admitted_fixture(root))

    roots, files = subject.logical_inputs(
        current_source_root=current,
        independent_support_root=support,
        live_verification=verification,
        closure_root=closure,
    )

    assert roots["current_source"] == current.resolve()
    assert roots["independent_support"] == support.resolve()
    assert files["bound_verification_0"] == verification.resolve()
    assert set(roots) == {
        "current_source",
        "independent_support",
        "live_pack",
        "negative_pack",
        "portfolio_pack",
        "closure_inputs",
        "closure_f4_artifacts",
    }
    assert set(files) == {
        "behavior_summary",
        "bound_verification_0",
        "bound_verification_1",
        "bound_verification_2",
        "closure_f4_request",
        "closure_authority_manifest",
    }
    assert roots["closure_inputs"] == (closure / "source_materials" / "inputs").resolve()
    assert (
        roots["closure_f4_artifacts"]
        == (closure / "source_materials" / "artifacts" / "F4_research_factory").resolve()
    )
    assert (
        files["closure_f4_request"]
        == (closure / "assertion_requests" / "F4_research_factory.json").resolve()
    )
    assert (
        files["closure_authority_manifest"]
        == (closure / "authority_snapshot" / "authority_manifest.json").resolve()
    )


def test_closure_identity_rejects_unbound_extra_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closure = _closure_fixture(tmp_path)
    admitted = _admitted_fixture(closure)
    monkeypatch.setattr(subject, "admit_f4_closure", lambda root: admitted)
    (closure / "source_materials" / "inputs" / "unbound.bin").write_bytes(b"extra")

    with pytest.raises(subject.RelocationCapsuleBuildError, match="exact six-file set"):
        subject.closure_identity_inputs(closure)


def test_closure_identity_rejects_unbound_extra_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closure = _closure_fixture(tmp_path)
    admitted = _admitted_fixture(closure)
    monkeypatch.setattr(subject, "admit_f4_closure", lambda root: admitted)
    artifact = closure / "source_materials" / "artifacts" / "F4_research_factory" / "unbound.json"
    artifact.write_text("{}", encoding="utf-8")

    with pytest.raises(subject.RelocationCapsuleBuildError, match="exact eight-file set"):
        subject.closure_identity_inputs(closure)
