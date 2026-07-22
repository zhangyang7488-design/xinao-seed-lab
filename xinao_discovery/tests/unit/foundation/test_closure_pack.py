from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from pathlib import Path

import pytest

from xinao.canonical import canonical_dumps
from xinao.foundation.assertion_bundle_runner import (
    PROTOCOL_VERSION,
    REQUEST_SCHEMA_VERSION,
    AssertionBundleRunnerError,
    build_bundle_bytes_v2,
)
from xinao.foundation.assertion_verifier_registry import (
    AUTHORITY_MANIFEST_SCHEMA_VERSION,
    AUTHORITY_SEAL_POLICY_ID,
    FOUNDATION_BLOCK_IDS,
    CanonicalVerifierError,
    canonical_blueprint_path,
    canonical_code_manifest_bytes,
    canonical_python_executable,
    canonical_registry,
    validate_canonical_code_manifest,
)
from xinao.foundation.closure_pack import build_foundation_closure_pack


def _invalid_request(**extra: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "block_id": "F1_settlement_world",
        "assertion_ids": ["semantic_rule_mapped_eq"],
        "input_evidence": {},
        "input_hashes": {},
        "artifacts": {},
        "compiler_code_sha256": "a" * 64,
        "compiler_config_sha256": "b" * 64,
    }
    request.update(extra)
    return request


def test_public_builder_has_no_caller_authority_surface() -> None:
    parameters = inspect.signature(build_foundation_closure_pack).parameters

    assert set(parameters) == {
        "output_root",
        "input_evidence",
        "artifact_materials",
        "report_id",
        "version",
        "created_at",
    }
    assert not {
        "blueprint_path",
        "assertion_bundle_verifiers",
        "block_producer_ids",
        "block_verifier_ids",
        "report_producer_ids",
        "independent_verifier_id",
        "python_executable",
    } & set(parameters)


@pytest.mark.parametrize(
    "legacy_name,legacy_value",
    [
        ("assertion_bundle_verifiers", {}),
        ("python_executable", "fake-python"),
        ("blueprint_path", Path("forged-blueprint.json")),
        ("independent_verifier_id", "caller-claims-independent"),
    ],
)
def test_legacy_caller_authority_inputs_are_rejected(
    tmp_path: Path, legacy_name: str, legacy_value: object
) -> None:
    values = {
        "output_root": tmp_path / "pack",
        "input_evidence": {},
        "artifact_materials": {},
        "report_id": "negative",
        "version": "v0",
        "created_at": "2026-07-15T00:00:00+08:00",
        legacy_name: legacy_value,
    }

    with pytest.raises(TypeError, match=legacy_name):
        build_foundation_closure_pack(**values)  # type: ignore[arg-type]


def test_registry_is_exact_package_bound_and_content_identified() -> None:
    registry = canonical_registry()
    package_root = (
        Path(__file__).resolve().parents[3] / "src" / "xinao" / "foundation" / "assertion_verifiers"
    ).resolve()

    assert tuple(registry) == FOUNDATION_BLOCK_IDS
    for block_id, entry in registry.items():
        assert entry.block_id == block_id
        assert entry.source_path.is_relative_to(package_root)
        assert entry.module_name.startswith("xinao.foundation.assertion_verifiers.")
        assert entry.checker_id.endswith(entry.source_sha256)
        assert "scripts.foundation_assertion_verifiers" not in entry.module_name


def test_code_manifest_is_exact_current_tree_and_tamper_fails(
    tmp_path: Path,
) -> None:
    raw = canonical_code_manifest_bytes()
    path = tmp_path / "compiler_code_manifest.json"
    path.write_bytes(raw)
    manifest = validate_canonical_code_manifest(path)
    file_sha256 = hashlib.sha256(raw).hexdigest()

    assert manifest["schema_version"] == AUTHORITY_MANIFEST_SCHEMA_VERSION
    assert manifest["policy_id"] == AUTHORITY_SEAL_POLICY_ID
    assert manifest["content_sha256"]
    assert file_sha256 != manifest["content_sha256"]
    roles = {entry["role"] for entry in manifest["entries"]}
    assert "source:xinao_discovery/src/xinao/canonical/__init__.py" in roles
    assert any(role.endswith("assertion_verifier_registry.py") for role in roles)
    assert any(role.endswith("assertion_verifiers/common.py") for role in roles)
    assert any(role.endswith("assertion_verifiers/f4_assertion_actuals.py") for role in roles)
    assert not any("/validation/" in role for role in roles)
    assert not any("/tests/" in role for role in roles)
    assert not any(role.startswith("lock:") for role in roles)

    tampered = json.loads(raw)
    tampered["policy_id"] = "attacker.self-authorized.v1"
    path.write_bytes(canonical_dumps(tampered))
    with pytest.raises(CanonicalVerifierError, match="does not match current sealed code"):
        validate_canonical_code_manifest(path)


def test_runner_rejects_any_expectation_or_oracle_field_before_execution() -> None:
    for field in ("expected", "required_assertions", "oracle", "blueprint_path"):
        with pytest.raises(AssertionBundleRunnerError, match="keys are not exact"):
            build_bundle_bytes_v2(
                request=_invalid_request(**{field: {"semantic_rule_mapped_eq": True}}),
                block_id="F1_settlement_world",
            )


def test_fixed_interpreter_isolated_mode_imports_canonical_registry() -> None:
    python = canonical_python_executable()
    completed = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            (
                "from xinao.foundation.assertion_verifier_registry import "
                "canonical_registry;print(','.join(canonical_registry()))"
            ),
        ],
        capture_output=True,
        check=False,
        cwd=python.parents[2],
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().split(",") == list(FOUNDATION_BLOCK_IDS)


def test_only_canonical_desktop_blueprint_has_production_identity(tmp_path: Path) -> None:
    assert canonical_blueprint_path().is_file()
    forged = tmp_path / "blueprint.json"
    forged.write_text("{}", encoding="utf-8")

    with pytest.raises(
        CanonicalVerifierError,
        match="current non-authoritative machine projection",
    ):
        canonical_blueprint_path(forged)
