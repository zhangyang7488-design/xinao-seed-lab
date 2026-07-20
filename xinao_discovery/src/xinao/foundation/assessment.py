"""Build a fail-closed A-G foundation gap matrix from current evidence.

The assessor deliberately separates 433-row source classification from the
416-row ACTIVE settlement surface.  The 17 frozen agent-route quotes are
catalog evidence, not missing settlement work.  Missing evidence never becomes
an implicit pass, and historical restore evidence must be rebound to the
current input and catalog hashes before it can close gate G.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    FROZEN_ROUTE_QUOTE_BASELINE_IDS,
)

FOUNDATION_STATUSES = {"verified", "partial", "broken", "missing", "not_applicable"}
REQUIRED_FAMILY_COUNT = 13
REQUIRED_PLAY_COUNT = 433
REQUIRED_ACTIVE_PLAY_COUNT = 416
REQUIRED_FROZEN_ROUTE_QUOTE_COUNT = 17
REQUIRED_DRAW_COUNT = 913


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _read_optional(path: Path) -> dict[str, Any] | None:
    return _read_json(path) if path.is_file() else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _first_existing(*paths: Path) -> Path:
    for path in paths:
        if path.is_file():
            return path
    return paths[0]


def _gate(
    status: str,
    summary: str,
    *,
    evidence: list[str],
    blockers: list[str],
) -> dict[str, Any]:
    if status not in FOUNDATION_STATUSES:
        raise ValueError(f"invalid foundation status: {status}")
    return {
        "status": status,
        "summary": summary,
        "evidence": evidence,
        "blockers": blockers,
    }


def _catalog_family_coverage(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise ValueError("catalog entries are missing")
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("catalog entry must be an object")
        key = (str(raw.get("play_group", "")), str(raw.get("family_id", "")))
        if not all(key):
            raise ValueError("catalog family identity is missing")
        item = grouped.setdefault(
            key,
            {
                "play_group": key[0],
                "family_id": key[1],
                "source_total": 0,
                "active_required": 0,
                "active_compiled": 0,
                "active_not_compiled": 0,
                "frozen_agent_route_quote_count": 0,
                "settlement_function_refs": [],
            },
        )
        item["source_total"] += 1
        baseline_id = str(raw.get("baseline_id", ""))
        if baseline_id in FROZEN_ROUTE_QUOTE_BASELINE_IDS:
            item["frozen_agent_route_quote_count"] += 1
            continue
        if baseline_id not in ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError(f"catalog baseline role is unclassified: {baseline_id}")
        item["active_required"] += 1
        if raw.get("compilation_status") == "COMPILED" and raw.get("settlement_function_ref"):
            item["active_compiled"] += 1
            ref = str(raw["settlement_function_ref"])
            if ref not in item["settlement_function_refs"]:
                item["settlement_function_refs"].append(ref)
        else:
            item["active_not_compiled"] += 1
    return sorted(grouped.values(), key=lambda item: item["family_id"])


def _route_is_live(route: dict[str, Any] | None, operation_id: str) -> bool:
    if route is None:
        return False
    result = route.get("result")
    if not isinstance(result, dict):
        return False
    fanin = result.get("grok_fanin")
    children = result.get("langgraph_children")
    return bool(
        route.get("ok") is True
        and route.get("workflow_status") == "completed"
        and route.get("parent_operation_id") == operation_id
        and result.get("ok") is True
        and isinstance(fanin, dict)
        and fanin.get("ok") is True
        and fanin.get("model") == "grok-4.5"
        and int(fanin.get("succeeded", 0)) >= 1
        and isinstance(children, list)
        and any(isinstance(child, dict) and child.get("passed") is True for child in children)
    )


def _recovery_is_current(report: dict[str, Any] | None, operation_id: str) -> bool:
    return bool(
        report
        and report.get("ok") is True
        and report.get("operation_id") == operation_id
        and report.get("continue_as_new_verified") is True
        and int(report.get("history_event_count", 0)) > 0
        and report.get("checkpoint_recovery_verified") is True
    )


def _rule_source_is_authorized(
    source_report: dict[str, Any] | None,
    rule_report: dict[str, Any] | None,
) -> bool:
    return bool(
        source_report
        and rule_report
        and source_report.get("ok") is True
        and source_report.get("source_type") == "TARGET_MARKET_PAGE_SNAPSHOT"
        and source_report.get("authority_basis") == "USER_CONFIRMED_LOCAL_SNAPSHOT"
        and source_report.get("manifest_hash_ok") is True
        and source_report.get("listed_files_ok") is True
        and source_report.get("file_set_ok") is True
        and rule_report.get("ok") is True
        and rule_report.get("slice_evidence_ok") is True
        and rule_report.get("verification_scope") == "SPECIAL_NUMBER_EXACT_NUMBER_SLICE_ONLY"
        and rule_report.get("foundation_closure_claim_allowed") is False
        and rule_report.get("source_type") == "TARGET_MARKET_PAGE_SNAPSHOT"
        and rule_report.get("authority_basis") == "USER_CONFIRMED_LOCAL_SNAPSHOT"
        and rule_report.get("source_bundle_hash") == source_report.get("source_bundle_hash")
        and rule_report.get("semantic_status") == ["EXPLICIT_PAGE", "RESEARCH_CONVENTION"]
        and rule_report.get("compiled_baseline_ids") == ["BO0001", "BO0013"]
        and rule_report.get("family_compilation_status") == "PARTIALLY_COMPILED"
    )


def _report_binds_catalog(report: dict[str, Any] | None, catalog_hash: str) -> bool:
    return bool(
        report and report.get("ok") is True and report.get("catalog_content_hash") == catalog_hash
    )


def _family_replays_close(
    report: dict[str, Any] | None, *, catalog_hash: str, family_ids: set[str]
) -> bool:
    if not _report_binds_catalog(report, catalog_hash):
        return False
    representatives = report.get("representatives") if report else None
    if not isinstance(representatives, list):
        return False
    replayed = {
        str(item.get("family_id"))
        for item in representatives
        if isinstance(item, dict)
        and item.get("replay_ok") is True
        and item.get("settlement_function_ref")
    }
    return replayed == family_ids


def _family_validation_closes(
    report: dict[str, Any] | None, *, catalog_hash: str, family_ids: set[str]
) -> bool:
    if not _report_binds_catalog(report, catalog_hash):
        return False
    families = report.get("families") if report else None
    if not isinstance(families, list):
        return False
    required = (
        "statistics_ok",
        "decision_ok",
        "freeze_ok",
        "settlement_ok",
        "shadow_ledger_ok",
    )
    closed = {
        str(item.get("family_id"))
        for item in families
        if isinstance(item, dict) and all(item.get(field) is True for field in required)
    }
    return closed == family_ids


def _formal_ledger_closes(
    report: dict[str, Any] | None, *, catalog_hash: str, family_ids: set[str]
) -> bool:
    return bool(
        _report_binds_catalog(report, catalog_hash)
        and report
        and set(report.get("family_ids", [])) == family_ids
        and report.get("live_source_truth_ok") is True
        and report.get("freeze_ok") is True
        and report.get("confirmation_ok") is True
        and report.get("ledger_replay_ok") is True
    )


def _restore_closes(
    report: dict[str, Any] | None,
    *,
    catalog_hash: str,
    dataset_hash: str,
    baseline_hash: str,
) -> bool:
    return bool(
        _report_binds_catalog(report, catalog_hash)
        and report
        and report.get("isolated_restore_ok") is True
        and report.get("dataset_sha256") == dataset_hash
        and report.get("baseline_sha256") == baseline_hash
        and report.get("mlflow_run_id")
        and report.get("openlineage_run_id")
        and report.get("trace_id")
    )


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def assess_foundation(
    *,
    evidence_root: Path,
    catalog_path: Path,
    route_result_path: Path,
    operation_id: str,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Assess A-G against current artifacts and optionally persist the matrix."""

    input_manifest_path = _first_existing(
        evidence_root / "input_material_manifest.json",
        evidence_root / "capability_manifest.json" / "input_material_manifest.json",
    )
    canonical_path = evidence_root / "canonical_golden_report.json"
    coverage_path = evidence_root / "catalog_coverage.json"
    world_path = evidence_root / "world_special_number" / "evidence_manifest.json"
    validation_path = evidence_root / "validation_court" / "candidate_validation_report.json"
    required_paths = (
        input_manifest_path,
        canonical_path,
        coverage_path,
        world_path,
        validation_path,
        catalog_path,
        route_result_path,
    )
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"required foundation evidence missing: {missing}")

    input_manifest = _read_json(input_manifest_path)
    canonical = _read_json(canonical_path)
    coverage = _read_json(coverage_path)
    world = _read_json(world_path)
    validation = _read_json(validation_path)
    catalog = _read_json(catalog_path)
    route = _read_json(route_result_path)

    family_replay_path = evidence_root / "family_settlement_report.json"
    family_validation_path = evidence_root / "family_validation_report.json"
    formal_ledger_path = evidence_root / "formal_ledger_report.json"
    recovery_path = evidence_root / "durability_recovery_report.json"
    restore_path = evidence_root / "current_foundation_restore_report.json"
    source_bundle_path = evidence_root / "source_bundle_verification.json"
    special_rule_path = evidence_root / "special_number_rule_evidence.json"
    family_registry_path = catalog_path.with_name("play_family.v1.json")
    family_replay = _read_optional(family_replay_path)
    family_validation = _read_optional(family_validation_path)
    formal_ledger = _read_optional(formal_ledger_path)
    recovery = _read_optional(recovery_path)
    restore = _read_optional(restore_path)
    source_bundle = _read_optional(source_bundle_path)
    special_rule = _read_optional(special_rule_path)
    family_registry = _read_optional(family_registry_path)

    family_coverage = _catalog_family_coverage(catalog)
    family_ids = {str(item["family_id"]) for item in family_coverage}
    source_total = sum(int(item["source_total"]) for item in family_coverage)
    active_required = sum(int(item["active_required"]) for item in family_coverage)
    active_compiled = sum(int(item["active_compiled"]) for item in family_coverage)
    active_not_compiled = sum(int(item["active_not_compiled"]) for item in family_coverage)
    frozen_route_quotes = sum(
        int(item["frozen_agent_route_quote_count"]) for item in family_coverage
    )
    classified = active_required + frozen_route_quotes
    unclassified = source_total - classified
    catalog_hash = str(catalog.get("content_hash", ""))
    rule_source_authorized = _rule_source_is_authorized(source_bundle, special_rule)

    dataset_verification = input_manifest.get("dataset_verification", {})
    baseline_verification = input_manifest.get("baseline_verification", {})
    materials = input_manifest.get("materials", [])
    material_hashes = {
        str(item.get("material_id")): str(item.get("sha256"))
        for item in materials
        if isinstance(item, dict)
    }
    dataset_hash = material_hashes.get("macaujc2-authority-dataset-2024-01-01--2026-07-01", "")
    baseline_hash = material_hashes.get("baseline-odds-water.v1", "")

    a_ok = bool(
        input_manifest.get("result_status") == "verified"
        and isinstance(dataset_verification, dict)
        and dataset_verification.get("ok") is True
        and dataset_verification.get("declared_records") == REQUIRED_DRAW_COUNT
        and dataset_verification.get("human_record_lines") == REQUIRED_DRAW_COUNT
        and dataset_verification.get("json_record_lines") == REQUIRED_DRAW_COUNT
        and isinstance(baseline_verification, dict)
        and baseline_verification.get("ok") is True
        and baseline_verification.get("data_rows") == REQUIRED_PLAY_COUNT
        and len(baseline_verification.get("play_group_names", [])) == REQUIRED_FAMILY_COUNT
        and dataset_hash
        and baseline_hash
    )
    b_ok = bool(
        canonical.get("ok") is True
        and all(
            isinstance(canonical.get(key), dict) and canonical[key].get("ok") is True
            for key in ("local_process", "fresh_process", "sqlite_readback", "postgres_readback")
        )
    )
    coverage_identity_ok = bool(
        coverage.get("source_total") == REQUIRED_PLAY_COUNT
        and coverage.get("classified") == classified
        and coverage.get("active_required") == REQUIRED_ACTIVE_PLAY_COUNT
        and coverage.get("frozen_agent_route_quote_count") == REQUIRED_FROZEN_ROUTE_QUOTE_COUNT
        and coverage.get("catalog_content_hash") == catalog_hash
        and coverage.get("active_compiled") == active_compiled
        and coverage.get("active_not_compiled") == active_not_compiled
        and coverage.get("unclassified_count") == unclassified == 0
        and source_total == REQUIRED_PLAY_COUNT
        and active_required == REQUIRED_ACTIVE_PLAY_COUNT
        and frozen_route_quotes == REQUIRED_FROZEN_ROUTE_QUOTE_COUNT
        and len(family_ids) == REQUIRED_FAMILY_COUNT
    )
    family_registry_ok = bool(
        family_registry
        and family_registry.get("identity_complete") is True
        and family_registry.get("family_count") == REQUIRED_FAMILY_COUNT
        and family_registry.get("catalog_content_hash") == catalog_hash
    )
    catalog_complete = bool(
        coverage_identity_ok
        and active_compiled == REQUIRED_ACTIVE_PLAY_COUNT
        and active_not_compiled == 0
    )
    family_replay_ok = _family_replays_close(
        family_replay, catalog_hash=catalog_hash, family_ids=family_ids
    )
    d_ok = catalog_complete and family_registry_ok and family_replay_ok
    formal_ledger_ok = _formal_ledger_closes(
        formal_ledger, catalog_hash=catalog_hash, family_ids=family_ids
    )
    c_narrow_ok = bool(
        world.get("result_status") == "verified"
        and world.get("dataset_hash") == dataset_hash
        and world.get("baseline_hash") == baseline_hash
        and validation.get("verdict") in {"NO_ACTION", "CONFIRMED"}
    )
    c_ok = d_ok and formal_ledger_ok
    family_validation_ok = _family_validation_closes(
        family_validation, catalog_hash=catalog_hash, family_ids=family_ids
    )
    e_ok = d_ok and family_validation_ok
    route_ok = _route_is_live(route, operation_id)
    recovery_ok = _recovery_is_current(recovery, operation_id)
    f_ok = route_ok and recovery_ok
    restore_ok = _restore_closes(
        restore,
        catalog_hash=catalog_hash,
        dataset_hash=dataset_hash,
        baseline_hash=baseline_hash,
    )
    d_blockers = []
    if not d_ok:
        if not coverage_identity_ok:
            d_blockers.append("active_split_coverage_identity_missing")
        if active_not_compiled:
            d_blockers.append("active_not_compiled_entries_present")
        if not family_replay_ok:
            d_blockers.append("family_representative_replays_missing")
        if not family_registry_ok:
            d_blockers.append("family_registry_identity_missing")

    gates = {
        "A": _gate(
            "verified" if a_ok else "broken",
            "913-draw and 433-play formal input identity is pinned."
            if a_ok
            else "Formal input identity does not satisfy the fixed 913/433 contract.",
            evidence=["input_material_manifest"],
            blockers=[] if a_ok else ["input_identity_or_hash_mismatch"],
        ),
        "B": _gate(
            "verified" if b_ok else "broken",
            "Canonical envelopes replay across local, fresh-process, SQLite, and Postgres."
            if b_ok
            else "Cross-runtime canonical replay is incomplete.",
            evidence=["canonical_golden_report"],
            blockers=[] if b_ok else ["canonical_cross_runtime_readback_failed"],
        ),
        "C": _gate(
            "verified" if c_ok else ("partial" if c_narrow_ok else "missing"),
            "Wide live truth, freeze, confirmation, and ledger replay are verified."
            if c_ok
            else (
                "A replayable special-number vertical exists, but wide formal ledger "
                "evidence is absent."
            )
            if c_narrow_ok
            else "No admissible live formal truth and ledger replay evidence is present.",
            evidence=["world_special_number", "candidate_validation_report"]
            + (["formal_ledger_report"] if formal_ledger else []),
            blockers=[] if c_ok else ["wide_formal_ledger_not_verified", "depends_on_D"],
        ),
        "D": _gate(
            "verified" if d_ok else ("broken" if coverage_identity_ok else "missing"),
            "All 433 source rows are classified, all 416 ACTIVE plays are compiled, "
            "and every family has a replayed representative."
            if d_ok
            else (
                (
                    "The authorized snapshot and first RuleVersion slice are verified; "
                    f"only {active_compiled}/{REQUIRED_ACTIVE_PLAY_COUNT} ACTIVE plays "
                    "are compiled; 17 agent-route quotes remain frozen and "
                    "family-wide replay remains open."
                )
                if rule_source_authorized
                else (
                    f"Only {active_compiled}/{REQUIRED_ACTIVE_PLAY_COUNT} ACTIVE plays "
                    "are compiled; 17 agent-route quotes remain frozen and "
                    "family-wide replay is open."
                )
            ),
            evidence=["play_catalog", "catalog_coverage"]
            + (["play_family_registry"] if family_registry else [])
            + (["family_settlement_report"] if family_replay else [])
            + (
                ["source_bundle_verification", "special_number_rule_evidence"]
                if rule_source_authorized
                else []
            ),
            blockers=d_blockers,
        ),
        "E": _gate(
            "verified" if e_ok else ("broken" if coverage_identity_ok else "missing"),
            "Every family has statistics, decision, freeze, settlement, and shadow-ledger evidence."
            if e_ok
            else "Per-family validation and shadow-ledger evidence cannot close before D.",
            evidence=["candidate_validation_report"]
            + (["family_validation_report"] if family_validation else []),
            blockers=[] if e_ok else ["per_family_validation_missing", "depends_on_D"],
        ),
        "F": _gate(
            "verified" if f_ok else ("partial" if route_ok else "broken"),
            "The canonical Temporal-Docker-LangGraph-Grok route and recovery are current."
            if f_ok
            else (
                "The canonical route is live, but current-task Continue-As-New/checkpoint "
                "recovery is unproven."
            )
            if route_ok
            else "The canonical durable route did not produce admissible current-task evidence.",
            evidence=["canonical_grok_route_result"]
            + (["durability_recovery_report"] if recovery else []),
            blockers=[] if f_ok else ["current_durability_recovery_not_verified"],
        ),
        "G": _gate(
            "verified" if restore_ok else "missing",
            "Lineage, observability, backup, and isolated restore bind to this foundation."
            if restore_ok
            else (
                "No isolated restore with non-null lineage IDs binds to the current "
                "input/catalog hashes."
            ),
            evidence=["current_foundation_restore_report"] if restore else [],
            blockers=[] if restore_ok else ["current_foundation_restore_missing"],
        ),
    }
    legacy_all_gates_verified = all(item["status"] == "verified" for item in gates.values())

    artifacts = {
        "input_material_manifest": _artifact(input_manifest_path),
        "canonical_golden_report": _artifact(canonical_path),
        "catalog_coverage": _artifact(coverage_path),
        "play_catalog": _artifact(catalog_path),
        "world_special_number": _artifact(world_path),
        "candidate_validation_report": _artifact(validation_path),
        "canonical_grok_route_result": _artifact(route_result_path),
    }
    for name, path in (
        ("play_family_registry", family_registry_path),
        ("family_settlement_report", family_replay_path),
        ("family_validation_report", family_validation_path),
        ("formal_ledger_report", formal_ledger_path),
        ("durability_recovery_report", recovery_path),
        ("current_foundation_restore_report", restore_path),
        ("source_bundle_verification", source_bundle_path),
        ("special_number_rule_evidence", special_rule_path),
    ):
        if path.is_file():
            artifacts[name] = _artifact(path)

    body: dict[str, Any] = {
        "schema_version": "xinao.foundation_gap_matrix.v1",
        "operation_id": operation_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "acceptance_profile": "B-leaning-C",
        "input_identity": {
            "draw_count": REQUIRED_DRAW_COUNT,
            "play_count": REQUIRED_PLAY_COUNT,
            "family_count": REQUIRED_FAMILY_COUNT,
            "dataset_sha256": dataset_hash,
            "baseline_sha256": baseline_hash,
            "catalog_content_hash": catalog_hash,
        },
        "catalog_coverage": {
            "source_total": source_total,
            "classified": classified,
            "active_required": active_required,
            "active_compiled": active_compiled,
            "active_not_compiled": active_not_compiled,
            "frozen_agent_route_quote_count": frozen_route_quotes,
            "unclassified_count": unclassified,
            "family_registry_identity_complete": family_registry_ok,
            "families": family_coverage,
        },
        "rule_authority": {
            "authorized_local_snapshot_bound": rule_source_authorized,
            "source_type": special_rule.get("source_type") if special_rule else None,
            "source_bundle_hash": (
                special_rule.get("source_bundle_hash") if special_rule else None
            ),
            "authority_basis": (special_rule.get("authority_basis") if special_rule else None),
            "semantic_status": (special_rule.get("semantic_status") if special_rule else []),
            "compiled_baseline_ids": (
                special_rule.get("compiled_baseline_ids") if special_rule else []
            ),
        },
        "gates": gates,
        "dependency_graph": {
            "A": [],
            "B": [],
            "C": ["A", "B", "D"],
            "D": ["A", "B"],
            "E": ["C", "D"],
            "F": [],
            "G": ["A", "B", "C", "D", "E", "F"],
        },
        "ready_frontier": [
            {
                "priority": 1,
                "gate": "D",
                "action": (
                    "compile_remaining_slices_from_explicit_or_versioned_convention"
                    if rule_source_authorized
                    else "bind_rule_authority_then_compile_and_replay_all_13_families"
                ),
            },
            {
                "priority": 2,
                "gate": "C/E",
                "action": "bind_family_decision_freeze_settlement_and_shadow_ledgers",
            },
            {
                "priority": 3,
                "gate": "G" if f_ok else "F/G",
                "action": (
                    "backup_and_restore_this_foundation_with_lineage"
                    if f_ok
                    else "prove_recovery_then_backup_and_restore_this_foundation"
                ),
            },
        ],
        "canonical_route": {
            "verified_live_call": route_ok,
            "workflow_id": route.get("workflow_id"),
            "run_id": route.get("run_id"),
            "model": route.get("result", {}).get("grok_fanin", {}).get("model"),
        },
        "legacy_diagnostic_only": True,
        "legacy_all_gates_verified": legacy_all_gates_verified,
        "foundation_closed": False,
        "formal_research_allowed": False,
        "result_status": "diagnostic",
        "artifacts": artifacts,
    }
    body["content_hash"] = canonical_sha256(body)
    if output_path is not None:
        _write_atomic(output_path, body)
    return body
