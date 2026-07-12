from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from xinao_market_lab.catalog import load_rule_bundle, rule_semantic_hash
from xinao_market_lab.inputs import canonical_json_bytes
from xinao_market_lab.models import (
    CompiledExactRule,
    CostModel,
    Draw,
    JudgeGateResult,
    LineageRecord,
    P2EvidencePin,
)
from xinao_market_lab.research import (
    build_judge_gate,
    build_research_protocol,
    build_tombstones,
    tombstone_ledger_bytes,
    validate_research_protocol,
    verify_research_trial_ledger,
    write_research_trial_ledger,
)

RULE_BUNDLE = Path(__file__).parents[1] / "rules" / "p2_rule_bundle_v1.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_draw(index: int) -> Draw:
    numbers = tuple(((index * 7 + offset) % 49) + 1 for offset in range(7))
    return Draw(
        series_id="macaujc2_daily_2132_type8",
        source_expect=f"2026{index + 1:03d}",
        open_time=datetime(2026, 1, index + 1, 21, 32, 32, tzinfo=SHANGHAI),
        regular_numbers=numbers[:6],  # type: ignore[arg-type]
        special=numbers[6],
        wave=("red", "blue", "green", "red", "blue", "green", "red"),
        zodiac=("鼠", "牛", "虎", "兔", "龍", "蛇", "馬"),
        source_verified=False,
    )


def fixture_objects():
    draws = tuple(make_draw(index) for index in range(8))
    lineage = tuple(
        LineageRecord(
            source_index=index,
            source_expect=draw.source_expect,
            open_time=draw.open_time,
            outcome_sha256=hashlib.sha256(str(index).encode()).hexdigest(),
            source_verified=False,
            source_flags=(),
            status="canonical",
            canonical_expect=draw.source_expect,
            reason_code="canonical_unique",
        )
        for index, draw in enumerate(draws)
    )
    definitions = load_rule_bundle(RULE_BUNDLE).rules
    compiled = tuple(
        CompiledExactRule(
            definition=definition,
            rule_hash=rule_semantic_hash(definition),
            quote_evidence={},
        )
        for definition in definitions
    )
    p2_pin = P2EvidencePin(
        run_directory="D:/fixture/p2",
        input_snapshot_id="a" * 64,
        checks_sha256="b" * 64,
        rule_catalog_sha256="c" * 64,
        conformance_ledger_sha256="d" * 64,
        conformance_chain_tip="e" * 64,
        status="verified_rule_catalog_pure_settle_with_lineage_v2",
    )
    protocol = build_research_protocol(
        draws=draws,
        compiled_rules=compiled,
        cost=CostModel(),
        snapshot_id="a" * 64,
        p2_evidence=p2_pin,
    )
    return draws, lineage, compiled, protocol


def test_protocol_freezes_exact_cartesian_surface_and_event_time_folds() -> None:
    draws, _lineage, compiled, protocol = fixture_objects()
    validate_research_protocol(protocol, draws=draws, compiled_rules=compiled)
    assert [candidate.candidate_id for candidate in protocol.spec.candidates] == [
        "always_no_bet",
        "fixed_01",
        "previous_special",
        "rolling_mode_49",
    ]
    assert len(protocol.spec.rules) == 8
    assert protocol.spec.declared_cell_budget == 32
    assert protocol.spec.declared_trial_row_budget == 256
    assert [(fold.start_index, fold.end_index_exclusive) for fold in protocol.spec.folds] == [
        (0, 2),
        (2, 4),
        (4, 6),
        (6, 8),
    ]
    assert protocol.spec.ranking_permitted is False
    assert protocol.spec.economic_claim_permitted is False


def test_trial_ledger_semantically_replays_and_rejects_rechained_decision_tampering(
    tmp_path: Path,
) -> None:
    draws, lineage, compiled, protocol = fixture_objects()
    protocol_path = tmp_path / "research_protocol.json"
    protocol_path.write_bytes(canonical_json_bytes(protocol.model_dump(mode="json")))
    protocol_artifact_sha256 = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    ledger_path = tmp_path / "trials.jsonl"
    result = write_research_trial_ledger(
        ledger_path,
        protocol=protocol,
        protocol_artifact_sha256=protocol_artifact_sha256,
        draws=draws,
        lineage=lineage,
        compiled_rules=compiled,
    )
    replay = verify_research_trial_ledger(
        ledger_path,
        protocol=protocol,
        protocol_artifact_sha256=protocol_artifact_sha256,
        draws=draws,
        lineage=lineage,
        compiled_rules=compiled,
    )
    assert result["trial_rows"] == replay["trial_rows"] == 256
    assert result["ledger_sha256"] == replay["ledger_sha256"]
    assert len(result["summaries"]) == 32

    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    rows[8]["decision_payload"] = {
        "place_bet": True,
        "selection": 49,
        "information_cutoff_expect": None,
    }
    rows[8]["decision_hash"] = hashlib.sha256(canonical_json_bytes(rows[8]["decision_payload"])).hexdigest()
    previous_hash = "0" * 64
    for row in rows:
        row["previous_hash"] = previous_hash
        material = dict(row)
        material.pop("event_hash")
        row["event_hash"] = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
        previous_hash = row["event_hash"]
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    with pytest.raises(ValueError, match="event mismatch"):
        verify_research_trial_ledger(
            tampered,
            protocol=protocol,
            protocol_artifact_sha256=protocol_artifact_sha256,
            draws=draws,
            lineage=lineage,
            compiled_rules=compiled,
        )


def test_judge_accepts_mechanics_but_schema_blocks_economic_claims(tmp_path: Path) -> None:
    draws, lineage, compiled, protocol = fixture_objects()
    protocol_bytes = canonical_json_bytes(protocol.model_dump(mode="json"))
    protocol_sha = hashlib.sha256(protocol_bytes).hexdigest()
    ledger = tmp_path / "trials.jsonl"
    result = write_research_trial_ledger(
        ledger,
        protocol=protocol,
        protocol_artifact_sha256=protocol_sha,
        draws=draws,
        lineage=lineage,
        compiled_rules=compiled,
    )
    replay = verify_research_trial_ledger(
        ledger,
        protocol=protocol,
        protocol_artifact_sha256=protocol_sha,
        draws=draws,
        lineage=lineage,
        compiled_rules=compiled,
    )
    judge = build_judge_gate(
        protocol=protocol,
        ledger_result=result,
        verified_ledger=replay,
        cell_summary=result,
        future_suffix_decisions_unchanged=True,
    )
    assert judge.mechanics_status == "MECHANICS_ACCEPTED"
    assert judge.economic_claim_status == "ECONOMIC_CLAIM_BLOCKED"
    assert judge.completed_cells == 32
    assert all(judge.checks.values())

    invalid = judge.model_dump(mode="python")
    invalid["ranking_permitted"] = True
    with pytest.raises(ValidationError):
        JudgeGateResult.model_validate(invalid, strict=True)


def test_blocked_claim_tombstones_are_nonempty_hashed_and_reproducible() -> None:
    _draws, _lineage, _compiled, protocol = fixture_objects()
    first = tombstone_ledger_bytes(build_tombstones(protocol))
    second = tombstone_ledger_bytes(build_tombstones(protocol))
    assert first == second
    assert len(first.splitlines()) == 3
    assert b"economic_candidate_ranking" in first
    assert b"historical_edge_claim" in first
    assert b"forward_market_or_liability_claim" in first
