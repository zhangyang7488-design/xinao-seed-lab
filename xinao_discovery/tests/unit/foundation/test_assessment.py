from __future__ import annotations

import json
from pathlib import Path

from xinao.canonical import canonical_sha256
from xinao.catalog import family_registry
from xinao.contracts.objects import PLAY_GROUP_NAMES
from xinao.foundation import assess_foundation
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    FROZEN_ROUTE_QUOTE_BASELINE_IDS,
)

FAMILIES = tuple(f"family-{index:02d}" for index in range(13))
PLAY_GROUPS = tuple(sorted(PLAY_GROUP_NAMES))


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixtures(root: Path, *, compiled: int, operation_id: str) -> tuple[Path, Path, Path]:
    evidence = root / "evidence"
    dataset_hash = "a" * 64
    baseline_hash = "b" * 64
    _write(
        evidence / "capability_manifest.json" / "input_material_manifest.json",
        {
            "result_status": "verified",
            "dataset_verification": {
                "ok": True,
                "declared_records": 913,
                "human_record_lines": 913,
                "json_record_lines": 913,
            },
            "baseline_verification": {
                "ok": True,
                "data_rows": 433,
                "play_group_names": list(FAMILIES),
            },
            "materials": [
                {
                    "material_id": "macaujc2-authority-dataset-2024-01-01--2026-07-01",
                    "sha256": dataset_hash,
                },
                {"material_id": "baseline-odds-water.v1", "sha256": baseline_hash},
            ],
        },
    )
    _write(
        evidence / "canonical_golden_report.json",
        {
            "ok": True,
            "local_process": {"ok": True},
            "fresh_process": {"ok": True},
            "sqlite_readback": {"ok": True},
            "postgres_readback": {"ok": True},
        },
    )
    if not 0 <= compiled <= len(ACTIVE_SETTLEMENT_BASELINE_IDS):
        raise ValueError("compiled must describe ACTIVE settlement rows only")
    compiled_ids = set(sorted(ACTIVE_SETTLEMENT_BASELINE_IDS)[:compiled])
    entries = []
    for index in range(433):
        baseline_id = f"BO{index + 1:04d}"
        is_frozen = baseline_id in FROZEN_ROUTE_QUOTE_BASELINE_IDS
        is_compiled = baseline_id in compiled_ids
        entries.append(
            {
                "baseline_id": baseline_id,
                "play_group": PLAY_GROUPS[index % 13],
                "family_id": FAMILIES[index % 13],
                "physical_role": ("FROZEN_AGENT_ROUTE_QUOTE" if is_frozen else "ACTIVE_SETTLEMENT"),
                "compilation_status": (
                    "FROZEN" if is_frozen else "COMPILED" if is_compiled else "NOT_COMPILED"
                ),
                "settlement_function_ref": f"settle-{index % 13}" if is_compiled else None,
            }
        )
    catalog = {"catalog_ref": "play-catalog.v1", "entries": entries}
    catalog["content_hash"] = canonical_sha256(catalog)
    catalog_path = root / "catalog.json"
    _write(catalog_path, catalog)
    family_registry(catalog, output_path=root / "play_family.v1.json")
    _write(
        evidence / "catalog_coverage.json",
        {
            "source_total": 433,
            "classified": 433,
            "active_required": 416,
            "active_compiled": compiled,
            "active_not_compiled": 416 - compiled,
            "frozen_agent_route_quote_count": 17,
            "unclassified_count": 0,
            "catalog_content_hash": catalog["content_hash"],
        },
    )
    _write(
        evidence / "world_special_number" / "evidence_manifest.json",
        {
            "result_status": "verified",
            "dataset_hash": dataset_hash,
            "baseline_hash": baseline_hash,
        },
    )
    _write(
        evidence / "validation_court" / "candidate_validation_report.json",
        {"verdict": "NO_ACTION"},
    )
    route_path = root / "route.json"
    _write(
        route_path,
        {
            "ok": True,
            "workflow_status": "completed",
            "workflow_id": "wf-current",
            "run_id": "run-current",
            "parent_operation_id": operation_id,
            "result": {
                "ok": True,
                "grok_fanin": {"ok": True, "model": "grok-4.5", "succeeded": 1},
                "langgraph_children": [{"passed": True}],
            },
        },
    )
    return evidence, catalog_path, route_path


def test_current_narrow_vertical_fails_closed(tmp_path: Path) -> None:
    operation_id = "foundation-run"
    evidence, catalog, route = _fixtures(tmp_path, compiled=2, operation_id=operation_id)
    result = assess_foundation(
        evidence_root=evidence,
        catalog_path=catalog,
        route_result_path=route,
        operation_id=operation_id,
    )
    assert {name: gate["status"] for name, gate in result["gates"].items()} == {
        "A": "verified",
        "B": "verified",
        "C": "partial",
        "D": "broken",
        "E": "broken",
        "F": "partial",
        "G": "missing",
    }
    assert result["catalog_coverage"]["active_compiled"] == 2
    assert result["catalog_coverage"]["frozen_agent_route_quote_count"] == 17
    assert result["legacy_diagnostic_only"] is True
    assert result["foundation_closed"] is False
    assert result["formal_research_allowed"] is False


def test_authorized_rule_source_removes_authority_blocker_without_lowering_gate_d(
    tmp_path: Path,
) -> None:
    operation_id = "foundation-run"
    evidence, catalog, route = _fixtures(tmp_path, compiled=2, operation_id=operation_id)
    bundle_hash = "c" * 64
    _write(
        evidence / "source_bundle_verification.json",
        {
            "ok": True,
            "source_type": "TARGET_MARKET_PAGE_SNAPSHOT",
            "source_bundle_hash": bundle_hash,
            "authority_basis": "USER_CONFIRMED_LOCAL_SNAPSHOT",
            "manifest_hash_ok": True,
            "listed_files_ok": True,
            "file_set_ok": True,
        },
    )
    _write(
        evidence / "special_number_rule_evidence.json",
        {
            "ok": True,
            "slice_evidence_ok": True,
            "verification_scope": "SPECIAL_NUMBER_EXACT_NUMBER_SLICE_ONLY",
            "foundation_closure_claim_allowed": False,
            "source_type": "TARGET_MARKET_PAGE_SNAPSHOT",
            "source_bundle_hash": bundle_hash,
            "authority_basis": "USER_CONFIRMED_LOCAL_SNAPSHOT",
            "semantic_status": ["EXPLICIT_PAGE", "RESEARCH_CONVENTION"],
            "compiled_baseline_ids": ["BO0001", "BO0013"],
            "family_compilation_status": "PARTIALLY_COMPILED",
        },
    )
    _write(
        evidence / "durability_recovery_report.json",
        {
            "ok": True,
            "operation_id": operation_id,
            "continue_as_new_verified": True,
            "history_event_count": 555,
            "checkpoint_recovery_verified": True,
        },
    )
    result = assess_foundation(
        evidence_root=evidence,
        catalog_path=catalog,
        route_result_path=route,
        operation_id=operation_id,
    )
    assert result["rule_authority"]["authorized_local_snapshot_bound"] is True
    assert result["gates"]["D"]["status"] == "broken"
    assert "only 2/416 ACTIVE plays" in result["gates"]["D"]["summary"]
    assert result["foundation_closed"] is False
    assert result["formal_research_allowed"] is False
    assert result["gates"]["F"]["status"] == "verified"
    assert result["ready_frontier"][2] == {
        "priority": 3,
        "gate": "G",
        "action": "backup_and_restore_this_foundation_with_lineage",
    }


def test_legacy_433_compiled_shape_cannot_reopen_frozen_b_as_missing_work(
    tmp_path: Path,
) -> None:
    operation_id = "foundation-run"
    evidence, catalog, route = _fixtures(tmp_path, compiled=416, operation_id=operation_id)
    catalog_hash = json.loads(catalog.read_text(encoding="utf-8"))["content_hash"]
    _write(
        evidence / "catalog_coverage.json",
        {
            "total": 433,
            "compiled": 433,
            "not_compiled": 0,
            "unclassified_count": 0,
            "catalog_content_hash": catalog_hash,
        },
    )

    result = assess_foundation(
        evidence_root=evidence,
        catalog_path=catalog,
        route_result_path=route,
        operation_id=operation_id,
    )

    assert result["catalog_coverage"]["active_compiled"] == 416
    assert result["catalog_coverage"]["active_not_compiled"] == 0
    assert result["catalog_coverage"]["frozen_agent_route_quote_count"] == 17
    assert "active_split_coverage_identity_missing" in result["gates"]["D"]["blockers"]
    assert "active_not_compiled_entries_present" not in result["gates"]["D"]["blockers"]
    assert result["foundation_closed"] is False


def test_all_gates_can_close_with_current_bound_evidence(tmp_path: Path) -> None:
    operation_id = "foundation-run"
    evidence, catalog_path, route = _fixtures(tmp_path, compiled=416, operation_id=operation_id)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_hash = catalog["content_hash"]
    representatives = [
        {
            "family_id": family,
            "settlement_function_ref": f"settle-{index}",
            "replay_ok": True,
        }
        for index, family in enumerate(FAMILIES)
    ]
    _write(
        evidence / "family_settlement_report.json",
        {"ok": True, "catalog_content_hash": catalog_hash, "representatives": representatives},
    )
    _write(
        evidence / "formal_ledger_report.json",
        {
            "ok": True,
            "catalog_content_hash": catalog_hash,
            "family_ids": list(FAMILIES),
            "live_source_truth_ok": True,
            "freeze_ok": True,
            "confirmation_ok": True,
            "ledger_replay_ok": True,
        },
    )
    _write(
        evidence / "family_validation_report.json",
        {
            "ok": True,
            "catalog_content_hash": catalog_hash,
            "families": [
                {
                    "family_id": family,
                    "statistics_ok": True,
                    "decision_ok": True,
                    "freeze_ok": True,
                    "settlement_ok": True,
                    "shadow_ledger_ok": True,
                }
                for family in FAMILIES
            ],
        },
    )
    _write(
        evidence / "durability_recovery_report.json",
        {
            "ok": True,
            "operation_id": operation_id,
            "continue_as_new_verified": True,
            "history_event_count": 185,
            "checkpoint_recovery_verified": True,
        },
    )
    _write(
        evidence / "current_foundation_restore_report.json",
        {
            "ok": True,
            "catalog_content_hash": catalog_hash,
            "isolated_restore_ok": True,
            "dataset_sha256": "a" * 64,
            "baseline_sha256": "b" * 64,
            "mlflow_run_id": "mlflow-1",
            "openlineage_run_id": "lineage-1",
            "trace_id": "trace-1",
        },
    )
    result = assess_foundation(
        evidence_root=evidence,
        catalog_path=catalog_path,
        route_result_path=route,
        operation_id=operation_id,
    )
    assert all(gate["status"] == "verified" for gate in result["gates"].values())
    assert result["legacy_all_gates_verified"] is True
    assert result["legacy_diagnostic_only"] is True
    assert result["foundation_closed"] is False
    assert result["formal_research_allowed"] is False
