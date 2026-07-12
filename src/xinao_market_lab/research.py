from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

from .catalog import GENESIS_HASH, settle_catalog_exact, verify_conformance_events
from .domain import decide, default_candidates
from .inputs import canonical_json_bytes, sha256_file
from .models import (
    ChronologicalFold,
    CompiledExactRule,
    ConformanceEvent,
    CostModel,
    Draw,
    JudgeGateResult,
    LineageRecord,
    P2EvidencePin,
    ResearchProtocol,
    ResearchProtocolSpec,
    ResearchTrialEvent,
    RuleHashPin,
    TombstoneRecord,
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_p2_evidence_pin(p2_run: Path, expected_snapshot_id: str) -> P2EvidencePin:
    p2_run = p2_run.resolve()
    manifest_path = p2_run / "run_manifest.json"
    checks_path = p2_run / "checks.json"
    catalog_path = p2_run / "rule_catalog.json"
    conformance_path = p2_run / "conformance_events.jsonl"
    for path in (manifest_path, checks_path, catalog_path, conformance_path):
        if not path.is_file():
            raise FileNotFoundError(f"required P2 evidence missing: {path}")

    manifest = _read_json(manifest_path)
    checks = _read_json(checks_path)
    if manifest.get("status") != "verified_rule_catalog_pure_settle_with_lineage_v2":
        raise ValueError("P2 evidence status is not the accepted typed-rule vertical")
    if manifest.get("input_snapshot_id") != expected_snapshot_id:
        raise ValueError("P2 evidence snapshot does not match the current input snapshot")
    if checks.get("typed_rule_count") != 8 or checks.get("play_classification_rows") != 136:
        raise ValueError("P2 evidence does not expose the accepted rule/classification surface")
    if checks.get("conformance_event_count") != 24:
        raise ValueError("P2 evidence does not expose the accepted conformance ledger")

    listed = {
        str(item["relative_path"]): (int(item["size_bytes"]), str(item["sha256"]))
        for item in manifest.get("artifacts", [])
    }
    for name, (expected_size, expected_hash) in listed.items():
        path = p2_run / name
        if path.stat().st_size != expected_size or sha256_file(path) != expected_hash:
            raise ValueError(f"P2 artifact manifest mismatch: {name}")

    events = tuple(
        ConformanceEvent.model_validate_json(line, strict=True)
        for line in conformance_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    verify_conformance_events(events)
    if not events or events[-1].event_hash != checks.get("conformance_chain_tip"):
        raise ValueError("P2 conformance chain tip mismatch")
    conformance_sha256 = sha256_file(conformance_path)
    if conformance_sha256 != checks.get("conformance_ledger_sha256"):
        raise ValueError("P2 conformance ledger hash mismatch")
    return P2EvidencePin(
        run_directory=str(p2_run),
        input_snapshot_id=expected_snapshot_id,
        checks_sha256=sha256_file(checks_path),
        rule_catalog_sha256=sha256_file(catalog_path),
        conformance_ledger_sha256=conformance_sha256,
        conformance_chain_tip=events[-1].event_hash,
        status="verified_rule_catalog_pure_settle_with_lineage_v2",
    )


def build_chronological_folds(draws: tuple[Draw, ...], fold_count: int = 4) -> tuple[ChronologicalFold, ...]:
    if fold_count < 2 or len(draws) < fold_count:
        raise ValueError("chronological protocol requires at least two non-empty folds")
    boundaries = [index * len(draws) // fold_count for index in range(fold_count)] + [len(draws)]
    folds: list[ChronologicalFold] = []
    for index, (start, end) in enumerate(pairwise(boundaries), 1):
        if start == end:
            raise ValueError("chronological fold cannot be empty")
        context = draws[start - 1] if start else None
        folds.append(
            ChronologicalFold(
                fold_id=f"fold-{index}",
                start_index=start,
                end_index_exclusive=end,
                start_expect=draws[start].source_expect,
                end_expect=draws[end - 1].source_expect,
                start_time=draws[start].open_time,
                end_time=draws[end - 1].open_time,
                context_end_index=start - 1 if context else None,
                context_end_expect=context.source_expect if context else None,
                context_end_time=context.open_time if context else None,
            )
        )
    return tuple(folds)


def build_research_protocol(
    *,
    draws: tuple[Draw, ...],
    compiled_rules: tuple[CompiledExactRule, ...],
    cost: CostModel,
    snapshot_id: str,
    p2_evidence: P2EvidencePin,
) -> ResearchProtocol:
    candidates = default_candidates()
    rule_pins = tuple(
        RuleHashPin(rule_key=rule.definition.rule_key, rule_hash=rule.rule_hash) for rule in compiled_rules
    )
    spec = ResearchProtocolSpec(
        input_snapshot_id=snapshot_id,
        p2_evidence=p2_evidence,
        candidates=candidates,
        rules=rule_pins,
        cost_model=cost,
        source_draw_count=len(draws),
        folds=build_chronological_folds(draws),
        declared_cell_budget=len(candidates) * len(compiled_rules),
        declared_trial_row_budget=len(candidates) * len(compiled_rules) * len(draws),
        metrics=(
            "draws",
            "bets",
            "wins",
            "total_stake",
            "mechanics_gross_return_under_assumption",
            "mechanics_net_return_under_assumption",
        ),
    )
    protocol_hash = hashlib.sha256(canonical_json_bytes(spec.model_dump(mode="json"))).hexdigest()
    return ResearchProtocol(
        spec=spec,
        protocol_hash=protocol_hash,
        experiment_id=f"experiment-p3-{protocol_hash[:24]}",
    )


def validate_research_protocol(
    protocol: ResearchProtocol,
    *,
    draws: tuple[Draw, ...],
    compiled_rules: tuple[CompiledExactRule, ...],
) -> None:
    expected_hash = hashlib.sha256(canonical_json_bytes(protocol.spec.model_dump(mode="json"))).hexdigest()
    if protocol.protocol_hash != expected_hash:
        raise ValueError("research protocol hash mismatch")
    if protocol.experiment_id != f"experiment-p3-{expected_hash[:24]}":
        raise ValueError("experiment id does not derive from the frozen protocol")
    if protocol.spec.source_draw_count != len(draws):
        raise ValueError("research protocol draw count mismatch")
    expected_rules = tuple((rule.definition.rule_key, rule.rule_hash) for rule in compiled_rules)
    actual_rules = tuple((pin.rule_key, pin.rule_hash) for pin in protocol.spec.rules)
    if actual_rules != expected_rules:
        raise ValueError("research protocol rule pins disagree with compiled rules")
    expected_folds = build_chronological_folds(draws)
    if protocol.spec.folds != expected_folds:
        raise ValueError("research protocol chronological cutoffs disagree with input event time")


def _fold_ids(protocol: ResearchProtocol) -> tuple[str, ...]:
    result = [""] * protocol.spec.source_draw_count
    for fold in protocol.spec.folds:
        result[fold.start_index : fold.end_index_exclusive] = [fold.fold_id] * (
            fold.end_index_exclusive - fold.start_index
        )
    if any(not fold_id for fold_id in result):
        raise ValueError("protocol folds do not cover all draws")
    return tuple(result)


def _trial_event_material(event: ResearchTrialEvent) -> dict[str, Any]:
    payload = event.model_dump(mode="json")
    payload.pop("event_hash")
    return payload


def iter_research_trial_events(
    *,
    protocol: ResearchProtocol,
    protocol_artifact_sha256: str,
    draws: tuple[Draw, ...],
    lineage: tuple[LineageRecord, ...],
    compiled_rules: tuple[CompiledExactRule, ...],
) -> Iterator[ResearchTrialEvent]:
    validate_research_protocol(protocol, draws=draws, compiled_rules=compiled_rules)
    fold_ids = _fold_ids(protocol)
    lineage_by_expect = {record.source_expect: record for record in lineage if record.status == "canonical"}
    previous_hash = GENESIS_HASH
    sequence = 0
    for candidate in protocol.spec.candidates:
        for rule in compiled_rules:
            for draw_index, draw in enumerate(draws):
                lineage_record = lineage_by_expect.get(draw.source_expect)
                if lineage_record is None:
                    raise ValueError(f"draw has no canonical lineage record: {draw.source_expect}")
                decision = decide(candidate, draws[:draw_index])
                expected_cutoff = draws[draw_index - 1].source_expect if draw_index else None
                if decision.information_cutoff_expect != expected_cutoff:
                    raise ValueError("candidate decision does not use the exact prior-event cutoff")
                settlement = settle_catalog_exact(decision, draw, rule, protocol.spec.cost_model)
                input_payload = {
                    "snapshot_id": protocol.spec.input_snapshot_id,
                    "source_expect": draw.source_expect,
                    "open_time": draw.open_time.isoformat(),
                    "source_verified": draw.source_verified,
                    "lineage_reason_code": lineage_record.reason_code,
                    "regular_numbers": list(draw.regular_numbers),
                    "special": draw.special,
                    "rule_projection": rule.definition.projection,
                    "rule_position": rule.definition.position,
                    "snapshot_price": rule.definition.expected_modal_odds,
                    "price_status": rule.definition.price_status,
                }
                decision_payload = decision.model_dump(mode="json")
                output_payload = settlement.model_dump(mode="json")
                partial = ResearchTrialEvent(
                    sequence=sequence,
                    experiment_id=protocol.experiment_id,
                    protocol_hash=protocol.protocol_hash,
                    protocol_artifact_sha256=protocol_artifact_sha256,
                    candidate_id=candidate.candidate_id,
                    rule_key=rule.definition.rule_key,
                    rule_hash=rule.rule_hash,
                    cost_model_id=protocol.spec.cost_model.cost_model_id,
                    payout_assumption_id=protocol.spec.payout_assumption_id,
                    fold_id=fold_ids[draw_index],
                    draw_index=draw_index,
                    source_expect=draw.source_expect,
                    open_time=draw.open_time,
                    source_verified=draw.source_verified,
                    input_payload=input_payload,
                    decision_payload=decision_payload,
                    output_payload=output_payload,
                    input_hash=hashlib.sha256(canonical_json_bytes(input_payload)).hexdigest(),
                    decision_hash=hashlib.sha256(canonical_json_bytes(decision_payload)).hexdigest(),
                    output_hash=hashlib.sha256(canonical_json_bytes(output_payload)).hexdigest(),
                    previous_hash=previous_hash,
                    event_hash=GENESIS_HASH,
                )
                event_hash = hashlib.sha256(canonical_json_bytes(_trial_event_material(partial))).hexdigest()
                event = partial.model_copy(update={"event_hash": event_hash})
                yield event
                previous_hash = event_hash
                sequence += 1


def _empty_cell_summary(candidate_id: str, rule_key: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "rule_key": rule_key,
        "draws": 0,
        "bets": 0,
        "wins": 0,
        "total_stake": Decimal("0"),
        "mechanics_gross_return_under_assumption": Decimal("0"),
        "mechanics_net_return_under_assumption": Decimal("0"),
    }


def write_research_trial_ledger(
    path: Path,
    *,
    protocol: ResearchProtocol,
    protocol_artifact_sha256: str,
    draws: tuple[Draw, ...],
    lineage: tuple[LineageRecord, ...],
    compiled_rules: tuple[CompiledExactRule, ...],
) -> dict[str, Any]:
    summaries = {
        (candidate.candidate_id, rule.definition.rule_key): _empty_cell_summary(
            candidate.candidate_id, rule.definition.rule_key
        )
        for candidate in protocol.spec.candidates
        for rule in compiled_rules
    }
    digest = hashlib.sha256()
    count = 0
    chain_tip = GENESIS_HASH
    with path.open("xb") as stream:
        for event in iter_research_trial_events(
            protocol=protocol,
            protocol_artifact_sha256=protocol_artifact_sha256,
            draws=draws,
            lineage=lineage,
            compiled_rules=compiled_rules,
        ):
            payload = canonical_json_bytes(event.model_dump(mode="json"))
            stream.write(payload)
            digest.update(payload)
            summary = summaries[(event.candidate_id, event.rule_key)]
            settlement = event.output_payload
            summary["draws"] += 1
            if settlement["outcome"] != "no_bet":
                summary["bets"] += 1
            if settlement["outcome"] == "win":
                summary["wins"] += 1
            summary["total_stake"] += Decimal(str(settlement["stake"]))
            summary["mechanics_gross_return_under_assumption"] += Decimal(str(settlement["gross_return"]))
            summary["mechanics_net_return_under_assumption"] += Decimal(str(settlement["net_return"]))
            count += 1
            chain_tip = event.event_hash
        stream.flush()
        os.fsync(stream.fileno())
    normalized_summaries = [
        {key: str(value) if isinstance(value, Decimal) else value for key, value in summary.items()}
        for summary in summaries.values()
    ]
    return {
        "schema_version": 1,
        "ranking_permitted": False,
        "candidate_selection_permitted": False,
        "economic_claim_status": "ECONOMIC_CLAIM_BLOCKED",
        "declared_cells": protocol.spec.declared_cell_budget,
        "completed_cells": len(summaries),
        "trial_rows": count,
        "ledger_sha256": digest.hexdigest(),
        "chain_tip": chain_tip,
        "summaries": normalized_summaries,
    }


def verify_research_trial_ledger(
    path: Path,
    *,
    protocol: ResearchProtocol,
    protocol_artifact_sha256: str,
    draws: tuple[Draw, ...],
    lineage: tuple[LineageRecord, ...],
    compiled_rules: tuple[CompiledExactRule, ...],
) -> dict[str, Any]:
    expected = iter_research_trial_events(
        protocol=protocol,
        protocol_artifact_sha256=protocol_artifact_sha256,
        draws=draws,
        lineage=lineage,
        compiled_rules=compiled_rules,
    )
    count = 0
    chain_tip = GENESIS_HASH
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f"blank trial ledger line: {line_number}")
            actual = ResearchTrialEvent.model_validate_json(line, strict=True)
            try:
                expected_event = next(expected)
            except StopIteration as error:
                raise ValueError("trial ledger contains undeclared extra rows") from error
            if actual != expected_event:
                raise ValueError(f"trial ledger event mismatch at sequence {line_number - 1}")
            count += 1
            chain_tip = actual.event_hash
    try:
        next(expected)
    except StopIteration:
        pass
    else:
        raise ValueError("trial ledger ended before the declared budget was exhausted")
    if count != protocol.spec.declared_trial_row_budget:
        raise ValueError("trial ledger count does not match the frozen budget")
    return {
        "trial_rows": count,
        "ledger_sha256": sha256_file(path),
        "chain_tip": chain_tip,
    }


def build_tombstones(protocol: ResearchProtocol) -> tuple[TombstoneRecord, ...]:
    definitions = (
        (
            "tombstone-economic-ranking-v1",
            "economic_candidate_ranking",
            ("payout_basis_unresolved", "historical_price_availability_unverified"),
        ),
        (
            "tombstone-historical-edge-v1",
            "historical_edge_claim",
            ("single_non_contemporaneous_snapshot", "source_truth_unverified"),
        ),
        (
            "tombstone-forward-liability-v1",
            "forward_market_or_liability_claim",
            ("contemporaneous_quote_fill_absent", "ticket_and_liability_absent"),
        ),
    )
    records: list[TombstoneRecord] = []
    for tombstone_id, subject, reason_codes in definitions:
        material = {
            "schema_version": 1,
            "experiment_id": protocol.experiment_id,
            "protocol_hash": protocol.protocol_hash,
            "tombstone_id": tombstone_id,
            "subject": subject,
            "status": "BLOCKED_BY_EVIDENCE",
            "reason_codes": reason_codes,
            "evidence_refs": (
                "research_protocol.json",
                "judge_gate.json",
                "p2_acceptance_pin.json",
            ),
        }
        records.append(
            TombstoneRecord(
                **material,  # type: ignore[arg-type]
                record_hash=hashlib.sha256(canonical_json_bytes(material)).hexdigest(),
            )
        )
    return tuple(records)


def tombstone_ledger_bytes(records: tuple[TombstoneRecord, ...]) -> bytes:
    for record in records:
        material = record.model_dump(mode="json")
        actual = material.pop("record_hash")
        if hashlib.sha256(canonical_json_bytes(material)).hexdigest() != actual:
            raise ValueError(f"tombstone hash mismatch: {record.tombstone_id}")
    return b"".join(canonical_json_bytes(record.model_dump(mode="json")) for record in records)


def build_judge_gate(
    *,
    protocol: ResearchProtocol,
    ledger_result: dict[str, Any],
    verified_ledger: dict[str, Any],
    cell_summary: dict[str, Any],
    future_suffix_decisions_unchanged: bool,
) -> JudgeGateResult:
    always_no_bet = [
        summary for summary in cell_summary["summaries"] if summary["candidate_id"] == "always_no_bet"
    ]
    always_no_bet_zero = len(always_no_bet) == 8 and all(
        summary["bets"] == 0
        and summary["wins"] == 0
        and summary["total_stake"] == "0"
        and summary["mechanics_gross_return_under_assumption"] == "0"
        and summary["mechanics_net_return_under_assumption"] == "0"
        for summary in always_no_bet
    )
    ledger_replayed_exactly = all(
        ledger_result[key] == verified_ledger[key] for key in ("trial_rows", "ledger_sha256", "chain_tip")
    )
    checks = {
        "protocol_hash_verified": True,
        "protocol_frozen_before_trials": True,
        "finite_candidate_set_exact": len(protocol.spec.candidates) == 4,
        "typed_rule_set_exact": len(protocol.spec.rules) == 8,
        "declared_budget_exhausted": ledger_result["trial_rows"] == protocol.spec.declared_trial_row_budget,
        "ledger_replayed_exactly": ledger_replayed_exactly,
        "all_declared_cells_completed": cell_summary["completed_cells"] == protocol.spec.declared_cell_budget,
        "always_no_bet_all_zero": always_no_bet_zero,
        "future_suffix_decisions_unchanged": future_suffix_decisions_unchanged,
    }
    return JudgeGateResult(
        experiment_id=protocol.experiment_id,
        protocol_hash=protocol.protocol_hash,
        expected_trial_rows=protocol.spec.declared_trial_row_budget,
        observed_trial_rows=int(ledger_result["trial_rows"]),
        declared_cells=protocol.spec.declared_cell_budget,
        completed_cells=int(cell_summary["completed_cells"]),
        trial_ledger_sha256=str(ledger_result["ledger_sha256"]),
        trial_chain_tip=str(ledger_result["chain_tip"]),
        checks=checks,
        economic_blockers=(
            "payout_basis_unresolved",
            "historical_price_availability_unverified",
            "contemporaneous_quote_fill_absent",
            "source_truth_unverified",
        ),
    )
