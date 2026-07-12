from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from .baseline import regular_set_exact_baseline, uniform_rtp_baseline
from .catalog import build_conformance_events, build_typed_rule_catalog, conformance_ledger_bytes
from .domain import (
    build_regular_semantics,
    build_regular_trial_records,
    build_rule,
    build_special_semantics,
    build_trial_records,
    default_candidates,
    ledger_bytes,
    p2_decision_trace_bytes,
    p2_default_candidates,
    p2_rule_claims,
    projection_ledger_bytes,
    summarize_candidates,
)
from .inputs import (
    InputLayout,
    assert_snapshot_unchanged,
    audit_inputs,
    audit_inputs_p2,
    build_snapshot_manifest,
    canonical_json_bytes,
    load_raw_draws,
    sha256_file,
    write_json_atomic,
)
from .models import (
    CostModel,
    JudgeGateResult,
    P2EvidencePin,
    P3AcceptancePin,
    P4JudgeGateResult,
    P4Protocol,
    P5EvidenceRecord,
    P5Protocol,
    ProjectionTrialRecord,
    ResearchProtocol,
    SeriesSpec,
)
from .research import (
    build_judge_gate,
    build_research_protocol,
    build_tombstones,
    load_p2_evidence_pin,
    tombstone_ledger_bytes,
    validate_research_protocol,
    verify_research_trial_ledger,
    write_research_trial_ledger,
)
from .semantics import (
    EXPECTED_CANONICAL_TERM_COUNTS,
    QUERY_TERMS,
    RULE_CLAIM_SUBJECTS,
    build_p5_acceptance_pin,
    build_p5_judge,
    build_p5_protocol,
    build_p5_tombstones,
    build_semantics_artifacts,
    build_source_inventory,
    evidence_ledger_bytes,
    p5_tombstone_ledger_bytes,
    query_vocabulary_artifact,
    scan_packet,
    source_scan_contract_artifact,
    validate_p5_protocol,
    verify_selector,
)
from .structure import (
    build_contamination_pin_artifact,
    build_null_family_artifact,
    build_p3_acceptance_pin,
    build_p4_judge,
    build_p4_protocol,
    build_p4_tombstones,
    build_test_results,
    contamination_evidence,
    contamination_ledger_bytes,
    draw_array,
    observed_score_detail,
    p4_tombstone_ledger_bytes,
    simulate_shared_null,
    structure_test_ledger_bytes,
    validate_p4_protocol,
)

CANONICAL_INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")
CANONICAL_EVIDENCE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _write_ledger(path: Path, payload: bytes) -> str:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(payload).hexdigest()


def _artifact_hashes(run_dir: Path, names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "relative_path": name,
            "size_bytes": (run_dir / name).stat().st_size,
            "sha256": sha256_file(run_dir / name),
        }
        for name in names
    ]


def _source_fingerprint() -> str:
    project_root = Path(__file__).resolve().parents[2]
    paths = [
        project_root / "pyproject.toml",
        project_root / "uv.lock",
        project_root / "README.md",
        project_root / "docs" / "P1_SPEC.md",
        project_root / "docs" / "P2_SPEC.md",
        project_root / "docs" / "P3_SPEC.md",
        project_root / "docs" / "P4_SPEC.md",
        project_root / "docs" / "P5_SPEC.md",
        project_root / "rules" / "p2_rule_bundle_v1.json",
    ]
    paths.extend(sorted((project_root / "src" / "xinao_market_lab").glob("*.py")))
    rows = [
        {
            "relative_path": path.relative_to(project_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]
    return hashlib.sha256(canonical_json_bytes(rows)).hexdigest()


def _is_sha256_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def run_p1(*, input_root: Path, evidence_root: Path, run_name: str) -> dict[str, Any]:
    layout = InputLayout.from_root(input_root)
    evidence_root = evidence_root.resolve()
    run_dir = evidence_root / run_name
    if _is_under(run_dir, layout.root):
        raise ValueError("evidence output must not be inside the input tree")
    if layout.root == CANONICAL_INPUT_ROOT.resolve() and not _is_under(
        run_dir, CANONICAL_EVIDENCE_ROOT.resolve()
    ):
        raise ValueError(f"canonical input evidence must stay under {CANONICAL_EVIDENCE_ROOT}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)

    snapshot_before = build_snapshot_manifest(layout)
    write_json_atomic(run_dir / "input_snapshot.json", snapshot_before)
    draws_list, quote, source_audit = audit_inputs(layout)
    draws = tuple(draws_list)
    write_json_atomic(run_dir / "source_audit.json", source_audit)

    series = SeriesSpec()
    cost = CostModel()
    rule = build_rule(quote)
    candidates = default_candidates()
    object_pin = {
        "schema_version": 1,
        "series": series.model_dump(mode="json"),
        "quote": quote.model_dump(mode="json"),
        "rule": rule.model_dump(mode="json"),
        "cost": cost.model_dump(mode="json"),
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "hard_boundaries": [
            "seventh source number is special",
            "exact-number settlement has no push branch",
            "displayed payout is treated as inclusive return only for this mechanics check",
            "single 2026-05-12 quote is not contemporaneous with historical draws",
            "no output may be interpreted as betting advice or a real-money action",
        ],
    }
    write_json_atomic(run_dir / "object_pin.json", object_pin)

    run_key, records = build_trial_records(
        draws=draws,
        candidates=candidates,
        quote=quote,
        rule=rule,
        cost=cost,
        snapshot_id=snapshot_before["snapshot_id"],
    )
    ledger_payload = ledger_bytes(records)
    ledger_sha256 = _write_ledger(run_dir / "trials.jsonl", ledger_payload)
    candidate_summary = summarize_candidates(records, candidates, quote)
    write_json_atomic(run_dir / "candidate_summary.json", candidate_summary)
    baseline = uniform_rtp_baseline(draws, quote)
    write_json_atomic(run_dir / "uniform_rtp_baseline.json", baseline)

    snapshot_after = build_snapshot_manifest(layout)
    assert_snapshot_unchanged(snapshot_before, snapshot_after)
    checks = {
        "schema_version": 1,
        "input_snapshot_unchanged": True,
        "bundle_manifest_hashes_match": not source_audit["bundle_manifest_mismatches"],
        "history_representations_match": source_audit["history"]["tsv_json_mismatch_count"] == 0,
        "quarantined_expect_year_mismatches": source_audit["history"]["expect_year_mismatches"],
        "quarantined_duplicate_outcome_repetitions": source_audit["history"][
            "quarantined_duplicate_outcome_repetitions"
        ],
        "candidate_count": len(candidates),
        "candidate_count_within_limit": len(candidates) <= 4,
        "ledger_record_count": len(records),
        "ledger_sha256": ledger_sha256,
        "always_no_bet_net_zero": next(
            summary["mechanics_net_return_at_non_contemporaneous_price"]
            for summary in candidate_summary["summaries"]
            if summary["candidate"]["candidate_id"] == "always_no_bet"
        )
        == "0",
        "completion_claim": "mechanics_verified_no_edge_claim",
    }
    if not all(
        checks[name]
        for name in (
            "input_snapshot_unchanged",
            "bundle_manifest_hashes_match",
            "history_representations_match",
            "candidate_count_within_limit",
            "always_no_bet_net_zero",
        )
    ):
        raise RuntimeError(f"P1 acceptance check failed: {checks}")
    write_json_atomic(run_dir / "checks.json", checks)

    artifact_names = (
        "input_snapshot.json",
        "source_audit.json",
        "object_pin.json",
        "trials.jsonl",
        "candidate_summary.json",
        "uniform_rtp_baseline.json",
        "checks.json",
    )
    manifest = {
        "schema_version": 1,
        "status": "verified_mechanics_only",
        "run_name": run_name,
        "run_key": run_key,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "input_snapshot_id": snapshot_before["snapshot_id"],
        "source_fingerprint": _source_fingerprint(),
        "evaluation_kind": "mechanics_replay_non_contemporaneous_price",
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("xinao-market-lab", "polars", "pydantic", "scipy")
        },
        "artifacts": _artifact_hashes(run_dir, artifact_names),
        "claim_boundary": (
            "This run verifies read-only ingestion, settlement mechanics, cost accounting, deterministic "
            "ledger generation and a descriptive uniform/RTP baseline. It does not verify source truth, "
            "historical quote availability, predictive edge, betting advice or real-money execution."
        ),
    }
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    return {
        "status": manifest["status"],
        "run_dir": str(run_dir),
        "run_key": run_key,
        "snapshot_id": snapshot_before["snapshot_id"],
        "ledger_sha256": ledger_sha256,
        "draw_count": len(draws),
        "candidate_count": len(candidates),
    }


def run_p3_research_protocol_judge(
    *,
    input_root: Path,
    evidence_root: Path,
    run_name: str,
    p2_evidence_run: Path,
) -> dict[str, Any]:
    layout = InputLayout.from_root(input_root)
    evidence_root = evidence_root.resolve()
    run_dir = evidence_root / run_name
    if _is_under(run_dir, layout.root):
        raise ValueError("evidence output must not be inside the input tree")
    if layout.root == CANONICAL_INPUT_ROOT.resolve() and not _is_under(
        run_dir, CANONICAL_EVIDENCE_ROOT.resolve()
    ):
        raise ValueError(f"canonical input evidence must stay under {CANONICAL_EVIDENCE_ROOT}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)

    snapshot_before = build_snapshot_manifest(layout)
    write_json_atomic(run_dir / "input_snapshot.json", snapshot_before)
    draws, _quote, source_audit, lineage, source_catalog = audit_inputs_p2(layout)
    write_json_atomic(run_dir / "source_audit.json", source_audit)

    project_root = Path(__file__).resolve().parents[2]
    typed_rule_bundle, compiled_rules, classifications = build_typed_rule_catalog(
        layout=layout,
        rule_bundle_path=project_root / "rules" / "p2_rule_bundle_v1.json",
        snapshot_id=snapshot_before["snapshot_id"],
    )
    rule_surface_pin = {
        "schema_version": 1,
        "bundle_id": typed_rule_bundle["bundle_id"],
        "source_snapshot_id": typed_rule_bundle["source_snapshot_id"],
        "source_definition": typed_rule_bundle["source_definition"],
        "verified_source_hashes": typed_rule_bundle["verified_source_hashes"],
        "rules": [
            {
                "rule_key": rule.definition.rule_key,
                "rule_hash": rule.rule_hash,
                "projection": rule.definition.projection,
                "position": rule.definition.position,
                "modal_odds": rule.definition.expected_modal_odds,
                "price_status": rule.definition.price_status,
            }
            for rule in compiled_rules
        ],
        "classification": {
            "source_row_count": len(classifications),
            "implemented_reference_rows": sum(item.status == "IMPLEMENTED" for item in classifications),
            "unresolved_rows": sum(item.status == "UNRESOLVED" for item in classifications),
        },
    }
    write_json_atomic(run_dir / "rule_surface_pin.json", rule_surface_pin)

    p2_evidence = load_p2_evidence_pin(p2_evidence_run, snapshot_before["snapshot_id"])
    write_json_atomic(run_dir / "p2_acceptance_pin.json", p2_evidence.model_dump(mode="json"))
    cost = CostModel()
    protocol = build_research_protocol(
        draws=draws,
        compiled_rules=compiled_rules,
        cost=cost,
        snapshot_id=snapshot_before["snapshot_id"],
        p2_evidence=p2_evidence,
    )
    write_json_atomic(run_dir / "research_protocol.json", protocol.model_dump(mode="json"))
    protocol_artifact_sha256 = sha256_file(run_dir / "research_protocol.json")
    protocol_readback = ResearchProtocol.model_validate_json(
        (run_dir / "research_protocol.json").read_text(encoding="utf-8"), strict=True
    )
    validate_research_protocol(
        protocol_readback,
        draws=draws,
        compiled_rules=compiled_rules,
    )

    ledger_result = write_research_trial_ledger(
        run_dir / "trials.jsonl",
        protocol=protocol_readback,
        protocol_artifact_sha256=protocol_artifact_sha256,
        draws=draws,
        lineage=lineage,
        compiled_rules=compiled_rules,
    )
    write_json_atomic(run_dir / "cell_summary.json", ledger_result)
    verified_ledger = verify_research_trial_ledger(
        run_dir / "trials.jsonl",
        protocol=protocol_readback,
        protocol_artifact_sha256=protocol_artifact_sha256,
        draws=draws,
        lineage=lineage,
        compiled_rules=compiled_rules,
    )

    candidates = default_candidates()
    changed_last = draws[-1]
    occupied = {*changed_last.regular_numbers, changed_last.special}
    replacement = next(number for number in range(1, 50) if number not in occupied)
    mutated_last = changed_last.model_copy(
        update={"regular_numbers": (replacement, *changed_last.regular_numbers[1:])}
    )
    prefix_limit = len(draws) - 1
    future_suffix_decisions_unchanged = p2_decision_trace_bytes(
        draws, candidates, through_index=prefix_limit
    ) == p2_decision_trace_bytes((*draws[:-1], mutated_last), candidates, through_index=prefix_limit)

    tombstones = build_tombstones(protocol_readback)
    tombstones_payload = tombstone_ledger_bytes(tombstones)
    tombstones_sha256 = _write_ledger(run_dir / "tombstones.jsonl", tombstones_payload)
    judge = build_judge_gate(
        protocol=protocol_readback,
        ledger_result=ledger_result,
        verified_ledger=verified_ledger,
        cell_summary=ledger_result,
        future_suffix_decisions_unchanged=future_suffix_decisions_unchanged,
    )
    write_json_atomic(run_dir / "judge_gate.json", judge.model_dump(mode="json"))

    snapshot_after = build_snapshot_manifest(layout)
    assert_snapshot_unchanged(snapshot_before, snapshot_after)
    checks = {
        "schema_version": 1,
        "input_snapshot_unchanged": True,
        "input_snapshot_id": snapshot_before["snapshot_id"],
        "p2_acceptance_pin_verified": True,
        "protocol_frozen_before_trials": True,
        "protocol_artifact_sha256": protocol_artifact_sha256,
        "protocol_hash": protocol.protocol_hash,
        "experiment_id": protocol.experiment_id,
        "candidate_count": len(protocol.spec.candidates),
        "typed_rule_count": len(protocol.spec.rules),
        "declared_cell_budget": protocol.spec.declared_cell_budget,
        "completed_cells": ledger_result["completed_cells"],
        "declared_trial_row_budget": protocol.spec.declared_trial_row_budget,
        "trial_rows": ledger_result["trial_rows"],
        "chronological_fold_count": len(protocol.spec.folds),
        "chronological_fold_sizes": [
            fold.end_index_exclusive - fold.start_index for fold in protocol.spec.folds
        ],
        "future_suffix_decisions_unchanged": future_suffix_decisions_unchanged,
        "trial_ledger_sha256": ledger_result["ledger_sha256"],
        "trial_chain_tip": ledger_result["chain_tip"],
        "trial_ledger_replayed_exactly": ledger_result["ledger_sha256"] == verified_ledger["ledger_sha256"]
        and ledger_result["chain_tip"] == verified_ledger["chain_tip"]
        and ledger_result["trial_rows"] == verified_ledger["trial_rows"],
        "tombstone_count": len(tombstones),
        "tombstones_sha256": tombstones_sha256,
        "mechanics_status": judge.mechanics_status,
        "economic_claim_status": judge.economic_claim_status,
        "all_source_rows_unverified": source_audit["lineage_v2"]["source_verify_true"] == 0,
        "catalog_play_rows": source_catalog["sources"]["play_structure"]["row_count"],
        "catalog_odds_rows": source_catalog["sources"]["odds_candidates"]["row_count"],
        "forbidden_claim_flags_all_false": all(
            not value
            for value in (
                judge.ranking_permitted,
                judge.candidate_selection_permitted,
                judge.recommendation_permitted,
                judge.real_money_use_permitted,
                judge.source_truth_verified,
                judge.historical_price_availability_verified,
            )
        ),
    }
    required_true = (
        "input_snapshot_unchanged",
        "p2_acceptance_pin_verified",
        "protocol_frozen_before_trials",
        "future_suffix_decisions_unchanged",
        "trial_ledger_replayed_exactly",
        "all_source_rows_unverified",
        "forbidden_claim_flags_all_false",
    )
    if not all(checks[name] for name in required_true):
        raise RuntimeError(f"P3 protocol/Judge acceptance failed: {checks}")
    if (
        checks["candidate_count"] != 4
        or checks["typed_rule_count"] != 8
        or checks["declared_cell_budget"] != 32
        or checks["completed_cells"] != 32
        or checks["declared_trial_row_budget"] != 38_528
        or checks["trial_rows"] != 38_528
        or checks["chronological_fold_sizes"] != [301, 301, 301, 301]
        or checks["tombstone_count"] != 3
        or checks["mechanics_status"] != "MECHANICS_ACCEPTED"
        or checks["economic_claim_status"] != "ECONOMIC_CLAIM_BLOCKED"
        or checks["catalog_play_rows"] != 136
        or checks["catalog_odds_rows"] != 4_043
    ):
        raise RuntimeError(f"P3 frozen scope mismatch: {checks}")
    write_json_atomic(run_dir / "checks.json", checks)

    artifact_names = (
        "input_snapshot.json",
        "source_audit.json",
        "rule_surface_pin.json",
        "p2_acceptance_pin.json",
        "research_protocol.json",
        "trials.jsonl",
        "cell_summary.json",
        "tombstones.jsonl",
        "judge_gate.json",
        "checks.json",
    )
    manifest = {
        "schema_version": 1,
        "status": "verified_research_protocol_mechanics_economic_claims_blocked",
        "resolution_key": "p3-research-protocol-judge-gate-v1",
        "run_name": run_name,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": protocol.experiment_id,
        "protocol_hash": protocol.protocol_hash,
        "input_snapshot_id": snapshot_before["snapshot_id"],
        "source_fingerprint": _source_fingerprint(),
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("xinao-market-lab", "polars", "pydantic", "scipy")
        },
        "artifacts": _artifact_hashes(run_dir, artifact_names),
        "claims": {
            "mechanics_protocol_verified": True,
            "operator_rule_truth_verified": False,
            "payout_basis_verified": False,
            "historical_price_availability_verified": False,
            "predictive_ranking_permitted": False,
            "recommendation_permitted": False,
            "real_money_use_permitted": False,
            "whole_project_complete": False,
        },
        "claim_boundary": (
            "This run verifies a pre-frozen finite research protocol, complete deterministic replay, "
            "hash-linked trial evidence, chronological no-lookahead, and Judge mechanics gates. The "
            "Judge blocks every economic, edge, ranking, recommendation, source-truth, forward-price, "
            "real-money, and whole-project claim because the required evidence is absent."
        ),
    }
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    return {
        "status": manifest["status"],
        "run_dir": str(run_dir),
        "experiment_id": protocol.experiment_id,
        "protocol_hash": protocol.protocol_hash,
        "input_snapshot_id": snapshot_before["snapshot_id"],
        "candidate_count": len(protocol.spec.candidates),
        "typed_rule_count": len(protocol.spec.rules),
        "cell_count": protocol.spec.declared_cell_budget,
        "trial_rows": ledger_result["trial_rows"],
        "trial_ledger_sha256": ledger_result["ledger_sha256"],
        "trial_chain_tip": ledger_result["chain_tip"],
        "mechanics_status": judge.mechanics_status,
        "economic_claim_status": judge.economic_claim_status,
    }


def verify_p3_run(*, input_root: Path, run_dir: Path) -> dict[str, Any]:
    layout = InputLayout.from_root(input_root)
    run_dir = run_dir.resolve()
    if _is_under(run_dir, layout.root):
        raise ValueError("P3 evidence cannot be inside the input tree")
    required = (
        "input_snapshot.json",
        "source_audit.json",
        "rule_surface_pin.json",
        "p2_acceptance_pin.json",
        "research_protocol.json",
        "trials.jsonl",
        "cell_summary.json",
        "tombstones.jsonl",
        "judge_gate.json",
        "checks.json",
        "run_manifest.json",
    )
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"P3 evidence is incomplete: {missing}")

    snapshot_before = build_snapshot_manifest(layout)
    pinned_snapshot = json.loads((run_dir / "input_snapshot.json").read_text(encoding="utf-8"))
    if pinned_snapshot != snapshot_before:
        raise ValueError("P3 input snapshot artifact does not match the current read-only input")

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "verified_research_protocol_mechanics_economic_claims_blocked":
        raise ValueError("P3 manifest does not have the accepted protocol/Judge status")
    listed = {
        str(item["relative_path"]): (int(item["size_bytes"]), str(item["sha256"]))
        for item in manifest.get("artifacts", [])
    }
    for name in required[:-1]:
        expected = listed.get(name)
        if expected is None:
            raise ValueError(f"P3 manifest does not list required artifact: {name}")
        path = run_dir / name
        if (path.stat().st_size, sha256_file(path)) != expected:
            raise ValueError(f"P3 manifest artifact mismatch: {name}")

    draws, _quote, _source_audit, lineage, _source_catalog = audit_inputs_p2(layout)
    project_root = Path(__file__).resolve().parents[2]
    _bundle, compiled_rules, _classifications = build_typed_rule_catalog(
        layout=layout,
        rule_bundle_path=project_root / "rules" / "p2_rule_bundle_v1.json",
        snapshot_id=snapshot_before["snapshot_id"],
    )
    p2_pin = P2EvidencePin.model_validate_json(
        (run_dir / "p2_acceptance_pin.json").read_text(encoding="utf-8"), strict=True
    )
    live_p2_pin = load_p2_evidence_pin(Path(p2_pin.run_directory), snapshot_before["snapshot_id"])
    if p2_pin != live_p2_pin:
        raise ValueError("P3 P2 evidence pin no longer matches its immutable source run")

    protocol_path = run_dir / "research_protocol.json"
    protocol_artifact_sha256 = sha256_file(protocol_path)
    protocol = ResearchProtocol.model_validate_json(protocol_path.read_text(encoding="utf-8"), strict=True)
    validate_research_protocol(protocol, draws=draws, compiled_rules=compiled_rules)
    if protocol.spec.p2_evidence != p2_pin:
        raise ValueError("frozen P3 protocol does not contain the accepted P2 evidence pin")
    verified_ledger = verify_research_trial_ledger(
        run_dir / "trials.jsonl",
        protocol=protocol,
        protocol_artifact_sha256=protocol_artifact_sha256,
        draws=draws,
        lineage=lineage,
        compiled_rules=compiled_rules,
    )

    cell_summary = json.loads((run_dir / "cell_summary.json").read_text(encoding="utf-8"))
    expected_cells = {
        (candidate.candidate_id, rule.definition.rule_key)
        for candidate in protocol.spec.candidates
        for rule in compiled_rules
    }
    actual_cells = {
        (str(summary["candidate_id"]), str(summary["rule_key"]))
        for summary in cell_summary.get("summaries", [])
    }
    if actual_cells != expected_cells or len(cell_summary.get("summaries", [])) != 32:
        raise ValueError("P3 cell summary does not equal the frozen 4 x 8 cartesian surface")
    if any(key in cell_summary for key in ("winner", "rank", "top", "best")):
        raise ValueError("P3 cell summary exposes a forbidden ranking field")

    candidates = default_candidates()
    changed_last = draws[-1]
    occupied = {*changed_last.regular_numbers, changed_last.special}
    replacement = next(number for number in range(1, 50) if number not in occupied)
    mutated_last = changed_last.model_copy(
        update={"regular_numbers": (replacement, *changed_last.regular_numbers[1:])}
    )
    prefix_limit = len(draws) - 1
    future_suffix_decisions_unchanged = p2_decision_trace_bytes(
        draws, candidates, through_index=prefix_limit
    ) == p2_decision_trace_bytes((*draws[:-1], mutated_last), candidates, through_index=prefix_limit)
    expected_judge = build_judge_gate(
        protocol=protocol,
        ledger_result=cell_summary,
        verified_ledger=verified_ledger,
        cell_summary=cell_summary,
        future_suffix_decisions_unchanged=future_suffix_decisions_unchanged,
    )
    actual_judge = JudgeGateResult.model_validate_json(
        (run_dir / "judge_gate.json").read_text(encoding="utf-8"), strict=True
    )
    if actual_judge != expected_judge:
        raise ValueError("P3 Judge artifact does not derive from the frozen protocol and replayed ledger")

    expected_tombstones = tombstone_ledger_bytes(build_tombstones(protocol))
    if (run_dir / "tombstones.jsonl").read_bytes() != expected_tombstones:
        raise ValueError("P3 tombstones are not the deterministic evidence-bounded set")
    claims = manifest.get("claims", {})
    required_false = (
        "operator_rule_truth_verified",
        "payout_basis_verified",
        "historical_price_availability_verified",
        "predictive_ranking_permitted",
        "recommendation_permitted",
        "real_money_use_permitted",
        "whole_project_complete",
    )
    if any(claims.get(name) is not False for name in required_false):
        raise ValueError("P3 manifest enables a forbidden economic or completion claim")
    if claims.get("mechanics_protocol_verified") is not True:
        raise ValueError("P3 manifest does not record the bounded mechanics result")

    snapshot_after = build_snapshot_manifest(layout)
    assert_snapshot_unchanged(snapshot_before, snapshot_after)
    return {
        "status": "verified",
        "run_dir": str(run_dir),
        "experiment_id": protocol.experiment_id,
        "protocol_hash": protocol.protocol_hash,
        "input_snapshot_id": snapshot_before["snapshot_id"],
        "cell_count": len(actual_cells),
        "trial_rows": verified_ledger["trial_rows"],
        "trial_ledger_sha256": verified_ledger["ledger_sha256"],
        "trial_chain_tip": verified_ledger["chain_tip"],
        "mechanics_status": actual_judge.mechanics_status,
        "economic_claim_status": actual_judge.economic_claim_status,
        "tombstone_count": len(expected_tombstones.splitlines()),
    }


P4_ARTIFACT_NAMES = (
    "input_snapshot.json",
    "p3_acceptance_pin.json",
    "p4_protocol.json",
    "null_family.json",
    "contamination_pin.json",
    "contamination_audit.jsonl",
    "contamination_summary.json",
    "null_statistics.jsonl",
    "null_summary.json",
    "structure_tests.jsonl",
    "tombstones.jsonl",
    "judge_gate_p4.json",
    "checks.json",
)


def _p4_judge_checks(
    *,
    protocol: P4Protocol,
    contamination_summary: dict[str, Any],
    null_summary: dict[str, Any],
    test_results: tuple[Any, ...],
    all_source_rows_unverified: bool,
) -> dict[str, bool]:
    stream_hash = str(null_summary["null_score_stream_sha256"])
    return {
        "protocol_hash_verified": True,
        "protocol_frozen_before_simulation": True,
        "p3_acceptance_verified": True,
        "contamination_pin_matched": (
            contamination_summary["gate_status"] == "CONTAMINATION_PIN_MATCHED"
            and contamination_summary["residual_alias_count"] == 0
        ),
        "contamination_gate_outside_holm": True,
        "raw_collision_descriptive_only": True,
        "family_exact_m5": tuple(record.test_id for record in test_results)
        == tuple(test.test_id for test in protocol.spec.family),
        "shared_joint_null_stream": all(
            record.null_score_stream_sha256 == stream_hash for record in test_results
        ),
        "pcg64_budget_exhausted": null_summary["simulation_count"] == protocol.spec.n_mc,
        "plus_one_p_values": all(
            record.raw_p_numerator == record.exceedance_count + 1
            and record.raw_p_denominator == protocol.spec.n_mc + 1
            for record in test_results
        ),
        "holm_controls_only_five": len(test_results) == protocol.spec.family_size == 5,
        "all_source_rows_unverified": all_source_rows_unverified,
        "forbidden_claim_flags_all_false": True,
    }


def _p4_checks(
    *,
    protocol: P4Protocol,
    protocol_artifact_sha256: str,
    p3_pin: P3AcceptancePin,
    contamination_payload_sha256: str,
    contamination_summary: dict[str, Any],
    null_ledger_sha256: str,
    null_summary: dict[str, Any],
    structure_ledger_sha256: str,
    test_results: tuple[Any, ...],
    tombstone_sha256: str,
    judge: P4JudgeGateResult,
    judge_checks: dict[str, bool],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "input_snapshot_unchanged": True,
        "input_snapshot_id": protocol.spec.input_snapshot_id,
        "p3_acceptance_pin_verified": True,
        "p3_protocol_hash": p3_pin.protocol_hash,
        "p3_trial_ledger_sha256": p3_pin.trial_ledger_sha256,
        "protocol_frozen_before_simulation": True,
        "protocol_artifact_sha256": protocol_artifact_sha256,
        "protocol_hash": protocol.protocol_hash,
        "experiment_id": protocol.experiment_id,
        "contamination_gate_status": contamination_summary["gate_status"],
        "contamination_audit_sha256": contamination_payload_sha256,
        "raw_source_draw_count": contamination_summary["raw_source_draw_count"],
        "canonical_draw_count": contamination_summary["canonical_draw_count"],
        "pinned_quarantine_count": contamination_summary["pinned_quarantine_count"],
        "residual_alias_count": contamination_summary["residual_alias_count"],
        "raw_collision_pair_counts": {
            row["identity"]: row["observed_pair_collisions"]
            for row in contamination_summary["collision_diagnostics"]
        },
        "family_size": protocol.spec.family_size,
        "family_order": [test.test_id for test in protocol.spec.family],
        "collision_test_in_family": False,
        "alias_gate_in_family": False,
        "rng_bit_generator": protocol.spec.rng_bit_generator,
        "rng_seed": protocol.spec.rng_seed,
        "numpy_version": protocol.spec.numpy_version,
        "sampler_algorithm_id": protocol.spec.sampler_algorithm_id,
        "n_mc": protocol.spec.n_mc,
        "batch_size": protocol.spec.batch_size,
        "fold_sizes": list(protocol.spec.fold_sizes),
        "null_statistics_sha256": null_ledger_sha256,
        "null_statistics_chain_tip": null_summary["null_score_chain_tip"],
        "early_stream_sentinel_event_hashes": null_summary["early_stream_sentinel_event_hashes"],
        "structure_tests_sha256": structure_ledger_sha256,
        "rejected_tests": list(judge.rejected_tests),
        "structure_status": judge.structure_status,
        "economic_claim_status": judge.economic_claim_status,
        "tombstone_count": 4,
        "tombstones_sha256": tombstone_sha256,
        "judge_checks": judge_checks,
        "all_judge_checks_pass": all(judge_checks.values()),
        "forbidden_claim_flags_all_false": all(
            not value
            for value in (
                judge.ranking_permitted,
                judge.recommendation_permitted,
                judge.real_money_use_permitted,
                judge.source_truth_verified,
                judge.historical_price_availability_verified,
                judge.generator_mechanism_claim_permitted,
            )
        ),
        "test_decisions": {record.test_id: record.decision for record in test_results},
    }


def run_p4_exact_null_contamination_structure(
    *,
    input_root: Path,
    evidence_root: Path,
    run_name: str,
    p3_evidence_run: Path,
) -> dict[str, Any]:
    layout = InputLayout.from_root(input_root)
    evidence_root = evidence_root.resolve()
    run_dir = evidence_root / run_name
    if _is_under(run_dir, layout.root):
        raise ValueError("evidence output must not be inside the input tree")
    if layout.root == CANONICAL_INPUT_ROOT.resolve() and not _is_under(
        run_dir, CANONICAL_EVIDENCE_ROOT.resolve()
    ):
        raise ValueError(f"canonical input evidence must stay under {CANONICAL_EVIDENCE_ROOT}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)

    snapshot_before = build_snapshot_manifest(layout)
    write_json_atomic(run_dir / "input_snapshot.json", snapshot_before)
    canonical_draws, _quote, source_audit, lineage, _catalog = audit_inputs_p2(layout)
    raw_draws = load_raw_draws(layout)

    p3_verification = verify_p3_run(input_root=input_root, run_dir=p3_evidence_run)
    p3_pin = build_p3_acceptance_pin(p3_evidence_run, p3_verification)
    if p3_pin.input_snapshot_id != snapshot_before["snapshot_id"]:
        raise ValueError("P4 input snapshot does not match the accepted P3 run")
    write_json_atomic(run_dir / "p3_acceptance_pin.json", p3_pin.model_dump(mode="json"))

    protocol = build_p4_protocol(snapshot_id=snapshot_before["snapshot_id"], p3_evidence=p3_pin)
    write_json_atomic(run_dir / "p4_protocol.json", protocol.model_dump(mode="json"))
    protocol_artifact_sha256 = sha256_file(run_dir / "p4_protocol.json")
    protocol_readback = P4Protocol.model_validate_json(
        (run_dir / "p4_protocol.json").read_text(encoding="utf-8"), strict=True
    )
    validate_p4_protocol(
        protocol_readback,
        snapshot_id=snapshot_before["snapshot_id"],
        p3_evidence=p3_pin,
    )

    null_family = build_null_family_artifact(protocol_readback, protocol_artifact_sha256)
    contamination_pin = build_contamination_pin_artifact(protocol_readback)
    write_json_atomic(run_dir / "null_family.json", null_family)
    write_json_atomic(run_dir / "contamination_pin.json", contamination_pin)
    if _read_json_file(run_dir / "null_family.json") != null_family:
        raise ValueError("P4 null family readback mismatch before simulation")
    if _read_json_file(run_dir / "contamination_pin.json") != contamination_pin:
        raise ValueError("P4 contamination pin readback mismatch before simulation")

    contamination_records, contamination_summary = contamination_evidence(
        raw_draws=raw_draws,
        canonical_draws=canonical_draws,
        lineage=lineage,
    )
    contamination_payload = contamination_ledger_bytes(contamination_records)
    contamination_payload_sha256 = _write_ledger(run_dir / "contamination_audit.jsonl", contamination_payload)
    contamination_summary = {
        **contamination_summary,
        "audit_ledger_sha256": contamination_payload_sha256,
    }
    write_json_atomic(run_dir / "contamination_summary.json", contamination_summary)

    values = draw_array(canonical_draws)
    observed_detail = observed_score_detail(values, fold_sizes=protocol_readback.spec.fold_sizes)
    observed_scores = np.asarray(
        [
            observed_detail[test_id]
            for test_id in ("T_special", "T_pos_max", "T_regular_incl", "T_lag1", "T_fold")
        ],
        dtype=np.int64,
    )
    simulation = simulate_shared_null(
        observed_scores=observed_scores,
        draw_count=len(canonical_draws),
        fold_sizes=protocol_readback.spec.fold_sizes,
        seed=protocol_readback.spec.rng_seed,
        n_mc=protocol_readback.spec.n_mc,
        batch_size=protocol_readback.spec.batch_size,
    )
    null_ledger_bytes = simulation.pop("_ledger_bytes")
    if not isinstance(null_ledger_bytes, bytes):
        raise TypeError("P4 null simulation did not return a byte ledger")
    null_ledger_sha256 = _write_ledger(run_dir / "null_statistics.jsonl", null_ledger_bytes)
    if null_ledger_sha256 != simulation["null_score_stream_sha256"]:
        raise RuntimeError("P4 null score ledger hash mismatch")
    null_summary = {
        **simulation,
        "experiment_id": protocol_readback.experiment_id,
        "protocol_hash": protocol_readback.protocol_hash,
        "protocol_artifact_sha256": protocol_artifact_sha256,
        "observed_detail": observed_detail,
        "rng": null_family["rng"],
        "sampler": null_family["sampler"],
    }
    write_json_atomic(run_dir / "null_summary.json", null_summary)

    test_results = build_test_results(
        protocol=protocol_readback,
        protocol_artifact_sha256=protocol_artifact_sha256,
        null_summary=null_summary,
    )
    structure_payload = structure_test_ledger_bytes(test_results)
    structure_ledger_sha256 = _write_ledger(run_dir / "structure_tests.jsonl", structure_payload)
    tombstones = build_p4_tombstones(protocol_readback)
    tombstone_payload = p4_tombstone_ledger_bytes(tombstones)
    tombstone_sha256 = _write_ledger(run_dir / "tombstones.jsonl", tombstone_payload)

    judge_checks = _p4_judge_checks(
        protocol=protocol_readback,
        contamination_summary=contamination_summary,
        null_summary=null_summary,
        test_results=test_results,
        all_source_rows_unverified=source_audit["lineage_v2"]["source_verify_true"] == 0,
    )
    judge = build_p4_judge(
        protocol=protocol_readback,
        protocol_artifact_sha256=protocol_artifact_sha256,
        test_results=test_results,
        checks=judge_checks,
    )
    write_json_atomic(run_dir / "judge_gate_p4.json", judge.model_dump(mode="json"))
    checks = _p4_checks(
        protocol=protocol_readback,
        protocol_artifact_sha256=protocol_artifact_sha256,
        p3_pin=p3_pin,
        contamination_payload_sha256=contamination_payload_sha256,
        contamination_summary=contamination_summary,
        null_ledger_sha256=null_ledger_sha256,
        null_summary=null_summary,
        structure_ledger_sha256=structure_ledger_sha256,
        test_results=test_results,
        tombstone_sha256=tombstone_sha256,
        judge=judge,
        judge_checks=judge_checks,
    )
    required_true = (
        "input_snapshot_unchanged",
        "p3_acceptance_pin_verified",
        "protocol_frozen_before_simulation",
        "all_judge_checks_pass",
        "forbidden_claim_flags_all_false",
    )
    if not all(checks[name] for name in required_true):
        raise RuntimeError(f"P4 acceptance check failed: {checks}")
    if (
        checks["raw_source_draw_count"] != 1_209
        or checks["canonical_draw_count"] != 1_204
        or checks["pinned_quarantine_count"] != 5
        or checks["residual_alias_count"] != 0
        or set(checks["raw_collision_pair_counts"].values()) != {5}
        or checks["family_size"] != 5
        or checks["n_mc"] != 19_999
        or checks["tombstone_count"] != 4
        or checks["economic_claim_status"] != "ECONOMIC_CLAIM_BLOCKED"
    ):
        raise RuntimeError(f"P4 frozen scope mismatch: {checks}")
    write_json_atomic(run_dir / "checks.json", checks)

    snapshot_after = build_snapshot_manifest(layout)
    assert_snapshot_unchanged(snapshot_before, snapshot_after)
    manifest = {
        "schema_version": 1,
        "status": "verified_exact_null_contamination_structure_economic_claims_blocked",
        "resolution_key": "p4-exact-null-contamination-structure-v1",
        "experiment_id": protocol_readback.experiment_id,
        "protocol_hash": protocol_readback.protocol_hash,
        "input_snapshot_id": snapshot_before["snapshot_id"],
        "source_fingerprint": _source_fingerprint(),
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("xinao-market-lab", "numpy", "polars", "pydantic", "scipy")
        },
        "artifacts": _artifact_hashes(run_dir, P4_ARTIFACT_NAMES),
        "claims": {
            "bounded_structure_protocol_verified": True,
            "source_contamination_pin_verified": True,
            "operator_rule_truth_verified": False,
            "payout_basis_verified": False,
            "historical_price_availability_verified": False,
            "generator_mechanism_verified": False,
            "predictive_ranking_permitted": False,
            "recommendation_permitted": False,
            "real_money_use_permitted": False,
            "whole_project_complete": False,
        },
        "claim_boundary": (
            "This run verifies a frozen five-test Monte Carlo structure protocol and exact raw-source "
            "contamination pin. Retaining or rejecting the bounded null is not an economic edge, "
            "generator-mechanism attribution, candidate ranking, recommendation, source-truth "
            "upgrade, forward-price claim, real-money permission, or whole-project completion."
        ),
    }
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    return {
        "status": manifest["status"],
        "run_dir": str(run_dir),
        "experiment_id": protocol_readback.experiment_id,
        "protocol_hash": protocol_readback.protocol_hash,
        "protocol_artifact_sha256": protocol_artifact_sha256,
        "input_snapshot_id": snapshot_before["snapshot_id"],
        "contamination_status": judge.contamination_status,
        "family_size": protocol_readback.spec.family_size,
        "simulation_count": null_summary["simulation_count"],
        "null_statistics_sha256": null_ledger_sha256,
        "null_statistics_chain_tip": null_summary["null_score_chain_tip"],
        "structure_status": judge.structure_status,
        "rejected_tests": list(judge.rejected_tests),
        "economic_claim_status": judge.economic_claim_status,
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _expected_p4_anchor(run_dir: Path) -> dict[str, Any]:
    protocol_path = run_dir / "p4_protocol.json"
    protocol = P4Protocol.model_validate_json(protocol_path.read_text(encoding="utf-8"), strict=True)
    null_family = _read_json_file(run_dir / "null_family.json")
    contamination_pin = _read_json_file(run_dir / "contamination_pin.json")
    null_summary = _read_json_file(run_dir / "null_summary.json")
    p3_pin = P3AcceptancePin.model_validate_json(
        (run_dir / "p3_acceptance_pin.json").read_text(encoding="utf-8"), strict=True
    )
    simulation_contract = {
        "family": null_family["tests"],
        "alpha_fwer_fraction": null_family["alpha_fwer_fraction"],
        "multiplicity_method": null_family["multiplicity_method"],
        "rng": null_family["rng"],
        "sampler": null_family["sampler"],
        "fold_sizes": null_family["fold_sizes"],
        "p_value_method": null_family["p_value_method"],
        "null_ledger_contract": null_family["null_ledger_contract"],
    }
    return {
        "schema_version": 1,
        "resolution_key": "p4-exact-null-contamination-structure-v1",
        "input_snapshot_id": protocol.spec.input_snapshot_id,
        "protocol_artifact_sha256": sha256_file(protocol_path),
        "protocol_hash": protocol.protocol_hash,
        "null_family_sha256": sha256_file(run_dir / "null_family.json"),
        "contamination_identity_spec_sha256": hashlib.sha256(
            canonical_json_bytes(contamination_pin)
        ).hexdigest(),
        "simulation_contract_sha256": hashlib.sha256(canonical_json_bytes(simulation_contract)).hexdigest(),
        "null_statistics_sha256": sha256_file(run_dir / "null_statistics.jsonl"),
        "null_statistics_chain_tip": null_summary["null_score_chain_tip"],
        "early_stream_sentinel_event_hashes": null_summary["early_stream_sentinel_event_hashes"],
        "structure_tests_sha256": sha256_file(run_dir / "structure_tests.jsonl"),
        "judge_gate_sha256": sha256_file(run_dir / "judge_gate_p4.json"),
        "run_manifest_sha256": sha256_file(run_dir / "run_manifest.json"),
        "p1_trial_ledger_sha256": ("9c2a59d6f9c26097ac933681dd84e5d9fa84e8ded19df32632873eae11fc0980"),
        "p2_trial_ledger_sha256": ("8e98407bd07812768c401be9d8f5f34fa5b77c8f80e86c6eb60a8376ba794d01"),
        "p2_conformance_ledger_sha256": ("d1dd5444d5c47c75c15187f9e3bfa8c76672c6f5f4c07728338f19e3efda0a6f"),
        "p3_protocol_artifact_sha256": p3_pin.protocol_artifact_sha256,
        "p3_protocol_hash": p3_pin.protocol_hash,
        "p3_trial_ledger_sha256": p3_pin.trial_ledger_sha256,
        "p3_trial_chain_tip": p3_pin.trial_chain_tip,
    }


def verify_p4_run(*, input_root: Path, run_dir: Path, trusted_anchor: Path | None = None) -> dict[str, Any]:
    layout = InputLayout.from_root(input_root)
    run_dir = run_dir.resolve()
    if _is_under(run_dir, layout.root):
        raise ValueError("P4 evidence cannot be inside the input tree")
    required = (*P4_ARTIFACT_NAMES, "run_manifest.json")
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"P4 evidence is incomplete: {missing}")

    snapshot_before = build_snapshot_manifest(layout)
    if _read_json_file(run_dir / "input_snapshot.json") != snapshot_before:
        raise ValueError("P4 input snapshot artifact does not match the current read-only input")
    manifest = _read_json_file(run_dir / "run_manifest.json")
    if manifest.get("status") != "verified_exact_null_contamination_structure_economic_claims_blocked":
        raise ValueError("P4 manifest status is not accepted")
    if manifest.get("resolution_key") != "p4-exact-null-contamination-structure-v1":
        raise ValueError("P4 manifest resolution drift")
    if not _is_sha256_text(manifest.get("source_fingerprint")):
        raise ValueError("P4 producer source fingerprint is not a canonical SHA-256")
    listed = {
        str(item["relative_path"]): (int(item["size_bytes"]), str(item["sha256"]))
        for item in manifest.get("artifacts", [])
    }
    if set(listed) != set(P4_ARTIFACT_NAMES):
        raise ValueError("P4 manifest artifact surface is not exact")
    for name in P4_ARTIFACT_NAMES:
        path = run_dir / name
        if (path.stat().st_size, sha256_file(path)) != listed[name]:
            raise ValueError(f"P4 manifest artifact mismatch: {name}")

    canonical_draws, _quote, source_audit, lineage, _catalog = audit_inputs_p2(layout)
    raw_draws = load_raw_draws(layout)
    p3_pin = P3AcceptancePin.model_validate_json(
        (run_dir / "p3_acceptance_pin.json").read_text(encoding="utf-8"), strict=True
    )
    live_p3 = verify_p3_run(input_root=input_root, run_dir=Path(p3_pin.run_directory))
    live_p3_pin = build_p3_acceptance_pin(Path(p3_pin.run_directory), live_p3)
    if p3_pin != live_p3_pin:
        raise ValueError("P4 P3 acceptance pin no longer matches its immutable source run")

    protocol_path = run_dir / "p4_protocol.json"
    protocol_artifact_sha256 = sha256_file(protocol_path)
    protocol = P4Protocol.model_validate_json(protocol_path.read_text(encoding="utf-8"), strict=True)
    validate_p4_protocol(
        protocol,
        snapshot_id=snapshot_before["snapshot_id"],
        p3_evidence=p3_pin,
    )
    expected_family = build_null_family_artifact(protocol, protocol_artifact_sha256)
    if (run_dir / "null_family.json").read_bytes() != canonical_json_bytes(expected_family):
        raise ValueError("P4 null family does not derive from the frozen accepted protocol")
    expected_contamination_pin = build_contamination_pin_artifact(protocol)
    if (run_dir / "contamination_pin.json").read_bytes() != canonical_json_bytes(expected_contamination_pin):
        raise ValueError("P4 contamination identity specification drift")

    contamination_records, contamination_summary = contamination_evidence(
        raw_draws=raw_draws,
        canonical_draws=canonical_draws,
        lineage=lineage,
    )
    contamination_payload = contamination_ledger_bytes(contamination_records)
    if (run_dir / "contamination_audit.jsonl").read_bytes() != contamination_payload:
        raise ValueError("P4 contamination ledger semantic replay mismatch")
    contamination_payload_sha256 = hashlib.sha256(contamination_payload).hexdigest()
    contamination_summary = {
        **contamination_summary,
        "audit_ledger_sha256": contamination_payload_sha256,
    }
    if (run_dir / "contamination_summary.json").read_bytes() != canonical_json_bytes(contamination_summary):
        raise ValueError("P4 contamination summary semantic replay mismatch")

    values = draw_array(canonical_draws)
    observed_detail = observed_score_detail(values, fold_sizes=protocol.spec.fold_sizes)
    observed_scores = np.asarray(
        [
            observed_detail[test_id]
            for test_id in ("T_special", "T_pos_max", "T_regular_incl", "T_lag1", "T_fold")
        ],
        dtype=np.int64,
    )
    simulation = simulate_shared_null(
        observed_scores=observed_scores,
        draw_count=len(canonical_draws),
        fold_sizes=protocol.spec.fold_sizes,
        seed=protocol.spec.rng_seed,
        n_mc=protocol.spec.n_mc,
        batch_size=protocol.spec.batch_size,
    )
    expected_null_ledger = simulation.pop("_ledger_bytes")
    if (run_dir / "null_statistics.jsonl").read_bytes() != expected_null_ledger:
        raise ValueError("P4 null statistics differ from an independent full PCG64 resimulation")
    null_ledger_sha256 = hashlib.sha256(expected_null_ledger).hexdigest()
    null_summary = {
        **simulation,
        "experiment_id": protocol.experiment_id,
        "protocol_hash": protocol.protocol_hash,
        "protocol_artifact_sha256": protocol_artifact_sha256,
        "observed_detail": observed_detail,
        "rng": expected_family["rng"],
        "sampler": expected_family["sampler"],
    }
    if (run_dir / "null_summary.json").read_bytes() != canonical_json_bytes(null_summary):
        raise ValueError("P4 null summary differs from full resimulation")
    test_results = build_test_results(
        protocol=protocol,
        protocol_artifact_sha256=protocol_artifact_sha256,
        null_summary=null_summary,
    )
    structure_payload = structure_test_ledger_bytes(test_results)
    if (run_dir / "structure_tests.jsonl").read_bytes() != structure_payload:
        raise ValueError("P4 plus-one p-values or exact Holm decisions do not replay")
    structure_ledger_sha256 = hashlib.sha256(structure_payload).hexdigest()
    tombstone_payload = p4_tombstone_ledger_bytes(build_p4_tombstones(protocol))
    if (run_dir / "tombstones.jsonl").read_bytes() != tombstone_payload:
        raise ValueError("P4 deterministic claim tombstones drift")
    tombstone_sha256 = hashlib.sha256(tombstone_payload).hexdigest()

    judge_checks = _p4_judge_checks(
        protocol=protocol,
        contamination_summary=contamination_summary,
        null_summary=null_summary,
        test_results=test_results,
        all_source_rows_unverified=source_audit["lineage_v2"]["source_verify_true"] == 0,
    )
    expected_judge = build_p4_judge(
        protocol=protocol,
        protocol_artifact_sha256=protocol_artifact_sha256,
        test_results=test_results,
        checks=judge_checks,
    )
    actual_judge = P4JudgeGateResult.model_validate_json(
        (run_dir / "judge_gate_p4.json").read_text(encoding="utf-8"), strict=True
    )
    if actual_judge != expected_judge:
        raise ValueError("P4 Judge does not derive from the gate and exact Holm results")
    expected_checks = _p4_checks(
        protocol=protocol,
        protocol_artifact_sha256=protocol_artifact_sha256,
        p3_pin=p3_pin,
        contamination_payload_sha256=contamination_payload_sha256,
        contamination_summary=contamination_summary,
        null_ledger_sha256=null_ledger_sha256,
        null_summary=null_summary,
        structure_ledger_sha256=structure_ledger_sha256,
        test_results=test_results,
        tombstone_sha256=tombstone_sha256,
        judge=expected_judge,
        judge_checks=judge_checks,
    )
    if (run_dir / "checks.json").read_bytes() != canonical_json_bytes(expected_checks):
        raise ValueError("P4 checks do not derive from independent semantic replay")

    claims = manifest.get("claims", {})
    required_false = (
        "operator_rule_truth_verified",
        "payout_basis_verified",
        "historical_price_availability_verified",
        "generator_mechanism_verified",
        "predictive_ranking_permitted",
        "recommendation_permitted",
        "real_money_use_permitted",
        "whole_project_complete",
    )
    if any(claims.get(name) is not False for name in required_false):
        raise ValueError("P4 manifest enables a forbidden economic or completion claim")
    if claims.get("bounded_structure_protocol_verified") is not True:
        raise ValueError("P4 manifest omits the bounded verified structure result")
    if trusted_anchor is not None:
        actual_anchor = _read_json_file(trusted_anchor.resolve())
        expected_anchor = _expected_p4_anchor(run_dir)
        if actual_anchor != expected_anchor:
            raise ValueError("P4 trusted out-of-run acceptance anchor mismatch")

    snapshot_after = build_snapshot_manifest(layout)
    assert_snapshot_unchanged(snapshot_before, snapshot_after)
    return {
        "status": "verified",
        "run_dir": str(run_dir),
        "experiment_id": protocol.experiment_id,
        "protocol_hash": protocol.protocol_hash,
        "protocol_artifact_sha256": protocol_artifact_sha256,
        "input_snapshot_id": snapshot_before["snapshot_id"],
        "contamination_status": actual_judge.contamination_status,
        "family_size": protocol.spec.family_size,
        "simulation_count": null_summary["simulation_count"],
        "null_statistics_sha256": null_ledger_sha256,
        "null_statistics_chain_tip": null_summary["null_score_chain_tip"],
        "structure_status": actual_judge.structure_status,
        "rejected_tests": list(actual_judge.rejected_tests),
        "economic_claim_status": actual_judge.economic_claim_status,
        "trusted_anchor_verified": trusted_anchor is not None,
    }


def build_p4_trusted_anchor(*, input_root: Path, run_dir: Path, anchor_path: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    anchor_path = anchor_path.resolve()
    if _is_under(anchor_path, run_dir):
        raise ValueError("P4 trusted anchor must be outside the evidence run it anchors")
    if anchor_path.exists():
        raise FileExistsError(f"trusted anchor already exists: {anchor_path}")
    verify_p4_run(input_root=input_root, run_dir=run_dir)
    anchor = _expected_p4_anchor(run_dir)
    write_json_atomic(anchor_path, anchor)
    return {
        "status": "trusted_anchor_created",
        "anchor_path": str(anchor_path),
        "anchor_sha256": sha256_file(anchor_path),
        "protocol_hash": anchor["protocol_hash"],
        "null_statistics_sha256": anchor["null_statistics_sha256"],
    }


P5_SOURCE_MATERIAL_PATHS = (
    "pyproject.toml",
    "uv.lock",
    "docs/P5_SPEC.md",
    "src/xinao_market_lab/__init__.py",
    "src/xinao_market_lab/inputs.py",
    "src/xinao_market_lab/models.py",
    "src/xinao_market_lab/p5_cli.py",
    "src/xinao_market_lab/runner.py",
    "src/xinao_market_lab/semantics.py",
    "tests/test_actual_p5.py",
    "tests/test_p5_semantics.py",
)


def _p5_source_statement() -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[2]
    selection_policy = {
        "schema_version": 1,
        "kind": "explicit_allowlist_no_glob_v1",
        "paths": list(P5_SOURCE_MATERIAL_PATHS),
        "path_format": "project_relative_posix",
        "content_hashing": "raw_bytes_sha256",
        "future_phase_files_included": False,
    }
    entries = []
    for relative_path in P5_SOURCE_MATERIAL_PATHS:
        path = project_root / Path(relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"P5 producer source material is missing: {relative_path}")
        entries.append(
            {
                "path": relative_path,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    source_manifest = {
        "selection_policy": selection_policy,
        "selection_policy_sha256": hashlib.sha256(canonical_json_bytes(selection_policy)).hexdigest(),
        "entries": entries,
    }
    materials_sha256 = hashlib.sha256(canonical_json_bytes(source_manifest)).hexdigest()
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "name": "p5-producer-source-materials-v1",
                "digest": {"sha256": materials_sha256},
                "mediaType": "application/vnd.xinao.source-manifest+json",
            }
        ],
        "predicateType": "urn:xinao:predicate:producer-source:v1",
        "predicate": {
            "sourceManifest": source_manifest,
            "producer": {
                "name": "xinao-market-lab-p5",
                "version": importlib.metadata.version("xinao-market-lab"),
            },
            "assurance": {
                "authenticated": False,
                "signature": "none",
                "sourceControl": "none",
                "slsaBuildLevel": "not-claimed",
                "slsaSourceLevel": "not-claimed",
                "scope": "local deterministic source-material identity only",
            },
        },
    }


def _p5_source_fingerprint() -> str:
    return str(_p5_source_statement()["subject"][0]["digest"]["sha256"])


P5_ARTIFACT_NAMES = (
    "input_snapshot.json",
    "producer_source_statement.json",
    "p4_acceptance_pin.json",
    "p2_semantics_surface_pin.json",
    "query_vocabulary.json",
    "source_scan_contract.json",
    "p5_protocol.json",
    "evidence_ledger.jsonl",
    "local_packet_scan.json",
    "unresolved_claim_register.json",
    "play_classification_register.json",
    "tombstones_p5.jsonl",
    "judge_gate_p5.json",
    "checks.json",
)


def _p5_prepare(
    *,
    input_root: Path,
    p4_evidence_run: Path,
    p4_trusted_anchor: Path,
    admin_acceptance: Path,
) -> tuple[InputLayout, dict[str, Any], Any, tuple[Any, ...], P5Protocol]:
    layout = InputLayout.from_root(input_root)
    snapshot = build_snapshot_manifest(layout)
    inventory = build_source_inventory(snapshot)
    acceptance = build_p5_acceptance_pin(
        p4_run_dir=p4_evidence_run,
        trusted_anchor_path=p4_trusted_anchor,
        admin_acceptance_path=admin_acceptance,
    )
    if snapshot["snapshot_id"] != _read_json_file(p4_evidence_run / "run_manifest.json")["input_snapshot_id"]:
        raise ValueError("P5 input snapshot does not match the accepted P4 run")
    protocol = build_p5_protocol(
        snapshot_id=snapshot["snapshot_id"],
        p4_acceptance=acceptance,
        source_inventory=inventory,
    )
    return layout, snapshot, acceptance, inventory, protocol


def _p5_expected_artifacts(
    *,
    layout: InputLayout,
    snapshot: dict[str, Any],
    acceptance: Any,
    inventory: tuple[Any, ...],
    protocol: P5Protocol,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    validate_p5_protocol(
        protocol,
        snapshot_id=snapshot["snapshot_id"],
        p4_acceptance=acceptance,
        source_inventory=inventory,
    )
    vocabulary = query_vocabulary_artifact()
    source_contract = source_scan_contract_artifact(inventory)
    source_statement = _p5_source_statement()
    scan_summary, evidence_records = scan_packet(root=layout.root, protocol=protocol)
    for record in evidence_records:
        verify_selector(root=layout.root, record=record)
    evidence_payload = evidence_ledger_bytes(evidence_records)
    p2_surface, claim_register, classification_register = build_semantics_artifacts(
        layout=layout,
        snapshot_id=snapshot["snapshot_id"],
        p4_acceptance=acceptance,
        records=evidence_records,
        scan_summary=scan_summary,
    )
    tombstones = build_p5_tombstones(protocol)
    tombstone_payload = p5_tombstone_ledger_bytes(tombstones)
    claim_rows = claim_register["rule_claims"]
    classification_rows = classification_register["rows"]
    judge_checks = {
        "protocol_frozen_before_scan": True,
        "producer_source_statement_frozen": (
            source_statement["predicateType"] == "urn:xinao:predicate:producer-source:v1"
            and source_statement["predicate"]["assurance"]["authenticated"] is False
            and source_statement["predicate"]["assurance"]["slsaBuildLevel"] == "not-claimed"
            and source_statement["subject"][0]["digest"]["sha256"] == _p5_source_fingerprint()
        ),
        "p4_independent_acceptance_chain_verified": True,
        "input_snapshot_exact_33_files": snapshot["file_count"] == 33,
        "source_scan_or_exclude_complete": (
            scan_summary["source_file_count"] == 33
            and scan_summary["scanned_file_count"] == 27
            and scan_summary["excluded_file_count"] == 6
        ),
        "source_roles_never_operator_truth": all(
            item.source_role
            in {
                "captured_page_snapshot",
                "package_manifest",
                "human_context_hypothesis",
                "derived_catalog",
            }
            for item in inventory
            if item.disposition == "SCANNED"
        ),
        "query_vocabulary_frozen": (
            tuple(row["term"] for row in vocabulary["terms"]) == QUERY_TERMS
            and vocabulary["vocabulary_sha256"] == protocol.spec.query_vocabulary_sha256
        ),
        "canonical_marker_counts_rederived": (scan_summary["term_counts"] == EXPECTED_CANONICAL_TERM_COUNTS),
        "all_evidence_selectors_reresolved": True,
        "evidence_ledger_complete_and_hash_chained": (
            len(evidence_records) == sum(scan_summary["term_counts"].values())
            and scan_summary["evidence_chain_tip"]
            == (evidence_records[-1].record_hash if evidence_records else "0" * 64)
        ),
        "two_unresolved_rule_claims_accounted_once": (
            tuple(row["subject"] for row in claim_rows) == RULE_CLAIM_SUBJECTS
            and len({row["claim_id"] for row in claim_rows}) == 2
            and all(row["p5_evidence_status"] == "INSUFFICIENT_LOCAL_EVIDENCE" for row in claim_rows)
            and all(row["direct_marker_count"] == 0 for row in claim_rows)
        ),
        "unresolved_claims_remain_uncompiled": all(
            row["semantics_hash"] is None and row["compiler_execution_permitted"] is False
            for row in claim_rows
        ),
        "play_structure_136_16_120_accounted_once": (
            classification_register["source_row_count"] == 136
            and classification_register["implemented_reference_rows"] == 16
            and classification_register["unresolved_rows"] == 120
            and len(classification_rows) == 136
            and len({row["row_number"] for row in classification_rows}) == 136
        ),
        "network_and_economic_actions_disabled": (
            protocol.spec.network_permitted is False
            and protocol.spec.semantics_compilation_permitted is False
            and protocol.spec.operator_truth_upgrade_permitted is False
            and protocol.spec.economic_claim_permitted is False
            and protocol.spec.ranking_permitted is False
            and protocol.spec.recommendation_permitted is False
            and protocol.spec.real_money_use_permitted is False
        ),
    }
    judge = build_p5_judge(protocol=protocol, checks=judge_checks)
    checks = {
        "schema_version": 1,
        "input_snapshot_unchanged": True,
        "input_snapshot_id": snapshot["snapshot_id"],
        "protocol_hash": protocol.protocol_hash,
        "catalog_id": protocol.catalog_id,
        "p4_protocol_hash": acceptance.p4_protocol_hash,
        "p4_trusted_anchor_sha256": acceptance.trusted_anchor_sha256,
        "p2_rule_catalog_sha256": acceptance.p2_rule_catalog_sha256,
        "producer_source_statement_sha256": hashlib.sha256(
            canonical_json_bytes(source_statement)
        ).hexdigest(),
        "producer_source_fingerprint": _p5_source_fingerprint(),
        "query_vocabulary_sha256": protocol.spec.query_vocabulary_sha256,
        "source_scan_contract_sha256": hashlib.sha256(canonical_json_bytes(source_contract)).hexdigest(),
        "evidence_ledger_sha256": hashlib.sha256(evidence_payload).hexdigest(),
        "evidence_record_count": len(evidence_records),
        "evidence_chain_tip": scan_summary["evidence_chain_tip"],
        "term_counts": scan_summary["term_counts"],
        "rule_claim_subjects": list(RULE_CLAIM_SUBJECTS),
        "play_structure_rows": classification_register["source_row_count"],
        "implemented_reference_rows": classification_register["implemented_reference_rows"],
        "unresolved_rows": classification_register["unresolved_rows"],
        "tombstone_count": len(tombstones),
        "tombstones_sha256": hashlib.sha256(tombstone_payload).hexdigest(),
        "judge_checks": judge_checks,
        "all_judge_checks_pass": all(judge_checks.values()),
        "catalog_status": judge.catalog_status,
        "semantics_status": judge.semantics_status,
        "economic_claim_status": judge.economic_claim_status,
        "forbidden_claim_flags_all_false": all(
            value is False
            for value in (
                judge.source_truth_verified,
                judge.semantics_compilation_permitted,
                judge.historical_price_availability_verified,
                judge.ranking_permitted,
                judge.recommendation_permitted,
                judge.real_money_use_permitted,
                judge.whole_project_complete,
            )
        ),
    }
    if not checks["all_judge_checks_pass"] or not checks["forbidden_claim_flags_all_false"]:
        raise RuntimeError(f"P5 acceptance checks failed: {checks}")
    artifacts = {
        "input_snapshot.json": canonical_json_bytes(snapshot),
        "producer_source_statement.json": canonical_json_bytes(source_statement),
        "p4_acceptance_pin.json": canonical_json_bytes(acceptance.model_dump(mode="json")),
        "p2_semantics_surface_pin.json": canonical_json_bytes(p2_surface),
        "query_vocabulary.json": canonical_json_bytes(vocabulary),
        "source_scan_contract.json": canonical_json_bytes(source_contract),
        "p5_protocol.json": canonical_json_bytes(protocol.model_dump(mode="json")),
        "evidence_ledger.jsonl": evidence_payload,
        "local_packet_scan.json": canonical_json_bytes(scan_summary),
        "unresolved_claim_register.json": canonical_json_bytes(claim_register),
        "play_classification_register.json": canonical_json_bytes(classification_register),
        "tombstones_p5.jsonl": tombstone_payload,
        "judge_gate_p5.json": canonical_json_bytes(judge.model_dump(mode="json")),
        "checks.json": canonical_json_bytes(checks),
    }
    if tuple(artifacts) != P5_ARTIFACT_NAMES:
        raise RuntimeError("P5 artifact order or surface drift")
    return artifacts, checks


def _p5_manifest(
    protocol: P5Protocol,
    artifacts: dict[str, bytes],
) -> dict[str, Any]:
    source_statement = json.loads(artifacts["producer_source_statement.json"])
    source_fingerprint = source_statement["subject"][0]["digest"]["sha256"]
    if not _is_sha256_text(source_fingerprint):
        raise ValueError("P5 producer source fingerprint is not a canonical SHA-256")
    return {
        "schema_version": 1,
        "status": "verified_evidence_catalog_semantics_still_unresolved_economic_claims_blocked",
        "resolution_key": "p5-unresolved-semantics-evidence-catalog-v1",
        "catalog_id": protocol.catalog_id,
        "protocol_hash": protocol.protocol_hash,
        "input_snapshot_id": protocol.spec.input_snapshot_id,
        "source_fingerprint": source_fingerprint,
        "source_attestation": {
            "statement_sha256": hashlib.sha256(artifacts["producer_source_statement.json"]).hexdigest(),
            "historical_artifact_integrity": "HISTORICAL_ARTIFACT_INTEGRITY_VERIFIED",
            "current_source_replay": "CURRENT_SOURCE_REPLAY_VERIFIED",
            "authenticated": False,
            "slsa_level": "not-claimed",
        },
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("xinao-market-lab", "polars", "pydantic")
        },
        "artifacts": [
            {
                "relative_path": name,
                "size_bytes": len(artifacts[name]),
                "sha256": hashlib.sha256(artifacts[name]).hexdigest(),
            }
            for name in P5_ARTIFACT_NAMES
        ],
        "claims": {
            "evidence_catalog_verified": True,
            "semantics_resolved": False,
            "operator_rule_truth_verified": False,
            "payout_basis_verified": False,
            "special_two_sided_49_policy_verified": False,
            "historical_price_availability_verified": False,
            "predictive_ranking_permitted": False,
            "recommendation_permitted": False,
            "real_money_use_permitted": False,
            "whole_project_complete": False,
        },
        "claim_boundary": (
            "This run verifies a complete frozen 33-file scan-or-exclude catalog, replayable RFC 6901 "
            "and W3C text selectors, two unresolved RuleClaims, and the separate 136/16/120 P2 "
            "classification surface. Sparse generic markers do not resolve payout or special-49 "
            "semantics and cannot enable operator truth, economic claims, ranking, recommendation, "
            "real-money use, or project completion."
        ),
    }


def run_p5_unresolved_semantics_evidence_catalog(
    *,
    input_root: Path,
    evidence_root: Path,
    run_name: str,
    p4_evidence_run: Path,
    p4_trusted_anchor: Path,
    admin_acceptance: Path,
) -> dict[str, Any]:
    layout, snapshot, acceptance, inventory, protocol = _p5_prepare(
        input_root=input_root,
        p4_evidence_run=p4_evidence_run,
        p4_trusted_anchor=p4_trusted_anchor,
        admin_acceptance=admin_acceptance,
    )
    evidence_root = evidence_root.resolve()
    run_dir = evidence_root / run_name
    if _is_under(run_dir, layout.root):
        raise ValueError("P5 evidence cannot be inside the input tree")
    if layout.root == CANONICAL_INPUT_ROOT.resolve() and not _is_under(
        run_dir, CANONICAL_EVIDENCE_ROOT.resolve()
    ):
        raise ValueError(f"canonical input evidence must stay under {CANONICAL_EVIDENCE_ROOT}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)

    pre_scan = {
        "input_snapshot.json": canonical_json_bytes(snapshot),
        "producer_source_statement.json": canonical_json_bytes(_p5_source_statement()),
        "p4_acceptance_pin.json": canonical_json_bytes(acceptance.model_dump(mode="json")),
        "query_vocabulary.json": canonical_json_bytes(query_vocabulary_artifact()),
        "source_scan_contract.json": canonical_json_bytes(source_scan_contract_artifact(inventory)),
        "p5_protocol.json": canonical_json_bytes(protocol.model_dump(mode="json")),
    }
    for name, payload in pre_scan.items():
        _write_ledger(run_dir / name, payload)
    protocol_readback = P5Protocol.model_validate_json(
        (run_dir / "p5_protocol.json").read_text(encoding="utf-8"), strict=True
    )
    validate_p5_protocol(
        protocol_readback,
        snapshot_id=snapshot["snapshot_id"],
        p4_acceptance=acceptance,
        source_inventory=inventory,
    )
    artifacts, checks = _p5_expected_artifacts(
        layout=layout,
        snapshot=snapshot,
        acceptance=acceptance,
        inventory=inventory,
        protocol=protocol_readback,
    )
    for name, payload in artifacts.items():
        if name in pre_scan:
            if (run_dir / name).read_bytes() != payload:
                raise RuntimeError(f"P5 pre-scan artifact drifted during execution: {name}")
        else:
            _write_ledger(run_dir / name, payload)
    manifest = _p5_manifest(protocol_readback, artifacts)
    _write_ledger(run_dir / "run_manifest.json", canonical_json_bytes(manifest))
    snapshot_after = build_snapshot_manifest(layout)
    assert_snapshot_unchanged(snapshot, snapshot_after)
    verification = verify_p5_run(
        input_root=input_root,
        run_dir=run_dir,
        p4_evidence_run=p4_evidence_run,
        p4_trusted_anchor=p4_trusted_anchor,
        admin_acceptance=admin_acceptance,
    )
    return {
        "status": manifest["status"],
        "run_dir": str(run_dir),
        "catalog_id": protocol.catalog_id,
        "protocol_hash": protocol.protocol_hash,
        "input_snapshot_id": snapshot["snapshot_id"],
        "evidence_record_count": checks["evidence_record_count"],
        "evidence_ledger_sha256": checks["evidence_ledger_sha256"],
        "evidence_chain_tip": checks["evidence_chain_tip"],
        "term_counts": checks["term_counts"],
        "catalog_status": checks["catalog_status"],
        "semantics_status": checks["semantics_status"],
        "economic_claim_status": checks["economic_claim_status"],
        "self_verification": verification["status"],
    }


def _expected_p5_anchor(run_dir: Path) -> dict[str, Any]:
    protocol = P5Protocol.model_validate_json(
        (run_dir / "p5_protocol.json").read_text(encoding="utf-8"), strict=True
    )
    scan = _read_json_file(run_dir / "local_packet_scan.json")
    acceptance = _read_json_file(run_dir / "p4_acceptance_pin.json")
    return {
        "schema_version": 1,
        "resolution_key": "p5-unresolved-semantics-evidence-catalog-v1",
        "input_snapshot_id": protocol.spec.input_snapshot_id,
        "catalog_id": protocol.catalog_id,
        "protocol_hash": protocol.protocol_hash,
        "protocol_artifact_sha256": sha256_file(run_dir / "p5_protocol.json"),
        "producer_source_statement_sha256": sha256_file(run_dir / "producer_source_statement.json"),
        "producer_source_fingerprint": _read_json_file(run_dir / "producer_source_statement.json")["subject"][
            0
        ]["digest"]["sha256"],
        "query_vocabulary_sha256": sha256_file(run_dir / "query_vocabulary.json"),
        "source_scan_contract_sha256": sha256_file(run_dir / "source_scan_contract.json"),
        "evidence_ledger_sha256": sha256_file(run_dir / "evidence_ledger.jsonl"),
        "evidence_chain_tip": scan["evidence_chain_tip"],
        "p2_semantics_surface_pin_sha256": sha256_file(run_dir / "p2_semantics_surface_pin.json"),
        "unresolved_claim_register_sha256": sha256_file(run_dir / "unresolved_claim_register.json"),
        "play_classification_register_sha256": sha256_file(run_dir / "play_classification_register.json"),
        "tombstones_sha256": sha256_file(run_dir / "tombstones_p5.jsonl"),
        "judge_gate_sha256": sha256_file(run_dir / "judge_gate_p5.json"),
        "run_manifest_sha256": sha256_file(run_dir / "run_manifest.json"),
        "p4_trusted_anchor_sha256": acceptance["trusted_anchor_sha256"],
        "p4_admin_acceptance_sha256": acceptance["admin_acceptance_sha256"],
    }


def verify_p5_run(
    *,
    input_root: Path,
    run_dir: Path,
    p4_evidence_run: Path,
    p4_trusted_anchor: Path,
    admin_acceptance: Path,
    trusted_anchor: Path | None = None,
) -> dict[str, Any]:
    layout, snapshot, acceptance, inventory, protocol = _p5_prepare(
        input_root=input_root,
        p4_evidence_run=p4_evidence_run,
        p4_trusted_anchor=p4_trusted_anchor,
        admin_acceptance=admin_acceptance,
    )
    run_dir = run_dir.resolve()
    if _is_under(run_dir, layout.root):
        raise ValueError("P5 evidence cannot be inside the input tree")
    required = (*P5_ARTIFACT_NAMES, "run_manifest.json")
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"P5 run is incomplete: {missing}")
    actual_protocol = P5Protocol.model_validate_json(
        (run_dir / "p5_protocol.json").read_text(encoding="utf-8"), strict=True
    )
    if actual_protocol != protocol:
        raise ValueError("P5 protocol differs from the independently rebuilt protocol")
    artifacts, checks = _p5_expected_artifacts(
        layout=layout,
        snapshot=snapshot,
        acceptance=acceptance,
        inventory=inventory,
        protocol=protocol,
    )
    for name, expected in artifacts.items():
        if (run_dir / name).read_bytes() != expected:
            raise ValueError(f"P5 semantic artifact mismatch: {name}")
    ledger_records = tuple(
        P5EvidenceRecord.model_validate_json(line, strict=True)
        for line in (run_dir / "evidence_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    )
    if evidence_ledger_bytes(ledger_records) != artifacts["evidence_ledger.jsonl"]:
        raise ValueError("P5 evidence ledger typed replay mismatch")
    for record in ledger_records:
        verify_selector(root=layout.root, record=record)
    expected_manifest = _p5_manifest(protocol, artifacts)
    if (run_dir / "run_manifest.json").read_bytes() != canonical_json_bytes(expected_manifest):
        raise ValueError("P5 run manifest or claim boundary mismatch")
    anchor_verified = False
    if trusted_anchor is not None:
        expected_anchor = _expected_p5_anchor(run_dir)
        if _read_json_file(trusted_anchor) != expected_anchor:
            raise ValueError("P5 trusted anchor mismatch")
        anchor_verified = True
    snapshot_after = build_snapshot_manifest(layout)
    assert_snapshot_unchanged(snapshot, snapshot_after)
    return {
        "status": "verified",
        "run_dir": str(run_dir),
        "catalog_id": protocol.catalog_id,
        "protocol_hash": protocol.protocol_hash,
        "input_snapshot_id": snapshot["snapshot_id"],
        "evidence_record_count": checks["evidence_record_count"],
        "evidence_ledger_sha256": checks["evidence_ledger_sha256"],
        "evidence_chain_tip": checks["evidence_chain_tip"],
        "catalog_status": checks["catalog_status"],
        "semantics_status": checks["semantics_status"],
        "economic_claim_status": checks["economic_claim_status"],
        "historical_artifact_integrity": "HISTORICAL_ARTIFACT_INTEGRITY_VERIFIED",
        "current_source_replay": "CURRENT_SOURCE_REPLAY_VERIFIED",
        "producer_source_fingerprint": _p5_source_fingerprint(),
        "trusted_anchor_verified": anchor_verified,
    }


def build_p5_trusted_anchor(
    *,
    input_root: Path,
    run_dir: Path,
    p4_evidence_run: Path,
    p4_trusted_anchor: Path,
    admin_acceptance: Path,
    anchor_path: Path,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    anchor_path = anchor_path.resolve()
    if _is_under(anchor_path, run_dir):
        raise ValueError("P5 trusted anchor must be outside the run directory")
    if anchor_path.exists():
        raise FileExistsError(f"trusted anchor already exists and is immutable: {anchor_path}")
    verify_p5_run(
        input_root=input_root,
        run_dir=run_dir,
        p4_evidence_run=p4_evidence_run,
        p4_trusted_anchor=p4_trusted_anchor,
        admin_acceptance=admin_acceptance,
    )
    anchor = _expected_p5_anchor(run_dir)
    write_json_atomic(anchor_path, anchor)
    return {
        "status": "trusted_anchor_created",
        "anchor_path": str(anchor_path),
        "anchor_sha256": sha256_file(anchor_path),
        "catalog_id": anchor["catalog_id"],
        "protocol_hash": anchor["protocol_hash"],
        "evidence_ledger_sha256": anchor["evidence_ledger_sha256"],
    }


def compare_ledgers(first_run: Path, second_run: Path) -> dict[str, Any]:
    first = first_run / "trials.jsonl"
    second = second_run / "trials.jsonl"
    first_bytes = first.read_bytes()
    second_bytes = second.read_bytes()
    return {
        "equal": first_bytes == second_bytes,
        "first_sha256": hashlib.sha256(first_bytes).hexdigest(),
        "second_sha256": hashlib.sha256(second_bytes).hexdigest(),
        "first_size": len(first_bytes),
        "second_size": len(second_bytes),
    }


def _summarize_projection_candidates(records: tuple[ProjectionTrialRecord, ...]) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for candidate_id in dict.fromkeys(record.candidate_id for record in records):
        selected = [record for record in records if record.candidate_id == candidate_id]
        bets = [record for record in selected if record.decision.place_bet]
        wins = [record for record in bets if record.settlement.outcome == "win"]
        total_stake = sum((record.settlement.stake for record in selected), Decimal("0"))
        gross = sum((record.settlement.gross_return for record in selected), Decimal("0"))
        net = sum((record.settlement.net_return for record in selected), Decimal("0"))
        summaries.append(
            {
                "candidate_id": candidate_id,
                "draws": len(selected),
                "bets": len(bets),
                "wins": len(wins),
                "total_stake": str(total_stake),
                "mechanics_gross_return_under_assumption": str(gross),
                "mechanics_net_return_under_assumption": str(net),
            }
        )
    return {
        "schema_version": 2,
        "ranking_permitted": False,
        "inference_permitted": False,
        "source_truth_verified": False,
        "historical_price_availability_verified": False,
        "payout_basis_status": "UNRESOLVED",
        "summaries": summaries,
    }


def run_p2_domain_lineage_zhengma(*, input_root: Path, evidence_root: Path, run_name: str) -> dict[str, Any]:
    layout = InputLayout.from_root(input_root)
    evidence_root = evidence_root.resolve()
    run_dir = evidence_root / run_name
    if _is_under(run_dir, layout.root):
        raise ValueError("evidence output must not be inside the input tree")
    if layout.root == CANONICAL_INPUT_ROOT.resolve() and not _is_under(
        run_dir, CANONICAL_EVIDENCE_ROOT.resolve()
    ):
        raise ValueError(f"canonical input evidence must stay under {CANONICAL_EVIDENCE_ROOT}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)

    snapshot_before = build_snapshot_manifest(layout)
    write_json_atomic(run_dir / "input_snapshot.json", snapshot_before)
    draws, quote, source_audit, lineage, source_catalog = audit_inputs_p2(layout)
    write_json_atomic(run_dir / "source_audit.json", source_audit)
    lineage_pin = {
        "schema_version": 2,
        "policy_id": "validation-ranked-exact-time-alias-then-chronological-outcome-v2",
        "policy": [
            "retain every source row in lineage evidence",
            "for identical open_time and full outcome prefer expect-year consistency, "
            "then source verification, then source index",
            "quarantine the lower-ranked exact-time alias",
            "for a full outcome repeated at a later open_time retain the earliest canonical row",
            "never upgrade source_verified",
        ],
        "source_count": len(lineage),
        "usable_count": len(draws),
        "records": [record.model_dump(mode="json") for record in lineage],
    }
    write_json_atomic(run_dir / "lineage_pin.json", lineage_pin)

    project_root = Path(__file__).resolve().parents[2]
    typed_rule_bundle, compiled_rules, classifications = build_typed_rule_catalog(
        layout=layout,
        rule_bundle_path=project_root / "rules" / "p2_rule_bundle_v1.json",
        snapshot_id=snapshot_before["snapshot_id"],
    )

    regular_semantics = build_regular_semantics()
    special_semantics = build_special_semantics()
    claims = p2_rule_claims(
        regular_semantics=regular_semantics,
        special_semantics=special_semantics,
    )
    regular_claim = next(claim for claim in claims if claim.subject == "regular_set_membership")
    rule_catalog = {
        **source_catalog,
        "typed_rule_bundle": typed_rule_bundle,
        "compiled_semantics": [
            special_semantics.model_dump(mode="json"),
            regular_semantics.model_dump(mode="json"),
        ],
        "claims": [claim.model_dump(mode="json") for claim in claims],
        "compiler_gate": "UNRESOLVED claims have no semantics_hash and cannot execute",
    }
    write_json_atomic(run_dir / "rule_catalog.json", rule_catalog)

    cost = CostModel()
    candidates = p2_default_candidates()
    payout_assumption_id = "mechanics-assumption-inclusive-return-v1"
    object_pin = {
        "schema_version": 2,
        "series": SeriesSpec().model_dump(mode="json"),
        "quote": quote.model_dump(mode="json"),
        "semantics": regular_semantics.model_dump(mode="json"),
        "rule_claim": regular_claim.model_dump(mode="json"),
        "cost": cost.model_dump(mode="json"),
        "payout_assumption_id": payout_assumption_id,
        "payout_assumption_status": "explicit_mechanics_assumption_not_source_truth",
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "hard_boundaries": [
            "regular-set membership is pinned by the project specification only",
            "displayed odds are not proof of inclusive-return or net-win payout basis",
            "the quote is a single non-contemporaneous candidate snapshot",
            "special two-sided 49 policy remains unresolved and uncompiled",
            "no output is a ranking, recommendation, source-truth upgrade, or real-money action",
        ],
    }
    write_json_atomic(run_dir / "object_pin.json", object_pin)

    conformance_events = build_conformance_events(draws, compiled_rules, cost)
    conformance_payload = conformance_ledger_bytes(conformance_events)
    conformance_sha256 = _write_ledger(run_dir / "conformance_events.jsonl", conformance_payload)

    run_key, records = build_regular_trial_records(
        draws=draws,
        lineage=lineage,
        candidates=candidates,
        quote=quote,
        semantics=regular_semantics,
        claim=regular_claim,
        cost=cost,
        snapshot_id=snapshot_before["snapshot_id"],
        payout_assumption_id=payout_assumption_id,
    )
    ledger_payload = projection_ledger_bytes(records)
    ledger_sha256 = _write_ledger(run_dir / "trials.jsonl", ledger_payload)
    candidate_summary = _summarize_projection_candidates(records)
    write_json_atomic(run_dir / "candidate_summary.json", candidate_summary)
    exact_baseline = regular_set_exact_baseline(draws, quote)
    write_json_atomic(run_dir / "exact_baseline.json", exact_baseline)

    changed_last = draws[-1]
    occupied = {*changed_last.regular_numbers, changed_last.special}
    replacement = next(number for number in range(1, 50) if number not in occupied)
    mutated_last = changed_last.model_copy(
        update={"regular_numbers": (replacement, *changed_last.regular_numbers[1:])}
    )
    mutated_draws = (*draws[:-1], mutated_last)
    prefix_limit = len(draws) - 1
    future_suffix_decisions_unchanged = p2_decision_trace_bytes(
        draws, candidates, through_index=prefix_limit
    ) == p2_decision_trace_bytes(mutated_draws, candidates, through_index=prefix_limit)

    snapshot_after = build_snapshot_manifest(layout)
    assert_snapshot_unchanged(snapshot_before, snapshot_after)
    unresolved_subjects = sorted(claim.subject for claim in claims if claim.status == "unresolved")
    quarantine_expects = sorted(record.source_expect for record in lineage if record.status == "quarantined")
    checks = {
        "schema_version": 2,
        "input_snapshot_unchanged": True,
        "catalog_status": source_catalog["catalog_status"],
        "catalog_play_rows": source_catalog["sources"]["play_structure"]["row_count"],
        "catalog_odds_rows": source_catalog["sources"]["odds_candidates"]["row_count"],
        "typed_rule_count": len(compiled_rules),
        "typed_rule_keys": [rule.definition.rule_key for rule in compiled_rules],
        "play_classification_rows": len(classifications),
        "play_implemented_reference_rows": sum(item.status == "IMPLEMENTED" for item in classifications),
        "play_unresolved_rows": sum(item.status == "UNRESOLVED" for item in classifications),
        "all_rules_have_three_golden_events": all(
            sum(event.rule_key == rule.definition.rule_key for event in conformance_events) == 3
            for rule in compiled_rules
        ),
        "conformance_event_count": len(conformance_events),
        "conformance_ledger_sha256": conformance_sha256,
        "conformance_chain_tip": conformance_events[-1].event_hash,
        "conformance_previous_hash_field_present": all(
            len(event.previous_hash) == 64 for event in conformance_events
        ),
        "all_rules_stamp_cost_model": all(
            event.cost_model_id == cost.cost_model_id for event in conformance_events
        ),
        "modal_snapshot_prices": {
            rule.definition.rule_key: rule.definition.expected_modal_odds for rule in compiled_rules
        },
        "all_exact_number_49_paths_resolvable": all(
            rule.quote_evidence["exact_number_49_status"] == "resolvable_at_modal_exact_number_price"
            for rule in compiled_rules
        ),
        "all_label_and_two_sided_49_paths_unresolved": all(
            rule.quote_evidence["label_and_two_sided_49_policy_status"] == "UNRESOLVED"
            for rule in compiled_rules
        ),
        "legacy_p1_usable_draws": source_audit["legacy_p1"]["usable_draws"],
        "lineage_v2_source_draws": len(lineage),
        "lineage_v2_usable_draws": len(draws),
        "lineage_v2_quarantines": quarantine_expects,
        "lineage_v2_strictly_increasing_open_time": source_audit["lineage_v2"][
            "strictly_increasing_open_time"
        ],
        "all_source_rows_unverified": source_audit["lineage_v2"]["source_verify_true"] == 0,
        "quote_page_aliases_identical": source_audit["regular_a_quote"]["page_aliases_identical"],
        "quote_captured_at": quote.captured_at.isoformat(),
        "quote_bundle_created_at": quote.bundle_created_at.isoformat(),
        "quote_displayed_odds": str(quote.displayed_odds),
        "payout_basis_status": quote.payout_basis_status.upper(),
        "unresolved_claim_subjects": unresolved_subjects,
        "future_suffix_decisions_unchanged": future_suffix_decisions_unchanged,
        "candidate_count": len(candidates),
        "candidate_count_within_limit": len(candidates) <= 4,
        "ledger_record_count": len(records),
        "ledger_sha256": ledger_sha256,
        "always_no_bet_all_zero": next(
            summary
            for summary in candidate_summary["summaries"]
            if summary["candidate_id"] == "always_no_bet"
        )
        == {
            "candidate_id": "always_no_bet",
            "draws": len(draws),
            "bets": 0,
            "wins": 0,
            "total_stake": "0",
            "mechanics_gross_return_under_assumption": "0",
            "mechanics_net_return_under_assumption": "0",
        },
        "completion_claim": (
            "eight_typed_exact_rules_and_hash_chain_verified_under_pinned_spec_with_lineage_v2_"
            "no_source_truth_claim"
        ),
    }
    required = (
        "input_snapshot_unchanged",
        "lineage_v2_strictly_increasing_open_time",
        "all_source_rows_unverified",
        "quote_page_aliases_identical",
        "future_suffix_decisions_unchanged",
        "candidate_count_within_limit",
        "always_no_bet_all_zero",
        "all_rules_have_three_golden_events",
        "conformance_previous_hash_field_present",
        "all_rules_stamp_cost_model",
        "all_exact_number_49_paths_resolvable",
        "all_label_and_two_sided_49_paths_unresolved",
    )
    if not all(checks[name] for name in required):
        raise RuntimeError(f"P2 acceptance check failed: {checks}")
    if (
        checks["catalog_play_rows"] != 136
        or checks["catalog_odds_rows"] != 4_043
        or checks["legacy_p1_usable_draws"] != 1_203
        or checks["lineage_v2_source_draws"] != 1_209
        or checks["lineage_v2_usable_draws"] != 1_204
        or checks["quote_displayed_odds"] != "7.850"
        or checks["typed_rule_count"] != 8
        or checks["play_classification_rows"] != 136
        or checks["play_implemented_reference_rows"] != 16
        or checks["play_unresolved_rows"] != 120
        or checks["conformance_event_count"] != 24
        or sorted(set(checks["modal_snapshot_prices"].values())) != ["42.300", "47.285", "7.850"]
        or unresolved_subjects != ["payout_basis", "special_two_sided_49_policy"]
    ):
        raise RuntimeError(f"P2 pinned evidence mismatch: {checks}")
    write_json_atomic(run_dir / "checks.json", checks)

    artifact_names = (
        "input_snapshot.json",
        "source_audit.json",
        "lineage_pin.json",
        "rule_catalog.json",
        "object_pin.json",
        "conformance_events.jsonl",
        "trials.jsonl",
        "candidate_summary.json",
        "exact_baseline.json",
        "checks.json",
    )
    manifest = {
        "schema_version": 2,
        "status": "verified_rule_catalog_pure_settle_with_lineage_v2",
        "run_name": run_name,
        "run_key": run_key,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "input_snapshot_id": snapshot_before["snapshot_id"],
        "source_fingerprint": _source_fingerprint(),
        "evaluation_kind": "typed_exact_rule_conformance_spec_pinned_non_contemporaneous_price",
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("xinao-market-lab", "polars", "pydantic", "scipy")
        },
        "artifacts": _artifact_hashes(run_dir, artifact_names),
        "claims": {
            "operator_rule_truth_verified": False,
            "payout_basis_verified": False,
            "historical_price_availability_verified": False,
            "predictive_ranking_permitted": False,
            "recommendation_permitted": False,
            "real_money_use_permitted": False,
            "whole_project_complete": False,
        },
        "claim_boundary": (
            "This run verifies lossless source cataloging, validation-ranked lineage-v2, eight typed "
            "exact-number projections, 136-row resolution accounting, and a deterministic hash-chained "
            "conformance ledger under a pinned project specification and named payout assumption. "
            "Operator rule truth, payout meaning, historical price "
            "availability, predictive ranking, recommendation, and real-money use remain unverified "
            "or prohibited."
        ),
    }
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    return {
        "status": manifest["status"],
        "run_dir": str(run_dir),
        "run_key": run_key,
        "snapshot_id": snapshot_before["snapshot_id"],
        "ledger_sha256": ledger_sha256,
        "conformance_ledger_sha256": conformance_sha256,
        "typed_rule_count": len(compiled_rules),
        "play_classification_count": len(classifications),
        "draw_count": len(draws),
        "lineage_source_count": len(lineage),
        "candidate_count": len(candidates),
    }
