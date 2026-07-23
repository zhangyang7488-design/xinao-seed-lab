from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_bundle_runner import (
    BUNDLE_SCHEMA_VERSION,
    PROTOCOL_VERSION,
    REQUEST_SCHEMA_VERSION,
)
from xinao.foundation.assertion_verifier_registry import (
    canonical_projection_path,
    canonical_verifier,
)
from xinao.foundation.closure import (
    FOUNDATION_BLOCK_IDS,
    derive_foundation_closure_report,
    evidence_ref,
    verify_foundation_closure_report,
)

INPUT_KEYS = (
    "dataset_sha256",
    "baseline_sha256",
    "play_catalog_sha256",
    "rule_semantic_map_sha256",
    "compiler_code_sha256",
    "compiler_config_sha256",
)

F1_ARTIFACT_TYPES = (
    "RuleSemanticMapVersion",
    "ExpectedSelectionDomainManifestVersion",
    "AtomicTicketBindingVersion",
    "RuleSetVersion",
    "SettlementFunctionSetVersion",
    "EventMatrixSnapshot",
    "WorldSnapshot",
)
ACTIVE_IDS = tuple(
    f"BO{number:04d}" for number in range(1, 434) if number not in {*range(13, 25), *range(30, 35)}
)


def _write(tmp_path: Path, name: str, content: str | bytes) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _write_json(tmp_path: Path, name: str, value: dict[str, Any]) -> Path:
    return _write(
        tmp_path,
        name,
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def _content_hashed(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("content_hash", None)
    result["content_hash"] = canonical_sha256(result)
    return result


def _f1_payloads() -> dict[str, dict[str, Any]]:
    family_counts = {f"family-{index:02d}": 32 for index in range(13)}
    selection_specs = []
    offset = 0
    for index in range(233):
        width = 2 if index < 183 else 1
        selection_specs.append(
            {"component_baseline_ids": list(ACTIVE_IDS[offset : offset + width])}
        )
        offset += width
    semantic_map = _content_hashed(
        {
            "semantic_record_count": 416,
            "family_counts": family_counts,
            "records": [
                {
                    "baseline_id": baseline_id,
                    "physical_role": "ACTIVE_SETTLEMENT",
                }
                for baseline_id in ACTIVE_IDS
            ],
        }
    )
    rule_set = _content_hashed(
        {
            "rule_count": 416,
            "semantic_map_content_hash": semantic_map["content_hash"],
            "rules": [
                {
                    "baseline_id": baseline_id,
                    "physical_role": "ACTIVE_SETTLEMENT",
                }
                for baseline_id in ACTIVE_IDS
            ],
        }
    )
    function_set = _content_hashed(
        {
            "function_count": 416,
            "rule_set_content_hash": rule_set["content_hash"],
            "bindings": [{"baseline_id": baseline_id} for baseline_id in ACTIVE_IDS],
        }
    )
    manifest = _content_hashed(
        {
            "component_catalog_row_count": 416,
            "selection_domain_spec_count": 233,
            "exact_atomic_selection_count": 21_652_542_248,
            "canonical_materialized_atomic_selection_count": 0,
            "specifications": selection_specs,
        }
    )
    atomic = _content_hashed(
        {
            "binding_count": 37,
            "exact_atomic_ticket_count": 21_652_539_822,
            "materialized_atomic_ticket_count": 0,
            "bindings": [
                {
                    "binding_id": f"binding-{index:02d}",
                    "component_baseline_ids": [ACTIVE_IDS[index]],
                }
                for index in range(37)
            ],
        }
    )
    event_matrix = _content_hashed(
        {
            "family_cell_counts": {f"family-{index:02d}": 29_216 for index in range(13)},
            "coverage": {
                "draw_count": 913,
                "active_settlement_component_count": 416,
                "expected_functional_cell_count": 379_808,
                "actual_functional_cell_count": 379_808,
            },
        }
    )
    world = _content_hashed(
        {
            "event_matrix_snapshot_hash": event_matrix["content_hash"],
            "draw_inputs": [{"draw_id": f"draw-{index:04d}"} for index in range(913)],
            "expanded_atomic_ticket_keys_materialized": False,
            "lazy_domain_proof": {
                "expanded_atomic_ticket_keys_materialized": False,
                "materialized_atomic_ticket_key_count": 0,
                "exact_conceptual_atomic_selection_count": 21_652_542_248,
                "composite_exact_atomic_ticket_count": 21_652_539_822,
                "atomic_ticket_binding_count": 37,
                "component_baseline_count": 416,
            },
        }
    )
    return {
        "RuleSemanticMapVersion": semantic_map,
        "ExpectedSelectionDomainManifestVersion": manifest,
        "AtomicTicketBindingVersion": atomic,
        "RuleSetVersion": rule_set,
        "SettlementFunctionSetVersion": function_set,
        "EventMatrixSnapshot": event_matrix,
        "WorldSnapshot": world,
    }


def _fixture(
    tmp_path: Path,
    *,
    canonical_projection: bool = True,
) -> tuple[dict[str, Any], Path]:
    profile: dict[str, Any] = {
        "blocks": {
            "F1_settlement_world": {
                "required_artifact_types": list(F1_ARTIFACT_TYPES),
                "required_assertion_ids": [
                    "catalog_total_eq",
                    "semantic_rule_mapped_eq",
                    "active_settlement_compiled_eq",
                    "active_settlement_not_compiled_eq",
                    "draw_total_eq",
                    "distinct_active_world_cells_eq",
                    "actual_event_key_set_equals_expected",
                    "atomic_ticket_binding_count_eq",
                    "active_atomic_selection_count_eq",
                    "atomic_ticket_count_eq",
                    "atomic_ticket_domain_lazy_not_materialized",
                ],
                "required_assertions": {
                    "catalog_total_eq": 433,
                    "semantic_rule_mapped_eq": 416,
                    "active_settlement_compiled_eq": 416,
                    "active_settlement_not_compiled_eq": 0,
                    "draw_total_eq": 913,
                    "distinct_active_world_cells_eq": 379_808,
                    "actual_event_key_set_equals_expected": True,
                    "atomic_ticket_binding_count_eq": 37,
                    "active_atomic_selection_count_eq": 21_652_542_248,
                    "atomic_ticket_count_eq": 21_652_539_822,
                    "atomic_ticket_domain_lazy_not_materialized": True,
                },
            },
            "F2_issuer_settlement_cost_space": {
                "required_artifact_types": [
                    "SettlementProbabilitySnapshotVersion",
                    "RebateScheduleVersion",
                    "SettlementCostSurfaceVersion",
                ],
                "required_assertion_ids": [
                    "turnover_rebate_materialized",
                    "expected_unit_cost_recomputed_from_payout_and_rebate",
                ],
                "required_assertions": {
                    "turnover_rebate_materialized": True,
                    "expected_unit_cost_recomputed_from_payout_and_rebate": True,
                },
            },
            "F3_research_weight": {
                "required_artifact_types": ["ResearchWeightBaselineVersion"],
                "required_assertion_ids": ["exploration_share_gt"],
                "required_assertions": {"exploration_share_gt": True},
            },
            "F4_research_factory": {
                "required_artifact_types": ["ResearchFactoryCanaryReport"],
                "required_assertion_ids": ["real_temporal_workflow_history_verified"],
                "required_assertions": {"real_temporal_workflow_history_verified": True},
            },
        }
    }
    closure_schema = {"schema_version": "xinao.foundation_closure_report.v1"}
    exclusions = {"legacy_a_g_gate": "diagnostic_only"}
    config_payload = {
        "foundation_closure_profile": profile,
        "foundation_closure_report_schema": closure_schema,
        "foundation_exclusions": exclusions,
    }
    input_paths = {
        key: _write(tmp_path, f"inputs/{key}.json", f'{{"key":"{key}"}}\n')
        for key in INPUT_KEYS
        if key != "compiler_config_sha256"
    }
    input_paths["compiler_config_sha256"] = _write(
        tmp_path,
        "inputs/compiler_config_sha256.json",
        canonical_dumps(config_payload),
    )
    input_refs = {key: evidence_ref(path, input_hash_key=key) for key, path in input_paths.items()}
    input_hashes = {key: ref["sha256"] for key, ref in input_refs.items()}
    fixture_blueprint_path = _write_json(
        tmp_path,
        "blueprint.json",
        {
            **config_payload,
            "current_foundation_closure_payload": {"input_hashes": input_hashes},
        },
    )
    blueprint_path = canonical_projection_path() if canonical_projection else fixture_blueprint_path

    verifier_sources = {
        block_id: canonical_verifier(block_id).source_path for block_id in FOUNDATION_BLOCK_IDS
    }
    foundation_source_root = Path(__file__).resolve().parents[3] / "src" / "xinao" / "foundation"

    def code_entry(role: str, path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        return {
            "role": role,
            "source_path": str(path.resolve()),
            "sha256": __import__("hashlib").sha256(raw).hexdigest(),
            "size": len(raw),
        }

    code_manifest_core = {
        "schema_version": "xinao.compiler_code_manifest.v1",
        "entries": [
            code_entry("closure_pack.py", foundation_source_root / "closure_pack.py"),
            code_entry("closure.py", foundation_source_root / "closure.py"),
            code_entry(
                "assertion_bundle_runner.py",
                foundation_source_root / "assertion_bundle_runner.py",
            ),
            *[
                code_entry(f"assertion_verifier:{block_id}", verifier_sources[block_id])
                for block_id in FOUNDATION_BLOCK_IDS
            ],
        ],
    }
    code_manifest = {
        **code_manifest_core,
        "content_sha256": canonical_sha256(code_manifest_core),
    }
    code_manifest_path = _write_json(tmp_path, "compiler_code_manifest.json", code_manifest)
    code_manifest_ref = evidence_ref(code_manifest_path)

    block_reports: dict[str, Any] = {}
    f1_payloads = _f1_payloads()
    for block_id in FOUNDATION_BLOCK_IDS:
        profile_block = profile["blocks"][block_id]
        artifacts = profile_block["required_artifact_types"]
        assertions = profile_block["required_assertion_ids"]
        artifact_versions = {name: f"{name}.v1" for name in artifacts}
        artifact_refs: list[dict[str, Any]] = []
        artifact_source_hashes: dict[str, str] = {}
        for artifact_type in artifacts:
            payload = f1_payloads.get(
                artifact_type,
                {
                    "schema_version": f"fixture.{artifact_type}.v1",
                    "artifact_identity": f"{block_id}:{artifact_type}",
                },
            )
            source_path = _write_json(
                tmp_path,
                f"artifact_sources/{block_id}/{artifact_type}.json",
                payload,
            )
            source_ref = evidence_ref(source_path, artifact_type=artifact_type)
            artifact_source_hashes[artifact_type] = source_ref["sha256"]
            artifact_path = _write_json(
                tmp_path,
                f"artifacts/{block_id}/{artifact_type}.json",
                {
                    "artifact_type": artifact_type,
                    "version": artifact_versions[artifact_type],
                    "input_hashes": input_hashes,
                    "code_hash": input_hashes["compiler_code_sha256"],
                    "config_hash": input_hashes["compiler_config_sha256"],
                    "source_ref": source_ref,
                    "payload": payload,
                    "payload_sha256": canonical_sha256(payload),
                },
            )
            artifact_refs.append(evidence_ref(artifact_path, artifact_type=artifact_type))
        request = {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "block_id": block_id,
            "assertion_ids": sorted(assertions),
            "input_hashes": input_hashes,
            "artifacts": {
                artifact_type: artifact_source_hashes[artifact_type]
                for artifact_type in sorted(artifact_source_hashes)
            },
        }
        request_path = _write_json(tmp_path, f"assertion_requests/{block_id}.json", request)
        request_ref = evidence_ref(request_path)
        canonical_entry = canonical_verifier(block_id)
        checker_id = canonical_entry.checker_id
        checker_version = canonical_entry.checker_version
        source_ref = evidence_ref(verifier_sources[block_id])
        actuals = {
            assertion_id: profile_block["required_assertions"][assertion_id]
            for assertion_id in sorted(assertions)
        }
        actual_hashes = {
            assertion_id: canonical_sha256({"assertion_id": assertion_id, "actual": actual})
            for assertion_id, actual in actuals.items()
        }
        bundle_core = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "block_id": block_id,
            "checker_id": checker_id,
            "checker_version": checker_version,
            "request_sha256": canonical_sha256(request),
            "entrypoint": {
                "module_name": canonical_entry.module_name,
                "source_path": str(verifier_sources[block_id].resolve()),
                "source_sha256": source_ref["sha256"],
                "checker_id": checker_id,
                "checker_version": checker_version,
            },
            "assertion_actuals": actuals,
            "assertion_actual_content_sha256": actual_hashes,
        }
        bundle = {**bundle_core, "content_sha256": canonical_sha256(bundle_core)}
        stored_path = _write_json(tmp_path, f"bundles/{block_id}.json", bundle)
        fresh_path = _write_json(tmp_path, f"fresh_bundles/{block_id}.json", bundle)
        stored_ref = evidence_ref(stored_path)
        fresh_ref = evidence_ref(fresh_path)
        receipt = {
            "schema_version": "xinao.fresh_assertion_bundle_receipt.v2",
            "protocol_version": PROTOCOL_VERSION,
            "block_id": block_id,
            "request_ref": request_ref,
            "first_bundle_ref": stored_ref,
            "second_bundle_ref": fresh_ref,
            "entrypoint_source_ref": source_ref,
            "compiler_code_manifest_ref": code_manifest_ref,
            "double_fresh_bytes_equal": True,
        }
        receipt_path = _write_json(tmp_path, f"receipts/{block_id}.json", receipt)
        receipt_ref = evidence_ref(receipt_path)
        assertion_results: dict[str, Any] = {}
        for assertion_id in assertions:
            expected = profile_block["required_assertions"][assertion_id]
            assertion_payload = {
                "schema_version": "xinao.closure_assertion_evidence.v3",
                "assertion_id": assertion_id,
                "result": "PASS",
                "checker_id": checker_id,
                "checker_version": checker_version,
                "checker_code_hash": source_ref["sha256"],
                "config_hash": input_hashes["compiler_config_sha256"],
                "producer_ids": [f"producer:{block_id}"],
                "verifier_id": f"block-verifier:{block_id}",
                "input_hashes": input_hashes,
                "artifact_source_hashes": artifact_source_hashes,
                "actual": expected,
                "expected": expected,
                "actual_content_sha256": actual_hashes[assertion_id],
                "assertion_bundle_content_sha256": bundle["content_sha256"],
                "assertion_bundle_ref": stored_ref,
                "fresh_assertion_bundle_ref": fresh_ref,
                "fresh_receipt_ref": receipt_ref,
                "compiler_code_manifest_ref": code_manifest_ref,
                "executed_at": "2026-07-14T08:00:00Z",
            }
            output_path = _write_json(
                tmp_path,
                f"assertions/{block_id}/{assertion_id}.json",
                assertion_payload,
            )
            output_ref = evidence_ref(output_path, assertion_id=assertion_id)
            assertion_results[assertion_id] = {
                key: value
                for key, value in assertion_payload.items()
                if key not in {"schema_version", "actual", "expected"} and not key.endswith("_ref")
            } | {
                "evidence_refs": [output_ref],
                "output_hash": output_ref["sha256"],
            }
        block_reports[block_id] = {
            "block_id": block_id,
            "artifact_versions": artifact_versions,
            "artifact_hashes": {ref["artifact_type"]: ref["sha256"] for ref in artifact_refs},
            "input_hashes": input_hashes,
            "assertion_results": assertion_results,
            "evidence_refs": artifact_refs,
            "producer_ids": [f"producer:{block_id}"],
            "verifier_id": f"block-verifier:{block_id}",
        }
    report_input = {
        "report_id": "foundation-closure:test",
        "version": "foundation-closure.v1",
        "created_at": "2026-07-14T08:00:00Z",
        "input_hashes": input_hashes,
        "code_hash": input_hashes["compiler_code_sha256"],
        "config_hash": input_hashes["compiler_config_sha256"],
        "compiler_code_manifest_ref": code_manifest_ref,
        "block_reports": block_reports,
        "evidence_refs": list(input_refs.values()),
        "producer_ids": ["report-producer"],
        "independent_verifier_id": "report-independent-verifier",
    }
    return report_input, blueprint_path


def _derive(
    tmp_path: Path,
    *,
    canonical_projection: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    report_input, blueprint_path = _fixture(
        tmp_path,
        canonical_projection=canonical_projection,
    )
    return (
        derive_foundation_closure_report(report_input, blueprint_path=blueprint_path),
        report_input,
        blueprint_path,
    )


def test_caller_forged_identical_bundles_cannot_open_formal_research(
    tmp_path: Path,
) -> None:
    result, _, blueprint_path = _derive(tmp_path, canonical_projection=False)

    # This fixture deliberately hand-writes both bundle files and the receipt
    # without running the canonical verifier.  A non-canonical authority
    # projection is not eligible even for a PARTIAL production-profile replay.
    assert result["status"] == "NOT_PERFORMED"
    assert result["foundation_closed"] is False
    assert result["formal_research_allowed"] is False
    assert result["formal_research_gate"] == "CLOSED"
    assert result["canonical_projection_bound"] is False
    assert result["canonical_bundle_replay_verified"] is False
    assert result["legacy_a_g_gate_used"] is False
    assert result["blockers"][0].startswith("authority_projection_not_canonical:")
    assert verify_foundation_closure_report(result, blueprint_path=blueprint_path)["ok"] is True


def test_missing_rebate_schedule_fails_f2_and_keeps_gate_closed(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    f2 = report_input["block_reports"]["F2_issuer_settlement_cost_space"]
    f2["artifact_versions"].pop("RebateScheduleVersion")
    f2["artifact_hashes"].pop("RebateScheduleVersion")

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)

    assert result["block_reports"]["F2_issuer_settlement_cost_space"]["status"] == "PARTIAL"
    assert result["foundation_closed"] is False
    assert result["formal_research_gate"] == "CLOSED"


def test_legacy_artifacts_cannot_compensate_for_missing_f_block(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    report_input["block_reports"].pop("F3_research_weight")
    report_input["formal_ledger_report"] = {"ok": True}
    report_input["family_validation_report"] = {"shadow_ledger_ok": True}

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)

    assert result["bindings_complete"] is False
    assert result["block_reports"]["F3_research_weight"]["status"] == "PARTIAL"
    assert result["foundation_closed"] is False


def test_wrong_block_id_is_closed(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    report_input["block_reports"]["F1_settlement_world"]["block_id"] = "WRONG"

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)

    assert result["foundation_closed"] is False
    assert "block_id_mismatch" in result["block_reports"]["F1_settlement_world"]["failure_reasons"]


def test_frozen_route_quote_artifact_is_not_a_gate_requirement_or_hash(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    f1 = report_input["block_reports"]["F1_settlement_world"]
    artifact_type = "FrozenAgentRouteQuoteMap"
    payload = _content_hashed(
        {
            "records": [
                {
                    "baseline_id": "BO0013",
                    "physical_role": "FROZEN_AGENT_ROUTE_QUOTE",
                }
            ]
        }
    )
    source = _write_json(tmp_path, "artifact_sources/frozen.json", payload)
    source_ref = evidence_ref(source, artifact_type=artifact_type)
    envelope = _write_json(
        tmp_path,
        "artifacts/F1_settlement_world/frozen.json",
        {
            "artifact_type": artifact_type,
            "version": "frozen.v1",
            "input_hashes": report_input["input_hashes"],
            "code_hash": report_input["code_hash"],
            "config_hash": report_input["config_hash"],
            "source_ref": source_ref,
            "payload": payload,
            "payload_sha256": canonical_sha256(payload),
        },
    )
    ref = evidence_ref(envelope, artifact_type=artifact_type)
    f1["artifact_versions"][artifact_type] = "frozen.v1"
    f1["artifact_hashes"][artifact_type] = ref["sha256"]
    f1["evidence_refs"].append(ref)

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)
    reasons = result["block_reports"]["F1_settlement_world"]["failure_reasons"]

    assert result["foundation_closed"] is False
    assert "required_artifact_set_mismatch" in reasons
    assert "f1_active_artifact_payload_set_mismatch" in reasons


def test_f1_artifact_config_seal_cannot_be_rewritten_to_green(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    f1 = report_input["block_reports"]["F1_settlement_world"]
    artifact_type = "RuleSemanticMapVersion"
    old_ref = next(item for item in f1["evidence_refs"] if item["artifact_type"] == artifact_type)
    envelope_path = Path(old_ref["path"])
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    envelope["config_hash"] = "0" * 64
    envelope_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
    replacement = evidence_ref(envelope_path, artifact_type=artifact_type)
    f1["evidence_refs"] = [
        replacement if item["artifact_type"] == artifact_type else item
        for item in f1["evidence_refs"]
    ]
    f1["artifact_hashes"][artifact_type] = replacement["sha256"]

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)

    assert result["foundation_closed"] is False
    assert (
        f"artifact_evidence_payload_mismatch:{artifact_type}"
        in result["block_reports"]["F1_settlement_world"]["failure_reasons"]
    )


def test_artifact_and_assertion_outputs_must_bind_real_evidence(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    f2 = report_input["block_reports"]["F2_issuer_settlement_cost_space"]
    f2["artifact_hashes"]["RebateScheduleVersion"] = "a" * 64
    assertion = f2["assertion_results"]["turnover_rebate_materialized"]
    assertion["output_hash"] = "b" * 64

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)
    reasons = result["block_reports"]["F2_issuer_settlement_cost_space"]["failure_reasons"]

    assert result["foundation_closed"] is False
    assert "artifact_not_bound_to_evidence:RebateScheduleVersion" in reasons
    assert "assertion_output_not_bound_to_evidence:turnover_rebate_materialized" in reasons


def test_metadata_only_artifact_cannot_pose_as_compiled_payload(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    f1 = report_input["block_reports"]["F1_settlement_world"]
    artifact_type = "RuleSemanticMapVersion"
    ref = next(item for item in f1["evidence_refs"] if item["artifact_type"] == artifact_type)
    path = Path(ref["path"])
    path.write_text(
        json.dumps(
            {
                "artifact_type": artifact_type,
                "version": f1["artifact_versions"][artifact_type],
                "input_hashes": report_input["input_hashes"],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    replacement = evidence_ref(path, artifact_type=artifact_type)
    f1["evidence_refs"] = [
        replacement if item["artifact_type"] == artifact_type else item
        for item in f1["evidence_refs"]
    ]
    f1["artifact_hashes"][artifact_type] = replacement["sha256"]

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)

    assert result["foundation_closed"] is False
    assert (
        f"artifact_evidence_payload_mismatch:{artifact_type}"
        in result["block_reports"]["F1_settlement_world"]["failure_reasons"]
    )


def test_input_keys_config_code_and_evidence_are_bound(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    report_input["input_hashes"]["unexpected"] = "a" * 64

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)

    assert result["bindings_complete"] is False
    assert result["foundation_closed"] is False


def test_report_verifier_cannot_reuse_any_checker_role(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    assertion = report_input["block_reports"]["F1_settlement_world"]["assertion_results"][
        "semantic_rule_mapped_eq"
    ]
    report_input["independent_verifier_id"] = assertion["checker_id"]

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)

    assert result["bindings_complete"] is False
    assert result["foundation_closed"] is False


def test_same_unrelated_file_cannot_pose_as_every_assertion(tmp_path: Path) -> None:
    report_input, blueprint_path = _fixture(tmp_path)
    unrelated = _write(tmp_path, "unrelated.txt", "ordinary file\n")
    for block in report_input["block_reports"].values():
        for assertion_id, assertion in block["assertion_results"].items():
            ref = evidence_ref(unrelated, assertion_id=assertion_id)
            assertion["evidence_refs"] = [ref]
            assertion["output_hash"] = ref["sha256"]

    result = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)

    assert result["foundation_closed"] is False
    assert any(
        "assertion_evidence_schema_mismatch" in reason
        for block in result["block_reports"].values()
        for reason in block["failure_reasons"]
    )


def test_evidence_tampering_after_derivation_is_detected(tmp_path: Path) -> None:
    result, _, blueprint_path = _derive(tmp_path)
    evidence_path = Path(result["block_reports"]["F1_settlement_world"]["evidence_refs"][0]["path"])
    evidence_path.write_text('{"tampered":true}\n', encoding="utf-8")

    verification = verify_foundation_closure_report(result, blueprint_path=blueprint_path)

    assert verification["ok"] is False
    assert verification["checks"]["block_derivations_match"] is False


def test_manual_gate_or_status_tampering_is_detected(tmp_path: Path) -> None:
    result, _, blueprint_path = _derive(tmp_path)
    tampered = deepcopy(result)
    tampered["formal_research_gate"] = "OPEN"

    verification = verify_foundation_closure_report(tampered, blueprint_path=blueprint_path)

    assert verification["ok"] is False
    assert verification["checks"]["derived_report_fields_match"] is False


def test_schema_version_is_acceptance_critical(tmp_path: Path) -> None:
    result, _, blueprint_path = _derive(tmp_path)
    result["schema_version"] = "xinao.foundation_closure_report.v0"
    body = dict(result)
    body.pop("artifact_hash")
    result["artifact_hash"] = canonical_sha256(body)

    verification = verify_foundation_closure_report(result, blueprint_path=blueprint_path)

    assert verification["ok"] is False
    assert verification["checks"]["schema_version_matches"] is False
