from __future__ import annotations

import json
from pathlib import Path

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation import assertion_verifier_registry as registry
from xinao.foundation.closure import (
    FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
    MISSING_IMPLEMENTATION_REQUIREMENTS,
    FoundationProfileUnavailable,
    derive_foundation_closure_report,
    load_foundation_profile,
    resolve_foundation_profile,
    verify_foundation_closure_report,
)
from xinao.foundation.closure_pack import (
    ClosurePackNotPerformed,
    build_foundation_closure_pack,
)


def _current_projection() -> Path:
    return registry.canonical_projection_path()


def test_current_projection_binds_live_authorities_but_profile_is_not_performed() -> None:
    resolution = resolve_foundation_profile(_current_projection())

    assert resolution["status"] == "NOT_PERFORMED"
    assert resolution["authority_binding_valid"] is True
    assert resolution["human_spec_ref"]["sha256"] == (
        "6fc4a6bef2845fd4bd47e74a2b0379467714377a354cd98a49d8daa0327bf89a"
    )
    assert resolution["formal_contract_ref"]["sha256"] == (
        "c519dde39c738223078da7716f49ddcac69ea339339f5ce6b2a1acc968f7ec5b"
    )
    assert resolution["foundation_projection"]["derived_state"] == (
        "FOUNDATION_EXECUTION_READY"
    )
    assert resolution["foundation_projection"]["does_not_imply_formal_research"] is True
    assert resolution["runtime_cutover"]["status"] == "NOT_PERFORMED"
    assert resolution["missing_implementation_requirements"] == list(
        MISSING_IMPLEMENTATION_REQUIREMENTS
    )
    assert any(
        blocker.startswith("runtime_cutover_declares_not_performed:")
        for blocker in resolution["blockers"]
    )


def test_profile_loader_raises_structured_not_performed() -> None:
    with pytest.raises(FoundationProfileUnavailable) as caught:
        load_foundation_profile(_current_projection())

    assert caught.value.resolution["status"] == "NOT_PERFORMED"
    assert caught.value.resolution["authority_binding_valid"] is True
    assert "NOT_PERFORMED" in str(caught.value)


def test_report_and_independent_verifier_preserve_closed_formal_gate() -> None:
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
    assert report["status"] == "NOT_PERFORMED"
    assert report["canonical_projection_bound"] is True
    assert report["foundation_execution_ready"] is False
    assert report["foundation_closed"] is False
    assert report["formal_research_allowed"] is False
    assert report["formal_research_gate"] == "CLOSED"
    assert {block["status"] for block in report["block_reports"].values()} == {
        "NOT_PERFORMED"
    }

    verification = verify_foundation_closure_report(report, blueprint_path=projection)
    assert verification["ok"] is True
    assert verification["status"] == "NOT_PERFORMED"
    assert verification["foundation_execution_ready"] is False

    tampered = dict(report)
    tampered["formal_research_allowed"] = True
    tampered_body = dict(tampered)
    tampered_body.pop("artifact_hash")
    tampered["artifact_hash"] = canonical_sha256(tampered_body)
    rejected = verify_foundation_closure_report(tampered, blueprint_path=projection)
    assert rejected["ok"] is False
    assert rejected["checks"]["formal_research_remains_closed"] is False


def test_pack_fails_before_creating_output_when_profile_is_not_admitted(
    tmp_path: Path,
) -> None:
    output = tmp_path / "closure-pack"

    with pytest.raises(ClosurePackNotPerformed) as caught:
        build_foundation_closure_pack(
            output_root=output,
            input_evidence={},
            artifact_materials={},
            report_id="must-not-build",
            version="v2",
            created_at="2026-07-17T00:00:00+08:00",
        )

    assert caught.value.status == "NOT_PERFORMED"
    assert caught.value.resolution["authority_binding_valid"] is True
    assert not output.exists()


def test_noncanonical_projection_is_rejected_without_reading_archived_profile(
    tmp_path: Path,
) -> None:
    forged = tmp_path / "blueprint.current_domain_research.json"
    forged.write_text(
        _current_projection().read_text(encoding="utf-8-sig"), encoding="utf-8"
    )

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


@pytest.mark.parametrize(
    "extra_field",
    ("FORMAL_AUTONOMOUS_DOMAIN_RESEARCH_ALLOWED", "admission_allowed"),
)
def test_not_performed_verifier_rejects_resigned_extra_admission_field(
    extra_field: str,
) -> None:
    projection = _current_projection()
    report = derive_foundation_closure_report(
        {
            "report_id": "resigned-extra-field",
            "version": "v2",
            "created_at": "2026-07-17T00:00:00+08:00",
        },
        blueprint_path=projection,
    )
    report[extra_field] = True
    report_body = dict(report)
    report_body.pop("artifact_hash")
    report["artifact_hash"] = canonical_sha256(report_body)

    verification = verify_foundation_closure_report(report, blueprint_path=projection)

    assert verification["ok"] is False
    assert verification["status"] == "NOT_PERFORMED"
    assert verification["foundation_execution_ready"] is False
    assert verification["checks"]["exact_top_level_keys"] is False
    assert verification["checks"]["report_replays_exactly"] is False
