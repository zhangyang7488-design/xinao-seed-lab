from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from .inputs import InputLayout, canonical_json_bytes, sha256_file
from .models import (
    CompiledExactRule,
    ConformanceEvent,
    CostModel,
    Decision,
    Draw,
    ExactRuleBundle,
    ExactRuleDefinition,
    PlayStructureClassification,
    RuleResolution,
    Settlement,
)

FULL_V3_SOURCE = "盘口_全玩法赔率_full_v3_2026-05-12T11-12-34-765Z.json"
GENESIS_HASH = "0" * 64


def load_rule_bundle(path: Path) -> ExactRuleBundle:
    return ExactRuleBundle.model_validate_json(path.read_text(encoding="utf-8"), strict=True)


def rule_semantic_material(rule: ExactRuleDefinition) -> dict[str, Any]:
    return {
        "schema_version": rule.schema_version,
        "rule_revision": rule.rule_revision,
        "family": rule.family,
        "projection": rule.projection,
        "position": rule.position,
        "pid": rule.pid,
        "tid": rule.tid,
        "pan": rule.pan,
        "selection_domain": "1..49",
        "winning_condition": rule.winning_condition,
        "push_policy": rule.push_policy,
    }


def rule_semantic_hash(rule: ExactRuleDefinition) -> str:
    return hashlib.sha256(canonical_json_bytes(rule_semantic_material(rule))).hexdigest()


def _csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        fields = list(reader.fieldnames)
        rows = [{field: row.get(field, "") for field in fields} for row in reader]
    return fields, rows


def _verify_source_pins(bundle: ExactRuleBundle, layout: InputLayout) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    for pin in bundle.source_hashes:
        path = layout.root / Path(pin.relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"pinned catalog source missing: {path}")
        actual = sha256_file(path)
        if actual != pin.sha256:
            raise ValueError(
                "pinned catalog source hash mismatch: "
                f"{pin.relative_path} expected={pin.sha256} actual={actual}"
            )
        verified.append(
            {
                "relative_path": pin.relative_path,
                "size_bytes": path.stat().st_size,
                "sha256": actual,
            }
        )
    return verified


def _page_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            key = payload.get("canonical_key")
            if not isinstance(key, str) or not key:
                raise ValueError(f"odds page row {line_number} has no canonical_key")
            keys.add(key)
    return keys


def _quote_evidence(
    rule: ExactRuleDefinition,
    odds_rows: list[dict[str, str]],
    known_page_keys: set[str],
) -> dict[str, Any]:
    selected = [
        row
        for row in odds_rows
        if row.get("source_file") == FULL_V3_SOURCE
        and row.get("pid") == rule.pid
        and row.get("tid") == rule.tid
        and row.get("pan") == rule.pan
    ]
    if not selected:
        raise ValueError(f"no full_v3 quote rows for {rule.rule_key}")
    by_url: dict[str, list[dict[str, str]]] = {}
    for row in selected:
        by_url.setdefault(row.get("final_url", ""), []).append(row)
    if "" in by_url:
        raise ValueError(f"quote rows have empty final_url for {rule.rule_key}")

    pages: list[dict[str, Any]] = []
    for final_url, page_rows in sorted(by_url.items()):
        numeric: list[tuple[int, Decimal, dict[str, str]]] = []
        for row in page_rows:
            try:
                number = int(row.get("item", ""))
                odds = Decimal(row.get("odds", ""))
            except (ValueError, ArithmeticError):
                continue
            if 1 <= number <= 49:
                numeric.append((number, odds, row))
        counts = Counter(odds for _number, odds, _row in numeric)
        if not counts:
            raise ValueError(f"quote page has no numeric candidates: {final_url}")
        modal_odds, modal_count = min(counts.items(), key=lambda item: (-item[1], item[0]))
        accepted = [(number, row) for number, odds, row in numeric if odds == modal_odds]
        accepted_numbers = sorted(number for number, _row in accepted)
        if modal_count != 49 or accepted_numbers != list(range(1, 50)):
            raise ValueError(f"quote page does not provide one modal row for every exact number: {final_url}")
        if modal_odds != Decimal(rule.expected_modal_odds):
            raise ValueError(
                f"quote page modal mismatch for {rule.rule_key}: "
                f"expected={rule.expected_modal_odds} actual={modal_odds}"
            )
        accepted_ids = {id(row) for _number, row in accepted}
        rejected = [
            {"item": row.get("item", ""), "odds": row.get("odds", "")}
            for row in page_rows
            if id(row) not in accepted_ids
        ]
        parser_49_132 = sum(
            item["item"] == "49" and Decimal(item["odds"]) == Decimal("132")
            for item in rejected
            if item["odds"]
        )
        if parser_49_132 != 1:
            raise ValueError(f"expected one rejected 49->132 parser artifact on {final_url}")
        page_key_values = {row.get("page_key", "") for row in page_rows}
        if len(page_key_values) != 1 or "" in page_key_values:
            raise ValueError(f"quote page rows do not map to one page_key: {final_url}")
        page_key = next(iter(page_key_values))
        if page_key not in known_page_keys:
            raise ValueError(f"quote page_key has no page-level evidence: {page_key}")
        pages.append(
            {
                "page_key": page_key,
                "final_url": final_url,
                "numeric_candidate_count": len(numeric),
                "accepted_number_count": len(accepted),
                "accepted_numbers": accepted_numbers,
                "modal_odds": f"{modal_odds:.3f}",
                "rejected_candidates": rejected,
                "parser_artifact_49_to_132_count": parser_49_132,
            }
        )
    return {
        "status": "validated_snapshot_candidate",
        "price_status": rule.price_status,
        "source_truth_status": rule.source_truth_status,
        "source_file": FULL_V3_SOURCE,
        "page_count": len(pages),
        "accepted_number_count_per_page": 49,
        "modal_odds": rule.expected_modal_odds,
        "exact_number_49_status": "resolvable_at_modal_exact_number_price",
        "label_and_two_sided_49_policy_status": "UNRESOLVED",
        "pages": pages,
    }


def _classify_play_rows(
    play_rows: list[dict[str, str]], compiled_rules: tuple[CompiledExactRule, ...]
) -> tuple[PlayStructureClassification, ...]:
    by_identity = {
        (rule.definition.pid, rule.definition.tid, rule.definition.pan): rule for rule in compiled_rules
    }
    supported_pid_tid = {(pid, tid) for pid, tid, _pan in by_identity}
    classifications: list[PlayStructureClassification] = []
    for row_number, row in enumerate(play_rows, 2):
        identity = (row.get("pid", ""), row.get("tid", ""), row.get("pan", ""))
        rule = by_identity.get(identity)
        if rule is not None:
            classifications.append(
                PlayStructureClassification(
                    row_number=row_number,
                    play_id=row.get("play_id", ""),
                    pid=identity[0],
                    tid=identity[1],
                    pan=identity[2],
                    status="IMPLEMENTED",
                    rule_key=rule.definition.rule_key,
                    reason_code="exact_pid_tid_pan_maps_to_typed_projection",
                )
            )
            continue
        reason = (
            "unsupported_or_ambiguous_pan"
            if identity[:2] in supported_pid_tid
            else "unsupported_play_family_or_projection"
        )
        classifications.append(
            PlayStructureClassification(
                row_number=row_number,
                play_id=row.get("play_id", ""),
                pid=identity[0],
                tid=identity[1],
                pan=identity[2],
                status="UNRESOLVED",
                reason_code=reason,
            )
        )
    if len(classifications) != 136:
        raise ValueError(f"expected 136 classified play rows, got {len(classifications)}")
    return tuple(classifications)


def build_typed_rule_catalog(
    *,
    layout: InputLayout,
    rule_bundle_path: Path,
    snapshot_id: str,
) -> tuple[dict[str, Any], tuple[CompiledExactRule, ...], tuple[PlayStructureClassification, ...]]:
    bundle = load_rule_bundle(rule_bundle_path)
    if snapshot_id != bundle.source_snapshot_id:
        raise ValueError(
            f"rule bundle snapshot mismatch: expected={bundle.source_snapshot_id} actual={snapshot_id}"
        )
    verified_sources = _verify_source_pins(bundle, layout)
    _play_fields, play_rows = _csv_rows(layout.play_structure_csv)
    _odds_fields, odds_rows = _csv_rows(layout.odds_items_csv)
    if len(play_rows) != 136 or len(odds_rows) != 4_043:
        raise ValueError(f"catalog row-count drift: play={len(play_rows)} odds={len(odds_rows)}")
    known_page_keys = _page_keys(layout.odds_pages_jsonl)
    compiled_rules = tuple(
        CompiledExactRule(
            definition=rule,
            rule_hash=rule_semantic_hash(rule),
            quote_evidence=_quote_evidence(rule, odds_rows, known_page_keys),
        )
        for rule in bundle.rules
    )
    classifications = _classify_play_rows(play_rows, compiled_rules)
    implemented_count = sum(item.status == "IMPLEMENTED" for item in classifications)
    unresolved_count = len(classifications) - implemented_count
    bundle_payload = {
        "schema_version": 1,
        "bundle_id": bundle.bundle_id,
        "source_snapshot_id": bundle.source_snapshot_id,
        "source_definition": {
            "relative_path": rule_bundle_path.name,
            "sha256": sha256_file(rule_bundle_path),
        },
        "verified_source_hashes": verified_sources,
        "rules": [
            {
                "definition": rule.definition.model_dump(mode="json"),
                "semantic_material": rule_semantic_material(rule.definition),
                "rule_hash": rule.rule_hash,
                "quote_evidence": rule.quote_evidence,
            }
            for rule in compiled_rules
        ],
        "classification": {
            "source_row_count": len(classifications),
            "implemented_reference_rows": implemented_count,
            "unresolved_rows": unresolved_count,
            "default_status": "UNRESOLVED",
            "rows": [item.model_dump(mode="json") for item in classifications],
        },
        "hard_boundaries": [
            "only exact-number selections 1..49 compile",
            "source truth and payout basis remain unverified",
            "label, two-sided, combination, cash, rebate, and push semantics remain UNRESOLVED",
            "snapshot prices are candidates, not forward or historical quotes",
            "classification is coverage accounting, not full-market implementation",
        ],
    }
    return bundle_payload, compiled_rules, classifications


def resolve_exact_rule(
    compiled_rules: tuple[CompiledExactRule, ...],
    *,
    pid: str,
    tid: str,
    pan: str,
    selection: int | None,
    requested_mode: str = "exact_number",
) -> RuleResolution:
    if requested_mode != "exact_number":
        return RuleResolution(status="UNRESOLVED", reason_code="unsupported_or_ambiguous_mode")
    if selection is None or not 1 <= selection <= 49:
        return RuleResolution(status="UNRESOLVED", reason_code="selection_outside_exact_number_1_49")
    matching = [
        rule
        for rule in compiled_rules
        if (rule.definition.pid, rule.definition.tid, rule.definition.pan) == (pid, tid, pan)
    ]
    if len(matching) != 1:
        return RuleResolution(status="UNRESOLVED", reason_code="no_unique_typed_projection")
    rule = matching[0]
    return RuleResolution(
        status="IMPLEMENTED",
        rule_key=rule.definition.rule_key,
        rule_hash=rule.rule_hash,
        reason_code="typed_exact_projection_resolved",
    )


def settle_catalog_exact(
    decision: Decision,
    draw: Draw,
    rule: CompiledExactRule,
    cost: CostModel,
) -> Settlement:
    if not decision.place_bet:
        return Settlement(
            outcome="no_bet",
            stake=Decimal("0"),
            explicit_cost=Decimal("0"),
            gross_return=Decimal("0"),
            net_return=Decimal("0"),
        )
    selection = decision.selection
    if selection is None:
        raise ValueError("bet decision has no exact-number selection")
    definition = rule.definition
    if definition.projection == "special":
        won = selection == draw.special
    elif definition.projection == "regular_set":
        won = selection in draw.regular_numbers
    else:
        if definition.position is None:
            raise ValueError("regular-position rule has no position")
        won = selection == draw.regular_numbers[definition.position - 1]
    gross = Decimal(definition.expected_modal_odds) * cost.stake if won else Decimal("0")
    return Settlement(
        outcome="win" if won else "lose",
        stake=cost.stake,
        explicit_cost=cost.explicit_cost,
        gross_return=gross,
        net_return=gross - cost.stake - cost.explicit_cost,
    )


def _event_material(event: ConformanceEvent) -> dict[str, Any]:
    payload = event.model_dump(mode="json")
    payload.pop("event_hash")
    return payload


def _projected_winner(draw: Draw, rule: CompiledExactRule) -> int | tuple[int, ...]:
    definition = rule.definition
    if definition.projection == "special":
        return draw.special
    if definition.projection == "regular_set":
        return draw.regular_numbers
    if definition.position is None:
        raise ValueError("regular-position rule has no position")
    return draw.regular_numbers[definition.position - 1]


def build_conformance_events(
    draws: tuple[Draw, ...],
    compiled_rules: tuple[CompiledExactRule, ...],
    cost: CostModel,
) -> tuple[ConformanceEvent, ...]:
    if len(draws) < 3:
        raise ValueError("conformance ledger requires at least three draws")
    events: list[ConformanceEvent] = []
    previous_hash = GENESIS_HASH
    for rule in compiled_rules:
        winner = _projected_winner(draws[0], rule)
        winning_selection = winner[0] if isinstance(winner, tuple) else winner
        losing_draw = draws[1]
        losing_target = _projected_winner(losing_draw, rule)
        losing_set = set(losing_target) if isinstance(losing_target, tuple) else {losing_target}
        losing_selection = next(number for number in range(1, 50) if number not in losing_set)
        cases = (
            (
                "win",
                draws[0],
                Decision(place_bet=True, selection=winning_selection, information_cutoff_expect=None),
            ),
            (
                "lose",
                losing_draw,
                Decision(place_bet=True, selection=losing_selection, information_cutoff_expect=None),
            ),
            ("no-bet", draws[2], Decision(place_bet=False, selection=None, information_cutoff_expect=None)),
        )
        for expected_outcome, draw, decision in cases:
            settlement = settle_catalog_exact(decision, draw, rule, cost)
            normalized_outcome = "no_bet" if expected_outcome == "no-bet" else expected_outcome
            if settlement.outcome != normalized_outcome:
                raise RuntimeError(f"golden conformance case failed for {rule.definition.rule_key}")
            input_payload = {
                "source_expect": draw.source_expect,
                "source_verified": draw.source_verified,
                "regular_numbers": list(draw.regular_numbers),
                "special": draw.special,
                "decision": decision.model_dump(mode="json"),
                "snapshot_price": rule.definition.expected_modal_odds,
                "price_status": rule.definition.price_status,
                "payout_basis_status": "explicit_mechanics_assumption_not_source_truth",
            }
            output_payload = settlement.model_dump(mode="json")
            input_hash = hashlib.sha256(canonical_json_bytes(input_payload)).hexdigest()
            output_hash = hashlib.sha256(canonical_json_bytes(output_payload)).hexdigest()
            partial = ConformanceEvent(
                sequence=len(events),
                case_id=f"{rule.definition.rule_key}:{expected_outcome}",
                rule_key=rule.definition.rule_key,
                rule_hash=rule.rule_hash,
                cost_model_id=cost.cost_model_id,
                input_payload=input_payload,
                output_payload=output_payload,
                input_hash=input_hash,
                output_hash=output_hash,
                previous_hash=previous_hash,
                event_hash=GENESIS_HASH,
            )
            event_hash = hashlib.sha256(canonical_json_bytes(_event_material(partial))).hexdigest()
            event = partial.model_copy(update={"event_hash": event_hash})
            events.append(event)
            previous_hash = event_hash
    verify_conformance_events(tuple(events))
    return tuple(events)


def verify_conformance_events(events: tuple[ConformanceEvent, ...]) -> None:
    previous_hash = GENESIS_HASH
    for sequence, event in enumerate(events):
        if event.sequence != sequence or event.previous_hash != previous_hash:
            raise ValueError(f"conformance chain link mismatch at sequence {sequence}")
        if hashlib.sha256(canonical_json_bytes(event.input_payload)).hexdigest() != event.input_hash:
            raise ValueError(f"conformance input hash mismatch at sequence {sequence}")
        if hashlib.sha256(canonical_json_bytes(event.output_payload)).hexdigest() != event.output_hash:
            raise ValueError(f"conformance output hash mismatch at sequence {sequence}")
        expected_event_hash = hashlib.sha256(canonical_json_bytes(_event_material(event))).hexdigest()
        if expected_event_hash != event.event_hash:
            raise ValueError(f"conformance event hash mismatch at sequence {sequence}")
        previous_hash = event.event_hash


def conformance_ledger_bytes(events: tuple[ConformanceEvent, ...]) -> bytes:
    verify_conformance_events(events)
    return b"".join(canonical_json_bytes(event.model_dump(mode="json")) for event in events)
