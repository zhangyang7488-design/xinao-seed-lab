from __future__ import annotations

import json
from pathlib import Path

import pytest

from xinao.foundation import assertion_verifier_registry as registry
from xinao.foundation.authority_generation import (
    AuthorityGenerationError,
    generation_reference,
    load_generation_binding_from_projection,
    prepare_authority_generation,
    validate_authority_generation,
)
from xinao.foundation.foundation_implementation_model import foundation_implementation_model


def test_generation_is_content_addressed_exact_and_reusable(tmp_path: Path) -> None:
    first = prepare_authority_generation(
        projection_path=registry.canonical_projection_path(),
        owner_id="codex-owner-test",
        rationale="reviewed publication is compatible with the sealed F1-F4 inventory",
        generation_root=tmp_path / "generations",
    )
    second = prepare_authority_generation(
        projection_path=registry.canonical_projection_path(),
        owner_id="codex-owner-test",
        rationale="reviewed publication is compatible with the sealed F1-F4 inventory",
        generation_root=tmp_path / "generations",
    )

    assert first["reused"] is False
    assert second["reused"] is True
    assert first["manifest_path"] == second["manifest_path"]
    assert first["generation_root"].name == first["manifest"]["content_sha256"]
    assert set(path.name for path in first["generation_root"].iterdir()) == {
        "formal_contract_snapshot.txt",
        "generation_manifest.json",
        "human_spec_snapshot.txt",
        "owner_verdict.json",
    }

    projection = json.loads(registry.canonical_projection_path().read_text(encoding="utf-8-sig"))
    projection["authority"]["foundation_generation"] = generation_reference(first["manifest_path"])
    binding, reference = load_generation_binding_from_projection(projection)
    assert binding == first["binding"]
    assert reference["generation_content_sha256"] == first["manifest"]["content_sha256"]


def test_generation_material_tamper_fails_closed(tmp_path: Path) -> None:
    generation = prepare_authority_generation(
        projection_path=registry.canonical_projection_path(),
        owner_id="codex-owner-test",
        rationale="reviewed publication is compatible with the sealed F1-F4 inventory",
        generation_root=tmp_path / "generations",
    )
    contract = generation["generation_root"] / "formal_contract_snapshot.txt"
    contract.write_bytes(contract.read_bytes() + b"tamper")

    with pytest.raises(AuthorityGenerationError, match="material drifted"):
        validate_authority_generation(generation["manifest_path"])


def test_generation_reference_tamper_fails_closed(tmp_path: Path) -> None:
    generation = prepare_authority_generation(
        projection_path=registry.canonical_projection_path(),
        owner_id="codex-owner-test",
        rationale="reviewed publication is compatible with the sealed F1-F4 inventory",
        generation_root=tmp_path / "generations",
    )
    projection = json.loads(registry.canonical_projection_path().read_text(encoding="utf-8-sig"))
    reference = generation_reference(generation["manifest_path"])
    reference["manifest_sha256"] = "0" * 64
    projection["authority"]["foundation_generation"] = reference

    with pytest.raises(AuthorityGenerationError, match="reference drifted"):
        load_generation_binding_from_projection(projection)


def test_generation_cannot_be_reused_after_model_core_drift(tmp_path: Path) -> None:
    generation = prepare_authority_generation(
        projection_path=registry.canonical_projection_path(),
        owner_id="codex-owner-test",
        rationale="reviewed publication is compatible with the sealed F1-F4 inventory",
        generation_root=tmp_path / "generations",
    )
    drifted = dict(generation["binding"])
    drifted["implementation_model_core_sha256"] = "0" * 64

    with pytest.raises(RuntimeError, match="model core is not owner-reviewed"):
        foundation_implementation_model(drifted)
