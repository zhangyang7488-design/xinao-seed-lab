from __future__ import annotations

import json
from pathlib import Path

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation import assertion_verifier_registry as registry
from xinao.foundation.closure import (
    FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
    FoundationProfileUnavailable,
    derive_foundation_closure_report,
    load_foundation_profile,
    resolve_foundation_profile,
    verify_foundation_closure_report,
)
from xinao.foundation.closure_pack import (
    ClosurePackError,
    build_foundation_closure_pack,
)
from xinao.foundation.foundation_implementation_model import (
    foundation_implementation_model,
    implementation_model_projection,
)


def _current_projection() -> Path:
    return registry.canonical_projection_path()


def test_current_projection_binds_live_authorities_and_exact_model() -> None:
    resolution = resolve_foundation_profile(_current_projection())

    assert resolution["status"] == "READY"
    assert resolution["authority_binding_valid"] is True
    assert resolution["human_spec_ref"]["sha256"] == (
        "6fc4a6bef2845fd4bd47e74a2b0379467714377a354cd98a49d8daa0327bf89a"
    )
    assert resolution["formal_contract_ref"]["sha256"] == (
        "c519dde39c738223078da7716f49ddcac69ea339339f5ce6b2a1acc968f7ec5b"
    )
    assert resolution["foundation_projection"]["derived_state"] == ("FOUNDATION_EXECUTION_READY")
    assert resolution["foundation_projection"]["does_not_imply_formal_research"] is True
    assert resolution["runtime_cutover"] == implementation_model_projection()
    assert resolution["implementation_model_ref"] == implementation_model_projection()
    assert resolution["missing_implementation_requirements"] == []
    assert resolution["blockers"] == []


def test_profile_loader_returns_exact_code_owned_inventory() -> None:
    profile = load_foundation_profile(_current_projection())
    model = foundation_implementation_model()

    assert profile["blocks"] == model["blocks"]
    assert set(profile["blocks"]) == set(registry.FOUNDATION_BLOCK_IDS)
    assert profile["_closure_meta"]["required_report_schema_version"] == (
        FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION
    )
    assert (
        profile["_closure_meta"]["implementation_model_sha256"]
        == (implementation_model_projection()["implementation_model_sha256"])
    )
    assert "formal_research_allowed" in profile["foundation_exclusions"]


def test_authority_seal_includes_current_material_and_pack_entrypoints() -> None:
    manifest = registry.build_canonical_code_manifest()
    sealed_paths = {entry["relative_path"] for entry in manifest["entries"]}

    assert {
        "scripts/build_current_foundation_closure_pack.py",
        "scripts/export_current_foundation_materials.py",
    } <= sealed_paths
    assert "tests/test_current_foundation_closure_clis.py" not in sealed_paths


def test_incomplete_report_preserves_closed_formal_gate() -> None:
    projection = _current_projection()
    report = derive_foundation_closure_report(
        {
            "report_id": "cutover-status",
            "version": "v2",
            "created_at": "2026-07-17T00:00:00+08:00",
        },
        blueprint_path=projection,
    )

    assert report["schema_version"] == FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION
    assert report["status"] == "PARTIAL"
    assert report["canonical_projection_bound"] is False
    assert report["foundation_execution_ready"] is False
    assert report["foundation_closed"] is False
    assert report["formal_research_allowed"] is False
    assert report["formal_research_gate"] == "CLOSED"
    assert {block["status"] for block in report["block_reports"].values()} == {"PARTIAL"}

    verification = verify_foundation_closure_report(report, blueprint_path=projection)
    assert verification["ok"] is False
    assert verification["foundation_execution_ready"] is False

    tampered = dict(report)
    tampered["formal_research_allowed"] = True
    tampered_body = dict(tampered)
    tampered_body.pop("artifact_hash")
    tampered["artifact_hash"] = canonical_sha256(tampered_body)
    rejected = verify_foundation_closure_report(tampered, blueprint_path=projection)
    assert rejected["ok"] is False
    assert rejected["checks"]["derived_report_fields_match"] is False


def test_pack_rejects_missing_current_input_inventory(
    tmp_path: Path,
) -> None:
    output = tmp_path / "closure-pack"

    with pytest.raises(ClosurePackError, match="input_evidence key mismatch"):
        build_foundation_closure_pack(
            output_root=output,
            input_evidence={},
            artifact_materials={},
            report_id="must-not-build",
            version="v2",
            created_at="2026-07-17T00:00:00+08:00",
        )

    assert output.exists()


def test_noncanonical_projection_is_rejected_without_reading_archived_profile(
    tmp_path: Path,
) -> None:
    forged = tmp_path / "blueprint.current_domain_research.json"
    forged.write_text(_current_projection().read_text(encoding="utf-8-sig"), encoding="utf-8")

    resolution = resolve_foundation_profile(forged)

    assert resolution["status"] == "NOT_PERFORMED"
    assert resolution["authority_binding_valid"] is False
    assert resolution["projection_ref"] == {}
    assert resolution["blockers"][0].startswith("authority_projection_not_canonical:")


def test_declared_contract_hash_drift_is_a_specific_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = json.loads(_current_projection().read_text(encoding="utf-8-sig"))
    value["authority"]["formal_admission_contract_sha256"] = "0" * 64
    forged = tmp_path / "blueprint.current_domain_research.json"
    forged.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(registry, "CANONICAL_PROJECTION_PATH", forged)

    resolution = resolve_foundation_profile(forged)

    assert resolution["status"] == "NOT_PERFORMED"
    assert resolution["authority_binding_valid"] is False
    assert "formal_contract_sha256_mismatch" in resolution["blockers"]


@pytest.mark.parametrize("extra_field", ("status", "required_artifact_types"))
def test_blueprint_cannot_define_or_hand_set_implementation_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra_field: str
) -> None:
    value = json.loads(_current_projection().read_text(encoding="utf-8-sig"))
    value["runtime_cutover"][extra_field] = "READY"
    forged = tmp_path / "blueprint.current_domain_research.json"
    forged.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(registry, "CANONICAL_PROJECTION_PATH", forged)

    resolution = resolve_foundation_profile(forged)

    assert resolution["status"] == "NOT_PERFORMED"
    assert "implementation_model_projection_fingerprint_mismatch" in resolution["blockers"]
    with pytest.raises(FoundationProfileUnavailable):
        load_foundation_profile(forged)


def test_projected_model_hash_drift_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = json.loads(_current_projection().read_text(encoding="utf-8-sig"))
    value["runtime_cutover"]["implementation_model_sha256"] = "0" * 64
    forged = tmp_path / "blueprint.current_domain_research.json"
    forged.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(registry, "CANONICAL_PROJECTION_PATH", forged)

    resolution = resolve_foundation_profile(forged)

    assert resolution["status"] == "NOT_PERFORMED"
    assert "implementation_model_projection_fingerprint_mismatch" in resolution["blockers"]


@pytest.mark.parametrize(
    "extra_field",
    ("FORMAL_AUTONOMOUS_DOMAIN_RESEARCH_ALLOWED", "admission_allowed"),
)
def test_verifier_rejects_resigned_extra_admission_field(
    extra_field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xinao.foundation.closure as closure

    projection = Path("projection.json")
    rebuilt = {
        "schema_version": FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
        "status": "VERIFIED",
        "block_reports": {},
        "bindings_complete": True,
        "canonical_projection_bound": True,
        "authority_snapshot_bound": True,
        "source_materials_self_contained": True,
        "canonical_bundle_replay_verified": True,
        "all_required_assertions_pass": True,
        "foundation_execution_ready": True,
        "foundation_closed": False,
        "formal_research_allowed": False,
        "formal_research_gate": "CLOSED",
        "legacy_a_g_gate_used": False,
        "manual_override_used": False,
    }
    rebuilt["artifact_hash"] = canonical_sha256(rebuilt)
    report = dict(rebuilt)
    report[extra_field] = True
    report_body = dict(report)
    report_body.pop("artifact_hash")
    report["artifact_hash"] = canonical_sha256(report_body)

    monkeypatch.setattr(closure, "resolve_foundation_profile", lambda _path: {"status": "READY"})
    monkeypatch.setattr(
        closure,
        "load_foundation_profile",
        lambda _path: {
            "_closure_meta": {
                "required_report_schema_version": FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION
            }
        },
    )
    monkeypatch.setattr(
        closure,
        "derive_foundation_closure_report",
        lambda _report, *, blueprint_path: rebuilt,
    )

    verification = verify_foundation_closure_report(report, blueprint_path=projection)

    assert verification["ok"] is False
    assert verification["foundation_execution_ready"] is False
    assert verification["checks"]["exact_top_level_keys"] is False
    assert verification["checks"]["report_replays_exactly"] is False
