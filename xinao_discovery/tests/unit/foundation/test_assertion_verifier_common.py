from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation.assertion_bundle_runner import build_assertion_request_v2
from xinao.foundation.assertion_verifiers.common import (
    INPUT_KEYS,
    AssertionActualsError,
    prepare_request,
)


def _request(tmp_path: Path) -> dict[str, Any]:
    input_refs = {}
    for index, key in enumerate(sorted(INPUT_KEYS)):
        path = tmp_path / f"{index:02d}-{key}.input"
        path.write_bytes(f"{key}\n".encode())
        input_refs[key] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return {
        "block_id": "test-block",
        "input_refs": input_refs,
        "artifact_refs": {},
        "required_assertion_ids": ["test-assertion"],
    }


def _prepare(request: dict[str, Any]):
    return prepare_request(
        request,
        expected_block_id="test-block",
        expected_artifact_types=frozenset(),
        expected_assertion_ids=("test-assertion",),
    )


def _request_v2(tmp_path: Path) -> tuple[dict[str, Any], Path, str]:
    input_refs = _request(tmp_path)["input_refs"]
    input_hashes = {key: ref["sha256"] for key, ref in input_refs.items()}
    payload = {"schema_version": "test-artifact.v1", "value": "bound"}
    artifact_path = tmp_path / "test-artifact.json"
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    request = build_assertion_request_v2(
        block_id="test-block",
        assertion_ids=("test-assertion",),
        input_refs=input_refs,
        input_hashes=input_hashes,
        materials={
            "TestArtifact": {
                "version": "test-artifact.v1",
                "source_ref": {
                    "path": str(artifact_path),
                    "sha256": artifact_sha256,
                },
                "payload": payload,
            }
        },
        compiler_code_sha256=input_hashes["compiler_code_sha256"],
        compiler_config_sha256=input_hashes["compiler_config_sha256"],
    )
    return request, artifact_path.resolve(), artifact_sha256


def _prepare_v2(request: dict[str, Any]):
    return prepare_request(
        request,
        expected_block_id="test-block",
        expected_artifact_types=frozenset({"TestArtifact"}),
        expected_assertion_ids=("test-assertion",),
    )


def test_prepare_request_accepts_only_the_exact_ten_input_inventory(tmp_path: Path) -> None:
    prepared = _prepare(_request(tmp_path))

    assert set(prepared.input_paths) == INPUT_KEYS
    assert len(prepared.input_hashes) == 10


@pytest.mark.parametrize("mutation", ("missing", "extra"))
def test_prepare_request_rejects_missing_or_extra_input_key(
    tmp_path: Path,
    mutation: str,
) -> None:
    request = _request(tmp_path)
    if mutation == "missing":
        request["input_refs"].pop("f3_prior_draft_sha256")
    else:
        request["input_refs"]["unclassified_sha256"] = next(iter(request["input_refs"].values()))

    with pytest.raises(AssertionActualsError, match="input_refs key mismatch"):
        _prepare(request)


def test_prepare_request_rejects_changed_input_bytes_with_old_hash(tmp_path: Path) -> None:
    request = _request(tmp_path)
    ref = request["input_refs"]["f3_external_synthesis_sha256"]
    Path(ref["path"]).write_bytes(b"tampered")

    with pytest.raises(AssertionActualsError, match="hash mismatch"):
        _prepare(request)


def test_prepare_request_accepts_and_preserves_the_v2_bridge(tmp_path: Path) -> None:
    request, artifact_path, artifact_sha256 = _request_v2(tmp_path)

    prepared = _prepare_v2(request)

    assert set(prepared.input_paths) == INPUT_KEYS
    assert prepared.input_hashes == request["input_hashes"]
    assert prepared.artifact_paths == {"TestArtifact": artifact_path}
    assert prepared.artifact_hashes == {"TestArtifact": artifact_sha256}
    assert prepared.artifact_versions == {"TestArtifact": "test-artifact.v1"}


@pytest.mark.parametrize("binding", ("input_hashes", "code_hash", "config_hash"))
def test_prepare_request_rejects_resealed_v2_envelope_binding_drift(
    tmp_path: Path,
    binding: str,
) -> None:
    request, _, _ = _request_v2(tmp_path)
    wrapper = request["artifacts"]["TestArtifact"]
    envelope = wrapper["staged_envelope"]
    if binding == "input_hashes":
        envelope[binding] = {**envelope[binding], "baseline_sha256": "f" * 64}
    else:
        envelope[binding] = "f" * 64
    wrapper["staged_envelope_content_sha256"] = canonical_sha256(envelope)

    with pytest.raises(AssertionActualsError, match="envelope binding mismatch"):
        _prepare_v2(request)
