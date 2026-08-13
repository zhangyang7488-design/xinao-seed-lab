from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest
from scripts import build_worker_package_batch as builder
from scripts import validate_worker_package_batch as preflight
from services.agent_runtime.audit_adjudication import (
    build_audit_assessment,
    build_owner_adjudication,
)
from services.agent_runtime.dispatch_economics import (
    DispatchEconomicsError,
    build_neutral_output_contract,
    validate_dispatch_envelope,
    validate_package_batch_manifest,
)
from tests.test_dispatch_economics import (
    _fixture,
    _owner_adoption_event,
    _owner_event,
    _seal_dispatch,
    _worker_event,
)


def _logical_spec(
    fixture: dict[str, object],
    *,
    rewrite: Callable[[str], str] | None = None,
) -> dict[str, object]:
    manifest = fixture["manifest"]

    def logical(value: object) -> str:
        text = str(value)
        return rewrite(text) if rewrite else text

    packages = []
    for package in manifest["packages"]:
        acceptance = copy.deepcopy(package["acceptance"])
        schema_ref = acceptance.pop("json_schema_ref", None)
        if schema_ref:
            acceptance["json_schema_path"] = logical(schema_ref["path"])
        row = {
            "package_id": package["package_id"],
            "work_key": package["work_key"],
            "work_class": package["work_class"],
            "role": package["role"],
            "phase": package["phase"],
            "prompt_path": logical(package["prompt_ref"]["path"]),
            "context_manifest_path": logical(package["context_manifest_ref"]["path"]),
            "input_paths": [logical(item["path"]) for item in package["input_refs"]],
            "rules_path": logical(package["rules_ref"]["path"]),
            "write_domains": list(package["write_domains"]),
            "candidate_only": package["candidate_only"],
            "allowed_output_root": logical(package["allowed_output_root"]),
            "cwd": logical(package["cwd"]),
            "depends_on": copy.deepcopy(package["depends_on"]),
            "acceptance": acceptance,
            "timeout_sec": package["timeout_sec"],
        }
        if package.get("prior_attempt_receipt_ref"):
            row["prior_attempt_receipt_ref"] = {
                "path": logical(package["prior_attempt_receipt_ref"]["path"])
            }
        if package.get("prior_logical_contract_ref"):
            row["prior_logical_contract_ref"] = {
                "path": logical(package["prior_logical_contract_ref"]["path"])
            }
        if package.get("audit_assessment_ref"):
            row["audit_assessment_path"] = logical(package["audit_assessment_ref"]["path"])
        if package.get("audit_adjudication_ref"):
            row["audit_adjudication_path"] = logical(package["audit_adjudication_ref"]["path"])
        if package.get("prior_audit_adjudication_refs"):
            row["prior_audit_adjudication_paths"] = [
                logical(item["path"]) for item in package["prior_audit_adjudication_refs"]
            ]
        if package.get("audit_role"):
            row["audit_role"] = package["audit_role"]
        packages.append(row)
    return {
        "schema_version": "xinao.worker_package_batch_spec.v1",
        "external_input_admission": {
            "status": "owner_reviewed_redacted",
            "scope": "all_package_sources",
            "reviewer_role": "codex_owner",
        },
        "parent_work_key": manifest["parent_work_key"],
        "candidate_output_base": logical(manifest["candidate_output_base"]),
        "epoch_id": "epoch-1",
        "graph_revision": manifest["graph_revision"],
        "predecessor_manifest_ref": copy.deepcopy(manifest["predecessor_manifest_ref"]),
        "reseal_of": copy.deepcopy(manifest["reseal_of"]),
        "affected_cone": list(manifest["affected_cone"]),
        "limits": copy.deepcopy(manifest["limits"]),
        "packages": packages,
    }


def _read_json(path: str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _audit_gate_inputs(
    tmp_path: Path,
    *,
    work_key: str,
    evidence_path: Path,
) -> tuple[Path, Path]:
    evidence_ref = {
        "path": str(evidence_path),
        "sha256": builder._sha(evidence_path),
    }

    def pin(label: str) -> str:
        return hashlib.sha256(label.encode()).hexdigest()

    assessment = build_audit_assessment(
        audit_id="audit-repair-gate",
        work_key=work_key,
        assessor_identity={
            "provider_id": "provider-a",
            "profile_ref": "profile:independent-audit",
            "model_id": "model:strong-audit",
            "transport_id": "worker-pool",
        },
        assessment_plan={
            "methods": ["read", "replay"],
            "objects": ["source", "evidence"],
            "depth": "bounded",
            "coverage": "verdict-changing evidence",
            "blocking_severities": ["high"],
            "in_scope": ["frozen object"],
            "out_of_scope": ["expanded platform"],
        },
        scope_pins={
            "object_sha256": pin("object"),
            "scope_sha256": pin("scope"),
            "threat_model_sha256": pin("threat"),
            "completion_bar_sha256": pin("bar"),
        },
        required_evidence_refs=[evidence_ref],
        evidence_access={
            "status": "VERIFIED",
            "mode": "DIRECT_TOOL",
            "package_ref": evidence_ref,
            "accessed_evidence_refs": [evidence_ref],
            "limitations": [],
        },
        candidate_output={
            "schema_version": "xinao.audit_candidate_findings.v1",
            "verdict": "CANDIDATE_FINDINGS",
            "summary": "candidate-only result",
            "findings": [
                {
                    "finding_id": "finding-1",
                    "family": "identity-binding",
                    "title": "reproducible bypass",
                    "claim": "the frozen identity can be replaced",
                    "severity_claim": "high",
                    "evidence_citations": [
                        {
                            "path": str(evidence_path),
                            "source_sha256": evidence_ref["sha256"],
                            "line_start": 1,
                            "line_end": 1,
                            "content_sha256": evidence_ref["sha256"],
                        }
                    ],
                    "reproduction_conditions": ["replace identity before use"],
                    "finding_kind": "CANDIDATE_FINDING",
                }
            ],
            "limitations": [],
            "authority": False,
            "completion_claim_allowed": False,
            "repair_authorized": False,
        },
    )
    adjudication = build_owner_adjudication(
        assessment=assessment,
        finding_id="finding-1",
        owner_identity="codex-main",
        disposition="BLOCKING",
        severity="high",
        owner_reproduction={
            "status": "VERIFIED",
            "method": "Owner isolated local replay",
            "evidence_refs": [evidence_ref],
        },
    )
    assessment_path = tmp_path / "assessment.json"
    adjudication_path = tmp_path / "adjudication.json"
    _write_json(assessment_path, assessment)
    _write_json(adjudication_path, adjudication)
    return assessment_path, adjudication_path


def test_high_value_audit_is_candidate_only_and_uses_canonical_candidate_schema(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    spec = _logical_spec(fixture)
    spec["packages"][0]["work_class"] = "high_value_audit"
    spec["packages"][0]["audit_role"] = "cognitive_review"

    manifest = builder.build_neutral_manifest(spec)
    package = manifest["packages"][0]

    assert package["candidate_only"] is True
    assert package["write_domains"] == []
    assert package["audit_role"] == "cognitive_review"
    assert package["cannot_access_filesystem"] is True
    assert package["tool_execution_allowed"] is False
    assert package["evaluator_output_authority"] == "candidate_only"
    assert package["acceptance"]["require_json_object"] is True
    assert package["acceptance"]["json_schema_ref"]["path"].endswith(
        "audit_candidate_findings.v1.schema.json"
    )


def test_audit_repair_manifest_requires_hash_bound_owner_authorization(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    spec = _logical_spec(fixture)
    package_spec = spec["packages"][0]
    evidence_path = Path(package_spec["input_paths"][0])
    assessment_path, adjudication_path = _audit_gate_inputs(
        tmp_path,
        work_key=str(package_spec["work_key"]),
        evidence_path=evidence_path,
    )
    package_spec.update(
        {
            "work_class": "audit_repair",
            "audit_assessment_path": str(assessment_path),
            "audit_adjudication_path": str(adjudication_path),
        }
    )

    manifest = builder.build_neutral_manifest(spec)
    package = manifest["packages"][0]
    assert package["audit_assessment_ref"] in package["input_refs"]
    assert package["audit_adjudication_ref"] in package["input_refs"]

    tampered = json.loads(adjudication_path.read_text(encoding="utf-8"))
    tampered["repair_authorized"] = False
    _write_json(adjudication_path, tampered)
    with pytest.raises(DispatchEconomicsError, match="adjudication_sha256 mismatch"):
        builder.build_neutral_manifest(spec)


def test_audit_repair_provider_inputs_share_snapshot_catalog_and_manifest(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    spec = _logical_spec(fixture)
    package_spec = spec["packages"][0]
    evidence_path = Path(package_spec["input_paths"][0])
    assessment_path, adjudication_path = _audit_gate_inputs(
        tmp_path,
        work_key=str(package_spec["work_key"]),
        evidence_path=evidence_path,
    )
    package_spec.update(
        {
            "work_class": "audit_repair",
            "audit_assessment_path": str(assessment_path),
            "audit_adjudication_path": str(adjudication_path),
        }
    )
    prior_adjudication_path = tmp_path / "prior-adjudication.json"
    prior_adjudication = _read_json(str(adjudication_path))
    prior_adjudication["finding_family"] = "unrelated-prior-family"
    prior_adjudication.pop("adjudication_sha256")
    prior_adjudication["adjudication_sha256"] = builder._canonical_sha(prior_adjudication)
    _write_json(prior_adjudication_path, prior_adjudication)
    package_spec["prior_audit_adjudication_paths"] = [str(prior_adjudication_path)]

    frozen, snapshot, bindings = builder.snapshot_package_spec_inputs(
        spec,
        snapshot_root=tmp_path / "sealed-inputs",
    )
    manifest = builder.build_neutral_manifest(
        frozen,
        path_resolver=builder.build_path_resolver(exact_bindings=bindings),
    )
    package = manifest["packages"][0]
    catalog_ref = snapshot["package_catalogs"][0]["catalog_ref"]
    catalog = _read_json(str(catalog_ref["path"]))

    assert package["audit_assessment_ref"] in package["input_refs"]
    assert package["audit_adjudication_ref"] in package["input_refs"]
    assert package["prior_audit_adjudication_refs"][0] in package["input_refs"]
    assert len(catalog["entries"]) == len(package["input_refs"]) == 4
    assert {row["sha256"] for row in catalog["entries"]} == {
        row["sha256"] for row in package["input_refs"]
    }


def _route_receipt(transport_id: str) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "xinao.supervisor_worker_decision_receipt.v1",
        "decision": "selected",
        "selected_candidate": {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": "grok-4.6",
            "transport_id": transport_id,
            "declared_active": True,
            "healthy": True,
            "positive_benefit": True,
        },
    }
    receipt["decision_sha256"] = builder._canonical_sha(receipt)
    return receipt


def test_route_bound_envelopes_keep_neutral_manifest_bytes_but_not_dispatch_identity(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    manifest = builder.build_neutral_manifest(_logical_spec(fixture))
    manifest_path = tmp_path / "neutral.json"
    manifest_ref = {
        "path": str(manifest_path),
        "sha256": builder._atomic_json(manifest_path, manifest),
    }
    manifest_bytes = manifest_path.read_bytes()
    snapshot = _read_json(str(fixture["quota_ref"]["path"]))
    a_receipt = _route_receipt("direct-grok-worker-pool")
    b_receipt = _route_receipt("temporal-docker-langgraph")
    a = builder.build_route_bound_dispatch_envelope(
        leg="A",
        manifest_ref=manifest_ref,
        package_ids=["p1"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=fixture["quota_ref"],
        selection=a_receipt,
        selection_ref={"path": "selection-a.json", "sha256": "1" * 64},
    )
    b = builder.build_route_bound_dispatch_envelope(
        leg="B",
        manifest_ref=manifest_ref,
        package_ids=["p1"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=fixture["quota_ref"],
        selection=b_receipt,
        selection_ref={"path": "selection-b.json", "sha256": "2" * 64},
    )

    assert a["package_manifest_ref"] == b["package_manifest_ref"] == manifest_ref
    assert manifest_path.read_bytes() == manifest_bytes
    assert a["selection"]["transport_id"] == "direct-grok-worker-pool"
    assert "execution_adapter" not in a
    assert b["selection"]["transport_id"] == "temporal-docker-langgraph"
    assert b["execution_adapter"]["provider_transport_id"] == "grok_cli_json"
    assert (
        a["selection"]["route_decision_binding_sha256"]
        != b["selection"]["route_decision_binding_sha256"]
    )


def test_builder_requires_rules_path_and_derives_neutral_output_contract(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec = _logical_spec(fixture)
    expected_rules_ref = copy.deepcopy(fixture["manifest"]["packages"][0]["rules_ref"])
    manifest = builder.build_neutral_manifest(spec)
    package = manifest["packages"][0]
    assert package["rules_ref"] == expected_rules_ref
    assert package["rules_sha256"] == expected_rules_ref["sha256"]
    assert (
        package["output_contract_sha256"]
        == fixture["manifest"]["packages"][0]["output_contract_sha256"]
    )
    assert build_neutral_output_contract(package["acceptance"]) == {
        "result_format": "text",
        "result_json_schema_sha256": "",
        "min_result_chars": 1,
        "required_result_markers": ["OK"],
    }

    missing_rules = copy.deepcopy(spec)
    missing_rules["packages"][0].pop("rules_path")
    with pytest.raises(ValueError, match="rules_path"):
        builder.build_neutral_manifest(missing_rules)

    output_drift = copy.deepcopy(spec)
    output_drift["packages"][0]["output_contract_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="output_contract_sha256 does not bind acceptance"):
        builder.build_neutral_manifest(output_drift)


def test_input_snapshot_freezes_all_source_material_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec = _logical_spec(fixture)
    original_prompt = Path(str(spec["packages"][0]["prompt_path"]))
    original_input = Path(str(spec["packages"][0]["input_paths"][0]))
    frozen_spec, snapshot_manifest, exact_bindings = builder.snapshot_package_spec_inputs(
        spec,
        snapshot_root=tmp_path / "sealed-inputs",
    )

    frozen_package = frozen_spec["packages"][0]
    frozen_prompt_logical = str(frozen_package["prompt_path"])
    frozen_prompt = Path(frozen_prompt_logical)
    frozen_input = Path(str(frozen_package["input_paths"][0]))
    assert frozen_prompt != original_prompt
    assert frozen_input != original_input
    assert frozen_prompt.read_bytes() == original_prompt.read_bytes()
    assert frozen_input.read_bytes() == original_input.read_bytes()
    assert exact_bindings[frozen_prompt_logical].resolve() == frozen_prompt.resolve()
    assert snapshot_manifest["authority"] is False
    assert snapshot_manifest["completion_claim_allowed"] is False
    assert len(str(snapshot_manifest["snapshot_identity_sha256"])) == 64
    assert snapshot_manifest["external_input_admission"] == {
        "status": "owner_reviewed_redacted",
        "scope": "all_package_sources",
        "reviewer_role": "codex_owner",
        "snapshot_generation_sha256": snapshot_manifest["snapshot_generation_sha256"],
    }

    package_root = next(
        parent for parent in frozen_input.parents if parent.parent.name == "packages"
    )
    assert not frozen_prompt.is_relative_to(package_root)
    package_files = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
    }
    assert package_files == {
        "catalog.json",
        frozen_input.relative_to(package_root).as_posix(),
    }

    manifest = builder.build_neutral_manifest(
        frozen_spec,
        path_resolver=builder.build_path_resolver(exact_bindings=exact_bindings),
    )
    frozen_ref = manifest["packages"][0]["input_refs"][0]
    original_input.write_text("live input changed after sealing\n", encoding="utf-8")
    assert builder._sha(frozen_input) == frozen_ref["sha256"]
    assert (
        builder.validate_package_batch_manifest(manifest)["packages"][0]["input_refs"][0]
        == frozen_ref
    )


def test_input_snapshot_ref_root_keeps_logical_and_physical_paths_separate(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec = _logical_spec(fixture)
    frozen_spec, _, exact_bindings = builder.snapshot_package_spec_inputs(
        spec,
        snapshot_root=tmp_path / "physical-sealed-inputs",
        snapshot_ref_root="/xinao/sealed-inputs",
    )
    prompt_logical = str(frozen_spec["packages"][0]["prompt_path"])
    assert prompt_logical.startswith("/xinao/sealed-inputs/")
    assert exact_bindings[prompt_logical].is_file()
    manifest = builder.build_neutral_manifest(
        frozen_spec,
        path_resolver=builder.build_path_resolver(exact_bindings=exact_bindings),
    )
    assert manifest["packages"][0]["prompt_ref"]["path"] == prompt_logical


def test_input_snapshot_package_components_are_collision_resistant() -> None:
    slash = builder._safe_snapshot_component("review/a", "package_id")
    underscore = builder._safe_snapshot_component("review_a", "package_id")
    long_a = builder._safe_snapshot_component("x" * 120 + "a", "package_id")
    long_b = builder._safe_snapshot_component("x" * 120 + "b", "package_id")

    assert slash != underscore
    assert long_a != long_b
    assert len(slash) <= 96
    assert len(long_a) <= 96


def test_input_snapshot_rejects_duplicate_effective_inputs(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec = _logical_spec(fixture)
    only_input = spec["packages"][0]["input_paths"][0]
    spec["packages"][0]["input_paths"] = [only_input, only_input]

    with pytest.raises(ValueError, match="duplicate sealed inputs"):
        builder.snapshot_package_spec_inputs(
            spec,
            snapshot_root=tmp_path / "sealed-inputs",
        )


def test_input_snapshot_is_stable_and_survives_source_deletion(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec = _logical_spec(fixture)
    root = tmp_path / "sealed-inputs"
    first, first_receipt, first_bindings = builder.snapshot_package_spec_inputs(
        spec,
        snapshot_root=root,
    )
    second, second_receipt, second_bindings = builder.snapshot_package_spec_inputs(
        spec,
        snapshot_root=root,
    )
    assert first == second
    assert first_receipt == second_receipt
    assert first_bindings == second_bindings

    original = Path(str(spec["packages"][0]["input_paths"][0]))
    frozen = Path(str(first["packages"][0]["input_paths"][0]))
    frozen_sha256 = builder._sha(frozen)
    original.unlink()
    assert frozen.is_file()
    assert builder._sha(frozen) == frozen_sha256
    assert any(frozen_sha256 == row["source_sha256"] for row in first_receipt["sources"])


def test_input_snapshot_rejects_secret_files_and_reparse_roots(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec = _logical_spec(fixture)
    secret = tmp_path / "credentials.json"
    secret.write_text('{"token":"do-not-copy"}\n', encoding="utf-8")
    spec["packages"][0]["input_paths"] = [str(secret)]
    with pytest.raises(ValueError, match="sensitive input cannot be snapshotted"):
        builder.snapshot_package_spec_inputs(spec, snapshot_root=tmp_path / "sealed-inputs")

    for filename in (".env.local", "token.json", "api-key.txt"):
        spec = _logical_spec(fixture)
        secret = tmp_path / filename
        secret.write_text("redaction required\n", encoding="utf-8")
        spec["packages"][0]["input_paths"] = [str(secret)]
        with pytest.raises(ValueError, match="sensitive input cannot be snapshotted"):
            builder.snapshot_package_spec_inputs(
                spec, snapshot_root=tmp_path / f"sealed-{filename.replace('.', '_')}"
            )

    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_text('{"kind":"legitimate model vocabulary"}\n', encoding="utf-8")
    spec = _logical_spec(fixture)
    spec["packages"][0]["input_paths"] = [str(tokenizer)]
    frozen, _, _ = builder.snapshot_package_spec_inputs(
        spec, snapshot_root=tmp_path / "sealed-tokenizer"
    )
    assert Path(str(frozen["packages"][0]["input_paths"][0])).is_file()

    if os.name == "nt":
        real_root = tmp_path / "real-root"
        real_root.mkdir()
        reparse_root = tmp_path / "reparse-root"
        try:
            os.symlink(real_root, reparse_root, target_is_directory=True)
        except OSError:
            pass
        else:
            spec = _logical_spec(fixture)
            with pytest.raises(ValueError, match="reparse point"):
                builder.snapshot_package_spec_inputs(spec, snapshot_root=reparse_root)


def test_input_snapshot_requires_positive_owner_reviewed_redacted_admission(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec = _logical_spec(fixture)
    spec.pop("external_input_admission")

    with pytest.raises(ValueError, match="external_input_admission"):
        builder.snapshot_package_spec_inputs(spec, snapshot_root=tmp_path / "sealed-inputs")

    for invalid in (
        {},
        {
            "status": "owner_reviewed_redacted",
            "scope": "all_package_sources",
            "reviewer_role": "worker",
        },
        {
            "status": "owner_reviewed_redacted",
            "scope": "all_package_sources",
            "reviewer_role": "codex_owner",
            "extra": True,
        },
    ):
        invalid_spec = _logical_spec(fixture)
        invalid_spec["external_input_admission"] = invalid
        with pytest.raises(ValueError, match="external_input_admission"):
            builder.build_neutral_manifest(invalid_spec)

    missing = _logical_spec(fixture)
    missing.pop("external_input_admission")
    with pytest.raises(ValueError, match="external_input_admission"):
        builder.build_neutral_manifest(missing)


def test_cli_rejects_no_input_snapshot_bypass_before_loading_sources(
    tmp_path: Path,
) -> None:
    script = Path(builder.__file__).resolve()
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--spec",
            str(tmp_path / "missing-spec.json"),
            "--quota-resolution",
            str(tmp_path / "missing-quota.json"),
            "--output",
            str(tmp_path / "never-written.json"),
            "--no-input-snapshot",
        ],
        cwd=script.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 20
    assert "--no-input-snapshot is disabled" in completed.stderr
    assert not (tmp_path / "never-written.json").exists()


def test_cli_defaults_to_sealed_input_copy_that_survives_live_source_drift(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec = _logical_spec(fixture)
    spec_path = tmp_path / "package-spec.json"
    _write_json(spec_path, spec)
    selection_path = tmp_path / "selection.json"
    _write_json(selection_path, _route_receipt("direct-grok-worker-pool"))
    quota_path = Path(str(fixture["quota_ref"]["path"]))
    snapshot = _read_json(str(quota_path))
    snapshot["snapshot_ref"] = str(quota_path)
    resolution_path = tmp_path / "quota-resolution.json"
    _write_json(
        resolution_path,
        {
            "schema_version": "xinao.quota_dispatch_epoch_resolution.v1",
            "snapshot": snapshot,
        },
    )
    manifest_path = tmp_path / "package-manifest.json"
    envelope_path = tmp_path / "dispatch-envelope.json"
    script = Path(builder.__file__).resolve()
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--spec",
            str(spec_path),
            "--quota-resolution",
            str(resolution_path),
            "--selection-receipt",
            str(selection_path),
            "--output",
            str(manifest_path),
            "--dispatch-output-a",
            str(envelope_path),
        ],
        cwd=script.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["input_snapshot_status"] == "sealed_copy"
    snapshot_ref = result["input_snapshot_manifest_ref"]
    assert Path(snapshot_ref["path"]).is_file()
    assert builder._sha(Path(snapshot_ref["path"])) == snapshot_ref["sha256"]
    first_snapshot_manifest = _read_json(str(snapshot_ref["path"]))
    first_snapshot_root = Path(str(first_snapshot_manifest["snapshot_root"]))
    assert first_snapshot_root.parent.name == "generations"
    assert first_snapshot_root.parent.parent.name == "sealed-inputs"
    assert first_snapshot_root.name == first_snapshot_manifest["snapshot_generation_sha256"]

    manifest = _read_json(str(manifest_path))
    frozen_input_logical = str(manifest["packages"][0]["input_refs"][0]["path"])
    frozen_input = Path(frozen_input_logical)
    live_input = Path(str(spec["packages"][0]["input_paths"][0]))
    assert frozen_input != live_input
    live_input.write_text("live source drift after CLI seal\n", encoding="utf-8")
    assert (
        validate_package_batch_manifest(manifest)["packages"][0]["input_refs"][0]["path"]
        == frozen_input_logical
    )
    assert validate_dispatch_envelope(_read_json(str(envelope_path)))["validated_package_manifest"][
        "packages"
    ][0]["input_refs"][0]["sha256"] == builder._sha(frozen_input)

    second_manifest_path = tmp_path / "package-manifest-generation-2.json"
    second_envelope_path = tmp_path / "dispatch-envelope-generation-2.json"
    second = subprocess.run(
        [
            sys.executable,
            str(script),
            "--spec",
            str(spec_path),
            "--quota-resolution",
            str(resolution_path),
            "--selection-receipt",
            str(selection_path),
            "--output",
            str(second_manifest_path),
            "--dispatch-output-a",
            str(second_envelope_path),
        ],
        cwd=script.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert second.returncode == 0, second.stderr
    second_result = json.loads(second.stdout)
    second_snapshot_manifest = _read_json(str(second_result["input_snapshot_manifest_ref"]["path"]))
    second_snapshot_root = Path(str(second_snapshot_manifest["snapshot_root"]))
    assert second_snapshot_root != first_snapshot_root
    assert second_snapshot_root.name == second_snapshot_manifest["snapshot_generation_sha256"]
    assert (
        _read_json(str(second_manifest_path))["packages"][0]["input_refs"][0]["sha256"]
        != _read_json(str(manifest_path))["packages"][0]["input_refs"][0]["sha256"]
    )

    unsupported = subprocess.run(
        [
            sys.executable,
            str(script),
            "--spec",
            str(spec_path),
            "--quota-resolution",
            str(resolution_path),
            "--selection-receipt",
            str(selection_path),
            "--output",
            str(tmp_path / "unsupported-logical-manifest.json"),
            "--dispatch-output-a",
            str(tmp_path / "unsupported-logical-envelope.json"),
            "--input-snapshot-ref-root",
            "/logical/sealed-inputs",
        ],
        cwd=script.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert unsupported.returncode != 0
    assert "sealed manifest refs must be physical paths" in unsupported.stderr


def test_route_bound_envelope_rejects_wrong_leg_and_selector_capability_claim() -> None:
    kwargs = {
        "manifest_ref": {"path": "manifest.json", "sha256": "1" * 64},
        "package_ids": ["p1"],
        "epoch_id": "epoch-1",
        "snapshot": {"snapshot_id": "snapshot-1"},
        "snapshot_ref": {"path": "quota.json", "sha256": "2" * 64},
        "selection_ref": {"path": "selection.json", "sha256": "3" * 64},
    }
    with pytest.raises(ValueError, match="transport_id"):
        builder.build_route_bound_dispatch_envelope(
            leg="A",
            selection=_route_receipt("temporal-docker-langgraph"),
            **kwargs,
        )
    fake = _route_receipt("direct-grok-worker-pool")
    fake["selected_candidate"]["capability_binding_sha256"] = "4" * 64
    fake.pop("decision_sha256")
    fake["decision_sha256"] = builder._canonical_sha(fake)
    with pytest.raises(ValueError, match="must not claim provider capability"):
        builder.build_route_bound_dispatch_envelope(
            leg="A",
            selection=fake,
            **kwargs,
        )


def test_builder_keeps_one_neutral_manifest_for_host_a_and_docker_b(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "physical")
    physical_root = str(Path(fixture["root"]))
    logical_root = "D:/XINAO_RESEARCH_RUNTIME/shared-dispatch"

    def to_logical(value: str) -> str:
        return value.replace(physical_root, logical_root).replace("\\", "/")

    def host_resolver(logical: str) -> Path:
        return Path(logical.replace(logical_root, physical_root))

    def docker_resolver(logical: str) -> Path:
        # Distinct resolver identity; its return stands in for Docker's mounted file.
        return Path(logical.replace(logical_root, physical_root))

    spec = _logical_spec(fixture, rewrite=to_logical)
    manifest = builder.build_neutral_manifest(spec, path_resolver=host_resolver)
    plan = builder.plan_worker_dispatch(manifest, path_resolver=host_resolver)
    assert plan["worker_package_ids"] == ["p1"]
    assert plan["unresolved_pin_package_ids"] == ["p2"]
    assert manifest["graph_revision"] == 1
    assert manifest["limits"] == {
        "max_parallel": 2,
        "fan_in_capacity": 1,
        "candidate_ingestion_capacity": 2,
    }
    assert manifest["packages"][0]["prompt_ref"]["path"].startswith(logical_root)

    manifest_path = Path(fixture["root"]) / "neutral-manifest.json"
    manifest_sha = builder._atomic_json(manifest_path, manifest)
    raw_before = manifest_path.read_bytes()
    manifest_ref = {
        "path": f"{logical_root}/neutral-manifest.json",
        "sha256": manifest_sha,
    }
    quota_path = Path(str(fixture["quota_ref"]["path"]))
    selection_a_path = Path(fixture["root"]) / "selection-a.json"
    selection_b_path = Path(fixture["root"]) / "selection-b.json"
    selection_a = _route_receipt("direct-grok-worker-pool")
    selection_b = _route_receipt("temporal-docker-langgraph")
    _write_json(selection_a_path, selection_a)
    _write_json(selection_b_path, selection_b)
    selection_ref = {
        "path": to_logical(str(selection_a_path)),
        "sha256": builder._sha(selection_a_path),
    }
    selection_b_ref = {
        "path": to_logical(str(selection_b_path)),
        "sha256": builder._sha(selection_b_path),
    }
    quota_ref = {
        "path": to_logical(str(quota_path)),
        "sha256": fixture["quota_ref"]["sha256"],
    }
    snapshot = _read_json(str(quota_path))
    envelope_a = builder.build_dispatch_envelope(
        leg="A",
        manifest_ref=manifest_ref,
        package_ids=plan["worker_package_ids"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=quota_ref,
        selection=selection_a,
        selection_ref=selection_ref,
    )
    envelope_b = builder.build_dispatch_envelope(
        leg="B",
        manifest_ref=manifest_ref,
        package_ids=plan["worker_package_ids"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=quota_ref,
        selection=selection_b,
        selection_ref=selection_b_ref,
    )
    validated_a = validate_dispatch_envelope(envelope_a, path_resolver=host_resolver)
    validated_b = validate_dispatch_envelope(envelope_b, path_resolver=docker_resolver)
    assert validated_a["package_manifest_ref"] == validated_b["package_manifest_ref"]
    assert (
        validated_a["validated_package_manifest"]["validated_manifest_sha256"]
        == validated_b["validated_package_manifest"]["validated_manifest_sha256"]
    )
    assert manifest_path.read_bytes() == raw_before
    assert physical_root.encode() not in raw_before
    assert preflight.validate_manifest_and_envelopes(
        manifest,
        [envelope_a],
        path_resolver=host_resolver,
    )["worker_admitted_package_ids"] == ["p1"]
    assert preflight.validate_manifest_and_envelopes(
        manifest,
        [envelope_b],
        path_resolver=docker_resolver,
    )["worker_admitted_package_ids"] == ["p1"]
    with pytest.raises(DispatchEconomicsError, match="dual-dispatched"):
        preflight.validate_manifest_and_envelopes(
            manifest,
            [envelope_a, envelope_b],
            path_resolver=host_resolver,
        )


def test_builder_filters_owner_and_unpinned_packages_before_worker_envelope(
    tmp_path: Path,
) -> None:
    owner_fixture = _fixture(tmp_path / "owner", second_candidate_only=False)
    owner_spec = _logical_spec(owner_fixture)
    owner_spec["packages"][1]["depends_on"] = []
    owner_spec["limits"]["candidate_ingestion_capacity"] = 1
    owner_manifest = builder.build_neutral_manifest(owner_spec)
    owner_plan = builder.plan_worker_dispatch(owner_manifest)
    assert [row["package_id"] for row in owner_plan["frontier"]["admitted"]] == ["p1", "p2"]
    assert owner_plan["worker_package_ids"] == ["p1"]
    assert owner_plan["owner_package_ids"] == ["p2"]

    owner_saturated = builder.plan_worker_dispatch(
        owner_manifest,
        pending_owner_authority_count=1,
    )
    assert owner_saturated["worker_package_ids"] == ["p1"]
    assert owner_saturated["frontier"]["pending_owner_ready_package_ids"] == ["p2"]
    candidate_saturated = builder.plan_worker_dispatch(
        owner_manifest,
        pending_candidate_ingestion_count=1,
    )
    assert candidate_saturated["worker_package_ids"] == []
    assert candidate_saturated["owner_package_ids"] == ["p2"]
    assert candidate_saturated["frontier"]["pending_candidate_ready_package_ids"] == ["p1"]

    invalid_capacity = copy.deepcopy(owner_spec)
    invalid_capacity["limits"]["candidate_ingestion_capacity"] = 0
    with pytest.raises(DispatchEconomicsError, match="candidate_ingestion_capacity"):
        builder.build_neutral_manifest(invalid_capacity)
    invalid_owner_capacity = copy.deepcopy(owner_spec)
    invalid_owner_capacity["limits"]["fan_in_capacity"] = 0
    with pytest.raises(DispatchEconomicsError, match="fan_in_capacity"):
        builder.build_neutral_manifest(invalid_owner_capacity)

    candidate_fixture = _fixture(tmp_path / "candidate")
    candidate_manifest = builder.build_neutral_manifest(_logical_spec(candidate_fixture))
    candidate_plan = builder.plan_worker_dispatch(candidate_manifest)
    assert candidate_plan["worker_package_ids"] == ["p1"]
    assert candidate_plan["unresolved_pin_package_ids"] == ["p2"]
    assert "p2" not in candidate_plan["worker_package_ids"]


def test_validator_rejects_ready_candidate_outside_bounded_admitted_frontier(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    spec = _logical_spec(fixture)
    spec["packages"][1]["depends_on"] = []
    spec["limits"]["max_parallel"] = 1
    manifest = builder.build_neutral_manifest(spec)
    plan = builder.plan_worker_dispatch(manifest)
    assert plan["worker_package_ids"] == ["p1"]
    assert plan["frontier"]["pending_ready_package_ids"] == ["p2"]
    manifest_path = tmp_path / "bounded-manifest.json"
    manifest_ref = {
        "path": str(manifest_path),
        "sha256": builder._atomic_json(manifest_path, manifest),
    }
    snapshot = _read_json(str(fixture["quota_ref"]["path"]))
    selection_path = tmp_path / "selection-a.json"
    selection = _route_receipt("direct-grok-worker-pool")
    _write_json(selection_path, selection)
    selection_ref = {
        "path": str(selection_path),
        "sha256": builder._sha(selection_path),
    }
    envelope = builder.build_dispatch_envelope(
        leg="A",
        manifest_ref=manifest_ref,
        package_ids=["p2"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=fixture["quota_ref"],
        selection=selection,
        selection_ref=selection_ref,
    )
    with pytest.raises(DispatchEconomicsError, match="outside the admitted worker frontier"):
        preflight.validate_manifest_and_envelopes(manifest, [envelope])


def test_builder_admits_typed_pin_only_after_real_owner_event_and_rejects_wrong_type(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    predecessor_ref, envelope_ref, _ = _seal_dispatch(fixture, suffix="-r1")
    _, worker_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=predecessor_ref,
        envelope_ref=envelope_ref,
    )
    _, owner_verdict_ref = _owner_event(
        fixture,
        provider_ref=worker_ref,
        artifact_ref=artifact_ref,
    )
    _, owner_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_verdict_ref,
        artifact_ref=artifact_ref,
    )
    predecessor = validate_package_batch_manifest(fixture["manifest"])
    revision_two_spec = _logical_spec(fixture)
    revision_two_spec.update(
        graph_revision=2,
        predecessor_manifest_ref=predecessor_ref,
        reseal_of={
            "package_id": "p2",
            "package_identity_sha256": predecessor["packages"][1]["package_identity_sha256"],
            "graph_revision": 1,
        },
        affected_cone=["p2"],
    )
    revision_two_spec["packages"][1]["depends_on"][0]["pin"] = {
        "event_ref": owner_ref,
        "artifact_ref": artifact_ref,
    }
    revision_two = builder.build_neutral_manifest(revision_two_spec)
    plan = builder.plan_worker_dispatch(revision_two)
    assert revision_two["graph_revision"] == 2
    assert revision_two["predecessor_manifest_ref"] == predecessor_ref
    assert revision_two["reseal_of"]["package_id"] == "p2"
    assert revision_two["affected_cone"] == ["p2"]
    assert plan["worker_package_ids"] == ["p2"]
    assert plan["frontier"]["terminal_package_ids"] == ["p1"]

    wrong_type = copy.deepcopy(revision_two_spec)
    wrong_type["packages"][1]["depends_on"][0]["pin"]["event_ref"] = worker_ref
    with pytest.raises(DispatchEconomicsError, match="typed condition"):
        builder.build_neutral_manifest(wrong_type)

    wrong_cone = copy.deepcopy(revision_two_spec)
    wrong_cone["affected_cone"] = ["p1", "p2"]
    with pytest.raises(DispatchEconomicsError, match="affected_cone"):
        builder.build_neutral_manifest(wrong_cone)

    wrong_revision = copy.deepcopy(revision_two_spec)
    wrong_revision["graph_revision"] = 1
    with pytest.raises(DispatchEconomicsError, match="initial graph revision"):
        builder.build_neutral_manifest(wrong_revision)
    wrong_predecessor = copy.deepcopy(revision_two_spec)
    wrong_predecessor["predecessor_manifest_ref"]["sha256"] = "0" * 64
    with pytest.raises(DispatchEconomicsError, match="predecessor_manifest_ref sha256 mismatch"):
        builder.build_neutral_manifest(wrong_predecessor)
    wrong_reseal = copy.deepcopy(revision_two_spec)
    wrong_reseal["reseal_of"]["package_identity_sha256"] = "0" * 64
    with pytest.raises(DispatchEconomicsError, match="reseal_of package identity mismatch"):
        builder.build_neutral_manifest(wrong_reseal)


def test_builder_cli_emits_one_route_at_a_time_and_preserves_neutral_bytes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec_path = tmp_path / "spec.json"
    resolution_path = tmp_path / "quota-resolution.json"
    manifest_a_path = tmp_path / "manifest-a.json"
    manifest_b_path = tmp_path / "manifest-b.json"
    envelope_a_path = tmp_path / "envelope-a.json"
    envelope_b_path = tmp_path / "envelope-b.json"
    selection_a_path = tmp_path / "selection-a.json"
    selection_b_path = tmp_path / "selection-b.json"
    _write_json(spec_path, _logical_spec(fixture))
    _write_json(selection_a_path, _route_receipt("direct-grok-worker-pool"))
    _write_json(selection_b_path, _route_receipt("temporal-docker-langgraph"))
    snapshot = _read_json(str(fixture["quota_ref"]["path"]))
    _write_json(
        resolution_path,
        {
            "snapshot": {
                **snapshot,
                "snapshot_ref": fixture["quota_ref"]["path"],
            }
        },
    )
    dual = subprocess.run(
        [
            sys.executable,
            str(Path(builder.__file__)),
            "--spec",
            str(spec_path),
            "--quota-resolution",
            str(resolution_path),
            "--selection-receipt-a",
            str(selection_a_path),
            "--selection-receipt-b",
            str(selection_b_path),
            "--output",
            str(tmp_path / "must-not-exist.json"),
            "--dispatch-output-a",
            str(envelope_a_path),
            "--dispatch-output-b",
            str(envelope_b_path),
        ],
        cwd=Path(builder.__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert dual.returncode == 20
    assert "mutually exclusive route alternatives" in dual.stderr

    def build_one(leg: str, manifest_path: Path, envelope_path: Path) -> dict[str, object]:
        receipt_path = selection_a_path if leg == "A" else selection_b_path
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(builder.__file__)),
                "--spec",
                str(spec_path),
                "--quota-resolution",
                str(resolution_path),
                f"--selection-receipt-{leg.lower()}",
                str(receipt_path),
                "--output",
                str(manifest_path),
                f"--dispatch-output-{leg.lower()}",
                str(envelope_path),
            ],
            cwd=Path(builder.__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        assert result["worker_package_ids"] == ["p1"]
        assert result["unresolved_pin_package_ids"] == ["p2"]
        assert result["selected_leg"] == leg
        return result

    build_one("A", manifest_a_path, envelope_a_path)
    build_one("B", manifest_b_path, envelope_b_path)
    assert manifest_a_path.read_bytes() == manifest_b_path.read_bytes()
    envelope_a = _read_json(str(envelope_a_path))
    envelope_b = _read_json(str(envelope_b_path))
    assert envelope_a["package_ids"] == envelope_b["package_ids"] == ["p1"]
    assert envelope_a["leg"] == "A"
    assert envelope_b["leg"] == "B"
    assert envelope_a["selection"]["transport_id"] == "direct-grok-worker-pool"
    assert envelope_b["selection"]["transport_id"] == "temporal-docker-langgraph"
    assert envelope_b["execution_adapter"]["provider_transport_id"] == "grok_cli_json"

    for manifest_path, envelope_path in (
        (manifest_a_path, envelope_a_path),
        (manifest_b_path, envelope_b_path),
    ):
        validate = subprocess.run(
            [
                sys.executable,
                str(Path(preflight.__file__)),
                "--manifest",
                str(manifest_path),
                "--dispatch-envelope",
                str(envelope_path),
                "--plan-initial-frontier",
            ],
            cwd=Path(preflight.__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        assert validate.returncode == 0, validate.stderr
        assert json.loads(validate.stdout)["worker_admitted_package_ids"] == ["p1"]


def test_builder_cli_rebinds_fresh_epoch_without_changing_sealed_manifest(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec = _logical_spec(fixture)
    spec_path = tmp_path / "spec.json"
    initial_resolution_path = tmp_path / "quota-resolution-initial.json"
    selection_path = tmp_path / "selection-a.json"
    manifest_path = tmp_path / "manifest.json"
    initial_envelope_path = tmp_path / "envelope-initial.json"
    rebound_envelope_path = tmp_path / "envelope-rebound.json"
    _write_json(spec_path, spec)
    _write_json(selection_path, _route_receipt("direct-grok-worker-pool"))
    initial_snapshot = _read_json(str(fixture["quota_ref"]["path"]))
    _write_json(
        initial_resolution_path,
        {
            "snapshot": {
                **initial_snapshot,
                "snapshot_ref": fixture["quota_ref"]["path"],
            }
        },
    )
    initial = subprocess.run(
        [
            sys.executable,
            str(Path(builder.__file__)),
            "--spec",
            str(spec_path),
            "--quota-resolution",
            str(initial_resolution_path),
            "--selection-receipt-a",
            str(selection_path),
            "--output",
            str(manifest_path),
            "--dispatch-output-a",
            str(initial_envelope_path),
        ],
        cwd=Path(builder.__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert initial.returncode == 0, initial.stderr
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = builder._sha(manifest_path)

    # The original sender-side input may drift after sealing.  Rebinding the
    # physical dispatch carrier must continue to consume the sealed manifest.
    Path(str(spec["packages"][0]["prompt_path"])).write_text(
        "changed after the neutral manifest was sealed\n",
        encoding="utf-8",
    )
    fresh_snapshot_path = tmp_path / "quota-snapshot-fresh.json"
    fresh_snapshot = {
        **initial_snapshot,
        "epoch_id": "epoch-1",
        "snapshot_id": "snapshot-fresh",
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_ref": str(fresh_snapshot_path),
    }
    _write_json(fresh_snapshot_path, fresh_snapshot)
    fresh_resolution_path = tmp_path / "quota-resolution-fresh.json"
    _write_json(fresh_resolution_path, {"snapshot": fresh_snapshot})

    rebound = subprocess.run(
        [
            sys.executable,
            str(Path(builder.__file__)),
            "--existing-manifest",
            str(manifest_path),
            "--prior-dispatch-envelope",
            str(initial_envelope_path),
            "--quota-resolution",
            str(fresh_resolution_path),
            "--selection-receipt-a",
            str(selection_path),
            "--dispatch-output-a",
            str(rebound_envelope_path),
        ],
        cwd=Path(builder.__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rebound.returncode == 0, rebound.stderr
    result = json.loads(rebound.stdout)
    assert result["manifest_reused"] is True
    assert result["manifest_sha256"] == manifest_sha256
    assert result["input_snapshot_status"] == "reused_sealed_manifest"
    assert result["worker_package_ids"] == ["p1"]
    assert manifest_path.read_bytes() == manifest_bytes
    envelope = _read_json(str(rebound_envelope_path))
    assert envelope["package_manifest_ref"] == {
        "path": str(manifest_path),
        "sha256": manifest_sha256,
    }
    assert envelope["dispatch_epoch"]["quota_snapshot_id"] == "snapshot-fresh"
    assert validate_dispatch_envelope(envelope)["package_ids"] == ["p1"]

    wrong_epoch_snapshot_path = tmp_path / "quota-snapshot-wrong-epoch.json"
    wrong_epoch_snapshot = {
        **fresh_snapshot,
        "epoch_id": "different-episode",
        "snapshot_id": "snapshot-wrong-epoch",
        "snapshot_ref": str(wrong_epoch_snapshot_path),
    }
    _write_json(wrong_epoch_snapshot_path, wrong_epoch_snapshot)
    wrong_epoch_resolution_path = tmp_path / "quota-resolution-wrong-epoch.json"
    _write_json(wrong_epoch_resolution_path, {"snapshot": wrong_epoch_snapshot})
    wrong_epoch_envelope_path = tmp_path / "envelope-wrong-epoch.json"
    wrong_epoch = subprocess.run(
        [
            sys.executable,
            str(Path(builder.__file__)),
            "--existing-manifest",
            str(manifest_path),
            "--prior-dispatch-envelope",
            str(initial_envelope_path),
            "--quota-resolution",
            str(wrong_epoch_resolution_path),
            "--selection-receipt-a",
            str(selection_path),
            "--dispatch-output-a",
            str(wrong_epoch_envelope_path),
        ],
        cwd=Path(builder.__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_epoch.returncode == 20
    assert "must preserve the prior envelope" in wrong_epoch.stderr
    assert not wrong_epoch_envelope_path.exists()

    stale_snapshot_path = tmp_path / "quota-snapshot-stale.json"
    stale_snapshot = {
        **fresh_snapshot,
        "snapshot_id": "snapshot-stale",
        "queried_at": "2000-01-01T00:00:00+00:00",
        "snapshot_ref": str(stale_snapshot_path),
    }
    _write_json(stale_snapshot_path, stale_snapshot)
    stale_resolution_path = tmp_path / "quota-resolution-stale.json"
    _write_json(stale_resolution_path, {"snapshot": stale_snapshot})
    stale_envelope_path = tmp_path / "envelope-stale.json"
    stale = subprocess.run(
        [
            sys.executable,
            str(Path(builder.__file__)),
            "--existing-manifest",
            str(manifest_path),
            "--prior-dispatch-envelope",
            str(initial_envelope_path),
            "--quota-resolution",
            str(stale_resolution_path),
            "--selection-receipt-a",
            str(selection_path),
            "--dispatch-output-a",
            str(stale_envelope_path),
        ],
        cwd=Path(builder.__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale.returncode == 20
    assert "quota snapshot exceeds existing-manifest rebind freshness limit" in stale.stderr
    assert not stale_envelope_path.exists()
