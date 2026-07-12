from __future__ import annotations

import hashlib
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from typing import Any

from .inputs import canonical_json_bytes
from .models import (
    CandidateSpec,
    CostModel,
    Decision,
    DisplayedOddsQuote,
    Draw,
    LineageRecord,
    OddsQuote,
    ProjectionTrialRecord,
    RuleClaim,
    RuleSemantics,
    RuleVersion,
    Settlement,
    TrialRecord,
)


def build_rule(quote: OddsQuote) -> RuleVersion:
    material = {
        "schema_version": 1,
        "play_family": "special_number",
        "projection": "special",
        "outcome_space": "1..49",
        "winning_condition": "decision.selection == draw.special",
        "payout_basis": "inclusive_return",
        "push_policy": "not_applicable_for_exact_number",
        "quote_id": quote.quote_id,
    }
    digest = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    return RuleVersion(rule_id=f"special-number-a-{digest[:16]}", rule_hash=digest, quote_id=quote.quote_id)


def default_candidates() -> tuple[CandidateSpec, ...]:
    return (
        CandidateSpec(candidate_id="always_no_bet", kind="always_no_bet"),
        CandidateSpec(candidate_id="fixed_01", kind="fixed_number", fixed_number=1),
        CandidateSpec(candidate_id="previous_special", kind="previous_special"),
        CandidateSpec(candidate_id="rolling_mode_49", kind="rolling_mode", window=49),
    )


def decide(candidate: CandidateSpec, past_draws: tuple[Draw, ...]) -> Decision:
    cutoff = past_draws[-1].source_expect if past_draws else None
    if candidate.kind == "always_no_bet":
        return Decision(place_bet=False, selection=None, information_cutoff_expect=cutoff)
    if candidate.kind == "fixed_number":
        return Decision(place_bet=True, selection=candidate.fixed_number, information_cutoff_expect=cutoff)
    if candidate.kind == "previous_special":
        selection = past_draws[-1].special if past_draws else None
        return Decision(
            place_bet=selection is not None,
            selection=selection,
            information_cutoff_expect=cutoff,
        )
    if candidate.kind == "rolling_mode":
        window = candidate.window or 0
        if len(past_draws) < window:
            return Decision(place_bet=False, selection=None, information_cutoff_expect=cutoff)
        counts = Counter(draw.special for draw in past_draws[-window:])
        maximum = max(counts.values())
        selection = min(number for number, count in counts.items() if count == maximum)
        return Decision(place_bet=True, selection=selection, information_cutoff_expect=cutoff)
    raise ValueError(f"unsupported candidate kind: {candidate.kind}")


def settle(
    decision: Decision,
    draw: Draw,
    quote: OddsQuote,
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
    won = decision.selection == draw.special
    gross = quote.inclusive_return * cost.stake if won else Decimal("0")
    return Settlement(
        outcome="win" if won else "lose",
        stake=cost.stake,
        explicit_cost=cost.explicit_cost,
        gross_return=gross,
        net_return=gross - cost.stake - cost.explicit_cost,
    )


def build_trial_records(
    *,
    draws: tuple[Draw, ...],
    candidates: tuple[CandidateSpec, ...],
    quote: OddsQuote,
    rule: RuleVersion,
    cost: CostModel,
    snapshot_id: str,
) -> tuple[str, tuple[TrialRecord, ...]]:
    if len(candidates) > 4:
        raise ValueError("P1 candidate set must contain at most four fixed mechanics baselines")
    run_material: dict[str, Any] = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "quote": quote.model_dump(mode="json"),
        "rule": rule.model_dump(mode="json"),
        "cost": cost.model_dump(mode="json"),
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "draw_expect_order": [draw.source_expect for draw in draws],
    }
    run_key = "run-" + hashlib.sha256(canonical_json_bytes(run_material)).hexdigest()[:24]
    records: list[TrialRecord] = []
    for candidate in candidates:
        for index, draw in enumerate(draws):
            decision = decide(candidate, draws[:index])
            records.append(
                TrialRecord(
                    run_key=run_key,
                    snapshot_id=snapshot_id,
                    candidate_id=candidate.candidate_id,
                    draw_index=index,
                    source_expect=draw.source_expect,
                    source_verified=draw.source_verified,
                    draw_flags=draw.flags,
                    decision=decision,
                    actual_special=draw.special,
                    rule_id=rule.rule_id,
                    rule_hash=rule.rule_hash,
                    quote_id=quote.quote_id,
                    settlement=settle(decision, draw, quote, cost),
                )
            )
    return run_key, tuple(records)


def ledger_bytes(records: tuple[TrialRecord, ...]) -> bytes:
    return b"".join(canonical_json_bytes(record.model_dump(mode="json")) for record in records)


def summarize_candidates(
    records: tuple[TrialRecord, ...], candidates: tuple[CandidateSpec, ...], quote: OddsQuote
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for candidate in candidates:
        selected = [record for record in records if record.candidate_id == candidate.candidate_id]
        bets = [record for record in selected if record.decision.place_bet]
        wins = [record for record in bets if record.settlement.outcome == "win"]
        total_stake = sum((record.settlement.stake for record in selected), Decimal("0"))
        total_explicit_cost = sum((record.settlement.explicit_cost for record in selected), Decimal("0"))
        gross_return = sum((record.settlement.gross_return for record in selected), Decimal("0"))
        net_return = sum((record.settlement.net_return for record in selected), Decimal("0"))
        summaries.append(
            {
                "candidate": candidate.model_dump(mode="json"),
                "draws": len(selected),
                "bets": len(bets),
                "wins": len(wins),
                "hit_rate_when_betting": str(Decimal(len(wins)) / Decimal(len(bets))) if bets else None,
                "total_stake": str(total_stake),
                "total_explicit_cost": str(total_explicit_cost),
                "mechanics_gross_return_at_non_contemporaneous_price": str(gross_return),
                "mechanics_net_return_at_non_contemporaneous_price": str(net_return),
                "mechanics_return_on_stake_at_non_contemporaneous_price": (
                    str(gross_return / total_stake) if total_stake else None
                ),
                "theoretical_uniform_return_on_stake": str(quote.inclusive_return / Decimal(49))
                if bets
                else None,
                "claim_boundary": (
                    "mechanics accounting at a non-contemporaneous candidate price only; the totals are "
                    "not historical returns, an edge estimate, a ranking, or a recommendation"
                ),
            }
        )
    return {
        "schema_version": 1,
        "ranking_permitted": False,
        "inference_permitted": False,
        "selection_status": "fixed_before_p1_execution_not_statistical_preregistration",
        "price_status": "single_non_contemporaneous_candidate_snapshot",
        "summaries": summaries,
    }


def _build_semantics(
    *,
    play_family: str,
    projection: str,
    winning_condition: str,
) -> RuleSemantics:
    material = {
        "schema_version": 1,
        "play_family": play_family,
        "projection": projection,
        "selection_domain": "1..49",
        "winning_condition": winning_condition,
        "outcome_space": "no_bet|win|lose",
        "push_policy": "not_applicable_for_exact_number",
    }
    digest = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    return RuleSemantics(
        semantics_id=f"semantics-{play_family}-{digest[:16]}",
        semantics_hash=digest,
        play_family=play_family,  # type: ignore[arg-type]
        projection=projection,  # type: ignore[arg-type]
        winning_condition=winning_condition,  # type: ignore[arg-type]
    )


def build_special_semantics() -> RuleSemantics:
    return _build_semantics(
        play_family="special_number",
        projection="special",
        winning_condition="decision.selection == draw.special",
    )


def build_regular_semantics() -> RuleSemantics:
    return _build_semantics(
        play_family="regular_number",
        projection="regular_set",
        winning_condition="decision.selection in draw.regular_numbers",
    )


def p2_rule_claims(
    *, regular_semantics: RuleSemantics, special_semantics: RuleSemantics
) -> tuple[RuleClaim, ...]:
    return (
        RuleClaim(
            claim_id="claim-special-exact-spec-pinned-v1",
            subject="special_exact_membership",
            status="spec_pinned_mechanics_candidate",
            semantics_hash=special_semantics.semantics_hash,
            assumption_id="mainline-spec-special-position-v1",
            reason_code="project_spec_pins_seventh_position_as_special",
            evidence_refs=("docs/P1_SPEC.md", "input:history_jsonl"),
        ),
        RuleClaim(
            claim_id="claim-regular-set-spec-pinned-v1",
            subject="regular_set_membership",
            status="spec_pinned_mechanics_candidate",
            semantics_hash=regular_semantics.semantics_hash,
            assumption_id="mainline-spec-regular-set-membership-v1",
            reason_code="project_spec_pins_first_six_as_regular_set",
            evidence_refs=("docs/P2_SPEC.md", "input:history_jsonl"),
        ),
        RuleClaim(
            claim_id="claim-payout-basis-unresolved-v1",
            subject="payout_basis",
            status="unresolved",
            assumption_id="mechanics-assumption-inclusive-return-v1",
            reason_code="packet_displays_odds_but_does_not_define_inclusive_return_or_net_win",
            evidence_refs=("input:odds_snapshot_pages_v1.jsonl", "input:full_v3_raw"),
        ),
        RuleClaim(
            claim_id="claim-special-two-sided-49-unresolved-v1",
            subject="special_two_sided_49_policy",
            status="unresolved",
            reason_code="packet_has_prices_but_no_49_win_lose_push_void_or_refund_rule",
            evidence_refs=("input:odds_snapshot_pages_v1.jsonl", "mainline:rule_gap_register"),
        ),
    )


def compile_rule_claim(claim: RuleClaim, semantics: RuleSemantics) -> RuleSemantics:
    if claim.status != "spec_pinned_mechanics_candidate":
        raise ValueError(f"rule claim is not executable: {claim.claim_id}:{claim.reason_code}")
    if claim.semantics_hash != semantics.semantics_hash:
        raise ValueError("rule claim semantics hash does not match the compiled semantics")
    return semantics


def p2_default_candidates() -> tuple[CandidateSpec, ...]:
    return (
        CandidateSpec(candidate_id="always_no_bet", kind="always_no_bet"),
        CandidateSpec(candidate_id="fixed_01", kind="fixed_number", fixed_number=1),
    )


def settle_regular_exact(
    decision: Decision,
    draw: Draw,
    quote: DisplayedOddsQuote,
    cost: CostModel,
    *,
    semantics: RuleSemantics,
    claim: RuleClaim,
    payout_assumption_id: str,
) -> Settlement:
    compile_rule_claim(claim, semantics)
    if semantics.projection != "regular_set":
        raise ValueError("regular exact settlement requires regular_set semantics")
    if payout_assumption_id != "mechanics-assumption-inclusive-return-v1":
        raise ValueError("P2 supports only the explicitly named mechanics payout assumption")
    if not decision.place_bet:
        return Settlement(
            outcome="no_bet",
            stake=Decimal("0"),
            explicit_cost=Decimal("0"),
            gross_return=Decimal("0"),
            net_return=Decimal("0"),
        )
    won = decision.selection in draw.regular_numbers
    gross = quote.displayed_odds * cost.stake if won else Decimal("0")
    return Settlement(
        outcome="win" if won else "lose",
        stake=cost.stake,
        explicit_cost=cost.explicit_cost,
        gross_return=gross,
        net_return=gross - cost.stake - cost.explicit_cost,
    )


def build_regular_trial_records(
    *,
    draws: tuple[Draw, ...],
    lineage: tuple[LineageRecord, ...],
    candidates: tuple[CandidateSpec, ...],
    quote: DisplayedOddsQuote,
    semantics: RuleSemantics,
    claim: RuleClaim,
    cost: CostModel,
    snapshot_id: str,
    payout_assumption_id: str = "mechanics-assumption-inclusive-return-v1",
) -> tuple[str, tuple[ProjectionTrialRecord, ...]]:
    if len(candidates) > 4:
        raise ValueError("P2 candidate set must contain at most four fixed mechanics baselines")
    compile_rule_claim(claim, semantics)
    lineage_by_expect = {record.source_expect: record for record in lineage if record.status == "canonical"}
    missing = [draw.source_expect for draw in draws if draw.source_expect not in lineage_by_expect]
    if missing:
        raise ValueError(f"usable draws are missing canonical lineage records: {missing[:10]}")
    run_material: dict[str, Any] = {
        "schema_version": 2,
        "snapshot_id": snapshot_id,
        "quote": quote.model_dump(mode="json"),
        "semantics": semantics.model_dump(mode="json"),
        "claim": claim.model_dump(mode="json"),
        "cost": cost.model_dump(mode="json"),
        "payout_assumption_id": payout_assumption_id,
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "draw_expect_order": [draw.source_expect for draw in draws],
    }
    run_key = "run-p2-" + hashlib.sha256(canonical_json_bytes(run_material)).hexdigest()[:24]
    records: list[ProjectionTrialRecord] = []
    for candidate in candidates:
        for index, draw in enumerate(draws):
            decision = decide(candidate, draws[:index])
            records.append(
                ProjectionTrialRecord(
                    run_key=run_key,
                    snapshot_id=snapshot_id,
                    candidate_id=candidate.candidate_id,
                    draw_index=index,
                    source_expect=draw.source_expect,
                    source_verified=draw.source_verified,
                    lineage_reason_code=lineage_by_expect[draw.source_expect].reason_code,
                    decision=decision,
                    actual_regular_set=tuple(sorted(draw.regular_numbers)),  # type: ignore[arg-type]
                    actual_special=draw.special,
                    semantics_id=semantics.semantics_id,
                    semantics_hash=semantics.semantics_hash,
                    rule_claim_id=claim.claim_id,
                    quote_id=quote.quote_id,
                    payout_assumption_id=payout_assumption_id,
                    settlement=settle_regular_exact(
                        decision,
                        draw,
                        quote,
                        cost,
                        semantics=semantics,
                        claim=claim,
                        payout_assumption_id=payout_assumption_id,
                    ),
                )
            )
    return run_key, tuple(records)


def projection_ledger_bytes(records: tuple[ProjectionTrialRecord, ...]) -> bytes:
    return b"".join(canonical_json_bytes(record.model_dump(mode="json")) for record in records)


def p2_decision_trace_bytes(
    draws: tuple[Draw, ...], candidates: tuple[CandidateSpec, ...], *, through_index: int | None = None
) -> bytes:
    limit = len(draws) if through_index is None else min(len(draws), through_index)
    rows = []
    for candidate in candidates:
        for index in range(limit):
            rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "draw_index": index,
                    "source_expect": draws[index].source_expect,
                    "decision": decide(candidate, draws[:index]).model_dump(mode="json"),
                }
            )
    return b"".join(canonical_json_bytes(row) for row in rows)


def regular_mechanics_fractions(quote: DisplayedOddsQuote) -> dict[str, Fraction]:
    probability = Fraction(6, 49)
    displayed = Fraction(quote.displayed_odds)
    rtp = displayed * probability
    return {
        "uniform_hit_probability": probability,
        "mechanics_rtp_under_inclusive_return_assumption": rtp,
        "mechanics_net_expectation_under_inclusive_return_assumption": rtp - 1,
    }
